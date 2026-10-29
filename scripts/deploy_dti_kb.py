#!/usr/bin/env python3
"""Idempotently publish the Generic JSON V2 DTI API and test article to the PDI."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

from deploy_jabberwocky_flow_action import ServiceNow


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "generic_json_v2" / "kb" / "generic_json_v2_dti_api_and_tests.md"
TITLE = "Generic JSON V2 Direct To Incident API, Business Rule, and Python Testing"
# Stable migration lookup: update the existing article and retain its number/attachments.
LEGACY_TITLE = "Generic JSON V2 Direct To Incident Linux Synthetic"


def instance_origin(value: str) -> str:
    """Validate an explicit HTTPS origin without silently discarding URL parts."""
    message = "expected an HTTPS instance origin without userinfo, path, query or fragment"
    if (value != value.strip() or any(character.isspace() or ord(character) < 32 or ord(character) == 127
                                    for character in value)
            or "\\" in value or "?" in value or "#" in value):
        raise argparse.ArgumentTypeError(message)
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port  # Validate malformed and out-of-range ports as well.
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or parsed.netloc.endswith(":")):
            raise ValueError(message)
        host = parsed.hostname.lower()
        authority_host = "[" + host + "]" if ":" in host else host
        suffix = parsed.netloc.lower()[len(authority_host):]
        if ((port is None and suffix) or
                (port is not None and not re.fullmatch(r":[0-9]+", suffix))):
            raise ValueError(message)
    except ValueError:
        raise argparse.ArgumentTypeError(message) from None
    return urllib.parse.urlunsplit(("https", parsed.netloc.lower(), "", "", ""))


def verify_target(expected: str, client: Client, admin: ServiceNow) -> None:
    """Fail before any query or write when a connection targets another instance."""
    try:
        actual = (instance_origin(client.base), instance_origin(admin.instance))
    except argparse.ArgumentTypeError:
        raise RuntimeError("A configured publishing target is not a valid HTTPS origin") from None
    if actual != (expected, expected):
        raise RuntimeError("Publishing connections do not match --expected-instance; no request was sent")


def load_env() -> None:
    for raw in (ROOT / ".env").read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class Client:
    def __init__(self) -> None:
        load_env()
        self.base = os.environ["servicenow_instance"].rstrip("/")
        token = base64.b64encode(
            f"{os.environ['servicenow_user']}:{os.environ['servicenow_password']}".encode()
        ).decode()
        self.headers = {"Authorization": "Basic " + token, "Accept": "application/json", "Content-Type": "application/json"}

    def request(self, method: str, path: str, payload: dict | None = None) -> object:
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())["result"]

    def query(self, table: str, query: str, fields: str, limit: int = 10) -> list[dict]:
        params = urllib.parse.urlencode({"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": str(limit)})
        return self.request("GET", f"/api/now/table/{table}?{params}")


def markdown_to_html(source: str) -> str:
    output: list[str] = []
    in_code = False
    in_list = False
    for line in source.splitlines():
        if line.startswith("```"):
            if in_list:
                output.append("</ul>"); in_list = False
            output.append("<pre><code>" if not in_code else "</code></pre>")
            in_code = not in_code
        elif in_code:
            output.append(html.escape(line))
        elif line.startswith("# "):
            output.append("<h1>" + html.escape(line[2:]) + "</h1>")
        elif line.startswith("## "):
            if in_list:
                output.append("</ul>"); in_list = False
            output.append("<h2>" + html.escape(line[3:]) + "</h2>")
        elif line.startswith("- "):
            if not in_list:
                output.append("<ul>"); in_list = True
            output.append("<li>" + html.escape(line[2:]) + "</li>")
        elif line.strip():
            if in_list:
                output.append("</ul>"); in_list = False
            escaped = html.escape(line)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            output.append("<p>" + escaped + "</p>")
    if in_list:
        output.append("</ul>")
    return "\n".join(output)


def normalized_knowledge_html(value: str) -> str:
    """Ignore only ASCII separators at raw UL/LI boundaries, never code/text."""
    separators = re.compile(r"(?<=<ul>)[ \t\r\n]+(?=<li>)|(?<=</li>)[ \t\r\n]+(?=<li>|</ul>)")
    protected = re.compile(r"<(?P<tag>pre|code)\b[^>]*>.*?</(?P=tag)[ \t\r\n]*>", re.IGNORECASE | re.DOTALL)
    parts = []
    cursor = 0
    for match in protected.finditer(value):
        parts.append(separators.sub("", value[cursor:match.start()]))
        parts.append(match.group())
        cursor = match.end()
    parts.append(separators.sub("", value[cursor:]))
    # Decode only after matching raw tags: escaped code examples are not structure.
    return html.unescape("".join(parts))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-instance", required=True, type=instance_origin,
                        help="intended HTTPS instance origin; must match both publishing connections")
    args = parser.parse_args(argv)
    client = Client()
    admin = ServiceNow()
    verify_target(args.expected_instance, client, admin)
    bases = client.query("kb_knowledge_base", "active=true^ORDERBYtitle", "sys_id,title", 10)
    if not bases:
        raise RuntimeError("No active Knowledge base found")
    preferred = next((row for row in bases if row.get("title") == "IT"), bases[0])
    existing = client.query("kb_knowledge", "short_description=" + TITLE + "^latest=true", "sys_id", 1)
    if not existing:
        existing = client.query("kb_knowledge", "short_description=" + LEGACY_TITLE + "^latest=true", "sys_id", 1)
    payload = {
        "short_description": TITLE,
        "kb_knowledge_base": preferred["sys_id"],
        "text": markdown_to_html(SOURCE.read_text()),
        "article_type": "text",
        "workflow_state": "published",
        "active": True,
        "display_attachments": True,
        "valid_to": "2099-12-31",
    }
    if existing:
        sys_id = existing[0]["sys_id"]
    else:
        sys_id = client.request("POST", "/api/now/table/kb_knowledge", payload)["sys_id"]
    body = payload["text"]
    admin.run_background_script(
        "var k=new GlideRecord('kb_knowledge');"
        + "if(!k.get(" + json.dumps(sys_id) + "))throw 'DTI KB missing';"
        + "k.setWorkflow(false);k.setValue('short_description'," + json.dumps(TITLE) + ");"
        + "k.setValue('text'," + json.dumps(body) + ");"
        + "k.setValue('kb_knowledge_base'," + json.dumps(preferred["sys_id"]) + ");"
        + "k.setValue('valid_to','2099-12-31');k.setValue('workflow_state','published');"
        + "k.setValue('active','true');k.setValue('display_attachments','true');"
        + "k.update();gs.print('DTI_KB_PUBLISHED');",
        "global",
    )
    rows = client.query("kb_knowledge", "sys_id=" + sys_id,
                        "sys_id,number,short_description,workflow_state,active,latest,display_attachments,text", 1)
    if (not rows or rows[0].get("workflow_state") != "published" or
            str(rows[0].get("active")).lower() != "true" or
            str(rows[0].get("display_attachments")).lower() != "true" or
            str(rows[0].get("latest")).lower() != "true" or rows[0].get("short_description") != TITLE):
        raise RuntimeError("Knowledge article did not read back with the expected title, active, latest, "
                           "published and visible-attachments state")
    if normalized_knowledge_html(rows[0].get("text", "")) != normalized_knowledge_html(body):
        raise RuntimeError("Knowledge article body does not match the source")
    rows[0].pop("text", None)
    print(json.dumps(rows[0], sort_keys=True))


if __name__ == "__main__":
    main()
