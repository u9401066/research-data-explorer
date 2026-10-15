"""MI reports and publication figures use saved estimates and traces only."""

from pathlib import Path

import pandas as pd

from .fixed_publication import blocks, flow_table, render
from .report import cell, number


def _model_scale(result):
    """The outcome model, never a predictor's binary coding, determines the scale."""
    if result["spec"]["distribution"] == "binomial":
        return (
            "二元結果 logistic 模型的預測變項係數為條件 log-odds；連續預測變項每增加一個來源單位，或二元預測變項編碼 1 相對 0，在其他模型預測變項固定下比較。exp 後為條件 OR（截距為參照 log-odds，exp 後為參照 odds），不是邊際 OR、風險比或風險差。",
            "The binary-outcome logistic model reports conditional log-odds coefficients: a continuous predictor per one source unit or a binary predictor coded 1 versus 0, holding the other model predictors fixed. Exponentiating predictor coefficients gives conditional odds ratios, not marginal odds ratios, risk ratios or risk differences. The intercept is reference log-odds with all model predictors set to zero.",
            "Pooled conditional log-odds coefficient",
        )
    return (
        f"連續結果 Gaussian OLS 模型的係數以結果 {cell(result['spec']['outcome'])} 的原始單位（{cell(result['spec']['outcome_unit'])}）表示。連續預測變項每增加一個來源單位，或二元預測變項編碼 1 相對 0，在其他模型預測變項固定下的係數是條件平均差，不是邊際平均差或因果效果；截距為所有模型預測變項取 0 時的參照平均數。",
        "The continuous-outcome Gaussian OLS model uses original outcome units (see the source-context mapping). Predictor coefficients are conditional mean differences for a continuous predictor per one source unit or a binary predictor coded 1 versus 0, holding the other model predictors fixed; they are not marginal effects or causal effects. The intercept is the reference mean with all model predictors set to zero.",
        "Pooled coefficient (original outcome units)",
    )


def flow(result):
    ledger = result["case_ledger"]
    return [
        {"stage": "Original source rows", "subjects": ledger["input_rows"]},
        {"stage": "Outside declared cohort", "subjects": len(ledger["filter_excluded_data_rows"])},
        {
            "stage": "Missing nonimputable roles",
            "subjects": len(ledger["missing_excluded_data_rows"]),
        },
        {"stage": "Subjects retained in every dataset", "subjects": result["n"]},
        {"stage": "Subjects with imputed cells", "subjects": len(ledger["imputed_data_rows"])},
        {
            "stage": "Original analysis-complete subjects",
            "subjects": len(ledger["analysis_complete_data_rows"]),
        },
    ]


def missing_rows(result):
    ledger = result["case_ledger"]
    return [
        {
            "column": column["column"],
            "label": f"V{i+1}",
            "missing_in_cohort": ledger["missing_by_role"][column["column"]],
            "imputed_per_dataset": sum(
                cell["column"] == column["column"] for cell in ledger["imputed_cells"]
            ),
            "imputation_permitted": column["impute"],
            "retained_subjects": result["n"],
        }
        for i, column in enumerate(result["spec"]["columns"])
    ]


def required_figures(result):
    return {
        "clinical_imputation_flow",
        *[f"clinical_imputation_missing_{key}" for key, _ in blocks(missing_rows(result), 10)],
        *[f"clinical_imputation_effects_{key}" for key, _ in blocks(result["coefficients"], 7)],
        *[
            f"clinical_imputation_traces_{key}"
            for key, _ in blocks(result["diagnostics"]["cycle_order"], 4)
        ],
    }


