# Research Data Explorer

**Research Data Explorer (RDE)** is a code-backed MCP server and VS Code harness for auditable exploratory data analysis. It is built for real research datasets where the agent must show its work: intake decisions, schema assumptions, analysis planning, execution artifacts, deviations, report readiness, and audit evidence.

RDE is not a generic "run every statistical method" bot. Its value is narrower and more useful: put a trusted set of EDA, statistical, report, and handoff tools inside a governed workflow that an agent cannot legitimately skip.

**Live workflow site:** <https://u9401066.github.io/research-data-explorer/>

## Current Code-Verified Snapshot

This README is aligned with the current implementation, not only the older prose docs:

| Contract area | Current implementation source | What it says |
| --- | --- | --- |
| Public workflow | [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py) | 13 phases, `phase_00_project_setup` through `phase_12_auto_improve` |
| MCP server registration | [src/rde/interface/mcp/server.py](src/rde/interface/mcp/server.py) | 9 tool modules are registered into the `research-data-explorer` FastMCP server |
| MCP tool surface | [src/rde/interface/mcp/tools](src/rde/interface/mcp/tools) and [vscode-extension/package.json](vscode-extension/package.json) | 49 expected MCP tools, matching actual `@server.tool()` registration |
| Agent control contract | [.github/agent-control.yaml](.github/agent-control.yaml) | phase controls, override flags, audit paths, delegation, UX harness, readiness goals |
| VSIX harness | [vscode-extension/src/extension.ts](vscode-extension/src/extension.ts) and [vscode-extension/package.json](vscode-extension/package.json) | MCP server provider, `@rde` chat participant, commands, Codex config helper, optional automl check |
| Report readiness | [src/rde/interface/mcp/tools/report_tools.py](src/rde/interface/mcp/tools/report_tools.py) | `minimum_complete`, `academic_ready`, `production_ready`, publication bundle, semantic quality, core-goal audit |

## What RDE Solves

Traditional EDA is often difficult to review because method changes are buried in notebooks, intermediate assumptions disappear, and reports do not explain why a method was chosen or changed.

RDE makes the agent behave more like a traceable analysis operator:

1. It creates a project-scoped artifact store before touching data.
2. It runs intake checks before loading datasets, including format, size, and PII gates.
3. It builds a schema registry and profile before planning analyses.
4. It requires explicit user confirmation for concept alignment and plan ideation.
5. It locks an analysis plan before governed Phase 8 execution.
6. It writes decisions and deviations to append-only logs.
7. It blocks polished reports unless readiness, publication bundle, and core-goal checks pass or the caller explicitly allows incomplete output.

## What It Is Honest About

RDE can govern standard, template-friendly analysis families: descriptive summaries, Table 1, group comparisons, correlation/collinearity review, repeated-measures summaries, common figures, adjusted local models, ROC/AUC, basic power analysis, Kaplan-Meier summaries, Cox regression when feasible, and lightweight propensity scoring.

Specialized methods that depend heavily on study design still need custom integration or human methodology review. RDE should not pretend that an imagined method is implemented just because an agent can describe it.

## Architecture

RDE follows a DDD layout:

```text
Interface MCP tools -> Application use cases -> Domain models/policies/services <- Infrastructure adapters
```

The runtime control layers are:

| Layer | Code | Responsibility |
| --- | --- | --- |
| Policy and agent contract | [AGENTS.md](AGENTS.md), [.github/copilot-instructions.md](.github/copilot-instructions.md), [.github/agent-control.yaml](.github/agent-control.yaml) | Tell agents what they may do and which gates are authoritative |
| Pipeline state machine | [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py) | Enforce prerequisites, user-confirmed phases, artifact gates, and plan lock |
| MCP tools | [src/rde/interface/mcp/tools](src/rde/interface/mcp/tools) | Execute project, intake, profiling, planning, analysis, branch, UX, report, and audit operations |
| Decision logging | [src/rde/application/decision_logger.py](src/rde/application/decision_logger.py) | Preserve append-only decision and deviation records |
| Analysis engines | [src/rde/infrastructure/adapters/scipy_engine.py](src/rde/infrastructure/adapters/scipy_engine.py), [src/rde/infrastructure/adapters/analysis_delegator.py](src/rde/infrastructure/adapters/analysis_delegator.py) | Run local-lite statistics first, delegate heavy workflows to automl-stat-mcp when available |

