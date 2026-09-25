# Generic Mapped JSON Push Connector

Repo version: `2026.09.25.1`
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
- the connector reuses the key's open incident, or opens a new one, and returns it in the same response
- DTI breadcrumbs stay in `additional_info`
- `dti_impact` / `dti_urgency` are always present in `additional_info`
- if `dti_short_description` is not provided, it is auto-filled from event `description`
- nothing touches the alert during the request; the link is made afterwards

Two actors attach the alert, and either may win:
- the queued `x_usbna_usb_event.link_alert_later` event, handled by the `link_alert_later` Script Action, which calls `relinkAlertToIncidentAsync`. If Event Management has not built the alert yet it re-queues itself, `fast_dti_link_delay_seconds` apart (10 by default), up to `fast_dti_link_max_retries` times (6), then stops with `alert_not_found`.
- the async `em_alert` reconcile rule in [servicenow/USBEM_FastDtiAlertReconcile.business_rule.js](servicenow/USBEM_FastDtiAlertReconcile.business_rule.js), which fires as soon as the alert is created or updated.

Both write through the same conditional claim, so the loser reports what it found instead of overwriting it. Whichever runs second typically logs `already_linked`.

Note that this path returns before the alert exists, so `usbem_wait_for_alert` has no effect when it is combined with `direct_to_incident=true` and `dti_wait_for_incident=false`: no alert identifiers come back.

### DTI with waiting

If `direct_to_incident=true` and `dti_wait_for_incident=true`:
- the event is inserted
- the connector waits for alert generation
- if the alert already has a **reusable** incident, that incident is returned
- otherwise the connector creates an incident and links it to the alert during the request
- the response includes event / alert / incident identifiers

### Terminal incidents end the reuse window

A message key stops reusing its incident once that incident reaches a terminal state. The next event opens a new incident, later events reuse the new one while it stays open, and the alert is moved across.

- terminal states come from `x_usbna_usb_event.dti_terminal_incident_states`, default `6,7,8` (Resolved, Closed, Canceled)
- the test is on `state`, never `active`: a Resolved incident is still `active=true`
- the value must be a comma-separated list of integer states. Anything else (labels, `;` separators) falls back to the default and logs one warning, so a typo cannot quietly re-enable reuse of finished incidents
- setting it to `0`, a state that does not exist, is the kill switch: it restores the pre-fix behaviour without a code change
- the correlation lookup excludes terminal states in the query, so a key that has cycled through many incidents stays fast; among open incidents the oldest still wins

Statuses that name a terminal skip or relink, in `dti_incident_status` and in the async linker's logged outcome:

| Status | Meaning |
|---|---|
| `created_fast_after_terminal` | fast path opened a new incident because the key's incident was finished |
| `existing_fast_after_terminal` | fast path skipped a finished incident and returned the key's open one |
| `created_after_terminal` | wait path opened a new incident; the alert was left where it was |
| `claimed_from_terminal_incident` | wait path moved the alert off a finished incident onto the open one |
| `relinked_from_terminal_incident` | the alert was moved off a finished incident onto the new one |
| `kept_terminal_incident` | the alert was deliberately left on a finished incident (foreign task, or the preference rules declined) |
| `existing_after_terminal` / `existing_unlinked` | the open incident was returned without claiming the alert |
| `skipped_closed_alert` | reconcile left a Closed alert on the incident of the cycle it closed with |
| `alert_link_changed` | the alert moved to something that is not an incident before the claim landed |

An alert is only ever written when its link is empty or holds one of our own incidents, and every write is conditional on the exact link that was inspected.

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

The group on a DTI incident is resolved in this order:

1. `cmdb_ci.support_group`
2. `cmdb_ci.u_level_2_support_assignee_group`
3. `assignment_group` from the payload
4. nothing — the incident is left unassigned

The CI fields are an ordered list, `CI_SUPPORT_GROUP_FIELDS` in `src/USBEM_Lookups.js`; adding a level 3 tier is one entry. A field that does not exist on the instance is skipped rather than treated as an error, so the same code runs on instances that never got the custom fields. The lookup reports which field matched, for example `cmdb_ci_u_level_2_support_assignee_group`.

Note that a CI-derived group beats an `assignment_group` supplied in the payload.

There is no default or placeholder group. An incident nobody owns is left unassigned rather than parked on a catch-all group where it goes unnoticed, so `x_usbna_usb_event.default_assignment_group_sys_id` is no longer read.

The two custom fields are reference fields to `sys_user_group`. Create them with
[servicenow/install_ci_support_tier_fields.background.js](servicenow/install_ci_support_tier_fields.background.js)
rather than moving them between instances; see [docs/dti_transfer_package.md](docs/dti_transfer_package.md).

### Sending a group on the payload

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
- reuses the key's open incident or opens a new one, with `dti_mode=fast_async`
- returns that incident in the response
- then links the alert to that incident asynchronously after the response returns, with bounded retries

This branch short-circuits before the `usbem_wait_for_alert` handling, so a fast-path call never returns alert identifiers even if that flag is set.

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
- `dti_mode` — `fast_async` or `wait_for_incident`
- `dti_incident_status` — how the incident was chosen; see the terminal-incident table above
- `dti_link_status` — `queued` or `queue_failed` on the fast path
- `usbem_processing_ms`
- `debug_steps` when `usbem_debug=true`

## Testing

[tests/dti_terminal_incident_check.py](tests/dti_terminal_incident_check.py) checks the DTI behaviour against a live instance. Standard library only, self-cleaning, exit code 0/1.

```bash
python3 tests/dti_terminal_incident_check.py            # all cases, both modes
python3 tests/dti_terminal_incident_check.py --listener  # add the REST-path check
```

It covers a new key, an open incident in each open state, each terminal state and the events that follow, alert relinking, a closed alert, non-DTI and foreign-linked alerts, message keys longer than `correlation_id`, the async retry bound, and the CI support tier chain. Concurrency and timing are reported as observations. It needs an admin account, because it drives the Script Include through a background script.

## Known gaps

- **The deployed listener carries its own copy.** The `USBEM genericJsonV2` Event Management listener is an inlined build with its own older `USBEM_DTI`, `USBEM_Core` and `USBEM_Lookups`. Changes to the Script Includes do not reach callers of the REST endpoint until that build is regenerated. Only the async Script Action and the reconcile business rule use the Script Includes.
- **`cmdb_rel_ci` read privilege.** Where the scope runs with `runtime_access_tracking = enforcing` and has no privilege for `cmdb_rel_ci`, any event that resolves to a real CI throws `ScopeAccessNotGrantedException` before the support-group logic runs.
- **No duplicate protection on the fast path.** Simultaneous events for one key can each open an incident. This predates the terminal-incident work and is reported as an observation by the test suite.
- **Message keys longer than `incident.correlation_id`** (100 characters out of box) can only be matched through the alert link, because the correlation lookup queries the full key. An event that arrives while the alert is briefly unlinked opens another incident.

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
- `docs/dti_transfer_package.md`
- `docs/install_and_behavior.md`
- `servicenow/install_ci_support_tier_fields.background.js`
- `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`
- `tests/dti_terminal_incident_check.py`
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
