# Research Data Explorer

Research Data Explorer (RDE) is an 11-phase auditable EDA pipeline built as an MCP server for VS Code agents.

It is designed to constrain analysis behavior instead of letting an agent improvise freely. The repository combines:

- phase gates and artifact gates
- explicit user confirmation for concept alignment and plan locking
- append-only decision and deviation logs
- hard and soft statistical constraints
- delegated heavy analysis through automl-stat-mcp

More honestly, the positioning is this:

- standard, template-friendly analysis families can be brought into the governed workflow
- specialized methods that depend heavily on domain context or study design will often still require manual execution, custom vendor integration, or purpose-built code
- RDE is therefore not a universal “run every statistical method automatically” MCP
- and if the goal is only generic one-shot auto-analysis, other more general-purpose MCP or agent tools already exist in the ecosystem

RDE's value is not maximum method coverage. Its value is putting a narrower but trusted method pool inside an auditable, reviewable, handoff-ready workflow.

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
5. Phase 3.5: `propose_analysis_plan()`
6. Phase 4: `register_analysis_plan(confirm=true)`
7. Phase 5: `check_readiness`
8. Phase 6: analysis tools such as `compare_groups`, `correlation_matrix`, `run_advanced_analysis`
9. Phase 7: `collect_results`
10. Phase 8: `assemble_report`
11. Phase 9: `run_audit`
12. Phase 10: `auto_improve`, `export_handoff`, `verify_audit_trail`

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
6. `propose_analysis_plan()`
7. `register_analysis_plan(confirm=true)`
8. `check_readiness`
9. phase-6 analysis tools
10. `collect_results`
11. `assemble_report`
12. `run_audit`
13. `auto_improve`
14. `export_handoff`
15. `verify_audit_trail`

## Why Phase 3 and 4 Matter

This is the point where a research question becomes an auditable analysis contract.

`align_concept(confirm=true)` should at least pin down:

- the unit of analysis: patient, visit, specimen, procedure, or operator
- the exposure or grouping variable
- the primary and secondary outcomes
- the outcome type: continuous, binary, categorical, time-to-event, or repeated-measures
- adjustment covariates, subgroup variables, exclusion fields, and time-axis columns

`register_analysis_plan(confirm=true)` should then lock the allowed analysis families, variables, and fallback rules rather than only storing a loose checklist.

If you want the agent to drive EDA more autonomously, the repo now provides `propose_analysis_plan()` between Phase 3 and Phase 4. It no longer behaves as a bare greedy sorter only. It now produces a draft candidate set, runs an internal methodology review / repair pass, expands beyond the initial budget when that preserves promising EDA branches, and then emits a reviewed blueprint plus a visualization bundle and Phase 6 execution schedule that can be passed into `register_analysis_plan()`. The point is not to bypass human confirmation; the point is to make autonomous ideation itself auditable, repairable, and lockable.

`register_analysis_plan(confirm=true)` now also performs a methodology gate before lock. If the submitted plan is obviously under-scoped for the detected data structure, for example trying to stop after only a couple of analyses even though the dataset supports grouped comparisons, association screening, and adjusted modeling, Phase 4 now first auto-expands the plan with optional exploratory branches. Only if the reviewed plan is still too thin does it block the lock and push the agent back toward `propose_analysis_plan()`, unless `allow_methodology_override=true` is set explicitly. When the plan is locked, the repo also persists an execution schedule artifact so Phase 6 can follow the reviewed ordering instead of improvising from scratch.

Typical analysis options to place in the Phase 4 plan:

| Analysis goal | Typical column structure | Recommended tool / method | What to lock in Phase 4 |
| --- | --- | --- | --- |
| Baseline description / Table 1 | one grouping column + multiple baseline variables | `generate_table_one` | grouping variable, included variables, overall/group display |
| Two-group or multi-group comparison | one group + one or more outcomes | `compare_groups`; with t-test / Mann-Whitney U / ANOVA / Kruskal-Wallis / chi-square / Fisher chosen by data type | group, outcomes, primary comparisons, multiple-comparison correction |
| Single-variable profiling | one variable | `analyze_variable` | variable name and whether it is descriptive or pre-inference screening |
| Correlation / collinearity review | multiple continuous or mixed variables | `correlation_matrix` with VIF warnings | variable set and whether high-collinearity variables should be screened out |
| Repeated-measures / before-after analysis | subject id + time/repeated-measure field + outcome | `run_repeated_measures` | subject id, time variable, primary outcome, paired/repeated setting |
| Adjusted or predictive modeling | outcome + exposure + covariates | `run_advanced_analysis` | outcome, primary predictors, adjustment set, model family such as logistic / linear / Cox / ROC / power |
| Learning-curve or operator performance analysis | operator + trial order + success / error | `run_advanced_analysis(analysis_type="learning_curve_cusum")` | operator, trial order, success definition, target success rate |
| Sensitivity or subgroup analysis | primary-analysis fields + subgroup or alternate coding | follow-up `compare_groups` or `run_advanced_analysis` | subgroup definitions, alternate variable definitions, required sensitivity checks |
| Visualization outputs | outcome + optional group / time | `create_visualization` | plot type, variables, grouping, filename convention |

