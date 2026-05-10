"""
Project MCP tools — direct MongoDB access via Motor.

Tools:
  project_list               → all projects the authenticated user is a member of
  project_get_by_identifier  → single project by its short identifier (e.g. "TIC-1")
  project_create             → insert a new project
  project_update             → update name or memberIds of an existing project
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pymongo import ReturnDocument

from db.mongo_types import ObjectId

from db.connection import COLL_PROJECTS, COLL_USERS, get_db
from tools._utils import (
    generate_project_identifier,
    lookup_users,
    mcp_error,
    mcp_ok,
    shape_project,
)

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
# Aggregation helper: populate memberIds → members (array of user objects)
# ---------------------------------------------------------------------------

def _project_pipeline(match_stage: dict) -> list[dict]:
    """Build an aggregation pipeline that looks up members + audit users."""
    return [
        {"$match": match_stage},
        # Populate memberIds array → members
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "memberIds",
                "foreignField": "_id",
                "as": "memberIds",
                "pipeline": [
                    {
                        "$project": {
                            "fullname": 1, "firstname": 1, "lastname": 1,
                            "userId": 1, "image": 1, "email": 1, "_id": 0,
                        }
                    }
                ],
            }
        },
        # Populate createdById
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "createdById",
                "foreignField": "_id",
                "as": "createdById",
                "pipeline": [
                    {
                        "$project": {
                            "fullname": 1, "firstname": 1, "lastname": 1,
                            "userId": 1, "image": 1, "email": 1, "_id": 0,
                        }
                    }
                ],
            }
        },
        {"$unwind": {"path": "$createdById", "preserveNullAndEmptyArrays": True}},
        # Populate updatedById
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "updatedById",
                "foreignField": "_id",
                "as": "updatedById",
                "pipeline": [
                    {
                        "$project": {
                            "fullname": 1, "firstname": 1, "lastname": 1,
                            "userId": 1, "image": 1, "email": 1, "_id": 0,
                        }
                    }
                ],
            }
        },
        {"$unwind": {"path": "$updatedById", "preserveNullAndEmptyArrays": True}},
    ]


def _doc_to_detail(doc: dict) -> dict:
    """Mirror castProjectDocumentToDetails from utils.ts."""
    return {
        "projectId": str(doc.get("projectId") or doc.get("_id", "")),
        "name": doc.get("name", ""),
        "identifier": doc.get("identifier", ""),
        "createdAt": doc.get("createdAt").isoformat() if doc.get("createdAt") else None,
        "updatedAt": doc.get("updatedAt").isoformat() if doc.get("updatedAt") else None,
        "members": doc.get("memberIds", []),  # already populated
        "createdBy": doc.get("createdById"),
        "updatedBy": doc.get("updatedById"),
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def project_list(args: dict, user_id: str) -> dict:
    """Return all projects where the authenticated user is a member."""
    try:
        db = get_db()
        coll = db[COLL_PROJECTS]

        pipeline = _project_pipeline({"memberIds": {"$in": [ObjectId(user_id)]}})
        cursor = await coll.aggregate(pipeline)
        projects = [_doc_to_detail(doc) async for doc in cursor]

        return mcp_ok(projects)
    except Exception as exc:
        logger.exception("project_list failed")
        return mcp_error(f"Error fetching projects: {exc}")


async def project_get_by_identifier(args: dict, user_id: str) -> dict:
    """Return a single project by its short identifier (case-insensitive)."""
    identifier: str | None = args.get("identifier")
    if not identifier:
        return mcp_error("Error fetching project: identifier is required")

    try:
        db = get_db()
        coll = db[COLL_PROJECTS]

        # Use the $regex/$options operator — avoids passing a compiled regex
        # object, keeping queries fully JSON-serialisable and compatible with
        # pymongo's AsyncMongoClient.
        pipeline = _project_pipeline(
            {"identifier": {"$regex": f"^{re.escape(identifier)}$", "$options": "i"}}
        )
        cursor = await coll.aggregate(pipeline)
        docs = [doc async for doc in cursor]

        if not docs:
            return mcp_error(f"Project with identifier '{identifier}' not found")

        return mcp_ok(_doc_to_detail(docs[0]))
    except Exception as exc:
        logger.exception("project_get_by_identifier failed")
        return mcp_error(f"Error fetching project: {exc}")


async def project_create(args: dict, user_id: str) -> dict:
    """Create a new project. The creator is added as the first member automatically."""
    name: str | None = args.get("name")
    if not name or not name.strip():
        return mcp_error("Error creating project: name is required")

    try:
        db = get_db()
        coll = db[COLL_PROJECTS]

        # Build memberIds list (always include the creator)
        member_id_strs: list[str] = args.get("memberIds") or []
        member_oids: list[ObjectId] = []
        seen: set[str] = set()
        for mid in [user_id] + member_id_strs:
            if mid not in seen:
                try:
                    member_oids.append(ObjectId(mid))
                    seen.add(mid)
                except Exception:
                    pass  # skip invalid ids

        # Identifier
        custom_identifier: str | None = args.get("identifier")
        if custom_identifier:
            identifier = custom_identifier.upper()
            # Verify uniqueness
            existing = await coll.find_one(
                {"identifier": {"$regex": f"^{custom_identifier}$", "$options": "i"}}
            )
            if existing:
                return mcp_error(
                    f"Error creating project: identifier '{custom_identifier}' is already taken"
                )
        else:
            identifier = await generate_project_identifier(name.strip(), coll)

        new_id = ObjectId()
        doc = {
            "_id": new_id,
            "projectId": str(new_id),
            "name": name.strip(),
            "identifier": identifier,
            "memberIds": member_oids,
            "taskIds": [],
            "createdById": ObjectId(user_id),
            "updatedById": ObjectId(user_id),
        }

        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        doc["createdAt"] = now
        doc["updatedAt"] = now

        await coll.insert_one(doc)

        # Fetch back with populated fields
        pipeline = _project_pipeline({"_id": new_id})
        cursor = await coll.aggregate(pipeline)
        docs = [d async for d in cursor]
        created = _doc_to_detail(docs[0]) if docs else {"projectId": str(new_id)}

        return mcp_ok(created)
    except Exception as exc:
        logger.exception("project_create failed")
        return mcp_error(f"Error creating project: {exc}")


async def project_update(args: dict, user_id: str) -> dict:
    """Update an existing project's name and/or memberIds."""
    project_id: str | None = args.get("projectId")
    if not project_id:
        return mcp_error("Error updating project: projectId is required")

    update_fields: dict[str, Any] = {}
    if "name" in args and args["name"]:
        update_fields["name"] = args["name"].strip()

    if "memberIds" in args and isinstance(args["memberIds"], list):
        # Validate and convert member IDs
        member_oids: list[ObjectId] = []
        for mid in args["memberIds"]:
            try:
                member_oids.append(ObjectId(mid))
            except Exception:
                pass
        update_fields["memberIds"] = member_oids

    if not update_fields:
        return mcp_error("Error updating project: no fields to update (provide name or memberIds)")

    try:
        from datetime import datetime, timezone
        update_fields["updatedById"] = ObjectId(user_id)
        update_fields["updatedAt"] = datetime.now(tz=timezone.utc)

        db = get_db()
        coll = db[COLL_PROJECTS]

        result = await coll.find_one_and_update(
            {"projectId": project_id},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if not result:
            return mcp_error(f"Error updating project: project '{project_id}' not found")

        # Fetch back with populated fields
        pipeline = _project_pipeline({"projectId": project_id})
        cursor = await coll.aggregate(pipeline)
        docs = [d async for d in cursor]
        updated = _doc_to_detail(docs[0]) if docs else result

        return mcp_ok(updated)
    except Exception as exc:
        logger.exception("project_update failed")
        return mcp_error(f"Error updating project: {exc}")
