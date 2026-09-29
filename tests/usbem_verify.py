#!/usr/bin/env python3
"""USBEM genericJsonV2 connector — end-to-end verification, in one file.

Copy this file anywhere and run it. Nothing else to download, nothing to install, no particular
directory. Standard library only; if `requests` happens to be installed it is used, because it
carries its own CA bundle, but it is not required.

    python3 usbem_verify.py                      # every group
    python3 usbem_verify.py --only fast --only notes
    python3 usbem_verify.py --keep               # leave the records it creates
    python3 usbem_verify.py --json out.json      # machine-readable results

Everything it creates is tagged with a unique prefix and deleted afterwards. Exit code is 0 only
when every check passed.

CREDENTIALS, in order of preference:
    --instance https://dev382837.service-now.com --user admin --password '...'
    environment: servicenow_instance / servicenow_user / servicenow_password
                 (SN_INSTANCE_URL / SN_USERNAME / SN_PASSWORD also work)
    a .env file: --env-file /path/to/.env, or the nearest .env at or above the current
                 directory, or one next to this script
An admin account is needed: resolving and closing incidents goes through a background script,
because the Table API trips over the mandatory close fields.

TLS: certificates are verified. On a Mac whose Python has no CA bundle you may see
CERTIFICATE_VERIFY_FAILED — the script says so and tells you the three ways out:
    pip install certifi          (or requests, which brings it)
    --ca-bundle /path/root.pem   to trust a corporate root
    --insecure                   to skip verification, last resort

GROUPS (--only <name>, repeatable):
    deploy   the versions the live endpoint reports, the reconcile rule's configuration, and that
             nothing queues an event or runs on a schedule
    compat   the original connector contract: plain events, batches, no incident without DTI,
             and the legacy dti_ field names
    fast     direct_to_incident returns an incident immediately, reuses it while open, opens a new
             one once it is Resolved/Closed/Canceled, and the alert follows
    wait     the same cycle with dti_wait_for_incident=true
    fields   NetCool, category, subcategory, caller, the severity tiers, u_generating_alert, and
             every payload override
    ci       the assignment group chain against a real CI: payload, support_group, level 2 tier,
             then the alert's own group
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
GROUPS = ("deploy", "compat", "fast", "wait", "fields", "ci", "notes", "edge", "timing")

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
    def __init__(self, sn: ServiceNow, prefix: str, alert_wait: int, expected: str) -> None:
        self.sn = sn
        self.prefix = prefix
        self.alert_wait = alert_wait
        self.expected = expected
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
        return self.sn.push_event(self.payload(case, **overrides))

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
        source = """
