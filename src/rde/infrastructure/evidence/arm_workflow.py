"""Immutable, approved source-arm preparation, separate from patient-level EDA."""

import csv
import json
import sys
from importlib.metadata import version
from pathlib import Path

from pydantic import TypeAdapter

from rde.domain.models import evidence_arms as contract
from rde.infrastructure.evidence import arm_preparation as engine
from rde.infrastructure.evidence import arm_source
from rde.infrastructure.evidence import workflow as w
from rde.infrastructure.prediction.splits import digest

ADAPTER = TypeAdapter(contract.ArmRequest)
MAX_JSON = 16 * 1024 * 1024


def implementation():
    return {
        "source_sha256": {
            name: w.file_hash(Path(module.__file__))
            for name, module in {
                "contract": contract,
                "source_reader": arm_source,
                "calculator": engine,
                "workflow": sys.modules[__name__],
                "integrity_helpers": w,
            }.items()
        },
        "python": sys.version.split()[0],
        "versions": {
            name: version(name) for name in ("research-data-explorer", "openpyxl", "pydantic")
        },
    }


def directory(project, preparation_id):
    w.canonical_id(preparation_id)
    return w.safe_path(
        project.output_dir.resolve(), f"artifacts/evidence_arm_preparation/{preparation_id}"
    )


