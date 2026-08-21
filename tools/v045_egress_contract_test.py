#!/usr/bin/env python3
"""Station v0.45 model-provider egress contract tests for Linear Guard."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "module.json"
HANDLER = ROOT / "handlers" / "handler.py"
IMPLEMENTATION = ROOT / "handlers" / "linear_guard_impl.py"

MODEL_IMPORT_ROOTS = {
    "anthropic",
    "openai",
    "groq",
    "xai",
    "ollama",
    "station_llm",
}

MODEL_SOURCE_PATTERNS = {
    "Anthropic": r"api\.anthropic\.com|\banthropic\b",
    "OpenAI": r"api\.openai\.com|\bopenai\b",
    "Groq": r"api\.groq\.com|\bgroq\b",
    "Gemini": r"generativelanguage\.googleapis\.com|google\.generativeai",
    "xAI": r"api\.x\.ai|\bxai\b",
    "Ollama": r"localhost:11434|127\.0\.0\.1:11434|\bollama\b",
    "RailCall model completion": r"\bstation_llm\b",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = (
    HANDLER.read_text(encoding="utf-8")
    + "\n"
    + IMPLEMENTATION.read_text(encoding="utf-8")
)
    tree = ast.parse(source)

    if "allowed_destinations" not in manifest:
        fail("module.json does not declare allowed_destinations")
    expected_allowed_destinations = [{"provider": "linear", "hosts": ["api.linear.app"]}]
    if manifest["allowed_destinations"] != expected_allowed_destinations:
        fail(
            "Linear Guard must declare allowed_destinations as exactly the Linear "
            f"API host ({expected_allowed_destinations!r}) and no LLM/model-provider entries"
        )

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    forbidden_imports = sorted(imported_roots & MODEL_IMPORT_ROOTS)
    if forbidden_imports:
        fail("model-provider imports found: " + ", ".join(forbidden_imports))

    for label, pattern in MODEL_SOURCE_PATTERNS.items():
        if re.search(pattern, source, flags=re.IGNORECASE):
            fail(f"{label} model-provider marker found in handler.py")

    if "https://api.linear.app/graphql" not in source:
        fail("declared Linear business integration endpoint is missing")
    if 'vault_get("linear")' not in source:
        fail("Linear credential is not resolved through RailCall Vault")

    print("PASS: module.json explicitly declares allowed_destinations as the Linear API host only")
    print("PASS: handler imports no supported model-provider SDK")
    print("PASS: handler contains no supported model-provider host or station_llm marker")
    print("PASS: api.linear.app remains the declared business integration endpoint")
    print("PASS: Linear credentials remain RailCall Vault-only")
    print("STATION v0.45 EGRESS CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
