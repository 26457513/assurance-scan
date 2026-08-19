"""Symmetric encryption for tokens at rest (stdlib only).

Stream cipher built from SHA-256 in counter mode with an HMAC tag. The
threat model is backup/secondary-copy disclosure: the key lives in .env on
the same host as the DB, so full-root compromise of the host is out of
scope by construction. Rotate by changing TOKEN_ENCRYPTION_KEY.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return out[:length]


def encrypt(secret: str, key: str) -> str:
    """plaintext -> nonce.ciphertext.tag, all base64 url-safe."""
    import base64

    nonce = os.urandom(16)
    enc_key = hashlib.sha256(("enc:" + key).encode()).digest()
    mac_key = hashlib.sha256(("mac:" + key).encode()).digest()
    plaintext = secret.encode()
    cipher = bytes(a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext))))
    tag = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    b64 = base64.urlsafe_b64encode
    return f"{b64(nonce).decode()}.{b64(cipher).decode()}.{b64(tag).decode()}"


def decrypt(value: str, key: str) -> str | None:
    """None on any tamper/wrong-key/shape failure — never raises."""
    import base64

    try:
        nonce_b, cipher_b, tag_b = value.split(".")
        nonce = base64.urlsafe_b64decode(nonce_b)
        cipher = base64.urlsafe_b64decode(cipher_b)
        tag = base64.urlsafe_b64decode(tag_b)
        enc_key = hashlib.sha256(("enc:" + key).encode()).digest()
        mac_key = hashlib.sha256(("mac:" + key).encode()).digest()
        expected = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None
        plain = bytes(a ^ b for a, b in zip(cipher, _keystream(enc_key, nonce, len(cipher))))
        return plain.decode()
    except Exception:
        return None
