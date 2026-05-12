from pathlib import Path
import builtins

import pandas as pd

from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer


def test_grouped_boxplot_records_statistical_annotation(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "group": ["control"] * 24 + ["treated"] * 24,
            "value": list(range(24)) + list(range(20, 44)),
        }
    )
    output_path = tmp_path / "grouped_boxplot.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="boxplot",
        variables=["value"],
        output_path=output_path,
        group_var="group",
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "Mann-Whitney U" in visualizer.last_annotation_summary
    assert (
        "p =" in visualizer.last_annotation_summary or "p <" in visualizer.last_annotation_summary
    )
    assert "control n=24" in visualizer.last_annotation_summary
    assert "treated n=24" in visualizer.last_annotation_summary


def test_scatter_records_correlation_annotation(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "x": list(range(1, 31)),
            "y": [value * 3 + (value % 4) for value in range(1, 31)],
        }
    )
    output_path = tmp_path / "scatter.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="scatter",
        variables=["x", "y"],
        output_path=output_path,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "Spearman rho=" in visualizer.last_annotation_summary
    assert (
        "p =" in visualizer.last_annotation_summary or "p <" in visualizer.last_annotation_summary
    )
    assert "n=30" in visualizer.last_annotation_summary


def test_grouped_bar_records_chi_square_annotation(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "precedex_exposure": [0] * 30 + [1] * 30,
            "crbd_present": [1] * 22 + [0] * 8 + [1] * 11 + [0] * 19,
        }
    )
    output_path = tmp_path / "grouped_bar.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="bar",
        variables=["crbd_present"],
        output_path=output_path,
        group_var="precedex_exposure",
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "Chi-square" in visualizer.last_annotation_summary
    assert "precedex_exposure" not in visualizer.last_annotation_summary
    assert "0 n=30" in visualizer.last_annotation_summary
    assert "1 n=30" in visualizer.last_annotation_summary


def test_simple_bar_uses_fast_matplotlib_path_without_seaborn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "seaborn" or name.startswith("seaborn."):
            raise AssertionError("simple bar charts should not import seaborn")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    df = pd.DataFrame({"outcome": [0, 1, 1, 0, 1, 0]})
    output_path = tmp_path / "simple_bar.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="bar",
        variables=["outcome"],
        output_path=output_path,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary == "n=6; levels=2"


def test_histogram_uses_fast_matplotlib_path_without_seaborn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "seaborn" or name.startswith("seaborn."):
            raise AssertionError("histograms should not import seaborn")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    df = pd.DataFrame({"duration": [1, 2, 2, 4, 8, 16]})
    output_path = tmp_path / "histogram.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="histogram",
        variables=["duration"],
        output_path=output_path,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "n=6" in visualizer.last_annotation_summary


def test_line_plot_uses_local_lite_annotation_without_scipy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise AssertionError("line plot annotations should not import scipy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    df = pd.DataFrame({"trial": [1, 2, 3, 4, 5], "success": [0, 0, 1, 1, 1]})
    output_path = tmp_path / "line.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="line",
        variables=["trial", "success"],
        output_path=output_path,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "Wilcoxon signed-rank" in visualizer.last_annotation_summary


def test_histogram_excludes_implausible_adult_bmi_values(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "age_years": [61, 72, 77, 84],
            "bmi": [24.0, 26.0, 555.0, 8.2],
        }
    )
    output_path = tmp_path / "bmi_histogram.png"

    visualizer = MatplotlibVisualizer()
    result = visualizer.create_plot(
        data=df,
        plot_type="histogram",
        variables=["bmi"],
        output_path=output_path,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert visualizer.last_annotation_summary is not None
    assert "n=2" in visualizer.last_annotation_summary
    assert "mean=25.00" in visualizer.last_annotation_summary
    assert "bmi: excluded 2 implausible values" in visualizer.last_annotation_summary
