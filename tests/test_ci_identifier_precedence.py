#!/usr/bin/env python3
"""One standalone, standard-library Generic JSON V2 / fast-DTI release tester.

Run this file without arguments. It reads production_test.env and dev-fixtures.json beside
the script, uses the production-safe three-table test, and saves dti-results-*.json there.
It runs available checks and reports missing optional prerequisites as INCOMPLETE, never PASS.
The compatibility command-line interface remains available for existing automation.
The production-safe test permits only:
connector POST, Event read, and owned Alert/Incident read/write. It does not read reference,
journal, attachment, schema or security tables; those evidence limits are explicit in its report.
All test records are retained. Normal testing uses no service, email, schema/security changes,
background scripts, deletes, POST retries or legacy wait keys. PATCH is restricted to owned records.
Explicit confirmed-DEV fixture setup may create five allowlisted customer fields and tagged data
through its fixed admin installer. The optional temporary default-CI phase is journaled and restored;
--prepare-fixtures-only never activates that property. Production fixture setup is prohibited.
Parallel first-event stress always runs and reports the accepted race as a known limitation.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import http.client
import http.cookiejar
import hashlib
import html
import io
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

EXPECTED_RELEASE = "2026.10.29.3"
TEST_SUITE_VERSION = "1.3.0"
try:
    SCRIPT_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
except OSError:
    SCRIPT_SHA256 = ""
SYS_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
IDENTIFIER_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
PAYLOAD_WRAPPERS = ("event", "payload", "data", "record", "alert")


def unwrap_connector(result):
    """Normalize the connector's listener-name/string envelope, without logging raw bodies."""
    if isinstance(result, dict) and "result" in result:
        result = result["result"]
    for _ in range(3):
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                raise ApiError("connector returned invalid JSON") from None
        elif (isinstance(result, dict) and result.get("status") == "failure" and
              isinstance(result.get("error"), dict) and isinstance(result["error"].get("message"), str)):
            # The Event Management resource wraps listener HTTP500 responses as
            # {status:failure,error:{message:'Listener name : {JSON}'}}. Decode the
            # embedded *whole* JSON object; do not accept arbitrary generic 500s.
            message = result["error"]["message"]
            offset = message.find("{")
            if offset < 1 or not message[:offset].rstrip().endswith(":"):
                break
            try:
                inner, end = json.JSONDecoder().raw_decode(message[offset:])
            except ValueError:
                break
            if (message[offset + end:].strip() or not isinstance(inner, dict) or
                    inner.get("status") != "error" or not isinstance(inner.get("versions"), dict)):
                break
            result = inner
        elif isinstance(result, dict) and len(result) == 1 and "status" not in result:
            result = next(iter(result.values()))
        else:
            break
    return result


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError("environment file does not exist; copy the supplied template first")
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
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
        self.insecure = bool(insecure)
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

    def query(self, table: str, query: str, fields: str, timeout: float, limit: int = 1000) -> list[dict]:
        if not IDENTIFIER_KEY.fullmatch(table):
            raise ValueError("invalid table name")
        params = {"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": str(limit),
                  "sysparm_display_value": "false", "sysparm_exclude_reference_link": "true"}
        result = self.request("GET", "/api/now/table/" + table + "?" + urllib.parse.urlencode(params), timeout=timeout)
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ApiError(table + " read returned an unexpected result shape")
        if len(result) >= limit:
            raise ApiError(table + " read reached its limit; complete evidence cannot be established")
        return result

    def download(self, attachment_id: str, timeout: float) -> bytes:
        if not SYS_ID.fullmatch(attachment_id):
            raise ValueError("invalid attachment ID")
        started = time.monotonic()
        request = urllib.request.Request(self.base + "/api/now/attachment/" + attachment_id + "/file",
                                         headers={"Accept": "application/json", "Authorization": self.authorization(timeout)})
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ApiError("attachment authentication deadline expired", retryable=True)
        try:
            with self.opener.open(request, timeout=remaining) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise ApiError("attachment download returned HTTP " + str(code), code) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise ApiError("attachment download transport/TLS failure or timeout", retryable=True) from None
        if len(raw) > 4 * 1024 * 1024:
            raise ApiError("attachment download exceeded the 4 MiB limit")
        return raw

    def probe(self, source: str, body, timeout: float, raw: bool = False) -> tuple[int, object]:
        """One deliberate negative request. Only parsed JSON is returned, never raw error text."""
        started = time.monotonic()
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "User-Agent": "genericendpoint", "Authorization": self.authorization(timeout)}
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ApiError("negative-probe authentication deadline expired", retryable=True)
        data = body if raw else json.dumps(body).encode()
        path = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": source})
        request = urllib.request.Request(self.base + path, data=data, method="POST", headers=headers)
        try:
            with self.opener.open(request, timeout=remaining) as response:
                code, content = response.status, response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            code, content = error.code, error.read(4 * 1024 * 1024 + 1)
            error.close()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise ApiError("negative-probe transport/TLS failure or timeout", retryable=True) from None
        if len(content) > 4 * 1024 * 1024:
            raise ApiError("negative-probe response exceeded the 4 MiB limit")
        try:
            return code, unwrap_connector(json.loads(content.decode("utf-8")))
        except (ValueError, UnicodeError):
            raise ApiError("negative-probe response was not JSON", code) from None


class ProductionClient(Client):
    """Enforce the production operator's three-table HTTP boundary before auth.

    This is a client-side safety boundary, not a substitute for server ACLs.
    It cannot add any privilege to the authenticated account.
    """
    TABLES = frozenset(("em_event", "em_alert", "incident"))
    PATCH_FIELDS = {"incident": frozenset(("state", "close_code", "close_notes", "u_cause")),
                    "em_alert": frozenset(("state", "incident"))}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.operation_counts = {}
        self.operation_lock = threading.Lock()

    @classmethod
    def permitted(cls, method, path, body=None):
        if not isinstance(path, str) or "\\" in path or any(character.isspace() for character in path):
            raise ValueError("production access profile refuses an external or malformed request path")
        parsed = urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not path.startswith("/"):
            raise ValueError("production access profile refuses an external or malformed request path")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if method == "POST" and parsed.path == "/oauth_token.do" and not query:
            return "oauth_token"
        if method == "POST" and parsed.path == "/api/sn_em_connector/em/inbound_event":
            if set(query) != {"source"} or len(query["source"]) != 1 or not query["source"][0]:
                raise ValueError("production connector request requires one explicit source")
            return "connector"
        match = re.fullmatch(r"/api/now/table/(em_event|em_alert|incident)(?:/([0-9a-fA-F]{32}))?", parsed.path)
        if not match:
            raise ValueError("production access profile permits only Event, Alert and Incident table requests")
        table, record_id = match.groups()
        if method == "GET":
            allowed = {"sysparm_query", "sysparm_fields", "sysparm_limit", "sysparm_display_value", "sysparm_exclude_reference_link"}
            if set(query) - allowed or any(len(values) != 1 for values in query.values()):
                raise ValueError("production table read has unsupported query parameters")
            if "sysparm_fields" in query and any(not IDENTIFIER_KEY.fullmatch(field) for field in query["sysparm_fields"][0].split(",")):
                raise ValueError("production table reads refuse reference dot-walking")
            if query.get("sysparm_display_value", ["false"]) != ["false"]:
                # Journal-input raw values are empty in Table API. Only this
                # exact-record, non-reference field view may request formatting.
                journal_view = (record_id and table in ("incident", "em_alert") and
                    query.get("sysparm_display_value") == ["true"] and
                    set(query.get("sysparm_fields", [""])[0].split(",")) == {"sys_id", "work_notes"} and
                    not (set(query) - {"sysparm_fields", "sysparm_display_value", "sysparm_exclude_reference_link"}))
                if not journal_view:
                    raise ValueError("production evidence requires raw stored values except the exact owned-record journal view")
            if "javascript:" in query.get("sysparm_query", [""])[0].lower():
                raise ValueError("production table reads refuse executable query values")
            return table
        if method == "PATCH" and record_id and not query and table in cls.PATCH_FIELDS:
            if not isinstance(body, dict) or not body or set(body) - cls.PATCH_FIELDS[table]:
                raise ValueError("production PATCH is outside its field allowlist")
            return table
        raise ValueError("production access profile refuses direct Event writes, creates, deletes or unsupported operations")

    def _count_operation(self, method, destination):
        with self.operation_lock:
            key = method + " " + destination
            self.operation_counts[key] = self.operation_counts.get(key, 0) + 1

    def request(self, method, path, body=None, timeout=90.0):
        self.permitted(method, path, body)
        return super().request(method, path, body, timeout)

    def send(self, method, path, data, headers, timeout):
        body = None
        if method == "PATCH":
            try:
                body = json.loads(data.decode("utf-8")) if data is not None else None
            except (ValueError, UnicodeError, AttributeError):
                raise ValueError("production PATCH requires an allowlisted JSON object") from None
        destination = self.permitted(method, path, body)
        self._count_operation(method, destination)
        return super().send(method, path, data, headers, timeout)

    def probe(self, source, body, timeout, raw=False):
        path = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": source})
        self._count_operation("POST", self.permitted("POST", path))
        return super().probe(source, body, timeout, raw)

    def download(self, attachment_id, timeout):
        raise ValueError("production access profile does not request attachment download access")


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
                 duplicate: bool, key: str, submissions: int = 1, wrapper: str = "") -> dict:
        if wrapper and wrapper not in PAYLOAD_WRAPPERS:
            raise ValueError("unsupported test payload wrapper")
        started = self.clock()
        result = {"name": name, "message_key": key, "status": "running", "expected_cmdb_ci": expected_ci,
                  "payload_wrapper": wrapper or "flat", "phases": [], "records_retained": True}
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
        if wrapper:
            # Wrap the complete record, including the Incident-only field overrides. Keeping
            # those fields at the root would miss the wrapper field-loss regression.
            payload = {wrapper: payload}
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
            ("name_only_control", {"cmdb_ci": settings.decoy_name}, settings.decoy_id, False, False, 1, ""),
            ("identifier_only_control", identity, settings.expected_id, False, False, 1, ""),
            ("explicit_sys_id_precedence", dict(identity, cmdb_ci=settings.decoy_id), settings.decoy_id, False, False, 1, ""),
            ("fast_camel_conflict", dict(identity, cmdb_ci=settings.decoy_name), settings.expected_id, False, True, 1, ""),
            ("fast_snake_conflict", {"ci_type": settings.ci_type, "ci_identifier": settings.identifier,
                                     "cmdb_ci": settings.decoy_name}, settings.expected_id, True, True, 1, ""),
        ]
        cases.extend(("wrapped_" + wrapper, dict(identity, cmdb_ci=settings.decoy_name),
                      settings.expected_id, False, False, 1, wrapper)
                     for wrapper in PAYLOAD_WRAPPERS)
        if settings.include_concurrency:
            cases.append(("concurrent_fast_duplicates", dict(identity, cmdb_ci=settings.decoy_name),
                          settings.expected_id, False, False, 3, ""))
        started = self.clock()
        results = []
        stop_reason = ""
        for index, (name, lookup, expected_ci, snake, duplicate, submissions, wrapper) in enumerate(cases):
            if stop_reason:
                results.append({"name": name, "status": "skipped", "reason": stop_reason})
                continue
            if progress:
                progress("Running " + name + " (stable observation " + str(settings.stable_seconds) + "s per phase)")
            key = "USBEM-CIP-" + run_id + "-" + str(index + 1)
            result = self.run_case(name, lookup, expected_ci, snake, duplicate, key, submissions, wrapper)
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
                "scope": "Fast DTI CI precedence, exact incident fields in flat/all five supported wrappers, and sequential duplicates, using records visible to the test identity; not legacy wait mode, alert linkage or complete incident lifecycle",
                "concurrency_included": settings.include_concurrency,
                "accepted_residual_limitation": "Simultaneous first events for the same message key can create duplicate incidents. A default pass does not assert concurrent safety.",
                "concurrency_note": ("The optional race case fails on divergent incidents; one passing race does not prove every interleaving."
                                     if settings.include_concurrency else
                                     "Concurrent first-event stress was not requested; use --include-concurrency to exercise the accepted limitation.")}


ADVANCED_FEATURES = (
    "node_fallback", "resource_resolution", "additional_info_name_fallback", "ci_class_label",
    "canonical_ci_name", "canonical_group_name", "invalid_group_ci_fallback", "car_id",
    "l2_support_group", "service_inference", "offering_parent_filter", "custom_incident_fields",
    "default_dummy_policy", "ambiguous_user_rejection", "foreign_task_guard",
)
FEATURE_MANIFEST = (
    "read_preflight", "name_only_control", "identifier_only_control", "explicit_sys_id_precedence",
    "fast_camel_conflict", "fast_snake_conflict",
) + tuple("wrapped_" + value for value in PAYLOAD_WRAPPERS) + (
    "wrapped_additional_info_object", "wrapped_additional_info_string", "outer_precedence",
    "record_envelope_precedence", "batch_records", "batch_events", "batch_array", "batch_mixed",
    "negative_scalar", "negative_null", "negative_string", "negative_records_null",
    "negative_records_member", "negative_events_member", "negative_array_member",
    "negative_records_container", "negative_events_container", "negative_syntax",
    "severity_1", "severity_2", "severity_3", "severity_4", "severity_0", "severity_5",
    "severity_clear", "severity_OK", "plain_non_dti", "group_name", "caller_assignee_sysid",
    "caller_assignee_name", "default_caller", "invalid_user_fallback", "ci_support_group",
    "explicit_group_override", "service_sysid", "service_name", "offering_sysid", "offering_name",
    "long_key_reuse", "incident_alert_notes", "plain_alert_notes", "default_and_duplicate_notes", "debug_success", "debug_plain", "debug_error",
    "terminal_6", "terminal_7", "terminal_8", "foreign_incident_guard", "closed_alert_guard",
    "concurrent_first_events", "parser_contract", "event_aliases", "salesforce_peru", "scalar_passthrough_and_reserved_fields",
    "dti_aliases", "incident_field_defaults", "generating_alert_reference", "netcool_ticket_default", "final_evidence_integrity",
) + ADVANCED_FEATURES


class MissingFixture(RuntimeError):
    pass


def correlation_key(key: str, length: int = 100) -> str:
    """Match the runtime's JS FNV-1a over UTF-16 code units (not UTF-8 bytes)."""
    units = key.encode("utf-16-le", errors="surrogatepass")
    value = 0x811C9DC5
    for offset in range(0, len(units), 2):
        value = ((value ^ (units[offset] | units[offset + 1] << 8)) * 0x01000193) & 0xFFFFFFFF
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    hashed = ""
    while value:
        value, remainder = divmod(value, 36)
        hashed = digits[remainder] + hashed
    suffix = "~" + (hashed or "0")
    # Test keys are ASCII, but count/truncate JS UTF-16 units for the public helper too.
    if len(units) // 2 <= length:
        return key
    return units[:2 * (length - len(suffix))].decode("utf-16-le", errors="surrogatepass") + suffix


def aggregate_status(features: list[dict]) -> str:
    if not features or any(item.get("status") not in {"pass", "fail", "error", "skip", "running", "pending", "known_limitation"} for item in features):
        return "incomplete"
    statuses = {item.get("status", "skip") for item in features}
    if "fail" in statuses:
        return "fail"
    if "error" in statuses:
        return "error"
    if statuses.intersection({"skip", "running", "pending"}):
        return "incomplete"
    return "complete_with_known_limitations" if "known_limitation" in statuses else "pass"


DEV_FIXTURE_NAMESPACE = "USBEM-DTI-FIXTURES-V1"
DEFAULT_CI_PROPERTY = "x_usbna_usb_event.default_cmdb_ci_sys_id"
FIXTURE_SCHEMA = (
    ("cmdb_ci_business_app", "u_car_id", "string", "", 100),
    ("cmdb_ci", "u_level_2_support_assignee_group", "reference", "sys_user_group", 32),
    ("incident", "u_usb_em_test_value", "string", "", 255),
    ("incident", "u_netcool_ticket", "boolean", "", None),
    ("incident", "u_generating_alert", "reference", "em_alert", 32),
)


def validate_fixture_target(instance, confirmation, auth, insecure=False):
    if (not re.fullmatch(r"https://dev[0-9]+\.service-now\.com", str(instance)) or
            confirmation != instance or not isinstance(auth, dict) or auth.get("mode") != "basic" or
            not isinstance(auth.get("username"), str) or not auth["username"] or ":" in auth["username"] or
            not isinstance(auth.get("password"), str) or not auth["password"] or insecure):
        raise ValueError("fixture administration requires verified TLS, Basic admin credentials and an exact canonical DEV PDI --confirm-fixture-target")
    return instance


def write_private_json(path, value, exclusive=False):
    """Keep recovery/catalog files private; never follow a target symlink."""
    target = Path(path).expanduser()
    if target.is_symlink():
        raise ValueError("refusing a symlink for private fixture state")
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = None
    if not exclusive:
        descriptor, temporary = tempfile.mkstemp(prefix=".usbem-state-", dir=str(target.parent))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if exclusive:
        descriptor = os.open(str(target), flags, 0o600)
    try:
        # POSIX enforces 0600 here. Windows Python may not expose fchmod;
        # file privacy there depends on the destination folder's NTFS ACLs.
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary:
            if target.is_symlink():
                raise ValueError("refusing a symlink for private fixture state")
            os.replace(temporary, target)
            temporary = None
        try:
            directory = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            # Some platforms do not permit directory fsync. The file itself is synced.
            pass
    finally:
        os.close(descriptor)
        if temporary:
            os.unlink(temporary)


class _NonceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nonce = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "input" and values.get("name") == "sysparm_ck":
            self.nonce = values.get("value") or ""


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, request, response, code, message, headers, new_url):
        destination = urllib.parse.urljoin(request.full_url, new_url)
        parsed = urllib.parse.urlsplit(destination)
        if urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")) != self.origin or code in (307, 308):
            return None
        return super().redirect_request(request, response, code, message, headers, destination)


# This is an allowlisted installer, not a general Background-script execution interface.
# Only the explicitly confirmed DEV-only mode can instantiate its authenticated session.
DEV_FIXTURE_ADMIN_SCRIPT = r"""
(function () {
    var result = {}, marker = 'USBEM DTI fixture pack v1', ns = cfg.namespace;
    function fail(message) { throw new Error(message); }
    function id(value) { return /^[0-9a-f]{32}$/.test(String(value || '')); }
    function record(table, sysId) { var g = new GlideRecord(table); if (!id(sysId) || !g.get(sysId)) fail('Fixture record unreadable: ' + table); return g; }
    function rows(table, field, value) { var g = new GlideRecord(table), out = []; g.addQuery(field, value); g.setLimit(3); g.query(); while (g.next()) out.push(String(g.getUniqueValue())); return out; }
    function value(g, field) { var raw=String(g.getValue(field) || '');if(['active','locked_out','web_service_access_only'].indexOf(field)>=0){if(raw==='1')return 'true';if(raw==='0')return 'false';}return raw; }
    function exactOwner(g, nameField, expected, ownerField) { if (value(g, nameField) !== expected || value(g, ownerField || 'description') !== marker + ' | ' + ns) fail('Fixture ownership collision: ' + g.getTableName()); }
    function ensure(table, key, expected, fields, ownerField) {
        ownerField = ownerField || 'description';
        var allowed = {sys_user_group:['active'],sys_user:['first_name','last_name','email','locked_out','active','web_service_access_only'],task:['active','state']};
        if (!allowed[table]) fail('Fixture table outside allowlist');
        var found = rows(table, key, expected), g, field;
        var shape = new GlideRecord(table);
        if (!shape.isValidField(key) || !shape.isValidField(ownerField)) fail('Fixture identity field unavailable');
        for(field in fields) if(Object.prototype.hasOwnProperty.call(fields,field) && (allowed[table].indexOf(field) < 0 || !shape.isValidField(field))) fail('Fixture field outside allowlist or absent: ' + table + '.' + field);
        if (found.length > 1) fail('Duplicate fixture key: ' + table);
        if (found.length) {
            g = record(table, found[0]); exactOwner(g, key, expected, ownerField);
            for (field in fields) if (Object.prototype.hasOwnProperty.call(fields, field) && value(g, field) !== String(fields[field])) fail('Fixture drift: ' + table + '.' + field);
            return found[0];
        }
        g = new GlideRecord(table); g.initialize(); g.setValue(key, expected); g.setValue(ownerField, marker + ' | ' + ns);
        for (field in fields) if (Object.prototype.hasOwnProperty.call(fields, field)) g.setValue(field, fields[field]);
        var inserted = String(g.insert() || ''); if (!id(inserted)) fail('Fixture insert failed: ' + table);
        g = record(table, inserted); exactOwner(g, key, expected, ownerField);
        for(field in fields)if(Object.prototype.hasOwnProperty.call(fields,field) && value(g,field)!==String(fields[field]))fail('New fixture readback mismatch: '+table+'.'+field);
        return inserted;
    }
    function propertySnapshot() {
        var found = rows('sys_properties', 'name', cfg.property_name), out = {exists: false, sys_id: '', value: '', description: '', valid_ci: false, mod_count:'', updated_on:'', effective_value:String(gs.getProperty(cfg.property_name,'__USBEM_ABSENT__'))};
        if (found.length > 1) fail('Duplicate default CI property');
        if (found.length) { var p = record('sys_properties', found[0]); out.exists = true; out.sys_id = found[0]; out.value = value(p, 'value'); out.description = value(p, 'description'); out.mod_count=value(p,'sys_mod_count');out.updated_on=value(p,'sys_updated_on');var ci = new GlideRecord('cmdb_ci'); out.valid_ci = id(out.value) && ci.get(out.value) === true; }
        return out;
    }
    function sameSnapshot(current, before) { return current.exists === before.exists && (!current.exists || (current.sys_id === before.sys_id && current.value === before.value && (!before.mod_count || current.mod_count === before.mod_count) && (!before.updated_on || current.updated_on === before.updated_on))); }
    try {
        if (!gs.hasRole('admin')) fail('DEV fixture administration requires admin');
        if (!/^https:\/\/dev[0-9]+\.service-now\.com$/.test(cfg.target) || cfg.confirmation !== cfg.target || cfg.target !== 'https://' + gs.getProperty('instance_name', '') + '.service-now.com') fail('DEV target confirmation mismatch');
        if (ns !== 'USBEM-DTI-FIXTURES-V1') fail('Fixture namespace mismatch');
        if (cfg.action.indexOf('property_') === 0) {
            if (cfg.property_name !== 'x_usbna_usb_event.default_cmdb_ci_sys_id') fail('Property is outside allowlist');
            var current = propertySnapshot();
            if (cfg.action === 'property_snapshot') result = current;
            else if (cfg.action === 'property_set') {
                if (!sameSnapshot(current, cfg.before) || current.valid_ci) fail('Default CI property changed or already points at a valid CI; refusing overwrite');
                var fixture = record('cmdb_ci', cfg.fixture_ci_id);
                if (value(fixture, 'name').indexOf('[TEST] ' + ns + ' ') !== 0 || value(fixture, 'short_description') !== marker + ' | ' + ns) fail('Temporary CI is not an owned fixture');
                var p = current.exists ? record('sys_properties', current.sys_id) : new GlideRecord('sys_properties');
                if (!current.exists) { p.initialize(); p.setValue('name', cfg.property_name); p.setValue('description', marker + ' | ' + ns + ' temporary lease'); p.setValue('type', 'string'); p.setValue('ignore_cache',true);p.setValue('private',true); }
                p.setValue('value', cfg.fixture_ci_id); var propertyId = String(current.exists ? p.update() : p.insert());
                if (!id(propertyId)) fail('Temporary property write failed');
                var after = propertySnapshot(); if (after.value !== cfg.fixture_ci_id || after.effective_value !== cfg.fixture_ci_id) fail('Temporary property readback/cache failed'); result = {sys_id: propertyId, temporary: true, mod_count:after.mod_count,updated_on:after.updated_on};
            } else if (cfg.action === 'property_restore') {
                // A completed restore increments the original row's version. A repeat
                // recovery is still a safe NO-OP when exact identity/value/cache match.
                var originalAlreadyRestored=current.exists===cfg.before.exists && (!current.exists || (current.sys_id===cfg.before.sys_id && current.value===cfg.before.value));
                if (originalAlreadyRestored) { if(current.effective_value !== (cfg.before.exists ? cfg.before.value : '__USBEM_ABSENT__')) fail('Original property effective value differs');result = {restored: true, unchanged: true}; }
                else {
                    if (!current.exists || current.value !== cfg.fixture_ci_id || (cfg.lease_sys_id && current.sys_id !== cfg.lease_sys_id) || (cfg.lease_mod_count && current.mod_count !== cfg.lease_mod_count) || (cfg.lease_updated_on && current.updated_on !== cfg.lease_updated_on)) fail('Concurrent default CI change: recovery refused to clobber');
                    if(cfg.before.exists && !cfg.lease_mod_count && (!/^\d+$/.test(String(cfg.before.mod_count || '')) || parseInt(current.mod_count,10)!==parseInt(cfg.before.mod_count,10)+1))fail('Prepared recovery cannot prove the expected single property update; refusing concurrent-change risk');
                    var restoreRow = record('sys_properties', current.sys_id);
                    if (cfg.before.exists) {
                        if (current.sys_id !== cfg.before.sys_id) fail('Original property identity changed');
                        restoreRow.setValue('value', cfg.before.value); if (!restoreRow.update()) fail('Property restore update failed');
                    } else {
                        if (value(restoreRow, 'description') !== marker + ' | ' + ns + ' temporary lease') fail('Temporary property ownership marker changed');
                        if (!restoreRow.deleteRecord()) fail('Temporary property removal failed');
                    }
                    var verified = propertySnapshot(); if (verified.exists !== cfg.before.exists || (verified.exists && (verified.sys_id !== cfg.before.sys_id || verified.value !== cfg.before.value)) || verified.effective_value !== (cfg.before.exists ? cfg.before.value : '__USBEM_ABSENT__')) fail('Property restoration row/cache readback failed'); result = {restored: true, removed_temporary_property: !cfg.before.exists};
                }
            } else fail('Unknown property action');
        } else if (cfg.action === 'provision') {
            var schema = [
                ['cmdb_ci_business_app','u_car_id','string','',100],
                ['cmdb_ci','u_level_2_support_assignee_group','reference','sys_user_group',32],
                ['incident','u_usb_em_test_value','string','',255],
                ['incident','u_netcool_ticket','boolean','',0],
                ['incident','u_generating_alert','reference','em_alert',32]
            ], missing = [], definitions = [], x, spec, d, existing;
            var preflightTables={sys_user_group:['name','description','active'],sys_user:['user_name','source','first_name','last_name','email','locked_out','web_service_access_only','active'],task:['short_description','description','active','state']};
            for(var preTable in preflightTables) if(Object.prototype.hasOwnProperty.call(preflightTables,preTable)){var preRecord=new GlideRecord(preTable);for(var preField=0;preField<preflightTables[preTable].length;preField++)if(!preRecord.isValidField(preflightTables[preTable][preField]))fail('Required fixture field unavailable: '+preTable+'.'+preflightTables[preTable][preField]);}
            // Validate every existing definition before any schema or fixture data write.
            for (x = 0; x < schema.length; x++) {
                spec = schema[x]; d = new GlideRecord('sys_dictionary'); d.addQuery('name', spec[0]); d.addQuery('element', spec[1]); d.query();
                if (d.next()) {
                    if (value(d, 'internal_type') !== spec[2] || value(d, 'reference') !== spec[3] || (spec[4] && parseInt(value(d,'max_length'),10) !== spec[4]) || value(d,'sys_scope') !== 'global') fail('Existing dictionary definition mismatch: ' + spec[0] + '.' + spec[1]);
                    if(!new GlideRecord(spec[0]).isValidField(spec[1]))fail('Existing physical fixture field is absent: '+spec[1]);
                    if (d.next()) fail('Duplicate dictionary definition');
                } else missing.push(spec);
            }
            for (x = 0; x < missing.length; x++) {
                spec = missing[x]; d = new GlideRecord('sys_dictionary'); d.initialize(); d.setValue('name', spec[0]); d.setValue('element', spec[1]); d.setValue('column_label', spec[1]); d.setValue('internal_type', spec[2]); d.setValue('sys_scope', 'global');
                if (spec[3]) d.setValue('reference', spec[3]); if (spec[4]) d.setValue('max_length', spec[4]);
                var definitionId=String(d.insert() || '');if (!id(definitionId)) fail('Dictionary create failed: ' + spec[1]);
                var stored=record('sys_dictionary',definitionId);if(value(stored,'internal_type')!==spec[2] || value(stored,'reference')!==spec[3] || (spec[4] && parseInt(value(stored,'max_length'),10)!==spec[4]) || !new GlideRecord(spec[0]).isValidField(spec[1]))fail('New dictionary/physical field readback failed: '+spec[1]);definitions.push(spec[0] + '.' + spec[1]);
            }
            var l2 = ensure('sys_user_group','name','[TEST] ' + ns + ' L2 Support',{active:'true'});
            function testUser(suffix, first, last) {
                var username = 'usbem_dti_fixture_v1_' + suffix;
                return ensure('sys_user','user_name',username,{first_name:first,last_name:last,email:'',locked_out:'true',web_service_access_only:'true',active:'true'},'source');
            }
            var owner = testUser('owner','USBEM DTI Fixture','Owner');
            var ambiguousA = testUser('ambiguous_a','USBEM DTI Fixture','Ambiguous');
            var ambiguousB = testUser('ambiguous_b','USBEM DTI Fixture','Ambiguous');
            var role = new GlideRecord('sys_user_has_role'); role.addQuery('user','IN',[owner,ambiguousA,ambiguousB].join(',')); role.setLimit(1); role.query(); if (role.hasNext()) fail('Fixture users have roles; refusing to adopt');
            var task = ensure('task','short_description','[TEST] USBEM ' + ns + ' foreign Task',{active:'false',state:'3'});
            function ire(key, cls, values) {
                values.name = '[TEST] ' + ns + ' ' + key; values.short_description = marker + ' | ' + ns;
                var reserved=rows('cmdb_ci','name',values.name), reservedId='';
                if(reserved.length>1)fail('Duplicate reserved fixture CI name: '+key);
                if(reserved.length){var reservedRow=record('cmdb_ci',reserved[0]);exactOwner(reservedRow,'name',values.name,'short_description');if(value(reservedRow,'sys_class_name')!==cls)fail('Reserved fixture CI class collision: '+key);reservedId=reserved[0];}
                var payload = {items:[{internal_id:key,className:cls,values:values,sys_object_source_info:{source_name:'ServiceNow',source_native_key:ns + ':' + key}}]};
                function parse(raw) { var out = JSON.parse(String(raw)); if (!out || out.hasError || out.errorCount || (out.errors && out.errors.length) || !out.items || out.items.length !== 1) fail('IRE failed: ' + key); var sections=['items','relations','additionalCommittedItems','additionalCommittedRelations']; for (var a=0;a<sections.length;a++) { var list=out[sections[a]] || []; for(var b=0;b<list.length;b++) if(list[b].errorCount || (list[b].errors && list[b].errors.length) || (list[b].warnings && list[b].warnings.length) || (list[b].maskedAttributes && list[b].maskedAttributes.length)) fail('IRE rejected or masked fixture: ' + key); } return out; }
                var simulation = parse(SNC.IdentificationEngineScriptableApi.identifyCI(JSON.stringify(payload))), item=simulation.items[0], predicted=String(item.sysId || item.sys_id || '');
                if(reservedId && predicted!==reservedId)fail('IRE did not prove the existing reserved fixture identity: '+key);
                if (String(item.operation).toUpperCase() !== 'INSERT' && !id(predicted)) fail('IRE existing-operation identity unproven: '+key);
                if (id(predicted)) { var match=new GlideRecord(cls);if(match.get(predicted)){if(value(match,'name') !== values.name || value(match,'short_description') !== marker + ' | ' + ns || value(match,'sys_class_name') !== cls) fail('IRE would update a foreign CI: ' + key);var unchanged=true;for(var candidateField in values)if(Object.prototype.hasOwnProperty.call(values,candidateField) && value(match,candidateField)!==String(values[candidateField]))unchanged=false;if(unchanged)return predicted;}else if(String(item.operation).toUpperCase()!=='INSERT')fail('IRE predicted existing CI is unreadable'); }
                var committed=parse(SNC.IdentificationEngineScriptableApi.createOrUpdateCI('ServiceNow',JSON.stringify(payload))), ciId=String(committed.items[0].sysId || committed.items[0].sys_id || '');
                var ci=record(cls,ciId);if(value(ci,'sys_class_name')!==cls)fail('IRE fixture class mismatch: '+key); for(var field in values) if(Object.prototype.hasOwnProperty.call(values,field) && value(ci,field) !== String(values[field])) fail('IRE fixture readback mismatch: ' + key + '.' + field);
                return ciId;
            }
            var serviceA=ire('Service A','cmdb_ci_service',{}), serviceB=ire('Service B','cmdb_ci_service',{});
            var offering=ire('Parent Offering','service_offering',{parent:serviceA});
            var l2ci=ire('L2 Server','cmdb_ci_server',{serial_number:ns + '-L2',support_group:'',u_level_2_support_assignee_group:l2});
            var supportci=ire('Support Server','cmdb_ci_server',{serial_number:ns + '-SUPPORT',support_group:l2});
            var dummy=ire('Default Server','cmdb_ci_server',{serial_number:ns + '-DEFAULT'});
            var application=ire('Business Application','cmdb_ci_business_app',{it_application_owner:owner,u_car_id:ns + '-CAR'});
            var assoc=new GlideRecord('svc_ci_assoc'), ciField='', serviceField='';
            var ciFields=['ci','cmdb_ci','configuration_item','ci_id'], serviceFields=['service','business_service','cmdb_ci_service','service_id'];
            for(x=0;x<ciFields.length;x++) if(assoc.isValidField(ciFields[x])){ciField=ciFields[x];break;}
            for(x=0;x<serviceFields.length;x++) if(assoc.isValidField(serviceFields[x])){serviceField=serviceFields[x];break;}
            if(!ciField || !serviceField) fail('Service association fields unavailable');
            assoc.addQuery(ciField,l2ci); assoc.addQuery(serviceField,serviceA); assoc.query(); var assocId='';
            if(assoc.next()){assocId=String(assoc.getUniqueValue());if(assoc.next())fail('Duplicate fixture association');}
            else{assoc.initialize();assoc.setValue(ciField,l2ci);assoc.setValue(serviceField,serviceA);assocId=String(assoc.insert() || '');if(!id(assocId))fail('Service association create failed');}
            result={namespace:ns,created_dictionary:definitions,l2_group:l2,owner_user:owner,ambiguous_users:[ambiguousA,ambiguousB],foreign_task:task,service_a:serviceA,service_b:serviceB,offering:offering,l2_ci:l2ci,support_ci:supportci,default_ci:dummy,business_app:application,association:assocId,ambiguous_name:value(record('sys_user',ambiguousA),'name')};
        } else fail('Unknown fixture action');
        gs.print(cfg.result_marker + JSON.stringify({ok:true,result:result}) + cfg.result_marker);
    } catch(e) { gs.print(cfg.result_marker + JSON.stringify({ok:false,error:String(e)}) + cfg.result_marker); }
})();
"""


