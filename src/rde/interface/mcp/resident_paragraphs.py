"""An opt-in descriptive manuscript protocol. Each model reply has an immutable review."""

from __future__ import annotations

from hashlib import sha256
import json
import re

from rde.infrastructure.adapters.dataframe_lineage import dataset_version
from rde.interface.mcp.action_review import artifact_json, digest, pointer, review
from rde.interface.mcp import resident_protocol_v3 as v3
from rde.interface.mcp.research_plans import read_sealed, write_once
from rde.interface.mcp.resident import (
    ACTION_SCHEMA,
    PARAGRAPH_ACTIONS,
    SECTIONS,
    card_index,
    cited_claims,
    observations,
)
from rde.interface.mcp.resident_bindings import displayed
from rde.interface.mcp.resident_citations import numeric_links, render, source_fields
from rde.interface.mcp.resident_reasoning import (
    LIMITS,
    action_reason,
    apply_edits,
    edit_schema,
    sentence_slices,
)


# Each assignment describes work for the resident. The host supplies no manuscript prose.
TASKS = (
    ("解釋研究問題、觀測單位與量測尺度。", "data_quality"),
    ("辨認資料來源、資料字典及本次採用的欄位，文中連結 {{source}}。", "source"),
    ("說明分組如何界定比較對象，區分分組、抽樣與分派。", "design"),
    ("界定描述性比較要回答的問題，以及回答它需要哪些可觀測證據。", "design"),
    ("用原始筆數與完整筆數說明各種分母的計數規則。", "data_quality"),
    ("比較各組可用測量與缺值的分母，解釋缺值比例的計算方式。", "group_completeness"),
    ("說明平均數和中位數各自回答的中心位置問題，列出計算條件。", "group_estimates"),
    ("說明四分位數線性內插、四分位距和樣本標準差的算法與單位。", "group_spread"),
    ("比較每組平均、有效筆數與量測單位，另起一行放 {{group_table}} 供讀者核對。", "table"),
    ("解讀各組的中位數和範圍，區分典型值與邊界觀測。", "distribution"),
    ("解讀組內離散程度，用四分位距與標準差描述各組變異。", "group_spread"),
    ("解讀平均差與中位數差，明確交代比較組減參照組和原量綱。", "group_contrasts"),
    ("利用各組缺測比率評估完整資料分析的涵蓋範圍。", "group_completeness"),
    ("比較平均差與中位數差的方向與尺度，評估描述對摘要選擇的敏感性。", "group_contrasts"),
    ("對照組內四分位範圍和整體極值，討論兩種摘要提供的不同訊息。", "spread_range"),
    ("評估分組組成、觀測單位或資料收集背景如何影響比較，明示哪些解釋仍待證實。", "design"),
    ("說明觀測層級及相依性對可做的推論有何影響，區分資料能核對和無法判斷之處。", "design"),
    ("界定抽樣涵蓋的對象、代表性與外推條件，指出來源有何實際限制。", "design"),
    ("給出可依來源重算的順序，對照原始欄名、分母及數值定位。", "reproduce"),
    ("指出下一個可實際驗證的研究問題、所需新增證據與會改變解讀的結果。", "design"),
)
DESCRIPTIONS = {
    "data_quality": "rows 全檔筆數、missing_group 缺組、missing_measure 缺測、complete 兩欄皆有值。",
    "group_estimates": "每組 rows 組內全部筆數、observed 有測量筆數、mean 算術平均。",
    "distribution": "每組非缺測的 median 中位數、min 最小值、max 最大值。",
    "group_spread": "非缺測值排序，q1/q3 以 (n−1)p 線性內插；iqr=q3−q1；sd 為樣本標準差除數 n−1。",
    "group_completeness": "每組 missing=rows−observed、missing_percent=100×missing/rows、observed_percent=100×observed/rows。未歸組資料另計。",
    "group_contrasts": "按原生排序，首個有測量組為參照；mean_difference、median_difference 是比較組減參照組的原量綱差。",
}
FIELD_TITLES = {
    "rows": "筆數",
    "observed": "有效筆數",
    "complete": "完整筆數",
    "missing_group": "缺分組筆數",
    "missing_measure": "缺測量筆數",
    "missing": "缺測筆數",
    "missing_percent": "缺測百分比",
    "observed_percent": "有效測量百分比",
    "mean": "平均數",
    "median": "中位數",
    "min": "最小值",
    "max": "最大值",
    "q1": "下四分位數",
    "q3": "上四分位數",
    "iqr": "四分位距",
    "sd": "樣本標準差",
    "mean_difference": "平均數差",
    "median_difference": "中位數差",
}


def feedback(disposition, reason, **checks):
    return {
        "feedback": {"disposition": disposition, "reason": reason},
        "checklist": [{"check": name, "passed": value} for name, value in checks.items()],
    }


def raw_hash(value):
    return sha256(value.encode("utf-8")).hexdigest()


def remaining(folder):
    return [a for a in PARAGRAPH_ACTIONS if not (folder / f"{a}.json").exists()]


def sections():
    return [
        {
            "index": i,
            "title": title,
            "paragraphs": [{"turn": t, "focus": TASKS[t][0]} for t in range(i * 4, (i + 1) * 4)],
        }
        for i, title in enumerate(SECTIONS)
    ]


def approved_context(scope):
    return {
        k: scope[k] for k in ("question", "group", "measure", "unit", "population", "source_note")
    }


