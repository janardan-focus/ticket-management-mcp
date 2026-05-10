"""
Kanban MCP tools — direct MongoDB access via Motor.

Tools:
  kanban_get_column_order  → retrieve column order for a board
  kanban_set_column_order  → upsert column order for a board

Identifier format (mirrors getKanbanColumnOrderKey in utils.ts):
  {userId}_{projectId}_{groupType}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db.connection import COLL_KANBAN, get_db
from tools._utils import mcp_error, mcp_ok

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
# Helpers
# ---------------------------------------------------------------------------

def _kanban_key(user_id: str, project_id: str, group_type: str) -> str:
    """Mirror getKanbanColumnOrderKey() from utils.ts."""
    return f"{user_id}_{project_id}_{group_type}"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def kanban_get_column_order(args: dict, user_id: str) -> dict:
    """Retrieve the persisted column order for a kanban board."""
    project_id: str | None = args.get("projectId")
    group_type: str | None = args.get("groupType")

    if not project_id:
        return mcp_error("Error getting kanban column order: projectId is required")
    if group_type not in ("status", "priority"):
        return mcp_error("Error getting kanban column order: groupType must be 'status' or 'priority'")

    try:
        db = get_db()
        coll = db[COLL_KANBAN]

        identifier = _kanban_key(user_id, project_id, group_type)
        doc = await coll.find_one({"identifier": identifier})

        if not doc:
            return mcp_ok({
                "projectId": project_id,
                "groupType": group_type,
                "columns": [],
                "message": "No column order saved yet for this board",
            })

        return mcp_ok({
            "projectId": project_id,
            "groupType": group_type,
            "columns": doc.get("entityOrder", []),
            "identifier": identifier,
        })
    except Exception as exc:
        logger.exception("kanban_get_column_order failed")
        return mcp_error(f"Error getting kanban column order: {exc}")


async def kanban_set_column_order(args: dict, user_id: str) -> dict:
    """Persist the column order for a kanban board (upsert)."""
    project_id: str | None = args.get("projectId")
    group_type: str | None = args.get("groupType")
    columns: list | None = args.get("columns")

    if not project_id:
        return mcp_error("Error setting kanban column order: projectId is required")
    if group_type not in ("status", "priority"):
        return mcp_error("Error setting kanban column order: groupType must be 'status' or 'priority'")
    if not columns or not isinstance(columns, list) or len(columns) == 0:
        return mcp_error("Error setting kanban column order: columns must be a non-empty array")

    try:
        db = get_db()
        coll = db[COLL_KANBAN]

        identifier = _kanban_key(user_id, project_id, group_type)
        now = datetime.now(tz=timezone.utc)

        await coll.update_one(
            {"identifier": identifier},
            {
                "$set": {
                    "entityOrder": columns,
                    "updatedAt": now,
                },
                "$setOnInsert": {
                    "createdAt": now,
                },
            },
            upsert=True,
        )

        return mcp_ok({
            "projectId": project_id,
            "groupType": group_type,
            "columns": columns,
            "identifier": identifier,
            "message": "Column order updated successfully",
        })
    except Exception as exc:
        logger.exception("kanban_set_column_order failed")
        return mcp_error(f"Error setting kanban column order: {exc}")
