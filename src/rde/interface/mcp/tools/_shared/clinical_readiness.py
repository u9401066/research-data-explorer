"""Check clinical study evidence without substituting generic EDA method counts."""

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.tools.clinical_tools import (
    clinical_plan,
    clinical_records,
    planned_clinical_spec,
    verify_clinical_artifacts,
)


def required_figures(result):
    if result["spec"]["family"] == "regression":
        from rde.infrastructure.clinical.regression_report import (
            required_figures as regression_figures,
        )

        return regression_figures(result)
    if result["spec"]["family"] == "longitudinal":
        from rde.infrastructure.clinical.longitudinal_report import (
            required_figures as required_longitudinal_figures,
        )

        return required_longitudinal_figures(result)
    if result["spec"]["family"] != "survival":
        from rde.infrastructure.clinical.measurement_report import (
            required_figures as required_measurement_figures,
        )

        return required_measurement_figures(result)
    plots = {"clinical_participant_flow"}
    if result["spec"]["competing_values"]:
        plots.update(f"clinical_incidence_G{i + 1}" for i in range(len(result["strata"])))
    else:
        plots.add("clinical_survival")
    times = len(result["strata"][0]["risk_table"])
    plots.update(f"clinical_risk_table_{i + 1}" for i in range((times + 5) // 6))
    if result.get("cox"):
        count = len(result["cox"]["coefficients"])
        plots.update(f"clinical_cox_{i + 1}" for i in range((count + 7) // 8))
        plots.update("clinical_ph_" + r["term"] for r in result["cox"]["coefficients"])
    return plots


def clinical_readiness(store, *, data_quality, require_report_generation=True):
    spec = planned_clinical_spec(clinical_plan(store)).to_dict()
    records = clinical_records(store)
    checks = []

    def check(key, passed, evidence):
        checks.append(dict(id=key, passed=bool(passed), evidence=evidence))

    check("single_completed_clinical_receipt", len(records) == 1, [r["artifact"] for r in records])
    result = records[0]["result"] if len(records) == 1 else {}
    root = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parents[2]
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    check(
        "locked_clinical_specification",
        plan.get("locked") is True and result.get("spec") == spec,
        ["analysis_plan.yaml"],
    )
    check(
        "clinical_artifact_integrity",
        len(records) == 1 and verify_clinical_artifacts(records[0], root),
        [r["artifact"] for r in records],
    )
    ledger = result.get("case_ledger", {})
    included = ledger.get("complete_data_rows", [])
    excluded = (
        ledger.get("filter_excluded_data_rows", [])
        + ledger.get("missing_excluded_data_rows", [])
        + ledger.get("indeterminate_excluded_data_rows", [])
    )
    check(
        "participant_flow",
        bool(included)
        and len(included) == result.get("n")
        and sorted(included + excluded) == list(range(1, ledger.get("input_rows", 0) + 1)),
        ["case_ledger"],
    )
    if spec["family"] == "survival":
        strata = result.get("strata", [])
        shared_cases = (
            bool(strata)
            and sum(g["n"] for g in strata) == result.get("n")
            and all(g["n"] == g["events"] + g["censored"] + g["competing"] for g in strata)
        )
    elif spec["family"] == "diagnostic_accuracy":
        shared_cases = bool(result.get("confusion_counts")) and sum(
            result["confusion_counts"].values()
        ) == result.get("n")
    elif spec["family"] in {"bland_altman", "regression"}:
        shared_cases = [p["data_row"] for p in result.get("points", [])] == included and bool(
            included
        )
    elif spec["family"] == "longitudinal":
        points = result.get("points", [])
        shared_cases = (
            bool(included)
            and sorted(p["data_row"] for p in points) == included
            and len({p["subject_code"] for p in points})
            == result.get("n_subjects")
            == ledger.get("n_subjects")
        )
    else:
        shared_cases = bool(result.get("table")) and sum(
            sum(row) for row in result["table"]
        ) == result.get("n")
    check("shared_case_set", shared_cases, ["case_ledger", "family-specific counts"])
    cox = result.get("cox")
    if spec["family"] == "survival" and spec.get("covariates"):
        check(
            "cox_estimation_and_assumption_checks",
            cox
            and cox["n"] == result.get("n")
            and len(cox["ph_checks"]) == 2 * len(cox["coefficients"])
            and len(cox["scaled_schoenfeld"]) == result.get("events"),
            ["cox"],
        )
    if spec["family"] == "longitudinal":
        model = result.get("model", {})
        coefficients = result.get("coefficients", [])
        check(
            "longitudinal_model_and_complete_observations",
            model.get("converged") is True
            and model.get("parameters") == len(coefficients) > 1
            and sum(p["observations"] for p in result.get("observed_by_time", []))
            == result.get("n")
            and result.get("multiplicity", {}).get("family")
            == [row["term"] for row in coefficients[1:]],
            ["model", "points", "coefficients", "observed_by_time", "multiplicity"],
        )
    if spec["family"] == "regression":
        model = result.get("model", {})
        coefficients = result.get("coefficients", [])
        check(
            "regression_model_and_complete_cases",
            model.get("converged") is True
            and model.get("mean_parameters") == len(coefficients) > 0
            and bool(result.get("joint_tests"))
            and result.get("multiplicity", {}).get("coefficient_family")
            == [row["term"] for row in coefficients if row["role"] != "intercept"]
            and len(result.get("conditional_curves", []))
            == sum(p["kind"] == "continuous" for p in spec["predictors"]),
            [
                "model",
                "points",
                "coefficients",
                "joint_tests",
                "conditional_curves",
                "multiplicity",
            ],
        )
    expected = required_figures(result) if result else set()
    actual = {f["plot_type"] for f in records[0].get("figures", [])} if len(records) == 1 else set()
    check("clinical_figures", bool(expected) and expected == actual, sorted(expected))
    figures = records[0].get("figures", []) if len(records) == 1 else []
    check(
        "clinical_publication_exports",
        bool(figures)
        and all(
            set(figure.get("publication", {}).get("files", {}))
            == {"png", "pdf", "svg", "tiff", "caption", "data"}
            and figure["publication"].get("source_receipt_sha256") == result.get("receipt_sha256")
            and figure["publication"].get("text_outside_canvas") == []
            and figure["publication"].get("raster_dpi") == 300
            for figure in figures
        ),
        ["native vectors, 300 dpi raster, full bilingual caption and plotted data"],
    )
    check(
        "data_quality_review",
        not data_quality.get("missing_requirements"),
        ["quality_report.json", "readiness_checklist.json"],
    )
    if require_report_generation:
        report = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md") or "")
        from rde.infrastructure.clinical.measurement_report import TITLES

        heading = (
            "生存與事件分析"
            if spec["family"] == "survival"
            else "縱向追蹤與重複觀察"
            if spec["family"] == "longitudinal"
            else "多因素關聯、計數與序位迴歸"
            if spec["family"] == "regression"
            else TITLES[spec["family"]]
        )
        check(
            "report_clinical_sections",
            all(
                part in report
                for part in [
                    heading,
                    "個案納入與排除",
                    "解讀與適用範圍",
                    result.get("receipt_sha256") or "missing receipt",
                ]
            ),
            ["eda_report.md"],
        )
    missing = [c["id"] for c in checks if not c["passed"]]
    return dict(
        ready=not missing,
        scope="clinical_study_report_evidence",
        target_tier="clinical_study",
        current_tier="clinical_study" if not missing else "incomplete_clinical_study",
        review_status="pass" if not missing else "incomplete",
        publication_bundle_met=not missing,
        data_quality=data_quality,
        analysis_depth=dict(ready=not missing, checks=checks, missing_requirements=missing),
        semantic_report_quality=dict(
            ready="report_clinical_sections" not in missing,
            scope="Prespecified methods, case flow, uncertainty and limitations",
            missing_requirements=[m for m in missing if m.startswith("report_")],
        ),
        core_goal_audit=dict(
            scope="clinical_study_report_evidence",
            ready=not missing,
            checks=checks,
            missing_goals=missing,
        ),
        missing_requirements=missing,
        applicability="Evidence completeness only; clinical assumptions and interpretation require researcher review.",
    )


def clinical_deliverables(project, store):
    records = clinical_records(store)
    complete = len(records) == 1 and verify_clinical_artifacts(records[0], project.output_dir)
    figures = records[0].get("figures", []) if len(records) == 1 else []
    needed = (
        required_figures(records[0]["result"])
        if len(records) == 1
        else {"clinical curves and risk table"}
    )
    matched = {f["plot_type"] for f in figures} == needed
    return dict(
        scope="clinical_study",
        minimum_publication_bundle_met=complete and matched,
        total_figures=len(figures),
        analytical_figures=len(figures),
        required_analytical_figures=len(needed),
        required_descriptive_figures=0,
        descriptive_figures=0,
        table_one_required=False,
        figure_files=[f["path"] for f in figures],
        missing_components=[]
        if complete and matched
        else ["clinical numeric receipt, complete figures and data tables"],
    )
