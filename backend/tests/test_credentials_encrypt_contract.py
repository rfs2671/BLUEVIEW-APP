"""MR.10 — Contract test: frontend SubtleCrypto encrypt path produces
ciphertext that the agent's existing decrypt path correctly recovers.

Why this test is the load-bearing piece of MR.10:
  • Frontend (browser, SubtleCrypto) and agent (Python, cryptography.
    hazmat) must agree on the byte format down to the last byte.
  • A mismatch produces an unhelpful "InvalidTag" or
    "MAC verification failed" exception at decrypt time, which the
    operator only sees AFTER they've encrypted credentials and
    enqueued a filing — too late to recover gracefully.
  • This test pins the format. We can't actually run JS in pytest,
    so we construct the blob byte-for-byte the way the JS module
    (frontend/src/lib/agent_crypto.js) does, then decrypt via the
    agent's production decrypt_credentials path. If any bytes
    diverge, decryption fails and the test fails.

Coverage:
  • Round-trip via the agent's encrypt/decrypt helpers (sanity
    check that the agent can decrypt its own output).
  • Manual byte-layout construction matching agent_crypto.js exactly
    — proves the format the frontend produces is decryptable.
  • Public key fingerprint computation matches between PEM and
    fingerprint helper output.
  • Tampering detection: flipping a single byte in the ciphertext
    causes decrypt to raise (AES-GCM auth tag verification).
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))


def _load_worker_crypto():
    """Load dob_worker/lib/crypto.py directly by file path. We can't
    `from lib import crypto` because backend/lib/ and dob_worker/lib/
    are sibling packages with the same name — Python's package import
    resolves one and the other is shadowed."""
    import importlib.util
    crypto_path = _REPO / "dob_worker" / "lib" / "crypto.py"
    spec = importlib.util.spec_from_file_location(
        "dob_worker_lib_crypto", crypto_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generate_rsa_keypair_pem():
    """Fresh RSA-4096 keypair, PEM-encoded. Returns (private_pem,
    public_pem) as bytes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=4096,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _encrypt_like_frontend(plaintext_dict, public_pem):
    """Build the ciphertext blob byte-for-byte the way
    frontend/src/lib/agent_crypto.js does. Returns base64 string.

    Layout:
      [4-byte BE uint32: wrapped_key length]
      [wrapped_key]
      [12-byte AES-GCM nonce]
      [AES-GCM ciphertext + 16-byte tag]
    Then base64.
    """
    import secrets
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    public_key = serialization.load_pem_public_key(public_pem)

    # Generate fresh AES-256-GCM key + 12-byte nonce. SubtleCrypto's
    # generateKey({name:'AES-GCM', length:256}) produces a 32-byte key;
    # we mirror that.
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)

    # AES-GCM encrypt — output is ciphertext+tag concatenated, matching
    # SubtleCrypto's tagLength:128 behavior.
    aesgcm = AESGCM(aes_key)
    aes_ct_and_tag = aesgcm.encrypt(
        nonce, json.dumps(plaintext_dict).encode("utf-8"), associated_data=None,
    )

    # RSA-OAEP-SHA256 wrap of the AES key.
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
        + aes_ct_and_tag
    )
    return base64.b64encode(blob).decode("ascii")


# ── Round-trip: frontend-style encrypt → agent decrypt ─────────────

class TestFrontendStyleEncryptRoundTrip(unittest.TestCase):

    def test_decrypt_recovers_plaintext(self):
        worker_crypto = _load_worker_crypto()

        private_pem, public_pem = _generate_rsa_keypair_pem()
        plaintext = {
            "username": "filing.rep@gc.com",
            "password": "C0rrect-Horse-Battery-Staple!",
        }

        # Encrypt the way agent_crypto.js does.
        ciphertext_b64 = _encrypt_like_frontend(plaintext, public_pem)

        # Write the private key to a temp file and point the agent's
        # PRIVATE_KEY_PATH at it.
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".key",
        ) as f:
            f.write(private_pem)
            key_path = f.name
        try:
            os.environ["PRIVATE_KEY_PATH"] = key_path
            recovered = worker_crypto.decrypt_credentials(ciphertext_b64)
        finally:
            try:
                os.unlink(key_path)
            except OSError:
                pass

        self.assertEqual(recovered, plaintext)

    def test_tampering_fails_decrypt(self):
        """Flipping a single byte in the ciphertext must cause decrypt
        to raise (AES-GCM auth tag verification). This is the
        tamper-evidence guarantee the worker relies on."""
        worker_crypto = _load_worker_crypto()

        private_pem, public_pem = _generate_rsa_keypair_pem()
        plaintext = {"username": "x", "password": "y"}
        ciphertext_b64 = _encrypt_like_frontend(plaintext, public_pem)

        # Decode, flip a byte in the AES ciphertext region, re-encode.
        blob = bytearray(base64.b64decode(ciphertext_b64))
        # Flip the LAST byte (part of the 16-byte GCM tag).
        blob[-1] = (blob[-1] ^ 0xFF) & 0xFF
        tampered = base64.b64encode(bytes(blob)).decode("ascii")

        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".key",
        ) as f:
            f.write(private_pem)
            key_path = f.name
        try:
            os.environ["PRIVATE_KEY_PATH"] = key_path
            with self.assertRaises(Exception):
                worker_crypto.decrypt_credentials(tampered)
        finally:
            try:
                os.unlink(key_path)
            except OSError:
                pass


# ── Worker's own round-trip (sanity baseline) ──────────────────────

class TestWorkerOwnRoundTrip(unittest.TestCase):
    """If the agent's encrypt + decrypt pair don't round-trip on
    their own, no contract test will pass. Catch that case early
    with a baseline assertion."""

    def test_worker_encrypt_decrypt_round_trip(self):
        worker_crypto = _load_worker_crypto()

        private_pem, public_pem = _generate_rsa_keypair_pem()
        plaintext = {"username": "u", "password": "p"}
        ciphertext_b64 = worker_crypto.encrypt_credentials(plaintext, public_pem)

        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".key",
        ) as f:
            f.write(private_pem)
            key_path = f.name
        try:
            os.environ["PRIVATE_KEY_PATH"] = key_path
            recovered = worker_crypto.decrypt_credentials(ciphertext_b64)
        finally:
            try:
                os.unlink(key_path)
            except OSError:
                pass

        self.assertEqual(recovered, plaintext)


# ── Fingerprint helper ─────────────────────────────────────────────

class TestPublicKeyFingerprint(unittest.TestCase):

    def test_fingerprint_is_64_hex_chars(self):
        import server
        _, public_pem = _generate_rsa_keypair_pem()
        fp = server._compute_public_key_fingerprint(public_pem.decode("utf-8"))
        self.assertEqual(len(fp), 64)
        # Hex only.
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_same_pem_produces_same_fingerprint(self):
        import server
        _, public_pem = _generate_rsa_keypair_pem()
        pem_str = public_pem.decode("utf-8")
        self.assertEqual(
            server._compute_public_key_fingerprint(pem_str),
            server._compute_public_key_fingerprint(pem_str),
        )

    def test_different_pems_produce_different_fingerprints(self):
        import server
        _, public_pem_a = _generate_rsa_keypair_pem()
        _, public_pem_b = _generate_rsa_keypair_pem()
        self.assertNotEqual(
            server._compute_public_key_fingerprint(public_pem_a.decode("utf-8")),
            server._compute_public_key_fingerprint(public_pem_b.decode("utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
