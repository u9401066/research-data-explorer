import json
import pytest
from rde.interface.mcp.resident import scope_issues
from rde.interface.mcp.resident_bindings import edited_blocks, expand


def test_resident_selects_only_native_table_cells_and_source():
    cards = {}
    for i, (field, value) in enumerate(
        [("group", "G|1"), ("observed", 2), ("rows", 3), ("mean", 4.25)], 1
    ):
        cards[f"2.{i}"] = {
            "pointer": f"/payload/observation/groups/0/{field}",
            "label": f"group_estimates/groups/G|1/{field}",
            "value": value,
        }
    scope = {
        "unit": "mg",
        "group": "arm",
        "source_note": "https://example.org/dictionary 。official",
    }
    text = "Model-owned intro.\n\n{{group_table}}\n\n{{source}}"
    rendered, bindings = expand(text, cards, scope)
    assert "2[R2.2] | 4.25[R2.4]" in rendered and "<https://example.org/dictionary>" in rendered
    assert "G\\|1" in rendered and bindings[0]["token"] == "{{group_table}}"
    assert expand("Model-owned prose.", cards, scope) == ("Model-owned prose.", [])
    assert expand("{{R9.9}}", cards, scope)[0] == "{{R9.9}}"


def test_local_edits_preserve_all_other_model_blocks():
    original = "Alpha\n\nBeta\n\nGamma"
    patch = json.dumps({"edits": [{"block": 1, "text": "New authored text"}]})
    assert edited_blocks(original, patch) == "Alpha\n\nNew authored text\n\nGamma"
    with pytest.raises(ValueError):
        edited_blocks(original, '{"edits":[{"block":-1,"text":"untargeted"}]}')
    assert not scope_issues(
        "組別依觀測分類，並非隨機分派。", {"source_note": "觀察", "population": "樣本"}
    )


def test_random_treatment_allocation_and_random_sampling_remain_distinct():
    scope = {"source_note": "一項隨機對照試驗", "population": "門診樣本"}
    assert not scope_issues("受試者隨機分派到組別。", scope)
    assert scope_issues("受試者經隨機抽樣。", scope) == ["UNDOCUMENTED_STUDY_DESIGN"]
    assert scope_issues("進行雙盲。", scope) == ["UNDOCUMENTED_STUDY_DESIGN"]
