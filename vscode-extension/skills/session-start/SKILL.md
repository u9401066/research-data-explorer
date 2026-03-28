---
name: session-start
description: "Session start initialization. Reads Memory Bank and restores pipeline context. Triggers: session start, 開始, hello, 繼續, 接著做, resume."
---

# Session Start

## 描述
Session 開始時載入 Memory Bank 並恢復 pipeline 上下文。

## 觸發條件
- Session 開始（自動）
- 「繼續上次的」「接著做」「resume」

## 執行流程

### Step 1: 載入 Memory Bank
依序讀取：
1. `memory-bank/productContext.md` — 專案上下文
2. `memory-bank/activeContext.md` — 上次的工作焦點
3. `memory-bank/systemPatterns.md` — 技術模式
4. `memory-bank/decisionLog.md` — 重要決策
5. `memory-bank/progress.md` — Done/Doing/Next

### Step 2: 載入 Pipeline 狀態
```
get_pipeline_status()
→ 目前 Phase、artifacts 狀態
```

### Step 3: 顯示恢復摘要

```
🔄 Session 恢復
- 專案: {project_name}
- Pipeline Phase: {current_phase}
- 上次進度: {last_activity}
- 建議下一步: {suggested_next_action}
```

### Step 4: 建議行動

| 情境 | 建議 |
|------|------|
| Phase 2 完成 | 「要做概念對齊嗎？」 |
| Phase 4 未鎖定 | 「分析計畫需要確認和鎖定」 |
| Phase 6 進行中 | 「上次分析到 X，繼續？」 |
| Phase 8 完成 | 「要做審計和改善嗎？」 |
| 全部完成 | 「要匯出 handoff 給 med-paper-assistant 嗎？」 |
