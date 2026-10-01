"""Prediction-specific tables and figures; no in-sample inference claims."""

from __future__ import annotations

from pathlib import Path

import numpy as np


DESIGNS = {
    "observational_cohort": "觀察性世代",
    "diagnostic_accuracy": "診斷研究",
    "case_control": "病例對照研究",
}
SAMPLING = {
    "single_gate": "共同納入途徑",
    "two_gate": "依結果分別納入有病／無病個案",
    "unknown": "抽樣方式尚未確認",
}
SPLITS = {"random": "獨立觀察列隨機分割", "group": "按受試者分組分割", "temporal": "按時間界線分割"}
MODELS = {"linear": "正則化線性／Logistic 模型", "random_forest": "隨機森林"}
METRICS = {
    "auroc": "區辨能力（AUROC）",
    "average_precision": "平均精確率（AP）",
    "brier": "機率平方誤差（Brier）",
    "log_loss": "機率對數損失（Log loss）",
    "sensitivity": "敏感度（Sensitivity）",
    "specificity": "特異度（Specificity）",
    "ppv": "樣本陽性預測值（PPV）",
    "npv": "樣本陰性預測值（NPV）",
    "f1": "F1",
    "accuracy": "樣本正確率（Accuracy）",
    "tn": "真陰性（TN）",
    "fp": "假陽性（FP）",
    "fn": "假陰性（FN）",
    "tp": "真陽性（TP）",
    "mae": "平均絕對誤差（MAE）",
    "rmse": "均方根誤差（RMSE）",
    "r2": "決定係數（R²）",
}


def number(value):
    return f"{value:.6g}" if isinstance(value, (float, int)) else "無法估計"


def cell(value):
    return (
        str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
    )


def participant_flow(result):
    split = result["outer_split"]
    return [
        ("原始來源", result["n_source"]),
        ("結果／分割鍵不完整或無效", result["n_source"] - result["n_eligible"]),
        ("跨時間邊界受試者的訓練列移除", len(split["purged_train_positions"])),
        ("最終訓練資料", split["n_train"]),
        ("最終保留驗證資料", split["n_validation"]),
    ]


def required_figures(spec):
    kinds = {"prediction_cv", "prediction_participants"}
    kinds |= (
        {"prediction_roc", "prediction_pr", "prediction_calibration", "prediction_confusion"}
        if spec["task"] == "binary"
        else {"prediction_observed", "prediction_residual"}
    )
    if spec.get("decision_curve"):
        kinds.add("prediction_decision_curve")
    return kinds


