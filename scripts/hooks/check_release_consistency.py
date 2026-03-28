"""Release consistency and internal data guard.

Pre-commit hook that prevents three classes of release mistakes:

1. Repo package version and VS Code extension version drifting apart.
2. Missing changelog coverage for the current synchronized version.
3. Accidental staging of local-only internal test datasets.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
VSCODE_PACKAGE = ROOT / "vscode-extension" / "package.json"
CHANGELOG = ROOT / "CHANGELOG.md"
BLOCKED_INTERNAL_PATHS = {
    "經超音波施打動脈導管收案總表V3xlsx.xlsx": (
        "Internal test dataset must stay local-only and must not be committed."
    ),
}


def read_repo_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def read_extension_version() -> str:
    data = json.loads(VSCODE_PACKAGE.read_text(encoding="utf-8"))
    return str(data["version"])


def changelog_has_version(version: str) -> bool:
    if not CHANGELOG.exists():
        return False
    pattern = re.compile(rf"^##\s+\[{re.escape(version)}\](?:\s|$|-)", re.MULTILINE)
    return bool(pattern.search(CHANGELOG.read_text(encoding="utf-8")))


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def find_blocked_staged_files(staged_files: list[str]) -> list[str]:
    blocked: list[str] = []
    for path in staged_files:
        normalized = path.strip().replace("\\", "/")
        if normalized in BLOCKED_INTERNAL_PATHS:
            blocked.append(normalized)
    return blocked


def main() -> int:
    errors: list[str] = []

    repo_version = read_repo_version()
    extension_version = read_extension_version()
    if repo_version != extension_version:
        errors.append(
            "Repo version and VS Code extension version are out of sync: "
            f"pyproject.toml={repo_version}, vscode-extension/package.json={extension_version}."
        )

    if not CHANGELOG.exists():
        errors.append(
            "CHANGELOG.md is missing. Add a changelog entry before committing release-related changes."
        )
    elif not changelog_has_version(repo_version):
        errors.append(
            f"CHANGELOG.md does not contain a section for version {repo_version}. "
            f"Add a heading like '## [{repo_version}]'."
        )

    staged_files = get_staged_files()
    for path in find_blocked_staged_files(staged_files):
        errors.append(f"Blocked internal dataset staged for commit: {path}")

    if errors:
        print("[Release Guard] Commit blocked:")
        for item in errors:
            print(f"- {item}")
        print(
            "\nExpected release rule: repo tag, pyproject version, and VSX version move together."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
