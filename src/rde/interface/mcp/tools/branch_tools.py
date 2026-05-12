"""Phase 8 exploration branch loop MCP tools."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import uuid

from rde.application.pipeline import PipelinePhase
from rde.domain.models.exploration_branch import (
    BranchEvent,
    BranchStatus,
    BranchType,
    ExperimentEvent,
    ExplorationBranch,
)
from rde.domain.services.exploration_branch_evaluator import ExplorationBranchEvaluator
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools._shared import (
    ensure_phase_ready,
    fmt_error,
    fmt_success,
    log_tool_call,
    log_tool_error,
)


BRANCH_LOG = "exploration_branches.jsonl"
EXPERIMENT_LEDGER = "experiment_ledger.jsonl"
BRANCH_EXPERIMENT_RESULTS_LOG = "branch_experiment_results.jsonl"
BRANCH_EVALUATIONS_LOG = "branch_evaluations.jsonl"
BRANCH_PROMOTION_GATE = "branch_promotion_gate.json"
EXPLORATION_BOARD = "exploration_board.json"
PLAN_AMENDMENTS_LEDGER = "plan_amendments.jsonl"
PLAN_AMENDMENTS_PREFIX = "plan_amendments"
BRANCH_RESULTS_PREFIX = "branch_results"
AUTORESEARCH_RUNS_LOG = "autoresearch_runs.jsonl"
AUTORESEARCH_WORK_QUEUE = "work_queue.jsonl"
AUTORESEARCH_WORK_EVENTS = "work_events.jsonl"
AUTORESEARCH_BUDGET_STATE = "budget_state.json"
AUTORESEARCH_STOP_DECISIONS = "stop_decisions.jsonl"
AUTORESEARCH_RESUME_DECISIONS = "resume_decisions.jsonl"
AUTORESEARCH_PROGRESS_EVENTS = "progress_events.jsonl"


def register_branch_tools(server: Any) -> None:
    """Register Phase 8 YOLO exploration branch tools."""

    @server.tool()
    def open_exploration_branch(
        project_id: str | None = None,
        hypothesis: str = "",
        reason: str = "",
        parent_plan_item: str | None = None,
        variables: list[str] | None = None,
        risk_level: str = "low",
    ) -> str:
        """Open an auditable Phase 8 exploratory branch without amending the plan."""

        log_tool_call(
            "open_exploration_branch",
            {
                "project_id": project_id,
                "hypothesis": hypothesis,
                "parent_plan_item": parent_plan_item,
                "variables": variables,
                "risk_level": risk_level,
            },
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            clean_variables = _normalize_variables(variables)
            branch_type = _infer_branch_type(hypothesis, reason)
            branch_id = f"br_{uuid.uuid4().hex[:10]}"
            event = BranchEvent(
                branch_id=branch_id,
                event_id=_event_id("branch"),
                event_type="branch_opened",
                project_id=project.id,
                branch_type=branch_type,
                status=BranchStatus.OPEN,
                hypothesis=hypothesis,
                reason=reason,
                parent_plan_item=parent_plan_item,
                variables=clean_variables,
                risk_level=_normalize_risk_level(risk_level),
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, event.to_dict())
            return fmt_success(
                "Exploration branch opened.",
                "\n".join(
                    [
                        f"- branch_id: `{branch_id}`",
                        f"- branch_type: {branch_type.value}",
                        f"- status: {BranchStatus.OPEN.value}",
                        f"- artifact: `{PipelinePhase.EXECUTE_EXPLORATION.value}/{BRANCH_LOG}`",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("open_exploration_branch", exc)
            return fmt_error(f"open_exploration_branch failed: {exc}")

    @server.tool()
    def suggest_branch_experiments(
        project_id: str | None = None,
        max_suggestions: int = 5,
    ) -> str:
        """Suggest deterministic branch experiments from schema and locked plan."""

        log_tool_call(
            "suggest_branch_experiments",
            {"project_id": project_id, "max_suggestions": max_suggestions},
        )
        ok, msg, project, store = _phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert store is not None

        try:
            schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json") or {}
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
            roles = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json") or {}
            limit = max(0, min(int(max_suggestions), 10))
            suggestions = _build_branch_suggestions(schema, plan, roles)[:limit]
            if not suggestions:
                return "No branch experiment suggestions are currently relevant."

            lines = ["# Exploration Branch Suggestions"]
            for index, suggestion in enumerate(suggestions, 1):
                lines.append(f"{index}. branch_type: {suggestion['branch_type']}")
                lines.append(f"   hypothesis: {suggestion['hypothesis']}")
                lines.append(f"   reason: {suggestion['reason']}")
                lines.append(f"   variables: {suggestion['variables']}")
                lines.append(f"   experiment_type: {suggestion['experiment_type']}")
                if suggestion.get("analysis_contract"):
                    lines.append(f"   analysis_contract: {suggestion['analysis_contract']}")
            return "\n".join(lines)
        except Exception as exc:
            log_tool_error("suggest_branch_experiments", exc)
            return fmt_error(f"suggest_branch_experiments failed: {exc}")

    @server.tool()
    def run_branch_experiment(
        project_id: str | None = None,
        branch_id: str = "",
        experiment_type: str = "sensitivity",
        parameters: dict[str, Any] | None = None,
        result_summary: str = "",
        metrics: dict[str, Any] | None = None,
        status: str = "completed",
    ) -> str:
        """Append an experiment result to a branch ledger and result artifact."""

        log_tool_call(
            "run_branch_experiment",
            {
                "project_id": project_id,
                "branch_id": branch_id,
                "experiment_type": experiment_type,
                "status": status,
            },
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            board = _reconstruct_board(store)
            branch = board["branches"].get(branch_id)
            if branch is None:
                return fmt_error(f"Unknown exploration branch: {branch_id}")
            if branch.status in {BranchStatus.DISCARDED, BranchStatus.PROMOTED, BranchStatus.CRASHED}:
                return fmt_error(f"Branch {branch_id} is closed ({branch.status.value}).")

            experiment_id = f"exp_{uuid.uuid4().hex[:10]}"
            experiment_artifact = (
                f"{BRANCH_RESULTS_PREFIX}/{branch_id}/experiments/{experiment_id}.json"
            )
            experiment = ExperimentEvent(
                project_id=project.id,
                branch_id=branch_id,
                experiment_id=experiment_id,
                experiment_type=_normalize_token(experiment_type) or "sensitivity",
                parameters=dict(parameters or {}),
                result_summary=result_summary,
                metrics=dict(metrics or {}),
                artifacts=[f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{experiment_artifact}"],
                status=_normalize_token(status) or "completed",
            )
            store.get_path(PipelinePhase.EXECUTE_EXPLORATION, experiment_artifact).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            experiment_path = store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                experiment_artifact,
                {
                    "branch_id": branch_id,
                    "experiment_id": experiment.experiment_id,
                    "scope": "branch",
                    "exploratory": True,
                    "experiment": experiment.to_dict(),
                },
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, EXPERIMENT_LEDGER, experiment.to_dict())
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                BRANCH_EXPERIMENT_RESULTS_LOG,
                {
                    "event_type": "branch_experiment_recorded",
                    "project_id": project.id,
                    "branch_id": branch_id,
                    "experiment_id": experiment.experiment_id,
                    "status": experiment.status,
                    "experiment_type": experiment.experiment_type,
                    "artifact": str(experiment_path),
                    "experiment": experiment.to_dict(),
                },
            )

            if experiment.status in {"crashed", "failed", "error"}:
                crash_event = BranchEvent(
                    branch_id=branch_id,
                    event_id=_event_id("branch"),
                    event_type="branch_crashed",
                    project_id=project.id,
                    branch_type=branch.branch_type,
                    status=BranchStatus.CRASHED,
                    hypothesis=branch.hypothesis,
                    reason=result_summary or "Branch experiment crashed.",
                    parent_plan_item=branch.parent_plan_item,
                    variables=branch.variables,
                    risk_level=branch.risk_level,
                    payload={"experiment_id": experiment.experiment_id},
                )
                store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, crash_event.to_dict())
            else:
                experiment_event = BranchEvent(
                    branch_id=branch_id,
                    event_id=_event_id("branch"),
                    event_type="branch_experiment_recorded",
                    project_id=project.id,
                    branch_type=branch.branch_type,
                    status=BranchStatus.EXPERIMENTING,
                    hypothesis=branch.hypothesis,
                    reason=result_summary or "Branch experiment recorded.",
                    parent_plan_item=branch.parent_plan_item,
                    variables=branch.variables,
                    risk_level=branch.risk_level,
                    payload={"experiment_id": experiment.experiment_id},
                )
                store.save(
                    PipelinePhase.EXECUTE_EXPLORATION,
                    BRANCH_LOG,
                    experiment_event.to_dict(),
                )

            payload, result_path = _save_branch_result(store, branch_id)
            _log_branch_decision(
                project,
                "run_branch_experiment",
                {
                    "branch_id": branch_id,
                    "experiment_id": experiment.experiment_id,
                    "experiment_type": experiment.experiment_type,
                    "scope": "branch",
                    "status": experiment.status,
                },
                "Branch-scoped exploratory experiment; does not amend locked plan.",
                result_summary or f"{experiment.experiment_type} experiment recorded",
                artifacts=[str(experiment_path), result_path],
            )
            return fmt_success(
                "Branch experiment recorded.",
                "\n".join(
                    [
                        f"- branch_id: `{branch_id}`",
                        f"- experiment_id: `{experiment.experiment_id}`",
                        f"- experiments: {len(payload['experiments'])}",
                        f"- experiment_artifact: `{experiment_path}`",
                        f"- artifact: `{result_path}`",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("run_branch_experiment", exc)
            return fmt_error(f"run_branch_experiment failed: {exc}")

    @server.tool()
    def evaluate_branch(
        project_id: str | None = None,
        branch_id: str = "",
    ) -> str:
        """Evaluate a branch and write a promotion review artifact."""

        log_tool_call("evaluate_branch", {"project_id": project_id, "branch_id": branch_id})
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            branch, experiments = _branch_and_experiments(store, branch_id)
            if branch is None:
                return fmt_error(f"Unknown exploration branch: {branch_id}")
            if branch.status in {BranchStatus.DISCARDED, BranchStatus.PROMOTED}:
                return fmt_error(f"Branch {branch_id} is closed ({branch.status.value}).")

            evaluation = ExplorationBranchEvaluator().evaluate(branch, experiments)
            evaluation = _apply_live_evidence_gate(evaluation, store, experiments)
            experiment_ids = _current_experiment_ids(experiments)
            event = BranchEvent(
                branch_id=branch_id,
                event_id=_event_id("branch"),
                event_type="branch_evaluated",
                project_id=project.id,
                branch_type=branch.branch_type,
                status=(
                    BranchStatus.CRASHED
                    if branch.status == BranchStatus.CRASHED
                    else BranchStatus.EVALUATED
                ),
                hypothesis=branch.hypothesis,
                reason="Promotion gate evaluation completed.",
                parent_plan_item=branch.parent_plan_item,
                variables=branch.variables,
                risk_level=branch.risk_level,
                payload={"evaluation": evaluation, "experiment_ids": experiment_ids},
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, event.to_dict())
            _save_branch_result(store, branch_id, evaluation=evaluation)
            review_path = _save_promotion_review(store, branch, evaluation, experiments)
            gate_path = _save_promotion_gate(
                store,
                branch,
                evaluation,
                experiments,
                review_path=review_path,
            )
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                BRANCH_EVALUATIONS_LOG,
                {
                    "event_type": "branch_evaluated",
                    "project_id": project.id,
                    "branch_id": branch_id,
                    "evaluation": evaluation,
                    "experiment_ids": experiment_ids,
                    "experiment_count": len(experiments),
                    "review_artifact": review_path,
                    "gate_artifact": gate_path,
                },
            )
            _log_branch_decision(
                project,
                "evaluate_branch",
                {"branch_id": branch_id, "scope": "branch"},
                "Branch audit gate evaluation before any promotion.",
                (
                    f"score={evaluation['overall_score']}; "
                    f"recommendation={evaluation['recommendation']}; "
                    f"can_promote={evaluation['promotion_gate']['can_promote']}"
                ),
                artifacts=[review_path, gate_path],
            )
            return _format_evaluation(evaluation, review_path)
        except Exception as exc:
            log_tool_error("evaluate_branch", exc)
            return fmt_error(f"evaluate_branch failed: {exc}")

    @server.tool()
    def promote_branch_to_plan_amendment(
        project_id: str | None = None,
        branch_id: str = "",
        confirm: bool = False,
    ) -> str:
        """Promote a high-evidence branch into a plan amendment artifact."""

        log_tool_call(
            "promote_branch_to_plan_amendment",
            {"project_id": project_id, "branch_id": branch_id, "confirm": confirm},
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        if not confirm:
            return fmt_error(
                "Promotion requires explicit confirmation.",
                suggestion="Call promote_branch_to_plan_amendment(confirm=True).",
            )

        prerequisite_blockers = _promotion_prerequisite_blockers(project, store)
        if prerequisite_blockers:
            return fmt_error(
                "Promotion requires a confirmed locked plan and successful readiness gate.",
                f"blockers={prerequisite_blockers}",
                "Run Phase 6 plan registration and Phase 7 check_readiness() before promotion.",
            )

        try:
            branch, experiments = _branch_and_experiments(store, branch_id)
            if branch is None:
                return fmt_error(f"Unknown exploration branch: {branch_id}")
            if branch.status in {BranchStatus.DISCARDED, BranchStatus.PROMOTED, BranchStatus.CRASHED}:
                return fmt_error(f"Branch {branch_id} is closed ({branch.status.value}).")
            if branch.status != BranchStatus.EVALUATED:
                return fmt_error(
                    "Promotion requires a completed branch audit gate.",
                    suggestion="Call evaluate_branch() after the latest branch experiment, then retry.",
                )

            evaluated = _latest_evaluation_event(store, branch_id)
            if evaluated is None:
                return fmt_error(
                    "Promotion requires a persisted evaluate_branch audit event.",
                    suggestion="Call evaluate_branch() before promotion.",
                )
            missing_gate_artifacts = [
                name
                for name in ("review_artifact", "gate_artifact")
                if not _stored_artifact_exists(store, evaluated.get(name))
            ]
            if missing_gate_artifacts:
                return fmt_error(
                    "Promotion gate audit artifacts are missing.",
                    (
                        "Missing: "
                        + ", ".join(missing_gate_artifacts)
                        + ". Re-run evaluate_branch() to rebuild the audit gate."
                    ),
                )

            current_experiment_ids = _current_experiment_ids(experiments)
            if evaluated["experiment_ids"] != current_experiment_ids:
                return fmt_error(
                    "Promotion gate is stale because branch experiments changed after evaluation.",
                    suggestion="Re-run evaluate_branch() before promotion.",
                )

            evaluation = _apply_live_evidence_gate(evaluated["evaluation"], store, experiments)
            if (
                evaluation["overall_score"] < ExplorationBranchEvaluator.PROMOTION_THRESHOLD
                or evaluation["recommendation"] != "promote_candidate"
                or not evaluation["promotion_gate"]["can_promote"]
            ):
                return fmt_error(
                    "Promotion gate failed.",
                    (
                        f"score={evaluation['overall_score']} "
                        f"recommendation={evaluation['recommendation']} "
                        f"blockers={evaluation['promotion_gate']['blockers']}"
                    ),
                    "Only promote branches with score >= 70 and recommendation=promote_candidate.",
                )

            amendment = _build_plan_amendment(project.id, branch, experiments, evaluation)
            amendment_json = f"{PLAN_AMENDMENTS_PREFIX}/{branch_id}.json"
            amendment_md = f"{PLAN_AMENDMENTS_PREFIX}/{branch_id}.md"
            store.get_path(PipelinePhase.EXECUTE_EXPLORATION, amendment_json).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            amendment_json_path = store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                amendment_json,
                amendment,
            )
            amendment_md_path = store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                amendment_md,
                _format_plan_amendment_markdown(amendment),
            )
            review_path = _save_promotion_review(store, branch, evaluation, experiments)
            gate_path = _save_promotion_gate(
                store,
                branch,
                evaluation,
                experiments,
                review_path=review_path,
                amendment_artifacts=[str(amendment_json_path), str(amendment_md_path)],
            )
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                PLAN_AMENDMENTS_LEDGER,
                {
                    "event_type": "plan_amendment_proposed",
                    "project_id": project.id,
                    "branch_id": branch_id,
                    "source": "phase_08_exploration_branch_loop",
                    "evaluation": evaluation,
                    "artifacts": [str(amendment_json_path), str(amendment_md_path)],
                },
            )
            event = BranchEvent(
                branch_id=branch_id,
                event_id=_event_id("branch"),
                event_type="branch_promoted",
                project_id=project.id,
                branch_type=branch.branch_type,
                status=BranchStatus.PROMOTED,
                hypothesis=branch.hypothesis,
                reason="Confirmed promotion to plan amendment.",
                parent_plan_item=branch.parent_plan_item,
                variables=branch.variables,
                risk_level=branch.risk_level,
                payload={
                    "evaluation": evaluation,
                    "plan_amendment_artifacts": [
                        str(amendment_json_path),
                        str(amendment_md_path),
                    ],
                },
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, event.to_dict())
            _save_branch_result(store, branch_id, evaluation=evaluation)
            _log_branch_decision(
                project,
                "promote_branch_to_plan_amendment",
                {"branch_id": branch_id, "scope": "branch", "confirm": True},
                "Confirmed branch-scoped plan amendment proposal after audit gate.",
                f"score={evaluation['overall_score']}; amendment remains branch-scoped",
                artifacts=[str(amendment_json_path), str(amendment_md_path), gate_path],
            )
            return fmt_success(
                "Exploration branch promoted to plan amendment.",
                "\n".join(
                    [
                        f"- branch_id: `{branch_id}`",
                        f"- score: {evaluation['overall_score']}",
                        f"- artifact: `{amendment_json_path}`",
                        f"- markdown: `{amendment_md_path}`",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("promote_branch_to_plan_amendment", exc)
            return fmt_error(f"promote_branch_to_plan_amendment failed: {exc}")

    @server.tool()
    def discard_branch(
        project_id: str | None = None,
        branch_id: str = "",
        reason: str = "",
    ) -> str:
        """Discard an exploratory branch via append-only lifecycle event."""

        log_tool_call(
            "discard_branch",
            {"project_id": project_id, "branch_id": branch_id, "reason": reason},
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            branch, _ = _branch_and_experiments(store, branch_id)
            if branch is None:
                return fmt_error(f"Unknown exploration branch: {branch_id}")
            if branch.status == BranchStatus.PROMOTED:
                return fmt_error(f"Branch {branch_id} is already promoted and cannot be discarded.")
            event = BranchEvent(
                branch_id=branch_id,
                event_id=_event_id("branch"),
                event_type="branch_discarded",
                project_id=project.id,
                branch_type=branch.branch_type,
                status=BranchStatus.DISCARDED,
                hypothesis=branch.hypothesis,
                reason=reason,
                parent_plan_item=branch.parent_plan_item,
                variables=branch.variables,
                risk_level=branch.risk_level,
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, event.to_dict())
            payload, result_path = _save_branch_result(store, branch_id)
            _log_branch_decision(
                project,
                "discard_branch",
                {"branch_id": branch_id, "scope": "branch"},
                "Branch-scoped exploratory path discarded.",
                reason or "Branch discarded.",
                artifacts=[result_path],
            )
            return fmt_success(
                "Exploration branch discarded.",
                f"- branch_id: `{branch_id}`\n- experiments: {len(payload['experiments'])}\n- reason: {reason}",
            )
        except Exception as exc:
            log_tool_error("discard_branch", exc)
            return fmt_error(f"discard_branch failed: {exc}")

    @server.tool()
    def get_exploration_board(project_id: str | None = None) -> str:
        """Return the current branch board reconstructed from append-only events."""

        log_tool_call("get_exploration_board", {"project_id": project_id})
        ok, msg, _, store = _phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert store is not None

        try:
            board = _reconstruct_board(store)
            board_path = _save_exploration_board(store, board)
            branches = list(board["branches"].values())
            if not branches:
                return (
                    "# Exploration Board\n\n"
                    "No exploration branches are open.\n\n"
                    f"- artifact: `{board_path}`"
                )

            lines = ["# Exploration Board"]
            for branch in sorted(branches, key=lambda item: item.opened_at):
                status = branch.status.value
                experiment_count = len(board["experiments_by_branch"].get(branch.branch_id, []))
                if status == BranchStatus.OPEN.value and experiment_count:
                    status = BranchStatus.EXPERIMENTING.value
                score = ""
                if branch.last_evaluation:
                    score = f" score={branch.last_evaluation.get('overall_score')}"
                lines.append(
                    (
                        f"- `{branch.branch_id}` status={status} "
                        f"branch_type={branch.branch_type.value} experiments={experiment_count}{score}"
                    )
                )
                if branch.hypothesis:
                    lines.append(f"  hypothesis: {branch.hypothesis}")
            lines.append(f"\n- artifact: `{board_path}`")
            return "\n".join(lines)
        except Exception as exc:
            log_tool_error("get_exploration_board", exc)
            return fmt_error(f"get_exploration_board failed: {exc}")

    @server.tool()
    def start_autoresearch_run(
        project_id: str | None = None,
        max_tasks: int = 10,
        max_branches: int = 10,
        max_failures: int = 3,
        max_minutes: int = 480,
    ) -> str:
        """Seed a durable Phase 8 autoresearch queue from the locked plan and branch suggestions."""

        log_tool_call(
            "start_autoresearch_run",
            {
                "project_id": project_id,
                "max_tasks": max_tasks,
                "max_branches": max_branches,
                "max_failures": max_failures,
                "max_minutes": max_minutes,
            },
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            active = _active_autoresearch_run(store)
            if active is not None:
                return fmt_error(
                    "Autoresearch run already active.",
                    f"run_id={active['run_id']} queue_depth={active['queue_depth']}",
                    suggestion="Call get_autoresearch_status() or stop_autoresearch_run() first.",
                )

            schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json") or {}
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
            roles = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json") or {}
            suggestions = _build_branch_suggestions(schema, plan, roles)
            task_limit = max(1, min(int(max_tasks or 1), int(max_branches or max_tasks or 1)))
            selected = suggestions[:task_limit]
            run_id = f"ar_{uuid.uuid4().hex[:10]}"
            started_at = datetime.now()
            deadline_at = started_at + timedelta(minutes=max(1, int(max_minutes or 1)))
            if not selected:
                completed_event = {
                    "event_type": "autoresearch_run_completed",
                    "run_id": run_id,
                    "project_id": project.id,
                    "status": "completed",
                    "started_at": started_at.isoformat(),
                    "completed_at": started_at.isoformat(),
                    "deadline_at": deadline_at.isoformat(),
                    "reason": "no_suggestions",
                    "max_tasks": 0,
                    "max_branches": max(1, int(max_branches or 1)),
                    "max_failures": max(0, int(max_failures or 0)),
                    "max_minutes": max(1, int(max_minutes or 1)),
                }
                store.save(
                    PipelinePhase.EXECUTE_EXPLORATION,
                    AUTORESEARCH_RUNS_LOG,
                    completed_event,
                )
                store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_WORK_QUEUE, [])
                store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_WORK_EVENTS, [])
                budget = _build_budget_state(completed_event, [])
                budget.update(
                    {
                        "status": "completed",
                        "max_tasks": 0,
                        "remaining_tasks": 0,
                        "completed_tasks": 0,
                        "failed_tasks": 0,
                        "current_blocker": "no_suggestions",
                        "completed_at": started_at.isoformat(),
                    }
                )
                store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
                _save_autoresearch_progress(store, run_id, "completed", blocker="no_suggestions")
                _log_autoresearch_lifecycle_decision(
                    project,
                    "start_autoresearch_run",
                    run_id,
                    {
                        "status": "completed",
                        "requested_max_tasks": max_tasks,
                        "requested_max_branches": max_branches,
                        "queued_tasks": 0,
                    },
                    "Autoresearch run requested but no branch suggestions were available.",
                    "No branch suggestions available; no active run was created.",
                    artifacts=[
                        f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_RUNS_LOG}",
                        f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}",
                    ],
                )
                return fmt_success(
                    "Autoresearch run completed with no branch suggestions.",
                    "\n".join(
                        [
                            f"- run_id: `{run_id}`",
                            "- queued_tasks: 0",
                            "- status: completed",
                            "- reason: no_suggestions",
                        ]
                    ),
                )
            run_event = {
                "event_type": "autoresearch_run_started",
                "run_id": run_id,
                "project_id": project.id,
                "status": "running",
                "started_at": started_at.isoformat(),
                "deadline_at": deadline_at.isoformat(),
                "max_tasks": task_limit,
                "max_branches": max(1, int(max_branches or task_limit)),
                "max_failures": max(0, int(max_failures or 0)),
                "max_minutes": max(1, int(max_minutes or 1)),
            }
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_RUNS_LOG, run_event)

            queue_items = [
                _build_autoresearch_work_item(project.id, run_id, index + 1, suggestion)
                for index, suggestion in enumerate(selected)
            ]
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                AUTORESEARCH_WORK_QUEUE,
                queue_items,
            )
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                AUTORESEARCH_WORK_EVENTS,
                [
                    {
                        "event_type": "work_item_queued",
                        "run_id": run_id,
                        "task_id": item["task_id"],
                        "priority_score": item["priority_score"],
                        "status": item["status"],
                    }
                    for item in queue_items
                ],
            )

            budget = _build_budget_state(run_event, queue_items)
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
            _save_autoresearch_progress(store, run_id, "started")
            _log_autoresearch_lifecycle_decision(
                project,
                "start_autoresearch_run",
                run_id,
                {
                    "max_tasks": task_limit,
                    "max_branches": max(1, int(max_branches or task_limit)),
                    "max_failures": max(0, int(max_failures or 0)),
                    "max_minutes": max(1, int(max_minutes or 1)),
                    "queued_tasks": len(queue_items),
                },
                "Autoresearch durable branch queue started under the locked Phase 8 plan.",
                f"queued_tasks={len(queue_items)}; deadline_at={deadline_at.isoformat()}",
                artifacts=[
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_RUNS_LOG}",
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_WORK_QUEUE}",
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}",
                ],
            )

            return fmt_success(
                "Autoresearch run started.",
                "\n".join(
                    [
                        f"- run_id: `{run_id}`",
                        f"- queued_tasks: {len(queue_items)}",
                        f"- deadline_at: {deadline_at.isoformat()}",
                        f"- queue: `{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_WORK_QUEUE}`",
                        f"- budget: `{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}`",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("start_autoresearch_run", exc)
            return fmt_error(f"start_autoresearch_run failed: {exc}")

    @server.tool()
    def get_autoresearch_status(project_id: str | None = None) -> str:
        """Return durable autoresearch queue/budget/progress status."""

        log_tool_call("get_autoresearch_status", {"project_id": project_id})
        ok, msg, _, store = _phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert store is not None

        try:
            status = _autoresearch_status_payload(store)
            if not status.get("run_id"):
                return "# Autoresearch Status\n\nNo autoresearch run has been started."
            _save_autoresearch_progress(store, str(status["run_id"]), "status_checked")
            return "\n".join(
                [
                    "# Autoresearch Status",
                    f"- run_id: `{status['run_id']}`",
                    f"- status: {status['status']}",
                    f"- queue_depth: {status['queue_depth']}",
                    f"- completed: {status['completed_count']}",
                    f"- failed: {status['failed_count']}",
                    f"- budget_remaining: {status['budget_remaining']}",
                    f"- current_blocker: {status.get('current_blocker') or 'none'}",
                ]
            )
        except Exception as exc:
            log_tool_error("get_autoresearch_status", exc)
            return fmt_error(f"get_autoresearch_status failed: {exc}")

    @server.tool()
    def stop_autoresearch_run(project_id: str | None = None, reason: str = "") -> str:
        """Stop the latest durable autoresearch run and write a stop decision."""

        log_tool_call("stop_autoresearch_run", {"project_id": project_id, "reason": reason})
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            status = _autoresearch_status_payload(store)
            if not status or status.get("status") != "running":
                return fmt_error("No autoresearch run is active.")
            run_id = str(status["run_id"])
            stop_reason = reason.strip() or "Autoresearch run stopped by user."
            stopped_at = datetime.now().isoformat()
            stop_event = {
                "event_type": "autoresearch_run_stopped",
                "run_id": run_id,
                "project_id": project.id,
                "status": "stopped",
                "stopped_at": stopped_at,
                "reason": stop_reason,
            }
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_STOP_DECISIONS, stop_event)
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_RUNS_LOG, stop_event)
            queue = _project_autoresearch_queue(store, run_id)
            budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE) or {}
            budget = budget if isinstance(budget, dict) else {}
            completed = _count_autoresearch_status(queue, {"completed"})
            failed = _count_autoresearch_status(queue, {"failed", "crashed", "error"})
            remaining = _count_autoresearch_status(
                queue,
                {"pending", "running", "leased", "in_progress"},
            )
            budget.update(
                {
                    "run_id": run_id,
                    "project_id": project.id,
                    "status": "stopped",
                    "stopped_at": stopped_at,
                    "stop_reason": stop_reason,
                    "current_blocker": stop_reason,
                    "completed_tasks": completed,
                    "failed_tasks": failed,
                    "remaining_tasks": remaining,
                    "queued_tasks": len(queue),
                    "updated_at": stopped_at,
                }
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
            _save_autoresearch_progress(store, run_id, "stopped", blocker=stop_reason)
            _log_autoresearch_lifecycle_decision(
                project,
                "stop_autoresearch_run",
                run_id,
                {
                    "reason": stop_reason,
                    "completed_tasks": completed,
                    "failed_tasks": failed,
                    "remaining_tasks": remaining,
                },
                "Autoresearch durable branch queue stopped before continuing exploration.",
                stop_reason,
                artifacts=[
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_STOP_DECISIONS}",
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}",
                ],
            )
            return fmt_success(
                "Autoresearch run stopped.",
                f"- run_id: `{run_id}`\n- reason: {stop_reason}",
            )
        except Exception as exc:
            log_tool_error("stop_autoresearch_run", exc)
            return fmt_error(f"stop_autoresearch_run failed: {exc}")

    @server.tool()
    def resume_autoresearch_run(project_id: str | None = None, reason: str = "") -> str:
        """Resume the latest stopped or expired durable autoresearch run."""

        log_tool_call("resume_autoresearch_run", {"project_id": project_id, "reason": reason})
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            status = _autoresearch_status_payload(store)
            if not status.get("run_id"):
                return fmt_error("No autoresearch run has been started.")
            if status.get("status") == "running":
                return fmt_error(
                    "Autoresearch run already active.",
                    f"run_id={status['run_id']} queue_depth={status['queue_depth']}",
                )
            if status.get("status") not in {"stopped", "expired"}:
                return fmt_error(
                    f"Cannot resume autoresearch run with status {status.get('status')}.",
                    "Only stopped or expired autoresearch runs can be resumed.",
                )
            run_id = str(status["run_id"])
            resumed_at = datetime.now().isoformat()
            resume_reason = reason.strip() or "Autoresearch run resumed."
            resume_event = {
                "event_type": "autoresearch_run_resumed",
                "run_id": run_id,
                "project_id": project.id,
                "status": "running",
                "resumed_at": resumed_at,
                "reason": resume_reason,
            }
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_RESUME_DECISIONS, resume_event)
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_RUNS_LOG, resume_event)
            queue = _project_autoresearch_queue(store, run_id)
            budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE) or {}
            budget = budget if isinstance(budget, dict) else {}
            max_minutes = int(budget.get("max_minutes") or 480)
            deadline_at = (datetime.now() + timedelta(minutes=max(1, max_minutes))).isoformat()
            budget.update(
                {
                    "run_id": run_id,
                    "project_id": project.id,
                    "status": "running",
                    "resumed_at": resumed_at,
                    "deadline_at": deadline_at,
                    "resume_reason": resume_reason,
                    "current_blocker": None,
                    "remaining_tasks": _count_autoresearch_status(
                        queue,
                        {"pending", "running", "leased", "in_progress"},
                    ),
                    "completed_tasks": _count_autoresearch_status(queue, {"completed"}),
                    "failed_tasks": _count_autoresearch_status(
                        queue,
                        {"failed", "crashed", "error"},
                    ),
                    "queued_tasks": len(queue),
                    "updated_at": resumed_at,
                }
            )
            store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
            _save_autoresearch_progress(store, run_id, "resumed")
            _log_autoresearch_lifecycle_decision(
                project,
                "resume_autoresearch_run",
                run_id,
                {
                    "reason": resume_reason,
                    "remaining_tasks": budget["remaining_tasks"],
                    "deadline_at": deadline_at,
                },
                "Autoresearch durable branch queue resumed under the locked Phase 8 plan.",
                resume_reason,
                artifacts=[
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_RESUME_DECISIONS}",
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}",
                ],
            )
            return fmt_success(
                "Autoresearch run resumed.",
                f"- run_id: `{run_id}`\n- queue_depth: {budget['remaining_tasks']}",
            )
        except Exception as exc:
            log_tool_error("resume_autoresearch_run", exc)
            return fmt_error(f"resume_autoresearch_run failed: {exc}")

    @server.tool()
    def run_autoresearch_next_task(
        project_id: str | None = None,
        lease_owner: str = "agent",
        lease_seconds: int = 900,
    ) -> str:
        """Execute one pending autoresearch queue item as an auditable branch task."""

        log_tool_call(
            "run_autoresearch_next_task",
            {
                "project_id": project_id,
                "lease_owner": lease_owner,
                "lease_seconds": lease_seconds,
            },
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            result = _execute_autoresearch_next_task(
                project,
                store,
                lease_owner=lease_owner,
                lease_seconds=max(1, int(lease_seconds or 1)),
            )
            if not result["ok"]:
                return fmt_error(str(result["message"]))
            if result["status"] == "idle":
                return fmt_success(
                    "Autoresearch queue is idle.",
                    f"- run_id: `{result['run_id']}`\n- processed: 0",
                )
            return fmt_success(
                "Autoresearch task completed.",
                "\n".join(
                    [
                        f"- run_id: `{result['run_id']}`",
                        f"- task_id: `{result['task_id']}`",
                        f"- branch_id: `{result['branch_id']}`",
                        f"- experiment_id: `{result['experiment_id']}`",
                        f"- task_status: {result['status']}",
                        f"- remaining_tasks: {result['remaining_tasks']}",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("run_autoresearch_next_task", exc)
            return fmt_error(f"run_autoresearch_next_task failed: {exc}")

    @server.tool()
    def run_autoresearch_queue(
        project_id: str | None = None,
        max_tasks: int = 10,
        lease_owner: str = "agent",
    ) -> str:
        """Drain pending autoresearch queue items until idle or budget limit."""

        log_tool_call(
            "run_autoresearch_queue",
            {
                "project_id": project_id,
                "max_tasks": max_tasks,
                "lease_owner": lease_owner,
            },
        )
        ok, msg, project, store = _governed_phase8_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            processed: list[dict[str, Any]] = []
            task_limit = max(0, int(max_tasks or 0))
            for _ in range(task_limit):
                result = _execute_autoresearch_next_task(
                    project,
                    store,
                    lease_owner=lease_owner,
                    lease_seconds=900,
                )
                if not result["ok"]:
                    status = _autoresearch_status_payload(store)
                    if (
                        processed
                        and str(result["message"]) == "No running autoresearch run."
                        and status.get("status") == "completed"
                        and int(status.get("queue_depth") or 0) == 0
                    ):
                        break
                    return fmt_error(str(result["message"]))
                if result["status"] == "idle":
                    break
                processed.append(result)

            status = _autoresearch_status_payload(store)
            return fmt_success(
                "Autoresearch queue drain completed.",
                "\n".join(
                    [
                        f"- run_id: `{status.get('run_id') or ''}`",
                        f"- processed_tasks: {len(processed)}",
                        f"- status: {status.get('status')}",
                        f"- queue_depth: {status.get('queue_depth')}",
                        f"- completed: {status.get('completed_count')}",
                        f"- failed: {status.get('failed_count')}",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("run_autoresearch_queue", exc)
            return fmt_error(f"run_autoresearch_queue failed: {exc}")


def _phase8_context(
    project_id: str | None,
) -> tuple[bool, str, Any | None, ArtifactStore | None]:
    ok, msg, project, _ = ensure_phase_ready(
        PipelinePhase.EXECUTE_EXPLORATION,
        project_id=project_id,
        require_dataset=False,
    )
    store = ArtifactStore(project.artifacts_dir) if project is not None else None
    if not ok or project is None:
        return False, msg, project, store
    return True, "ready", project, store


def _governed_phase8_context(
    project_id: str | None,
) -> tuple[bool, str, Any | None, ArtifactStore | None]:
    ok, msg, project, store = _phase8_context(project_id)
    if project is not None and store is not None:
        blockers = _promotion_prerequisite_blockers(project, store)
        if blockers:
            return (
                False,
                (
                    "Phase 8 branch exploration requires a confirmed locked plan and "
                    "successful readiness gate. "
                    f"blockers={blockers}. "
                    "Run Phase 6 register_analysis_plan(confirm=True) and Phase 7 "
                    "check_readiness() before branch/autoresearch execution."
                ),
                project,
                store,
            )

    if not ok or project is None or store is None:
        return ok, msg, project, store

    return True, "ready", project, store


def _event_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _normalize_variables(variables: list[str] | None) -> list[str]:
    if not variables:
        return []
    return [str(variable) for variable in variables if str(variable).strip()]


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_risk_level(value: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in {"low", "medium", "high"} else "low"


def _infer_branch_type(hypothesis: str, reason: str) -> BranchType:
    text = f"{hypothesis} {reason}".lower()
    if "missing" in text or "imput" in text:
        return BranchType.MISSING_STRATEGY
    if "survival" in text or "kaplan" in text or "cox" in text:
        return BranchType.SURVIVAL
    if "roc" in text or "auc" in text:
        return BranchType.ROC
    if "propensity" in text or "balance" in text:
        return BranchType.PROPENSITY
    if "subgroup" in text or "interaction" in text:
        return BranchType.SUBGROUP
    if "repeated" in text or "longitudinal" in text:
        return BranchType.REPEATED_MEASURES
    if "adjust" in text or "covariate" in text or "model" in text:
        return BranchType.ADJUSTED_MODEL
    if "visual" in text or "plot" in text or "chart" in text:
        return BranchType.VISUALIZATION
    if "sensitivity" in text or "robust" in text or "stable" in text:
        return BranchType.SENSITIVITY
    return BranchType.HYPOTHESIS


def _load_jsonl(store: ArtifactStore, filename: str) -> list[dict[str, Any]]:
    payload = store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)
    return payload if isinstance(payload, list) else []


def _reconstruct_board(store: ArtifactStore) -> dict[str, Any]:
    branches: dict[str, ExplorationBranch] = {}
    for event in _load_jsonl(store, BRANCH_LOG):
        branch_id = str(event.get("branch_id") or "")
        if not branch_id:
            continue
        if branch_id not in branches:
            branches[branch_id] = ExplorationBranch.from_dict(event)
        branch = branches[branch_id]
        branch.status = BranchStatus(str(event.get("status") or branch.status.value))
        branch.updated_at = str(event.get("timestamp") or branch.updated_at)
        if event.get("hypothesis"):
            branch.hypothesis = str(event["hypothesis"])
        if event.get("reason"):
            branch.reason = str(event["reason"])
        payload = event.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("evaluation"), dict):
            branch.last_evaluation = payload["evaluation"]

    experiment_events = [
        ExperimentEvent.from_dict(event) for event in _load_jsonl(store, EXPERIMENT_LEDGER)
    ]
    experiments_by_branch: dict[str, list[ExperimentEvent]] = {}
    for experiment in experiment_events:
        experiments_by_branch.setdefault(experiment.branch_id, []).append(experiment)
    for branch_id, experiments in experiments_by_branch.items():
        if branch_id in branches:
            branches[branch_id].experiments_count = len(experiments)
    return {"branches": branches, "experiments_by_branch": experiments_by_branch}


def _branch_and_experiments(
    store: ArtifactStore,
    branch_id: str,
) -> tuple[ExplorationBranch | None, list[ExperimentEvent]]:
    board = _reconstruct_board(store)
    branch = board["branches"].get(branch_id)
    experiments = board["experiments_by_branch"].get(branch_id, [])
    return branch, experiments


def _current_experiment_ids(experiments: list[ExperimentEvent]) -> list[str]:
    return [experiment.experiment_id for experiment in experiments]


def _latest_evaluation_event(
    store: ArtifactStore,
    branch_id: str,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for event in _load_jsonl(store, BRANCH_EVALUATIONS_LOG):
        if event.get("event_type") != "branch_evaluated":
            continue
        if str(event.get("branch_id") or "") != branch_id:
            continue
        evaluation = event.get("evaluation")
        if not isinstance(evaluation, dict):
            continue
        latest = {
            "evaluation": evaluation,
            "experiment_ids": [str(value) for value in event.get("experiment_ids") or []],
            "review_artifact": event.get("review_artifact"),
            "gate_artifact": event.get("gate_artifact"),
        }
    return latest


def _stored_artifact_exists(store: ArtifactStore, value: Any) -> bool:
    if not value:
        return False
    text = str(value)
    path = Path(text)
    if path.exists():
        return True
    normalized = text.replace("\\", "/")
    marker = f"{PipelinePhase.EXECUTE_EXPLORATION.value}/"
    if marker in normalized:
        relative = normalized.split(marker, 1)[1]
        return store.exists(PipelinePhase.EXECUTE_EXPLORATION, relative)
    return store.exists(PipelinePhase.EXECUTE_EXPLORATION, text)


def _promotion_prerequisite_blockers(project: Any, store: ArtifactStore) -> list[str]:
    from rde.application.session import get_session

    session = get_session()
    pipeline = session.get_pipeline(project.id)
    blockers: list[str] = []
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    readiness = store.load(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json")
    phase6 = pipeline.completed_phases.get(PipelinePhase.PLAN_REGISTRATION)
    phase7 = pipeline.completed_phases.get(PipelinePhase.PRE_EXPLORE_CHECK)

    if not project.plan_locked or not pipeline.plan_locked:
        blockers.append("phase_06_plan_not_locked")
    if phase6 is None or not phase6.success or not phase6.user_confirmed:
        blockers.append("phase_06_not_successfully_confirmed")
    if not isinstance(plan, dict) or plan.get("locked") is not True:
        blockers.append("analysis_plan_yaml_not_locked")
    if phase7 is None or not phase7.success:
        blockers.append("phase_07_readiness_not_successful")
    if not isinstance(readiness, dict) or readiness.get("all_passed") is not True:
        blockers.append("readiness_checklist_not_all_passed")
    return blockers


def _apply_live_evidence_gate(
    evaluation: dict[str, Any],
    store: ArtifactStore,
    experiments: list[ExperimentEvent],
) -> dict[str, Any]:
    updated = dict(evaluation)
    gate = dict(updated.get("promotion_gate") or {})
    blockers = list(gate.get("blockers") or [])
    completed = [experiment for experiment in experiments if experiment.status == "completed"]
    if completed and not any(_experiment_has_live_evidence(store, experiment) for experiment in completed):
        blockers.append("missing_live_evidence_artifact")
    blockers = sorted(set(str(blocker) for blocker in blockers if blocker))
    gate["blockers"] = blockers
    if blockers:
        gate["can_promote"] = False
        updated["recommendation"] = "discard"
    updated["promotion_gate"] = gate
    return updated


def _experiment_has_live_evidence(store: ArtifactStore, experiment: ExperimentEvent) -> bool:
    if not _experiment_has_structured_metric(experiment):
        return False
    return any(_stored_artifact_exists(store, artifact) for artifact in experiment.artifacts)


def _experiment_has_structured_metric(experiment: ExperimentEvent) -> bool:
    return any(
        name in experiment.metrics for name in ExplorationBranchEvaluator.STRUCTURED_METRIC_NAMES
    )


def _save_branch_result(
    store: ArtifactStore,
    branch_id: str,
    *,
    evaluation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    branch, experiments = _branch_and_experiments(store, branch_id)
    payload = {
        "branch_id": branch_id,
        "branch": branch.to_dict() if branch else None,
        "experiments": [experiment.to_dict() for experiment in experiments],
        "evaluation": evaluation or (branch.last_evaluation if branch else None),
    }
    filename = f"{BRANCH_RESULTS_PREFIX}/{branch_id}.json"
    store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, filename, payload)
    return payload, str(path)


def _save_exploration_board(store: ArtifactStore, board: dict[str, Any]) -> str:
    branches = {
        branch_id: branch.to_dict()
        for branch_id, branch in sorted(board["branches"].items(), key=lambda item: item[0])
    }
    experiments = {
        branch_id: [experiment.to_dict() for experiment in branch_experiments]
        for branch_id, branch_experiments in sorted(
            board["experiments_by_branch"].items(),
            key=lambda item: item[0],
        )
    }
    path = store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        EXPLORATION_BOARD,
        {
            "branches": branches,
            "experiments_by_branch": experiments,
            "branch_count": len(branches),
            "experiment_count": sum(len(items) for items in experiments.values()),
        },
    )
    return str(path)


def _save_promotion_review(
    store: ArtifactStore,
    branch: ExplorationBranch,
    evaluation: dict[str, Any],
    experiments: list[ExperimentEvent],
) -> str:
    filename = f"{BRANCH_RESULTS_PREFIX}/{branch.branch_id}_promotion_review.md"
    store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    lines = [
        f"# Promotion Review: {branch.branch_id}",
        "",
        f"- recommendation: {evaluation['recommendation']}",
        f"- overall_score: {evaluation['overall_score']}",
        f"- promotion_gate: {evaluation['promotion_gate']['can_promote']}",
        f"- blockers: {evaluation['promotion_gate']['blockers']}",
        f"- experiments: {len(experiments)}",
        "",
        "## Component Scores",
    ]
    for name, score in evaluation["component_scores"].items():
        lines.append(f"- {name}: {score}")
    lines.extend(["", "## Experiment Evidence"])
    if not experiments:
        lines.append("- none")
    for experiment in experiments:
        lines.append(
            (
                f"- {experiment.experiment_id}: type={experiment.experiment_type}; "
                f"status={experiment.status}; artifacts={experiment.artifacts}"
            )
        )
        preview = _metric_preview(experiment.metrics)
        if preview:
            lines.append(f"  metrics: {preview}")
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, filename, "\n".join(lines))
    return str(path)


def _save_promotion_gate(
    store: ArtifactStore,
    branch: ExplorationBranch,
    evaluation: dict[str, Any],
    experiments: list[ExperimentEvent],
    *,
    review_path: str,
    amendment_artifacts: list[str] | None = None,
) -> str:
    payload = {
        "branch_id": branch.branch_id,
        "branch_status": branch.status.value,
        "recommendation": evaluation.get("recommendation"),
        "overall_score": evaluation.get("overall_score"),
        "promotion_gate": evaluation.get("promotion_gate", {}),
        "experiment_ids": _current_experiment_ids(experiments),
        "experiment_count": len(experiments),
        "live_evidence_experiment_ids": [
            experiment.experiment_id
            for experiment in experiments
            if _experiment_has_live_evidence(store, experiment)
        ],
        "review_artifact": review_path,
        "amendment_artifacts": amendment_artifacts or [],
        "exploratory_only_until_audit_gate": True,
    }
    filename = f"{BRANCH_RESULTS_PREFIX}/{branch.branch_id}_promotion_gate.json"
    store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, filename, payload)
    store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_PROMOTION_GATE, payload)
    return str(path)


def _metric_preview(metrics: dict[str, Any]) -> dict[str, Any]:
    preview_keys = [
        "n",
        "nobs",
        "sample_size",
        "p_value",
        "effect_size",
        "odds_ratio",
        "hazard_ratio",
        "auc",
        "roc_auc",
        "c_index",
        "standardized_mean_difference",
        "ci_low",
        "ci_high",
        "common_support",
    ]
    return {key: metrics[key] for key in preview_keys if key in metrics}


def _format_plan_amendment_markdown(amendment: dict[str, Any]) -> str:
    review = amendment.get("promotion_review") or {}
    proposed = amendment.get("proposed_amendment") or {}
    return "\n".join(
        [
            f"# Plan Amendment Proposal: {amendment.get('branch_id', '')}",
            "",
            "> Exploratory branch output. This is not a primary conclusion until reviewed.",
            "",
            f"- source: {amendment.get('source', '')}",
            f"- parent_plan_item: {amendment.get('parent_plan_item') or 'none'}",
            f"- hypothesis: {amendment.get('hypothesis', '')}",
            f"- proposed_type: {proposed.get('type', '')}",
            f"- variables: {proposed.get('variables', [])}",
            f"- recommendation: {review.get('recommendation', '')}",
            f"- overall_score: {review.get('overall_score', '')}",
            f"- blockers: {(review.get('promotion_gate') or {}).get('blockers', [])}",
        ]
    )


def _log_branch_decision(
    project: Any,
    action: str,
    parameters: dict[str, Any],
    rationale: str,
    result_summary: str,
    *,
    artifacts: list[str] | None = None,
) -> None:
    from rde.application.session import get_session
    from rde.interface.mcp.tools._shared.project_context import (
        compute_phase6_progress,
        save_phase6_progress,
    )

    clean_parameters = dict(parameters)
    clean_parameters["scope"] = "branch"
    session = get_session()
    logger = session.get_logger(project.id)
    logger.log_decision(
        phase=PipelinePhase.EXECUTE_EXPLORATION.value,
        action=action,
        tool_used=action,
        parameters=clean_parameters,
        rationale=rationale,
        result_summary=result_summary,
        artifacts=artifacts,
    )
    progress = compute_phase6_progress(project)
    save_phase6_progress(
        project,
        progress,
        last_action={
            "tool": action,
            "parameters": clean_parameters,
            "result_summary": result_summary,
        },
    )


def _log_autoresearch_lifecycle_decision(
    project: Any,
    action: str,
    run_id: str,
    parameters: dict[str, Any],
    rationale: str,
    result_summary: str,
    *,
    artifacts: list[str] | None = None,
) -> None:
    payload = dict(parameters)
    payload["run_id"] = run_id
    _log_branch_decision(
        project,
        action,
        payload,
        rationale,
        result_summary,
        artifacts=artifacts,
    )


def _format_evaluation(evaluation: dict[str, Any], review_path: str) -> str:
    return "\n".join(
        [
            "# Branch Evaluation",
            f"- branch_id: `{evaluation['branch_id']}`",
            f"- overall_score: {evaluation['overall_score']}",
            f"- recommendation: {evaluation['recommendation']}",
            f"- can_promote: {evaluation['promotion_gate']['can_promote']}",
            f"- blockers: {evaluation['promotion_gate']['blockers']}",
            f"- artifact: `{review_path}`",
        ]
    )


def _build_plan_amendment(
    project_id: str,
    branch: ExplorationBranch,
    experiments: list[ExperimentEvent],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    primary_experiment = experiments[-1] if experiments else None
    return {
        "project_id": project_id,
        "branch_id": branch.branch_id,
        "source": "phase_08_exploration_branch_loop",
        "created_at": _event_id("amendment"),
        "parent_plan_item": branch.parent_plan_item,
        "hypothesis": branch.hypothesis,
        "reason": branch.reason,
        "variables": branch.variables,
        "proposed_amendment": {
            "type": primary_experiment.experiment_type if primary_experiment else branch.branch_type.value,
            "variables": branch.variables,
            "rationale": branch.hypothesis or branch.reason,
            "status": "promotion_candidate",
        },
        "promotion_review": evaluation,
        "experiments": [experiment.to_dict() for experiment in experiments],
    }


def _auto_evaluate_autoresearch_branch(
    project: Any,
    store: ArtifactStore,
    branch_id: str,
) -> dict[str, Any]:
    """Evaluate autoresearch output without mutating the locked plan."""

    branch, experiments = _branch_and_experiments(store, branch_id)
    if branch is None or not experiments:
        return {}
    if branch.status in {BranchStatus.DISCARDED, BranchStatus.PROMOTED, BranchStatus.CRASHED}:
        return {}
    if any(experiment.status in {"failed", "crashed", "error"} for experiment in experiments):
        return {}

    evaluation = ExplorationBranchEvaluator().evaluate(branch, experiments)
    evaluation = _apply_live_evidence_gate(evaluation, store, experiments)
    experiment_ids = _current_experiment_ids(experiments)
    event = BranchEvent(
        branch_id=branch_id,
        event_id=_event_id("branch"),
        event_type="branch_auto_evaluated",
        project_id=project.id,
        branch_type=branch.branch_type,
        status=BranchStatus.EVALUATED,
        hypothesis=branch.hypothesis,
        reason="Autoresearch runner evaluated branch evidence after execution.",
        parent_plan_item=branch.parent_plan_item,
        variables=branch.variables,
        risk_level=branch.risk_level,
        payload={"evaluation": evaluation, "experiment_ids": experiment_ids},
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, event.to_dict())
    _save_branch_result(store, branch_id, evaluation=evaluation)

    amendment_artifacts: list[str] = []
    if (
        evaluation.get("recommendation") == "promote_candidate"
        and (evaluation.get("promotion_gate") or {}).get("can_promote")
    ):
        amendment = _build_plan_amendment(project.id, branch, experiments, evaluation)
        amendment["candidate_status"] = "auto_evaluated_requires_confirmed_promotion"
        amendment_json = f"{PLAN_AMENDMENTS_PREFIX}/candidates/{branch_id}.json"
        amendment_md = f"{PLAN_AMENDMENTS_PREFIX}/candidates/{branch_id}.md"
        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, amendment_json).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        amendment_json_path = store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            amendment_json,
            amendment,
        )
        amendment_md_path = store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            amendment_md,
            _format_plan_amendment_markdown(amendment),
        )
        amendment_artifacts = [str(amendment_json_path), str(amendment_md_path)]

    review_path = _save_promotion_review(store, branch, evaluation, experiments)
    gate_path = _save_promotion_gate(
        store,
        branch,
        evaluation,
        experiments,
        review_path=review_path,
        amendment_artifacts=amendment_artifacts,
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        BRANCH_EVALUATIONS_LOG,
        {
            "event_type": "branch_auto_evaluated",
            "project_id": project.id,
            "branch_id": branch_id,
            "evaluation": evaluation,
            "experiment_ids": experiment_ids,
            "experiment_count": len(experiments),
            "review_artifact": review_path,
            "gate_artifact": gate_path,
            "amendment_artifacts": amendment_artifacts,
        },
    )
    return {
        "evaluation": evaluation,
        "review_artifact": review_path,
        "gate_artifact": gate_path,
        "amendment_artifacts": amendment_artifacts,
    }


def _execute_autoresearch_next_task(
    project: Any,
    store: ArtifactStore,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> dict[str, Any]:
    status = _autoresearch_status_payload(store)
    if not status.get("run_id") or status.get("status") != "running":
        return {"ok": False, "message": "No running autoresearch run."}

    run_id = str(status["run_id"])
    queue = _project_autoresearch_queue(store, run_id)
    if _reclaim_expired_autoresearch_leases(store, queue):
        queue = _project_autoresearch_queue(store, run_id)
    failure_blocker = _enforce_autoresearch_failure_budget(project, store, run_id, queue)
    if failure_blocker:
        return {"ok": False, "message": failure_blocker}
    pending = [
        item
        for item in queue
        if str(item.get("status") or "") in {"pending", "leased", "running", "in_progress"}
    ]
    pending = [item for item in pending if str(item.get("status") or "") == "pending"]
    if not pending:
        _complete_autoresearch_run_if_idle(project, store, run_id)
        return {"ok": True, "status": "idle", "run_id": run_id}

    task = sorted(
        pending,
        key=lambda item: (-int(item.get("priority_score") or 0), int(item.get("rank") or 0)),
    )[0]
    task_id = str(task["task_id"])
    branch_id = f"br_{uuid.uuid4().hex[:10]}"
    experiment_id = f"exp_{uuid.uuid4().hex[:10]}"
    now = datetime.now()
    started_at = now.isoformat()
    lease_expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()

    _append_autoresearch_work_update(
        store,
        task,
        {
            "event_type": "work_item_started",
            "status": "running",
            "branch_id": branch_id,
            "lease_owner": lease_owner,
            "lease_expires_at": lease_expires_at,
            "started_at": started_at,
        },
    )

    branch_type = _branch_type_from_value(task.get("branch_type"))
    variables = [str(value) for value in task.get("variables") or []]
    branch_event = BranchEvent(
        branch_id=branch_id,
        event_id=_event_id("branch"),
        event_type="branch_opened",
        project_id=project.id,
        branch_type=branch_type,
        status=BranchStatus.OPEN,
        hypothesis=str(task.get("hypothesis") or "Autoresearch branch task."),
        reason=str(task.get("reason") or "Autoresearch queue execution."),
        variables=variables,
        risk_level="low",
        payload={
            "run_id": run_id,
            "task_id": task_id,
            "analysis_contract": task.get("analysis_contract") or {},
            "runner_generated": True,
        },
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, BRANCH_LOG, branch_event.to_dict())

    experiment_artifact = f"{BRANCH_RESULTS_PREFIX}/{branch_id}/experiments/{experiment_id}.json"
    store.get_path(PipelinePhase.EXECUTE_EXPLORATION, experiment_artifact).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    contract_result = _execute_autoresearch_analysis_contract(
        project,
        store,
        task,
        branch_id=branch_id,
        experiment_id=experiment_id,
        variables=variables,
    )
    metrics = contract_result.get("metrics") or _runner_metrics_for_task(store, task)
    result_summary = str(
        contract_result.get("result_summary")
        or (
            "Autoresearch runner recorded an auditable branch task without a live "
            "analysis contract. This branch remains exploratory until "
            "evaluate_branch() and promotion confirmation."
        )
    )
    experiment_status = str(contract_result.get("status") or "completed")
    contract_artifacts = [str(path) for path in contract_result.get("artifacts") or []]
    experiment_artifacts = [
        f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{experiment_artifact}",
        *contract_artifacts,
    ]
    experiment = ExperimentEvent(
        project_id=project.id,
        branch_id=branch_id,
        experiment_id=experiment_id,
        experiment_type=_normalize_token(task.get("experiment_type")) or "autoresearch_task",
        parameters={
            "run_id": run_id,
            "task_id": task_id,
            "analysis_contract": dict(task.get("analysis_contract") or {}),
            "variables": variables,
        },
        result_summary=result_summary,
        metrics=metrics,
        artifacts=experiment_artifacts,
        status=experiment_status,
    )
    experiment_path = store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        experiment_artifact,
        {
            "branch_id": branch_id,
            "experiment_id": experiment_id,
            "scope": "branch",
            "exploratory": True,
            "runner_generated": bool(metrics.get("runner_generated", True)),
            "contract_execution": contract_result,
            "run_id": run_id,
            "task_id": task_id,
            "task": task,
            "experiment": experiment.to_dict(),
        },
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, EXPERIMENT_LEDGER, experiment.to_dict())
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        BRANCH_EXPERIMENT_RESULTS_LOG,
        {
            "event_type": "branch_experiment_recorded",
            "project_id": project.id,
            "branch_id": branch_id,
            "experiment_id": experiment_id,
            "status": experiment_status,
            "experiment_type": experiment.experiment_type,
            "artifact": str(experiment_path),
            "run_id": run_id,
            "task_id": task_id,
            "experiment": experiment.to_dict(),
        },
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        BRANCH_LOG,
        BranchEvent(
            branch_id=branch_id,
            event_id=_event_id("branch"),
            event_type="branch_experiment_recorded",
            project_id=project.id,
            branch_type=branch_type,
            status=BranchStatus.CRASHED
            if experiment_status in {"failed", "crashed", "error"}
            else BranchStatus.EXPERIMENTING,
            hypothesis=str(task.get("hypothesis") or ""),
            reason=result_summary,
            variables=variables,
            risk_level="low",
            payload={"run_id": run_id, "task_id": task_id, "experiment_id": experiment_id},
        ).to_dict(),
    )
    _, branch_result_path = _save_branch_result(store, branch_id)
    auto_evaluation = {}
    if experiment_status not in {"failed", "crashed", "error"}:
        auto_evaluation = _auto_evaluate_autoresearch_branch(project, store, branch_id)
    auto_evaluation_artifacts = [
        str(path)
        for path in [
            auto_evaluation.get("review_artifact"),
            auto_evaluation.get("gate_artifact"),
            *(auto_evaluation.get("amendment_artifacts") or []),
        ]
        if path
    ]
    _append_autoresearch_work_update(
        store,
        task,
        {
            "event_type": "work_item_failed"
            if experiment_status in {"failed", "crashed", "error"}
            else "work_item_completed",
            "status": "failed"
            if experiment_status in {"failed", "crashed", "error"}
            else "completed",
            "branch_id": branch_id,
            "experiment_id": experiment_id,
            "completed_at": datetime.now().isoformat(),
            "artifacts": [
                *experiment_artifacts,
                branch_result_path,
                *auto_evaluation_artifacts,
            ],
            "error": contract_result.get("error"),
        },
    )
    _log_branch_decision(
        project,
        "run_autoresearch_next_task",
        {
            "run_id": run_id,
            "task_id": task_id,
            "branch_id": branch_id,
            "scope": "branch",
        },
        "Autoresearch runner executed one branch-scoped queue item.",
        result_summary,
        artifacts=[str(experiment_path), *contract_artifacts, branch_result_path, *auto_evaluation_artifacts],
    )
    budget = _update_autoresearch_budget(store, run_id, status="running")
    _save_autoresearch_progress(
        store,
        run_id,
        "task_failed" if experiment_status in {"failed", "crashed", "error"} else "task_completed",
    )
    if int(budget.get("remaining_tasks") or 0) == 0:
        _complete_autoresearch_run_if_idle(project, store, run_id)
        budget = _update_autoresearch_budget(store, run_id, status="completed")
    return {
        "ok": True,
        "status": experiment_status,
        "run_id": run_id,
        "task_id": task_id,
        "branch_id": branch_id,
        "experiment_id": experiment_id,
        "remaining_tasks": budget.get("remaining_tasks", 0),
    }


def _reclaim_expired_autoresearch_leases(
    store: ArtifactStore,
    queue: list[dict[str, Any]],
) -> bool:
    reclaimed = False
    now = datetime.now()
    for task in queue:
        if str(task.get("status") or "") not in {"running", "leased", "in_progress"}:
            continue
        lease_expires_at = _parse_iso_datetime(task.get("lease_expires_at"))
        if lease_expires_at is None or lease_expires_at >= now:
            continue
        _append_autoresearch_work_update(
            store,
            task,
            {
                "event_type": "work_item_lease_reclaimed",
                "status": "pending",
                "lease_owner": None,
                "lease_expires_at": None,
                "reclaimed_at": now.isoformat(),
                "error": "expired_lease_reclaimed",
            },
        )
        reclaimed = True
    return reclaimed


def _enforce_autoresearch_failure_budget(
    project: Any,
    store: ArtifactStore,
    run_id: str,
    queue: list[dict[str, Any]],
) -> str | None:
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE) or {}
    budget = budget if isinstance(budget, dict) else {}
    raw_max_failures = budget.get("max_failures")
    try:
        max_failures = int(raw_max_failures)
    except (TypeError, ValueError):
        max_failures = 0
    failed = _count_autoresearch_status(queue, {"failed", "crashed", "error"})
    exhausted = failed > 0 if max_failures <= 0 else failed >= max_failures
    if not exhausted:
        return None

    latest = _latest_autoresearch_run(store)
    if latest and latest.get("status") == "failed_budget_exhausted":
        return "Autoresearch failure budget exhausted."

    exhausted_at = datetime.now().isoformat()
    blocker = "failure budget exhausted"
    event = {
        "event_type": "autoresearch_run_failed_budget_exhausted",
        "run_id": run_id,
        "project_id": project.id,
        "status": "failed_budget_exhausted",
        "failed_at": exhausted_at,
        "reason": blocker,
        "failed_tasks": failed,
        "max_failures": max_failures,
    }
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_RUNS_LOG, event)
    remaining = _count_autoresearch_status(queue, {"pending", "running", "leased", "in_progress"})
    budget.update(
        {
            "run_id": run_id,
            "project_id": project.id,
            "status": "failed_budget_exhausted",
            "failed_at": exhausted_at,
            "failed_tasks": failed,
            "remaining_tasks": remaining,
            "current_blocker": blocker,
            "updated_at": exhausted_at,
        }
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
    _save_autoresearch_progress(store, run_id, "failed_budget_exhausted", blocker=blocker)
    _log_autoresearch_lifecycle_decision(
        project,
        "autoresearch_failure_budget_exhausted",
        run_id,
        {
            "failed_tasks": failed,
            "max_failures": max_failures,
            "remaining_tasks": remaining,
        },
        "Autoresearch runner stopped before executing more branch tasks because failures reached the configured budget.",
        blocker,
        artifacts=[
            f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_RUNS_LOG}",
            f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{AUTORESEARCH_BUDGET_STATE}",
        ],
    )
    return "Autoresearch failure budget exhausted."


def _append_autoresearch_work_update(
    store: ArtifactStore,
    task: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(task)
    payload.update(update)
    payload["run_id"] = str(task.get("run_id") or update.get("run_id") or "")
    payload["task_id"] = str(task.get("task_id") or update.get("task_id") or "")
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_WORK_QUEUE, payload)
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_WORK_EVENTS, payload)
    return payload


def _branch_type_from_value(value: Any) -> BranchType:
    try:
        return BranchType(str(value or BranchType.HYPOTHESIS.value))
    except ValueError:
        return BranchType.YOLO


def _apply_autoresearch_derived_variables(
    dataframe: Any,
    contract: dict[str, Any],
) -> tuple[Any, list[str], list[dict[str, Any]]]:
    specs = contract.get("derived_variables") or []
    if not isinstance(specs, list) or not specs:
        return dataframe, [], []

    import pandas as pd

    def scalar(value: Any) -> Any:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        if hasattr(value, "item"):
            try:
                return value.item()
            except (TypeError, ValueError):
                pass
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    working = dataframe.copy()
    notes: list[str] = []
    metadata: list[dict[str, Any]] = []
    for raw_spec in specs:
        if not isinstance(raw_spec, dict):
            notes.append("Skipped malformed derived-variable spec.")
            continue
        source = str(raw_spec.get("source") or raw_spec.get("source_variable") or "").strip()
        operation = str(raw_spec.get("operation") or raw_spec.get("type") or "equals").strip().lower()
        name = str(raw_spec.get("name") or "").strip()
        if not name and source:
            name = f"{_normalize_token(source) or 'derived'}_{operation}"
        if not source or source not in working.columns:
            notes.append(f"Skipped derived variable `{name or source}` because source `{source}` is absent.")
            continue
        if not name:
            notes.append(f"Skipped derived variable for `{source}` because no output name was provided.")
            continue

        source_series = working[source]
        nonmissing = source_series.dropna()
        if operation == "dominant_vs_other":
            counts = nonmissing.value_counts()
            if len(counts) < 2:
                notes.append(
                    f"Skipped `{name}` because `{source}` has fewer than two observed levels."
                )
                continue
            positive_value = counts.index[0]
            comparison = source_series == positive_value
            value_counts = {str(scalar(index)): int(count) for index, count in counts.items()}
        elif operation in {"equals", "eq", "is"}:
            positive_value = raw_spec.get("value")
            comparison = source_series == positive_value
            if not bool(comparison.fillna(False).any()):
                comparison = source_series.astype(str) == str(positive_value)
            value_counts = {}
        elif operation in {"in", "one_of"}:
            raw_values = raw_spec.get("values") or []
            values = list(raw_values) if isinstance(raw_values, list) else [raw_values]
            positive_value = [scalar(value) for value in values]
            comparison = source_series.isin(values)
            if not bool(comparison.fillna(False).any()):
                comparison = source_series.astype(str).isin([str(value) for value in values])
            value_counts = {}
        else:
            notes.append(f"Skipped `{name}` because operation `{operation}` is unsupported.")
            continue

        derived = comparison.fillna(False).astype(float)
        derived.loc[source_series.isna()] = pd.NA
        working[name] = derived
        positive_count = int((derived == 1).sum())
        negative_count = int((derived == 0).sum())
        missing_count = int(derived.isna().sum())
        metadata.append(
            {
                "name": name,
                "source": source,
                "operation": operation,
                "positive_value": scalar(positive_value),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "missing_count": missing_count,
                "value_counts": value_counts,
            }
        )
        notes.append(
            f"Derived `{name}` from `{source}` using `{operation}` "
            f"(positive={scalar(positive_value)}, n1={positive_count}, "
            f"n0={negative_count}, missing={missing_count})."
        )

    return working, notes, metadata


def _execute_autoresearch_analysis_contract(
    project: Any,
    store: ArtifactStore,
    task: dict[str, Any],
    *,
    branch_id: str,
    experiment_id: str,
    variables: list[str],
) -> dict[str, Any]:
    contract = dict(task.get("analysis_contract") or {})
    if not contract:
        return {
            "executed": False,
            "status": "completed",
            "artifacts": [],
            "metrics": _runner_metrics_for_task(store, task),
            "result_summary": (
                "Autoresearch branch has no live analysis contract; recorded branch "
                "ledger only."
            ),
        }
    if str(contract.get("tool") or "") != "run_advanced_analysis":
        return {
            "executed": False,
            "status": "completed",
            "artifacts": [],
            "metrics": _runner_metrics_for_task(store, task),
            "result_summary": (
                f"Autoresearch contract tool `{contract.get('tool')}` is not executable "
                "by the branch runner yet; recorded branch ledger only."
            ),
        }

    from rde.infrastructure.adapters import get_analysis_delegator
    from rde.interface.mcp.tools._shared import ensure_dataset
    from rde.interface.mcp.tools.analysis_tools import (
        _format_advanced_analysis_output,
        _sanitize_analysis_frame,
        _summarize_advanced_analysis_result,
    )

    ok, message, entry = ensure_dataset(None, project=project)
    if not ok or entry is None:
        return {
            "executed": False,
            "status": "failed",
            "artifacts": [],
            "metrics": _runner_metrics_for_task(store, task),
            "result_summary": (
                "Autoresearch live analysis contract skipped because the project "
                f"dataset was unavailable: {message}"
            ),
            "error": message,
        }

    analysis_type = str(contract.get("analysis_type") or task.get("experiment_type") or "")
    target_variable = contract.get("target_variable")
    group_variable = contract.get("group_variable")
    covariates = [str(value) for value in contract.get("covariates") or []]
    config: dict[str, Any] = {
        "variables": [],
        "project_name": f"rde_branch_{entry.dataset.id}",
        "user_id": f"rde-{project.id}",
        "branch_id": branch_id,
        "experiment_id": experiment_id,
    }
    branch_backend = contract.get("backend")
    if branch_backend:
        config["backend"] = str(branch_backend)
    elif analysis_type in {
        "glm",
        "logistic_regression",
        "multiple_regression",
        "propensity_score",
        "roc_auc",
    }:
        config["backend"] = "fast"
        config["regularization_alpha"] = 1.0
        config["max_iter"] = 200
    if target_variable:
        config["target"] = str(target_variable)
        config["variables"].append(str(target_variable))
    if group_variable:
        config["group_var"] = str(group_variable)
        config["variables"].append(str(group_variable))
    if covariates:
        config["covariates"] = covariates
        config["variables"].extend(covariates)
    for variable in variables:
        if variable not in config["variables"]:
            config["variables"].append(variable)
    config["variables"] = list(dict.fromkeys(config["variables"]))

    try:
        analysis_source_df, derived_notes, derived_metadata = _apply_autoresearch_derived_variables(
            entry.dataframe,
            contract,
        )
        derived_registry_entries: list[dict[str, Any]] = []
        derived_registry_path: str | None = None
        if derived_metadata:
            from rde.domain.services.derived_variable_registry import (
                DERIVED_VARIABLE_REGISTRY,
                upsert_derived_variable_registry,
            )

            derived_registry_entries, derived_registry_path = upsert_derived_variable_registry(
                store,
                derived_metadata,
                branch_id=branch_id,
                experiment_id=experiment_id,
                contract=contract,
            )
            derived_registry_ref = f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{DERIVED_VARIABLE_REGISTRY}"
        else:
            derived_registry_ref = None
        for derived in derived_metadata:
            derived_name = str(derived.get("name") or "")
            if derived_name and derived_name not in config["variables"]:
                config["variables"].append(derived_name)
        config["variables"] = list(dict.fromkeys(config["variables"]))
        analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
            analysis_source_df,
            config["variables"],
        )
        delegator = get_analysis_delegator()
        result = delegator.run_analysis(analysis_df, analysis_type, config)
        source = str(result.get("source") or "unknown")
        analysis_result = result.get("result") or {}
        metrics = _metrics_from_live_analysis_result(
            analysis_result,
            row_count=int(entry.dataset.row_count or len(entry.dataframe)),
        )
        metrics.update(
            {
                "runner_generated": False,
                "contract_executed": True,
                "analysis_type": analysis_type,
                "source": source,
            }
        )

        artifact_name = (
            f"{BRANCH_RESULTS_PREFIX}/{branch_id}/experiments/"
            f"{experiment_id}_{_normalize_token(analysis_type) or 'analysis'}.json"
        )
        artifact_payload = {
            "branch_id": branch_id,
            "experiment_id": experiment_id,
            "analysis_contract": contract,
            "config": config,
            "source": source,
            "analysis_result": analysis_result,
            "plausibility_notes": plausibility_notes,
            "plausibility_summary": plausibility_summary,
            "derived_variables": derived_metadata,
            "derived_variable_notes": derived_notes,
            "derived_variable_registry_entries": derived_registry_entries,
            "derived_variable_registry_artifact": derived_registry_ref,
        }
        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, artifact_name).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        artifact_path = store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            artifact_name,
            artifact_payload,
        )

        if isinstance(analysis_result, dict) and analysis_result.get("error"):
            error = str(analysis_result.get("error"))
            markdown = "\n".join(
                [
                    f"# Autoresearch Contract Failed: {analysis_type}",
                    "",
                    f"- branch_id: `{branch_id}`",
                    f"- experiment_id: `{experiment_id}`",
                    f"- source: {source}",
                    f"- error: {error}",
                    f"- suggestion: {analysis_result.get('suggestion', '')}",
                ]
            )
            md_name = artifact_name.replace(".json", ".md")
            md_path = store.save(PipelinePhase.EXECUTE_EXPLORATION, md_name, markdown)
            return {
                "executed": True,
                "status": "failed",
                "artifacts": [
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{artifact_name}",
                    f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{md_name}",
                    *([derived_registry_ref] if derived_registry_ref else []),
                ],
                "metrics": metrics,
                "result_summary": f"live {analysis_type} failed: {error}",
                "error": error,
                "artifact_path": str(artifact_path),
                "markdown_path": str(md_path),
            }

        rendered = _format_advanced_analysis_output(
            analysis_type=analysis_type,
            source=source,
            analysis_result=analysis_result,
            artifact_path=artifact_path,
            automl_available=delegator.automl_available,
        )
        figures: list[dict[str, str]] = []
        figure_warnings: list[str] = []
        if bool(contract.get("create_figures")):
            from rde.interface.mcp.tools.analysis_tools import (
                _auto_create_advanced_analysis_figures,
            )

            figures, figure_warnings = _auto_create_advanced_analysis_figures(
                project=project,
                dataset=entry.dataset,
                dataframe=analysis_df,
                analysis_type=analysis_type,
                source=source,
                analysis_result=analysis_result,
                config=config,
            )
        else:
            figure_warnings.append(
                "Autoresearch branch runner skipped automatic figure generation; "
                "use create_visualization or set analysis_contract.create_figures=true "
                "when branch-specific figures are required."
            )
        if figures:
            rendered += "\n\n## Figures\n" + "\n".join(
                f"- `{figure['path']}` ({figure['plot_type']})" for figure in figures
            )
        if figure_warnings:
            rendered += "\n\n## Figure fallback warnings\n" + "\n".join(
                f"- {warning}" for warning in figure_warnings
            )
        if derived_notes:
            rendered += "\n\n## Branch-derived variables\n" + "\n".join(
                f"- {note}" for note in derived_notes
            )
            if derived_registry_path:
                rendered += (
                    "\n"
                    f"- registry: `{PipelinePhase.EXECUTE_EXPLORATION.value}/"
                    "derived_variable_registry.json`"
                )
        if plausibility_notes:
            rendered += "\n\n## 資料合理性防護\n" + "\n".join(
                f"- {note}" for note in plausibility_notes
            )
        md_name = artifact_name.replace(".json", ".md")
        md_path = store.save(PipelinePhase.EXECUTE_EXPLORATION, md_name, rendered)
        artifact_refs = [
            f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{artifact_name}",
            f"{PipelinePhase.EXECUTE_EXPLORATION.value}/{md_name}",
            *([derived_registry_ref] if derived_registry_ref else []),
            *[figure["path"] for figure in figures],
        ]
        summary = _summarize_advanced_analysis_result(analysis_result)
        if plausibility_summary:
            summary = f"{summary}; {plausibility_summary}"
        if derived_metadata:
            summary = f"{summary}; derived_variables={len(derived_metadata)}"
        return {
            "executed": True,
            "status": "completed",
            "artifacts": artifact_refs,
            "metrics": metrics,
            "result_summary": f"live {analysis_type}: source={source}; {summary}",
            "artifact_path": str(artifact_path),
            "markdown_path": str(md_path),
        }
    except Exception as exc:
        return {
            "executed": True,
            "status": "failed",
            "artifacts": [],
            "metrics": {
                "runner_generated": False,
                "contract_executed": True,
                "analysis_type": analysis_type,
                "n": int(entry.dataset.row_count or len(entry.dataframe)),
            },
            "result_summary": f"live {analysis_type} crashed: {exc}",
            "error": str(exc),
        }


def _metrics_from_live_analysis_result(
    analysis_result: Any,
    *,
    row_count: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"n": row_count, "sample_size": row_count}
    if not isinstance(analysis_result, dict):
        return metrics
    for key in ("nobs", "n_complete", "n_total", "count"):
        if key in analysis_result:
            metrics[key] = analysis_result[key]
            break
    if "propensity_score_summary" in analysis_result:
        summary = analysis_result.get("propensity_score_summary") or {}
        if isinstance(summary, dict) and "count" in summary:
            metrics["nobs"] = summary["count"]
    p_values = analysis_result.get("p_values")
    if isinstance(p_values, dict):
        numeric_p_values = [
            float(value)
            for name, value in p_values.items()
            if name != "const" and value is not None
        ]
        metrics["p_values"] = p_values
        if numeric_p_values:
            metrics["p_value"] = min(numeric_p_values)
    coefficients = analysis_result.get("coefficients")
    if isinstance(coefficients, dict):
        numeric_coefficients = [
            abs(float(value))
            for name, value in coefficients.items()
            if name != "const" and value is not None
        ]
        metrics["coefficients"] = coefficients
        if numeric_coefficients:
            metrics["effect_size"] = max(numeric_coefficients)
    odds_ratios = analysis_result.get("odds_ratios")
    if isinstance(odds_ratios, dict):
        metrics["odds_ratios"] = odds_ratios
        non_const = [
            float(value)
            for name, value in odds_ratios.items()
            if name != "const" and value is not None
        ]
        if non_const:
            metrics["odds_ratio"] = max(non_const, key=lambda value: abs(value - 1.0))
    if "r_squared" in analysis_result:
        metrics["r_squared"] = analysis_result["r_squared"]
        metrics.setdefault("effect_size", analysis_result["r_squared"])
    if "adj_r_squared" in analysis_result:
        metrics["adj_r_squared"] = analysis_result["adj_r_squared"]
    if "pseudo_r2" in analysis_result:
        metrics["pseudo_r2"] = analysis_result["pseudo_r2"]
        metrics.setdefault("effect_size", analysis_result["pseudo_r2"])
    common_support = analysis_result.get("common_support")
    if isinstance(common_support, dict):
        metrics["common_support"] = common_support
        if "in_support_fraction" in common_support:
            metrics["effect_size"] = common_support["in_support_fraction"]
    balance = analysis_result.get("balance_diagnostics")
    if isinstance(balance, dict):
        metrics["balance_diagnostics"] = balance
        smds: list[float] = []
        for item in balance.values():
            if isinstance(item, dict) and item.get("standardized_mean_difference") is not None:
                smds.append(abs(float(item["standardized_mean_difference"])))
        if smds:
            metrics["standardized_mean_difference"] = max(smds)
    weighted_balance = analysis_result.get("weighted_balance_diagnostics")
    if isinstance(weighted_balance, dict):
        metrics["weighted_balance_diagnostics"] = weighted_balance
        weighted_smds = [
            abs(float(item["standardized_mean_difference"]))
            for item in weighted_balance.values()
            if isinstance(item, dict) and item.get("standardized_mean_difference") is not None
        ]
        if weighted_smds:
            metrics["weighted_standardized_mean_difference"] = max(weighted_smds)
    matched_balance = analysis_result.get("matched_balance_diagnostics")
    if isinstance(matched_balance, dict):
        metrics["matched_balance_diagnostics"] = matched_balance
        matched_smds = [
            abs(float(item["standardized_mean_difference"]))
            for item in matched_balance.values()
            if isinstance(item, dict) and item.get("standardized_mean_difference") is not None
        ]
        if matched_smds:
            metrics["matched_standardized_mean_difference"] = max(matched_smds)
    if "matching_summary" in analysis_result:
        metrics["matching_summary"] = analysis_result["matching_summary"]
    if "power" in analysis_result:
        metrics["power"] = analysis_result["power"]
    if metrics.get("common_support") and metrics.get("standardized_mean_difference") is not None:
        support = metrics.get("common_support") or {}
        support_fraction = float(support.get("in_support_fraction") or 0.0)
        max_smd = abs(float(metrics.get("standardized_mean_difference") or 0.0))
        metrics.setdefault("evidence_score", min(95.0, 55.0 + support_fraction * 35.0))
        metrics.setdefault("stability_score", max(40.0, 90.0 - max_smd * 30.0))
    metrics.setdefault("sample_support", 75.0 if row_count >= 30 else 45.0)
    metrics.setdefault("alignment_score", 80.0)
    return metrics


def _runner_metrics_for_task(store: ArtifactStore, task: dict[str, Any]) -> dict[str, Any]:
    schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json") or {}
    row_count = 0
    if isinstance(schema, dict):
        try:
            row_count = int(schema.get("row_count") or schema.get("n_rows") or 0)
        except (TypeError, ValueError):
            row_count = 0
    variables = task.get("variables") or []
    metrics = {
        "runner_generated": True,
        "contract_executed": False,
        "n": row_count,
        "sample_size": row_count,
        "alignment_score": 70.0 if variables else 50.0,
        "sample_support": 75.0 if row_count >= 30 else 45.0,
    }
    if task.get("analysis_contract"):
        metrics["contract_available"] = True
    return metrics


def _update_autoresearch_budget(
    store: ArtifactStore,
    run_id: str,
    *,
    status: str | None = None,
    current_blocker: str | None = None,
) -> dict[str, Any]:
    queue = _project_autoresearch_queue(store, run_id)
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE) or {}
    budget = budget if isinstance(budget, dict) else {}
    completed = _count_autoresearch_status(queue, {"completed"})
    failed = _count_autoresearch_status(queue, {"failed", "crashed", "error"})
    remaining = _count_autoresearch_status(queue, {"pending", "running", "leased", "in_progress"})
    budget.update(
        {
            "run_id": run_id,
            "status": status or budget.get("status") or "running",
            "queued_tasks": len(queue),
            "completed_tasks": completed,
            "failed_tasks": failed,
            "remaining_tasks": remaining,
            "current_blocker": current_blocker,
            "updated_at": datetime.now().isoformat(),
        }
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
    return budget


def _complete_autoresearch_run_if_idle(project: Any, store: ArtifactStore, run_id: str) -> None:
    queue = _project_autoresearch_queue(store, run_id)
    remaining = _count_autoresearch_status(queue, {"pending", "running", "leased", "in_progress"})
    if remaining:
        return
    latest = _latest_autoresearch_run(store)
    if latest and latest.get("status") == "completed":
        return
    completed_at = datetime.now().isoformat()
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        AUTORESEARCH_RUNS_LOG,
        {
            "event_type": "autoresearch_run_completed",
            "run_id": run_id,
            "project_id": project.id,
            "status": "completed",
            "completed_at": completed_at,
        },
    )
    _update_autoresearch_budget(store, run_id, status="completed")
    _save_autoresearch_progress(store, run_id, "completed")


def _build_autoresearch_work_item(
    project_id: str,
    run_id: str,
    rank: int,
    suggestion: dict[str, Any],
) -> dict[str, Any]:
    priority_score = _branch_suggestion_priority(suggestion, rank)
    return {
        "event_type": "work_item_queued",
        "project_id": project_id,
        "run_id": run_id,
        "task_id": f"task_{uuid.uuid4().hex[:10]}",
        "status": "pending",
        "priority_score": priority_score,
        "rank": rank,
        "branch_id": "",
        "branch_type": suggestion.get("branch_type") or BranchType.HYPOTHESIS.value,
        "experiment_type": suggestion.get("experiment_type") or "exploratory",
        "hypothesis": suggestion.get("hypothesis") or "",
        "reason": suggestion.get("reason") or "",
        "variables": list(suggestion.get("variables") or []),
        "analysis_contract": dict(suggestion.get("analysis_contract") or {}),
        "suggestion": suggestion,
        "attempts": 0,
        "lease_owner": None,
        "lease_expires_at": None,
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "artifacts": [],
        "error": None,
    }


def _branch_suggestion_priority(suggestion: dict[str, Any], rank: int) -> int:
    branch_type = str(suggestion.get("branch_type") or "").lower()
    experiment_type = str(suggestion.get("experiment_type") or "").lower()
    priority = 100 - (max(rank, 1) - 1) * 5
    priority += {
        BranchType.SENSITIVITY.value: 18,
        BranchType.MISSING_STRATEGY.value: 16,
        BranchType.ADJUSTED_MODEL.value: 15,
        BranchType.PROPENSITY.value: 14,
        BranchType.SURVIVAL.value: 13,
        BranchType.ROC.value: 12,
        BranchType.REPEATED_MEASURES.value: 10,
        BranchType.SUBGROUP.value: 8,
        BranchType.VISUALIZATION.value: 2,
    }.get(branch_type, 0)
    if suggestion.get("analysis_contract"):
        priority += 6
    if experiment_type in {"logistic_regression", "survival_analysis", "propensity_score"}:
        priority += 4
    return max(priority, 1)


def _build_budget_state(
    run_event: dict[str, Any],
    queue_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_event.get("run_id"),
        "project_id": run_event.get("project_id"),
        "status": run_event.get("status", "running"),
        "started_at": run_event.get("started_at"),
        "deadline_at": run_event.get("deadline_at"),
        "max_tasks": run_event.get("max_tasks", len(queue_items)),
        "max_branches": run_event.get("max_branches", len(queue_items)),
        "max_failures": run_event.get("max_failures", 0),
        "max_minutes": run_event.get("max_minutes", 480),
        "queued_tasks": len(queue_items),
        "completed_tasks": 0,
        "failed_tasks": 0,
        "remaining_tasks": len(queue_items),
        "current_blocker": None,
        "updated_at": datetime.now().isoformat(),
    }


def _latest_autoresearch_run(store: ArtifactStore) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for event in _load_jsonl(store, AUTORESEARCH_RUNS_LOG):
        if str(event.get("event_type") or "").startswith("autoresearch_run_"):
            latest = event
    return latest


def _active_autoresearch_run(store: ArtifactStore) -> dict[str, Any] | None:
    status = _autoresearch_status_payload(store)
    if status.get("status") == "running":
        return status
    return None


def _project_autoresearch_queue(store: ArtifactStore, run_id: str) -> list[dict[str, Any]]:
    by_task: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in _load_jsonl(store, AUTORESEARCH_WORK_QUEUE):
        if str(item.get("run_id") or "") != run_id:
            continue
        task_id = str(item.get("task_id") or "")
        if not task_id:
            continue
        if task_id not in by_task:
            order.append(task_id)
        by_task[task_id] = dict(item)

    for event in _load_jsonl(store, AUTORESEARCH_WORK_EVENTS):
        if str(event.get("run_id") or "") != run_id:
            continue
        task_id = str(event.get("task_id") or "")
        if not task_id:
            continue
        if task_id not in by_task:
            order.append(task_id)
            by_task[task_id] = {
                "run_id": run_id,
                "task_id": task_id,
                "status": "unknown",
            }
        for key in (
            "status",
            "branch_id",
            "artifacts",
            "error",
            "started_at",
            "completed_at",
            "lease_owner",
            "lease_expires_at",
            "reclaimed_at",
            "priority_score",
        ):
            if key in event:
                by_task[task_id][key] = event[key]

    return [by_task[task_id] for task_id in order]


def _count_autoresearch_status(queue: list[dict[str, Any]], statuses: set[str]) -> int:
    return sum(1 for item in queue if str(item.get("status") or "") in statuses)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _autoresearch_status_payload(store: ArtifactStore) -> dict[str, Any]:
    latest = _latest_autoresearch_run(store)
    if latest is None:
        return {}
    run_id = str(latest.get("run_id") or "")
    queue = _project_autoresearch_queue(store, run_id)
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE) or {}
    budget = budget if isinstance(budget, dict) else {}
    pending_count = _count_autoresearch_status(queue, {"pending"})
    completed_count = _count_autoresearch_status(queue, {"completed"})
    failed_count = _count_autoresearch_status(queue, {"failed", "crashed", "error"})
    max_tasks = int(budget.get("max_tasks") or latest.get("max_tasks") or len(queue) or 0)
    budget_remaining = max(0, max_tasks - completed_count - failed_count)
    status = str(budget.get("status") or latest.get("status") or "unknown")
    current_blocker = budget.get("current_blocker") or budget.get("stop_reason")
    deadline_at = budget.get("deadline_at") or latest.get("deadline_at")
    deadline = _parse_iso_datetime(deadline_at)
    if status == "running" and deadline is not None and deadline < datetime.now():
        status = "expired"
        current_blocker = "deadline_expired"
        budget.update(
            {
                "status": "expired",
                "current_blocker": current_blocker,
                "updated_at": datetime.now().isoformat(),
            }
        )
        store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_BUDGET_STATE, budget)
        if latest.get("status") != "expired":
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                AUTORESEARCH_RUNS_LOG,
                {
                    "event_type": "autoresearch_run_expired",
                    "run_id": run_id,
                    "project_id": latest.get("project_id"),
                    "status": "expired",
                    "expired_at": datetime.now().isoformat(),
                    "reason": current_blocker,
                },
            )
    return {
        "run_id": run_id,
        "status": status,
        "queue_depth": pending_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "budget_remaining": budget_remaining,
        "current_blocker": current_blocker,
    }


def _save_autoresearch_progress(
    store: ArtifactStore,
    run_id: str,
    status: str,
    *,
    blocker: str | None = None,
) -> None:
    payload = _autoresearch_status_payload(store)
    event = {
        "event_type": "autoresearch_progress",
        "run_id": run_id,
        "status": status,
        "queue_depth": payload.get("queue_depth", 0),
        "completed_count": payload.get("completed_count", 0),
        "failed_count": payload.get("failed_count", 0),
        "budget_remaining": payload.get("budget_remaining", 0),
        "current_blocker": blocker or payload.get("current_blocker"),
        "timestamp": datetime.now().isoformat(),
    }
    store.save(PipelinePhase.EXECUTE_EXPLORATION, AUTORESEARCH_PROGRESS_EVENTS, event)


def _build_branch_suggestions(
    schema: dict[str, Any],
    plan: dict[str, Any],
    roles: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from rde.domain.services.common_medical_eda_pack import (
        build_common_medical_eda_suggestions,
    )

    return build_common_medical_eda_suggestions(schema, plan, roles)

    variables = schema.get("variables") if isinstance(schema, dict) else []
    variables = variables if isinstance(variables, list) else []
    analyses = plan.get("analyses") if isinstance(plan, dict) else []
    analyses = analyses if isinstance(analyses, list) else []
    roles = roles if isinstance(roles, dict) else {}
    variable_index = {
        str(var.get("name")): var
        for var in variables
        if isinstance(var, dict) and var.get("name")
    }

    def schema_type(name: str) -> str:
        var = variable_index.get(name) or {}
        return str(var.get("variable_type", "")).lower()

    def schema_unique_count(name: str) -> int | None:
        var = variable_index.get(name) or {}
        raw = var.get("n_unique")
        if raw is None:
            raw = var.get("unique_count")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def is_binary_schema_var(name: str, *, allow_unknown_categorical: bool = False) -> bool:
        var_type = schema_type(name)
        if var_type in {"binary", "boolean"}:
            return True
        if var_type in {"categorical", "factor", "ordinal", "integer", "numeric"}:
            n_unique = schema_unique_count(name)
            if n_unique == 2:
                return True
            if n_unique is None and allow_unknown_categorical and var_type in {"categorical", "factor"}:
                return True
        return False

    def is_multilevel_treatment_var(name: str) -> bool:
        var_type = schema_type(name)
        if var_type not in {"categorical", "factor", "ordinal", "integer", "numeric"}:
            return False
        n_unique = schema_unique_count(name)
        return n_unique is not None and 3 <= n_unique <= 12

    def is_outcome_like_var(name: str) -> bool:
        lowered = name.lower()
        if name in role_outcomes:
            return True
        if name in role_groups:
            return False
        if any(
            token in lowered
            for token in (
                "sex",
                "gender",
                "age",
                "height",
                "weight",
                "bmi",
                "baseline",
                "treat",
                "group",
                "arm",
                "exposure",
            )
        ):
            return False
        return any(
            token in lowered or token in name
            for token in (
                "outcome",
                "endpoint",
                "event",
                "status",
                "death",
                "mortality",
                "relapse",
                "progression",
                "readmission",
                "aki",
                "renal",
                "creatinine",
                "ngal",
                "kim",
                "cystatin",
                "結果",
                "事件",
                "死亡",
                "腎",
            )
        )

    numeric = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict)
        and str(var.get("variable_type", "")).lower() in {"continuous", "numeric", "integer"}
    ]
    categorical = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict)
        and str(var.get("variable_type", "")).lower()
        in {"binary", "boolean", "categorical", "factor", "ordinal"}
    ]
    missing = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict) and float(var.get("missing_rate") or 0) > 0
    ]
    all_names = [str(var.get("name")) for var in variables if isinstance(var, dict)]
    role_outcomes = _role_values(roles, ("outcome", "target", "dependent", "endpoint"))
    role_groups = _role_values(roles, ("group", "treatment", "exposure"))
    role_times = _role_values(roles, ("time", "duration", "followup", "survival_time"))
    role_events = _role_values(roles, ("event", "censor", "mortality", "relapse", "endpoint"))
    time_vars = [
        name
        for name in all_names
        if any(
            token in name.lower()
            for token in (
                "time",
                "day",
                "days",
                "month",
                "months",
                "follow",
                "duration",
                "survival",
                "os_",
                "dfs",
                "pfs",
            )
        )
    ]
    time_vars = list(dict.fromkeys(role_times + time_vars))
    event_vars = [
        name
        for name in all_names
        if any(
            token in name.lower()
            for token in (
                "death",
                "mortality",
                "event",
                "status",
                "relapse",
                "readmission",
                "censor",
                "progression",
            )
        )
        and is_binary_schema_var(name, allow_unknown_categorical=True)
    ]
    event_vars = list(dict.fromkeys(role_events + event_vars))
    treatment_vars = [
        name
        for name in categorical
        if any(token in name.lower() for token in ("treat", "group", "arm", "exposure"))
    ]
    treatment_vars = list(dict.fromkeys(role_groups + treatment_vars))
    repeated_sets = _repeated_measure_sets(numeric)

    suggestions: list[dict[str, Any]] = []

    def add(entry: dict[str, Any]) -> None:
        key = (
            entry.get("experiment_type"),
            tuple(entry.get("variables") or []),
            str(entry.get("hypothesis") or ""),
        )
        existing = {
            (
                item.get("experiment_type"),
                tuple(item.get("variables") or []),
                str(item.get("hypothesis") or ""),
            )
            for item in suggestions
        }
        if key not in existing:
            suggestions.append(entry)

    if missing:
        add(
            {
                "branch_type": BranchType.MISSING_STRATEGY.value,
                "experiment_type": "missing_strategy",
                "hypothesis": "Missing-data handling does not change the substantive conclusion.",
                "reason": "schema.json reports variables with missing_rate > 0.",
                "variables": missing[:5],
            }
        )

    planned_entries = [entry for entry in analyses if isinstance(entry, dict)] or [{}]
    for analysis in planned_entries:
        analysis_outcomes = _analysis_outcomes(analysis)
        outcome_vars = role_outcomes or analysis_outcomes or numeric[:1] or categorical[:1]
        group_var = analysis.get("group_variable") or analysis.get("group_var")
        if not group_var and role_groups:
            group_var = role_groups[0]
        if not group_var and treatment_vars:
            group_var = treatment_vars[0]
        plan_vars = list(dict.fromkeys(outcome_vars + ([str(group_var)] if group_var else [])))
        covariates = [
            var for var in list(dict.fromkeys(numeric + categorical)) if var not in set(plan_vars)
        ][:5]

        if plan_vars:
            add(
                {
                    "branch_type": BranchType.SENSITIVITY.value,
                    "experiment_type": "sensitivity",
                    "hypothesis": "Primary planned result is stable under a sensitivity check.",
                    "reason": "Locked analysis_plan.yaml contains a primary analysis that can be stress-tested.",
                    "variables": plan_vars,
                }
            )

        continuous_outcomes = [
            outcome
            for outcome in outcome_vars
            if schema_type(outcome) in {"continuous", "numeric", "integer"}
        ]
        if continuous_outcomes and covariates:
            add(
                {
                    "branch_type": BranchType.ADJUSTED_MODEL.value,
                    "experiment_type": "adjusted_model",
                    "hypothesis": (
                        f"Adjustment for plausible covariates preserves the planned signal "
                        f"for {continuous_outcomes[0]}."
                    ),
                    "reason": "schema.json contains covariates not already in the primary plan.",
                    "variables": list(dict.fromkeys([continuous_outcomes[0]] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "multiple_regression",
                        "target_variable": continuous_outcomes[0],
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )
            for outcome in continuous_outcomes[1:4]:
                add(
                    {
                        "branch_type": BranchType.ADJUSTED_MODEL.value,
                        "experiment_type": "adjusted_model",
                        "hypothesis": (
                            "Autoresearch covariate-adjusted model checks a secondary "
                            f"clinical outcome: {outcome}."
                        ),
                        "reason": (
                            "schema.json contains multiple clinical outcomes; autonomous "
                            "RDE should not stop after one adjusted model."
                        ),
                        "variables": list(dict.fromkeys([outcome] + covariates)),
                        "analysis_contract": {
                            "tool": "run_advanced_analysis",
                            "analysis_type": "multiple_regression",
                            "target_variable": outcome,
                            "covariates": covariates,
                            "create_figures": True,
                        },
                    }
                )

        binary_outcomes = [
            var
            for var in outcome_vars
            if (
                is_binary_schema_var(var, allow_unknown_categorical=False) or var in event_vars
            )
            and is_outcome_like_var(var)
        ]
        if binary_outcomes and covariates:
            add(
                {
                    "branch_type": BranchType.ADJUSTED_MODEL.value,
                    "experiment_type": "adjusted_model",
                    "hypothesis": "Adjusted model is required for the binary clinical endpoint.",
                    "reason": (
                        "Medical EDA should surface a generic adjusted-model branch even "
                        "when the executable model is logistic regression."
                    ),
                    "variables": list(dict.fromkeys(binary_outcomes[:1] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "logistic_regression",
                        "target_variable": binary_outcomes[0],
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )
            add(
                {
                    "branch_type": BranchType.ADJUSTED_MODEL.value,
                    "experiment_type": "logistic_regression",
                    "hypothesis": "Binary clinical outcome remains associated after adjustment.",
                    "reason": "Medical datasets often require adjusted odds ratios for binary endpoints.",
                    "variables": list(dict.fromkeys(binary_outcomes[:1] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "logistic_regression",
                        "target_variable": binary_outcomes[0],
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )

        if (
            group_var
            and is_binary_schema_var(str(group_var), allow_unknown_categorical=True)
            and covariates
        ):
            add(
                {
                    "branch_type": BranchType.PROPENSITY.value,
                    "experiment_type": "propensity_score",
                    "hypothesis": "Treatment/exposure groups remain comparable after propensity scoring.",
                    "reason": "Group imbalance is common in observational medical data.",
                    "variables": list(dict.fromkeys([str(group_var)] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "propensity_score",
                        "group_variable": str(group_var),
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )
        elif group_var and is_multilevel_treatment_var(str(group_var)) and covariates:
            safe_group = _normalize_token(str(group_var)) or "group"
            derived_group = f"{safe_group}_dominant_vs_other"
            add(
                {
                    "branch_type": BranchType.PROPENSITY.value,
                    "experiment_type": "propensity_score",
                    "hypothesis": (
                        "Dominant treatment/exposure level remains comparable with other "
                        "levels after propensity scoring."
                    ),
                    "reason": (
                        "The main exposure is multi-level, so autonomous RDE creates a "
                        "branch-local binary contrast before propensity scoring."
                    ),
                    "variables": list(dict.fromkeys([derived_group, str(group_var)] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "propensity_score",
                        "group_variable": derived_group,
                        "covariates": covariates,
                        "derived_variables": [
                            {
                                "name": derived_group,
                                "source": str(group_var),
                                "operation": "dominant_vs_other",
                            }
                        ],
                        "create_figures": True,
                    },
                }
            )

        if group_var and outcome_vars and covariates:
            add(
                {
                    "branch_type": BranchType.SUBGROUP.value,
                    "experiment_type": "subgroup_interaction",
                    "hypothesis": "Primary association is not driven by a clinically plausible subgroup.",
                    "reason": "Subgroup and interaction checks help detect heterogeneous effects.",
                    "variables": list(dict.fromkeys(outcome_vars + [str(group_var)] + covariates[:2])),
                }
            )

        if plan_vars:
            add(
                {
                    "branch_type": BranchType.VISUALIZATION.value,
                    "experiment_type": "visualization",
                    "hypothesis": "A visualization reveals whether the planned result is pattern-stable.",
                    "reason": "Visual inspection can detect outliers, imbalance, or non-linear structure.",
                    "variables": plan_vars,
                }
            )

    if time_vars and event_vars:
        add(
            {
                "branch_type": BranchType.SURVIVAL.value,
                "experiment_type": "survival_analysis",
                "hypothesis": "Time-to-event patterns are consistent across clinically relevant strata.",
                "reason": "schema.json contains candidate time and event variables.",
                "variables": list(dict.fromkeys(time_vars[:1] + event_vars[:1] + treatment_vars[:1])),
                "analysis_contract": {
                    "tool": "run_advanced_analysis",
                    "analysis_type": "survival_analysis",
                    "time_variable": time_vars[0],
                    "target_variable": event_vars[0],
                    "group_variable": treatment_vars[0] if treatment_vars else None,
                },
            }
        )

    score_vars = [name for name in numeric if any(token in name.lower() for token in ("score", "risk", "prob"))]
    if score_vars and event_vars:
        add(
            {
                "branch_type": BranchType.ROC.value,
                "experiment_type": "roc_auc",
                "hypothesis": "Risk score discrimination is adequate for the binary clinical endpoint.",
                "reason": "schema.json contains score-like predictors and event-like outcomes.",
                "variables": list(dict.fromkeys(score_vars[:1] + event_vars[:1])),
                "analysis_contract": {
                    "tool": "run_advanced_analysis",
                    "analysis_type": "roc_auc",
                    "score_variable": score_vars[0],
                    "target_variable": event_vars[0],
                },
            }
        )

    for repeated in repeated_sets[:2]:
        add(
            {
                "branch_type": BranchType.REPEATED_MEASURES.value,
                "experiment_type": "repeated_measures",
                "hypothesis": "Repeated clinical measurements change consistently over time.",
                "reason": "schema.json contains repeated-measure naming patterns.",
                "variables": repeated,
            }
        )
    return suggestions


def _analysis_outcomes(analysis: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("variables", "outcome_variables", "targets"):
        raw = analysis.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    for key in ("target_variable", "outcome", "dependent_variable"):
        if analysis.get(key):
            values.append(str(analysis[key]))
    return list(dict.fromkeys(values))


def _role_values(roles: dict[str, Any], role_names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key, raw in roles.items():
        normalized_key = str(key).lower()
        if any(role_name in normalized_key for role_name in role_names):
            if isinstance(raw, list):
                values.extend(str(item) for item in raw)
            elif isinstance(raw, dict):
                values.extend(str(item) for item in raw.values() if item)
            elif raw:
                values.append(str(raw))
        if isinstance(raw, str) and any(role_name in raw.lower() for role_name in role_names):
            values.append(str(key))
    return list(dict.fromkeys(values))


def _repeated_measure_sets(numeric: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    suffixes = (
        "_0h",
        "_1h",
        "_4h",
        "_6h",
        "_12h",
        "_24h",
        "_48h",
        "_baseline",
        "_followup",
        "_pre",
        "_post",
        "_visit1",
        "_visit2",
        "_visit_1",
        "_visit_2",
        "_month1",
        "_month3",
        "_month6",
        "_month12",
    )
    prefixes = ("pre_", "post_", "baseline_", "followup_")
    for name in numeric:
        lower = name.lower()
        matched_suffix = next((suffix for suffix in suffixes if lower.endswith(suffix)), None)
        if matched_suffix:
            base = name[: -len(matched_suffix)]
            groups.setdefault(base, []).append(name)
            continue
        matched_prefix = next((prefix for prefix in prefixes if lower.startswith(prefix)), None)
        if not matched_prefix:
            continue
        base = name[len(matched_prefix) :]
        groups.setdefault(base, []).append(name)
    return [items for items in groups.values() if len(items) >= 2]
