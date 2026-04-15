"""MatplotlibVisualizer — Adapter implementing VisualizationPort.

Uses matplotlib and seaborn for generating statistical visualizations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

from rde.domain.ports import VisualizationPort


def _configure_font_fallback() -> None:
    """Prefer a local CJK-capable sans-serif font when available."""
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    preferred_fonts = [
        "Microsoft JhengHei",
        "Microsoft YaHei",
        "Noto Sans CJK TC",
        "Noto Sans CJK SC",
        "PingFang TC",
        "PingFang SC",
    ]
    selected_fonts = [font for font in preferred_fonts if font in available_fonts]
    if not selected_fonts:
        return

    existing_fonts = list(matplotlib.rcParams.get("font.sans-serif", []))
    merged_fonts: list[str] = []
    for font_name in selected_fonts + existing_fonts:
        if font_name not in merged_fonts:
            merged_fonts.append(font_name)

    matplotlib.rcParams["font.family"] = ["sans-serif"]
    matplotlib.rcParams["font.sans-serif"] = merged_fonts
    matplotlib.rcParams["axes.unicode_minus"] = False


_configure_font_fallback()


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

    def __init__(self) -> None:
        self.last_annotation_summary: str | None = None

    def create_plot(
        self,
        data: Any,
        plot_type: str,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> str:
        df: pd.DataFrame = data
        self.last_annotation_summary = None

        method_name = self._PLOT_DISPATCH.get(plot_type)
        if method_name is None:
            raise ValueError(
                f"Unsupported plot type: {plot_type}. Supported: {list(self._PLOT_DISPATCH.keys())}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        method = getattr(self, method_name)
        method(df, variables, output_path, **kwargs)

        return str(output_path)

    def _set_annotation(self, ax: Any, lines: list[str], summary: str | None = None) -> None:
        cleaned = [line for line in lines if line]
        if not cleaned:
            self.last_annotation_summary = None
            return

        ax.text(
            0.02,
            0.98,
            "\n".join(cleaned),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9, "edgecolor": "0.7"},
        )
        self.last_annotation_summary = summary or "; ".join(cleaned)

    def _format_p_value(self, p_value: float | None) -> str:
        if p_value is None or pd.isna(p_value):
            return "p = NA"
        if p_value < 0.001:
            return "p < 0.001"
        return f"p = {p_value:.3f}"

    def _annotate_distribution_stats(self, ax: Any, series: pd.Series, label: str) -> None:
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if numeric.empty:
            self._set_annotation(ax, [f"{label}: no valid values"], summary=f"{label}: no valid values")
            return

        self._set_annotation(
            ax,
            [
                f"n = {len(numeric)}",
                f"mean = {numeric.mean():.2f}",
                f"median = {numeric.median():.2f}",
                f"SD = {numeric.std(ddof=1):.2f}" if len(numeric) > 1 else "SD = NA",
            ],
            summary=(
                f"n={len(numeric)}; mean={numeric.mean():.2f}; "
                f"median={numeric.median():.2f}; SD={numeric.std(ddof=1):.2f}"
                if len(numeric) > 1
                else f"n={len(numeric)}; mean={numeric.mean():.2f}; median={numeric.median():.2f}; SD=NA"
            ),
        )

    def _build_grouped_numeric_frame(
        self,
        df: pd.DataFrame,
        value_var: str,
        group_var: str,
    ) -> tuple[pd.DataFrame, list[Any]]:
        sub = df[[group_var, value_var]].copy()
        sub[value_var] = pd.to_numeric(sub[value_var], errors="coerce")
        sub = sub.dropna(subset=[group_var, value_var])
        order = list(pd.unique(sub[group_var]))
        return sub, order

    def _draw_pairwise_bracket(self, ax: Any, label: str) -> None:
        y_min, y_max = ax.get_ylim()
        span = y_max - y_min
        if span <= 0:
            span = 1.0
        line_y = y_max + span * 0.03
        height = span * 0.05
        ax.plot(
            [0, 0, 1, 1],
            [line_y, line_y + height, line_y + height, line_y],
            color="black",
            linewidth=1.1,
            clip_on=False,
        )
        ax.text(0.5, line_y + height, label, ha="center", va="bottom", fontsize=9)
        ax.set_ylim(y_min, line_y + height * 2.0)

    def _annotate_group_comparison(
        self,
        ax: Any,
        df: pd.DataFrame,
        value_var: str,
        group_var: str,
        group_order: list[Any],
    ) -> None:
        from scipy import stats

        sub, order = self._build_grouped_numeric_frame(df, value_var, group_var)
        if sub.empty:
            self._set_annotation(
                ax,
                ["Comparison unavailable", "No valid grouped observations"],
                summary="Comparison unavailable: no valid grouped observations",
            )
            return

        aligned_order = [group for group in group_order if group in set(sub[group_var])]
        if not aligned_order:
            aligned_order = order

        groups = [sub.loc[sub[group_var] == group, value_var] for group in aligned_order]
        labels = [str(group) for group in aligned_order]
        valid_groups = [(label, values) for label, values in zip(labels, groups) if not values.empty]
        if len(valid_groups) < 2:
            self._set_annotation(
                ax,
                ["Comparison unavailable", "Need at least 2 non-empty groups"],
                summary="Comparison unavailable: fewer than 2 non-empty groups",
            )
            return

        labels = [label for label, _ in valid_groups]
        groups = [values for _, values in valid_groups]
        counts_line = ", ".join(f"{label} n={len(values)}" for label, values in zip(labels, groups))

        if len(groups) == 2:
            try:
                statistic, p_value = stats.mannwhitneyu(groups[0], groups[1], alternative="two-sided")
                p_text = self._format_p_value(float(p_value))
                self._draw_pairwise_bracket(ax, p_text)
                self._set_annotation(
                    ax,
                    [f"Mann-Whitney U = {statistic:.1f}", p_text, counts_line],
                    summary=f"Mann-Whitney U; {p_text}; {counts_line}",
                )
                return
            except ValueError:
                pass

        try:
            statistic, p_value = stats.kruskal(*groups)
            p_text = self._format_p_value(float(p_value))
            self._set_annotation(
                ax,
                [f"Kruskal-Wallis H = {statistic:.2f}", p_text, counts_line],
                summary=f"Kruskal-Wallis H; {p_text}; {counts_line}",
            )
        except ValueError:
            self._set_annotation(
                ax,
                ["Comparison unavailable", counts_line],
                summary=f"Comparison unavailable; {counts_line}",
            )

    def _annotate_scatter_stats(
        self,
        ax: Any,
        df: pd.DataFrame,
        x_var: str,
        y_var: str,
    ) -> None:
        from scipy import stats

        sub = df[[x_var, y_var]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(sub) < 3:
            self._set_annotation(
                ax,
                ["Correlation unavailable", f"n = {len(sub)}"],
                summary=f"Correlation unavailable; n={len(sub)}",
            )
            return

        rho, p_value = stats.spearmanr(sub[x_var], sub[y_var])
        self._set_annotation(
            ax,
            [f"Spearman rho = {rho:.2f}", self._format_p_value(float(p_value)), f"n = {len(sub)}"],
            summary=f"Spearman rho={rho:.2f}; {self._format_p_value(float(p_value))}; n={len(sub)}",
        )

    def _annotate_line_stats(self, ax: Any, complete: pd.DataFrame, cols: list[str]) -> None:
        from scipy import stats

        if len(complete) < 3:
            self._set_annotation(
                ax,
                ["Trend comparison unavailable", f"n = {len(complete)}"],
                summary=f"Trend comparison unavailable; n={len(complete)}",
            )
            return

        if len(cols) >= 3:
            statistic, p_value = stats.friedmanchisquare(*(complete[col] for col in cols))
            p_text = self._format_p_value(float(p_value))
            self._set_annotation(
                ax,
                [f"Friedman χ² = {statistic:.2f}", p_text, f"n = {len(complete)}"],
                summary=f"Friedman chi-square={statistic:.2f}; {p_text}; n={len(complete)}",
            )
            return

        statistic, p_value = stats.wilcoxon(complete[cols[0]], complete[cols[1]])
        p_text = self._format_p_value(float(p_value))
        self._set_annotation(
            ax,
            [f"Wilcoxon W = {statistic:.1f}", p_text, f"n = {len(complete)}"],
            summary=f"Wilcoxon signed-rank; {p_text}; n={len(complete)}",
        )

    def _annotate_paired_stats(
        self,
        ax: Any,
        sub: pd.DataFrame,
        x_var: str,
        y_var: str,
    ) -> None:
        from scipy import stats

        if len(sub) < 3:
            self._set_annotation(
                ax,
                ["Paired comparison unavailable", f"n = {len(sub)}"],
                summary=f"Paired comparison unavailable; n={len(sub)}",
            )
            return

        statistic, p_value = stats.wilcoxon(sub[x_var], sub[y_var])
        median_delta = (sub[y_var] - sub[x_var]).median()
        p_text = self._format_p_value(float(p_value))
        self._set_annotation(
            ax,
            [f"Wilcoxon W = {statistic:.1f}", p_text, f"median Δ = {median_delta:.2f}", f"n = {len(sub)}"],
            summary=f"Wilcoxon signed-rank; {p_text}; median delta={median_delta:.2f}; n={len(sub)}",
        )

    # ── plot implementations ─────────────────────────────────────────

    def _plot_histogram(
        self,
        df: pd.DataFrame,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> None:
        import seaborn as sns

        fig, axes = plt.subplots(1, len(variables), figsize=(5 * len(variables), 4), squeeze=False)
        for i, var in enumerate(variables):
            if var in df.columns:
                numeric = pd.to_numeric(df[var], errors="coerce").dropna()
                sns.histplot(numeric, kde=True, ax=axes[0, i])
                axes[0, i].set_title(var)
                self._annotate_distribution_stats(axes[0, i], numeric, var)
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
            grouped, order = self._build_grouped_numeric_frame(df, variables[0], group_var)
            fig, ax = plt.subplots(figsize=(6, 4))
            sns.boxplot(data=grouped, x=group_var, y=variables[0], order=order, ax=ax)
            ax.set_title(f"{variables[0]} by {group_var}")
            self._annotate_group_comparison(ax, grouped, variables[0], group_var, order)
        else:
            plot_data = df[[v for v in variables if v in df.columns]].select_dtypes(
                include="number"
            )
            fig, ax = plt.subplots(figsize=(max(6, len(plot_data.columns) * 1.5), 4))
            plot_data.boxplot(ax=ax)
            ax.set_title("Box Plot")
            if not plot_data.empty:
                self._annotate_distribution_stats(ax, plot_data.stack(), "combined boxplot")
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
        sns.scatterplot(data=df, x=x_var, y=y_var, hue=hue, alpha=0.7, ax=ax)
        numeric = df[[x_var, y_var]].apply(pd.to_numeric, errors="coerce").dropna()
        if not numeric.empty:
            sns.regplot(data=numeric, x=x_var, y=y_var, scatter=False, ci=None, ax=ax, color="darkorange")
        ax.set_title(f"{x_var} vs {y_var}")
        self._annotate_scatter_stats(ax, df, x_var, y_var)
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

        group_var = kwargs.get("group_var")
        if group_var and group_var in df.columns:
            from scipy import stats

            sub = df[[group_var, var]].dropna()
            contingency = pd.crosstab(sub[group_var], sub[var])
            if contingency.shape[0] >= 2 and contingency.shape[1] >= 2:
                proportions = contingency.div(contingency.sum(axis=1), axis=0).reset_index()
                plot_frame = proportions.melt(
                    id_vars=group_var,
                    var_name=var,
                    value_name="proportion",
                )

                fig, ax = plt.subplots(figsize=(max(6, contingency.shape[0] * 1.6), 4.5))
                sns.barplot(data=plot_frame, x=group_var, y="proportion", hue=var, ax=ax)
                ax.set_title(f"{var} by {group_var}")
                ax.set_xlabel(group_var)
                ax.set_ylabel("Proportion")
                ax.set_ylim(0, 1)

                chi2, p_value, _, _ = stats.chi2_contingency(contingency)
                counts_line = ", ".join(
                    f"{index} n={int(contingency.loc[index].sum())}" for index in contingency.index
                )
                self._set_annotation(
                    ax,
                    [f"Chi-square = {chi2:.2f}", self._format_p_value(float(p_value)), counts_line],
                    summary=f"Chi-square; {self._format_p_value(float(p_value))}; {counts_line}",
                )
                plt.tight_layout()
                fig.savefig(output_path, dpi=150, bbox_inches="tight")
                plt.close(fig)
                return

        fig, ax = plt.subplots(figsize=(6, 4))
        counts = df[var].value_counts()
        if len(counts) > 20:
            counts = counts.head(20)
        sns.barplot(x=counts.index.astype(str), y=counts.values, ax=ax)
        ax.set_title(f"Distribution of {var}")
        ax.set_xlabel(var)
        ax.set_ylabel("Count")
        self._set_annotation(
            ax,
            [f"n = {int(counts.sum())}", f"levels = {len(counts)}"],
            summary=f"n={int(counts.sum())}; levels={len(counts)}",
        )
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
            grouped, order = self._build_grouped_numeric_frame(df, variables[0], group_var)
            fig, ax = plt.subplots(figsize=(6, 4))
            sns.violinplot(data=grouped, x=group_var, y=variables[0], order=order, ax=ax)
            ax.set_title(f"{variables[0]} by {group_var}")
            self._annotate_group_comparison(ax, grouped, variables[0], group_var, order)
        else:
            numeric_vars = [
                v for v in variables if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
            ]
            if not numeric_vars:
                raise ValueError("No numeric variables to plot.")
            fig, ax = plt.subplots(figsize=(max(6, len(numeric_vars) * 1.5), 4))
            df[numeric_vars].plot(kind="box", ax=ax)
            ax.set_title("Violin Plot")
            self._annotate_distribution_stats(ax, df[numeric_vars].stack(), "combined violin")
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
        self._set_annotation(
            ax,
            [f"variables = {len(numeric_vars)}", f"complete rows = {len(df[numeric_vars].dropna())}"],
            summary=f"variables={len(numeric_vars)}; complete_rows={len(df[numeric_vars].dropna())}",
        )
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
                ax.plot(
                    range(len(cols)), row[cols].values, color="steelblue", alpha=0.15, linewidth=0.8
                )

        # Summary: median + IQR
        medians = [complete[c].median() for c in cols]
        q25 = [complete[c].quantile(0.25) for c in cols]
        q75 = [complete[c].quantile(0.75) for c in cols]

        ax.fill_between(range(len(cols)), q25, q75, alpha=0.3, color="steelblue", label="IQR")
        ax.plot(
            range(len(cols)),
            medians,
            "o-",
            color="steelblue",
            linewidth=2,
            markersize=8,
            label="Median",
        )

        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontweight="bold")
        ax.legend()
        self._annotate_line_stats(ax, complete, cols)
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
            ax.plot([0, 1], [row[x_var], row[y_var]], color="steelblue", alpha=0.3, linewidth=0.8)
        ax.boxplot(
            [sub[x_var], sub[y_var]],
            positions=[0, 1],
            widths=0.3,
            patch_artist=True,
            boxprops=dict(facecolor="lightblue", alpha=0.7),
        )
        ax.set_xticks([0, 1])
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontweight="bold")
        self._annotate_paired_stats(ax, sub, x_var, y_var)
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
