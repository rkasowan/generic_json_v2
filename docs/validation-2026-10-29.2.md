# Corrected DTI release retest — 2026.10.29.2

## Verdict and boundary

Corrected-path DEV retest PASS on **dev392825.service-now.com**, Australia Patch 7,
2026-10-29. This closes the five approved findings from the historical comprehensive run.
It is not a guarantee of every production rule, identity, fixture, or concurrent interleaving.
No production instance was deployed or exercised.

Actual inbound HTTP testing ran from **14:07:06.208 to 14:19:00.613 UTC**,
**714.405 seconds (11 minutes 54.405 seconds)**. It used the authenticated DEV browser
session, the real Event Management endpoint, and stored-record/journal/attachment reads,
not mocked server responses. The standalone Python file itself was not run against this
browser-only authenticated target; its runner and wire behavior were validated locally.

- 47 main message-key cases plus three terminal-state lifecycles: **50 positive scenarios**.
- Ten malformed-payload probes, all explicitly rejected with no tested partial/junk inserts.
- **280 functional assertions**, no unresolved failures, no harness errors, no field/identity drift.
- 69 tagged Events, all Processed; one additional debug companion Event; 44 retained Incidents
  (INC0010066–INC0010109) and 48 tagged Alerts. Records were retained, not deleted.
- Test prefix: `USBEM-FIX-1793282431269`.
- All five API component versions returned `2026.10.29.2`; BR source/config read back separately.

The prior `validation-2026-10-29-comprehensive.md` remains an accurate historical failure
report. It was not rewritten into a pass.

## Approved changes and confirmation

| Finding | Correction | Live confirmation |
|---|---|---|
| Wrapped payloads lost Incident overrides | Flatten only recognized one-level wrapper passthrough; preserve selected routing aliases, outer precedence, per-record overrides and wrapped additional_info | All five root wrappers, five wrapped batch members, object/string additional_info and envelope defaults preserve the intended stored fields |
| Malformed records inserted junk/partial data | Preflight root/container/member object shapes before processing any batch member | Ten invalid probes explicitly fail; valid-first/bad-second requests insert neither the first Event nor its Incident; no new undefined-key Event |
| Installer omitted Advanced/readback | Set Advanced=true, support missing-BR insert, verify stored ID/source/config after create and update; never automatically retry a POST | DEV BR is Advanced=true with exact script/condition/config; 32 installer/transport tests pass. DEV deployment used authorized Background writes and independent HTTP readback, not an end-to-end CLI installer run |
| New Alert notes were lost after an open Incident link | Pending work_notes can invoke the BR independently of the DTI nil/terminal condition | New unique follow-up note appears once; two later no-note updates do not repeat it; plain non-DTI Alert note also appears once |
| Debug companion had no files | Approve only the existing requested DEV GlideSysAttachment.write / execute privilege | Nine success JSON artifacts downloaded and parsed successfully |

No claim table, new persistent data model, Linux service, scheduler, root process, or monitoring
email was introduced. Normal DTI requests omit wait keys. Legacy wait compatibility remains
for existing clients only.

## Runtime source and configuration readback

The following source strings matched the corresponding repository file SHA-256 exactly after
deployment. IDs are DEV locators, not portable production identities.

| Component | DEV sys_id | SHA-256 |
|---|---|---|
| Core | `4312b4e0975c17105fb3ba6de053afa6` | `a990a2aa6dbffcd9c9b6a7551a493d6dbbca7eae21631c38fe72ecd5e0784cec` |
| Lookups | `5312b4e0975c17105fb3ba6de053afaf` | `3e032fca89033493310403bd2db5f674dae56ac7b51b00ac98a8cc0861c4d55c` |
| Debug | `d31278e0975c17105fb3ba6de053af92` | `90adf165e4600c1936e8b5fe31ad6a7d208397780c414f0ba1cd2e03d406b55b` |
| DTI | `9b1278e0975c17105fb3ba6de053af97` | `c13fc86c626bbfe304401742f1ec957ef6bfc574cabd3fafea4c7648f5ce3073` |
| Listener | `ab1278e0975c17105fb3ba6de053afa9` | `05ce45fb659d31e89a9840716698c5ae7f4d91593d7c7b64b3f7b05cf5ef835f` |
| Alert reconcile BR | `631278e0975c17105fb3ba6de053afb4` | `50095e5d50b1e4a32953a9267e965a12b5a5e5dc03fe27dcb28e43770286f1e5` |

Scope: `x_usbna_usb_event`, ID `96abfcbb97774b105fb3ba6de053afa6`, enforcing. Four includes
remain scoped; listener and BR remain Global. BR readback: active=true, advanced=true,
when=after, order=150, insert/update=true, delete/query=false, abort_action/add_message=false.
It is not async and does not wait inside the API request.

