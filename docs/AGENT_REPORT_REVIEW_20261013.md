# 2026-10-13 Agent／RDE 報告核對

此修訂保留既有原始資料與歷史報告。新執行依鎖定計畫範圍判定報告 readiness，不會重寫歷史研究。

## 原生修正

- `report_tools._summarize_publication_deliverables` 由鎖定的 `planned_descriptive` 判定通用投稿 bundle 不適用。描述性研究不再被要求 Table 1、三張粗分析圖及六張細分析圖。
- `audit_tools` 保留來源、決策鏈、方法報告及 readiness 核對。不適用的 publication bundle 計為 0/0，沒有以虛構滿分補齊，亦不因此宣稱可投稿。
- Phase 10 最終報告使用真實 `target_tier`；`descriptive_only` 等範圍完成不再寫成 production-ready。
- Codex、Claude、VS Code 發佈內容中的 EDA／report skills 說明實際載入邊界、宿主保存的授權、方法範圍、固定資料版本、完整分頁報告與稽核證據。候選稿標記不代表可以直接投稿。

## 驗證

`tests/test_descriptive_study.py::test_descriptive_full_mcp_audit_does_not_demand_inferential_publication_bundle` 從原生 MCP 計畫執行到 collect／assemble／audit／auto-improve；刪除真實方法報告後再次 audit 必須失敗。相關描述與報告契約 54 項通過；Ruff 與六份 skill 格式驗證通過。

Workbench 對新 RDE 原始碼的實際 MCP 整合兩項通過，包括固定資料的 autoresearch 分支、成果保存與投稿圖。整合中的模型候選為受控 fixture，不能當成真實 Qwen 驗證。真實 Qwen 規劃、獨立審閱、執行與結果解讀由 Workbench 的 `docs/RDE_AGENT_AUDIT_20261013.md` 記錄。

首次全套 pytest 的暫存區耗盡，該輪失敗且不列為通過；改用獨立暫存區後重跑。最終全套結果為 **1100 passed、81 skipped、4205 warnings，496.76 秒**；警告包含既有套件棄用訊息，不等同瀏覽器 console 錯誤。

這些核對不證明所有臨床方法或研究定義都正確。本文及 skills 是指引；執行 gate、版本綁定與結果完整性仍由程式與 MCP 契約核對。
