"""Clinical reading layer over immutable numerical receipts; never recomputes fits."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def number(value):
    return f"{value:.6g}" if isinstance(value, (int, float)) else "無法估計"


def markdown(result: dict) -> str:
    if result["spec"]["family"] == "longitudinal":
        from .longitudinal_report import markdown as longitudinal_markdown

        return longitudinal_markdown(result)
    if result["spec"]["family"] != "survival":
        from .measurement_report import markdown as measurement_markdown

        return measurement_markdown(result)
    s, ledger = result["spec"], result["case_ledger"]
    competing = bool(s["competing_values"])
    ci = f"{s['confidence_level']:.1%}"
    lines = [
        "## 生存與事件分析（Survival analysis）",
        "",
        "### 研究問題與分析方法",
        "",
        f"- 追蹤時間欄位：{cell(s['time'])}；單位：{cell(s['time_unit'])}。起算點：{cell(s['time_origin'])}。",
        f"- 事件欄位：{cell(s['event'])}；目標事件代碼：{cell(s['event_value'])}；追蹤截止但未觀察到事件（右設限，right censoring）：{cell(s['censor_value'])}。",
        f"- 競爭事件代碼：{', '.join(cell(v) for v in s['competing_values']) or '未指定'}。分組欄位：{cell(s['group'] or '不分組')}。",
        f"- 受試者識別欄：{cell(s['subject'] or '未提供；研究者確認每列為不同受試者')}。一人一列，分析不含重複事件、延遲進入或隨時間改變的共變項。",
        f"- 信賴區間（confidence interval, CI）：{ci}；逐一時點區間不代表整條曲線的同時信賴帶。",
        "- 所有圖、表與模型使用同一組完整個案（complete cases）；有缺失的必要欄位不自動補值。連續變項線性納入，不依 p 值自動挑選。",
    ]
    if s["cohort_filter"]:
        f = s["cohort_filter"]
        lines.append(
            f"- 事先指定納入範圍：{cell(f['column'])} 屬於 {', '.join(cell(v) for v in f['values'])}。"
        )
    lines += [
        "",
        "### 個案納入與排除（Participant flow）",
        "",
        "| 步驟 | 人數 |",
        "|---|---:|",
        f"| 原始資料 | {ledger['input_rows']} |",
        f"| 不符合指定納入範圍 | {len(ledger['filter_excluded_data_rows'])} |",
        f"| 範圍內但必要欄位缺失 | {len(ledger['missing_excluded_data_rows'])} |",
        f"| 最終共同分析人數 | {result['n']} |",
        "",
        "逐列納排原因保存在可下載的個案紀錄；資料列號從 1 開始，不包含標題列。",
        "",
        "| 分組原始值 | 人數 | 目標事件 | 競爭事件 | 右設限 |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in result["strata"]:
        lines.append(
            f"| {cell(group['label'])} | {group['n']} | {group['events']} | {group['competing']} | {group['censored']} |"
        )
    lines += ["", "### 事件曲線與追蹤人數", ""]
    if competing:
        lines += [
            "累積發生率（cumulative incidence）使用 Aalen–Johansen 估計。它估計在其他競爭事件存在時，至某時點已發生指定事件的機率；不能將競爭事件單純當作失訪再用 1 − Kaplan–Meier 取代。",
            f"{ci} 區間使用逐點常態近似並限制在 0–1；稀少事件與邊界機率的區間可能不可靠。原始同時事件保留，不加入隨機時間偏移。此流程未計算 Gray 檢定或 Fine–Gray 模型。",
            "",
            "| 分組 | 事件代碼 | 最後觀察時間 | 累積發生率 | 信賴區間 |",
            "|---|---|---:|---:|---|",
        ]
        for group in result["strata"]:
            for cause, curve in group["estimate"]["curves"].items():
                last = curve[-1] if curve else {}
                lines.append(
                    f"| {cell(group['label'])} | {cell(cause)} | {number(last.get('time'))} | {number(last.get('estimate'))} | {number(last.get('lower'))} – {number(last.get('upper'))} |"
                )
        lines.append(
            "各組最後追蹤時間可能不同，上表不可用作固定時點的組間風險比較。沒有事件的組保留無事件狀態，不能據此推定風險為零。"
        )
    else:
        lines += [
            f"Kaplan–Meier 曲線估計尚未發生目標事件的比例；{ci} 信賴區間為 Greenwood log–log 逐點區間。中位時間是曲線首次達到 0.5 的時間；尚未達到時不填入推測值。",
            "",
            "| 分組 | 事件時間中位數 |",
            "|---|---:|",
        ]
        for group in result["strata"]:
            median = group["estimate"]["median"]
            lines.append(
                f"| {cell(group['label'])} | {number(median) if median is not None else '追蹤內尚未達到'} |"
            )
        test = result["logrank"]
        if test:
            lines += [
                "",
                (
                    f"整體組間曲線比較（log-rank）：χ²={number(test['statistic'])}，自由度={test['df']}，p={number(test['p_value'])}。這是未調整的整體比較，不表示因果療效，也不提供兩兩比較。"
                    if "statistic" in test
                    else "組間曲線比較無法估計：沒有足夠事件或有效的組間在險集合。"
                ),
            ]
    lines += [
        "",
        "在險人數（number at risk）指該時點事件／設限發生**之前**仍在追蹤的人數；追蹤尾端人數少時估計較不穩定。",
        "",
        "| 分組 | 時間 | 在險人數 | 先前目標事件 | 先前競爭事件 | 先前右設限 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in result["strata"]:
        for row in group["risk_table"]:
            lines.append(
                f"| {cell(group['label'])} | {number(row['time'])} | {row['at_risk']} | {row['prior_events']} | {row['prior_competing']} | {row['prior_censored']} |"
            )
    cox = result["cox"]
    if cox:
        lines += [
            "",
            "### 調整其他因素後的瞬時事件率（Cox regression）",
            "",
            f"共同分析 n={cox['n']}；目標事件 {cox['events']}；每個估計參數約 {cox['events_per_parameter']:.2f} 個事件。沒有自動變項選擇或懲罰化估計；同時事件採 Efron 處理。",
            "危險比（hazard ratio, HR）比較仍未發生目標事件者的瞬時事件率，不是固定期間的風險比或絕對風險。HR > 1 表示模型中的瞬時事件率較高；HR < 1 較低。連續欄位是每增加 1 個原始單位，類別欄位相對於指定參考組。",
            "h(t|x)=h₀(t) × exp(βx)，HR=exp(β)，CI=exp(β ± z × SE)。"
            + (
                "此處為原因別危險比（cause-specific HR）；競爭事件在發生時退出風險集合，不是次分布危險比。"
                if competing
                else ""
            ),
            "",
            f"| 變項與比較 | HR | {ci} 下限 | 上限 | p 值 |",
            "|---|---:|---:|---:|---:|",
        ]
        for row in cox["coefficients"]:
            label = (
                f"{row['variable']}：{row['level']} vs {row['reference']}"
                if "level" in row
                else f"{row['variable']}（每 +1）"
            )
            lines.append(
                f"| {cell(label)} | {number(row['hazard_ratio'])} | {number(row['lower'])} | {number(row['upper'])} | {number(row['p_value'])} |"
            )
        lines += [
            "",
            "### 模型假設檢查（Proportional hazards）",
            "",
            "比例風險假設要求 HR 隨追蹤時間大致穩定。下表檢查縮放 Schoenfeld 殘差與時間的關係，以 rank 與 KM 兩種時間轉換檢查，每個編碼參數與轉換共同做 Holm 多重校正。小 p 值提示需再檢視；大 p 值不能證明假設成立。診斷圖以原始追蹤時間呈現殘差，不取代上述正式檢查。",
            "",
            "| 參數 | 時間轉換 | 檢查統計量 | 原始 p | Holm 校正 p |",
            "|---|---|---:|---:|---:|",
        ]
        names = {
            r["term"]: cell(
                r["variable"] + (f"：{r['level']} vs {r['reference']}" if "level" in r else "")
            )
            for r in cox["coefficients"]
        }
        for row in cox["ph_checks"]:
            lines.append(
                f"| {names[row['term']]} | {row['transform']} | {number(row['statistic'])} | {number(row['p_value'])} | {number(row['p_adjusted'])} |"
            )
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        "- 本分析描述觀察到的追蹤與關聯。分組曲線和調整後 HR 不會自動消除混雜，也不能直接推論治療有效。",
        "- 完整個案可能與被排除者不同；需檢視缺失原因及失訪是否與結局相關。樣本代表性、追蹤起點與事件確認仍需研究者核對。",
        "- 右設限分析需要合理的獨立設限假設。此流程不包含延遲進入、反覆住院等重複事件、時間變動共變項、Fine–Gray 或限制平均生存時間（RMST）。",
        "- 若 CI 很寬、少量事件或比例風險不合適，應預先規劃額外資料或其他方法；不要以最小 p 值挑選報告結果。",
        "",
        "### 可追溯紀錄",
        "",
        f"- 數值收據 SHA256：`{result['receipt_sha256']}`",
        f"- 分析規格 SHA256：`{result['spec_sha256']}`",
        f"- 分析欄位與原始列值 SHA256：`{result['dataframe_sha256']}`",
    ]
    if cox and cox["events_per_parameter"] < 10:
        lines.insert(
            lines.index("### 解讀與適用範圍") + 2,
            "事件數相對模型參數偏少（每參數少於 10 個事件）；估計可能不穩定，這項經驗檢查不是樣本數充足的證明。",
        )
    lines += [f"- 計算套件：{', '.join(k + ' ' + v for k, v in result['versions'].items())}。", ""]
    return "\n".join(lines)


def figures(result: dict, directory: Path, prefix: str):
    if result["spec"]["family"] == "survival":
        from .survival_publication import figures as publication_figures
    elif result["spec"]["family"] == "longitudinal":
        from .longitudinal_publication import figures as publication_figures
    else:
        from .measurement_report import figures as publication_figures
    return publication_figures(result, directory, prefix)


def tables(result: dict, directory: Path, prefix: str):
    if result["spec"]["family"] == "longitudinal":
        from .longitudinal_report import tables as longitudinal_tables

        return longitudinal_tables(result, directory, prefix)
    if result["spec"]["family"] != "survival":
        from .measurement_report import tables as measurement_tables

        return measurement_tables(result, directory, prefix)
    directory.mkdir(parents=True, exist_ok=True)
    ledger = result["case_ledger"]
    rows = [
        {"data_row": row, "status": label}
        for key, label in [
            ("filter_excluded_data_rows", "outside_cohort"),
            ("missing_excluded_data_rows", "missing_required_value"),
            ("complete_data_rows", "included"),
        ]
        for row in ledger[key]
    ]
    data = {
        "participants": sorted(rows, key=lambda r: r["data_row"]),
        "risk_table": [
            {"group": group["label"], **row}
            for group in result["strata"]
            for row in group["risk_table"]
        ],
    }
    if result["spec"]["competing_values"]:
        data["incidence"] = [
            {"group": group["label"], "event": cause, **row}
            for group in result["strata"]
            for cause, curve in group["estimate"]["curves"].items()
            for row in curve
        ]
    else:
        data["survival"] = [
            {"group": group["label"], **row}
            for group in result["strata"]
            for row in group["estimate"]["curve"]
        ]
    if result["cox"]:
        for name in ["coefficients", "ph_checks", "scaled_schoenfeld"]:
            data[name] = result["cox"][name]
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_{name}.csv"
        # A no-event competing-risk analysis has no estimated curve points.
        # Keep a readable, typed empty table instead of an unparseable blank file.
        columns = (
            ["group", "event", "time", "estimate", "standard_error", "lower", "upper"]
            if name == "incidence" and not rows
            else None
        )
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
        paths.append(path)
    return paths
