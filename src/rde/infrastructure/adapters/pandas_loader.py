"""PandasLoader — Adapter implementing DataLoaderPort.

Loads data files using pandas, auto-detecting format.
"""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata

import pandas as pd

from rde.domain.models.dataset import DatasetMetadata
from rde.domain.models.ingestion import ColumnNormalization, RawDataNormalizationReport
from rde.domain.models.variable import Variable
from rde.domain.policies import DEFAULT_HEURISTIC_POLICY
from rde.domain.ports import DataLoaderPort

# Map file extensions to pandas read functions
FORMAT_READERS = {
    "csv": pd.read_csv,
    "tsv": lambda p, **kw: pd.read_csv(p, sep="\t", **kw),
    "xlsx": pd.read_excel,
    "xls": pd.read_excel,
    "parquet": pd.read_parquet,
    "sas7bdat": pd.read_sas,
    "sav": pd.read_spss,
    "dta": pd.read_stata,
}


_SENTINEL_VALUES = DEFAULT_HEURISTIC_POLICY.intake.sentinel_values
_HEADER_METADATA_KEYWORDS = ("研究資料", "匯出時間", "export", "時間")
_CRITICAL_PATTERNS = (
    re.compile(r"^=.+", re.IGNORECASE),
    re.compile(r"cmd\|", re.IGNORECASE),
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"auto[\s_]*open", re.IGNORECASE),
)
_WARNING_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"^@.+", re.IGNORECASE),
)


