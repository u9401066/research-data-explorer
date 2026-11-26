"""Resolve only author-selected evidence fields, reference links or native aggregate tables."""

import re


def _cell(value):
    return (
        str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    )


def displayed(value):
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def table(cards, scope):
    by_group = {}
    for key, card in cards.items():
        parts = card["pointer"].split("/")
        if "/groups/" not in card["pointer"]:
            continue
        action = card["label"].split("/", 1)[0]
        row = by_group.setdefault(int(parts[-2]), {})
        row[action, parts[-1]] = (key, card["value"])
    columns = [("group_estimates", "observed", "有效觀測數"), ("group_estimates", "mean", "平均")]
    if any(("distribution", "median") in row for row in by_group.values()):
        columns.extend(
            ("distribution", k, name)
            for k, name in [("median", "中位數"), ("min", "最小值"), ("max", "最大值")]
        )
    headers = [_cell(scope["group"])] + [
        name if field == "observed" else f"{name}（{_cell(scope['unit'])}）"
        for _, field, name in columns
    ]
    rows = [headers, ["---"] * len(headers)]
    for _, row in sorted(by_group.items()):
        label = _cell(row["group_estimates", "group"][1])
        cells = [label]
        for action, field, _ in columns:
            if (action, field) not in row:
                cells.append("缺測")
            else:
                key, value = row[action, field]
                cells.append(f"{displayed(value)}[R{key}]")
        rows.append(cells)
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def expand(text, cards, scope):
    """The trace preserves exact raw tokens, rendered bytes and their source binding."""
    replacements = []

    def render(match):
        token = match.group(1)
        if token == "group_table":
            value = table(cards, scope)
        elif token == "source":
            url = re.search(r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+", scope["source_note"])
            if not url:
                return match.group()
            value = "<" + url.group().rstrip(".,;") + ">"
        else:
            card = cards.get(token[1:])
            if card is None:
                return match.group()
            value = displayed(card["value"]) + f"[{token}]"
        replacements.append(
            {"token": match.group(), "rendered": value, "start": match.start(), "end": match.end()}
        )
        return value

    output = re.sub(r"\{\{(group_table|source|R\d+\.\d+)\}\}", render, text)
    return output, replacements


def edited_blocks(previous, reply):
    """Apply only edits explicitly supplied by the resident, addressed to whole Markdown blocks."""
    import json

    obj = json.loads(reply)
    blocks = re.split(r"\n\s*\n", previous.strip())
    if (
        not isinstance(obj, dict)
        or set(obj) != {"edits"}
        or not isinstance(obj["edits"], list)
        or not 0 < len(obj["edits"]) <= len(blocks)
    ):
        raise ValueError("INVALID_EDIT_SET")
    used = set()
    for edit in obj["edits"]:
        if not isinstance(edit, dict) or set(edit) != {"block", "text"}:
            raise ValueError("INVALID_EDIT")
        i, text = edit["block"], edit["text"]
        if (
            type(i) is not int
            or not 0 <= i < len(blocks)
            or i in used
            or not isinstance(text, str)
            or len(text) > 12000
        ):
            raise ValueError("INVALID_EDIT")
        used.add(i)
        blocks[i] = text
    return "\n\n".join(block for block in blocks if block.strip())
