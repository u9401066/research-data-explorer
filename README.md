# Research Data Explorer

Research Data Explorer (RDE) is an 11-phase auditable EDA pipeline built as an MCP server for VS Code agents.

It is designed to constrain analysis behavior instead of letting an agent improvise freely. The repository combines:

- phase gates and artifact gates
- explicit user confirmation for concept alignment and plan locking
- append-only decision and deviation logs
- hard and soft statistical constraints
- delegated heavy analysis through automl-stat-mcp

繁體中文完整說明請見 [README.zh-TW.md](README.zh-TW.md).

## What This Repo Solves

Traditional exploratory analysis is often hard to review because method changes are not logged, intermediate decisions are not preserved, and artifacts are scattered.

RDE addresses that by enforcing:

1. Project initialization before analysis
2. Intake validation before loading data
3. Schema registration before planning
4. User-confirmed concept alignment before plan registration
5. User-confirmed plan lock before Phase 6 execution
6. Audit-ready artifacts for every major phase

The core governance documents are:

- [AGENTS.md](AGENTS.md)
- [.github/copilot-instructions.md](.github/copilot-instructions.md)
- [SPEC.md](SPEC.md)
- [CONSTITUTION.md](CONSTITUTION.md)
- [.github/agent-control.yaml](.github/agent-control.yaml)

Editor and collaboration support files are also provided:

- [.vscode/settings.json](.vscode/settings.json)
- [.github/agents](.github/agents)
- [.github/prompts](.github/prompts)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

## Architecture

RDE follows a DDD layout:

```text
Interface (MCP tools) -> Application (Use Cases) -> Domain (Pure logic) <- Infrastructure (Adapters)
```

Important implementation entry points:

- MCP server entry: [src/rde/__main__.py](src/rde/__main__.py)
- MCP registration: [src/rde/interface/mcp/server.py](src/rde/interface/mcp/server.py)
- Pipeline state machine: [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py)
- Decision logging: [src/rde/application/decision_logger.py](src/rde/application/decision_logger.py)
- Advanced analysis delegation: [src/rde/infrastructure/adapters/analysis_delegator.py](src/rde/infrastructure/adapters/analysis_delegator.py)
- Vendor gateway: [src/rde/infrastructure/adapters/automl_gateway.py](src/rde/infrastructure/adapters/automl_gateway.py)

## 11-Phase Constrained Workflow

The intended execution order is:

1. Phase 0: `init_project`
2. Phase 1: `run_intake`
3. Phase 2: `build_schema`, `profile_dataset`
4. Phase 3: `align_concept(confirm=true)`
5. Phase 4: `register_analysis_plan(confirm=true)`
6. Phase 5: `check_readiness`
7. Phase 6: analysis tools such as `compare_groups`, `correlation_matrix`, `run_advanced_analysis`
8. Phase 7: `collect_results`
9. Phase 8: `assemble_report`
10. Phase 9: `run_audit`
11. Phase 10: `auto_improve`, `export_handoff`, `verify_audit_trail`

### Hard Constraints

The workflow is not advisory only. These constraints are enforced by code and pipeline state:

- H-001: file size must be below 500 MB
- H-002: file format must be on the whitelist
- H-003: minimum sample size for statistics
- H-004: PII detection blocks loading by default
- H-005: report integrity checks before final reporting
- H-006: output sanitization
- H-007: Phase 6 requires a locked plan
- H-008: artifact gate between phases
- H-009: decision logging during exploration
- H-010: append-only decision and deviation logs

### Soft Constraints

The agent also surfaces methodological reminders, including:

- normality and nonparametric fallback
- multiple-comparison correction
- missingness pattern review
- collinearity warnings
- effect size interpretation
- power and sensitivity analysis hints

## How Copilot Is Actually Constrained

Copilot is constrained through repository behavior, not just prompt text.

In practice, this repo limits an agent in four layers:

1. Policy layer
   - Rules are described in [AGENTS.md](AGENTS.md), [.github/copilot-instructions.md](.github/copilot-instructions.md), and [CONSTITUTION.md](CONSTITUTION.md)
2. Pipeline layer
   - [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py) enforces prerequisites, plan lock, and artifact gates
3. Tool layer
   - MCP tools in [src/rde/interface/mcp/tools](src/rde/interface/mcp/tools) validate readiness before each operation
