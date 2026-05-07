from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import yaml
import pytest

from rde.application.pipeline import PipelinePhase, REQUIRED_ARTIFACTS
from rde.interface.mcp.tools import branch_tools, ux_tools
from rde.interface.mcp.server import create_server


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "src" / "rde" / "interface" / "mcp" / "tools"
TOOL_POLICY = ROOT / "vscode-extension" / "src" / "toolPolicy.ts"
AGENT_CONTROL = ROOT / ".github" / "agent-control.yaml"
VSIX_STRICT_AGENT = ROOT / "vscode-extension" / "agents" / "eda.agent.md"
VSIX_RDE_PROMPT = ROOT / "vscode-extension" / "prompts" / "rde-13-phase.prompt.md"
ROOT_RDE_PROMPT = ROOT / ".github" / "prompts" / "rde-13-phase.prompt.md"
VSIX_REPORT_SKILL = ROOT / "vscode-extension" / "skills" / "report-generator" / "SKILL.md"
VSIX_EDA_SKILL = ROOT / "vscode-extension" / "skills" / "eda-workflow" / "SKILL.md"
STRICT_AGENT = ROOT / ".github" / "agents" / "eda.agent.md"
SYNC_FILES = [
    ROOT / ".claude" / "skills" / "eda-workflow" / "SKILL.md",
    ROOT / "AGENTS.md",
    ROOT / "SPEC.md",
    ROOT / ".github" / "prompts" / "rde-13-phase.prompt.md",
]
PHASE_PATH_SYNC_FILES = [
    ROOT / ".github" / "bylaws" / "pipeline-workflow.md",
    ROOT / "SPEC.md",
    ROOT / "scripts" / "pipeline_guard.py",
]
COUNT_SYNC_PATTERNS = {
    ROOT / ".github" / "copilot-instructions.md": r"(\d+)\s+MCP tools",
    ROOT / "vscode-extension" / "README.md": r"\*\*(\d+)\s+MCP Tools\*\*",
    ROOT / "vscode-extension" / "copilot-instructions.md": r"(\d+)\s+MCP tools",
}
DEPRECATED_ALIASES = {
    "align_concepts",
    "register_plan",
    "run_precheck",
    "execute_cleaning",
}
DEPRECATED_PHASE_PATHS = {
    "phase_01_intake",
    "phase_02_schema",
    "phase_03_concept",
    "phase_04_plan",
    "phase_05_precheck",
    "phase_06_execution",
    "phase_07_results",
    "phase_08_report",
    "phase_09_audit",
    "phase_10_improve",
}
BRANCH_TOOL_NAMES = {
    "open_exploration_branch",
    "suggest_branch_experiments",
    "start_autoresearch_run",
    "get_autoresearch_status",
    "stop_autoresearch_run",
    "resume_autoresearch_run",
    "run_autoresearch_next_task",
    "run_autoresearch_queue",
    "run_branch_experiment",
    "evaluate_branch",
    "promote_branch_to_plan_amendment",
    "discard_branch",
    "get_exploration_board",
}
BRANCH_ARTIFACT_NAMES = {
    branch_tools.EXPLORATION_BOARD,
    branch_tools.BRANCH_LOG,
    branch_tools.EXPERIMENT_LEDGER,
    branch_tools.BRANCH_EXPERIMENT_RESULTS_LOG,
    branch_tools.BRANCH_EVALUATIONS_LOG,
    branch_tools.BRANCH_PROMOTION_GATE,
    branch_tools.AUTORESEARCH_RUNS_LOG,
    branch_tools.AUTORESEARCH_WORK_QUEUE,
    branch_tools.AUTORESEARCH_WORK_EVENTS,
    branch_tools.AUTORESEARCH_BUDGET_STATE,
    branch_tools.AUTORESEARCH_STOP_DECISIONS,
    branch_tools.AUTORESEARCH_RESUME_DECISIONS,
    branch_tools.AUTORESEARCH_PROGRESS_EVENTS,
    f"{branch_tools.BRANCH_RESULTS_PREFIX}/{{branch_id}}.json",
    f"{branch_tools.BRANCH_RESULTS_PREFIX}/{{branch_id}}/experiments/{{experiment_id}}.json",
    f"{branch_tools.BRANCH_RESULTS_PREFIX}/{{branch_id}}_promotion_review.md",
    f"{branch_tools.BRANCH_RESULTS_PREFIX}/{{branch_id}}_promotion_gate.json",
    f"{branch_tools.PLAN_AMENDMENTS_PREFIX}/{{branch_id}}.json",
    f"{branch_tools.PLAN_AMENDMENTS_PREFIX}/{{branch_id}}.md",
    branch_tools.PLAN_AMENDMENTS_LEDGER,
}
UX_TOOL_NAMES = {
    "get_approval_card",
    "get_harness_dashboard",
    "build_artifact_index",
    "get_blocker_playbook",
}
UX_ARTIFACT_NAMES = {
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.APPROVAL_CARD_JSON}",
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.APPROVAL_CARD_MD}",
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.HARNESS_DASHBOARD}",
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.ARTIFACT_INDEX}",
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.BLOCKER_PLAYBOOK_JSON}",
    f"{PipelinePhase.PROJECT_SETUP.value}/{ux_tools.BLOCKER_PLAYBOOK_MD}",
}


