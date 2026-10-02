"""Comparison receipts must keep the actual test, direction and analyzed groups."""

import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableType
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine


def categorical_table(counts):
    return pd.DataFrame(
        [
            {"outcome": f"level{i + 1}", "group": f"group{j + 1}"}
            for i, row in enumerate(counts)
            for j, count in enumerate(row)
            for _ in range(count)
        ]
    )


@pytest.mark.parametrize("backend", ["local-lite", "scipy"])
def test_mann_whitney_signed_full_range_and_ties_match_pairwise_dominance(backend, monkeypatch):
    monkeypatch.setenv("RDE_STATS_BACKEND", backend)
    engine = ScipyStatisticalEngine()
    for x, y in [([8, 9, 10, 11], [1, 2, 3]), ([1, 2, 2, 5], [2, 2, 4]), ([2, 2], [2, 2])]:
        frame = pd.DataFrame(
            {"group": ["Z-first"] * len(x) + ["A-second"] * len(y), "value": x + y}
        )
        result = engine.run_test(frame, "mann_whitney", ["value", "group"])
        expected = stats.mannwhitneyu(x, y, alternative="two-sided", method="auto")
        dominance = np.mean([np.sign(a - b) for a in x for b in y])
        assert result["statistic"] == pytest.approx(expected.statistic)
        assert result["p_value"] == pytest.approx(expected.pvalue)
        assert result["effect_size"] == pytest.approx(dominance)
        assert result["group_labels"] == ["Z-first", "A-second"]
        assert result["sample_sizes"] == [len(x), len(y)]
        assert result["effect_direction"] == "Z-first minus A-second"
        reversed_result = engine.run_test(
            frame, "mann_whitney", ["value", "group"], group_order=["A-second", "Z-first"]
        )
        assert reversed_result["effect_size"] == pytest.approx(-dominance)
        assert reversed_result["p_value"] == pytest.approx(expected.pvalue)


@pytest.mark.parametrize("backend", ["local-lite", "scipy"])
def test_fisher_is_exact_even_with_zero_cells_and_sparse_margins(backend, monkeypatch):
    monkeypatch.setenv("RDE_STATS_BACKEND", backend)
    engine = ScipyStatisticalEngine()
    for table, exact in [([[8, 2], [1, 5]], 0.034965034965034975), ([[6, 0], [0, 6]], 2 / 924)]:
        result = engine.run_test(categorical_table(table), "fisher_exact", ["outcome", "group"])
        assert result["p_value"] == pytest.approx(exact)
        assert result["contingency_matrix"] == table
        assert result["p_value_method"] == "two-sided Fisher exact (fixed margins)"
        json.dumps(result, allow_nan=False)
        if table[0][1] == 0:
            assert result["statistic"] is None
            assert result["statistic_status"] == "positive_infinity"
            assert result["effect_size_status"] == "positive_infinity"
        else:
            assert result["statistic"] == pytest.approx(20)


def test_sparse_binary_selection_uses_expected_cells_and_keeps_infinite_or_explicit():
    frame = categorical_table([[1, 0], [29, 30]])
    dataset = Dataset(
        row_count=len(frame), variables=[Variable("outcome", "object", VariableType.BINARY)]
    )
    result = CompareGroupsUseCase(ScipyStatisticalEngine()).execute(
        dataset, frame, ["outcome"], "group"
    )
    assert result.tests[0].test_name == "Fisher's exact test"
    assert result.tests[0].p_value == 1
    assert result.tests[0].statistic_status == "positive_infinity"
    assert result.tables["test_details"]["outcome"]["selection"]["minimum_expected_count"] == 0.5
    assert result.tables["test_details"]["outcome"]["group_labels"] == ["group1", "group2"]


def test_sparse_multicategory_does_not_silently_use_two_by_two_fisher_or_bad_chi_square():
    frame = categorical_table([[1, 0, 0], [19, 20, 20]])
    dataset = Dataset(
        row_count=len(frame), variables=[Variable("outcome", "object", VariableType.BINARY)]
    )
    with pytest.raises(ValueError, match="sparse.*2.*2"):
        CompareGroupsUseCase(ScipyStatisticalEngine()).execute(dataset, frame, ["outcome"], "group")


