"""
Ticket Management MCP Server
=============================
Python FastAPI server that exposes all ticket-management tools over the
MCP JSON-RPC 2.0 wire protocol — a drop-in replacement for the Next.js
/api/mcp endpoint.

Wire format is identical to the Next.js MCP endpoint so the existing
MCPHTTPClient in generative-ui-agents-server works without any changes.

Endpoint:  POST /mcp
Auth:      Authorization: Bearer <tms_...api_key>
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth.api_key import validate_api_key
from config import settings
from db.connection import connect_db, disconnect_db
from tools.registry import ToolRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: open / close MongoDB connection
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await disconnect_db()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Ticket Management MCP Server",
    description=(
        "Python MCP server exposing ticket-management tools over JSON-RPC 2.0. "
        "Direct MongoDB access — replaces the Next.js /api/mcp endpoint."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _ok(rpc_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "ticket-management-mcp",
        "version": "1.0.0",
        "protocol": "mcp",
        "transport": "http",
        "endpoint": "/mcp",
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    """
    MCP JSON-RPC 2.0 endpoint.

    Supported methods:
      tools/list  — return all available tool definitions
      tools/call  — execute a named tool
    """
    # ---- 1. Authentication -----------------------------------------------
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            _err(None, -32001, "Unauthorized: Bearer token required"),
            status_code=401,
        )

    api_key = auth_header[7:]  # strip "Bearer "
    validation = await validate_api_key(api_key)
    if not validation["valid"]:
        return JSONResponse(
            _err(None, -32001, validation.get("error") or "Invalid API key"),
            status_code=401,
        )

    user_id: str = validation["user_id"]  # type: ignore[assignment]

    # ---- 2. Parse JSON-RPC body ------------------------------------------
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse(
            _err(None, -32700, "Parse error: request body must be valid JSON"),
            status_code=400,
        )

    rpc_id = body.get("id")
    method: str | None = body.get("method")
    params: dict = body.get("params") or {}

    if not method:
        return JSONResponse(
            _err(rpc_id, -32600, "Invalid Request: 'method' field is required"),
            status_code=400,
        )

    # ---- 3. Dispatch -------------------------------------------------------
    try:
        if method == "tools/list":
            result = registry.list_tools()

        elif method == "tools/call":
            tool_name: str | None = params.get("name")
            tool_args: dict = params.get("arguments") or {}

            if not tool_name:
                return JSONResponse(
                    _err(rpc_id, -32602, "Invalid params: 'name' is required for tools/call"),
                    status_code=400,
                )

            result = await registry.call_tool(tool_name, tool_args, user_id)

        else:
            return JSONResponse(
                _err(rpc_id, -32601, f"Method not found: '{method}'"),
                status_code=404,
            )

    except ValueError as exc:
        # Unknown tool name
        return JSONResponse(_err(rpc_id, -32602, str(exc)), status_code=400)

    except Exception as exc:
        logger.exception("Unhandled error in tool execution")
        return JSONResponse(
            _err(rpc_id, -32603, f"Internal error: {exc}"),
            status_code=500,
        )

    return JSONResponse(_ok(rpc_id, result))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.mcp_server_port,
        reload=True,
        log_level="info",
    )
