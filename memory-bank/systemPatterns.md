# System Patterns

## Architectural Patterns

- **DDD 4-Layer**: Interface → Application → Domain ← Infrastructure
- **MCP Tool Registration**: `register_*_tools(server)` pattern — 每個 tool file 有一個 register 函數
- **Artifact Store**: 按 Phase 分目錄 (`data/projects/{id}/artifacts/phase_NN_*/`)
- **Pipeline FSM**: PipelineState dataclass 追蹤 current phase + completed phases
- **Authoritative Manifest**: `.github/agent-control.yaml` 統一定義可執行控制規則，文件與測試向它對齊

## Design Patterns

- **Port/Adapter**: Domain 定義 Port (ABC)，Infrastructure 實作 Adapter
- **Use Case**: Application layer 的 Use Case class 封裝單一操作邏輯
- **Anti-Corruption Layer (ACL)**: AutomlGateway 隔離外部 API
- **Event Bus**: Domain events 解耦 (EventBus singleton)
- **Decision Logger**: Append-only JSONL 日誌

## Common Idioms

- **Tool Return Pattern**: 所有 MCP tools 回傳 markdown 字串 (medpaper pattern)
- **Error Handling**: `try/except` 在 tool 層，回傳 `❌ Error: ...` markdown
- **Logging**: `log_tool_call()` / `log_tool_result()` / `log_tool_error()` 三件套
- **Session**: In-memory session (loaded datasets, pipeline state) 透過 `get_session()` 全局存取
- **Soft Constraint Check**: `SoftConstraintChecker` 在 precheck/execution 時自動觸發
- **Variable Classification**: `VariableClassifier` 推論 numeric/categorical/datetime/identifier/text types
- **Phase Gate Wrapper**: tool 先呼叫 `ensure_phase_ready(...)`，同時檢查 pipeline gate 與 prerequisite artifacts
- **Plan Adherence Auto-Log**: `_auto_log_decision()` 在 Phase 8 除 decision log 外，還會依 Phase 6 locked plan 自動寫 deviation log
- **Plan Scope Readiness**: Phase 7 `check_readiness()` derives its variable scope from Phase 6 `analysis_plan.yaml` and Phase 3 `variable_roles.json` before normality/missingness/collinearity checks
- **Scheduled Step Adherence**: Phase 8 plan-adherence checks include both `analyses` and Phase 6 `execution_schedule`
- **Structured Figure Interpretation**: Reports with figure manifests require `figure_interpretation_harness.json` entries covering evidence role, visual read, statistical support, caveat, reportable claim, and next analysis
- **Raw Workbook Coverage Gate**: Phase 1 intake records workbook/sheet coverage and report readiness blocks unresolved multi-file/multi-sheet coverage
- **Greedy Plan Ideation**: `propose_analysis_plan()` 在 Phase 4 用 deterministic heuristic 排序 candidate analyses，輸出可確認的 blueprint 與 visualization bundle
- **Methodology Review Before Lock**: autonomous planner 先產生 draft，再做 internal review / repair；`register_analysis_plan()` 會再次檢查是否低於方法學最低覆蓋要求
- **PII Safety Default**: discovery/load flow 透過 `_pii_gate_message()` 對疑似 PII 預設阻擋，只有明確 override 才放行

## File Naming

- Tool files: `*_tools.py` (analysis_tools, report_tools, etc.)
- Use cases: `*.py` in `application/use_cases/` (analyze_variable, export_report, etc.)
- Domain services: `*.py` in `domain/services/` (collinearity_checker, etc.)
- Adapters: `*.py` in `infrastructure/adapters/` (docx_exporter, scipy_engine, etc.)
