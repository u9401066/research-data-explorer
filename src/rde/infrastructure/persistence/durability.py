"""Platform-specific flush primitives; never weaken immutable receipt checks.

Windows does not expose a portable directory fsync through Python's os.open.
File contents are still flushed before publication; skipping directory fsync
does not claim equivalent crash/power-loss durability on all filesystems.
"""

import os
import sys
from pathlib import Path


def sync_directory(path: Path) -> None:
    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_existing_file(path: Path) -> None:
    # Windows FlushFileBuffers needs a writable handle. Never truncate bytes.
    with path.open("r+b" if sys.platform == "win32" else "rb") as stream:
        os.fsync(stream.fileno())
