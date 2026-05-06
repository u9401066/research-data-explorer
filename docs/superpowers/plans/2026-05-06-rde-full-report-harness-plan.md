# RDE Full Report Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the RDE harness so VSIX-installed Copilot, Codex, and Cline can drive each new real dataset through a complete 13-phase auditable report workflow.

**Architecture:** Keep `PipelinePhase` as the canonical source of truth and make manifest, prompts, tests, and VSIX runtime conform to it. Implement Phase 5 as a formal plan-completeness artifact in the registration flow for `0.4.5`, then enforce report and release readiness through executable tests and package guards.

**Tech Stack:** Python 3.11+, pytest, ruff, FastMCP, pandas/scipy/statsmodels, TypeScript, Vitest, VS Code extension APIs, npm/vsce, PowerShell/Bash release scripts.

---

## Work Packages

### Task 1: Canonical 13-Phase Contract

**Files:**
- Modify: `.github/agent-control.yaml`
- Modify: `tests/test_agent_control_manifest.py`
- Modify: `tests/test_pipeline_enforcement.py`
- Modify: `tests/test_docs_and_tool_sync.py`
- Modify: `src/rde/application/pipeline/__init__.py`
- Modify: `src/rde/domain/models/project.py`

- [ ] **Step 1: Write failing manifest/phase sync tests**

Add tests that load `.github/agent-control.yaml` and assert every manifest phase exists in `PipelinePhase`, decision/deviation paths end in `phase_08_execute_exploration/*.jsonl`, and user-confirmed Phase 3 blocks Phase 4 before checking missing Phase 5/6 prerequisites.

Run: `python3 -m pytest -q tests/test_agent_control_manifest.py tests/test_pipeline_enforcement.py`

Expected before implementation: failures showing old manifest phase paths and stale test expectations.

- [ ] **Step 2: Update manifest and phase confirmation behavior**

Change manifest phase names to `phase_04_creative_ideation`, `phase_05_plan_completeness_review`, `phase_06_plan_registration`, `phase_08_execute_exploration`. In `PipelineState.can_execute`, check confirmation status for completed prior gated phases before missing downstream prerequisites when the target phase is later in the workflow.

- [ ] **Step 3: Verify targeted tests**

Run: `python3 -m pytest -q tests/test_agent_control_manifest.py tests/test_pipeline_enforcement.py`

Expected after implementation: targeted tests pass.

- [ ] **Step 4: Commit**

Commit only files touched by this task:

```bash
git add .github/agent-control.yaml tests/test_agent_control_manifest.py tests/test_pipeline_enforcement.py src/rde/application/pipeline/__init__.py src/rde/domain/models/project.py
git commit -m "fix(pipeline): align canonical 13-phase contract"
```

### Task 2: Phase 4/5/6 MCP Progression

**Files:**
- Modify: `src/rde/interface/mcp/tools/plan_tools.py`
- Modify: `src/rde/interface/mcp/tools/_shared/project_context.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_plan_adherence.py`

- [ ] **Step 1: Write failing full-flow tests**

Add an MCP integration test for `init_project -> run_intake -> build_schema -> align_concept(confirm=true) -> propose_analysis_plan -> register_analysis_plan(confirm=true) -> check_readiness`. Assert Phase 4, Phase 5, and Phase 6 are completed with artifacts in their canonical directories.

Run: `python3 -m pytest -q tests/test_pipeline_integration.py::test_full_mcp_flow_completes_phase_4_5_6_contract`

Expected before implementation: failure at Phase 5/6 prerequisite or missing artifacts.

- [ ] **Step 2: Mark `propose_analysis_plan` as Phase 4 completion**

When proposal artifacts are saved, mark `PipelinePhase.CREATIVE_IDEATION` completed with `user_confirmed=True` only if the tool contract accepts confirmation or the proposal is explicitly non-locking but reviewable. For `0.4.5`, record completion as reviewable output and keep locking in Phase 6.

- [ ] **Step 3: Save Phase 5 review artifacts in `phase_05_plan_completeness_review`**

During `register_analysis_plan`, run methodology review before lock, save `analysis_plan_review.json` and `.md` to Phase 5, mark Phase 5 completed with confirmation when `confirm=true`, then save locked plan to Phase 6.

