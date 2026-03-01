# Git Workflow Bylaw

> Version: 1.0.0 | 依據：CONSTITUTION.md Article II §1

## §1 分支策略

| 分支 | 用途 | 保護 |
| ---- | ---- | ---- |
| `main` | 穩定版本 | 禁止直接 push |
| `develop` | 開發整合 | PR review |
| `feature/*` | 功能開發 | 無 |
| `fix/*` | Bug 修復 | 無 |

## §2 Commit 規範

使用 Conventional Commits 格式：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Type 列表

| Type | 用途 |
| ---- | ---- |
| `feat` | 新功能 |
| `fix` | Bug 修復 |
| `refactor` | 重構（不改行為） |
| `docs` | 文件更新 |
| `test` | 測試 |
| `chore` | 構建/工具 |
| `pipeline` | Pipeline 流程變更 |
| `hook` | Hook/Constraint 變更 |

### Scope 列表

| Scope | 對應 |
| ---- | ---- |
| `domain` | Domain layer |
| `app` | Application layer |
| `infra` | Infrastructure layer |
| `mcp` | MCP tools |
| `automl` | automl-stat-mcp 整合 |
| `phase-N` | Pipeline Phase N |

### 範例

```
feat(mcp): add propensity score delegation to automl

Pipeline Phase 6 now delegates propensity score matching to
automl-stat-mcp when service is available, with ScipyEngine
fallback.

Closes #42
```

## §3 Pre-commit Hooks

### 必要 hooks（透過 .pre-commit-config.yaml）

1. **ruff**: lint + format
2. **rde-decision-log-integrity**: H-010 append-only 檢查
3. **rde-pii-scan**: H-004/H-006 PII 掃描
4. **rde-artifact-gate**: H-008 artifact 完整性
5. **rde-report-sanitize**: H-006 報告清除

### 安裝

```bash
pip install pre-commit
pre-commit install
```

### 跳過規則

`--no-verify` 僅在以下情況允許：
- CI/CD 系統自動 commit（如文件自動生成）
- 已確認誤報並在 commit message 中說明理由

## §4 Data 檔案

### 不得 commit 的內容

- 原始資料檔案（`data/rawdata/` 在 `.gitignore`）
- 含 PII 的任何檔案
- 大於 50MB 的檔案

### 允許 commit 的內容

- `data/projects/*/project.yaml`
- `data/projects/*/artifacts/` (不含原始資料)
- `data/projects/*/decision_log.jsonl`
- `data/projects/*/deviation_log.jsonl`
- 報告輸出（經 H-006 清除後）
