# Changelog

All notable project updates should be recorded here when work is completed and pushed.

## 2026.09.25.3 - 2026-09-25

- every script carries a version and every response reports them: `versions` on the endpoint
  envelope covers the listener and all four Script Includes, `dti_version` rides on the DTI
  result, and the business rule logs its version with each outcome
- matched the retired "EM - Generic Endpoint Create Incident" subflow's field mapping on every
  incident this connector creates: `u_netcool_ticket = true`, category `Software`, subcategory
  `Monitoring Alert`, caller `Event Management`, `u_generating_alert` pointed at the alert, the
  alert's group as a last-resort assignment group, and the work note
  "Direct To Incident Via Event Management Generic JSON Endpoint / Incident Created From <alert>"
- reproduced the subflow's duplicate branch: an event folded into an existing incident adds a
  duplicate work note, switchable with `x_usbna_usb_event.dti_duplicate_work_note`
- payload fields still win over all of it, and `work_notes` / `comments` are now written as
  journal entries instead of being dropped by the generic passthrough
- made the defaults fence-safe: a scope denied read on `sys_user` or write on `incident` loses
  that one field and reports it in `incident_defaults_skipped` / `incident_work_note`, instead of
  failing the event with `ScopeAccessNotGrantedException`
- added `scripts/deploy_usbem.py` (push the repo at an instance, read back live versions),
  `scripts/usbem_client.py` and `requirements.txt`; the Python tooling now uses `requests` and
  certifi, which fixes the macOS venv `CERTIFICATE_VERIFY_FAILED` failures, and honours
  `SN_CA_BUNDLE` / `SN_VERIFY_SSL`
- replaced `tests/dti_terminal_incident_check.py` with `tests/verify_usbem_connector.py`: seven
  selectable groups covering version/drift, the original connector contract, both DTI paths,
  field mapping, work notes on both records, and timing
- tightened the reconcile rule's condition to the alerts this connector owns, and removed
  `src/USBEM_genericJsonV2.js`, the second copy of the listener script

## 2026.09.25.2 - 2026-09-25

- rebuilt the genericJsonV2 listener as a thin script that calls the Script Includes; the deployed build had inlined its own copies and drifted, so REST callers were running months-old logic (171 KB down to 4 KB)
- `direct_to_incident` now returns an incident in the same response without waiting; `dti_wait_for_incident` keeps the original polling behaviour
- any incident field can be sent under its real name (`caller_id`, `category`, `subcategory`, `contact_type`, ...), resolved by sys_id or display value, reported back as `incident_fields_applied` / `incident_fields_skipped`
- work notes work on both records: `work_notes` on the incident, `alert_work_notes` on the alert, and the documented `dti_work_note` works again
- fixed journal writes: `work_notes` is a journal_input, where `setValue()` is silently dropped, so `dti_work_note` had never actually written anything
- retired the queued `link_alert_later` event, its Script Action and the retry loop; nothing creates sys_events any more
- the alert reconcile business rule is synchronous `after` with a condition, per "Do not write async business rules for alert tables"
- removed `src/USBEM_genericJsonV2_Full.js`, the inlined build that caused the drift

## 2026.09.25.1 - 2026-09-25

- stopped DTI reusing an incident once it is Resolved, Closed or Canceled: the next event for the key opens a new incident, later events reuse that one, and the alert is moved across
- added `x_usbna_usb_event.dti_terminal_incident_states` (default `6,7,8`, integer states only, `0` acts as a kill switch) and excluded terminal states in the correlation query
- made every alert write a conditional claim on the exact link inspected, so a foreign task, a Closed alert's incident or a concurrent writer is never overwritten
- added distinct statuses and trace lines for terminal skips and relinks
- fixed the async link retry, which had never run: script action parameters arrive as GlideElements so the payload was dropped and the retry cap never tripped, and scoped `GlideDateTime` has no `addSecondsLocalTime`, so retries re-queued with no delay. It now stops after the configured retries, spaced by the configured delay
- repaired the `link_alert_later` Script Action source, which was stored with literal `\n` sequences and never compiled, and the event registration name
- resolved the incident assignment group from the event's `assignment_group`, then `cmdb_ci.support_group`, then `cmdb_ci.u_level_2_support_assignee_group`, and removed the default/placeholder group so an unresolved incident is left unassigned
- a group named on the event is no longer overridden by CI data, and the CI is only read when the event did not name one
- added an idempotent installer for the two CI support tier reference fields
- added `tests/dti_terminal_incident_check.py`, a self-cleaning live check, and `docs/dti_transfer_package.md` for manual export

## 2026.09.10.2 - 2026-09-10

- allowed staged rollout by treating an empty instance URL as a skipped slot
- kept installer reruns idempotent so later runs can add remaining instances or update shared settings and credentials

