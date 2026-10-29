# generic_json_v2 — project notes

Compact working state for the USBEM genericJsonV2 push connector. Detailed behaviour lives in
`README.md` and `docs/`; this file is what a future session needs before touching the PDI.

## Documentation target correction (2026-10-29)

- Owner explicitly requires implementation and all documentation/KB/attachments in the same
  named PDI. Do not let a default shared connection or older KB override the requested target.
  This durable preference is also in root AGENTS.md and the compact root notes index.
- Correct DTI article: **KB0010015 on dev392825**, sys_id
  `7433ede097d457105fb3ba6de053af9b`, IT base `a7e8a78bff0221009b20ffffffffff17`, Global.
  Article1.3.0 / runtime2026.10.29.2, active/latest/published, exact body readback passed.
  `display_attachments=true` was explicitly set and read back; without it, this target defaults
  false and hides attached downloads in the reader UI. All five links now render in kb_view.
- All five DEV attachments downloaded and SHA-256 matched repository bytes: Python
  `f343e92497d457105fb3ba6de053aff4` (40089 bytes), env template
  `c4532d2497d457105fb3ba6de053af57` (4538), current `.2` report
  `14532d2497d457105fb3ba6de053af5d` (15212), original extended report
  `50532d2497d457105fb3ba6de053af63` (8673), historical comprehensive failure report
  `6c532d2497d457105fb3ba6de053afd8` (14283). Hashes are unchanged from their source files.
  The five actual reader-facing `sys_attachment.do` links also returned exact matching bytes,
  not just the Table API downloads; the published reader page renders all five links.
- Original dev382837 KB0010025 and its attachments were left unchanged, not deleted.
  No runtime, security, or test records changed during this documentation correction.
- KB publisher now requires an explicit expected HTTPS origin and rejects connection/target
  mismatches before any network call. Do not point it at default credentials and assume it
  selected DEV. This DEV publication used the existing authorized browser session; it did not
  change the shared .env or copy credentials between instances.
- Guard/visibility validation: 12 focused offline tests pass; full Python discovery passes
  77 tests, with changed-file syntax and git diff checks clean. Connector/runtime source and
  the earlier 204-test release evidence remain unchanged by this documentation-only correction.

## Release 2026.10.29.2 (2026-10-29)

- Corrected-path DEV retest PASS, not a universal production/concurrency guarantee. See
  `docs/validation-2026-10-29.2.md`: 714.405 seconds (14:07:06.208–14:19:00.613 UTC),
  47 main cases + three terminal lifecycles + ten negative payload probes; 280 functional
  assertions, no unresolved failures, 69 prefixed processed Events + one debug companion,
  44 Incidents and 48 Alerts. Two 15-sample stability windows were clean.
- User approved all five corrections: wrapped Incident passthrough/AI+envelope precedence,
  full shape preflight, installer Advanced/readback, follow-up Alert note condition, and the
  exact DEV `GlideSysAttachment.write/execute` privilege. No table, service, scheduler, or
  monitoring email was added. The accepted concurrent-first-event race is unchanged.
- All six dev392825 sources match local `.2` SHA-256 and BR configuration. Record IDs:
  Core `4312b4e0975c17105fb3ba6de053afa6`, Lookups `5312b4e0975c17105fb3ba6de053afaf`,
  Debug `d31278e0975c17105fb3ba6de053af92`, DTI `9b1278e0975c17105fb3ba6de053af97`,
  listener `ab1278e0975c17105fb3ba6de053afa9`, BR `631278e0975c17105fb3ba6de053afb4`.
  Scope remains `96abfcbb97774b105fb3ba6de053afa6` / `x_usbna_usb_event` (enforcing);
  listener/BR remain Global. Advanced=true, after insert/update, order150, not async.
- Only privilege `9dde38ac97dc17105fb3ba6de053afce` was changed requested→allowed,
  target `GlideSysAttachment.write`, execute. Nine success JSON artifacts downloaded and
  parsed; `10_error_context.json` is conditional, not a required success attachment.
- Initial Incident `INC0010066` existed while no Alert existed, returned in 1258ms, and later
  linked to Alert0010108. Replays preserve required fields and reuse it. New unique follow-up
  Alert note journaled exactly once; two no-note updates did not repeat it. All five wrappers
  preserve required fields and Incident work notes. Lifecycle replacements: INC0010104→105
  (resolved), INC0010106→107 (closed), INC0010108→109 (canceled), correct new Alert links.
