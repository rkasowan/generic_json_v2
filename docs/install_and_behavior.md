# Install and Behavior Notes

This doc primarily describes the locked standalone `genericMappedJson` transform path.

The repo now also includes the live modular `genericJsonV2` PDI layout:
- `src/USBEM_Core.js`
- `src/USBEM_Lookups.js`
- `src/USBEM_Debug.js`
- `src/USBEM_DTI.js`
- `servicenow/USBEM_genericJsonV2.listener.js`
- `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`

Install it with `scripts/deploy_usbem.py` and verify it with `tests/verify_usbem_connector.py`;
[install_from_scratch.md](install_from_scratch.md) is the full walkthrough.

For environment testing, the repo also includes:
- `atf/install_usbem_atf.js`
- `docs/atf_testing.md`

The locked standalone transform source now lives at:
- `standalone/genericMappedJson_transform.js`

## Endpoint

Create an **Instance** push connector with URL parameter value:

`genericMappedJson`

Resulting endpoint:

`https://<INSTANCE>/api/sn_em_connector/em/inbound_event?source=genericMappedJson`

## Payload styles

This connector accepts:
- a single object
- an array of objects
- `{ "records": [...] }`
- `{ "events": [...] }`

It is intentionally friendly to:
- flat JSON
- bulk payloads
- legacy `additional_info` JSON strings
- nested `ci_identifier` objects

## `additional_info` behavior

The transform accepts:
- no `additional_info`
- `additional_info` as a JSON object
- `additional_info` as an escaped JSON string

Fields that map cleanly into standard event fields are promoted out of `additional_info`.

Everything else stays in the final `em_event.additional_info` JSON string.

When a CI is resolved, `cmdb_ci` is also preserved in `additional_info`.

## Message key behavior

If `message_key` is not provided, the transform assembles one from:

`source + node + type + resource + metric_name`

That keeps event/alert deduplication aligned with the normal Event API behavior.

## DTI incident field mapping

For synchronous incident creation:
- `dti_short_description` populates incident `short_description`
- event `description` populates incident `description`

The `genericJsonV2` path adds two things on top. Any field that exists on `incident` can be sent
under its real name (`category`, `caller_id`, `contact_type`, ...) and is written as-is, and the
connector first applies the defaults the retired **EM - Generic Endpoint Create Incident** subflow
used to apply — `u_netcool_ticket = true`, category `Software`, subcategory `Monitoring Alert`,
caller `Event Management`, the alert in `u_generating_alert`, and a work note reading
`Direct To Incident Via Event Management Generic JSON Endpoint` followed by
`Incident Created From <alert number>`. Payload values override every one of them. See the README
for the full table.

If `direct_to_incident=true` and `dti_short_description` is omitted, the transform auto-fills `dti_short_description` from event `description`. This enables a minimal DTI payload that stays close to the standard event payload.

If `dti_description` is present, it stays available in `additional_info` but is not used for incident creation.

## DTI impact / urgency behavior

`direct_to_incident` is the intent flag.

For any DTI request, the transform makes sure `additional_info` ends up with:
- `dti_impact`
- `dti_urgency`

Rules:
1. If the payload provides `dti_impact` / `dti_urgency`, those values are preserved.
2. If the payload does not provide them, the transform fills them from the static severity map.
3. If `direct_to_incident=true` and `dti_short_description` is not provided, the transform fills it from event `description`.
4. If the connector creates an incident inline, it uses the provided values when present.
5. If the connector creates an incident inline and no values were provided, it uses the severity map.
6. Default map never generates P1.

Default map:
- `1`, `2` -> `impact=2`, `urgency=2`
- `3` -> `impact=3`, `urgency=3`
- `4` -> `impact=4`, `urgency=4`
- `0`, `5` -> `impact=4`, `urgency=4`, and no auto-incident unless custom values are provided while waiting

## Wait behavior

In scoped apps this build avoids `gs.sleep` and uses record-state polling instead.


### `usbem_wait_for_alert=true`

Poll the inserted event and related alert state (scope-safe, no `gs.sleep`) and return alert identifiers.

### `direct_to_incident=true` without `dti_wait_for_incident=true`

Flow:
1. insert event
2. reuse the key's open incident, or open a new one if there is none or the last one is finished
3. return the incident in the API response
4. complete alert attachment asynchronously after the response returns

Nothing touches the alert during the request, and nothing is queued. The alert is attached by one
actor: the synchronous `after` business rule on `em_alert` in
[servicenow/USBEM_FastDtiAlertReconcile.business_rule.js](../servicenow/USBEM_FastDtiAlertReconcile.business_rule.js),
which runs the moment Event Management creates or updates the alert.

The write is a conditional claim — it only lands if the alert is still unlinked or still holds the
exact incident that was inspected — so a concurrent writer is never overwritten and the second
actor reports `already_linked`.

This branch returns before the alert exists and short-circuits the `usbem_wait_for_alert` handling, so a fast-path call returns no alert identifiers even when that flag is set.

