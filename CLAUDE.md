# CLAUDE.md — ticket-management-mcp

## Design decision: why REST API, not direct MongoDB

The MCP server was originally a Python clone of the Next.js business logic — it
ran the same `$lookup` aggregations, generated identifiers, and validated API keys
against MongoDB itself. That meant **every business rule existed twice** and any
change to the Next.js actions had to be manually mirrored here.

The server was refactored to call the Next.js REST API instead:

- **Single source of truth.** Identifier generation, kanban key format, populate
  shape, member rules — all live only in the Next.js actions layer. The MCP tools
  become thin HTTP callers (~5 lines each).
- **Consistent behaviour by construction.** The MCP server hits the exact same
  `/api/*` routes the web UI uses, so validation, audit fields, and error handling
  are identical without any extra effort.
- **Pass-through auth.** The caller's `Bearer tms_<key>` is forwarded verbatim to
  every Next.js route. The API resolves `userId` and enforces permissions — no
  duplicate SHA-256 hash lookup in Python.

Trade-off accepted: the MCP server now depends on the Next.js app being up. This
is intentional — the Next.js REST API is the single data gateway.

## Project Overview

**Python FastAPI** server that exposes all Ticket Management System tools over the
**MCP JSON-RPC 2.0 wire protocol** — a drop-in replacement for the Next.js `/api/mcp` endpoint.

Key design goals (post-migration):
- Identical wire format to the Next.js endpoint → `MCPHTTPClient` in `generative-ui-agents-server` works with **zero changes**
- **REST API client** (`api/client.py`, httpx) — no direct MongoDB access
- **Pass-through auth** — the caller's `Bearer tms_<key>` is forwarded verbatim to every Next.js route; the API enforces user identity and permissions
- Business logic (identifier generation, populate/$lookup, kanban key format) lives **only** in the Next.js actions layer

> **Coupling note:** The MCP server hard-depends on the Next.js app being up.
> `TMS_API_BASE_URL` must point to a reachable instance. Previously it could run
> standalone against Atlas — that is no longer the case by design.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Web framework | FastAPI 0.115+, uvicorn |
| HTTP client | httpx 0.27+ (async, reused per request) |
| Config | pydantic-settings 2.x |
| Python | 3.13, virtual env at `.venv/` |

---

## Directory Structure

```
ticket-management-mcp/
├── main.py              # FastAPI app — POST /mcp endpoint (JSON-RPC 2.0)
├── config.py            # Pydantic settings (reads .env) — TMS_API_BASE_URL, MCP_SERVER_PORT
├── requirements.txt     # fastapi, uvicorn, httpx, pydantic, pydantic-settings
├── .env                 # Local env vars (git-ignored in prod)
├── .env.example         # Template
│
├── api/
│   ├── __init__.py
│   └── client.py        # TMSApiClient — async httpx wrapper + TMSApiError
│
├── auth/
│   ├── __init__.py
│   └── api_key.py       # Stub: is_valid_token_format() format check only (DB lookup removed)
│
├── db/                  # DEPRECATED — tombstone stubs, safe to delete from repo
│   ├── connection.py    # raises ImportError
│   └── mongo_types.py   # raises ImportError
│
└── tools/
    ├── __init__.py
    ├── _utils.py        # mcp_ok, mcp_error (Mongo helpers removed)
    ├── registry.py      # ToolRegistry + ToolContext dataclass
    ├── projects.py      # project_list, project_get_by_identifier, project_create, project_update
    ├── tickets.py       # ticket_list, ticket_create, ticket_update
    └── kanban.py        # kanban_get_column_order, kanban_set_column_order
```

---

## Environment Variables (`.env`)

```
TMS_API_BASE_URL=http://localhost:3000   # Next.js app base URL — must be reachable
MCP_SERVER_PORT=8001                     # Port to listen on (8000 = agents-server)
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000","http://localhost:8000"]
```

---

## MCP Tools Exposed

| Tool | REST endpoint |
|---|---|
| `project_list` | `GET /api/projects` |
| `project_get_by_identifier` | `GET /api/project/identifier/{identifier}` |
| `project_create` | `POST /api/project/create` |
| `project_update` | `POST /api/project/update` |
| `ticket_list` | `GET /api/ticket/list?projectId=&page=&pageSize=&sortBy=&sortOrder=` |
| `ticket_create` | `POST /api/ticket/create` |
| `ticket_update` | `POST /api/ticket/update` |
| `kanban_get_column_order` | `GET /api/kanban/column-order?projectId=&groupType=` |
| `kanban_set_column_order` | `POST /api/kanban/column-order` |

---

## Auth Flow

```
agents-server
  └─ POST /mcp
      Authorization: Bearer tms_<key>
          │
          ▼
    main.py: cheap format check (startswith "tms_")
          │
          ▼
    api/client.py: forward header verbatim on every REST call
          │
          ▼
    Next.js tokenParser → validateApiKey (SHA-256 lookup) → resolves userId
```

The MCP server never reads the database itself — it is a thin HTTP proxy.

---

## Wire Format (JSON-RPC 2.0)

Requests:
```json
POST /mcp
Authorization: Bearer tms_<key>
Content-Type: application/json

{ "jsonrpc": "2.0", "id": 1, "method": "tools/list" }
{ "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": { "name": "project_list", "arguments": {} } }
```

Responses (identical to Next.js endpoint):
```json
{ "jsonrpc": "2.0", "id": 1, "result": { "tools": [...] } }
{ "jsonrpc": "2.0", "id": 2, "result": { "content": [{ "type": "text", "text": "..." }] } }
```

---

## Inter-Service Communication

```
mcp-chat-client (Vite :5173)
    └─ GET /chat/stream ──► generative-ui-agents-server (:8000)
                                └─ POST /mcp ──► THIS server (:8001)
                                                    └─ HTTP ──► Next.js (:3000)
                                                                    └─ Mongoose ──► MongoDB Atlas
```

---

## Running Locally

```bash
cd ticket-management-mcp

# Create venv and install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and configure env
cp .env.example .env
# Edit .env — set TMS_API_BASE_URL to your Next.js app URL

# Ensure Next.js app is running (it is required)
# cd ../Ticket-Management-System && npm run dev

# Start (reload mode for development)
python main.py
# or
uvicorn main:app --reload --port 8001
```

---

## Key Files to Know First

1. `main.py` — FastAPI app, format-check auth, JSON-RPC dispatch, per-request `ToolContext`
2. `api/client.py` — `TMSApiClient` (httpx wrapper) + `TMSApiError`
3. `tools/registry.py` — `ToolRegistry`, `ToolContext` dataclass, handler dispatch
4. `tools/_utils.py` — `mcp_ok`, `mcp_error` envelope builders
5. `config.py` — `TMS_API_BASE_URL` and other settings
