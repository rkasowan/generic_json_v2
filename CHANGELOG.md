# Changelog

All notable project updates should be recorded here when work is completed and pushed.

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
