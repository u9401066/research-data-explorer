# Decision Log

| Date | Decision | Rationale |
| ---- | -------- | --------- |
| 2026-03-01 | DDD 4-layer architecture | 清晰職責分離，Domain 不依賴外部套件 |
| 2026-03-01 | FastMCP as MCP framework | 輕量、stdio transport、decorator pattern |
| 2026-03-01 | 11-Phase pipeline design | 完整審計鏈，每步產出 artifact |
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
