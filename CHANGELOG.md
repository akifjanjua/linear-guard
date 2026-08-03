# Changelog

## 1.5.4 — Marketplace handler contract

- Restored the complete 16-command implementation directly in `handlers/handler.py` to satisfy RailCall Marketplace quality checks.
- Preserved the identical implementation in `handlers/linear_guard_impl.py`.
- Configured `handlers/handler.py` and `module.json` for exact CRLF byte preservation on Windows.
- Prevented Marketplace text-mode installation from invalidating the signed v2 module tree.
- Preserved all governed commands, vault-only credentials, zero model-provider destinations, and approval-controlled writes.

## 1.5.3 — Marketplace byte-stable entrypoint

- Added a newline-free `handlers/handler.py` bootstrap that remains byte-identical when RailCall Marketplace processes it on Windows.
- Moved the complete 16-command implementation to `handlers/linear_guard_impl.py`.
- Prevented CRLF conversion of the marketplace entrypoint from invalidating the signed v2 module tree.
- Updated release validation and Station v0.45 egress tests to inspect both the bootstrap and implementation files.
- Preserved all 16 governed Linear commands, `allowed_destinations: []`, vault-only credentials, and approval-controlled writes.

## 1.5.2 — Signed-tree release integrity

- Corrected the release workflow so archives contain the exact Git-committed tree covered by RailCall's v2 module signature.
- Added independent Ed25519 tree-signature verification and optional official RailCall verification after archive extraction.
- Changed the build to read immutable bytes from `HEAD`, eliminating checkout line-ending drift.
- Moved the per-file release manifest outside the signed module archive to avoid adding unsigned files after signing.
- Removed the obsolete single-file signing helper; all signing now uses `railcall market module sign`.
- Enforced commit-before-sign ordering and post-sign, post-package, and post-merge verification.
- Added `.moduleignore` and aligned release packaging with RailCall's exact ignored-path rules, excluding local `dist/` and reference artifacts from the signed tree.

## 1.5.1 — Station v0.45 egress contract

- Added a signed `allowed_destinations: []` manifest declaration: Linear Guard permits zero LLM/model-provider destinations.
- Added a dedicated v0.45 contract test that rejects accidental model-provider SDKs, provider hosts, or `station_llm` usage.
- Clarified that `api.linear.app` is the module's declared business integration endpoint, not model-provider egress.
- Wired the new contract test into multi-version CI and deterministic release acceptance.

## Unreleased — v1.5.0 governed operations

- Added `linear.list_members`, `linear.list_cycles`, and `linear.sprint_health`.
- Added `linear.triage_issue`, a preflighted single-consent composite for bounded issue triage.
- Added `linear.plan_sprint`, an atomic 2–5 issue sprint-planning composite using Linear `issueBatchCreate`.
- Added `linear.rebalance_sprint`, a preflighted 2–5 issue batch correction composite using Linear `issueBatchUpdate`.
- Added public `homepage` and `tests_url` metadata plus a multi-version GitHub Actions test workflow.
- Added sprint-wide preflight validation, one-request blast-radius evidence, and deterministic created-issue mapping.
- Kept nested created-issue receipt evidence URL-free so RailCall redaction cannot corrupt its JSON structure.
- Added exact reference validation, no-op rejection, label-set limits, and honest partial-failure reporting.
- Added deterministic release ZIP metadata, canonical line endings, extracted-package validation, and byte-for-byte reproducibility checks.
- Canonicalized all unsigned packaged text so Linux and Windows checkouts produce the same release bytes.

All notable Linear Guard changes are documented here.

## 1.4.0

- Resolve Linear credentials exclusively through RailCall `vault_get`.
- Remove direct credential-file access and all curl/subprocess networking.
- Use `urllib.request` with a certifi-backed verified SSL context.
- Declare API-key authentication in `module.json`.
- Add active credential redaction to translated errors.
- Never automatically retry mutations; fail loudly on unknown outcomes.
- Strengthen create/update input validation and security tests.
- Rewrite the README and marketplace description for a fast buyer setup.

## 1.3.0

- Added `linear.update_issue`.
- Added `linear.add_comment`.
- Applied `write_requires_approval` governance to all three mutating commands.
- Added receipt-safe output for issue updates and comments.
- Verified the complete preview → blocked → human approval → execution → signed receipt flow against the real Linear API.

## 1.2.0

- Added `linear.search_issues`.
- Added `linear.get_issue`.
- Added receipt-safe pagination for issue search output.
- Verified retrieval by shorthand identifier such as `RAI-9`.

## 1.1.1

- Added `linear.list_projects`.
- Added `linear.list_labels`.
- Added `linear.list_workflow_states`.
- Added receipt-safe pagination for workflow states.

## 0.1.0-prototype

- Added authenticated Linear user and team reads.
- Added approval-controlled issue creation.
- Implemented secure local credential loading.
- Added verified Windows TLS fallback.
- Verified signed RailCall receipts independently.