class DevAdminSession:
    def __init__(self, client, confirmed_target, ca_bundle=""):
        self.target = validate_fixture_target(client.base, confirmed_target, client.auth, getattr(client, "insecure", False))
        self.client = client
        context = ssl.create_default_context(cafile=ca_bundle or None)
        self.opener = urllib.request.build_opener(_SameOriginRedirect(self.target),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), urllib.request.HTTPSHandler(context=context))
        self.logged_in = False

    def _html(self, path, fields=None):
        data = None if fields is None else urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(self.target + path, data=data,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener.open(request, timeout=300 if path == "/sys.scripts.do" and fields is not None else 90) as response:
                content = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            code = error.code; error.close()
            raise ApiError("DEV fixture administration returned HTTP " + str(code), code) from None
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException):
            raise ApiError("DEV fixture administration transport/TLS failure; outcome may be unknown") from None
        if len(content) > 8 * 1024 * 1024:
            raise ApiError("DEV fixture administration response exceeded its size limit")
        return content.decode("utf-8", "replace")

    def execute(self, action, config):
        if action not in ("provision", "property_snapshot", "property_set", "property_restore"):
            raise ValueError("fixture action is outside the built-in allowlist")
        validate_fixture_target(self.target, self.target, self.client.auth, getattr(self.client, "insecure", False))
        if not self.logged_in:
            self._html("/login.do")
            self._html("/login.do", {"user_name": self.client.auth["username"], "user_password": self.client.auth["password"], "sys_action": "sysverb_login"})
            self.logged_in = True
        parser = _NonceParser(); parser.feed(self._html("/sys.scripts.do"))
        if not parser.nonce:
            raise ApiError("DEV fixture administration session lacks Scripts Background access")
        marker = "USBEM_FIXTURE_" + uuid.uuid4().hex
        cfg = dict(config, action=action, target=self.target, confirmation=self.target,
                   namespace=DEV_FIXTURE_NAMESPACE, result_marker=marker)
        output = self._html("/sys.scripts.do", {"sysparm_ck": parser.nonce, "runscript": "Run script", "sys_scope": "global", "quota_managed_transaction": "on",
                             "script": "var cfg = " + json.dumps(cfg) + ";\n" + DEV_FIXTURE_ADMIN_SCRIPT})
        match = re.search(re.escape(marker) + r"(\{.*?\})" + re.escape(marker), html.unescape(output), re.S)
        if not match:
            raise ApiError("DEV fixture administration did not return its controlled result; inspect the private DEV execution history")
        try:
            decoded = json.loads(match.group(1))
        except ValueError:
            raise ApiError("DEV fixture administration result was invalid JSON") from None
        if decoded.get("ok") is not True or not isinstance(decoded.get("result"), dict):
            # The script only emits controlled diagnostics, never raw HTTP/proxy response bodies.
            reason = str(decoded.get("error", "fixture administration failed"))[:500]
            raise ApiError("DEV fixture administration failed: " + reason)
        return decoded["result"]


class DefaultCiLease:
    def __init__(self, admin, target, fixture_ci_id, recovery_path):
        if not SYS_ID.fullmatch(str(fixture_ci_id)):
            raise ValueError("temporary default CI must be a valid fixture sys_id")
        self.admin, self.target, self.fixture_ci_id = admin, target, fixture_ci_id
        self.path, self.journal = Path(recovery_path).expanduser(), None

    def activate(self):
        before = self.admin.execute("property_snapshot", {"property_name": DEFAULT_CI_PROPERTY})
        if before.get("valid_ci"):
            raise ValueError("an existing valid default CI must be reused, not overwritten")
        self.journal = {"format": "USBEM-default-ci-recovery-v1", "target": self.target, "namespace": DEV_FIXTURE_NAMESPACE,
                        "property_name": DEFAULT_CI_PROPERTY, "before": before, "fixture_ci_id": self.fixture_ci_id,
                        "state": "prepared", "test_suite_version": TEST_SUITE_VERSION, "script_sha256": SCRIPT_SHA256}
        write_private_json(self.path, self.journal, exclusive=True)
        result = self.admin.execute("property_set", self.journal)
        self.journal.update(lease_sys_id=result.get("sys_id", ""), lease_mod_count=result.get("mod_count", ""),
                            lease_updated_on=result.get("updated_on", ""), state="active")
        write_private_json(self.path, self.journal)
        return result

    def restore(self):
        if self.journal is None:
            return {"restored": True, "unchanged": True}
        result = self.admin.execute("property_restore", self.journal)
        if result.get("restored") is not True:
            raise ApiError("default CI restoration was not confirmed; retain the private recovery journal")
        self.journal.update(state="restored", restoration=result)
        write_private_json(self.path, self.journal)
        return result


class DevFixtureProvisioner:
    """Explicit DEV-only fixture administration; never used by a normal test run.

    Setup and execution identities are intentionally separate in time: a prepared
    catalog can subsequently be read by the ordinary restricted API test identity.
    """
    CATALOG_FORMAT = "USBEM-DTI-fixture-catalog-v1"
    CI_HINTS = ("cmdb_ci", "cmdbCi", "ci_type", "ciType", "ci_identifier", "ciIdentifier")
    SERVICE_HINTS = ("service", "business_service", "usbem_service", "usbemService", "usbem_offering",
                     "usbemOffering", "service_offering", "serviceOffering")

    def __init__(self, client, settings, confirmed_target, recovery_path, fixtures=None,
                 ca_bundle="", allow_default_ci_property=False):
        self.target = validate_fixture_target(client.base, confirmed_target, client.auth, getattr(client, "insecure", False))
        self.client, self.settings = client, settings
        self.admin = DevAdminSession(client, confirmed_target, ca_bundle)
        self.recovery_path = Path(recovery_path).expanduser()
        self.allow_default_ci_property = bool(allow_default_ci_property)
        self.fixtures = dict(fixtures or {})
        self.info = {"namespace": DEV_FIXTURE_NAMESPACE, "target": self.target,
                     "schema_allowlist": [{"table": t, "field": f, "type": kind, "reference": ref,
                                           "max_length": length} for t, f, kind, ref, length in FIXTURE_SCHEMA],
                     "cmdb_write_path": "IRE simulation then commit; exact owned identities only",
                     "fixture_records_retained": True, "automatic_privilege_grants": False,
                     "default_ci_property": {"status": "not_activated"}}

    def query(self, table, encoded_query, fields, limit=1000):
        return self.client.query(table, encoded_query, fields,
                                 self.settings.request_timeout if self.settings else 90, limit=limit)

    def exact(self, table, record_id, fields):
        if not SYS_ID.fullmatch(str(record_id)):
            raise ValueError("fixture identity is not a valid sys_id: " + table)
        result = self.query(table, "sys_id=" + record_id, fields)
        if len(result) != 1 or any(field not in result[0] for field in fields.split(",")):
            raise ApiError("fixture readback is absent or field-restricted: " + table)
        return result[0]

    def property_value(self, name):
        found = self.query("sys_properties", "name=" + name, "sys_id,name,value")
        if len(found) > 1:
            raise ApiError("duplicate fixture configuration property: " + name)
        return str(found[0].get("value", "")) if found else ""

    def provision(self):
        if self.settings is None:
            raise ValueError("fixture setup requires ordinary baseline CI/caller/group settings")
        # Prove the immutable caller/CI/group inputs before any administrator write.
        primary = self.exact("cmdb_ci", self.settings.expected_id, "sys_id,name,sys_class_name")
        self.exact("cmdb_ci", self.settings.decoy_id, "sys_id,name")
        caller = self.exact("sys_user", self.settings.caller_id, "sys_id,name")
        group = self.exact("sys_user_group", self.settings.expected_assignment_group_id, "sys_id,name")
        if not self.settings.assignment_group:
            raise ValueError("fixture setup requires the configurable baseline assignment group")
        default_caller = self.property_value("x_usbna_usb_event.default_caller_sys_id")
        if not SYS_ID.fullmatch(default_caller):
            raise ApiError("a valid existing connector default-caller property is required; setup will not change it")
        self.exact("sys_user", default_caller, "sys_id,name")
        class_rows = self.query("sys_db_object", "name=" + self.settings.ci_type, "name,label")
        if len(class_rows) != 1 or not class_rows[0].get("label"):
            raise ApiError("baseline CI class label is not uniquely readable")
        # A unique-name active member is required to test both assignee input forms.
        # Never add synthetic membership to an existing operational group.
        assignee = None
        requested = self.fixtures.get("assignee_sys_id", "")
        members = self.query("sys_user_grmember", "group=" + group["sys_id"], "sys_id,user")
        member_ids = sorted({row.get("user", "") for row in members if SYS_ID.fullmatch(str(row.get("user", "")))})
        if requested:
            member_ids = [requested] if requested in member_ids else []
        for member_id in member_ids:
            candidate = self.exact("sys_user", member_id, "sys_id,name,active")
            if str(candidate["active"]).lower() != "true" or not candidate["name"]:
                continue
            names = self.query("sys_user", "name=" + ComprehensiveRunner.literal(candidate["name"]), "sys_id")
            if len(names) == 1:
                assignee = candidate
                break
        if assignee is None:
            raise ApiError("configured group has no readable unique-name active assignee; setup will not add operational memberships")
        default_snapshot = self.admin.execute("property_snapshot", {"property_name": DEFAULT_CI_PROPERTY})
        if default_snapshot.get("description") == "USBEM DTI fixture pack v1 | " + DEV_FIXTURE_NAMESPACE + " temporary lease":
            self.info["restoration_error"] = "An earlier temporary default-CI lease must be recovered before fixture setup"
            raise ApiError(self.info["restoration_error"])
        existing_default = ""
        if default_snapshot.get("valid_ci"):
            existing_default = str(default_snapshot.get("value", ""))
            if not SYS_ID.fullmatch(existing_default) or default_snapshot.get("effective_value") != existing_default:
                raise ApiError("permanent default-CI identity/effective cache could not be verified before fixture setup")
            self.exact("cmdb_ci", existing_default, "sys_id,name")
        self.info["default_ci_property"] = {"status": "existing_valid_default_available" if existing_default else "lease_required",
                                             "writes": 0, "activated_during_setup": False}
        owned = self.admin.execute("provision", {})
        self.info["provisioned"] = owned
        required_ids = ("l2_group", "owner_user", "foreign_task", "service_a", "service_b", "offering",
                        "l2_ci", "support_ci", "default_ci", "business_app", "association")
        if owned.get("namespace") != DEV_FIXTURE_NAMESPACE or any(not SYS_ID.fullmatch(str(owned.get(key, ""))) for key in required_ids):
            raise ApiError("DEV fixture setup returned an invalid identity catalog")
        names = {}
        for key, table in (("l2_group", "sys_user_group"), ("service_a", "cmdb_ci_service"),
                           ("service_b", "cmdb_ci_service"), ("offering", "service_offering"), ("support_ci", "cmdb_ci")):
            names[key] = self.exact(table, owned[key], "sys_id,name")["name"]
        refs = self.query("sys_dictionary", "name=em_alert^element=incident", "sys_id,name,element,internal_type,reference")
        if len(refs) != 1 or refs[0].get("internal_type") != "reference" or refs[0].get("reference") != "task":
            raise ApiError("foreign Task test requires the actual em_alert.incident reference-to-task contract")
        catalog = dict(self.fixtures)
        catalog.update(group_name=group["name"], caller_name=caller["name"], default_caller_sys_id=default_caller,
                       assignee_sys_id=assignee["sys_id"], assignee_name=assignee["name"],
                       ci_support_sys_id=owned["support_ci"], ci_support_group_sys_id=owned["l2_group"],
                       service_name=names["service_a"], service_sys_id=owned["service_a"],
                       offering_name=names["offering"], offering_sys_id=owned["offering"],
                       default_category="Software", default_subcategory="Monitoring Alert",
                       foreign_task_sys_id=owned["foreign_task"], foreign_task_marker="[TEST] USBEM " + DEV_FIXTURE_NAMESPACE,
                       foreign_task_link_field="incident", provisioned_default_ci_sys_id=owned["default_ci"],
                       duplicate_work_note_enabled=self.property_value("x_usbna_usb_event.dti_duplicate_work_note").lower() != "false")
        advanced = dict(catalog.get("advanced_cases", {}))

        def case(payload, expected=None, remove=(), **extra):
            return {"payload": payload, "expected_incident": expected or {}, "remove_fields": list(remove), **extra}

        ci_remove = self.CI_HINTS
        # All fallback fixtures remove the base identifier, class and decoy name.
        advanced.update({
            "node_fallback": case({"node": primary["name"], "resource": ""}, {"cmdb_ci": primary["sys_id"]}, ci_remove),
            "resource_resolution": case({"node": "", "resource": primary["name"], "ci_type": self.settings.ci_type},
                                        {"cmdb_ci": primary["sys_id"]}, ci_remove),
            "additional_info_name_fallback": case({"node": "", "resource": "", "additional_info": {"name": primary["name"]}},
                                                  {"cmdb_ci": primary["sys_id"]}, ci_remove,
                                                  absent_additional_info=["name"]),
            "ci_class_label": case({"ci_type": class_rows[0]["label"]}, {"cmdb_ci": primary["sys_id"]}),
            "canonical_ci_name": case({"cmdb_ci": re.sub(r"[^A-Za-z0-9]+", "_", names["support_ci"]).strip("_")},
                                      {"cmdb_ci": owned["support_ci"]}, ci_remove),
            "canonical_group_name": case({"assignment_group": re.sub(r"[^A-Za-z0-9]+", "_", names["l2_group"]).strip("_")},
                                         {"assignment_group": owned["l2_group"]}),
            "invalid_group_ci_fallback": case({"assignment_group": DEV_FIXTURE_NAMESPACE + "-missing-group", "cmdb_ci": owned["support_ci"]},
                                              {"cmdb_ci": owned["support_ci"], "assignment_group": owned["l2_group"]}, ci_remove),
            "l2_support_group": case({"cmdb_ci": owned["l2_ci"]}, {"cmdb_ci": owned["l2_ci"], "assignment_group": owned["l2_group"]}, ci_remove + ("assignment_group",)),
            "car_id": case({"usbem_car_id": DEV_FIXTURE_NAMESPACE + "-CAR"}, expected_additional_info={"cmdb_ci_business_app": owned["business_app"]}),
            "service_inference": case({"cmdb_ci": owned["l2_ci"]}, {"cmdb_ci": owned["l2_ci"], "business_service": owned["service_a"]}, ci_remove + self.SERVICE_HINTS),
            "offering_parent_filter": [case({"usbem_service": names[service], "usbem_offering": names["offering"]},
                                           {"business_service": owned[service], "service_offering": offered}, self.SERVICE_HINTS)
                                       for service, offered in (("service_a", owned["offering"]), ("service_b", ""))],
            "custom_incident_fields": case({"u_usb_em_test_value": DEV_FIXTURE_NAMESPACE}, {"u_usb_em_test_value": DEV_FIXTURE_NAMESPACE}),
            "ambiguous_user_rejection": case({"assigned_to": owned.get("ambiguous_name", "")}, {"assigned_to": ""}),
        })
        dummy_remove = ci_remove + ("direct_to_incident", "directToIncident")
        advanced["default_dummy_policy"] = [
            case({"node": DEV_FIXTURE_NAMESPACE + "-missing-node", "resource": ""}, remove=dummy_remove,
                 expected_event={"cmdb_ci": existing_default or owned["default_ci"]}, want_incident=False),
            case({"node": DEV_FIXTURE_NAMESPACE + "-missing-node", "resource": "", "cmdb_ci": DEV_FIXTURE_NAMESPACE + "-missing-ci"},
                 remove=dummy_remove, expected_event={"cmdb_ci": ""}, want_incident=False),
            case({"node": "", "resource": ""}, remove=dummy_remove, expected_event={"cmdb_ci": ""}, want_incident=False)]
        catalog["advanced_cases"] = advanced
        catalog["fixture_catalog"] = {"format": self.CATALOG_FORMAT, "target": self.target,
                                      "namespace": DEV_FIXTURE_NAMESPACE, "test_suite_version": TEST_SUITE_VERSION,
                                      "fixture_records_retained": True, "runtime_release": EXPECTED_RELEASE,
                                      "default_ci_lease_required": not bool(existing_default),
                                      "default_ci_positive_sys_id": existing_default or owned["default_ci"]}
        self.fixtures = catalog
        self.info["catalog_status"] = "prepared"
        return catalog

    def run_default_ci_controls(self, runner, fixture_cases):
        before = self.admin.execute("property_snapshot", {"property_name": DEFAULT_CI_PROPERTY})
        if before.get("description") == "USBEM DTI fixture pack v1 | " + DEV_FIXTURE_NAMESPACE + " temporary lease":
            self.info["restoration_error"] = "An earlier temporary default-CI lease is still present; explicit journal recovery is required"
            runner.write_stop_reason = self.info["restoration_error"]
            raise ApiError(self.info["restoration_error"])
        if before.get("valid_ci"):
            fixtures = json.loads(json.dumps(fixture_cases))
            fixtures[0]["expected_event"]["cmdb_ci"] = before["value"]
            result = runner.advanced_collection("default_dummy_policy", fixtures)
            self.info["default_ci_property"] = {"status": "existing_valid_default_reused", "writes": 0,
                                                "default_ci_sys_id": before["value"]}
            return dict(result, property=self.info["default_ci_property"])
        if not self.allow_default_ci_property:
            raise MissingFixture("positive default-CI controls require --allow-default-ci-property in explicit DEV provisioning mode")
        fixture_ci = self.fixtures.get("provisioned_default_ci_sys_id", "")
        lease = DefaultCiLease(self.admin, self.target, fixture_ci, self.recovery_path)
        self.info["default_ci_property"] = {"status": "activation_pending", "recovery_journal": str(lease.path)}
        runner.progress("Default-CI recovery journal: " + str(lease.path))
        start = len(runner.cases)
        try:
            lease.activate()
            result = runner.advanced_collection("default_dummy_policy", fixture_cases)
            controls = runner.cases[start:]
            runner.settle(controls)
            if len(controls) != 3 or any(case.get("observation_failed") for case in controls):
                raise CheckFailed("temporary-default positive/negative controls did not all stabilize")
            return dict(result, property_restoration_required=True, recovery_journal=str(lease.path))
        finally:
            if lease.journal is not None:
                try:
                    restoration = lease.restore()
                    self.info["default_ci_property"] = {"status": "restored", "recovery_journal": str(lease.path), **restoration}
                except (ApiError, OSError, ValueError) as error:
                    self.info["default_ci_property"] = {"status": "error", "restored": False, "recovery_journal": str(lease.path),
                                                        "reason": "restoration could not be verified; run explicit recovery before continuing"}
                    runner.write_stop_reason = "Default CI restoration is unverified; further test writes stopped"
                    self.info["restoration_error"] = "Default CI restoration is unverified; use the retained private recovery journal"
                    raise ApiError("default CI restoration failed; retain recovery journal " + str(lease.path)) from error

    def recover(self, path):
        target = Path(path).expanduser()
        if target.is_symlink() or not target.is_file() or target.stat().st_mode & 0o077:
            raise ValueError("recovery requires a regular private0600 journal, not a symlink or public file")
        saved = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(saved, dict) or saved.get("format") != "USBEM-default-ci-recovery-v1" or
                saved.get("target") != self.target or saved.get("namespace") != DEV_FIXTURE_NAMESPACE or
                saved.get("property_name") != DEFAULT_CI_PROPERTY or not SYS_ID.fullmatch(str(saved.get("fixture_ci_id", ""))) or
                not isinstance(saved.get("before"), dict) or type(saved["before"].get("exists")) is not bool or
                saved.get("state") not in ("prepared", "active", "restored")):
            raise ValueError("recovery journal is invalid or belongs to another target")
        before = saved["before"]
        if (not isinstance(before.get("value"), str) or (before["exists"] and not SYS_ID.fullmatch(str(before.get("sys_id", "")))) or
                any(key in saved and saved[key] and not SYS_ID.fullmatch(str(saved[key])) for key in ("lease_sys_id",))):
            raise ValueError("recovery journal has an invalid original identity/value")
        # Forward only the fixed action schema, never arbitrary caller-supplied code.
        safe = {key: saved[key] for key in ("property_name", "before", "fixture_ci_id", "lease_sys_id", "lease_mod_count", "lease_updated_on") if key in saved}
        result = self.admin.execute("property_restore", safe)
        if result.get("restored") is not True:
            raise ApiError("recovery did not confirm property restoration")
        saved.update(state="restored", restoration=result)
        write_private_json(target, saved)
        self.info["default_ci_property"] = {"status": "restored", "recovery_journal": str(target), **result}
        return self.info["default_ci_property"]


