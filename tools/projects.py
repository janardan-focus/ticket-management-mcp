"""
Project MCP tools — calls the Next.js REST API.

Tools:
  project_list               → GET  /api/projects
  project_get_by_identifier  → GET  /api/project/identifier/{identifier}
  project_create             → POST /api/project/create
  project_update             → POST /api/project/update
"""

from __future__ import annotations

import logging
from typing import Any

from api.client import TMSApiError
from tools._utils import mcp_error, mcp_ok
from tools.context import ToolContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas (JSON Schema format — used by tools/list response)
# ---------------------------------------------------------------------------

PROJECT_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

PROJECT_GET_BY_IDENTIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "identifier": {
            "type": "string",
            "description": "Project short identifier, e.g. 'TIC-1'",
        }
    },
    "required": ["identifier"],
}

PROJECT_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Project display name"},
        "identifier": {
            "type": "string",
            "description": "Custom short identifier (auto-generated if omitted)",
        },
        "memberIds": {
            "type": "array",
            "items": {"type": "string"},
            "description": "User IDs to add as members",
        },
    },
    "required": ["name"],
}

PROJECT_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projectId": {"type": "string", "description": "ID of the project to update"},
        "name": {"type": "string"},
        "memberIds": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Replacement member user ID list",
        },
    },
    "required": ["projectId"],
}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def project_list(args: dict, ctx: ToolContext) -> dict:
    """Return all projects where the authenticated user is a member."""
    try:
        data = await ctx.api.get("/api/projects")
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("project_list failed: %s", exc)
        return mcp_error(f"Error fetching projects: {exc}")
    except Exception as exc:
        logger.exception("project_list unexpected error")
        return mcp_error(f"Error fetching projects: {exc}")


async def project_get_by_identifier(args: dict, ctx: ToolContext) -> dict:
    """Return a single project by its short identifier."""
    identifier: str | None = args.get("identifier")
    if not identifier:
        return mcp_error("Error fetching project: identifier is required")

    try:
        data = await ctx.api.get(f"/api/project/identifier/{identifier}")
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("project_get_by_identifier failed: %s", exc)
        if exc.status_code == 404:
            return mcp_error(f"Project with identifier '{identifier}' not found")
        return mcp_error(f"Error fetching project: {exc}")
    except Exception as exc:
        logger.exception("project_get_by_identifier unexpected error")
        return mcp_error(f"Error fetching project: {exc}")


async def project_create(args: dict, ctx: ToolContext) -> dict:
    """Create a new project."""
    name: str | None = args.get("name")
    if not name or not name.strip():
        return mcp_error("Error creating project: name is required")

    body: dict[str, Any] = {"name": name.strip()}
    if args.get("identifier"):
        body["identifier"] = args["identifier"]
    if args.get("memberIds"):
        body["memberIds"] = args["memberIds"]

    try:
        data = await ctx.api.post("/api/project/create", json=body)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("project_create failed: %s", exc)
        return mcp_error(f"Error creating project: {exc}")
    except Exception as exc:
        logger.exception("project_create unexpected error")
        return mcp_error(f"Error creating project: {exc}")


async def project_update(args: dict, ctx: ToolContext) -> dict:
    """Update an existing project's name and/or memberIds."""
    project_id: str | None = args.get("projectId")
    if not project_id:
        return mcp_error("Error updating project: projectId is required")

    body: dict[str, Any] = {"projectId": project_id}
    has_updates = False

    if "name" in args and args["name"]:
        body["name"] = args["name"].strip()
        has_updates = True
    if "memberIds" in args and isinstance(args["memberIds"], list):
        body["memberIds"] = args["memberIds"]
        has_updates = True

    if not has_updates:
        return mcp_error(
            "Error updating project: no fields to update (provide name or memberIds)"
        )

    try:
        data = await ctx.api.post("/api/project/update", json=body)
        return mcp_ok(data)
    except TMSApiError as exc:
        logger.error("project_update failed: %s", exc)
        if exc.status_code == 404:
            return mcp_error(f"Error updating project: project '{project_id}' not found")
        return mcp_error(f"Error updating project: {exc}")
    except Exception as exc:
        logger.exception("project_update unexpected error")
        return mcp_error(f"Error updating project: {exc}")