def next_action(scope, available, observed=None, prior=None):
    schema = {
        **ACTION_SCHEMA,
        "properties": {
            **ACTION_SCHEMA["properties"],
            "action": {"type": "string", "enum": available},
        },
    }
    prompt = (
        "你是研究作者。根據核准範圍及已觀測的彙總結果，選下一個檢查。"
        "只輸出 JSON 的 action 和 reason；說明此檢查能解答的問題，勿預先假定結果或研究設計。\n"
        + json.dumps(approved_context(scope), ensure_ascii=False)
        + "\n可選檢查 "
        + json.dumps(
            {a: {"outputs": DESCRIPTIONS[a], "limits": LIMITS[a]} for a in available},
            ensure_ascii=False,
        )
    )
    if observed is not None:
        prompt += "\n最近一次彙總 " + json.dumps(observed, ensure_ascii=False)
    if scope.get("manuscript_protocol") == "paragraph-v3":
        contracts = v3.capabilities(scope, DESCRIPTIONS)
        prior = prior or {}
        schema = v3.choice_schema(available, contracts, prior)
        prompt = (
            "選擇一項描述性研究查詢。action、purpose 與 intended_fields 請從同一份契約逐字選擇。reason 用一句自然繁體中文解釋為何需要這些欄位。"
            "先前觀測若有相關，可用 prior_refs 標記；總列、分組列、有效列和個人數的定義分開。\n"
            + json.dumps(approved_context(scope), ensure_ascii=False)
            + "\n可選："
            + json.dumps({a: contracts[a] for a in available}, ensure_ascii=False)
            + "\n已取得的資料證據："
            + json.dumps(prior, ensure_ascii=False)
        )
        return {
            "response_schema": schema,
            "prompt": prompt,
            "remaining_actions": available,
            "capabilities": contracts,
            "prior_evidence": prior,
        }
    return {
        "response_schema": schema,
        "prompt": prompt,
        "remaining_actions": available,
        "capabilities": {
            a: {"outputs": DESCRIPTIONS[a], "limits": LIMITS[a]} for a in PARAGRAPH_ACTIONS
        },
    }


def safe_grouping(frame, scope):
    group = scope["group"]
    if group not in frame or scope["measure"] not in frame:
        raise ValueError("UNKNOWN_OR_DUPLICATE_COLUMN")
    if re.search(
        r"(?:^|[^a-z])(?:id|mrn|ssn|email|name)(?:$|[^a-z])|^(?:patient|subject|person|participant)(?:id|number)?$|recordid$|姓名|身分證|識別碼|病歷號",
        group,
        re.I,
    ):
        raise ValueError("IDENTIFIER_GROUP_NOT_ALLOWED")
    for v in frame[group].dropna().unique():
        if len(str(v)) > 100 or re.search(
            r"@|[\r\n]|^\d{7,}$|[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}", str(v), re.I
        ):
            raise ValueError("IDENTIFIER_GROUP_NOT_ALLOWED")


def scientific_issues(text, scope):
    """Check affirmative, local assertions; negation of one design does not license another."""
    rules = (
        (
            "UNDOCUMENTED_STUDY_DESIGN",
            r"隨機(?:分派|分配|分組|對照試驗|試驗)|randomi[sz]ed(?:\s+(?:allocation|trial|assignment))?",
        ),
        (
            "UNDOCUMENTED_STUDY_DESIGN",
            r"隨機(?:抽樣|取樣|分派與抽樣|分配與抽樣)|random\s+sampl(?:e|ing)",
        ),
        ("UNDOCUMENTED_STUDY_DESIGN", r"雙盲|double.blind"),
        ("UNDOCUMENTED_STUDY_DESIGN", r"分層隨機化|分層隨機分派|stratified randomi[sz]ation"),
        (
            "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE",
            r"統計(?:學)?(?:上)?顯著|顯著(?:提升|降低|增加|高於|低於)|統計(?:學)?意義|statistically significant",
        ),
        (
            "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE",
            r"(?:具有|存在|證實|確立)(?:了)?因果|導致|造成|信賴區間(?:為|是)|[pP]\s*[<≤=]|(?:證明|證實)(?:療效|治療效果)",
        ),
        (
            "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE",
            r"(?:判斷|推斷|推論|評估).{0,20}是否.{0,12}影響治療反應|影響治療反應的.{0,8}因子|對風險因素的影響機制",
        ),
    )
    negation = r"未(?:曾|必|能)?|無法|無從|不是|並非|非(?:經由)?|不(?:宜|能|應|足以|代表|屬於|是|具|具有|可)|沒有|缺乏|是否|避免|難以|假如|若|假設|可能|cannot|without|not\s"
    boundary = r"[。；;!！?？\n，,]|但(?:是)?|然而|而是"

    def hits(body, pattern):
        for m in re.finditer(pattern, body, re.I):
            before = re.split(boundary, body[: m.start()])[-1]
            if not re.search(negation, before[-32:], re.I):
                yield m

    approved = scope["source_note"] + " " + scope["population"]
    out = []
    for issue, pattern in rules:
        if issue == "UNDOCUMENTED_STUDY_DESIGN" and next(hits(approved, pattern), None):
            continue
        for match in hits(text, pattern):
            out.append(
                {"issue": issue, "start": match.start(), "end": match.end(), "quote": match.group()}
            )
    return out


def observe(project, entry, scope, anchor, folder, turn, response):
    if turn not in range(1, 19) or turn > 1 and not (folder / f"action-{turn-1}.json").exists():
        raise ValueError("INVALID_ACTION_SEQUENCE")
    receipt = folder / f"action-{turn}.json"
    if receipt.exists():
        prior = read_sealed(receipt)["payload"]
        if prior["response"] != response:
            raise ValueError("ACTION_REPLAY_CHANGED")
        return prior["result"]
    try:
        choice = json.loads(response)
    except ValueError:
        choice = None
    action = choice.get("action") if isinstance(choice, dict) else None
    modern = scope.get("manuscript_protocol") == "paragraph-v3"

    def previous_cards():
        if not modern:
            return {}
        per_action = {}
        for k, c in card_index(project, folder).items():
            family = c["label"].split("/")[0]
            per_action.setdefault(family, {})
            if type(c["value"]) in (int, float) and len(per_action[family]) < 8:
                per_action[family]["R" + k] = {"field": c["label"], "value": c["value"]}
        return {k: v for block in per_action.values() for k, v in block.items()}

    issue, observation, errors = None, None, []
    if (
        action not in PARAGRAPH_ACTIONS
        or (not modern and set(choice) != {"action", "reason"})
        or not isinstance(choice.get("reason"), str)
        or not choice["reason"].strip()
    ):
        issue = "INVALID_ACTION_OR_REASON"
    elif modern and (
        errors := v3.intent_issues(choice, v3.capabilities(scope, DESCRIPTIONS), previous_cards())
    ):
        issue = errors[0]["issue"]
    elif errors := scientific_issues(choice["reason"], scope) + action_reason(
        action,
        choice["reason"],
        {
            k: read_sealed(folder / f"{k}.json")["payload"]["observation"]
            for k in PARAGRAPH_ACTIONS
            if (folder / f"{k}.json").exists()
        },
    ):
        issue = errors[0]["issue"]
    else:
        path = folder / f"{action}.json"
        owner = {"turn": turn, "response_sha256": raw_hash(response)}
        if path.exists():
            saved = read_sealed(path)["payload"]
            if saved.get("owner") != owner:
                issue = "REPEATED_ACTION"
            else:
                observation = saved["observation"]
        else:
            observation = observations(entry.dataframe, scope, action)
            write_once(
                path,
                {
                    "source": scope["source"],
                    "version": anchor["version"],
                    "owner": owner,
                    "observation": observation,
                },
            )
    result = {
        "status": "repair" if issue else "observed",
        "action": action,
        "issue": issue,
        "issues": list(dict.fromkeys(d["issue"] for d in errors)) or ([issue] if issue else []),
        "diagnostics": errors,
        "observation": observation,
        **next_action(scope, remaining(folder), observation, previous_cards()),
        **feedback(
            "repair" if issue else "accept",
            issue or f"已核對 {action} 的已核准欄位與來源版本。",
            approved_source=True,
            action_observed=not issue,
        ),
    }
    if issue:
        result["prompt"] = (
            "上一個選擇需修正："
            + json.dumps(errors or [issue], ensure_ascii=False)
            + "。用一句話說明所選工具會取得的實際欄位。\n"
            + result["prompt"]
        )
    if modern:
        result["intent"] = (
            {k: choice.get(k) for k in ("action", "purpose", "intended_fields", "prior_refs")}
            if isinstance(choice, dict)
            else None
        )
        result["semantic_scope"] = "獨立科學評閱仍須核對自由理由與申報用途。"
    write_once(receipt, {"turn": turn, "response": response, "result": result})
    return result