class ComprehensiveRunner(Runner):
    """Full manifest runner. Independent cases share a continuous stable observation window."""
    EVENT_FIELDS = "sys_id,message_key,source,event_class,node,resource,metric_name,type,state,severity,description,additional_info,resolution_state,time_of_event,cmdb_ci,assignment_group,service,service_offering"
    INCIDENT_FIELDS = "sys_id,number,state,cmdb_ci,correlation_id,correlation_display,short_description,description,assignment_group,caller_id,assigned_to,category,subcategory,impact,urgency,business_service,service_offering"
    ALERT_FIELDS = "sys_id,number,message_key,source,event_class,state,incident,task,additional_info,cmdb_ci"
    PATCH_FIELDS = {"incident": {"state", "close_code", "close_notes", "u_cause"},
                    "em_alert": {"state", "incident", "task"}}
    DEBUG_NAMES = tuple(f"{index:02d}_{name}.json" for index, name in enumerate((
        "raw_payload", "normalized_payload", "mapped_event", "lookup_trace", "candidate_scores",
        "correlation_hints", "performance", "response_summary", "dti_timeline", "error_context"), 1))

    def __init__(self, client, settings: Settings, fixtures: dict | None = None,
                 monotonic=time.monotonic, sleep=time.sleep, provisioner=None) -> None:
        super().__init__(client, settings, monotonic, sleep)
        self.fixtures = fixtures or {}
        self.provisioner = provisioner
        terminal_extra = self.fixtures.get("terminal_extra_fields", {})
        if (not isinstance(terminal_extra, dict) or set(terminal_extra) - {"u_cause"} or
                any(not isinstance(value, str) or not value.strip() for value in terminal_extra.values())):
            raise ValueError("terminal_extra_fields may contain only a non-empty string u_cause")
        self.run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        self.event_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        self.prefix = "USBEM-ALL-" + self.run_id
        self.features = []
        self.cases = []
        self.owned = {}
        self.validated_task_fixtures = {}
        self.validated_task_link_fields = set()
        self.current_feature = ""
        self.permission_stop = False
        self.write_stop_reason = ""
        self.generic_baseline = None
        self.negative_keys, self.debug_events = [], []
        self.started = self.clock()

    def require(self, *names: str):
        missing = [name for name in names if not self.fixtures.get(name)]
        if missing:
            raise MissingFixture("missing reference fixture(s): " + ", ".join(missing))

    def check_group_fixture(self):
        if not self.settings.assignment_group or not SYS_ID.fullmatch(self.settings.expected_assignment_group_id):
            raise MissingFixture("complete assignment-group coverage requires assignment_group and an exact expected_assignment_group_id")

    @staticmethod
    def literal(value):
        text = str(value)
        if "^" in text or "\r" in text or "\n" in text or text.lower().startswith("javascript:"):
            raise ValueError("reference fixture text must not contain encoded-query operators")
        return text

    @staticmethod
    def equal(actual, expected, label: str):
        if str(actual or "") != str(expected or ""):
            raise CheckFailed(label + " does not equal the configured expected stored value")

    def query(self, table: str, query: str, fields: str, deadline: float | None = None):
        return self.client.query(table, query, fields, self.budget(deadline) if deadline else self.settings.request_timeout)

    def exact(self, table: str, record_id: str, fields: str):
        if not SYS_ID.fullmatch(record_id):
            raise CheckFailed("a returned record ID was invalid")
        rows = self.query(table, "sys_id=" + record_id, fields)
        if len(rows) != 1:
            raise MissingFixture(table + " exact record is not readable; inspect record/field ACLs")
        return rows[0]

    def payload(self, name: str, **overrides) -> dict:
        key = self.prefix + "-" + name
        result = {"source": "USBEM Comprehensive Regression", "event_class": "USBEM Comprehensive Regression",
                  "node": self.prefix, "resource": name, "metric_name": "usbem.release", "type": "release-test",
                  "message_key": key, "severity": "1", "description": "Retained comprehensive test " + key,
                  "direct_to_incident": True, "ci_type": self.settings.ci_type,
                  "ci_identifier": self.settings.identifier, "cmdb_ci": self.settings.decoy_name,
                  "caller_id": self.settings.caller_id, "category": self.settings.category,
                  "subcategory": self.settings.subcategory, "dti_impact": self.settings.impact,
                  "dti_urgency": self.settings.urgency, "dti_short_description": ("[TEST] USBEM " + key)[:160]}
        if self.settings.assignment_group:
            result["assignment_group"] = self.settings.assignment_group
        result.update(overrides)
        return result

    def expected(self, payload: dict, **overrides) -> dict:
        result = {"cmdb_ci": self.settings.expected_id, "caller_id": self.settings.caller_id,
                  "category": self.settings.expected_category, "subcategory": self.settings.expected_subcategory,
                  "impact": self.settings.impact, "urgency": self.settings.urgency,
                  "short_description": payload["dti_short_description"], "description": payload["description"]}
        if self.settings.expected_assignment_group_id:
            result["assignment_group"] = self.settings.expected_assignment_group_id
        result.update(overrides)
        return result

    def response_rows(self, response, count: int):
        if not isinstance(response, dict) or response.get("status") != "success":
            raise CheckFailed("connector did not report success")
        versions = response.get("versions", {})
        if response.get("version") != self.settings.expected_release or any(
                versions.get(name) != self.settings.expected_release for name in ("listener", "core", "lookups", "debug", "dti")):
            raise CheckFailed("connector component release mismatch")
        rows = response.get("results")
        if not isinstance(rows, list) or len(rows) != count or str(response.get("inserted")) != str(count):
            raise CheckFailed("connector inserted/result count mismatch")
        ids = [str(row.get("event_sys_id", "")) for row in rows if isinstance(row, dict)]
        if len(ids) != count or len(set(ids)) != count or any(not SYS_ID.fullmatch(value) for value in ids):
            raise CheckFailed("connector Event IDs are invalid or reused")
        if response.get("sys_ids") != ids:
            raise CheckFailed("connector top-level Event ID list disagrees")
        return rows

    def add_response(self, case: dict, row: dict, elapsed: float, replace: bool = False):
        if row.get("status") != "success" or row.get("message_key") != case["key"]:
            raise CheckFailed("connector per-event status/message key mismatch")
        event_id = row["event_sys_id"]
        if event_id in case["event_ids"]:
            raise CheckFailed("a replay returned an old Event ID")
        incident_id = str(row.get("incident_sys_id") or "")
        if case["want_incident"]:
            if not SYS_ID.fullmatch(incident_id) or row.get("dti_mode") != "fast_async":
                raise CheckFailed("fast DTI did not promptly return a valid Incident without wait mode")
            if case.get("active_incident") and not replace and incident_id != case["active_incident"]:
                raise CheckFailed("sequential replay changed the Incident")
            if replace and incident_id in case["incident_ids"]:
                raise CheckFailed("terminal Incident replay did not create a new Incident")
            case["active_incident"] = incident_id
            case["incident_ids"].add(incident_id)
            self.owned[("incident", incident_id)] = case["key"]
        elif incident_id:
            raise CheckFailed("suppressed or non-DTI Event unexpectedly returned an Incident")
        if elapsed > self.settings.fast_post_max_seconds:
            raise CheckFailed("fast POST exceeded the configured prompt-return budget")
        case["event_ids"].append(event_id)
        case["submissions"].append({"event_sys_id": event_id, "incident_sys_id": incident_id,
                                    "post_seconds": round(elapsed, 3), "dti_mode": row.get("dti_mode", ""),
                                    "dti_incident_status": row.get("dti_incident_status", "")})
        case["stable_since"] = None
        case["was_ready"] = False  # A deliberate new Event begins a new observation generation.

    def submit(self, payload: dict, *, wire=None, expected=None, want_incident=True,
               want_alert=True, expected_event=None, existing=None, replace=False):
        if existing is None:
            case = {"feature": self.current_feature, "name": payload.get("resource", self.current_feature),
                    "key": payload["message_key"], "payload": payload, "wire": payload if wire is None else wire,
                    "expected": self.expected(payload) if expected is None else expected,
                    "expected_event": expected_event or {}, "want_incident": want_incident,
                    "want_alert": want_alert, "event_ids": [], "incident_ids": set(), "terminal": {},
                    "active_incident": "", "submissions": [], "observations": [], "stable_since": None}
            if not case["key"].startswith(self.prefix):
                raise ValueError("all deliberate test keys must carry this run's ownership prefix")
            self.cases.append(case)
        else:
            case = existing
        started = self.clock()
        response = self.client.push(self.settings.source, case["wire"] if wire is None else wire,
                                    min(self.settings.request_timeout, self.settings.fast_post_max_seconds))
        self.add_response(case, self.response_rows(response, 1)[0], self.clock() - started, replace)
        case["response"] = response
        return case

    def submit_non_dti_guard_replay(self, case, note):
        """Exercise only the BR on a guarded Alert, without invoking DTI reuse policy.

        The API intentionally treats an existing Alert's reusable Incident as
        authoritative. This isolated NON-DTI replay must not alter the original
        case's Incident expectations or weaken ordinary DTI response assertions.
        """
        if (not any(candidate is case for candidate in self.cases) or
                case.get("feature") not in ("foreign_incident_guard", "foreign_task_guard") or
                self.current_feature != case["feature"] or case.get("want_incident") is not True or
                not str(case.get("key", "")).startswith(self.prefix) or
                self.owned.get(("incident", case.get("active_incident"))) != case["key"] or
                not isinstance(note, str) or not note.startswith(self.prefix)):
            raise CheckFailed("non-DTI guard replay is restricted to registered current-run foreign-link guard cases")
        field = "incident"
        target = case.get("expected_alert_incident", "")
        if not target and case.get("expected_alert_task"):
            field, target = "task", case["expected_alert_task"]
        if not target or target == case["active_incident"]:
            raise CheckFailed("non-DTI guard replay requires an explicit foreign link, never the original Incident")
        if ("incident", target) in self.owned:
            foreign = self.exact("incident", target, "sys_id,correlation_id,correlation_display")
            expected_key = self.owned[("incident", target)]
            if not expected_key.startswith(self.prefix):
                raise CheckFailed("foreign guard Incident ownership is not current-run")
            self.equal(foreign.get("correlation_id"), correlation_key(expected_key, int(self.fixtures.get("correlation_length", 100))),
                       "foreign guard Incident provenance")
            self.equal(foreign.get("correlation_display"), "USBEM DTI", "foreign guard Incident provenance")
        elif target in self.validated_task_fixtures and field in self.validated_task_link_fields:
            self.validate_task_fixture(target)
        else:
            raise CheckFailed("non-DTI guard replay target is not an owned Incident or validated read-only test Task")
        alerts = case.get("last_alerts", [])
        if len(alerts) != 1 or self.owned.get(("em_alert", alerts[0].get("sys_id"))) != case["key"]:
            raise CheckFailed("non-DTI guard replay requires one owned Alert")
        alert = self.exact("em_alert", alerts[0]["sys_id"], self.ALERT_FIELDS)
        self.equal(alert.get(field), target, "non-DTI guard replay fresh foreign link")
        wire = json.loads(json.dumps(case["payload"]))
        if wire.get("message_key") != case["key"]:
            raise CheckFailed("guard replay payload no longer carries its registered owned message key")
        if any(isinstance(wire.get(key), dict) for key in PAYLOAD_WRAPPERS):
            raise CheckFailed("guard replay must use the flat internally built test payload")
        for key in ("direct_to_incident", "directToIncident", "work_notes", "dti_work_note", "dtiWorkNote"):
            wire.pop(key, None)
        for key in ("additional_info", "additionalInfo"):
            if key not in wire:
                continue
            was_string = isinstance(wire[key], str)
            info = self.payload_info({key: wire[key]})
            for alias in ("direct_to_incident", "directToIncident", "work_notes", "dti_work_note", "dtiWorkNote"):
                info.pop(alias, None)
            wire[key] = json.dumps(info) if was_string else info
        wire["alert_work_notes"] = note
        started = self.clock()
        response = self.client.push(self.settings.source, wire,
                                    min(self.settings.request_timeout, self.settings.fast_post_max_seconds))
        elapsed = self.clock() - started
        row = self.response_rows(response, 1)[0]
        if row.get("status") != "success" or row.get("message_key") != case["key"]:
            raise CheckFailed("non-DTI guard response status/message key mismatch")
        event_id = row["event_sys_id"]
        if event_id in case["event_ids"]:
            raise CheckFailed("non-DTI guard replay returned an old Event ID")
        if row.get("incident_sys_id"):
            raise CheckFailed("non-DTI guard replay unexpectedly returned an Incident")
        if elapsed > self.settings.fast_post_max_seconds:
            raise CheckFailed("non-DTI guard replay exceeded the prompt-return budget")
        case["event_ids"].append(event_id)
        case["submissions"].append({"event_sys_id": event_id, "incident_sys_id": "", "post_seconds": round(elapsed, 3),
                                    "dti_mode": row.get("dti_mode", ""), "dti_incident_status": row.get("dti_incident_status", ""),
                                    "response_expectation": "isolated_non_dti_guard_no_incident"})
        case["stable_since"], case["was_ready"], case["response"] = None, False, response
        return case

    def batch(self, container: str, mixed=False):
        label = container + ("-mixed" if mixed else "")
        payloads = [self.payload(label + "-" + str(index)) for index in range(5 if container == "records" and not mixed else 3)]
        if container == "records" and not mixed:
            for index, payload in enumerate(payloads):
                payload["additional_info"] = {"custom_context": {"unchanged": True, "record_index": index}}
        if mixed:
            payloads[0].pop("direct_to_incident")
            payloads[2]["severity"] = "5"
        members = [{wrapper: payload} for wrapper, payload in zip(PAYLOAD_WRAPPERS, payloads)] if container == "records" and not mixed else payloads
        wire = members if container == "array" else {container: members}
        started = self.clock()
        response = self.client.push(self.settings.source, wire, min(self.settings.request_timeout, self.settings.fast_post_max_seconds))
        elapsed = self.clock() - started
        rows = self.response_rows(response, len(payloads))
        for index, (payload, row) in enumerate(zip(payloads, rows)):
            case = {"feature": self.current_feature, "name": payload["resource"], "key": payload["message_key"],
                    "payload": payload, "wire": payload, "expected": self.expected(payload), "expected_event": {},
                    "want_incident": not mixed or index == 1, "want_alert": not mixed or index != 2,
                    "event_ids": [], "incident_ids": set(), "terminal": {}, "active_incident": "",
                    "submissions": [], "observations": [], "stable_since": None}
            self.cases.append(case)
            if container == "records" and not mixed:
                case["expected_additional_info"] = {"custom_context": {"unchanged": True, "record_index": index}}
            self.add_response(case, row, elapsed)
        return {"batch_members": len(payloads), "post_seconds": round(elapsed, 3)}

    def snapshot(self, case: dict, deadline: float) -> bool:
        if any(not IDENTIFIER_KEY.fullmatch(field) for field in list(case["expected"]) + list(case["expected_event"])):
            raise ValueError("expected fields must be technical field names")
        event_fields = self.EVENT_FIELDS + "," + ",".join(case["expected_event"])
        incident_fields = self.INCIDENT_FIELDS + "," + ",".join(case["expected"])
        events = self.query("em_event", "message_key=" + case["key"], event_fields, deadline)
        incidents = self.query("incident", "correlation_id=" + correlation_key(case["key"], int(self.fixtures.get("correlation_length", 100))), incident_fields, deadline)
        alerts = self.query("em_alert", "message_key=" + case["key"], self.ALERT_FIELDS, deadline)
        for rows, required in ((events, ("sys_id", "message_key", "state", "additional_info")),
                               (incidents, ("sys_id", "correlation_id", "state")),
                               (alerts, ("sys_id", "message_key", "incident", "additional_info", "state"))):
            if any(any(field not in row for field in required) for row in rows):
                raise MissingFixture("readback omitted required fields; inspect field ACLs")
        if len(events) > len(case["event_ids"]):
            raise CheckFailed("more Event rows than deliberate one-shot submissions")
        if any(row["sys_id"] not in case["event_ids"] for row in events):
            raise CheckFailed("stored Event ID differs from response")
        actual_incidents = {row["sys_id"] for row in incidents}
        if len(actual_incidents) != len(incidents):
            raise CheckFailed("Incident read returned duplicate rows/IDs")
        if len({row["sys_id"] for row in events}) != len(events) or len({row["sys_id"] for row in alerts}) != len(alerts):
            raise CheckFailed("Event/Alert read returned duplicate rows/IDs")
        if actual_incidents - case["incident_ids"]:
            raise CheckFailed("an unexpected duplicate Incident exists for the correlation key")
        if not case["want_incident"] and incidents:
            raise CheckFailed("suppressed/non-DTI payload created an Incident")
        reasons = []
        if {row["sys_id"] for row in events} != set(case["event_ids"]):
            reasons.append("Event visibility")
        if any(str(row["state"]).lower() != "processed" for row in events):
            reasons.append("Event processing")
        for row in events:
            for field, value in case["expected_event"].items():
                if field not in row:
                    raise MissingFixture("Event read omitted expected field " + field)
                self.equal(row[field], value, "Event " + field)
        if actual_incidents != case["incident_ids"]:
            reasons.append("Incident visibility")
        for row in incidents:
            self.equal(row["correlation_id"], correlation_key(case["key"], int(self.fixtures.get("correlation_length", 100))), "Incident correlation breadcrumb")
            if row["sys_id"] in case["terminal"]:
                self.equal(row["state"], case["terminal"][row["sys_id"]], "retained terminal Incident state")
            elif row["sys_id"] == case["active_incident"] or case.get("concurrency"):
                if str(row["state"]) in ("6", "7", "8") and not case.get("allow_terminal_active"):
                    raise CheckFailed("returned active Incident is terminal")
                for field, value in case["expected"].items():
                    if field not in row:
                        raise MissingFixture("Incident read omitted expected field " + field)
                    self.equal(row[field], value, "Incident " + field)
        if case["want_alert"] and not alerts:
            reasons.append("Alert visibility")
        needs_current_replacement_link = bool(case["want_incident"] and case["terminal"] and case["active_incident"] and
                                              "expected_alert_incident" not in case and not case.get("concurrency"))
        current_replacement_link_seen = False
        for alert in alerts:
            self.owned[("em_alert", alert["sys_id"])] = case["key"]
            expected_link = case.get("expected_alert_incident", case["active_incident"] if case["want_incident"] else "")
            actual_link = str(alert["incident"] or "")
            closed = str(alert.get("state") or "").casefold() == str(self.fixtures.get("alert_closed_state", "Closed")).casefold()
            # Historical Closed Alerts are immutable lifecycle evidence. The BR deliberately
            # leaves their old terminal Incident link intact; a *current* Alert must separately
            # claim the replacement. Never accept a foreign link just because an Alert is Closed.
            if needs_current_replacement_link and closed and actual_link in case["terminal"]:
                continue
            if "expected_alert_task" in case:
                if "task" not in alert:
                    raise MissingFixture("Alert task link not readable")
                self.equal(alert["task"], case["expected_alert_task"], "foreign Task guard stable link")
            if case.get("concurrency"):
                if actual_link and actual_link not in case["incident_ids"]:
                    raise CheckFailed("race Alert linked to an Incident outside the returned owned set")
                if not actual_link:
                    reasons.append("BR race Alert/Incident link")
                continue
            if actual_link and actual_link != expected_link:
                if actual_link in case["terminal"] and not case.get("was_ready"):
                    reasons.append("BR terminal replacement link")
                    continue
                raise CheckFailed("Alert was linked to a different Incident")
            if actual_link != expected_link:
                reasons.append("BR Alert/Incident link")
            elif needs_current_replacement_link and not closed:
                current_replacement_link_seen = True
        if needs_current_replacement_link and not current_replacement_link_seen:
            reasons.append("current Alert/replacement Incident link")
        ready = not reasons
        case["observations"].append({"elapsed_seconds": round(self.clock() - self.started, 3), "ready": ready,
                                     "reasons": sorted(set(reasons)), "event_count": len(events),
                                     "incident_count": len(incidents), "alert_ids": [row["sys_id"] for row in alerts]})
        case["last_events"], case["last_incidents"], case["last_alerts"] = events, incidents, alerts
        if case.get("was_ready") and not ready:
            raise CheckFailed("stored evidence drifted after reaching the expected state: " + ", ".join(reasons))
        case["was_ready"] = ready
        return ready

    def settle(self, cases: list[dict] | None = None):
        pending = [case for case in (self.cases if cases is None else cases) if not case.get("observation_failed")]
        if not pending:
            return
        deadline = self.clock() + self.settings.timeout
        for case in pending:
            case["stable_since"] = None
        while pending and self.clock() < deadline:
            for case in list(pending):
                try:
                    ready = self.snapshot(case, deadline)
                    if self.clock() >= deadline:
                        raise CheckFailed("observation deadline expired during readback")
                    if ready:
                        case["stable_since"] = self.clock() if case["stable_since"] is None else case["stable_since"]
                        dwell = self.clock() - case["stable_since"]
                        case["stable_observed_seconds"] = round(dwell, 3)
                        if dwell >= self.settings.stable_seconds:
                            pending.remove(case)
                    else:
                        case["stable_since"] = None
                except ApiError as error:
                    case["stable_since"] = None
                    if error.retryable and error.status not in (401, 403):
                        case["transient_read_errors"] = case.get("transient_read_errors", 0) + 1
                        continue
                    self.observation_error(case, error)
                    pending.remove(case)
                except (CheckFailed, MissingFixture) as error:
                    self.observation_error(case, error)
                    pending.remove(case)
            if pending:
                self.sleep(min(self.settings.poll_seconds, max(0, deadline - self.clock())))
        for case in pending:
            self.observation_error(case, CheckFailed("stable observation timed out; see recorded readiness reasons"))

    def observation_error(self, case, error):
        case["observation_failed"] = True
        feature = next(item for item in self.features if item["name"] == case["feature"])
        status = "skip" if isinstance(error, MissingFixture) or isinstance(error, ApiError) and error.status == 403 else "error" if isinstance(error, ApiError) else "fail"
        self.feature_problem(feature, status, str(error), "stored_observation", error.status if isinstance(error, ApiError) else None)
        if isinstance(error, ApiError):
            self.permission_stop = self.permission_stop or error.status == 401

    @staticmethod
    def feature_problem(feature, status, reason, phase, http_status=None):
        # A later observer must not replace the original response/semantic
        # failure with a secondary symptom such as an unbookkept Event row.
        if feature.get("reason") and feature.get("status") in ("fail", "error", "skip"):
            secondary = {"phase": phase, "status": status, "reason": reason}
            if http_status is not None:
                secondary["http_status"] = http_status
            feature.setdefault("additional_failures", []).append(secondary)
        else:
            feature.update(status=status, reason=reason)
            if http_status is not None:
                feature["http_status"] = http_status

    def run_feature(self, name: str, callback, required=()):
        if name not in FEATURE_MANIFEST:
            raise ValueError("feature must be declared in FEATURE_MANIFEST")
        self.current_feature = name
        feature = {"name": name, "status": "running", "required_fixtures": list(required)}
        self.features.append(feature)
        started = self.clock()
        try:
            if self.permission_stop:
                raise MissingFixture("authentication failed; further writes stopped")
            if self.write_stop_reason:
                raise MissingFixture(self.write_stop_reason)
            self.require(*required)
            detail = callback()
            if feature["status"] == "running":
                feature["status"] = "pass"
            if isinstance(detail, dict) and "event_ids" not in detail:
                feature["evidence"] = detail
        except MissingFixture as error:
            self.feature_problem(feature, "skip", str(error), "feature_execution")
        except CheckFailed as error:
            self.feature_problem(feature, "fail", str(error), "feature_execution")
        except ApiError as error:
            self.feature_problem(feature, "skip" if error.status == 403 else "error", str(error), "feature_execution", error.status)
            self.permission_stop = self.permission_stop or error.status == 401
        except (ValueError, TypeError, KeyError, IndexError):
            self.feature_problem(feature, "error", "fixture or response structure is invalid; inspect configured schema", "feature_execution")
        feature["elapsed_seconds"] = round(self.clock() - started, 3)
        return feature

    def patch_owned(self, table: str, record_id: str, updates: dict):
        if table not in self.PATCH_FIELDS or not updates or set(updates) - self.PATCH_FIELDS[table]:
            raise ValueError("PATCH contains a table or field outside the test allowlist")
        key = self.owned.get((table, record_id), "")
        if not key.startswith(self.prefix):
            raise CheckFailed("refusing to PATCH a record not owned by this run")
        for field, value in updates.items():
            if field not in ("incident", "task") or not value:
                continue
            if ("incident", str(value)) in self.owned:
                continue
            if field in self.validated_task_link_fields and str(value) in self.validated_task_fixtures:
                self.validate_task_fixture(str(value))
                continue
            raise CheckFailed("refusing PATCH: target Incident/Task is not owned by this run or an explicitly validated test Task fixture")
        fields = self.INCIDENT_FIELDS if table == "incident" else self.ALERT_FIELDS
        row = self.exact(table, record_id, fields)
        ownership = row.get("correlation_id") if table == "incident" else row.get("message_key")
        expected = correlation_key(key, int(self.fixtures.get("correlation_length", 100))) if table == "incident" else key
        if ownership != expected:
            raise CheckFailed("refusing PATCH: fresh stored ownership marker differs")
        if table == "incident" and row.get("correlation_display") != "USBEM DTI":
            raise CheckFailed("refusing PATCH: Incident lacks USBEM DTI provenance")
        return self.client.request("PATCH", "/api/now/table/" + table + "/" + record_id, updates,
                                   timeout=self.settings.request_timeout)

    def journals(self, record_id: str, note: str):
        if ("incident", record_id) not in self.owned and ("em_alert", record_id) not in self.owned:
            if record_id not in self.validated_task_fixtures:
                raise CheckFailed("journal target is not owned by this run or a validated read-only test Task")
            self.validate_task_fixture(record_id)
        rows = self.query("sys_journal_field", "element_id=" + record_id + "^element=work_notes", "sys_id,element_id,element,value")
        if any("value" not in row for row in rows):
            raise MissingFixture("journal values not readable; inspect field ACLs")
        return [row for row in rows if note in str(row["value"]).replace("\r\n", "\n").split("\n\n")]

    def assert_note(self, ids, note, expected, label):
        count = sum(str(row["value"]).replace("\r\n", "\n").split("\n\n").count(note)
                    for record_id in ids for row in self.journals(record_id, note))
        if count != expected:
            raise CheckFailed(label + " journal count is " + str(count) + ", expected " + str(expected))

    def negative(self, name: str, body, expected_message: str, keys=(), raw=False):
        started = self.clock()
        code, response = self.client.probe(self.settings.source, body, self.settings.request_timeout, raw)
        if code in (401, 403):
            raise ApiError("negative probe was denied, not validated by the listener", code)
        if code not in (400, 500) or not isinstance(response, dict) or response.get("status") != "error":
            raise CheckFailed("invalid shape did not receive an explicit listener error")
        if expected_message not in str(response.get("message", "")):
            raise CheckFailed("negative response was not the expected shape-validation error")
        versions = response.get("versions", {})
        if response.get("version") != self.settings.expected_release or any(versions.get(component) != self.settings.expected_release for component in ("listener", "core", "lookups", "debug", "dti")):
            raise CheckFailed("negative probe was not handled by the expected listener release")
        # Repeat this no-side-effect check after the final observation window too.
        self.negative_keys.extend(keys)
        for key in keys:
            for table, field in (("em_event", "message_key"), ("incident", "correlation_id"), ("em_alert", "message_key")):
                if self.query(table, field + "=" + key, "sys_id"):
                    raise CheckFailed("malformed batch inserted a valid first member")
        return {"http_status": code, "expected_error_class": name, "post_seconds": round(self.clock() - started, 3)}

    def notes_case(self, plain=False):
        suffix = "plain-notes" if plain else "notes"
        incident_note, alert_note = self.prefix + " INCIDENT-ONLY", self.prefix + " ALERT-INITIAL"
        payload = self.payload(suffix, work_notes=incident_note, alert_work_notes=alert_note)
        if plain:
            payload.pop("direct_to_incident")
            payload.pop("alert_work_notes")
        case = self.submit(payload, want_incident=not plain)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("note fixture did not reach processed/linked state")
        alert_ids = [row["sys_id"] for row in case["last_alerts"]]
        if plain:
            self.assert_note(alert_ids, incident_note, 1, "plain work_notes to Alert")
            for _ in range(2):
                wire = dict(payload)
                wire.pop("work_notes")
                self.submit(payload, wire=wire, existing=case)
            self.settle([case])
            self.assert_note(alert_ids, incident_note, 1, "plain note after no-note updates")
            self.assert_consumed_notes(case["last_alerts"])
            return {"plain_note_count": 1, "no_note_updates": 2}
        self.assert_note([case["active_incident"]], incident_note, 1, "Incident-only creation note")
        self.assert_note(alert_ids, incident_note, 0, "Incident-only note not copied to Alert")
        self.assert_note(alert_ids, alert_note, 1, "initial Alert note")
        followup = self.prefix + " ALERT-FOLLOWUP-AFTER-LINK"
        wire = dict(payload)
        wire.pop("work_notes")
        wire["alert_work_notes"] = followup
        self.submit(payload, wire=wire, existing=case)
        self.settle([case])
        self.assert_note(alert_ids, followup, 1, "follow-up Alert note")
        for _ in range(2):
            wire = dict(payload)
            wire.pop("work_notes")
            wire.pop("alert_work_notes")
            self.submit(payload, wire=wire, existing=case)
        self.settle([case])
        self.assert_note(alert_ids, followup, 1, "follow-up after two no-note updates")
        self.assert_note([case["active_incident"]], followup, 0, "Alert note not copied to Incident")
        self.assert_note([case["active_incident"]], incident_note, 1, "Incident note not repeated by replay")
        self.assert_consumed_notes(case["last_alerts"])
        return {"initial_incident_note": 1, "initial_alert_note": 1, "followup_alert_note": 1, "no_note_updates": 2}

    def assert_consumed_notes(self, alerts):
        for alert in alerts:
            try:
                info = json.loads(alert["additional_info"] or "{}")
            except (ValueError, TypeError):
                raise CheckFailed("Alert additional_info is not valid JSON") from None
            if "alert_work_notes" in info or "work_notes" in info:
                raise CheckFailed("pending Alert note was not consumed")

    def default_notes_case(self):
        payload = self.payload("default-note")
        case = self.submit(payload)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("default note fixture did not become processed/linked")
        target = [case["active_incident"]]
        creation = "Direct To Incident Via Event Management Generic JSON Endpoint"
        self.assert_note(target, creation, 1, "default connector creation note")
        self.assert_note(target, "Incident Created From " + case["key"], 1, "creation provenance breadcrumb")
        self.submit(payload, existing=case)
        self.settle([case])
        duplicate = "Duplicate event received via Event Management Generic JSON Endpoint (" + case["key"] + ")"
        duplicate_enabled = self.fixtures.get("duplicate_work_note_enabled", True)
        if not isinstance(duplicate_enabled, bool):
            raise ValueError("duplicate_work_note_enabled fixture must be a JSON boolean")
        self.assert_note(target, creation, 1, "creation note not replayed")
        self.assert_note(target, duplicate, 1 if duplicate_enabled else 0, "duplicate reuse note policy")
        # The documented dti_work_note alias must also survive create and reuse.
        alias_payload = self.payload("documented-note", dti_work_note=self.prefix + " DTI-ALIAS-NOTE")
        alias_case = self.submit(alias_payload)
        self.settle([alias_case])
        self.submit(alias_payload, existing=alias_case)
        self.settle([alias_case])
        self.assert_note([alias_case["active_incident"]], alias_payload["dti_work_note"], 2, "documented alias on create and replay")
        return {"creation_note_count": 1, "duplicate_note_count": 1 if duplicate_enabled else 0,
                "documented_alias_note_count": 2, "duplicate_policy_enabled": duplicate_enabled}

    def dti_aliases_case(self):
        aliases = {"direct_to_incident": "directToIncident", "dti_impact": "dtiImpact",
                   "dti_urgency": "dtiUrgency", "dti_short_description": "dtiShortDescription",
                   "dti_work_note": "dtiWorkNote"}
        for style in ("snake", "camel"):
            payload = self.payload("dti-alias-" + style, dti_work_note=self.prefix + " DTI-ALIAS-" + style)
            expected = self.expected(payload)
            wire = {aliases.get(key, key) if style == "camel" else key: value for key, value in payload.items()}
            case = self.submit(payload, wire=wire, expected=expected)
            self.settle([case])
            if case.get("observation_failed"):
                raise CheckFailed("DTI alias case did not become processed and linked")
            self.submit(payload, wire=wire, existing=case)
            self.settle([case])
            self.assert_note([case["active_incident"]], payload["dti_work_note"], 2,
                             style + " DTI work-note alias on creation and sequential replay")
        return {"alias_styles": ["snake", "camel"], "note_count_per_style": 2,
                "required_fields_checked": True, "wait_keys_sent": False}

    def incident_defaults_case(self):
        self.require("default_category", "default_subcategory")
        if any(not isinstance(self.fixtures[name], str) or not self.fixtures[name].strip()
               for name in ("default_category", "default_subcategory")):
            raise MissingFixture("default category/subcategory fixtures must be independently verified stored values")
        payload = self.payload("default-categories")
        wire = dict(payload)
        wire.pop("category")
        wire.pop("subcategory")
        self.submit(payload, wire=wire,
                    expected=self.expected(payload, category=self.fixtures["default_category"], subcategory=self.fixtures["default_subcategory"]))
        payload = self.payload("default-short-description")
        wire = dict(payload)
        wire.pop("dti_short_description")
        wire.pop("short_description", None)
        wire["dti_description"] = "This unmapped distractor must not replace Event description " + self.prefix
        case = self.submit(payload, wire=wire,
                           expected=self.expected(payload, short_description=payload["description"][:160], description=payload["description"]))
        case["expected_additional_info"] = {"dti_description": wire["dti_description"]}
        return {"default_category": self.fixtures["default_category"], "default_subcategory": self.fixtures["default_subcategory"],
                "short_description_falls_back_to_event_description": True, "subcases": 2,
                "qualification": "Stored-value contract, not certification that a target's choice taxonomy is appropriate for production."}

    def scalar_reserved_case(self):
        unknown = "usbem_unknown_" + uuid.uuid4().hex[:12]
        fake_id = uuid.uuid4().hex
        fake_number = "USBEM-FAKE-NUMBER-" + self.run_id
        info = {"sys_id": fake_id, "number": fake_number, "correlation_id": self.prefix + "-ATTACKED-CORRELATION",
                "correlation_display": "NOT USBEM DTI", "contact_type": "email", unknown: "retained unknown scalar",
                "location": {"nested": "do not coerce into a reference"}, "watch_list": ["do not coerce into a list field"],
                "custom_context": {"retained": True, "array": [1, "two"]}}
        payload = self.payload("reserved-and-scalars", additional_info=info)
        case = self.submit(payload, expected=self.expected(payload, contact_type="email", correlation_display="USBEM DTI"))
        returned = case["response"]["results"][0]
        skipped = set(str(returned.get("incident_fields_skipped", "")).split(","))
        applied = set(str(returned.get("incident_fields_applied", "")).split(","))
        if unknown not in skipped or "contact_type" not in applied:
            raise CheckFailed("scalar passthrough/unknown-field reporting contract mismatch")
        if applied.intersection({"sys_id", "number", "correlation_id", "correlation_display", "location", "watch_list"}):
            raise CheckFailed("reserved or object/array Incident fields were reported as applied")
        row = self.exact("incident", case["active_incident"], "sys_id,number,correlation_id,correlation_display,contact_type,location,watch_list")
        if any(field not in row for field in ("contact_type", "location", "watch_list", "number", "correlation_display")):
            raise MissingFixture("standard passthrough/reserved-field readback fields are absent or unreadable")
        if row["sys_id"] == fake_id or row["number"] == fake_number:
            raise CheckFailed("sender replaced a reserved Incident identity field")
        self.equal(row["correlation_display"], "USBEM DTI", "protected Incident provenance")
        self.equal(row["correlation_id"], correlation_key(case["key"], int(self.fixtures.get("correlation_length", 100))), "protected Incident correlation")
        for field in ("location", "watch_list"):
            actual = str(row.get(field) or "")
            if "do not coerce" in actual or actual in ("[object Object]", json.dumps(info[field])):
                raise CheckFailed("unsupported object/array context was coerced into an Incident field")
        case["expected_additional_info"] = {"custom_context": {"retained": True, "array": [1, "two"]},
                                           "location": {"nested": "do not coerce into a reference"},
                                           "watch_list": ["do not coerce into a list field"]}
        return {"unknown_scalar_field": unknown, "contact_type": "email", "reserved_identity_fields_unchanged": True,
                "object_array_context_preserved_without_incident_coercion": True}

    def incident_default_field_case(self, generating=False):
        candidates = [case for case in self.cases if case["feature"] == "identifier_only_control" and not case.get("observation_failed")]
        if not candidates or not candidates[0].get("last_alerts"):
            raise MissingFixture("a processed, linked identifier control is needed for custom Incident defaults")
        case = candidates[0]
        field = "u_generating_alert" if generating else "u_netcool_ticket"
        row = self.exact("incident", case["active_incident"], "sys_id," + field)
        if field not in row:
            raise MissingFixture(field + " is not installed or not readable on this target; no schema will be added")
        if generating:
            allowed = {alert["sys_id"] for alert in case["last_alerts"]}
            if row[field] not in allowed:
                raise CheckFailed("Incident generating Alert reference does not identify its actual linked Alert")
        elif str(row[field]).lower() not in ("true", "1"):
            raise CheckFailed("Netcool Ticket default was not set true without an incoming override")
        return {"incident_sys_id": row["sys_id"], "field": field, "stored_value": row[field], "extra_writes": 0}

    def debug_case(self, error=False, plain=False):
        payload = self.payload("debug-error" if error else "debug-plain" if plain else "debug-success", usbem_debug=True)
        if plain:
            payload.pop("direct_to_incident")
        if error:
            code, response = self.client.probe(self.settings.source, {"usbem_debug": True, "records": [payload, None]}, self.settings.request_timeout)
            if code not in (400, 500) or not isinstance(response, dict) or response.get("status") != "error" or "index 1" not in response.get("message", ""):
                raise CheckFailed("debug error probe did not produce the expected shape error")
            self.negative_keys.append(payload["message_key"])
        else:
            case = self.submit(payload, want_incident=not plain)
            response = case["response"]
        debug_id = str(response.get("debug_raw_event_sys_id", ""))
        if not SYS_ID.fullmatch(debug_id):
            raise CheckFailed("debug response did not return a companion Event ID")
        event = self.exact("em_event", debug_id, self.EVENT_FIELDS)
        self.equal(event.get("severity"), "5", "debug companion severity")
        rows = self.query("sys_attachment", "table_name=em_event^table_sys_id=" + debug_id,
                          "sys_id,file_name,content_type,size_bytes,table_name,table_sys_id")
        expected_names = set(self.DEBUG_NAMES[:8]) | ({self.DEBUG_NAMES[9]} if error else set() if plain else {self.DEBUG_NAMES[8]})
        names = [row.get("file_name", "") for row in rows]
        if set(names) != expected_names or len(names) != len(set(names)):
            raise CheckFailed("debug attachment names/count differ from conditional attachment contract")
        downloads = []
        parsed = {}
        for row in rows:
            raw = self.client.download(row["sys_id"], self.settings.request_timeout)
            if str(len(raw)) != str(row.get("size_bytes")):
                raise CheckFailed("debug download byte length differs from attachment metadata")
            if any(field not in row for field in ("content_type", "table_name", "table_sys_id")):
                raise MissingFixture("debug attachment metadata fields are not readable")
            if str(row["content_type"]).split(";", 1)[0].strip().lower() != "application/json":
                raise CheckFailed("debug attachment content type is not application/json")
            if row["table_name"] != "em_event" or row["table_sys_id"] != debug_id:
                raise CheckFailed("debug attachment belongs to a different parent record")
            try:
                parsed[row["file_name"]] = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                raise CheckFailed("a debug attachment is not UTF-8 JSON") from None
            downloads.append({"file_name": row["file_name"], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        for name in self.DEBUG_NAMES[1:7]:
            if not isinstance(parsed[name], list):
                raise CheckFailed("debug array attachment has an invalid shape")
        array_keys = {
            self.DEBUG_NAMES[1]: ("record_index", "normalized_input", "raw_event"),
            self.DEBUG_NAMES[2]: ("record_index", "event_sys_id", "final_event"),
            self.DEBUG_NAMES[3]: ("record_index", "steps", "lookups", "notes", "errors"),
            self.DEBUG_NAMES[4]: ("record_index", "candidates"),
            self.DEBUG_NAMES[5]: ("record_index", "event_sys_id", "message_key", "source", "event_class"),
            self.DEBUG_NAMES[6]: ("record_index", "processing_ms", "perf", "quality"),
        }
        for name, required in array_keys.items():
            records = parsed[name]
            if len(records) != (0 if error else 1):
                raise CheckFailed("debug per-record attachment count differs from processed contexts")
            if any(not isinstance(record, dict) or any(key not in record for key in required) or record["record_index"] != index
                   for index, record in enumerate(records)):
                raise CheckFailed("debug per-record attachment schema/index invalid")
        if not isinstance(parsed[self.DEBUG_NAMES[7]], dict):
            raise CheckFailed("debug response summary shape invalid")
        if error:
            if "index 1" not in str(parsed[self.DEBUG_NAMES[9]].get("error", "")):
                raise CheckFailed("error context does not identify the deliberate invalid member")
        else:
            if parsed[self.DEBUG_NAMES[0]] != payload:
                raise CheckFailed("raw debug attachment differs from the submitted payload")
            if parsed[self.DEBUG_NAMES[7]].get("sys_ids") != case["event_ids"]:
                raise CheckFailed("debug response summary identifies a different parent Event")
            mapped = parsed[self.DEBUG_NAMES[2]][0]
            hints = parsed[self.DEBUG_NAMES[5]][0]
            if mapped["event_sys_id"] != case["event_ids"][0] or hints["event_sys_id"] != case["event_ids"][0] or hints["message_key"] != case["key"]:
                raise CheckFailed("debug mapped Event/correlation hints identify a different parent")
            for name, key in ((self.DEBUG_NAMES[1], "normalized_input"), (self.DEBUG_NAMES[1], "raw_event"),
                              (self.DEBUG_NAMES[2], "final_event")):
                if not isinstance(parsed[name][0][key], dict):
                    raise CheckFailed("debug payload/Event snapshot must be an object")
            if not plain:
                timeline = parsed[self.DEBUG_NAMES[8]]
                if (not isinstance(timeline, list) or len(timeline) != 1 or not isinstance(timeline[0], dict) or
                        any(key not in timeline[0] for key in ("record_index", "direct_to_incident", "dti", "result")) or
                        timeline[0]["record_index"] != 0 or timeline[0]["direct_to_incident"] is not True or
                        timeline[0].get("wait_for_alert") is not False or timeline[0].get("wait_for_incident") is not False or
                        not isinstance(timeline[0]["dti"], dict) or not isinstance(timeline[0]["result"], dict)):
                    raise CheckFailed("DTI timeline shape/default no-wait flags invalid")
            try:
                companion_info = json.loads(event.get("additional_info") or "{}")
            except (ValueError, TypeError):
                raise CheckFailed("debug companion metadata is not JSON") from None
            if companion_info.get("usbem_version") != self.settings.expected_release or companion_info.get("usbem_debug_parent_event_sys_ids") != ",".join(case["event_ids"]) or companion_info.get("usbem_debug_parent_message_keys") != case["key"]:
                raise CheckFailed("debug companion version/parent metadata mismatch")
        self.debug_events.append(debug_id)
        return {"debug_event_sys_id": debug_id, "attachments": downloads}

    def terminal_case(self, state: str):
        payload = self.payload("terminal-" + state)
        case = self.submit(payload)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("terminal fixture did not become processed and linked")
        old_id = case["active_incident"]
        extra = self.fixtures.get("terminal_extra_fields", {})
        if extra:
            row = self.exact("incident", old_id, "sys_id," + ",".join(extra))
            if any(field not in row for field in extra):
                raise MissingFixture("configured terminal u_cause field is absent or unreadable")
        self.patch_owned("incident", old_id, {"state": state,
                         "close_code": self.fixtures.get("terminal_close_code", "Solution provided"),
                         "close_notes": "Retained comprehensive lifecycle fixture " + self.prefix, **extra})
        stored = self.exact("incident", old_id, "sys_id,state," + ",".join(extra))
        self.equal(stored.get("state"), state, "requested terminal state")
        for field, value in extra.items():
            self.equal(stored.get(field), value, "terminal " + field)
        case["terminal"][old_id] = state
        case["was_ready"] = False
        self.submit(payload, existing=case, replace=True)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("replacement did not stabilize")
        replacement_id = case["active_incident"]
        self.submit(payload, existing=case)
        self.settle([case])
        return {"terminal_incident_sys_id": old_id, "terminal_state": state,
                "replacement_incident_sys_id": replacement_id, "third_submission_reused_replacement": True}

    def guard_case(self, closed=False):
        payload = self.payload("closed-alert" if closed else "foreign-alert")
        case = self.submit(payload)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("guard fixture did not become processed and linked")
        if len(case["last_alerts"]) != 1:
            raise CheckFailed("guard requires exactly one owned Alert")
        alert = case["last_alerts"][0]
        note = ""
        if closed:
            info = self.payload_info({"additional_info": alert.get("additional_info", "")})
            if str(info.get("direct_to_incident", "")).lower() not in ("true", "1"):
                raise CheckFailed("closed-Alert fixture lacks the stored DTI metadata needed to exercise the BR condition")
            updates = {"state": self.fixtures.get("alert_closed_state", "Closed"), "incident": ""}
            if "task" in alert:
                updates["task"] = ""
                case["expected_alert_task"] = ""
            self.patch_owned("em_alert", alert["sys_id"], updates)
            case["expected_alert_incident"] = ""
            case["allow_terminal_active"] = True
            # This update itself satisfies the actual BR condition (stored DTI +
            # blank link). Its Closed guard must leave the link blank, without
            # depending on a Table API write to protected additional_info.
        else:
            foreign = self.submit(self.payload("foreign-owner"))
            self.settle([foreign])
            if foreign.get("observation_failed"):
                raise CheckFailed("foreign-owned test fixture did not become processed and linked")
            foreign_id = foreign["active_incident"]
            updates = {"incident": foreign_id}
            if "task" in alert:
                updates["task"] = foreign_id
                case["expected_alert_task"] = foreign_id
            self.patch_owned("em_alert", alert["sys_id"], updates)
            case["expected_alert_incident"] = foreign_id
            link = self.exact("em_alert", alert["sys_id"], self.ALERT_FIELDS)
            self.equal(link.get("incident"), foreign_id, "foreign Incident guard fixture readback")
            if "expected_alert_task" in case:
                self.equal(link.get("task"), foreign_id, "foreign Incident consistent Task fixture readback")
            note = self.prefix + " foreign Incident guard Alert-only note"
            # Event Management owns additional_info; its write ACL can silently
            # ignore a Table API PATCH. Use the supported connector path and prove
            # the pending-note BR really executed rather than merely observing a link.
            self.submit_non_dti_guard_replay(case, note)
        case["was_ready"] = False
        self.settle([case])
        stored = self.exact("em_alert", alert["sys_id"], self.ALERT_FIELDS)
        self.equal(stored.get("incident"), case["expected_alert_incident"], "guarded Alert link")
        if "expected_alert_task" in case:
            self.equal(stored.get("task"), case["expected_alert_task"], "guarded consistent Alert Task link")
        if closed:
            self.equal(stored.get("state"), self.fixtures.get("alert_closed_state", "Closed"), "closed Alert guard state")
            info = self.payload_info({"additional_info": stored.get("additional_info", "")})
            if str(info.get("direct_to_incident", "")).lower() not in ("true", "1"):
                raise CheckFailed("closed-Alert guard lost its stored DTI condition metadata")
        else:
            self.assert_note([alert["sys_id"]], note, 1, "foreign Incident guard Alert note")
            self.assert_note([case["active_incident"], foreign_id], note, 0, "guard note must not copy to either Incident")
            self.assert_consumed_notes([stored])
        return {"alert_sys_id": alert["sys_id"], "expected_incident_sys_id": case["expected_alert_incident"],
                "trigger": "closed state/link update with stored DTI metadata" if closed else "NON-DTI connector replay with unique Alert note"}

    def concurrency_case(self):
        payload = self.payload("concurrency")
        started = self.clock()
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.client.push, self.settings.source, payload,
                                   min(self.settings.request_timeout, self.settings.fast_post_max_seconds)) for _ in range(3)]
            responses, errors = [], []
            for future in futures:
                try:
                    responses.append(future.result())
                except ApiError as error:
                    errors.append(error)
        if errors:
            raise errors[0]
        elapsed = self.clock() - started
        rows = [self.response_rows(response, 1)[0] for response in responses]
        event_ids = [row["event_sys_id"] for row in rows]
        if len(set(event_ids)) != 3:
            raise CheckFailed("parallel submissions reused Event IDs")
        incident_ids = {str(row.get("incident_sys_id", "")) for row in rows}
        if any(not SYS_ID.fullmatch(value) for value in incident_ids):
            raise CheckFailed("parallel fast request did not return a valid Incident")
        case = {"feature": self.current_feature, "name": "concurrency", "key": payload["message_key"],
                "payload": payload, "wire": payload, "expected": self.expected(payload), "expected_event": {},
                "want_incident": True, "want_alert": True, "event_ids": event_ids,
                "incident_ids": incident_ids, "terminal": {}, "active_incident": "", "submissions": [],
                "observations": [], "stable_since": None, "concurrency": True}
        # Allow any returned, correctly correlated open Incident in this accepted race only.
        self.cases.append(case)
        for incident_id in incident_ids:
            self.owned[("incident", incident_id)] = case["key"]
        if elapsed > self.settings.fast_post_max_seconds:
            raise CheckFailed("concurrent fast POST group exceeded prompt-return budget")
        feature = self.features[-1]
        feature["status"] = "known_limitation"
        return {"submissions": 3, "distinct_returned_incidents": len(incident_ids),
                "race_observed": len(incident_ids) > 1,
                "limitation": "No unique claim table: simultaneous first events may create duplicate Incidents; one non-racing run cannot prove concurrency safety."}

    def advanced_case(self, name):
        fixture = self.fixtures.get("advanced_cases", {}).get(name)
        if name == "foreign_task_guard":
            self.require("foreign_task_sys_id")
            return self.foreign_task_case()
        if name == "default_dummy_policy" and self.provisioner is not None:
            if not isinstance(fixture, list) or len(fixture) != 3:
                raise MissingFixture("provisioned default-CI controls need exactly three explicit positive/negative fixtures")
            return self.provisioner.run_default_ci_controls(self, fixture)
        return self.advanced_collection(name, fixture)

    def advanced_collection(self, name, fixture):
        if name in ("offering_parent_filter", "default_dummy_policy") and (not isinstance(fixture, list) or len(fixture) < (2 if name == "offering_parent_filter" else 3)):
            raise MissingFixture(name + " needs multiple positive/negative control fixtures, not one generic Event")
        if isinstance(fixture, list):
            if not fixture:
                raise MissingFixture("advanced_cases." + name + " is empty")
            self.validate_advanced_controls(name, fixture)
            for index, member in enumerate(fixture):
                self.advanced_record(name, member, index)
            return {"configured_subcases": len(fixture)}
        return self.advanced_record(name, fixture)

    def validate_task_fixture(self, record_id):
        if not SYS_ID.fullmatch(record_id):
            raise ValueError("foreign_task_sys_id must be a 32-character sys_id")
        fields = "sys_id,sys_class_name,number,short_description,state,sys_updated_on,sys_mod_count"
        task = self.exact("task", record_id, fields)
        if any(field not in task for field in fields.split(",")):
            raise MissingFixture("foreign Task fixture fields are not readable")
        marker = self.fixtures.get("foreign_task_marker", "[TEST] USBEM")
        if not isinstance(marker, str) or not marker.startswith("[TEST] USBEM") or not task["short_description"].startswith(marker):
            raise MissingFixture("foreign Task fixture must be explicitly marked [TEST] USBEM; no arbitrary Task will be linked")
        if not task["sys_class_name"] or task["sys_class_name"] == "incident":
            raise MissingFixture("foreign Task guard needs a real non-Incident Task, never an Incident")
        if record_id in self.validated_task_fixtures and task != self.validated_task_fixtures[record_id]:
            raise CheckFailed("foreign test Task changed after its baseline; guard fixture no longer safe")
        return task

    def foreign_task_case(self):
        record_id = str(self.fixtures["foreign_task_sys_id"])
        before = self.validate_task_fixture(record_id)
        link_field = self.fixtures.get("foreign_task_link_field", "incident")
        if link_field not in ("incident", "task"):
            raise MissingFixture("foreign Task link must use an actual supported Alert reference field")
        definitions = self.query("sys_dictionary", "name=em_alert^element=" + link_field,
                                 "sys_id,internal_type,reference")
        if (len(definitions) != 1 or definitions[0].get("internal_type") != "reference" or
                definitions[0].get("reference") != "task"):
            raise MissingFixture("foreign Task guard requires a readable Alert field actually referencing Task")
        self.validated_task_fixtures[record_id] = before
        self.validated_task_link_fields.add(link_field)
        payload = self.payload("foreign-task-guard")
        case = self.submit(payload)
        self.settle([case])
        if case.get("observation_failed") or len(case.get("last_alerts", [])) != 1:
            raise CheckFailed("foreign Task guard's owned Alert did not become processed/linked")
        alert = case["last_alerts"][0]
        if link_field not in alert:
            raise MissingFixture("configured Alert Task-reference field is absent or unreadable")
        updates = {link_field: record_id}
        if link_field == "task":
            updates["incident"] = ""
            case["expected_alert_incident"] = ""
            case["expected_alert_task"] = record_id
        else:
            case["expected_alert_incident"] = record_id
        self.patch_owned("em_alert", alert["sys_id"], updates)
        linked = self.exact("em_alert", alert["sys_id"], self.ALERT_FIELDS)
        self.equal(linked.get(link_field), record_id, "foreign Task guard fixture readback")
        note = self.prefix + " foreign Task guard Alert-only note"
        # A pending connector note exercises the actual BR even with a non-empty
        # foreign Task link. Never PATCH the protected additional_info field.
        self.submit_non_dti_guard_replay(case, note)
        case["was_ready"] = False
        self.settle([case])
        stored = self.exact("em_alert", alert["sys_id"], self.ALERT_FIELDS)
        self.equal(stored.get(link_field), record_id, "foreign Task guard link")
        if link_field == "task":
            self.equal(stored.get("incident"), "", "foreign Task guard must not inject an Incident")
        self.assert_note([alert["sys_id"]], note, 1, "foreign Task guard Alert note")
        self.assert_note([case["active_incident"]], note, 0, "foreign Task note must not copy to original Incident")
        self.assert_note([record_id], note, 0, "foreign Task note must not copy to the foreign Task")
        self.assert_consumed_notes([stored])
        after = self.validate_task_fixture(record_id)
        return {"owned_alert_sys_id": alert["sys_id"], "preprovisioned_test_task_sys_id": record_id,
                "task_unchanged": before == after, "task_writes": 0, "alert_link_field": link_field,
                "trigger": "NON-DTI connector replay with unique Alert note"}

    def advanced_payload(self, name, fixture, index=0):
        if not isinstance(fixture, dict) or not isinstance(fixture.get("payload"), dict) or not isinstance(fixture.get("expected_incident"), dict):
            raise MissingFixture("advanced_cases." + name + " needs payload and expected_incident objects")
        payload = self.payload(name)
        for field in fixture.get("remove_fields", []):
            if not isinstance(field, str) or field in ("message_key", "source", "event_class"):
                raise ValueError("advanced remove_fields contains a protected field")
            payload.pop(field, None)
        payload.update(fixture["payload"])
        if any(wrapper in payload and isinstance(payload[wrapper], dict) for wrapper in PAYLOAD_WRAPPERS):
            raise MissingFixture("advanced branch fixtures must be flat; nested wrapper inputs can mask the intended branch")
        # No fixture can inject foreign keys, waits, or arbitrary writable records.
        payload["message_key"] = self.prefix + "-" + name + "-" + str(index)
        payload["source"] = "USBEM Comprehensive Regression"
        if any("wait" in key.lower() for key in payload):
            raise ValueError("legacy wait keys are not permitted in default fixtures")
        return payload

    def advanced_record(self, name, fixture, index=0):
        payload = self.advanced_payload(name, fixture, index)
        if any(not isinstance(fixture.get(flag, True), bool) for flag in ("want_incident", "want_alert")):
            raise MissingFixture("advanced fixture want_incident/want_alert must be JSON booleans")
        if name != "default_dummy_policy" and fixture.get("want_incident", True) is not True:
            raise MissingFixture(name + " requires a real Incident; disabling its creation cannot prove Incident-field behavior")
        self.validate_advanced_fixture(name, payload, fixture)
        case = self.submit(payload, expected=self.expected(payload, **fixture["expected_incident"]),
                           expected_event=fixture.get("expected_event", {}),
                           want_incident=fixture.get("want_incident", True), want_alert=fixture.get("want_alert", True))
        case["expected_additional_info"] = fixture.get("expected_additional_info", {})
        case["absent_additional_info"] = fixture.get("absent_additional_info", [])
        return case

    def validate_advanced_controls(self, name, fixtures):
        if name not in ("offering_parent_filter", "default_dummy_policy"):
            return
        payloads = [self.advanced_payload(name, fixture, index) for index, fixture in enumerate(fixtures)]
        if name == "offering_parent_filter":
            offering_names = {str(payload.get("usbem_offering", "")) for payload in payloads}
            services = {str(payload.get("usbem_service", "")) for payload in payloads}
            outcomes = [fixture["expected_incident"].get("service_offering") for fixture in fixtures]
            if (len(offering_names) != 1 or not next(iter(offering_names)) or len(services) < 2 or "" in services or
                    not any(SYS_ID.fullmatch(str(value or "")) for value in outcomes) or "" not in outcomes):
                raise MissingFixture("offering_parent_filter needs the same offering under different valid parents: one exact positive offering and one blank negative")
            for payload, fixture in zip(payloads, fixtures):
                service_id = fixture["expected_incident"].get("business_service", "")
                if not SYS_ID.fullmatch(str(service_id)):
                    raise MissingFixture("offering parent controls require exact expected business_service IDs")
                self.exact("cmdb_ci_service", str(service_id), "sys_id,name")
                if any(payload.get(key) or self.payload_info(payload).get(key) for key in ("service", "business_service", "service_offering", "serviceOffering")):
                    raise MissingFixture("offering parent controls must not carry stronger direct service/offering passthrough overrides")
                offering_id = fixture["expected_incident"].get("service_offering")
                if offering_id:
                    offering = self.exact("service_offering", str(offering_id), "sys_id,parent,name")
                    if "parent" not in offering or offering["parent"] != service_id:
                        raise MissingFixture("positive offering parent fixture must have the exact configured service as its actual parent")
            return
        properties = self.query("sys_properties", "name=x_usbna_usb_event.default_cmdb_ci_sys_id", "sys_id,name,value")
        if len(properties) != 1 or not SYS_ID.fullmatch(str(properties[0].get("value", ""))):
            raise MissingFixture("positive default/dummy CI route requires an existing non-empty valid configured default CI; negative-only checks cannot sign off this family")
        default_ci = str(properties[0]["value"])
        self.exact("cmdb_ci", default_ci, "sys_id,name")
        branches = set()
        for payload, fixture in zip(payloads, fixtures):
            expected_ci = fixture.get("expected_event", {}).get("cmdb_ci")
            hints = [payload.get(key) for key in ("cmdb_ci", "cmdbCi", "ci_type", "ciType", "ci_identifier", "ciIdentifier")]
            if fixture.get("want_incident", True) or payload.get("direct_to_incident") or payload.get("directToIncident"):
                raise MissingFixture("default/dummy controls must explicitly omit DTI")
            if not any(hints) and (payload.get("node") or payload.get("resource")) and expected_ci == default_ci:
                branches.add("unresolved_hints_use_configured_default")
            elif payload.get("cmdb_ci") and not SYS_ID.fullmatch(str(payload["cmdb_ci"])) and not any(payload.get(key) for key in ("ci_identifier", "ciIdentifier")) and expected_ci == "":
                branches.add("explicit_unresolved_ci_does_not_use_default")
            elif not any(hints) and not payload.get("node") and not payload.get("resource") and expected_ci == "":
                branches.add("no_hints_do_not_use_default")
        if len(branches) != 3:
            raise MissingFixture("default_dummy_policy needs three distinct configured-default / explicit-unresolved / no-hint controls, including the non-empty positive route")

    def validate_advanced_fixture(self, name, payload, fixture):
        """Refuse green labels when fixture defaults would bypass the named branch."""
        expected = fixture["expected_incident"]
        info = self.payload_info(payload)
        hints = ("cmdb_ci", "cmdbCi", "ci_type", "ciType", "ci_identifier", "ciIdentifier")
        no_ci_hints = not any(payload.get(key) or info.get(key) for key in hints)
        valid_ci = SYS_ID.fullmatch(str(expected.get("cmdb_ci", ""))) is not None
        if name == "node_fallback" and (not no_ci_hints or not payload.get("node") or payload.get("resource") or not valid_ci):
            raise MissingFixture("node_fallback must remove all explicit CI hints/resource and specify a real node with expected CI")
        if name == "resource_resolution" and (any(payload.get(key) or info.get(key) for key in ("cmdb_ci", "cmdbCi", "ci_identifier", "ciIdentifier")) or not payload.get("resource") or not valid_ci):
            raise MissingFixture("resource_resolution needs a real resource, no stronger CI identifier/name, and expected CI")
        if name == "additional_info_name_fallback" and (not no_ci_hints or payload.get("node") or payload.get("resource") or not isinstance(info, dict) or not info.get("name") or not valid_ci):
            raise MissingFixture("additional_info_name_fallback needs name-only context without stronger CI/node/resource hints")
        if name == "ci_class_label" and (not payload.get("ci_identifier", payload.get("ciIdentifier")) or not payload.get("ci_type", payload.get("ciType")) or str(payload.get("ci_type", payload.get("ciType"))).startswith("cmdb_ci") or not valid_ci):
            raise MissingFixture("ci_class_label must exercise a human class label and identifier against an expected CI")
        if name == "canonical_ci_name" and (any(payload.get(key) or info.get(key) for key in ("ci_identifier", "ciIdentifier")) or not payload.get("cmdb_ci") or SYS_ID.fullmatch(str(payload.get("cmdb_ci"))) or not valid_ci):
            raise MissingFixture("canonical_ci_name needs a non-sysid display-name variant without a stronger identifier")
        if name == "canonical_ci_name":
            candidate = self.exact("cmdb_ci", expected["cmdb_ci"], "sys_id,name")
            value = self.literal(payload["cmdb_ci"]).strip()
            if "name" not in candidate:
                raise MissingFixture("canonical CI candidate name is not readable")
            if value.casefold() == str(candidate["name"]).strip().casefold() or self.query("cmdb_ci", "name=" + value, "sys_id"):
                raise MissingFixture("canonical CI control must differ beyond case/outer whitespace and must not have an exact-name match")
        if name in ("canonical_group_name", "invalid_group_ci_fallback", "l2_support_group"):
            if not SYS_ID.fullmatch(str(expected.get("assignment_group", ""))):
                raise MissingFixture(name + " requires an exact expected assignment group")
        if name == "canonical_group_name" and (not payload.get("assignment_group") or SYS_ID.fullmatch(str(payload.get("assignment_group")))):
            raise MissingFixture("canonical_group_name must use a display-name variant, not a sys_id")
        if name == "canonical_group_name":
            candidate = self.exact("sys_user_group", expected["assignment_group"], "sys_id,name")
            value = self.literal(payload["assignment_group"]).strip()
            if "name" not in candidate:
                raise MissingFixture("canonical group candidate name is not readable")
            if value.casefold() == str(candidate["name"]).strip().casefold() or self.query("sys_user_group", "name=" + value, "sys_id"):
                raise MissingFixture("canonical group control must differ beyond case/outer whitespace and must not have an exact-name match")
        if name == "invalid_group_ci_fallback" and (not payload.get("assignment_group") or not valid_ci):
            raise MissingFixture("invalid_group_ci_fallback needs an invalid explicit group plus a support-group CI")
        if name == "l2_support_group":
            if payload.get("assignment_group") or not valid_ci:
                raise MissingFixture("l2_support_group must omit the explicit group and use a real L2 CI")
            ci = self.exact("cmdb_ci", expected["cmdb_ci"], "sys_id,support_group,u_level_2_support_assignee_group")
            if "u_level_2_support_assignee_group" not in ci:
                raise MissingFixture("L2 custom field is absent or not readable on this target")
            if ci.get("support_group") or ci.get("u_level_2_support_assignee_group") != expected["assignment_group"]:
                raise MissingFixture("L2 positive fixture needs an empty primary support_group and the configured L2 group")
        if name == "car_id" and (not payload.get("usbem_car_id", payload.get("usbemCarId")) or not SYS_ID.fullmatch(str(fixture.get("expected_additional_info", {}).get("cmdb_ci_business_app", "")))):
            raise MissingFixture("car_id needs a real CAR input and exact business application readback")
        if name == "service_inference" and (any(payload.get(key) or info.get(key) for key in ("service", "business_service", "usbem_service", "usbemService", "usbem_offering", "usbemOffering", "service_offering")) or not SYS_ID.fullmatch(str(expected.get("business_service", "")))):
            raise MissingFixture("service_inference must omit explicit services/offerings and expect a known associated service")
        if name == "offering_parent_filter" and (not payload.get("usbem_service") or not payload.get("usbem_offering") or "service_offering" not in expected):
            raise MissingFixture("offering_parent_filter needs explicit parent service, offering name and exact positive/blank offering result")
        if name == "custom_incident_fields" and not any(key.startswith("u_") and key in payload for key in expected):
            raise MissingFixture("custom_incident_fields needs installed custom fields with supplied and expected stored values")
        if name == "default_dummy_policy" and (fixture.get("want_incident", True) or "cmdb_ci" not in fixture.get("expected_event", {})):
            raise MissingFixture("default_dummy_policy must be a non-DTI Event with explicit CI-or-blank Event expectation")
        if name == "ambiguous_user_rejection" and (not payload.get("assigned_to") or expected.get("assigned_to") != ""):
            raise MissingFixture("ambiguous_user_rejection needs a known ambiguous assignee display name and blank expected assignment")
        if name == "ambiguous_user_rejection":
            matches = self.query("sys_user", "name=" + self.literal(payload["assigned_to"]), "sys_id,name")
            if len(matches) < 2:
                raise MissingFixture("ambiguous assignee control needs at least two existing exact-name users; an unknown or unique name is not an ambiguity test")

    @staticmethod
    def payload_info(payload):
        info = {}
        for key in ("additionalInfo", "additional_info"):
            value = payload.get(key, {})
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = {}
            if isinstance(value, dict):
                info.update(value)
        return info

    def simple_case(self, name, **options):
        changes = options.pop("changes", {})
        remove = options.pop("remove", ())
        payload = self.payload(name, **changes)
        for field in remove:
            payload.pop(field, None)
        expected_changes = options.pop("expected_changes", {})
        expected = self.expected(payload, **expected_changes)
        case = self.submit(payload, expected=expected, **options)
        return case

    def ci_case(self, name, kind, wrapper=""):
        payload = self.payload(name)
        expected_ci = self.settings.expected_id
        if kind == "name":
            payload.pop("ci_type")
            payload.pop("ci_identifier")
            expected_ci = self.settings.decoy_id
        elif kind == "identifier":
            payload.pop("cmdb_ci")
        elif kind == "explicit":
            payload["cmdb_ci"] = self.settings.decoy_id
            expected_ci = self.settings.decoy_id
        elif kind == "camel":
            payload["ciType"] = payload.pop("ci_type")
            payload["ciIdentifier"] = payload.pop("ci_identifier")
            payload["directToIncident"] = payload.pop("direct_to_incident")
        if wrapper:
            payload["work_notes"] = self.prefix + " WRAPPED-" + wrapper
        case = self.submit(payload, wire={wrapper: payload} if wrapper else payload,
                           expected=self.expected(payload, cmdb_ci=expected_ci))
        if kind in ("camel", "snake"):
            self.submit(payload, existing=case)
        return case

    def wrapper_ai_case(self, string=False):
        payload = self.payload("ai-string" if string else "ai-object")
        info = {field: payload.pop(field) for field in ("caller_id", "category", "subcategory")}
        info.update(custom_context={"retained": True, "nested": {"run": self.prefix}})
        payload["additionalInfo"] = json.dumps(info) if string else info
        case = self.submit(payload, wire={"payload": payload}, expected=self.expected(payload))
        case["expected_additional_info"] = {"custom_context": {"retained": True, "nested": {"run": self.prefix}}}
        return case

    def outer_case(self):
        outer = self.payload("outer-authority", cmdb_ci=self.settings.decoy_id)
        inner = self.payload("inner-loses", description="Losing inner description", cmdb_ci=self.settings.expected_id,
                             assignment_group="USBEM-NOT-A-REAL-GROUP")
        inner["message_key"] = outer["message_key"]
        wire = dict(outer, event=inner)
        return self.submit(outer, wire=wire, expected=self.expected(outer, cmdb_ci=self.settings.decoy_id))

    def envelope_case(self):
        payload = self.payload("record-envelope")
        envelope = {"caller_id": self.fixtures["default_caller_sys_id"], "category": "USBEM-NOT-A-CATEGORY",
                    "subcategory": "USBEM-NOT-A-SUBCATEGORY", "dti_impact": "3", "dti_urgency": "3",
                    "records": [{"event": payload}]}
        self.submit(payload, wire=envelope, expected=self.expected(payload, impact="3", urgency="3"))
        # Mapped Event/SPECIAL aliases preserve their root-first selection above. Real
        # Incident passthrough fields, however, must let the individual wrapped record
        # override ordinary Incident defaults supplied by its batch envelope.
        payload = self.payload("record-envelope-incident")
        payload.pop("dti_impact")
        payload.pop("dti_urgency")
        payload.update(impact=self.settings.impact, urgency=self.settings.urgency)
        envelope = {"caller_id": self.fixtures["default_caller_sys_id"], "category": "USBEM-NOT-A-CATEGORY",
                    "subcategory": "USBEM-NOT-A-SUBCATEGORY", "impact": "3", "urgency": "2",
                    "records": [{"event": payload}]}
        self.submit(payload, wire=envelope)
        return {"subcases": 2, "root_special_aliases_preserved": True,
                "wrapped_incident_passthrough_overrides_envelope_defaults": True}

    def severity_case(self, severity):
        name = "severity-" + str(severity)
        payload = self.payload(name, severity=str(severity))
        payload.pop("dti_impact")
        payload.pop("dti_urgency")
        enabled = str(severity) in ("1", "2", "3", "4")
        mapping = self.fixtures.get("severity_map", {"1": ["2", "2"], "2": ["2", "2"], "3": ["3", "3"], "4": ["4", "4"]})
        pair = mapping.get(str(severity), ["", ""])
        expected_severity = "0" if str(severity) == "clear" else "5" if str(severity) == "OK" else str(severity)
        return self.submit(payload, expected=self.expected(payload, impact=str(pair[0]), urgency=str(pair[1])),
                           want_incident=enabled, want_alert=enabled,
                           expected_event={"severity": expected_severity})

    def long_case(self):
        common = self.prefix + "-long-" + "X" * 140
        keys = [common + "A", common + "B"]
        if correlation_key(keys[0]) == correlation_key(keys[1]):
            raise CheckFailed("chosen long-key controls collide; choose different test tails")
        for index, key in enumerate(keys):
            payload = self.payload("long-" + str(index), message_key=key)
            case = self.submit(payload)
            self.submit(payload, existing=case)
        return {"keys_share_first_100_characters": True, "expected_correlations": [correlation_key(key, int(self.fixtures.get("correlation_length", 100))) for key in keys]}

    def parser_case(self):
        # Suppressed events avoid routing defaults obscuring parser assertions.
        payload = self.payload("parser-contract", severity="informational", resolutionState="resolved",
                               timeOfEvent=self.event_time,
                               additional_info={"boolean_value": True, "number_value": 7, "nested": {"value": 1}})
        payload.pop("direct_to_incident")
        case = self.submit(payload, want_incident=False, want_alert=False,
                           expected_event={"severity": "5", "resolution_state": "Closing", "time_of_event": self.event_time})
        case["expected_additional_info"] = {"boolean_value": True, "number_value": 7, "nested": {"value": 1}}
        for suffix, additional_info, expected_info in (
                ("ai-text", "retained scalar context", {"additional_info_text": "retained scalar context"}),
                ("ai-array", [1, True, {"x": 2}], {"additional_info_array": [1, True, {"x": 2}]})):
            payload = self.payload(suffix, severity="5", additional_info=additional_info)
            payload.pop("direct_to_incident")
            created = self.submit(payload, want_incident=False, want_alert=False)
            created["expected_additional_info"] = expected_info
        # Generated keys and defaults are observed in stored Events, not inferred from a response.
        wire = {"source": self.prefix + "-generated-", "node": "node", "type": "type", "resource": "resource", "metric_name": "metric"}
        generated = "".join(wire[field] for field in ("source", "node", "type", "resource", "metric_name"))
        payload = self.payload("generated", message_key=generated)
        self.submit(payload, wire=wire, want_incident=False, want_alert=False,
                    expected_event={"message_key": generated, "event_class": wire["source"], "description": "Generic JSON event", "severity": "5"})
        defaults = self.payload("generic-defaults")
        self.submit(defaults, wire={"message_key": defaults["message_key"]}, want_incident=False, want_alert=False,
                    expected_event={"source": "GenericJSON", "event_class": "GenericJSON", "description": "Generic JSON event", "severity": "5"})
        long_wire = self.payload("truncated-key", severity="5", message_key=self.prefix + "-" + "T" * 1100)
        long_wire.pop("direct_to_incident")
        payload = dict(long_wire, message_key=long_wire["message_key"][:1024])
        self.submit(payload, wire=long_wire, want_incident=False, want_alert=False, expected_event={"message_key": payload["message_key"]})
        overflow = self.payload("ai-overflow", additional_info={"padding_" + str(index): "X" * 180 for index in range(40)})
        created = self.submit(overflow)
        created["expected_additional_info"] = {"cmdb_ci": self.settings.expected_id, "direct_to_incident": "true",
                                                "dti_impact": self.settings.impact, "dti_urgency": self.settings.urgency}
        if self.settings.expected_assignment_group_id:
            created["expected_additional_info"]["assignment_group"] = self.settings.expected_assignment_group_id
        created["additional_info_max_length"] = 4000
        return {"parser_subcases": 7, "generated_keys": True, "generic_defaults": True, "message_key_max_length": 1024, "additional_info_max_length": 4000}

    def event_aliases_case(self):
        payload = self.payload("event-aliases")
        wire = {"source": payload["source"], "eventClass": "USBEM Alias Regression", "hostName": self.prefix + "-alias-node",
                "component": "alias-component", "metric": "alias-metric", "eventType": "alias-type",
                "messageKey": payload["message_key"], "summary": "Retained Event alias contract " + self.prefix,
                "timestamp": self.event_time, "eventState": "active", "severity": "warn",
                "ciType": self.settings.ci_type, "ciIdentifiers": self.settings.identifier,
                "cmdbCi": self.settings.decoy_name, "assignmentGroup": self.settings.assignment_group}
        case = self.submit(payload, wire=wire, want_incident=False,
                           expected_event={"event_class": wire["eventClass"], "node": wire["hostName"], "resource": wire["component"],
                                           "metric_name": wire["metric"], "type": wire["eventType"], "description": wire["summary"],
                                           "severity": "4", "resolution_state": "New", "time_of_event": self.event_time,
                                           "cmdb_ci": self.settings.expected_id})
        case["expected_additional_info"] = {"assignment_group": self.settings.expected_assignment_group_id}
        return case

    def salesforce_case(self):
        # Unique case_number keeps generated key owned without overriding Salesforce defaults.
        payload = {"case_number": self.prefix + "-salesforce", "subject": "Salesforce PERU contract " + self.prefix,
                   "status": "Closed", "created_date": self.event_time, "outage": False}
        key = payload["case_number"]
        expected_payload = self.payload("salesforce", message_key=key)
        case = self.submit(expected_payload, wire=payload, want_incident=False, want_alert=False,
                           expected_event={"source": "salesforce", "event_class": "salesforce", "type": "peru",
                                           "resource": key, "metric_name": "salesforce_case", "severity": "0",
                                           "description": payload["subject"], "resolution_state": "Closing", "time_of_event": self.event_time})
        canonical = dict(payload)
        canonical["case_number"] = self.prefix + "-salesforce-canonical-status"
        canonical["case_status"] = canonical.pop("status")
        self.submit(self.payload("salesforce-canonical", message_key=canonical["case_number"]),
                    wire=canonical, want_incident=False, want_alert=False,
                    expected_event={"source": "salesforce", "event_class": "salesforce", "type": "peru",
                                    "resource": canonical["case_number"], "metric_name": "salesforce_case", "severity": "0",
                                    "description": canonical["subject"], "resolution_state": "Closing", "time_of_event": self.event_time})
        for suffix, subject, count, severity in (("outage", "Major outage retained fixture", 0, "2"),
                                                ("impacted", "Retained affected customer fixture", 5, "2"),
                                                ("minor", "Retained single customer fixture", 1, "3")):
            key = self.prefix + "-salesforce-" + suffix
            wire = {"case_number": key, "subject": subject + " " + self.prefix, "status": "Open",
                    "number_of_customers_impacted": count}
            self.submit(self.payload(suffix, message_key=key), wire=wire, want_incident=False,
                        expected_event={"source": "salesforce", "event_class": "salesforce", "type": "peru",
                                        "resource": key, "metric_name": "salesforce_case", "severity": severity,
                                        "description": wire["subject"], "resolution_state": "New"})
        wire = self.payload("salesforce-explicit", severity="5", case_number=self.prefix + "-ignored-case",
                            subject="Ignored Salesforce default", status="Closed")
        wire.pop("direct_to_incident")
        self.submit(wire, want_incident=False, want_alert=False,
                    expected_event={"source": wire["source"], "event_class": wire["event_class"], "type": wire["type"],
                                    "resource": wire["resource"], "metric_name": wire["metric_name"], "severity": "5", "description": wire["description"]})
        if not self.fixtures.get("offering_name") or not self.fixtures.get("offering_sys_id"):
            raise MissingFixture("Salesforce primary/secondary offering checks require offering_name and offering_sys_id")
        for primary in (True, False):
            key = self.prefix + "-salesforce-offering-" + str(primary)
            wire = {"case_number": key, "subject": "Retained offering fixture " + self.prefix, "status": "Closed",
                    "secondary_offering": self.fixtures["offering_name"] if not primary else self.prefix + "-nonexistent-secondary"}
            if primary:
                wire["primary_offering"] = self.fixtures["offering_name"]
            created = self.submit(self.payload("salesforce-offering", message_key=key), wire=wire, want_incident=False, want_alert=False)
            created["expected_additional_info"] = {"cmdb_ci_service_offering": self.fixtures["offering_sys_id"]}
        return {"salesforce_subcases": 8, "generic_status_and_canonical_case_status_closed": True,
                "primary_over_secondary": True, "explicit_fields_preserved": True}

    def finish_evidence(self):
        # Notes in wrappers must survive Incident passthrough, not merely the HTTP response.
        for case in self.cases:
            if case.get("observation_failed"):
                continue
            if case["feature"].startswith("wrapped_") and case["feature"] in {"wrapped_" + wrapper for wrapper in PAYLOAD_WRAPPERS}:
                try:
                    self.assert_note([case["active_incident"]], case["payload"]["work_notes"], len(case["submissions"]), "wrapped Incident create/replay note")
                except (CheckFailed, ApiError, MissingFixture) as error:
                    self.observation_error(case, error)
            if case.get("expected_additional_info") or case.get("absent_additional_info") or case.get("additional_info_max_length"):
                try:
                    for event in case.get("last_events", []):
                        info = json.loads(event.get("additional_info") or "{}")
                        if case.get("additional_info_max_length") and len(event.get("additional_info") or "") > case["additional_info_max_length"]:
                            raise CheckFailed("stored additional_info exceeded its configured bound")
                        for key, value in case.get("expected_additional_info", {}).items():
                            if key not in info or info[key] != value:
                                raise CheckFailed("stored additional_info lost or changed custom context")
                        if any(key in info for key in case.get("absent_additional_info", [])):
                            raise CheckFailed("stored additional_info contains a key that should have been consumed/absent")
                except (ValueError, TypeError):
                    self.observation_error(case, CheckFailed("stored additional_info is not JSON"))
                except (CheckFailed, ApiError, MissingFixture) as error:
                    self.observation_error(case, error)
        for key in self.negative_keys:
            for table, field in (("em_event", "message_key"), ("incident", "correlation_id"), ("em_alert", "message_key")):
                if self.query(table, field + "=" + key, "sys_id"):
                    raise CheckFailed("invalid batch produced delayed side effects")
        if self.generic_baseline is not None:
            after = self.query("em_event", "message_key=GenericJSONundefinedundefinedundefinedundefined", "sys_id")
            if {row["sys_id"] for row in after} != self.generic_baseline:
                raise CheckFailed("generic undefined-key Event baseline changed during invalid-shape tests")
        else:
            raise MissingFixture("generic undefined-key baseline was unreadable; invalid-shape no-side-effect coverage is incomplete")
        for record_id in self.debug_events:
            deadline = self.clock() + self.settings.timeout
            stable_since = None
            while self.clock() < deadline:
                row = self.exact("em_event", record_id, "sys_id,state,severity,message_key,additional_info")
                if "state" not in row:
                    raise MissingFixture("debug companion state not readable")
                if str(row["state"]).lower() == "processed":
                    stable_since = self.clock() if stable_since is None else stable_since
                    if self.clock() - stable_since >= self.settings.stable_seconds:
                        if "message_key" not in row:
                            raise MissingFixture("debug companion message key is not readable")
                        key = self.literal(row["message_key"])
                        if self.query("em_alert", "message_key=" + key, "sys_id") or self.query("incident", "correlation_id=" + correlation_key(key, int(self.fixtures.get("correlation_length", 100))), "sys_id"):
                            raise CheckFailed("debug companion unexpectedly generated an Alert or Incident")
                        break
                else:
                    stable_since = None
                self.sleep(min(self.settings.poll_seconds, max(0, deadline - self.clock())))
            else:
                raise CheckFailed("debug companion did not remain Processed during stable observation")

    def run(self, progress=None) -> dict:
        self.negative_keys, self.debug_events = [], []
        self.progress = progress or (lambda message: None)
        self.progress("Target " + str(getattr(self.client, "base", "configured instance")) + "; run_id=" + self.run_id)
        self.progress("Running complete manifest; all owned evidence is retained, concurrency limitation is always exercised")
        def preflight():
            self.check_group_fixture()
            checked = []
            for table in ("em_event", "em_alert", "incident", "sys_journal_field", "sys_attachment"):
                self.query(table, "sys_id=00000000000000000000000000000000", "sys_id")
                checked.append(table)
            return {"readable_tables": checked, "qualification": "An empty read proves table access only; populated field ACLs and attachment download access are verified in later features."}
        preflight_result = self.run_feature("read_preflight", preflight)
        if preflight_result["status"] != "pass":
            self.write_stop_reason = "required table-read preflight failed; no test Events submitted"
        # A failed baseline is an explicit incomplete feature, not grounds for a false no-side-effect claim.
        try:
            baseline = self.query("em_event", "message_key=GenericJSONundefinedundefinedundefinedundefined", "sys_id")
            self.generic_baseline = {row["sys_id"] for row in baseline}
        except ApiError as error:
            self.generic_baseline = None
            self.baseline_error = error
        dispatch = []
        for name, kind in (("name_only_control", "name"), ("identifier_only_control", "identifier"),
                           ("explicit_sys_id_precedence", "explicit"), ("fast_camel_conflict", "camel"),
                           ("fast_snake_conflict", "snake")):
            dispatch.append((name, lambda name=name, kind=kind: self.ci_case(name, kind), ()))
        dispatch.extend(("wrapped_" + wrapper, lambda wrapper=wrapper: self.ci_case("wrapped_" + wrapper, "snake", wrapper), ()) for wrapper in PAYLOAD_WRAPPERS)
        dispatch.extend([
            ("wrapped_additional_info_object", lambda: self.wrapper_ai_case(), ()),
            ("wrapped_additional_info_string", lambda: self.wrapper_ai_case(True), ()),
            ("outer_precedence", self.outer_case, ()),
            ("record_envelope_precedence", self.envelope_case, ("default_caller_sys_id",)),
            ("batch_records", lambda: self.batch("records"), ()),
            ("batch_events", lambda: self.batch("events"), ()),
            ("batch_array", lambda: self.batch("array"), ()),
            ("batch_mixed", lambda: self.batch("records", True), ()),
        ])
        invalid_first = [self.payload("bad-records-first"), self.payload("bad-events-first"), self.payload("bad-array-first")]
        probes = [
            ("negative_scalar", 42, "Payload must be", (), False),
            ("negative_null", None, "Payload must be", (), False),
            ("negative_string", "not an object", "Payload must be", (), False),
            ("negative_records_null", {"records": None}, "records must be", (), False),
            ("negative_records_member", {"records": [invalid_first[0], None]}, "index 1", (invalid_first[0]["message_key"],), False),
            ("negative_events_member", {"events": [invalid_first[1], 7]}, "index 1", (invalid_first[1]["message_key"],), False),
            ("negative_array_member", [invalid_first[2], None], "index 1", (invalid_first[2]["message_key"],), False),
            ("negative_records_container", {"records": {}}, "records must be", (), False),
            ("negative_events_container", {"events": "bad"}, "events must be", (), False),
            ("negative_syntax", b'{"records":[', "SyntaxError", (), True),
        ]
        for name, body, message, keys, raw in probes:
            dispatch.append((name, lambda name=name, body=body, message=message, keys=keys, raw=raw: self.negative(name, body, message, keys, raw), ()))
        for severity in ("1", "2", "3", "4", "0", "5", "clear", "OK"):
            dispatch.append(("severity_" + severity, lambda severity=severity: self.severity_case(severity), ()))
        dispatch.extend([
            ("plain_non_dti", lambda: self.simple_case("plain", remove=("direct_to_incident",), want_incident=False), ()),
            ("group_name", lambda: self.simple_case("group-name", changes={"assignment_group": self.fixtures["group_name"]}), ("group_name",)),
            ("caller_assignee_sysid", lambda: self.simple_case("user-ids", changes={"assigned_to": self.fixtures["assignee_sys_id"]}, expected_changes={"assigned_to": self.fixtures["assignee_sys_id"]}), ("assignee_sys_id",)),
            ("caller_assignee_name", lambda: self.simple_case("user-names", changes={"caller_id": self.fixtures["caller_name"], "assigned_to": self.fixtures["assignee_name"]}, expected_changes={"assigned_to": self.fixtures["assignee_sys_id"]}), ("caller_name", "assignee_name", "assignee_sys_id")),
            ("default_caller", lambda: self.simple_case("default-caller", remove=("caller_id",), expected_changes={"caller_id": self.fixtures["default_caller_sys_id"]}), ("default_caller_sys_id",)),
            ("invalid_user_fallback", lambda: self.simple_case("invalid-users", changes={"caller_id": self.prefix + "-missing-user", "assigned_to": self.prefix + "-missing-user"}, expected_changes={"caller_id": self.fixtures["default_caller_sys_id"], "assigned_to": ""}), ("default_caller_sys_id",)),
            ("ci_support_group", lambda: self.simple_case("ci-support", changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]}, remove=("assignment_group", "ci_type", "ci_identifier"), expected_changes={"cmdb_ci": self.fixtures["ci_support_sys_id"], "assignment_group": self.fixtures["ci_support_group_sys_id"]}), ("ci_support_sys_id", "ci_support_group_sys_id")),
            ("explicit_group_override", lambda: self.simple_case("explicit-group", changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]}, remove=("ci_type", "ci_identifier"), expected_changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]}), ("ci_support_sys_id", "ci_support_group_sys_id")),
        ])
        dispatch.extend([
            ("service_sysid", lambda: self.simple_case("service-id", changes={"service": self.fixtures["service_sys_id"], "business_service": self.fixtures["service_sys_id"]}, expected_changes={"business_service": self.fixtures["service_sys_id"]}), ("service_sys_id",)),
            ("offering_sysid", lambda: self.simple_case("offering-id", changes={"service_offering": self.fixtures["offering_sys_id"], "additional_info": {"service_offering": self.fixtures["offering_sys_id"]}}, expected_changes={"service_offering": self.fixtures["offering_sys_id"]}), ("offering_sys_id",)),
        ])
        for feature, key, value_key, stored in (("service_name", "usbem_service", "service_name", "business_service"),
                                                ("offering_name", "usbem_offering", "offering_name", "service_offering")):
            expected_key = "service_sys_id" if stored == "business_service" else "offering_sys_id"
            dispatch.append((feature, lambda feature=feature, key=key, value_key=value_key, stored=stored, expected_key=expected_key: self.simple_case(feature, changes={key: self.fixtures[value_key]}, expected_changes={stored: self.fixtures[expected_key]}), (value_key, expected_key)))
        dispatch.extend([
            ("long_key_reuse", self.long_case, ()), ("debug_success", self.debug_case, ()),
            ("debug_plain", lambda: self.debug_case(plain=True), ()),
            ("debug_error", lambda: self.debug_case(True), ()),
            ("parser_contract", self.parser_case, ()), ("event_aliases", self.event_aliases_case, ()),
            ("salesforce_peru", self.salesforce_case, ()),
            ("scalar_passthrough_and_reserved_fields", self.scalar_reserved_case, ()),
            ("incident_field_defaults", self.incident_defaults_case, ("default_category", "default_subcategory")),
        ])
        dispatch.extend((name, lambda name=name: self.advanced_case(name), ()) for name in ADVANCED_FEATURES)
        for name, callback, required in dispatch:
            self.progress("Submitting " + name)
            feature = self.run_feature(name, callback, required)
            if name in ("name_only_control", "identifier_only_control"):
                controls = [case for case in self.cases if case["feature"] == name]
                self.settle(controls)
                if feature["status"] != "pass" or not controls:
                    self.write_stop_reason = "CI fixture control failed or was unreadable; further test writes stopped"
            pending = feature["status"] == "pass" and any(case["feature"] == name for case in self.cases)
            self.progress(name + ": " + ("submitted/pending stored verification" if pending else feature["status"]))
        self.progress("Observing all independent cases continuously for " + str(self.settings.stable_seconds) + " seconds once ready")
        self.settle()
        # Dependent behavior deliberately waits for the original Alert/Incident link first.
        for name, callback in [("incident_alert_notes", self.notes_case), ("plain_alert_notes", lambda: self.notes_case(True)),
                               ("default_and_duplicate_notes", self.default_notes_case), ("dti_aliases", self.dti_aliases_case),
                               ("generating_alert_reference", lambda: self.incident_default_field_case(True)),
                               ("netcool_ticket_default", self.incident_default_field_case)] + [
                ("terminal_" + state, lambda state=state: self.terminal_case(state)) for state in ("6", "7", "8")] + [
                ("foreign_incident_guard", self.guard_case), ("closed_alert_guard", lambda: self.guard_case(True)),
                ("concurrent_first_events", self.concurrency_case)]:
            self.progress("Running dependent feature " + name)
            self.run_feature(name, callback)
        self.progress("Final cross-feature stable observation and journal/debug/no-side-effect verification")
        self.settle()
        self.run_feature("final_evidence_integrity", self.finish_evidence)
        for name in FEATURE_MANIFEST:
            if not any(item["name"] == name for item in self.features):
                self.features.append({"name": name, "status": "skip", "reason": "declared feature did not execute"})
        result_cases = []
        for case in self.cases:
            result_cases.append({key: value for key, value in case.items() if key in (
                "feature", "name", "key", "event_ids", "active_incident", "submissions", "observations",
                "stable_observed_seconds", "observation_failed", "transient_read_errors") } | {
                    "incident_ids": sorted(case["incident_ids"]), "expected_incident_fields": case["expected"],
                    "expected_event_fields": case["expected_event"]})
        counts = {status: sum(item["status"] == status for item in self.features) for status in ("pass", "fail", "error", "skip", "known_limitation")}
        return {"status": aggregate_status(self.features), "run_id": self.run_id, "expected_release": self.settings.expected_release,
                "test_suite_version": TEST_SUITE_VERSION, "script_sha256": SCRIPT_SHA256,
                "manifest": list(FEATURE_MANIFEST), "features": self.features, "counts": counts, "cases": result_cases,
                "elapsed_seconds": round(self.clock() - self.started, 3), "stable_seconds": self.settings.stable_seconds,
                "phase_timeout_seconds": self.settings.timeout, "post_retries": 0, "records_retained": True,
                "concurrency_included": True, "legacy_wait_included": False,
                "scope": "Declared Generic JSON V2/fast-DTI feature manifest under the actual API identity and configured reference fixtures; not an assertion about arbitrary production business rules, unbounded loads, every possible interleaving, or legacy wait mode.",
                "accepted_residual_limitation": "Simultaneous first events may create duplicate Incidents; no unique claim table was authorized."}

