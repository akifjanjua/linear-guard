#!/usr/bin/env python3
"""Unit tests for Linear Guard's v1.7.0 symmetric completions
(unarchive_issue, update_label, delete_attachment, unlink_issues,
resolve_comment, unresolve_comment) and cycle writes (create_cycle,
update_cycle)."""

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


def test_unarchive_issue(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "issueUnarchive" in query
        assert variables == {"issueId": "i1"}
        return 200, {
            "issueUnarchive": {
                "success": True,
                "entity": {"id": "i1", "identifier": "RAI-9", "title": "Back", "url": "https://linear.app/i1"},
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_unarchive_issue({"issue_id": "i1"}, None)
        assert result["issue_id"] == "i1"
        assert result["identifier"] == "RAI-9"
        assert result["unarchived"] is True

        expect_failure(
            lambda: h.linear_unarchive_issue({"issue_id": ""}, None),
            "issue_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: unarchive_issue")


def test_update_label(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "issueLabelUpdate" in query
        assert variables["labelId"] == "l1"
        assert variables["input"] == {"name": "Bug Fix", "color": "#FF0000"}
        return 200, {
            "issueLabelUpdate": {
                "success": True,
                "issueLabel": {"id": "l1", "name": "Bug Fix", "color": "#FF0000", "description": "", "isGroup": False},
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_update_label(
            {"label_id": "l1", "name": "Bug Fix", "color": "#FF0000"}, None
        )
        assert result["label_id"] == "l1"
        assert result["name"] == "Bug Fix"
        assert result["color"] == "#FF0000"

        expect_failure(
            lambda: h.linear_update_label({"label_id": "l1"}, None),
            "Supply at least one field",
        )
        expect_failure(
            lambda: h.linear_update_label({"label_id": "l1", "color": "red"}, None),
            "color must be a hex color",
        )
    finally:
        del h._graphql

    print("PASS: update_label")


def test_delete_attachment(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "attachmentDelete" in query
        assert variables == {"attachmentId": "a1"}
        return 200, {"attachmentDelete": {"success": True, "entityId": "a1"}}

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_delete_attachment({"attachment_id": "a1"}, None)
        assert result["attachment_id"] == "a1"
        assert result["deleted"] is True

        expect_failure(
            lambda: h.linear_delete_attachment({"attachment_id": ""}, None),
            "attachment_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: delete_attachment")


def test_unlink_issues(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "issueRelationDelete" in query
        assert variables == {"relationId": "r1"}
        return 200, {"issueRelationDelete": {"success": True, "entityId": "r1"}}

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_unlink_issues({"relation_id": "r1"}, None)
        assert result["relation_id"] == "r1"
        assert result["unlinked"] is True

        expect_failure(
            lambda: h.linear_unlink_issues({"relation_id": ""}, None),
            "relation_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: unlink_issues")


def test_resolve_unresolve_comment(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        if "commentResolve" in query:
            assert variables == {"commentId": "c1"}
            return 200, {"commentResolve": {"success": True, "comment": {"id": "c1", "resolvedAt": "2026-08-23T00:00:00Z"}}}
        if "commentUnresolve" in query:
            assert variables == {"commentId": "c1"}
            return 200, {"commentUnresolve": {"success": True, "comment": {"id": "c1", "resolvedAt": None}}}
        raise AssertionError("unexpected query")

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_resolve_comment({"comment_id": "c1"}, None)
        assert result["comment_id"] == "c1"
        assert result["resolved_at"] == "2026-08-23T00:00:00Z"

        result, _ = h.linear_unresolve_comment({"comment_id": "c1"}, None)
        assert result["comment_id"] == "c1"
        assert result["resolved_at"] == ""

        expect_failure(
            lambda: h.linear_resolve_comment({"comment_id": ""}, None),
            "comment_id must be a non-empty",
        )
        expect_failure(
            lambda: h.linear_unresolve_comment({"comment_id": ""}, None),
            "comment_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: resolve_comment / unresolve_comment")


def test_create_cycle(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "cycleCreate" in query
        assert variables["input"] == {
            "teamId": "t1",
            "startsAt": "2026-09-01T00:00:00Z",
            "endsAt": "2026-09-14T00:00:00Z",
            "name": "Sprint 5",
        }
        return 200, {
            "cycleCreate": {
                "success": True,
                "cycle": {
                    "id": "c1", "number": 5, "name": "Sprint 5",
                    "startsAt": "2026-09-01T00:00:00Z", "endsAt": "2026-09-14T00:00:00Z",
                    "completedAt": None,
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_create_cycle(
            {
                "team_id": "t1",
                "starts_at": "2026-09-01T00:00:00Z",
                "ends_at": "2026-09-14T00:00:00Z",
                "name": "Sprint 5",
            },
            None,
        )
        assert result["cycle_id"] == "c1"
        assert result["number"] == 5
        assert result["name"] == "Sprint 5"

        expect_failure(
            lambda: h.linear_create_cycle({"team_id": "t1", "starts_at": "", "ends_at": "x"}, None),
            "starts_at must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: create_cycle")


def test_update_cycle(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "cycleUpdate" in query
        assert variables["cycleId"] == "c1"
        assert variables["input"] == {"name": "Sprint 5 (renamed)"}
        return 200, {
            "cycleUpdate": {
                "success": True,
                "cycle": {
                    "id": "c1", "number": 5, "name": "Sprint 5 (renamed)",
                    "startsAt": "2026-09-01T00:00:00Z", "endsAt": "2026-09-14T00:00:00Z",
                    "completedAt": None,
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_update_cycle({"cycle_id": "c1", "name": "Sprint 5 (renamed)"}, None)
        assert result["name"] == "Sprint 5 (renamed)"

        expect_failure(
            lambda: h.linear_update_cycle({"cycle_id": "c1"}, None),
            "Supply at least one field",
        )
    finally:
        del h._graphql

    print("PASS: update_cycle")


def main() -> int:
    h = load_handler()
    test_unarchive_issue(h)
    test_update_label(h)
    test_delete_attachment(h)
    test_unlink_issues(h)
    test_resolve_unresolve_comment(h)
    test_create_cycle(h)
    test_update_cycle(h)
    print("V1.7.0 SYMMETRY AND CYCLE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
