#!/usr/bin/env python3
"""Production-safe regression check for Generic JSON V2 CI identifier precedence.

The test intentionally sends a valid but incorrect CI display name together with the expected
CI type and identifier. It passes only when the created DTI incident references the identifier-
selected CI. Records are retained as tagged operational evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def first(values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "") or values.get(key, "")
        if value:
            return value.strip()
    return ""


def decode_b64(value: str, label: str) -> str:
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except Exception as error:
        raise ValueError(f"{label} is not valid base64 UTF-8") from error


class Client:
    def __init__(self, base: str, username: str, password: str, insecure: bool) -> None:
        self.base = base.rstrip("/")
        self.context = ssl.create_default_context()
        if insecure:
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {
            "Authorization": "Basic " + token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "usbem-ci-identifier-precedence-test/1.0",
        }

    def request(self, method: str, path: str, body: dict | None = None) -> object:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=120, context=self.context) as response:
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {detail[:300]}") from None
        parsed = json.loads(text) if text else {}
        return parsed.get("result", parsed) if isinstance(parsed, dict) else parsed

    def push(self, source: str, payload: dict) -> dict:
        path = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": source})
        result = self.request("POST", path, payload)
        if isinstance(result, dict) and len(result) == 1 and "status" not in result:
            result = next(iter(result.values()))
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            raise RuntimeError("connector returned an unexpected response")
        return result

    def incident(self, sys_id: str) -> dict:
        params = urllib.parse.urlencode({
            "sysparm_fields": "sys_id,number,cmdb_ci,correlation_id,short_description",
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
        })
        result = self.request("GET", f"/api/now/table/incident/{sys_id}?{params}")
        return result if isinstance(result, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=str(Path(__file__).with_name("ci_identifier_test.env")))
    parser.add_argument("--instance", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--insecure", action="store_true", help="disable TLS verification (last resort)")
    args = parser.parse_args()

    values = read_env(Path(args.env_file).expanduser())
    instance = args.instance or first(values, "SN_INSTANCE_URL")
    username = args.user or first(values, "SN_USERNAME")
    password = args.password or first(values, "SN_PASSWORD")
    if not username and first(values, "SN_USERNAME_B64"):
        username = decode_b64(first(values, "SN_USERNAME_B64"), "SN_USERNAME_B64")
    if not password and first(values, "SN_PASSWORD_B64"):
        password = decode_b64(first(values, "SN_PASSWORD_B64"), "SN_PASSWORD_B64")
    source = args.source or first(values, "USBEM_SOURCE") or "genericJsonV2"
    ci_type = first(values, "USBEM_CI_TYPE")
    identifier_text = first(values, "USBEM_CI_IDENTIFIER_JSON")
    decoy_name = first(values, "USBEM_DECOY_CI_NAME")
    expected_sys_id = first(values, "USBEM_EXPECTED_CI_SYS_ID").lower()
    assignment_group = first(values, "USBEM_ASSIGNMENT_GROUP")
    missing = [label for label, value in (
        ("SN_INSTANCE_URL", instance), ("username", username), ("password", password),
        ("USBEM_CI_TYPE", ci_type), ("USBEM_CI_IDENTIFIER_JSON", identifier_text),
        ("USBEM_DECOY_CI_NAME", decoy_name), ("USBEM_EXPECTED_CI_SYS_ID", expected_sys_id),
    ) if not value]
    if missing:
        parser.error("missing configuration: " + ", ".join(missing))
    try:
        identifier = json.loads(identifier_text)
    except ValueError as error:
        parser.error(f"USBEM_CI_IDENTIFIER_JSON must be valid JSON: {error}")
    if not isinstance(identifier, dict) or not identifier:
        parser.error("USBEM_CI_IDENTIFIER_JSON must be a non-empty JSON object")

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    message_key = "USBEM-CI-ID-PRECEDENCE-" + run_id
    payload = {
        "source": "USBEM CI Identifier Regression Test",
        "event_class": "Synthetic Test",
        "node": "usbem-ci-identifier-test",
        "resource": "ci-identifier-precedence",
        "metric_name": "usbem.ci_identifier.precedence",
        "message_key": message_key,
        "severity": "4",
        "description": "CI identifier precedence regression test " + run_id,
        "cmdb_ci": decoy_name,
        "ciType": ci_type,
        "ciIdentifier": identifier,
        "directToIncident": True,
        "dtiWaitForIncident": True,
        "usbemWaitSeconds": 60,
        "dtiShortDescription": "[SYNTHETIC] USBEM CI identifier precedence " + run_id,
        "dtiWorkNote": "Retained test evidence. Expected identifier-selected CI: " + expected_sys_id,
    }
    if assignment_group:
        payload["assignmentGroup"] = assignment_group

    client = Client(instance, username, password, args.insecure)
    response = client.push(source, payload)
    result = response.get("results", [response])[0] if isinstance(response.get("results"), list) else response
    incident_sys_id = str(result.get("incident_sys_id") or response.get("incident_sys_id") or "")
    if not incident_sys_id:
        print(json.dumps({"status": "fail", "reason": "connector returned no incident", "message_key": message_key}, sort_keys=True))
        return 2
    incident = client.incident(incident_sys_id)
    actual = str(incident.get("cmdb_ci") or "").lower()
    passed = actual == expected_sys_id
    output = {
        "status": "pass" if passed else "fail",
        "message_key": message_key,
        "incident_number": incident.get("number", ""),
        "incident_sys_id": incident_sys_id,
        "expected_cmdb_ci": expected_sys_id,
        "actual_cmdb_ci": actual,
        "ci_type": ci_type,
        "identifier_keys": sorted(identifier),
        "decoy_name_was_ignored": passed,
        "records_retained": True,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        raise SystemExit(3)
