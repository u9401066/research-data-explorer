from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"


def _load_script_module(name: str):
    spec = importlib.util.spec_from_file_location(f"test_{name}", SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_aki_scripts_resolve_paths_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    preprocess = _load_script_module("preprocess_aki")
    analyze = _load_script_module("analyze_aki")
    visualize = _load_script_module("visualize_aki")
    export = _load_script_module("export_aki_report")

    assert preprocess.RAW == ROOT / "data" / "rawdata"
    assert analyze.DATA == ROOT / "data" / "rawdata" / "aki_analysis_ready.csv"
    assert analyze.OUT == ROOT / "data" / "reports" / "aki_analysis"
    assert visualize.DATA == ROOT / "data" / "rawdata" / "aki_analysis_ready.csv"
    assert visualize.FIG_DIR == ROOT / "data" / "reports" / "aki_analysis" / "figures"
    assert export.report_md == ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.md"
    assert export.figures_dir == ROOT / "data" / "reports" / "aki_analysis" / "figures"
    assert (
        export.output_docx == ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.docx"
    )
    assert (
        export.output_pdf_html
        == ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.pdf"
    )
    assert str(ROOT / "src") in sys.path
    assert not (tmp_path / "data").exists()
