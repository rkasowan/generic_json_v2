# generic_json_v2 — project notes

Compact working state for the USBEM genericJsonV2 push connector. Detailed behaviour lives in
`README.md` and `docs/`; this file is what a future session needs before touching the PDI.

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

## Release 2026.09.28.1 (2026-09-28)

- alert work notes: posted once, through a fresh record with `setWorkflow(false)`, and the key is
  consumed from the alert's `additional_info`. The old code wrote through the business rule's own
  `current` and re-posted on every later alert write
- a DTI sender's plain `work_notes` goes to the incident only; `alert_work_notes` is the alert's
- long message keys: `correlation_id` now stores (and is queried by) a leading slice plus a stable
  FNV hash of the whole key, so keys over 100 characters stop opening an incident per event
- wait loops call `gs.sleep` between polls instead of spinning; scoped apps are allowed to sleep on
  Zurich (verified), and the spin is kept only as a fallback
- unknown payload field names come back in `incident_fields_skipped` instead of vanishing
- `--env-file` reads the named file, not the nearest `.env` beside it
- verification groups are now deploy / compat / fast / wait / fields / ci / notes / edge / timing

## Release 2026.09.25.3 (2026-09-25)

- every script stamps the release and the endpoint returns `versions` for listener + 4 includes;
  the business rule logs its version with each outcome
- incident creation matches the retired subflow: `u_netcool_ticket` true, category `Software`,
  subcategory `Monitoring Alert`, caller `Event Management`, `u_generating_alert`, alert group as
  the last-resort assignment group, connector work note + `Incident Created From <alert>`,
  duplicate note on reuse. Payload fields override all of it
- the fast path now claims an already-existing alert during the request
  (`claimAlertForFastIncident`), so a terminal-state relink no longer waits for the rule to fire
- `scripts/deploy_usbem.py` + `tests/usbem_verify.py`, both standard-library only

## Gotchas proven on this PDI

- **Scope fencing.** `x_usbna_usb_event` needs `incident` read+create+write and `cmdb_rel_ci`
  read; both were `requested` until 2026-09-28, when they were flipped to `allowed` (the user
  confirmed prod gives the scope full CRU). `sys_user` read is still denied and not needed — the
  default caller is set with `getElement('caller_id').setDisplayValue(...)` precisely to avoid
  that query. An uncaught fencing exception returns HTTP 500 and loses the event, so every
  cross-scope call in the DTI path stays wrapped and reports a skip.
- **Journal fields.** `work_notes` on both `incident` and `em_alert` only accept dot assignment;
  `setValue()` is silently dropped.
- **`u_netcool_ticket`** and **`u_generating_alert`** (reference → `em_alert`, added by the user
  on 2026-09-28) both exist on the PDI incident table and are verified on the wait path and the
  fast path.
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
python3 tests/usbem_verify.py     # 9 groups, self-cleaning, one file, no dependencies
```

Last full run 2026-09-25: all groups pass; the duplicate work note reports
`skipped: no_write_access_to_incident`, which is the scope privilege above, not a code fault.
