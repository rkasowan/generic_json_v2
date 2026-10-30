# Generic Mapped JSON Push Connector

Repo version: `2026.10.29.3`
Release history: [CHANGELOG.md](CHANGELOG.md)

Current laptop deliverable: **Python suite `1.3.0`, published article `1.7.0`**. Put the updated script,
your `production_test.env`, and your already-filled `dev-fixtures.json` in the same private folder,
then run `python test_ci_identifier_precedence.py`. No flags, options, pip packages or extra
test program are needed. A readable summary appears on screen; detailed JSON results are saved
automatically beside the script.
Missing optional advanced fixtures are reported INCOMPLETE without blocking the baseline tests;
they never become PASS. The 85-entry report retains the enforced connector POST + Event R +
Alert RW + Incident RW boundary, with no reference/admin reads or administrator fallback.
Runtime `2026.10.29.3` is unchanged. Updated-version offline validation passes 446 Python tests
plus 234 JavaScript checks (680 total), including 30 new laptop-entry tests. The frozen suite
1.3.0 program SHA-256 is `c39760011c871a659ae40e2c5cc03ca592f4b702d93439d1acd01739298748ab`.
Focused DEV invocation proof completed in 132.586 seconds: five selected checks passed and two
deliberately unavailable optional features were skipped, correctly producing INCOMPLETE/exit 4.
Independent GET-only readback verified four Processed Events, three Incidents, three Alerts and
21 required-field checks. This used the actual no-argument path with private focused dispatch
and an in-memory DEV connection; sidecar parsing was tested offline. It is not all-85 live
acceptance or actual restricted production-identity proof. Article `1.7.0` is published and
reader-verified in matching dev392825, with exact source-body readback and actual attachment links.
See [the three-step laptop instructions](docs/production-test-usage.md).
Updated-version evidence: [one-command validation](docs/validation-2026-10-29-one-command.md).

Historical suite `1.2.0` / article `1.6.0` evidence follows. Those exact bytes were validated and
published in matching DEV; this is not validation of suite `1.3.0`. No actual production instance
or restricted production identity is claimed tested.
Historical local validation passed 416 Python and 234 JavaScript checks (650 total), including 102
production unit methods. The independent native-Alert model exercised all 85 actual production
callbacks: 84 passed and one reported the accepted concurrency limitation. Its 102 modeled cases
made 119 connector calls, 11 negative probes, 24 formatted-note reads, three debug companions
and five owned PATCH operations. That simulated result is not full live production acceptance.
The frozen program SHA-256 is `68db4a360ae112c223e327bc5a51f1f5bc2e77703353b42a96dc2d3bf4f5d280`.
Its exact-file focused DEV run completed 20 checks over 33 cases in 725.494 seconds: 19 PASS,
one accepted concurrency limitation, zero failures/errors/skips. Maximum POST was 1.137 seconds;
minimum case stability was 34.813 seconds, with eight formatted-note observations and three
debug companions. Three simultaneous first requests created three test Incidents, reproducing
the accepted race. Independent GET-only readback passed: three queries, zero writes, 45 retained
Events all Processed (42 primary + three debug), 15 Incidents, 25 Alerts and 98 required-field
checks; expected stored fields/links remained unchanged. This is not full 85-feature live
acceptance or actual production-identity proof. See [the scoped validation report](docs/validation-2026-10-29-production-access.md).

The separate suite `1.1.0` provisioned-fixture administrative full retest remains incomplete,
including the unapproved business-application read privilege and default-CI prerequisites.
Article `1.5.0` was a pending source draft, not a published milestone. That broader gate does
not prevent delivery of the separately scoped three-table production test. No grant or runtime
change is part of this production-test update.

The prior suite `1.0.0` exact-file full Python run completed
in 1749.514 seconds: 75 features passed, one failed, nine were skipped, and one retained the
accepted limitation (93 cases; no errors). Its raw status is `fail`, exit 2. The sole failed
assertion used our incorrect lowercase default-category fixture; the same-file corrected-fixture
supplemental defaults check passed both cases. That does not rewrite the raw full failure or
close the nine unavailable-feature gaps. No clean full-suite pass is claimed.

