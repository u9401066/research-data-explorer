"""Source/approval/restart edges through MCP; independent R checks run via smoke."""

import asyncio
import csv
import json
import uuid
import shutil
from zipfile import ZipFile
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path

import openpyxl
import pytest

from rde.application.session import get_session
from rde.domain.models.evidence_arms import BinaryArmSpec
from rde.infrastructure.evidence import arm_preparation as engine
from rde.infrastructure.evidence import arm_source
from rde.infrastructure.evidence import arm_workflow as workflow
from rde.interface.mcp.server import create_server

FIXTURES = Path(__file__).parent / "fixtures/evidence-arms"


def spec():
    return json.loads((FIXTURES / "spec.json").read_text())


def call(arguments, error=False):
    response = asyncio.run(create_server().call_tool("evidence_arm_preparation", arguments))
    assert response.is_error is error, response.content
    return response.content[0].text if error else json.loads(response.content[0].text)


def setup(options=None, source_bytes=None):
    asyncio.run(
        create_server().call_tool(
            "init_project",
            {"name": "Synthetic arms QA", "research_question": "Software verification only"},
        )
    )
    project = get_session().get_project()
    identity = {"project_id": project.id}
    prep = str(uuid.uuid4())
    incoming = project.output_dir / "incoming/evidence-arms" / prep / "source.csv"
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(
        source_bytes if source_bytes is not None else (FIXTURES / "source.csv").read_bytes()
    )
    request = {
        "op": "draft",
        "preparation_id": prep,
        "filename": incoming.name,
        "source_sha256": workflow.w.file_hash(incoming),
        "specification": options or spec(),
    }
    plan = call({**identity, "request": request})
    return project, identity, request, plan


def approve(identity, request, plan, error=False):
    return call(
        {
            **identity,
            "request": {
                "op": "approve",
                "preparation_id": request["preparation_id"],
                "expected_plan_sha256": plan["receipt_sha256"],
                "review": {
                    "reviewer": "Authorized engineering QA",
                    "note": "Synthetic assumptions reviewed; not clinical approval.",
                    "confirmations": {name: True for name in plan["required_confirmations"]},
                },
            },
        },
        error=error,
    )


def execute_request(request, plan, approval):
    return {
        "op": "execute",
        "preparation_id": request["preparation_id"],
        "expected_plan_sha256": plan["receipt_sha256"],
        "expected_approval_sha256": approval["receipt_sha256"],
        "run_id": str(uuid.uuid4()),
    }


