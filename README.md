# Generic Mapped JSON Push Connector

Repo version: `2026.09.10.2`
Release history: [CHANGELOG.md](CHANGELOG.md)

The repo release version is separate from the locked standalone ServiceNow transform in
`standalone/genericMappedJson_transform.js`, which remains `2026-03-18a` for the final path.

The repo also carries the live modular `genericJsonV2` source layout used in PDIs:
- `src/USBEM_Core.js`
- `src/USBEM_Lookups.js`
- `src/USBEM_Debug.js`
- `src/USBEM_DTI.js`
- `src/USBEM_genericJsonV2.js`
- `src/USBEM_genericJsonV2_Full.js`

The repo also includes ATF assets for environment testing:
- `atf/install_usbem_atf.js`
- `docs/atf_testing.md`

The Linux systemd synthetic under `synthetic/` runs every five minutes, validates DTI duplicate handling through live `em_event` and `incident` readback, removes the successful probe incident, emits an OK event, and creates a separately assigned DTI incident plus SMTP email only on failure. Installation and operations are documented in `kb/generic_json_v2_dti_linux_synthetic.md`.

## Purpose

This bundle gives you a custom **Instance** push connector transform for Event Management that accepts generic JSON, maps standard `em_event` fields when it can, and places everything else into the event's `additional_info` JSON string.

It is designed to be friendly to:
- flat JSON payloads
- bulk payloads with `records` or `events`
- legacy payloads that send `additional_info` as an escaped JSON string
- migration payloads that need assignment-group, CI, service, offering, business-app, and DTI helper behavior

## Source Layout

Two source layouts are kept in the repo:

- `standalone/genericMappedJson_transform.js` is the locked standalone transform artifact
- the `genericJsonV2` modular layout is split across:
  - `src/USBEM_Core.js`
  - `src/USBEM_Lookups.js`
  - `src/USBEM_Debug.js`
  - `src/USBEM_DTI.js`
  - `src/USBEM_genericJsonV2.js`
- `src/USBEM_genericJsonV2_Full.js` is the fully inlined test build that embeds the listener plus all four script include components in one file
- `atf/install_usbem_atf.js` is the idempotent Background Script installer for the `USBEM` parent ATF suite, the `USBEM genericJsonV2 API Coverage` child suite, and the helper include
- `docs/atf_testing.md` documents installation, coverage, reruns, and execution flow

## Inbound Email Bridge

The optional Flow Designer custom Action in
`servicenow/USBEM_JabberwockyInboundEmail.flow_action.js` lets inbound-email Flows
create events through the same genericJsonV2 mapping path without using
`sysevent_in_email_action`.

Deploy or update it with:

```bash
python3 generic_json_v2/scripts/deploy_jabberwocky_flow_action.py
```

The deployer publishes the Flow Action
`USBEM Jabberwocky Inbound Email JSON Event` and deactivates the legacy
`USBEM Jabberwocky Inbound JSON Event` inbound email action if it exists.

Recommended Flow Designer wiring:
- trigger: inbound email / email received
- trigger condition: subject contains `jabberwocky`
- action: `USBEM Jabberwocky Inbound Email JSON Event`
- map trigger subject to `Subject`
- map email description/body text to `Description` or `Body Text`
- map body HTML to `Body HTML` when available
- map sender/from to `From Email`
- map the source `sys_email` sys_id to `Inbound Email Sys ID` when available

Action behavior:
- subject must contain `jabberwocky` (case-insensitive); otherwise the action returns `skipped=true`
- email body/description must contain a JSON event payload, JSON array, `{ "records": [...] }`, or `{ "events": [...] }`
- the action parses the first JSON object/array it finds, then inserts `em_event` records through `USBEM_Core`, `USBEM_Lookups`, `USBEM_Debug`, and `USBEM_DTI`
- email metadata is preserved in `additional_info`

## Main behavior

The transform supports these event field names directly:

- `source`
- `event_class`
- `node`
- `resource`
- `metric_name`
- `type`
- `message_key`
- `ci_type`
- `ci_identifier`
- `cmdb_ci`
- `service`
- `service_offering`
- `severity`
- `description`
- `time_of_event`
- `resolution_state`

