"""Prespecified clinical Phase 4 proposals; no exploratory breadth heuristic."""

from datetime import datetime
import json

from rde.application.pipeline import PhaseResult, PipelinePhase
from rde.domain.models.project import ProjectStatus
from rde.interface.mcp.tools._shared.project_context import persist_project
from rde.interface.mcp.tools.clinical_tools import parse_clinical_spec


STRATEGY = "prespecified_clinical_contract"


def clinical_blueprint(options):
    spec = parse_clinical_spec(options)
    return {
        "type": "run_clinical_study",
        "variables": spec.variables(),
        "rationale": "Execute only the complete prespecified clinical contract; no method expansion.",
        "execution_arguments": {"clinical_options": spec.to_dict()},
    }


def check_registered_clinical_proposal(proposal, analyses, *, dataset_id):
    """A reviewed typed draft cannot be registered with changed methods/settings."""
    if not isinstance(proposal, dict) or proposal.get("strategy") != STRATEGY:
        return
    if proposal.get("dataset_id") != dataset_id:
        raise ValueError("The current dataset differs from the confirmed clinical proposal.")
    if not proposal.get("confirmed") or not isinstance(analyses, list) or len(analyses) != 1:
        raise ValueError("Registration requires the confirmed single clinical proposal.")
    entry = analyses[0]
    if entry.get("type") != "run_clinical_study":
        raise ValueError("Registration cannot replace the confirmed clinical proposal with EDA.")
    normalized = clinical_blueprint(entry.get("execution_arguments", {}).get("clinical_options"))
    if normalized != proposal.get("plan_blueprint", [None])[0] or set(
        entry.get("variables", [])
    ) != set(normalized["variables"]):
        raise ValueError(
            "Clinical settings differ from the confirmed proposal; draft and review again."
        )


def _render(proposal):
    spec = proposal["plan_blueprint"][0]["execution_arguments"]["clinical_options"]
    return "\n".join(
        [
            "# 指定臨床研究提案（Phase 4）",
            "",
            f"- 研究家族：`{spec.get('family', 'survival')}`",
            f"- 確認狀態：{'已確認提案；仍須登錄及鎖定計畫' if proposal['confirmed'] else '待審閱；尚未確認或鎖定'}",
            "- 分析範圍：一個完整 `run_clinical_study` 契約；不按探索家族數量增加方法。",
            "- 執行順序：登錄同一份參數 → 來源與前提核對 → 指定方法 → 保存結果與報告。",
            "",
            "## 完整方法與研究定義",
            "```json",
            json.dumps(spec, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 核對範圍與限制",
            *[f"- {warning}" for warning in proposal["warnings"]],
        ]
    )


def propose_clinical_plan(project, entry, pipeline, store, options, *, confirm):
    """Preserve the existing draft→confirm Phase 4 gate with exact typed settings."""
    if options is None:
        raise ValueError("Confirming a clinical draft requires the same clinical_options.")
    blueprint = clinical_blueprint(options)
    available = {variable.name for variable in entry.dataset.variables}
    if set(blueprint["variables"]) - available:
        raise ValueError("Clinical proposal roles must all exist in the current dataset schema.")
    spec = blueprint["execution_arguments"]["clinical_options"]
    warnings = [
        "僅核對軟體契約與來源欄位；未執行資料前提檢查、統計估計或臨床驗證。",
        "來源編碼、研究族群、時間窗、獨立性與方法假設仍須研究審閱；樣本數與檢定力未由分析項目數量證明。",
        "執行時保留實際缺失、可估計性及方法診斷；提案確認不代表分析成功或研究假說成立。",
    ]
    if spec.get("family") == "imputation":
        warnings.append(
            "依指定欄位及 MAR 假設進行 MICE/PMM，固定模型以 Rubin 規則合併；m 份完成集不增加原始樣本數，不取代 MNAR 敏感度分析。"
        )
    elif spec.get("family") == "stratified":
        warnings.append(
            "依指定原碼及分層進行 CMH 與共同 OR；保留稀疏、零格與異質性診斷，不把 OR 當成 RR 或因果效果。"
        )
    elif spec.get("family") == "noninferiority":
        warnings.append(
            "僅指定 Welch 均差非劣性與單側下界；界值依據、方向及分析族群須事前指定，完成不代表證明非劣性，不自動建立 ITT/PP 族群。"
        )
    elif spec.get("family") == "matching":
        warnings.append(
            "固定 caliper 的 1:1 不放回最佳配對；目標為成功配對處置者，非原全體 ATT。配對群集 CR1 近似推論未宣稱完整校正估計傾向分數不確定性；保存所有未配對、平衡與品質限制。"
        )
    elif spec.get("family") == "target_trial":
        warnings.append(
            "僅來源綁定的基線點處置、單一 time zero、完整固定追蹤與原有 ATE／ATT／ATO 加權。鎖定及執行前須核對完整核准 preparation、全部個案時序與 eligible 集合；不得額外刪除缺失個案。提案不驗證因果識別，不支援動態／持續策略、時變處置、失訪校正或 CCW。"
        )
    schedule = [
        dict(
            order=1,
            step_id="run_clinical_study",
            stage="clinical_study",
            tool_name="run_clinical_study",
            analysis_label="run_clinical_study",
            variables=blueprint["variables"],
            depends_on=[],
            rationale="Exact typed contract, including its own population and missing-data policy.",
        )
    ]
    proposal = dict(
        strategy=STRATEGY,
        dataset_id=entry.dataset.id,
        research_question=project.research_question or "",
        confirmed=False,
        candidate_pool_size=1,
        selected=[blueprint],
        plan_blueprint=[blueprint],
        execution_schedule=schedule,
        enrichment_rounds=[],
        warnings=warnings,
        review=dict(
            scope="clinical_specification_review",
            status="specification_validated",
            numerical_evidence="not_executed",
            clinical_validation="not_performed",
            warnings=warnings,
        ),
    )
    phase = PipelinePhase.CREATIVE_IDEATION
    if confirm:
        saved = store.load(phase, "greedy_analysis_candidates.json")
        if saved != proposal:
            raise ValueError(
                "Clinical confirmation requires the exact existing unconfirmed draft, dataset and research question; draft and review again."
            )
        proposal.update(confirmed=True, confirmed_at=datetime.now().isoformat())
    content = _render(proposal)
    artifacts = {}
    for name, value in {
        "greedy_analysis_candidates.json": proposal,
        "greedy_analysis_candidates.md": content,
        "greedy_analysis_review.json": proposal["review"],
        "greedy_analysis_review.md": "# Clinical specification review\n\n" + "\n".join(warnings),
        "greedy_execution_schedule.json": schedule,
        "greedy_execution_schedule.md": "# Typed clinical execution\n\nOnly run_clinical_study with the registered clinical_options; no independent preprocessing or exploratory methods.",
        "greedy_plan_enrichment.json": [],
        "greedy_plan_enrichment.md": "# Plan enrichment\n\nNot requested for a prespecified clinical contract.",
        "greedy_statsmodels_base_analysis.py": "# Use RDE MCP run_clinical_study with the locked clinical_options.\n# No standalone analysis or preprocessing script is generated.\n",
    }.items():
        artifacts[name] = str(store.save(phase, name, value))
    pipeline.mark_started(phase)
    pipeline.mark_completed(
        PhaseResult(phase, datetime.now(), True, artifacts, user_confirmed=confirm)
    )
    project.advance_to(ProjectStatus.CREATIVE_IDEATION)
    persist_project(project)
    return content
