#!/usr/bin/env python3
"""Offline deployer tests: no credentials, network, or ServiceNow writes."""

import copy
import importlib.util
import io
from pathlib import Path
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "deploy_usbem.py"
SPEC = importlib.util.spec_from_file_location("usbem_deployer_under_test", MODULE_PATH)
deployer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployer)
BR = next(component for component in deployer.COMPONENTS if component["table"] == "sys_script")
RECORD_ID = "c" * 32


class FakeServiceNow:
    """Persist writes independently of responses, including server-side alterations."""

    instance = "https://example.invalid"

    def __init__(self, stored=None):
        self.stored = copy.deepcopy(stored)
        self.writes = []
        self.reads = []
        self.mutate_stored = lambda row: None
        self.insert_response = None
        self.hide_from_query = False

    def table(self, name, query, fields, limit=50):
        if self.hide_from_query or self.stored is None:
            return []
        return [self._selected(fields)]

    def _selected(self, fields):
        return {field: copy.deepcopy(self.stored[field])
                for field in fields.split(",") if field in self.stored}

    def record(self, name, sys_id, fields):
        self.reads.append((name, sys_id, fields))
        if self.stored is None:
            return {}
        return self._selected(fields)

    def insert(self, name, payload):
        self.writes.append(("POST", name, copy.deepcopy(payload)))
        response = {"sys_id": RECORD_ID, **copy.deepcopy(payload)}
        self.stored = copy.deepcopy(response)
        self.mutate_stored(self.stored)
        return copy.deepcopy(self.insert_response if self.insert_response is not None else response)

    def update(self, name, sys_id, payload):
        self.writes.append(("PATCH", name, copy.deepcopy(payload)))
        self.stored.update(copy.deepcopy(payload))
        optimistic = copy.deepcopy(self.stored)
        self.mutate_stored(self.stored)
        return optimistic


