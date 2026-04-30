"""Hybrid-encryption decrypt path for GC-provided DOB NOW credentials.

Scheme: RSA-OAEP (SHA-256, 4096-bit) wraps a per-payload AES-256-GCM
key. AES-GCM encrypts the actual {username, password} JSON. The
ciphertext layout is:

    [4-byte big-endian length of RSA-wrapped AES key][RSA-wrapped key]
    [12-byte GCM nonce][GCM ciphertext][16-byte GCM tag]

Length-prefixing the RSA key avoids guessing the key size at decrypt
time (4096-bit RSA-OAEP-SHA256 produces a 512-byte wrapped key, but
hard-coding that constant is brittle if we ever rotate to a larger
modulus).

The whole concatenation is base64-encoded for transport in JSON.

This module is decrypt-only — the matching encrypt path lives
cloud-side and ships with MR.10's onboarding UI (the operator gives
LeveLog the public key; cloud encrypts; ciphertext stored in Mongo;
shipped to worker in the job payload; decrypted here).

Threat model:
  - Cloud DB compromise alone reveals only ciphertext (useless).
  - Worker laptop compromise alone reveals only the private key
    (useful only if the attacker also has cloud DB access).
  - Both together = breach. v2 hardens via OS-keychain integration;
    v1 relies on filesystem + chmod 0400 + bind-mount path outside
    the repo tree.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
from typing import Dict


logger = logging.getLogger(__name__)


_RSA_KEY_LENGTH_PREFIX_BYTES = 4
_GCM_NONCE_BYTES = 12
_GCM_TAG_BYTES = 16


def _load_private_key():
    """Load the agent's private key from PRIVATE_KEY_PATH.

    Imports cryptography lazily so this module loads cleanly in
    static analysis / on machines without the dep installed
    (the worker container has it; tests that mock decrypt don't
    need it)."""
    from cryptography.hazmat.primitives import serialization

    path = os.environ.get("PRIVATE_KEY_PATH", "/keys/agent.key")
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def agent_key_fingerprint() -> str:
    """MR.11 — return SHA-256 hex digest of the DER-encoded public-key
    half of the agent's local private key, matching the fingerprint
    convention the backend stores on FilingRepCredential.public_key_
    fingerprint at encrypt time.

    Used by dob_now_filing handler to verify a credential ciphertext
    in a queue payload was encrypted against THIS agent's keypair
    BEFORE attempting decrypt. Mismatch = silent fail at decrypt
    time (or worse, decrypt with garbage); the explicit check up
    front gives the operator a clean `credential_key_mismatch`
    error instead.

    Same convention used in:
      - backend/server.py:_compute_public_key_fingerprint (MR.10
        registers via this when the operator POSTs the public key)
      - frontend/src/lib/agent_crypto.js:publicKeyFingerprint
        (encryption-side reference fingerprint for verification UI)
    """
    import hashlib
    from cryptography.hazmat.primitives import serialization

    private_key = _load_private_key()
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def decrypt_credentials(ciphertext_b64: str) -> Dict[str, str]:
    """Decrypt a hybrid-encrypted credentials blob and return the
    {username, password} dict. Raises on tampering, wrong key, or
    malformed input."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    blob = base64.b64decode(ciphertext_b64)
    if len(blob) < _RSA_KEY_LENGTH_PREFIX_BYTES + _GCM_NONCE_BYTES + _GCM_TAG_BYTES:
        raise ValueError("ciphertext too short")

    rsa_key_len = struct.unpack(">I", blob[:_RSA_KEY_LENGTH_PREFIX_BYTES])[0]
    cursor = _RSA_KEY_LENGTH_PREFIX_BYTES
    wrapped_key = blob[cursor:cursor + rsa_key_len]
    cursor += rsa_key_len
    nonce = blob[cursor:cursor + _GCM_NONCE_BYTES]
    cursor += _GCM_NONCE_BYTES
    aes_ct_and_tag = blob[cursor:]  # last bytes include the tag

    private_key = _load_private_key()
    aes_key = private_key.decrypt(
        wrapped_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(nonce, aes_ct_and_tag, associated_data=None)
    return json.loads(plaintext.decode("utf-8"))


# ── Encrypt helper exposed for tests + generate_keypair smoke ──────
# The cloud-side encrypt path lives in MR.10. This function exists
# in the worker module so the test suite can round-trip without
# having to import a cloud-only encrypt module.

def encrypt_credentials(
    plaintext: Dict[str, str],
    public_key_pem: bytes,
) -> str:
    """Round-trip helper for tests. NOT used by production worker
    (worker only decrypts). Cloud-side production encrypt path
    will mirror this implementation."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import secrets

    public_key = serialization.load_pem_public_key(public_key_pem)
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(_GCM_NONCE_BYTES)
    aesgcm = AESGCM(aes_key)
    aes_ct = aesgcm.encrypt(
        nonce, json.dumps(plaintext).encode("utf-8"), associated_data=None,
    )

    wrapped_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    blob = (
        struct.pack(">I", len(wrapped_key))
        + wrapped_key
        + nonce
        + aes_ct
    )
    return base64.b64encode(blob).decode("ascii")
