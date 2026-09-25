# Generic Mapped JSON Push Connector

Repo version: `2026.09.25.3`
Release history: [CHANGELOG.md](CHANGELOG.md)

Every script in this project carries that version, and the endpoint reports all of them in every
response under `versions`, so you can tell what an instance is actually running without opening a
single record:

```json
"version": "2026.09.25.3",
"versions": {"listener": "2026.09.25.3", "core": "2026.09.25.3",
             "lookups": "2026.09.25.3", "debug": "2026.09.25.3", "dti": "2026.09.25.3"}
```

The business rule has no response to report into, so it logs its version with every outcome
(`USBEM fast DTI alert reconcile [v2026.09.25.3] outcome: ...`).

The repo release version is separate from the locked standalone ServiceNow transform in
`standalone/genericMappedJson_transform.js`, which remains `2026-03-18a` for the final path.

The repo also carries the live modular `genericJsonV2` source layout used in PDIs:
- `src/USBEM_Core.js`
- `src/USBEM_Lookups.js`
- `src/USBEM_Debug.js`
- `src/USBEM_DTI.js`
- `servicenow/USBEM_genericJsonV2.listener.js`

The repo also includes ATF assets for environment testing:
- `atf/install_usbem_atf.js`
- `docs/atf_testing.md`

The Linux systemd synthetic under `synthetic/` runs every five minutes, validates DTI duplicate handling through live `em_event` and `incident` readback, removes the successful probe incident, emits an OK event, and creates a separately assigned DTI incident plus SMTP email only on failure. Installation and operations are documented in `kb/generic_json_v2_dti_linux_synthetic.md`.

## Installing

