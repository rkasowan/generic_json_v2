# Installing genericJsonV2 + DTI from scratch

For a clean instance with nothing from this project on it. Every value below was read from the
working install on dev382837 on 2026-09-25.

Steps are marked **[verified]** where this exact arrangement is running on dev382837, and
**[not verified here]** where it is the recommended arrangement but has not been proven on an
instance yet. Do not treat the second kind as tested.

Source of truth: `rkasowan/generic_json_v2`. Use the files under `src/` as-is.

---

## 0. Prerequisites

- Event Management plugin active, with alert creation working (see the trap in section 10).
- An account with `admin`. The Script Includes are installed in a scoped app, and the
  verification script drives them through a background script.
- Decide the endpoint name now. dev382837 uses `genericJsonV2`; it appears in the listener,
  the push URL and every sender's configuration.

## 1. Scoped application [verified]

Create the application:

| Field | Value |
|---|---|
| Name | `USB Event Management` |
| Scope | `x_usbna_usb_event` |
| JavaScript mode | ES latest (`es_latest`) |
| Runtime access tracking | `enforcing` |

The scope name is baked into the property names, the event name and every
`x_usbna_usb_event.USBEM_*` reference. Changing it means changing all of them.

## 2. Script Includes [verified]

Create four, all in the scope above, **Accessible from: All application scopes**
(`access = public`), not client callable:

| Name | Source file |
|---|---|
| `USBEM_Core` | `src/USBEM_Core.js` |
| `USBEM_Lookups` | `src/USBEM_Lookups.js` |
| `USBEM_Debug` | `src/USBEM_Debug.js` |
| `USBEM_DTI` | `src/USBEM_DTI.js` |

Paste the file contents verbatim. `USBEM_DTI` depends on `USBEM_Core`; `USBEM_Lookups` depends
on `USBEM_Core`; the listener constructs all four.

## 3. Inbound listener [verified]

The endpoint is an Event Management **Instance** listener. On dev382837 there is no push
instance record for it — the listener alone serves:

    POST /api/sn_em_connector/em/inbound_event?source=genericJsonV2

| Field | Value |
|---|---|
| Name | `USBEM genericJsonV2` |
| Source | `genericJsonV2` |
| Type | Instance (`type = 1`) |
| Header name / value | `user-agent` / `genericendpoint` |
| Active | true |
| Script | `servicenow/USBEM_genericJsonV2.listener.js` |

The script constructs `USBEM_Core`, `USBEM_Lookups`, `USBEM_Debug` and `USBEM_DTI` by their full
`x_usbna_usb_event.` names and holds no copy of them, so there is one copy of the logic and it
cannot drift. It is about 4 KB.

Earlier builds pasted an inlined bundle of all four classes into this record instead. That is why
REST callers on dev382837 ran months-old logic while the Script Includes were current: do not
reintroduce it.

## 4. No async linker, no queued events [verified]

Earlier builds queued a `x_usbna_usb_event.link_alert_later` event and handled it in a Script
Action, with a retry loop. That is retired: nothing queues events, there is no Script Action and
no scheduled job. The business rule in section 5 does the linking. If you are migrating an older
install, deactivate that Script Action and remove the event registration.

## 5. Reconcile business rule [verified]

`servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`, in the **global** scope:

| Field | Value |
|---|---|
| Table | `em_alert` |
| When | `after` — **not async** |
| Insert / Update | true / true |
| Order | 150 |
| Condition | see below |
| Active | true |

```javascript
(current.additional_info.indexOf('direct_to_incident') > -1 ||
 current.additional_info.indexOf('work_notes') > -1) &&
(current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)
```

The condition is what keeps this rule cheap: it only runs for an alert this connector is
responsible for — one whose event asked for an incident or carried a work note — and only while
that alert has no incident or holds a finished one. `alert_work_notes` matches the `work_notes`
test as a substring, so both spellings are covered. Everything else on `em_alert` is filtered out
before the script executes.

It attaches the alert link as soon as Event Management creates or updates an alert, and in
practice usually beats the Script Action to it. Both write through the same conditional claim,
so whichever runs second reports `already_linked` instead of overwriting.

**Do not make this async.** Event Management best practices state: "Do not write async business
rules for alert tables", that a rule here must not take "more than a few milliseconds", and that
an inefficient one "can cause incident creation for an alert to fail and the alert impact
calculation to fail". dev382837 ran it as `async_always` with no condition until 2026-09-25,
which is exactly the pattern that guidance prohibits.

The condition does the heavy lifting: the rule is skipped entirely for alerts that already have
an incident, have no message key, or are Closed. When it does run and no open USBEM DTI incident
exists for the key, the script costs one query and writes nothing.

## 6. Properties [verified]

Create in the `x_usbna_usb_event` scope. All are optional — the code has the same defaults — but
creating them makes the behaviour visible and tunable.

