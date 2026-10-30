#!/usr/bin/env python3
"""Offline tests for the no-argument, production-safe laptop entry point.

The fake platform below is an orchestration model, not a replacement for live
ServiceNow acceptance. No test reads credentials or contacts an instance.
"""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ci_identifier_precedence as runner
import test_dti_production_runner as contract
from test_dti_production_runner import (
    ALERT, CALLER, DECOY, EXPECTED, FOREIGN, GROUP, INCIDENT,
    Clock, ManifestModelClient, StrictClient, complete_catalog, settings,
)


def make_model(fixtures=None, hidden_fields=()):
    """Visit real runner callbacks while materializing expected stored rows."""
    class ModelRunner(runner.LaptopProductionRunner):
        def snapshot(self, case, deadline):
            self.client.materialize(case)
            return super().snapshot(case, deadline)

    clock, client = Clock(), ManifestModelClient()
    suite = ModelRunner(client, settings(), fixtures if fixtures is not None else {},
                        clock.monotonic, clock.sleep)
    client.suite = suite
    # Seed readable values independently of the supplied optional catalog. It is
    # important not to replace partial fixtures with a complete one in this helper.
    fields = {
        "em_event": set(suite.EVENT_FIELDS.split(",")),
        "em_alert": set(suite.ALERT_FIELDS.split(",")),
        "incident": set(suite.INCIDENT_FIELDS.split(",")),
    }
    fields["incident"].update(("u_generating_alert", "u_netcool_ticket", "contact_type", "location", "watch_list",
                               "work_notes", "close_code", "close_notes", "u_cause", "assigned_to",
                               "business_service", "service_offering"))
    fields["em_alert"].add("work_notes")
    for fixture in complete_catalog()["advanced_cases"].values():
        for member in fixture if isinstance(fixture, list) else [fixture]:
            fields["incident"].update(member.get("expected_incident", {}))
            fields["em_event"].update(member.get("expected_event", {}))
    for index, (table, names) in enumerate(fields.items()):
        client.tables[table] = [{**dict.fromkeys(names, ""), "sys_id": format(900 + index, "032x")}]
    client.hidden_fields.update(hidden_fields)
    return suite, client, clock


def features(report):
    return {feature["name"]: feature for feature in report["features"]}


