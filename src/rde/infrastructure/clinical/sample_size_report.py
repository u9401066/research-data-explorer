"""Chinese planning report and English publication figures from saved numbers."""

import csv
from pathlib import Path
import textwrap

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure


METHODS = {
    "independent_means": "Two independent means (pooled t)",
    "paired_means": "Paired mean difference (paired t)",
    "independent_proportions": "Two independent proportions (normal approximation)",
}


def summary_rows(result):
    spec = result["spec"]
    return [
        {
            "scenario_id": row["scenario_id"],
            "scenario_label": row["label"],
            "primary": row["primary"],
            "design": spec["design"],
            "difference": row["assumptions"].get("difference"),
            "sd": row["assumptions"].get("sd"),
            "probability_1": row["assumptions"].get("probabilities", [None, None])[0],
            "probability_2": row["assumptions"].get("probabilities", [None, None])[1],
            "alpha": spec["alpha"],
            "target_power": spec["target_power"],
            "achieved_power": row["achieved_power"],
            "loss_rate": row["assumptions"]["loss_rate"],
            **{f"evaluable_{key}": value for key, value in row["evaluable"].items()},
            **{f"enrollment_{key}": value for key, value in row["enrollment"].items()},
            "previous_evaluable_units": (row["previous_allocation"] or {}).get("total_units"),
            "previous_power": (row["previous_allocation"] or {}).get("power"),
        }
        for row in result["scenarios"]
    ]


def write_table(result, directory):
    rows = summary_rows(result)
    path = directory / "sample-size-summary.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def review_markdown(spec, limitations):
    lines = [
        "# 前瞻樣本數規劃 — 待核准假設",
        "",
        f"方法：{METHODS[spec['design']]}；單一主要雙側檢定，虛無差值為零。",
        "",
    ]
    for key, label in (
        ("population", "研究族群"),
        ("endpoint", "主要結果"),
        ("time_horizon", "觀察時間窗"),
        ("outcome_unit", "結果單位"),
        ("contrast", "比較定義"),
    ):
        lines += [f"- {label}：{spec[key]}"]
    lines += [
        f"- 組別／量測順序：1={spec['group_labels'][0]}；2={spec['group_labels'][1]}；差值一律 1−2。",
        f"- 顯著水準 α={spec['alpha']}；目標 power={spec['target_power']}。",
        f"- 可分析分配比例：{spec['allocation'] if spec['allocation'] else '完整配對，沒有獨立組分配'}；計算上限 {spec['max_evaluable']} 個獨立人員／配對。",
        f"- 宣告的常態模型：{spec['normal_model']}；獨立分析單位：已確認。",
        f"- 設計依據：{', '.join(spec['design_source_ids'])}。",
        "",
        "共同 SD 指兩組共用的母體標準差；配對 SD 是同一對兩量測之差的標準差，不能用任一次量測的 SD 代替。",
        "",
    ]
    for scenario in spec["scenarios"]:
        numeric = (
            f"機率 p1={scenario['probabilities'][0]}；p2={scenario['probabilities'][1]}；差值={scenario['probabilities'][0]-scenario['probabilities'][1]:g}，乘 100 才是百分點。"
            if "probabilities" in scenario
            else f"差值={scenario['difference']}；SD={scenario['sd']}，單位皆為 {spec['outcome_unit']}。"
        )
        lines += [
            f"## {scenario['label']} — {'主情境' if scenario['id'] == spec['primary_scenario_id'] else '敏感度情境'}",
            "",
            numeric,
            f"共同結果缺失／不完整配對率={scenario['loss_rate']:.6g}。",
            "",
            f"差異依據：{', '.join(scenario['effect_source_ids'])}；變異／基準機率依據：{', '.join(scenario['nuisance_source_ids'])}；缺失依據：{', '.join(scenario['loss_source_ids'])}。",
            "",
        ]
    lines += ["## 假設來源（使用者提供，尚需人類核對）", ""]
    for source in spec["sources"]:
        lines += [
            f"### {source['id']} — {source['kind']}",
            "",
            source["citation"],
            "",
            f"定位：{source['locator']}",
            "",
            f"適用理由：{source['justification']}",
            "",
        ]
    lines += [
        "## 審閱要點與限制",
        "",
        *[f"- {item}" for item in limitations],
        "",
        "需確認：族群／結果／比較方向、每項數值與來源、方法及獨立性、主情境與分配／缺失假設。核准只涵蓋這一份固定草案。",
    ]
    return "\n".join(lines) + "\n"


