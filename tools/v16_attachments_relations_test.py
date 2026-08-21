#!/usr/bin/env python3
"""Unit tests for Linear Guard's v1.6.0 attachment and issue-relation
commands: create_attachment and link_issues."""

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


def test_create_attachment(h):
    def fake_graphql(query, variables=None, *, is_write=False):
        assert is_write is True
        assert "attachmentCreate" in query
        assert variables["input"] == {
            "issueId": "i1",
            "title": "Design doc",
            "url": "https://example.com/doc",
            "subtitle": "Figma",
        }
        return 200, {
            "attachmentCreate": {
                "success": True,
                "attachment": {
                    "id": "a1",
                    "title": "Design doc",
                    "subtitle": "Figma",
                    "url": "https://example.com/doc",
                    "createdAt": "2026-08-21T23:00:00Z",
                    "issue": {"id": "i1", "identifier": "RAI-9"},
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_create_attachment(
            {
                "issue_id": "i1",
                "title": "Design doc",
                "url": "https://example.com/doc",
                "subtitle": "Figma",
            },
            None,
        )
        assert result["attachment_id"] == "a1"
        assert result["title"] == "Design doc"
        assert result["url"] == "https://example.com/doc"
        assert result["issue_id"] == "i1"
        assert result["issue_identifier"] == "RAI-9"

        expect_failure(
            lambda: h.linear_create_attachment(
                {"issue_id": "i1", "title": "Doc", "url": "ftp://example.com"}, None
            ),
            "url must start with http",
        )
        expect_failure(
            lambda: h.linear_create_attachment(
                {"issue_id": "i1", "title": "  ", "url": "https://example.com"}, None
            ),
            "title must be a non-empty string",
        )
    finally:
        del h._graphql

    print("PASS: create_attachment")


def test_link_issues(h):
    calls = []

    def fake_graphql(query, variables=None, *, is_write=False):
        calls.append(variables)
        assert is_write is True
        assert "issueRelationCreate" in query
        return 200, {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {
                    "id": "r1",
                    "type": "blocks",
                    "createdAt": "2026-08-21T23:05:00Z",
                    "issue": {"id": "i1", "identifier": "RAI-9"},
                    "relatedIssue": {"id": "i2", "identifier": "RAI-10"},
                },
            }
        }

    h._graphql = fake_graphql
    try:
        result, _ = h.linear_link_issues(
            {"issue_id": "i1", "related_issue_id": "i2", "type": "blocks"}, None
        )
        assert result["relation_id"] == "r1"
        assert result["type"] == "blocks"
        assert result["issue_id"] == "i1"
        assert result["issue_identifier"] == "RAI-9"
        assert result["related_issue_id"] == "i2"
        assert result["related_issue_identifier"] == "RAI-10"
        assert calls[-1] == {
            "input": {"issueId": "i1", "relatedIssueId": "i2", "type": "blocks"}
        }

        for relation_type in ("duplicate", "related", "similar"):
            h.linear_link_issues(
                {"issue_id": "i1", "related_issue_id": "i2", "type": relation_type},
                None,
            )
            assert calls[-1]["input"]["type"] == relation_type

        expect_failure(
            lambda: h.linear_link_issues(
                {"issue_id": "i1", "related_issue_id": "i2", "type": "clones"}, None
            ),
            "type must be one of",
        )
        expect_failure(
            lambda: h.linear_link_issues(
                {"issue_id": "i1", "related_issue_id": "i1", "type": "blocks"}, None
            ),
            "must refer to different issues",
        )
    finally:
        del h._graphql

    print("PASS: link_issues")


def main() -> int:
    h = load_handler()
    test_create_attachment(h)
    test_link_issues(h)
    print("V1.6.0 ATTACHMENTS AND ISSUE RELATIONS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
