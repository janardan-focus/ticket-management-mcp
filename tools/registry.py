"""
Tool registry — maps tool names to handlers + JSON Schemas for tools/list.

Adding a new tool:
  1. Write the handler in the relevant module (projects.py, tickets.py, etc.)
  2. Add an entry to _TOOLS below.

Handler signature: async def my_tool(args: dict, ctx: ToolContext) -> dict
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from tools.context import ToolContext  # noqa: F401 — re-exported for callers
from tools.kanban import (
    KANBAN_GET_COLUMN_ORDER_SCHEMA,
    KANBAN_SET_COLUMN_ORDER_SCHEMA,
    kanban_get_column_order,
    kanban_set_column_order,
)
from tools.projects import (
    PROJECT_CREATE_SCHEMA,
    PROJECT_GET_BY_IDENTIFIER_SCHEMA,
    PROJECT_LIST_SCHEMA,
    PROJECT_UPDATE_SCHEMA,
    project_create,
    project_get_by_identifier,
    project_list,
    project_update,
)
from tools.tickets import (
    TICKET_CREATE_SCHEMA,
    TICKET_LIST_SCHEMA,
    TICKET_UPDATE_SCHEMA,
    ticket_create,
    ticket_list,
    ticket_update,
)

logger = logging.getLogger(__name__)


# Type alias for async tool handlers
ToolHandler = Callable[[dict, ToolContext], Coroutine[Any, Any, dict]]


class _ToolEntry:
    __slots__ = ("name", "description", "input_schema", "handler")

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: ToolHandler,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler


_TOOLS: list[_ToolEntry] = [
    # ----- Projects -----
    _ToolEntry(
        name="project_list",
        description="Get all projects for the authenticated user",
        input_schema=PROJECT_LIST_SCHEMA,
        handler=project_list,
    ),
    _ToolEntry(
        name="project_get_by_identifier",
        description="Get a project by its short identifier (e.g. 'TIC-1')",
        input_schema=PROJECT_GET_BY_IDENTIFIER_SCHEMA,
        handler=project_get_by_identifier,
    ),
    _ToolEntry(
        name="project_create",
        description="Create a new project in the ticket management system",
        input_schema=PROJECT_CREATE_SCHEMA,
        handler=project_create,
    ),
    _ToolEntry(
        name="project_update",
        description="Update an existing project (name or members)",
        input_schema=PROJECT_UPDATE_SCHEMA,
        handler=project_update,
    ),
    # ----- Tickets -----
    _ToolEntry(
        name="ticket_list",
        description="List tickets for a project with optional pagination",
        input_schema=TICKET_LIST_SCHEMA,
        handler=ticket_list,
    ),
    _ToolEntry(
        name="ticket_create",
        description="Create a new ticket in a project",
        input_schema=TICKET_CREATE_SCHEMA,
        handler=ticket_create,
    ),
    _ToolEntry(
        name="ticket_update",
        description="Update an existing ticket (name, description, status, priority, assignees)",
        input_schema=TICKET_UPDATE_SCHEMA,
        handler=ticket_update,
    ),
    # ----- Kanban -----
    _ToolEntry(
        name="kanban_get_column_order",
        description="Get the column order for a kanban board grouped by status or priority",
        input_schema=KANBAN_GET_COLUMN_ORDER_SCHEMA,
        handler=kanban_get_column_order,
    ),
    _ToolEntry(
        name="kanban_set_column_order",
        description="Set the column order for a kanban board grouped by status or priority",
        input_schema=KANBAN_SET_COLUMN_ORDER_SCHEMA,
        handler=kanban_set_column_order,
    ),
]

_TOOL_MAP: dict[str, _ToolEntry] = {t.name: t for t in _TOOLS}


class ToolRegistry:
    """Dispatches JSON-RPC tools/list and tools/call."""

    def list_tools(self) -> dict:
        """Return the tools/list response payload."""
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                }
                for t in _TOOLS
            ]
        }

    async def call_tool(self, name: str, args: dict, ctx: ToolContext) -> dict:
        """Dispatch a tool call. Raises ValueError for unknown tools."""
        entry = _TOOL_MAP.get(name)
        if not entry:
            raise ValueError(f"Unknown tool: {name}")
        logger.info("Calling tool '%s'", name)
        return await entry.handler(args, ctx)
