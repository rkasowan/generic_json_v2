# Generic JSON V2 Direct To Incident Linux Synthetic

Version: 1.1.1

## Purpose

Install this five-minute systemd synthetic against four production instances to validate the real Generic JSON V2 inbound Event Connector path, DTI incident creation, and duplicate-event incident reuse. Each environment runs independently. A passing run removes its temporary test incident and emits a severity-5 OK event. A failing run sends email and creates a separate actionable DTI incident.

## Prerequisites

- Python 3.9 or newer; no third-party packages are required.
- HTTPS reachability to the ServiceNow instance.
- An integration identity that can post to `/api/sn_em_connector/em/inbound_event?source=genericJsonV2` and read `em_event` and `incident` through the Table API.
- The same identity must be allowed to delete only the synthetic incident it just created; this prevents passing checks from leaving incidents behind.
- An SMTP relay and failure recipient.
- The `genericJsonV2` connector and DTI components are installed and active.
- Store the password in a root-readable environment file or inject it from the server's approved secret manager. Never commit it.

## Install

Copy the `synthetic` directory to the Linux server, then run the idempotent interactive installer as root. It prompts once for the shared username, assignment group, failure-email recipient, sender, and SMTP relay. For each unconfigured environment, an empty instance URL skips that slot. Configure DEV in slot 1 and press Enter at the URL prompts for slots 2–4:

```bash
cd synthetic
sudo ./install.sh
```

The installer writes one mode-`0600` file per configured slot under `/etc/generic-json-v2-dti-synthetic/`. Re-run it for the progression DEV, DEV/IT, DEV/IT/UAT, and finally DEV/IT/UAT/PROD. Existing URLs appear as defaults and a blank password keeps that slot's current encoded password; enter a URL only for the next environment being added and leave later URLs empty. The installer updates files and units in place and restarts only configured timers. `DTI_ASSIGNMENT_GROUP` accepts a group name or sys_id.

Credentials are base64 encoded in the environment files. Base64 is reversible encoding, not encryption or hashing, so retain root-only permissions and use an approved secret manager where required.

Run and inspect it immediately:

```bash
sudo systemctl start generic-json-v2-dti-synthetic@1.service
sudo systemctl status generic-json-v2-dti-synthetic@1.service
sudo journalctl -u generic-json-v2-dti-synthetic@1.service -n 20 --no-pager
```

## What a passing run proves

Each run creates a unique `message_key` and sends the same event twice. Exit code `0` requires all of the following:

- both connector calls return an event sys_id;
- at least two `em_event` rows are readable for the message key;
- exactly one temporary `incident` exists with `correlation_id` equal to that message key;
- both connector responses identify the same incident;
- the response incident matches the live incident read through the Table API;
- the temporary incident is deleted after validation; and
- a non-DTI severity-5 OK event is created.

Exit code `2` means a functional assertion failed. Exit code `3` means configuration, authentication, transport, or response parsing failed. The service writes one non-secret JSON result to stdout for collection by journald or a monitoring agent.

## Operations

Four template timers (`@1` through `@4`) run every five minutes as root. Successful runs leave their probe events and final severity-5 OK event as audit evidence but remove the temporary incident. Identify records by event source `Generic JSON V2 DTI Synthetic` and the `synthetic-generic-json-v2-` message-key prefixes.

On a failed assertion, the synthetic posts a new DTI failure event using `DTI_FAILURE_SEVERITY`, `DTI_ASSIGNMENT_GROUP`, and a distinct failure message key, then sends email through the configured SMTP relay. If the connector itself is unavailable, the incident may also fail; the independent SMTP attempt still provides an alternate notification path.

Monitor the systemd unit's exit status. Alert on one failure after accounting for planned ServiceNow maintenance; escalate repeated failures to the Event Management connector owner with the emitted `run_id`, `message_key`, failed checks, HTTP status if present, and relevant ServiceNow transaction logs. Do not include the password in tickets or logs.

## Laptop regression test and current validation gate

The attachments `test_ci_identifier_precedence.py` and `ci_identifier_test.env.example` are the
current standalone laptop suite. Download both, copy the template to `ci_identifier_test.env`,
and configure the target instance, credentials, two distinct CI fixtures, affected-end-user
sys_id, valid category/subcategory choices, impact, urgency, and optional assignment group.

```bash
python3 test_ci_identifier_precedence.py --report-file ci-test-report.json
```

The normal contract is fast DTI: create an Incident, stamp the message key in `correlation_id`,
return its sys_id promptly, then let the alert Business Rule link the alert after it arrives.
The laptop suite omits all wait keys. The wait key is retained only for legacy callers.

The test checks six cases: name and identifier fixture controls, explicit CI sys_id precedence,
camelCase and snake_case conflicting-name inputs, sequential duplicate reuse, and three
simultaneous first events. Every stored Incident must have the expected CI, caller, category,
subcategory, urgency, impact, short description, description, and correlation breadcrumb.
Configured assignment groups are verified by sys_id. The script uses connector POST and read
access to `em_event` and `incident`; it retains all records and does not require deletion access.

Allow at least four minutes for a complete passing run: each of eight phases requires 30 stable
seconds, separately from the prompt POST response. Timeouts and observation windows are
configurable. Basic/base64 and OAuth credentials and corporate CA bundles are supported.
An incomplete or failed check cannot return PASS. Exit codes are 0 pass, 2 functional failure,
and 3 configuration/access/transport error. It does not test email delivery.

Current gate: extended actual HTTP testing on dev392825 took 263.786 seconds and confirmed the CI
precedence fix, but three concurrent first fast-DTI events created two Incidents (`INC0010012`
and `INC0010013`). Sequential duplicates reused one Incident. The strengthened laptop test
fails this race. Hold production promotion until a concurrency correction is validated.
The attached `validation-2026-10-29.md` records the live method, results, retained evidence, and
limits. Production-specific identities, rules, choices, and field access still need target testing.

## Security and rollback

Each template unit runs as root, as required, with systemd hardening and reads its matching root-only `/etc/generic-json-v2-dti-synthetic/<index>.env` file. Use a least-privilege ServiceNow integration identity and rotate its password through the approved secret process.

To disable and remove the service:

```bash
sudo systemctl disable --now generic-json-v2-dti-synthetic@{1,2,3,4}.timer
sudo rm /etc/systemd/system/generic-json-v2-dti-synthetic@.service
sudo rm /etc/systemd/system/generic-json-v2-dti-synthetic@.timer
sudo rm -r /opt/generic-json-v2-dti-synthetic
sudo rm -r /etc/generic-json-v2-dti-synthetic
sudo systemctl daemon-reload
```

Remove `/etc/generic-json-v2-dti-synthetic.env` separately after confirming its credential is no longer needed.
