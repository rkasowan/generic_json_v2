# Provisioned standalone comprehensive Python tester — 2026-10-29

Historical suite 1.1.0 / unpublished article 1.5.0 draft evidence. Its administrative full-run
gate remains open; references below to a frozen/current candidate apply to that recorded
milestone, not the later suite 1.2.0 production-access delivery. See
[the separately scoped production test validation](validation-2026-10-29-production-access.md).
Publishing that production tester does not convert this pending administrative full retest
into a pass. Historical outcomes and hashes below are retained unchanged.

This is a sanitized public summary. Instance hostnames, record identifiers, fixture values,
precise execution timestamps and detailed machine evidence belong only in the matching DEV
Knowledge attachments or ignored private local evidence, not public Git. The owner authorized
publication of reviewed source/templates and this sanitized summary at coherent completion.

## Verdict

**BLOCKED / FULL RETEST PENDING: the exact DEV business-application read privilege still needs
approval. Focused guards pass; no complete new-suite PASS is claimed.**

The missing approval is for the application scope's exact requested `cmdb_ci_business_app / read`
operation in the approved DEV PDI. Its final readback remains `requested`; it is not granted by
fixture setup. Approval must precede the CAR-ID positive retest and a new clean full CLI run.
Knowledge 1.5.0 and authorized sanitized Git delivery await those results. No full CLI acceptance
run has started, and no runtime/Knowledge/Git write was made by the latest guard validation.

Runtime release `2026.10.29.3` is unchanged. Fresh readback confirms all six deployed source
strings and BR configuration still match. Article source version is `1.5.0`. The previous article `1.4.0` and suite
`1.0.0` results are historical evidence, not proof of this provisioned suite's outcome.

| Final execution fact | Result |
|---|---|
| Exact script SHA-256 / suite version | Current frozen candidate `a01958b88f3c1b9ff716ef6c78ca0ca868f69bc558057240c5df7e48fb46c04e` / 1.1.0; focused guards PASS, full execution blocked/PENDING |
| Runtime / article source version | 2026.10.29.3 unchanged / 1.5.0 |
| Setup target / identity / confirmation | Approved DEV PDI, explicit exact-target-confirmed Basic-admin preparation completed; final frozen-file full execution PENDING |
| Setup field/data inventory and idempotent readback | Current bounded prepare/readback PASS: zero Events/new fields; captured fields, IDs and audit versions unchanged for seven CIs, three users, group and Task. A separate broad-interval comparison failed on three CI audit versions after linked asset follow-ons; no all-test immutability claim |
| Temporary-property original-state journal / restoration / recovery verification | Actual earlier-candidate crash recovery PASS: original absence restored; repeat/stale-active recovery made zero writes. Full-run lease/restoration on the final candidate PENDING |
| Current exact-file focused guard result | All three guards and final evidence integrity **PASS**, **338.716 seconds**; no full-run acceptance claim |
| Remaining security prerequisite / property state | Exact business-app scoped read request still `requested`; default-CI property independently confirmed absent |
| Actual complete feature/case outcomes and elapsed duration | PENDING; derive from final machine report |
| Machine status / process exit | PENDING |
| Retained Event / Alert / Incident counts and independent audit | PENDING; aggregate only in public summary |
| Offline regressions / syntax / safety checks | **548 offline checks PASS** for the current candidate, including neutralized offline hostname fixtures. Offline checks are not live acceptance |
| Knowledge publication and authenticated attachment verification | PENDING new article/test/report publication; preserve prior evidence |
| Sanitized public Git publication | Authorized; PENDING coherent completion |

## One-file contract and opt-in boundaries

The canonical executable remains `tests/test_ci_identifier_precedence.py`, using stock Python
3.9+ and no other project imports. There is no Linux service, scheduler, root requirement,
monitoring-email configuration, default legacy wait key, or claim table. Env and fixture JSON
are configuration, not additional test programs.

Ordinary Basic/OAuth test mode uses existing approved fixtures. It reads actual Events,
Incidents, Alerts, journals, attachments and needed reference metadata, and only allowlisted
updates to this run's owned Incidents/Alerts exercise lifecycle/ownership. It does not provision
schema, reference data, privileges or system properties.