class ProductionRunner(ComprehensiveRunner):
    """Observable end-to-end contract using only Event R, Alert RW and Incident RW.

    Lookup fixtures are target-owner inputs, not records discovered by this identity.
    Administrative proofs are explicitly excluded rather than silently marked passed.
    The transport is independently restricted by ProductionClient in production mode.
    """
    MANIFEST = tuple(name for name in FEATURE_MANIFEST if name != "foreign_task_guard")
    # Optional connector passthrough columns are requested only when a specific
    # case expects them, not assumed to exist on every Event installation.
    EVENT_FIELDS = "sys_id,message_key,source,event_class,node,resource,metric_name,type,state,severity,description,additional_info,resolution_state,time_of_event,cmdb_ci"
    INCIDENT_FIELDS = ComprehensiveRunner.INCIDENT_FIELDS + ",work_notes"
    ALERT_FIELDS = "sys_id,number,message_key,source,event_class,state,incident,additional_info,cmdb_ci,work_notes"
    PATCH_FIELDS = {"incident": {"state", "close_code", "close_notes", "u_cause"},
                    "em_alert": {"state", "incident"}}
    READ_TABLES = frozenset(("em_event", "em_alert", "incident"))
    ATTESTED_FEATURES = frozenset(("canonical_ci_name", "canonical_group_name", "l2_support_group",
                                  "car_id", "service_inference", "offering_parent_filter",
                                  "default_dummy_policy", "ambiguous_user_rejection", "ci_support_group"))
    EVIDENCE_BOUNDARIES = (
        "Only the authenticated identity's visible Event, Alert and Incident records are verified; ACL-hidden rows cannot be ruled out.",
        "Target-specific CI/user/group/service/offerings and configured defaults are owner-supplied expectations, not independently read reference data.",
        "Formatted visible work_notes prove sentinel presence/absence only within that view, not complete raw journal history, exact counts or that a hidden entry never existed.",
        "Debug companion Event, response and parent metadata are checked; attachment existence, names, bytes and JSON contents are not certified.",
        "The foreign-link guard uses two current-run Incidents; non-Incident Task baseline/class/reference-schema protection is not certified.",
        "Installed source, schema, ACLs, cross-scope grants, properties and production fixture provenance are not inspected or changed.",
        "No arbitrary production rule, notification/email policy, unbounded load, every concurrent interleaving or legacy wait mode is certified.",
    )
    EVIDENCE_LIMITS = EVIDENCE_BOUNDARIES

    def __init__(self, client, settings: Settings, fixtures: dict | None = None,
                 monotonic=time.monotonic, sleep=time.sleep) -> None:
        super().__init__(client, settings, fixtures, monotonic, sleep)
        if type(self.fixtures.get("correlation_length", 100)) is not int or self.fixtures.get("correlation_length", 100) != 100:
            raise ValueError("production correlation_length must equal this release's vetted 100-character breadcrumb contract")
        self.note_observations = []
        self.owner_attestations_used = set()
        self.debug_observations = []

    @staticmethod
    def equal(actual, expected, label: str):
        # Raw Table API stored values are strings. Do not collapse JSON false,
        # numeric zero or null into an empty stored field through truthiness.
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise CheckFailed(label + " must compare explicit raw stored-value strings")
        if actual != expected:
            raise CheckFailed(label + " does not equal the configured expected stored value")

    @staticmethod
    def strict_json_equal(actual, expected):
        """Compare JSON types recursively; booleans are never numeric zero/one."""
        if actual is None or expected is None:
            return actual is None and expected is None
        if isinstance(actual, bool) or isinstance(expected, bool):
            return type(actual) is bool and type(expected) is bool and actual == expected
        if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
            # JSON has one number type, so 1 and 1.0 are equivalent numbers;
            # non-finite Python extensions are not valid JSON evidence.
            if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
                return False
            if any(isinstance(value, float) and not math.isfinite(value) for value in (actual, expected)):
                return False
            return actual == expected
        if type(actual) is not type(expected):
            return False
        if isinstance(actual, dict):
            return set(actual) == set(expected) and all(ProductionRunner.strict_json_equal(actual[key], expected[key]) for key in actual)
        if isinstance(actual, list):
            return len(actual) == len(expected) and all(ProductionRunner.strict_json_equal(left, right) for left, right in zip(actual, expected))
        return isinstance(actual, str) and actual == expected

    def finish_evidence(self):
        # Python's ordinary equality treats True == 1 and False == 0, including
        # inside dictionaries/lists. Check native additional_info types before
        # the shared final verifier performs its value and bound checks.
        for case in self.cases:
            if case.get("observation_failed"):
                continue
            try:
                for event in case.get("last_events", []):
                    info = json.loads(event.get("additional_info") or "{}")
                    if not isinstance(info, dict):
                        raise CheckFailed("stored additional_info must be a JSON object")
                    for key, value in case.get("expected_additional_info", {}).items():
                        if key not in info or not self.strict_json_equal(info[key], value):
                            raise CheckFailed("stored additional_info changed a context value or its native JSON type")
            except (ValueError, TypeError):
                self.observation_error(case, CheckFailed("stored additional_info is not valid JSON"))
            except CheckFailed as error:
                self.observation_error(case, error)
        return super().finish_evidence()

    def query(self, table: str, query: str, fields: str, deadline: float | None = None):
        if table not in self.READ_TABLES:
            raise ValueError("production access profile forbids reads outside em_event, em_alert and incident")
        if not isinstance(fields, str):
            raise ValueError("production field requests must be direct technical fields, never dot-walks")
        # The shared observer appends a separator when no extra expectations exist.
        fields = ",".join(dict.fromkeys(field for field in fields.split(",") if field))
        if (not fields or any(not IDENTIFIER_KEY.fullmatch(field) for field in fields.split(","))):
            raise ValueError("production field requests must be direct technical fields, never dot-walks")
        rows = super().query(table, query, fields, deadline)
        # An absent field is different from an empty readable field. Never turn an
        # ACL-trimmed value into a successful blank negative expectation.
        required = set(fields.split(","))
        if any(required - set(row) for row in rows):
            raise MissingFixture(table + " read omitted requested fields; field ACL coverage is incomplete")
        if any(not isinstance(row[field], str) for row in rows for field in required):
            raise ApiError(table + " raw stored fields must be strings; malformed boolean, numeric, null or reference-object values cannot establish evidence")
        return rows

    def snapshot(self, case: dict, deadline: float) -> bool:
        ready = super().snapshot(case, deadline)
        for alert in case.get("last_alerts", []):
            try:
                info = json.loads(alert["additional_info"] or "{}")
            except (ValueError, TypeError):
                raise CheckFailed("stored Alert additional_info is not valid JSON") from None
            if not isinstance(info, dict):
                raise CheckFailed("stored Alert additional_info must be a JSON object")
        if not case["want_alert"] and case.get("last_alerts"):
            raise CheckFailed("a case explicitly requiring no Alert unexpectedly produced an Alert")
        # Fresh non-lifecycle keys must not silently spawn duplicate Alerts. A
        # terminal replay may legitimately retain historical Closed Alerts.
        if case["want_alert"] and not case.get("terminal") and not case.get("concurrency") and len(case.get("last_alerts", [])) > 1:
            raise CheckFailed("a unique non-lifecycle test key produced more than one Alert")
        ci_asserted = "cmdb_ci" in case.get("expected_event", {}) or case["want_incident"] and case["expected"].get("cmdb_ci")
        if ready and ci_asserted:
            expected_ci = case.get("expected_event", {}).get("cmdb_ci", case["expected"].get("cmdb_ci", ""))
            for event in case.get("last_events", []):
                self.equal(event["cmdb_ci"], case.get("expected_event", {}).get("cmdb_ci", expected_ci), "Event CI end-to-end binding")
            for alert in case.get("last_alerts", []):
                self.equal(alert["cmdb_ci"], expected_ci, "Alert CI end-to-end binding")
        return ready

    def exact(self, table: str, record_id: str, fields: str):
        row = super().exact(table, record_id, fields)
        if "sys_id" not in row or str(row["sys_id"]).lower() != record_id.lower():
            raise CheckFailed("exact production read returned a different record identity")
        return row

    def attest(self, name: str):
        attestations = self.fixtures.get("production_attestations", {})
        if not isinstance(attestations, dict) or attestations.get(name) is not True:
            raise MissingFixture("production_attestations." + name +
                                 " must be true after the target owner verifies the otherwise unreadable lookup facts")
        self.owner_attestations_used.add(name)

    def payload(self, name: str, **overrides) -> dict:
        result = super().payload(name, **overrides)
        self.refuse_legacy_wait(result)
        return result

    def preflight(self):
        self.check_group_fixture()
        self.validate_production_catalog()
        checked = []
        event_fields, incident_fields = set(self.EVENT_FIELDS.split(",")), set(self.INCIDENT_FIELDS.split(","))
        incident_fields.update(("u_generating_alert", "u_netcool_ticket", "contact_type", "location", "watch_list"))
        incident_fields.update(self.fixtures.get("terminal_extra_fields", {}))
        for name in ADVANCED_FEATURES:
            if name == "foreign_task_guard":
                continue
            fixture = self.fixtures["advanced_cases"][name]
            for member in fixture if isinstance(fixture, list) else [fixture]:
                if isinstance(member, dict):
                    event_fields.update(member.get("expected_event", {}))
                    incident_fields.update(member.get("expected_incident", {}))
        for table, fields in (("em_event", ",".join(sorted(event_fields))), ("em_alert", self.ALERT_FIELDS),
                              ("incident", ",".join(sorted(incident_fields)))):
            params = {"sysparm_query": "sys_idISNOTEMPTY^ORDERBYDESCsys_created_on", "sysparm_fields": fields,
                      "sysparm_limit": "1", "sysparm_display_value": "false", "sysparm_exclude_reference_link": "true"}
            result = self.client.request("GET", "/api/now/table/" + table + "?" + urllib.parse.urlencode(params),
                                         timeout=self.settings.request_timeout)
            if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                raise ApiError(table + " populated read probe returned an unexpected result shape")
            if len(result) != 1:
                raise MissingFixture(table + " needs one visible populated row to establish field-read access before test writes")
            if set(fields.split(",")) - set(result[0]):
                raise MissingFixture(table + " populated probe omitted required fields; check field read ACLs")
            if any(not isinstance(result[0][field], str) for field in fields.split(",")):
                raise ApiError(table + " populated probe returned non-string raw stored values")
            if not SYS_ID.fullmatch(str(result[0].get("sys_id", ""))):
                raise CheckFailed(table + " populated probe returned an invalid record identity")
            checked.append({"table": table, "populated_field_read": True, "fields": fields.split(",")})
        return {"readable_tables": checked, "schema_or_reference_reads": 0,
                "qualification": "Populated read access, not a role audit. Writes are proven only against newly created current-run records in later lifecycle/guard cases."}

    def validate_production_catalog(self):
        """Fail before the first Event for every statically missing matrix input."""
        required = ("group_name", "assignee_sys_id", "caller_name", "assignee_name", "default_caller_sys_id",
                    "ci_support_sys_id", "ci_support_group_sys_id", "service_sys_id", "service_name", "offering_sys_id",
                    "offering_name", "default_category", "default_subcategory", "default_ci_sys_id")
        self.require(*required)
        for key in ("assignee_sys_id", "default_caller_sys_id", "ci_support_sys_id", "ci_support_group_sys_id", "service_sys_id", "offering_sys_id", "default_ci_sys_id"):
            if not isinstance(self.fixtures[key], str) or not SYS_ID.fullmatch(self.fixtures[key]):
                raise MissingFixture("production fixture " + key + " must be an exact target-specific sys_id")
        for key in ("group_name", "caller_name", "assignee_name", "service_name", "offering_name", "default_category", "default_subcategory"):
            if not isinstance(self.fixtures[key], str) or not self.fixtures[key].strip():
                raise MissingFixture("production fixture " + key + " must be a non-empty target-specific string")
            self.literal(self.fixtures[key])
        if not SYS_ID.fullmatch(str(self.settings.caller_id)) or not SYS_ID.fullmatch(str(self.settings.expected_id)) or not SYS_ID.fullmatch(str(self.settings.decoy_id)):
            raise MissingFixture("production baseline needs exact caller, identifier CI and conflicting-name CI IDs")
        if self.settings.expected_id == self.settings.decoy_id or not self.settings.identifier or not self.settings.decoy_name:
            raise MissingFixture("production CI precedence needs distinct identifier and conflicting-name CIs")
        if self.fixtures["ci_support_group_sys_id"] == self.settings.expected_assignment_group_id:
            raise MissingFixture("production explicit-group override needs a different attested CI support group")
        if not isinstance(self.fixtures.get("duplicate_work_note_enabled", True), bool):
            raise MissingFixture("duplicate_work_note_enabled must be a JSON boolean")
        for key, default in (("terminal_close_code", "Solution provided"), ("alert_closed_state", "Closed")):
            if not isinstance(self.fixtures.get(key, default), str) or not self.fixtures.get(key, default).strip():
                raise MissingFixture(key + " must be a non-empty stored-value string")
        severity_map = self.fixtures.get("severity_map", {"1": ["2", "2"], "2": ["2", "2"], "3": ["3", "3"], "4": ["4", "4"]})
        if (not isinstance(severity_map, dict) or any(not isinstance(severity_map.get(key), (list, tuple)) or
                len(severity_map[key]) != 2 or any(not isinstance(value, str) or not value for value in severity_map[key])
                for key in ("1", "2", "3", "4"))):
            raise MissingFixture("severity_map must give explicit non-empty stored impact/urgency pairs for severities 1 through 4")
        for name in self.ATTESTED_FEATURES:
            self.attest(name)
        advanced = self.fixtures.get("advanced_cases")
        if not isinstance(advanced, dict):
            raise MissingFixture("production advanced_cases must define every advanced matrix family")
        for name in ADVANCED_FEATURES:
            if name == "foreign_task_guard":
                continue
            fixture = advanced.get(name)
            if name in ("offering_parent_filter", "default_dummy_policy") and (not isinstance(fixture, list) or len(fixture) < (2 if name == "offering_parent_filter" else 3)):
                raise MissingFixture(name + " needs the complete positive/negative control collection before any test Events")
            members = fixture if isinstance(fixture, list) else [fixture]
            if not members:
                raise MissingFixture("production advanced_cases." + name + " must not be empty")
            for index, member in enumerate(members):
                if not isinstance(member, dict):
                    raise MissingFixture(name + " advanced control members must be objects")
                remove_fields = member.get("remove_fields", [])
                if not isinstance(remove_fields, list) or any(not isinstance(field, str) or not IDENTIFIER_KEY.fullmatch(field) for field in remove_fields):
                    raise MissingFixture(name + " remove_fields must be an array of technical field names")
                expected_info = member.get("expected_additional_info", {})
                if not isinstance(expected_info, dict) or any(not isinstance(key, str) or not key for key in expected_info):
                    raise MissingFixture(name + " expected_additional_info must be an object with non-empty string keys")
                absent_info = member.get("absent_additional_info", [])
                if not isinstance(absent_info, list) or any(not isinstance(key, str) or not key for key in absent_info):
                    raise MissingFixture(name + " absent_additional_info must be an array of non-empty string keys")
                payload = self.advanced_payload(name, member, index)
                try:
                    json.dumps({"payload": payload, "expected_additional_info": expected_info}, allow_nan=False)
                except (ValueError, TypeError):
                    raise MissingFixture(name + " payload and additional_info expectations must contain valid finite native JSON values") from None
                if any(not isinstance(member.get(flag, True), bool) for flag in ("want_incident", "want_alert")):
                    raise MissingFixture(name + " fixture outcomes must be JSON booleans")
                if name != "default_dummy_policy" and member.get("want_incident", True) is not True:
                    raise MissingFixture(name + " cannot disable its Incident proof")
                expected_event = member.get("expected_event", {})
                if not isinstance(expected_event, dict) or any(not IDENTIFIER_KEY.fullmatch(field) for field in expected_event):
                    raise MissingFixture(name + " expected_event needs direct technical field names")
                if any(not IDENTIFIER_KEY.fullmatch(field) for field in member["expected_incident"]):
                    raise MissingFixture(name + " expected_incident needs direct technical field names")
                if any(not isinstance(value, str) for value in list(member["expected_incident"].values()) + list(expected_event.values())):
                    raise MissingFixture(name + " expected stored fields must be strings: use '0', 'false' or an explicit empty string, never JSON numbers, booleans or null")
                try:
                    complete_expected = self.expected(payload, **member["expected_incident"])
                except (KeyError, TypeError):
                    raise MissingFixture(name + " fixture removed a baseline field needed to build complete Incident expectations") from None
                if any(not isinstance(value, str) for value in complete_expected.values()):
                    raise MissingFixture(name + " complete Incident stored-value expectations must be strings")
                if member.get("want_incident", True) and any(not complete_expected[field].strip() for field in (
                        "caller_id", "category", "subcategory", "impact", "urgency", "short_description", "description")):
                    raise MissingFixture(name + " must expect all seven required Incident fields to be non-empty")
                for field, value in member["expected_incident"].items():
                    if field in ("cmdb_ci", "assignment_group", "assigned_to", "caller_id", "business_service", "service_offering") and value != "" and not SYS_ID.fullmatch(str(value)):
                        raise MissingFixture(name + " expected Incident references must be exact target-specific sys_ids or explicit blanks")
                if "cmdb_ci" in expected_event and expected_event["cmdb_ci"] != "" and not SYS_ID.fullmatch(str(expected_event["cmdb_ci"])):
                    raise MissingFixture(name + " expected Event CI must be an exact target-specific sys_id or an explicit blank")
                self.validate_advanced_fixture(name, payload, member)
            if isinstance(fixture, list):
                self.validate_advanced_controls(name, fixture)

    @staticmethod
    def refuse_legacy_wait(value):
        aliases = {"wait_for_alert", "waitForAlert", "wait_for_incident", "waitForIncident",
                   "usbem_wait_for_alert", "usbemWaitForAlert",
                   "dti_wait_for_alert", "dtiWaitForAlert", "dti_wait_for_incident", "dtiWaitForIncident"}
        if isinstance(value, dict):
            if aliases.intersection(value):
                raise ValueError("legacy wait keys are forbidden in every production payload context")
            for key, member in value.items():
                if key in ("additional_info", "additionalInfo") and isinstance(member, str):
                    try:
                        member = json.loads(member)
                    except ValueError:
                        pass
                ProductionRunner.refuse_legacy_wait(member)
        elif isinstance(value, list):
            for member in value:
                ProductionRunner.refuse_legacy_wait(member)

    def advanced_payload(self, name, fixture, index=0):
        result = super().advanced_payload(name, fixture, index)
        self.refuse_legacy_wait(result)
        # Advanced controls isolate a specific routing branch. Keep their keys
        # canonical so an overlooked stronger alias cannot make a misleading green
        # branch label; the separate alias matrix exercises the public aliases.
        noncanonical = {"ciType", "ciIdentifier", "ci_identifiers", "ciIdentifiers", "cmdbCi",
                        "assignmentGroup", "serviceOffering", "usbemService", "usbemOffering", "directToIncident",
                        "host", "host_name", "hostName", "hostname", "fqdn", "ip", "ip_address", "ipAddress",
                        "ipaddress", "server", "device", "component", "instance", "object", "target"}
        if noncanonical.intersection(result) or noncanonical.intersection(self.payload_info(result)):
            raise MissingFixture("advanced production routing controls must use canonical keys; aliases are exercised by the alias matrix")
        return result

    def patch_owned(self, table: str, record_id: str, updates: dict):
        if table not in self.PATCH_FIELDS or not updates or set(updates) - self.PATCH_FIELDS[table]:
            raise ValueError("production PATCH contains a forbidden table or field")
        # All non-empty incident references must be Incidents created by this run.
        if table == "em_alert" and updates.get("incident") and ("incident", str(updates["incident"])) not in self.owned:
            raise CheckFailed("production Alert PATCH target must be a current-run owned Incident")
        if table == "em_alert" and updates.get("incident"):
            target_id = str(updates["incident"])
            target_key = self.owned[("incident", target_id)]
            if not target_key.startswith(self.prefix):
                raise CheckFailed("production Alert PATCH target lacks current-run ownership")
            target = self.exact("incident", target_id, "sys_id,correlation_id,correlation_display")
            self.equal(target["correlation_id"], correlation_key(target_key, 100), "fresh Alert PATCH target ownership")
            self.equal(target["correlation_display"], "USBEM DTI", "fresh Alert PATCH target provenance")
        return super().patch_owned(table, record_id, updates)

    def journals(self, record_id: str, note: str):
        # This intentionally does NOT emulate sys_journal_field or exact history.
        targets = [table for table in ("incident", "em_alert") if (table, record_id) in self.owned]
        if len(targets) != 1:
            raise CheckFailed("visible work-note target is not uniquely owned by this run")
        table = targets[0]
        ownership = "correlation_id" if table == "incident" else "message_key"
        fields = "sys_id," + ownership + (",correlation_display" if table == "incident" else "")
        row = self.exact(table, record_id, fields)
        key = self.owned[(table, record_id)]
        if not key.startswith(self.prefix):
            raise CheckFailed("visible work-note target lacks current-run ownership")
        self.equal(row[ownership], correlation_key(key, int(self.fixtures.get("correlation_length", 100))) if table == "incident" else key,
                   "visible work-note ownership")
        if table == "incident":
            self.equal(row["correlation_display"], "USBEM DTI", "visible work-note provenance")
        # Journal-input raw values are commonly blank even when the journal has
        # entries. The exact-record formatted view is a supported Table API read
        # on the same owned table, not a sys_journal_field or attachment request.
        params = {"sysparm_fields": "sys_id,work_notes", "sysparm_display_value": "true",
                  "sysparm_exclude_reference_link": "true"}
        displayed = self.client.request("GET", "/api/now/table/" + table + "/" + record_id + "?" +
                                         urllib.parse.urlencode(params), timeout=self.settings.request_timeout)
        if not isinstance(displayed, dict):
            raise ApiError("formatted work-note read returned an unexpected result shape")
        if "sys_id" not in displayed:
            raise MissingFixture("formatted work-note read omitted the record identity; field access is incomplete")
        if str(displayed.get("sys_id", "")).lower() != record_id.lower():
            raise CheckFailed("formatted work-note read returned a different record identity")
        if not isinstance(displayed.get("work_notes"), str) or not displayed["work_notes"].strip():
            raise MissingFixture("formatted visible work_notes is unavailable or empty; neither note presence nor absence can be certified")
        return [{"value": displayed["work_notes"], "table": table, "record_id": record_id,
                 "evidence_view": "exact_owned_record_formatted_work_notes"}]

    def assert_note(self, ids, note, expected, label):
        if not isinstance(note, str) or not note or not isinstance(expected, int) or expected < 0:
            raise ValueError("invalid visible-note assertion")
        rows = [row for record_id in ids for row in self.journals(record_id, note)]
        present = any(note in row["value"].replace("\r\n", "\n") for row in rows)
        self.note_observations.append({"label": label, "record_ids": list(ids),
                                       "note_sha256": hashlib.sha256(note.encode()).hexdigest(),
                                       "expected_visible_presence": expected > 0, "visible_presence": present,
                                       "evidence_view": "exact_owned_record_formatted_work_notes",
                                       "complete_raw_history_verified": False, "exact_history_count_verified": False})
        if present != (expected > 0):
            raise CheckFailed(label + " formatted visible work-note presence differs from expectation (complete raw journal history is not accessed)")

    def notes_case(self, plain=False):
        suffix = "plain-visible-notes" if plain else "visible-notes"
        incident_note, alert_note = self.prefix + " INCIDENT-ONLY", self.prefix + " ALERT-INITIAL"
        payload = self.payload(suffix, work_notes=incident_note, alert_work_notes=alert_note)
        if plain:
            payload.pop("direct_to_incident")
            payload.pop("alert_work_notes")
        case = self.submit(payload, want_incident=not plain)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("visible note fixture did not reach processed/linked state")
        alert_ids = [row["sys_id"] for row in case["last_alerts"]]
        if plain:
            self.assert_note(alert_ids, incident_note, 1, "plain Event note visible on Alert")
            wire = dict(payload)
            wire.pop("work_notes")
            for _ in range(2):
                self.submit(payload, wire=wire, existing=case)
            self.settle([case])
            self.assert_note(alert_ids, incident_note, 1, "plain note remains visible after no-note updates")
            self.assert_consumed_notes(case["last_alerts"])
            return {"visible_plain_note": True, "no_note_updates": 2, "exact_history_count_verified": False}
        self.assert_note([case["active_incident"]], incident_note, 1, "creation Incident note visible")
        self.assert_note(alert_ids, incident_note, 0, "Incident-only sentinel absent from visible Alert note")
        self.assert_note(alert_ids, alert_note, 1, "initial Alert note visible")
        followup = self.prefix + " ALERT-FOLLOWUP-AFTER-LINK"
        wire = dict(payload)
        wire.pop("work_notes")
        wire["alert_work_notes"] = followup
        self.submit(payload, wire=wire, existing=case)
        self.settle([case])
        self.assert_note(alert_ids, followup, 1, "follow-up Alert note visible after link")
        wire.pop("alert_work_notes")
        for _ in range(2):
            self.submit(payload, wire=wire, existing=case)
        self.settle([case])
        self.assert_note(alert_ids, followup, 1, "follow-up remains visible after no-note updates")
        self.assert_note([case["active_incident"]], followup, 0, "Alert-only sentinel absent from visible Incident note")
        self.assert_consumed_notes(case["last_alerts"])
        return {"visible_creation_and_followup_notes": True, "consumed_alert_metadata": True,
                "no_note_updates": 2, "exact_history_count_verified": False}

    def default_notes_case(self):
        payload = self.payload("visible-default-note")
        case = self.submit(payload)
        self.settle([case])
        if case.get("observation_failed"):
            raise CheckFailed("default-note fixture did not stabilize")
        target = [case["active_incident"]]
        creation = "Direct To Incident Via Event Management Generic JSON Endpoint"
        self.assert_note(target, creation, 1, "default creation note visible before replay")
        self.assert_note(target, "Incident Created From " + case["key"], 1, "creation key breadcrumb visible before replay")
        self.submit(payload, existing=case)
        self.settle([case])
        duplicate_enabled = self.fixtures.get("duplicate_work_note_enabled", True)
        if not isinstance(duplicate_enabled, bool):
            raise ValueError("duplicate_work_note_enabled fixture must be a JSON boolean")
        duplicate = "Duplicate event received via Event Management Generic JSON Endpoint (" + case["key"] + ")"
        self.assert_note(target, duplicate, 1 if duplicate_enabled else 0, "visible duplicate-note policy")
        first = self.prefix + " DOCUMENTED-CREATE-NOTE"
        replay = self.prefix + " DOCUMENTED-REPLAY-NOTE"
        alias_payload = self.payload("visible-document-note", dti_work_note=first)
        alias_case = self.submit(alias_payload)
        self.settle([alias_case])
        self.assert_note([alias_case["active_incident"]], first, 1, "documented alias creation sentinel visible")
        wire = dict(alias_payload, dti_work_note=replay)
        self.submit(alias_payload, wire=wire, existing=alias_case)
        self.settle([alias_case])
        self.assert_note([alias_case["active_incident"]], replay, 1, "documented alias replay sentinel visible")
        return {"default_note_and_duplicate_policy_observed": True, "distinct_create_replay_sentinels": True,
                "duplicate_policy_enabled": duplicate_enabled, "exact_history_count_verified": False}

    def dti_aliases_case(self):
        aliases = {"direct_to_incident": "directToIncident", "dti_impact": "dtiImpact",
                   "dti_urgency": "dtiUrgency", "dti_short_description": "dtiShortDescription", "dti_work_note": "dtiWorkNote"}
        for style in ("snake", "camel"):
            creation = self.prefix + " ALIAS-CREATE-" + style
            replay = self.prefix + " ALIAS-REPLAY-" + style
            payload = self.payload("visible-dti-alias-" + style, dti_work_note=creation)
            wire = {aliases.get(key, key) if style == "camel" else key: value for key, value in payload.items()}
            case = self.submit(payload, wire=wire)
            self.settle([case])
            if case.get("observation_failed"):
                raise CheckFailed("DTI alias case did not stabilize")
            self.assert_note([case["active_incident"]], creation, 1, style + " alias creation sentinel visible")
            wire["dtiWorkNote" if style == "camel" else "dti_work_note"] = replay
            self.submit(payload, wire=wire, existing=case)
            self.settle([case])
            self.assert_note([case["active_incident"]], replay, 1, style + " alias replay sentinel visible")
        return {"alias_styles": ["snake", "camel"], "distinct_create_replay_sentinels": True,
                "required_fields_checked": True, "wait_keys_sent": False, "exact_history_count_verified": False}

    def debug_case(self, error=False, plain=False):
        payload = self.payload("debug-error" if error else "debug-plain" if plain else "debug-success", usbem_debug=True)
        if plain:
            payload.pop("direct_to_incident")
        case = None
        if error:
            code, response = self.client.probe(self.settings.source, {"usbem_debug": True, "records": [payload, None]},
                                               self.settings.request_timeout)
            if code not in (400, 500) or not isinstance(response, dict) or response.get("status") != "error" or "index 1" not in response.get("message", ""):
                raise CheckFailed("debug invalid-shape probe did not return the expected error")
            if response.get("version") != self.settings.expected_release:
                raise CheckFailed("debug error response release mismatch")
            self.negative_keys.append(payload["message_key"])
        else:
            case = self.submit(payload, want_incident=not plain)
            response = case["response"]
        debug_id = str(response.get("debug_raw_event_sys_id", ""))
        if not SYS_ID.fullmatch(debug_id):
            raise CheckFailed("debug response did not return a valid companion Event ID")
        event = self.exact("em_event", debug_id, self.EVENT_FIELDS)
        self.equal(event["severity"], "5", "debug companion severity")
        try:
            info = json.loads(event["additional_info"] or "{}")
        except (ValueError, TypeError):
            raise CheckFailed("debug companion metadata is not JSON") from None
        if not isinstance(info, dict):
            raise CheckFailed("debug companion metadata is not an object")
        self.equal(info.get("usbem_version"), self.settings.expected_release, "debug companion version")
        if case is not None:
            self.equal(info.get("usbem_debug_parent_event_sys_ids"), ",".join(case["event_ids"]), "debug parent Event IDs")
            self.equal(info.get("usbem_debug_parent_message_keys"), case["key"], "debug parent key")
        self.debug_events.append(debug_id)
        detail = {"debug_event_sys_id": debug_id, "companion_metadata_verified": True,
                  "response_metadata_verified": True, "attachment_bytes_verified": False,
                  "qualification": "No sys_attachment access or download was attempted."}
        self.debug_observations.append(detail)
        return detail

    def advanced_case(self, name):
        if name == "foreign_task_guard":
            raise MissingFixture("non-Incident Task proof is outside this three-table production profile")
        fixture = self.fixtures.get("advanced_cases", {}).get(name)
        return self.advanced_collection(name, fixture)

    def validate_task_fixture(self, record_id):
        raise ValueError("production profile never reads or links a pre-existing non-Incident Task")

    def foreign_task_case(self):
        raise MissingFixture("non-Incident Task proof requires additional Task/schema read access and is excluded")

    def validate_advanced_controls(self, name, fixtures):
        if name not in ("offering_parent_filter", "default_dummy_policy"):
            return
        self.attest(name)
        payloads = [self.advanced_payload(name, fixture, index) for index, fixture in enumerate(fixtures)]
        if name == "offering_parent_filter":
            offerings = {str(payload.get("usbem_offering", "")) for payload in payloads}
            services = {str(payload.get("usbem_service", "")) for payload in payloads}
            outcomes = [fixture["expected_incident"].get("service_offering") for fixture in fixtures]
            if (len(offerings) != 1 or not next(iter(offerings)) or len(services) < 2 or "" in services or
                    not any(SYS_ID.fullmatch(str(value or "")) for value in outcomes) or "" not in outcomes):
                raise MissingFixture("parent-offering controls need the same offering and different attested parents with exact positive/blank outcomes")
            for payload, fixture in zip(payloads, fixtures):
                if not SYS_ID.fullmatch(str(fixture["expected_incident"].get("business_service", ""))):
                    raise MissingFixture("parent-offering controls require exact expected service IDs")
                if any(payload.get(key) or self.payload_info(payload).get(key) for key in ("service", "business_service", "service_offering", "serviceOffering")):
                    raise MissingFixture("parent-offering controls must not contain stronger direct reference overrides")
            return
        default_ci = str(self.fixtures.get("default_ci_sys_id", ""))
        if not SYS_ID.fullmatch(default_ci):
            raise MissingFixture("default_dummy_policy needs the target owner's attested default_ci_sys_id; no property will be read or changed")
        branches = set()
        for payload, fixture in zip(payloads, fixtures):
            expected_ci = fixture.get("expected_event", {}).get("cmdb_ci")
            info = self.payload_info(payload)
            hints = [payload.get(key) or info.get(key) for key in ("cmdb_ci", "cmdbCi", "ci_type", "ciType", "ci_identifier", "ciIdentifier")]
            if fixture.get("want_incident", True) or payload.get("direct_to_incident") or payload.get("directToIncident") or info.get("direct_to_incident") or info.get("directToIncident"):
                raise MissingFixture("default-CI controls must explicitly omit DTI")
            if not any(hints) and (payload.get("node") or payload.get("resource")) and expected_ci == default_ci:
                branches.add("unresolved_hints_use_attested_default")
            elif payload.get("cmdb_ci") and not SYS_ID.fullmatch(str(payload["cmdb_ci"])) and not any(payload.get(key) for key in ("ci_identifier", "ciIdentifier")) and expected_ci == "":
                branches.add("explicit_unresolved_ci_no_default")
            elif not any(hints) and not payload.get("node") and not payload.get("resource") and expected_ci == "":
                branches.add("no_hints_no_default")
        if len(branches) != 3:
            raise MissingFixture("default-CI controls need positive configured-default, explicit unresolved and no-hints branches")

    def validate_advanced_fixture(self, name, payload, fixture):
        if name in self.ATTESTED_FEATURES:
            self.attest(name)
        expected, info = fixture["expected_incident"], self.payload_info(payload)
        if name == "canonical_ci_name":
            if (any(payload.get(key) or info.get(key) for key in ("ci_identifier", "ciIdentifier")) or
                    not payload.get("cmdb_ci") or SYS_ID.fullmatch(str(payload["cmdb_ci"])) or
                    not SYS_ID.fullmatch(str(expected.get("cmdb_ci", "")))):
                raise MissingFixture("canonical CI needs an attested non-exact name variant without a stronger identifier and an exact expected CI")
            return
        if name == "canonical_group_name":
            if (not payload.get("assignment_group") or SYS_ID.fullmatch(str(payload["assignment_group"])) or
                    not SYS_ID.fullmatch(str(expected.get("assignment_group", "")))):
                raise MissingFixture("canonical group needs an attested non-exact name variant and an exact expected group")
            return
        if name == "l2_support_group":
            if payload.get("assignment_group") or info.get("assignment_group") or info.get("assignmentGroup") or not SYS_ID.fullmatch(str(expected.get("cmdb_ci", ""))) or not SYS_ID.fullmatch(str(expected.get("assignment_group", ""))):
                raise MissingFixture("L2 support needs no explicit group and attested empty primary/non-empty L2 routing facts")
            return
        if name == "ambiguous_user_rejection":
            if not payload.get("assigned_to") or expected.get("assigned_to") != "":
                raise MissingFixture("ambiguous-user control needs an attested ambiguous exact name and a blank expected assignee")
            return
        # The remaining parent validations inspect payloads only; source-table
        # branches above were deliberately handled without invoking their reads.
        return super().validate_advanced_fixture(name, payload, fixture)

    def run(self, progress=None) -> dict:
        self.progress = progress or (lambda message: None)
        self.progress("Target " + str(getattr(self.client, "base", "configured instance")) + "; production three-table run_id=" + self.run_id)
        self.progress("Retaining all test records; no administrator, reference-table, journal-table or attachment access")
        preflight = self.run_feature("read_preflight", self.preflight)
        if preflight["status"] != "pass":
            self.write_stop_reason = "required populated three-table preflight failed; no test Events submitted"
        try:
            self.generic_baseline = {row["sys_id"] for row in self.query("em_event", "message_key=GenericJSONundefinedundefinedundefinedundefined", "sys_id")}
        except (ApiError, MissingFixture) as error:
            self.generic_baseline = None
            self.baseline_error = error
            self.write_stop_reason = "Event no-side-effect baseline was unreadable; no test Events submitted"
        dispatch = []
        for name, kind in (("name_only_control", "name"), ("identifier_only_control", "identifier"), ("explicit_sys_id_precedence", "explicit"),
                           ("fast_camel_conflict", "camel"), ("fast_snake_conflict", "snake")):
            dispatch.append((name, lambda name=name, kind=kind: self.ci_case(name, kind), ()))
        dispatch.extend(("wrapped_" + wrapper, lambda wrapper=wrapper: self.ci_case("wrapped_" + wrapper, "snake", wrapper), ()) for wrapper in PAYLOAD_WRAPPERS)
        dispatch.extend([
            ("wrapped_additional_info_object", self.wrapper_ai_case, ()),
            ("wrapped_additional_info_string", lambda: self.wrapper_ai_case(True), ()),
            ("outer_precedence", self.outer_case, ()), ("record_envelope_precedence", self.envelope_case, ("default_caller_sys_id",)),
            ("batch_records", lambda: self.batch("records"), ()), ("batch_events", lambda: self.batch("events"), ()),
            ("batch_array", lambda: self.batch("array"), ()), ("batch_mixed", lambda: self.batch("records", True), ()),
        ])
        invalid = [self.payload("bad-records-first"), self.payload("bad-events-first"), self.payload("bad-array-first")]
        probes = [
            ("negative_scalar", 42, "Payload must be", (), False), ("negative_null", None, "Payload must be", (), False),
            ("negative_string", "not an object", "Payload must be", (), False), ("negative_records_null", {"records": None}, "records must be", (), False),
            ("negative_records_member", {"records": [invalid[0], None]}, "index 1", (invalid[0]["message_key"],), False),
            ("negative_events_member", {"events": [invalid[1], 7]}, "index 1", (invalid[1]["message_key"],), False),
            ("negative_array_member", [invalid[2], None], "index 1", (invalid[2]["message_key"],), False),
            ("negative_records_container", {"records": {}}, "records must be", (), False),
            ("negative_events_container", {"events": "bad"}, "events must be", (), False),
            ("negative_syntax", b'{"records":[', "SyntaxError", (), True),
        ]
        for name, body, message, keys, raw in probes:
            dispatch.append((name, lambda name=name, body=body, message=message, keys=keys, raw=raw: self.negative(name, body, message, keys, raw), ()))
        dispatch.extend(("severity_" + severity, lambda severity=severity: self.severity_case(severity), ()) for severity in ("1", "2", "3", "4", "0", "5", "clear", "OK"))
        dispatch.extend([
            ("plain_non_dti", lambda: self.simple_case("plain", remove=("direct_to_incident",), want_incident=False), ()),
            ("group_name", lambda: self.simple_case("group-name", changes={"assignment_group": self.fixtures["group_name"]}), ("group_name",)),
            ("caller_assignee_sysid", lambda: self.simple_case("user-ids", changes={"assigned_to": self.fixtures["assignee_sys_id"]}, expected_changes={"assigned_to": self.fixtures["assignee_sys_id"]}), ("assignee_sys_id",)),
            ("caller_assignee_name", lambda: self.simple_case("user-names", changes={"caller_id": self.fixtures["caller_name"], "assigned_to": self.fixtures["assignee_name"]}, expected_changes={"assigned_to": self.fixtures["assignee_sys_id"]}), ("caller_name", "assignee_name", "assignee_sys_id")),
            ("default_caller", lambda: self.simple_case("default-caller", remove=("caller_id",), expected_changes={"caller_id": self.fixtures["default_caller_sys_id"]}), ("default_caller_sys_id",)),
            ("invalid_user_fallback", lambda: self.simple_case("invalid-users", changes={"caller_id": self.prefix + "-missing-user", "assigned_to": self.prefix + "-missing-user"}, expected_changes={"caller_id": self.fixtures["default_caller_sys_id"], "assigned_to": ""}), ("default_caller_sys_id",)),
            ("ci_support_group", self.support_group_case, ("ci_support_sys_id", "ci_support_group_sys_id")),
            ("explicit_group_override", self.explicit_group_case, ("ci_support_sys_id", "ci_support_group_sys_id")),
            ("service_sysid", lambda: self.simple_case("service-id", changes={"service": self.fixtures["service_sys_id"], "business_service": self.fixtures["service_sys_id"]}, expected_changes={"business_service": self.fixtures["service_sys_id"]}), ("service_sys_id",)),
            ("offering_sysid", lambda: self.simple_case("offering-id", changes={"service_offering": self.fixtures["offering_sys_id"], "additional_info": {"service_offering": self.fixtures["offering_sys_id"]}}, expected_changes={"service_offering": self.fixtures["offering_sys_id"]}), ("offering_sys_id",)),
        ])
        for feature, key, value_key, stored in (("service_name", "usbem_service", "service_name", "business_service"), ("offering_name", "usbem_offering", "offering_name", "service_offering")):
            expected_key = "service_sys_id" if stored == "business_service" else "offering_sys_id"
            dispatch.append((feature, lambda feature=feature, key=key, value_key=value_key, stored=stored, expected_key=expected_key: self.simple_case(feature, changes={key: self.fixtures[value_key]}, expected_changes={stored: self.fixtures[expected_key]}), (value_key, expected_key)))
        dispatch.extend([
            ("long_key_reuse", self.long_case, ()), ("debug_success", self.debug_case, ()),
            ("debug_plain", lambda: self.debug_case(plain=True), ()), ("debug_error", lambda: self.debug_case(True), ()),
            ("parser_contract", self.parser_case, ()), ("event_aliases", self.event_aliases_case, ()),
            ("salesforce_peru", self.salesforce_case, ()), ("scalar_passthrough_and_reserved_fields", self.scalar_reserved_case, ()),
            ("incident_field_defaults", self.incident_defaults_case, ("default_category", "default_subcategory")),
        ])
        dispatch.extend((name, lambda name=name: self.advanced_case(name), ()) for name in ADVANCED_FEATURES if name != "foreign_task_guard")
        for name, callback, required in dispatch:
            self.progress("Submitting " + name)
            feature = self.run_feature(name, callback, required)
            if name in ("name_only_control", "identifier_only_control"):
                controls = [case for case in self.cases if case["feature"] == name]
                self.settle(controls)
                if feature["status"] != "pass" or not controls:
                    self.write_stop_reason = "CI reference control failed or was unreadable; further test writes stopped"
            pending = feature["status"] == "pass" and any(case["feature"] == name for case in self.cases)
            self.progress(name + ": " + ("pending stored verification" if pending else feature["status"]))
        self.progress("Observing production outcomes through the actual three-table read identity")
        self.settle()
        dependent = [("incident_alert_notes", self.notes_case), ("plain_alert_notes", lambda: self.notes_case(True)),
                     ("default_and_duplicate_notes", self.default_notes_case), ("dti_aliases", self.dti_aliases_case),
                     ("generating_alert_reference", lambda: self.incident_default_field_case(True)), ("netcool_ticket_default", self.incident_default_field_case)]
        dependent.extend(("terminal_" + state, lambda state=state: self.terminal_case(state)) for state in ("6", "7", "8"))
        dependent.extend((("foreign_incident_guard", self.guard_case), ("closed_alert_guard", lambda: self.guard_case(True)),
                          ("concurrent_first_events", self.concurrency_case)))
        for name, callback in dependent:
            self.progress("Running dependent feature " + name)
            self.run_feature(name, callback)
        self.settle()
        self.run_feature("final_evidence_integrity", self.finish_evidence)
        for name in self.MANIFEST:
            if not any(item["name"] == name for item in self.features):
                self.features.append({"name": name, "status": "skip", "reason": "declared production feature did not execute"})
        result_cases = []
        for case in self.cases:
            result_cases.append({key: value for key, value in case.items() if key in (
                "feature", "name", "key", "event_ids", "active_incident", "submissions", "observations", "stable_observed_seconds", "observation_failed", "transient_read_errors")} | {
                    "incident_ids": sorted(case["incident_ids"]), "expected_incident_fields": case["expected"], "expected_event_fields": case["expected_event"]})
        counts = {status: sum(item["status"] == status for item in self.features) for status in ("pass", "fail", "error", "skip", "known_limitation")}
        return {"status": aggregate_status(self.features), "access_profile": "production", "run_id": self.run_id,
                "expected_release": self.settings.expected_release, "test_suite_version": TEST_SUITE_VERSION,
                "script_sha256": SCRIPT_SHA256, "manifest": list(self.MANIFEST), "features": self.features,
                "counts": counts, "cases": result_cases, "elapsed_seconds": round(self.clock() - self.started, 3),
                "stable_seconds": self.settings.stable_seconds, "phase_timeout_seconds": self.settings.timeout,
                "post_retries": 0, "records_retained": True, "concurrency_included": True, "legacy_wait_included": False,
                "allowed_table_access": {"em_event": ["GET"], "em_alert": ["GET", "PATCH"], "incident": ["GET", "PATCH"]},
                "owner_attestations_used": sorted(self.owner_attestations_used), "visible_note_observations": self.note_observations,
                "debug_observations": self.debug_observations, "evidence_boundaries": list(self.EVIDENCE_BOUNDARIES),
                "excluded_administrative_proofs": ["non_incident_task_guard", "exact_journal_history_counts", "debug_attachment_downloads", "installed_source_schema_security_and_property_readback"],
                "scope": "All declared production-observable Generic JSON V2/fast-DTI cases through only Event R, Alert RW and Incident RW, using owner-supplied target fixtures. Not administrative certification.",
                "accepted_residual_limitation": "Simultaneous first events may create duplicate Incidents; no unique claim table was authorized."}

    def support_group_case(self):
        self.attest("ci_support_group")
        return self.simple_case("ci-support", changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]},
                                remove=("assignment_group", "ci_type", "ci_identifier"),
                                expected_changes={"cmdb_ci": self.fixtures["ci_support_sys_id"], "assignment_group": self.fixtures["ci_support_group_sys_id"]})

    def explicit_group_case(self):
        if self.fixtures["ci_support_group_sys_id"] == self.settings.expected_assignment_group_id:
            raise MissingFixture("explicit-group override needs a CI support group different from the explicit target group")
        self.attest("ci_support_group")
        return self.simple_case("explicit-group", changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]},
                                remove=("ci_type", "ci_identifier"), expected_changes={"cmdb_ci": self.fixtures["ci_support_sys_id"]})

    def severity_case(self, severity):
        case = super().severity_case(severity)
        if str(severity) in ("5", "OK"):
            # Informational/OK suppresses DTI Incident creation, not native Alert
            # creation. A fresh New Event still creates one informational Alert.
            case["want_alert"] = True
        return case

    def batch(self, container: str, mixed=False):
        first = len(self.cases)
        result = super().batch(container, mixed)
        if mixed:
            informational = self.cases[first + 2]
            informational["want_alert"] = True
            informational["expected_event"]["severity"] = "5"
        return result

    def parser_case(self):
        first = len(self.cases)
        result = super().parser_case()
        for case in self.cases[first:]:
            if case["want_incident"] or case["want_alert"]:
                continue
            if case.get("expected_event", {}).get("resolution_state") == "Closing":
                continue
            # The remaining hard-coded parser controls are fresh severity-5/New
            # Events (including absent severity's default), not Alert suppression.
            case["want_alert"] = True
            case["expected_event"].setdefault("severity", "5")
        return result


