# Production Transfer Inventory

## DTI runtime

Release `2026.10.29.2` uses the Event Management Instance push connector, not a separate
Scripted REST API. Its normal DTI path creates or reuses an incident, stores the message-key
breadcrumb in `incident.correlation_id`, and returns promptly. The alert reconcile Business Rule
links the later alert to that incident. Do not add a wait key to new callers; it is legacy
compatibility only.

Release gate: **corrected-path DEV retest PASS** on dev392825. The
[release retest](validation-2026-10-29.2.md) records 714.405 seconds, 50 positive scenarios,
ten invalid-payload probes, and 204 local tests. This does not certify production identities,
instance-specific rules, or simultaneous-first-event safety.

| Artifact | Target record/configuration |
|---|---|
| `src/USBEM_Core.js` | scoped Script Include `USBEM_Core` |
| `src/USBEM_Lookups.js` | scoped Script Include `USBEM_Lookups` |
| `src/USBEM_Debug.js` | scoped Script Include `USBEM_Debug` |
| `src/USBEM_DTI.js` | scoped Script Include `USBEM_DTI` |
| `servicenow/USBEM_genericJsonV2.listener.js` | active Global `sn_em_connector_listener`, source `genericJsonV2`, Instance type |
| `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` | active Global `em_alert` after Business Rule, Advanced=true, insert/update, order 150; not async |

The Script Includes belong to `x_usbna_usb_event`; the listener and BR remain Global.
`scripts/deploy_usbem.py` updates the known runtime records or creates a missing BR, verifies
stored source/configuration after each write, and reports endpoint versions.
Use [the clean-install guide](install_from_scratch.md) for prerequisites and initial configuration,
and [the manual transfer package](dti_transfer_package.md) for record configuration and exclusions.
Copy the exact `BR_CONDITION` from the deployer as well as the BR script. Pending work notes
can run with an open linked Incident; DTI-only metadata retains the nil/terminal gate. Do not
restore the retired queued-event/Script Action linker.

## ServiceNow dependencies

- Active Event Management with working inbound event processing and alert creation.
- Authorized connector endpoint: `/api/sn_em_connector/em/inbound_event?source=genericJsonV2`.
- Cross-scope table and scriptable privileges from the clean-install guide, including Incident
  read/create/write and the reads needed for CI, caller, and assignment-group resolution.
- Optional debug attachments require the exact scriptable privilege
  `GlideSysAttachment.write / execute` for `x_usbna_usb_event`, reviewed in each target. DEV's
  existing requested row was approved for testing; do not export that row or broad grants.
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
- `tests/test_ci_identifier_runner.py`, `tests/test_ci_lookup_precedence.js`,
  `tests/test_wrapper_passthrough.js`, `tests/test_listener_shape_contract.js`, and
  `tests/test_deploy_usbem.py`: focused local behavior and installer tests.
- `kb/generic_json_v2_dti_api_and_tests.md`: Knowledge source for API, BR, and laptop testing.
- `scripts/deploy_dti_kb.py`: publish/update in the implementation's explicitly selected target,
  preserving that target's existing KB identity. Pass `--expected-instance https://<target>.service-now.com`;
  both configured connections must match before any network call. It enables reader-visible
  attachments and verifies that flag after publication. Copy/verify attachment bytes separately.
- `docs/validation-2026-10-29.md`: DEV runtime/readback evidence and known limitations.
- `docs/validation-2026-10-29-comprehensive.md`: prior comprehensive run and defects; preserve
  alongside the new release's retest evidence rather than rewriting its historical results.
- `docs/validation-2026-10-29.2.md`: corrected-path DEV release retest, source/configuration
  hashes, retained evidence, fixes, observation windows, and acceptance limits.

The focused laptop identity needs connector access plus `em_event` and `incident` read. The ten
standard cases retain twelve tagged Events and expect ten Incidents, including sequential replay
checks and all five single-record wrappers (`event`, `payload`, `data`, `record`, `alert`). Each
observation must remain correct for 30 seconds; twelve phases require at least six minutes plus
request time for a passing standard run. It does not query alerts, so it does not directly prove the BR
link; that was verified separately in DEV. Production rules and permissions must be validated
in each target rather than inferred from DEV.

The owner accepted the known simultaneous-first-event race and declined a claim table. No claim
table is part of this package. Optional `--include-concurrency` stress testing fails if concurrent
requests create different incidents; the normal suite does not claim concurrency safety.

Instance URLs, credentials, sys_ids, users, roles, and Knowledge numbers are environment-specific and are not portable artifacts.

Current matching DEV article: KB0010015 on dev392825, sys_id
`7433ede097d457105fb3ba6de053af9b`. Article1.3.0 is active/latest/published with all five
attachments visible; all five downloads match repository bytes. The earlier dev382837
KB0010025 is a separate historical copy and is not the documentation target for dev392825 work.
