"""RDE MCP Server entry point.

Usage: python -m rde
"""

from rde.interface.mcp.server import create_server


def main() -> None:
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
