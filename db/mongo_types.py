"""
MongoDB / BSON type imports — single place for the whole project.

ObjectId is imported from the bson package that ships inside pymongo.
Do NOT install the standalone 'bson' PyPI package — it is abandoned and
incompatible; if present it shadows pymongo's bson and breaks everything.
"""

from __future__ import annotations

import re

# ObjectId lives in pymongo's bundled bson — no separate install required.
from bson import ObjectId

_OID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def is_valid_object_id(value: str) -> bool:
    """Return True if *value* is a valid 24-hex-char ObjectId string."""
    return bool(_OID_RE.match(value))


__all__ = ["ObjectId", "is_valid_object_id"]