def markdown(result, rendered):
    spec = result["spec"]
    lines = [
        "# 樣本數規劃報告",
        "",
        "這是前瞻設計計算，未讀入或分析病人資料。",
        "",
        f"數值收據：`{result['receipt_sha256']}`",
        "",
        "## 整數設計與招募目標",
        "",
    ]
    paired = spec["design"] == "paired_means"
    for row in result["scenarios"]:
        ev, en = row["evaluable"], row["enrollment"]
        lines += [f"### {row['label']} — {'主情境' if row['primary'] else '敏感度情境'}", ""]
        if paired:
            lines += [
                f"需要 **{ev['pairs']} 個完整配對**；規劃招募 **{en['pairs']} 個可形成配對的研究單位**，不是把兩次量測各算一位。"
            ]
        else:
            lines += [
                f"需要 **{ev['total_units']} 位可分析個案**（組 1：{ev['group_1']}，組 2：{ev['group_2']}）；規劃招募 **{en['total_units']} 位**（組 1：{en['group_1']}，組 2：{en['group_2']}）。"
            ]
        lines += [
            "",
            f"此整數設計的 power={row['achieved_power']:.8f}；目標={spec['target_power']}。預期留存 {row['expected_retained_units']:.8g} 個分析單位，屬期望值而非保證。",
        ]
        previous = row["previous_allocation"]
        lines += [
            f"前一個合乎分配比例的設計：{previous['total_units']} 個分析單位，power={previous['power']:.8f}，尚未達標。"
            if previous
            else "已達最小可計算設計：每組至少 2 人或至少 2 個完整配對。",
            "",
        ]
        lines += [f"- {warning}" for warning in row["warnings"]]
        if row["expected_cells"]:
            alternative = ", ".join(f"{n:.6g}" for n in row["expected_cells"]["alternative"])
            null = ", ".join(f"{n:.6g}" for n in row["expected_cells"]["pooled_null"])
            lines += [
                f"預期格數（依組 1 事件、組 1 非事件、組 2 事件、組 2 非事件；顯示至 6 位有效數字）：對立假設 [{alternative}]；pooled 虛無 [{null}]。",
                "",
            ]
    lines += [
        review_markdown(spec, result["limitations"]).replace(
            "# 前瞻樣本數規劃 — 待核准假設", "## 本次核准假設"
        ),
        "",
        "## 計算與重現",
        "",
        result["method_contract"][spec["design"]],
        "",
        result["method_contract"]["integer_search"],
        "",
        result["method_contract"]["enrollment"],
        "",
        "套件版本：" + "; ".join(f"{k}={v}" for k, v in result["engine_versions"].items()),
        "",
        "方法來源："
        + "、".join(
            f"[參考 {i+1}]({url})" for i, url in enumerate(result["method_contract"]["sources"])
        ),
        "",
        "## 投稿圖",
        "",
    ]
    for figure in rendered:
        publication = figure["publication"]
        lines += [
            f"![Figure {publication['figure_number']}]({Path(figure['path']).name})",
            "",
            publication["caption_en"],
            "",
            "中文解釋：" + publication["explanation_zh"],
            "",
        ]
    return "\n".join(lines)


