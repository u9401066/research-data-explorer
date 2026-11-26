"""Capability-aware feedback for descriptive action choices and sentence-level author edits."""

from __future__ import annotations

import json
import re

LIMITS = {
    "data_quality": "全檔分母及缺測欄位；各組的名稱、筆數及比率由分組工具提供。",
    "group_estimates": "各組列數、有效數與算術平均；離散度由 group_spread、端點由 distribution 計算。",
    "distribution": "組內中位數、最小與最大，不能判定常態性、分布形狀或重疊的比例。",
    "group_spread": "組內四分位、四分位距與樣本標準差，不交付排序後的明細或全距端點。",
    "group_completeness": "各組缺測與有效比例，可審視資料涵蓋。母群代表性需另有抽樣框及選樣資料。",
    "group_contrasts": "原量綱的平均差和中位數差，判斷顯著性、因果或臨床重要性需另有設計或檢定。",
}
STATISTICS = {
    "group_estimates": r"平均(?:數|值)|均值|\bmean\b",
    "group_spread": r"四分位|四分位距|標準差|标准差|\b(?:sd|iqr|q[13])\b",
    "distribution": r"中位數|中位数|極值|极值|(?:全距|範圍)端點|最大值|最小值",
    "group_completeness": r"(?:缺(?:失|測|值)|完整|有效|可用)(?:百分比|率)",
    "group_contrasts": r"(?:平均(?:數|值)?|中位數|均值)(?:差(?:異|值)?|的組間差)",
}
UNSUPPORTED = (
    (
        "NORMALITY",
        r"常態(?:性|分布|分佈)?|常态|正態|正态|正常範態|normality|gaussian",
        "可描述端點、中心或離散，判定常態需要其他分布證據。",
    ),
    (
        "INFERENCE",
        r"顯著(?:性|差異)|显著|統計推論|統計意義|臨床(?:重要性|意義|或統計意義)|p\s*值|信賴區間|significance|clinical significance",
        "此處只能描述已觀測差異。顯著性要有推論方法，臨床意義要有事前閾值及背景。",
    ),
    (
        "REPRESENTATIVENESS",
        r"代表(?:外部)?母群|代表性|representativeness",
        "完整程度只能說明現有資料的缺測，代表性須核對抽樣框與納入方式。",
    ),
)
NEG = r"不能|無法|不(?:可|能|足以|足|宜|代表|等於|等同|進行|作|會|涉及|用以|能据此)|不足|未(?:能|經|做|進行|證實|知|檢驗)|無從|沒有|並非|缺乏|避免|另(?:需|須|行|待|用)|另外需要|需要另|留待|尚待|若要|若需|if\b|cannot|not\b|requires? (?:another|additional)"
SEGMENT = r"[^。！？!?；;，,\n]+"


def qualified(clause, match):
    prefix = clause[: match.start()]
    suffix = clause[match.end() :]
    # A qualification after a coordinated list may govern the whole list.
    return bool(
        re.search(NEG, prefix, re.I)
        or re.search(
            r"^(?:[）)」\s]*)(?:尚?需(?:要)?(?:其他|另|額外)|有待|需另|需其他|不可|無法|不能)",
            suffix,
        )
    )


