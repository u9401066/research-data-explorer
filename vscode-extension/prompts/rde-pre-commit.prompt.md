---
description: "RDE 提交前檢查：同步文件、跑 pytest/pre-commit、確認治理檔與測試一致。"
agent: "agent"
tools: ['changes', 'codebase', 'problems', 'runCommands', 'search']
---

# RDE Pre-commit

請協助做提交前檢查，但不要自動 commit，除非使用者明確要求。

## 檢查順序

1. `git status --short`
2. 若改到治理或 workflow，檢查 `README.md`、`AGENTS.md`、`.github/copilot-instructions.md`、`.github/agent-control.yaml`
3. 跑 `python3 -m pytest -q`
4. 若有 pre-commit，跑 `pre-commit run --all-files`
5. 彙整失敗項目與建議的 commit message

## 特別注意

- 不要忽略 vendor-only failure，要標示是環境還是產品問題
- 不要建議略過 phase gate 測試
