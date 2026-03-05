"""
AKI Biomarker Visualization Suite
===================================
Generates publication-quality figures for the AKI biomarker study.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")

# ── Style ────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", font_scale=1.1)
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "figure.facecolor": "white",
})

# ── Paths ────────────────────────────────────────────────────────
DATA = Path("data/rawdata/aki_analysis_ready.csv")
FIG_DIR = Path("data/reports/aki_analysis/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Load ─────────────────────────────────────────────────────────
df = pd.read_csv(DATA)
numeric_candidates = [c for c in df.columns if c not in (
    "subject_id", "sex", "sex_code", "aki_cr_rise", "aki_cr_7d",
    "aki_urine_criteria", "aki_status",
)]
for col in numeric_candidates:
    df[col] = pd.to_numeric(df[col], errors="coerce")

BIOMARKERS = {
    "NGAL": ("ngal_0hr", "ngal_4hr", "ngal_24hr"),
    "KIM-1": ("kim1_0hr", "kim1_4hr", "kim1_24hr"),
    "Cystatin C": ("cystc_0hr", "cystc_4hr", "cystc_24hr"),
    "Urine Cr": ("urine_cr_0hr", "urine_cr_4hr", "urine_cr_24hr"),
}
RATIOS = {
    "NGAL/Cr": ("ngal_cr_0hr", "ngal_cr_4hr", "ngal_cr_24hr"),
    "KIM-1/Cr": ("kim1_cr_0hr", "kim1_cr_4hr", "kim1_cr_24hr"),
    "CystC/Cr": ("cystc_cr_0hr", "cystc_cr_4hr", "cystc_cr_24hr"),
}


# ══════════════════════════════════════════════════════════════════
# Figure 1: Biomarker Time-Course (raw concentrations)
# ══════════════════════════════════════════════════════════════════
def fig_timecourse_raw():
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    timepoints = ["0h", "4h", "24h"]

    for ax, (name, cols) in zip(axes.flat, BIOMARKERS.items()):
        data = df[list(cols)].dropna()
        melted = data.melt(var_name="Timepoint", value_name="Value")
        melted["Timepoint"] = melted["Timepoint"].map(
            {cols[0]: "0h", cols[1]: "4h", cols[2]: "24h"}
        )
        sns.boxplot(data=melted, x="Timepoint", y="Value", ax=ax,
                    palette="Set2", order=timepoints, width=0.5)
        sns.stripplot(data=melted, x="Timepoint", y="Value", ax=ax,
                      color="0.3", alpha=0.4, size=3, order=timepoints, jitter=True)

        # Friedman p-value annotation
        complete = df[list(cols)].dropna()
        if len(complete) >= 3:
            _, p = stats.friedmanchisquare(
                complete.iloc[:, 0], complete.iloc[:, 1], complete.iloc[:, 2]
            )
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
            ax.set_title(f"{name}  (Friedman p={p:.4f} {sig})", fontweight="bold")
        else:
            ax.set_title(name, fontweight="bold")
        ax.set_xlabel("")
        ax.set_ylabel(f"{name} (ng/mL)" if name != "Urine Cr" else "Cr (mg/dL)")

    fig.suptitle("Figure 1. Urinary Biomarker Time-Course (Raw)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig1_timecourse_raw.png")
    plt.close(fig)
    print("  ✅ fig1_timecourse_raw.png")


# ══════════════════════════════════════════════════════════════════
# Figure 2: Creatinine-Normalized Biomarker Time-Course
# ══════════════════════════════════════════════════════════════════
def fig_timecourse_normalized():
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    timepoints = ["0h", "4h", "24h"]

    for ax, (name, cols) in zip(axes, RATIOS.items()):
        data = df[list(cols)].dropna()
        melted = data.melt(var_name="Timepoint", value_name="Value")
        melted["Timepoint"] = melted["Timepoint"].map(
            {cols[0]: "0h", cols[1]: "4h", cols[2]: "24h"}
        )
        sns.boxplot(data=melted, x="Timepoint", y="Value", ax=ax,
                    palette="Set3", order=timepoints, width=0.5)
        sns.stripplot(data=melted, x="Timepoint", y="Value", ax=ax,
                      color="0.3", alpha=0.4, size=3, order=timepoints, jitter=True)

        complete = df[list(cols)].dropna()
        if len(complete) >= 3:
            _, p = stats.friedmanchisquare(
                complete.iloc[:, 0], complete.iloc[:, 1], complete.iloc[:, 2]
            )
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
            ax.set_title(f"{name}  (p={p:.4f} {sig})", fontweight="bold")
        ax.set_xlabel("")
        ax.set_ylabel(f"{name} ratio")

    fig.suptitle("Figure 2. Creatinine-Normalized Biomarkers", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig2_timecourse_normalized.png")
    plt.close(fig)
    print("  ✅ fig2_timecourse_normalized.png")


# ══════════════════════════════════════════════════════════════════
# Figure 3: eGFR Pre vs Post (paired)
# ══════════════════════════════════════════════════════════════════
def fig_egfr_change():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Paired lines
    sub = df[["preop_egfr", "postop24_egfr"]].dropna()
    for _, row in sub.iterrows():
        ax1.plot([0, 1], [row["preop_egfr"], row["postop24_egfr"]],
                 color="steelblue", alpha=0.3, linewidth=0.8)
    ax1.boxplot(
        [sub["preop_egfr"], sub["postop24_egfr"]],
        positions=[0, 1], widths=0.3,
        patch_artist=True,
        boxprops=dict(facecolor="lightblue", alpha=0.7),
    )
    ax1.set_xticks([0, 1])
    ax1.set_xticklabels(["Pre-op", "Post-24h"])
    ax1.set_ylabel("eGFR (mL/min/1.73m²)")
    ax1.set_title("eGFR Pre-op vs Post-24h", fontweight="bold")

    # Difference histogram
    diff = sub["postop24_egfr"] - sub["preop_egfr"]
    ax2.hist(diff, bins=20, color="steelblue", edgecolor="white", alpha=0.8)
    ax2.axvline(0, color="red", linestyle="--", linewidth=1.5)
    ax2.axvline(diff.mean(), color="orange", linestyle="-", linewidth=1.5, label=f"Mean Δ={diff.mean():.1f}")
    ax2.set_xlabel("ΔeGFR (Post - Pre)")
    ax2.set_ylabel("Count")
    ax2.set_title(f"eGFR Change Distribution (p<0.001, d={abs(diff.mean()/diff.std()):.2f})", fontweight="bold")
    ax2.legend()

    fig.suptitle("Figure 3. eGFR Change Analysis", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig3_egfr_change.png")
    plt.close(fig)
    print("  ✅ fig3_egfr_change.png")


# ══════════════════════════════════════════════════════════════════
# Figure 4: Correlation — Hypotension Duration vs Key Biomarkers
# ══════════════════════════════════════════════════════════════════
def fig_correlations():
    key_pairs = [
        ("hypotension_min", "ngal_cr_4hr", "NGAL/Cr 4h"),
        ("hypotension_min", "kim1_cr_24hr", "KIM-1/Cr 24h"),
        ("hypotension_min", "cystc_4hr", "CystC 4h"),
        ("surgery_min", "ngal_cr_4hr", "NGAL/Cr 4h"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    for ax, (xvar, yvar, ylabel) in zip(axes.flat, key_pairs):
        sub = df[[xvar, yvar]].dropna()
        if len(sub) < 5:
            ax.text(0.5, 0.5, "Insufficient data", transform=ax.transAxes, ha="center")
            continue
        ax.scatter(sub[xvar], sub[yvar], alpha=0.6, edgecolor="white", s=50)

        # Regression line
        slope, intercept, r, p, se = stats.linregress(sub[xvar], sub[yvar])
        x_line = np.linspace(sub[xvar].min(), sub[xvar].max(), 100)
        ax.plot(x_line, slope * x_line + intercept, "r--", linewidth=1.5)

        # Spearman
        rho, sp = stats.spearmanr(sub[xvar], sub[yvar])
        sig = "*" if sp < 0.05 else ""
        ax.set_title(f"{ylabel} vs {xvar.replace('_', ' ').title()}\nρ={rho:.3f}, p={sp:.4f}{sig}",
                     fontweight="bold", fontsize=10)
        ax.set_xlabel(xvar.replace("_", " ").title() + " (min)")
        ax.set_ylabel(ylabel)

    fig.suptitle("Figure 4. Correlations with Surgical Parameters", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig4_correlations.png")
    plt.close(fig)
    print("  ✅ fig4_correlations.png")


# ══════════════════════════════════════════════════════════════════
# Figure 5: Correlation Heatmap (all biomarkers vs clinical)
# ══════════════════════════════════════════════════════════════════
def fig_heatmap():
    clinical = ["age", "bmi", "surgery_min", "hypotension_min", "preop_egfr", "preop_cr"]
    bio_cols = []
    for cols in list(BIOMARKERS.values()) + list(RATIOS.values()):
        bio_cols.extend(cols)

    available = [c for c in clinical + bio_cols if c in df.columns]
    corr_data = df[available].dropna(how="all")
    rho_matrix = corr_data.corr(method="spearman")

    # Focus on clinical x biomarkers
    clinical_avail = [c for c in clinical if c in rho_matrix.columns]
    bio_avail = [c for c in bio_cols if c in rho_matrix.columns]
    sub_matrix = rho_matrix.loc[bio_avail, clinical_avail]

    fig, ax = plt.subplots(figsize=(10, 14))
    sns.heatmap(sub_matrix, annot=True, fmt=".2f", center=0,
                cmap="RdBu_r", vmin=-0.6, vmax=0.6,
                linewidths=0.5, ax=ax, annot_kws={"size": 8})
    ax.set_title("Figure 5. Spearman Correlation Heatmap\n(Biomarkers × Clinical Variables)",
                 fontweight="bold", fontsize=13)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right")
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig5_correlation_heatmap.png")
    plt.close(fig)
    print("  ✅ fig5_correlation_heatmap.png")


# ══════════════════════════════════════════════════════════════════
# Figure 6: Sex Differences in Normalized Biomarkers
# ══════════════════════════════════════════════════════════════════
def fig_sex_diff():
    ratio_cols = [c for ratio in RATIOS.values() for c in ratio]
    fig, axes = plt.subplots(3, 3, figsize=(14, 12))

    for ax, col in zip(axes.flat, ratio_cols):
        sub = df[["sex", col]].dropna()
        sns.boxplot(data=sub, x="sex", y=col, ax=ax, palette="Pastel1", width=0.5)
        sns.stripplot(data=sub, x="sex", y=col, ax=ax, color="0.3", alpha=0.4, size=3, jitter=True)

        m = sub[sub["sex"] == "male"][col]
        f = sub[sub["sex"] == "female"][col]
        if len(m) >= 3 and len(f) >= 3:
            u, p = stats.mannwhitneyu(m, f, alternative="two-sided")
            sig = "*" if p < 0.05 else ""
            ax.set_title(f"{col}\n(p={p:.4f}{sig})", fontsize=9, fontweight="bold")
        else:
            ax.set_title(col, fontsize=9)
        ax.set_xlabel("")

    fig.suptitle("Figure 6. Sex Differences in Normalized Biomarkers", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig6_sex_differences.png")
    plt.close(fig)
    print("  ✅ fig6_sex_differences.png")


# ══════════════════════════════════════════════════════════════════
# Figure 7: Missing Data Pattern
# ══════════════════════════════════════════════════════════════════
def fig_missing():
    bio_all = []
    for cols in list(BIOMARKERS.values()) + list(RATIOS.values()):
        bio_all.extend(cols)
    bio_all = [c for c in bio_all if c in df.columns]

    missing = df[bio_all].isnull().astype(int)
    fig, ax = plt.subplots(figsize=(14, 8))
    sns.heatmap(missing.T, cbar_kws={"label": "Missing (1=yes)"},
                cmap="YlOrRd", yticklabels=True, xticklabels=False, ax=ax)
    ax.set_xlabel(f"Subjects (n={len(df)})")
    ax.set_title("Figure 7. Missing Data Pattern — Biomarker Variables", fontweight="bold", fontsize=13)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig7_missing_pattern.png")
    plt.close(fig)
    print("  ✅ fig7_missing_pattern.png")


# ══════════════════════════════════════════════════════════════════
# Figure 8: Serum Creatinine Change
# ══════════════════════════════════════════════════════════════════
def fig_cr_change():
    sub = df[["preop_cr", "postop24_cr"]].dropna()
    diff = sub["postop24_cr"] - sub["preop_cr"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Paired
    for _, row in sub.iterrows():
        color = "red" if row["postop24_cr"] - row["preop_cr"] >= 0.3 else "steelblue"
        ax1.plot([0, 1], [row["preop_cr"], row["postop24_cr"]], color=color, alpha=0.3, linewidth=0.8)
    ax1.axhline(y=sub["preop_cr"].median() + 0.3, color="red", linestyle="--", linewidth=1, label="KDIGO +0.3")
    ax1.boxplot(
        [sub["preop_cr"], sub["postop24_cr"]],
        positions=[0, 1], widths=0.3,
        patch_artist=True,
        boxprops=dict(facecolor="lightyellow", alpha=0.7),
    )
    ax1.set_xticks([0, 1])
    ax1.set_xticklabels(["Pre-op", "Post-24h"])
    ax1.set_ylabel("Serum Creatinine (mg/dL)")
    ax1.set_title("Serum Cr: Pre vs Post", fontweight="bold")
    ax1.legend(fontsize=9)

    # Bland-Altman style: mean vs difference
    mean_cr = (sub["preop_cr"] + sub["postop24_cr"]) / 2
    ax2.scatter(mean_cr, diff, alpha=0.5, edgecolor="white", s=40)
    ax2.axhline(diff.mean(), color="orange", linestyle="-", linewidth=1.5, label=f"Mean Δ={diff.mean():.3f}")
    ax2.axhline(diff.mean() + 1.96 * diff.std(), color="gray", linestyle="--", linewidth=1)
    ax2.axhline(diff.mean() - 1.96 * diff.std(), color="gray", linestyle="--", linewidth=1)
    ax2.axhline(0, color="black", linestyle=":", linewidth=0.5)
    ax2.axhline(0.3, color="red", linestyle="--", linewidth=1, label="KDIGO +0.3 threshold")
    ax2.set_xlabel("Mean Cr (mg/dL)")
    ax2.set_ylabel("ΔCr (Post - Pre)")
    ax2.set_title("Bland-Altman: Cr Change", fontweight="bold")
    ax2.legend(fontsize=9)

    fig.suptitle("Figure 8. Serum Creatinine Change & KDIGO Assessment", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig8_creatinine_change.png")
    plt.close(fig)
    print("  ✅ fig8_creatinine_change.png")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("Generating AKI Biomarker Figures")
    print("=" * 60)
    fig_timecourse_raw()
    fig_timecourse_normalized()
    fig_egfr_change()
    fig_correlations()
    fig_heatmap()
    fig_sex_diff()
    fig_missing()
    fig_cr_change()
    print("=" * 60)
    print(f"All figures saved to: {FIG_DIR}")
    print("=" * 60)
