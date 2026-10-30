# Generic JSON V2 Direct To Incident API, Business Rule, and Python Testing

Article version: 1.7.0. Connector runtime release: 2026.10.29.3. Python test suite version: 1.3.0.

The laptop test now runs with one command and no flags: `python test_ci_identifier_precedence.py`. Keep the updated script, your `production_test.env`, and your already-filled `dev-fixtures.json` together in one private folder. It automatically uses the restricted production-safe workflow, displays the single selected target, runs the available checks, prints a readable summary, and saves detailed JSON results beside the script. Missing optional advanced fixtures remain explicitly INCOMPLETE without blocking unrelated baseline checks; they never become PASS. All 85 manifest entries remain in the report. Do not replace your filled configuration with the example templates.

Suite 1.3.0 uses only the existing connector POST plus Event R, Alert RW and Incident RW, with no reference/admin table reads, fixture provisioning or administrator fallback. Runtime `2026.10.29.3` is unchanged; no security grant or API/BR change is part of this update. Updated-version offline validation passes 446 Python plus 234 JavaScript checks (680 total), including 30 new laptop-entry tests. Program SHA-256: `c39760011c871a659ae40e2c5cc03ca592f4b702d93439d1acd01739298748ab`.

Focused DEV invocation proof completed in 132.586 seconds: seven selected features/three CI cases produced five PASS, zero FAIL/errors and two deliberately unavailable optional-feature SKIPs, correctly returning INCOMPLETE/exit 4. The missing custom-field and CAR fixtures sent no Events for those features; unrelated checks continued. Four connector POSTs and zero PATCHes verified name-only/identifier-only controls, conflicting camelCase CI selection, duplicate reuse and final integrity. Independent three-GET/zero-write readback verified four Processed Events, three Incidents, three Alerts and 21 required-field checks, with expected CI, assignment, caller, seven fields, correlation and links unchanged. This exercised the actual no-argument path using private focused dispatch and an in-memory DEV connection; standalone sidecar parsing was tested offline. It is not all-85 live acceptance or actual restricted production-identity proof. See `validation-2026-10-29-one-command.md`. The suite 1.2.0 / article 1.6.0 results below are historical exact-file evidence, not verification of the updated bytes.

Article 1.7.0 is published, active, latest and reader-verified in matching dev392825, with exact normalized source-body readback and actual reader links for the canonical program, production env/catalog and usage guide. The current program and new focused evidence pass exact-byte authenticated API/reader download checks; anonymous requests do not return the files. Previous script/usage attachments are replaced with recovery copies retained; historical reports remain intact. This release contains reviewed sanitized source/summary only; filled configuration and full machine reports remain private. Runtime `2026.10.29.3` is unchanged, and no actual corporate production environment or restricted production identity is claimed tested.

The separate suite 1.1.0 administrative provisioned-fixture full retest remains incomplete, including the unapproved business-application read privilege and default-CI prerequisites. Article 1.5.0 was an unpublished draft, not a verified publication. Delivery of this separately scoped production test does not certify or require closing that broader administrative gate. The prior published article 1.4.0 and suite 1.0.0 evidence remain historical, including their raw failed/incomplete report and separate corrected-fixture supplemental result. Keep full machine JSON and filled fixtures private to this matching DEV KB or ignored local evidence; only reviewed sanitized source/summary may be published to public Git.

Historical suite 1.2.0 local validation passed 416 Python plus 234 JavaScript checks (650 total), including 102 production unit methods. The independent native-Alert model exercised all 85 actual production callbacks with 84 PASS and one accepted concurrency limitation: 102 modeled cases, 119 connector calls, 11 negative probes, 24 formatted-note reads, three debug companions and five owned PATCH operations. This is simulated transport/behavior coverage, not a full live production acceptance run. That prior program's SHA-256: `68db4a360ae112c223e327bc5a51f1f5bc2e77703353b42a96dc2d3bf4f5d280`.

The historical suite 1.2.0 exact-file focused DEV run completed 20 checks over 33 cases in 725.494 seconds: 19 PASS, one accepted concurrency limitation and zero failures/errors/skips. Maximum POST was 1.137 seconds and minimum case stability 34.813 seconds, with eight formatted-note observations and three debug companions. Three simultaneous first requests created three test Incidents, reproducing the accepted race. Independent GET-only readback passed with three queries/zero writes: 45 retained Events all Processed (42 primary + three debug), 15 Incidents, 25 Alerts and 98 required-field checks; expected stored fields/links remained unchanged. See `validation-2026-10-29-production-access.md` for the scoped evidence. This is not a full 85-feature live acceptance run and does not certify an actual restricted production identity or corporate endpoint.

