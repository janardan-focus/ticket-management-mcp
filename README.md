# Ticket Management MCP Server

A standalone **Python MCP (Model Context Protocol) server** that exposes ticket management tools over a **JSON-RPC 2.0 HTTP endpoint** — replacing the MCP endpoint that was previously embedded inside the Next.js app.

The `generative-ui-agents-server` (LangGraph agent backend) calls this server to read and write ticket/project data directly from MongoDB, with no dependency on the Next.js app being alive.

---

## Why This Exists

The original architecture had the Next.js app (`localhost:3000`) doubling as both a UI server and an MCP data endpoint (`/api/mcp`). This Python server separates those concerns:

```
Before:
  agents-server → POST http://localhost:3000/api/mcp  (Next.js)

After:
  agents-server → POST http://localhost:8001/mcp       (this server)
                                    ↓
                              MongoDB Atlas (direct)
```

Benefits:
- The MCP data layer runs independently — the Next.js app no longer needs to be up for agent queries to work
- Python-native stack — easier to extend with new tools using the same language as the agent pipeline
- Same wire format — the existing `MCPHTTPClient` in `generative-ui-agents-server` works with zero code changes (only the URL in `.env` changes)

---

## Architecture

```
ticket-management-mcp/
│
├── main.py              # Entry point — FastAPI app with POST /mcp
├── config.py            # All env vars via pydantic-settings
├── requirements.txt     # Python dependencies
├── .env                 # Local secrets (MongoDB URI, port, etc.)
├── .env.example         # Template — copy this to .env
│
├── db/
│   └── connection.py    # Motor (async MongoDB) client singleton
│                        # + collection name constants
│
├── auth/
│   └── api_key.py       # API key validation (SHA-256 hash lookup)
│
└── tools/
    ├── _utils.py        # Shared helpers (JSON serialiser, MCP envelope, $lookup builders)
    ├── registry.py      # Tool registry — maps names to handlers for tools/list + tools/call
    ├── projects.py      # project_* tool handlers
    ├── tickets.py       # ticket_* tool handlers
    └── kanban.py        # kanban_* tool handlers
```

---

## How the MCP Protocol Works Here

This server speaks **JSON-RPC 2.0** over HTTP `POST /mcp` — the same protocol the Next.js app used.

### List available tools
```http
POST /mcp
Authorization: Bearer tms_<your-api-key>
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      { "name": "project_list", "description": "...", "inputSchema": { ... } },
      ...
    ]
  }
}
```

### Call a tool
```http
POST /mcp
Authorization: Bearer tms_<your-api-key>
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "project_list",
    "arguments": {}
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{ "type": "text", "text": "[{\"projectId\": \"...\", ...}]" }]
  }
}
```

The `content[].text` field is always a JSON string — the `MCPHTTPClient` in the agents server parses it automatically.

---

## Available Tools

| Tool | Description | Required Args |
|---|---|---|
| `project_list` | All projects the authenticated user is a member of | _(none)_ |
| `project_get_by_identifier` | Get a project by its short identifier (e.g. `TIC-1`) | `identifier` |
| `project_create` | Create a new project | `name` |
| `project_update` | Update project name or members | `projectId` |
| `ticket_list` | Paginated tickets for a project | `projectId` |
| `ticket_create` | Create a new ticket | `projectId`, `name` |
| `ticket_update` | Update ticket fields (status, priority, assignees, etc.) | `ticketId`, `projectId` |
| `kanban_get_column_order` | Get saved column order for a kanban board | `projectId`, `groupType` |
| `kanban_set_column_order` | Save column order for a kanban board | `projectId`, `groupType`, `columns` |

---

## Authentication

API keys are created in the Ticket Management System UI at `/api-keys`. The key is stored as a SHA-256 hash in the MongoDB `apikeys` collection.

When calling this server, pass the key as a Bearer token:
```
Authorization: Bearer tms_<your-api-key>
```

The server validates it by:
1. Hashing the provided key with SHA-256
2. Looking it up in the `apikeys` collection by `keyHash`
3. Checking `isActive == true` and that `expiresAt` (if set) is in the future
4. Updating `lastUsedAt` on success and returning the associated `userId`

All tool handlers receive the authenticated `userId` so they can scope queries correctly (e.g. `project_list` only returns projects the user is a member of).

---

## Database

This server connects directly to the same **MongoDB Atlas** cluster used by the Next.js app. No data is duplicated — it's the same database, same collections.

### Collection names

Mongoose auto-pluralises model names to lowercase — this server uses the same convention:

| Model (Next.js) | Collection |
|---|---|
| `AppUser` | `appusers` |
| `Project` | `projects` |
| `Ticket` | `tickets` |
| `Status` | `statuses` |
| `Priority` | `priorities` |
| `ApiKey` | `apikeys` |
| `KanbanColumnOrder` | `kanbancolumnorders` |

