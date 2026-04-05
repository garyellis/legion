"""Token generation and hashing helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_token() -> str:
    """Generate a high-entropy opaque token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a raw token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(raw_token: str, token_hash: str) -> bool:
    """Compare a raw token against a stored hash."""
    return hmac.compare_digest(hash_token(raw_token), token_hash)
