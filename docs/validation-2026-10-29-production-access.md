# Python suite 1.2.0 — restricted production test delivery

Scope: one standalone Python 3.9+ program, `tests/test_ci_identifier_precedence.py`,
with explicit `--access-profile production`. Connector runtime `2026.10.29.3` is unchanged.
No service, scheduler, root requirement, dedicated email notifier, security grant, property
change, production fixture provisioning, or new table is part of this delivery.

## Exact delivered program

- Suite: `1.2.0`; article source: `1.6.0`.
- SHA-256: `68db4a360ae112c223e327bc5a51f1f5bc2e77703353b42a96dc2d3bf4f5d280`.
- Production manifest: 85 feature checks. One accepted concurrency limitation is reported
  explicitly: simultaneous first events may create multiple Incidents without a claim table.
- Required transport: the existing connector POST, Event read, Alert read/write, Incident
  read/write. No direct Event-table write or administrative fallback is used.
- Configuration: private env and full-shaped reference catalog templates; these are data,
  not additional test programs. The data owner must supply this target's existing references
  and verify the nine source-fact attestations the three-table identity cannot itself read.

## Completed offline validation

416 Python regression tests and 234 JavaScript runtime/installer contracts pass: 650 checks.
The Python tests include a strict deterministic model invoking all 85 production callbacks:
84 pass plus the accepted first-event concurrency limitation. This is model coverage, not
proof that a target instance has passed all features.

The 102 production regression methods include an independent native Alert model: it derives
Alerts from Event severity/resolution rather than copying the test's expected outcome. It
reproduced the four old informational-Alert expectation failures before the correction. The
full callback model includes 102 cases, 119 connector calls, 11 negative probes, 24 formatted
note observations, three debug companions and five owned lifecycle/guard PATCHes.

Focused regressions exercise the transport boundary before authentication, required-field
visibility, raw stored reference IDs, foreign-record ownership rejection, complete fixture
validation before Event submission, blank selected URLs, per-profile Basic/OAuth settings,
failure and incomplete exit codes, stable observations, report integrity, atomic output on
Windows without `os.fchmod`, and exact owned-record formatted journal views. Five JavaScript
suites independently exercise the actual CI lookup, wrapped normalization, Salesforce status,
listener shape and explicit DEV fixture installer source.

## Live DEV validation

The final exact-file focused DEV production-transport run completed in **725.494 seconds**
with **19 PASS, one accepted concurrency limitation, zero failures, errors or skipped checks**
across 20 checks and 33 cases. Status is `complete_with_known_limitations`, exit 0. It is not
the full 85-feature acceptance run and used the approved DEV identity through the production
transport allowlist, not the actual restricted production identity. No corporate production
endpoint has been exercised.

The live selection covered populated three-table field probes, name-only and identifier-only
CI controls, identifier/name conflict and duplicate reuse, Clear/OK severities, mixed batches,
all seven parser/default subcases, eight Salesforce subcases, three debug modes, Incident/Alert
note separation and follow-up replay, terminal-state-6 replacement/reuse, foreign-Incident and
Closed-Alert guards, concurrency and final evidence integrity. Maximum recorded POST was
1.137 seconds; the minimum per-case observed stable dwell was 34.813 seconds. Eight formatted
note observations were made. The full catalog preflight was not represented by this focused
driver's populated field probes; its separate safe-stop CLI and offline coverage are noted below.

An independent subsequent GET-only check used exactly one request to each allowed table and
zero writes: **42 primary Events plus three debug companions, all Processed; 15 retained
Incidents; 25 retained Alerts**. It confirmed unchanged expected stored Event/Incident values,
current Alert links/states/CI references and 98 required-field nonblank checks on the active
expected Incidents. All records are retained. Three simultaneous first submissions returned
three Incidents, reproducing the already accepted no-claim-table race rather than certifying
concurrency safety.

