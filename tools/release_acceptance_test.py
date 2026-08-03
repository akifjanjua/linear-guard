#!/usr/bin/env python3
"""Verify the built Linear Guard archive before publication."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ENTRIES = {
    ".github/workflows/linear-guard-tests.yml",
    "CHANGELOG.md",
    "CONTEST_SUBMISSION.md",
    "EVIDENCE_CHECKLIST.md",
    "MARKETPLACE_LISTING.md",
    "PUBLISH_CHECKLIST.md",
    "README.md",
    "SECURITY.md",
    "VIDEO_SCRIPT.md",
    "docs/TROUBLESHOOTING.md",
    "handlers/handler.py",
    "module.json",
    "module.sig",
    "release-manifest.json",
    "requirements.txt",
    "tools/release_acceptance_test.py",
    "tools/security_test.py",
    "tools/v045_egress_contract_test.py",
    "tools/smoke_test.py",
    "tools/v15_plan_sprint_test.py",
    "tools/v15_read_test.py",
    "tools/v15_rebalance_sprint_test.py",
    "tools/v15_triage_test.py",
    "tools/validate_release.py",
}

FORBIDDEN_BASENAMES = {
    ".env",
    "credentials.local.json",
    "keys.local.json",
    "approve_token.json",
    "linear-guard-smoke-report.json",
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


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    source_manifest = json.loads((ROOT / "module.json").read_text(encoding="utf-8"))
    version = str(source_manifest["version"])
    archive_path = ROOT / "dist" / f"linear-guard-v{version}.zip"

    if not archive_path.is_file():
        fail(f"release archive is missing: {archive_path.relative_to(ROOT)}")

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        name_set = set(names)

        if len(names) != len(name_set):
            fail("release archive contains duplicate paths")

        missing = sorted(REQUIRED_ENTRIES - name_set)
        if missing:
            fail(f"release archive is missing entries: {missing}")

        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                fail(f"unsafe archive path: {name}")
            if path.name in FORBIDDEN_BASENAMES:
                fail(f"forbidden file packaged: {name}")
            if any(part in {".git", "__pycache__", "receipts", "dist"} for part in path.parts):
                fail(f"forbidden directory packaged: {name}")
            if path.suffix.lower() in {".key", ".patch", ".pyc"}:
                fail(f"forbidden file type packaged: {name}")

        packaged_module = json.loads(archive.read("module.json"))
        release_manifest = json.loads(archive.read("release-manifest.json"))
        signature = archive.read("module.sig").decode("utf-8").strip()

        if packaged_module.get("id") != "muhammad-akif-janjua/linear-guard":
            fail("packaged module id is incorrect")
        if packaged_module.get("version") != version:
            fail("packaged version differs from source version")
        if len(packaged_module.get("commands") or []) != 16:
            fail("packaged command count is not 16")
        if packaged_module.get("allowed_destinations") != []:
            fail("packaged module does not declare zero model-provider destinations")
        if not re.fullmatch(r"[0-9a-fA-F]{128}", signature):
            fail("packaged module signature is not 128 hexadecimal characters")

        if release_manifest.get("module_id") != packaged_module.get("id"):
            fail("release manifest module id mismatch")
        if release_manifest.get("module_version") != version:
            fail("release manifest version mismatch")
        if release_manifest.get("command_count") != 16:
            fail("release manifest command count mismatch")
        if release_manifest.get("signature_included") is not True:
            fail("release manifest does not confirm signature inclusion")
        if release_manifest.get("reproducible_build") is not True:
            fail("release manifest does not confirm reproducible build settings")

        for info in archive.infolist():
            if info.date_time != (1980, 1, 1, 0, 0, 0):
                fail(f"non-deterministic ZIP timestamp for {info.filename}")

        for name in names:
            suffix = PurePosixPath(name).suffix.lower()
            should_be_canonical = (
                name == "module.sig"
                or name == "requirements.txt"
                or (
                    name not in SIGNED_SOURCE_PATHS
                    and suffix in CANONICAL_TEXT_SUFFIXES
                )
            )
            if should_be_canonical and b"\r" in archive.read(name):
                fail(f"text file is not packaged with canonical LF endings: {name}")

        expected_hashed_entries = name_set - {"release-manifest.json"}
        listed_hashes = release_manifest.get("files") or {}

        if set(listed_hashes) != expected_hashed_entries:
            missing_hashes = sorted(expected_hashed_entries - set(listed_hashes))
            extra_hashes = sorted(set(listed_hashes) - expected_hashed_entries)
            fail(
                "release manifest file set mismatch; "
                f"missing={missing_hashes}, extra={extra_hashes}"
            )

        for name, expected_hash in listed_hashes.items():
            actual_hash = sha256_bytes(archive.read(name))
            if actual_hash != expected_hash:
                fail(f"release hash mismatch for {name}")

    with tempfile.TemporaryDirectory(prefix="linear-guard-release-") as temp_dir:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_dir)
        extracted_root = Path(temp_dir)
        subprocess.run(
            [sys.executable, str(extracted_root / "tools" / "validate_release.py")],
            cwd=extracted_root,
            check=True,
        )

    first_build = archive_path.read_bytes()
    workflow_path = ROOT / ".github" / "workflows" / "linear-guard-tests.yml"
    workflow_original = workflow_path.read_bytes()
    workflow_lf = workflow_original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    try:
        workflow_path.write_bytes(workflow_lf.replace(b"\n", b"\r\n"))
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_release.py")],
            cwd=ROOT,
            check=True,
        )
        second_build = archive_path.read_bytes()
    finally:
        workflow_path.write_bytes(workflow_original)

    if first_build != second_build:
        fail("release archive changes when a Windows CRLF checkout is simulated")

    print("PASS: release archive opens and contains unique safe paths")
    print("PASS: all buyer, reviewer, test, and CI evidence files are included")
    print(f"PASS: packaged module is v{version} with 16 commands, zero model-provider destinations, and a valid signature token")
    print("PASS: generated release manifest matches every packaged file hash")
    print("PASS: ZIP metadata and unsigned text files are canonical across LF/CRLF checkouts")
    print("PASS: extracted-package validation succeeds")
    print("PASS: a simulated Windows CRLF checkout rebuild is byte-for-byte identical")
    print("PASS: credentials, receipts, patches, caches, and local output are absent")
    print("RELEASE ACCEPTANCE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
