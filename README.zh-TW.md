# Research Data Explorer

RDE 是一個以 MCP server 與 VS Code harness 實作的可審計 EDA 工作流程。它不是讓 agent 自由寫 notebook 或臨時 pandas 腳本，而是要求 agent 在受治理的工具鏈裡完成資料收件、schema、概念對齊、分析計畫、執行、報告、audit 與 handoff。

正式網站：<https://u9401066.github.io/research-data-explorer/>

英文入口請見 [README.md](README.md)。

## i18n / 文件同步

- 英文總覽：[README.md](README.md)
- 繁體中文總覽：[README.zh-TW.md](README.zh-TW.md)
- Agent 操作契約：[AGENTS.md](AGENTS.md)
- VS Code Extension 說明：[vscode-extension/README.md](vscode-extension/README.md)

當 governance、phase 編號、release 驗證證據、no-Docker 行為或 Codex/VSIX 啟動方式改變時，請同步更新以上文件、[CHANGELOG.md](CHANGELOG.md) 與 `memory-bank/`。

## 目前真實程式碼快照

這份 README 與網站目前對齊下列實作，而不是只沿用舊文件描述：

| 合約面向 | 程式碼來源 | 目前事實 |
| --- | --- | --- |
| Public workflow | [src/rde/application/pipeline/__init__.py](src/rde/application/pipeline/__init__.py) | `PipelinePhase` 定義 13 個 phase，從 `phase_00_project_setup` 到 `phase_12_auto_improve` |
| MCP server registration | [src/rde/interface/mcp/server.py](src/rde/interface/mcp/server.py) | `create_server()` 註冊 9 組 tool modules |
| MCP tool surface | [src/rde/interface/mcp/tools](src/rde/interface/mcp/tools) 與 [vscode-extension/package.json](vscode-extension/package.json) | 目前 49 個 expected MCP tools，與實際 `@server.tool()` 註冊合計一致 |
| Agent control contract | [.github/agent-control.yaml](.github/agent-control.yaml) | phase controls、override flags、audit paths、delegation、UX harness、core goal contract |
| VSIX harness | [vscode-extension/src/extension.ts](vscode-extension/src/extension.ts) 與 [vscode-extension/package.json](vscode-extension/package.json) | MCP provider、`@rde` chat participant、Command Palette 指令、Codex config helper、optional automl check |
| Report readiness | [src/rde/interface/mcp/tools/report_tools.py](src/rde/interface/mcp/tools/report_tools.py) | `minimum_complete`、`academic_ready`、`production_ready`、publication bundle、semantic quality、claim provenance、core-goal audit |

## 核心產品契約

RDE 是給非資料科學家使用的 agent harness，不是只產生漂亮摘要的黑箱。目標使用者可能有真實資料，但不知道該跑哪些分析、不知道怎樣組合方法，也不會寫分析程式。因此 MCP + harness 必須讓 agent 完成：

1. 了解資料：intake、schema、profile、quality、PII 檢查。
2. 規劃分析：從研究問題與變數角色產生可審查的分析計畫。
3. 可重現探索：每個決策與偏離都寫入 append-only log。
4. 完成分析並嘗試解釋：Docker 不可用時仍可用 local-lite 跑核心報告路徑。
5. 產出報告：包含 artifact、audit、handoff 與可追溯脈絡。

`report_readiness` 與 `run_audit` 會正式檢查這份契約。缺少資料理解、分析規劃、readiness、執行解釋、可重現紀錄、報告產出或 agent/no-code harness 時，會以 `core_goal:*` 缺口阻擋 `production_ready`。

## MCP + Harness 設計

目前 RDE 實作 49 個 MCP tools，分布如下：

| Module | 數量 | 工具 |
| --- | ---: | --- |
| `project_tools.py` | 5 | `init_project`, `get_pipeline_status`, `get_decision_log`, `get_deviation_log`, `log_deviation` |
| `discovery_tools.py` | 4 | `scan_data_folder`, `load_dataset`, `run_intake`, `build_schema` |
| `profiling_tools.py` | 2 | `profile_dataset`, `assess_quality` |
| `plan_tools.py` | 4 | `align_concept`, `propose_analysis_plan`, `register_analysis_plan`, `check_readiness` |
| `analysis_tools.py` | 8 | `suggest_cleaning`, `apply_cleaning`, `analyze_variable`, `compare_groups`, `correlation_matrix`, `generate_table_one`, `run_advanced_analysis`, `run_repeated_measures` |
| `branch_tools.py` | 13 | `open_exploration_branch`, `suggest_branch_experiments`, `run_branch_experiment`, `evaluate_branch`, `promote_branch_to_plan_amendment`, `discard_branch`, `get_exploration_board`, `start_autoresearch_run`, `get_autoresearch_status`, `stop_autoresearch_run`, `resume_autoresearch_run`, `run_autoresearch_next_task`, `run_autoresearch_queue` |
| `ux_tools.py` | 4 | `get_approval_card`, `get_harness_dashboard`, `build_artifact_index`, `get_blocker_playbook` |
| `report_tools.py` | 4 | `collect_results`, `assemble_report`, `create_visualization`, `export_report` |
| `audit_tools.py` | 5 | `run_audit`, `auto_improve`, `export_final_report`, `export_handoff`, `verify_audit_trail` |

