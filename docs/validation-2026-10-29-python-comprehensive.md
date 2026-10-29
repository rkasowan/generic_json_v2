# Standalone comprehensive Python tester — 2026-10-29

This is a **sanitized public summary**, not the full machine report. Instance hostnames, run IDs,
record identifiers, precise execution timestamps, fixture values, and record-level evidence are
deliberately excluded. The complete credential-free JSON still contains internal metadata and
belongs only in the selected DEV PDI's Knowledge attachments, not public Git.

## Verdict

**QUALIFIED / INCOMPLETE COVERAGE: runtime `.3` is deployed, but no clean full-suite PASS is claimed.**
The exact-file full CLI completed with raw status `fail`/exit 2: **75 pass, 1 fail, 9 skip,
1 known limitation, zero errors, and 93 cases** over **1749.514 seconds**. Its sole failed
assertion used our incorrect default-category fixture. A separate corrected-fixture defaults
execution using the same script passed both cases; it does not rewrite that full raw failure.
Nine unavailable-feature gaps remain. Deployment readback matched all six normalized source
strings, and an independent final audit confirmed stored evidence. Script/template Knowledge
attachments and final detailed reports are byte-verified. Article 1.4.0 is published, active,
latest and reader-verified in the same DEV PDI with reader-visible attachments; public Git
publication remains held for approval.
Do not substitute a previous browser-driven matrix or local unit-test result for this execution.

Target class: **requested DEV PDI**. Deployed connector runtime: **2026.10.29.3**.
Standalone Python test suite: **1.0.0**. Matching documentation is in the same DEV PDI,
article source version **1.4.0**. No production target or production OAuth identity is certified
by this PDI work.

## Purpose and exact test artifact

The canonical work-laptop tester is one standard-library Python 3.9+ file:
`tests/test_ci_identifier_precedence.py`. Its historical filename is retained, but its default
CLI now executes the complete declared current Generic JSON V2 API-and-BR manifest. It imports
no other project module. The env template and reference-fixture JSON are configuration, not
additional test programs.

The read-only `--list-tests` / `--plan` paths require no credentials or network requests.
The plan and actual report record `test_suite_version` and `script_sha256`, captured from the
executing file at module load. The suite version is separate from the runtime release.
The current `.3` frozen script declares 86 features. The final outcomes below come from its
completed report and independent readback, not the earlier exploratory trials.

| Final execution fact | Result |
|---|---|
| Script SHA-256 / suite version | `39bda3b5ae4e0192c384a8d6df55679805b505fc998f6ab6bf7b9f3fae6ed369` / suite 1.0.0 |
| Execution target / identity class / transport | DEV PDI; approved Basic-auth API identity, normal stock-Python HTTPS execution with certificate verification; detailed provenance retained only in Knowledge |
| Actual elapsed duration | **1749.514 seconds** (29 minutes 9.514 seconds) |
| Manifest / feature outcomes / cases | **86 features: 75 pass, 1 fail, 9 skip, 1 known limitation; zero errors; 93 cases** |
| Machine status / process exit code | **`fail` / 2**, preserved unchanged; sole failure was the default-category fixture expectation |
| Retained Event / Alert / Incident counts | **122 Events (119 primary + 3 debug), all Processed; 84 Alerts; 72 Incidents**, independently read back; record identifiers excluded |
| Fast response / stable evidence | Maximum POST **2.347 seconds**; minimum passing observed stable window **94.224 seconds** |
| Full machine JSON evidence | Final raw JSON attached in matching DEV Knowledge; authenticated API/reader bytes verified and anonymous access unavailable; do not commit publicly |
| Local regression validation totals | **435 passing offline checks**: 230 Python + 205 JavaScript (including seven selected-target guard tests, twelve publisher checks, and 66 Salesforce checks); Python compilation is clean |
| KB publication and attachment byte verification | Article 1.4.0 published/active/latest; exact body content and reader-visible attachments verified. Script/template exactly one each; detailed-report API/authenticated-reader bytes verified. Anonymous requests return login, not files |

