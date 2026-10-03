"""Fixed external evidence workflow, separate from patient-level EDA phases."""

import json

from rde.infrastructure.evidence import workflow
from rde.interface.mcp.tools._shared import ensure_project_context, fmt_error


def render_edition(
    project,
    source_id,
    render_id,
    expected_study_sha256,
    preset_id,
    edition_id,
    start_number,
    captions,
    display_dictionary=None,
):
    from rde.interface.mcp.tools.publication_tools import _create_verified_edition

    with workflow.locked(project):
        record, result = workflow.read_study(project, source_id, render_id, expected_study_sha256)
        source = workflow.safe_path(project.output_dir.resolve(), record["receipt_path"])
        dictionary_table = (
            workflow.load_json(
                workflow.safe_path(
                    workflow.source_directory(project, source_id), "source-table.json"
                )
            )
            if display_dictionary is not None
            else None
        )
        edition = _create_verified_edition(
            project,
            source=source,
            study_artifact=record["receipt_path"],
            expected_record_sha256=workflow.file_hash(source),
            record={
                "source_id": source_id,
                "render_id": render_id,
                "figures": record["figures"],
                "source": result["source"]["source"],
                "dictionary_source_table": dictionary_table,
            },
            result=result,
            preset_id=preset_id,
            edition_id=edition_id,
            start_number=start_number,
            captions=captions,
            display_dictionary=display_dictionary,
        )
        # Check the complete source closure again, not only the top-level study record.
        workflow.read_study(project, source_id, render_id, expected_study_sha256)
        workflow.event(
            project,
            "render_evidence_publication",
            source_id=source_id,
            render_id=render_id,
            edition_id=edition_id,
            receipt_sha256=edition["receipt_sha256"],
        )
        return edition


def register_evidence_tools(server):
    def call(project_id, function, **arguments):
        ok, message, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(message)
        try:
            return json.dumps(function(project, **arguments), ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, KeyError, OSError) as error:
            return fmt_error(
                str(error),
                suggestion="Review the saved source/attempt. Do not overwrite evidence; use a new render ID after a failed or interrupted rendering.",
            )

    @server.tool()
    def evidence_arm_preparation(project_id: str, request: dict) -> str:
        """固定原始 binary trial arms、審閱納排／分母／補值與零事件策略，核准後換算。

        request={"op":"contract"} 取得嚴格 JSON schema 與方法；其餘操作依序
        inspect 原始格線 → draft → read 完整 plan/grid/review → approve → execute → read result。
        受信任 adapter 將原檔放在 project.output_dir 下的
        incoming/evidence-arms/<preparation_id>/<filename>，不接受任意絕對路徑。
        草案不計算效應；來源、欄位、納排、方法改動必須另建新草案。
        inspect/read 為固定 SHA256 的文字分頁，續頁須 expected_text_sha256；完整讀完才審核。
        本流程不擬合統合分析、不推進個案資料 EDA 階段、不證明臨床來源正確。
        """
        from rde.infrastructure.evidence import arm_workflow

        if request == {"op": "contract"}:
            return json.dumps(arm_workflow.dispatch(None, request), ensure_ascii=False)
        return call(project_id, arm_workflow.dispatch, raw_request=request)

    @server.tool()
    def import_evidence_source(project_id: str, source_id: str, expected_bundle_sha256: str) -> str:
        """驗證並凍結已核准的外部 R 文獻整合結果，不执行統計或推進 EDA 階段。

        init_project 後，受信任的 Workbench adapter 在該專案 output_dir 的
        incoming/evidence/<source_id>/bundle.json 準備 evidence-source-bundle-v1。
        source_id 為 canonical UUID；expected_bundle_sha256 固定實際 bundle bytes。
        必須含原始資料、解析表、schema、核准前計畫原 bytes、已核准計畫、options、
        完整納排及 pinned R input/script/execution/output hashes/numeric receipt。
        每次取回驗證全部來源；相同 ID 不覆寫。此工具不核准研究或證明文獻真實性。
        """
        return call(
            project_id,
            workflow.import_source,
            source_id=source_id,
            expected_bundle_sha256=expected_bundle_sha256,
        )

    @server.tool()
    def get_evidence_source(project_id: str, source_id: str) -> str:
        """重啟後驗證保存的全部文獻來源與圖稿；列出完成、失敗及中斷的出圖嘗試。"""
        return call(project_id, workflow.get_source, source_id=source_id)

    @server.tool()
    def render_evidence_study(
        project_id: str, source_id: str, expected_source_sha256: str, render_id: str
    ) -> str:
        """從固定外部數值產生英文六格式研究圖及中文解釋；不重新估計模型。

        expected_source_sha256 是 import_evidence_source 回傳的 receipt_sha256。
        render_id 為新 UUID；相同完成 ID 僅驗證取回。失敗／中斷保留原嘗試，
        明確用新 ID 可由原數值重新出圖，無須重新執行 R。
        """
        return call(
            project_id,
            workflow.render_study,
            source_id=source_id,
            expected_source_sha256=expected_source_sha256,
            render_id=render_id,
        )

    @server.tool()
    def render_evidence_publication(
        project_id: str,
        source_id: str,
        render_id: str,
        expected_study_sha256: str,
        preset_id: str,
        edition_id: str,
        start_number: int = 1,
        captions: dict[str, dict[str, str]] | None = None,
        display_dictionary: dict | None = None,
    ) -> str:
        """另建不可變文獻投稿圖版，改期刊樣式、圖號與圖說但固定所有研究數值。

        expected_study_sha256 是 render_evidence_study 的 receipt_sha256。
        新 edition_id 為 UUID；preset 由 get_publication_presets 取得。
        captions 以原圖序號為 key，接受 title/caption_en/explanation_zh；須研究者審閱。
        display_dictionary 固定比較表來源與審閱版本；同一治療跨欄意義必須相同。
        effect/se 為 log OR、log RR 或原 MD 單位；不得改標成另一個數值尺度。
        同 ID 同請求讀回已存版次，不覆寫原圖、不重新分析。
        """
        return call(
            project_id,
            render_edition,
            source_id=source_id,
            render_id=render_id,
            expected_study_sha256=expected_study_sha256,
            preset_id=preset_id,
            edition_id=edition_id,
            start_number=start_number,
            captions=captions,
            display_dictionary=display_dictionary,
        )