def actions_for(kind):
    return {
        "source": [],
        "design": [],
        "table": ["group_estimates", "distribution"],
        "reproduce": ["data_quality"],
        "spread_range": ["group_spread", "distribution"],
    }.get(kind, [kind])


def card_details(cards, scope):
    """A reader can resolve every card without the source host or a row-level export."""
    details = {}
    for key, card in cards.items():
        field = card["pointer"].rsplit("/", 1)[-1]
        action, *rest = card["label"].split("/")
        measure = scope["measure"] if field in FIELD_TITLES else None
        unit = (
            "%"
            if field.endswith("_percent")
            else "筆"
            if field
            in {
                "rows",
                "observed",
                "complete",
                "missing",
                "missing_measure",
                "missing_group",
            }
            else scope["unit"]
            if measure
            else None
        )
        details[key] = {
            **card,
            "statistic": field,
            "statistic_title": FIELD_TITLES.get(field, field),
            "measure_column": measure,
            "group_column": scope["group"],
            "unit": unit,
        }
        if len(rest) >= 3:
            details[key]["group"] = "/".join(rest[1:-1])
            if action == "group_contrasts":
                details[key]["reference_group"] = next(
                    c["value"] for c in cards.values() if c["label"] == "group_contrasts/reference"
                )
    return details


