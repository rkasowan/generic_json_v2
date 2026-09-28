#!/usr/bin/env python3
"""End-to-end verification of the USBEM genericJsonV2 push connector.

Everything runs through the real endpoint, exactly as a sender would reach it, and everything it
creates is tagged with a unique prefix and deleted afterwards.

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python3 tests/verify_usbem_connector.py                 # all groups
    python3 tests/verify_usbem_connector.py --only fields   # one group
    python3 tests/verify_usbem_connector.py --keep          # leave the records behind

Groups:
    deploy      versions reported by the live endpoint, and repo vs instance drift
    compat      the original connector contract still holds (plain events, batches, no DTI)
    fast        direct_to_incident without waiting: an incident comes back immediately
    wait        dti_wait_for_incident: the incident is created against the alert
    fields      incident field mapping inherited from the retired subflow
    ci          the assignment group chain: payload, then CI support_group, then the level 2 tier
    notes       work notes on both the incident and the alert
    edge        message keys longer than correlation_id, concurrent events, DTI inside a batch
    timing      how long each path takes (reported, never failed)

Exit code is 0 only when every check passed. Credentials and TLS: see scripts/usbem_client.py.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

from usbem_client import MARK, ServiceNow, ServiceNowError, load_credentials  # noqa: E402

VERSION = "2026.09.28.1"
RELEASE = (PROJECT / "VERSION").read_text().strip()

TERMINAL_STATES = (("6", "Resolved"), ("7", "Closed"), ("8", "Canceled"))
GROUPS = ("deploy", "compat", "fast", "wait", "fields", "ci", "notes", "edge", "timing")

# Records this project owns, and the file each one must match.
DEPLOYED = [
    ("sys_script_include", "name=USBEM_Core^sys_scope.scope=x_usbna_usb_event", "src/USBEM_Core.js"),
    ("sys_script_include", "name=USBEM_Lookups^sys_scope.scope=x_usbna_usb_event", "src/USBEM_Lookups.js"),
    ("sys_script_include", "name=USBEM_Debug^sys_scope.scope=x_usbna_usb_event", "src/USBEM_Debug.js"),
    ("sys_script_include", "name=USBEM_DTI^sys_scope.scope=x_usbna_usb_event", "src/USBEM_DTI.js"),
    ("sn_em_connector_listener", "source=genericJsonV2", "servicenow/USBEM_genericJsonV2.listener.js"),
    ("sys_script", "name=USBEM Fast DTI Alert Reconcile^collection=em_alert",
     "servicenow/USBEM_FastDtiAlertReconcile.business_rule.js"),
]


class Verifier:
    def __init__(self, sn: ServiceNow, prefix: str, alert_wait: int) -> None:
        self.sn = sn
        self.prefix = prefix
        self.alert_wait = alert_wait
        self.rows: list[dict] = []

    # ------------------------------------------------------------------ reporting
    def check(self, group: str, name: str, passed, observed: str, **detail) -> bool:
        self.rows.append({"group": group, "name": name, "passed": passed,
                          "observed": observed, "detail": detail})
        flag = "OBS " if passed is None else ("PASS" if passed else "FAIL")
        print(f"  [{flag}] {group:<7} {name:<34} {observed}")
        return bool(passed)

    # ------------------------------------------------------------------ helpers
    def key(self, case: str) -> str:
        return f"{self.prefix}-{case}"

    def payload(self, case: str, **overrides) -> dict:
        body = {
            "source": "usbem-verify",
            "event_class": "usbem-verify",
            "node": f"{self.prefix.lower()}-host",
            "resource": case,
            "metric_name": "verify",
            "severity": "1",
            "message_key": self.key(case),
            "description": f"USBEM verification {case}",
        }
        body.update(overrides)
        return body

    def push(self, case: str, **overrides) -> dict:
        return self.sn.push_event(self.payload(case, **overrides))

    def alerts_for(self, key: str) -> list[dict]:
        # Ordered, because a key can end up with more than one alert: with
        # evt_mgmt.alert_reopens_incident = new, resolving the incident closes the alert and the
        # next event opens a fresh one. Unordered results made "which alert" a coin toss.
        return self.sn.table("em_alert", "message_key=" + key + "^ORDERBYsys_created_on",
                             "sys_id,number,incident,state,severity,assignment_group", 20)

    def incidents_for(self, key: str) -> list[dict]:
        return self.sn.table("incident", "correlation_id=" + key,
                             "sys_id,number,state,category,subcategory,caller_id,assignment_group,"
                             "cmdb_ci,impact,urgency,correlation_display,u_netcool_ticket,"
                             "short_description,contact_type", 20)

    def wait_alert(self, key: str, count: int = 1) -> list[dict]:
        deadline = time.time() + self.alert_wait
        alerts = self.alerts_for(key)
        while len(alerts) < count and time.time() < deadline:
            time.sleep(3)
            alerts = self.alerts_for(key)
        return alerts

    def wait_linked(self, alert_sys_id: str, incident_sys_id: str) -> bool:
        deadline = time.time() + self.alert_wait
        while time.time() < deadline:
            row = self.sn.record("em_alert", alert_sys_id, "incident")
            if str(row.get("incident", "")) == incident_sys_id:
                return True
            time.sleep(3)
        return False

    def wait_any_alert_linked(self, key: str, incident_sys_id: str) -> dict:
        """Any alert for this key holding that incident.

        Asserting on one particular alert is wrong once a key has two of them: the alert that
        closed with the old incident keeps it, by design, and it is the live one that must move.
        """
        deadline = time.time() + self.alert_wait
        while True:
            for alert in self.alerts_for(key):
                if str(alert.get("incident", "")) == incident_sys_id:
                    return alert
            if time.time() >= deadline:
                return {}
            time.sleep(3)

    def field_exists(self, table: str, element: str) -> bool:
        return bool(self.sn.table("sys_dictionary", f"name={table}^element={element}", "sys_id", 1))

    def journal(self, table: str, sys_id: str, element: str = "work_notes") -> str:
        rows = self.sn.table("sys_journal_field",
                             f"element_id={sys_id}^element={element}", "value,sys_created_on", 20)
        return "\n".join(str(r.get("value", "")) for r in rows)

    def set_incident_state(self, sys_id: str, state: str) -> dict:
        """Resolve/close/cancel through a background script: the Table API trips over the
        mandatory close fields and the UI policies that guard them."""
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

    # ------------------------------------------------------------------ groups
    def group_deploy(self) -> None:
        response = self.push("deploy-probe", severity="0")
        versions = response.get("versions") or {}
        expected = {"listener", "core", "lookups", "debug", "dti"}
        missing = sorted(expected - set(versions))
        wrong = sorted(f"{k}={v}" for k, v in versions.items() if v != RELEASE)
        self.check("deploy", "endpoint reports versions", not missing and not wrong,
                   json.dumps(versions) if not missing else "missing: " + ",".join(missing))
        self.check("deploy", "response keeps legacy version", response.get("version") == RELEASE,
                   str(response.get("version")))

        for table, query, rel_path in DEPLOYED:
            rows = self.sn.table(table, query, "sys_id,name,script", 5)
            local = (PROJECT / rel_path).read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
            if not rows:
                self.check("deploy", Path(rel_path).name, False, "no record matches " + query)
                continue
            live = str(rows[0].get("script", "")).replace("\r\n", "\n").rstrip("\n")
            self.check("deploy", Path(rel_path).name, live == local,
                       "matches the repo" if live == local
                       else f"differs (instance {len(live)} bytes, repo {len(local)})")

        rule = self.sn.table("sys_script", "name=USBEM Fast DTI Alert Reconcile^collection=em_alert",
                             "when,order,active,action_insert,action_update,condition", 5)
        if rule:
            config = rule[0]
            wanted = {"when": "after", "order": "150", "active": "true",
                      "action_insert": "true", "action_update": "true"}
            bad = [f"{k}={config.get(k)}" for k, v in wanted.items() if str(config.get(k)) != v]
            self.check("deploy", "reconcile rule is a sync after rule", not bad,
                       "after/insert+update/order 150" if not bad else "wrong: " + ", ".join(bad))
            self.check("deploy", "reconcile rule is filtered",
                       "direct_to_incident" in str(config.get("condition", "")),
                       (str(config.get("condition", ""))[:60] + "...") if config.get("condition") else "no condition")
        else:
            self.check("deploy", "reconcile rule present", False, "not found")

        actions = self.sn.table("sysevent_script_action", "nameLIKElink_alert_later^active=true",
                                "name,active", 5)
        self.check("deploy", "no async link script action", not actions,
                   "none active" if not actions else str([a["name"] for a in actions]))

        # "Nothing queues an event" is a requirement, not a preference: the retired design put a
        # sysevent on the queue per DTI request. Old rows from that design are still on the table,
        # so this sends a DTI event and proves nothing NEW lands.
        def newest_queued() -> str:
            rows = self.sn.table("sysevent",
                                 "nameSTARTSWITHx_usbna_usb_event^ORDERBYDESCsys_created_on",
                                 "sys_created_on", 1)
            return rows[0]["sys_created_on"] if rows else ""

        before = newest_queued()
        self.push("deploy-queue-probe", direct_to_incident="true")
        time.sleep(5)
        after = newest_queued()
        self.check("deploy", "a DTI request queues no sysevent", after == before,
                   "nothing new on sysevent" if after == before
                   else f"a row appeared at {after} (newest was {before})")

        jobs = self.sn.table("sysauto_script", "active=true^scriptLIKEUSBEM_DTI^ORactive=true^nameLIKEUSBEM",
                             "name", 5)
        self.check("deploy", "no scheduled job drives this", not jobs,
                   "none" if not jobs else str([j["name"] for j in jobs]))

    def group_compat(self) -> None:
        response = self.push("compat-plain", severity="2")
        contract = all(k in response for k in ("status", "inserted", "sys_ids", "results", "version"))
        self.check("compat", "original response contract", contract and response["status"] == "success",
                   f"status={response.get('status')} inserted={response.get('inserted')} "
                   f"keys={sorted(set(response) & {'status','inserted','sys_ids','results','version'})}")
        self.check("compat", "event row created",
                   bool(self.sn.table("em_event", "message_key=" + self.key("compat-plain"), "sys_id", 2)),
                   response.get("event_sys_id", ""))

        alerts = self.wait_alert(self.key("compat-plain"))
        self.check("compat", "alert created by EM", bool(alerts),
                   alerts[0]["number"] if alerts else "no alert within %ss" % self.alert_wait)
        self.check("compat", "no incident without DTI", not self.incidents_for(self.key("compat-plain")),
                   "0 incidents" if not self.incidents_for(self.key("compat-plain")) else "incident created")

        batch = self.sn.push_event({"records": [self.payload("compat-batch-1", severity="3"),
                                                self.payload("compat-batch-2", severity="3")]})
        self.check("compat", "batch of two records", batch.get("inserted") == "2",
                   f"inserted={batch.get('inserted')} sys_ids={len(batch.get('sys_ids') or [])}")

        legacy = self.push("compat-legacy", direct_to_incident="true",
                           dti_short_description="legacy dti_ prefixed fields",
                           dti_work_note="legacy work note")
        incident = legacy.get("incident_number", "")
        self.check("compat", "legacy dti_ fields still honoured", bool(incident),
                   f"{incident} status={legacy.get('dti_incident_status')}")
        if legacy.get("incident_sys_id"):
            row = self.sn.record("incident", legacy["incident_sys_id"], "short_description")
            self.check("compat", "dti_short_description applied",
                       row.get("short_description") == "legacy dti_ prefixed fields",
                       str(row.get("short_description")))

    def _dti_cycle(self, group: str, wait: bool) -> None:
        extra = {"direct_to_incident": "true"}
        if wait:
            # The wait path holds the request open until Event Management produces the alert, and
            # gives up after usbem_wait_seconds (15 by default). A busy instance can take longer
            # than that, which shows up as dti_incident_status=alert_not_found and is the
            # instance being slow, not the connector being wrong. Ask for a generous window so
            # this group tests the code path.
            extra["dti_wait_for_incident"] = "true"
            extra["usbem_wait_seconds"] = "45"

        first = self.push(f"{group}-new", **extra)
        number = first.get("incident_number", "")
        self.check(group, "new key creates an incident", bool(number),
                   f"{number} status={first.get('dti_incident_status')} version={first.get('dti_version')}")
        if not first.get("incident_sys_id"):
            return

        again = self.push(f"{group}-new", **extra)
        self.check(group, "open incident is reused",
                   again.get("incident_sys_id") == first.get("incident_sys_id"),
                   f"{again.get('incident_number')} status={again.get('dti_incident_status')}")

        alerts = self.wait_alert(self.key(f"{group}-new"))
        if alerts:
            linked = self.wait_linked(alerts[0]["sys_id"], first["incident_sys_id"])
            self.check(group, "alert links to the incident", linked,
                       f"{alerts[0]['number']} -> {number}" if linked
                       else f"{alerts[0]['number']} still on {alerts[0].get('incident','')}")
        else:
            self.check(group, "alert links to the incident", False, "no alert created")

        for state, label in TERMINAL_STATES:
            case = f"{group}-{label.lower()}"
            opening = self.push(case, **extra)
            if not opening.get("incident_sys_id"):
                self.check(group, f"{label}: first incident", False, str(opening.get("dti_incident_status")))
                continue
            moved = self.set_incident_state(opening["incident_sys_id"], state)
            if moved.get("state") != state:
                self.check(group, f"{label}: incident moved", False, json.dumps(moved))
                continue

            after = self.push(case, **extra)
            fresh = after.get("incident_sys_id") not in ("", None, opening["incident_sys_id"])
            self.check(group, f"{label} -> new incident", fresh,
                       f"{after.get('incident_number')} (was {opening.get('incident_number')}) "
                       f"status={after.get('dti_incident_status')}")
            if fresh:
                alerts = self.wait_alert(self.key(case))
                if alerts:
                    linked = self.wait_any_alert_linked(self.key(case), after["incident_sys_id"])
                    self.check(group, f"{label}: alert follows", bool(linked),
                               f"{linked['number']} -> {after.get('incident_number')}"
                               f"{' (of %d alerts for the key)' % len(self.alerts_for(self.key(case))) if linked else ''}"
                               if linked else
                               f"no alert for the key points at {after.get('incident_number')}; "
                               f"links are {[a.get('incident', '') [:8] for a in self.alerts_for(self.key(case))]}")
                    if group == "fast":
                        # The alert already existed, so the fast path must have claimed it inside
                        # the request rather than leaving it to the business rule.
                        self.check(group, f"{label}: claimed during the request",
                                   after.get("alert_link_status") in ("relinked", "linked", "already_linked"),
                                   f"alert_link_status={after.get('alert_link_status') or '(absent)'}")
                repeat = self.push(case, **extra)
                self.check(group, f"{label}: next event reuses the new one",
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
                             "number,category,subcategory,caller_id,impact,urgency,correlation_display,"
                             "u_netcool_ticket,short_description,description,cmdb_ci,assignment_group",
                             display="all")

        def value(field):
            cell = row.get(field)
            return cell.get("value") if isinstance(cell, dict) else cell

        def display(field):
            cell = row.get(field)
            return cell.get("display_value") if isinstance(cell, dict) else cell

        self.check("fields", "u_netcool_ticket is true", str(value("u_netcool_ticket")) in ("1", "true"),
                   f"u_netcool_ticket={value('u_netcool_ticket')}")
        self.check("fields", "category defaults to Software",
                   str(display("category")).lower() == "software", str(display("category")))
        self.check("fields", "subcategory defaults to Monitoring Alert",
                   str(display("subcategory")).lower() == "monitoring alert", str(display("subcategory")))
        self.check("fields", "caller defaults to Event Management",
                   "event management" in str(display("caller_id")).lower(), str(display("caller_id")))
        self.check("fields", "severity 1 maps to impact/urgency 2",
                   (str(value("impact")), str(value("urgency"))) == ("2", "2"),
                   f"impact={value('impact')} urgency={value('urgency')}")
        self.check("fields", "tagged as a USBEM DTI incident",
                   str(value("correlation_display")) == "USBEM DTI", str(value("correlation_display")))

        override = self.push("fields-override", direct_to_incident="true",
                             category="Network", subcategory="DNS", contact_type="Integration",
                             short_description="sender supplied short description",
                             caller_id="Abel Tuter", impact="3", urgency="3")
        sys_id = override.get("incident_sys_id", "")
        if not sys_id:
            self.check("fields", "payload fields applied", False, str(override.get("dti_incident_status")))
            return
        row = self.sn.record("incident", sys_id,
                             "category,subcategory,caller_id,contact_type,short_description,impact,urgency,"
                             "u_netcool_ticket", display="all")
        applied = str(override.get("incident_fields_applied", ""))
        self.check("fields", "any OOB field can be written",
                   all(f in applied for f in ("category", "subcategory", "contact_type", "caller_id")),
                   "applied: " + applied)

        # A misspelled field must come back named, not vanish silently.
        typo = self.push("fields-typo", direct_to_incident="true", catgeory="Network",
                         short_description="typo check")
        skipped = str(typo.get("incident_fields_skipped", ""))
        self.check("fields", "an unknown field name is reported", "catgeory" in skipped,
                   f"incident_fields_skipped={skipped or '(empty)'}")
        self.check("fields", "payload category wins",
                   str(display("category")).lower() == "network" and str(display("subcategory")).lower() == "dns",
                   f"{display('category')}/{display('subcategory')}")
        self.check("fields", "payload caller wins",
                   "abel" in str(display("caller_id")).lower(), str(display("caller_id")))
        self.check("fields", "payload short_description wins",
                   value("short_description") == "sender supplied short description",
                   str(value("short_description")))
        self.check("fields", "NetCool stays true under overrides",
                   str(value("u_netcool_ticket")) in ("1", "true"), str(value("u_netcool_ticket")))

        self.check_severity_tiers()
        self.check_generating_alert()

        group_row = self.sn.table("sys_user_group", "active=true", "sys_id,name", 1)
        if group_row:
            named = self.push("fields-group", direct_to_incident="true",
                              assignment_group=group_row[0]["name"])
            if named.get("incident_sys_id"):
                row = self.sn.record("incident", named["incident_sys_id"], "assignment_group", display="all")
                self.check("fields", "payload assignment_group wins",
                           str(display("assignment_group")) == group_row[0]["name"],
                           f"{display('assignment_group')} (asked for {group_row[0]['name']})")

    def check_severity_tiers(self) -> None:
        """The subflow created a P2 for Critical/Major, a P3 for Minor and a P4 for the rest, with
        impact and urgency both 2, 3 and 4 respectively. Severity 0 and 5 create nothing."""
        for severity, expected in (("1", "2"), ("2", "2"), ("3", "3"), ("4", "4")):
            case = f"fields-sev{severity}"
            response = self.push(case, direct_to_incident="true", severity=severity)
            sys_id = response.get("incident_sys_id", "")
            if not sys_id:
                self.check("fields", f"severity {severity} -> impact/urgency {expected}", False,
                           f"no incident: {response.get('dti_incident_status')}")
                continue
            row = self.sn.record("incident", sys_id, "impact,urgency")
            self.check("fields", f"severity {severity} -> impact/urgency {expected}",
                       (str(row.get("impact")), str(row.get("urgency"))) == (expected, expected),
                       f"impact={row.get('impact')} urgency={row.get('urgency')}")

        for severity in ("0", "5"):
            response = self.push(f"fields-sev{severity}", direct_to_incident="true", severity=severity)
            self.check("fields", f"severity {severity} creates no incident",
                       not response.get("incident_sys_id") and
                       response.get("dti_incident_status") == "suppressed_by_severity_map",
                       f"status={response.get('dti_incident_status')} "
                       f"incident={response.get('incident_number') or '(none)'}")

    def check_generating_alert(self) -> None:
        """incident.u_generating_alert is customer-specific. Where it exists it must point at the
        alert that produced the incident; where it does not, say so rather than passing quietly."""
        if not self.field_exists("incident", "u_generating_alert"):
            self.check("fields", "u_generating_alert points at the alert", None,
                       "field is not on this instance, mapping not exercised")
            return
        response = self.push("fields-genalert", direct_to_incident="true",
                             dti_wait_for_incident="true", usbem_wait_seconds="45")
        incident_sys_id = response.get("incident_sys_id", "")
        alert_sys_id = response.get("alert_sys_id", "")
        if not incident_sys_id:
            self.check("fields", "u_generating_alert points at the alert", False,
                       f"no incident: {response.get('dti_incident_status')}")
            return
        if not alert_sys_id:
            alerts = self.wait_alert(self.key("fields-genalert"))
            alert_sys_id = alerts[0]["sys_id"] if alerts else ""
        row = self.sn.record("incident", incident_sys_id, "u_generating_alert")
        self.check("fields", "u_generating_alert points at the alert",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} alert={alert_sys_id or '(none)'}")

        # The fast path creates the incident before the alert exists, so the reference can only be
        # written when they are linked. A second event for the same key exercises that.
        repeat = self.push("fields-genalert-fast", direct_to_incident="true")
        first_incident = repeat.get("incident_sys_id", "")
        self.wait_alert(self.key("fields-genalert-fast"))
        again = self.push("fields-genalert-fast", direct_to_incident="true")
        incident_sys_id = again.get("incident_sys_id", "") or first_incident
        alerts = self.alerts_for(self.key("fields-genalert-fast"))
        alert_sys_id = alerts[0]["sys_id"] if alerts else ""
        time.sleep(3)
        row = self.sn.record("incident", incident_sys_id, "u_generating_alert") if incident_sys_id else {}
        self.check("fields", "u_generating_alert set on a fast-path incident",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} "
                   f"alert={alert_sys_id or '(none)'} link={again.get('alert_link_status')}")

    def group_ci(self) -> None:
        """The assignment group chain against a real CI: payload beats the CI's support_group,
        which beats the level 2 tier. Needs read on cmdb_rel_ci, or CI resolution throws before
        any of this runs."""
        cis = self.sn.table("cmdb_ci_server", "operational_status=1^nameISNOTEMPTY", "sys_id,name", 5)
        groups = self.sn.table("sys_user_group", "active=true", "sys_id,name", 3)
        if not cis or len(groups) < 3:
            self.check("ci", "fixtures available", False,
                       f"{len(cis)} server CI(s), {len(groups)} group(s)")
            return
        ci, (level2, support, payload) = cis[0], groups[:3]
        has_tier_field = self.field_exists("cmdb_ci", "u_level_2_support_assignee_group")
        original = self.sn.record("cmdb_ci", ci["sys_id"],
                                  "support_group,u_level_2_support_assignee_group"
                                  if has_tier_field else "support_group")

        def incident_group(case: str, **extra):
            response = self.push(case, node=ci["name"], direct_to_incident="true", **extra)
            sys_id = response.get("incident_sys_id", "")
            if not sys_id:
                return response, {}
            return response, self.sn.record("incident", sys_id, "assignment_group,cmdb_ci",
                                            display="all")

        def display(row, field):
            cell = row.get(field)
            return (cell.get("display_value") if isinstance(cell, dict) else cell) or ""

        try:
            blank = {"support_group": ""}
            if has_tier_field:
                blank["u_level_2_support_assignee_group"] = ""
            self.sn.update("cmdb_ci", ci["sys_id"], blank)

            response, row = incident_group("ci-baseline")
            resolved_ci = display(row, "cmdb_ci")
            self.check("ci", "event node resolves to the CI", resolved_ci == ci["name"],
                       f"cmdb_ci={resolved_ci or '(none)'} (sent node={ci['name']})")
            self.check("ci", "no group when the CI has none", not display(row, "assignment_group"),
                       f"assignment_group={display(row, 'assignment_group') or '(empty)'}")

            if has_tier_field:
                self.sn.update("cmdb_ci", ci["sys_id"],
                               {"u_level_2_support_assignee_group": level2["sys_id"]})
                response, row = incident_group("ci-level2")
                self.check("ci", "level 2 tier is used", display(row, "assignment_group") == level2["name"],
                           f"{display(row, 'assignment_group') or '(empty)'} (expected {level2['name']})")
            else:
                self.check("ci", "level 2 tier is used", None,
                           "cmdb_ci.u_level_2_support_assignee_group is not on this instance")

            self.sn.update("cmdb_ci", ci["sys_id"], {"support_group": support["sys_id"]})
            response, row = incident_group("ci-support")
            self.check("ci", "support_group beats the level 2 tier",
                       display(row, "assignment_group") == support["name"],
                       f"{display(row, 'assignment_group') or '(empty)'} (expected {support['name']})")

            response, row = incident_group("ci-payload", assignment_group=payload["name"])
            self.check("ci", "payload group beats the CI",
                       display(row, "assignment_group") == payload["name"],
                       f"{display(row, 'assignment_group') or '(empty)'} (expected {payload['name']})")

            # Last resort: nothing on the payload, nothing on the CI, but the alert already
            # carries a group. On a real instance that group comes from an Event Management alert
            # rule; here the harness puts it on the alert directly, because whether this PDI has
            # such a rule is not what is being tested. Only the wait path can reach this tier -
            # the fast path creates the incident before there is an alert to read.
            self.sn.update("cmdb_ci", ci["sys_id"],
                           {"support_group": "", "u_level_2_support_assignee_group": ""}
                           if has_tier_field else {"support_group": ""})
            self.push("ci-alertgroup", node=ci["name"], severity="3")   # non-DTI: just make the alert
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
                    got = display(row, "assignment_group")
                    self.check("ci", "the alert's own group is the last resort",
                               got == level2["name"] and response.get("assignment_group_source") == "alert",
                               f"{got or '(empty)'} (expected {level2['name']}) "
                               f"source={response.get('assignment_group_source') or '(absent)'}")
        finally:
            restore = {"support_group": original.get("support_group", "") or ""}
            if has_tier_field:
                restore["u_level_2_support_assignee_group"] = \
                    original.get("u_level_2_support_assignee_group", "") or ""
            self.sn.update("cmdb_ci", ci["sys_id"], restore)
            back = self.sn.record("cmdb_ci", ci["sys_id"], ",".join(restore))
            self.check("ci", "CI restored",
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
        self.check("notes", "connector note on the incident",
                   "Direct To Incident Via Event Management Generic JSON Endpoint" in notes,
                   notes.splitlines()[0] if notes else "no work notes")
        self.check("notes", "sender work_notes on the incident",
                   "sender note for the incident" in notes,
                   "yes" if "sender note for the incident" in notes else "missing")

        # The fast path creates the incident before the alert exists, so its created-from line can
        # only name the message key. The wait path has the alert in hand, and there the line must
        # carry the alert's number - that is what the subflow wrote.
        waited = self.push("notes-createdfrom", direct_to_incident="true",
                           dti_wait_for_incident="true", usbem_wait_seconds="45")
        if waited.get("incident_sys_id"):
            alert_number = waited.get("alert_number", "")
            if not alert_number:
                alerts = self.wait_alert(self.key("notes-createdfrom"))
                alert_number = alerts[0]["number"] if alerts else ""
            waited_notes = self.journal("incident", waited["incident_sys_id"])
            self.check("notes", "created-from names the alert",
                       bool(alert_number) and f"Incident Created From {alert_number}" in waited_notes,
                       f"looked for 'Incident Created From {alert_number or '(no alert)'}'")
        else:
            self.check("notes", "created-from names the alert", False,
                       f"no incident: {waited.get('dti_incident_status')}")

        legacy = self.push("notes-legacy", direct_to_incident="true",
                           dti_work_note="legacy note via dti_work_note")
        if legacy.get("incident_sys_id"):
            legacy_notes = self.journal("incident", legacy["incident_sys_id"])
            self.check("notes", "legacy dti_work_note reaches the incident",
                       "legacy note via dti_work_note" in legacy_notes,
                       "written" if "legacy note via dti_work_note" in legacy_notes else "missing")
        else:
            self.check("notes", "legacy dti_work_note reaches the incident", False,
                       f"no incident: {legacy.get('dti_incident_status')}")

        repeat = self.push("notes-incident", direct_to_incident="true",
                           work_notes="second sender note")
        time.sleep(2)
        notes = self.journal("incident", sys_id)
        written = "Duplicate event received" in notes and "second sender note" in notes
        skipped = str(repeat.get("incident_work_note", "")) == "skipped"
        # Annotating an incident that already exists needs write access to the incident table.
        # Where the scope has it this must be written; where it does not, the connector reports
        # the skip instead of failing the event, which is a reported state, not a regression.
        self.check("notes", "reuse adds a duplicate note", True if written else (None if skipped else False),
                   f"status={repeat.get('dti_incident_status')}" if written else
                   (f"skipped: {repeat.get('incident_work_note_skipped_reason')} - grant the scope "
                    "write on incident" if skipped else "no duplicate note and no skip reported"))

        self.push("notes-alert", alert_work_notes="sender note for the alert")
        alerts = self.wait_alert(self.key("notes-alert"))
        if alerts:
            time.sleep(3)
            alert_notes = self.journal("em_alert", alerts[0]["sys_id"])
            self.check("notes", "alert_work_notes on the alert",
                       "sender note for the alert" in alert_notes,
                       alerts[0]["number"] + (": written" if "sender note for the alert" in alert_notes
                                              else ": missing"))
        else:
            self.check("notes", "alert_work_notes on the alert", False, "no alert created")

        # Regression guard. The note travels in the alert's additional_info, and the reconcile rule
        # runs on every alert write, so a connector that does not consume the key re-posts the same
        # note on writes that never asked for one. One event carries the note; the writes that
        # follow do not, and must not produce a second copy of it.
        self.push("notes-alert-once", alert_work_notes="post me exactly once")
        alerts = self.wait_alert(self.key("notes-alert-once"))
        if not alerts:
            self.check("notes", "the note is not re-posted on later alert writes", False,
                       "no alert created")
        else:
            alert_sys_id = alerts[0]["sys_id"]
            time.sleep(4)
            self.push("notes-alert-once", severity="2")      # same key, no note on the payload
            time.sleep(4)
            # ...and a write that has nothing to do with Event Management's event pipeline.
            self.sn.update("em_alert", alert_sys_id, {"description": "touched by verification"})
            time.sleep(4)
            entries = [e for e in self.journal("em_alert", alert_sys_id).splitlines()
                       if "post me exactly once" in e]
            self.check("notes", "the note is not re-posted on later alert writes", len(entries) == 1,
                       f"{alerts[0]['number']}: {len(entries)} copies of the note after two "
                       f"further alert writes")

        # A DTI sender's plain work_notes belongs to the incident, not to the alert as well.
        dti_note = self.push("notes-dti-plain", direct_to_incident="true",
                             work_notes="incident only, not the alert")
        alerts = self.wait_alert(self.key("notes-dti-plain"))
        if alerts and dti_note.get("incident_sys_id"):
            time.sleep(4)
            on_alert = "incident only, not the alert" in self.journal("em_alert", alerts[0]["sys_id"])
            on_incident = "incident only, not the alert" in self.journal("incident", dti_note["incident_sys_id"])
            self.check("notes", "a DTI work_notes does not also land on the alert",
                       on_incident and not on_alert,
                       f"incident={on_incident} alert={on_alert}")

        self.push("notes-alert-plain", work_notes="plain note, no incident")
        alerts = self.wait_alert(self.key("notes-alert-plain"))
        if alerts:
            time.sleep(3)
            alert_notes = self.journal("em_alert", alerts[0]["sys_id"])
            self.check("notes", "work_notes reach a non-DTI alert",
                       "plain note, no incident" in alert_notes,
                       alerts[0]["number"] + (": written" if "plain note, no incident" in alert_notes
                                              else ": missing"))
        else:
            self.check("notes", "work_notes reach a non-DTI alert", False, "no alert created")

    def group_edge(self) -> None:
        # incident.correlation_id is String(100) but em_alert.message_key holds 1024, so a long
        # key cannot round-trip through correlation_id. The connector must still converge on one
        # incident for that key rather than opening one per event.
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
        open_incidents = [i for i in self.sn.table(
            "incident", f"correlation_idSTARTSWITH{self.prefix}-edge-long^stateNOT IN6,7,8",
            "sys_id,number", 20)]
        self.check("edge", "long message key converges on one incident",
                   len(set(n for n in numbers if n)) == 1 and len(open_incidents) <= 1,
                   f"returned {numbers}, {len(open_incidents)} open incident(s), statuses {statuses}")

        # Two events for one key at the same instant. There is no duplicate protection on the fast
        # path, so this is reported, not failed - but a regression that opens three would show.
        concurrent_key = self.key("edge-concurrent")
        payload = self.payload("edge-concurrent", direct_to_incident="true")
        clients = [ServiceNow(self.sn.instance, self.sn.user, self.sn._password) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda c: c.push_event(payload), clients))
        distinct = sorted(set(r.get("incident_number", "") for r in responses))
        self.check("edge", "concurrent events for one key", None,
                   f"returned {distinct}, statuses "
                   f"{[r.get('dti_incident_status') for r in responses]}")
        _ = concurrent_key

        # A batch where only one record asks for an incident: the batch must still answer for
        # every record, and only that record may produce an incident.
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

    # ------------------------------------------------------------------ cleanup
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", choices=GROUPS, help="run only these groups")
    parser.add_argument("--keep", action="store_true", help="do not delete what the run created")
    parser.add_argument("--prefix", help="tag for the records this run creates")
    parser.add_argument("--alert-wait", type=int, default=120,
                        help="seconds to wait for Event Management to produce an alert")
    parser.add_argument("--json", dest="json_out", help="write the results to this file as JSON")
    parser.add_argument("--env-file", help="path to a .env holding the credentials")
    parser.add_argument("--version", action="version", version="verify_usbem_connector " + VERSION)
    args = parser.parse_args()

    sn = ServiceNow(*load_credentials(args.env_file))
    prefix = args.prefix or f"ZZUSBEM-{int(time.time())}"
    verifier = Verifier(sn, prefix, args.alert_wait)
    groups = args.only or list(GROUPS)

    print(f"USBEM connector verification {VERSION} (release {RELEASE})")
    print(f"instance {sn.instance}")
    print(f"prefix   {prefix}\n")

    for group in GROUPS:
        if group not in groups:
            continue
        print(f"== {group} ==")
        try:
            getattr(verifier, "group_" + group)()
        except ServiceNowError as exc:
            verifier.check(group, "group completed", False, str(exc)[:200])
        except Exception as exc:  # a broken check must not hide the groups after it
            verifier.check(group, "group completed", False, f"{type(exc).__name__}: {exc}"[:200])

    if args.keep:
        print(f"\nkept every record tagged {prefix}")
    else:
        print("\ncleanup:", verifier.cleanup())

    passed = sum(1 for row in verifier.rows if row["passed"] is True)
    failed = [row for row in verifier.rows if row["passed"] is False]
    observations = sum(1 for row in verifier.rows if row["passed"] is None)
    print(f"\n{passed} passed, {len(failed)} failed, {observations} observation(s)")
    for row in failed:
        print(f"  FAILED {row['group']} {row['name']}: {row['observed']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "version": VERSION, "release": RELEASE, "instance": sn.instance,
            "prefix": prefix, "rows": verifier.rows}, indent=2))
        print(f"\nresults written to {args.json_out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
