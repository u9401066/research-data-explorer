"""Prespecified clinical studies via the same locked, auditable RDE pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.clinical.survival import SurvivalSpec, digest, prepare_population
from rde.infrastructure.clinical.measurement import (
    MeasurementSpec,
    measurement_preflight,
    prepare_measurement,
    run_measurement,
)
from rde.infrastructure.clinical.longitudinal_contract import (
    LongitudinalSpec,
    longitudinal_preflight,
    prepare_longitudinal,
)
from rde.infrastructure.clinical.regression_contract import (
    RegressionSpec,
    regression_preflight,
    prepare_regression,
)
from rde.infrastructure.clinical.weighting_contract import (
    WeightingSpec,
    weighting_preflight,
    prepare_weighting,
)
from rde.infrastructure.clinical.comparison_contract import (
    ComparisonSpec,
    comparison_preflight,
    prepare_comparison,
)
from rde.infrastructure.clinical.repeated_contract import (
    RepeatedSpec,
    repeated_preflight,
    prepare_repeated,
)
from rde.infrastructure.clinical.imputation_contract import (
    ImputationSpec,
    imputation_preflight,
    prepare_imputation,
)
from rde.infrastructure.clinical.stratified_contract import (
    StratifiedSpec,
    stratified_preflight,
    prepare_stratified,
)
from rde.infrastructure.clinical.noninferiority_contract import (
    NoninferioritySpec,
    noninferiority_preflight,
    prepare_noninferiority,
)
from rde.infrastructure.clinical.matching import MatchingSpec, matching_preflight, prepare_matching
from rde.interface.mcp.tools.prediction_tools import atomic_json
from rde.infrastructure.clinical.target_trial_study import (
    TargetTrialSpec,
    persist_source_check,
    target_trial_preflight,
    run_target_trial,
    verify_target_trial_result,
    verify_target_trial_artifacts,
    verify_source_artifact,
)
from rde.infrastructure.clinical.target_trial_source import (
    validate_target_trial_source,
    target_trial_source_contract,
)


def planned_clinical_spec(entry):
    options = entry.get("execution_arguments", {}).get("clinical_options")
    return parse_clinical_spec(options)


def parse_clinical_spec(options):
    if isinstance(options, dict) and options.get("family") == "matching":
        return MatchingSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "target_trial":
        return TargetTrialSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "noninferiority":
        return NoninferioritySpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "imputation":
        return ImputationSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "stratified":
        return StratifiedSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "repeated":
        return RepeatedSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "comparison":
        return ComparisonSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "weighting":
        return WeightingSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "regression":
        return RegressionSpec.parse(options)
    if isinstance(options, dict) and options.get("family") == "longitudinal":
        return LongitudinalSpec.parse(options)
    if isinstance(options, dict) and options.get("family", "survival") != "survival":
        return MeasurementSpec.parse(options)
    return SurvivalSpec.parse(options)


def clinical_plan(store):
    entries = (store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}).get(
        "analyses", []
    )
    matching = [e for e in entries if isinstance(e, dict) and e.get("type") == "run_clinical_study"]
    if not matching:
        return None
    if len(entries) != 1 or len(matching) != 1:
        raise ValueError(
            "A clinical study plan requires exactly one complete prespecified study bundle."
        )
    return matching[0]


def clinical_records(store):
    records = []
    for name in sorted(store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)):
        if name.startswith("clinical_study_") and name.endswith(".json"):
            value = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
            if isinstance(value, dict) and value.get("result", {}).get("status") == "completed":
                records.append({**value, "artifact": name})
    return records


def verify_imputation_derived(record, root: Path):
    """Require the whole kernel inventory, including its matching result.json."""
    try:
        result = record["result"]
        inventory = record.get("derived_artifacts", [])
        expected = result.get("artifact_files", [])
        if not inventory or not expected:
            return False
        paths = [(root / item["path"]).resolve() for item in inventory]
        if len({p.parent for p in paths}) != 1 or len(set(paths)) != len(paths):
            return False
        directory = paths[0].parent
        listed = {path.name: item for path, item in zip(paths, inventory, strict=True)}
        expected_names = [item["path"] for item in expected]
        if len(set(expected_names)) != len(expected_names) or set(listed) != {
            *expected_names,
            "result.json",
        }:
            return False
        for path, item in zip(paths, inventory, strict=True):
            if (
                not path.is_relative_to(root.resolve())
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                return False
        for item in expected:
            if Path(item["path"]).name != item["path"]:
                return False
            path = directory / item["path"]
            if (
                listed[item["path"]]["sha256"] != item["sha256"]
                or path.stat().st_size != item["bytes"]
            ):
                return False
        return json.loads((directory / "result.json").read_text(encoding="utf-8")) == result
    except (OSError, ValueError, TypeError, KeyError):
        return False


def verify_clinical_artifacts(record, root: Path):
    artifacts = record.get("artifacts", [])
    result = record.get("result", {})
    if not artifacts or digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    ) != result.get("receipt_sha256"):
        return False
    if result.get("spec", {}).get("family") == "imputation" and not verify_imputation_derived(
        record, root
    ):
        return False
    if result.get("spec", {}).get("family") == "target_trial" and not verify_target_trial_artifacts(
        record, root
    ):
        return False
    for item in [*artifacts, *record.get("derived_artifacts", [])]:
        path = (root / item["path"]).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            return False
    return True


def register_clinical_tools(server: Any):
    @server.tool()
    def get_target_trial_contract(
        dataset_id: str, weighting_options: dict[str, Any] | None = None
    ) -> str:
        """取得核准資料的基線TTE完整typed schema、原生binding、prep規則與來源欄名；不回原始個案、不核准或估計。

        weighting_options 可提供完整原 weighting 規格，回傳正規化 weighting 與 Python canonical SHA，
        供 protocol.analysis.weighting_spec_sha256 使用；不可自行猜來源hash或研究定義。
        完成 protocol 後仍須 inspect_clinical_study、註冊鎖定計畫及正式run。
        """
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error

        ok, message, project, entry = ensure_phase_ready(
            PipelinePhase.CONCEPT_ALIGNMENT, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        try:
            result = target_trial_source_contract(project, entry.dataset.metadata)
            if weighting_options is not None:
                weighting = WeightingSpec.parse(weighting_options)
                result.update(
                    weighting=weighting.to_dict(), weighting_spec_sha256=digest(weighting.to_dict())
                )
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, KeyError, OSError) as error:
            return fmt_error(str(error))

    @server.tool()
    def inspect_clinical_study(dataset_id: str, clinical_options: dict[str, Any]) -> str:
        """計畫前核對臨床角色與分母；不估計模型或 p 值。target_trial 必須完整 weighting 與 typed protocol，核對已核准多表來源／所有個案時序，保存完整 source-check artifact。"""
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error

        ok, message, _project, entry = ensure_phase_ready(
            PipelinePhase.CONCEPT_ALIGNMENT, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        try:
            spec = parse_clinical_spec(clinical_options)
            source = entry.dataset.metadata
            if not source or not source.file_path.is_file():
                raise ValueError("The clinical source file is required.")
            if isinstance(spec, TargetTrialSpec):
                check = validate_target_trial_source(
                    _project, source, entry.dataframe, spec.weighting, spec.protocol
                )
                store = ArtifactStore(_project.artifacts_dir)
                artifact = persist_source_check(
                    check,
                    store.get_path(PipelinePhase.CONCEPT_ALIGNMENT, "unused").parent,
                    _project.output_dir,
                )
                return json.dumps(
                    {
                        **target_trial_preflight(spec, check, artifact),
                        "source_sha256": hashlib.sha256(source.file_path.read_bytes()).hexdigest(),
                        "sheet": source.sheet_name,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            if isinstance(
                spec,
                (
                    NoninferioritySpec,
                    ImputationSpec,
                    StratifiedSpec,
                    RepeatedSpec,
                    ComparisonSpec,
                    MeasurementSpec,
                    LongitudinalSpec,
                    RegressionSpec,
                    WeightingSpec,
                ),
            ):
                preflight = (
                    matching_preflight
                    if isinstance(spec, MatchingSpec)
                    else noninferiority_preflight
                    if isinstance(spec, NoninferioritySpec)
                    else imputation_preflight
                    if isinstance(spec, ImputationSpec)
                    else stratified_preflight
                    if isinstance(spec, StratifiedSpec)
                    else repeated_preflight
                    if isinstance(spec, RepeatedSpec)
                    else comparison_preflight
                    if isinstance(spec, ComparisonSpec)
                    else weighting_preflight
                    if isinstance(spec, WeightingSpec)
                    else regression_preflight
                    if isinstance(spec, RegressionSpec)
                    else longitudinal_preflight
                    if isinstance(spec, LongitudinalSpec)
                    else measurement_preflight
                )
                return json.dumps(
                    {
                        **preflight(entry.dataframe, spec),
                        "source_sha256": hashlib.sha256(source.file_path.read_bytes()).hexdigest(),
                        "sheet": source.sheet_name,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            frame, ledger, frame_hash, codes = prepare_population(entry.dataframe, spec)
            return json.dumps(
                dict(
                    schema="clinical-preflight-v1",
                    spec_sha256=digest(spec.to_dict()),
                    dataframe_sha256=frame_hash,
                    source_sha256=hashlib.sha256(source.file_path.read_bytes()).hexdigest(),
                    sheet=source.sheet_name,
                    n=len(frame),
                    events=int((frame.event_code == 1).sum()),
                    competing=int((frame.event_code > 1).sum()),
                    censored=int((frame.event_code == 0).sum()),
                    event_codes=codes,
                    input_rows=ledger["input_rows"],
                    outside_cohort=len(ledger["filter_excluded_data_rows"]),
                    missing_required=len(ledger["missing_excluded_data_rows"]),
                    strata=[
                        dict(
                            label=str(label),
                            n=len(group),
                            events=int((group.event_code == 1).sum()),
                        )
                        for label, group in frame.groupby("group", sort=True)
                    ],
                    scope="Eligibility and coding only; no fitted model, p-value or clinical assumption validation.",
                ),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError, KeyError, OSError) as error:
            return fmt_error(str(error))

    @server.tool()
    def run_clinical_study(dataset_id: str, clinical_options: dict[str, Any]) -> str:
        """執行鎖定的臨床研究：survival、diagnostic_accuracy、bland_altman、cohens_kappa、longitudinal、regression、weighting、comparison、repeated、imputation、stratified、noninferiority。

        target_trial={family:target_trial,weighting:{完整原weighting規格},protocol:{完整rde-baseline-target-trial-v1}}。
        僅一人一個基線點處置、固定完整horizon，核對核准bundle/release/完整trace/時序/全部eligible。
        cached reuse之前再次驗證來源與鎖定protocol；不支援時變/動態/失訪/CCW，不可退回普通weighting。
        頂層missing_strategy=listwise與multiplicity=none；額外驗證沒有任何eligible分析缺失排除。
        imputation 僅固定 continuous/binary PMM 與 gaussian/binomial 加法分析；須讀取完整 typed 規格。
        內層 columns 明列原始欄位、代碼、unit、impute 與 predictors，m/burn_in/between/k_pmm/seed 固定。
        頂層 missing_strategy=multiple_imputation、multiplicity=none；全部完成CSV與模型保存，原觀察格不變。
        Rubin covariance 配逐項漸近常態Wald；不冒稱Barnard-Rubin、MNAR或NARFCS。
        matching 僅1:1無放回logit-caliper最適配對＋pair-cluster CR1 t(G−1)近似推論；
        僅matched_treated族群、完整個案、不得依outcome調配對、不得聲稱全體ATT或AI2016校正。
        noninferiority 只允許 method=welch_mean，subject 必填、treatment_levels=[control,treatment]、
        outcome/outcome_unit/window/definition、direction=higher_is_better/lower_is_better、margin>0、
        margin_scale=outcome_unit、margin_basis、population_definition；內層complete_case，頂層listwise/none。
        confidence_level 是單側下限且=1-one_sided_alpha；top alpha 必須相同。binary NI 不支援且不得替換方法。
        NI未通過也是已完成的計算，讀取noninferiority.decision，不以completed推定非劣性。
        stratified 為事先固定 binary 原碼與 strata_levels 的CMH/MH OR；內層missing_strategy=complete_case，
        頂層listwise及multiplicity=none。禁止刪除空層、加0.5或用合併表代替；邊界OR與不可估CI明列。

        repeated 必須 subject、measurements=[{column,label}]（2..8 時點）、contrasts=[[first,second]]（1..28 明確方向），
        outcome_name、outcome_unit、outcome_definition、context、independent_subjects=true、same_outcome=true。
        method=paired_mean（primary_effect=mean_difference）或 signed_rank（primary_effect=rank_biserial）。
        case_strategy=complete/pairwise（兩時點只能 complete）；signed_rank 固定 bootstrap={resamples,seed}，可 omnibus=true（Friedman，至少三時點）。
        confidence_level、multiplicity=holm/bonferroni/fdr 及可選 cohort_filter 事先指定；全部比較執行，不依整體 p 篩選。
        區間逐項未校正，重抽樣保留整個受試者配對。共同描述與每對比較的分母分開保存；無法估計不代換成零寬區間。

        comparison 必須 outcome、group、group_levels（2..8 明確順序）、contrasts（1..12 事先指定兩組順序），
        method=welch_mean/rank/binary、primary_effect、outcome_unit、outcome_definition、outcome_window、
        context、study_design、independent_rows=true；可 subject、cohort_filter、confidence_level、omnibus。
        welch_mean 的主要效果 mean_difference；rank 為 rank_biserial，另指定 bootstrap={resamples,seed}。
        binary 指定 outcome_levels=[non-event,event]，primary_effect=proportion_difference/proportion_ratio/odds_ratio；
        病例對照或未指定抽樣只允許 odds_ratio。multiplicity=holm/bonferroni/fdr 涵蓋所有計畫對比與可選整體檢定。
        信賴區間逐項未校正，保存零／未定義／無限大／未能估計，不自動挑檢定、比較對象或效果尺度。
        clinical_options 必須逐項符合唯一計畫的 execution_arguments.clinical_options。
        必填 time、event、event_value、censor_value、time_origin、time_unit、independent_rows=true。
        可明列 group、subject、covariates、categorical_covariates、references、competing_values、risk_times、cohort_filter。
        同一完整個案集合提供 KM/競爭事件曲線、在險人數、Cox HR/CI/比例風險檢查、圖表與中文報告。
        不將競爭事件合併成目標事件，不自動挑選變項，不改寫既有成功結果。
        診斷／一致性須 first、second、context、independent_rows=true 及明確 diagnostic／agreement／categories。
        診斷固定陽性規則、參照標準與抽樣；一致性保留差異方向、單位、界限涵蓋率與臨床容許差異。
        longitudinal 必須指定 outcome、subject、time、time_unit、time_origin、outcome_unit、context、
        independent_subjects=true、method=gee/mixed、distribution=gaussian/binomial/poisson。
        GEE correlation=independence/exchangeable；Gaussian mixed 要 correlation=null，可 random_slope=true。
        time_mode=linear/categorical、time_reference、time_levels、group/group_reference、time_by_group 明訂。
        binomial 指定 positive/negative；Poisson 可指定 exposure/exposure_unit。固定 covariates、
        categorical_covariates、references、time_varying_covariates，不平均重複 subject/time、不自動選模。
        regression 必須 outcome、outcome_unit、context、independent_rows=true、study_design、distribution、predictors。
        distribution=gaussian/binomial/poisson/negative_binomial/ordinal；可 subject、cohort_filter、confidence_level。
        predictor 連續定義 column/kind=continuous/label/unit/reference/increment/knots（空或3..5明確節點）；
        類別定義 column/kind=categorical/label/reference/levels（完整原始類別）。interactions 為兩個主因素欄名的配對。
        binomial outcome_levels=[negative,positive]；ordinal 為3..8由低至高類別。計數可 exposure/exposure_unit。
        NB2 聯合估計 dispersion；序位採比例勝算，無截距；基底係數與臨床對比不得混稱。來源單位與參照固定。
        weighting 必須 treatment、treatment_levels=[control,treated]、treatment_definition、outcome、
        outcome_type=continuous/binary、outcome_unit、outcome_definition、time_origin、outcome_window、
        study_design=observational_cohort、context、estimand=ATE/ATT/ATO、independent_rows=true、pretreatment_covariates=true。
        covariates 沿用 regression predictor 完整型別，每項另需 pre_exposure_basis；可 interactions、subject、cohort_filter。
        binary outcome_levels=[negative,positive]；continuous 無 levels。單一 Hájek 平均差／機率差，聯合估計方程含 propensity 不確定性。
        不自動裁切／截斷、挑目標、配對、補值或把未確認追蹤者當作沒有事件；群集／時變處置／加權生存不屬此契約。
        """
        from rde.application.session import get_session
        from rde.interface.mcp.tools._shared import ensure_phase_ready, fmt_error, log_tool_error
        from rde.interface.mcp.tools.analysis_tools import _auto_log_decision
        from rde.interface.mcp.tools.report_tools import _upsert_visualization_manifest
        from rde.infrastructure.clinical.survival import run_survival
        from rde.infrastructure.clinical.longitudinal import run_longitudinal
        from rde.infrastructure.clinical.regression import run_regression
        from rde.infrastructure.clinical.weighting import run_weighting
        from rde.infrastructure.clinical.comparison import run_comparison
        from rde.infrastructure.clinical.repeated import run_repeated
        from rde.infrastructure.clinical.imputation import run_imputation
        from rde.infrastructure.clinical.stratified import run_stratified
        from rde.infrastructure.clinical.noninferiority import run_noninferiority
        from rde.infrastructure.clinical.matching import run_matching
        from rde.infrastructure.clinical.report import figures, markdown, tables

        ok, message, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION, dataset_id=dataset_id, require_dataset=True
        )
        if not ok:
            return fmt_error(message)
        store = ArtifactStore(project.artifacts_dir)
        parameters = {"dataset_id": dataset_id, "clinical_options": clinical_options}
        attempt = None
        derived_directory = None
        target_check = None
        target_artifact = None
        try:
            spec = parse_clinical_spec(clinical_options)
            if isinstance(spec, TargetTrialSpec):
                attempt = store.get_path(
                    PipelinePhase.EXECUTE_EXPLORATION,
                    f"clinical_attempt_{uuid.uuid4().hex[:16]}.json",
                )
                atomic_json(
                    attempt,
                    {
                        "status": "started",
                        "dataset_id": dataset_id,
                        "spec_sha256": digest(spec.to_dict()),
                        "family": "target_trial",
                    },
                )
            plan = clinical_plan(store)
            if plan is None or planned_clinical_spec(plan).to_dict() != spec.to_dict():
                raise ValueError(
                    "Clinical options must exactly match the single locked study plan."
                )
            if isinstance(spec, TargetTrialSpec):
                target_check = validate_target_trial_source(
                    project, entry.dataset.metadata, entry.dataframe, spec.weighting, spec.protocol
                )
                locked = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
                pin = locked.get("target_trial_source_check", {})
                if (
                    locked.get("locked") is not True
                    or pin.get("receipt_sha256") != target_check["receipt_sha256"]
                    or not verify_source_artifact(
                        pin.get("artifact", {}), project.output_dir, target_check
                    )
                ):
                    raise ValueError(
                        "TTE_LOCKED_SOURCE_CHECK: source validation or its implementation differs from the exact locked plan; review a new version."
                    )
            parameters["variables"] = spec.variables()
            frame_hash = (
                prepare_matching(entry.dataframe, spec)
                if isinstance(spec, MatchingSpec)
                else (None, None, target_check["weighting_preflight"]["dataframe_sha256"])
                if isinstance(spec, TargetTrialSpec)
                else prepare_noninferiority(entry.dataframe, spec)
                if isinstance(spec, NoninferioritySpec)
                else prepare_imputation(entry.dataframe, spec)
                if isinstance(spec, ImputationSpec)
                else prepare_stratified(entry.dataframe, spec)
                if isinstance(spec, StratifiedSpec)
                else prepare_repeated(entry.dataframe, spec)
                if isinstance(spec, RepeatedSpec)
                else prepare_comparison(entry.dataframe, spec)
                if isinstance(spec, ComparisonSpec)
                else prepare_weighting(entry.dataframe, spec)
                if isinstance(spec, WeightingSpec)
                else prepare_measurement(entry.dataframe, spec)
                if isinstance(spec, MeasurementSpec)
                else prepare_longitudinal(entry.dataframe, spec)
                if isinstance(spec, LongitudinalSpec)
                else prepare_regression(entry.dataframe, spec)
                if isinstance(spec, RegressionSpec)
                else prepare_population(entry.dataframe, spec)
            )[2]
            metadata = entry.dataset.metadata
            if not metadata or not metadata.file_path.is_file():
                raise ValueError(
                    "The immutable source file is required for the clinical study receipt."
                )
            source = dict(
                path=str(metadata.file_path),
                sha256=hashlib.sha256(metadata.file_path.read_bytes()).hexdigest(),
                sheet=metadata.sheet_name,
            )
            filename = f"clinical_study_{digest(dataset_id)[:16]}.json"
            previous = store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)
            from rde.interface.mcp.runtime import CLINICAL_REPLAY_ONLY

            if CLINICAL_REPLAY_ONLY.get() and (not previous or not previous.get("artifacts")):
                raise ValueError(
                    "CLINICAL_REPLAY_INCOMPLETE: the original live clinical evidence is missing or incomplete; refusing to refit or rebuild it from an invocation snapshot."
                )
            if previous and (
                previous["result"]["spec_sha256"] != digest(spec.to_dict())
                or previous["result"]["dataframe_sha256"] != frame_hash
                or any(previous.get("source", {}).get(k) != source[k] for k in ["sha256", "sheet"])
            ):
                raise ValueError(
                    "Saved clinical evidence has different source/specification. Create an explicit new analysis branch instead of replacing it."
                )
            if previous and digest(
                {k: v for k, v in previous["result"].items() if k != "receipt_sha256"}
            ) != previous["result"].get("receipt_sha256"):
                raise ValueError("Saved clinical numerical evidence failed integrity checks.")
            if (
                previous
                and isinstance(spec, TargetTrialSpec)
                and (
                    not verify_target_trial_result(previous["result"])
                    or previous["result"]["source_check"] != target_check
                    or not verify_source_artifact(
                        previous.get("target_trial_source_artifact", {}),
                        project.output_dir,
                        target_check,
                    )
                )
            ):
                raise ValueError(
                    "TTE_REUSE_SOURCE: saved protocol/source/numerical links differ; refusing to refit or relabel evidence."
                )
            if previous and isinstance(spec, ImputationSpec):
                if not verify_imputation_derived(previous, project.output_dir):
                    raise ValueError(
                        "Saved imputation derived inventory failed integrity checks; refusing to refit."
                    )
            if previous and previous.get("artifacts"):
                if not verify_clinical_artifacts(previous, project.output_dir):
                    raise ValueError(
                        "Saved clinical artifacts failed integrity checks; refusing to replace evidence."
                    )
                _auto_log_decision(
                    "run_clinical_study",
                    parameters,
                    "Reuse the verified locked clinical study without refitting.",
                    f"Saved declared analysis population n={previous['result']['n']}.",
                    artifacts=[filename],
                )
                if isinstance(spec, TargetTrialSpec):
                    atomic_json(
                        attempt,
                        {
                            "status": "reused",
                            "dataset_id": dataset_id,
                            "source_check_sha256": target_check["receipt_sha256"],
                            "numerical_receipt_sha256": previous["result"]["receipt_sha256"],
                        },
                    )
                return markdown(previous["result"]) + "\n已取回保存結果；本次沒有重新估計模型。\n"
            if isinstance(spec, TargetTrialSpec):
                target_artifact = (
                    previous["target_trial_source_artifact"]
                    if previous
                    else persist_source_check(
                        target_check,
                        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parent,
                        project.output_dir,
                    )
                )
            run_id = previous["run_id"] if previous else uuid.uuid4().hex[:16]
            attempt = attempt or store.get_path(
                PipelinePhase.EXECUTE_EXPLORATION, f"clinical_attempt_{run_id}.json"
            )
            derived_directory = (
                store.get_path(PipelinePhase.EXECUTE_EXPLORATION, f"imputation_{run_id}")
                if isinstance(spec, ImputationSpec)
                else None
            )
            if not previous:
                atomic_json(
                    attempt,
                    {
                        "status": "started",
                        "dataset_id": dataset_id,
                        "run_id": run_id,
                        "source": source,
                        "spec_sha256": digest(spec.to_dict()),
                    },
                )
            result = (
                previous["result"]
                if previous
                else (
                    run_matching(entry.dataframe, spec)
                    if isinstance(spec, MatchingSpec)
                    else run_target_trial(entry.dataframe, spec, target_check)
                    if isinstance(spec, TargetTrialSpec)
                    else run_noninferiority(entry.dataframe, spec)
                    if isinstance(spec, NoninferioritySpec)
                    else run_imputation(entry.dataframe, spec, derived_directory)
                    if isinstance(spec, ImputationSpec)
                    else run_stratified(entry.dataframe, spec)
                    if isinstance(spec, StratifiedSpec)
                    else run_repeated(entry.dataframe, spec)
                    if isinstance(spec, RepeatedSpec)
                    else run_comparison(entry.dataframe, spec)
                    if isinstance(spec, ComparisonSpec)
                    else run_weighting(entry.dataframe, spec)
                    if isinstance(spec, WeightingSpec)
                    else run_measurement(entry.dataframe, spec)
                    if isinstance(spec, MeasurementSpec)
                    else run_longitudinal(entry.dataframe, spec)
                    if isinstance(spec, LongitudinalSpec)
                    else run_regression(entry.dataframe, spec)
                    if isinstance(spec, RegressionSpec)
                    else run_survival(entry.dataframe, spec)
                )
            )
            if (
                not metadata.file_path.is_file()
                or hashlib.sha256(metadata.file_path.read_bytes()).hexdigest() != source["sha256"]
            ):
                raise ValueError(
                    "Clinical source file changed during execution; saved partial evidence cannot complete this plan."
                )
            if isinstance(spec, TargetTrialSpec):
                if (
                    validate_target_trial_source(
                        project, metadata, entry.dataframe, spec.weighting, spec.protocol
                    )
                    != target_check
                ):
                    raise ValueError(
                        "TTE_SOURCE_CHANGED: prepared source evidence changed during execution."
                    )
            record = dict(
                dataset_id=dataset_id, run_id=run_id, source=source, result=result, artifacts=[]
            )
            if isinstance(spec, TargetTrialSpec):
                record["target_trial_source_artifact"] = target_artifact
            if isinstance(spec, ImputationSpec):
                record["derived_artifacts"] = (
                    previous["derived_artifacts"]
                    if previous
                    else [
                        {
                            "path": str(path.relative_to(project.output_dir)),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for path in sorted(derived_directory.rglob("*"))
                        if path.is_file()
                    ]
                )
            # Persist numbers before visualization; a renderer failure never erases the estimate.
            atomic_json(attempt, record)
            final = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
            atomic_json(final, record)
            prefix = f"clinical_{run_id}"
            images = figures(result, project.output_dir / "figures", prefix)
            report = store.save(PipelinePhase.EXECUTE_EXPLORATION, f"{prefix}.md", markdown(result))
            table_dir = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parent
            figure_paths = [
                Path(path)
                for image in images
                for path in image.get("publication", {})
                .get("files", {"png": image["path"]})
                .values()
            ]
            paths = [
                report,
                *([project.output_dir / target_artifact["path"]] if target_artifact else []),
                *tables(result, table_dir, prefix),
                *figure_paths,
                *[
                    project.output_dir / item["path"]
                    for item in record.get("derived_artifacts", [])
                ],
            ]
            record["artifacts"] = [
                dict(
                    path=str(p.relative_to(project.output_dir)),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                )
                for p in paths
            ]
            record["figures"] = images
            for image in images:
                _upsert_visualization_manifest(
                    project,
                    plot_type=image["plot_type"],
                    variables=spec.variables(),
                    result_path=image["path"],
                    group_var=getattr(spec, "group", None),
                    stats_summary=image["caption"],
                )
            atomic_json(final, record)
            _auto_log_decision(
                "run_clinical_study",
                parameters,
                "Prespecified clinical study with exact source coding and family-specific missing-data population.",
                f"family={spec.family}; n={result['n']}; no automatic clinical validity or causal promotion.",
                artifacts=[filename, *[a["path"] for a in record["artifacts"]]],
            )
            return markdown(result) + f"\n**數值收據：** `{final}`\n"
        except Exception as error:
            if target_check is not None or (
                attempt and isinstance(locals().get("spec"), TargetTrialSpec)
            ):
                atomic_json(
                    attempt,
                    {
                        "status": "failed",
                        "dataset_id": dataset_id,
                        "family": "target_trial",
                        "error": str(error),
                        "source_check_sha256": target_check["receipt_sha256"]
                        if target_check
                        else None,
                        "source_artifact": target_artifact,
                    },
                )
            failure_artifacts = [attempt.name] if attempt and attempt.is_file() else []
            if derived_directory and derived_directory.is_dir():
                failure_artifacts += [
                    str(path.relative_to(project.output_dir))
                    for path in sorted(derived_directory.rglob("*"))
                    if path.is_file()
                ]
            get_session().get_logger(project.id).log_decision(
                phase=PipelinePhase.EXECUTE_EXPLORATION.value,
                action="run_clinical_study_failed",
                tool_used="run_clinical_study",
                parameters={**parameters, "execution_status": "failed"},
                rationale="Keep failure evidence without completing plan coverage.",
                result_summary=str(error),
                artifacts=failure_artifacts,
            )
            log_tool_error("run_clinical_study", error)
            return fmt_error(str(error))
