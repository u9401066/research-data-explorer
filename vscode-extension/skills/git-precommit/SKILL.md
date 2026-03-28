---
name: git-precommit
description: "Pre-commit orchestration workflow for RDE. Ensures pipeline integrity, PII scanning, and Memory Bank sync before git commit. Triggers: commit, push, 提交, 準備 commit, git commit, pre-commit, 推送."
---

# Git 提交前工作流（RDE 特化版）

## 描述
協調 Git 提交前的所有驗證工作，包括 RDE pipeline guard 和標準品質檢查。

## 觸發條件
- 「準備 commit」「要提交了」「git commit」「推送」

## 法規依據
- 憲法：CONSTITUTION.md Article II §1
- 子法：.github/bylaws/git-workflow.md
- hooks：.pre-commit-config.yaml

## 執行流程

```
┌─────────────────────────────────────────────────────────┐
│              RDE Git Pre-Commit Orchestrator             │
├─────────────────────────────────────────────────────────┤
│  Step 1: pipeline-guard    [必要] Pipeline 狀態驗證      │
│  Step 2: log-integrity     [必要] Decision log 完整性    │
│  Step 3: pii-scan          [必要] PII / 敏感路徑掃描     │
│  Step 4: report-sanitize   [條件] 報告清除敏感資訊       │
│  Step 5: memory-sync       [可選] Memory Bank 同步       │
│  Step 6: lint-format       [自動] Ruff lint + format     │
│  Step 7: commit-prepare    [最終] 準備提交               │
└─────────────────────────────────────────────────────────┘
```

## 各步驟詳細說明

### Step 1: Pipeline Guard (H-007, H-008)
```bash
python scripts/pipeline_guard.py data/projects/<project> --strict
```
- 檢查 artifact gate（不可跳過 Phase）
- 檢查 plan lock（Phase 6+ 需鎖定計畫）
- 如有問題 → 阻止 commit

### Step 2: Log Integrity (H-010)
```
scripts/hooks/check_log_integrity.py
```
- 確認 decision_log.jsonl 只有新增
- 確認 deviation_log.jsonl 只有新增
- 刪除或修改已有記錄 → 阻止 commit

### Step 3: PII Scan (H-004, H-006)
```
scripts/hooks/pii_scan.py
```
- 掃描所有輸出檔案（.md, .json, .csv, .html）
- email、電話、ID 號碼、病人識別碼 → 警告
- Windows/Mac/Linux 使用者路徑 → 警告

### Step 4: Report Sanitize (H-006)
```
scripts/hooks/report_sanitize.py
```
- 僅對報告檔案（eda_report、final_report 等）
- 檢查絕對路徑、credential、token

### Step 5: Memory Bank 同步 (可選)
- 更新 memory-bank/ 目錄
- 記錄當前 pipeline 狀態到 activeContext.md

### Step 6: Lint & Format (自動)
```
ruff check --fix .
ruff format .
```

### Step 7: Commit Prepare
- `git add` 被修改的檔案
- 確認 commit message 格式

## 安裝

```bash
pip install pre-commit
pre-commit install
```

安裝後，每次 `git commit` 都會自動執行上述檢查。
