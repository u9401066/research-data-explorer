"""Numerical edge cases and the actual locked MCP/report/evidence workflow."""

import asyncio
import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm, t

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.clinical.measurement import (
    MeasurementSpec,
    prepare_measurement,
    run_measurement,
)
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness


def diagnostic_spec(**changes):
    diagnostic = dict(
        positive="M",
        negative="B",
        reference_description="Declared synthetic reference standard",
        reference_independence="unknown",
        sampling="single_gate",
        test_kind="score",
        threshold=5.0,
        positive_direction="greater_equal",
        test_positive=None,
        test_negative=None,
        threshold_basis="Engineering test cutoff, no clinical validation",
        threshold_status="exploratory",
        reference_indeterminate=[],
        test_indeterminate=[],
    )
    diagnostic.update(changes.pop("diagnostic", {}))
    return MeasurementSpec.parse(
        dict(
            family="diagnostic_accuracy",
            first="reference",
            second="index",
            context="Synthetic independent pairs for numerical checks",
            independent_rows=True,
            diagnostic=diagnostic,
            **changes,
        )
    )


def diagnostic_frame():
    return pd.DataFrame(
        {"reference": ["M"] * 5 + ["B"] * 5, "index": [9, 8, 7, 5, 1, 8, 5, 4, 2, 0]}
    )


def agreement_spec(**changes):
    agreement = dict(
        unit="mmHg",
        coverage=0.95,
        acceptable_lower=-8.0,
        acceptable_upper=8.0,
        margin_basis="Synthetic engineering acceptance example",
    )
    agreement.update(changes.pop("agreement", {}))
    return MeasurementSpec.parse(
        dict(
            family="bland_altman",
            first="first",
            second="second",
            context="Two simultaneous independent paired devices",
            independent_rows=True,
            agreement=agreement,
            **changes,
        )
    )


def agreement_frame():
    rng = np.random.default_rng(83)
    second = rng.normal(120, 10, 40)
    return pd.DataFrame({"first": second + rng.normal(1.5, 3, 40), "second": second})


def kappa_spec():
    return MeasurementSpec.parse(
        dict(
            family="cohens_kappa",
            first="first",
            second="second",
            context="Independent blinded synthetic raters",
            independent_rows=True,
            categories=["high", "low", "unused"],
        )
    )


def kappa_frame():
    return pd.DataFrame(
        {
            "first": ["high"] * 7 + ["low"] * 5,
            "second": ["high"] * 5 + ["low"] * 2 + ["high"] + ["low"] * 4,
        }
    )


def test_diagnostic_manual_counts_wilson_and_reversed_direction_preserve_source():
    frame, spec = diagnostic_frame(), diagnostic_spec()
    original = frame.copy(deep=True)
    result = run_measurement(frame, spec)
    assert result["confusion_counts"] == dict(TP=4, FN=1, FP=2, TN=3)
    for key, num, den in [
        ("sensitivity", 4, 5),
        ("specificity", 3, 5),
        ("positive_predictive_value", 4, 6),
        ("negative_predictive_value", 3, 4),
        ("accuracy", 7, 10),
    ]:
        row = result["estimates"][key]
        z, p = norm.ppf(0.975), num / den
        center = (p + z * z / (2 * den)) / (1 + z * z / den)
        width = z * math.sqrt(p * (1 - p) / den + z * z / (4 * den * den)) / (1 + z * z / den)
        assert [row["estimate"], row["ci_lower"], row["ci_upper"]] == pytest.approx(
            [p, center - width, center + width]
        )
        assert (row["numerator"], row["denominator"]) == (num, den)
    # Mann–Whitney pair comparisons, with exact half-credit ties, independently checks AUC.
    expected_auc = np.mean(
        [float(x > y) + 0.5 * float(x == y) for x in frame["index"][:5] for y in frame["index"][5:]]
    )
    assert result["roc"]["estimate"] == expected_auc
    reverse = run_measurement(
        frame.assign(index=-frame["index"]),
        diagnostic_spec(diagnostic={"threshold": -5, "positive_direction": "less_equal"}),
    )
    assert reverse["estimates"] == result["estimates"] and reverse["roc"] == result["roc"]
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("sampling", ["two_gate", "unknown"])
def test_selected_or_unknown_sampling_never_promotes_sample_predictive_values(sampling):
    result = run_measurement(diagnostic_frame(), diagnostic_spec(diagnostic={"sampling": sampling}))
    assert result["estimates"]["sensitivity"]["estimate"] == 0.8
    for key in ["positive_predictive_value", "negative_predictive_value", "accuracy"]:
        assert result["estimates"][key]["estimate"] is None and result["estimates"][key]["reason"]


