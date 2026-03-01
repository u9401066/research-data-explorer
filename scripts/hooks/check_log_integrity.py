"""H-010: Decision log append-only integrity check.

Pre-commit hook that ensures decision_log.jsonl and deviation_log.jsonl
are only appended to, never modified or truncated.
"""

from __future__ import annotations

import subprocess
import sys


def get_staged_diff(filepath: str) -> str:
    """Get the staged diff for a file."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--", filepath],
        capture_output=True,
        text=True,
    )
    return result.stdout


def check_append_only(filepath: str) -> bool:
    """Verify that a JSONL file has only additions, no deletions of existing lines."""
    diff = get_staged_diff(filepath)
    if not diff:
        return True

    for line in diff.splitlines():
        # Deletion of a content line (not metadata) is a violation
        if line.startswith("-") and not line.startswith("---"):
            stripped = line[1:].strip()
            if stripped and stripped.startswith("{"):
                print(f"❌ [H-010] Append-only violation in {filepath}")
                print(f"   Deleted line: {stripped[:80]}...")
                print("   decision_log 和 deviation_log 只能新增，不可修改或刪除。")
                return False
    return True


def main() -> int:
    exit_code = 0
    for filepath in sys.argv[1:]:
        if not check_append_only(filepath):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
