# Typed research transitions through the existing RDE MCP

`get_workflow_contract` now includes `canvas_contract` (`rde-canvas-v1`). The
source file is `src/rde/interface/mcp/canvas_contract.json`; hosts synchronize
that complete definition and check the live server before enabling operations.

Node outputs and transition inputs model compatible ports, inspired by
[Langflow components](https://docs.langflow.org/concepts-components). Research
adds explicit planning/execution facts. `validate_workflow_connection` checks
source type, transition and every explicit boolean fact. Unknown inputs and
missing facts fail; incompatibility returns `allowed=false` with a code.

This is a topology check, **not authorization**. RDE does not know a host's
accounts or canvas IDs. Hosts must derive identity, full ancestry, version and
approval from persisted state, reject stale requests and run normal source,
approval and execution gates. Directions inherit ancestry; they cannot reset
an analysis to prospective design. Reading an earlier design is navigation,
not a new successor edge. New analyses after results require explicit revision
or appended-question drafts and fresh approval. Historical execution edges
remain provenance, not editable drawing instructions.

The native `draft_sample_size_plan` also refuses an already locked or executed
analysis project. An independent future recruitment study needs its own design
project. Existing reviewed designs remain readable. No additional MCP server,
database, UI framework or Langflow runtime is required.

Tests exercise direct/indirect forbidden connections, explicit prerequisites,
strict boolean inputs, live MCP discovery/validation, and native sample-size
blocking while retaining the previous design.
