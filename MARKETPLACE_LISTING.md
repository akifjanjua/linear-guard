Linear Guard is a governance-first Linear integration for engineering, product, and operations teams that want AI-assisted issue work without unrestricted write access.

It provides 10 focused commands: identify the current Linear user; list teams, projects, labels, and workflow states; search issues; retrieve a specific issue; create an issue; update an issue; and add a comment. The seven discovery and read commands are low risk. The three commands that change Linear use RailCall's preview → approve → execute flow, so no external write occurs until a human approves the exact payload.

Typical uses include issue discovery and triage, preparing a new issue for the correct team, changing title, priority, workflow state, project, or description, and posting an auditable follow-up comment. Every completed command produces a signed RailCall receipt.

Credentials are resolved exclusively through RailCall's `linear` vault provider. Linear Guard does not read RailCall credential files, does not use process environment variables, does not log the API key, and does not invoke curl or another subprocess. HTTPS requests use Python urllib with a certifi-backed verified SSL context.

Linear-specific failures are handled honestly. The module checks GraphQL `errors` even when Linear responds with HTTP 200, reports authentication and rate-limit failures clearly, and never converts exceptions into successful-looking error data. Mutations are never automatically retried. If a network failure occurs before Linear confirms a write, the module reports that the outcome is unknown and tells the user to check Linear before retrying.

Quick start: install the module, configure `LINEAR_API_KEY` in RailCall's Linear vault entry, then run `linear.get_current_user` or `linear.list_teams`. Preview create, update, and comment operations and approve them only after reviewing the exact payload.

Known limitations: personal API keys act with the permissions of the Linear user who created them; issue search examines up to 100 recent matches; multi-record outputs use receipt-safe pagination.

contest:2026Q3