The first candidate exposed a tester defect: raw Table API `work_notes` was empty even when
notes existed. That failed report is retained unchanged. The correction reads only the exact
owned Incident/Alert's formatted visible work-note field after a fresh raw ownership check.
Missing, blank, non-string or mismatched-identity responses cannot pass an absence assertion.
The final candidate has its own new keys and separate evidence; earlier failures are not
rewritten into passes.

That longer first run also exposed an incorrect inherited expectation that OK/severity-5
suppresses Alerts. It suppresses this connector's automatic DTI Incident, not native Alert
creation. Clear/severity-0 and Closing fresh-event controls retain strict no-Alert expectations.
Only the production tester's built-in expectations changed; explicit advanced-fixture
`want_alert` values are not overridden. This agrees with
[ServiceNow's documented OK/Clear behavior](https://www.servicenow.com/docs/r/it-operations-management/event-management/t_EMViewAlert.html).
Final review additionally hardened stored-string and recursive native-JSON comparisons and
complete malformed-catalog rejection before writes. No API/BR correction was required.

The normal CLI with the untouched placeholder production catalog correctly returns
INCOMPLETE/exit 4 with zero submitted Events and no PATCH. This verifies a safe configuration
stop, not functional acceptance. Independent read-only DEV readback confirms all six installed
runtime sources and Business Rule configuration match release `2026.10.29.3`; no runtime
metadata was written in this test-delivery turn.

## Evidence boundaries and release use

Production mode observes processed Events, Alert links, required Incident fields, routing,
duplicates, severity, notes, lifecycle and guards over bounded stability windows. It cannot
independently certify reference-source truth, installed BR source, complete journal history,
exact global note counts, debug attachment bytes, or a non-Incident Task baseline. The report
names these exclusions. Debug checks prove companion Event metadata/processing, not attachment
contents. Visible note presence/absence is not raw-history completeness.

The separate administrative DEV full run remains incomplete: the business-application read
privilege has not been approved, and complete default-CI controls require a real configured
prerequisite. No security or property change was made to force a passing result. Historical
raw failures and the earlier suite results remain intact.

Run one target at a time, review its JSON, then advance DEV → IT → UAT → PROD. Real test records
are retained; native notifications and Business Rules can run. Use an approved test window,
caller, CIs and configurable assignment group. POSIX output uses mode 0600; on Windows use a
user-only NTFS folder because mode bits do not establish private Windows ACLs.

## Knowledge and attachment verification

The matching DEV article 1.6.0 is published, active and latest with visible attachments.
Source-body readback matches the rendered Knowledge source, and authenticated reader inspection
confirms actual attachment links, not merely attachment-table rows. Current script, both env
templates, full fixture template, usage guide, both unchanged failed candidate reports, final
focused report, independent readback and safe-stop preflight report all downloaded byte-for-byte
through both the API and reader routes. Anonymous requests cannot retrieve the files.

Only the two independently identified obsolete script/template attachments were replaced after
verifying the new downloads; local recovery copies are retained. All historical reports remain.
The summary accompanies the same article. No documentation or attachment was published to a
different PDI during this delivery.

| Current operator artifact | Verified SHA-256 |
| --- | --- |
| `test_ci_identifier_precedence.py` | `68db4a360ae112c223e327bc5a51f1f5bc2e77703353b42a96dc2d3bf4f5d280` |
| `production_test.env.example` | `acc89290b49a84a22f4fa55520b18b5f69d331a468048197f7f5a960334c4680` |
| `production-fixtures.example.json` | `c3ae29f1fd8d06a4f51404143f38c831f7f21933ac8afcd49f4f89941b09039b` |
| `production-test-usage.md` | `01b9b337d6087818f26b00c0a9908371d1268ea21bad0d702959fe88e4ed0483` |

Only sanitized source, templates and this summary belong in the public repository. Detailed
instance/record evidence stays private and in the matching DEV Knowledge article. The public
source milestone does not certify a corporate production target or close the separate
administrative full-retest gate. No PDI backup was run or queued under the manual-only policy.
