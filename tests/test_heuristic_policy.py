from __future__ import annotations

import pandas as pd

from rde.domain.models.report import REQUIRED_SECTIONS
from rde.domain.policies import DEFAULT_HEURISTIC_POLICY
from rde.domain.policies.soft_constraints import SoftConstraints
from rde.domain.services.collinearity_checker import check_collinearity
from rde.domain.services.variable_classifier import PII_PATTERNS, VariableClassifier


def test_report_required_sections_are_driven_by_policy() -> None:
    assert REQUIRED_SECTIONS == list(DEFAULT_HEURISTIC_POLICY.reporting.required_sections)


def test_variable_classifier_uses_policy_backed_pii_patterns() -> None:
    classifier = VariableClassifier()

    assert tuple(PII_PATTERNS) == DEFAULT_HEURISTIC_POLICY.classification.pii_patterns
    assert classifier._check_pii("patient_name") is True


def test_collinearity_checker_uses_policy_threshold_by_default() -> None:
    df = pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 5],
            "y": [1.0, 2.0, 3.1, 4.0, 5.0],
            "z": [5, 1, 4, 2, 3],
        }
    )

    report = check_collinearity(df)

    assert report.threshold == DEFAULT_HEURISTIC_POLICY.analysis.collinearity_correlation_threshold
    assert report.has_collinearity is True


def test_s007_message_matches_pairwise_correlation_screening_policy() -> None:
    result = SoftConstraints.s007_collinearity_warning(0.91)

    assert result.passed is False
    assert "Pairwise correlation" in result.message
    assert "VIF" in result.suggestion
