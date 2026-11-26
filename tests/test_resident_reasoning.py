import hashlib
import json

import pytest

from rde.interface.mcp.resident_citations import numeric_links, render, source_fields
from rde.interface.mcp.resident_paragraphs import DESCRIPTIONS, scientific_issues, scope_numbers
from rde.interface.mcp.resident_protocol_v3 import (
    capabilities,
    choice_schema,
    intent_issues,
    parse_author,
    presentation_schema,
    validate_external,
)
from rde.interface.mcp.resident_reasoning import action_reason, sentence_slices, apply_edits


@pytest.mark.parametrize(
    "action,reason,issue",
    [
        ("distribution", "以範圍檢驗分布是否符合常態。", "ACTION_UNSUPPORTED_NORMALITY"),
        ("group_contrasts", "可用這個差值判斷具有臨床重要性。", "ACTION_UNSUPPORTED_INFERENCE"),
        (
            "group_completeness",
            "計算有效百分比以推估母體代表性。",
            "ACTION_UNSUPPORTED_REPRESENTATIVENESS",
        ),
        ("group_estimates", "本步提供樣本標準差。", "ACTION_FIELD_NOT_PROVIDED"),
        ("group_spread", "此工具回傳全距端點。", "ACTION_FIELD_NOT_PROVIDED"),
        ("group_estimates", "文中確認總樣本數（rows=7）。", "GLOBAL_DENOMINATOR_NOT_VERIFIED"),
    ],
)
def test_descriptive_action_rejects_unavailable_evidence(action, reason, issue):
    result = action_reason(action, reason, {"distribution": {"groups": [{"rows": 7}, {"rows": 7}]}})
    assert issue in {d["issue"] for d in result} and all(d["repair"] for d in result)


@pytest.mark.parametrize(
    "reason",
    [
        "尚未檢驗常態性，本步先計算各組平均值。",
        "若要判斷顯著性需另作檢定，此處先計算各組平均數。",
        "此工具不能證明臨床重要性或代表性，後續另需其他檢定。",
        "先前的中位數已有證據，本次只比較平均數。",
    ],
)
def test_separate_future_tests_are_valid(reason):
    assert not action_reason("group_estimates", reason, {})


def test_difference_in_means_and_medians_is_a_supported_contrast():
    assert not action_reason(
        "group_contrasts", "此工具計算比較組減參照組的平均值與中位數差距。", {}
    )


def test_verified_author_written_scalar_requires_value_unit_group_and_statistic():
    scope = {
        "source_note": "原始字典 https://example.org ；深度變項每格 2.5 公分。",
        "measure": "depth",
        "group": "arm",
        "unit": "公分",
    }
    cards = {
        "2.4": {
            "value": 2.456,
            "statistic": "mean",
            "group": "甲",
            "unit": "公分",
            "pointer": "/groups/0/mean",
            "label": "group_estimates/groups/甲/mean",
        },
        "1.1": {
            "value": 12,
            "statistic": "rows",
            "unit": "筆",
            "pointer": "/rows",
            "label": "data_quality/rows",
        },
    }
    for raw in ["甲組平均值為 2.46 公分[R2.4]。", "甲組平均 {{R2.4}} 約 2.46 公分。"]:
        issues, links = numeric_links(raw, scope, cards, scope_numbers(raw, scope, cards))
        assert not issues and links[0]["reference"] == "R2.4"
    for raw in [
        "甲組平均值為 2.6 公分[R2.4]。",
        "甲組平均值為 2.46 秒[R2.4]。",
        "乙組平均值為 2.46 公分[R2.4]。",
        "甲組中位數為 2.46 公分[R2.4]。",
        "共有12筆完整記錄 {{R1.1}}。",
        "甲組平均值為 2.46 公分。",
    ]:
        issues, links = numeric_links(raw, scope, cards, scope_numbers(raw, scope, cards))
        assert issues and not links
    public = source_fields(scope)["S1"]
    assert (
        scope["source_note"][public["start"] : public["end"]]
        == public["quote"]
        == "深度變項每格 2.5 公分"
    )
    raw = "本次核對{{S1}}。"
    text, changes = render(raw, cards, scope)
    assert changes[0]["rendered"] in text and public["quote"] in text and public["url"] in text
    assert not scope_numbers(raw, scope, cards) and scope_numbers(
        "觀察平均 2.5 公分。", scope, cards
    )