class LaptopProductionRunner(ProductionRunner):
    """Run the useful core now; report unavailable optional coverage honestly.

    This is the no-argument laptop entry point's production runner. The explicit
    production CLI retains its strict, all-inputs-before-writes preflight. Both
    paths use the same 85 callbacks and independently guarded HTTP transport.
    """
    INCIDENT_FIELDS = ",".join(field for field in ProductionRunner.INCIDENT_FIELDS.split(",")
                               if field not in {"assigned_to", "business_service", "service_offering", "work_notes"})
    ALERT_FIELDS = ",".join(field for field in ProductionRunner.ALERT_FIELDS.split(",") if field != "work_notes")
    EVIDENCE_BOUNDARIES = ProductionRunner.EVIDENCE_BOUNDARIES + (
        "The laptop run continues through available features when optional fixtures or readable fields are missing; any skipped feature makes the aggregate INCOMPLETE, never PASS.",
    )
    EVIDENCE_LIMITS = EVIDENCE_BOUNDARIES
    FIXTURE_IDS = frozenset(("assignee_sys_id", "default_caller_sys_id", "ci_support_sys_id",
                             "ci_support_group_sys_id", "service_sys_id", "offering_sys_id", "default_ci_sys_id"))
    FEATURE_FIELDS = {
        "caller_assignee_sysid": {"incident": {"assigned_to"}},
        "caller_assignee_name": {"incident": {"assigned_to"}},
        "invalid_user_fallback": {"incident": {"assigned_to"}},
        "service_sysid": {"incident": {"business_service"}},
        "service_name": {"incident": {"business_service"}},
        "offering_sysid": {"incident": {"service_offering"}},
        "offering_name": {"incident": {"service_offering"}},
        "scalar_passthrough_and_reserved_fields": {"incident": {"contact_type", "location", "watch_list"}},
        "incident_alert_notes": {"incident": {"work_notes"}, "em_alert": {"work_notes"}},
        "plain_alert_notes": {"em_alert": {"work_notes"}},
        "default_and_duplicate_notes": {"incident": {"work_notes"}},
        "dti_aliases": {"incident": {"work_notes"}},
        "foreign_incident_guard": {"incident": {"work_notes"}, "em_alert": {"work_notes"}},
        "generating_alert_reference": {"incident": {"u_generating_alert"}},
        "netcool_ticket_default": {"incident": {"u_netcool_ticket"}},
    }

    def __init__(self, client, settings: Settings, fixtures: dict | None = None,
                 monotonic=time.monotonic, sleep=time.sleep):
        self.terminal_prerequisite_error = ""
        # Closure-only input is never a reason to prevent safe CI/core tests.
        # Remove invalid extras from the internal copy and gate all terminal
        # callbacks instead; do not mutate the user's catalog or send a fallback.
        safe_fixtures = fixtures
        if isinstance(fixtures, dict):
            extra = fixtures.get("terminal_extra_fields", {})
            if (not isinstance(extra, dict) or set(extra) - {"u_cause"} or
                    any(not isinstance(value, str) or not value.strip() for value in extra.values())):
                safe_fixtures = dict(fixtures)
                safe_fixtures.pop("terminal_extra_fields", None)
                self.terminal_prerequisite_error = "terminal_extra_fields may contain only a non-empty string u_cause; terminal checks were not run"
        super().__init__(client, settings, safe_fixtures, monotonic, sleep)
        self.readable_fields = {table: set() for table in self.READ_TABLES}
        self.optional_field_probes = []

    @staticmethod
    def reject_placeholders(value):
        if isinstance(value, str):
            normalized = re.sub(r"[-\s]+", "_", value.strip().upper())
            if ("REPLACE_WITH" in normalized or "CHANGE_ME" in normalized or
                    normalized.startswith(("YOUR_", "<YOUR", "<REPLACE"))):
                raise MissingFixture("a fixture still contains a template placeholder; fill it in to enable this check")
        elif isinstance(value, dict):
            for key, member in value.items():
                LaptopProductionRunner.reject_placeholders(key)
                LaptopProductionRunner.reject_placeholders(member)
        elif isinstance(value, list):
            for member in value:
                LaptopProductionRunner.reject_placeholders(member)

    def validate_laptop_baseline(self):
        self.check_group_fixture()
        for name in ("caller_id", "expected_id", "decoy_id", "expected_assignment_group_id"):
            if not isinstance(getattr(self.settings, name), str) or not SYS_ID.fullmatch(getattr(self.settings, name)):
                raise MissingFixture("the core test requires a valid " + name + " before sending any Event")
        if self.settings.expected_id == self.settings.decoy_id:
            raise MissingFixture("the core test needs two different CI sys_ids to prove identifier precedence")
        for name in ("source", "ci_type", "decoy_name", "assignment_group", "category", "subcategory", "expected_release",
                     "expected_category", "expected_subcategory", "impact", "urgency"):
            value = getattr(self.settings, name)
            if not isinstance(value, str) or not value.strip():
                raise MissingFixture("the core test requires a non-empty " + name)
            self.literal(value)
            self.reject_placeholders(value)
        if not IDENTIFIER_KEY.fullmatch(self.settings.ci_type):
            raise MissingFixture("the core CI type must be a technical class name")
        identifier = self.settings.identifier
        if (not isinstance(identifier, dict) or not identifier or any(
                not isinstance(key, str) or not IDENTIFIER_KEY.fullmatch(key) or
                isinstance(value, bool) or not isinstance(value, (str, int, float)) or not str(value).strip() or
                isinstance(value, float) and not math.isfinite(value) for key, value in identifier.items())):
            raise MissingFixture("the core test requires a non-empty CI identifier object with valid scalar fields")
        for value in identifier.values():
            self.literal(value)
            self.reject_placeholders(value)
        if self.settings.impact not in ("1", "2", "3", "4") or self.settings.urgency not in ("1", "2", "3", "4"):
            raise MissingFixture("core impact and urgency must be stored numeric choice values 1 through 4")

    def probe_read_fields(self, table, fields):
        requested = set(fields) | {"sys_id"}
        if table not in self.READ_TABLES or any(not isinstance(field, str) or not IDENTIFIER_KEY.fullmatch(field) for field in requested):
            raise MissingFixture("field evidence must use direct fields on the three permitted tables")
        fields = ",".join(sorted(requested))
        params = {"sysparm_query": "sys_idISNOTEMPTY^ORDERBYDESCsys_created_on", "sysparm_fields": fields,
                  "sysparm_limit": "1", "sysparm_display_value": "false", "sysparm_exclude_reference_link": "true"}
        rows = self.client.request("GET", "/api/now/table/" + table + "?" + urllib.parse.urlencode(params),
                                   timeout=self.settings.request_timeout)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ApiError(table + " populated field-read probe returned an invalid response shape")
        if len(rows) != 1:
            raise MissingFixture(table + " needs one visible populated row to check these fields before test writes")
        missing = requested - set(rows[0])
        if missing:
            raise MissingFixture(table + " fields absent or unreadable: " + ", ".join(sorted(missing)) + "; only checks requiring them are unavailable")
        if any(not isinstance(rows[0][field], str) for field in requested):
            raise ApiError(table + " field-read probe returned non-string raw stored values")
        if not SYS_ID.fullmatch(rows[0]["sys_id"]):
            raise CheckFailed(table + " populated field-read probe returned an invalid record identity")
        self.readable_fields[table].update(requested)
        return {"table": table, "populated_field_read": True, "fields": sorted(requested)}

    def preflight(self):
        self.validate_laptop_baseline()
        checked = [self.probe_read_fields(table, fields.split(",")) for table, fields in (
            ("em_event", self.EVENT_FIELDS), ("em_alert", self.ALERT_FIELDS), ("incident", self.INCIDENT_FIELDS))]
        return {"readable_tables": checked, "schema_or_reference_reads": 0, "partial_fixture_mode": True,
                "qualification": "Core inputs and populated field reads checked before writes. Each optional feature separately validates its own fixtures and fields before it can send an Event."}

    def validate_optional_advanced(self, name):
        advanced = self.fixtures.get("advanced_cases", {})
        fixture = advanced.get(name) if isinstance(advanced, dict) else None
        if fixture is None:
            raise MissingFixture("advanced_cases." + name + " is missing; other available checks will still run")
        self.reject_placeholders(fixture)
        if name in ("offering_parent_filter", "default_dummy_policy") and (
                not isinstance(fixture, list) or len(fixture) < (2 if name == "offering_parent_filter" else 3)):
            raise MissingFixture(name + " needs its complete positive/negative control collection")
        members = fixture if isinstance(fixture, list) else [fixture]
        if not members:
            raise MissingFixture(name + " advanced control collection is empty")
        fields = {"incident": set(), "em_event": set()}
        for index, member in enumerate(members):
            if not isinstance(member, dict):
                raise MissingFixture(name + " advanced controls must be objects")
            remove = member.get("remove_fields", [])
            info, absent = member.get("expected_additional_info", {}), member.get("absent_additional_info", [])
            if not isinstance(remove, list) or any(not isinstance(field, str) or not IDENTIFIER_KEY.fullmatch(field) for field in remove):
                raise MissingFixture(name + " remove_fields must contain technical field names")
            if not isinstance(info, dict) or any(not isinstance(key, str) or not key for key in info):
                raise MissingFixture(name + " expected_additional_info must be an object with non-empty string keys")
            if not isinstance(absent, list) or any(not isinstance(key, str) or not key for key in absent):
                raise MissingFixture(name + " absent_additional_info must contain non-empty string keys")
            payload = self.advanced_payload(name, member, index)
            json.dumps({"payload": payload, "expected_additional_info": info}, allow_nan=False)
            if any(not isinstance(member.get(flag, True), bool) for flag in ("want_incident", "want_alert")):
                raise MissingFixture(name + " fixture outcomes must be JSON booleans")
            if name != "default_dummy_policy" and member.get("want_incident", True) is not True:
                raise MissingFixture(name + " cannot disable its Incident proof")
            expected_event, expected_incident = member.get("expected_event", {}), member["expected_incident"]
            for table, expectations in (("em_event", expected_event), ("incident", expected_incident)):
                if not isinstance(expectations, dict) or any(not isinstance(field, str) or not IDENTIFIER_KEY.fullmatch(field) or
                        not isinstance(value, str) for field, value in expectations.items()):
                    raise MissingFixture(name + " expected stored fields must be direct technical names with string values")
                fields[table].update(expectations)
            complete = self.expected(payload, **expected_incident)
            if any(not isinstance(value, str) for value in complete.values()):
                raise MissingFixture(name + " complete Incident expectations must be raw stored-value strings")
            if member.get("want_incident", True) and any(not complete[field].strip() for field in (
                    "caller_id", "category", "subcategory", "impact", "urgency", "short_description", "description")):
                raise MissingFixture(name + " must expect all seven required Incident fields")
            for field, value in expected_incident.items():
                if field in ("cmdb_ci", "assignment_group", "assigned_to", "caller_id", "business_service", "service_offering") and value and not SYS_ID.fullmatch(value):
                    raise MissingFixture(name + " expected references must be exact sys_ids or explicit blanks")
            if expected_event.get("cmdb_ci") and not SYS_ID.fullmatch(expected_event["cmdb_ci"]):
                raise MissingFixture(name + " expected Event CI must be an exact sys_id or explicit blank")
            self.validate_advanced_fixture(name, payload, member)
        if isinstance(fixture, list):
            self.validate_advanced_controls(name, fixture)
        return fields

    def validate_feature_inputs(self, name, required=()):
        # The Salesforce callback also uses these near its end. Validate them
        # before its first subcase, so a partial catalog cannot emit placeholders.
        if name == "salesforce_peru":
            required = tuple(required) + ("offering_name", "offering_sys_id")
        self.require(*required)
        for key in required:
            value = self.fixtures[key]
            self.reject_placeholders(value)
            if not isinstance(value, str) or not value.strip():
                raise MissingFixture(key + " must be a non-empty target-specific string")
            self.literal(value)
            if key in self.FIXTURE_IDS and not SYS_ID.fullmatch(value):
                raise MissingFixture(key + " must be an exact target-specific sys_id")
        fields = {table: set(values) for table, values in self.FEATURE_FIELDS.get(name, {}).items()}
        if name in {"wrapped_" + wrapper for wrapper in PAYLOAD_WRAPPERS}:
            fields["incident"] = {"work_notes"}
        if name in ADVANCED_FEATURES:
            fields = self.validate_optional_advanced(name)
        if name in ("ci_support_group", "explicit_group_override"):
            self.attest("ci_support_group")
            if self.fixtures["ci_support_group_sys_id"] == self.settings.expected_assignment_group_id:
                raise MissingFixture("CI support routing controls need a support group different from the explicit assignment group")
        if name.startswith("severity_"):
            mapping = self.fixtures.get("severity_map", {"1": ["2", "2"], "2": ["2", "2"], "3": ["3", "3"], "4": ["4", "4"]})
            severity = name.removeprefix("severity_")
            pair = mapping.get(severity, ["", ""]) if isinstance(mapping, dict) else None
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(not isinstance(value, str) for value in pair) or
                    severity in ("1", "2", "3", "4") and any(not value.strip() for value in pair)):
                raise MissingFixture(name + " needs an explicit stored impact/urgency pair in severity_map")
            self.reject_placeholders(pair)
        if name == "default_and_duplicate_notes" and not isinstance(self.fixtures.get("duplicate_work_note_enabled", True), bool):
            raise MissingFixture("duplicate_work_note_enabled must be a JSON boolean")
        if name.startswith("terminal_"):
            if self.terminal_prerequisite_error:
                raise MissingFixture(self.terminal_prerequisite_error)
            close_code = self.fixtures.get("terminal_close_code", "Solution provided")
            if not isinstance(close_code, str) or not close_code.strip():
                raise MissingFixture("terminal_close_code must be a non-empty stored-value string")
            self.reject_placeholders(close_code)
            self.reject_placeholders(self.fixtures.get("terminal_extra_fields", {}))
            fields["incident"] = {"state", "close_code", "close_notes"} | set(self.fixtures.get("terminal_extra_fields", {}))
        if name == "closed_alert_guard":
            state = self.fixtures.get("alert_closed_state", "Closed")
            if not isinstance(state, str) or not state.strip():
                raise MissingFixture("alert_closed_state must be a non-empty stored-value string")
            self.reject_placeholders(state)
        return fields

    def run_feature(self, name, callback, required=()):
        def checked_callback():
            if name not in ("read_preflight", "final_evidence_integrity"):
                try:
                    fields = self.validate_feature_inputs(name, required)
                except (ValueError, TypeError, KeyError, IndexError):
                    raise MissingFixture(name + " optional fixture is invalid; correct that feature's fixture to enable its check") from None
                for table, wanted in fields.items():
                    missing = wanted - self.readable_fields[table]
                    if missing:
                        self.optional_field_probes.append(self.probe_read_fields(table, missing))
            return callback()
        return super().run_feature(name, checked_callback, required)

    def run(self, progress=None):
        result = super().run(progress)
        result["laptop_partial_fixture_mode"] = True
        result["optional_field_probes"] = self.optional_field_probes
        return result


