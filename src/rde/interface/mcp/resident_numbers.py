"""Parse authored measurements without treating ordinary Chinese classifiers as results."""

import re

DIGITS = dict(zip("零一二三四五六七八九", "0123456789", strict=True))
SMALL = {"十": 10, "百": 100, "千": 1000}
BIG = {"萬": 10000, "億": 100000000}
FOLD = str.maketrans(
    dict(
        zip(
            "０１２３４５６７８９．＋－−％〇○兩两壹貳贰參叁肆伍陸陆柒捌玖拾佰仟万亿点负",
            "0123456789.+--%零零二二一二二三三四五六六七八九十百千萬億點負",
            strict=True,
        )
    )
)
QUANTITY = re.compile(
    r"[正負+\-]?[0-9零一二三四五六七八九十百千萬億]+(?:[.點][0-9零一二三四五六七八九]+)?"
)
STAT = r"平均(?:數|值)?|均值|中位(?:數|值)?|最[大小]值|標準差|四分位(?:距|數)|[Qq][123]|\b(?:sd|iqr)\b|(?:完整|缺測|缺失|有效|總)(?:列數|筆數|比率|率|數|百分比)"


def decimal_text(word):
    sign = "-" if word[:1] in ("-", "負") else ""
    body = word.lstrip("正負+-").replace("點", ".")
    whole, _, fraction = body.partition(".")
    if not any(c in SMALL or c in BIG for c in whole):
        integer = "".join(DIGITS.get(c, c) for c in whole).lstrip("0") or "0"
    else:
        total = part = 0
        digit = None
        for c in whole:
            if c in SMALL:
                part += (1 if digit is None else digit) * SMALL[c]
                digit = None
            elif c in BIG:
                total += (part + (digit or 0)) * BIG[c]
                part = 0
                digit = None
            else:
                digit = (
                    int(DIGITS.get(c, c)) if digit is None else digit * 10 + int(DIGITS.get(c, c))
                )
        integer = total + part + (digit or 0)
    digits = "".join(DIGITS.get(c, c) for c in fraction)
    return sign + str(integer) + ("." + digits if digits else "")


def quantities(raw, masked, scope):
    # Each normalized character occupies the same code-point position as the original.
    text = masked.translate(FOLD)
    out = []
    for m in QUANTITY.finditer(text):
        before = text[: m.start()]
        after = text[m.end() :]
        cn = re.search(r"[正負零一二三四五六七八九十百千萬億點]", m.group())
        percent = bool(re.search(r"百分之$", before))
        if cn:
            if (
                before.endswith("第")
                or re.match(r"分位|組|群|類|分之", after)
                or re.search(r"(?:分組|組別)(?:為|是)?$", before)
            ):
                continue
            clause = re.split(r"[。；;，,\n]", before)[-1]
            metric = re.search(STAT, clause, re.I)
            plain_unit = re.match(r"\s*(?:" + re.escape(scope["unit"]) + r"|%)", after)
            if (
                m.group() == "一"
                and re.search(r"一(?:眼|人|列|筆|次)$", before)
                and re.match(r"眼|人|列|筆|次", after)
            ):
                continue
            if not (
                percent
                or plain_unit
                or (metric and "點" in m.group())
                or (metric and re.search(r"(?:為|達|計|等於|約|是)\s*$", clause))
            ):
                continue
            if re.match(r"個|項|種|方面|眼一人|人一眼|眼每人", after) and not plain_unit:
                continue
        if len(m.group()) > 100:
            # The native statistics are finite machine scalars. Keep malformed output
            # as a reviewable author error without converting an arbitrary-size integer.
            out.append(
                {
                    "issue": "UNBOUND_AUTHOR_NUMBER",
                    "start": m.start(),
                    "end": m.end(),
                    "quote": raw[m.start() : m.end()],
                    "unrepresentable": True,
                }
            )
            continue
        number = decimal_text(m.group())
        out.append(
            {
                "issue": "UNBOUND_AUTHOR_NUMBER",
                "start": m.start(),
                "end": m.end(),
                "quote": raw[m.start() : m.end()],
                "numeric": number,
                **({"implicit_percent": True} if percent else {}),
            }
        )
    return out