def _json(path, value):
    w.require(
        len(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")) + 1
        <= MAX_JSON,
        "arm record exceeds 16 MiB; narrow the preparation",
    )
    w.write_new(path, value)


def _inventory(root, names):
    return {
        name: {
            "bytes": w.safe_path(root, name).stat().st_size,
            "sha256": w.file_hash(w.safe_path(root, name)),
        }
        for name in names
    }


def _verify_files(root, files):
    w.require(isinstance(files, dict) and 1 <= len(files) <= 10, "invalid arm file inventory")
    for name, info in files.items():
        path = w.safe_path(root, name)
        w.require(
            path.is_file()
            and path.stat().st_size == info["bytes"]
            and path.stat().st_size <= arm_source.MAX_BYTES,
            "arm evidence file size changed",
        )
        w.require(w.file_hash(path) == info["sha256"], "arm evidence file SHA256 changed")


def read_plan(project, preparation_id, expected=None):
    root = directory(project, preparation_id)
    plan = w.read_sealed(w.safe_path(root, "plan.json"))
    w.require(
        plan.get("schema") == "binary-arm-plan-v1"
        and plan.get("project_id") == project.id
        and plan.get("preparation_id") == preparation_id,
        "arm plan identity differs",
    )
    w.require(
        expected is None or plan["receipt_sha256"] == expected,
        "arm plan differs from reviewed SHA256",
    )
    w.require(
        set(plan["files"]) == {"source/" + plan["filename"], "grid.json", "review.json"},
        "arm source closure is incomplete",
    )
    _verify_files(root, plan["files"])
    w.require(
        plan["source_sha256"] == plan["files"]["source/" + plan["filename"]]["sha256"],
        "arm source identity differs",
    )
    w.require(
        digest(plan["specification"]) == plan["specification_sha256"], "arm specification differs"
    )
    for path in root.rglob("*"):
        w.safe_path(root, path.relative_to(root).as_posix())
        if path.is_file() and not path.relative_to(root).as_posix().startswith("runs/"):
            w.require(
                path.relative_to(root).as_posix() in {*plan["files"], "plan.json", "approval.json"},
                "unexpected file in arm plan closure",
            )
    return plan


def inspect(project, request):
    """Read exact source coordinates before asking the reviewer to map columns."""
    w.require(Path(request.filename).name == request.filename, "plain source filename required")
    path = w.safe_path(
        project.output_dir.resolve(),
        f"incoming/evidence-arms/{request.preparation_id}/{request.filename}",
    )
    w.require(
        path.is_file() and path.stat().st_size <= arm_source.MAX_BYTES,
        "missing or oversized incoming arm source",
    )
    data = path.read_bytes()
    w.require(
        w.sha(data) == request.source_sha256, "incoming arm source differs from requested SHA256"
    )
    grid = arm_source.source_grid(data, request.filename, request.selection)
    text = json.dumps(grid, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    w.require(len(text.encode("utf-8")) <= MAX_JSON, "source grid exceeds the 16 MiB review budget")
    hashed = w.sha(text.encode("utf-8"))
    w.require(
        request.expected_text_sha256 is None or request.expected_text_sha256 == hashed,
        "arm inspection differs from pinned text SHA256",
    )
    w.require(request.text_offset <= len(text), "text offset exceeds the source grid")
    end = min(len(text), request.text_offset + request.text_limit)
    return {
        "source_sha256": request.source_sha256,
        "text_sha256": hashed,
        "text_offset": request.text_offset,
        "text_total_chars": len(text),
        "text_excerpt": text[request.text_offset : end],
        "next_text_offset": end if end < len(text) else None,
        "scope": "Source inspection only; no draft, eligibility decision, approval or calculation.",
    }


def draft(project, request):
    root = directory(project, request.preparation_id)
    spec = request.specification
    incoming = w.safe_path(
        project.output_dir.resolve(),
        f"incoming/evidence-arms/{request.preparation_id}/{request.filename}",
    )
    w.require(Path(request.filename).name == request.filename, "plain source filename required")
    if root.exists():
        plan = read_plan(project, request.preparation_id)
        w.require(
            plan["specification"] == spec.model_dump()
            and plan["filename"] == request.filename
            and plan["source_sha256"] == request.source_sha256
            and plan["implementation"] == implementation(),
            "preparation ID already has different source, specification or implementation; use a new ID",
        )
        return _summary(plan)
    w.require(
        incoming.is_file() and incoming.stat().st_size <= arm_source.MAX_BYTES,
        "missing or oversized incoming arm source",
    )
    data = incoming.read_bytes()
    w.require(
        w.sha(data) == request.source_sha256, "incoming arm source differs from requested SHA256"
    )
    grid = arm_source.source_grid(data, request.filename, spec)
    reviewed = engine.review(grid, spec)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()  # Exclusive: incomplete drafts remain visible, never overwritten.
    (root / "source").mkdir()
    with w.safe_path(root, "source/" + request.filename).open("xb") as output:
        output.write(data)
        output.flush()
        import os

        os.fsync(output.fileno())
    _json(root / "grid.json", grid)
    _json(root / "review.json", reviewed)
    plan = w.sealed(
        {
            "schema": "binary-arm-plan-v1",
            "project_id": project.id,
            "preparation_id": request.preparation_id,
            "created_at": w.timestamp(),
            "filename": request.filename,
            "source_sha256": request.source_sha256,
            "specification": spec.model_dump(),
            "specification_sha256": digest(spec.model_dump()),
            "method": engine.METHOD,
            "implementation": implementation(),
            "files": _inventory(root, ["source/" + request.filename, "grid.json", "review.json"]),
            "ready_for_approval": reviewed["ready_for_approval"],
            "summary": reviewed["summary"],
            "error_count": len(reviewed["errors"]),
            "required_confirmations": list(contract.Confirmations.model_fields),
            "scope": "Preparation of aggregate trial arms only. No EDA phase advancement, model fit or completed clinical audit.",
        }
    )
    _json(root / "plan.json", plan)
    read_plan(project, request.preparation_id, plan["receipt_sha256"])
    w.event(
        project,
        "evidence_arms_drafted",
        preparation_id=request.preparation_id,
        plan_sha256=plan["receipt_sha256"],
        ready_for_approval=plan["ready_for_approval"],
    )
    return _summary(plan)


def _summary(plan):
    return {
        key: plan[key]
        for key in (
            "project_id",
            "preparation_id",
            "receipt_sha256",
            "source_sha256",
            "ready_for_approval",
            "summary",
            "error_count",
            "required_confirmations",
            "scope",
        )
    }


def read_approval(project, plan, expected=None):
    root = directory(project, plan["preparation_id"])
    approval = w.read_sealed(w.safe_path(root, "approval.json"))
    w.require(
        approval.get("schema") == "binary-arm-approval-v1"
        and approval.get("project_id") == project.id
        and approval.get("preparation_id") == plan["preparation_id"]
        and approval.get("plan_sha256") == plan["receipt_sha256"],
        "approval belongs to a different arm plan",
    )
    contract.ApprovalReview.model_validate(approval["review"])
    w.require(
        expected is None or approval["receipt_sha256"] == expected,
        "arm approval differs from requested SHA256",
    )
    return approval


def approve(project, request):
    plan = read_plan(project, request.preparation_id, request.expected_plan_sha256)
    w.require(
        plan["ready_for_approval"] is True,
        "resolve source review errors in a new draft before approval",
    )
    w.require(
        plan["implementation"] == implementation(),
        "arm implementation changed; create a new reviewed draft",
    )
    path = w.safe_path(directory(project, request.preparation_id), "approval.json")
    if path.exists():
        previous = read_approval(project, plan)
        w.require(
            previous["review"] == request.review.model_dump(),
            "an immutable approval already exists with different review",
        )
        return previous
    approval = w.sealed(
        {
            "schema": "binary-arm-approval-v1",
            "project_id": project.id,
            "preparation_id": request.preparation_id,
            "plan_sha256": plan["receipt_sha256"],
            "approved_at": w.timestamp(),
            "review": request.review.model_dump(),
        }
    )
    _json(path, approval)
    w.event(
        project,
        "evidence_arms_approved",
        preparation_id=request.preparation_id,
        approval_sha256=approval["receipt_sha256"],
    )
    return approval


def _run_root(project, preparation_id, run_id):
    w.canonical_id(run_id)
    return w.safe_path(directory(project, preparation_id), "runs/" + run_id)


def read_run(project, plan, run_id, approval):
    root = _run_root(project, plan["preparation_id"], run_id)
    w.require(
        (root / "result-receipt.json").is_file(),
        "arm run is failed or interrupted; retain it and use a new run ID",
    )
    receipt = w.read_sealed(w.safe_path(root, "result-receipt.json"))
    w.require(
        receipt.get("schema") == "binary-arm-execution-v1"
        and receipt.get("run_id") == run_id
        and receipt.get("plan_sha256") == plan["receipt_sha256"]
        and receipt.get("approval_sha256") == approval["receipt_sha256"],
        "arm execution identity differs",
    )
    w.require(
        set(receipt["files"]) == {"attempt.json", "result.json", "contrasts.csv"},
        "arm result closure is incomplete",
    )
    _verify_files(root, receipt["files"])
    actual = set()
    for path in root.rglob("*"):
        w.safe_path(root, path.relative_to(root).as_posix())
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    w.require(
        actual == {*receipt["files"], "result-receipt.json"}, "unexpected file in completed arm run"
    )
    return receipt


def execute(project, request):
    plan = read_plan(project, request.preparation_id, request.expected_plan_sha256)
    approval = read_approval(project, plan, request.expected_approval_sha256)
    w.require(plan["ready_for_approval"] is True, "unresolved arm plan cannot execute")
    root = _run_root(project, request.preparation_id, request.run_id)
    if root.exists():
        return read_run(project, plan, request.run_id, approval)
    w.require(
        plan["implementation"] == implementation(),
        "arm implementation changed; create and approve a new draft",
    )
    root.parent.mkdir(exist_ok=True)
    root.mkdir()
    _json(
        root / "attempt.json",
        w.sealed(
            {
                "schema": "binary-arm-attempt-v1",
                "run_id": request.run_id,
                "plan_sha256": plan["receipt_sha256"],
                "approval_sha256": approval["receipt_sha256"],
                "started_at": w.timestamp(),
            }
        ),
    )
    try:
        reviewed = w.load_json(directory(project, request.preparation_id) / "review.json")
        result = engine.calculate(
            reviewed, contract.BinaryArmSpec.model_validate(plan["specification"])
        )
        _json(root / "result.json", result)
        with (root / "contrasts.csv").open("x", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=engine.COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(result["contrasts"])
            output.flush()
            import os

            os.fsync(output.fileno())
        read_plan(project, request.preparation_id, plan["receipt_sha256"])
        read_approval(project, plan, approval["receipt_sha256"])
        files = _inventory(root, ["attempt.json", "result.json", "contrasts.csv"])
        _verify_files(root, files)
        receipt = w.sealed(
            {
                "schema": "binary-arm-execution-v1",
                "project_id": project.id,
                "preparation_id": request.preparation_id,
                "run_id": request.run_id,
                "plan_sha256": plan["receipt_sha256"],
                "approval_sha256": approval["receipt_sha256"],
                "completed_at": w.timestamp(),
                "files": files,
                "result_path": (root / "result.json")
                .relative_to(project.output_dir.resolve())
                .as_posix(),
                "contrast_path": (root / "contrasts.csv")
                .relative_to(project.output_dir.resolve())
                .as_posix(),
                "summary": result["summary"],
                "scope": plan["scope"],
            }
        )
        _json(root / "result-receipt.json", receipt)
    except Exception as error:
        _json(
            root / "failure.json",
            w.sealed(
                {
                    "failed_at": w.timestamp(),
                    "error_type": type(error).__name__,
                    "message": str(error)[:2000],
                }
            ),
        )
        w.event(
            project,
            "evidence_arms_failed",
            preparation_id=request.preparation_id,
            run_id=request.run_id,
        )
        raise
    w.event(
        project,
        "evidence_arms_completed",
        preparation_id=request.preparation_id,
        run_id=request.run_id,
        receipt_sha256=receipt["receipt_sha256"],
    )
    return read_run(project, plan, request.run_id, approval)


def read(project, request):
    plan = read_plan(project, request.preparation_id)
    root = directory(project, request.preparation_id)
    approval_path = w.safe_path(root, "approval.json")
    approval = read_approval(project, plan) if approval_path.exists() else None
    result_receipt = None
    if request.part == "result":
        w.require(approval is not None, "result requires the saved arm approval")
        result_receipt = read_run(project, plan, request.run_id, approval)
        path = _run_root(project, request.preparation_id, request.run_id) / "result.json"
    else:
        path = root / (request.part + ".json")
    # Exact file text, not a JSON reserialization. Offsets count Unicode characters.
    text = path.read_bytes().decode("utf-8")
    hashed = w.sha(text.encode("utf-8"))
    w.require(
        request.expected_text_sha256 is None or hashed == request.expected_text_sha256,
        "arm read differs from the pinned text SHA256",
    )
    w.require(request.text_offset <= len(text), "text offset exceeds the complete record")
    end = min(len(text), request.text_offset + request.text_limit)
    attempts = []
    runs = w.safe_path(root, "runs")
    if runs.exists():
        for run in sorted(runs.iterdir()):
            w.safe_path(runs, run.name)
            w.canonical_id(run.name)
            if (run / "result-receipt.json").exists():
                w.require(approval is not None, "completed arm run has no approval")
                record = read_run(project, plan, run.name, approval)
                attempts.append(
                    {
                        "run_id": run.name,
                        "status": "completed",
                        "receipt_sha256": record["receipt_sha256"],
                    }
                )
            else:
                failure = w.safe_path(run, "failure.json")
                if failure.exists():
                    w.read_sealed(failure)
                attempts.append(
                    {"run_id": run.name, "status": "failed" if failure.exists() else "interrupted"}
                )
    return {
        "plan": _summary(plan),
        "approval": approval,
        "attempts": attempts,
        "result_receipt": result_receipt,
        "part": request.part,
        "text_sha256": hashed,
        "text_offset": request.text_offset,
        "text_total_chars": len(text),
        "text_excerpt": text[request.text_offset : end],
        "next_text_offset": end if end < len(text) else None,
    }


def dispatch(project, raw_request):
    request = ADAPTER.validate_python(raw_request)
    if request.op == "contract":
        return {
            "schema": "binary-arm-preparation-contract-v1",
            "request_schema": ADAPTER.json_schema(),
            "method": engine.METHOD,
            "source_location": "<project.output_dir>/incoming/evidence-arms/<preparation_id>/<filename>",
            "workflow": "inspect source grid -> draft -> read complete plan/grid/review -> approve -> execute -> read complete result; changed sources/decisions require a new preparation ID",
            "paging": "Exact UTF-8 file SHA256; offsets count Unicode characters; pin expected_text_sha256 on every continuation.",
            "scope": "This workflow neither fits a meta-analysis nor advances patient-level EDA phases.",
        }
    with w.locked(project):
        return {
            "inspect": inspect,
            "draft": draft,
            "read": read,
            "approve": approve,
            "execute": execute,
        }[request.op](project, request)
