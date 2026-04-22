# ATF Testing

The repo includes an idempotent ATF installer:

- `atf/install_usbem_atf.js`

Run that file as a **Background Script** on the target instance to create or refresh:

- the parent `USBEM` ATF suite
- the child `USBEM genericJsonV2 API Coverage` ATF suite
- the `USBEM_ATF_Helper` Script Include used by the test steps
- the `USBEM ATF Local Admin` basic auth profile when credentials are provided in the installer config
- all `USBEM genericJsonV2 - ...` test cases

## Why The Suite Uses Server-Side Steps

The suite exercises the real inbound endpoint:

- `POST /api/sn_em_connector/em/inbound_event?source=genericJsonV2`

It does that from ATF `Run Server Side Script` steps with `RESTMessageV2`.

That approach keeps the suite stable for same-instance authenticated calls and still validates the actual API path, payload parsing, lookups, waiting behavior, and DTI behavior end to end.

## Coverage

The installer creates tests for:

1. field mapping, generated `message_key`, and `additional_info` object handling
2. bulk `events[]` payloads and legacy escaped `additional_info` strings
3. assignment group resolution by sys_id, exact name, and canonical name
4. CI resolution by sys_id, exact name, canonical name, human-readable `ci_type`, and no-match blanking
5. duplicate-name CI preference rules
6. `usbem_car_id`, `usbem_service`, `usbem_offering`, and `svc_ci_assoc` service inference
7. `usbem_debug` companion debug event creation and lookup diagnostics
8. `usbem_wait_for_alert`
9. no-wait DTI single-incident enforcement and alert linking
10. DTI with synchronous incident creation
11. DTI suppression for severity-map non-incident values

The no-wait DTI test intentionally watches the record set for 30 seconds before asserting success so it can catch late duplicate incidents, not just the initial API response.

For debug coverage, the suite validates lookup diagnostics from the companion debug event attachments, especially:

- `04_lookup_trace.json`
- `06_correlation_hints.json`

That is the durable place to inspect verbose lookup traces. The main event `additional_info` only keeps the operational outputs.

## Install

1. Open `atf/install_usbem_atf.js`.
2. Review the `CONFIG` block at the top.
3. Choose one auth option:

- preferred: set `auth_profile_sys_id` to an existing `sys_auth_profile_basic`
- or: set `auth_profile_name` to an existing basic auth profile name
- or: provide `auth_profile_username` and `auth_profile_password` so the installer can create/update the profile
- or: provide `basic_auth_username` and `basic_auth_password` to use inline Basic Auth from the helper include instead of `setAuthenticationProfile(...)`

4. Run the full file in **System Definition > Scripts - Background**.

The installer also enables `sn_atf.runner.enabled` when `enable_runner_if_disabled=true`.

Inline basic auth is useful on instances where auth-profile password decryption is unreliable in server-side ATF execution. If you use that path, prefer a dedicated non-production ATF user.

## Run The Suite

After install:

1. Open **Automated Test Framework > Test Suites**
2. Open the parent suite `USBEM`
3. Open the child suite `USBEM genericJsonV2 API Coverage`
4. Run the child suite or any individual `USBEM genericJsonV2 - ...` test

## Re-Run Safely

The installer is designed to be re-run.

When `delete_existing_assets=true` it will:

- remove the previously installed `USBEM genericJsonV2 API Coverage` child suite
- remove previously installed `USBEM genericJsonV2 - ...` tests
- recreate the latest helper include and test definitions under the `USBEM` parent suite

The ATF test setup steps also clean up prior test events, alerts, incidents, and debug events for their fixed test message keys before each execution.

## Fixture Data

The suite provisions and reuses its own named fixture records with the `ZZ USBEM ATF ...` prefix, including:

- assignment groups
- CMDB server and VMware duplicates
- business applications
- services
- service offerings
- `svc_ci_assoc` mappings

That keeps the tests deterministic across reruns.

## Updating The Suite

If connector behavior changes:

1. update `atf/install_usbem_atf.js`
2. rerun the installer on the target instance
3. rerun the relevant tests or the full suite

Because the suite is recreated from the installer, the repo stays as the source of truth instead of relying on manual ATF edits in the instance.
