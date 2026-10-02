"""Real MCP planning gates, immutable output, interrupted attempts and restart."""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from rde.application.session import get_session
from rde.infrastructure.clinical import sample_size_workflow as workflow
from rde.interface.mcp.server import create_server
from test_sample_size_planning import planning_spec


def tool(name, arguments, *, error=False):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert response.is_error is error, response.content
    text = response.content[0].text
    if error or name == "init_project":
        return text
    return json.loads(text)


def draft(design="independent_means"):
    tool(
        "init_project",
        {"name": "Prospective planning QA", "research_question": "Synthetic reference only"},
    )
    project = get_session().get_project()
    plan_id = str(uuid.uuid4())
    result = tool(
        "draft_sample_size_plan",
        {
            "project_id": project.id,
            "plan_id": plan_id,
            "planning_options": planning_spec(design).to_dict(),
        },
    )
    return project, result


def approval(project, plan):
    return tool(
        "approve_sample_size_plan",
        {
            "project_id": project.id,
            "plan_id": plan["plan_id"],
            "expected_plan_sha256": plan["receipt_sha256"],
            "review": {
                "reviewer": "Engineering QA",
                "note": "User-authorized synthetic reference workflow; not a clinical recommendation.",
                "confirmations": {key: True for key in workflow.CONFIRMATIONS},
            },
        },
    )


def execution(project, plan, approved):
    return {
        "project_id": project.id,
        "plan_id": plan["plan_id"],
        "expected_plan_sha256": plan["receipt_sha256"],
        "expected_approval_sha256": approved["receipt_sha256"],
        "run_id": str(uuid.uuid4()),
    }


