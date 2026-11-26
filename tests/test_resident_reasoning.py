from rde.interface.mcp.resident_citations import numeric_links, render, source_fields
from rde.interface.mcp.resident_paragraphs import scope_numbers
from rde.interface.mcp.resident_reasoning import action_reason, sentence_slices, apply_edits
import json
import pytest


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
