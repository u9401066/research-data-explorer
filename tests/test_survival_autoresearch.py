"""Primary-bound survival branches: fixed cases, independent math, real MCP queue."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
import pytest
from statsmodels.duration.hazard_regression import PHReg

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.clinical.survival import digest, run_survival, run_survival_sensitivity
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools._shared.clinical_branch import execute_survival_branch
from rde.interface.mcp.tools.clinical_tools import clinical_records
from test_clinical_survival import clinical_project, cox_frame, spec


@pytest.mark.parametrize("competing", [False, True])
def test_omitted_missing_predictor_cannot_expand_cohort_and_reference_matches_phreg(competing):
    frame = cox_frame()
    frame.loc[::7, "x"] = np.nan
    frame["cohort"] = "trial"
    frame.loc[:10, "cohort"] = "other"
    if competing:
        frame.loc[(frame.index % 3 == 0) & (frame.status == "C"), "status"] = "T"
    original = frame.copy(deep=True)
    baseline = spec(
        group="group",
        covariates=["x", "group"],
        categorical_covariates=["group"],
        references={"group": "control"},
        competing_values=["T"] if competing else [],
        cohort_filter={"column": "cohort", "values": ["trial"]},
    )
    primary = run_survival(frame, baseline)
    branch = run_survival_sensitivity(frame, baseline, ["group"])
    retained = frame.loc[(frame.cohort == "trial") & frame.x.notna()]
    reference = PHReg(
        retained.time,
        (retained.group == "treated").astype(float).to_numpy()[:, None],
        status=retained.status == "D",
        ties="efron",
    ).fit()
    estimate = branch["cox"]["coefficients"][0]
    assert estimate["hazard_ratio"] == pytest.approx(np.exp(reference.params[0]), abs=2e-5)
    assert estimate["reference"] == "control"
    assert branch["case_ledger"] == primary["case_ledger"]
    assert branch["strata"] == primary["strata"]
    assert branch["n"] == len(retained) < len(frame[frame.cohort == "trial"])
    assert branch["dataframe_sha256"] == primary["dataframe_sha256"]
    assert branch["population_spec_sha256"] == primary["spec_sha256"]
    assert branch["spec"]["covariates"] == ["group"]
    assert branch["cox"]["method"] == (
        "cause-specific Cox" if competing else "Cox proportional hazards"
    )
    assert (
        digest({k: v for k, v in branch.items() if k != "receipt_sha256"})
        == branch["receipt_sha256"]
    )
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("covariates", [[], ["x", "group"], ["x", "x"], ["unknown"]])
def test_identical_empty_duplicate_and_new_predictors_are_rejected(covariates):
    with pytest.raises(ValueError, match="proper subset"):
        run_survival_sensitivity(cox_frame(), spec(covariates=["x", "group"]), covariates)


@pytest.fixture
def primary(tmp_path):
    project, store, dataset, options = clinical_project(tmp_path)

    async def run():
        return await create_server().call_tool(
            "run_clinical_study", {"dataset_id": dataset.id, "clinical_options": options.to_dict()}
        )

    response = asyncio.run(run())
    assert not response.is_error, response.content
    record = clinical_records(store)[0]
    path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    contract = dict(
        tool="run_clinical_study",
        analysis_type="survival_sensitivity",
        covariates=["x"],
        focus_variable="x",
        required_covariates=["x"],
        primary_receipt_sha256=record["result"]["receipt_sha256"],
        primary_record_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        case_set_sha256=digest(record["result"]["case_ledger"]["complete_data_rows"]),
    )
    return project, store, dataset, record, path, contract


@pytest.mark.parametrize("preset", ["journal-neutral-english-v1", "nature-single-v1"])
def test_real_mcp_survival_branch_has_full_reports_and_cannot_overwrite_primary(
    primary, monkeypatch, preset
):
    if preset == "nature-single-v1":
        font_dir = os.environ.get("RDE_JOURNAL_TEST_FONT_DIR") or os.environ.get(
            "RDE_PUBLICATION_FONT_DIR"
        )
        if not font_dir:
            pytest.skip(
                "Nature branch edition requires an explicitly configured authorized Arial directory"
            )
        monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", font_dir)
    project, store, _, record, path, contract = primary
    primary_path = path
    originals = {
        p: p.read_bytes()
        for p in [path, *[project.output_dir / a["path"] for a in record["artifacts"]]]
    }

    async def run():
        server = create_server()
        seeded = await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project.id,
                "max_tasks": 1,
                "include_builtin_suggestions": False,
                "agent_proposals": [
                    {
                        "hypothesis": "Evaluate adjustment sensitivity on the same people",
                        "reason": "Compare effect uncertainty, not significance",
                        "variables": ["x"],
                        "analysis_contract": contract,
                    }
                ],
            },
        )
        assert not seeded.is_error, seeded.content
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    response = asyncio.run(run())
    assert not response.is_error, response.content
    event = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")[-1]
    assert event["status"] == "completed"
    assert event["metrics"]["n"] == record["result"]["n"]
    assert event["metrics"]["case_set_sha256"] == contract["case_set_sha256"]
    artifact = next(p for p in event["artifacts"] if p.endswith("survival_sensitivity.json"))
    payload = json.loads((project.output_dir / artifact).read_text())
    assert payload["status"] == "completed"
    assert payload["analysis_result"]["case_ledger"] == record["result"]["case_ledger"]
    assert len(payload["figures"]) == 5
    for figure in payload["figures"]:
        for path in figure["publication"]["files"].values():
            assert str(Path(path).relative_to(project.output_dir)) in {
                a["path"] for a in payload["artifacts"]
            }
        assert "exploratory adjustment-sensitivity" in figure["publication"]["caption_en"]
    for a in payload["artifacts"]:
        assert (
            hashlib.sha256((project.output_dir / a["path"]).read_bytes()).hexdigest() == a["sha256"]
        )
    report_path = next(a["path"] for a in payload["artifacts"] if a["path"].endswith(".md"))
    assert "未恢復任何被排除個案" in (project.output_dir / report_path).read_text()
    assert all(p.read_bytes() == before for p, before in originals.items())

    # Edition requests exercise the public MCP entry point with a real executed
    # branch. Neither a successful render nor recovery may invoke an estimator.
    from rde.infrastructure.clinical import survival, survival_publication
    from rde.interface.mcp.tools._shared.branch_publication import branch_publication_source
    from rde.interface.mcp.tools.publication_tools import file_hash

    monkeypatch.setattr(survival, "run_survival", lambda *a, **kw: pytest.fail("Refitted primary"))
    monkeypatch.setattr(
        survival, "run_survival_sensitivity", lambda *a, **kw: pytest.fail("Refitted branch")
    )
    source = project.output_dir / artifact
    branch_originals = {
        p: p.read_bytes()
        for p in [source, *[project.output_dir / a["path"] for a in payload["artifacts"]]]
    }
    ledger_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    ledger_before = ledger_path.read_bytes()
    args = dict(
        project_id=project.id,
        branch_id=payload["branch_id"],
        experiment_id=payload["experiment_id"],
        expected_record_sha256=file_hash(source),
        preset_id=preset,
        edition_id=str(uuid.uuid4()),
        start_number=7,
        captions={
            "1": {
                "title": "Participant flow in the exploratory model",
                "caption_en": "Fixed participants from the saved primary study.",
                "explanation_zh": "沿用主要分析固定個案。",
            }
        },
    )

    def render(values):
        response = asyncio.run(create_server().call_tool("render_branch_publication", values))
        assert not response.is_error, response.content
        text = "".join(c.text for c in response.content if hasattr(c, "text"))
        assert not text.startswith("❌"), text
        return json.loads(text)

    edition = render(args)
    assert edition["publication_scope"] == "exploratory_branch"
    assert edition["source_branch_id"] == payload["branch_id"]
    assert edition["source_experiment_id"] == payload["experiment_id"]
    assert (
        edition["source_numerical_receipt_sha256"] == payload["analysis_result"]["receipt_sha256"]
    )
    assert edition["primary_binding"] == payload["primary_binding"]
    assert len(edition["artifacts"]) == len(payload["figures"]) * 6 + 1
    for item in edition["artifacts"]:
        output = project.output_dir / item["path"]
        assert output.stat().st_size == item["bytes"] and file_hash(output) == item["sha256"]
    assert (
        "exploratory adjustment-sensitivity" in edition["figures"][0]["publication"]["caption_en"]
    )
    assert (
        "不取代主要分析"
        in (
            project.output_dir
            / "figures"
            / "editions"
            / args["edition_id"]
            / "publication-edition.md"
        ).read_text()
    )
    for old, new in zip(payload["figures"], edition["figures"], strict=True):
        assert (
            Path(old["publication"]["files"]["data"]).read_bytes()
            == Path(new["publication"]["files"]["data"]).read_bytes()
        )
    from test_publication_dictionary import display_dictionary, numerical_rows

    annotated = render(
        {**args, "edition_id": str(uuid.uuid4()), "display_dictionary": display_dictionary(record)}
    )
    for old, new in zip(payload["figures"], annotated["figures"], strict=True):
        caption = new["publication"]["caption_en"]
        assert caption.count("exploratory adjustment-sensitivity") == 1
        assert caption.count("Display labels follow") == 1
        assert numerical_rows(old["publication"]["files"]["data"]) == numerical_rows(
            new["publication"]["files"]["data"]
        )
    monkeypatch.setattr(
        survival_publication,
        "figures",
        lambda *a, **kw: pytest.fail("Rendered saved edition again"),
    )
    assert render(args) == edition
    assert ledger_path.read_bytes() == ledger_before
    assert all(p.read_bytes() == before for p, before in (originals | branch_originals).items())
    # Corrupt files must also block a cached edition. Restore each exact source
    # after checking rejection; no new analysis or overwrite may conceal damage.
    for damaged in [
        source,
        primary_path,
        project.output_dir / payload["artifacts"][-1]["path"],
        ledger_path,
    ]:
        old = damaged.read_bytes()
        damaged.write_bytes(b"corrupt QA evidence")
        try:
            with pytest.raises((ValueError, KeyError, TypeError)):
                branch_publication_source(
                    project,
                    args["branch_id"],
                    args["experiment_id"],
                    args["expected_record_sha256"],
                )
        finally:
            damaged.write_bytes(old)


@pytest.mark.parametrize(
    "tamper", ["source", "figure", "record", "cases", "receipt", "plan", "required", "unknown"]
)
def test_changed_evidence_and_out_of_scope_contracts_never_fit(primary, monkeypatch, tamper):
    project, store, dataset, record, path, contract = primary
    from rde.infrastructure.clinical import survival

    monkeypatch.setattr(
        survival, "run_survival_sensitivity", lambda *a: pytest.fail("Invalid branch was fitted")
    )
    if tamper == "source":
        dataset.metadata.file_path.write_text("changed source")
    elif tamper == "figure":
        (project.output_dir / record["artifacts"][-1]["path"]).write_bytes(b"changed")
    elif tamper == "record":
        path.write_text(path.read_text() + " ")
    elif tamper in {"cases", "receipt"}:
        contract["case_set_sha256" if tamper == "cases" else "primary_receipt_sha256"] = "0" * 64
    elif tamper == "plan":
        plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        plan["analyses"][0]["execution_arguments"]["clinical_options"]["time_unit"] = "months"
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    elif tamper == "required":
        contract["required_covariates"] = ["x", "group"]
    else:
        contract["clinical_options"] = {"event_value": "C"}
    result = execute_survival_branch(project, store, contract, "testbranch", "experiment")
    assert result["status"] == "failed" and not result["executed"]
    assert json.loads(open(result["artifact_path"]).read())["error"]


def test_failed_renderer_preserves_numerical_branch_evidence(primary, monkeypatch):
    project, store, _, _, _, contract = primary
    from rde.infrastructure.clinical import report

    def broken(*a, **kw):
        raise OSError("plot renderer fixture failure")

    monkeypatch.setattr(report, "figures", broken)
    result = execute_survival_branch(project, store, contract, "branch", "experiment")
    assert result["status"] == "failed" and result["executed"]
    payload = json.loads(open(result["artifact_path"]).read())
    assert payload["analysis_result"]["status"] == "completed"
    assert payload["analysis_result"]["n"] == 300
    assert "renderer fixture failure" in payload["error"]
