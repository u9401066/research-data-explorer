from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "src" / "rde" / "interface" / "mcp" / "tools"
TOOL_POLICY = ROOT / "vscode-extension" / "src" / "toolPolicy.ts"
STRICT_AGENT = ROOT / ".github" / "agents" / "eda.agent.md"
SYNC_FILES = [
    ROOT / ".claude" / "skills" / "eda-workflow" / "SKILL.md",
    ROOT / "AGENTS.md",
    ROOT / "SPEC.md",
    ROOT / ".github" / "prompts" / "rde-phase-0-10.prompt.md",
]
PHASE_PATH_SYNC_FILES = [
    ROOT / ".github" / "bylaws" / "pipeline-workflow.md",
    ROOT / "SPEC.md",
    ROOT / "scripts" / "pipeline_guard.py",
]
COUNT_SYNC_PATTERNS = {
    ROOT / ".github" / "copilot-instructions.md": r"(\d+)\s+MCP tools",
    ROOT / "vscode-extension" / "README.md": r"\*\*(\d+)\s+MCP Tools\*\*",
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


def _extract_ts_string_array(source: str, constant_name: str) -> list[str]:
    pattern = rf"{constant_name}\s*=\s*\[(.*?)\]\s*as const;"
    match = re.search(pattern, source, re.DOTALL)
    assert match, f"Could not find TypeScript constant {constant_name}"
    return re.findall(r"'([^']+)'", match.group(1))


def test_vsx_allowlist_matches_registered_mcp_tools() -> None:
    server_tools = _extract_server_tool_names()
    ts_source = TOOL_POLICY.read_text(encoding="utf-8")
    vsx_allowlist = set(_extract_ts_string_array(ts_source, "RDE_MCP_TOOL_NAMES"))

    assert vsx_allowlist == server_tools


def test_workflow_docs_do_not_use_deprecated_tool_aliases() -> None:
    for path in SYNC_FILES:
        content = path.read_text(encoding="utf-8")
        for alias in DEPRECATED_ALIASES:
            assert alias not in content, f"Deprecated alias {alias} still appears in {path}"


def test_prompt_and_skill_reference_current_workflow_tool_names() -> None:
    prompt = (ROOT / ".github" / "prompts" / "rde-phase-0-10.prompt.md").read_text(encoding="utf-8")
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
