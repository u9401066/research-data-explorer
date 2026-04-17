# Handoff — 2026-04-17 — phase13 / release 0.4.5 prep

## 目的

此交班文件用於中斷目前 session 後，在其他環境繼續完成 RDE `0.4.5` 規劃與實作。

## 使用者明確需求

準備在 `0.4.5` 前加入以下能力：

1. 新增一個正式 phase 專門檢查 plan 完整性。
2. `schema` 出來後就要自主規劃圖表數量，而且只能多不能少；不能只達最低門檻，必須要求 planner 嘗試變數組合。
3. 新增一個正式 phase 做 creative ideation。
4. `posthoc` 分析要獨立出來，且要有最少 3 張圖規則。

## 本次 session 已完成的事情

### 1. 已完成唯讀盤點與設計收斂

已確認這不是小修，需從 **11-phase 擴成 13-phase**。

核心位置已定位：

- pipeline enum / prerequisite / required artifacts:
  - `src/rde/application/pipeline/__init__.py`
- project lifecycle mapping:
  - `src/rde/domain/models/project.py`
- artifact gate:
  - `scripts/hooks/artifact_gate.py`
  - `scripts/pipeline_guard.py`
- planner / methodology review / visualization floor:
  - `src/rde/domain/services/autonomous_eda_planner.py`
- planning MCP tools:
  - `src/rde/interface/mcp/tools/plan_tools.py`
- repeated measures 現有 post-hoc 顯示：
  - `src/rde/interface/mcp/tools/analysis_tools.py`
- extension / docs / prompts 中寫死 11-phase 的地方很多，後續要一起改。

### 2. 已完成設計方向

建議正式 phase 順序為 **13-phase**：

- Phase 0 `PROJECT_SETUP`
- Phase 1 `DATA_INTAKE`
- Phase 2 `SCHEMA_REGISTRY`
- Phase 3 `CONCEPT_ALIGNMENT`
- Phase 4 `CREATIVE_IDEATION`
- Phase 5 `PLAN_COMPLETENESS_REVIEW`
- Phase 6 `PLAN_REGISTRATION`
- Phase 7 `PRE_EXPLORE_CHECK`
- Phase 8 `EXECUTE_EXPLORATION`
- Phase 9 `COLLECT_RESULTS`
- Phase 10 `REPORT_ASSEMBLY`
- Phase 11 `AUDIT_REVIEW`
- Phase 12 `AUTO_IMPROVE`

### 3. 確認過的治理決策

- `creative ideation` 應升格成正式 phase，而不是繼續留在非正式 `Phase 3.5`。
- `plan completeness review` 應從 `register_analysis_plan()` 前的內部 methodology gate 升格為正式 phase。
- `posthoc` **不建議做成獨立 phase**，應做成 **Phase 8/Execute 的獨立 analysis family / tool**，才能：
  - 被納入 plan
  - 被 schedule 排序
  - 被 deviation / audit / report 計算
  - 強制自己最少 3 張圖

## 目前 repo 狀態

### 已存在但尚未提交的變更

工作樹目前已有使用者或先前 session 的未提交改動，主要集中在：

- `README.md`
- `README.zh-TW.md`
- `src/rde/application/use_cases/analyze_variable.py`
- `src/rde/application/use_cases/export_report.py`
- `src/rde/domain/policies/heuristics.py`
- `src/rde/domain/services/autonomous_eda_planner.py`
- `src/rde/infrastructure/adapters/__init__.py`
- `src/rde/infrastructure/adapters/docx_exporter.py`
- `src/rde/infrastructure/adapters/markdown_renderer.py`
- `src/rde/infrastructure/visualization/matplotlib_viz.py`
- `src/rde/interface/mcp/tools/analysis_tools.py`
- `src/rde/interface/mcp/tools/audit_tools.py`
- `src/rde/interface/mcp/tools/plan_tools.py`
- `src/rde/interface/mcp/tools/report_tools.py`
- `tests/test_autonomous_eda_planner.py`
- `tests/test_report_contract.py`
- `tests/test_visualization_stats_annotations.py`
- `src/rde/domain/services/numeric_plausibility.py`（新檔）
- `tests/test_numeric_plausibility.py`（新檔）

