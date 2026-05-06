# Architecture

Research Data Explorer is a governed analysis orchestrator, not just a statistics helper.

## System Shape

The core dependency direction is fixed:

```text
Interface (MCP tools) -> Application (Use Cases) -> Domain (Pure logic) <- Infrastructure (Adapters)
```

## Main Components

### Interface

- `src/rde/interface/mcp/` exposes MCP tools and workflow-facing entry points.
- Tools should validate prerequisites before invoking deeper layers.

### Application

- `src/rde/application/use_cases/` coordinates workflow steps.
- `src/rde/application/pipeline/` tracks completed phases, plan lock, and artifact gating.
- `src/rde/application/decision_logger.py` owns decision and deviation logging contracts.

### Domain

- `src/rde/domain/models/` contains pure analysis, dataset, report, and quality concepts.
- `src/rde/domain/policies/` contains hard and soft constraints.
- Domain logic should stay framework-light and reusable.

### Infrastructure

- `src/rde/infrastructure/adapters/` integrates pandas, scipy, docx export, profiling, and delegated vendor services.
- `analysis_delegator.py` decides whether work stays local or is routed to `automl-stat-mcp`.
- `automl_gateway.py` is the anti-corruption layer for vendor HTTP contracts.

## Workflow Contract

The product behavior is governed by a 13-phase pipeline.

- Phase 0-3 establish project state, schema, and concept alignment.
- Phase 4-7 generate candidates, review completeness, lock the plan, and check readiness.
- Phase 8 executes analysis and writes decision logs.
- Phase 9-12 collect, report, audit, improve, and export.

The authoritative operational contract is `.github/agent-control.yaml`.

## Architectural Guardrails

- Do not let Interface or Infrastructure inject ad hoc policy that conflicts with Domain or Application rules.
- Do not bypass phase state updates when adding new exploration paths.
- Keep audit artifacts append-only where required.
- Treat vendor delegation failures as observable artifacts, not silent fallbacks.

## Validation Sources

- `tests/test_pipeline_enforcement.py`
- `tests/test_pipeline_integration.py`
- `tests/test_plan_adherence.py`
- `tests/test_analysis_delegation.py`
- `tests/test_vendor_automl_contract_integration.py`
