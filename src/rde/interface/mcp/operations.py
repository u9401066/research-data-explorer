"""Durable invocation receipts: replay only completed calls, never ambiguous effects."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from shutil import copyfile

from rde.infrastructure.persistence.durability import sync_existing_file
from rde.interface.mcp.research_plans import digest, read_sealed, write_once
from rde.interface.mcp.results import RdeResult, artifact_reference


def implementation_hash():
    root = Path(__file__).parents[2]
    return digest(
        {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


def begin(project, key, tool, arguments):
    if project is None or not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("INVALID_EXECUTION_KEY: a project and SHA256 execution key are required")
    directory = project.output_dir / ".rde_operations" / key
    if any(p.is_symlink() for p in [directory, *directory.parents]):
        raise ValueError("Symlink operation directory is not allowed")
    intent = {"tool": tool, "arguments": arguments, "implementation": implementation_hash()}
    if directory.exists():
        if not (directory / "intent.json").exists():
            raise ValueError("EXECUTION_INDETERMINATE: incomplete intent; do not repeat effects")
        old = read_sealed(directory / "intent.json")
        if old["payload"] != intent:
            raise ValueError("EXECUTION_CONFLICT: key arguments or implementation changed")
        if not (directory / "result.json").exists():
            raise ValueError(
                "EXECUTION_INDETERMINATE: invocation started without a committed result; inspect existing artifacts"
            )
        saved = read_sealed(directory / "result.json")
        result = RdeResult.model_validate(saved["payload"])
        for ref in result.artifacts:
            path = project.output_dir / ref.relative_path
            if any(p.is_symlink() for p in [path, *path.parents]):
                raise ValueError("CORRUPT_EXECUTION: symlink result")
            if hashlib.sha256(path.read_bytes()).hexdigest() != ref.sha256:
                raise ValueError("CORRUPT_EXECUTION: saved artifact changed")
        return directory, result
    # Exclusive directory creation serializes independent MCP processes too.
    directory.mkdir(parents=True, exist_ok=False)
    write_once(directory / "intent.json", intent)
    return directory, None


def finish(project, directory, result):
    snapshots = []
    for ref in result.artifacts:
        source = project.output_dir / ref.relative_path
        target = directory / "artifacts" / ref.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source, target)
        sync_existing_file(target)
        snapshot = artifact_reference(
            project, target.relative_to(project.output_dir).as_posix(), target
        )
        if snapshot.sha256 != ref.sha256 or snapshot.bytes != ref.bytes:
            raise ValueError("EXECUTION_INDETERMINATE: artifact changed while saving receipt")
        snapshot.role = ref.role
        snapshots.append(snapshot)
    result.artifacts = snapshots
    write_once(directory / "result.json", result.model_dump(mode="json"))
    return result


def operation_status(project):
    """Bounded metadata query; completion is backed by a sealed native receipt."""
    directory = project.output_dir / ".rde_operations"
    if not directory.exists():
        return []
    if directory.is_symlink():
        raise ValueError("Symlink operation directory is not allowed")
    result = []
    for path in sorted(directory.iterdir()):
        if not path.is_dir() or path.is_symlink():
            continue
        intent = read_sealed(path / "intent.json") if (path / "intent.json").exists() else None
        saved = read_sealed(path / "result.json") if (path / "result.json").exists() else None
        result.append(
            {
                "execution_key": path.name,
                "tool": intent["payload"]["tool"] if intent else None,
                "status": saved["payload"]["status"] if saved else "indeterminate",
                "invocation_id": saved["payload"]["invocation_id"] if saved else None,
                "receipt_sha256": saved["sha256"] if saved else None,
            }
        )
    return result
