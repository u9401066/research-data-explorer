"""Approved assumptions survive the catalog -> execution -> DOCX boundary."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.research_plans import execute, root, write_once
from rde.interface.mcp.research_execution import (
    RELATIVE_PATH,
    MARKER_PATH,
    REQUIRED_BINDING,
    execution_evidence,
    execution_markdown,
    preserve_execution_binding,
)
from rde.interface.mcp.tools.report_tools import (
    _build_formal_research_report,
    _build_claim_provenance_manifest,
    _formal_abstract,
    _flatten_variable_roles,
)
from test_dataframe_lineage import setup


def ref(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def fixture(tmp_path):
    project, entry = setup(tmp_path)
    session = get_session()
    session.register_project(project)
    session.register_dataset(entry.dataset, entry.dataframe)
    source = ref(entry.dataset.metadata.file_path)
    schema_path = tmp_path / "original-schema.json"
    schema_path.write_text('{"version":"catalog schema, distinct from execution schema"}')
    schema = ref(schema_path)
    catalog = Project(
        id="catalog", name="catalog", data_dir=tmp_path, output_dir=tmp_path / "catalog"
    )
    plan_id, execution_id = str(uuid4()), str(uuid4())
    protocol = {
        "question": "Compare recorded scores by original group",
        "sourceHash": source["sha256"],
        "schemaHash": schema["sha256"],
        "alpha": 0.05,
        "missingStrategy": "listwise",
        "multiplicity": "holm",
        "researchDetails": {
            "studyDesign": "不同受試者獨立是研究者指定假設；群聚依賴未驗證。",
            "population": "上傳前已指定族群，不宣稱由平台篩選。",
            "endpointTime": "基線分數；未觀測後續結果。",
        },
        "limitations": ["不推論療效；核准不是臨床驗證。"],
        "steps": [
            {
                "tool": "analyze_variable",
                "planEntry": {
                    "type": "analyze_variable",
                    "variables": ["score"],
                    "rationale": "Prespecified score",
                },
            }
        ],
    }
    reason = "研究者原文：group=0 是 reference；group=1 是 active。\n\n每列一位受試者，統計獨立性未經驗證。"
    plan = execute(
        catalog,
        dict(
            op="draft", plan_id=plan_id, protocol=protocol, sources=[source, schema], reason=reason
        ),
    )
    approval = execute(
        catalog,
        dict(
            op="approve",
            plan_id=plan_id,
            expected_sha256=plan["sha256"],
            reviewer={"kind": "agent"},
        ),
    )["approval"]
    store = ArtifactStore(project.artifacts_dir)
    intake = {
        "dataset_id": entry.dataset.id,
        "source": {**source, "filename": "original.csv", "sheet_name": None},
        "row_count": len(entry.dataframe),
        "filename": "original.csv",
    }
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", intake)
    locked = {
        "project_id": project.id,
        "research_question": protocol["question"],
        "alpha": 0.05,
        "missing_strategy": "listwise",
        "multiple_comparison_method": "holm",
        "analyses": [s["planEntry"] for s in protocol["steps"]],
        "execution_schedule": [],
        "created_at": "first registration",
        "locked": True,
    }
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", locked)
    request = dict(
        op="bind_execution",
        plan_id=plan_id,
        expected_sha256=plan["sha256"],
        execution_id=execution_id,
        dataset_id=entry.dataset.id,
        plan_file=ref(root(catalog, plan_id) / "plan.json"),
        approval_file=ref(root(catalog, plan_id) / "approval.json"),
    )
    return project, entry, store, intake, protocol, locked, request, approval


def test_approved_definition_binding_formal_docx_provenance_and_exact_replay(tmp_path):
    from docx import Document
    from rde.infrastructure.adapters.docx_exporter import DocxExporter
    from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
    from rde.interface.mcp.results import make_result, fingerprints

    project, _, store, intake, protocol, locked, request, approval = fixture(tmp_path)
    numeric = store.save(
        PipelinePhase.EXECUTE_EXPLORATION, "frozen-results.json", {"value": 2.4000000000000004}
    )
    before_numeric = numeric.read_bytes()
    first = execute(project, request)
    assert first["approval_sha256"] == approval["sha256"]
    assert first["approval_sha256"] != request["approval_file"]["sha256"]
    assert first["relative_path"] == RELATIVE_PATH
    before = fingerprints(project)
    assert execute(project, request) == first
    result = make_result("research_plan", json.dumps(first), project, before)
    assert {r.relative_path for r in result.artifacts} == {
        RELATIVE_PATH,
        MARKER_PATH,
        "artifacts/research_execution/plan.json",
        "artifacts/research_execution/approval.json",
        "artifacts/phase_06_plan_registration/analysis_plan.yaml",
    }
    locked["created_at"] = "recovery registration"
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        preserve_execution_binding(project, locked),
    )
    assert execute(project, request) == first
    # Reading a bound report does not need a live in-memory DatasetEntry.
    get_session()._datasets.clear()
    evidence = execution_evidence(project, intake)
    md = execution_markdown(evidence)
    assert "群聚依賴未驗證" in md and "研究者原文：group=0 是 reference" in md
    assert "clinical_validation：not_performed" in md
    assert request["expected_sha256"] in md
    assert request["plan_file"]["path"] not in md
    report = _build_formal_research_report(project, store, "# Bound report")
    rendered = MarkdownReportRenderer().render_markdown(report)
    assert "群聚依賴未驗證" in rendered and "group=1 是 active" in rendered
    path = tmp_path / "bound.docx"
    DocxExporter().export_docx(report, path)
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "群聚依賴未驗證" in text and "group=0 是 reference" in text
    assert "上傳前已指定族群" in text and "not_performed" in text
    claims = _build_claim_provenance_manifest(project, store, report_source="test")["claims"]
    claim = next(c for c in claims if c["claim_type"] == "approved_research_definitions")
    assert claim["confidence"] == "approved_source_statements_not_clinical_validation"
    assert first["context_sha256"] in [x["receipt_sha256"] for x in claim["evidence"]]
    assert numeric.read_bytes() == before_numeric
    assert (
        Path(request["plan_file"]["path"]).read_bytes()
        == (project.output_dir / "artifacts/research_execution/plan.json").read_bytes()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_context",
        "missing_marker",
        "missing_imported_plan",
        "missing_imported_approval",
        "all_evidence_removed",
        "required_binding_removed",
        "required_binding_changed",
        "context_tampered",
        "plan_tampered",
        "approval_tampered",
        "source_drift",
        "schema_drift",
        "intake_drift",
        "locked_methods_drift",
        "locked_schedule_drift",
        "foreign_project",
        "symlink",
    ],
)
def test_bound_reports_fail_closed_without_refitting_or_losing_old_results(tmp_path, fault):
    project, entry, store, intake, _, locked, request, _ = fixture(tmp_path)
    execute(project, request)
    base = project.artifacts_dir / "research_execution"
    if fault == "all_evidence_removed":
        import shutil

        shutil.rmtree(base)
        (project.output_dir / MARKER_PATH).unlink()
    if fault.startswith("required_binding_"):
        saved = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        if fault == "required_binding_removed":
            saved.pop(REQUIRED_BINDING)
        else:
            saved[REQUIRED_BINDING]["context_sha256"] = "0" * 64
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", saved)
    if fault.startswith("missing_"):
        target = {
            "missing_context": base / "context.json",
            "missing_marker": project.output_dir / MARKER_PATH,
            "missing_imported_plan": base / "plan.json",
            "missing_imported_approval": base / "approval.json",
        }[fault]
        target.unlink()
    if fault in ("context_tampered", "plan_tampered", "approval_tampered"):
        name = fault.removesuffix("_tampered")
        path = base / f"{name}.json"
        data = json.loads(path.read_text())
        data["payload"]["unexpected"] = True
        path.write_text(json.dumps(data))
    if fault == "source_drift":
        entry.dataset.metadata.file_path.write_text("changed")
    if fault == "schema_drift":
        (tmp_path / "original-schema.json").write_text("changed")
    if fault == "intake_drift":
        intake["dataset_id"] = "another"
    if fault.startswith("locked_"):
        if fault == "locked_methods_drift":
            locked["analyses"][0]["variables"] = ["group"]
        else:
            locked["execution_schedule"] = [{"tool_name": "different"}]
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", locked)
    if fault == "foreign_project":
        project.id = "sibling"
    if fault == "symlink":
        path = base / "plan.json"
        raw = path.read_bytes()
        path.unlink()
        external = tmp_path / "external.json"
        external.write_bytes(raw)
        path.symlink_to(external)
    if fault == "intake_drift":
        store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", intake)
    with pytest.raises(ValueError, match="RESEARCH_REPORT_EVIDENCE_INVALID"):
        execution_evidence(project, intake)
    with pytest.raises(ValueError, match="RESEARCH_REPORT_EVIDENCE_INVALID"):
        _build_formal_research_report(project, store, "# Must not silently export")


def test_re_registration_retains_requirement_and_rebind_does_not_recreate_lost_copies(tmp_path):
    import copy
    import shutil

    project, _, store, intake, _, locked, request, _ = fixture(tmp_path)
    execute(project, request)
    required = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")[REQUIRED_BINDING]
    # This is the same helper used by real register_analysis_plan. Re-registering
    # methods before recovery cannot turn a previously bound run into legacy.
    locked["created_at"] = "resume"
    resumed = preserve_execution_binding(project, locked)
    assert resumed[REQUIRED_BINDING] == required
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", resumed)
    wrong = copy.deepcopy(locked)
    wrong["analyses"][0]["variables"] = ["different"]
    with pytest.raises(ValueError, match="IMMUTABLE_RECORD"):
        preserve_execution_binding(project, wrong)
    shutil.rmtree(project.artifacts_dir / "research_execution")
    (project.output_dir / MARKER_PATH).unlink()
    with pytest.raises(ValueError, match="RESEARCH_REPORT_EVIDENCE_INVALID"):
        execution_evidence(project, intake)
    # An uncached bind is validation, not implicit repair of deleted evidence.
    with pytest.raises(ValueError, match="RESEARCH_REPORT_EVIDENCE_INVALID"):
        execute(project, request)
    assert not (project.artifacts_dir / "research_execution").exists()
    assert not (project.output_dir / MARKER_PATH).exists()


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_plan_hash",
        "wrong_file_hash",
        "wrong_approval",
        "foreign_dataset",
        "unlocked",
        "different_methods",
    ],
)
def test_binding_rejects_wrong_identity_before_committing(tmp_path, fault):
    project, _, store, _, _, locked, request, _ = fixture(tmp_path)
    if fault == "wrong_plan_hash":
        request["expected_sha256"] = "0" * 64
    if fault == "wrong_file_hash":
        request["plan_file"]["sha256"] = "0" * 64
    if fault == "wrong_approval":
        path = tmp_path / "another-approval.json"
        write_once(path, {"plan_sha256": "0" * 64, "reviewer": {"kind": "human"}})
        request["approval_file"] = ref(path)
    if fault == "foreign_dataset":
        request["dataset_id"] = "another"
    if fault == "unlocked":
        locked["locked"] = False
    if fault == "different_methods":
        locked["analyses"][0]["variables"] = ["group"]
    if fault in ("unlocked", "different_methods"):
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", locked)
    with pytest.raises(ValueError):
        execute(project, request)
    assert not (project.output_dir / RELATIVE_PATH).exists()
    assert not (project.output_dir / MARKER_PATH).exists()


def test_no_silent_rebind_to_new_execution_and_legacy_remains_unbound(tmp_path):
    project, _, store, intake, _, _, request, _ = fixture(tmp_path)
    assert execution_evidence(project, intake) is None
    report = _build_formal_research_report(project, store, "# Native unbound study")
    assert all("本次核准計畫" not in s.content for s in report.sections)
    execute(project, request)
    before = (project.output_dir / RELATIVE_PATH).read_bytes()
    with pytest.raises(ValueError, match="IMMUTABLE_RECORD"):
        execute(project, {**request, "execution_id": str(uuid4())})
    assert (project.output_dir / RELATIVE_PATH).read_bytes() == before


def test_native_role_envelope_never_reports_metadata_keys_as_variables():
    envelope = {
        "dataset": "native-id",
        "research_question": "Q",
        "analysis_scope": "inferential",
        "total_variables": 3,
        "analyzable_variables": 2,
        "variable_roles": {"status": "outcome", "trt": "group", "id": "id"},
        "outcome": ["status"],
        "confirmed": True,
        "warnings": [],
    }
    assert _flatten_variable_roles(envelope) == envelope["variable_roles"]
    text = _formal_abstract(
        None,
        {"loaded_file": "source.csv"},
        {"row_count": 20, "column_count": 3},
        {"total_analyses": 1},
        variable_roles=envelope,
    )
    assert "status、trt、id" in text
    assert all(
        k not in text
        for k in ("research_question", "total_variables", "analysis_scope", "native-id")
    )
    assert _flatten_variable_roles({"outcome": ["score"], "group": "group"}) == {
        "score": "outcome",
        "group": "group",
    }


def test_execution_binding_mcp_envelope_and_durable_replay(tmp_path):
    import asyncio
    from mcp import Client
    from rde.interface.mcp.server import create_server

    project, _, _, _, _, _, request, _ = fixture(tmp_path)

    async def run():
        async with Client(create_server()) as client:
            first = await client.call_tool(
                "research_plan",
                {"project_id": project.id, "request": request, "execution_key": "1" * 64},
            )
            assert not first.is_error, first.content
            data = first.structured_content
            assert data["data"]["schema"] == "rde-research-execution-context-v1"
            paths = [r["relative_path"] for r in data["artifacts"]]
            assert any(p.endswith("/artifacts/research_execution/context.json") for p in paths)
            assert any(
                p.endswith("/artifacts/phase_06_plan_registration/research_execution.json")
                for p in paths
            )
            second = await client.call_tool(
                "research_plan",
                {"project_id": project.id, "request": request, "execution_key": "1" * 64},
            )
            assert not second.is_error
            assert second.structured_content == data

    asyncio.run(run())


def test_real_register_checkpoint_stays_immutable_when_binding_pins_live_plan(tmp_path):
    import asyncio
    from mcp import Client
    from rde.application.pipeline import REQUIRED_ARTIFACTS
    from rde.interface.mcp.server import create_server
    from test_exploration_branch_loop import _complete_phase

    project, _, store, _, protocol, _, request, _ = fixture(tmp_path)
    project.research_question = protocol["question"]
    pipeline = get_session().get_pipeline(project.id)
    for phase in list(PipelinePhase)[:5]:
        files = {}
        for name in REQUIRED_ARTIFACTS[phase]:
            existing = store.load(phase, name)
            files[name] = (
                existing
                if existing is not None
                else ({"confirmed": True} if name.endswith((".json", ".yaml")) else "")
            )
        pipeline.mark_completed(_complete_phase(store, phase, files, user_confirmed=True))
    args = dict(
        project_id=project.id,
        analyses=[s["planEntry"] for s in protocol["steps"]],
        alpha=protocol["alpha"],
        missing_strategy=protocol["missingStrategy"],
        multiple_comparison_method=protocol["multiplicity"],
        allow_methodology_override=True,
        confirm=True,
        execution_key="2" * 64,
    )

    async def run():
        async with Client(create_server()) as client:
            registered = await client.call_tool("register_analysis_plan", args)
            assert not registered.is_error, registered.content
            register_data = registered.structured_content
            saved_ref = next(
                r
                for r in register_data["artifacts"]
                if r["relative_path"].endswith("/analysis_plan.yaml")
            )
            saved_path = project.output_dir / saved_ref["relative_path"]
            saved_bytes = saved_path.read_bytes()
            assert hashlib.sha256(saved_bytes).hexdigest() == saved_ref["sha256"]
            locked = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            # The approved protocol exactly adopts the actual registered method
            # list; this test checks receipt lifecycle, not a statistical result.
            catalog = Project(
                id="new-catalog",
                name="catalog",
                data_dir=tmp_path,
                output_dir=tmp_path / "new-catalog",
            )
            original = json.loads(Path(request["plan_file"]["path"]).read_text())["payload"]
            adopted = {**protocol, "steps": [{"planEntry": a} for a in locked["analyses"]]}
            plan_id = str(uuid4())
            plan = execute(
                catalog,
                dict(
                    op="draft",
                    plan_id=plan_id,
                    protocol=adopted,
                    sources=original["sources"],
                    reason=original["reason"],
                ),
            )
            execute(
                catalog,
                dict(
                    op="approve",
                    plan_id=plan_id,
                    expected_sha256=plan["sha256"],
                    reviewer={"kind": "agent"},
                ),
            )
            bind_request = {
                **request,
                "plan_id": plan_id,
                "expected_sha256": plan["sha256"],
                "plan_file": ref(root(catalog, plan_id) / "plan.json"),
                "approval_file": ref(root(catalog, plan_id) / "approval.json"),
            }
            bound = await client.call_tool(
                "research_plan", {"project_id": project.id, "request": bind_request}
            )
            assert not bound.is_error, bound.content
            current = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            assert (
                current[REQUIRED_BINDING]["context_sha256"]
                == bound.structured_content["data"]["context_sha256"]
            )
            assert saved_path.read_bytes() == saved_bytes
            replay = await client.call_tool("register_analysis_plan", args)
            assert not replay.is_error and replay.structured_content == register_data
            assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") == current
            assert saved_path.read_bytes() == saved_bytes

    asyncio.run(run())
