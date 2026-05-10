"""
PyMongo AsyncMongoClient — singleton lifecycle managed by FastAPI lifespan.

pymongo 4.9+ ships a native async client (AsyncMongoClient), removing the
need for Motor as a separate dependency.

Collection names mirror Mongoose's auto-pluralisation convention:
  AppUser          → appusers
  Project          → projects
  Ticket           → tickets
  Status           → statuses
  Priority         → priorities
  ApiKey           → apikeys
  KanbanColumnOrder→ kanbancolumnorders
"""

from __future__ import annotations

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.server_api import ServerApi

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None


async def connect_db() -> None:
    """Open the AsyncMongoClient and verify connectivity with a ping.

    ServerApi(version="1") enables the MongoDB Stable API, which ensures
    consistent behaviour across server upgrades and raises deprecation errors
    immediately rather than silently.
    """
    global _client
    _client = AsyncMongoClient(
        settings.mongodb_uri,
        server_api=ServerApi(version="1", strict=True, deprecation_errors=True),
    )
    await _client.admin.command("ping")
    logger.info("Connected to MongoDB — db: %s", settings.mongodb_db_name)


async def disconnect_db() -> None:
    """Close the AsyncMongoClient."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        logger.info("Disconnected from MongoDB")


def get_db() -> AsyncDatabase:
    """Return the application database. Raises if connect_db() was not called."""
    if _client is None:
        raise RuntimeError("Database not connected — call connect_db() first (FastAPI lifespan).")
    return _client[settings.mongodb_db_name]


def get_collection(name: str) -> AsyncCollection:
    """Convenience helper — return a named collection from the app database."""
    return get_db()[name]


# ---------------------------------------------------------------------------
# Collection name constants (Mongoose pluralisation)
# ---------------------------------------------------------------------------

COLL_USERS = "appusers"
COLL_PROJECTS = "projects"
COLL_TICKETS = "tickets"
COLL_STATUSES = "statuses"
COLL_PRIORITIES = "priorities"
COLL_API_KEYS = "apikeys"
COLL_KANBAN = "kanbancolumnorders"