Exact external BR condition:

```javascript
((current.getValue('additional_info') || '').indexOf('work_notes') > -1 || ((current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1 && (current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)))
```

Only the specifically approved privilege `9dde38ac97dc17105fb3ba6de053afce` changed from
requested to allowed: source DEV scope above, target `GlideSysAttachment.write`, operation
execute, target Global. No broad role, table-attachment grant, or membership was added.
Review/approve each target's own request rather than transporting this DEV row.

## Positive matrix and retained evidence

Unless a case deliberately checks defaults/mapping, required-field fixtures were deliberately
non-default: caller Abel Tuter (`62826bf03710200044e0bfc8bcbe5df1`), category `hardware`,
subcategory `cpu`, impact `1`, urgency `3`, unique exact short description and description.
All seven fields were checked immediately after POST and again during stable observations.
Explicit group was Hardware (`8a5055c9c61122780043563ef53438e3`).

| Cases | Retained Incident evidence | Checked behavior |
|---|---|---|
| fast-first | INC0010066 | First POST returns Incident in 1258ms while no Alert exists; immediate duplicate, later duplicate, unique new Alert note and two no-note replays all reuse it; later Alert0010108 links correctly |
| root-event/payload/data/record/alert | INC0010067–71 | All seven fields, identifier-selected CI and group survive each wrapper; sequential replay reuses each Incident; wrapped Incident note appears once per requesting Event |
| camel-conflict, explicit-sysid, name-only, identifier-only, missing-identifier-fallback | INC0010072–76 | Explicit sys_id wins; otherwise class+identifier wins over conflicting CI name; controls and actual missing-identifier name fallback work |
| plain, quiet-0/5/clear/OK | None | Normal non-DTI and quiet/clear Events do not create an Incident or an unexpected Alert-to-Incident link |
| severity-1/2/3/4 | INC0010077–80 | Existing severity-to-impact/urgency policy retained; explicit fields elsewhere override it |
| group-name, caller-assignee-name, default-caller, invalid-caller-fallback | INC0010081–84 | Exact group/user name resolution, valid group-member assignee, valid configured default caller, invalid-caller fallback and invalid-assignee omission |
| ci-support, group-overrides-support | INC0010085–86 | CI support group routing and explicit group precedence |
| service, offering | INC0010087–88 | Real local service and offering references reach Incident |
| long-A/B | INC0010089–90 | Keys sharing their first 100 characters remain distinct via prefix+hash; both sequential replays reuse the correct Incident |
| wrapped-info-object/string | INC0010091–92 | Incident fields and work notes from wrapped additional_info survive; nested custom_context.event.unchanged remains true |
| outer-precedence | INC0010093 | Explicit outer description, CI and group are not replaced by losing inner aliases |
| debug | INC0010094 | Normal fast DTI plus readable companion JSON capture |
| batch-event/payload/data/record/alert | INC0010095–99 | Five wrapped records in one records batch preserve independent fields/IDs |
| mixed-plain/dti/quiet | INC0010100 only | Mixed records batch creates only the intended DTI Incident |
| events-wrapper | INC0010101 | events batch envelope supported |
| array-dti/plain | INC0010102 only | Bare array processes both records without creating an Incident for plain member |
| envelope-wrapped | INC0010103 | Wrapped per-record hardware/cpu/caller/impact/urgency beat flat envelope defaults |
| plain-note | None | Non-DTI work_notes posts once to its Alert; no Incident created |

Primary CI: Car-1, `6cabe993c611222500bb025775ec8732`, queried as `cmdb_ci_server` with serial
`478933-e78-8823`. Decoy name `*ANNIE-IBM` resolves to a different real CI,
`b4fd7c8437201000deeabfc8bcbe5dc1`. Readback used raw reference sys_ids, not display names.
The valid assignee Beth Anglin was confirmed a Hardware group member; no fixture membership
or existing abort Business Rule was changed.

Single-record main-case first POSTs were 111–1258ms. The five-record batch was 2230ms.
Sequential main-case duplicate POSTs were 205–356ms. All met the 10-second budget. Batch
timings are for the whole HTTP request, not five separate requests.

## Terminal-state lifecycle

For each terminal state, create via API, observe the initial BR link, update only the owned
test Incident, read the actual terminal state, post the same key again, and replay a third
Event. The second Incident differs from the terminal one; the third Event reuses the second.
Final readback again verifies all required fields and the new Alert link; the old state stays
terminal. Each key has exactly three Processed Events and two Incidents.

| Stored old state | Old Incident | New/reused Incident | Final Alert |
|---|---|---|---|
| 6 (resolved) | INC0010104 | INC0010105 | Alert0010155 |
| 7 (closed) | INC0010106 | INC0010107 | Alert0010156 |
| 8 (canceled) | INC0010108 | INC0010109 | Alert0010157 |