def evidence_index(scope, cards):
    def cell(value):
        return (
            str(value if value is not None else "—")
            .replace("|", "\\|")
            .replace("\n", " ")
            .replace("\r", " ")
        )

    lines = [
        "# 原生資料證據索引",
        "",
        "來源 SHA-256：" + scope["source"],
        "",
        "分組欄：" + scope["group"] + "。測量欄：" + scope["measure"] + "。",
        "",
        "正文的 R 編號對應原生運算與欄位。差值方向為所列組別減參照組。",
        "",
        "| 引用 | 運算 | 組別 | 參照組 | 欄位 | 原生值 | 單位 | 原生 JSON 定位 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    artifacts = {}
    for key, card in cards.items():
        action = card["label"].split("/", 1)[0]
        artifacts[action] = (card["artifact_id"], card["sha256"])
        row = (
            "R" + key,
            action,
            card.get("group"),
            card.get("reference_group"),
            card["statistic_title"] + " (" + card["statistic"] + ")",
            card["value"] if card["value"] is not None else "null（無法估計）",
            card["unit"],
            card["pointer"],
        )
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    lines += ["", "## 原生觀測檔", "", "| 運算 | Artifact ID | SHA-256 |", "|---|---|---|"]
    lines.extend("| " + " | ".join((a, *v)) + " |" for a, v in artifacts.items())
    return "\n".join(lines) + "\n"


def manuscript_title(scope):
    # Approved prompts may include operational directions after (or instead of) a question.
    match = re.match(r"\s*([^\n。；;！？?!]{3,100}[？?])", scope["question"])
    if match:
        return match.group(1)
    return f"{scope['measure']} 依 {scope['group']} 分組的描述性研究"


def paragraph_path(folder, turn, attempt):
    return folder / f"paragraph-{turn:02}-{attempt}.json"


def accepted(folder, turn):
    for attempt in (1, 2, 3, 4, 5):
        path = paragraph_path(folder, turn, attempt)
        if path.exists():
            record = read_sealed(path)["payload"]
            if not record["result"]["issues"]:
                return record
    return None


def assignments(scope, turn, cards, prior, previous):
    focus, kind = TASKS[turn]
    if scope.get("manuscript_protocol") == "paragraph-v3" and turn == 0:
        kind = "design"
    actions = actions_for(kind)
    relevant = {}
    for key, c in cards.items():
        action = c["label"].split("/")[0]
        if action not in actions or type(c["value"]) not in (float, int):
            continue
        field = c["statistic"]
        if field in ("observed", "rows") and action not in ("data_quality", "group_completeness"):
            continue
        comparison = " 減參照組 " + c["reference_group"] if c.get("reference_group") else ""
        relevant["{{R" + key + "}}"] = (
            " / ".join(filter(None, [c.get("group", "") + comparison, c["statistic_title"]]))
            + " = "
            + displayed(c["value"])
            + " "
            + c["unit"]
        )
    prompt = (
        "你是研究作者。為此研究撰寫一個可獨立理解、能銜接前後文的繁體中文研究段落。"
        "這一段的任務："
        + focus
        + "\n核准資料："
        + json.dumps(
            {**approved_context(scope), "question": manuscript_title(scope)}, ensure_ascii=False
        )
        + "\n直接輸出正文，約 190 至 320 個中文字。不要輸出章名、小標、清單、JSON、作者自述或寫作指示。"
        "用具體科學解釋把本段的問題、觀察和意義連起來，各段各有新資訊。"
        "樣本描述須區分資料列、量測及個人，不能把組別差異當療效。"
        "依來源寫明設計；隨機分派與隨機抽樣依據不同。"
        "須書寫數字組別時直接在代碼後加「組」。其餘測量數值使用提供的資料欄位代碼。"
        "自行決定論述的句子，勿抄任務或前稿。"
    )
    role = (
        "本章建立問題與來源，交代量測和目標。",
        "本章寫讀者可操作的計算與分母規則，用證據定位規則，避免預先解讀結果。",
        "本章寫實際觀察、方向與大小，勿重教方法。",
        "本章檢查資料品質與摘要選擇是否改變描述，勿重述結果表。",
        "本章交代範圍、外推條件與重現性，給出具體品質或驗證條件。",
    )
    prompt += "\n本章角色：" + role[turn // 4]
    dictionary = source_fields(scope)
    if dictionary:
        prompt += (
            "\n如需引用含數字的資料字典定義，可選原文代碼以帶入原文、單位及來源連結："
            + json.dumps(
                {"{{" + key + "}}": v["quote"] for key, v in dictionary.items()}, ensure_ascii=False
            )
        )
    if relevant:
        prompt += (
            "\n引用下列與本段相符的欄位，用完整的 {{R卡號}} 代碼放在相應組別、統計指標之後。"
            "系統會代入值和引文，勿另抄數字。" + json.dumps(relevant, ensure_ascii=False)
        )
    elif actions and kind != "table":
        prompt += "\n這項彙總沒有可計算的所需數值。說明哪些條件使本項無法估計，不推測數字。"
    if actions:
        prompt += "\n運算定義：" + " ".join(DESCRIPTIONS[k] for k in actions)
    if prior:
        prompt += "\n前段已完成的任務（不要重寫）：" + " ".join(
            TASKS[r["turn"]][0] for r in prior[-4:]
        )
        prompt += "\n緊接的上段結尾：" + prior[-1]["author_source"].strip()[-120:]
    if previous:
        prompt += (
            "\n本回合是局部修訂。只輸出 JSON edits，依下列句號索引修正有問題的句子；刪句用空字串。"
            "text 寫你自行修訂的完整句子並保留句尾標點，不需重抄其餘句子。原稿索引："
            + json.dumps(
                list(enumerate(sentence_slices(previous["author_source"]))), ensure_ascii=False
            )
            + "\n實際核對："
            + json.dumps(previous["result"]["diagnostics"][:12], ensure_ascii=False)
        )
    return prompt


def clean_text(text):
    return re.sub(r"\{\{[^{}]*\}\}|https?://\S+|[^\w\u3400-\u9fff]", "", text).casefold()


def repetition(raw, prior):
    def grams(s):
        return {s[i : i + 5] for i in range(len(s) - 4)}

    current = clean_text(raw)
    sentences = {clean_text(s) for s in re.split(r"[。！？；\n]", raw) if len(clean_text(s)) >= 18}
    all_sentences = [
        clean_text(s) for s in re.split(r"[。！？；\n]", raw) if len(clean_text(s)) >= 18
    ]
    if len(sentences) != len(all_sentences):
        return "WITHIN_PARAGRAPH_REPETITION"
    shingles = grams(current)
    for item in prior:
        old = item["author_source"]
        old_sentences = {clean_text(s) for s in re.split(r"[。！？；\n]", old)}
        old_grams = grams(clean_text(old))
        if sentences & old_sentences or (
            shingles and len(shingles & old_grams) / len(shingles) >= 0.52
        ):
            return "REPEATED_PARAGRAPH_CONTENT"
    return None


def scope_numbers(raw, scope, cards):
    """Ignore digits *within* approved codes/units/column names and author-selected bindings."""
    text = re.sub(r"\{\{[^{}]*\}\}|\[R\d+\.\d+\]", lambda m: " " * len(m.group()), raw)
    allowed = {scope[k] for k in ("group", "measure", "unit")}
    allowed.update(str(c["group"]) for c in cards.values() if c.get("group") is not None)
    for word in sorted((w for w in allowed if re.search(r"\d", w)), key=len, reverse=True):
        # Standalone numeric group levels are valid labels only in explicit group context.
        pattern = (
            r"(?:"
            + re.escape(scope["group"])
            + r"|組別|組|類別|分組|分類|代碼|編碼|group)\s*(?:為|是|等於|=|：|:)?\s*"
            + re.escape(word)
            + r"(?![\d.])"
            + r"|(?<![\d.])"
            + re.escape(word)
            + r"\s*(?:組|類)"
        )
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", word):
            pattern = re.escape(word)
        text = re.sub(pattern, lambda m: " " * len(m.group()), text, flags=re.I)
    # Statistical formula names are method terminology. Other sample counts/effects must bind.
    text = re.sub(
        r"\b(?:q[13]|ddof\s*=\s*1|n\s*[-−]\s*1)\b", lambda m: " " * len(m.group()), text, flags=re.I
    )
    for year in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", scope["source_note"]):
        text = re.sub(year + r"(?=\s*年)", "    ", text)
    return [
        {"issue": "UNBOUND_AUTHOR_NUMBER", "start": m.start(), "end": m.end(), "quote": m.group()}
        for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text)
    ]


def claim_context(raw, cards):
    """Catch explicit adjacent wrong labels; qualitative scientific meaning still needs review."""
    names = {
        "mean": r"平均(?:數|值)?",
        "median": r"中位(?:數|值)?",
        "min": "最小值",
        "max": "最大值",
        "iqr": "四分位距",
        "sd": r"(?:樣本)?標準差",
        "q1": r"(?:第一|下)四分位數",
        "q3": r"(?:第三|上)四分位數",
        "mean_difference": r"平均(?:數|值)?差(?:值)?",
        "median_difference": r"中位(?:數|值)?差(?:值)?",
    }
    groups = {c["group"] for c in cards.values() if c.get("group")}
    out = []
    for m in re.finditer(r"\{\{R(\d+\.\d+)\}\}", raw):
        c = cards.get(m.group(1))
        if not c:
            continue
        clause = re.split(r"[，,。；;：:\n]|\}\}", raw[: m.start()])[-1]
        for field, name in names.items():
            label = re.search(
                r"(?:" + name + r")(?:約為|分別為|為|是|達|約|等於)?\s*$", clause, re.I
            )
            if not label:
                continue
            if field != c["statistic"]:
                out.append(
                    {
                        "issue": "CITATION_METRIC_MISMATCH",
                        "quote": clause[-60:] + m.group(),
                        "expected": c["label"],
                    }
                )
            prefix = clause[: label.start()]
            for g in groups:
                if g != c.get("group") and re.search(
                    r"(?<![\w.])" + re.escape(g) + r"(?:組|群)?(?:的|之)?\s*$",
                    prefix,
                    re.ASCII | re.I,
                ):
                    out.append(
                        {
                            "issue": "CITATION_GROUP_MISMATCH",
                            "quote": clause[-60:] + m.group(),
                            "expected": c["label"],
                        }
                    )
            break
    return out


def check_paragraph(
    project, scope, cards, turn, raw, prior, *, presentation=None, extra_diagnostics=()
):
    focus, kind = TASKS[turn]
    modern = scope.get("manuscript_protocol") == "paragraph-v3"
    if modern and turn == 0:
        kind = "design"
    diagnostics = list(extra_diagnostics)

    def problem(code, **details):
        diagnostics.append({"issue": code, **details})

    if presentation is not None:
        text, replacements, attachments = v3.compose(raw, presentation, cards, scope)
    else:
        text, replacements = render(raw, cards, scope)
        attachments = []
    prose = clean_text(raw)
    han = re.findall(r"[\u3400-\u9fff]", prose)
    if len(han) < 90 or len(set(han)) < 35:
        problem("INSUFFICIENT_OR_PADDED_PROSE", measured_characters=len(han), minimum=90)
    if (
        len(set(han).intersection("之於的是以為其可應與在而由將從或按但和需有未比並對")) < 3
        or len(re.findall(r"[。，；！？、]", raw)) < 2
    ):
        problem("UNSTRUCTURED_PROSE", expected="請用完整的繁體中文句子說明觀察及意義。")
    if len(prose) > 850:
        problem("EXCESSIVE_PARAGRAPH_LENGTH", measured_characters=len(prose))
    if re.search(r'(^\s*[#>|*\-]|\x60\x60\x60|<[^ >]+>|待填寫|XX\.XX|\{\s*"\w+"\s*:)', raw, re.M):
        problem("UNEXPECTED_FORMAT_OR_PLACEHOLDER")
    if re.search(r"https?://", raw):
        problem("UNBOUND_SOURCE_LINK", expected="{{source}}")
    if re.search(
        r"\{\{|\}\}|\[R\d|\[E?\d+\]",
        re.sub(r"\{\{(?:R\d+\.\d+|S\d+|source|group_table)\}\}|\[R\d+\.\d+\]", "", raw),
    ):
        problem("UNKNOWN_OR_MANUAL_BINDING")
    if "{{" in text or "}}" in text:
        problem("UNKNOWN_FIELD_BINDING")
    if modern:
        for m in re.finditer(r"\[\[[^\n]*?\]\]|(?<![\[{])\bR\d+\.\d+\b(?![\]}])", raw):
            problem(
                "UNRESOLVED_EDITOR_MARKUP",
                start=m.start(),
                end=m.end(),
                quote=m.group(),
                repair="以自然語句撰寫，正式數值引用用該統計指標旁的 {{R卡號}}；公開來源連結用 {{source}}。",
            )
    if (
        kind == "source"
        and not (presentation and (presentation["link_source"] or presentation["source_ids"]))
        and "{{source}}" not in raw
        and not any("{{" + s + "}}" in raw for s in source_fields(scope))
    ):
        problem("SOURCE_LINK_REQUIRED", expected="{{source}}")
    if raw.count("{{group_table}}") + int(bool(presentation and presentation["group_table"])) != (
        1 if kind == "table" else 0
    ):
        problem("GROUP_TABLE_PLACEMENT", expected=1 if kind == "table" else 0)
    if len(text) > 20000 or len(raw) > 5000:
        problem("REVIEW_SIZE_LIMIT")
    if code := repetition(raw, prior):
        problem(code)
    diagnostics.extend(scientific_issues(raw, scope))
    numbers, linked = numeric_links(raw, scope, cards, scope_numbers(raw, scope, cards))
    diagnostics.extend(numbers)
    diagnostics.extend(claim_context(raw, cards))
    null_checks = []
    binding_text = text
    if modern:
        cache = {}

        def check_null(m):
            k = m.group(1)
            c = cards.get(k)
            valid = False
            if c and c["value"] is None:
                identity = (c["artifact_id"], c["sha256"])
                if identity not in cache:
                    cache[identity] = artifact_json(project.id, *identity)
                valid = pointer(cache[identity], c["pointer"]) is None
            null_checks.append(
                {"reference": "R" + k, "pointer": c["pointer"] if c else None, "native_null": valid}
            )
            if not valid:
                problem("INVALID_UNESTIMABLE_REFERENCE", quote=m.group())
            return " " * len(m.group())

        binding_text = re.sub(r"無法估計\[R(\d+\.\d+)\]", check_null, text)
    claims, used, binding_issues = cited_claims(binding_text, cards, scope["unit"])
    diagnostics.extend(binding_issues)
    actions = actions_for(kind)
    field_by_action = {
        "distribution": {"min", "max", "median"},
        "group_estimates": {"mean"},
        "group_spread": {"q1", "q3", "sd", "iqr"},
        "group_completeness": {"missing", "missing_percent", "observed_percent", "observed"},
        "group_contrasts": {"mean_difference", "median_difference"},
        "data_quality": {"rows", "missing_group", "missing_measure", "complete"},
    }
    for action in actions:
        eligible = {
            k
            for k, c in cards.items()
            if c["label"].startswith(action + "/")
            and c["statistic"] in field_by_action[action]
            and type(c["value"]) in (int, float)
        }
        if eligible and not eligible.intersection(used):
            problem(
                "FOCUS_EVIDENCE_REQUIRED",
                action=action,
                eligible=["R" + k for k in sorted(eligible)][:24],
            )
    reviews = []
    if claims and len(text) <= 20000:
        for i in range(0, len(claims), 32):
            part = claims[i : i + 32]
            native = review(project.id, text, part)
            reviews.append(native)
            for item in native["checks"]:
                if item["issue"]:
                    claim = part[item["claim"]]
                    problem(item["issue"], quote=claim["quote"], pointer=claim["pointer"])
    issues = list(dict.fromkeys(d["issue"] for d in diagnostics))
    for diagnostic in diagnostics:
        issue = diagnostic["issue"]
        diagnostic.setdefault(
            "repair",
            {
                "UNDOCUMENTED_STUDY_DESIGN": "只按核准來源敘述。分派決定受試者如何進組；抽樣決定個體如何進入樣本。缺乏資料的程序請刪除或明確標示未知。",
                "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE": "刪除無法用核准描述統計回答的療效、機制或推論；若談未來研究，要明確標明還需哪些新證據。",
                "FOCUS_EVIDENCE_REQUIRED": "在本段指明一個可用卡號，放在符合的統計名、組別或分母旁。",
                "CITATION_METRIC_MISMATCH": "核對引文卡名稱，讓正在說明的欄位與卡號相符。",
            }.get(issue, "依檢查項目及定位修訂該句；保留符合本段任務的其他句子。"),
        )
        if isinstance(diagnostic.get("start"), int):
            pos = 0
            for i, sentence in enumerate(sentence_slices(raw)):
                if pos <= diagnostic["start"] < pos + len(sentence):
                    diagnostic.update(sentence=i, sentence_text=sentence)
                    break
                pos += len(sentence)
    checks = {
        "source_anchored": True,
        "prose_format": not any(
            i in issues
            for i in (
                "INSUFFICIENT_OR_PADDED_PROSE",
                "EXCESSIVE_PARAGRAPH_LENGTH",
                "UNEXPECTED_FORMAT_OR_PLACEHOLDER",
            )
        ),
        "distinct_content": not any("REPETITION" in i or "REPEATED" in i for i in issues),
        "focus_evidence": "FOCUS_EVIDENCE_REQUIRED" not in issues,
        "scope_and_numeric_bindings": not issues,
    }
    return {
        "turn": turn,
        "focus": focus,
        "text": text,
        "author_source": raw,
        **(
            {
                "presentation": presentation,
                "attachments": attachments,
                "attachments_sha256": digest(attachments),
            }
            if presentation is not None
            else {}
        ),
        "response_sha256": raw_hash(raw),
        "replacements": replacements,
        "cards_sha256": digest(cards),
        "result": {
            "status": "repair" if issues else "observed",
            "issues": issues,
            "diagnostics": diagnostics,
            "used": sorted(used),
            "native_reviews": reviews,
            **(
                {"presentation": presentation, "attachments_sha256": digest(attachments)}
                if presentation is not None
                else {}
            ),
            "numeric_links": linked,
            **({"native_null_checks": null_checks} if modern else {}),
            **feedback(
                "repair" if issues else "accept",
                "、".join(issues) or "段落正文、資料範圍及所引欄位已核對。",
                **checks,
            ),
        },
    }


def assemble(scope, cards, folder):
    old_path = folder / "assembly.json"
    if old_path.exists():
        existing = read_sealed(old_path)["payload"]
        if "source_dictionary" not in existing:
            if existing["cards"] != cards or existing["source"] != scope["source"]:
                raise ValueError("ASSEMBLY_SOURCE_CHANGED")
            return existing
    authorship, chapters, issues = [], [], []
    card_sha = digest(cards)
    for chapter in sections():
        records = []
        for paragraph in chapter["paragraphs"]:
            turn = paragraph["turn"]
            record = accepted(folder, turn)
            if not record:
                issues.append(f"MISSING_ACCEPTED_PARAGRAPH:{turn}")
                continue
            if "response" not in record:
                record = {
                    **record,
                    "response": record["author_source"],
                    "author_source_sha256": record["response_sha256"],
                    "edit_applied": False,
                    "base_attempt": None,
                }
            if "presentation" in record:
                rendered, changes, attachments = v3.compose(
                    record["author_source"], record["presentation"], cards, scope
                )
                if (
                    attachments != record["attachments"]
                    or digest(attachments) != record["attachments_sha256"]
                ):
                    issues.append(f"PARAGRAPH_ATTACHMENTS_CHANGED:{turn}")
                    continue
            else:
                rendered, changes = render(record["author_source"], cards, scope)
            if (
                card_sha != record["cards_sha256"]
                or rendered != record["text"]
                or changes != record["replacements"]
                or raw_hash(record["author_source"]) != record["author_source_sha256"]
                or raw_hash(record["response"]) != record["response_sha256"]
            ):
                issues.append(f"PARAGRAPH_BINDING_CHANGED:{turn}")
                continue
            records.append(
                {
                    k: record[k]
                    for k in (
                        "turn",
                        "focus",
                        "attempt",
                        "author_source",
                        "response_sha256",
                        "response",
                        "author_source_sha256",
                        "edit_applied",
                        "base_attempt",
                        "text",
                        "replacements",
                    )
                }
            )
            if "presentation" in record:
                records[-1].update(
                    presentation=record["presentation"],
                    attachments=record["attachments"],
                    attachments_sha256=record["attachments_sha256"],
                    semantic_review=record.get("semantic_review"),
                )
        authorship.append({"title": chapter["title"], "paragraphs": records})
        chapters.append("## " + chapter["title"] + "\n\n" + "\n\n".join(r["text"] for r in records))
    result = {
        "protocol": scope["manuscript_protocol"],
        "status": "withheld" if issues else "independent_review_required",
        "issues": issues,
        "authorship": authorship,
        "cards": cards,
        "source": scope["source"],
        "source_dictionary": source_fields(scope),
        "question": scope["question"],
        "sections": sections(),
        **feedback(
            "withhold" if issues else "independent_review",
            "、".join(issues) or "全部段落已逐筆審核。研究設計、數值方向、意義及成稿仍需獨立評閱。",
            source_anchored=True,
            complete_observations=True,
            complete_paragraphs=not issues,
        ),
    }
    if not issues:
        result["manuscript"] = "# " + manuscript_title(scope) + "\n\n" + "\n\n".join(chapters)
        result["evidence_index"] = evidence_index(scope, cards)
        write_once(folder / "assembly.json", result)
    return result


def paragraph_v3(
    project,
    scope,
    cards,
    turn,
    attempt,
    op,
    response,
    previous,
    prior,
    semantic_review,
    path,
    prompt_path,
):
    fresh = attempt in (1, 4)
    focus, kind = TASKS[turn]
    if turn == 0:
        kind = "design"
    focus = focus.replace("文中連結 {{source}}", "選擇資料字典連結").replace(
        "另起一行放 {{group_table}} 供讀者核對", "選擇原生統計表供讀者核對"
    )
    if op == "draft":
        evidence = v3.editing_evidence(cards, actions_for(kind))
        dictionary = source_fields(scope)
        source = v3.source_scope(scope, cards)
        result = {
            "status": "draft",
            "turn": turn,
            "attempt": attempt,
            "mode": "author_json" if fresh else "sentence_edit",
            "focus": focus,
            "source_scope": source,
            "editor_evidence": evidence,
            "source_dictionary": dictionary,
        }
        target = None if fresh else v3.target_sentence(previous)
        result["response_schema"] = v3.presentation_schema(
            evidence, dictionary, kind == "table", None if fresh else target["sentence"]
        )
        role = (
            "交代資料和問題。",
            "說明誰納入分母、如何計算；勿預先作結果解讀。",
            "解讀已計算的差異和範圍。",
            "解讀品質與替代摘要。",
            "說明適用範圍及如何重現。",
        )[turn // 4]
        prompt = (
            "你是作者，用繁體中文自行完成一個研究段落。主問題："
            + manuscript_title(scope)
            + "\n本段唯一任務："
            + focus
            + " "
            + role
            + "\n來源："
            + json.dumps(source, ensure_ascii=False)
            + "\n本段可選的原生欄位："
            + json.dumps(evidence, ensure_ascii=False)
            + "\n可選字典："
            + json.dumps({k: v["quote"] for k, v in dictionary.items()}, ensure_ascii=False)
            + "\n使用 JSON。prose 寫約 150 至 220 個中文字，交代這個問題、資料支持的說明及其意義。"
            "寫自然句子，專注本段；欄名只是分組變數，真正的組別在 observed_group_levels。正文可完全不用卡號及數字。"
            "用 evidence_ids 選相應指標（最多三個），group_table 選是否附上原生數表，source_ids 選字典條文，link_source 選是否附來源連結。"
            "RDE 將資料與單位另行排版，不要把卡片目錄抄進正文。未知的代表性、設計、作者或療效不要臆測。"
        )
        if kind == "source":
            prompt += "本段必須選 link_source 或選一則字典原文。"
        if kind == "table":
            prompt += "本段必須選 group_table=true。"
        if actions_for(kind) and kind != "table":
            prompt += "選擇和本段分析相符的統計欄位。"
        if any(r["turn"] != turn for r in prior):
            prompt += "\n其他已完成段落任務：" + json.dumps(
                [r["focus"] for r in prior if r["turn"] != turn][-5:], ensure_ascii=False
            )
        if attempt == 4:
            result["revisit_context"] = {
                "previous_attempt": 3,
                "previous_response_sha256": previous["response_sha256"],
                "previous_author_source_sha256": previous["author_source_sha256"],
                "accepted_paragraphs": [
                    {
                        "turn": r["turn"],
                        "attempt": r["attempt"],
                        "author_source_sha256": r["author_source_sha256"],
                    }
                    for r in prior
                    if r["turn"] != turn
                ],
                "card_ids": list(evidence),
                "issues": previous["result"]["issues"],
            }
            prompt += "\n這是獨立重訪，從資料重新回答此項任務；先前仍欠核對：" + "、".join(
                previous["result"]["issues"]
            )
        if target:
            result.update(
                base_attempt=attempt - 1,
                base_sha256=previous["author_source_sha256"],
                sentences=sentence_slices(previous["author_source"]),
                repair_target=target,
                base_presentation=previous["presentation"],
            )
            prompt += (
                "\n現在只修指定的一句，不要另寫 prose。edits 清單只准一項，sentence 必須等於指定索引，text 是你改好的整句（刪句可空白）。"
                "其餘句子原封保留。重新明確指定本段四個證據選項。"
                "\n被退回的語句及修訂方向："
                + json.dumps(target, ensure_ascii=False)
                + "\n完整基稿："
                + json.dumps(result["sentences"], ensure_ascii=False)
                + "\n原選項："
                + json.dumps(result["base_presentation"], ensure_ascii=False)
            )
        result["prompt"] = prompt
        result.update(
            feedback(
                "ready",
                "本段的來源、可選欄位、角色與修訂範圍已核對。",
                approved_source=True,
                complete_observations=True,
                bounded_revision=True,
            )
        )
        return write_once(prompt_path, result)["payload"]
    if not prompt_path.exists():
        raise ValueError("PARAGRAPH_NOT_REQUESTED")
    draft = read_sealed(prompt_path)["payload"]
    issue = None
    try:
        author, presentation = v3.parse_author(response, draft)
    except (ValueError, TypeError) as ex:
        issue = (
            str(ex)
            if isinstance(ex, ValueError) and str(ex).startswith("INVALID_")
            else "INVALID_AUTHOR_ENVELOPE"
        )
        author, presentation = (
            ("", v3.empty_presentation())
            if fresh
            else (previous["author_source"], previous["presentation"])
        )
    if semantic_review is None and scope.get("semantic_review") == "required":
        raise ValueError("EXTERNAL_REVIEW_REQUIRED")
    extra = (
        v3.validate_external(semantic_review, scope["source"], response, author)
        if semantic_review is not None
        else []
    )
    if (
        previous
        and author == previous["author_source"]
        and presentation == previous["presentation"]
    ):
        old_target = v3.target_sentence(previous)
        extra.append(
            {
                "issue": "UNCHANGED_FAILED_CANDIDATE",
                "sentence": old_target["sentence"],
                "quote": old_target["previous_text"],
                "repair": "仍是上次退回的相同正文與附件選擇。" + old_target["repair"],
            }
        )
    if issue:
        extra.insert(
            0,
            {
                "issue": issue,
                "repair": "依本輪宣告的 JSON 欄位、指定句位及本段提供的 ID 重新作答。",
            },
        )
    record = check_paragraph(
        project,
        scope,
        cards,
        turn,
        author,
        [r for r in prior if r["turn"] != turn],
        presentation=presentation,
        extra_diagnostics=extra,
    )
    meta = {
        "response_sha256": raw_hash(response),
        "author_source_sha256": raw_hash(author),
        "edit_applied": not fresh and not issue,
        "base_attempt": None if fresh else attempt - 1,
    }
    record.update(attempt=attempt, response=response, semantic_review=semantic_review, **meta)
    record["result"].update(meta)
    record["result"]["checklist"].append({"check": "model_edits_valid", "passed": not issue})
    if semantic_review is not None:
        record["result"]["checklist"].append(
            {
                "check": "external_scientific_review",
                "passed": semantic_review["verdict"] == "accept",
            }
        )
        record["result"]["semantic_review"] = semantic_review
    write_once(path, record)
    return record["result"]


def run_paragraphs(
    project, entry, scope, anchor, folder, op, turn, attempt, response, semantic_review=None
):
    modern = scope["manuscript_protocol"] == "paragraph-v3"
    version = dataset_version(project, entry)
    if (
        version["source_status"] != "verified"
        or version["source"]["sha256"] != scope["source"]
        or version["version_sha256"] != anchor["version"]
    ):
        raise ValueError("DATASET_CHANGED")
    safe_grouping(entry.dataframe, scope)
    if op == "open":
        if (folder / "open.json").exists():
            return read_sealed(folder / "open.json")["payload"]
        result = {
            "status": "explore",
            "protocol": scope["manuscript_protocol"],
            **(
                {
                    "first_pass_attempts": 3,
                    "max_paragraph_attempts": 5,
                    "table_format": "grouped-summaries-v3",
                    "semantic_review": scope.get("semantic_review", "optional"),
                }
                if modern
                else {}
            ),
            "max_observation_turns": 18,
            "sections": sections(),
            **next_action(scope, list(PARAGRAPH_ACTIONS)),
            **feedback(
                "accept",
                "原始資料雜湊、核准範圍與資料版本一致，已建立六個可選原生探索動作。",
                source_anchored=True,
                grouping_checked=True,
                bounded_actions=True,
            ),
        }
        return write_once(folder / "open.json", result)["payload"]
    if op == "observe":
        return observe(project, entry, scope, anchor, folder, turn, response)
    if op not in ("draft", "review", "assemble"):
        raise ValueError("UNKNOWN_OPERATION")
    missing = remaining(folder)
    if missing:
        return {
            "status": "withheld",
            "remaining_actions": missing,
            "issues": ["MISSING_OBSERVATION:" + k for k in missing],
            **feedback(
                "withhold", "尚缺原生探索 " + "、".join(missing), complete_observations=False
            ),
        }
    cards = card_details(card_index(project, folder, include_null=modern), scope)
    if op == "assemble":
        return assemble(scope, cards, folder)
    if turn not in range(len(TASKS)) or attempt not in range(1, 6 if modern else 4):
        raise ValueError("INVALID_PARAGRAPH")
    path = paragraph_path(folder, turn, attempt)
    prompt_path = folder / f"draft-{turn:02}-{attempt}.json"
    if op == "draft" and prompt_path.exists():
        return read_sealed(prompt_path)["payload"]
    if op == "review" and path.exists():
        record = read_sealed(path)["payload"]
        if (
            record.get("response", record["author_source"]) != response
            or record.get("semantic_review") != semantic_review
        ):
            raise ValueError("PARAGRAPH_REPLAY_CHANGED")
        return record["result"]
    prior = [accepted(folder, i) for i in range(len(TASKS) if attempt >= 4 else turn)]
    if any(not r and not paragraph_path(folder, i, 3).exists() for i, r in enumerate(prior)):
        raise ValueError("EARLIER_PARAGRAPH_NOT_ACCEPTED")
    prior = [r for r in prior if r]
    previous = None
    if attempt > 1:
        previous = read_sealed(paragraph_path(folder, turn, attempt - 1))["payload"]
        if not previous["result"]["issues"]:
            raise ValueError("PARAGRAPH_ALREADY_ACCEPTED")
    if modern:
        return paragraph_v3(
            project,
            scope,
            cards,
            turn,
            attempt,
            op,
            response,
            previous,
            prior,
            semantic_review,
            path,
            prompt_path,
        )
    if op == "draft":
        result = {
            "status": "draft",
            "turn": turn,
            "attempt": attempt,
            "prompt": assignments(scope, turn, cards, prior, previous),
            **feedback(
                "ready",
                "本段任務、可用資料及先前審核回饋已連結。",
                complete_observations=True,
                prior_paragraphs_reviewed=True,
            ),
        }
        if previous:
            sentences = sentence_slices(previous["author_source"])
            result.update(
                base_attempt=attempt - 1,
                base_sha256=raw_hash(previous["author_source"]),
                sentences=sentences,
                response_schema=edit_schema(len(sentences)),
            )
        return write_once(prompt_path, result)["payload"]
    if not prompt_path.exists():
        raise ValueError("PARAGRAPH_NOT_REQUESTED")
    author_source = response
    invalid = False
    if previous:
        try:
            author_source = apply_edits(sentence_slices(previous["author_source"]), response)
        except (ValueError, TypeError):
            invalid = True
            author_source = previous["author_source"]
    record = check_paragraph(project, scope, cards, turn, author_source, prior)
    meta = {
        "response_sha256": raw_hash(response),
        "author_source_sha256": raw_hash(author_source),
        "edit_applied": bool(previous) and not invalid,
        "base_attempt": attempt - 1 if previous else None,
    }
    record.update(attempt=attempt, response=response, **meta)
    record["result"].update(meta)
    if invalid:
        result = record["result"]
        result.update(status="repair", issues=["INVALID_SENTENCE_EDITS", *result["issues"]])
        result["diagnostics"].insert(
            0,
            {
                "issue": "INVALID_SENTENCE_EDITS",
                "repair": "只回傳 edits，索引從零且不重複，text 為完整修正句；刪句可給空字串。",
            },
        )
        result["feedback"] = {"disposition": "repair", "reason": "INVALID_SENTENCE_EDITS"}
    record["result"]["checklist"].append({"check": "model_edits_valid", "passed": not invalid})
    write_once(path, record)
    return record["result"]