def test_mcp_review_approval_run_paging_and_immutable_replay(monkeypatch):
    project, identity, request, plan = setup()
    assert plan["ready_for_approval"] and plan["summary"]["planned_contrasts"] == 4
    assert plan["summary"]["source_rows"] == 11 and plan["summary"]["excluded_studies"] == 2
    assert call({**identity, "request": request}) == plan
    denied = execute_request(request, plan, {"receipt_sha256": "0" * 64})
    call({**identity, "request": denied}, error=True)
    approval = approve(identity, request, plan)
    assert approve(identity, request, plan) == approval
    run_request = execute_request(request, plan, approval)
    run = call({**identity, "request": run_request})
    full = ""
    page_request = {
        "op": "read",
        "preparation_id": request["preparation_id"],
        "part": "result",
        "run_id": run["run_id"],
        "text_limit": 701,
    }
    while True:
        page = call({**identity, "request": page_request})
        full += page["text_excerpt"]
        if page["next_text_offset"] is None:
            break
        page_request.update(
            text_offset=page["next_text_offset"], expected_text_sha256=page["text_sha256"]
        )
    assert workflow.w.sha(full.encode()) == page["text_sha256"]
    result = json.loads(full)
    assert len(result["contrasts"]) == 4
    assert result["derivations"][0]["arms"][0]["events"] == "5.5"
    assert result["derivations"][0]["arms"][0]["source_rows"] == [3, 4]
    assert result["derivations"][0]["arms"][0]["corrected_events"] == "6.0"
    assert all(a["corrected_total"] != a["total"] for a in result["derivations"][0]["arms"])
    # Shared-arm algebra: the three paired effects close exactly within rounding.
    ab, ac, bc = result["contrasts"][:3]
    assert ab["effect"] + bc["effect"] == pytest.approx(ac["effect"], abs=1e-14)
    monkeypatch.setattr(
        engine, "calculate", lambda *_: pytest.fail("Completed replay must not calculate")
    )
    assert call({**identity, "request": run_request}) == run
    assert project.dataset_ids == []
    page_request["expected_text_sha256"] = "0" * 64
    call({**identity, "request": page_request}, error=True)
    (project.output_dir / run["contrast_path"]).write_text("tampered\n")
    assert "arm evidence file size changed" in call(
        {**identity, "request": run_request}, error=True
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("merge_policy", "reject", "merge_not_approved"),
        ("zero_cells", "reject", "zero_cells"),
        ("fractional_events", "reject", "invalid_counts"),
        ("uninformative_studies", "reject", "uninformative_study"),
        ("insufficient_treatments", "reject", "insufficient_treatments"),
    ],
)
def test_unresolved_policy_cannot_be_approved(field, value, code):
    options = spec()
    options[field] = value
    project, identity, request, plan = setup(options)
    assert not plan["ready_for_approval"]
    reviewed = workflow.w.load_json(
        workflow.directory(project, request["preparation_id"]) / "review.json"
    )
    assert code in {e["code"] for e in reviewed["errors"]}
    assert "resolve source review errors" in approve(identity, request, plan, error=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("independent_parallel_arms", 1),
        ("independent_parallel_arms", False),
        ("outcome", " "),
        ("unmentioned_default", True),
        (
            "missing_codes",
            [{"value": "", "meaning": "blank"}, {"value": "0", "meaning": "missing"}],
        ),
    ],
)
def test_strict_spec_does_not_coerce_or_silently_default(field, value):
    options = spec()
    options[field] = value
    with pytest.raises(ValueError):
        BinaryArmSpec.model_validate(options)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("duplicate", "duplicate_arm"),
        ("denominator", "invalid_counts"),
        ("flag", "unknown_imputation"),
        ("fraction_without_flag", "invalid_counts"),
        ("unknown_treatment", "unknown_treatment"),
        ("metadata", "inconsistent_metadata"),
    ],
)
def test_raw_arm_edges_retain_source_and_stop(mutation, code):
    options = BinaryArmSpec.model_validate(spec())
    grid = arm_source.source_grid((FIXTURES / "source.csv").read_bytes(), "source.csv", options)
    if mutation == "duplicate":
        grid["rows"][3][1] = "A.low"
    elif mutation == "denominator":
        grid["rows"][2][4] = "2"
    elif mutation == "flag":
        grid["rows"][2][5] = ""
    elif mutation == "fraction_without_flag":
        grid["rows"][2][5] = "0"
    elif mutation == "unknown_treatment":
        grid["rows"][2][2] = "unreviewed"
    else:
        grid["rows"][2][6] = "another report"
    reviewed = engine.review(grid, options)
    assert not reviewed["ready_for_approval"] and code in {e["code"] for e in reviewed["errors"]}
    assert reviewed["arms"][4]["missing"]["events"] == "Not available in source."
    with pytest.raises(ValueError, match="Unresolved"):
        engine.calculate(reviewed, options)


def test_xlsx_multilevel_headers_exact_cells_formula_and_merge_guards():
    options = spec()
    options["sheet"] = "DATA"
    parsed = BinaryArmSpec.model_validate(options)
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "DATA"
    for row in csv.reader(StringIO((FIXTURES / "source.csv").read_text())):
        sheet.append(row)
    sheet.merge_cells("A1:G1")
    data = BytesIO()
    book.save(data)
    grid = arm_source.source_grid(data.getvalue(), "source.xlsx", parsed)
    assert engine.review(grid, parsed)["ready_for_approval"]
    assert grid["rows"][2][3] == "2.5"
    sheet["D3"] = "=2.5"
    sheet.merge_cells("F8:F9")
    data = BytesIO()
    book.save(data)
    reviewed = engine.review(arm_source.source_grid(data.getvalue(), "source.xlsx", parsed), parsed)
    assert {"formula_cell", "merged_cell"} <= {e["code"] for e in reviewed["errors"]}