Analysis ideation usually needs more than one layer of reasoning. A practical order is: frame the question first, inspect the data structure second, and only then choose methods and figures.

| Thinking layer | First question | Typical exit | RDE tools |
| --- | --- | --- | --- |
| Problem framing | Am I describing a variable, comparing groups, exploring relationships, or making adjusted/predictive claims? | Separate descriptive, comparative, associative, and modeling goals first | `build_schema`, `profile_dataset`, `align_concept` |
| Structure check | Is there a grouping variable, a time axis, repeated measures, or a clear outcome? Is the outcome continuous, binary, categorical, or time-to-event? | No comparator usually stays univariable; group leads to comparison; multivariable without a primary outcome leads to correlation; covariates or prediction needs modeling | `align_concept`, `check_readiness` |
| Method selection | Is the question “what does this look like”, “is A different from B”, “do X and Y move together”, or “does the claim hold after adjustment”? | `analyze_variable`, `compare_groups`, `correlation_matrix`, `run_repeated_measures`, `run_advanced_analysis` | `register_analysis_plan` |
| Figure planning | Which figure best supports the question: distribution, difference, relationship, or trajectory? | histogram / boxplot / violin / scatter / heatmap / line / paired / bar | `create_visualization` |
| Governance lock | What is primary vs secondary, and what are alpha, missing-data, fallback, and required outputs? | Build an auditable contract before Phase 6 | `register_analysis_plan(confirm=true)`, `log_deviation` |

A quick rule of thumb:

- Distribution checks only: one variable, no comparator, no time structure, no adjustment need, and the real goal is to understand shape, missingness, or outliers.
- Group comparison: there is a clear group or exposure and the question is whether A differs from B.
- Correlation: there is no treatment-outcome hierarchy yet and the goal is association structure or collinearity review.
- Advanced modeling: you need confounder adjustment, prediction, time-to-event, repeated structure, power/ROC/propensity, or sequence problems such as learning-curve CUSUM.

### Should figures be planned in Phase 4?

Yes. `create_visualization` currently supports `histogram`, `boxplot`, `scatter`, `bar`, `violin`, `heatmap`, `line`, and `paired`.

In practice, plan figure bundles rather than a single isolated chart:

- single continuous variable: `histogram` + `boxplot`
- group difference: `boxplot` or `violin`, and `bar` for categorical proportions
- multivariable relationship: `scatter` + `heatmap`
- time or before-after structure: `line` or `paired`
- if you want a simple “4-plot” concept, define it as a small figure bundle in the plan rather than expecting one built-in command to create all four views

In addition to analysis families, the plan should explicitly lock:

- primary and secondary endpoints
- alpha and multiple-testing strategy
- missing-data strategy
- fallback rules for non-normality or imbalance
- required tables, figures, and sensitivity outputs

Three concrete examples:

1. Distribution only
Question: I only want to understand the distribution, skewness, and outliers of creatinine.
Suggested path: `analyze_variable`, then `histogram` and `boxplot`.
At this stage you do not need `compare_groups` or `run_advanced_analysis`.

2. Two-group clinical comparison
Question: Are lactate and in-hospital death different between sepsis and non-sepsis groups?
Suggested path: `generate_table_one` + `compare_groups`. If age, SOFA, or other confounders must be adjusted for, escalate to `run_advanced_analysis`.
Figures: `boxplot` or `violin` for lactate, `bar` for mortality.

3. Operator learning curve
Question: Does success improve over trial order, and where does performance stabilize?
Suggested path: this is not a plain group comparison; Phase 4 should explicitly register `run_advanced_analysis(analysis_type="learning_curve_cusum")`.
Figures: `line` for the raw trend, with the formal evidence coming from the CUSUM artifact.

Without these two phases, a fully governed Phase 6 execution path is not really established. If the method changes later, the deviation should be logged explicitly.

### When agents or subagents help

They can help with ideation, but they should not replace the governed workflow.

