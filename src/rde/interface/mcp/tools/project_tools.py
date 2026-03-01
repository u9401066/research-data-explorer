"""Project Tools — Phase 0 (Project Setup) & pipeline/log management.

All tools return markdown strings (medpaper pattern).
"""

from __future__ import annotations

from typing import Any


def register_project_tools(server: Any) -> None:
    """Register project management MCP tools."""

    @server.tool()
    def init_project(
        name: str,
        data_dir: str = "data/rawdata",
        research_question: str = "",
    ) -> str:
        """建立新的 EDA 探索專案（Phase 0）。

        建立專案目錄結構，初始化 project.yaml。

        Args:
            name: 專案名稱
            data_dir: 原始資料目錄路徑（預設: data/rawdata）
            research_question: 研究問題描述（可選，Phase 3 再填也行）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error,
        )

        log_tool_call("init_project", {"name": name, "data_dir": data_dir})

        if not name or not name.strip():
            return fmt_error("專案名稱不可為空。")

        try:
            import uuid
            from pathlib import Path
            from datetime import datetime

            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.domain.models.project import Project, ProjectStatus
            from rde.infrastructure.persistence import FileSystemProjectRepository
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            project_id = str(uuid.uuid4())[:8]
            output_dir = Path("data/projects") / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            project = Project(
                id=project_id,
                name=name,
                data_dir=Path(data_dir),
                output_dir=output_dir,
                research_question=research_question,
            )

            (output_dir / "artifacts").mkdir(exist_ok=True)
            (output_dir / "figures").mkdir(exist_ok=True)

            session = get_session()
            session.register_project(project)

            repo = FileSystemProjectRepository(Path("data/projects"))
            repo.save(project)

            store = ArtifactStore(project.artifacts_dir)
            store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {
                "id": project_id,
                "name": name,
                "data_dir": str(data_dir),
                "output_dir": str(output_dir),
                "research_question": research_question,
                "created_at": datetime.now().isoformat(),
            })

            pipeline = session.get_pipeline(project_id)
            pipeline.mark_started(PipelinePhase.PROJECT_SETUP)
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.PROJECT_SETUP,
                completed_at=datetime.now(),
                success=True,
                artifacts={"project.yaml": str(output_dir / "artifacts")},
            ))
            project.advance_to(ProjectStatus.PROJECT_SETUP)

            log_tool_result("init_project", f"created {project_id}")

            rq = research_question or "(未指定，Phase 3 再填)"
            return (
                f"✅ 專案建立成功！\n\n"
                f"📁 **專案名稱:** {name}\n"
                f"🔖 **專案 ID:** {project_id}\n"
                f"📂 **輸出目錄:** {output_dir}\n"
                f"🔬 **研究問題:** {rq}\n\n"
                f"**下一步:** 使用 `run_intake()` 執行完整收件流程，"
                f"或 `scan_data_folder()` 掃描資料目錄。"
            )

        except Exception as e:
            log_tool_error("init_project", e, {"name": name})
            return fmt_error(f"建立專案失敗: {e}")

    @server.tool()
    def get_pipeline_status(project_id: str | None = None) -> str:
        """查看目前分析專案的 11-Phase Pipeline 進度。

        Args:
            project_id: 專案 ID（可選，預設使用目前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, fmt_error, ensure_project_context,
        )

        log_tool_call("get_pipeline_status", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        from rde.application.session import get_session
        session = get_session()
        pipeline = session.get_pipeline(project.id)
        datasets = session.list_datasets()
        summary = pipeline.summary()

        completed = summary.get("completed", [])
        progress = summary.get("progress", "0%")
        mode = summary.get("mode", "full_audit")
        next_phase = summary.get("next_suggested", "done")
        plan_locked = "🔒 已鎖定" if summary.get("plan_locked") else "🔓 未鎖定"

        lines = [
            f"# 📊 Pipeline 進度 — {project.name}\n",
            f"- **模式:** {mode}",
            f"- **進度:** {progress}",
            f"- **分析計畫:** {plan_locked}",
            f"- **已載入資料集:** {len(datasets)} 個",
            f"- **研究問題:** {project.research_question or '(未指定)'}",
            "",
            "## 已完成的階段",
        ]
        if completed:
            for p in completed:
                lines.append(f"  ✅ {p}")
        else:
            lines.append("  (尚無)")

        if next_phase != "done":
            lines.append(f"\n**下一步:** `{next_phase}`")
        else:
            lines.append("\n**🎉 所有階段已完成！**")

        return "\n".join(lines)

    @server.tool()
    def get_decision_log(project_id: str | None = None) -> str:
        """查詢分析決策紀錄（decision_log.jsonl）。

        Args:
            project_id: 專案 ID
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, fmt_error, ensure_project_context,
        )

        log_tool_call("get_decision_log", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        from rde.application.session import get_session
        logger = get_session().get_logger(project.id)
        decisions = logger.read_decisions()

        if not decisions:
            return f"📋 **{project.name}** — 決策紀錄: 0 筆\n\n(Phase 6 尚未執行任何分析)"

        lines = [f"# 📋 決策紀錄 — {project.name}\n", f"共 {len(decisions)} 筆\n"]
        for i, d in enumerate(decisions, 1):
            ts = d.get("timestamp", "")[:19]
            action = d.get("action", "")
            tool = d.get("tool_used", "")
            rationale = d.get("rationale", "")
            result_summary = d.get("result_summary", "")
            lines.append(f"### #{i} [{ts}] {action}")
            lines.append(f"- **工具:** {tool}")
            lines.append(f"- **理由:** {rationale}")
            lines.append(f"- **結果:** {result_summary}\n")

        return "\n".join(lines)

    @server.tool()
    def get_deviation_log(project_id: str | None = None) -> str:
        """查詢計畫偏離紀錄（deviation_log.jsonl）。

        Args:
            project_id: 專案 ID
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, fmt_error, ensure_project_context,
        )

        log_tool_call("get_deviation_log", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        from rde.application.session import get_session
        logger = get_session().get_logger(project.id)
        deviations = logger.read_deviations()

        if not deviations:
            return f"📋 **{project.name}** — 偏離紀錄: 0 筆"

        lines = [f"# 📋 偏離紀錄 — {project.name}\n", f"共 {len(deviations)} 筆\n"]
        for i, d in enumerate(deviations, 1):
            ts = d.get("timestamp", "")[:19]
            lines.append(f"### #{i} [{ts}]")
            lines.append(f"- **原計畫:** {d.get('planned_action', '')}")
            lines.append(f"- **實際操作:** {d.get('actual_action', '')}")
            lines.append(f"- **偏離理由:** {d.get('reason', '')}")
            lines.append(f"- **影響評估:** {d.get('impact_assessment', '')}\n")

        return "\n".join(lines)

    @server.tool()
    def log_deviation(
        project_id: str | None = None,
        planned_action: str = "",
        actual_action: str = "",
        reason: str = "",
        impact_assessment: str = "",
    ) -> str:
        """記錄計畫偏離（Phase 6+ 偏離已鎖定計畫時必須呼叫）。

        Args:
            project_id: 專案 ID
            planned_action: 原計畫的操作
            actual_action: 實際執行的操作
            reason: 偏離理由
            impact_assessment: 影響評估
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_project_context,
        )

        log_tool_call("log_deviation", {
            "planned_action": planned_action, "actual_action": actual_action,
        })

        if not planned_action or not actual_action or not reason:
            return fmt_error("planned_action、actual_action、reason 都是必填欄位。")

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            logger = get_session().get_logger(project.id)

            entry = logger.log_deviation(
                phase="phase_06",
                planned_action=planned_action,
                actual_action=actual_action,
                reason=reason,
                impact_assessment=impact_assessment,
            )

            return fmt_success(
                f"偏離已記錄 (#{logger.deviation_count})",
                f"- **時間:** {entry.timestamp[:19]}\n"
                f"- **原計畫:** {planned_action}\n"
                f"- **實際操作:** {actual_action}\n"
                f"- **理由:** {reason}",
            )

        except Exception as e:
            log_tool_error("log_deviation", e)
            return fmt_error(f"記錄偏離失敗: {e}")
