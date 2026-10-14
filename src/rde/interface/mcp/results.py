"""Typed wire results and hash-pinned, project-scoped artifact access.

Human text is a display field. Clients must use status/error/data and artifact
references for control flow. A reference binds current bytes; changed mutable
artifacts fail stale reads instead of silently returning a different revision.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ResultError(BaseModel):
    code: str
    message: str
    detail: str = ""
    suggestion: str = ""
    retryable: bool = False


class ArtifactReference(BaseModel):
    artifact_id: str
    project_id: str
    relative_path: str
    sha256: str
    bytes: int
    revision: str
    role: Literal["schema", "intake", "analysis_plan", "artifact"] = "artifact"


class SourceReference(BaseModel):
    dataset_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)
    filename: str
    sheet_name: str | None


class ResultContext(BaseModel):
    project_id: str | None = None
    project_root: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)


class RdeResult(BaseModel):
    contract: Literal["rde-result-v1"] = "rde-result-v1"
    tool: str
    invocation_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["ok", "error"]
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    context: ResultContext = Field(default_factory=ResultContext)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    error: ResultError | None = None


class ToolFailure(str):
    """Keep readable domain messages while carrying explicit failure metadata."""

    def __new__(cls, text: str, error: ResultError):
        value = super().__new__(cls, text)
        value.error = error
        return value


def resolve_project(arguments: dict[str, Any]):
    from rde.application.session import get_session

    try:
        project = get_session().get_project(arguments.get("project_id"))
    except KeyError:
        return None
    dataset_id = arguments.get("dataset_id")
    if dataset_id and dataset_id not in project.dataset_ids:
        return None
    return project


def artifact_paths(project, *, include_operations=False) -> dict[str, Path]:
    """Never traverse symlinks or expose files outside the selected project."""
    if project is None:
        return {}
    root = project.output_dir.resolve()
    paths = {}
    directories = [root / "artifacts", root / "figures"]
    if include_operations:
        operations = root / ".rde_operations"
        if operations.is_dir() and not operations.is_symlink():
            directories.extend(
                p / "artifacts" for p in operations.iterdir() if p.is_dir() and not p.is_symlink()
            )
    for directory in directories:
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            resolved = path.resolve()
            if resolved.is_relative_to(root) and not any(
                parent.is_symlink() for parent in path.parents if parent != root
            ):
                paths[path.relative_to(root).as_posix()] = path
    return paths


def artifact_id(project_id: str, relative_path: str) -> str:
    return hashlib.sha256(f"{project_id}\0{relative_path}".encode()).hexdigest()


def artifact_role(relative_path: str) -> str:
    if relative_path.startswith(".rde_operations/"):
        relative_path = "/".join(relative_path.split("/")[3:])
    return {
        "artifacts/phase_01_data_intake/intake_report.json": "intake",
        "artifacts/phase_02_schema_registry/schema.json": "schema",
        "artifacts/phase_06_plan_registration/analysis_plan.yaml": "analysis_plan",
    }.get(relative_path, "artifact")


def artifact_reference(project, relative_path: str, path: Path) -> ArtifactReference:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return ArtifactReference(
        artifact_id=artifact_id(project.id, relative_path),
        project_id=project.id,
        relative_path=relative_path,
        sha256=digest,
        revision=digest,
        bytes=path.stat().st_size,
        role=artifact_role(relative_path),
    )


def fingerprints(project) -> dict[str, tuple[int, int, int]]:
    return {
        key: (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        for key, path in artifact_paths(project).items()
        for stat in [path.stat()]
    }


def project_record(project) -> ResultContext:
    if project is None:
        return ResultContext()
    intake = project.artifacts_dir / "phase_01_data_intake/intake_report.json"
    sources = []
    if (
        intake.is_file()
        and not intake.is_symlink()
        and intake.resolve().is_relative_to(project.output_dir.resolve())
    ):
        saved = json.loads(intake.read_text(encoding="utf-8"))
        if isinstance(saved.get("source"), dict):
            sources = [{"dataset_id": saved.get("dataset_id"), **saved["source"]}]
    return ResultContext(
        project_id=project.id,
        project_root=str(project.output_dir.resolve()),
        dataset_ids=list(project.dataset_ids),
        sources=sources,
    )


def make_result(tool: str, value: Any, project=None, before=None) -> RdeResult:
    error = value.error if isinstance(value, ToolFailure) else None
    message = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    data = value if isinstance(value, dict) else {}
    if isinstance(value, str) and not error:
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                data = decoded
        except (ValueError, TypeError):
            pass
    artifacts = []
    if project is not None:
        paths = artifact_paths(project)
        for key, path in paths.items():
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != (before or {}).get(key):
                artifacts.append(artifact_reference(project, key, path))
        # Bootstrap data comes from canonical persisted records, never markdown.
        record_paths = {
            "run_intake": "artifacts/phase_01_data_intake/intake_report.json",
            "build_schema": "artifacts/phase_02_schema_registry/schema.json",
        }
        if not error and tool in record_paths and record_paths[tool] in paths:
            path = paths[record_paths[tool]]
            data = json.loads(path.read_text(encoding="utf-8"))
            if not any(item.relative_path == record_paths[tool] for item in artifacts):
                artifacts.append(artifact_reference(project, record_paths[tool], path))
        # Idempotent protocol binding still returns its exact evidence bundle.
        # Durable invocation receipts must retain these files even on a replay
        # that did not change any mtime; absence is rejected by bind_execution.
        if (
            not error
            and tool == "research_plan"
            and data.get("schema") == "rde-research-execution-context-v1"
        ):
            for relative in (
                "artifacts/research_execution/context.json",
                "artifacts/research_execution/plan.json",
                "artifacts/research_execution/approval.json",
                "artifacts/phase_06_plan_registration/research_execution.json",
            ):
                if relative not in paths:
                    raise ValueError("Research execution binding evidence is missing")
                if not any(item.relative_path == relative for item in artifacts):
                    artifacts.append(artifact_reference(project, relative, paths[relative]))
    return RdeResult(
        tool=tool,
        status="error" if error else "ok",
        message=str(message),
        data=data,
        error=error,
        context=project_record(project),
        artifacts=artifacts,
    )


def read_artifact_page(
    project_id: str, reference_id: str, expected_sha256: str, offset: int = 0, limit: int = 65536
) -> dict:
    from rde.application.session import get_session

    if offset < 0 or not 1 <= limit <= 262144:
        raise ValueError("offset must be nonnegative; limit must be 1..262144 bytes")
    project = get_session().get_project(project_id)
    for key, path in artifact_paths(project, include_operations=True).items():
        if artifact_id(project.id, key) != reference_id:
            continue
        # Read and hash one byte snapshot; no hash/read race across independent opens.
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != expected_sha256:
                raise ValueError("STALE_ARTIFACT: artifact bytes differ from the pinned revision")
            size = stream.seek(0, 2)
            if offset > size:
                raise ValueError("offset exceeds artifact size")
            stream.seek(offset)
            chunk = stream.read(limit)
            stream.seek(0)
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
                raise ValueError("STALE_ARTIFACT: artifact changed during read")
        ref = ArtifactReference(
            artifact_id=reference_id,
            project_id=project.id,
            relative_path=key,
            sha256=digest,
            revision=digest,
            bytes=size,
            role=artifact_role(key),
        )
        return {
            "artifact": ref.model_dump(),
            "offset": offset,
            "encoding": "base64",
            "content_base64": base64.b64encode(chunk).decode("ascii"),
            "next_offset": offset + len(chunk) if offset + len(chunk) < size else None,
        }
    raise ValueError("ARTIFACT_NOT_FOUND: artifact does not belong to this project")
