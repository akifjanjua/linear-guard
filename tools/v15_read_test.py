#!/usr/bin/env python3
"""Unit tests for Linear Guard v1.5.0 discovery and sprint-health reads."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "handlers" / "handler.py"


def load_handler():
    spec = importlib.util.spec_from_file_location("linear_guard_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    h = load_handler()
    original = h._graphql

    def fake_graphql(query, variables=None, **kwargs):
        if "RailCallWorkspaceMembers" in query:
            return 200, {
                "users": {"nodes": [
                    {"id": "u2", "name": "Zara", "email": "z@example.com"},
                    {"id": "u1", "name": "Akif", "email": "a@example.com"},
                ]}
            }
        if "RailCallTeamCycles" in query:
            return 200, {
                "team": {
                    "id": "t1", "name": "RailCall", "key": "RAI",
                    "cycles": {"nodes": [
                        {"id": "c1", "number": 1, "name": "Sprint 1",
                         "startsAt": "2026-07-01T00:00:00Z",
                         "endsAt": "2026-07-14T00:00:00Z",
                         "completedAt": "2026-07-14T00:00:00Z"}
                    ]}
                }
            }
        if "RailCallSprintHealth" in query:
            return 200, {
                "cycle": {
                    "id": "c2", "number": 2, "name": "",
                    "startsAt": "2026-07-15T00:00:00Z",
                    "endsAt": "2026-07-31T00:00:00Z",
                    "completedAt": None,
                    "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
                    "issues": {"nodes": [
                        {"id": "i1", "identifier": "RAI-1", "title": "Done",
                         "priority": 3, "estimate": 2,
                         "updatedAt": "2026-07-29T00:00:00Z",
                         "state": {"id": "s1", "name": "Done", "type": "completed"},
                         "assignee": {"id": "u1", "name": "Akif"},
                         "labels": {"nodes": [{"id": "l1", "name": "Feature"}]}},
                        {"id": "i2", "identifier": "RAI-2", "title": "Needs attention",
                         "priority": 1, "estimate": 0,
                         "updatedAt": "2026-01-01T00:00:00Z",
                         "state": {"id": "s2", "name": "In Progress", "type": "started"},
                         "assignee": None, "labels": {"nodes": []}},
                    ]}
                }
            }
        raise AssertionError("unexpected GraphQL query")

    h._graphql = fake_graphql
    try:
        members, _ = h.linear_list_members({}, None)
        assert members["member_count"] == 2
        assert json.loads(members["members_json"])[0]["name"] == "Akif"

        cycles, _ = h.linear_list_cycles({"team_id": "t1"}, None)
        assert cycles["cycle_count"] == 1
        assert json.loads(cycles["cycles_json"])[0]["id"] == "c1"

        health, _ = h.linear_sprint_health(
            {"cycle_id": "c2", "stale_days": 7}, None
        )
        assert health["total_issues"] == 2
        assert health["completed_issues"] == 1
        assert health["completion_percent"] == 50.0
        assert health["unassigned_issues"] == 1
        assert health["high_or_urgent_issues"] == 1
        assert health["without_estimate"] == 1
        assert health["without_labels"] == 1
        assert health["stale_issues"] == 1
        assert health["cycle_name"] == "Cycle 2"

        warnings = json.loads(health["warnings_json"])
        assert "1 issue(s) have no labels" in warnings

        assert json.loads(health["attention_issues_json"])[0]["identifier"] == "RAI-2"

        try:
            h.linear_sprint_health({"cycle_id": "c2", "stale_days": 0}, None)
        except RuntimeError as exc:
            assert "between 1 and 90" in str(exc)
        else:
            raise AssertionError("stale_days validation did not fail")
    finally:
        h._graphql = original

    print("PASS: list_members")
    print("PASS: list_cycles")
    print("PASS: sprint_health metrics and bounded inputs")
    print("V1.5 READ TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
