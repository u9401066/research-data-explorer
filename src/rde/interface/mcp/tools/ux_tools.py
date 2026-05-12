"""No-code UX harness tools for RDE agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools._shared import (
    ensure_project_context,
    fmt_error,
    fmt_success,
    log_tool_call,
    log_tool_error,
)


APPROVAL_CARD_JSON = "approval_card.json"
APPROVAL_CARD_MD = "approval_card.md"
HARNESS_DASHBOARD = "harness_dashboard.json"
ARTIFACT_INDEX = "artifact_index.json"
BLOCKER_PLAYBOOK_JSON = "blocker_playbook.json"
BLOCKER_PLAYBOOK_MD = "blocker_playbook.md"


def refresh_ux_harness_artifacts(
    project: Any,
    pipeline: Any,
    *,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Persist the no-code UX artifact bundle used by agent readiness gates."""

    store = store or ArtifactStore(project.artifacts_dir)
    approval = _build_approval_card(project, store, pipeline)
    store.save(PipelinePhase.PROJECT_SETUP, APPROVAL_CARD_JSON, approval)
    store.save(PipelinePhase.PROJECT_SETUP, APPROVAL_CARD_MD, _format_approval_card(approval))

    artifacts = _collect_artifact_entries(project)
    summary = pipeline.summary()
    dashboard = {
        "project_id": project.id,
        "project_name": project.name,
        "research_question": project.research_question,
        "progress": summary.get("progress"),
        "next_suggested": summary.get("next_suggested"),
        "plan_locked": bool(summary.get("plan_locked")),
        "completed_phases": summary.get("completed", []),
        "approval": approval,
        "artifact_count": len(artifacts),
    }
    store.save(PipelinePhase.PROJECT_SETUP, HARNESS_DASHBOARD, dashboard)

    indexed_artifacts = _collect_artifact_entries(project)
    artifact_index = {
        "project_id": project.id,
        "artifact_root": ".",
        "artifact_root_policy": "relative_to_project_artifacts_dir",
        "artifact_count": len(indexed_artifacts),
        "artifacts": indexed_artifacts,
    }
    store.save(PipelinePhase.PROJECT_SETUP, ARTIFACT_INDEX, artifact_index)

    blockers = _build_blockers(project, store, pipeline)
    blocker_payload = {"project_id": project.id, "blockers": blockers}
    store.save(PipelinePhase.PROJECT_SETUP, BLOCKER_PLAYBOOK_JSON, blocker_payload)
    store.save(PipelinePhase.PROJECT_SETUP, BLOCKER_PLAYBOOK_MD, _format_blocker_playbook(blockers))

    return {
        "approval": approval,
        "dashboard": dashboard,
        "artifact_index": artifact_index,
        "blockers": blockers,
    }


