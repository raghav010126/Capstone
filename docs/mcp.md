# MediShield as an MCP server

MediShield exposes its read-only case and policy tools over the [Model Context Protocol](https://modelcontextprotocol.io), so
Claude Code, Claude Desktop or any MCP client can use them. The tools have **the same role permissions as the app**: the
role comes only from your MediShield sign-in token, and each tool calls the REST API's own permission and visibility checks.

| Where | URL / command | Transport |
|---|---|---|
| AWS deployment | `https://<site>/api/mcp` (CloudFront → API Lambda) | Streamable HTTP, stateless, JSON responses |
| Local API (`make api`) | `http://localhost:8100/mcp` | same |
| Local process (Claude Desktop) | `python -m medishield.mcp_server` | stdio |

On AWS it runs inside the existing API Lambda, so it adds no resources and no idle cost.

## Tools

| Tool | What it returns | Permission (same as the app) |
|---|---|---|
| `check_coverage(cpt_code, plan)` | `NOT_COVERED` / `CONDITIONAL` (prior authorisation) / `NOT_LISTED` / `COVERED`, decided by exact match in the plan's parsed exclusion table (table 4.1), with the clause and page; plus the plan's in-network Schedule of Benefits row(s) for that kind of service. Deterministic: **no model call** | `policy:ask` (every role) |
| `get_case(case_id)` | status, automated and final decision, confidence, amount, justification, and each document's decision, rule and reasons | `case:read`; submitters only their own cases |
| `list_cases(status=None, limit=20)` | recent cases, newest first (like `GET /cases`) | `case:read`; submitters only their own cases |
| `review_queue()` | cases waiting for a human, most urgent first (like `GET /review/queue`) | `review:queue` (reviewer, senior reviewer, auditor, admin) |
| `case_status(case_id)` | the status only (one cheap read, for polling) | `case:read`; submitters only their own cases |
| `ask_assistant(question, conversation_id=None)` | the role-aware assistant's answer with `[n]` citations and its sources, exactly as `POST /chat` (in-process locally, AgentCore runtime on AWS). Pass back `conversation_id` for follow-ups | any signed-in user; the assistant refuses topics outside the role |

A case another submitter owns gets the same answer as a case that does not exist (`case … not found or not visible to you`),
so case ids cannot be probed. A missing permission returns a tool error such as
`permission denied: role 'submitter' lacks permission 'review:queue'`. No tool can approve, override or change anything.

## 1. Get a token

The tools use the same tokens as the web app. Sign in with your MediShield account:

```bash
curl -s https://<site>/api/auth/login -H 'content-type: application/json' \
  -d '{"username": "reviewer", "password": "..."}' | jq -r .access_token
```

(Locally: `http://localhost:8100/auth/login`; demo passwords are `<username>-demo` when `MEDISHIELD_DEMO_USERS=1`.) Tokens
expire after `JWT_TTL_MINUTES` (default 480, i.e. 8 hours); then sign in again and update the client's header.

## 2. Connect a client

**Claude Code** (remote, HTTP):

```bash
claude mcp add --transport http medishield https://<site>/api/mcp --header "Authorization: Bearer <token>"
# local API: claude mcp add --transport http medishield http://localhost:8100/mcp --header "Authorization: Bearer <token>"
```

**Claude Desktop, remote** (through the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge; needs Node). In
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "medishield": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<site>/api/mcp", "--header", "Authorization:${MEDISHIELD_AUTH}"],
      "env": { "MEDISHIELD_AUTH": "Bearer <token>" }
    }
  }
}
```

**Claude Desktop, local process** (stdio, against your local install: the same database, policies and assistant as
`make api`):

```json
{
  "mcpServers": {
    "medishield-local": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/medishield-capstone", "python", "-m", "medishield.mcp_server"],
      "env": { "MEDISHIELD_USER": "reviewer", "MEDISHIELD_PASSWORD": "reviewer-demo", "MEDISHIELD_API_URL": "http://localhost:8100" }
    }
  }
}
```

The local process authenticates with `MEDISHIELD_TOKEN=<token>`, or with `MEDISHIELD_USER` + `MEDISHIELD_PASSWORD`, which
signs in at `MEDISHIELD_API_URL` (default `http://localhost:8100`) and signs in again when the token expires. The token is
verified locally, so it must come from an API that shares this machine's `JWT_SECRET` and database. For the AWS deployment,
use the remote options above.

**Any client / curl.** Each POST is self-contained: no session id, no SSE.

```bash
curl -s https://<site>/api/mcp -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' -H 'mcp-protocol-version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_coverage","arguments":{"cpt_code":"17000","plan":"gold"}}}'
```

## How it runs

- `backend/src/medishield/mcp_server/`: `tools.py` (server and tools), `coverage.py` (deterministic coverage), `http.py`
  (`/mcp` endpoint), `__main__.py` (stdio).
- **Stateless Streamable HTTP with JSON responses.** The API Lambda runs FastAPI through Mangum with `lifespan="off"`, so nothing
  long-running can own the SDK's session manager. Each POST gets its own stateless session manager, entered and left inside
  the request: one JSON-RPC message in, one JSON response out, nothing kept between invocations. `GET` (the optional SSE
  stream) and `DELETE` (session end) answer `405`, as the spec allows; an open SSE stream would otherwise hold the Lambda
  until its timeout.
- The MCP SDK is imported on the first `/mcp` request, so the API's cold start does not pay for it. `check_coverage` reads the
  cached parsed policies directly and never loads the search models.

## Security notes

- **Same RBAC.** The token is verified by `api.security.principal_from_token`, as for every REST call: signature, expiry, and
  the user must still exist and be active. Missing or invalid tokens get `401` with `WWW-Authenticate: Bearer` before any MCP
  processing. Tools check permissions with `api.security.require` and case visibility with `api.deps.get_case`. Tool arguments
  cannot change the role.
- **Audit.** Every tool call, including denied ones, appends `mcp_tool_called` to the hash-chained audit log with the tool name
  and case id only (no arguments, questions or results). Assistant refusals also write `chat_blocked`, as in the app.
  `GET /audit/verify` covers these events.
- **Rate limit and spend.** `ask_assistant` shares the per-user chat rate limit and the model-spend caps with `POST /chat`. The
  other tools make no model calls.
- **Token handling.** A token is a bearer credential for your account until it expires: keep client config files private, and
  prefer the stdio `MEDISHIELD_USER`/`MEDISHIELD_PASSWORD` form or short `JWT_TTL_MINUTES` on shared machines. Disabling a user
  stops their token at the next call.
- **Where results go.** Tool results go to your MCP client and its model. They contain exactly what your role can already see
  in the app (for example case justifications), and nothing more.
- **Not supported (by design, for a stateless Lambda):** OAuth discovery (use a static bearer token), server-to-client
  requests (sampling, elicitation), and streamed progress notifications.
