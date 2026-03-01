# System Patterns

## Architectural Patterns

- **DDD 4-Layer**: Interface → Application → Domain ← Infrastructure
- **MCP Tool Registration**: `register_*_tools(server)` pattern — 每個 tool file 有一個 register 函數
- **Artifact Store**: 按 Phase 分目錄 (`data/projects/{id}/artifacts/phase_NN_*/`)
- **Pipeline FSM**: PipelineState dataclass 追蹤 current phase + completed phases

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

## File Naming

- Tool files: `*_tools.py` (analysis_tools, report_tools, etc.)
- Use cases: `*.py` in `application/use_cases/` (analyze_variable, export_report, etc.)
- Domain services: `*.py` in `domain/services/` (collinearity_checker, etc.)
- Adapters: `*.py` in `infrastructure/adapters/` (docx_exporter, scipy_engine, etc.)