class LaptopPartialFixtureTests(unittest.TestCase):
    def test_complete_catalog_visits_all_85_callbacks_without_expanding_access(self):
        suite, client, _clock = make_model(complete_catalog())
        report = suite.run()
        self.assertEqual(len(report["manifest"]), 85)
        self.assertEqual(set(features(report)), set(report["manifest"]))
        self.assertEqual(len(report["features"]), 85)
        self.assertEqual(report["counts"]["skip"], 0, report["features"])
        self.assertEqual(report["counts"]["fail"], 0, report["features"])
        self.assertEqual(report["counts"]["error"], 0, report["features"])
        self.assertEqual(report["counts"]["known_limitation"], 1)
        self.assertEqual(report["status"], "complete_with_known_limitations")
        self.assertEqual({query[0] for query in client.queries}, StrictClient.TABLES)
        self.assertEqual({request[0] for request in client.requests}, {"GET", "PATCH"})
        self.assertGreater(len(client.pushes), 80)
        self.assertGreaterEqual(len(client.probes), 10)
        self.assertEqual(report["post_retries"], 0)
        self.assertTrue(report["records_retained"])
        self.assertTrue(all(not item["attachment_bytes_verified"] for item in report["debug_observations"]))

    def test_empty_optional_catalog_runs_core_and_reports_untested_branches_incomplete(self):
        suite, client, _clock = make_model({})
        report = suite.run()
        by_name = features(report)
        self.assertEqual(len(by_name), 85)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(by_name["read_preflight"]["status"], "pass")
        self.assertEqual(by_name["name_only_control"]["status"], "pass")
        self.assertEqual(by_name["identifier_only_control"]["status"], "pass")
        for name in ("fast_snake_conflict", "fast_camel_conflict", "terminal_6", "foreign_incident_guard", "closed_alert_guard"):
            with self.subTest(name=name):
                self.assertEqual(by_name[name]["status"], "pass", by_name[name])
        self.assertEqual(by_name["service_sysid"]["status"], "skip")
        self.assertEqual(by_name["custom_incident_fields"]["status"], "skip")
        self.assertGreater(report["counts"]["pass"], 40)
        self.assertEqual(report["counts"]["error"], 0, report["features"])
        self.assertEqual(report["counts"]["fail"], 0, report["features"])
        self.assertGreater(len(client.pushes), 30)

    def test_unfilled_template_never_sends_placeholder_payloads(self):
        catalog = json.loads(Path(__file__).with_name("production-fixtures.example.json").read_text())
        suite, client, _clock = make_model(catalog)
        report = suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(features(report)["name_only_control"]["status"], "pass")
        self.assertTrue(client.pushes)
        serialized = json.dumps(client.pushes)
        self.assertNotIn("REPLACE_WITH", serialized.upper())
        self.assertNotIn("u_replace_with_existing_test_field", serialized)

    def test_one_missing_optional_reference_does_not_stop_unrelated_checks(self):
        catalog = complete_catalog()
        catalog.pop("assignee_sys_id")
        suite, client, _clock = make_model(catalog)
        report = suite.run()
        by_name = features(report)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(by_name["caller_assignee_sysid"]["status"], "skip")
        self.assertEqual(by_name["caller_assignee_name"]["status"], "skip")
        for name in ("group_name", "service_sysid", "node_fallback", "terminal_8"):
            with self.subTest(name=name):
                self.assertEqual(by_name[name]["status"], "pass", by_name[name])
        self.assertTrue(client.pushes)

    def test_missing_owner_attestation_skips_only_its_observable_branch(self):
        catalog = complete_catalog()
        catalog["production_attestations"]["car_id"] = False
        suite, _client, _clock = make_model(catalog)
        report = suite.run()
        by_name = features(report)
        self.assertEqual(by_name["car_id"]["status"], "skip")
        self.assertEqual(by_name["canonical_ci_name"]["status"], "pass")
        self.assertEqual(by_name["fast_snake_conflict"]["status"], "pass")
        self.assertEqual(report["status"], "incomplete")

    def test_unavailable_optional_custom_fields_do_not_poison_core_preflight(self):
        suite, _client, _clock = make_model(complete_catalog(),
            hidden_fields=("u_generating_alert", "u_netcool_ticket", "u_usb_em_test_value"))
        report = suite.run()
        by_name = features(report)
        self.assertEqual(by_name["read_preflight"]["status"], "pass")
        self.assertEqual(by_name["fast_camel_conflict"]["status"], "pass")
        self.assertEqual(by_name["terminal_6"]["status"], "pass")
        for name in ("generating_alert_reference", "netcool_ticket_default", "custom_incident_fields"):
            with self.subTest(name=name):
                self.assertEqual(by_name[name]["status"], "skip", by_name[name])
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["counts"]["error"], 0, report["features"])
        self.assertEqual(report["counts"]["fail"], 0, report["features"])

    def test_bad_advanced_fixture_is_skipped_before_its_first_event_not_global_stop(self):
        catalog = complete_catalog()
        catalog["advanced_cases"]["node_fallback"]["expected_incident"]["cmdb_ci"] = "REPLACE_WITH_CI_SYS_ID"
        suite, client, _clock = make_model(catalog)
        report = suite.run()
        by_name = features(report)
        self.assertEqual(by_name["node_fallback"]["status"], "skip")
        self.assertEqual(by_name["resource_resolution"]["status"], "pass")
        self.assertEqual(by_name["terminal_6"]["status"], "pass")
        self.assertNotIn("REPLACE_WITH", json.dumps(client.pushes))
        self.assertFalse(any(case["feature"] == "node_fallback" for case in report["cases"]))

    def test_current_run_lifecycle_guard_remains_enforced(self):
        suite, client, _clock = make_model(complete_catalog())
        with self.assertRaises(runner.CheckFailed):
            suite.patch_owned("incident", FOREIGN, {"state": "6"})
        self.assertFalse(client.requests)
        with self.assertRaises(ValueError):
            suite.query("sys_user", "sys_id=" + CALLER, "sys_id")
        self.assertFalse(client.queries)

    def test_baseline_field_acl_failure_still_stops_all_event_writes(self):
        suite, client, _clock = make_model(complete_catalog(), hidden_fields=("caller_id",))
        report = suite.run()
        self.assertEqual(features(report)["read_preflight"]["status"], "skip")
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(client.pushes)
        self.assertFalse(client.probes)

    def test_malformed_optional_severity_branch_is_skipped_before_its_event(self):
        catalog = complete_catalog()
        catalog["severity_map"] = {"1": ["2", "2"], "2": ["2", "2"], "3": ["3", "3"], "4": ["4", "4"], "0": None}
        suite, _client, _clock = make_model(catalog)
        report = suite.run()
        self.assertEqual(features(report)["severity_0"]["status"], "skip")
        self.assertEqual(features(report)["severity_1"]["status"], "pass")
        self.assertEqual(features(report)["terminal_6"]["status"], "pass")
        self.assertFalse(any(case["feature"] == "severity_0" for case in report["cases"]))
        self.assertEqual(report["status"], "incomplete")

    def test_malformed_severity_map_does_not_stop_other_functionality(self):
        catalog = complete_catalog()
        catalog["severity_map"] = []
        suite, _client, _clock = make_model(catalog)
        report = suite.run()
        for severity in ("1", "2", "3", "4", "0", "5", "clear", "OK"):
            self.assertEqual(features(report)["severity_" + severity]["status"], "skip")
        self.assertEqual(features(report)["fast_snake_conflict"]["status"], "pass")
        self.assertEqual(features(report)["terminal_8"]["status"], "pass")
        self.assertEqual(report["counts"]["error"], 0)
        self.assertEqual(report["counts"]["fail"], 0)

    def test_placeholder_terminal_cause_is_never_posted_or_patched(self):
        catalog = complete_catalog()
        catalog["terminal_extra_fields"] = {"u_cause": "REPLACE_WITH_CAUSE"}
        suite, client, _clock = make_model(catalog)
        report = suite.run()
        for state in ("6", "7", "8"):
            self.assertEqual(features(report)["terminal_" + state]["status"], "skip")
        self.assertEqual(features(report)["closed_alert_guard"]["status"], "pass")
        self.assertNotIn("REPLACE_WITH", json.dumps(client.pushes + client.requests))

    def test_hyphenated_baseline_placeholder_stops_before_first_event(self):
        suite, client, _clock = make_model(complete_catalog())
        suite.settings.category = "replace-with-valid-category-stored-value"
        report = suite.run()
        self.assertEqual(features(report)["read_preflight"]["status"], "skip")
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(client.pushes)
        self.assertFalse(client.probes)
        self.assertFalse(any(method == "PATCH" for method, _path, _body, _timeout in client.requests))

    def test_malformed_terminal_extra_fields_skip_only_lifecycle_without_mutating_input(self):
        for malformed in ([], "not an object", {"caller_id": CALLER}, {"u_cause": []}):
            with self.subTest(malformed=malformed):
                catalog = complete_catalog()
                catalog["terminal_extra_fields"] = malformed
                original = copy.deepcopy(catalog)
                suite, client, _clock = make_model(catalog)
                report = suite.run()
                self.assertEqual(catalog, original)
                for state in ("6", "7", "8"):
                    self.assertEqual(features(report)["terminal_" + state]["status"], "skip")
                self.assertEqual(features(report)["fast_camel_conflict"]["status"], "pass")
                self.assertEqual(features(report)["foreign_incident_guard"]["status"], "pass")
                self.assertEqual(report["counts"]["fail"], 0)
                self.assertEqual(report["counts"]["error"], 0)
                self.assertFalse(any(case["feature"].startswith("terminal_") for case in report["cases"]))
                self.assertFalse(any(method == "PATCH" and "/incident/" in path for method, path, _body, _timeout in client.requests))


