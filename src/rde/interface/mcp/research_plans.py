"""Immutable research protocols, revision diffs and explicit result lineage.

Catalog governance complements, never bypasses, the native execution phase lock.
Files are host-authorized local inputs; their bytes are independently verified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reference(Strict):
    plan_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class File(Strict):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)


class Request(Strict):
    op: Literal["draft", "read", "approve", "attach_results", "reuse", "bind_execution"]
    plan_id: str
    expected_sha256: str | None = None
    parent: Reference | None = None
    intent: Literal["initial", "revise", "append"] = "initial"
    reason: str = ""
    protocol: dict | None = None
    sources: list[File] | None = None
    reviewer: dict | None = None
    execution_id: str | None = None
    artifacts: list[File] | None = None
    dataset_id: str | None = None
    plan_file: File | None = None
    approval_file: File | None = None


def canonical_id(value):
    if str(UUID(value)) != value:
        raise ValueError("Expected canonical UUID")
    return value


def root(project, plan_id):
    path = project.artifacts_dir / "research_plans" / canonical_id(plan_id)
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink plan directory is not allowed")
    return path


def verify_file(record):
    path = Path(record["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Source must be an absolute regular file without symlinks")
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
        size = stream.seek(0, 2)
    if sha != record["sha256"] or size != record["bytes"]:
        raise ValueError("STALE_EVIDENCE: source or saved result changed")


def write_once(path, payload):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink receipt path is not allowed")
    record = {"payload": payload, "sha256": digest(payload)}
    if path.exists():
        if read_sealed(path) != record:
            raise ValueError("IMMUTABLE_RECORD: existing record differs")
        return record
    path.parent.mkdir(parents=True, exist_ok=True)
    import os

    # Publish a complete durable file atomically; no partial file can look committed.
    from uuid import uuid4

    temporary = path.with_name(f".{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as out:
            json.dump(record, out, ensure_ascii=False, allow_nan=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.link(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def read_sealed(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink receipt is not allowed")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["sha256"] != digest(record["payload"]):
        raise ValueError("CORRUPT_RECORD: receipt hash mismatch")
    return record


def differences(before, after, path=""):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                result.append({"path": pointer, "before": before.get(key), "after": after.get(key)})
            else:
                result.extend(differences(before[key], after[key], pointer))
        return result
    return [] if before == after else [{"path": path or "/", "before": before, "after": after}]


def read_plan(project, plan_id, expected=None):
    record = read_sealed(root(project, plan_id) / "plan.json")
    if expected is not None and record["sha256"] != expected:
        raise ValueError("STALE_PLAN: reviewed plan differs")
    return record


def execute(project, request):
    req = Request.model_validate(request)
    if req.op == "bind_execution":
        from rde.interface.mcp.research_execution import bind_execution

        return bind_execution(project, req)
    directory = root(project, req.plan_id)
    if req.op == "draft":
        if not req.protocol or not req.sources or not req.reason.strip():
            raise ValueError(
                "A complete protocol, verified source/schema files and revision reason are required"
            )
        for file in req.sources:
            verify_file(file.model_dump())
        protocol = req.protocol
        if not protocol.get("question") or not protocol.get("steps"):
            raise ValueError("Research question and prespecified execution steps are required")
        hashes = {file.sha256 for file in req.sources}
        if not {protocol.get("sourceHash"), protocol.get("schemaHash")} <= hashes:
            raise ValueError("Source and schema hashes must match independently verified files")
        if bool(req.parent) != (req.intent != "initial"):
            raise ValueError("A revision/append requires an exact parent reference")
        parent = read_plan(project, req.parent.plan_id, req.parent.sha256) if req.parent else None
        if req.parent and req.parent.plan_id == req.plan_id:
            raise ValueError("A new plan ID is required")
        payload = {
            "contract": "rde-research-plan-v1",
            "plan_id": req.plan_id,
            "protocol": protocol,
            "sources": [s.model_dump() for s in req.sources],
            "parent": req.parent.model_dump() if req.parent else None,
            "intent": req.intent,
            "reason": req.reason,
            "changes": differences(parent["payload"]["protocol"], protocol) if parent else [],
        }
        write_once(directory / "plan.json", payload)
    record = read_plan(project, req.plan_id, req.expected_sha256)
    if req.op in ("approve", "attach_results", "reuse"):
        if not req.expected_sha256:
            raise ValueError("Exact expected_sha256 is required")
        for file in record["payload"]["sources"]:
            verify_file(file)
    if req.op == "approve":
        if not req.reviewer or req.reviewer.get("kind") not in (
            "human",
            "agent",
            "prior_workbench_approval",
        ):
            raise ValueError("Explicit reviewer attribution is required")
        write_once(
            directory / "approval.json", {"plan_sha256": record["sha256"], "reviewer": req.reviewer}
        )
    approval = (
        read_sealed(directory / "approval.json") if (directory / "approval.json").exists() else None
    )
    if approval and approval["payload"]["plan_sha256"] != record["sha256"]:
        raise ValueError("Approval belongs to a different plan")
    if req.op in ("attach_results", "reuse"):
        if not approval:
            raise ValueError("PLAN_NOT_APPROVED")
        if req.op == "attach_results":
            if not req.execution_id or not req.artifacts:
                raise ValueError("Completed execution identity and artifacts are required")
            for artifact in req.artifacts:
                verify_file(artifact.model_dump())
            write_once(
                directory / "results" / f"{canonical_id(req.execution_id)}.json",
                {
                    "execution_id": req.execution_id,
                    "plan_sha256": record["sha256"],
                    "artifacts": [a.model_dump() for a in req.artifacts],
                    "kind": "executed",
                },
            )
        else:
            parent_ref = record["payload"]["parent"]
            if not parent_ref:
                raise ValueError("No parent plan to reuse")
            parent = read_plan(project, parent_ref["plan_id"], parent_ref["sha256"])
            # Exact scientific protocol equality. No inference from similar step names.
            if parent["payload"]["protocol"] != record["payload"]["protocol"]:
                raise ValueError(
                    "REUSE_INELIGIBLE: scientific protocol differs; a new execution is required"
                )
            origin = (
                root(project, parent_ref["plan_id"])
                / "results"
                / f"{canonical_id(req.execution_id)}.json"
            )
            results = read_sealed(origin)
            for artifact in results["payload"]["artifacts"]:
                verify_file(artifact)
            write_once(
                directory / "reuse" / f"{req.execution_id}.json",
                {
                    "kind": "reused_reference_only",
                    "origin": parent_ref,
                    "execution_id": req.execution_id,
                    "result_sha256": results["sha256"],
                    "artifacts": results["payload"]["artifacts"],
                },
            )
    results = [read_sealed(p) for p in sorted((directory / "results").glob("*.json"))]
    reuse = [read_sealed(p) for p in sorted((directory / "reuse").glob("*.json"))]
    parent_ref = record["payload"]["parent"]
    eligible = False
    available = []
    if parent_ref:
        parent = read_plan(project, parent_ref["plan_id"], parent_ref["sha256"])
        eligible = parent["payload"]["protocol"] == record["payload"]["protocol"]
        if eligible:
            available = [
                read_sealed(p)
                for p in sorted((root(project, parent_ref["plan_id"]) / "results").glob("*.json"))
            ]
    return {
        **record,
        "approval": approval,
        "results": results,
        "reuse": reuse,
        "reuse_eligible": eligible,
        "available_results": available,
    }