The prior suite 1.2.0 program/configuration and evidence uploads were byte-verified through authenticated API and reader downloads; anonymous requests do not return their files. Article 1.6.0 was published and reader-verified on dev392825 with actual links for those downloads. Only the previous Python/common-env attachments were replaced at that milestone, with recovery copies retained; historical reports remain intact. Article 1.4.0 is historical and 1.5.0 was an unpublished draft. The historical sanitized Git milestone is `6e7c1a5`; it is separate from this suite 1.3.0 source/summary release.

## Historical `.2` DEV validation status

The corrected paths in release `2026.10.29.2` passed authorized live retesting on dev392825: all five wrappers preserve required Incident fields and notes; outer-field precedence, wrapped additional information, and envelope defaults are respected; malformed record shapes fail before Event insertion; and a new follow-up Alert note is journaled once after an Incident is already linked. The installed six runtime records were read back against source, including Advanced=true and the corrected BR condition. The exact DEV `GlideSysAttachment.write / execute` privilege was approved and successful debug capture produced nine JSON artifacts; the tenth error-context artifact is conditional on an error.

The corrected live matrix ran for 714.405 seconds (11 minutes 54 seconds): 47 main cases plus three terminal lifecycles (50 positive scenarios), ten malformed-shape probes with no tested Event/Incident side effects, and 280 passing functional assertions. Sequential duplicates reused the intended Incident; actual terminal states 6, 7, and 8 produced a new Incident and then reused it, with the Alert linked to the replacement. Both 15-sample stability windows passed without field or link drift. All 204 persisted offline tests passed. See the attached `validation-2026-10-29.2.md` for final observations, timing, installed-source evidence, and acceptance limits. This is DEV evidence, not production or restricted production-identity certification; the accepted simultaneous-first-event race remains.

The attached historical `validation-2026-10-29-comprehensive.md` records the preceding release's failed checks and 744-second run. Those results are retained, not rewritten as passes; the new report documents the subsequent corrections and retest.

## Purpose and scope

Deploy the existing Generic JSON V2 DTI API and alert-reconciliation Business Rule, then run one standalone Python tester from a work laptop without arguments. For production operators with Event R, Alert RWC and Incident RWC, that laptop workflow automatically follows the restricted actual Event, Alert and Incident path. The broader `comprehensive` developer CLI additionally verifies journal history, downloaded debug attachments and reference-source facts and needs its separately documented access; it is not the no-argument workflow. Explicit administrative DEV setup is isolated from production mode. This package does not install a Linux service, scheduler, root process, or monitoring-email notifier. The earlier service requirement has been withdrawn.

The program uses stock Python 3.9+, with no other project imports or required packages. The env and required reference-fixture catalog are configuration; supply the catalog as JSON or the env JSON-object setting. `ci_identifier_test.env.example` remains the broader comprehensive-profile template. The attached `validation-2026-10-29.2.md` is the corrected runtime release's historical DEV evidence, not a result from the expanded runner. The older `validation-2026-10-29.md` and `validation-2026-10-29-comprehensive.md` also remain historical evidence and limitations. GitHub source is in `rkasowan/generic_json_v2`, whose repository visibility is public. Documentation and attachments for this DEV implementation belong to KB0010015 on dev392825. Keep filled fixtures and full machine reports out of public Git: credential-free reports still contain instance and record metadata.

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

Single-record fields can be under `event`, `payload`, `data`, `record`, or `alert`. Recognized one-level wrappers preserve Incident fields and `additional_info` / `additionalInfo` values, including an escaped JSON string. Explicit root Event/SPECIAL aliases retain precedence over conflicting wrapped aliases: for example, root/envelope `dti_impact` wins over wrapped `dti_impact`. Separately, wrapped per-record real Incident passthrough fields such as `impact`, `urgency`, `category`, and `caller_id` overlay flat envelope Incident defaults. This is not arbitrary recursive flattening of custom nested objects, nor a reversal of Event/SPECIAL alias priority.

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

To customize assignment, set `USBEM_ASSIGNMENT_GROUP` in the test env. Complete test coverage requires a non-empty group input and its exact expected sys_id. A sys_id input supplies that expectation automatically. If sending a group name, set `USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID` so readback proves the intended group. These are instance-specific values. The API payload uses `assignment_group`; no test-specific group is hardcoded in the runtime.

## Run the production test: three steps

Use Python 3.9 or newer; no package installation is needed.

1. Keep the updated `test_ci_identifier_precedence.py`, `production_test.env`, and your already-filled `dev-fixtures.json` in the same private folder. Do not replace your filled files with the example attachments.
2. Open Terminal or PowerShell in that folder and run:

```bash
python test_ci_identifier_precedence.py
```

If your computer calls Python `python3` or `py -3`, use that command instead.

3. Read the final on-screen summary. The detailed `dti-results-....json` file is saved automatically beside the script. Allow many minutes for real processing and stable link checks.

