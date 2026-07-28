# Evidence and Screenshot Checklist

## Strongest evidence set

1. **Real Linear result** — show a harmless approved update or comment on the test issue.
2. **Module loaded** — Linear Guard `v1.4.0`, signature verified, 10 commands, 1 loaded, 0 rejected.
3. **Blocked before approval** — `blocked_by_policy` and `external_api_touched: false`.
4. **Approved execution** — Sends card showing executed, HTTP 200, and signature present.
5. **Independent receipt verification** — successful verification for the executed write.
6. **Safe smoke test** — all reads and all three previews pass; no write approved or executed.
7. **Public marketplace listing** — creator, version, 10 commands, governance posture, and video badge.
8. **Review acknowledgement/approval** — RailCall message or dashboard status.

## Redact

Hide API keys, approval codes, personal email addresses, full UUIDs, raw signatures, unrelated browser notifications, and local credential paths. Keep command names, status labels, HTTP status, issue identifier, governance result, and verification success visible.

## Video evidence

The 60-second video should show: module loaded → real read → exact write preview → pending approval → human approval → visible Linear change → signed receipt verification. Never show the API key or terminal approval code.
