# Research Data Explorer

Research Data Explorer，簡稱 RDE，是一個把資料探索流程做成可約束、可審計、可再現的 MCP 伺服器專案。

它的核心不是「幫你自動分析」，而是「限制代理一定要照經得起審視的方法學流程分析」。

這個 repo 目前已經把以下事情接起來：

- 11-phase auditable EDA pipeline
- hard constraints 與 soft constraints
- plan lock 與 artifact gate
- append-only decision log / deviation log
- automl-stat-mcp 委派分析
- 報告、審計、handoff package 匯出

英文版入口說明請見 [README.md](README.md).

## 這個 Repo 在約束什麼

這個專案不是只靠提示詞要求 Copilot 聽話，而是用程式與 pipeline 狀態實際限制它。

關鍵治理文件：

- [AGENTS.md](AGENTS.md)
- [.github/copilot-instructions.md](.github/copilot-instructions.md)
- [SPEC.md](SPEC.md)
- [CONSTITUTION.md](CONSTITUTION.md)
- [.github/agent-control.yaml](.github/agent-control.yaml)

這次也補上讓 VS Code agent mode 真正吃到 repo 規則的配套檔：

- [.vscode/settings.json](.vscode/settings.json)
- [.github/agents](.github/agents)
- [.github/prompts](.github/prompts)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

關鍵實作位置：

- MCP server 入口: [src/rde/__main__.py](src/rde/__main__.py)
- MCP tool 註冊: [src/rde/interface/mcp/server.py](src/rde/interface/mcp/server.py)
- pipeline state machine: [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py)
- append-only decision log: [src/rde/application/decision_logger.py](src/rde/application/decision_logger.py)
- 委派分析邏輯: [src/rde/infrastructure/adapters/analysis_delegator.py](src/rde/infrastructure/adapters/analysis_delegator.py)
- vendor gateway: [src/rde/infrastructure/adapters/automl_gateway.py](src/rde/infrastructure/adapters/automl_gateway.py)

## 11-Phase 約束流程

完整工作流如下：

1. Phase 0: `init_project`
2. Phase 1: `run_intake`
3. Phase 2: `build_schema`、`profile_dataset`
4. Phase 3: `align_concept(confirm=true)`
5. Phase 4: `register_analysis_plan(confirm=true)`
6. Phase 5: `check_readiness`
7. Phase 6: 執行分析工具
8. Phase 7: `collect_results`
9. Phase 8: `assemble_report`
10. Phase 9: `run_audit`
11. Phase 10: `auto_improve`、`export_handoff`、`verify_audit_trail`

### 你真正會被哪些規則卡住

這些規則不是建議，是會影響能不能往下執行。

#### Hard Constraints

- H-001: 檔案大小必須小於 500MB
- H-002: 檔案格式必須在白名單內
- H-003: 樣本量不足時不能做統計分析
- H-004: 偵測到疑似 PII 預設拒絕載入
- H-005: 報告組裝前要過完整性檢查
- H-006: 輸出前要清除敏感路徑資訊
- H-007: Phase 6 前一定要有已鎖定的 plan
- H-008: 前一 phase artifact 不完整不能進下一 phase
- H-009: Phase 6 分析操作要寫 decision log
- H-010: decision log 與 deviation log 是 append-only

#### Soft Constraints

這些不一定阻擋你，但 agent 會提醒：

- 常態性與有母數/無母數選擇
- 多重比較校正
- 缺失模式檢查
- 高共線性警告
- 效果量是否完整
- 檢定力與敏感度分析建議

## Copilot 在這裡怎麼被約束

如果代理是透過這個 repo 提供的 MCP tools 工作，它會同時受到四層限制：

1. 規範層
   - [AGENTS.md](AGENTS.md)、[.github/copilot-instructions.md](.github/copilot-instructions.md)、[CONSTITUTION.md](CONSTITUTION.md)
2. Pipeline 層
   - [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py) 會檢查 phase prerequisite、plan lock、artifact gate
3. Tool 層
   - [src/rde/interface/mcp/tools](src/rde/interface/mcp/tools) 在每個 tool 入口驗證前置條件
4. Audit 層
   - [src/rde/application/decision_logger.py](src/rde/application/decision_logger.py) 會保留決策與偏離紀錄

也就是說，這不是「叫 Copilot 自律」，而是「讓它不符合流程時就過不了」。

## 怎樣完成受約束的 Phase

### 最推薦的操作順序

如果你要完整、穩健、可稽核的流程，請照這個順序用：

1. `init_project`
2. `run_intake`
3. `build_schema`
4. `profile_dataset`
5. `align_concept(confirm=true)`
6. `register_analysis_plan(confirm=true)`
7. `check_readiness`
8. `compare_groups` / `correlation_matrix` / `run_advanced_analysis`
9. `collect_results`
10. `assemble_report`
11. `run_audit`
12. `auto_improve`
13. `export_handoff`
14. `verify_audit_trail`

### 每個階段的實際重點

#### Phase 0-2

目的是把資料安全地帶進來，並建立 schema。

- `run_intake` 會做格式、大小、PII 初篩
- `build_schema` 會建立欄位型別與基礎統計
- `profile_dataset` 會產生更完整的 profiling 檢視

#### Phase 3-4

這是最重要的約束點。

- `align_concept(confirm=true)` 讓研究問題對齊到實際欄位
- `register_analysis_plan(confirm=true)` 把後面允許做的分析鎖定下來

