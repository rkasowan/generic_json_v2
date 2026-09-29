#!/usr/bin/env python3
"""Deploy the USBEM genericJsonV2 connector to a ServiceNow instance.

Pushes each source file to the record that runs it, reads the record back, and reports the
version each component reports. Only three kinds of record are touched: Script Includes, the
push connector listener, and the reconcile business rule.

    python3 scripts/deploy_usbem.py            # deploy what differs
    python3 scripts/deploy_usbem.py --dry-run  # show what would change
    python3 scripts/deploy_usbem.py --force    # rewrite every record

Standard library only, nothing to install. It does need the repo, because the repo is what it
deploys: run it from the checkout, or point --repo at one.

Credentials come from --instance/--user/--password, the environment (servicenow_instance /
servicenow_user / servicenow_password), or a .env — the one named by --env-file, or the nearest
one at or above the current directory. Certificates are verified; --ca-bundle trusts a corporate
root and --insecure skips verification as a last resort.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

VERSION = "2026.09.28.1"
EXPECTED_RELEASE = "2026.09.28.1"

MARK = "@@JSON@@"
INSTANCE_KEYS = ("servicenow_instance", "SN_INSTANCE_URL", "SN_INSTANCE", "instance")
USER_KEYS = ("servicenow_user", "SN_USERNAME", "SN_USER", "user")
PASSWORD_KEYS = ("servicenow_password", "SN_PASSWORD", "password")

# Optional: used if installed, because requests ships a CA bundle. Not required.
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
    parser.add_argument("--repo", help="the checkout to deploy from (default: this script's repo)")
    parser.add_argument("--instance", default="", help="https://<instance>.service-now.com")
    parser.add_argument("--user", default="", help="an admin account")
    parser.add_argument("--password", default="")
    parser.add_argument("--env-file", help="a .env holding the credentials")
    parser.add_argument("--ca-bundle", default="", help="PEM file to trust (a corporate root)")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification, last resort")
    parser.add_argument("--version", action="version", version="deploy_usbem " + VERSION)
    args = parser.parse_args()

    instance, user, password = resolve_credentials(args)
    sn = ServiceNow(instance, user, password, ca_bundle=args.ca_bundle, insecure=args.insecure)
    global PROJECT
    if args.repo:
        PROJECT = Path(args.repo).expanduser().resolve()
    if not (PROJECT / "src" / "USBEM_DTI.js").is_file():
        sys.exit(f"{PROJECT} does not look like the generic_json_v2 checkout "
                 "(src/USBEM_DTI.js is missing); pass --repo")
    failures = deploy(sn, args.dry_run, args.force)
    if not args.dry_run:
        report_versions(sn)
    if failures:
        print(f"\n{failures} component(s) did not deploy cleanly")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
