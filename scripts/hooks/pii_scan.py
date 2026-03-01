"""H-004/H-006: PII scan on output files.

Pre-commit hook that scans staged output files for potential PII
(names, emails, phone numbers, ID numbers, addresses).
"""

from __future__ import annotations

import re
import sys

# Patterns that suggest PII in output files
PII_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "Email address"),
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "Phone number (US)"),
    (r"\b09\d{2}[-]?\d{3}[-]?\d{3}\b", "Phone number (TW)"),
    (r"\b[A-Z]\d{9}\b", "TW National ID"),
    (r"\b\d{3}-?\d{2}-?\d{4}\b", "SSN pattern"),
    (r"(?i)\b(patient|病人|個案)\s*(name|姓名|id)\b", "Patient identifier field"),
]

# Patterns for sensitive paths (H-006)
PATH_PATTERNS = [
    (r"[A-Z]:\\Users\\[^\\]+", "Windows user path"),
    (r"/home/[^/]+", "Linux home path"),
    (r"/Users/[^/]+", "macOS home path"),
]


def scan_file(filepath: str) -> list[str]:
    """Scan a file for PII patterns. Returns list of warnings."""
    warnings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                for pattern, desc in PII_PATTERNS + PATH_PATTERNS:
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
        warnings = scan_file(filepath)
        if warnings:
            print(f"⚠️ [H-004/H-006] Potential PII in {filepath}:")
            for w in warnings:
                print(w)
            exit_code = 1
    if exit_code:
        print("\n請確認上述內容不含個人資料，或使用 H-006 清除敏感路徑。")
        print("如為誤報，可使用 `git commit --no-verify` 跳過（需記錄理由）。")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
