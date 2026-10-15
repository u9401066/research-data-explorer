"""Frozen clinical receipts retain their scope in actual formal DOCX exports."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import re
import zipfile

from docx import Document
import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _figure_interpretation_harness_entry
from test_clinical_imputation import fixture as mi_fixture
from test_clinical_noninferiority import means_fixture
from test_clinical_stratified import fixture as cmh_fixture
from test_clinical_survival import clinical_project


def call(name, arguments):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert not response.is_error, response.content
    return response.content[0].text


@pytest.mark.parametrize("family", ["imputation", "stratified", "noninferiority"])
def test_actual_clinical_docx_uses_locked_scope_and_separate_source_context(tmp_path, family):
    frame, spec = {
        "imputation": mi_fixture,
        "stratified": cmh_fixture,
        "noninferiority": lambda: means_fixture()[:2],
    }[family]()
    spec = replace(spec, context="工程案例：核對已核准計畫的原始研究問題")
    if family == "stratified":
        treatment_levels = ["原始對照碼", "原始介入碼"]
        outcome_levels = ["原始無事件碼", "原始事件碼"]
        strata_levels = [f"原始層碼{i + 1}" for i in range(len(spec.strata_levels))]
        for column, old, new in [
            (spec.treatment, spec.treatment_levels, treatment_levels),
            (spec.outcome, spec.outcome_levels, outcome_levels),
            (spec.strata, spec.strata_levels, strata_levels),
        ]:
            frame[column] = frame[column].map(dict(zip(old, new, strict=True)))
        spec = replace(
            spec,
            treatment_levels=treatment_levels,
            outcome_levels=outcome_levels,
            strata_levels=strata_levels,
        )
    if family == "noninferiority":
        spec = replace(
            spec,
            margin=0.05,
            margin_basis="僅供工程驗證的界值依據",
            outcome_definition="觀察結果原始定義",
            outcome_unit="量表分數",
            outcome_window="預先指定窗口",
        )
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    store.save(
        PipelinePhase.CONCEPT_ALIGNMENT,
        "concept_alignment.md",
        "研究問題: 已核准研究計畫的工程驗證",
    )
    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()})
    record = clinical_records(store)[0]
    assert verify_clinical_artifacts(record, project.output_dir)
    saved = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"]).read_bytes()
    for figure in record["figures"]:
        publication = figure["publication"]
        assert re.search(r"[\u3400-\u9fff]", publication["caption_en"]) is None
        assert publication["source_context"]["context"] == spec.context
        assert spec.context not in publication["caption_en"]
        assert publication["explanation_zh"]
        caption_file = Path(publication["files"]["caption"]).read_text()
        assert "Source context (original language)" in caption_file
        assert spec.context in caption_file
        context = json.loads(caption_file.split("```json\n", 1)[1].split("\n```", 1)[0])
        assert context == publication["source_context"]
        if family == "noninferiority":
            assert context["margin_basis"] == spec.margin_basis
            assert context["outcome_unit"] == spec.outcome_unit
        elif family == "imputation":
            assert context["variable_aliases"]["V1"] == spec.columns[0]["column"]
        else:
            assert context["outcome_aliases"]["Y1"] == spec.outcome_levels[1]
            assert context["stratum_aliases"]["S1"] == spec.strata_levels[0]
    call("collect_results", {"project_id": project.id})
    call("assemble_report", {"project_id": project.id})
    result = call("export_report", {"project_id": project.id, "formats": "docx"})
    assert "DOCX" in result
    exports = project.artifacts_dir / "exports"
    assert not (exports / "eda_report.pdf").exists()  # Figure PDFs are not a report PDF.
    source = (exports / "eda_report_formal_source.md").read_text()
    docx = exports / "eda_report.docx"
    document = Document(docx)
    text = "\n".join(p.text for p in document.paragraphs)
    for content in [source, text]:
        assert "已登錄並鎖定之臨床研究契約" in content
        assert "所有結果應視為早期探索與假說生成" not in content
        assert "Table 1 is not available" not in content
        assert "本核准研究契約不另外產生 Table 1" in content
        assert "interpretation type not mapped" not in content
        if family == "imputation":
            assert "不乘以 m" in content and "不證明" in content
        elif family == "stratified":
            assert "共同 OR 不是" in content
        else:
            assert "保存數值未能證明非劣性" in content
            assert "保存數值支持預先指定界值下的非劣性" not in content
    with zipfile.ZipFile(docx) as archive:
        assert len([name for name in archive.namelist() if name.startswith("word/media/")]) == len(
            record["figures"]
        )
    harness = store.load(PipelinePhase.REPORT_ASSEMBLY, "figure_interpretation_harness.json")[
        "entries"
    ]
    assert len(harness) == len(record["figures"])
    assert all("not mapped" not in item["evidence_role"] for item in harness)
    assert all(item["p_value"] is None for item in harness)
    # Report assembly/export do not refit or rewrite frozen numerical evidence.
    assert (
        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"]).read_bytes() == saved
    )
    assert verify_clinical_artifacts(record, project.output_dir)


@pytest.mark.parametrize(
    "plot,expected",
    [
        ("clinical_imputation_flow", "population"),
        ("clinical_imputation_missing_12", "missing-cell"),
        ("clinical_imputation_effects_2", "Rubin"),
        ("clinical_imputation_traces_3", "Single-chain"),
        ("clinical_stratified_flow", "population"),
        ("clinical_stratified_tables_2", "Original binary"),
        ("clinical_stratified_effect", "Mantel-Haenszel"),
        ("clinical_noninferiority_flow", "population"),
        ("clinical_noninferiority_effect", "one-sided"),
    ],
)
def test_native_figure_interpretation_never_infers_success_from_caption_p(plot, expected):
    entry = _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type=plot,
        variables=["outcome"],
        stats_summary="Saved p=0.001; diagnostics p=0.8",
        group_var="arm",
    )
    assert expected in entry["evidence_role"]
    assert entry["p_value"] is None
    assert entry["statistical_support"] == "Saved p=0.001; diagnostics p=0.8"
    assert entry["validity_caveat"] and entry["next_analysis"]
