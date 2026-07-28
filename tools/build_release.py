#!/usr/bin/env python3
"""Build a clean Linear Guard release archive after local signing."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

REQUIRED = [
    "module.json",
    "module.sig",
    "handlers/handler.py",
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "requirements.txt",
]

OPTIONAL = [
    "MARKETPLACE_LISTING.md",
    "CONTEST_SUBMISSION.md",
    "EVIDENCE_CHECKLIST.md",
    "PUBLISH_CHECKLIST.md",
    "docs/TROUBLESHOOTING.md",
    "tools/validate_release.py",
    "tools/smoke_test.py",
    "tools/security_test.py",
]

FORBIDDEN_NAMES = {
    ".env",
    "credentials.local.json",
    "keys.local.json",
    "approve_token.json",
}


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        print("FAIL: missing required release files:")
        for path in missing:
            print(f"- {path}")
        return 1

    manifest = json.loads((ROOT / "module.json").read_text(encoding="utf-8"))
    version = manifest["version"]

    for path in ROOT.rglob("*"):
        if path.is_file() and path.name in FORBIDDEN_NAMES:
            print(f"FAIL: forbidden credential file exists in project tree: {path}")
            return 1

    DIST.mkdir(exist_ok=True)
    archive_path = DIST / f"linear-guard-v{version}.zip"

    files = REQUIRED + [path for path in OPTIONAL if (ROOT / path).is_file()]

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for relative in files:
            archive.write(ROOT / relative, relative)

    print(f"Built: {archive_path}")
    print("Included files:")
    for relative in files:
        print(f"- {relative}")
    print("Credentials, local receipts and temporary test output were excluded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
