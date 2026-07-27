"""Sign Linear Guard using the local RailCall publisher identity."""

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "module.json"
HANDLER_PATH = ROOT / "handlers" / "handler.py"
SIGNATURE_PATH = ROOT / "module.sig"
PUBLISHER_PATH = (
    Path.home()
    / ".railcall"
    / "marketplace_publisher.json"
)


manifest = json.loads(
    MANIFEST_PATH.read_text(encoding="utf-8")
)
publisher = json.loads(
    PUBLISHER_PATH.read_text(encoding="utf-8")
)

seed_hex = str(publisher.get("seed_hex") or "")
pubkey_hex = str(publisher.get("pubkey_hex") or "")

if len(seed_hex) != 64 or len(pubkey_hex) != 64:
    raise SystemExit(
        "Publisher identity is missing valid Ed25519 key material."
    )

if manifest.get("publisher_pubkey") != pubkey_hex:
    raise SystemExit(
        "module.json publisher_pubkey does not match "
        "the local RailCall publisher identity."
    )

manifest_without_signature = {
    key: value
    for key, value in manifest.items()
    if key != "signature"
}

canonical_manifest = json.dumps(
    manifest_without_signature,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8")

handler_bytes = HANDLER_PATH.read_bytes()

signed_payload = (
    canonical_manifest
    + b"\n"
    + handler_bytes
)

private_key = Ed25519PrivateKey.from_private_bytes(
    bytes.fromhex(seed_hex)
)

signature = private_key.sign(signed_payload)

public_key = Ed25519PublicKey.from_public_bytes(
    bytes.fromhex(pubkey_hex)
)

public_key.verify(signature, signed_payload)

SIGNATURE_PATH.write_text(
    signature.hex() + "\n",
    encoding="utf-8",
)

print("Module signed successfully.")
print("Signature verified locally.")
print(f"Signature bytes: {len(signature)}")
print(f"Publisher fingerprint: {pubkey_hex[:16]}...")