def markdown(result):
    spec, ledger = result["spec"], result["case_ledger"]
    lines = [
        "## 標準多重插補與缺失資料分析",
        "",
        f"研究情境：{cell(spec['context'])}。族群：{cell(spec['population_definition'])}。",
        f"結果：{cell(spec['outcome'])}；單位：{cell(spec['outcome_unit'])}；模型：{cell(result['model']['analysis'])}。",
        f"缺失假設依據：{cell(spec['missingness_basis'])}。可插補範圍：{cell(spec['imputation_scope'])}。",
        "### 個案納入與排除",
        "",
        "| 步驟 | 受試者數 |",
        "|---|---:|",
    ]
    labels = [
        "來源列",
        "不符合納入限制",
        "不可插補欄缺失",
        "每份完成資料保留個案",
        "有插補格的個案",
        "原分析完整個案",
    ]
    lines += [
        f"| {label} | {row['subjects']} |" for label, row in zip(labels, flow(result), strict=True)
    ]
    lines += [
        "",
        f"共 {result['m']} 份插補資料，每份 {result['n']} 人；不是 {result['n'] * result['m']} 位獨立受試者。原觀察格全部保留，來源檔案不改寫。",
        "### 插補模型與可重現設定",
        "",
        f"全域 k_pmm={spec['k_pmm']}；burn-in={spec['burn_in']}；每份間隔 cycles={spec['between']}；seed={spec['seed']}。",
        "連續欄使用 OLS、二元欄使用 Logistic conditional mean；兩者均以 Gaussian parameter perturbation 後的 PMM 抽取觀察 donor，並非 Bernoulli 抽樣或 NARFCS。單一 chain 保存多次完成資料；完成 cycles 不等於證明收斂。",
        "| 欄位 | 型態 | 原碼／單位 | 可插補 | imputation predictors | 插補格／份 |",
        "|---|---|---|---|---|---:|",
    ]
    for column in spec["columns"]:
        count = sum(c["column"] == column["column"] for c in ledger["imputed_cells"])
        lines.append(
            f"| {cell(column['column'])} | {column['kind']} | {cell(column['levels'] or column['unit'])} | {column['impute']} | {cell(', '.join(column['predictors']))} | {count} |"
        )
    lines += [
        "",
        "### Rubin 合併估計與不確定性",
        "",
        "每份資料各自估計相同模型，再合併參數與完整 covariance；區間及 p 值為逐項未校正的漸近常態 Wald，沒有 Barnard–Rubin 小樣本自由度。",
        _model_scale(result)[0],
        "",
        "| 參數 | 係數 | SE | 係數區間下限 | 上限 | p | within variance | between variance |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["coefficients"]:
        lines.append(
            f"| {cell(row['column'] or 'intercept')} | {number(row['coefficient'])} | {number(row['standard_error'])} | {number(row['coefficient_lower'])} | {number(row['coefficient_upper'])} | {number(row['p_value'])} | {number(row['within_variance'])} | {number(row['between_variance'])} |"
        )
    comparison = result["complete_case_comparison"]
    lines += [
        "",
        "### 原完整個案比較與插補影響",
        "",
        f"原 analysis 完整人口 n={comparison['n']}；狀態：{comparison['status']}。這個比較同時改變分析人口，不能診斷 MAR/MNAR 或當成 MNAR 敏感度分析。",
    ]
    if comparison["status"] == "completed":
        lines += ["", "| 參數 | MI 係數 | 原完整個案係數 |", "|---|---:|---:|"]
        lines += [
            f"| {cell(a['column'] or 'intercept')} | {number(a['coefficient'])} | {number(b['coefficient'])} |"
            for a, b in zip(result["coefficients"], comparison["coefficients"], strict=True)
        ]
    else:
        lines.append(f"無法估計原因：{cell(comparison.get('reason'))}。")
    lines += ["", "### 解讀與適用範圍", ""]
    lines += [f"- {cell(note)}" for note in result["limitations"]]
    lines += [
        "",
        f"- 數值收據 SHA256：`{result['receipt_sha256']}`",
        f"- 規格 SHA256：`{result['spec_sha256']}`",
        f"- 來源欄位／列 SHA256：`{result['dataframe_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def tables(result, directory: Path, prefix):
    included = set(result["case_ledger"]["included_data_rows"])
    outside = set(result["case_ledger"]["filter_excluded_data_rows"])
    imputed = set(result["case_ledger"]["imputed_data_rows"])
    rows = [
        {
            "data_row": row,
            "status": "included"
            if row in included
            else "outside_cohort"
            if row in outside
            else "missing_nonimputable",
            "has_imputed_cell": row in imputed,
        }
        for row in range(1, result["case_ledger"]["input_rows"] + 1)
    ]
    data = {
        "participants": rows,
        "coefficients": result["coefficients"],
        "missingness": missing_rows(result),
        "imputed_cells": result["case_ledger"]["imputed_cells"],
        "chain_traces": result["diagnostics"]["chain_traces"],
    }
    paths = []
    for label, values in data.items():
        path = directory / f"{prefix}_imputation_{label}.csv"
        pd.DataFrame(values).to_csv(path, index=False)
        paths.append(path)
    return paths


def figures(result, directory, prefix, preset_id="journal-neutral-english-v1", edition=None):
    labels = {column["column"]: f"V{i+1}" for i, column in enumerate(result["spec"]["columns"])}
    source = (
        f"n={result['n']} independent subjects; m={result['m']} completed datasets of the same subjects. "
        "Variable aliases identify original columns in the accompanying source-context mapping. "
        "Review the separately retained original-language study definitions before manuscript submission. "
    )

    def draw(new, save):
        fig, axes = new(85)
        flow_table(axes[0], flow(result))
        save(
            fig,
            "flow",
            "Multiple-imputation participant flow.",
            source
            + "Original observations are not overwritten. Only prespecified nonimputable-role missingness is excluded; imputed subjects remain in every dataset. Counts are people, not m times people.",
            "來源、排除與插補個案分開列示，m份資料不能倍增人數。",
            flow(result),
        )
        for key, rows in blocks(missing_rows(result), 10):
            fig, axes = new(max(65, 22 + 7 * len(rows)))
            ax = axes[0]
            ax.barh(range(len(rows)), [r["imputed_per_dataset"] for r in rows], color="#176e68")
            ax.set_yticks(range(len(rows)), [r["label"] for r in rows])
            ax.invert_yaxis()
            ax.set_xlabel("Imputed cells per completed dataset")
            save(
                fig,
                f"missing_{key}",
                "Prespecified imputation counts.",
                source
                + "Bars count missing cells filled among retained subjects. Cohort missing counts before nonimputable-role exclusion are separately preserved in the data table; absence of a bar does not mean absence of missingness in the source.",
                "顯示保留人口每份資料實際補值格數；排除前的缺值另保留，不能混稱為零。",
                rows,
            )
        for key, rows in blocks(result["coefficients"], 7):
            fig, axes = new(max(70, 24 + 10 * len(rows)))
            ax = axes[0]
            for i, row in enumerate(rows):
                ax.hlines(i, row["coefficient_lower"], row["coefficient_upper"], color="#176e68")
                ax.plot(row["coefficient"], i, "o", color="#176e68")
            ax.axvline(0, linestyle="dashed", color="#777777", linewidth=0.7)
            ax.set_yticks(range(len(rows)), [labels.get(r["column"], "Intercept") for r in rows])
            ax.invert_yaxis()
            scale_zh, scale_en, axis_label = _model_scale(result)
            ax.set_xlabel(axis_label)
            save(
                fig,
                f"effects_{key}",
                "Rubin pooled coefficients and uncertainty.",
                source
                + f"Points and bars are saved coefficients and pointwise unadjusted {result['spec']['confidence_level']:.1%} asymptotic normal Wald intervals. Covariance is U_bar + (1+1/m) B from statsmodels MICE.combine. No Barnard-Rubin correction, robust covariance or multiplicity adjustment. Predictor scales differ; coefficient magnitude does not rank importance. "
                + scale_en,
                "合併係數與區間來自保存收據；沒有小樣本自由度或多重校正，也不按係數大小比較重要性。"
                + scale_zh,
                rows,
            )
        traces = result["diagnostics"]["chain_traces"]
        for key, columns in blocks(result["diagnostics"]["cycle_order"], 4):
            fig, axes = new(55 * len(columns), len(columns))
            data = []
            for ax, column in zip(axes, columns, strict=True):
                rows = [r for r in traces if r["column"] == column]
                ax.plot(
                    [r["cycle"] for r in rows], [r["imputed_mean"] for r in rows], color="#176e68"
                )
                ax.axvline(result["spec"]["burn_in"] + 0.5, linestyle="dashed", color="#777777")
                ax.set_ylabel(f"{labels[column]} imputed mean")
                ax.set_xlabel("MICE cycle")
                data.extend(rows)
            save(
                fig,
                f"traces_{key}",
                "Single-chain imputed means by cycle.",
                source
                + "One chained process is shown; the dashed line separates burn-in from retained-sampling cycles. Data also include imputed SD and range. Trace appearance and completed iterations do not certify convergence, MAR or unbiased inference. No independent-chain diagnostic is claimed.",
                "每輪補值平均與burn-in分界；這是單一chain的過程紀錄，不是收斂或MAR通過證明。",
                data,
            )

    return render(
        result,
        directory,
        prefix,
        "imputation",
        draw,
        preset_id,
        edition,
        {
            "variable_aliases": {alias: column for column, alias in labels.items()},
            "column_definitions": result["spec"]["columns"],
        },
    )