## MCP Tool Surface

The current implementation exposes 49 MCP tools across 9 modules:

| Module | Count | Tools |
| --- | ---: | --- |
| `project_tools.py` | 5 | `init_project`, `get_pipeline_status`, `get_decision_log`, `get_deviation_log`, `log_deviation` |
| `discovery_tools.py` | 4 | `scan_data_folder`, `load_dataset`, `run_intake`, `build_schema` |
| `profiling_tools.py` | 2 | `profile_dataset`, `assess_quality` |
| `plan_tools.py` | 4 | `align_concept`, `propose_analysis_plan`, `register_analysis_plan`, `check_readiness` |
| `analysis_tools.py` | 8 | `suggest_cleaning`, `apply_cleaning`, `analyze_variable`, `compare_groups`, `correlation_matrix`, `generate_table_one`, `run_advanced_analysis`, `run_repeated_measures` |
| `branch_tools.py` | 13 | `open_exploration_branch`, `suggest_branch_experiments`, `run_branch_experiment`, `evaluate_branch`, `promote_branch_to_plan_amendment`, `discard_branch`, `get_exploration_board`, `start_autoresearch_run`, `get_autoresearch_status`, `stop_autoresearch_run`, `resume_autoresearch_run`, `run_autoresearch_next_task`, `run_autoresearch_queue` |
| `ux_tools.py` | 4 | `get_approval_card`, `get_harness_dashboard`, `build_artifact_index`, `get_blocker_playbook` |
| `report_tools.py` | 4 | `collect_results`, `assemble_report`, `create_visualization`, `export_report` |
| `audit_tools.py` | 5 | `run_audit`, `auto_improve`, `export_final_report`, `export_handoff`, `verify_audit_trail` |

## 13-Phase Workflow

| Phase | Purpose | Representative tool/artifact |
| --- | --- | --- |
| 00 Project setup | Create project, artifact root, no-code harness bootstrap | `init_project`, `project.yaml` |
| 01 Data intake | Scan and guard raw files | `run_intake`, `intake_report.json` |
| 02 Schema registry | Load, type, profile, and assess data | `build_schema`, `schema.json` |
| 03 Concept alignment | Map research question to variables and roles | `align_concept(confirm=true)` |
| 04 Creative ideation | Generate candidate analyses and execution schedule | `propose_analysis_plan(confirm=false/true)` |
| 05 Plan completeness review | Check whether the method pool is too thin | `analysis_plan_review.json` |
| 06 Plan registration | Lock the analysis plan after confirmation | `register_analysis_plan(confirm=true)`, `analysis_plan.yaml` |
| 07 Pre-explore check | Check readiness, sample size, missingness, normality, collinearity | `check_readiness` |
| 08 Execute exploration | Run analyses, figures, cleaning, and branch experiments | `decision_log.jsonl` |
| 09 Collect results | Summarize results and publication deliverables | `collect_results`, `results_summary.json` |
| 10 Report assembly | Build EDA report, readiness artifacts, figure interpretation, claim provenance | `assemble_report`, `eda_report.md` |
| 11 Audit review | Grade adherence, method fit, report readiness, PII, reproducibility | `run_audit`, `audit_report.json` |
| 12 Auto-improve and handoff | Refresh final report and handoff package | `auto_improve`, `export_handoff`, `verify_audit_trail` |

## Harness Design

The harness exists so a no-code user can understand what the agent is about to do, what is blocked, and which artifacts support the answer.

