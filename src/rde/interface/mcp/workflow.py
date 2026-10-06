"""Read-only, server-derived actions for agents and host user interfaces.

Actions describe current prerequisites, never grant approval or replace the
mutation's own source/plan/method checks. Drafting and confirming are distinct.
"""

from __future__ import annotations

import hashlib
import json

from rde.application.pipeline import (
    PipelinePhase as P,
    REQUIRED_ARTIFACTS,
    PREREQUISITES,
    OPTIONAL_PHASES,
)
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.results import artifact_reference, project_record

PHASE_LABELS = dict(
    zip(
        P,
        [
            "建立研究",
            "資料收件",
            "欄位辨識",
            "研究問題與變項對應",
            "計畫草案",
            "方法與假設審閱",
            "計畫核准",
            "分析前提檢查",
            "分析執行",
            "結果彙整",
            "研究報告",
            "證據稽核",
            "報告改善",
        ],
    )
)


def workflow_actions(project, pipeline) -> dict:
    if project is None:
        value = {
            "contract": "rde-actions-v1",
            "project_id": None,
            "plan_locked": False,
            "sources": [],
            "artifacts": [],
            "actions": [
                {
                    "id": "create_project",
                    "label": "建立研究",
                    "tool": "init_project",
                    "phase": P.PROJECT_SETUP.value,
                    "status": "needs_input",
                    "blockers": [],
                    "required_facts": [{"field": "name", "label": "研究名稱", "provider": "user"}],
                    "requires_confirmation": False,
                    "can_automate": False,
                    "arguments": {},
                }
            ],
        }
        return _pin(value)
    store = ArtifactStore(project.artifacts_dir)
    saved = {}
    refs = []
    for phase, names in REQUIRED_ARTIFACTS.items():
        for name in names:
            path = store.get_path(phase, name)
            if path.is_file():
                refs.append(
                    artifact_reference(
                        project, path.relative_to(project.output_dir).as_posix(), path
                    ).model_dump()
                )
        saved[phase] = store.check_artifacts(phase)[0]
    ids = list(project.dataset_ids)
    dataset = ids[0] if len(ids) == 1 else None
    base = {"project_id": project.id}
    with_dataset = {**base, **({"dataset_id": dataset} if dataset else {})}
    actions = []

    def add(
        identity,
        label,
        tool,
        phase,
        *,
        arguments=None,
        facts=None,
        confirmation=False,
        complete=None,
        blockers=None,
    ):
        allowed, reason = pipeline.can_execute(phase)
        blocked = list(blockers or [])
        if not allowed:
            names = [
                label for candidate, label in PHASE_LABELS.items() if candidate.value in reason
            ]
            blocked.append(
                {
                    "code": "PHASE_PREREQUISITE",
                    "message": "請先完成並確認：" + "、".join(names or ["前一步驟"]) + "。",
                }
            )
        for required in PREREQUISITES.get(phase, set()):
            if not saved.get(required, False) and not (
                pipeline.is_quick_explore and required in OPTIONAL_PHASES
            ):
                blocked.append(
                    {
                        "code": "MISSING_ARTIFACT",
                        "message": f"尚缺{PHASE_LABELS[required]}的完整成果。",
                    }
                )
        result = pipeline.completed_phases.get(phase)
        done = (
            bool(result and result.success and saved.get(phase)) if complete is None else complete
        )
        fields = list(facts or [])
        if done:
            blocked = [item for item in blocked if item["code"] != "PLAN_LOCKED"]
        status = (
            "blocked"
            if blocked
            else "completed"
            if done
            else "needs_input"
            if fields
            else "needs_confirmation"
            if confirmation
            else "ready"
        )
        actions.append(
            {
                "id": identity,
                "label": label,
                "tool": tool,
                "phase": phase.value,
                "status": status,
                "blockers": blocked,
                "required_facts": fields,
                "requires_confirmation": confirmation,
                "can_automate": status == "ready" and not confirmation and tool is not None,
                "arguments": arguments if arguments is not None else dict(base),
            }
        )

    choose_dataset = (
        []
        if dataset
        else [{"field": "dataset_id", "label": "選擇本次研究資料", "provider": "user"}]
    )
    add(
        "intake",
        "檢查並匯入資料",
        "run_intake",
        P.DATA_INTAKE,
        arguments={**base, "directory": str(project.data_dir), "allow_pii": False},
    )
    add(
        "schema",
        "辨識資料欄位",
        "build_schema",
        P.SCHEMA_REGISTRY,
        arguments=with_dataset,
        facts=choose_dataset,
    )
    alignment = pipeline.completed_phases.get(P.CONCEPT_ALIGNMENT)
    aligned = bool(
        alignment and alignment.success and alignment.user_confirmed and saved[P.CONCEPT_ALIGNMENT]
    )
    question_facts = (
        []
        if project.research_question.strip()
        else [
            {
                "field": "research_question",
                "label": "想回答的研究問題與資料背景",
                "provider": "user",
            }
        ]
    )
    locked_block = (
        [{"code": "PLAN_LOCKED", "message": "此執行計畫已鎖定；變更請建立研究計畫修訂。"}]
        if pipeline.plan_locked
        else []
    )
    add(
        "draft_alignment",
        "讓研究助理整理問題與變項",
        "align_concept",
        P.CONCEPT_ALIGNMENT,
        arguments={
            **with_dataset,
            "research_question": project.research_question,
            "confirm": False,
        },
        facts=[*choose_dataset, *question_facts],
        complete=bool(alignment and saved[P.CONCEPT_ALIGNMENT]),
        blockers=locked_block,
    )
    add(
        "review_alignment",
        "確認研究問題與變項意義",
        "align_concept",
        P.CONCEPT_ALIGNMENT,
        arguments={**with_dataset, "confirm": True},
        confirmation=True,
        complete=aligned,
        blockers=locked_block
        + (
            []
            if alignment and saved[P.CONCEPT_ALIGNMENT]
            else [{"code": "DRAFT_REQUIRED", "message": "請先產生並閱讀變項對應草案。"}]
        ),
    )
    proposed = pipeline.completed_phases.get(P.CREATIVE_IDEATION)
    proposal_confirmed = bool(
        proposed and proposed.success and proposed.user_confirmed and saved[P.CREATIVE_IDEATION]
    )
    add(
        "draft_plan",
        "讓研究助理擬定分析計畫",
        "propose_analysis_plan",
        P.CREATIVE_IDEATION,
        arguments={**with_dataset, "confirm": False},
        facts=choose_dataset,
        blockers=locked_block,
    )
    add(
        "review_plan",
        "審閱分析方法與研究假設",
        "propose_analysis_plan",
        P.CREATIVE_IDEATION,
        arguments={**with_dataset, "confirm": True},
        confirmation=True,
        complete=proposal_confirmed,
        blockers=locked_block
        + (
            []
            if proposed and saved[P.CREATIVE_IDEATION]
            else [{"code": "DRAFT_REQUIRED", "message": "請先產生分析計畫草案。"}]
        ),
    )
    # register_analysis_plan performs phases 5 and 6 together; gate against phase 5.
    add(
        "lock_plan",
        "核准這個版本的計畫",
        "register_analysis_plan",
        P.PLAN_COMPLETENESS_REVIEW,
        arguments={**base, "confirm": True},
        confirmation=True,
        complete=pipeline.plan_locked,
        facts=[]
        if pipeline.plan_locked
        else [{"field": "analyses", "label": "審閱後的分析項目與方法", "provider": "agent"}],
    )
    add("readiness", "檢查分析前提", "check_readiness", P.PRE_EXPLORE_CHECK)
    readiness = pipeline.completed_phases.get(P.PRE_EXPLORE_CHECK)
    readiness_record = store.load(P.PRE_EXPLORE_CHECK, "readiness_checklist.json") or {}
    add(
        "execute",
        "執行核准的分析",
        None,
        P.EXECUTE_EXPLORATION,
        blockers=[]
        if readiness and readiness.success and readiness_record.get("all_passed") is True
        else [{"code": "READINESS_REQUIRED", "message": "分析前提尚未通過；請先處理檢查結果。"}],
    )
    add("collect", "彙整已完成的結果", "collect_results", P.COLLECT_RESULTS)
    report_blockers = []
    if not pipeline.is_quick_explore and not saved[P.COLLECT_RESULTS]:
        report_blockers.append(
            {"code": "RESULTS_REQUIRED", "message": "正式報告需要先完成分析與結果彙整。"}
        )
    add(
        "report",
        "產生研究報告",
        "assemble_report",
        P.REPORT_ASSEMBLY,
        arguments={**base, "allow_incomplete": pipeline.is_quick_explore},
        blockers=report_blockers,
    )
    add("audit", "檢查報告與分析證據", "run_audit", P.AUDIT_REVIEW)
    add("improve", "依檢查結果改善報告", "auto_improve", P.AUTO_IMPROVE)
    return _pin(
        {
            "contract": "rde-actions-v1",
            "project_id": project.id,
            "plan_locked": pipeline.plan_locked,
            "sources": project_record(project).model_dump()["sources"],
            "artifacts": refs,
            "actions": actions,
        }
    )


def _pin(value):
    value["revision"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return value
