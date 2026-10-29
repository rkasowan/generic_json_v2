# Comprehensive DTI pre-release validation — 2026-10-29

## Release decision

**HOLD: this is not a clean release pass for runtime 2026.10.29.1.**

The normal flat-payload DTI path passes the exercised live checks. Broader testing found
wrapped Incident-field loss, missing debug attachments in the enforcing DEV scope, and lost
follow-up alert work notes. Invalid JSON shapes also produce junk events. These are distinct
from the simultaneous-first-event race already accepted by the owner. No runtime fix,
permission change, or production deployment was performed during this test run.

## Method and boundaries

- Target: `https://dev392825.service-now.com`, authenticated `api_test` browser session.
- Actual HTTP POSTs to the existing inbound Event Connector, `source=genericJsonV2`, using
  `User-Agent: genericendpoint`. The native listener-name/string response envelope was unwrapped
  before checking its business result. Table API reads verified the resulting records.
- Run prefix: `USBEM-FULL-1793280412147`.
- Main captured interval: `2026-10-29T13:26:52.147Z`–`2026-10-29T13:39:16.228Z`, 744.081 seconds.
- 49 event-matrix cases, three terminal-state cycles, isolated ownership checks, and three
  malformed-input probes. This was a browser-transport live matrix, not an execution of the
  standalone laptop Python process or the production OAuth identity.
- Dense observation windows: 15 polls spanning 72.636 seconds, followed by 14 polls spanning
  67.628 seconds, with additional readbacks between and afterward. These were bounded windows,
  not a claim of continuous observation for the entire run.
- Final prefix readback: 72 Events, all `Processed`; 51 Alerts; 47 Incidents including terminal
  generations and the foreign-owner platform-reopen fixture described below.
- All test records were retained. Only this run's own test Incidents and Alert links were
  deliberately updated for lifecycle/ownership tests. No CMDB data, users, memberships,
  configuration, source records, or unrelated operational records were changed.
- No wait keys were sent. No Linux service or monitoring email was involved.

## Confirmed passing behavior

| Feature | Live result / retained evidence |
|---|---|
| Fast DTI and immediate replay | `INC0010017`: first POST 662 ms; immediate replay 388 ms; replay response still had no alert ID, returned the same Incident |
| CI class + identifier beats conflicting name | Snake `INC0010017`, camel `INC0010018`; expected `Car-1`, not the decoy name |
| Explicit CI sys_id is authoritative | `INC0010019` retained the explicit decoy sys_id despite the conflicting identifier |
| CI controls and fallback | Name-only `INC0010020`, identifier-only `INC0010021`, missing-identifier match fallback `INC0010022`, wrong-class fallback `INC0010023` |
| Additional-info object / JSON string | `INC0010024` / `INC0010025`; identifier resolution and custom marker preserved |
| No DTI / quiet severity | Plain event created no Incident; `0`, `5`, `clear`, and `OK` created no Incident even with explicit DTI impact/urgency overrides |
| Severity mapping | `INC0010026`–`INC0010029`: `1/2 → 2/2`, `3 → 3/3`, `4 → 4/4`; see target-choice warning below |
| Assignment by name and sys_id | Exact Hardware sys_id persisted; group-name case `INC0010030` |
| CI support group and explicit override | `INC0010034` used the CI's different support group; `INC0010035` used explicit Hardware instead |
| Caller fallback | Unresolved caller `INC0010032` and omitted caller `INC0010033` used the configured default; unresolved assignee remained blank |
| Full-name caller and valid assignee | `INC0010040` caller-only; `INC0010055` caller/assignee names and `INC0010056` assignee sys_id, with a verified Hardware member |
| Service / offering names | `INC0010036` / `INC0010037` stored exact expected references |
| Long keys with identical first 100 characters | `INC0010038` / `INC0010039`: distinct hash-suffixed correlation IDs, distinct Incidents, three Events per key, correct BR links |
| Flat mixed `records` batch | Plain + DTI + OK inputs matched their own result/Event IDs; only the DTI input created `INC0010046` |
| Bare array | DTI `INC0010047` and plain input remained separate |
| Envelope defaults and per-record override | `INC0010050` / `INC0010051` retained distinct expected CIs and all requested fields |
| Event aliases | `INC0010052`; `host`, `target`, `metric`, `eventType`, `messageKey`, and `summary` mapped to the expected stored Event fields |
| Required fields and later BR link | Passing flat cases retained exact caller, category, subcategory, impact, urgency, short description, description, CI, group, and correlation breadcrumb after alert arrival and through observation windows |
| Sequential duplicate stability | `INC0010017` retained seven Events / one Incident; camel and both long-key cases retained three Events / one Incident each; no field drift observed |
| Unknown Incident fields | `unknown_release_field` was explicitly reported skipped |
| Incident journals | One creation note; one duplicate note per deliberate replay; Incident-only sender text was not copied to Alert journals |
| Plain non-DTI work note | `Alert0010105` received `PLAIN-ALERT-NOTE <prefix>` exactly once |
| Malformed JSON syntax | `{"broken":` returned HTTP 500 with explicit connector error, not business success |

