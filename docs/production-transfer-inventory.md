# Production Transfer Inventory

## DTI runtime

Release `2026.10.29.3` uses the Event Management Instance push connector, not a separate
Scripted REST API. Its normal DTI path creates or reuses an incident, stores the message-key
breadcrumb in `incident.correlation_id`, and returns promptly. The alert reconcile Business Rule
links the later alert to that incident. Do not add a wait key to new callers; it is legacy
compatibility only.

Current test delivery is suite `1.2.0` / published article `1.6.0`: an explicit three-table
`--access-profile production` mode plus private-fill env/catalog templates. It changes test
assets/documentation only, not runtime `.3`, security or production data. Focused DEV validation
under the enforced three-table request boundary is complete; matching DEV article/body/current
attachment verification is complete, and no actual production identity is certified. The approved Salesforce correction is already deployed in DEV with six matched
runtime sources and preserved BR configuration.
Local validation: 416 Python + 234 JavaScript checks (650 total), including 102 production
unit methods. The independent native-Alert model exercises all 85 actual callbacks with 84 PASS /
1 accepted concurrency limitation: 102 modeled cases, 119 connector calls, 11 negative probes,
24 formatted-note reads, three debug companions and five owned PATCH operations. This is not
full live production proof. Frozen program SHA-256:
`68db4a360ae112c223e327bc5a51f1f5bc2e77703353b42a96dc2d3bf4f5d280`.
The exact-file focused DEV run completed 20 checks/33 cases in 725.494 seconds: 19 PASS,
one accepted concurrency limitation and zero failures/errors/skips. Maximum POST 1.137 seconds,
minimum case stability 34.813 seconds, eight formatted-note observations and three debug companions.
Three first concurrent requests created three Incidents under the accepted race. Independent
GET-only readback passed with three queries/zero writes: 45 Events all Processed (42 primary +
three debug), 15 Incidents, 25 Alerts and 98 required-field checks; expected fields/links unchanged.
See [the scoped validation report](validation-2026-10-29-production-access.md). This is not
full 85-feature live acceptance or actual restricted production-account/corporate-endpoint proof.
Knowledge article `1.6.0` is published, active, latest and reader-verified in the matching DEV PDI.
Normalized body readback is exact; current program/configuration and evidence uploads pass authenticated API/reader byte checks,
actual reader download links render, and anonymous requests do not return files.

The separate provisioned administrative full retest remains incomplete, including the unapproved
business-application read privilege and default-CI prerequisites. Suite 1.1.0/article 1.5.0 added
the privileged DEV setup path; article 1.5.0 was an unpublished draft. That broader pending gate
does not prevent delivery of the separately scoped production-observable test. Historical raw
failures and gaps remain, not converted to a clean full-suite pass. Sanitized public Git publication
is authorized at the coherent delivery milestone; detailed reports/filled catalogs remain private.
The prior suite 1.0.0 exact-file full CLI finished in 1749.514 seconds with 75 pass / 1 fail / 9 skip / 1 known
limitation, zero errors and 93 cases. Raw `fail`/exit 2 is preserved: the sole failed assertion
was our incorrect default-category fixture, separately retested with two supplemental passes.
The nine unavailable-feature gaps remain; this is not a clean full-suite PASS.
Historical `.2` corrected-path DEV retest PASS is recorded separately. The
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
- Resource-backed CI lookup can query its requested CI child table directly; review that table's
  scoped read privilege independently of the identifier path's `cmdb_ci` + `INSTANCEOF` access.
  The current DEV comprehensive trial generated a `cmdb_ci_server / read` request; the owner
  approved that exact DEV privilege and readback confirmed `allowed`. No other grants changed.
  No DEV privilege row is a portable grant.

## Standalone Python test and Knowledge

- `tests/test_ci_identifier_precedence.py`: canonical on-demand Python 3.9+ API-and-BR tester.
  The historical filename is retained. Use `--access-profile production` for the 85-feature
  three-table production-observable manifest; the default `comprehensive` profile retains the
  broader administrative-evidence requirements.
  It imports no other project files and requires no packages, Linux service, root access,
  scheduler, or monitoring email configuration.
  Suite version `1.2.0` is separate from runtime `2026.10.29.3`; plan/report provenance
  includes the executing script's SHA-256 captured at module load.
  Explicit Basic-admin DEV fixture setup and temporary default-property control are additional
  opt-ins in that same file, unavailable in production mode and not restricted-account requirements.
- `tests/production_test.env.example`: private-fill production URL/profile, Basic/OAuth,
  CI/required-field/assignment and timing template. A shared Basic username can use separate
  profile passwords; explicit blank selected URLs fail before network and unselected blanks are ignored.
