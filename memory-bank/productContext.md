# Product Context

## Core Product Contract

RDE is for non-data-scientists with real datasets who may not know what to analyze, how to combine methods, or how to code analysis. The harness must let an agent understand data, plan analyses, run reproducible exploration, interpret results, and produce an auditable report without requiring Docker or user-written code.

`report_readiness` and `run_audit` enforce this with `core_goal:*` gaps. automl-stat-mcp is optional; local-lite statsmodels/scipy fallbacks cover adjusted models, ROC/AUC, basic power analysis, Kaplan-Meier summaries, and lightweight propensity scoring for the VSIX core path.

## Overview

Research Data Explorer (RDE) — MCP Server 提供 13-Phase Auditable EDA Pipeline，結合 VS Code Agent (chatmodes + instructions + skills) 讓研究者透過自然語言完成資料分析。

## Core Features

- **13-Phase Pipeline**: Project Setup → Data Intake → Schema → Concept Alignment → Creative Ideation → Plan Completeness Review → Plan Registration → Precheck → Execute → Collect → Report → Audit → Auto-Improve
- **32 MCP Tools**: 7 tool 檔案涵蓋 project/discovery/profiling/plan/analysis/report/audit
- **Audit Trail**: decision_log.jsonl + deviation_log.jsonl (append-only)
- **Hard Constraints** (H-001~H-010): 自動防呆（檔案大小、格式、PII、plan lock 等）
- **Soft Constraints** (S-001~S-012): 統計提醒（常態性、多重比較、效果量等）
- **Local-first advanced analysis**: adjusted models、ROC/AUC、basic power、Kaplan-Meier、lightweight propensity scoring 不需要 Docker；automl-stat-mcp 只作為重型 vendor workflow 的可選委派
- **Export**: Word (.docx) + PDF 輸出含嵌入圖表
- **Machine-readable governance**: `.github/agent-control.yaml` 定義 confirm flag、PII override、audit path、delegation、analysis plan schema
- **Plan-aware execution**: Phase 8 工具會自動比對 Phase 6 鎖定的 analysis_plan.yaml，偏離時自動寫入 deviation log
- **Multi-workbook coverage**: Phase 1/10/11 readiness now tracks raw workbook and worksheet coverage so reports cannot silently claim completeness when Excel sheets are unreviewed or excluded without rationale
- **Structured interpretation**: Figure-heavy reports must include structured figure interpretation and literature-aware discussion instead of presenting only tables/plots
- **Autonomous ideation**: `propose_analysis_plan()` 以 deterministic greedy heuristic 產生 ranked candidates + visualization bundle，輸出 Phase 4 creative ideation blueprint
- **Methodology guardrails**: Phase 5 會先做 internal review + repair；Phase 6 對 under-scoped plan 預設拒絕鎖定，除非明確 override

## Technical Stack

- **Language**: Python >=3.11
- **MCP Framework**: FastMCP (stdio transport)
- **Architecture**: DDD 4-layer (Domain → Application → Infrastructure → Interface)
- **Stats Engine**: SciPy + tableone + statsmodels local-lite (本地) / optional automl-stat-mcp (Docker, 進階)
- **Visualization**: Matplotlib + Seaborn
- **Export**: python-docx (Word) + xhtml2pdf (PDF)
- **Profiling**: ydata-profiling (optional)
- **Quality**: pytest regression suite + pre-commit hooks (ruff + 4 custom RDE hooks)