def test_csv_blank_records_and_embedded_newlines_keep_logical_coordinates():
    options = spec()
    options.update(first_data_row=1, last_data_row=3)
    grid = arm_source.source_grid(
        b'"first\nline",x\n\nlast,z\n', "source.csv", BinaryArmSpec.model_validate(options)
    )
    assert grid["rows"] == [["first\nline", "x"], ["", ""], ["last", "z"]]
    assert grid["csv_record_end_lines"] == [2, 3, 4]


def test_xlsx_numeric_lexical_precision_survives_without_float_rounding():
    options = spec()
    options.update(sheet="DATA", first_data_row=1, last_data_row=1)
    book = openpyxl.Workbook()
    book.active.title = "DATA"
    book.active["A1"] = 1.25
    original, rewritten = BytesIO(), BytesIO()
    book.save(original)
    precise = "1.23456789012345678901"
    with ZipFile(original) as source, ZipFile(rewritten, "w") as target:
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<v>1.25</v>", ("<v>" + precise + "</v>").encode())
            target.writestr(member, data)
    grid = arm_source.source_grid(
        rewritten.getvalue(), "source.xlsx", BinaryArmSpec.model_validate(options)
    )
    assert grid["rows"][0][0] == precise
    assert grid["worksheet_part"] == "xl/worksheets/sheet1.xml"


def test_unadjudicated_real_source_vocabulary_is_a_draft_not_an_exclusion():
    options = spec()
    for treatment in options["treatments"]:
        treatment.update(decision="unresolved", reason="Source eligibility not yet adjudicated.")
    parsed = BinaryArmSpec.model_validate(options)
    reviewed = engine.review(
        arm_source.source_grid((FIXTURES / "source.csv").read_bytes(), "source.csv", parsed), parsed
    )
    assert not reviewed["ready_for_approval"]
    assert reviewed["summary"]["included_studies"] == 0
    assert reviewed["summary"]["excluded_studies"] == 0
    assert reviewed["summary"]["arm_decisions"] == {"unresolved": 11}
    assert all(study["decision"] == "unresolved" for study in reviewed["studies"])
    assert sum(error["code"] == "unresolved_eligibility" for error in reviewed["errors"]) == 11


@pytest.mark.parametrize(
    "problem", ["source", "symlink", "changed_implementation", "partial_run", "failed_run"]
)
def test_immutable_source_and_failed_attempt_guards(problem, monkeypatch):
    project, identity, request, plan = setup()
    approval = approve(identity, request, plan)
    run_request = execute_request(request, plan, approval)
    root = workflow.directory(project, request["preparation_id"])
    if problem == "source":
        (root / "source/source.csv").write_text("changed")
    elif problem == "symlink":
        (root / "source/source.csv").rename(root / "original.csv")
        (root / "source/source.csv").symlink_to(root / "original.csv")
    elif problem == "changed_implementation":
        monkeypatch.setattr(workflow, "implementation", dict)
    elif problem == "partial_run":
        (root / "runs" / run_request["run_id"]).mkdir(parents=True)
    else:

        def fail(*_):
            raise ValueError("Injected engineering failure")

        monkeypatch.setattr(engine, "calculate", fail)
    call({**identity, "request": run_request}, error=True)
    if problem == "failed_run":
        failure = root / "runs" / run_request["run_id"] / "failure.json"
        assert failure.is_file()
        original = failure.read_bytes()
        assert "failed or interrupted" in call({**identity, "request": run_request}, error=True)
        assert failure.read_bytes() == original


def test_contract_and_request_reject_path_and_unknown_parameters():
    contract_result = call({"project_id": "", "request": {"op": "contract"}})
    assert contract_result["request_schema"]["discriminator"]["propertyName"] == "op"
    _, identity, request, _ = setup()
    changed = deepcopy(request)
    changed["filename"] = "../source.csv"
    call({**identity, "request": changed}, error=True)
    request["unexpected"] = True
    call({**identity, "request": request}, error=True)