- `tests/production-fixtures.example.json`: complete-shaped configuration for all 14 production
  advanced families, exact expected target references and nine owner attestations. Invalid ID
  placeholders and false attestations must be replaced/verified before any Event is submitted.
  This is configuration, not a second test program; no PDI values are portable.
- `docs/production-test-usage.md`: production commands, target-data preparation, observable
  coverage, rights boundary, retained records and notification/outage-rule warning.
- `docs/validation-2026-10-29-production-access.md`: frozen-program provenance, offline/model
  validation, focused live DEV three-table evidence and independent readback, with explicit
  full-live/actual-production-account limitations. It does not replace administrative full evidence.
- `tests/test_dti_production_runner.py`: 102 offline production-mode regression methods,
  including an independent native-Alert model invoking the complete 85-feature manifest.
  This repository regression asset is not a second laptop executable or a live production result.
- `docs/validation-2026-10-29-production-access.md`: sanitized suite 1.2.0 provenance,
  offline/model results, scoped live DEV validation, rights boundaries and attachment proof.
- `tests/ci_identifier_test.env.example`: non-secret template for target URL, Basic or OAuth
  credentials, CI fixtures, required Incident fields, and the required group/exact-ID expectation.
  The JSON reference catalog is configuration supplied by `--fixture` or
  `USBEM_TEST_FIXTURES_JSON`, not another test script. Keep filled files private; base64 is
  encoding, not credential protection.
- `tests/test_ci_identifier_runner.py`, `tests/test_dti_comprehensive_runner.py`, `tests/test_ci_lookup_precedence.js`,
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
- `docs/validation-2026-10-29-python-comprehensive.md`: separate evidence record for the actual
  prior suite 1.0.0 one-file CLI, frozen script provenance, approved resource-child read privilege,
  offline validation and the actual qualified/incomplete live result. Do not substitute an earlier trial's outcome.
- `docs/validation-2026-10-29-provisioned-comprehensive.md`: new suite 1.1.0 setup/recovery and
  exact-file full-run evidence; currently PENDING. Prior report/raw outcomes remain unchanged.

For production use `--access-profile production --list-tests` and the matching read-only `--plan`.
Its transport and runner allow only connector POST, Event reads and owned Alert/Incident reads/PATCH.
No reference-table reads, dot-walks, admin fallback, fixture setup, schema/property/security writes,
direct Event writes, creates/deletes, background scripts or attachment downloads are permitted.
Static full-catalog validation and populated required-field probes precede the first Event.
Stored reference IDs still must match independent owner expectations. After fresh raw ownership
verification, note sentinels use only the exact owned Incident/Alert's formatted visible
`sys_id,work_notes` view. Blank/missing formatted views are incomplete even for negative checks;
visible presence/absence does not prove complete raw history, exact global counts or hidden entries.
Debug Events do not prove attachment bytes, and source-reference facts
are explicitly owner-attested. Non-Incident Task proof is excluded. Complete production status is
scoped to that observable manifest, not broader administrative certification.

For the broader comprehensive profile inspect its `--list-tests` and read-only `--plan`.
Selected profile URLs must be non-empty; missing/blank selection stops before network calls,
never falls back to a global PDI. Explicit `--instance` wins; unselected blank profiles are
ignored for staged DEV-first configuration. Empty normalized profile names are rejected.
The supplied template uses the vetted 240-second observation deadline, 30-second continuous
stability, and 10-second POST budget. The raw CLI's compatibility fallback of 120 seconds is
not claimed as live-certified for this full serial-read manifest.
The comprehensive matrix observes processed Events, exact required Incident fields/CI/group/correlation,
actual Alert links, wrapper/batch/alias/default/error contracts, sequential duplicates, terminal
6/7/8 replacement/reuse, ownership guards, journal occurrence counts, debug JSON downloads,
fixture-driven routing, Salesforce PERU mapping, and concurrent first events. No default payload
uses a legacy wait key. The full identity needs connector POST; Event/Incident/Alert reads;
`sys_journal_field` reads; attachment metadata/file reads; and permission to PATCH the run's own
tagged test Incidents/Alerts for lifecycle and ownership checks. The ordinary-mode allowlist excludes
unowned writes, deletes, Scripts - Background, CMDB/schema/security changes, and grants.
Advanced fixture validation also reads the required CMDB/group/service/offering records and
the named default-CI property; ambiguous-user coverage reads exact-name `sys_user` matches.
Customer default/back-reference checks require actual readable
`u_netcool_ticket` and `u_generating_alert` fields; absence cannot become a positive result.
The foreign-task guard additionally needs a marked non-Incident test Task whose
short description starts `[TEST] USBEM` (or the configured more-specific marker), its
`foreign_task_sys_id`, Task baseline reads, and the actual Alert Task-reference field's read/write
access. DEV's `em_alert.incident` references `task`; no `em_alert.task` column is needed or added.
Ordinary guard execution links only its own Alert and verifies the Task is unchanged. Explicit
DEV setup can create the marked Problem/base Task fixture; no arbitrary real Task is adopted.

