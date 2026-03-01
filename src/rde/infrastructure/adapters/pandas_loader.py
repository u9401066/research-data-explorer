"""PandasLoader — Adapter implementing DataLoaderPort.

Loads data files using pandas, auto-detecting format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from rde.domain.models.dataset import DatasetMetadata
from rde.domain.models.variable import Variable, VariableType
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


class PandasLoader(DataLoaderPort):
    """Loads data files using pandas."""

    def load(self, metadata: DatasetMetadata) -> tuple[pd.DataFrame, list[Variable], int]:
        """Load data from file and return (DataFrame, Variables, row_count)."""
        reader = FORMAT_READERS.get(metadata.file_format)
        if reader is None:
            raise ValueError(f"Unsupported format: {metadata.file_format}")

        kwargs: dict[str, Any] = {}
        if metadata.encoding:
            kwargs["encoding"] = metadata.encoding
        if metadata.sheet_name and metadata.file_format in ("xlsx", "xls"):
            kwargs["sheet_name"] = metadata.sheet_name

        df = reader(metadata.file_path, **kwargs)

        from rde.domain.services.variable_classifier import VariableClassifier
        classifier = VariableClassifier()

        variables = [
            classifier.classify(
                name=col,
                dtype=str(df[col].dtype),
                n_unique=int(df[col].nunique()),
                n_total=len(df),
                sample_values=df[col].dropna().head(10).tolist(),
            )
            for col in df.columns
        ]
        # Carry over missing counts
        for var, col in zip(variables, df.columns):
            var.n_missing = int(df[col].isna().sum())

        return df, variables, len(df)

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
