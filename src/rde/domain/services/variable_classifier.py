"""VariableClassifier — Domain Service.

Infers the statistical type of a variable from its raw dtype,
value distribution, **and sample values**. Pure domain logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rde.domain.models.variable import Variable, VariableType

logger = logging.getLogger(__name__)

# Column name patterns that suggest PII (Hook H-004)
PII_PATTERNS = [
    "name", "姓名", "email", "phone", "電話", "address", "地址",
    "id_number", "身分證", "身份證", "社會安全", "ssn", "passport",
    "護照", "birthday", "生日", "出生",
]

# Column name patterns that strongly suggest ID columns
ID_NAME_PATTERNS = re.compile(
    r"(?:^id$|_id$|^.*_?(?:no|number|code|key|uuid|guid)$)", re.IGNORECASE,
)

# Common date-like patterns for string detection
_DATE_PATTERNS = [
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"),          # 2025-03-02
    re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"),        # 03/02/2025
    re.compile(r"^\d{8}$"),                                 # 20250302
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}"), # 2025-03-02 10:...
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
        is_pii = self._check_pii(name)

        return Variable(
            name=name,
            dtype=dtype,
            variable_type=variable_type,
            n_unique=n_unique,
            is_pii_suspect=is_pii,
            extra={"total_count": n_total},
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
            if n_total > 0 and n_unique / n_total > 0.05:
                return VariableType.CONTINUOUS
            if n_unique <= 10:
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
            if n_unique <= 20:
                return VariableType.CATEGORICAL
            if n_total > 0 and n_unique / n_total > 0.9:
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
        matches = sum(
            1 for v in valid
            if any(p.match(v) for p in _DATE_PATTERNS)
        )
        return matches / len(valid) >= 0.6

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
        return numeric / len(valid) >= 0.6

    def _check_pii(self, name: str) -> bool:
        """Hook H-004: flag potential PII columns."""
        name_lower = name.lower().replace("_", "").replace("-", "").replace(" ", "")
        return any(pattern in name_lower for pattern in PII_PATTERNS)
