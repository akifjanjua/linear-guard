#!/usr/bin/env python3
"""
Safe local smoke test for Linear Guard.

Executes read commands and previews writes. It never approves or executes a
write command.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://127.0.0.1:8799"


class SmokeFailure(RuntimeError):
    pass


def call(endpoint: str, route: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint.rstrip("/") + route,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": endpoint.rstrip("/"),
            "Referer": endpoint.rstrip("/") + "/v2",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"HTTP {exc.code} from {route}: {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"Could not reach RailCall Studio: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"RailCall returned invalid JSON from {route}") from exc


def execute(endpoint: str, command_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return call(
        endpoint,
        "/api/commands/execute",
        {
            "command_id": command_id,
            "inputs": inputs,
            "intent": f"Linear Guard smoke test: {command_id}",
        },
    )


def preview(endpoint: str, command_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return call(
        endpoint,
        "/api/commands/preview",
        {
            "command_id": command_id,
            "inputs": inputs,
            "intent": f"Linear Guard safe preview: {command_id}",
        },
    )


def receipt_output(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = result.get("receipt")
    if not isinstance(receipt, dict):
        raise SmokeFailure("response contains no receipt object")
    output = receipt.get("output")
    if output is None:
        output = {}
    if not isinstance(output, dict):
        raise SmokeFailure("receipt output is not an object")
    return receipt, output


def require_executed(name: str, result: dict[str, Any]) -> dict[str, Any]:
    receipt, output = receipt_output(result)
    status = receipt.get("result_status")
    if status not in {"executed", "ok"}:
        raise SmokeFailure(f"{name} did not execute successfully: {status!r}")
    if output.get("http_status") != 200:
        raise SmokeFailure(f"{name} returned HTTP {output.get('http_status')!r}")
    print(f"PASS read: {name}")
    return output


def load_page(output: dict[str, Any], field: str) -> list[dict[str, Any]]:
    raw = output.get(field) or "[]"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{field} is not complete JSON") from exc
    if not isinstance(value, list):
        raise SmokeFailure(f"{field} is not a list")
    return [item for item in value if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--issue", default="RAI-9")
    parser.add_argument("--search", default="RailCall")
    parser.add_argument(
        "--report",
        default="linear-guard-smoke-report.json",
        help="Path for the redacted JSON report.",
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "endpoint": args.endpoint,
        "reads": {},
        "write_previews": {},
    }

    current = require_executed(
        "linear.get_current_user",
        execute(args.endpoint, "linear.get_current_user", {}),
    )
    report["reads"]["current_user"] = {
        "http_status": current.get("http_status"),
        "name_present": bool(current.get("name")),
        "email_present": bool(current.get("email")),
    }

    teams_output = require_executed(
        "linear.list_teams",
        execute(args.endpoint, "linear.list_teams", {}),
    )
    teams = load_page(teams_output, "teams_json")
    report["reads"]["teams"] = {
        "count": teams_output.get("team_count"),
        "returned": len(teams),
    }

    projects_output = require_executed(
        "linear.list_projects",
        execute(args.endpoint, "linear.list_projects", {}),
    )
    projects = load_page(projects_output, "projects_json")
    report["reads"]["projects"] = {
        "count": projects_output.get("project_count"),
        "returned": len(projects),
    }

    labels_output = require_executed(
        "linear.list_labels",
        execute(args.endpoint, "linear.list_labels", {}),
    )
    labels = load_page(labels_output, "labels_json")
    report["reads"]["labels"] = {
        "count": labels_output.get("label_count"),
        "returned": len(labels),
    }

    all_states: list[dict[str, Any]] = []
    offset = 0
    while True:
        states_output = require_executed(
            f"linear.list_workflow_states offset={offset}",
            execute(
                args.endpoint,
                "linear.list_workflow_states",
                {"offset": offset, "limit": 10},
            ),
        )
        all_states.extend(load_page(states_output, "workflow_states_json"))
        if not states_output.get("has_more"):
            break
        next_offset = states_output.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise SmokeFailure("invalid workflow-state pagination")
        offset = next_offset

    report["reads"]["workflow_states"] = {"returned": len(all_states)}

    issue_output = require_executed(
        "linear.get_issue",
        execute(args.endpoint, "linear.get_issue", {"issue_id": args.issue}),
    )
    report["reads"]["issue"] = {
        "identifier": issue_output.get("identifier"),
        "title_present": bool(issue_output.get("title")),
        "state": issue_output.get("state_name"),
    }

    search_results: list[dict[str, Any]] = []
    offset = 0
    while True:
        search_output = require_executed(
            f"linear.search_issues offset={offset}",
            execute(
                args.endpoint,
                "linear.search_issues",
                {"query": args.search, "offset": offset, "limit": 10},
            ),
        )
        search_results.extend(load_page(search_output, "issues_json"))
        if not search_output.get("has_more"):
            break
        next_offset = search_output.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise SmokeFailure("invalid issue-search pagination")
        offset = next_offset

    report["reads"]["search"] = {"returned": len(search_results)}

    if not teams:
        raise SmokeFailure("cannot preview create_issue because no team was returned")

    write_payloads = {
        "linear.create_issue": {
            "team_id": teams[0].get("id"),
            "title": "Linear Guard safe smoke-test preview",
            "description": "Preview only. This test does not execute the write.",
        },
        "linear.update_issue": {
            "issue_id": args.issue,
            "priority": 2,
        },
        "linear.add_comment": {
            "issue_id": args.issue,
            "body": "Linear Guard safe smoke-test preview. This is not executed.",
        },
    }

    for command_id, inputs in write_payloads.items():
        result = preview(args.endpoint, command_id, inputs)
        # Preview response shapes may differ across Station builds, so record
        # only whether a JSON response was returned and never execute it.
        if not isinstance(result, dict):
            raise SmokeFailure(f"{command_id} preview returned no object")
        report["write_previews"][command_id] = {"response_received": True}
        print(f"PASS preview only: {command_id}")

    report_path = Path(args.report)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("SAFE SMOKE TEST PASSED")
    print("No write command was approved or executed.")
    print(f"Redacted report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