Both profiles create real retained test Incidents and Alerts and run normal platform Business
Rules. Native email/notifications, outage automation and other local rules can fire; none are
suppressed. Choose an approved testing window, caller, group and CIs. The test configures no email
notifier or scheduler. No actual production account or environment is claimed tested by DEV evidence.
Generated outputs use atomic replacement and POSIX 0600 mode where supported. Credentials,
catalogs, reports and recovery journals on Windows require a user-only NTFS folder; `mkstemp`
and POSIX mode bits cannot create private Windows ACLs.

### Explicit DEV setup and recovery boundary

`--provision-dev-fixtures` requires `--confirm-fixture-target` matching the exact selected HTTPS
PDI origin on a `dev<digits>.service-now.com` host, plus Basic-auth administrative access. It
executes an embedded, allowlisted Global background setup. `--plan` remains read-only and
describes these conditional writes. Normal tests against approved existing fixtures continue
with Basic or OAuth identities and do not perform setup.

Only five exact custom fields may be created: `cmdb_ci_business_app.u_car_id` string(100),
`cmdb_ci.u_level_2_support_assignee_group` reference to `sys_user_group`(32),
`incident.u_usb_em_test_value` string(255), `incident.u_netcool_ticket` boolean, and
`incident.u_generating_alert` reference to `em_alert`(32). All are customer `u_*` fields in
Global schema matching the runtime's existing names.
Existing type/reference mismatches stop setup; existing fields are not repurposed. Test-owned
groups, locked-out/web-service-only role-free email-blank ambiguous-name users and a marked non-Incident
Task are allowed; owned CI/service/offering data uses IRE. Record ownership and stable source
keys must be verified before any update; duplicate/colliding matches stop setup. Schema and
fixture data persist and are inventoried, not silently removed. There is no claim table, new
Alert task column, or automatic role/ACL/cross-scope grant.
Normal platform processing may also populate owned CI asset/model references and create linked
hardware assets. Retain/inventory those follow-ons, but do not export or automatically delete
them. A passing bounded installer-rerun comparison does not promise fixture versions are
immutable through later platform activity. Existing referenced models are not mutated by setup.

`--prepare-fixtures-only` performs setup/readback without submitting test Events;
`--fixture-output` chooses the target-bound catalog (POSIX 0600; user-only Windows folder required). Common env baseline inputs
plus the owned pack generate all fixture cases; no external fixture JSON is required for setup.
The configured group must already have an active unique-name assignee member, and the existing
default-caller property must be valid; setup never adds operational membership or changes that
property. Stable namespace `USBEM-DTI-FIXTURES-V1` ownership/drift checks govern reruns.

`--allow-default-ci-property` separately permits a brief temporary value for only
`x_usbna_usb_event.default_cmdb_ci_sys_id` during the three non-DTI default/dummy controls.
A `--fixture-recovery-file` journal (POSIX 0600; private Windows folder required) records original row/value or absence, and guarded
`finally` restoration must be read back in the database and effective property cache. An existing
valid default CI is reused without writes. Recover interrupted runs with
`--restore-fixture-default-ci JOURNAL --confirm-fixture-target <exact-origin>` before proceeding;
that separate mode needs connection credentials only and cannot be combined with provisioning.
Use a fresh journal path for each lease. Do not overwrite a concurrent
external change. If originally absent, only the exact setup-created property row may be removed
to restore absence. Restoration failure is an error/nonzero. This shared property can affect
unrelated unhinted events while set; require the approved DEV maintenance window. Do not
transport PDI setup data/journals or enable setup/property writes on production targets.
Preparation alone cannot certify a positive missing-default branch for a subsequent normal
restricted-account run; the temporary lease requires the explicit administrative full-run flags.
Use an existing ignored private directory such as `.local-evidence/` for arbitrary generated
catalog, journal and report names; credentials omitted does not make metadata safe for public Git.

