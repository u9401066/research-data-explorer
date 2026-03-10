"""H-008: Pipeline artifact gate check.

Pre-commit hook that verifies committed project directories
have consistent phase artifacts (no skipped phases).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Expected artifacts per phase (minimum required files)
# Keys must match PipelinePhase enum values in src/rde/application/pipeline/__init__.py
PHASE_ARTIFACTS = {
    "phase_00_project_setup": ["project.yaml"],
    "phase_01_data_intake": ["intake_report.json"],
    "phase_02_schema_registry": ["schema.json"],
    "phase_03_concept_alignment": ["concept_alignment.md"],
    "phase_04_plan_registration": ["analysis_plan.yaml"],
    "phase_05_pre_explore_check": ["readiness_checklist.json"],
    "phase_06_execute_exploration": ["decision_log.jsonl"],
    "phase_07_collect_results": ["results_summary.json"],
    "phase_08_report_assembly": ["eda_report.md"],
    "phase_09_audit_review": ["audit_report.json"],
    "phase_10_auto_improve": ["final_report.md"],
}


def check_project(project_dir: Path) -> list[str]:
    """Check a project directory for artifact consistency."""
    artifacts_dir = project_dir / "artifacts"
    if not artifacts_dir.exists():
        return []  # Not a pipeline project

    issues = []
    highest_phase = -1
    present_phases: dict[int, bool] = {}

    for phase_idx, (phase_name, required_files) in enumerate(PHASE_ARTIFACTS.items()):
        phase_dir = artifacts_dir / phase_name
        if phase_dir.exists():
            highest_phase = phase_idx
            present_phases[phase_idx] = True
            for fname in required_files:
                if not (phase_dir / fname).exists():
                    issues.append(
                        f"  Phase {phase_idx}: {phase_name}/ 缺少 {fname}"
                    )
        else:
            present_phases[phase_idx] = False

    # Check for skipped phases (H-008 artifact gate)
    for phase_idx in range(highest_phase):
        if not present_phases.get(phase_idx, False):
            phase_name = list(PHASE_ARTIFACTS.keys())[phase_idx]
            issues.append(
                f"  ⛔ Phase {phase_idx} ({phase_name}) 被跳過但後續 Phase 已存在"
            )

    return issues


def main() -> int:
    projects_dir = Path("data/projects")
    if not projects_dir.exists():
        return 0

    exit_code = 0
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        artifacts_dir = project_dir / "artifacts"
        if not artifacts_dir.exists():
            continue
        # Detect project by presence of Phase 0 artifact or project.yaml at root
        is_project = (
            (artifacts_dir / "phase_00_project_setup" / "project.yaml").exists()
            or (project_dir / "project.yaml").exists()
        )
        if is_project:
            issues = check_project(project_dir)
            if issues:
                print(f"❌ [H-008] Artifact gate issues in {project_dir.name}:")
                for issue in issues:
                    print(issue)
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
