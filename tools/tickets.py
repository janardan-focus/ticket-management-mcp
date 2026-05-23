"""
Ticket MCP tools — calls the Next.js REST API.

Tools:
  ticket_list    → GET  /api/ticket/list?projectId=&page=&pageSize=&sortBy=&sortOrder=
  ticket_create  → POST /api/ticket/create
  ticket_update  → POST /api/ticket/update
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

TICKET_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projectId": {"type": "string", "description": "Project ID to list tickets for"},
        "page": {"type": "integer", "description": "Page number (1-based, default 1)"},
        "pageSize": {"type": "integer", "description": "Items per page (default 100)"},
        "sortBy": {"type": "string", "description": "Field to sort by (default createdAt)"},
        "sortOrder": {"type": "string", "enum": ["asc", "desc"], "description": "Sort direction"},
    },
    "required": ["projectId"],
}

TICKET_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projectId": {"type": "string", "description": "Project ID"},
        "name": {"type": "string", "description": "Ticket title"},
        "description": {"type": "string", "description": "Ticket description"},
        "assigneeIds": {
            "type": "array",
            "items": {"type": "string"},
            "description": "User IDs to assign",
        },
        "statusId": {"type": "string", "description": "Status ID"},
        "priorityId": {"type": "string", "description": "Priority ID"},
    },
    "required": ["projectId", "name"],
}

TICKET_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ticketId": {"type": "string", "description": "Ticket ID to update"},
        "projectId": {"type": "string", "description": "Project ID the ticket belongs to"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "assigneeIds": {"type": "array", "items": {"type": "string"}},
        "statusId": {"type": "string"},
        "priorityId": {"type": "string"},
    },
    "required": ["ticketId", "projectId"],
}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def ticket_list(args: dict, ctx: ToolContext) -> dict:
    """Return paginated tickets for a project."""
    project_id: str | None = args.get("projectId")
    if not project_id:
        return mcp_error("Error listing tickets: projectId is required")

    params: dict[str, Any] = {"projectId": project_id}
    if "page" in args:
        params["page"] = int(args["page"])
    if "pageSize" in args:
        params["pageSize"] = int(args["pageSize"])
    if "sortBy" in args:
        params["sortBy"] = args["sortBy"]
    if "sortOrder" in args:
        params["sortOrder"] = args["sortOrder"]

    try:
        data = await ctx.api.get("/api/ticket/list", params=params)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("ticket_list failed: %s", exc)
        return mcp_error(f"Error listing tickets: {exc}")
    except Exception as exc:
        logger.exception("ticket_list unexpected error")
        return mcp_error(f"Error listing tickets: {exc}")


async def ticket_create(args: dict, ctx: ToolContext) -> dict:
    """Create a new ticket in the specified project."""
    project_id: str | None = args.get("projectId")
    name: str | None = args.get("name")

    if not project_id:
        return mcp_error("Error creating ticket: projectId is required")
    if not name or not name.strip():
        return mcp_error("Error creating ticket: name is required")

    body: dict[str, Any] = {
        "projectId": project_id,
        "name": name.strip(),
    }
    if args.get("description") is not None:
        body["description"] = args["description"]
    if args.get("assigneeIds"):
        body["assigneeIds"] = args["assigneeIds"]
    if args.get("statusId"):
        body["statusId"] = args["statusId"]
    if args.get("priorityId"):
        body["priorityId"] = args["priorityId"]

    try:
        data = await ctx.api.post("/api/ticket/create", json=body)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("ticket_create failed: %s", exc)
        return mcp_error(f"Error creating ticket: {exc}")
    except Exception as exc:
        logger.exception("ticket_create unexpected error")
        return mcp_error(f"Error creating ticket: {exc}")


async def ticket_update(args: dict, ctx: ToolContext) -> dict:
    """Update fields on an existing ticket."""
    ticket_id: str | None = args.get("ticketId")
    project_id: str | None = args.get("projectId")

    if not ticket_id:
        return mcp_error("Error updating ticket: ticketId is required")
    if not project_id:
        return mcp_error("Error updating ticket: projectId is required")

    body: dict[str, Any] = {
        "ticketId": ticket_id,
        "projectId": project_id,
    }
    has_updates = False

    if "name" in args and args["name"]:
        body["name"] = args["name"].strip()
        has_updates = True
    if "description" in args:
        body["description"] = args["description"]
        has_updates = True
    if "assigneeIds" in args and isinstance(args["assigneeIds"], list):
        body["assigneeIds"] = args["assigneeIds"]
        has_updates = True
    if "statusId" in args and args["statusId"]:
        body["statusId"] = args["statusId"]
        has_updates = True
    if "priorityId" in args and args["priorityId"]:
        body["priorityId"] = args["priorityId"]
        has_updates = True

    if not has_updates:
        return mcp_error(
            "Error updating ticket: no fields to update "
            "(provide name, description, assigneeIds, statusId, or priorityId)"
        )

    try:
        data = await ctx.api.post("/api/ticket/update", json=body)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("ticket_update failed: %s", exc)
        if exc.status_code == 404:
            return mcp_error(
                f"Error updating ticket: ticket '{ticket_id}' not found in project '{project_id}'"
            )
        return mcp_error(f"Error updating ticket: {exc}")
    except Exception as exc:
        logger.exception("ticket_update unexpected error")
        return mcp_error(f"Error updating ticket: {exc}")
