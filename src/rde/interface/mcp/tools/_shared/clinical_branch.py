"""Bounded Cox branches with immutable primary evidence and a fixed participant set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.clinical.survival import digest, prepare_population
from rde.interface.mcp.tools.prediction_tools import atomic_json


def execute_survival_branch(project, store, contract, branch_id, experiment_id):
    from rde.interface.mcp.tools._shared import ensure_dataset
    from rde.interface.mcp.tools.clinical_tools import (
        clinical_plan,
        planned_clinical_spec,
        verify_clinical_artifacts,
    )
    from rde.infrastructure.clinical.survival import run_survival_sensitivity
    from rde.infrastructure.clinical.report import figures, markdown, tables

    folder = store.get_path(
        PipelinePhase.EXECUTE_EXPLORATION, f"branch_results/{branch_id}/experiments"
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{experiment_id}_survival_sensitivity.json"
    report_path = path.with_suffix(".md")
    record = dict(
        branch_id=branch_id,
        experiment_id=experiment_id,
        analysis_contract=contract,
        source="local-clinical-survival",
        status="failed",
        artifacts=[],
    )
    metrics = dict(
        runner_generated=False,
        contract_executed=False,
        execution_status="failed",
        analysis_type="survival_sensitivity",
        inference_scope="exploratory; pointwise uncertainty; no correction across models",
    )
    executed = False
    try:
        allowed = {
            "tool",
            "analysis_type",
            "covariates",
            "focus_variable",
            "required_covariates",
            "primary_receipt_sha256",
            "primary_record_sha256",
            "case_set_sha256",
        }
        if set(contract) != allowed or contract["analysis_type"] != "survival_sensitivity":
            raise ValueError("The survival branch requires the exact bounded sensitivity contract.")
        locked = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
        if locked.get("locked") is not True:
            raise ValueError("A locked primary clinical study is required.")
        plan = clinical_plan(store)
        if not plan:
            raise ValueError("A single primary clinical study is required.")
        spec = planned_clinical_spec(plan)
        covariates = contract["covariates"]
        required = contract["required_covariates"]
        focus = contract["focus_variable"]
        for values in [covariates, required]:
            if (
                not isinstance(values, list)
                or not all(isinstance(v, str) for v in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("Covariates and required factors must be unique variable names.")
        if (
            not isinstance(focus, str)
            or focus not in required
            or not set(required) <= set(covariates)
            or not set(covariates) < set(spec.covariates)
            or covariates != [v for v in spec.covariates if v in covariates]
        ):
            raise ValueError(
                "Retain the focus and all required factors in a proper primary subset."
            )
        ok, message, entry = ensure_dataset(None, project=project)
        if not ok or entry is None:
            raise ValueError(f"The primary dataset is unavailable: {message}")
        primary_path = store.get_path(
            PipelinePhase.EXECUTE_EXPLORATION,
            f"clinical_study_{digest(entry.dataset.id)[:16]}.json",
        )
        primary_bytes = primary_path.read_bytes()
        if hashlib.sha256(primary_bytes).hexdigest() != contract["primary_record_sha256"]:
            raise ValueError("The primary clinical record changed or failed integrity checks.")
        primary = json.loads(primary_bytes)
        primary_result = primary["result"]
        if (
            primary.get("dataset_id") != entry.dataset.id
            or primary_result.get("status") != "completed"
            or primary_result.get("spec") != spec.to_dict()
            or primary_result.get("spec_sha256") != digest(spec.to_dict())
            or primary_result.get("receipt_sha256") != contract["primary_receipt_sha256"]
            or not primary_result.get("cox")
            or not verify_clinical_artifacts(primary, project.output_dir)
        ):
            raise ValueError(
                "The verified primary Cox receipt and complete artifacts are required."
            )
        metadata = entry.dataset.metadata
        if (
            not metadata
            or not metadata.file_path.is_file()
            or hashlib.sha256(metadata.file_path.read_bytes()).hexdigest()
            != primary["source"]["sha256"]
            or metadata.sheet_name != primary["source"].get("sheet")
        ):
            raise ValueError("The primary source file or worksheet changed.")
        _, ledger, frame_hash, _ = prepare_population(entry.dataframe, spec)
        if (
            frame_hash != primary_result["dataframe_sha256"]
            or ledger != primary_result["case_ledger"]
            or digest(ledger["complete_data_rows"]) != contract["case_set_sha256"]
        ):
            raise ValueError("The primary complete-case population changed.")
        binding = {key: contract[key] for key in allowed if key.endswith("sha256")}
        binding.update(
            focus_variable=focus,
            required_covariates=required,
            primary_artifact=str(primary_path.relative_to(project.output_dir)),
        )
        record.update(
            primary_binding=binding, dataset_id=entry.dataset.id, source_file=primary["source"]
        )
        executed = True
        result = run_survival_sensitivity(entry.dataframe, spec, covariates)
        result["primary_binding"] = binding
        result["receipt_sha256"] = digest(
            {k: v for k, v in result.items() if k != "receipt_sha256"}
        )
        record["analysis_result"] = result
        record["status"] = "rendering"
        # Retain the numerical receipt even if a plot renderer fails later.
        atomic_json(path, record)
        baseline_focus = [
            c for c in primary_result["cox"]["coefficients"] if c["variable"] == focus
        ]
        branch_focus = [c for c in result["cox"]["coefficients"] if c["variable"] == focus]
        metrics.update(
            contract_executed=True,
            n=result["n"],
            events=result["events"],
            censored=result["censored"],
            competing=result["competing"],
            case_set_sha256=result["case_set_sha256"],
            focus_variable=focus,
            primary_focus=baseline_focus,
            branch_focus=branch_focus,
        )
        images = figures(result, folder / experiment_id / "figures", experiment_id)
        comparison = [
            "# 生存研究：調整因素敏感度分支",
            "",
            f"主要關注因素：{focus}。各分支必須保留：{'、'.join(required)}。",
            f"本次調整因素：{'、'.join(covariates)}。",
            f"主要分析與本分支使用相同 {result['n']} 人、{result['events']} 個目標事件；未恢復任何被排除個案。",
            "",
            "| 因素／比較 | 主要分析 HR（信賴區間） | 分支 HR（信賴區間） |",
            "| --- | --- | --- |",
        ]
        for first, second in zip(baseline_focus, branch_focus, strict=True):
            label = first["variable"]
            if "level" in first:
                label += f"：{first['level']} vs {first['reference']}"

            def bounds(c):
                return f"{c['hazard_ratio']:.4g}（{c['lower']:.4g}–{c['upper']:.4g}）"

            comparison.append(
                f"| {label.replace('|', '／')} | {bounds(first)} | {bounds(second)} |"
            )
        comparison.extend(
            [
                "",
                "這是探索性調整模型比較，並未檢定兩個 HR 的差異；不依 p 值挑選最佳模型或取代主要分析。",
                "模型間尚未校正多重探索；比例風險診斷的 Holm 校正僅適用於單一模型內。",
                "",
                markdown(result),
                "",
                "## 本分支圖形",
                "",
            ]
        )
        for image in images:
            relative = str(Path(image["path"]).relative_to(project.output_dir))
            comparison.append(f"![{image['caption']}]({relative})")
        report_path.write_text("\n".join(comparison), encoding="utf-8")
        paths = [
            report_path,
            *tables(result, folder / experiment_id, experiment_id),
            *[Path(i["path"]) for i in images],
        ]
        record["artifacts"] = [
            {
                "path": str(p.relative_to(project.output_dir)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in paths
        ]
        record["figures"] = [
            {**i, "path": str(Path(i["path"]).relative_to(project.output_dir))} for i in images
        ]
        record["status"] = "completed"
        metrics["execution_status"] = "completed"
        summary = f"探索性 {result['cox']['method']}：固定 {result['n']} 人、{result['events']} 個目標事件；關注 {focus}。"
        error = None
    except Exception as exc:
        error = str(exc)
        summary = f"Survival sensitivity branch failed: {error}"
        record.update(status="failed", error=error)
    record["metrics"] = metrics
    atomic_json(path, record)
    references = [
        str(path.relative_to(project.output_dir)),
        *[a["path"] for a in record["artifacts"]],
    ]
    return dict(
        executed=executed,
        status=record["status"],
        artifacts=references,
        metrics=metrics,
        result_summary=summary,
        error=error,
        artifact_path=str(path),
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        markdown_path=str(report_path) if report_path.exists() else None,
    )
