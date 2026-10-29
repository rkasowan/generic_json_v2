# Generic JSON V2 extended DEV validation — 2026-10-29

Extended stress result: **FAIL — concurrent first-event DTI can create duplicate incidents.**

The CI identifier precedence correction and required-field checks pass the exercised live cases.
The owner accepted the simultaneous-first-event limitation on 2026-10-29 and explicitly selected
the fast API plus correlation-based Business Rule design without a new claim table. Standard
acceptance covers sequential duplicates; it makes no concurrent-first-event guarantee.

## Live method and duration

- Target: `dev392825`, installed connector release `2026.10.29.1`.
- Actual `POST /api/sn_em_connector/em/inbound_event?source=genericJsonV2` requests through the
  authenticated browser session, with the listener's `genericendpoint` User-Agent.
- Readback through the Table API for `em_event`, `em_alert`, and `incident`.
- Run marker: `USBEM-EXT-1793277833901`.
- Started `2026-10-29T12:43:53.901Z`; finished `2026-10-29T12:48:17.687Z`.
- Total elapsed: **263.786 seconds**. Poll interval: five seconds.
- The nine original cases had 41 observations spanning 204.805 seconds. The later concurrency
  case had 34 observations spanning 164.884 seconds. Final readback was 168.508 seconds after
  settled duplicate replay and concurrent submission finished.
- Every submitted event was processed. Every response was HTTP 200 and reported all five
  components at `2026.10.29.1`. Those facts alone did not constitute a pass.
- All tagged events, alerts, and incidents were retained. No production instance was accessed.

The primary CI was `Car-1` (`6cabe993c611222500bb025775ec8732`), selected by
`ci_type=cmdb_ci_server` and `serial_number=478933-e78-8823`. Preflight found one CI with that
serial. The distinct name control was `*ANNIE-IBM`
(`b4fd7c8437201000deeabfc8bcbe5dc1`, class `cmdb_ci_computer`).

## Results

This exploratory matrix includes legacy wait-key compatibility cases. New integrations use
the fast path exclusively; the strengthened laptop suite sends no wait keys. The additional
fast-only required-field validation is documented separately below.

| Case | Posts / stored events | Stored incidents | Result |
|---|---:|---|---|
| Identifier-only, wait mode | 2 / 2 | `INC0010005` | Pass; primary CI |
| Name-only fixture control | 2 / 2 | `INC0010006` | Pass; decoy CI |
| Conflicting name + camelCase identifier, fast mode | 3 / 3 | `INC0010007` | Pass; primary CI, immediate and settled duplicates reused it |
| Conflicting name + snake_case identifier, wait mode | 2 / 2 | `INC0010008` | Pass; primary CI, settled duplicate reused it |
| Explicit CI sys_id + conflicting identifier, fast mode | 2 / 2 | `INC0010009` | Pass; explicit decoy sys_id stayed authoritative |
| Missing identifier + name fallback | 2 / 2 | `INC0010010` | Pass; decoy CI |
| Wrong CI class + name fallback | 2 / 2 | `INC0010011` | Pass; decoy CI |
| Severity 5 with DTI requested | 1 / 1 | None | Pass; incident suppressed |
| Severity 0 with DTI requested | 1 / 1 | None | Pass; incident suppressed |
| Three simultaneous first events, one fast-DTI key | 3 / 3 | `INC0010012`, `INC0010013` | **Fail; two incidents for one key** |

Correct CI values and alert-to-incident links remained stable throughout observations in the
nine passing cases. Initial wait-mode requests took 8.035–9.990 seconds; sequential replays took
0.193–0.339 seconds. The fast conflict request took 0.468 seconds. A quick response can therefore
be legitimate while still being insufficient evidence of correct delayed behavior.

## Concurrency defect and production gate

The failing key is `USBEM-EXT-1793277833901-concurrent_three_fast`.
Three successful responses returned `INC0010013`, `INC0010012`, and `INC0010012`.
The final alert was linked to `INC0010012`, while both incidents remained open with the correct
CI. This is a duplicate-creation race, independent of the CI precedence correction.

`getOrCreateFastIncident` queries for an existing incident, then inserts when none is visible.
Two requests can both complete the query before either insert is visible. Sequential replay
does not exercise that interval. The older full verifier's concurrent case was observational
(`passed=None`); the strengthened laptop suite's optional concurrency check treats this outcome
as a failure. Enable it explicitly with `--include-concurrency`.