Configured final-run observation controls are **30-second continuous stable observation**,
**240-second observation deadline**, and **10-second fast POST budget**. Other final options
and observed timing belong in the execution record above. There is no fixed minimum duration
or pre-promised Event/Incident count for this expanded matrix.
The supplied env template now matches those controls. The raw CLI retains a 120-second fallback
for compatibility; this report does not live-certify that smaller budget for the full manifest.

Independent final GET-only readback verified the full retained-record union, all Event processing
states, current Alert linkage and required-field evidence. The only expected-field mismatch was
the documented default-category fixture. Both Salesforce Closed forms stored severity `0` and
resolution state `Closing`. All six active `.3` source strings, the exact BR configuration and
the uniquely allowed approved child-table read request matched their expected values.

The concurrency trial submitted three requests and returned **one distinct Incident**;
`race_observed` was false. No duplicate Incidents were observed in that trial. This does not
remove the previously reproduced, owner-accepted simultaneous-first-event limitation.

The final candidate adds a pre-network target-selection guard: a selected profile with no URL
fails rather than using a global instance. An explicit instance override wins, unselected blank
profiles are ignored, and empty normalized profile names are invalid. The earlier completed or
continuing comparison candidate is not final evidence for this updated exact file. The completed
exact-file outcome is recorded above. This configuration-only change does not alter runtime `.3`.

## Coverage and result contract

Confirmed historical `.2` runtime finding: a Salesforce case with root `status:"Closed"` has that
field consumed by generic Event resolution-state mapping before Salesforce severity inference.
It produces `resolution_state=Closing` but inferred severity `3`, whereas canonical
`case_status:"Closed"` produces severity `0`. The owner approved the narrow recovery fix and DEV
retest. Release `.3` now selects remaining case context, then original additional information,
then original Event context, recovering status lost during alias promotion without overriding
explicitly mapped severity/resolution. User JSON types remain intact. Regress canonical,
root/wrapped generic, blank/conflicting statuses, overrides, and non-Salesforce controls. Targeted
live root/canonical Closed controls and the final exact-file Salesforce family passed. Independent
final readback confirmed severity `0` and resolution state `Closing` for both Closed forms.
The alias remains explicitly tested. The approved DEV resource-child privilege was separately
verified allowed; it is not a remaining blocker.

Tester expectation corrections are separate from that runtime finding: user additional-info JSON
values retain native types, and root/envelope Event/SPECIAL aliases outrank wrapped aliases.
Only real per-record Incident passthrough fields overlay envelope Incident defaults. Neither
correction requires a runtime rewrite or changes those existing precedence/type contracts.

The authoritative manifest is emitted by the exact script. Declared coverage includes:

- Prompt no-wait DTI responses and component versions; stored Event processing; all seven
  required stored Incident fields, exact CI/group/correlation; actual Alert-to-Incident linkage;
  and sequential replay without unexpected Incidents.
- Five root wrappers, wrapped object/string additional information, outer/envelope precedence,
  mixed and homogeneous batches, aliases, defaults, time/severity/resolution normalization,
  custom context, malformed shape/JSON handling, no-side-effect probes, long/generated keys,
  and Salesforce PERU mapping.
- CI/name/identifier/sys_id/class-label/canonical/node/resource lookup, assignment/support tiers,
  service inference, offering parent controls, CAR ID, and user/default/fallback/ambiguity behavior
  with independently verified target fixtures.
- Exact journal occurrence counts for creation, duplicate, sender and follow-up notes; note
  consumption; debug companion Events and downloaded JSON content; terminal states 6/7/8;
  Closed prior-cycle links; and foreign ownership guards.
- Connector-owned Incident identity/correlation protection, generic scalar mapping/reporting,
  snake/camel DTI aliases, omitted category/subcategory defaults, Event-description short-description
  fallback, and actual customer defaults/back-references (`u_netcool_ticket`, `u_generating_alert`).
- Three concurrent first events, always exercised with the accepted duplicate race reported
  explicitly as a known limitation.

Missing positive fixtures, absent customer schema, unreadable required fields/journals/files,
denied required lifecycle updates, or unperformed features cannot return an unqualified PASS.
The current PDI's missing fixture/schema families must remain explicitly incomplete rather
than being filled by invented data or marked passed. A complete run with the accepted race has
status `complete_with_known_limitations`, not a claim of concurrency safety. Exit codes are 0
complete/qualified complete, 2 functional failure, 3 configuration/access/transport error, and
4 incomplete.

