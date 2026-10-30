#!/usr/bin/env python3
"""Offline contracts for the one-script comprehensive DTI tester; no live access."""

import copy
import io
import json
import contextlib
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ci_identifier_precedence as runner


EXPECTED, DECOY, INCIDENT, EVENT, ALERT, GROUP, CALLER = (character * 32 for character in "abcdef1")


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class HTTPResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class ComprehensiveTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = runner.Client("https://example.service-now.com", {
            "mode": "basic", "username": "offline-fixture", "password": "offline-fixture"})

    def test_connector_envelopes_are_unwrapped_without_dropping_contract(self):
        expected = {"status": "error", "message": "Payload must be a JSON object or an array of JSON objects"}
        for payload in (expected, json.dumps(expected), {"listener": json.dumps(expected)},
                        {"result": {"listener": json.dumps(expected)}}):
            with self.subTest(payload=payload):
                self.assertEqual(runner.unwrap_connector(payload), expected)

    def test_connector_invalid_json_is_a_controlled_error(self):
        with self.assertRaises(runner.ApiError) as raised:
            runner.unwrap_connector("NOT_JSON_DO_NOT_LOG")
        self.assertNotIn("NOT_JSON_DO_NOT_LOG", str(raised.exception))

    def test_actual_event_management_http500_envelope_decodes_only_listener_error(self):
        inner = {"status": "error", "message": "Error: Payload must be a JSON object or an array of JSON objects",
                 "version": runner.EXPECTED_RELEASE,
                 "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")}}
        outer = {"error": {"message": "USBEM genericJsonV2 : " + json.dumps(inner), "detail": ""}, "status": "failure"}
        self.assertEqual(runner.unwrap_connector(outer), inner)
        self.assertEqual(runner.unwrap_connector({"result": outer}), inner)
        error = urllib.error.HTTPError("https://example.service-now.com/api", 500, "error", {},
                                       io.BytesIO(json.dumps(outer).encode()))
        with patch.object(self.client.opener, "open", side_effect=error) as opened:
            self.assertEqual(self.client.probe("genericJsonV2", None, 3), (500, inner))
        self.assertEqual(opened.call_count, 1)

    def test_em_error_json_decoder_does_not_accept_trailing_text_or_other_contracts(self):
        valid = {"status": "error", "message": "deliberate error", "version": runner.EXPECTED_RELEASE,
                 "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")}}
        for text in ("USBEM genericJsonV2 : " + json.dumps(valid) + " trailing text",
                     "USBEM genericJsonV2 : " + json.dumps(valid) + json.dumps(valid),
                     "USBEM genericJsonV2 : " + json.dumps(dict(valid, status="success")),
                     "USBEM genericJsonV2 : " + json.dumps({"status": "error", "message": "not a versioned listener"}),
                     "USBEM genericJsonV2 : " + json.dumps(dict(valid, versions="not an object"))):
            with self.subTest(text=text):
                outer = {"status": "failure", "error": {"message": text, "detail": ""}}
                result = runner.unwrap_connector(outer)
                self.assertEqual(result, outer)

    def test_query_is_exact_raw_read_with_no_mutation(self):
        with patch.object(self.client, "request", return_value=[]) as request:
            self.assertEqual(self.client.query("em_alert", "message_key=OWN-KEY", "sys_id,incident", 3), [])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], "GET")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[1]).query)
        self.assertEqual(query["sysparm_query"], ["message_key=OWN-KEY"])
        self.assertEqual(query["sysparm_display_value"], ["false"])
        self.assertEqual(query["sysparm_exclude_reference_link"], ["true"])

    def test_query_rejects_invalid_table_before_a_request(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaises(ValueError):
                self.client.query("incident/../../sys_user", "", "sys_id", 3)
        request.assert_not_called()

    def test_query_refuses_truncated_evidence(self):
        with patch.object(self.client, "request", return_value=[{"sys_id": EVENT}]):
            with self.assertRaises(runner.ApiError) as raised:
                self.client.query("em_event", "message_key=OWN-KEY", "sys_id", 3, limit=1)
        self.assertIn("complete evidence", str(raised.exception))

    def test_query_rejects_nonrecord_shapes(self):
        for payload in ({}, [None], ["row"], "[]"):
            with self.subTest(payload=payload), patch.object(self.client, "request", return_value=payload):
                with self.assertRaises(runner.ApiError):
                    self.client.query("em_event", "message_key=OWN-KEY", "sys_id", 3)

    def test_negative_probe_keeps_http_and_exact_connector_contract(self):
        body = {"status": "error", "message": "records must be an array of JSON objects",
                "version": runner.EXPECTED_RELEASE, "versions": {"listener": runner.EXPECTED_RELEASE}}
        response = urllib.error.HTTPError("https://example.service-now.com/api", 500, "error", {},
                                          io.BytesIO(json.dumps({"listener": json.dumps(body)}).encode()))
        with patch.object(self.client.opener, "open", side_effect=response) as opened:
            code, actual = self.client.probe("genericJsonV2", {"records": None}, 3)
        self.assertEqual((code, actual), (500, body))
        self.assertEqual(opened.call_count, 1)
        request = opened.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("User-agent"), "genericendpoint")
        self.assertEqual(json.loads(request.data), {"records": None})

    def test_negative_probe_never_retries_transport_failure(self):
        with patch.object(self.client.opener, "open", side_effect=TimeoutError("DO_NOT_LOG")) as opened:
            with self.assertRaises(runner.ApiError) as raised:
                self.client.probe("genericJsonV2", None, 3)
        self.assertEqual(opened.call_count, 1)
        self.assertNotIn("DO_NOT_LOG", str(raised.exception))

    def test_negative_probe_rejects_html_error_not_an_expected_json_failure(self):
        response = urllib.error.HTTPError("https://example.service-now.com/api", 500, "error", {},
                                          io.BytesIO(b"<html>DO_NOT_LOG_BODY</html>"))
        with patch.object(self.client.opener, "open", side_effect=response):
            with self.assertRaises(runner.ApiError) as raised:
                self.client.probe("genericJsonV2", None, 3)
        self.assertEqual(raised.exception.status, 500)
        self.assertNotIn("DO_NOT_LOG_BODY", str(raised.exception))

    def test_malformed_json_probe_is_sent_unchanged_once(self):
        with patch.object(self.client.opener, "open", return_value=HTTPResponse(b'{"status":"error"}')) as opened:
            self.client.probe("genericJsonV2", b'{"records":[', 3, raw=True)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(opened.call_args.args[0].data, b'{"records":[')

    def test_attachment_download_is_a_bounded_get(self):
        with patch.object(self.client.opener, "open", return_value=HTTPResponse(b'{"record_index":0}')) as opened:
            self.assertEqual(self.client.download(EVENT, 3), b'{"record_index":0}')
        self.assertEqual(opened.call_count, 1)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://example.service-now.com/api/now/attachment/" + EVENT + "/file")

    def test_attachment_download_rejects_oversize_evidence(self):
        with patch.object(self.client.opener, "open", return_value=HTTPResponse(b"x" * (4 * 1024 * 1024 + 1))):
            with self.assertRaises(runner.ApiError) as raised:
                self.client.download(EVENT, 3)
        self.assertIn("4 MiB", str(raised.exception))

    def test_attachment_download_invalid_id_does_not_request(self):
        with patch.object(self.client.opener, "open") as opened:
            with self.assertRaises(ValueError):
                self.client.download("../../other", 3)
        opened.assert_not_called()

    def test_attachment_error_does_not_disclose_body_or_retry(self):
        error = urllib.error.HTTPError("https://example.service-now.com/api", 403, "denied", {},
                                       io.BytesIO(b"DO_NOT_LOG_ATTACHMENT"))
        with patch.object(self.client.opener, "open", side_effect=error) as opened:
            with self.assertRaises(runner.ApiError) as raised:
                self.client.download(EVENT, 3)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(raised.exception.status, 403)
        self.assertNotIn("DO_NOT_LOG_ATTACHMENT", str(raised.exception))


def connector_response(key, event_id=EVENT, incident_id=INCIDENT):
    row = {"status": "success", "message_key": key, "event_sys_id": event_id,
           "incident_sys_id": incident_id, "dti_mode": "fast_async" if incident_id else "",
           "dti_incident_status": "created" if incident_id else "not_requested"}
    return {"status": "success", "inserted": "1", "version": runner.EXPECTED_RELEASE,
            "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")},
            "sys_ids": [event_id], "results": [row]}


class MemoryClient:
    """Small exact-query store. It intentionally has no ServiceNow connection."""
    def __init__(self):
        self.tables = {}
        self.pushes, self.queries, self.requests = [], [], []
        self.push_result = None
        self.probe_result = (500, {})
        self.downloads = {}
        self.request_error = None
        self.query_error = None

    def query(self, table, query, fields, timeout, limit=1000):
        self.queries.append((table, query, fields, timeout))
        if self.query_error:
            raise self.query_error
        rows = copy.deepcopy(self.tables.get(table, []))
        for part in query.split("^"):
            if "=" in part:
                field, expected = part.split("=", 1)
                rows = [row for row in rows if str(row.get(field, "")) == expected]
        return rows

    def request(self, method, path, body=None, timeout=90):
        self.requests.append((method, path, copy.deepcopy(body), timeout))
        if self.request_error:
            raise self.request_error
        table, record_id = path.rsplit("/", 2)[-2:]
        rows = [row for row in self.tables.get(table, []) if row.get("sys_id") == record_id]
        if method == "PATCH" and len(rows) == 1:
            rows[0].update(body)
            return copy.deepcopy(rows[0])
        return {}

    def push(self, source, payload, timeout):
        self.pushes.append(copy.deepcopy(payload))
        if callable(self.push_result):
            return self.push_result(payload)
        return copy.deepcopy(self.push_result)

    def probe(self, source, payload, timeout, raw=False):
        self.pushes.append(copy.deepcopy(payload))
        return copy.deepcopy(self.probe_result)

    def download(self, attachment_id, timeout):
        return self.downloads[attachment_id]


class ComprehensiveBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.client = Clock(), MemoryClient()
        self.settings = runner.Settings("genericJsonV2", "cmdb_ci_server", {"serial_number": "unit-test"},
            "decoy-name", EXPECTED, DECOY, caller_id=CALLER, category="hardware", expected_category="hardware",
            subcategory="cpu", expected_subcategory="cpu", impact="1", urgency="3", assignment_group=GROUP,
            expected_assignment_group_id=GROUP, timeout=8, stable_seconds=2, poll_seconds=1, request_timeout=3)
        self.suite = runner.ComprehensiveRunner(self.client, self.settings, {}, self.clock.monotonic, self.clock.sleep)
        self.suite.current_feature = "fast_camel_conflict"
        self.suite.features = [{"name": "fast_camel_conflict", "status": "pass"}]

    def ready_case(self, **overrides):
        payload = self.suite.payload("case")
        self.client.push_result = connector_response(payload["message_key"])
        case = self.suite.submit(payload, **overrides)
        self.client.tables = {
            "em_event": [{"sys_id": EVENT, "message_key": case["key"], "state": "Processed", "additional_info": "{}"}],
            "incident": [{"sys_id": INCIDENT, "number": "INC-OFFLINE", "state": "1", "correlation_id": case["key"],
                          "correlation_display": "USBEM DTI", **case["expected"]}],
            "em_alert": [{"sys_id": ALERT, "message_key": case["key"], "state": "Open", "incident": INCIDENT,
                          "task": "", "additional_info": "{}"}],
        }
        return case

    def test_manifest_declares_unique_features_and_covers_required_families(self):
        self.assertEqual(len(runner.FEATURE_MANIFEST), len(set(runner.FEATURE_MANIFEST)))
        for name in ("batch_records", "batch_events", "batch_array", "batch_mixed", "negative_records_member",
                     "incident_alert_notes", "debug_success", "debug_error", "terminal_6", "terminal_7", "terminal_8",
                     "foreign_incident_guard", "closed_alert_guard", "concurrent_first_events", "parser_contract"):
            self.assertIn(name, runner.FEATURE_MANIFEST)
        for wrapper in runner.PAYLOAD_WRAPPERS:
            self.assertIn("wrapped_" + wrapper, runner.FEATURE_MANIFEST)

    def test_aggregation_never_passes_no_tests_or_unrecognized_status(self):
        for features in ([], [{}], [{"status": "unknown"}], [{"status": "pending"}], [{"status": "running"}]):
            with self.subTest(features=features):
                self.assertEqual(runner.aggregate_status(features), "incomplete")

    def test_aggregation_does_not_hide_skips_failures_errors_or_known_race(self):
        for state, expected in (("skip", "incomplete"), ("fail", "fail"), ("error", "error"),
                                ("known_limitation", "complete_with_known_limitations")):
            with self.subTest(state=state):
                self.assertEqual(runner.aggregate_status([{"status": "pass"}, {"status": state}]), expected)

    def test_accepted_race_plus_skip_is_incomplete_not_complete_with_limitations(self):
        self.assertEqual(runner.aggregate_status([
            {"status": "pass"}, {"status": "known_limitation"}, {"status": "skip"}]), "incomplete")

    def test_missing_feature_fixture_never_calls_callback_and_is_incomplete(self):
        with patch.object(self.client, "push") as push:
            feature = self.suite.run_feature("service_name", lambda: push(), required=("service_name",))
        push.assert_not_called()
        self.assertEqual(feature["status"], "skip")
        self.assertEqual(runner.aggregate_status(self.suite.features), "incomplete")

    def test_comprehensive_run_without_assignment_group_is_incomplete_before_events(self):
        self.settings.assignment_group = ""
        self.settings.expected_assignment_group_id = ""
        self.suite.features = []
        report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])
        preflight = next(row for row in report["features"] if row["name"] == "read_preflight")
        self.assertEqual(preflight["status"], "skip")
        self.assertIn("group", preflight["reason"].lower())

    def test_complete_group_coverage_requires_payload_group_and_valid_expected_sysid(self):
        for group, expected in (("", GROUP), (GROUP, ""), ("Hardware", "not-a-sys-id")):
            with self.subTest(group=group, expected=expected):
                self.settings.assignment_group = group
                self.settings.expected_assignment_group_id = expected
                with self.assertRaises(runner.MissingFixture):
                    self.suite.check_group_fixture()
        self.settings.assignment_group = "Hardware"
        self.settings.expected_assignment_group_id = GROUP
        self.suite.check_group_fixture()
        self.assertEqual(self.client.pushes, [])

    def test_field_acl_omission_cannot_be_a_pass(self):
        case = self.ready_case()
        del self.client.tables["incident"][0]["caller_id"]
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "skip")
        self.assertEqual(runner.aggregate_status(self.suite.features), "incomplete")

    def test_403_is_incomplete_and_401_stops_further_writes(self):
        for code, expected in ((403, "skip"), (401, "error")):
            with self.subTest(code=code):
                self.setUp()
                def denied():
                    raise runner.ApiError("denied", code)
                feature = self.suite.run_feature("service_name", denied)
                self.assertEqual(feature["status"], expected)
                self.assertEqual(self.suite.permission_stop, code == 401)
                if code == 401:
                    with patch.object(self.client, "push") as push:
                        next_feature = self.suite.run_feature("offering_name", lambda: push())
                    push.assert_not_called()
                    self.assertEqual(next_feature["status"], "skip")

    def test_snapshot_requires_processed_event_and_real_br_link(self):
        for table, field, value, reason in (("em_event", "state", "Ready", "Event processing"),
                                           ("em_alert", "incident", "", "BR Alert/Incident link")):
            with self.subTest(table=table):
                self.setUp()
                case = self.ready_case()
                self.client.tables[table][0][field] = value
                self.assertFalse(self.suite.snapshot(case, 8))
                self.assertIn(reason, case["observations"][-1]["reasons"])

    def test_wrong_alert_incident_fails_immediately(self):
        case = self.ready_case()
        self.client.tables["em_alert"][0]["incident"] = "9" * 32
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_missing_alert_cannot_be_ready(self):
        case = self.ready_case()
        self.client.tables["em_alert"] = []
        self.assertFalse(self.suite.snapshot(case, 8))

    def test_every_required_incident_value_is_compared_exactly(self):
        for field in ("caller_id", "category", "subcategory", "impact", "urgency", "short_description", "description",
                      "assignment_group", "cmdb_ci"):
            with self.subTest(field=field):
                self.setUp()
                case = self.ready_case()
                self.client.tables["incident"][0][field] = "wrong"
                with self.assertRaises(runner.CheckFailed):
                    self.suite.snapshot(case, 8)

    def test_explicit_expected_blank_is_asserted_not_ignored(self):
        case = self.ready_case(expected={"business_service": ""})
        self.client.tables["incident"][0]["business_service"] = EXPECTED
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_expected_event_blank_and_context_are_asserted(self):
        case = self.ready_case(expected_event={"resource": "", "additional_info": '{"custom_context":{"event":{"unchanged":true}}}'})
        self.client.tables["em_event"][0]["resource"] = "unexpected"
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_duplicate_event_and_incident_counts_are_not_inferred_from_response(self):
        for table in ("em_event", "incident"):
            with self.subTest(table=table):
                self.setUp()
                case = self.ready_case()
                self.client.tables[table].append(dict(self.client.tables[table][0], sys_id="9" * 32))
                with self.assertRaises(runner.CheckFailed):
                    self.suite.snapshot(case, 8)

    def test_duplicate_identical_stored_rows_cannot_hide_behind_set_comparison(self):
        for table in ("em_event", "incident"):
            with self.subTest(table=table):
                self.setUp()
                case = self.ready_case()
                self.client.tables[table].append(copy.deepcopy(self.client.tables[table][0]))
                with self.assertRaises(runner.CheckFailed):
                    self.suite.snapshot(case, 8)

    def test_stable_window_observes_repeated_reads_before_passing(self):
        case = self.ready_case()
        self.suite.settle([case])
        self.assertEqual(self.clock.now, 2)
        self.assertEqual(case["stable_observed_seconds"], 2)
        self.assertEqual(len(case["observations"]), 3)
        self.assertFalse(case.get("observation_failed"))

    def test_late_processing_requires_full_stable_window(self):
        case = self.ready_case()
        original_query = self.client.query
        def pending_until_two(table, query, fields, timeout, limit=1000):
            rows = original_query(table, query, fields, timeout, limit)
            if table == "em_event" and self.clock.now < 2:
                rows[0]["state"] = "Ready"
            return rows
        self.client.query = pending_until_two
        self.suite.settle([case])
        self.assertEqual(self.clock.now, 4)
        self.assertEqual(case["stable_observed_seconds"], 2)

    def test_evidence_drift_after_ready_fails_not_a_new_stability_pass(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        self.client.tables["em_event"][0]["state"] = "Ready"
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_deliberate_new_event_phase_is_allowed_to_be_pending_before_reprocessing(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        row = connector_response(case["key"], "9" * 32, INCIDENT)["results"][0]
        self.suite.add_response(case, row, 0)
        self.assertIsNone(case["stable_since"])
        # The deliberate new Event is not visible yet; this is pending, not evidence drift.
        self.assertFalse(self.suite.snapshot(case, 8))
        self.assertIn("Event visibility", case["observations"][-1]["reasons"])

    def test_transient_reads_reset_continuous_dwell(self):
        case = self.ready_case()
        original_query = self.client.query
        seen = [False]
        def once_error(table, query, fields, timeout, limit=1000):
            if self.clock.now == 1 and not seen[0]:
                seen[0] = True
                raise runner.ApiError("temporary read", 503, True)
            return original_query(table, query, fields, timeout, limit)
        self.client.query = once_error
        self.suite.settle([case])
        self.assertEqual(self.clock.now, 4)
        self.assertEqual(case["transient_read_errors"], 1)

    def test_submit_never_retries_outcome_unknown_post(self):
        with patch.object(self.client, "push", side_effect=runner.ApiError("outcome unknown", retryable=True)) as push:
            with self.assertRaises(runner.ApiError):
                self.suite.submit(self.suite.payload("one-attempt"))
        self.assertEqual(push.call_count, 1)

    def test_payloads_default_to_no_legacy_wait_keys(self):
        for name in runner.FEATURE_MANIFEST:
            wire = self.suite.payload(name)
            self.assertFalse(any("wait" in key.lower() for key in wire))

    def test_batch_result_must_validate_each_record_unique_event_and_count(self):
        response = connector_response("key")
        self.assertEqual(len(self.suite.response_rows(response, 1)), 1)
        for broken in (dict(response, inserted="2"), dict(response, results=[None]), dict(response, sys_ids=[])):
            with self.subTest(broken=broken), self.assertRaises(runner.CheckFailed):
                self.suite.response_rows(broken, 1)

    def test_sequential_replay_requires_new_event_same_incident(self):
        case = self.ready_case()
        for row in (connector_response(case["key"])["results"][0],
                    connector_response(case["key"], "9" * 32, "8" * 32)["results"][0]):
            with self.subTest(row=row), self.assertRaises(runner.CheckFailed):
                self.suite.add_response(case, row, 0)

    def test_terminal_replacement_requires_new_incident_then_reuse(self):
        case = self.ready_case()
        old = INCIDENT
        with self.assertRaises(runner.CheckFailed):
            self.suite.add_response(case, connector_response(case["key"], "9" * 32, old)["results"][0], 0, replace=True)
        new = "8" * 32
        self.suite.add_response(case, connector_response(case["key"], "9" * 32, new)["results"][0], 0, replace=True)
        self.assertEqual(case["active_incident"], new)
        self.assertEqual(case["incident_ids"], {old, new})
        self.suite.add_response(case, connector_response(case["key"], "7" * 32, new)["results"][0], 0)
        self.assertEqual(case["active_incident"], new)

    def test_terminal_incident_must_remain_terminal_and_new_one_open(self):
        case = self.ready_case()
        case["terminal"][INCIDENT] = "6"
        case["active_incident"] = "8" * 32
        case["incident_ids"].add("8" * 32)
        old = self.client.tables["incident"][0]
        old["state"] = "6"
        self.client.tables["incident"].append(dict(old, sys_id="8" * 32, state="1"))
        self.client.tables["em_alert"][0]["incident"] = "8" * 32
        self.assertTrue(self.suite.snapshot(case, 8))
        old["state"] = "1"
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def replacement_alert_fixture(self):
        case = self.ready_case()
        replacement = "8" * 32
        case["terminal"][INCIDENT] = "6"
        case["active_incident"] = replacement
        case["incident_ids"].add(replacement)
        self.client.tables["incident"][0]["state"] = "6"
        self.client.tables["incident"].append(dict(self.client.tables["incident"][0], sys_id=replacement, state="1"))
        old_alert = self.client.tables["em_alert"][0]
        old_alert.update(state="Closed", incident=INCIDENT)
        new_alert = dict(old_alert, sys_id="7" * 32, state="Open", incident=replacement)
        self.client.tables["em_alert"].append(new_alert)
        return case, old_alert, new_alert

    def test_terminal_closed_historical_alert_and_open_replacement_alert_are_valid(self):
        case, old_alert, _new_alert = self.replacement_alert_fixture()
        self.assertTrue(self.suite.snapshot(case, 8))
        self.assertEqual(old_alert["incident"], INCIDENT)
        self.assertEqual(old_alert["state"], "Closed")

    def test_only_closed_historical_alert_waits_for_active_replacement_alert(self):
        case, old_alert, _new_alert = self.replacement_alert_fixture()
        self.client.tables["em_alert"] = [old_alert]
        self.assertFalse(self.suite.snapshot(case, 8))

    def test_closed_historical_alert_never_exempts_a_foreign_incident_link(self):
        case, old_alert, _new_alert = self.replacement_alert_fixture()
        old_alert["incident"] = "9" * 32
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_open_old_link_is_transitional_until_replacement_link_arrives(self):
        case, old_alert, _new_alert = self.replacement_alert_fixture()
        old_alert["state"] = "Open"
        self.client.tables["em_alert"] = [old_alert]
        self.assertFalse(self.suite.snapshot(case, 8))
        old_alert["incident"] = case["active_incident"]
        self.assertTrue(self.suite.snapshot(case, 8))

    def test_ready_replacement_link_drifting_to_old_open_incident_fails(self):
        case, _old_alert, new_alert = self.replacement_alert_fixture()
        self.assertTrue(self.suite.snapshot(case, 8))
        new_alert["incident"] = INCIDENT
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, 8)

    def test_all_closed_alerts_do_not_prove_an_active_replacement_link(self):
        case, old_alert, new_alert = self.replacement_alert_fixture()
        old_alert["state"] = "closed"
        new_alert["state"] = "Closed"
        self.assertFalse(self.suite.snapshot(case, 8))

    def test_patch_requires_registered_fresh_marker_and_dti_provenance(self):
        case = self.ready_case()
        self.suite.patch_owned("incident", INCIDENT, {"state": "6"})
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0][0], "PATCH")
        self.assertEqual(self.client.requests[0][2], {"state": "6"})

    def test_patch_foreign_unregistered_record_has_zero_writes(self):
        self.ready_case()
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("incident", "9" * 32, {"state": "6"})
        self.assertEqual(self.client.requests, [])

    def test_owned_alert_patch_cannot_link_to_an_unowned_incident(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("em_alert", ALERT, {"incident": "9" * 32})
        self.assertEqual(self.client.requests, [])

    def task_fixture(self):
        record_id = "2" * 32
        row = {"sys_id": record_id, "sys_class_name": "change_request", "number": "CHG-OFFLINE",
               "short_description": "[TEST] USBEM foreign Task fixture", "state": "-5", "sys_updated_on": "2026-10-29 15:00:00",
               "sys_mod_count": "0"}
        self.client.tables["task"] = [row]
        self.client.tables["sys_dictionary"] = [{"sys_id": "3" * 32, "name": "em_alert", "element": "incident",
                                                   "internal_type": "reference", "reference": "task"}]
        self.suite.fixtures["foreign_task_sys_id"] = record_id
        return record_id, row

    def test_foreign_task_fixture_needs_nonincident_class_and_explicit_test_marker(self):
        for field, value in (("sys_class_name", "incident"), ("sys_class_name", ""),
                             ("short_description", "Real business work")):
            with self.subTest(field=field, value=value):
                self.setUp()
                record_id, row = self.task_fixture()
                row[field] = value
                with self.assertRaises(runner.MissingFixture):
                    self.suite.validate_task_fixture(record_id)
                self.assertEqual(self.client.requests, [])
        record_id, row = self.task_fixture()
        row["sys_class_name"] = "task"
        self.assertEqual(self.suite.validate_task_fixture(record_id), row)

    def test_foreign_task_marker_override_cannot_authorize_arbitrary_business_task(self):
        record_id, row = self.task_fixture()
        row["short_description"] = "Real business work"
        self.suite.fixtures["foreign_task_marker"] = "Real business"
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_task_fixture(record_id)
        self.assertEqual(self.client.requests, [])

    def test_foreign_task_missing_baseline_field_is_incomplete(self):
        record_id, row = self.task_fixture()
        del row["sys_updated_on"]
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_task_fixture(record_id)

    def test_foreign_task_baseline_drift_is_failure_and_blocks_owned_alert_link(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        record_id, row = self.task_fixture()
        self.suite.validated_task_fixtures[record_id] = self.suite.validate_task_fixture(record_id)
        row["state"] = "3"
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("em_alert", ALERT, {"task": record_id})
        self.assertEqual(self.client.requests, [])

    def test_foreign_task_same_second_modcount_change_invalidates_baseline(self):
        record_id, row = self.task_fixture()
        self.suite.validated_task_fixtures[record_id] = self.suite.validate_task_fixture(record_id)
        before_time = row["sys_updated_on"]
        row["sys_mod_count"] = "1"
        self.assertEqual(row["sys_updated_on"], before_time)
        with self.assertRaises(runner.CheckFailed):
            self.suite.validate_task_fixture(record_id)
        self.assertEqual(self.client.requests, [])

    def test_unvalidated_task_reference_has_zero_writes_even_on_owned_alert(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        record_id, _ = self.task_fixture()
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("em_alert", ALERT, {"task": record_id})
        self.assertEqual(self.client.requests, [])

    def test_foreign_task_guard_writes_only_owned_alert_and_asserts_unchanged_task(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        record_id, row = self.task_fixture()
        before = copy.deepcopy(row)
        def replay(replayed_case, note):
            self.assertIs(replayed_case, case)
            self.assertEqual(self.client.tables["em_alert"][0]["incident"], record_id)
            self.assertTrue(note.startswith(self.suite.prefix))
            return case
        with patch.object(self.suite, "submit", return_value=case) as submissions, patch.object(self.suite, "settle"), \
                patch.object(self.suite, "submit_non_dti_guard_replay", side_effect=replay) as replayed, \
                patch.object(self.suite, "assert_note") as notes, patch.object(self.suite, "assert_consumed_notes") as consumed:
            result = self.suite.foreign_task_case()
        self.assertEqual(result["preprovisioned_test_task_sys_id"], record_id)
        self.assertEqual(result["task_writes"], 0)
        self.assertTrue(result["task_unchanged"])
        self.assertEqual(row, before)
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(submissions.call_count, 1)
        replayed.assert_called_once()
        self.assertTrue(all(request[0] == "PATCH" and request[1].endswith("/em_alert/" + ALERT)
                            for request in self.client.requests))
        self.assertEqual(self.client.requests[0][2], {"incident": record_id})
        self.assertEqual(case["expected_alert_incident"], record_id)
        self.assertEqual(result["alert_link_field"], "incident")
        self.assertEqual([call.args[2] for call in notes.call_args_list], [1, 0, 0])
        self.assertEqual(notes.call_args_list[0].args[0], [ALERT])
        self.assertEqual(notes.call_args_list[1].args[0], [INCIDENT])
        self.assertEqual(notes.call_args_list[2].args[0], [record_id])
        consumed.assert_called_once()

    def test_foreign_task_guard_fails_if_br_injects_an_incident(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        self.task_fixture()
        def bad_reconcile(_case, _note):
            self.client.tables["em_alert"][0]["incident"] = INCIDENT
            return case
        with patch.object(self.suite, "submit", return_value=case) as submissions, patch.object(self.suite, "settle"), \
                patch.object(self.suite, "submit_non_dti_guard_replay", side_effect=bad_reconcile) as replayed, \
                patch.object(self.suite, "assert_note") as notes:
            with self.assertRaises(runner.CheckFailed) as raised:
                self.suite.foreign_task_case()
        self.assertIn("foreign Task guard link", str(raised.exception))
        self.assertEqual(submissions.call_count, 1)
        replayed.assert_called_once()
        notes.assert_not_called()
        self.assertTrue(all("/task/" not in request[1] for request in self.client.requests))

    def test_additional_info_patch_is_forbidden_even_for_owned_alert(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        with self.assertRaises(ValueError):
            self.suite.patch_owned("em_alert", ALERT, {"additional_info": '{"alert_work_notes":"ignored by native ACL"}'})
        self.assertEqual(self.client.requests, [])

    def foreign_guard_cases(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        foreign_id = "4" * 32
        self.suite.owned[("incident", foreign_id)] = self.suite.prefix + "-foreign-owner"
        foreign = copy.deepcopy(case)
        foreign["active_incident"] = foreign_id
        return case, foreign, foreign_id

    def test_foreign_incident_guard_replays_connector_note_after_fresh_link_readback(self):
        case, foreign, foreign_id = self.foreign_guard_cases()
        def replay(replayed_case, note):
            self.assertEqual(self.client.tables["em_alert"][0]["incident"], foreign_id)
            self.assertEqual(self.client.tables["em_alert"][0]["task"], foreign_id)
            self.assertIs(replayed_case, case)
            self.assertTrue(note.startswith(self.suite.prefix))
            return case
        with patch.object(self.suite, "submit", side_effect=[case, foreign]) as submit_mock, patch.object(self.suite, "settle"), \
                patch.object(self.suite, "submit_non_dti_guard_replay", side_effect=replay) as replayed, \
                patch.object(self.suite, "assert_note") as notes, patch.object(self.suite, "assert_consumed_notes") as consumed:
            result = self.suite.guard_case()
        self.assertEqual(submit_mock.call_count, 2)
        replayed.assert_called_once()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0][2], {"incident": foreign_id, "task": foreign_id})
        self.assertEqual(result["trigger"], "NON-DTI connector replay with unique Alert note")
        self.assertEqual([call.args[2] for call in notes.call_args_list], [1, 0])
        self.assertEqual(notes.call_args_list[1].args[0], [INCIDENT, foreign_id])
        consumed.assert_called_once()

    def test_ignored_foreign_link_patch_fails_before_replay_and_cannot_look_tested(self):
        case, foreign, _foreign_id = self.foreign_guard_cases()
        with patch.object(self.client, "request", return_value={}), \
                patch.object(self.suite, "submit", side_effect=[case, foreign]) as submissions, \
                patch.object(self.suite, "settle"):
            with self.assertRaises(runner.CheckFailed) as raised:
                self.suite.guard_case()
        self.assertIn("foreign Incident guard fixture readback", str(raised.exception))
        self.assertEqual(submissions.call_count, 2)

    def test_closed_guard_uses_existing_dti_condition_without_metadata_patch_or_replay(self):
        case = self.ready_case()
        self.client.tables["em_alert"][0]["additional_info"] = '{"direct_to_incident":"true"}'
        self.assertTrue(self.suite.snapshot(case, 8))
        with patch.object(self.suite, "submit", return_value=case) as submissions, patch.object(self.suite, "settle"), \
                patch.object(self.suite, "assert_note") as notes:
            result = self.suite.guard_case(closed=True)
        self.assertEqual(submissions.call_count, 1)
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0][2], {"state": "Closed", "incident": "", "task": ""})
        self.assertEqual(result["trigger"], "closed state/link update with stored DTI metadata")
        notes.assert_not_called()

    def test_closed_guard_without_stored_dti_condition_has_zero_patches(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        with patch.object(self.suite, "submit", return_value=case), patch.object(self.suite, "settle"):
            with self.assertRaises(runner.CheckFailed):
                self.suite.guard_case(closed=True)
        self.assertEqual(self.client.requests, [])

    def test_closed_guard_cannot_pass_if_stored_dti_condition_is_lost_after_patch(self):
        case = self.ready_case()
        self.client.tables["em_alert"][0]["additional_info"] = '{"direct_to_incident":"true"}'
        self.assertTrue(self.suite.snapshot(case, 8))
        original_request = self.client.request
        def loses_metadata(method, path, body=None, timeout=90):
            result = original_request(method, path, body, timeout)
            self.client.tables["em_alert"][0]["additional_info"] = "{}"
            return result
        self.client.request = loses_metadata
        with patch.object(self.suite, "submit", return_value=case) as submissions, patch.object(self.suite, "settle"):
            with self.assertRaises(runner.CheckFailed) as raised:
                self.suite.guard_case(closed=True)
        self.assertIn("stored DTI condition metadata", str(raised.exception))
        self.assertEqual(submissions.call_count, 1)

    def non_dti_guard_fixture(self, task=False):
        feature = "foreign_task_guard" if task else "foreign_incident_guard"
        self.suite.current_feature = feature
        self.suite.features = [{"name": feature, "status": "pass"}]
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, 8))
        if task:
            target, _row = self.task_fixture()
            self.suite.validated_task_fixtures[target] = self.suite.validate_task_fixture(target)
            self.suite.validated_task_link_fields.add("incident")
        else:
            target = "4" * 32
            foreign_key = self.suite.prefix + "-foreign-owner"
            self.suite.owned[("incident", target)] = foreign_key
            self.client.tables["incident"].append({"sys_id": target, "correlation_id": foreign_key,
                                                    "correlation_display": "USBEM DTI"})
        case["expected_alert_incident"] = target
        self.client.tables["em_alert"][0]["incident"] = target
        self.client.pushes.clear()
        self.client.push_result = connector_response(case["key"], event_id="5" * 32, incident_id="")
        return case, self.suite.prefix + " isolated Alert-only note", target

    def test_non_dti_guard_replay_appends_only_event_without_changing_incident_expectations(self):
        case, note, _target = self.non_dti_guard_fixture()
        before = copy.deepcopy({key: case[key] for key in ("want_incident", "active_incident", "incident_ids", "expected", "payload")})
        ownership = copy.deepcopy(self.suite.owned)
        initial_events, initial_submissions = list(case["event_ids"]), len(case["submissions"])
        case["was_ready"], case["stable_since"] = True, 123
        self.assertIs(self.suite.submit_non_dti_guard_replay(case, note), case)
        self.assertEqual({key: case[key] for key in before}, before)
        self.assertEqual(self.suite.owned, ownership)
        self.assertEqual(case["event_ids"], initial_events + ["5" * 32])
        self.assertEqual(len(case["submissions"]), initial_submissions + 1)
        self.assertEqual(case["submissions"][-1]["incident_sys_id"], "")
        self.assertEqual(case["submissions"][-1]["response_expectation"], "isolated_non_dti_guard_no_incident")
        self.assertIsNone(case["stable_since"])
        self.assertFalse(case["was_ready"])
        self.assertEqual(len(self.client.pushes), 1)

    def test_non_dti_guard_wire_strips_dti_and_incident_notes_from_all_supported_contexts(self):
        for string_info in (False, True):
            with self.subTest(string_info=string_info):
                self.setUp()
                case, note, _target = self.non_dti_guard_fixture()
                consumed = {"direct_to_incident": True, "directToIncident": True, "work_notes": "must not copy",
                            "dti_work_note": "must not copy", "dtiWorkNote": "must not copy"}
                case["payload"].update(consumed)
                info = dict(consumed, custom_context={"native": True, "count": 7})
                case["payload"]["additional_info"] = json.dumps(info) if string_info else info
                case["payload"]["additionalInfo"] = copy.deepcopy(info)
                before = copy.deepcopy(case["payload"])
                self.suite.submit_non_dti_guard_replay(case, note)
                wire = self.client.pushes[0]
                self.assertEqual(case["payload"], before)
                self.assertFalse(set(consumed).intersection(wire))
                self.assertEqual(wire["alert_work_notes"], note)
                for alias in ("additional_info", "additionalInfo"):
                    actual = json.loads(wire[alias]) if isinstance(wire[alias], str) else wire[alias]
                    self.assertFalse(set(consumed).intersection(actual))
                    self.assertEqual(actual["custom_context"], {"native": True, "count": 7})
                self.assertFalse({"wait", "wait_for_alert", "dti_wait", "dti_wait_for_alert"}.intersection(wire))

    def test_non_dti_guard_requires_registered_case_identity_and_current_guard_feature(self):
        for invalid in ("copied_case", "ordinary_feature", "wrong_current_feature", "not_dti_case", "foreign_key", "unowned_active_incident"):
            with self.subTest(invalid=invalid):
                self.setUp()
                case, note, _target = self.non_dti_guard_fixture()
                if invalid == "copied_case": case = copy.deepcopy(case)
                elif invalid == "ordinary_feature": case["feature"] = self.suite.current_feature = "fast_camel_conflict"
                elif invalid == "wrong_current_feature": self.suite.current_feature = "foreign_task_guard"
                elif invalid == "not_dti_case": case["want_incident"] = False
                elif invalid == "foreign_key": case["key"] = "NOT-OWNED"
                else: self.suite.owned.pop(("incident", INCIDENT))
                with self.assertRaises(runner.CheckFailed):
                    self.suite.submit_non_dti_guard_replay(case, note)
                self.assertEqual(self.client.pushes, [])

    def test_non_dti_guard_note_target_and_flat_payload_must_be_explicitly_safe(self):
        for invalid in ("foreign_note", "blank_note", "original_target", "unknown_target", "payload_key_drift", "nested_wrapper"):
            with self.subTest(invalid=invalid):
                self.setUp()
                case, note, _target = self.non_dti_guard_fixture()
                if invalid == "foreign_note": note = "not this run"
                elif invalid == "blank_note": note = ""
                elif invalid == "original_target": case["expected_alert_incident"] = INCIDENT
                elif invalid == "unknown_target": case["expected_alert_incident"] = "9" * 32
                elif invalid == "payload_key_drift": case["payload"]["message_key"] = self.suite.prefix + "-different"
                else: case["payload"]["event"] = {"direct_to_incident": True}
                with self.assertRaises(runner.CheckFailed):
                    self.suite.submit_non_dti_guard_replay(case, note)
                self.assertEqual(self.client.pushes, [])

    def test_non_dti_guard_foreign_incident_provenance_is_freshly_verified(self):
        for field, value in (("correlation_id", "foreign"), ("correlation_display", "not DTI")):
            with self.subTest(field=field):
                self.setUp()
                case, note, target = self.non_dti_guard_fixture()
                next(row for row in self.client.tables["incident"] if row["sys_id"] == target)[field] = value
                with self.assertRaises(runner.CheckFailed):
                    self.suite.submit_non_dti_guard_replay(case, note)
                self.assertEqual(self.client.pushes, [])

    def test_non_dti_guard_requires_one_registered_alert_and_fresh_foreign_link(self):
        for invalid in ("missing_alert", "multiple_alerts", "unowned_alert", "changed_link"):
            with self.subTest(invalid=invalid):
                self.setUp()
                case, note, _target = self.non_dti_guard_fixture()
                if invalid == "missing_alert": case["last_alerts"] = []
                elif invalid == "multiple_alerts": case["last_alerts"] *= 2
                elif invalid == "unowned_alert": self.suite.owned.pop(("em_alert", ALERT))
                else: self.client.tables["em_alert"][0]["incident"] = INCIDENT
                with self.assertRaises(runner.CheckFailed):
                    self.suite.submit_non_dti_guard_replay(case, note)
                self.assertEqual(self.client.pushes, [])

    def test_non_dti_guard_accepts_only_unchanged_explicitly_validated_test_task(self):
        case, note, _target = self.non_dti_guard_fixture(task=True)
        self.suite.submit_non_dti_guard_replay(case, note)
        self.assertEqual(len(self.client.pushes), 1)
        self.setUp()
        case, note, _target = self.non_dti_guard_fixture(task=True)
        self.client.tables["task"][0]["sys_mod_count"] = "1"
        with self.assertRaises(runner.CheckFailed):
            self.suite.submit_non_dti_guard_replay(case, note)
        self.assertEqual(self.client.pushes, [])

    def test_non_dti_guard_response_must_be_versioned_fresh_and_incident_free_before_bookkeeping(self):
        for invalid in ("incident", "old_event", "row_key", "row_status", "version", "inserted_count", "event_id_list"):
            with self.subTest(invalid=invalid):
                self.setUp()
                case, note, _target = self.non_dti_guard_fixture()
                response = self.client.push_result
                if invalid == "incident": response["results"][0]["incident_sys_id"] = INCIDENT
                elif invalid == "old_event": response["results"][0]["event_sys_id"] = EVENT; response["sys_ids"] = [EVENT]
                elif invalid == "row_key": response["results"][0]["message_key"] = "foreign"
                elif invalid == "row_status": response["results"][0]["status"] = "error"
                elif invalid == "version": response["versions"]["core"] = "wrong"
                elif invalid == "inserted_count": response["inserted"] = "2"
                else: response["sys_ids"] = ["6" * 32]
                before = copy.deepcopy({key: case[key] for key in ("event_ids", "submissions", "incident_ids", "active_incident", "want_incident")})
                with self.assertRaises(runner.CheckFailed):
                    self.suite.submit_non_dti_guard_replay(case, note)
                self.assertEqual({key: case[key] for key in before}, before)
                self.assertEqual(len(self.client.pushes), 1)

    def test_non_dti_guard_transport_failure_is_one_shot_and_does_not_bookkeep_unknown_event(self):
        case, note, _target = self.non_dti_guard_fixture()
        before = copy.deepcopy(case["event_ids"])
        with patch.object(self.client, "push", side_effect=runner.ApiError("unknown outcome", retryable=True)) as push:
            with self.assertRaises(runner.ApiError):
                self.suite.submit_non_dti_guard_replay(case, note)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(case["event_ids"], before)

    def test_non_dti_guard_slow_post_does_not_append_a_false_success(self):
        case, note, _target = self.non_dti_guard_fixture()
        before = list(case["event_ids"])
        def slow_post(*_args):
            self.clock.now += self.settings.fast_post_max_seconds + 1
            return self.client.push_result
        with patch.object(self.client, "push", side_effect=slow_post) as push:
            with self.assertRaises(runner.CheckFailed):
                self.suite.submit_non_dti_guard_replay(case, note)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(case["event_ids"], before)

    def test_secondary_observer_failure_preserves_primary_reason_status_and_http_code(self):
        case = self.ready_case()
        feature = self.suite.features[0]
        feature.update(status="error", reason="primary connector authentication failure", http_status=401)
        self.suite.observation_error(case, runner.ApiError("secondary field denied", 403))
        self.assertEqual((feature["status"], feature["reason"], feature["http_status"]),
                         ("error", "primary connector authentication failure", 401))
        self.assertEqual(feature["additional_failures"], [{"phase": "stored_observation", "status": "skip",
                                                          "reason": "secondary field denied", "http_status": 403}])
        self.assertTrue(case["observation_failed"])

    def test_feature_execution_preserves_prior_primary_failure_and_collects_later_api_error(self):
        def callback():
            feature = self.suite.features[-1]
            self.suite.feature_problem(feature, "fail", "primary response mismatch", "response_validation")
            raise runner.ApiError("secondary API failure", 500)
        feature = self.suite.run_feature("foreign_incident_guard", callback)
        self.assertEqual((feature["status"], feature["reason"]), ("fail", "primary response mismatch"))
        self.assertNotIn("http_status", feature)
        self.assertEqual(feature["additional_failures"][0], {"phase": "feature_execution", "status": "error",
                                                          "reason": "secondary API failure", "http_status": 500})

    def test_first_observer_failure_still_changes_a_previously_passing_feature(self):
        case = self.ready_case()
        self.suite.observation_error(case, runner.CheckFailed("first stored linkage failure"))
        feature = self.suite.features[0]
        self.assertEqual((feature["status"], feature["reason"]), ("fail", "first stored linkage failure"))
        self.assertNotIn("additional_failures", feature)

    def test_patch_changed_marker_or_missing_provenance_has_zero_writes(self):
        for field, value in (("correlation_id", "FOREIGN"), ("correlation_display", "not-DTI")):
            with self.subTest(field=field):
                self.setUp()
                self.ready_case()
                self.client.tables["incident"][0][field] = value
                with self.assertRaises(runner.CheckFailed):
                    self.suite.patch_owned("incident", INCIDENT, {"state": "6"})
                self.assertEqual(self.client.requests, [])

    def test_patch_arbitrary_tables_fields_and_empty_patch_have_zero_requests(self):
        self.ready_case()
        for table, updates in (("sys_user", {"active": False}), ("incident", {"caller_id": CALLER}),
                               ("incident", {}), ("em_alert", {"message_key": "FOREIGN"})):
            with self.subTest(table=table, updates=updates), self.assertRaises(ValueError):
                self.suite.patch_owned(table, INCIDENT, updates)
        self.assertEqual(self.client.requests, [])

    def test_patch_transport_error_never_retries(self):
        self.ready_case()
        self.client.request_error = runner.ApiError("outcome unknown", retryable=True)
        with self.assertRaises(runner.ApiError):
            self.suite.patch_owned("incident", INCIDENT, {"state": "6"})
        self.assertEqual(len(self.client.requests), 1)

    def test_negative_requires_expected_message_status_and_every_component_version(self):
        expected = "records must be an array of JSON objects"
        valid = {"status": "error", "message": "Error: " + expected, "version": runner.EXPECTED_RELEASE,
                 "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")}}
        for code, body in ((500, {"status": "error", "message": "some unrelated error"}),
                           (200, valid), (403, valid), (500, dict(valid, versions={})),
                           (500, dict(valid, status="success"))):
            with self.subTest(code=code, body=body):
                self.client.probe_result = (code, body)
                with self.assertRaises((runner.CheckFailed, runner.ApiError)):
                    self.suite.negative("records", {"records": None}, expected)

    def test_negative_mixed_batch_asserts_zero_effects_for_valid_first_member(self):
        key = self.suite.prefix + "-bad-batch-first"
        expected = "Event at index 1 must be a JSON object"
        self.client.probe_result = (500, {"status": "error", "message": "Error: " + expected,
            "version": runner.EXPECTED_RELEASE,
            "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")}})
        for table, field in (("em_event", "message_key"), ("incident", "correlation_id"), ("em_alert", "message_key")):
            with self.subTest(table=table):
                self.client.tables = {table: [{"sys_id": EVENT, field: key}]}
                with self.assertRaises(runner.CheckFailed):
                    self.suite.negative("bad-member", {"records": [{"message_key": key}, None]}, expected, (key,))

    def test_exact_journal_count_and_no_foreign_journal_reads(self):
        self.ready_case()
        self.client.tables["sys_journal_field"] = [{"sys_id": "9" * 32, "element_id": INCIDENT, "element": "work_notes", "value": "NOTE"}]
        self.suite.assert_note([INCIDENT], "NOTE", 1, "creation")
        for expected in (0, 2):
            with self.subTest(expected=expected), self.assertRaises(runner.CheckFailed):
                self.suite.assert_note([INCIDENT], "NOTE", expected, "creation")
        before = len(self.client.queries)
        with self.assertRaises(runner.CheckFailed):
            self.suite.journals("8" * 32, "NOTE")
        self.assertEqual(len(self.client.queries), before)

    def test_missing_journal_value_is_incomplete_not_zero_notes(self):
        self.ready_case()
        self.client.tables["sys_journal_field"] = [{"sys_id": "9" * 32, "element_id": INCIDENT, "element": "work_notes"}]
        with self.assertRaises(runner.MissingFixture):
            self.suite.journals(INCIDENT, "NOTE")

    def test_notes_case_submits_followup_then_two_note_free_updates(self):
        payload = self.suite.payload("notes", work_notes="INCIDENT", alert_work_notes="ALERT")
        case = {"active_incident": INCIDENT, "last_alerts": [{"sys_id": ALERT, "additional_info": "{}"}]}
        calls = []
        def submit(payload, **kwargs):
            calls.append(copy.deepcopy(kwargs.get("wire", payload)))
            return case
        with patch.object(self.suite, "submit", side_effect=submit), patch.object(self.suite, "settle"), \
                patch.object(self.suite, "assert_note") as notes:
            result = self.suite.notes_case()
        self.assertEqual(len(calls), 4)
        self.assertIn("work_notes", calls[0])
        self.assertIn("alert_work_notes", calls[0])
        self.assertNotIn("work_notes", calls[1])
        self.assertIn("ALERT-FOLLOWUP-AFTER-LINK", calls[1]["alert_work_notes"])
        self.assertTrue(all("work_notes" not in wire and "alert_work_notes" not in wire for wire in calls[2:]))
        self.assertEqual(result["no_note_updates"], 2)
        self.assertTrue(any(call.args[2] == 0 for call in notes.call_args_list))

    def test_pending_note_metadata_after_processing_fails(self):
        for metadata in ('{"alert_work_notes":"still pending"}', '{"work_notes":"still pending"}', "not JSON"):
            with self.subTest(metadata=metadata):
                case = {"active_incident": INCIDENT, "last_alerts": [{"sys_id": ALERT, "additional_info": metadata}]}
                with patch.object(self.suite, "submit", return_value=case), patch.object(self.suite, "settle"), \
                        patch.object(self.suite, "assert_note"), self.assertRaises(runner.CheckFailed):
                    self.suite.notes_case()

    def debug_fixture(self, error=False, plain=False):
        payload = self.suite.payload("debug-error" if error else "debug-plain" if plain else "debug-success", usbem_debug=True)
        if plain:
            payload.pop("direct_to_incident")
        response = connector_response(payload["message_key"], incident_id="" if plain else INCIDENT)
        response["debug_raw_event_sys_id"] = "9" * 32
        if error:
            response.update(status="error", message="Error: Event at index 1 must be a JSON object")
        names = self.suite.DEBUG_NAMES
        bodies = {
            names[0]: {"usbem_debug": True, "records": [payload, None]} if error else payload,
            names[1]: [] if error else [{"record_index": 0, "normalized_input": {}, "raw_event": payload}],
            names[2]: [] if error else [{"record_index": 0, "event_sys_id": EVENT, "final_event": {}}],
            names[3]: [] if error else [{"record_index": 0, "steps": [], "lookups": {}, "notes": [], "errors": []}],
            names[4]: [] if error else [{"record_index": 0, "candidates": {}}],
            names[5]: [] if error else [{"record_index": 0, "event_sys_id": EVENT, "message_key": payload["message_key"],
                                       "source": payload["source"], "event_class": payload["event_class"]}],
            names[6]: [] if error else [{"record_index": 0, "processing_ms": "1", "perf": {}, "quality": {}}],
            names[7]: response,
        }
        if error:
            bodies[names[9]] = {"error": "Error: Event at index 1 must be a JSON object"}
        elif not plain:
            bodies[names[8]] = [{"record_index": 0, "direct_to_incident": True, "wait_for_alert": False,
                                "wait_for_incident": False, "dti": {}, "result": response["results"][0]}]
        self.client.probe_result = (500, response)
        case = {"response": response, "event_ids": [EVENT], "key": payload["message_key"]}
        return payload, case, bodies

    def run_debug_fixture(self, error=False, mutate=None, plain=False):
        payload, case, bodies = self.debug_fixture(error, plain)
        if mutate:
            mutate(bodies)
        attachment_rows = []
        for index, (name, body) in enumerate(bodies.items(), 20):
            attachment_id = format(index, "032x")
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.client.downloads[attachment_id] = raw
            attachment_rows.append({"sys_id": attachment_id, "file_name": name, "size_bytes": str(len(raw)),
                                    "content_type": "application/json", "table_name": "em_event", "table_sys_id": "9" * 32})
        payload_for_builder = dict(payload, direct_to_incident=True) if plain else payload
        companion = {"sys_id": "9" * 32, "severity": "5", "additional_info": json.dumps({
            "usbem_version": runner.EXPECTED_RELEASE, "usbem_debug_parent_event_sys_ids": EVENT,
            "usbem_debug_parent_message_keys": case["key"]})}
        with patch.object(self.suite, "payload", return_value=payload_for_builder), \
                patch.object(self.suite, "submit", return_value=case), \
                patch.object(self.suite, "exact", return_value=companion), \
                patch.object(self.suite, "query", return_value=attachment_rows):
            return self.suite.debug_case(error, plain=plain)

    def test_successful_dti_debug_requires_nine_not_unconditional_ten_files(self):
        result = self.run_debug_fixture()
        self.assertEqual(len(result["attachments"]), 9)
        names = {row["file_name"] for row in result["attachments"]}
        self.assertIn("09_dti_timeline.json", names)
        self.assertNotIn("10_error_context.json", names)
        self.assertTrue(all(len(row["sha256"]) == 64 for row in result["attachments"]))

    def test_error_debug_has_conditional_tenth_name_but_no_dti_timeline(self):
        result = self.run_debug_fixture(error=True)
        names = {row["file_name"] for row in result["attachments"]}
        self.assertEqual(len(names), 9)
        self.assertIn("10_error_context.json", names)
        self.assertNotIn("09_dti_timeline.json", names)

    def test_plain_debug_requires_eight_base_files_without_dti_or_error(self):
        result = self.run_debug_fixture(plain=True)
        names = {row["file_name"] for row in result["attachments"]}
        self.assertEqual(len(names), 8)
        self.assertNotIn("09_dti_timeline.json", names)
        self.assertNotIn("10_error_context.json", names)

    def test_debug_json_metadata_must_match_exact_download_size(self):
        payload, case, bodies = self.debug_fixture()
        rows = []
        for index, (name, body) in enumerate(bodies.items(), 20):
            attachment_id = format(index, "032x")
            raw = json.dumps(body).encode()
            self.client.downloads[attachment_id] = raw
            rows.append({"sys_id": attachment_id, "file_name": name, "size_bytes": len(raw) + 1})
        with patch.object(self.suite, "payload", return_value=payload), \
                patch.object(self.suite, "submit", return_value=case), \
                patch.object(self.suite, "exact", return_value={"severity": "5"}), \
                patch.object(self.suite, "query", return_value=rows), self.assertRaises(runner.CheckFailed):
            self.suite.debug_case()

    def test_debug_missing_attachment_or_unconditional_error_attachment_fails(self):
        for mutate in (lambda bodies: bodies.pop("06_correlation_hints.json"),
                       lambda bodies: bodies.update({"10_error_context.json": {"error": "unexpected"}})):
            with self.subTest(mutate=mutate), self.assertRaises(runner.CheckFailed):
                self.run_debug_fixture(mutate=mutate)

    def test_debug_invalid_json_and_wrong_array_shapes_fail(self):
        for value in (b"not JSON", {}, "array-as-string"):
            with self.subTest(value=value), self.assertRaises(runner.CheckFailed):
                self.run_debug_fixture(mutate=lambda bodies: bodies.update({"02_normalized_payload.json": value}))

    def test_debug_success_arrays_need_parent_record_schema_not_just_list_type(self):
        for name, value in (("02_normalized_payload.json", []),
                            ("02_normalized_payload.json", [{"record_index": 0}]),
                            ("03_mapped_event.json", [{"record_index": 0, "event_sys_id": "8" * 32, "final_event": {}}]),
                            ("06_correlation_hints.json", [{"record_index": 0, "event_sys_id": EVENT, "message_key": "FOREIGN"}]),
                            ("09_dti_timeline.json", [{"arbitrary": "object"}])):
            with self.subTest(name=name, value=value), self.assertRaises(runner.CheckFailed):
                self.run_debug_fixture(mutate=lambda bodies: bodies.update({name: value}))

    def test_debug_raw_and_response_must_identify_exact_submission(self):
        for name, value in (("01_raw_payload.json", {"different": "payload"}),
                            ("08_response_summary.json", {"sys_ids": ["8" * 32]})):
            with self.subTest(name=name), self.assertRaises(runner.CheckFailed):
                self.run_debug_fixture(mutate=lambda bodies: bodies.update({name: value}))

    def test_correlation_key_reuses_short_keys_and_separates_long_shared_prefix(self):
        self.assertEqual(runner.correlation_key("short-key"), "short-key")
        first = runner.correlation_key("A" * 150 + "-first")
        second = runner.correlation_key("A" * 150 + "-second")
        self.assertEqual(len(first), 100)
        self.assertNotEqual(first, second)
        self.assertEqual(first, runner.correlation_key("A" * 150 + "-first"))

    def test_advanced_fixture_cannot_sneak_legacy_wait_key(self):
        self.suite.fixtures["advanced_cases"] = {"node_fallback": {
            "payload": {"waitForAlert": True}, "expected_incident": {"cmdb_ci": EXPECTED}}}
        with patch.object(self.suite, "submit") as submit, self.assertRaises(ValueError):
            self.suite.advanced_case("node_fallback")
        submit.assert_not_called()

    def test_advanced_missing_fixture_cannot_be_a_passing_case(self):
        with self.assertRaises(runner.MissingFixture):
            self.suite.advanced_case("node_fallback")

    def test_empty_advanced_payload_and_expectation_cannot_claim_feature_coverage(self):
        for name in runner.ADVANCED_FEATURES:
            with self.subTest(name=name):
                self.suite.fixtures["advanced_cases"] = {name: {"payload": {}, "expected_incident": {}}}
                with patch.object(self.suite, "submit") as submit, self.assertRaises((runner.MissingFixture, ValueError)):
                    self.suite.advanced_case(name)
                submit.assert_not_called()

    def test_advanced_incident_families_cannot_disable_incident_creation_to_claim_pass(self):
        for name in runner.ADVANCED_FEATURES:
            if name == "default_dummy_policy":
                continue
            with self.subTest(name=name):
                fixture = {"payload": {}, "expected_incident": {}, "want_incident": False}
                with patch.object(self.suite, "validate_advanced_fixture") as validate, \
                        patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
                    self.suite.advanced_record(name, fixture)
                validate.assert_not_called()
                submit.assert_not_called()

    def test_all_advanced_families_require_real_json_booleans_for_execution_flags(self):
        for name in runner.ADVANCED_FEATURES:
            for flag in ("want_incident", "want_alert"):
                for value in (0, 1, "false", None, [], {}):
                    with self.subTest(name=name, flag=flag, value=value):
                        fixture = {"payload": {}, "expected_incident": {}, flag: value}
                        with patch.object(self.suite, "validate_advanced_fixture") as validate, \
                                patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
                            self.suite.advanced_record(name, fixture)
                        validate.assert_not_called()
                        submit.assert_not_called()

    def test_default_dummy_family_still_allows_explicit_nonincident_control(self):
        fixture = self.default_ci_controls()[0]
        with patch.object(self.suite, "submit", return_value={}) as submit:
            self.suite.advanced_record("default_dummy_policy", fixture)
        self.assertFalse(submit.call_args.kwargs["want_incident"])
        self.assertFalse(submit.call_args.kwargs["want_alert"])
        self.assertNotIn("direct_to_incident", submit.call_args.args[0])

    def test_canonical_ci_fixture_cannot_use_the_exact_real_name(self):
        payload = self.suite.payload("canonical-ci", cmdb_ci="Server-One")
        payload.pop("ci_identifier")
        fixture = {"payload": {"cmdb_ci": "Server-One"}, "expected_incident": {"cmdb_ci": EXPECTED}}
        self.client.tables["cmdb_ci"] = [{"sys_id": EXPECTED, "name": "Server-One"}]
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_advanced_fixture("canonical_ci_name", payload, fixture)

    def test_canonical_group_fixture_cannot_use_the_exact_real_name(self):
        payload = self.suite.payload("canonical-group", assignment_group="Hardware Group")
        fixture = {"payload": {"assignment_group": "Hardware Group"}, "expected_incident": {"assignment_group": GROUP}}
        self.client.tables["sys_user_group"] = [{"sys_id": GROUP, "name": "Hardware Group"}]
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_advanced_fixture("canonical_group_name", payload, fixture)

    def test_canonical_ci_fixture_cannot_accidentally_use_another_exact_candidate(self):
        payload = self.suite.payload("canonical-ci", cmdb_ci="Server One")
        payload.pop("ci_identifier")
        fixture = {"payload": {"cmdb_ci": "Server One"}, "expected_incident": {"cmdb_ci": EXPECTED}}
        self.client.tables["cmdb_ci"] = [{"sys_id": EXPECTED, "name": "Server-One"},
                                         {"sys_id": DECOY, "name": "Server One"}]
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_advanced_fixture("canonical_ci_name", payload, fixture)

    def test_canonical_valid_nonexact_ci_and_group_variants_are_not_rejected(self):
        ci_payload = self.suite.payload("canonical-ci", cmdb_ci="Server One")
        ci_payload.pop("ci_identifier")
        self.client.tables["cmdb_ci"] = [{"sys_id": EXPECTED, "name": "Server-One"}]
        self.suite.validate_advanced_fixture("canonical_ci_name", ci_payload,
            {"payload": {"cmdb_ci": "Server One"}, "expected_incident": {"cmdb_ci": EXPECTED}})
        group_payload = self.suite.payload("canonical-group", assignment_group="Hardware-Group")
        self.client.tables["sys_user_group"] = [{"sys_id": GROUP, "name": "Hardware Group"}]
        self.suite.validate_advanced_fixture("canonical_group_name", group_payload,
            {"payload": {"assignment_group": "Hardware-Group"}, "expected_incident": {"assignment_group": GROUP}})

    def test_reference_fixture_query_literals_reject_query_operator_injection(self):
        for value in ("name^ORactive=true", "javascript:gs.getUserID()", "bad\rname", "bad\nname"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.suite.literal(value)

    def test_node_fallback_fixture_cannot_leave_identifier_or_explicit_ci_controls(self):
        self.suite.fixtures["advanced_cases"] = {"node_fallback": {
            "payload": {"node": "NODE-LOOKUP-FIXTURE"}, "expected_incident": {"cmdb_ci": DECOY}}}
        with patch.object(self.suite, "submit") as submit, self.assertRaises((runner.MissingFixture, ValueError)):
            self.suite.advanced_case("node_fallback")
        submit.assert_not_called()

    def test_dummy_default_controls_cannot_repeat_three_identical_blank_branches(self):
        self.default_ci_fixture()
        no_hint = {"remove_fields": ["direct_to_incident", "ci_type", "ci_identifier", "cmdb_ci", "node", "resource"],
                   "payload": {"severity": "5"}, "expected_incident": {}, "expected_event": {"cmdb_ci": ""},
                   "want_incident": False, "want_alert": False}
        self.suite.fixtures["advanced_cases"] = {"default_dummy_policy": [copy.deepcopy(no_hint) for _ in range(3)]}
        with patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
            self.suite.advanced_case("default_dummy_policy")
        submit.assert_not_called()

    def default_ci_fixture(self):
        self.client.tables["sys_properties"] = [{"sys_id": "3" * 32, "name": "x_usbna_usb_event.default_cmdb_ci_sys_id", "value": EXPECTED}]
        self.client.tables["cmdb_ci"] = [{"sys_id": EXPECTED, "name": "OFFLINE DEFAULT CI"}]

    def default_ci_controls(self):
        remove = ["direct_to_incident", "ci_type", "ci_identifier", "cmdb_ci", "node", "resource"]
        base = {"remove_fields": remove, "expected_incident": {}, "want_incident": False, "want_alert": False}
        return [dict(copy.deepcopy(base), payload={"node": "OFFLINE-NONEXISTENT-NODE", "severity": "5"}, expected_event={"cmdb_ci": EXPECTED}),
                dict(copy.deepcopy(base), payload={"cmdb_ci": "OFFLINE-NONEXISTENT-CI", "severity": "5"}, expected_event={"cmdb_ci": ""}),
                dict(copy.deepcopy(base), payload={"severity": "5"}, expected_event={"cmdb_ci": ""})]

    def test_dummy_default_controls_require_and_accept_all_three_distinct_real_branches(self):
        self.default_ci_fixture()
        controls = self.default_ci_controls()
        self.suite.validate_advanced_controls("default_dummy_policy", controls)
        for damaged in ([controls[0], controls[1], copy.deepcopy(controls[1])],
                        [dict(controls[0], expected_event={"cmdb_ci": ""}), controls[1], controls[2]]):
            with self.subTest(damaged=damaged), self.assertRaises(runner.MissingFixture):
                self.suite.validate_advanced_controls("default_dummy_policy", damaged)

    def test_missing_configured_default_ci_is_incomplete_not_three_negative_passes(self):
        with self.assertRaises(runner.MissingFixture):
            self.suite.validate_advanced_controls("default_dummy_policy", self.default_ci_controls())

    def test_valid_offering_parent_controls_accept_exact_positive_and_blank_negative(self):
        second_service = "4" * 32
        self.client.tables["cmdb_ci_service"] = [{"sys_id": EXPECTED, "name": "OFFLINE SERVICE A"},
                                                {"sys_id": second_service, "name": "OFFLINE SERVICE B"}]
        self.client.tables["service_offering"] = [{"sys_id": "2" * 32, "parent": EXPECTED, "name": "Shared Offering Name"}]
        controls = [
            {"payload": {"usbem_service": EXPECTED, "usbem_offering": "Shared Offering Name"},
             "expected_incident": {"business_service": EXPECTED, "service_offering": "2" * 32}},
            {"payload": {"usbem_service": second_service, "usbem_offering": "Shared Offering Name"},
             "expected_incident": {"business_service": second_service, "service_offering": ""}},
        ]
        self.suite.validate_advanced_controls("offering_parent_filter", controls)

    def test_offering_parent_controls_need_positive_and_negative_not_two_positives(self):
        positive = {"payload": {"usbem_service": EXPECTED, "usbem_offering": "Shared Offering Name"},
                    "expected_incident": {"service_offering": "2" * 32}}
        self.suite.fixtures["advanced_cases"] = {"offering_parent_filter": [copy.deepcopy(positive), copy.deepcopy(positive)]}
        with patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
            self.suite.advanced_case("offering_parent_filter")
        submit.assert_not_called()

    def test_offering_negative_control_needs_a_different_parent_with_the_same_offering_name(self):
        positive = {"payload": {"usbem_service": EXPECTED, "usbem_offering": "Shared Offering Name"},
                    "expected_incident": {"service_offering": "2" * 32}}
        negative = {"payload": {"usbem_service": EXPECTED, "usbem_offering": "Different Offering Name"},
                    "expected_incident": {"service_offering": ""}}
        self.suite.fixtures["advanced_cases"] = {"offering_parent_filter": [positive, negative]}
        with patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
            self.suite.advanced_case("offering_parent_filter")
        submit.assert_not_called()

    def test_advanced_fallback_fixture_really_removes_higher_priority_ci_selectors(self):
        self.suite.fixtures["advanced_cases"] = {"node_fallback": {
            "remove_fields": ["ci_type", "ci_identifier", "cmdb_ci", "resource"],
            "payload": {"node": "NODE-LOOKUP-FIXTURE"}, "expected_incident": {"cmdb_ci": DECOY}}}
        with patch.object(self.suite, "submit", return_value={}) as submit:
            self.suite.advanced_case("node_fallback")
        payload = submit.call_args.args[0]
        self.assertEqual(payload["node"], "NODE-LOOKUP-FIXTURE")
        self.assertTrue(all(field not in payload for field in ("ci_type", "ci_identifier", "cmdb_ci", "resource")))
        self.assertEqual(submit.call_args.kwargs["expected"]["cmdb_ci"], DECOY)

    def test_advanced_fixture_cannot_remove_protected_ownership_fields(self):
        for field in ("message_key", "source", "event_class"):
            with self.subTest(field=field):
                self.suite.fixtures["advanced_cases"] = {"node_fallback": {
                    "remove_fields": [field], "payload": {}, "expected_incident": {}}}
                with patch.object(self.suite, "submit") as submit, self.assertRaises(ValueError):
                    self.suite.advanced_case("node_fallback")
                submit.assert_not_called()

    def test_wrapper_ai_case_preserves_nested_custom_context_in_object_and_string(self):
        for as_string in (False, True):
            with self.subTest(as_string=as_string):
                with patch.object(self.suite, "submit", return_value={}) as submit:
                    case = self.suite.wrapper_ai_case(as_string)
                wire = submit.call_args.kwargs["wire"]
                self.assertEqual(set(wire), {"payload"})
                nested = wire["payload"]
                info = json.loads(nested["additionalInfo"]) if as_string else nested["additionalInfo"]
                self.assertEqual(info["caller_id"], CALLER)
                self.assertEqual(info["category"], "hardware")
                self.assertEqual(info["subcategory"], "cpu")
                self.assertEqual(info["custom_context"]["nested"]["run"], self.suite.prefix)
                self.assertEqual(case["expected_additional_info"]["custom_context"], {
                    "retained": True, "nested": {"run": self.suite.prefix}})

    def test_envelope_special_alias_priority_is_distinct_from_incident_field_passthrough(self):
        # Confirmed against real Core.createRecordContext + DTI.applyRequestedIncidentFields:
        # root dti_* aliases win alias selection, but wrapped real impact/urgency win
        # ordinary Incident passthrough. These are deliberately different contracts.
        self.settings.urgency = "1"
        self.suite.fixtures["default_caller_sys_id"] = "2" * 32
        with patch.object(self.suite, "submit", return_value={}) as submit:
            result = self.suite.envelope_case()
        self.assertEqual(submit.call_count, 2)
        first_payload = submit.call_args_list[0].args[0]
        first = submit.call_args_list[0].kwargs
        self.assertEqual(first_payload["dti_impact"], "1")
        self.assertEqual(first_payload["dti_urgency"], "1")
        self.assertEqual(first["wire"]["dti_impact"], "3")
        self.assertEqual(first["wire"]["dti_urgency"], "3")
        self.assertEqual(first["expected"]["impact"], "3")
        self.assertEqual(first["expected"]["urgency"], "3")
        self.assertEqual(first["expected"]["caller_id"], CALLER)
        self.assertEqual(first["expected"]["category"], "hardware")
        second_payload = submit.call_args_list[1].args[0]
        second = submit.call_args_list[1].kwargs
        self.assertNotIn("dti_impact", second_payload)
        self.assertNotIn("dti_urgency", second_payload)
        self.assertEqual(second_payload["impact"], "1")
        self.assertEqual(second_payload["urgency"], "1")
        self.assertEqual(second["wire"]["impact"], "3")
        self.assertEqual(second["wire"]["urgency"], "2")
        self.assertNotIn("expected", second)
        second_expected = self.suite.expected(second_payload)
        self.assertEqual(second_expected["impact"], "1")
        self.assertEqual(second_expected["urgency"], "1")
        self.assertEqual(second["wire"]["records"][0]["event"], second_payload)
        self.assertEqual(result["subcases"], 2)

    def test_each_root_wrapper_replays_the_complete_wrapped_record(self):
        for wrapper in runner.PAYLOAD_WRAPPERS:
            with self.subTest(wrapper=wrapper), patch.object(self.suite, "submit", return_value={}) as submit:
                self.suite.ci_case("wrapped_" + wrapper, "snake", wrapper)
                payload = submit.call_args_list[0].args[0]
                wire = submit.call_args_list[0].kwargs["wire"]
                self.assertEqual(wire, {wrapper: payload})
                self.assertEqual(payload["caller_id"], CALLER)
                self.assertEqual(payload["assignment_group"], GROUP)
                self.assertEqual(payload["ci_identifier"], {"serial_number": "unit-test"})
                self.assertIn("work_notes", payload)
                self.assertEqual(submit.call_count, 2)
                self.assertEqual(submit.call_args_list[1].args[0], payload)

    def test_record_batch_exercises_all_five_wrappers_with_per_record_fields(self):
        def batch_response(wire):
            members = wire["records"]
            payloads = [next(iter(member.values())) if len(member) == 1 and next(iter(member)) in runner.PAYLOAD_WRAPPERS else member
                        for member in members]
            rows = [connector_response(payload["message_key"], format(100 + index, "032x"),
                                       format(200 + index, "032x"))["results"][0]
                    for index, payload in enumerate(payloads)]
            response = connector_response("ignored")
            response.update(inserted=str(len(rows)), results=rows, sys_ids=[row["event_sys_id"] for row in rows])
            return response
        self.client.push_result = batch_response
        result = self.suite.batch("records")
        wire = self.client.pushes[0]["records"]
        self.assertEqual(len(wire), 5)
        self.assertEqual([next(iter(member)) for member in wire], list(runner.PAYLOAD_WRAPPERS))
        self.assertEqual(result["batch_members"], 5)
        self.assertEqual(len(self.suite.cases), 5)
        for wrapper, member, case in zip(runner.PAYLOAD_WRAPPERS, wire, self.suite.cases):
            payload = member[wrapper]
            self.assertEqual(payload["message_key"], case["key"])
            self.assertEqual(payload["caller_id"], CALLER)
            self.assertEqual(payload["category"], "hardware")
            self.assertEqual(payload["subcategory"], "cpu")
            self.assertEqual(case["expected"]["short_description"], payload["dti_short_description"])
            self.assertTrue(payload["additional_info"]["custom_context"]["unchanged"])
            self.assertEqual(case["expected_additional_info"]["custom_context"],
                             payload["additional_info"]["custom_context"])
            self.assertIsInstance(case["expected_additional_info"]["custom_context"]["unchanged"], bool)
            self.assertIsInstance(case["expected_additional_info"]["custom_context"]["record_index"], int)

    def test_full_run_dispatches_every_manifest_feature(self):
        def feature(name, callback, required=()):
            row = {"name": name, "status": "known_limitation" if name == "concurrent_first_events" else "pass"}
            self.suite.features.append(row)
            return row
        self.suite.features = []
        with patch.object(self.suite, "run_feature", side_effect=feature), \
                patch.object(self.suite, "settle"), patch.object(self.suite, "finish_evidence"):
            report = self.suite.run()
        self.assertEqual({row["name"] for row in report["features"]}, set(runner.FEATURE_MANIFEST))
        self.assertEqual(len(report["features"]), len(runner.FEATURE_MANIFEST))
        self.assertEqual(report["status"], "complete_with_known_limitations")
        self.assertEqual(report["post_retries"], 0)
        self.assertTrue(report["concurrency_included"])
        self.assertFalse(report["legacy_wait_included"])

    def test_unrun_declared_feature_makes_report_incomplete(self):
        missing = "offering_name"
        def feature(name, callback, required=()):
            row = {"name": name, "status": "pass"}
            if name != missing:
                self.suite.features.append(row)
            return row
        self.suite.features = []
        with patch.object(self.suite, "run_feature", side_effect=feature), \
                patch.object(self.suite, "settle"), patch.object(self.suite, "finish_evidence"):
            report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        row = next(row for row in report["features"] if row["name"] == missing)
        self.assertEqual(row["status"], "skip")

    def test_failed_read_preflight_submits_no_events_and_returns_incomplete(self):
        self.suite.features = []
        original_query = self.client.query
        def denied_attachments(table, query, fields, timeout, limit=1000):
            if table == "sys_attachment":
                raise runner.ApiError("read denied", 403)
            return original_query(table, query, fields, timeout, limit)
        self.client.query = denied_attachments
        report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])
        self.assertEqual(self.client.requests, [])
        preflight = next(row for row in report["features"] if row["name"] == "read_preflight")
        self.assertEqual(preflight["status"], "skip")
        self.assertEqual(preflight["http_status"], 403)

    def test_preflight_checks_all_five_tables_without_claiming_field_acl_proof(self):
        self.suite.features = []
        with patch.object(self.suite, "ci_case", side_effect=runner.MissingFixture("CI control fixture unavailable")):
            report = self.suite.run()
        preflight = next(row for row in report["features"] if row["name"] == "read_preflight")
        self.assertEqual(preflight["status"], "pass")
        self.assertEqual(set(preflight["evidence"]["readable_tables"]),
                         {"em_event", "em_alert", "incident", "sys_journal_field", "sys_attachment"})
        self.assertIn("populated field ACLs", preflight["evidence"]["qualification"])
        self.assertEqual(self.client.pushes, [])
        self.assertEqual(report["status"], "incomplete")

    def test_failed_ci_control_stops_after_first_control_without_subsequent_writes(self):
        self.suite.features = []
        def first_control(name, kind, wrapper=""):
            self.client.pushes.append(self.suite.payload("control-only"))
            raise runner.CheckFailed("CI control wrong expected CI")
        with patch.object(self.suite, "ci_case", side_effect=first_control) as controls:
            report = self.suite.run()
        self.assertEqual(controls.call_count, 1)
        self.assertEqual(len(self.client.pushes), 1)
        self.assertEqual(report["status"], "fail")
        rows = {row["name"]: row for row in report["features"]}
        self.assertEqual(rows["name_only_control"]["status"], "fail")
        self.assertEqual(rows["identifier_only_control"]["status"], "skip")
        self.assertEqual(rows["concurrent_first_events"]["status"], "skip")

    def test_delayed_invalid_batch_effects_fail_final_verification(self):
        key = self.suite.prefix + "-bad-first"
        self.suite.negative_keys = [key]
        self.client.tables["em_event"] = [{"sys_id": EVENT, "message_key": key}]
        with self.assertRaises(runner.CheckFailed):
            self.suite.finish_evidence()

    def test_changed_undefined_key_baseline_fails_final_verification(self):
        self.suite.generic_baseline = set()
        self.client.tables["em_event"] = [{"sys_id": EVENT, "message_key": "GenericJSONundefinedundefinedundefinedundefined"}]
        with self.assertRaises(runner.CheckFailed):
            self.suite.finish_evidence()

    def test_parser_explicit_timestamp_is_fresh_utc_and_readback_expected_matches(self):
        submissions = []
        def submit(payload, **options):
            submissions.append((copy.deepcopy(payload), copy.deepcopy(options)))
            return {}
        with patch.object(self.suite, "submit", side_effect=submit):
            self.suite.parser_case()
        payload, options = submissions[0]
        text = payload["timeOfEvent"]
        actual = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.assertLess(abs((datetime.now(timezone.utc) - actual).total_seconds()), 90)
        self.assertEqual(options["expected_event"]["time_of_event"], text)

    def test_parser_default_case_really_sends_no_hidden_base_event_fields(self):
        submissions = []
        def submit(payload, **options):
            submissions.append((copy.deepcopy(payload), copy.deepcopy(options)))
            return {}
        with patch.object(self.suite, "submit", side_effect=submit):
            self.suite.parser_case()
        default_cases = [options for _payload, options in submissions if set(options.get("wire", {})) == {"message_key"}]
        self.assertEqual(len(default_cases), 1)
        self.assertEqual(default_cases[0]["expected_event"], {"source": "GenericJSON", "event_class": "GenericJSON",
            "description": "Generic JSON event", "severity": "5"})
        self.assertFalse(default_cases[0]["want_incident"])
        self.assertFalse(default_cases[0]["want_alert"])

    def test_parser_user_context_expected_types_match_real_core_json_roundtrip(self):
        # Golden values verified by executing Core.createRecordContext and
        # JSON.parse(Core.buildAdditionalInfoString(ctx.user_additional_info)).
        # The trace's normalizeAdditionalInfoValue is not the transport contract.
        cases = []
        def submit(payload, **options):
            case = {}
            cases.append((copy.deepcopy(payload), case))
            return case
        with patch.object(self.suite, "submit", side_effect=submit):
            self.suite.parser_case()
        expected = cases[0][1]["expected_additional_info"]
        self.assertEqual(expected, {"boolean_value": True, "number_value": 7, "nested": {"value": 1}})
        self.assertIs(expected["boolean_value"], True)
        self.assertIs(type(expected["number_value"]), int)
        array_cases = [case for payload, case in cases if isinstance(payload.get("additional_info"), list)]
        self.assertEqual(len(array_cases), 1)
        self.assertEqual(array_cases[0]["expected_additional_info"], {"additional_info_array": [1, True, {"x": 2}]})

    def test_event_alias_probe_uses_alias_keys_and_compares_mapped_stored_fields(self):
        with patch.object(self.suite, "submit", return_value={}) as submit:
            case = self.suite.event_aliases_case()
        options = submit.call_args.kwargs
        wire = options["wire"]
        for alias, stored in (("eventClass", "event_class"), ("hostName", "node"), ("component", "resource"),
                              ("metric", "metric_name"), ("eventType", "type"), ("summary", "description"),
                              ("timestamp", "time_of_event")):
            self.assertIn(alias, wire)
            self.assertNotIn(stored, wire)
            self.assertEqual(options["expected_event"][stored], wire[alias])
        self.assertNotIn("message_key", wire)
        self.assertIn("messageKey", wire)
        self.assertNotIn("direct_to_incident", wire)
        self.assertEqual(wire["ciIdentifiers"], self.settings.identifier)
        self.assertEqual(options["expected_event"]["cmdb_ci"], EXPECTED)
        self.assertEqual(case["expected_additional_info"]["assignment_group"], GROUP)

    def test_oversized_additional_info_case_keeps_routing_fields_in_stored_assertions(self):
        calls = []
        def submit(payload, **options):
            case = {}
            calls.append((copy.deepcopy(payload), options, case))
            return case
        with patch.object(self.suite, "submit", side_effect=submit):
            self.suite.parser_case()
        overflow = [(payload, case) for payload, _options, case in calls if case.get("additional_info_max_length") == 4000]
        self.assertEqual(len(overflow), 1)
        payload, case = overflow[0]
        self.assertGreater(len(json.dumps(payload["additional_info"])), 4000)
        expected = case["expected_additional_info"]
        self.assertEqual(expected["cmdb_ci"], EXPECTED)
        self.assertEqual(expected["assignment_group"], GROUP)
        self.assertEqual(expected["direct_to_incident"], "true")

    def test_salesforce_explicit_timestamp_is_fresh_not_a_stale_event_fixture(self):
        submissions = []
        self.suite.fixtures.update(offering_name="OFFLINE TEST OFFERING", offering_sys_id="2" * 32)
        def submit(payload, **options):
            submissions.append((copy.deepcopy(payload), copy.deepcopy(options)))
            return {}
        with patch.object(self.suite, "submit", side_effect=submit):
            self.suite.salesforce_case()
        _payload, options = submissions[0]
        wire = options["wire"]
        actual = datetime.strptime(wire["created_date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.assertLess(abs((datetime.now(timezone.utc) - actual).total_seconds()), 90)
        self.assertEqual(options["expected_event"]["time_of_event"], wire["created_date"])

    def test_salesforce_closed_status_alias_and_canonical_control_both_require_clear_event(self):
        submissions = []
        self.suite.fixtures.update(offering_name="OFFLINE TEST OFFERING", offering_sys_id="2" * 32)
        def submit(payload, **options):
            submissions.append((copy.deepcopy(payload), copy.deepcopy(options)))
            return {}
        with patch.object(self.suite, "submit", side_effect=submit):
            result = self.suite.salesforce_case()
        generic = [options for _payload, options in submissions if options.get("wire", {}).get("status") == "Closed"
                   and "case_status" not in options.get("wire", {})]
        canonical = [options for _payload, options in submissions if options.get("wire", {}).get("case_status") == "Closed"]
        self.assertTrue(generic)
        self.assertEqual(len(canonical), 1)
        # Never lower the failing generic alias expectation to informational severity.
        for options in (generic[0], canonical[0]):
            self.assertEqual(options["expected_event"]["severity"], "0")
            self.assertEqual(options["expected_event"]["resolution_state"], "Closing")
            self.assertFalse(options["want_incident"])
            self.assertFalse(options["want_alert"])
        self.assertEqual(result["salesforce_subcases"], 8)

    def test_final_evidence_failure_is_not_misattributed_to_negative_scalar(self):
        self.suite.features = []
        def feature(name, callback, required=()):
            self.suite.current_feature = name
            row = {"name": name, "status": "known_limitation" if name == "concurrent_first_events" else "pass"}
            self.suite.features.append(row)
            if name == "final_evidence_integrity":
                row.update(status="fail", reason="deliberate final evidence fault")
            return row
        with patch.object(self.suite, "run_feature", side_effect=feature), \
                patch.object(self.suite, "settle"), \
                patch.object(self.suite, "finish_evidence", side_effect=runner.CheckFailed("deliberate final evidence fault")):
            report = self.suite.run()
        rows = {row["name"]: row for row in report["features"]}
        self.assertEqual(rows["negative_scalar"]["status"], "pass")
        self.assertEqual(rows["final_evidence_integrity"]["status"], "fail")
        self.assertEqual(report["status"], "fail")

    def test_default_and_documented_alias_notes_have_exact_create_and_replay_counts(self):
        case = {"key": self.suite.prefix + "-notes", "active_incident": INCIDENT}
        aliases = {"key": self.suite.prefix + "-aliases", "active_incident": "8" * 32}
        self.suite.fixtures["duplicate_work_note_enabled"] = True
        with patch.object(self.suite, "submit", side_effect=[case, case, aliases, aliases]) as submit, \
                patch.object(self.suite, "settle"), patch.object(self.suite, "assert_note") as note:
            result = self.suite.default_notes_case()
        self.assertEqual(submit.call_count, 4)
        self.assertEqual(result["creation_note_count"], 1)
        self.assertEqual(result["duplicate_note_count"], 1)
        self.assertEqual(result["documented_alias_note_count"], 2)
        self.assertTrue(any(call.args[2] == 2 and "documented alias" in call.args[3] for call in note.call_args_list))

    def test_disabled_duplicate_note_policy_expects_zero_not_a_silent_skip(self):
        case = {"key": self.suite.prefix + "-notes", "active_incident": INCIDENT}
        self.suite.fixtures["duplicate_work_note_enabled"] = False
        with patch.object(self.suite, "submit", return_value=case), patch.object(self.suite, "settle"), \
                patch.object(self.suite, "assert_note") as note:
            result = self.suite.default_notes_case()
        duplicate = [call for call in note.call_args_list if "duplicate reuse note" in call.args[3]]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0].args[2], 0)
        self.assertEqual(result["duplicate_note_count"], 0)

    def test_journal_verification_counts_exact_paragraphs_inside_combined_entries(self):
        self.ready_case()
        self.client.tables["sys_journal_field"] = [{"sys_id": "9" * 32, "element_id": INCIDENT,
            "element": "work_notes", "value": "Creation breadcrumb\n\nEXACT-NOTE\n\nDuplicate breadcrumb"}]
        self.suite.assert_note([INCIDENT], "EXACT-NOTE", 1, "combined creation journal")
        self.client.tables["sys_journal_field"][0]["value"] = "EXACT-NOTE\n\nEXACT-NOTE"
        self.suite.assert_note([INCIDENT], "EXACT-NOTE", 2, "repeated exact alias paragraphs")
        with self.assertRaises(runner.CheckFailed):
            self.suite.assert_note([INCIDENT], "EXACT-NOTE", 1, "must catch duplicate paragraphs")
        self.client.tables["sys_journal_field"][0]["value"] = "prefix EXACT-NOTE suffix"
        self.suite.assert_note([INCIDENT], "EXACT-NOTE", 0, "substring is not an exact note")

    def test_both_dti_alias_styles_create_replay_and_check_two_exact_note_occurrences(self):
        case = {"active_incident": INCIDENT}
        with patch.object(self.suite, "submit", return_value=case) as submit, \
                patch.object(self.suite, "settle"), patch.object(self.suite, "assert_note") as notes:
            result = self.suite.dti_aliases_case()
        self.assertEqual(submit.call_count, 4)
        for index, style in ((0, "snake"), (2, "camel")):
            wire = submit.call_args_list[index].kwargs["wire"]
            replay = submit.call_args_list[index + 1]
            self.assertEqual(replay.kwargs["wire"], wire)
            self.assertIs(replay.kwargs["existing"], case)
            for snake, camel in (("direct_to_incident", "directToIncident"), ("dti_impact", "dtiImpact"),
                                 ("dti_urgency", "dtiUrgency"), ("dti_short_description", "dtiShortDescription"),
                                 ("dti_work_note", "dtiWorkNote")):
                self.assertIn(snake if style == "snake" else camel, wire)
                self.assertNotIn(camel if style == "snake" else snake, wire)
            self.assertFalse(any("wait" in key.lower() for key in wire))
        self.assertEqual([call.args[2] for call in notes.call_args_list], [2, 2])
        self.assertEqual(result["note_count_per_style"], 2)

    def scalar_reserved_fixture(self, mutate=""):
        state = {}
        def submit(payload, **options):
            info = payload["additional_info"]
            unknown = next(key for key in info if key.startswith("usbem_unknown_"))
            row = {"incident_fields_skipped": "" if mutate == "unknown-not-reported" else unknown,
                   "incident_fields_applied": "" if mutate == "contact-not-applied" else
                       "contact_type,sys_id" if mutate == "reserved-applied" else "contact_type"}
            case = {"key": payload["message_key"], "active_incident": INCIDENT, "response": {"results": [row]}}
            stored = {"sys_id": info["sys_id"] if mutate == "identity-overwritten" else INCIDENT,
                      "number": info["number"] if mutate == "number-overwritten" else "INC-OFFLINE",
                      "correlation_id": "WRONG" if mutate == "breadcrumb-overwritten" else payload["message_key"],
                      "correlation_display": "WRONG" if mutate == "provenance-overwritten" else "USBEM DTI",
                      "contact_type": "email", "location": "[object Object]" if mutate == "object-coerced" else "", "watch_list": ""}
            if mutate == "field-unreadable":
                del stored["location"]
            state.update(payload=payload, case=case, stored=stored, options=options)
            return case
        with patch.object(self.suite, "submit", side_effect=submit), \
                patch.object(self.suite, "exact", side_effect=lambda *_args: state["stored"]):
            result = self.suite.scalar_reserved_case()
        return state, result

    def test_scalar_reserved_case_checks_real_passthrough_and_preserved_structured_context(self):
        state, result = self.scalar_reserved_fixture()
        self.assertEqual(state["options"]["expected"]["contact_type"], "email")
        self.assertEqual(state["options"]["expected"]["correlation_display"], "USBEM DTI")
        self.assertEqual(state["case"]["expected_additional_info"]["custom_context"],
                         {"retained": True, "array": [1, "two"]})
        self.assertTrue(result["reserved_identity_fields_unchanged"])
        self.assertTrue(result["object_array_context_preserved_without_incident_coercion"])
        self.assertEqual(self.client.requests, [])

    def test_scalar_reserved_case_rejects_false_reports_and_stored_identity_or_context_damage(self):
        for mutation in ("unknown-not-reported", "contact-not-applied", "reserved-applied", "identity-overwritten",
                         "number-overwritten", "breadcrumb-overwritten", "provenance-overwritten", "object-coerced"):
            with self.subTest(mutation=mutation), self.assertRaises(runner.CheckFailed):
                self.scalar_reserved_fixture(mutation)

    def test_scalar_reserved_unreadable_field_is_incomplete_not_a_passing_omission(self):
        with self.assertRaises(runner.MissingFixture):
            self.scalar_reserved_fixture("field-unreadable")

    def test_custom_default_field_checks_skip_absent_schema_without_creating_it(self):
        case = self.ready_case()
        case["feature"] = "identifier_only_control"
        self.assertTrue(self.suite.snapshot(case, 8))
        for generating in (False, True):
            with self.subTest(generating=generating), self.assertRaises(runner.MissingFixture):
                self.suite.incident_default_field_case(generating)
        self.assertEqual(self.client.requests, [])

    def test_generating_alert_default_must_point_to_actual_linked_alert(self):
        case = self.ready_case()
        case["feature"] = "identifier_only_control"
        self.assertTrue(self.suite.snapshot(case, 8))
        self.client.tables["incident"][0]["u_generating_alert"] = ALERT
        result = self.suite.incident_default_field_case(True)
        self.assertEqual(result["stored_value"], ALERT)
        self.assertEqual(result["extra_writes"], 0)
        self.client.tables["incident"][0]["u_generating_alert"] = "8" * 32
        with self.assertRaises(runner.CheckFailed):
            self.suite.incident_default_field_case(True)

    def test_terminal_extra_fields_cannot_expand_to_arbitrary_custom_or_system_fields(self):
        for extra in ({"caller_id": CALLER}, {"u_other": "value"}, {"u_cause": ""}, {"u_cause": True}, ["u_cause"]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                runner.ComprehensiveRunner(self.client, self.settings, {"terminal_extra_fields": extra},
                    self.clock.monotonic, self.clock.sleep)
        runner.ComprehensiveRunner(self.client, self.settings, {"terminal_extra_fields": {"u_cause": "Offline test"}},
            self.clock.monotonic, self.clock.sleep)

    def test_incident_defaults_require_nonempty_independently_configured_stored_values(self):
        for fixtures in ({}, {"default_category": "software"},
                         {"default_category": "software", "default_subcategory": ""},
                         {"default_category": "software", "default_subcategory": 1},
                         {"default_category": True, "default_subcategory": "Monitoring Alert"}):
            with self.subTest(fixtures=fixtures):
                self.suite.fixtures = fixtures
                with patch.object(self.suite, "submit") as submit, self.assertRaises(runner.MissingFixture):
                    self.suite.incident_defaults_case()
                submit.assert_not_called()

    def test_incident_defaults_probe_omits_overrides_and_verifies_event_description_fallback(self):
        self.suite.fixtures.update(default_category="software", default_subcategory="Monitoring Alert")
        cases = [{}, {}]
        with patch.object(self.suite, "submit", side_effect=cases) as submit:
            result = self.suite.incident_defaults_case()
        self.assertEqual(submit.call_count, 2)
        first_payload = submit.call_args_list[0].args[0]
        first = submit.call_args_list[0].kwargs
        self.assertIn("category", first_payload)
        self.assertIn("subcategory", first_payload)
        self.assertNotIn("category", first["wire"])
        self.assertNotIn("subcategory", first["wire"])
        self.assertEqual(first["expected"]["category"], "software")
        self.assertEqual(first["expected"]["subcategory"], "Monitoring Alert")
        second_payload = submit.call_args_list[1].args[0]
        second = submit.call_args_list[1].kwargs
        self.assertNotIn("dti_short_description", second["wire"])
        self.assertNotIn("short_description", second["wire"])
        self.assertNotEqual(second["wire"]["dti_description"], second_payload["description"])
        self.assertEqual(second["expected"]["short_description"], second_payload["description"][:160])
        self.assertEqual(second["expected"]["description"], second_payload["description"])
        self.assertEqual(cases[1]["expected_additional_info"], {"dti_description": second["wire"]["dti_description"]})
        self.assertEqual(result["subcases"], 2)
        self.assertTrue(result["short_description_falls_back_to_event_description"])

    def test_ambiguity_fixture_needs_two_actual_exact_name_users_not_unknown_name(self):
        payload = self.suite.payload("ambiguous-user", assigned_to="OFFLINE DUPLICATE NAME")
        fixture = {"payload": {"assigned_to": "OFFLINE DUPLICATE NAME"}, "expected_incident": {"assigned_to": ""}}
        for rows in ([], [{"sys_id": CALLER, "name": "OFFLINE DUPLICATE NAME"}]):
            with self.subTest(rows=rows):
                self.client.tables["sys_user"] = rows
                with self.assertRaises(runner.MissingFixture):
                    self.suite.validate_advanced_fixture("ambiguous_user_rejection", payload, fixture)
        self.client.tables["sys_user"] = [{"sys_id": CALLER, "name": "OFFLINE DUPLICATE NAME"},
                                          {"sys_id": "8" * 32, "name": "OFFLINE DUPLICATE NAME"}]
        self.suite.validate_advanced_fixture("ambiguous_user_rejection", payload, fixture)

    def test_lifecycle_sequence_patches_owned_incident_then_replaces_and_reuses(self):
        for state in ("6", "7", "8"):
            with self.subTest(state=state):
                case = {"active_incident": INCIDENT, "terminal": {}, "incident_ids": {INCIDENT}}
                def submit(payload, **options):
                    if options.get("replace"):
                        case["active_incident"] = "8" * 32
                        case["incident_ids"].add("8" * 32)
                    return case
                with patch.object(self.suite, "submit", side_effect=submit) as submissions, \
                        patch.object(self.suite, "settle") as settle, \
                        patch.object(self.suite, "patch_owned") as patch_owned, \
                        patch.object(self.suite, "exact", return_value={"state": state}):
                    result = self.suite.terminal_case(state)
                self.assertEqual(submissions.call_count, 3)
                self.assertEqual(settle.call_count, 3)
                self.assertTrue(submissions.call_args_list[1].kwargs["replace"])
                self.assertNotIn("replace", submissions.call_args_list[2].kwargs)
                self.assertEqual(patch_owned.call_args.args[:2], ("incident", INCIDENT))
                self.assertEqual(patch_owned.call_args.args[2]["state"], state)
                self.assertEqual(case["terminal"][INCIDENT], state)
                self.assertEqual(result["replacement_incident_sys_id"], "8" * 32)
                self.assertTrue(result["third_submission_reused_replacement"])

    def test_concurrency_stress_is_never_an_unqualified_pass(self):
        index = [0]
        def response(payload):
            index[0] += 1
            return connector_response(payload["message_key"], format(100 + index[0], "032x"),
                                      format(200 + index[0], "032x"))
        self.client.push_result = response
        self.suite.current_feature = "concurrent_first_events"
        self.suite.features = [{"name": "concurrent_first_events", "status": "running"}]
        result = self.suite.concurrency_case()
        self.assertEqual(len(self.client.pushes), 3)
        self.assertEqual(result["distinct_returned_incidents"], 3)
        self.assertTrue(result["race_observed"])
        self.assertEqual(self.suite.features[0]["status"], "known_limitation")
        self.assertEqual(runner.aggregate_status(self.suite.features), "complete_with_known_limitations")


class ComprehensiveCLITests(unittest.TestCase):
    def test_plan_and_manifest_are_credential_free_read_only(self):
        for flag in ("--plan", "--list-tests"):
            with self.subTest(flag=flag), patch.object(sys, "argv", ["dti-tester", flag]), \
                    patch.object(runner, "Client") as client, \
                    patch.object(runner, "configuration") as configuration, \
                    patch.object(runner, "read_env", side_effect=AssertionError("read-only inventory must not need auth")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 0)
                self.assertIn("terminal_6", output.getvalue())
                self.assertIn("concurrent_first_events", output.getvalue())
                client.assert_not_called()
                configuration.assert_not_called()

    def test_explicit_comprehensive_cli_uses_complete_runner_not_legacy_focused_suite(self):
        for status, exit_code in (("pass", 0), ("complete_with_known_limitations", 0), ("incomplete", 4),
                                  ("fail", 2), ("error", 3)):
            with self.subTest(status=status), patch.object(sys, "argv", ["dti-tester", "--access-profile", "comprehensive"]), \
                    patch.dict(runner.os.environ, {}, clear=True), \
                    patch.object(runner, "read_env", return_value={}), \
                    patch.object(runner, "configuration", return_value=("https://example.service-now.com", {"mode": "basic"}, object())), \
                    patch.object(runner, "Client"), patch.object(runner, "Runner") as focused, \
                    patch.object(runner, "ComprehensiveRunner") as comprehensive, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                comprehensive.return_value.run.return_value = {"status": status}
                self.assertEqual(runner.main(), exit_code)
                comprehensive.assert_called_once()
                focused.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_cli_selected_missing_profile_target_errors_before_client_or_any_network(self):
        for selected in ({}, {"USBEM_PROD_URL": ""}):
            with self.subTest(selected=selected), patch.object(sys, "argv", ["dti-tester", "--profile", "PROD"]), \
                    patch.dict(runner.os.environ, {}, clear=True), \
                    patch.object(runner, "read_env", return_value={"SN_INSTANCE_URL": "https://unrelated-pdi.service-now.com", **selected}), \
                    patch.object(runner, "Client") as client, \
                    patch.object(runner, "ComprehensiveRunner") as comprehensive, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 3)
                report = json.loads(output.getvalue())
                self.assertEqual(report["status"], "error")
                self.assertIn("USBEM_PROD_URL", report["reason"])
                client.assert_not_called()
                comprehensive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
