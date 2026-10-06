"""MediShield as an MCP server, with the app's role permissions (docs/mcp.md).

* ``tools``     the MCP server and its tools (access enforced with the REST API's own functions; every call audited)
* ``coverage``  deterministic coverage answers from the parsed exclusion table (no model call)
* ``http``      ``/mcp`` on the API: Streamable HTTP, stateless, JSON responses, ``Authorization: Bearer <MediShield JWT>``
* ``__main__``  ``python -m medishield.mcp_server``: the same tools over stdio, for Claude Desktop on a local install

Nothing is imported here, so mounting ``/mcp`` does not load the MCP SDK until the first MCP request.
"""