如果你不做這兩步，後面 Phase 6 的完整受約束分析就不成立。

#### Phase 5

`check_readiness` 會檢查：

- 樣本量是否足夠
- 是否有 PII
- plan 是否真的鎖定
- 前面 artifact 是否完整
- 常態性、缺失、共線性提醒

#### Phase 6

這裡是正式探索執行層：

- `compare_groups`
- `analyze_variable`
- `correlation_matrix`
- `generate_table_one`
- `run_advanced_analysis`
- `create_visualization`

這些操作會寫入 decision log；如果偏離已鎖定計畫，應該用 `log_deviation` 記錄原因。

#### Phase 7-10

- `collect_results` 彙整結果與 publishable items
- `assemble_report` 組裝完整 EDA 報告
- `run_audit` 評估完整性、計畫遵循、效果量、可再現性
- `auto_improve` 針對 audit 結果補做可自動修補的項目
- `export_handoff` 匯出給下游 repo 使用

## 怎樣善用 MCP

### 1. 啟動 RDE MCP Server

先安裝本 repo：

```bash
python3 -m pip install -e .
```

啟動 MCP server：

```bash
python3 -m rde
```

### 2. 啟動 automl-stat-mcp

如果你要用進階統計或 AutoML 委派，另外啟動 vendor 服務：

```bash
cd vendor/automl-stat-mcp
docker compose --profile ml up -d
```

### 3. 建議的 VS Code MCP 設定

可以用這樣的設定：

```json
{
  "servers": {
    "research-data-explorer": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "rde"]
    },
    "automl-stat-mcp": {
      "type": "sse",
      "url": "http://localhost:8002/sse"
    }
  }
}
```

### 4. 問 Copilot 的方式也要對

如果你想讓代理盡量維持在受治理流程中，建議這樣下指令：

```text
我有一個 CSV，請用完整 11-phase auditable workflow。
不要跳過 concept alignment 和 plan lock。
Phase 5 沒完成前不要做進階分析。
如果要偏離計畫，請記錄 deviation。
```

如果你是在 VS Code 直接用 agent mode，建議保持 [.vscode/settings.json](.vscode/settings.json)、[.github/agents](.github/agents)、[.github/prompts](.github/prompts) 與治理文件同步，否則 editor 端能看到的規則會落後於 repo 真實約束。

## 目前已驗證到什麼程度

這個 repo 不是只有單元測試，還做過 live vendor contract 與真實 dry run。

### 測試層

- 全 repo 測試用 `python3 -m pytest -q`
- 重要測試：
  - [tests/test_pipeline_integration.py](tests/test_pipeline_integration.py)
  - [tests/test_analysis_delegation.py](tests/test_analysis_delegation.py)
  - [tests/test_advanced_analysis_formatting.py](tests/test_advanced_analysis_formatting.py)
  - [tests/test_vendor_automl_contract_integration.py](tests/test_vendor_automl_contract_integration.py)

### 實跑 artifact 範例

最小 full-gate dry run：

- 專案目錄: [data/projects/e45af361](data/projects/e45af361)
- 結果摘要: [data/projects/e45af361/artifacts/phase_07_collect_results/results_summary.json](data/projects/e45af361/artifacts/phase_07_collect_results/results_summary.json)

heart_disease Phase 0-10 dry run：

- 專案目錄: [data/projects/12aafc56](data/projects/12aafc56)
- 最終摘要: [data/projects/heart_disease_phase0_10_final_summary.json](data/projects/heart_disease_phase0_10_final_summary.json)
- audit report: [data/projects/12aafc56/artifacts/phase_09_audit_review/audit_report.json](data/projects/12aafc56/artifacts/phase_09_audit_review/audit_report.json)
- handoff package: [data/projects/12aafc56/artifacts/handoff_package](data/projects/12aafc56/artifacts/handoff_package)

## 已知限制

目前這個 repo 已能完整約束 pipeline 與保存 audit trail，但 vendor 端仍有一個你應該知道的現況：

- 某些 `run_advanced_analysis` payload 在 heart_disease 這份資料上仍可能被 vendor endpoint 回 422
- 發生時會 fallback 到本地引擎，並把原因寫成 artifact，不會默默失敗

這個例子可以直接看：

- [data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json](data/projects/12aafc56/artifacts/phase_06_execute_exploration/advanced_analysis_automl.json)

所以目前最精確的描述是：

1. 11-phase 約束流程可完整執行
2. audit trail、report、handoff 都可以產出
3. vendor 委派能力已整合，但特定 AutoML payload 仍有 live 422 契約落差要再修

## Repo 結構

```text
src/rde/                         核心應用與 MCP tools
tests/                           回歸、整合、vendor 契約測試
vendor/automl-stat-mcp/          重量級分析引擎
data/projects/                   每次分析的 artifacts 輸出
memory-bank/                     專案記憶與脈絡文件
```

## 開發與驗證

安裝開發依賴並跑測試：

```bash
python3 -m pip install -e .[dev]
python3 -m pytest -q
```

如果你有修改治理、phase 流程或審計邏輯，請至少同步檢查：

1. [SPEC.md](SPEC.md)
2. [CONSTITUTION.md](CONSTITUTION.md)
3. [AGENTS.md](AGENTS.md)
4. [.github/copilot-instructions.md](.github/copilot-instructions.md)
5. 實作與測試