- `ask` or `Explore`: broaden candidate questions and analysis directions
- `architect`: translate those candidates into a Phase 3-4 contract
- `orchestrator`: split the work into profiling, methods, figures, and audit tasks
- `eda`: execute inside the governed pipeline after Phase 3-4 confirmation
- `audit`: review plan adherence and artifact completeness afterward

Switching agents or using a stronger reasoning model can improve the breadth of ideas, but it does not replace concept alignment, plan lock, or readiness checks. A robust pattern is to brainstorm broadly first, then write the approved subset back into the locked analysis plan.

### Method Coverage and Why the Agent Does Not Run Everything

RDE is not designed to exhaustively run every statistical method in the library. It is designed to select an appropriate method from a governed method pool.

At the moment, method coverage is best understood in layers:

- the Phase 6 user-facing layer exposes 6 main analysis entrypoints plus 1 visualization entrypoint: `compare_groups`, `analyze_variable`, `correlation_matrix`, `generate_table_one`, `run_advanced_analysis`, `run_repeated_measures`, and `create_visualization`
- the Phase 4 analysis plan schema currently allows 16 analysis types
- the local Scipy engine declares 16 capabilities in the manifest
- the delegated automl layer declares 10 advanced capabilities in the manifest

These numbers should not be added together directly because they represent different layers: user entrypoints, plan types, local engine capabilities, and delegated capabilities. There is overlap, aliasing, and abstraction between them.

More importantly, the agent does not automatically run every possible method because:

- `compare_groups` is already expected to choose an appropriate test based on data type, group structure, normality, and pairing, rather than running t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, and Fisher all at once
- Phase 3 and Phase 4 are meant to turn the research question into a governed contract before Phase 6 executes anything
- blindly running every possible method would inflate multiple comparisons, method drift, false positives, and audit noise
- in that sense, the system is intentionally selective, but only within the families that have actually been implemented, tested, and accepted by the plan schema; if a method family is not wired into the schema, delegator, or heuristics, it will not be adopted automatically in governed execution

So the issue is not that the agent cannot think of more methods. It is that governed execution intentionally refuses to treat “the agent can imagine it” as sufficient justification to run it.

### What to Borrow From `autoresearch`

The concept is worth borrowing, but the code should not be transplanted directly.

What is useful from `karpathy/autoresearch`:

- a lightweight “program” layer that describes what kinds of candidates the agent should explore
- generating candidate directions first, then explicitly keeping or discarding them
- treating the agent’s ideation loop as an evolving asset instead of a one-off prompt

What should not be copied directly into RDE:

- autoresearch optimizes under a fixed experiment budget toward a single improvement metric, while RDE is a multi-objective system constrained by methodological fit, interpretability, audit trail requirements, PII handling, and plan lock
- RDE cannot replace methodology with “run everything and keep whatever looks best"
- biomedical and EDA workflows are not a good fit for an unbounded self-modifying experiment loop

The more suitable adaptation would be a bounded pre-lock candidate-analysis generator:

- it would live between Phase 3 and Phase 4
- it could help expand candidate analyses, figures, and sensitivity checks
- but the final approved subset would still have to be written back into `analysis_plan.yaml` and locked with `confirm=true`

If this idea is adopted in the repo, the README should describe it explicitly as an RDE analysis-ideation layer inspired by `autoresearch`, not as a direct transplant of the original autonomous experiment loop.

## Validation Status

The current repository has been validated in three ways:

1. Unit and integration tests
   - Run with `python3 -m pytest -q`
2. Live vendor contract tests
   - [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)
3. End-to-end dry runs using repository sample data
   - minimal full-gate dry run artifacts under [data/projects/e45af361](data/projects/e45af361)
   - heart disease dry run artifacts under [data/projects/12aafc56](data/projects/12aafc56)

New projects created via `init_project()` now use sortable timestamp-prefixed folders in the form `data/projects/YYYYMMDD_HHMMSS_<project_id>/`. The checked-in sample dry runs above still use legacy short-ID folder names.
When launched from the VS Code extension, `init_project()` resolves this `data/projects/` root from the active workspace via `RDE_WORKSPACE`, not from the MCP server process cwd.

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
4. Specialized analyses outside the current schema, delegator, or vendor contract will often still require manual execution or custom integration rather than a generic built-in tool

Example fallback artifact:

- [data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json](data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json)

## Repository Layout

```text
src/rde/                         Core application
tests/                           Regression and contract tests
vendor/automl-stat-mcp/          Delegated heavy-analysis engine
data/projects/                   Per-project outputs and artifacts
                                New folders: YYYYMMDD_HHMMSS_<project_id>
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
