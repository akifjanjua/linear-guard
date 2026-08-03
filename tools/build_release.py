#!/usr/bin/env python3
"""Build a clean, deterministic, self-describing Linear Guard release archive."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

REQUIRED = [
    "module.json",
    "module.sig",
    "handlers/handler.py",
    "requirements.txt",
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
]

OPTIONAL = [
    "MARKETPLACE_LISTING.md",
    "CONTEST_SUBMISSION.md",
    "EVIDENCE_CHECKLIST.md",
    "PUBLISH_CHECKLIST.md",
    "VIDEO_SCRIPT.md",
    "docs/TROUBLESHOOTING.md",
    "tools/validate_release.py",
    "tools/security_test.py",
    "tools/v045_egress_contract_test.py",
    "tools/smoke_test.py",
    "tools/v15_read_test.py",
    "tools/v15_triage_test.py",
    "tools/v15_plan_sprint_test.py",
    "tools/v15_rebalance_sprint_test.py",
    "tools/release_acceptance_test.py",
    ".github/workflows/linear-guard-tests.yml",
]

FORBIDDEN_NAMES = {
    ".env",
    "credentials.local.json",
    "keys.local.json",
    "approve_token.json",
    "linear-guard-smoke-report.json",
}

FORBIDDEN_SUFFIXES = {
    ".key",
    ".patch",
    ".pyc",
}

CANONICAL_TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".txt",
    ".yml",
    ".yaml",
}

SIGNED_SOURCE_PATHS = {
    "handlers/handler.py",
    "module.json",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def canonical_release_bytes(relative: str, data: bytes) -> bytes:
    """Normalize unsigned text files without changing signed source bytes."""
    if relative == "module.sig":
        token = data.decode("ascii").strip()
        return (token + "\n").encode("ascii")

    suffix = Path(relative).suffix.lower()
    should_normalize = (
        relative == "requirements.txt"
        or (
            relative not in SIGNED_SOURCE_PATHS
            and suffix in CANONICAL_TEXT_SUFFIXES
        )
    )

    if should_normalize:
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        return text.encode("utf-8")

    return data


def write_deterministic_entry(
    archive: zipfile.ZipFile,
    relative: str,
    data: bytes,
) -> None:
    info = zipfile.ZipInfo(relative, date_time=FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        print("FAIL: missing required release files:")
        for path in missing:
            print(f"- {path}")
        return 1

    manifest = json.loads((ROOT / "module.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(ROOT).parts
        if "dist" in relative_parts or "__pycache__" in relative_parts or ".git" in relative_parts:
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            return fail(f"forbidden local or credential file exists: {path.relative_to(ROOT)}")

    DIST.mkdir(exist_ok=True)
    archive_path = DIST / f"linear-guard-v{version}.zip"

    included = REQUIRED + [path for path in OPTIONAL if (ROOT / path).is_file()]
    included = sorted(dict.fromkeys(included))

    file_bytes = {
        relative: canonical_release_bytes(relative, (ROOT / relative).read_bytes())
        for relative in included
    }

    release_manifest = {
        "name": "Linear Guard release archive",
        "module_id": manifest.get("id"),
        "module_version": version,
        "command_count": len(manifest.get("commands") or []),
        "signature_included": True,
        "generated_by": "tools/build_release.py",
        "reproducible_build": True,
        "files": {
            relative: sha256_bytes(data)
            for relative, data in sorted(file_bytes.items())
        },
    }

    manifest_bytes = (
        json.dumps(release_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_STORED,
    ) as archive:
        for relative, data in sorted(file_bytes.items()):
            write_deterministic_entry(archive, relative, data)
        write_deterministic_entry(
            archive,
            "release-manifest.json",
            manifest_bytes,
        )

    print(f"Built: {archive_path}")
    print(f"Module version: {version}")
    print(f"Command count: {release_manifest['command_count']}")
    print("Included files:")
    for relative in sorted(file_bytes):
        print(f"- {relative}")
    print("- release-manifest.json (generated)")
    print("Archive metadata, stored entries, and unsigned text files are canonical and deterministic.")
    print("Credentials, local receipts, patches, caches, and temporary output were excluded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
