from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_pipeline_guard_direct_script_entrypoint_works_outside_repo(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    phase_zero = project_dir / "artifacts" / "phase_00_project_setup"
    phase_zero.mkdir(parents=True)
    (phase_zero / "project.yaml").write_text("name: test\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "pipeline_guard.py"),
            str(project_dir),
            "--phase",
            "1",
            "--strict",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All checks passed" in result.stdout
