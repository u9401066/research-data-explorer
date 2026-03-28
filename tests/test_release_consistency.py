from __future__ import annotations

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = ROOT / "scripts" / "hooks" / "check_release_consistency.py"
CHANGELOG = ROOT / "CHANGELOG.md"
GITIGNORE = ROOT / ".gitignore"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("check_release_consistency", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_and_extension_versions_match() -> None:
    hook = _load_hook_module()

    repo_version = hook.read_repo_version()
    extension_version = hook.read_extension_version()

    assert repo_version == extension_version
    assert re.fullmatch(r"\d+\.\d+\.\d+", repo_version)


def test_changelog_exists_and_covers_current_version() -> None:
    hook = _load_hook_module()

    assert CHANGELOG.exists()
    assert hook.changelog_has_version(hook.read_repo_version()) is True


def test_internal_dataset_is_gitignored_and_blocked() -> None:
    hook = _load_hook_module()
    ignored = GITIGNORE.read_text(encoding="utf-8")

    assert "經超音波施打動脈導管收案總表V3xlsx.xlsx" in ignored
    assert hook.find_blocked_staged_files(["經超音波施打動脈導管收案總表V3xlsx.xlsx"]) == [
        "經超音波施打動脈導管收案總表V3xlsx.xlsx"
    ]
