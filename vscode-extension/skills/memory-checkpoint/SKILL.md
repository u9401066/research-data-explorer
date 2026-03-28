---
name: memory-checkpoint
description: "Save current pipeline state to memory bank as a checkpoint. Use when user wants to save progress or before closing session. Triggers: checkpoint, 存檔, 儲存進度, save progress, 記錄."
---

# Memory Checkpoint

## 描述
將目前的 pipeline 進度和分析狀態存入 Memory Bank，以便跨 session 恢復。

## 觸發條件
- 「存一下進度」「checkpoint」「記錄目前狀態」
- Session 結束前自動觸發（由 session-end skill）

## 保存內容

### activeContext.md
```markdown
## 目前狀態
- Pipeline Phase: {current_phase}
- 專案: {project_name}
- 資料集: {dataset_id}
- 最後操作: {last_tool_call}
- 未完成項目: {pending_items}

## 關鍵發現
- {finding_1}
- {finding_2}
```

### progress.md
```markdown
## 已完成
- Phase 0-N: {completed_phases}
- 分析: {completed_analyses}

## 進行中
- {current_task}

## 待辦
- {next_steps}
```

### decisionLog.md
- 從 `decision_log.jsonl` 擷取重要決策
- 從 `deviation_log.jsonl` 擷取偏離紀錄

## 恢復流程

下次 session 開始時：
1. 讀取 memory-bank/ 所有檔案
2. `get_pipeline_status()` 確認 pipeline 狀態
3. 告知用戶目前進度
4. 建議下一步
