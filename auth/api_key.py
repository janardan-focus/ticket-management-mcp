"""
API key validation — exact Python port of the Next.js validateApiKey action.

Algorithm (mirrors ApiKey Mongoose model):
  1. Accept keys with prefix "tms_" OR legacy 24-char hex keyId format.
  2. For tms_ keys: SHA-256 hash → look up by keyHash in the ApiKey collection.
  3. For legacy keyId: look up by keyId field directly (deprecated, warns).
  4. Verify isActive == True and expiresAt is in the future (if set).
  5. Update lastUsedAt on success.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from db.connection import COLL_API_KEYS, get_db

logger = logging.getLogger(__name__)

_KEY_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)


class ValidationResult(TypedDict):
    valid: bool
    user_id: str | None
    key_id: str | None
    error: str | None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def validate_api_key(api_key: str) -> ValidationResult:
    """Validate a Bearer API key against the MongoDB ApiKey collection."""
    is_key_id_format = bool(_KEY_ID_RE.match(api_key))
    is_tms_format = api_key.startswith("tms_")

    if not is_tms_format and not is_key_id_format:
        logger.error("API key validation failed: invalid format")
        return {
            "valid": False,
            "user_id": None,
            "key_id": None,
            "error": 'Invalid API key format. API key should start with "tms_"',
        }

    db = get_db()
    coll = db[COLL_API_KEYS]

    # ------------------------------------------------------------------
    # Legacy keyId path (deprecated — kept for backward-compat)
    # ------------------------------------------------------------------
    if is_key_id_format and not is_tms_format:
        logger.warning("API key validation: received keyId format (deprecated)")
        doc: dict[str, Any] | None = await coll.find_one(
            {"keyId": api_key, "isActive": True}
        )
        if not doc:
            return _invalid("Invalid API key")

        if _is_expired(doc):
            return _invalid("API key has expired")

        await coll.update_one({"keyId": doc["keyId"]}, {"$set": {"lastUsedAt": _now()}})
        return _ok(doc)

    # ------------------------------------------------------------------
    # Normal tms_ path
    # ------------------------------------------------------------------
    key_hash = _sha256(api_key)
    doc = await coll.find_one({"keyHash": key_hash, "isActive": True})

    if not doc:
        logger.error("API key validation failed: key not found in database")
        return _invalid("Invalid API key")

    if _is_expired(doc):
        return _invalid("API key has expired")

    await coll.update_one({"keyId": doc["keyId"]}, {"$set": {"lastUsedAt": _now()}})
    return _ok(doc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_expired(doc: dict[str, Any]) -> bool:
    expires_at = doc.get("expiresAt")
    if expires_at is None:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    # Make offset-aware if needed
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < _now()


def _ok(doc: dict[str, Any]) -> ValidationResult:
    return {
        "valid": True,
        "user_id": doc.get("userId"),
        "key_id": doc.get("keyId"),
        "error": None,
    }


def _invalid(error: str) -> ValidationResult:
    return {"valid": False, "user_id": None, "key_id": None, "error": error}
