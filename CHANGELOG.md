# Changelog

## 1.6.1 — Sub-Issue Parenting, Issue History, Scannable Description

Two more real, evidenced gaps closed, plus the storefront-depth fix flagged
by re-reading `docs/marketplace_review_playbook.md` in full: §1.2.D
explicitly rejects wall-of-prose descriptions and asks for a bullet
structure answering what/who/what-integrations — ours wasn't.

- `linear.create_issue` and `linear.update_issue` gain `parent_id`
  (sub-issue linking); `update_issue` also gains `clear_parent`, following
  the exact `clear_assignee`/`clear_project`/`clear_cycle` convention
  already in `triage_issue`/`rebalance_sprint`. `parentId` on
  `IssueUpdateInput` is a plain nullable `String`, confirmed via live
  introspection; explicit `null` clears it the same way the existing
  clear-flags already do for assignee/project/cycle (`_graphql()` JSON-
  serializes Python `None` to a real `null`, not an omitted key — proven
  in production already, not a new mechanism).
- Added `linear.get_issue_history` (`Issue.history`, a standard Relay
  connection, confirmed via introspection) — a curated audit-trail read:
  actor, `createdAt`, `botActor`, and from/to pairs for title, state,
  assignee, priority, project, cycle, parent, and labels. Bounded
  `first: 100` from Linear, client-side offset/limit slicing, matching
  `list_workflow_states`' existing pagination pattern. `risk: low`,
  `mode: read`.
- Restructured `module.json`'s description opening into an explicit
  what/who/integrations/governance bullet list per the playbook's own
  `description_unscannable` rejection criterion. All existing detail
  (composite descriptions, GraphQL/no-mocks paragraph, quick start,
  limitations, contest line) preserved unchanged — only the opening three
  paragraphs were restructured.
- Command count: 22 → 23 (11 read, 12 write). `handlers/handler.py` and
  `handlers/linear_guard_impl.py` stay byte-identical, both LF-only. Added
  `tools/v16_parent_history_test.py`. Version bumped as a patch, not minor:
  both changes extend existing commands' optional fields (non-breaking) or
  add one read-only command, smaller in scope than v1.6.0's two new write
  commands.

## 1.6.0 — Attachments and Issue Relations

Completes the API-depth roadmap identified by competitive research (priority
4, deferred from v1.5.9). Same discipline as v1.5.9: every mutation shape
verified against Linear's live GraphQL schema via unauthenticated
introspection against `api.linear.app/graphql` before any handler code was
written. This round had no discrepancies with the initial research — both
mutations, both input types, and both payload shapes matched expectations —
except one confirmed addition: `IssueRelationType` has four values on the
live schema (`blocks`, `duplicate`, `related`, `similar`), one more than the
three originally named; `similar` is included since it's real and adds
coverage.

- Added `linear.create_attachment` (`attachmentCreate`) — attaches an
  external URL to an issue. `AttachmentCreateInput` requires `title`, `url`,
  and `issueId`; `subtitle` is optional. `risk: medium`.
- Added `linear.link_issues` (`issueRelationCreate`) — creates a typed
  relation between two issues: `blocks`, `duplicate`, `related`, or
  `similar`. `risk: medium`.
- Command count: 20 → 22 (10 read, 12 write). `handlers/handler.py` and
  `handlers/linear_guard_impl.py` stay byte-identical, both LF-only.
- Added `tools/v16_attachments_relations_test.py`, unit-testing both new
  commands against a monkeypatched `_graphql`, including all four relation
  types and validation-failure paths. Wired into CI.

## 1.5.9 — Label Lifecycle, Issue Archive, Comment Update

Competitive research against a higher-scoring free module on the same rubric
(dihanadil25/gitlab-governance) identified read-only entities and missing
lifecycle operations as the largest remaining API-depth gap. Every new
mutation shape below was verified against Linear's live GraphQL schema via
unauthenticated introspection (`api.linear.app/graphql`) before being coded,
not assumed from documentation summaries — one assumption from the initial
research (a mutation named `issueLabelArchive`) turned out not to exist on
the live schema and was corrected to the real equivalent, `issueLabelRetire`,
during verification.

- Added `linear.create_label` (`issueLabelCreate`) — create an issue label,
  optionally scoped to one team, with name/color/description. `risk: medium`.
- Added `linear.archive_label` (`issueLabelRetire`) — Linear's API calls this
  operation "retire," not "archive"; there is no `issueLabelArchive`
  mutation. Retiring hides the label from pickers while preserving every
  existing issue association and all history. `risk: medium`.
