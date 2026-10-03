"""Main-workflow general analyses: retain source closure and immutable plot inputs."""

import hashlib
import json
from pathlib import Path
import re
import uuid

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.adapters.advanced_evidence import finite_evidence
from rde.infrastructure.adapters.dataframe_lineage import frame_record, verify_source_binding
from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.advanced_publication import figures, publication_result
from rde.interface.mcp.tools.prediction_tools import atomic_json


def _reference(path, root):
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def save_advanced_study(
    project,
    entry,
    *,
    raw_artifact,
    analysis_type,
    source,
    config,
    analysis_result,
    source_binding,
    analysis_frame,
    plausibility_notes,
    plausibility_summary,
):
    """Save numerical evidence before rendering; each invocation owns new paths.

    Phase/plan/readiness gates have already passed in run_advanced_analysis.
    This receipt records placement in the main workflow, not confirmatory status.
    Failed/interrupted render attempts remain on disk alongside their numbers.
    """
    from rde.infrastructure.clinical.advanced_report import markdown
    from rde.interface.mcp.tools.report_tools import _upsert_visualization_manifest

    root = project.output_dir.resolve()
    phase = project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value
    study_id = uuid.uuid4().hex[:16]
    folder = phase / "advanced_studies" / study_id
    folder.mkdir(parents=True, exist_ok=False)
    plan = project.artifacts_dir / PipelinePhase.PLAN_REGISTRATION.value / "analysis_plan.yaml"
    plan_snapshot = folder / "analysis_plan.yaml"
    plan_snapshot.write_bytes(plan.read_bytes())
    # The renderer binds executed roles, including any engine-selected predictors.
    # The exact requested config remains separately preserved in both receipts.
    executed_covariates = (
        []
        if analysis_type == "risk_estimates"
        else analysis_result["covariates"]
        if analysis_type == "propensity_score"
        else analysis_result["source_covariates"]
    )
    evidence = finite_evidence(
        {
            "schema": "advanced-study-evidence-v1",
            "status": "completed",
            "publication_scope": "main_analysis",
            "study_id": study_id,
            "dataset_id": entry.dataset.id,
            "engine": source,
            "source": source_binding["source"],
            "analysis_contract": {
                "tool": "run_advanced_analysis",
                "analysis_type": analysis_type,
                "target_variable": config.get("target"),
                "group_variable": config.get("group_var"),
                "covariates": executed_covariates,
                "confidence_level": config["confidence_level"],
                "missing_strategy": config["missing_strategy"],
            },
            "config": config,
            "analysis_result": finite_evidence(analysis_result),
            "raw_analysis": _reference(raw_artifact, root),
            "plan_snapshot": _reference(plan_snapshot, root),
            "input_evidence": {
                "source_binding": source_binding,
                "analysis_frame": frame_record(analysis_frame),
            },
            "plausibility_notes": plausibility_notes,
            "plausibility_summary": plausibility_summary,
        }
    )
    numerical = folder / "numerical-evidence.json"
    atomic_json(numerical, evidence)
    attempt = folder / "render-attempt.json"
    atomic_json(attempt, {"status": "running", "numerical_evidence": _reference(numerical, root)})
    try:
        result = publication_result(evidence)
        rendered = figures(result, root / "figures" / f"advanced_{study_id}", study_id)
        for figure in rendered:
            figure["path"] = str(Path(figure["path"]).relative_to(root))
        report = markdown(analysis_result, source_binding=source_binding)
        if executed_covariates != config.get("covariates", []):
            report += (
                "\n\n原要求與引擎實際使用的因素不同，兩者均保存在數值紀錄。"
                "上列表格及投稿圖依實際估計模型；二元風險比較不包含調整因素。"
            )
        report += (
            "\n\n本分析記錄於主研究流程；是否屬預先指定的主要分析，須依保存計畫及偏離紀錄判定。"
            "不同分析的完整個案可能不同；未校正跨模型的多重探索。\n\n"
            "## 分析圖、英文圖說與中文解釋\n\n"
            + "\n\n".join(f"![{f['plot_type']}]({f['path']})\n\n{f['caption']}" for f in rendered)
        )
        report_path = folder / "analysis-report.md"
        report_path.write_text(report, encoding="utf8")
        verify_source_binding(source_binding, root)
        paths = [
            numerical,
            plan_snapshot,
            raw_artifact,
            report_path,
            *[Path(p) for f in rendered for p in f["publication"]["files"].values()],
        ]
        record = {
            **evidence,
            "result": result,
            "figures": rendered,
            "artifacts": [_reference(p, root) for p in paths],
        }
        record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
        destination = phase / f"advanced_study_{study_id}.json"
        atomic_json(destination, record)
        atomic_json(attempt, {"status": "completed", "study": _reference(destination, root)})
        for figure in rendered:
            _upsert_visualization_manifest(
                project,
                plot_type=figure["plot_type"],
                variables=config["variables"],
                result_path=str(root / figure["path"]),
                group_var=config.get("group_var"),
                stats_summary=figure["caption"],
                retain_history=True,
            )
        return destination, record, report
    except Exception as error:
        atomic_json(
            attempt,
            {
                "status": "failed",
                "error": str(error),
                "numerical_evidence": _reference(numerical, root),
            },
        )
        raise


def advanced_study_source(project, study_artifact, expected_record_sha256):
    """Verify all saved inputs and figures without loading data or executing models."""
    from rde.interface.mcp.tools._shared.branch_publication import _verify_figures
    from rde.interface.mcp.tools.clinical_tools import verify_clinical_artifacts
    from rde.interface.mcp.tools.publication_tools import file_hash

    if not re.fullmatch(r"advanced_study_[a-f0-9]{16}\.json", study_artifact):
        raise ValueError("Use the exact completed advanced study artifact filename.")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_record_sha256):
        raise ValueError("Expected advanced study SHA256 is required.")
    root = project.output_dir.resolve()

    def confined(value):
        path = (root / value).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Advanced study evidence must be saved inside this project.")
        return path

    path = confined(
        project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value / study_artifact
    )
    if file_hash(path) != expected_record_sha256:
        raise ValueError("Saved advanced study differs from the requested SHA256.")
    record = json.loads(path.read_text(encoding="utf8"))
    result = record.get("result")
    binding = record["input_evidence"]["source_binding"]
    raw = json.loads(confined(record["raw_analysis"]["path"]).read_text(encoding="utf8"))
    if (
        record.get("schema") != "advanced-study-evidence-v1"
        or study_artifact != f"advanced_study_{record.get('study_id')}.json"
        or record.get("dataset_id") not in project.dataset_ids
        or binding.get("dataset_id") != record["dataset_id"]
        or record.get("source") != binding["source"]
        or result != publication_result(record)
        or finite_evidence(raw.get("result")) != record["analysis_result"]
        or raw.get("dataset_id") != record["dataset_id"]
        or raw.get("config") != record["config"]
        or raw.get("source") != record["engine"]
        or not verify_clinical_artifacts(record, root)
    ):
        raise ValueError("Advanced study identity or complete numerical evidence differs.")
    paths = {a["path"] for a in record["artifacts"]}
    for ref in [record["raw_analysis"], record["plan_snapshot"], *record["artifacts"]]:
        saved = confined(ref["path"])
        if ref["path"] not in paths or _reference(saved, root) != ref:
            raise ValueError("Retained analysis, plan, report or figure evidence changed.")
    verify_source_binding(binding, root)
    _verify_figures(record, result, confined)
    return path, record