`run_repeated_measures` 對兩時點資料使用依原始列對齊的 Wilcoxon signed-rank；三個以上時點使用共同完整個案的 Friedman 主檢定。Post-hoc 可選固定 complete cohort 或每個 contrast 各自的 pairwise-complete rows，並逐一記錄各時點可觀察數、實際配對 n、排除數與 case strategy。Paired 圖註記使用相同的 tie-aware SciPy 方法；報告重建時，每組變數只採最新 durable result，同一實體圖路徑只保留一筆 manifest。

UX harness 是給 no-code 使用者與 agent 看見流程狀態的控制面：

- `get_approval_card` 產生下一個需要確認的 tool call、目的與應檢查 artifacts。
- `get_harness_dashboard` 回報 project、progress、next suggested phase、plan lock、pending approval 與 artifact count。
- `build_artifact_index` 建立 project-scoped artifact index，方便報告與 handoff 追蹤來源。
- `get_blocker_playbook` 在 prerequisite、confirmation、artifact 或 readiness gate 阻擋時，給出可執行下一步。

這些 UX tools 只做導覽與 artifact 產出；不執行統計、不覆蓋 PII gate、不跳過確認、不繞過 locked plan。

## RDE 解決什麼問題

傳統 EDA 很難審查，因為方法變更常常沒有記錄，中間決策散落在 notebook 或口頭說明裡，最後報告也不一定能重現。RDE 的價值不是「跑最多方法」，而是把較窄但可信的分析方法池放進一個可治理、可審計、可交接的流程。

RDE 會強制：

- 先建立 project，再收資料。
- 先完成 intake / schema，再做概念對齊。
- Phase 3 / Phase 4 / Phase 5 / Phase 6 需要明確確認。
- Phase 6 鎖定分析計畫後，Phase 8 若偏離計畫必須記錄 deviation。
- 每個 phase 都產出結構化 artifact。
- decision log 與 deviation log 必須 append-only。

## 視覺總覽

### 整體概念

![整體概念](docs/figures/01-overall-concept.svg)

### DDD 系統架構

![DDD 系統架構](docs/figures/02-system-architecture.svg)

### 13-Phase Workflow

![13-Phase Workflow](docs/figures/03-workflow-detail.svg)

## 13-Phase 受治理流程

1. Phase 0: `init_project`
2. Phase 1: `run_intake`
3. Phase 2: `build_schema`、`profile_dataset`
4. Phase 3: `align_concept(confirm=true)`
5. Phase 4: `propose_analysis_plan(confirm=false)` 先產生 draft，review 後用 `confirm=true` 確認
6. Phase 5+6: `register_analysis_plan(confirm=true)` 做 methodology review 並鎖定 Phase 6 plan
7. Phase 7: `check_readiness`
8. Phase 8: `compare_groups`、`correlation_matrix`、`generate_table_one`、`run_advanced_analysis`、`create_visualization` 等分析工具
9. Phase 9: `collect_results`
10. Phase 10: `assemble_report`
11. Phase 11: `run_audit`
12. Phase 12: `auto_improve`、`export_handoff`、`verify_audit_trail`

## Hard Constraints

- H-001: 檔案大小限制。
- H-002: 格式白名單。
- H-003: 最小樣本數。
- H-004: PII 預設阻擋，僅能明確 override。
- H-005: 報告完整性。
- H-006: 輸出敏感資訊清理。
- H-007: Phase 8 執行需要 Phase 6 locked plan。
- H-008: Artifact gate。
- H-009: Decision logging。
- H-010: Append-only logs。

Soft constraints 包含常態性、多重比較、缺失模式、共線性、effect size、power analysis 與敏感度分析提醒。

## no-Docker local-lite 路徑

`automl-stat-mcp` 是可選重型引擎，不是 VSIX / Codex 完成核心報告的必要條件。Docker 不可用時，RDE 仍會用 local-lite 支援核心報告路徑：

- 描述統計與 Table 1。
- 組間比較。
- ROC/AUC、基本 power hint。
- Kaplan-Meier 摘要。
- 輕量 propensity scoring。
- 高維 logistic / linear model 的 numpy fallback。
- 常見 Matplotlib 圖表輸出。

