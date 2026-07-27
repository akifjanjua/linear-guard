#!/usr/bin/env python3
"""Static release validation for Linear Guard."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "module.json"
HANDLER_PATH = ROOT / "handlers" / "handler.py"

EXPECTED_COMMANDS = {
    "linear.get_current_user": "read",
    "linear.list_teams": "read",
    "linear.list_projects": "read",
    "linear.list_labels": "read",
    "linear.list_workflow_states": "read",
    "linear.search_issues": "read",
    "linear.get_issue": "read",
    "linear.create_issue": "write_requires_approval",
    "linear.update_issue": "write_requires_approval",
    "linear.add_comment": "write_requires_approval",
}

FORBIDDEN_SOURCE_PATTERNS = {
    "disabled TLS verification": r"\bCERT_NONE\b|check_hostname\s*=\s*False",
    "insecure curl option": r"(?<!\w)--insecure\b|(?<!\w)curl\s+-k\b",
    "probable embedded Linear token": r"\b(?:lin_api_|lin_oauth_|pat-)[A-Za-z0-9_-]{12,}\b",
    "probable private key block": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing {MANIFEST_PATH.relative_to(ROOT)}")
    except json.JSONDecodeError as exc:
        fail(f"module.json is invalid JSON: {exc}")


def main() -> int:
    if not HANDLER_PATH.is_file():
        fail("missing handlers/handler.py")

    manifest = load_manifest()
    source = HANDLER_PATH.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        fail(f"handler.py syntax error: {exc}")

    required_keys = {
        "id",
        "name",
        "version",
        "publisher_pubkey",
        "provider",
        "description",
        "commands",
    }
    missing = sorted(required_keys - set(manifest))
    if missing:
        fail(f"module.json is missing keys: {', '.join(missing)}")

    if manifest["id"] != "muhammad-akif-janjua/linear-guard":
        fail("unexpected module id")

    if manifest["provider"] != "linear":
        fail("provider must be linear")

    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest["version"])):
        fail("version must use semantic x.y.z form")

    pubkey = str(manifest["publisher_pubkey"])
    if not re.fullmatch(r"[0-9a-fA-F]{64}", pubkey):
        fail("publisher_pubkey must be 64 hexadecimal characters")

    commands = manifest.get("commands")
    if not isinstance(commands, list):
        fail("commands must be a list")

    command_ids = [command.get("id") for command in commands]
    if len(command_ids) != len(set(command_ids)):
        fail("command ids are not unique")

    if set(command_ids) != set(EXPECTED_COMMANDS):
        missing_ids = sorted(set(EXPECTED_COMMANDS) - set(command_ids))
        extra_ids = sorted(set(command_ids) - set(EXPECTED_COMMANDS))
        fail(f"command set mismatch; missing={missing_ids}, extra={extra_ids}")

    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for command in commands:
        command_id = command["id"]
        expected_mode = EXPECTED_COMMANDS[command_id]

        if command.get("provider") != "linear":
            fail(f"{command_id}: provider must be linear")

        if command.get("mode") != expected_mode:
            fail(f"{command_id}: expected mode {expected_mode!r}")

        if command.get("preview") is not True:
            fail(f"{command_id}: preview must be true")

        if command.get("receipt_required") is not True:
            fail(f"{command_id}: receipt_required must be true")

        function_name = command_id.replace(".", "_")
        if function_name not in functions:
            fail(f"{command_id}: handler function {function_name} not found")

        if expected_mode == "write_requires_approval":
            if command.get("risk") not in {"medium", "high"}:
                fail(f"{command_id}: write risk must be medium or high")

    for label, pattern in FORBIDDEN_SOURCE_PATTERNS.items():
        if re.search(pattern, source):
            fail(f"{label} detected in handler.py")

    if "https://api.linear.app/graphql" not in source:
        fail("Linear GraphQL endpoint not found")

    if "response.get(\"errors\")" not in source:
        fail("GraphQL errors array does not appear to be checked")

    print("PASS: module.json is valid")
    print("PASS: handler.py parses")
    print("PASS: 10 expected commands are present")
    print("PASS: all write commands require approval")
    print("PASS: previews and signed receipts are required")
    print("PASS: no obvious embedded secrets or insecure TLS flags found")
    print(f"PASS: Linear Guard {manifest['version']} is release-ready for signing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
