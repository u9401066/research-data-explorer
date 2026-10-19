"""Saved figure descriptions must not invent a contrast, pathology, or new analysis."""

import copy

import pytest

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools.report_tools import (
    _figure_interpretation_harness_entry,
    _interpret_advanced_models,
    _interpret_table_one,
    _render_figure_harness_bullets,
)


def entry(plot, caption, variables=None, group=""):
    return _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type=plot,
        variables=variables or ["treatment"],
        stats_summary=caption,
        group_var=group,
    )


@pytest.mark.parametrize("plot", ["bar", "boxplot", "violin"])
def test_ungrouped_display_does_not_invent_a_between_group_comparison(plot):
    caption = "n=160; levels=2; 0 n=80, 1 n=80"
    result = entry(plot, caption)
    text = "\n".join(_render_figure_harness_bullets(result))
    assert "Univariate" in result["evidence_role"]
    assert "is compared" not in text
    assert "group-contrast pattern" not in text
    assert "Collapse sparse" not in text
    assert result["statistical_support"] == caption


@pytest.mark.parametrize("caption", ["Descriptive only; 0 n=80, 1 n=80", "0 n=2, 1 n=158"])
def test_grouped_plot_never_prescribes_merging_or_redefines_an_approved_contrast(caption):
    result = entry("boxplot", caption, ["lactate"], "treatment")
    text = "\n".join(_render_figure_harness_bullets(result))
    assert "across treatment" in result["visual_read"]
    assert result["statistical_support"] == caption
    assert "Collapse" not in text
    assert "approved" in result["next_analysis"]
    assert bool(result["sparse_groups"]) == ("n=2," in caption)


def test_weak_correlation_heatmap_does_not_assert_redundancy_or_variable_semantics():
    result = entry("heatmap", "age vs sofa_score: r=-0.10", ["age", "sofa_score"])
    text = "\n".join(_render_figure_harness_bullets(result))
    assert "anthropometric" not in text
    assert "small-sample" not in text
    assert "around redundant covariates" not in text
    assert "Avoid putting" not in text
    assert result["statistical_support"] == "age vs sofa_score: r=-0.10"


def test_scatter_has_no_unsupported_sample_size_or_strength_verdict():
    result = entry("scatter", "r=0.50; p=0.06", ["age", "lactate"])
    text = "\n".join(_render_figure_harness_bullets(result))
    assert "cohort is small" not in text
    assert "association is weak" not in text
    assert result["statistical_support"] == "r=0.50; p=0.06"


@pytest.mark.parametrize(
    "kind",
    [
        "advanced_inclusion",
        "advanced_coefficients",
        "advanced_fitted",
        "advanced_residuals",
        "unknown_saved_plot",
    ],
)
def test_unmapped_plot_keeps_exact_caption_with_concise_review_caveat(kind):
    caption = "Saved original caption: model n=160; coefficient=-0.090516; CI crosses zero."
    result = entry(kind, caption, ["treatment", "lactate"])
    bullets = _render_figure_harness_bullets(result)
    assert len(bullets) <= 3
    assert sum(caption in line for line in bullets) == 1
    assert "review" in " ".join(bullets).lower()
    assert "unmapped" not in " ".join(bullets)
    assert result["statistical_support"] == caption
    assert result["p_value"] is None
    assert "No additional result claim" in result["reportable_claim"]


def test_missing_unmapped_caption_remains_explicitly_unavailable():
    result = entry("unknown_saved_plot", "")
    assert "No statistical annotation" in "\n".join(_render_figure_harness_bullets(result))


def test_balanced_table_does_not_invent_a_sparse_code_warning():
    table = "| Variable | Overall | 0 | 1 |\n|---|---|---|---|\n| n | 160 | 80 | 80 |\n| age | 50 (10) | 50 (10) | 50 (10) |"
    text = _interpret_table_one(table, {"row_count": 160})
    assert "preserve the sparse-code warning" not in text
    assert "collapsed" not in text


def test_undefined_table_sd_does_not_diagnose_single_observation_or_merge_groups():
    text = _interpret_table_one("| Variable | Overall |\n|---|---|\n| age | 50 (nan) |", None)
    assert "some groups contain a single observation" not in text
    assert "collapsed" not in text
    assert "counts" in text


def test_alpha_display_changes_no_saved_value_or_comparison(tmp_path):
    store = ArtifactStore(tmp_path)
    payload = {
        "result": {
            "analysis_type": "multiple_regression",
            "target": "lactate",
            "p_values": {"const": 0.01, "treatment": 0.720616},
            "inference_policy": {"alpha": 0.050000000000000044},
        }
    }
    original = copy.deepcopy(payload)
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, "advanced_analysis_saved.json", payload)
    before = path.read_bytes()
    text = _interpret_advanced_models(store)
    assert "alpha=0.05 " in text
    assert "0.050000000000000044" not in text
    assert "not evidence of equivalence" in text
    assert payload == original and path.read_bytes() == before


# Reuse only the immutable saved-artifact projection fixture: no dataset load or fit.
from test_generic_report_completeness import saved_report as _saved_report  # noqa: E402

saved_report = _saved_report


def test_saved_case_docx_keeps_all_images_and_replaces_unsupported_narratives(saved_report):
    assert len(saved_report.drawings) == 16
    for unsupported in [
        "treatment is compared.",
        "Collapse sparse groups",
        "cohort is small",
        "anthropometric",
        "around redundant covariates",
        "0.050000000000000044",
        "interpretation type not mapped",
        "No additional result claim",
    ]:
        assert unsupported not in saved_report.text
    assert "Univariate distribution description" in saved_report.text
    assert saved_report.text.count("Saved original caption — researcher review required:") == 5
    assert "alpha=0.05" in saved_report.text
    for estimate in ["-0.090516", "0.720616", "-0.0962016", "0.705763"]:
        assert estimate in saved_report.text


def test_saved_case_native_captions_remain_verbatim_in_formal_markdown(saved_report):
    from rde.interface.mcp.tools.report_tools import _resolved_visualization_manifest_entries

    entries = _resolved_visualization_manifest_entries(saved_report.project, saved_report.store)
    advanced = [x for x in entries if x.get("plot_type", "").startswith("advanced_")]
    assert len(advanced) == 5
    for item in advanced:
        caption = str(item.get("summary") or item.get("stats_summary") or "").strip()
        assert caption and caption in saved_report.rendered
