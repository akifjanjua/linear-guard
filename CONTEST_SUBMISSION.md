# Freelancer Contest Entry Draft

## Title

Linear Guard — Governed Linear Integration

## Description

I built Linear Guard as a signed RailCall module for real Linear workspaces. It provides 31 focused commands covering workspace discovery, sprint health, issue audit history, approval-controlled issue and label lifecycle work (including sub-issue parenting), attachments, issue relations, cycle management, governed triage, transactional sprint planning, and bounded multi-issue sprint rebalancing.

The six write commands cannot run silently. RailCall previews the exact payload, blocks it until a human approves it, executes only the approved action, and records the result in a signed receipt that can be independently verified.

Linear Guard resolves credentials only through RailCall's vault helper, uses certifi-backed verified HTTPS, never invokes curl or another subprocess, actively redacts credentials from errors, and never automatically retries mutations with an uncertain outcome.

I tested it against the real Linear GraphQL API with no mocks or stubs. The evidence includes one approved triage composite, an atomic two-issue sprint plan, a one-request two-issue sprint rebalance, bounded receipt evidence, and independently verified signed receipts. The public CI workflow tests Python 3.10, 3.12, and 3.13 and verifies the final release archive file by file.

Marketplace listing: [PASTE APPROVED LISTING URL]

README URL: [PASTE PUBLIC README URL]

Demo video: [PASTE UNLISTED YOUTUBE URL]

`contest:2026Q3`

## Station v0.45 trust declaration

Linear Guard's signed manifest declares zero LLM/model-provider destinations. The module talks only to the Linear GraphQL business API and does not send issue data to a model-provider SDK or RailCall model-completion primitive.
