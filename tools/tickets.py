"""
Ticket MCP tools — direct MongoDB access via Motor.

Tools:
  ticket_list    → paginated tickets for a project
  ticket_create  → create a new ticket in a project
  ticket_update  → update fields on an existing ticket
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from db.mongo_types import ObjectId, is_valid_object_id

from db.connection import (
    COLL_PRIORITIES,
    COLL_PROJECTS,
    COLL_STATUSES,
    COLL_TICKETS,
    COLL_USERS,
    get_db,
)
from tools._utils import generate_ticket_identifier, mcp_error, mcp_ok

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
# Aggregation pipeline: populate all refs (mirrors getPaginatedProjectTickets)
# ---------------------------------------------------------------------------

def _ticket_pipeline(match_stage: dict) -> list[dict]:
    _user_proj = {
        "fullname": 1, "firstname": 1, "lastname": 1,
        "userId": 1, "image": 1, "email": 1, "_id": 0,
    }
    _project_proj = {"projectId": 1, "name": 1, "identifier": 1, "_id": 0}
    _status_proj = {"statusId": 1, "name": 1, "isDefault": 1, "icon": 1, "color": 1, "isDone": 1, "_id": 0}
    _priority_proj = {"priorityId": 1, "name": 1, "isDefault": 1, "icon": 1, "color": 1, "_id": 0}

    return [
        {"$match": match_stage},
        # assigneeIds → array of user objects
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "assigneeIds",
                "foreignField": "_id",
                "as": "assigneeIds",
                "pipeline": [{"$project": _user_proj}],
            }
        },
        # projectId → project object
        {
            "$lookup": {
                "from": COLL_PROJECTS,
                "localField": "projectId",
                "foreignField": "_id",
                "as": "projectId",
                "pipeline": [{"$project": _project_proj}],
            }
        },
        {"$unwind": {"path": "$projectId", "preserveNullAndEmptyArrays": True}},
        # statusId → status object
        {
            "$lookup": {
                "from": COLL_STATUSES,
                "localField": "statusId",
                "foreignField": "_id",
                "as": "statusId",
                "pipeline": [{"$project": _status_proj}],
            }
        },
        {"$unwind": {"path": "$statusId", "preserveNullAndEmptyArrays": True}},
        # priorityId → priority object
        {
            "$lookup": {
                "from": COLL_PRIORITIES,
                "localField": "priorityId",
                "foreignField": "_id",
                "as": "priorityId",
                "pipeline": [{"$project": _priority_proj}],
            }
        },
        {"$unwind": {"path": "$priorityId", "preserveNullAndEmptyArrays": True}},
        # createdById → user object
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "createdById",
                "foreignField": "_id",
                "as": "createdById",
                "pipeline": [{"$project": _user_proj}],
            }
        },
        {"$unwind": {"path": "$createdById", "preserveNullAndEmptyArrays": True}},
        # updatedById → user object
        {
            "$lookup": {
                "from": COLL_USERS,
                "localField": "updatedById",
                "foreignField": "_id",
                "as": "updatedById",
                "pipeline": [{"$project": _user_proj}],
            }
        },
        {"$unwind": {"path": "$updatedById", "preserveNullAndEmptyArrays": True}},
    ]


def _doc_to_detail(doc: dict) -> dict:
    """Mirror castTicketDocumentToDetails from utils.ts."""
    return {
        "ticketId": str(doc.get("ticketId") or doc.get("_id", "")),
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "identifier": doc.get("identifier", ""),
        "createdAt": doc["createdAt"].isoformat() if doc.get("createdAt") else None,
        "updatedAt": doc["updatedAt"].isoformat() if doc.get("updatedAt") else None,
        "assignee": doc.get("assigneeIds", []),
        "status": doc.get("statusId"),
        "priority": doc.get("priorityId"),
        "project": doc.get("projectId"),
        "createdBy": doc.get("createdById"),
        "updatedBy": doc.get("updatedById"),
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def ticket_list(args: dict, user_id: str) -> dict:
    """Return paginated tickets for a project (default page=1, pageSize=100, sortBy=createdAt desc)."""
    project_id: str | None = args.get("projectId")
    if not project_id:
        return mcp_error("Error listing tickets: projectId is required")

    page = max(1, int(args.get("page", 1)))
    page_size = max(1, min(200, int(args.get("pageSize", 100))))
    sort_by = args.get("sortBy", "createdAt")
    sort_order = -1 if args.get("sortOrder", "desc") == "desc" else 1
    skip = (page - 1) * page_size

    try:
        db = get_db()
        coll = db[COLL_TICKETS]

        match = {"projectId": ObjectId(project_id)}

        # Total count
        total_records = await coll.count_documents(match)

        # Paginated pipeline
        pipeline = _ticket_pipeline(match) + [
            {"$sort": {sort_by: sort_order}},
            {"$skip": skip},
            {"$limit": page_size},
        ]
        cursor = await coll.aggregate(pipeline)
        tickets = [_doc_to_detail(doc) async for doc in cursor]

        return mcp_ok({
            "data": tickets,
            "totalRecords": total_records,
            "totalPages": -(-total_records // page_size),  # ceiling division
            "page": page,
            "pageSize": page_size,
            "sortBy": sort_by,
            "sortOrder": "desc" if sort_order == -1 else "asc",
        })
    except Exception as exc:
        logger.exception("ticket_list failed")
        return mcp_error(f"Error listing tickets: {exc}")


async def ticket_create(args: dict, user_id: str) -> dict:
    """Create a new ticket in the specified project."""
    project_id: str | None = args.get("projectId")
    name: str | None = args.get("name")

    if not project_id:
        return mcp_error("Error creating ticket: projectId is required")
    if not name or not name.strip():
        return mcp_error("Error creating ticket: name is required")

    try:
        db = get_db()
        ticket_coll = db[COLL_TICKETS]
        project_coll = db[COLL_PROJECTS]

        # Fetch project for identifier generation
        project_doc = await project_coll.find_one({"projectId": project_id})
        if not project_doc:
            return mcp_error(f"Error creating ticket: project '{project_id}' not found")

        project_identifier: str = project_doc.get("identifier", "TICK")
        ticket_identifier = await generate_ticket_identifier(
            project_identifier, project_id, ticket_coll
        )

        # Build assigneeIds
        assignee_oids: list[ObjectId] = []
        for aid in (args.get("assigneeIds") or []):
            try:
                assignee_oids.append(ObjectId(aid))
            except Exception:
                pass

        new_id = ObjectId()
        now = datetime.now(tz=timezone.utc)

        doc: dict[str, Any] = {
            "_id": new_id,
            "ticketId": str(new_id),
            "name": name.strip(),
            "description": args.get("description", ""),
            "identifier": ticket_identifier,
            "assigneeIds": assignee_oids,
            "projectId": ObjectId(project_id),
            "createdById": ObjectId(user_id),
            "updatedById": ObjectId(user_id),
            "createdAt": now,
            "updatedAt": now,
        }

        # Optional references
        if args.get("statusId"):
            try:
                doc["statusId"] = ObjectId(args["statusId"])
            except Exception:
                pass
        if args.get("priorityId"):
            try:
                doc["priorityId"] = ObjectId(args["priorityId"])
            except Exception:
                pass

        await ticket_coll.insert_one(doc)

        # Fetch back with populated fields
        pipeline = _ticket_pipeline({"_id": new_id})
        cursor = ticket_coll.aggregate(pipeline)
        docs = [d async for d in cursor]
        created = _doc_to_detail(docs[0]) if docs else {"ticketId": str(new_id)}

        return mcp_ok(created)
    except Exception as exc:
        logger.exception("ticket_create failed")
        return mcp_error(f"Error creating ticket: {exc}")


async def ticket_update(args: dict, user_id: str) -> dict:
    """Update fields on an existing ticket."""
    ticket_id: str | None = args.get("ticketId")
    project_id: str | None = args.get("projectId")

    if not ticket_id:
        return mcp_error("Error updating ticket: ticketId is required")
    if not project_id:
        return mcp_error("Error updating ticket: projectId is required")

    update_fields: dict[str, Any] = {}

    if "name" in args and args["name"]:
        update_fields["name"] = args["name"].strip()
    if "description" in args:
        update_fields["description"] = args["description"]
    if "assigneeIds" in args and isinstance(args["assigneeIds"], list):
        update_fields["assigneeIds"] = [
            ObjectId(aid) for aid in args["assigneeIds"]
            if is_valid_object_id(aid)
        ]
    if "statusId" in args and args["statusId"] and is_valid_object_id(args["statusId"]):
        update_fields["statusId"] = ObjectId(args["statusId"])
    if "priorityId" in args and args["priorityId"] and is_valid_object_id(args["priorityId"]):
        update_fields["priorityId"] = ObjectId(args["priorityId"])

    if not update_fields:
        return mcp_error(
            "Error updating ticket: no fields to update "
            "(provide name, description, assigneeIds, statusId, or priorityId)"
        )

    try:
        update_fields["updatedById"] = ObjectId(user_id)
        update_fields["updatedAt"] = datetime.now(tz=timezone.utc)

        db = get_db()
        coll = db[COLL_TICKETS]

        result = await coll.find_one_and_update(
            {"ticketId": ticket_id, "projectId": ObjectId(project_id)},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if not result:
            return mcp_error(
                f"Error updating ticket: ticket '{ticket_id}' not found in project '{project_id}'"
            )

        # Fetch back with populated fields
        pipeline = _ticket_pipeline({"ticketId": ticket_id})
        cursor = await coll.aggregate(pipeline)
        docs = [d async for d in cursor]
        updated = _doc_to_detail(docs[0]) if docs else result

        return mcp_ok(updated)
    except Exception as exc:
        logger.exception("ticket_update failed")
        return mcp_error(f"Error updating ticket: {exc}")