The existing optional DTI map is not configured and no map table exists on this DEV instance.
Enabling its property alone is not a safe correction: it lacks validated schema and uniqueness,
safe ownership transitions, and terminal-incident handling.

A durable correction needs an atomic database claim shared by both fast and wait creation paths,
with a unique per-key record, verified owner token, open-incident reuse, safe terminal-generation
transition, and fail-closed behavior on uncertain ownership. A reviewed adjacent implementation
uses a unique SHA-256 key plus deterministic registry sys_id. Adopting that pattern here adds
scoped schema, installer, privileges, rollback, and production-transfer requirements. A second
lookup or deletion of a losing incident cannot retract notifications or Flows already triggered
by its insert. This expansion was declined by the owner; no new table or mutex was added.
The delivered design retains this documented race rather than claiming exactly-once creation.

## Fast-only required Incident fields

Two additional actual HTTP checks used no wait keys and reported `dti_mode=fast_async`:

| Case | Incident | HTTP round trip | Caller source |
|---|---|---:|---|
| Explicit affected end user | `INC0010014` | 1.868 seconds | Payload `caller_id` |
| Configured caller fallback | `INC0010015` | 0.484 seconds | Per-instance default property |

Both had exact stored values for all seven required fields: `caller_id`, `category`,
`subcategory`, `impact`, `urgency`, `short_description`, and `description`. The expected CI,
Hardware assignment group, correlation breadcrumb, and later alert-to-incident link were also
verified. Thirteen observations per incident spanned 96.629 and 96.640 seconds with no drift.
The requests began at `2026-10-29T12:54:21.513Z`; final readback was
`2026-10-29T12:57:16.522Z`.

Follow-up sequential replays returned the same `INC0010014` and `INC0010015` in 0.389 and
0.193 seconds. Their later field/link observations continued to pass. A third fast-only
snake_case case created `INC0010016` in 1.096 seconds and replayed it in 0.292 seconds.
At the first read, 7.483 seconds after submission, all required fields were correct while the
alert had not landed yet. Once the alert arrived, it linked to that same Incident; the linked
CI and all required fields then remained correct over 67.260 seconds. This is the intended
separation between a prompt API response and later Business Rule reconciliation.

The default caller property was missing on this clean DEV install. It is now configured as
`x_usbna_usb_event.default_caller_sys_id=9d5de9e5930022005bc5f179077ffb07`, the existing active
Event Management integration user. That sys_id is instance-specific.

The explicit test used DEV-valid stored choices `category=software`, `subcategory=os`,
`impact=2`, and `urgency=2`. The connector's customer-oriented defaults `Software` /
`Monitoring Alert` and severity-4 values `4` are not installed OOB choices on this PDI.
Production choices must be configured from production metadata in the test env; this work
did not change those runtime defaults or redefine the customer's severity policy.

## Installed-source readback

The stored source of all six runtime records matched the local release files byte-for-byte:

| Component | SHA-256 |
|---|---|
| Core | `35a8b7819025f5ff6b4a7083213d4af2f3a828412c515206e4b253cf0c7bd31e` |
| Lookups | `b89e37d56176719c21c9336c8d4ed11267dc25bf2d41c162352cf8a81e182575` |
| Debug | `e9ac18b1e6c1bd3521582ca744cb59dacdc3a9865cf6ffc87862b52b8bca9c1f` |
| DTI | `a8efe2b5300784ea0558b57470d4b6f6df4d9d1c33882374b14801aa2e566c6e` |
| Listener | `c2797bdb5f732da917d798c2427ed5748dcf73966d3485079cac78e6373ebb46` |
| Reconcile rule | `59bd4e9cbbf43944dbb1ab32e49aa0b1d23a69e95716144d4bebc08ef8c316bb` |

## Limits

This DEV run used the signed-in browser identity, not the customer's production OAuth identity.
It did not test email delivery, production ACLs, production-specific Incident Business Rules,
terminal-incident lifecycle, or sustained load. Invalid or ambiguous identifier fallback remains
the existing documented policy; the CI fix does not redefine that policy. Passing observations
over a bounded window cannot guarantee that no unrelated process will change the records later.
