from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_skill_documents_rde_mcp_and_phase4_contract() -> None:
    skill = (ROOT / ".codex" / "skills" / "eda-workflow" / "SKILL.md").read_text(encoding="utf-8")

    assert "[mcp_servers.research-data-explorer]" in skill
    assert "scripts/configure_codex_mcp.py --apply" in skill
    assert "propose_analysis_plan(confirm=false)" in skill
    assert "propose_analysis_plan(confirm=true)" in skill
    assert skill.index("propose_analysis_plan(confirm=false)") < skill.index(
        "propose_analysis_plan(confirm=true)"
    )
    assert "propose_analysis_plan()\n" not in skill


def test_configure_codex_mcp_updates_config_without_duplicate_sections(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                'model = "gpt-5.5"',
                "",
                "[mcp_servers.research-data-explorer]",
                'command = "old"',
                "",
                "[mcp_servers.research-data-explorer.env]",
                'RDE_WORKSPACE = "old"',
                "",
                "[mcp_servers.other]",
                'command = "keep"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "configure_codex_mcp.py"),
            "--apply",
            "--config",
            str(config),
            "--repo-root",
            str(repo_root),
            "--uv-command",
            "uv",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    text = config.read_text(encoding="utf-8")
    assert "Codex RDE MCP config updated" in result.stdout
    assert text.count("[mcp_servers.research-data-explorer]") == 1
    assert text.count("[mcp_servers.research-data-explorer.env]") == 1
    assert "[mcp_servers.other]" in text
    assert 'args = ["run", "--directory"' in text
    assert f'"{repo_root}"'.replace("\\", "\\\\") in text


def test_codex_rde_smoke_can_list_mcp_tools() -> None:
    env = os.environ.copy()
    env["RDE_WORKSPACE"] = str(ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "codex_rde_smoke.py"),
            "--list-tools-only",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert "tools=49" in result.stdout
    assert "init_project" in result.stdout
    assert "propose_analysis_plan" in result.stdout


def test_codex_rde_smoke_runs_quick_explore_report(tmp_path: Path) -> None:
    env = os.environ.copy()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "codex_rde_smoke.py"),
            "--workspace",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert "workflow=ok" in result.stdout
    reports = list(
        tmp_path.glob("data/projects/*/artifacts/phase_10_report_assembly/eda_report.md")
    )
    assert reports
    assert "Quick Explore -- Not Audited" in reports[-1].read_text(encoding="utf-8")
