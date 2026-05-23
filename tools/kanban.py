"""
Kanban MCP tools — calls the Next.js REST API.

Tools:
  kanban_get_column_order  → GET  /api/kanban/column-order?projectId=&groupType=
  kanban_set_column_order  → POST /api/kanban/column-order
"""

from __future__ import annotations

import logging
from typing import Any

from api.client import TMSApiError
from tools._utils import mcp_error, mcp_ok
from tools.context import ToolContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

KANBAN_GET_COLUMN_ORDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projectId": {"type": "string", "description": "Project ID"},
        "groupType": {
            "type": "string",
            "enum": ["status", "priority"],
            "description": "Board grouping type",
        },
    },
    "required": ["projectId", "groupType"],
}

KANBAN_SET_COLUMN_ORDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projectId": {"type": "string", "description": "Project ID"},
        "groupType": {
            "type": "string",
            "enum": ["status", "priority"],
            "description": "Board grouping type",
        },
        "columns": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Ordered list of column entity IDs",
        },
        "projectIdentifier": {
            "type": "string",
            "description": "Optional project short identifier",
        },
    },
    "required": ["projectId", "groupType", "columns"],
}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def kanban_get_column_order(args: dict, ctx: ToolContext) -> dict:
    """Retrieve the persisted column order for a kanban board."""
    project_id: str | None = args.get("projectId")
    group_type: str | None = args.get("groupType")

    if not project_id:
        return mcp_error("Error getting kanban column order: projectId is required")
    if group_type not in ("status", "priority"):
        return mcp_error("Error getting kanban column order: groupType must be 'status' or 'priority'")

    try:
        data = await ctx.api.get(
            "/api/kanban/column-order",
            params={"projectId": project_id, "groupType": group_type},
        )
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("kanban_get_column_order failed: %s", exc)
        return mcp_error(f"Error getting kanban column order: {exc}")
    except Exception as exc:
        logger.exception("kanban_get_column_order unexpected error")
        return mcp_error(f"Error getting kanban column order: {exc}")


async def kanban_set_column_order(args: dict, ctx: ToolContext) -> dict:
    """Persist the column order for a kanban board."""
    project_id: str | None = args.get("projectId")
    group_type: str | None = args.get("groupType")
    columns: list | None = args.get("columns")

    if not project_id:
        return mcp_error("Error setting kanban column order: projectId is required")
    if group_type not in ("status", "priority"):
        return mcp_error("Error setting kanban column order: groupType must be 'status' or 'priority'")
    if not columns or not isinstance(columns, list) or len(columns) == 0:
        return mcp_error("Error setting kanban column order: columns must be a non-empty array")

    body: dict[str, Any] = {
        "projectId": project_id,
        "groupType": group_type,
        "columns": columns,
    }
    if args.get("projectIdentifier"):
        body["projectIdentifier"] = args["projectIdentifier"]

    try:
        data = await ctx.api.post("/api/kanban/column-order", json=body)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("kanban_set_column_order failed: %s", exc)
        return mcp_error(f"Error setting kanban column order: {exc}")
    except Exception as exc:
        logger.exception("kanban_set_column_order unexpected error")
        return mcp_error(f"Error setting kanban column order: {exc}")
