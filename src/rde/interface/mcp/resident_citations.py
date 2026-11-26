"""Validate author-specified numeric/reference pairs and verbatim public dictionary excerpts."""

from decimal import Decimal
import re

from rde.interface.mcp.resident_bindings import expand
from rde.interface.mcp.resident_tables import display_stat, summary_tables
from rde.interface.mcp.resident_numbers import FOLD


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
    "q1": r"下四分位數|第一四分位數|(?<![A-Za-z0-9_])Q1(?![A-Za-z0-9_])",
    "q3": r"上四分位數|第三四分位數|(?<![A-Za-z0-9_])Q3(?![A-Za-z0-9_])",
    "mean_difference": r"(?:平均(?:數|值)?|均值)(?:之|的)?差",
    "median_difference": r"中位數(?:之|的)?差",
}
TOKEN = re.compile(r"\{\{R(\d+\.\d+)\}\}|\[R(\d+\.\d+)\]")


def contrast_direction(clause, card):
    """Match the named subtraction or explicit reference role in an author's clause."""

    def named(level):
        level = re.escape(str(level))
        return rf"(?:(?<![A-Za-z0-9]){level}\s*(?:組|群)|(?:組別|組|group)\s*[=:：]?\s*{level}(?![A-Za-z0-9]))"

    def ordered(comparison, reference):
        return bool(
            re.search(
                comparison
                + r"\s*(?:扣除|減去?|[−－-]|相(?:較|對)(?:於)?|相對于|minus)\s*(?:參照|對照)?"
                + reference,
                clause,
                re.I,
            )
            or re.search(
                r"以\s*"
                + reference
                + r"\s*(?:作為|為|作)?\s*(?:參照|基準|對照)(?:組)?[^。；]{0,25}"
                + comparison,
                clause,
                re.I,
            )
        )

    comparison, reference = named(card["group"]), named(card["reference_group"])
    forward, backward = ordered(comparison, reference), ordered(reference, comparison)
    if forward != backward:
        return "comparison_minus_reference" if forward else "reference_minus_comparison"
    return (
        "ambiguous"
        if re.search(comparison, clause, re.I) or re.search(reference, clause, re.I)
        else "unspecified"
    )


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


def matches_authored_number(actual, number):
    if type(actual) not in (int, float):
        return False
    source = Decimal(str(actual))
    authored = Decimal(number)
    if not source.is_finite() or not authored.is_finite():
        return False
    places = len(number.partition(".")[2])
    if places > 8:
        return source == authored
    return abs(source - authored) <= Decimal("0.5").scaleb(-places)


def numeric_links(raw, scope, cards, unchecked, *, selected_ids=None):
    problems, links = [], []
    for item in unchecked:
        if item.get("unrepresentable"):
            problems.append(item)
            continue
        start, end = item["start"], item["end"]
        left = max(raw.rfind(ch, 0, start) for ch in "，,。；;\n") + 1
        stops = [i for c in "，,。；;\n" if (i := raw.find(c, end)) >= 0]
        right = min(stops, default=len(raw))
        clause = raw[left:right]
        clean = TOKEN.sub("", clause)
        inline = {m.group(1) or m.group(2) for m in TOKEN.finditer(clause)}
        selected = {ref[1:] for ref in (selected_ids or ())}
        tags = (inline if selected_ids is None else inline & selected) if inline else selected
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
            number = item.get("numeric", item["quote"])
            if not matches_authored_number(c["value"], number):
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
            if c.get("group") or not inline:
                groups = {
                    str(card[k])
                    for card in cards.values()
                    for k in ("group", "reference_group")
                    if card.get(k)
                }
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
                expected_groups = {str(c["group"])} if c.get("group") else set()
                if c.get("reference_group"):
                    expected_groups.add(str(c["reference_group"]))
                if mentioned != expected_groups:
                    continue
                if (
                    not inline
                    and not expected_groups
                    and not re.search(
                        r"全檔|全表|整體|整份|全資料集|全部(?:紀錄|記錄|資料)|whole dataset|all rows",
                        clean,
                        re.I,
                    )
                ):
                    continue
                if (
                    scope.get("manuscript_protocol") == "paragraph-v3"
                    and c.get("reference_group")
                    and contrast_direction(clean, c) != "comparison_minus_reference"
                ):
                    continue
            unit = c["unit"]
            unit_pattern = r"(?:筆|列|個|例|人|份)" if unit == "筆" else re.escape(unit)
            if unit == "筆" and scope.get("manuscript_protocol") == "paragraph-v3":
                unit_pattern = r"(?:筆|列|條(?:紀錄|記錄)|rows?\b|records?\b)"
            implicit = unit == "%" and item.get("implicit_percent")
            if not implicit:
                tail = TOKEN.sub("", raw[end:right]).translate(FOLD)
                match = re.match(r"\s*" + unit_pattern, tail)
                if not match:
                    continue
                if scope.get("manuscript_protocol") == "paragraph-v3" and re.match(
                    r"\s*(?:[A-Za-z0-9µμ⁰¹²³⁴⁵⁶⁷⁸⁹₀-₉/%％／^⁄·×＊]|平方|立方)", tail[match.end() :]
                ):
                    continue
            valid.append(key)
        if len(valid) == 1:
            key = valid[0]
            tag = re.search(r"\[R" + re.escape(key) + r"\]", raw[end:right])
            links.append(
                {
                    "start": start,
                    "end": end,
                    "quote": item["quote"],
                    "reference": "R" + valid[0],
                    "pointer": cards[valid[0]]["pointer"],
                    **(
                        {
                            "numeric": item["numeric"],
                            "match_method": "inline_reference" if inline else "selected_evidence",
                            "context_start": left,
                            "context_end": right,
                            "context_quote": clause,
                            **({"manual_tag_start": end + tag.start()} if tag else {}),
                        }
                        if "numeric" in item
                        else {}
                    ),
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