| Harness feature | Tool | Artifact |
| --- | --- | --- |
| Approval card | `get_approval_card` | `phase_00_project_setup/approval_card.json`, `approval_card.md` |
| Dashboard | `get_harness_dashboard` | `phase_00_project_setup/harness_dashboard.json` |
| Artifact index | `build_artifact_index` | `phase_00_project_setup/artifact_index.json` |
| Blocker guidance | `get_blocker_playbook` | `phase_00_project_setup/blocker_playbook.json`, `blocker_playbook.md` |

These tools guide the user and the agent. They do not execute analysis, override PII gates, skip confirmations, or bypass plan lock.

## Report Readiness

RDE treats a report as a contract, not a Markdown side effect. The report layer evaluates:

- `minimum_complete`, `academic_ready`, and `production_ready` completion tiers
- publication bundle completeness
- data quality and raw-file coverage
- analysis depth, including multivariable and medical-analysis depth when applicable
- semantic report quality, including structured figure interpretation
- claim provenance for tables, figures, results, and external context
- core-goal audit dimensions such as data understanding, planning, traceability, report generation, no-code operation, and agent-friendly harness

`assemble_report` and `export_report` default-gate on `production_ready` unless `allow_incomplete=true` is passed explicitly.

## Visual Overview

![Overall Concept](docs/figures/01-overall-concept.svg)

![System Architecture](docs/figures/02-system-architecture.svg)

![Workflow Detail](docs/figures/03-workflow-detail.svg)

## Documentation Map

- Live workflow website: <https://u9401066.github.io/research-data-explorer/>
- Traditional Chinese guide: [README.zh-TW.md](README.zh-TW.md)
- Agent operational contract: [AGENTS.md](AGENTS.md)
- VS Code extension guide: [vscode-extension/README.md](vscode-extension/README.md)
- Product doctrine: [docs/product-doctrine.md](docs/product-doctrine.md)
- Machine-readable control manifest: [.github/agent-control.yaml](.github/agent-control.yaml)

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

### 2. Optional: start automl-stat-mcp for delegated heavy analysis

VSIX users do not need Docker to complete the governed EDA path. RDE can run standard statistics plus local-lite adjusted models, ROC/AUC, basic power analysis, Kaplan-Meier summaries, and lightweight propensity scoring through Python dependencies bundled with the project.

Start automl-stat-mcp only when you need heavier vendor workflows, such as full propensity matching/weighting, deeper survival workflows, or AutoML training jobs.

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

The minimal no-Docker configuration only registers RDE:

```json
{
  "servers": {
    "research-data-explorer": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "rde"]
    }
  }
}
```

Add the optional vendor server only after automl-stat-mcp is running:

```json
{
  "servers": {
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
I have a CSV file. Please use the full 13-phase auditable workflow.
Do not skip concept alignment or plan lock.
Use run_advanced_analysis only when Phase 7 is complete.
Log deviations if you need to change the plan.
```

## Recommended Operating Sequence

For a fully constrained run:

1. `init_project`
2. `run_intake`
3. `build_schema`
4. `profile_dataset`
5. `align_concept(confirm=true)`
6. `propose_analysis_plan(confirm=false)` to create the greedy blueprint/review artifacts
7. `propose_analysis_plan(confirm=true)` after user review
8. `register_analysis_plan(confirm=true)`
9. `check_readiness`
10. phase-8 analysis tools
11. `collect_results`
12. `assemble_report`
13. `run_audit`
14. `auto_improve`
15. `export_handoff`
16. `verify_audit_trail`

## Why Phase 3 and 4 Matter

This is the point where a research question becomes an auditable analysis contract.

`align_concept(confirm=true)` should at least pin down:

- the unit of analysis: patient, visit, specimen, procedure, or operator
- the exposure or grouping variable
- the primary and secondary outcomes
- the outcome type: continuous, binary, categorical, time-to-event, or repeated-measures
- adjustment covariates, subgroup variables, exclusion fields, and time-axis columns

`propose_analysis_plan(confirm=false)` should then generate the greedy blueprint/review artifacts for user review. After the user confirms that creative ideation output, `propose_analysis_plan(confirm=true)` records Phase 4 as confirmed.

