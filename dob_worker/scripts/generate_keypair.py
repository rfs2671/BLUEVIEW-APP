"""Generate the dob_worker's RSA-4096 keypair.

Operator runs this ONCE during agent setup. Output:
  - Private key written to PRIVATE_KEY_PATH (default /keys/agent.key),
    PEM format, chmod 0400.
  - Public key printed to stdout in PEM format. Operator pastes the
    public key into the backend admin UI (endpoint shipped in MR.10);
    the cloud uses it to encrypt GC-provided DOB NOW credentials.

Run via:
    docker compose run --rm dob_worker python scripts/generate_keypair.py

Or locally (requires `cryptography` installed):
    PRIVATE_KEY_PATH=~/.levelog/agent-keys/agent.key \\
      python scripts/generate_keypair.py

Idempotency: refuses to overwrite an existing key file. Operator
must explicitly delete the old key (and re-encrypt every GC's
credentials cloud-side) to rotate.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def main() -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    path_str = os.environ.get("PRIVATE_KEY_PATH", "/keys/agent.key")
    path = Path(path_str).expanduser()

    if path.exists():
        print(
            f"ERROR: {path} already exists. Refusing to overwrite. "
            f"Delete it explicitly to rotate.",
            file=sys.stderr,
        )
        return 2

    path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating RSA-4096 keypair at {path}...", file=sys.stderr)
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    pem_priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem_priv)
    try:
        os.chmod(path, stat.S_IRUSR)  # 0400
    except (OSError, NotImplementedError):
        # Windows hosts may not support chmod fully; surface a hint.
        print(
            f"WARNING: chmod 0400 on {path} may not have applied "
            f"(Windows hosts handle permissions differently). Verify "
            f"the bind-mount source is in a user-only directory.",
            file=sys.stderr,
        )

    pem_pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    print(
        f"Private key written: {path} (chmod 0400, do NOT commit)",
        file=sys.stderr,
    )
    print(
        "Paste the following public key into the backend admin UI "
        "(MR.10 onboarding flow):",
        file=sys.stderr,
    )
    print()
    sys.stdout.write(pem_pub.decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
