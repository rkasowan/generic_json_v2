# Manual transfer package — genericJsonV2 connector, release 2026.10.29.2

The source/configuration package to move between instances. Update sets are not the source of
truth here; git is. The six source files below define the runtime. Historical dev382837 IDs are
record locators only, not portable identities or proof that that instance runs this release.
`scripts/deploy_usbem.py` updates the known records, can create a missing reconcile BR, and
verifies stored source and configuration after each write.

Source of truth: `rkasowan/generic_json_v2`, coherent release commit for `2026.10.29.2`.
Release gate: **corrected-path DEV retest PASS** on dev392825; see
[release evidence](validation-2026-10-29.2.md). The earlier
[comprehensive validation](validation-2026-10-29-comprehensive.md) remains historical failure
evidence. Production identity, local rules/fixtures, and the accepted concurrency limitation
still require target-specific acceptance.

## 1. Records to move

| # | Table | Record | sys_id (dev382837) | Source file |
|---|---|---|---|---|
| 1 | `sys_script_include` | `USBEM_Core` | `e2734f2bc38c4f100bc1b91ed401319c` | `src/USBEM_Core.js` |
| 2 | `sys_script_include` | `USBEM_Lookups` | `8063cba7c38c4f100bc1b91ed401310a` | `src/USBEM_Lookups.js` |
| 3 | `sys_script_include` | `USBEM_Debug` | `ae23cba7c38c4f100bc1b91ed4013117` | `src/USBEM_Debug.js` |
| 4 | `sys_script_include` | `USBEM_DTI` | `5643c32bc38c4f100bc1b91ed40131e7` | `src/USBEM_DTI.js` |
| 5 | `sn_em_connector_listener` | `USBEM genericJsonV2` | `ec08e3e7c3848f100bc1b91ed40131ef` | `servicenow/USBEM_genericJsonV2.listener.js` |
| 6 | `sys_script` | `USBEM Fast DTI Alert Reconcile` | `26dcd72193a78710c8ebf85bdd03d613` | `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js` |

All four Script Includes are in scope `x_usbna_usb_event`, **Accessible from: All application
scopes**, not client callable. The listener and the business rule are global.

Every one of these scripts carries the release version, and the endpoint returns all of them in
its `versions` response block. After the transfer, push one event at the target and check that
block before believing anything else.

### The business rule's configuration is part of the package

| Field | Value |
|---|---|
| Table | `em_alert` |
| When | `after` — **not async** |
| Insert / Update | true / true |
| Order | 150 |
| Advanced | true |
| Active | true |

```javascript
((current.getValue('additional_info') || '').indexOf('work_notes') > -1 ||
 ((current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1 &&
  (current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)))
```

Event Management best practices prohibit async business rules on alert tables. If the rule already
exists in the target, check its `when`, Advanced flag, and condition before overwriting the script.
Pending Alert notes must run even with an open linked Incident; DTI-only metadata remains gated
by nil/terminal Incident state. Copy this exact condition from `scripts/deploy_usbem.py`'s
`BR_CONDITION`, not an older update set. Read back the stored rule after creation or update;
the deployer fails on a missing record ID or mismatched script/configuration.

## 2. Create in the target, do not export

`cmdb_ci.u_level_2_support_assignee_group` and `cmdb_ci.u_level_3_support_assignee_group`, both
`reference` → `sys_user_group`.

Do not hand-export them. Adding a column to `cmdb_ci` propagates a dictionary entry **and** a
label record to every CI class: on dev382837 that is **1,334 `sys_dictionary` rows and 1,334
`sys_documentation` rows per field** — 5,336 records for the pair. Let the platform generate them:

    servicenow/install_ci_support_tier_fields.background.js

Idempotent. **Run it from Scripts – Background in the UI, not over HTTP** — a client timeout cuts
the transaction short. Expect minutes, and a slow instance while it runs.

## 3. Properties — defaults plus the per-instance caller fallback

| Property | Value |
|---|---|
| `x_usbna_usb_event.dti_terminal_incident_states` | `6,7,8` |
| `x_usbna_usb_event.dti_duplicate_work_note` | `true` |
| `x_usbna_usb_event.default_caller_sys_id` | a valid caller sys_id for this instance |

