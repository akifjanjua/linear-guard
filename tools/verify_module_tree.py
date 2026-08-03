#!/usr/bin/env python3
"""Verify a RailCall v2 module tree signature without trusting module.sig text alone."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


IGNORED_DIRS = {".git", "dist", "__pycache__", ".pytest_cache"}
IGNORED_FILES = {"module.sig"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def canonical_manifest(manifest: dict) -> bytes:
    body = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def signed_tree(root: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue
        relative = relative_path.as_posix()
        if relative in IGNORED_FILES:
            continue
        files.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    files.sort(key=lambda item: item[0])
    return files


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    manifest_path = root / "module.json"
    signature_path = root / "module.sig"
    handler_path = root / "handlers" / "handler.py"

    for path in (manifest_path, signature_path, handler_path):
        if not path.is_file():
            fail(f"missing required module file: {path.relative_to(root)}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(manifest.get("manifest_version") or 1) < 2:
        fail("module is not using RailCall v2 tree signing")

    pubkey_hex = str(manifest.get("publisher_pubkey") or "").strip()
    signature_hex = signature_path.read_text(encoding="ascii").strip()
    if len(pubkey_hex) != 64:
        fail("publisher_pubkey must contain 64 hexadecimal characters")
    if len(signature_hex) != 128:
        fail("module.sig must contain 128 hexadecimal characters")

    tree = signed_tree(root)
    tree_manifest = "".join(
        f"{relative}\t{digest}\n"
        for relative, digest in tree
    ).encode("utf-8")
    payload = canonical_manifest(manifest) + b"\n" + tree_manifest

    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        public_key.verify(bytes.fromhex(signature_hex), payload)
    except (ValueError, InvalidSignature) as exc:
        fail(f"RailCall v2 module tree signature is invalid: {type(exc).__name__}")

    print("PASS: RailCall v2 module tree signature is valid")
    print(f"Module ID: {manifest.get('id')}")
    print(f"Version: {manifest.get('version')}")
    print(f"Commands: {len(manifest.get('commands') or [])}")
    print(f"Signed tree files: {len(tree)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
