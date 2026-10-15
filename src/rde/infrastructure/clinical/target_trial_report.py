"""Read-only reporting from linked frozen target-trial and weighting receipts."""

import json
from pathlib import Path

import pandas as pd

from . import weighting_report, weighting_publication
from .fixed_publication import flow_table
from .report import cell
from .target_trial_study import verify_target_trial_result


def checked(result):
    if not verify_target_trial_result(result):
        raise ValueError("TTE_RESULT_INTEGRITY: frozen target-trial source/numerical links failed.")
    return result["source_check"], result["weighting_result"]


def required_figures(result):
    return {
        *weighting_report.required_figures(result["weighting_result"]),
        "clinical_target_trial_flow",
    }


def markdown(result):
    source, numerical = checked(result)
    p, population = result["spec"]["protocol"], source["population"]
    lines = [
        "## 基線目標試驗模擬（Baseline target-trial emulation）",
        "",
        "此分析核對核准多表來源與每位個案的時間／納排，再執行原有 propensity weighting。來源一致與計算完成不證明因果識別，也不把觀察資料變成隨機試驗。",
        "",
        "### 固定研究 protocol",
        "",
        "| 項目 | 核准定義與範圍 |",
        "|---|---|",
    ]
    definitions = {
        "Eligibility": p["eligibility"]["definition"]
        + "; rules="
        + ", ".join(p["eligibility"]["rule_ids"]),
        "Time zero": p["time_zero"]["definition"] + "; column=" + p["time_zero"]["index_column"],
        "Treatment strategies": "; ".join(
            f"{level}: {definition}"
            for level, definition in zip(
                p["treatment"]["levels"], p["treatment"]["definitions"], strict=True
            )
        ),
        "Assignment": p["assignment"]["selection_basis"]
        + "; "
        + p["assignment"]["confounder_selection_basis"],
        "Follow-up": p["followup"]["definition"]
        + f"; complete horizon={p['followup']['horizon_days']} days",
        "Outcome": p["outcome"]["definition"]
        + f"; {p['outcome']['column']}, {p['outcome']['unit']}; relation={p['outcome']['relation_id']}",
        "Estimand": p["estimand"]["kind"] + ": " + p["estimand"]["target_population"],
        "Analysis": "Unchanged prespecified weighting; all prepared eligible units, zero additional missing/filter exclusions",
    }
    lines += [f"| {key} | {cell(value)} |" for key, value in definitions.items()]
    lines += [
        "",
        "### 個案納入與排除：原始來源到分析",
        "",
        f"原始 root 個案 {population['root_records']}；事先基線規則排除 {population['excluded_by_baseline_eligibility']}；eligible 與實際分析均為 {population['analysis_n']}。完整逐人來源、時間與納排保存於 source-check JSON／CSV，沒有只查預覽頁。",
        "每位 eligible 均須符合完整固定追蹤、明確匯出與 intercurrent status。未知、失訪或無法判定結果會阻擋此版本，不能先刪人再宣稱分析原目標族群。",
        "",
        f"資料準備核對狀態：`{source['clinical_validation']}`；review kind：`{source['preparation_review_kind']}`。自動技術核對不等於資料管理者或臨床核准。",
        "",
        "### 基線角色的來源時序",
        "",
        "| 欄位 | 來源 | 事件時間 | 可得時間 |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {cell(f['column'])} | {cell(f['source_id'])} | {cell(f['event_column'])} | {cell(f['available_column'])} |"
        for f in [p["treatment"]["field"], *p["baseline"]]
    ]
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        *[f"- {cell(text)}" for text in source["limitations"]],
        f"- Consistency：{cell(p['analysis']['consistency_basis'])}",
        f"- Exchangeability：{cell(p['analysis']['exchangeability_basis_and_limitations'])}",
        f"- Positivity：{cell(p['analysis']['positivity_basis_and_limitations'])}",
        "- 此版本只有基線點處置、固定完整追蹤與既有 ATE／ATT／ATO 加權；不含時變處置、動態策略、grace period、失訪校正、clone–censor–weight 或配對推論。",
        "",
        f"- 完整 TTE 收據 SHA256：`{result['receipt_sha256']}`",
        f"- Protocol SHA256：`{source['protocol_sha256']}`",
        f"- 來源核對 SHA256：`{source['receipt_sha256']}`",
        f"- 核准 release SHA256：`{source['binding']['release_sha256']}`",
        f"- 原 weighting 數值 SHA256：`{numerical['receipt_sha256']}`",
        "",
        weighting_report.markdown(numerical),
    ]
    return "\n".join(lines)


def tables(result, directory: Path, prefix):
    source, numerical = checked(result)
    paths = weighting_report.tables(numerical, directory, prefix)
    rows = [
        {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
            for key, value in row.items()
        }
        for row in source["rows"]
    ]
    ledger = directory / f"{prefix}_target_trial_source_rows.csv"
    pd.DataFrame(rows).to_csv(ledger, index=False)
    protocol = directory / f"{prefix}_target_trial_protocol.json"
    protocol.write_text(json.dumps(result["spec"]["protocol"], ensure_ascii=False, indent=2) + "\n")
    return [*paths, ledger, protocol]


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rde.infrastructure.visualization.publication import (
        publication_style,
        save_publication_figure,
    )

    source, numerical = checked(result)
    # Weighting panels preserve their true nested numerical-receipt identity.
    records = weighting_publication.figures(numerical, directory, prefix, preset_id, edition)
    population = source["population"]
    rows = [
        {"stage": "Original root population", "subjects": population["root_records"]},
        {
            "stage": "Excluded by baseline eligibility",
            "subjects": population["excluded_by_baseline_eligibility"],
        },
        {"stage": "Eligible with complete fixed follow-up", "subjects": population["included"]},
        {"stage": "Additional analysis exclusions", "subjects": 0},
        {"stage": "Prespecified weighting population", "subjects": population["analysis_n"]},
    ]
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        fig, ax = plt.subplots(figsize=(180 / 25.4, 85 * 180 / profile["width_mm"] / 25.4))
        flow_table(ax, rows)
        caption = "Complete source population and prespecified baseline eligibility for a point-treatment target-trial protocol. Every eligible person retains complete fixed-horizon ascertainment and enters the unchanged weighting analysis. Counts refer to persons, not linked events. Source consistency does not establish clinical validity or causal identification."
        pub = save_publication_figure(
            fig,
            directory,
            f"{prefix}_target_trial_flow",
            number=len(records) + 1,
            title="Baseline target-trial population",
            caption=caption,
            explanation="原始個案、基線納排與分析分母完整核對；未知追蹤不當陰性，也不默默排除。技術核對不證明臨床或因果有效性。",
            data=rows,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=caption,
        )
        pub["source_context"] = result["spec"]["protocol"]
        with Path(pub["files"]["caption"]).open("a", encoding="utf-8") as stream:
            stream.write(
                "\n## 研究原文 protocol（不屬於英文圖說）\n\n```json\n"
                + json.dumps(result["spec"]["protocol"], ensure_ascii=False, indent=2)
                + "\n```\n"
            )
        records.append(
            {
                "path": pub["files"]["png"],
                "plot_type": "clinical_target_trial_flow",
                "caption": pub["caption_en"] + "\n\n中文解釋：" + pub["explanation_zh"],
                "fonts": {"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                "publication": pub,
            }
        )
        plt.close(fig)
    return records
