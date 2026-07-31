#!/usr/bin/env python3
"""Unit and governance tests for Linear Guard's sprint-rebalance composite."""

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


def issue(index, *, team="t1", priority=2, estimate=0, state="s0", assignee=None, project=None, cycle="c0", labels=None):
    if labels is None:
        labels = []
    return {
        "id": f"00000000-0000-4000-8000-00000000000{index}",
        "identifier": f"RAI-{index}",
        "title": f"Issue {index}",
        "archivedAt": None,
        "priority": priority,
        "estimate": estimate,
        "state": {"id": state, "name": "Todo", "type": "unstarted", "team": {"id": team, "name": "RailCall"}},
        "assignee": ({"id": assignee, "name": "Akif"} if assignee else None),
        "project": ({"id": project, "name": "Project", "archivedAt": None} if project else None),
        "cycle": ({"id": cycle, "number": 1, "name": "Cycle 1", "completedAt": None, "team": {"id": team, "name": "RailCall"}} if cycle else None),
        "labels": {"nodes": [{"id": label, "name": label, "isGroup": False, "archivedAt": None, "team": {"id": team, "name": "RailCall"}} for label in labels]},
        "team": {"id": team, "name": "RailCall", "key": "RAI"},
        "updatedAt": "2026-07-31T00:00:00Z",
    }


def preflight_data(*, issue2_team="t1", state_team="t1", cycle_team="t1", label_team="t1", project_teams=None):
    if project_teams is None:
        project_teams = ["t1"]
    return {
        "issue0": issue(1),
        "issue1": issue(2, team=issue2_team),
        "targetState": {"id": "s1", "name": "In Progress", "type": "started", "archivedAt": None, "team": {"id": state_team, "name": "RailCall"}},
        "targetAssignee": {"id": "u1", "name": "Akif"},
        "targetProject": {"id": "p1", "name": "Linear Guard", "archivedAt": None, "teamIds": project_teams},
        "targetCycle": {"id": "c1", "number": 2, "name": "Cycle 2", "completedAt": None, "team": {"id": cycle_team, "name": "RailCall"}},
        "targetLabel0": {"id": "l1", "name": "Ready", "isGroup": False, "archivedAt": None, "team": {"id": label_team, "name": "RailCall"}},
    }


def inputs():
    return {
        "issue_ids_json": json.dumps(["RAI-1", "RAI-2"]),
        "priority": 3,
        "estimate": 5,
        "state_id": "s1",
        "assignee_id": "u1",
        "project_id": "p1",
        "cycle_id": "c1",
        "label_ids_json": json.dumps(["l1"]),
    }


def expect_runtime(callable_, message_part):
    try:
        callable_()
    except RuntimeError as exc:
        assert message_part in str(exc), str(exc)
        return
    raise AssertionError(f"Expected RuntimeError containing {message_part!r}")


def updated_issue(original):
    result = dict(original)
    result.update({
        "priority": 3,
        "estimate": 5,
        "state": {"id": "s1", "name": "In Progress", "type": "started"},
        "assignee": {"id": "u1", "name": "Akif"},
        "project": {"id": "p1", "name": "Linear Guard"},
        "cycle": {"id": "c1", "number": 2, "name": "Cycle 2"},
        "labels": {"nodes": [{"id": "l1", "name": "Ready"}]},
        "team": {"id": "t1", "name": "RailCall", "key": "RAI"},
    })
    return result