| Property | Value | Purpose |
|---|---|---|
| `x_usbna_usb_event.dti_terminal_incident_states` | `6,7,8` | states that end incident reuse for a message key. Integers only; anything else falls back to the default and logs a warning. Set to `0` as a kill switch to restore pre-fix reuse |
| `x_usbna_usb_event.dti_duplicate_work_note` | `true` | add a work note to an incident an event was folded into. `false` turns it off |
| `x_usbna_usb_event.default_cmdb_ci_sys_id` | optional | fallback CI when none resolves. Point it at a real CI or leave it unset; dev382837's value does not resolve |
| `x_usbna_usb_event.dti_map_table` | leave blank | the map-table code is inert and expects `u_*` fields that do not exist. Leave it empty |

Do **not** create `x_usbna_usb_event.default_assignment_group_sys_id`. It is no longer read: an
incident with no resolvable group is deliberately left unassigned.

The `fast_dti_event_name`, `fast_dti_link_delay_seconds` and `fast_dti_link_max_retries`
properties belonged to the retired async linker and are no longer read by anything.

## 7. CI support tier fields [verified]

Run `servicenow/install_ci_support_tier_fields.background.js` from **Scripts – Background**. It
creates `cmdb_ci.u_level_2_support_assignee_group` and `u_level_3_support_assignee_group`, both
reference → `sys_user_group`, and is idempotent.

Two warnings:

- Adding a column to `cmdb_ci` propagates a dictionary entry and a label record to every CI
  class — 1,334 of each per field on dev382837. It ran for over 30 minutes and slowed the
  instance noticeably. Do it in a quiet window.
- Run it from the UI, not over HTTP. A client-side timeout cuts the transaction short: on
  dev382837 the columns were created but nothing was captured in the update set.

Only the level 2 field is in the resolution chain today. To add level 3, append it to
`CI_SUPPORT_GROUP_FIELDS` in `src/USBEM_Lookups.js`.

## 8. Cross-scope privileges [verified as a gap]

With `runtime_access_tracking = enforcing`, the scope needs explicit access to the tables it
touches outside itself. dev382837 grants `cmdb_ci_service` and `service_offering`, and create on
`incident`, but not the three below. Each one costs a feature, and the connector is written so
that none of them costs an event:

| Table | Access | What is lost without it |
|---|---|---|
| `cmdb_rel_ci` | read | any event resolving to a real CI throws `ScopeAccessNotGrantedException` before the assignment-group logic runs, so CI-derived groups never take effect |
| `incident` | write | the duplicate work note on a reused incident, and `u_generating_alert` written after creation. Both report a skip on the response |
| `sys_user` | read | nothing today: the default caller is set through the reference field rather than a query, precisely so this privilege is not needed |

Grant them in **System Applications > Application Cross-Scope Access**.

## 9. Deploy and verify

Both scripts need Python 3.9+ and the packages in `requirements.txt`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Push the repo at the instance and read back what it is running:

```bash
python3 scripts/deploy_usbem.py --dry-run   # what would change
python3 scripts/deploy_usbem.py             # write it, then report live versions
```

Then verify behaviour end to end:

```bash
python3 tests/verify_usbem_connector.py
```

Self-cleaning, exit code 0 when everything passed. `--only deploy` is the fastest confidence
check: it compares every record on the instance with the file in this repo and confirms the
endpoint reports this release's version for all five components.

Quick manual smoke test:

```bash
curl -u "$USER:$PASS" -H 'Content-Type: application/json' \
  "$INSTANCE/api/sn_em_connector/em/inbound_event?source=genericJsonV2" \
  -d '{"source":"smoke","event_class":"smoke","node":"smoke-host","resource":"smoke",
       "metric_name":"smoke","severity":"1","message_key":"smoke-001",
       "description":"smoke test","direct_to_incident":"true"}'
```

The response carries `incident_number`, `dti_mode: fast_async` and a `versions` block. Resolve
that incident, send the same payload again, and you get a **different** incident number.

## 10. Traps worth knowing before you start

- **Event rules that swallow events.** dev382837 had four active `em_match_rule` records with
  empty filters and `ignore_event = true`, which suppressed *all* alert creation instance-wide
  for two months. If alerts never appear, check `em_match_rule` for catch-all ignore rules before
  suspecting this project.
- **Alert reopen behaviour.** With `evt_mgmt.alert_reopens_incident = new`, a new event for a
  recently closed alert reopens that alert and disconnects the resolved incident, rather than
  opening a new alert. Both behaviours are handled, but expect the reopen path in testing.
- **Long metadata operations over HTTP.** Anything that alters `cmdb_ci` or takes minutes should
  be run from the UI. A client timeout leaves the work applied but the update set empty, and can
  leave your current update set pointing somewhere unexpected.
- **`em_alert.task` may not exist.** On dev382837 only `em_alert.incident` does. The code handles
  both, but queries you write by hand should check first.