def markdown(result: dict) -> str:
    spec, split, selection, validation = (
        result[key] for key in ["spec", "outer_split", "selection", "validation"]
    )
    uncertainty = validation["uncertainty"]
    ci = f"{uncertainty['confidence_level']:.1%}"
    encoding = (
        "、".join(
            f"{cell(label)} → {'事件／陽性' if code == 1 else '非事件／陰性'}（{code}）"
            for label, code in result["target_encoding"].items()
        )
        or "連續數值，保持原始尺度"
    )
    invalid = (
        "、".join(
            f"{cell(key)}：{count} 次"
            for key, count in result["invalid_predictor_values"].items()
            if count
        )
        or "沒有非缺失但無效的數值"
    )
    lines = [
        "## 預測建模與內部驗證（Prediction validation）",
        "",
        "此報告描述固定候選模型在本研究保留樣本的表現；沒有外部驗證，也不是臨床部署認證。",
        "",
        "### 研究設計與預測目標",
        "",
        f"- 設計：{DESIGNS[spec['study_design']]}；抽樣：{SAMPLING[spec['sampling']]}。",
        f"- 收集與抽樣事實：{cell(spec['sampling_description'])}。",
        f"- 結果定義：{cell(spec['target_definition'])}；結果欄位 {cell(spec['target'])}。",
        f"- 原始結果編碼：{encoding}。研究者的標籤說明不代表軟體已驗證診斷真值或盲判。",
        f"- 預測時點：{cell(spec['prediction_time_definition'])}；特徵當時可取得由研究者確認。",
        f"- 事先選定特徵：{cell('、'.join(spec['predictors']))}；類別型特徵：{cell('、'.join(spec['categorical_predictors']) or '無')}。",
        f"- 受試者欄位：{cell(spec['subject_variable'] or '未指定；需確認各列獨立')}。日期欄位：{cell(spec['time_variable'] or '未使用')}；時間界線：{cell(spec['cutoff'] or '未使用')}。",
        f"- 分割：{SPLITS[spec['split']]}；固定種子={spec['seed']}；要求保留比例 {spec['test_fraction']:.1%}。分組分割按受試者數，時間分割以指定界線為準。",
        "- 補值、縮放、缺失指標與類別詞彙，只從每個訓練子集估計；不補結果或分割鍵，不從保留集選變項、調參或找最佳閾值。",
    ]
    if spec["sampling"] != "single_gate":
        lines += [
            "",
            "**本資料的結果選樣或抽樣方式未知。** 以下 AP、PPV／NPV、F1、正確率、Brier／log loss 及校準圖僅用於檢查本保留樣本內的模型表現，不能解讀為臨床母群風險或盛行率。模型輸出的機率分數並非已驗證的病人疾病機率；ROC、敏感度與特異度亦可能受疾病譜及選擇偏差影響。未使用外部盛行率校正，不提供決策淨效益。",
        ]
    else:
        lines += [
            "",
            "共同納入途徑不保證樣本代表任何醫院或母群；所有指標仍需結合納入方式、結果判定及外部驗證解讀。",
        ]
    lines += ["", "### 資料納排與分割", "", "| 階段 | 觀察列數 |", "|---|---:|"]
    lines += [f"| {name} | {count} |" for name, count in participant_flow(result)]
    lines += [
        "",
        "訓練、保留及移除列分開保存；原始位置從 0 起算，不包含標題列。相同個人多列時，列數不是受試者數。",
        "個別排除原因可能重疊；原始列位置及完整原因另附納排表 CSV。",
        f"數值特徵格式核對：{invalid}。無效數值轉為缺失；須核對資料字典，不能以補值掩蓋原始格式錯誤。",
        "",
        "### 訓練內模型比較（Training-only candidate comparison）",
        "",
        f"以 {spec['cv_folds']} 折訓練 CV 的平均 {selection['criterion']} {'最高' if selection['direction']=='maximize' else '最低'} 選擇模型；平手按事先指定候選順序。保留集從未參與此比較。",
        "",
        "| 候選模型 | 完成狀態 | 訓練 CV 平均 | 選定 | 未完成原因 |",
        "|---|---|---:|---|---|",
    ]
    for candidate in result["candidates"]:
        lines.append(
            f"| {MODELS[candidate['name']]} | {'完成' if candidate['status']=='completed' else '未完成'} | {number(candidate.get('cv_score'))} | {'是' if candidate['name']==selection['selected'] else '否'} | {cell(candidate.get('error') or '—')} |"
        )
    lines += [
        "",
        "### 保留樣本表現（Held-out performance）",
        "",
        f"選定模型：{MODELS[selection['selected']]}；驗證觀察列 n={validation['n']}。分類閾值：{number(validation['threshold']) if spec['task']=='binary' else '不適用'}。",
        "",
        f"| 指標 | 本樣本估計 | {ci} 下限 | 上限 | 可估計 bootstrap 次數 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, value in validation["metrics"].items():
        bounds = uncertainty["intervals"].get(key)
        lines.append(
            f"| {METRICS.get(key, key)} | {number(value)} | {number(bounds['lower']) if bounds else '—'} | {number(bounds['upper']) if bounds else '—'} | {bounds['estimable_replicates'] if bounds else '計數；不套用此區間'} |"
        )
    lines += [
        "",
        f"{ci} CI 為固定所選模型的百分位 bootstrap；單位={'整個受試者' if uncertainty['unit']=='subject_cluster' else '觀察列'}，單位數={uncertainty['units']}，要求 {uncertainty['replicates_requested']} 次。未重訓或重選模型，故不涵蓋訓練與選模的不確定性；少於 20 次可估計重複不顯示區間。逐項區間未作多重校正，小樣本／稀疏事件與少量重複仍可能不穩定。",
    ]
    if spec["task"] == "binary":
        m = validation["metrics"]
        lines += [
            "",
            "| 固定閾值判定 | 原始陽性 | 原始陰性 |",
            "|---|---:|---:|",
            f"| 陽性 | {m['tp']} | {m['fp']} |",
            f"| 陰性 | {m['fn']} | {m['tn']} |",
            "",
            f"敏感度分母={m['tp']+m['fn']}；特異度分母={m['tn']+m['fp']}；PPV 分母={m['tp']+m['fp']}；NPV 分母={m['tn']+m['fn']}。零分母標為無法估計。AP 不是梯形 PR 面積；Brier／log loss 越低越好。",
            "",
            "校準圖按事先固定的 10 個等寬分箱，比較平均機率分數與本樣本陽性比例，保留各箱人數；未在保留集重校準模型。空箱不畫，稀疏分箱不能當成穩定校準證據。",
        ]
    lines += [
        "",
        "### 簡單基準與模型資訊",
        "",
        f"基準僅使用訓練資料結果的平均／陽性比例 {number(validation['baseline']['constant'])} 對每列給相同預測，供檢查模型是否有超過簡單常數的表現；不以保留集比較後重新選模。",
        "",
        "| 指標 | 常數基準 | 選定模型 |",
        "|---|---:|---:|",
    ]
    for key in ["auroc", "brier", "log_loss", "rmse", "mae"]:
        if key in validation["metrics"]:
            lines.append(
                f"| {METRICS[key]} | {number(validation['baseline']['metrics'][key])} | {number(validation['metrics'][key])} |"
            )
    fit = result["final_fit"]
    lines += [
        "",
        f"最終估計器：{cell(fit['estimator'])}；以全部訓練列 n={fit['n_train']} 擬合。",
        "正則化 logistic 固定 C=1；ridge 固定 alpha=1；森林固定 64 棵、深度 8、每葉至少 5 列。未估計推論性係數 p 值。標準化係數與訓練 impurity importance 不是因果效果；完整轉換、係數／重要度與每折預測可下載。",
    ]
    curve = validation["decision_curve"]
    lines += ["", "### 決策曲線（Decision curve）", ""]
    if curve:
        lines += [
            f"- 行動情境：{cell(curve['action'])}。",
            f"- 閾值及利弊權衡依據：{cell(curve['threshold_basis'])}。",
            "- 每個閾值 t 的淨效益 NB=TP/n − FP/n × t/(1−t)；比較依模型採取行動、全部採取、全部不採取。模型分數 >= t 才採取行動。",
            "- 全部不採取的 NB=0。各點使用相同保留樣本與配對 bootstrap；差值 CI 直接對同一次抽樣的模型 NB 減全部行動 NB 計算，不是兩個 CI 相減。不是同時區間，不用最大 NB 自動挑閾值。",
            "",
            f"| 事先閾值 | 模型 NB | {ci} CI | 全部採取 NB | 模型減全部採取 | 差值 CI |",
            "|---|---:|---|---:|---:|---|",
        ]
        for row in curve["points"]:
            bounds, diff = row["intervals"]["model"], row["intervals"]["difference_vs_all"]
            lines.append(
                f"| {row['threshold']:.3f} | {number(row['model'])} | {number(bounds['lower'])}–{number(bounds['upper'])} | {number(row['treat_all'])} | {number(row['difference_vs_all'])} | {number(diff['lower'])}–{number(diff['upper'])} |"
            )
        lines += [
            "",
            "此為固定模型在本驗證樣本的條件性決策分析，不計額外檢測成本，不量化外部母群漂移；沒有證明採用模型能改善病人結局。必須審閱機率校準、代表性、每個行動的利弊與指定閾值是否合理。",
        ]
    else:
        lines.append(
            "未執行決策曲線。需要二元結果、共同納入途徑、每人一次獨立判斷，以及事先指定的行動情境和閾值／利弊依據；抽樣未知或病例對照不能直接推出母群淨效益。"
        )
    lines += [
        "",
        "### 解讀與適用範圍（Interpretation and limitations）",
        "",
        "- 區辨、校準與特定閾值表現回答不同問題；高 AUROC 不保證校準或臨床效益，觀察性預測也不建立因果關係。",
        "- 連續結果的 MAE／RMSE 使用原始結果尺度，RMSE 較強調大誤差；未提供單位時不能猜測。R² 可為負，常數結果下無法估計。",
        "- 資料分割不能去除選擇、測量、混雜或時間漂移；需核對受試者代表性、結果定義及參照標準、特徵時點、樣本／事件數與子群表現。",
        "- 看過保留集後再修模型，需新驗證資料或明示探索性；複製相同來源／換專案不會讓已見資料變成外部資料。公開 benchmark 的工程演示亦不代表新的臨床驗證。",
        "- 方法與來源收據完整，不表示符合全部 TRIPOD+AI 項目或已可投稿。",
        "",
        "### 追溯與下載",
        "",
        f"- 數值收據 SHA256：`{result['receipt_sha256']}`；模型 fit SHA256：`{fit['fit_sha256']}`。",
        f"- 資料框 SHA256：`{result['dataframe_sha256']}`；規格 SHA256：`{result['spec_sha256']}`。",
        f"- 套件：{cell('、'.join(f'{name} {version}' for name, version in result['versions'].items()))}；Python {result['python']}。",
        "- 保存原始列位置、納排、完整切分、訓練轉換、固定超參數、每折與保留集預測、候選失敗及 bootstrap 抽樣雜湊；顯示與匯出不重訓模型。",
        "",
        "### 方法參考",
        "",
        "- [TRIPOD+AI 報告指引](https://www.tripod-statement.org/)",
        "- [決策曲線方法與適用範圍](https://www.mskcc.org/departments/epidemiology-biostatistics/biostatistics/decision-curve-analysis)",
        "",
    ]
    return "\n".join(lines)


def figures(result: dict, directory: Path, prefix: str) -> list[dict]:
    from .publication import figures as publication_figures

    return publication_figures(result, directory, prefix)


def tables(result, directory: Path, prefix):
    import pandas as pd

    directory.mkdir(parents=True, exist_ok=True)
    split, validation = result["outer_split"], result["validation"]
    train, valid, purged = (
        set(split[name])
        for name in ["train_positions", "validation_positions", "purged_train_positions"]
    )
    reasons = {}
    for reason, positions in result["exclusions"].items():
        for position in positions:
            reasons.setdefault(position, []).append(reason)
    data = {
        "validation": validation["predictions"],
        "participants": [
            dict(
                source_position=position,
                partition="training"
                if position in train
                else "validation"
                if position in valid
                else "purged"
                if position in purged
                else "excluded",
                reasons=";".join(reasons.get(position, [])),
            )
            for position in range(result["n_source"])
        ],
        "metrics": [
            dict(
                metric=key,
                estimate=value,
                **{
                    k: v
                    for k, v in validation["uncertainty"]["intervals"].get(key, {}).items()
                    if k != "estimate"
                },
                sampling=result["spec"]["sampling"],
                scope="internal_sample_only",
            )
            for key, value in validation["metrics"].items()
        ],
        "candidates": [
            dict(
                name=c["name"],
                status=c["status"],
                cv_score=c.get("cv_score"),
                selected=c["name"] == result["selection"]["selected"],
                error=c.get("error"),
            )
            for c in result["candidates"]
        ],
    }
    if validation["calibration_bins"]:
        data["calibration_bins"] = validation["calibration_bins"]
    if validation["decision_curve"]:
        data["decision_curve"] = [
            {
                **{k: v for k, v in p.items() if k != "intervals"},
                **{
                    f"{metric}_{key}": value
                    for metric, interval in p["intervals"].items()
                    for key, value in interval.items()
                    if key != "estimate"
                },
            }
            for p in validation["decision_curve"]["points"]
        ]
    fit = result["final_fit"]
    values = np.asarray(fit.get("coefficients", fit.get("feature_importance"))).ravel()
    data["model_parameters"] = [
        dict(
            feature=name,
            value=float(value),
            kind="standardized_penalized_coefficient"
            if "coefficients" in fit
            else "training_impurity_importance",
        )
        for name, value in zip(fit["encoded_feature_names"], values, strict=True)
    ]
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        paths.append(path)
    return paths
