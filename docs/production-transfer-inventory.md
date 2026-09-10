# Production Transfer Inventory

## Linux assets

- `synthetic/generic_json_v2_dti_synthetic.py`
- `synthetic/generic-json-v2-dti-synthetic@.service`
- `synthetic/generic-json-v2-dti-synthetic@.timer`
- `synthetic/generic-json-v2-dti-synthetic.env.example`
- `synthetic/install.sh`

## ServiceNow dependencies

- Active Instance push connector URL parameter `genericJsonV2`
- Generic JSON V2 DTI runtime already supplied by this repository
- Integration identity authorized for the inbound Event Connector endpoint and read access to `em_event` and `incident`
- Published Knowledge article sourced from `kb/generic_json_v2_dti_linux_synthetic.md`

Instance URLs, credentials, sys_ids, users, roles, and Knowledge numbers are environment-specific and are not portable artifacts.
