# Install and Behavior Notes

This doc primarily describes the locked standalone `genericMappedJson` transform path.

The repo now also includes the live modular `genericJsonV2` PDI layout:
- `src/USBEM_Core.js`
- `src/USBEM_Lookups.js`
- `src/USBEM_Debug.js`
- `src/USBEM_DTI.js`
- `src/USBEM_genericJsonV2.js`

For environment testing, the repo also includes:
- `src/USBEM_genericJsonV2_Full.js`
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
2. create or reuse the incident immediately
3. return the incident in the API response
4. complete alert attachment asynchronously after the response returns

The supported fast-path deployment includes the async `em_alert` reconcile rule in
[servicenow/USBEM_FastDtiAlertReconcile.business_rule.js](../servicenow/USBEM_FastDtiAlertReconcile.business_rule.js).
That rule links or relinks the alert to the preferred USBEM DTI incident as soon as Event Management creates the alert.

If a later duplicate incident appears with the same `message_key` / `correlation_id`, the async linker prefers the original fast incident when it can safely prove they are the same duplicate chain.

### `direct_to_incident=true` with `dti_wait_for_incident=true`

Flow:
1. insert event
2. poll the event until it leaves `Ready` and/or an alert is attached
3. if alert already has an incident, return it
4. otherwise create an incident and return it

If the event dedupes into an existing alert, this path returns the existing alert / incident instead of creating a duplicate.

## Wait timeout

Use `usbem_wait_seconds` to control the synchronous polling window.

If omitted, the script uses its internal default.

## Response identifiers

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

### DTI did not create an incident

Check:
- `direct_to_incident=true`
- alert generation timing
- whether the alert already had an incident
- whether severity `0` / `5` suppressed auto-creation under the default map
- whether no-wait processing returned `dti_mode=fast_async`
- whether the async business rule `USBEM Fast DTI Alert Reconcile` is active on `em_alert`
- whether Script Actions listening for `x_usbna_usb_event.fast_dti_event_name` are configured for the same event name
- whether any scoped Script Actions instantiate `x_usbna_usb_event.USBEM_Core` / `x_usbna_usb_event.USBEM_DTI` instead of bare global class names
- if the fallback event path is in use, whether `x_usbna_usb_event.link_alert_later` exists in **Event Registry** with table `incident`