Advanced Incident-field families must actually create an Incident; `want_incident:false` cannot
bypass their readback. Offering parent filtering needs positive and negative controls for the
same offering under different services. Default/dummy-CI policy needs three distinct controls,
including a real non-empty configured default CI; a missing default makes that family incomplete.
Canonical controls must differ beyond case/outer whitespace. Ambiguous-user coverage requires
at least two existing exact-name users, not a missing or unique name.

## Independent DEV fixture-availability audit

A separate GET-only audit distinguished unavailable schema, missing configuration, and missing
positive data. Actual table ancestors were checked, with 17 readable out-of-box dictionary
controls. No schema, properties, records, fixtures, or running-test settings were changed.
These findings explain the final run's nine skipped families; they do not turn them into passes.

| Family | Aggregate availability finding | Required catalog/evidence |
|---|---|---|
| CAR ID | Required `u_car_id` absent across business-application CMDB ancestors | `advanced_cases.car_id`, plus actual installed field and positive business-application fixture |
| L2 support group | Required L2 field absent across CI ancestors | `advanced_cases.l2_support_group`, plus installed field and a CI with empty primary support group and valid L2 group |
| Custom Incident fields | No `u_*` dictionary fields on Incident/Task ancestors | `advanced_cases.custom_incident_fields` using an actual installed field |
| Generating Alert back-reference | Required customer field absent | Automatic actual-field readback; no catalog value substitutes for schema |
| Netcool default | Required customer field absent | Automatic actual-field readback; no catalog value substitutes for schema |
| Default/dummy CI policy | Named default-CI property has no row; this is missing configuration, not missing CMDB schema | Existing valid configured default CI plus three `advanced_cases.default_dummy_policy` controls |
| Offering parent filtering | Parent field exists/readable, but no offering has a populated parent; positive fixture data is missing | Two `advanced_cases.offering_parent_filter` controls: valid parent match and different-service nonmatch |
| Ambiguous user rejection | 650 nonempty names form 650 groups, with no duplicate-name group; no positive ambiguity data | `advanced_cases.ambiguous_user_rejection` using an existing genuinely duplicated exact name |
| Foreign Task guard | Alert task-link field absent, and no appropriately marked non-Incident Task found | Existing link schema and preprovisioned marked Task; `foreign_task_sys_id` / optional marker |

The nine families therefore must not all be described as absent schema, or merely as unfilled
catalog entries. The audit did not find an appropriate existing positive fixture that was simply
left unconfigured. The tester must report unavailable evidence as incomplete; it must not create
customer fields, duplicate users, alter properties, or provision business data to manufacture a pass.
Record identifiers, user names, fixture values, and precise audit timestamps are excluded here.

## Transparent default-fixture disposition

The earlier `.3` comparison candidate completed in **1770.917 seconds** with **75 pass,
1 fail, 9 skipped, and 1 known limitation**. Its sole failure was the assistant-chosen
`default_category=software` expectation versus the actual stored `Software`; the subcategory
expectation `Monitoring Alert` matched. The raw report remains failed and is retained unchanged
as detailed Knowledge evidence, not published as a clean full-suite pass.

