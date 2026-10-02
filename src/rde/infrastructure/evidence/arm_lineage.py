"""Verify portable source-arm evidence before accepting a derived synthesis input.

Only reads frozen records: never re-runs source parsing, clinical adjudication,
effect calculations, or a statistical model during publication/recovery.
"""

import csv
from io import StringIO
from types import SimpleNamespace

from rde.domain.models.evidence_arms import ArmOrigin, BinaryArmSpec
from rde.infrastructure.evidence import arm_workflow as arms
from rde.infrastructure.evidence import workflow as w

PREFIX = "arm-preparation/"


def verify(bundle, directory, options):
    schema = w.load_json(w.safe_path(directory, "source-schema.json"))
    origin = schema.get("armOrigin")
    supplied = bundle["source"].get("arm_origin")
    names = {name for name in bundle["files"] if name.startswith(PREFIX)}
    w.require(origin == supplied, "arm origin differs between source and schema")
    if origin is None:
        w.require(not names, "arm evidence files have no declared source origin")
        return None
    origin = ArmOrigin.model_validate(origin).model_dump()
    w.require(
        origin["projectId"] == bundle["identity"]["project_id"]
        and origin["sourceDatasetId"] != bundle["identity"]["dataset_id"],
        "arm source belongs to another Workbench project or is not a derived dataset",
    )
    w.require(
        origin["contrastSha256"] == bundle["source"]["sha256"]
        and bundle["source"].get("sheet") is None,
        "derived source differs from the prepared contrast CSV",
    )
    project = SimpleNamespace(
        id=origin["nativeProjectId"], output_dir=w.safe_path(directory, PREFIX.rstrip("/"))
    )
    plan = arms.read_plan(project, origin["preparationId"], origin["planSha256"])
    approval = arms.read_approval(project, plan, origin["approvalSha256"])
    run = arms.read_run(project, plan, origin["runId"], approval)
    w.require(
        plan["ready_for_approval"] is True
        and plan["source_sha256"] == origin["sourceHash"]
        and run["receipt_sha256"] == origin["runSha256"]
        and run["files"]["contrasts.csv"]["sha256"] == origin["contrastSha256"],
        "arm source, approved plan or execution binding differs",
    )
    root = arms.directory(project, origin["preparationId"])
    run_prefix = "runs/" + origin["runId"] + "/"
    expected = {
        PREFIX + root.relative_to(project.output_dir).as_posix() + "/" + name
        for name in (
            *plan["files"],
            "plan.json",
            "approval.json",
            *(run_prefix + name for name in run["files"]),
            run_prefix + "result-receipt.json",
        )
    }
    w.require(names == expected, "portable arm evidence inventory is incomplete or has extra files")
    for name in expected:
        path = w.safe_path(directory, name)
        record = bundle["files"][name]
        w.require(
            path.is_file()
            and path.stat().st_size == record["bytes"]
            and w.file_hash(path) == record["sha256"],
            "portable arm evidence differs from the source inventory",
        )
    spec = BinaryArmSpec.model_validate(plan["specification"])
    for option, expected_value in (
        ("measure", spec.measure),
        ("outcome", spec.outcome),
        ("timepoint", spec.timepoint),
        ("independentParallelTrials", True),
    ):
        w.require(
            options.get(option) == expected_value, "synthesis changes prepared endpoint or scale"
        )
    attempt = w.read_sealed(w.safe_path(root, run_prefix + "attempt.json"))
    w.require(
        attempt.get("schema") == "binary-arm-attempt-v1"
        and attempt.get("run_id") == origin["runId"]
        and attempt.get("plan_sha256") == origin["planSha256"]
        and attempt.get("approval_sha256") == origin["approvalSha256"],
        "arm attempt differs from the reviewed execution",
    )
    contrast = w.safe_path(root, run_prefix + "contrasts.csv")
    data = contrast.read_bytes()
    w.require(
        data == w.safe_path(directory, bundle["source"]["file"]).read_bytes(),
        "derived source bytes differ from the completed arm conversion",
    )
    table = list(csv.reader(StringIO(data.decode("utf-8"), newline=""), strict=True))
    w.require(
        bool(table)
        and w.load_json(w.safe_path(directory, "source-table.json"))
        == {"columns": table[0], "rows": table[1:]},
        "parsed synthesis input differs from the exact prepared contrast table",
    )
    w.require(
        run.get("contrast_path") == contrast.relative_to(project.output_dir).as_posix()
        and run.get("result_path")
        == (root / run_prefix / "result.json").relative_to(project.output_dir).as_posix(),
        "arm result paths differ from the approved execution",
    )
    return origin
