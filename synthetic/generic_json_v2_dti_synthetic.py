#!/usr/bin/env python3
"""End-to-end synthetic for Generic JSON V2 Direct To Incident."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import socket
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def decoded_env(encoded_name: str, plain_name: str) -> str:
    encoded = env(encoded_name)
    if encoded:
        return base64.b64decode(encoded).decode("utf-8")
    return env(plain_name)


class ServiceNow:
    def __init__(self, instance: str, username: str, password: str, timeout: int) -> None:
        self.instance = instance.rstrip("/")
        self.timeout = timeout
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "Basic " + token,
            "User-Agent": "generic-json-v2-dti-synthetic/1.0",
        }

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.instance + path, data=data, method=method, headers=self.headers
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode()
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"HTTP {response.status}")
            return json.loads(body) if body else {}

    def table(self, table: str, query: str, fields: str) -> list[dict]:
        params = urllib.parse.urlencode(
            {
                "sysparm_query": query,
                "sysparm_fields": fields,
                "sysparm_limit": "100",
                "sysparm_display_value": "false",
            }
        )
        return self.request("GET", f"/api/now/table/{table}?{params}").get("result", [])

    def delete(self, table: str, sys_id: str) -> None:
        self.request("DELETE", f"/api/now/table/{table}/{sys_id}")


def first_result(body: dict) -> dict:
    result = body.get("result", body)
    if isinstance(result, dict) and len(result) == 1:
        only_value = next(iter(result.values()))
        if isinstance(only_value, str):
            try:
                result = json.loads(only_value)
            except json.JSONDecodeError:
                pass
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        return result["results"][0] if result["results"] else {}
    if isinstance(result, list):
        return result[0] if result else {}
    return result if isinstance(result, dict) else {}


def require_config() -> tuple[str, str, str]:
    instance = env("SN_INSTANCE_URL") or env("SERVICENOW_INSTANCE")
    username = decoded_env("SN_USERNAME_B64", "SN_USERNAME") or env("SERVICENOW_USER")
    password = decoded_env("SN_PASSWORD_B64", "SN_PASSWORD") or env("SERVICENOW_PASSWORD")
    missing = [name for name, value in (("SN_INSTANCE_URL", instance), ("SN_USERNAME", username), ("SN_PASSWORD", password)) if not value]
    if missing:
        raise RuntimeError("missing required environment: " + ", ".join(missing))
    return instance, username, password


def event_payload(message_key: str, run_id: str, severity: str, direct: bool) -> dict:
    environment_name = env("DTI_ENVIRONMENT_NAME", "unspecified")
    payload = {
        "source": env("DTI_EVENT_SOURCE", "Generic JSON V2 DTI Synthetic"),
        "event_class": "Synthetic Test",
        "node": env("DTI_NODE", socket.gethostname()),
        "resource": "generic-json-v2-dti",
        "metric_name": "generic_json_v2.dti.synthetic",
        "type": "Synthetic Test",
        "message_key": message_key,
        "severity": severity,
        "description": f"Generic JSON V2 DTI synthetic for {environment_name} ({run_id})",
        "direct_to_incident": direct,
    }
    assignment_group = env("DTI_ASSIGNMENT_GROUP")
    if assignment_group:
        payload["assignment_group"] = assignment_group
    return payload


def send_failure_email(run_id: str, message_key: str, detail: str) -> None:
    host = env("DTI_SMTP_HOST")
    recipient = env("DTI_FAILURE_EMAIL_TO")
    sender = env("DTI_FAILURE_EMAIL_FROM", "generic-json-v2-synthetic@localhost")
    if not host or not recipient:
        raise RuntimeError("DTI_SMTP_HOST and DTI_FAILURE_EMAIL_TO are required for failure email")
    port = int(env("DTI_SMTP_PORT", "25"))
    subject = f"FAIL: Generic JSON V2 DTI synthetic {env('DTI_ENVIRONMENT_NAME', 'unspecified')} {run_id}"
    safe_detail = detail.replace("\r", " ").replace("\n", " ")
    message = (
        f"From: {sender}\r\nTo: {recipient}\r\nSubject: {subject}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"The Generic JSON V2 DTI synthetic failed.\nRun ID: {run_id}\n"
        f"Message key: {message_key}\nDetail: {safe_detail}\n"
    )
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if env("DTI_SMTP_STARTTLS", "false").lower() in ("1", "true", "yes"):
            smtp.starttls()
        smtp_user = env("DTI_SMTP_USERNAME")
        if smtp_user:
            smtp.login(smtp_user, env("DTI_SMTP_PASSWORD"))
        smtp.sendmail(sender, [recipient], message.encode("utf-8"))


def post_connector(client: ServiceNow, endpoint: str, payload: dict) -> dict:
    return first_result(client.request("POST", endpoint, payload))


def run() -> dict:
    instance, username, password = require_config()
    timeout = int(env("DTI_HTTP_TIMEOUT_SECONDS", "60"))
    poll_seconds = int(env("DTI_POLL_SECONDS", "45"))
    connector_source = env("DTI_CONNECTOR_SOURCE", "genericJsonV2")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    message_key = env("DTI_MESSAGE_KEY_PREFIX", "synthetic-generic-json-v2-dti") + "-" + run_id
    client = ServiceNow(instance, username, password, timeout)
    endpoint = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": connector_source})
    payload = event_payload(message_key, run_id, env("DTI_TEST_SEVERITY", "4"), True)
    payload["dti_short_description"] = f"[SYNTHETIC TEST] Generic JSON V2 DTI {run_id}"
    payload["dti_work_note"] = "Temporary validation incident created by the Generic JSON V2 DTI Linux synthetic."

    responses = []
    for duplicate_number in (1, 2):
        request_payload = dict(payload)
        request_payload["synthetic_duplicate_number"] = duplicate_number
        responses.append(post_connector(client, endpoint, request_payload))

    deadline = time.monotonic() + poll_seconds
    events: list[dict] = []
    incidents: list[dict] = []
    while True:
        events = client.table("em_event", "message_key=" + message_key, "sys_id,message_key,alert,source")
        incidents = client.table(
            "incident", "correlation_id=" + message_key, "sys_id,number,correlation_id,correlation_display,active"
        )
        if len(events) >= 2 and len(incidents) == 1:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(2)

    response_incidents = {str(item.get("incident_sys_id", "")) for item in responses} - {""}
    live_incident_ids = {str(item.get("sys_id", "")) for item in incidents} - {""}
    checks = {
        "both_posts_returned_events": len(responses) == 2 and all(item.get("event_sys_id") for item in responses),
        "two_events_are_queryable": len(events) >= 2,
        "exactly_one_correlated_incident": len(incidents) == 1,
        "responses_reused_one_incident": len(response_incidents) == 1,
        "response_matches_live_incident": response_incidents == live_incident_ids,
    }
    if all(checks.values()):
        client.delete("incident", next(iter(live_incident_ids)))
        cleanup_rows = client.table("incident", "correlation_id=" + message_key, "sys_id")
        checks["temporary_incident_removed"] = len(cleanup_rows) == 0
    if all(checks.values()):
        ok_key = env("DTI_OK_MESSAGE_KEY_PREFIX", "synthetic-generic-json-v2-ok") + "-" + run_id
        ok_payload = event_payload(ok_key, run_id, "5", False)
        ok_payload["description"] = f"Generic JSON V2 DTI synthetic succeeded ({run_id})"
        ok_response = post_connector(client, endpoint, ok_payload)
        checks["ok_event_created"] = bool(ok_response.get("event_sys_id"))
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "run_id": run_id,
        "message_key": message_key,
        "checks": checks,
        "event_count": len(events),
        "incident_count": len(incidents),
        "event_sys_ids": sorted(str(row.get("sys_id", "")) for row in events),
        "incident_number": incidents[0].get("number", "") if len(incidents) == 1 else "",
        "incident_sys_id": incidents[0].get("sys_id", "") if len(incidents) == 1 else "",
    }


def report_failure(error_detail: str) -> dict:
    instance, username, password = require_config()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    message_key = env("DTI_FAILURE_MESSAGE_KEY_PREFIX", "synthetic-generic-json-v2-failure") + "-" + run_id
    client = ServiceNow(instance, username, password, int(env("DTI_HTTP_TIMEOUT_SECONDS", "60")))
    connector_source = env("DTI_CONNECTOR_SOURCE", "genericJsonV2")
    endpoint = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": connector_source})
    payload = event_payload(message_key, run_id, env("DTI_FAILURE_SEVERITY", "2"), True)
    payload["dti_short_description"] = f"Generic JSON V2 DTI synthetic failed on {socket.gethostname()}"
    payload["dti_work_note"] = "Synthetic failure detail: " + error_detail[:2000]
    incident_response = post_connector(client, endpoint, payload)
    send_failure_email(run_id, message_key, error_detail)
    return {"failure_message_key": message_key, "failure_incident_number": incident_response.get("incident_number", "")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()
    try:
        result = run()
        if result["status"] != "pass":
            try:
                result.update(report_failure(json.dumps(result["checks"], sort_keys=True)))
            except Exception as report_error:
                result["failure_reporting_error"] = str(report_error)
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
        return 0 if result["status"] == "pass" else 2
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
        failure = {"status": "error", "error": str(error)}
        try:
            failure.update(report_failure(str(error)))
        except Exception as report_error:
            failure["failure_reporting_error"] = str(report_error)
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