No flags or options are needed. The script reads only `production_test.env` and `dev-fixtures.json` beside itself, not another working directory's configuration or inherited shell credentials. It uses a nonblank `USBEM_DEV_URL`, otherwise `SN_INSTANCE_URL`, from that file, displays the single selected target, and never advances automatically to another environment. Existing shared Basic username/per-profile passwords, OAuth and plain/base64 credential settings remain supported. Base64 is reversible encoding, not hashing or encryption.

Valid baseline CI, caller, required-field and assignment settings are required. Missing optional advanced fixture data no longer blocks unrelated baseline checks: the affected features remain INCOMPLETE, not PASS, and all 85 manifest entries are reported. The summary names the missing data. Malformed JSON, unsafe baseline configuration or failed baseline controls stop safely with an actionable explanation. The script does not discover restricted reference data, request more permissions or provision production fixtures. Set owner attestations only after the data owner verifies those facts.

Assignment uses the existing `USBEM_ASSIGNMENT_GROUP` and independently known expected group ID settings; no Python edit is needed. The run creates real retained test Incidents/Alerts and can trigger native notifications/email, outage rules and other Business Rules. Use approved CIs, caller, group and a testing window. Keep filled configuration and detailed results private; never put credentials in shell arguments or copy one environment's record IDs to another.

Generated outputs use atomic replacement and POSIX mode 0600 where supported. On Windows use a user-only NTFS folder for credentials, catalogs and reports: `mkstemp`/POSIX mode bits cannot configure private Windows ACLs. The same requirement applies to the DEV setup's catalogs and recovery journals; a documented 0600 mode is a POSIX control, not a cross-platform privacy guarantee.

### Production coverage and evidence boundary

The 85-feature production manifest tests fast no-wait DTI, all seven required Incident fields, CI identifier/type precedence and Event/Alert/Incident CI binding, wrappers/batches, invalid inputs, severity/clear/suppression, sequential duplicates and long keys, routing, Salesforce, default/custom fields and back-references, visible note delivery, terminal Incident replacement, foreign-Incident and closed-Alert guards, debug companion Events, and the accepted parallel-first-event race. It observes actual stored effects over bounded continuous stability windows, not only HTTP success. Missing fixtures, operations or readable fields prevent complete acceptance.

| What is observed | What these rights cannot independently certify |
| --- | --- |
| Exact stored reference IDs on owned Event/Alert/Incident | CMDB/user/group/service source facts, property values, canonical-name uniqueness or offering-parent relationships |
| Sentinel presence/absence in the exact owned record's formatted visible work notes, plus consumed pending-note metadata | Complete raw journal history, exact global occurrence counts or ACL-hidden entries |
| Debug companion Event metadata and processed state | Attachment filenames, complete attachment set or downloaded bytes |
| Actual Alert-to-Incident link and guard outcomes | Installed Business Rule source/configuration |
| Foreign link guard using two current-run Incidents | An unreadable non-Incident Task baseline; that guard is excluded |

The full-shaped catalog includes all 14 production advanced families. Supply independently known expected IDs and set `production_attestations` booleans only after the data owner verifies canonical CI/group names, primary/L2 support routing, CAR-ID mapping, CI/service inference, offering-parent filtering, existing default-CI policy and genuinely ambiguous user names. An attestation qualifies provenance; it is not an automated proof of the source fact, and stored results still must match expectations. Default-CI coverage needs explicit `default_ci_sys_id` and three positive/negative controls; the test never changes the property. The support CI's group must differ from the explicit baseline group to prove override precedence. Offering-parent coverage needs a valid positive service and a different valid negative-control service.

Confirm the catalog's default `severity_map` against any target overrides, literal stored default category/subcategory values, duplicate-note policy, valid closure choice and Alert Closed state. `terminal_extra_fields` may contain only a nonempty `u_cause` string where required. Replace the custom-field placeholder in both the payload and expected result with an existing approved Incident field. Existing readable `u_netcool_ticket` and `u_generating_alert` fields are required for those declared customer features; missing fields cannot become PASS.

Production `expected_incident` and `expected_event` values must be stored-value strings, including `"0"`, `"false"` and `""`; JSON numbers/booleans are not interchangeable with these strings. User `additional_info` expectations retain native JSON booleans, numbers, arrays and objects and are compared recursively with type distinctions. Invalid optional fixture families are reported incomplete rather than blocking unrelated tests; malformed JSON or unsafe baseline configuration stops before Event writes. Invalid raw stored-value response types cannot pass through truthy/falsy coercion.

