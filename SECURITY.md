# Security

## Vault-only credentials

Linear Guard resolves `LINEAR_API_KEY` exclusively through RailCall's injected `vault_get("linear")` helper. It does not inspect `credentials.local.json`, other RailCall files, process environment variables, command-line arguments, or command inputs for secrets.

Never publish API keys, approval codes, local receipt archives, `.env` files, or RailCall credential files.

## HTTPS transport

All Linear requests use Python `urllib.request` with certificate and hostname verification enabled through a certifi-backed `SSLContext`. The module does not invoke curl, a shell, or another subprocess and never disables TLS verification.

## Governance

All six writes—`linear.create_issue`, `linear.update_issue`, `linear.add_comment`, `linear.triage_issue`, `linear.plan_sprint`, and `linear.rebalance_sprint`—are `write_requires_approval`. RailCall binds approval to the exact previewed payload. Without matching approval, the external write is blocked.

The three composites preflight every referenced Linear entity before mutation. Sprint planning and rebalancing are capped at five issues, use one server-side batch request, reject no-op or malformed plans, and return bounded per-issue receipt evidence.

## Retry and unknown-outcome policy

The handler performs one HTTP attempt per command. Mutations are never automatically retried. If a timeout, connection failure, unreadable successful response, HTTP 5xx, or missing mutation data prevents confirmation, the handler reports that the write outcome is unknown and instructs the user to check Linear before retrying.

## Error handling and redaction

GraphQL errors are checked even on HTTP 200 responses. Failures are raised so the airlock cannot mistake them for success. Known Linear token formats, Authorization values, the exact active API key, and `LINEAR_API_KEY` values are redacted from translated exceptions.

## Responsible disclosure

Report security issues with a redacted reproduction. Do not include credentials, private issue contents, personal email addresses, approval codes, signatures, or full sensitive identifiers.
