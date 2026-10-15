"""Read-only Welch NI reports and one-sided figures from frozen numerical receipts."""

from pathlib import Path

import pandas as pd

from .fixed_publication import flow_table, render
from .report import cell, number


TITLE = "獨立兩組均差非劣性分析"
DECISIONS = {
    "noninferiority_demonstrated": ("支持預先指定界值下的非劣性", "Noninferiority demonstrated"),
    "noninferiority_not_demonstrated": ("未能證明非劣性", "Noninferiority not demonstrated"),
    "boundary_not_demonstrated": (
        "位於數值界值；不宣稱非劣性",
        "At the decision boundary; NI not demonstrated",
    ),
}


def flow(result):
    ledger = result["case_ledger"]
    return [
        {"stage": "Original source subjects", "subjects": ledger["input_rows"]},
        {
            "stage": "Incomplete required roles",
            "subjects": len(ledger["missing_excluded_data_rows"]),
        },
        {"stage": "Shared complete subjects", "subjects": result["n"]},
    ]


def required_figures(result):
    return {"clinical_noninferiority_flow", "clinical_noninferiority_effect"}


def effect_row(result):
    inference = result["noninferiority"]
    # Scalars only: keep the drawing CSV directly comparable with the receipt.
    return {key: value for key, value in inference.items() if not isinstance(value, (dict, list))}