特殊研究設計、非常領域化的統計方法或超出目前 delegator/vendor contract 的分析，仍需要客製 integration 或人工方法學審核。RDE 會透過 readiness/audit/blocker artifact 說明缺口，而不是假裝完成。

## Codex / VSIX 支援

Codex 可以透過 RDE MCP server 使用完整工具鏈，不應用臨時 shell / pandas 腳本替代 pipeline。建議使用：

```bash
python scripts/configure_codex_mcp.py --apply
python scripts/codex_rde_smoke.py --list-tools-only
python scripts/codex_rde_smoke.py
```

VSIX 啟動時會嘗試自動 upsert `~/.codex/config.toml` 的 `research-data-explorer` MCP block，也可以用 Command Palette 的 `RDE: Configure Codex MCP` 手動重跑。

## 目前驗證狀態

0.4.14 release 前已驗證：

- Python focused contract / harness tests。
- VSIX helper tests 與 TypeScript compile。
- MCP live tool inventory smoke：可看到 49 個 RDE tools，包含 `init_project`、`run_intake`、`build_schema`、`propose_analysis_plan`、`run_audit`。
- Quick Explore MCP smoke：可從外部 stdio subprocess 產出 Phase 10 report。
- 真實 Excel governed `--full-yolo` smoke：從 intake/schema/plan/readiness/Phase 8 execution/collect/report/audit/auto-improve 跑到 `production_ready`。
- Cross-platform entrypoint checks：VSIX helper tests 覆蓋 Codex MCP config upsert、UTF-8 env、Node `path`、workspace/project path 產生，以及 MCP subprocess 的 PATH/HOME/TEMP 等平台 runtime env；JSON/JSONL artifacts 也會 ASCII escape，避免 Windows ANSI/CP950 讀取 audit JSON 時破壞內容。
- GitHub Actions 已加入 Ubuntu / Windows / macOS Intel / macOS Apple Silicon VSIX smoke matrix，release 發布前會跑 helper tests、bundled Python install-shape smoke、package 與 package validation。
- Multi-workbook / multi-sheet governed rerun：兩個 Excel workbook、19 個 worksheet 已完成 sheet-scope alignment，產生 50 rows x 118 columns derived master；Phase 8 跑出 43 個分析、27 張圖、Table 1、多變量模型與 propensity/balance diagnostics；audit grade A，165/165，`report_readiness=production_ready`，且具 structured figure interpretation harness。

真實 Excel full-yolo 驗證摘要：

```text
audit grade: A
audit score: 130 / 130
report_readiness: production_ready
core_goal_audit: 9 / 9
publication bundle: met
decision log: 23 entries
plan adherence: 100%
```

驗證 artifact 範例：

- `.tmp/codex-full-yolo-final15/data/projects/20260508_124523_codex-rde-full-yolo_bf7434f6/artifacts/phase_10_report_assembly/eda_report.md`
- `.tmp/codex-full-yolo-final15/data/projects/20260508_124523_codex-rde-full-yolo_bf7434f6/artifacts/phase_11_audit_review/audit_report.json`

## 已知限制

1. Docker 與 `automl-stat-mcp` 是可選重型引擎；核心 no-Docker 報告路徑使用 local-lite。
2. 某些 vendor payload 在特定資料集上仍可能因 endpoint contract 回 422，RDE 會保留 fallback artifact。
3. 特殊分析如果超出目前 schema、delegator 或 vendor contract，需要客製整合，不應承諾為通用內建工具。
4. 本機可驗證 Windows 路徑與 VSIX/Codex helper；Linux/macOS Intel/Apple Silicon 的實機證據由 GitHub Actions VSIX smoke matrix 提供。

## Repository Layout

```text
src/rde/                         核心應用與 MCP tools
tests/                           regression / contract tests
vendor/automl-stat-mcp/          可選重型分析引擎
data/projects/                   每次分析的 project artifacts
                                新資料夾格式: YYYYMMDD_HHMMSS_<project_name_slug>_<project_id>
memory-bank/                     專案記憶與 release context
vscode-extension/                VS Code extension 與 packaged VSIX 支援
```

## 開發與驗證

```bash
python -m pytest -q
python scripts/codex_rde_smoke.py --list-tools-only
python scripts/codex_rde_smoke.py
cd vscode-extension
npm test -- extensionHelpers.test.ts
npm run compile
```

若修改 workflow governance，請同步更新：

1. [SPEC.md](SPEC.md)
2. [CONSTITUTION.md](CONSTITUTION.md)
3. [AGENTS.md](AGENTS.md)
4. [.github/copilot-instructions.md](.github/copilot-instructions.md)
5. [README.md](README.md)
6. [README.zh-TW.md](README.zh-TW.md)
7. [vscode-extension/README.md](vscode-extension/README.md)
8. [CHANGELOG.md](CHANGELOG.md)
9. `memory-bank/`