If you want the agent to drive EDA more autonomously, Phase 4 no longer behaves as a bare greedy sorter. It now produces a draft candidate set, runs an internal methodology review / repair pass, expands beyond the initial budget when that preserves promising EDA branches, and then emits a reviewed blueprint plus a visualization bundle and Phase 8 execution schedule that can be passed into `register_analysis_plan(confirm=true)`. The point is not to bypass human confirmation; the point is to make autonomous ideation itself auditable, repairable, and lockable.

`register_analysis_plan(confirm=true)` now also performs a methodology gate before lock. If the submitted plan is obviously under-scoped for the detected data structure, for example trying to stop after only a couple of analyses even though the dataset supports grouped comparisons, association screening, and adjusted modeling, Phase 5 now first auto-expands the plan with optional exploratory branches. Only if the reviewed plan is still too thin does it block the lock and push the agent back toward `propose_analysis_plan(confirm=false)`, unless `allow_methodology_override=true` is set explicitly. When the plan is locked in Phase 6, the repo also persists an execution schedule artifact so Phase 8 can follow the reviewed ordering instead of improvising from scratch.

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
| Governance lock | What is primary vs secondary, and what are alpha, missing-data, fallback, and required outputs? | Build an auditable contract before Phase 8 | `register_analysis_plan(confirm=true)`, `log_deviation` |

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

Without these planning phases, a fully governed Phase 8 execution path is not really established. If the method changes later, the deviation should be logged explicitly.

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

- the Phase 8 user-facing layer exposes 6 main analysis entrypoints plus 1 visualization entrypoint: `compare_groups`, `analyze_variable`, `correlation_matrix`, `generate_table_one`, `run_advanced_analysis`, `run_repeated_measures`, and `create_visualization`
- the Phase 4 analysis plan schema currently allows 16 analysis types
- the local Scipy/tableone/local-lite layer declares core and no-Docker advanced capabilities in the manifest
- the optional delegated automl layer declares heavy advanced capabilities in the manifest

These numbers should not be added together directly because they represent different layers: user entrypoints, plan types, local engine capabilities, and delegated capabilities. There is overlap, aliasing, and abstraction between them.

More importantly, the agent does not automatically run every possible method because:

- `compare_groups` is already expected to choose an appropriate test based on data type, group structure, normality, and pairing, rather than running t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, and Fisher all at once
- Phase 3 through Phase 6 are meant to turn the research question into a governed contract before Phase 8 executes anything
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

The current repository has been validated in six ways for the 0.4.14 release:

1. Unit and integration tests
   - Run focused contract and harness suites with `python -m pytest ...`
2. Live vendor contract tests
   - [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)
3. End-to-end dry runs through the external Codex/RDE MCP runtime
   - external Codex/RDE MCP runtime smoke: `python scripts/codex_rde_smoke.py --list-tools-only`
   - Quick Explore report smoke: `python scripts/codex_rde_smoke.py`
   - real-file governed smoke: `python scripts/codex_rde_smoke.py --data-file <path> --full-yolo`
   - pytest coverage: [tests/test_codex_support.py](tests/test_codex_support.py)
4. A real Excel governed full-yolo run with no Docker dependency
   - command: `python scripts/codex_rde_smoke.py --workspace .tmp\codex-full-yolo-final15 --data-file <real Excel file> --research-question "比較有無中線輔助對超音波施打動脈導管成功率、耗時與穿刺次數的影響，並探索操作者學習曲線" --full-yolo`
   - report artifact: `.tmp/codex-full-yolo-final15/data/projects/20260508_124523_codex-rde-full-yolo_bf7434f6/artifacts/phase_10_report_assembly/eda_report.md`
   - audit artifact: `.tmp/codex-full-yolo-final15/data/projects/20260508_124523_codex-rde-full-yolo_bf7434f6/artifacts/phase_11_audit_review/audit_report.json`
   - audit result: grade A, 130/130, `report_readiness=production_ready`, `core_goal_audit=9/9`, publication bundle `4/3` descriptive figures and `6/6` analytical figures
