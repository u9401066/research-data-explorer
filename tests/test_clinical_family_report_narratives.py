"""New clinical families must never inherit an unrelated survival narrative."""

import pytest

from rde.interface.mcp.tools.report_tools import (
    _formal_key_findings,
    _formal_conclusions,
    _build_interpretation_discussion,
)


@pytest.mark.parametrize("family", ["noninferiority", "imputation", "stratified"])
def test_formal_clinical_narratives_keep_family_specific_limits(family):
    results = {
        "clinical_studies": [
            {"family": family, "noninferiority_decision": "noninferiority_not_demonstrated"}
        ]
    }
    sections = [
        _formal_key_findings(results),
        _formal_conclusions(results, None, pubmed_context=""),
        _build_interpretation_discussion(
            None, None, results=results, readiness=None, schema=None, table_one=None
        ),
    ]
    for section in sections:
        assert not any(
            word in section for word in ["Cox", "生存曲線", "累積發生率", "## 臨床事件結果解讀"]
        )
        if family == "noninferiority":
            assert "單側" in section and "margin" in section
            assert "共同完整個案" in section or "完整個案" in section
        elif family == "imputation":
            assert "MAR" in section and ("收斂" in section or "未由軟體驗證" in section)
            assert "樣本數" in section or "不乘以 m" in section
        else:
            assert "OR" in section and "因果" in section
            assert "同質" in section or "共同效果假設" in section
    if family == "noninferiority":
        assert "保存數值未能證明非劣性" in sections[0]
        assert "支持預先指定界值下的非劣性" not in "".join(sections)


@pytest.mark.parametrize("decision", ["boundary_not_demonstrated", None])
def test_missing_or_boundary_ni_summary_does_not_invent_success(decision):
    text = _formal_key_findings(
        {"clinical_studies": [{"family": "noninferiority", "noninferiority_decision": decision}]}
    )
    assert "保存數值支持" not in text
    assert "不宣稱非劣性" in text or "須核對" in text
