"""
Shared utilities for tool implementations.

- ObjectId / datetime → JSON-safe conversion
- MCP content-envelope builder (matches the Next.js MCP wire format exactly)
- $lookup pipeline fragments for Mongoose-style populate
"""

from __future__ import annotations

import json
import random
import re
import string
from datetime import datetime
from typing import Any

from pymongo import ReturnDocument  # noqa: F401 — re-exported for convenience

from db.mongo_types import ObjectId


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------

class _MongoEncoder(json.JSONEncoder):
    """Converts ObjectId and datetime to JSON-serialisable types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def to_json(obj: Any) -> str:
    return json.dumps(obj, cls=_MongoEncoder)


def _stringify(obj: Any) -> Any:
    """Recursively convert ObjectId/datetime in a dict/list to strings."""
    if isinstance(obj, dict):
        return {k: _stringify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify(i) for i in obj]
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# MCP content-envelope builder
# ---------------------------------------------------------------------------

def mcp_ok(data: Any) -> dict[str, Any]:
    """
    Wrap data in the MCP content envelope that MCPHTTPClient expects:
      { content: [{ type: 'text', text: '<JSON string>' }] }
    """
    return {
        "content": [{"type": "text", "text": to_json(_stringify(data))}]
    }


def mcp_error(message: str) -> dict[str, Any]:
    """Return an MCP error envelope (isError=True)."""
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# ---------------------------------------------------------------------------
# $lookup pipeline fragments (Mongoose populate equivalents)
# ---------------------------------------------------------------------------

# Fields projected for each related collection
_USER_PROJECT = {
    "fullname": 1, "firstname": 1, "lastname": 1,
    "userId": 1, "image": 1, "email": 1, "_id": 0,
}
_PROJECT_BASE_PROJECT = {"projectId": 1, "name": 1, "identifier": 1, "_id": 0}
_STATUS_PROJECT = {
    "statusId": 1, "name": 1, "isDefault": 1,
    "icon": 1, "color": 1, "isDone": 1, "_id": 0,
}
_PRIORITY_PROJECT = {
    "priorityId": 1, "name": 1, "isDefault": 1,
    "icon": 1, "color": 1, "_id": 0,
}


def lookup_users(local_field: str, as_field: str, is_array: bool = False) -> list[dict]:
    """$lookup + $unwind (for single-ref fields) or keep array."""
    stages: list[dict] = [
        {
            "$lookup": {
                "from": "appusers",
                "localField": local_field,
                "foreignField": "_id",
                "as": as_field,
                "pipeline": [{"$project": _USER_PROJECT}],
            }
        }
    ]
    if not is_array:
        # Flatten single-element array to object
        stages.append(
            {"$unwind": {"path": f"${as_field}", "preserveNullAndEmptyArrays": True}}
        )
    return stages


def lookup_project(local_field: str = "projectId", as_field: str = "project") -> list[dict]:
    return [
        {
            "$lookup": {
                "from": "projects",
                "localField": local_field,
                "foreignField": "_id",
                "as": as_field,
                "pipeline": [{"$project": _PROJECT_BASE_PROJECT}],
            }
        },
        {"$unwind": {"path": f"${as_field}", "preserveNullAndEmptyArrays": True}},
    ]


def lookup_status(local_field: str = "statusId", as_field: str = "status") -> list[dict]:
    return [
        {
            "$lookup": {
                "from": "statuses",
                "localField": local_field,
                "foreignField": "_id",
                "as": as_field,
                "pipeline": [{"$project": _STATUS_PROJECT}],
            }
        },
        {"$unwind": {"path": f"${as_field}", "preserveNullAndEmptyArrays": True}},
    ]


def lookup_priority(local_field: str = "priorityId", as_field: str = "priority") -> list[dict]:
    return [
        {
            "$lookup": {
                "from": "priorities",
                "localField": local_field,
                "foreignField": "_id",
                "as": as_field,
                "pipeline": [{"$project": _PRIORITY_PROJECT}],
            }
        },
        {"$unwind": {"path": f"${as_field}", "preserveNullAndEmptyArrays": True}},
    ]


# ---------------------------------------------------------------------------
# Document → detail-shape helpers (mirror castXxxDocumentToDetails in utils.ts)
# ---------------------------------------------------------------------------

def shape_project(doc: dict) -> dict:
    return {
        "projectId": str(doc.get("projectId") or doc.get("_id", "")),
        "name": doc.get("name", ""),
        "identifier": doc.get("identifier", ""),
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
        "members": doc.get("memberIds", []),  # already populated via $lookup
    }


def shape_ticket(doc: dict) -> dict:
    return {
        "ticketId": str(doc.get("ticketId") or doc.get("_id", "")),
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "identifier": doc.get("identifier", ""),
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
        "assignee": doc.get("assigneeIds", []),
        "status": doc.get("statusId"),
        "priority": doc.get("priorityId"),
        "project": doc.get("projectId"),
        "createdBy": doc.get("createdById"),
        "updatedBy": doc.get("updatedById"),
    }


def _iso(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# Identifier generation (mirrors Mongoose pre-save hooks)
# ---------------------------------------------------------------------------

def generate_random_char_string(length: int) -> str:
    """Mirror of generateRandomCharString() in utils.ts."""
    chars = string.ascii_letters
    return "".join(random.choice(chars) for _ in range(length))


async def generate_project_identifier(name: str, coll: Any) -> str:
    """
    Replicates the Project pre-save identifier generation:
      - Try '{name[:3]}-{counter}' up to counter 100, then '{random3}-{counter}'.
      - Returns the unique identifier in UPPER CASE.

    Uses the $regex/$options query operator (instead of re.compile) so the
    query is fully serialisable and compatible with pymongo's AsyncMongoClient.
    """
    check_count = 1
    while True:
        prefix = name[:3] if (check_count < 100 and len(name) > 3) else generate_random_char_string(3)
        candidate = f"{prefix}-{check_count}".upper()
        existing = await coll.find_one(
            {"identifier": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}}
        )
        if not existing:
            return candidate
        check_count = check_count + 1 if check_count < 100 else 1


async def generate_ticket_identifier(project_identifier: str, project_id_str: str, coll: Any) -> str:
    """
    Replicates the Ticket pre-save identifier generation:
      - Format: '{project.identifier}-{task_count + 1}'
      - Loops until unique.

    Uses the $regex/$options query operator for case-insensitive uniqueness checks.
    """
    task_count = await coll.count_documents({"projectId": ObjectId(project_id_str)})
    while True:
        candidate = f"{project_identifier}-{task_count + 1}".upper()
        existing = await coll.find_one(
            {"identifier": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}}
        )
        if not existing:
            return candidate
        task_count += 1
