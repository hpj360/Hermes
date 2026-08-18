"""At-rest symmetric encryption for platform credentials (stdlib-only).

Because the project intentionally avoids third-party runtime dependencies
(``cryptography`` is not installed), this module provides an authenticated
stream cipher built from the stdlib:

* **Key derivation** — PBKDF2-HMAC-SHA256 (200k iterations) from
  ``HERMES_SECRET_KEY`` + a random 16-byte salt.
* **Cipher** — CTR-mode keystream where the keystream is repeated
  HMAC-SHA256(key, counter) blocks XORed with the plaintext.
* **Integrity** — HMAC-SHA256 over the ciphertext, compared in constant time.

Honesty note: this is at-rest **obfuscation with integrity**, not AES-grade
encryption. For a local single-user tool whose real exposure is mitigated by
(a) never returning tokens over the API and (b) binding loopback, this is a
reasonable defense-in-depth layer. Set ``HERMES_SECRET_KEY`` in ``.env``;
when it is unset, encryption is disabled and values pass through unchanged
(dev mode).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

__all__ = ["encrypt", "decrypt", "get_secret"]

_SALT_LEN = 16
_MAC_LEN = 32
_ITERATIONS = 200_000


def get_secret() -> str | None:
    """Return ``HERMES_SECRET_KEY`` from settings, or None when unset."""
    from hermes.config import get_settings

    secret = getattr(get_settings(), "hermes_secret_key", None)
    return secret if secret else None


def _derive_keys(secret: str, salt: bytes) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, _ITERATIONS, dklen=64)
    return dk[:32], dk[32:]  # enc_key, mac_key


def _keystream(key: bytes, length: int) -> bytes:
    stream = b""
    counter = 0
    while len(stream) < length:
        stream += hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return stream[:length]


def encrypt(secret: str, plaintext: str) -> str:
    """Encrypt *plaintext*; returns base64 ``salt || ciphertext || mac``."""
    salt = os.urandom(_SALT_LEN)
    enc_key, mac_key = _derive_keys(secret, salt)
    data = plaintext.encode("utf-8")
    stream = _keystream(enc_key, len(data))
    ct = bytes(a ^ b for a, b in zip(data, stream))
    mac = hmac.new(mac_key, ct, hashlib.sha256).digest()
    return base64.b64encode(salt + ct + mac).decode("ascii")


def decrypt(secret: str, blob: str) -> str | None:
    """Decrypt a blob produced by :func:`encrypt`; None on any failure.

    Returns None (not raises) so callers can fall back to legacy plaintext.
    """
    try:
        raw = base64.b64decode(blob)
        if len(raw) < _SALT_LEN + _MAC_LEN:
            return None
        salt, ct, mac = raw[:_SALT_LEN], raw[_SALT_LEN:-_MAC_LEN], raw[-_MAC_LEN:]
        enc_key, mac_key = _derive_keys(secret, salt)
        expected = hmac.new(mac_key, ct, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, mac):
            return None
        stream = _keystream(enc_key, len(ct))
        return bytes(a ^ b for a, b in zip(ct, stream)).decode("utf-8")
    except Exception:  # noqa: BLE001 - defensive: corrupt/legacy blobs
        return None
