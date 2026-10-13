"""A locked, source-bound descriptive step for incomplete research definitions."""

import hashlib
import json
from typing import Any

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.adapters.descriptive_study import parse_options, summarize, markdown
from rde.infrastructure.adapters.dataframe_lineage import dataset_version
from rde.infrastructure.clinical.survival import digest


def planned_descriptive(analyses):
    matching = [x for x in analyses if x.get("type") == "run_descriptive_study"]
    if not matching:
        return None
    if len(analyses) != 1:
        raise ValueError("Descriptive scope cannot include inferential steps")
    spec = parse_options(matching[0].get("execution_arguments", {}).get("descriptive_options"))
    if matching[0].get("variables") != spec["columns"]:
        raise ValueError("Descriptive variables must match the exact selected columns")
    return spec


def descriptive_summary(store):
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
    if not record:
        return []
    return [
        dict(
            receipt_sha256=record["receipt_sha256"],
            result=record["result"],
            summary_markdown=markdown(record["result"])
            + "\nReceipt SHA256: "
            + record["receipt_sha256"],
        )
    ]


def descriptive_readiness(store, require_report_generation):
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    spec = planned_descriptive(plan.get("analyses", []))
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json") or {}
    report = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_report.md")
    checks = []

    def check(name, passed):
        checks.append(dict(id=name, required=True, passed=bool(passed), evidence=[name]))

    check("descriptive_lock", plan.get("locked") and spec and record.get("options") == spec)
    check(
        "descriptive_receipt",
        record
        and record.get("receipt_sha256")
        == digest({k: v for k, v in record.items() if k != "receipt_sha256"}),
    )
    check("descriptive_source", record.get("version", {}).get("source_status") == "verified")
    check(
        "descriptive_report",
        report.is_file()
        and hashlib.sha256(report.read_bytes()).hexdigest() == record.get("report_sha256"),
    )
    check("descriptive_scope", record.get("result", {}).get("inference_performed") is False)
    for phase, name in [
        (PipelinePhase.DATA_INTAKE, "intake_report.json"),
        (PipelinePhase.SCHEMA_REGISTRY, "schema.json"),
        (PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json"),
        (PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json"),
        (PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl"),
        (PipelinePhase.COLLECT_RESULTS, "results_summary.json"),
    ]:
        check(name, store.exists(phase, name))
    if require_report_generation:
        assembled = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md") or "")
        check(
            "assembled_descriptive_report",
            record.get("receipt_sha256", "missing") in assembled
            and "描述性資料研究報告" in assembled,
        )
    missing = [x["id"] for x in checks if not x["passed"]]
    return dict(
        ready=not missing,
        scope="descriptive_evidence_only",
        target_tier="descriptive_only",
        current_tier="descriptive_only",
        review_status="pass" if not missing else "incomplete",
        publication_bundle_met=False,
        missing_requirements=missing,
        analysis_depth=dict(ready=not missing, checks=checks, missing_requirements=missing),
        semantic_report_quality=dict(ready=not missing, missing_requirements=missing),
        core_goal_audit=dict(
            ready=not missing, scope="descriptive_only", checks=checks, missing_goals=missing
        ),
        applicability="Completed observed-row description only; no inferential or publication readiness claim.",
    )


def register_descriptive_tools(server: Any):
    @server.tool()
    def run_descriptive_study(dataset_id: str, descriptive_options: dict[str, Any]) -> str:
        """描述已鎖定資料列，不要求獨立性或已知抽樣設計。不刪列、補值、估計 p/CI 或選主終點。

        descriptive_options={columns:[1..80欄],identifiers:[0..8候選識別欄],unresolved:[待定義事實]}。
        計畫恰有此一操作並固定所有設定；逐欄保留分母、缺失、識別碼重複與分布。
        """
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error
        from rde.interface.mcp.tools.analysis_tools import _auto_log_decision

        ok, message, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        try:
            store = ArtifactStore(project.artifacts_dir)
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
            spec = parse_options(descriptive_options)
            if not plan.get("locked") or planned_descriptive(plan.get("analyses", [])) != spec:
                raise ValueError("Descriptive options must exactly match the locked plan")
            version = dataset_version(project, entry)
            if version["source_status"] != "verified":
                raise ValueError("Verified source and preparation lineage required")
            name = "descriptive_study.json"
            previous = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
            report_name = "descriptive_report.md"
            if previous:
                report = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, report_name)
                if (
                    previous.get("version") != version
                    or previous.get("options") != spec
                    or previous.get("receipt_sha256")
                    != digest({k: v for k, v in previous.items() if k != "receipt_sha256"})
                    or not report.is_file()
                    or hashlib.sha256(report.read_bytes()).hexdigest()
                    != previous.get("report_sha256")
                ):
                    raise ValueError("Saved descriptive evidence changed; create a new plan")
                result = previous["result"]
            else:
                result = summarize(entry.dataframe, spec)
                report = store.save(
                    PipelinePhase.EXECUTE_EXPLORATION, report_name, markdown(result)
                )
                record = dict(
                    options=spec,
                    version=version,
                    result=result,
                    report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                )
                store.save(
                    PipelinePhase.EXECUTE_EXPLORATION,
                    name,
                    {**record, "receipt_sha256": digest(record)},
                )
            _auto_log_decision(
                "run_descriptive_study",
                {
                    "dataset_id": dataset_id,
                    "variables": spec["columns"],
                    "descriptive_options": spec,
                },
                "Describe observed rows; unresolved facts do not authorize inference",
                f"{result['input_rows']} rows; no inference",
                artifacts=[name, report_name],
            )
            return json.dumps(
                {"status": "completed", "reused": bool(previous), "result": result},
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError, KeyError) as error:
            return fmt_error(str(error))
