#!/usr/bin/env python3
"""Live check that USBEM_DTI stops reusing terminal incidents (ATF stand-in).

Drives x_usbna_usb_event.USBEM_DTI exactly as the inbound listener does
(createRecordContext -> resolveAll -> insertEventRecord -> handlePostInsert) through a
background script, so real em_event records are inserted, Event Management builds the
alerts, the link_alert_later script action runs the async link, and the
"USBEM Fast DTI Alert Reconcile" business rule fires.

It drives the Script Include on purpose. The deployed genericJsonV2 listener carries its
own inlined copy of the DTI class, so --listener is offered separately to show what REST
callers actually get; that check is expected to FAIL until the listener is regenerated.

Every record it creates is tagged with --prefix (default ZZDTI) and deleted at the end.

Credentials come from environment variables, else the workspace .env:
    servicenow_instance, servicenow_user, servicenow_password

Examples:
    python3 tests/dti_terminal_incident_check.py                       # all cases, both modes
    python3 tests/dti_terminal_incident_check.py --mode fast --cases 1,3,4
    python3 tests/dti_terminal_incident_check.py --listener            # add the REST-path check
    python3 tests/dti_terminal_incident_check.py --json results.json --keep

Exit code is 0 when every check passed, 1 otherwise. Observation-only checks never fail.

Known limitation, case 10: incident.correlation_id stores 100 characters while message keys
may be 1024, so for a longer key only the alert link can find the open incident; the
correlation lookup and the reconcile rule both query the full key and cannot match. Any
event that arrives while the alert has no link (between Event Management disconnecting a
terminal incident and the async linker relinking) opens another incident. Case 10 therefore
fails intermittently on long keys. It is a real gap, not a flaky check.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import http.cookiejar
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MARK = "@@JSON@@"
TERMINAL_STATES = (("6", "Resolved"), ("7", "Closed"), ("8", "Canceled"))
OPEN_STATES = (("1", "New"), ("2", "In Progress"), ("3", "On Hold"))


# --------------------------------------------------------------------------- config
def load_credentials() -> tuple[str, str, str]:
    values = {k: os.getenv(k, "") for k in ("servicenow_instance", "servicenow_user", "servicenow_password")}
    if not all(values.values()):
        for folder in Path(__file__).resolve().parents:
            env_file = folder / ".env"
            if env_file.is_file():
                for raw in env_file.read_text().splitlines():
                    if "=" in raw and not raw.lstrip().startswith("#"):
                        key, value = raw.split("=", 1)
                        key = key.strip()
                        if key in values and not values[key]:
                            values[key] = value.strip().strip("\"'")
                break
    missing = [k for k, v in values.items() if not v]
    if missing:
        sys.exit(f"missing credentials: {', '.join(missing)} (set them in the environment or .env)")
    instance = values["servicenow_instance"].rstrip("/")
    if not instance.startswith("http"):
        instance = "https://" + instance
    return instance, values["servicenow_user"], values["servicenow_password"]


# --------------------------------------------------------------------------- client
class ServiceNow:
    """Table API plus a background-script runner (no extra packages)."""

    def __init__(self, instance: str, user: str, password: str, timeout: int = 180) -> None:
        self.instance = instance
        self.user = user
        self.password = password
        self.timeout = timeout
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": "Basic " + token, "Accept": "application/json"}
        self._opener: urllib.request.OpenerDirector | None = None
        self._ck = ""

    # ---- Table API
    def _json(self, method: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = dict(self.headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.instance + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"{method} {path} -> HTTP {error.code}: {detail}") from None
        return json.loads(body)["result"] if body else None

    def table(self, name: str, query: str, fields: str, limit: int = 50, display: str = "false") -> list[dict]:
        params = urllib.parse.urlencode({
            "sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": str(limit),
            "sysparm_display_value": display, "sysparm_exclude_reference_link": "true",
        })
        return self._json("GET", f"/api/now/table/{name}?{params}") or []

    def record(self, name: str, sys_id: str, fields: str) -> dict:
        params = urllib.parse.urlencode({"sysparm_fields": fields, "sysparm_exclude_reference_link": "true"})
        return self._json("GET", f"/api/now/table/{name}/{sys_id}?{params}") or {}

    def post(self, path: str, payload: dict):
        return self._json("POST", path, payload)

    # ---- background scripts
    def _login(self) -> None:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
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
            sys.exit("could not obtain the background-script token; does this account have admin?")
        self._opener, self._ck = opener, match.group(1)

    def script(self, source: str, scope: str = "global", fresh_session: bool = False):
        """Run a background script. The script should gs.print(MARK + JSON.stringify(x))."""
        if fresh_session:
            saved = (self._opener, self._ck)
            self._opener = None
            try:
                self._login()
                return self.script(source, scope)
            finally:
                self._opener, self._ck = saved
        if self._opener is None:
            self._login()
        form = urllib.parse.urlencode({
            "sysparm_ck": self._ck, "runscript": "Run script", "sys_scope": scope, "script": source,
        }).encode()
        request = urllib.request.Request(
            self.instance + "/sys.scripts.do", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert self._opener is not None
        with self._opener.open(request, timeout=300) as response:
            page = response.read().decode("utf-8", "replace")
        import html as html_module
        text = re.sub(r"(?s)<script.*?</script>", "", page)
        text = re.sub(r"(?s)<style.*?</style>", "", text)
        text = html_module.unescape(re.sub(r"(?s)<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", text)))
        for line in text.replace("*** Script:", "\n*** Script:").splitlines():
            if MARK in line:
                try:
                    return json.JSONDecoder().raw_decode(line.split(MARK, 1)[1].strip())[0]
                except ValueError:
                    continue  # the page echoed the script source, not output
        return {"__error__": text.strip()[:1500]}


# --------------------------------------------------------------------------- JS snippets
SEND_JS = """
var PAYLOAD = __PAYLOAD__;
var out = {};
try {
    var core = new x_usbna_usb_event.USBEM_Core();
    var lookups = new x_usbna_usb_event.USBEM_Lookups(core);
    var dti = new x_usbna_usb_event.USBEM_DTI(core);
    var started = new Date().getTime();
    var ctx = core.createRecordContext(PAYLOAD, {});
    lookups.resolveAll(ctx);
    var additional = core.addOperationalAdditionalInfo(ctx);
    core.insertEventRecord(ctx, additional);
    dti.handlePostInsert(ctx);
    out.elapsed_ms = new Date().getTime() - started;
    out.result = ctx.result;
} catch (e) { out.error = String(e); }
gs.print('@@JSON@@' + JSON.stringify(out));
"""

SET_INCIDENT_STATE_JS = """
var g = new GlideRecord('incident'), out = {};
if (g.get('__ID__')) {
    g.setValue('state', '__STATE__');
    if ('__STATE__' === '3') { g.setValue('hold_reason', '1'); }
    if ('__STATE__' === '6' || '__STATE__' === '7') {
        g.setValue('close_code', 'Solved (Permanently)');
        g.setValue('close_notes', '__PREFIX__ automated check');
    }
    if ('__STATE__' === '8') { g.setValue('close_notes', '__PREFIX__ automated check'); }
    g.update();
    var r = new GlideRecord('incident'); r.get('__ID__');
    out = { number: String(r.getValue('number')), state: String(r.getValue('state')), active: String(r.getValue('active')) };
}
gs.print('@@JSON@@' + JSON.stringify(out));
"""

SET_ALERT_STATE_JS = """
var g = new GlideRecord('em_alert');
if (g.get('__ID__')) { g.setValue('state', '__STATE__'); g.update(); }
gs.print('@@JSON@@' + JSON.stringify({ state: String(g.getValue('state')) }));
"""

LINK_FOREIGN_JS = """
var i = new GlideRecord('incident');
i.initialize();
i.setValue('short_description', '__PREFIX__ foreign incident (not USBEM DTI)');
i.setValue('correlation_id', '__KEY__');
i.setValue('correlation_display', 'Some Other Integration');
var id = String(i.insert());
var a = new GlideRecord('em_alert');
if (a.get('__ALERT__')) { a.setValue('incident', id); a.update(); }
gs.print('@@JSON@@' + JSON.stringify({ incident: id }));
"""

JOURNAL_JS = """
var out = [];
var j = new GlideRecord('sys_journal_field');
j.addQuery('element_id', '__ID__'); j.orderBy('sys_created_on'); j.query();
while (j.next()) { out.push(String(j.getValue('value')).replace(/\\s+/g, ' ').substring(0, 220)); }
gs.print('@@JSON@@' + JSON.stringify(out));
"""

QUEUE_RETRY_PROBE_JS = """
var inc = new GlideRecord('incident');
inc.initialize();
inc.setValue('short_description', '__PREFIX__ retry-bound probe');
inc.setValue('correlation_id', '__KEY__');
inc.setValue('correlation_display', 'USBEM DTI');
var id = String(inc.insert());
var g = new GlideRecord('incident'); g.get(id);
var payload = JSON.stringify({ event_sys_id: '', incident_sys_id: id, message_key: '__KEY__',
    source: '__PREFIX__', event_class: '__PREFIX__', retry_count: 0 }, null, 2);
