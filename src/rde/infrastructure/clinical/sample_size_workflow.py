"""Immutable prospective design workflow, independent of patient-data EDA phases."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import uuid

from rde.domain.models.sample_size import SampleSizeSpec
from . import sample_size as engine
from .sample_size_report import figures, markdown, review_markdown, write_table
from .survival import digest


CONFIRMATIONS = [
    "population_and_endpoint",
    "assumptions_and_sources",
    "method_and_independence",
    "primary_scenario_allocation_and_loss",
]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def canonical_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Use a canonical UUID for the plan or run ID.")
    return value


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def sealed(value):
    return {**value, "receipt_sha256": digest(value)}


def read_sealed(path):
    if path.is_symlink():
        raise ValueError("Symlinked planning records are not allowed.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("receipt_sha256") != digest(
        {k: v for k, v in value.items() if k != "receipt_sha256"}
    ):
        raise ValueError("Planning record integrity verification failed.")
    return value


def planning_root(project):
    root = project.output_dir.resolve()
    target = root / "artifacts" / "prospective_design"
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError("Planning evidence must remain inside its own project.")
    target.mkdir(parents=True, exist_ok=True)
    return target


def plan_directory(project, plan_id):
    target = planning_root(project) / canonical_id(plan_id)
    if target.is_symlink() or target.resolve().parent != planning_root(project).resolve():
        raise ValueError("Plan directory identity does not match this project.")
    return target


def run_directory(plan_dir, run_id):
    target = plan_dir / "runs" / canonical_id(run_id)
    if (plan_dir / "runs").is_symlink() or target.is_symlink():
        raise ValueError("Run directory may not be redirected by a symlink.")
    return target


def event(project, action, **details):
    path = planning_root(project) / "decision_log.jsonl"
    if path.is_symlink():
        raise ValueError("The prospective decision log may not be redirected.")
    record = {"at": timestamp(), "project_id": project.id, "action": action, **details}
    # One append write per bounded record; never rewrite historical decisions.
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def implementation():
    import rde.domain.models.sample_size as contract

    return {
        "method_contract_sha256": digest(engine.METHOD_CONTRACT),
        "source_sha256": {
            "contract": file_hash(Path(contract.__file__)),
            "calculator": file_hash(Path(engine.__file__)),
        },
        "versions": {
            name: version(name)
            for name in ("research-data-explorer", "statsmodels", "scipy", "numpy")
        },
        "python": sys.version.split()[0],
    }


def read_plan(project, plan_id, expected=None):
    directory = plan_directory(project, plan_id)
    plan = read_sealed(directory / "plan.json")
    if plan.get("project_id") != project.id or plan.get("plan_id") != plan_id:
        raise ValueError("Plan belongs to a different project or identity.")
    if expected is not None and plan["receipt_sha256"] != expected:
        raise ValueError("The plan differs from the reviewed SHA256.")
    review = directory / "review.md"
    if (
        review.is_symlink()
        or not review.is_file()
        or file_hash(review) != plan.get("review_sha256")
    ):
        raise ValueError("Saved planning review failed integrity verification.")
    if digest(plan["spec"]) != plan.get("assumptions_sha256"):
        raise ValueError("Saved assumptions failed integrity verification.")
    return plan


def draft_plan(project, plan_id, options):
    spec = SampleSizeSpec.parse(options)
    directory = plan_directory(project, plan_id)
    if directory.exists():
        existing = read_plan(project, plan_id)
        if existing["spec"] != spec.to_dict() or existing["implementation"] != implementation():
            raise ValueError(
                "Plan ID already has different assumptions or implementation; create a new plan."
            )
        return existing
    directory.mkdir()  # Exclusive reservation; an interrupted draft is never silently overwritten.
    review = review_markdown(spec.to_dict(), engine.LIMITATIONS)
    (directory / "review.md").write_text(review, encoding="utf-8")
    plan = sealed(
        {
            "schema": "sample-size-plan-v1",
            "project_id": project.id,
            "plan_id": plan_id,
            "created_at": timestamp(),
            "spec": spec.to_dict(),
            "assumptions_sha256": digest(spec.to_dict()),
            "method_contract": engine.METHOD_CONTRACT,
            "implementation": implementation(),
            "limitations": engine.LIMITATIONS,
            "review_sha256": file_hash(directory / "review.md"),
            "required_confirmations": CONFIRMATIONS,
            "scope": "Prospective design only. No patient dataset, EDA phase advancement or completed EDA audit.",
        }
    )
    write_new(directory / "plan.json", plan)
    event(project, "sample_size_drafted", plan_id=plan_id, plan_sha256=plan["receipt_sha256"])
    return plan


def read_approval(project, plan, expected=None):
    approval = read_sealed(plan_directory(project, plan["plan_id"]) / "approval.json")
    if approval.get("plan_sha256") != plan["receipt_sha256"]:
        raise ValueError("Approval is not bound to this exact planning review.")
    if expected is not None and approval["receipt_sha256"] != expected:
        raise ValueError("Approval differs from the expected SHA256.")
    return approval


def approve_plan(project, plan_id, expected_plan_sha256, review):
    plan = read_plan(project, plan_id, expected_plan_sha256)
    if plan["implementation"] != implementation():
        raise ValueError("Calculation implementation changed; create and review a new draft.")
    if not isinstance(review, dict) or set(review) != {"reviewer", "note", "confirmations"}:
        raise ValueError("Approval requires reviewer, note and all explicit confirmations.")
    from rde.domain.models.sample_size import text

    for key in ("reviewer", "note"):
        text(review[key], key, limit=2000)
    confirmations = review["confirmations"]
    if (
        not isinstance(confirmations, dict)
        or set(confirmations) != set(CONFIRMATIONS)
        or any(v is not True for v in confirmations.values())
    ):
        raise ValueError(
            "Every required planning assumption must be explicitly confirmed after review."
        )
    path = plan_directory(project, plan_id) / "approval.json"
    if path.exists():
        previous = read_approval(project, plan)
        if previous["review"] != review:
            raise ValueError("This plan already has a different immutable approval.")
        return previous
    approval = sealed(
        {
            "schema": "sample-size-approval-v1",
            "plan_sha256": plan["receipt_sha256"],
            "approved_at": timestamp(),
            "review": review,
        }
    )
    write_new(path, approval)
    event(
        project, "sample_size_approved", plan_id=plan_id, approval_sha256=approval["receipt_sha256"]
    )
    return approval


def inventory(directory, project):
    records = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Run artifacts may not escape the run directory.")
        if path.is_file() and path != directory / "run.json":
            records.append(
                {
                    "path": str(path.relative_to(project.output_dir)),
                    "sha256": file_hash(path),
                    "bytes": path.stat().st_size,
                }
            )
    return records


def read_run(project, plan, run_id, expected=None):
    directory = run_directory(plan_directory(project, plan["plan_id"]), run_id)
    record = read_sealed(directory / "run.json")
    if (
        record.get("plan_sha256") != plan["receipt_sha256"]
        or record.get("run_id") != run_id
        or record.get("project_id") != project.id
        or record.get("status") != "completed"
    ):
        raise ValueError("Run identity, status or planning approval does not match.")
    if expected is not None and expected != record["receipt_sha256"]:
        raise ValueError("Run differs from the expected SHA256.")
    read_approval(project, plan, record["approval_sha256"])
    if inventory(directory, project) != record["artifacts"]:
        raise ValueError(
            "Saved sample-size artifacts failed integrity verification; no output will be overwritten."
        )
    result = read_sealed(directory / "result.json")
    if (
        result["spec"] != plan["spec"]
        or result["receipt_sha256"] != record["numerical_receipt_sha256"]
    ):
        raise ValueError("Saved result no longer matches its plan or numerical receipt.")
    return record


def run_plan(project, plan_id, expected_plan_sha256, expected_approval_sha256, run_id):
    plan = read_plan(project, plan_id, expected_plan_sha256)
    approval = read_approval(project, plan, expected_approval_sha256)
    directory = run_directory(plan_directory(project, plan_id), run_id)
    if directory.exists():
        if not (directory / "run.json").exists():
            raise ValueError(
                "Run is unfinished or failed; inspect its retained attempt and use a new run ID."
            )
        return read_run(project, plan, run_id)
    if plan["implementation"] != implementation():
        raise ValueError(
            "Calculation implementation changed after review; create a new planning draft."
        )
    spec = SampleSizeSpec.parse(plan["spec"])
    directory.parent.mkdir(exist_ok=True)
    directory.mkdir()
    request = {
        "plan_id": plan_id,
        "plan_sha256": plan["receipt_sha256"],
        "approval_sha256": approval["receipt_sha256"],
        "run_id": run_id,
    }
    write_new(directory / "request.json", {**request, "started_at": timestamp()})
    event(project, "sample_size_started", **request)
    try:
        write_new(
            directory / "readiness.json",
            {
                "ready": True,
                "plan_integrity": True,
                "review_integrity": True,
                "approval_integrity": True,
                "implementation_matches_review": True,
                "strict_contract_valid": True,
                "source_truth": "human-reviewed declaration, not machine verification",
                "patient_data_used": False,
                "eda_phases_changed": False,
            },
        )
        result = engine.calculate_sample_size(spec)
        write_new(directory / "result.json", result)
        write_table(result, directory)
        rendered = figures(result, directory)
        (directory / "sample-size-report.md").write_text(
            markdown(result, rendered), encoding="utf-8"
        )
        # Recheck original evidence immediately before committing the completed marker.
        read_plan(project, plan_id, expected_plan_sha256)
        read_approval(project, plan, expected_approval_sha256)
        record = sealed(
            {
                "schema": "sample-size-run-v1",
                "project_id": project.id,
                "status": "completed",
                **request,
                "completed_at": timestamp(),
                "numerical_receipt_sha256": result["receipt_sha256"],
                "figures": rendered,
                "artifacts": inventory(directory, project),
                "result_path": str((directory / "result.json").relative_to(project.output_dir)),
                "report_path": str(
                    (directory / "sample-size-report.md").relative_to(project.output_dir)
                ),
                "receipt_path": str((directory / "run.json").relative_to(project.output_dir)),
                "primary_scenario": next(row for row in result["scenarios"] if row["primary"]),
                "audit_scope": "Prospective plan, approval, readiness and output integrity; not a completed EDA audit.",
            }
        )
        write_new(directory / "run.json", record)
    except BaseException as error:
        write_new(
            directory / "failure.json",
            {"failed_at": timestamp(), "error_type": type(error).__name__, "message": str(error)},
        )
        event(
            project,
            "sample_size_failed",
            **request,
            error_type=type(error).__name__,
            message=str(error),
        )
        raise
    event(project, "sample_size_completed", **request, receipt_sha256=record["receipt_sha256"])
    return read_run(project, plan, run_id)


def get_plan(project, plan_id):
    plan = read_plan(project, plan_id)
    directory = plan_directory(project, plan_id)
    approval = read_approval(project, plan) if (directory / "approval.json").exists() else None
    runs = []
    if (directory / "runs").is_symlink():
        raise ValueError("Planning run evidence may not be redirected.")
    for path in sorted((directory / "runs").glob("*")):
        run_directory(directory, path.name)
        if (path / "run.json").exists():
            runs.append(read_run(project, plan, path.name))
        else:
            failure = path / "failure.json"
            if path.is_symlink() or failure.is_symlink():
                raise ValueError("Planning run evidence may not be redirected.")
            runs.append(
                {
                    "run_id": path.name,
                    "status": "failed" if failure.exists() else "unfinished",
                    "failure": json.loads(failure.read_text()) if failure.exists() else None,
                }
            )
    return {
        "plan": plan,
        "review_markdown": (directory / "review.md").read_text(encoding="utf-8"),
        "approval": approval,
        "runs": runs,
        "implementation_matches_review": plan["implementation"] == implementation(),
    }
