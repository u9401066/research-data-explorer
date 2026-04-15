from pathlib import Path

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
    assert "p =" in visualizer.last_annotation_summary or "p <" in visualizer.last_annotation_summary
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
    assert "p =" in visualizer.last_annotation_summary or "p <" in visualizer.last_annotation_summary
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