## Stable observation, notes, and debug artifacts

Two dense windows queried stored Event/Incident/Alert records at approximately five-second
intervals. The first had 15 samples spanning **72.880 seconds**, all 46 then-existing main
cases ready. After duplicates, notes and lifecycles, the second had 15 samples spanning
**72.843 seconds**, all 47 main cases ready. A final independent read also passed.
Most main cases have 32 observations; the later plain-note case has 17. No stored required
field, Incident identity/count, or Alert link drifted.

For INC0010066, journal readback contains one creation note and five duplicate notes for six
Events. Incident-only sender text did not reach the Alert. `ALERT-FIRST <prefix>` appears
three times for the three Events requesting it; the unique `ALERT-SECOND <prefix>` appears
once. Two subsequent Events without a requested note produced no repeat. Consumed note
keys are absent from final Alert additional_info. All five wrapped Incident notes appear once
on create and once on replay, not on incidental BR updates.

Debug companion Event `078785a8975057105fb3ba6de053afe1` has these downloadable, parsed JSON
files: 01_raw_payload, 02_normalized_payload, 03_mapped_event, 04_lookup_trace,
05_candidate_scores, 06_correlation_hints, 07_performance, 08_response_summary and
09_dti_timeline (all `.json`). The tenth `10_error_context.json` is conditional on an error.
The harness initially expected ten on success; that assertion was corrected against the
unchanged Debug implementation, then all nine expected success artifacts passed. This was a
harness expectation correction, not a suppressed runtime failure.

## Negative shape probes

All ten returned the connector's existing explicit HTTP 500 error contract, not a new 400
contract: scalar number, null root, JSON string root, records containing null, valid record
then null in records, valid record then scalar in events, valid record then null in a bare
array, non-array records container, non-array events container, and malformed JSON syntax.

The three valid-first/bad-second keys (`<prefix>-bad-records-first`, `-bad-events-first`,
`-bad-array-first`) had zero Events and zero correlated Incidents after observation. The two
pre-existing historical `GenericJSONundefinedundefinedundefinedundefined` Events remained
the exact same two IDs: no new junk row was added. They were not deleted.

This is **shape preflight**, not a database transaction across a batch. Later runtime errors
or platform rules can still fail after earlier valid members have been processed. Empty
objects/empty batches retain the prior contract; this release does not add a required Event
schema validator.

## Local validation and laptop delivery

All **204** persisted local tests pass: 65 Python tests (33 laptop-runner and 32 installer/
transport), 26 CI-precedence checks, 39 listener-shape checks and 74 wrapper-passthrough
checks. All six runtime JS files, three Node suites and six relevant Python scripts pass
syntax checks; git diff --check is clean.

The standalone `test_ci_identifier_precedence.py` plus `ci_identifier_test.env.example` use
stock Python 3.9+, Basic/plain-or-base64 or OAuth client credentials, verified HTTPS and an
optional corporate CA. Base64 is reversible encoding, not hashing/encryption. POSTs are
not automatically retried. Configure target-local fixtures and optional assignment group.

Default: ten cases, twelve Events, ten expected Incidents, twelve 30-second stable phases,
at least six minutes plus request time. Optional concurrency: eleven cases, fifteen Events,
eleven expected Incidents if it passes, at least 6.5 minutes plus request time. The limited
laptop identity reads only em_event and incident, so its PASS does **not** directly prove
the BR Alert link. This DEV audit separately queried Alert/journal/attachment evidence.

## Acceptance limits and promotion

- Owner accepted simultaneous first-event duplicate creation and declined a claim table.
  This release does not fix that race; optional stress testing fails divergent Incident IDs.
- No production OAuth/restricted API identity, corporate network path or target-specific ACL
  was exercised. Run the attached laptop test per target before advancing DEV→IT→UAT→PROD.
- Positive custom `u_generating_alert`, `u_netcool_ticket`, `u_cause`, CAR-ID and custom L2
  fixtures were unavailable here. Do not label unexercised custom production features live-tested.
- Severity4's stored 4/4 and customer default Software/Monitoring Alert are existing policy,
  not a guarantee of out-of-box valid choices. The required-field cases use valid hardware/cpu/1/3.
- Existing native Event Management lifecycle rules can independently copy/reopen incidents
  (documented in the historical comprehensive report). A native policy mutation is not proof
  that DTI overwrote a foreign link. Review those policies in each target.
- CLI installer create/update transport is unit-tested; DEV runtime/config live readback is
  verified, but the target's deployment identity and permissions still require acceptance.

Promote the six runtime files together with exact configuration and target-specific reviewed
privileges. Keep the Python test/template and this report attached to the existing KB. Preserve
all historical reports and retained test records until an approved exact-record cleanup.