Target-specific JSON fixtures cover caller/assignee names and IDs, default caller, support tiers,
service/offering, and advanced lookup/customer-field branches. Advanced feature values may be arrays
of case objects. Offering parent filtering needs positive and negative controls; default-CI policy
needs three distinct controls including a valid non-empty configured default CI, explicit-unresolved
CI suppression, and no-hint blank behavior. Without the explicit DEV property opt-in, a missing
default leaves the whole family incomplete.
Expected additional-info native JSON values and absent keys are supported; user booleans/numbers
are not stringified. Connector-added routing/DTI values retain their operational string contract.
Root/envelope Event/SPECIAL aliases outrank wrapped aliases, separately from wrapped real Incident
passthrough overriding envelope Incident defaults. Canonical fixture inputs
must differ beyond letter case; exact names do not prove canonical resolution.
`duplicate_work_note_enabled` is a JSON boolean matching the actual target property, not a request
to change it. If local closure requires it, `terminal_extra_fields` may contain only an existing,
readable, non-empty string `u_cause`; the owned Incident update's stored value is verified.
No other extra PATCH field is allowed. Missing fixtures, hidden evidence,
denied updates, or unperformed features yield INCOMPLETE/nonzero, not a smaller green suite.
An absent customer field in a PDI cannot count as a tested production mapping. The JSON report
records actual counts, timings, stable observations, feature statuses and retained records;
no old focused-suite count/duration applies. The prior suite 1.0.0 exact-file CLI result is retained as
`fail`/exit 2: 75 pass / 1 fail / 9 skip / 1 known limitation in 1749.514 seconds (93 cases;
zero errors). Independent final readback found 122 retained Events, all Processed, 72 Incidents
and 84 Alerts; the only required-field expectation mismatch was the documented category fixture.
The historical release retest above is not that new script's result.
Production rules and permissions must be validated in each target rather than inferred from DEV.
Supply `default_category` and `default_subcategory` as independently verified stored defaults.
Do not infer them solely from choice labels: DEV stores the declared parity literal `Software`,
not canonical PDI choice `software`, and `Monitoring Alert` is not an installed PDI choice.
Seven filled fields are not choice-taxonomy certification. Prefer explicit stored production
choice values; retain raw failed reports and distinguish any corrected-fixture supplemental retest.
The same-final-script supplemental defaults execution passed two cases in 44.619 seconds,
including real stored-record readback and 30-second stability. It remains separate from the
completed full CLI and does not rewrite its raw failure as a pass.
Their omitted-payload test and the Event-description short-description fallback are separate
from explicit field overrides. Advanced Incident-field families must actually create an Incident;
`want_incident:false` cannot bypass their readback. Terminal observers preserve valid Closed
prior-cycle links and still require a current Alert linked to the replacement.

The owner accepted the known simultaneous-first-event race and declined a claim table. No claim
table is part of this package. Three concurrent first events always run and report the observed
race explicitly. Only fully exercised coverage can return `complete_with_known_limitations`;
that status is not a claim of concurrency safety. Exit codes: 0 complete (including that qualified
status), 2 functional failure, 3 configuration/access/transport error, 4 incomplete.
The prior suite 1.0.0 trial's three submissions returned one distinct Incident and did not observe a race;
that single trial does not eliminate the accepted concurrency limitation.
Legacy waiting and optional Flow/email/ATF/locked-transform artifacts are outside this default
current-listener API-and-BR manifest and require separate explicit compatibility validation.

Instance URLs, credentials, sys_ids, users, roles, and Knowledge numbers are environment-specific and are not portable artifacts.
The GitHub repository is public. Filled fixtures and full machine reports must not be committed;
credential-free evidence can still expose target/record metadata. Retain detailed new evidence
only in the selected PDI's Knowledge attachments and publish a reviewed sanitized summary.

Current matching DEV article: KB0010015 on dev392825, sys_id
`7433ede097d457105fb3ba6de053af9b`. Article 1.6.0 is published, active, latest and reader-verified,
with attachments enabled and exact normalized body readback. Current program/configuration and evidence uploads pass exact-byte
authenticated API/reader download verification, and anonymous downloads do not return files.
Actual reader links render for the canonical program, production env/catalog and usage guide.
Only the previous Python/common-env attachments were replaced, with local recovery copies retained;
all historical reports remain intact. Article 1.4.0 is historical; 1.5.0 was not published.
Suite 1.1.0's administrative provisioned full evidence remains incomplete. Sanitized public Git
publication is authorized but not yet claimed complete. Full detailed
reports and filled fixture data remain private. Do not treat older
attachment hashes as proof of the updated bytes. The earlier dev382837
KB0010025 is a separate historical copy and is not the documentation target for dev392825 work.
