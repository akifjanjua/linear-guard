#!/usr/bin/env python3
"""Stateful pair tests for Linear Guard's four reverse/produce-consume
command relationships. Unlike the rest of the test suite (each command
mocked independently, canned response per call), these tests share ONE
mutable fake-Linear store across both calls in a pair, so the second call's
behavior genuinely depends on what the first call actually did -- not just
two isolated contract checks that happen to use matching literals.

Covers exactly the four gaps identified when asked "were the reverse pairs
tested together, not just individually":
  1. archive_issue -> unarchive_issue restores the specific issue's state
  2. link_issues -> unlink_issues removes the SPECIFIC relation created,
     not just any relation, and a second unlink of the same id fails
  3. resolve_comment -> unresolve_comment toggles the same comment's state
  4. create_cycle produces a cycle that a sprint_health-shaped query
     (cycle(id:) lookup) can actually see and read back correctly
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "handlers" / "handler.py"


def load_handler():
    spec = importlib.util.spec_from_file_location("linear_guard_handler", HANDLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_failure(fn, message_fragment):
    try:
        fn()
    except RuntimeError as exc:
        assert message_fragment in str(exc), f"expected {message_fragment!r} in {exc!r}"
    else:
        raise AssertionError(f"expected failure containing {message_fragment!r}")


class FakeLinear:
    """A tiny in-memory Linear stand-in. Mutations write to it; queries and
    later mutations read from it -- so a second call can only see what a
    first call actually did, the way the real API would behave."""

    def __init__(self):
        self.issues = {
            "i1": {
                "id": "i1", "identifier": "RAI-1", "title": "Test issue",
                "url": "https://linear.app/i1", "archived": False,
            }
        }
        self.relations = {}
        self._relation_seq = 0
        self.comments = {"c1": {"id": "c1", "resolvedAt": None}}
        self.cycles = {}


def test_archive_unarchive_issue(h):
    """archive_issue sets archived=True; unarchive_issue must observe and
    clear that SAME flag on the SAME issue, not just return a canned OK."""
    fl = FakeLinear()

    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        if "issueArchive" in query:
            issue = fl.issues[variables["issueId"]]
            issue["archived"] = True
            return 200, {"issueArchive": {"success": True}}
        if "issueUnarchive" in query:
            issue = fl.issues[variables["issueId"]]
            issue["archived"] = False
            return 200, {
                "issueUnarchive": {
                    "success": True,
                    "entity": {
                        "id": issue["id"], "identifier": issue["identifier"],
                        "title": issue["title"], "url": issue["url"],
                    },
                }
            }
        raise AssertionError("unexpected query")

    h._graphql = fake_graphql
    try:
        assert fl.issues["i1"]["archived"] is False

        archive_result, _ = h.linear_archive_issue({"issue_id": "i1"}, None)
        assert archive_result["archived"] is True
        assert fl.issues["i1"]["archived"] is True, "fake state did not actually flip to archived"

        unarchive_result, _ = h.linear_unarchive_issue({"issue_id": "i1"}, None)
        assert unarchive_result["issue_id"] == "i1"
        assert unarchive_result["identifier"] == "RAI-1"
        assert fl.issues["i1"]["archived"] is False, "unarchive did not actually clear the archived flag"
    finally:
        del h._graphql

    print("PASS: archive_issue -> unarchive_issue restores real state")


def test_link_unlink_issues(h):
    """unlink_issues must remove the SPECIFIC relation link_issues created --
    not merely accept any relation_id string and report success."""
    fl = FakeLinear()

    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        if "issueRelationCreate" in query:
            fl._relation_seq += 1
            rid = f"r{fl._relation_seq}"
            inp = variables["input"]
            fl.relations[rid] = dict(inp)
            return 200, {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {
                        "id": rid, "type": inp["type"], "createdAt": "2026-08-23T00:00:00Z",
                        "issue": {"id": inp["issueId"], "identifier": "RAI-1"},
                        "relatedIssue": {"id": inp["relatedIssueId"], "identifier": "RAI-2"},
                    },
                }
            }
        if "issueRelationDelete" in query:
            rid = variables["relationId"]
            if rid not in fl.relations:
                # Real Linear behavior for an unknown/already-deleted id: no
                # match, mutation fails. Simulated here as a GraphQL error.
                return 200, {"errors": [{"message": f"IssueRelation {rid} not found"}]}
            del fl.relations[rid]
            return 200, {"issueRelationDelete": {"success": True, "entityId": rid}}
        raise AssertionError("unexpected query")

    h._graphql = fake_graphql
    try:
        link_result, _ = h.linear_link_issues(
            {"issue_id": "i1", "related_issue_id": "i2", "type": "blocks"}, None
        )
        relation_id = link_result["relation_id"]
        assert relation_id in fl.relations, "link_issues did not actually create a relation in fake state"
        assert fl.relations[relation_id]["type"] == "blocks"

        unlink_result, _ = h.linear_unlink_issues({"relation_id": relation_id}, None)
        assert unlink_result["relation_id"] == relation_id
        assert relation_id not in fl.relations, "unlink_issues did not remove the specific relation"

        # The important negative check: unlinking the SAME id again must
        # fail (it's gone), proving unlink targets a specific record rather
        # than always reporting success regardless of what's actually there.
        expect_failure(
            lambda: h.linear_unlink_issues({"relation_id": relation_id}, None),
            "Linear did not confirm the issue-relation delete",
        )
    finally:
        del h._graphql

    print("PASS: link_issues -> unlink_issues removes the specific relation, not just any")


def test_resolve_unresolve_comment(h):
    """resolve_comment and unresolve_comment must toggle the SAME comment's
    resolvedAt in shared state, not return independently canned values."""
    fl = FakeLinear()

    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        comment = fl.comments[variables["commentId"]]
        if "commentResolve" in query:
            comment["resolvedAt"] = "2026-08-23T00:00:00Z"
            return 200, {"commentResolve": {"success": True, "comment": dict(comment)}}
        if "commentUnresolve" in query:
            comment["resolvedAt"] = None
            return 200, {"commentUnresolve": {"success": True, "comment": dict(comment)}}
        raise AssertionError("unexpected query")

    h._graphql = fake_graphql
    try:
        assert fl.comments["c1"]["resolvedAt"] is None

        resolve_result, _ = h.linear_resolve_comment({"comment_id": "c1"}, None)
        assert resolve_result["resolved_at"] == "2026-08-23T00:00:00Z"
        assert fl.comments["c1"]["resolvedAt"] == "2026-08-23T00:00:00Z", "resolve did not set shared state"

        unresolve_result, _ = h.linear_unresolve_comment({"comment_id": "c1"}, None)
        assert unresolve_result["resolved_at"] == ""
        assert fl.comments["c1"]["resolvedAt"] is None, "unresolve did not clear shared state"
    finally:
        del h._graphql

    print("PASS: resolve_comment -> unresolve_comment toggles the same comment's state")


def test_create_cycle_visible_to_sprint_health_shape(h):
    """A cycle produced by create_cycle must be readable back through the
    exact cycle(id:) lookup shape linear_sprint_health uses -- same fields,
    same values, proving the write and the read agree on what a cycle is."""
    fl = FakeLinear()

    def fake_graphql(query, variables=None, *, is_write=False):
        if "cycleCreate" in query:
            assert is_write is True
            inp = variables["input"]
            cid = "c1"
            fl.cycles[cid] = {
                "id": cid, "number": 7, "name": inp.get("name"),
                "startsAt": inp["startsAt"], "endsAt": inp["endsAt"],
                "completedAt": None, "teamId": inp["teamId"],
            }
            return 200, {"cycleCreate": {"success": True, "cycle": dict(fl.cycles[cid])}}
        if "RailCallSprintHealth" in query:
            # Mirrors linear_sprint_health's real query shape: cycle(id:) with
            # team + a bounded issues connection. No issues seeded here --
            # this test is specifically about the cycle fields themselves.
            cycle = fl.cycles.get(variables["cycleId"])
            if cycle is None:
                return 200, {"cycle": None}
            return 200, {
                "cycle": {
                    "id": cycle["id"], "number": cycle["number"], "name": cycle["name"],
                    "startsAt": cycle["startsAt"], "endsAt": cycle["endsAt"],
                    "completedAt": cycle["completedAt"],
                    "team": {"id": cycle["teamId"], "name": "RailCall", "key": "RAI"},
                    "issues": {"nodes": []},
                }
            }
        raise AssertionError("unexpected query")

    h._graphql = fake_graphql
    try:
        create_result, _ = h.linear_create_cycle(
            {
                "team_id": "t1",
                "starts_at": "2026-09-01T00:00:00Z",
                "ends_at": "2026-09-14T00:00:00Z",
                "name": "Sprint 7",
            },
            None,
        )
        created_cycle_id = create_result["cycle_id"]
        assert created_cycle_id in fl.cycles, "create_cycle did not actually store the cycle"

        health_result, _ = h.linear_sprint_health({"cycle_id": created_cycle_id}, None)
        assert health_result["cycle_id"] == created_cycle_id
        assert health_result["cycle_name"] == "Sprint 7"
        assert health_result["cycle_number"] == 7
        assert health_result["total_issues"] == 0
    finally:
        del h._graphql

    print("PASS: create_cycle -> sprint_health reads back the same cycle correctly")


def main() -> int:
    h = load_handler()
    test_archive_unarchive_issue(h)
    test_link_unlink_issues(h)
    test_resolve_unresolve_comment(h)
    test_create_cycle_visible_to_sprint_health_shape(h)
    print("V1.7.0 STATEFUL PAIR TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
