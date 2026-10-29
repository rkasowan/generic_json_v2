# Generic JSON V2 Direct To Incident API, Business Rule, and Python Testing

Article version: 1.3.0. Connector runtime release: 2026.10.29.2.

## Current DEV validation status

The corrected paths in release `2026.10.29.2` passed authorized live retesting on dev392825: all five wrappers preserve required Incident fields and notes; outer-field precedence, wrapped additional information, and envelope defaults are respected; malformed record shapes fail before Event insertion; and a new follow-up Alert note is journaled once after an Incident is already linked. The installed six runtime records were read back against source, including Advanced=true and the corrected BR condition. The exact DEV `GlideSysAttachment.write / execute` privilege was approved and successful debug capture produced nine JSON artifacts; the tenth error-context artifact is conditional on an error.

The corrected live matrix ran for 714.405 seconds (11 minutes 54 seconds): 47 main cases plus three terminal lifecycles (50 positive scenarios), ten malformed-shape probes with no tested Event/Incident side effects, and 280 passing functional assertions. Sequential duplicates reused the intended Incident; actual terminal states 6, 7, and 8 produced a new Incident and then reused it, with the Alert linked to the replacement. Both 15-sample stability windows passed without field or link drift. All 204 persisted offline tests passed. See the attached `validation-2026-10-29.2.md` for final observations, timing, installed-source evidence, and acceptance limits. This is DEV evidence, not production or restricted production-identity certification; the accepted simultaneous-first-event race remains.

The attached historical `validation-2026-10-29-comprehensive.md` records the preceding release's failed checks and 744-second run. Those results are retained, not rewritten as passes; the new report documents the subsequent corrections and retest.

## Purpose and scope

Deploy the existing Generic JSON V2 DTI API and alert-reconciliation Business Rule, then run a standalone Python regression test from a work laptop. This package does not install a Linux service, scheduler, root process, or monitoring-email notifier. The earlier service requirement has been withdrawn.

Download the attached `test_ci_identifier_precedence.py` and `ci_identifier_test.env.example` together. The attached `validation-2026-10-29.2.md` is the corrected release's DEV evidence. The older `validation-2026-10-29.md` and `validation-2026-10-29-comprehensive.md` remain historical evidence and limitations. GitHub source is in the private repository `rkasowan/generic_json_v2`.

## API and Business Rule contract

Submit JSON to the existing Event Management connector endpoint:

```text
POST https://<instance>.service-now.com/api/sn_em_connector/em/inbound_event?source=genericJsonV2
Content-Type: application/json
User-Agent: genericendpoint
```

The normal DTI path creates or reuses an open Incident, stamps its message-key correlation breadcrumb in `incident.correlation_id`, and promptly returns the Incident sys_id. Event Management subsequently processes the event and creates or updates its alert. `USBEM Fast DTI Alert Reconcile` then finds the Incident through that breadcrumb and links the alert to it. This separates the prompt API response from later alert processing.

The BR is active on `em_alert`, Advanced=true, after insert/update, order 150, not async. Delete/query, abort action, and add message are false. It is invoked when an alert arrives or changes; it does not hold the API request open waiting for an alert. If an alert already exists, the API can link it during the request. Use the source and configuration in `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` and `scripts/deploy_usbem.py`, not a hand-recreated rule. Its exact Advanced condition is:

```javascript
((current.getValue('additional_info') || '').indexOf('work_notes') > -1 ||
 ((current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1 &&
  (current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)))
```

Pending `work_notes` / `alert_work_notes` metadata can run even with an open linked Incident. Consumed Alert-note metadata is removed after journaling so unrelated later updates do not repeat the note. DTI-only metadata retains the nil/terminal-Incident gate. DEV retesting verified a unique follow-up Alert note appeared once and two subsequent no-note updates did not repeat it.

New integrations and this test omit all wait-for-incident keys. The wait key is retained only for compatibility with existing legacy clients. The new design does not add a claim table.

Accepted JSON containers are an object, an array of record objects, or an object whose selected `records` / `events` container is an array of record objects. A present `records` or `events` value of another type is rejected. Every selected batch member is shape-checked before the first member is processed; scalars and null members cannot produce partial junk Events. Invalid shapes use the connector's explicit HTTP 500 error path. This is shape preflight, not an atomic transaction or a new minimum Event-field schema: later runtime failures can still occur after earlier valid records have been processed.

