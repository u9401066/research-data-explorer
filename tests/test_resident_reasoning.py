import hashlib
import json

import pytest

from rde.interface.mcp.resident_citations import numeric_links, render, source_fields
from rde.interface.mcp.resident_dictionary import dictionary_claims
from rde.interface.mcp.resident_relations import study_relations
from rde.interface.mcp.resident_paragraphs import (
    DESCRIPTIONS,
    rationale_issues,
    claim_context,
    scientific_issues,
    scope_numbers,
)
from rde.interface.mcp.resident_protocol_v3 import (
    capabilities,
    choice_schema,
    intent_issues,
    parse_author,
    presentation_schema,
    validate_external,
    verify_sentence_reviews,
    target_sentence,
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


def test_signed_measure_requires_named_direction_and_count_keeps_native_unit():
    cards = {
        "6.2": {
            "group": "B",
            "reference_group": "A",
            "value": 2.5,
            "unit": "cm",
            "statistic": "mean_difference",
            "label": "group_contrasts/comparisons/B/mean_difference",
            "pointer": "/comparison",
        },
        "2.2": {
            "group": "A",
            "value": 7,
            "unit": "筆",
            "statistic": "rows",
            "label": "group_estimates/groups/A/rows",
            "pointer": "/rows",
        },
    }
    for phrase, accepted in (
        ("B組減A組", True),
        ("以A組為參照的B組", True),
        ("A組減B組", False),
        ("A組與B組", False),
    ):
        inline = phrase + "的平均數差為{{R6.2}}。"
        typed = phrase + "的平均數差為二點五 cm[R6.2]。"
        assert (not claim_context(inline, cards, strict_contrasts=True)) == accepted
        assert (
            not numeric_links(typed, SCOPE, cards, scope_numbers(typed, SCOPE, cards))[0]
        ) == accepted

    for unit, accepted in (("筆", True), ("列", True), ("人", False), ("眼", False)):
        typed = "A組總筆數為七" + unit + "[R2.2]。"
        assert (
            not numeric_links(typed, SCOPE, cards, scope_numbers(typed, SCOPE, cards))[0]
        ) == accepted


def test_dictionary_codes_resolve_to_exact_approved_column_label_and_offsets():
    note = "來源 https://example.org/dictionary 。diet：0=室內、1=室外。device: X=原件、Y=複本。"
    scope = dict(SCOPE, group="diet", measure="device", source_note=note)
    author = "diet 欄：0 為室內、1 代表室外。device 欄：Y 表示複本。"
    checks, issues = dictionary_claims(author, scope)
    assert not issues and [(r["column"], r["code"], r["label"]) for r in checks] == [
        ("diet", "0", "室內"),
        ("diet", "1", "室外"),
        ("device", "Y", "複本"),
    ]
    assert not scope_numbers(author, scope, {}, dictionary_spans=checks)
    for r in checks:
        assert author[r["start"] : r["end"]] == r["quote"]
        assert note[r["dictionary_start"] : r["dictionary_end"]] == r["dictionary_quote"]
        assert r["source_url"] == "https://example.org/dictionary"
        assert r["dictionary_sha256"] == hashlib.sha256(note.encode()).hexdigest()
    for authored, issue in [
        ("diet：0 為室外、1 為室內。", "DICTIONARY_CODE_MISMATCH"),
        ("diet：2 表示室內。", "DICTIONARY_CODE_UNVERIFIED"),
        ("diet：X 代表原件。", "DICTIONARY_CODE_UNVERIFIED"),
        ("device：Y 表示原件。", "DICTIONARY_CODE_MISMATCH"),
    ]:
        checked, errors = dictionary_claims(authored, scope)
        assert not checked and all(e["issue"] == issue for e in errors) and errors
    assert dictionary_claims(author, dict(scope, source_note=note + " diet：0=室外。"))[1]
    assert dictionary_claims(
        author, dict(scope, source_note=note + " https://example.org/another")
    )[1]


def test_authored_value_without_inline_tag_requires_unique_selected_indicator():
    c = {
        "group": "A",
        "statistic": "median",
        "value": 3.504,
        "unit": "cm",
        "label": "distribution/groups/A/median",
        "pointer": "/a",
    }
    cards = {"3.4": c, "3.8": dict(c, group="B", pointer="/b"), "3.10": dict(c, pointer="/alias")}
    raw = "A組中位數為3.50 cm。"

    def check(text, ids):
        return numeric_links(
            text, SCOPE, cards, scope_numbers(text, SCOPE, cards), selected_ids=ids
        )

    issues, links = check(raw, ["R3.4", "R3.8"])
    assert (
        not issues
        and links[0]["reference"] == "R3.4"
        and links[0]["match_method"] == "selected_evidence"
    )
    assert raw[links[0]["start"] : links[0]["end"]] == "3.50"
    for candidate, ids in [
        (raw, []),
        (raw, ["R3.4", "R3.10"]),
        (raw, ["R3.8"]),
        (raw.replace("3.50", "3.51"), ["R3.4"]),
        (raw.replace("cm", "m"), ["R3.4"]),
        (raw.replace("中位數", "平均數"), ["R3.4"]),
        (raw.replace("A組", ""), ["R3.4"]),
    ]:
        assert check(candidate, ids)[0]


def test_sentence_reviews_cannot_skip_reorder_hide_veto_or_substitute_raw():
    def record(index, findings):
        raw = json.dumps({"findings": findings})
        return {
            "sentence": index,
            "reviewer_response": raw,
            "reviewer_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        }

    clean = [record(i, []) for i in (0, 2, 3)]
    veto = record(2, [{"sentence": 2, "issue": "scope", "reason": "重新核對。"}])

    def check(records, verdict="accept", final=None):
        verify_sentence_reviews(
            {
                "verdict": verdict,
                "sentence_reviews": records,
                "reviewer_response": final or records[-1]["reviewer_response"],
            },
            [0, 2, 3],
        )

    check(clean)
    check([clean[0], veto], "repair")
    for records, verdict, final in [
        (clean[:2], "accept", None),
        ([clean[0], clean[2]], "accept", None),
        ([clean[0], veto, clean[2]], "repair", None),
        ([clean[0], dict(veto, reviewer_response_sha256="a" * 64)], "repair", None),
        ([clean[0], veto], "repair", clean[0]["reviewer_response"]),
        ([clean[0], record(2, [{"sentence": 3}])], "repair", None),
    ]:
        with pytest.raises(ValueError, match="EXTERNAL_SENTENCE"):
            check(records, verdict, final)


@pytest.mark.parametrize(
    "field,text,refs,issue",
    [
        (
            "unresolved_question",
            "這個描述性查詢能否判定組間差異具有統計顯著性？",
            [],
            "ACTION_UNSUPPORTED_INFERENCE",
        ),
        ("unresolved_question", "本次無法檢驗顯著性，若要作推論還需新的分析。", [], None),
        ("reason", "根據 R6.1 的觀察，需要查驗分布。", [], "UNDECLARED_PRIOR_REFERENCE"),
        (
            "unresolved_question",
            "曾在 R91.2 發現差異，該如何查驗？",
            [],
            "PRIOR_EVIDENCE_NOT_OBSERVED",
        ),
        ("reason", "先前指標顯示中位數差為負。", [], "PRIOR_CONTRAST_DIRECTION_UNVERIFIED"),
        ("reason", "先前指標顯示中位數差為負。", ["R6.1"], "PRIOR_CONTRAST_DIRECTION_UNVERIFIED"),
        ("reason", "先前指標顯示中位數差為正。", ["R6.1"], None),
        ("reason", "若中位數差為負，則需再查驗端點。", [], None),
        ("unresolved_question", "中位數差是否為負？", [], None),
        ("reason", "中位數差為正表示比較組中位數較高。", [], None),
        ("reason", "B組的中位數低於A組。", ["R6.1"], "PRIOR_CONTRAST_DIRECTION_UNVERIFIED"),
        ("reason", "B組的中位數高於A組。", ["R6.1"], None),
        ("reason", "B組平均數比A組高。", [], "PRIOR_CONTRAST_DIRECTION_UNVERIFIED"),
    ],
)
def test_all_action_research_text_is_bound_to_the_claimed_prior_observation(
    field, text, refs, issue
):
    previous = {
        "R6.1": {"statistic": "median_difference", "group": "B", "reference_group": "A", "value": 2}
    }
    choice = {"action": "group_contrasts", field: text, "prior_refs": refs}
    issues = rationale_issues(choice, SCOPE, {}, previous)
    assert all(i["rationale_field"] == field for i in issues)
    assert (issue in {i["issue"] for i in issues}) if issue else not issues


def test_arithmetic_relations_verify_touch_overlap_gaps_and_missing_limits():
    cards = {}
    values = {
        "A": (1, 6, 2, 5, 4, 4),
        "B": (5, 9, 6, 8, 6, 7),
        "C": (6, 8, 6, 7, 7, 6),
        "D": (None, None, None, None, None, None),
    }
    for name, numbers in values.items():
        for field, value in zip(("min", "max", "q1", "q3", "mean", "median"), numbers, strict=True):
            cards[str(len(cards) + 1)] = {
                "group": name,
                "statistic": field,
                "value": value,
                "unit": "cm",
            }
        if name != "A":
            for field, value in zip(
                ("mean_difference", "median_difference"), numbers[-2:], strict=True
            ):
                cards[str(len(cards) + 1)] = {
                    "group": name,
                    "reference_group": "A",
                    "statistic": field,
                    "value": value - 4 if value is not None else None,
                    "unit": "cm",
                }
    summaries = study_relations(cards, "table")["comparisons"]
    assert summaries[0]["mean_difference"]["sign"] == "positive"
    assert (
        summaries[0]["range"]["intersection"] == [5, 6]
        and summaries[0]["range"]["status"] == "overlap"
    )
    assert (
        summaries[0]["quartiles"]["status"] == "disjoint"
        and summaries[0]["quartiles"]["intersection"] is None
    )
    assert summaries[1]["range"]["status"] == "touching" and summaries[1]["range"][
        "intersection"
    ] == [6, 6]
    assert (
        summaries[2]["range"]["status"]
        == summaries[2]["median_difference"]["status"]
        == "unavailable"
    )
    for relation in ("mean_difference", "range", "quartiles"):
        for card in summaries[0][relation]["inputs"].values():
            assert cards[card["id"][1:]]["value"] == card["value"] and card["unit"] == "cm"
    assert study_relations(cards, "design") is None


def test_number_repair_offers_options_and_locates_author_value_without_editing_it():
    author = "先說明研究範圍。A組中位數為4.15 cm。"
    start = author.index("4.15")
    diagnostic = {
        "issue": "UNBOUND_AUTHOR_NUMBER",
        "numeric": "4.15",
        "start": start,
        "end": start + 4,
        "sentence": 1,
    }
    previous = {"author_source": author, "result": {"diagnostics": [diagnostic]}}
    evidence = {
        "R3.4": {
            "group": "A",
            "statistic": "median",
            "statistic_title": "中位數",
            "value": 4.1,
            "unit": "cm",
        },
        "R3.8": {
            "group": "B",
            "statistic": "median",
            "statistic_title": "中位數",
            "value": 4.15,
            "unit": "cm",
        },
    }
    repair = target_sentence(previous, evidence=evidence)
    assert repair["author_span"] == {"start": start, "end": start + 4, "quote": "4.15"}
    assert repair["previous_text"] == sentence_slices(author)[1]
    assert [c["id"] for c in repair["evidence_candidates"]] == ["R3.4", "R3.8"]