The separate `--provision-dev-fixtures` mode requires `--confirm-fixture-target` matching the
exact selected HTTPS PDI origin on a `dev<digits>.service-now.com` host and Basic-auth
administrative access. Its narrow Global background setup is embedded in the same Python file.
`--plan` remains read-only and describes conditional setup writes. No other installer file is
required; production targets must use approved preexisting schema/data, not this DEV setup.
`--prepare-fixtures-only` with setup performs preparation/readback without submitting Events.
`--fixture-output` selects the private 0600 target-bound catalog. Common env baseline CI/caller/group
inputs plus marked fixture data generate the catalog; no external fixture JSON is needed for setup.
The configured group must already have an active unique-name member for assignee controls, and
the connector's existing default-caller property must be valid. Neither is modified by setup.

## Authorized setup inventory

Setup may add only these five required customer fields, in Global schema to preserve the
existing runtime's `u_*` names. Runtime Script Includes remain in `x_usbna_usb_event`.

| Required schema | Type / purpose |
|---|---|
| `cmdb_ci_business_app.u_car_id` | String(100); positive CAR-ID lookup |
| `cmdb_ci.u_level_2_support_assignee_group` | Reference to `sys_user_group`(32); base-CI L2 fallback |
| `incident.u_usb_em_test_value` | String(255); real customer-field passthrough |
| `incident.u_netcool_ticket` | Boolean; actual default readback |
| `incident.u_generating_alert` | Reference to `em_alert`; actual Alert back-reference |

Existing compatible fields are reused. Type/reference mismatches are not overwritten, and
schema provisioning/readback must be verified before testing. Persistent field and fixture
records are retained and inventoried, not silently deleted. No `em_alert.task` column or
claim table is created. Missing roles, ACLs or cross-scope privileges remain blockers; none are
automatically granted.

Reference data is marked test-owned with stable ownership/source keys. No existing real CI,
group, user, service, offering or Task may be adopted or modified merely because its name
matches. Duplicate/colliding matches stop setup. Allowed positive fixtures cover a business app
with CAR ID, an L2 CI with blank primary support group, two parent services and a parented
offering, a dedicated support group, three locked-out web-service-only role-free email-blank
users (including two sharing one generated display name), and a marked non-Incident base Task.
Created users are not test login identities. No roles or operational group memberships are granted.

CI/service/offering ingestion uses IRE rather than direct CMDB inserts. Individual returned
item outcomes, exact identity/class and stored fields must be checked; HTTP success is not
proof of successful or correctly owned ingestion. Setup idempotence and no-unrelated-write
evidence for the final frozen-file execution remain PENDING until that full run is reviewed.

## Completed preparation evidence — not full-suite acceptance

The initial administrative setup request exceeded its then-90-second HTTP observation budget.
Its result was unknown, not presumed rolled back or safe to blindly repeat. The error report is
preserved. No automatic POST retry occurred. Independent GET readback found all five logical
fields, seven owned CMDB records, three locked-out web-service-only role-free users, one owned
group and one marked base Task. The six dictionary rows seen across the inspected tables include
an inherited L2-field entry; that is not a sixth logical custom field.

After readback, an explicit idempotent preparation rerun used a 300-second administrative HTTP
budget and returned preparation PASS with no newly created dictionary fields. Independent
readback confirmed all seven CI, three user, group and Task identities, modification counters
and update timestamps unchanged across that early preparation-rerun interval. Only captured fields
are covered, not all possible business fields or all later platform activity. A private target-bound catalog was generated
from common env inputs without an external fixture JSON. Preparation submitted no test Events.
The owned service-association ID and fields were reused/read back; its original modification
version was not separately captured, so unchanged association versions are not claimed.

This establishes installed fixture preparation and observed idempotent reuse, not API/BR feature
acceptance. Focused checks and a full run of the final frozen suite, property restoration,
independent final evidence, attachments and publication remain PENDING. No runtime `.3` source
change is part of fixture preparation, and prior raw reports remain untouched.

A later broad comparison from the original baseline through subsequent testing **failed for
three of seven CIs**: modification counters changed from zero to one and update timestamps
advanced; the other nine of twelve compared CI/user/group/Task rows were unchanged in the
captured fields. The failed operator assertion and raw readback evidence are preserved. Those
broad baseline CI snapshots captured identity/name/class and audit metadata, not every business
field. Separate audit history identifies `asset` and `model_id` changes, and Asset readback
confirms three linked hardware assets referencing a pre-existing model. The follow-ons occurred
outside the later bounded installer window. Native automation is a plausible inference, but
the specific job/actor was not established; definitive attribution is not claimed.