- [ ] **Step 4: Verify full planning flow**

Run: `python3 -m pytest -q tests/test_pipeline_integration.py tests/test_plan_adherence.py`

Expected after implementation: phase progression tests pass without manually injecting Phase 6 artifacts.

- [ ] **Step 5: Commit**

```bash
git add src/rde/interface/mcp/tools/plan_tools.py src/rde/interface/mcp/tools/_shared/project_context.py tests/test_pipeline_integration.py tests/test_plan_adherence.py
git commit -m "fix(plan): complete phase 4 5 6 planning gates"
```

### Task 3: Tool Inventory, Report Chain, and Python Baseline

**Files:**
- Modify: `vscode-extension/src/toolPolicy.ts`
- Modify: `tests/test_docs_and_tool_sync.py`
- Modify: `src/rde/interface/mcp/tools/report_tools.py`
- Modify: `src/rde/interface/mcp/tools/audit_tools.py`
- Modify: `src/rde/interface/mcp/tools/discovery_tools.py`
- Modify: `tests/test_report_contract.py`

- [ ] **Step 1: Write failing tool/report tests**

Assert `export_final_report` is in `RDE_MCP_TOOL_NAMES`, tool count docs match registered tools, Phase 10 source markdown uses `phase_09_collect_results`, and no stale `11-Phase` appears in MCP server instructions.

Run: `python3 -m pytest -q tests/test_docs_and_tool_sync.py tests/test_report_contract.py`

Expected before implementation: failures for missing `export_final_report`, count 31 vs 32, and stale phase paths.

- [ ] **Step 2: Update tool allowlist and report paths**

Add `export_final_report` to the VSIX allowlist and report/audit tool groups. Update report chain references to Phase 9/10/11/12 canonical names. Remove unused imports flagged by ruff.

- [ ] **Step 3: Verify Python baseline subset**

Run: `uv run ruff check .`

Expected after implementation: no ruff errors.

Run: `python3 -m pytest -q tests/test_docs_and_tool_sync.py tests/test_report_contract.py`

Expected after implementation: targeted tests pass.

- [ ] **Step 4: Commit**

```bash
git add vscode-extension/src/toolPolicy.ts tests/test_docs_and_tool_sync.py src/rde/interface/mcp/tools/report_tools.py src/rde/interface/mcp/tools/audit_tools.py src/rde/interface/mcp/tools/discovery_tools.py tests/test_report_contract.py
git commit -m "fix(report): sync tool inventory and report chain"
```

### Task 4: VSIX Bundle and Cross-Platform Scripts

**Files:**
- Modify: `vscode-extension/package.json`
- Modify: `vscode-extension/.vscodeignore`
- Modify: `vscode-extension/scripts/prepare-bundle.mjs`
- Create: `vscode-extension/scripts/check-package-contents.mjs`
- Create: `vscode-extension/scripts/install-smoke.mjs`
- Modify: `vscode-extension/src/uvManager.ts`
- Modify: `vscode-extension/test/extensionHelpers.test.ts`
- Modify: `vscode-extension/test/utils.test.ts`

- [ ] **Step 1: Write failing Vitest/package tests**

Add tests for enriched `PATH` propagation or absolute `uv` discovery behavior. Add package contents script and initially run it against an intentionally absent package to confirm it reports a clear error.

Run: `cd vscode-extension && npm run test:unit`

Expected before implementation: script missing or new tests fail.

- [ ] **Step 2: Add release scripts**

Add `sync-assets`, `sync-assets:check`, `test:unit`, `package:contents`, `test:ci`, and `test:install-smoke` to `package.json`. Ensure `test:ci` compiles, runs unit tests, packages VSIX, and checks package contents.

- [ ] **Step 3: Clean bundle root and ignore heavy artifacts**

Make `prepare-bundle.mjs` rebuild `bundled/tool` from a whitelist. Update `.vscodeignore` to exclude `.venv`, caches, prior `.vsix`, and generated test outputs.

- [ ] **Step 4: Verify extension baseline**

Run: `cd vscode-extension && npm run test:ci`

Expected after implementation: compile, Vitest, package, and package contents guard pass.

