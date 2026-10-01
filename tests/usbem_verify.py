#!/usr/bin/env python3
"""USBEM genericJsonV2 — API functionality test, in one file.

Tests the inbound event API and nothing else. It writes only uniquely tagged events, alerts,
and incidents. Standard profile attempts cleanup; limited production profile retains its records
because the caller may not have delete access. It does not modify CMDB records or configuration.

The script uses Python's standard library. Production URLs, OAuth credentials, and fixture values
come from one ignored `tests/usbem_verify.env` file. A custom target can use `--instance` and
`--user` / `--password`. On macOS, it uses `/usr/bin/curl` with Apple SecureTransport when
available so a venv honors local Keychain trust roots; elsewhere it uses `requests` when installed
and otherwise Python's verified TLS defaults.

    python3 usbem_verify.py --instance https://xxx.service-now.com --user admin --password '...'
    python3 usbem_verify.py --only fast --only notes
    python3 usbem_verify.py --source firstGenericJson --contract legacy
    python3 usbem_verify.py --access-profile limited
    python3 usbem_verify.py --keep                # leave the records it creates
    python3 usbem_verify.py --json out.json       # machine-readable results

With no --instance, the verifier prompts you to choose one of the four production instances and
uses that instance's URL and OAuth credentials from `tests/usbem_verify.env`. Shared fixture
values and that instance's caller/assignee fixtures come from the same file.

Terminal incident transitions use only the caller's Incident API access. If an ACL blocks a
transition, that state case is reported as skipped; the verifier never uses Scripts - Background.

TLS: certificates are verified. If you see CERTIFICATE_VERIFY_FAILED, either
`pip install certifi`, or pass --ca-bundle /path/root.pem for a corporate root, or --insecure.

Use --source to select a different push connector. For the original PDI listener, run
`--source firstGenericJson --contract legacy`. Production instances can use the
same command with their original listener source value. The default source is `genericJsonV2`.

For restricted production users, `--access-profile limited` submits events through the connector
and verifies through Incident/Alert readback. Fixture values load from `tests/usbem_verify.env`;
blank values make only their fixture-driven checks report as skipped. The notes group prints record numbers and prompts for manual checks without querying
`sys_journal_field`. The profile avoids Scripts - Background and deletion, and retains created records.

GROUPS (--only <name>, repeatable):
    compat   response envelope, event acceptance (plus event-row readback in standard mode),
             alert, no incident without DTI, batches, and the
             modern listener's legacy dti_ field aliases; legacy mode tests original event/batch
             compatibility without modern-only DTI assertions
    payload_contract old payload containers, camelCase aliases, and both additional_info forms;
             asserts readback through alerts (no em_event table ACL required)
    lookups  optional fixture-driven CI, assignment-group, service, and offering resolution,
             verified on incidents through the caller's Incident read access
    fast     direct_to_incident returns an incident immediately, reuses it while open, resolves it
             with the required closure fields, opens a new incident, and links the alert
    fields   NetCool, default/overridden category and subcategory, caller_id by sys_id/name,
             severity tiers, and other incident overrides
    notes    manually verify incident and alert work notes using printed record numbers
    edge     message keys longer than correlation_id, concurrent events, DTI inside a batch
    timing   round-trip milliseconds per path, reported not failed
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import ssl
import subprocess
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = "2026.09.30.1"
EXPECTED_RELEASE = "2026.09.30.1"      # what the live endpoint should report; --expect-version overrides

RESOLVED_STATE = ("6", "Resolved")
RESOLUTION_FIELDS = {
    "close_code": "Solved (Permanently)",
    "u_cause": "Abandoned",
    "close_notes": "Testing DTI",
}
GROUPS = ("compat", "payload_contract", "fast", "fields", "lookups", "notes", "edge", "timing")
DEFAULT_SOURCE = "genericJsonV2"
PRODUCTION_INSTANCES = ("itsmnowDEVworker", "itsmnowITworker",
                        "itsmnowUATworker", "itsmnowworker")

# Fixture values are kept outside this script so script updates preserve per-instance setup.
FIXTURE_ENV_KEYS = {
    "ci_name": "USBEM_FIXTURE_CI_NAME",
    "ci_sys_id": "USBEM_FIXTURE_CI_SYS_ID",
    "ci_type": "USBEM_FIXTURE_CI_TYPE",
    "ci_identifier": "USBEM_FIXTURE_CI_IDENTIFIER",
    "assignment_group": "USBEM_FIXTURE_ASSIGNMENT_GROUP",
    "ci_support_group": "USBEM_FIXTURE_CI_SUPPORT_GROUP",
    "service_name": "USBEM_FIXTURE_SERVICE_NAME",
    "service_sys_id": "USBEM_FIXTURE_SERVICE_SYS_ID",
    "offering_name": "USBEM_FIXTURE_OFFERING_NAME",
    "offering_sys_id": "USBEM_FIXTURE_OFFERING_SYS_ID",
    "business_app_car_id": "USBEM_FIXTURE_BUSINESS_APP_CAR_ID",
    "caller_sys_id": "USBEM_FIXTURE_CALLER_SYS_ID",
    "caller_full_name": "USBEM_FIXTURE_CALLER_FULL_NAME",
    "caller_first_name": "USBEM_FIXTURE_CALLER_FIRST_NAME",
    "caller_last_name": "USBEM_FIXTURE_CALLER_LAST_NAME",
    "assigned_to_sys_id": "USBEM_FIXTURE_ASSIGNED_TO_SYS_ID",
    "assigned_to_full_name": "USBEM_FIXTURE_ASSIGNED_TO_FULL_NAME",
    "assigned_to_first_name": "USBEM_FIXTURE_ASSIGNED_TO_FIRST_NAME",
    "assigned_to_last_name": "USBEM_FIXTURE_ASSIGNED_TO_LAST_NAME",
    "default_caller_sys_id": "USBEM_FIXTURE_DEFAULT_CALLER_SYS_ID",
    "ambiguous_caller_full_name": "USBEM_FIXTURE_AMBIGUOUS_CALLER_FULL_NAME",
}
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


def load_fixtures(values=None, instance_name="") -> tuple[dict, list[str]]:
    """Load common and selected-instance fixture values from the unified config."""
    merged_values = dict(values or {})
    fixtures = {key: "" for key in FIXTURE_ENV_KEYS}
    fixtures["ci_identifier"] = {}
    configured = []
    slug = re.sub(r"[^A-Za-z0-9]", "", instance_name).upper()
    for name, env_key in FIXTURE_ENV_KEYS.items():
        profile_key = (f"USBEM_{slug}_{env_key.removeprefix('USBEM_')}"
                       if instance_name else "")
        raw = (os.environ.get(profile_key) if profile_key else "") or \
              merged_values.get(profile_key, "") or os.environ.get(env_key, "") or \
              merged_values.get(env_key, "")
        raw = raw.strip()
        if not raw:
            continue
        if name == "ci_identifier":
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise ValueError(f"{env_key} must be a JSON object") from None
            if not isinstance(parsed, dict):
                raise ValueError(f"{env_key} must be a JSON object")
            fixtures[name] = parsed
        else:
            fixtures[name] = raw
        configured.append(name)

    for name in ("caller", "assigned_to"):
        full_name_key = name + "_full_name"
        if not fixtures[full_name_key]:
            first_name = fixtures[name + "_first_name"]
            last_name = fixtures[name + "_last_name"]
            if first_name and last_name:
                fixtures[full_name_key] = f"{first_name} {last_name}".strip()
                configured.append(full_name_key)
    return fixtures, configured


def production_url(instance_name: str, values=None) -> str:
    """Read and validate a production URL from the unified config or its env override."""
    slug = re.sub(r"[^A-Za-z0-9]", "", instance_name).upper()
    key = f"USBEM_{slug}_URL"
    url = (os.environ.get(key) or (values or {}).get(key, "")).strip().rstrip("/")
    if not url:
        raise ValueError(f"set {key} in tests/usbem_verify.env; copy "
                         "tests/usbem_verify.env.example first")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{key} must be a full https:// URL")
    return url


def select_instance(requested: str, config_values=None) -> tuple[str, str]:
    """Prompt for a configured production target, or normalize a custom instance URL."""
    config_values = config_values or {}
    if not requested:
        if not sys.stdin.isatty():
            raise ValueError("choose an instance interactively or pass --instance")
        print("Select the ServiceNow instance to test:")
        for index, name in enumerate(PRODUCTION_INSTANCES, start=1):
            print(f"  {index}. {name}")
        choice = input("Instance [1-4]: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(PRODUCTION_INSTANCES):
            raise ValueError("enter a number from 1 to 4")
        name = PRODUCTION_INSTANCES[int(choice) - 1]
        return name, production_url(name, config_values)

    value = requested.strip()
    candidate_url = value if value.lower().startswith(("http://", "https://")) else "https://" + value
    requested_host = (urllib.parse.urlparse(candidate_url).hostname or "").casefold()
    for name in PRODUCTION_INSTANCES:
        try:
            url = production_url(name, config_values)
        except ValueError:
            url = ""
        if value.casefold() == name.casefold():
            if not url:
                return name, production_url(name, config_values)
            return name, url
        if not url:
            continue
        known_host = urllib.parse.urlparse(url).hostname or ""
        if requested_host == known_host.casefold():
            return name, url
    return "", candidate_url.rstrip("/")


def resolve_credentials(args, instance: str, instance_name: str = "", config_values=None) -> dict:
    """Resolve one selected instance's OAuth credentials, or Basic auth for a custom target."""
    config_values = config_values or {}
    if instance_name and (args.user or args.password):
        sys.exit("the four production profiles use their per-instance OAuth credentials; "
                 "remove --user/--password")
    if args.user or args.password:
        if not args.user or not args.password:
            sys.exit("Basic auth requires both --user and --password")
        return {"mode": "basic", "user": args.user, "password": args.password}

    env_values = dict(os.environ)
    if instance_name:
        slug = re.sub(r"[^A-Za-z0-9]", "", instance_name).upper()
        oauth_id = (env_values.get(f"USBEM_{slug}_OAUTH_CLIENT_ID") or
                    config_values.get(f"USBEM_{slug}_OAUTH_CLIENT_ID", ""))
        oauth_secret = (env_values.get(f"USBEM_{slug}_OAUTH_CLIENT_SECRET") or
                        config_values.get(f"USBEM_{slug}_OAUTH_CLIENT_SECRET", ""))
        oauth_scope = (env_values.get(f"USBEM_{slug}_OAUTH_SCOPE") or
                       config_values.get(f"USBEM_{slug}_OAUTH_SCOPE", ""))
        if not oauth_id or not oauth_secret:
            sys.exit(f"OAuth client ID/secret are missing for {instance_name}; fill "
                     f"USBEM_{slug}_OAUTH_CLIENT_ID and USBEM_{slug}_OAUTH_CLIENT_SECRET "
                     "in tests/usbem_verify.env")
        return {"mode": "oauth", "client_id": oauth_id,
                "client_secret": oauth_secret, "scope": oauth_scope}

    oauth_id = env_values.get("USBEM_OAUTH_CLIENT_ID") or config_values.get("USBEM_OAUTH_CLIENT_ID", "")
    oauth_secret = env_values.get("USBEM_OAUTH_CLIENT_SECRET") or config_values.get("USBEM_OAUTH_CLIENT_SECRET", "")
    oauth_scope = env_values.get("USBEM_OAUTH_SCOPE") or config_values.get("USBEM_OAUTH_SCOPE", "")
    if oauth_id or oauth_secret:
        if not oauth_id or not oauth_secret:
            sys.exit("OAuth authentication requires USBEM_OAUTH_CLIENT_ID and "
                     "USBEM_OAUTH_CLIENT_SECRET")
        return {"mode": "oauth", "client_id": oauth_id,
                "client_secret": oauth_secret, "scope": oauth_scope}

    sources = [config_values, env_values]

    def first(keys, override):
        if override:
            return override
        for key in keys:
            for source in sources:
                if source.get(key):
                    return source[key]
        return ""

    user = first(USER_KEYS, args.user)
    password = first(PASSWORD_KEYS, args.password)
    missing = [name for name, value in
               (("user", user), ("password", password)) if not value]
    if missing:
        sys.exit("missing credentials: " + ", ".join(missing) + "\n"
                 "  pass --user/--password, set servicenow_user / servicenow_password,\n"
                 "  or point --env-file at a credentials file")
    return {"mode": "basic", "user": user, "password": password}