Single-record fields can be under `event`, `payload`, `data`, `record`, or `alert`. Recognized one-level wrappers preserve Incident fields and `additional_info` / `additionalInfo` values, including an escaped JSON string. Explicit outer values retain precedence over conflicting wrapped values; per-record wrapped inputs are not masked by flat envelope defaults. This is not arbitrary recursive flattening of custom nested objects.

Example payload; replace every fixture with a value valid in the target instance:

```json
{
  "source": "DTI API Regression",
  "event_class": "API Test",
  "node": "work-laptop-test",
  "resource": "dti-api",
  "metric_name": "dti-regression",
  "type": "DTI API Test",
  "message_key": "unique-test-run-key",
  "severity": "4",
  "description": "DTI API regression test",
  "direct_to_incident": true,
  "ci_type": "cmdb_ci_server",
  "ci_identifier": {"serial_number": "unique-existing-serial"},
  "caller_id": "<valid-caller-sys-id>",
  "category": "software",
  "subcategory": "os",
  "impact": "2",
  "urgency": "2",
  "short_description": "DTI API regression test",
  "assignment_group": "<valid-assignment-group-sys-id>"
}
```

## CI selection, required fields, and assignment

CI precedence is an explicit `cmdb_ci` sys_id first, then `ci_type` plus `ci_identifier`, then textual `cmdb_ci` name fallback. A conflicting display name must not bypass a valid class-scoped identifier. CamelCase `ciType` and `ciIdentifier` aliases are also supported.

The test verifies all seven required stored Incident fields: affected end user (`caller_id`), category, subcategory, urgency, impact, short description, and description. Configure a real caller and valid choice values in each target instance. The customer-oriented runtime defaults are not necessarily installed choices in a clean PDI. Set `x_usbna_usb_event.default_caller_sys_id` to a valid per-instance fallback caller; do not transport the DEV caller sys_id.

To customize assignment, set `USBEM_ASSIGNMENT_GROUP` in the test env. A sys_id is verified automatically. If sending a group name, also set `USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID` so readback proves the intended group. These are instance-specific values. The API payload uses `assignment_group`; no test-specific group is hardcoded in the runtime.

## Configure and run the standalone Python test

Use stock Python 3.9 or newer. No pip packages, root access, service installation, or background process is required.

```bash
cp ci_identifier_test.env.example ci_identifier_test.env
python3 test_ci_identifier_precedence.py --report-file ci-test-report.json
```

Before running, fill the env file with the target HTTPS instance origin, Basic or OAuth credentials, two distinct real CI fixtures, affected-end-user sys_id, valid category/subcategory inputs and expected stored values, impact, urgency, and optional assignment group. The identifier must uniquely select the expected CI; the different CI's name is the decoy. The name-only and identifier-only controls stop the suite early if the fixtures are invalid.

Basic credentials may use plain or base64 variables; base64 is reversible encoding, not hashing or encryption. OAuth client credentials and a PEM corporate CA bundle are supported. Keep filled env files private and out of Git. TLS verification is enabled, redirects are rejected, and a POST is attempted once rather than automatically retried.

Existing production OAuth profiles can be selected with `--env-file usbem_verify.env --profile itsmnowDEVworker` after adding the focused fixture keys from the attached template. Run one selected target at a time, starting with DEV and progressing through the approved SDLC environments after each passes. This is an explicit test invocation, not a scheduled multi-instance monitor.

## What a passing run proves

The ten standard fast-DTI cases cover name-only and identifier-only controls, explicit CI sys_id precedence, camelCase and snake_case identifier inputs that conflict with a different existing CI name, and each of the five supported wrappers (`event`, `payload`, `data`, `record`, `alert`). Both conflict cases replay sequential duplicates and require reuse of the same Incident.

Every response must report all five API components at the configured release, one valid event sys_id, and a valid Incident sys_id within the prompt POST budget (10 seconds by default). The script then separately observes exact Event and Incident records, the correlation breadcrumb, expected CI, all seven required Incident fields, and the configured assignment group.

