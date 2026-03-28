---
name: session-end
description: "End-of-session cleanup and checkpoint. Use when user says goodbye or session is ending. Triggers: 結束, bye, session end, 下次見, 先這樣, 收工."
---

# Session End

## 描述
Session 結束時的清理和檢查點保存，確保下次可以無縫接續。

## 觸發條件
- 「先這樣」「下次見」「結束」「bye」「收工」

## 執行流程

### Step 1: Pipeline 狀態摘要
```
get_pipeline_status()
→ 目前 Phase、已完成項目、待辦項目
```

### Step 2: 檢查未保存的工作
- decision_log 最後寫入時間
- 是否有未完成的分析
- 是否有未確認的概念對齊或計畫

### Step 3: Memory Bank 同步
觸發 memory-checkpoint skill：
- 更新 activeContext.md（目前狀態）
- 更新 progress.md（Done/Doing/Next）
- 如有重要決策 → 更新 decisionLog.md

### Step 4: 摘要回覆

```
📋 Session 摘要
- 專案: {project_name}
- 目前 Phase: {current_phase}
- 本次完成:
  - {completed_items}
- 下次建議:
  - {next_steps}

✅ Memory Bank 已同步
```

## 下次啟動

agent 開始新 session 時應：
1. 讀取 memory-bank/
2. 顯示上次摘要
3. 建議從哪裡繼續
