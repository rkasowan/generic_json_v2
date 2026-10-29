#!/usr/bin/env python3
"""Offline behavioral tests for the standalone laptop runner; no live services or secrets."""

import argparse
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ci_identifier_precedence as runner

EXPECTED, DECOY, INCIDENT, EVENT, GROUP = (character * 32 for character in "abcde")


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def response(key, event_id=EVENT, incident_id=INCIDENT, mode="fast_async"):
    row = {"status": "success", "message_key": key, "event_sys_id": event_id, "incident_sys_id": incident_id,
           "dti_mode": mode, "dti_incident_status": "created"}
    return {"status": "success", "inserted": "1", "version": runner.EXPECTED_RELEASE,
            "versions": {name: runner.EXPECTED_RELEASE for name in ("listener", "core", "lookups", "debug", "dti")},
            "sys_ids": [event_id], "results": [row], **row}


class FakeClient:
    def __init__(self, clock):
        self.clock = clock
        self.pushes = []
        self.records = {}
        self.hidden_until = 0.0
        self.ci_ready_at = 0.0
        self.drift_at = float("inf")
        self.missing_response_id = False
        self.extra_incident = False
        self.return_different_duplicate = False
        self.different_concurrent = False
        self.transient_errors = 0
        self.read_error = None
        self.push_error = None
        self.mutate_response = None

    def push(self, source, payload, timeout):
        self.pushes.append(copy.deepcopy(payload))
        if self.push_error:
            raise self.push_error
        key = payload["message_key"]
        state = self.records.setdefault(key, {"events": [], "ci": "", "incident": format(len(self.records) + 1, "032x")})
        event_id = format(len(self.pushes) + 100, "032x")
        state["events"].append({"sys_id": event_id, "message_key": key})
        ci = payload.get("cmdb_ci", "")
        if ci == DECOY:
            state["ci"] = DECOY
        elif payload.get("ciIdentifier") or payload.get("ci_identifier"):
            state["ci"] = EXPECTED
        else:
            state["ci"] = DECOY
        state["fields"] = {field: payload.get(field, "") for field in ("caller_id", "category", "subcategory", "description")}
        state["fields"].update(impact=payload.get("dtiImpact", payload.get("dti_impact", "")),
                               urgency=payload.get("dtiUrgency", payload.get("dti_urgency", "")),
                               short_description=payload.get("dtiShortDescription", payload.get("dti_short_description", "")))
        incident_id = "" if self.missing_response_id else state["incident"]
        if (self.return_different_duplicate or self.different_concurrent) and len(state["events"]) > 1:
            incident_id = "9" * 32
        result = response(key, event_id, incident_id)
        if self.mutate_response:
            self.mutate_response(result)
        return result

    def rows(self, table, key, timeout):
        if self.read_error:
            raise self.read_error
        if self.transient_errors:
            self.transient_errors -= 1
            raise runner.ApiError("temporary read error", 503, True)
        state = self.records[key]
        if table == "em_event":
            return copy.deepcopy(state["events"])
        if self.clock.now < self.hidden_until:
            return []
        actual = state["ci"] if self.clock.now >= self.ci_ready_at else ""
        if self.clock.now >= self.drift_at:
            actual = DECOY if state["ci"] == EXPECTED else EXPECTED
        rows = [{"sys_id": state["incident"], "number": "INC-TEST", "cmdb_ci": actual,
                 "correlation_id": key, "assignment_group": GROUP, **state["fields"]}]
        if self.extra_incident:
            rows.append(dict(rows[0], sys_id="8" * 32))
        return rows


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.client = FakeClient(self.clock)
        self.settings = runner.Settings("genericJsonV2", "cmdb_ci_server", {"serial_number": "test"},
                                        "decoy", EXPECTED, DECOY, caller_id="f" * 32, timeout=12, stable_seconds=3,
                                        poll_seconds=1, request_timeout=8)
        self.runner = runner.Runner(self.client, self.settings, self.clock.monotonic, self.clock.sleep)

    def case(self, duplicate=False, submissions=1):
        return self.runner.run_case("example", {"ciType": "cmdb_ci_server", "ciIdentifier": {"serial_number": "test"},
                                                 "cmdb_ci": "decoy"}, EXPECTED, False, duplicate, "KEY", submissions)

    def test_delayed_incident_and_ci_pass_only_after_full_stable_dwell(self):
        self.client.hidden_until = 2
        self.client.ci_ready_at = 5
        result = self.case()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["elapsed_seconds"], 8)
        self.assertEqual(result["phases"][0]["polls"], 9)
        self.assertEqual(result["phases"][0]["stable_observed_seconds"], 3)

    def test_fast_response_must_include_incident_without_waiting(self):
        self.client.missing_response_id = True
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("promptly return", result["reason"])
        self.assertEqual(result["elapsed_seconds"], 0)

    def test_fast_post_latency_budget_is_enforced(self):
        original_push = self.client.push

        def slow_push(source, payload, timeout):
            self.assertEqual(timeout, min(self.settings.fast_post_max_seconds, self.settings.request_timeout))
            self.clock.now += 11
            return original_push(source, payload, timeout)

        self.client.push = slow_push
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("prompt return budget", result["reason"])

    def test_ci_that_never_arrives_times_out(self):
        self.client.ci_ready_at = 100
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("timed out", result["reason"])
        self.assertEqual(result["elapsed_seconds"], 12)

    def test_ci_drift_during_observation_fails(self):
        self.client.drift_at = 2
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("drifted", result["reason"])

    def test_duplicate_requires_two_distinct_events_and_one_same_incident(self):
        result = self.case(duplicate=True)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(self.client.pushes), 2)
        self.assertEqual(result["phases"][1]["actual_event_count"], 2)
        self.assertEqual(result["phases"][1]["actual_incident_count"], 1)
        self.assertEqual(result["elapsed_seconds"], 6)

    def test_duplicate_returning_different_incident_fails(self):
        self.client.return_different_duplicate = True
        result = self.case(duplicate=True)
        self.assertEqual(result["status"], "fail")
        self.assertIn("different incidents", result["reason"])

    def test_concurrent_different_response_ids_fail_before_readback(self):
        self.client.different_concurrent = True
        result = self.case(submissions=3)
        self.assertEqual(result["status"], "fail")
        self.assertIn("different incidents", result["reason"])
        self.assertEqual(len(self.client.pushes), 3)
        self.assertEqual(result["elapsed_seconds"], 0)
        self.assertEqual(len(result["phases"][0]["submissions"]), 3)

    def test_all_concurrent_transport_errors_are_collected_without_retry(self):
        self.client.push_error = runner.ApiError("access denied", 401)
        result = self.case(submissions=3)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["http_status"], 401)
        self.assertEqual(len(self.client.pushes), 3)
        self.assertEqual(len(result["phases"][0]["submission_errors"]), 3)

    def test_a_slow_read_cannot_pass_after_the_phase_deadline(self):
        original_rows = self.client.rows

        def slow_rows(table, key, timeout):
            self.clock.now += 7
            return original_rows(table, key, timeout)

        self.client.rows = slow_rows
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("deadline expired", result["reason"])

    def test_duplicate_phase_rejects_ci_drift_after_initial_stability(self):
        original_push = self.client.push

        def drift_on_duplicate(source, payload, timeout):
            if self.client.pushes:
                self.client.drift_at = self.clock.now
            return original_push(source, payload, timeout)

        self.client.push = drift_on_duplicate
        result = self.case(duplicate=True)
        self.assertEqual(result["status"], "fail")
        self.assertIn("drifted", result["reason"])

    def test_transient_reads_reset_the_required_stable_dwell(self):
        original_rows = self.client.rows
        raised = [False]

        def flaky_rows(table, key, timeout):
            if self.clock.now == 2 and not raised[0]:
                raised[0] = True
                raise runner.ApiError("temporary", 503, True)
            return original_rows(table, key, timeout)

        self.client.rows = flaky_rows
        result = self.case()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["elapsed_seconds"], 6)

    def test_extra_persisted_incident_fails_even_if_response_claims_one(self):
        self.client.extra_incident = True
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("more than one incident", result["reason"])

    def test_post_transport_error_never_retries(self):
        self.client.push_error = runner.ApiError("timeout after submission", retryable=True)
        result = self.case()
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.client.pushes), 1)

    def test_transient_reads_are_retried_inside_deadline(self):
        self.client.transient_errors = 2
        result = self.case()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["phases"][0]["transient_read_errors"], 2)
        self.assertEqual(result["elapsed_seconds"], 5)

    def test_auth_denial_stops_entire_suite_without_another_post(self):
        self.client.read_error = runner.ApiError("access denied", 403)
        result = self.runner.run()
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.client.pushes), 1)
        self.assertTrue(all(row["status"] == "skipped" for row in result["cases"][1:]))

    def test_fixture_control_failure_blocks_precedence_claims(self):
        self.client.ci_ready_at = 100
        result = self.runner.run()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(len(self.client.pushes), 1)
        self.assertTrue(all(row["status"] == "skipped" for row in result["cases"][1:]))

    def test_default_matrix_is_fast_only_with_both_aliases_and_no_stress(self):
        result = self.runner.run()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["cases"]), 5)
        self.assertEqual(len(self.client.pushes), 7)
        self.assertEqual(result["elapsed_seconds"], 21)
        self.assertFalse(result["concurrency_included"])
        self.assertIn("does not assert concurrent safety", result["accepted_residual_limitation"])
        self.assertTrue(any(payload.get("direct_to_incident") and "ci_identifier" in payload
                            for payload in self.client.pushes))
        self.assertTrue(all("dti_wait_for_incident" not in payload and "dtiWaitForIncident" not in payload
                            for payload in self.client.pushes))
        self.assertTrue(all(phase["actual_incident_fields"] == case["expected_incident_fields"]
                            for case in result["cases"] for phase in case["phases"]))

    def test_optional_stress_adds_sixth_case_and_three_concurrent_submissions(self):
        self.settings.include_concurrency = True
        result = self.runner.run()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["cases"]), 6)
        self.assertEqual(len(self.client.pushes), 10)
        self.assertEqual(result["elapsed_seconds"], 24)
        self.assertTrue(result["concurrency_included"])
        self.assertEqual(result["cases"][-1]["name"], "concurrent_fast_duplicates")
        self.assertEqual(result["cases"][-1]["phases"][0]["actual_event_count"], 3)

    def test_optional_stress_divergent_incidents_still_fail_suite(self):
        self.settings.include_concurrency = True
        original_push = self.client.push

        def divergent_only_in_stress(source, payload, timeout):
            self.client.different_concurrent = payload["message_key"].endswith("-6")
            return original_push(source, payload, timeout)

        self.client.push = divergent_only_in_stress
        result = self.runner.run()
        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["concurrency_included"])
        self.assertIn("different incidents", result["cases"][-1]["reason"])

    def test_required_incident_fields_must_be_nonempty_and_match(self):
        original_rows = self.client.rows

        def missing_caller(table, key, timeout):
            rows = original_rows(table, key, timeout)
            if table == "incident":
                rows[0]["caller_id"] = ""
            return rows

        self.client.rows = missing_caller
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("caller_id", result["reason"])

    def test_missing_incident_field_acl_is_reported_as_access_error(self):
        original_rows = self.client.rows

        def missing_description(table, key, timeout):
            rows = original_rows(table, key, timeout)
            if table == "incident":
                del rows[0]["description"]
            return rows

        self.client.rows = missing_description
        result = self.case()
        self.assertEqual(result["status"], "error")
        self.assertIn("field read ACLs", result["reason"])

    def test_assignment_group_is_verified(self):
        self.settings.expected_assignment_group_id = "9" * 32
        result = self.case()
        self.assertEqual(result["status"], "fail")
        self.assertIn("assignment group", result["reason"])

    def test_malformed_or_failed_response_cannot_pass(self):
        mutations = [lambda row: row.update(status="error"), lambda row: row.update(results=[]),
                     lambda row: row["results"][0].update(status="error"),
                     lambda row: row.update(results=[None]), lambda row: row.update(sys_ids=[]),
                     lambda row: row["versions"].update(lookups="old"),
                     lambda row: row.update(incident_sys_id="9" * 32)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp()
                self.client.mutate_response = mutate
                self.assertEqual(self.case()["status"], "fail")


class TransportConfigTests(unittest.TestCase):
    def test_connector_routing_header_and_single_post(self):
        client = runner.Client("https://example.service-now.com", {"mode": "basic", "username": "fixture", "password": "test"})
        with patch.object(client, "send", return_value={}) as send:
            client.push("genericJsonV2", {"message_key": "KEY"}, 4)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[3]["User-Agent"], "genericendpoint")
        self.assertTrue(send.call_args.args[3]["Authorization"].startswith("Basic "))

    def test_oauth_client_credentials_uses_form_and_bearer_without_retry(self):
        client = runner.Client("https://example.service-now.com", {"mode": "oauth", "client_id": "fixture",
                                                                       "client_secret": "test", "scope": "fixture"})
        with patch.object(client, "send", side_effect=[{"access_token": "fake", "expires_in": 3600}, {}]) as send:
            client.push("genericJsonV2", {}, 4)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[1], "/oauth_token.do")
        self.assertIn(b"grant_type=client_credentials", send.call_args_list[0].args[2])
        self.assertEqual(send.call_args_list[1].args[3]["Authorization"], "Bearer fake")

    def test_http_error_body_is_never_returned(self):
        client = runner.Client("https://example.service-now.com", {"mode": "basic", "username": "fixture", "password": "test"})
        error = urllib.error.HTTPError("https://example.service-now.com/api", 403, "denied", {}, io.BytesIO(b"DO_NOT_LOG_BODY"))
        with patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(runner.ApiError) as raised:
                client.push("genericJsonV2", {}, 4)
        self.assertNotIn("DO_NOT_LOG_BODY", str(raised.exception))
        self.assertEqual(raised.exception.status, 403)

    def test_https_origin_and_redirect_rules(self):
        self.assertEqual(runner.validate_instance("https://example.service-now.com/"), "https://example.service-now.com")
        for value in ("http://example.com", "https://user:pass@example.com", "https://example.com/path",
                      "https://example.com?x=1", "https://example.com#x", "example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.validate_instance(value)
        self.assertIsNone(runner.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.com"))

    def args(self, **overrides):
        values = {"profile": "", "instance": "", "user": "", "password": "", "source": "",
                  "expect_version": "", "timeout": None, "stable_seconds": None,
                  "poll_seconds": None, "request_timeout": None, "fast_post_max_seconds": None,
                  "include_concurrency": False}
        values.update(overrides)
        return argparse.Namespace(**values)

    def config(self):
        return {"SN_INSTANCE_URL": "https://example.service-now.com", "SN_USERNAME_B64": base64.b64encode(b"fixture").decode(),
                "SN_PASSWORD_B64": base64.b64encode(b" test ").decode(), "USBEM_CI_TYPE": "cmdb_ci_server",
                "USBEM_CI_IDENTIFIER_JSON": '{"serial_number":"test"}', "USBEM_DECOY_CI_NAME": "decoy",
                "USBEM_EXPECTED_CI_SYS_ID": EXPECTED, "USBEM_DECOY_CI_SYS_ID": DECOY,
                "USBEM_TEST_CALLER_SYS_ID": "f" * 32}

    def test_base64_and_existing_production_oauth_profile_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            values = self.config()
            _, auth, _ = runner.configuration(self.args(), values)
            self.assertEqual(auth["password"], " test ")
            values.update(USBEM_ITSMNOWDEVWORKER_URL="https://dev.service-now.com",
                          USBEM_ITSMNOWDEVWORKER_OAUTH_CLIENT_ID="fixture",
                          USBEM_ITSMNOWDEVWORKER_OAUTH_CLIENT_SECRET="test")
            instance, auth, _ = runner.configuration(self.args(profile="itsmnowDEVworker"), values)
            self.assertEqual(instance, "https://dev.service-now.com")
            self.assertEqual(auth["mode"], "oauth")

    def test_concurrency_opt_in_can_be_selected_by_flag_or_env(self):
        with patch.dict(os.environ, {}, clear=True):
            _, _, settings = runner.configuration(self.args(), self.config())
            self.assertFalse(settings.include_concurrency)
            _, _, settings = runner.configuration(self.args(include_concurrency=True), self.config())
            self.assertTrue(settings.include_concurrency)
            _, _, settings = runner.configuration(self.args(), dict(self.config(), USBEM_TEST_INCLUDE_CONCURRENCY="true"))
            self.assertTrue(settings.include_concurrency)

    def test_unsafe_or_ambiguous_fixture_configurations_rejected(self):
        changes = [{"USBEM_DECOY_CI_SYS_ID": EXPECTED}, {"USBEM_CI_IDENTIFIER_JSON": '{"serial_number":{}}'},
                   {"USBEM_CI_IDENTIFIER_JSON": '{"serial_number":"x^ORname=y"}'},
                   {"USBEM_CI_IDENTIFIER_JSON": '{"serial_number":true}'},
                   {"USBEM_CI_IDENTIFIER_JSON": '{"serial_number":"javascript:1"}'},
                   {"USBEM_ASSIGNMENT_GROUP": "named group"}]
        with patch.dict(os.environ, {}, clear=True):
            for change in changes:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    runner.configuration(self.args(), dict(self.config(), **change))


if __name__ == "__main__":
    unittest.main()
