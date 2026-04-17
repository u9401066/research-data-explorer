"""Numeric plausibility guards for analysis-ready data.

Applies conservative human bounds plus adult-specific anthropometric ranges
when an age column is available. Implausible numeric values are masked as
missing so downstream plots and analyses can remain robust without silently
re-scaling the data.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd


@dataclass(frozen=True)
class NumericPlausibilityRule:
    canonical_name: str
    universal_lower: float
    universal_upper: float
    aliases: tuple[str, ...]
    adult_lower: float | None = None
    adult_upper: float | None = None


@dataclass(frozen=True)
class NumericPlausibilityFinding:
    variable_name: str
    excluded_count: int
    universal_excluded_count: int = 0
    adult_excluded_count: int = 0

    def annotation_line(self) -> str:
        details: list[str] = []
        if self.universal_excluded_count:
            details.append(f"human-bounds n={self.universal_excluded_count}")
        if self.adult_excluded_count:
            details.append(f"adult-range n={self.adult_excluded_count}")
        detail_text = f" ({', '.join(details)})" if details else ""
        return f"{self.variable_name}: excluded {self.excluded_count} implausible values{detail_text}"

    def markdown_line(self) -> str:
        details: list[str] = []
        if self.universal_excluded_count:
            details.append(f"超出人類合理界限 {self.universal_excluded_count} 筆")
        if self.adult_excluded_count:
            details.append(f"超出成人範圍 {self.adult_excluded_count} 筆")
        detail_text = f"（{'；'.join(details)}）" if details else ""
        return f"{self.variable_name}: 排除 {self.excluded_count} 筆不合理值{detail_text}"

    def summary_token(self) -> str:
        return f"{self.variable_name} excluded {self.excluded_count}"


_RULES: tuple[NumericPlausibilityRule, ...] = (
    NumericPlausibilityRule(
        canonical_name="bmi",
        universal_lower=5.0,
        universal_upper=120.0,
        adult_lower=10.0,
        adult_upper=80.0,
        aliases=("bmi", "bodymassindex", "身體質量指數"),
    ),
    NumericPlausibilityRule(
        canonical_name="height_cm",
        universal_lower=30.0,
        universal_upper=250.0,
        adult_lower=100.0,
        adult_upper=250.0,
        aliases=("heightcm", "height_cm", "height", "bodyheight", "身高"),
    ),
    NumericPlausibilityRule(
        canonical_name="weight_kg",
        universal_lower=1.0,
        universal_upper=400.0,
        adult_lower=25.0,
        adult_upper=400.0,
        aliases=("weightkg", "weight_kg", "weight", "bodyweight", "體重"),
    ),
)

_AGE_ALIASES = ("age", "ageyears", "age_years", "年齡")


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(name).strip().lower())


def match_numeric_plausibility_rule(variable_name: str) -> NumericPlausibilityRule | None:
    normalized = _normalize_name(variable_name)
    for rule in _RULES:
        for alias in rule.aliases:
            alias_normalized = _normalize_name(alias)
            if normalized == alias_normalized or alias_normalized in normalized:
                return rule
    return None


def _find_age_column(df: pd.DataFrame) -> str | None:
    normalized_map = {_normalize_name(column): column for column in df.columns}
    for alias in _AGE_ALIASES:
        column = normalized_map.get(_normalize_name(alias))
        if column is not None:
            return column
    return None


def apply_numeric_plausibility_filters(
    df: pd.DataFrame,
    variables: list[str] | tuple[str, ...],
) -> tuple[pd.DataFrame, list[NumericPlausibilityFinding]]:
    """Mask implausible numeric values as missing for selected variables."""

    cleaned = df.copy()
    findings: list[NumericPlausibilityFinding] = []
    age_column = _find_age_column(cleaned)
    age_series = (
        pd.to_numeric(cleaned[age_column], errors="coerce") if age_column and age_column in cleaned else None
    )

    seen: set[str] = set()
    for variable in variables:
        if variable in seen or variable not in cleaned.columns:
            continue
        seen.add(variable)

        rule = match_numeric_plausibility_rule(variable)
        if rule is None:
            continue

        numeric = pd.to_numeric(cleaned[variable], errors="coerce")
        universal_mask = numeric.notna() & ~numeric.between(
            rule.universal_lower,
            rule.universal_upper,
            inclusive="both",
        )
        adult_mask = pd.Series(False, index=cleaned.index)
        if age_series is not None and rule.adult_lower is not None and rule.adult_upper is not None:
            adult_rows = age_series.notna() & (age_series >= 18) & numeric.notna() & ~universal_mask
            adult_mask = adult_rows & ~numeric.between(
                rule.adult_lower,
                rule.adult_upper,
                inclusive="both",
            )

        combined_mask = universal_mask | adult_mask
        excluded_count = int(combined_mask.sum())
        if excluded_count == 0:
            continue

        cleaned[variable] = numeric.mask(combined_mask)
        findings.append(
            NumericPlausibilityFinding(
                variable_name=variable,
                excluded_count=excluded_count,
                universal_excluded_count=int(universal_mask.sum()),
                adult_excluded_count=int(adult_mask.sum()),
            )
        )

    return cleaned, findings


def format_plausibility_markdown(findings: list[NumericPlausibilityFinding]) -> list[str]:
    return [finding.markdown_line() for finding in findings]


def summarize_plausibility_findings(findings: list[NumericPlausibilityFinding]) -> str | None:
    if not findings:
        return None
    return "; ".join(finding.summary_token() for finding in findings)