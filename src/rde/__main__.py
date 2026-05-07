"""RDE MCP Server entry point.

Usage: python -m rde
"""

import os
import sys

from rde.interface.mcp.server import create_server


def _configure_utf8_runtime() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_utf8_runtime()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
