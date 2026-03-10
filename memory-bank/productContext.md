# Product Context

## Overview

Research Data Explorer (RDE) — MCP Server 提供 11-Phase Auditable EDA Pipeline，結合 VS Code Agent (chatmodes + instructions + skills) 讓研究者透過自然語言完成資料分析。

## Core Features

- **11-Phase Pipeline**: Project Setup → Data Intake → Schema → Concept Alignment → Plan → Precheck → Execute → Collect → Report → Audit → Auto-Improve
- **30 MCP Tools**: 7 tool 檔案涵蓋 project/discovery/profiling/plan/analysis/report/audit
- **Audit Trail**: decision_log.jsonl + deviation_log.jsonl (append-only)
- **Hard Constraints** (H-001~H-010): 自動防呆（檔案大小、格式、PII、plan lock 等）
- **Soft Constraints** (S-001~S-012): 統計提醒（常態性、多重比較、效果量等）
- **automl-stat-mcp 委派**: 進階統計（PSM、survival、ROC）委派給 Docker 服務
- **Export**: Word (.docx) + PDF 輸出含嵌入圖表
- **Machine-readable governance**: `.github/agent-control.yaml` 定義 confirm flag、PII override、audit path、delegation、analysis plan schema
- **Plan-aware execution**: Phase 6 工具會自動比對已鎖定 analysis_plan.yaml，偏離時自動寫入 deviation log

## Technical Stack

- **Language**: Python >=3.11
- **MCP Framework**: FastMCP (stdio transport)
- **Architecture**: DDD 4-layer (Domain → Application → Infrastructure → Interface)
- **Stats Engine**: SciPy + tableone (本地) / automl-stat-mcp (Docker, 進階)
- **Visualization**: Matplotlib + Seaborn
- **Export**: python-docx (Word) + xhtml2pdf (PDF)
- **Profiling**: ydata-profiling (optional)
- **Quality**: pytest regression suite + pre-commit hooks (ruff + 4 custom RDE hooks)