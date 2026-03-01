"""ScipyStatisticalEngine — Adapter implementing StatisticalEnginePort.

Uses scipy.stats, statsmodels, and tableone for statistical analysis.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from rde.domain.ports import StatisticalEnginePort


class ScipyStatisticalEngine(StatisticalEnginePort):
    """Statistical engine backed by scipy.stats and tableone."""

    # ── dispatch table ───────────────────────────────────────────────

    _TEST_DISPATCH: dict[str, str] = {
        "Independent t-test": "_ttest_ind",
        "Paired t-test": "_ttest_paired",
        "Mann-Whitney U test": "_mann_whitney",
        "Wilcoxon signed-rank test": "_wilcoxon",
        "One-way ANOVA": "_anova",
        "Kruskal-Wallis test": "_kruskal",
        "Chi-squared test": "_chi_squared",
        "Fisher's exact test": "_fisher_exact",
        "Shapiro-Wilk": "_shapiro",
        "Pearson correlation": "_pearson",
        "Spearman correlation": "_spearman",
        "Levene's test": "_levene",
        "Tukey HSD": "_tukey_hsd",
        "Dunn's test": "_dunn",
        "Point-biserial correlation": "_point_biserial",
    }

    # ── port interface ───────────────────────────────────────────────

    def run_test(
        self,
        data: Any,
        test_name: str,
        variables: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        df: pd.DataFrame = data
        method_name = self._TEST_DISPATCH.get(test_name)
        if method_name is None:
            return {
                "error": f"Unsupported test: {test_name}",
                "supported": list(self._TEST_DISPATCH.keys()),
            }
        method = getattr(self, method_name)
        return method(df, variables, **kwargs)

    def generate_table_one(
        self,
        data: Any,
        group_var: str,
        variables: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        df: pd.DataFrame = data
        try:
            from tableone import TableOne
        except ImportError:
            return {"error": "tableone not installed. pip install tableone"}

        cols = [c for c in variables if c in df.columns and c != group_var]
        if not cols:
            return {"error": "No valid variables found for Table 1."}

        # Detect categorical columns
        categorical = [
            c for c in cols
            if df[c].dtype == "object"
            or df[c].dtype.name == "category"
            or df[c].nunique() <= 10
        ]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = TableOne(
                df,
                columns=cols,
                categorical=categorical,
                groupby=group_var,
                pval=True,
                htest_name=True,
                **kwargs,
            )

        # Convert table_dict keys to strings (tableone uses tuples as keys)
        raw_dict = table.tableone.to_dict()
        table_dict = {}
        for col_key, rows in raw_dict.items():
            str_col = str(col_key) if not isinstance(col_key, str) else col_key
            table_dict[str_col] = {
                (str(k) if not isinstance(k, str) else k): v
                for k, v in rows.items()
            }

        return {
            "table_text": table.tabulate(tablefmt="grid"),
            "table_html": table.tabulate(tablefmt="html"),
            "table_dict": table_dict,
            "group_var": group_var,
            "n_variables": len(cols),
            "n_categorical": len(categorical),
        }

    # ── individual test implementations ──────────────────────────────

    def _ttest_ind(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_keys = list(groups.index)
        if len(group_keys) < 2:
            return {"error": f"Need ≥2 groups, found {len(group_keys)}."}

        a, b = groups.iloc[0], groups.iloc[1]
        stat, p = stats.ttest_ind(a, b, equal_var=kw.get("equal_var", True))
        d = self._cohens_d(a, b)

        return {
            "test_name": "Independent t-test",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(d),
            "effect_size_name": "Cohen's d",
            "sample_sizes": [len(a), len(b)],
            "group_labels": [str(g) for g in group_keys[:2]],
            "interpretation": self._interpret_comparison(p, d, "Cohen's d"),
        }

    def _ttest_paired(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        if len(variables) < 2:
            return {"error": "Paired t-test requires 2 outcome variable names."}
        a = df[variables[0]].dropna().values
        b = df[variables[1]].dropna().values
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        stat, p = stats.ttest_rel(a, b)
        d = self._cohens_d(a, b)

        return {
            "test_name": "Paired t-test",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(d),
            "effect_size_name": "Cohen's d",
            "sample_sizes": [n],
            "interpretation": self._interpret_comparison(p, d, "Cohen's d"),
        }

    def _mann_whitney(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_keys = list(groups.index)
        if len(group_keys) < 2:
            return {"error": f"Need ≥2 groups, found {len(group_keys)}."}

        a, b = groups.iloc[0], groups.iloc[1]
        stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        n = len(a) + len(b)
        r = abs(stat - (len(a) * len(b) / 2)) / (len(a) * len(b)) if n > 0 else 0

        return {
            "test_name": "Mann-Whitney U",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(r),
            "effect_size_name": "rank-biserial r",
            "sample_sizes": [len(a), len(b)],
            "group_labels": [str(g) for g in group_keys[:2]],
            "interpretation": self._interpret_comparison(p, r, "r"),
        }

    def _wilcoxon(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        if len(variables) < 2:
            return {"error": "Wilcoxon test requires 2 variable names."}
        a = df[variables[0]].dropna().values
        b = df[variables[1]].dropna().values
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        stat, p = stats.wilcoxon(a, b)
        r = stat / (n * (n + 1) / 2) if n > 0 else 0

        return {
            "test_name": "Wilcoxon signed-rank",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(r),
            "effect_size_name": "r",
            "sample_sizes": [n],
            "interpretation": self._interpret_comparison(p, r, "r"),
        }

    def _anova(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups_series = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_arrays = [g for g in groups_series]
        if len(group_arrays) < 2:
            return {"error": "ANOVA requires ≥2 groups."}

        stat, p = stats.f_oneway(*group_arrays)
        # eta-squared
        grand_mean = np.concatenate(group_arrays).mean()
        ss_between = sum(
            len(g) * (g.mean() - grand_mean) ** 2 for g in group_arrays
        )
        ss_total = sum(
            np.sum((g - grand_mean) ** 2) for g in group_arrays
        )
        eta_sq = ss_between / ss_total if ss_total > 0 else 0

        return {
            "test_name": "One-way ANOVA",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(eta_sq),
            "effect_size_name": "eta-squared",
            "sample_sizes": [len(g) for g in group_arrays],
            "group_labels": [str(k) for k in groups_series.index],
            "interpretation": self._interpret_comparison(p, eta_sq, "η²"),
        }

    def _kruskal(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups_series = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_arrays = [g for g in groups_series]
        if len(group_arrays) < 2:
            return {"error": "Kruskal-Wallis requires ≥2 groups."}

        stat, p = stats.kruskal(*group_arrays)
        n = sum(len(g) for g in group_arrays)
        k = len(group_arrays)
        eta_h = (stat - k + 1) / (n - k) if (n - k) > 0 else 0

        return {
            "test_name": "Kruskal-Wallis",
            "statistic": float(stat),
            "p_value": float(p),
            "effect_size": float(eta_h),
            "effect_size_name": "eta-squared (H)",
            "sample_sizes": [len(g) for g in group_arrays],
            "group_labels": [str(k) for k in groups_series.index],
            "interpretation": self._interpret_comparison(p, eta_h, "η²"),
        }

    def _chi_squared(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        var1, var2 = variables[0], variables[1]
        ct = pd.crosstab(df[var1], df[var2])
        stat, p, dof, expected = stats.chi2_contingency(ct)
        n = ct.sum().sum()
        cramers_v = np.sqrt(stat / (n * (min(ct.shape) - 1))) if n > 0 and min(ct.shape) > 1 else 0

        return {
            "test_name": "Chi-squared",
            "statistic": float(stat),
            "p_value": float(p),
            "degrees_of_freedom": int(dof),
            "effect_size": float(cramers_v),
            "effect_size_name": "Cramér's V",
            "contingency_table": ct.to_dict(),
            "interpretation": self._interpret_comparison(p, cramers_v, "V"),
        }

    def _fisher_exact(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        var1, var2 = variables[0], variables[1]
        ct = pd.crosstab(df[var1], df[var2])
        if ct.shape != (2, 2):
            return {"error": "Fisher's exact test requires a 2×2 table."}
        odds_ratio, p = stats.fisher_exact(ct)

        return {
            "test_name": "Fisher's exact",
            "statistic": float(odds_ratio),
            "p_value": float(p),
            "effect_size": float(odds_ratio),
            "effect_size_name": "Odds Ratio",
            "contingency_table": ct.to_dict(),
            "interpretation": self._interpret_comparison(p, odds_ratio, "OR"),
        }

    def _shapiro(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        var_name = variables[0]
        values = df[var_name].dropna().values
        if len(values) < 3:
            return {"error": "Shapiro-Wilk requires ≥3 non-missing values."}
        if len(values) > 5000:
            values = np.random.default_rng(42).choice(values, 5000, replace=False)
        stat, p = stats.shapiro(values)

        return {
            "test_name": "Shapiro-Wilk",
            "statistic": float(stat),
            "p_value": float(p),
            "is_normal": p > 0.05,
            "interpretation": (
                f"{var_name} 呈常態分佈 (W={stat:.4f}, p={p:.4f})"
                if p > 0.05
                else f"{var_name} 非常態分佈 (W={stat:.4f}, p={p:.4f})"
            ),
        }

    def _pearson(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        x_name, y_name = variables[0], variables[1]
        valid = df[[x_name, y_name]].dropna()
        r, p = stats.pearsonr(valid[x_name], valid[y_name])

        return {
            "test_name": "Pearson correlation",
            "statistic": float(r),
            "p_value": float(p),
            "effect_size": float(r),
            "effect_size_name": "r",
            "sample_size": len(valid),
            "interpretation": self._interpret_correlation(r, p),
        }

    def _spearman(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        x_name, y_name = variables[0], variables[1]
        valid = df[[x_name, y_name]].dropna()
        r, p = stats.spearmanr(valid[x_name], valid[y_name])

        return {
            "test_name": "Spearman correlation",
            "statistic": float(r),
            "p_value": float(p),
            "effect_size": float(r),
            "effect_size_name": "rho",
            "sample_size": len(valid),
            "interpretation": self._interpret_correlation(r, p),
        }

    def _levene(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups_series = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_arrays = [g for g in groups_series]
        stat, p = stats.levene(*group_arrays)

        return {
            "test_name": "Levene's test",
            "statistic": float(stat),
            "p_value": float(p),
            "equal_variance": p > 0.05,
            "interpretation": (
                f"變異數齊性成立 (F={stat:.4f}, p={p:.4f})"
                if p > 0.05
                else f"變異數不齊性 (F={stat:.4f}, p={p:.4f})"
            ),
        }

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _cohens_d(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = len(a), len(b)
        pooled_std = np.sqrt(
            ((na - 1) * np.std(a, ddof=1) ** 2 + (nb - 1) * np.std(b, ddof=1) ** 2)
            / (na + nb - 2)
        )
        if pooled_std == 0:
            return 0.0
        return float((np.mean(a) - np.mean(b)) / pooled_std)

    @staticmethod
    def _hedges_g(a: np.ndarray, b: np.ndarray) -> float:
        """Hedges' g — bias-corrected Cohen's d for small samples."""
        na, nb = len(a), len(b)
        d = ScipyStatisticalEngine._cohens_d(a, b)
        df = na + nb - 2
        if df <= 0:
            return d
        correction = 1 - 3 / (4 * df - 1)
        return float(d * correction)

    @staticmethod
    def _interpret_comparison(p: float, effect: float, effect_name: str) -> str:
        sig = "有顯著差異" if p < 0.05 else "無顯著差異"
        return f"兩組{sig} (p = {p:.4f}, {effect_name} = {effect:.3f})"

    @staticmethod
    def _interpret_correlation(r: float, p: float) -> str:
        strength = "強" if abs(r) > 0.7 else ("中等" if abs(r) > 0.3 else "弱")
        direction = "正" if r > 0 else "負"
        sig = "顯著" if p < 0.05 else "不顯著"
        return f"{sig}的{strength}{direction}相關 (r = {r:.4f}, p = {p:.4f})"

    # ── post-hoc tests ───────────────────────────────────────────────

    def _tukey_hsd(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        """Tukey HSD post-hoc test for ANOVA follow-up."""
        from scipy import stats

        outcome, group = variables[0], variables[1]
        groups_series = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_labels = list(groups_series.index)
        group_arrays = [g for g in groups_series]

        if len(group_arrays) < 3:
            return {"error": "Tukey HSD 需要 ≥3 組。使用 t-test 比較 2 組。"}

        result = stats.tukey_hsd(*group_arrays)

        pairwise: list[dict] = []
        for i in range(len(group_labels)):
            for j in range(i + 1, len(group_labels)):
                p_val = float(result.pvalue[i][j])
                stat_val = float(result.statistic[i][j])
                d = self._cohens_d(group_arrays[i], group_arrays[j])
                pairwise.append({
                    "group_1": str(group_labels[i]),
                    "group_2": str(group_labels[j]),
                    "statistic": stat_val,
                    "p_value": p_val,
                    "significant": p_val < kw.get("alpha", 0.05),
                    "effect_size": float(d),
                    "effect_size_name": "Cohen's d",
                })

        return {
            "test_name": "Tukey HSD",
            "pairwise_comparisons": pairwise,
            "n_comparisons": len(pairwise),
            "group_labels": [str(g) for g in group_labels],
            "sample_sizes": [len(g) for g in group_arrays],
            "interpretation": (
                f"Tukey HSD: {sum(1 for p in pairwise if p['significant'])}/"
                f"{len(pairwise)} 對比較達顯著差異"
            ),
        }

    def _dunn(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        """Dunn's test — non-parametric post-hoc for Kruskal-Wallis follow-up."""
        from scipy import stats
        from itertools import combinations

        outcome, group = variables[0], variables[1]
        groups_series = df.groupby(group)[outcome].apply(
            lambda x: x.dropna().values
        )
        group_labels = list(groups_series.index)
        group_arrays = [g for g in groups_series]

        if len(group_arrays) < 3:
            return {"error": "Dunn's test 需要 ≥3 組。使用 Mann-Whitney U 比較 2 組。"}

        # Dunn's test using Bonferroni correction on pairwise Mann-Whitney
        alpha = kw.get("alpha", 0.05)
        n_pairs = len(list(combinations(range(len(group_arrays)), 2)))
        adjusted_alpha = alpha / n_pairs  # Bonferroni

        pairwise: list[dict] = []
        for i, j in combinations(range(len(group_arrays)), 2):
            a, b = group_arrays[i], group_arrays[j]
            stat_val, p_raw = stats.mannwhitneyu(a, b, alternative="two-sided")
            p_adj = min(p_raw * n_pairs, 1.0)  # Bonferroni adjusted
            n = len(a) + len(b)
            r = abs(stat_val - (len(a) * len(b) / 2)) / (len(a) * len(b)) if n > 0 else 0

            pairwise.append({
                "group_1": str(group_labels[i]),
                "group_2": str(group_labels[j]),
                "statistic": float(stat_val),
                "p_value_raw": float(p_raw),
                "p_value_adjusted": float(p_adj),
                "significant": p_adj < alpha,
                "effect_size": float(r),
                "effect_size_name": "rank-biserial r",
            })

        return {
            "test_name": "Dunn's test (Bonferroni)",
            "pairwise_comparisons": pairwise,
            "n_comparisons": len(pairwise),
            "correction": "bonferroni",
            "group_labels": [str(g) for g in group_labels],
            "sample_sizes": [len(g) for g in group_arrays],
            "interpretation": (
                f"Dunn's test: {sum(1 for p in pairwise if p['significant'])}/"
                f"{len(pairwise)} 對比較達顯著差異 (Bonferroni 校正)"
            ),
        }

    def _point_biserial(
        self, df: pd.DataFrame, variables: list[str], **kw: Any
    ) -> dict[str, Any]:
        """Point-biserial correlation between binary and continuous variable."""
        from scipy import stats

        continuous, binary = variables[0], variables[1]
        valid = df[[continuous, binary]].dropna()

        # Encode binary as 0/1 if needed
        col = valid[binary]
        if col.dtype == "object" or col.dtype.name == "category":
            unique = col.unique()
            if len(unique) != 2:
                return {"error": f"'{binary}' 不是二元變數 (唯一值={len(unique)})"}
            col = col.map({unique[0]: 0, unique[1]: 1})

        r, p = stats.pointbiserialr(col, valid[continuous])

        return {
            "test_name": "Point-biserial correlation",
            "statistic": float(r),
            "p_value": float(p),
            "effect_size": float(r),
            "effect_size_name": "r_pb",
            "sample_size": len(valid),
            "interpretation": self._interpret_correlation(float(r), float(p)),
        }

    # ── power analysis ───────────────────────────────────────────────

    def post_hoc_power(
        self,
        test_name: str,
        effect_size: float,
        n: int,
        n_groups: int = 2,
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        """Compute post-hoc statistical power (S-010)."""
        from scipy import stats

        power = 0.0
        if test_name in ("Independent t-test", "Mann-Whitney U"):
            # Two-sample: use noncentrality parameter
            ncp = effect_size * np.sqrt(n / (2 * n_groups))
            crit = stats.t.ppf(1 - alpha / 2, df=n - 2)
            power = 1 - stats.t.cdf(crit, df=n - 2, loc=ncp) + stats.t.cdf(-crit, df=n - 2, loc=ncp)
        elif test_name in ("One-way ANOVA", "Kruskal-Wallis"):
            # F-test: f2 = eta2 / (1 - eta2)
            f2 = effect_size / (1 - effect_size) if effect_size < 1 else effect_size
            df1 = n_groups - 1
            df2 = n - n_groups
            if df2 > 0:
                lam = f2 * n  # noncentrality
                crit = stats.f.ppf(1 - alpha, df1, df2)
                power = 1 - stats.ncf.cdf(crit, df1, df2, lam)
        elif test_name in ("Chi-squared", "Fisher's exact"):
            # Chi-sq: w = sqrt(chi2/n), noncentrality = n*w^2
            lam = n * effect_size ** 2
            df_val = max(1, n_groups - 1)
            crit = stats.chi2.ppf(1 - alpha, df_val)
            power = 1 - stats.ncx2.cdf(crit, df_val, lam)
        else:
            # Generic: normal approximation
            z_alpha = stats.norm.ppf(1 - alpha / 2)
            z_power = effect_size * np.sqrt(n) - z_alpha
            power = float(stats.norm.cdf(z_power))

        power = max(0.0, min(1.0, float(power)))

        if power >= 0.8:
            interp = f"檢定力足夠 ({power:.1%})。結果可信。"
        elif power >= 0.5:
            interp = f"檢定力中等 ({power:.1%})。結果需謹慎解讀。"
        else:
            interp = f"檢定力不足 ({power:.1%})。可能存在 Type II error，建議增加樣本量。"

        return {
            "power": power,
            "alpha": alpha,
            "effect_size": effect_size,
            "n": n,
            "n_groups": n_groups,
            "interpretation": interp,
            "adequate": power >= 0.8,
        }

    # ── missing data pattern analysis ────────────────────────────────

    def analyze_missing_patterns(
        self,
        data: Any,
        variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze missing data patterns (S-005: MCAR/MAR/MNAR)."""
        df: pd.DataFrame = data
        if variables:
            cols = [c for c in variables if c in df.columns]
        else:
            cols = df.columns.tolist()

        missing_counts = df[cols].isna().sum()
        cols_with_missing = [c for c in cols if missing_counts[c] > 0]

        if not cols_with_missing:
            return {
                "pattern": "no_missing",
                "interpretation": "無缺失值，無需分析缺失模式。",
                "variables_with_missing": [],
            }

        # Missing data pattern matrix
        n = len(df)
        patterns: dict[str, dict] = {}
        for col in cols_with_missing:
            mc = int(missing_counts[col])
            patterns[col] = {
                "n_missing": mc,
                "missing_rate": mc / n,
            }

        # Little's MCAR test approximation:
        # If missing in one variable is independent of observed values in others
        from scipy import stats

        mcar_evidence = True
        correlation_results: list[dict] = []
        numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]

        for target in cols_with_missing:
            indicator = df[target].isna().astype(int)
            for predictor in numeric_cols:
                if predictor == target:
                    continue
                valid_mask = df[predictor].notna()
                if valid_mask.sum() < 10:
                    continue
                try:
                    stat, p = stats.pointbiserialr(
                        indicator[valid_mask], df[predictor][valid_mask]
                    )
                    if p < 0.05:
                        mcar_evidence = False
                        correlation_results.append({
                            "missing_var": target,
                            "predictor": predictor,
                            "r": float(stat),
                            "p_value": float(p),
                        })
                except Exception:
                    pass

        # Determine pattern type
        if not cols_with_missing:
            pattern_type = "complete"
            interpretation = "資料完整，無缺失值。"
        elif mcar_evidence:
            pattern_type = "MCAR"
            interpretation = (
                "缺失值可能為完全隨機 (MCAR)。"
                "Complete case analysis 或多重插補皆適用。"
            )
        elif correlation_results:
            # MAR: missing depends on observed variables
            pattern_type = "MAR"
            interpretation = (
                "缺失值可能與觀測值有關 (MAR)。"
                "建議使用多重插補 (Multiple Imputation)，避免 listwise deletion。"
            )
        else:
            pattern_type = "unknown"
            interpretation = "無法確定缺失模式。建議人工檢視並考慮多重插補。"

        return {
            "pattern": pattern_type,
            "interpretation": interpretation,
            "variables_with_missing": list(patterns.keys()),
            "variable_details": patterns,
            "mcar_evidence": mcar_evidence,
            "significant_correlations": correlation_results,
            "recommendation": (
                "Complete case analysis" if pattern_type == "MCAR"
                else "Multiple Imputation" if pattern_type == "MAR"
                else "需人工判斷"
            ),
        }