def action_reason(action, reason, observed):
    out = []

    def issue(code, sentence, repair):
        out.append(
            {"issue": code, "quote": sentence, "repair": repair, "capability": LIMITS[action]}
        )

    # Respect independently negated clauses and separately planned statistics.
    for sentence in re.finditer(SEGMENT, reason):
        clause = sentence.group()
        for code, pattern, advice in UNSUPPORTED:
            for match in re.finditer(pattern, clause, re.I):
                if code == "REPRESENTATIVENESS" and re.search(
                    r"(?:可能|恐|風險).{0,5}(?:影響|限制|損及)", clause[: match.start()]
                ):
                    continue
                if not qualified(clause, match):
                    issue("ACTION_UNSUPPORTED_" + code, clause, advice)
                    break
        for provider, pattern in STATISTICS.items():
            if provider == action:
                continue
            if (
                action == "group_contrasts"
                and provider in ("group_estimates", "distribution")
                and re.search(r"平均|均值|中位", clause)
                and re.search(r"差(?:距|值|異)?|相減", clause)
                and not re.search(r"最大|最小|極值|端點", clause)
            ):
                continue
            for match in re.finditer(pattern, clause, re.I):
                if qualified(clause, match):
                    continue
                # Mentioning prior evidence, or a separate later action, is legitimate.
                prefix = clause[: match.start()]
                if re.search(
                    r"先前|上一|已(?:有|知|取得|觀察)|前次|上一步|根據|後續|另行|再(?:檢查|比較)|之後",
                    prefix,
                ):
                    continue
                explicit = re.search(
                    r"(?:本|此|這)(?:步|次|項|個檢查|檢查|工具).{0,15}(?:計算|提供|產生|給出|驗證|取得|回傳|估計)|(?:將|直接|可同時|必須)(?:同時)?(?:計算|檢查|取得|比較)|^(?:其中)?包括",
                    clause,
                )
                if explicit:
                    issue(
                        "ACTION_FIELD_NOT_PROVIDED",
                        clause,
                        "要取得這項欄位須另選 " + provider + "。",
                    )
                    break
        if (
            action == "data_quality"
            and re.search(
                r"(?:驗證|檢查|確認).{0,8}(?:各組|每組|兩組|所有組).{0,24}(?:存在|人數|樣本量|分布)",
                clause,
            )
            and not re.search(NEG, clause)
        ):
            issue(
                "ACTION_GROUP_SCOPE_MISMATCH",
                clause,
                "data_quality 只有全檔品質，檢查各組應使用分組觀測。",
            )
    # Per-group rows are not the full dataset (this claim requires an actual data_quality receipt).
    total = re.search(r"(?:全檔筆數|總樣本(?:數)?|全(?:部|體)樣本數)[^。；;\d]{0,18}(\d+)", reason)
    if total and not re.search(NEG, re.split(r"[，,。；;]", reason[: total.start()])[-1]):
        actual = observed.get("data_quality", {}).get("rows")
        if actual is None or int(total.group(1)) != actual:
            issue(
                "GLOBAL_DENOMINATOR_NOT_VERIFIED",
                total.group(),
                "全檔總列數使用 data_quality.rows；分組結果中的 rows 只屬於該組。",
            )
    return out


def sentence_slices(text):
    # Delimiters belong to the sentence on their left; keep every byte of whitespace.
    return re.findall(r"[^。！？!?\n]*[。！？!?\n]|[^。！？!?\n]+$", text) or [""]


def edit_schema(count):
    return {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "minItems": 1,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {
                        "sentence": {"type": "integer", "minimum": 0, "maximum": count - 1},
                        "text": {"type": "string"},
                    },
                    "required": ["sentence", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["edits"],
        "additionalProperties": False,
    }


def apply_edits(sentences, response):
    item = json.loads(response)
    if not isinstance(item, dict) or set(item) != {"edits"} or not isinstance(item["edits"], list):
        raise ValueError("INVALID_SENTENCE_EDITS")
    edits, used = list(sentences), set()
    if not 1 <= len(item["edits"]) <= len(sentences):
        raise ValueError("INVALID_SENTENCE_EDITS")
    for change in item["edits"]:
        if not isinstance(change, dict) or set(change) != {"sentence", "text"}:
            raise ValueError("INVALID_SENTENCE_EDITS")
        i, text = change["sentence"], change["text"]
        if (
            type(i) is not int
            or not 0 <= i < len(sentences)
            or i in used
            or not isinstance(text, str)
            or len(text) > 5000
        ):
            raise ValueError("INVALID_SENTENCE_EDITS")
        used.add(i)
        edits[i] = text
    return "".join(edits)
