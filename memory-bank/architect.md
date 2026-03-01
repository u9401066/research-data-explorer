# System Architect

## Overview

RDE 採用 DDD (Domain-Driven Design) 四層架構，配合 11-Phase Auditable EDA Pipeline。

## Architecture

```text
Interface (MCP tools) → Application (Use Cases, Pipeline) → Domain (Pure Logic) ← Infrastructure (Adapters)
```

### Layer 職責

| Layer | 路徑 | 職責 |
| ----- | ---- | ---- |
| Domain | `src/rde/domain/` | Models (AR/VO/Entity), Services, Policies (Hard/Soft), Events, Ports (ABC) |
| Application | `src/rde/application/` | Use Cases, Pipeline FSM, DTOs, DecisionLogger, Session |
| Infrastructure | `src/rde/infrastructure/` | PandasLoader, ScipyEngine, AutomlGateway, ArtifactStore, MatplotlibViz, MarkdownRenderer, DocxExporter |
| Interface | `src/rde/interface/` | MCP Server (FastMCP), 7 tool files, Prompts |

## Architectural Decisions

1. **DDD 純 Domain**: Domain layer 不依賴任何外部套件，純商業邏輯
2. **MCP as sole interface**: 所有對外互動透過 MCP tools，無 REST API
3. **Anti-Corruption Layer**: AutomlGateway 隔離 automl-stat-mcp API 概念
4. **Pre-commit hooks**: 4 custom hooks 確保 decision log 完整性、PII 防護
5. **Append-only logs**: decision_log.jsonl/deviation_log.jsonl 不可修改 (H-010)
6. **Plan Lock**: Phase 4 鎖定分析計畫，Phase 6+ 偏離需記錄 (H-007)
7. **Artifact Gate**: 前一 Phase artifact 必須存在才能進入下一 Phase (H-008)
8. **Export 雙格式**: python-docx (Word) + xhtml2pdf (PDF)，嵌入圖表與表格