def _extract_server_tool_names() -> set[str]:
    names: set[str] = set()

    for path in TOOLS_DIR.glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if isinstance(func, ast.Attribute) and func.attr == "tool":
                    if isinstance(func.value, ast.Name) and func.value.id == "server":
                        names.add(node.name)
    return names


def _load_agent_control() -> dict:
    return yaml.safe_load(AGENT_CONTROL.read_text(encoding="utf-8"))


def _extract_ts_string_array(source: str, constant_name: str) -> list[str]:
    pattern = rf"{constant_name}\s*=\s*\[(.*?)\]\s*as const;"
    match = re.search(pattern, source, re.DOTALL)
    assert match, f"Could not find TypeScript constant {constant_name}"
    body = match.group(1)
    values = re.findall(r"'([^']+)'", body)
    for spread_name in re.findall(r"\.\.\.([A-Z0-9_]+)", body):
        values.extend(_extract_ts_string_array(source, spread_name))
    return values


def test_vsx_allowlist_matches_registered_mcp_tools() -> None:
    server_tools = _extract_server_tool_names()
    ts_source = TOOL_POLICY.read_text(encoding="utf-8")
    vsx_allowlist = set(_extract_ts_string_array(ts_source, "RDE_MCP_TOOL_NAMES"))

    assert vsx_allowlist == server_tools


def test_live_mcp_tool_list_includes_project_bootstrap_chain() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    async def list_tool_names() -> set[str]:
        server = create_server()
        return {tool.name for tool in await server.list_tools()}

    live_tools = asyncio.run(list_tool_names())

    assert {"init_project", "run_intake", "build_schema", "align_concept"} <= live_tools
    assert len(live_tools) == len(_extract_server_tool_names())


def test_agent_control_declares_phase_08_branch_loop_contract() -> None:
    data = _load_agent_control()
    controls = data["phase_controls"]["exploration_branch_loop"]
    promotion_gate = controls["promotion_gate"]
    artifact_groups = controls["artifact_groups"]

    assert controls["phase"] == "phase_08_execute_exploration"
    assert controls["requires_locked_plan"] is True
    assert controls["allows_autonomous_branch_running"] is True
    assert set(controls["tools"]) == BRANCH_TOOL_NAMES
    assert set(controls["artifact_names"]) == BRANCH_ARTIFACT_NAMES
    assert "work_queue.jsonl" in artifact_groups["autoresearch_run_started"]
    assert "stop_decisions.jsonl" in artifact_groups["autoresearch_run_stopped"]
    assert "plan_amendments.jsonl" in artifact_groups["branch_promoted_after_audit_gate"]
    assert promotion_gate["tool"] == "promote_branch_to_plan_amendment"
    assert promotion_gate["requires_audit_gate"] is True
    assert promotion_gate["audit_tool"] == "evaluate_branch"
    assert promotion_gate["requires_prior_audit_event"] is True
    assert promotion_gate["blocks_stale_evaluation"] is True
    assert promotion_gate["requires_user_confirmation"] is True
    assert promotion_gate["confirmation_flag"] == "confirm"
    assert promotion_gate["blocks_auto_merge_to_primary_conclusions"] is True


def test_agent_control_declares_no_code_ux_harness_contract() -> None:
    data = _load_agent_control()
    controls = data["phase_controls"]["ux_harness"]

    assert controls["phase"] == PipelinePhase.PROJECT_SETUP.value
    assert set(controls["tools"]) == UX_TOOL_NAMES
    assert set(controls["output_artifacts"]) == UX_ARTIFACT_NAMES
    assert controls["must_not_execute_analysis"] is True
    assert controls["must_not_override_phase_gates"] is True


