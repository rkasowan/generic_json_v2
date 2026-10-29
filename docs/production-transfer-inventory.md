# Production Transfer Inventory

## DTI runtime

Release `2026.10.29.1` uses the Event Management Instance push connector, not a separate
Scripted REST API. Its normal DTI path creates or reuses an incident, stores the message-key
breadcrumb in `incident.correlation_id`, and returns promptly. The alert reconcile Business Rule
links the later alert to that incident. Do not add a wait key to new callers; it is legacy
compatibility only.

| Artifact | Target record/configuration |
|---|---|
| `src/USBEM_Core.js` | scoped Script Include `USBEM_Core` |
| `src/USBEM_Lookups.js` | scoped Script Include `USBEM_Lookups` |
| `src/USBEM_Debug.js` | scoped Script Include `USBEM_Debug` |
| `src/USBEM_DTI.js` | scoped Script Include `USBEM_DTI` |
| `servicenow/USBEM_genericJsonV2.listener.js` | active Global `sn_em_connector_listener`, source `genericJsonV2`, Instance type |
| `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` | active Global `em_alert` after Business Rule, insert/update, order 150; not async |

The Script Includes belong to `x_usbna_usb_event`; the listener and BR remain Global.
`scripts/deploy_usbem.py` updates these six existing records and reads back their versions.
Use [the clean-install guide](install_from_scratch.md) for prerequisites and initial configuration,
and [the manual transfer package](dti_transfer_package.md) for record configuration and exclusions.
Copy the BR condition as well as its script. Do not restore the retired queued-event/Script Action linker.

## ServiceNow dependencies

- Active Event Management with working inbound event processing and alert creation.
- Authorized connector endpoint: `/api/sn_em_connector/em/inbound_event?source=genericJsonV2`.
- Cross-scope table and scriptable privileges from the clean-install guide, including Incident
  read/create/write and the reads needed for CI, caller, and assignment-group resolution.
- Per-instance `x_usbna_usb_event.default_caller_sys_id` pointing to the intended valid caller.
- Valid local category/subcategory stored values and impact/urgency values. Validate caller,
  category, subcategory, urgency, impact, short description, and description on resulting incidents.
- Local CI fixtures and group references. Explicit CI sys_id takes precedence, then
  `ci_type` + `ci_identifier`, then a textual `cmdb_ci` fallback. An explicit `assignment_group`
  payload value can select the intended DTI assignment group; use target-specific references.
- CI support tier fields only where that existing assignment feature is required; create them
  using `servicenow/install_ci_support_tier_fields.background.js` rather than exporting inherited rows.

## Standalone Python test and Knowledge

- `tests/test_ci_identifier_precedence.py`: on-demand Python 3.9+ regression test; no packages,
  Linux service, root access, scheduler, or monitoring email configuration required.
- `tests/ci_identifier_test.env.example`: non-secret template for target URL, Basic or OAuth
  credentials, CI fixtures, required Incident fields, and optional assignment-group expectation.
  Keep filled env files private; base64 is encoding, not credential protection.
- `tests/test_ci_identifier_runner.py` and `tests/test_ci_lookup_precedence.js`: local behavior tests.
- `kb/generic_json_v2_dti_api_and_tests.md`: Knowledge source for API, BR, and laptop testing.
- `scripts/deploy_dti_kb.py`: update the existing article, preserving its KB identity.
- `docs/validation-2026-10-29.md`: DEV runtime/readback evidence and known limitations.

The focused laptop identity needs connector access plus `em_event` and `incident` read. The five
standard cases retain seven tagged events and expect five incidents, including sequential replay
checks. Each observation must remain correct for 30 seconds; a passing standard run takes at
least 3.5 minutes plus request time. It does not query alerts, so it does not directly prove the BR
link; that was verified separately in DEV. Production rules and permissions must be validated
in each target rather than inferred from DEV.

The owner accepted the known simultaneous-first-event race and declined a claim table. No claim
table is part of this package. Optional `--include-concurrency` stress testing fails if concurrent
requests create different incidents; the normal suite does not claim concurrency safety.

Instance URLs, credentials, sys_ids, users, roles, and Knowledge numbers are environment-specific and are not portable artifacts.