Anything else stays in `additional_info`.

It also supports these helper inputs:

- `assignment_group`
- `usbem_car_id`
- `usbem_service`
- `usbem_offering`
- `usbem_wait_for_alert`
- `usbem_wait_seconds`
- `usbem_debug`
- `direct_to_incident`
- `dti_wait_for_incident`
- `dti_impact`
- `dti_urgency`

## DTI behavior

`direct_to_incident` is the trigger flag.

### DTI without waiting

If `direct_to_incident=true` and `dti_wait_for_incident` is not true:
- the event is inserted normally
- the connector creates or reuses the incident immediately and returns it in the same response
- DTI breadcrumbs stay in `additional_info`
- `dti_impact` / `dti_urgency` are always present in `additional_info`
- if `dti_short_description` is not provided, it is auto-filled from event `description`
- the alert link is completed asynchronously after the response returns
- the async `em_alert` reconcile rule in [servicenow/USBEM_FastDtiAlertReconcile.business_rule.js](servicenow/USBEM_FastDtiAlertReconcile.business_rule.js) prefers the original USBEM DTI incident if Event Management later creates or links a duplicate

If a late duplicate incident ever appears with the same `message_key`/`correlation_id`, the async linker prefers the original fast incident when it can safely do so.

### DTI with waiting

If `direct_to_incident=true` and `dti_wait_for_incident=true`:
- the event is inserted
- the connector waits for alert generation
- if the alert already has an incident, that incident is returned
- otherwise the connector creates an incident and links it to the alert
- the response includes event / alert / incident identifiers

### DTI incident field mapping

When the connector creates an incident synchronously:
- `dti_short_description` -> incident `short_description`
- event `description` -> incident `description`

If `direct_to_incident=true` and `dti_short_description` is omitted, the connector auto-fills `dti_short_description` from event `description`. That allows a minimal DTI payload to stay close to the standard event payload while still producing a usable incident short description.

This keeps the long description aligned to the event body.

If a payload also includes `dti_description`, it is preserved in `additional_info` but is not used for synchronous incident creation.

### DTI impact / urgency rules

The script has a small easy-to-edit config block at the top.

Current default map:

- severity `1` Critical -> impact `2`, urgency `2`
- severity `2` Major -> impact `2`, urgency `2`
- severity `3` Minor -> impact `3`, urgency `3`
- severity `4` Warning -> impact `4`, urgency `4`
- severity `0` Clear -> impact `4`, urgency `4`, no auto-incident
- severity `5` OK -> impact `4`, urgency `4`, no auto-incident

Rules:
1. If `direct_to_incident=true` and no `dti_impact` / `dti_urgency` are provided, the mapped values are added to `additional_info`.
2. If `direct_to_incident=true` and custom `dti_impact` / `dti_urgency` are provided, those values are preserved in `additional_info`.
3. If the connector creates an incident inline, it uses the provided values when present.
4. If the connector creates an incident inline and no custom values are provided, it uses the severity map.
5. No P1 values are generated by the default map.

## Assignment group behavior

`assignment_group` can be sent as:
- an exact group `sys_id`, or
- a group name string

Resolution flow:
1. exact `sys_user_group.name` match
2. canonical/token fallback for names with underscores, symbols, and separators

Example:
- `MY_Group:Name`
- `my_group_name`

On success the transform writes:

```json
"assignment_group": "<group_sys_id>"
```

It also keeps helpful lookup breadcrumbs such as:
- `assignment_group_name`
- `assignment_group_lookup_status`
- `assignment_group_lookup_method`

When `usbem_debug=true`, the connector also restores the richer lookup diagnostics into `additional_info`, including keys such as:
- `assignment_group_input`
- `assignment_group_candidate_count`
- `assignment_group_selection_reason`
- `assignment_group_candidates`
- `cmdb_ci_input`
- `cmdb_ci_candidate_count`
- `cmdb_ci_selection_reason`
- `cmdb_ci_candidates`
- `cmdb_ci_business_app_*`
- `cmdb_ci_service_*`
- `cmdb_ci_service_offering_*`

## CI / service / offering helpers

### CI lookup

