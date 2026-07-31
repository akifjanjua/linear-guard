#!/usr/bin/env python3
"""Unit and governance tests for Linear Guard's triage composite."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "handlers" / "handler.py"


def load_handler():
    spec = importlib.util.spec_from_file_location("linear_guard_handler", HANDLER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight_data(*, state_team="t1", cycle_team="t1", label_team="t1"):
    return {
        "issue": {
            "id": "i1",
            "identifier": "RAI-9",
            "title": "Needs triage",
            "url": "https://linear.app/issue/RAI-9",
            "priority": 3,
            "updatedAt": "2026-07-30T00:00:00Z",
            "state": {
                "id": "s-old",
                "name": "Todo",
                "type": "unstarted",
                "team": {"id": "t1", "name": "RailCall"},
            },
            "assignee": None,
            "project": None,
            "cycle": None,
            "labels": {"nodes": [{"id": "l-old", "name": "Needs review"}]},
            "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
        },
        "targetAssignee": {"id": "u1", "name": "Akif"},
        "targetState": {
            "id": "s-new",
            "name": "In Progress",
            "type": "started",
            "archivedAt": None,
            "team": {"id": state_team, "name": "RailCall"},
        },
        "targetProject": {"id": "p1", "name": "Module", "archivedAt": None, "teamIds": ["t1"]},
        "targetCycle": {
            "id": "c1",
            "number": 1,
            "name": "Cycle 1",
            "completedAt": None,
            "team": {"id": cycle_team, "name": "RailCall"},
        },
        "targetLabel0": {
            "id": "l1",
            "name": "Bug",
            "isGroup": False,
            "archivedAt": None,
            "team": {"id": label_team, "name": "RailCall"},
        },
    }


def updated_issue():
    return {
        "id": "i1",
        "identifier": "RAI-9",
        "title": "Needs triage",
        "url": "https://linear.app/issue/RAI-9",
        "priority": 2,
        "updatedAt": "2026-07-31T00:00:00Z",
        "state": {"id": "s-new", "name": "In Progress", "type": "started"},
        "assignee": {"id": "u1", "name": "Akif"},
        "project": {"id": "p1", "name": "Module"},
        "cycle": {"id": "c1", "number": 1, "name": "Cycle 1"},
        "labels": {"nodes": [{"id": "l1", "name": "Bug"}]},
        "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
    }


def test_success(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, variables, is_write))
        if "RailCallTriagePreflight" in query:
            return 200, preflight_data()
        if "RailCallTriageIssue" in query:
            assert is_write is True
            assert variables["input"] == {
                "priority": 2,
                "stateId": "s-new",
                "assigneeId": "u1",
                "projectId": "p1",
                "cycleId": "c1",
                "labelIds": ["l1"],
            }
            return 200, {
                "issueUpdate": {"success": True, "issue": updated_issue()}
            }
        if "RailCallTriageComment" in query:
            assert is_write is True
            assert variables["input"]["issueId"] == "RAI-9"
            return 200, {
                "commentCreate": {
                    "success": True,
                    "comment": {
                        "id": "comment-1",
                        "createdAt": "2026-07-31T00:00:01Z",
                        "body": variables["input"]["body"],
                    },
                }
            }
        raise AssertionError("unexpected GraphQL operation")

    original = h._graphql
    h._graphql = fake_graphql
    try:
        result, artifact = h.linear_triage_issue(
            {
                "issue_id": "RAI-9",
                "priority": 2,
                "state_id": "s-new",
                "assignee_id": "u1",
                "project_id": "p1",
                "cycle_id": "c1",
                "label_ids_json": '["l1"]',
                "triage_note": "Weekly triage decision.",
            },
            None,
        )
    finally:
        h._graphql = original

    assert artifact is None
    assert result["operation"] == "triage_issue"
    assert result["identifier"] == "RAI-9"
    assert result["comment_id"] == "comment-1"
    assert result["triage_note_added"] is True
    assert json.loads(result["completed_steps_json"]) == [
        "issue_update",
        "triage_comment",
    ]
    changes = json.loads(result["changes_applied_json"])
    assert {change["field"] for change in changes} == {
        "priority",
        "state",
        "assignee",
        "project",
        "cycle",
        "labels",
    }
    assert [call[2] for call in calls] == [False, True, True]


def test_wrong_team_preflight(h):
    writes = []

    def fake_graphql(query, variables=None, *, is_write=False):
        writes.append(is_write)
        return 200, preflight_data(state_team="other-team")

    original = h._graphql
    h._graphql = fake_graphql
    try:
        try:
            h.linear_triage_issue(
                {"issue_id": "RAI-9", "state_id": "s-new"},
                None,
            )
        except RuntimeError as exc:
            assert "does not belong to the issue's team" in str(exc)
        else:
            raise AssertionError("wrong-team state was not rejected")
    finally:
        h._graphql = original
    assert writes == [False]


def test_noop_rejected(h):
    calls = []
    data = preflight_data()
    data["issue"]["priority"] = 2

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append(is_write)
        return 200, data

    original = h._graphql
    h._graphql = fake_graphql
    try:
        try:
            h.linear_triage_issue(
                {"issue_id": "RAI-9", "priority": 2},
                None,
            )
        except RuntimeError as exc:
            assert "already match" in str(exc)
        else:
            raise AssertionError("no-op triage was not rejected")
    finally:
        h._graphql = original
    assert calls == [False]


def test_partial_failure(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, is_write))
        if "RailCallTriagePreflight" in query:
            return 200, preflight_data()
        if "RailCallTriageIssue" in query:
            return 200, {
                "issueUpdate": {"success": True, "issue": updated_issue()}
            }
        if "RailCallTriageComment" in query:
            raise RuntimeError("simulated comment failure")
        raise AssertionError("unexpected operation")

    original = h._graphql
    h._graphql = fake_graphql
    try:
        try:
            h.linear_triage_issue(
                {
                    "issue_id": "RAI-9",
                    "priority": 2,
                    "triage_note": "Record the decision.",
                },
                None,
            )
        except RuntimeError as exc:
            message = str(exc)
            assert "updated successfully" in message
            assert "Do not rerun the entire triage command blindly" in message
            assert "priority" in message
        else:
            raise AssertionError("partial failure did not fail loudly")
    finally:
        h._graphql = original
    assert [flag for _, flag in calls] == [False, True, True]



def test_clear_fields_and_labels(h):
    calls = []
    data = preflight_data()
    data["issue"]["assignee"] = {"id": "u-old", "name": "Old owner"}
    data["issue"]["project"] = {"id": "p-old", "name": "Old project"}
    data["issue"]["cycle"] = {"id": "c-old", "number": 9, "name": "Old cycle"}

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, variables, is_write))
        if "RailCallTriagePreflight" in query:
            return 200, data
        if "RailCallTriageIssue" in query:
            assert variables["input"] == {
                "assigneeId": None,
                "projectId": None,
                "cycleId": None,
                "labelIds": [],
            }
            result = updated_issue()
            result["assignee"] = None
            result["project"] = None
            result["cycle"] = None
            result["labels"] = {"nodes": []}
            return 200, {"issueUpdate": {"success": True, "issue": result}}
        raise AssertionError("unexpected operation")

    original = h._graphql
    h._graphql = fake_graphql
    try:
        result, _ = h.linear_triage_issue(
            {
                "issue_id": "RAI-9",
                "clear_assignee": True,
                "clear_project": True,
                "clear_cycle": True,
                "label_ids_json": "[]",
            },
            None,
        )
    finally:
        h._graphql = original

    assert json.loads(result["assignee_json"]) is None
    assert json.loads(result["project_json"]) is None
    assert json.loads(result["cycle_json"]) is None
    assert json.loads(result["labels_json"]) == []
    assert [call[2] for call in calls] == [False, True]


def test_project_scope_preflight(h):
    writes = []
    data = preflight_data()
    data["targetProject"]["teamIds"] = ["other-team"]

    def fake_graphql(query, variables=None, *, is_write=False):
        writes.append(is_write)
        return 200, data

    original = h._graphql
    h._graphql = fake_graphql
    try:
        try:
            h.linear_triage_issue(
                {"issue_id": "RAI-9", "project_id": "p1"},
                None,
            )
        except RuntimeError as exc:
            assert "not associated with the issue's team" in str(exc)
        else:
            raise AssertionError("wrong-team project was not rejected")
    finally:
        h._graphql = original
    assert writes == [False]

def test_input_guards(h):
    def must_fail(inputs, fragment):
        try:
            h.linear_triage_issue(inputs, None)
        except RuntimeError as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(f"expected failure containing {fragment!r}")

    must_fail(
        {
            "issue_id": "RAI-9",
            "assignee_id": "u1",
            "clear_assignee": True,
        },
        "not both",
    )
    must_fail(
        {
            "issue_id": "RAI-9",
            "label_ids_json": json.dumps([f"l{i}" for i in range(6)]),
        },
        "at most 5 labels",
    )
    must_fail(
        {"issue_id": "RAI-9", "triage_note": "comment only"},
        "Supply at least one triage property",
    )


def main() -> int:
    h = load_handler()
    test_success(h)
    test_wrong_team_preflight(h)
    test_noop_rejected(h)
    test_partial_failure(h)
    test_clear_fields_and_labels(h)
    test_project_scope_preflight(h)
    test_input_guards(h)
    print("PASS: bounded triage input validation")
    print("PASS: all references preflight before the first mutation")
    print("PASS: one approved command applies a composite issue update")
    print("PASS: no-op requests are rejected before write execution")
    print("PASS: partial comment failure reports completed work honestly")
    print("PASS: explicit clear operations and empty label replacement are bounded")
    print("PASS: project scope is validated against the issue team")
    print("V1.5 TRIAGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
