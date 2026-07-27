# Linear Guard for RailCall

Linear Guard is a signed RailCall module that connects to the real Linear GraphQL API. It provides safe discovery and issue reads, while every issue-changing action is held behind RailCall's preview → approve → execute → signed receipt airlock.

**Version:** 1.3.0  
**Provider:** Linear  
**Commands:** 10 (7 reads, 3 approval-controlled writes)  
**Contest tag:** `contest:2026Q3`

## Why this module exists

Small product and engineering teams often want AI-assisted issue management, but they do not want an agent silently creating, editing, or commenting on work items. Linear Guard separates safe reads from governed writes:

- reads execute immediately and generate signed receipts;
- writes are previewed first;
- RailCall blocks execution until a human approves the exact payload;
- the final action and Linear response are captured in a signed receipt;
- credentials remain local and are never returned in module output.

## Capabilities

| `linear.get_current_user` | Get Current Linear User | `read` | None |
| `linear.list_teams` | List Linear Teams | `read` | None |
| `linear.list_projects` | List Linear Projects | `read` | None |
| `linear.list_labels` | List Linear Issue Labels | `read` | None |
| `linear.list_workflow_states` | List Linear Workflow States | `read` | offset, limit |
| `linear.search_issues` | Search Linear Issues | `read` | query, offset, limit |
| `linear.get_issue` | Get a Linear Issue | `read` | issue_id |
| `linear.create_issue` | Create a Linear Issue | `write_requires_approval` | team_id, title, description |
| `linear.update_issue` | Update a Linear Issue | `write_requires_approval` | issue_id, title, description, state_id, project_id, priority |
| `linear.add_comment` | Add a Comment to a Linear Issue | `write_requires_approval` | issue_id, body |

### Updateable issue fields

`linear.update_issue` can change any combination of:

- title;
- description;
- workflow state;
- project;
- priority (`0`–`4`).

At least one update field is required.

## Requirements

- RailCall Station/Studio with marketplace module support;
- a Linear workspace;
- a Linear personal API key with access to the workspace you want to use;
- system `curl` available as a verified TLS fallback on Windows.

## Install from the RailCall marketplace

1. Install **Linear Guard** from the RailCall marketplace.
2. Open **RailCall Studio → Integrations**.
3. Search for **Linear** and choose **Add credential**.
4. Enter a clear label, such as `Linear Workspace`.
5. Paste the Linear API key into **Linear API Key**.
6. Keep it set as the default credential and save it.
7. Open **Modules** and select **Reload all**.
8. Confirm that **Linear Guard v1.3.0** shows:
   - signature verified;
   - one module loaded;
   - zero rejected;
   - ten registered commands.

The API key remains on the local RailCall station. It is not embedded in this module and is not emitted in receipts.

## Install from source

Place the project files in a local folder using this structure:

```text
linear-guard/
├── module.json
├── module.sig
├── README.md
├── CHANGELOG.md
├── SECURITY.md
├── handlers/
│   └── handler.py
└── tools/
    ├── validate_release.py
    ├── smoke_test.py
    └── build_release.py
```

Validate and sign from the project root:

```bash
python -m py_compile handlers/handler.py
python -m json.tool module.json > /dev/null
python tools/validate_release.py
python tools/sign_module.py
```

Copy the signed files into the station module directory, or publish through the marketplace:

```bash
railcall market publish .
```

## Quick verification

Keep RailCall Studio running, then execute a read command against the local Station API:

```bash
curl -sS \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8799" \
  -H "Referer: http://127.0.0.1:8799/v2" \
  --data '{
    "command_id": "linear.get_current_user",
    "inputs": {},
    "intent": "Verify the installed Linear Guard module"
  }' \
  http://127.0.0.1:8799/api/commands/execute
```

A successful receipt reports an executed result, HTTP `200`, and `external_api_touched: true`.

For a full safe test suite:

```bash
python tools/smoke_test.py --issue RAI-9
```

The smoke test executes read commands and previews the three write commands. It never approves or performs a write.

## Governed write example

A write request such as `linear.add_comment` is expected to behave as follows:

1. preview the exact issue and comment;
2. attempt execution;
3. receive `blocked_by_policy` with `external_api_touched: false`;
4. review the pending request in **Studio → Sends**;
5. approve the exact payload;
6. RailCall executes it against Linear;
7. verify the signed receipt independently.

This is a safety feature, not an error.

## Authentication and transport

Linear Guard supports the Linear personal API-key authentication format and sends requests to:

```text
https://api.linear.app/graphql
```

The handler:

- validates required fields before network calls;
- checks GraphQL `errors` even when HTTP is `200`;
- handles HTTP `429` explicitly;
- uses verified Python TLS first;
- uses verified system `curl` only as a Windows certificate-chain fallback;
- never disables hostname or certificate verification.

For a public multi-user application, Linear recommends OAuth. This marketplace module currently uses a locally stored personal API key because it is designed for a user's own RailCall station.

## Receipt-safe output

RailCall Studio may shorten long string fields in receipt views. Commands that can return multiple records use compact, receipt-safe JSON pages with `offset`, `next_offset`, and `has_more` where necessary.

## Troubleshooting

### Module is rejected after editing

The signature covers the exact bytes of `module.json` and `handlers/handler.py`. Re-run:

```bash
python tools/sign_module.py
```

Then reload the module.

### Integration test reports a certificate error

Linear Guard keeps TLS verification enabled and automatically attempts the system `curl` fallback. Confirm that `curl --version` works and that the system date, time, and root certificates are correct.

### Write returns `blocked_by_policy`

Open **Studio → Sends**, inspect the exact payload, and approve it. Any changed title, body, identifier, spacing, or input creates a different payload and requires a new approval.

### Search or workflow output has multiple pages

Follow `next_offset` while `has_more` is true. The included smoke test does this automatically.

### Issue or team cannot be found

Run `linear.list_teams`, `linear.list_projects`, or `linear.search_issues` first. Linear Guard accepts shorthand issue identifiers such as `RAI-9` where Linear supports them.

## Security

Read [SECURITY.md](SECURITY.md) before publishing or modifying credential behaviour.

## Release history

Read [CHANGELOG.md](CHANGELOG.md).

## Contest

This listing is prepared for the RailCall module contest under:

```text
contest:2026Q3
```

The project uses the real Linear API—no mocks or stubs.