def test_zero_denominators_and_one_reference_class_are_not_perfect_performance():
    result = run_measurement(
        pd.DataFrame({"reference": ["B"] * 5, "index": [0] * 5}), diagnostic_spec()
    )
    assert result["estimates"]["sensitivity"]["estimate"] is None
    assert result["estimates"]["positive_predictive_value"]["denominator"] == 0
    assert result["roc"]["estimate"] is None and not result["roc"]["curve"]


def test_single_positive_subject_does_not_get_a_degenerate_bootstrap_interval():
    result = run_measurement(
        pd.DataFrame({"reference": ["M", "B", "B"], "index": [9, 4, 2]}), diagnostic_spec()
    )
    assert result["roc"]["estimate"] == 1
    assert result["roc"]["ci_lower"] is None and result["roc"]["bootstrap_samples"] == 0


def test_indeterminate_missing_overlap_and_case_alignment_are_explicit():
    frame = pd.concat(
        [
            diagnostic_frame(),
            pd.DataFrame({"reference": [None, "U", "M", "U"], "index": [9, 8, "ERR", None]}),
        ],
        ignore_index=True,
    )
    spec = diagnostic_spec(
        diagnostic={"reference_indeterminate": ["U"], "test_indeterminate": ["ERR"]}
    )
    prepared, ledger, _ = prepare_measurement(frame, spec)
    assert len(prepared) == 10 and ledger["complete_data_rows"] == list(range(1, 11))
    assert ledger["missing_excluded_data_rows"] == [11, 14]
    assert ledger["indeterminate_excluded_data_rows"] == [12, 13]
    assert ledger["reference_indeterminate_rows"] == [12, 14]
    assert ledger["test_indeterminate_rows"] == [13]
    assert run_measurement(frame, spec)["confusion_counts"] == dict(TP=4, FN=1, FP=2, TN=3)


@pytest.mark.parametrize(
    "change, message",
    [
        (dict(reference="unknown"), "Unlisted reference"),
        (dict(index="bad"), "non-numeric"),
        (dict(index=float("inf")), "non-finite"),
    ],
)
def test_invalid_codes_and_numeric_values_fail_even_if_other_column_is_missing(change, message):
    frame = diagnostic_frame().astype(object)
    for column, value in change.items():
        frame.loc[0, column] = value
    frame.loc[0, "index" if "reference" in change else "reference"] = None
    with pytest.raises(ValueError, match=message):
        prepare_measurement(frame, diagnostic_spec())


def test_duplicate_subjects_are_not_hidden_by_incomplete_case_exclusion():
    frame = diagnostic_frame().assign(subject=list(range(10)))
    frame.loc[1, ["subject", "index"]] = [0, np.nan]
    with pytest.raises(ValueError, match="unique"):
        prepare_measurement(frame, diagnostic_spec(subject="subject"))


def test_binary_original_labels_are_mapped_explicitly_without_roc_or_cutoff_guessing():
    frame = diagnostic_frame()
    frame["index"] = np.where(frame["index"] >= 5, "detected", "absent")
    spec = diagnostic_spec(
        diagnostic={
            "test_kind": "binary",
            "test_positive": "detected",
            "test_negative": "absent",
            "threshold": None,
            "positive_direction": None,
        }
    )
    result = run_measurement(frame, spec)
    assert result["roc"] is None and result["confusion_counts"] == dict(TP=4, FN=1, FP=2, TN=3)
    with pytest.raises(ValueError, match="binary"):
        diagnostic_spec(
            diagnostic={
                "test_kind": "binary",
                "test_positive": "detected",
                "test_negative": "absent",
            }
        )


def test_bland_altman_coverage_and_ci_are_separate_with_exact_pair_ledger():
    frame = agreement_frame()
    frame.loc[3, "first"] = np.nan
    frame.loc[6, "second"] = np.nan
    result = run_measurement(frame, agreement_spec(confidence_level=0.99))
    retained = frame.dropna()
    differences = retained["first"] - retained["second"]
    n, bias, sd = len(retained), differences.mean(), differences.std(ddof=1)
    z, critical = norm.ppf(0.975), t.ppf(0.995, n - 1)
    lo = result["estimates"]["lower_limit_of_agreement"]
    expected = bias - z * sd
    width = critical * sd * math.sqrt(1 / n + z * z / (2 * (n - 1)))
    assert [lo["estimate"], lo["ci_lower"], lo["ci_upper"]] == pytest.approx(
        [expected, expected - width, expected + width]
    )
    assert result["agreement_coverage"] == 0.95 and result["confidence_level"] == 0.99
    assert result["case_ledger"]["missing_excluded_data_rows"] == [4, 7]
    assert [p["difference"] for p in result["points"]] == pytest.approx(differences)
    assert result["margin_comparison"]["within_count"] == int((differences.abs() <= 8).sum())
    assert "not a formal equivalence" in result["margin_comparison"]["claim"]


