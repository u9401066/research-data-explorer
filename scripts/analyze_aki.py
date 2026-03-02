"""
AKI Biomarker Analysis — Full EDA Pipeline
============================================
Study: Urinary biomarkers for subclinical AKI after controlled hypotension
         during orthognathic surgery

This script runs a complete 11-Phase-like analysis directly.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Paths ────────────────────────────────────────────────────────
DATA = Path("data/rawdata/aki_analysis_ready.csv")
OUT = Path("data/reports/aki_analysis")
OUT.mkdir(parents=True, exist_ok=True)

# ── Load ─────────────────────────────────────────────────────────
df = pd.read_csv(DATA)
# Coerce numeric columns that may contain non-numeric values like 'X'
numeric_candidates = [c for c in df.columns if c not in (
    "subject_id", "sex", "sex_code", "aki_cr_rise", "aki_cr_7d",
    "aki_urine_criteria", "aki_status",
)]
for col in numeric_candidates:
    df[col] = pd.to_numeric(df[col], errors="coerce")
print(f"Loaded {len(df)} subjects × {len(df.columns)} variables")


# ══════════════════════════════════════════════════════════════════
# 1) TABLE 1 — Baseline Characteristics
# ══════════════════════════════════════════════════════════════════
def make_table1(df: pd.DataFrame) -> str:
    """Generate Table 1: Demographics and surgical characteristics."""
    lines = []
    lines.append("# Table 1. Baseline Characteristics (N=69)")
    lines.append("")
    lines.append("| Variable | Value |")
    lines.append("|----------|-------|")

    def fmt_continuous(col, unit=""):
        vals = df[col].dropna()
        n = len(vals)
        # Shapiro-Wilk for normality
        if n >= 3:
            sw_stat, sw_p = stats.shapiro(vals)
            normal = sw_p > 0.05
        else:
            normal = False
        if normal:
            s = f"{vals.mean():.1f} ± {vals.std():.1f}"
            note = "mean ± SD"
        else:
            s = f"{vals.median():.1f} ({vals.quantile(0.25):.1f}–{vals.quantile(0.75):.1f})"
            note = "median (IQR)"
        return f"{s} {unit} [{note}], n={n}"

    def fmt_categorical(col):
        vc = df[col].value_counts()
        parts = [f"{k}: {v} ({v/len(df)*100:.1f}%)" for k, v in vc.items()]
        return ", ".join(parts)

    # Demographics
    lines.append(f"| Age (years) | {fmt_continuous('age')} |")
    lines.append(f"| Sex | {fmt_categorical('sex')} |")
    lines.append(f"| Height (cm) | {fmt_continuous('height_cm')} |")
    lines.append(f"| Weight (kg) | {fmt_continuous('weight_kg')} |")
    lines.append(f"| BMI (kg/m²) | {fmt_continuous('bmi')} |")
    lines.append(f"| ASA | {fmt_categorical('asa')} |")

    # Surgical
    lines.append(f"| Surgery time (min) | {fmt_continuous('surgery_min', 'min')} |")
    lines.append(f"| Hypotension time (min) | {fmt_continuous('hypotension_min', 'min')} |")
    if "hypotensive_drug" in df.columns:
        drug = df["hypotensive_drug"].dropna()
        lines.append(f"| Hypotensive drug | {fmt_categorical('hypotensive_drug')} |")

    # Renal function
    lines.append(f"| Pre-op BUN | {fmt_continuous('preop_bun')} |")
    lines.append(f"| Pre-op Creatinine | {fmt_continuous('preop_cr')} |")
    lines.append(f"| Pre-op eGFR | {fmt_continuous('preop_egfr')} |")
    lines.append(f"| Post-24h BUN | {fmt_continuous('postop24_bun')} |")
    lines.append(f"| Post-24h Creatinine | {fmt_continuous('postop24_cr')} |")
    lines.append(f"| Post-24h eGFR | {fmt_continuous('postop24_egfr')} |")

    # AKI
    if "aki_status" in df.columns:
        lines.append(f"| AKI status | {fmt_categorical('aki_status')} |")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 2) BIOMARKER TIME-COURSE ANALYSIS
# ══════════════════════════════════════════════════════════════════
def analyze_biomarker_timecourse(df: pd.DataFrame) -> str:
    """Analyze biomarker changes across 0h → 4h → 24h."""
    lines = []
    lines.append("# Biomarker Time-Course Analysis")
    lines.append("")

    biomarkers = {
        "NGAL": ("ngal_0hr", "ngal_4hr", "ngal_24hr"),
        "KIM-1": ("kim1_0hr", "kim1_4hr", "kim1_24hr"),
        "Cystatin C": ("cystc_0hr", "cystc_4hr", "cystc_24hr"),
        "Urine Creatinine": ("urine_cr_0hr", "urine_cr_4hr", "urine_cr_24hr"),
        "NGAL/Cr": ("ngal_cr_0hr", "ngal_cr_4hr", "ngal_cr_24hr"),
        "KIM-1/Cr": ("kim1_cr_0hr", "kim1_cr_4hr", "kim1_cr_24hr"),
        "Cystatin C/Cr": ("cystc_cr_0hr", "cystc_cr_4hr", "cystc_cr_24hr"),
    }

    results = {}

    for name, (c0, c4, c24) in biomarkers.items():
        lines.append(f"\n## {name}")
        lines.append("")

        # Complete cases for repeated measures
        complete = df[[c0, c4, c24]].dropna()
        n = len(complete)

        if n < 5:
            lines.append(f"⚠️ Only {n} complete cases — insufficient for analysis")
            continue

        vals_0 = complete[c0].values
        vals_4 = complete[c4].values
        vals_24 = complete[c24].values

        # Descriptive
        lines.append(f"| Timepoint | n | Median (IQR) | Mean ± SD |")
        lines.append(f"|-----------|---|--------------|-----------|")
        for tp_name, vals in [("0h", vals_0), ("4h", vals_4), ("24h", vals_24)]:
            med = np.median(vals)
            q1, q3 = np.percentile(vals, [25, 75])
            lines.append(
                f"| {tp_name} | {len(vals)} | {med:.2f} ({q1:.2f}–{q3:.2f}) | {np.mean(vals):.2f} ± {np.std(vals):.2f} |"
            )

        # Normality check (Shapiro-Wilk)
        norms = {}
        for tp_name, vals in [("0h", vals_0), ("4h", vals_4), ("24h", vals_24)]:
            _, p = stats.shapiro(vals)
            norms[tp_name] = p > 0.05

        all_normal = all(norms.values())
        lines.append(f"\nNormality (Shapiro-Wilk): {'All normal' if all_normal else 'Non-normal detected'}")

        # Friedman test (non-parametric repeated measures)
        try:
            friedman_stat, friedman_p = stats.friedmanchisquare(vals_0, vals_4, vals_24)
            lines.append(f"\n**Friedman test**: χ² = {friedman_stat:.3f}, p = {friedman_p:.4f}")

            # Effect size: Kendall's W
            k = 3  # timepoints
            n_subj = n
            w = friedman_stat / (n_subj * (k - 1))
            lines.append(f"**Kendall's W** = {w:.3f}")

            if friedman_p < 0.05:
                lines.append(f"→ **顯著差異** across timepoints")

                # Post-hoc: Wilcoxon signed-rank pairwise
                pairs = [("0h vs 4h", vals_0, vals_4), ("0h vs 24h", vals_0, vals_24), ("4h vs 24h", vals_4, vals_24)]
                lines.append(f"\nPost-hoc Wilcoxon signed-rank (Bonferroni α = {0.05/3:.4f}):")
                for pair_name, a, b in pairs:
                    w_stat, w_p = stats.wilcoxon(a, b)
                    # Effect size r = Z / sqrt(N)
                    z = stats.norm.ppf(w_p / 2)
                    r = abs(z) / np.sqrt(n)
                    sig = "✅" if w_p < 0.05/3 else "—"
                    lines.append(f"  {pair_name}: W={w_stat:.1f}, p={w_p:.4f}, r={r:.3f} {sig}")
            else:
                lines.append("→ 無顯著差異 across timepoints")
        except Exception as e:
            lines.append(f"⚠️ Friedman test failed: {e}")

        # Store results
        results[name] = {
            "n": n,
            "friedman_p": float(friedman_p) if 'friedman_p' in dir() else None,
            "median_0h": float(np.median(vals_0)),
            "median_4h": float(np.median(vals_4)),
            "median_24h": float(np.median(vals_24)),
        }

    return "\n".join(lines), results


# ══════════════════════════════════════════════════════════════════
# 3) eGFR CHANGE ANALYSIS
# ══════════════════════════════════════════════════════════════════
def analyze_egfr_change(df: pd.DataFrame) -> str:
    """Analyze eGFR change pre-op vs post-24h."""
    lines = []
    lines.append("# eGFR Change Analysis")
    lines.append("")

    complete = df[["preop_egfr", "postop24_egfr"]].dropna()
    n = len(complete)
    lines.append(f"Complete cases: {n}")

    if n < 5:
        lines.append("⚠️ Insufficient data")
        return "\n".join(lines)

    pre = complete["preop_egfr"].values
    post = complete["postop24_egfr"].values
    diff = post - pre

    lines.append(f"\n| Metric | Pre-op | Post-24h | Difference |")
    lines.append(f"|--------|--------|----------|------------|")
    lines.append(
        f"| Mean ± SD | {np.mean(pre):.1f} ± {np.std(pre):.1f} | "
        f"{np.mean(post):.1f} ± {np.std(post):.1f} | "
        f"{np.mean(diff):.1f} ± {np.std(diff):.1f} |"
    )
    lines.append(
        f"| Median (IQR) | {np.median(pre):.1f} ({np.percentile(pre,25):.1f}–{np.percentile(pre,75):.1f}) | "
        f"{np.median(post):.1f} ({np.percentile(post,25):.1f}–{np.percentile(post,75):.1f}) | "
        f"{np.median(diff):.1f} ({np.percentile(diff,25):.1f}–{np.percentile(diff,75):.1f}) |"
    )

    # Normality of difference
    _, sw_p = stats.shapiro(diff)
    lines.append(f"\nNormality of difference (Shapiro-Wilk): p = {sw_p:.4f}")

    if sw_p > 0.05:
        t_stat, t_p = stats.ttest_rel(pre, post)
        lines.append(f"**Paired t-test**: t = {t_stat:.3f}, p = {t_p:.4f}")
        d = np.mean(diff) / np.std(diff)
        lines.append(f"**Cohen's d** = {d:.3f}")
    else:
        w_stat, w_p = stats.wilcoxon(pre, post)
        lines.append(f"**Wilcoxon signed-rank**: W = {w_stat:.1f}, p = {w_p:.4f}")
        z = stats.norm.ppf(w_p / 2)
        r = abs(z) / np.sqrt(n)
        lines.append(f"**Effect size r** = {r:.3f}")

    # Clinical significance
    lines.append(f"\neGFR decline > 25%: {(diff / pre < -0.25).sum()}/{n}")
    lines.append(f"eGFR decline > 15%: {(diff / pre < -0.15).sum()}/{n}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 4) CORRELATION: Hypotension Duration vs Biomarkers
# ══════════════════════════════════════════════════════════════════
def analyze_correlations(df: pd.DataFrame) -> str:
    """Correlation between hypotension duration and biomarker levels."""
    lines = []
    lines.append("# Correlation Analysis: Hypotension Duration vs Biomarkers")
    lines.append("")

    bio_cols = [c for c in df.columns if c.startswith(("ngal_", "kim1_", "cystc_")) and "clarity" not in c and "volume" not in c]

    lines.append("| Biomarker | n | Spearman ρ | p-value | Interpretation |")
    lines.append("|-----------|---|------------|---------|----------------|")

    for col in sorted(bio_cols):
        pair = df[["hypotension_min", col]].dropna()
        n = len(pair)
        if n < 10:
            continue
        rho, p = stats.spearmanr(pair["hypotension_min"], pair[col])
        interp = ""
        if p < 0.05:
            if abs(rho) >= 0.5:
                interp = "強相關 ✅"
            elif abs(rho) >= 0.3:
                interp = "中度相關 ✅"
            else:
                interp = "弱相關"
        else:
            interp = "無顯著相關"
        sig = "**" if p < 0.05 else ""
        lines.append(f"| {col} | {n} | {sig}{rho:.3f}{sig} | {p:.4f} | {interp} |")

    # Also correlate surgery_min
    lines.append("")
    lines.append("## Surgery Duration vs Biomarkers")
    lines.append("")
    lines.append("| Biomarker | n | Spearman ρ | p-value | Interpretation |")
    lines.append("|-----------|---|------------|---------|----------------|")

    for col in sorted(bio_cols):
        pair = df[["surgery_min", col]].dropna()
        n = len(pair)
        if n < 10:
            continue
        rho, p = stats.spearmanr(pair["surgery_min"], pair[col])
        interp = ""
        if p < 0.05:
            if abs(rho) >= 0.5:
                interp = "強相關 ✅"
            elif abs(rho) >= 0.3:
                interp = "中度相關 ✅"
            else:
                interp = "弱相關"
        else:
            interp = "無顯著相關"
        sig = "**" if p < 0.05 else ""
        lines.append(f"| {col} | {n} | {sig}{rho:.3f}{sig} | {p:.4f} | {interp} |")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 5) SUBGROUP: Drug Type Analysis
# ══════════════════════════════════════════════════════════════════
def analyze_drug_subgroups(df: pd.DataFrame) -> str:
    """Compare biomarkers by hypotensive drug type."""
    lines = []
    lines.append("# Subgroup Analysis: Hypotensive Drug Type")
    lines.append("")

    drug = df[df["hypotensive_drug"].notna()].copy()
    drug["drug_label"] = drug["hypotensive_drug"].map(
        {1: "NTG", 2: "Trandate", 3: "NTG+Trandate"}
    )
    lines.append(f"Drug distribution: {dict(drug['drug_label'].value_counts())}")
    lines.append("")

    groups = drug.groupby("drug_label")
    group_names = sorted(drug["drug_label"].unique())

    if len(group_names) < 2:
        lines.append("⚠️ Only one drug group — cannot compare")
        return "\n".join(lines)

    bio_markers = ["ngal_cr_0hr", "ngal_cr_4hr", "ngal_cr_24hr",
                   "kim1_cr_0hr", "kim1_cr_4hr", "kim1_cr_24hr",
                   "cystc_cr_0hr", "cystc_cr_4hr", "cystc_cr_24hr"]

    lines.append("| Biomarker | Test | Statistic | p-value | Sig? |")
    lines.append("|-----------|------|-----------|---------|------|")

    for col in bio_markers:
        group_data = [g[col].dropna().values for _, g in groups if len(g[col].dropna()) >= 3]
        if len(group_data) < 2:
            continue

        if len(group_names) == 2:
            u_stat, u_p = stats.mannwhitneyu(group_data[0], group_data[1], alternative="two-sided")
            test_name = "Mann-Whitney U"
            stat_val = f"U={u_stat:.1f}"
        else:
            h_stat, h_p = stats.kruskal(*group_data)
            test_name = "Kruskal-Wallis"
            stat_val = f"H={h_stat:.2f}"
            u_p = h_p

        sig = "✅" if u_p < 0.05 else ""
        lines.append(f"| {col} | {test_name} | {stat_val} | {u_p:.4f} | {sig} |")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 6) Cr CHANGE: Pre-op vs Post-24h
# ══════════════════════════════════════════════════════════════════
def analyze_cr_change(df: pd.DataFrame) -> str:
    """Analyze serum creatinine change."""
    lines = []
    lines.append("# Serum Creatinine Change Analysis")
    lines.append("")

    # Need to handle 'X' and other non-numeric values
    for c in ["preop_cr", "postop24_cr"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    complete = df[["preop_cr", "postop24_cr"]].dropna()
    n = len(complete)
    lines.append(f"Complete cases: {n}")

    if n < 5:
        lines.append("⚠️ Insufficient data")
        return "\n".join(lines)

    pre = complete["preop_cr"].values
    post = complete["postop24_cr"].values
    diff = post - pre
    pct_change = (diff / pre) * 100

    lines.append(f"\n| Metric | Pre-op | Post-24h | Change |")
    lines.append(f"|--------|--------|----------|--------|")
    lines.append(
        f"| Mean ± SD | {np.mean(pre):.3f} ± {np.std(pre):.3f} | "
        f"{np.mean(post):.3f} ± {np.std(post):.3f} | "
        f"{np.mean(diff):.3f} ± {np.std(diff):.3f} |"
    )

    # Test
    _, sw_p = stats.shapiro(diff)
    if sw_p > 0.05:
        t, p = stats.ttest_rel(pre, post)
        lines.append(f"\nPaired t-test: t = {t:.3f}, p = {p:.4f}")
        d = np.mean(diff) / np.std(diff)
        lines.append(f"Cohen's d = {d:.3f}")
    else:
        w, p = stats.wilcoxon(pre, post)
        lines.append(f"\nWilcoxon signed-rank: W = {w:.1f}, p = {p:.4f}")
        z = stats.norm.ppf(p / 2)
        r = abs(z) / np.sqrt(n)
        lines.append(f"Effect size r = {r:.3f}")

    # AKI KDIGO Stage 1: Cr increase ≥ 0.3 mg/dL or ≥ 1.5× baseline
    cr_rise_03 = (diff >= 0.3).sum()
    cr_rise_15x = (post >= pre * 1.5).sum()
    lines.append(f"\nKDIGO AKI Stage 1:")
    lines.append(f"  Cr rise ≥ 0.3 mg/dL: {cr_rise_03}/{n} ({cr_rise_03/n*100:.1f}%)")
    lines.append(f"  Cr rise ≥ 1.5× baseline: {cr_rise_15x}/{n} ({cr_rise_15x/n*100:.1f}%)")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 7) SEX SUBGROUP
# ══════════════════════════════════════════════════════════════════
def analyze_sex_difference(df: pd.DataFrame) -> str:
    """Compare biomarker levels by sex."""
    lines = []
    lines.append("# Sex Difference in Biomarkers")
    lines.append("")

    sex_data = df[df["sex"].notna()]
    male = sex_data[sex_data["sex"] == "male"]
    female = sex_data[sex_data["sex"] == "female"]
    lines.append(f"Male: {len(male)}, Female: {len(female)}")
    lines.append("")

    bio_cols = [c for c in df.columns
                if c.startswith(("ngal_cr_", "kim1_cr_", "cystc_cr_"))
                and "clarity" not in c and "volume" not in c]

    lines.append("| Biomarker | Male median | Female median | U | p | Sig? |")
    lines.append("|-----------|-------------|---------------|---|---|------|")

    for col in sorted(bio_cols):
        m = male[col].dropna()
        f = female[col].dropna()
        if len(m) < 3 or len(f) < 3:
            continue
        u_stat, p = stats.mannwhitneyu(m, f, alternative="two-sided")
        sig = "✅" if p < 0.05 else ""
        lines.append(f"| {col} | {m.median():.4f} | {f.median():.4f} | {u_stat:.0f} | {p:.4f} | {sig} |")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 8) MISSING DATA ANALYSIS
# ══════════════════════════════════════════════════════════════════
def analyze_missing(df: pd.DataFrame) -> str:
    """Analyze missing data patterns."""
    lines = []
    lines.append("# Missing Data Analysis")
    lines.append("")

    miss = df.isnull().sum()
    miss_pct = miss / len(df) * 100

    lines.append("| Variable | Missing | % |")
    lines.append("|----------|---------|---|")
    for col in miss[miss > 0].sort_values(ascending=False).index:
        lines.append(f"| {col} | {miss[col]}/{len(df)} | {miss_pct[col]:.1f}% |")

    # Pattern: Are 4hr/24hr missing together?
    bio_4 = df["ngal_4hr"].isna()
    bio_24 = df["ngal_24hr"].isna()
    both_miss = (bio_4 & bio_24).sum()
    only_4 = (bio_4 & ~bio_24).sum()
    only_24 = (~bio_4 & bio_24).sum()
    lines.append(f"\n4hr & 24hr biomarker missing pattern:")
    lines.append(f"  Both missing: {both_miss}")
    lines.append(f"  Only 4hr missing: {only_4}")
    lines.append(f"  Only 24hr missing: {only_24}")
    lines.append(f"  Both available: {(~bio_4 & ~bio_24).sum()}")

    # MCAR test (approximate) — compare demographics of complete vs incomplete
    complete = df[~bio_4].copy()
    incomplete = df[bio_4].copy()
    lines.append(f"\nComplete (has 4hr): {len(complete)}, Incomplete: {len(incomplete)}")

    for col in ["age", "bmi", "surgery_min"]:
        c = complete[col].dropna()
        i = incomplete[col].dropna()
        if len(c) >= 3 and len(i) >= 3:
            u, p = stats.mannwhitneyu(c, i, alternative="two-sided")
            lines.append(f"  {col}: complete median={c.median():.1f} vs incomplete={i.median():.1f}, p={p:.3f}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# MAIN: Assemble Report
# ══════════════════════════════════════════════════════════════════
def main():
    print("="*60)
    print("AKI Biomarker Analysis — Full Report")
    print("="*60)

    report = []
    report.append(f"---")
    report.append(f"title: AKI Biomarker EDA Report")
    report.append(f"date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"subjects: {len(df)}")
    report.append(f"pipeline: RDE 11-Phase (Direct Execution)")
    report.append(f"---\n")

    # 1) Table 1
    print("\n[1/8] Table 1...")
    t1 = make_table1(df)
    report.append(t1)
    report.append("\n---\n")

    # 2) Biomarker time course
    print("[2/8] Biomarker time-course...")
    tc, tc_results = analyze_biomarker_timecourse(df)
    report.append(tc)
    report.append("\n---\n")

    # 3) eGFR
    print("[3/8] eGFR change...")
    egfr = analyze_egfr_change(df)
    report.append(egfr)
    report.append("\n---\n")

    # 4) Correlations
    print("[4/8] Correlations...")
    corr = analyze_correlations(df)
    report.append(corr)
    report.append("\n---\n")

    # 5) Drug subgroups
    print("[5/8] Drug subgroups...")
    drug = analyze_drug_subgroups(df)
    report.append(drug)
    report.append("\n---\n")

    # 6) Cr change
    print("[6/8] Creatinine change...")
    cr = analyze_cr_change(df)
    report.append(cr)
    report.append("\n---\n")

    # 7) Sex differences
    print("[7/8] Sex differences...")
    sex = analyze_sex_difference(df)
    report.append(sex)
    report.append("\n---\n")

    # 8) Missing data
    print("[8/8] Missing data...")
    miss = analyze_missing(df)
    report.append(miss)

    # Save report
    report_text = "\n".join(report)
    report_path = OUT / "eda_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\n✅ Report saved to: {report_path}")
    print(f"   {len(report_text)} chars, {report_text.count(chr(10))} lines")

    # Also print key findings
    print("\n" + "="*60)
    print("KEY FINDINGS SUMMARY")
    print("="*60)
    print(report_text)


if __name__ == "__main__":
    main()
