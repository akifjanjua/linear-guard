# Linear Guard

Linear Guard is a governance-first RailCall module for engineering, product, and operations teams that use Linear. It provides 10 focused commands for discovering workspace data, finding issues, and making approval-controlled changes through the real Linear GraphQL API.

## Commands

Reads: `linear.get_current_user`, `linear.list_teams`, `linear.list_projects`, `linear.list_labels`, `linear.list_workflow_states`, `linear.search_issues`, and `linear.get_issue`.

Writes: `linear.create_issue`, `linear.update_issue`, and `linear.add_comment`. Every write is declared `write_requires_approval`, so RailCall previews the exact payload and blocks execution until a human approves it. Each result produces a signed receipt.

## Install

```bash
python -m pip install certifi
railcall market install muhammad-akif-janjua/linear-guard
```

Open RailCall Studio, reload **Modules**, and confirm **Linear Guard v1.4.0**, **signature verified**, and **10 commands**.

## Configure credentials

Create a Linear personal API key at `https://linear.app/settings/api`. In **RailCall Studio → Integrations → Linear**, save it as `LINEAR_API_KEY` and select it as the default Linear credential. Linear Guard resolves credentials only through RailCall's `vault_get("linear")` helper. It never reads credential files or environment variables.

## Working read example

Run `linear.get_current_user` with `{}`. Expected receipt output includes:

```json
{
  "ok": true,
  "http_status": 200,
  "user_id": "...",
  "name": "...",
  "email": "..."
}
```

## Governed write example

Preview `linear.update_issue` with:

```json
{"issue_id":"RAI-9","priority":2}
```

Expected behaviour: RailCall creates a pending approval and does not touch Linear. After you approve the exact payload, the command executes once and produces a signed receipt. Linear Guard never automatically retries mutations. If the connection ends before a mutation is confirmed, it raises an “outcome is unknown” error and instructs you to check Linear before retrying.

## Limitations

Personal API keys act with the permissions of the Linear user who created them. Search examines up to 100 recent matching issues. Multi-record outputs are paginated to remain readable in receipts. The module requires the `certifi` Python package for verified HTTPS.

## Troubleshooting

- **Credentials not configured:** add `LINEAR_API_KEY` to the RailCall `linear` vault entry.
- **`blocked_by_policy`:** review and approve the exact payload in **Studio → Sends**.
- **Certificate dependency missing:** run `python -m pip install certifi` with the Python used by RailCall.

`contest:2026Q3`