- [ ] **Step 5: Commit**

```bash
git add vscode-extension/package.json vscode-extension/package-lock.json vscode-extension/.vscodeignore vscode-extension/scripts/prepare-bundle.mjs vscode-extension/scripts/check-package-contents.mjs vscode-extension/scripts/install-smoke.mjs vscode-extension/src/uvManager.ts vscode-extension/test
git commit -m "fix(vsix): add release-grade package checks"
```

### Task 5: Three-Agent Workspace Setup Harness

**Files:**
- Create: `vscode-extension/src/workspaceSetup.ts`
- Modify: `vscode-extension/src/extension.ts`
- Modify: `vscode-extension/src/extensionHelpers.ts`
- Create: `vscode-extension/test/workspaceSetup.test.ts`
- Modify: `.codex/skills/asset-aware-mcp-harness/SKILL.md`
- Modify: `.cline/skills/asset-aware-mcp-harness/SKILL.md`
- Modify: `.claude/skills/eda-workflow/SKILL.md`

- [ ] **Step 1: Write failing idempotent setup tests**

Test that setup can copy/update Copilot `.github` assets, Codex `.codex/skills`, and Cline `.cline/skills` without deleting unrelated user files. Test `.vscode/mcp.json` detection via JSON parsing.

Run: `cd vscode-extension && npm run test:unit`

Expected before implementation: missing module or failing setup behavior.

- [ ] **Step 2: Implement setup service**

Extract setup logic from `extension.ts` into pure functions where possible. Support manifest/hash comparison and preserve existing files by writing `.rde.bak` only when a managed asset update is requested.

- [ ] **Step 3: Verify setup tests**

Run: `cd vscode-extension && npm run test:unit`

Expected after implementation: setup tests pass.

- [ ] **Step 4: Commit**

```bash
git add vscode-extension/src/workspaceSetup.ts vscode-extension/src/extension.ts vscode-extension/src/extensionHelpers.ts vscode-extension/test/workspaceSetup.test.ts .codex/skills/asset-aware-mcp-harness/SKILL.md .cline/skills/asset-aware-mcp-harness/SKILL.md .claude/skills/eda-workflow/SKILL.md
git commit -m "feat(vsix): support copilot codex cline setup"
```

### Task 6: Privacy, Dataset Registry, and Analysis Sufficiency

**Files:**
- Modify: `src/rde/domain/services/variable_classifier.py`
- Modify: `src/rde/interface/mcp/tools/discovery_tools.py`
- Modify: `src/rde/application/session.py`
- Modify: `src/rde/interface/mcp/tools/_shared/project_context.py`
- Modify: `src/rde/interface/mcp/tools/report_tools.py`
- Modify: `tests/test_pipeline_enforcement.py`
- Create: `tests/test_schema_registry_contract.py`

- [ ] **Step 1: Write failing privacy/reload tests**

Add tests that generic column names with email/phone-like values are blocked by default, PII override status is recorded, multiple loadable files require explicit selection, and project-bound dataset metadata can be reloaded after session reset.

Run: `python3 -m pytest -q tests/test_pipeline_enforcement.py tests/test_schema_registry_contract.py`

Expected before implementation: value-level PII and reload tests fail.

- [ ] **Step 2: Implement value-level PII and dataset metadata**

Add sample-value scanning with conservative regex evidence. Persist source path, loader type, dataset id, and PII override status in intake/schema artifacts. Make `ensure_dataset()` reload from metadata when possible.

- [ ] **Step 3: Count only successful analyses**

Add status fields to advanced analysis artifacts and ensure `collect_results` coverage excludes failed/unsupported analyses.

- [ ] **Step 4: Verify targeted tests**

Run: `python3 -m pytest -q tests/test_pipeline_enforcement.py tests/test_schema_registry_contract.py tests/test_pipeline_integration.py`

