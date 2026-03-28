---
description: "針對 RDE repo 做快速 code review，優先抓 phase gate、DDD 邊界、audit 與 delegation 風險。"
agent: "agent"
tools: ['changes', 'codebase', 'problems', 'runCommands', 'search', 'usages']
---

# RDE Code Review

請用 review mindset 檢查最近變更，優先找真正會破壞 repository contract 的問題。

## Review focus

1. phase gate 或 artifact gate 是否被弱化
2. decision 或 deviation log 是否可能漏寫
3. DDD 依賴方向是否被打破
4. `automl-stat-mcp` delegation/fallback 是否被改壞
5. 測試是否足以覆蓋新行為
6. 文件是否仍與實作一致

## 輸出格式

- Findings first, ordered by severity
- 每個 finding 要有檔案位置與風險
- 若沒有 findings，明確說明 residual risk 或測試缺口