def test_inspection_requires_no_clinical_decisions_and_pins_every_source_page():
    project, identity, request, _ = setup()
    root = workflow.directory(project, request["preparation_id"])
    original = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    inspection = {
        "op": "inspect",
        "preparation_id": request["preparation_id"],
        "filename": request["filename"],
        "source_sha256": request["source_sha256"],
        "selection": {"sheet": None},
        "text_limit": 257,
    }
    whole = ""
    while True:
        page = call({**identity, "request": inspection})
        whole += page["text_excerpt"]
        if page["next_text_offset"] is None:
            break
        inspection.update(
            text_offset=page["next_text_offset"], expected_text_sha256=page["text_sha256"]
        )
    assert workflow.w.sha(whole.encode()) == page["text_sha256"]
    assert json.loads(whole)["rows"][2][3] == "2.5"
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == original
    unpinned = {k: v for k, v in inspection.items() if k != "expected_text_sha256"}
    assert "Continuation requires" in call({**identity, "request": unpinned}, error=True)
    incoming = (
        project.output_dir
        / "incoming/evidence-arms"
        / request["preparation_id"]
        / request["filename"]
    )
    incoming.write_text("different source")
    assert "source differs" in call({**identity, "request": inspection}, error=True)


def portable_source(tmp_path):
    from rde.infrastructure.evidence.arm_lineage import PREFIX

    project, identity, request, plan = setup()
    approval = approve(identity, request, plan)
    run_request = execute_request(request, plan, approval)
    run = call({**identity, "request": run_request})
    original = workflow.directory(project, request["preparation_id"])
    directory = tmp_path / "portable-source"
    relative = original.relative_to(project.output_dir)
    copied = directory / PREFIX / relative
    shutil.copytree(original, copied)
    data = (copied / "runs" / run["run_id"] / "contrasts.csv").read_bytes()
    origin = {
        "contract": "workbench-arm-source-v1",
        "projectId": str(uuid.uuid4()),
        "sourceDatasetId": str(uuid.uuid4()),
        "preparationId": request["preparation_id"],
        "runId": run["run_id"],
        "nativeProjectId": project.id,
        "sourceHash": request["source_sha256"],
        "planSha256": plan["receipt_sha256"],
        "approvalSha256": approval["receipt_sha256"],
        "runSha256": run["receipt_sha256"],
        "contrastSha256": workflow.w.sha(data),
    }
    (directory / "source").mkdir()
    (directory / "source/data.csv").write_bytes(data)
    (directory / "source-schema.json").write_text(json.dumps({"armOrigin": origin}))
    table = list(csv.reader(StringIO(data.decode(), newline="")))
    (directory / "source-table.json").write_text(
        json.dumps({"columns": table[0], "rows": table[1:]})
    )
    files = {
        p.relative_to(directory).as_posix(): {
            "sha256": workflow.w.file_hash(p),
            "bytes": p.stat().st_size,
        }
        for p in directory.rglob("*")
        if p.is_file()
    }
    bundle = {
        "identity": {"project_id": origin["projectId"], "dataset_id": str(uuid.uuid4())},
        "source": {
            "file": "source/data.csv",
            "sha256": origin["contrastSha256"],
            "sheet": None,
            "arm_origin": origin,
        },
        "files": files,
    }
    options = {k: request["specification"][k] for k in ("measure", "outcome", "timepoint")}
    options["independentParallelTrials"] = True
    return directory, copied, original, bundle, options


def test_portable_arm_source_recovers_without_original_workspace_or_recalculation(
    tmp_path, monkeypatch
):
    from rde.infrastructure.evidence.arm_lineage import verify

    directory, _, original, bundle, options = portable_source(tmp_path)
    shutil.rmtree(original)

    def denied(*args, **kwargs):
        raise AssertionError(
            "portable source verification must not recalculate or parse the original source"
        )

    monkeypatch.setattr(engine, "calculate", denied)
    monkeypatch.setattr(arm_source, "source_grid", denied)
    assert verify(bundle, directory, options) == bundle["source"]["arm_origin"]


