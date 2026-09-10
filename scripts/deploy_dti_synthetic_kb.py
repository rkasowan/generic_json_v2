#!/usr/bin/env python3
"""Idempotently publish the Generic JSON V2 DTI synthetic article to the PDI."""

from __future__ import annotations

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
SOURCE = ROOT / "generic_json_v2" / "kb" / "generic_json_v2_dti_linux_synthetic.md"
TITLE = "Generic JSON V2 Direct To Incident Linux Synthetic"


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


def main() -> None:
    client = Client()
    bases = client.query("kb_knowledge_base", "active=true^ORDERBYtitle", "sys_id,title", 10)
    if not bases:
        raise RuntimeError("No active Knowledge base found")
    preferred = next((row for row in bases if row.get("title") == "IT"), bases[0])
    existing = client.query("kb_knowledge", "short_description=" + TITLE + "^latest=true", "sys_id", 1)
    payload = {
        "short_description": TITLE,
        "kb_knowledge_base": preferred["sys_id"],
        "text": markdown_to_html(SOURCE.read_text()),
        "article_type": "text",
        "workflow_state": "published",
        "active": True,
        "valid_to": "2099-12-31",
    }
    if existing:
        sys_id = existing[0]["sys_id"]
    else:
        sys_id = client.request("POST", "/api/now/table/kb_knowledge", payload)["sys_id"]
    body = payload["text"]
    ServiceNow().run_background_script(
        "var k=new GlideRecord('kb_knowledge');"
        + "if(!k.get(" + json.dumps(sys_id) + "))throw 'DTI synthetic KB missing';"
        + "k.setWorkflow(false);k.setValue('short_description'," + json.dumps(TITLE) + ");"
        + "k.setValue('text'," + json.dumps(body) + ");"
        + "k.setValue('kb_knowledge_base'," + json.dumps(preferred["sys_id"]) + ");"
        + "k.setValue('valid_to','2099-12-31');k.setValue('workflow_state','published');"
        + "k.setValue('active','true');k.update();gs.print('DTI_SYNTHETIC_KB_PUBLISHED');",
        "global",
    )
    rows = client.query("kb_knowledge", "sys_id=" + sys_id, "sys_id,number,short_description,workflow_state,active,latest", 1)
    if not rows or rows[0].get("workflow_state") != "published" or str(rows[0].get("active")).lower() != "true":
        raise RuntimeError("Knowledge article did not read back as active and published")
    print(json.dumps(rows[0], sort_keys=True))


if __name__ == "__main__":
    main()