`x_usbna_usb_event.default_assignment_group_sys_id` is no longer read. If the target sets it, that
value stops taking effect — intended: an incident with no resolvable group is left unassigned.

## 4. Do not move

| Table | Record(s) | Why |
|---|---|---|
| `em_match_rule` | `cghfvghjk`, `Junk Rule`, `Do Something Dumb`, `This will break everything` | PDI-only junk rules with empty filters and `ignore_event=true`, deactivated 2026-09-18. They suppressed **all** alert creation. Exporting them would recreate them |
| `sysevent_script_action` | `link_alert_later` | the retired async linker. Deactivated, not part of this design |
| `sysevent_register` | `x_usbna_usb_event.link_alert_later` | same |
| `sys_dictionary` / `sys_documentation` | the 5,336 per-class rows for the two CI fields | generated by section 2 |
| `sys_ui_section` | `90fe4db4c0a801640043b5bbfcdac216` | incidental CI form layout change. Move only if you want the fields on the form |

## 5. Environment-specific — re-check in the target

- **Incident fields.** `u_netcool_ticket` (boolean) and `u_generating_alert` (reference →
  `em_alert`) must exist on `incident`, or those two mappings are skipped without failing the
  event. Both exist on dev382837 and are verified there as of 2026-09-28.
- **Caller sys_id.** Set `x_usbna_usb_event.default_caller_sys_id` to the intended fallback user in
  each target instance. Exact full-name `caller_id` / `assigned_to` inputs use scoped `sys_user`
  read; an ambiguous or unresolved caller uses this configured fallback. An unresolved assignee is
  left blank so on-call assignment can populate it. The API verifier reads only Incident/Alert.
- **Category and subcategory.** The defaults are the literals `Software` and `Monitoring Alert`.
  Where the choice exists they resolve to its value; where it does not, the literal is written.
  dev382837 has no `Monitoring Alert` choice, so it stores the literal.
- **Cross-scope privileges.** `x_usbna_usb_event` runs with `runtime_access_tracking = enforcing`
  and needs `incident` read+create+write, `sys_user` read for full-name resolution, and
  `cmdb_rel_ci` read. Without the incident write the
  duplicate work note and post-creation `u_generating_alert` are skipped and reported; without
  `cmdb_rel_ci` read, CI-derived assignment groups cannot work at all. Both were granted on
  dev382837 on 2026-09-28. The rows usually exist already with status `requested` — flip them to
  `allowed` rather than creating new ones.
- **Optional debug attachments.** Enabling `usbem_debug` attachments additionally requires the
  exact scriptable privilege `GlideSysAttachment.write / execute` for `x_usbna_usb_event` in each
  target. DEV's existing requested row was approved for testing; that approval is not portable.
  Review and approve the target's exact requested privilege rather than exporting DEV's row or
  granting broad attachment/table access. Read back a resulting attachment when testing debug.
- **Group references.** Nothing hardcodes a group, but the CI fields point at `sys_user_group`
  records whose sys_ids differ per environment. CI data is not part of this package.

## 6. Verify after transfer

```bash
python3 tests/usbem_verify.py
```

For a production selection the verifier defaults to limited access, submits events, checks
Incident/Alert readback, and retains tagged records. A custom target defaults to self-cleanup.
Run `python3 scripts/deploy_usbem.py --dry-run` to compare the target's source records with this
checkout; the verifier's `compat` group checks the endpoint's reported component versions.

For the standalone work-laptop acceptance test, configure target-specific fixtures using
`tests/ci_identifier_test.env.example` and run:

```bash
python3 tests/test_ci_identifier_precedence.py --report-file ci-test-report.json
```

The default ten fast-only cases cover flat CI precedence, sequential duplicates, required
Incident fields, and all five single-record wrappers. They retain twelve Events and expect ten
Incidents. Twelve observation phases at 30 seconds require at least six minutes plus request
time. The test needs connector access plus `em_event` and `incident` read; it does not inspect
Alert links, so validate BR linking and Alert-note journaling separately with an authorized
identity. Optional `--include-concurrency` remains a stress check that fails if simultaneous
first requests return/create different Incidents; the owner accepted this known race without a
claim table. Do not interpret the default suite as proof of concurrency safety.