@pytest.mark.parametrize(
    "problem",
    [
        "schema_origin",
        "omitted_origin",
        "other_project",
        "same_dataset",
        "endpoint",
        "scale",
        "table",
        "original_bytes",
        "missing_member",
        "extra_member",
        "approval",
        "run_identity",
    ],
)
def test_portable_arm_source_rejects_broken_or_relabelled_lineage(tmp_path, problem):
    from rde.infrastructure.evidence.arm_lineage import verify

    directory, root, _, bundle, options = portable_source(tmp_path)
    origin = bundle["source"]["arm_origin"]
    if problem == "schema_origin":
        (directory / "source-schema.json").write_text("{}")
    elif problem == "omitted_origin":
        (directory / "source-schema.json").write_text("{}")
        bundle["source"].pop("arm_origin")
    elif problem == "other_project":
        bundle["identity"]["project_id"] = str(uuid.uuid4())
    elif problem == "same_dataset":
        bundle["identity"]["dataset_id"] = origin["sourceDatasetId"]
    elif problem == "endpoint":
        options["outcome"] = "other endpoint"
    elif problem == "scale":
        options["measure"] = "RR"
    elif problem == "table":
        (directory / "source-table.json").write_text('{"columns": [], "rows": []}')
    elif problem == "original_bytes":
        (root / "source/source.csv").write_text("changed original")
    elif problem == "missing_member":
        name = next(n for n in bundle["files"] if n.endswith("/grid.json"))
        del bundle["files"][name]
    elif problem == "extra_member":
        path = root / "runs" / str(uuid.uuid4()) / "unexpected.txt"
        path.parent.mkdir()
        path.write_text("unrelated attempt")
        bundle["files"][path.relative_to(directory).as_posix()] = {
            "sha256": workflow.w.file_hash(path),
            "bytes": path.stat().st_size,
        }
    elif problem == "approval":
        (root / "approval.json").write_text("{}")
    elif problem == "run_identity":
        path = root / "runs" / origin["runId"] / "result-receipt.json"
        record = json.loads(path.read_text())
        record["project_id"] = "12345678"
        record.pop("receipt_sha256")
        record = workflow.w.sealed(record)
        path.write_text(json.dumps(record))
        origin["runSha256"] = record["receipt_sha256"]
        (directory / "source-schema.json").write_text(json.dumps({"armOrigin": origin}))
    with pytest.raises((ValueError, OSError)):
        verify(bundle, directory, options)


def study_field(name="population", value="Synthetic reviewed population"):
    return {
        "field": name,
        "value": value,
        "reason": "Explicit synthetic source review, not a clinical determination.",
        "evidence": {
            "source": "synthetic://study-record-qa",
            "locator": "Appendix page 8, trial table row 2",
            "sha256": "a" * 64,
        },
    }


def study_record(raw="s1", identity="Reviewed-1"):
    return {
        "source_study": raw,
        "study_id": identity,
        "reason": "Explicit correspondence; preserve original name and coordinates.",
        "fields": [study_field()],
    }


