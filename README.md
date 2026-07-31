# Linear Guard

[![Linear Guard Tests](https://github.com/akifjanjua/linear-guard/actions/workflows/linear-guard-tests.yml/badge.svg)](https://github.com/akifjanjua/linear-guard/actions/workflows/linear-guard-tests.yml)

Linear Guard is a governance-first RailCall module for engineering, product, and operations teams using Linear. It provides 16 focused commands for discovery, sprint reporting, and approval-controlled issue operations through the real Linear GraphQL API.

## Commands

Reads: `linear.get_current_user`, `linear.list_teams`, `linear.list_projects`, `linear.list_labels`, `linear.list_workflow_states`, `linear.search_issues`, `linear.get_issue`, `linear.list_members`, `linear.list_cycles`, and `linear.sprint_health`.

Writes: `linear.create_issue`, `linear.update_issue`, `linear.triage_issue`, `linear.plan_sprint`, `linear.rebalance_sprint`, and `linear.add_comment`. Every write uses `write_requires_approval`, so RailCall binds human approval to the exact payload and produces a signed receipt.

`linear.plan_sprint` is the flagship composite. One approval creates 2–5 fully configured issues through Linear's server-side `issueBatchCreate` transaction. It preflights the team, cycle, project, workflow state, parent issue, assignees, and labels before the single write request. Each issue can include its own title, description, priority, estimate, assignee, and up to five labels. The receipt records the bounded blast radius and every created issue.

`linear.triage_issue` applies a complete bounded triage decision under one approval, including priority, state, assignee, project, cycle, labels, and an optional audit note.

`linear.rebalance_sprint` applies one shared priority, estimate, state, assignee, project, cycle, or label-set decision to 2–5 same-team issues through one preflighted `issueBatchUpdate` request. This closes the loop from `linear.sprint_health` diagnosis to bounded corrective action.

## Install

```bash
python -m pip install certifi
railcall market install muhammad-akif-janjua/linear-guard
```

Open RailCall Studio, reload **Modules**, and confirm **Linear Guard v1.5.0**, **signature verified**, and **16 commands**.

The release archive is generated with a per-file SHA-256 manifest and is verified by the public CI workflow before publication.

## Configure credentials

Create a Linear personal API key at `https://linear.app/settings/api`. In **RailCall Studio → Integrations → Linear**, save it as `LINEAR_API_KEY`. Credentials are resolved only through `vault_get("linear")`.

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

Personal API keys act with their creator's permissions. Sprint plans and rebalances are limited to five issues; label sets are limited to five labels; all batch outputs use bounded receipt-safe evidence shards. Search and multi-record outputs remain bounded for receipt readability.

`contest:2026Q3`