Expected after implementation: targeted tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/rde/domain/services/variable_classifier.py src/rde/interface/mcp/tools/discovery_tools.py src/rde/application/session.py src/rde/interface/mcp/tools/_shared/project_context.py src/rde/interface/mcp/tools/report_tools.py tests/test_pipeline_enforcement.py tests/test_schema_registry_contract.py
git commit -m "feat(intake): strengthen pii and dataset registry"
```

### Task 7: Documentation and MEM+ Sync

**Files:**
- Modify: `AGENTS.md`
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `.github/copilot-instructions.md`
- Modify: `vscode-extension/copilot-instructions.md`
- Modify: `.github/prompts/rde-phase-0-10.prompt.md`
- Modify: `vscode-extension/prompts/rde-phase-0-10.prompt.md`
- Modify: `.github/agents/eda.agent.md`
- Modify: `vscode-extension/agents/eda.agent.md`
- Modify: `memory-bank/activeContext.md`
- Modify: `memory-bank/decisionLog.md`
- Modify: `memory-bank/productContext.md`
- Modify: `memory-bank/projectBrief.md`
- Create: `memory-bank/canonicalContract.md`

- [ ] **Step 1: Write failing docs sync tests**

Extend docs sync tests to fail on execution-guiding `11-Phase`, `Phase 0-10`, `Phase 3.5`, `phase_04_plan_registration`, and `phase_06_execute_exploration` in active instructions.

Run: `python3 -m pytest -q tests/test_docs_and_tool_sync.py`

Expected before implementation: stale instruction failures.

- [ ] **Step 2: Update instructions and memory**

Rewrite active agent-facing docs to use Phase 0-12, canonical artifact paths, report chain, quick-explore contract, and MEM+ handoff fields.

- [ ] **Step 3: Verify docs sync**

Run: `python3 -m pytest -q tests/test_docs_and_tool_sync.py`

Expected after implementation: docs sync tests pass.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md SPEC.md README.md README.zh-TW.md .github/copilot-instructions.md vscode-extension/copilot-instructions.md .github/prompts/rde-phase-0-10.prompt.md vscode-extension/prompts/rde-phase-0-10.prompt.md .github/agents/eda.agent.md vscode-extension/agents/eda.agent.md memory-bank
git commit -m "docs: sync 13-phase agent harness memory"
```

### Task 8: Release Harness, Version, Verification, Push, Tag

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/rde/__init__.py`
- Modify: `vscode-extension/package.json`
- Modify: `vscode-extension/package-lock.json`
- Modify: `CHANGELOG.md`
- Create: `scripts/get_version.py`
- Create: `scripts/audit_release_harness.py`
- Create: `scripts/audit_release_artifacts.py`
- Modify: `.clinerules/40-release.md`
- Modify: `.clinerules/workflows/full-check.md`
- Modify: `.clinerules/workflows/release-publish.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/publish-extension.yml`

- [ ] **Step 1: Write failing release tests**

Extend release consistency tests to check `pyproject.toml`, `src/rde/__init__.py`, `vscode-extension/package.json`, `package-lock.json`, changelog coverage, and strict semver helper.

Run: `python3 -m pytest -q tests/test_release_consistency.py`

Expected before implementation: missing `__version__` and missing scripts fail.

- [ ] **Step 2: Implement release scripts and bump to 0.4.5**

Add strict version reader, harness audit, package artifact audit. Sync versions to `0.4.5`. Update changelog with a dated `0.4.5` section.

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
python3 -m pytest -q
cd vscode-extension && npm run test:ci
cd ..
python3 scripts/audit_release_harness.py
python3 scripts/audit_release_artifacts.py
git diff --check
```

Expected after implementation: all commands pass, or any failing external smoke is documented before tag.

- [ ] **Step 4: Commit, push, tag**

```bash
git add pyproject.toml src/rde/__init__.py vscode-extension/package.json vscode-extension/package-lock.json CHANGELOG.md scripts/get_version.py scripts/audit_release_harness.py scripts/audit_release_artifacts.py .clinerules .github/workflows
git commit -m "release: prepare 0.4.5"
git push origin HEAD
git tag -a v0.4.5 -m "Release v0.4.5"
git push origin v0.4.5
```

## Execution Notes

- Stage only files intentionally touched by each task. The current worktree has pre-existing untracked files; do not sweep them into commits.
- Use subagents for independent tasks with disjoint write sets after Task 1 stabilizes the canonical contract.
- Do not tag until Python tests, extension `test:ci`, package contents, release audit scripts, and git diff hygiene are clean.