def test_per_study_source_review_retains_raw_identity_and_context_through_mcp(monkeypatch):
    raw_id = "  Long source trial " + "x" * 100 + "\nsecond line  "
    rows = list(csv.reader(StringIO((FIXTURES / "source.csv").read_text())))
    for row in rows[2:7]:
        row[0] = raw_id
        row[6] = raw_id
    serialized = StringIO(newline="")
    csv.writer(serialized).writerows(rows)
    source_bytes = serialized.getvalue().encode()
    options = spec()
    record = study_record(raw_id)
    record["fields"].extend(
        [
            study_field("report_id", "Reviewed report 1"),
            study_field("endpoint_timepoint", "8 weeks, source endpoint"),
            study_field("trial_duration", "10 weeks, includes a run-in period"),
            study_field("risk_domains", "Stated but not tested; retained original wording"),
        ]
    )
    options["study_records"] = [record]
    project, identity, request, plan = setup(options, source_bytes)
    assert plan["ready_for_approval"]
    root = workflow.directory(project, request["preparation_id"])
    grid = workflow.w.load_json(root / "grid.json")
    review = workflow.w.load_json(root / "review.json")
    saved_plan = workflow.w.load_json(root / "plan.json")
    assert saved_plan["specification"]["study_records"] == [record]
    assert grid["rows"][2][0] == raw_id
    arm = review["arms"][0]
    assert arm["raw"]["study"] == raw_id
    assert arm["coordinates"]["study"] == {"row": 3, "column": 1}
    assert arm["study_id"] == "Reviewed-1"
    assert arm["original_metadata"]["report_id"] == raw_id
    assert arm["metadata"]["report_id"] == "Reviewed report 1"
    assert (
        arm["metadata_sources"]["population"]["external_source_verification"]
        == "reviewer_provided_not_verified_by_executor"
    )
    assert review["arms"][5]["metadata"]["population"] == options["metadata"]["population"]["value"]
    assert "trial_duration" not in arm["metadata"]
    assert arm["study_record"]["fields"] == record["fields"]
    approval = approve(identity, request, plan)
    run_request = execute_request(request, plan, approval)
    run = call({**identity, "request": run_request})
    result = workflow.w.load_json(root / "runs" / run["run_id"] / "result.json")
    assert result["derivations"][0]["source_study_id"] == raw_id
    assert result["derivations"][0]["study_record"] == record
    assert result["contrasts"][0]["study_id"] == "Reviewed-1"
    assert result["contrasts"][0]["population"] == record["fields"][0]["value"]
    assert result["contrasts"][0]["timepoint"] == options["timepoint"]
    assert result["summary"]["planned_contrasts"] == 4
    snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        engine, "calculate", lambda *_: pytest.fail("Do not recalculate saved review")
    )
    assert call({**identity, "request": run_request}) == run
    assert snapshot == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("target", ["s2", "s4"])
def test_study_identity_collision_never_merges_included_or_excluded_trials(target):
    options = spec()
    options["study_records"] = [study_record(identity=target)]
    project, identity, request, plan = setup(options)
    review = workflow.w.load_json(
        workflow.directory(project, request["preparation_id"]) / "review.json"
    )
    assert "study_identity_collision" in {e["code"] for e in review["errors"]}
    assert [s["source_study_id"] for s in review["studies"]] == ["s1", "s2", "s3", "s4"]
    assert review["studies"][0]["source_rows"] == [3, 4, 5, 6, 7]
    assert not plan["ready_for_approval"]
    assert "resolve source review errors" in approve(identity, request, plan, error=True)


@pytest.mark.parametrize(
    "case,code",
    [
        ("whitespace", "unknown_study_record"),
        ("missing_raw", "missing_study_record"),
        ("missing_reviewed", "invalid_identity"),
    ],
)
def test_study_identity_requires_exact_present_nonmissing_source(case, code):
    options = spec()
    options["study_records"] = [study_record()]
    if case == "whitespace":
        options["study_records"][0]["source_study"] = " s1 "
    elif case == "missing_raw":
        options["missing_codes"].append({"value": "s1", "meaning": "Missing trial identity"})
    else:
        options["study_records"][0]["study_id"] = "*"
    parsed = BinaryArmSpec.model_validate(options)
    grid = arm_source.source_grid((FIXTURES / "source.csv").read_bytes(), "source.csv", parsed)
    review = engine.review(grid, parsed)
    assert code in {e["code"] for e in review["errors"]}
    assert not review["ready_for_approval"]


@pytest.mark.parametrize("case", ["source", "id", "field", "url", "hash", "locator", "trim"])
def test_study_record_schema_rejects_ambiguous_or_incomplete_citations(case):
    options = spec()
    record = study_record()
    options["study_records"] = [record]
    if case == "source":
        options["study_records"].append(study_record(identity="Another-ID"))
    elif case == "id":
        options["study_records"].append(study_record(raw="s2"))
    elif case == "field":
        record["fields"].append(study_field())
    elif case == "url":
        record["fields"][0]["evidence"]["source"] = "javascript:alert(1)"
    elif case == "hash":
        record["fields"][0]["evidence"]["sha256"] = "not a digest"
    elif case == "locator":
        record["fields"][0]["evidence"]["locator"] = "  "
    else:
        record["study_id"] = " Reviewed-1 "
    with pytest.raises(ValueError):
        BinaryArmSpec.model_validate(options)
