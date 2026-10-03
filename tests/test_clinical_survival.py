"""Numerical and case-set checks for the reusable clinical survival executor."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.duration.survfunc import CumIncidenceRight, survdiff

from rde.infrastructure.clinical.survival import SurvivalSpec, prepare_population, run_survival


def spec(**changes):
    return SurvivalSpec.parse(
        dict(
            time="time",
            event="status",
            event_value="D",
            censor_value="C",
            time_origin="Date of cohort entry",
            time_unit="days",
            independent_rows=True,
            **changes,
        )
    )


def test_km_tied_censoring_has_manual_greenwood_intervals_and_pre_event_risk_sets():
    frame = pd.DataFrame({"time": [1, 1, 2, 3, 4], "status": ["D", "C", "D", "C", "D"]})
    original = frame.copy(deep=True)
    result = run_survival(frame, spec(risk_times=[0, 1, 2, 4]))
    estimate = result["strata"][0]["estimate"]
    assert [p["estimate"] for p in estimate["curve"]] == pytest.approx([1, 0.8, 8 / 15, 8 / 15, 0])
    point = next(p for p in estimate["curve"] if p["time"] == 2)
    survival = 8 / 15
    greenwood = 1 / (5 * 4) + 1 / (3 * 2)
    se = math.sqrt(greenwood) / abs(math.log(survival))
    z = norm.ppf(0.975)
    assert point["lower"] == pytest.approx(
        math.exp(-math.exp(math.log(-math.log(survival)) + z * se))
    )
    assert point["upper"] == pytest.approx(
        math.exp(-math.exp(math.log(-math.log(survival)) - z * se))
    )
    assert [p["at_risk"] for p in result["strata"][0]["risk_table"]] == [5, 5, 3, 1]
    assert estimate["median"] == 4
    pd.testing.assert_frame_equal(frame, original)


def test_aj_preserves_tied_event_times_and_terminal_multinomial_uncertainty():
    frame = pd.DataFrame({"time": [1, 1, 1, 1], "status": ["D", "D", "T", "T"]})
    result = run_survival(frame, spec(competing_values=["T"]))
    estimate = result["strata"][0]["estimate"]
    for cause in ["D", "T"]:
        last = estimate["curves"][cause][-1]
        assert last["time"] == 1
        assert last["estimate"] == pytest.approx(0.5)
        assert last["standard_error"] == pytest.approx(math.sqrt(0.5 * 0.5 / 4))
    assert result["logrank"] is None


def test_aj_with_censoring_matches_independent_package_and_keeps_absent_causes():
    frame = pd.DataFrame({"time": [1, 1, 2, 3, 4, 5], "status": ["D", "T", "C", "D", "T", "C"]})
    result = run_survival(frame, spec(competing_values=["T", "X"]))
    reference = CumIncidenceRight(frame.time.to_numpy(), np.array([1, 2, 0, 1, 2, 0]))
    curves = result["strata"][0]["estimate"]["curves"]
    for i, cause in enumerate(["D", "T"]):
        assert [p["estimate"] for p in curves[cause]] == pytest.approx(reference.cinc[i])
        assert [p["standard_error"] for p in curves[cause]] == pytest.approx(reference.cinc_se[i])
    assert [p["estimate"] for p in curves["X"]] == [0] * len(reference.times)
    assert curves["D"][-1]["estimate"] == pytest.approx(7 / 18)


def test_no_observed_events_is_not_a_fabricated_median_or_significance(tmp_path):
    frame = pd.DataFrame({"time": [1, 2, 3, 4], "status": ["C"] * 4, "group": ["A", "A", "B", "B"]})
    result = run_survival(frame, spec(group="group"))
    assert result["logrank"]["status"] == "not_estimable"
    assert all(s["estimate"]["median"] is None for s in result["strata"])
    competing = run_survival(frame, spec(group="group", competing_values=["T"]))
    assert all(s["estimate"]["no_observed_events"] for s in competing["strata"])
    from rde.infrastructure.clinical.report import tables

    paths = tables(competing, tmp_path, "empty")
    curve = pd.read_csv(next(p for p in paths if p.name.endswith("_incidence.csv")))
    assert curve.empty
    assert {"event", "time", "estimate", "lower", "upper"}.issubset(curve.columns)


def test_common_complete_cases_and_explicit_cohort_filter_retain_source_row_numbers():
    frame = pd.DataFrame(
        {
            "time": [1, 2, 3, 4, None, 6],
            "status": ["D", "C", "D", "D", "C", "D"],
            "x": [2, None, 1, 4, 3, 6],
            "cohort": ["trial", "trial", "trial", "other", "trial", "trial"],
        }
    )
    prepared, ledger, _, _ = prepare_population(
        frame, spec(covariates=["x"], cohort_filter={"column": "cohort", "values": ["trial"]})
    )
    assert ledger["complete_data_rows"] == [1, 3, 6]
    assert ledger["missing_excluded_data_rows"] == [2, 5]
    assert ledger["filter_excluded_data_rows"] == [4]
    assert len(prepared) == 3
    assert ledger["input_rows"] == 6 and ledger["cohort_rows"] == 5


def cox_frame():
    rng = np.random.default_rng(862)
    x = rng.normal(size=300)
    group = rng.integers(0, 2, size=300)
    event = np.maximum(1, np.ceil(rng.exponential(scale=15 * np.exp(-0.4 * x + 0.3 * group))))
    censor = rng.uniform(5, 35, size=300).round()
    return pd.DataFrame(
        {
            "time": np.minimum(event, censor),
            "status": np.where(event <= censor, "D", "C"),
            "x": x,
            "group": np.where(group, "treated", "control"),
        }
    )


def test_cox_ci_and_tie_estimates_match_phreg_with_prespecified_reference():
    frame = cox_frame()
    result = run_survival(
        frame,
        spec(
            group="group",
            covariates=["x", "group"],
            categorical_covariates=["group"],
            references={"group": "control"},
        ),
    )
    fitted = PHReg(
        frame.time,
        np.column_stack([frame.x, frame.group == "treated"]),
        status=frame.status == "D",
        ties="efron",
    ).fit()
    coefficients = result["cox"]["coefficients"]
    assert [c["coefficient"] for c in coefficients] == pytest.approx(fitted.params, abs=2e-5)
    assert [c["standard_error"] for c in coefficients] == pytest.approx(fitted.bse, abs=2e-5)
    assert [c["lower"] for c in coefficients] == pytest.approx(
        np.exp(fitted.conf_int()[:, 0]), abs=2e-5
    )
    assert [c["upper"] for c in coefficients] == pytest.approx(
        np.exp(fitted.conf_int()[:, 1]), abs=2e-5
    )
    assert coefficients[1]["reference"] == "control"
    assert len(result["cox"]["ph_checks"]) == 4
    assert all(c["p_adjusted"] >= c["p_value"] for c in result["cox"]["ph_checks"])
    assert len(result["cox"]["scaled_schoenfeld"]) == result["events"]
    statistic, p_value = survdiff(frame.time, frame.status == "D", frame.group)
    assert result["logrank"]["statistic"] == pytest.approx(statistic)
    assert result["logrank"]["p_value"] == pytest.approx(p_value)


@pytest.mark.parametrize(
    "change",
    [
        {"independent_rows": False},
        {"event_value": "C"},
        {"competing_values": ["D"]},
        {"risk_times": [2, 1]},
        {"risk_times": [True]},
        {"confidence_level": float("nan")},
        {"covariates": ["time"]},
        {"subject": "status"},
        {"unknown": 1},
        {"categorical_covariates": ["x"]},
        {"cohort_filter": {"column": "x", "values": []}},
    ],
)
def test_invalid_survival_specification_is_rejected(change):
    defaults = dict(
        time="time",
        event="status",
        event_value="D",
        censor_value="C",
        time_origin="Entry into the cohort",
        time_unit="days",
        independent_rows=True,
    )
    with pytest.raises(ValueError):
        SurvivalSpec.parse({**defaults, **change})


@pytest.mark.parametrize(
    "column,value,pattern",
    [
        ("time", -1, "nonnegative"),
        ("time", "bad", "non-numeric"),
        ("status", "T", "Unmapped event"),
    ],
)
def test_invalid_observations_cannot_be_silently_dropped(column, value, pattern):
    frame = pd.DataFrame({"time": [1, 2, 3], "status": ["D", "C", "D"]}, dtype=object)
    frame.loc[1, column] = value
    with pytest.raises(ValueError, match=pattern):
        run_survival(frame, spec())


def test_repeated_subject_and_nonestimable_models_are_explicit_failures():
    frame = cox_frame()
    frame["id"] = "same-person"
    with pytest.raises(ValueError, match="unique"):
        run_survival(frame, spec(subject="id"))
    frame["duplicate"] = frame.x
    with pytest.raises(ValueError, match="collinear"):
        run_survival(frame, spec(covariates=["x", "duplicate"]))
    frame["status"] = "C"
    frame.loc[:2, "status"] = "D"
    with pytest.raises(ValueError, match="at least five"):
        run_survival(frame, spec(covariates=["x"]))


def clinical_project(tmp_path, *, competing=False, frame=None, options=None):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.pipeline import PipelinePhase
    from rde.application.session import get_session
    from rde.domain.models.dataset import Dataset, DatasetMetadata

    project, store = _make_phase8_ready_project(tmp_path)
    frame = cox_frame() if frame is None else frame
    if competing:
        frame.loc[frame.index % 7 == 0, "status"] = "T"
    options = options or spec(
        group="group",
        covariates=["x", "group"],
        categorical_covariates=["group"],
        references={"group": "control"},
        competing_values=["T"] if competing else [],
    )
    source = tmp_path / "clinical-fixture.csv"
    frame.to_csv(source, index=False)
    dataset = Dataset(
        row_count=len(frame), metadata=DatasetMetadata(source, "csv", source.stat().st_size)
    )
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                {
                    "type": "run_clinical_study",
                    "variables": options.variables(),
                    "execution_arguments": {"clinical_options": options.to_dict()},
                }
            ],
        },
    )
    store.save(PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json", {"engine": "fixture"})
    store.save(
        PipelinePhase.SCHEMA_REGISTRY,
        "quality_report.json",
        {"is_analysis_ready": True, "issues": [], "critical_issue_count": 0},
    )
    return project, store, dataset, options


@pytest.mark.parametrize("competing", [False, True])
def test_mcp_report_keeps_all_panels_for_no_events_and_many_risk_times(
    tmp_path, monkeypatch, competing
):
    import asyncio
    import csv
    import hashlib
    import os
    import uuid
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools.clinical_tools import clinical_records

    frame = pd.DataFrame(
        {
            "time": [1, 2, 3, 4] * 6,
            "status": ["C"] * 24,
            "group": [f"治療組別{i}" for i in range(6) for _ in range(4)],
        }
    )
    times = [0, 0.5, 1, 1.00000001, 1.00000002, 1.5, 2, 2.5, 3, 3.5, 3.9, 4]
    options = spec(group="group", risk_times=times, competing_values=["T"] if competing else [])
    project, store, dataset, _ = clinical_project(tmp_path, frame=frame, options=options)

    def call(name, args):
        response = asyncio.run(create_server().call_tool(name, args))
        assert not response.is_error, response.content
        return response

    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": options.to_dict()})
    record = clinical_records(store)[0]
    assert len(record["figures"]) == (9 if competing else 4)
    risk_rows = []
    for figure in record["figures"]:
        with Path(figure["publication"]["files"]["data"]).open() as stream:
            rows = list(csv.DictReader(stream))
        if figure["plot_type"].startswith("clinical_risk_table"):
            risk_rows.extend(rows)
        if figure["plot_type"].startswith("clinical_incidence"):
            assert all(r["plot_role"] == "not_estimated_no_events" for r in rows)
            assert not any(r.get("estimate") or r.get("lower") or r.get("upper") for r in rows)
    assert len(risk_rows) == 72
    for group in frame.group.unique():
        assert [float(r["time"]) for r in risk_rows if r["source_group"] == group] == times
    call("collect_results", {"project_id": project.id})
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert all(Path(f["path"]).name in report for f in record["figures"])
    if os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"):
        monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
        source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
        call(
            "render_publication_figures",
            {
                "project_id": project.id,
                "study_artifact": source.name,
                "expected_record_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "preset_id": "nature-single-v1",
                "edition_id": str(uuid.uuid4()),
            },
        )


@pytest.mark.parametrize("competing", [False, True])
def test_real_mcp_clinical_receipt_report_integrity_and_no_refit(tmp_path, monkeypatch, competing):
    import asyncio
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.clinical import survival
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
    from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness

    project, store, dataset, options = clinical_project(tmp_path, competing=competing)

    async def call(name, args):
        return await create_server().call_tool(name, args)

    args = {"dataset_id": dataset.id, "clinical_options": options.to_dict()}
    inspected = asyncio.run(call("inspect_clinical_study", args))
    assert not inspected.is_error, inspected.content
    import json

    counts = json.loads(inspected.content[0].text)
    assert counts["n"] == counts["input_rows"] == 300
    assert counts["events"] + counts["censored"] + counts["competing"] == counts["n"]
    assert not clinical_records(store)
    response = asyncio.run(call("run_clinical_study", args))
    assert not response.is_error, response.content
    record = clinical_records(store)[0]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert len(record["figures"]) == (7 if competing else 6)
    monkeypatch.setattr(
        survival,
        "run_survival",
        lambda *a, **kw: pytest.fail("Saved clinical evidence was refitted"),
    )
    repeated = asyncio.run(call("run_clinical_study", args))
    assert not repeated.is_error and "沒有重新估計" in repeated.content[0].text
    collected = asyncio.run(call("collect_results", {"project_id": project.id}))
    assert not collected.is_error, collected.content
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert summary["clinical_studies"][0]["receipt_sha256"] == record["result"]["receipt_sha256"]
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    assembled = asyncio.run(call("assemble_report", {"project_id": project.id}))
    assert not assembled.is_error, assembled.content
    report = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"))
    assert "生存與事件分析" in report and "在險人數" in report
    risk_set = "當時仍在追蹤且尚未發生" + ("目標或任何競爭事件" if competing else "目標事件")
    assert risk_set + "者的瞬時目標事件率" in report
    assert "每個 HR 都在其他已納入因素相同的條件下解讀" in report
    assert "類別因素的參考組不是其他連續因素 HR 的比較對象" in report
    if competing:
        assert "Aalen–Johansen" in report and "cause-specific HR" in report
    else:
        assert "目標或任何競爭事件者" not in report
    assert len({f["plot_type"] for f in record["figures"]}) == len(record["figures"])
    for figure in record["figures"]:
        assert Path(figure["path"]).name in report
    assert record["result"]["receipt_sha256"] in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["locked"] = False
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    assert not _evaluate_report_readiness(summary, store)["ready"]
    plan["locked"] = True
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    artifact = project.output_dir / record["artifacts"][0]["path"]
    artifact.write_text("changed report")
    assert not verify_clinical_artifacts(record, project.output_dir)
    assert not _evaluate_report_readiness(summary, store)["ready"]
    refused = asyncio.run(call("run_clinical_study", args))
    assert refused.is_error and "integrity" in refused.content[0].text
    assert artifact.read_text() == "changed report"


def test_clinical_render_recovery_keeps_numbers_and_rejects_changed_plan(tmp_path, monkeypatch):
    import asyncio
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.clinical import survival, report
    from rde.interface.mcp.server import create_server

    _, store, dataset, options = clinical_project(tmp_path)

    async def call(s):
        return await create_server().call_tool(
            "run_clinical_study", {"dataset_id": dataset.id, "clinical_options": s}
        )

    original = report.figures

    def broken(*a, **kw):
        raise OSError("fixture renderer failure")

    monkeypatch.setattr(report, "figures", broken)
    first = asyncio.run(call(options.to_dict()))
    assert first.is_error and "renderer failure" in first.content[0].text
    monkeypatch.setattr(report, "figures", original)
    monkeypatch.setattr(
        survival,
        "run_survival",
        lambda *a, **kw: pytest.fail("Fit repeated after rendering failure"),
    )
    assert not asyncio.run(call(options.to_dict())).is_error
    changed = {**options.to_dict(), "group": None}
    rejected = asyncio.run(call(changed))
    assert rejected.is_error and "exactly match" in rejected.content[0].text
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["analyses"][0]["execution_arguments"]["clinical_options"] = changed
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    rejected = asyncio.run(call(changed))
    assert rejected.is_error and "different source/specification" in rejected.content[0].text
