# Freelancer Contest Entry Draft

## Title

Linear Guard — Governed Linear Integration

## Description

I built Linear Guard as a signed RailCall module for real Linear workspaces. It provides 16 focused commands covering workspace discovery, sprint health, approval-controlled issue work, governed triage, transactional sprint planning, and bounded multi-issue sprint rebalancing.

The six write commands cannot run silently. RailCall previews the exact payload, blocks it until a human approves it, executes only the approved action, and records the result in a signed receipt that can be independently verified.

Linear Guard resolves credentials only through RailCall's vault helper, uses certifi-backed verified HTTPS, never invokes curl or another subprocess, actively redacts credentials from errors, and never automatically retries mutations with an uncertain outcome.

I tested it against the real Linear GraphQL API with no mocks or stubs. The evidence includes one approved triage composite, an atomic two-issue sprint plan, bounded receipt evidence, and independently verified signed receipts.

Marketplace listing: [PASTE APPROVED LISTING URL]

README URL: [PASTE PUBLIC README URL]

Demo video: [PASTE UNLISTED YOUTUBE URL]

`contest:2026Q3`