def configuration(args, values: dict, *, connection_only=False, environment=None):
    environment = os.environ if environment is None else environment
    slug = re.sub(r"[^A-Za-z0-9]", "", args.profile).upper()
    if args.profile and not slug:
        raise ValueError("--profile must contain at least one ASCII letter or digit")

    def get(key: str, default: str = "") -> str:
        keys = (["USBEM_" + slug + "_" + key.removeprefix("USBEM_")] if slug and key.startswith("USBEM_") else []) + [key]
        for candidate in keys:
            if environment.get(candidate, ""):
                return environment[candidate]
            if values.get(candidate, ""):
                return values[candidate]
        return default

    def secret(key: str) -> str:
        # A profile-specific encoded credential must beat a shared plaintext
        # fallback; do not mix credentials from different target profiles.
        keys = (["USBEM_" + slug + "_" + key.removeprefix("USBEM_")]
                if slug and key.startswith("USBEM_") else []) + [key]
        for candidate in keys:
            plain = environment.get(candidate, "") or values.get(candidate, "")
            encoded = environment.get(candidate + "_B64", "") or values.get(candidate + "_B64", "")
            if plain:
                return plain
            if encoded:
                return decode_b64(encoded, candidate + "_B64")
        return ""

    if args.instance:
        instance = args.instance
        raw_instance = instance
    elif args.profile:
        # A selected profile must never silently run against a shared/default PDI.
        # Treat an explicitly blank process value as disabled, not as permission to
        # fall back to either the env file or an unrelated global URL.
        profile_url_key = "USBEM_" + slug + "_URL"
        profile_url = environment[profile_url_key] if profile_url_key in environment else values.get(profile_url_key, "")
        if not isinstance(profile_url, str) or not profile_url.strip():
            raise ValueError("selected --profile requires non-empty " + profile_url_key + "; no global URL fallback is allowed")
        raw_instance = profile_url
        instance = profile_url.strip()
    else:
        instance = get("SN_INSTANCE_URL")
        raw_instance = instance
    instance = validate_instance(instance)
    client_id = secret("USBEM_OAUTH_CLIENT_ID")
    client_secret = secret("USBEM_OAUTH_CLIENT_SECRET")
    profile_username = secret("USBEM_USERNAME") if args.profile else ""
    profile_password = secret("USBEM_PASSWORD") if args.profile else ""
    username = args.user or profile_username or secret("SN_USERNAME")
    password = args.password or profile_password or secret("SN_PASSWORD")
    if client_id or client_secret:
        if not client_id or not client_secret or args.user or args.password:
            raise ValueError("OAuth needs client ID and secret; do not combine OAuth with Basic CLI credentials")
        auth = {"mode": "oauth", "client_id": client_id, "client_secret": client_secret, "scope": get("USBEM_OAUTH_SCOPE")}
    else:
        if not username or not password or ":" in username:
            raise ValueError("configure Basic username/password or OAuth client ID/secret")
        auth = {"mode": "basic", "username": username, "password": password}
    if getattr(args, "provision_dev_fixtures", False) or getattr(args, "restore_fixture_default_ci", ""):
        validate_fixture_target(raw_instance, getattr(args, "confirm_fixture_target", ""), auth,
                                getattr(args, "insecure", False))
    if connection_only:
        return instance, auth, None
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


