#!/usr/bin/env python3
"""Offline safety contracts for explicit DEV fixture setup; never contacts a PDI."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ci_identifier_precedence as runner


TARGET = "https://dev123456.service-now.com"
CI, PROPERTY = "a" * 32, "b" * 32
AUTH = {"mode": "basic", "username": "offline-only", "password": "offline-only"}


class AdminStub:
    """A local journal-aware action stub, not an HTTP or ServiceNow client."""

    def __init__(self, snapshot=None):
        self.snapshot = copy.deepcopy(snapshot or {"exists": False, "sys_id": "", "value": "", "description": "", "valid_ci": False})
        self.calls = []
        self.before_set = None
        self.set_error = None
        self.restore_error = None

    def execute(self, action, cfg):
        self.calls.append((action, copy.deepcopy(cfg)))
        if action == "property_snapshot":
            return copy.deepcopy(self.snapshot)
        if action == "property_set":
            if self.before_set:
                self.before_set(cfg)
            if self.set_error:
                raise self.set_error
            self.snapshot = {"exists": True, "sys_id": PROPERTY, "value": CI,
                             "description": "offline fixture lease"}
            return {"sys_id": PROPERTY}
        if action == "property_restore":
            if self.restore_error:
                raise self.restore_error
            return {"restored": True}
        raise AssertionError("unexpected local fixture action: " + action)


class FixtureReadClient:
    """Exact local fixture reads, with mutation intentionally unavailable."""

    def __init__(self):
        self.base, self.auth, self.insecure = TARGET, copy.deepcopy(AUTH), False
        self.queries = []
        self.tables = {}

    def query(self, table, query, fields, timeout, limit=1000):
        self.queries.append((table, query, fields, timeout, limit))
        rows = copy.deepcopy(self.tables.get(table, []))
        for part in query.split("^"):
            key, value = part.split("=", 1)
            rows = [row for row in rows if str(row.get(key, "")) == value]
        return [{key: row[key] for key in fields.split(",") if key in row} for row in rows]


def baseline_client():
    client = FixtureReadClient()
    decoy, group, caller, assignee = (character * 32 for character in "cdef")
    settings = runner.Settings("genericJsonV2", "cmdb_ci_server", {"serial_number": "OFFLINE-EXPECTED"},
                               "Offline Decoy", CI, decoy, caller_id=caller,
                               assignment_group=group, expected_assignment_group_id=group)
    owned = {key: format(100 + index, "032x") for index, key in enumerate((
        "l2_group", "owner_user", "foreign_task", "service_a", "service_b", "offering",
        "l2_ci", "support_ci", "default_ci", "business_app", "association"))}
    owned.update(namespace=runner.DEV_FIXTURE_NAMESPACE, ambiguous_name="USBEM DTI Fixture Ambiguous")
    client.tables = {
        "cmdb_ci": [{"sys_id": CI, "name": "Offline Primary", "sys_class_name": settings.ci_type},
                    {"sys_id": decoy, "name": "Offline Decoy"},
                    {"sys_id": owned["support_ci"], "name": "[TEST] USBEM DTI Support Server"}],
        "sys_user": [{"sys_id": caller, "name": "Offline Caller"},
                     {"sys_id": assignee, "name": "Offline Assignee", "active": "true"}],
        "sys_user_group": [{"sys_id": group, "name": "Offline Operations"},
                           {"sys_id": owned["l2_group"], "name": "[TEST] USBEM DTI L2"}],
        "sys_properties": [{"sys_id": PROPERTY, "name": "x_usbna_usb_event.default_caller_sys_id", "value": caller}],
        "sys_db_object": [{"name": settings.ci_type, "label": "Server"}],
        "sys_user_grmember": [{"sys_id": "9" * 32, "group": group, "user": assignee}],
        "cmdb_ci_service": [{"sys_id": owned["service_a"], "name": "[TEST] USBEM Service A"},
                            {"sys_id": owned["service_b"], "name": "[TEST] USBEM Service B"}],
        "service_offering": [{"sys_id": owned["offering"], "name": "[TEST] USBEM Offering"}],
        "sys_dictionary": [{"sys_id": "8" * 32, "name": "em_alert", "element": "incident",
                            "internal_type": "reference", "reference": "task"}],
    }
    return client, settings, owned


class FixtureTargetGuardTests(unittest.TestCase):
    def test_exact_explicit_dev_origin_basic_auth_is_accepted(self):
        self.assertEqual(runner.validate_fixture_target(TARGET, TARGET, AUTH), TARGET)

    def test_setup_requires_exact_confirmation(self):
        for confirmation in ("", "yes", "dev123456", "https://dev654321.service-now.com"):
            with self.subTest(confirmation=confirmation), self.assertRaises(ValueError):
                runner.validate_fixture_target(TARGET, confirmation, AUTH)

    def test_production_and_lookalike_origins_are_rejected(self):
        for target in ("https://company.service-now.com", "https://prod392825.service-now.com",
                       "https://dev123456.service-now.com.evil.invalid", "https://dev123456.example.com",
                       "http://dev123456.service-now.com", "https://localhost"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                runner.validate_fixture_target(target, target, AUTH)

    def test_userinfo_port_path_query_fragment_are_not_normalized_into_permission(self):
        for target in (TARGET + "/", TARGET + "/anything", TARGET + ":443", TARGET + "?x=1",
                       TARGET + "#fragment", "https://offline@dev123456.service-now.com"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                runner.validate_fixture_target(target, target, AUTH)

    def test_setup_rejects_oauth_incomplete_basic_and_insecure_tls(self):
        for auth in ({"mode": "oauth", "client_id": "offline", "client_secret": "offline"},
                     {"mode": "basic", "username": "offline", "password": ""},
                     {"mode": "basic", "username": "", "password": "offline"},
                     {"mode": "basic", "username": "with:colon", "password": "offline"}, {}):
            with self.subTest(auth=auth), self.assertRaises(ValueError):
                runner.validate_fixture_target(TARGET, TARGET, auth)
        with self.assertRaises(ValueError):
            runner.validate_fixture_target(TARGET, TARGET, AUTH, insecure=True)


class PrivateFixtureFileTests(unittest.TestCase):
    def test_json_is_valid_and_mode0600_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.json"
            previous = os.umask(0)
            try:
                runner.write_private_json(path, {"instance": TARGET, "original_value": ""})
            finally:
                os.umask(previous)
            self.assertEqual(json.loads(path.read_text()), {"instance": TARGET, "original_value": ""})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_exclusive_creation_does_not_overwrite_existing_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.json"
            runner.write_private_json(path, {"original": "preserve"})
            before = path.read_bytes()
            with self.assertRaises((OSError, ValueError, runner.ApiError)):
                runner.write_private_json(path, {"new": "do not replace"}, exclusive=True)
            self.assertEqual(path.read_bytes(), before)

    def test_existing_permissive_file_is_hardened_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            runner.write_private_json(path, {"old": True})
            path.chmod(0o644)
            runner.write_private_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"new": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_symlink_destination_never_overwrites_foreign_file(self):
        with tempfile.TemporaryDirectory() as directory:
            foreign, link = Path(directory) / "foreign.json", Path(directory) / "journal.json"
            runner.write_private_json(foreign, {"foreign": "unchanged"})
            link.symlink_to(foreign)
            before = foreign.read_bytes()
            with self.assertRaises((OSError, ValueError, runner.ApiError)):
                runner.write_private_json(link, {"overwrite": True})
            self.assertEqual(foreign.read_bytes(), before)

    def test_failed_fsync_does_not_destroy_previous_recovery_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recover.json"
            runner.write_private_json(path, {"state": "prepared", "original_value": "preserve this"})
            before = path.read_bytes()
            with patch.object(runner.os, "fsync", side_effect=OSError("offline simulated disk failure")):
                with self.assertRaises(OSError):
                    runner.write_private_json(path, {"state": "active"})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_unserializable_update_preserves_existing_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recover.json"
            runner.write_private_json(path, {"state": "prepared"})
            before = path.read_bytes()
            with self.assertRaises(TypeError):
                runner.write_private_json(path, {"not_json": object()})
            self.assertEqual(path.read_bytes(), before)


class DefaultCiLeaseTests(unittest.TestCase):
    def test_construction_does_not_read_or_write_global_property(self):
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub()
            runner.DefaultCiLease(admin, TARGET, CI, path)
            self.assertEqual(admin.calls, [])
            self.assertFalse(path.exists())

    def test_invalid_fixture_id_is_rejected_without_property_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            for record_id in ("", "not-an-id", "a" * 31, "../../sys_properties"):
                admin = AdminStub()
                with self.subTest(record_id=record_id), self.assertRaises(ValueError):
                    runner.DefaultCiLease(admin, TARGET, record_id, Path(directory) / "recover.json")
                self.assertEqual(admin.calls, [])

    def test_valid_existing_default_cannot_be_overwritten_by_a_lease(self):
        original = {"exists": True, "sys_id": PROPERTY, "value": "c" * 32,
                    "description": "pre-existing real default", "valid_ci": True}
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub(original)
            lease = runner.DefaultCiLease(admin, TARGET, CI, path)
            with self.assertRaises(ValueError):
                lease.activate()
            self.assertEqual([action for action, _ in admin.calls], ["property_snapshot"])
            self.assertFalse(path.exists())

    def test_recovery_journal_is_private_and_durable_before_first_property_write(self):
        original = {"exists": True, "sys_id": PROPERTY, "value": "", "description": "existing property"}
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub(original)
            observed = []

            def before_set(_cfg):
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                saved = json.loads(path.read_text())
                serialized = json.dumps(saved)
                self.assertIn(TARGET, serialized)
                self.assertIn(CI, serialized)
                self.assertIn(PROPERTY, serialized)
                self.assertIn("existing property", serialized)
                observed.append(saved)

            admin.before_set = before_set
            lease = runner.DefaultCiLease(admin, TARGET, CI, path)
            lease.activate()
            self.assertEqual(len(observed), 1)
            self.assertEqual([action for action, _ in admin.calls], ["property_snapshot", "property_set"])

    def test_existing_recovery_journal_blocks_another_property_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub()
            runner.write_private_json(path, {"pending": "do not replace"})
            before = path.read_bytes()
            with self.assertRaises((ValueError, OSError, runner.ApiError, runner.CheckFailed)):
                runner.DefaultCiLease(admin, TARGET, CI, path).activate()
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("property_set", [action for action, _ in admin.calls])

    def test_journal_write_failure_prevents_property_write(self):
        with tempfile.TemporaryDirectory() as directory:
            admin = AdminStub()
            lease = runner.DefaultCiLease(admin, TARGET, CI, Path(directory) / "recover.json")
            with patch.object(runner, "write_private_json", side_effect=OSError("offline write denied")):
                with self.assertRaises((OSError, runner.ApiError, ValueError)):
                    lease.activate()
            self.assertNotIn("property_set", [action for action, _ in admin.calls])

    def test_uncertain_set_failure_retains_recovery_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub()
            admin.set_error = runner.ApiError("set outcome unknown", retryable=True)
            with self.assertRaises(runner.ApiError):
                runner.DefaultCiLease(admin, TARGET, CI, path).activate()
            self.assertTrue(path.exists())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual([action for action, _ in admin.calls].count("property_set"), 1)

    def test_restore_failure_is_not_silently_successful_and_keeps_recovery_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path, admin = Path(directory) / "recover.json", AdminStub()
            lease = runner.DefaultCiLease(admin, TARGET, CI, path)
            lease.activate()
            admin.restore_error = runner.ApiError("concurrent property change; not overwritten")
            with self.assertRaises(runner.ApiError):
                lease.restore()
            self.assertTrue(path.exists())
            self.assertEqual([action for action, _ in admin.calls].count("property_restore"), 1)


class DevAdminSessionTests(unittest.TestCase):
    def client(self):
        return SimpleNamespace(base=TARGET, auth=copy.deepcopy(AUTH), insecure=False)

    def test_session_construction_has_no_network_or_login_side_effect(self):
        with patch.object(urllib.request.OpenerDirector, "open") as opened:
            session = runner.DevAdminSession(self.client(), TARGET)
        self.assertFalse(session.logged_in)
        opened.assert_not_called()

    def test_actual_insecure_client_is_not_permitted_to_administer_fixtures(self):
        client = runner.Client(TARGET, copy.deepcopy(AUTH), insecure=True)
        with self.assertRaises(ValueError):
            runner.DevAdminSession(client, TARGET)

    def test_non_allowlisted_action_is_rejected_before_authentication(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        with patch.object(session, "_html") as html:
            for action in ("", "eval", "background_script", "delete_all", "property_set;evil()"):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    session.execute(action, {})
        html.assert_not_called()

    def test_only_builtin_script_runs_and_reserved_guard_config_cannot_be_overridden(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        marker = "USBEM_FIXTURE_" + "0" * 32
        output = marker + json.dumps({"ok": True, "result": {"namespace": runner.DEV_FIXTURE_NAMESPACE}}) + marker
        with patch.object(runner.uuid, "uuid4", return_value=SimpleNamespace(hex="0" * 32)), \
                patch.object(session, "_html", side_effect=["", "", '<input name="sysparm_ck" value="offline-nonce">', output]) as html:
            actual = session.execute("provision", {"target": "https://evil.invalid", "confirmation": "wrong",
                                                   "action": "eval", "namespace": "foreign", "script": "evil()"})
        self.assertEqual(actual, {"namespace": runner.DEV_FIXTURE_NAMESPACE})
        self.assertEqual(html.call_count, 4)
        self.assertEqual([call.args[0] for call in html.call_args_list],
                         ["/login.do", "/login.do", "/sys.scripts.do", "/sys.scripts.do"])
        body = html.call_args_list[-1].args[1]
        self.assertEqual(body["sys_scope"], "global")
        self.assertEqual(body["quota_managed_transaction"], "on")
        prefix, actual_script = body["script"].split(";\n", 1)
        cfg = json.loads(prefix.removeprefix("var cfg = "))
        self.assertEqual((cfg["target"], cfg["confirmation"], cfg["action"], cfg["namespace"]),
                         (TARGET, TARGET, "provision", runner.DEV_FIXTURE_NAMESPACE))
        self.assertEqual(actual_script, runner.DEV_FIXTURE_ADMIN_SCRIPT)

    def test_missing_background_nonce_blocks_action_before_any_script_post(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        with patch.object(session, "_html", side_effect=["", "", "<html>NO_ACCESS_DO_NOT_ECHO</html>"]) as html:
            with self.assertRaises(runner.ApiError) as raised:
                session.execute("provision", {})
        self.assertEqual(html.call_count, 3)
        self.assertNotIn("NO_ACCESS_DO_NOT_ECHO", str(raised.exception))

    def test_missing_controlled_result_does_not_echo_html(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        session.logged_in = True
        with patch.object(session, "_html", side_effect=['<input name="sysparm_ck" value="n">', "DO_NOT_ECHO_RAW_BODY"]):
            with self.assertRaises(runner.ApiError) as raised:
                session.execute("provision", {})
        self.assertNotIn("DO_NOT_ECHO_RAW_BODY", str(raised.exception))

    def test_admin_transport_is_one_shot_and_never_echoes_failure_body(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        for error in (TimeoutError("DO_NOT_ECHO"),
                      urllib.error.HTTPError(TARGET + "/sys.scripts.do", 403, "denied", {}, io.BytesIO(b"DO_NOT_ECHO"))):
            with self.subTest(error=type(error).__name__), patch.object(session.opener, "open", side_effect=error) as opened:
                with self.assertRaises(runner.ApiError) as raised:
                    session._html("/sys.scripts.do", {"script": "built-in"})
                self.assertEqual(opened.call_count, 1)
                self.assertNotIn("DO_NOT_ECHO", str(raised.exception))

    def test_only_script_post_gets_longer_timeout_without_any_automatic_retry(self):
        session = runner.DevAdminSession(self.client(), TARGET)
        for path, fields, timeout in (("/sys.scripts.do", {"script": "built-in"}, 300),
                                      ("/sys.scripts.do", None, 90),
                                      ("/login.do", {"user_name": "offline", "user_password": "offline"}, 90)):
            with self.subTest(path=path, fields=None if fields is None else sorted(fields)), \
                    patch.object(session.opener, "open", return_value=io.BytesIO(b"safe offline response")) as opened:
                self.assertEqual(session._html(path, fields), "safe offline response")
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(opened.call_args.kwargs["timeout"], timeout)

    def test_redirect_handler_never_forwards_login_to_another_origin_or_replays_post(self):
        handler = runner._SameOriginRedirect(TARGET)
        request = urllib.request.Request(TARGET + "/login.do", data=b"offline-password")
        for code, destination in ((302, "https://evil.invalid/login.do"), (307, TARGET + "/login.do"),
                                  (308, TARGET + "/login.do"), (302, "http://dev123456.service-now.com/login.do")):
            with self.subTest(code=code, destination=destination):
                self.assertIsNone(handler.redirect_request(request, None, code, "redirect", {}, destination))


class FixtureProvisionerTests(unittest.TestCase):
    def provisioner(self, directory, fixtures=None, allow=True, with_settings=True, default_snapshot=None):
        client, settings, owned = baseline_client()
        with patch.object(runner, "DevAdminSession"):
            provisioner = runner.DevFixtureProvisioner(client, settings if with_settings else None, TARGET,
                                                       Path(directory) / "recover.json", fixtures=fixtures,
                                                       allow_default_ci_property=allow)
        provisioner.admin = Mock()
        provisioner.admin.execute.return_value = owned
        snapshot = default_snapshot or {"exists": False, "sys_id": "", "value": "", "description": "",
                                        "valid_ci": False, "effective_value": "__USBEM_ABSENT__"}
        provisioner.admin.execute.side_effect = lambda action, _cfg: copy.deepcopy(snapshot) if action == "property_snapshot" else provisioner.admin.execute.return_value
        return provisioner, client, owned

    def test_missing_baseline_fixture_prevents_any_admin_action(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, client, _owned = self.provisioner(directory)
            client.tables["cmdb_ci"] = []
            with self.assertRaises(runner.ApiError):
                provisioner.provision()
            provisioner.admin.execute.assert_not_called()

    def test_recovery_connection_does_not_need_baseline_settings_but_cannot_provision(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, with_settings=False)
            with self.assertRaises(ValueError):
                provisioner.provision()
            provisioner.admin.execute.assert_not_called()

    def test_invalid_default_caller_never_modifies_existing_global_property(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, client, _owned = self.provisioner(directory)
            client.tables["sys_properties"][0]["value"] = "invalid"
            with self.assertRaises(runner.ApiError):
                provisioner.provision()
            provisioner.admin.execute.assert_not_called()

    def test_no_group_membership_never_adds_a_member_to_an_operational_group(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, client, _owned = self.provisioner(directory)
            client.tables["sys_user_grmember"] = []
            with self.assertRaises(runner.ApiError):
                provisioner.provision()
            provisioner.admin.execute.assert_not_called()

    def test_catalog_is_target_bound_and_uses_explicit_positive_and_negative_controls(self):
        original = {"terminal_extra_fields": {"u_cause": "offline fixture"}}
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, owned = self.provisioner(directory, fixtures=copy.deepcopy(original))
            catalog = provisioner.provision()
        self.assertEqual([call.args[0] for call in provisioner.admin.execute.call_args_list], ["property_snapshot", "provision"])
        self.assertEqual(original, {"terminal_extra_fields": {"u_cause": "offline fixture"}})
        self.assertEqual(catalog["fixture_catalog"]["target"], TARGET)
        self.assertEqual(catalog["foreign_task_link_field"], "incident")
        self.assertEqual(catalog["foreign_task_sys_id"], owned["foreign_task"])
        advanced = catalog["advanced_cases"]
        for name in ("node_fallback", "resource_resolution", "additional_info_name_fallback", "service_inference"):
            self.assertTrue(set(provisioner.CI_HINTS).issubset(advanced[name]["remove_fields"]), name)
        parent_cases = advanced["offering_parent_filter"]
        self.assertEqual(len(parent_cases), 2)
        self.assertEqual([case["expected_incident"]["service_offering"] for case in parent_cases], [owned["offering"], ""])
        self.assertNotEqual(parent_cases[0]["expected_incident"]["business_service"], parent_cases[1]["expected_incident"]["business_service"])
        dummy = advanced["default_dummy_policy"]
        self.assertEqual([case["expected_event"]["cmdb_ci"] for case in dummy], [owned["default_ci"], "", ""])
        self.assertTrue(all(case["want_incident"] is False for case in dummy))
        self.assertTrue(all("direct_to_incident" in case["remove_fields"] for case in dummy))
        self.assertTrue(catalog["fixture_catalog"]["default_ci_lease_required"])
        self.assertEqual(catalog["fixture_catalog"]["default_ci_positive_sys_id"], owned["default_ci"])
        self.assertEqual(provisioner.info["default_ci_property"]["writes"], 0)
        self.assertFalse(provisioner.info["default_ci_property"]["activated_during_setup"])

    def test_catalog_preserves_actual_valid_permanent_default_without_requiring_a_lease(self):
        snapshot = {"exists": True, "sys_id": PROPERTY, "value": CI, "description": "permanent connector default",
                    "valid_ci": True, "effective_value": CI}
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, owned = self.provisioner(directory, default_snapshot=snapshot)
            catalog = provisioner.provision()
        metadata = catalog["fixture_catalog"]
        self.assertFalse(metadata["default_ci_lease_required"])
        self.assertEqual(metadata["default_ci_positive_sys_id"], CI)
        self.assertNotEqual(CI, owned["default_ci"])
        self.assertEqual(catalog["advanced_cases"]["default_dummy_policy"][0]["expected_event"]["cmdb_ci"], CI)
        self.assertEqual(provisioner.info["default_ci_property"]["writes"], 0)
        self.assertEqual([call.args[0] for call in provisioner.admin.execute.call_args_list], ["property_snapshot", "provision"])

    def test_catalog_refuses_unfinished_temporary_lease_before_any_provision_action(self):
        snapshot = {"exists": True, "sys_id": PROPERTY, "value": CI, "valid_ci": True, "effective_value": CI,
                    "description": "USBEM DTI fixture pack v1 | " + runner.DEV_FIXTURE_NAMESPACE + " temporary lease"}
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, default_snapshot=snapshot)
            with self.assertRaises(runner.ApiError):
                provisioner.provision()
        self.assertTrue(provisioner.info["restoration_error"])
        self.assertEqual([call.args[0] for call in provisioner.admin.execute.call_args_list], ["property_snapshot"])

    def test_catalog_requires_permanent_default_id_readback_and_effective_value_before_provision(self):
        for corrupt in ({"value": "invalid"}, {"effective_value": "stale"}, {"value": "9" * 32, "effective_value": "9" * 32}):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                snapshot = {"exists": True, "sys_id": PROPERTY, "value": CI, "description": "permanent",
                            "valid_ci": True, "effective_value": CI, **corrupt}
                provisioner, _client, _owned = self.provisioner(directory, default_snapshot=snapshot)
                with self.assertRaises(runner.ApiError):
                    provisioner.provision()
                self.assertEqual([call.args[0] for call in provisioner.admin.execute.call_args_list], ["property_snapshot"])

    def controller(self, provisioner, admin=None):
        provisioner.admin = admin or AdminStub()
        provisioner.fixtures["provisioned_default_ci_sys_id"] = CI
        observer = SimpleNamespace(cases=[], progress=Mock(), settle=Mock(), write_stop_reason="")

        def collection(_name, fixtures):
            observer.cases.extend({"name": "offline-control-" + str(index)} for index in range(len(fixtures)))
            return {"configured_subcases": len(fixtures)}

        observer.advanced_collection = Mock(side_effect=collection)
        cases = [{"expected_event": {"cmdb_ci": value}} for value in (CI, "", "")]
        return observer, cases

    def test_temporary_default_controls_are_settled_then_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory)
            observer, cases = self.controller(provisioner)
            result = provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual(result["configured_subcases"], 3)
            self.assertEqual(provisioner.info["default_ci_property"]["status"], "restored")
            self.assertEqual([action for action, _ in provisioner.admin.calls],
                             ["property_snapshot", "property_snapshot", "property_set", "property_restore"])
            observer.settle.assert_called_once_with(observer.cases)
            saved = json.loads(Path(provisioner.recovery_path).read_text())
            self.assertEqual(saved["state"], "restored")

    def test_temporary_property_requires_explicit_allow_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, allow=False)
            observer, cases = self.controller(provisioner)
            with self.assertRaises(runner.MissingFixture):
                provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual([action for action, _ in provisioner.admin.calls], ["property_snapshot"])
            observer.advanced_collection.assert_not_called()

    def test_existing_valid_default_is_used_without_a_property_lease(self):
        admin = AdminStub({"exists": True, "sys_id": PROPERTY, "value": "c" * 32,
                           "description": "real existing default", "valid_ci": True})
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, allow=False)
            observer, cases = self.controller(provisioner, admin)
            original = copy.deepcopy(cases)
            provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual(cases, original)
            self.assertEqual(observer.advanced_collection.call_args.args[1][0]["expected_event"]["cmdb_ci"], "c" * 32)
            self.assertEqual([action for action, _ in admin.calls], ["property_snapshot"])
            self.assertEqual(provisioner.info["default_ci_property"]["writes"], 0)

    def test_unfinished_prior_lease_is_not_adopted_as_an_ordinary_valid_default(self):
        for valid in (True, False):
            with self.subTest(valid_ci=valid), tempfile.TemporaryDirectory() as directory:
                provisioner, _client, _owned = self.provisioner(directory)
                admin = AdminStub({"exists": True, "sys_id": PROPERTY, "value": CI, "valid_ci": valid,
                                   "description": "USBEM DTI fixture pack v1 | " + runner.DEV_FIXTURE_NAMESPACE + " temporary lease"})
                observer, cases = self.controller(provisioner, admin)
                with self.assertRaises(runner.ApiError):
                    provisioner.run_default_ci_controls(observer, cases)
                self.assertTrue(provisioner.info["restoration_error"])
                self.assertTrue(observer.write_stop_reason)
                observer.advanced_collection.assert_not_called()
                self.assertEqual([action for action, _ in admin.calls], ["property_snapshot"])

    def test_active_journal_update_failure_still_restores_using_prepared_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory)
            observer, cases = self.controller(provisioner)
            real_write = runner.write_private_json
            calls = []

            def fail_active_update(path, value, exclusive=False):
                calls.append(value["state"])
                if value["state"] == "active":
                    self.assertEqual(json.loads(Path(path).read_text())["state"], "prepared")
                    raise OSError("offline simulated active journal replacement failure")
                return real_write(path, value, exclusive=exclusive)

            with patch.object(runner, "write_private_json", side_effect=fail_active_update), self.assertRaises(OSError):
                provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual(calls, ["prepared", "active", "restored"])
            self.assertEqual(provisioner.admin.calls[-1][0], "property_restore")
            self.assertEqual(json.loads(provisioner.recovery_path.read_text())["state"], "restored")
            observer.advanced_collection.assert_not_called()

    def test_submission_exception_and_keyboardinterrupt_both_restore_temporary_property(self):
        for error in (runner.CheckFailed("offline assertion failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                provisioner, _client, _owned = self.provisioner(directory)
                observer, cases = self.controller(provisioner)
                observer.advanced_collection.side_effect = error
                with self.assertRaises(type(error)):
                    provisioner.run_default_ci_controls(observer, cases)
                self.assertEqual(provisioner.admin.calls[-1][0], "property_restore")
                self.assertEqual(provisioner.info["default_ci_property"]["status"], "restored")

    def test_observation_failure_cannot_bypass_finally_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory)
            observer, cases = self.controller(provisioner)
            observer.settle.side_effect = runner.ApiError("offline read error")
            with self.assertRaises(runner.ApiError):
                provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual(provisioner.admin.calls[-1][0], "property_restore")

    def test_restoration_failure_overrides_test_failure_and_stops_further_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory)
            observer, cases = self.controller(provisioner)
            observer.advanced_collection.side_effect = runner.CheckFailed("original test failed")
            provisioner.admin.restore_error = runner.ApiError("concurrent choice; no clobber")
            with self.assertRaises(runner.ApiError):
                provisioner.run_default_ci_controls(observer, cases)
            self.assertEqual(provisioner.info["default_ci_property"]["status"], "error")
            self.assertFalse(provisioner.info["default_ci_property"]["restored"])
            self.assertTrue(observer.write_stop_reason)
            self.assertTrue(provisioner.recovery_path.exists())

    def saved_journal(self):
        return {"format": "USBEM-default-ci-recovery-v1", "target": TARGET,
                "namespace": runner.DEV_FIXTURE_NAMESPACE, "property_name": runner.DEFAULT_CI_PROPERTY,
                "before": {"exists": False, "sys_id": "", "value": "", "description": ""},
                "fixture_ci_id": CI, "state": "prepared"}

    def test_recovery_accepts_prepared_unknown_outcome_and_forwards_only_fixed_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, with_settings=False)
            saved = dict(self.saved_journal(), script="evil()", action="provision")
            runner.write_private_json(provisioner.recovery_path, saved)
            provisioner.admin.execute.return_value = {"restored": True}
            result = provisioner.recover(provisioner.recovery_path)
            self.assertTrue(result["restored"])
            action, cfg = provisioner.admin.execute.call_args.args
            self.assertEqual(action, "property_restore")
            self.assertEqual(set(cfg), {"property_name", "before", "fixture_ci_id"})
            self.assertEqual(json.loads(provisioner.recovery_path.read_text())["state"], "restored")

    def test_wrong_target_invalid_ids_or_public_journal_never_make_a_recovery_action(self):
        corruptions = ({"target": "https://dev654321.service-now.com"}, {"namespace": "other"},
                       {"property_name": "glide.foreign.setting"}, {"fixture_ci_id": "invalid"},
                       {"before": {"exists": "false", "value": ""}}, {"state": "unknown"})
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, with_settings=False)
            for change in corruptions:
                with self.subTest(change=change):
                    runner.write_private_json(provisioner.recovery_path, dict(self.saved_journal(), **change))
                    with self.assertRaises(ValueError):
                        provisioner.recover(provisioner.recovery_path)
            runner.write_private_json(provisioner.recovery_path, self.saved_journal())
            provisioner.recovery_path.chmod(0o644)
            with self.assertRaises(ValueError):
                provisioner.recover(provisioner.recovery_path)
            provisioner.admin.execute.assert_not_called()

    def test_failed_recovery_retains_original_private_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, with_settings=False)
            runner.write_private_json(provisioner.recovery_path, self.saved_journal())
            before = provisioner.recovery_path.read_bytes()
            provisioner.admin.execute.side_effect = runner.ApiError("operator changed property; refused")
            with self.assertRaises(runner.ApiError):
                provisioner.recover(provisioner.recovery_path)
            self.assertEqual(provisioner.recovery_path.read_bytes(), before)

    def test_recovery_symlink_cannot_authorize_or_modify_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner, _client, _owned = self.provisioner(directory, with_settings=False)
            actual, link = Path(directory) / "actual.json", Path(directory) / "link.json"
            runner.write_private_json(actual, self.saved_journal())
            link.symlink_to(actual)
            before = actual.read_bytes()
            with self.assertRaises(ValueError):
                provisioner.recover(link)
            provisioner.admin.execute.assert_not_called()
            self.assertEqual(actual.read_bytes(), before)


class FixtureCliTests(unittest.TestCase):
    def values(self):
        _client, settings, _owned = baseline_client()
        return {"SN_INSTANCE_URL": TARGET, "SN_USERNAME": "offline-only", "SN_PASSWORD": "offline-only",
                "USBEM_CI_TYPE": settings.ci_type, "USBEM_CI_IDENTIFIER_JSON": json.dumps(settings.identifier),
                "USBEM_DECOY_CI_NAME": settings.decoy_name, "USBEM_EXPECTED_CI_SYS_ID": settings.expected_id,
                "USBEM_DECOY_CI_SYS_ID": settings.decoy_id, "USBEM_TEST_CALLER_SYS_ID": settings.caller_id,
                "USBEM_ASSIGNMENT_GROUP": settings.assignment_group,
                "USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID": settings.expected_assignment_group_id}

    def test_normal_run_never_constructs_admin_or_provisioner_even_when_features_are_incomplete(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["tester", "--access-profile", "comprehensive"]), \
                patch.object(runner, "read_env", return_value=self.values()), patch.object(runner, "Client"), \
                patch.object(runner, "ComprehensiveRunner") as suite, patch.object(runner, "DevAdminSession") as admin, \
                patch.object(runner, "DevFixtureProvisioner") as setup, contextlib.redirect_stdout(output):
            suite.return_value.run.return_value = {"status": "incomplete"}
            self.assertEqual(runner.main(), 4)
        admin.assert_not_called()
        setup.assert_not_called()
        self.assertNotIn("provisioner", suite.call_args.kwargs)
        self.assertEqual(json.loads(output.getvalue())["status"], "incomplete")

    def test_plan_with_all_setup_flags_reads_no_credentials_and_makes_no_network_requests(self):
        output = io.StringIO()
        argv = ["tester", "--plan", "--provision-dev-fixtures", "--prepare-fixtures-only",
                "--confirm-fixture-target", TARGET, "--allow-default-ci-property"]
        with patch.object(sys, "argv", argv), patch.object(runner, "read_env") as env, \
                patch.object(runner, "Client") as client, patch.object(runner, "DevAdminSession") as admin, \
                patch.object(runner, "DevFixtureProvisioner") as setup, contextlib.redirect_stdout(output):
            self.assertEqual(runner.main(), 0)
        for operation in (env, client, admin, setup):
            operation.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual((report["network_requests"], report["writes"]), (0, 0))
        self.assertFalse(report["explicit_dev_fixture_setup"]["new_tables_or_security_grants"])

    def test_setup_without_exact_confirmation_is_rejected_before_any_client_or_admin(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["tester", "--provision-dev-fixtures"]), \
                patch.object(runner, "read_env", return_value=self.values()), patch.object(runner, "Client") as client, \
                patch.object(runner, "DevAdminSession") as admin, patch.object(runner, "DevFixtureProvisioner") as setup, \
                contextlib.redirect_stdout(output):
            self.assertEqual(runner.main(), 3)
        for operation in (client, admin, setup):
            operation.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "error")

    def test_administrative_flag_without_explicit_setup_is_an_error_before_credentials(self):
        for flag in ("--allow-default-ci-property", "--prepare-fixtures-only"):
            with self.subTest(flag=flag), patch.object(sys, "argv", ["tester", flag]), \
                    patch.object(runner, "read_env") as env, patch.object(runner, "Client") as client, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 3)
                env.assert_not_called()
                client.assert_not_called()

    def test_recovery_uses_only_connection_credentials_not_ci_or_reference_fixtures(self):
        connection = {key: value for key, value in self.values().items() if key.startswith("SN_")}
        output = io.StringIO()
        argv = ["tester", "--restore-fixture-default-ci", "/offline/recover.json", "--confirm-fixture-target", TARGET]
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", argv), \
                patch.object(runner, "read_env", return_value=connection), patch.object(runner, "Client"), \
                patch.object(runner, "fixture_input") as fixture_input, patch.object(runner, "ComprehensiveRunner") as suite, \
                patch.object(runner, "DevFixtureProvisioner") as setup, contextlib.redirect_stdout(output):
            setup.return_value.info = {"default_ci_property": {"status": "restored"}}
            setup.return_value.recover.return_value = {"restored": True}
            self.assertEqual(runner.main(), 0)
        fixture_input.assert_not_called()
        suite.assert_not_called()
        self.assertIsNone(setup.call_args.args[1])
        setup.return_value.recover.assert_called_once_with("/offline/recover.json")
        self.assertEqual(json.loads(output.getvalue())["mode"], "fixture_default_ci_recovery")

    def test_recovery_cannot_be_combined_with_provisioning(self):
        argv = ["tester", "--restore-fixture-default-ci", "/offline/recover.json", "--provision-dev-fixtures"]
        with patch.object(sys, "argv", argv), patch.object(runner, "read_env") as env, \
                patch.object(runner, "Client") as client, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(), 3)
        env.assert_not_called()
        client.assert_not_called()

    def test_unverified_restoration_forces_top_level_error_even_when_test_already_failed(self):
        output = io.StringIO()
        argv = ["tester", "--provision-dev-fixtures", "--confirm-fixture-target", TARGET]
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", argv), \
                patch.object(runner, "read_env", return_value=self.values()), patch.object(runner, "Client"), \
                patch.object(runner, "write_private_json"), patch.object(runner, "ComprehensiveRunner") as suite, \
                patch.object(runner, "DevFixtureProvisioner") as setup, contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(io.StringIO()):
            setup.return_value.provision.return_value = {}
            setup.return_value.info = {"restoration_error": "recover before continuing",
                                       "default_ci_property": {"status": "error", "restored": False}}
            suite.return_value.run.return_value = {"status": "fail", "counts": {"fail": 1, "error": 1}}
            self.assertEqual(runner.main(), 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")

    def test_prepare_only_produces_private_catalog_without_running_events(self):
        argv = ["tester", "--provision-dev-fixtures", "--prepare-fixtures-only", "--confirm-fixture-target", TARGET]
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", argv), \
                patch.object(runner, "read_env", return_value=self.values()), patch.object(runner, "Client"), \
                patch.object(runner, "write_private_json") as writer, patch.object(runner, "ComprehensiveRunner") as suite, \
                patch.object(runner, "DevFixtureProvisioner") as setup, contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(io.StringIO()):
            setup.return_value.provision.return_value = {"fixture_catalog": {"target": TARGET}}
            setup.return_value.info = {"namespace": runner.DEV_FIXTURE_NAMESPACE}
            self.assertEqual(runner.main(), 0)
        suite.assert_not_called()
        writer.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["test_events_submitted"], 0)

    def test_selected_profile_fixture_json_has_same_precedence_as_other_configuration(self):
        args = SimpleNamespace(fixture="", profile="DEV")
        values = {"USBEM_TEST_FIXTURES_JSON": '{"global":true}', "USBEM_DEV_TEST_FIXTURES_JSON": '{"profile":true}'}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(json.loads(runner.fixture_input(args, values)), {"profile": True})
        with patch.dict(os.environ, {"USBEM_DEV_TEST_FIXTURES_JSON": '{"process":true}'}, clear=True):
            self.assertEqual(json.loads(runner.fixture_input(args, values)), {"process": True})

    def test_report_cannot_replace_env_even_if_other_arguments_are_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            protected = Path(directory) / "connection.env"
            runner.write_private_json(protected, {"offline-fixture": "preserve exact bytes"})
            before = protected.read_bytes()
            argv = ["tester", "--env-file", str(protected), "--report-file", str(protected), "--allow-default-ci-property"]
            with patch.object(sys, "argv", argv), patch.object(runner, "read_env") as env, \
                    patch.object(runner, "Client") as client, patch.object(runner, "DevAdminSession") as admin, \
                    patch.object(runner, "write_private_json") as writer, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 3)
            for operation in (env, client, admin, writer):
                operation.assert_not_called()
            self.assertEqual(protected.read_bytes(), before)

    def test_report_cannot_replace_fixture_or_recovery_input_via_resolved_alias(self):
        for option in ("--fixture", "--fixture-recovery-file", "--restore-fixture-default-ci"):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                protected = Path(directory) / "private-state.json"
                runner.write_private_json(protected, {"preserve": True})
                before = protected.read_bytes()
                argv = ["tester", option, str(protected), "--report-file", str(protected.parent / "." / protected.name)]
                with patch.object(sys, "argv", argv), patch.object(runner, "read_env") as env, \
                        patch.object(runner, "Client") as client, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 3)
                env.assert_not_called()
                client.assert_not_called()
                self.assertEqual(protected.read_bytes(), before)

    def test_unowned_existing_catalog_output_blocks_provision_before_admin_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            runner.write_private_json(path, {"unrelated": "do not overwrite"})
            before = path.read_bytes()
            argv = ["tester", "--provision-dev-fixtures", "--confirm-fixture-target", TARGET, "--fixture-output", str(path)]
            with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", argv), \
                    patch.object(runner, "read_env", return_value=self.values()), patch.object(runner, "Client"), \
                    patch.object(runner, "DevFixtureProvisioner") as provisioner, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 3)
            provisioner.assert_not_called()
            self.assertEqual(path.read_bytes(), before)


class FixtureCatalogOwnershipTests(unittest.TestCase):
    def catalog(self):
        return {"fixture_catalog": {"format": runner.DevFixtureProvisioner.CATALOG_FORMAT,
                                    "target": TARGET, "namespace": runner.DEV_FIXTURE_NAMESPACE}}

    def test_handwritten_fixture_without_generated_metadata_remains_valid(self):
        runner.validate_catalog_metadata({"assignee_sys_id": CI}, TARGET)

    def test_generated_catalog_requires_exact_target_format_and_namespace(self):
        runner.validate_catalog_metadata(self.catalog(), TARGET)
        for field, value in (("target", "https://dev654321.service-now.com"), ("format", "unknown"), ("namespace", "unowned")):
            with self.subTest(field=field):
                catalog = self.catalog()
                catalog["fixture_catalog"][field] = value
                with self.assertRaises(ValueError):
                    runner.validate_catalog_metadata(catalog, TARGET)
        with self.assertRaises(ValueError):
            runner.validate_catalog_metadata({"fixture_catalog": None}, TARGET)

    def test_only_owned_same_target_existing_output_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            runner.validate_fixture_output(path, TARGET)
            runner.write_private_json(path, self.catalog())
            before = path.read_bytes()
            runner.validate_fixture_output(path, TARGET)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                runner.validate_fixture_output(path, "https://dev654321.service-now.com")
            self.assertEqual(path.read_bytes(), before)

    def test_output_symlink_and_unowned_json_are_never_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            path, link = Path(directory) / "foreign.json", Path(directory) / "link.json"
            runner.write_private_json(path, {"unrelated": True})
            link.symlink_to(path)
            before = path.read_bytes()
            for target in (path, link):
                with self.subTest(target=target.name), self.assertRaises(ValueError):
                    runner.validate_fixture_output(target, TARGET)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
