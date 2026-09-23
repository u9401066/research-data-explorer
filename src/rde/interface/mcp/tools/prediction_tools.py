"""Phase 8 prediction tool: exact locked specification and durable holdout receipt."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.prediction.contract import PredictionSpec
from rde.infrastructure.prediction.splits import digest, prepare_population


def prediction_plan(store) -> dict | None:
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    entries = plan.get("analyses", [])
    matching = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "run_prediction_study"
    ]
    if not matching:
        return None
    if len(entries) != 1 or len(matching) != 1:
        raise ValueError(
            "A prediction plan must contain exactly one prespecified prediction study; full-data inferential analyses cannot be mixed into it."
        )
    return matching[0]


def planned_spec(entry) -> PredictionSpec:
    options = entry.get("execution_arguments", {}).get("prediction_options") or entry.get(
        "prediction_options"
    )
    return PredictionSpec.parse(options)


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as output:
            os.chmod(temp, 0o600)
            json.dump(value, output, ensure_ascii=False, allow_nan=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def persisted_predictions(store) -> list[dict]:
    records = []
    for name in sorted(store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)):
        if name.startswith("prediction_study_") and name.endswith(".json"):
            value = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
            if isinstance(value, dict) and value.get("result", {}).get("status") == "completed":
                records.append({**value, "artifact": name})
    return records


def verify_prediction_artifacts(record, project_dir: Path) -> bool:
    for artifact in record.get("artifacts", []):
        path = (project_dir / artifact["path"]).resolve()
        if not path.is_relative_to(project_dir.resolve()) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            return False
    result = record.get("result", {})
    return bool(record.get("artifacts")) and digest(
        {key: value for key, value in result.items() if key != "receipt_sha256"}
    ) == result.get("receipt_sha256")


def register_prediction_tools(server: Any) -> None:
    @server.tool()
    def run_prediction_study(dataset_id: str, prediction_options: dict[str, Any]) -> str:
        """依鎖定計畫執行預測模型訓練內 CV 與單一保留集驗證。

        prediction_options 必須與計畫 execution_arguments.prediction_options 完全相符。
        必填 target、predictors、prediction_time_definition、features_available_at_prediction=true。
        task=binary/regression；split=random/group/temporal；候選 linear/random_forest。
        同一資料集已完成的驗證只讀取保存結果，禁止看過保留集後更換設定重測。
        所有補值、縮放與編碼只 fit 訓練 partition；完整列位置、CV、失敗、指標、圖表可稽核。
        """
        from rde.application.session import get_session
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error, log_tool_error
        from rde.interface.mcp.tools.analysis_tools import _auto_log_decision
        from rde.interface.mcp.tools.report_tools import _upsert_visualization_manifest
        from rde.infrastructure.prediction.engine import PredictionFailure, run_prediction
        from rde.infrastructure.prediction.report import figures, markdown
        import pandas as pd

        ok, message, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        store = ArtifactStore(project.artifacts_dir)
        progress_path = None
        parameters = {"dataset_id": dataset_id, "prediction_options": prediction_options}
        try:
            spec = PredictionSpec.parse(prediction_options)
            registered = prediction_plan(store)
            if registered is None or planned_spec(registered).to_dict() != spec.to_dict():
                raise ValueError(
                    "Prediction options must exactly match the single locked prediction plan."
                )
            variables = list(
                dict.fromkeys(
                    [
                        spec.target,
                        *spec.predictors,
                        *[v for v in [spec.subject_variable, spec.time_variable] if v],
                    ]
                )
            )
            parameters.update(
                variables=variables, target_variable=spec.target, predictors=spec.predictors
            )
            population = prepare_population(entry.dataframe, spec)
            filename = f"prediction_study_{digest(dataset_id)[:16]}.json"
            previous = store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)
            if previous:
                if (
                    previous["result"]["spec_sha256"] != digest(spec.to_dict())
                    or previous["result"]["dataframe_sha256"] != population["dataframe_sha256"]
                ):
                    raise ValueError(
                        "This dataset has an inspected holdout. Changed specifications/data cannot be presented as a new unseen validation; use genuinely new validation data."
                    )
                if digest(
                    {
                        key: value
                        for key, value in previous["result"].items()
                        if key != "receipt_sha256"
                    }
                ) != previous["result"].get("receipt_sha256"):
                    raise ValueError("Saved prediction numeric receipt failed its integrity check.")
                if previous.get("artifacts") and not verify_prediction_artifacts(
                    previous, project.output_dir
                ):
                    raise ValueError(
                        "Saved prediction evidence failed integrity checks; refusing to refit against an already inspected holdout."
                    )
                if previous.get("artifacts"):
                    _auto_log_decision(
                        "run_prediction_study",
                        parameters,
                        "Reuse verified prediction receipt without refitting or repeating holdout evaluation.",
                        "Existing internal validation evidence reused.",
                        artifacts=[filename],
                    )
                    return (
                        markdown(previous["result"])
                        + f"\nExisting verified receipt reused: `{filename}`. No model was refitted.\n"
                    )
            run_id = previous["run_id"] if previous else uuid.uuid4().hex[:16]
            progress_path = store.get_path(
                PipelinePhase.EXECUTE_EXPLORATION, f"prediction_attempt_{run_id}.json"
            )
            source = entry.dataset.metadata
            source_record = {
                "path": str(source.file_path) if source else None,
                "sha256": hashlib.sha256(source.file_path.read_bytes()).hexdigest()
                if source and source.file_path.is_file()
                else None,
                "sheet": source.sheet_name if source else None,
            }
            record = previous or {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "source": source_record,
                "artifacts": [],
            }

            def progress(result):
                atomic_json(progress_path, {**record, "result": result})

            result = (
                previous["result"]
                if previous
                else run_prediction(entry.dataframe, spec, progress=progress)
            )
            # Persist completed numeric evidence before rendering, so render failure never erases it.
            record["result"] = result
            atomic_json(progress_path, record)
            final_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
            atomic_json(final_path, record)
            prefix = f"prediction_{run_id}"
            images = figures(result, project.output_dir / "figures", prefix)
            report_path = store.save(
                PipelinePhase.EXECUTE_EXPLORATION, f"{prefix}.md", markdown(result)
            )
            csv_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, f"{prefix}_validation.csv")
            pd.DataFrame(result["validation"]["predictions"]).to_csv(csv_path, index=False)
            paths = [report_path, csv_path, *[Path(image["path"]) for image in images]]
            record["artifacts"] = [
                {
                    "path": str(path.relative_to(project.output_dir)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in paths
            ]
            record["figures"] = images
            for image in images:
                _upsert_visualization_manifest(
                    project,
                    plot_type=image["plot_type"],
                    variables=[spec.target],
                    result_path=image["path"],
                    group_var=None,
                    stats_summary=image["caption"],
                )
            atomic_json(final_path, record)
            _auto_log_decision(
                "run_prediction_study",
                parameters,
                "Locked predictors/split; training-only CV selection; selected model held-out validation.",
                f"Selected {result['selection']['selected']}; held-out n={result['validation']['n']}; internal validation only.",
                artifacts=[filename, *[a["path"] for a in record["artifacts"]]],
            )
            return markdown(result) + f"\n**Receipt:** `{final_path}`\n"
        except Exception as error:
            if isinstance(error, PredictionFailure) and progress_path:
                atomic_json(progress_path, {"dataset_id": dataset_id, "result": error.receipt})
            get_session().get_logger(project.id).log_decision(
                phase=PipelinePhase.EXECUTE_EXPLORATION.value,
                action="run_prediction_study_failed",
                tool_used="run_prediction_study",
                parameters={**parameters, "execution_status": "failed"},
                rationale="Retain failed evidence without completing planned coverage.",
                result_summary=str(error),
                artifacts=[progress_path.name] if progress_path else [],
            )
            log_tool_error("run_prediction_study", error)
            return fmt_error(str(error))
