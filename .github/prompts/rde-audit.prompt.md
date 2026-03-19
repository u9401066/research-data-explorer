---
description: "對 RDE 做治理與方法論稽核，確認 phase、artifact、log、report 與 vendor contract 是否一致。"
agent: "agent"
tools: ['changes', 'codebase', 'problems', 'runCommands', 'search', 'usages']
---

# RDE Audit Prompt

請把這個 repo 當成一個受治理的分析系統來審計，而不是一般應用程式。

## 稽核面向

1. workflow enforcement
2. append-only decision/deviation logs
3. audit artifact completeness
4. report sanitization and PII safeguards
5. delegated analysis contract and fallback behavior
6. 測試是否能證明上述行為

## 輸出

- 嚴重度排序的 findings
- 需要補的測試
- 需要補的文件
- 若只是不確定，明確標示為 validation gap