class DeployerTests(unittest.TestCase):
    def setUp(self):
        self.component = copy.deepcopy(BR)
        self.source = (deployer.PROJECT / self.component["file"]).read_text(encoding="utf-8")
        self.current = {"sys_id": RECORD_ID, "script": self.source,
                        **self.component["create_if_missing"], **self.component["config"]}

    def run_deploy(self, sn, dry_run=False, force=False):
        output = io.StringIO()
        with patch.object(deployer, "COMPONENTS", [self.component]), redirect_stdout(output):
            failures = deployer.deploy(sn, dry_run=dry_run, force=force)
        return failures, output.getvalue()

    def test_br_explicitly_requires_advanced(self):
        self.assertEqual(self.component["config"]["advanced"], "true")

    def test_missing_br_is_created_and_stored_record_is_verified(self):
        sn = FakeServiceNow()
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 0)
        self.assertIn("created", output)
        self.assertEqual(len(sn.writes), 1)
        method, table, payload = sn.writes[0]
        self.assertEqual((method, table), ("POST", "sys_script"))
        self.assertEqual(payload, {"script": self.source, **self.component["create_if_missing"],
                                   **self.component["config"]})
        self.assertEqual(sn.reads[-1][1], RECORD_ID)
        for field in payload:
            self.assertIn(field, sn.reads[-1][2].split(","))

    def test_rerun_of_created_br_has_no_writes(self):
        sn = FakeServiceNow()
        self.assertEqual(self.run_deploy(sn)[0], 0)
        count = len(sn.writes)
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 0)
        self.assertIn("up to date", output)
        self.assertEqual(len(sn.writes), count)

    def test_existing_advanced_false_is_corrected_and_read_back(self):
        self.current["advanced"] = "false"
        sn = FakeServiceNow(self.current)
        self.assertEqual(self.run_deploy(sn)[0], 0)
        self.assertEqual(sn.writes[0][2], {"advanced": "true"})
        self.assertEqual(sn.stored["advanced"], "true")
        self.assertEqual(sn.reads[-1][1], RECORD_ID)

    def test_creation_uses_stored_script_not_optimistic_insert_response(self):
        sn = FakeServiceNow()
        sn.mutate_stored = lambda row: row.update(script="server replaced the script")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("script differs after write", output)

    def test_creation_advanced_false_is_a_failure(self):
        sn = FakeServiceNow()
        sn.mutate_stored = lambda row: row.update(advanced="false")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("fields not applied: advanced", output)

    def test_creation_identity_fields_are_verified(self):
        sn = FakeServiceNow()
        sn.mutate_stored = lambda row: row.update(collection="incident")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("fields not applied: collection", output)

    def test_creation_missing_returned_id_is_a_failure(self):
        sn = FakeServiceNow()
        sn.insert_response = {}
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("create returned no record ID", output)
        self.assertNotIn("created", output)

    def test_creation_missing_readback_id_is_a_failure(self):
        sn = FakeServiceNow()
        sn.mutate_stored = lambda row: row.pop("sys_id")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("record ID missing or differs", output)

    def test_update_script_is_verified_from_storage(self):
        self.current["script"] = "old script"
        sn = FakeServiceNow(self.current)
        sn.mutate_stored = lambda row: row.update(script="old script")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("script differs after write", output)

    def test_update_reads_all_configuration_not_only_changed_fields(self):
        self.current["advanced"] = "false"
        sn = FakeServiceNow(self.current)
        sn.mutate_stored = lambda row: row.update(order="999")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("fields not applied: order", output)
        for field in self.component["config"]:
            self.assertIn(field, sn.reads[-1][2].split(","))

    def test_update_advanced_false_after_write_is_a_failure(self):
        self.current["advanced"] = "false"
        sn = FakeServiceNow(self.current)
        sn.mutate_stored = lambda row: row.update(advanced="false")
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("fields not applied: advanced", output)

    def test_unchanged_install_is_not_written(self):
        sn = FakeServiceNow(self.current)
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 0)
        self.assertIn("up to date", output)
        self.assertEqual(sn.writes, [])

    def test_line_ending_noise_is_not_written(self):
        self.current["script"] = self.source.replace("\n", "\r\n") + "\r\n"
        sn = FakeServiceNow(self.current)
        self.assertEqual(self.run_deploy(sn)[0], 0)
        self.assertEqual(sn.writes, [])

    def test_dry_run_existing_br_writes_nothing(self):
        self.current["advanced"] = "false"
        sn = FakeServiceNow(self.current)
        failures, output = self.run_deploy(sn, dry_run=True)
        self.assertEqual(failures, 0)
        self.assertIn("would write", output)
        self.assertEqual(sn.writes, [])
        self.assertEqual(sn.reads, [])

    def test_dry_run_missing_br_writes_nothing(self):
        sn = FakeServiceNow()
        failures, output = self.run_deploy(sn, dry_run=True)
        self.assertEqual(failures, 0)
        self.assertIn("would create", output)
        self.assertEqual(sn.writes, [])
        self.assertTrue(all(sys_id == self.component["sys_id"] for _, sys_id, _ in sn.reads))

    def test_force_writes_and_verifies_all_source_and_config(self):
        sn = FakeServiceNow(self.current)
        self.assertEqual(self.run_deploy(sn, force=True)[0], 0)
        self.assertEqual(sn.writes[0][2], {"script": self.source, **self.component["config"]})
        self.assertEqual(len(sn.reads), 1)

    def test_found_record_without_id_is_a_failure(self):
        self.current.pop("sys_id")
        sn = FakeServiceNow(self.current)
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("matched record has no record ID", output)
        self.assertEqual(sn.writes, [])

    def test_missing_noncreatable_component_fails_without_write(self):
        self.component.pop("create_if_missing")
        sn = FakeServiceNow()
        failures, output = self.run_deploy(sn)
        self.assertEqual(failures, 1)
        self.assertIn("MISSING", output)
        self.assertEqual(sn.writes, [])

    def test_fallback_id_lookup_remains_supported(self):
        sn = FakeServiceNow(self.current)
        sn.hide_from_query = True
        self.assertEqual(self.run_deploy(sn)[0], 0)
        self.assertEqual(sn.reads[0][1], self.component["sys_id"])
        self.assertEqual(sn.writes, [])

    def test_insert_http_wrapper_posts_to_table_api(self):
        sn = deployer.ServiceNow.__new__(deployer.ServiceNow)
        sn.instance = "https://example.invalid"
        sn._request = Mock(return_value={"sys_id": RECORD_ID})
        payload = {"advanced": "true"}
        self.assertEqual(sn.insert("sys_script", payload), {"sys_id": RECORD_ID})
        sn._request.assert_called_once_with(
            "POST", "https://example.invalid/api/now/table/sys_script", body=payload)

    def test_insert_http_wrapper_empty_result_is_a_dict(self):
        sn = deployer.ServiceNow.__new__(deployer.ServiceNow)
        sn.instance = "https://example.invalid"
        sn._request = Mock(return_value=None)
        self.assertEqual(sn.insert("sys_script", {}), {})

    def condition_result(self, *, work_notes, dti, incident_nil, terminal):
        # Replace only complete, known platform predicates. Evaluating the remaining Boolean
        # expression exercises the actual installer parentheses without pretending to emulate
        # GlideRecord or invoking a JavaScript engine/ServiceNow.
        predicates = {
            "(current.getValue('additional_info') || '').indexOf('work_notes') > -1": "work_notes",
            "(current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1": "dti",
            "current.incident.nil()": "incident_nil",
            "'6,7,8'.indexOf(current.incident.state.toString()) > -1": "terminal",
        }
        expression = deployer.BR_CONDITION
        for predicate, symbol in predicates.items():
            self.assertIn(predicate, expression)
            expression = expression.replace(predicate, symbol)
        expression = expression.replace("||", " or ").replace("&&", " and ")
        self.assertEqual(re.sub(r"\b(work_notes|dti|incident_nil|terminal|and|or)\b|[\s()]", "", expression), "")
        return eval(expression, {"__builtins__": {}}, {
            "work_notes": work_notes, "dti": dti, "incident_nil": incident_nil,
            "terminal": terminal})

    def test_pending_note_runs_for_open_linked_incident(self):
        self.assertTrue(self.condition_result(work_notes=True, dti=True,
                                              incident_nil=False, terminal=False))
        self.assertTrue(self.condition_result(work_notes=True, dti=False,
                                              incident_nil=False, terminal=False))

    def test_dti_only_still_skips_open_linked_incident(self):
        self.assertFalse(self.condition_result(work_notes=False, dti=True,
                                               incident_nil=False, terminal=False))

    def test_dti_only_runs_for_nil_or_terminal_link(self):
        self.assertTrue(self.condition_result(work_notes=False, dti=True,
                                              incident_nil=True, terminal=False))
        self.assertTrue(self.condition_result(work_notes=False, dti=True,
                                              incident_nil=False, terminal=True))

    def test_unrelated_alert_is_skipped_even_without_incident(self):
        self.assertFalse(self.condition_result(work_notes=False, dti=False,
                                               incident_nil=True, terminal=False))