The source explicitly declares literal Software / Monitoring Alert defaults for retired-flow
parity. The helper permits literal storage; the test itself qualifies its purpose as a stored-value
contract, not certification of target choice taxonomy. The active PDI Software choice has the
canonical value `software`, so the stored parity literal is noncanonical on this PDI even though
the required field is filled. Choice metadata alone did not establish the runtime default and
was an unverified fixture assumption. The [Australia Scoped GlideElement API](https://www.servicenow.com/docs/r/australia/api-reference/server-api-reference/c_GlideElementScopedAPI.html)
describes the display setter; it does not establish portable normalization of every string-choice
label. No runtime choice-normalization change is being made.

Only the temporary supplemental fixture was corrected to the explicitly declared/stored
parity default. A focused defaults-method execution using the **same final script bytes** passed
**both cases in 44.619 seconds**, including actual Event/Incident/Alert readback, a continuous
30-second stable window, and final evidence checks. An earlier invocation completed checks but
its operator-side JSON serialization failed; the clean repeat retained the full supplemental JSON.
The current exact-file full run loaded the original fixture; its raw `fail`/exit 2 remains
untouched, with the same single default-category mismatch. This separate focused success must not be
retroactively combined into a claim that one full run passed cleanly. Prefer explicit stored
choice values in production: seven filled fields do not certify category/subcategory validity.

## Refreshed standalone attachments

There is exactly one current Python attachment and one env-template attachment on the matching
DEV Knowledge article. Both authenticated API download and authenticated reader download
matched the exact local bytes; anonymous download is unavailable. No filled fixture or full
machine report is included in the public summary.

| Attachment | Verified raw-file SHA-256 |
|---|---|
| `test_ci_identifier_precedence.py` | `39bda3b5ae4e0192c384a8d6df55679805b505fc998f6ab6bf7b9f3fae6ed369` |
| `ci_identifier_test.env.example` | `40afd83f1086a63c5187bb9a89b99b672a67717f0a6e74647538f2fd63090f54` |

The three historical validation-report attachments are preserved. The final raw report and
independent readback-audit JSON have authenticated API/reader byte verification; anonymous
requests return login rather than files. The published article body matches the frozen source
content, and the reader shows version 1.4.0 and its attachments. The publisher allows only ASCII
whitespace differences between HTML list tags, covering platform formatting without ignoring
text/content differences; twelve focused regression checks cover that comparison behavior.

## Safety and identity boundary

The tester uses the connector/listener endpoint, not direct Event insertion. A comprehensive run
creates dozens of retained records and executes normal platform Business Rules/notifications;
native workflow and mail are not suppressed. Review caller/group/target/identity first. It reads actual
Event/Incident/Alert state, journals, attachments and required fixture metadata. It has no
Linux service, scheduler, root requirement, monitoring email, schema/security installer, or
background-script dependency. Normal cases omit legacy wait keys. No POST is automatically
retried; redirects are rejected; TLS verification is enabled unless explicitly disabled by the
operator. Reports omit credentials and do not log raw HTTP error bodies.

Intentional Table API PATCH operations are allowlisted and restricted to this run's tagged
Incidents and Alerts, with fresh stored ownership/provenance checks. They exercise Incident
state/closure and Alert state/link/metadata. Optional `terminal_extra_fields` permits only an
existing non-empty string `u_cause`, with stored readback; it is not arbitrary field write access.
All test records are retained. The script never deletes records, grants privileges, changes
schema/properties, or invokes Scripts - Background.

The foreign-task guard requires a preprovisioned non-Incident Task subclass whose short
description starts `[TEST] USBEM` (or a more-specific permitted marker), its explicit fixture ID,
Task read access and `em_alert.task` read/write. Only an owned Alert is linked/updated; the
preprovisioned Task is never created or written and its baseline must remain unchanged.

These checks do not certify arbitrary customer business rules, inaccessible records, every
state transition, unbounded load, all possible concurrent interleavings, optional inbound-email
Flow/ATF/locked-transform artifacts, or unexercised legacy waiting. Production-specific identity,
rules, references, choices and privileges require their own target execution.

## Historical `.2` baseline source and BR configuration evidence

Before the approved Salesforce correction, the six deployed runtime records were independently
read back against release `.2`; the following historical SHA-256 baseline is retained unchanged.
It is not `.3` source proof; the new `.3` deployment record follows separately below.

| Component | SHA-256 |
|---|---|
| USBEM_Core | `a990a2aa6dbffcd9c9b6a7551a493d6dbbca7eae21631c38fe72ecd5e0784cec` |
| USBEM_Lookups | `3e032fca89033493310403bd2db5f674dae56ac7b51b00ac98a8cc0861c4d55c` |
| USBEM_Debug | `90adf165e4600c1936e8b5fe31ad6a7d208397780c414f0ba1cd2e03d406b55b` |
| USBEM_DTI | `c13fc86c626bbfe304401742f1ec957ef6bfc574cabd3fafea4c7648f5ce3073` |
| genericJsonV2 listener | `05ce45fb659d31e89a9840716698c5ae7f4d91593d7c7b64b3f7b05cf5ef835f` |
| Fast DTI Alert Reconcile BR | `50095e5d50b1e4a32953a9267e965a12b5a5e5dc03fe27dcb28e43770286f1e5` |

The four Script Includes remain in scope `x_usbna_usb_event`; the listener and BR remain Global.
Record/scope identifiers are retained only in private evidence. BR configuration:
active=true, advanced=true, `em_alert`, after, order 150, insert/update=true,
delete/query=false, abort_action/add_message=false, not async. Its condition is:

```javascript
((current.getValue('additional_info') || '').indexOf('work_notes') > -1 ||
 ((current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1 &&
  (current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)))
```

The observer preserves the runtime's lifecycle contract: a historical Closed Alert may keep
its recorded terminal Incident, while a current non-Closed Alert must link to the replacement.
An old Closed Alert alone is not proof that the replacement was linked.

## Release `.3` deployment readback

The six deployed source strings matched the following hashes after deployment. These are SHA-256
over **LF-normalized UTF-8 source strings**, matching the deployer's text-read behavior for legacy
mixed-EOL files. They are not raw mixed-EOL file hashes. Independent GET-only post-deployment
verification passed; source matching alone does not complete the live feature matrix.

| Component | LF-normalized source SHA-256 |
|---|---|
| USBEM_Core | `0bdcaa66c7ff52ca5b5978942505c0707f802f2b68243772d6eb22d75b7580c5` |
| USBEM_Lookups | `dd0bb22db627922a2fc6153d2b0e68ca9e05b925f1052da19b7f22d2f1c46f60` |
| USBEM_Debug | `c37a6e78c82f88c0b2111a211b1a0a79727702b639ad8412335f35c843822eab` |
| USBEM_DTI | `83802e02061806f1a04a83c71d32e2129632a2d7cede1a864d574bfb50924d2c` |
| genericJsonV2 listener | `efc207d4ae76f753a106943c5256cb36fb5590e892e2cc079301a1300dc3a749` |
| Fast DTI Alert Reconcile BR | `61c9536b160e2ca128359cae75ca2c135d5182493cc6515d448ccce747907bf4` |

The existing record identities/scopes and BR configuration are retained. Independent confirmation
of the `.3` BR's active/Advanced/after/order/operation flags and exact condition passed. The actual
installer's read-only drift check reports all six components up to date.

## Exact approved DEV privilege

The actual resource-path trial generated a specific scoped read request for `cmdb_ci_server`.
The owner approved **only that exact DEV request**, and readback confirmed `allowed` from the
application scope to Global. No other privilege grant changed in this tester update. Exact
privilege/scope record identifiers and readback timestamps are retained only in Knowledge.

Identifier lookup uses `cmdb_ci` plus `INSTANCEOF`; resource lookup can directly query its
requested child class. Passing identifier tests does not prove that separate resource-path
privilege. The DEV privilege record is not portable approval or a production transfer artifact.
The earlier approved `GlideSysAttachment.write / execute` debug privilege remains historical
runtime evidence, not a new broad grant.

## Separation from historical reports and final publication

Exploratory CLI trials preceded the current candidate. The first used an earlier
79-feature matrix before harness fixes. A later 85-feature trial was intentionally interrupted
at debug-success testing when the independent audit required the Closed-prior-cycle observer
correction, stricter Incident evidence prerequisites, and added Incident-default coverage.
Subsequent candidates were also stopped or retained as comparison evidence. The final exact-file
run is recorded separately above; no exploratory trial substitutes for its result. Their partial
observations are not being published as passes or conflated with runtime defects; the earlier
historical report files remain intact.

`validation-2026-10-29.2.md` records the prior corrected-runtime browser-driven retest, including
its 714.405-second duration and 204 local tests. The standalone Python file was not executed
live in that earlier report. `validation-2026-10-29-comprehensive.md` retains the preceding
failed runtime findings; `validation-2026-10-29.md` retains still-earlier evidence and limits.
None of those historical outcomes is being rewritten as a result for this new one-file suite.

The article and detailed evidence are published and reader-verified in the **same requested DEV PDI**.
Script, template and final detailed-report attachment bytes match authenticated API and reader
downloads. Public Git publication remains held for approval. Preserve the full raw failure,
supplemental result, nine incomplete families and accepted limitation in any publication;
do not publish this DEV update to another PDI.
