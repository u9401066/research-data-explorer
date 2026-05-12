"""VariableClassifier — Domain Service.

Infers the statistical type of a variable from its raw dtype,
value distribution, **and sample values**. Pure domain logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rde.domain.models.variable import Variable, VariableType
from rde.domain.policies import DEFAULT_HEURISTIC_POLICY

logger = logging.getLogger(__name__)

# Column name patterns that suggest PII (Hook H-004)
PII_PATTERNS = list(DEFAULT_HEURISTIC_POLICY.classification.pii_patterns)
PII_VALUE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in DEFAULT_HEURISTIC_POLICY.classification.pii_value_patterns
]

# Column name patterns that strongly suggest ID columns
ID_NAME_PATTERNS = re.compile(
    r"(?:^id$|_id$|^.*_?(?:no|number|code|key|uuid|guid)$)",
    re.IGNORECASE,
)

# Numeric columns with these names usually encode categories rather than
# measurements. Keep this conservative: the unique-count guard below must also
# pass before the classifier treats them as categorical.
CODED_CATEGORY_NAME_PATTERNS = re.compile(
    r"(?:sex|gender|group|arm|treat|drug|medication|用藥|藥物|性別|組別|分組|類別|分類|"
    r"(?:^|_)\d+[_-])",
    re.IGNORECASE,
)

ORDINAL_NAME_PATTERNS = re.compile(
    r"(?:grade|stage|severity|rank|level|score|分級|等級|級別|程度|評分)",
    re.IGNORECASE,
)

# Common date-like patterns for string detection
_DATE_PATTERNS = [
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"),  # 2025-03-02
    re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"),  # 03/02/2025
    re.compile(r"^\d{8}$"),  # 20250302
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}"),  # 2025-03-02 10:...
]


class VariableClassifier:
    """Classifies variables by statistical type.

    Responsible for:
    - Inferring VariableType from dtype + value characteristics + sample values
    - Detecting potential PII columns (Hook H-004)
    """

    def classify(
        self,
        name: str,
        dtype: str,
        n_unique: int,
        n_total: int,
        sample_values: list | None = None,
    ) -> Variable:
        """Classify a variable and return a Variable entity."""
        variable_type = self._infer_type(dtype, n_unique, n_total, name, sample_values)
        pii_reasons = self._pii_reasons(name, sample_values or [])
        is_pii = bool(pii_reasons)
        extra: dict[str, Any] = {"total_count": n_total}
        if pii_reasons:
            extra["pii_detection"] = pii_reasons

        return Variable(
            name=name,
            dtype=dtype,
            variable_type=variable_type,
            n_unique=n_unique,
            is_pii_suspect=is_pii,
            extra=extra,
        )

    def _infer_type(
        self,
        dtype: str,
        n_unique: int,
        n_total: int,
        name: str = "",
        sample_values: list | None = None,
    ) -> VariableType:
        dtype_lower = dtype.lower()

        # ── 1. Explicit datetime dtype ──────────────────────────
        if "datetime" in dtype_lower or "timestamp" in dtype_lower:
            return VariableType.DATETIME

        # ── 2. Boolean ──────────────────────────────────────────
        if "bool" in dtype_lower:
            return VariableType.BINARY

        # ── 3. Numeric dtype ────────────────────────────────────
        if any(t in dtype_lower for t in ("int", "float", "decimal", "numeric")):
            # Name-based ID detection (e.g., patient_id with int dtype)
            if ID_NAME_PATTERNS.search(name):
                return VariableType.ID
            if n_unique == 2:
                return VariableType.BINARY
            if (
                n_unique <= DEFAULT_HEURISTIC_POLICY.classification.numeric_ordinal_unique_max
                and CODED_CATEGORY_NAME_PATTERNS.search(name)
            ):
                return VariableType.CATEGORICAL
            if (
                n_unique <= DEFAULT_HEURISTIC_POLICY.classification.numeric_ordinal_unique_max
                and ORDINAL_NAME_PATTERNS.search(name)
            ):
                return VariableType.ORDINAL
            if (
                n_total > 0
                and n_unique / n_total
                > DEFAULT_HEURISTIC_POLICY.classification.numeric_continuous_unique_ratio_threshold
            ):
                return VariableType.CONTINUOUS
            if n_unique <= DEFAULT_HEURISTIC_POLICY.classification.numeric_ordinal_unique_max:
                return VariableType.ORDINAL
            return VariableType.CONTINUOUS

        # ── 4. String/Object — enhanced with sample_values ──────
        if any(t in dtype_lower for t in ("object", "string", "category", "str")):
            # Name-based ID check first
            if ID_NAME_PATTERNS.search(name):
                return VariableType.ID

            # Sample-value deep inference (when available)
            if sample_values:
                if self._looks_like_datetime(sample_values):
                    return VariableType.DATETIME
                if self._looks_like_numeric_string(sample_values):
                    # Numeric strings with low cardinality → ordinal
                    if n_unique <= 10:
                        return VariableType.ORDINAL
                    return VariableType.CONTINUOUS

            if n_unique == 2:
                return VariableType.BINARY
            if n_unique <= DEFAULT_HEURISTIC_POLICY.classification.string_categorical_unique_max:
                return VariableType.CATEGORICAL
            if (
                n_total > 0
                and n_unique / n_total
                > DEFAULT_HEURISTIC_POLICY.classification.string_id_unique_ratio_threshold
            ):
                return VariableType.ID
            return VariableType.TEXT

        return VariableType.UNKNOWN

    # ── Sample-value helpers ────────────────────────────────────

    @staticmethod
    def _looks_like_datetime(samples: list[Any]) -> bool:
        """Check if ≥60% of non-null sample values match date patterns."""
        valid = [str(s).strip() for s in samples if s is not None and str(s).strip()]
        if len(valid) < 2:
            return False
        matches = sum(1 for v in valid if any(p.match(v) for p in _DATE_PATTERNS))
        return (
            matches / len(valid)
            >= DEFAULT_HEURISTIC_POLICY.classification.sample_match_ratio_threshold
        )

    @staticmethod
    def _looks_like_numeric_string(samples: list[Any]) -> bool:
        """Check if ≥60% of non-null samples are parseable as numbers."""
        valid = [str(s).strip() for s in samples if s is not None and str(s).strip()]
        if len(valid) < 2:
            return False
        numeric = 0
        for v in valid:
            try:
                float(v)
                numeric += 1
            except (ValueError, TypeError):
                pass
        return (
            numeric / len(valid)
            >= DEFAULT_HEURISTIC_POLICY.classification.sample_match_ratio_threshold
        )

    def _check_pii(self, name: str, sample_values: list[Any] | None = None) -> bool:
        """Hook H-004: flag potential PII columns."""
        return bool(self._pii_reasons(name, sample_values or []))

    def _pii_reasons(self, name: str, sample_values: list[Any]) -> list[str]:
        """Hook H-004: flag name-based and value-level PII signals."""
        reasons: list[str] = []
        name_lower = name.lower().replace("_", "").replace("-", "").replace(" ", "")
        if any(pattern in name_lower for pattern in PII_PATTERNS):
            reasons.append("name_pattern")

        valid = [
            str(value).strip()
            for value in sample_values
            if value is not None and str(value).strip()
        ]
        if not valid:
            return reasons

        matches = 0
        for value in valid:
            if any(pattern.search(value) for pattern in PII_VALUE_PATTERNS):
                matches += 1

        policy = DEFAULT_HEURISTIC_POLICY.classification
        if matches >= policy.pii_value_sample_min_matches and matches / len(valid) >= min(
            1.0, policy.pii_value_sample_ratio_threshold
        ):
            reasons.append("value_pattern")

        return reasons