Each of twelve phases must remain correct for 30 seconds within its own 120-second deadline. A complete passing standard run takes at least six minutes plus request time. Increase observation settings for a slower target if required; a brief HTTP 200 is not a pass. The default run retains twelve tagged Events and expects ten Incidents. It does not update or delete them. Optional `--include-concurrency` adds an eleventh case with three simultaneous first Events: fifteen retained Events, eleven expected Incidents, and at least 6.5 minutes plus request time if the run passes.

Exit codes are 0 for pass, 2 for functional failure, and 3 for configuration, access, or transport error. An incomplete check cannot return PASS. Preserve the JSON report and tagged records for troubleshooting, without including credentials.

## Access and BR validation boundary

The focused script needs connector POST plus `em_event` and `incident` read access. Incident field access must include `sys_id`, `number`, `cmdb_ci`, `correlation_id`, all seven required fields, and `assignment_group` when configured. Event field access must include `sys_id` and `message_key`. A 401/403 or omitted required field fails the test.

This deliberately limited standalone script does not query `em_alert`, so its PASS is not proof of the later BR link, Alert notes, debug attachments, or terminal Incident lifecycle. The broader authorized live DEV audit separately observed the arriving Alert linked to the same returned Incident, including a case where the Alert was initially absent and later linked correctly, and checked replacement/reuse after terminal states 6, 7, and 8. Those broader checks are not claimed as work performed by the laptop script. For a repeatable target-instance BR check, the repository's broader `tests/usbem_verify.py --only fast --keep` verifies Alert linkage and Incident lifecycle using the configured Incident read/write and Alert access. Review its fixture and state-change requirements before running it in a production target.

## Accepted limitation and evidence

Simultaneous first events for the same message key can create more than one Incident. Extended actual HTTP testing on dev392825 took 263.786 seconds and reproduced two Incidents for three concurrent first requests. Sequential duplicates reused one Incident. The owner accepted this residual race and explicitly declined a claim table.

The default suite does not assert concurrent safety. Use `--include-concurrency` for an optional three-request stress case; divergent returned IDs or multiple stored Incidents are a failure. A passing stress run still does not prove every possible interleaving. The test does not prove every production-specific rule, ACL, or Incident lifecycle transition.

The attached current validation report records installed-source readback, observations, timing, retained DEV evidence, and which checks required broader authorized access. Historical reports distinguish exploratory legacy compatibility cases from the later fast-only required-field and BR-link checks and record failures found before these corrections. No production instance or production OAuth/restricted identity was deployed or exercised by this DEV validation. Validate production-specific Incident rules, references, choices, privileges, and identities in each target; DEV success does not certify them.

## Deployment and rollback

The portable runtime consists of the four `src/USBEM_*.js` Script Includes, `servicenow/USBEM_genericJsonV2.listener.js`, and `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`. Use `scripts/deploy_usbem.py`, `docs/install_from_scratch.md`, `docs/dti_transfer_package.md`, and `docs/production-transfer-inventory.md` for scope, prerequisites, privileges, configuration, and transfer details. The four includes run in `x_usbna_usb_event`; the listener and BR remain Global. The installer verifies stored source and allowlisted configuration after both creates and updates, including Advanced=true; a write response alone is not install proof.

Optional debug attachments require the exact `GlideSysAttachment.write / execute` scriptable privilege for `x_usbna_usb_event`, reviewed in each target. Only DEV's existing requested privilege was approved for this retest; do not transport the privilege record or grant broad permissions. Successful debug capture has nine JSON artifacts (`01_raw_payload.json` through `09_dti_timeline.json`); `10_error_context.json` is produced only when error context exists. Missing privilege can cause debug capture to fail or be skipped; do not assume the Event always succeeds under a debug-capture failure.

After an approved transfer, compare installed source with `python3 scripts/deploy_usbem.py --dry-run`, verify the endpoint's component versions, then run the laptop test with that target's fixtures and identity. Do not copy PDI sys_ids, credentials, junk event rules, or the retired async linker into production.

Rollback the runtime using the previous approved six source records and their configuration. Keep test records as evidence until normal Incident/Event retention or an approved, exact-record cleanup is performed. No Linux-service uninstall step is part of this deliverable.
