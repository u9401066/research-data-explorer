# EDA Autoresearch Branch Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Phase 8 YOLO exploration branch loop that lets RDE run auditable exploratory branches while keeping locked primary analyses protected.

**Architecture:** Add a branch domain model, deterministic evaluator, MCP branch tools, Phase 8 artifacts, and VSIX/tool policy sync. Branch state is reconstructed from append-only JSONL events; promotion writes an amendment artifact instead of rewriting `analysis_plan.yaml`.

**Tech Stack:** Python dataclasses, FastMCP tool registration, existing `ArtifactStore`, existing session/project helpers, pytest, TypeScript VSIX tool policy tests.

---

### Task 1: Branch Domain Model And Evaluator

**Files:**
- Create: `src/rde/domain/models/exploration_branch.py`
- Create: `src/rde/domain/services/exploration_branch_evaluator.py`
- Test: `tests/test_exploration_branch_loop.py`

- [ ] **Step 1: Write failing model/evaluator tests**

Add tests that create branch and experiment payloads, then assert evaluation blocks crashed branches, recommends discard for low evidence, and recommends `promote_candidate` for completed high-value branch evidence.

- [ ] **Step 2: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py`

Expected: FAIL because the model and evaluator modules do not exist.

- [ ] **Step 3: Implement dataclasses and evaluator**

Add branch status enums, event dataclasses, and `ExplorationBranchEvaluator.evaluate(branch, experiments)` returning a dict with component scores, overall score, recommendation, and promotion gate fields.

- [ ] **Step 4: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py`

Expected: PASS for evaluator tests.

### Task 2: MCP Branch Tools

**Files:**
- Create: `src/rde/interface/mcp/tools/branch_tools.py`
- Modify: `src/rde/interface/mcp/server.py`
- Test: `tests/test_exploration_branch_loop.py`

- [ ] **Step 1: Write failing MCP tests**

Add tests for `open_exploration_branch`, `run_branch_experiment`, `evaluate_branch`, `promote_branch_to_plan_amendment`, `discard_branch`, and `get_exploration_board` using FastMCP calls.

- [ ] **Step 2: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py`

Expected: FAIL because the MCP tools are not registered.

- [ ] **Step 3: Implement branch tools**

Implement append-only JSONL helpers, branch state reconstruction, branch-scoped result artifact saving, promotion gate enforcement, and board rendering.

- [ ] **Step 4: Register tools**

Import and call `register_branch_tools(server)` in `src/rde/interface/mcp/server.py`.

- [ ] **Step 5: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py`

Expected: PASS.

### Task 3: Suggestions And Control Manifest

**Files:**
- Modify: `.github/agent-control.yaml`
- Modify: `src/rde/interface/mcp/tools/branch_tools.py`
- Test: `tests/test_exploration_branch_loop.py`
- Test: `tests/test_docs_and_tool_sync.py`

- [ ] **Step 1: Write failing suggestion/control tests**

Assert `suggest_branch_experiments()` emits at least sensitivity/adjusted-model/visualization candidates from a locked plan and schema, and assert the control manifest lists branch tools and promotion gate semantics.

- [ ] **Step 2: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py tests/test_docs_and_tool_sync.py`

Expected: FAIL on missing branch control entries or suggestions.

- [ ] **Step 3: Implement suggestion heuristics**

Use schema variables, locked plan entries, and existing artifacts to generate bounded suggestions. Keep suggestions as branch candidates only; do not auto-open them.

- [ ] **Step 4: Update control manifest**

Add branch loop controls under Phase 8, tool names, artifact names, and promotion gate rules.

- [ ] **Step 5: Run targeted tests**

Run: `python3 -m pytest -q tests/test_exploration_branch_loop.py tests/test_docs_and_tool_sync.py`

Expected: PASS.

### Task 4: VSIX Tool Policy Sync

**Files:**
- Modify: `vscode-extension/src/toolPolicy.ts`
- Modify: `vscode-extension/test/toolPolicy.test.ts`
- Modify: `vscode-extension/agents/eda.agent.md`
- Modify: `vscode-extension/prompts/rde-13-phase.prompt.md`

- [ ] **Step 1: Write failing VSIX tests**

Assert branch tools are allowed in analysis/advanced/pipeline workflows and promotion wording requires audit gate confirmation.

- [ ] **Step 2: Run VSIX tests**

Run: `npm test -- test/toolPolicy.test.ts` from `vscode-extension/`

Expected: FAIL because new branch tools are not in policy.

- [ ] **Step 3: Update policy and prompts**

Add branch tools to `RDE_MCP_TOOL_NAMES` and appropriate groups. Update agent/prompt wording to say autonomous branches are allowed but promotion requires audit gate confirmation.

- [ ] **Step 4: Run VSIX tests**

Run: `npm test -- test/toolPolicy.test.ts` from `vscode-extension/`

Expected: PASS.

### Task 5: Full Verification

**Files:**
- No new implementation files.

- [ ] **Step 1: Run full Python suite**

Run: `python3 -m pytest -q`

Expected: PASS.

- [ ] **Step 2: Run VSIX suite**

Run: `npm test` from `vscode-extension/`

Expected: PASS.

- [ ] **Step 3: Run asset sync check**

Run: `npm run sync-assets:check` from `vscode-extension/`

Expected: PASS.

- [ ] **Step 4: Run diff hygiene**

Run: `git diff --check`

Expected: no whitespace errors; LF-to-CRLF warnings are acceptable in this workspace.