def test_tied_kruskal_and_pearson_chi_square_use_real_reference_distributions(monkeypatch):
    monkeypatch.delenv("RDE_STATS_BACKEND", raising=False)
    engine = ScipyStatisticalEngine()
    samples = [[1, 1, 2, 2, 2], [2, 2, 3, 3, 3], [3, 3, 4, 4, 4]]
    frame = pd.DataFrame({"value": sum(samples, []), "group": np.repeat(["Z", "M", "A"], 5)})
    actual = engine.run_test(frame, "kruskal_wallis", ["value", "group"])
    reference = stats.kruskal(*samples)
    assert actual["statistic"] == pytest.approx(reference.statistic)
    assert actual["p_value"] == pytest.approx(reference.pvalue)
    assert actual["group_labels"] == ["Z", "M", "A"]
    table = [[20, 10], [15, 25]]
    categorical = engine.run_test(categorical_table(table), "chi_square", ["outcome", "group"])
    reference = stats.chi2_contingency(table, correction=False)
    assert categorical["statistic"] == pytest.approx(reference.statistic)
    assert categorical["p_value"] == pytest.approx(reference.pvalue)
    assert categorical["effect_size"] == pytest.approx(np.sqrt(reference.statistic / 70))


def test_missing_first_observation_cannot_reverse_a_planned_group_direction():
    frame = pd.DataFrame(
        {"group": ["Z", "A"] * 6, "value": [None, 1, 10, 2, 11, 3, 12, 4, 13, 5, 14, 6]}
    )
    dataset = Dataset(
        row_count=len(frame), variables=[Variable("value", "float64", VariableType.CONTINUOUS)]
    )
    result = CompareGroupsUseCase(ScipyStatisticalEngine()).execute(
        dataset, frame, ["value"], "group"
    )
    details = result.tables["test_details"]["value"]
    assert (
        result.tables["case_sets"]["value"]["group_order"] == details["group_labels"] == ["Z", "A"]
    )
    assert result.tests[0].sample_sizes == (5, 6)
    assert details["sample_sizes"] == [5, 6]
    assert result.tests[0].effect_size == 1


def test_zero_odds_ratio_unused_categories_and_numeric_group_codes_stay_explicit():
    frame = categorical_table([[6, 0], [0, 6]])
    frame["group"] = pd.Categorical(
        frame["group"].map({"group1": 20, "group2": 1}), categories=[1, 20, 99]
    )
    frame["outcome"] = pd.Categorical(frame["outcome"], categories=["level2", "unused", "level1"])
    result = ScipyStatisticalEngine().run_test(
        frame, "fisher_exact", ["outcome", "group"], group_order=[1, 20]
    )
    assert result["contingency_matrix"] == [[0, 6], [6, 0]]
    assert result["group_labels"] == ["1", "20"]
    assert result["outcome_labels"] == ["level1", "level2"]
    assert result["statistic"] == result["effect_size"] == 0
    assert result["statistic_status"] == result["effect_size_status"] == "finite"
    assert result["p_value"] == pytest.approx(2 / 924)
    json.dumps(result, allow_nan=False)


def test_group_counts_alone_cannot_claim_expected_cell_adequacy():
    from rde.domain.services.statistical_advisor import StatisticalAdvisor

    result = StatisticalAdvisor().recommend_comparison_test(
        VariableType.BINARY, 2, False, None, [100, 100]
    )
    assert result.test_name == "Manual review needed"
    assert "group sizes alone are insufficient" in result.rationale


def test_report_keeps_boundary_and_zero_effect_estimates_separate_from_missing():
    from rde.interface.mcp.tools.report_tools import _comparison_results_markdown

    for estimate, status, expected in [
        (None, "positive_infinity", "+∞"),
        (0, "finite", "Odds Ratio = 0"),
    ]:
        text = _comparison_results_markdown(
            {
                "comparisons": [
                    {
                        "artifact": "compare_groups_group_outcome.json",
                        "tests": [
                            {
                                "variables": ["outcome", "group"],
                                "effect_size": estimate,
                                "effect_size_status": status,
                                "effect_size_name": "Odds Ratio",
                                "group_labels": ["Z", "A"],
                                "sample_sizes": [6, 6],
                            }
                        ],
                        "test_details": {
                            "outcome": {"p_value_method": "two-sided Fisher exact (fixed margins)"}
                        },
                    }
                ]
            }
        )
        assert expected in text
        assert "Z: n=6；A: n=6" in text
        assert "此比較未估計效果量信賴區間" in text
        assert "two-sided Fisher exact" in text