def test_author_edits_preserve_untouched_utf8_and_fail_on_invalid_indices():
    raw = "  首句 🐳。\r\n次句？末句 "
    tokens = sentence_slices(raw)
    assert "".join(tokens) == raw
    assert apply_edits(
        tokens, json.dumps({"edits": [{"sentence": 0, "text": "  改句。"}]})
    ) == raw.replace("  首句 🐳。", "  改句。")
    with pytest.raises(ValueError):
        apply_edits(tokens, '{"edits":[{"sentence":0,"text":"X"},{"sentence":0,"text":"Y"}]}')


SCOPE = {
    "source_note": "公開來源。",
    "population": "登錄資料。",
    "group": "batch",
    "measure": "intensity",
    "unit": "cm",
    "manuscript_protocol": "paragraph-v3",
}


@pytest.mark.parametrize(
    "sentence,issue",
    [
        ("利用組內平均差評估干預對初始狀態的影響幅度。", "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE"),
        ("可從基線量測判定處置對基線狀態的效應。", "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE"),
        ("既有資料無法判定干預對基線的影響。", None),
        ("若要估計暴露對病程的作用，還需新的追蹤資料。", None),
        ("計算有效列數，排除因樣本量不足導致的誤解。", None),
        ("分組方式會影響可用筆數與讀者對基線的理解。", None),
        (
            "無法判定抽樣方式，但可用完整率評估樣本代表可能性。",
            "ACTION_UNSUPPORTED_REPRESENTATIVENESS",
        ),
        ("要評估樣本代表性仍需要另外的納入資料。", None),
        ("四分位距為 Q3−Q2。", "STATISTIC_DEFINITION_MISMATCH"),
        ("四分位距為 Q3−Q1。", None),
        ("計算完整程度以推估母體代表性。", "ACTION_UNSUPPORTED_REPRESENTATIVENESS"),
        ("已有的分组均值可估计干预对基线的影响。", "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE"),
    ],
)
def test_scientific_actor_target_polarity(sentence, issue):
    codes = [d["issue"] for d in scientific_issues(sentence, SCOPE)]
    assert (issue in codes) if issue else not codes


@pytest.mark.parametrize(
    "text,number",
    [
        ("A組中位數為四十點一一三 cm[R3.5]。", "40.113"),
        ("A組中位數為負壹拾貳點伍 cm[R3.5]。", "-12.5"),
        ("A組中位數為＋１２．５ cm[R3.5]。", "12.5"),
        ("A組中位數為－１２．５ cm[R3.5]。", "-12.5"),
        ("第一組依一眼一人的核准資料記錄。", None),
        ("兩組比較均可用第一四分位數描述。", None),
    ],
)
def test_authored_measurements_bind_numbers_without_converting_classifiers(text, number):
    nums = scope_numbers(text, SCOPE, {})
    assert [n["numeric"] for n in nums] == ([number] if number else [])
    if not number:
        return
    card = {
        "3.5": {
            "label": "distribution/groups/A/median",
            "statistic": "median",
            "value": float(number),
            "group": "A",
            "unit": "cm",
            "pointer": "/native",
        }
    }
    problems, links = numeric_links(text, SCOPE, card, nums)
    assert not problems and links[0]["numeric"] == number
    card["3.5"]["value"] += 2
    assert (
        numeric_links(text, SCOPE, card, nums)[0][0]["issue"] == "NUMERIC_CITATION_CONTEXT_MISMATCH"
    )
    clean = text.replace("[R3.5]", "")
    assert (
        numeric_links(clean, SCOPE, card, scope_numbers(clean, SCOPE, card))[0][0]["issue"]
        == "UNBOUND_AUTHOR_NUMBER"
    )