OK is not Clear: native OK/severity 5 can create an Alert, while Clear/severity 0 does not create a fresh Alert and closes matching existing Alerts. See [ServiceNow: View alert information](https://www.servicenow.com/docs/r/it-operations-management/event-management/t_EMViewAlert.html). The connector's severity-5 DTI policy suppresses its automatic Incident, not the native Alert. Fresh Clear/Closing controls expect no Alert; the production callbacks distinguish these outcomes rather than assuming every non-DTI Event has no Alert.

Production mode permits only connector POST and direct reads of `em_event`, `em_alert`, `incident`, plus allowlisted PATCH to freshly verified current-run Incidents/Alerts. It rejects other table reads, reference dot-walks, direct Event writes, creates/deletes, background scripts, schema/security/property changes, administrative fixture setup and attachment downloads. There is no admin fallback. For notes, raw journal-input reads can be blank; after fresh raw ownership verification the tester requests only the exact owned record's `sys_id,work_notes` formatted view. A blank/missing formatted view makes even a negative-note check incomplete, not a false absence PASS. Sentinel observations in that visible view are not complete raw history/exact-count proof; debug Events are not attachment proof. Completion applies to this explicitly scoped production-observable manifest, not the broader administrative manifest. A passing DEV check is not certification of the actual production identity or local rules. Three parallel first events may still create multiple test Incidents under the accepted no-claim-table race.

## Comprehensive-profile configuration and DEV setup

Use stock Python 3.9 or newer. No pip packages, root access, service installation, or background process is required.

```bash
cp ci_identifier_test.env.example ci_identifier_test.env
python3 test_ci_identifier_precedence.py --access-profile comprehensive --list-tests
python3 test_ci_identifier_precedence.py --access-profile comprehensive --plan
python3 test_ci_identifier_precedence.py --access-profile comprehensive --fixture target-fixtures.json --report-file dti-report.json
```

This is advanced compatibility guidance, not the no-argument laptop workflow above. These commands explicitly use the broader `comprehensive` profile. `--list-tests` and `--plan` are read-only: inspect coverage and conditional setup writes before supplying credentials or writing records. Both plan and actual report include `test_suite_version` and the executing file's module-load `script_sha256`. Suite `1.3.0` is separate from runtime `2026.10.29.3`. Fill the env file with the target HTTPS origin, Basic or OAuth credentials, two distinct CI fixtures, caller, valid category/subcategory inputs and expected stored values, impact, urgency and assignment group/exact expected ID. The identifier must uniquely select the expected CI; the different CI's name is the decoy. Controls must pass before dependent claims are accepted. Explicit DEV setup can top up the catalog from configured references and marked fixtures; it does not replace actual stored-value proof.

The complete manifest also needs target-specific reference data for caller/assignee names and expected IDs, the configured default caller, support tiers, services/offerings, CAR ID, canonical CI/group names, node/resource resolution, and customer fields/ownership guards. Supply that catalog with `--fixture target-fixtures.json`, or as a JSON object in `USBEM_TEST_FIXTURES_JSON`. Top-level names are `caller_name`, `assignee_sys_id`, `assignee_name`, `group_name`, `default_caller_sys_id`, `ci_support_sys_id`, `ci_support_group_sys_id`, `service_sys_id`, `service_name`, `offering_sys_id`, `offering_name`, `default_category`, and `default_subcategory`. The last two are independently verified stored values for the runtime's Software / Monitoring Alert defaults, separate from the payload override choices in the env file. The assignee must be valid for the selected assignment group under local rules. Optional configuration includes `severity_map`, `terminal_close_code`, `alert_closed_state`, `correlation_length`, and `duplicate_work_note_enabled`. The last is a JSON boolean (default `true`) that must match the actual `x_usbna_usb_event.dti_duplicate_work_note` setting; the test does not modify that property.

If target-specific Incident resolution requires cause data, `terminal_extra_fields` may contain only a non-empty string `u_cause`, for example `{"u_cause":"Testing DTI"}`. That existing field must be readable; the tester includes it only on its owned terminal-state updates and verifies the stored result. Arbitrary extra Incident fields are not added to the PATCH allowlist. Do not create the field or transport a DEV-only choice merely to make a test pass.

Default fixtures must describe the independently verified stored connector-parity contract, not just a `sys_choice` label lookup. The DEV default is literally `Software`, while the active PDI choice label Software maps to `software`; `Monitoring Alert` is likewise a customer-parity literal rather than an installed PDI choice. This tests filled/stored fields, not valid choice taxonomy. Prefer explicitly supplied stored choice values in production. An assistant-selected lowercase expectation caused a comparison-run failure; that raw failure is preserved, and any corrected-fixture focused retest is separate evidence, not a rewritten full-suite pass.

The prior suite 1.0.0 corrected-fixture supplemental execution passed both defaults cases in 44.619 seconds using that same prior script, real Event/Incident/Alert readback, 30-second stable observation and final evidence verification. An earlier operator-only JSON serialization failure was rerun successfully with the complete supplemental JSON retained. This stored-value-only result does not alter either prior full run's original fixture or raw failed outcome. That prior exact-file full report remains `fail`/exit 2, with 75 pass / 1 fail / 9 skip / 1 known limitation. It is not evidence that the new provisioned suite has passed.

Advanced cases contain `payload`, `expected_incident`, and optional `remove_fields`, `expected_event`, `expected_additional_info`, `absent_additional_info`, `want_incident`, and `want_alert` values under `advanced_cases.<feature_name>`. A feature value can be one case object or an array of case objects. `payload` overrides the common test payload; `remove_fields` removes inherited inputs that would mask a lookup branch. For example, a node-only lookup must remove the common `cmdb_ci`, `ci_type`, and `ci_identifier` inputs. Expected values are stored API values, including an explicit empty string when a field must stay blank. User additional information preserves native JSON booleans, numbers, arrays, and objects; do not stringify those expectations. Connector-added routing references and DTI flags/values follow their operational string contract. `absent_additional_info` lists keys that must not remain. This partial catalog illustrates the format; it is not a complete fixture set:

```json
{
  "caller_name": "<exact test caller full name>",
  "assignee_sys_id": "<valid target assignee sys_id>",
  "assignee_name": "<exact assignee full name>",
  "group_name": "<exact configured assignment group name>",
  "default_caller_sys_id": "<configured target default caller sys_id>",
  "severity_map": {"1": ["2", "2"], "2": ["2", "2"], "3": ["3", "3"], "4": ["4", "4"]},
  "advanced_cases": {
    "node_fallback": {
      "payload": {"node": "<unique existing CI name>", "resource": ""},
      "remove_fields": ["cmdb_ci", "ci_type", "ci_identifier"],
      "expected_incident": {"cmdb_ci": "<expected CI sys_id>"},
      "expected_event": {"cmdb_ci": "<expected CI sys_id>"}
    }
  }
}
```

The advanced feature keys are `node_fallback`, `resource_resolution`, `additional_info_name_fallback`, `ci_class_label`, `canonical_ci_name`, `canonical_group_name`, `invalid_group_ci_fallback`, `car_id`, `l2_support_group`, `service_inference`, `offering_parent_filter`, `custom_incident_fields`, `default_dummy_policy`, `ambiguous_user_rejection`, and `foreign_task_guard`. `offering_parent_filter` requires an array containing both a positive and a negative parent control for the same offering against different services. `default_dummy_policy` requires three distinct controls: a real configured non-empty default CI used for unresolved hints; that default suppressed by an explicit unresolved CI; and no CI hints producing a blank CI. Without a valid configured default, ordinary mode leaves that family incomplete. Only the separately authorized DEV setup mode with `--allow-default-ci-property` may temporarily configure it for those three controls, with verified restoration. Canonical CI/group inputs must be genuine separator/token variants, not an exact name with letter case changed.

For `foreign_task_guard`, provide the separate top-level `foreign_task_sys_id`, plus optional `foreign_task_marker` (default `[TEST] USBEM`), or use the explicit DEV setup's marked fixture. Never select an actual work task. The runner reads that Task's baseline, links only its own test Alert to it, triggers the installed BR, and verifies the foreign link survives and the Task baseline is unchanged. On this DEV the supported internal Alert field is `incident`, which references `task`; no `em_alert.task` column exists or is needed. Ordinary mode never creates or writes the Task. Explicit setup may create the marked non-Incident Problem/base-Task fixture, but the actual guard does not write it. Missing suitable link-field access or a valid marked fixture makes the guard incomplete.

Use the script's plan and missing-fixture messages to finish the catalog. Ordinary mode reuses existing CIs, groups, references, and customer fields and does not create CMDB/schema/security fixtures. Absent schema or positive fixtures remain INCOMPLETE unless the separate explicit DEV provisioning phase successfully installs and verifies the authorized fixtures. A setup request or HTTP 200 alone does not establish coverage; the subsequent API/BR tests must verify actual stored effects.

Advanced Incident-field families require `want_incident: true` as a JSON boolean; disabling creation cannot turn an untested Incident field into a passing feature. The default/dummy-CI control family is the deliberate non-DTI exception. The ambiguous-assignee fixture must identify at least two existing exact-name users; an unknown or unique user is not an ambiguity test.

Basic credentials may use plain or base64 variables; base64 is reversible encoding, not hashing or encryption. OAuth client credentials and a PEM corporate CA bundle are supported. Keep filled env files private and out of Git. TLS verification is enabled, redirects are rejected, and a POST is attempted once rather than automatically retried.

Existing production OAuth profiles must select `--access-profile production --env-file usbem_verify.env --profile itsmnowDEVworker` with the production template's target fixture keys/catalog. The commands above without that flag retain the broader comprehensive access requirements. Run one target at a time through the approved SDLC after reviewing each report; this is not a scheduled monitor.

For a selected profile, `USBEM_<PROFILE>_URL` must be present and non-empty; otherwise configuration fails before any network call. It never silently falls back to a global PDI. An explicit `--instance` takes precedence. Blank profiles that were not selected are ignored, so configure DEV first and add IT/UAT/PROD later. A profile name that normalizes to an empty key is rejected. This is a target guard, not permission to run against every populated environment.

## Explicit administrative DEV fixture setup

Provisioning is not the default. Select `--provision-dev-fixtures` and supply `--confirm-fixture-target` with the exact selected HTTPS PDI origin. The target must be a `dev<digits>.service-now.com` host and use Basic-auth administrative access. The same Python file contains a narrow embedded Global background setup; no additional installer file or server service is required. Normal OAuth/restricted-account testing does not invoke this path. `--plan` remains read-only, including when describing setup's conditional writes. The implementation and exact-file live result for this new mode remain PENDING until recorded in the provisioned validation report.

Setup may add only five customer `u_*` fields with their required types: `cmdb_ci_business_app.u_car_id` (string, 100), `cmdb_ci.u_level_2_support_assignee_group` (reference to `sys_user_group`, 32), `incident.u_usb_em_test_value` (string, 255), `incident.u_netcool_ticket` (boolean), and `incident.u_generating_alert` (reference to `em_alert`, 32). Their exact `u_*` names remain in Global schema to match the existing runtime contract; runtime Script Includes stay in `x_usbna_usb_event`. Existing compatible schema is reused; an incompatible field is not relabeled, retyped or repurposed. Persistent schema changes are explicitly reported and retained. There is no claim table, no `em_alert.task` column, and no automatic role, ACL or cross-scope privilege grant.

Only marked test-owned fixtures may be created or updated: CI/business-application/service/offering records via IRE; a dedicated support group; three locked-out, web-service-only users with no roles/email (including two with identical generated display names and distinct usernames); a marked base Task; and an owned service association. Existing configured native references can be read to complete the catalog, but unrelated records must not be adopted or overwritten. Stable ownership/source keys in namespace `USBEM-DTI-FIXTURES-V1` make reruns idempotent; duplicate or conflicting matches stop setup. No setup claim counts as a feature pass without actual subsequent Event/Incident/Alert evidence. Native platform rules and notifications still run.

The common env's CI/caller/group inputs plus the marked fixture pack generate the target-bound catalog; no externally authored fixture JSON is required for this setup. The configured group must already contain an active unique-name member for assignee controls, and the existing connector default-caller property must be valid. Setup does not alter operational group membership or that property. `--fixture-output` chooses the generated catalog (POSIX mode 0600; user-only folder ACLs required on Windows). `--prepare-fixtures-only` with setup performs preparation/readback without submitting test Events; its successful result is not a full-suite PASS. Normal platform processing may later populate owned CI asset/model references and create linked hardware assets. Follow-on records are retained and inventoried; fixture versions are not promised immutable through all later processing. Existing referenced model records are not created or mutated by the tester.

```bash
python3 test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --prepare-fixtures-only --fixture-output dti-reference-fixtures.json --report-file dti-setup-report.json
python3 test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --allow-default-ci-property --fixture-output dti-reference-fixtures.json --fixture-recovery-file dti-default-ci-recovery.json --report-file dti-report.json
python3 test_ci_identifier_precedence.py --restore-fixture-default-ci dti-default-ci-recovery.json --confirm-fixture-target https://dev123456.service-now.com --report-file dti-recovery-report.json
```

Replace the example origin with the exact selected DEV PDI. Recovery is a separate connection-only mode requiring no CI/caller/group inputs; do not combine it with provisioning flags. Choose a fresh journal path for each new temporary lease. Prefer an existing ignored private directory such as `.local-evidence/` for every generated catalog, journal and machine report; arbitrary filenames are not automatically ignored.

An existing valid default CI is reused without property writes. Otherwise the default/dummy-CI family needs the separate `--allow-default-ci-property` permission. This permits only `x_usbna_usb_event.default_cmdb_ci_sys_id` to be temporarily set during its three non-DTI controls. Before changing it, preserve the original row/value or absence in the `--fixture-recovery-file` journal (POSIX mode 0600; private Windows folder required). Guarded `finally` restoration must restore and read back that exact original state in the database and property cache; a concurrent external value must not be overwritten. If the property was absent, only the exact setup-created row may be removed to restore absence. An interruption can bypass `finally`, so recover from the journal before rerunning; restoration/recovery failure is an error, never PASS. A prepared catalog alone cannot certify this positive branch under a normal restricted run if the property is absent. Run the brief property phase only in the approved DEV maintenance window because unrelated unhinted events share the property. Do not enable provisioning or this property phase for production tests.

Keep setup provenance, recovery journals, filled catalog values and detailed JSON reports private. Reviewed source and sanitized summary publication is authorized at the coherent milestone for the delivered scope. Publishing the separately scoped production test does not assert that the still-pending administrative full retest passed.

## Comprehensive coverage and shared result semantics

The advanced comprehensive runner executes the broader manifest; it is not selected by the no-argument laptop workflow. `--access-profile production --list-tests` inspects the separate production-observable manifest described above. The comprehensive families include:

- Fast DTI, component versions, exact Event IDs and processing state, correlation breadcrumbs, all seven required Incident fields, exact CI/group values, later Alert-to-Incident linkage, and sequential duplicate reuse.
- Five wrappers, wrapped additional information as an object or JSON string, outer/envelope precedence, `records`/`events`/bare-array batches, mixed DTI/non-DTI records, aliases, defaults, time/severity/resolution mapping, and retained custom context.
- Malformed JSON and invalid record/container shapes, with valid-first malformed-batch checks for unintended Event/Incident effects; long-key distinction/reuse and Salesforce PERU mapping.
- Caller/assignee/default/fallback behavior; CI name/identifier/sys_id/class-label/canonical/node/resource lookup; assignment precedence, support tiers, service inference, offering parent filtering, CAR ID, and customer Incident fields using configured fixtures.
- Incident creation/duplicate/sender notes, initial and follow-up Alert notes exactly once, non-DTI Alert notes, successful/error debug companion Events and downloadable JSON artifacts, terminal states 6/7/8, and closed-Alert/foreign-ownership guards.
- Connector-owned Incident identity/correlation protection, scalar field/unknown-field reporting, snake/camel DTI aliases, `u_netcool_ticket` defaults, and the actual `u_generating_alert` back-reference where those customer fields exist. Missing customer fields remain incomplete, not passed.
- Omitted category/subcategory defaults and omitted DTI short-description autofill from Event description, with an ignored `dti_description` distractor retained as additional information. Historical Closed Alerts may retain their recorded terminal-cycle Incident; a current non-Closed Alert must separately link to the replacement Incident.
- Three simultaneous first events, always run and explicitly reported against the accepted race limitation.

Fast DTI submissions omit wait keys and must return the intended Incident within the configured prompt-response budget. The supplied env template uses the vetted settings: a 10-second POST budget, a separate 240-second stored-observation deadline, and 30 seconds of continuous stability. The observer separately polls stored Event, Incident, and Alert records and requires processing/link completion. The raw CLI retains a 120-second timeout fallback for compatibility; that setting was not live-certified here for the complete serial-read manifest. Increase observation headroom for a slower target if needed; a brief HTTP 200 is not a pass. Actual counts, feature statuses, timing, retained record IDs, and observation evidence are recorded in the JSON report rather than promised in advance.

Any failed assertion is a failure. Missing fixtures, hidden required fields, unavailable required evidence, denied lifecycle updates, or unperformed features make the run INCOMPLETE or an access/configuration error, with a nonzero exit; they cannot silently become PASS. Exit codes are `0` for a complete run (including `complete_with_known_limitations`), `2` for a functional failure, `3` for configuration/access/transport errors, and `4` for incomplete coverage. A fully exercised run still reports the accepted concurrency race as `complete_with_known_limitations`, not a concurrency-safety guarantee. Preserve the JSON report and retained tagged records without credentials. The prior suite 1.0.0 DEV execution took 1749.514 seconds and retained raw `fail`/exit 2, with 75 pass / 1 fail / 9 skip / 1 known limitation, zero errors and 93 cases. Its default-fixture failure and separate two-case supplemental PASS are explained above. Three concurrent submissions returned one distinct Incident; no race was observed in that trial, but the accepted limitation remains. Suite 1.1.0's provisioned full result is PENDING. Do not substitute historical runtime evidence or combine the supplemental result into a clean full-suite PASS.

## Comprehensive evidence access and intentional test writes

The comprehensive profile needs connector POST plus reads of `em_event`, `incident`, and `em_alert`, including processing state, required fields/correlation/references, and Alert state/Task-link/additional information. It additionally reads `sys_journal_field` for exact journal occurrences, `sys_attachment` metadata/files for debug JSON, required CMDB/group/service/offering records, the named default-CI property, exact-name users for ambiguity, and the marked foreign Task baseline. Ordinary comprehensive testing needs no Task create/write; provisioning separately needs Basic-auth administrative access. Hidden required fields block complete sign-off. These broader evidence requirements do not apply to the restricted production-observable profile above.

A comprehensive live run creates dozens of retained Events, Alerts, and Incidents and executes normal platform Business Rules and notifications. It does not suppress native workflow or mail. Review the test caller, assignment group, selected target, and production identity before running. The tester configures no scheduler or email notifier; that does not mean native platform notifications cannot occur. Exact record counts come from the actual report, not an advance promise.

Ordinary lifecycle and ownership tests intentionally update only Incidents and Alerts created and tagged by the current run, through an explicit table/field allowlist. They change test Incident state/closure data and test Alert state/Task link/metadata. Ordinary mode retains all records and never deletes them, invokes Scripts - Background, grants privileges, changes schema, or installs a service. Only the explicit administrative DEV setup and temporary-property restoration modes have the narrow exceptions documented above. Review the read-only plan before running in a production target. Missing required privileges remain a reported blocker; the script never grants them automatically.

## Accepted limitation and evidence

Simultaneous first events for the same message key can create more than one Incident. Extended actual HTTP testing on dev392825 took 263.786 seconds and reproduced two Incidents for three concurrent first requests. Sequential duplicates reused one Incident. The owner accepted this residual race and explicitly declined a claim table.

The default suite always exercises three concurrent first requests and reports observed IDs/counts under the accepted known limitation. Neither one non-racing run nor `complete_with_known_limitations` proves concurrent safety. Legacy wait compatibility is outside the default no-wait acceptance contract and must not be claimed unless explicitly exercised in a separate approved compatibility run. No finite test proves every production-specific rule, ACL, state transition, or concurrency interleaving; the report identifies the declared features actually exercised.

The attached current validation report records installed-source readback, observations, timing, retained DEV evidence, and which checks required broader authorized access. Historical reports distinguish exploratory legacy compatibility cases from the later fast-only required-field and BR-link checks and record failures found before these corrections. No production instance or production OAuth/restricted identity was deployed or exercised by this DEV validation. Validate production-specific Incident rules, references, choices, privileges, and identities in each target; DEV success does not certify them.

The prior suite 1.0.0 independent final readback verified 122 retained Events (119 primary and three debug), all Processed, 72 Incidents and 84 Alerts. Current Alert linkage and final evidence integrity passed; the only expected-field mismatch was the documented default-category fixture. Both Salesforce Closed forms stored severity `0` and resolution state `Closing`. Maximum observed POST was 2.347 seconds, and the minimum passing observed stable window was 94.224 seconds. Those historical raw and readback-audit JSON attachments retain authenticated API/reader byte verification; anonymous access is unavailable. Full raw and supplemental machine reports belong in this DEV KB, not public Git. They are not results for suite 1.1.0.

## Deployment and rollback

Release `2026.10.29.3` is the approved narrow runtime correction for Salesforce case status lost during generic alias promotion. It is deployed in DEV, and all six runtime source strings match the installer with existing BR configuration preserved. The correction recovers original case status only when normal preserved case-specific selection is empty and retains explicit Event severity/resolution priority. Focused regressions and the prior exact-file Salesforce feature cover the correction. Suite 1.3.0/article 1.7.0 change laptop invocation, fixture handling, reports and documentation, not runtime code or security. Their scoped delivery does not claim completion of the separate provisioned administrative full retest or publication of its article 1.5.0 draft. Historical fixture failure/incomplete coverage remain unchanged.

The portable runtime consists of the four `src/USBEM_*.js` Script Includes, `servicenow/USBEM_genericJsonV2.listener.js`, and `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`. Use `scripts/deploy_usbem.py`, `docs/install_from_scratch.md`, `docs/dti_transfer_package.md`, and `docs/production-transfer-inventory.md` for scope, prerequisites, privileges, configuration, and transfer details. The four includes run in `x_usbna_usb_event`; the listener and BR remain Global. The installer verifies stored source and allowlisted configuration after both creates and updates, including Advanced=true; a write response alone is not install proof.

Optional runtime debug attachments require the exact `GlideSysAttachment.write / execute` scriptable privilege for `x_usbna_usb_event`, reviewed in each target. Attachment evidence is mandatory for complete comprehensive-profile sign-off; production mode explicitly verifies only debug companion Events/metadata. Only DEV's existing requested privilege was approved for the historical runtime retest; do not transport the row or grant broad permissions. Successful plain debug capture has artifacts `01_raw_payload.json` through `08_response_summary.json`; DTI adds `09_dti_timeline.json`, and `10_error_context.json` exists only with error context. Missing privilege may affect capture; do not assume Event success under a capture failure.

CI identifier lookup queries `cmdb_ci` with an `INSTANCEOF` class filter. Resource-backed lookup instead can directly query the requested CI child table before the parent-table fallback. Review that child's scoped read access separately; identifier success does not prove resource access. The new DEV matrix exposed a `cmdb_ci_server / read` request. The owner approved that exact DEV privilege and live readback confirmed `allowed`; no other grants were changed. This is target-specific approval, not a portable privilege record or authorization to grant a child-table privilege on another target.

After an approved transfer, compare installed source with `python3 scripts/deploy_usbem.py --dry-run`, verify the endpoint's component versions, then run the laptop test with that target's fixtures and identity. Do not copy PDI sys_ids, credentials, junk event rules, or the retired async linker into production.

Rollback the runtime using the previous approved six source records and their configuration. Keep test records as evidence until normal Incident/Event retention or an approved, exact-record cleanup is performed. No Linux-service uninstall step is part of this deliverable.