All five API component versions were exactly `2026.10.29.1` on successful matrix responses.
All first-response matrix POSTs stayed below the 10-second budget; the largest was the
five-record wrapper batch at 2,383 ms. A prompt response did not override any persisted-field
failure. Of the 49 matrix cases, 40 matched their expected persisted records; seven wrapper
cases failed field checks and two assignee cases were rejected by existing target policy.
The debug case additionally failed its attachment-specific assertion despite its core DTI pass.

## Terminal-state and ownership checks

| State | Old Incident | New Incident | Later replay / Alert |
|---|---|---|---|
| Resolved (`6`) | `INC0010057` | `INC0010058` | New Incident reused; `Alert0010101` linked to it |
| Closed (`7`) | `INC0010059` | `INC0010060` | New Incident reused; `Alert0010102` linked to it |
| Canceled (`8`) | `INC0010061` | `INC0010062` | New Incident reused; `Alert0010103` linked to it |

Transitions used this DEV instance's valid `Solution provided` close code and explicit test
close notes. The customer-specific `u_cause`/close-code contract was not installed here and was
not silently added to make the test pass. These live cycles had Open alerts; preservation of
a pre-existing Closed alert was covered by offline branches, not reproduced live here.

Ownership fixture `INC0010063` / `Alert0010104` was deliberately linked to foreign terminal
fixture `INC0010064`, which had `correlation_display=Foreign ownership test`, not the DTI marker.
The DTI replay returned `INC0010063`, reported `deferred_to_reconcile_rule`, and initially left
the foreign link untouched. Later the platform's own reopening policy changed that link:
`evt_mgmt.alert_reopens_incident=new` and `evt_mgmt.incident_closes_alert=true`. The system
created `INC0010065` by copying the foreign fixture and moved the Alert to `Reopen` with that
new foreign Incident. This was observed, not suppressed or mistaken for a DTI correlation
duplicate: `INC0010065` was created by `system`, retained the foreign marker, and was not returned
by the DTI API. No unrelated Incident was used for this test.

## Findings requiring disposition

### 1. Wrapped payloads discard Incident overrides — release blocker

All five supported one-level wrappers inside `records` (`event`, `payload`, `data`, `record`,
`alert`) created `INC0010041`–`INC0010045`, but discarded their supplied category/subcategory
overrides. Two `{events:[{payload:...}]}` cases created `INC0010048` / `INC0010049` with the same
defect. CI, fast DTI, and later Alert linking passed, so response-only checks missed it.

Exact example: `INC0010041`, sys_id `1fce7c2c97dc17105fb3ba6de053afbb`, was sent
`category=software`, `subcategory=os`; it stored `Software` and `Monitoring Alert` instead.
Responses omitted `incident_fields_applied` for these wrapped inputs.

Source diagnosis: Core extracts recognized Event/DTI aliases from wrappers, but leaves remaining
Incident fields nested under the wrapper. DTI passthrough accepts top-level scalars, so it
skips that object. The same source path affects wrapped caller/assignee overrides, ordinary
`work_notes`, and wrapped `additional_info` extraction. Those additional effects were reproduced
locally; this live matrix directly proved category/subcategory loss.

A fix must preserve explicit outer alias precedence and arbitrary nested custom context, not
naively flatten every JSON object. Add all-wrapper required-field, journal, additional-info,
outer-camel/inner-snake precedence, and envelope regressions before deployment.

### 2. Follow-up Alert work notes on linked DTI alerts are lost

Initial `ALERT-ONLY <prefix>` reached `Alert0010048` once. Later a different
`ALERT-SECOND <prefix>` was sent and processed after its Incident was already linked. After
the final observation window it remained in Alert `additional_info`, but no corresponding
`sys_journal_field` entry existed. The BR condition excludes an open linked Incident, preventing
the note-consumption code from running in that case. The Incident-only note did remain isolated.

