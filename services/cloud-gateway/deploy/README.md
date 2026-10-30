# Nebius gateway deployment

## Local demo

Use [nebius-dev.toml](nebius-dev.toml). It inherits the Nebius Token Factory routes and prices from [defaults.toml](../cloud_gateway/defaults.toml), keeps provider keys in the gateway and applies the existing persistent inference budget.

From the repository root:

```bash
uv run --offline python -m cloud_gateway --config services/cloud-gateway/deploy/nebius-dev.toml --port 8081
```

The app launcher connects to this loopback gateway; it does not provision cloud infrastructure. Keychain setup, optional web/narration services, the app command and approved demo limits are in the [project README](../../../README.md).

Keep `~/.local/state/jana-nebius-gateway` across restarts. It replaced `/tmp/jana-nebius-gateway`, which macOS cleared, losing that ledger. Its ledger includes actual spend and unresolved reservations. No retry, configuration cleanup or demo reset should erase those amounts. Cloud conversational voice remains disabled.

## Production template

[m42-production.toml.example](m42-production.toml.example) now uses the packaged Nebius routes. It is deliberately incomplete, has zero deployment inference allowance, and does not authorize deployment or spending. Copy it outside the checkout and supply the actual HTTPS audience, public entitlement keys, mounted `nebius_api_key`, approved spending limits and expiry, measured extraction charges and reviewed provider/hosting evidence. Never put a secret value in the TOML file.

[jana-cloud-gateway.service.example](jana-cloud-gateway.service.example) is a Linux service template. Measure its sandbox, temporary memory, no-swap/core-dump controls, network restrictions, read-only secret mount and logging behavior on the actual host. Uploaded source bytes, prompts and extraction results must not enter persistent body logs. Keep PDFium, PyAV and FFmpeg licences and source/build provenance with distributed binaries.

Production preflight uses the existing release manifest and checks the actual endpoint, configured model, public trust, provider-retention evidence, measured prices, quality reports and native-device acceptance. A development test or another provider’s recorded result cannot qualify this deployment. The detailed release mechanics and earlier observations are preserved in [M42-DEPLOYMENT-RECORDS.md](M42-DEPLOYMENT-RECORDS.md); the existing [release handoff](M42-RELEASE-HANDOFF.md) is a historical record for its named deployment, not this demo’s configuration.

No cloud resource, DNS record, identity, credential or approved budget is changed by these templates.
