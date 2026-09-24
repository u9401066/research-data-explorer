from __future__ import annotations

import math

import pandas as pd
import pytest

from rde.domain.services.repeated_measures import prepare_repeated_frame
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer


def test_signed_rank_matches_enumerated_sign_probability_and_reverses_direction():
    df = pd.DataFrame({"before": [10] * 6, "after": [11, 12, 13, 14, 15, 16]})
    engine = ScipyStatisticalEngine()
    result = engine.run_test(df, "wilcoxon", ["before", "after"])
    reverse = engine.run_test(df, "wilcoxon", ["after", "before"])
    # Of 2**6 equally likely sign assignments, only all-positive/all-negative
    # attain an extreme signed-rank sum. This reference does not call SciPy.
    assert result["statistic"] == 0
    assert result["p_value"] == 2 / 2**6
    assert result["effect_size"] == 1
    assert reverse["effect_size"] == -1
    assert result["effect_direction"] == "after - before"
    assert result["change_summary"]["mean"] == 3.5
    assert reverse["p_value"] == result["p_value"]


def test_friedman_reference_and_all_pair_family():
    df = pd.DataFrame({f"t{i}": [j + i * 10 for j in range(12)] for i in range(7)})
    result = ScipyStatisticalEngine().run_test(df, "friedman", list(df))
    # Identical within-person rank ordering => Q = n*(k-1), W=1.
    assert result["statistic"] == 72
    assert result["effect_size"] == 1
    # Closed-form chi-square(df=6) survival at Q=72.
    assert result["p_value"] == pytest.approx(math.exp(-36) * (1 + 36 + 36**2 / 2))
    assert result["warnings"] == []
    assert len(result["posthoc"]) == 21
    for pair in result["posthoc"]:
        assert pair["effect_size"] == 1
        assert pair["p_adjusted"] == min(1, pair["p_value"] * 21)


def test_all_zero_and_degenerate_friedman_are_explicit():
    df = pd.DataFrame({"t0": [1] * 12, "t1": [1] * 12, "t2": [1] * 12})
    engine = ScipyStatisticalEngine()
    paired = engine.run_test(df, "wilcoxon", ["t0", "t1"])
    assert paired["p_value_method"] == "all_zero_convention"
    assert paired["p_value"] == 1
    assert paired["zero_difference_pairs"] == 12
    assert "tie correction" in engine.run_test(df, "friedman", list(df))["error"]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), "not measured", "NaN"])
def test_non_numeric_is_rejected_before_plausibility_can_mask_it(bad):
    df = pd.DataFrame({"code": ["s1", "s2"], "weight_0": [50, bad], "weight_1": [55, 60]})
    with pytest.raises(ValueError, match="非數值|無限值"):
        prepare_repeated_frame(df, ["weight_0", "weight_1"], "code")


@pytest.mark.parametrize("subjects", [["a", "a"], ["a", None], ["a", " "]])
def test_subjects_must_be_unique_and_present(subjects):
    df = pd.DataFrame({"code": subjects, "t0": [1, 2], "t1": [2, 3]})
    with pytest.raises(ValueError, match="識別"):
        prepare_repeated_frame(df, ["t0", "t1"], "code")


def test_missing_rows_and_numeric_plausibility_are_shared_with_plot(tmp_path):
    df = pd.DataFrame(
        {
            "code": ["s1", "s2", "s3", "s4"],
            "weight_0": [50, None, 999, 60],
            "weight_1": [55, 60, 70, 66],
        }
    )
    clean, ledger, notes = prepare_repeated_frame(df, ["weight_0", "weight_1"], "code")
    assert ledger["complete_data_rows"] == [1, 4]
    assert ledger["excluded_data_rows"] == [2, 3]
    assert ledger["observed_bitmask_by_data_row"] == [3, 2, 2, 3]
    assert ledger["plausibility_exclusions"] == [{"variable": "weight_0", "data_rows": [3]}]
    assert len(notes) == 1
    result = ScipyStatisticalEngine().run_test(clean, "wilcoxon", ["weight_0", "weight_1"])
    assert result["n_pairs"] == 2
    viz = MatplotlibVisualizer()
    viz.create_plot(
        df,
        "paired",
        ["weight_0", "weight_1"],
        tmp_path / "paired.png",
        subject_variable="code",
        include_tests=False,
    )
    assert "n=2" in viz.last_annotation_summary
    assert "p=" not in viz.last_annotation_summary
    assert (tmp_path / "paired.png").stat().st_size > 1000


@pytest.mark.parametrize("plot,variables", [("paired", ["t0", "t1"]), ("line", ["t0", "t1", "t2"])])
def test_descriptive_time_figures_do_not_add_unapproved_tests(tmp_path, plot, variables):
    df = pd.DataFrame({"t0": list(range(12)), "t1": list(range(12, 24)), "t2": list(range(24, 36))})
    viz = MatplotlibVisualizer()
    viz.create_plot(df, plot, variables, tmp_path / "figure.png", include_tests=False)
    assert "n=12" in viz.last_annotation_summary
    assert "p=" not in viz.last_annotation_summary
    assert "p <" not in viz.last_annotation_summary
    assert "Wilcoxon" not in viz.last_annotation_summary
    assert "Friedman" not in viz.last_annotation_summary


def test_exploratory_time_plot_uses_paired_friedman_not_independent_kruskal(tmp_path):
    df = pd.DataFrame({"t0": list(range(12)), "t1": list(range(12, 24)), "t2": list(range(24, 36))})
    viz = MatplotlibVisualizer()
    viz.create_plot(df, "line", list(df), tmp_path / "figure.png", include_tests=True)
    assert "Friedman chi2=24.00" in viz.last_annotation_summary


def test_paired_interpretation_respects_registered_alpha():
    df = pd.DataFrame({"a": [0] * 6, "b": [1, 2, 3, 4, 5, 6]})
    result = ScipyStatisticalEngine().run_test(df, "wilcoxon", ["a", "b"], alpha=0.01)
    assert result["p_value"] == 0.03125
    assert "reject_null=False" in result["interpretation"]
