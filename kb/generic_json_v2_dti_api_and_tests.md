# Generic JSON V2 Direct To Incident API, Business Rule, and Python Testing

Article version: 1.2.0. Connector runtime release: 2026.10.29.1.

## Purpose and scope

Deploy the existing Generic JSON V2 DTI API and alert-reconciliation Business Rule, then run a standalone Python regression test from a work laptop. This package does not install a Linux service, scheduler, root process, or monitoring-email notifier. The earlier service requirement has been withdrawn.

Download the attached `test_ci_identifier_precedence.py` and `ci_identifier_test.env.example` together. The attached `validation-2026-10-29.md` contains the extended DEV evidence and limitations. GitHub source is in the private repository `rkasowan/generic_json_v2`.

## API and Business Rule contract

Submit JSON to the existing Event Management connector endpoint:

```text
POST https://<instance>.service-now.com/api/sn_em_connector/em/inbound_event?source=genericJsonV2
Content-Type: application/json
User-Agent: genericendpoint
```

The normal DTI path creates or reuses an open Incident, stamps its message-key correlation breadcrumb in `incident.correlation_id`, and promptly returns the Incident sys_id. Event Management subsequently processes the event and creates or updates its alert. `USBEM Fast DTI Alert Reconcile` then finds the Incident through that breadcrumb and links the alert to it. This separates the prompt API response from later alert processing.

The BR is active on `em_alert`, after insert/update, order 150, not async. It is invoked when an alert arrives or changes; it does not hold the API request open waiting for an alert. If an alert already exists, the API can link it during the request. Use the source and condition in `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` and `scripts/deploy_usbem.py`, not a hand-recreated rule.

New integrations and this test omit all wait-for-incident keys. The wait key is retained only for compatibility with existing legacy clients. The new design does not add a claim table.

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

The five standard fast-DTI cases cover name-only and identifier-only controls, explicit CI sys_id precedence, and camelCase and snake_case identifier inputs that conflict with a different existing CI name. Both conflict cases replay sequential duplicates and require reuse of the same Incident.

Every response must report all five API components at the configured release, one valid event sys_id, and a valid Incident sys_id within the prompt POST budget (10 seconds by default). The script then separately observes exact Event and Incident records, the correlation breadcrumb, expected CI, all seven required Incident fields, and the configured assignment group.

Each of seven phases must remain correct for 30 seconds within its own 120-second deadline. A complete passing standard run takes at least 3.5 minutes plus request time. Increase observation settings for a slower target if required; a brief HTTP 200 is not a pass. The default run retains seven tagged events and expects five Incidents. It does not update or delete them.

Exit codes are 0 for pass, 2 for functional failure, and 3 for configuration, access, or transport error. An incomplete check cannot return PASS. Preserve the JSON report and tagged records for troubleshooting, without including credentials.

## Access and BR validation boundary

The focused script needs connector POST plus `em_event` and `incident` read access. Incident field access must include `sys_id`, `number`, `cmdb_ci`, `correlation_id`, all seven required fields, and `assignment_group` when configured. Event field access must include `sys_id` and `message_key`. A 401/403 or omitted required field fails the test.

This deliberately limited script does not query `em_alert`, so its PASS is not proof of the later BR link. Actual DEV testing separately observed the arriving alert linked to the same returned Incident, including a case where the alert was initially absent and later linked correctly. For a repeatable target-instance BR check, the repository's broader `tests/usbem_verify.py --only fast --keep` verifies alert linkage and Incident lifecycle using the configured Incident read/write and Alert access. Review its fixture and state-change requirements before running it in a production target.

## Accepted limitation and evidence

Simultaneous first events for the same message key can create more than one Incident. Extended actual HTTP testing on dev392825 took 263.786 seconds and reproduced two Incidents for three concurrent first requests. Sequential duplicates reused one Incident. The owner accepted this residual race and explicitly declined a claim table.

The default suite does not assert concurrent safety. Use `--include-concurrency` for an optional three-request stress case; divergent returned IDs or multiple stored Incidents are a failure. A passing stress run still does not prove every possible interleaving. The test does not prove every production-specific rule, ACL, or Incident lifecycle transition.

The attached validation report distinguishes the exploratory legacy compatibility cases from the later fast-only required-field and BR-link checks. It records the installed-source readback, observations, timing, and retained DEV evidence. No production instance was deployed or exercised by that DEV validation.

## Deployment and rollback

The portable runtime consists of the four `src/USBEM_*.js` Script Includes, `servicenow/USBEM_genericJsonV2.listener.js`, and `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`. Use `scripts/deploy_usbem.py`, `docs/install_from_scratch.md`, `docs/dti_transfer_package.md`, and `docs/production-transfer-inventory.md` for scope, prerequisites, privileges, configuration, and transfer details. The four includes run in `x_usbna_usb_event`; the listener and BR remain Global.

After an approved transfer, compare installed source with `python3 scripts/deploy_usbem.py --dry-run`, verify the endpoint's component versions, then run the laptop test with that target's fixtures and identity. Do not copy PDI sys_ids, credentials, junk event rules, or the retired async linker into production.

Rollback the runtime using the previous approved six source records and their configuration. Keep test records as evidence until normal Incident/Event retention or an approved, exact-record cleanup is performed. No Linux-service uninstall step is part of this deliverable.