def test_vsix_docs_explain_autonomous_branches_and_promotion_confirmation() -> None:
    for path in [VSIX_STRICT_AGENT, VSIX_RDE_PROMPT]:
        content = path.read_text(encoding="utf-8")

        assert "Phase 8 may run autonomous YOLO exploration branches" in content
        assert "start_autoresearch_run" in content
        assert "get_autoresearch_status" in content
        assert "stop_autoresearch_run" in content
        assert "resume_autoresearch_run" in content
        assert "promote_branch_to_plan_amendment(confirm=true)" in content
        assert "audit gate" in content
        assert "explicit user confirmation" in content


def test_root_prompt_explains_autoresearch_and_does_not_require_workspace_reads() -> None:
    content = ROOT_RDE_PROMPT.read_text(encoding="utf-8")

    assert "start_autoresearch_run" in content
    assert "get_autoresearch_status" in content
    assert "stop_autoresearch_run" in content
    assert "resume_autoresearch_run" in content
    assert "promote_branch_to_plan_amendment(confirm=true)" in content
    assert "audit gate" in content
    assert "explicit user confirmation" in content
    assert "Read AGENTS.md" not in content
    assert ".github/agent-control.yaml" not in content


def test_workflow_docs_do_not_use_deprecated_tool_aliases() -> None:
    for path in SYNC_FILES:
        content = path.read_text(encoding="utf-8")
        for alias in DEPRECATED_ALIASES:
            assert alias not in content, f"Deprecated alias {alias} still appears in {path}"


def test_prompt_and_skill_reference_current_workflow_tool_names() -> None:
    prompt = (ROOT / ".github" / "prompts" / "rde-13-phase.prompt.md").read_text(encoding="utf-8")
    skill = (ROOT / ".claude" / "skills" / "eda-workflow" / "SKILL.md").read_text(encoding="utf-8")

    for name in [
        "align_concept",
        "register_analysis_plan",
        "check_readiness",
        "apply_cleaning",
    ]:
        assert name in prompt or name in skill


def test_tool_count_mentions_match_the_registered_server_count() -> None:
    expected = len(_extract_server_tool_names())

    for path, pattern in COUNT_SYNC_PATTERNS.items():
        content = path.read_text(encoding="utf-8")
        match = re.search(pattern, content)
        assert match, f"Could not find tool-count mention in {path}"
        assert int(match.group(1)) == expected
        assert "MCP Tools (32)" not in content
        assert "32 tools" not in content
        assert "39 tools" not in content.lower()
        assert "39 mcp tools" not in content.lower()
        assert "32 工具" not in content


def test_strict_eda_agent_exists_and_disables_generic_code_tools() -> None:
    raw = STRICT_AGENT.read_text(encoding="utf-8")
    frontmatter = raw.split("---", 2)[1]
    description = re.search(r'description:\s*"([^"]+)"', frontmatter)
    tools_match = re.search(r"tools:\s*\[(.*?)\]", frontmatter, re.DOTALL)

    assert description, "Missing description in strict EDA agent frontmatter"
    assert tools_match, "Missing tools list in strict EDA agent frontmatter"

    tools = set(re.findall(r"'([^']+)'", tools_match.group(1)))
    forbidden = {"editFiles", "runCommands", "search", "codebase", "runTasks", "runNotebooks"}

    assert not (tools & forbidden)
    assert "嚴格 EDA 模式" in description.group(1)
    assert "@rde" in raw


def test_phase_path_docs_and_scripts_use_current_phase_directory_names() -> None:
    for path in PHASE_PATH_SYNC_FILES:
        content = path.read_text(encoding="utf-8")
        for deprecated in DEPRECATED_PHASE_PATHS:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(deprecated)}(?![A-Za-z0-9_])"
            assert not re.search(
                pattern, content
            ), f"Deprecated phase path {deprecated} still appears in {path}"


def test_vsix_quick_commands_document_bootstrapped_workflows() -> None:
    agent = VSIX_STRICT_AGENT.read_text(encoding="utf-8")

    for snippet in [
        "Phase 4 is a two-step confirmation gate",
        "`propose_analysis_plan(confirm=false)`",
        "`propose_analysis_plan(confirm=true)`",
        "Phase 5+6 are completed by one confirmed `register_analysis_plan(confirm=true)` call",
        "combined Phase 5+6 review/lock require explicit user confirmation",
    ]:
        assert snippet in agent


