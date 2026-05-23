# Ticket Management MCP Server

A standalone **Python MCP (Model Context Protocol) server** that exposes ticket management tools over a **JSON-RPC 2.0 HTTP endpoint**.

The `generative-ui-agents-server` (LangGraph agent backend) calls this server, which forwards every tool call to the **Next.js REST API** — making it a thin, authenticated proxy rather than a direct database client.

---

## Why REST API, not direct MongoDB

The original design had this server talking directly to MongoDB Atlas, replicating every business rule from the Next.js actions layer (identifier generation, `$lookup` pipelines, API key SHA-256 validation, kanban key format). That meant **every rule lived in two places** — a maintenance hazard and a source of silent drift.

### What changed

| Concern | Before (direct Mongo) | After (REST proxy) |
|---|---|---|
| Business logic | Duplicated in Python | Lives only in Next.js actions |
| Auth | SHA-256 hash lookup in Python | `Bearer` token forwarded; Next.js validates |
| Consistency | Manual sync required | Same route = identical behaviour by construction |
| Dependency | Standalone (needed Atlas URI) | Requires Next.js app to be running |

### Why the trade-off is worth it

The MCP server is now a **thin HTTP client** — each tool handler is ~5 lines. Any change to Next.js actions (new fields, new validation, new relations) is automatically reflected in the MCP tools with zero Python changes. The coupling to Next.js uptime is intentional: the Next.js REST API is the single data gateway for all clients.

---

## Architecture

```
mcp-chat-client (:5173)
  └─ GET /chat/stream
       └─ agents-server (:8000)        ← LangGraph agents
            └─ POST /mcp  Bearer tms_...
                 └─ THIS server (:8001) ← MCP JSON-RPC proxy
                      └─ HTTP REST
                           └─ Next.js (:3000)   ← single data gateway
                                └─ MongoDB Atlas
```

```
ticket-management-mcp/
├── main.py              # FastAPI app — POST /mcp (JSON-RPC 2.0), format-check auth
├── config.py            # TMS_API_BASE_URL, MCP_SERVER_PORT, CORS_ORIGINS
├── requirements.txt     # fastapi, uvicorn, httpx, pydantic, pydantic-settings
├── .env / .env.example
│
├── api/
│   └── client.py        # TMSApiClient (httpx) + TMSApiError
│
├── auth/
│   └── api_key.py       # is_valid_token_format() — cheap prefix check only
│
└── tools/
    ├── context.py       # ToolContext dataclass (holds TMSApiClient per request)
    ├── _utils.py        # mcp_ok / mcp_error envelope builders
    ├── registry.py      # ToolRegistry — maps names → handlers
    ├── projects.py      # project_* handlers → GET/POST /api/project(s)/*
    ├── tickets.py       # ticket_* handlers  → GET/POST /api/ticket/*
    └── kanban.py        # kanban_* handlers  → GET/POST /api/kanban/*
```

---

## Available Tools

| Tool | REST endpoint | Required args |
|---|---|---|
| `project_list` | `GET /api/projects` | _(none)_ |
| `project_get_by_identifier` | `GET /api/project/identifier/{id}` | `identifier` |
| `project_create` | `POST /api/project/create` | `name` |
| `project_update` | `POST /api/project/update` | `projectId` |
| `ticket_list` | `GET /api/ticket/list` | `projectId` |
| `ticket_create` | `POST /api/ticket/create` | `projectId`, `name` |
| `ticket_update` | `POST /api/ticket/update` | `ticketId`, `projectId` |
| `kanban_get_column_order` | `GET /api/kanban/column-order` | `projectId`, `groupType` |
| `kanban_set_column_order` | `POST /api/kanban/column-order` | `projectId`, `groupType`, `columns` |

---

## Authentication

API keys are created in the Next.js UI at `/api-keys`. Pass the key as a Bearer token:

```
Authorization: Bearer tms_<your-api-key>
```

**Auth flow:**
1. This server checks the token starts with `tms_` (fast fail for obviously bad keys).
2. The raw token is forwarded verbatim on every REST call to Next.js.
3. The Next.js `tokenParser` validates the key (SHA-256 hash lookup, `isActive`, `expiresAt`) and resolves `userId`.
4. Auth errors from Next.js surface as `mcp_error(...)` back to the agent.

No credential is stored or checked in Python beyond the prefix format.

---

## Wire Format (JSON-RPC 2.0)

```http
POST /mcp
Authorization: Bearer tms_<key>
Content-Type: application/json

{ "jsonrpc": "2.0", "id": 1, "method": "tools/list" }
{ "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": { "name": "project_list", "arguments": {} } }
```

Responses:
```json
{ "jsonrpc": "2.0", "id": 1, "result": { "tools": [...] } }
{ "jsonrpc": "2.0", "id": 2, "result": { "content": [{ "type": "text", "text": "[{...}]" }] } }
```

`content[].text` is always a JSON string — the `MCPHTTPClient` in the agents server parses it automatically.

---

## Setup

### 1. Prerequisites

The **Next.js Ticket Management System must be running** before this server can serve any tool call. Set `TMS_API_BASE_URL` to its base URL.

### 2. Install

```bash
cd generative-ui/ticket-management-mcp
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

`.env`:
```env
TMS_API_BASE_URL=http://localhost:3000   # Next.js app — must be reachable
MCP_SERVER_PORT=8001
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000","http://localhost:8000"]
```

### 4. Run

```bash
python main.py
# or
uvicorn main:app --reload --port 8001
```

Health check:
```bash
curl http://localhost:8001/health
# {"status":"ok","service":"ticket-management-mcp","version":"2.0.0",...}
```

---

## Adding a New Tool

1. Add a handler in the relevant `tools/*.py` file:
   ```python
   async def my_tool(args: dict, ctx: ToolContext) -> dict:
       try:
           data = await ctx.api.get("/api/my-endpoint", params={"id": args["id"]})
           return mcp_ok(data)
       except TMSApiError as exc:
           return mcp_error(f"Error: {exc}")
   ```

2. Define its JSON Schema (used in `tools/list`).

3. Register in `tools/registry.py`:
   ```python
   _ToolEntry(name="my_tool", description="...", input_schema=MY_SCHEMA, handler=my_tool)
   ```

The new tool is immediately available to the agents server — no other changes needed.

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | HTTP framework and routing |
| `uvicorn` | ASGI server |
| `httpx` | Async HTTP client (calls Next.js REST API) |
| `pydantic` | Data validation |
| `pydantic-settings` | `.env` loading |
| `python-dotenv` | `.env` file support |
