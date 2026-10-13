"""Regression from the real UCI 519 agent smoke: optional Table 1 was shown ❌."""
import pytest

from rde.interface.mcp.tools.audit_tools import _publication_bundle_check


@pytest.mark.parametrize("figures", [1, 4, 8])
def test_method_scope_does_not_penalize_or_describe_optional_table_as_missing(figures):
    result = _publication_bundle_check(dict(
        table_one_required=False, required_descriptive_figures=0,
        descriptive_figures=0, analytical_figures=figures,
        required_analytical_figures=figures, minimum_publication_bundle_met=True,
    ), True)
    assert result["passed"] is True
    assert result["score"] == result["max"] == 5
    assert "table_one=not_required_by_locked_scope" in result["details"]
    assert "crude=not_required_by_locked_scope" in result["details"]
    assert "missing" not in result["details"]
    assert "not publication approval" in result["details"]


def test_missing_required_evidence_still_fails_and_legacy_eda_defaults_are_preserved():
    legacy = _publication_bundle_check(dict(
        analytical_figures=6, descriptive_figures=3, minimum_publication_bundle_met=False,
    ), True)
    assert legacy["passed"] is False
    assert legacy["score"] == 8 and legacy["max"] == 10
    assert "table_one=missing" in legacy["details"]
    clinical = _publication_bundle_check(dict(
        table_one_required=False, required_descriptive_figures=0,
        analytical_figures=7, required_analytical_figures=8,
        minimum_publication_bundle_met=False,
    ), True)
    assert clinical["passed"] is False and clinical["score"] < clinical["max"]
    assert "detailed=7/8" in clinical["details"]


def test_descriptive_scope_never_claims_publication_readiness():
    result = _publication_bundle_check({}, False)
    assert result["score"] == result["max"] == 0
    assert result["applicable"] is False
    assert "no publication readiness claim" in result["details"]