def register_ux_tools(server: Any) -> None:
    """Register no-code harness UX tools."""

    @server.tool()
    def get_approval_card(project_id: str | None = None) -> str:
        """Return the next explicit user approval card and persist it as an artifact."""

        log_tool_call("get_approval_card", {"project_id": project_id})
        ok, msg, project, store, pipeline = _ux_context(project_id)
        if not ok:
            return _format_bootstrap_approval_card(msg)
        assert project is not None
        assert store is not None
        assert pipeline is not None

        try:
            bundle = refresh_ux_harness_artifacts(project, pipeline, store=store)
            md = _format_approval_card(bundle["approval"])
            path = store.get_path(PipelinePhase.PROJECT_SETUP, APPROVAL_CARD_MD)
            return fmt_success(
                "Approval card prepared.",
                md + f"\n\n- artifact: `{_relative_artifact_path(path, project)}`",
            )
        except Exception as exc:
            log_tool_error("get_approval_card", exc)
            return fmt_error(f"get_approval_card failed: {exc}")

    @server.tool()
    def get_harness_dashboard(project_id: str | None = None) -> str:
        """Return a concise no-code dashboard for pipeline, approval, and artifacts."""

        log_tool_call("get_harness_dashboard", {"project_id": project_id})
        ok, msg, project, store, pipeline = _ux_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None
        assert pipeline is not None

        try:
            bundle = refresh_ux_harness_artifacts(project, pipeline, store=store)
            dashboard = bundle["dashboard"]
            approval = bundle["approval"]
            path = store.get_path(PipelinePhase.PROJECT_SETUP, HARNESS_DASHBOARD)
            lines = [
                "# Harness Dashboard",
                f"- project: {project.name}",
                f"- progress: {dashboard['progress']}",
                f"- next_suggested: {dashboard['next_suggested']}",
                f"- plan_locked: {dashboard['plan_locked']}",
                f"- pending_approval: {approval['status']}",
                f"- artifact_count: {dashboard['artifact_count']}",
                f"- artifact: `{_relative_artifact_path(path, project)}`",
            ]
            return "\n".join(lines)
        except Exception as exc:
            log_tool_error("get_harness_dashboard", exc)
            return fmt_error(f"get_harness_dashboard failed: {exc}")

    @server.tool()
    def build_artifact_index(project_id: str | None = None) -> str:
        """Build a recursive artifact index for no-code review and handoff."""

        log_tool_call("build_artifact_index", {"project_id": project_id})
        ok, msg, project, store, _ = _ux_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert store is not None

        try:
            from rde.application.session import get_session

            pipeline = get_session().get_pipeline(project.id)
            payload = refresh_ux_harness_artifacts(project, pipeline, store=store)["artifact_index"]
            path = store.get_path(PipelinePhase.PROJECT_SETUP, ARTIFACT_INDEX)
            return fmt_success(
                "Artifact index built.",
                "\n".join(
                    [
                        f"- artifact_count: {payload['artifact_count']}",
                        f"- artifact: `{_relative_artifact_path(path, project)}`",
                    ]
                ),
            )
        except Exception as exc:
            log_tool_error("build_artifact_index", exc)
            return fmt_error(f"build_artifact_index failed: {exc}")

    @server.tool()
    def get_blocker_playbook(project_id: str | None = None) -> str:
        """Return action-oriented blocker guidance for the current harness state."""

        log_tool_call("get_blocker_playbook", {"project_id": project_id})
        ok, msg, project, store, pipeline = _ux_context(project_id)
        if not ok:
            return _format_bootstrap_blocker_playbook(msg)
        assert project is not None
        assert store is not None
        assert pipeline is not None

        try:
            bundle = refresh_ux_harness_artifacts(project, pipeline, store=store)
            md = _format_blocker_playbook(bundle["blockers"])
            path = store.get_path(PipelinePhase.PROJECT_SETUP, BLOCKER_PLAYBOOK_MD)
            return md + f"\n\n- artifact: `{_relative_artifact_path(path, project)}`"
        except Exception as exc:
            log_tool_error("get_blocker_playbook", exc)
            return fmt_error(f"get_blocker_playbook failed: {exc}")


def _ux_context(
    project_id: str | None,
) -> tuple[bool, str, Any | None, ArtifactStore | None, Any | None]:
    ok, msg, project = ensure_project_context(project_id)
    if not ok or project is None:
        return False, msg, None, None, None
    from rde.application.session import get_session

    return (
        True,
        "ready",
        project,
        ArtifactStore(project.artifacts_dir),
        get_session().get_pipeline(project.id),
    )


