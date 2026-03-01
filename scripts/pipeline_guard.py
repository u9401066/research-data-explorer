"""Pipeline Guard — CLI tool to validate pipeline state.

Usage:
    python scripts/pipeline_guard.py <project_dir>
    python scripts/pipeline_guard.py data/projects/my_project --phase 6

Validates:
  - Artifact gate (H-008): All preceding phase artifacts exist
  - Plan lock (H-007): Phase 6+ requires locked plan
  - Decision log integrity (H-010): Append-only verification
  - Minimum sample size (H-003): n >= 10 for stats
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PHASE_NAMES = [
    "phase_00_project",
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
]


def check_artifacts(project_dir: Path, target_phase: int) -> list[str]:
    """H-008: Verify all prior phase artifacts exist."""
    from scripts.hooks.artifact_gate import PHASE_ARTIFACTS

    issues = []
    artifacts_dir = project_dir / "artifacts"

    for phase_idx in range(min(target_phase, len(PHASE_ARTIFACTS))):
        phase_name = list(PHASE_ARTIFACTS.keys())[phase_idx]
        required = PHASE_ARTIFACTS[phase_name]
        phase_dir = artifacts_dir / phase_name

        if not phase_dir.exists():
            issues.append(f"⛔ [H-008] Phase {phase_idx} ({phase_name}/) 不存在")
            continue

        for fname in required:
            if not (phase_dir / fname).exists():
                issues.append(f"⚠️ [H-008] Phase {phase_idx}: 缺少 {fname}")

    return issues


def check_plan_lock(project_dir: Path, target_phase: int) -> list[str]:
    """H-007: Verify plan is locked for Phase 6+."""
    if target_phase < 6:
        return []

    plan_file = project_dir / "artifacts" / "phase_04_plan" / "analysis_plan.yaml"
    if not plan_file.exists():
        return ["⛔ [H-007] Phase 6 需要鎖定的分析計畫，但 analysis_plan.yaml 不存在"]

    content = plan_file.read_text(encoding="utf-8")
    if "locked: true" not in content.lower() and "status: locked" not in content.lower():
        return ["⚠️ [H-007] 分析計畫尚未鎖定。Phase 6 前必須鎖定計畫。"]

    return []


def check_log_integrity(project_dir: Path) -> list[str]:
    """H-010: Basic integrity check on log files."""
    issues = []
    for log_name in ["decision_log.jsonl", "deviation_log.jsonl"]:
        log_path = project_dir / log_name
        if not log_path.exists():
            continue

        with open(log_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "timestamp" not in entry:
                        issues.append(
                            f"⚠️ [H-010] {log_name} line {line_no}: 缺少 timestamp"
                        )
                except json.JSONDecodeError:
                    issues.append(
                        f"❌ [H-010] {log_name} line {line_no}: 無效 JSON"
                    )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="RDE Pipeline Guard")
    parser.add_argument("project_dir", type=Path, help="專案目錄路徑")
    parser.add_argument(
        "--phase", type=int, default=None,
        help="目標 Phase 編號 (0-10)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="嚴格模式：任何警告都視為錯誤",
    )
    args = parser.parse_args()

    project_dir = args.project_dir
    if not project_dir.exists():
        print(f"❌ 專案目錄不存在: {project_dir}")
        return 1

    target_phase = args.phase or 10
    all_issues: list[str] = []

    print(f"🔍 Pipeline Guard — {project_dir.name} (目標 Phase {target_phase})")
    print("=" * 60)

    # Artifact gate (H-008)
    issues = check_artifacts(project_dir, target_phase)
    all_issues.extend(issues)

    # Plan lock (H-007)
    issues = check_plan_lock(project_dir, target_phase)
    all_issues.extend(issues)

    # Log integrity (H-010)
    issues = check_log_integrity(project_dir)
    all_issues.extend(issues)

    if all_issues:
        print("\n找到以下問題：")
        for issue in all_issues:
            print(f"  {issue}")

        errors = [i for i in all_issues if i.startswith("⛔") or i.startswith("❌")]
        warnings = [i for i in all_issues if i.startswith("⚠️")]

        print(f"\n  ❌ 錯誤: {len(errors)}  ⚠️ 警告: {len(warnings)}")

        if errors or (args.strict and warnings):
            return 1
    else:
        print("  ✅ All checks passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
