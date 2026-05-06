"""Centralized heuristic policy for auditable EDA behavior.

This module gathers non-hard-coded thresholds and interpretation defaults in one
place so the repo can evolve from scattered heuristics toward configurable
policy-driven behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntakeHeuristics:
    default_encodings: tuple[str, ...] = (
        "utf-8-sig",
        "utf-8",
        "utf-16",
        "cp950",
        "big5",
        "latin1",
    )
    sentinel_values: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "X",
                "x",
                "N/A",
                "n/a",
                "NA",
                "na",
                "NaN",
                "nan",
                "NULL",
                "null",
                "None",
                "none",
                ".",
                "-",
                "--",
                "---",
                "missing",
                "MISSING",
                "未測",
                "未做",
                "缺失",
            }
        )
    )
    header_scan_limit: int = 12
    max_header_prefix_rows: int = 2
    numeric_coerce_min_ratio: float = 0.9
    nondata_sheet_name_keywords: tuple[str, ...] = (
        "calc",
        "計算",
        "公式",
        "summary",
        "摘要",
        "報表",
        "report",
        "pivot",
        "樞紐",
        "chart",
        "圖表",
        "dashboard",
        "看板",
        "lookup",
        "對照",
        "codebook",
        "字典",
        "dictionary",
        "說明",
    )
    data_sheet_name_keywords: tuple[str, ...] = (
        "data",
        "raw",
        "資料",
        "名單",
        "名冊",
        "dataset",
        "export",
        "匯出",
        "病例",
        "個案",
    )
    summary_cell_keywords: tuple[str, ...] = (
        "合計",
        "總計",
        "平均",
        "中位數",
        "百分比",
        "占比",
        "統計",
        "summary",
        "total",
        "mean",
        "median",
        "count",
        "n=",
        "ratio",
        "percent",
    )
    code_like_name_keywords: tuple[str, ...] = (
        "id",
        "code",
        "key",
        "uuid",
        "guid",
        "mrn",
        "chart",
        "subject",
        "study",
        "case",
        "編號",
        "案號",
        "病歷號",
        "代碼",
    )
    semantic_alias_patterns: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "patient_id": (
                "病歷號",
                "病歷編號",
                "病例號",
                "個案編號",
                "chartno",
                "mrn",
                "patientid",
            ),
            "case_id": ("案號", "受試者編號", "subjectid", "caseid", "studyid"),
            "sex": ("性別", "gender", "sex"),
            "age": ("年齡", "age", "歲"),
            "birth_date": ("出生日期", "生日", "dob", "birthdate"),
            "admission_date": ("入院日期", "住院日期", "admissiondate", "admdate"),
            "discharge_date": ("出院日期", "dischargedate", "dcdate"),
            "bmi": ("bmi", "bodymassindex", "身體質量指數"),
            "serum_creatinine": ("creatinine", "肌酐", "血清肌酐", "scr"),
            "bun": ("bun", "尿素氮", "bloodureanitrogen"),
            "crp": ("crp", "c反應蛋白", "creactiveprotein"),
            "wbc": ("wbc", "whitebloodcell", "白血球"),
            "hemoglobin": ("hemoglobin", "hb", "血紅素"),
            "platelet": ("platelet", "plt", "血小板"),
            "aki": ("aki", "acutekidneyinjury", "急性腎損傷"),
            "egfr": ("egfr", "estimatedgfr", "腎絲球過濾率"),
        }
    )


@dataclass(frozen=True)
class ClassificationHeuristics:
    pii_patterns: tuple[str, ...] = (
        "name",
        "姓名",
        "email",
        "phone",
        "電話",
        "address",
        "地址",
        "id_number",
        "身分證",
        "身份證",
        "社會安全",
        "ssn",
        "passport",
        "護照",
        "birthday",
        "生日",
        "出生",
    )
    pii_value_patterns: tuple[str, ...] = (
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]\d{4}\b",
        r"\b[A-Z][12]\d{8}\b",
    )
    pii_value_sample_min_matches: int = 1
    pii_value_sample_ratio_threshold: float = 0.2
    numeric_continuous_unique_ratio_threshold: float = 0.05
    numeric_ordinal_unique_max: int = 10
    string_categorical_unique_max: int = 20
    string_id_unique_ratio_threshold: float = 0.9
    sample_match_ratio_threshold: float = 0.6


@dataclass(frozen=True)
class AnalysisHeuristics:
    normality_large_sample_threshold: int = 50
    multiple_comparison_bonferroni_max: int = 5
    missing_moderate_pct_threshold: float = 5.0
    missing_critical_pct_threshold: float = 50.0
    skewness_transform_threshold: float = 1.0
    outlier_skewness_threshold: float = 2.0
    outlier_kurtosis_threshold: float = 7.0
    collinearity_correlation_threshold: float = 0.8
    sample_balance_ratio_threshold: float = 3.0
    power_small_sample_threshold: int = 100
    parametric_group_min_n: int = 30
    chi_square_expected_cell_min: int = 5
    small_effect_thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "cohen_d": 0.2,
            "cohens_d": 0.2,
            "hedges_g": 0.2,
            "glass_delta": 0.2,
            "r": 0.1,
            "pearson_r": 0.1,
            "spearman_r": 0.1,
            "point_biserial_r": 0.1,
            "eta_squared": 0.01,
            "partial_eta_squared": 0.01,
            "cramers_v": 0.1,
        }
    )
    effect_size_label_thresholds: dict[str, tuple[float, float, float]] = field(
        default_factory=lambda: {
            "cohen_d": (0.2, 0.5, 0.8),
            "cohens_d": (0.2, 0.5, 0.8),
            "hedges_g": (0.2, 0.5, 0.8),
            "glass_delta": (0.2, 0.5, 0.8),
            "r": (0.1, 0.3, 0.5),
            "pearson_r": (0.1, 0.3, 0.5),
            "spearman_r": (0.1, 0.3, 0.5),
            "point_biserial_r": (0.1, 0.3, 0.5),
            "cramers_v": (0.1, 0.3, 0.5),
            "eta_squared": (0.01, 0.06, 0.14),
            "partial_eta_squared": (0.01, 0.06, 0.14),
        }
    )


@dataclass(frozen=True)
class ReportingHeuristics:
    required_sections: tuple[str, ...] = (
        "data_overview",
        "data_quality",
        "variable_profiles",
        "key_findings",
        "statistical_analyses",
        "recommendations",
    )
    heading_alias_map: dict[str, str] = field(
        default_factory=lambda: {
            "table_1": "data_overview",
            "baseline": "data_overview",
            "correlation": "statistical_analyses",
            "missing": "data_quality",
            "methodology": "recommendations",
            "limitation": "recommendations",
            "executive": "key_findings",
            "finding": "key_findings",
            "pipeline": "recommendations",
        }
    )
    quick_explore_banner: tuple[str, str] = (
        "Quick Explore — Not Audited",
        "此報告僅供快速概況探索，未完成 concept alignment、plan lock、collect_results 與 audit review。",
    )
    publishable_requires_significance: bool = True
    default_completion_target: str = "production_ready"


@dataclass(frozen=True)
class HeuristicPolicy:
    intake: IntakeHeuristics = field(default_factory=IntakeHeuristics)
    classification: ClassificationHeuristics = field(default_factory=ClassificationHeuristics)
    analysis: AnalysisHeuristics = field(default_factory=AnalysisHeuristics)
    reporting: ReportingHeuristics = field(default_factory=ReportingHeuristics)


DEFAULT_HEURISTIC_POLICY = HeuristicPolicy()
