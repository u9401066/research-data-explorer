"""A locked, source-bound descriptive step for incomplete research definitions."""

import hashlib
import json
from pathlib import Path
from typing import Any

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.adapters.descriptive_study import parse_options, summarize, markdown
from rde.infrastructure.adapters.dataframe_lineage import dataset_version
from rde.infrastructure.clinical.survival import digest
from rde.infrastructure.visualization.descriptive import descriptive_figures


def _sealed(record):
    return bool(record) and record.get("receipt_sha256") == digest(
        {k: v for k, v in record.items() if k != "receipt_sha256"}
    )


def _figure_evidence_valid(store, record):
    """Verify every delivered format, caption and plot value against the saved run."""
    try:
        numbers = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_numbers.json")
        if not _sealed(record) or not _sealed(numbers):
            return False
        if record.get("numeric_receipt_sha256") != numbers["receipt_sha256"]:
            return False
        if any(
            record.get(k) != numbers.get(k)
            for k in ("options", "version", "result", "report_sha256", "figure_units")
        ):
            return False
        root = (
            store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
            .parents[2]
            .resolve()
        )
        figures = record.get("figures", [])
        if not figures:
            return False
        columns = record["result"]["columns"]
        numeric = [r for r in columns if r["kind"] == "numeric"]
        expected_panels = [
            (kind, [r["column"] for r in rows[start : start + size]])
            for kind, rows, size in [
                ("descriptive_availability", columns, 16),
                ("descriptive_quantiles", numeric, 4),
            ]
            for start in range(0, len(rows), size)
        ]
        if [
            (image.get("plot_type"), image.get("variables")) for image in figures
        ] != expected_panels:
            return False
        expected = set()
        for image in figures:
            publication = image["publication"]
            if publication["source_receipt_sha256"] != numbers["receipt_sha256"]:
                return False
            if set(publication["files"]) != {"png", "pdf", "svg", "tiff", "caption", "data"}:
                return False
            if publication["files"]["png"] != image["path"]:
                return False
            for value in publication["files"].values():
                path = Path(value).resolve()
                if not path.is_relative_to(root / "figures"):
                    return False
                expected.add(path.relative_to(root).as_posix())
        artifacts = record.get("artifacts", [])
        if len(artifacts) != len(expected) or {a["path"] for a in artifacts} != expected:
            return False
        for item in artifacts:
            path = (root / item["path"]).resolve()
            if (
                not path.is_relative_to(root / "figures")
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                return False
        manifest = (
            store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
        )
        for image in figures:
            path = Path(image["path"]).resolve().relative_to(root).as_posix()
            expected_sha = next(a["sha256"] for a in artifacts if a["path"] == path)
            if not any(
                m.get("output_path") == path
                and m.get("sha256") == expected_sha
                and m.get("stats_summary") == image["caption"]
                for m in manifest
            ):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return False


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
    check("descriptive_figures", _figure_evidence_valid(store, record))
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
        固定產出逐欄有值/缺失圖及非識別數值欄的五數摘要圖，綁定數值收據；
        英文圖說、中文解釋、PNG/PDF/SVG/TIFF與plot-data，不做推論或另擬合模型。
        """
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error
        from rde.interface.mcp.tools.analysis_tools import _auto_log_decision
        from rde.interface.mcp.tools.report_tools import _upsert_visualization_manifest

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
            numeric_name = "descriptive_numbers.json"
            numbers = store.load(PipelinePhase.EXECUTE_EXPLORATION, numeric_name)
            report_name = "descriptive_report.md"
            report = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, report_name)
            units = {}
            intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json") or {}
            if intake.get("preparation") is not None:
                from rde.infrastructure.preparation.reporting import preparation_evidence

                evidence = preparation_evidence(project, intake)
                units = {
                    f["output"]: f["output_unit"]
                    for r in evidence["plan"]["specification"]["relations"]
                    for f in r["features"]
                    if f.get("output_unit")
                }
            if numbers and (
                not _sealed(numbers)
                or numbers.get("version") != version
                or numbers.get("options") != spec
                or numbers.get("figure_units") != units
                or not report.is_file()
                or hashlib.sha256(report.read_bytes()).hexdigest() != numbers.get("report_sha256")
            ):
                raise ValueError("Saved descriptive numbers changed; create a new plan")
            if previous:
                if (
                    previous.get("version") != version
                    or previous.get("options") != spec
                    or previous.get("receipt_sha256")
                    != digest({k: v for k, v in previous.items() if k != "receipt_sha256"})
                    or not report.is_file()
                    or hashlib.sha256(report.read_bytes()).hexdigest()
                    != previous.get("report_sha256")
                    or not _figure_evidence_valid(store, previous)
                ):
                    raise ValueError("Saved descriptive evidence changed; create a new plan")
                result = previous["result"]
            else:
                if not numbers:
                    result = summarize(entry.dataframe, spec)
                    report = store.save(
                        PipelinePhase.EXECUTE_EXPLORATION, report_name, markdown(result)
                    )
                    basis = dict(
                        options=spec,
                        version=version,
                        result=result,
                        figure_units=units,
                        report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                    )
                    numbers = {**basis, "receipt_sha256": digest(basis)}
                    # A renderer failure retains exact numbers for a safe retry.
                    store.save(PipelinePhase.EXECUTE_EXPLORATION, numeric_name, numbers)
                result = numbers["result"]
                directory = project.output_dir / "figures"
                if not directory.resolve().is_relative_to(project.output_dir.resolve()):
                    raise ValueError("Descriptive figure directory escapes the project")
                images = descriptive_figures(result, directory, numbers["receipt_sha256"], units)
                paths = [
                    Path(p) for image in images for p in image["publication"]["files"].values()
                ]
                for image in images:
                    _upsert_visualization_manifest(
                        project,
                        plot_type=image["plot_type"],
                        variables=image["variables"],
                        result_path=image["path"],
                        group_var=None,
                        stats_summary=image["caption"],
                    )
                record = {
                    **{k: v for k, v in numbers.items() if k != "receipt_sha256"},
                    "numeric_receipt_sha256": numbers["receipt_sha256"],
                    "figures": images,
                    "artifacts": [
                        dict(
                            path=p.relative_to(project.output_dir).as_posix(),
                            sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                        )
                        for p in paths
                    ],
                }
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
                artifacts=[name, numeric_name, report_name, "visualization_manifest.json"],
            )
            return json.dumps(
                {
                    "status": "completed",
                    "reused": bool(previous),
                    "result": result,
                    "figures": (previous or record)["figures"],
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError, KeyError) as error:
            return fmt_error(str(error))