這些變更與本次 13-phase 任務**不是同一件事**，但目前使用者要求先全部 push 到測試分支保存，因此會一起提交。

## 後續實作順序（建議照這個做）

### Step 1 — 先改核心 phase/gate

優先改：

- `src/rde/application/pipeline/__init__.py`
- `src/rde/domain/models/project.py`
- `scripts/hooks/artifact_gate.py`
- `scripts/pipeline_guard.py`
- `src/rde/application/session.py`
- 任何依賴 `completed_phases` / `PIPELINE_ORDER` / phase dir 的地方

重點：

- 從 11-phase 改成 13-phase
- `PLAN_REGISTRATION` 往後平移
- `EXECUTE_EXPLORATION` 與後續 phase index 也要整體平移
- 舊資料 rehydrate 時要考慮相容性

### Step 2 — 升格兩個 planning phase

處理：

- `propose_analysis_plan()` → 對應正式 `CREATIVE_IDEATION`
- methodology review → 正式 `PLAN_COMPLETENESS_REVIEW`
- `register_analysis_plan()` 改為只負責 lock / registration

建議 artifact：

- `phase_04_creative_ideation/`
  - `greedy_analysis_candidates.json`
  - `greedy_analysis_candidates.md`
  - `greedy_execution_schedule.json`
  - `greedy_execution_schedule.md`
  - `greedy_plan_enrichment.json`
  - `greedy_plan_enrichment.md`
  - `greedy_statsmodels_base_analysis.py`
- `phase_05_plan_completeness_review/`
  - `analysis_plan_review.json`
  - `analysis_plan_review.md`

這樣最穩，且與既有 artifact 名稱相容度高，只是 phase dir 轉移。

### Step 3 — posthoc 獨立 family/tool

目前 `run_repeated_measures()` 裡雖有 post-hoc 輸出，但不算獨立 family。

後續應做：

- 在 planner 中新增 `posthoc_analysis` family（或更明確 family 名）
- execution schedule 要能排它
- phase 8 執行時要能有獨立 artifact / decision log / visualization manifest
- 視覺化 contract 要新增：`posthoc` 類最少 **3 張圖**

## 圖表 contract 建議

目前 planner 只有：

- `MIN_DESCRIPTIVE_VISUALIZATIONS = 3`
- `MIN_ANALYTICAL_VISUALIZATIONS = 6`

但使用者需求不是單純改下限，而是：

- schema 一出來就主動規劃
- 要「嘗試變數組合」
- 圖數只能增加不能比自主規劃更少

建議後續實作為可測規則：

1. `schema` 後先產出 `visualization_plan_target` / `visualization_expansion_summary`
2. 至少根據：
   - 單變數分布
   - group × outcome
   - continuous × continuous
   - repeated cluster
   - posthoc pairwise / adjusted follow-up
   做系統性組合嘗試
3. `register_analysis_plan()` 不可把 planner 自主產生的 visualization bundle 減到低於 planner target，除非明示 override
4. `posthoc` family 自己維持 `min 3` figures

## 需要優先補的測試

### 最優先

- `tests/test_pipeline_enforcement.py`
- `tests/test_pipeline_integration.py`
- `tests/test_plan_adherence.py`
- `tests/test_docs_and_tool_sync.py`
- `tests/test_agent_control_manifest.py`
- `tests/test_autonomous_eda_planner.py`

### 之後要新增

- 13-phase ordering / prerequisites / optional phase tests
- creative ideation phase artifact existence
- plan completeness review phase artifact existence
- old project rehydrate compatibility
- posthoc family scheduling / plan adherence / min 3 figures
- visualization target can only expand, not shrink

## 注意事項

- repo 目前 branch 是 `main`
- 使用者要求：**現在先開測試分支，全部 git + push，之後換環境慢慢修**
- 因此這次提交重點是 **保存現況與交班**，不是完成 13-phase 功能
- commit message 請明確標註為 handoff / WIP

## 建議後續 branch 命名

- `wip/phase13-release-0.4.5-handoff`

## 最後一句

這次真正開始實作時，請務必先從 phase enum / artifact gate / project status 改起，不要先碰文件，否則很容易造成 phase 名稱和 gate 全部不同步。
