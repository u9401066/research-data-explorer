"""Compact data displays for the paragraph protocol with explicit native field references."""

import re
from rde.interface.mcp.resident_bindings import _cell

COUNTS = {"rows", "complete", "observed", "missing", "missing_group", "missing_measure"}


def display_stat(card):
    v = card["value"]
    if v is None:
        return "無法估計"
    if card["statistic"] in COUNTS:
        return str(int(v))
    if type(v) not in (int, float):
        return str(v)
    precision = 8 if v and abs(v) < 0.0001 else 4
    whole, fraction = f"{v:.{precision}f}".split(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


def summary_tables(cards, scope):
    lookup = {}
    labels = {}
    contrasts = {}
    for key, card in cards.items():
        action = card["label"].split("/", 1)[0]
        m = re.search(r"/(?:groups|comparisons)/(\d+)/([^/]+)$", card["pointer"])
        i = int(m.group(1)) if m else None
        field = card["statistic"]
        lookup[action, i, field] = (key, card)
        if action == "group_estimates" and field == "group":
            labels[i] = card["value"]
        if action == "group_contrasts" and field in {"group", "reference"} and i is not None:
            contrasts.setdefault(i, {})[field] = card["value"]

    def cell(action, i, field):
        key, card = lookup[action, i, field]
        return display_stat(card) + "[R" + key + "]"

    def table(head, rows):
        lines = [head, ["---"] * len(head), *rows]
        return "\n".join("| " + " | ".join(_cell(v) for v in row) + " |" for row in lines)

    def groups(fields):
        return [
            [labels[i], *(cell(action, i, field) for action, field in fields)]
            for i in sorted(labels)
        ]

    g, u = scope["group"], scope["unit"]
    quality = ("rows", "missing_group", "missing_measure", "complete")
    completeness = ("rows", "observed", "missing", "observed_percent", "missing_percent")

    def names(titles):
        return [s + "（" + u + "）" for s in titles]

    summaries = [
        table(
            ["全檔筆數", "缺分組筆數", "缺測量筆數", "完整筆數"],
            [[cell("data_quality", None, f) for f in quality]],
        ),
        table(
            [g, "組內總筆數", "有效筆數", "缺測筆數", "有效測量率（%）", "缺測率（%）"],
            groups([("group_completeness", f) for f in completeness]),
        ),
        table(
            [g, *names(["平均數", "中位數", "最小值", "最大值"])],
            groups(
                [
                    ("group_estimates", "mean"),
                    *(("distribution", f) for f in ("median", "min", "max")),
                ]
            ),
        ),
        table(
            [g, *names(["下四分位數", "上四分位數", "四分位距", "樣本標準差"])],
            groups([("group_spread", f) for f in ("q1", "q3", "iqr", "sd")]),
        ),
    ]
    comparison = [
        [
            r["group"],
            r["reference"],
            cell("group_contrasts", i, "mean_difference"),
            cell("group_contrasts", i, "median_difference"),
        ]
        for i, r in sorted(contrasts.items())
    ]
    summaries.append(
        table(
            ["比較組（" + g + "）", "參照組（" + g + "）", *names(["平均數差", "中位數差"])],
            comparison,
        )
    )
    if not comparison:
        summaries.append("無可比較的組合。")
    return "\n\n".join(summaries)
