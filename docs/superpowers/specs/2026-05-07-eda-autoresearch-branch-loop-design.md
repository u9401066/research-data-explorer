# EDA Autoresearch Branch Loop Design

## Goal

Add a YOLO overnight exploration loop to RDE so Phase 8 can grow auditable exploratory branches without weakening the Phase 6 locked primary analysis plan.

## Product Contract

The locked plan remains the pre-specified primary analysis contract. Autonomous exploration is allowed after Phase 7 readiness, but it must run in isolated branch artifacts, keep an append-only ledger, and never promote an exploratory finding into the main conclusion without an audit gate and explicit confirmation.

## Architecture

RDE will add a branch harness inside Phase 8:

- `open_exploration_branch()` creates a branch record with hypothesis, trigger reason, parent plan item, variables, and risk class.
- `suggest_branch_experiments()` proposes safe exploratory branches from schema, locked plan, and current result facts.
- `run_branch_experiment()` records or executes a branch-scoped experiment without overwriting primary artifacts.
- `evaluate_branch()` scores the branch for validity, method fit, robustness, report value, and complexity cost.
- `promote_branch_to_plan_amendment(confirm=true)` writes an amendment artifact only when the branch passes the promotion gate and the user confirms.
- `discard_branch()` and `get_exploration_board()` keep the branch lifecycle visible.

The branch harness uses append-only JSONL events for reproducibility. Current branch state is reconstructed from those events rather than mutating prior records.

## Safety Rules

YOLO autonomous branches may run:

- alternative tests
- transformations on branch copies
- subgroup or sensitivity checks
- adjusted and unadjusted model variants
- ROC/calibration-style follow-up checks
- missing-strategy comparisons
- visualization bundles

YOLO autonomous branches may not:

- overwrite raw data
- override PII gates
- rewrite locked primary artifacts
- promote exploratory findings to clinical conclusions
- mutate `analysis_plan.yaml` silently
- perform irreversible deletion without a branch record and audit trail

## Artifacts

All artifacts live under `artifacts/phase_08_execute_exploration/`:

- `exploration_branches.jsonl`
- `experiment_ledger.jsonl`
- `branch_results/{branch_id}.json`
- `branch_results/{branch_id}_promotion_review.md`
- `plan_amendment.yaml`

## Promotion Gate

A branch can become an amended analysis only if:

- it has at least one completed experiment,
- it has no crash status,
- it has enough methodological evidence to score at least 70/100,
- it has a recommendation of `promote_candidate`,
- `confirm=true` is passed to the promotion tool.

Promotion writes `plan_amendment.yaml`; it does not rewrite the locked plan.

## Report Semantics

Reports must keep analysis strata separate:

- primary pre-specified analyses,
- confirmed plan amendments,
- exploratory branches,
- discarded or failed branch appendix.

Exploratory results are hypothesis-generating until promoted.

## Testing Strategy

Tests should cover:

- branch events are append-only and reconstruct current state,
- suggestions are generated from schema/plan facts,
- branch experiments create branch-scoped artifacts,
- evaluation produces deterministic scores and recommendations,
- promotion blocks without confirmation or insufficient score,
- promotion writes amendment artifact when the gate passes,
- VSIX/tool policy exposes branch tools only inside RDE workflow groups.