var out = {};
var gr = new GlideRecord('incident');
if (gr.get('%s')) {
    gr.setValue('state', '%s');
    if (gr.isValidField('close_code')) { gr.setValue('close_code', 'Solved (Permanently)'); }
    if (gr.isValidField('close_notes')) { gr.setValue('close_notes', 'USBEM verification'); }
    gr.update();
    var back = new GlideRecord('incident');
    back.get('%s');
    out.state = String(back.getValue('state'));
    out.number = String(back.getValue('number'));
} else { out.error = 'incident not found'; }
gs.print('%s' + JSON.stringify(out));
""" % (sys_id, state, sys_id, MARK)
        return self.sn.script(source)

    # ---- groups
    def group_deploy(self) -> None:
        response = self.push("deploy-probe", severity="0")
        versions = response.get("versions") or {}
        expected_components = {"listener", "core", "lookups", "debug", "dti"}
        missing = sorted(expected_components - set(versions))
        wrong = sorted(f"{k}={v}" for k, v in versions.items() if v != self.expected)
        self.check("deploy", f"every component reports {self.expected}", not missing and not wrong,
                   json.dumps(versions) if versions else "the response carries no versions block")
        self.check("deploy", "response keeps the legacy version field",
                   str(response.get("version", "")) == self.expected, str(response.get("version")))

        rule = self.sn.table("sys_script", "name=USBEM Fast DTI Alert Reconcile^collection=em_alert",
                             "when,order,active,action_insert,action_update,condition", 5)
        if rule:
            config = rule[0]
            wanted = {"when": "after", "order": "150", "active": "true",
                      "action_insert": "true", "action_update": "true"}
            bad = [f"{k}={config.get(k)}" for k, v in wanted.items() if str(config.get(k)) != v]
            self.check("deploy", "reconcile rule is a synchronous after rule", not bad,
                       "after / insert+update / order 150" if not bad else "wrong: " + ", ".join(bad))
            self.check("deploy", "reconcile rule is filtered",
                       "direct_to_incident" in str(config.get("condition", "")),
                       (str(config.get("condition", ""))[:70] + "...") if config.get("condition")
                       else "no condition, so it runs on every alert write")
        else:
            self.check("deploy", "reconcile rule is present", False, "not found on em_alert")

        actions = self.sn.table("sysevent_script_action", "nameLIKElink_alert_later^active=true",
                                "name", 5)
        self.check("deploy", "no async link script action", not actions,
                   "none active" if not actions else str([a["name"] for a in actions]))

        def newest_queued() -> str:
            rows = self.sn.table("sysevent", "nameSTARTSWITHx_usbna_usb_event^ORDERBYDESCsys_created_on",
                                 "sys_created_on", 1)
            return rows[0]["sys_created_on"] if rows else ""

        before = newest_queued()
        self.push("deploy-queue-probe", direct_to_incident="true")
        time.sleep(5)
        self.check("deploy", "a DTI request queues no sysevent", newest_queued() == before,
                   "nothing new on sysevent" if newest_queued() == before
                   else "a queued event appeared")

        jobs = self.sn.table("sysauto_script",
                             "active=true^scriptLIKEUSBEM_DTI^ORactive=true^nameLIKEUSBEM", "name", 5)
        self.check("deploy", "no scheduled job drives this", not jobs,
                   "none" if not jobs else str([j["name"] for j in jobs]))

    def group_compat(self) -> None:
        response = self.push("compat-plain", severity="2")
        contract = all(k in response for k in ("status", "inserted", "sys_ids", "results", "version"))
        self.check("compat", "original response contract",
                   contract and response.get("status") == "success",
                   f"status={response.get('status')} inserted={response.get('inserted')}")
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

    def _dti_cycle(self, group: str, wait: bool) -> None:
        extra = {"direct_to_incident": "true"}
        if wait:
            # The wait path holds the request open until Event Management produces the alert and
            # gives up after usbem_wait_seconds (15 by default). A busy instance needs longer, and
            # that shows up as alert_not_found - the instance being slow, not the connector wrong.
            extra["dti_wait_for_incident"] = "true"
            extra["usbem_wait_seconds"] = "45"

        first = self.push(f"{group}-new", **extra)
        self.check(group, "new key creates an incident", bool(first.get("incident_number")),
                   f"{first.get('incident_number')} status={first.get('dti_incident_status')} "
                   f"version={first.get('dti_version')}")
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
                self.check(group, f"{label}: incident moved to {label}", False, json.dumps(moved))
                continue

            # What the fast path could have claimed in-request, recorded before the event lands.
            claimable_before = [a for a in self.alerts_for(self.key(case))
                                if str(a.get("state", "")).lower() != "closed"]
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
                if group == "fast":
                    # The fast path can only claim an alert that already exists and is claimable.
                    # If the previous one closed with the old incident, or Event Management has not
                    # produced one yet, there is nothing to claim and the rule does it afterwards -
                    # that is the design, not a failure.
                    status = after.get("alert_link_status") or ""
                    if claimable_before:
                        self.check(group, f"{label}: claimed during the request",
                                   status in ("relinked", "linked", "already_linked"),
                                   f"alert_link_status={status or '(absent)'}")
                    else:
                        self.check(group, f"{label}: claimed during the request", None,
                                   "no claimable alert existed when the event arrived"
                                   f"{', status ' + status if status else ''}; "
                                   "the reconcile rule links it")
            repeat = self.push(case, **extra)
            self.check(group, f"{label}: the next event reuses the new one",
                       repeat.get("incident_sys_id") == after["incident_sys_id"],
                       f"{repeat.get('incident_number')} status={repeat.get('dti_incident_status')}")

    def group_fast(self) -> None:
        self._dti_cycle("fast", wait=False)

    def group_wait(self) -> None:
        self._dti_cycle("wait", wait=True)

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
        waited = self.push("fields-genalert", direct_to_incident="true",
                           dti_wait_for_incident="true", usbem_wait_seconds="45")
        if not waited.get("incident_sys_id"):
            self.check("fields", "u_generating_alert points at the alert", False,
                       f"no incident: {waited.get('dti_incident_status')}")
            return
        alert_sys_id = waited.get("alert_sys_id", "")
        if not alert_sys_id:
            alerts = self.wait_alert(self.key("fields-genalert"))
            alert_sys_id = alerts[0]["sys_id"] if alerts else ""
        row = self.sn.record("incident", waited["incident_sys_id"], "u_generating_alert")
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

    def group_ci(self) -> None:
        """The assignment group chain against a real CI. Needs read on cmdb_rel_ci, or CI
        resolution throws before any of this runs."""
        cis = self.sn.table("cmdb_ci_server", "operational_status=1^nameISNOTEMPTY", "sys_id,name", 5)
        groups = self.sn.table("sys_user_group", "active=true", "sys_id,name", 3)
        if not cis or len(groups) < 3:
            self.check("ci", "fixtures available", False,
                       f"{len(cis)} server CI(s), {len(groups)} group(s)")
            return
        ci = cis[0]
        level2, support, payload_group = groups[0], groups[1], groups[2]
        has_tier_field = self.field_exists("cmdb_ci", "u_level_2_support_assignee_group")
        fields = "support_group,u_level_2_support_assignee_group" if has_tier_field else "support_group"
        original = self.sn.record("cmdb_ci", ci["sys_id"], fields)

        def incident_for(case: str, **extra):
            response = self.push(case, node=ci["name"], direct_to_incident="true", **extra)
            if not response.get("incident_sys_id"):
                return response, {}
            return response, self.sn.record("incident", response["incident_sys_id"],
                                            "assignment_group,cmdb_ci", display="all")

        def shown(row, field):
            cell = row.get(field)
            return (cell.get("display_value") if isinstance(cell, dict) else cell) or ""

        blank = {"support_group": ""}
        if has_tier_field:
            blank["u_level_2_support_assignee_group"] = ""
        try:
            self.sn.update("cmdb_ci", ci["sys_id"], blank)

            response, row = incident_for("ci-baseline")
            self.check("ci", "the event's node resolves to the CI", shown(row, "cmdb_ci") == ci["name"],
                       f"cmdb_ci={shown(row, 'cmdb_ci') or '(none)'} (sent node={ci['name']})")
            self.check("ci", "no group when the CI has none", not shown(row, "assignment_group"),
                       f"assignment_group={shown(row, 'assignment_group') or '(empty)'}")

            if has_tier_field:
                self.sn.update("cmdb_ci", ci["sys_id"],
                               {"u_level_2_support_assignee_group": level2["sys_id"]})
                response, row = incident_for("ci-level2")
                self.check("ci", "the level 2 tier is used",
                           shown(row, "assignment_group") == level2["name"],
                           f"{shown(row, 'assignment_group') or '(empty)'} (expected {level2['name']})")
            else:
                self.check("ci", "the level 2 tier is used", None,
                           "cmdb_ci.u_level_2_support_assignee_group is not on this instance")

            self.sn.update("cmdb_ci", ci["sys_id"], {"support_group": support["sys_id"]})
            response, row = incident_for("ci-support")
            self.check("ci", "support_group beats the level 2 tier",
                       shown(row, "assignment_group") == support["name"],
                       f"{shown(row, 'assignment_group') or '(empty)'} (expected {support['name']})")

            response, row = incident_for("ci-payload", assignment_group=payload_group["name"])
            self.check("ci", "the payload group beats the CI",
                       shown(row, "assignment_group") == payload_group["name"],
                       f"{shown(row, 'assignment_group') or '(empty)'} (expected {payload_group['name']})")

            # Last resort: nothing on the payload, nothing on the CI, but the alert carries a
            # group. On a real instance that comes from an alert rule; here the harness puts it on
            # the alert directly, because whether this instance has such a rule is not the point.
            self.sn.update("cmdb_ci", ci["sys_id"], blank)
            self.push("ci-alertgroup", node=ci["name"], severity="3")     # non-DTI: just make the alert
            alerts = self.wait_alert(self.key("ci-alertgroup"))
            if not alerts:
                self.check("ci", "the alert's own group is the last resort", False, "no alert created")
            else:
                self.sn.update("em_alert", alerts[0]["sys_id"], {"assignment_group": level2["sys_id"]})
                response = self.push("ci-alertgroup", node=ci["name"], direct_to_incident="true",
                                     dti_wait_for_incident="true", usbem_wait_seconds="45")
                if not response.get("incident_sys_id"):
                    self.check("ci", "the alert's own group is the last resort", False,
                               f"no incident: {response.get('dti_incident_status')}")
                else:
                    row = self.sn.record("incident", response["incident_sys_id"], "assignment_group",
                                         display="all")
                    self.check("ci", "the alert's own group is the last resort",
                               shown(row, "assignment_group") == level2["name"] and
                               response.get("assignment_group_source") == "alert",
                               f"{shown(row, 'assignment_group') or '(empty)'} "
                               f"(expected {level2['name']}) "
                               f"source={response.get('assignment_group_source') or '(absent)'}")
        finally:
            restore = {"support_group": original.get("support_group", "") or ""}
            if has_tier_field:
                restore["u_level_2_support_assignee_group"] = \
                    original.get("u_level_2_support_assignee_group", "") or ""
            self.sn.update("cmdb_ci", ci["sys_id"], restore)
            back = self.sn.record("cmdb_ci", ci["sys_id"], ",".join(restore))
            self.check("ci", "the CI is restored",
                       all(str(back.get(f, "")) == str(v) for f, v in restore.items()),
                       f"{ci['name']}: " + ", ".join(f"{f}={back.get(f) or '(empty)'}" for f in restore))

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

        # The fast path creates the incident before the alert exists, so its created-from line can
        # only name the message key. The wait path has the alert, and there it must name the alert.
        waited = self.push("notes-createdfrom", direct_to_incident="true",
                           dti_wait_for_incident="true", usbem_wait_seconds="45")
        if waited.get("incident_sys_id"):
            alert_number = waited.get("alert_number", "")
            if not alert_number:
                alerts = self.wait_alert(self.key("notes-createdfrom"))
                alert_number = alerts[0]["number"] if alerts else ""
            waited_notes = self.journal("incident", waited["incident_sys_id"])
            self.check("notes", "the created-from line names the alert",
                       bool(alert_number) and f"Incident Created From {alert_number}" in waited_notes,
                       f"looked for 'Incident Created From {alert_number or '(no alert)'}'")
        else:
            self.check("notes", "the created-from line names the alert", False,
                       f"no incident: {waited.get('dti_incident_status')}")

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
            self.push("notes-alert-once", severity="2")        # same key, no note on the payload
            time.sleep(4)
            self.sn.update("em_alert", alerts[0]["sys_id"], {"description": "touched by verification"})
            time.sleep(4)
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
        samples = {"plain": [], "fast": [], "wait": []}
        for index in range(3):
            for mode in samples:
                extra = {}
                if mode != "plain":
                    extra["direct_to_incident"] = "true"
                if mode == "wait":
                    extra["dti_wait_for_incident"] = "true"
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
    sn = ServiceNow(instance, user, password, ca_bundle=args.ca_bundle, insecure=args.insecure)
    prefix = args.prefix or f"ZZUSBEM-{int(time.time())}"
    verifier = Verifier(sn, prefix, args.alert_wait, args.expect_version)
    groups = args.only or list(GROUPS)

    print(f"USBEM connector verification {VERSION}")
    print(f"instance {instance}")
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

    if args.keep:
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