### Joins / Population

MongoDB has no native joins. This server uses **aggregation `$lookup` pipelines** to replicate what Mongoose's `.populate()` does in the Next.js app. For example, `ticket_list` joins across `appusers`, `projects`, `statuses`, and `priorities` in a single aggregation.

---

## Setup & Running

### 1. Clone / navigate to directory
```bash
cd generative-ui/ticket-management-mcp
```

### 2. Create virtual environment
```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows
```

### 3. Install dependencies
```bash
# If you accidentally installed the standalone bson package before, remove it first:
pip uninstall bson -y 2>/dev/null || true

pip install -r requirements.txt
# bson is bundled inside pymongo — do NOT pip install bson separately
```

### 4. Configure environment
```bash
cp .env.example .env
```

Edit `.env`:
```env
# Same connection string as the Next.js app's MONGODB_URI
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/?appName=MyApp

# The database name your Mongoose app uses.
# Check MongoDB Atlas → your cluster → Collections to find the correct name.
# Mongoose defaults to 'test' when no DB name is in the URI path.
MONGODB_DB_NAME=test

# Port for this server (8001 keeps it separate from the agents-server on 8000)
MCP_SERVER_PORT=8001

# Allowed CORS origins (JSON array format)
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000","http://localhost:8000"]
```

### 5. Start the server
```bash
# Development (auto-reload on file changes)
python main.py

# Or directly with uvicorn
uvicorn main:app --reload --port 8001

# Production
uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4
```

### 6. Verify it's running
```bash
curl http://localhost:8001/health
# {"status":"ok","service":"ticket-management-mcp","version":"1.0.0",...}
```

---

## Connecting the Agents Server

The `generative-ui-agents-server` already has its `.env` updated to point here:

```env
# generative-ui-agents-server/.env
MCP_SERVER_URL=http://localhost:8001/mcp   # ← was http://localhost:3000/api/mcp
```

No code changes are needed in the agents server — only this URL change.

---

## Full System Flow

```
Browser
  └─ mcp-chat-client (Vite :5173)
       └─ GET /chat/stream?query=...&api_key=...
            └─ generative-ui-agents-server (:8000)   ← LangGraph agents
                 └─ POST /mcp  Authorization: Bearer tms_...
                      └─ THIS server (:8001)           ← you are here
                           └─ MongoDB Atlas            ← shared DB
                                ↑
                 Ticket Management System (:3000)      ← UI only, no longer in data path
```

---

## Adding a New Tool

1. Write your handler in the appropriate file (`tools/projects.py`, `tools/tickets.py`, etc.) following the existing pattern:
   ```python
   async def my_tool(args: dict, user_id: str) -> dict:
       # ... Motor queries ...
       return mcp_ok(result)   # or mcp_error("message")
   ```

2. Define a JSON Schema for the tool inputs (used in `tools/list` responses).

3. Register it in `tools/registry.py` by adding a `_ToolEntry` to the `_TOOLS` list:
   ```python
   _ToolEntry(
       name="my_tool",
       description="What this tool does",
       input_schema=MY_TOOL_SCHEMA,
       handler=my_tool,
   )
   ```

That's it — it becomes immediately available to the agents server on next request.

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | HTTP framework and request routing |
| `uvicorn` | ASGI server |
| `motor==3.3.2` | Async MongoDB driver (built on pymongo) |
| `pymongo==4.6.3` | MongoDB wire protocol + **bson bundled inside** |
| `pydantic` | Data validation |
| `pydantic-settings` | Environment variable loading |
| `python-dotenv` | `.env` file support |

> **⚠️ Do NOT `pip install bson`**
> The standalone `bson` package on PyPI is an abandoned, incompatible project. `ObjectId` and all other BSON types ship **inside `pymongo`** — once you install `pymongo`, `from bson import ObjectId` works automatically. Installing the standalone `bson` package will break pymongo's bson import entirely.

---

## Troubleshooting

### `Failed to build installable wheels for bson`
You ran `pip install bson` by mistake. That standalone package is broken and not needed.

Fix:
```bash
pip uninstall bson           # remove the broken standalone package
pip install -r requirements.txt   # pymongo already bundles bson
```

### `ModuleNotFoundError: No module named 'bson'`
You have `bson` installed as the standalone package which shadows pymongo's bson.

Fix:
```bash
pip uninstall bson pymongo motor
pip install -r requirements.txt   # fresh install of pymongo (includes bson)
```

### `AttributeError: module 'lib' has no attribute 'X509_V_FLAG_NOTIFY_POLICY'`
Your system has an old `pyOpenSSL` (< 23.2.0) conflicting with a newer `cryptography` library.

Fix:
```bash
pip install "pyOpenSSL>=23.2.0"
```

### Motor / pymongo version conflicts
Pin to the tested versions in `requirements.txt`:
```
motor==3.3.2
pymongo==4.6.3
```