- Local validation: 65 Python + 26 CI + 39 listener-shape + 74 wrapper checks = 204 passing.
  Laptop default is ten cases/twelve Events/ten Incidents/twelve stable phases (>=6 minutes).
  It reads only Event+Incident, so it does not itself prove the BR link. No actual production
  or restricted/OAuth identity run was performed; the live matrix used authorized browser HTTP.
- Knowledge article1.3.0 is published on existing dev382837 KB0010025
  (`3c617cbc9353c7d0c8ebf85bdd03d643`); title/body match source and active/latest/published
  readback passed. New attachments download byte-for-byte: Python `8baa0d2093945b90c8ebf85bdd03d612`
  (40089 bytes, SHA256 `2c8075d602e5a383a9a39613f4b09d0b2dbd18ba2fe4f0ae51a75906fa1a5f71`),
  template `88ba0d2093945b90c8ebf85bdd03d6c8` (4538 bytes, SHA256
  `38f214408e763fea22a423f96e1320d0e29ed56d88586d8617ed0d1778d4009b`), report
  `3cbacde8939c1b90c8ebf85bdd03d6f2` (15212 bytes, SHA256
  `8e0b8f922d9fd477d4ed958f1faed1e6acb5bc227cd0fa07cd205a51fe848d58`). Only the two
  exact known obsolete Python/template attachment copies were removed after replacement
  verification; they are recoverable from Git. Both historical reports remain attached.

## Release 2026.10.29.1 (2026-10-29)

- Comprehensive follow-up gate is HOLD, not a clean pass. See
  `docs/validation-2026-10-29-comprehensive.md`: 744-second captured actual-HTTP matrix,
  72 tagged processed Events, seven wrapped-payload cases lose category/subcategory overrides;
  unique follow-up alert work note remains unjournaled after an open Incident is linked;
  debug has zero attachments because `GlideSysAttachment.write/execute` is still requested;
  non-object JSON records create junk Events. Assignee rejection was isolated to the existing
  group-membership abort BR and valid-member cases pass. Runtime/source/privileges were not
  changed during testing; approval to correct the newly found issues was requested.
- CI resolution precedence is explicit sys_id, then `ci_type` + `ci_identifier`, then textual
  `cmdb_ci`; a display/name value can no longer bypass a valid class-scoped identifier.
- `tests/test_ci_identifier_precedence.py` is the standalone post-deployment laptop test. It uses
  an ignored env file and a deliberately different existing CI name to prove identifier precedence.
- DTI API/BR/test Knowledge article `KB0010025` on dev382837 (`3c617cbc9353c7d0c8ebf85bdd03d643`),
  sourced from `kb/generic_json_v2_dti_api_and_tests.md`,
  has `test_ci_identifier_precedence.py` and `ci_identifier_test.env.example` attached as of
  2026-10-29; both downloaded copies were verified byte-for-byte against the repository source.
- dev392825 clean install: scope `96abfcbb97774b105fb3ba6de053afa6`; live conflicting-name DTI
  test created `INC0010004` and resolved CI `Car-1` (`6cabe993c611222500bb025775ec8732`)
  from `cmdb_ci_server` + serial `478933-e78-8823`, ignoring decoy name `*ANNIE-IBM`. All five
  endpoint components reported `2026.10.29.1`.
- the clean enforcing scope additionally required `svc_ci_assoc/read`,
  `life_cycle_stage_status/read`, and the requested scriptable privileges
  `GlideRecord.setValue/execute` and `GlideRecord.update/execute`.
- Extended actual HTTP evidence is in `docs/validation-2026-10-29.md`: 263.786 seconds,
  nine cases passed, concurrent-three-fast failed with `INC0010012` + `INC0010013` for one key.
  Runtime source readback matched all six files exactly. Do not call the release concurrency-safe.
- The new flow is fast DTI only; the wait key is legacy compatibility. The laptop suite now
  omits it, verifies a prompt incident response, and observes CI plus all seven required fields.
- dev392825 default caller property now points to the active Event Management user
  `9d5de9e5930022005bc5f179077ffb07`. Explicit/default caller fast checks created
  `INC0010014` / `INC0010015` with valid local software/os/2/2 choices and the Hardware group.
- Owner explicitly declined a claim table and accepted the simultaneous-first-event race.
  Keep fast API creation + correlation breadcrumb + alert BR linking. The five-case standard
  laptop suite covers sequential duplicates; `--include-concurrency` is an optional stress test.
- Owner withdrew the Linux service requirement. Current delivery is the DTI API, alert reconcile
  BR, and on-demand Python test only; retired service/installer/unit assets were removed from
  the active package. No root service, scheduler, or monitoring email setup is required.