class TransportRetryTests(unittest.TestCase):
    def make_client(self, session=True):
        client = deployer.ServiceNow.__new__(deployer.ServiceNow)
        client.instance = "https://example.invalid"
        client.timeout = 10
        client.context = None
        client._basic = "Basic not-a-real-credential"
        client._session = Mock() if session else None
        return client

    def test_requests_post_transport_failure_is_not_retried(self):
        client = self.make_client()
        client._session.request.side_effect = ConnectionError("secret-must-not-be-logged")
        with patch.object(deployer.time, "sleep") as sleep:
            with self.assertRaises(deployer.ServiceNowError) as caught:
                client._request("POST", client.instance + "/api/now/table/sys_script",
                                body={"script": "private-script-body"})
        self.assertEqual(client._session.request.call_count, 1)
        sleep.assert_not_called()
        self.assertIn("POST outcome unknown", str(caught.exception))
        self.assertIn("Read back the target state", str(caught.exception))
        self.assertNotIn("secret-must-not-be-logged", str(caught.exception))
        self.assertNotIn("private-script-body", str(caught.exception))

    def test_urllib_post_transport_failure_is_not_retried(self):
        client = self.make_client(session=False)
        with patch.object(deployer.urllib.request, "urlopen", side_effect=TimeoutError(
                "secret-must-not-be-logged")) as open_request, \
                patch.object(deployer.time, "sleep") as sleep:
            with self.assertRaises(deployer.ServiceNowError) as caught:
                client._request("POST", client.instance + "/api/now/table/sys_script", body={})
        self.assertEqual(open_request.call_count, 1)
        self.assertEqual(open_request.call_args.args[0].get_method(), "POST")
        sleep.assert_not_called()
        self.assertIn("POST outcome unknown", str(caught.exception))
        self.assertNotIn("secret-must-not-be-logged", str(caught.exception))

    def test_requests_get_retries_are_bounded(self):
        client = self.make_client()
        client._session.request.side_effect = ConnectionError("secret-must-not-be-logged")
        with patch.object(deployer.time, "sleep") as sleep:
            with self.assertRaises(deployer.ServiceNowError) as caught:
                client._request("GET", client.instance + "/api/now/table/sys_script")
        self.assertEqual(client._session.request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        self.assertIn("GET request failed after 3 attempts", str(caught.exception))
        self.assertNotIn("secret-must-not-be-logged", str(caught.exception))

    def test_urllib_get_retries_are_bounded(self):
        client = self.make_client(session=False)
        with patch.object(deployer.urllib.request, "urlopen", side_effect=TimeoutError(
                "secret-must-not-be-logged")) as open_request, \
                patch.object(deployer.time, "sleep") as sleep:
            with self.assertRaises(deployer.ServiceNowError):
                client._request("GET", client.instance + "/api/now/table/sys_script")
        self.assertEqual(open_request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_get_can_recover_within_retry_bound(self):
        client = self.make_client()
        client._session.request.side_effect = [
            ConnectionError("temporary"), TimeoutError("temporary"),
            Mock(status_code=200, text='{"result":{"sys_id":"' + RECORD_ID + '"}}'),
        ]
        with patch.object(deployer.time, "sleep"):
            self.assertEqual(client._request("GET", client.instance + "/api/now/table/sys_script"),
                             {"sys_id": RECORD_ID})
        self.assertEqual(client._session.request.call_count, 3)

    def test_post_http_failure_is_not_retried_or_body_logged(self):
        client = self.make_client()
        client._session.request.return_value = Mock(
            status_code=503, text="secret-must-not-be-logged")
        with patch.object(deployer.time, "sleep") as sleep:
            with self.assertRaises(deployer.ServiceNowError) as caught:
                client._request("POST", client.instance + "/api/now/table/sys_script", body={})
        self.assertEqual(client._session.request.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(str(caught.exception), "POST request -> HTTP 503")


if __name__ == "__main__":
    unittest.main()
