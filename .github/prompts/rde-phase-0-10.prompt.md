---
description: "用 RDE 的完整 11-phase workflow 規劃並執行一次受治理的分析流程。"
agent: "agent"
tools: ['codebase', 'problems', 'runCommands', 'search']
---

# RDE Full Pipeline

請依照這個 repo 的 11-phase auditable workflow 工作，不要跳過治理步驟。

## 必須遵守

1. 先讀 `README.md`、`.github/copilot-instructions.md`、`.github/agent-control.yaml`、`AGENTS.md`
2. 清楚標示目前是 Phase 0 到哪一個 phase
3. Phase 3 `align_concept()` 必須 `confirm=true`
4. Phase 4 `register_analysis_plan()` 必須 `confirm=true`
5. Phase 6 前要確認 plan 已鎖定且 readiness 完成
6. 若偏離 plan，要明確記錄 deviation
7. 回答中引用 artifact 路徑與測試或實作來源

## 產出格式

- 目前 phase 與完成條件
- 執行步驟
- 產出 artifact
- 卡住點與原因
- 下一步