- The focused laptop test reads only `em_event` and `incident`; it does not directly verify
  alert linking. The BR's correct alert-to-incident link was verified separately in DEV, as
  recorded in `docs/validation-2026-10-29.md`.
- Scope cleanup readback: KB0010025 retains its identity, is active/latest/published under
  `Generic JSON V2 Direct To Incident API, Business Rule, and Python Testing`, article 1.2.0.
  Its body matches the new source, and the Python script, env template, and validation-report
  attachments download byte-for-byte. Local validation: 31 Python + 26 JavaScript checks pass.
  No runtime scripts changed and no new live test events were submitted during this cleanup.

## Live objects (dev382837)

| Record | Table | sys_id |
|---|---|---|
| `USBEM_Core` | `sys_script_include` | `e2734f2bc38c4f100bc1b91ed401319c` |
| `USBEM_Lookups` | `sys_script_include` | `8063cba7c38c4f100bc1b91ed401310a` |
| `USBEM_Debug` | `sys_script_include` | `ae23cba7c38c4f100bc1b91ed4013117` |
| `USBEM_DTI` | `sys_script_include` | `5643c32bc38c4f100bc1b91ed40131e7` |
| `USBEM genericJsonV2` | `sn_em_connector_listener` | `ec08e3e7c3848f100bc1b91ed40131ef` |
| `USBEM Fast DTI Alert Reconcile` | `sys_script` (em_alert) | `26dcd72193a78710c8ebf85bdd03d613` |

All four Script Includes are in scope `x_usbna_usb_event` (`9d73f059c3c407500bc1b91ed401313e`),
access public. The listener and the rule are global.

`FirstGenericJSON` (`sn_em_connector_listener` `25b1272993e78710c8ebf85bdd03d63f`, source
`firstGenericJson`) is the **original** connector and is off limits. It carries the reference
attachments: the whitepaper, the customer KB, the incident `sys_dictionary` dump, and the PNG of
the retired `EM - Generic Endpoint Create Incident` subflow.

## Release 2026.09.30.1 (2026-09-30)

- sender `caller_id` / `assigned_to` accept sys_ids or exact full names. The Script Include resolves
  names via scoped `sys_user` read; missing/ambiguous caller uses the per-instance
  `x_usbna_usb_event.default_caller_sys_id`, while unresolved `assigned_to` stays blank for on-call.
- production verifier uses one ignored `tests/usbem_verify.env` for all four instance URLs and
  OAuth pairs, shared lookup fixtures, and per-instance caller/assignee IDs and first names. The
  tracked `tests/usbem_verify.env.example` is the only verifier config template; filled secrets
  stay local.
- production verifier defaults to em_event W + Incident RW + Alert RWC, submits events via the
  connector, retains records, and reads mapped users only from Incident. It never queries
  `sys_user` or `sys_journal_field` through the API.
- Mac HTTP calls use system curl SecureTransport/Keychain. No production instance was deployed or
  exercised by this repo update.

## Release 2026.09.28.1 (2026-09-28)

- alert work notes: posted once through a fresh record, using journal-field dot assignment with
  workflow/auditing enabled; the note key is consumed from `additional_info` before update.
  `setWorkflow(false)` suppressed the Activity entry, and scoped fencing blocks `setJournalEntry()`.
- a DTI sender's plain `work_notes` goes to the incident only; `alert_work_notes` is the alert's
- long message keys: `correlation_id` now stores (and is queried by) a leading slice plus a stable
  FNV hash of the whole key, so keys over 100 characters stop opening an incident per event
- wait loops call `gs.sleep` between polls instead of spinning; scoped apps are allowed to sleep on
  Zurich (verified), and the spin is kept only as a fallback
- unknown payload field names come back in `incident_fields_skipped` instead of vanishing
- `--env-file` reads the named file, not the nearest `.env` beside it
- verification covers compat / legacy payloads / fast DTI / incident fields / fixture-driven
  lookups / manually confirmed notes / edge / timing. `--access-profile limited` uses Incident RW
  and Alert RWC, retains tagged records, and never queries `sys_journal_field` or runs Scripts -
  Background. Work-note checks print Incident/Alert numbers and prompt for manual y/n confirmation.
- at that release, the verifier loaded per-instance CI, CI identifier, group, service, offering,
  CAR ID, and caller fixtures from separate ignored env files. These settings are now consolidated
  into the single `tests/usbem_verify.env` described above. Blank fixtures report as skipped. Field
  checks verify default Software/Monitoring Alert and Hardware/Server overrides plus caller_id and
  assigned_to by sys_id or exact full name (whose first name may vary across anonymized lower
  instances). This release adds exact `sys_user` lookup inside the Script Include; the API verifier
  still checks only the resulting Incident reference.
  `--source firstGenericJson --contract legacy` selects the original listener's response envelope
  while still running the legacy payload matrix.

