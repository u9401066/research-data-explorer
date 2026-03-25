from pathlib import Path

import pandas as pd

from rde.domain.models.dataset import DatasetMetadata
from rde.infrastructure.adapters.pandas_loader import PandasLoader


def test_pandas_loader_normalizes_messy_raw_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "messy_raw.csv"
    csv_path.write_text(
        "\n".join(
            [
                "AKI 研究資料,,,,",
                "匯出時間：2026-03-25,,,,",
                "病歷號  , 年齡 , CRP（mg／dL）, 空白欄 , 註記<script>",
                "A001,34,1.2,   , 正常",
                'A002, ,"=SUM(1,2)",   ,   ',
                " , , , , ",
                "A003,45,3.4,　,javascript:alert(1)",
            ]
        ),
        encoding="utf-8",
    )

    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=csv_path,
        file_format="csv",
        file_size_bytes=csv_path.stat().st_size,
    )

    df, variables, row_count, report = loader.load(metadata)

    assert report.encoding_used in {"utf-8", "utf-8-sig"}
    assert report.header_row_index == 2
    assert report.skipped_leading_rows == 2
    assert report.removed_empty_rows == 1
    assert report.removed_empty_columns == 1
    assert report.suspicious_formula_cells >= 2
    assert row_count == 3
    assert "病歷號" in df.columns
    assert "年齡" in df.columns
    assert "空白欄" not in df.columns

    crp_column = next(name for name in df.columns if name.startswith("CRP"))
    note_column = next(name for name in df.columns if name.startswith("註記"))

    assert pd.isna(df.loc[1, crp_column])
    assert pd.isna(df.loc[2, note_column])
    assert df.loc[0, "病歷號"] == "A001"
    assert df.loc[1, "年齡"] is pd.NA or pd.isna(df.loc[1, "年齡"])

    normalized_pairs = {(item.original_name, item.normalized_name) for item in report.standardized_columns}
    assert any(original == "病歷號" and normalized == "病歷號" for original, normalized in normalized_pairs) is False
    assert any(original == "CRP(mg/dL)" and normalized.startswith("CRP") for original, normalized in normalized_pairs)
    assert {variable.name for variable in variables} == set(df.columns)
    assert any("公式" in warning or "script" in warning for warning in report.warnings)


def test_pandas_loader_merges_multirow_headers_and_assigns_semantic_aliases(tmp_path: Path) -> None:
    csv_path = tmp_path / "taiwan_header_style.csv"
    csv_path.write_text(
        "\n".join(
            [
                "台灣腎臟研究資料,,,,,",
                ",基本資料,基本資料,實驗室,實驗室,註記",
                "受試者編號,性別,年齡,血清肌酐,CRP（mg／dL）,附註",
                "S001,M,67,1.8,2.4,正常",
                'S002,F,58,=cmd|\'/c calc\'!A0,1.1,https://bad.example',
                'S003,F,61,1.2,0.8,Sub Auto_Open() ',
            ]
        ),
        encoding="utf-8",
    )

    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=csv_path,
        file_format="csv",
        file_size_bytes=csv_path.stat().st_size,
    )

    df, variables, row_count, report = loader.load(metadata)

    assert row_count == 3
    assert report.header_row_index == 2
    assert report.header_row_span == 2
    assert report.highest_suspicious_severity == "critical"
    assert report.suspicious_counts_by_severity["critical"] >= 2
    assert report.suspicious_counts_by_severity["warning"] >= 1

    alias_map = {item.normalized_name: item.semantic_alias for item in report.semantic_aliases}
    assert alias_map["受試者編號"] == "case_id"
    assert alias_map["基本資料_性別"] == "sex"
    assert alias_map["基本資料_年齡"] == "age"
    assert alias_map["實驗室_血清肌酐"] == "serum_creatinine"
    assert alias_map["實驗室_CRP_mg_dL"] == "crp"

    variable_aliases = {variable.name: variable.extra.get("semantic_alias") for variable in variables}
    assert variable_aliases["基本資料_性別"] == "sex"
    assert variable_aliases["實驗室_血清肌酐"] == "serum_creatinine"

    note_column = next(name for name in df.columns if name.endswith("附註"))
    assert pd.isna(df.loc[1, "實驗室_血清肌酐"])
    assert pd.isna(df.loc[1, note_column])
    assert pd.isna(df.loc[2, note_column])


def test_pandas_loader_auto_selects_data_sheet_from_multisheet_excel(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "multisheet_workbook.xlsx"

    calc_df = pd.DataFrame(
        [
            ["平均值", "=AVERAGE(資料!C2:C4)"],
            ["總數", "=COUNTA(資料!A2:A4)"],
            ["百分比", "=B1/B2"],
        ]
    )
    data_df = pd.DataFrame(
        [
            ["病歷號", "性別", "年齡", "CRP"],
            ["A001", "M", 65, 1.2],
            ["A002", "F", 57, 3.4],
            ["A003", "F", 49, 0.8],
        ]
    )

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        calc_df.to_excel(writer, sheet_name="計算表", header=False, index=False)
        data_df.to_excel(writer, sheet_name="資料", header=False, index=False)

    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=xlsx_path,
        file_format="xlsx",
        file_size_bytes=xlsx_path.stat().st_size,
    )

    df, variables, row_count, report = loader.load(metadata)

    assert metadata.sheet_name == "資料"
    assert report.selected_sheet_name == "資料"
    assert report.sheet_selection_mode == "auto"
    assert row_count == 3
    assert set(df.columns) == {"病歷號", "性別", "年齡", "CRP"}
    assert all(variable.name in df.columns for variable in variables)

    assessments = {item.sheet_name: item for item in report.sheet_assessments}
    assert assessments["資料"].selected is True
    assert assessments["資料"].classification == "data_candidate"
    assert assessments["計算表"].selected is False
    assert assessments["計算表"].classification == "non_data_sheet"
    assert any("Excel 多分頁" in warning for warning in report.warnings)
    assert any("略過疑似非資料工作表" in warning for warning in report.warnings)


def test_pandas_loader_preserves_code_like_and_non_alias_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "code_like_columns.csv"
    csv_path.write_text(
        "\n".join(
            [
                "sample_code,stage,message,lab_value",
                "001,2,hello,1.2",
                "010,3,world,2.4",
                "099,4,again,3.6",
            ]
        ),
        encoding="utf-8",
    )

    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=csv_path,
        file_format="csv",
        file_size_bytes=csv_path.stat().st_size,
    )

    df, variables, _, report = loader.load(metadata)

    assert not pd.api.types.is_numeric_dtype(df["sample_code"])
    assert df.loc[0, "sample_code"] == "001"
    alias_map = {item.normalized_name: item.semantic_alias for item in report.semantic_aliases}
    assert "stage" not in alias_map
    assert "message" not in alias_map
    variable_aliases = {variable.name: variable.extra.get("semantic_alias") for variable in variables}
    assert variable_aliases["stage"] is None
    assert any("sample_code" in warning and "保留文字格式" in warning for warning in report.warnings)