def test_previous_card_use_is_an_explicit_auditable_decision():
    contracts = capabilities(SCOPE, DESCRIPTIONS)
    prior = {"R1.1": {"field": "data_quality/missing_measure", "value": 2}}
    props = choice_schema(["group_completeness"], contracts, prior)["required"]
    assert {"evidence_use", "unresolved_question", "prior_refs"} <= set(props)
    choice = {
        "action": "group_completeness",
        "purpose": "audit_measurement_coverage",
        "intended_fields": ["group_completeness.missing_percent"],
        "reason": "全檔可看到缺值，故需定位哪一組涵蓋較少。",
        "unresolved_question": "各組缺測率是否有不同？",
        "prior_refs": [],
        "evidence_use": "follow_up",
    }
    assert intent_issues(choice, contracts, prior)[0]["issue"] == "FOLLOW_UP_RELATION_REQUIRED"
    assert not intent_issues(dict(choice, prior_refs=["R1.1"]), contracts, prior)
    assert not intent_issues(dict(choice, evidence_use="independent_check"), contracts, prior)
    assert (
        intent_issues(dict(choice, prior_refs=["R7.1"]), contracts, prior)[0]["issue"]
        == "PRIOR_EVIDENCE_NOT_OBSERVED"
    )
    assert (
        intent_issues(dict(choice, unresolved_question="？"), contracts, prior)[0]["issue"]
        == "UNRESOLVED_QUESTION_REQUIRED"
    )


def test_sentence_repairs_constrained_on_decode_and_on_review():
    schema = presentation_schema({}, {}, False, 1)
    edit = schema["properties"]["edits"]
    assert edit["maxItems"] == edit["minItems"] == 1
    assert edit["items"]["properties"]["text"] == {"type": "string", "maxLength": 120}
    fresh = presentation_schema({}, {}, False)["properties"]["prose"]
    assert fresh == {"type": "string", "minLength": 120, "maxLength": 230}
    opts = {"evidence_ids": [], "source_ids": [], "link_source": False, "group_table": False}
    draft = {
        "response_schema": schema,
        "editorial_basis_version": 1,
        "source_dictionary": {},
        "editor_evidence": {},
        "repair_target": {"sentence": 1},
        "sentences": ["甲。", "乙。", "丙。"],
    }
    for text in ("重寫。又寫一次。", "甲" * 121, "一行\n另一行"):
        with pytest.raises(ValueError, match="INVALID_TARGETED_EDIT"):
            parse_author(json.dumps(dict(opts, edits=[{"sentence": 1, "text": text}])), draft)
    for text in ("", "重寫這句。", "此處的 {{R1.1}} 包含小數點。"):
        assert (
            parse_author(json.dumps(dict(opts, edits=[{"sentence": 1, "text": text}])), draft)[0]
            == "甲。" + text + "丙。"
        )


def test_editor_claim_requires_exact_substring_and_available_basis():
    def h(text):
        return hashlib.sha256(text.encode()).hexdigest()

    author = "分組名稱不是觀測單位。"
    source = "a" * 64
    draft = {"editor_evidence": {"R2.4": {}}, "source_scope": {"group_column": "x"}}
    for extra, code in [
        ({}, None),
        ({"claim": "分組名稱", "basis": "scope.group_column"}, None),
        ({"claim": "分組名稱", "basis": "R2.4"}, None),
        ({"claim": "自行新造詞", "basis": "R2.4"}, "EXTERNAL_CLAIM_NOT_IN_SENTENCE"),
        ({"claim": "分組名稱", "basis": "R99.1"}, "EXTERNAL_BASIS_OUTSIDE_DRAFT"),
    ]:
        finding = {"sentence": 0, "issue": "identity", "reason": "核對欄位名稱。", **extra}
        raw = json.dumps({"findings": [finding]}, ensure_ascii=False)
        envelope = {
            "verdict": "repair",
            "reviewer": "referee",
            "source_sha256": source,
            "response_sha256": h("raw"),
            "author_source_sha256": h(author),
            "reviewer_response_sha256": h(raw),
            "reviewer_response": raw,
            "diagnostics": [{"issue": "identity", "quote": author, "repair": "核對欄位名稱。"}],
        }
        if code:
            with pytest.raises(ValueError, match=code):
                validate_external(envelope, source, "raw", author, draft=draft)
        else:
            result = validate_external(envelope, source, "raw", author, draft=draft)[0]
            assert {k: result[k] for k in extra} == extra
