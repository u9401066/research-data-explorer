"""Immutable preparations and releases with project-scoped, restart-safe effects."""

import csv
import hashlib
import io
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from rde.domain.models import preparation as contract
from rde.infrastructure.evidence.workflow import canonical_id, safe_path
from rde.infrastructure.preparation import engine, sources
from rde.infrastructure.preparation.sources import canonical, digest, file_hash


def now():
    return datetime.now(timezone.utc).isoformat()


def implementation():
    from rde.infrastructure.preparation import portable

    return {
        "files": {
            name: file_hash(Path(module.__file__))
            for name, module in {
                "contract": contract,
                "sources": sources,
                "engine": engine,
                "workflow": sys.modules[__name__],
                "portable": portable,
            }.items()
        },
        "python": sys.version.split()[0],
        "dependencies": {name: version(name) for name in ("pydantic", "openpyxl")},
    }


def directory(project):
    result = safe_path(project.output_dir.resolve(), "artifacts/data_preparation")
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result


@contextmanager
def locked(root):
    with safe_path(root, ".lock").open("a+b") as file:
        if os.name == "nt":
            import msvcrt

            if file.seek(0, os.SEEK_END) == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def write_bytes(path, raw):
    """Called under the project lock; atomic publication never replaces evidence."""
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("IMMUTABLE_CONFLICT: retained bytes differ")
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name("." + path.name + "." + str(uuid.uuid4()) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def seal(path, payload):
    record = {**payload, "receipt_sha256": digest(payload)}
    write_bytes(path, (canonical(record) + "\n").encode())
    return record


def read_sealed(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("preparation metadata exceeds size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("receipt_sha256") != digest(
        {k: v for k, v in value.items() if k != "receipt_sha256"}
    ):
        raise ValueError("CORRUPT_PREPARATION: receipt failed integrity verification")
    return value


def source_list(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("choose 1..16 explicit sources")
    result = [contract.Source.model_validate(value) for value in raw]
    if len({s.id for s in result}) != len(result):
        raise ValueError("source IDs must be unique")
    return result


def inventory(root):
    return {
        p.relative_to(root).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def verify_files(root, files):
    for name, info in files.items():
        path = safe_path(root, name)
        if (
            not path.is_file()
            or path.stat().st_size != info["bytes"]
            or file_hash(path) != info["sha256"]
        ):
            raise ValueError(f"CORRUPT_PREPARATION: retained file changed: {name}")


def read_plan(project, preparation_id, expected=None, live=False):
    canonical_id(preparation_id)
    root = directory(project)
    folder = safe_path(root, "versions/" + preparation_id)
    plan = read_sealed(safe_path(folder, "plan.json"))
    if (
        plan.get("project_id") != project.id
        or plan.get("preparation_id") != preparation_id
        or plan.get("schema") != "rde-preparation-plan-v1"
    ):
        raise ValueError("preparation ownership or identity mismatch")
    if expected is not None and plan["receipt_sha256"] != expected:
        raise ValueError("STALE_PREPARATION: draft differs from reviewed version")
    verify_files(folder, plan["files"])
    for record in plan["source_snapshots"]:
        snapshot = safe_path(root, record["snapshot"])
        source = contract.Source.model_validate(record["source"])
        if (
            not snapshot.is_file()
            or snapshot.stat().st_size != source.bytes
            or file_hash(snapshot) != source.sha256
        ):
            raise ValueError("CORRUPT_PREPARATION: original source snapshot changed")
        if live:
            original = Path(source.path)
            if (
                not original.is_file()
                or original.stat().st_size != source.bytes
                or file_hash(original) != source.sha256
            ):
                raise ValueError(
                    "SOURCE_CHANGED: original input changed; create a new preparation revision"
                )
    return plan


def lines(path):
    with path.open(encoding="utf-8") as stream:
        for text in stream:
            yield json.loads(text)


def flow_svg(summary):
    from html import escape

    steps = summary["flow"]
    height = 110 + len(steps) * 105
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{height}" viewBox="0 0 920 {height}"><rect width="100%" height="100%" fill="white"/><title>Research data preparation flow</title><style>text{{font-family:Arial,sans-serif;fill:#183f3a}}.title{{font-size:22px;font-weight:bold}}.label{{font-size:16px}}.note{{font-size:14px}}</style><text x="30" y="35" class="title">Research data preparation · unit and participant flow</text>'
    ]
    for i, step in enumerate(steps):
        y = 60 + i * 105
        before, after = step["before"], step["after"]
        parts += [
            f'<rect x="30" y="{y}" width="860" height="82" rx="8" fill="#eff6f3" stroke="#187568"/>',
            f'<text x="48" y="{y + 25}" class="label">{escape(step["step"])}</text>',
            f'<text x="48" y="{y + 49}" class="note">Rows: {before["rows"]} → {after["rows"]} · {escape(after["unit_kind"])} units: {before["units"]} → {after["units"]} · subjects: {before["subjects"]} → {after["subjects"]}</text>',
            f'<text x="48" y="{y + 69}" class="note">Excluded rows at this step: {step["excluded_rows"]}</text>',
        ]
        if i < len(steps) - 1:
            parts.append(
                f'<path d="M460 {y + 82}v17m-5 -5l5 5 5 -5" fill="none" stroke="#187568" stroke-width="2"/>'
            )
    parts.append(
        f'<text x="30" y="{height - 18}" class="note">Preparation denominators; model-specific exclusions remain separate. Source and linkage validity require review.</text></svg>'
    )
    return "".join(parts).encode()


def draft(project, request):
    pid = canonical_id(request["preparation_id"])
    inputs = source_list(request["sources"])
    spec = contract.Specification.model_validate(request["specification"])
    root = directory(project)
    parent = request.get("parent")
    if parent:
        if set(parent) != {"preparation_id", "receipt_sha256"} or parent["preparation_id"] == pid:
            raise ValueError("invalid parent preparation reference")
        read_plan(project, parent["preparation_id"], parent["receipt_sha256"])
    reason, author = request.get("reason", ""), request.get("author", "")
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(author, str)
        or not author.strip()
    ):
        raise ValueError("preparation requires a reason and attributed author")
    intent = {
        "sources": [s.model_dump() for s in inputs],
        "specification": spec.model_dump(),
        "parent": parent,
        "reason": reason,
        "author": author,
        "implementation": implementation(),
    }
    intent_path = safe_path(root, f"intents/{pid}.json")
    if intent_path.exists():
        if read_sealed(intent_path)["intent"] != intent:
            raise ValueError(
                "IMMUTABLE_CONFLICT: this draft ID has a different intent or implementation"
            )
    else:
        seal(intent_path, {"intent": intent, "created_at": now()})
    destination = safe_path(root, "versions/" + pid)
    if destination.exists():
        return read_plan(project, pid, live=True)
    attempt_id = str(uuid.uuid4())
    attempt = safe_path(root, f"attempts/{pid}/{attempt_id}")
    attempt.mkdir(parents=True, mode=0o700)
    seal(
        attempt / "started.json",
        {"operation": "draft", "preparation_id": pid, "at": now(), "intent_sha256": digest(intent)},
    )
    try:
        tables = {s.id: sources.load(s) for s in inputs}
        snapshots = []
        for s in inputs:
            relative = "sources/" + s.sha256 + Path(s.path).suffix.lower()
            target = safe_path(root, relative)
            raw = Path(s.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != s.sha256 or len(raw) != s.bytes:
                raise ValueError("SOURCE_CHANGED during snapshot creation")
            write_bytes(target, raw)
            snapshots.append({"source": s.model_dump(), "snapshot": relative})
        result = engine.Evaluation(tables, spec, project.id).evaluate()
        stage = attempt / "candidate"
        stage.mkdir(mode=0o700)
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=result.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)
        write_bytes(stage / "analysis.csv", text.getvalue().encode("utf-8"))
        from rde.infrastructure.preparation.portable import output_schema

        write_bytes(
            stage / "analysis.schema.json",
            (canonical(output_schema(spec, result.columns)) + "\n").encode(),
        )
        write_bytes(
            stage / "analysis.jsonl", "".join(canonical(r) + "\n" for r in result.rows).encode()
        )
        for name, records in {
            "issues": result.issues,
            "exceptions": result.exceptions,
            "trace": result.trace.values(),
        }.items():
            write_bytes(
                stage / f"{name}.jsonl", "".join(canonical(r) + "\n" for r in records).encode()
            )
        summary = result.summary()
        write_bytes(stage / "validation.json", (canonical(summary) + "\n").encode())
        write_bytes(stage / "flow.svg", flow_svg(summary))
        write_bytes(stage / "specification.json", (canonical(spec.model_dump()) + "\n").encode())
        plan = seal(
            stage / "plan.json",
            {
                "schema": "rde-preparation-plan-v1",
                "project_id": project.id,
                "preparation_id": pid,
                "parent": parent,
                "created_at": now(),
                "author": author,
                "reason": reason,
                "specification": spec.model_dump(),
                "source_snapshots": snapshots,
                "implementation": intent["implementation"],
                "summary": summary,
                "files": inventory(stage),
            },
        )
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(stage, destination)
        seal(
            attempt / "completed.json",
            {"receipt_sha256_of_plan": plan["receipt_sha256"], "at": now()},
        )
        return plan
    except Exception as error:
        seal(
            attempt / "failed.json",
            {"error_type": type(error).__name__, "message": str(error), "at": now()},
        )
        raise


def approve(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"], live=True)
    if plan["implementation"] != implementation():
        raise ValueError("IMPLEMENTATION_CHANGED: create and review a new draft")
    if not plan["summary"]["ready_for_approval"]:
        raise ValueError("QUALITY_BLOCKED: resolve every blocker before approval")
    warnings = sorted(set(request.get("acknowledged_warnings", [])))
    if warnings != plan["summary"]["warnings"]:
        raise ValueError("review and acknowledge the exact current warning list")
    reviewer = request.get("reviewer", "")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("approval requires an attributed reviewer")
    review = contract.Review.model_validate(request["review"])
    if not review.denominator_confirmed:
        raise ValueError("review the source, eligibility and final denominators")
    if review.kind == "synthetic_oracle" and not all(
        s["source"]["synthetic"] for s in plan["source_snapshots"]
    ):
        raise ValueError("real sources cannot be approved as a synthetic oracle")
    folder = safe_path(directory(project), "versions/" + plan["preparation_id"])
    units = {r["unit_id"] for r in lines(folder / "trace.jsonl")}
    if (
        len(review.reviewed_unit_ids) != len(set(review.reviewed_unit_ids))
        or not set(review.reviewed_unit_ids) <= units
    ):
        raise ValueError("review must reference distinct actual units from this exact draft")
    payload = {
        "schema": "rde-preparation-approval-v1",
        "project_id": project.id,
        "preparation_id": plan["preparation_id"],
        "plan_sha256": plan["receipt_sha256"],
        "reviewer": reviewer,
        "acknowledged_warnings": warnings,
        "review": review.model_dump(),
        "clinical_validation": "manager_attestation"
        if review.kind == "data_manager"
        else "synthetic_only",
    }
    path = folder / "approval.json"
    if path.exists():
        previous = read_sealed(path)
        if {k: previous[k] for k in payload} != payload:
            raise ValueError("IMMUTABLE_APPROVAL: create a new preparation revision")
        return previous
    return seal(path, {**payload, "created_at": now()})


def release(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"], live=True)
    if plan["implementation"] != implementation():
        raise ValueError("IMPLEMENTATION_CHANGED: create and approve a new preparation")
    folder = safe_path(directory(project), "versions/" + plan["preparation_id"])
    approval = read_sealed(folder / "approval.json")
    if (
        approval["plan_sha256"] != plan["receipt_sha256"]
        or approval["receipt_sha256"] != request["approval_sha256"]
    ):
        raise ValueError("STALE_APPROVAL: exact approval does not bind this preparation")
    payload = {
        "schema": "rde-data-release-v1",
        "project_id": project.id,
        "release_id": plan["preparation_id"],
        "plan_sha256": plan["receipt_sha256"],
        "approval_sha256": approval["receipt_sha256"],
        "dataset": {"path": str(folder / "analysis.csv"), **plan["files"]["analysis.csv"]},
        "source_set_sha256": digest(plan["source_snapshots"]),
        "specification_sha256": digest(plan["specification"]),
        "implementation": plan["implementation"],
        "population": plan["summary"]["population"],
        "unit": plan["specification"]["unit"],
        "column_roles": {
            feature["output"]: (r["window"]["purpose"] if r["window"] else "descriptive")
            for r in plan["specification"]["relations"]
            for feature in r["features"]
        },
        "clinical_validation": approval["clinical_validation"],
    }
    path = folder / "release.json"
    if path.exists():
        previous = read_sealed(path)
        if {k: previous[k] for k in payload} != payload:
            raise ValueError("CORRUPT_RELEASE: immutable release payload differs")
        return previous
    return seal(path, {**payload, "created_at": now()})


def page(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"])
    section = request.get("section", "issues")
    if section not in {"issues", "exceptions", "units", "output"}:
        raise ValueError("unknown preparation page section")
    offset, limit = request.get("offset", 0), request.get("limit", 30)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid page offset or limit")
    folder = safe_path(directory(project), "versions/" + plan["preparation_id"])
    name = "trace" if section in {"units", "output"} else section
    records, total = [], 0
    for record in lines(folder / f"{name}.jsonl"):
        if section == "output" and not record["included"]:
            continue
        if offset <= total < offset + limit:
            if name == "trace":
                record = {
                    k: record[k]
                    for k in ("unit_id", "subject_id", "root", "included", "exclusions", "values")
                }
            records.append(record)
        total += 1
    return {
        "preparation_id": plan["preparation_id"],
        "plan_sha256": plan["receipt_sha256"],
        "section": section,
        "offset": offset,
        "records": records,
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
    }


def trace(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"])
    folder = safe_path(directory(project), "versions/" + plan["preparation_id"])
    record = next(
        (r for r in lines(folder / "trace.jsonl") if r["unit_id"] == request["unit_id"]), None
    )
    if record is None:
        raise ValueError("unit does not belong to this preparation")
    column = request.get("column")
    if column is None:
        return {
            k: record[k]
            for k in ("unit_id", "subject_id", "root", "included", "exclusions", "values")
        } | {"traceable_columns": list(record["cells"])}
    if column not in record["cells"]:
        raise ValueError("column has no trace in this preparation")
    cell = record["cells"][column]
    offset, limit = request.get("offset", 0), request.get("limit", 30)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid trace page")
    refs = cell["sources"]
    values = []
    cache = {}
    for ref in refs[offset : offset + limit]:
        source_id = ref["source_id"]
        if source_id not in cache:
            item = next(s for s in plan["source_snapshots"] if s["source"]["id"] == source_id)
            cache[source_id] = sources.load(
                contract.Source.model_validate(item["source"]),
                safe_path(directory(project), item["snapshot"]),
            )
        row = cache[source_id].rows[ref["record_index"]]
        if row.sha256 != ref["row_sha256"]:
            raise ValueError("CORRUPT_TRACE: source row identity mismatch")
        values.append({"reference": ref, "values": row.values})
    return {
        "unit_id": record["unit_id"],
        "column": column,
        "value": record["values"].get(column),
        "rule": {k: v for k, v in cell.items() if k != "sources"},
        "source_records": values,
        "offset": offset,
        "total": len(refs),
        "next_offset": offset + limit if offset + limit < len(refs) else None,
    }


def execute(project, request):
    if not isinstance(request, dict):
        raise ValueError("preparation request must be an object")
    op = request.get("op")
    allowed = {
        "contract": {"op"},
        "inspect": {"op", "sources"},
        "draft": {"op", "preparation_id", "sources", "specification", "parent", "reason", "author"},
        "read": {"op", "preparation_id", "expected_sha256"},
        "approve": {
            "op",
            "preparation_id",
            "expected_sha256",
            "acknowledged_warnings",
            "reviewer",
            "review",
        },
        "release": {"op", "preparation_id", "expected_sha256", "approval_sha256"},
        "page": {"op", "preparation_id", "expected_sha256", "section", "offset", "limit"},
        "trace": {
            "op",
            "preparation_id",
            "expected_sha256",
            "unit_id",
            "column",
            "offset",
            "limit",
        },
        "bundle": {"op", "preparation_id", "expected_sha256", "release_sha256"},
    }
    if op not in allowed or set(request) - allowed[op]:
        raise ValueError("unknown preparation operation or fields")
    if op == "contract":
        return {
            "schema": "rde-data-preparation-contract-v1",
            "operations": list(allowed),
            "specification": contract.Specification.model_json_schema(),
            "source": contract.Source.model_json_schema(),
            "review": contract.Review.model_json_schema(),
            "partial_linkage": [
                "matched",
                "matched_partial",
                "no_record",
                "not_exported",
                "outside_window",
                "not_available",
                "link_failed",
                "unknown_coverage",
                "filtered_out",
            ],
            "model_execution": False,
            "clinical_truth": "Software validation and reviewer attestation are distinct; neither proves real clinical linkage truth.",
        }
    root = directory(project)
    with locked(root):
        if op == "bundle":
            from rde.infrastructure.preparation.portable import export_bundle

            return export_bundle(project, request)
        if op == "inspect":
            return sources.inspect({s.id: sources.load(s) for s in source_list(request["sources"])})
        if op == "read":
            plan = read_plan(project, request["preparation_id"], request.get("expected_sha256"))
            folder = safe_path(root, "versions/" + plan["preparation_id"])
            approval = (
                read_sealed(folder / "approval.json")
                if (folder / "approval.json").exists()
                else None
            )
            released = (
                read_sealed(folder / "release.json") if (folder / "release.json").exists() else None
            )
            if approval and (
                approval.get("project_id") != project.id
                or approval.get("preparation_id") != plan["preparation_id"]
                or approval.get("plan_sha256") != plan["receipt_sha256"]
            ):
                raise ValueError("CORRUPT_APPROVAL: approval belongs to a different preparation")
            if released and (
                not approval
                or released.get("project_id") != project.id
                or released.get("release_id") != plan["preparation_id"]
                or released.get("plan_sha256") != plan["receipt_sha256"]
                or released.get("approval_sha256") != approval["receipt_sha256"]
            ):
                raise ValueError("CORRUPT_RELEASE: release does not bind this plan and approval")
            return {"plan": plan, "approval": approval, "release": released}
        return {
            "draft": draft,
            "approve": approve,
            "release": release,
            "page": page,
            "trace": trace,
        }[op](project, request)