def test_kappa_matches_manual_marginals_and_does_not_claim_diagnostic_validity():
    result = run_measurement(kappa_frame(), kappa_spec())
    po, pe = 9 / 12, (7 * 6 + 5 * 6) / 144
    assert result["observed_agreement"] == po
    assert result["estimates"]["cohens_kappa"]["estimate"] == pytest.approx((po - pe) / (1 - pe))
    assert result["table"] == [[5, 2], [1, 4]]
    with pytest.raises(ValueError, match="prespecified"):
        run_measurement(kappa_frame().assign(first="unexpected"), kappa_spec())


def measurement_project(tmp_path, family):
    from test_clinical_survival import clinical_project
    from rde.application.session import get_session

    project, store, dataset, _ = clinical_project(tmp_path)
    frame, spec = {
        "diagnostic_accuracy": (diagnostic_frame(), diagnostic_spec()),
        "bland_altman": (agreement_frame(), agreement_spec()),
        "cohens_kappa": (kappa_frame(), kappa_spec()),
    }[family]
    frame.to_csv(dataset.metadata.file_path, index=False)
    dataset.row_count = len(frame)
    get_session().register_dataset(dataset, frame)
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                dict(
                    type="run_clinical_study",
                    variables=spec.variables(),
                    execution_arguments={"clinical_options": spec.to_dict()},
                )
            ],
        },
    )
    return project, store, dataset, spec


async def call(name, args):
    return await create_server().call_tool(name, args)


@pytest.mark.parametrize(
    "family, figures", [("diagnostic_accuracy", 4), ("bland_altman", 4), ("cohens_kappa", 2)]
)
def test_actual_mcp_preflight_execution_report_integrity_and_reuse(
    tmp_path, monkeypatch, family, figures
):
    from rde.interface.mcp.tools import clinical_tools

    project, store, dataset, spec = measurement_project(tmp_path, family)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    preflight = asyncio.run(call("inspect_clinical_study", args))
    assert not preflight.is_error, preflight.content
    assert json.loads(preflight.content[0].text)["family"] == family
    assert not clinical_records(store)
    changed = {**args, "clinical_options": {**spec.to_dict(), "context": "A changed study"}}
    assert asyncio.run(call("run_clinical_study", changed)).is_error
    response = asyncio.run(call("run_clinical_study", args))
    assert not response.is_error, response.content
    record = clinical_records(store)[0]
    assert len(record["figures"]) == figures and verify_clinical_artifacts(
        record, project.output_dir
    )
    monkeypatch.setattr(
        clinical_tools, "run_measurement", lambda *a: pytest.fail("Saved study was recomputed")
    )
    assert not asyncio.run(call("run_clinical_study", args)).is_error
    assert not asyncio.run(call("collect_results", {"project_id": project.id})).is_error
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert summary["clinical_studies"][0]["family"] == family
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    assembled = asyncio.run(call("assemble_report", {"project_id": project.id}))
    assert not assembled.is_error, assembled.content
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert record["result"]["receipt_sha256"] in report and "個案納入與排除" in report
    assert "臨床事件結果解讀" not in report and "Cox 模型與適用限制" not in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    artifact = project.output_dir / record["artifacts"][0]["path"]
    artifact.write_text("altered evidence")
    assert not _evaluate_report_readiness(summary, store)["ready"]
    refused = asyncio.run(call("run_clinical_study", args))
    assert refused.is_error and "integrity" in refused.content[0].text
    assert artifact.read_text() == "altered evidence"


def test_renderer_failure_retains_numbers_and_can_recover_without_reanalysis(tmp_path, monkeypatch):
    from rde.interface.mcp.tools import clinical_tools
    from rde.infrastructure.clinical import measurement_report

    _, store, dataset, spec = measurement_project(tmp_path, "diagnostic_accuracy")
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original = measurement_report.figures

    def broken(*args):
        raise OSError("Synthetic renderer failure")

    monkeypatch.setattr(measurement_report, "figures", broken)
    failed = asyncio.run(call("run_clinical_study", args))
    assert failed.is_error and "renderer failure" in failed.content[0].text
    receipt = clinical_records(store)[0]["result"]["receipt_sha256"]
    monkeypatch.setattr(measurement_report, "figures", original)
    monkeypatch.setattr(
        clinical_tools,
        "run_measurement",
        lambda *a: pytest.fail("Repeated estimates after renderer failure"),
    )
    recovered = asyncio.run(call("run_clinical_study", args))
    assert not recovered.is_error, recovered.content
    assert clinical_records(store)[0]["result"]["receipt_sha256"] == receipt
