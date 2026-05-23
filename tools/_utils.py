"""
Shared utilities for tool implementations.

- MCP content-envelope builder (matches the Next.js MCP wire format exactly)

Note: MongoDB helpers ($lookup builders, ObjectId/datetime converters,
identifier generators) have been removed — that logic lives in the Next.js
actions layer. The REST API returns JSON-safe strings directly.
"""

from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# MCP content-envelope builder
# ---------------------------------------------------------------------------

def mcp_ok(data: Any) -> dict[str, Any]:
    """
    Wrap data in the MCP content envelope that MCPHTTPClient expects:
      { content: [{ type: 'text', text: '<JSON string>' }] }
    """
    return {
        "content": [{"type": "text", "text": json.dumps(data)}]
    }


def mcp_error(message: str) -> dict[str, Any]:
    """Return an MCP error envelope (isError=True)."""
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
