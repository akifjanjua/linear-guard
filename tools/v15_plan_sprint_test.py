#!/usr/bin/env python3
"""Unit and governance tests for Linear Guard's sprint-plan composite."""

from __future__ import annotations

import importlib.util
import json
import uuid
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


def plan_json():
    return json.dumps([
        {
            "title": "Build approval flow",
            "description": "Implement bounded approval UX.",
            "priority": 2,
            "estimate": 3,
            "assignee_id": "u1",
            "label_ids": ["l1"],
        },
        {
            "title": "Document receipt trail",
            "description": "Write the operator guide.",
            "priority": 3,
            "estimate": 2,
            "assignee_id": "u2",
            "label_ids": ["l1", "l2"],
        },
    ])


def preflight_data(*, cycle_team="t1", state_team="t1", label_team="t1", project_teams=None, parent_team="t1"):
    if project_teams is None:
        project_teams = ["t1"]
    return {
        "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
        "cycle": {
            "id": "c1",
            "number": 4,
            "name": "Sprint 4",
            "startsAt": "2026-07-30T00:00:00Z",
            "endsAt": "2099-08-06T00:00:00Z",
            "completedAt": None,
            "team": {"id": cycle_team, "name": "RailCall"},
        },
        "targetProject": {
            "id": "p1",
            "name": "Linear Guard",
            "archivedAt": None,
            "teamIds": project_teams,
        },
        "targetState": {
            "id": "s1",
            "name": "Todo",
            "type": "unstarted",
            "archivedAt": None,
            "team": {"id": state_team, "name": "RailCall"},
        },
        "parentIssue": {
            "id": "parent1",
            "identifier": "RAI-1",
            "title": "Sprint objective",
            "archivedAt": None,
            "team": {"id": parent_team, "name": "RailCall"},
        },
        "targetAssignee0": {"id": "u1", "name": "Akif"},
        "targetAssignee1": {"id": "u2", "name": "Reviewer"},
        "targetLabel0": {
            "id": "l1",
            "name": "Feature",
            "isGroup": False,
            "archivedAt": None,
            "team": {"id": label_team, "name": "RailCall"},
        },
        "targetLabel1": {
            "id": "l2",
            "name": "Docs",
            "isGroup": False,
            "archivedAt": None,
            "team": None,
        },
    }


def created_issue(issue_input, number):
    return {
        "id": issue_input["id"],
        "identifier": f"RAI-{number}",
        "title": issue_input["title"],
        "priority": issue_input.get("priority", 0),
        "estimate": issue_input.get("estimate", 0),
        "createdAt": "2026-07-31T00:00:00Z",
        "state": {"id": "s1", "name": "Todo", "type": "unstarted"},
        "assignee": (
            {"id": issue_input["assigneeId"], "name": "Assigned"}
            if issue_input.get("assigneeId")
            else None
        ),
        "project": {"id": "p1", "name": "Linear Guard"},
        "cycle": {"id": "c1", "number": 4, "name": "Sprint 4"},
        "parent": {
            "id": "parent1",
            "identifier": "RAI-1",
            "title": "Sprint objective",
        },
        "labels": {
            "nodes": [
                {"id": label_id, "name": "Label"}
                for label_id in issue_input.get("labelIds", [])
            ]
        },
        "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
    }


def full_inputs():
    return {
        "team_id": "t1",
        "cycle_id": "c1",
        "project_id": "p1",
        "state_id": "s1",
        "parent_issue_id": "RAI-1",
        "issues_json": plan_json(),
    }


def expect_runtime(callable_, message_part):
    try:
        callable_()
    except RuntimeError as exc:
        assert message_part in str(exc), str(exc)
        return
    raise AssertionError(f"Expected RuntimeError containing {message_part!r}")


