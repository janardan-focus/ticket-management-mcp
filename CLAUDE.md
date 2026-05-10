# CLAUDE.md — ticket-management-mcp

## Project Overview

**Python FastAPI** server that exposes all Ticket Management System tools over the
**MCP JSON-RPC 2.0 wire protocol** — a drop-in replacement for the Next.js `/api/mcp` endpoint.

Key design goals:
- Identical wire format to the Next.js endpoint → `MCPHTTPClient` in `generative-ui-agents-server` works with **zero changes**
- **Direct MongoDB access** via Motor (async) — no dependency on the Next.js app being alive
- Same authentication logic (SHA-256 API key hash, checked against the shared `ApiKey` collection)
- Same business rules (project/ticket identifier generation, kanban key format)

---

## Tech Stack

| Layer | Tech |
|---|---|
| Web framework | FastAPI 0.115+, uvicorn |
| Database | pymongo 4.16+ — native `AsyncMongoClient` (Motor removed) |
| Config | pydantic-settings 2.x |
| Python | 3.13, virtual env at `.venv/` |

> **Motor removed (May 2025):** pymongo 4.9+ ships `AsyncMongoClient` natively.
> Motor is no longer a dependency. The `[srv]` extra (`pymongo[srv]`) pulls in
> `dnspython` for `mongodb+srv://` Atlas connection strings.

---

## Directory Structure

```
ticket-management-mcp/
├── main.py              # FastAPI app — POST /mcp endpoint (JSON-RPC 2.0)
├── config.py            # Pydantic settings (reads .env)
├── requirements.txt
├── .env                 # Local env vars (git-ignored in prod)
├── .env.example         # Template
│
├── db/
│   ├── __init__.py
│   └── connection.py    # Motor client singleton + collection name constants
│
├── auth/
│   ├── __init__.py
│   └── api_key.py       # API key validation (SHA-256 hash, port of Next.js validateApiKey)
│
└── tools/
    ├── __init__.py
    ├── _utils.py        # Shared: JSON serialisation, MCP envelope builder, $lookup helpers
    ├── registry.py      # ToolRegistry: tools/list + tools/call dispatcher
    ├── projects.py      # project_list, project_get_by_identifier, project_create, project_update
    ├── tickets.py       # ticket_list, ticket_create, ticket_update
    └── kanban.py        # kanban_get_column_order, kanban_set_column_order
```

---

## Environment Variables (`.env`)

```
MONGODB_URI=mongodb+srv://...    # Same as Next.js MONGODB_URI
MONGODB_DB_NAME=test             # DB name (Mongoose defaults to 'test' when not in URI path)
MCP_SERVER_PORT=8001             # Port to listen on (8000 = agents-server)
CORS_ORIGINS=http://...          # Comma-separated allowed origins
```

---

## MCP Tools Exposed

| Tool | Description |
|---|---|
| `project_list` | All projects the user is a member of |
| `project_get_by_identifier` | Single project by short identifier (e.g. `TIC-1`) |
| `project_create` | Create a new project |
| `project_update` | Update project name / members |
| `ticket_list` | Paginated tickets for a project |
| `ticket_create` | Create a ticket (auto-generates identifier) |
| `ticket_update` | Update ticket fields |
| `kanban_get_column_order` | Retrieve board column order |
| `kanban_set_column_order` | Persist board column order |

---

## MongoDB Collection Names

Mongoose auto-pluralises model names (lowercase):

| Mongoose Model | Collection |
|---|---|
| `AppUser` | `appusers` |
| `Project` | `projects` |
| `Ticket` | `tickets` |
| `Status` | `statuses` |
| `Priority` | `priorities` |
| `ApiKey` | `apikeys` |
| `KanbanColumnOrder` | `kanbancolumnorders` |

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

## Business Rules Replicated from Next.js

### API Key Validation (`auth/api_key.py`)
- `tms_` prefix → SHA-256 hash → lookup by `keyHash` in `apikeys` collection
- 24-char hex → legacy `keyId` lookup (deprecated, warns)
- Checks `isActive == True` and `expiresAt` not in the past
- Updates `lastUsedAt` on success

### Project Identifier Generation (`tools/_utils.py`)
- Format: `{name[:3]}-{counter}` (counter 1–100), then `{random3}-{counter}`
- Stored in UPPER CASE
- Loops until unique (case-insensitive check)

### Ticket Identifier Generation (`tools/_utils.py`)
- Format: `{project.identifier}-{ticket_count+1}` (UPPER CASE)
- Loops until unique

### Kanban Column Order Key (`tools/kanban.py`)
- Format: `{userId}_{projectId}_{groupType}` (mirrors `getKanbanColumnOrderKey` in utils.ts)

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
# Edit .env — set MONGODB_URI and MONGODB_DB_NAME

# Start (reload mode for development)
python main.py
# or
uvicorn main:app --reload --port 8001
```

---

## Inter-Service Communication

```
mcp-chat-client (Vite :5173)
    └─ GET /chat/stream ──► generative-ui-agents-server (:8000)
                                └─ POST /mcp ──► THIS server (:8001)
                                                    └─ Motor ──► MongoDB Atlas
```

The agents-server's `MCP_SERVER_URL` is set to `http://localhost:8001/mcp` in its `.env`.
The Next.js app (`:3000`) is still needed for the **UI** — only the MCP data path is replaced.

---

## Key Files to Know First

1. `main.py` — FastAPI app, auth flow, JSON-RPC dispatch
2. `tools/registry.py` — tool list and name→handler mapping
3. `auth/api_key.py` — SHA-256 key validation
4. `db/connection.py` — Motor client + collection name constants
5. `tools/_utils.py` — MCP envelope builder, $lookup helpers, identifier generators