def test_agent_control_phase4_confirmation_and_artifacts_match_pipeline() -> None:
    control = yaml.safe_load(AGENT_CONTROL.read_text(encoding="utf-8"))
    ideation = control["phase_controls"]["plan_ideation"]

    assert ideation["requires_user_confirmation"] is True
    assert ideation["confirmation_flag"] == "confirm"
    assert ideation["draft_call"] == "propose_analysis_plan(confirm=false)"
    assert ideation["confirmation_call"] == "propose_analysis_plan(confirm=true)"
    assert ideation["confirmation_sequence"] == "draft_then_user_review_then_confirm"
    for artifact in REQUIRED_ARTIFACTS[PipelinePhase.CREATIVE_IDEATION]:
        assert artifact in ideation["output_artifacts"]


def test_agent_control_documents_combined_phase5_phase6_lock() -> None:
    control = yaml.safe_load(AGENT_CONTROL.read_text(encoding="utf-8"))
    review = control["phase_controls"]["plan_completeness_review"]
    registration = control["phase_controls"]["plan_registration"]

    assert review["combined_with_plan_registration_when_confirmed"] is True
    assert review["same_tool_invocation_can_complete_phase_06"] is True
    assert registration["performed_by_same_confirmed_register_analysis_plan_call"] is True


def test_vsix_readme_has_single_current_phase_map() -> None:
    content = (ROOT / "vscode-extension" / "README.md").read_text(encoding="utf-8")

    assert "Current 0-12 Phase Map" not in content
    assert content.count("### 13-Phase Pipeline") == 1
    assert "| 12 | Auto-Improve | Final report and handoff |" in content


def test_vsix_report_generator_uses_current_phase_numbers() -> None:
    skill = VSIX_REPORT_SKILL.read_text(encoding="utf-8")

    assert "Phase 10 report assembly and export workflow" in skill
    assert "Phase 9 `collect_results()`" in skill
    assert "Phase 8 report assembly" not in skill
    assert "Phase 7 `collect_results()`" not in skill


def test_vsix_report_docs_do_not_call_candidates_publishable_before_audit() -> None:
    for path in [VSIX_REPORT_SKILL, VSIX_EDA_SKILL]:
        content = path.read_text(encoding="utf-8")
        assert "PUBLISHABLE" not in content
        assert "CANDIDATE_FINDING" in content or "candidate" in content.lower()


def test_rde_13_phase_prompts_disable_generic_analysis_tools() -> None:
    for path in [VSIX_RDE_PROMPT, ROOT_RDE_PROMPT]:
        raw = path.read_text(encoding="utf-8")
        frontmatter = raw.split("---", 2)[1]
        tools_match = re.search(r"tools:\s*\[(.*?)\]", frontmatter, re.DOTALL)

        assert tools_match, f"Missing tools list in {path} frontmatter"

        tools = set(re.findall(r"'([^']+)'", tools_match.group(1)))
        assert not (tools & {"codebase", "runCommands", "search"})


def test_root_and_vsix_rde_prompts_share_confirmation_contract() -> None:
    root = ROOT_RDE_PROMPT.read_text(encoding="utf-8")
    vsix = VSIX_RDE_PROMPT.read_text(encoding="utf-8")

    for snippet in [
        "propose_analysis_plan(confirm=false)",
        "propose_analysis_plan(confirm=true)",
        "two-step",
        "Phase 5+6",
        "register_analysis_plan(confirm=true)",
        "get_approval_card",
        "get_harness_dashboard",
        "build_artifact_index",
        "get_blocker_playbook",
        "Phase 9-12",
    ]:
        assert snippet in root
        assert snippet in vsix


def test_agent_facing_docs_use_phase4_two_step_confirmation() -> None:
    paths = [
        ROOT / ".github" / "copilot-instructions.md",
        ROOT / "vscode-extension" / "copilot-instructions.md",
        STRICT_AGENT,
        ROOT / "README.md",
    ]

    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "propose_analysis_plan(confirm=false)" in content
        assert "propose_analysis_plan(confirm=true)" in content
        assert "propose_analysis_plan()" not in content
        assert "Phase 4 requires `register_analysis_plan(confirm=true)`" not in content


def test_vsix_rde_13_phase_prompt_disables_generic_analysis_tools() -> None:
    raw = VSIX_RDE_PROMPT.read_text(encoding="utf-8")
    frontmatter = raw.split("---", 2)[1]
    tools_match = re.search(r"tools:\s*\[(.*?)\]", frontmatter, re.DOTALL)

    assert tools_match, "Missing tools list in VSIX RDE prompt frontmatter"

    tools = set(re.findall(r"'([^']+)'", tools_match.group(1)))
    assert not (tools & {"codebase", "runCommands", "search"})
