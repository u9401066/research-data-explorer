"""VariableClassifier — Domain Service.

Infers the statistical type of a variable from its raw dtype
and value distribution. Pure domain logic.
"""

from __future__ import annotations

from rde.domain.models.variable import Variable, VariableType

# Column name patterns that suggest PII (Hook H-004)
PII_PATTERNS = [
    "name", "姓名", "email", "phone", "電話", "address", "地址",
    "id_number", "身分證", "身份證", "社會安全", "ssn", "passport",
    "護照", "birthday", "生日", "出生",
]


class VariableClassifier:
    """Classifies variables by statistical type.

    Responsible for:
    - Inferring VariableType from dtype + value characteristics
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
        variable_type = self._infer_type(dtype, n_unique, n_total)
        is_pii = self._check_pii(name)

        return Variable(
            name=name,
            dtype=dtype,
            variable_type=variable_type,
            n_unique=n_unique,
            is_pii_suspect=is_pii,
            extra={"total_count": n_total},
        )

    def _infer_type(self, dtype: str, n_unique: int, n_total: int) -> VariableType:
        dtype_lower = dtype.lower()

        # Datetime
        if "datetime" in dtype_lower or "timestamp" in dtype_lower:
            return VariableType.DATETIME

        # Numeric
        if any(t in dtype_lower for t in ("int", "float", "decimal", "numeric")):
            if n_unique == 2:
                return VariableType.BINARY
            # High cardinality numeric → continuous
            if n_total > 0 and n_unique / n_total > 0.05:
                return VariableType.CONTINUOUS
            # Low cardinality numeric → could be ordinal/categorical
            if n_unique <= 10:
                return VariableType.ORDINAL
            return VariableType.CONTINUOUS

        # String/Object
        if any(t in dtype_lower for t in ("object", "string", "category", "str")):
            if n_unique == 2:
                return VariableType.BINARY
            if n_unique <= 20:
                return VariableType.CATEGORICAL
            if n_total > 0 and n_unique / n_total > 0.9:
                return VariableType.ID
            return VariableType.TEXT

        # Boolean
        if "bool" in dtype_lower:
            return VariableType.BINARY

        return VariableType.UNKNOWN

    def _check_pii(self, name: str) -> bool:
        """Hook H-004: flag potential PII columns."""
        name_lower = name.lower().replace("_", "").replace("-", "").replace(" ", "")
        return any(pattern in name_lower for pattern in PII_PATTERNS)
