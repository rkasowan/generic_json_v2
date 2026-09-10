# Changelog

All notable project updates should be recorded here when work is completed and pushed.

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