- Added `linear.archive_issue` (`issueArchive`) — archives an issue,
  optionally moving it to trash via the mutation's own `trash` argument.
  `risk: high`, higher than every other write command, since it is the most
  consequential of the ten write commands. `issueArchive` returns only
  `{success, lastSyncId}` with no updated entity, so the command echoes the
  requested `issue_id` rather than inventing fields Linear's API does not
  return.
- Added `linear.update_comment` (`commentUpdate`) — updates the body of an
  existing comment; genuine depth beyond parity with the researched
  competitor, which does not expose comment editing either.
- Command count: 16 → 20 (10 read, 10 write). `handlers/handler.py` and
  `handlers/linear_guard_impl.py` stay byte-identical; both re-encoded
  LF-only, matching the v1.5.7 encoding fix.
- Added `tools/v15_api_depth_test.py`, unit-testing all four new commands
  against a monkeypatched `_graphql`, matching the existing test suite's
  style. Wired into CI.

## 1.5.8 — Video URL, License Required

- Added `video_url` as a top-level `module.json` field, pointing at the
  recorded demo walkthrough. Confirmed via competitive research that the
  marketplace backend lifts this field onto the listing the same way it
  already does for `homepage`/`tests_url`, neither of which has special
  CLI-side handling in `railcall market publish` either.
- Added `license_required: false` for manifest completeness, matching the
  explicit declaration convention used by other real modules on the
  platform.

## 1.5.7 — Credential Spec, Declared Egress Host, LF Handler Encoding

- Added a `credential_spec` block (`provider`, `category`, `name`, `required: ["LINEAR_API_KEY"]`, `optional`, `shape`, `risk`, `read_write`) so RailCall Studio's Integrations → Linear Configure prompt renders correctly.
- Changed `allowed_destinations` from `[]` to `[{"provider":"linear","hosts":["api.linear.app"]}]`, matching the convention used by every other module on the platform (including RailCall's own internal modules): egress is declared as `{provider, hosts}` regardless of whether the provider is an LLM. This still declares zero LLM/model-provider destinations — the sole entry names the Linear business API itself. `requires.network` continues to be the runtime sandbox enforcement of the same host.
- Re-encoded `handlers/handler.py` from CR-only to plain LF line endings. `railcall market publish` reads `handler.py` in text mode without `newline=""`, which silently converts CR bytes to LF before embedding the string in the publish payload; a CR-only file therefore corrupts on publish even though the local signature stays valid. LF-only content passes through that read unchanged, so the published payload now matches what was signed.
- Updated `tools/validate_release.py` and `tools/v045_egress_contract_test.py` to assert the new `allowed_destinations` and `credential_spec` values instead of requiring an empty list.
- Added a demo video link to `README.md`.

## 1.5.6 — Declared Sandbox Requirements

- Added a top-level `requires` block to `module.json` declaring the module's sandbox needs: outbound network to `api.linear.app`, no subprocess execution, and no filesystem writes.
- Left the 16 per-command `requires` fields as empty credential lists; they are unrelated to the top-level sandbox declaration.
- Preserved `allowed_destinations: []`, keeping the Station v0.45 zero-model-provider-egress contract intact.
- Preserved the newline-free `module.json` representation and the CR-only `handlers/handler.py` encoding.
- Excluded editor and backup artefacts (`*.bak`, `*.orig`, `*.rej`, `*.backup-*`) and the local `.claude/` directory from `.moduleignore`, so untracked working-directory files can no longer enter the signed module tree.
- Wired the previously unused `assert_local_tree_matches_head` check into `tools/verify_module_tree.py`, so a local tree that differs from `HEAD` fails with the offending paths instead of an opaque `InvalidSignature`. The check is skipped when the target is not a Git working tree, so extracted-archive verification is unaffected.

## 1.5.5 — CR-Only Marketplace Handler Contract

- Restored all 16 command implementations as real top-level functions in `handlers/handler.py`.
- Satisfies the Marketplace static handler-function quality check without using an `exec(...)` wrapper.
- Encoded `handlers/handler.py` with CR-only physical line separators: 3310 CR bytes and 0 LF bytes.
- Preserved the newline-free `module.json` representation.
- Confirmed that the CR-only handler parses successfully and exposes all 16 declared commands.
- Preserved all governed Linear operations, vault-only credentials, zero model-provider destinations, approval-controlled writes, signed previews, and signed receipts.
- Requires an exact-read publishing path so the submitted `handler_py` string retains its CR-only representation.

## 1.5.4 — Marketplace handler contract

- Restored the complete 16-command implementation directly in `handlers/handler.py` to satisfy RailCall Marketplace quality checks.
- Preserved the identical implementation in `handlers/linear_guard_impl.py`.
- Encoded `handlers/handler.py` and `module.json` without physical newline bytes so Marketplace text-mode installation preserves identical signed bytes across Windows, Linux, and macOS.
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
