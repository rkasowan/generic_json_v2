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

## 3. Inbound listener

The endpoint is an Event Management **Instance** listener. On dev382837 there is no push
instance record for it — the listener alone serves:

    POST /api/sn_em_connector/em/inbound_event?source=genericJsonV2

Two ways to install it. Pick one and understand the trade.

### Option A — delegate to the Script Includes (recommended) [verified]

Create `sn_em_connector_listener` **inside the `x_usbna_usb_event` scope** with the script from
`src/USBEM_genericJsonV2.js`, which constructs `USBEM_Core`, `USBEM_Lookups`, `USBEM_Debug` and
`USBEM_DTI` by bare name. Inside the scope those names resolve to the Script Includes, so there
is one copy of the logic and it cannot drift.

This is what dev382837 now runs, and it is verified end to end. The listener script is
`servicenow/USBEM_genericJsonV2.listener.js`; it is ~4 KB instead of the 171 KB inlined build.

### Option B — inlined build (legacy, not recommended)

Create `sn_em_connector_listener` in the **global** scope with the script from
`src/USBEM_genericJsonV2_Full.js`, a single file that embeds the listener plus all four classes.

| Field | Value |
|---|---|
| Name | `USBEM genericJsonV2` |
| Source | `genericJsonV2` |
| Type | Instance (`type = 1`) |
| Header name / value | `user-agent` / `genericendpoint` |
| Active | true |

**The catch:** the embedded classes are a copy. Any later fix to a Script Include does not reach
callers of this endpoint until the bundle is regenerated from `src/`. On dev382837 the bundle is
older than the Script Includes, so REST callers still get pre-fix behaviour for terminal
incidents and for assignment group precedence. If you take this option, add "regenerate the
bundle" to the release checklist for every change under `src/`.

## 4. No async linker [verified]

Earlier builds queued a `x_usbna_usb_event.link_alert_later` event and handled it in a Script
Action, with a retry loop. That is retired: nothing queues events, and there is no Script Action.
The business rule in section 5 does the linking. If you are migrating an older install, deactivate
that Script Action and remove the event registration.

## 5. Reconcile business rule [verified]

`servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`, in the **global** scope:

| Field | Value |
|---|---|
| Table | `em_alert` |
| When | `after` — **not async** |
| Insert / Update | true / true |
| Order | 150 |
| Condition | `!current.message_key.nil() && current.incident.nil() && current.state != 'Closed'` |
| Active | true |

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
| `x_usbna_usb_event.fast_dti_event_name` | `x_usbna_usb_event.link_alert_later` | event the fast path queues |
| `x_usbna_usb_event.fast_dti_link_delay_seconds` | `10` | gap between async link retries |
| `x_usbna_usb_event.fast_dti_link_max_retries` | `6` | retry cap before `alert_not_found` |
| `x_usbna_usb_event.default_cmdb_ci_sys_id` | optional | fallback CI when none resolves. Point it at a real CI or leave it unset; dev382837's value does not resolve |
| `x_usbna_usb_event.dti_map_table` | leave blank | the map-table code is inert and expects `u_*` fields that do not exist. Leave it empty |

Do **not** create `x_usbna_usb_event.default_assignment_group_sys_id`. It is no longer read: an
incident with no resolvable group is deliberately left unassigned.

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

With `runtime_access_tracking = enforcing`, the scope needs explicit read on the CMDB tables it
walks. dev382837 grants `cmdb_ci_service` and `service_offering` but **not `cmdb_rel_ci`**, and
the result is that any event resolving to a real CI throws:

    com.glide.script.fencing.access.ScopeAccessNotGrantedException: read access to cmdb_rel_ci not granted

That happens before the assignment group logic runs, so CI-derived groups never take effect.
Grant read on `cmdb_rel_ci` to `x_usbna_usb_event` if you expect CI matching to work.

## 9. Verify

```bash
python3 tests/dti_terminal_incident_check.py --listener
```

Standard library only. Reads `servicenow_instance`, `servicenow_user`, `servicenow_password` from
the environment or a `.env`. Tags everything it creates and deletes it afterwards. Exit code 0
when all checks pass.

Expected on a correct install: all cases pass, concurrency and timing report as observations,
and `--listener` passes **only if** you took Option A or regenerated the Option B bundle.

Quick manual smoke test:

```bash
curl -u "$USER:$PASS" -H 'Content-Type: application/json' \
  "$INSTANCE/api/sn_em_connector/em/inbound_event?source=genericJsonV2" \
  -d '{"source":"smoke","event_class":"smoke","node":"smoke-host","resource":"smoke",
       "metric_name":"smoke","severity":"1","message_key":"smoke-001",
       "description":"smoke test","direct_to_incident":"true"}'
```

The response should carry `incident_number` and `dti_mode: fast_async`. Resolve that incident,
send the same payload again, and you should get a **different** incident number.

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