Starting from a clean instance: [docs/install_from_scratch.md](docs/install_from_scratch.md) walks
through the scoped app, the four Script Includes, the inbound listener, the reconcile rule,
properties, the CI support tier fields, the cross-scope privileges and verification. To push the
repo at an instance and read back what it is running:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/deploy_usbem.py
``` Moving this work between existing instances: [docs/dti_transfer_package.md](docs/dti_transfer_package.md).

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
  - `servicenow/USBEM_genericJsonV2.listener.js` — the listener script itself, which constructs
    the four Script Includes and holds no copy of them. The inlined build that used to live in
    `src/USBEM_genericJsonV2_Full.js` is gone: it drifted, and REST callers silently ran
    months-old logic while the Script Includes were current
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

`direct_to_incident: true` returns an incident in the same response:

- the event is inserted normally
- the connector reuses the key's open incident, or opens a new one
- the incident comes back in the response; nothing waits for Event Management
- if the alert already exists — every event after the first for a key — it is attached during the
  request with one conditional write, and `alert_link_status` says `linked` or `relinked`
- otherwise the alert is attached by the `USBEM Fast DTI Alert Reconcile` business rule the moment
  Event Management creates it

There are no queued events, no Script Actions and no retry loop. The business rule is a
synchronous `after` rule with a condition, because Event Management best practices say plainly:
"Do not write async business rules for alert tables."

### DTI with waiting

`dti_wait_for_incident: true` keeps the original behaviour: insert, poll for the alert, reuse a
reusable linked incident or create one and link it inside the request. Slower, and only needed if
you want the alert identifiers back in the same response.

### Incident fields

The endpoint replaces a direct write to the incident table, so send incident fields under their
real names and they are written as-is:

```json
{
  "source": "MyApp Monitor", "node": "VM1234", "severity": "1",
  "description": "Service is down", "direct_to_incident": "true",
  "caller_id": "Abel Tuter", "category": "Software", "subcategory": "Email",
  "contact_type": "Integration", "work_notes": "note for the incident",
  "alert_work_notes": "note for the alert"
}
```

- any field that exists on `incident` is accepted; `sys_id`, `number`, `correlation_id` and
  `correlation_display` are owned by the connector and ignored
- a 32-character value is used as a sys_id, anything else is resolved as a display value, so
  `"category": "Software"` and `"caller_id": "Abel Tuter"` both work
- what was applied and what was ignored comes back as `incident_fields_applied` and
  `incident_fields_skipped`
- `work_notes` goes on the incident, `alert_work_notes` on the alert; the legacy
  `dti_work_note` still works

#### Defaults the connector applies first

These reproduce the retired **EM - Generic Endpoint Create Incident** subflow, which is what this
endpoint replaced. They are applied before the payload, so anything you send overrides them.

| Field | Default | Notes |
|---|---|---|
| `u_netcool_ticket` | `true` | on every incident this connector creates; skipped where the field does not exist |
| `category` | `Software` | |
| `subcategory` | `Monitoring Alert` | |
| `caller_id` | user `Event Management` | resolved through the reference field, so no sys_id is baked in |
| `impact` / `urgency` | from the severity map | severity 1 and 2 give 2/2, which is what the subflow's "Create P2 Incident" step set |
| `u_generating_alert` | the alert | written when the alert exists: at creation in wait mode, at link time on the fast path |
| `assignment_group` | the alert's group | last resort only, after the payload group and the CI support tiers |
| `work_notes` | `Direct To Incident Via Event Management Generic JSON Endpoint` + `Incident Created From <alert or message key>` | your own note is appended to it |

An instance can refuse any of these — a scoped app is not always granted read on `sys_user` or
write on `incident`. A refusal costs that one field, never the event: the names come back in
`incident_defaults_skipped` and the incident is still created and returned.

When an event reuses an existing incident instead of creating one, the connector adds
`Duplicate event received via Event Management Generic JSON Endpoint (<message key>)`, as the
subflow's duplicate branch did. Set `x_usbna_usb_event.dti_duplicate_work_note` to `false` to turn
that off. Annotating an existing incident needs **write** access to `incident`; where the scope
only has create, the response reports `incident_work_note: skipped` with a reason.

### Terminal incidents end the reuse window

A message key stops reusing its incident once that incident reaches a terminal state. The next event opens a new incident, later events reuse the new one while it stays open, and the alert is moved across.

- terminal states come from `x_usbna_usb_event.dti_terminal_incident_states`, default `6,7,8` (Resolved, Closed, Canceled)
- the test is on `state`, never `active`: a Resolved incident is still `active=true`
- the value must be a comma-separated list of integer states. Anything else (labels, `;` separators) falls back to the default and logs one warning, so a typo cannot quietly re-enable reuse of finished incidents
- setting it to `0`, a state that does not exist, is the kill switch: it restores the pre-fix behaviour without a code change
- the correlation lookup excludes terminal states in the query, so a key that has cycled through many incidents stays fast; among open incidents the oldest still wins

Statuses that name a terminal skip or relink, in `dti_incident_status` and in the reconcile rule's logged outcome:

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

1. `assignment_group` from the payload
2. `cmdb_ci.support_group`
3. `cmdb_ci.u_level_2_support_assignee_group`
4. nothing — the incident is left unassigned

The CI fields are an ordered list, `CI_SUPPORT_GROUP_FIELDS` in `src/USBEM_Lookups.js`; adding a level 3 tier is one entry. A field that does not exist on the instance is skipped rather than treated as an error, so the same code runs on instances that never got the custom fields. The lookup reports which field matched, for example `cmdb_ci_u_level_2_support_assignee_group`.

A group named on the event wins: the caller knows where the work should go, and the CI is the fallback. The CI is only read when the event did not name a group.

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
- `dti_version` — the `USBEM_DTI` version that handled the incident
- `alert_link_status` — `linked`, `relinked` or `deferred_to_reconcile_rule` when the alert
  already existed and the fast path attached it during the request
- `incident_fields_applied` / `incident_fields_skipped` — which payload fields were written
- `incident_netcool_ticket`, `incident_caller_default`, `incident_defaults_skipped` — what the
  connector defaults did
- `incident_work_note` — `reuse` when a duplicate note was added, `skipped` with
  `incident_work_note_skipped_reason` when the instance would not allow it
- `usbem_processing_ms`
- `debug_steps` when `usbem_debug=true`
- `version` and `versions` on the envelope, as shown at the top of this file

## Testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 tests/verify_usbem_connector.py
```