A fresh tight before/stock-prepare/after comparison then **passed**: all twelve rows retained
their captured fields, IDs, modification counters and timestamps, with **zero new dictionary
fields and zero test Events**. This proves observed installer-rerun idempotence in that bounded
interval, not fixture immutability through all tests. The three linked hardware assets are
retained and inventoried; no asset/model cleanup, deletion, model mutation or security change
was performed. Original failed broad-interval evidence remains intact alongside the passing
bounded comparison.

### Focused preflight findings — retained failed evidence

A focused preflight completed in **435.111 seconds**, with **17 passing feature checks and two
failures**. The CAR-ID positive lookup generated a narrowly requested scoped read privilege for
`cmdb_ci_business_app`; approval is pending. The runner does not automatically grant it. The
other failure was the foreign-Task Alert-note assertion. Its direct Alert additional-info PATCH
was silently ignored by the target's existing field ACL, so HTTP success did not prove that the
metadata needed to trigger the note was stored. The failed raw report is retained, not rewritten.

The installed runtime already processes the Alert note before its foreign-link guard; no API/BR
code change is established by this finding. The harness is being corrected to replay a normal
connector Event carrying `alert_work_notes`, respecting the supported ingestion path rather than
depending on that blocked direct metadata write. Foreign-Task, foreign-Incident and Closed-Alert
guards, plus CAR-ID after approval, required fresh focused readback before the full acceptance run.
The later guard retest below now supplies that guard evidence; CAR-ID and the full outcome remain pending.

A subsequent three-guard preflight completed in **292.026 seconds**. The Closed-Alert guard,
foreign-Task guard and final evidence-integrity check passed, but the foreign-Incident guard
failed: its DTI replay legitimately returned the Alert's existing foreign Incident under the
API's authoritative-link behavior. An initial assertion was masked by the later Event count,
so both the original failure and its diagnosis are preserved rather than reclassified as PASS.
This was not evidence of an API/BR regression.

The current frozen candidate isolates the BR guards using **non-DTI** connector replays with
unique `alert_work_notes`. Those replay responses must not return an Incident, while the original
owned case's Incident expectations remain intact. Normal DTI API assertions are not relaxed;
existing linked foreign-Incident authority remains part of that separate runtime behavior.
The Closed guard uses the Closed-state/blank-link update with already-stored DTI metadata and
makes no new journal assertion.

The exact-file three-guard retest has now **passed all three guards and final evidence integrity
in 338.716 seconds**. Observed feature durations were 135.749 seconds for the foreign-Incident
guard, 76.003 for Closed Alert, 87.747 for foreign Task and 0.360 for final evidence integrity;
the total also includes setup/control overhead. Actual readback verified the unique Alert note,
no extra Incident copies and an unchanged foreign Task baseline.

Final GET readback still shows the CAR-ID scoped read request as `requested` and the default-CI
property absent. Release remains **blocked on that exact DEV read approval**. After approval,
CAR-ID must pass and the clean full CLI, independent audit, Knowledge/attachment replacement
and authorized sanitized Git publication must still complete. No full CLI acceptance run has
started; focused guard success is not substituted for that missing full execution.

## Supported foreign-Task guard

The existing DEV dictionary's internal `em_alert.incident` field references `task`; its UI
meaning is the Alert's Task, not only an Incident. `em_alert.task` is absent and unnecessary.
The current API/BR already conditionally refuses to replace a nonempty foreign Task link.
The updated tester uses the actual supported reference field, replays a non-DTI connector Event
carrying an owned Alert note to isolate the installed BR, verifies the foreign link survives,
and compares the referenced Task's
baseline unchanged. Only setup may create the marked fixture; the actual guard never writes it.

## Temporary default-CI property and recovery

An existing valid default CI is reused without property writes. Otherwise
`--allow-default-ci-property` is a separate opt-in for only
`x_usbna_usb_event.default_cmdb_ci_sys_id`, during the three non-DTI default/dummy controls:
unresolved hints use the real configured default; explicit unresolved CI suppresses it; and no
CI hints leave CI blank.

