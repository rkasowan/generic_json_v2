"""Shared ServiceNow client for the USBEM genericJsonV2 tooling.

Why requests instead of urllib: on macOS a plain venv has no CA bundle wired into the stdlib,
so urllib raises CERTIFICATE_VERIFY_FAILED against perfectly valid ServiceNow certificates.
requests uses certifi's bundle, which works out of the box. Install with:

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

Credentials come from the environment or the nearest .env, under any of the spellings this
workspace has used: servicenow_instance / SN_INSTANCE_URL / instance, and the matching
user/password names. Nothing here ever prints a secret.

TLS knobs, in order of preference:
    SN_CA_BUNDLE=/path/to/corporate-root.pem   trust an extra root (also REQUESTS_CA_BUNDLE)
    SN_VERIFY_SSL=false                        last resort; skips verification entirely
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "2026.09.25.3"

# Python 3.9 on macOS links LibreSSL, and urllib3 2.x warns about it on every import. The
# warning is noise here: ServiceNow is reached over TLS 1.2+ either way.
import warnings
warnings.filterwarnings("ignore", message=".*OpenSSL 1.1.1.*")

try:
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:  # pragma: no cover - the message is the point
    sys.exit(
        "the 'requests' package is required\n"
        "    python3 -m venv .venv && source .venv/bin/activate\n"
        "    pip install -r requirements.txt"
    )

try:
    import certifi
except ImportError:
    certifi = None

MARK = "@@JSON@@"

_INSTANCE_KEYS = ("servicenow_instance", "SN_INSTANCE_URL", "instance", "SN_INSTANCE")
_USER_KEYS = ("servicenow_user", "SN_USERNAME", "user", "SN_USER")
_PASSWORD_KEYS = ("servicenow_password", "SN_PASSWORD", "password")


def _read_env_file(start: Path) -> Dict[str, str]:
    for folder in [start] + list(start.parents):
        env_file = folder / ".env"
        if env_file.is_file():
            values: Dict[str, str] = {}
            for raw in env_file.read_text(errors="replace").splitlines():
                if "=" in raw and not raw.lstrip().startswith("#"):
                    key, value = raw.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
            return values
    return {}


def _first(sources: List[Dict[str, str]], keys) -> str:
    for key in keys:
        for source in sources:
            if source.get(key):
                return source[key]
    return ""


def load_credentials(env_file: Optional[str] = None) -> tuple[str, str, str]:
    """(instance_url, user, password) from the environment or the nearest .env."""
    sources: List[Dict[str, str]] = [dict(os.environ)]
    if env_file:
        sources.append(_read_env_file(Path(env_file).expanduser().resolve().parent))
    sources.append(_read_env_file(Path(__file__).resolve().parent))

    instance = _first(sources, _INSTANCE_KEYS).rstrip("/")
    user = _first(sources, _USER_KEYS)
    password = _first(sources, _PASSWORD_KEYS)
    missing = [name for name, value in
               (("instance", instance), ("user", user), ("password", password)) if not value]
    if missing:
        sys.exit("missing credentials: " + ", ".join(missing) +
                 " (set servicenow_instance / servicenow_user / servicenow_password in the "
                 "environment or a .env)")
    if not instance.startswith("http"):
        instance = "https://" + instance
    return instance, user, password


def tls_verify_setting() -> Any:
    """What to hand requests as `verify`, honouring the TLS knobs documented above."""
    if str(os.getenv("SN_VERIFY_SSL", "true")).strip().lower() in {"0", "false", "no", "off"}:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        return False
    bundle = os.getenv("SN_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
    if bundle and Path(bundle).is_file():
        return bundle
    if certifi is not None:
        return certifi.where()
    return True


class ServiceNowError(RuntimeError):
    pass


class ServiceNow:
    """Table API, REST push and a background-script runner."""

    def __init__(self, instance: str, user: str, password: str, timeout: int = 180) -> None:
        self.instance = instance
        self.user = user
        self.timeout = timeout
        self.verify = tls_verify_setting()

        self.api = requests.Session()
        self.api.auth = (user, password)
        self.api.verify = self.verify
        self.api.headers.update({"Accept": "application/json"})
        self.api.mount("https://", HTTPAdapter(max_retries=2, pool_maxsize=16))

        # Separate cookie-bearing session for /sys.scripts.do, which is form + session based.
        self.ui = requests.Session()
        self.ui.verify = self.verify
        self.ui.mount("https://", HTTPAdapter(max_retries=2, pool_maxsize=4))
        self._password = password
        self._ck = ""

    # ------------------------------------------------------------------ plumbing
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else self.instance + path
        try:
            response = self.api.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.SSLError as exc:
            raise ServiceNowError(
                f"TLS verification failed for {url}: {exc}\n"
                "  pip install -U certifi        (usual fix on macOS)\n"
                "  SN_CA_BUNDLE=/path/root.pem   to trust a corporate root\n"
                "  SN_VERIFY_SSL=false           to skip verification (last resort)"
            ) from None
        except requests.exceptions.RequestException as exc:
            raise ServiceNowError(f"{method} {url} failed: {exc}") from None
        if response.status_code >= 400:
            raise ServiceNowError(f"{method} {path} -> HTTP {response.status_code}: {response.text[:400]}")
        if not response.text.strip():
            return None
        try:
            body = response.json()
        except ValueError:
            return response.text
        return body.get("result", body) if isinstance(body, dict) else body

    # ------------------------------------------------------------------ Table API
    def table(self, name: str, query: str, fields: str, limit: int = 50,
              display: str = "false") -> List[dict]:
        return self._request("GET", f"/api/now/table/{name}", params={
            "sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": str(limit),
            "sysparm_display_value": display, "sysparm_exclude_reference_link": "true",
        }) or []

    def record(self, name: str, sys_id: str, fields: str, display: str = "false") -> dict:
        return self._request("GET", f"/api/now/table/{name}/{sys_id}", params={
            "sysparm_fields": fields, "sysparm_display_value": display,
            "sysparm_exclude_reference_link": "true",
        }) or {}

    def insert(self, name: str, payload: dict) -> dict:
        return self._request("POST", f"/api/now/table/{name}", json=payload) or {}

    def update(self, name: str, sys_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"/api/now/table/{name}/{sys_id}", json=payload) or {}

    def delete(self, name: str, sys_id: str) -> None:
        self._request("DELETE", f"/api/now/table/{name}/{sys_id}")

    def push_event(self, payload: Any, source: str = "genericJsonV2") -> dict:
        """POST to the push connector endpoint exactly as a real sender would."""
        result = self._request(
            "POST", "/api/sn_em_connector/em/inbound_event",
            params={"source": source}, json=payload,
            headers={"Content-Type": "application/json", "user-agent": "genericendpoint"})
        return self._unwrap_listener_response(result)

    @staticmethod
    def _unwrap_listener_response(result: Any) -> dict:
        """The endpoint answers {"<listener name>": "<json string the listener returned>"}.

        A single-record push therefore arrives double-wrapped; unwrap it so callers see the
        listener's own contract (status, results[], version, versions, ...).
        """
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

    # ------------------------------------------------------------------ background scripts
    def _login(self) -> None:
        try:
            self.ui.post(self.instance + "/login.do", timeout=60, data={
                "user_name": self.user, "user_password": self._password,
                "sys_action": "sysverb_login",
            })
            page = self.ui.get(self.instance + "/sys.scripts.do", timeout=60).text
        except requests.exceptions.SSLError as exc:
            raise ServiceNowError(f"TLS verification failed signing in: {exc}") from None
        match = (re.search(r'name=["\']sysparm_ck["\'][^>]*value=["\']([^"\']+)', page)
                 or re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']sysparm_ck', page))
        if not match:
            raise ServiceNowError("could not obtain the background-script token; does this account have admin?")
        self._ck = match.group(1)

    def script(self, source: str, scope: str = "global"):
        """Run a background script. It should gs.print(MARK + JSON.stringify(payload))."""
        if not self._ck:
            self._login()
        data = {
            "script": source, "sysparm_ck": self._ck, "runscript": "Run script",
            "sys_scope": scope, "quota_managed_transaction": "on",
        }
        text = self.ui.post(self.instance + "/sys.scripts.do", data=data, timeout=self.timeout).text
        if MARK not in text:
            snippet = re.sub(r"<[^>]+>", " ", text)
            snippet = re.sub(r"\s+", " ", snippet)[:400]
            raise ServiceNowError("background script produced no marked output: " + snippet)
        # The page echoes the script source back above its output, so the first marker found is
        # usually the gs.print() line itself. Try every marker and keep the first that parses.
        for segment in text.split(MARK)[1:]:
            chunk = segment.split("<", 1)[0].strip()
            chunk = (chunk.replace("&quot;", '"').replace("&amp;", "&")
                          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
            try:
                return json.loads(chunk)
            except ValueError:
                continue
        raise ServiceNowError("background script output was not JSON: " + text.split(MARK)[-1][:200])


def wait_for(predicate, timeout_s: float, every: float = 2.0):
    """Poll until predicate returns something truthy, or give up and return it anyway."""
    deadline = time.time() + timeout_s
    result = predicate()
    while not result and time.time() < deadline:
        time.sleep(every)
        result = predicate()
    return result
