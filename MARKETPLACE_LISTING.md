Linear Guard is a governance-first Linear integration for engineering, product, and operations teams that want AI-assisted issue work without unrestricted write access.

It provides 16 focused commands: 10 low-risk discovery and reporting commands plus 6 approval-controlled writes. The module can discover teams, projects, labels, workflow states, members, and cycles; search and retrieve issues; analyze sprint health; create and update issues; add comments; apply a complete triage decision; create a bounded sprint plan, and rebalance an existing sprint in one batch.

The flagship `linear.plan_sprint` command answers the question “why not install the bigger endpoint wrapper?” It is not another individual API action. One exact RailCall approval creates 2–5 fully configured Linear issues through the server-side `issueBatchCreate` transaction. The plan can bind every issue to a verified team and cycle, optionally link all issues to a project, workflow state, or parent issue, and apply per-issue assignees, labels, priorities, estimates, titles, and descriptions.

Every referenced Linear entity is validated before the single write request. The module rejects archived, cross-team, malformed, oversized, and duplicate plan data before touching Linear. The signed receipt records the requested and created issue counts, one-request transaction scope, blast-radius totals, and structured evidence for every created issue.

`linear.triage_issue` provides a second governed composite: one approval can set priority, workflow state, assignee, project, cycle, and a bounded replacement label set, then optionally add an audit note.

`linear.rebalance_sprint` provides the operational follow-through. After `linear.sprint_health` identifies attention items, one exact approval can apply one shared priority, estimate, workflow state, assignee, project, cycle, or replacement label set to 2–5 same-team issues through Linear `issueBatchUpdate`. It preflights every issue and reference, rejects all-no-op requests, uses one write request, and returns bounded per-issue evidence.

Credentials are resolved exclusively through RailCall's `linear` vault provider. Linear Guard never reads credential files or process environment variables, invokes no subprocess, uses certifi-backed TLS, never automatically retries writes, and checks GraphQL `errors` even when Linear responds with HTTP 200.

Quick start: install the module, configure `LINEAR_API_KEY` in RailCall's Linear vault entry, run the discovery commands to obtain IDs, and preview `linear.plan_sprint` or `linear.triage_issue` before approving the exact payload.

Known limitations: personal API keys act with the permissions of their Linear user; sprint plans and rebalances are limited to five issues; label sets are limited to five labels; search and receipt outputs are bounded for readability.

contest:2026Q3
