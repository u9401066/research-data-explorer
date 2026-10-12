"""Complete prepared-source handoff; never guess headers, missingness or types."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
import zipfile

from rde.infrastructure.evidence.workflow import safe_path
from rde.infrastructure.preparation.sources import file_hash

MAX_BUNDLE = 2 * 1024**3


def output_schema(spec, columns):
    features = {f.output: f for r in spec.relations for f in r.features}
    result = []
    ids = set(spec.unit.keys + spec.unit.subject_keys + ["_rde_unit_id", "_rde_subject_id"])
    for name in columns:
        feature = features.get(name)
        numeric = feature and (
            feature.value_type == "number"
            or feature.aggregate in {"count", "exists", "days_to_first"}
        )
        rule = spec.unit.columns.get(name)
        result.append(
            {
                "name": name,
                "type": "number" if numeric or (rule and rule.value_type == "number") else "text",
                "identifier": name in ids,
            }
        )
    return {"schema": "rde-prepared-columns-v1", "columns": result, "missing": "json_null_only"}


def verify_bundle_folder(folder, release_sha):
    from rde.infrastructure.preparation import workflow as w

    plan = w.read_sealed(folder / "plan.json")
    approval = w.read_sealed(folder / "approval.json")
    release = w.read_sealed(folder / "release.json")
    if (
        release.get("schema") != "rde-data-release-v1"
        or release.get("receipt_sha256") != release_sha
        or approval.get("plan_sha256") != plan["receipt_sha256"]
        or release.get("plan_sha256") != plan["receipt_sha256"]
        or release.get("approval_sha256") != approval["receipt_sha256"]
        or approval.get("project_id") != plan["project_id"]
        or release.get("project_id") != plan["project_id"]
        or approval.get("preparation_id") != plan["preparation_id"]
        or release.get("release_id") != plan["preparation_id"]
        or not plan["summary"]["ready_for_approval"]
    ):
        raise ValueError("CORRUPT_BUNDLE: release, plan and approval do not agree")
    expected = dict(plan["files"])
    for item in plan["source_snapshots"]:
        source = item["source"]
        expected[item["snapshot"]] = {"sha256": source["sha256"], "bytes": source["bytes"]}
    names = set(expected) | {"plan.json", "approval.json", "release.json"}
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != names:
        raise ValueError("CORRUPT_BUNDLE: evidence closure is incomplete or contains extra files")
    w.verify_files(folder, expected)
    if {k: release["dataset"][k] for k in ("sha256", "bytes")} != plan["files"]["analysis.csv"]:
        raise ValueError("CORRUPT_BUNDLE: released dataset differs from the plan")
    return plan, release


def export_bundle(project, request):
    from rde.infrastructure.preparation import workflow as w

    plan = w.read_plan(project, request["preparation_id"], request["expected_sha256"])
    root = w.directory(project)
    folder = safe_path(root, "versions/" + plan["preparation_id"])
    approval = w.read_sealed(folder / "approval.json")
    release = w.read_sealed(folder / "release.json")
    if (
        release["receipt_sha256"] != request["release_sha256"]
        or release["plan_sha256"] != plan["receipt_sha256"]
        or approval["plan_sha256"] != plan["receipt_sha256"]
        or release["approval_sha256"] != approval["receipt_sha256"]
    ):
        raise ValueError("STALE_RELEASE: bundle must bind the exact approved release")
    destination = safe_path(root, "bundles/" + release["receipt_sha256"] + ".zip")
    receipt_path = destination.with_suffix(".json")
    if receipt_path.exists():
        receipt = w.read_sealed(receipt_path)
        if file_hash(destination) != receipt["sha256"]:
            raise ValueError("CORRUPT_BUNDLE: retained archive changed")
        return receipt
    paths = {name: safe_path(folder, name) for name in plan["files"]}
    paths.update({name: folder / name for name in ("plan.json", "approval.json", "release.json")})
    paths.update(
        {item["snapshot"]: safe_path(root, item["snapshot"]) for item in plan["source_snapshots"]}
    )
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name("." + str(uuid.uuid4()) + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for name, path in sorted(paths.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with archive.open(info, "w") as out, path.open("rb") as source:
                    shutil.copyfileobj(source, out, length=1024 * 1024)
        if destination.exists() and file_hash(destination) != file_hash(temporary):
            raise ValueError("IMMUTABLE_CONFLICT: archive bytes differ")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return w.seal(
        receipt_path,
        {
            "schema": "rde-prepared-bundle-v1",
            "path": str(destination),
            "sha256": file_hash(destination),
            "bytes": destination.stat().st_size,
            "release_sha256": release["receipt_sha256"],
            "files": len(paths),
        },
    )


def import_bundle(project, path, expected_sha, release_sha):
    from rde.infrastructure.preparation import workflow as w

    if not all(
        isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for v in (expected_sha, release_sha)
    ):
        raise ValueError("prepared intake requires the exact bundle and release SHA-256")
    source = Path(path)
    if (
        not source.is_absolute()
        or source.stat().st_size > MAX_BUNDLE
        or file_hash(source) != expected_sha
    ):
        raise ValueError("prepared bundle path, size or hash differs")
    root = w.directory(project)
    with w.locked(root):
        folder = safe_path(root, "imports/" + expected_sha)
        if not folder.exists():
            stage = safe_path(root, "imports/.pending-" + str(uuid.uuid4()))
            stage.mkdir(parents=True, mode=0o700)
            try:
                with zipfile.ZipFile(source) as archive:
                    members = archive.infolist()
                    names = [m.filename for m in members]
                    if (
                        len(names) > 128
                        or len(names) != len(set(names))
                        or sum(m.file_size for m in members) > MAX_BUNDLE
                    ):
                        raise ValueError(
                            "prepared bundle exceeds extraction limits or repeats a file"
                        )
                    for member in members:
                        target = safe_path(stage, member.filename)
                        mode = member.external_attr >> 16
                        if (
                            member.is_dir()
                            or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                            or member.flag_bits & 1
                        ):
                            raise ValueError(
                                "bundle permits only ordinary, unencrypted evidence files"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        with archive.open(member) as input_file, target.open("xb") as output:
                            shutil.copyfileobj(input_file, output, length=1024 * 1024)
                        target.chmod(0o600)
                if file_hash(source) != expected_sha:
                    raise ValueError("bundle changed during extraction")
                verify_bundle_folder(stage, release_sha)
                os.replace(stage, folder)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)  # Only this operation's unpublished staging directory.
        plan, release = verify_bundle_folder(folder, release_sha)
    return {
        "schema": "rde-prepared-intake-v1",
        "folder": str(folder),
        "bundle_sha256": expected_sha,
        "release_sha256": release_sha,
        "project_id": plan["project_id"],
        "preparation_id": plan["preparation_id"],
        "dataset": release["dataset"],
        "column_roles": release["column_roles"],
    }


def load_prepared(metadata):
    """Read typed approved values verbatim, retaining all columns and empty strings."""
    import math
    import pandas as pd
    from rde.domain.models.ingestion import RawDataNormalizationReport
    from rde.domain.models.variable import VariableRole, VariableType
    from rde.domain.services.variable_classifier import VariableClassifier
    from rde.infrastructure.preparation import workflow as w

    binding = metadata.preparation
    folder = Path(binding["folder"])
    plan, release = verify_bundle_folder(folder, binding["release_sha256"])
    if (
        file_hash(metadata.file_path) != release["dataset"]["sha256"]
        or metadata.file_format != "csv"
    ):
        raise ValueError("PREPARED_SOURCE_CHANGED: intake bytes differ from the approved dataset")
    schema = json.loads((folder / "analysis.schema.json").read_text(encoding="utf-8"))
    columns = schema["columns"]
    names = [c["name"] for c in columns]
    if schema.get("schema") != "rde-prepared-columns-v1" or len(names) != len(set(names)):
        raise ValueError("invalid prepared column contract")
    rows = list(w.lines(folder / "analysis.jsonl"))
    for row in rows:
        if set(row) != set(names):
            raise ValueError("prepared row does not match its column contract")
        for column in columns:
            value = row[column["name"]]
            if value is not None and (
                (column["type"] == "text" and not isinstance(value, str))
                or (
                    column["type"] == "number"
                    and (type(value) not in (int, float) or not math.isfinite(value))
                )
                or column["type"] not in ("number", "text")
            ):
                raise ValueError("prepared value does not match its declared type")
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    if hashlib.sha256(text.getvalue().encode("utf-8")).hexdigest() != release["dataset"]["sha256"]:
        raise ValueError("prepared typed values do not reproduce the approved CSV")
    frame = pd.DataFrame(
        {
            c["name"]: pd.Series(
                [r[c["name"]] for r in rows], dtype="float64" if c["type"] == "number" else object
            )
            for c in columns
        }
    )
    classifier = VariableClassifier()
    variables = []
    for column in columns:
        name = column["name"]
        series = frame[name]
        variable = classifier.classify(
            name,
            str(series.dtype),
            int(series.nunique(dropna=True)),
            len(frame),
            series.dropna().head(20).tolist(),
        )
        variable.n_missing = int(series.isna().sum())
        variable.extra["preparation_release_sha256"] = release["receipt_sha256"]
        variable.extra["preparation_time_role"] = release["column_roles"].get(name, "descriptive")
        if column["identifier"]:
            variable.role = VariableRole.ID
            variable.variable_type = VariableType.ID
        variables.append(variable)
    return frame, variables, len(frame), RawDataNormalizationReport(encoding_used="utf-8")