class LaptopNoArgumentTests(unittest.TestCase):
    @staticmethod
    def local_files(directory, values=None, fixture=None, fixture_name="dev-fixtures.json"):
        configured = {
            "USBEM_DEV_URL": "https://offline-dev.service-now.com",
            "USBEM_IT_URL": "https://offline-it.service-now.com",
            "USBEM_UAT_URL": "https://offline-uat.service-now.com",
            "USBEM_PROD_URL": "https://offline-prod.service-now.com",
            "SN_INSTANCE_URL": "https://offline-global.service-now.com",
            "SN_USERNAME": "offline-file-user",
            "SN_PASSWORD": "offline-file-password",
            "USBEM_DEV_PASSWORD": "offline-dev-file-password",
            "USBEM_CI_TYPE": "cmdb_ci_server",
            "USBEM_CI_IDENTIFIER_JSON": '{"serial_number":"offline-serial"}',
            "USBEM_EXPECTED_CI_SYS_ID": EXPECTED,
            "USBEM_DECOY_CI_NAME": "offline-decoy",
            "USBEM_DECOY_CI_SYS_ID": DECOY,
            "USBEM_ASSIGNMENT_GROUP": GROUP,
            "USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID": GROUP,
            "USBEM_TEST_CALLER_SYS_ID": CALLER,
            "USBEM_TEST_CATEGORY": "hardware",
            "USBEM_EXPECTED_CATEGORY": "hardware",
            "USBEM_TEST_SUBCATEGORY": "cpu",
            "USBEM_EXPECTED_SUBCATEGORY": "cpu",
        }
        configured.update(values or {})
        script = directory / "test_ci_identifier_precedence.py"
        script.write_bytes(b"# offline-only sentinel: this file must not change\n")
        env = directory / "production_test.env"
        env.write_text("\n".join(key + "=" + value for key, value in configured.items()) + "\n")
        catalog = directory / fixture_name
        catalog.write_text(json.dumps({} if fixture is None else fixture))
        return script, env, catalog

    @staticmethod
    def fake_report(status="incomplete"):
        return {"status": status, "run_id": "offline-only", "features": [
            {"name": "read_preflight", "status": "pass"},
            {"name": "car_id", "status": "skip", "reason": "missing owner-supplied fixture"}],
            "counts": {"pass": 1, "skip": 1, "fail": 0, "error": 0, "known_limitation": 0},
            "cases": [{"offline_model_only": True, "large_field": "x" * 12000}]}

    def run_local(self, directory, values=None, fixture=None, fixture_name="dev-fixtures.json", status="incomplete"):
        script, env, catalog = self.local_files(directory, values, fixture, fixture_name)
        originals = {path: path.read_bytes() for path in (script, env, catalog)}
        process_overrides = {
            "SN_INSTANCE_URL": "https://process-must-never-win.service-now.com",
            "USBEM_DEV_URL": "https://process-must-never-win.service-now.com",
            "SN_USERNAME": "process-must-never-win-user",
            "SN_PASSWORD": "process-must-never-win-password",
            "USBEM_DEV_PASSWORD": "process-must-never-win-dev-password",
            "USBEM_EXPECTED_CI_SYS_ID": "f" * 32,
            "USBEM_CA_BUNDLE": "/process/must/not/win.pem",
        }
        with patch.object(runner, "__file__", str(script)), patch.dict(runner.os.environ, process_overrides), \
                patch.object(runner, "ProductionClient") as client, patch.object(runner, "Client") as broad, \
                patch.object(runner, "LaptopProductionRunner") as suite, \
                patch.object(runner, "DevFixtureProvisioner") as provisioner, \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            client.return_value.operation_counts = {}
            suite.return_value.run.return_value = self.fake_report(status)
            code = runner.run_laptop()
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        broad.assert_not_called()
        provisioner.assert_not_called()
        return code, output.getvalue(), errors.getvalue(), client, suite

    def test_no_arguments_dispatch_to_easy_launcher(self):
        with patch.object(sys, "argv", ["test_ci_identifier_precedence.py"]), \
                patch.object(runner, "run_laptop", return_value=4) as launch:
            self.assertEqual(runner.main(), 4)
        launch.assert_called_once_with()

    def test_file_directory_not_working_directory_and_process_values_never_override(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            code, output, errors, client, suite = self.run_local(directory)
            self.assertEqual(code, 4)
            self.assertEqual(client.call_count, 1, "must never loop over all configured targets")
            self.assertEqual(suite.call_count, 1)
            instance, auth = client.call_args.args[:2]
            self.assertEqual(instance, "https://offline-dev.service-now.com")
            self.assertEqual(auth, {"mode": "basic", "username": "offline-file-user", "password": "offline-dev-file-password"})
            self.assertEqual(client.call_args.args[2:], ("", False))
            self.assertEqual(suite.call_args.args[1].expected_id, EXPECTED)
            self.assertEqual(suite.call_args.args[2], {})
            reports = list(directory.glob("dti-results-*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["instance"], instance)
            self.assertIn(str(reports[0]), output)
            self.assertNotIn("large_field", output)
            self.assertNotIn("x" * 100, output)
            for secret in ("offline-file-password", "offline-dev-file-password", "process-must-never-win-password"):
                self.assertNotIn(secret, output + errors + reports[0].read_text())
            if os.name != "nt":
                self.assertEqual(reports[0].stat().st_mode & 0o777, 0o600)

    def test_blank_dev_uses_only_explicit_global_url_never_it_uat_prod(self):
        with tempfile.TemporaryDirectory() as folder:
            code, _output, _errors, client, _suite = self.run_local(Path(folder), {"USBEM_DEV_URL": ""})
            self.assertEqual(code, 4)
            self.assertEqual(client.call_count, 1)
            self.assertEqual(client.call_args.args[0], "https://offline-global.service-now.com")
            self.assertEqual(client.call_args.args[1]["password"], "offline-file-password")

    def test_neither_file_target_is_configured_stops_before_constructing_any_client(self):
        with tempfile.TemporaryDirectory() as folder:
            code, output, errors, client, suite = self.run_local(Path(folder), {"USBEM_DEV_URL": "", "SN_INSTANCE_URL": ""})
            self.assertEqual(code, 3)
            client.assert_not_called()
            suite.assert_not_called()
            self.assertNotIn("Traceback", output + errors)
            self.assertNotIn("process-must-never-win-password", output + errors)

    def test_support_example_hostname_never_receives_credentials(self):
        for placeholder in ("https://your-dev-instance.service-now.com", "https://your-instance.service-now.com"):
            with self.subTest(placeholder=placeholder), tempfile.TemporaryDirectory() as folder:
                code, output, errors, client, suite = self.run_local(Path(folder), {"USBEM_DEV_URL": placeholder})
                self.assertEqual(code, 3)
                client.assert_not_called()
                suite.assert_not_called()
                self.assertIn("No test Events were sent", output + errors)

    def test_internal_laptop_mode_rejects_comprehensive_profile_before_configuration(self):
        with patch.object(runner, "configuration") as configure, patch.object(runner, "read_env") as read_env, \
                patch.object(runner, "Client") as broad, patch.object(runner, "ProductionClient") as restricted, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(["--access-profile", "comprehensive"], laptop=True), 3)
        configure.assert_not_called()
        read_env.assert_not_called()
        broad.assert_not_called()
        restricted.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "error")

    def test_common_fixture_filename_typo_is_supported_when_correct_file_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            code, _output, _errors, client, suite = self.run_local(Path(folder), fixture_name="dev-fixutres.json")
            self.assertEqual(code, 4)
            client.assert_called_once()
            suite.assert_called_once()

    def test_correct_fixture_filename_has_priority_over_typo(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "dev-fixutres.json").write_text('{"wrong_file": true}')
            code, _output, _errors, _client, suite = self.run_local(directory, fixture={"correct_file": True})
            self.assertEqual(code, 4)
            self.assertEqual(suite.call_args.args[2], {"correct_file": True})

    def test_bad_json_prints_clear_local_error_before_auth_and_never_echoes_its_content(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            script, _env, catalog = self.local_files(directory)
            catalog.write_text('{"private_sentinel_do_not_echo": trailing,}')
            with patch.object(runner, "__file__", str(script)), patch.object(runner, "ProductionClient") as client, \
                    patch.object(runner, "Client") as broad, contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                code = runner.run_laptop()
            self.assertEqual(code, 3)
            client.assert_not_called()
            broad.assert_not_called()
            self.assertIn("dev-fixtures.json", output.getvalue() + errors.getvalue())
            self.assertNotIn("Traceback", output.getvalue() + errors.getvalue())
            self.assertNotIn("private_sentinel_do_not_echo", output.getvalue() + errors.getvalue())

    def test_report_filename_is_unique_on_rerun_and_inputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.run_local(directory)
            first = list(directory.glob("dti-results-*.json"))
            self.assertEqual(len(first), 1)
            first_contents = first[0].read_bytes()
            self.run_local(directory)
            self.assertEqual(len(list(directory.glob("dti-results-*.json"))), 2)
            self.assertEqual(first[0].read_bytes(), first_contents)

    def test_windows_without_fchmod_can_run_and_save_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            proxy = contract.ProductionPortabilityTests.windows_os_without_fchmod(directory)
            with patch.object(runner, "os", proxy):
                code, _output, _errors, client, _suite = self.run_local(directory)
            self.assertEqual(code, 4)
            client.assert_called_once()
            reports = list(directory.glob("dti-results-*.json"))
            self.assertEqual(len(reports), 1)
            self.assertEqual(json.loads(reports[0].read_text())["status"], "incomplete")

    def test_initial_report_write_failure_prevents_authentication_and_event_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            script, _env, _catalog = self.local_files(directory)
            with patch.object(runner, "__file__", str(script)), patch.object(runner, "write_private_json", side_effect=PermissionError()), \
                    patch.object(runner, "ProductionClient") as client, patch.object(runner, "Client") as broad, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.run_laptop(), 3)
            client.assert_not_called()
            broad.assert_not_called()
            self.assertIn("No test Events were sent", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())

    def test_interrupt_keeps_running_report_and_never_prints_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            script, _env, _catalog = self.local_files(directory)
            with patch.object(runner, "__file__", str(script)), patch.object(runner, "ProductionClient") as client, \
                    patch.object(runner, "LaptopProductionRunner") as suite, contextlib.redirect_stdout(io.StringIO()) as output:
                client.return_value.operation_counts = {}
                suite.return_value.run.side_effect = KeyboardInterrupt()
                self.assertEqual(runner.run_laptop(), 130)
            reports = list(directory.glob("dti-results-*.json"))
            self.assertEqual(len(reports), 1)
            self.assertEqual(json.loads(reports[0].read_text())["status"], "running")
            self.assertIn("STOPPED", output.getvalue())
            self.assertNotIn("RESULT: PASS", output.getvalue())

    def test_windows_utf8_bom_sidecars_are_accepted_without_rewriting_them(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            script, env, catalog = self.local_files(directory)
            for sidecar in (env, catalog):
                sidecar.write_bytes(b"\xef\xbb\xbf" + sidecar.read_bytes())
            original = {path: path.read_bytes() for path in (env, catalog)}
            with patch.object(runner, "__file__", str(script)), patch.object(runner, "ProductionClient") as client, \
                    patch.object(runner, "LaptopProductionRunner") as suite, contextlib.redirect_stdout(io.StringIO()):
                client.return_value.operation_counts = {}
                suite.return_value.run.return_value = self.fake_report()
                self.assertEqual(runner.run_laptop(), 4)
            self.assertEqual(client.call_args.args[0], "https://offline-dev.service-now.com")
            self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_missing_fixture_stops_before_any_client_and_names_the_needed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            script, _env, catalog = self.local_files(directory)
            catalog.unlink()
            with patch.object(runner, "__file__", str(script)), patch.object(runner, "ProductionClient") as client, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.run_laptop(), 3)
            client.assert_not_called()
            self.assertIn("dev-fixtures.json", output.getvalue())
            self.assertIn("No test Events were sent", output.getvalue())

    def test_one_copied_python_file_has_no_repository_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other_folder:
            copied = Path(folder) / "test_ci_identifier_precedence.py"
            original_bytes = Path(runner.__file__).read_bytes()
            copied.write_bytes(original_bytes)
            result = subprocess.run([sys.executable, str(copied)], cwd=other_folder,
                env={"PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stdout + result.stderr)
            self.assertIn("production_test.env", result.stdout + result.stderr)
            self.assertEqual(hashlib.sha256(copied.read_bytes()).digest(), hashlib.sha256(original_bytes).digest())


if __name__ == "__main__":
    unittest.main()
