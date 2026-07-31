# Linear Guard

Linear Guard is a governance-first RailCall module for engineering, product, and operations teams that use Linear. It provides 14 focused commands for discovery, sprint reporting, and approval-controlled issue operations through the real Linear GraphQL API.

## Commands

Reads: `linear.get_current_user`, `linear.list_teams`, `linear.list_projects`, `linear.list_labels`, `linear.list_workflow_states`, `linear.search_issues`, `linear.get_issue`, `linear.list_members`, `linear.list_cycles`, and `linear.sprint_health`.

Writes: `linear.create_issue`, `linear.update_issue`, `linear.triage_issue`, and `linear.add_comment`. Every write is declared `write_requires_approval`, so RailCall previews the exact payload and blocks execution until a human approves it. Each result produces a signed receipt.

`linear.triage_issue` is a bounded composite: one approval can set priority, workflow state, assignee, project, cycle, an exact replacement label set, and an optional triage note. It validates all referenced Linear entities before the first mutation, rejects no-op requests, never retries writes, and reports partial completion honestly if the optional comment cannot be confirmed.

## Install

```bash
python -m pip install certifi
railcall market install muhammad-akif-janjua/linear-guard
```

Open RailCall Studio, reload **Modules**, and confirm **Linear Guard v1.5.0**, **signature verified**, and **14 commands**.

## Configure credentials

Create a Linear personal API key at `https://linear.app/settings/api`. In **RailCall Studio → Integrations → Linear**, save it as `LINEAR_API_KEY`. Linear Guard resolves credentials only through RailCall's `vault_get("linear")` helper. It never reads credential files or environment variables.

## Governed triage example

Preview `linear.triage_issue` with:

```json
{
  "issue_id": "RAI-9",
  "priority": 2,
  "assignee_id": "USER_UUID",
  "state_id": "STATE_UUID",
  "label_ids_json": "[\"LABEL_UUID\"]",
  "triage_note": "Assigned and prioritized during weekly triage."
}
```

RailCall binds approval to this exact payload. Linear Guard preflights the issue and every referenced entity before the first mutation, applies the bounded update once, optionally adds the note, and returns structured before/after evidence in the signed receipt.

## Limitations

Personal API keys act with the permissions of the Linear user who created them. Searches examine up to 100 recent matches. Triage accepts at most five labels and treats `label_ids_json` as the complete replacement label set. Multi-record outputs remain bounded for receipt readability.

`contest:2026Q3`
