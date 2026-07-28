#!/usr/bin/env python3
"""Focused offline security tests for Linear Guard v1.4.0."""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

# Synthetic fixture assembled in pieces to avoid secret-scanner false positives.
TEST_LINEAR_TOKEN = "".join(("lin", "_api_", "testfixture1234567"))


ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "handlers" / "handler.py"


def load_handler():
    spec = importlib.util.spec_from_file_location("linear_guard_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_runtime_error(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        if contains.lower() not in str(exc).lower():
            raise AssertionError(f"expected {contains!r} in {exc!r}") from exc
    else:
        raise AssertionError("expected RuntimeError")


def main() -> int:
    source = HANDLER.read_text(encoding="utf-8")
    forbidden = [
        "credentials.local.json",
        "subprocess",
        "shutil",
        "os.environ",
        "_post_graphql_with_curl",
        "_curl_config_quote",
        "curl --",
    ]
    for text in forbidden:
        assert text not in source, f"forbidden source text remains: {text}"
    print("PASS: no credential-file, environment, curl, or subprocess fallback")

    h = load_handler()

    h.__rc_helpers__ = {"vault_get": lambda provider: TEST_LINEAR_TOKEN}
    assert h._load_api_key() == TEST_LINEAR_TOKEN
    assert h._extract_api_key({"fields": {"LINEAR_API_KEY": " key "}}) == "key"
    print("PASS: vault_get supplies string and documented field shapes")

    h.__rc_helpers__ = {"vault_get": lambda provider: None}
    expect_runtime_error(h._load_api_key, "not configured")
    h.__rc_helpers__ = {}
    expect_runtime_error(h._load_api_key, "vault_get")
    print("PASS: missing vault configuration fails clearly")

    secret = TEST_LINEAR_TOKEN
    redacted = h._redact(
        f"Authorization: {secret}; LINEAR_API_KEY={secret}",
        secret,
    )
    assert secret not in redacted
    assert "[REDACTED]" in redacted
    print("PASS: active secret redaction")

    calls = {"count": 0}
    original_urlopen = h.urllib.request.urlopen

    def failing_urlopen(*args, **kwargs):
        calls["count"] += 1
        raise urllib.error.URLError("timed out")

    h.urllib.request.urlopen = failing_urlopen
    try:
        try:
            h._post_graphql(secret, b"{}", is_write=True)
        except RuntimeError as exc:
            assert "outcome is unknown" in str(exc)
            assert exc.__cause__ is None
        else:
            raise AssertionError("expected unknown write outcome")
        assert calls["count"] == 1, "write transport was retried"
    finally:
        h.urllib.request.urlopen = original_urlopen
    print("PASS: mutation transport makes one attempt and hides low-level cause")

    h.__rc_helpers__ = {"vault_get": lambda provider: secret}
    original_post = h._post_graphql
    h._post_graphql = lambda *a, **k: (
        200,
        json.dumps({"errors": [{"message": f"bad {secret}"}]}).encode(),
    )
    try:
        try:
            h._graphql("mutation X { x }", is_write=True)
        except RuntimeError as exc:
            assert secret not in str(exc)
            assert "GraphQL returned errors" in str(exc)
        else:
            raise AssertionError("expected GraphQL mutation failure")
    finally:
        h._post_graphql = original_post
    print("PASS: HTTP-200 GraphQL mutation errors fail and redact")

    expect_runtime_error(
        lambda: h.linear_create_issue(
            {"team_id": "t", "title": "x" * 256},
            None,
        ),
        "255",
    )
    expect_runtime_error(
        lambda: h.linear_update_issue({"issue_id": "RAI-9"}, None),
        "at least one field",
    )
    print("PASS: important write inputs fail before network access")

    context = h._build_tls_context()
    assert context.verify_mode != 0 and context.check_hostname is True
    print("PASS: certifi-backed TLS verification is enabled")

    print("SECURITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
