import pandas as pd
import pytest

from rde.interface.mcp.resident import observations, scope_issues, section_review


def test_group_denominators_with_missing_group_and_missing_measure():
    frame = pd.DataFrame({"arm": ["B", "A", "A", None], "reading": [2, None, 4, 100]})
    scope = {"group": "arm", "measure": "reading"}
    assert observations(frame, scope, "data_quality") == {
        "rows": 4,
        "missing_group": 1,
        "missing_measure": 1,
        "complete": 2,
    }
    grouped = observations(frame, scope, "group_estimates")["groups"]
    assert grouped == [
        {"group": "A", "observed": 1, "rows": 2, "mean": 4},
        {"group": "B", "observed": 1, "rows": 1, "mean": 2},
    ]
    with pytest.raises(ValueError, match="NON_NUMERIC_MEASURE"):
        observations(pd.DataFrame({"arm": [1], "reading": ["invalid"]}), scope, "group_estimates")


def test_results_cannot_advance_with_unbound_numeric_card():
    cards = {"2.1": {"label": "group_estimates/arms/A/mean"}}
    text = "正文" * 200 + " [R2.1]"
    result = section_review("project", text, cards, 2)
    assert result["issues"] == ["UNBOUND_REFERENCE", "MISSING_GROUP_ESTIMATE_OR_DENOMINATOR"]


def test_undocumented_design_is_reviewed_at_the_turn_that_introduced_it():
    scope = {"source_note": "來源註明為觀察性調查。", "population": "門診樣本"}
    assert scope_issues("兩組受試者隨機分派。", scope) == ["UNDOCUMENTED_STUDY_DESIGN"]
    assert not scope_issues("資料未說明是否隨機分派。", scope)
    assert not scope_issues("兩組受試者隨機分派。", dict(scope, source_note="以隨機分派進行。"))
