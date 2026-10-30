# Run the DTI test

Python suite 1.3.0 runs without flags or options. Use Python 3.9 or newer; no packages need installing.

1. Put the updated `test_ci_identifier_precedence.py`, `production_test.env`, and your already-filled `dev-fixtures.json` together in one private folder. Keep your filled files; do not replace them with the example templates.
2. Open Terminal or PowerShell in that folder and run:

   ```bash
   python test_ci_identifier_precedence.py
   ```

   If your computer calls Python `python3` or `py -3`, use that command instead.
3. Read the final on-screen summary. The detailed `dti-results-....json` file is saved automatically in that folder. Allow many minutes; the test waits for actual Event processing, Alert links and stable results.

There is no command-line configuration to assemble. The test reads only the two files beside the script, not another working directory's files or inherited shell credentials. It uses the nonblank `USBEM_DEV_URL` from `production_test.env`, otherwise its `SN_INSTANCE_URL`, and displays the one selected target. It never advances automatically to IT, UAT or PROD. Existing plain/base64 Basic credentials and OAuth settings still work; base64 is reversible encoding, not hashing or encryption. Assignment uses the existing `USBEM_ASSIGNMENT_GROUP` and expected group ID settings, without editing Python.

Baseline CI, caller, required-field and assignment settings must be valid. Missing optional advanced fixture data no longer prevents the ordinary checks from running: all 85 manifest entries remain in the report, and unavailable features are explicitly INCOMPLETE, not PASS. Fix the named data when you need complete acceptance; do not change owner attestations to true without verifying them. Malformed JSON, unsafe baseline configuration or failed baseline controls stop safely with an actionable explanation.

The run creates real retained test Incidents/Alerts and can trigger normal notifications/email, outage rules and other Business Rules. Use approved test CIs, caller, assignment group and testing window. No service, root access, scheduler or separate email notifier is installed.

Keep configuration and results private. On POSIX systems generated outputs use mode 0600; on Windows use a user-only NTFS folder because POSIX mode bits cannot set Windows ACL privacy. Do not put credentials in shell arguments or copy one target's record IDs into another target's fixtures.

Suite 1.3.0 changes only the laptop entry point, fixture handling and reporting; runtime 2026.10.29.3 is unchanged. It still uses only existing connector POST plus Event read, Alert read/write and Incident read/write, with no administrator fallback. Advanced developer flags remain supported for compatibility but are unnecessary for this laptop workflow. Updated-version offline validation passes 446 Python plus 234 JavaScript checks (680 total), including 30 new laptop-entry tests. Program SHA-256: `c39760011c871a659ae40e2c5cc03ca592f4b702d93439d1acd01739298748ab`.

Focused DEV invocation proof completed in 132.586 seconds: five checks passed and two intentionally unavailable optional features were skipped, correctly returning INCOMPLETE/exit 4 while unrelated CI/duplicate checks continued. Fresh GET-only readback verified four Processed Events, three Incidents, three Alerts and 21 required-field checks. This exercised the actual no-argument path through a private focused dispatch with the DEV connection injected in memory; sidecar parsing was tested offline. It is not all-85 live acceptance or actual restricted production-identity proof. Article 1.7.0 is published and reader-verified in matching dev392825, with exact source-body readback and actual script/configuration/usage links. The canonical program and focused evidence pass authenticated API/reader byte checks; anonymous downloads are blocked. Previous script/usage attachments are replaced recoverably, and historical reports remain. See [one-command validation](validation-2026-10-29-one-command.md); suite 1.2.0 evidence remains historical, not verification of these updated bytes.

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

Production `expected_incident` / `expected_event` values must be stored-value strings, including `"0"`, `"false"` and `""`, not interchangeable JSON numbers, booleans or null. User `additional_info` expectations preserve native JSON types and use type-strict recursive comparison. Invalid optional fixture families are reported incomplete rather than blocking unrelated tests; malformed JSON or unsafe baseline configuration stops before Event writes. Malformed raw stored response types do not pass through truthy/falsy coercion.

Native OK/severity 5 can create an Alert; Clear/severity 0 instead closes matching Alerts and creates no fresh Alert. See [ServiceNow: View alert information](https://www.servicenow.com/docs/r/it-operations-management/event-management/t_EMViewAlert.html). The connector suppresses an automatic DTI Incident for severity 5, not its native Alert. Fresh Clear/Closing cases expect no Alert, and the production tests distinguish these outcomes.

The accepted first-event race remains: simultaneous first events may create multiple Incidents because no unique-claim table was authorized. A single non-racing test does not prove concurrency safety. Production-local business rules, field ACLs, valid stored choices, and required closure fields must be tested with the actual production identity; DEV results are not a substitute.
