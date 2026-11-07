"""GitHub webhook signatures (X-Hub-Signature-256: sha256=<hex HMAC of the raw body>)."""

from __future__ import annotations

import hashlib
import hmac

PREFIX = "sha256="


def sign(secret: str, body: bytes) -> str:
    return PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith(PREFIX):
        return False
    return hmac.compare_digest(sign(secret, body), header.strip())
