"""MatplotlibVisualizer — Adapter implementing VisualizationPort.

Uses matplotlib and seaborn for generating statistical visualizations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import pandas as pd

from rde.domain.ports import VisualizationPort


class MatplotlibVisualizer(VisualizationPort):
    """Create plots with matplotlib/seaborn and save to file."""

    _PLOT_DISPATCH: dict[str, str] = {
        "histogram": "_plot_histogram",
        "boxplot": "_plot_boxplot",
        "scatter": "_plot_scatter",
        "bar": "_plot_bar",
        "violin": "_plot_violin",
        "heatmap": "_plot_heatmap",
        "line": "_plot_line",
        "paired": "_plot_paired",
    }

    def create_plot(
        self,
        data: Any,
        plot_type: str,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> str:
        df: pd.DataFrame = data

        method_name = self._PLOT_DISPATCH.get(plot_type)
        if method_name is None:
            raise ValueError(
                f"Unsupported plot type: {plot_type}. "
                f"Supported: {list(self._PLOT_DISPATCH.keys())}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        method = getattr(self, method_name)
        method(df, variables, output_path, **kwargs)

        return str(output_path)

    # ── plot implementations ─────────────────────────────────────────

    def _plot_histogram(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        fig, axes = plt.subplots(
            1, len(variables), figsize=(5 * len(variables), 4), squeeze=False
        )
        for i, var in enumerate(variables):
            if var in df.columns:
                sns.histplot(df[var].dropna(), kde=True, ax=axes[0, i])
                axes[0, i].set_title(var)
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_boxplot(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        group_var = kwargs.get("group_var")
        if group_var and group_var in df.columns and len(variables) == 1:
            fig, ax = plt.subplots(figsize=(6, 4))
            sns.boxplot(data=df, x=group_var, y=variables[0], ax=ax)
            ax.set_title(f"{variables[0]} by {group_var}")
        else:
            plot_data = df[
                [v for v in variables if v in df.columns]
            ].select_dtypes(include="number")
            fig, ax = plt.subplots(figsize=(max(6, len(plot_data.columns) * 1.5), 4))
            plot_data.boxplot(ax=ax)
            ax.set_title("Box Plot")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_scatter(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        if len(variables) < 2:
            raise ValueError("Scatter plot requires at least 2 variables.")
        x_var, y_var = variables[0], variables[1]
        hue = kwargs.get("hue")
        fig, ax = plt.subplots(figsize=(6, 5))
        sns.scatterplot(
            data=df, x=x_var, y=y_var, hue=hue, alpha=0.7, ax=ax
        )
        ax.set_title(f"{x_var} vs {y_var}")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_bar(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        var = variables[0]
        if var not in df.columns:
            raise ValueError(f"Variable '{var}' not found.")

        fig, ax = plt.subplots(figsize=(6, 4))
        counts = df[var].value_counts()
        if len(counts) > 20:
            counts = counts.head(20)
        sns.barplot(x=counts.index.astype(str), y=counts.values, ax=ax)
        ax.set_title(f"Distribution of {var}")
        ax.set_xlabel(var)
        ax.set_ylabel("Count")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_violin(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        group_var = kwargs.get("group_var")
        if group_var and group_var in df.columns and len(variables) == 1:
            fig, ax = plt.subplots(figsize=(6, 4))
            sns.violinplot(data=df, x=group_var, y=variables[0], ax=ax)
            ax.set_title(f"{variables[0]} by {group_var}")
        else:
            numeric_vars = [
                v for v in variables if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
            ]
            if not numeric_vars:
                raise ValueError("No numeric variables to plot.")
            fig, ax = plt.subplots(figsize=(max(6, len(numeric_vars) * 1.5), 4))
            df[numeric_vars].plot(kind="box", ax=ax)
            ax.set_title("Violin Plot")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_heatmap(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        numeric_vars = [
            v for v in variables if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
        ]
        if not numeric_vars:
            raise ValueError("No numeric variables for heatmap.")

        corr = df[numeric_vars].corr()
        fig, ax = plt.subplots(figsize=(max(6, len(numeric_vars)), max(5, len(numeric_vars) * 0.8)))
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax)
        ax.set_title("Correlation Heatmap")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_line(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        """Line plot for repeated/time-course measurements.

        `variables` should be ordered columns representing timepoints.
        kwargs:
            labels: list[str] — x-axis tick labels (e.g., ["0h", "4h", "24h"])
            title: str — plot title
            ylabel: str — y-axis label
            show_individual: bool — draw individual subject lines (default False)
        """
        import seaborn as sns

        cols = [v for v in variables if v in df.columns]
        if not cols:
            raise ValueError("No valid variables for line plot.")

        complete = df[cols].dropna()
        labels = kwargs.get("labels", cols)
        title = kwargs.get("title", "Time-Course Plot")
        ylabel = kwargs.get("ylabel", "Value")
        show_individual = kwargs.get("show_individual", False)

        fig, ax = plt.subplots(figsize=(8, 5))

        if show_individual:
            for _, row in complete.iterrows():
                ax.plot(range(len(cols)), row[cols].values,
                        color="steelblue", alpha=0.15, linewidth=0.8)

        # Summary: median + IQR
        medians = [complete[c].median() for c in cols]
        q25 = [complete[c].quantile(0.25) for c in cols]
        q75 = [complete[c].quantile(0.75) for c in cols]

        ax.fill_between(range(len(cols)), q25, q75, alpha=0.3, color="steelblue", label="IQR")
        ax.plot(range(len(cols)), medians, "o-", color="steelblue",
                linewidth=2, markersize=8, label="Median")

        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontweight="bold")
        ax.legend()
        sns.despine()
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_paired(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        """Paired comparison plot (pre vs post) with individual subject lines.

        Expects exactly 2 variables.
        """
        if len(variables) < 2:
            raise ValueError("Paired plot requires exactly 2 variables.")

        x_var, y_var = variables[0], variables[1]
        sub = df[[x_var, y_var]].dropna()

        labels = kwargs.get("labels", [x_var, y_var])
        title = kwargs.get("title", f"{x_var} vs {y_var}")
        ylabel = kwargs.get("ylabel", "Value")

        fig, ax = plt.subplots(figsize=(6, 5))
        for _, row in sub.iterrows():
            ax.plot([0, 1], [row[x_var], row[y_var]],
                    color="steelblue", alpha=0.3, linewidth=0.8)
        ax.boxplot(
            [sub[x_var], sub[y_var]],
            positions=[0, 1], widths=0.3,
            patch_artist=True,
            boxprops=dict(facecolor="lightblue", alpha=0.7),
        )
        ax.set_xticks([0, 1])
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontweight="bold")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
