#!/usr/bin/env python3
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
SCRIPT_FILE = ROOT / "generic_json_v2" / "servicenow" / "USBEM_JabberwockyInboundEmail.flow_action.js"

ACTION_INTERNAL_NAME = "usbem_jabberwocky_inbound_email_json_event"
ACTION_NAME = "USBEM Jabberwocky Inbound Email JSON Event"
LEGACY_INBOUND_ACTION_NAME = "USBEM Jabberwocky Inbound JSON Event"

SCRIPT_STEP_DEFINITION = "106afb6647032200b4fad7527c9a71e7"
SCRIPT_VARIABLE = "71aa7f6647032200b4fad7527c9a719b"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def b64(name: str) -> str:
    value = os.getenv(name, "")
    return base64.b64decode(value).decode("utf-8") if value else ""


class ServiceNow:
    def __init__(self) -> None:
        load_env(ENV_FILE)
        self.instance = (os.getenv("SN_INSTANCE_URL") or os.getenv("servicenow_instance") or "").rstrip("/")
        self.username = b64("SN_USERNAME_B64") or os.getenv("SN_USERNAME") or os.getenv("servicenow_user")
        self.password = b64("SN_PASSWORD_B64") or os.getenv("SN_PASSWORD") or os.getenv("servicenow_password")
        if not self.instance or not self.username or not self.password:
            raise RuntimeError("ServiceNow instance and credentials were not found in .env")
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "Basic " + token,
        }

    def request(
        self,
        method: str,
        table: str,
        payload: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
    ) -> list[dict[str, object]] | dict[str, object]:
        url = f"{self.instance}/api/now/table/{table}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))["result"]

    def get_one(self, table: str, sysparm_query: str, fields: str = "sys_id") -> dict[str, object] | None:
        result = self.request(
            "GET",
            table,
            query={
                "sysparm_query": sysparm_query,
                "sysparm_fields": fields,
                "sysparm_limit": "1",
                "sysparm_display_value": "false",
            },
        )
        if not isinstance(result, list):
            return None
        return result[0] if result else None

    def create(self, table: str, payload: dict[str, str]) -> dict[str, object]:
        result = self.request("POST", table, payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected create response for {table}")
        return result

    def update(self, table: str, sys_id: str, payload: dict[str, str]) -> dict[str, object]:
        result = self.request("PATCH", f"{table}/{sys_id}", payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected update response for {table}/{sys_id}")
        return result

    def run_background_script(self, script: str, scope: str = "global") -> str:
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

        login_payload = urllib.parse.urlencode(
            {
                "user_name": self.username,
                "user_password": self.password,
                "sys_action": "sysverb_login",
            }
        ).encode("utf-8")
        opener.open(urllib.request.Request(f"{self.instance}/login.do", method="GET"), timeout=60).read()
        opener.open(
            urllib.request.Request(
                f"{self.instance}/login.do",
                data=login_payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=60,
        ).read()

        scripts_html = opener.open(urllib.request.Request(f"{self.instance}/sys.scripts.do", method="GET"), timeout=60).read().decode(
            "utf-8", "replace"
        )
        match = re.search(r'name=["\']sysparm_ck["\'][^>]*value=["\']([^"\']+)["\']', scripts_html)
        if not match:
            match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']sysparm_ck["\']', scripts_html)
        if not match:
            raise RuntimeError("Could not find sysparm_ck on sys.scripts.do")

        run_payload = urllib.parse.urlencode(
            {
                "sysparm_ck": match.group(1),
                "runscript": "Run script",
                "sys_scope": scope,
                "script": script,
            }
        ).encode("utf-8")
        response = opener.open(
            urllib.request.Request(
                f"{self.instance}/sys.scripts.do",
                data=run_payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=120,
        )
        return response.read().decode("utf-8", "replace")


def value_of(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if isinstance(value, dict):
        nested = value.get("value")
        return "" if nested is None else str(nested)
    return "" if value is None else str(value)


def variable_payload(
    kind: str,
    owner_id: str,
    element: str,
    label: str,
    internal_type: str,
    order: int,
    mandatory: bool = False,
) -> dict[str, str]:
    ui_unique_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ACTION_INTERNAL_NAME}:{kind}:{element}"))
    max_length = "8000" if internal_type == "string" else "40"
    return {
        "model": owner_id,
        "model_id": owner_id,
        "model_table": "sys_hub_action_type_definition",
        "name": f"var__m_{kind}_{owner_id}",
        "element": element,
        "label": label,
        "internal_type": internal_type,
        "max_length": max_length,
        "order": str(order),
        "mandatory": "true" if mandatory else "false",
        "active": "true",
        "virtual_type": "script",
        "attributes": (
            "element_mapping_provider=com.glide.flow_design.action.data.FlowDesignVariableMapper,"
            f"uiType={internal_type},uiTypeLabel={label},uiUniqueId={ui_unique_id}"
        ),
    }


def step_variable_payload(
    kind: str,
    step_id: str,
    element: str,
    label: str,
    internal_type: str,
    order: int,
    mandatory: bool = False,
) -> dict[str, str]:
    payload = variable_payload(kind, step_id, element, label, internal_type, order, mandatory)
    payload["model_table"] = "sys_hub_step_instance"
    payload["name"] = f"var__m_{kind}_{step_id}"
    return payload


def ensure_mapping(sn: ServiceNow, table_name: str, owner_id: str, field: str, value: str) -> str:
    existing = sn.get_one("sys_element_mapping", f"id={owner_id}^table={table_name}^field={field}", "sys_id")
    payload = {"id": owner_id, "table": table_name, "field": field, "value": value}
    if existing:
        sn.update("sys_element_mapping", value_of(existing, "sys_id"), payload)
        return value_of(existing, "sys_id")
    return value_of(sn.create("sys_element_mapping", payload), "sys_id")


def ensure_variable(
    sn: ServiceNow,
    table: str,
    query: str,
    payload: dict[str, str],
) -> str:
    existing = sn.get_one(table, query, "sys_id")
    if existing:
        sys_id = value_of(existing, "sys_id")
        sn.update(table, sys_id, payload)
        return sys_id
    return value_of(sn.create(table, payload), "sys_id")


def set_script_variable_value(sn: ServiceNow, step_id: str, script: str) -> str:
    script_payload = {
        "document": "sys_hub_step_instance",
        "document_key": step_id,
        "variable": SCRIPT_VARIABLE,
        "value": script,
        "order": "600",
    }
    script_var = sn.get_one(
        "sys_variable_value",
        f"document=sys_hub_step_instance^document_key={step_id}^variable={SCRIPT_VARIABLE}",
        "sys_id",
    )
    try:
        if script_var:
            sys_id = value_of(script_var, "sys_id")
            sn.update("sys_variable_value", sys_id, script_payload)
            return sys_id
        return value_of(sn.create("sys_variable_value", script_payload), "sys_id")
    except urllib.error.HTTPError as exc:
        if exc.code not in {401, 403}:
            raise

    background = """
(function () {
    var gr = new GlideRecord('sys_variable_value');
    var created = false;
    gr.addQuery('document', 'sys_hub_step_instance');
    gr.addQuery('document_key', %(step_id)s);
    gr.addQuery('variable', %(variable)s);
    gr.query();
    if (!gr.next()) {
        gr.initialize();
        gr.setValue('document', 'sys_hub_step_instance');
        gr.setValue('document_key', %(step_id)s);
        gr.setValue('variable', %(variable)s);
        created = true;
    }
    gr.setValue('value', %(script)s);
    gr.setValue('order', '600');
    var sysId = created ? gr.insert() : gr.update();
    gs.print('USBEM flow action script variable ' + (created ? 'created' : 'updated') + ': ' + sysId);
})();
""" % {
        "step_id": json.dumps(step_id),
        "variable": json.dumps(SCRIPT_VARIABLE),
        "script": json.dumps(script),
    }
    sn.run_background_script(background, "global")
    script_var = sn.get_one(
        "sys_variable_value",
        f"document=sys_hub_step_instance^document_key={step_id}^variable={SCRIPT_VARIABLE}",
        "sys_id",
    )
    if not script_var:
        raise RuntimeError("Background script did not create sys_variable_value for script step")
    return value_of(script_var, "sys_id")


def deactivate_legacy_inbound_action(sn: ServiceNow) -> str:
    existing = sn.get_one(
        "sysevent_in_email_action",
        f"name={LEGACY_INBOUND_ACTION_NAME}",
        "sys_id,active",
    )
    if not existing:
        return "not_found"
    sys_id = value_of(existing, "sys_id")
    if value_of(existing, "active") == "false":
        return "already_inactive"
    sn.update("sysevent_in_email_action", sys_id, {"active": "false"})
    return "deactivated"


def main() -> None:
    sn = ServiceNow()
    script = SCRIPT_FILE.read_text(encoding="utf-8")

    action = sn.get_one(
        "sys_hub_action_type_definition",
        f"internal_name={ACTION_INTERNAL_NAME}",
        "sys_id,internal_name,name",
    )
    action_payload = {
        "name": ACTION_NAME,
        "internal_name": ACTION_INTERNAL_NAME,
        "state": "published",
        "active": "true",
        "access": "public",
        "sys_scope": "global",
        "sys_package": "global",
        "description": (
            "Flow Designer action that accepts inbound email fields, requires "
            "jabberwocky in the subject, parses a genericJsonV2 payload from "
            "the body/description, and inserts Event Management events."
        ),
    }
    if action:
        action = sn.update("sys_hub_action_type_definition", value_of(action, "sys_id"), action_payload)
    else:
        action = sn.create("sys_hub_action_type_definition", action_payload)
    action_id = value_of(action, "sys_id")

    existing_step = sn.get_one("sys_hub_step_instance", f"action={action_id}^label=Script step", "sys_id,cid")
    step_payload = {
        "action": action_id,
        "step_type": SCRIPT_STEP_DEFINITION,
        "label": "Script step",
        "order": "1",
        "cid": value_of(existing_step or {}, "cid") or str(uuid.uuid4()),
        "error_handling_type": "1",
        "sys_scope": "global",
    }
    if existing_step:
        step_id = value_of(existing_step, "sys_id")
        step = sn.update("sys_hub_step_instance", step_id, step_payload)
    else:
        step = sn.create("sys_hub_step_instance", step_payload)
        step_id = value_of(step, "sys_id")
    step_cid = value_of(step, "cid") or step_payload["cid"]

    script_value_id = set_script_variable_value(sn, step_id, script)

    inputs = [
        ("subject", "Subject", "string", 1, True),
        ("description", "Description", "string", 2, False),
        ("body_text", "Body Text", "string", 3, False),
        ("body_html", "Body HTML", "string", 4, False),
        ("from_email", "From Email", "string", 5, False),
        ("sys_email_sys_id", "Inbound Email Sys ID", "string", 6, False),
    ]
    outputs = [
        ("status", "Status", "string", 1),
        ("skipped", "Skipped", "boolean", 2),
        ("inserted", "Inserted", "integer", 3),
        ("sys_ids", "Event Sys IDs", "string", 4),
        ("event_sys_id", "First Event Sys ID", "string", 5),
        ("version", "USBEM Version", "string", 6),
        ("message", "Message", "string", 7),
        ("response_json", "Response JSON", "string", 8),
    ]

    for element, label, typ, order, mandatory in inputs:
        ensure_variable(
            sn,
            "sys_hub_action_input",
            f"model={action_id}^element={element}",
            variable_payload("sys_hub_action_input", action_id, element, label, typ, order, mandatory),
        )
        ensure_variable(
            sn,
            "sys_hub_step_ext_input",
            f"model={step_id}^element={element}",
            step_variable_payload("sys_hub_step_ext_input", step_id, element, label, typ, order, mandatory),
        )
        ensure_mapping(
            sn,
            f"var__m_sys_hub_step_ext_input_{step_id}",
            step_id,
            element,
            "{{action." + element + "}}",
        )

    for element, label, typ, order in outputs:
        ensure_variable(
            sn,
            "sys_hub_action_output",
            f"model={action_id}^element={element}",
            variable_payload("sys_hub_action_output", action_id, element, label, typ, order, False),
        )
        ensure_variable(
            sn,
            "sys_hub_step_ext_output",
            f"model={step_id}^element={element}",
            step_variable_payload("sys_hub_step_ext_output", step_id, element, label, typ, order, False),
        )
        ensure_mapping(
            sn,
            f"var__m_sys_hub_action_output_{action_id}",
            action_id,
            element,
            "{{step[" + step_cid + "]." + element + "}}",
        )

    legacy_status = deactivate_legacy_inbound_action(sn)

    print(
        json.dumps(
            {
                "action": ACTION_NAME,
                "internal_name": ACTION_INTERNAL_NAME,
                "action_sys_id": action_id,
                "step_sys_id": step_id,
                "script_value_sys_id": script_value_id,
                "legacy_sysevent_in_email_action": legacy_status,
                "url": f"{sn.instance}/sys_hub_action_type_definition.do?sys_id={action_id}",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
