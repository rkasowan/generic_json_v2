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

## Release 2026.09.25.3 (2026-09-25)

- every script stamps the release and the endpoint returns `versions` for listener + 4 includes;
  the business rule logs its version with each outcome
- incident creation matches the retired subflow: `u_netcool_ticket` true, category `Software`,
  subcategory `Monitoring Alert`, caller `Event Management`, `u_generating_alert`, alert group as
  the last-resort assignment group, connector work note + `Incident Created From <alert>`,
  duplicate note on reuse. Payload fields override all of it
- the fast path now claims an already-existing alert during the request
  (`claimAlertForFastIncident`), so a terminal-state relink no longer waits for the rule to fire
- `scripts/deploy_usbem.py` + `tests/verify_usbem_connector.py` + `requirements.txt`

## Gotchas proven on this PDI

- **Scope fencing.** `x_usbna_usb_event` can create incidents but **not update** them; `sys_user`
  and `cmdb_rel_ci` reads are denied. An uncaught fencing exception returns HTTP 500 and loses the
  event, so every cross-scope call in the DTI path is wrapped and reports a skip. The default
  caller is set with `getElement('caller_id').setDisplayValue(...)` precisely to avoid a
  `sys_user` query.
- **Journal fields.** `work_notes` on both `incident` and `em_alert` only accept dot assignment;
  `setValue()` is silently dropped.
- **`u_netcool_ticket`** exists on the PDI incident table; **`u_generating_alert` does not**, so
  that mapping is code-complete but unverified here. It is in the customer dictionary dump.
- **Choice values.** The PDI has no `Monitoring Alert` subcategory choice, so `setChoiceLike`
  falls back to writing the literal, which is what the subflow did.
- **`sys.scripts.do` echoes the script source** above its output, so a marker-based background
  script runner must try every marker occurrence, not the first.
- **Wait mode** gives up after `usbem_wait_seconds` (15 default) with
  `dti_incident_status=alert_not_found`. A degraded PDI needs more; the verifier asks for 45.
- Endpoint round trips while the PDI was degraded, 2026-09-25: plain ~3.7 s, fast ~6–8 s, wait
  ~16–18 s.

## Verification

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/deploy_usbem.py          # deploy + read live versions back
python3 tests/verify_usbem_connector.py  # 7 groups, self-cleaning
```

Last full run 2026-09-25: all groups pass; the duplicate work note reports
`skipped: no_write_access_to_incident`, which is the scope privilege above, not a code fault.