def fixture_input(args, values, *, environment=None):
    environment = os.environ if environment is None else environment
    if args.fixture:
        return Path(args.fixture).expanduser().read_text(encoding="utf-8-sig")
    slug = re.sub(r"[^A-Za-z0-9]", "", args.profile).upper()
    keys = (["USBEM_" + slug + "_TEST_FIXTURES_JSON"] if slug else []) + ["USBEM_TEST_FIXTURES_JSON"]
    for key in keys:
        if environment.get(key, ""):
            return environment[key]
        if values.get(key, ""):
            return values[key]
    return "{}"


def validate_catalog_metadata(fixtures, instance):
    if "fixture_catalog" not in fixtures:
        return
    metadata = fixtures["fixture_catalog"]
    if (not isinstance(metadata, dict) or metadata.get("format") != DevFixtureProvisioner.CATALOG_FORMAT or
            metadata.get("target") != instance or metadata.get("namespace") != DEV_FIXTURE_NAMESPACE):
        raise ValueError("generated fixture catalog belongs to another target or has an invalid ownership marker")


def validate_fixture_output(path, instance):
    target = Path(path).expanduser()
    if target.is_symlink():
        raise ValueError("refusing a symlink for generated fixture output")
    if target.exists():
        if not target.is_file():
            raise ValueError("generated fixture output must be a regular file")
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("refusing to overwrite an unrelated fixture-output file") from None
        if not isinstance(existing, dict) or "fixture_catalog" not in existing:
            raise ValueError("refusing to overwrite an unrelated fixture-output file")
        validate_catalog_metadata(existing, instance)


