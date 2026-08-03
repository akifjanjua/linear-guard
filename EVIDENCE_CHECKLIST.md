# Evidence and Screenshot Checklist

## Strongest evidence set

1. **Real Linear result** — show a harmless approved update or comment on the test issue.
2. **Module loaded** — Linear Guard `v1.5.4`, signature verified, 16 commands, 1 loaded, 0 rejected.
3. **Blocked before approval** — `blocked_by_policy` and `external_api_touched: false`.
4. **Approved execution** — Sends card showing executed, HTTP 200, and signature present.
5. **Independent receipt verification** — successful verification for the executed write.
6. **Safe smoke test** — all reads and all six write previews pass; no write approved or executed.
7. **Public marketplace listing** — creator, version, 16 commands, governance posture, and video badge.
8. **Review acknowledgement/approval** — RailCall message or dashboard status.

## Redact

Hide API keys, approval codes, personal email addresses, full UUIDs, raw signatures, unrelated browser notifications, and local credential paths. Keep command names, status labels, HTTP status, issue identifier, governance result, and verification success visible.

## Video evidence

The video should show: module loaded → sprint-health diagnosis → exact composite preview → one human approval → multi-issue Linear result → bounded signed receipt verification. Never show the API key or terminal approval code.
