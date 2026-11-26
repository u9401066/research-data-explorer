"""Validate author-specified numeric/reference pairs and verbatim public dictionary excerpts."""

import re

from rde.interface.mcp.action_review import compare_scalar
from rde.interface.mcp.resident_bindings import expand
from rde.interface.mcp.resident_tables import display_stat, summary_tables


METRICS = {
    "rows": r"(?:全檔|全表|總|組內總)(?:樣本數|列數|筆數|記錄數|紀錄數)|總(?:共有|計|數)",
    "complete": r"完整(?:資料|紀錄|記錄|觀測|筆數|列數)|(?:資料|記錄)完整筆數",
    "observed": r"有效(?:觀測|測量|筆數)|非缺測(?:筆數|觀測)",
    "missing_group": r"缺(?:失|少)?(?:分組|組別)|分組缺失",
    "missing_measure": r"缺測量|測量缺(?:失|值)|量測缺(?:失|值)",
    "missing": r"缺(?:測|失|值)(?:資料)?(?:數量|筆數|數)",
    "missing_percent": r"缺(?:測|失|值)(?:百分比|率|比例)",
    "observed_percent": r"(?:有效|完整|觀測)(?:測量)?(?:百分比|率|比例)",
    "mean": r"平均(?:數|值)?(?!差)|均值(?!差)",
    "median": r"中位(?:數|值)(?!差)",
    "min": "最小值",
    "max": "最大值",
    "sd": r"標準差|\bSD\b",
    "iqr": r"四分位距|\bIQR\b",
    "q1": r"下四分位數|第一四分位數|\bQ1\b",
    "q3": r"上四分位數|第三四分位數|\bQ3\b",
    "mean_difference": r"(?:平均(?:數|值)?|均值)(?:之|的)?差",
    "median_difference": r"中位數(?:之|的)?差",
}
TOKEN = re.compile(r"\{\{R(\d+\.\d+)\}\}|\[R(\d+\.\d+)\]")


def source_fields(scope):
    note = scope["source_note"]
    link = re.search(r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+", note)
    if not link:
        return {}
    url = link.group().rstrip(".,;")
    fields = {}
    excluded = re.sub(
        r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+", lambda m: "\n" * len(m.group()), note
    )
    for clause in re.finditer(r"[^。；;\n]+", excluded):
        quote = clause.group().strip(" ，,")
        if re.search(r"\d", quote) and len(quote) <= 420:
            start = note.index(quote, clause.start())
            fields["S" + str(len(fields) + 1)] = {
                "quote": quote,
                "url": url,
                "start": start,
                "end": start + len(quote),
            }
    return fields


def render(raw, cards, scope):
    fields = source_fields(scope)
    replacements = []

    def one(match):
        token = match.group()
        source = fields.get(token[2:-2])
        if source:
            value = "「" + source["quote"] + "」" + "（[來源字典](" + source["url"] + ")）"
        elif scope.get("manuscript_protocol") == "paragraph-v3" and token == "{{group_table}}":
            value = summary_tables(cards, scope)
        elif (
            scope.get("manuscript_protocol") == "paragraph-v3"
            and token[2:-2].startswith("R")
            and token[3:-2] in cards
        ):
            value = display_stat(cards[token[3:-2]]) + "[" + token[2:-2] + "]"
        else:
            value, changes = expand(token, cards, scope)
            if not changes:
                return token
        replacements.append(
            {"token": token, "rendered": value, "start": match.start(), "end": match.end()}
        )
        return value

    text = re.sub(r"\{\{(?:R\d+\.\d+|S\d+|group_table|source)\}\}", one, raw)
    return text, replacements


def numeric_links(raw, scope, cards, unchecked):
    problems, links = [], []
    for item in unchecked:
        start, end = item["start"], item["end"]
        left = max(raw.rfind(ch, 0, start) for ch in "，,。；;\n") + 1
        stops = [i for c in "，,。；;\n" if (i := raw.find(c, end)) >= 0]
        right = min(stops, default=len(raw))
        clause = raw[left:right]
        clean = TOKEN.sub("", clause)
        tags = {m.group(1) or m.group(2) for m in TOKEN.finditer(clause)}
        if not tags:
            problems.append(
                {
                    **item,
                    "quote": clause,
                    "repair": "在統計指標及組別旁選用一張相符的 {{R卡號}}；刪除未指向證據的數值。",
                }
            )
            continue
        valid = []
        for key in tags:
            c = cards.get(key)
            if not c or type(c.get("value")) not in (float, int):
                continue
            number = item["quote"]
            if not compare_scalar(c["value"], float(number), min(8, len(number.partition(".")[2]))):
                continue
            field = c["statistic"]
            if field not in METRICS or not re.search(METRICS[field], clean, re.I):
                continue
            present = {k for k, p in METRICS.items() if re.search(p, clean, re.I)}
            for stat in ("mean", "median"):
                if stat + "_difference" in present:
                    present.discard(stat)
            if present != {field}:
                continue
            if c.get("group"):
                groups = {str(card["group"]) for card in cards.values() if card.get("group")}
                mentioned = {
                    g
                    for g in groups
                    if re.search(
                        r"(?<![A-Za-z\d])"
                        + re.escape(g)
                        + r"\s*(?:組|群)|(?:組別|組|"
                        + re.escape(scope["group"])
                        + r")\s*[=:：]?\s*"
                        + re.escape(g)
                        + r"(?![A-Za-z\d])",
                        clean,
                        re.I,
                    )
                }
                expected_groups = {str(c["group"])}
                if c.get("reference_group"):
                    expected_groups.add(str(c["reference_group"]))
                if mentioned != expected_groups:
                    continue
            unit = c["unit"]
            unit_pattern = r"(?:筆|列|個|例|人|份)" if unit == "筆" else re.escape(unit)
            if not re.match(r"\s*" + unit_pattern, TOKEN.sub("", raw[end:right])):
                continue
            valid.append(key)
        if len(valid) == 1:
            links.append(
                {
                    "start": start,
                    "end": end,
                    "quote": item["quote"],
                    "reference": "R" + valid[0],
                    "pointer": cards[valid[0]]["pointer"],
                }
            )
        else:
            problems.append(
                {
                    **item,
                    "issue": "NUMERIC_CITATION_CONTEXT_MISMATCH",
                    "quote": clause,
                    "selected": [
                        {
                            "reference": "R" + k,
                            "field": cards[k]["label"],
                            "value": cards[k]["value"],
                        }
                        for k in sorted(tags)
                        if k in cards
                    ],
                    "repair": "將數值、同一統計欄名、單位及組別和正確卡號放在同一短句；或只選欄位代碼以免重複。",
                }
            )
    return problems, links
