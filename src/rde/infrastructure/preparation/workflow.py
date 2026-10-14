"""Immutable preparations and releases with project-scoped, restart-safe effects."""

import csv
import hashlib
import io
import json
import math
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
    from rde.domain.models import preparation_edit
    from rde.infrastructure.preparation import aggregation, portable

    return {
        "files": {
            name: file_hash(Path(module.__file__))
            for name, module in {
                "contract": contract,
                "sources": sources,
                "engine": engine,
                "workflow": sys.modules[__name__],
                "portable": portable,
                "aggregation": aggregation,
                "preparation_edit": preparation_edit,
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
    candidate_ref = request.get("candidate_ref")
    if candidate_ref is not None:
        if "sources" in request or "specification" in request:
            raise ValueError("candidate_ref cannot be mixed with sources/specification")
        from rde.infrastructure.preparation.aggregation import resolve_draft

        candidate = resolve_draft(project, candidate_ref)
        request = {
            **request,
            "sources": candidate["sources"],
            "specification": candidate["specification"],
        }
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
        "candidate_ref": candidate_ref,
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
                "candidate_ref": candidate_ref,
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


def automated_payload(project, plan):
    """Stream all retained rows; check consistency, never attest clinical truth.

    Only IDs and row digests are retained in memory. Trace order is the source
    order while analysis rows are key-sorted, so row positions are not identity.
    """
    if plan["implementation"] != implementation():
        raise ValueError("IMPLEMENTATION_CHANGED: create and review a new draft")
    summary = plan["summary"]
    if not summary["ready_for_approval"]:
        raise ValueError("QUALITY_BLOCKED: resolve every blocker before automated review")
    folder = safe_path(directory(project), "versions/" + plan["preparation_id"])
    required = {
        "analysis.csv",
        "analysis.jsonl",
        "analysis.schema.json",
        "trace.jsonl",
        "validation.json",
        "specification.json",
    }
    if not required <= set(plan["files"]):
        raise ValueError("AUTOMATED_CHECK_FAILED: incomplete retained preparation evidence")
    if (
        json.loads((folder / "validation.json").read_text(encoding="utf-8")) != summary
        or json.loads((folder / "specification.json").read_text(encoding="utf-8"))
        != plan["specification"]
    ):
        raise ValueError("AUTOMATED_CHECK_FAILED: summary or specification differs from plan")
    columns = summary["output_columns"]
    if (
        not isinstance(columns, list)
        or not all(isinstance(c, str) for c in columns)
        or len(columns) != len(set(columns))
        or not {"_rde_unit_id", "_rde_subject_id"} <= set(columns)
    ):
        raise ValueError("AUTOMATED_CHECK_FAILED: invalid analysis columns")
    from rde.infrastructure.preparation.portable import output_schema

    schema = json.loads((folder / "analysis.schema.json").read_text(encoding="utf-8"))
    spec = contract.Specification.model_validate(plan["specification"])
    if schema != output_schema(spec, columns):
        raise ValueError(
            "AUTOMATED_CHECK_FAILED: native output schema differs from rules or identifiers"
        )
    all_units, subjects, expected = set(), set(), {}
    for record in lines(folder / "trace.jsonl"):
        uid, sid, values = record.get("unit_id"), record.get("subject_id"), record.get("values")
        if (
            not isinstance(uid, str)
            or not uid
            or not isinstance(sid, str)
            or not sid
            or uid in all_units
            or type(record.get("included")) is not bool
            or not isinstance(values, dict)
            or values.get("_rde_unit_id") != uid
            or values.get("_rde_subject_id") != sid
        ):
            raise ValueError("AUTOMATED_CHECK_FAILED: invalid or duplicate trace identity")
        all_units.add(uid)
        if record["included"]:
            subjects.add(sid)
            projected = {column: values.get(column) for column in columns}
            for column in schema["columns"]:
                value = projected[column["name"]]
                if value is not None and (
                    (column["type"] == "text" and not isinstance(value, str))
                    or (
                        column["type"] == "number"
                        and (type(value) not in (int, float) or not math.isfinite(value))
                    )
                ):
                    raise ValueError(
                        "AUTOMATED_CHECK_FAILED: trace value differs from native output schema"
                    )
            expected[uid] = (
                digest(projected),
                digest(["" if projected[c] is None else str(projected[c]) for c in columns]),
            )
    count = len(expected)
    kind = plan["specification"]["unit"]["kind"]
    population = {
        "rows": count,
        "units": count,
        "subjects": len(subjects),
        "unit_kind": kind,
        "encounters": count if kind == "encounter" else None,
        "events": count if kind == "event" else None,
    }
    if not count or population != summary["population"] or len(all_units) != summary["trace_units"]:
        raise ValueError("AUTOMATED_CHECK_FAILED: trace and population denominators differ")
    seen = set()
    for row in lines(folder / "analysis.jsonl"):
        uid = row.get("_rde_unit_id") if isinstance(row, dict) else None
        if (
            not isinstance(uid, str)
            or uid not in expected
            or uid in seen
            or set(row) != set(columns)
            or digest(row) != expected[uid][0]
        ):
            raise ValueError(
                "AUTOMATED_CHECK_FAILED: typed analysis row differs from included trace"
            )
        seen.add(uid)
    if len(seen) != count:
        raise ValueError("AUTOMATED_CHECK_FAILED: typed analysis rows omit included units")
    seen.clear()
    with (folder / "analysis.csv").open(encoding="utf-8", newline="") as stream:
        rows = csv.reader(stream)
        if next(rows, None) != columns:
            raise ValueError("AUTOMATED_CHECK_FAILED: CSV columns differ from plan")
        unit_index = columns.index("_rde_unit_id")
        for row in rows:
            uid = row[unit_index] if len(row) == len(columns) else None
            if uid not in expected or uid in seen or digest(row) != expected[uid][1]:
                raise ValueError("AUTOMATED_CHECK_FAILED: CSV row differs from included trace")
            seen.add(uid)
    if len(seen) != count:
        raise ValueError("AUTOMATED_CHECK_FAILED: CSV rows omit included units")
    return {
        "schema": "rde-preparation-automated-checks-v1",
        "project_id": project.id,
        "preparation_id": plan["preparation_id"],
        "plan_sha256": plan["receipt_sha256"],
        "source_set_sha256": digest(plan["source_snapshots"]),
        "specification_sha256": digest(plan["specification"]),
        "files_sha256": digest(plan["files"]),
        "schema_sha256": plan["files"]["analysis.schema.json"]["sha256"],
        "summary_sha256": digest(summary),
        "implementation": plan["implementation"],
        "population": population,
        "checked_counts": {
            "trace_units": len(all_units),
            "included_units": count,
            "analysis_jsonl_rows": count,
            "analysis_csv_rows": count,
        },
        "reviewed_unit_ids": sorted(expected)[:100],
        "sample_policy": "First up to 100 included unit IDs in lexical order; deterministic technical trace sample, not a representative clinical case review.",
        "checks": {
            "retained_files": "verified",
            "live_sources": "verified",
            "native_output_schema_and_value_types": "verified",
            "unique_trace_units": "verified",
            "population": "verified",
            "all_analysis_rows_against_trace": "verified",
        },
        "clinical_validation": "not_performed",
        "review_scope": "automated_checks_only",
        "limitations": [
            "Consistency of retained software outputs is not independent recomputation of joins or aggregations.",
            "Clinical identity, source completeness and appropriateness of cohort, linkage and time definitions are not established.",
            "No data-manager review or clinical attestation was performed.",
        ],
    }


def checked_automated_receipt(project, plan, expected_hash=None, create=False):
    """Only the fixed server path supplies evidence; caller assertions cannot."""
    path = safe_path(
        directory(project), "versions/" + plan["preparation_id"] + "/automated_review.json"
    )
    if not path.exists() and not create:
        raise ValueError("AUTOMATED_REVIEW_REQUIRED: run automated_review for this exact draft")
    payload = automated_payload(project, plan)
    # Recheck bytes after streaming, before publishing or reusing an attestation.
    read_plan(project, plan["preparation_id"], plan["receipt_sha256"], live=True)
    if path.exists():
        previous = read_sealed(path)
        if {
            k: v for k, v in previous.items() if k not in {"created_at", "receipt_sha256"}
        } != payload:
            raise ValueError(
                "STALE_AUTOMATED_REVIEW: audit differs from the exact draft or implementation"
            )
        if expected_hash is not None and previous["receipt_sha256"] != expected_hash:
            raise ValueError("STALE_AUTOMATED_REVIEW: expected audit hash differs")
        return previous
    return seal(path, {**payload, "created_at": now()})


def automated_review(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"], live=True)
    return checked_automated_receipt(project, plan, create=True)


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
    if review.kind == "automated_checks":
        audit = checked_automated_receipt(project, plan, review.automated_receipt_sha256)
        if review.reviewed_unit_ids != audit["reviewed_unit_ids"]:
            raise ValueError(
                "AUTOMATED_REVIEW_SAMPLE: review must retain the exact audited unit IDs"
            )
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
        "review": review.model_dump(exclude_none=True),
        "clinical_validation": {
            "data_manager": "manager_attestation",
            "synthetic_oracle": "synthetic_only",
            "automated_checks": "not_performed",
        }[review.kind],
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
    if approval["review"]["kind"] == "automated_checks":
        review = contract.Review.model_validate(approval["review"])
        audit = checked_automated_receipt(project, plan, review.automated_receipt_sha256)
        if (
            review.reviewed_unit_ids != audit["reviewed_unit_ids"]
            or approval["clinical_validation"] != "not_performed"
        ):
            raise ValueError("CORRUPT_APPROVAL: automatic review cannot attest clinical validation")
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
            feature["output"]: (
                r["window"]["purpose"]
                if r["window"]
                else "baseline"
                if r["at_index_basis"]
                else "descriptive"
            )
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
    relation = cell.get("relation")
    linkage = record["relations"].get(relation) if relation else None
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
        "root_reference": record["root"],
        "relation_rule": next(
            (r for r in plan["specification"]["relations"] if r["id"] == relation), None
        ),
        "linkage_evidence": {
            "status": linkage["status"],
            "coverage": linkage["coverage"],
            "matched_count": len(linkage["matched_records"]),
            "selected_count": len(linkage["selected_records"]),
            "excluded_counts": {reason: len(rows) for reason, rows in linkage["excluded"].items()},
        }
        if linkage
        else None,
        "source_records": values,
        "offset": offset,
        "total": len(refs),
        "next_offset": offset + limit if offset + limit < len(refs) else None,
    }


def source_row(project, request):
    plan = read_plan(project, request["preparation_id"], request["expected_sha256"])
    reference = request["reference"]
    item = next(
        (s for s in plan["source_snapshots"] if s["source"]["id"] == reference.get("source_id")),
        None,
    )
    if item is None:
        raise ValueError("source does not belong to this preparation")
    table = sources.load(
        contract.Source.model_validate(item["source"]),
        safe_path(directory(project), item["snapshot"]),
    )
    index = reference.get("record_index")
    if type(index) is not int or not 0 <= index < len(table.rows):
        raise ValueError("invalid source record position")
    row = table.rows[index]
    if table.ref(row) != reference:
        raise ValueError("STALE_SOURCE_ROW: full source record reference differs")
    return {"reference": reference, "values": row.values}


def execute(project, request):
    if not isinstance(request, dict):
        raise ValueError("preparation request must be an object")
    op = request.get("op")
    allowed = {
        "contract": {"op"},
        "inspect": {"op", "sources"},
        "preview": {"op", "sources", "specification"},
        "draft": {
            "op",
            "preparation_id",
            "sources",
            "specification",
            "candidate_ref",
            "parent",
            "reason",
            "author",
        },
        "aggregation_compose": {
            "op",
            "candidate_id",
            "revision_id",
            "sources",
            "unit",
            "definitions",
            "from_specification",
            "author",
            "reason",
        },
        "aggregation_patch": {
            "op",
            "candidate_ref",
            "revision_id",
            "operations",
            "author",
            "reason",
        },
        "aggregation_read": {
            "op",
            "candidate_ref",
            "preview_sha256",
            "section",
            "unit_id",
            "column",
            "offset",
            "limit",
        },
        "aggregation_preview": {"op", "candidate_ref"},
        "aggregation_diff": {"op", "before", "after"},
        "read": {"op", "preparation_id", "expected_sha256"},
        "automated_review": {"op", "preparation_id", "expected_sha256"},
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
        "source_row": {"op", "preparation_id", "expected_sha256", "reference"},
    }
    if op not in allowed or set(request) - allowed[op]:
        raise ValueError("unknown preparation operation or fields")
    if op == "contract":
        from rde.infrastructure.preparation.aggregation import contract as aggregation_contract

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
            "aggregation": aggregation_contract(),
            "execution_semantics": {
                "unit_conversion": contract.UNIT_CONVERSION_SEMANTICS,
                "source_schema": "inspect returns a hash-bound rde-source-table-schema-v1 per verified source, preserving column order, raw text storage, parser settings, observed missingness and uniqueness. It does not declare clinical roles or confirmed keys. This raw-source schema is separate from the preparation's analysis.schema.json (explicit typed rules) and downstream intake's semantic variable classification.",
                "cohort": "Each cohort.keep executes exactly one predicate. Multiple conditions need separate rules, applied sequentially. Rule id/reason are explanations, not executable conditions.",
                "filters": "relation.filters address columns of that relation's event source, not the main unit table. Numeric comparisons use literal constants. Cross-column dates belong in window, never filters.",
                "window": "Event time minus the unit index time is compared in fractional 24-hour days with start_days/end_days and bounds. end_days=0 means the exact index timestamp, not the end of its calendar day. followup_end_column additionally bounds event time when present.",
                "baseline_availability": "With window.purpose=baseline, available_column is parsed and events known after index are classified not_available and cannot contribute feature values. availability=event_time_confirmed explicitly uses event time instead. This check is implemented by RDE; do not add a duplicate cross-column filter.",
                "coverage": "coverage.mode=by_column reads the named column from the MAIN unit row: exported_values => complete; not_exported_values => not_exported; every other value => unknown. With no matching records these produce no_record/not_exported/unknown_coverage statuses respectively. Coverage does not itself delete a unit.",
                "exclude_statuses": "These statuses delete the ENTIRE analysis unit after aggregation. The default empty list retains units without usable events. Filtering unusable/future event records does not require excluding their patients or encounters.",
                "column_roles": "Derived fields with a window inherit baseline/followup from window.purpose. Without a window and without at_index_basis they are descriptive, not baseline predictors. A declared at_index_basis without a window attests index-time availability. A requested all-time descriptive medication count must not acquire an invented baseline window or availability assertion.",
                "aggregation": "Every relation is aggregated independently to each unit before combining features; raw event tables are never joined together. count counts selected event records. Missing feature values and linkage statuses stay separate; unknown/not-exported coverage is not evidence of zero events.",
                "aggregation_unique": "unique requires one distinct nonmissing value across ALL records selected for that relation and unit, after declared value typing and unit conversion. It returns a single value, not a list of distinct values. Different values at different event times still conflict. Do not add unique as a tie check for first/last; it imposes a different, stronger whole-window requirement.",
                "aggregation_first_last": "first/last requires an explicit event-time window and selects the earliest/latest timestamp among selected records with a nonmissing feature value, after declared value typing and unit conversion. Unequal values at other timestamps do not conflict. All nonmissing values at the selected timestamp must agree; unequal values raise a blocker, and identical-value ties retain all contributing source records. Physical row order is never a tie breaker. No usable feature value produces null, not zero.",
                "aggregation_evidence": "Draft/release retain validation.json population and per-stage flow, relationships/status counts, feature quality, issues/exceptions and exact trace.jsonl source members. first/last already blocks conflicting selected-time values and preserves every equal-valued selected-time contributor. Do not require invented latest-value-list, conflict-flag or duplicated stage-count analysis columns to establish these native audit facts. Published report still explains the observed evidence and limits.",
                "validation": "Preview executes the specification and returns denominators, statuses and technical issues without approval or persistent analysis version. Zero blockers is not semantic or clinical approval; requirement alignment and actual linkage truth require review.",
                "automated_review": "After an immutable draft, automated_review requires preparation_id and expected_sha256. The server verifies every retained file and live source, the native analysis.schema.json against declared rules/identifier roles/headers/value types, all included trace identities and denominators, and every CSV/typed row against its included trace. It saves rde-preparation-automated-checks-v1 with an immutable receipt_sha256 and up to 100 actual reviewed_unit_ids. This is consistency checking, not independent recomputation, clinical validation or a human review. Prepared storage supports text and finite numbers; root dates and booleans remain explicit text unless a numeric rule was declared. Do not infer clinical roles or model types from this storage schema.",
                "automated_approval": "approve review.kind=automated_checks requires automated_receipt_sha256, denominator_confirmed=true, exactly the audited reviewed_unit_ids in their returned order, and notes. The server revalidates the sealed audit, files, sources and implementation; caller assertions alone cannot approve. Exact warning acknowledgements and attributed reviewer are still required. Approval and release clinical_validation remain not_performed. Other review kinds cannot carry an automated receipt.",
            },
            "clinical_truth": "Software validation and reviewer attestation are distinct; neither proves real clinical linkage truth.",
        }
    root = directory(project)
    with locked(root):
        if op.startswith("aggregation_"):
            from rde.infrastructure.preparation.aggregation import execute as aggregation_execute

            return aggregation_execute(project, request)
        if op == "source_row":
            return source_row(project, request)
        if op == "bundle":
            from rde.infrastructure.preparation.portable import export_bundle

            return export_bundle(project, request)
        if op == "inspect":
            return sources.inspect({s.id: sources.load(s) for s in source_list(request["sources"])})
        if op == "preview":
            spec = contract.Specification.model_validate(request["specification"])
            evaluated = engine.Evaluation(
                {s.id: sources.load(s) for s in source_list(request["sources"])}, spec, project.id
            ).evaluate()
            return {
                "schema": "rde-preparation-preview-v1",
                "advisory_only": True,
                "summary": evaluated.summary(),
                "issues": [
                    {k: v for k, v in issue.items() if k != "records"}
                    for issue in evaluated.issues[:100]
                ],
                "issue_count": len(evaluated.issues),
            }
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
            "automated_review": automated_review,
            "approve": approve,
            "release": release,
            "page": page,
            "trace": trace,
        }[op](project, request)
