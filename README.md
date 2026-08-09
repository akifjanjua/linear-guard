# Linear Guard

![Linear Guard Tests](https://github.com/akifjanjua/linear-guard/actions/workflows/linear-guard-tests.yml/badge.svg)

Linear Guard is a governance-first RailCall module for engineering, product, and operations teams using Linear. It provides 16 focused commands for discovery, sprint reporting, and approval-controlled issue operations through the real Linear GraphQL API. Verified on station-v0.65.

## Commands

**Reads (10):** `linear.get_current_user`, `linear.list_teams`, `linear.list_projects`, `linear.list_labels`, `linear.list_workflow_states`, `linear.search_issues`, `linear.get_issue`, `linear.list_members`, `linear.list_cycles`, `linear.sprint_health`.

**Writes (6):** `linear.create_issue`, `linear.update_issue`, `linear.triage_issue`, `linear.plan_sprint`, `linear.rebalance_sprint`, `linear.add_comment`. Every write uses `write_requires_approval`, so RailCall binds human approval to the exact payload and produces a signed receipt.

`linear.plan_sprint` is the flagship composite: one approval creates 2–5 fully configured issues through Linear's server-side `issueBatchCreate` transaction, preflighting team, cycle, project, workflow state, parent, assignees, and labels before the single write.

`linear.triage_issue` applies a complete bounded triage decision under one approval. `linear.rebalance_sprint` applies one shared change to 2–5 same-team issues via `issueBatchUpdate`, closing the loop from `linear.sprint_health` diagnosis to corrective action.

## Egress contract

The signed manifest declares `"allowed_destinations": []` — zero LLM/model-provider destinations. The module never calls Anthropic, OpenAI, Groq, Gemini, xAI, Ollama, or RailCall's model-completion primitive. HTTPS traffic is limited to `api.linear.app` using the credential from RailCall Vault. CI fails if model-provider SDKs or `station_llm` usage are introduced.

## Install

```
python -m pip install certifi
railcall market install muhammad-akif-janjua/linear-guard
```

Open RailCall Studio, reload **Modules**, and confirm Linear Guard v1.5.5, signature verified, 16 commands.

## Configure credentials

Create a Linear personal API key at https://linear.app/settings/api. In RailCall Studio → Integrations → Linear, save it as `LINEAR_API_KEY`. Credentials resolve only through `vault_get("linear")`.

## Example

Preview `linear.plan_sprint` with a team ID, cycle ID, and this `issues_json` string:

```
[
  {"title":"Implement approval UX","priority":2,"estimate":3},
  {"title":"Document receipt verification","priority":3,"estimate":2}
]
```

### Expected output

Preview returns the exact payload for review and halts pending approval — Linear is not called and no issue exists yet. Approve, and the module issues a single `issueBatchCreate` request, then returns the created issues with their Linear identifiers and titles, plus the requested and created counts so partial results are visible rather than hidden.

RailCall writes a signed receipt recording the bounded blast radius and every created issue. Browse and re-verify receipts with `railcall receipts` or in Studio.

Reject at the preview step and nothing is sent. GraphQL errors are surfaced even when the HTTP status is 200, and writes are never retried automatically.

## Limitations

Personal API keys act with their creator's permissions. Sprint plans and rebalances are limited to five issues; label sets to five labels. Search and multi-record outputs remain bounded for receipt readability.

`contest:2026Q3`