def markdown(result):
    spec, inference = result["spec"], result["noninferiority"]
    lines = [
        f"## {TITLE}",
        "",
        f"研究情境：{cell(spec['context'])}。",
        f"處置：{cell(spec['treatment_definition'])}；對照原碼 {cell(spec['treatment_levels'][0])}，處置原碼 {cell(spec['treatment_levels'][1])}。",
        f"終點：{cell(spec['outcome_definition'])}；時間窗：{cell(spec['outcome_window'])}；單位：{cell(spec['outcome_unit'])}。",
        f"預先指定方向：{cell(spec['direction'])}；正的有利方向差異代表處置較好。",
        f"分析族群定義：{cell(spec['population_definition'])}；完整個案不表示 ITT／PP 成員資格已驗證。",
        "### 個案納入與排除",
        "",
        "| 步驟 | 受試者數 |",
        "|---|---:|",
    ]
    lines += [
        f"| {label} | {row['subjects']} |"
        for label, row in zip(["來源列", "必要角色缺失", "共同完整個案"], flow(result), strict=True)
    ]
    lines += [
        "",
        "### 各組固定分析個案",
        "",
        "| 角色 | 原始代碼 | n | 平均值 | 樣本變異數 |",
        "|---|---|---:|---:|---:|",
    ]
    lines += [
        f"| {cell(row['role'])} | {cell(row['label'])} | {row['n']} | {number(row['mean'])} | {number(row['sample_variance'])} |"
        for row in result["groups"]
    ]
    lines += [
        "",
        "### 預先指定界值與單側推論",
        "",
        f"Margin={number(spec['margin'])} {cell(spec['outcome_unit'])}，依據：{cell(spec['margin_basis'])}。此計算不驗證其臨床合理性。",
        f"虛無假設：有利方向差異 ≤ −{number(spec['margin'])}；對立假設：有利方向差異 > −{number(spec['margin'])}。",
        f"原始處置−對照均差={number(inference['raw_treatment_minus_control'])}；有利方向差異={number(inference['benefit_difference'])}。",
        f"單側 alpha={number(spec['one_sided_alpha'])}；Welch t={number(inference['statistic'])}，df={number(inference['degrees_of_freedom'])}，單側 p={number(inference['p_value'])}。",
        f"{spec['confidence_level']:.1%} **單側下限**={number(inference['lower_confidence_bound'])}；上限無界（+∞），不是同水準的雙側 CI。",
        f"**結論：{DECISIONS[inference['decision']][0]}。**",
        "計算已完成。非劣性未獲支持或位於界值均保留完整成果，不是執行失敗；也不能據此宣稱已證明劣效。",
        "界值等號不通過；檢定與下限共同決策，不以 superiority 的非顯著 p 值代替 NI。",
        "### 解讀與適用範圍",
        "",
    ]
    lines += [f"- {cell(note)}" for note in result["warnings"]]
    lines += [
        "",
        f"- 數值收據 SHA256：`{result['receipt_sha256']}`",
        f"- 規格 SHA256：`{result['spec_sha256']}`",
        f"- 來源欄位／列 SHA256：`{result['dataframe_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    missing = set(result["case_ledger"]["missing_excluded_data_rows"])
    data = {
        "participants": [
            {"data_row": i, "status": "missing_required" if i in missing else "included"}
            for i in range(1, result["case_ledger"]["input_rows"] + 1)
        ],
        "observations": result["observations"],
        "groups": [
            {k: v for k, v in group.items() if k != "data_rows"} for group in result["groups"]
        ],
        "inference": [effect_row(result)],
        "hypothesis": result["hypotheses"],
    }
    paths = []
    for label, rows in data.items():
        path = directory / f"{prefix}_noninferiority_{label}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        paths.append(path)
    return paths


def figures(result, directory, prefix, preset_id="journal-neutral-english-v1", edition=None):
    spec, inference = result["spec"], result["noninferiority"]
    source = (
        f"Study context: {spec['context']}. n={result['n']} shared complete independent subjects. "
        f"T0 (control)={spec['treatment_levels'][0]!r}; T1 (treatment)={spec['treatment_levels'][1]!r}. "
        f"Outcome: {spec['outcome_definition']}; window: {spec['outcome_window']}; unit: {spec['outcome_unit']}. "
    )

    def draw(new, save):
        fig, axes = new(65)
        flow_table(axes[0], flow(result))
        save(
            fig,
            "flow",
            "Prespecified complete-case participant flow.",
            source
            + "Identity and all observed treatment codes and outcome values are checked before missing-role exclusion. No imputation or automatic ITT/per-protocol classification is performed.",
            "身份與原始代碼先核對，必要角色缺失才剔除；完整個案不等於已確認ITT或PP族群。",
            flow(result),
        )
        fig, axes = new(85)
        ax = axes[0]
        estimate, lower, margin = (
            inference["benefit_difference"],
            inference["lower_confidence_bound"],
            spec["margin"],
        )
        left, right = min(lower, -margin, 0, estimate), max(lower, -margin, 0, estimate)
        span = max(right - left, inference["standard_error"], margin)
        left, right = left - 0.18 * span, right + 0.45 * span
        ax.set_xlim(left, right)
        ax.set_ylim(-0.65, 1)
        ax.axvline(
            -margin, color="#a23c32", linestyle="--", linewidth=1, label="NI boundary (-margin)"
        )
        ax.axvline(0, color="#888888", linestyle=":", linewidth=0.8, label="No mean difference")
        ax.plot([estimate], [0], "o", color="#176e68", label="Benefit-oriented mean difference")
        ax.plot([lower], [0], "|", color="#176e68", markersize=14)
        ax.annotate(
            "",
            xy=(right - 0.05 * span, 0),
            xytext=(lower, 0),
            arrowprops={"arrowstyle": "->", "color": "#176e68", "linewidth": 1.2},
        )
        ax.text(
            0.99, 0.28, "Upper bound: +infinity", transform=ax.transAxes, ha="right", fontsize=9
        )
        ax.text(
            0.02,
            0.05,
            DECISIONS[inference["decision"]][1],
            transform=ax.transAxes,
            fontsize=9,
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 3},
        )
        ax.set_yticks([0], [f"{spec['confidence_level']:.1%} one-sided\nconfidence set"])
        ax.set_xlabel("Benefit difference (original outcome units; positive favors treatment)")
        ax.legend(
            loc="upper left",
            frameon=True,
            facecolor="white",
            edgecolor="none",
            framealpha=1,
            fontsize=8,
        )
        caption = (
            source
            + f"Saved Welch mean NI inference. Direction={spec['direction']}; benefit difference={estimate:.6g}, "
            f"one-sided {spec['confidence_level']:.1%} lower bound={lower:.6g}, upper bound=+infinity. "
            f"Margin={margin:.6g} in original outcome units; basis: {spec['margin_basis']}. "
            f"One-sided alpha={spec['one_sided_alpha']:.6g}; one-sided p={inference['p_value']:.6g}. "
            f"{DECISIONS[inference['decision']][1]}. Arrow indicates the unbounded confidence set, not a finite upper endpoint. "
            "Equality at the NI boundary does not pass. Completion does not imply NI success; failure to demonstrate NI does not prove inferiority. No two-sided CI or superiority-p substitution."
        )
        save(
            fig,
            "effect",
            "Welch mean noninferiority with a one-sided lower confidence bound.",
            caption,
            "點為有利方向均差，短直線是單側下限，箭頭表示上界無限；紅虛線是預先指定非劣性界值。下限必須嚴格高於界值才可支持非劣性，計算完成不等於非劣性成立。",
            [effect_row(result)],
        )

    return render(result, directory, prefix, "noninferiority", draw, preset_id, edition)
