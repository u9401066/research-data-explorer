"""Interpret native plot roles, never generic first-variable visual patterns."""

import copy

import pytest

from rde.application.pipeline import PipelinePhase
from rde.domain.models.project import Project
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools.report_tools import (
    _build_figure_interpretation_harness,
    _figure_interpretation_harness_entry,
)


@pytest.mark.parametrize(
    ("kind", "role", "caveat"),
    [
        ("clinical_participant_flow", "inclusion and exclusion", "independence"),
        ("clinical_incidence_G1", "Cumulative incidence", "ordinary censoring"),
        ("clinical_incidence_G2", "Cumulative incidence", "fixed-time"),
        ("clinical_survival", "Kaplan–Meier", "censoring"),
        ("clinical_risk_table_1", "Numbers at risk", "Zero remaining"),
        ("clinical_cox_1", "Cox hazard-ratio", "not a cumulative-risk"),
        ("clinical_ph_c0_0", "Proportional-hazards", "do not test a treatment effect"),
    ],
)
def test_clinical_figure_roles_preserve_exact_caption_without_new_significance(kind, role, caveat):
    caption = "Saved caption: n=12; rank p=0.01, Holm p=0.06; source coding retained."
    result = _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type=kind,
        variables=["time", "status", "treatment"],
        stats_summary=caption,
        group_var="treatment",
    )
    assert role in result["evidence_role"]
    assert caveat in result["validity_caveat"]
    assert result["statistical_support"] == caption
    assert result["p_value"] is None
    assert "displays time" not in result["visual_read"]
    assert "role is unclear" not in result["validity_caveat"]


def test_native_manifest_six_survival_panels_keep_source_bytes_and_distinct_roles(tmp_path):
    project = Project(
        id="figure-roles", name="roles", data_dir=tmp_path / "data", output_dir=tmp_path / "project"
    )
    store = ArtifactStore(project.artifacts_dir)
    figures_dir = project.output_dir / "figures"
    kinds = [
        "clinical_participant_flow",
        "clinical_incidence_G1",
        "clinical_incidence_G2",
        "clinical_risk_table_1",
        "clinical_cox_1",
        "clinical_ph_c0_0",
    ]
    entries = []
    for index, kind in enumerate(kinds):
        path = figures_dir / f"panel-{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unchanged saved figure")
        entries.append(
            dict(
                plot_type=kind,
                variables=["time", "status"],
                group_var="group",
                output_path=f"figures/{path.name}",
                stats_summary=f"Exact saved caption {index}; no new calculation.",
            )
        )
    original = copy.deepcopy(entries)
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json", entries)
    before = path.read_bytes()
    results = _build_figure_interpretation_harness(project, store)
    assert [x["plot_type"] for x in results] == kinds
    assert [x["statistical_support"] for x in results] == [x["stats_summary"] for x in original]
    assert len({x["evidence_role"] for x in results}) == 5
    assert path.read_bytes() == before
    assert all(p.read_bytes() == b"unchanged saved figure" for p in figures_dir.glob("*.png"))


def test_unknown_plot_does_not_infer_pattern_from_time_or_p_value():
    result = _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type="clinical_unknown",
        variables=["time"],
        stats_summary="Existing author caption: p=0.001; requires method review.",
        group_var="group",
    )
    assert "no structured interpretation" in result["visual_read"]
    assert "displays time" not in result["visual_read"]
    assert "No additional result claim" in result["reportable_claim"]
    assert result["statistical_support"].startswith("Existing author caption")


def test_missing_caption_does_not_fabricate_numeric_support():
    result = _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type="clinical_cox_1",
        variables=["time"],
        stats_summary="",
        group_var="group",
    )
    assert "numerical interpretation remains unverified" in result["statistical_support"]
    assert "adjustment scope" in result["reportable_claim"]
