"""Immutable display editions from completed numerical receipts; never refit a study."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.presets import list_presets, resolve_preset
from rde.interface.mcp.tools.prediction_tools import atomic_json, verify_prediction_artifacts
from rde.interface.mcp.tools.clinical_tools import verify_clinical_artifacts


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_options(start_number, captions, figure_count):
    if type(start_number) is not int or not 1 <= start_number <= 999:
        raise ValueError("Figure start number must be an integer from 1 to 999.")
    if captions is None:
        captions = {}
    if not isinstance(captions, dict):
        raise ValueError("Captions must map original one-based figure numbers to edited text.")
    normalized = {}
    for key, value in captions.items():
        if (
            not isinstance(key, str)
            or not key.isdigit()
            or key != str(int(key))
            or not 1 <= int(key) <= figure_count
        ):
            raise ValueError("Caption references a figure outside this saved bundle.")
        if (
            not isinstance(value, dict)
            or not value
            or set(value) - {"title", "caption_en", "explanation_zh"}
        ):
            raise ValueError("A caption edit accepts only title, caption_en and explanation_zh.")
        for field, text in value.items():
            limit = 180 if field == "title" else 6000
            if not isinstance(text, str) or not text.strip() or len(text) > limit or "\x00" in text:
                raise ValueError(f"Invalid {field} caption text.")
        normalized[key] = value
    return {"start_number": start_number, "captions": normalized}


def verify_edition(record, root):
    if (
        not record.get("figures")
        or len(record.get("artifacts", [])) != len(record["figures"]) * 6 + 1
        or len({a["path"] for a in record["artifacts"]}) != len(record["artifacts"])
        or digest({k: v for k, v in record.items() if k != "receipt_sha256"})
        != record.get("receipt_sha256")
    ):
        raise ValueError("Saved figure edition receipt failed integrity verification.")
    for item in record.get("artifacts", []):
        path = (root / item["path"]).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or not path.is_file()
            or path.stat().st_size != item["bytes"]
            or file_hash(path) != item["sha256"]
        ):
            raise ValueError(
                "Saved figure edition failed integrity verification; it will not be overwritten."
            )


def create_edition(
    project,
    *,
    study_artifact,
    expected_record_sha256,
    preset_id,
    edition_id,
    start_number,
    captions,
):
    if not re.fullmatch(r"(?:clinical|prediction)_study_[a-f0-9]{16}\.json", study_artifact):
        raise ValueError("Use the exact completed clinical/prediction study artifact filename.")
    if str(uuid.UUID(edition_id)) != edition_id:
        raise ValueError("Edition ID must be a canonical UUID.")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_record_sha256):
        raise ValueError("Expected study record SHA256 is required.")
    root = project.output_dir.resolve()
    store = ArtifactStore(project.artifacts_dir)
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, study_artifact).resolve()
    if (
        not source.is_relative_to(root)
        or not source.is_file()
        or file_hash(source) != expected_record_sha256
    ):
        raise ValueError("Saved study record differs from the requested SHA256.")
    record = json.loads(source.read_text(encoding="utf-8"))
    result = record.get("result", {})
    if record.get("dataset_id") not in project.dataset_ids or result.get("status") != "completed":
        raise ValueError("A completed study belonging to this project is required.")
    prediction = study_artifact.startswith("prediction_")
    verifier = verify_prediction_artifacts if prediction else verify_clinical_artifacts
    if not verifier(record, root):
        raise ValueError(
            "Original numerical receipt or study artifacts failed integrity verification."
        )
    return _create_verified_edition(
        project,
        source=source,
        study_artifact=study_artifact,
        expected_record_sha256=expected_record_sha256,
        record=record,
        result=result,
        prediction=prediction,
        preset_id=preset_id,
        edition_id=edition_id,
        start_number=start_number,
        captions=captions,
    )


def _create_verified_edition(
    project,
    *,
    source,
    study_artifact,
    expected_record_sha256,
    record,
    result,
    prediction=False,
    preset_id,
    edition_id,
    start_number,
    captions,
):
    """Shared renderer; callers must first verify their full, typed source workflow."""
    if str(uuid.UUID(edition_id)) != edition_id:
        raise ValueError("Edition ID must be a canonical UUID.")
    root = project.output_dir.resolve()
    options = render_options(start_number, captions, len(record.get("figures", [])))
    request = {
        "source_artifact": study_artifact,
        "source_record_sha256": expected_record_sha256,
        "preset_id": preset_id,
        "options": options,
    }
    editions = (root / "figures" / "editions").resolve()
    if not editions.is_relative_to(root):
        raise ValueError("Figure edition directory must be inside this project.")
    final = editions / edition_id
    receipt_path = final / "publication-edition.json"
    if final.exists():
        if not receipt_path.is_file():
            raise ValueError("Existing figure edition is incomplete; choose a new edition ID.")
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        if previous.get("request") != request:
            raise ValueError("Edition ID already belongs to another rendering request.")
        verify_edition(previous, root)
        return previous
    preset = resolve_preset(preset_id)
    editions.mkdir(parents=True, exist_ok=True)
    staging = editions / f".pending-{uuid.uuid4()}"
    staging.mkdir()
    try:
        if result.get("spec", {}).get("family") == "sample_size":
            from rde.infrastructure.clinical.sample_size_report import figures
        elif result.get("spec", {}).get("family") == "evidence_synthesis":
            from rde.infrastructure.evidence.publication import figures
        elif prediction:
            from rde.infrastructure.prediction.publication import figures
        elif result["spec"]["family"] == "survival":
            from rde.infrastructure.clinical.survival_publication import figures
        elif result["spec"]["family"] == "longitudinal":
            from rde.infrastructure.clinical.longitudinal_publication import figures
        elif result["spec"]["family"] == "regression":
            from rde.infrastructure.clinical.regression_publication import figures
        elif result["spec"]["family"] == "repeated":
            from rde.infrastructure.clinical.repeated_publication import figures
        elif result["spec"]["family"] == "comparison":
            from rde.infrastructure.clinical.comparison_publication import figures
        elif result["spec"]["family"] == "weighting":
            from rde.infrastructure.clinical.weighting_publication import figures
        else:
            from rde.infrastructure.clinical.measurement_publication import figures
        rendered = figures(result, staging, "unused", preset_id=preset_id, edition=options)
        if len(rendered) != len(record["figures"]):
            raise ValueError(
                "Figure count changed; this source needs a separately reviewed migration."
            )
        lines = [
            "# 投稿圖版",
            "",
            f"樣式：{preset['name']}。來源數值保持固定；本圖版未重新估計任何分析。",
            "",
            f"原數值收據 SHA256：`{result['receipt_sha256']}`",
            "",
            "圖說與圖號供稿件使用，仍須核對目標期刊與最終稿件。",
            "",
        ]
        artifacts = []
        for figure in rendered:
            publication = figure["publication"]
            lines += [
                f"## Figure {publication['figure_number']}",
                "",
                f"![Figure {publication['figure_number']}]({Path(figure['path']).name})",
                "",
                publication["caption_en"],
                "",
                f"中文解釋：{publication['explanation_zh']}",
                "",
            ]
            for key, path in publication["files"].items():
                original = Path(path)
                destination = final / original.relative_to(staging)
                artifacts.append(
                    {
                        "path": str(destination.relative_to(root)),
                        "sha256": file_hash(original),
                        "bytes": original.stat().st_size,
                        "format": key,
                    }
                )
                publication["files"][key] = str(destination)
            figure["path"] = publication["files"]["png"]
        report = staging / "publication-edition.md"
        report.write_text("\n".join(lines), encoding="utf-8")
        artifacts.append(
            {
                "path": str((final / report.name).relative_to(root)),
                "sha256": file_hash(report),
                "bytes": report.stat().st_size,
                "format": "report",
            }
        )
        if (
            file_hash(source) != expected_record_sha256
            or digest({k: v for k, v in result.items() if k != "receipt_sha256"})
            != result["receipt_sha256"]
        ):
            raise ValueError("Source evidence changed during rendering.")
        edition = {
            "schema": "publication-edition-v1",
            "edition_id": edition_id,
            "request": request,
            "source_numerical_receipt_sha256": result["receipt_sha256"],
            "source_dataset_id": record.get("dataset_id"),
            **(
                {"source_plan_id": record["plan_id"], "source_run_id": record["run_id"]}
                if "plan_id" in record
                else {}
            ),
            **(
                {"source_evidence_id": record["source_id"], "source_render_id": record["render_id"]}
                if "source_id" in record
                else {}
            ),
            "numerical_analysis": "unchanged; no fitting or resampling",
            "preset": preset,
            "figures": rendered,
            "artifacts": artifacts,
            "receipt_path": str(receipt_path.relative_to(root)),
        }
        edition["receipt_sha256"] = digest(edition)
        atomic_json(staging / receipt_path.name, edition)
        os.rename(staging, final)
        return edition
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def register_publication_tools(server):
    @server.tool()
    def get_publication_presets() -> str:
        """列出有來源日期、字型可用性、尺寸與格式的期刊出圖樣式。"""
        return json.dumps(
            {
                "presets": list_presets(),
                "supported_studies": [
                    "prediction",
                    "survival",
                    "diagnostic_accuracy",
                    "bland_altman",
                    "cohens_kappa",
                    "longitudinal",
                    "regression",
                    "weighting",
                    "comparison",
                    "repeated",
                    "sample_size",
                    "evidence_synthesis",
                ],
            },
            ensure_ascii=False,
        )

    @server.tool()
    def render_publication_figures(
        project_id: str,
        study_artifact: str,
        expected_record_sha256: str,
        preset_id: str,
        edition_id: str,
        start_number: int = 1,
        captions: dict[str, dict[str, str]] | None = None,
    ) -> str:
        """從指定 SHA256 的已保存研究另建投稿圖版，不重估、不重抽樣、不改原圖。

        study_artifact 是原始 clinical_study_*.json 或 prediction_study_*.json 檔名。
        edition_id 為新 UUID；同 ID 同請求讀回已保存產物，其他內容拒絕覆寫。
        captions 以原圖一開始的序號為 key，可明列 title/caption_en/explanation_zh；保留原圖說。
        本工具僅改顯示版本，不核准新分析或改變原計畫。圖說修訂需研究者審閱。
        """
        from rde.application.session import get_session
        from rde.interface.mcp.tools._shared import ensure_project_context, fmt_error

        ok, message, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(message)
        try:
            result = create_edition(
                project,
                study_artifact=study_artifact,
                expected_record_sha256=expected_record_sha256,
                preset_id=preset_id,
                edition_id=edition_id,
                start_number=start_number,
                captions=captions,
            )
            get_session().get_logger(project.id).log_decision(
                phase=PipelinePhase.REPORT_ASSEMBLY.value,
                action="render_publication_figures",
                tool_used="render_publication_figures",
                parameters={"edition_id": edition_id, **result["request"]},
                rationale="Create or retrieve a display edition from a fixed numerical receipt; no new analysis.",
                result_summary=f"{len(result['figures'])} figures, {preset_id}",
                artifacts=[result["receipt_path"]],
            )
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as error:
            return fmt_error(str(error))
