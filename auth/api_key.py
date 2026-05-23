"""
API key utilities — stub after REST migration.

The full SHA-256 DB validation has been removed. Auth is now performed by
the Next.js REST API on every request (Bearer token forwarded verbatim).

Only a cheap local format check remains so obviously-bad keys fail fast
without a network round-trip. Real validation is delegated to the API.
"""

from __future__ import annotations


def is_valid_token_format(token: str) -> bool:
    """
    Return True if the token looks like a valid TMS API key.

    Accepts:
      - tms_<anything>   (current format)
      - 24-char hex      (legacy keyId format, deprecated)
    """
    return token.startswith("tms_") or (len(token) == 24 and token.isalnum())