class PandasLoader(DataLoaderPort):
    """Loads data files using pandas."""

    def list_sheets(self, file_path: Path) -> list[str]:
        """List sheet names in an Excel file."""
        ext = file_path.suffix.lstrip(".")
        if ext not in ("xlsx", "xls"):
            return []
        xf = pd.ExcelFile(file_path)
        return [str(sheet_name) for sheet_name in xf.sheet_names]

    def load(
        self, metadata: DatasetMetadata
    ) -> tuple[pd.DataFrame, list[Variable], int, RawDataNormalizationReport]:
        """Load data from file and return normalized data plus an audit report."""
        report = RawDataNormalizationReport()
        raw = self._read_raw_table(metadata, report)
        header_rows = self._detect_header_rows(raw)
        report.header_row_index = header_rows[-1]
        report.header_row_span = len(header_rows)
        report.skipped_leading_rows = header_rows[0]

        columns = self._build_columns(raw, header_rows, report)
        data = raw.iloc[header_rows[-1] + 1 :].reset_index(drop=True).copy()
        data.columns = columns
        data = self._clean_values(data, report)
        data = self._drop_empty_axes(data, report)
        data = self._coerce_columns(data, report)

        from rde.domain.services.variable_classifier import VariableClassifier

        classifier = VariableClassifier()
        variables: list[Variable] = []
        for col in data.columns:
            series = data[col]
            variable = classifier.classify(
                name=col,
                dtype=str(series.dtype),
                n_unique=int(series.nunique(dropna=True)),
                n_total=len(data),
                sample_values=series.dropna().head(20).tolist(),
            )
            variable.n_missing = int(series.isna().sum())
            alias = self._match_semantic_alias(col)
            if alias is not None:
                semantic_alias, matched_pattern = alias
                report.add_alias(col, semantic_alias, matched_pattern)
                variable.extra["semantic_alias"] = semantic_alias
            variables.append(variable)

        return data, variables, len(data), report

    @staticmethod
    def _coerce_sentinels(df: pd.DataFrame) -> pd.DataFrame:
        """Backward-compatible sentinel replacement helper."""
        for col in df.columns:
            if df[col].dtype == "object":
                vals = df[col].dropna().unique()
                sentinel_found = any(str(v).strip() in _SENTINEL_VALUES for v in vals)
                if sentinel_found:
                    df[col] = df[col].apply(
                        lambda value: pd.NA if str(value).strip() in _SENTINEL_VALUES else value
                    )
                converted = pd.to_numeric(df[col], errors="coerce")
                non_null = df[col].notna().sum()
                numeric_count = converted.notna().sum()
                if (
                    non_null > 0
                    and numeric_count / non_null
                    >= DEFAULT_HEURISTIC_POLICY.intake.numeric_coerce_min_ratio
                ):
                    df[col] = converted
        return df

    def _read_raw_table(
        self, metadata: DatasetMetadata, report: RawDataNormalizationReport
    ) -> pd.DataFrame:
        if metadata.file_format in ("xlsx", "xls"):
            return self._read_excel(metadata, report)
        if metadata.file_format in ("csv", "tsv"):
            sep = "\t" if metadata.file_format == "tsv" else ","
            return self._read_delimited(metadata, sep, report)

        reader = FORMAT_READERS.get(metadata.file_format)
        if reader is None:
            raise ValueError(f"Unsupported format: {metadata.file_format}")
        return reader(metadata.file_path)

    def _read_delimited(
        self, metadata: DatasetMetadata, sep: str, report: RawDataNormalizationReport
    ) -> pd.DataFrame:
        encodings = [metadata.encoding] if metadata.encoding else []
        encodings.extend(DEFAULT_HEURISTIC_POLICY.intake.default_encodings)
        tried: set[str] = set()
        last_error: Exception | None = None
        for encoding in encodings:
            if encoding is None or encoding in tried:
                continue
            tried.add(encoding)
            try:
                df = pd.read_csv(
                    metadata.file_path,
                    sep=sep,
                    header=None,
                    dtype=object,
                    encoding=encoding,
                    keep_default_na=False,
                )
                report.encoding_used = encoding
                return df
            except Exception as exc:
                last_error = exc
        raise ValueError(f"Unable to decode {metadata.file_path.name}: {last_error}")

    def _read_excel(
        self, metadata: DatasetMetadata, report: RawDataNormalizationReport
    ) -> pd.DataFrame:
        workbook = pd.ExcelFile(metadata.file_path)
        sheet_name = metadata.sheet_name
        if sheet_name is None and len(workbook.sheet_names) > 1:
            sheet_name = self._select_sheet(workbook, metadata, report)
            metadata.sheet_name = sheet_name
        elif sheet_name is None:
            sheet_name = str(workbook.sheet_names[0])
        report.selected_sheet_name = sheet_name
        return workbook.parse(sheet_name=sheet_name, header=None, dtype=object)

    def _select_sheet(
        self,
        workbook: pd.ExcelFile,
        metadata: DatasetMetadata,
        report: RawDataNormalizationReport,
    ) -> str:
        report.sheet_selection_mode = "auto"
        report.add_warning("Excel 多分頁，將自動選擇最像資料表的工作表。")
        best_sheet = str(workbook.sheet_names[0])
        best_score = float("-inf")

        for raw_sheet_name in workbook.sheet_names:
            sheet_name = str(raw_sheet_name)
            frame = workbook.parse(sheet_name=sheet_name, header=None, dtype=object)
            row_count, column_count = frame.shape
            total_cells = max(row_count * max(column_count, 1), 1)
            non_empty_ratio = float(frame.notna().sum().sum()) / total_cells
            name_key = self._simplify_token(sheet_name)
            reasons: list[str] = []
            score = non_empty_ratio
            classification = "review_sheet"

            if any(
                keyword in name_key
                for keyword in DEFAULT_HEURISTIC_POLICY.intake.nondata_sheet_name_keywords
            ):
                classification = "non_data_sheet"
                score -= 1.0
                reasons.append("sheet name resembles summary/calculation sheet")
            else:
                classification = "data_candidate"
                if any(
                    keyword in name_key
                    for keyword in DEFAULT_HEURISTIC_POLICY.intake.data_sheet_name_keywords
                ):
                    score += 1.0
                    reasons.append("sheet name resembles raw data")
                if row_count >= 3 and column_count >= 2:
                    score += 0.5
                    reasons.append("sheet has data-like dimensions")

            report.add_sheet_assessment(
                sheet_name=sheet_name,
                classification=classification,
                score=round(score, 4),
                row_count=row_count,
                column_count=column_count,
                non_empty_ratio=round(non_empty_ratio, 4),
                reasons=tuple(reasons),
                selected=False,
            )

            if classification == "data_candidate" and score > best_score:
                best_score = score
                best_sheet = sheet_name

        report.sheet_assessments = [
            item
            if item.sheet_name != best_sheet
            else type(item)(
                sheet_name=item.sheet_name,
                classification=item.classification,
                score=item.score,
                row_count=item.row_count,
                column_count=item.column_count,
                non_empty_ratio=item.non_empty_ratio,
                reasons=item.reasons,
                selected=True,
            )
            for item in report.sheet_assessments
        ]
        skipped = [
            item.sheet_name
            for item in report.sheet_assessments
            if item.sheet_name != best_sheet and item.classification == "non_data_sheet"
        ]
        if skipped:
            report.add_warning(f"略過疑似非資料工作表: {', '.join(skipped)}")
        return best_sheet

    def _detect_header_rows(self, raw: pd.DataFrame) -> list[int]:
        limit = min(len(raw), DEFAULT_HEURISTIC_POLICY.intake.header_scan_limit)
        start = 0
        for idx in range(limit):
            values = self._row_values(raw.iloc[idx])
            if self._is_metadata_row(values):
                continue
            if self._row_looks_like_header(values):
                start = idx
                break

        header_rows = [start]
        for idx in range(
            start + 1,
            min(start + 1 + DEFAULT_HEURISTIC_POLICY.intake.max_header_prefix_rows, limit),
        ):
            values = self._row_values(raw.iloc[idx])
            if self._row_looks_like_data(values):
                break
            if self._row_looks_like_header(values):
                header_rows.append(idx)
            else:
                break
        return header_rows

    def _build_columns(
        self,
        raw: pd.DataFrame,
        header_rows: list[int],
        report: RawDataNormalizationReport,
    ) -> list[str]:
        columns: list[str] = []
        seen: dict[str, int] = {}
        last_header = raw.iloc[header_rows[-1]]

        for idx in range(raw.shape[1]):
            raw_base = self._normalize_text(last_header.iloc[idx])
            parts = [self._normalize_text(raw.iloc[row_idx, idx]) for row_idx in header_rows]
            parts = [part for part in parts if part]
            if not parts:
                parts = [f"column_{idx + 1}"]
            combined = "_".join(parts)
            normalized = self._sanitize_column_name(combined)
            normalized = self._dedupe_name(normalized, seen)
            columns.append(normalized)
            if raw_base and normalized != raw_base:
                report.standardized_columns.append(
                    ColumnNormalization(original_name=raw_base, normalized_name=normalized)
                )

        return columns

    def _clean_values(self, df: pd.DataFrame, report: RawDataNormalizationReport) -> pd.DataFrame:
        cleaned = df.copy()
        warning_flags = {"formula": False, "script": False, "url": False}

        for column in cleaned.columns:
            values: list[object] = []
            for row_idx, value in enumerate(cleaned[column].tolist(), start=1):
                normalized = self._normalize_text(value)
                if not normalized or normalized in _SENTINEL_VALUES:
                    values.append(pd.NA)
                    continue

                critical = next(
                    (pattern for pattern in _CRITICAL_PATTERNS if pattern.search(normalized)), None
                )
                if critical is not None:
                    values.append(pd.NA)
                    lowered = normalized.lower()
                    is_critical_payload = any(
                        token in lowered
                        for token in ("cmd|", "<script", "javascript:", "auto_open", "auto open")
                    )
                    severity = "critical" if is_critical_payload else "warning"
                    warning_flags["script" if is_critical_payload else "formula"] = True
                    report.add_suspicious_finding(
                        category="formula_or_script",
                        severity=severity,
                        cell_reference=f"{column}[{row_idx}]",
                        sample_value=normalized,
                        action_taken="replaced_with_missing",
                    )
                    continue

                warning = next(
                    (pattern for pattern in _WARNING_PATTERNS if pattern.search(normalized)), None
                )
                if warning is not None:
                    values.append(pd.NA)
                    warning_flags["url"] = True
                    report.add_suspicious_finding(
                        category="external_reference",
                        severity="warning",
                        cell_reference=f"{column}[{row_idx}]",
                        sample_value=normalized,
                        action_taken="replaced_with_missing",
                    )
                    continue

                values.append(normalized)

            cleaned[column] = pd.Series(values, index=cleaned.index, dtype=object)

        if warning_flags["formula"]:
            report.add_warning("偵測到疑似公式內容，已轉為缺失值。")
        if warning_flags["script"]:
            report.add_warning("偵測到疑似 script / 巨集內容，已轉為缺失值。")
        if warning_flags["url"]:
            report.add_warning("偵測到疑似外部連結內容，已轉為缺失值。")

        return cleaned

    def _drop_empty_axes(
        self, df: pd.DataFrame, report: RawDataNormalizationReport
    ) -> pd.DataFrame:
        non_empty_rows = df.notna().any(axis=1)
        report.removed_empty_rows = int((~non_empty_rows).sum())
        df = df.loc[non_empty_rows].reset_index(drop=True)

        non_empty_cols = df.notna().any(axis=0)
        report.removed_empty_columns = int((~non_empty_cols).sum())
        return df.loc[:, non_empty_cols]

    def _coerce_columns(self, df: pd.DataFrame, report: RawDataNormalizationReport) -> pd.DataFrame:
        coerced = df.copy()
        for column in coerced.columns:
            series = coerced[column]
            if self._should_preserve_text(column, series):
                report.add_warning(f"欄位 {column} 疑似代碼欄，保留文字格式。")
                continue

            numeric = pd.to_numeric(series, errors="coerce")
            non_null = int(series.notna().sum())
            if non_null == 0:
                continue
            if (
                numeric.notna().sum() / non_null
                >= DEFAULT_HEURISTIC_POLICY.intake.numeric_coerce_min_ratio
            ):
                coerced[column] = numeric
        return coerced

    @staticmethod
    def _row_values(row: pd.Series) -> list[str]:
        return [
            unicodedata.normalize("NFKC", str(value)).strip()
            for value in row.tolist()
            if value is not None and str(value).strip()
        ]

    def _row_looks_like_header(self, values: list[str]) -> bool:
        if len(values) < 2 or self._is_metadata_row(values):
            return False
        textish = sum(1 for value in values if not self._is_numeric_like(value))
        return textish / len(values) >= 0.6

    def _row_looks_like_data(self, values: list[str]) -> bool:
        if len(values) < 2:
            return False
        data_like = sum(
            1 for value in values if self._is_numeric_like(value) or self._is_code_like_value(value)
        )
        return data_like / len(values) >= 0.4

    def _is_metadata_row(self, values: list[str]) -> bool:
        if len(values) <= 1:
            return True
        joined = " ".join(values)
        return any(keyword in joined for keyword in _HEADER_METADATA_KEYWORDS)

    @staticmethod
    def _normalize_text(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return unicodedata.normalize("NFKC", str(value)).strip()

    @staticmethod
    def _sanitize_column_name(name: str) -> str:
        normalized = unicodedata.normalize("NFKC", name).strip()
        normalized = re.sub(r"<[^>]+>", "", normalized)
        normalized = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "unnamed"

    @staticmethod
    def _dedupe_name(name: str, seen: dict[str, int]) -> str:
        count = seen.get(name, 0)
        seen[name] = count + 1
        if count == 0:
            return name
        return f"{name}_{count + 1}"

    @staticmethod
    def _is_numeric_like(value: str) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_code_like_value(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z]*\d+[A-Za-z\d]*", value))

    def _should_preserve_text(self, column: str, series: pd.Series) -> bool:
        key = self._simplify_token(column)
        if any(
            keyword in key for keyword in DEFAULT_HEURISTIC_POLICY.intake.code_like_name_keywords
        ):
            return True
        sample = [str(value) for value in series.dropna().head(10).tolist()]
        return any(re.fullmatch(r"0\d+", value) for value in sample)

    def _match_semantic_alias(self, column_name: str) -> tuple[str, str] | None:
        simplified = self._simplify_token(column_name)
        tokens = self._tokenize_column_name(column_name)
        for alias, patterns in DEFAULT_HEURISTIC_POLICY.intake.semantic_alias_patterns.items():
            for pattern in patterns:
                simplified_pattern = self._simplify_token(pattern)
                if not simplified_pattern:
                    continue
                if re.fullmatch(r"[a-z0-9]+", simplified_pattern):
                    if simplified == simplified_pattern or simplified_pattern in tokens:
                        return alias, pattern
                    continue
                if simplified_pattern in simplified:
                    return alias, pattern
        return None

    def _tokenize_column_name(self, column_name: str) -> set[str]:
        tokens = {
            self._simplify_token(part)
            for part in re.split(r"[_\W]+", unicodedata.normalize("NFKC", column_name).lower())
            if part
        }
        return {token for token in tokens if token}

    @staticmethod
    def _simplify_token(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).lower()
        return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)

    def scan_directory(self, directory: Path) -> list[DatasetMetadata]:
        """Scan directory for data files."""
        results: list[DatasetMetadata] = []
        for ext in FORMAT_READERS:
            for file_path in directory.glob(f"**/*.{ext}"):
                results.append(
                    DatasetMetadata(
                        file_path=file_path,
                        file_format=ext,
                        file_size_bytes=file_path.stat().st_size,
                    )
                )
        return results
