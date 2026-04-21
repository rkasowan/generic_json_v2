# Changelog

All notable project updates should be recorded here when work is completed and pushed.

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
