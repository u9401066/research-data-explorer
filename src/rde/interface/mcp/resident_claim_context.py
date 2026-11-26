"""Locate an unsupported scientific relation in its own clause, keeping its actor and target."""

import re

# One-to-one character normalization keeps offsets in the author's original UTF-8 text.
NORMALIZE = str.maketrans(
    "样体组间处疗药剂响预导误会评释断仅从为显据应无严随对认义结获够产证区总数论还线变临床归纳额标",
    "樣體組間處療藥劑響預導誤會評釋斷僅從為顯據應無嚴隨對認義結獲夠產證區總數論還線變臨床歸納額標",
)
ACTOR = r"(?:治療|干預|介入|用藥|藥物|分派|處置|暴露|方案|分組|組別|組間差(?:異|距)|treatment|intervention|exposure|allocation)"
TARGET = r"(?:基線|起始|初始|介入前|入組時|原有狀態|健康狀態|治療反應|疾病結局|臨床反應|症狀|生存|病程|療效|死亡風險|baseline|pretreatment|clinical outcome|response to treatment)"
PREDICATE = r"(?:導致|造成|引起|致使|改變|影響|效應|作用|effect|impact|caus(?:e|ed|al))"
META = r"(?:誤解|誤讀|誤判|閱讀|解讀|詮釋|文字表述|理解|估算精度|估計精確|標準誤|分母(?:大小)?|可用筆數|選法|量綱|查驗)"
NEG = r"無法|不能|不可|不(?:能據此|應|表示|意味|代表|等同|足以|足|支持|宜|是)|無從|沒有(?:證據|資料)|未(?:能|證實|檢驗|提供)|並非|不是|避免|防止|勿(?:將|把)|難以|不能排除|cannot|does not|without evidence"
FUTURE = r"若(?:要|想|需|欲)|如(?:要|需|欲)|若將來|日後若|未來(?:需|可|應)|有待|另(?:需|須|待|行)|需要另|需額外"
BOUNDARY = r"[。！？!?；;，,\n]|然而|但是|反而|而是|不過|卻|但"
POPULATION = r"(?:母體|母群(?:體)?|總體|人群)"


def clauses(text):
    normalized = text.translate(NORMALIZE)
    start = 0
    for b in re.finditer(BOUNDARY, normalized):
        if start < b.start():
            yield start, b.start(), normalized[start : b.start()]
        start = b.end()
    if start < len(text):
        yield start, len(text), normalized[start:]


def qualified_relation(clause, start, end):
    before = clause[:start]
    after = clause[end:]
    # The last conjunction starts a new proposition. Negating A cannot license B.
    before = re.split(r"且|仍可|仍能|同時(?:可|能)|另外|反倒", before)[-1]
    return bool(
        re.search(NEG, before, re.I)
        or re.search(FUTURE, before, re.I)
        or re.search(
            r"^(?:仍|尚)?(?:需(?:要)?另|須另|有待|無法|不能|不可|並非|不足)", after.lstrip(" 」）)")
        )
    )


def relation_diagnostics(text, scope):
    target = TARGET
    if scope.get("measure"):
        target = "(?:" + TARGET + "|" + re.escape(scope["measure"].translate(NORMALIZE)) + ")"
    findings = []
    for first, last, clause in clauses(text):
        for formula in re.finditer(
            r"(?:IQR|四分位距)\s*(?:=|＝|為|是|等於|定義為)\s*Q([123])\s*(?:-|−|－|減去|減)\s*Q([123])",
            clause,
            re.I,
        ):
            if formula.groups() != ("3", "1") and not qualified_relation(
                clause, formula.start(), formula.end()
            ):
                findings.append(
                    {
                        "issue": "STATISTIC_DEFINITION_MISMATCH",
                        "start": first + formula.start(),
                        "end": first + formula.end(),
                        "quote": text[first + formula.start() : first + formula.end()],
                        "basis": "scope.methods",
                        "repair": "核對 method_definitions.iqr 定義中上、下四分位數與相減方向。",
                    }
                )
        # Require the scientific actor, its proposed effect and the measured/clinical target.
        # A method affecting comprehension or available records is a different proposition.
        for a in re.finditer(ACTOR, clause, re.I):
            for t in re.finditer(target, clause, re.I):
                if max(a.end(), t.end()) - min(a.start(), t.start()) > 58:
                    continue
                p = None
                if a.start() < t.start():
                    p = re.search(PREDICATE, clause[a.end() : t.start()], re.I)
                    trailing = re.search(
                        r"^(?:[^。；，]{0,9})(?:的|之)?(?:影響|效應|作用)(?:程度|大小|幅度|量)?",
                        clause[t.end() :],
                        re.I,
                    )
                    if not p and not trailing:
                        continue
                    end = t.end() + (trailing.end() if trailing else 0)
                    start = a.start()
                else:
                    # Reverse the word order only where an explicit attribution connects them.
                    if not re.search(
                        r"(?:受|歸因於|是由|乃由|可由|源自|取決於|為).{0,12}$",
                        clause[t.end() : a.start()],
                    ):
                        continue
                    if (
                        not re.search(r"影響|效應|導致|造成|決定|引起", clause[a.end() :])
                        and "歸因於" not in clause[t.end() : a.start()]
                    ):
                        continue
                    start, end = t.start(), len(clause)
                statement = clause[start:end]
                if (
                    re.search(META, statement)
                    or qualified_relation(clause, start, end)
                    or re.search(NEG + "|" + FUTURE, statement)
                ):
                    continue
                findings.append(
                    {
                        "issue": "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE",
                        "start": first + start,
                        "end": first + end,
                        "quote": text[first + start : first + end],
                        "actor": a.group(),
                        "target": t.group(),
                        "repair": "群組量測只能說明這批資料的分布或差值；這項資料無法估計某處置對該量測的因果效應。",
                    }
                )
                break
            else:
                continue
            break
        population = re.search(
            rf"(?:抽樣(?:的)?代表(?:性|程度|可能)|樣本(?:的|是否|能否|具有|具備|具|可)?代表(?:性|的?可能(?:性)?|程度|能力|(?:外部)?{POPULATION})|(?:代表(?:外部)?{POPULATION}|{POPULATION}(?:的)?代表性)|population representativeness|representative of)",
            clause,
            re.I,
        )
        if population:
            evaluating = re.search(
                r"評估|推(?:估|定|斷)|判(?:斷|定)|可判|檢驗|證(?:明|實)|確認|量化|反映|保證|看出|詮釋|代表(?:性|程度).{0,3}(?:充分|足夠)|具有|infer|establish",
                clause,
                re.I,
            )
            uncertainty = re.search(
                r"可能.{0,6}(?:限制|影響)|無從|另需|尚待|有待|仍需額外|不能推定", clause
            )
            if (
                evaluating
                and not uncertainty
                and not qualified_relation(clause, population.start(), population.end())
            ):
                findings.append(
                    {
                        "issue": "ACTION_UNSUPPORTED_REPRESENTATIVENESS",
                        "start": first,
                        "end": last,
                        "quote": text[first:last],
                        "target": population.group(),
                        "repair": "此工具可核對樣本內的資料。母群代表性需另有抽樣框、納入與未納入者等資料。",
                    }
                )
    return findings
