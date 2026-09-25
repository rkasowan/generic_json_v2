#!/usr/bin/env python3
"""Deploy the USBEM genericJsonV2 connector to a ServiceNow instance.

Pushes each source file to the record that runs it, reads the record back, and reports the
version each component reports. Only three kinds of record are touched: Script Includes, the
push connector listener, and the reconcile business rule.

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python3 scripts/deploy_usbem.py            # deploy what differs
    python3 scripts/deploy_usbem.py --dry-run  # show what would change
    python3 scripts/deploy_usbem.py --force    # rewrite every record

Credentials and TLS options: see scripts/usbem_client.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usbem_client import ServiceNow, ServiceNowError, load_credentials  # noqa: E402

VERSION = "2026.09.25.3"
PROJECT = Path(__file__).resolve().parents[1]
SCOPE = "x_usbna_usb_event"

# The reconcile rule's configuration is part of the deliverable: an `after` rule (Event
# Management best practices forbid async rules on alert tables) that is filtered down to the
# alerts this connector cares about before its script runs.
BR_CONDITION = (
    "(current.additional_info.indexOf('direct_to_incident') > -1 || "
    "current.additional_info.indexOf('work_notes') > -1) && "
    "(current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)"
)

COMPONENTS = [
    {
        "label": "USBEM_Core",
        "table": "sys_script_include",
        "query": "name=USBEM_Core^sys_scope.scope=" + SCOPE,
        "sys_id": "e2734f2bc38c4f100bc1b91ed401319c",
        "file": "src/USBEM_Core.js",
        "script_field": "script",
    },
    {
        "label": "USBEM_Lookups",
        "table": "sys_script_include",
        "query": "name=USBEM_Lookups^sys_scope.scope=" + SCOPE,
        "sys_id": "8063cba7c38c4f100bc1b91ed401310a",
        "file": "src/USBEM_Lookups.js",
        "script_field": "script",
    },
    {
        "label": "USBEM_Debug",
        "table": "sys_script_include",
        "query": "name=USBEM_Debug^sys_scope.scope=" + SCOPE,
        "sys_id": "ae23cba7c38c4f100bc1b91ed4013117",
        "file": "src/USBEM_Debug.js",
        "script_field": "script",
    },
    {
        "label": "USBEM_DTI",
        "table": "sys_script_include",
        "query": "name=USBEM_DTI^sys_scope.scope=" + SCOPE,
        "sys_id": "5643c32bc38c4f100bc1b91ed40131e7",
        "file": "src/USBEM_DTI.js",
        "script_field": "script",
    },
    {
        "label": "listener USBEM genericJsonV2",
        "table": "sn_em_connector_listener",
        "query": "source=genericJsonV2",
        "sys_id": "ec08e3e7c3848f100bc1b91ed40131ef",
        "file": "servicenow/USBEM_genericJsonV2.listener.js",
        "script_field": "script",
        "config": {"active": "true", "type": "1"},
    },
    {
        "label": "business rule USBEM Fast DTI Alert Reconcile",
        "table": "sys_script",
        "query": "name=USBEM Fast DTI Alert Reconcile^collection=em_alert",
        "sys_id": "26dcd72193a78710c8ebf85bdd03d613",
        "file": "servicenow/USBEM_FastDtiAlertReconcile.business_rule.js",
        "script_field": "script",
        "create_if_missing": {
            "name": "USBEM Fast DTI Alert Reconcile",
            "collection": "em_alert",
        },
        "config": {
            "when": "after",
            "action_insert": "true",
            "action_update": "true",
            "action_delete": "false",
            "action_query": "false",
            "order": "150",
            "active": "true",
            "condition": BR_CONDITION,
            "abort_action": "false",
            "add_message": "false",
        },
    },
]


def normalize(text: str) -> str:
    """ServiceNow stores whatever it is given; compare without line-ending noise."""
    return (text or "").replace("\r\n", "\n").rstrip("\n")


def find_record(sn: ServiceNow, component: dict) -> dict | None:
    fields = "sys_id,name," + component["script_field"]
    extra = sorted(component.get("config", {}).keys())
    if extra:
        fields += "," + ",".join(extra)
    rows = sn.table(component["table"], component["query"], fields, limit=5)
    if rows:
        if len(rows) > 1:
            print(f"  ! {component['label']}: {len(rows)} records match, using the first")
        return rows[0]
    try:
        row = sn.record(component["table"], component["sys_id"], fields)
    except ServiceNowError:
        return None
    return row or None


def deploy(sn: ServiceNow, dry_run: bool, force: bool) -> int:
    failures = 0
    print(f"USBEM deploy {VERSION} -> {sn.instance}")
    print(f"{'component':<46} {'action':<12} {'bytes':>7}  record")
    print("-" * 96)

    for component in COMPONENTS:
        path = PROJECT / component["file"]
        source = path.read_text(encoding="utf-8")
        record = find_record(sn, component)

        if record is None:
            if not component.get("create_if_missing"):
                print(f"{component['label']:<46} {'MISSING':<12} {'':>7}  create it first "
                      f"(see docs/install_from_scratch.md)")
                failures += 1
                continue
            if dry_run:
                print(f"{component['label']:<46} {'would create':<12} {len(source):>7}")
                continue
            payload = dict(component["create_if_missing"])
            payload.update(component.get("config", {}))
            payload[component["script_field"]] = source
            record = sn.insert(component["table"], payload)
            print(f"{component['label']:<46} {'created':<12} {len(source):>7}  {record.get('sys_id','')}")
            continue

        sys_id = record["sys_id"]
        payload = {}
        script_changed = normalize(record.get(component["script_field"], "")) != normalize(source)
        if script_changed or force:
            payload[component["script_field"]] = source
        for field, want in component.get("config", {}).items():
            if str(record.get(field, "")) != str(want) or force:
                payload[field] = want

        if not payload:
            print(f"{component['label']:<46} {'up to date':<12} {len(source):>7}  {sys_id}")
            continue
        if dry_run:
            print(f"{component['label']:<46} {'would write':<12} {len(source):>7}  {sys_id} "
                  f"({', '.join(sorted(payload))})")
            continue

        sn.update(component["table"], sys_id, payload)
        back = sn.record(component["table"], sys_id,
                         "sys_id," + component["script_field"] +
                         ("," + ",".join(sorted(component.get("config", {}))) if component.get("config") else ""))
        ok = normalize(back.get(component["script_field"], "")) == normalize(source)
        mismatched = [f for f, want in component.get("config", {}).items()
                      if str(back.get(f, "")) != str(want)]
        status = "written" if ok and not mismatched else "MISMATCH"
        if status == "MISMATCH":
            failures += 1
        detail = "" if ok else " script differs after write"
        if mismatched:
            detail += " fields not applied: " + ",".join(mismatched)
        print(f"{component['label']:<46} {status:<12} {len(source):>7}  {sys_id}{detail}")

    return failures


def report_versions(sn: ServiceNow) -> None:
    """Ask the live endpoint what it is running. This is the check that catches a stale copy."""
    payload = {
        "source": "usbem-deploy", "event_class": "usbem-deploy", "node": "usbem-deploy",
        "resource": "version-probe", "metric_name": "version_probe", "severity": "0",
        "message_key": "USBEM-DEPLOY-VERSION-PROBE", "description": "deploy version probe",
    }
    try:
        response = sn.push_event(payload)
    except ServiceNowError as exc:
        print("version probe failed: " + str(exc))
        return
    versions = response.get("versions") or {}
    print("\nversions reported by the live endpoint:")
    if not versions:
        print("  none - the listener on this instance predates version reporting")
    for name in sorted(versions):
        flag = "" if versions[name] == VERSION else "   <- not " + VERSION
        print(f"  {name:<10} {versions[name]}{flag}")
    event_sys_id = response.get("event_sys_id") or ""
    if event_sys_id:
        try:
            sn.delete("em_event", event_sys_id)
            print("  (probe event removed)")
        except ServiceNowError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    parser.add_argument("--force", action="store_true", help="rewrite every record")
    parser.add_argument("--env-file", help="path to a .env holding the credentials")
    parser.add_argument("--version", action="version", version="deploy_usbem " + VERSION)
    args = parser.parse_args()

    sn = ServiceNow(*load_credentials(args.env_file))
    failures = deploy(sn, args.dry_run, args.force)
    if not args.dry_run:
        report_versions(sn)
    if failures:
        print(f"\n{failures} component(s) did not deploy cleanly")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