5. Cross-platform entrypoint checks
    - VSIX helper tests cover Codex MCP config generation/upsert, UTF-8 environment variables, and path handling.
    - CI now runs VSIX helper tests, bundled Python install-shape smoke, package, and package validation on Ubuntu, Windows, macOS Intel, and macOS Apple Silicon before release publishing.
    - MCP inventory smoke verifies the live Codex/RDE subprocess exposes the required tool surface.
    - The repository uses `pathlib`, Node `path`, inherited PATH/HOME/TEMP runtime variables, UTF-8 environment settings, and ASCII-escaped JSON/JSONL artifacts instead of shell-specific path assembly or ANSI-sensitive machine-readable output.
6. Multi-workbook / multi-sheet governed rerun
   - Project artifact: `data/projects/20260512_143801_kmu_spark_aki_multisheet_full_rerun_d626d6d9`
   - Derived master: 50 rows x 118 columns from two Excel workbooks and 19 worksheets, with each sheet classified as primary analysis, derived merge, QC/context, or excluded context.
   - Phase 8 coverage: 43 analyses, including univariate, bivariate, repeated-measures, adjusted regression, propensity/balance diagnostics, Table 1, and 27 report figures.
   - Audit result: grade A, 165/165, `report_readiness=production_ready`, structured figure interpretation harness present.

The no-Docker local-lite path now defaults away from slow or fragile heavy imports for large routine runs:

- Shapiro-Wilk is skipped for large univariate summaries and replaced with an S-001 large-sample advisory.
- Table 1 defaults to descriptive local-lite output; p-values and the `tableone` package are opt-in.
- Group comparisons, post-hoc power hints, common chart annotations, high-dimensional logistic regression, and high-dimensional linear regression have local-lite fallbacks.
- Matplotlib figures use pure headless Matplotlib paths for common plots instead of requiring seaborn for the production report bundle.

The VSIX also auto-upserts Codex MCP configuration in `~/.codex/config.toml` on activation when a workspace is open. Use `RDE: Configure Codex MCP` to re-run that setup manually.

New projects created via `init_project()` now use sortable, human-readable folders in the form `data/projects/YYYYMMDD_HHMMSS_<project_name_slug>_<project_id>/`.
When launched from the VS Code extension, `init_project()` resolves this `data/projects/` root from the active workspace via `RDE_WORKSPACE`, not from the MCP server process cwd.

Relevant tests include:

- [tests/test_pipeline_integration.py](tests/test_pipeline_integration.py)
- [tests/test_analysis_delegation.py](tests/test_analysis_delegation.py)
- [tests/test_advanced_analysis_formatting.py](tests/test_advanced_analysis_formatting.py)
- [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)

## Known Limitations

At the time of writing:

1. `run_advanced_analysis` can delegate successfully when vendor contracts match the request shape.
2. Docker and automl-stat-mcp remain optional heavy engines; no-Docker VSIX/Codex runs use local-lite fallbacks for the core report path.
3. Some vendor payloads, especially direct model and AutoML submissions on specific datasets, may still fall back if vendor endpoints return HTTP 422.
4. The fallback is preserved as an artifact so auditability is not lost.
5. Specialized analyses outside the current schema, delegator, or vendor contract will often still require custom integration rather than a generic built-in tool.

Example fallback artifact:

- [data/projects/12aafc56/artifacts/phase_08_execute_exploration/advanced_analysis_automl.json](data/projects/12aafc56/artifacts/phase_08_execute_exploration/advanced_analysis_automl.json)

## Repository Layout

```text
src/rde/                         Core application
tests/                           Regression and contract tests
vendor/automl-stat-mcp/          Delegated heavy-analysis engine
data/projects/                   Per-project outputs and artifacts
                                New folders: YYYYMMDD_HHMMSS_<project_name_slug>_<project_id>
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
