"""Native column-to-role envelopes must not invert role-like column names."""

from dataclasses import replace

from docx import Document
import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _flatten_variable_roles
from test_clinical_formal_exports import call
from test_clinical_survival import clinical_project
from test_matching_candidate import matching_fixture


@pytest.mark.parametrize("envelope_key", ["variable_roles", "roles"])
def test_explicit_native_envelope_retains_column_direction(envelope_key):
    # Names collide with role vocabulary and each other. The wrapper declares
    # direction, so neither role-word heuristics nor outer metadata may win.
    columns = {
        "treatment": "group",
        "group": "outcome",
        "outcome": "covariate",
        "exposure": "id",
        "predictor": "unassigned",
    }
    envelope = {
        envelope_key: columns,
        "dataset": "not-a-column",
        "research_question": "Not an outcome",
        "group": ["incorrect-outer-summary"],
    }
    assert _flatten_variable_roles(envelope) == columns
    assert _flatten_variable_roles({envelope_key: {}, "group": ["ghost"]}) == {}


def test_unwrapped_legacy_role_collections_still_expand():
    assert _flatten_variable_roles({"outcome": ["score"], "group": "arm"}) == {
        "score": "outcome",
        "arm": "group",
    }


@pytest.mark.parametrize(
    "outcome,treatment,covariate",
    [("outcome", "treatment", "stratum"), ("group", "outcome", "treatment")],
)
def test_actual_matching_docx_preserves_role_collision_columns(
    tmp_path, monkeypatch, outcome, treatment, covariate
):
    from rde.infrastructure.clinical import matching

    frame, options = matching_fixture("binary")
    frame = frame.rename(
        columns={options.outcome: outcome, options.treatment: treatment, "stratum": covariate}
    )
    options = replace(
        options,
        outcome=outcome,
        treatment=treatment,
        covariates=[{**options.covariates[0], "column": covariate}],
    )
    project, store, dataset, options = clinical_project(tmp_path, frame=frame, options=options)
    roles = {outcome: "outcome", treatment: "group", covariate: "covariate", "case": "id"}
    # This is the persisted Phase 3 representation produced by align_concept,
    # including redundant role summaries outside the canonical mapping.
    store.save(
        PipelinePhase.CONCEPT_ALIGNMENT,
        "variable_roles.json",
        {
            "dataset": dataset.id,
            "research_question": "Prespecified synthetic matching role check",
            "variable_roles": roles,
            "outcome": [outcome],
            "group": [treatment],
            "covariate": [covariate],
            "confirmed": True,
        },
    )
    store.save(
        PipelinePhase.SCHEMA_REGISTRY,
        "schema.json",
        {"variables": [{"name": column, "variable_type": "categorical"} for column in frame]},
    )
    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": options.to_dict()})
    record = clinical_records(store)[0]
    saved = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = saved.read_bytes()
    monkeypatch.setattr(matching, "run_matching", lambda *a, **kw: pytest.fail("Report refitted"))
    call("collect_results", {"project_id": project.id})
    call("assemble_report", {"project_id": project.id})
    call("export_report", {"project_id": project.id, "formats": "docx"})
    exports = project.artifacts_dir / "exports"
    for text in [
        (exports / "eda_report_formal_source.md").read_text(),
        "\n".join(p.text for p in Document(exports / "eda_report.docx").paragraphs),
    ]:
        assert f"主要 outcome / endpoint 變項：{outcome}。" in text
        assert f"主要 group / exposure 變項：{treatment}。" in text
        assert f"主要 covariate / adjuster 變項：{covariate}。" in text
        assert "主要 group / exposure 變項：group。" not in text
        assert record["result"]["receipt_sha256"] in text
    assert (
        store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json")["variable_roles"]
        == roles
    )
    assert saved.read_bytes() == frozen
    assert verify_clinical_artifacts(record, project.output_dir)
