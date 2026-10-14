"""Exact approved protocol bindings for execution reports; never fits a model.

The catalog protocol and its approval are copied with their original bytes.
Researcher statements retain their attribution and are not clinical validation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.research_plans import (
    canonical_id,
    digest,
    read_sealed,
    verify_file,
    write_once,
)

RELATIVE_PATH = "artifacts/research_execution/context.json"
MARKER_PATH = "artifacts/phase_06_plan_registration/research_execution.json"
SCHEMA = "rde-research-execution-context-v1"


def _regular(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Research execution evidence must not use symlinks")
    if not path.is_file():
        raise ValueError("Research execution evidence file is missing")
    return path


def _bytes_once(path, data):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink execution evidence is not allowed")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _regular(path).read_bytes() != data:
            raise ValueError("IMMUTABLE_RECORD: imported protocol differs")
        return
    temporary = path.with_name(f".{uuid4()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _locked_plan(project, protocol):
    path = _regular(
        project.artifacts_dir / PipelinePhase.PLAN_REGISTRATION.value / "analysis_plan.yaml"
    )
    import yaml

    locked = yaml.safe_load(path.read_text(encoding="utf8"))
    if not isinstance(locked, dict) or locked.get("locked") is not True:
        raise ValueError("An exact locked execution plan is required")
    expected = {
        "project_id": project.id,
        "research_question": protocol["question"],
        "alpha": protocol["alpha"],
        "missing_strategy": protocol["missingStrategy"],
        "multiple_comparison_method": protocol["multiplicity"],
        "analyses": [step["planEntry"] for step in protocol["steps"]],
    }
    if any(locked.get(k) != v for k, v in expected.items()):
        raise ValueError("Locked execution methods/settings differ from the approved protocol")
    # Registering the identical plan on recovery refreshes created_at. Scientific
    # content and execution schedule must remain identical; timestamp is not identity.
    return {k: v for k, v in locked.items() if k != "created_at"}


def _dataset_binding(project, dataset_id):
    from rde.interface.mcp.tools._shared import ensure_dataset
    from rde.infrastructure.adapters.dataframe_lineage import bind_source

    if dataset_id not in project.dataset_ids:
        raise ValueError("Dataset does not belong to this execution project")
    ok, message, entry = ensure_dataset(dataset_id, project=project)
    if not ok or entry is None:
        raise ValueError(message)
    binding = bind_source(project, entry)
    if binding.get("status") != "verified":
        raise ValueError("Verified source-to-frame identity is required")
    return binding


def _verify_records(project, plan, approval, dataset_id, source_binding, intake):
    from rde.infrastructure.adapters.dataframe_lineage import verify_source_binding

    payload = plan["payload"]
    if payload.get("contract") != "rde-research-plan-v1":
        raise ValueError("Unsupported research protocol")
    if approval["payload"].get("plan_sha256") != plan["sha256"]:
        raise ValueError("Approval belongs to another protocol")
    if approval["payload"].get("reviewer", {}).get("kind") not in (
        "human",
        "agent",
        "prior_workbench_approval",
    ):
        raise ValueError("Explicit protocol approval is required")
    protocol = payload["protocol"]
    if not payload.get("reason", "").strip():
        raise ValueError("Saved researcher request is missing")
    for ref in payload["sources"]:
        verify_file(ref)
    hashes = {ref["sha256"] for ref in payload["sources"]}
    if not {protocol["sourceHash"], protocol["schemaHash"]} <= hashes:
        raise ValueError("Protocol source/schema identity differs from its verified files")
    if dataset_id not in project.dataset_ids or source_binding.get("dataset_id") != dataset_id:
        raise ValueError("Execution dataset ownership differs")
    if not isinstance(intake, dict) or intake.get("dataset_id") != dataset_id:
        raise ValueError("Execution intake belongs to another dataset")
    source = source_binding["source"]
    if source["sha256"] != protocol["sourceHash"] or any(
        intake.get("source", {}).get(k) != source[k] for k in ("sha256", "bytes")
    ):
        raise ValueError("Execution source differs from approved protocol/intake")
    verify_file({k: source[k] for k in ("path", "sha256", "bytes")})
    verify_source_binding(source_binding, project.output_dir)
    return _locked_plan(project, protocol)


def bind_execution(project, request):
    if not all(
        (
            request.expected_sha256,
            request.execution_id,
            request.dataset_id,
            request.plan_file,
            request.approval_file,
        )
    ):
        raise ValueError(
            "Exact protocol/approval files, hashes, execution and dataset are required"
        )
    canonical_id(request.plan_id)
    canonical_id(request.execution_id)
    inputs = {}
    records = {}
    for name, ref in (("plan", request.plan_file), ("approval", request.approval_file)):
        verify_file(ref.model_dump())
        raw = _regular(ref.path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.sha256 or len(raw) != ref.bytes:
            raise ValueError("Protocol evidence changed while importing")
        record = json.loads(raw)
        if digest(record["payload"]) != record["sha256"]:
            raise ValueError("CORRUPT_RECORD: imported receipt hash mismatch")
        inputs[name] = raw
        records[name] = record
    plan, approval = records["plan"], records["approval"]
    if plan["sha256"] != request.expected_sha256 or plan["payload"]["plan_id"] != request.plan_id:
        raise ValueError("STALE_PLAN: imported protocol differs from the exact reference")
    binding = _dataset_binding(project, request.dataset_id)
    store = ArtifactStore(project.artifacts_dir)
    intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
    locked = _verify_records(project, plan, approval, request.dataset_id, binding, intake)
    base = project.artifacts_dir / "research_execution"
    payload = {
        "schema": SCHEMA,
        "project_id": project.id,
        "execution_id": request.execution_id,
        "dataset_id": request.dataset_id,
        "plan_id": request.plan_id,
        "plan_sha256": plan["sha256"],
        "approval_sha256": approval["sha256"],
        "source_sha256": binding["source"]["sha256"],
        "source_binding": binding,
        "locked_plan": locked,
        "intake_sha256": digest(intake),
        "files": {
            name: {
                "path": f"{name}.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
            for name, raw in inputs.items()
        },
        "clinical_validation": "not_performed",
    }
    # Check immutable identity before creating any additional imported files.
    path = base / "context.json"
    if path.exists() and read_sealed(path) != {"payload": payload, "sha256": digest(payload)}:
        raise ValueError("IMMUTABLE_RECORD: execution context already bound differently")
    for name, raw in inputs.items():
        _bytes_once(base / f"{name}.json", raw)
    sealed = write_once(path, payload)
    write_once(
        project.output_dir / MARKER_PATH,
        {
            "project_id": project.id,
            "execution_id": request.execution_id,
            "context_sha256": sealed["sha256"],
            "relative_path": RELATIVE_PATH,
        },
    )
    execution_evidence(project, intake)
    return {
        k: payload[k]
        for k in (
            "schema",
            "project_id",
            "execution_id",
            "plan_id",
            "plan_sha256",
            "approval_sha256",
            "source_sha256",
            "clinical_validation",
        )
    } | {"context_sha256": sealed["sha256"], "relative_path": RELATIVE_PATH}


def execution_evidence(project, intake):
    """Read exact saved context and bytes, without parsing data or refitting models."""
    path = project.output_dir / RELATIVE_PATH
    marker_path = project.output_dir / MARKER_PATH
    if not path.exists() and not marker_path.exists() and not path.parent.exists():
        return None  # Native/legacy studies never silently acquire an approval.
    try:
        context = read_sealed(_regular(path))
        marker = read_sealed(_regular(marker_path))["payload"]
        data = context["payload"]
        if (
            data["schema"] != SCHEMA
            or data["project_id"] != project.id
            or marker
            != {
                "project_id": project.id,
                "execution_id": data["execution_id"],
                "context_sha256": context["sha256"],
                "relative_path": RELATIVE_PATH,
            }
        ):
            raise ValueError("Execution context identity differs")
        records = {}
        for name in ("plan", "approval"):
            ref = data["files"][name]
            if ref["path"] != f"{name}.json":
                raise ValueError("Unexpected protocol evidence path")
            file = path.parent / ref["path"]
            verify_file({**ref, "path": str(file)})
            records[name] = read_sealed(file)
            if records[name]["sha256"] != data[f"{name}_sha256"]:
                raise ValueError("Imported protocol/approval identity differs")
        if records["plan"]["payload"]["plan_id"] != data["plan_id"]:
            raise ValueError("Protocol belongs to another plan")
        if digest(intake) != data["intake_sha256"]:
            raise ValueError("Execution intake changed after binding")
        locked = _verify_records(
            project,
            records["plan"],
            records["approval"],
            data["dataset_id"],
            data["source_binding"],
            intake,
        )
        if (
            locked != data["locked_plan"]
            or data["source_sha256"] != data["source_binding"]["source"]["sha256"]
        ):
            raise ValueError("Execution methods/source changed after binding")
        return {**data, **records, "context_sha256": context["sha256"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"RESEARCH_REPORT_EVIDENCE_INVALID: {error}") from error


def _text(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("<", "&lt;").replace("|", "\\|")


def execution_markdown(evidence):
    protocol = evidence["plan"]["payload"]["protocol"]
    lines = [
        "### 本次核准計畫的研究定義與假設",
        "",
        "以下內容來自本次執行精確綁定的核准計畫；來源陳述、研究者指定假設與限制不代表已經工具或臨床驗證。",
        f"- 研究問題：{_text(protocol['question'])}",
        f"- 計畫版本：{evidence['plan_id']}；本次執行：{evidence['execution_id']}。",
    ]
    labels = {
        "studyDesign": "研究設計與分析假設",
        "population": "研究族群與分析單位",
        "endpointTime": "終點與時間定義",
    }
    for key, value in protocol.get("researchDetails", {}).items():
        lines.append(f"- {labels.get(key, key)}：{_text(value)}")
    lines += ["", "#### 核准範圍與限制", ""]
    lines += [f"- {_text(value)}" for value in protocol.get("limitations", [])]
    if protocol.get("sampleSizeBasis"):
        lines += [f"- 樣本數規劃依據（原計畫紀錄）：{_text(protocol['sampleSizeBasis'])}"]
    lines += [
        "",
        "#### 研究者提供的原始定義與需求（原文）",
        "",
        "下列是已封存計畫 reason 中的來源陳述，包含原文提供的代碼／單位等定義；不是新計算結果，也不表示全部延伸需求都已執行。",
        "",
    ]
    # Preserve researcher wording and paragraph boundaries; prevent Markdown from
    # promoting instructions/links into renderer actions or new document headings.
    import html
    import re

    reason = html.escape(evidence["plan"]["payload"]["reason"], quote=False)
    reason = re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", reason)
    lines += [
        reason,
        "",
        "#### 計畫與來源追溯",
        "",
        f"- 分析輸入 SHA-256：{evidence['source_sha256']}。",
        f"- 核准計畫 SHA-256：{evidence['plan_sha256']}。",
        f"- 核准收據 SHA-256：{evidence['approval_sha256']}。",
        f"- 本次執行綁定 SHA-256：{evidence['context_sha256']}。",
        "- clinical_validation：not_performed；計畫核准與來源核對不證明研究假設、群聚獨立性或臨床適用性。",
    ]
    return "\n".join(lines)
