Linear Guard is a governance-first Linear integration for engineering, product, and operations teams that want AI-assisted issue work without unrestricted write access.

It provides 14 focused commands: 10 low-risk discovery and reporting commands plus 4 approval-controlled writes. The module can identify the current user; list teams, projects, labels, workflow states, workspace members, and cycles; search and retrieve issues; analyze sprint health; create and update issues; add comments; and apply a complete triage decision.

The flagship `linear.triage_issue` command makes governance-first concrete. One exact approval can set priority, workflow state, assignee, project, cycle, and a bounded replacement label set, then optionally add a triage note. Every referenced entity is validated before the first mutation, no-op requests are rejected, writes are never retried automatically, and partial completion is reported honestly rather than disguised as success.

Credentials are resolved exclusively through RailCall's `linear` vault provider. Linear Guard does not read credential files, use process environment variables, log the API key, or invoke curl or another subprocess. HTTPS uses Python urllib with a certifi-backed verified SSL context.

Linear-specific failures are handled honestly. The module checks GraphQL `errors` even when Linear responds with HTTP 200, reports authentication and rate-limit failures clearly, and never converts exceptions into successful-looking error data. Every completed command produces a signed RailCall receipt.

Quick start: install the module, configure `LINEAR_API_KEY` in RailCall's Linear vault entry, then run `linear.get_current_user`, `linear.list_teams`, or `linear.sprint_health`. Preview all write commands and approve them only after reviewing the exact payload.

Known limitations: personal API keys act with the permissions of their Linear user; search examines up to 100 recent matches; triage accepts at most five labels and treats `label_ids_json` as the complete replacement label set.

contest:2026Q3