def figures(
    result, directory, prefix="sample_size", preset_id="journal-neutral-english-v1", edition=None
):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    spec, records = result["spec"], []
    paired = spec["design"] == "paired_means"
    count_label = "Complete pairs" if paired else "Evaluable participants (both groups)"
    method = (
        f"{METHODS[spec['design']]}; a single two-sided test of zero difference with alpha={spec['alpha']:g} and target power={spec['target_power']:g}. "
        f"Counts denote {result['n_definition']}. "
        + (
            "The SD is that of within-pair differences. "
            if paired
            else f"Evaluable allocation n1:n2={spec['allocation'][0]}:{spec['allocation'][1]}. "
        )
        + "All scenarios and their assumption sources were specified before calculation; no patient outcomes were analyzed. "
    )
    method += (
        f"Planning population: {spec['population']!r}. Endpoint: {spec['endpoint']!r}; "
        f"time horizon: {spec['time_horizon']!r}; outcome unit: {spec['outcome_unit']!r}. "
        f"G1={spec['group_labels'][0]!r}; G2={spec['group_labels'][1]!r}. "
        f"Contrast definition: {spec['contrast']!r}; numerical differences always use G1 minus G2. "
    )
    assumptions = ""
    for row in result["scenarios"]:
        s = row["assumptions"]
        numeric = (
            f"p1={s['probabilities'][0]:g}, p2={s['probabilities'][1]:g}"
            if "probabilities" in s
            else f"signed difference={s['difference']:g}, SD={s['sd']:g} in the same declared outcome unit"
        )
        assumptions += f"{row['label']} ({'primary' if row['primary'] else 'sensitivity'}): {numeric}, common loss rate={s['loss_rate']:g}, evaluable n={row['evaluable']['total_units']}, power={row['achieved_power']:.6f}. "
    if spec["design"] == "independent_proportions":
        method += "Normal approximation with pooled null and unpooled alternative variances; no continuity correction or exact-test guarantee. "
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition

        def new(height):
            return plt.subplots(figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4))

        def save(fig, key, title, caption, explanation, data):
            publication = save_publication_figure(
                fig,
                directory,
                f"{prefix}_{key}",
                number=len(records) + 1,
                title=title,
                caption=method + assumptions + caption,
                explanation=explanation,
                data=data,
                profile=profile,
                receipt_sha256=result["receipt_sha256"],
            )
            records.append(
                {
                    "path": publication["files"]["png"],
                    "plot_type": f"sample_size_{key}",
                    "caption": publication["caption_en"] + "\n\n中文解釋：" + explanation,
                    "publication": publication,
                }
            )

        fig, ax = new(105 + 7 * len(result["scenarios"]))
        data = []
        colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#333333"]
        for i, row in enumerate(result["scenarios"]):
            points = row["power_curve"]
            label = f"S{i+1}: {row['label']}" + (" (primary)" if row["primary"] else "")
            ax.plot(
                [p["total_units"] for p in points],
                [p["power"] for p in points],
                color=colors[i],
                linestyle=["-", "--", "-.", ":", "-"][i],
                label="\n".join(textwrap.wrap(label, 35)),
            )
            ax.scatter(
                [row["evaluable"]["total_units"]],
                [row["achieved_power"]],
                color=colors[i],
                s=22,
                zorder=3,
            )
            data += [
                {"scenario_id": row["scenario_id"], "primary": row["primary"], **p} for p in points
            ]
        ax.axhline(spec["target_power"], color="#666666", linestyle="--", linewidth=0.8)
        ax.set(xlabel=count_label, ylabel="Design power", ylim=(0, 1.02))
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), borderaxespad=0)
        save(
            fig,
            "power",
            "Power across prespecified sample sizes",
            "Dots mark each minimum permitted integer design meeting the target; the dashed horizontal line marks target power. Curves join evaluated integer designs for display and are not confidence bands. Primary and sensitivity scenarios retain their original status.",
            "各點來自固定假設下的整數設計。實心點是該情境剛達標的最小分配；虛線是目標 power。曲線不是信賴區間，敏感度情境不會自動取代主情境。",
            data,
        )

        fig, ax = new(55 + 17 * len(result["scenarios"]))
        for i, row in enumerate(result["scenarios"]):
            ax.scatter(
                row["evaluable"]["total_units"],
                i - 0.12,
                color="#0072B2",
                marker="o",
                label="Evaluable" if i == 0 else None,
            )
            ax.scatter(
                row["enrollment"]["total_units"],
                i + 0.12,
                color="#D55E00",
                marker="s",
                label="Recruitment target" if i == 0 else None,
            )
            ax.plot(
                [row["evaluable"]["total_units"], row["enrollment"]["total_units"]],
                [i - 0.12, i + 0.12],
                color="#aaaaaa",
                linewidth=0.8,
            )
        ax.set_yticks(
            range(len(result["scenarios"])),
            [f"S{i+1}" + ("*" if r["primary"] else "") for i, r in enumerate(result["scenarios"])],
        )
        ax.set(
            xlabel="Pairs" if paired else "Participants (both groups)",
            ylabel="Prespecified scenario",
            ylim=(-0.7, len(result["scenarios"]) - 0.3),
        )
        ax.invert_yaxis()
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), borderaxespad=0)
        labels = "; ".join(f"S{i+1}={r['label']}" for i, r in enumerate(result["scenarios"]))
        save(
            fig,
            "recruitment",
            "Evaluable and recruitment counts by scenario",
            f"{labels}; an asterisk marks the primary scenario. Recruitment is rounded upward to preserve the declared allocation after a common expected loss rate. Expected retention is not guaranteed and does not address informative missingness, nonadherence or effect dilution. Exact group counts are provided in the accompanying table.",
            "藍色圓點是可分析數，橘色方點是保留分配比例、依共同缺失率向上取整的招募目標。星號代表事前指定的主情境；圖中的人數是總數，配對設計則是配對數。失訪膨脹不能補救偏差或效果稀釋。",
            summary_rows(result),
        )
    return records
