"""Governed prospective planning; no fake intake or EDA phase advancement."""

import json

from rde.infrastructure.clinical import sample_size_workflow as workflow
from rde.interface.mcp.tools._shared import ensure_project_context, fmt_error


def render_edition(
    project, plan_id, run_id, expected_run_sha256, preset_id, edition_id, start_number, captions
):
    from rde.interface.mcp.tools.publication_tools import _create_verified_edition

    plan = workflow.read_plan(project, plan_id)
    run = workflow.read_run(project, plan, run_id, expected_run_sha256)
    source = project.output_dir / run["receipt_path"]
    result = workflow.read_sealed(project.output_dir / run["result_path"])
    edition = _create_verified_edition(
        project,
        source=source,
        study_artifact=run["receipt_path"],
        expected_record_sha256=workflow.file_hash(source),
        record={"plan_id": plan_id, "run_id": run_id, "figures": run["figures"]},
        result=result,
        preset_id=preset_id,
        edition_id=edition_id,
        start_number=start_number,
        captions=captions,
    )
    workflow.event(
        project,
        "sample_size_publication",
        plan_id=plan_id,
        run_id=run_id,
        run_sha256=expected_run_sha256,
        edition_id=edition_id,
        edition_sha256=edition["receipt_sha256"],
    )
    return edition


def register_sample_size_tools(server):
    def call(project_id, function, **arguments):
        ok, message, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(message)
        try:
            return json.dumps(function(project, **arguments), ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, KeyError, OSError) as error:
            return fmt_error(
                str(error),
                suggestion="Inspect the saved planning review; revise assumptions in a new plan rather than overwriting evidence.",
            )

    @server.tool()
    def draft_sample_size_plan(project_id: str, plan_id: str, planning_options: dict) -> str:
        """建立不依賴病人資料的前瞻樣本數草案；不計算或推進 EDA 階段。

        先 init_project，再以新的 UUID plan_id 保存不可變草案。
        planning_options 必須 design=independent_means/paired_means/independent_proportions、
        population、endpoint、time_horizon、outcome_unit、contrast（1−2）、group_labels=[1,2]、
        independent_units=true、normal_model=common_normal_sd/normal_differences/not_applicable、
        alpha、target_power、allocation=[正整數1,正整數2]（最簡比；paired=null）、max_evaluable。
        sources=[{id,kind:published/prior_study/clinical_judgment/engineering_fixture,citation,locator,justification}]；
        design_source_ids 指到來源。primary_scenario_id 固定主情境。
        scenarios 1..5 項：id、英文 label、loss_rate（共同缺失／不完整配對率）、
        effect_source_ids、nuisance_source_ids、loss_source_ids；mean 加 difference/sd，
        proportion 加 probabilities=[p1,p2]。SD 是共同組間 SD 或配對差值 SD。
        僅 prospective_superiority、two-sided、零差值虛無；無預設效應或數值假設。
        回傳完整草案 hash；用 get_sample_size_plan 讀完整人類審閱內容後才可核准。
        """
        return call(project_id, workflow.draft_plan, plan_id=plan_id, options=planning_options)

    @server.tool()
    def get_sample_size_plan(project_id: str, plan_id: str) -> str:
        """讀回完整前瞻設計、審閱文字、核准與執行成果，逐一驗證保存 hash。"""
        return call(project_id, workflow.get_plan, plan_id=plan_id)

    @server.tool()
    def render_sample_size_publication(
        project_id: str,
        plan_id: str,
        run_id: str,
        expected_run_sha256: str,
        preset_id: str,
        edition_id: str,
        start_number: int = 1,
        captions: dict[str, dict[str, str]] | None = None,
    ) -> str:
        """從核對過的樣本數數值另建不可變期刊圖稿；不重算，也不改原圖與主情境。

        expected_run_sha256 是成功 run_sample_size_plan 回傳的 receipt_sha256。
        新 edition_id 使用 UUID；preset_id 由 get_publication_presets 取得。
        captions 可依原圖序號修改 title/caption_en/explanation_zh，須審閱文字。
        保存六格式與圖說；相同圖稿 ID 重試僅驗證並取回既有版本。
        """
        return call(
            project_id,
            render_edition,
            plan_id=plan_id,
            run_id=run_id,
            expected_run_sha256=expected_run_sha256,
            preset_id=preset_id,
            edition_id=edition_id,
            start_number=start_number,
            captions=captions,
        )

    @server.tool()
    def approve_sample_size_plan(
        project_id: str, plan_id: str, expected_plan_sha256: str, review: dict
    ) -> str:
        """只在研究者已審閱明確草案後核准；不執行計算。

        review={reviewer,note,confirmations:{population_and_endpoint:true,
        assumptions_and_sources:true,method_and_independence:true,primary_scenario_allocation_and_loss:true}}。
        expected_plan_sha256 必須是本次實際審閱草案的完整 hash；核准不可覆寫。
        """
        return call(
            project_id,
            workflow.approve_plan,
            plan_id=plan_id,
            expected_plan_sha256=expected_plan_sha256,
            review=review,
        )

    @server.tool()
    def run_sample_size_plan(
        project_id: str,
        plan_id: str,
        expected_plan_sha256: str,
        expected_approval_sha256: str,
        run_id: str,
    ) -> str:
        """在固定草案與核准 hash 下執行整數樣本數計算，保存中文報告、表格與英文六格式圖。

        run_id 使用新 UUID；相同成功 run_id 僅核對並取回，不重算。
        未完成／失敗的 run_id 保留原紀錄，需要檢視後用新 ID 明確重試。
        計算上限、不支持設計、變更／損壞證據會停止，不自行降低目標或替代主情境。
        """
        return call(
            project_id,
            workflow.run_plan,
            plan_id=plan_id,
            expected_plan_sha256=expected_plan_sha256,
            expected_approval_sha256=expected_approval_sha256,
            run_id=run_id,
        )