@pytest.mark.parametrize("design", ["independent_means", "paired_means", "independent_proportions"])
def test_full_mcp_plan_reports_restart_no_fake_patient_dataset(tmp_path, monkeypatch, design):
    project, plan = draft(design)
    pipeline_before = deepcopy(get_session().get_pipeline(project.id).summary())
    plan_dir = workflow.plan_directory(project, plan["plan_id"])
    # No calculation is allowed before the complete review is read and approved.
    assert not (plan_dir / "runs").exists()
    view = tool("get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]})
    assert "假設來源" in view["review_markdown"] and view["approval"] is None
    denied = tool(
        "run_sample_size_plan", execution(project, plan, {"receipt_sha256": "0" * 64}), error=True
    )
    assert "approval.json" in denied and not (plan_dir / "runs").exists()
    approved = approval(project, plan)
    args = execution(project, plan, approved)
    wrong = {**args, "expected_approval_sha256": "0" * 64}
    assert "expected SHA256" in tool("run_sample_size_plan", wrong, error=True)
    run = tool("run_sample_size_plan", args)
    assert run["status"] == "completed"
    assert len(run["figures"]) == 2 and len(run["artifacts"]) == 17
    assert get_session().get_pipeline(project.id).summary() == pipeline_before
    assert project.dataset_ids == [] and get_session().list_datasets() == []
    report = (project.output_dir / run["report_path"]).read_text(encoding="utf-8")
    assert "前瞻設計計算" in report and "事後 power" in report and "Figure 2" in report
    numeric = json.loads((project.output_dir / run["result_path"]).read_text())
    assert numeric["spec"] == plan["spec"]
    assert all(
        set(f["publication"]["files"]) == {"png", "svg", "pdf", "tiff", "caption", "data"}
        for f in run["figures"]
    )
    before = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in plan_dir.rglob("*")
        if path.is_file()
    }
    # New server/session must load saved approvals and exact output; no refit or rewrite.
    import rde.application.session as session_module

    session_module._session = None
    monkeypatch.setattr(
        workflow.engine,
        "calculate_sample_size",
        lambda _: pytest.fail("recalculated immutable result"),
    )
    assert tool("run_sample_size_plan", args) == run
    restored = tool("get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]})
    assert restored["runs"] == [run] and restored["approval"] == approved
    assert {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in plan_dir.rglob("*")
        if path.is_file()
    } == before
    assert get_session().get_project(project.id).dataset_ids == []
    # Changed output cannot be returned as valid or overwritten by a retry.
    Path(run["figures"][0]["path"]).write_bytes(b"damaged")
    assert "integrity" in tool("run_sample_size_plan", args, error=True)
    assert "integrity" in tool(
        "get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]}, error=True
    )


def test_foreign_plan_changed_review_stale_hash_and_missing_confirmation_are_rejected():
    project, plan = draft()
    args = {
        "project_id": project.id,
        "plan_id": plan["plan_id"],
        "expected_plan_sha256": "0" * 64,
        "review": {"reviewer": "QA", "note": "Synthetic QA", "confirmations": {}},
    }
    assert "reviewed SHA256" in tool("approve_sample_size_plan", args, error=True)
    args["expected_plan_sha256"] = plan["receipt_sha256"]
    assert "explicitly confirmed" in tool("approve_sample_size_plan", args, error=True)
    options = {**plan["spec"], "alpha": 0.01}
    assert "different assumptions" in tool(
        "draft_sample_size_plan",
        {"project_id": project.id, "plan_id": plan["plan_id"], "planning_options": options},
        error=True,
    )
    other_project, _ = draft()
    tool(
        "get_sample_size_plan",
        {"project_id": other_project.id, "plan_id": plan["plan_id"]},
        error=True,
    )
    review = workflow.plan_directory(project, plan["plan_id"]) / "review.md"
    review.write_text("different review")
    assert "integrity" in tool("approve_sample_size_plan", args, error=True)


def test_interrupted_attempt_preserves_partial_evidence_and_requires_new_id(monkeypatch):
    project, plan = draft()
    approved = approval(project, plan)
    args = execution(project, plan, approved)
    real_figures = workflow.figures

    def interrupted(*_):
        raise OSError("Synthetic renderer interruption")

    monkeypatch.setattr(workflow, "figures", interrupted)
    assert "Synthetic renderer interruption" in tool("run_sample_size_plan", args, error=True)
    directory = workflow.run_directory(
        workflow.plan_directory(project, plan["plan_id"]), args["run_id"]
    )
    assert (directory / "result.json").is_file() and not (directory / "run.json").exists()
    old_result = (directory / "result.json").read_bytes()
    assert "unfinished or failed" in tool("run_sample_size_plan", args, error=True)
    monkeypatch.setattr(workflow, "figures", real_figures)
    completed = tool("run_sample_size_plan", {**args, "run_id": str(uuid.uuid4())})
    assert (
        completed["status"] == "completed"
        and (directory / "result.json").read_bytes() == old_result
    )
    records = tool("get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]})[
        "runs"
    ]
    assert sorted(r["status"] for r in records) == ["completed", "failed"]
    log = [
        json.loads(line)
        for line in (workflow.planning_root(project) / "decision_log.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [r["action"] for r in log] == [
        "sample_size_drafted",
        "sample_size_approved",
        "sample_size_started",
        "sample_size_failed",
        "sample_size_started",
        "sample_size_completed",
    ]


def test_plan_path_traversal_and_external_symlink_are_rejected(tmp_path):
    project, plan = draft()
    tool("get_sample_size_plan", {"project_id": project.id, "plan_id": "../../escape"}, error=True)
    directory = workflow.plan_directory(project, plan["plan_id"])
    outside = tmp_path / "outside.json"
    outside.write_text("preserve me")
    (directory / "approval.json").symlink_to(outside)
    assert "Symlinked" in tool(
        "get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]}, error=True
    )
    assert outside.read_text() == "preserve me"


def test_unfinished_run_listing_cannot_follow_redirected_parent(tmp_path):
    project, plan = draft()
    external = tmp_path / "external-runs"
    failed = external / str(uuid.uuid4())
    failed.mkdir(parents=True)
    (failed / "failure.json").write_text('{"message":"foreign evidence"}')
    (workflow.plan_directory(project, plan["plan_id"]) / "runs").symlink_to(external)
    assert "may not be redirected" in tool(
        "get_sample_size_plan", {"project_id": project.id, "plan_id": plan["plan_id"]}, error=True
    )
    assert (failed / "failure.json").read_text() == '{"message":"foreign evidence"}'


@pytest.mark.parametrize(
    "preset", ["journal-neutral-english-v1", "nature-single-v1", "plos-column-v1"]
)
def test_publication_edition_uses_saved_numbers_and_retains_edited_captions(monkeypatch, preset):
    if preset != "journal-neutral-english-v1":
        if not os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"):
            pytest.skip("Authorized local Arial required")
        monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    project, plan = draft("paired_means")
    run = tool("run_sample_size_plan", execution(project, plan, approval(project, plan)))
    frozen = {r["path"]: (project.output_dir / r["path"]).read_bytes() for r in run["artifacts"]}
    monkeypatch.setattr(
        workflow.engine, "calculate_sample_size", lambda _: pytest.fail("recalculated for display")
    )
    args = {
        "project_id": project.id,
        "plan_id": plan["plan_id"],
        "run_id": run["run_id"],
        "expected_run_sha256": run["receipt_sha256"],
        "edition_id": str(uuid.uuid4()),
        "preset_id": preset,
        "start_number": 11,
        "captions": {
            "1": {
                "caption_en": "Prespecified synthetic planning example; no patient data were analyzed.",
                "explanation_zh": "合成規劃驗證，未分析病人資料。",
            }
        },
    }
    edition = tool("render_sample_size_publication", args)
    assert edition["source_dataset_id"] is None and edition["source_plan_id"] == plan["plan_id"]
    assert len(edition["artifacts"]) == 13
    assert edition["figures"][0]["publication"]["figure_number"] == 11
    assert "no patient data" in edition["figures"][0]["publication"]["caption_en"]
    for original, current in zip(run["figures"], edition["figures"], strict=True):
        assert (
            original["publication"]["original_caption"]
            == current["publication"]["original_caption"]
        )
        assert (
            Path(original["publication"]["files"]["data"]).read_bytes()
            == Path(current["publication"]["files"]["data"]).read_bytes()
        )
    import rde.application.session as session_module

    session_module._session = None
    assert tool("render_sample_size_publication", args) == edition
    assert all((project.output_dir / p).read_bytes() == value for p, value in frozen.items())
    assert "another rendering request" in tool(
        "render_sample_size_publication", {**args, "start_number": 12}, error=True
    )
    assert "expected SHA256" in tool(
        "render_sample_size_publication", {**args, "expected_run_sha256": "0" * 64}, error=True
    )