4. Audit layer
   - [src/rde/application/decision_logger.py](src/rde/application/decision_logger.py) keeps append-only logs for decisions and deviations

This means an agent cannot legitimately execute a Phase 6 analysis path without the expected upstream artifacts and confirmations.

## Using MCP Effectively

### 1. Start the RDE MCP server

Install dependencies first:

```bash
python3 -m pip install -e .
```

Run the server:

```bash
python3 -m rde
```

### 2. Start automl-stat-mcp when you need delegated heavy analysis

```bash
cd vendor/automl-stat-mcp
docker compose --profile ml up -d
```

This enables delegated analysis such as:

- propensity score workflows
- survival analysis
- ROC/AUC analysis
- power analysis endpoints
- AutoML training jobs

### 3. Suggested VS Code MCP configuration

```json
{
  "servers": {
    "research-data-explorer": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "rde"]
    },
    "automl-stat-mcp": {
      "type": "sse",
      "url": "http://localhost:8002/sse"
    }
  }
}
```

### 4. Best practice prompt pattern

If you want the agent to stay inside the governed workflow, ask for work in phase-oriented terms. For example:

```text
I have a CSV file. Please use the full 11-phase auditable workflow.
Do not skip concept alignment or plan lock.
Use run_advanced_analysis only when Phase 5 is complete.
Log deviations if you need to change the plan.
```

## Recommended Operating Sequence

For a fully constrained run:

1. `init_project`
2. `run_intake`
3. `build_schema`
4. `profile_dataset`
5. `align_concept(confirm=true)`
6. `register_analysis_plan(confirm=true)`
7. `check_readiness`
8. phase-6 analysis tools
9. `collect_results`
10. `assemble_report`
11. `run_audit`
12. `auto_improve`
13. `export_handoff`
14. `verify_audit_trail`

## Validation Status

The current repository has been validated in three ways:

1. Unit and integration tests
   - Run with `python3 -m pytest -q`
2. Live vendor contract tests
   - [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)
3. End-to-end dry runs using repository sample data
   - minimal full-gate dry run artifacts under [data/projects/e45af361](data/projects/e45af361)
   - heart disease dry run artifacts under [data/projects/12aafc56](data/projects/12aafc56)

Relevant tests include:

- [tests/test_pipeline_integration.py](tests/test_pipeline_integration.py)
- [tests/test_analysis_delegation.py](tests/test_analysis_delegation.py)
- [tests/test_advanced_analysis_formatting.py](tests/test_advanced_analysis_formatting.py)
- [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)

## Known Limitations

At the time of writing:

1. `run_advanced_analysis` can delegate successfully when vendor contracts match the request shape
2. Some payloads, especially direct model and AutoML submissions on specific datasets, may still fall back if vendor endpoints return HTTP 422
3. The fallback is preserved as an artifact so auditability is not lost

Example fallback artifact:

- [data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json](data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json)

## Repository Layout

```text
src/rde/                         Core application
tests/                           Regression and contract tests
vendor/automl-stat-mcp/          Delegated heavy-analysis engine
data/projects/                   Per-project outputs and artifacts
memory-bank/                     Project memory documents
```

## Development

Install dev dependencies and run tests:

```bash
python3 -m pip install -e .[dev]
python3 -m pytest -q
```

If you change workflow governance, update these together:

1. [SPEC.md](SPEC.md)
2. [CONSTITUTION.md](CONSTITUTION.md)
3. [AGENTS.md](AGENTS.md)
4. [.github/copilot-instructions.md](.github/copilot-instructions.md)
5. implementation and tests

If you use VS Code agent mode, keep [.vscode/settings.json](.vscode/settings.json), [.github/agents](.github/agents), and [.github/prompts](.github/prompts) aligned with those governance files.

## Extension Release

The VS Code extension release path now includes:

1. extension lint, test, and VSIX packaging in [.github/workflows/ci.yml](.github/workflows/ci.yml)
2. tag-driven publish automation in [.github/workflows/publish-extension.yml](.github/workflows/publish-extension.yml)
3. Apache-2.0 license files in [LICENSE](LICENSE) and [vscode-extension/LICENSE.txt](vscode-extension/LICENSE.txt)

Required GitHub secrets for automated publishing:

- `VSCE_PAT` for Visual Studio Marketplace
- `OVSX_PAT` for Open VSX