def _build_approval_card(project: Any, store: ArtifactStore, pipeline: Any) -> dict[str, Any]:
    setup_sequence = [
        (
            PipelinePhase.DATA_INTAKE,
            "run_intake",
            "run_intake(project_id=...)",
            ["phase_01_data_intake/intake_report.json"],
            "Run Phase 1 intake before schema and concept alignment.",
        ),
        (
            PipelinePhase.SCHEMA_REGISTRY,
            "build_schema",
            "build_schema(project_id=..., dataset_id=...)",
            ["phase_02_schema_registry/schema.json"],
            "Build the schema registry before mapping concepts to variables.",
        ),
    ]
    for phase, tool, call, artifacts, purpose in setup_sequence:
        if phase not in pipeline.completed_phases:
            return {
                "project_id": project.id,
                "status": "blocked_prerequisite",
                "phase": phase.value,
                "tool": tool,
                "call": call,
                "requires_user_confirmation": False,
                "purpose": purpose,
                "review_artifacts": artifacts,
            }

    if getattr(pipeline, "is_quick_explore", False):
        if PipelinePhase.REPORT_ASSEMBLY not in pipeline.completed_phases:
            return {
                "project_id": project.id,
                "status": "next_action",
                "phase": PipelinePhase.REPORT_ASSEMBLY.value,
                "tool": "assemble_report",
                "call": (
                    'assemble_report(title="Quick Explore -- Not Audited", '
                    "allow_incomplete=true)"
                ),
                "requires_user_confirmation": False,
                "purpose": (
                    "Assemble a quick, explicitly non-audited overview report after "
                    "intake and schema."
                ),
                "review_artifacts": [
                    "phase_01_data_intake/intake_report.json",
                    "phase_02_schema_registry/schema.json",
                ],
            }
        return {
            "project_id": project.id,
            "status": "no_pending_approval",
            "phase": "",
            "tool": "",
            "call": "",
            "requires_user_confirmation": False,
            "purpose": "Quick Explore report is assembled; no explicit approval gate is pending.",
            "review_artifacts": [],
        }

    gates = [
        (
            PipelinePhase.CONCEPT_ALIGNMENT,
            "align_concept",
            "align_concept(confirm=true)",
            [
                "phase_03_concept_alignment/concept_alignment.md",
                "phase_03_concept_alignment/variable_roles.json",
            ],
            "Confirm concept-to-variable mapping before planning.",
        ),
        (
            PipelinePhase.CREATIVE_IDEATION,
            "propose_analysis_plan",
            "propose_analysis_plan(confirm=true)",
            [
                "phase_04_creative_ideation/greedy_analysis_candidates.md",
                "phase_04_creative_ideation/greedy_analysis_review.md",
            ],
            "Confirm the greedy blueprint before methodology review.",
        ),
        (
            PipelinePhase.PLAN_REGISTRATION,
            "register_analysis_plan",
            "register_analysis_plan(confirm=true)",
            [
                "phase_05_plan_completeness_review/analysis_plan_review.md",
                "phase_06_plan_registration/analysis_plan.yaml",
            ],
            "Confirm the reviewed plan before locking execution.",
        ),
    ]
    for phase, tool, call, artifacts, purpose in gates:
        result = pipeline.completed_phases.get(phase)
        if result is not None and result.user_confirmed:
            continue
        if phase == PipelinePhase.CREATIVE_IDEATION and result is None:
            return {
                "project_id": project.id,
                "status": "approval_required",
                "phase": phase.value,
                "tool": tool,
                "call": "propose_analysis_plan(confirm=false)",
                "requires_user_confirmation": False,
                "purpose": "Generate the greedy blueprint draft first; user confirmation happens after review.",
                "review_artifacts": [],
            }
        if phase == PipelinePhase.CREATIVE_IDEATION:
            call = "propose_analysis_plan(confirm=true)"
            purpose = "Confirm the reviewed greedy blueprint after inspecting Phase 4 artifacts."
        if result is None or not result.user_confirmed:
            return {
                "project_id": project.id,
                "status": "approval_required",
                "phase": phase.value,
                "tool": tool,
                "call": call,
                "requires_user_confirmation": True,
                "purpose": purpose,
                "review_artifacts": artifacts,
            }

    promotion_gate = store.load(PipelinePhase.EXECUTE_EXPLORATION, "branch_promotion_gate.json")
    if isinstance(promotion_gate, dict):
        gate = promotion_gate.get("promotion_gate") or {}
        if gate.get("can_promote"):
            branch_id = str(promotion_gate.get("branch_id") or "")
            return {
                "project_id": project.id,
                "status": "approval_required",
                "phase": PipelinePhase.EXECUTE_EXPLORATION.value,
                "tool": "promote_branch_to_plan_amendment",
                "call": f"promote_branch_to_plan_amendment(branch_id='{branch_id}', confirm=true)",
                "requires_user_confirmation": True,
                "purpose": "Confirm audited branch promotion before amending the locked plan.",
                "review_artifacts": [
                    "phase_08_execute_exploration/branch_promotion_gate.json",
                    f"phase_08_execute_exploration/branch_results/{branch_id}_promotion_review.md",
                ],
            }

    return {
        "project_id": project.id,
        "status": "no_pending_approval",
        "phase": "",
        "tool": "",
        "call": "",
        "requires_user_confirmation": False,
        "purpose": "No explicit approval gate is currently pending.",
        "review_artifacts": [],
    }


def _format_approval_card(card: dict[str, Any]) -> str:
    lines = [
        "# Approval Card",
        f"- status: {card['status']}",
        f"- phase: {card.get('phase') or 'none'}",
        f"- tool: {card.get('tool') or 'none'}",
        f"- call: `{card.get('call') or 'none'}`",
        f"- purpose: {card.get('purpose')}",
        f"- requires_user_confirmation: {card.get('requires_user_confirmation')}",
        "",
        "## Review Artifacts",
    ]
    artifacts = card.get("review_artifacts") or []
    if not artifacts:
        lines.append("- none")
    else:
        lines.extend(f"- `{artifact}`" for artifact in artifacts)
    return "\n".join(lines)


def _collect_artifact_entries(project: Any) -> list[dict[str, Any]]:
    root = Path(project.artifacts_dir)
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        phase = relative.split("/", 1)[0] if "/" in relative else ""
        entries.append(
            {
                "path": relative,
                "phase": phase,
                "suffix": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "modified_at": path.stat().st_mtime,
            }
        )
    return entries


