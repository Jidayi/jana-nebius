# ingest

Telemetry, crash-report and support-bundle intake (`ingest`; ARC-16 `services/ingest/`, TABLE OPS-17a). It receives
what the core's outbox uploads and what a person uploads for a support ticket, and keeps it only as long as its
rules allow.

- `POST /v1/outbox/{kind}` (`crash_report`, `telemetry`): the core's outbox (`agent_core/net/outbox.py`) sends each
  approved crash report (OBS-17) and the daily telemetry report (OBS-20) here, with its idempotency key and **no
  credential or device identifier** (SEC-21; a request carrying one is refused). Telemetry is validated against the
  `cloud/outbox` contract's `Telemetry` (the `trace/telemetry` report), a crash report against its `CrashReport` and
  the redaction scanner (both bundled as `ingest.contracts` by `python -m jana_tools codegen`, so the core's outbox and
  the ingest check the same shapes). Replies are the contract's `OutboxReceipt` and `OutboxError` (D99). `201` kept, `409` seen already (the outbox counts both as delivered), any other refusal keeps
  nothing. Reports keep their UTC day of arrival only.
- `GET /support` and `PUT /v1/support/tickets/{ref}/bundle`: the support upload page (OPS-24). Support opens a ticket
  and gives its reference to the family; they upload the report file the app saved. A plain report is re-scanned and
  its manifest checked; a passphrase-sealed one (with a conversation) is kept as it came and opened only by an L3
  assignee naming the defect. Both are stored AES-GCM encrypted under the storage key.
- `/admin/v1/...`: staff, each with their own bearer token: tickets, holds for child-safety incidents (OPS-31),
  opening bundles, the access log, deletion requests (PRV-10) and the received reports for the dashboards (OBS-21).
  Every call is in the access log.
- Retention (`Retention` in `ingest/config.py`): bundles at ticket close or after 30 days (OPS-24 proposal), unless an
  incident holds them; crash reports 90 days and telemetry 400 days (OBS-17 and OBS-20 proposals for the owner to
  confirm, D99); the access log 400 days. A purge runs every `purge_interval_s`.

No client address is read or stored: the server runs with proxy headers and its access log off.

## Deploying

The hosts in `services/agent-core/agent_core/net/policy.json` are placeholders ending in `.invalid` until operations
names the real ones (OPS-35). One ingest deployment can serve both the `crash` and the `telemetry` service hosts; the
support page can sit on either.

1. **Storage.** A persistent volume for `storage_dir` (SQLite plus encrypted bundle files), private to the service
   account. Backups of it must not outlive the bundle retention, or deletions do not reach every copy.
2. **Secrets** in the secret manager's mount (`secrets_dir`, one file per secret, never inside a git checkout):
   - `ingest_storage_key`: base64 of 32 random bytes, for example
     `python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"`. Losing it makes stored bundles
     unreadable; rotating it means re-encrypting them.
   - one token per staff member, named in the configuration (long random strings; revoke by removing the file).
3. **Configuration** (`--config`, merged over `ingest/defaults.toml`):

   ```toml
   environment = "pilot"
   storage_dir = "/var/lib/jana-ingest"
   secrets_dir = "/run/secrets/jana-ingest"
   log_path = "/var/log/jana-ingest/ingest.log"

   [staff.support-l1-a]
   secret = "staff_support_l1_a"
   level = "L1"

   [staff.engineer-l3-b]
   secret = "staff_engineer_l3_b"
   level = "L3"
   ```

4. **Run** `python -m ingest --config /etc/jana-ingest.toml --host 0.0.0.0 --port 8081` behind a TLS terminator.
   The terminator must present a chain from our intermediate CA (the core pins its public keys and a backup pin,
   SEC-31), must not forward or log client addresses (TABLE OBS-19a), and must allow request bodies up to
   `max_bundle_bytes` on `/v1/support/`.
5. **Point the app at it**: set the real `crash` and `telemetry` hosts and their pins per environment in
   `policy.json` (and the support page's address in the support documents, OPS-25).
6. **Monitor** `GET /v1/ping` and `GET /v1/status` against TABLE OPS-17a's 99.0% objective (OPS-17).

What a deployment must verify (it cannot be shown from this repository): the device reaches the real host through
its pins; the terminator logs no client address; the volume and its backups follow the retention; and the staff
tokens and storage key are only in the secret manager.

## Tests

`uv run pytest services/ingest/tests`: the core's real outbox over pinned TLS to the ingest served in-process,
refusals, retention, the support lifecycle with bundles from the core's own writer, and the allow-list against the
contracts.