[tests/verify_usbem_connector.py](tests/verify_usbem_connector.py) drives the live endpoint the
way a sender does, tags everything it creates with a unique prefix, deletes it afterwards, and
exits non-zero if anything failed. Groups, selectable with `--only`:

| Group | What it proves |
|---|---|
| `deploy` | the endpoint reports this release's version for every component, and each instance record still matches the file in this repo |
| `compat` | the original contract holds: plain events, `records` batches, no incident without DTI, and the legacy `dti_short_description` / `dti_work_note` names |
| `fast` | `direct_to_incident` returns an incident immediately, reuses it while open, opens a new one once it is Resolved/Closed/Canceled, and the alert follows |
| `wait` | the same cycle with `dti_wait_for_incident=true` |
| `fields` | NetCool, category, subcategory, caller, impact/urgency, and every payload override |
| `notes` | the connector note, the created-from line, sender notes on the incident, `alert_work_notes` on the alert, and a plain `work_notes` on a non-DTI alert |
| `timing` | round-trip milliseconds for each path, reported as an observation |

`--keep` leaves the records in place for inspection, `--json out.json` writes the results, and
`--prefix` sets the tag. It needs an admin account: resolving and closing incidents goes through a
background script, because the Table API trips over the mandatory close fields.

**Python on macOS.** Use the venv and `requirements.txt` above. The scripts talk to ServiceNow
through `requests`, which carries its own CA bundle; the stdlib `urllib` in a fresh macOS venv has
no usable one and fails valid certificates with `CERTIFICATE_VERIFY_FAILED`. If your network
terminates TLS with a corporate root, point `SN_CA_BUNDLE` at that root instead of disabling
verification. `SN_VERIFY_SSL=false` exists as a last resort.

## Known gaps

- **The scope cannot update incidents here.** `x_usbna_usb_event` runs with
  `runtime_access_tracking = enforcing` and, on dev382837, is granted create but not write on
  `incident`. Creating and returning an incident works; annotating one that already exists (the
  duplicate work note) and writing `u_generating_alert` after the fact do not. Both report the
  skip instead of failing the event. Grant the scope write on `incident` where those matter.
- **`cmdb_rel_ci` read privilege.** Same enforcing scope, no privilege for `cmdb_rel_ci`: any
  event that resolves to a real CI throws `ScopeAccessNotGrantedException` before the
  support-group logic runs.
- **No duplicate protection on the fast path.** Simultaneous events for one key can each open an
  incident. This predates the terminal-incident work.
- **Message keys longer than `incident.correlation_id`** (100 characters out of box) can only be
  matched through the alert link, because the correlation lookup queries the full key. An event
  that arrives while the alert is briefly unlinked opens another incident.

## Files in this bundle

Runtime:

- `src/USBEM_Core.js`, `src/USBEM_Lookups.js`, `src/USBEM_Debug.js`, `src/USBEM_DTI.js`
- `servicenow/USBEM_genericJsonV2.listener.js` — the push connector listener
- `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` — the `em_alert` reconcile rule
- `servicenow/install_ci_support_tier_fields.background.js` — the two CI support tier fields
- `servicenow/USBEM_JabberwockyInboundEmail.flow_action.js` — the optional inbound email bridge
- `standalone/genericMappedJson_transform.js` — the locked standalone transform

Tooling:

- `requirements.txt`, `scripts/usbem_client.py`
- `scripts/deploy_usbem.py` — push the repo to an instance and read back its versions
- `tests/verify_usbem_connector.py` — live end-to-end verification

Docs:

- `docs/install_from_scratch.md`, `docs/install_and_behavior.md`, `docs/dti_transfer_package.md`,
  `docs/atf_testing.md`, `docs/production-transfer-inventory.md`
- `atf/install_usbem_atf.js`
- `examples/` — sample payloads for each supported shape
