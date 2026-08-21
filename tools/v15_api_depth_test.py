#!/usr/bin/env python3
"""Unit tests for Linear Guard's v1.5.9 API-depth commands: create_label,
archive_label, archive_issue, and update_comment."""

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


def test_create_label(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append((query, variables, is_write))
        assert is_write is True
        if "issueLabelCreate" in query:
            assert variables["input"]["name"] == "Bug"
            assert variables["input"]["teamId"] == "t1"
            assert variables["input"]["color"] == "#4EA7FC"
            assert variables["input"]["description"] == "Confirmed defects"
            return 200, {
                "issueLabelCreate": {
                    "success": True,
                    "issueLabel": {
                        "id": "l1",
                        "name": "Bug",
                        "color": "#4EA7FC",
                        "description": "Confirmed defects",
                        "isGroup": False,
                        "team": {"id": "t1", "name": "RailCall"},
                    },
                }
            }
        raise AssertionError("unexpected GraphQL query")

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_create_label(
            {
                "name": "Bug",
                "team_id": "t1",
                "color": "#4EA7FC",
                "description": "Confirmed defects",
            },
            None,
        )
        assert result["label_id"] == "l1"
        assert result["name"] == "Bug"
        assert result["color"] == "#4EA7FC"
        assert result["is_group"] is False
        assert result["team_id"] == "t1"
        assert result["team_name"] == "RailCall"
        assert len(calls) == 1

        expect_failure(
            lambda: h.linear_create_label({"name": "   "}, None),
            "name must be a non-empty string",
        )
        expect_failure(
            lambda: h.linear_create_label({"name": "Bug", "color": "blue"}, None),
            "color must be a hex color",
        )
    finally:
        del h._graphql

    print("PASS: create_label")


def test_archive_label(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "issueLabelRetire" in query
        assert variables == {"labelId": "l1"}
        return 200, {
            "issueLabelRetire": {
                "success": True,
                "issueLabel": {
                    "id": "l1",
                    "name": "Bug",
                    "retiredAt": "2026-08-21T22:00:00Z",
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_archive_label({"label_id": "l1"}, None)
        assert result["label_id"] == "l1"
        assert result["name"] == "Bug"
        assert result["retired_at"] == "2026-08-21T22:00:00Z"

        expect_failure(
            lambda: h.linear_archive_label({"label_id": ""}, None),
            "label_id must be a non-empty",
        )
    finally:
        del h._graphql

    print("PASS: archive_label")


def test_archive_issue(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append(variables)
        assert is_write is True
        assert "issueArchive" in query
        return 200, {"issueArchive": {"success": True}}

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_archive_issue({"issue_id": "i1"}, None)
        assert result["issue_id"] == "i1"
        assert result["archived"] is True
        assert result["trashed"] is False
        assert calls[-1] == {"issueId": "i1", "trash": False}

        result, _ = h.linear_archive_issue({"issue_id": "i1", "trash": True}, None)
        assert result["trashed"] is True
        assert calls[-1] == {"issueId": "i1", "trash": True}

        expect_failure(
            lambda: h.linear_archive_issue({"issue_id": ""}, None),
            "issue_id must be a non-empty",
        )
        expect_failure(
            lambda: h.linear_archive_issue({"issue_id": "i1", "trash": "yes"}, None),
            "trash must be a boolean",
        )
    finally:
        del h._graphql

    print("PASS: archive_issue")


def test_update_comment(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "commentUpdate" in query
        assert variables == {"commentId": "c1", "input": {"body": "Updated body"}}
        return 200, {
            "commentUpdate": {
                "success": True,
                "comment": {
                    "id": "c1",
                    "body": "Updated body",
                    "updatedAt": "2026-08-21T22:05:00Z",
                    "editedAt": "2026-08-21T22:05:00Z",
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_update_comment(
            {"comment_id": "c1", "body": "Updated body"}, None
        )
        assert result["comment_id"] == "c1"
        assert result["body_preview"] == "Updated body"
        assert result["updated_at"] == "2026-08-21T22:05:00Z"
        assert result["edited_at"] == "2026-08-21T22:05:00Z"

        expect_failure(
            lambda: h.linear_update_comment({"comment_id": "c1", "body": "  "}, None),
            "body must be a non-empty string",
        )
    finally:
        del h._graphql

    print("PASS: update_comment")


def main() -> int:
    h = load_handler()
    test_create_label(h)
    test_archive_label(h)
    test_archive_issue(h)
    test_update_comment(h)
    print("V1.5.9 API DEPTH TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
