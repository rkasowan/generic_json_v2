#!/usr/bin/env python3
"""USBEM genericJsonV2 — API functionality test, in one file.

Tests the inbound event API and nothing else. It writes only uniquely tagged events, alerts,
and incidents. Standard profile attempts cleanup; limited production profile retains its records
because the caller may not have delete access. It does not modify CMDB records or configuration.

Copy this file anywhere and run it. Standard library only; if `requests` happens to be
installed it is used, because it carries its own CA bundle, but it is not required.

    python3 usbem_verify.py --instance https://xxx.service-now.com --user admin --password '...'
    python3 usbem_verify.py --only fast --only notes
    python3 usbem_verify.py --source firstGenericJson --contract legacy --only compat
    python3 usbem_verify.py --access-profile limited
    python3 usbem_verify.py --keep                # leave the records it creates
    python3 usbem_verify.py --json out.json       # machine-readable results

Credentials, in order of preference: --instance/--user/--password; the environment
(servicenow_instance / servicenow_user / servicenow_password, or SN_INSTANCE_URL / SN_USERNAME
/ SN_PASSWORD); a .env named by --env-file, or the nearest one at or above the working
directory.

Terminal incident transitions use only the caller's Incident API access. If an ACL blocks a
transition, that state case is reported as skipped; the verifier never uses Scripts - Background.

TLS: certificates are verified. If you see CERTIFICATE_VERIFY_FAILED, either
`pip install certifi`, or pass --ca-bundle /path/root.pem for a corporate root, or --insecure.

Use --source to select a different push connector. For the original PDI listener, run
`--source firstGenericJson --contract legacy --only compat`. Production instances can use the
same command with their original listener source value. The default source is `genericJsonV2`.

For restricted production users, `--access-profile limited` runs only compat and fast checks,
uses Incident/Alert readback, avoids Scripts - Background, and retains created records because
delete access is not assumed. The script prints the prefix used to tag them.

GROUPS (--only <name>, repeatable):
    compat   response envelope, event row, alert, no incident without DTI, batches, and the
             modern listener's legacy dti_ field aliases; legacy mode tests original event/batch
             compatibility without modern-only DTI assertions
    fast     direct_to_incident returns an incident immediately, reuses it while open, opens a
             new one once it is Resolved/Closed/Canceled, and the Business Rule links the alert
    fields   what lands on the incident: NetCool, category, subcategory, caller, the severity
             tiers, u_generating_alert, and every payload override
    notes    work notes on the incident and on the alert, and that a note is not re-posted
    edge     message keys longer than correlation_id, concurrent events, DTI inside a batch
    timing   round-trip milliseconds per path, reported not failed
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path

VERSION = "2026.09.28.1"
EXPECTED_RELEASE = "2026.09.28.1"      # what the live endpoint should report; --expect-version overrides

MARK = "@@JSON@@"
TERMINAL_STATES = (("6", "Resolved"), ("7", "Closed"), ("8", "Canceled"))
GROUPS = ("compat", "fast", "fields", "notes", "edge", "timing")
DEFAULT_SOURCE = "genericJsonV2"

INSTANCE_KEYS = ("servicenow_instance", "SN_INSTANCE_URL", "SN_INSTANCE", "instance")
USER_KEYS = ("servicenow_user", "SN_USERNAME", "SN_USER", "user")
PASSWORD_KEYS = ("servicenow_password", "SN_PASSWORD", "password")

# Optional: only used if it is installed. requests ships a CA bundle, which is the usual cure for
# certificate failures on macOS.
try:
    import requests  # type: ignore
except ImportError:
    requests = None

try:
    import certifi  # type: ignore
except ImportError:
    certifi = None


# --------------------------------------------------------------------------------- credentials
def parse_env_file(path: Path) -> dict:
    values = {}
    for raw in path.read_text(errors="replace").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def nearest_env_file(start: Path) -> dict:
    for folder in [start] + list(start.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return parse_env_file(candidate)
    return {}


def resolve_credentials(args) -> tuple:
    sources = []
    if args.instance and args.user and args.password:
        return args.instance.rstrip("/"), args.user, args.password
    sources.append(dict(os.environ))
    if args.env_file:
        named = Path(args.env_file).expanduser()
        if not named.is_file():
            sys.exit(f"--env-file {named} does not exist")
        sources.append(parse_env_file(named))
    sources.append(nearest_env_file(Path.cwd()))
    sources.append(nearest_env_file(Path(__file__).resolve().parent))

    def first(keys, override):
        if override:
            return override
        for key in keys:
            for source in sources:
                if source.get(key):
                    return source[key]
        return ""

    instance = first(INSTANCE_KEYS, args.instance).rstrip("/")
    user = first(USER_KEYS, args.user)
    password = first(PASSWORD_KEYS, args.password)
    missing = [name for name, value in
               (("instance", instance), ("user", user), ("password", password)) if not value]
    if missing:
        sys.exit("missing credentials: " + ", ".join(missing) + "\n"
                 "  pass --instance/--user/--password, set servicenow_instance / servicenow_user /\n"
                 "  servicenow_password in the environment, or point --env-file at a .env")
    if not instance.startswith("http"):
        instance = "https://" + instance
    return instance, user, password


# --------------------------------------------------------------------------------- HTTP client
class ServiceNowError(RuntimeError):
    pass


class ServiceNow:
    """Table API, the inbound event endpoint, and a background-script runner."""

    def __init__(self, instance: str, user: str, password: str,
                 ca_bundle: str = "", insecure: bool = False, timeout: int = 180) -> None:
        self.instance = instance
        self.user = user
        self.password = password
        self.timeout = timeout
        self.insecure = insecure
        self.ca_bundle = ca_bundle
        self.context = self._ssl_context()
        self._session = None
        if requests is not None:
            self._session = requests.Session()
            self._session.auth = (user, password)
            self._session.verify = False if insecure else (ca_bundle or (certifi.where() if certifi else True))
            if insecure:
                try:
                    import urllib3  # type: ignore
                    urllib3.disable_warnings()
                except Exception:
                    pass
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._basic = "Basic " + token
        self._opener = None
        self._ck = ""

    def _ssl_context(self):
        if self.insecure:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        if self.ca_bundle:
            return ssl.create_default_context(cafile=self.ca_bundle)
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    # ---- one request, either transport
    def _request(self, method: str, url: str, params=None, body=None, headers=None):
        headers = dict(headers or {})
        headers.setdefault("Accept", "application/json")
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        last = None
        for attempt in range(3):
            try:
                if self._session is not None:
                    response = self._session.request(method, url, data=data, headers=headers,
                                                     timeout=self.timeout)
                    status, text = response.status_code, response.text
                else:
                    headers["Authorization"] = self._basic
                    request = urllib.request.Request(url, data=data, method=method, headers=headers)
                    with urllib.request.urlopen(request, timeout=self.timeout,
                                                context=self.context) as raw:
                        status, text = raw.status, raw.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as error:
                status = error.code
                text = error.read().decode("utf-8", "replace")
                break
            except Exception as error:                       # transport, not HTTP
                message = str(error)
                if "CERTIFICATE_VERIFY_FAILED" in message or "certificate verify failed" in message:
                    raise ServiceNowError(
                        f"TLS verification failed for {url}\n"
                        f"  {message}\n"
                        "  pip install certifi        (usual fix on macOS)\n"
                        "  --ca-bundle /path/root.pem to trust a corporate root\n"
                        "  --insecure                 to skip verification, last resort") from None
                last = error
                time.sleep(2 * (attempt + 1))
        else:
            raise ServiceNowError(f"{method} {url} failed after 3 attempts: {last}")

        if status >= 400:
            raise ServiceNowError(f"{method} {url} -> HTTP {status}: {text[:400]}")
        if not text.strip():
            return None
        try:
            parsed = json.loads(text)
        except ValueError:
            return text
        return parsed.get("result", parsed) if isinstance(parsed, dict) else parsed

    # ---- Table API
    def table(self, name: str, query: str, fields: str, limit: int = 50, display: str = "false"):
        return self._request("GET", f"{self.instance}/api/now/table/{name}", params={
            "sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": str(limit),
            "sysparm_display_value": display, "sysparm_exclude_reference_link": "true",
        }) or []

    def record(self, name: str, sys_id: str, fields: str, display: str = "false"):
        return self._request("GET", f"{self.instance}/api/now/table/{name}/{sys_id}", params={
            "sysparm_fields": fields, "sysparm_display_value": display,
            "sysparm_exclude_reference_link": "true",
        }) or {}

    def update(self, name: str, sys_id: str, payload: dict):
        return self._request("PATCH", f"{self.instance}/api/now/table/{name}/{sys_id}", body=payload) or {}

    def delete(self, name: str, sys_id: str):
        self._request("DELETE", f"{self.instance}/api/now/table/{name}/{sys_id}")

    def push_event(self, payload, source: str = "genericJsonV2") -> dict:
        """POST to the push connector endpoint exactly as a real sender would."""
        result = self._request("POST", f"{self.instance}/api/sn_em_connector/em/inbound_event",
                               params={"source": source}, body=payload,
                               headers={"user-agent": "genericendpoint"})
        return self._unwrap(result)

    @staticmethod
    def _unwrap(result) -> dict:
        """The endpoint answers {"<listener name>": "<json the listener returned>"}."""
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                return {"raw": result}
        if isinstance(result, dict) and "status" not in result and len(result) == 1:
            inner = next(iter(result.values()))
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    return {"raw": inner}
            if isinstance(inner, dict):
                return inner
        return result if isinstance(result, dict) else {"raw": result}

    # ---- background scripts, for the things the Table API will not do
    def _login(self) -> None:
        jar = CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(jar)]
        if not self.insecure or True:
            handlers.append(urllib.request.HTTPSHandler(context=self.context))
        opener = urllib.request.build_opener(*handlers)
        form = urllib.parse.urlencode({
            "user_name": self.user, "user_password": self.password, "sys_action": "sysverb_login",
        }).encode()
        opener.open(urllib.request.Request(
            self.instance + "/login.do", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=60).read()
        page = opener.open(self.instance + "/sys.scripts.do", timeout=60).read().decode("utf-8", "replace")
        match = (re.search(r'name=["\']sysparm_ck["\'][^>]*value=["\']([^"\']+)', page)
                 or re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']sysparm_ck', page))
        if not match:
            raise ServiceNowError("could not obtain the background-script token; does this account have admin?")
        self._opener, self._ck = opener, match.group(1)

    def script(self, source: str, scope: str = "global"):
        """Run a background script. It should gs.print(MARK + JSON.stringify(payload))."""
        if self._opener is None:
            self._login()
        form = urllib.parse.urlencode({
            "script": source, "sysparm_ck": self._ck, "runscript": "Run script",
            "sys_scope": scope, "quota_managed_transaction": "on",
        }).encode()
        text = self._opener.open(urllib.request.Request(
            self.instance + "/sys.scripts.do", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"}),
            timeout=self.timeout).read().decode("utf-8", "replace")
        if MARK not in text:
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:400]
            raise ServiceNowError("background script produced no marked output: " + snippet)
        # The page echoes the script source above its output, so the first marker is usually the
        # gs.print() line itself. Try every marker and keep the first that parses.
        for segment in text.split(MARK)[1:]:
            chunk = segment.split("<", 1)[0].strip()
            chunk = (chunk.replace("&quot;", '"').replace("&amp;", "&")
                          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
            try:
                return json.loads(chunk)
            except ValueError:
                continue
        raise ServiceNowError("background script output was not JSON: " + text.split(MARK)[-1][:200])


# --------------------------------------------------------------------------------- verification
class Verifier:
    def __init__(self, sn: ServiceNow, prefix: str, alert_wait: int, expected: str,
                 source: str = DEFAULT_SOURCE, contract: str = "modern",
                 access_profile: str = "standard") -> None:
        self.sn = sn
        self.prefix = prefix
        self.alert_wait = alert_wait
        self.expected = expected
        self.source = source
        self.contract = contract
        self.access_profile = access_profile
        self.rows = []

    # ---- reporting
    def check(self, group: str, name: str, passed, observed: str) -> bool:
        self.rows.append({"group": group, "name": name, "passed": passed, "observed": observed})
        flag = "OBS " if passed is None else ("PASS" if passed else "FAIL")
        print(f"  [{flag}] {group:<7} {name:<44} {observed}", flush=True)
        return bool(passed)

    # ---- helpers
    def key(self, case: str) -> str:
        return f"{self.prefix}-{case}"

    def payload(self, case: str, **overrides) -> dict:
        body = {
            "source": "usbem-verify", "event_class": "usbem-verify",
            "node": f"{self.prefix.lower()}-host", "resource": case,
            "metric_name": "verify", "severity": "1", "message_key": self.key(case),
            "description": f"USBEM verification {case}",
        }
        body.update(overrides)
        return body

    def push(self, case: str, **overrides) -> dict:
        return self.sn.push_event(self.payload(case, **overrides), source=self.source)

    def field_exists(self, table: str, element: str) -> bool:
        return bool(self.sn.table("sys_dictionary", f"name={table}^element={element}", "sys_id", 1))

    def alerts_for(self, key: str):
        # Ordered: a key can end up with more than one alert, because with
        # evt_mgmt.alert_reopens_incident = new, resolving the incident closes the alert and the
        # next event opens a fresh one.
        return self.sn.table("em_alert", "message_key=" + key + "^ORDERBYsys_created_on",
                             "sys_id,number,incident,state,severity,assignment_group", 20)

    def incidents_for(self, key: str):
        return self.sn.table("incident", "correlation_id=" + key, "sys_id,number,state", 20)

    def wait_alert(self, key: str, count: int = 1):
        deadline = time.time() + self.alert_wait
        alerts = self.alerts_for(key)
        while len(alerts) < count and time.time() < deadline:
            time.sleep(3)
            alerts = self.alerts_for(key)
        return alerts

    def wait_any_alert_linked(self, key: str, incident_sys_id: str, timeout: float = 0.0) -> dict:
        """Any alert for this key holding that incident.

        Asserting on one particular alert is wrong once a key has two: the alert that closed with
        the old incident keeps it by design, and it is the live one that has to move.
        """
        deadline = time.time() + (timeout or self.alert_wait)
        while True:
            for alert in self.alerts_for(key):
                if str(alert.get("incident", "")) == incident_sys_id:
                    return alert
            if time.time() >= deadline:
                return {}
            time.sleep(3)

    def journal(self, table: str, sys_id: str, element: str = "work_notes") -> str:
        rows = self.sn.table("sys_journal_field", f"element_id={sys_id}^element={element}",
                             "value,sys_created_on", 30)
        return "\n".join(str(r.get("value", "")) for r in rows)

    def set_incident_state(self, sys_id: str, state: str) -> dict:
        """Move an incident this run created to Resolved / Closed / Canceled.

        Use only the caller's Incident API access. If policy or mandatory fields block a state
        transition, report it as unavailable; never elevate through Scripts - Background.
        """
        try:
            self.sn.update("incident", sys_id, {
                "state": state, "close_code": "Solved (Permanently)",
                "close_notes": "USBEM verification"})
            back = self.sn.record("incident", sys_id, "state,number")
            if str(back.get("state")) == state:
                return {"state": str(back.get("state")), "number": str(back.get("number")),
                        "how": "table api"}
            return {"state": str(back.get("state", "")),
                    "number": str(back.get("number", "")),
                    "error": f"state remained {back.get('state')}", "how": "table api"}
        except ServiceNowError as error:
            return {"error": str(error)[:140], "how": "unavailable"}

    # ---- groups
    def group_compat(self) -> None:
        response = self.push("compat-plain", severity="2")
        if self.contract == "modern":
            versions = response.get("versions") or {}
            wrong = sorted(f"{k}={v}" for k, v in versions.items() if v != self.expected)
            self.check("compat", f"the response reports {self.expected} for every component",
                       bool(versions) and not wrong,
                       json.dumps(versions) if versions else "the response carries no versions block")
        else:
            self.check("compat", "legacy listener responds without requiring component versions",
                       bool(response.get("version")),
                       f"version={response.get('version') or '(absent)'}")
        contract = all(k in response for k in ("status", "inserted", "sys_ids", "results", "version"))
        self.check("compat", "original response contract",
                   contract and response.get("status") == "success",
                   f"status={response.get('status')} inserted={response.get('inserted')}")
        if self.access_profile == "limited":
            self.check("compat", "event accepted by connector", bool(response.get("event_sys_id")),
                       str(response.get("event_sys_id", "response has no event_sys_id"))
                       + " (em_event table readback not required)")
        else:
            self.check("compat", "event row created",
                       bool(self.sn.table("em_event", "message_key=" + self.key("compat-plain"), "sys_id", 2)),
                       str(response.get("event_sys_id", "")))

        alerts = self.wait_alert(self.key("compat-plain"))
        self.check("compat", "alert created by Event Management", bool(alerts),
                   alerts[0]["number"] if alerts else f"no alert within {self.alert_wait}s")
        self.check("compat", "no incident without DTI",
                   not self.incidents_for(self.key("compat-plain")), "0 incidents")

        batch = self.sn.push_event({"records": [self.payload("compat-batch-1", severity="3"),
                                                self.payload("compat-batch-2", severity="3")]})
        self.check("compat", "batch of two records", batch.get("inserted") == "2",
                   f"inserted={batch.get('inserted')} sys_ids={len(batch.get('sys_ids') or [])}")

        if self.contract == "legacy":
            # The original transform is an event-ingestion contract. DTI result fields and
            # the newer dti_ helper aliases belong to the modular listener compatibility checks.
            return

        legacy = self.push("compat-legacy", direct_to_incident="true",
                           dti_short_description="legacy dti_ prefixed fields",
                           dti_work_note="legacy work note")
        self.check("compat", "legacy dti_ fields still honoured", bool(legacy.get("incident_number")),
                   f"{legacy.get('incident_number')} status={legacy.get('dti_incident_status')}")
        if legacy.get("incident_sys_id"):
            row = self.sn.record("incident", legacy["incident_sys_id"], "short_description")
            self.check("compat", "dti_short_description applied",
                       row.get("short_description") == "legacy dti_ prefixed fields",
                       str(row.get("short_description")))

    def _dti_cycle(self, group: str) -> None:
        extra = {"direct_to_incident": "true"}

        started = time.perf_counter()
        first = self.push(f"{group}-new", **extra)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        self.check(group, "new key creates an incident", bool(first.get("incident_number")),
                   f"{first.get('incident_number')} status={first.get('dti_incident_status')} "
                   f"version={first.get('dti_version')}")
        self.check(group, "immediate DTI response time (ms)", None, str(elapsed_ms))
        if not first.get("incident_sys_id"):
            return

        again = self.push(f"{group}-new", **extra)
        self.check(group, "an open incident is reused",
                   again.get("incident_sys_id") == first.get("incident_sys_id"),
                   f"{again.get('incident_number')} status={again.get('dti_incident_status')}")

        alerts = self.wait_alert(self.key(f"{group}-new"))
        if alerts:
            linked = self.wait_any_alert_linked(self.key(f"{group}-new"), first["incident_sys_id"])
            self.check(group, "the alert links to the incident", bool(linked),
                       f"{linked['number']} -> {first.get('incident_number')}" if linked
                       else "no alert points at it")
        else:
            self.check(group, "the alert links to the incident", False, "no alert created")

        for state, label in TERMINAL_STATES:
            case = f"{group}-{label.lower()}"
            opening = self.push(case, **extra)
            if not opening.get("incident_sys_id"):
                self.check(group, f"{label}: first incident", False,
                           str(opening.get("dti_incident_status")))
                continue
            moved = self.set_incident_state(opening["incident_sys_id"], state)
            if moved.get("state") != state:
                self.check(group, f"{label} -> a new incident", None,
                           f"skipped: this account cannot move an incident to {label} "
                           f"({moved.get('error') or moved.get('how')})")
                continue

            # What the fast path could have claimed in-request, recorded before the event lands.
            after = self.push(case, **extra)
            fresh = after.get("incident_sys_id") not in ("", None, opening["incident_sys_id"])
            self.check(group, f"{label} -> a new incident", fresh,
                       f"{after.get('incident_number')} (was {opening.get('incident_number')}) "
                       f"status={after.get('dti_incident_status')}")
            if not fresh:
                continue

            if self.wait_alert(self.key(case)):
                # This is the slowest thing the system does: Event Management may have to reopen
                # the alert that closed with the old incident, or make a new one, before anything
                # can link it. Give it double the usual window before calling it a failure.
                linked = self.wait_any_alert_linked(self.key(case), after["incident_sys_id"],
                                                    timeout=self.alert_wait * 2)
                self.check(group, f"{label}: the alert follows", bool(linked),
                           f"{linked['number']} -> {after.get('incident_number')}" if linked
                           else "no alert points at it; links are " +
                                str([(a["number"], a.get("state"), a.get("incident", "")[:8])
                                     for a in self.alerts_for(self.key(case))]))
            repeat = self.push(case, **extra)
            self.check(group, f"{label}: the next event reuses the new one",
                       repeat.get("incident_sys_id") == after["incident_sys_id"],
                       f"{repeat.get('incident_number')} status={repeat.get('dti_incident_status')}")

    def group_fast(self) -> None:
        self._dti_cycle("fast")

    def group_fields(self) -> None:
        response = self.push("fields-defaults", direct_to_incident="true")
        sys_id = response.get("incident_sys_id", "")
        if not sys_id:
            self.check("fields", "incident created", False, str(response.get("dti_incident_status")))
            return
        row = self.sn.record("incident", sys_id,
                             "number,category,subcategory,caller_id,impact,urgency,"
                             "correlation_display,u_netcool_ticket", display="all")

        def value(field):
            cell = row.get(field)
            return cell.get("value") if isinstance(cell, dict) else cell

        def shown(field):
            cell = row.get(field)
            return cell.get("display_value") if isinstance(cell, dict) else cell

        self.check("fields", "u_netcool_ticket is true", str(value("u_netcool_ticket")) in ("1", "true"),
                   f"u_netcool_ticket={value('u_netcool_ticket')}")
        self.check("fields", "category defaults to Software",
                   str(shown("category")).lower() == "software", str(shown("category")))
        self.check("fields", "subcategory defaults to Monitoring Alert",
                   str(shown("subcategory")).lower() == "monitoring alert", str(shown("subcategory")))
        self.check("fields", "caller defaults to Event Management",
                   "event management" in str(shown("caller_id")).lower(), str(shown("caller_id")))
        self.check("fields", "tagged as a USBEM DTI incident",
                   str(value("correlation_display")) == "USBEM DTI", str(value("correlation_display")))

        # The subflow made a P2 for Critical/Major, a P3 for Minor and a P4 for the rest, with
        # impact and urgency both 2, 3 and 4. Severity 0 and 5 create nothing at all.
        for severity, expected in (("1", "2"), ("2", "2"), ("3", "3"), ("4", "4")):
            tier = self.push(f"fields-sev{severity}", direct_to_incident="true", severity=severity)
            if not tier.get("incident_sys_id"):
                self.check("fields", f"severity {severity} -> impact/urgency {expected}", False,
                           f"no incident: {tier.get('dti_incident_status')}")
                continue
            got = self.sn.record("incident", tier["incident_sys_id"], "impact,urgency")
            self.check("fields", f"severity {severity} -> impact/urgency {expected}",
                       (str(got.get("impact")), str(got.get("urgency"))) == (expected, expected),
                       f"impact={got.get('impact')} urgency={got.get('urgency')}")
        for severity in ("0", "5"):
            quiet = self.push(f"fields-sev{severity}", direct_to_incident="true", severity=severity)
            self.check("fields", f"severity {severity} creates no incident",
                       not quiet.get("incident_sys_id") and
                       quiet.get("dti_incident_status") == "suppressed_by_severity_map",
                       f"status={quiet.get('dti_incident_status')} "
                       f"incident={quiet.get('incident_number') or '(none)'}")

        override = self.push("fields-override", direct_to_incident="true",
                             category="Network", subcategory="DNS", contact_type="Integration",
                             short_description="sender supplied short description",
                             caller_id="Abel Tuter", impact="3", urgency="3")
        sys_id = override.get("incident_sys_id", "")
        if sys_id:
            row = self.sn.record("incident", sys_id,
                                 "category,subcategory,caller_id,contact_type,short_description,"
                                 "u_netcool_ticket", display="all")
            applied = str(override.get("incident_fields_applied", ""))
            self.check("fields", "any incident field can be written",
                       all(f in applied for f in ("category", "subcategory", "contact_type", "caller_id")),
                       "applied: " + applied)
            self.check("fields", "the payload category wins",
                       str(shown("category")).lower() == "network" and str(shown("subcategory")).lower() == "dns",
                       f"{shown('category')}/{shown('subcategory')}")
            self.check("fields", "the payload caller wins",
                       "abel" in str(shown("caller_id")).lower(), str(shown("caller_id")))
            self.check("fields", "the payload short_description wins",
                       value("short_description") == "sender supplied short description",
                       str(value("short_description")))
            self.check("fields", "NetCool stays true under overrides",
                       str(value("u_netcool_ticket")) in ("1", "true"), str(value("u_netcool_ticket")))

        typo = self.push("fields-typo", direct_to_incident="true", catgeory="Network",
                         short_description="typo check")
        skipped = str(typo.get("incident_fields_skipped", ""))
        self.check("fields", "an unknown field name is reported", "catgeory" in skipped,
                   f"incident_fields_skipped={skipped or '(empty)'}")

        self.check_generating_alert()

        group_row = self.sn.table("sys_user_group", "active=true", "sys_id,name", 1)
        if group_row:
            named = self.push("fields-group", direct_to_incident="true",
                              assignment_group=group_row[0]["name"])
            if named.get("incident_sys_id"):
                row = self.sn.record("incident", named["incident_sys_id"], "assignment_group",
                                     display="all")
                self.check("fields", "the payload assignment_group wins",
                           str(shown("assignment_group")) == group_row[0]["name"],
                           f"{shown('assignment_group')} (asked for {group_row[0]['name']})")

    def check_generating_alert(self) -> None:
        """incident.u_generating_alert is customer-specific: where it exists it must point at the
        alert that produced the incident, and where it does not, say so rather than pass quietly."""
        if not self.field_exists("incident", "u_generating_alert"):
            self.check("fields", "u_generating_alert points at the alert", None,
                       "the field is not on this instance, so the mapping is not exercised")
            return
        fast = self.push("fields-genalert", direct_to_incident="true")
        if not fast.get("incident_sys_id"):
            self.check("fields", "u_generating_alert points at the alert", False,
                       f"no immediate incident: {fast.get('dti_incident_status')}")
            return
        self.check("fields", "fast path returns incident before alert processing",
                   bool(fast.get("incident_sys_id")),
                   f"{fast.get('incident_number')} status={fast.get('dti_incident_status')}")
        self.wait_alert(self.key("fields-genalert"))
        linked = self.wait_any_alert_linked(self.key("fields-genalert"), fast["incident_sys_id"])
        alert_sys_id = linked.get("sys_id", "") if linked else ""
        row = self.sn.record("incident", fast["incident_sys_id"], "u_generating_alert")
        self.check("fields", "u_generating_alert points at the alert",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} "
                   f"alert={alert_sys_id or '(none)'}")

        # The fast path creates the incident before the alert exists, so the reference can only be
        # written once they are linked. A second event for the same key exercises that.
        first = self.push("fields-genalert-fast", direct_to_incident="true")
        self.wait_alert(self.key("fields-genalert-fast"))
        second = self.push("fields-genalert-fast", direct_to_incident="true")
        incident_sys_id = second.get("incident_sys_id", "") or first.get("incident_sys_id", "")
        alerts = self.alerts_for(self.key("fields-genalert-fast"))
        alert_sys_id = alerts[0]["sys_id"] if alerts else ""
        time.sleep(3)
        row = self.sn.record("incident", incident_sys_id, "u_generating_alert") if incident_sys_id else {}
        self.check("fields", "u_generating_alert set on a fast-path incident",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} "
                   f"alert={alert_sys_id or '(none)'}")

    def group_notes(self) -> None:
        response = self.push("notes-incident", direct_to_incident="true",
                             work_notes="sender note for the incident")
        sys_id = response.get("incident_sys_id", "")
        if not sys_id:
            self.check("notes", "incident created", False, str(response.get("dti_incident_status")))
            return
        notes = self.journal("incident", sys_id)
        self.check("notes", "the connector note is on the incident",
                   "Direct To Incident Via Event Management Generic JSON Endpoint" in notes,
                   notes.splitlines()[0] if notes else "no work notes")
        self.check("notes", "a sender work_notes reaches the incident",
                   "sender note for the incident" in notes,
                   "written" if "sender note for the incident" in notes else "missing")

        # DTI returns the incident immediately; the Business Rule links the alert afterward.
        # The creation note therefore names the message key, not a not-yet-created alert.
        fast = self.push("notes-createdfrom", direct_to_incident="true")
        if fast.get("incident_sys_id"):
            notes = self.journal("incident", fast["incident_sys_id"])
            self.check("notes", "the created-from line names the message key",
                       f"Incident Created From {self.key('notes-createdfrom')}" in notes,
                       f"looked for 'Incident Created From {self.key('notes-createdfrom')}'")
        else:
            self.check("notes", "the created-from line names the message key", False,
                       f"no immediate incident: {fast.get('dti_incident_status')}")

        legacy = self.push("notes-legacy", direct_to_incident="true",
                           dti_work_note="legacy note via dti_work_note")
        if legacy.get("incident_sys_id"):
            legacy_notes = self.journal("incident", legacy["incident_sys_id"])
            self.check("notes", "the legacy dti_work_note reaches the incident",
                       "legacy note via dti_work_note" in legacy_notes,
                       "written" if "legacy note via dti_work_note" in legacy_notes else "missing")

        repeat = self.push("notes-incident", direct_to_incident="true",
                           work_notes="second sender note")
        time.sleep(2)
        notes = self.journal("incident", sys_id)
        written = "Duplicate event received" in notes and "second sender note" in notes
        skipped = str(repeat.get("incident_work_note", "")) == "skipped"
        # Annotating an incident that already exists needs write access to the incident table.
        # Where the scope has it this must be written; where it does not, the connector reports the
        # skip instead of failing the event, which is a reported state, not a regression.
        self.check("notes", "reuse adds a duplicate note",
                   True if written else (None if skipped else False),
                   f"status={repeat.get('dti_incident_status')}" if written else
                   (f"skipped: {repeat.get('incident_work_note_skipped_reason')} — grant the scope "
                    "write on incident" if skipped else "no duplicate note and no skip reported"))

        self.push("notes-alert", alert_work_notes="sender note for the alert")
        alerts = self.wait_alert(self.key("notes-alert"))
        if alerts:
            time.sleep(3)
            alert_notes = self.journal("em_alert", alerts[0]["sys_id"])
            self.check("notes", "alert_work_notes reaches the alert",
                       "sender note for the alert" in alert_notes,
                       alerts[0]["number"] +
                       (": written" if "sender note for the alert" in alert_notes else ": missing"))
        else:
            self.check("notes", "alert_work_notes reaches the alert", False, "no alert created")

        # Regression guard. The note travels in the alert's additional_info and the reconcile rule
        # runs on every alert write, so a connector that does not consume the key re-posts the same
        # note on writes that never asked for one.
        self.push("notes-alert-once", alert_work_notes="post me exactly once")
        alerts = self.wait_alert(self.key("notes-alert-once"))
        if not alerts:
            self.check("notes", "the note is not re-posted on later alert writes", False,
                       "no alert created")
        else:
            time.sleep(4)
            for _ in range(2):
                self.push("notes-alert-once", severity="2")    # same key, no note on the payload
                time.sleep(5)
            copies = [line for line in self.journal("em_alert", alerts[0]["sys_id"]).splitlines()
                      if "post me exactly once" in line]
            self.check("notes", "the note is not re-posted on later alert writes", len(copies) == 1,
                       f"{alerts[0]['number']}: {len(copies)} copies after two further alert writes")

        dti_note = self.push("notes-dti-plain", direct_to_incident="true",
                             work_notes="incident only, not the alert")
        alerts = self.wait_alert(self.key("notes-dti-plain"))
        if alerts and dti_note.get("incident_sys_id"):
            time.sleep(4)
            on_alert = "incident only, not the alert" in self.journal("em_alert", alerts[0]["sys_id"])
            on_incident = "incident only, not the alert" in self.journal("incident",
                                                                         dti_note["incident_sys_id"])
            self.check("notes", "a DTI work_notes does not also land on the alert",
                       on_incident and not on_alert, f"incident={on_incident} alert={on_alert}")

        self.push("notes-alert-plain", work_notes="plain note, no incident")
        alerts = self.wait_alert(self.key("notes-alert-plain"))
        if alerts:
            time.sleep(3)
            alert_notes = self.journal("em_alert", alerts[0]["sys_id"])
            self.check("notes", "work_notes reaches a non-DTI alert",
                       "plain note, no incident" in alert_notes,
                       alerts[0]["number"] +
                       (": written" if "plain note, no incident" in alert_notes else ": missing"))
        else:
            self.check("notes", "work_notes reaches a non-DTI alert", False, "no alert created")

    def group_edge(self) -> None:
        # incident.correlation_id is String(100) but em_alert.message_key holds 1024, so a long key
        # cannot round-trip. The connector must still converge on one incident for that key.
        long_key = (self.prefix + "-edge-long-" + ("k" * 130))[:180]
        numbers, statuses = [], []
        for _ in range(3):
            response = self.sn.push_event({
                "source": "usbem-verify", "event_class": "usbem-verify",
                "node": f"{self.prefix.lower()}-host", "resource": "edge-long",
                "metric_name": "verify", "severity": "1", "message_key": long_key,
                "description": "USBEM verification long key", "direct_to_incident": "true"})
            numbers.append(response.get("incident_number", ""))
            statuses.append(response.get("dti_incident_status", ""))
        open_incidents = self.sn.table(
            "incident", f"correlation_idSTARTSWITH{self.prefix}-edge-long^stateNOT IN6,7,8",
            "sys_id,number", 20)
        self.check("edge", "a long message key converges on one incident",
                   len(set(n for n in numbers if n)) == 1 and len(open_incidents) <= 1,
                   f"returned {numbers}, {len(open_incidents)} open incident(s)")

        # Two events for one key at the same instant. There is no duplicate protection on the fast
        # path, so this is reported, not failed — but a regression that opens three would show.
        payload = self.payload("edge-concurrent", direct_to_incident="true")
        clients = [ServiceNow(self.sn.instance, self.sn.user, self.sn.password,
                              self.sn.ca_bundle, self.sn.insecure) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda c: c.push_event(payload), clients))
        self.check("edge", "concurrent events for one key", None,
                   f"returned {sorted(set(r.get('incident_number', '') for r in responses))}, "
                   f"statuses {[r.get('dti_incident_status') for r in responses]}")

        batch = self.sn.push_event({"records": [
            self.payload("edge-batch-plain", severity="3"),
            self.payload("edge-batch-dti", severity="1", direct_to_incident="true"),
        ]})
        results = batch.get("results") or []
        with_incident = [r for r in results if r.get("incident_sys_id")]
        self.check("edge", "DTI inside a batch",
                   batch.get("inserted") == "2" and len(with_incident) == 1,
                   f"inserted={batch.get('inserted')}, {len(with_incident)} of {len(results)} "
                   f"result(s) carry an incident")

    def group_timing(self) -> None:
        samples = {"plain": [], "direct_to_incident": []}
        for index in range(3):
            for mode in samples:
                extra = {}
                if mode == "direct_to_incident":
                    extra["direct_to_incident"] = "true"
                started = time.time()
                self.push(f"timing-{mode}-{index}", **extra)
                samples[mode].append(round((time.time() - started) * 1000))
        self.check("timing", "endpoint round trip (ms)", None,
                   " ".join(f"{mode} median {statistics.median(values):.0f}"
                            for mode, values in samples.items()))

    # ---- cleanup
    def cleanup(self) -> dict:
        removed = {}
        for table, field in (("incident", "correlation_id"), ("em_alert", "message_key"),
                             ("em_event", "message_key")):
            count = 0
            for row in self.sn.table(table, f"{field}STARTSWITH{self.prefix}", "sys_id", 500):
                try:
                    self.sn.delete(table, row["sys_id"])
                    count += 1
                except ServiceNowError:
                    pass
            removed[table] = count
        return removed


# --------------------------------------------------------------------------------- entry point
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", choices=GROUPS, help="run only these groups")
    parser.add_argument("--keep", action="store_true", help="do not delete what the run created")
    parser.add_argument("--prefix", help="tag for the records this run creates")
    parser.add_argument("--alert-wait", type=int, default=120,
                        help="seconds to wait for Event Management to produce an alert")
    parser.add_argument("--expect-version", default=EXPECTED_RELEASE,
                        help=f"version every component should report (default {EXPECTED_RELEASE})")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help=f"listener source parameter (default: {DEFAULT_SOURCE}; legacy PDI: firstGenericJson)")
    parser.add_argument("--contract", choices=("modern", "legacy"), default="modern",
                        help="modern requires component versions; legacy checks the original response envelope and dti_ aliases")
    parser.add_argument("--access-profile", choices=("standard", "limited"), default="standard",
                        help="limited uses only Incident/Alert readback, avoids background scripts and deletion, and runs compat+fast")
    parser.add_argument("--json", dest="json_out", help="write the results to this file")
    parser.add_argument("--instance", default="", help="https://<instance>.service-now.com")
    parser.add_argument("--user", default="", help="an admin account")
    parser.add_argument("--password", default="")
    parser.add_argument("--env-file", help="a .env holding the credentials")
    parser.add_argument("--ca-bundle", default="", help="PEM file to trust (a corporate root)")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification, last resort")
    parser.add_argument("--version", action="version", version="usbem_verify " + VERSION)
    args = parser.parse_args()

    instance, user, password = resolve_credentials(args)
    groups = args.only or (["compat"] if args.contract == "legacy" else list(GROUPS))
    if args.access_profile == "limited":
        allowed_groups = {"compat", "fast"}
        if args.only and not set(groups).issubset(allowed_groups):
            parser.error("--access-profile limited supports only --only compat and --only fast")
        if not args.only:
            groups = ["compat", "fast"] if args.contract == "modern" else ["compat"]
    sn = ServiceNow(instance, user, password, ca_bundle=args.ca_bundle, insecure=args.insecure)
    prefix = args.prefix or f"ZZUSBEM-{int(time.time())}"
    verifier = Verifier(sn, prefix, args.alert_wait, args.expect_version,
                        source=args.source, contract=args.contract,
                        access_profile=args.access_profile)

    print(f"USBEM connector verification {VERSION}")
    print(f"instance {instance}")
    print(f"connector source {args.source} ({args.contract} contract)")
    if args.access_profile == "limited":
        print("access profile limited: requires Incident read/write and Alert read/write/create; "
              "created records are retained because delete access is not assumed")
    if args.contract == "modern":
        print(f"expecting components to report {args.expect_version}")
    print(f"prefix   {prefix}")
    print(f"http     {'requests' if requests is not None else 'urllib'}"
          f"{' (TLS verification OFF)' if args.insecure else ''}\n", flush=True)

    for group in GROUPS:
        if group not in groups:
            continue
        print(f"== {group} ==", flush=True)
        try:
            getattr(verifier, "group_" + group)()
        except ServiceNowError as error:
            verifier.check(group, "group completed", False, str(error)[:220])
        except Exception as error:        # a broken check must not hide the groups after it
            verifier.check(group, "group completed", False, f"{type(error).__name__}: {error}"[:220])

    if args.keep or args.access_profile == "limited":
        print(f"\nkept every record tagged {prefix}")
    else:
        print("\ncleanup:", verifier.cleanup())

    passed = sum(1 for row in verifier.rows if row["passed"] is True)
    failed = [row for row in verifier.rows if row["passed"] is False]
    observed = sum(1 for row in verifier.rows if row["passed"] is None)
    print(f"\n{passed} passed, {len(failed)} failed, {observed} observation(s)")
    for row in failed:
        print(f"  FAILED {row['group']} {row['name']}: {row['observed']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "script_version": VERSION, "expected_release": args.expect_version,
            "instance": instance, "prefix": prefix, "rows": verifier.rows}, indent=2))
        print(f"\nresults written to {args.json_out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
