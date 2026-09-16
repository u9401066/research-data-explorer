"""Reviewed effects and governance metadata for the entire MCP tool surface.

Annotations are hints, never authorization. Gates remain in application code.
Unknown registrations fail closed so every new tool requires an explicit review.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolContract:
    phase: str
    gate: str
    effects: str
    read_only: bool = False
    destructive: bool = False
    open_world: bool = False


CONTRACTS = {
    "init_project": ToolContract("0", "name + mode validation", "project and UX artifacts"),
    "get_pipeline_status": ToolContract("all", "project exists", "status", True),
    "get_decision_log": ToolContract("all", "project exists", "decision log read", True),
    "get_deviation_log": ToolContract("all", "project exists", "deviation log read", True),
    "log_deviation": ToolContract("all", "project exists", "append deviation"),
    "scan_data_folder": ToolContract("1", "supported local files", "file metadata", True),
    "load_dataset": ToolContract("1", "format/size/PII", "session dataset"),
    "run_intake": ToolContract("1", "format/size/PII", "intake and datasets"),
    "build_schema": ToolContract("2", "intake + dataset scope", "schema and roles"),
    "profile_dataset": ToolContract("2", "dataset exists", "profile artifacts"),
    "assess_quality": ToolContract("2", "dataset exists", "quality artifacts"),
    "align_concept": ToolContract("3", "schema + human confirmation", "concept and roles"),
    "propose_analysis_plan": ToolContract(
        "4", "confirmed concept; draft then confirm", "draft plan"
    ),
    "register_analysis_plan": ToolContract("5-6", "review + human confirmation", "locked plan"),
    "check_readiness": ToolContract("7", "locked plan + prior artifacts", "readiness"),
    "suggest_cleaning": ToolContract(
        "8", "locked plan + readiness + quality", "session cleaning proposal"
    ),
    "apply_cleaning": ToolContract(
        "8",
        "locked plan + readiness + approved actions",
        "cleaned data and decision",
        destructive=True,
    ),
    "analyze_variable": ToolContract("8", "locked plan + readiness + sample size", "decision"),
    "compare_groups": ToolContract("8", "locked plan + readiness", "results and decision"),
    "correlation_matrix": ToolContract("8", "locked plan + readiness", "results and decision"),
    "generate_table_one": ToolContract("8", "locked plan + readiness", "table and decision"),
    "run_advanced_analysis": ToolContract(
        "8", "locked plan + readiness", "results and decision", open_world=True
    ),
    "run_repeated_measures": ToolContract(
        "8", "locked plan + readiness", "case ledger and decision"
    ),
    "open_exploration_branch": ToolContract("8", "locked plan + readiness", "branch event"),
    "suggest_branch_experiments": ToolContract(
        "8", "project context", "candidate suggestions", True
    ),
    "start_autoresearch_run": ToolContract(
        "8", "locked plan + readiness + budget", "run/queue/budget"
    ),
    "get_autoresearch_status": ToolContract("8", "project context", "progress event"),
    "stop_autoresearch_run": ToolContract("8", "governed project", "stop decision and queue"),
    "resume_autoresearch_run": ToolContract(
        "8", "governed project + remaining budget", "resume decision"
    ),
    "run_autoresearch_next_task": ToolContract(
        "8", "governed project + lease + budget", "experiment/evaluation", open_world=True
    ),
    "run_autoresearch_queue": ToolContract(
        "8", "governed project + lease + budget", "bounded experiments", open_world=True
    ),
    "run_branch_experiment": ToolContract("8", "governed branch", "experiment ledger"),
    "evaluate_branch": ToolContract("8", "live evidence", "evaluation and review"),
    "promote_branch_to_plan_amendment": ToolContract(
        "8", "fresh audit + human confirmation", "amendment, never auto-merge"
    ),
    "discard_branch": ToolContract("8", "branch exists", "discard event; evidence retained"),
    "get_exploration_board": ToolContract("8", "project context", "board snapshot"),
    "get_approval_card": ToolContract("all", "bootstrap allowed", "UX artifacts"),
    "get_harness_dashboard": ToolContract("all", "project exists", "UX artifacts"),
    "build_artifact_index": ToolContract("all", "project exists", "artifact index"),
    "get_blocker_playbook": ToolContract("all", "bootstrap allowed", "UX artifacts"),
    "collect_results": ToolContract("9", "execution complete or explicit force", "result summary"),
    "assemble_report": ToolContract(
        "10", "readiness or explicit unaudited preview", "report and provenance", destructive=True
    ),
    "create_visualization": ToolContract(
        "8/10", "execution gate + dataset", "figure and manifest", destructive=True
    ),
    "export_report": ToolContract("10", "report readiness", "export files", destructive=True),
    "run_audit": ToolContract("11", "project exists; diagnostics allowed", "audit artifacts"),
    "auto_improve": ToolContract("12", "audit complete", "final report", destructive=True),
    "export_final_report": ToolContract(
        "12", "audit + readiness", "export files", destructive=True
    ),
    "export_handoff": ToolContract("12", "audit + readiness", "handoff bundle", destructive=True),
    "verify_audit_trail": ToolContract("all", "project exists", "integrity result", True),
    "get_workflow_contract": ToolContract(
        "all", "server-resolved state", "next legal action", True
    ),
}


def public_contracts() -> dict:
    return {name: asdict(contract) for name, contract in sorted(CONTRACTS.items())}
