# Restricted production acceptance

On POSIX systems generated output files use mode 0600. On Windows, keep credentials, catalogs and reports in a user-only NTFS folder; POSIX mode bits cannot set Windows ACL privacy. Atomic output still works when Python does not expose `os.fchmod`.

Suite 1.2.0 of the same standalone `test_ci_identifier_precedence.py` has an explicit `--access-profile production` mode; runtime 2026.10.29.3 is unchanged. It exercises the connector and its actual Event → Alert → Incident outcomes using only the existing connector POST plus Event read, Alert read/write, and Incident read/write. It never switches to an admin identity or requests extra table access.

Use the attached `production_test.env.example` and full-shaped `production-fixtures.example.json` as private configuration templates. Replace every `REPLACE_WITH_...` token with this target's real value; repeated tokens identify the same object. The JSON intentionally contains invalid IDs and false attestations, so it is not a ready-to-run catalog. The current identity cannot discover those reference facts from CMDB/user/property tables: have the responsible owner supply existing target values, then affirm each verified source fact. No additional permission is requested, and no production fixture is provisioned. The catalog is data, not another test program.

Python 3.9 or newer is sufficient; there are no third-party package dependencies. A normal run creates real retained test Incidents/Alerts and may trigger normal notifications/email, outage rules and other Business Rules; those native effects are not suppressed. Agree on test CIs, caller, assignment group, and a testing window before running. The configurable assignment group is `USBEM_ASSIGNMENT_GROUP`, with the independently known `USBEM_EXPECTED_ASSIGNMENT_GROUP_SYS_ID` as the stored-value expectation. Complete static-catalog validation and populated required-field probes must pass before the first test Event.

Inspect the plan without credentials or network access:

```bash
python3 test_ci_identifier_precedence.py --access-profile production --plan
```

Configure one target directly, or reuse the existing environment profile pattern. Each invocation selects exactly one target; an explicitly selected blank URL stops before network access. Blank, unselected environment URLs are ignored. A shared Basic username can be combined with a different password for each profile; existing per-profile OAuth client credentials also work. Base64 is reversible encoding, not hashing or encryption.

```bash
python3 test_ci_identifier_precedence.py --access-profile production --env-file production_test.env --profile DEV --fixture dev-fixtures.json --report-file dev-report.json
python3 test_ci_identifier_precedence.py --access-profile production --env-file production_test.env --profile IT --fixture it-fixtures.json --report-file it-report.json
python3 test_ci_identifier_precedence.py --access-profile production --env-file production_test.env --profile UAT --fixture uat-fixtures.json --report-file uat-report.json
python3 test_ci_identifier_precedence.py --access-profile production --env-file production_test.env --profile PROD --fixture prod-fixtures.json --report-file prod-report.json
```

Run the next command only after reviewing the previous target's report. These are four separate acceptance runs, not a scheduler or automatic multi-instance rollout. All filled environment files, catalogs, journals and detailed reports must remain private. Do not put credentials in shell arguments or copy PDI record IDs to another target.

## Coverage and exact evidence boundary

The production manifest exercises fast no-wait DTI, all seven required Incident fields, CI identifier/type precedence and fallback paths, wrappers and batch shapes, invalid inputs, severity and suppression, duplicate reuse, long-key correlation, routing/reference results, Salesforce mappings, Incident field defaults and custom fields, note delivery, terminal Incident replacement, foreign-Incident and closed-Alert guards, debug companion Events, and the accepted parallel-first-event race. It observes actual stored Events, Alerts and Incidents over continuous bounded stability windows, not merely successful HTTP responses. Any missing fixture, denied operation, or hidden required field prevents complete acceptance.

These rights are enough for top-to-bottom **observable functional validation**, but not every form of administrative proof:

| What is observed | What the restricted identity cannot independently certify |
| --- | --- |
| Exact stored reference IDs on the owned Event/Alert/Incident | CMDB/user/group/service catalog truth, property values, canonical-name uniqueness, or offering-parent relationships |
| Sentinel presence/absence within the exact owned record's formatted visible work notes, plus consumed pending-note metadata | Complete raw journal history, exact global occurrence counts or ACL-hidden entries |
| Debug companion Event metadata and processed state | Attachment filenames, complete attachment set, or downloaded debug bytes |
| Actual Alert-to-Incident link convergence and guard outcomes | Installed Business Rule source/configuration |
| Foreign link guard using two Incidents created by this run | A protected non-Incident Task baseline; that guard is outside production mode |

For the first row, supply the existing target-specific reference catalog used by the ordinary tester, with independently known expected IDs. The catalog additionally uses `production_attestations` JSON booleans for the unobservable source facts of canonical CI/group names, L2 and primary support groups, CAR-ID mapping, CI/service inference, offering-parent filtering, default-CI policy, and ambiguous user names. Set an attestation only after the responsible data owner verifies that prerequisite; it is not an automated proof of that fact. Stored results still must match independent expected values. Default-CI controls require explicit `default_ci_sys_id` plus the three positive/negative cases; production mode never changes the property. Missing target fixtures are reported incomplete rather than synthesized in production.

Raw `work_notes` journal-input reads can be blank. The tester first verifies current-run ownership using raw fields, then reads only `sys_id,work_notes` from that exact owned Incident/Alert with formatted display enabled. Sentinel assertions apply only to the visible formatted view, not complete raw history or exact global counts. A blank/missing formatted view makes even a negative assertion INCOMPLETE; it cannot silently pass as note absence.

Production mode does not read CMDB, users, groups, properties, dictionary, journal, attachment, or Task tables. It never creates schema, fixtures, users, privileges, or properties, never runs Scripts - Background, and never deletes records or updates existing operational tickets. Lifecycle and ownership cases use a fresh ownership read before PATCH and can update only the current run's tagged Incidents and Alerts. It never writes the Event table directly. There is no Linux service, root process, scheduler, dedicated email notifier, or normal wait key.

The template's `severity_map` is the release's default mapping, not an assertion that your target has unchanged property overrides. Confirm it, the literal stored default category/subcategory values, duplicate-note policy, valid closure choice, and the Alert Closed state. `terminal_extra_fields` may be empty or contain only a nonempty `u_cause` string if the target requires that field. Replace the custom-field placeholder in both the payload and expected result with an existing approved Incident field. An offering-positive service and a different, valid negative-control service are both required. The CI-support group must differ from the explicitly supplied baseline test group so the override test proves real precedence.

Production `expected_incident` / `expected_event` values must be stored-value strings, including `"0"`, `"false"` and `""`, not interchangeable JSON numbers, booleans or null. User `additional_info` expectations preserve native JSON types and use type-strict recursive comparison. Malformed catalogs stop preflight before Event writes; malformed raw stored response types do not pass through truthy/falsy coercion.

Native OK/severity 5 can create an Alert; Clear/severity 0 instead closes matching Alerts and creates no fresh Alert. See [ServiceNow: View alert information](https://www.servicenow.com/docs/r/it-operations-management/event-management/t_EMViewAlert.html). The connector suppresses an automatic DTI Incident for severity 5, not its native Alert. Fresh Clear/Closing cases expect no Alert, and the production tests distinguish these outcomes.

The accepted first-event race remains: simultaneous first events may create multiple Incidents because no unique-claim table was authorized. A single non-racing test does not prove concurrency safety. Production-local business rules, field ACLs, valid stored choices, and required closure fields must be tested with the actual production identity; DEV results are not a substitute.