# --------------------------------------------------------------------------------- HTTP client
class ServiceNowError(RuntimeError):
    pass


class ServiceNow:
    """Table API and inbound-event endpoint client."""

    def __init__(self, instance: str, auth: dict,
                 ca_bundle: str = "", insecure: bool = False, timeout: int = 180) -> None:
        self.instance = instance
        self.auth = dict(auth)
        self.auth_mode = self.auth.get("mode", "basic")
        self.user = self.auth.get("user", "")
        self.password = self.auth.get("password", "")
        self.oauth_client_id = self.auth.get("client_id", "")
        self.oauth_client_secret = self.auth.get("client_secret", "")
        self.oauth_scope = self.auth.get("scope", "")
        self._access_token = ""
        self._access_token_expires_at = 0
        self.timeout = timeout
        self.insecure = insecure
        self.ca_bundle = ca_bundle
        self.context = self._ssl_context()
        self._session = None
        self._macos_curl = self._system_curl_uses_secure_transport()
        if requests is not None and not self._macos_curl:
            self._session = requests.Session()
            self._session.verify = False if insecure else (ca_bundle or (certifi.where() if certifi else True))
            if insecure:
                try:
                    import urllib3  # type: ignore
                    urllib3.disable_warnings()
                except Exception:
                    pass
        if self.auth_mode == "basic":
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            self._basic = "Basic " + token
        else:
            self._basic = ""
            self._ensure_oauth_token()

    @staticmethod
    def _system_curl_uses_secure_transport() -> bool:
        """Use Apple's TLS stack on macOS so Python venvs inherit Keychain trust roots."""
        curl = "/usr/bin/curl"
        if platform.system() != "Darwin" or not os.path.isfile(curl):
            return False
        try:
            result = subprocess.run([curl, "--version"], capture_output=True, text=True,
                                    timeout=5, check=False)
            return result.returncode == 0 and "SecureTransport" in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _curl_config_value(value: str) -> str:
        """Quote one value for curl's stdin config without putting credentials in argv."""
        escaped = (str(value).replace("\\", "\\\\").replace('"', '\\"')
                   .replace("\r", "\\r").replace("\n", "\\n"))
        return '"' + escaped + '"'

    def _request_with_macos_curl(self, method: str, url: str, data, headers):
        """Call system curl through stdin config; SecureTransport reads macOS Keychain roots."""
        config = [
            "request = " + self._curl_config_value(method),
            "url = " + self._curl_config_value(url),
        ]
        for name, value in headers.items():
            config.append("header = " + self._curl_config_value(name + ": " + str(value)))
        if data is not None:
            config.append("data-binary = " + self._curl_config_value(data.decode("utf-8")))

        command = ["/usr/bin/curl", "-q", "--config", "-", "--silent", "--show-error",
                   "--write-out", "\n__USBEM_HTTP_STATUS__:%{http_code}"]
        if self.insecure:
            command.append("--insecure")
        if self.ca_bundle:
            command.extend(["--cacert", self.ca_bundle])
        try:
            result = subprocess.run(command, input=("\n".join(config) + "\n").encode("utf-8"),
                                    capture_output=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ServiceNowError("macOS SecureTransport request timed out") from None
        except OSError as error:
            raise ServiceNowError("could not start system curl: " + str(error)) from None

        output = result.stdout.decode("utf-8", "replace")
        marker = "\n__USBEM_HTTP_STATUS__:"
        if marker not in output:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise ServiceNowError("macOS SecureTransport request failed" +
                                  (": " + detail[:300] if detail else ""))
        text, status_text = output.rsplit(marker, 1)
        try:
            status = int(status_text.strip())
        except ValueError:
            raise ServiceNowError("macOS SecureTransport returned no HTTP status") from None
        return status, text

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
    def _ensure_oauth_token(self):
        if self.auth_mode != "oauth":
            return
        if self._access_token and time.time() < self._access_token_expires_at - 60:
            return
        form = {
            "grant_type": "client_credentials",
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
        }
        if self.oauth_scope:
            form["scope"] = self.oauth_scope
        token_response = self._request(
            "POST", f"{self.instance}/oauth_token.do", form=form, token_request=True)
        if not isinstance(token_response, dict) or not token_response.get("access_token"):
            raise ServiceNowError("OAuth token response did not contain an access_token")
        try:
            expires_in = int(token_response.get("expires_in", 1800))
        except (TypeError, ValueError):
            expires_in = 1800
        self._access_token = str(token_response["access_token"])
        self._access_token_expires_at = time.time() + max(60, expires_in)

    def _request(self, method: str, url: str, params=None, body=None, headers=None,
                 form=None, token_request: bool = False):
        headers = dict(headers or {})
        headers.setdefault("Accept", "application/json")
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        if not token_request:
            if self.auth_mode == "oauth":
                self._ensure_oauth_token()
                headers["Authorization"] = "Bearer " + self._access_token
            else:
                headers["Authorization"] = self._basic

        last = None
        for attempt in range(3):
            try:
                if self._macos_curl:
                    status, text = self._request_with_macos_curl(method, url, data, headers)
                elif self._session is not None:
                    response = self._session.request(method, url, data=data, headers=headers,
                                                     timeout=self.timeout)
                    status, text = response.status_code, response.text
                else:
                    request = urllib.request.Request(url, data=data, method=method, headers=headers)
                    with urllib.request.urlopen(request, timeout=self.timeout,
                                                context=self.context) as raw:
                        status, text = raw.status, raw.read().decode("utf-8", "replace")
                if status == 401 and self.auth_mode == "oauth" and not token_request and attempt == 0:
                    self._access_token = ""
                    self._access_token_expires_at = 0
                    self._ensure_oauth_token()
                    headers["Authorization"] = "Bearer " + self._access_token
                    continue
                break
            except urllib.error.HTTPError as error:
                status = error.code
                text = error.read().decode("utf-8", "replace")
                break
            except Exception as error:                       # transport, not HTTP
                message = str(error)
                lowered = message.lower()
                if ("certificate_verify_failed" in lowered or
                        "certificate verify failed" in lowered or
                        ("certificate" in lowered and "curl" in lowered)):
                    trust_hint = ("  macOS uses the system curl SecureTransport trust store and Keychain; "
                                  "confirm the work CA is installed and trusted there\n"
                                  if self._macos_curl else
                                  "  install the corporate CA in the configured Python trust bundle\n")
                    raise ServiceNowError(
                        f"TLS verification failed for {url}\n"
                        f"  {message}\n"
                        + trust_hint +
                        "  --ca-bundle /path/root.pem to use an explicit corporate CA bundle\n"
                        "  --insecure                 to skip verification, last resort") from None
                last = error
                time.sleep(2 * (attempt + 1))
        else:
            raise ServiceNowError(f"{method} {url} failed after 3 attempts: {last}")

        if status >= 400:
            if token_request:
                raise ServiceNowError(f"OAuth token request failed (HTTP {status})")
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

    def update(self, name: str, sys_id: str, payload: dict,
               input_display_value: bool = False):
        params = {"sysparm_input_display_value": "true"} if input_display_value else None
        return self._request("PATCH", f"{self.instance}/api/now/table/{name}/{sys_id}",
                             params=params, body=payload) or {}

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

# --------------------------------------------------------------------------------- verification
class Verifier:
    def __init__(self, sn: ServiceNow, prefix: str, alert_wait: int, expected: str,
                 source: str = DEFAULT_SOURCE, contract: str = "modern",
                 access_profile: str = "standard", fixtures=None) -> None:
        self.sn = sn
        self.prefix = prefix
        self.alert_wait = alert_wait
        self.expected = expected
        self.source = source
        self.contract = contract
        self.access_profile = access_profile
        if fixtures is None:
            fixtures = {key: "" for key in FIXTURE_ENV_KEYS}
            fixtures["ci_identifier"] = {}
        self.fixtures = fixtures
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

        # These synthetic test nodes do not exist in CMDB. Use the configured real CI on DTI
        # events so unrelated incident checks do not all fail insert when the instance requires
        # cmdb_ci. Keep the ciType + ciIdentifier lookup case independent so it still tests that
        # mapping path; explicit cmdbCi inputs are also left untouched.
        direct_to_incident = any(
            str(body.get(key, "")).strip().casefold() in ("true", "1", "yes")
            for key in ("direct_to_incident", "directToIncident")
        )
        has_ci_input = any(str(body.get(key, "")).strip()
                           for key in ("cmdb_ci", "cmdbCi"))
        tests_ci_identifier = (
            any(str(body.get(key, "")).strip()
                for key in ("ci_type", "ciType")) and
            any(str(body.get(key, "")).strip()
                for key in ("ci_identifier", "ciIdentifier", "ci_identifiers", "ciIdentifiers"))
        )
        fixture_ci = str(self.fixtures.get("ci_sys_id") or
                         self.fixtures.get("ci_name") or "").strip()
        if direct_to_incident and fixture_ci and not has_ci_input and not tests_ci_identifier:
            body["cmdbCi"] = fixture_ci
        return body

    def push(self, case: str, **overrides) -> dict:
        return self.sn.push_event(self.payload(case, **overrides), source=self.source)

    def incident_reference(self, sys_id: str, fields: tuple[str, ...]):
        """Read one reference through Incident API access, tolerating instance-specific fields."""
        for field in fields:
            try:
                row = self.sn.record("incident", sys_id, field, display="all")
            except ServiceNowError:
                continue
            value = row.get(field)
            if isinstance(value, dict):
                stored = str(value.get("value") or "")
                displayed = str(value.get("display_value") or "")
                if stored or displayed:
                    return field, stored, displayed
                return field, "", ""
            if value:
                return field, str(value), ""
        return "", "", ""

    @staticmethod
    def reference_matches(value: str, display: str, expected: str,
                          allow_first_name: bool = False) -> bool:
        expected = str(expected or "").strip()
        expected_folded = expected.casefold()
        if not expected:
            return False
        if value.casefold() == expected_folded or display.casefold() == expected_folded:
            return True
        if allow_first_name:
            first_name = display.split(maxsplit=1)[0] if display else ""
            return first_name.casefold() == expected_folded
        return False

    def check_reference_fixture(self, group: str, name: str, field: str,
                                stored: str, display: str, expected_name: str,
                                expected_sys_id: str, fixture_key: str) -> None:
        observed = f"{field or '(not returned)'}: {display or stored or '(empty)'}"
        if not field:
            self.check(group, name, None,
                       f"Incident API did not return this reference; check its field read ACL ({observed})")
        elif expected_sys_id:
            matched = self.reference_matches(stored, display, expected_sys_id)
            self.check(group, name, matched,
                       f"{observed} (expected sys_id {expected_sys_id})")
        elif self.reference_matches(stored, display, expected_name):
            self.check(group, name, True, f"{observed} (matched configured name)")
        elif not stored and not display:
            self.check(group, name, False, f"{observed}; lookup returned an empty reference")
        elif re.fullmatch(r"[0-9a-fA-F]{32}", stored) and (not display or display == stored):
            self.check(group, name, None,
                       f"{observed}; API exposes only the reference sys_id, so configure "
                       f"{fixture_key} for exact validation")
        else:
            self.check(group, name, False,
                       f"{observed} (expected name {expected_name})")

    def incident_reference_matches_sys_id(self, incident_sys_id: str, field: str,
                                          expected_sys_id: str):
        """Check a reference's stored sys_id using Incident access only.

        A display label is not enough for CI verification because different CI classes can
        share the same name. Filtering the Incident row by the reference sys_id avoids a
        separate CMDB table read.
        """
        incident_sys_id = str(incident_sys_id or "").strip()
        expected_sys_id = str(expected_sys_id or "").strip()
        if (not re.fullmatch(r"[0-9a-fA-F]{32}", incident_sys_id) or
                not re.fullmatch(r"[0-9a-fA-F]{32}", expected_sys_id)):
            return False
        try:
            rows = self.sn.table(
                "incident", f"sys_id={incident_sys_id}^{field}={expected_sys_id}",
                "sys_id", 1)
        except ServiceNowError:
            return None
        return any(str(row.get("sys_id") or "").casefold() == incident_sys_id.casefold()
                   for row in rows)

    def lookup_incident(self, case: str, payload: dict) -> str:
        response = self.sn.push_event(payload, source=self.source)
        sys_id = str(response.get("incident_sys_id") or "")
        self.check("lookups", case + " returns incident immediately", bool(sys_id),
                   f"{response.get('incident_number') or '(none)'} "
                   f"status={response.get('dti_incident_status') or '(none)'}")
        return sys_id

    def ci_reference_matches_after_link(self, case: str, incident_sys_id: str,
                                        expected_sys_id: str):
        deadline = time.time() + self.alert_wait
        matched = self.incident_reference_matches_sys_id(
            incident_sys_id, "cmdb_ci", expected_sys_id)
        if matched is False:
            # The fast path inserts before the alert exists. A production incident rule may
            # clear cmdb_ci until the reconcile rule writes u_generating_alert, after which the
            # connector restores the resolved CI. Alert linking can become visible before the
            # follow-up Incident update, so keep checking until the same bounded alert deadline.
            linked = self.wait_any_alert_linked(
                self.key(case), incident_sys_id,
                timeout=max(0.1, deadline - time.time()))
            while linked and matched is False and time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
                matched = self.incident_reference_matches_sys_id(
                    incident_sys_id, "cmdb_ci", expected_sys_id)
        return matched

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

    def set_incident_state(self, sys_id: str) -> dict:
        """Resolve an incident this run created using the instance's required closure fields.

        Use display values because the contract specifies the human-readable close code and the
        internal value can vary by instance. If policy or mandatory fields block the transition,
        report it as unavailable; never elevate through Scripts - Background.
        """
        try:
            self.sn.update("incident", sys_id, {
                "state": RESOLVED_STATE[1], **RESOLUTION_FIELDS}, input_display_value=True)
            back = self.sn.record("incident", sys_id,
                                  "state,number,close_code,u_cause,close_notes", display="all")

            def read_value(field: str):
                value = back.get(field)
                if isinstance(value, dict):
                    return (str(value.get("value") or ""),
                            str(value.get("display_value") or ""))
                text = str(value or "")
                return text, text

            state_value, state_display = read_value("state")
            close_code_value, close_code_display = read_value("close_code")
            cause_value, cause_display = read_value("u_cause")
            notes_value, notes_display = read_value("close_notes")
            return {
                "state": state_value,
                "state_display": state_display,
                "number": str(back.get("number", "")),
                "close_code": close_code_display or close_code_value,
                "u_cause": cause_display or cause_value,
                "close_notes": notes_display or notes_value,
                "how": "table api",
            }
        except ServiceNowError as error:
            return {"error": " ".join(str(error).split())[:280], "how": "unavailable"}

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

    def group_payload_contract(self) -> None:
        """Exercise the old sender payload containers and aliases through the selected listener."""
        wrappers = ("event", "payload", "data", "record", "alert")
        records = []
        expected = {}
        for index, wrapper in enumerate(wrappers):
            case = "payload-wrap-" + wrapper
            key = self.key(case)
            marker = "legacy_marker_" + wrapper
            payload = {
                "source": "usbem-verify",
                "eventClass": "usbem-verify",
                "hostName": f"{self.prefix.lower()}-{wrapper}",
                "component": case,
                "metricName": "legacy-payload-check",
                "eventType": "compatibility",
                "messageKey": key,
                "severity": "2",
                "message": "legacy payload " + wrapper,
            }
            if index == 0:
                payload["additionalInfo"] = {"legacy_marker": marker}
            elif index == 1:
                payload["additional_info"] = json.dumps({"legacy_marker": marker})
            records.append({wrapper: payload})
            expected[key] = {
                "message_key": key,
                "node": payload["hostName"], "resource": case,
                "metric_name": "legacy-payload-check", "event_class": "usbem-verify",
                "source": "usbem-verify", "description": "legacy payload " + wrapper,
                "marker": marker if index < 2 else "",
            }

        wrapped = self.sn.push_event({"records": records}, source=self.source)
        wrapped_results = wrapped.get("results") or []
        self.check("payload_contract", "all five legacy nested wrappers are accepted",
                   wrapped.get("inserted") == str(len(wrappers)) and
                   len(wrapped_results) == len(wrappers) and
                   {row.get("message_key") for row in wrapped_results} == set(expected),
                   f"inserted={wrapped.get('inserted')} results={len(wrapped_results)}")

        array_cases = ("payload-array-1", "payload-array-2")
        array_payloads = []
        for case in array_cases:
            node = f"{self.prefix.lower()}-array"
            array_payload = {
                "event_class": "usbem-verify", "node": node, "resource": case,
                "metric_name": "legacy-payload-check", "type": "compatibility",
                "severity": "2", "shortDescription": "legacy array " + case,
            }
            if case.endswith("1"):
                array_payload["source"] = "usbem-verify"
                array_payload["correlationId"] = self.key(case)
            else:
                # The default key concatenates source + node + type + resource + metric_name.
                array_payload["source"] = self.prefix
            array_payloads.append(array_payload)
            marker = "legacy_marker_" + case
            if case.endswith("1"):
                array_payloads[-1]["additional_info"] = {"legacy_marker": marker}
            else:
                array_payloads[-1]["additionalInfo"] = json.dumps({"legacy_marker": marker})
            key = (self.key(case) if case.endswith("1") else
                   self.prefix + node + "compatibility" + case + "legacy-payload-check")
            expected[key] = {
                "message_key": key,
                "node": node, "resource": case,
                "metric_name": "legacy-payload-check", "event_class": "usbem-verify",
                "source": "usbem-verify" if case.endswith("1") else self.prefix,
                "description": "legacy array " + case,
                "marker": marker,
            }
        array_response = self.sn.push_event(array_payloads, source=self.source)
        array_results = array_response.get("results") or []
        self.check("payload_contract", "bare array payload and correlationId alias",
                   array_response.get("inserted") == "2" and len(array_results) == 2 and
                   {row.get("message_key") for row in array_results} ==
                   set(expected_key for expected_key in expected if "payload-array-" in expected_key),
                   f"inserted={array_response.get('inserted')} results={len(array_results)}")

        events_case = "payload-events-envelope"
        events_key = self.key(events_case)
        events_body = {"events": [{"payload": {
            "source": "usbem-verify", "eventClass": "usbem-verify",
            "host": f"{self.prefix.lower()}-events", "target": events_case,
            "metric": "legacy-payload-check", "eventType": "compatibility",
            "messageKey": events_key, "severity": "2",
            "summary": "legacy events envelope", "additionalInfo":
                json.dumps({"legacy_marker": "legacy_marker_events"})
        }}]}
        events_response = self.sn.push_event(events_body, source=self.source)
        events_results = events_response.get("results") or []
        self.check("payload_contract", "events envelope and nested payload are accepted",
                   events_response.get("inserted") == "1" and len(events_results) == 1 and
                   events_results[0].get("message_key") == events_key,
                   f"inserted={events_response.get('inserted')} results={len(events_results)}")
        expected[events_key] = {
            "message_key": events_key,
            "node": f"{self.prefix.lower()}-events", "resource": events_case,
            "metric_name": "legacy-payload-check", "event_class": "usbem-verify",
            "source": "usbem-verify", "description": "legacy events envelope",
            "marker": "legacy_marker_events",
        }

        alias_case = "payload-alias-bundle"
        alias_key = self.key(alias_case)
        alias_marker = "legacy_marker_alias_bundle"
        alias_payload = {
            "source": "usbem-verify", "sourceInstance": "usbem-verify",
            "fqdn": f"{self.prefix.lower()}-aliases", "object": alias_case,
            "metric": "legacy-payload-check", "type": "compatibility",
            "alertKey": alias_key, "severity": "2", "summary": "legacy alias bundle",
            "additionalInfo": {"legacy_marker": alias_marker},
        }
        alias_response = self.sn.push_event(alias_payload, source=self.source)
        alias_results = alias_response.get("results") or []
        self.check("payload_contract", "alternate legacy aliases are accepted",
                   alias_response.get("inserted") == "1" and len(alias_results) == 1 and
                   alias_results[0].get("message_key") == alias_key,
                   f"inserted={alias_response.get('inserted')} results={len(alias_results)}")
        expected[alias_key] = {
            "message_key": alias_key,
            "node": f"{self.prefix.lower()}-aliases", "resource": alias_case,
            "metric_name": "legacy-payload-check", "event_class": "usbem-verify",
            "source": "usbem-verify", "description": "legacy alias bundle",
            "marker": alias_marker,
        }

        pending = set(expected)
        found = {}
        deadline = time.time() + self.alert_wait
        while pending and time.time() < deadline:
            for key in list(pending):
                alerts = self.alerts_for(key)
                if alerts:
                    found[key] = alerts[0]
                    pending.remove(key)
            if pending:
                time.sleep(3)

        fields = "message_key,node,resource,metric_name,event_class,source,description,additional_info"

        def contains_marker(value, marker):
            if isinstance(value, str):
                try:
                    return contains_marker(json.loads(value), marker)
                except (TypeError, ValueError):
                    return value == marker
            if isinstance(value, dict):
                if value.get("legacy_marker") == marker:
                    return True
                return any(contains_marker(child, marker) for child in value.values())
            if isinstance(value, list):
                return any(contains_marker(child, marker) for child in value)
            return False

        for key, expectation in expected.items():
            alert = found.get(key)
            if not alert:
                self.check("payload_contract", "legacy payload maps to an alert", False,
                           f"{key}: no alert within {self.alert_wait}s")
                continue
            row = self.sn.record("em_alert", alert["sys_id"], fields)
            mapped = all(str(row.get(field, "")) == str(expectation[field]) for field in
                         ("message_key", "node", "resource", "metric_name", "event_class",
                          "source", "description"))
            try:
                additional = json.loads(row.get("additional_info") or "{}")
            except (TypeError, ValueError):
                additional = {}
            marker_ok = (not expectation["marker"] or
                         contains_marker(additional, expectation["marker"]))
            self.check("payload_contract", "legacy aliases and additional_info read back",
                       mapped and marker_ok,
                       f"{key}: mapped={'yes' if mapped else 'no'}, "
                       f"additional_info marker={'yes' if marker_ok else 'no'}")

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

        state, label = RESOLVED_STATE
        case = f"{group}-{label.lower()}"
        opening = self.push(case, **extra)
        if not opening.get("incident_sys_id"):
            self.check(group, f"{label}: first incident", False,
                       str(opening.get("dti_incident_status")))
            return
        moved = self.set_incident_state(opening["incident_sys_id"])
        if moved.get("state") != state and moved.get("state_display") != label:
            self.check(group, f"{label} -> a new incident", None,
                       f"skipped: this account could not resolve the test incident "
                       f"({moved.get('error') or moved.get('how')})")
            return

        closure_ok = all(moved.get(field) == expected
                         for field, expected in RESOLUTION_FIELDS.items())
        self.check(group, "Resolved closure fields persist", closure_ok,
                   ", ".join(f"{field}={moved.get(field) or '(empty)'}"
                             for field in RESOLUTION_FIELDS))
        if not closure_ok:
            return

        # A resolved incident is terminal for this connector's reuse check. Production profiles
        # do not cancel incidents, so the verifier intentionally never tries state 8.
        after = self.push(case, **extra)
        fresh = after.get("incident_sys_id") not in ("", None, opening["incident_sys_id"])
        self.check(group, f"{label} -> a new incident", fresh,
                   f"{after.get('incident_number')} (was {opening.get('incident_number')}) "
                   f"status={after.get('dti_incident_status')}")
        if not fresh:
            return

        if self.wait_alert(self.key(case)):
            # Event Management may reopen the old alert or create a new one before linking it.
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
        expected_default_caller = str(self.fixtures.get("default_caller_sys_id") or "").strip()
        if expected_default_caller:
            self.check("fields", "caller defaults to the configured sys_id",
                       str(value("caller_id")) == expected_default_caller,
                       f"caller_id={value('caller_id') or '(empty)'}")
        else:
            self.check("fields", "caller defaults to the configured sys_id", None,
                       "set the selected instance's default caller sys_id to the instance property value")
        if expected_default_caller:
            missing_caller = self.push(
                "fields-caller-name-not-found", direct_to_incident="true",
                caller_id=f"{self.prefix} USBEM Verifier Missing Caller")
            missing_incident = str(missing_caller.get("incident_sys_id") or "")
            if missing_incident:
                missing_row = self.sn.record("incident", missing_incident, "caller_id")
                missing_status = str(missing_caller.get("incident_user_reference_status") or "")
                self.check("fields", "unmatched caller name uses configured default sys_id",
                           str(missing_row.get("caller_id") or "") == expected_default_caller and
                           "caller_id:name_not_found_defaulted" in missing_status,
                           f"caller_id={missing_row.get('caller_id') or '(empty)'} "
                           f"status={missing_status}")
            else:
                self.check("fields", "unmatched caller name uses configured default sys_id", False,
                           f"no incident: {missing_caller.get('dti_incident_status')}")
        else:
            self.check("fields", "unmatched caller name uses configured default sys_id", None,
                       "set the selected instance's default caller sys_id to the instance property value")
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
                             category="Hardware", subcategory="Server", contact_type="Integration",
                             short_description="sender supplied short description",
                             impact="3", urgency="3")
        sys_id = override.get("incident_sys_id", "")
        if sys_id:
            row = self.sn.record("incident", sys_id,
                                 "category,subcategory,caller_id,contact_type,short_description,"
                                 "u_netcool_ticket", display="all")
            applied = str(override.get("incident_fields_applied", ""))
            self.check("fields", "any incident field can be written",
                       all(f in applied for f in ("category", "subcategory", "contact_type")),
                       "applied: " + applied)
            self.check("fields", "the payload category wins",
                       str(shown("category")).lower() == "hardware" and str(shown("subcategory")).lower() == "server",
                       f"{shown('category')}/{shown('subcategory')}")
            self.check("fields", "the payload short_description wins",
                       value("short_description") == "sender supplied short description",
                       str(value("short_description")))
            self.check("fields", "NetCool stays true under overrides",
                       str(value("u_netcool_ticket")) in ("1", "true"), str(value("u_netcool_ticket")))

        software = self.push("fields-software-choice", direct_to_incident="true",
                             category="Software", subcategory="Monitoring Alert")
        if software.get("incident_sys_id"):
            choice = self.sn.record("incident", software["incident_sys_id"],
                                    "category,subcategory", display="all")
            self.check("fields", "Software/Monitoring Alert choice labels pass through",
                       str((choice.get("category") or {}).get("display_value", "")).lower() == "software" and
                       str((choice.get("subcategory") or {}).get("display_value", "")).lower() == "monitoring alert",
                       f"{(choice.get('category') or {}).get('display_value')}/"
                       f"{(choice.get('subcategory') or {}).get('display_value')}")
        else:
            self.check("fields", "Software/Monitoring Alert choice labels pass through", False,
                       f"no incident: {software.get('dti_incident_status')}")

        user_reference_cases = (
            ("caller_id", "caller_sys_id", "caller_sys_id", "sys_id"),
            ("caller_id", "caller_full_name", "caller_sys_id", "full name"),
            ("assigned_to", "assigned_to_sys_id", "assigned_to_sys_id", "sys_id"),
            ("assigned_to", "assigned_to_full_name", "assigned_to_sys_id", "full name"),
        )
        for field_name, fixture_key, expected_sys_id_key, input_kind in user_reference_cases:
            supplied_user = str(self.fixtures.get(fixture_key) or "").strip()
            expected_sys_id = str(self.fixtures.get(expected_sys_id_key) or "").strip()
            expected_user = expected_sys_id or supplied_user
            case = f"{field_name} by {input_kind}"
            if not supplied_user:
                role = "caller" if field_name == "caller_id" else "assignee"
                self.check("fields", case + " mapping", None,
                           f"set that instance's {role} sys_id or first name, and the shared {role} last name, "
                           "in tests/usbem_verify.env")
                continue
            caller = self.push("fields-" + case, direct_to_incident="true",
                               **{field_name: supplied_user})
            incident_id = str(caller.get("incident_sys_id") or "")
            if not incident_id:
                self.check("fields", case + " mapping", False,
                           f"no incident: {caller.get('dti_incident_status')}")
                continue
            field, stored, display = self.incident_reference(incident_id, (field_name,))
            resolved = self.reference_matches(stored, display, expected_user)
            if input_kind == "full name" and not expected_sys_id and not display:
                self.check("fields", case + " mapping", None,
                           f"Incident API returned sys_id {stored or '(empty)'} without a display value; "
                           "set the selected instance's corresponding user sys_id for sys_id-only validation")
            else:
                self.check("fields", case + " mapping",
                           field == field_name and resolved,
                           f"{field or field_name}: {display or stored or '(empty)'}")

        ambiguous_name = str(self.fixtures.get("ambiguous_caller_full_name") or "").strip()
        if ambiguous_name and expected_default_caller:
            ambiguous = self.push("fields-caller-ambiguous", direct_to_incident="true",
                                  caller_id=ambiguous_name)
            ambiguous_incident = str(ambiguous.get("incident_sys_id") or "")
            if ambiguous_incident:
                status = str(ambiguous.get("incident_user_reference_status") or "")
                if "caller_id:ambiguous_name_defaulted" in status:
                    caller_ref = self.sn.record("incident", ambiguous_incident, "caller_id")
                    self.check("fields", "ambiguous caller name uses configured default sys_id",
                               str(caller_ref.get("caller_id") or "") == expected_default_caller,
                               f"caller_id={caller_ref.get('caller_id') or '(empty)'} status={status}")
                elif "caller_id:full_name" in status:
                    self.check("fields", "ambiguous caller name uses configured default sys_id", None,
                               "the configured name resolved uniquely here; duplicate-name fallback "
                               f"was not exercised (status={status})")
                else:
                    self.check("fields", "ambiguous caller name uses configured default sys_id", None,
                               "the configured name did not produce an ambiguous match; "
                               f"fallback was not exercised (status={status or '(no status)'})")
            else:
                self.check("fields", "ambiguous caller name uses configured default sys_id", False,
                           f"no incident: {ambiguous.get('dti_incident_status')}")
        else:
            self.check("fields", "ambiguous caller name uses configured default sys_id", None,
                       "set a duplicated full name in the common fixtures and a default caller sys_id "
                       "for the selected instance")

        typo = self.push("fields-typo", direct_to_incident="true", catgeory="Network",
                         short_description="typo check")
        skipped = str(typo.get("incident_fields_skipped", ""))
        self.check("fields", "an unknown field name is reported", "catgeory" in skipped,
                   f"incident_fields_skipped={skipped or '(empty)'}")

        self.check_generating_alert()

        group_fixture = str(self.fixtures.get("assignment_group") or "").strip()
        if group_fixture:
            named = self.push("fields-group", direct_to_incident="true",
                              assignment_group=group_fixture)
            if named.get("incident_sys_id"):
                field, stored, display = self.incident_reference(
                    named["incident_sys_id"], ("assignment_group",))
                self.check("fields", "the payload assignment_group wins",
                           field == "assignment_group" and
                           self.reference_matches(stored, display, group_fixture),
                           f"{display or stored or '(empty)'} (asked for {group_fixture})")
            else:
                self.check("fields", "the payload assignment_group wins", False,
                           f"no incident: {named.get('dti_incident_status')}")
        else:
            self.check("fields", "the payload assignment_group wins", None,
                       f"set {FIXTURE_ENV_KEYS['assignment_group']} in tests/usbem_verify.env")

    def group_lookups(self) -> None:
        """Exercise fixture-driven CMDB, group, service, and offering resolution."""
        ci_name = str(self.fixtures.get("ci_name") or "").strip()
        ci_sys_id = str(self.fixtures.get("ci_sys_id") or "").strip()
        ci_input = ci_sys_id or ci_name

        for label, supplied in (("CI sys_id", ci_sys_id), ("CI exact name", ci_name)):
            if not supplied:
                self.check("lookups", label + " lookup", None,
                           f"set {FIXTURE_ENV_KEYS['ci_sys_id']} or {FIXTURE_ENV_KEYS['ci_name']} in tests/usbem_verify.env")
                continue
            case = "lookup-ci-" + ("sysid" if label == "CI sys_id" else "name")
            payload = self.payload(case, directToIncident="true", cmdbCi=supplied)
            incident_id = self.lookup_incident(case, payload)
            if incident_id:
                field, stored, display = self.incident_reference(incident_id, ("cmdb_ci",))
                if ci_sys_id:
                    matched = self.ci_reference_matches_after_link(case, incident_id, ci_sys_id)
                    self.check("lookups", label + " maps to the configured CI sys_id",
                               matched,
                               f"{field or 'cmdb_ci'}: {display or stored or '(empty)'}; "
                               "exact Incident reference filter used")
                else:
                    self.check("lookups", label + " CI reference identity", None,
                               "the API-visible display label cannot distinguish duplicate CIs; "
                               f"set {FIXTURE_ENV_KEYS['ci_sys_id']} in tests/usbem_verify.env")

        ci_type = str(self.fixtures.get("ci_type") or "").strip()
        ci_identifier = self.fixtures.get("ci_identifier")
        if ci_type and isinstance(ci_identifier, dict) and ci_identifier:
            case = "lookup-ci-identifier"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", ciType=ci_type, ciIdentifier=ci_identifier))
            if incident_id:
                field, stored, display = self.incident_reference(incident_id, ("cmdb_ci",))
                expected_ci = ci_sys_id or ci_name
                matched = (self.ci_reference_matches_after_link(case, incident_id, ci_sys_id)
                           if ci_sys_id else bool(stored or display))
                self.check("lookups", "camelCase ciType + ciIdentifier resolve",
                           matched,
                           f"{display or stored or '(empty)'} "
                           f"(expected {expected_ci or 'a resolved CI'})")
        else:
            self.check("lookups", "camelCase ciType + ciIdentifier resolve", None,
                       f"set {FIXTURE_ENV_KEYS['ci_type']} and {FIXTURE_ENV_KEYS['ci_identifier']} in tests/usbem_verify.env")

        support_group = str(self.fixtures.get("ci_support_group") or "").strip()
        if ci_input and support_group:
            case = "lookup-ci-support-group"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", cmdbCi=ci_input))
            if incident_id:
                field, stored, display = self.incident_reference(incident_id, ("assignment_group",))
                self.check("lookups", "CI support group is the DTI fallback",
                           field == "assignment_group" and
                           self.reference_matches(stored, display, support_group),
                           f"{display or stored or '(empty)'} (expected {support_group})")
        else:
            self.check("lookups", "CI support group is the DTI fallback", None,
                       f"set a CI fixture and {FIXTURE_ENV_KEYS['ci_support_group']} in tests/usbem_verify.env")

        group_fixture = str(self.fixtures.get("assignment_group") or "").strip()
        if group_fixture:
            case = "lookup-assignment-group"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", assignmentGroup=group_fixture))
            if incident_id:
                field, stored, display = self.incident_reference(incident_id, ("assignment_group",))
                self.check("lookups", "camelCase assignmentGroup resolves",
                           field == "assignment_group" and
                           self.reference_matches(stored, display, group_fixture),
                           f"{display or stored or '(empty)'} (expected {group_fixture})")
        else:
            self.check("lookups", "camelCase assignmentGroup resolves", None,
                       f"set {FIXTURE_ENV_KEYS['assignment_group']} in tests/usbem_verify.env")

        service = str(self.fixtures.get("service_name") or "").strip()
        service_sys_id = str(self.fixtures.get("service_sys_id") or "").strip()
        if service:
            case = "lookup-service"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", usbemService=service))
            if incident_id:
                field, stored, display = self.incident_reference(
                    incident_id, ("business_service", "service"))
                self.check_reference_fixture(
                    "lookups", "camelCase usbemService resolves", field, stored, display,
                    service, service_sys_id, FIXTURE_ENV_KEYS["service_sys_id"])
        else:
            self.check("lookups", "camelCase usbemService resolves", None,
                       f"set {FIXTURE_ENV_KEYS['service_name']} in tests/usbem_verify.env")

        offering = str(self.fixtures.get("offering_name") or "").strip()
        offering_sys_id = str(self.fixtures.get("offering_sys_id") or "").strip()
        if offering:
            case = "lookup-offering"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", usbemOffering=offering,
                **({"usbemService": service} if service else {})))
            if incident_id:
                field, stored, display = self.incident_reference(
                    incident_id, ("service_offering",))
                self.check_reference_fixture(
                    "lookups", "camelCase usbemOffering resolves", field, stored, display,
                    offering, offering_sys_id, FIXTURE_ENV_KEYS["offering_sys_id"])
        else:
            self.check("lookups", "camelCase usbemOffering resolves", None,
                       f"set {FIXTURE_ENV_KEYS['offering_name']} in tests/usbem_verify.env")

        car_id = str(self.fixtures.get("business_app_car_id") or "").strip()
        if car_id:
            case = "lookup-business-app"
            incident_id = self.lookup_incident(case, self.payload(
                case, directToIncident="true", usbemCarId=car_id))
            if incident_id:
                alerts = self.wait_alert(self.key(case))
                if not alerts:
                    self.check("lookups", "camelCase usbemCarId resolves", False,
                               f"incident created but no alert within {self.alert_wait}s")
                else:
                    row = self.sn.record("em_alert", alerts[0]["sys_id"], "additional_info")
                    try:
                        info = json.loads(row.get("additional_info") or "{}")
                    except (TypeError, ValueError):
                        info = {}
                    resolved = bool(info.get("cmdb_ci_business_app"))
                    self.check("lookups", "camelCase usbemCarId resolves",
                               resolved, "resolved business-app sys_id present in alert additional_info"
                               if resolved else "cmdb_ci_business_app is absent from alert additional_info")
        else:
            self.check("lookups", "camelCase usbemCarId resolves", None,
                       f"set {FIXTURE_ENV_KEYS['business_app_car_id']} in tests/usbem_verify.env")

    def check_generating_alert(self) -> None:
        """incident.u_generating_alert is customer-specific: where it exists it must point at the
        alert that produced the incident. Check it directly through Incident API read access so
        production does not need a sys_dictionary permission."""
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
        try:
            row = self.sn.record("incident", fast["incident_sys_id"], "u_generating_alert")
        except ServiceNowError:
            self.check("fields", "u_generating_alert points at the alert", None,
                       "field is missing or not exposed by Incident API read access")
            return
        if "u_generating_alert" not in row:
            self.check("fields", "u_generating_alert points at the alert", None,
                       "field is missing or not exposed by Incident API read access")
            return
        self.check("fields", "u_generating_alert points at the alert",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} "
                   f"alert={alert_sys_id or '(none)'}")

        expected_ci_sys_id = str(self.fixtures.get("ci_sys_id") or "").strip()
        if expected_ci_sys_id:
            ci_match = self.incident_reference_matches_sys_id(
                fast["incident_sys_id"], "cmdb_ci", expected_ci_sys_id)
            self.check("fields", "configured CI survives the delayed alert link", ci_match,
                       "Incident.cmdb_ci must equal the configured sys_id after "
                       "u_generating_alert is populated")
        else:
            self.check("fields", "configured CI survives the delayed alert link", None,
                       f"set {FIXTURE_ENV_KEYS['ci_sys_id']} in tests/usbem_verify.env")

        # The fast path creates the incident before the alert exists, so the reference can only be
        # written once they are linked. A second event for the same key exercises that.
        first = self.push("fields-genalert-fast", direct_to_incident="true")
        self.wait_alert(self.key("fields-genalert-fast"))
        second = self.push("fields-genalert-fast", direct_to_incident="true")
        incident_sys_id = second.get("incident_sys_id", "") or first.get("incident_sys_id", "")
        alerts = self.alerts_for(self.key("fields-genalert-fast"))
        alert_sys_id = alerts[0]["sys_id"] if alerts else ""
        time.sleep(3)
        try:
            row = self.sn.record("incident", incident_sys_id, "u_generating_alert") if incident_sys_id else {}
        except ServiceNowError:
            row = {}
        if "u_generating_alert" not in row:
            self.check("fields", "u_generating_alert set on a fast-path incident", None,
                       "field is missing or not exposed by Incident API read access")
            return
        self.check("fields", "u_generating_alert set on a fast-path incident",
                   bool(alert_sys_id) and str(row.get("u_generating_alert", "")) == alert_sys_id,
                   f"u_generating_alert={row.get('u_generating_alert') or '(empty)'} "
                   f"alert={alert_sys_id or '(none)'}")

    def manual_confirmation(self, name: str, prompt: str, identifiers: str) -> None:
        print(f"  [MANUAL] {identifiers}\n           {prompt}", flush=True)
        if not sys.stdin.isatty():
            self.check("notes", name, None, "manual check printed; rerun in a terminal to enter y/n")
            return
        try:
            answer = input("           Did it match? [y=yes / n=no / Enter=skip] ").strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            self.check("notes", name, True, "confirmed manually")
        elif answer in ("n", "no"):
            self.check("notes", name, False, "manual check reported a mismatch")
        else:
            self.check("notes", name, None, "manual check skipped")

    def group_notes(self) -> None:
        """Create note examples and ask the operator to verify in the Incident/Alert forms.

        Production API access does not include sys_journal_field. Record identifiers and exact
        expected text are shown so this remains verifiable without that table permission.
        """
        incident_text = "USBEM verifier incident note " + self.key("notes-manual-incident")
        incident = self.push("notes-manual-incident", direct_to_incident="true",
                             dti_work_note=incident_text)
        incident_id = str(incident.get("incident_sys_id") or "")
        if not incident_id:
            self.check("notes", "incident note test created an incident", False,
                       f"status={incident.get('dti_incident_status')}")
        else:
            self.check("notes", "incident note test created an incident", True,
                       str(incident.get("incident_number") or incident_id))
            linked = self.wait_any_alert_linked(self.key("notes-manual-incident"), incident_id,
                                                timeout=self.alert_wait)
            alert_no = linked.get("number", "")
            self.manual_confirmation(
                "Incident journal note and linked-alert behavior",
                f"Open {incident.get('incident_number') or incident_id}; confirm the creation note, "
                f"'Incident Created From {self.key('notes-manual-incident')}', and sender text "
                f"'{incident_text}' appear in Work notes. If linked alert {alert_no or '(not linked yet)'} "
                "is available, confirm the sender text is not duplicated there.",
                f"Incident {incident.get('incident_number') or incident_id}; "
                f"Alert {alert_no or '(link pending)'}")

        alert_text = "USBEM verifier alert note " + self.key("notes-manual-alert")
        self.push("notes-manual-alert", alert_work_notes=alert_text)
        alerts = self.wait_alert(self.key("notes-manual-alert"))
        if not alerts:
            self.check("notes", "alert note test created an alert", False,
                       f"no alert within {self.alert_wait}s")
            return
        alert = alerts[0]
        self.check("notes", "alert note test created an alert", True,
                   str(alert.get("number") or alert.get("sys_id")))
        time.sleep(4)
        self.push("notes-manual-alert", severity="2")
        time.sleep(3)
        self.push("notes-manual-alert", severity="2")
        alert_number = str(alert.get("number") or alert.get("sys_id"))
        self.manual_confirmation(
            "Alert work note appears once after repeated alert updates",
            f"Open alert {alert_number}; confirm '{alert_text}' appears in Work notes exactly once "
            "after the two later events without a note.",
            f"Alert {alert_number}")

    def group_edge(self) -> None:
        # incident.correlation_id is String(100) but em_alert.message_key holds 1024, so a long key
        # cannot round-trip. The connector must still converge on one incident for that key.
        long_key = (self.prefix + "-edge-long-" + ("k" * 130))[:180]
        numbers, statuses = [], []
        for _ in range(3):
            response = self.sn.push_event(self.payload(
                "edge-long", message_key=long_key, direct_to_incident="true"),
                source=self.source)
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
        clients = [ServiceNow(self.sn.instance, self.sn.auth,
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
                        help="response envelope to assert; legacy skips modern-only DTI checks")
    parser.add_argument("--access-profile", choices=("standard", "limited"), default="",
                        help="limited submits events and uses Incident/Alert APIs, skips cleanup, "
                             "and prints manual note checks "
                             "(default for the four production profiles)")
    parser.add_argument("--json", dest="json_out", help="write the results to this file")
    parser.add_argument("--instance", default="",
                        help="known production name/URL, or a custom https://<instance>.service-now.com; "
                             "omit to choose one of the four production profiles")
    parser.add_argument("--user", default="", help="account with the API/table permissions for the selected profile")
    parser.add_argument("--password", default="")
    parser.add_argument("--env-file", help=(
        "override the unified config file; default tests/usbem_verify.env"))
    parser.add_argument("--ca-bundle", default="", help="PEM file to trust (a corporate root)")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification, last resort")
    parser.add_argument("--version", action="version", version="usbem_verify " + VERSION)
    args = parser.parse_args()

    config_path = (Path(args.env_file).expanduser() if args.env_file else
                   Path(__file__).resolve().with_name("usbem_verify.env"))
    config_values = {}
    if config_path.is_file():
        try:
            config_values = parse_env_file(config_path)
        except OSError as error:
            parser.error(f"could not read config file {config_path}: {error}")
    elif args.env_file:
        parser.error(f"config file does not exist: {config_path}")

    try:
        instance_name, instance = select_instance(args.instance, config_values)
    except ValueError as error:
        parser.error(str(error))

    try:
        fixtures, configured_fixtures = load_fixtures(values=config_values,
                                                       instance_name=instance_name)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    auth = resolve_credentials(args, instance, instance_name, config_values)
    access_profile = args.access_profile or ("limited" if instance_name else "standard")
    groups = args.only or (["compat", "payload_contract"] if args.contract == "legacy" else list(GROUPS))
    if access_profile == "limited" and not args.only and args.contract == "legacy":
        groups = ["compat", "payload_contract"]
    try:
        sn = ServiceNow(instance, auth, ca_bundle=args.ca_bundle, insecure=args.insecure)
    except ServiceNowError as error:
        parser.error(str(error))
    prefix = args.prefix or f"ZZUSBEM-{int(time.time())}"
    verifier = Verifier(sn, prefix, args.alert_wait, args.expect_version,
                        source=args.source, contract=args.contract,
                        access_profile=access_profile, fixtures=fixtures)

    print(f"USBEM connector verification {VERSION}")
    if instance_name:
        print(f"selected instance {instance_name}")
    print(f"instance {instance}")
    print(f"authentication {auth['mode']}")
    print(f"connector source {args.source} ({args.contract} contract)")
    if access_profile == "limited":
        print("access profile limited: requires em_event write, Incident read/write, "
              "and Alert read/create/update; events are submitted through the connector; "
              "records are retained; work notes are manually verified from printed numbers")
    if args.contract == "modern":
        print(f"expecting components to report {args.expect_version}")
    print(f"prefix   {prefix}")
    print(f"config   {config_path} "
          f"({len(configured_fixtures)} configured keys: "
          f"{', '.join(configured_fixtures) if configured_fixtures else 'none'})")
    transport = ("macOS SecureTransport/Keychain" if sn._macos_curl else
                 ("requests" if requests is not None else "urllib"))
    print(f"http     {transport}"
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

    if args.keep or access_profile == "limited":
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
