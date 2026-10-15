"""Frozen CMH/MH estimates with full original stratum tables and honest boundaries."""

from pathlib import Path
import pandas as pd

from .fixed_publication import blocks, flow_table, render
from .report import cell, number


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


def count_rows(result):
    return [
        {
            "stratum": row["label"],
            "stratum_alias": f"S{i+1}",
            "treatment": row["row_levels"][arm],
            "outcome": row["column_levels"][event],
            "subjects": row["table"][arm][event],
            "expected_under_independence": row["expected_under_independence"][arm][event],
            "stratum_n": row["n"],
        }
        for i, row in enumerate(result["strata"])
        for arm in range(2)
        for event in range(2)
    ]


def required_figures(result):
    return {
        "clinical_stratified_flow",
        "clinical_stratified_effect",
        *[f"clinical_stratified_tables_{key}" for key, _ in blocks(result["strata"], 8)],
    }


def markdown(result):
    spec, effect = result["spec"], result["common_odds_ratio"]
    lines = [
        "## 分層二元比較：CMH 與共同勝算比",
        "",
        f"研究情境：{cell(spec['context'])}。",
        f"處置定義：{cell(spec['treatment_definition'])}。結果定義：{cell(spec['outcome_definition'])}；窗口：{cell(spec['outcome_window'])}。",
        f"比較方向：{cell(spec['treatment_levels'][1])} 相對 {cell(spec['treatment_levels'][0])}；事件原碼 {cell(spec['outcome_levels'][1])}。分層欄位：{cell(spec['strata'])}。",
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
        "所有宣告層都保留；不合併、不加0.5、不以缺失排除掩蓋身份或代碼問題。",
        "### 每層原始 2×2 表",
        "",
        "| 層 | 處置原碼 | 結果原碼 | 個案數 | 獨立假設期望數 |",
        "|---|---|---|---:|---:|",
    ]
    lines += [
        f"| {cell(r['stratum'])} | {cell(r['treatment'])} | {cell(r['outcome'])} | {r['subjects']} | {number(r['expected_under_independence'])} |"
        for r in count_rows(result)
    ]
    lines += [
        "",
        "### 主要 CMH 與 MH 共同勝算比",
        "",
        f"CMH χ²={number(result['cmh']['statistic'])}，df=1，p={number(result['cmh']['p_value'])}。單一事先指定主要假設；無連續性校正。",
        f"MH OR={number(effect['estimate'])}；狀態={cell(effect['status'])}；邊界={cell(effect['boundary'])}。",
        f"{spec['confidence_level']:.1%} CI：{number(effect['ci_lower'])} 至 {number(effect['ci_upper'])}；{cell(effect['ci_status'])}。{cell(effect.get('reason', ''))}",
        f"區間方法：{cell(effect['ci_method'])}。",
        "### 異質性診斷",
        "",
        f"Breslow–Day/Tarone：{cell(result['equal_odds']['status'])}；p={number(result['equal_odds']['p_value'])}。{cell(result['equal_odds'].get('reason', ''))}",
        "診斷不作為選擇是否呈現主要結果的門檻；未顯著或不可估不證明同質性。",
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
    missing = set(result["case_ledger"]["missing_excluded_data_rows"])
    data = {
        "participants": [
            {"data_row": i, "status": "missing_required" if i in missing else "included"}
            for i in range(1, result["case_ledger"]["input_rows"] + 1)
        ],
        "observations": result["observations"],
        "counts": count_rows(result),
        "effect": [result["common_odds_ratio"]],
        "cmh": [result["cmh"]],
        "equal_odds": [result["equal_odds"]],
    }
    paths = []
    for label, rows in data.items():
        path = directory / f"{prefix}_stratified_{label}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        paths.append(path)
    return paths


def figures(result, directory, prefix, preset_id="journal-neutral-english-v1", edition=None):
    spec, effect = result["spec"], result["common_odds_ratio"]
    source = (
        f"Study context: {spec['context']}. n={result['n']} shared complete independent subjects. Treatment T0={spec['treatment_levels'][0]!r}, T1={spec['treatment_levels'][1]!r}; outcome Y0={spec['outcome_levels'][0]!r}, Y1={spec['outcome_levels'][1]!r}. "
        + "; ".join(f"S{i+1}={r['label']!r}" for i, r in enumerate(result["strata"]))
        + ". "
    )

    def draw(new, save):
        fig, axes = new(65)
        flow_table(axes[0], flow(result))
        save(
            fig,
            "flow",
            "Shared complete-case participant flow.",
            source
            + "Identity and all observed source codes are validated before missing-role exclusion. No stratum is merged or omitted; no imputation is performed.",
            "所有分層使用共同完整人口，身份和非法代碼先核對；沒有補值或默默刪層。",
            flow(result),
        )
        for key, strata in blocks(result["strata"], 8):
            rows = [r for r in count_rows(result) if r["stratum"] in {s["label"] for s in strata}]
            fig, axes = new(max(70, 25 + 8 * len(strata)))
            ax = axes[0]
            ax.axis("off")
            rendered = [
                [
                    f"S{result['strata'].index(r)+1}",
                    *[str(v) for row in r["table"] for v in row],
                    str(r["n"]),
                ]
                for r in strata
            ]
            table = ax.table(
                cellText=rendered,
                colLabels=["Stratum", "T0/Y0", "T0/Y1", "T1/Y0", "T1/Y1", "N"],
                cellLoc="center",
                loc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.8)
            save(
                fig,
                f"tables_{key}",
                "Unmodified binary counts in each prespecified stratum.",
                source
                + "Columns are exact source 2x2 counts in declared order. No 0.5 correction or stratum pooling is applied. Expected counts are in the drawing data; cells below five warrant review of asymptotic inference.",
                "保存每層原始2×2格數；期望格數在下載表中，稀疏層沒有自動合併或加常數。",
                rows,
            )
        fig, axes = new(65)
        ax = axes[0]
        ax.set_xscale("log")
        from matplotlib.ticker import LogLocator, NullFormatter, ScalarFormatter

        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_yticks([0], ["Common OR"])
        ax.set_ylim(-0.7, 0.7)
        if effect["status"] == "estimated":
            ax.axvline(1, color="#777777", linestyle="dashed", linewidth=0.7)
            ax.plot(effect["estimate"], 0, "o", color="#176e68")
            if effect["ci_status"] == "estimated":
                ax.hlines(0, effect["ci_lower"], effect["ci_upper"], color="#176e68")
            else:
                ax.text(0.02, 0.85, "Confidence interval unavailable", transform=ax.transAxes)
            values = [1, effect["estimate"]]
            if effect["ci_status"] == "estimated":
                values += [effect["ci_lower"], effect["ci_upper"]]
            ax.set_xlim(min(values) / 1.4, max(values) * 1.4)
        else:
            ax.set_xlim(0.1, 10)
            ax.text(
                0.02,
                0.85,
                "OR = 0 (log scale undefined); CI unavailable"
                if effect["boundary"] == "zero"
                else "Unbounded OR; finite estimate/CI unavailable",
                transform=ax.transAxes,
            )
        ax.set_xlabel("Mantel-Haenszel common odds ratio (T1 vs T0)")
        save(
            fig,
            "effect",
            "Common odds ratio and pointwise uncertainty.",
            source
            + f"Saved MH common OR for event Y1 in T1 relative to T0. {effect['ci_method']}. Confidence level={spec['confidence_level']:.1%}. OR boundaries and unavailable intervals remain explicit; no artificial point or zero-width CI. OR is not RR, RD or a causal effect. Primary CMH p={result['cmh']['p_value']:.6g}; equal-odds is diagnostic, not a reporting gate.",
            "共同OR與區間來自保存值；無限或零邊界不畫成有限點，不是RR、RD或因果效果。",
            [effect],
        )

    return render(result, directory, prefix, "stratified", draw, preset_id, edition)
