# One-command laptop test validation — October 29, 2026

Python suite: `1.3.0`. Knowledge article source: `1.7.0`.
Connector/API/Business Rule runtime remains `2026.10.29.3`.

Exact standalone program SHA-256:
`c39760011c871a659ae40e2c5cc03ca592f4b702d93439d1acd01739298748ab`.

## Operator contract

Keep the existing filled `production_test.env` and `dev-fixtures.json` beside the
updated `test_ci_identifier_precedence.py`. Run only:

```bash
python test_ci_identifier_precedence.py
```

No flags, pip installation, additional Python program, or replacement of filled
configuration files is required. The program prints the selected target, progress
and a readable final summary, and automatically saves a private, uniquely named
`dti-results-*.json` beside itself. It selects nonblank `USBEM_DEV_URL`, otherwise
`SN_INSTANCE_URL`, from that file only; it never advances to another environment
or inherits shell connection settings. It accepts UTF-8 BOM files and the prior
`dev-fixutres.json` typo only when the correctly named fixture file is absent.

All 85 manifest entries remain. Missing or malformed optional prerequisites affect
their own checks, not unrelated baseline checks. Any skipped feature produces
INCOMPLETE, never PASS. Invalid baseline configuration or CI controls stop writes.
An interrupted run's initial `running` report cannot be mistaken for a passing run.

## Offline verification

- 446 Python tests passed in 42.223 seconds, including 30 laptop-entry tests.
- 234 JavaScript contract cases passed: CI 26, wrappers 74, Salesforce 66,
  listener shapes 39, fixture installer 29. Total: 680 passing checks.
- The laptop runner exercised all 85 actual callbacks against the strict native
  Alert model: 84 PASS and one accepted concurrent-first-event limitation. This is
  modeled behavior, not a full live acceptance run.
- Partial/placeholder catalogs, hidden optional fields, invalid advanced controls,
  absent attestations, malformed lifecycle extras and missing optional references
  cannot silently pass or emit placeholder fixture values.
- Tests cover script-directory versus working-directory lookup, no shell override,
  one-target selection, safe setup failures before authentication, malformed JSON,
  unique reports, unwritable output directories, interruption, BOM handling,
  Windows without `fchmod`, and a copied standalone program without repo imports.
- An independent final source review found no blocking issue. Transport remains
  connector POST plus Event GET and owned Alert/Incident GET/PATCH only. No
  administrator fallback, reference-table reads, schema/security/property changes,
  provisioning, deletion, service, root requirement or dedicated notifier was added.

## Focused live DEV verification

The exact-file focused DEV invocation proof completed in 132.586 seconds. It
selected seven checks over three CI cases: five PASS, zero failures/errors, and
two deliberately unavailable optional checks. Correct aggregate: INCOMPLETE,
exit 4. Name-only and identifier-only positive controls, conflicting camelCase CI
identifiers, duplicate reuse, baseline field visibility and final evidence checks
passed. A nonexistent optional custom field and absent CAR-ID fixture each skipped
only its own check before sending its Event; unrelated checks continued.

The focused run used four connector POSTs, 45 Alert GETs, 47 Event GETs and 46
Incident GETs, with zero PATCH operations. Maximum POST: 0.870 seconds. Minimum
continuous case stability observation: 30.011 seconds. A separate fresh GET-only
audit made three queries and zero writes: four retained Events all Processed,
three Incidents, three Alerts, and 21 required-field checks. Expected CI binding,
assignment, caller, all seven required fields, correlation and Alert links remained
unchanged.

Qualification: this private validation harness selected the seven callbacks and
injected the approved DEV connection in memory through the actual no-argument
`main()` entry. Standalone sidecar parsing and complete dispatch are covered
offline. This is not a live run of all 85 manifest entries, the operator's filled
laptop files, an actual corporate production instance or a restricted production
identity. An initial harness attempt could not serialize its internal set-shaped
case snapshots; its `running` report remains private and is not claimed as a pass.
Only the private harness serialization was corrected; distributed program bytes
did not change between those attempts.

## Evidence and delivery

Detailed record-level reports remain private to ignored local evidence and the
matching DEV Knowledge article. Public source and this summary contain no filled
fixtures, credentials or run-specific record identifiers. Historical suite 1.2.0
reports remain unchanged and are not presented as validation of these new bytes.

The accepted simultaneous-first-event duplicate Incident race remains. No unique
claim table was authorized. This update does not certify installed source, ACLs,
properties, reference-data ownership, raw journal history or debug attachments
using a restricted three-table production account.

Article 1.7.0 is published, active and latest on matching dev392825 KB0010015,
with attachment display enabled. Exact normalized source-body readback and the
authenticated reader's actual download links were verified. The updated program
and detailed evidence downloads were byte-verified through authenticated API and
reader requests; unauthenticated requests did not return those files. Obsolete
script/usage copies are replaced only after exact identity, hash and recovery-copy
checks; historical reports and filled configuration remain unchanged.

The sanitized source, templates and this summary form the public repository
milestone. Detailed record-level evidence is excluded from that publication.
