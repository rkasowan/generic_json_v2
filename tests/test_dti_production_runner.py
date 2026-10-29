#!/usr/bin/env python3
"""Offline regression tests for the restricted production DTI tester.

These are client/harness tests, not evidence that a production instance passed.
No test loads credentials, opens a connection, or creates a ServiceNow record.
"""

import contextlib
import base64
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import urllib.parse
import threading
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ci_identifier_precedence as runner


EXPECTED, DECOY, GROUP, CALLER = (character * 32 for character in "abcd")
EVENT, INCIDENT, ALERT, FOREIGN = (character * 32 for character in "ef12")


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def response(key, event_id=EVENT, incident_id=INCIDENT):
    row = {"status": "success", "message_key": key, "event_sys_id": event_id,
           "incident_sys_id": incident_id, "dti_mode": "fast_async" if incident_id else "",
           "dti_incident_status": "created" if incident_id else "not_requested"}
    return {"status": "success", "inserted": "1", "version": runner.EXPECTED_RELEASE,
            "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")},
            "sys_ids": [event_id], "results": [row]}


class StrictClient:
    """Fail immediately if a production path asks for any additional permission."""

    TABLES = frozenset(("em_event", "em_alert", "incident"))
    PATCH_FIELDS = {"incident": {"state", "close_code", "close_notes", "u_cause"},
                    "em_alert": {"state", "incident"}}

    def __init__(self):
        self.tables = {table: [] for table in self.TABLES}
        self.queries, self.requests, self.pushes, self.probes = [], [], [], []
        self.query_error = self.request_error = self.push_error = None
        self.push_result = None
        self.probe_result = (500, {})
        self.hidden_fields = set()
        self.journal_responses = {}
        self.raw_journal_blank = True

    def query(self, table, query, fields, timeout, limit=1000):
        if table not in self.TABLES:
            raise AssertionError("production attempted a forbidden table read: " + table)
        if any("." in field for field in fields.split(",")):
            raise AssertionError("production attempted a dot-walked reference read")
        self.queries.append((table, query, fields, timeout))
        if self.query_error:
            raise self.query_error
        rows = copy.deepcopy(self.tables[table])
        for part in query.split("^"):
            if part.endswith("ISNOTEMPTY"):
                field = part[:-10]
                rows = [row for row in rows if row.get(field)]
            elif "=" in part:
                field, expected = part.split("=", 1)
                rows = [row for row in rows if str(row.get(field, "")) == expected]
        selected = set(fields.split(",")) - self.hidden_fields
        result = [{key: value for key, value in row.items() if key in selected} for row in rows]
        if self.raw_journal_blank:
            for row in result:
                if "work_notes" in row:
                    row["work_notes"] = ""
        return result

    def request(self, method, path, body=None, timeout=90):
        parts = urllib.parse.urlsplit(path)
        if method == "GET":
            segments = parts.path.split("/")
            if len(segments) not in (5, 6) or segments[1:4] != ["api", "now", "table"] or segments[4] not in self.TABLES or body is not None:
                raise AssertionError("production attempted a forbidden read URL")
            params = urllib.parse.parse_qs(parts.query)
            if len(segments) == 6:
                table, record_id = segments[4:]
                allowed = {"sysparm_fields", "sysparm_display_value", "sysparm_exclude_reference_link"}
                if (table not in ("incident", "em_alert") or not runner.SYS_ID.fullmatch(record_id) or
                        set(params) - allowed or params.get("sysparm_display_value") != ["true"] or
                        set(params.get("sysparm_fields", [""])[0].split(",")) != {"sys_id", "work_notes"}):
                    raise AssertionError("production attempted a broad, reference, or unowned-format journal read")
                self.requests.append((method, path, None, timeout))
                if self.request_error:
                    raise self.request_error
                if (table, record_id) in self.journal_responses:
                    return copy.deepcopy(self.journal_responses[(table, record_id)])
                rows = [row for row in self.tables[table] if row.get("sys_id") == record_id]
                if len(rows) != 1:
                    return {}
                return {key: copy.deepcopy(rows[0][key]) for key in ("sys_id", "work_notes")
                        if key in rows[0] and key not in self.hidden_fields}
            allowed = {"sysparm_query", "sysparm_fields", "sysparm_limit", "sysparm_display_value", "sysparm_exclude_reference_link"}
            if set(params) - allowed:
                raise AssertionError("production attempted an unreviewed read parameter")
            self.requests.append((method, path, None, timeout))
            return self.query(segments[4], params.get("sysparm_query", [""])[0],
                              params.get("sysparm_fields", [""])[0], timeout)[:int(params.get("sysparm_limit", [1000])[0])]
        if method != "PATCH" or parts.query:
            raise AssertionError("production attempted a forbidden request method or URL")
        segments = parts.path.split("/")
        if len(segments) != 6 or segments[1:4] != ["api", "now", "table"]:
            raise AssertionError("production attempted a non-table mutation")
        table, record_id = segments[4:]
        if table not in self.PATCH_FIELDS or not isinstance(body, dict) or not body or set(body) - self.PATCH_FIELDS[table]:
            raise AssertionError("production attempted a non-allowlisted mutation")
        self.requests.append((method, path, copy.deepcopy(body), timeout))
        if self.request_error:
            raise self.request_error
        rows = [row for row in self.tables[table] if row.get("sys_id") == record_id]
        if len(rows) != 1:
            raise AssertionError("production attempted to mutate an absent test record")
        rows[0].update(body)
        return copy.deepcopy(rows[0])

    def push(self, source, payload, timeout):
        self.pushes.append(copy.deepcopy(payload))
        if self.push_error:
            raise self.push_error
        return self.push_result(payload) if callable(self.push_result) else copy.deepcopy(self.push_result)

    def probe(self, source, payload, timeout, raw=False):
        self.probes.append((copy.deepcopy(payload), raw))
        return copy.deepcopy(self.probe_result)

    def rows(self, table, key, timeout):
        raise AssertionError("production bypassed the guarded query helper")

    def download(self, *_args, **_kwargs):
        raise AssertionError("production attempted an attachment download")


