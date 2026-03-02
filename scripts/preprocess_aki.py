"""Pre-process AKI research Excel files into a clean analytical CSV.

Reads two Excel files from data/rawdata/ and produces a merged,
analysis-ready CSV at data/rawdata/aki_analysis_ready.csv.

This script does NOT modify original files.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import sys

RAW = Path("data/rawdata")

def find_files():
    files = sorted(RAW.glob("AKI_*.xlsx"))
    if len(files) < 2:
        print(f"Expected 2 AKI xlsx files, found {len(files)}")
        sys.exit(1)
    # File with '檢體紀錄' is the main specimen file
    specimen_file = [f for f in files if "檢體" in f.name][0]
    results_file = [f for f in files if "results" in f.name][0]
    return specimen_file, results_file


def load_clinical(specimen_file: Path) -> pd.DataFrame:
    """Load clinical data from 血檢數據 sheet."""
    df = pd.read_excel(specimen_file, sheet_name="血檢數據")
    # Filter valid cases (exclude test row and empty)
    df = df[df["實驗code"].notna()].copy()
    # Convert experiment code to string
    df["subject_id"] = df["實驗code"].astype(str).str.strip().str.zfill(2)

    # Clean column names for analysis
    rename = {
        "年齡(yr)": "age",
        "性別:1=男 2=女": "sex_code",
        "Sex": "sex",
        "身高": "height_cm",
        "體重": "weight_kg",
        "BMI": "bmi",
        "ASA: 1=I 2=II": "asa",
        "降血壓用藥\n1= NTG\n2=Trandate\n3=1+2": "hypotensive_drug",
        "NTG使用量ml": "ntg_ml",
        "Trandate使用量 mg": "trandate_mg",
        "手術時間(min)": "surgery_min",
        "低血壓時間(min)": "hypotension_min",
        "血檢BUN": "preop_bun",
        "血檢Creatinine": "preop_cr",
        "eGFR (PreOP)": "preop_egfr",
        "BUN": "postop24_bun",
        "CR": "postop24_cr",
        "eGFR(POh-24)": "postop24_egfr",
        "手術~壓血壓後24\n小時內尿量ml": "urine_24h_ml",
        "尿量均值<0.5ml\n持續24小時": "urine_rate_24h",
        "48小時內血清肌酸酐(Cr)上升0.3mg/dL或是1.5倍以上": "aki_cr_rise",
        "過去7天內血清肌酐酸(Cr)增加1.5倍": "aki_cr_7d",
        "尿量(Urine)小於0.5 ml/kg/hr持續6小時": "aki_urine_criteria",
    }
    # Keep only columns we can rename + subject_id
    keep = ["subject_id"] + [c for c in rename.keys() if c in df.columns]
    out = df[keep].copy()
    out = out.rename(columns=rename)

    # Derive AKI status (any criteria met = YES)
    for c in ["aki_cr_rise", "aki_cr_7d", "aki_urine_criteria"]:
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip().str.upper()

    # AKI = YES if any criterion is YES
    aki_cols = [c for c in ["aki_cr_rise", "aki_cr_7d", "aki_urine_criteria"] if c in out.columns]
    if aki_cols:
        out["aki_status"] = out[aki_cols].apply(
            lambda row: "YES" if any(v == "YES" for v in row) else "NO", axis=1
        )
    return out


def load_biomarkers(specimen_file: Path) -> pd.DataFrame:
    """Load biomarker data from 0hr/4hr/24hr sheets and merge wide."""
    dfs = {}
    for timepoint in ["0hr", "4hr", "24hr"]:
        df = pd.read_excel(specimen_file, sheet_name=timepoint)
        df = df[df["實驗code"].notna()].copy()
        df["subject_id"] = df["實驗code"].astype(str).str.strip().str.zfill(2)

        suffix = f"_{timepoint}"
        bio_cols = {
            "NGAL (normalized)": f"ngal{suffix}",
            "KIM-1 (normalized)": f"kim1{suffix}",
            "Cystatin C (normalized)": f"cystc{suffix}",
            "Creatinine (normalized)": f"urine_cr{suffix}",
            "NGAL(/Cr)-normalized": f"ngal_cr{suffix}",
            "KIM-1(/Cr)-normalized": f"kim1_cr{suffix}",
            "CystatinC(/Cr)-normalized": f"cystc_cr{suffix}",
            "採尿量 ml": f"urine_volume{suffix}",
            "尿液狀況\n1=清澈\n2=混濁": f"urine_clarity{suffix}",
        }
        keep = ["subject_id"] + [c for c in bio_cols.keys() if c in df.columns]
        sub = df[keep].copy()
        sub = sub.rename(columns=bio_cols)
        dfs[timepoint] = sub

    # Merge all timepoints
    merged = dfs["0hr"]
    for tp in ["4hr", "24hr"]:
        merged = merged.merge(dfs[tp], on="subject_id", how="outer")
    return merged


def main():
    specimen_file, results_file = find_files()
    print(f"Specimen: {specimen_file.name}")
    print(f"Results: {results_file.name}")

    # Load clinical data
    clinical = load_clinical(specimen_file)
    print(f"\nClinical: {len(clinical)} subjects, {len(clinical.columns)} columns")

    # Load biomarkers
    biomarkers = load_biomarkers(specimen_file)
    print(f"Biomarkers: {len(biomarkers)} subjects, {len(biomarkers.columns)} columns")

    # Merge
    merged = clinical.merge(biomarkers, on="subject_id", how="outer")
    print(f"\nMerged: {len(merged)} subjects, {len(merged.columns)} columns")

    # Summary
    print(f"\nColumns:\n{list(merged.columns)}")
    print(f"\nMissing per column:")
    miss = merged.isnull().sum()
    for col, n in miss[miss > 0].items():
        print(f"  {col}: {n}/{len(merged)} ({n/len(merged)*100:.0f}%)")

    if "aki_status" in merged.columns:
        print(f"\nAKI status: {dict(merged['aki_status'].value_counts())}")
    if "sex" in merged.columns:
        print(f"Sex: {dict(merged['sex'].value_counts())}")

    # Save
    out_path = RAW / "aki_analysis_ready.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved to: {out_path}")
    print(f"Shape: {merged.shape}")


if __name__ == "__main__":
    main()