An early assertion expected four identical sender-note journal entries after four note-bearing
replays; that assumption was not used as a release verdict. The decisive failed test used a new,
unique follow-up note and verified the missing journal entry after processing.

### 3. Debug companion has no attachments — DEV prerequisite failure

Debug Event `15de38ac97dc17105fb3ba6de053afce` exists, is `Processed`, and points to its parent
Event `45de38ac97dc17105fb3ba6de053af72`. Both attachment APIs returned zero attachments instead
of the ten documented JSON captures. The exact scoped privilege `GlideSysAttachment.write`
is still `requested`, not `allowed`. The UI also displayed the corresponding denied-execute
message. No permission was changed during testing. The helper catches attachment exceptions,
so a debug-enabled successful response is not proof of captured debug files.

### 4. Invalid JSON shapes create junk Events — input-hardening gap

Raw JSON `42` and `{"records":[null]}` each returned success and inserted an Event with
`message_key=GenericJSONundefinedundefinedundefinedundefined`. Their retained Event sys_ids are
`4ade78ac97dc17105fb3ba6de053aff1` and `c6de78ac97dc17105fb3ba6de053aff3`. These two negative-test
Events do not carry the run prefix because of the generated-key behavior. Neither created an
Incident. The debug companion is a third Event outside the prefix query.

This permissive coercion is an existing behavior, not evidence that valid DTI payloads failed.
Recommend rejecting non-object records before processing any batch members. That preflight
would not make later database/runtime batch execution atomic; never automatically retry an
uncertain POST.

### 5. Fresh-install BR configuration needs an explicit guard

The live DEV BR is correct: active, Advanced=true, Global, `em_alert`, after insert/update,
order 150; stored condition and script match the repository. However `deploy_usbem.py` does
not explicitly set `advanced=true` on create/update, and its new-record branch lacks immediate
readback. An already-correct record passes; a clean-install guarantee cannot depend on an
unverified default. Set/verify this explicitly before claiming portable fresh installation.

## Fixture rejection is not a connector name-mapping failure

Two attempted assignee cases using Abel Tuter with Hardware returned `create_failed` and no
Incident. The existing before-insert Incident BR `Abort changes on group`
(`6a2e9d1453e80010833addeeff7b124f`) calls `setAbortAction(true)` when the assignee is not a member
of the group. The UI showed that exact error. Abel had no matching membership. Caller-only
Abel passed, and verified Hardware member Beth Anglin passed both full-name and sys_id tests
(`INC0010055`, `INC0010056`). No BR was disabled and no membership was changed.

## Installed-source and local verification

Live SHA-256 readback of all six runtime scripts exactly matched the unchanged repository
release. The four includes are active/public in enforcing scope `x_usbna_usb_event`; the
listener is active Instance type and the BR configuration is described above.

- Existing persisted tests: 31 Python runner tests and 26 JavaScript CI lookup cases passed.
- Additional offline checks: 56 mocked Core/DTI/BR branches and six in-memory deployer scenarios
  passed, including idempotent rerun and dry-run. These 62 checks are not live-platform proof.
- All six Python files parsed; all 11 JavaScript files passed `node --check`; all 13 JSON
  examples parsed; release stamps and BR condition were consistent; `git diff --check` passed.
- The existing broad verifier can report success with skipped fixtures/manual observations;
  its long-key check also allows incomplete evidence. This run used explicit persisted-record
  assertions and did not use that process exit code as the release gate.

## Remaining acceptance limits

The earlier three-simultaneous-first-event race remains accepted and documented separately;
this run did not repeat it or add a claim table. No production instance, production OAuth
identity, sustained-load test, or credentials-rotation test was exercised. CAR-ID and custom
CI support-tier positive live cases lacked suitable installed fixtures. Customer-specific
`u_generating_alert`, `u_netcool_ticket`, and `u_cause` were absent from DEV readback. No field or
CI was created just to turn those omissions into a pass.

Severity-4 defaults store `4/4`, and default category/subcategory are customer-oriented literals;
they are not OOB choices on this PDI. Passing required-field cases explicitly used valid local
`software/os/2/2` values. Confirm production choices, caller, group, field ACLs, privileges, and
rules with the actual target identity. A bounded DEV pass is not a universal guarantee.