The transform can resolve `cmdb_ci` by:
- provided `cmdb_ci` sys_id
- exact `cmdb_ci.name`
- canonical/token fallback for names with underscores, symbols, and separators
- `ci_type` + nested `ci_identifier`
- exact-name fallback when `node` is empty and a `name` is present

`ci_type` can be sent as either:
- the table name, such as `cmdb_ci_linux_server`, or
- the human-readable class label, such as `Linux Server`

The transform resolves human-readable class labels back to table names before doing the CI lookup.

When multiple exact-name CI matches exist, the lookup prefers higher-up CSDM / dependency-tree classes before status-based tie-breakers, such as:
- `cmdb_ci_business_app` over `cmdb_ci_service`
- `cmdb_ci_server` over `cmdb_ci_vmware_instance`

When a CI is resolved, `additional_info.cmdb_ci` is also populated with the same sys_id.
If no CI match is found, the event `cmdb_ci` field is left blank.

### Business application lookup

Input:

```json
"usbem_car_id": "1234"
```

Lookup:
- table: `cmdb_ci_business_app`
- field: `u_car_id`
- restricted to `sys_class_name = cmdb_ci_business_app`

Output:

```json
"cmdb_ci_business_app": "<business_app_sys_id>"
```

### Service lookup

Input:

```json
"usbem_service": "Service Name"
```

Lookup:
- table: `cmdb_ci_service`
- field: `name`

Output:

```json
"cmdb_ci_service": "<service_sys_id>"
```

If no `usbem_service` is provided, the script can infer a service from the resolved CI through `svc_ci_assoc`.

### Offering lookup

Input:

```json
"usbem_offering": "Offering Name"
```

Lookup:
- table: `service_offering`
- field: `name`
- if a service is known, the lookup also uses `parent=<service_sys_id>`

Output:

```json
"cmdb_ci_service_offering": "<offering_sys_id>"
```

## Wait flags

### `usbem_wait_for_alert`

Polls the inserted event and related alert state (scope-safe, no `gs.sleep`) and returns alert identifiers.

### `dti_wait_for_incident`

Polls the inserted event / alert state (scope-safe, no `gs.sleep`) and:
- returns an existing linked incident if one already exists
- otherwise creates a new incident if the DTI severity/override rules allow it

For `direct_to_incident=true` without `dti_wait_for_incident=true`, the connector keeps the no-wait fast path. It:
- creates or reuses the incident immediately, with `dti_mode=fast_async`
- returns that incident in the response
- then links the alert to that incident asynchronously after the response returns

> In scoped apps this build avoids `gs.sleep` and uses record-state polling instead.

## Response shape

For bulk payloads the response contains a `results` array.

Single-record responses also echo the first result to the top level for convenience.

`em_event` does not have an out-of-box `number` field, so the response returns `event_sys_id` only for the event itself.

Typical response fields:
- `event_sys_id`
- `message_key`
- `alert_sys_id`
- `alert_number`
- `incident_sys_id`
- `incident_number`
- `usbem_processing_ms`
- `debug_steps` when `usbem_debug=true`

## Files in this bundle

- `atf/install_usbem_atf.js`
- `src/USBEM_Core.js`
- `src/USBEM_Lookups.js`
- `src/USBEM_Debug.js`
- `src/USBEM_DTI.js`
- `src/USBEM_genericJsonV2.js`
- `src/USBEM_genericJsonV2_Full.js`
- `standalone/genericMappedJson_transform.js`
- `docs/atf_testing.md`
- `docs/install_and_behavior.md`
- `examples/ci_type_human_readable_label.json`
- `examples/sample_bulk_payload.json`
- `examples/sample_ci_identifier_payload.json`
- `examples/sample_debug_verbose_payload.json`
- `examples/sample_dti_custom_impact_urgency.json`
- `examples/sample_dti_description_mapping.json`
- `examples/sample_dti_wait_payload.json`
- `examples/sample_expected_additional_info.json`
- `examples/sample_legacy_additional_info_string.json`
- `examples/sample_minimal_dti_payload.json`
- `examples/sample_payload.json`
- `examples/sample_payload_no_message_key.json`
- `examples/sample_usbem_lookup_payload.json`