gs.eventQueue('x_usbna_usb_event.link_alert_later', g, '', payload);
gs.print('@@JSON@@' + JSON.stringify({ incident: id }));
"""

RETRY_STATE_JS = """
var out = { events: [], outcomes: [] };
var e = new GlideRecord('sysevent');
e.addQuery('name', 'x_usbna_usb_event.link_alert_later');
e.addQuery('instance', '__INC__'); e.orderBy('sys_created_on'); e.query();
while (e.next()) { out.events.push([String(e.getValue('sys_created_on')), String(e.getValue('process_on'))]); }
var s = new GlideRecord('syslog');
s.addQuery('sys_created_on', '>=', '__SINCE__');
s.addQuery('message', 'STARTSWITH', 'USBEM async alert linker');
s.orderBy('sys_created_on'); s.query();
while (s.next()) { out.outcomes.push(String(s.getValue('message')).replace(/\\s+/g, ' ')); }
gs.print('@@JSON@@' + JSON.stringify(out));
"""

NOW_JS = "gs.print('@@JSON@@' + JSON.stringify({ now: String(new GlideDateTime().getValue()) }));"

PERF_JS = """
var PREFIX = '__PREFIX__', KEY = '__KEY__';
var core = new x_usbna_usb_event.USBEM_Core();
var lookups = new x_usbna_usb_event.USBEM_Lookups(core);
var out = { fast_open_ms: [], wait_open_ms: [], corr_lookup_ms: [], made: [] };
function ctxFor(wait) {
    var p = { source: PREFIX, event_class: PREFIX, node: PREFIX + '-node', resource: PREFIX,
        metric_name: PREFIX + '_probe', type: PREFIX, severity: '1', message_key: KEY,
        description: PREFIX + ' perf probe', direct_to_incident: 'true', usbem_wait_seconds: '1' };
    if (wait) { p.dti_wait_for_incident = 'true'; }
    var c = core.createRecordContext(p, {});
    lookups.resolveAll(c);
    return c;
}
try {
    var inc = new GlideRecord('incident');
    inc.initialize();
    inc.setValue('short_description', PREFIX + ' perf open incident');
    inc.setValue('correlation_id', KEY);
    inc.setValue('correlation_display', 'USBEM DTI');
    inc.setValue('state', '2');
    var incId = String(inc.insert());
    out.made.push(['incident', incId]);
    var alert = new GlideRecord('em_alert');
    alert.initialize();
    alert.setValue('message_key', KEY); alert.setValue('source', PREFIX); alert.setValue('event_class', PREFIX);
    alert.setValue('description', PREFIX + ' perf alert'); alert.setValue('severity', '1');
    alert.setValue('state', 'Open'); alert.setValue('incident', incId);
    var alertId = String(alert.insert());
    out.made.push(['em_alert', alertId]);
    var fastCtx = ctxFor(false), waitCtx = ctxFor(true), i, t;
    for (i = 0; i < 10; i++) {
        var d1 = new x_usbna_usb_event.USBEM_DTI(core);
        t = new Date().getTime(); d1.getOrCreateFastIncident(fastCtx); out.fast_open_ms.push(new Date().getTime() - t);
        var ag = new GlideRecord('em_alert'); ag.get(alertId);
        var d2 = new x_usbna_usb_event.USBEM_DTI(core);
        t = new Date().getTime(); d2.createOrReuseIncidentForAlert(waitCtx, ag); out.wait_open_ms.push(new Date().getTime() - t);
        var d3 = new x_usbna_usb_event.USBEM_DTI(core);
        t = new Date().getTime(); d3.getExistingIncidentByCorrelationId(KEY, null); out.corr_lookup_ms.push(new Date().getTime() - t);
    }
} catch (e) { out.error = String(e); }
gs.print('@@JSON@@' + JSON.stringify(out));
"""

CLEANUP_JS = """
var out = {};
[['incident', 'correlation_id'], ['incident', 'short_description'],
 ['em_alert', 'message_key'], ['em_event', 'message_key']].forEach(function (pair) {
    var g = new GlideRecord(pair[0]);
    g.addQuery(pair[1], 'STARTSWITH', '__PREFIX__');
    g.query();
    var n = 0;
    while (g.next()) { g.deleteRecord(); n++; }
    out[pair[0] + '.' + pair[1]] = n;
});
gs.print('@@JSON@@' + JSON.stringify(out));
"""


# --------------------------------------------------------------------------- checker
class Checker:
    def __init__(self, sn: ServiceNow, prefix: str, wait_seconds: int) -> None:
        self.sn = sn
        self.prefix = prefix
        self.run_id = str(int(time.time()))
        self.wait_seconds = wait_seconds
        self.results: list[dict] = []
        self.alert_timeout = 180
        self.link_timeout = 150

    # ---- plumbing
    def key(self, mode: str, case: str) -> str:
        return f"{self.prefix}-{self.run_id}-{mode}-{case}"

    def payload(self, key: str, mode: str, description: str, dti: bool = True) -> dict:
        body = {
            "source": self.prefix, "event_class": self.prefix, "node": f"{self.prefix.lower()}-node",
            "resource": self.prefix.lower(), "metric_name": f"{self.prefix.lower()}_probe", "type": self.prefix,
            "severity": "1", "message_key": key, "description": f"{self.prefix} {description}",
        }
        if dti:
            body["direct_to_incident"] = "true"
        if dti and mode == "wait":
            body["dti_wait_for_incident"] = "true"
            body["usbem_wait_seconds"] = str(self.wait_seconds)
        return body

    def send(self, key: str, mode: str, description: str, dti: bool = True, fresh: bool = False) -> dict:
        script = SEND_JS.replace("__PAYLOAD__", json.dumps(self.payload(key, mode, description, dti)))
        out = self.sn.script(script, fresh_session=fresh)
        if isinstance(out, dict) and out.get("error"):
            print(f"    ! script error: {out['error'][:200]}")
        return (out or {}).get("result", {}) if isinstance(out, dict) else {}

    def run_js(self, source: str, **subs) -> object:
        for name, value in subs.items():
            source = source.replace(f"__{name.upper()}__", str(value))
        return self.sn.script(source)

    def set_incident_state(self, sys_id: str, state: str) -> dict:
        return self.run_js(SET_INCIDENT_STATE_JS, id=sys_id, state=state, prefix=self.prefix)

    def alerts_for(self, key: str) -> list[dict]:
        return self.sn.table("em_alert", f"message_key={key}^ORDERBYsys_created_on",
                             "sys_id,number,state,incident,sys_created_on", limit=20)

    def incidents_for(self, key: str) -> list[dict]:
        return self.sn.table("incident", f"correlation_id={key}^ORDERBYsys_created_on",
                             "sys_id,number,state,sys_created_on", limit=50)

    @staticmethod
    def wait_for(predicate, timeout_s: int, every: float = 3.0):
        deadline = time.time() + timeout_s
        outcome = None
        while time.time() < deadline:
            outcome = predicate()
            if outcome:
                return outcome
            time.sleep(every)
        return outcome

    def wait_alert(self, key: str, count: int = 1) -> list[dict]:
        found = self.wait_for(lambda: (lambda a: a if len(a) >= count else None)(self.alerts_for(key)),
                              self.alert_timeout)
        return found or self.alerts_for(key)

    def wait_linked(self, alert_sys_id: str, incident_sys_id: str) -> bool:
        if not (alert_sys_id and incident_sys_id):
            return False
        return bool(self.wait_for(
            lambda: self.sn.record("em_alert", alert_sys_id, "incident").get("incident") == incident_sys_id,
            self.link_timeout))

    def record(self, case: str, mode: str, expectation: str, observed: str, passed: bool | None, **detail) -> None:
        self.results.append({"case": case, "mode": mode, "expected": expectation,
                             "observed": observed, "pass": passed, **detail})
        flag = "OBS " if passed is None else ("PASS" if passed else "FAIL")
        print(f"  [{flag}] {mode:8s} {case:22s} {observed}", flush=True)

    def first_incident(self, key: str, mode: str) -> tuple[dict, dict]:
        """Case 1 core: first event for a key; returns (result, alert) once linked."""
        result = self.send(key, mode, "first event")
        incident = result.get("incident_sys_id", "")
        alerts = self.wait_alert(key)
        alert = alerts[0] if alerts else {}
        if alert and incident:
            self.wait_linked(alert["sys_id"], incident)
            alert = self.sn.record("em_alert", alert["sys_id"], "sys_id,number,state,incident")
        return result, alert

    # ---- cases
    def case_1(self, mode: str) -> None:
        key = self.key(mode, "C1")
        result, alert = self.first_incident(key, mode)
        expected_status = "created_fast" if mode == "fast" else "created"
        linked = alert.get("incident") == result.get("incident_sys_id")
        self.record("1 new key", mode, f"{expected_status}, incident returned and alert linked",
                    f"{result.get('dti_incident_status')} {result.get('incident_number')}; "
                    f"alert {alert.get('number')} {'linked' if linked else 'NOT linked'}",
                    result.get("dti_incident_status") == expected_status and linked, key=key)

    def case_2(self, mode: str) -> None:
        key = self.key(mode, "C2")
        first, _ = self.first_incident(key, mode)
        incident = first.get("incident_sys_id")
        expected_status = "existing_from_alert" if mode == "fast" else "existing"
        for state, label in OPEN_STATES:
            self.set_incident_state(incident, state)
            result = self.send(key, mode, f"repeat while {label}")
            self.record(f"2 open ({label})", mode, f"same incident, {expected_status}",
                        f"{result.get('dti_incident_status')} {result.get('incident_number')} "
                        f"(first {first.get('incident_number')})",
                        result.get("incident_sys_id") == incident
                        and result.get("dti_incident_status") == expected_status, key=key)

    def case_3_4_5(self, mode: str) -> None:
        for state, label in TERMINAL_STATES:
            key = self.key(mode, f"C3-{state}")
            first, alert = self.first_incident(key, mode)
            old = first.get("incident_sys_id")
            self.set_incident_state(old, state)

            result = self.send(key, mode, f"event after {label}")
            new = result.get("incident_sys_id")
            self.record(f"3 {label} -> new", mode, "a different, open incident is returned",
                        f"{result.get('dti_incident_status')} {result.get('incident_number')} "
                        f"(old {first.get('incident_number')})", bool(new) and new != old, key=key)

            if alert.get("sys_id") and new:
                moved = self.wait_linked(alert["sys_id"], new)
                self.record(f"5 {label} alert relink", mode, "the open alert ends on the new incident",
                            f"alert {alert.get('number')} -> {'new incident' if moved else 'still old/other'}",
                            moved, key=key)

            second = self.send(key, mode, f"second event after {label}")
            self.record(f"4 {label} next event", mode, "returns the new incident",
                        f"{second.get('dti_incident_status')} {second.get('incident_number')}",
                        second.get("incident_sys_id") == new, key=key)

    def case_6(self, mode: str) -> None:
        """Old alert Closed on a terminal incident, then a new event.

        Event Management either opens a NEW alert (then: new alert linked, old untouched) or
        reopens the old one and disconnects the resolved incident (then: the reopened alert
        must end on the new incident). Either way the old incident must not come back."""
        key = self.key(mode, "C6")
        first, old_alert = self.first_incident(key, mode)
        old_incident = first.get("incident_sys_id")
        self.set_incident_state(old_incident, "7")
        self.run_js(SET_ALERT_STATE_JS, id=old_alert.get("sys_id", ""), state="Closed")
        self.wait_for(lambda: self.sn.record("em_alert", old_alert["sys_id"], "state").get("state") == "Closed", 60)

        result = self.send(key, mode, "event after the alert closed")
        new_incident = result.get("incident_sys_id")
        returned_new = bool(new_incident) and new_incident != old_incident
        time.sleep(20)
        others = [a for a in self.alerts_for(key) if a["sys_id"] != old_alert["sys_id"]]
        old_now = self.sn.record("em_alert", old_alert["sys_id"], "state,incident")

        if others:
            linked = self.wait_linked(others[0]["sys_id"], new_incident)
            untouched = old_now.get("incident") == old_incident and old_now.get("state") == "Closed"
            self.record("6 closed alert", mode, "new alert linked; old alert untouched",
                        f"EM opened {others[0]['number']} ({'linked' if linked else 'NOT linked'}); "
                        f"old alert {'untouched' if untouched else 'CHANGED'}",
                        returned_new and linked and untouched, key=key)
        else:
            moved = self.wait_linked(old_alert["sys_id"], new_incident)
            journal = self.run_js(JOURNAL_JS, id=old_alert["sys_id"])
            disconnected = any("Disconnecting" in line for line in (journal if isinstance(journal, list) else []))
            self.record("6 closed alert (reopened)", mode,
                        "reopened alert ends on the new incident; old incident not reused",
                        f"EM reopened {old_alert.get('number')} (state {old_now.get('state')}), "
                        f"disconnect note={'yes' if disconnected else 'no'}; "
                        f"alert -> {'new incident' if moved else 'old/other'}",
                        returned_new and moved, key=key)

    def case_7(self, mode: str) -> None:
        """Observation only: the fast path has no duplicate protection by design."""
        key = self.key(mode, "C7")
        first, _ = self.first_incident(key, mode)
        self.set_incident_state(first.get("incident_sys_id"), "7")
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(
                lambda n: self.send(key, mode, f"concurrent event {n}", fresh=True), [1, 2]))
        time.sleep(20)
        open_incidents = [i for i in self.incidents_for(key) if i["state"] not in ("6", "7", "8")]
        self.record("7 concurrent events", mode, "observation only",
                    f"{len(open_incidents)} open incident(s); returned "
                    f"{[o.get('incident_number') for o in outcomes]}; "
                    f"statuses {[o.get('dti_incident_status') for o in outcomes]}",
                    None, key=key, open_incidents=[i["number"] for i in open_incidents])

    def case_8(self, mode: str) -> None:
        # 8a: a non-DTI alert with no DTI incident must be left alone
        key = self.key(mode, "C8A")
        self.send(key, mode, "non-DTI event", dti=False)
        alerts = self.wait_alert(key)
        time.sleep(15)  # let the async reconcile rule run
        alert = self.sn.record("em_alert", alerts[0]["sys_id"], "incident") if alerts else {}
        incidents = self.incidents_for(key)
        self.record("8a non-DTI alert", mode, "alert stays unlinked and no incident is created",
                    f"alert {'unlinked' if not alert.get('incident') else 'LINKED'}; "
                    f"{len(incidents)} incident(s)",
                    bool(alerts) and not alert.get("incident") and not incidents, key=key)

        # 8b: an alert holding a foreign closed task must never be overwritten by DTI
        key = self.key(mode, "C8B")
        self.send(key, mode, "non-DTI event", dti=False)
        alerts = self.wait_alert(key)
        if not alerts:
            self.record("8b foreign link", mode, "foreign link untouched", "no alert was created", False, key=key)
            return
        foreign = (self.run_js(LINK_FOREIGN_JS, key=key, alert=alerts[0]["sys_id"],
                               prefix=self.prefix) or {}).get("incident", "")
        self.set_incident_state(foreign, "7")
        result = self.send(key, mode, "DTI event on a foreign-linked alert")
        time.sleep(25 if mode == "fast" else 10)
        alert = self.sn.record("em_alert", alerts[0]["sys_id"], "incident")
        journal = self.run_js(JOURNAL_JS, id=alerts[0]["sys_id"])
        em_disconnected = any("Disconnecting the incident" in line
                              for line in (journal if isinstance(journal, list) else []))
        kept = alert.get("incident") == foreign
        # DTI may only fill an EMPTY link. If the foreign link is gone, Event Management must
        # be the one that removed it, which it records in the alert's work notes.
        passed = (bool(result.get("incident_sys_id")) and result.get("incident_sys_id") != foreign
                  and (kept or em_disconnected))
        self.record("8b foreign link", mode, "DTI never overwrites a foreign link",
                    f"{result.get('dti_incident_status')} {result.get('incident_number')}; link "
                    + ("foreign (untouched)" if kept else
                       f"changed after EM disconnect note={'yes' if em_disconnected else 'NO'}"),
                    passed, key=key)

    def case_9(self, mode: str) -> None:
        key = self.key(mode, "C9")
        out = self.run_js(PERF_JS, prefix=self.prefix, key=key)
        if not isinstance(out, dict) or out.get("error") or not out.get("fast_open_ms"):
            self.record("9 open-path timing", mode, "observation only",
                        f"could not measure: {str(out)[:120]}", None, key=key)
            return
        summary = {name: round(statistics.median(out[name]), 1)
                   for name in ("fast_open_ms", "wait_open_ms", "corr_lookup_ms")}
        self.record("9 open-path timing", mode, "observation only",
                    f"median ms: fast {summary['fast_open_ms']}, wait {summary['wait_open_ms']}, "
                    f"correlation lookup {summary['corr_lookup_ms']}", None, key=key, medians=summary)

    def case_10(self, mode: str) -> None:
        """Keys longer than incident.correlation_id (100) must still cycle to one new incident.

        This can fail while the alert is briefly unlinked; see the known limitation at the top."""
        key = self.key(mode, "C10-") + "x" * 120
        first, alert = self.first_incident(key, mode)
        self.set_incident_state(first.get("incident_sys_id"), "7")
        returned = []
        for n in range(3):
            result = self.send(key, mode, f"long-key event {n + 1} after closure")
            returned.append((result.get("dti_incident_status"), result.get("incident_number"),
                             result.get("incident_sys_id")))
            if n == 0 and alert.get("sys_id") and result.get("incident_sys_id"):
                self.wait_linked(alert["sys_id"], result["incident_sys_id"])
        new_ids = {sys_id for _, _, sys_id in returned if sys_id}
        stored_key = key[:100]
        open_incidents = [i for i in self.sn.table("incident", f"correlation_id={stored_key}", "sys_id,state", limit=20)
                          if i["state"] not in ("6", "7", "8")]
        alert_now = self.sn.record("em_alert", alert["sys_id"], "incident") if alert.get("sys_id") else {}
        self.record("10 key over 100 chars", mode, "one new incident across 3 events; alert moved to it",
                    f"{[f'{s} {n}' for s, n, _ in returned]}; {len(open_incidents)} open incident(s); "
                    f"alert -> {'new' if alert_now.get('incident') in new_ids else 'old/other'}",
                    len(new_ids) == 1 and len(open_incidents) == 1 and alert_now.get("incident") in new_ids,
                    key=key[:60] + "...")

    def case_11(self) -> None:
        """The async linker must give up after the configured retries instead of looping."""
        key = f"{self.prefix}-{self.run_id}-retrybound"
        since = (self.sn.script(NOW_JS) or {}).get("now", "")
        started = self.run_js(QUEUE_RETRY_PROBE_JS, key=key, prefix=self.prefix)
        incident = (started or {}).get("incident", "")
        rows = self.sn.table("sys_properties", "name=x_usbna_usb_event.fast_dti_link_max_retries", "value", limit=1)
        try:
            retries = int((rows[0]["value"] if rows else "") or 6)
        except (ValueError, KeyError):
            retries = 6
        deadline = time.time() + 40 + retries * 15
        state: dict = {}
        while time.time() < deadline:
            state = self.run_js(RETRY_STATE_JS, inc=incident, since=since) or {}
            if any("alert_not_found" in line for line in state.get("outcomes", [])):
                break
            time.sleep(10)
        events = state.get("events", [])
        delayed = sum(1 for created, process_on in events if process_on > created)
        finished = any("alert_not_found" in line for line in state.get("outcomes", []))
        self.record("11 retry bound", "async", f"stops after {retries} retries, each delayed",
                    f"{len(events)} queued event(s), {delayed} delayed; "
                    f"{'ended with alert_not_found' if finished else 'DID NOT STOP'}",
                    finished and len(events) <= retries + 1 and delayed >= 1, key=key)

    def case_listener(self) -> None:
        """What REST callers actually get. Expected to fail while the listener inlines its own copy."""
        key = f"{self.prefix}-{self.run_id}-listener"
        endpoint = "/api/sn_em_connector/em/inbound_event?" + urllib.parse.urlencode({"source": "genericJsonV2"})

        def push(description: str) -> dict:
            raw = self.sn.post(endpoint, self.payload(key, "fast", description))
            inner = raw.get("USBEM genericJsonV2") if isinstance(raw, dict) else None
            try:
                body = json.loads(inner) if isinstance(inner, str) else (inner or raw)
            except ValueError:
                body = {}
            first = (body.get("results") or [body])[0] if isinstance(body, dict) else {}
            return first if isinstance(first, dict) else {}

        first = push("listener event 1")
        incident = first.get("incident_sys_id", "")
        if not incident:
            self.record("12 listener endpoint", "listener", "a new incident after closure",
                        f"no incident returned: {str(first)[:120]}", False, key=key)
            return
        self.wait_for(lambda: (self.alerts_for(key) or [{}])[0].get("incident") == incident, 120)
        self.set_incident_state(incident, "6")
        time.sleep(5)
        second = push("listener event 2 after resolve")
        self.record("12 listener endpoint", "listener", "a different incident after the first is Resolved",
                    f"{second.get('dti_incident_status')} {second.get('incident_number')}"
                    + ("  <- still the resolved one; the listener inlines its own DTI copy"
                       if second.get("incident_sys_id") == incident else ""),
                    second.get("incident_sys_id") != incident, key=key)

    # ---- driver
    def cleanup(self) -> dict:
        return self.run_js(CLEANUP_JS, prefix=self.prefix) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="both", choices=["fast", "wait", "both"])
    parser.add_argument("--cases", default="1,2,3,6,7,8,9,10,11",
                        help="comma-separated: 1 new key, 2 open, 3 terminal (with 4 and 5), 6 closed alert, "
                             "7 concurrency, 8 non-DTI, 9 timing, 10 long keys, 11 retry bound")
    parser.add_argument("--listener", action="store_true",
                        help="also push through the real connector endpoint (fails until the listener is rebuilt)")
    parser.add_argument("--prefix", default="ZZDTI", help="tag for every record this script creates")
    parser.add_argument("--wait-seconds", type=int, default=60, help="usbem_wait_seconds for wait mode")
    parser.add_argument("--keep", action="store_true", help="leave the test records in place")
    parser.add_argument("--json", metavar="FILE", help="write the results as JSON")
    args = parser.parse_args()

    instance, user, password = load_credentials()
    checker = Checker(ServiceNow(instance, user, password), args.prefix, args.wait_seconds)
    modes = ["fast", "wait"] if args.mode == "both" else [args.mode]
    cases = {c.strip() for c in args.cases.split(",") if c.strip()}

    print(f"USBEM_DTI terminal-incident check on {instance}")
    print(f"prefix {args.prefix}-{checker.run_id}\n")
    try:
        for mode in modes:
            print(f"== {mode} mode ==")
            if "1" in cases:  checker.case_1(mode)
            if "2" in cases:  checker.case_2(mode)
            if "3" in cases:  checker.case_3_4_5(mode)
            if "6" in cases:  checker.case_6(mode)
            if "7" in cases:  checker.case_7(mode)
            if "8" in cases:  checker.case_8(mode)
            if "9" in cases:  checker.case_9(mode)
            if "10" in cases: checker.case_10(mode)
        if "11" in cases:
            print("== async ==")
            checker.case_11()
        if args.listener:
            print("== listener (REST path) ==")
            checker.case_listener()
    finally:
        if args.json:
            Path(args.json).write_text(json.dumps(
                {"instance": instance, "run": checker.run_id, "results": checker.results}, indent=1))
        if not args.keep:
            print("\ncleanup:", checker.cleanup())

    failed = [r for r in checker.results if r["pass"] is False]
    passed = [r for r in checker.results if r["pass"] is True]
    observed = [r for r in checker.results if r["pass"] is None]
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(observed)} observation(s)")
    for r in failed:
        print(f"  FAILED {r['mode']} {r['case']}: expected {r['expected']}; got {r['observed']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