### `direct_to_incident=true` with `dti_wait_for_incident=true`

Flow:
1. insert event
2. poll the event until it leaves `Ready` and/or an alert is attached
3. if the alert already has a reusable incident, return it
4. otherwise create an incident, link it to the alert during the request, and return it

If the event dedupes into an existing alert, this path returns the existing alert / incident instead of creating a duplicate.

If the alert still points at a finished incident, that link is replaced conditionally — only while the alert still holds that exact incident, and only when the incident is one of ours. A Closed alert is left on the incident of the cycle it closed with; Event Management gives the next event its own alert, or reopens the old one and disconnects the finished incident itself.

## Terminal incidents

A message key stops reusing its incident once that incident is Resolved, Closed or Canceled. The next event opens a new incident, later events reuse it while it stays open, and the alert is moved across.

- states come from `x_usbna_usb_event.dti_terminal_incident_states`, default `6,7,8`
- judged on `state`, not `active`, because a Resolved incident is still `active=true`
- a value that is not a comma-separated list of integers falls back to the default and logs a warning
- `0` is a usable kill switch: no state matches it, so the old reuse behaviour returns without a code change

`dti_incident_status` names what happened; the statuses are listed in the project README.

## Wait timeout

Use `usbem_wait_seconds` to control the synchronous polling window.

If omitted, the script uses its internal default.

## Response identifiers

Every response carries `version` (the `USBEM_Core` release, unchanged from earlier builds) and a
`versions` object naming the running version of the listener and of each Script Include. DTI
results also carry `dti_version`. That is the fastest way to tell what an instance is actually
running.

USBEM returns `event_sys_id` for events.

There is no `event_number` in the response because `em_event` does not have an out-of-box `number` field.

When waiting is enabled, the response can also include:
- `alert_sys_id`
- `alert_number`
- `incident_sys_id`
- `incident_number`

For bulk payloads, these live inside each `results[]` entry. For single-record payloads, the first result is also echoed to the top level for convenience.

## Debug mode

Set:

```json
"usbem_debug": true
```

Behavior:
- per-record `debug_steps` are included in the response
- a compact debug JSON line is written with `gs.info(...)`
- verbose lookup diagnostics are also written into `additional_info`

Typical extra debug keys:
- `assignment_group_input`, `assignment_group_candidate_count`, `assignment_group_selection_reason`, `assignment_group_candidates`
- `cmdb_ci_input`, `cmdb_ci_candidate_count`, `cmdb_ci_selection_reason`, `cmdb_ci_candidates`
- `cmdb_ci_business_app_*`, `cmdb_ci_service_*`, `cmdb_ci_service_offering_*`

## Lookup selection notes

For CI / service / offering / business-app lookups, the transform prefers:
1. exact/class-correct matches
2. higher CSDM / dependency-tree classes for duplicate CI names
3. operational records
4. production / installed records
5. active records

It still allows a non-operational or retired record to win if that is the only unique best match.

## Troubleshooting

### Assignment group did not resolve

Check:
- exact group name
- whether multiple similarly canonicalized names exist
- whether the group exists but is inactive

### CI did not resolve

Check:
- `ci_type` (table name like `cmdb_ci_linux_server` or human-readable label like `Linux Server`)
- `ci_identifier` key names
- whether duplicate CIs have the same effective score
- whether `cmdb_ci` was sent as a name instead of a sys_id

### DTI returned a finished incident

Check:
- whether `x_usbna_usb_event.dti_terminal_incident_states` is set to something unparseable, or to `0`
- whether the caller reached the Script Include at all: the deployed `USBEM genericJsonV2` listener inlines its own older copy of these classes, so REST callers keep the old behaviour until that build is regenerated

### No assignment group on the incident

The order is: `assignment_group` on the event, then `cmdb_ci.support_group`, then
`cmdb_ci.u_level_2_support_assignee_group`, then unassigned.

Check:
- `assignment_group` on the payload, and whether the name resolved
- `cmdb_ci.support_group` and `cmdb_ci.u_level_2_support_assignee_group` on the resolved CI
- whether a CI resolved at all; with no CI there is nothing to read a group from
- whether the scope can read `cmdb_rel_ci`. With `runtime_access_tracking = enforcing` and no privilege for that table, CI resolution throws `ScopeAccessNotGrantedException` before the group logic runs
- there is deliberately no default group, so an unresolved incident stays unassigned

### DTI did not create an incident

Check:
- `direct_to_incident=true`
- alert generation timing
- whether the alert already had an incident
- whether severity `0` / `5` suppressed auto-creation under the default map
- whether no-wait processing returned `dti_mode=fast_async`
- whether the business rule `USBEM Fast DTI Alert Reconcile` is active on `em_alert`, is `after`
  (not async), and its condition still matches the events you are sending
- what the endpoint reports in `versions`: a component that is not on the current release is
  running older logic than the repo says
- `syslog` for `USBEM fast DTI alert reconcile [v<version>] outcome`, which the rule logs whenever
  it links or relinks an alert
