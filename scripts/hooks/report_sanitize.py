"""H-006: Report output sanitization.

Pre-commit hook that checks report files for leaked sensitive paths,
absolute file paths, environment variables, etc.
"""

from __future__ import annotations

import re
import sys

SENSITIVE_PATTERNS = [
    (r"[A-Z]:\\Users\\[^\\]+\\", "Absolute Windows path with username"),
    (r"/home/[^/]+/", "Absolute Linux home path"),
    (r"/Users/[^/]+/", "Absolute macOS home path"),
    (r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+", "Credential pattern"),
    (r"(?i)bearer\s+[a-zA-Z0-9_\-.]+", "Bearer token"),
]


def check_report(filepath: str) -> list[str]:
    """Check a report file for sensitive content."""
    warnings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                for pattern, desc in SENSITIVE_PATTERNS:
                    if re.search(pattern, line):
                        warnings.append(
                            f"  Line {line_no}: {desc} — {line.strip()[:60]}"
                        )
    except (OSError, UnicodeDecodeError):
        pass
    return warnings


def main() -> int:
    exit_code = 0
    for filepath in sys.argv[1:]:
        warnings = check_report(filepath)
        if warnings:
            print(f"⚠️ [H-006] Sensitive content in {filepath}:")
            for w in warnings:
                print(w)
            exit_code = 1
    if exit_code:
        print("\n報告應清除所有敏感路徑。使用 run_audit() 的 H-006 自動清除功能。")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
