# MCP v2 integration

RDE uses the **official Python MCP SDK 2.2+**, not the separate FastMCP product.
The migration supports old hosts and 2026-era hosts through one stdio server.

## Agent capabilities

- `get_workflow_contract` returns server-derived phase state through SDK v2
  `Resolve`. The injected contract is absent from the model's input schema and
  cannot be forged by passing a same-named argument.
- `rde://capabilities` lists every tool's effect/gate metadata and SDK version.
- `rde://projects/{project_id}/workflow` reads a project workflow without exposing
  raw patient rows or arbitrary filesystem access.
- `governed_research` is a reusable prompt for moving from a clinical question to
  reproducible analysis, interpretation, audit and reporting.
- Every tool advertises effect annotations and a structured output schema.
  Existing Markdown stays available to older clients. Formatted tool failures
  now set MCP `isError`; successful execution is not a claim of publication readiness.

## Runtime safety

SDK v2 runs synchronous handlers in worker threads. RDE's registry is currently
process-global, so all tool bodies share a reentrant lock. This prevents concurrent
tools from interleaving active-project state and append-only logs without blocking
the event loop. It is not a multi-user HTTP isolation mechanism. Use one local
process/workspace; do not expose this local-filesystem service publicly.

The agent remains the research collaborator: propose hypotheses and alternative
methods freely, then record what was actually run. Plan approval and promotion
govern conclusions, not creative reasoning. The durable autoresearch queue is
host-driven; it is **not** the SDK's unimplemented MCP Tasks extension.

## Verification

```shell
uv run python scripts/audit_mcp_surface.py
uv run pytest tests/test_mcp_v2.py tests/test_docs_and_tool_sync.py
uv run python scripts/codex_rde_smoke.py --list-tools-only
```

The inventory checks every live tool against reviewed metadata and the VSIX
manifest. Tests cover modern/legacy clients, real stdio, error flags, resolver
injection, resources, prompt discovery and concurrent tool calls. The existing
legacy stdio smoke remains intentional backward-compatibility coverage.

References: [SDK migration](https://py.sdk.modelcontextprotocol.io/migration/),
[resolver dependencies](https://py.sdk.modelcontextprotocol.io/handlers/dependencies/),
[SDK releases](https://github.com/modelcontextprotocol/python-sdk/releases).
