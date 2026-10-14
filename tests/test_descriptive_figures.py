import asyncio
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.adapters.descriptive_study import summarize
from rde.interface.mcp.tools.descriptive_tools import _figure_evidence_valid


def test_plot_data_denominators_nonfinite_identifiers_units_and_layout(tmp_path, monkeypatch):
    import rde.infrastructure.visualization.descriptive as module
    from PIL import Image

    data = pd.DataFrame(
        dict(
            person=["private-A", "private-B", "private-C", "private-D"],
            value=[1.0, 3.0, float("inf"), None],
            empty=[float("nan")] * 4,
        )
    )
    result = summarize(data, dict(columns=list(data), identifiers=["person"], unresolved=[]))
    before = json.dumps(result, sort_keys=True)
    real_save = module.save_publication_figure

    def checked_save(fig, *args, **kwargs):
        saved = real_save(fig, *args, **kwargs)
        renderer = fig.canvas.get_renderer()
        for ax in fig.axes:
            if ax.get_legend():
                assert not ax.title.get_window_extent(renderer).overlaps(
                    ax.get_legend().get_window_extent(renderer)
                )
        return saved

    monkeypatch.setattr(module, "save_publication_figure", checked_save)
    images = module.descriptive_figures(result, tmp_path, "a" * 64, {"value": "mg/dL"})
    assert len(images) == 2
    availability, quantiles = images

    def rows(image):
        return list(csv.DictReader(Path(image["publication"]["files"]["data"]).open()))

    assert [(r["observed"], r["missing"]) for r in rows(availability)] == [
        ("4", "0"),
        ("3", "1"),
        ("0", "4"),
    ]
    summary = rows(quantiles)
    assert [r["column"] for r in summary] == ["value", "empty"]
    assert {
        k: summary[0][k]
        for k in ("finite", "nonfinite", "min", "q1", "median", "q3", "max", "unit")
    } == dict(
        finite="2",
        nonfinite="1",
        min="1.0",
        q1="1.5",
        median="2.0",
        q3="2.5",
        max="3.0",
        unit="mg/dL",
    )
    assert summary[1]["finite"] == "0" and summary[1]["median"] == ""
    for image in images:
        publication = image["publication"]
        assert publication["source_receipt_sha256"] == "a" * 64
        assert publication["text_outside_canvas"] == []
        files = publication["files"]
        assert set(files) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert Path(files["pdf"]).read_bytes().startswith(b"%PDF")
        assert "<svg" in Path(files["svg"]).read_text()
        with Image.open(files["png"]) as png:
            assert png.width > 2000 and png.info["dpi"][0] >= 299
        assert "private-A" not in Path(files["caption"]).read_text()
    assert "not Tukey whiskers" in quantiles["caption"]
    assert json.dumps(result, sort_keys=True) == before


def test_pagination_keeps_all_columns_and_all_numeric_panels(tmp_path):
    from rde.infrastructure.visualization.descriptive import descriptive_figures

    data = pd.DataFrame(
        {
            **{f"欄位/{i}/" + "long" * 30: ["x", None] for i in range(17)},
            **{f"numeric{i}": [i, i + 1] for i in range(5)},
        }
    )
    result = summarize(data, dict(columns=list(data), identifiers=[], unresolved=[]))
    images = descriptive_figures(result, tmp_path, "b" * 64)
    assert len(images) == 4
    availability = [x for x in images if x["plot_type"] == "descriptive_availability"]
    numeric = [x for x in images if x["plot_type"] == "descriptive_quantiles"]
    assert [c for x in availability for c in x["variables"]] == list(data)
    assert [c for x in numeric for c in x["variables"]] == [f"numeric{i}" for i in range(5)]
    assert all(x["publication"]["text_outside_canvas"] == [] for x in images)
    assert all(
        Path(p).parent == tmp_path for x in images for p in x["publication"]["files"].values()
    )


@pytest.mark.parametrize("extension", ["png", "plot-data.csv"])
def test_figure_target_symlink_cannot_overwrite_external_file(tmp_path, extension):
    from rde.infrastructure.visualization.descriptive import descriptive_figures

    directory = tmp_path / "figures"
    directory.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"ORIGINAL")
    target = directory / ("descriptive_" + "a" * 20 + "_availability_1." + extension)
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Host cannot create a symlink")
    result = summarize(
        pd.DataFrame({"category": ["a", "b"]}),
        dict(columns=["category"], identifiers=[], unresolved=[]),
    )
    with pytest.raises(ValueError, match="figure target"):
        descriptive_figures(result, directory, "a" * 64)
    assert outside.read_bytes() == b"ORIGINAL"
    assert target.is_symlink()
    assert list(directory.iterdir()) == [target]
    with pytest.raises(ValueError, match="receipt SHA256"):
        descriptive_figures(result, directory, "../unsafe")


def setup_call(tmp_path):
    from test_clinical_survival import clinical_project
    from rde.interface.mcp.server import create_server

    data = pd.DataFrame(dict(id=["a", "a", "b", "c"], value=[1.0, 3.0, 2.0, None]))
    options = dict(columns=list(data), identifiers=["id"], unresolved=["Unknown sampling"])
    project, store, dataset, _ = clinical_project(tmp_path, frame=data)
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        dict(
            locked=True,
            analyses=[
                dict(
                    type="run_descriptive_study",
                    variables=options["columns"],
                    execution_arguments=dict(descriptive_options=options),
                )
            ],
        ),
    )
    server = create_server()

    def call():
        return asyncio.run(
            server.call_tool(
                "run_descriptive_study", dict(dataset_id=dataset.id, descriptive_options=options)
            )
        )

    return project, store, dataset, call