def _build_blockers(project: Any, store: ArtifactStore, pipeline: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    approval = _build_approval_card(project, store, pipeline)
    if approval["status"] in {"approval_required", "blocked_prerequisite"}:
        blockers.append(
            {
                "id": f"approval:{approval['tool']}",
                "severity": (
                    "blocked" if approval["status"] == "blocked_prerequisite" else "action_required"
                ),
                "phase": approval["phase"],
                "tool": approval["tool"],
                "summary": approval["purpose"],
                "next_action": approval["call"],
                "artifacts": approval["review_artifacts"],
            }
        )

    summary = pipeline.summary()
    next_phase = summary.get("next_suggested")
    if next_phase and next_phase != "done":
        try:
            can_execute, reason = pipeline.can_execute(PipelinePhase(next_phase))
        except ValueError:
            can_execute, reason = True, ""
        if not can_execute:
            blockers.append(
                {
                    "id": f"phase_gate:{next_phase}",
                    "severity": "blocked",
                    "summary": reason,
                    "next_action": _suggest_action_for_blocker(reason),
                    "artifacts": [],
                }
            )

    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    if isinstance(results, dict):
        from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness

        readiness = _evaluate_report_readiness(results, store)
        if not readiness.get("ready"):
            blockers.append(
                {
                    "id": "report_readiness",
                    "severity": "blocked",
                    "summary": "Report is not production-ready.",
                    "next_action": "Run collect_results(), assemble_report(), run_audit(), and auto_improve() until readiness passes.",
                    "artifacts": ["phase_09_collect_results/results_summary.json"],
                    "missing": readiness.get("missing_requirements", []),
                }
            )
    return blockers


def _suggest_action_for_blocker(reason: str) -> str:
    lowered = reason.lower()
    if "phase_01" in lowered or "intake" in lowered:
        return "Run run_intake(project_id=...) before schema, concept alignment, or planning."
    if "phase_02" in lowered or "schema" in lowered:
        return "Run build_schema(project_id=..., dataset_id=...) before align_concept()."
    if "concept" in lowered:
        return "Run align_concept(confirm=false) to draft mapping, review concept_alignment.md, then call align_concept(confirm=true)."
    if "creative" in lowered or "ideation" in lowered:
        return "Run propose_analysis_plan(confirm=false) first; after reviewing greedy candidates, call propose_analysis_plan(confirm=true)."
    if "plan" in lowered or "locked" in lowered:
        return "Review analysis_plan_review.md, then call register_analysis_plan(confirm=true)."
    if "readiness" in lowered or "pre" in lowered:
        return "Run check_readiness() and address any readiness checklist blockers."
    return "Use get_pipeline_status() and the listed artifacts to resolve the phase gate."


def _format_bootstrap_blocker_playbook(reason: str) -> str:
    lines = [
        "# Blocker Playbook",
        "",
        "## 1. bootstrap:init_project",
        "- severity: blocked",
        f"- summary: {reason}",
        "- next_action: `init_project(name=..., data_dir=..., research_question=...)`",
        "- fallback: if `init_project` is not visible in the MCP tool list, reload VS Code (`Developer: Reload Window`) or restart the RDE MCP server so the extension refreshes the tool registry.",
        "- after_init: `run_intake(project_id=...)` -> `build_schema(project_id=..., dataset_id=...)` -> `align_concept(confirm=false)` -> review -> `align_concept(confirm=true)`",
    ]
    return "\n".join(lines)


def _format_bootstrap_approval_card(reason: str) -> str:
    lines = [
        "# Bootstrap Approval Card",
        "- status: blocked_prerequisite",
        "- phase: phase_00_project_setup",
        "- tool: init_project",
        "- call: `init_project(name=..., data_dir=..., research_question=...)`",
        "- purpose: Create an active RDE project before any intake, schema, concept alignment, or EDA planning tool can run.",
        "- requires_user_confirmation: false",
        f"- blocker: {reason}",
        "- fallback: if `init_project` is not visible in the MCP tool list, reload VS Code (`Developer: Reload Window`) or restart the RDE MCP server.",
        "",
        "## Review Artifacts",
        "- none",
    ]
    return "\n".join(lines)


def _format_blocker_playbook(blockers: list[dict[str, Any]]) -> str:
    lines = ["# Blocker Playbook"]
    if not blockers:
        lines.append("- no blockers detected")
        return "\n".join(lines)
    for index, blocker in enumerate(blockers, 1):
        lines.append(f"\n## {index}. {blocker['id']}")
        lines.append(f"- severity: {blocker['severity']}")
        lines.append(f"- summary: {blocker['summary']}")
        lines.append(f"- next_action: `{blocker['next_action']}`")
        artifacts = blocker.get("artifacts") or []
        if artifacts:
            lines.append("- artifacts: " + ", ".join(f"`{artifact}`" for artifact in artifacts))
        missing = blocker.get("missing") or []
        if missing:
            lines.append("- missing: " + ", ".join(str(item) for item in missing))
    return "\n".join(lines)


def _relative_artifact_path(path: Path, project: Any) -> str:
    try:
        return path.relative_to(project.artifacts_dir).as_posix()
    except ValueError:
        return str(path)
