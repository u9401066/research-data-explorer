"""Prespecified clinical studies via the same locked, auditable RDE pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.clinical.survival import SurvivalSpec, digest, prepare_population
from rde.interface.mcp.tools.prediction_tools import atomic_json


def planned_clinical_spec(entry):
    options = entry.get("execution_arguments", {}).get("clinical_options")
    return SurvivalSpec.parse(options)


def clinical_plan(store):
    entries = (store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}).get(
        "analyses", []
    )
    matching = [e for e in entries if isinstance(e, dict) and e.get("type") == "run_clinical_study"]
    if not matching:
        return None
    if len(entries) != 1 or len(matching) != 1:
        raise ValueError(
            "A clinical study plan requires exactly one complete prespecified study bundle."
        )
    return matching[0]


def clinical_records(store):
    records = []
    for name in sorted(store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)):
        if name.startswith("clinical_study_") and name.endswith(".json"):
            value = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
            if isinstance(value, dict) and value.get("result", {}).get("status") == "completed":
                records.append({**value, "artifact": name})
    return records


def verify_clinical_artifacts(record, root: Path):
    artifacts = record.get("artifacts", [])
    result = record.get("result", {})
    if not artifacts or digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    ) != result.get("receipt_sha256"):
        return False
    for item in artifacts:
        path = (root / item["path"]).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            return False
    return True


def register_clinical_tools(server: Any):
    @server.tool()
    def inspect_clinical_study(dataset_id: str, clinical_options: dict[str, Any]) -> str:
        """計畫審閱前核對生存事件編碼、受試者、共同完整個案與各組人數；不估計模型或 p 值。"""
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error

        ok, message, _project, entry = ensure_phase_ready(
            PipelinePhase.CONCEPT_ALIGNMENT, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        try:
            spec = SurvivalSpec.parse(clinical_options)
            frame, ledger, frame_hash, codes = prepare_population(entry.dataframe, spec)
            source = entry.dataset.metadata
            if not source or not source.file_path.is_file():
                raise ValueError("The clinical source file is required.")
            return json.dumps(
                dict(
                    schema="clinical-preflight-v1",
                    spec_sha256=digest(spec.to_dict()),
                    dataframe_sha256=frame_hash,
                    source_sha256=hashlib.sha256(source.file_path.read_bytes()).hexdigest(),
                    sheet=source.sheet_name,
                    n=len(frame),
                    events=int((frame.event_code == 1).sum()),
                    competing=int((frame.event_code > 1).sum()),
                    censored=int((frame.event_code == 0).sum()),
                    event_codes=codes,
                    input_rows=ledger["input_rows"],
                    outside_cohort=len(ledger["filter_excluded_data_rows"]),
                    missing_required=len(ledger["missing_excluded_data_rows"]),
                    strata=[
                        dict(
                            label=str(label),
                            n=len(group),
                            events=int((group.event_code == 1).sum()),
                        )
                        for label, group in frame.groupby("group", sort=True)
                    ],
                    scope="Eligibility and coding only; no fitted model, p-value or clinical assumption validation.",
                ),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError, KeyError) as error:
            return fmt_error(str(error))

    @server.tool()
    def run_clinical_study(dataset_id: str, clinical_options: dict[str, Any]) -> str:
        """執行鎖定的臨床研究，目前 family=survival（生存／競爭事件）。

        clinical_options 必须逐項符合唯一計畫的 execution_arguments.clinical_options。
        必填 time、event、event_value、censor_value、time_origin、time_unit、independent_rows=true。
        可明列 group、subject、covariates、categorical_covariates、references、competing_values、risk_times、cohort_filter。
        同一完整個案集合提供 KM/競爭事件曲線、在險人數、Cox HR/CI/比例風險檢查、圖表與中文報告。
        不將競爭事件合併成目標事件，不自動挑選變項，不改寫既有成功結果。
        """
        from rde.application.session import get_session
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error, log_tool_error
        from rde.interface.mcp.tools.analysis_tools import _auto_log_decision
        from rde.interface.mcp.tools.report_tools import _upsert_visualization_manifest
        from rde.infrastructure.clinical.survival import run_survival
        from rde.infrastructure.clinical.report import figures, markdown, tables

        ok, message, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        store = ArtifactStore(project.artifacts_dir)
        parameters = {"dataset_id": dataset_id, "clinical_options": clinical_options}
        attempt = None
        try:
            spec = SurvivalSpec.parse(clinical_options)
            plan = clinical_plan(store)
            if plan is None or planned_clinical_spec(plan).to_dict() != spec.to_dict():
                raise ValueError(
                    "Clinical options must exactly match the single locked study plan."
                )
            parameters["variables"] = spec.variables()
            _, _, frame_hash, _ = prepare_population(entry.dataframe, spec)
            metadata = entry.dataset.metadata
            if not metadata or not metadata.file_path.is_file():
                raise ValueError(
                    "The immutable source file is required for the clinical study receipt."
                )
            source = dict(
                path=str(metadata.file_path),
                sha256=hashlib.sha256(metadata.file_path.read_bytes()).hexdigest(),
                sheet=metadata.sheet_name,
            )
            filename = f"clinical_study_{digest(dataset_id)[:16]}.json"
            previous = store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)
            if previous and (
                previous["result"]["spec_sha256"] != digest(spec.to_dict())
                or previous["result"]["dataframe_sha256"] != frame_hash
                or any(previous.get("source", {}).get(k) != source[k] for k in ["sha256", "sheet"])
            ):
                raise ValueError(
                    "Saved clinical evidence has different source/specification. Create an explicit new analysis branch instead of replacing it."
                )
            if previous and digest(
                {k: v for k, v in previous["result"].items() if k != "receipt_sha256"}
            ) != previous["result"].get("receipt_sha256"):
                raise ValueError("Saved clinical numerical evidence failed integrity checks.")
            if previous and previous.get("artifacts"):
                if not verify_clinical_artifacts(previous, project.output_dir):
                    raise ValueError(
                        "Saved clinical artifacts failed integrity checks; refusing to replace evidence."
                    )
                _auto_log_decision(
                    "run_clinical_study",
                    parameters,
                    "Reuse the verified locked clinical study without refitting.",
                    f"Saved complete-case n={previous['result']['n']}.",
                    artifacts=[filename],
                )
                return markdown(previous["result"]) + "\n已取回保存結果；本次沒有重新估計模型。\n"
            run_id = previous["run_id"] if previous else uuid.uuid4().hex[:16]
            attempt = store.get_path(
                PipelinePhase.EXECUTE_EXPLORATION, f"clinical_attempt_{run_id}.json"
            )
            result = previous["result"] if previous else run_survival(entry.dataframe, spec)
            record = dict(
                dataset_id=dataset_id, run_id=run_id, source=source, result=result, artifacts=[]
            )
            # Persist numbers before visualization; a renderer failure never erases the estimate.
            atomic_json(attempt, record)
            final = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
            atomic_json(final, record)
            prefix = f"clinical_{run_id}"
            images = figures(result, project.output_dir / "figures", prefix)
            report = store.save(PipelinePhase.EXECUTE_EXPLORATION, f"{prefix}.md", markdown(result))
            table_dir = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parent
            paths = [report, *tables(result, table_dir, prefix), *[Path(i["path"]) for i in images]]
            record["artifacts"] = [
                dict(
                    path=str(p.relative_to(project.output_dir)),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                )
                for p in paths
            ]
            record["figures"] = images
            for image in images:
                _upsert_visualization_manifest(
                    project,
                    plot_type=image["plot_type"],
                    variables=spec.variables(),
                    result_path=image["path"],
                    group_var=spec.group,
                    stats_summary=image["caption"],
                )
            atomic_json(final, record)
            _auto_log_decision(
                "run_clinical_study",
                parameters,
                "Prespecified right-censored survival study with explicit event types and shared complete cases.",
                f"n={result['n']}; target events={result['events']}; competing events={result['competing']}; no causal promotion.",
                artifacts=[filename, *[a["path"] for a in record["artifacts"]]],
            )
            return markdown(result) + f"\n**數值收據：** `{final}`\n"
        except Exception as error:
            get_session().get_logger(project.id).log_decision(
                phase=PipelinePhase.EXECUTE_EXPLORATION.value,
                action="run_clinical_study_failed",
                tool_used="run_clinical_study",
                parameters={**parameters, "execution_status": "failed"},
                rationale="Keep failure evidence without completing plan coverage.",
                result_summary=str(error),
                artifacts=[attempt.name] if attempt and attempt.is_file() else [],
            )
            log_tool_error("run_clinical_study", error)
            return fmt_error(str(error))
