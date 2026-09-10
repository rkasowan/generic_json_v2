# Generic JSON V2 Direct To Incident Linux Synthetic

Version: 1.1.0

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

Copy the `synthetic` directory to the Linux server, then run the idempotent interactive installer as root. It prompts once for the shared username, assignment group, failure-email recipient, sender, and SMTP relay, then prompts for each of four instance labels, URLs, and passwords:

```bash
cd synthetic
sudo ./install.sh
```

The installer writes `/etc/generic-json-v2-dti-synthetic/1.env` through `4.env`, mode `0600`. Re-run it to change a password, email setting, URL, username, or assignment group; a blank password keeps that environment's existing encoded password. It updates files and units in place and restarts all timers. `DTI_ASSIGNMENT_GROUP` accepts a group name or sys_id.

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
