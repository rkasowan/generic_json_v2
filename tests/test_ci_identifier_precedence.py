#!/usr/bin/env python3
"""Observe CI precedence and duplicate DTI behavior through the real inbound-event API.

Requires connector POST plus incident/em_event read access. The default five fast-DTI cases
create seven tagged events and expect five incidents; all evidence is retained. A complete
default run takes at least 3.5 minutes: seven phases remain correct for 30 seconds each.
Control failures stop earlier. All payloads omit wait-for-incident keys. --include-concurrency
adds a three-request first-event stress case (ten total events, six expected incidents).
Simultaneous first events can create duplicate incidents; this accepted limitation is reported
even when the default suite passes. No POST is retried. This bounded suite does not prove
concurrent safety, email delivery, or every production rule and incident lifecycle transition.
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import http.client
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

EXPECTED_RELEASE = "2026.10.29.1"
SYS_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
IDENTIFIER_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError("environment file does not exist; copy the supplied template first")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def decode_b64(value: str, label: str) -> str:
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        raise ValueError(label + " must be valid base64 UTF-8") from None


def validate_instance(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port
    except ValueError:
        raise ValueError("instance URL has an invalid host or port") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or
            parsed.password is not None or parsed.path not in ("", "/") or
            parsed.query or parsed.fragment or "\\" in value or any(char.isspace() for char in value)):
        raise ValueError("instance must be an HTTPS origin without credentials, path, query or fragment")
    return value.rstrip("/")


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # Prevent auth headers being forwarded to another origin, or POST being replayed.
        return None


class Client:
    """One-shot HTTP requests; only the observer retries safe reads, within its deadline."""
    def __init__(self, base: str, auth: dict, ca_bundle: str = "", insecure: bool = False) -> None:
        self.base = validate_instance(base)
        self.auth = auth
        context = ssl.create_default_context(cafile=ca_bundle or None)
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
        self.token = ""
        self.token_expiry = 0.0
        self.token_lock = threading.Lock()

    def send(self, method: str, path: str, data, headers: dict, timeout: float):
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        label = method + " " + path.split("?", 1)[0]
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            # Do not expose response bodies: an upstream proxy can echo authorization data.
            code = error.code
            error.close()
            raise ApiError(label + " returned HTTP " + str(code), code,
                           code in (408, 429) or 500 <= code <= 599) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise ApiError(label + " transport/TLS failure or timeout", retryable=True) from None
        if len(raw) > 4 * 1024 * 1024:
            raise ApiError(label + " response exceeded the 4 MiB limit")
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ApiError(label + " did not return valid JSON") from None

    def authorization(self, timeout: float) -> str:
        if self.auth["mode"] == "basic":
            token = base64.b64encode((self.auth["username"] + ":" + self.auth["password"]).encode()).decode()
            return "Basic " + token
        started = time.monotonic()
        if not self.token_lock.acquire(timeout=timeout):
            raise ApiError("authentication deadline expired", retryable=True)
        try:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ApiError("authentication deadline expired", retryable=True)
            return self.oauth_authorization(remaining)
        finally:
            self.token_lock.release()

    def oauth_authorization(self, timeout: float) -> str:
        if not self.token or time.monotonic() >= self.token_expiry:
            form = {"grant_type": "client_credentials", "client_id": self.auth["client_id"],
                    "client_secret": self.auth["client_secret"]}
            if self.auth.get("scope"):
                form["scope"] = self.auth["scope"]
            started = time.monotonic()
            result = self.send("POST", "/oauth_token.do", urllib.parse.urlencode(form).encode(),
                               {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                               timeout)
            if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"]:
                raise ApiError("OAuth token response did not contain an access token")
            try:
                expires = float(result.get("expires_in", 1800))
                if not math.isfinite(expires) or expires <= 0:
                    raise ValueError()
                expires = max(1.0, expires - 30.0)
            except (TypeError, ValueError):
                raise ApiError("OAuth token response contained an invalid expiry") from None
            self.token, self.token_expiry = result["access_token"], started + expires
        return "Bearer " + self.token

    def request(self, method: str, path: str, body=None, timeout: float = 90.0):
        started = time.monotonic()
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "User-Agent": "genericendpoint", "Authorization": self.authorization(timeout)}
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ApiError("request deadline expired during authentication", retryable=True)
        result = self.send(method, path, None if body is None else json.dumps(body).encode(), headers, remaining)
        return result.get("result", result) if isinstance(result, dict) else result

    def push(self, source: str, payload: dict, timeout: float):
        result = self.request("POST", "/api/sn_em_connector/em/inbound_event?" +
                              urllib.parse.urlencode({"source": source}), payload, timeout)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                raise ApiError("connector returned invalid JSON") from None
        if isinstance(result, dict) and len(result) == 1 and "status" not in result:
            result = next(iter(result.values()))
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    raise ApiError("connector listener returned invalid JSON") from None
        return result

    def rows(self, table: str, key: str, timeout: float) -> list[dict]:
        field = "correlation_id" if table == "incident" else "message_key"
        fields = ("sys_id,number,cmdb_ci,correlation_id,short_description,description,assignment_group,caller_id,category,subcategory,impact,urgency" if table == "incident"
                  else "sys_id,message_key,source")
        params = {"sysparm_query": field + "=" + key, "sysparm_fields": fields,
                  "sysparm_limit": "10", "sysparm_display_value": "false",
                  "sysparm_exclude_reference_link": "true"}
        result = self.request("GET", "/api/now/table/" + table + "?" + urllib.parse.urlencode(params), timeout=timeout)
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ApiError(table + " read returned an unexpected result shape")
        return result


@dataclass
class Settings:
    source: str
    ci_type: str
    identifier: dict
    decoy_name: str
    expected_id: str
    decoy_id: str
    caller_id: str = ""
    category: str = "software"
    expected_category: str = "software"
    subcategory: str = "os"
    expected_subcategory: str = "os"
    impact: str = "2"
    urgency: str = "2"
    assignment_group: str = ""
    expected_assignment_group_id: str = ""
    expected_release: str = EXPECTED_RELEASE
    timeout: float = 120.0
    fast_post_max_seconds: float = 10.0
    stable_seconds: float = 30.0
    poll_seconds: float = 3.0
    request_timeout: float = 90.0
    include_concurrency: bool = False


class CheckFailed(RuntimeError):
    pass


def check_response(response, key: str, mode: str, release: str) -> tuple[str, str, dict]:
    if not isinstance(response, dict) or response.get("status") != "success":
        raise CheckFailed("connector did not report success")
    versions = response.get("versions")
    required = ("listener", "core", "lookups", "debug", "dti")
    if (response.get("version") != release or not isinstance(versions, dict) or
            any(versions.get(component) != release for component in required)):
        raise CheckFailed("connector component versions do not all match expected release " + release)
    results = response.get("results")
    if (str(response.get("inserted")) != "1" or not isinstance(results, list) or
            len(results) != 1 or not isinstance(results[0], dict)):
        raise CheckFailed("connector must report exactly one inserted event and one result")
    row = results[0]
    if row.get("status") != "success":
        raise CheckFailed("connector per-event result did not report success")
    event_id = str(row.get("event_sys_id") or "").lower()
    incident_id = str(row.get("incident_sys_id") or "").lower()
    if not SYS_ID.fullmatch(event_id) or response.get("sys_ids") != [event_id]:
        raise CheckFailed("connector event sys_id is missing, invalid or inconsistent")
    if row.get("message_key") != key or row.get("dti_mode") != mode:
        raise CheckFailed("connector returned a different message key or DTI mode")
    if not SYS_ID.fullmatch(incident_id):
        raise CheckFailed("fast DTI must promptly return a valid incident sys_id")
    for name, expected in (("event_sys_id", event_id), ("incident_sys_id", incident_id),
                           ("message_key", key), ("dti_mode", mode)):
        if name in response and str(response[name] or "").lower() != str(expected).lower():
            raise CheckFailed("connector top-level and per-event " + name + " disagree")
    if row.get("dti_incident_status") in ("create_failed", "suppressed_by_severity_map"):
        raise CheckFailed("connector reported DTI failure: " + row["dti_incident_status"])
    return event_id, incident_id, {name: versions[name] for name in required}


class Runner:
    def __init__(self, client, settings: Settings, monotonic=time.monotonic, sleep=time.sleep) -> None:
        self.client, self.settings = client, settings
        self.clock, self.sleep = monotonic, sleep

    def budget(self, deadline: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise CheckFailed("observation deadline expired")
        return min(self.settings.request_timeout, remaining)

    def observe(self, key: str, expected_ci: str, event_ids: list[str], incident_id: str,
                deadline: float, phase: dict, expected_fields: dict) -> dict:
        stable_since = None
        # A duplicate follows a completed stable observation of this same incident.
        saw_expected = phase.get("name") == "duplicate"
        saw_expected_fields = phase.get("name") == "duplicate"
        last_reason = "records not yet visible"
        phase.update(polls=0, transient_read_errors=0, expected_event_count=len(event_ids))
        while self.clock() < deadline:
            phase["polls"] += 1
            try:
                incidents = self.client.rows("incident", key, self.budget(deadline))
                events = self.client.rows("em_event", key, self.budget(deadline))
            except ApiError as error:
                if not error.retryable or error.status in (401, 403):
                    raise
                phase["transient_read_errors"] += 1
                stable_since = None
                last_reason = "transient read errors prevented a complete observation"
                self.sleep(min(self.settings.poll_seconds, max(0.0, deadline - self.clock())))
                continue
            if self.clock() >= deadline:
                raise CheckFailed("observation deadline expired during readback")
            if len(incidents) > 1:
                raise CheckFailed("more than one incident exists for the exact message key")
            if len(events) > len(event_ids):
                raise CheckFailed("more event rows exist than the deliberate submissions")
            if incidents:
                incident = incidents[0]
                required = ["sys_id", "cmdb_ci", "correlation_id"] + list(expected_fields)
                if self.settings.expected_assignment_group_id:
                    required.append("assignment_group")
                if any(field not in incident for field in required):
                    raise ApiError("Incident read omitted required fields; check field read ACLs")
                current_id = str(incident["sys_id"]).lower()
                if not SYS_ID.fullmatch(current_id) or incident["correlation_id"] != key:
                    raise CheckFailed("Incident read did not match the exact correlation key")
                if incident_id and current_id != incident_id:
                    raise CheckFailed("persisted incident differs from the returned or previously observed incident")
                if not incident_id:
                    incident_id = current_id
                actual = str(incident["cmdb_ci"] or "").lower()
                phase["last_cmdb_ci"] = actual
                if saw_expected and actual != expected_ci:
                    raise CheckFailed("incident CI drifted after the expected CI was observed")
                saw_expected = saw_expected or actual == expected_ci
                actual_group = str(incident.get("assignment_group") or "").lower()
                group_ready = not self.settings.expected_assignment_group_id or actual_group == self.settings.expected_assignment_group_id
                actual_fields = {field: str(incident.get(field) or "") for field in expected_fields}
                wrong_fields = [field for field, expected in expected_fields.items()
                                if not actual_fields[field] or actual_fields[field] != expected]
                fields_ready = not wrong_fields
                if saw_expected_fields and wrong_fields:
                    raise CheckFailed("incident fields drifted after expected values were observed: " + ", ".join(wrong_fields))
                saw_expected_fields = saw_expected_fields or fields_ready
                phase["actual_incident_fields"] = actual_fields
                if self.settings.expected_assignment_group_id:
                    phase["actual_assignment_group"] = actual_group
            else:
                actual, group_ready, fields_ready, wrong_fields = "", False, False, []
            if any("sys_id" not in event or "message_key" not in event for event in events):
                raise ApiError("Event read omitted required fields; check field read ACLs")
            if any(event["message_key"] != key for event in events):
                raise CheckFailed("Event read did not match the exact message key")
            actual_event_ids = [str(event["sys_id"]).lower() for event in events]
            if len(set(actual_event_ids)) != len(actual_event_ids) or any(value not in event_ids for value in actual_event_ids):
                raise CheckFailed("persisted event sys_ids differ from connector responses")
            ready = bool(incidents) and actual == expected_ci and group_ready and fields_ready and set(actual_event_ids) == set(event_ids)
            if ready:
                if stable_since is None:
                    stable_since = self.clock()
                phase["stable_observed_seconds"] = round(self.clock() - stable_since, 3)
                if self.clock() - stable_since >= self.settings.stable_seconds:
                    phase.update(incident_sys_id=incident_id, incident_number=incidents[0].get("number", ""),
                                 actual_event_count=len(events), actual_incident_count=len(incidents))
                    return incidents[0]
            else:
                stable_since = None
                last_reason = ("incident is not visible" if not incidents else
                               "incident CI has not reached the expected sys_id" if actual != expected_ci else
                               "assignment group does not match" if not group_ready else
                               "incident fields do not match: " + ", ".join(wrong_fields) if not fields_ready else
                               "event rows are not all visible")
            self.sleep(min(self.settings.poll_seconds, max(0.0, deadline - self.clock())))
        raise CheckFailed("observation timed out: " + last_reason)

    def run_case(self, name: str, lookup: dict, expected_ci: str, snake: bool,
                 duplicate: bool, key: str, submissions: int = 1) -> dict:
        started = self.clock()
        result = {"name": name, "message_key": key, "status": "running", "expected_cmdb_ci": expected_ci,
                  "phases": [], "records_retained": True}
        mode = "fast_async"
        short_description = ("[SYNTHETIC] USBEM CI precedence " + name + " " + key)[:160]
        description = "CI precedence test " + key
        expected_fields = {"caller_id": self.settings.caller_id, "category": self.settings.expected_category,
                           "subcategory": self.settings.expected_subcategory, "impact": self.settings.impact,
                           "urgency": self.settings.urgency, "short_description": short_description,
                           "description": description}
        result["expected_incident_fields"] = expected_fields
        payload = {"source": "USBEM CI Identifier Regression Test", "event_class": "Synthetic Test",
                   "node": "usbem-ci-identifier-test", "resource": "ci-identifier-precedence",
                   "metric_name": "usbem.ci_identifier.precedence", "message_key": key,
                   "severity": "4", "description": description, "caller_id": self.settings.caller_id,
                   "category": self.settings.category, "subcategory": self.settings.subcategory}
        if snake:
            payload.update(direct_to_incident=True, dti_impact=self.settings.impact, dti_urgency=self.settings.urgency,
                           dti_short_description=short_description,
                           dti_work_note="Retained CI precedence and duplicate test evidence.")
        else:
            payload.update(directToIncident=True, dtiImpact=self.settings.impact, dtiUrgency=self.settings.urgency,
                           dtiShortDescription=short_description,
                           dtiWorkNote="Retained CI precedence and duplicate test evidence.")
        payload.update(lookup)
        if self.settings.assignment_group:
            payload["assignmentGroup"] = self.settings.assignment_group
        event_ids, incident_id = [], ""
        try:
            for phase_name in (("initial", "duplicate") if duplicate else ("initial",)):
                phase_start = self.clock()
                deadline = phase_start + self.settings.timeout
                phase = {"name": phase_name}
                result["phases"].append(phase)
                # One attempt only: a transport timeout may occur after the event was accepted.
                phase["submissions_attempted"] = submissions
                submission_errors = []
                if submissions > 1:
                    with ThreadPoolExecutor(max_workers=submissions) as pool:
                        futures = [pool.submit(self.client.push, self.settings.source, payload,
                                               min(self.settings.fast_post_max_seconds, self.budget(deadline)))
                                   for _ in range(submissions)]
                        responses = []
                        for future in futures:
                            try:
                                responses.append(future.result())
                            except ApiError as error:
                                submission_errors.append(error)
                else:
                    responses = [self.client.push(self.settings.source, payload,
                                                  min(self.settings.fast_post_max_seconds, self.budget(deadline)))]
                phase["post_seconds"] = round(self.clock() - phase_start, 3)
                phase["submissions"] = []
                contract_errors = []
                for response in responses:
                    try:
                        event_id, returned_incident, versions = check_response(
                            response, key, mode, self.settings.expected_release)
                    except CheckFailed as error:
                        contract_errors.append(str(error))
                        continue
                    phase["submissions"].append({"event_sys_id": event_id,
                                                  "returned_incident_sys_id": returned_incident,
                                                  "versions": versions,
                                                  "dti_incident_status": response["results"][0].get("dti_incident_status", "")})
                if submission_errors:
                    phase["submission_errors"] = [{"reason": str(error), "http_status": error.status}
                                                   for error in submission_errors]
                    raise next((error for error in submission_errors if error.status in (401, 403)), submission_errors[0])
                if contract_errors:
                    phase["contract_errors"] = contract_errors
                    raise CheckFailed(contract_errors[0])
                if self.clock() - phase_start > self.settings.fast_post_max_seconds:
                    raise CheckFailed("fast DTI POST exceeded the prompt return budget")
                received_events = [item["event_sys_id"] for item in phase["submissions"]]
                received_incidents = {item["returned_incident_sys_id"] for item in phase["submissions"]
                                      if item["returned_incident_sys_id"]}
                if len(set(received_events + event_ids)) != len(received_events + event_ids):
                    raise CheckFailed("duplicate submission returned the original event sys_id")
                if incident_id:
                    received_incidents.add(incident_id)
                if len(received_incidents) > 1:
                    raise CheckFailed("concurrent or duplicate submissions returned different incidents")
                event_ids.extend(received_events)
                incident_id = next(iter(received_incidents), "")
                incident = self.observe(key, expected_ci, event_ids, incident_id, deadline, phase, expected_fields)
                incident_id = str(incident["sys_id"]).lower()
                phase["elapsed_seconds"] = round(self.clock() - phase_start, 3)
            result["status"] = "pass"
        except (CheckFailed, ApiError) as error:
            result["status"] = "error" if isinstance(error, ApiError) else "fail"
            result["reason"] = str(error)
            if isinstance(error, ApiError):
                result["http_status"] = error.status
            if result["phases"]:
                result["phases"][-1]["elapsed_seconds"] = round(self.clock() - phase_start, 3)
        result["elapsed_seconds"] = round(self.clock() - started, 3)
        return result

    def run(self, progress=None) -> dict:
        settings = self.settings
        run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        identity = {"ciType": settings.ci_type, "ciIdentifier": settings.identifier}
        cases = [
            ("name_only_control", {"cmdb_ci": settings.decoy_name}, settings.decoy_id, False, False, 1),
            ("identifier_only_control", identity, settings.expected_id, False, False, 1),
            ("explicit_sys_id_precedence", dict(identity, cmdb_ci=settings.decoy_id), settings.decoy_id, False, False, 1),
            ("fast_camel_conflict", dict(identity, cmdb_ci=settings.decoy_name), settings.expected_id, False, True, 1),
            ("fast_snake_conflict", {"ci_type": settings.ci_type, "ci_identifier": settings.identifier,
                                     "cmdb_ci": settings.decoy_name}, settings.expected_id, True, True, 1),
        ]
        if settings.include_concurrency:
            cases.append(("concurrent_fast_duplicates", dict(identity, cmdb_ci=settings.decoy_name),
                          settings.expected_id, False, False, 3))
        started = self.clock()
        results = []
        stop_reason = ""
        for index, (name, lookup, expected_ci, snake, duplicate, submissions) in enumerate(cases):
            if stop_reason:
                results.append({"name": name, "status": "skipped", "reason": stop_reason})
                continue
            if progress:
                progress("Running " + name + " (stable observation " + str(settings.stable_seconds) + "s per phase)")
            key = "USBEM-CIP-" + run_id + "-" + str(index + 1)
            result = self.run_case(name, lookup, expected_ci, snake, duplicate, key, submissions)
            results.append(result)
            if progress:
                progress(name + ": " + result["status"] + " after " + str(result["elapsed_seconds"]) + "s")
            if result.get("http_status") in (401, 403):
                stop_reason = "authentication or access denied; no further events submitted"
            elif index < 2 and result["status"] != "pass":
                stop_reason = "fixture control did not pass; precedence claims would be inconclusive"
        status = "pass" if all(result["status"] == "pass" for result in results) else (
            "error" if any(result["status"] == "error" for result in results) else "fail")
        return {"status": status, "run_id": run_id, "expected_release": settings.expected_release,
                "elapsed_seconds": round(self.clock() - started, 3), "cases": results,
                "phase_timeout_seconds": settings.timeout, "stable_seconds": settings.stable_seconds,
                "fast_post_max_seconds": settings.fast_post_max_seconds,
                "records_retained": True, "post_retries": 0,
                "scope": "Fast DTI CI precedence, incident fields and sequential duplicates, using records visible to the test identity; not legacy wait mode, email delivery or complete incident lifecycle",
                "concurrency_included": settings.include_concurrency,
                "accepted_residual_limitation": "Simultaneous first events for the same message key can create duplicate incidents. A default pass does not assert concurrent safety.",
                "concurrency_note": ("The optional race case fails on divergent incidents; one passing race does not prove every interleaving."
                                     if settings.include_concurrency else
                                     "Concurrent first-event stress was not requested; use --include-concurrency to exercise the accepted limitation.")}


def configuration(args, values: dict) -> tuple[str, dict, Settings]:
    slug = re.sub(r"[^A-Za-z0-9]", "", args.profile).upper()

    def get(key: str, default: str = "") -> str:
        keys = (["USBEM_" + slug + "_" + key.removeprefix("USBEM_")] if slug and key.startswith("USBEM_") else []) + [key]
        for candidate in keys:
            if os.environ.get(candidate, ""):
                return os.environ[candidate]
            if values.get(candidate, ""):
                return values[candidate]
        return default

    def secret(key: str) -> str:
        return get(key) or (decode_b64(get(key + "_B64"), key + "_B64") if get(key + "_B64") else "")

    instance = args.instance or (get("USBEM_URL") if slug else "") or get("SN_INSTANCE_URL")
    instance = validate_instance(instance)
    client_id = secret("USBEM_OAUTH_CLIENT_ID")
    client_secret = secret("USBEM_OAUTH_CLIENT_SECRET")
    username, password = args.user or secret("SN_USERNAME"), args.password or secret("SN_PASSWORD")
    if client_id or client_secret:
        if not client_id or not client_secret or args.user or args.password:
            raise ValueError("OAuth needs client ID and secret; do not combine OAuth with Basic CLI credentials")
        auth = {"mode": "oauth", "client_id": client_id, "client_secret": client_secret, "scope": get("USBEM_OAUTH_SCOPE")}
    else:
        if not username or not password or ":" in username:
            raise ValueError("configure Basic username/password or OAuth client ID/secret")
        auth = {"mode": "basic", "username": username, "password": password}
    ci_type, decoy_name = get("USBEM_CI_TYPE"), get("USBEM_DECOY_CI_NAME")
    expected_id, decoy_id = get("USBEM_EXPECTED_CI_SYS_ID").lower(), get("USBEM_DECOY_CI_SYS_ID").lower()
    if not ci_type or not IDENTIFIER_KEY.fullmatch(ci_type) or not decoy_name:
        raise ValueError("configure CI class and a valid distinct decoy CI name")
    if not SYS_ID.fullmatch(expected_id) or not SYS_ID.fullmatch(decoy_id) or expected_id == decoy_id:
        raise ValueError("expected and decoy CI sys_ids must be distinct 32-character hexadecimal IDs")
    try:
        identifier = json.loads(get("USBEM_CI_IDENTIFIER_JSON"))
    except ValueError:
        raise ValueError("USBEM_CI_IDENTIFIER_JSON must be a non-empty JSON object") from None
    if (not isinstance(identifier, dict) or not identifier or
            any(not IDENTIFIER_KEY.fullmatch(key) or not isinstance(value, (str, int, float)) or
                isinstance(value, bool) or not str(value).strip() or
                (isinstance(value, float) and not math.isfinite(value)) or
                (isinstance(value, str) and ("^" in value or "\n" in value or "\r" in value or
                                            value.lower().startswith("javascript:")))
                for key, value in identifier.items())):
        raise ValueError("identifier keys must be field names and values must be non-empty scalar strings/numbers without query operators")
    group = get("USBEM_ASSIGNMENT_GROUP")
    expected_group = get("USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID").lower() or (group.lower() if SYS_ID.fullmatch(group) else "")
    if expected_group and (not group or not SYS_ID.fullmatch(expected_group)):
        raise ValueError("expected assignment group needs a valid sys_id and a configured assignment group")
    if group and not expected_group:
        raise ValueError("when assignment group is a name, configure USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID")
    caller_id = get("USBEM_TEST_CALLER_SYS_ID").lower()
    if not SYS_ID.fullmatch(caller_id):
        raise ValueError("USBEM_TEST_CALLER_SYS_ID must be an existing test caller's 32-character sys_id")
    category, subcategory = get("USBEM_TEST_CATEGORY", "software"), get("USBEM_TEST_SUBCATEGORY", "os")
    expected_category = get("USBEM_EXPECTED_CATEGORY", "software")
    expected_subcategory = get("USBEM_EXPECTED_SUBCATEGORY", "os")
    impact, urgency = get("USBEM_TEST_IMPACT", "2"), get("USBEM_TEST_URGENCY", "2")
    if impact not in ("1", "2", "3", "4") or urgency not in ("1", "2", "3", "4"):
        raise ValueError("test impact and urgency must be valid configured numeric choice values (1-4)")
    if any(not value.strip() for value in (category, subcategory, expected_category, expected_subcategory)):
        raise ValueError("category/subcategory payload labels and expected stored values are required")
    settings = Settings(args.source or get("USBEM_SOURCE", "genericJsonV2"), ci_type, identifier,
                        decoy_name, expected_id, decoy_id, caller_id=caller_id, category=category,
                        expected_category=expected_category, subcategory=subcategory, expected_subcategory=expected_subcategory,
                        impact=impact, urgency=urgency, assignment_group=group, expected_assignment_group_id=expected_group,
                        expected_release=args.expect_version or get("USBEM_EXPECTED_RELEASE", EXPECTED_RELEASE))
    concurrency_value = get("USBEM_TEST_INCLUDE_CONCURRENCY", "false").strip().lower()
    if concurrency_value not in ("true", "false", "1", "0", "yes", "no"):
        raise ValueError("USBEM_TEST_INCLUDE_CONCURRENCY must be true or false")
    settings.include_concurrency = args.include_concurrency or concurrency_value in ("true", "1", "yes")
    for name, argument, key, default in (
            ("timeout", args.timeout, "USBEM_TEST_TIMEOUT_SECONDS", 120.0),
            ("fast_post_max_seconds", args.fast_post_max_seconds, "USBEM_FAST_POST_MAX_SECONDS", 10.0),
            ("stable_seconds", args.stable_seconds, "USBEM_TEST_STABLE_SECONDS", 30.0),
            ("poll_seconds", args.poll_seconds, "USBEM_TEST_POLL_SECONDS", 3.0),
            ("request_timeout", args.request_timeout, "USBEM_TEST_REQUEST_TIMEOUT_SECONDS", 90.0)):
        try:
            value = argument if argument is not None else float(get(key, str(default)))
        except ValueError:
            raise ValueError(name + " must be a positive finite number") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + " must be a positive finite number")
        setattr(settings, name, value)
    if settings.timeout <= settings.stable_seconds + settings.poll_seconds:
        raise ValueError("timeout must exceed stable_seconds plus poll_seconds")
    if settings.fast_post_max_seconds >= settings.timeout - settings.stable_seconds:
        raise ValueError("fast POST maximum must leave time for stable observation")
    return instance, auth, settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=str(Path(__file__).with_name("ci_identifier_test.env")))
    parser.add_argument("--profile", default="", help="use USBEM_<PROFILE>_URL/OAUTH_* keys from an existing verifier env")
    parser.add_argument("--instance", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="", help="prefer an env file to avoid credentials in process arguments")
    parser.add_argument("--source", default="")
    parser.add_argument("--expect-version", default="")
    parser.add_argument("--timeout", type=float, help="deadline per initial/duplicate phase, including POST (default 120)")
    parser.add_argument("--fast-post-max-seconds", type=float, help="maximum fast POST round-trip including auth (default 10)")
    parser.add_argument("--stable-seconds", type=float, help="continuous successful read observation per phase (default 30)")
    parser.add_argument("--poll-seconds", type=float, help="read polling interval (default 3)")
    parser.add_argument("--request-timeout", type=float, help="individual request cap, also bounded by phase deadline (default 90)")
    parser.add_argument("--ca-bundle", default="", help="PEM CA bundle for work laptop corporate trust roots")
    parser.add_argument("--insecure", action="store_true", help="disable TLS certificate verification (last resort)")
    parser.add_argument("--report-file", default="", help="save the same credential-free JSON report to this path")
    parser.add_argument("--include-concurrency", action="store_true", help="also stress three simultaneous first events; divergent incidents fail")
    args = parser.parse_args()
    try:
        values = read_env(Path(args.env_file).expanduser())
        instance, auth, settings = configuration(args, values)
        ca_bundle = args.ca_bundle or os.environ.get("USBEM_CA_BUNDLE", "") or values.get("USBEM_CA_BUNDLE", "")
        client = Client(instance, auth, ca_bundle, args.insecure)
        report = Runner(client, settings).run(lambda message: print(message, file=sys.stderr, flush=True))
        report.update(instance=instance, auth_mode=auth["mode"], tls_verified=not args.insecure)
    except (ValueError, OSError, ApiError) as error:
        # Only our controlled configuration/API messages are printed; never raw HTTP bodies.
        message = str(error) if isinstance(error, (ValueError, ApiError)) else "could not read configuration or CA bundle"
        report = {"status": "error", "reason": message}
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.report_file:
        try:
            Path(args.report_file).expanduser().write_text(output + "\n", encoding="utf-8")
        except OSError:
            print("Could not write JSON report file", file=sys.stderr)
            return 3
    print(output)
    return {"pass": 0, "fail": 2, "error": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