Before mutation, a private 0600 journal selected by `--fixture-recovery-file` records exact
original row/value or absence. Guarded `finally` restoration must restore and read back that
state in the database and effective property cache. If originally absent,
only the exact setup-created row may be removed to restore absence. A concurrent external
change must not be overwritten. A stopped process can bypass `finally`, so recovery from the
journal is required before another run. Restoration/recovery failure is an error/nonzero,
not a passing feature. Use a fresh journal path for each lease.

Real interrupted-process recovery was exercised on the preceding candidate: an owned child
process was stopped with `SIGKILL` after temporary activation, then the actual connection-only
recovery CLI restored the property's original absence. Repeating recovery and recovering a
stale active journal after restoration both made **zero writes**. Those results are preserved
separately from the current candidate's full-run lease/restoration, which remains PENDING.

```bash
python3 tests/test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --prepare-fixtures-only --fixture-output dti-reference-fixtures.json --report-file dti-setup-report.json
python3 tests/test_ci_identifier_precedence.py --provision-dev-fixtures --confirm-fixture-target https://dev123456.service-now.com --allow-default-ci-property --fixture-output dti-reference-fixtures.json --fixture-recovery-file dti-default-ci-recovery.json --report-file dti-report.json
python3 tests/test_ci_identifier_precedence.py --restore-fixture-default-ci dti-default-ci-recovery.json --confirm-fixture-target https://dev123456.service-now.com --report-file dti-recovery-report.json
```

Replace the example origin with the exact selected DEV PDI. Recovery is a separate connection-only
mode requiring no CI/caller/group fixtures and cannot be combined with provisioning flags.
A prepared catalog alone cannot certify a positive missing-default branch under a subsequent
normal restricted-account run; the temporary lease requires the administrative full-run opt-ins.
Prefer an existing ignored private directory such as `.local-evidence/` for every catalog,
journal and machine report; arbitrary output names are not automatically public-safe or ignored.

The property is shared by unrelated unhinted events during its brief temporary setting. Use
only the approved DEV maintenance window, not concurrent real integration traffic. Other
properties are unchanged; caller/group/default fixtures must not silently reconfigure runtime.

## Acceptance and safety

The same complete current API-and-BR manifest must run after setup. It must prove all seven
required stored Incident fields, correct class-scoped CI precedence, group assignment,
correlation, prompt no-wait response, Event processing, real Alert linkage, duplicates,
wrappers/batches/errors/aliases/defaults/Salesforce, routing, notes, debug downloads, lifecycle
and ownership. Missing fixtures/evidence/privileges cannot be relabeled PASS. Actual feature
counts/statuses come from the final frozen-file report, not a pre-promised count.

The known simultaneous-first-event race remains owner-accepted and is always exercised. No
claim table is added and no finite non-racing trial proves concurrency safety. A complete run
with this limitation can be `complete_with_known_limitations`, not unqualified safety.

A comprehensive execution retains many Events/Alerts/Incidents and runs native Business Rules
and notifications; mail is not suppressed. Review target, caller/group and identity before
running. Setup extends writes only through its explicit field/table/ownership allowlists.
No unrelated records or permissions may be changed. No production or restricted production
identity is certified by this administrative DEV fixture execution.

Choice expectations remain stored-value contracts, not target taxonomy certification. The
runtime's declared parity defaults must not be guessed from display labels. Explicit production
stored choice values are preferred; seven filled fields alone do not certify valid taxonomy.

## Preserved prior outcomes

The prior suite 1.0.0 full report remains raw `fail`/exit 2: 75 pass, one assistant-fixture
failure, nine skips and one known limitation, zero errors, 93 cases and 1749.514 seconds.
Its same-file corrected-fixture defaults supplement separately passed two cases in 44.619
seconds. The prior independent audit verified 122 Processed Events, 84 Alerts and 72 Incidents.
Those results are not rewritten or retroactively upgraded by adding setup.

See `validation-2026-10-29-python-comprehensive.md` for that preserved sanitized summary, and
the three earlier runtime reports for still-earlier evidence. Detailed raw JSON remains in the
matching DEV KB. The new suite needs its own frozen script hash, setup/restoration readbacks,
full result and independent evidence before publication or a completion claim.