class ManifestModelClient(StrictClient):
    """Deterministic orchestration model, not an implementation of the connector.

    Stored expectations are materialized by the model runner. Its purpose is to
    visit real production-runner callbacks and expose forbidden API calls; API
    mapping correctness still requires the real platform, not this oracle.
    """
    def __init__(self):
        super().__init__()
        self.sequence = 1000
        self.lock = threading.Lock()
        self.incidents_by_key = {}
        self.notes = {}
        self.suite = None

    def new_id(self):
        self.sequence += 1
        return format(self.sequence, "032x")

    @staticmethod
    def normalized(member):
        result = {}
        for wrapper in runner.PAYLOAD_WRAPPERS:
            if isinstance(member.get(wrapper), dict):
                result.update(ManifestModelClient.normalized(member[wrapper]))
        result.update({key: value for key, value in member.items() if key not in runner.PAYLOAD_WRAPPERS})
        aliases = {"messageKey": "message_key", "directToIncident": "direct_to_incident", "dtiWorkNote": "dti_work_note"}
        for key, canonical in aliases.items():
            if canonical not in result and key in result:
                result[canonical] = result[key]
        info = runner.ComprehensiveRunner.payload_info(result)
        for key, value in info.items():
            result.setdefault(aliases.get(key, key), value)
        return result

    def companion(self, parent_ids, keys):
        record_id = self.new_id()
        self.tables["em_event"].append({**dict.fromkeys(self.suite.EVENT_FIELDS.split(","), ""), "sys_id": record_id,
            "message_key": "offline-debug-" + record_id, "state": "Processed", "severity": "5",
            "additional_info": json.dumps({"usbem_version": runner.EXPECTED_RELEASE,
                "usbem_debug_parent_event_sys_ids": ",".join(parent_ids), "usbem_debug_parent_message_keys": ",".join(keys)})})
        return record_id

    @staticmethod
    def native_alert_expected(case):
        """Model native first-Event Alert creation independently of runner flags."""
        wire = case.get("wire", case["payload"])
        event = ManifestModelClient.normalized(wire) if isinstance(wire, dict) else case["payload"]
        expected = case.get("expected_event", {})
        severity = expected.get("severity", event.get("severity"))
        resolution = expected.get("resolution_state", event.get("resolution_state", event.get("resolutionState", event.get("status", event.get("case_status", "New")))))
        closing = str(resolution).casefold() in ("closing", "closed", "close", "clear", "cleared", "resolved")
        if severity is None:
            severity = "0" if event.get("case_number") and closing else "3" if event.get("case_number") else "5"
        severity = {"clear": "0", "ok": "5", "informational": "5"}.get(str(severity).casefold(), str(severity))
        return severity != "0" and not closing

    def push(self, source, payload, timeout):
        with self.lock:
            self.pushes.append(copy.deepcopy(payload))
            envelope = {}
            if isinstance(payload, list):
                members = payload
            elif isinstance(payload, dict) and any(isinstance(payload.get(key), list) for key in ("records", "events")):
                container = "records" if isinstance(payload.get("records"), list) else "events"
                members = payload[container]
                envelope = {key: value for key, value in payload.items() if key != container}
            else:
                members = [payload]
            rows, keys = [], []
            for member in members:
                normalized = self.normalized({**envelope, **member})
                key = str(normalized.get("message_key") or normalized.get("case_number") or "".join(str(normalized.get(field, "undefined")) for field in ("source", "node", "type", "resource", "metric_name")))[:1024]
                event_id, incident_id = self.new_id(), ""
                enabled = str(normalized.get("direct_to_incident", "")).lower() in ("true", "1")
                if str(normalized.get("severity", "5")).lower() in ("0", "5", "clear", "ok", "informational"):
                    enabled = False
                if enabled:
                    old_id = self.incidents_by_key.get(key)
                    old = next((row for row in self.tables["incident"] if row["sys_id"] == old_id), {})
                    created = not old_id or str(old.get("state")) in ("6", "7", "8")
                    incident_id = self.new_id() if created else old_id
                    self.incidents_by_key[key] = incident_id
                    note = normalized.get("work_notes") or normalized.get("dti_work_note")
                    if not note:
                        note = ("Direct To Incident Via Event Management Generic JSON Endpoint\n\nIncident Created From " + key if created else
                                "Duplicate event received via Event Management Generic JSON Endpoint (" + key + ")")
                    self.notes[("incident", incident_id)] = str(note)
                    if not any(row.get("sys_id") == incident_id for row in self.tables["incident"]):
                        self.tables["incident"].append({**dict.fromkeys(self.suite.INCIDENT_FIELDS.split(","), ""),
                            "sys_id": incident_id, "number": "INC-MODEL", "state": "1", "correlation_id": runner.correlation_key(key),
                            "correlation_display": "USBEM DTI", "contact_type": normalized.get("contact_type", ""), "location": "", "watch_list": ""})
                alert_note = normalized.get("alert_work_notes") or (normalized.get("work_notes") if not enabled else None)
                if alert_note:
                    self.notes[("em_alert", key)] = str(alert_note)
                row = response(key, event_id, incident_id)["results"][0]
                row["incident_fields_skipped"] = ",".join(name for name in normalized if name.startswith("usbem_unknown_"))
                row["incident_fields_applied"] = "contact_type" if "contact_type" in normalized else ""
                rows.append(row)
                keys.append(key)
            result = response("unused")
            result.update(inserted=str(len(rows)), results=rows, sys_ids=[row["event_sys_id"] for row in rows])
            if isinstance(payload, dict) and payload.get("usbem_debug"):
                result["debug_raw_event_sys_id"] = self.companion(result["sys_ids"], keys)
            return result

    def probe(self, source, payload, timeout, raw=False):
        with self.lock:
            self.probes.append((copy.deepcopy(payload), raw))
            if raw:
                message = "SyntaxError"
            elif not isinstance(payload, (dict, list)):
                message = "Payload must be a JSON object or an array of JSON objects"
            elif isinstance(payload, dict) and "records" in payload and not isinstance(payload["records"], list):
                message = "records must be an array of JSON objects"
            elif isinstance(payload, dict) and "events" in payload and not isinstance(payload["events"], list):
                message = "events must be an array of JSON objects"
            else:
                message = "invalid member at index 1"
            result = {"status": "error", "message": message, "version": runner.EXPECTED_RELEASE,
                      "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")}}
            if isinstance(payload, dict) and payload.get("usbem_debug"):
                result["debug_raw_event_sys_id"] = self.companion([], [])
            return 500, result

    def materialize(self, case):
        def upsert(table, record_id, values):
            old = next((row for row in self.tables[table] if row.get("sys_id") == record_id), None)
            if old is None:
                old = {"sys_id": record_id}
                self.tables[table].append(old)
            old.update(values)
            return old
        expected_ci = case.get("expected_event", {}).get("cmdb_ci", case["expected"].get("cmdb_ci", ""))
        for record_id in case["event_ids"]:
            values = {**dict.fromkeys(self.suite.EVENT_FIELDS.split(","), ""), "sys_id": record_id,
                      "message_key": case["key"], "state": "Processed", "cmdb_ci": expected_ci,
                      "additional_info": json.dumps(case.get("expected_additional_info", {})), **case["expected_event"]}
            upsert("em_event", record_id, values)
        alerts = [row for row in self.tables["em_alert"] if row.get("message_key") == case["key"]]
        alert_id = alerts[0]["sys_id"] if alerts else self.new_id()
        for record_id in case["incident_ids"]:
            values = {**dict.fromkeys(self.suite.INCIDENT_FIELDS.split(","), ""), **case["expected"], "sys_id": record_id,
                      "state": case["terminal"].get(record_id, "1"), "correlation_id": runner.correlation_key(case["key"]),
                      "correlation_display": "USBEM DTI", "work_notes": self.notes.get(("incident", record_id), ""),
                      "u_netcool_ticket": "true", "u_generating_alert": alert_id}
            upsert("incident", record_id, values)
        if self.native_alert_expected(case) or alerts:
            values = {**dict.fromkeys(self.suite.ALERT_FIELDS.split(","), ""), "sys_id": alert_id, "message_key": case["key"],
                      "state": alerts[0].get("state", "Open") if alerts else "Open",
                      "incident": case.get("expected_alert_incident", case["active_incident"] or next(iter(case["incident_ids"]), "")),
                      "cmdb_ci": expected_ci, "work_notes": self.notes.get(("em_alert", case["key"]), ""),
                      "additional_info": json.dumps({"direct_to_incident": "true"} if case["want_incident"] else {})}
            upsert("em_alert", alert_id, values)


def settings(**overrides):
    values = dict(source="genericJsonV2", ci_type="cmdb_ci_server", identifier={"serial_number": "offline-only"},
                  decoy_name="offline-decoy", expected_id=EXPECTED, decoy_id=DECOY,
                  caller_id=CALLER, category="hardware", expected_category="hardware",
                  subcategory="cpu", expected_subcategory="cpu", impact="1", urgency="3",
                  assignment_group=GROUP, expected_assignment_group_id=GROUP,
                  timeout=8, stable_seconds=2, poll_seconds=1, request_timeout=3)
    values.update(overrides)
    return runner.Settings(**values)


def complete_catalog():
    """Synthetic target-owner expectations; no real instance fixtures or IDs."""
    support, assignee, service, offering, other_service, application, default_ci = (value * 32 for value in "3456789")
    ci_remove = ["ci_type", "ci_identifier", "cmdb_ci"]
    def case(payload, expected=None, remove=(), **extra):
        return {"payload": payload, "expected_incident": expected or {}, "remove_fields": list(remove), **extra}
    result = {"group_name": "offline-group", "assignee_sys_id": assignee, "caller_name": "offline-caller",
              "assignee_name": "offline-assignee", "default_caller_sys_id": CALLER,
              "ci_support_sys_id": EXPECTED, "ci_support_group_sys_id": support,
              "service_sys_id": service, "service_name": "offline-service", "offering_sys_id": offering,
              "offering_name": "offline-offering", "default_category": "Software", "default_subcategory": "Monitoring Alert",
              "default_ci_sys_id": default_ci,
              "production_attestations": {name: True for name in runner.ProductionRunner.ATTESTED_FEATURES}}
    result["advanced_cases"] = {
        "node_fallback": case({"node": "offline-ci", "resource": ""}, {"cmdb_ci": EXPECTED}, ci_remove),
        "resource_resolution": case({"node": "", "resource": "offline-ci"}, {"cmdb_ci": EXPECTED}, ci_remove),
        "additional_info_name_fallback": case({"node": "", "resource": "", "additional_info": {"name": "offline-ci"}}, {"cmdb_ci": EXPECTED}, ci_remove),
        "ci_class_label": case({"ci_type": "Server"}, {"cmdb_ci": EXPECTED}),
        "canonical_ci_name": case({"cmdb_ci": "offline-ci-variant"}, {"cmdb_ci": EXPECTED}, ["ci_type", "ci_identifier"]),
        "canonical_group_name": case({"assignment_group": "offline-group-variant"}, {"assignment_group": GROUP}),
        "invalid_group_ci_fallback": case({"cmdb_ci": EXPECTED, "assignment_group": "offline-missing-group"}, {"cmdb_ci": EXPECTED, "assignment_group": support}, ["ci_type", "ci_identifier"]),
        "car_id": case({"usbem_car_id": "offline-car"}, expected_additional_info={"cmdb_ci_business_app": application}),
        "l2_support_group": case({"cmdb_ci": EXPECTED}, {"cmdb_ci": EXPECTED, "assignment_group": support}, ["assignment_group", "ci_type", "ci_identifier"]),
        "service_inference": case({"cmdb_ci": EXPECTED}, {"cmdb_ci": EXPECTED, "business_service": service}, ["ci_type", "ci_identifier"]),
        "offering_parent_filter": [case({"usbem_service": parent, "usbem_offering": "offline-offering"},
                                          {"business_service": parent_id, "service_offering": expected_offering})
                                   for parent, parent_id, expected_offering in (("offline-service", service, offering), ("offline-other-service", other_service, ""))],
        "custom_incident_fields": case({"u_usb_em_test_value": "offline-only"}, {"u_usb_em_test_value": "offline-only"}),
        "ambiguous_user_rejection": case({"assigned_to": "offline-ambiguous-name"}, {"assigned_to": ""}),
        "default_dummy_policy": [
            case({"node": "offline-missing-node", "resource": ""}, remove=ci_remove + ["direct_to_incident"], expected_event={"cmdb_ci": default_ci}, want_incident=False),
            case({"node": "offline-missing-node", "resource": "", "cmdb_ci": "offline-missing-ci"}, remove=["ci_type", "ci_identifier", "direct_to_incident"], expected_event={"cmdb_ci": ""}, want_incident=False),
            case({"node": "", "resource": ""}, remove=ci_remove + ["direct_to_incident"], expected_event={"cmdb_ci": ""}, want_incident=False)],
    }
    return result


class ProductionTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = runner.ProductionClient("https://offline.service-now.com", {
            "mode": "basic", "username": "offline-only", "password": "offline-only"})

    def test_three_table_raw_gets_are_permitted(self):
        for table in StrictClient.TABLES:
            with self.subTest(table=table):
                path = "/api/now/table/" + table + "?sysparm_fields=sys_id&sysparm_display_value=false"
                self.assertEqual(self.client.permitted("GET", path), table)

    def test_exact_incident_and_alert_journal_views_are_permitted_without_reference_display(self):
        params = urllib.parse.urlencode({"sysparm_fields": "sys_id,work_notes", "sysparm_display_value": "true",
                                         "sysparm_exclude_reference_link": "true"})
        for table in ("incident", "em_alert"):
            with self.subTest(table=table):
                self.assertEqual(self.client.permitted("GET", "/api/now/table/" + table + "/" + INCIDENT + "?" + params), table)

    def test_formatted_journal_exception_rejects_list_event_reference_and_extra_queries(self):
        examples = ("/api/now/table/incident?sysparm_fields=sys_id,work_notes&sysparm_display_value=true",
                    "/api/now/table/em_alert?sysparm_fields=sys_id,work_notes&sysparm_display_value=true",
                    "/api/now/table/em_event/" + EVENT + "?sysparm_fields=sys_id,work_notes&sysparm_display_value=true",
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=sys_id,work_notes&sysparm_display_value=all",
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=sys_id,work_notes,caller_id&sysparm_display_value=true",
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=sys_id,caller_id&sysparm_display_value=true",
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=work_notes&sysparm_display_value=true",
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=sys_id,work_notes&sysparm_display_value=true&sysparm_query=sys_id=" + INCIDENT,
                    "/api/now/table/incident/" + INCIDENT + "?sysparm_fields=sys_id,work_notes&sysparm_display_value=true&sysparm_limit=1")
        for path in examples:
            with self.subTest(path=path), patch.object(self.client, "authorization") as auth, patch.object(self.client.opener, "open") as opened:
                with self.assertRaises(ValueError):
                    self.client.request("GET", path)
                auth.assert_not_called()
                opened.assert_not_called()

    def test_connector_post_and_oauth_token_are_the_only_non_table_paths(self):
        self.assertEqual(self.client.permitted("POST", "/api/sn_em_connector/em/inbound_event?source=genericJsonV2"), "connector")
        self.assertEqual(self.client.permitted("POST", "/oauth_token.do"), "oauth_token")

    def test_forbidden_tables_urls_methods_and_reference_dotwalks_fail_before_auth(self):
        examples = [("GET", "/api/now/table/" + table + "?sysparm_fields=sys_id", None)
                    for table in ("cmdb_ci", "sys_user", "sys_user_group", "sys_properties", "sys_dictionary", "task",
                                  "sys_journal_field", "sys_attachment", "sys_scope_privilege", "kb_knowledge")]
        examples += [("GET", "/api/now/attachment/" + EVENT + "/file", None),
                     ("POST", "/sys.scripts.do", {}), ("POST", "/api/now/table/incident", {}),
                     ("POST", "/api/now/table/em_alert", {}), ("DELETE", "/api/now/table/incident/" + INCIDENT, None),
                     ("PATCH", "/api/now/table/em_event/" + EVENT, {"state": "Processed"}),
                     ("GET", "/api/now/table/incident?sysparm_fields=caller_id.email", None),
                     ("GET", "/api/now/table/em_event?sysparm_display_value=all", None),
                     ("GET", "/api/now/table/incident?sysparm_query=sys_id=javascript:gs.getUserID()", None),
                     ("GET", "https://external.example/api/now/table/incident", None),
                     ("GET", "//external.example/api/now/table/incident", None),
                     ("GET", "/api/now/table/incident#fragment", None),
                     ("POST", "/api/sn_em_connector/em/inbound_event", {}),
                     ("POST", "/api/sn_em_connector/em/inbound_event?source=a&source=b", {}),
                     ("POST", "/api/sn_em_connector/em/inbound_event?source=a&other=b", {})]
        for method, path, body in examples:
            with self.subTest(method=method, path=path), patch.object(self.client, "authorization") as auth, \
                    patch.object(self.client.opener, "open") as opened:
                with self.assertRaises(ValueError):
                    self.client.request(method, path, body)
                auth.assert_not_called()
                opened.assert_not_called()

    def test_direct_patch_allowlist_is_narrow(self):
        allowed = (("incident", {"state": "6", "close_code": "Solution provided", "close_notes": "retained"}),
                   ("em_alert", {"state": "Closed", "incident": INCIDENT}))
        for table, body in allowed:
            self.assertEqual(self.client.permitted("PATCH", "/api/now/table/" + table + "/" + INCIDENT, body), table)
        for table, body in (("incident", {}), ("incident", {"caller_id": CALLER}), ("incident", {"work_notes": "no"}),
                            ("em_alert", {"additional_info": "{}"}), ("em_alert", {"task": INCIDENT}), ("em_alert", {"work_notes": "no"})):
            with self.subTest(table=table, body=body), self.assertRaises(ValueError):
                self.client.permitted("PATCH", "/api/now/table/" + table + "/" + INCIDENT, body)

    def test_send_is_independently_guarded_against_a_helper_bypass(self):
        with patch.object(runner.Client, "send") as send:
            with self.assertRaises(ValueError):
                self.client.send("GET", "/api/now/table/sys_journal_field", None, {}, 3)
            with self.assertRaises(ValueError):
                self.client.send("PATCH", "/api/now/table/incident/" + INCIDENT, b'{"caller_id":"no"}', {}, 3)
            with self.assertRaises(ValueError):
                self.client.send("PATCH", "/api/now/table/incident/" + INCIDENT, b'{', {}, 3)
            send.assert_not_called()

    def test_attachment_helper_fails_without_auth_or_network(self):
        with patch.object(self.client, "authorization") as auth, patch.object(self.client.opener, "open") as opened:
            with self.assertRaises(ValueError):
                self.client.download(EVENT, 3)
            auth.assert_not_called()
            opened.assert_not_called()

    def test_forbidden_inherited_rows_helper_is_blocked_before_auth(self):
        with patch.object(self.client, "authorization") as auth, patch.object(self.client.opener, "open") as opened:
            with self.assertRaises(ValueError):
                self.client.rows("sys_user", "not-a-secret", 3)
            auth.assert_not_called()
            opened.assert_not_called()

    def test_connector_post_has_one_attempt_on_failure(self):
        with patch.object(runner.Client, "send", side_effect=runner.ApiError("one-shot failure", retryable=True)) as send:
            with self.assertRaises(runner.ApiError):
                self.client.push("genericJsonV2", {"message_key": "offline"}, 3)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(self.client.operation_counts.get("POST connector"), 1)


class ProductionBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.client = Clock(), StrictClient()
        self.suite = runner.ProductionRunner(self.client, settings(), {}, self.clock.monotonic, self.clock.sleep)
        self.suite.current_feature = "fast_snake_conflict"
        self.suite.features = [{"name": self.suite.current_feature, "status": "pass"}]

    def ready_case(self, **overrides):
        payload = self.suite.payload("offline-case")
        self.client.push_result = response(payload["message_key"])
        case = self.suite.submit(payload, **overrides)
        self.client.tables = {
            "em_event": [{**dict.fromkeys(self.suite.EVENT_FIELDS.split(","), ""),
                          "sys_id": EVENT, "message_key": case["key"], "state": "Processed", "additional_info": "{}", "cmdb_ci": case["expected"]["cmdb_ci"]}],
            "incident": [{**dict.fromkeys(self.suite.INCIDENT_FIELDS.split(","), ""),
                          "sys_id": INCIDENT, "number": "INC-OFFLINE", "state": "1", "correlation_id": case["key"],
                          "correlation_display": "USBEM DTI", "work_notes": "", **case["expected"]}],
            "em_alert": [{**dict.fromkeys(self.suite.ALERT_FIELDS.split(","), ""),
                          "sys_id": ALERT, "message_key": case["key"], "state": "Open", "incident": INCIDENT,
                          "additional_info": "{}", "work_notes": "", "cmdb_ci": case["expected"]["cmdb_ci"]}],
        }
        return case

    def seed_preflight(self):
        self.suite.fixtures = complete_catalog()
        fields_by_table = {"em_event": set(self.suite.EVENT_FIELDS.split(",")), "incident": set(self.suite.INCIDENT_FIELDS.split(",")),
                           "em_alert": set(self.suite.ALERT_FIELDS.split(","))}
        fields_by_table["incident"].update(("u_generating_alert", "u_netcool_ticket", "contact_type", "location", "watch_list"))
        for fixture in self.suite.fixtures["advanced_cases"].values():
            for member in fixture if isinstance(fixture, list) else [fixture]:
                fields_by_table["incident"].update(member.get("expected_incident", {}))
                fields_by_table["em_event"].update(member.get("expected_event", {}))
        for index, (table, fields) in enumerate(fields_by_table.items()):
            self.client.tables[table] = [{**dict.fromkeys(fields, ""), "sys_id": format(900 + index, "032x")}]

    def test_manifest_is_unique_and_excludes_unreadable_foreign_task_fixture(self):
        self.assertEqual(len(self.suite.MANIFEST), len(set(self.suite.MANIFEST)))
        self.assertNotIn("foreign_task_guard", self.suite.MANIFEST)
        self.assertIn("terminal_6", self.suite.MANIFEST)
        self.assertIn("foreign_incident_guard", self.suite.MANIFEST)
        self.assertIn("final_evidence_integrity", self.suite.MANIFEST)
        self.assertIn("concurrent_first_events", self.suite.MANIFEST)

    def test_run_prefix_is_unique_per_invocation(self):
        other = runner.ProductionRunner(self.client, settings(), {}, self.clock.monotonic, self.clock.sleep)
        self.assertNotEqual(self.suite.prefix, other.prefix)
        self.assertNotEqual(self.suite.payload("same")["message_key"], other.payload("same")["message_key"])

    def test_production_alert_fields_do_not_request_unavailable_task_reference(self):
        self.assertNotIn("task", self.suite.ALERT_FIELDS.split(","))
        self.assertIn("work_notes", self.suite.ALERT_FIELDS.split(","))
        self.assertIn("work_notes", self.suite.INCIDENT_FIELDS.split(","))

    def test_guarded_query_allows_only_three_tables(self):
        for table in StrictClient.TABLES:
            self.assertEqual(self.suite.query(table, "sys_id=" + EVENT, "sys_id"), [])
        for table in ("sys_journal_field", "sys_attachment", "sys_properties", "sys_dictionary", "cmdb_ci", "sys_user",
                      "sys_user_group", "task", "cmdb_ci_service", "service_offering"):
            with self.subTest(table=table), self.assertRaises((ValueError, runner.CheckFailed, runner.MissingFixture)):
                self.suite.query(table, "sys_id=" + EVENT, "sys_id")
        self.assertEqual(len(self.client.queries), 3)

    def test_forbidden_exact_reads_fail_before_the_client(self):
        with self.assertRaises((ValueError, runner.CheckFailed, runner.MissingFixture)):
            self.suite.exact("task", INCIDENT, "sys_id")
        self.assertEqual(self.client.queries, [])

    def test_ready_snapshot_uses_only_three_tables_and_stable_window(self):
        case = self.ready_case()
        self.suite.settle([case])
        self.assertFalse(case.get("observation_failed", False))
        self.assertGreaterEqual(case["stable_observed_seconds"], 2)
        self.assertEqual({item[0] for item in self.client.queries}, StrictClient.TABLES)
        self.assertEqual(self.client.requests, [])

    def test_missing_required_incident_field_is_incomplete_not_pass(self):
        case = self.ready_case()
        self.client.hidden_fields.add("caller_id")
        self.suite.settle([case])
        self.assertTrue(case["observation_failed"])
        self.assertEqual(self.suite.features[0]["status"], "skip")
        self.assertEqual(runner.aggregate_status(self.suite.features), "incomplete")

    def test_mismatched_required_incident_field_fails(self):
        case = self.ready_case()
        self.client.tables["incident"][0]["category"] = "wrong"
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_alert_link_must_be_the_returned_incident(self):
        case = self.ready_case()
        self.client.tables["em_alert"][0]["incident"] = FOREIGN
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_unexpected_stored_duplicate_incident_fails(self):
        case = self.ready_case()
        duplicate = dict(self.client.tables["incident"][0], sys_id=FOREIGN)
        self.client.tables["incident"].append(duplicate)
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_read_acl_denial_is_incomplete(self):
        case = self.ready_case()
        self.client.query_error = runner.ApiError("denied", 403)
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "skip")
        self.assertEqual(self.suite.features[0]["http_status"], 403)

    def test_authentication_failure_stops_followup_writes(self):
        self.client.push_error = runner.ApiError("denied", 401)
        first = self.suite.run_feature("fast_snake_conflict", lambda: self.suite.submit(self.suite.payload("auth")))
        second = self.suite.run_feature("fast_camel_conflict", lambda: self.suite.submit(self.suite.payload("must-not-send")))
        self.assertEqual(first["status"], "error")
        self.assertEqual(second["status"], "skip")
        self.assertEqual(len(self.client.pushes), 1)

    def test_push_transport_failure_is_not_retried(self):
        self.client.push_error = runner.ApiError("timeout", retryable=True)
        result = self.suite.run_feature("fast_snake_conflict", lambda: self.suite.submit(self.suite.payload("timeout")))
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.client.pushes), 1)

    def test_release_mismatch_cannot_pass(self):
        payload = self.suite.payload("version")
        result = response(payload["message_key"])
        result["versions"]["dti"] = "old"
        self.client.push_result = result
        feature = self.suite.run_feature("fast_snake_conflict", lambda: self.suite.submit(payload))
        self.assertEqual(feature["status"], "fail")

    def test_fast_response_budget_cannot_pass_a_slow_post(self):
        payload = self.suite.payload("slow")
        def slow_post(_payload):
            self.clock.sleep(self.suite.settings.fast_post_max_seconds + 1)
            return response(payload["message_key"])
        self.client.push_result = slow_post
        feature = self.suite.run_feature("fast_snake_conflict", lambda: self.suite.submit(payload))
        self.assertEqual(feature["status"], "fail")
        self.assertEqual(len(self.client.pushes), 1)

    def test_sequential_replay_cannot_change_incident(self):
        case = self.ready_case()
        self.client.push_result = response(case["key"], FOREIGN, FOREIGN)
        with self.assertRaises(runner.CheckFailed):
            self.suite.submit(case["payload"], existing=case)
        self.assertEqual(len(self.client.pushes), 2)

    def test_event_mutation_is_rejected_before_client(self):
        self.ready_case()
        with self.assertRaises(ValueError):
            self.suite.patch_owned("em_event", EVENT, {"state": "Processed"})
        self.assertEqual(self.client.requests, [])

    def test_incident_patch_requires_current_ownership_and_dti_provenance(self):
        case = self.ready_case()
        self.suite.patch_owned("incident", INCIDENT, {"state": "6", "close_code": "Solution provided", "close_notes": "owned"})
        self.assertEqual(len(self.client.requests), 1)
        self.client.tables["incident"][0]["correlation_display"] = "not USBEM DTI"
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("incident", INCIDENT, {"state": "7"})
        self.client.tables["incident"][0]["correlation_display"] = "USBEM DTI"
        self.client.tables["incident"][0]["correlation_id"] = "foreign"
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("incident", INCIDENT, {"state": "7"})
        self.assertEqual(len(self.client.requests), 1)
        self.assertTrue(case["key"].startswith(self.suite.prefix))

    def test_unowned_incident_cannot_be_patched(self):
        self.ready_case()
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("incident", FOREIGN, {"state": "6"})
        self.assertEqual(self.client.requests, [])

    def test_alert_patch_cannot_inject_foreign_reference_or_protected_field(self):
        case = self.ready_case()
        self.suite.owned[("em_alert", ALERT)] = case["key"]
        for changes in ({"incident": FOREIGN}, {"task": INCIDENT}, {"additional_info": "{}"}, {"work_notes": "no"}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, runner.CheckFailed)):
                self.suite.patch_owned("em_alert", ALERT, changes)
        self.assertEqual(self.client.requests, [])

    def test_alert_patch_requires_fresh_message_key(self):
        case = self.ready_case()
        self.suite.owned[("em_alert", ALERT)] = case["key"]
        self.client.tables["em_alert"][0]["message_key"] = "foreign"
        with self.assertRaises(runner.CheckFailed):
            self.suite.patch_owned("em_alert", ALERT, {"incident": INCIDENT})
        self.assertEqual(self.client.requests, [])

    def test_alert_link_target_requires_fresh_incident_provenance_not_only_cached_ownership(self):
        case = self.ready_case()
        self.suite.owned[("em_alert", ALERT)] = case["key"]
        for field, changed in (("correlation_id", "no-longer-owned"), ("correlation_display", "not USBEM DTI")):
            with self.subTest(field=field):
                original = self.client.tables["incident"][0][field]
                self.client.tables["incident"][0][field] = changed
                with self.assertRaises(runner.CheckFailed):
                    self.suite.patch_owned("em_alert", ALERT, {"incident": INCIDENT})
                self.client.tables["incident"][0][field] = original
        self.assertEqual(self.client.requests, [])

    def test_acl_denied_patch_is_not_a_success(self):
        self.ready_case()
        self.client.request_error = runner.ApiError("denied", 403)
        feature = self.suite.run_feature("terminal_6", lambda: self.suite.patch_owned("incident", INCIDENT, {"state": "6"}))
        self.assertEqual(feature["status"], "skip")
        self.assertEqual(len(self.client.requests), 1)

    def test_missing_fixture_is_explicitly_incomplete(self):
        feature = self.suite.run_feature("service_name", lambda: self.suite.require("service_name"))
        self.assertEqual(feature["status"], "skip")
        self.assertEqual(runner.aggregate_status([feature]), "incomplete")
        self.assertEqual(self.client.pushes, [])

    def test_note_helper_reads_only_owned_record_work_notes_not_the_journal_table(self):
        self.ready_case()
        self.client.tables["incident"][0]["work_notes"] = "offline-note"
        self.suite.assert_note([INCIDENT], "offline-note", 1, "sentinel")
        self.assertEqual(self.suite.note_observations[-1]["exact_history_count_verified"], False)
        self.assertTrue(self.suite.note_observations[-1]["visible_presence"])
        self.assertNotIn("sys_journal_field", {query[0] for query in self.client.queries})

    def test_transient_safe_read_error_is_retried_without_reposting(self):
        case = self.ready_case()
        original_query = self.client.query
        attempts = []
        def transient(table, query, fields, timeout, limit=1000):
            attempts.append(table)
            if len(attempts) == 1:
                raise runner.ApiError("temporary read failure", 503, retryable=True)
            return original_query(table, query, fields, timeout, limit)
        self.client.query = transient
        self.suite.settle([case])
        self.assertEqual(case.get("transient_read_errors"), 1)
        self.assertFalse(case.get("observation_failed", False))
        self.assertEqual(len(self.client.pushes), 1)

    def test_stored_evidence_drift_after_readiness_is_a_failure(self):
        case = self.ready_case()
        self.assertTrue(self.suite.snapshot(case, self.clock.monotonic() + 8))
        self.client.tables["em_event"][0]["state"] = "Ready"
        with self.assertRaises(runner.CheckFailed):
            self.suite.snapshot(case, self.clock.monotonic() + 8)

    def test_manifest_dispatches_every_declared_production_feature(self):
        invoked = []
        def feature(name, callback, required=()):
            invoked.append(name)
            row = {"name": name, "status": "known_limitation" if name == "concurrent_first_events" else "pass"}
            self.suite.features.append(row)
            return row
        self.suite.features = []
        with patch.object(self.suite, "run_feature", side_effect=feature), patch.object(self.suite, "settle"):
            report = self.suite.run()
        self.assertEqual(set(invoked), set(self.suite.MANIFEST))
        self.assertEqual(len(invoked), len(self.suite.MANIFEST))
        self.assertEqual(report["status"], "complete_with_known_limitations")
        self.assertEqual(report["post_retries"], 0)
        self.assertFalse(report["legacy_wait_included"])
        self.assertTrue(report["records_retained"])
        self.assertIn("evidence_boundaries", report)
        self.assertNotIn("foreign_task_guard", report["manifest"])

    def test_actual_failed_preflight_run_cannot_submit_events(self):
        self.suite.features = []
        self.client.query_error = runner.ApiError("table access denied", 403)
        report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])
        self.assertTrue(all(request[0] == "GET" for request in self.client.requests))
        self.assertEqual(set(report["manifest"]), set(self.suite.MANIFEST))
        self.assertTrue(all(feature["status"] != "pass" for feature in report["features"] if feature["name"] != "read_preflight"))

    def test_actual_missing_ci_control_run_stays_inside_three_table_boundary(self):
        self.suite.features = []
        self.seed_preflight()
        with patch.object(self.suite, "ci_case", side_effect=runner.MissingFixture("offline fixture unavailable")):
            report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])
        self.assertTrue(all(request[0] == "GET" for request in self.client.requests))
        preflight = next(feature for feature in report["features"] if feature["name"] == "read_preflight")
        self.assertEqual(preflight["status"], "pass")
        self.assertEqual({item["table"] for item in preflight["evidence"]["readable_tables"]}, StrictClient.TABLES)
        self.assertEqual({query[0] for query in self.client.queries}, StrictClient.TABLES)

    def test_forbidden_alert_on_suppressed_event_fails(self):
        case = self.ready_case(want_alert=False)
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_empty_populated_probe_is_not_proof_of_field_access(self):
        self.suite.features = []
        self.suite.fixtures = complete_catalog()
        report = self.suite.run()
        preflight = next(item for item in report["features"] if item["name"] == "read_preflight")
        self.assertEqual(preflight["status"], "skip")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])

    def test_populated_probe_detects_field_acl_before_any_writes(self):
        self.suite.features = []
        self.seed_preflight()
        self.client.hidden_fields.add("work_notes")
        report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(self.client.pushes, [])
        self.assertTrue(all(request[0] == "GET" for request in self.client.requests))

    def test_complete_catalog_validation_requires_no_reference_or_admin_table_reads(self):
        self.suite.fixtures = complete_catalog()
        self.suite.validate_production_catalog()
        self.assertEqual(self.client.queries, [])
        self.assertEqual(self.client.requests, [])
        self.assertEqual(self.client.pushes, [])
        self.assertEqual(self.suite.owner_attestations_used, self.suite.ATTESTED_FEATURES)

    def test_missing_owner_attestation_never_becomes_a_passing_lookup(self):
        for value in (None, False, "true", 1):
            with self.subTest(value=value):
                self.suite.fixtures = complete_catalog()
                self.suite.fixtures["production_attestations"]["canonical_ci_name"] = value
                feature = self.suite.run_feature("read_preflight", self.suite.preflight)
                self.assertEqual(feature["status"], "skip")
        self.assertEqual(self.client.pushes, [])

    def test_legacy_wait_is_rejected_in_every_nested_fixture_context(self):
        for context in ({"wait_for_alert": True}, {"payload": {"waitForIncident": True}},
                        {"additional_info": '{"dti_wait_for_alert":true}'},
                        {"additionalInfo": {"nested": [{"dtiWaitForIncident": True}]}}):
            with self.subTest(context=context), self.assertRaises(ValueError):
                self.suite.refuse_legacy_wait(context)
        self.assertEqual(self.client.pushes, [])

    def test_work_note_field_acl_is_incomplete_even_for_an_expected_absence(self):
        self.ready_case()
        self.client.hidden_fields.add("work_notes")
        with self.assertRaises(runner.MissingFixture):
            self.suite.assert_note([INCIDENT], "absent-sentinel", 0, "must-read-before-negative")
        self.assertEqual(self.suite.note_observations, [])

    def test_visible_formatted_note_presence_does_not_claim_exact_history_count(self):
        self.ready_case()
        self.client.tables["incident"][0]["work_notes"] = "offline-note\n\noffline-note"
        self.suite.assert_note([INCIDENT], "offline-note", 1, "visible-view-only")
        self.assertFalse(self.suite.note_observations[-1]["exact_history_count_verified"])

    def test_expected_absent_latest_note_fails_if_visible(self):
        self.ready_case()
        self.client.tables["incident"][0]["work_notes"] = "unexpected-sentinel"
        with self.assertRaises(runner.CheckFailed):
            self.suite.assert_note([INCIDENT], "unexpected-sentinel", 0, "latest-negative")

    def test_blank_raw_journal_uses_exact_owned_record_formatted_view(self):
        self.ready_case()
        self.client.tables["incident"][0]["work_notes"] = "2026-10-29 - Offline user (Work notes)\nunique-sentinel"
        raw = self.suite.query("incident", "sys_id=" + INCIDENT, "sys_id,work_notes")
        self.assertEqual(raw[0]["work_notes"], "")
        self.suite.assert_note([INCIDENT], "unique-sentinel", 1, "formatted-positive")
        self.assertEqual(len(self.client.requests), 1)
        method, path, body, _ = self.client.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(urllib.parse.urlsplit(path).path, "/api/now/table/incident/" + INCIDENT)
        self.assertIsNone(body)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        self.assertEqual(params["sysparm_display_value"], ["true"])
        self.assertEqual(set(params["sysparm_fields"][0].split(",")), {"sys_id", "work_notes"})
        self.assertEqual(set(params), {"sysparm_display_value", "sysparm_fields", "sysparm_exclude_reference_link"})
        observation = self.suite.note_observations[-1]
        self.assertTrue(observation["visible_presence"])
        self.assertFalse(observation["complete_raw_history_verified"])
        self.assertFalse(observation["exact_history_count_verified"])

    def test_empty_formatted_view_cannot_pass_an_expected_negative_note(self):
        self.ready_case()
        with self.assertRaises(runner.MissingFixture):
            self.suite.assert_note([INCIDENT], "absent-sentinel", 0, "empty-is-not-absence-proof")
        self.assertEqual(self.suite.note_observations, [])

    def test_missing_or_nonstring_formatted_journal_is_incomplete(self):
        self.ready_case()
        for value in ({"sys_id": INCIDENT}, {"sys_id": INCIDENT, "work_notes": None},
                      {"sys_id": INCIDENT, "work_notes": []}, {"sys_id": INCIDENT, "work_notes": " \n\t"}):
            with self.subTest(value=value):
                self.client.journal_responses[("incident", INCIDENT)] = value
                with self.assertRaises(runner.MissingFixture):
                    self.suite.assert_note([INCIDENT], "absent-sentinel", 0, "must-read-formatted-journal")
        self.assertEqual(self.suite.note_observations, [])

    def test_formatted_journal_wrong_identity_is_a_failure(self):
        self.ready_case()
        self.client.journal_responses[("incident", INCIDENT)] = {"sys_id": FOREIGN, "work_notes": "sentinel"}
        with self.assertRaises(runner.CheckFailed):
            self.suite.assert_note([INCIDENT], "sentinel", 1, "must-be-same-record")

    def test_formatted_journal_nonrecord_shape_is_an_error(self):
        self.ready_case()
        for value in ([], [{"sys_id": INCIDENT, "work_notes": "sentinel"}], "not-a-record", None):
            with self.subTest(value=value):
                self.client.journal_responses[("incident", INCIDENT)] = value
                with self.assertRaises(runner.ApiError):
                    self.suite.assert_note([INCIDENT], "sentinel", 1, "invalid-display-shape")

    def test_fresh_raw_provenance_is_verified_before_formatted_journal_request(self):
        case = self.ready_case()
        self.suite.owned[("em_alert", ALERT)] = case["key"]
        for table, record_id, field, changed in (("incident", INCIDENT, "correlation_id", "foreign"),
                                                ("incident", INCIDENT, "correlation_display", "not USBEM DTI"),
                                                ("em_alert", ALERT, "message_key", "foreign")):
            with self.subTest(table=table, field=field):
                original = self.client.tables[table][0][field]
                self.client.tables[table][0][field] = changed
                with self.assertRaises(runner.CheckFailed):
                    self.suite.assert_note([record_id], "sentinel", 1, "fresh-provenance-first")
                self.client.tables[table][0][field] = original
        self.assertEqual(self.client.requests, [])

    def test_formatted_journal_acl_denial_is_incomplete_not_negative_pass(self):
        self.ready_case()
        self.client.request_error = runner.ApiError("display view denied", 403)
        feature = self.suite.run_feature("default_and_duplicate_notes", lambda: self.suite.assert_note([INCIDENT], "sentinel", 0, "denied-display"))
        self.assertEqual(feature["status"], "skip")
        self.assertEqual(feature["http_status"], 403)
        self.assertEqual(self.suite.note_observations, [])

    def test_non_incident_task_helpers_fail_before_any_reference_read(self):
        with self.assertRaises(ValueError):
            self.suite.validate_task_fixture(FOREIGN)
        with self.assertRaises(runner.MissingFixture):
            self.suite.foreign_task_case()
        self.assertEqual(self.client.queries, [])
        self.assertEqual(self.client.requests, [])

    def test_duplicate_alerts_for_a_unique_non_lifecycle_key_fail(self):
        case = self.ready_case()
        self.client.tables["em_alert"].append(dict(self.client.tables["em_alert"][0], sys_id=FOREIGN))
        self.suite.settle([case])
        self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_event_and_alert_ci_binding_are_validated_end_to_end(self):
        for table in ("em_event", "em_alert"):
            with self.subTest(table=table):
                self.setUp()
                case = self.ready_case()
                self.client.tables[table][0]["cmdb_ci"] = DECOY
                self.suite.settle([case])
                self.assertEqual(self.suite.features[0]["status"], "fail")

    def test_advanced_branch_fixture_cannot_hide_stronger_routing_aliases(self):
        for key in ("ciIdentifiers", "ciIdentifier", "cmdbCi", "hostName", "assignmentGroup", "serviceOffering", "directToIncident"):
            for nested in (False, True):
                with self.subTest(key=key, nested=nested):
                    fixture = copy.deepcopy(complete_catalog()["advanced_cases"]["node_fallback"])
                    fixture["payload"].update({"additional_info": {key: "offline-hidden-route"}} if nested else {key: "offline-hidden-route"})
                    with self.assertRaises(runner.MissingFixture):
                        self.suite.advanced_payload("node_fallback", fixture)
        self.assertEqual(self.client.pushes, [])

    def test_expected_custom_field_acl_is_checked_in_populated_preflight(self):
        self.seed_preflight()
        self.client.hidden_fields.add("u_usb_em_test_value")
        feature = self.suite.run_feature("read_preflight", self.suite.preflight)
        self.assertEqual(feature["status"], "skip")
        self.assertEqual(self.client.pushes, [])

    def test_nonstandard_correlation_length_is_rejected_without_requests(self):
        for value in (99, 101, "100", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.ProductionRunner(self.client, settings(), {"correlation_length": value}, self.clock.monotonic, self.clock.sleep)
        self.assertEqual(self.client.queries, [])
        self.assertEqual(self.client.requests, [])

    def test_direct_reference_dotwalk_is_rejected_before_client_query(self):
        for fields in ("sys_id,caller_id.email", "sys_id,assignment_group.name", "sys_id,incident.number"):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.suite.query("incident", "sys_id=" + INCIDENT, fields)
        self.assertEqual(self.client.queries, [])

    def test_nonstring_stored_expectations_are_incomplete_before_any_event(self):
        for section, field in (("expected_incident", "u_usb_em_test_value"), ("expected_event", "severity")):
            for value in (0, False, None, [], {}, [0], {"nested": False}):
                with self.subTest(section=section, value=value):
                    self.setUp()
                    self.seed_preflight()
                    self.suite.fixtures["advanced_cases"]["custom_incident_fields"][section] = {field: value}
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_string_zero_false_and_blank_are_valid_stored_expectation_types(self):
        for value in ("0", "false", ""):
            with self.subTest(value=value):
                self.suite.fixtures = complete_catalog()
                fixture = self.suite.fixtures["advanced_cases"]["custom_incident_fields"]
                fixture["expected_incident"]["u_usb_em_test_value"] = value
                fixture["expected_event"] = {"severity": value}
                self.suite.validate_production_catalog()
        self.assertEqual(self.client.pushes, [])

    def test_raw_zero_false_or_null_never_compare_equal_to_blank(self):
        for actual, expected in ((0, ""), (False, ""), (None, ""), ("", 0), ("", False), ("", None)):
            with self.subTest(actual=actual, expected=expected), self.assertRaises((runner.CheckFailed, runner.MissingFixture, ValueError)):
                self.suite.equal(actual, expected, "strict stored-value comparison")
        for value in ("", "0", "false", "1", "true"):
            self.suite.equal(value, value, "valid stored string")

    def test_actual_nonstring_field_cannot_satisfy_expected_blank(self):
        for value in (0, False, None):
            with self.subTest(value=value):
                self.setUp()
                case = self.ready_case(expected={**self.suite.expected(self.suite.payload("offline-case")), "assigned_to": ""})
                self.client.tables["incident"][0]["assigned_to"] = value
                self.suite.settle([case])
                self.assertNotEqual(self.suite.features[0]["status"], "pass")
                self.assertTrue(case["observation_failed"])

    def test_native_json_payload_and_expectations_are_not_coerced_to_strings(self):
        self.suite.fixtures = complete_catalog()
        native = {"zero": 0, "false": False, "null": None, "nested": [False, 0, None, {"true": True}]}
        fixture = self.suite.fixtures["advanced_cases"]["custom_incident_fields"]
        fixture["payload"]["additional_info"] = {"native": native}
        fixture["expected_additional_info"] = {"native": copy.deepcopy(native)}
        self.suite.validate_production_catalog()
        payload = self.suite.advanced_payload("custom_incident_fields", fixture)
        self.assertEqual(payload["additional_info"]["native"], native)
        self.assertIs(payload["additional_info"]["native"]["false"], False)
        self.assertIs(payload["additional_info"]["native"]["null"], None)
        self.assertIs(type(payload["additional_info"]["native"]["zero"]), int)

    def test_native_json_boolean_and_number_mismatches_cannot_pass_final_evidence(self):
        pairs = ((False, 0), (True, 1), (0, False), (1, True),
                 ({"nested": False}, {"nested": 0}), ([False, {"value": 1}], [0, {"value": True}]),
                 ({"deep": {"array": [False]}}, {"deep": {"array": [0]}}))
        for expected, actual in pairs:
            with self.subTest(expected=expected, actual=actual):
                self.setUp()
                case = self.ready_case()
                case["expected_additional_info"] = {"native": expected}
                self.client.tables["em_event"][0]["additional_info"] = json.dumps({"native": actual})
                self.suite.settle([case])
                self.suite.generic_baseline = set()
                self.suite.run_feature("final_evidence_integrity", self.suite.finish_evidence)
                self.assertEqual(runner.aggregate_status(self.suite.features), "fail")

    def test_matching_native_json_types_pass_final_evidence(self):
        for value in (False, True, 0, 1, None, {"nested": [False, 0, None, {"true": True}]}, [1, "1", False]):
            with self.subTest(value=value):
                self.setUp()
                case = self.ready_case()
                case["expected_additional_info"] = {"native": value}
                self.client.tables["em_event"][0]["additional_info"] = json.dumps({"native": value})
                self.suite.settle([case])
                self.suite.generic_baseline = set()
                self.suite.run_feature("final_evidence_integrity", self.suite.finish_evidence)
                self.assertEqual(runner.aggregate_status(self.suite.features), "pass")

    def test_json_numbers_accept_equivalent_int_and_float_but_not_nonfinite_extensions(self):
        self.assertTrue(self.suite.strict_json_equal(1, 1.0))
        self.assertTrue(self.suite.strict_json_equal({"number": 0}, {"number": 0.0}))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertFalse(self.suite.strict_json_equal(value, value))
                self.assertFalse(self.suite.strict_json_equal({"nested": [value]}, {"nested": [value]}))

    def test_recursive_json_comparison_preserves_container_keys_lengths_and_array_order(self):
        for left, right in (({"a": False}, {"a": False, "extra": 0}), ([False], [False, 0]),
                            ([0, False], [False, 0]), ({"value": []}, {"value": {}}), (None, ""), (0, "0")):
            with self.subTest(left=left, right=right):
                self.assertFalse(self.suite.strict_json_equal(left, right))

    def test_malformed_additional_info_expectation_shapes_are_incomplete_before_events(self):
        for field, invalid_values in (("expected_additional_info", (None, False, 0, "text", [], {"": "empty-key"})),
                                      ("absent_additional_info", (None, False, 0, "text", {}, [""], [0], [None])),
                                      ("remove_fields", (None, False, 0, "description", {}, [""], [0], ["caller_id.name"]))):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.seed_preflight()
                    self.suite.fixtures["advanced_cases"]["custom_incident_fields"][field] = value
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_malformed_multi_control_members_are_rejected_before_field_access_or_writes(self):
        for name in ("offering_parent_filter", "default_dummy_policy"):
            for value in (None, False, 0, [], "not-a-member", {"payload": [], "expected_incident": {}}):
                with self.subTest(name=name, value=value):
                    self.setUp()
                    self.seed_preflight()
                    self.suite.fixtures["advanced_cases"][name][0] = value
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_nonfinite_native_json_fixture_extensions_are_rejected_before_events(self):
        for section in ("payload", "expected_additional_info"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(section=section, value=value):
                    self.setUp()
                    self.seed_preflight()
                    fixture = self.suite.fixtures["advanced_cases"]["custom_incident_fields"]
                    if section == "payload":
                        fixture[section]["additional_info"] = {"native": {"nested": [value]}}
                    else:
                        fixture[section] = {"native": {"nested": [value]}}
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_nonstring_raw_alert_reference_cannot_masquerade_as_no_incident(self):
        for value in (False, 0, None):
            with self.subTest(value=value):
                self.setUp()
                case = self.ready_case()
                case["want_incident"], case["active_incident"], case["incident_ids"] = False, "", set()
                self.client.tables["incident"] = []
                self.client.tables["em_alert"][0]["incident"] = value
                self.suite.settle([case])
                self.assertEqual(self.suite.features[0]["status"], "error")
                self.assertTrue(case["observation_failed"])

    def test_numeric_top_level_reference_ids_are_rejected_before_events(self):
        for field in ("assignee_sys_id", "default_caller_sys_id", "ci_support_sys_id", "ci_support_group_sys_id",
                      "service_sys_id", "offering_sys_id", "default_ci_sys_id"):
            with self.subTest(field=field):
                self.setUp()
                self.seed_preflight()
                self.suite.fixtures[field] = int("1" * 32)
                report = self.suite.run()
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(self.client.pushes, [])
                self.assertEqual(self.client.requests, [])

    def test_malformed_optional_lifecycle_values_are_rejected_before_events(self):
        for field in ("terminal_close_code", "alert_closed_state"):
            for value in (None, False, 0, [], {}, "", " \n\t"):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.seed_preflight()
                    self.suite.fixtures[field] = value
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_removed_or_nonstring_base_expected_fields_are_rejected_before_events(self):
        for field in ("description", "dti_short_description"):
            for value in ("remove", None, False, 0, [], {}):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.seed_preflight()
                    fixture = self.suite.fixtures["advanced_cases"]["custom_incident_fields"]
                    if value == "remove":
                        fixture["remove_fields"] = [field]
                    else:
                        fixture["payload"][field] = value
                    report = self.suite.run()
                    self.assertEqual(report["status"], "incomplete")
                    self.assertEqual(self.client.pushes, [])
                    self.assertEqual(self.client.requests, [])

    def test_each_required_incident_field_must_have_nonempty_complete_expectation(self):
        for field in ("caller_id", "category", "subcategory", "impact", "urgency", "short_description", "description"):
            with self.subTest(field=field):
                self.setUp()
                self.seed_preflight()
                fixture = self.suite.fixtures["advanced_cases"]["custom_incident_fields"]
                fixture["expected_incident"][field] = ""
                report = self.suite.run()
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(self.client.pushes, [])
                self.assertEqual(self.client.requests, [])

    def model_suite(self):
        client = ManifestModelClient()
        suite = runner.ProductionRunner(client, settings(), complete_catalog(), self.clock.monotonic, self.clock.sleep)
        client.suite = suite
        suite.current_feature = "severity_5"
        return suite, client

    def test_native_ok_severity_five_and_ok_label_expect_an_alert_without_incident(self):
        for severity in ("5", "OK"):
            with self.subTest(severity=severity):
                suite, _ = self.model_suite()
                suite.severity_case(severity)
                case = suite.cases[-1]
                self.assertFalse(case["want_incident"])
                self.assertTrue(case["want_alert"])
                self.assertEqual(case["expected_event"]["severity"], "5")
                self.assertTrue(ManifestModelClient.native_alert_expected(case))

    def test_native_clear_zero_and_clear_label_expect_neither_alert_nor_incident(self):
        for severity in ("0", "clear"):
            with self.subTest(severity=severity):
                suite, _ = self.model_suite()
                suite.severity_case(severity)
                case = suite.cases[-1]
                self.assertFalse(case["want_incident"])
                self.assertFalse(case["want_alert"])
                self.assertFalse(ManifestModelClient.native_alert_expected(case))

    def test_mixed_batch_informational_member_uses_native_ok_alert_contract(self):
        suite, _ = self.model_suite()
        suite.batch("records", True)
        self.assertEqual([case["want_incident"] for case in suite.cases], [False, True, False])
        self.assertEqual([case["want_alert"] for case in suite.cases], [True, True, True])
        self.assertTrue(ManifestModelClient.native_alert_expected(suite.cases[-1]))

    def test_parser_open_defaults_generate_ok_alerts_but_closing_informational_does_not(self):
        suite, _ = self.model_suite()
        suite.parser_case()
        by_name = {case["name"]: case for case in suite.cases}
        closing = by_name["parser-contract"]
        self.assertFalse(closing["want_alert"])
        self.assertEqual(closing["expected_event"]["resolution_state"], "Closing")
        self.assertFalse(ManifestModelClient.native_alert_expected(closing))
        for name in ("ai-text", "ai-array", "generated", "generic-defaults", "truncated-key"):
            with self.subTest(name=name):
                self.assertTrue(by_name[name]["want_alert"])
                self.assertFalse(by_name[name]["want_incident"])
                self.assertEqual(by_name[name]["expected_event"]["severity"], "5")
                self.assertTrue(ManifestModelClient.native_alert_expected(by_name[name]))

    def test_salesforce_closing_cases_stay_alert_free_including_explicit_ok_five(self):
        suite, _ = self.model_suite()
        suite.salesforce_case()
        self.assertTrue(all(not case["want_incident"] for case in suite.cases))
        open_count, closed_count = 0, 0
        for case in suite.cases:
            event = ManifestModelClient.normalized(case["wire"])
            status = event.get("status", event.get("case_status"))
            if status == "Closed":
                closed_count += 1
                self.assertFalse(case["want_alert"])
                self.assertFalse(ManifestModelClient.native_alert_expected(case))
            elif status == "Open":
                open_count += 1
                self.assertTrue(case["want_alert"])
                self.assertTrue(ManifestModelClient.native_alert_expected(case))
        self.assertGreaterEqual(closed_count, 5)
        self.assertEqual(open_count, 3)

    def test_explicit_advanced_alert_expectation_is_not_rewritten_by_default_callback_fixes(self):
        suite, _ = self.model_suite()
        fixture = copy.deepcopy(suite.fixtures["advanced_cases"]["default_dummy_policy"][0])
        fixture["want_alert"] = False
        case = suite.advanced_record("default_dummy_policy", fixture)
        self.assertFalse(case["want_alert"])
        self.assertTrue(ManifestModelClient.native_alert_expected(case))

    def test_event_additional_info_must_be_json_object_even_without_custom_expectations(self):
        for value in ("[]", "null", "false", "0", '"text"', "not-json"):
            with self.subTest(value=value):
                self.setUp()
                case = self.ready_case()
                self.client.tables["em_event"][0]["additional_info"] = value
                self.suite.settle([case])
                self.suite.generic_baseline = set()
                self.suite.run_feature("final_evidence_integrity", self.suite.finish_evidence)
                self.assertEqual(runner.aggregate_status(self.suite.features), "fail")

    def test_alert_additional_info_must_be_json_object_during_observation(self):
        for value in ("[]", "null", "false", "0", '"text"', "not-json"):
            with self.subTest(value=value):
                self.setUp()
                case = self.ready_case()
                self.client.tables["em_alert"][0]["additional_info"] = value
                self.suite.settle([case])
                self.assertEqual(self.suite.features[0]["status"], "fail")
                self.assertTrue(case["observation_failed"])

    def test_unexecuted_manifest_feature_cannot_be_reported_complete(self):
        omitted = "offering_name"
        def feature(name, callback, required=()):
            row = {"name": name, "status": "pass"}
            if name != omitted:
                self.suite.features.append(row)
            return row
        self.suite.features = []
        with patch.object(self.suite, "run_feature", side_effect=feature), patch.object(self.suite, "settle"):
            report = self.suite.run()
        self.assertEqual(report["status"], "incomplete")
        missing = next(feature for feature in report["features"] if feature["name"] == omitted)
        self.assertEqual(missing["status"], "skip")


class ProductionCLITests(unittest.TestCase):
    @staticmethod
    def config_args(**overrides):
        values = {"profile": "PROD", "instance": "", "user": "", "password": ""}
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_profile_basic_password_uses_shared_username_without_global_target_fallback(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com", "SN_INSTANCE_URL": "https://wrong-target.service-now.com",
                  "SN_USERNAME": "offline-shared-user", "SN_PASSWORD": "offline-shared-password", "USBEM_PROD_PASSWORD": "offline-profile-password"}
        with patch.dict(runner.os.environ, {}, clear=True):
            instance, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
        self.assertEqual(instance, "https://offline-production.service-now.com")
        self.assertEqual(auth, {"mode": "basic", "username": "offline-shared-user", "password": "offline-profile-password"})

    def test_profile_base64_credentials_and_explicit_plain_profile_precedence(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com", "SN_USERNAME": "offline-shared-user",
                  "SN_PASSWORD": "offline-shared-password", "USBEM_PROD_USERNAME_B64": base64.b64encode(b"offline-profile-user").decode(),
                  "USBEM_PROD_PASSWORD_B64": base64.b64encode(b"offline-profile-password").decode()}
        with patch.dict(runner.os.environ, {}, clear=True):
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
            self.assertEqual(auth["username"], "offline-profile-user")
            self.assertEqual(auth["password"], "offline-profile-password")
            values["USBEM_PROD_PASSWORD"] = "offline-profile-plain"
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
            self.assertEqual(auth["password"], "offline-profile-plain")

    def test_profile_base64_password_precedes_generic_usb_password(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com", "SN_USERNAME": "offline-shared-user",
                  "USBEM_PASSWORD": "offline-global-wrong-password",
                  "USBEM_PROD_PASSWORD_B64": base64.b64encode(b"offline-profile-password").decode()}
        with patch.dict(runner.os.environ, {}, clear=True):
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
        self.assertEqual(auth["password"], "offline-profile-password")

    def test_profile_base64_oauth_secret_precedes_global_plain_secret(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com",
                  "USBEM_OAUTH_CLIENT_ID": "offline-global-wrong-client", "USBEM_OAUTH_CLIENT_SECRET": "offline-global-wrong-secret",
                  "USBEM_PROD_OAUTH_CLIENT_ID_B64": base64.b64encode(b"offline-profile-client").decode(),
                  "USBEM_PROD_OAUTH_CLIENT_SECRET_B64": base64.b64encode(b"offline-profile-secret").decode()}
        with patch.dict(runner.os.environ, {}, clear=True):
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
        self.assertEqual(auth, {"mode": "oauth", "client_id": "offline-profile-client", "client_secret": "offline-profile-secret", "scope": ""})

    def test_missing_profile_basic_credentials_fall_back_to_shared_sn_credentials(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com", "SN_USERNAME": "offline-shared-user",
                  "SN_PASSWORD": "offline-shared-password"}
        with patch.dict(runner.os.environ, {}, clear=True):
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
        self.assertEqual(auth, {"mode": "basic", "username": "offline-shared-user", "password": "offline-shared-password"})

    def test_profile_basic_environment_override_wins_same_key_in_file(self):
        values = {"USBEM_PROD_URL": "https://offline-production.service-now.com", "SN_USERNAME": "offline-shared-user",
                  "USBEM_PROD_PASSWORD": "offline-file-password"}
        with patch.dict(runner.os.environ, {"USBEM_PROD_PASSWORD": "offline-environment-password"}, clear=True):
            _, auth, _ = runner.configuration(self.config_args(), values, connection_only=True)
        self.assertEqual(auth["password"], "offline-environment-password")

    def test_selected_empty_profile_cannot_run_against_a_global_instance(self):
        for url in ("", " ", None):
            values = {"SN_INSTANCE_URL": "https://wrong-target.service-now.com", "SN_USERNAME": "offline-only",
                      "SN_PASSWORD": "offline-only", "USBEM_PROD_URL": url}
            with self.subTest(url=url), patch.dict(runner.os.environ, {}, clear=True), self.assertRaises(ValueError):
                runner.configuration(self.config_args(), values, connection_only=True)

    def test_production_plan_and_manifest_need_no_environment_auth_or_network(self):
        for flag in ("--plan", "--list-tests"):
            with self.subTest(flag=flag), patch.object(sys, "argv", ["dti-tester", "--access-profile", "production", flag]), \
                    patch.object(runner, "Client") as client, patch.object(runner, "configuration") as configuration, \
                    patch.object(runner, "read_env", side_effect=AssertionError("plan must not read env files")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 0)
                value = json.loads(output.getvalue())
                rendered = json.dumps(value)
                self.assertIn("terminal_6", rendered)
                self.assertIn("production", rendered.lower())
                client.assert_not_called()
                configuration.assert_not_called()

    def test_production_cli_selects_restricted_runner_and_status_exit_codes(self):
        for status, code in (("pass", 0), ("complete_with_known_limitations", 0), ("incomplete", 4), ("fail", 2), ("error", 3)):
            with self.subTest(status=status), patch.object(sys, "argv", ["dti-tester", "--access-profile", "production"]), \
                    patch.dict(runner.os.environ, {}, clear=True), patch.object(runner, "read_env", return_value={}), \
                    patch.object(runner, "configuration", return_value=("https://offline.service-now.com", {"mode": "basic"}, settings())), \
                    patch.object(runner, "Client"), patch.object(runner, "ComprehensiveRunner") as broad, \
                    patch.object(runner, "ProductionRunner") as production, contextlib.redirect_stdout(io.StringIO()) as output:
                production.return_value.run.return_value = {"status": status}
                self.assertEqual(runner.main(), code)
                production.assert_called_once()
                broad.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_production_profile_rejects_every_admin_fixture_flag_before_auth(self):
        combinations = (("--provision-dev-fixtures",), ("--prepare-fixtures-only",), ("--allow-default-ci-property",),
                        ("--fixture-output", "offline.json"), ("--fixture-recovery-file", "offline.json"),
                        ("--confirm-fixture-target", "https://dev123456.service-now.com"),
                        ("--restore-fixture-default-ci", "offline.json"))
        for flags in combinations:
            with self.subTest(flags=flags), patch.object(sys, "argv", ["dti-tester", "--access-profile", "production", *flags]), \
                    patch.object(runner, "Client") as client, patch.object(runner, "configuration") as configuration, \
                    patch.object(runner, "read_env", side_effect=AssertionError("reject admin flags before env access")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 3)
                self.assertEqual(json.loads(output.getvalue())["status"], "error")
                client.assert_not_called()
                configuration.assert_not_called()


class ProductionManifestTraceTests(unittest.TestCase):
    def test_real_production_manifest_callbacks_stay_inside_the_three_table_boundary(self):
        class ModelRunner(runner.ProductionRunner):
            def snapshot(self, case, deadline):
                self.client.materialize(case)
                return super().snapshot(case, deadline)
        clock, client = Clock(), ManifestModelClient()
        suite = ModelRunner(client, settings(), complete_catalog(), clock.monotonic, clock.sleep)
        client.suite = suite
        seed = ProductionBehaviorTests("test_ready_snapshot_uses_only_three_tables_and_stable_window")
        seed.suite, seed.client = suite, client
        seed.seed_preflight()
        report = suite.run()
        self.assertEqual(set(report["manifest"]), set(suite.MANIFEST))
        self.assertEqual({feature["name"] for feature in report["features"]}, set(suite.MANIFEST))
        self.assertEqual(report["counts"]["skip"], 0, [(feature["name"], feature.get("reason")) for feature in report["features"] if feature["status"] == "skip"])
        self.assertEqual(report["counts"]["error"], 0, [(feature["name"], feature.get("reason")) for feature in report["features"] if feature["status"] == "error"])
        self.assertEqual(report["counts"]["fail"], 0, [(feature["name"], feature.get("reason")) for feature in report["features"] if feature["status"] == "fail"])
        self.assertGreaterEqual(len(report["cases"]), 70)
        self.assertGreaterEqual(len(client.probes), 10)
        self.assertTrue(client.pushes)
        self.assertEqual({query[0] for query in client.queries}, StrictClient.TABLES)
        self.assertEqual({request[0] for request in client.requests}, {"GET", "PATCH"})
        self.assertTrue(any("/incident/" in request[1] for request in client.requests if request[0] == "PATCH"))
        self.assertTrue(any("/em_alert/" in request[1] for request in client.requests if request[0] == "PATCH"))
        self.assertTrue(report["visible_note_observations"])
        self.assertTrue(all(not note["exact_history_count_verified"] for note in report["visible_note_observations"]))
        self.assertEqual(len(report["debug_observations"]), 3)
        self.assertTrue(all(not debug["attachment_bytes_verified"] for debug in report["debug_observations"]))
        self.assertEqual(report["post_retries"], 0)


class ProductionPortabilityTests(unittest.TestCase):
    @staticmethod
    def windows_os_without_fchmod(directory):
        actual_os = runner.os
        class WindowsOS:
            name = "nt"

            def __getattr__(self, name):
                if name == "fchmod":
                    raise AttributeError("Windows Python has no os.fchmod")
                return getattr(actual_os, name)

            def open(self, path, flags, *args):
                if Path(path) == directory:
                    raise PermissionError("Windows directory handles do not support this POSIX fsync path")
                return actual_os.open(path, flags, *args)
        return WindowsOS()

    def test_report_write_and_atomic_replace_work_when_windows_has_no_fchmod(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            target = directory / "report.json"
            with patch.object(runner, "os", self.windows_os_without_fchmod(directory)):
                runner.write_private_json(target, {"status": "first"})
                runner.write_private_json(target, {"status": "replacement"})
            self.assertEqual(json.loads(target.read_text()), {"status": "replacement"})
            self.assertEqual(list(directory.iterdir()), [target])

    def test_exclusive_recovery_journal_preserves_original_without_windows_fchmod(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            target = directory / "recovery.json"
            with patch.object(runner, "os", self.windows_os_without_fchmod(directory)):
                runner.write_private_json(target, {"original": "preserved"}, exclusive=True)
                with self.assertRaises(FileExistsError):
                    runner.write_private_json(target, {"original": "must-not-overwrite"}, exclusive=True)
            self.assertEqual(json.loads(target.read_text()), {"original": "preserved"})


if __name__ == "__main__":
    unittest.main()