def test_renderer_failure_retry_uses_sealed_numbers_and_tamper_blocks_reuse(tmp_path, monkeypatch):
    import rde.interface.mcp.tools.descriptive_tools as module

    project, store, dataset, call = setup_call(tmp_path)
    renderer = module.descriptive_figures

    def fail(*args):
        raise ValueError("Synthetic renderer failure")

    monkeypatch.setattr(module, "descriptive_figures", fail)
    failed = call()
    assert failed.is_error and "Synthetic renderer failure" in failed.content[0].text
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
    numbers = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_numbers.json")
    original_numbers = numbers.read_bytes()
    monkeypatch.setattr(
        module, "summarize", lambda *a: pytest.fail("A renderer retry must not recompute numbers")
    )
    monkeypatch.setattr(module, "descriptive_figures", renderer)
    success = call()
    assert not success.is_error, success.content
    assert numbers.read_bytes() == original_numbers
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
    assert _figure_evidence_valid(store, record)
    originals = {
        a["path"]: (project.output_dir / a["path"]).read_bytes() for a in record["artifacts"]
    }
    assert json.loads(call().content[0].text)["reused"]
    assert originals == {path: (project.output_dir / path).read_bytes() for path in originals}
    target = Path(record["figures"][0]["publication"]["files"]["data"])
    target.write_text("tampered")
    assert not _figure_evidence_valid(store, record)
    assert call().is_error
    target.write_bytes(originals[target.relative_to(project.output_dir).as_posix()])
    assert _figure_evidence_valid(store, record)
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json", [])
    assert not _figure_evidence_valid(store, record)
    assert call().is_error
    assert (
        hashlib.sha256(numbers.read_bytes()).hexdigest()
        == hashlib.sha256(original_numbers).hexdigest()
    )


def test_numeric_evidence_drift_cannot_be_repaired_by_rerender(tmp_path, monkeypatch):
    import rde.interface.mcp.tools.descriptive_tools as module

    _, store, _, call = setup_call(tmp_path)

    def fail(*args):
        raise ValueError("Synthetic renderer failure")

    monkeypatch.setattr(module, "descriptive_figures", fail)
    assert call().is_error
    numbers = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_numbers.json")
    numbers["result"]["input_rows"] = 999
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_numbers.json", numbers)
    response = call()
    assert response.is_error and "numbers changed" in response.content[0].text


def test_prepared_units_reach_native_figure_receipt_and_changed_bundle_blocks(tmp_path):
    from test_preparation_workflow import setup, approve
    from test_clinical_survival import clinical_project
    from rde.application.session import get_session
    from rde.domain.models.dataset import DatasetMetadata
    from rde.infrastructure.adapters.pandas_loader import PandasLoader
    from rde.infrastructure.preparation import portable, workflow
    from rde.interface.mcp.server import create_server

    raw = tmp_path / "raw"
    raw.mkdir()
    source_project, request = setup(raw)
    for relation in request["specification"]["relations"]:
        for feature in relation["features"]:
            if feature["output"] == "lab_mean":
                feature["output_unit"] = "mg/dL"
    plan = workflow.execute(source_project, request)
    approval = approve(source_project, plan)
    release = workflow.execute(
        source_project,
        dict(
            op="release",
            preparation_id=plan["preparation_id"],
            expected_sha256=plan["receipt_sha256"],
            approval_sha256=approval["receipt_sha256"],
        ),
    )
    bundle = workflow.execute(
        source_project,
        dict(
            op="bundle",
            preparation_id=plan["preparation_id"],
            expected_sha256=plan["receipt_sha256"],
            release_sha256=release["receipt_sha256"],
        ),
    )
    target = tmp_path / "analysis"
    target.mkdir()
    project, store, dataset, _ = clinical_project(
        target, frame=pd.DataFrame({"placeholder": list(range(6))})
    )
    binding = portable.import_bundle(
        project, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    metadata = DatasetMetadata(
        Path(release["dataset"]["path"]), "csv", release["dataset"]["bytes"], preparation=binding
    )
    data, variables, n, _ = PandasLoader().load(metadata)
    dataset.metadata = metadata
    dataset.mark_loaded(variables, n)
    get_session().register_dataset(dataset, data)
    store.save(
        PipelinePhase.DATA_INTAKE,
        "intake_report.json",
        dict(
            dataset_id=dataset.id,
            preparation=binding,
            row_count=n,
            source={
                **{k: release["dataset"][k] for k in ("sha256", "bytes")},
                "filename": metadata.file_path.name,
                "sheet_name": None,
            },
        ),
    )
    options = dict(
        columns=["_rde_unit_id", "_rde_subject_id", "lab_mean"],
        identifiers=["_rde_unit_id", "_rde_subject_id"],
        unresolved=[],
    )
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        dict(
            locked=True,
            analyses=[
                dict(
                    type="run_descriptive_study",
                    variables=options["columns"],
                    execution_arguments=dict(descriptive_options=options),
                )
            ],
        ),
    )

    def call():
        return asyncio.run(
            create_server().call_tool(
                "run_descriptive_study", dict(dataset_id=dataset.id, descriptive_options=options)
            )
        )

    answer = call()
    assert not answer.is_error, answer.content
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
    assert record["figure_units"] == {"lab_mean": "mg/dL"}
    assert "mg/dL" in record["figures"][1]["caption"]
    assert _figure_evidence_valid(store, record)
    numbers = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_numbers.json")
    original = numbers.read_bytes()
    (Path(binding["folder"]) / "specification.json").write_text("tampered")
    assert call().is_error
    assert numbers.read_bytes() == original
