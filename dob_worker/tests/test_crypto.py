"""Hybrid encrypt/decrypt round-trip + tampering tests."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DOB_WORKER = _HERE.parent
sys.path.insert(0, str(_DOB_WORKER))


def _generate_test_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


class TestCryptoRoundtrip(unittest.TestCase):

    def setUp(self):
        self.priv_pem, self.pub_pem = _generate_test_keypair()
        self.tmpdir = tempfile.mkdtemp()
        self.priv_path = Path(self.tmpdir) / "agent.key"
        self.priv_path.write_bytes(self.priv_pem)
        os.environ["PRIVATE_KEY_PATH"] = str(self.priv_path)

    def tearDown(self):
        os.environ.pop("PRIVATE_KEY_PATH", None)
        # tempfile.mkdtemp leaves the dir; not worth cleaning per-test

    def test_encrypt_decrypt_roundtrip(self):
        from lib.crypto import encrypt_credentials, decrypt_credentials
        plaintext = {"username": "rfsadmin", "password": "S3cret!#"}
        ct = encrypt_credentials(plaintext, self.pub_pem)
        decrypted = decrypt_credentials(ct)
        self.assertEqual(decrypted, plaintext)

    def test_wrong_key_fails(self):
        from lib.crypto import encrypt_credentials, decrypt_credentials
        # Encrypt with one keypair, swap the private key on disk
        # to a different one before decrypt → must fail.
        ct = encrypt_credentials({"username": "u", "password": "p"}, self.pub_pem)
        other_priv, _ = _generate_test_keypair()
        self.priv_path.write_bytes(other_priv)
        with self.assertRaises(Exception):
            decrypt_credentials(ct)

    def test_tampered_ciphertext_fails(self):
        from lib.crypto import encrypt_credentials, decrypt_credentials
        ct = encrypt_credentials({"username": "u", "password": "p"}, self.pub_pem)
        # Flip a byte near the end (in the GCM tag region) — GCM
        # auth must reject.
        raw = bytearray(base64.b64decode(ct))
        raw[-1] ^= 0xFF
        tampered = base64.b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(Exception):
            decrypt_credentials(tampered)


if __name__ == "__main__":
    unittest.main()
