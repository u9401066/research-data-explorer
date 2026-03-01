"""DiscoverDataUseCase — Pipeline Step 1.

Scans a directory for data files, validates them against
hard constraints, and returns a list of loadable files.
"""

from __future__ import annotations

from pathlib import Path

from rde.application.dto import FileInfo
from rde.domain.policies.hard_constraints import HardConstraints
from rde.domain.ports import DataLoaderPort


class DiscoverDataUseCase:
    """Scan a directory and identify loadable data files."""

    def __init__(self, loader: DataLoaderPort) -> None:
        self._loader = loader

    def execute(self, directory: str | Path) -> list[FileInfo]:
        """Scan directory and return file info with constraint checks."""
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        metadata_list = self._loader.scan_directory(directory)
        results: list[FileInfo] = []

        for meta in metadata_list:
            # Apply Hard Constraints H-001, H-002
            size_check = HardConstraints.h001_file_size_guard(meta.file_size_bytes)
            format_check = HardConstraints.h002_format_whitelist(meta.file_format)

            is_loadable = size_check.passed and format_check.passed
            rejection = ""
            if not size_check.passed:
                rejection = size_check.message
            elif not format_check.passed:
                rejection = format_check.message

            results.append(
                FileInfo(
                    file_name=meta.file_path.name,
                    file_path=str(meta.file_path),
                    file_format=meta.file_format,
                    file_size_bytes=meta.file_size_bytes,
                    is_loadable=is_loadable,
                    rejection_reason=rejection,
                )
            )

        return results