def test_success(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, variables, is_write))
        if "RailCallPlanSprintPreflight" in query:
            assert is_write is False
            assert variables["teamId"] == "t1"
            assert variables["cycleId"] == "c1"
            assert {variables["assigneeId0"], variables["assigneeId1"]} == {"u1", "u2"}
            assert {variables["labelId0"], variables["labelId1"]} == {"l1", "l2"}
            return 200, preflight_data()
        if "RailCallPlanSprint" in query:
            assert is_write is True
            issue_inputs = variables["input"]["issues"]
            assert len(issue_inputs) == 2
            assert len({item["id"] for item in issue_inputs}) == 2
            for item in issue_inputs:
                uuid.UUID(item["id"])
                assert item["teamId"] == "t1"
                assert item["cycleId"] == "c1"
                assert item["projectId"] == "p1"
                assert item["stateId"] == "s1"
                assert item["parentId"] == "parent1"
            assert issue_inputs[0]["assigneeId"] == "u1"
            assert issue_inputs[0]["labelIds"] == ["l1"]
            assert issue_inputs[1]["assigneeId"] == "u2"
            assert issue_inputs[1]["labelIds"] == ["l1", "l2"]
            return 200, {
                "issueBatchCreate": {
                    "success": True,
                    "issues": [
                        created_issue(issue_inputs[0], 10),
                        created_issue(issue_inputs[1], 11),
                    ],
                }
            }
        raise AssertionError("Unexpected GraphQL operation")

    h._graphql = fake_graphql
    output, _ = h.linear_plan_sprint(full_inputs(), None)
    assert output["ok"] is True
    assert output["atomic_batch"] is True
    assert output["write_request_count"] == 1
    assert output["requested_count"] == 2
    assert output["created_count"] == 2
    assert output["client_id_mapping_verified"] is True
    assert json.loads(output["completed_steps_json"]) == [
        "preflight",
        "issue_batch_create",
    ]
    blast = json.loads(output["blast_radius_json"])
    assert blast["issues_created"] == 2
    assert blast["assignee_links"] == 2
    assert blast["label_links"] == 3
    created_raw = output["created_issues_json"]
    assert "http://" not in created_raw
    assert "https://" not in created_raw
    assert json.loads(created_raw) == ["RAI-10", "RAI-11"]
    assert json.loads(output["created_issue_ids_json"]) == [
        calls[1][1]["input"]["issues"][0]["id"],
        calls[1][1]["input"]["issues"][1]["id"],
    ]
    detail_1 = json.loads(output["created_issue_1_json"])
    detail_2 = json.loads(output["created_issue_2_json"])
    assert detail_1["identifier"] == "RAI-10"
    assert detail_2["identifier"] == "RAI-11"
    assert detail_1["title_preview"] == "Build approval flow"
    assert detail_2["title_preview"] == "Document receipt trail"
    assert output["created_issue_3_json"] == "null"
    assert output["created_issue_4_json"] == "null"
    assert output["created_issue_5_json"] == "null"
    receipt_strings = [
        output["created_issues_json"],
        output["created_issue_ids_json"],
        output["created_issue_1_json"],
        output["created_issue_2_json"],
        output["created_issue_3_json"],
        output["created_issue_4_json"],
        output["created_issue_5_json"],
    ]
    assert all(len(value) <= 280 for value in receipt_strings)
    assert len(calls) == 2
    assert [call[2] for call in calls] == [False, True]


def test_validation(h):
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": "[]"}, None),
        "between 2 and 5",
    )
    too_many = [{"title": f"Issue {index}"} for index in range(6)]
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": json.dumps(too_many)}, None),
        "between 2 and 5",
    )
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": json.dumps([{"title": "A", "unknown": 1}, {"title": "B"}])}, None),
        "unsupported field",
    )
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": json.dumps([{"title": "Same"}, {"title": "same"}])}, None),
        "titles must be unique",
    )
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": json.dumps([{"title": "A", "priority": 5}, {"title": "B"}])}, None),
        "priority must be between 0 and 4",
    )
    expect_runtime(
        lambda: h.linear_plan_sprint({"team_id": "t1", "cycle_id": "c1", "issues_json": json.dumps([{"title": "A", "label_ids": [str(i) for i in range(6)]}, {"title": "B"}])}, None),
        "at most 5 labels",
    )


def test_preflight_rejects_before_write(h):
    scenarios = [
        (preflight_data(cycle_team="other"), "cycle does not belong"),
        (preflight_data(state_team="other"), "workflow state does not belong"),
        (preflight_data(project_teams=["other"]), "project is not linked"),
        (preflight_data(parent_team="other"), "parent issue does not belong"),
        (preflight_data(label_team="other"), "belongs to another team"),
    ]
    for data, message in scenarios:
        calls = []

        def fake_graphql(query, variables=None, *, is_write=False, data=data):
            calls.append(is_write)
            if "RailCallPlanSprintPreflight" in query:
                return 200, data
            raise AssertionError("Write must not be attempted after failed preflight")

        h._graphql = fake_graphql
        expect_runtime(lambda: h.linear_plan_sprint(full_inputs(), None), message)
        assert calls == [False]


def test_batch_count_mismatch_is_honest(h):
    mutation_inputs = []

    def fake_graphql(query, variables=None, *, is_write=False):
        if "RailCallPlanSprintPreflight" in query:
            return 200, preflight_data()
        if "RailCallPlanSprint" in query:
            mutation_inputs.extend(variables["input"]["issues"])
            return 200, {
                "issueBatchCreate": {
                    "success": True,
                    "issues": [created_issue(mutation_inputs[0], 10)],
                }
            }
        raise AssertionError("Unexpected GraphQL operation")

    h._graphql = fake_graphql
    expect_runtime(
        lambda: h.linear_plan_sprint(full_inputs(), None),
        "unexpected issue count",
    )


def main():
    h = load_handler()
    test_validation(h)
    print("PASS: bounded sprint-plan input validation")
    test_preflight_rejects_before_write(h)
    print("PASS: all sprint references preflight before the transaction")
    test_success(h)
    print("PASS: one approval creates a fully configured issue set in one transaction")
    test_batch_count_mismatch_is_honest(h)
    print("PASS: unexpected batch results fail loudly with recovery guidance")
    print("PASS: created-issue evidence is sharded below the receipt string cap")
    print("PASS: sprint blast radius and created issue evidence are receipt-safe")
    print("V1.5 PLAN SPRINT TESTS PASSED")


if __name__ == "__main__":
    main()
