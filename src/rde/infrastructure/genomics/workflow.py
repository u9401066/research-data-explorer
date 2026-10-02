"""Freeze approved multi-source DESeq2 runs and publish without refitting."""

import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from rde.infrastructure.evidence.workflow import (
    canonical_id,
    file_hash,
    safe_path,
    sealed,
    timestamp,
    write_new,
)
from rde.infrastructure.evidence.workflow import (
    load_json as _load_json,
)
from rde.infrastructure.genomics.contract import require
from rde.infrastructure.prediction.splits import digest

MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}")


def load_json(path):
    # The bounded count matrix contains up to five million cells. Ordinary
    # receipts retain the smaller default guard in the common helper.
    if path.stat().st_size <= 16 * 1024 * 1024:
        return _load_json(path)
    require(
        path.name
        in {
            "engine-input.json",
            "source-table.json",
            "publication-data.json",
            "publication-result.json",
            "review.json",
            "analysis-binding.json",
        }
        and path.stat().st_size <= MAX_FILE,
        "JSON record exceeds its size limit",
    )

    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid
    )


def read_sealed(path):
    value = load_json(path)
    require(
        isinstance(value, dict)
        and value.get("receipt_sha256")
        == digest({k: v for k, v in value.items() if k != "receipt_sha256"}),
        "saved receipt failed integrity verification",
    )
    return value


def verify_bundle(project, source_id, directory, expected):
    from rde.infrastructure.genomics.source import verify

    return verify(project, source_id, directory, expected)


def workflow_root(project):
    root = safe_path(project.output_dir.resolve(), "artifacts/genomics_publication")
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
                "This genomics workflow is busy; retry after the active operation."
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


def source_directory(project, source_id):
    return safe_path(workflow_root(project), f"sources/{canonical_id(source_id)}")


def read_source(project, source_id, expected=None):
    directory = source_directory(project, source_id)
    receipt = read_sealed(safe_path(directory, "source-receipt.json"))
    require(
        receipt.get("schema") == "genomics-source-receipt-v1"
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
        incoming = safe_path(project.output_dir.resolve(), f"incoming/genomics/{source_id}")
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
                    "schema": "genomics-source-receipt-v1",
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
            "import_genomics_source",
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
    record = read_sealed(safe_path(directory, "genomics-study.json"))
    require(
        record.get("schema") == "genomics-study-v1"
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
        == str((directory / "genomics-study.json").relative_to(project.output_dir)),
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
    from rde.infrastructure.genomics.publication import figures

    with locked(project):
        source, result = read_source(project, source_id, expected_source_sha256)
        directory = render_directory(project, source_id, render_id)
        if directory.exists():
            require(
                (directory / "genomics-study.json").is_file(),
                "render attempt is unfinished or failed; retain it and use a new render ID",
            )
            return read_study(project, source_id, render_id)[0]
        directory.mkdir(parents=True)
        write_new(
            directory / "started.json", {"at": timestamp(), "source_sha256": expected_source_sha256}
        )
        event(project, "render_genomics_started", source_id=source_id, render_id=render_id)
        try:
            rendered = figures(result, directory, "genomics")
            lines = [
                "# 基因研究圖稿",
                "",
                "本圖稿使用已核准並保存的 R 分析數值；沒有重新估計模型。",
                "來源核對不等於生物來源真實性、研究設計或個案資料完整稽核。",
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
            report = directory / "genomics-study.md"
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
                    "schema": "genomics-study-v1",
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
                        (directory / "genomics-study.json").relative_to(project.output_dir)
                    ),
                }
            )
            write_new(directory / "genomics-study.json", record)
            read_study(project, source_id, render_id, record["receipt_sha256"])
        except Exception as error:
            write_new(directory / "failure.json", {"at": timestamp(), "error": str(error)[:4000]})
            event(project, "render_genomics_failed", source_id=source_id, render_id=render_id)
            raise
        event(
            project,
            "render_genomics_completed",
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
            if (target / "genomics-study.json").is_file() and not safe_path(
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