Historical corrected-path DEV retest PASS belongs to `2026.10.29.2` only.
[The release retest](docs/validation-2026-10-29.2.md) records 714.405 seconds, 50 positive
scenarios, ten malformed-payload probes, exact six-source readback, and 204 passing local tests.
It closes the prior wrapped-field, follow-up Alert note, shape-validation, debug-privilege,
and installer findings. This is not production-identity or concurrency certification:
the accepted simultaneous-first-event race remains unchanged. Retest each target before promotion.

The existing matching DEV Knowledge article is
[KB0010015 on dev392825](https://dev392825.service-now.com/kb_view.do?sys_kb_id=7433ede097d457105fb3ba6de053af9b),
where article `1.7.0` is published, active, latest and reader-verified with reader-visible
attachments and exact normalized source-body readback. The current Python program and new focused
evidence were byte-verified through authenticated API and reader downloads; anonymous requests
do not return files. The reader renders actual download links for the Python program, production
env/catalog and usage guide. Previous script/usage copies are replaced with recovery copies
retained; historical reports remain intact. Article `1.6.0` is the prior suite's historical evidence;
article `1.4.0` is older historical evidence, and
`1.5.0` was never published. The provisioned administrative full retest remains incomplete.
The historical sanitized milestone is published as `6e7c1a5`; this suite `1.3.0` release contains
reviewed sanitized source and summary. Full machine reports
and filled fixtures remain private to the matching PDI/ignored local evidence.
Implementation and documentation must use the same explicitly selected PDI.

Every modular runtime component carries that version, and the endpoint reports its API components in every
response under `versions`, so you can tell what an instance is actually running without opening a
single record:

```json
"version": "2026.10.29.3",
"versions": {"listener": "2026.10.29.3", "core": "2026.10.29.3",
             "lookups": "2026.10.29.3", "debug": "2026.10.29.3", "dti": "2026.10.29.3"}
```

The business rule has no response to report into, so it logs its version with every outcome
(`USBEM fast DTI alert reconcile [v2026.10.29.3] outcome: ...`).

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

The DTI deliverable is the connector API, its correlation-based alert reconcile Business Rule,
and one comprehensive standalone Python tester in `tests/test_ci_identifier_precedence.py`.
The historical filename is retained. Running it without arguments now selects the three-table
production-safe laptop workflow and reads the existing sidecar configuration files. It does not
require another Python program, new options or replacement of your filled fixtures.
Runtime `.3` is already deployed and six-source readback matched. Prior reports are historical
runtime evidence, not a pass for the updated tester. Matching DEV article `1.7.0` and its current
script/configuration/usage links are published and reader-verified. Suite `1.2.0` / article `1.6.0`
evidence remains historical.
Historical `1.4.0` reports remain; no article `1.5.0` publication is claimed.
The test runs on demand from a work laptop; no Linux service, root account, scheduler, or
monitoring email setup is required. See [the DTI API and test guide](kb/generic_json_v2_dti_api_and_tests.md).

## Installing

Starting from a clean instance: [docs/install_from_scratch.md](docs/install_from_scratch.md) walks
through the scoped app, the four Script Includes, the inbound listener, the reconcile rule,
properties, the CI support tier fields, the cross-scope privileges and verification. To push the
repo at an instance and read back what it is running:

```bash
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
python3 scripts/deploy_jabberwocky_flow_action.py
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

The rule must have **Advanced=true**. Pending `work_notes` / `alert_work_notes` metadata can
run even with an open linked Incident so follow-up Alert notes can be journaled. DTI-only
metadata remains restricted to alerts with no Incident or a terminal Incident. Transfer the
condition together with the script; the deployer verifies stored source and configuration after
both creation and update. See [the exact BR configuration](docs/dti_transfer_package.md#the-business-rules-configuration-is-part-of-the-package).

### DTI with waiting

`dti_wait_for_incident: true` keeps the original behaviour: insert, poll for the alert, reuse a
reusable linked incident or create one and link it inside the request. Slower, and only needed if
you want the alert identifiers back in the same response.

### Incident fields

The endpoint replaces a direct write to the incident table, so send incident fields under their
real names. Prefer the target's stored choice values and verify actual stored references/choices:

```json
{
  "source": "MyApp Monitor", "node": "VM1234", "severity": "1",
  "description": "Service is down", "direct_to_incident": "true",
  "caller_id": "Abel Tuter", "category": "software", "subcategory": "email",
  "contact_type": "integration", "work_notes": "note for the incident",
  "alert_work_notes": "note for the alert"
}
```

- any field that exists on `incident` is accepted; `sys_id`, `number`, `correlation_id` and
  `correlation_display` are owned by the connector and ignored
- a 32-character value is used as a sys_id; other scalar fields use the display setter, whose
  stored result must be checked on the target; `caller_id` / `assigned_to` accept a sys_id or exact full name
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
| `caller_id` | `x_usbna_usb_event.default_caller_sys_id` | per-instance sys_id used when omitted or when a supplied full name is missing, ambiguous, or cannot be looked up |
| `impact` / `urgency` | from the severity map | severity 1 and 2 give 2/2, which is what the subflow's "Create P2 Incident" step set |
| `u_generating_alert` | the alert | written when the alert exists: at creation in wait mode, at link time on the fast path |
| `assignment_group` | the alert's group | last resort only, after the payload group and the CI support tiers |
| `work_notes` | `Direct To Incident Via Event Management Generic JSON Endpoint` + `Incident Created From <alert or message key>` | your own note is appended to it |

For `caller_id` and `assigned_to`, send a sys_id or an exact full name. Full names are resolved
inside the scoped Script Include through an exact `sys_user.name` query, so the scope needs
`sys_user` read. A missing, ambiguous, or unavailable caller lookup uses the configured default
caller sys_id; an unresolved `assigned_to` is left blank so on-call assignment can populate it.
The API verifier does not query `sys_user`; it checks the resulting references through Incident
readback. A denied scoped lookup costs that reference value, never the event.

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
| `created_unlinked` / `existing_unlinked` | the incident is returned but the alert holds a task we may not replace; `alert_link_status: deferred_to_reconcile_rule` says the same on the fast path |

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
4. the alert's own `assignment_group`, where the alert already exists — reported as
   `assignment_group_source: alert`
5. nothing — the incident is left unassigned

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

`additional_info` on the event carries the resolved sys_ids and the request's own flags, nothing
else: `cmdb_ci`, `assignment_group`, `cmdb_ci_business_app`, `cmdb_ci_service`,
`cmdb_ci_service_offering`, plus `direct_to_incident`, `dti_short_description`, `dti_impact`,
`dti_urgency`, `dti_work_note`, `dti_wait_for_incident` and `usbem_wait_for_alert`.

The lookup diagnostics — what was searched for, which candidates scored, why one won — are not
written there. With `usbem_debug=true` they go to the companion debug event as attachments
(`04_lookup_trace.json`, `05_candidate_scores.json`, `06_correlation_hints.json`); see
[docs/atf_testing.md](docs/atf_testing.md).

## CI / service / offering helpers

### CI lookup

The transform can resolve `cmdb_ci` by:
- provided `cmdb_ci` sys_id
- `ci_type` + nested `ci_identifier`
- exact `cmdb_ci.name`
- canonical/token fallback for names with underscores, symbols, and separators
- exact-name fallback when `node` is empty and a `name` is present

When a payload contains both a textual `cmdb_ci` and `ci_type` + `ci_identifier`, the class-scoped
identifier lookup wins. A literal `cmdb_ci` sys_id remains authoritative. The textual name is used
only when the identifier does not resolve.

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

Polls the inserted event and the alert it produces, and returns alert identifiers.

### `dti_wait_for_incident`

Polls the inserted event and alert state, and:
- returns an existing linked incident if one already exists
- otherwise creates a new incident if the DTI severity/override rules allow it

For `direct_to_incident=true` without `dti_wait_for_incident=true`, the connector keeps the no-wait fast path. It:
- reuses the key's open incident or opens a new one, with `dti_mode=fast_async`
- returns that incident in the response
- claims an alert that already exists during the request, and otherwise leaves the link to the
  synchronous `after` reconcile rule on `em_alert`

This branch short-circuits before the `usbem_wait_for_alert` handling, so a fast-path call never returns alert identifiers even if that flag is set.

> Waiting costs a REST worker thread for as long as it lasts, so prefer the fast path where you
> can. Between polls the loop calls `gs.sleep`, which a scoped application is allowed to do on
> current releases (verified on Zurich); where an instance refuses it, the loop falls back to
> spinning, which is what every release before 2026.09.28.1 did everywhere.

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
- `alert_link_status` — `linked`, `relinked`, `already_linked` or `deferred_to_reconcile_rule`
  when the alert already existed and the fast path attached it during the request
- `assignment_group_source` — `alert` when the group came from the alert rather than the payload
  or the CI
- `incident_fields_applied` / `incident_fields_skipped` — which payload fields were written
- `incident_netcool_ticket`, `incident_caller_default`, `incident_defaults_skipped` — what the
  connector defaults did
- `incident_work_note` — `reuse` when a duplicate note was added, `skipped` with
  `incident_work_note_skipped_reason` when the instance would not allow it
- `usbem_processing_ms`
- `debug_steps` when `usbem_debug=true`
- `version` and `versions` on the envelope, as shown at the top of this file

## Testing

The canonical laptop test is **one file**, `tests/test_ci_identifier_precedence.py`. Its
historical filename is retained, but it is not a CI-only check. It uses stock Python 3.9+ and imports no other project
file. No Linux service, root account, scheduler, monitoring email, or required pip package is involved.
The Python suite is version `1.3.0`, separate from runtime `2026.10.29.3`. Report provenance
includes the executing file's module-load SHA-256 as well as the suite version.

1. Keep the updated script, `production_test.env`, and your already-filled `dev-fixtures.json`
   together in the same private folder. Do not replace your filled files with the examples.
2. Open Terminal or PowerShell in that folder and run:

   ```bash
   python test_ci_identifier_precedence.py
   ```

   Use `python3` or `py -3` if that is your computer's Python command.
3. Review the on-screen summary. A detailed `dti-results-....json` file is saved automatically
   in the same folder.
   Allow many minutes for actual processing and stability checks.

With no arguments, the script reads only the files beside itself, not inherited shell credentials
or files in another working directory. It uses a nonblank `USBEM_DEV_URL`, otherwise
`SN_INSTANCE_URL`, from that env file and displays the selected target. It runs one target only;
it never automatically advances through environments. Existing Basic/OAuth and plain/base64
credential settings remain supported.

Valid baseline CI, caller, required-field and assignment settings are required. Missing optional
advanced fixture data no longer stops unrelated checks: each unavailable feature is reported
INCOMPLETE, and all 85 manifest entries remain visible. Malformed JSON, unsafe baseline configuration
or failed baseline controls stop safely with an actionable explanation. The existing catalog is
configuration, not another test program. The script neither creates production fixtures nor
requests CMDB/user/property access; independent expected references must still come from the owner.

### Production access profile

The 85-feature production manifest follows the actual connector → processed Event → Alert →
Incident path, including fast no-wait creation, the seven required fields, CI precedence and
Event/Alert/Incident CI binding, duplicates, wrappers/batches, errors, routing, severity/clear,
notes, terminal replacements and ownership guards. It requires only the existing connector POST,
Event read, Alert read/write and Incident read/write. A transport allowlist forbids all other
table access, dot-walks, direct Event writes, creates/deletes, administrative setup and attachment
downloads. Fresh ownership readback precedes every lifecycle/guard PATCH.

Those rights prove observable functionality, not hidden administrative evidence. Note sentinels
are checked in the formatted visible `work_notes` view of the exact owned Incident/Alert, after
a fresh raw ownership read. Blank or missing formatted views are incomplete, including for
negative assertions. This proves only presence/absence within that visible view, not complete
raw journal history, exact global counts, or ACL-hidden entries. Debug companion Event metadata is not downloaded
attachment proof; reference-source facts are owner-attested rather than independently queried.
The non-Incident Task guard is excluded because its Task baseline cannot be read. The report names
these boundaries; production completion is not the broader comprehensive-profile certification.
Missing fixtures, required customer fields or field ACLs remain INCOMPLETE/nonzero.

Run only the intended target, reviewing its report before moving through the SDLC. The no-argument
workflow does not inspect other configured URLs to choose a fallback target. Shared Basic usernames
with per-profile passwords and existing per-profile OAuth credentials are supported. Assignment
is configured by `USBEM_ASSIGNMENT_GROUP` and its exact expected ID, without code edits.
See [the three-step production usage guide](docs/production-test-usage.md).

The run creates real retained test Incidents/Alerts. Normal platform notifications, email,
outage rules and other Business Rules can fire; the script does not suppress them. Choose an
approved caller/group/CI and testing window. It installs no service, root process, scheduler or
email notifier. Three parallel first events still exercise the accepted duplicate-Incident race.

### Broader comprehensive profile

The remaining configuration/admin guidance is advanced compatibility guidance for the broader
`comprehensive` command-line profile, not the no-argument laptop workflow.
Use it only with its separately required reference, journal and attachment access. Its ordinary
env template is `tests/ci_identifier_test.env.example`; explicit DEV fixture administration is
not available in production mode. Historical failed/incomplete administrative evidence is retained.

`--list-tests` and `--plan` inspect coverage without credentials or network writes. For a live
run, configure the selected target's Basic credentials (plain or base64), OAuth client credentials,
or an existing profile such as `--env-file tests/usbem_verify.env --profile itsmnowDEVworker`.
The selected profile must have a non-empty `USBEM_<PROFILE>_URL`; a missing/blank selected URL
stops before network access instead of falling back to a global PDI. An explicit `--instance`
wins. Unselected blank profiles are ignored, so DEV can be configured before the other targets.
Profile names that normalize to an empty key are rejected.
Base64 is reversible encoding, not hashing or encryption. Keep filled configuration private.
Generated outputs use atomic replacement and POSIX mode 0600 where supported. On Windows,
store credentials, catalogs and reports in a user-only NTFS folder: POSIX mode bits and
`mkstemp` cannot establish private Windows ACLs. This privacy requirement also applies to the
administrative catalogs and recovery journals described below.
TLS verification is enabled; `--ca-bundle` supplies corporate trust roots. Redirects and automatic
POST retries are disabled.
The GitHub repository is public. Filled fixtures and full JSON reports are not public-safe merely
because they omit credentials: they contain target and record metadata. Keep detailed execution
evidence in the selected PDI's Knowledge attachments; publish only a reviewed sanitized summary.

The env template contains common CI/required-field settings. An ordinary run also needs a
target-specific JSON reference catalog, passed with `--fixture` or the
`USBEM_TEST_FIXTURES_JSON` JSON-object setting. This is configuration, not another test script.
See [the comprehensive KB configuration](kb/generic_json_v2_dti_api_and_tests.md#comprehensive-profile-configuration-and-dev-setup)
for its top-level fixture names and advanced-case schema. Missing fixtures or evidence access
produce INCOMPLETE/nonzero, not a smaller green test disguised as full acceptance.
Complete coverage requires a group input and exact expected sys_id. Advanced cases may be arrays:
offering parent filtering requires positive/negative controls, and default-CI policy requires
three distinct controls including a real configured non-empty default CI. No default configured
means that family remains incomplete unless the separately authorized DEV provisioning/property
mode is selected. Canonical inputs must be genuine name variants beyond
letter case. User additional-info expectations preserve native JSON booleans, numbers, arrays,
and objects; connector-added routing/DTI values follow their operational string contract.
Expectations can also require absent keys. Root/envelope Event/SPECIAL aliases beat conflicting
wrapped aliases, while wrapped real Incident passthrough fields overlay envelope Incident defaults.
Set `duplicate_work_note_enabled` to the actual target property's JSON boolean value; the tester
does not change it.
Provide `default_category` and `default_subcategory` as independently verified stored runtime
defaults, not the override choices from the env. The suite omits those payload fields to test
defaulting and separately omits DTI short description to prove Event-description autofill.
Do not infer `default_category` solely from a choice label. The DEV parity default is stored
literally as `Software`, not its canonical PDI choice value `software`; `Monitoring Alert` is
also a customer parity literal. The supplied required-field checks prove filled/stored values,
not choice-taxonomy validity. Prefer explicit target stored choice values in production.
The prior suite `1.0.0` corrected-fixture supplemental check passed both defaults cases in 44.619 seconds using
the same final script, actual Event/Incident/Alert readback and a 30-second stable window.
That separate result does not rewrite the exact-file full run's raw `fail`/exit 2 or constitute
a clean full-suite pass. Its 75 pass / 1 fail / 9 skip / 1 known-limitation result remains intact.
Advanced Incident-field families require `want_incident:true`; they cannot go green by disabling
the very Incident whose fields must be inspected.
Where local resolution requires it, `terminal_extra_fields` can contain only a non-empty string
`u_cause`; the field must already exist and its stored value is checked after the owned update.

### Explicit DEV fixture setup

The same file adds privileged setup only when `--provision-dev-fixtures` is explicitly selected
with `--confirm-fixture-target` matching the exact selected HTTPS PDI origin. Setup is restricted
to hosts of the form `dev<digits>.service-now.com`, requires Basic-auth administrative access,
and runs its embedded, allowlisted Global background setup. It is not part of an ordinary
OAuth/restricted-account test run. `--plan` remains read-only and describes the conditional writes.
No helper script, service, root process or claim table is installed.

The setup creates only the five required custom `u_*` fields, marked test-owned reference data,
and a target-bound catalog (POSIX mode 0600; user-only folder ACLs required on Windows). Common env CI/caller/group settings plus those fixtures
are sufficient; no externally authored fixture JSON is needed for setup. The configured group
must already have an active unique-name assignee member, and the existing default-caller property
must be valid; setup does not alter that property or operational group membership.
CI/service/offering ingestion goes through IRE. It does not adopt
unrelated records, alter existing field types/references, create `em_alert.task`, or automatically
grant missing privileges. Compatible existing schema is reused; mismatches stop setup. Persisted
schema and test fixtures are retained and reported rather than silently removed.
Normal platform processing can also populate owned CI asset/model references and create linked
hardware assets after IRE ingestion. Follow-on records are retained and inventoried; the tester
does not promise fixture versions remain immutable outside its bounded setup interval.

Use `--prepare-fixtures-only` with setup to provision/read back without submitting Events;
`--fixture-output` chooses the private generated catalog path. Marked fixtures are reused on
reruns after exact ownership/drift checks. Preparation success is not a full test PASS.

```bash
python3 tests/test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --prepare-fixtures-only --fixture-output dti-reference-fixtures.json --report-file dti-setup-report.json
python3 tests/test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --allow-default-ci-property --fixture-output dti-reference-fixtures.json --fixture-recovery-file dti-default-ci-recovery.json --report-file dti-report.json
python3 tests/test_ci_identifier_precedence.py --restore-fixture-default-ci dti-default-ci-recovery.json --confirm-fixture-target https://dev123456.service-now.com --report-file dti-recovery-report.json
```

Replace the example origin with the exact selected DEV PDI. Recovery is a separate connection-only
mode; do not combine it with provisioning flags. Use a fresh recovery-journal path per lease.
Prefer an existing ignored private directory such as `.local-evidence/` for every generated
catalog, journal and machine report; arbitrary filenames are not automatically ignored.
An existing valid default CI is reused without property writes. If none exists, the default-CI
family additionally requires `--allow-default-ci-property`. Only during its three non-DTI
controls may setup temporarily set `x_usbna_usb_event.default_cmdb_ci_sys_id`. A journal
(POSIX mode 0600; private Windows folder required) selected by `--fixture-recovery-file` preserves the original value or absence;
guarded `finally` restoration must be read back in the database and property cache, and interrupted
runs require recovery before continuing. A concurrent external
change is not overwritten; restoration failure makes the result nonzero. This shared application
property can affect unrelated unhinted events while set, so run this phase only in the approved
DEV maintenance window. A prepared catalog alone cannot prove the missing-property positive route
under a normal restricted-account run. Production runs use preexisting approved fixtures, never this setup mode.

The provisioned suite's frozen hash, final flags, setup effects/restoration evidence and actual
full result are recorded separately in
[the new validation report](docs/validation-2026-10-29-provisioned-comprehensive.md); currently PENDING.

### Comprehensive-profile coverage

`--list-tests` is the authoritative feature list. The declared families include:

- Fast DTI response/version/CI/correlation checks; exact seven required Incident fields and
  assignment; Event processing completion; actual later Alert-to-Incident BR linkage; sequential reuse.
- All five wrappers, additional information object/string forms, outer/envelope precedence,
  `records`/`events`/bare-array and mixed batches, aliases/defaults/time/severity/resolution,
  retained custom context, malformed-payload zero-side-effect probes, and long keys.
- Fixture-driven caller/assignee/fallback, canonical/class-label/name/identifier/node/resource CI,
  support-tier/group precedence, service inference, parent-filtered offerings, CAR ID,
  customer Incident fields, and Salesforce PERU mappings.
- Incident/Alert journal occurrence counts, new follow-up notes and no-note updates,
  debug companion Event/attachment downloads, terminal states 6/7/8, and closed/foreign ownership guards.
- Three concurrent first events, always exercised and explicitly reported with the accepted
  duplicate race limitation. A complete result is not a guarantee against all interleavings.

Normal payloads omit legacy wait keys. The API must promptly return the intended Incident within
the configured POST budget (default 10 seconds). Independent readback then requires processed Events,
the correct Alert link and fields, and a continuous stable window. The supplied env template uses
the vetted 30-second stable window, 240-second observation deadline, and 10-second POST budget.
The raw CLI's 120-second timeout fallback is retained for compatibility, not certified here for
the full serial-read manifest. Actual counts and duration come from the report; no old focused-suite
event count or minimum duration applies to the new matrix.

### Comprehensive-profile access, writes, and results

The full identity needs connector POST; Event, Incident and Alert reads including states and
references; `sys_journal_field` reads; and attachment metadata/file reads. Lifecycle/ownership
checks PATCH only Incidents/Alerts created and tagged by this run, using allowlisted fields.
In ordinary test mode, all records are retained and the tester never deletes records, invokes
Scripts - Background, changes CMDB/schema/security configuration, or grants missing permissions.
The explicit DEV setup mode has the narrowly documented schema/reference-data and temporary-property
exceptions above; it still does not grant privileges or modify unrelated records.
A live run creates dozens of retained Events/Alerts/Incidents and runs normal platform Business
Rules and notifications; native workflow/mail is not suppressed. Review the test caller, group,
target, and production identity first. No tester email notifier is configured, but native mail
can still occur. Actual counts belong in the report, not an advance promise.
Advanced fixture checks also read the required CMDB/group/service/offering records and the
named default-CI property; the ambiguity control also reads exact-name users. Missing fixture
or field access blocks the corresponding coverage. Closed historical Alerts may remain on their
recorded terminal Incident, but a current non-Closed Alert must link to the replacement.
The foreign-task guard needs a marked non-Incident test Task with a short
description starting `[TEST] USBEM`, its `foreign_task_sys_id`, Task read access, and
the actual Alert Task-reference field's read/write access. On DEV that supported internal field
is `em_alert.incident`, a reference to `task`; `em_alert.task` is absent and must not be added.
Ordinary mode never creates/writes the Task. Explicit setup can create the marked fixture;
the actual guard only updates its owned Alert and requires the Task baseline to stay unchanged.
No arbitrary real work task is accepted as this fixture.

Any failed assertion fails the run. Missing/hidden fields, absent fixtures, unperformed checks,
or denied required lifecycle updates block complete sign-off. Exit codes are `0` complete
(including `complete_with_known_limitations`), `2` functional failure, `3` configuration/access/
transport error, and `4` INCOMPLETE. A report with the accepted race stays explicitly
`complete_with_known_limitations`; it is not an unqualified concurrency PASS.
The prior suite `1.0.0` exact-file comprehensive CLI completed in **1749.514 seconds**, with **75 pass / 1 fail /
9 skip / 1 known limitation**, zero errors and 93 cases. Its raw `fail`/exit 2 is retained:
the failure was our incorrect default-category fixture, separately corrected and retested in
two passing supplemental cases. Nine unavailable fixture/schema families still block complete
coverage. Three concurrent submissions returned one distinct Incident in this run; that does
not disprove the accepted race. See [the preserved prior report](docs/validation-2026-10-29-python-comprehensive.md).
The new suite `1.1.0` provisioned-fixture full result is PENDING and must not be inferred from it.
The earlier
[714-second DEV runtime retest](docs/validation-2026-10-29.2.md) and its 204 local tests remain
historical runtime evidence, not proof that this expanded one-file matrix passed.

Run one selected target at a time through DEV, IT, UAT, and PROD with its own fixtures and
approved identity. DEV admin success does not certify a production OAuth identity or local rules.
Legacy waiting, the locked standalone transform, ATF installers, and the optional inbound-email
Flow Action are outside this default current-listener API-and-BR contract; do not claim them
unless separately exercised. The older `tests/usbem_verify.py` remains a historical helper,
not an additional script required for this comprehensive laptop test.

## Known gaps

- **The scope needs its cross-scope privileges.** `x_usbna_usb_event` runs with
  `runtime_access_tracking = enforcing`, so it needs `incident` read+create+**write**, `sys_user`
  read for exact full-name caller/assignee resolution, `cmdb_rel_ci` and `svc_ci_assoc` read, and
  the requested `GlideRecord.setValue` / `GlideRecord.update` execute privileges. Without the incident
  write, annotating an incident that already exists (the
  duplicate work note) and writing `u_generating_alert` after creation are skipped and reported
  rather than done. Without `cmdb_rel_ci` read, any event resolving to a real CI throws
  `ScopeAccessNotGrantedException` before the support-group logic runs. Both are granted on
  dev382837 as of 2026-09-28. The complete clean-install set was validated on dev392825 on
  2026-10-29; the rows usually already exist on `sys_scope_privilege` with status `requested`, so
  this is a status change, not a new record.
- **Debug attachments require a separate scriptable privilege.** If optional `usbem_debug`
  attachments are enabled, the target must explicitly approve `GlideSysAttachment.write / execute`
  for `x_usbna_usb_event`. DEV approval of its existing requested row is target-specific; do not
  export that row or replace it with broad attachment/table grants.
- **Identifier access does not prove resource access.** The identifier path queries `cmdb_ci`
  with `INSTANCEOF`; resource lookup can directly query the requested child class. Review that
  target's child-table scoped read privilege separately. The current DEV comprehensive trial
  exposed a `cmdb_ci_server / read` request; the owner approved that exact DEV request and its
  `allowed` status was read back. No other grants changed; do not treat it as portable approval.
- **No duplicate protection on the fast path.** Simultaneous events for one key can each open an
  incident. The extended 2026-10-29 DEV test reproduced two incidents for three simultaneous
  first events. The comprehensive laptop suite always exercises this case and explicitly reports
  the owner-accepted race as a known limitation, not an unqualified concurrency PASS.

Long message keys are stored and looked up as a length-bounded prefix plus a stable short hash
of the full key; keys that fit are unchanged. This avoids the former raw-key/truncated-column
mismatch and distinguishes the tested shared-prefix keys. It is not a collision-proof identity
scheme and does not remove the accepted concurrent-first-event race.

## Files in this bundle

Runtime:

- `src/USBEM_Core.js`, `src/USBEM_Lookups.js`, `src/USBEM_Debug.js`, `src/USBEM_DTI.js`
- `servicenow/USBEM_genericJsonV2.listener.js` — the push connector listener
- `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` — the `em_alert` reconcile rule
- `servicenow/install_ci_support_tier_fields.background.js` — the two CI support tier fields
- `servicenow/USBEM_JabberwockyInboundEmail.flow_action.js` — the optional inbound email bridge
- `standalone/genericMappedJson_transform.js` — the locked standalone transform

Tooling:

- `scripts/deploy_usbem.py` — push the repo to an instance and read back its versions
- `scripts/deploy_dti_kb.py` — publish/update the DTI API and test guide; requires an explicit
  `--expected-instance https://<target>.service-now.com` matching both configured connections
- `tests/test_ci_identifier_precedence.py` — canonical comprehensive one-file laptop API-and-BR tester
- `tests/ci_identifier_test.env.example` — non-secret configuration template for that tester
- `tests/usbem_verify.py` — historical verifier/helper, not required by the comprehensive tester
- `requirements.txt` — nothing required; `requests`/`certifi` only if TLS needs them

Docs:

- `docs/install_from_scratch.md`, `docs/install_and_behavior.md`, `docs/dti_transfer_package.md`,
  `docs/atf_testing.md`, `docs/production-transfer-inventory.md`
- `kb/generic_json_v2_dti_api_and_tests.md` — DTI API, alert reconcile BR, and laptop test guide
- `atf/install_usbem_atf.js`
- `examples/` — sample payloads for each supported shape
