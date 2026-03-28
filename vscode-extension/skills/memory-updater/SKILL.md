---
name: memory-updater
description: "Update Memory Bank files when significant changes occur. Triggers: update memory, 更新 memory bank, sync memory, 同步."
---

# Memory Bank Updater

## 描述
當專案發生重要變更時，同步更新 Memory Bank。

## 觸發條件
- 自動觸發：重大架構或流程決策後
- 手動觸發：「更新 memory bank」「同步 memory」

## 更新規則

| 檔案 | 何時更新 | 內容 |
|------|----------|------|
| `activeContext.md` | 每次 Phase 轉換 | 目前焦點、進行中任務 |
| `progress.md` | 每個 Phase 完成時 | Done/Doing/Next |
| `decisionLog.md` | 重要分析決策 | 決策 + 理由 |
| `productContext.md` | 專案範圍變更 | 產品上下文更新 |
| `systemPatterns.md` | 發現新模式 | 技術模式記錄 |
| `architect.md` | 架構變更 | 架構決策記錄 |

## 格式

### decisionLog.md 格式
```
[YYYY-MM-DD HH:MM:SS] - {決策摘要}
- 背景: {為什麼需要做決策}
- 選項: {考慮過的方案}
- 決定: {最終選擇}
- 理由: {選擇的原因}
```

### progress.md 格式
```
## Done
- [x] Phase 0: Project initialized
- [x] Phase 1: Data intake completed

## Doing
- [ ] Phase 2: Building schema

## Next
- Phase 3: Concept alignment
```
