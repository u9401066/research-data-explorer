# Decision Log

| Date | Decision | Rationale |
| ---- | -------- | --------- |
| 2026-05-07 | Treat recovered projects as audit-compatible only when session data carries Phase 1 and Phase 2 provenance | Auto-recovery must not fabricate schema or intake artifacts; it may recover from MCP tool-list drift only when `run_intake()` and `build_schema()` really ran. |
| 2026-05-07 | Persist and rehydrate explicit Phase 3/4 confirmation state from artifacts | A session reload must not promote unconfirmed concept alignment or creative ideation, while legacy locked-plan projects remain resumable through plan artifact compatibility. |
| 2026-05-07 | Preserve legacy `project.plan_locked=true` when old plan artifacts lack a `locked` field | Older projects recorded the lock on project JSON before `analysis_plan.yaml.locked` existed; reload repair must not downgrade valid locked plans unless the artifact explicitly says `locked:false`. |
| 2026-05-07 | Block partial VSIX RDE tool lists that omit `init_project()` | The chat harness should fail fast on client/server registration drift instead of letting agents call later pipeline tools without Phase 0 bootstrap. |
| 2026-05-07 | Allow auditable project recovery from session-only intake/schema before Phase 3 | Agent clients can cache or omit `init_project`; recovery preserves Phase 0-2 artifacts and normal Phase 3 confirmation instead of leaving non-data-scientists stuck. |
| 2026-05-07 | Treat `init_project()` as the only canonical RDE Phase 0 project bootstrap tool | `create_project()` belongs to delegated automl contexts and must not appear in RDE no-active-project guidance or VSIX pipeline bootstrap instructions. |
| 2026-05-07 | Treat Phase 8 branch/autoresearch as governed-only execution | Automatic branches are useful only after concept alignment, plan confirmation, locked plan registration, and readiness checks have created an auditable foundation. |
| 2026-05-07 | Use a durable queue for YOLO overnight exploration, but keep promotion behind audit gates | The agent may explore branches autonomously, while result promotion still requires coverage, artifact, decision-log, audit, and user-facing approval evidence. |
| 2026-05-07 | Keep Phase 4 as a two-step draft/review/confirm contract | Locking creative exploration too early blocks new branches, but confirmation still needs an explicit user-review boundary. |
| 2026-05-07 | Redact local paths in UX harness previews and artifact index output | No-code users need readable artifacts without leaking machine-specific workspace details into review surfaces. |
| 2026-05-06 | Keep 13 main phases and enforce sub-artifact gates instead of expanding the public phase count | 13 phases are enough for agent-facing workflow; Phase 4/5/6 and Phase 8 artifacts provide the needed granularity without making the harness unwieldy. |
| 2026-05-06 | VSIX setup must scaffold Copilot, Codex, and Cline assets | Real users may use any of the three mainstream agents; setup now writes `.github/*`, root `AGENTS.md`/`.codex/skills`, and `.clinerules` without overwriting existing files. |
| 2026-05-06 | H-004 PII detection must inspect sample values, not only column names | Real datasets often hide emails/phones/IDs under generic column names, so value-level patterns are needed before downstream analysis. |
| 2026-05-06 | Report readiness reads methodology review from Phase 5 | Plan completeness review is now its own canonical phase; final report readiness must follow that artifact rather than the locked-plan directory. |
| 2026-03-01 | DDD 4-layer architecture | 清晰職責分離，Domain 不依賴外部套件 |
| 2026-03-01 | FastMCP as MCP framework | 輕量、stdio transport、decorator pattern |
| 2026-03-01 | Auditable pipeline design | 完整審計鏈，每步產出 artifact |
| 2026-03-01 | Append-only decision log (JSONL) | 不可竄改，支持審計 |
| 2026-03-01 | automl-stat-mcp as vendor submodule | 版本追蹤，Docker 獨立部署 |
| 2026-03-01 | Pre-commit hooks (4 custom) | 自動化 H-004/H-006/H-008/H-010 檢查 |
| 2026-03-02 | Refactor analyze_variable → UseCase | DDD 原則：tool 層不含商業邏輯 |
| 2026-03-02 | CollinearityChecker domain service | S-007 VIF 檢查抽至 domain 層 |
| 2026-03-02 | python-docx for Word export | 穩定、純 Python，無 native deps |
| 2026-03-02 | xhtml2pdf for PDF (取代 WeasyPrint) | WeasyPrint 需要 GTK native libs，Windows 不可用 |
| 2026-03-02 | DocumentExporterPort in domain | Export 功能也遵循 Port/Adapter pattern |
| 2026-03-02 | VariableClassifier 加入 sample_values | 修正只靠 dtype 推論的缺陷：偵測日期字串、數字字串、依名稱辨識 ID |
| 2026-03-02 | build_schema Phase 2 重新分類 | build_schema 不再只序列化，會用 sample_values 重新分類 + 加入描述統計 |
| 2026-03-02 | AutomlGateway 重寫對齊實際 API | 舊 /api/projects 端點不存在；改為 stats-service:8003 + automl-service:8001 |
| 2026-03-02 | AutomlGatewayPort 擴展介面 | 3 methods → 8 methods (direct_analyze, propensity, survival, roc, power, automl, job_status) |
| 2026-03-10 | agent-control.yaml 作為 authoritative control manifest | 將 agent 約束從文字敘述提升為可驗證契約，文件與測試都以此為準 |
| 2026-03-10 | Phase 3/4 必須以 confirm=true 解鎖後續 phase | 避免 agent 在未經用戶確認下直接推進 concept / plan gate |
| 2026-03-10 | H-004 改為 default-block with explicit override | 對疑似 PII 採安全預設，只有 allow_pii=true 才允許載入且需明示警告 |
| 2026-03-10 | Phase 6 logs 固定寫入 phase_06 artifact 目錄 | 讓 audit contract、artifact gate、export_handoff 與實體檔案位置一致 |
| 2026-03-10 | Phase 8 自動檢查 analysis plan adherence | 將 S-011 從提醒提升為可執行自動偏離紀錄，降低 agent 無聲偏離風險 |
| 2026-03-10 | smoke tests 全面遷移為 pytest suite | 讓控制規則與回歸驗證可由 `python3 -m pytest -q` 直接守住 |
| 2026-03-19 | Adopted template-derived editor scaffolding for VS Code agent mode in RDE via .vscode/settings.json, .github/agents, and .github/prompts. | The repository already had governance content but lacked the file locations VS Code agent mode and prompt discovery rely on. Adding RDE-specific agents/prompts makes the constraints operational instead of documentation-only. |
| 2026-03-19 | Keep repo quality gates focused on repository-owned code and restore blocking CI. | Vendor code under vendor/automl-stat-mcp is upstream content and should not block RDE lint/pre-commit quality gates. After excluding vendor and fixing repo-owned lint issues, Ruff, pre-commit, and non-vendor pytest can be enforced again as hard checks. |
| 2026-03-25 | 採用雙層 extension release 流程：CI 先驗證並產出 VSIX artifact，tag workflow 再用 VSCE_PAT 與 OVSX_PAT 發布到 Visual Studio Marketplace 與 Open VSX。 | 先把打包驗證納入日常 CI，避免未經 package 驗證就打 tag；發布則獨立於一般 CI，減少 secret 暴露面並支援手動或 tag 觸發。 |
| 2026-03-26 | 將 repo 版本、VS Code extension 版本與 CHANGELOG 納入同一個 pre-commit release guard。 | 第一個正式版預計是 0.1.0，若沒有自動檢查，很容易出現 repo/VSX/tag 版本漂移或漏記 changelog。 |
| 2026-03-28 | 將 autonomous EDA ideation 正式收斂為 `propose_analysis_plan()` greedy MCP tool。 | `autoresearch` 式發想若只留在 README/prompt 會很快失真；把它做成 deterministic、可審查、可輸出 blueprint 的工具，才能在不破壞 Phase 3/4 confirm gate 的前提下，真正驅動 agent 自主規劃 EDA。 |
| 2026-03-28 | 將內部 methodology review / repair 與 methodology gate 接入 autonomous EDA workflow。 | 單有 greedy ideation 還不夠，agent 仍可能鎖定過薄的 plan。把 review / repair 放進 Phase 5，並讓 Phase 6 對 under-scoped plan 預設阻擋，才能真正防止「跑兩個分析就結束」的低品質 autonomous EDA。 |
