"""Project-independent, hash-pinned discovery of the actual research surface.

The checked JSON is a declaration, not a readiness/permission/clinical verdict.
Regenerate with ``python -m rde.interface.mcp.analysis_catalog --write``. Runtime
reads need neither a dataset nor optional vendor/network availability probes.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import importlib
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).with_suffix(".json")
SOURCE_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "rde-analysis-catalog-v1"

GROUPS = [
    ("prepare", "準備研究", "理解來源、整理多表與規劃樣本數"),
    ("describe", "了解資料", "先看分布、缺失及變項關聯"),
    ("compare", "比較與量測", "比較組別、同人重複量測與測量工具"),
    ("model", "建立模型", "依研究問題與設計選擇解釋、存活或預測模型"),
    ("specialist", "專門領域", "接收可追溯的外部統合研究或基因體結果"),
    ("deliver", "探索與交付", "受約束的探索、完整成果、稽核與投稿圖"),
]

SPEC_TYPES = {
    "sample_size": ("rde.domain.models.sample_size", "SampleSizeSpec"),
    "comparison": ("rde.infrastructure.clinical.comparison_contract", "ComparisonSpec"),
    "stratified": ("rde.infrastructure.clinical.stratified_contract", "StratifiedSpec"),
    "imputation": ("rde.infrastructure.clinical.imputation_contract", "ImputationSpec"),
    "noninferiority": ("rde.infrastructure.clinical.noninferiority_contract", "NoninferioritySpec"),
    "repeated": ("rde.infrastructure.clinical.repeated_contract", "RepeatedSpec"),
    "diagnostic_accuracy": (
        "rde.infrastructure.clinical.measurement",
        "MeasurementSpec",
    ),
    "bland_altman": ("rde.infrastructure.clinical.measurement", "MeasurementSpec"),
    "cohens_kappa": ("rde.infrastructure.clinical.measurement", "MeasurementSpec"),
    "regression": ("rde.infrastructure.clinical.regression_contract", "RegressionSpec"),
    "weighting": ("rde.infrastructure.clinical.weighting_contract", "WeightingSpec"),
    "longitudinal": (
        "rde.infrastructure.clinical.longitudinal_contract",
        "LongitudinalSpec",
    ),
    "survival": ("rde.infrastructure.clinical.survival", "SurvivalSpec"),
    "prediction": ("rde.infrastructure.prediction.contract", "PredictionSpec"),
}


def canonical_bytes(value):
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        # JSON parsers (including JavaScript) retain the number, not whether it
        # was spelled 0 or 0.0. Keep schema values while hashing that same number.
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def declaration_hash(value):
    return sha256(
        canonical_bytes({k: v for k, v in value.items() if k != "catalog_sha256"})
    ).hexdigest()


def source_path(reference):
    """Resolve both editable src/ and installed wheel package layouts."""
    if (
        not isinstance(reference, str)
        or not reference.startswith("src/rde/")
        or not reference.endswith(".py")
        or ".." in Path(reference).parts
    ):
        raise ValueError("Invalid analysis catalog source reference")
    path = (SOURCE_ROOT / reference.removeprefix("src/")).resolve()
    if not path.is_relative_to((SOURCE_ROOT / "rde").resolve()):
        raise ValueError("Analysis catalog source reference escapes the installed package")
    return path


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=1024)
def _cached_source_hash(path, identity):
    value = sha256(path.read_bytes()).hexdigest()
    if _identity(path) != identity:
        raise ValueError("Analysis catalog source changed during verification")
    return value


def source_hash(reference):
    path = source_path(reference)
    return _cached_source_hash(path, _identity(path))


def source_inventory():
    return sorted(
        "src/" + path.relative_to(SOURCE_ROOT).as_posix()
        for path in (SOURCE_ROOT / "rde").rglob("*.py")
    )


def verify_source_declaration(catalog):
    manifest = catalog.get("declaration_sources")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Analysis catalog source declaration is missing; regenerate catalog")
    expected = {}
    for item in manifest:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("Invalid analysis catalog source declaration")
        reference, digest = item["path"], item["sha256"]
        source_path(reference)
        if reference in expected or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Invalid or duplicate analysis catalog source declaration")
        expected[reference] = digest
    if set(expected) != set(source_inventory()):
        raise ValueError("Analysis catalog source inventory changed; regenerate catalog")
    for reference, digest in expected.items():
        if source_hash(reference) != digest:
            raise ValueError(f"Analysis catalog source drift: {reference}; regenerate catalog")
    for family in catalog["families"]:
        for item in family["contract_sources"]:
            if expected.get(item["path"]) != item["sha256"]:
                raise ValueError(
                    "Analysis catalog family contract differs from the source declaration"
                )


def binding(tool, argument=None, selector=None):
    result = {"tool": tool}
    if argument:
        result["argument"] = argument
    if selector is not None:
        result["selector"] = selector
    return result


def method(identifier, label, *, selector=None, execution_kind="native"):
    result = {"id": identifier, "label": label, "execution_kind": execution_kind}
    if selector is not None:
        result["selector"] = selector
    return result


def _family(
    identifier,
    group,
    title,
    question,
    summary,
    methods,
    tools,
    roles,
    outputs,
    requirements,
    limitations,
    refs,
    kind="native",
):
    return {
        "id": identifier,
        "group_id": group,
        "title": title,
        "question": question,
        "summary": summary,
        "methods": methods,
        "execution": {
            "kind": kind,
            "availability": "not_probed",
            "requirements": requirements,
        },
        "bindings": [binding(t) if isinstance(t, str) else t for t in tools],
        "input_roles": [
            {"id": key, "label": label, "requirement": requirement}
            for key, label, requirement in roles
        ],
        "outputs": outputs,
        "requirements": requirements,
        "limitations": limitations,
        "contract_refs": refs,
    }


def family_declarations():
    """Human guidance binds stable engine families and actual public tools."""
    families = []

    def add(*args, **kwargs):
        families.append(_family(*args, **kwargs))

    locked = "完整選項須納入核准且鎖定的計畫，通過 readiness；來源與清理版本固定。"
    facts = "研究設計、時間、分析單位與代碼須有來源；未知不自動當成已確認。"
    clinical = "src/rde/interface/mcp/tools/clinical_tools.py"
    add(
        "data_understanding",
        "prepare",
        "資料盤點與品質",
        "這些檔案有哪些欄位與品質問題？",
        "匯入、欄位角色、分布與品質檢查先於分析。",
        [
            method("intake", "匯入與來源識別"),
            method("schema", "欄位角色"),
            method("quality", "品質檢查"),
        ],
        [
            "scan_data_folder",
            "run_intake",
            "build_schema",
            "profile_dataset",
            "assess_quality",
        ],
        [("source", "來源檔案", "保留完整來源與選定工作表")],
        ["來源與資料集 ID", "schema", "profile", "品質問題"],
        ["支援的資料格式與大小限制"],
        ["欄位命名與唯一值不是研究設計或病人獨立性的證明。"],
        [
            "src/rde/interface/mcp/tools/discovery_tools.py",
            "src/rde/interface/mcp/tools/profiling_tools.py",
        ],
    )
    add(
        "preparation",
        "prepare",
        "多表資料準備",
        "如何正確串聯多表並保留每一步人數？",
        "明訂分析單位、鍵、時間窗、納排、品質核准與逐列追溯。",
        [
            method("relational_preparation", "關聯與族群規格"),
            method("data_aggregation", "原生資料聚合與局部規則修訂"),
            method("cleaning", "鎖定計畫內的清理"),
        ],
        [
            binding("data_preparation", "request"),
            "get_dataset_version",
            "suggest_cleaning",
            "apply_cleaning",
        ],
        [
            ("sources", "來源清單", "每份来源綁定 SHA256、大小及資料表"),
            ("specification", "關聯與族群規格", "明訂單位、關聯、聚合、時間與缺失狀態"),
        ],
        [
            "品質與各階段分母",
            "配對例外",
            "逐列／逐格來源",
            "核准 release 與可攜 bundle",
        ],
        ["來源快照完整", "明確品質與個案核對後才 release"],
        [
            "一對多不直接做笛卡兒積；未配對不等同陰性。",
            "清理或新來源須產生可追溯版本。",
            "聚合依原生方法契約與具版本的局部規則操作；試算通過不等於研究核准。",
        ],
        [
            "src/rde/domain/models/preparation.py",
            "src/rde/domain/models/preparation_edit.py",
            "src/rde/infrastructure/preparation/aggregation.py",
            "src/rde/infrastructure/preparation/engine.py",
            "src/rde/infrastructure/preparation/workflow.py",
        ],
    )
    add(
        "sample_size",
        "prepare",
        "前瞻樣本數",
        "正式收案前需要多少可分析個案？",
        "以前瞻且可追溯的效果、變異與失訪假設規劃整數樣本數。",
        [
            method(x, label, selector={"design": x})
            for x, label in [
                ("independent_means", "兩獨立組平均數"),
                ("paired_means", "配對平均差"),
                ("independent_proportions", "兩獨立組比例"),
            ]
        ],
        [
            binding("draft_sample_size_plan", "planning_options"),
            "get_sample_size_plan",
            "approve_sample_size_plan",
            "run_sample_size_plan",
            "render_sample_size_publication",
        ],
        [
            (
                "assumptions",
                "規劃假設",
                "效果、變異或比例、alpha、power、配置與失訪及其來源",
            )
        ],
        ["最小整數樣本數", "收案數", "主／敏感度情境", "power 曲線"],
        ["核准精確計畫 SHA256", "獨立個案或獨立配對，雙側 superiority"],
        [
            "不做 observed post-hoc power。",
            "不支援群集、期中分析、非劣性或多主要終點。",
        ],
        [
            "src/rde/domain/models/sample_size.py",
            "src/rde/infrastructure/clinical/sample_size.py",
        ],
    )
    add(
        "descriptive",
        "describe",
        "描述性研究",
        "資料實際包含什麼、缺了多少？",
        "可以在研究背景仍未知時完成有明確界限的原始資料列描述。",
        [
            method("observed_rows", "原始列與缺失描述"),
            method("table_one", "Table 1"),
            method("variable", "單變項摘要"),
        ],
        [
            binding("run_descriptive_study", "descriptive_options"),
            "generate_table_one",
            "analyze_variable",
        ],
        [
            ("columns", "要描述的欄位", "實際存在的欄位"),
            ("identifiers", "可能的識別碼", "與 unresolved 明確列出"),
        ],
        ["逐欄分母", "缺失模式", "識別碼重複性", "缺失與五數摘要圖", "描述報告／Table 1"],
        [locked],
        ["observed_rows 不補值、不刪除、不做推論，不把資料列直接稱為病人人數。"],
        [
            "src/rde/infrastructure/adapters/descriptive_study.py",
            "src/rde/infrastructure/visualization/descriptive.py",
            "src/rde/interface/mcp/tools/analysis_tools.py",
        ],
    )
    add(
        "association",
        "describe",
        "基本關聯與比較",
        "哪些變項有關聯或組間差異？",
        "基礎探索的檢定與矩陣；正式設計优先使用嚴格的研究族群契約。",
        [
            method("compare_groups", "依資料條件選擇組間檢定"),
            method("correlation_matrix", "Pearson 相關矩陣與 VIF"),
        ],
        ["compare_groups", "correlation_matrix"],
        [("variables", "變項", "型態與分組／結果角色固定")],
        ["檢定結果", "相關矩陣", "有效個案與缺失紀錄"],
        [locked, facts],
        ["關聯不代表因果；多重探索不自動成為確認性結論。"],
        [
            "src/rde/interface/mcp/tools/analysis_tools.py",
            "src/rde/infrastructure/adapters/scipy_engine.py",
        ],
    )

    clinical_rows = [
        (
            "noninferiority",
            "compare",
            "連續結果非劣性",
            "依事前臨床margin，處置是否未比參照差超過可接受界限？",
            [("welch_mean", "Welch 連續結果非劣性", {"method": "welch_mean"})],
            [
                ("subject", "獨立個案", "唯一非空且每人一列"),
                ("treatment", "處置", "[參照,處置] 原碼與研究定義"),
                ("outcome", "連續結果", "原始單位、時間窗與臨床方向"),
                ("margin", "非劣性界值", "正margin、原單位及事前臨床依據，不依結果挑選"),
                ("population_definition", "分析族群", "由來源明確定義，工具不驗證ITT／PP資格"),
            ],
            [
                "共同完整個案與分組摘要",
                "benefit difference／Welch單側檢定",
                "單側信賴下限及NI結論",
                "完整限制及英文投稿圖",
            ],
            [
                "alpha為單側；confidence_level=1-alpha表示單側下限。計算完成不代表非劣性成立。",
                "不顯著優效不代表非劣性，NI未通過也不等於證明劣效。",
                "不支援二元、存活、配對、群集、調整模型、多終點或期中NI；不自動替換估計器。",
                "margin、assay sensitivity/constancy、ITT/PP及因果解讀仍須臨床核對。",
            ],
        ),
        (
            "stratified",
            "compare",
            "分層二元比較",
            "控制事前指定分層後，二元處置與結果是否相關？",
            [("cmh", "Cochran–Mantel–Haenszel 與 common OR", {})],
            [
                ("subject", "獨立個案", "唯一非空識別；同人多列不可當獨立"),
                ("treatment", "處置", "[參照,處置] 原碼與研究定義"),
                ("outcome", "二元結果", "[非事件,事件] 原碼、時間窗與研究定義"),
                ("strata", "分層", "完整 2–50 層，不能事後刪除空層或零格"),
            ],
            [
                "逐列納排與各層 2×2 表",
                "單一 CMH 假說",
                "MH common OR／RBG CI",
                "Tarone–Breslow–Day 診斷",
                "英文向量圖及完整報告",
            ],
            [
                "每人一列，共享完整個案；零邊際／空層拒絕，不加0.5。",
                "漸近 CMH 不作連續性校正；沒有 exact CMH、RR／RD 或分層 logistic。",
                "同質性未顯著或無法估計不證明同質；OR 不能直接稱因果療效。",
            ],
        ),
        (
            "imputation",
            "model",
            "多重插補與合併迴歸",
            "保留可插補個案後，固定迴歸的估計與不確定性如何？",
            [
                ("pmm_gaussian", "PMM＋OLS＋Rubin 合併", {"distribution": "gaussian"}),
                ("pmm_binomial", "PMM＋logistic＋Rubin 合併", {"distribution": "binomial"}),
            ],
            [
                ("subject", "獨立個案", "唯一非空；單層資料，n不乘插補份數"),
                ("columns", "插補規格", "連續／二元原碼、單位、可插補與條件預測因子逐欄明訂"),
                ("predictors", "分析因素", "固定加法 OLS/logistic 1–12 項"),
                ("missingness_basis", "缺失依據", "不由缺失比例推定MAR或把結構性缺失當可插補"),
            ],
            [
                "原始分母與可插補格追溯",
                "每份完成資料 CSV、seed 與 hash",
                "逐份模型與 Rubin 完整 covariance",
                "逐項 Wald 估計",
                "缺失／鏈診斷與完整個案比較",
                "英文向量圖及完整報告",
            ],
            [
                "statsmodels PMM：二元也採觀察 donor，不是 Bernoulli draws。",
                "Rubin 合併採漸近 normal Wald、逐項未校正；沒有 Barnard–Rubin 小樣本修正。",
                "沒有 MNAR/NARFCS、多層、序位、survival-specific MI 或任意模型合併。",
                "原始觀察格不改；分離、未收斂或不完整 m 明確失敗，不退回單次補值。",
                "traces與完整個案比較不能證明MAR、收斂或MNAR穩健。",
            ],
        ),
        (
            "comparison",
            "compare",
            "獨立組比較",
            "獨立組的平均、排序或風險差多少？",
            [
                ("welch_mean", "Welch 平均差", {"method": "welch_mean"}),
                ("rank", "排序比較", {"method": "rank"}),
                ("binary", "二元風險比較", {"method": "binary"}),
            ],
            [
                ("outcome", "结果", "明確尺度與單位"),
                ("group", "獨立組別", "事前指定對比與分析單位"),
            ],
            ["效果量與信賴區間", "多重比較策略", "有效個案清單"],
            ["不適用同一病人反覆出現而未處理的群聚資料。"],
        ),
        (
            "repeated",
            "compare",
            "配對與重複量測",
            "同一人的不同量測有何差異？",
            [
                ("paired_mean", "配對平均差", {"method": "paired_mean"}),
                ("signed_rank", "Wilcoxon 與 Friedman", {"method": "signed_rank"}),
            ],
            [
                ("subject", "個案", "獨立個案識別"),
                ("measurements", "重複量測", "2–8 個寬表欄位與預先指定對比"),
            ],
            ["配對效果量與 CI", "完整／逐對個案分母", "Friedman omnibus（適用時）"],
            ["不是 repeated-measures ANOVA；非等時距的長表追蹤請用 longitudinal。"],
        ),
        (
            "diagnostic_accuracy",
            "compare",
            "診斷準確度",
            "檢測對參考標準有多準？",
            [("diagnostic_accuracy", "固定閾值診斷評估", {})],
            [
                ("first", "參考標準", "獨立性、抽樣、參考陽性／陰性與不確定代碼"),
                ("second", "檢測", "二元檢測代碼或預先固定閾值"),
            ],
            ["2×2 計數", "敏感度／特異度與 CI", "抽樣限制"],
            ["不自動最佳化閾值；病例對照抽樣不能直接估母群預測值。"],
        ),
        (
            "bland_altman",
            "compare",
            "量測一致性",
            "兩種量測方式能否互換？",
            [("bland_altman", "Bland–Altman", {})],
            [
                ("first", "第一量測", "連續量測與單位"),
                ("second", "第二量測", "同人配對及事前可接受差異"),
            ],
            ["偏差", "一致性界限與 CI", "差值圖"],
            ["相關性高不代表一致性；一人多組配對不在本契約內。"],
        ),
        (
            "cohens_kappa",
            "compare",
            "分類評分一致性",
            "兩位評分者的分類是否一致？",
            [("cohens_kappa", "Cohen's kappa", {})],
            [
                ("first", "第一評分", "明確類別順序"),
                ("second", "第二評分", "同一獨立個案的分類"),
            ],
            ["列聯表", "kappa 與 CI", "一致率"],
            ["不涵蓋任意多評分者或自行推定 ordinal 距離。"],
        ),
        (
            "regression",
            "model",
            "迴歸模型",
            "調整指定共變項後，結果與哪些因素相關？",
            [
                (x, label, {"distribution": x})
                for x, label in [
                    ("gaussian", "連續結果"),
                    ("binomial", "二元結果"),
                    ("poisson", "計數"),
                    ("negative_binomial", "過度離散計數"),
                    ("ordinal", "次序結果"),
                ]
            ],
            [
                ("outcome", "結果", "分布、代碼與單位"),
                ("predictors", "解釋變項", "預先指定調整項、參考值與交互作用"),
            ],
            ["效果量與 CI", "設計矩陣與個案", "模型診斷", "研究圖表"],
            ["獨立觀測；不自動逐步篩選變項，不宣稱因果。"],
        ),
        (
            "weighting",
            "model",
            "傾向分數加權",
            "觀察研究在可測混雜調整後有何差異？",
            [(x, x, {"estimand": x}) for x in ("ATE", "ATT", "ATO")],
            [
                ("treatment", "二元暴露", "明確處理／參考代碼"),
                ("outcome", "結果", "二元或連續結果及基線混雜項"),
            ],
            ["平衡診斷", "權重／有效樣本量", "加權效果與 CI"],
            ["只支援明示觀察隊列與可測基線混雜；不能修復未測量混雜或 positivity 缺口。"],
        ),
        (
            "longitudinal",
            "model",
            "縱向模型",
            "同一個案隨時間的結果如何改變？",
            [
                ("gee", "GEE", {"method": "gee"}),
                (
                    "mixed",
                    "Gaussian mixed model",
                    {"method": "mixed", "distribution": "gaussian"},
                ),
            ],
            [
                ("subject", "個案識別", "不同個案互相獨立"),
                ("time", "時間", "明訂起點、單位與表示方式"),
                ("outcome", "結果", "GEE gaussian/binomial/poisson；mixed gaussian"),
            ],
            ["模型效果與 CI", "追蹤人數／列數", "診斷與預測軌跡"],
            ["不能把多筆同人資料當獨立人；mixed 尚非任意 GLMM。"],
        ),
        (
            "survival",
            "model",
            "存活與競爭事件",
            "多久發生事件，哪些因素與時間相關？",
            [
                (
                    "kaplan_meier",
                    "Kaplan–Meier",
                    {"covariates": [], "competing_values": []},
                ),
                ("cox", "Cox PH", {}),
                ("competing_risk", "Aalen–Johansen 累積發生率", {}),
            ],
            [
                ("time", "追蹤時間", "起點與單位明確"),
                ("event", "事件", "事件／設限／競爭事件代碼明確"),
            ],
            ["存活或累積發生曲線", "風險表", "Cox HR 與 PH 檢查（指定 covariates 時）"],
            [
                "每人一列、右設限；不是任意 recurrent-event 或 time-varying 模型。",
                "Cox 需指定 covariates；競爭事件需指定 competing_values。",
            ],
        ),
    ]
    for (
        identifier,
        group,
        title,
        question,
        methods,
        roles,
        outputs,
        limits,
    ) in clinical_rows:
        add(
            identifier,
            group,
            title,
            question,
            "先 inspect 實際資料與編碼，再按核准規格執行完整研究。",
            [
                method(mid, label, selector={"family": identifier, **selector})
                for mid, label, selector in methods
            ],
            [
                binding("inspect_clinical_study", "clinical_options", {"family": identifier}),
                binding("run_clinical_study", "clinical_options", {"family": identifier}),
            ],
            roles,
            outputs,
            [locked, facts],
            limits,
            [clinical, SPEC_TYPES[identifier][0].replace(".", "/") + ".py"],
        )
        families[-1]["contract_refs"][-1] = "src/" + families[-1]["contract_refs"][-1]
    add(
        "prediction",
        "model",
        "預測研究",
        "未來的新個案能否被可靠預測？",
        "將訓練、交叉驗證與保留驗證集分開，保留資料切分與個案憑據。",
        [
            method("binary", "二元預測", selector={"task": "binary"}),
            method("regression", "連續結果預測", selector={"task": "regression"}),
        ],
        [binding("run_prediction_study", "prediction_options")],
        [
            ("target", "預測目標", "時間與代碼固定"),
            ("predictors", "預測欄位", "在預測時間已可取得"),
            ("split", "資料切分", "random/group/temporal，避免個案或未來資訊洩漏"),
        ],
        ["訓練 CV", "保留集指標與 CI", "校準", "逐例預測", "適用時的 decision curve"],
        [locked, facts],
        [
            "候選模型為 linear/random_forest；不代表任意 AutoML。",
            "不可反覆看驗證集挑模型；DCA 另有單入口抽樣等前提。",
        ],
        [
            "src/rde/infrastructure/prediction/contract.py",
            "src/rde/interface/mcp/tools/prediction_tools.py",
        ],
    )
    from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
    from rde.infrastructure.adapters.clinical_engine import CLINICAL_METHODS
    from rde.infrastructure.adapters.analysis_delegator import LOCAL_ADVANCED_LITE

    # Each declaration is selected by a real dispatcher; unsupported legacy list
    # entries (e.g. kolmogorov_smirnov) must not become discovery claims.
    aliases = {}
    for alias, label in ScipyStatisticalEngine._TEST_ALIASES.items():
        aliases.setdefault(label, alias)
    basic = [aliases[label] for label in sorted(ScipyStatisticalEngine._TEST_DISPATCH)]
    advanced = sorted(
        set(LOCAL_ADVANCED_LITE)
        | set(CLINICAL_METHODS)
        | {"table_one", "descriptive", "learning_curve_cusum"}
    )
    methods = [
        method(
            x,
            ScipyStatisticalEngine._TEST_ALIASES.get(x, x),
            selector={"analysis_type": x},
        )
        for x in basic + advanced
    ]
    methods.append(
        method(
            "automl",
            "外部 AutoML",
            selector={"analysis_type": "automl"},
            execution_kind="optional_vendor",
        )
    )
    add(
        "advanced",
        "model",
        "進階與相容分析介面",
        "既有進階工具還有哪些可呼叫的方法？",
        "列出實際 dispatcher 方法；完整臨床研究優先使用對應嚴格 family。",
        methods,
        [binding("run_advanced_analysis"), "run_repeated_measures"],
        [
            ("analysis_type", "方法", "使用宣告的方法 ID"),
            (
                "method_arguments",
                "方法參數",
                "使用 tool_input_schemas 內的明確參數與各方法原生要求",
            ),
        ],
        ["方法結果／錯誤", "來源引擎紀錄", "分析成果與決策紀錄"],
        [locked, "AutoML 需另行啟用並可連線的 vendor"],
        [
            "外部引擎 availability 未探測；AutoML 沒有本地替代。",
            "API 結構不等於完整科學參數 schema，優先使用明確 study contract。",
            "舊 run_repeated_measures 僅 Wilcoxon/Friedman；不是 repeated ANOVA。",
            "各進階方法的診斷與投稿輸出完整度不同。",
        ],
        [
            "src/rde/infrastructure/adapters/scipy_engine.py",
            "src/rde/infrastructure/adapters/clinical_engine.py",
            "src/rde/infrastructure/adapters/analysis_delegator.py",
        ],
    )
    for identifier, title, question, prefix, refs, methods, roles, limits in [
        (
            "external_evidence",
            "統合研究結果",
            "如何保存並呈現外部統合分析的完整證據？",
            "evidence",
            [
                "src/rde/infrastructure/evidence/workflow.py",
                "src/rde/interface/mcp/tools/evidence_tools.py",
            ],
            [("evidence_receipt", "統合研究結果收據")],
            [("bundle", "外部結果 bundle", "核准計畫、來源、R 程式／版本與數字閉包")],
            ["RDE 匯入與渲染已計算的數字，不自行估計 meta-analysis 或 network meta-analysis。"],
        ),
        (
            "external_genomics",
            "基因體研究結果",
            "如何保存並呈現外部基因體分析的完整證據？",
            "genomics",
            [
                "src/rde/infrastructure/genomics/workflow.py",
                "src/rde/interface/mcp/tools/genomics_tools.py",
            ],
            [("genomics_receipt", "基因體結果收據")],
            [
                (
                    "bundle",
                    "外部結果 bundle",
                    "核准 counts、metadata、gene sets 角色與 R 計算閉包",
                )
            ],
            ["RDE 不直接計算 DESeq2；需要外部引擎先完成並產生符合契約的結果。"],
        ),
    ]:
        add(
            identifier,
            "specialist",
            title,
            question,
            "依精確來源 hash 匯入，從已保存數字產生研究報告與投稿圖。",
            [method(mid, label, execution_kind="external_receipt") for mid, label in methods],
            [
                f"import_{prefix}_source",
                f"get_{prefix}_source",
                f"render_{prefix}_study",
                f"render_{prefix}_publication",
            ]
            + (["evidence_arm_preparation"] if prefix == "evidence" else []),
            roles,
            ["不可變來源收據", "研究報告", "多格式圖", "独立投稿版本"],
            ["外部計算已完成", "完整来源、計畫核准與結果 hash 通過核對"],
            limits,
            refs,
            kind="external_receipt",
        )
    add(
        "autoresearch",
        "deliver",
        "受控自動探索",
        "可否在保留主要計畫下持續測試延伸問題？",
        "保存探索分支與佇列，每次任務固定資料與方法規格並可停止／恢復。",
        [method("branches", "探索分支"), method("durable_queue", "可保存探索佇列")],
        [
            "open_exploration_branch",
            "suggest_branch_experiments",
            "run_branch_experiment",
            "evaluate_branch",
            "promote_branch_to_plan_amendment",
            "discard_branch",
            "get_exploration_board",
            "start_autoresearch_run",
            "get_autoresearch_status",
            "stop_autoresearch_run",
            "resume_autoresearch_run",
            "run_autoresearch_next_task",
            "run_autoresearch_queue",
        ],
        [("scope", "探索範圍", "已鎖定主要計畫、白名單方法及固定資料版本")],
        ["逐次任務／錯誤與結果", "探索評估", "分支與主要計畫差異"],
        [locked],
        [
            "host 驅動佇列，不是背景自主伺服器。",
            "探索結果不能自動升格主要結論；需要新計畫與核准。",
        ],
        ["src/rde/interface/mcp/tools/branch_tools.py"],
    )
    add(
        "reporting",
        "deliver",
        "報告與投稿成果",
        "如何確認所有分析都有交代並輸出可追溯報告？",
        "收集結果、組裝報告、核對完整性，再產生圖文與交接。",
        [
            method("report", "報告與圖表"),
            method("audit", "稽核"),
            method("publication", "投稿圖版本"),
        ],
        [
            "collect_results",
            "assemble_report",
            "create_visualization",
            "export_report",
            "run_audit",
            "auto_improve",
            "export_final_report",
            "export_handoff",
            "verify_audit_trail",
            "get_publication_presets",
            "render_publication_figures",
            "render_branch_publication",
            "read_artifact",
        ],
        [("artifacts", "研究成果", "完整分析、分母、版本與來源 hash")],
        ["報告", "PDF／DOCX（已配置格式）", "SVG／PNG／PDF 投稿圖", "稽核與交接包"],
        ["各步驟成果完整且通過對應 workflow gate"],
        [
            "檔案生成不等於研究結論通過審查；缺少／失敗的分析須保留。",
            "字型、PDF renderer 與格式支援依部署條件。",
        ],
        [
            "src/rde/interface/mcp/tools/report_tools.py",
            "src/rde/infrastructure/preparation/reporting.py",
            "src/rde/infrastructure/adapters/docx_exporter.py",
            "src/rde/interface/mcp/tools/audit_tools.py",
            "src/rde/interface/mcp/tools/publication_tools.py",
        ],
    )
    # Stable novice order is independent of implementation loop order.
    order = [
        "data_understanding",
        "preparation",
        "sample_size",
        "descriptive",
        "association",
        "comparison",
        "stratified",
        "noninferiority",
        "repeated",
        "diagnostic_accuracy",
        "bland_altman",
        "cohens_kappa",
        "regression",
        "imputation",
        "weighting",
        "longitudinal",
        "survival",
        "prediction",
        "advanced",
        "external_evidence",
        "external_genomics",
        "autoresearch",
        "reporting",
    ]
    return sorted(families, key=lambda family: order.index(family["id"]))


def native_options_schema(family):
    """Project actual Python types; never silently substitute an empty schema.

    Dataclass .parse/.validate functions remain authoritative, including nested
    dict semantic constraints that Python annotations cannot express.
    """
    from pydantic import TypeAdapter

    if family in SPEC_TYPES:
        module, name = SPEC_TYPES[family]
        spec = getattr(importlib.import_module(module), name)
        schema = TypeAdapter(spec).json_schema()
        # Every listed native parser rejects unknown top-level options.
        schema["additionalProperties"] = False
        return (
            schema,
            f"{module}.{name}.parse; structural types only; native parse/validate also required",
        )
    if family == "preparation":
        from rde.domain.models.preparation import Specification

        return (
            Specification.model_json_schema(),
            "Specification.model_validate; full specification schema, not the outer operation request",
        )
    return (
        None,
        "Actual MCP tool input schema only; opaque object arguments require the referenced native contract and validator",
    )


async def build_catalog():
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.contracts import CONTRACTS

    tools = {tool.name: tool.input_schema for tool in await create_server().list_tools()}
    families = family_declarations()
    for family in families:
        names = list(dict.fromkeys(item["tool"] for item in family["bindings"]))
        if any(name not in tools or name not in CONTRACTS for name in names):
            raise ValueError(f"Catalog binding is not a registered, reviewed tool: {family['id']}")
        family["tool_input_schemas"] = {name: tools[name] for name in names}
        options, scope = native_options_schema(family["id"])
        family["schema_scope"] = scope
        if options is not None:
            family["options_schema"] = options
        family["contract_sources"] = []
        for reference in family["contract_refs"]:
            family["contract_sources"].append({"path": reference, "sha256": source_hash(reference)})
    catalog = {
        "schema": SCHEMA,
        "version": 1,
        "hash_scope": "complete_catalog_declaration",
        "hash_algorithm": "sha256(canonical UTF-8 JSON with sorted keys, no whitespace, integral floats normalized to integers, excluding catalog_sha256)",
        "source_verification": "All installed RDE Python sources are verified at discovery; optional dependencies/vendor runtime are not probed",
        "declaration_sources": [
            {"path": reference, "sha256": source_hash(reference)}
            for reference in source_inventory()
        ],
        "declaration_scope": "Server method declaration; not runtime availability, scientific validity, approval, or host-platform support",
        "selector_scope": "Selectors are dispatch fragments, never complete executable requests; satisfy schemas, native validators and workflow gates",
        "result_contract": "rde-result-v1; status/error/context/artifact identities; numerical completeness remains method-specific",
        "groups": [
            {
                "id": gid,
                "title": title,
                "description": description,
                "family_ids": [f["id"] for f in families if f["group_id"] == gid],
            }
            for gid, title, description in GROUPS
        ],
        "families": families,
    }
    return {**catalog, "catalog_sha256": declaration_hash(catalog)}


def load_catalog():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if catalog.get("schema") != SCHEMA or catalog.get("catalog_sha256") != declaration_hash(
        catalog
    ):
        raise ValueError("Analysis catalog declaration failed schema/hash verification")
    verify_source_declaration(catalog)
    return catalog


def get_catalog(family=None, detail=False):
    if type(detail) is not bool or (family is not None and not isinstance(family, str)):
        raise ValueError("family must be an exact family ID; detail must be boolean")
    catalog = load_catalog()
    if family is not None:
        selected = [item for item in catalog["families"] if item["id"] == family]
        if not selected:
            raise ValueError("Unknown analysis family: " + family)
        catalog["families"] = selected
    is_full = detail or family is not None
    if family is not None or not detail:
        catalog.pop("declaration_sources", None)
    if not is_full:
        for item in catalog["families"]:
            for key in (
                "options_schema",
                "tool_input_schemas",
                "contract_sources",
                "contract_refs",
                "schema_scope",
                "input_roles",
                "outputs",
                "requirements",
                "limitations",
            ):
                item.pop(key, None)
            item["execution"].pop("requirements", None)
            item["methods"] = [
                {key: method[key] for key in ("id", "label", "execution_kind")}
                for method in item["methods"]
            ]
            item["details_available"] = True
    # Response projection metadata is excluded from the complete declaration hash.
    return {
        **deepcopy(catalog),
        "selection": {"family": family},
        "detail": "full" if is_full else "summary",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--write",
        action="store_true",
        help="regenerate the checked canonical declaration",
    )
    action.add_argument(
        "--check", action="store_true", help="read-only source, schema and catalog drift check"
    )
    args = parser.parse_args()
    try:
        generated = asyncio.run(build_catalog())
        if args.check:
            if load_catalog() != generated:
                raise ValueError(
                    "Analysis catalog differs from current tools/schemas; review and regenerate"
                )
            print(
                f"Analysis catalog verified: {len(generated['families'])} families; {generated['catalog_sha256']}"
            )
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
    if args.write:
        CATALOG_PATH.write_text(
            json.dumps(generated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{CATALOG_PATH}: {generated['catalog_sha256']}")
    elif not args.check:
        print(json.dumps(generated, ensure_ascii=False, indent=2))