## Release 2026.09.25.3 (2026-09-25)

- every script stamps the release and the endpoint returns `versions` for listener + 4 includes;
  the business rule logs its version with each outcome
- incident creation matches the retired subflow: `u_netcool_ticket` true, category `Software`,
  subcategory `Monitoring Alert`, caller `Event Management`, `u_generating_alert`, alert group as
  the last-resort assignment group, connector work note + `Incident Created From <alert>`,
  duplicate note on reuse. Payload fields override all of it
- the fast path now claims an already-existing alert during the request
  (`claimAlertForFastIncident`), so a terminal-state relink no longer waits for the rule to fire
- first-event fast DTI still inserts before an alert exists, so `u_generating_alert` is added by
  the later alert reconcile. If an incident before-insert rule clears or substitutes `cmdb_ci`
  while that reference is empty, the reconcile persists `u_generating_alert` first and restores
  the exact event-resolved CI from alert `additional_info`; the limited-access verifier checks
  the stored CI sys_id through the Incident table query, not its potentially duplicated display name
- `ciType` + `ciIdentifier` resolves CMDB descendants by querying `cmdb_ci` with an `INSTANCEOF`
  class filter. This avoids a scoped read privilege per CI child table while preserving the
  requested class, including server vs virtual-machine distinctions.
- `scripts/deploy_usbem.py` + `tests/usbem_verify.py`, both standard-library only

## Gotchas proven on this PDI

- **Resolution contract (2026-10-01).** `incident.u_cause` is a String(100). The PDI did not
  contain the production `close_code` choice `Solved (Permanently)`, so that exact choice was
  added for test parity. The verifier sends choice display values via `sysparm_input_display_value`
  and reads back the required close code, cause, and notes.
- **Scope fencing.** PDI had `incident` read+create+write and `cmdb_rel_ci` read flipped to
  `allowed` on 2026-09-28. The production connector scope can also read `sys_user`; the production
  API account cannot, so only the Script Include resolves names. An uncaught fencing exception
  returns HTTP 500 and loses the event, so user lookup failures are caught and fall back safely.
- **Journal fields.** `work_notes` on both `incident` and `em_alert` only accept dot assignment;
  `setValue()` is silently dropped.
- **`u_netcool_ticket`** and **`u_generating_alert`** (reference → `em_alert`, added by the user
  on 2026-09-28) both exist on the PDI incident table and are verified on the wait path and the
  fast path.
- **Principal CI classes (2026-10-01).** The PDI Business Rule `USB Restrict CI for APIs`
  (`sys_script` `27e2b92f93efcb50c8ebf85bdd03d647`) had a `cmdb_class_info.csv` attachment.
  Its list now has matching `principal_class=true` and descriptions for 116 classes: 92 existing
  rows were updated and 24 were added for registered CI tables. Six CSV classes have no PDI table
  definition (`cmdb_ci_mux_transport` and five `u_cmdb_ci_*` classes). Fourteen CSV rows refer to
  seven `managed_by_group` names absent from PDI, so those references remain unresolved.
- **Choice values.** The PDI has no `Monitoring Alert` subcategory choice, so `setChoiceLike`
  falls back to writing the literal, which is what the subflow did.
- **`sys.scripts.do` echoes the script source** above its output, so a marker-based background
  script runner must try every marker occurrence, not the first.
- **`gs.sleep` works in the scoped app** on Zurich (verified 2026-09-28), so wait loops do not need
  to spin. The old comments claiming otherwise were wrong.
- **Event Management refreshes `em_alert.additional_info` from each new event**, so a key removed
  from it comes back when the next event carries it. That is why the alert work note is posted per
  event that asks for one, and not again on writes that do not.
- **Wait mode** gives up after `usbem_wait_seconds` (15 default) with
  `dti_incident_status=alert_not_found`. A degraded PDI needs more; the verifier asks for 45.
- Endpoint round trips while the PDI was degraded, 2026-09-25: plain ~3.7 s, fast ~6–8 s, wait
  ~16–18 s.

## Verification

```bash
python3 scripts/deploy_usbem.py   # deploy + read live versions back
python3 tests/usbem_verify.py     # select one production instance; limited profile retains records
```

Last full run 2026-09-25: all groups pass; the duplicate work note reports
`skipped: no_write_access_to_incident`, which is the scope privilege above, not a code fault.
