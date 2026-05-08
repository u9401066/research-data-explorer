"""Install or preview the Codex MCP config block for Research Data Explorer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SERVER_NAME = "research-data-explorer"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _remove_existing_server_block(text: str, server_name: str = SERVER_NAME) -> str:
    target_headers = {
        f"[mcp_servers.{server_name}]",
        f"[mcp_servers.{server_name}.env]",
    }
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        if stripped in target_headers:
            skipping = True
            continue
        if skipping and stripped.startswith("[") and stripped.endswith("]"):
            skipping = False
        if not skipping:
            kept.append(line)

    return "\n".join(kept).rstrip()


def build_config_block(repo_root: Path, *, uv_command: str) -> str:
    root = str(repo_root.resolve())
    return "\n".join(
        [
            "# Managed by Research Data Explorer. Remove this block to opt out.",
            f"[mcp_servers.{SERVER_NAME}]",
            f"command = {_toml_string(uv_command)}",
            (
                'args = ["run", "--directory", '
                f"{_toml_string(root)}, "
                '"python", "-m", "rde"]'
            ),
            f"cwd = {_toml_string(root)}",
            "",
            f"[mcp_servers.{SERVER_NAME}.env]",
            f"RDE_WORKSPACE = {_toml_string(root)}",
            'PYTHONUTF8 = "1"',
            'PYTHONIOENCODING = "utf-8"',
        ]
    )


def update_config_text(existing: str, repo_root: Path, *, uv_command: str) -> str:
    body = _remove_existing_server_block(existing)
    block = build_config_block(repo_root, uv_command=uv_command)
    if body:
        return body.rstrip() + "\n\n" + block + "\n"
    return block + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the updated config. Without this flag, prints a preview.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".codex" / "config.toml",
        help="Path to Codex config.toml.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the RDE repository root.",
    )
    parser.add_argument(
        "--uv-command",
        default="uv",
        help="uv executable Codex should use to launch the RDE MCP server.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser()
    existing = ""
    if config_path.exists():
        existing = config_path.read_text(encoding="utf-8")

    updated = update_config_text(existing, args.repo_root, uv_command=args.uv_command)
    if args.apply:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(updated, encoding="utf-8")
        print(f"Codex RDE MCP config updated: {config_path}")
    else:
        print(f"Codex RDE MCP config preview: {config_path}")
        print(updated, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