def run_laptop() -> int:
    """One-command entry point; never select connections from process defaults."""
    folder = Path(__file__).resolve().parent
    env_path = folder / "production_test.env"
    fixture_path = folder / "dev-fixtures.json"
    # Accept the spelling used in the original support exchange without asking
    # the operator to rename an already completed file. The canonical name wins.
    if not fixture_path.is_file() and (folder / "dev-fixutres.json").is_file():
        fixture_path = folder / "dev-fixutres.json"
    report_path = folder / ("dti-results-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
                            "-" + uuid.uuid4().hex[:8] + ".json")
    try:
        if not env_path.is_file():
            raise ValueError("Put your completed production_test.env in the same folder as this Python script.")
        if not fixture_path.is_file():
            raise ValueError("Put your completed dev-fixtures.json in the same folder as this Python script.")
        values = read_env(env_path)
        try:
            fixtures = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Fix JSON syntax in {fixture_path.name}, line {error.lineno}, column {error.colno}.") from None
        if not isinstance(fixtures, dict):
            raise ValueError(f"{fixture_path.name} must contain one JSON object.")
        profile = "DEV" if values.get("USBEM_DEV_URL", "").strip() else ""
        instance = validate_instance(values.get("USBEM_DEV_URL" if profile else "SN_INSTANCE_URL", ""))
        if ("replace-with" in instance.casefold() or "replace_with" in instance.casefold() or
                urllib.parse.urlsplit(instance).hostname.casefold().startswith(("your-", "your_"))):
            raise ValueError("Set USBEM_DEV_URL or SN_INSTANCE_URL to your real instance in production_test.env.")
        write_private_json(report_path, {"status": "running", "access_profile": "production",
            "mode": "one_command_laptop", "instance": instance, "test_suite_version": TEST_SUITE_VERSION,
            "script_sha256": SCRIPT_SHA256,
            "qualification": "A running/interrupted report is not a passing result. Retained test records may exist."})
    except (ValueError, OSError, UnicodeError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else "Could not read the configuration files or create the results file. Use a writable private folder."
        print("SETUP NEEDED: " + message)
        print("No test Events were sent.")
        return 3
    print("DTI API test — production-safe mode")
    print("Instance: " + instance)
    print("Using: " + env_path.name + " and " + fixture_path.name)
    print("This run creates retained test Incidents/Alerts; normal platform notifications can run.")
    arguments = ["--access-profile", "production", "--env-file", str(env_path),
                 "--fixture", str(fixture_path), "--report-file", str(report_path)]
    if profile:
        arguments.extend(("--profile", profile))
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            code = main(arguments, laptop=True)
    except KeyboardInterrupt:
        print("STOPPED: test records are retained. The running report is not a pass.")
        print("Results: " + str(report_path))
        return 130
    try:
        report = json.loads(captured.getvalue())
    except (ValueError, TypeError):
        print("ERROR: no complete results summary was produced. The run is not a pass.")
        print("Results: " + str(report_path))
        return 3
    status = str(report.get("status", "error"))
    print("\nRESULT: " + status.upper().replace("_", " "))
    counts = report.get("counts", {})
    if counts:
        print("Checks: " + ", ".join(str(counts.get(key, 0)) + " " + label for key, label in
              (("pass", "passed"), ("fail", "failed"), ("error", "errors"), ("skip", "incomplete"),
               ("known_limitation", "known limitations"))))
    if report.get("reason"):
        print("Setup/error: " + str(report["reason"]))
    problems = [feature for feature in report.get("features", []) if feature.get("status") in ("skip", "fail", "error")]
    if problems:
        print("Items needing attention:")
        for feature in problems:
            print("  " + str(feature.get("name", "check")) + ": " + str(feature.get("reason", feature.get("status", "incomplete"))))
    if status == "incomplete":
        print("Available checks ran; missing prerequisites were not counted as passes.")
    print("Results: " + str(report_path))
    return code


def main(argv=None, *, laptop=False) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return run_laptop()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--access-profile", choices=("comprehensive", "production"), default="comprehensive",
                        help="production enforces connector POST plus Event R / Alert RW / Incident RW only")
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
    parser.add_argument("--include-concurrency", action="store_true", help="compatibility flag; comprehensive default always exercises concurrency")
    parser.add_argument("--fixture", default="", help="path to additional non-secret reference fixture JSON")
    parser.add_argument("--provision-dev-fixtures", action="store_true",
                        help="explicit Basic-admin setup of tagged fixtures and five customer fields in a confirmed DEV PDI, then test")
    parser.add_argument("--confirm-fixture-target", default="",
                        help="exact canonical HTTPS DEV PDI origin; required for all administrative fixture operations")
    parser.add_argument("--prepare-fixtures-only", action="store_true",
                        help="with --provision-dev-fixtures, prepare/read back fixtures without submitting test Events")
    parser.add_argument("--allow-default-ci-property", action="store_true",
                        help="with confirmed DEV setup, permit a journaled temporary default-CI lease only around its three controls")
    parser.add_argument("--fixture-output", default="", help="private generated reference-catalog JSON path for DEV setup")
    parser.add_argument("--fixture-recovery-file", default="",
                        help="private durable recovery journal path; a unique local path is generated if omitted")
    parser.add_argument("--restore-fixture-default-ci", default="", metavar="JOURNAL",
                        help="recover a prior DEV temporary default-CI lease; needs connection credentials but no test fixtures")
    parser.add_argument("--list-tests", action="store_true", help="list the complete feature manifest without reading credentials or contacting an instance")
    parser.add_argument("--plan", action="store_true", help="show read/write scope and prerequisites without reading credentials or contacting an instance")
    args = parser.parse_args(arguments)
    if args.list_tests or args.plan:
        if args.access_profile == "production":
            print(json.dumps({"status": "plan", "access_profile": "production",
                              "features": list(ProductionRunner.MANIFEST), "feature_count": len(ProductionRunner.MANIFEST),
                              "test_suite_version": TEST_SUITE_VERSION, "script_sha256": SCRIPT_SHA256,
                              "network_requests": 0, "writes": 0, "default_suite": "production",
                              "required_reads": ["em_event", "em_alert", "incident"],
                              "deliberate_writes": ["connector POST (one attempt)", "owned Incident lifecycle PATCH", "owned Alert guard PATCH"],
                              "no_direct_event_writes": True, "records_retained": True,
                              "fixture_input": "--fixture JSON path or USBEM_<PROFILE>_TEST_FIXTURES_JSON",
                              "fixture_provisioning": False, "security_or_property_changes": False,
                              "extra_table_reads_or_attachment_downloads": False,
                              "evidence_limits": list(ProductionRunner.EVIDENCE_LIMITS),
                              "missing_fixtures_or_permissions": "INCOMPLETE, never a passing acceptance",
                              "legacy_wait_included": False, "concurrency_always_included": True}, indent=2))
            return 0
        print(json.dumps({"status": "plan", "features": list(FEATURE_MANIFEST), "feature_count": len(FEATURE_MANIFEST),
                          "test_suite_version": TEST_SUITE_VERSION, "script_sha256": SCRIPT_SHA256,
                          "network_requests": 0, "writes": 0, "default_suite": "comprehensive",
                          "required_reads": ["em_event", "em_alert", "incident", "sys_journal_field", "sys_attachment", "attachment/file"],
                          "deliberate_writes": ["inbound_event POST (one attempt)", "owned Incident terminal-state PATCH", "owned Alert guard PATCH"],
                          "fixture_input": "--fixture JSON path or USBEM_TEST_FIXTURES_JSON",
                          "missing_fixtures_or_permissions": "skip feature and exit4 incomplete",
                          "records_retained": True, "normal_test_no_service_email_schema_security_or_delete": True,
                          "normal_test_write_boundary": "No schema/security/fixture setup; only connector POSTs and owned lifecycle/Alert PATCHes",
                          "explicit_dev_fixture_setup": {
                              "flag": "--provision-dev-fixtures", "target_confirmation": "--confirm-fixture-target exact HTTPS dev<digits>.service-now.com",
                              "identity": "Basic admin with verified TLS", "prepare_only": "--prepare-fixtures-only",
                              "writes": ["five allowlisted Global customer u_* fields if absent", "tagged users/groups/Task", "IRE-simulated tagged CMDB fixtures and owned service association"],
                              "temporary_default_ci": "Only with --allow-default-ci-property, durable private journal, three-control observation and guarded restoration",
                              "recovery": "--restore-fixture-default-ci JOURNAL; original value or absence must be verified",
                              "new_tables_or_security_grants": False,
                          },
                          "legacy_wait_included": False, "concurrency_always_included": True}, indent=2))
        return 0
    provisioner = None
    report_output_allowed = True
    try:
        if laptop and args.access_profile != "production":
            raise ValueError("the one-command laptop test only permits production-safe access")
        if args.access_profile == "production" and any((args.provision_dev_fixtures, args.confirm_fixture_target,
                args.prepare_fixtures_only, args.allow_default_ci_property, args.fixture_output,
                args.fixture_recovery_file, args.restore_fixture_default_ci)):
            raise ValueError("production access profile cannot be combined with DEV administration or fixture/property provisioning flags")
        if args.report_file:
            report_path = Path(args.report_file).expanduser().resolve()
            protected_paths = [args.env_file, args.fixture, args.fixture_output, args.fixture_recovery_file, args.restore_fixture_default_ci]
            if any(path and Path(path).expanduser().resolve() == report_path for path in protected_paths):
                report_output_allowed = False
                raise ValueError("report output must not overwrite configuration, fixture input, or a recovery journal")
        recovery = bool(args.restore_fixture_default_ci)
        if recovery and (args.provision_dev_fixtures or args.prepare_fixtures_only or args.allow_default_ci_property or args.fixture_output):
            raise ValueError("recovery cannot be combined with fixture provisioning or property activation")
        if not args.provision_dev_fixtures and not recovery and any((args.prepare_fixtures_only, args.allow_default_ci_property,
                                                                   args.fixture_output, args.fixture_recovery_file, args.confirm_fixture_target)):
            raise ValueError("administrative fixture flags require --provision-dev-fixtures or the explicit recovery mode")
        values = read_env(Path(args.env_file).expanduser())
        connection_options = {"environment": {}} if laptop else {}
        instance, auth, settings = configuration(args, values, connection_only=recovery, **connection_options)
        ca_bundle = args.ca_bundle or ("" if laptop else os.environ.get("USBEM_CA_BUNDLE", "")) or values.get("USBEM_CA_BUNDLE", "")
        client_type = ProductionClient if args.access_profile == "production" else Client
        client = client_type(instance, auth, ca_bundle, args.insecure)
        if recovery:
            provisioner = DevFixtureProvisioner(client, None, args.confirm_fixture_target,
                                               args.restore_fixture_default_ci, ca_bundle=ca_bundle)
            result = provisioner.recover(args.restore_fixture_default_ci)
            if not isinstance(result, dict) or result.get("restored") is not True:
                raise ApiError("default CI recovery was not verified")
            report = {"status": "pass", "mode": "fixture_default_ci_recovery", "recovery": result,
                      "fixture_setup": provisioner.info}
        else:
            try:
                fixtures = json.loads(fixture_input(args, values, **connection_options))
            except ValueError:
                raise ValueError("test fixture input must be a JSON object") from None
            if not isinstance(fixtures, dict):
                raise ValueError("test fixture input must be a JSON object")
            validate_catalog_metadata(fixtures, instance)
            if args.provision_dev_fixtures:
                recovery_path = args.fixture_recovery_file or str(Path(args.report_file).expanduser().parent /
                    ("dti-default-ci-recovery-" + uuid.uuid4().hex + ".json"))
                catalog_path = args.fixture_output or str(Path(args.report_file).expanduser().parent / "dti-reference-fixtures.json")
                distinct = [Path(path).expanduser().resolve() for path in (recovery_path, catalog_path, args.report_file) if path]
                if len(distinct) != len(set(distinct)) or any(
                        Path(path).expanduser().resolve() == Path(args.env_file).expanduser().resolve()
                        for path in (recovery_path, catalog_path)):
                    report_output_allowed = False
                    raise ValueError("fixture catalog, recovery journal, report and env paths must be distinct")
                validate_fixture_output(catalog_path, instance)
                provisioner = DevFixtureProvisioner(client, settings, args.confirm_fixture_target, recovery_path,
                                                   fixtures=fixtures, ca_bundle=ca_bundle,
                                                   allow_default_ci_property=args.allow_default_ci_property)
                print("Preparing confirmed DEV fixtures; no production setup is permitted", file=sys.stderr, flush=True)
                fixtures = provisioner.provision()
                write_private_json(catalog_path, fixtures)
                provisioner.info["fixture_catalog_file"] = str(Path(catalog_path).expanduser())
            if args.prepare_fixtures_only:
                report = {"status": "pass", "mode": "prepare_dev_fixtures_only", "test_events_submitted": 0,
                          "fixture_setup": provisioner.info}
            else:
                runner_options = {"provisioner": provisioner} if provisioner is not None else {}
                runner_type = LaptopProductionRunner if laptop else ProductionRunner if args.access_profile == "production" else ComprehensiveRunner
                report = runner_type(client, settings, fixtures, **runner_options).run(
                    lambda message: print(message, file=sys.stderr, flush=True))
                if provisioner is not None:
                    report["fixture_setup"] = provisioner.info
                    if provisioner.info.get("restoration_error"):
                        report["status"] = "error"
        report.update(instance=instance, auth_mode=auth["mode"], tls_verified=not args.insecure)
        if args.access_profile == "production":
            report["transport_boundary"] = {"allowed_table_reads": sorted(ProductionClient.TABLES),
                "direct_event_writes": False, "attachment_downloads": False, "admin_operations": False,
                "operation_counts": dict(client.operation_counts)}
    except (ValueError, OSError, ApiError) as error:
        # Only our controlled configuration/API messages are printed; never raw HTTP bodies.
        message = str(error) if isinstance(error, (ValueError, ApiError)) else "could not read or write configuration, fixture state, or CA bundle"
        report = {"status": "error", "reason": message}
        if provisioner is not None:
            report["fixture_setup"] = provisioner.info
    report.update(test_suite_version=TEST_SUITE_VERSION, script_sha256=SCRIPT_SHA256, access_profile=args.access_profile)
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.report_file and report_output_allowed:
        try:
            write_private_json(args.report_file, report)
        except (OSError, ValueError):
            print("Could not write JSON report file", file=sys.stderr)
            return 3
    print(output)
    return {"pass": 0, "complete_with_known_limitations": 0, "fail": 2, "error": 3, "incomplete": 4}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