## 2026.09.10.1 - 2026-09-10

- added a hardened five-minute Linux systemd synthetic for the Generic JSON V2 DTI path
- validated duplicate DTI events by requiring two live events to converge on exactly one correlated incident
- removed successful probe incidents and emitted a severity-5 OK event; failures create a separately assigned DTI incident and SMTP email
- added configurable assignment group and SMTP settings, tests, Knowledge source, and production-transfer inventory

## 2026.04.22.4 - 2026-04-22

- kept no-wait DTI incident-first and fast while adding an async `em_alert` reconciliation rule for reliable post-response alert attachment
- taught correlation-id incident selection to prefer the original USBEM DTI incident so late duplicates can be relinked back to the fast incident
- added the deployable business-rule artifact under `servicenow/USBEM_FastDtiAlertReconcile.business_rule.js`

## 2026.04.22.3 - 2026-04-22

- kept the no-wait DTI path incident-first and immediate so API responses stay fast
- removed the broken `ScheduleOnce` experiment from async alert linking and restored the delayed event / Script Action path
- fixed `dti_link_status` reporting so failed queue attempts cannot be reported as successful

## 2026.04.22.2 - 2026-04-22

- restored the no-wait DTI path to immediate `fast_async` incident-first behavior so API responses stay fast again
- kept the safer async relink logic so late duplicates with the same `message_key` / `correlation_id` can be steered back to the original fast incident
- updated the no-wait ATF coverage to assert the immediate `fast_async` response contract as well as the delayed single-incident outcome
- rewrote the docs to describe the returned-fast / link-later behavior instead of the temporary inline alert wait flow

## 2026.04.22.1 - 2026-04-22

- fixed no-wait DTI so it no longer creates an incident ahead of the alert and then races alert-side automation into a duplicate
- added an inline alert-first no-wait window, controlled by `x_usbna_usb_event.fast_dti_inline_wait_seconds`, with deferred alert-first fallback when the alert is not ready yet
- updated DTI incident reuse so existing incidents found by `correlation_id` are claimed onto the alert instead of creating a second incident
- expanded the ATF helper and no-wait DTI coverage to assert one linked incident after the delayed duplicate window
- documented the new no-wait DTI behavior, async fallback, and troubleshooting guidance

## 2026.04.21.4 - 2026-04-21

- added `atf/install_usbem_atf.js`, an idempotent Background Script installer that provisions the USBEM genericJsonV2 ATF suite, helper include, auth-profile hookup, and inline Basic Auth fallback
- added `docs/atf_testing.md` with install, rerun, and execution guidance for the ATF coverage suite
- documented the ATF assets in the main README and environment notes so repo-based testing stays tied to the project source of truth

## 2026.04.21.3 - 2026-04-21

- reshaped `src/` to the six-file test bundle layout: `USBEM_Core`, `USBEM_Lookups`, `USBEM_Debug`, `USBEM_DTI`, `USBEM_genericJsonV2`, and `USBEM_genericJsonV2_Full`
- moved the locked standalone transform artifact to `standalone/genericMappedJson_transform.js` so `src/` only contains the active modular and full test sources
- generated `USBEM_genericJsonV2_Full.js` by inlining the modular listener plus all four script include components for environment testing

## 2026.04.21.2 - 2026-04-21

- split the repo back into the live modular `genericJsonV2` layout with separate `USBEM_Core`, `USBEM_Lookups`, `USBEM_Debug`, and `USBEM_DTI` script includes
- added the thin `USBEM_genericJsonV2_listener.js` wrapper so the repo matches the PDI deployment model
- removed the old single-file `USBEM_Core.genericJsonV2.salesforce_peru.js` backup path in favor of the four maintained script include sources

## 2026.04.21.1 - 2026-04-21

- added `cmdb_ci` canonical/token name lookup so CI names like `money_movement` can resolve to CMDB records with spaces and symbols
- added CI class-preference scoring so duplicate names prefer higher CSDM / dependency-tree classes such as business apps over services and servers over VMware instances
- documented the new CI lookup behavior and clarified that unresolved CIs are left blank

## 2026.04.16.1 - 2026-04-16

- added repo-level release tracking with `VERSION` and `CHANGELOG.md`
- renamed the local project directory to `generic_json_v2` to match the GitHub repository name
- documented that repo release history is separate from the locked platform transform version

## 2026.04.15.1 - 2026-04-15

- initialized the GitHub project and imported the generic mapped JSON connector bundle
- preserved the stock transform file version `2026-03-18a` for the final production path
- retained the backup `USBEM_Core.genericJsonV2.salesforce_peru.js` reference for lab and PDI-only work
