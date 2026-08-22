#!/usr/bin/env python3
"""Unit tests for Linear Guard's v1.6.1 parent-issue linking (create_issue/
update_issue extensions) and the new get_issue_history command."""

from __future__ import annotations

import json
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


def test_create_issue_parent(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert variables["input"]["parentId"] == "p1"
        return 200, {
            "issueCreate": {
                "success": True,
                "issue": {"id": "i2", "identifier": "RAI-10", "title": "Sub-task", "url": "https://linear.app/i2"},
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_create_issue(
            {"team_id": "t1", "title": "Sub-task", "parent_id": "p1"}, None
        )
        assert result["issue_id"] == "i2"

        expect_failure(
            lambda: h.linear_create_issue(
                {"team_id": "t1", "title": "Sub-task", "parent_id": "  "}, None
            ),
            "parent_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: create_issue parent_id")


def test_update_issue_parent(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append(variables["input"])
        assert is_write is True
        return 200, {
            "issueUpdate": {
                "success": True,
                "issue": {
                    "id": "i1",
                    "identifier": "RAI-9",
                    "title": "Needs triage",
                    "url": "https://linear.app/i1",
                    "priority": 2,
                    "updatedAt": "2026-08-22T00:00:00Z",
                    "state": None,
                    "project": None,
                    "parent": {"id": "p1", "identifier": "RAI-1"},
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_update_issue({"issue_id": "i1", "parent_id": "p1"}, None)
        assert calls[-1]["parentId"] == "p1"
        assert result["parent_id"] == "p1"
        assert result["parent_identifier"] == "RAI-1"

        result, _ = h.linear_update_issue({"issue_id": "i1", "clear_parent": True}, None)
        assert calls[-1]["parentId"] is None

        expect_failure(
            lambda: h.linear_update_issue(
                {"issue_id": "i1", "parent_id": "p1", "clear_parent": True}, None
            ),
            "Supply parent_id or clear_parent",
        )
    finally:
        del h._graphql

    print("PASS: update_issue parent_id/clear_parent")


def test_get_issue_history(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is False
        assert "history" in query
        assert variables == {"issueId": "i1"}
        nodes = []
        for i in range(3):
            nodes.append({
                "id": f"h{i}",
                "createdAt": f"2026-08-2{i}T00:00:00Z",
                "actorId": "u1",
                "actor": {"id": "u1", "name": "Akif"},
                "botActor": None,
                "fromTitle": None,
                "toTitle": None,
                "fromPriority": None,
                "toPriority": None,
                "fromState": {"id": "s1", "name": "Todo"} if i == 0 else None,
                "toState": {"id": "s2", "name": "In Progress"} if i == 0 else None,
                "fromAssignee": None,
                "toAssignee": None,
                "fromProject": None,
                "toProject": None,
                "fromCycle": None,
                "toCycle": None,
                "fromParent": None,
                "toParent": None,
                "addedLabels": [{"id": "l1", "name": "Bug"}] if i == 1 else [],
                "removedLabels": [],
            })
        return 200, {"issue": {"history": {"nodes": nodes}}}

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_get_issue_history({"issue_id": "i1"}, None)
        assert result["issue_id"] == "i1"
        assert result["entry_count"] == 3
        assert result["returned_count"] == 3
        assert result["has_more"] is False

        entries = json.loads(result["history_json"])
        assert len(entries) == 3
        assert entries[0]["actor_name"] == "Akif"
        assert entries[0]["to_state_name"] == "In Progress"
        assert entries[1]["added_label_names"] == ["Bug"]

        result, _ = h.linear_get_issue_history({"issue_id": "i1", "offset": 0, "limit": 2}, None)
        assert result["returned_count"] == 2
        assert result["has_more"] is True
        assert result["next_offset"] == 2

        expect_failure(
            lambda: h.linear_get_issue_history({"issue_id": "i1", "limit": 0}, None),
            "limit must be between 1 and 25",
        )
        expect_failure(
            lambda: h.linear_get_issue_history({"issue_id": ""}, None),
            "issue_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: get_issue_history")


def main() -> int:
    h = load_handler()
    test_create_issue_parent(h)
    test_update_issue_parent(h)
    test_get_issue_history(h)
    print("V1.6.1 PARENT LINKING AND ISSUE HISTORY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
