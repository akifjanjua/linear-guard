# Linear Guard

[![Linear Guard Tests](https://github.com/akifjanjua/linear-guard/actions/workflows/linear-guard-tests.yml/badge.svg)](https://github.com/akifjanjua/linear-guard/actions/workflows/linear-guard-tests.yml)

Linear Guard is a governance-first RailCall module for engineering, product, and operations teams using Linear. It provides 31 focused commands for discovery, sprint reporting, and approval-controlled issue operations through the real Linear GraphQL API.

Demo video: [60-second walkthrough](https://drive.google.com/file/d/1Q40bT-Fdx2EtL2JJ021v-MZpjPrqHzDi/view?usp=sharing)

## Commands

Reads: `linear.get_current_user`, `linear.list_teams`, `linear.list_projects`, `linear.list_labels`, `linear.list_workflow_states`, `linear.search_issues`, `linear.get_issue`, `linear.get_issue_history`, `linear.list_members`, `linear.list_cycles`, and `linear.sprint_health`.

Writes (20, `write_requires_approval`, all prefixed `linear.`): issues — `create_issue`, `update_issue`, `archive_issue` (risk `high`; rest are `medium`), `unarchive_issue`, `triage_issue`; labels — `create_label`, `update_label`, `archive_label`; comments — `add_comment`, `update_comment`, `resolve_comment`, `unresolve_comment`; attachments — `create_attachment`, `delete_attachment`; relations (`blocks`/`duplicate`/`related`/`similar`) — `link_issues`, `unlink_issues`; cycles — `create_cycle`, `update_cycle`; sprints — `plan_sprint`, `rebalance_sprint`. RailCall binds approval to the exact previewed payload and signs a receipt. `create_issue`/`update_issue` take `parent_id`; `update_issue` also takes `clear_parent`.

`linear.plan_sprint` is the flagship composite: one approval creates 2–5 fully configured issues through Linear's server-side `issueBatchCreate` transaction, preflighting team, cycle, project, workflow state, parent issue, assignees, and labels first. Each issue can set its own title, description, priority, estimate, assignee, and up to five labels. The receipt records the bounded blast radius and every created issue.

`linear.triage_issue` applies a complete bounded triage decision under one approval, including priority, state, assignee, project, cycle, labels, and an optional audit note.

`linear.rebalance_sprint` applies one shared priority, estimate, state, assignee, project, cycle, or label-set decision to 2–5 same-team issues through one preflighted `issueBatchUpdate` request. This closes the loop from `linear.sprint_health` diagnosis to bounded corrective action.

## Station v0.45 egress contract

The signed manifest declares `"allowed_destinations": [{"provider":"linear","hosts":["api.linear.app"]}]`, pinning Linear Guard's only permitted egress to the Linear GraphQL API and declaring **zero LLM/model-provider destinations** — no Anthropic, OpenAI, Groq, Gemini, xAI, Ollama, or RailCall model-completion calls. `requires.network` enforces the same host at runtime; CI fails if model-provider SDKs, hosts, or `station_llm` usage are introduced.

## Install

```bash
python -m pip install certifi
railcall market install muhammad-akif-janjua/linear-guard
```

Open RailCall Studio, reload **Modules**, and confirm **Linear Guard v1.7.1**, **signature verified**, and **31 commands**.

The release archive is built from immutable Git `HEAD` bytes, reproduces byte-for-byte across checkouts, and must pass independent plus official RailCall signature verification after extraction.

## Configure credentials

Create a Linear personal API key at `https://linear.app/settings/api`. In **RailCall Studio → Integrations → Linear**, the module's `credential_spec` prompts for it as `LINEAR_API_KEY`; RailCall stores it and the handler resolves it only through `vault_get("linear")`.

## Governed sprint example

Preview `linear.plan_sprint` with a team ID, cycle ID, and:

```json
[
  {"title":"Implement approval UX","priority":2,"estimate":3,"assignee_id":"USER_UUID","label_ids":["LABEL_UUID"]},
  {"title":"Document receipt verification","priority":3,"estimate":2}
]
```

Pass that array as the `issues_json` string. Optional shared fields link every issue to a project, workflow state, or parent issue.

## Limitations

Personal API keys act with their creator's permissions. Sprint plans/rebalances are limited to five issues; label sets to five labels; batch outputs use bounded receipt-safe evidence shards. Search and multi-record outputs stay bounded for receipt readability. Every mutation is verified against Linear's live schema; reverse/produce-consume pairs (archive/unarchive, link/unlink, resolve/unresolve, cycle create → sprint_health) have stateful mock tests — none of this has run against a real workspace yet.

`contest:2026Q3`
