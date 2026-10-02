"""Import fixed external evidence and publish figures without rerunning an analysis.

Workbench owns source parsing, human approval and the pinned R execution. This
workflow verifies their complete byte-bound handoff; it does not certify source
truth or advance the patient-level EDA pipeline.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid

from rde.infrastructure.evidence.contract import publication_result
from rde.infrastructure.prediction.splits import digest

MAX_FILE = 100 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_R_MODEL = MAX_TOTAL
HEX = re.compile(r"[a-f0-9]{64}")
COLUMNS = {
    "study_id",
    "report_id",
    "treatment",
    "comparator",
    "effect",
    "se",
    "outcome",
    "timepoint",
    "decision",
    "reason",
    "source",
    "locator",
    "risk_of_bias",
    "bias_reason",
    "design",
    "population",
    "effect_modifiers",
    "effect_measure",
}
# Same whitespace accepted by the Workbench's String.trim().
JS_SPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def require(condition, message):
    if not condition:
        raise ValueError(f"Evidence source: {message}")


def canonical_id(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value, "use a canonical UUID")
    return value


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return sha(path.read_bytes())


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def safe_path(root, relative):
    require(isinstance(relative, str) and 0 < len(relative) <= 500, "invalid relative path")
    name = PurePosixPath(relative)
    require(
        not name.is_absolute()
        and str(name) == relative
        and all(p not in {"", ".", ".."} for p in name.parts)
        and not any(c in relative for c in ("\\", "\x00")),
        "path must be a normalized relative path",
    )
    path = root
    for part in name.parts:
        path = path / part
        require(not path.is_symlink(), "symlinked evidence is forbidden")
    require(path.resolve().is_relative_to(root.resolve()), "path leaves its project")
    return path


def load_json(path):
    require(path.stat().st_size <= 16 * 1024 * 1024, "JSON record exceeds the size limit")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid
    )


def write_new(path, value):
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())


def sealed(value):
    return {**value, "receipt_sha256": digest(value)}


def read_sealed(path):
    value = load_json(path)
    require(
        isinstance(value, dict)
        and value.get("receipt_sha256")
        == digest({k: v for k, v in value.items() if k != "receipt_sha256"}),
        "saved receipt failed integrity verification",
    )
    return value


def workflow_root(project):
    root = safe_path(project.output_dir.resolve(), "artifacts/evidence_publication")
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def locked(project):
    root = workflow_root(project)
    with safe_path(root, ".lock").open("a+b") as file:
        if os.name == "nt":
            import msvcrt

            if file.seek(0, os.SEEK_END) == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)

            def acquire():
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(file, fcntl.LOCK_UN)

        try:
            acquire()
        except (BlockingIOError, PermissionError) as error:
            raise ValueError(
                "This evidence workflow is busy; retry after the active operation."
            ) from error
        try:
            yield
        finally:
            release()


def event(project, action, **details):
    path = safe_path(workflow_root(project), "decision_log.jsonl")
    record = {"at": timestamp(), "project_id": project.id, "action": action, **details}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def verify_bundle(project, source_id, directory, expected):
    """Read actual bytes, not a self-reported 'verified' flag or arbitrary source path."""
    require(isinstance(expected, str) and HEX.fullmatch(expected), "bundle SHA256 is required")
    bundle_path = safe_path(directory, "bundle.json")
    require(file_hash(bundle_path) == expected, "bundle differs from requested SHA256")
    bundle = load_json(bundle_path)
    require(bundle.get("schema") == "evidence-source-bundle-v1", "unsupported bundle contract")
    require(
        bundle.get("project_id") == project.id and bundle.get("source_id") == source_id,
        "bundle belongs to another project or source",
    )
    identity = bundle["identity"]
    require(
        set(identity) == {"project_id", "dataset_id", "plan_id", "job_id", "node_id"},
        "incomplete Workbench identity",
    )
    for value in identity.values():
        canonical_id(value)
    files = bundle["files"]
    require(isinstance(files, dict) and 10 <= len(files) <= 128, "invalid file inventory")
    total = 0
    for name, metadata in files.items():
        path = safe_path(directory, name)
        require(name != "bundle.json" and path.is_file(), "missing inventory file")
        size = path.stat().st_size
        # A complete netmeta fit includes study covariance/weight matrices.
        # Retain it whole; numerical JSON keeps its separate 16 MiB guard and
        # the entire source bundle still shares the existing 512 MiB budget.
        limit = MAX_R_MODEL if name == "engine/network-model.rds" else MAX_FILE
        require(
            type(metadata.get("bytes")) is int and size == metadata["bytes"] and size <= limit,
            "file size differs or exceeds limit",
        )
        total += size
        require(
            total <= MAX_TOTAL and file_hash(path) == metadata.get("sha256"),
            "file SHA256 differs or bundle exceeds limit",
        )
    required = {
        "approved-plan.json",
        "reviewed-plan.json",
        "source-schema.json",
        "source-table.json",
        "review.json",
        "options.json",
        "engine/engine-input.json",
        "engine/numeric-result.json",
        "engine/analyze.R",
        "engine/execution.json",
        "engine/output-hashes.json",
    }
    require(required <= files.keys(), "missing required source evidence")
    source = bundle["source"]
    require(source["file"] in files and source["file"].startswith("source/"), "missing raw source")
    require(source.get("sha256") == files[source["file"]]["sha256"], "raw source SHA256 differs")
    require(source.get("schema_sha256") == files["source-schema.json"]["sha256"], "schema differs")
    require(
        isinstance(source.get("filename"), str) and bool(source["filename"]), "missing filename"
    )
    require(source.get("sheet") is None or isinstance(source["sheet"], str), "invalid source sheet")

    def read(name):
        return load_json(safe_path(directory, name))

    approved, reviewed = read("approved-plan.json"), read("reviewed-plan.json")
    require(
        approved.get("status") == "approved"
        and bool(approved.get("approvedAt"))
        and approved.get("scopePolicy") == "approved-only"
        and approved.get("domainId") == "evidence-synthesis",
        "approved evidence plan is required",
    )
    require(
        approved.get("approvalHash") == files["reviewed-plan.json"]["sha256"],
        "reviewed plan bytes differ from approval hash",
    )
    draft = {k: v for k, v in approved.items() if k not in {"approvedAt", "approvalHash"}}
    draft["status"] = "draft"
    require(reviewed == draft, "approved plan differs from the reviewed draft")
    for field, key in (("id", "plan_id"), ("projectId", "project_id"), ("datasetId", "dataset_id")):
        require(approved.get(field) == identity[key], "approved plan ownership differs")
    require(
        approved.get("sourceHash") == source["sha256"]
        and approved.get("schemaHash") == source["schema_sha256"],
        "plan source binding differs",
    )
    options, review = read("options.json"), read("review.json")
    from rde.infrastructure.evidence.arm_lineage import verify as verify_arm_lineage

    arm_origin = verify_arm_lineage(bundle, directory, options)
    payload, execution = read("engine/engine-input.json"), read("engine/execution.json")
    analysis = read("engine/numeric-result.json")
    require(
        options == approved.get("evidence") == payload.get("options") == analysis.get("options"),
        "numerical settings differ from the approved plan",
    )
    synthesis_steps = [
        step for step in approved.get("steps", []) if step.get("tool") == "evidence-synthesis"
    ]
    require(
        len(synthesis_steps) == 1 and synthesis_steps[0].get("args", {}).get("options") == options,
        "approved workflow does not contain this synthesis",
    )
    require(options.get("independentParallelTrials") is True, "trial design was not confirmed")
    require(review.get("valid") is True and review.get("issues") == [], "review did not pass")
    require(
        payload.get("review") == review and payload.get("rows") == review.get("included"),
        "engine input differs from the reviewed rows",
    )
    require(
        review.get("optionsHash") == files["options.json"]["sha256"]
        and review.get("inputHash") == files["source-table.json"]["sha256"],
        "review source-table/options binding differs",
    )
    require(
        execution.get("status") == "completed"
        and execution.get("containerRemoved") is True
        and re.fullmatch(r"sha256:[a-f0-9]{64}", execution.get("image", "")),
        "completed pinned R execution is required",
    )
    for key, name in (
        ("inputSha256", "engine/engine-input.json"),
        ("scriptSha256", "engine/analyze.R"),
        ("optionsHash", "options.json"),
        ("auditHash", "review.json"),
    ):
        require(
            execution.get(key) == files[name]["sha256"],
            "execution input/script/review binding differs",
        )
    engine_hashes = read("engine/output-hashes.json")
    require(isinstance(engine_hashes, dict), "missing R output inventory")
    require(
        set(engine_hashes)
        == {n[7:] for n in files if n.startswith("engine/")} - {"output-hashes.json"},
        "incomplete R output inventory",
    )
    for name, expected_hash in engine_hashes.items():
        require(files[f"engine/{name}"]["sha256"] == expected_hash, "R output binding differs")
    execution_origin = verify_execution_origin(bundle, read, engine_hashes, approved, execution)
    for key, value in analysis["review"].items():
        require(key in review and review[key] == value, "numerical review differs from input")
    observations = analysis["observations"]
    require(len(observations) == len(review["included"]), "numerical source membership differs")
    for original, numeric in zip(review["included"], observations, strict=True):
        require(
            all(k in numeric and numeric[k] == v for k, v in original.items()),
            "numerical observation differs from the original input",
        )
    verify_table(read("source-table.json"), review)
    result = publication_result(
        analysis,
        {
            "contract": "verified-external-r-evidence-v1",
            "project_id": project.id,
            "source_id": source_id,
            "identity": identity,
            "source": source,
            "bundle_sha256": expected,
            "numeric_file_sha256": files["engine/numeric-result.json"]["sha256"],
            "image": execution["image"],
            "script_sha256": execution["scriptSha256"],
            **({"execution_origin": execution_origin} if execution_origin else {}),
            **({"arm_origin": arm_origin} if arm_origin else {}),
            "verification_scope": "saved bytes, approved plan, parsed table, review and R receipt; not source truth or patient EDA audit",
        },
    )
    return bundle, result


def verify_execution_origin(bundle, read, engine_hashes, approved, execution):
    """Validate explicit Workbench checkpoint/reuse lineage when supplied.

    External R sources need not use Workbench's retry store. A supplied lineage
    is nevertheless evidence, never an unchecked advisory 'reused' flag.
    """
    files, identity = bundle["files"], bundle["identity"]
    names = {"execution-origin.json", "execution-checkpoint.json"}
    present = names & files.keys()
    if not present:
        return None
    require(present == names, "incomplete execution origin")
    origin, checkpoint = read("execution-origin.json"), read("execution-checkpoint.json")
    require(
        origin.get("schema") == "workbench-evidence-execution-origin-v1"
        and checkpoint.get("schema") == "workbench-evidence-checkpoint-v1",
        "unsupported execution checkpoint",
    )
    require(origin.get("identity") == identity, "retry belongs to another execution")
    old = checkpoint.get("identity", {})
    require(set(old) == set(identity) and origin.get("origin") == old, "invalid original execution")
    for value in old.values():
        canonical_id(value)
    for key in ("project_id", "dataset_id", "plan_id"):
        require(old[key] == identity[key], "checkpoint belongs to another approved source")
    kind = origin.get("kind")
    require(kind in {"executed", "reused"}, "unknown execution origin kind")
    require(
        (
            kind == "executed"
            and old == identity
            and origin.get("checkpointFile") == "evidence-checkpoint.json"
        )
        or (
            kind == "reused"
            and old["job_id"] != identity["job_id"]
            and old["node_id"] != identity["node_id"]
            and origin.get("checkpointFile") == "evidence-origin-checkpoint.json"
        ),
        "execution/reuse identity differs",
    )
    canonical_id(origin.get("checkpointArtifactId"))
    require(
        origin.get("checkpointSha256") == files["execution-checkpoint.json"]["sha256"],
        "checkpoint bytes differ from execution origin",
    )
    binding = checkpoint.get("binding", {})
    require(
        binding
        == {
            "planSha256": files["approved-plan.json"]["sha256"],
            "sourceSha256": bundle["source"]["sha256"],
            "schemaSha256": bundle["source"]["schema_sha256"],
            "sheet": bundle["source"].get("sheet"),
            "image": execution["image"],
            "inputSha256": execution["inputSha256"],
            "scriptSha256": execution["scriptSha256"],
        },
        "checkpoint numerical binding differs",
    )
    inventory = checkpoint.get("files", {})
    require(
        set(inventory) == set(engine_hashes) | {"output-hashes.json"},
        "checkpoint inventory differs",
    )
    prefix = f"datasets/{old['dataset_id']}/runs/{old['job_id']}/{old['node_id']}/output/"
    for name, expected in inventory.items():
        canonical_id(expected.get("artifactId"))
        require(
            expected.get("sha256") == files[f"engine/{name}"]["sha256"]
            and expected.get("bytes") == files[f"engine/{name}"]["bytes"]
            and isinstance(expected.get("sourcePath"), str)
            and expected["sourcePath"].replace("\\", "/") == prefix + name,
            "checkpoint member or original location differs",
        )
    return origin


def verify_table(table, review):
    columns, rows = table["columns"], table["rows"]
    require(
        isinstance(columns, list)
        and all(isinstance(v, str) for v in columns)
        and len(set(columns)) == len(columns)
        and COLUMNS <= set(columns)
        and len(columns) <= 100,
        "invalid source columns",
    )
    require(
        isinstance(rows, list) and 1 <= len(rows) <= 2000 and len(rows) == review["inputRows"],
        "source table row count differs",
    )
    require(len(review["decisions"]) == len(rows), "incomplete row disposition")
    included = {row["row"]: row for row in review["included"]}
    for index, (values, decision) in enumerate(
        zip(rows, review["decisions"], strict=True), start=2
    ):
        require(
            isinstance(values, list)
            and len(values) <= len(columns)
            and all(isinstance(v, str) and len(v) <= 8000 for v in values),
            "invalid source cells",
        )
        record = {
            name: (values[i] if i < len(values) else "").strip(JS_SPACE)
            for i, name in enumerate(columns)
        }
        require(
            decision
            == {
                "row": index,
                **{k: record[k] for k in ("study_id", "report_id", "decision", "reason", "source")},
            },
            "row disposition differs from source table",
        )
        if record["decision"] == "include":
            numeric = {**record, "row": index}
            for key in ("effect", "se"):
                require(
                    re.fullmatch(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?", record[key], re.I),
                    "invalid source effect or SE",
                )
                numeric[key] = float(record[key])
                require(math.isfinite(numeric[key]), "nonfinite source effect or SE")
            require(
                included.get(index) == numeric, "reviewed effect/identity differs from source table"
            )
        else:
            require(
                record["decision"] == "exclude" and index not in included, "unresolved source row"
            )


def source_directory(project, source_id):
    return safe_path(workflow_root(project), f"sources/{canonical_id(source_id)}")


def read_source(project, source_id, expected=None):
    directory = source_directory(project, source_id)
    receipt = read_sealed(safe_path(directory, "source-receipt.json"))
    require(
        receipt.get("schema") == "evidence-source-receipt-v1"
        and receipt.get("project_id") == project.id
        and receipt.get("source_id") == source_id,
        "source receipt ownership differs",
    )
    if expected is not None:
        require(
            receipt["receipt_sha256"] == expected, "source receipt differs from requested SHA256"
        )
    bundle, result = verify_bundle(project, source_id, directory, receipt["bundle_sha256"])
    require(
        receipt["identity"] == bundle["identity"]
        and receipt["source"] == bundle["source"]
        and receipt["result_path"]
        == str((directory / "publication-result.json").relative_to(project.output_dir))
        and receipt["receipt_path"]
        == str((directory / "source-receipt.json").relative_to(project.output_dir)),
        "source metadata differs from the verified bundle",
    )
    saved = read_sealed(safe_path(directory, "publication-result.json"))
    require(
        saved == result and saved["receipt_sha256"] == receipt["numerical_receipt_sha256"],
        "frozen numerical receipt differs",
    )
    return receipt, result


def import_source(project, source_id, expected_bundle_sha256):
    canonical_id(source_id)
    with locked(project):
        final = source_directory(project, source_id)
        if final.exists():
            receipt, _ = read_source(project, source_id)
            require(
                receipt["bundle_sha256"] == expected_bundle_sha256,
                "source ID already belongs to another bundle",
            )
            return receipt
        incoming = safe_path(project.output_dir.resolve(), f"incoming/evidence/{source_id}")
        bundle, result = verify_bundle(project, source_id, incoming, expected_bundle_sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging = safe_path(final.parent, f".pending-{uuid.uuid4()}")
        staging.mkdir()
        try:
            for name in ["bundle.json", *bundle["files"]]:
                target = safe_path(staging, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(safe_path(incoming, name).read_bytes())
                    output.flush()
                    os.fsync(output.fileno())
            _, copied_result = verify_bundle(project, source_id, staging, expected_bundle_sha256)
            require(copied_result == result, "source changed during import")
            write_new(staging / "publication-result.json", result)
            receipt = sealed(
                {
                    "schema": "evidence-source-receipt-v1",
                    "project_id": project.id,
                    "source_id": source_id,
                    "created_at": timestamp(),
                    "identity": bundle["identity"],
                    "source": bundle["source"],
                    "bundle_sha256": expected_bundle_sha256,
                    "numerical_receipt_sha256": result["receipt_sha256"],
                    "receipt_path": str(
                        (final / "source-receipt.json").relative_to(project.output_dir)
                    ),
                    "result_path": str(
                        (final / "publication-result.json").relative_to(project.output_dir)
                    ),
                }
            )
            write_new(staging / "source-receipt.json", receipt)
            os.rename(staging, final)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        event(
            project,
            "import_evidence_source",
            source_id=source_id,
            receipt_sha256=receipt["receipt_sha256"],
        )
        return receipt


def render_directory(project, source_id, render_id):
    return safe_path(source_directory(project, source_id), f"renders/{canonical_id(render_id)}")


def read_study(project, source_id, render_id, expected=None):
    source, result = read_source(project, source_id)
    directory = render_directory(project, source_id, render_id)
    require(
        not safe_path(directory, "failure.json").exists(),
        "render attempt failed; use a new render ID",
    )
    record = read_sealed(safe_path(directory, "evidence-study.json"))
    require(
        record.get("schema") == "evidence-study-v1"
        and record.get("project_id") == project.id
        and record.get("source_id") == source_id
        and record.get("render_id") == render_id
        and record.get("source_receipt_sha256") == source["receipt_sha256"]
        and record.get("source_numerical_receipt_sha256") == result["receipt_sha256"],
        "figure source binding differs",
    )
    require(
        record.get("identity") == source["identity"]
        and record.get("result_path") == source["result_path"]
        and record.get("receipt_path")
        == str((directory / "evidence-study.json").relative_to(project.output_dir)),
        "study metadata differs from its source",
    )
    if expected is not None:
        require(record["receipt_sha256"] == expected, "study receipt differs from requested SHA256")
    root = project.output_dir.resolve()
    require(
        record.get("figures")
        and len(record["artifacts"]) == len(record["figures"]) * 6 + 1
        and len({item["path"] for item in record["artifacts"]}) == len(record["artifacts"]),
        "figure artifact inventory is incomplete",
    )
    for item in record["artifacts"]:
        path = safe_path(root, item["path"])
        require(path.is_relative_to(directory), "figure file belongs to another rendering")
        require(
            path.is_file()
            and path.stat().st_size == item["bytes"]
            and file_hash(path) == item["sha256"],
            "saved figure artifact failed integrity verification",
        )
    paths = {
        str((root / a["path"]).resolve()) for a in record["artifacts"] if a["format"] != "report"
    }
    declared = []
    for figure in record["figures"]:
        publication = figure["publication"]
        require(
            set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
            and publication["source_receipt_sha256"] == result["receipt_sha256"]
            and figure["path"] == publication["files"]["png"],
            "figure metadata binding differs",
        )
        declared.extend(publication["files"].values())
    require(
        len(declared) == len(set(declared)) and set(declared) == paths,
        "figure inventory is incomplete",
    )
    return record, result


def render_study(project, source_id, expected_source_sha256, render_id):
    from rde.infrastructure.evidence.publication import figures

    with locked(project):
        source, result = read_source(project, source_id, expected_source_sha256)
        directory = render_directory(project, source_id, render_id)
        if directory.exists():
            require(
                (directory / "evidence-study.json").is_file(),
                "render attempt is unfinished or failed; retain it and use a new render ID",
            )
            return read_study(project, source_id, render_id)[0]
        directory.mkdir(parents=True)
        write_new(
            directory / "started.json", {"at": timestamp(), "source_sha256": expected_source_sha256}
        )
        event(project, "render_evidence_started", source_id=source_id, render_id=render_id)
        try:
            rendered = figures(result, directory, "evidence")
            lines = [
                "# 文獻整合研究圖稿",
                "",
                "本圖稿使用已核准並保存的 R 分析數值；沒有重新估計模型。",
                "來源核對不等於文獻真實性、研究設計或個案資料完整稽核。",
                "",
                f"數值收據 SHA256：`{result['receipt_sha256']}`",
                "",
            ]
            artifacts = []
            for figure in rendered:
                p = figure["publication"]
                lines += [
                    f"## Figure {p['figure_number']}",
                    "",
                    f"![Figure {p['figure_number']}]({Path(figure['path']).name})",
                    "",
                    p["caption_en"],
                    "",
                    f"中文解釋：{p['explanation_zh']}",
                    "",
                ]
                for key, name in p["files"].items():
                    path = Path(name)
                    artifacts.append(
                        {
                            "path": str(path.relative_to(project.output_dir)),
                            "format": key,
                            "sha256": file_hash(path),
                            "bytes": path.stat().st_size,
                        }
                    )
            report = directory / "evidence-study.md"
            report.write_text("\n".join(lines), encoding="utf-8")
            artifacts.append(
                {
                    "path": str(report.relative_to(project.output_dir)),
                    "format": "report",
                    "sha256": file_hash(report),
                    "bytes": report.stat().st_size,
                }
            )
            read_source(project, source_id, expected_source_sha256)
            record = sealed(
                {
                    "schema": "evidence-study-v1",
                    "project_id": project.id,
                    "source_id": source_id,
                    "render_id": render_id,
                    "source_receipt_sha256": source["receipt_sha256"],
                    "source_numerical_receipt_sha256": result["receipt_sha256"],
                    "identity": source["identity"],
                    "figures": rendered,
                    "artifacts": artifacts,
                    "created_at": timestamp(),
                    "result_path": source["result_path"],
                    "receipt_path": str(
                        (directory / "evidence-study.json").relative_to(project.output_dir)
                    ),
                }
            )
            write_new(directory / "evidence-study.json", record)
            read_study(project, source_id, render_id, record["receipt_sha256"])
        except Exception as error:
            write_new(directory / "failure.json", {"at": timestamp(), "error": str(error)[:4000]})
            event(project, "render_evidence_failed", source_id=source_id, render_id=render_id)
            raise
        event(
            project,
            "render_evidence_completed",
            source_id=source_id,
            render_id=render_id,
            receipt_sha256=record["receipt_sha256"],
        )
        return record


def get_source(project, source_id):
    with locked(project):
        source, _ = read_source(project, source_id)
        directory = safe_path(source_directory(project, source_id), "renders")
        renders = []
        for path in sorted(directory.iterdir()) if directory.exists() else []:
            canonical_id(path.name)
            target = render_directory(project, source_id, path.name)
            if (target / "evidence-study.json").is_file() and not safe_path(
                target, "failure.json"
            ).exists():
                renders.append(
                    {"status": "completed", "record": read_study(project, source_id, path.name)[0]}
                )
            else:
                failure = safe_path(target, "failure.json")
                renders.append(
                    {
                        "status": "failed" if failure.is_file() else "unfinished",
                        "render_id": path.name,
                        "failure": load_json(failure) if failure.is_file() else None,
                    }
                )
        return {"source": source, "renders": renders}
