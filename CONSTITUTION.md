# Research Data Explorer — Constitution

> 本文件定義 RDE 專案的核心原則與治理結構。所有 bylaws、skills、agent 行為均以此為最高準則。
> Version: 0.2.0 | Architecture: DDD | Pipeline: 11-Phase Auditable EDA

## Article I: Mission

Research Data Explorer (RDE) 使非 IT 專業研究者能透過自然語言完成資料探索與分析，產出**完整、透明、可再現**的結構化 EDA 報告，讓探索過程經得起科學審視。

## Article II: Core Principles

### §1 透明高於一切 (Transparency First)

- **Agent 不是黑箱**：每個分析決策都寫入 `decision_log.jsonl`
- **偏離必須記錄**：任何偏離預定計畫的操作寫入 `deviation_log.jsonl` 並附理由
- **Log 不可竄改**：decision_log 和 deviation_log 為 append-only，不可修改或刪除
- **Artifact Trail**：每個 Phase 產出結構化 artifact，構成完整審計鏈
- 任何人（PI、reviewer、co-author）都能從 artifact trail 重建整個探索過程

### §2 使用者優先 (User First)

- 所有設計以非 IT 使用者的體驗為中心
- 提供引導式工作流，不預設使用者知道統計方法
- 用白話文解釋分析結果，附帶技術細節
- Phase 3 (概念對齊) 和 Phase 4 (計畫鎖定) 必須用戶確認

### §3 不重造輪子 (Don't Reinvent)

- 統計分析委派給 automl-stat-mcp（透過 Anti-Corruption Layer）
- 整合成熟引擎（ydata-profiling、tableone、sweetviz）
- RDE 專注於 orchestration、audit trail、constraints

### §4 報告至上 (Report is King)

- 報告 ⊃ 論文：報告是完整探索紀錄，比論文更詳盡
- 報告中標記 `<!-- PUBLISHABLE -->` 的段落可直接用於論文
- 報告附帶決策日誌、偏離紀錄、原始統計輸出 → 可再現性保證
- med-paper-assistant 接續報告中的可發表內容 → 撰寫正式論文

### §5 安全與隱私 (Safety & Privacy)

- Hard Constraint: 自動偵測並保護 PII（H-004）
- Hard Constraint: 輸出報告清除敏感路徑資訊（H-006）
- 僅處理本機資料，不上傳至外部服務（除明確授權的 MCP 工具外）

### §6 統計嚴謹 (Statistical Rigor)

- **Pre-registration 精神**：先制定分析計畫，鎖定後才執行
- Agent 必須檢查統計假設再執行分析（Soft Constraints）
- 區分統計顯著性與臨床意義（S-009）
- 提供 effect size 與 confidence interval
- 多重比較必須校正（S-002）

## Article III: Governance Structure

### §1 DDD Architecture

```
Interface → Application → Domain ← Infrastructure
  (MCP)     (Use Cases)   (Pure)    (Adapters)
```

- **Domain Layer** (`src/rde/domain/`): 純業務邏輯，無外部相依
- **Application Layer** (`src/rde/application/`): Use Cases、Pipeline、DTOs、Decision Logger
- **Infrastructure Layer** (`src/rde/infrastructure/`): Adapters（pandas、ydata、automl ACL）
- **Interface Layer** (`src/rde/interface/`): MCP tools（Agent 進入點）
- **相依方向**: Interface → Application → Domain ← Infrastructure

### §2 Pipeline Governance

| 規則 | 層級 | 說明 |
|------|------|------|
| Phase Gate | Hard | 前一 Phase artifacts 必須存在才能進入下一 Phase |
| Plan Lock | Hard | Phase 4 鎖定後，偏離必須記錄理由 |
| Decision Log | Hard | Phase 6 每個分析操作必須寫入 log |
| Append-Only | Hard | decision_log 和 deviation_log 不可修改 |
| User Confirm | Hard | Phase 3 和 Phase 4 必須用戶確認 |
| Artifact Output | Hard | 每個 Phase 必須產出指定 artifacts |

### §3 Bylaws

位於 `.github/bylaws/`，定義具體操作規範。Bylaws 不得違反 Constitution。

### §4 Skills

位於 `.claude/skills/` 或 `.github/skills/`，封裝領域知識。Skills 必須遵守 bylaws。

### §5 Hooks

分為 Code-Enforced (Hard, H-001~H-010) 和 Agent-Driven (Soft, S-001~S-012)。

- Hard hooks 由程式碼強制執行，不可被使用者覆蓋
- Soft hooks 由 Agent 提醒，使用者可決定是否採納
- 詳細清單見 SPEC.md §6

### §6 Amendment

修改 Constitution 需要：

1. 在 SPEC.md 記錄修改理由
2. 更新所有受影響的 bylaws 和 skills
3. 確保向後相容性
4. **新增**：修改涉及 pipeline 或 audit trail → 必須同步更新 AGENTS.md

## Article IV: Integration Contracts

### §1 與 automl-stat-mcp 的契約

- RDE 負責: orchestration, hooks, constraints, EDA step decomposition, **audit trail**
- automl-stat-mcp 負責: 重量級統計分析、ML 訓練
- 透過 `AutomlGateway` (Anti-Corruption Layer) 通訊，保持鬆耦合
- automl 的操作指令在 Phase 4 預排，Phase 6 按計畫執行

### §2 與 med-paper-assistant 的契約

- RDE 輸出 `handoff_package/` (Phase 10)
- 包含: `methods_draft.md`, `results_draft.md`, tables/, figures/, full EDA report
- 報告中 `<!-- PUBLISHABLE -->` 標記的內容 → med-paper-assistant 可直接引用
- Handoff metadata 包含: 專案摘要、可發表內容索引、分析方法摘要

## Article V: Quality Layers

| Layer | 負責人 | 機制 | DDD 層 |
|-------|--------|------|--------|
| L1 — Hook | Code + Agent | 即時約束檢查 (H-001~H-010, S-001~S-012) | Domain Policies |
| L2 — Pipeline | Code | Phase Gate + Artifact Gate | Application Pipeline |
| L3 — Audit | Code + Agent | Decision Log + Deviation Log + Audit Report | Application Logger |
| L4 — Bylaw | Agent | 流程規範遵循 | Interface Layer |
| L5 — Skill | Agent | 領域知識應用 | Interface Layer |

## Article VI: Audit Trail Requirements

### §1 Completeness

完整的審計鏈必須包含：

```
project.yaml → intake_report → schema.json → concept_alignment
  → analysis_plan (LOCKED) → readiness_checklist
  → decision_log.jsonl → deviation_log.jsonl
  → results_summary → eda_report → audit_report → final_report
```

### §2 Traceability

- 每個分析結果必須能追溯到: 使用的方法 → 選擇該方法的理由 → 原始計畫中的目標
- 偏離計畫的操作必須記錄: 原始方法 → 修改後方法 → 修改理由 → 核准方式

### §3 Reproducibility

最終報告必須包含:

- 軟體版本（Python、pandas、ydata-profiling、automl-stat-mcp）
- 隨機種子（如有使用）
- 執行時間線
- 完整的分析計畫（含偏離紀錄）
