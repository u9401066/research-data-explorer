"""Frozen matching receipts to tables, English publication figures and Chinese explanations."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .fixed_publication import blocks, flow_table, render
from .report import cell, number

TITLE = "傾向分數配對與配對群聚推論"


def flow(result):
    ledger, pop = result["case_ledger"], result["matching_population"]
    return [
        {"stage": "Original source rows", "subjects": ledger["input_rows"]},
        {
            "stage": "Outside prespecified cohort",
            "subjects": len(ledger["filter_excluded_data_rows"]),
        },
        {"stage": "Missing required roles", "subjects": len(ledger["missing_excluded_data_rows"])},
        {"stage": "Complete cases before matching", "subjects": pop["complete_cases"]},
        {"stage": "Unmatched treated", "subjects": pop["unmatched_treated"]},
        {"stage": "Unused controls", "subjects": pop["unmatched_controls"]},
        {"stage": "Matched analysis subjects (two per pair)", "subjects": result["n"]},
    ]


def balance_rows(result):
    return [
        {**r, "alias": f"V{i+1}", "source_type": "covariate"}
        for i, r in enumerate(result["balance"])
    ] + [
        {**r, "alias": f"B{i+1}", "source_type": "model_basis"}
        for i, r in enumerate(result["basis_balance"])
    ]


def required_figures(result):
    return {
        "clinical_matching_flow",
        "clinical_matching_overlap",
        "clinical_matching_effect",
        *[f"clinical_matching_balance_{key}" for key, _ in blocks(balance_rows(result), 10)],
    }


def markdown(result):
    spec, effect, pop = result["spec"], result["effect"], result["matching_population"]
    lines = [
        f"## {TITLE}",
        "",
        f"研究情境：{cell(spec['context'])}。",
        f"處置定義：{cell(spec['treatment_definition'])}；終點：{cell(spec['outcome_definition'])}；時間窗：{cell(spec['outcome_window'])}。",
        f"處置原碼：{cell(spec['treatment_levels'][1])}；對照原碼：{cell(spec['treatment_levels'][0])}。方向固定為處置減對照。",
        "### 個案納入與排除",
        "",
        "| 步驟 | 人數 |",
        "|---|---:|",
    ]
    lines += [f"| {row['stage']} | {row['subjects']} |" for row in flow(result)]
    lines += [
        "",
        f"配對共 {pop['matched_pairs']} 對；分析 n={result['n']}，配對前完整個案 n={pop['complete_cases']}。",
        "**目標限於保留的 matched-treated 子族群，不能視為原全體 ATT 或 ATE。**",
        "完整逐列納排、未配對原因及雙方來源列／ID可在個案清單與配對表核對。結果值不參與配對，但終點是否缺失會影響完整個案族群。",
        "### 預先固定的配對與推論",
        "",
        f"1:1無放回，先最大化合法配對數，再最小化logit距離；caliper={spec['caliper_sd']} × 原完整個案兩組logit樣本變異平均之平方根（ddof=1），絕對界值={number(result['matching']['absolute_logit_caliper'])}。",
        "同分按固定來源ID排序並保留套件版本；零logit變異只允許精確分數配對，不自動加寬caliper。",
        f"{effect['measure']}={number(effect['estimate'])} {cell(spec['outcome_unit'])}；{spec['confidence_level']:.1%} 雙側CI [{number(effect['ci_lower'])}, {number(effect['ci_upper'])}]。",
        f"SE={number(effect['standard_error'])}；t={number(effect['statistic'])}，df={effect['df']}，雙側p={number(effect['p_value'])}。",
        "Treatment-only OLS，依pair群聚的CR1修正，t分布自由度G−1；不是精確配對t檢定或Abadie–Imbens 2016估PS校正。",
        "### 平衡、重疊與品質核對",
        "",
        "| 別名 | 原欄位／基底 | 原SMD | 配對後SMD | 核對原因 |",
        "|---|---|---:|---:|---|",
    ]
    lines += [
        f"| {r['alias']} | {cell(r.get('column', r.get('term')))} {cell(r.get('level') or '')} | {number(r['smd'])} | {number(r['matched_smd'])} | {cell(', '.join(r['review_reasons']) or '無固定規則旗標；不等於已證明有效')} |"
        for r in balance_rows(result)
    ]
    lines += [
        "",
        "前後SMD固定用原完整個案treated標準差；零SD保留未知。完整分布、ECDF差、變異比與分數直方圖保存在結果及下載表。",
        "固定品質規則：少於5對不執行；少於30對或二元discordant少於10對須審閱；|SMD|>0.1、連續變數變異比不在[0.5,2]或無法定義均標示。這些不是power門檻或因果有效證明。",
        f"本次旗標：{cell(', '.join(result['diagnostics']['review_flags']) or '無固定規則旗標')}。",
    ]
    if result["paired_binary"]:
        binary = result["paired_binary"]
        lines += [
            "",
            f"二元配對四格（列=對照0/1，欄=處置0/1）：{binary['cells']}；discordant={binary['discordant_pairs']}。來源0/1定義：{cell(spec['outcome_levels'])}。",
            "區間為機率差的近似區間；若超出[-1,1]也不偷偷截斷或改檢定。",
        ]
    lines += ["### 解讀與適用範圍", ""] + [f"- {cell(note)}" for note in result["limitations"]]
    lines += [
        "",
        f"- 數值收據 SHA256：`{result['receipt_sha256']}`",
        f"- 規格 SHA256：`{result['spec_sha256']}`",
        f"- 來源欄位／列 SHA256：`{result['dataframe_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def _flat(row):
    return {
        k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (list, dict)) else v
        for k, v in row.items()
    }


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "participants": result["source_case_ledger"],
        "pairs": result["pairs"],
        "balance": balance_rows(result),
        "overlap": result["diagnostics"]["propensity_histogram"],
        "effect": [result["effect"]],
        "quality": [result["diagnostics"]["quality_policy"]],
        "paired_binary": [result["paired_binary"]]
        if result["paired_binary"]
        else [{"status": "not_applicable_continuous"}],
    }
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_matching_{name}.csv"
        pd.DataFrame([_flat(row) for row in rows]).to_csv(path, index=False)
        paths.append(path)
    return paths


def figures(result, directory, prefix, preset_id="journal-neutral-english-v1", edition=None):
    rows, effect = balance_rows(result), result["effect"]
    aliases = {
        row["alias"]: {k: row[k] for k in ["column", "level", "term", "source_type"] if k in row}
        for row in rows
    }
    source = "Frozen prespecified 1:1 matching without replacement. Target: retained matched-treated subset, not the original population ATT. Original-language definitions and code aliases are retained separately. "

    def draw(new, save):
        fig, axes = new(95)
        flow_table(axes[0], flow(result))
        save(
            fig,
            "flow",
            "Prespecified matching population flow.",
            source
            + "Outcome availability affects complete-case inclusion; outcome values never enter propensity fitting or assignment. Unmatched cases remain in the downloadable ledger.",
            "完整個案與配對後族群分開列示，未配對不會消失；完整個案不等於缺失可忽略。",
            flow(result),
        )
        for key, selected in blocks(rows, 10):
            fig, axes = new(95)
            ax = axes[0]
            for ordinal, row in enumerate(selected):
                for field, marker, color, shift in [
                    ("smd", "o", "#777777", -0.1),
                    ("matched_smd", "s", "#176e68", 0.1),
                ]:
                    value = row[field]
                    if value is not None:
                        ax.scatter(abs(value), ordinal + shift, marker=marker, color=color, s=25)
                    else:
                        ax.text(0.02, ordinal + shift, "undefined SD", fontsize=8)
            ax.axvline(0.1, color="#ad5240", linestyle="--", linewidth=0.8)
            ax.set_yticks(np.arange(len(selected)), [row["alias"] for row in selected])
            ax.invert_yaxis()
            ax.set_xlabel("Absolute SMD (fixed original treated SD)")
            ax.plot([], [], "o", color="#777777", label="Before matching")
            ax.plot([], [], "s", color="#176e68", label="After matching")
            ax.legend(loc="best", fontsize=8)
            save(
                fig,
                f"balance_{key}",
                "Covariate and propensity-basis balance.",
                source
                + "V aliases identify original covariates/levels; B aliases identify prespecified model bases. Standardization is fixed before matching. Dashed line is a review threshold, not proof of exchangeability; zero SD remains undefined.",
                "原始共變數及模型基底均核對；固定原treated分母，不能把零SD填成平衡。",
                [
                    {
                        k: r[k]
                        for k in [
                            "alias",
                            "source_type",
                            "smd",
                            "matched_smd",
                            "standardization_sd",
                        ]
                    }
                    for r in selected
                ],
            )
        fig, axes = new(100, rows=2)
        for code, ax in enumerate(axes):
            hist = [
                r
                for r in result["diagnostics"]["propensity_histogram"]
                if r["treatment_code"] == code
            ]
            centers = [(r["left"] + r["right"]) / 2 for r in hist]
            ax.step(
                centers,
                [r["eligible_proportion"] for r in hist],
                where="mid",
                color="#777777",
                label="Complete cases",
            )
            ax.step(
                centers,
                [r["matched_proportion"] for r in hist],
                where="mid",
                color="#176e68",
                label="Matched cases",
            )
            ax.set_ylabel(f"T{code} proportion")
            ax.set_xlim(0, 1)
            ax.legend(fontsize=8)
        axes[-1].set_xlabel("Estimated propensity score; 20 fixed bins")
        save(
            fig,
            "overlap",
            "Propensity score distributions before and after matching.",
            source
            + "Separate within-group proportions use their own displayed populations; no smoothing, clipping or automatic common-support trimming. Score overlap does not establish covariate balance or positivity.",
            "各組分別用完整個案與配對個案分母顯示；分數重疊不證明共變數平衡或無混雜。",
            result["diagnostics"]["propensity_histogram"],
        )
        fig, axes = new(70)
        ax = axes[0]
        ax.errorbar(
            [effect["estimate"]],
            [0],
            xerr=[
                [effect["estimate"] - effect["ci_lower"]],
                [effect["ci_upper"] - effect["estimate"]],
            ],
            fmt="o",
            color="#176e68",
            capsize=4,
        )
        ax.axvline(0, color="#777777", linestyle="--")
        ax.set_yticks([0], ["Matched-treated\ncontrast"])
        ax.set_xlabel(
            "Risk difference (treated - control)"
            if effect["measure"] == "risk_difference"
            else "Mean difference (treated - control; original units)"
        )
        save(
            fig,
            "effect",
            "Matched-treated contrast with pair-cluster uncertainty.",
            source
            + f"Treatment-only OLS; CR1 covariance by pair, two-sided {effect['confidence_level']:.1%} interval with t({effect['df']}) inference. Estimate={effect['estimate']:.6g}, SE={effect['standard_error']:.6g}, p={effect['p_value']:.6g}. Approximate inference does not fully adjust propensity-estimation uncertainty or ensure finite-sample coverage. No clipping of interval bounds.",
            "效果方向固定處置減對照；此為配對群聚近似區間，不能外推原全體ATT或宣稱精確有限樣本推論。",
            [{k: v for k, v in effect.items() if not isinstance(v, (dict, list))}],
        )

    return render(
        result,
        directory,
        prefix,
        "matching",
        draw,
        preset_id,
        edition,
        {
            "variable_aliases": aliases,
            "treatment_aliases": dict(
                zip(["T0", "T1"], result["spec"]["treatment_levels"], strict=True)
            ),
            "outcome_levels": result["spec"]["outcome_levels"],
        },
    )
