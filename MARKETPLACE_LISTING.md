# Marketplace Listing Copy

## Listing title

Linear Guard

## Short tagline

Governed Linear reads and approval-controlled issue writes with signed receipts.

## Full description

I built Linear Guard for teams that want AI-assisted Linear operations without allowing an agent to change work items silently.

The module connects to the real Linear GraphQL API and includes ten practical commands: identify the current user, list teams, projects, labels and workflow states, search issues, retrieve an issue, create an issue, update issue fields and add comments.

Reads execute immediately and generate signed receipts. Every create, update or comment request goes through RailCall's full airlock: preview the exact payload, block execution until a human approves it, execute only the approved action, then record the result in a signed receipt that can be independently verified.

Credentials remain local to the RailCall station and are never returned in receipts. The module validates inputs, checks GraphQL errors even on HTTP 200 responses, handles rate limits honestly and keeps TLS verification enabled.

A detailed README, release validator, safe smoke-test script and troubleshooting guide are included so a new user can install and verify the module quickly.

`contest:2026Q3`

## Recommended category

Engineering / Project Management / Productivity

## Recommended keywords

Linear, issue tracking, project management, approval workflow, audit trail, governance, GraphQL, engineering operations

## Pricing recommendation for the contest

List it as **Free** during the contest and for at least the first 72 hours after publication. This removes purchase friction and gives reviewers and other users the easiest path to install and test it.

## What buyers need

- RailCall Station/Studio;
- a Linear workspace;
- a Linear personal API key;
- permission to access the intended Linear teams and issues.
