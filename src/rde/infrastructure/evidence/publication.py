"""English publication figures drawn exclusively from verified, frozen R estimates."""

import math
from pathlib import Path

import numpy as np

from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from .contract import validate_result


COLORS = ["#236b8e", "#a15b20", "#397757", "#797979"]
PAGE = 15  # Same membership and figure count for every preset and edition.


def _number(x):
    return f"{x:.3g}" if x is not None else "NA"


def _pages(rows, size=PAGE):
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    if (
        digest({k: v for k, v in result.items() if k != "receipt_sha256"})
        != result["receipt_sha256"]
    ):
        raise ValueError("Evidence numerical receipt changed before rendering.")
    validate_result(result["analysis"])
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator, NullLocator

    r, records = result["analysis"], []
    o = r["options"]
    treatment_map = {v["code"]: v["label"] for v in r["treatment_map"]}
    source_rows = {v["row"]: v for v in r["observations"]}
    confidence = f"{100 * o['confidence']:g}%"
    scale = "MD (U1)" if o["measure"] == "MD" else o["measure"]
    identities = "; ".join(f"{k}={v!r}" for k, v in treatment_map.items())
    source = (
        f"Outcome={o['outcome']!r}; timepoint={o['timepoint']!r}. "
        f"{identities}. {r['study_count']} independent included studies, "
        f"{r['contrast_count']} included comparison rows. "
        + (
            f"U1 denotes the declared common outcome unit {o['outcomeUnit']!r}. "
            if o["measure"] == "MD"
            else "OR denotes odds ratio; RR denotes risk ratio. Input effects and standard errors use the log-ratio scale. "
        )
        + "Codes preserve source identities without translating treatment names. "
    )
    inference = (
        f"{o['model'].capitalize()}-effect model; saved {confidence} Wald confidence intervals. "
        "Intervals and p values are not adjusted across comparisons. "
        "Crossing the null or a nonsignificant test does not establish equivalence. "
        "No new model, ranking, resampling or test is run when drawing this figure. "
    )
    if any(v["source"].startswith("synthetic://") for v in r["observations"]):
        source += "Synthetic software-validation data; no clinical interpretation. "

    def new(height=90, forest=False):
        return plt.subplots(
            1,
            2 if forest else 1,
            squeeze=False,
            figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4),
            gridspec_kw={"width_ratios": [1.6, 1.5]} if forest else None,
        )

    def save(fig, key, title, caption, explanation, data):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_evidence_{key}",
            number=len(records) + 1,
            title=title,
            caption=source + caption,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
        )
        records.append(
            {
                "path": publication["files"]["png"],
                "plot_type": f"evidence_{key}",
                "caption": publication["caption_en"]
                + "\n\n中文解釋："
                + publication["explanation_zh"],
                "fonts": {"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                "publication": publication,
            }
        )

    def forest(rows, *, ratio, x_label, weights=False):
        fig, axes = new(max(65, 23 + 6 * len(rows)), forest=True)
        ax, table = axes[0]
        null = 1 if ratio else 0
        finite = [v for v in rows if v.get("status", "estimated") == "estimated"]
        limits = [null, *[v[k] for v in finite for k in ("lower", "upper")]]
        if max(limits) == min(limits):
            limits = [0.5, 2] if ratio else [-1, 1]
        if ratio:
            ax.set_xscale("log")
            ax.set_xlim(min(limits) / 1.12, max(limits) * 1.12)
            lo, hi = np.log(ax.get_xlim())
            positions = [(math.log(null) - lo) / (hi - lo)]
            for candidate in (0.0, 1.0, 0.5):
                if all(abs(candidate - present) >= 0.28 for present in positions):
                    positions.append(candidate)
            ticks = sorted(math.exp(lo + position * (hi - lo)) for position in positions)
            ax.xaxis.set_major_locator(FixedLocator(ticks))
            ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.3g}"))
            ax.xaxis.set_minor_locator(NullLocator())
        else:
            pad = (max(limits) - min(limits)) * 0.09
            ax.set_xlim(min(limits) - pad, max(limits) + pad)
            ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
        ax.axvline(null, color="#888888", linewidth=0.8, linestyle="--")
        for i, v in enumerate(rows):
            y = len(rows) - i
            if v.get("status", "estimated") != "estimated":
                text = "Not estimable"
            else:
                color = v.get("color", COLORS[0])
                ax.plot([v["lower"], v["upper"]], [y, y], color=color, linewidth=1)
                if v.get("pooled"):
                    ax.add_patch(
                        Polygon(
                            [
                                (v["lower"], y),
                                (v["estimate"], y + 0.18),
                                (v["upper"], y),
                                (v["estimate"], y - 0.18),
                            ],
                            color=color,
                        )
                    )
                else:
                    # All markers have equal area; weights are explicit numerical columns.
                    ax.plot(v["estimate"], y, "o", color=color, markersize=3.5)
                text = f"{_number(v['estimate'])} [{_number(v['lower'])}, {_number(v['upper'])}]"
                if weights:
                    text += (
                        f"\nWeight {_number(v.get('weight_percent'))}%"
                        if not v.get("pooled")
                        else "\nAll studies in this pair"
                    )
            table.text(0.02, y, text, va="center", fontsize=8)
        ax.set_yticks(range(len(rows), 0, -1), [v["label"] for v in rows])
        ax.set_ylim(0.4, len(rows) + 0.6)
        ax.set_xlabel(x_label)
        table.set_ylim(ax.get_ylim())
        table.set_xlim(0, 1)
        table.set_title(f"Estimate [{confidence} CI]", fontsize=9)
        table.axis("off")
        return fig

    decisions = r["review"]["decisions"]
    flow = [
        ("Uploaded comparison rows", r["review"]["inputRows"]),
        ("Explicitly excluded rows", sum(v["decision"] == "exclude" for v in decisions)),
        ("Included comparison rows", r["contrast_count"]),
    ]
    fig, axes = new(65)
    ax = axes[0, 0]
    ax.axis("off")
    table = ax.table(
        cellText=flow,
        colLabels=["Evidence-table disposition", "Rows"],
        colWidths=[0.8, 0.2],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2.3)
    save(
        fig,
        "flow",
        "Disposition of uploaded evidence-table rows.",
        "The unit counted in this figure is a comparison row, not a publication, participant or independent trial. Multi-arm studies contribute multiple correlated rows. This is not a PRISMA flow diagram and does not document the completeness of a literature search. All include/exclude decisions and original row numbers remain in the companion data.",
        "此圖計算研究表的比較列，不能當成文獻篇數、受試者數或 PRISMA 篩選圖。多臂試驗會有多列，但研究總數依 study_id 去重。",
        decisions,
    )

    nodes, edges = r["topology"]["nodes"], r["topology"]["edges"]
    codes = list(treatment_map)
    positions = {
        code: (math.cos(2 * math.pi * i / len(codes)), math.sin(2 * math.pi * i / len(codes)))
        for i, code in enumerate(codes)
    }
    midpoints = [
        tuple(
            (a + b) / 2
            for a, b in zip(
                positions[e["treatment_code"]], positions[e["comparator_code"]], strict=True
            )
        )
        for e in edges
    ]
    separated = all(
        math.dist(a, b) >= 0.25 for i, a in enumerate(midpoints) for b in midpoints[i + 1 :]
    )
    if len(nodes) <= 8 and len(edges) <= 10 and separated:
        fig, axes = new(105)
        ax = axes[0, 0]
        for edge in edges:
            a, b = positions[edge["treatment_code"]], positions[edge["comparator_code"]]
            ax.plot([a[0], b[0]], [a[1], b[1]], color="#888888", linewidth=1)
            ax.text(
                (a[0] + b[0]) / 2,
                (a[1] + b[1]) / 2,
                str(edge["studies"]),
                ha="center",
                va="center",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1},
            )
        for node in nodes:
            x, y = positions[node["code"]]
            ax.plot(x, y, "o", color=COLORS[0], markersize=6)
            ax.text(
                x * 1.2, y * 1.2, f"{node['code']}\nk={node['studies']}", ha="center", va="center"
            )
        ax.set(xlim=(-1.5, 1.5), ylim=(-1.5, 1.5), aspect="equal")
        ax.axis("off")
        topology_data = [
            {
                "record": "node",
                **n,
                "study_codes": ";".join(n["study_codes"]),
                "rows": ";".join(map(str, n["rows"])),
            }
            for n in nodes
        ] + [
            {
                "record": "edge",
                **e,
                "study_codes": ";".join(e["study_codes"]),
                "rows": ";".join(map(str, e["rows"])),
            }
            for e in edges
        ]
        save(
            fig,
            "network",
            "Network of direct treatment comparisons.",
            "Each edge label counts independent studies for that pair. Each node's k counts independent studies involving that treatment. Multi-arm trials occur on multiple edges and nodes, so these counts must not be added to obtain the study total. Node size and edge width are constant; positions are categorical, not clinical similarity or effect size. Original comparison-row membership is in the drawing data.",
            "線上的數字是該治療對的獨立研究數，節點 k 是涉及該治療的獨立研究數。多臂試驗會出現在多條線，因此不能加總；線寬、點大小及距離不表示療效。",
            topology_data,
        )
    else:
        # Dense networks use complete paginated adjacency cells instead of overlapping edge labels.
        adjacency = {
            tuple(sorted([e["treatment_code"], e["comparator_code"]])): e["studies"] for e in edges
        }
        for ai, a_page in enumerate(_pages(codes, 15)):
            for bi, b_page in enumerate(_pages(codes, 15)):
                values = np.array(
                    [
                        [
                            np.nan if a == b else adjacency.get(tuple(sorted([a, b])), 0)
                            for b in b_page
                        ]
                        for a in a_page
                    ]
                )
                fig, axes = new(120)
                ax = axes[0, 0]
                ax.imshow(
                    values,
                    cmap="Blues",
                    vmin=0,
                    vmax=max(e["studies"] for e in edges),
                    aspect="auto",
                )
                data = []
                for i, a in enumerate(a_page):
                    for j, b in enumerate(b_page):
                        count = None if a == b else int(values[i, j])
                        ax.text(
                            j,
                            i,
                            "-" if count is None else str(count),
                            ha="center",
                            va="center",
                            color="white"
                            if count and count > max(e["studies"] for e in edges) / 2
                            else "black",
                            fontsize=8,
                        )
                        data.append(
                            {
                                "treatment_code": a,
                                "treatment": treatment_map[a],
                                "comparator_code": b,
                                "comparator": treatment_map[b],
                                "studies": count,
                            }
                        )
                ax.set_xticks(range(len(b_page)), b_page, rotation=90)
                ax.set_yticks(range(len(a_page)), a_page)
                save(
                    fig,
                    f"network_{ai+1}_{bi+1}",
                    "Direct evidence network as independent-study counts.",
                    f"Matrix block {ai+1}, {bi+1}; all treatment-pair cells are retained across blocks. Zero means no included direct comparison; a dash is the self-comparison diagonal. Symmetric cells show the same pair twice and must not be summed. Counts are independent studies per pair, not patients or weights. Multi-arm studies can contribute to multiple pairs.",
                    "密集網絡以分頁矩陣保留全部治療對，避免線標籤重疊。0 表示沒有直接比較，自我比較為短線；對稱格重複表示同一治療對，不能相加。",
                    data,
                )

    for pair in r["pairwise"]:
        rows = [v for v in r["direct_observations"] if v["pair"] == pair["pair"]]
        pages = _pages(rows)
        for page_i, page in enumerate(pages):
            drawn = [{**v, "label": f"{v['study_code']} / R{v['row']}"} for v in page]
            drawn.append(
                {
                    **pair,
                    "label": f"Pooled (k={pair['studies']})",
                    "pooled": True,
                    "color": "#222222",
                }
            )
            fig = forest(drawn, ratio=o["measure"] != "MD", x_label=scale, weights=True)
            data = [
                {
                    "record": "study",
                    **v,
                    **{f"source_{key}": value for key, value in source_rows[v["row"]].items()},
                }
                for v in page
            ]
            data.append({"record": "pooled_all_studies_in_pair", **pair})
            study_identity = "; ".join(
                f"{v['study_code']}={v['study_id']!r} (R{v['row']})" for v in page
            )
            save(
                fig,
                f"direct_{pair['pair'].replace(':', '_')}_{page_i+1}",
                "Study effects and their direct-comparison synthesis.",
                inference
                + f"Direction is {pair['treatment_code']} relative to {pair['comparator_code']}; MD is first minus second. Page {page_i+1} of {len(pages)}. R denotes the original table row including the header. Study identifiers in this panel: {study_identity}. All source identities and direction reversals are in the drawing data. The diamond uses every study in this pair and is repeated on each page, not fitted to the displayed page. Marker areas are constant. Weights are percentages within this pair, using inverse variances"
                + (
                    " plus this pair's independently estimated REML tau-squared"
                    if o["model"] == "random"
                    else ""
                )
                + f". Pair-specific tau-squared={_number(pair['tau2'])}; I-squared={_number(pair['I2'])} as a 0-1 fraction; NA means not estimable. These are separate direct meta-analyses, not the direct component using the network's common tau-squared. Study intervals use supplied effect/SE and a normal approximation.",
                "每列保留原表列號、原始方向與獨立研究身份。菱形使用該治療對的全部研究；多頁只分開顯示，不重跑模型。權重在各治療對內加總為 100%，不能當作網絡貢獻度。",
                data,
            )

    reference = r["network"]["reference"] if r["network"] else r["reference"]
    for page_i, page in enumerate(_pages(reference)):
        fig = forest(
            [{**v, "label": v["treatment_code"]} for v in page],
            ratio=o["measure"] != "MD",
            x_label=scale,
        )
        save(
            fig,
            f"reference_{page_i+1}",
            "Treatment effects relative to the selected reference.",
            inference
            + f"Each treatment is relative to {o['reference']!r}. Page {page_i+1} of {len(_pages(reference))}. "
            + (
                "Network estimates account for multi-arm correlation and combine direct and indirect evidence under the stated assumptions. "
                if r["network"]
                else "Two-treatment pairwise synthesis; direction follows the selected reference. "
            )
            + "No prediction interval or treatment ranking is displayed. Clinical comparability and risk of bias require separate review.",
            "所有點均相對同一個已核准的參照治療；OR／RR 使用比值的對數座標。這不是排名圖，也沒有新增預測區間；仍須人工核對臨床可比較性與偏差。",
            page,
        )

    if r["network"]:
        local = r["diagnostics"]["local"]["rows"]
        comparisons = [v for v in local if v["component"] == "compare"]
        for page_i, page in enumerate(_pages(comparisons, 7)):
            selected = {(v["treatment_code"], v["comparator_code"]) for v in page}
            components = sorted(
                [
                    v
                    for v in local
                    if v["component"] in {"direct", "indirect"}
                    and (v["treatment_code"], v["comparator_code"]) in selected
                ],
                key=lambda v: (v["treatment_code"], v["comparator_code"], v["component"]),
            )
            fig = forest(
                [
                    {
                        **v,
                        "label": f"{v['treatment_code']}/{v['comparator_code']} {'D' if v['component'] == 'direct' else 'I'}",
                        "color": COLORS[v["component"] == "indirect"],
                    }
                    for v in components
                ],
                ratio=o["measure"] != "MD",
                x_label=scale,
            )
            save(
                fig,
                f"split_{page_i+1}",
                "Direct and indirect evidence for each treatment comparison.",
                inference
                + "D denotes direct and I indirect evidence under netmeta Back-calculation (SIDE). "
                + f"Page {page_i+1} of {len(_pages(comparisons, 7))}. Direction is the first treatment relative to the second. For random effects, both components use the network's common between-study variance, not each pairwise model's independently estimated variance. Not estimable is retained when a component cannot be estimated; it is not a null effect or proof of consistency.",
                "D／I 分別是直接與間接證據。隨機效應拆分使用網絡共用異質性，不能與獨立 pairwise 合併混讀。沒有間接路徑等情形保留為無法估計，不畫成零。",
                components,
            )
            fig = forest(
                [{**v, "label": f"{v['treatment_code']}/{v['comparator_code']}"} for v in page],
                ratio=False,
                x_label="Direct minus indirect\n"
                + ("MD (U1)" if o["measure"] == "MD" else f"log {o['measure']} difference"),
            )
            save(
                fig,
                f"inconsistency_{page_i+1}",
                "Local differences between direct and indirect evidence.",
                inference
                + "This is direct minus indirect on the analysis scale: "
                + (
                    "a difference of mean differences in U1"
                    if o["measure"] == "MD"
                    else f"a difference of log {o['measure']} values, not an {o['measure']}"
                )
                + ". The null is zero. Standard errors and intervals are saved netmeta Back-calculation outputs; no local test is recomputed. Not estimable rows remain visible. A nonsignificant local or global test cannot establish consistency or transitivity. Raw unadjusted p values and availability are in the drawing data.",
                "這是直接減間接的分析尺度差值，虛無值為 0；OR／RR 的圖軸是 log 比值之差，並非原比值。沒有把缺少證據視為一致，也沒有因不顯著而宣稱可互換。",
                page,
            )

    bias = list({v["study_code"]: v for v in r["observations"]}.values())
    categories = ["low", "some_concerns", "high", "unclear"]
    counts = [sum(v["risk_of_bias"] == k for v in bias) for k in categories]
    fig, axes = new(75)
    ax = axes[0, 0]
    bars = ax.bar(range(4), counts, color=COLORS)
    ax.set_xticks(range(4), ["Low", "Some\nconcerns", "High", "Unclear"])
    ax.set_ylabel("Independent studies")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(0, max(counts) + max(1, max(counts) * 0.2))
    for bar, count in zip(bars, counts, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, count, str(count), ha="center", va="bottom")
    save(
        fig,
        "bias",
        "Researcher-supplied risk-of-bias judgments.",
        f"Review tool declared by the researcher: {o['riskOfBiasTool']!r}. Each independent study is counted once, including multi-arm trials. These are the supplied overall judgments, not an automated assessment, domain-level traffic-light assessment, GRADE or CINeMA score. No weighting, pooling or uncertainty interval is applied. Full reasons, sources and extraction locators are retained in the drawing data.",
        "每項獨立研究只計一次，直接呈現研究者提供的整體偏差判定；平台沒有自動評分，也不把它當作 GRADE／CINeMA 或各領域偏差交通燈。",
        bias,
    )
    return records