def test_success(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, variables, is_write))
        if "RailCallRebalanceSprintPreflight" in query:
            assert is_write is False
            return 200, preflight_data()
        if "RailCallRebalanceSprint" in query:
            assert is_write is True
            assert variables["ids"] == [
                "00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002",
            ]
            assert variables["input"] == {
                "priority": 3,
                "estimate": 5,
                "stateId": "s1",
                "assigneeId": "u1",
                "projectId": "p1",
                "cycleId": "c1",
                "labelIds": ["l1"],
            }
            return 200, {
                "issueBatchUpdate": {
                    "success": True,
                    "issues": [updated_issue(issue(1)), updated_issue(issue(2))],
                }
            }
        raise AssertionError("Unexpected GraphQL operation")

    h._graphql = fake_graphql
    output, _ = h.linear_rebalance_sprint(inputs(), None)
    assert output["ok"] is True
    assert output["batch_update"] is True
    assert output["write_request_count"] == 1
    assert output["requested_count"] == 2
    assert output["updated_count"] == 2
    assert output["changed_issue_count"] == 2
    assert json.loads(output["updated_issues_json"]) == ["RAI-1", "RAI-2"]
    assert json.loads(output["changes_requested_json"]) == [
        "priority", "estimate", "state", "assignee", "project", "cycle", "labels"
    ]
    assert json.loads(output["completed_steps_json"]) == ["preflight", "issue_batch_update"]
    assert json.loads(output["updated_issue_1_json"])["identifier"] == "RAI-1"
    assert json.loads(output["updated_issue_2_json"])["identifier"] == "RAI-2"
    assert output["updated_issue_3_json"] == "null"
    receipt_strings = [
        output["updated_issues_json"], output["updated_issue_ids_json"],
        output["updated_issue_1_json"], output["updated_issue_2_json"],
        output["updated_issue_3_json"], output["updated_issue_4_json"],
        output["updated_issue_5_json"], output["blast_radius_json"],
        output["changes_requested_json"],
    ]
    assert all(len(value) <= 280 for value in receipt_strings)
    assert [call[2] for call in calls] == [False, True]


def test_validation(h):
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": "[]", "priority": 2}, None),
        "between 2 and 5",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "rai-1"]), "priority": 2}, None),
        "duplicate",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "RAI-2"])}, None),
        "Supply at least one shared",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "RAI-2"]), "priority": 5}, None),
        "between 0 and 4",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "RAI-2"]), "estimate": 101}, None),
        "between 0 and 100",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "RAI-2"]), "assignee_id": "u1", "clear_assignee": True}, None),
        "not both",
    )
    expect_runtime(
        lambda: h.linear_rebalance_sprint({"issue_ids_json": json.dumps(["RAI-1", "RAI-2"]), "label_ids_json": json.dumps([str(i) for i in range(6)])}, None),
        "at most 5 labels",
    )


def test_preflight_rejects_before_write(h):
    scenarios = [
        (preflight_data(issue2_team="other"), "same team"),
        (preflight_data(state_team="other"), "workflow state does not belong"),
        (preflight_data(cycle_team="other"), "cycle does not belong"),
        (preflight_data(label_team="other"), "belongs to another team"),
        (preflight_data(project_teams=["other"]), "project is not associated"),
    ]
    for data, message in scenarios:
        calls = []

        def fake_graphql(query, variables=None, *, is_write=False, data=data):
            calls.append(is_write)
            if "RailCallRebalanceSprintPreflight" in query:
                return 200, data
            raise AssertionError("Write must not be attempted after failed preflight")

        h._graphql = fake_graphql
        expect_runtime(lambda: h.linear_rebalance_sprint(inputs(), None), message)
        assert calls == [False]


def test_noop_rejected_before_write(h):
    data = preflight_data()
    for key in ("issue0", "issue1"):
        data[key] = updated_issue(data[key])
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append(is_write)
        if "RailCallRebalanceSprintPreflight" in query:
            return 200, data
        raise AssertionError("No-op must not reach write execution")

    h._graphql = fake_graphql
    expect_runtime(lambda: h.linear_rebalance_sprint(inputs(), None), "already match every issue")
    assert calls == [False]


def test_batch_mismatch_is_honest(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        if "RailCallRebalanceSprintPreflight" in query:
            return 200, preflight_data()
        if "RailCallRebalanceSprint" in query:
            return 200, {"issueBatchUpdate": {"success": True, "issues": [updated_issue(issue(1))]}}
        raise AssertionError("Unexpected GraphQL operation")

    h._graphql = fake_graphql
    expect_runtime(lambda: h.linear_rebalance_sprint(inputs(), None), "unexpected issue count")


def main():
    h = load_handler()
    test_validation(h)
    print("PASS: bounded sprint-rebalance input validation")
    test_preflight_rejects_before_write(h)
    print("PASS: every issue and shared reference preflights before the batch")
    test_noop_rejected_before_write(h)
    print("PASS: all-no-op rebalances are rejected before write execution")
    test_success(h)
    print("PASS: one approval applies one shared decision through issueBatchUpdate")
    test_batch_mismatch_is_honest(h)
    print("PASS: unexpected batch results fail loudly with recovery guidance")
    print("PASS: updated-issue evidence is sharded below the receipt string cap")
    print("V1.5 REBALANCE SPRINT TESTS PASSED")


if __name__ == "__main__":
    main()
