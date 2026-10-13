# 按鎖定方法核對成果配額

2026-10-13 的公開 UCI 519 心衰竭資料實測，Workbench 真 Qwen 完成生存計畫、RDE 與完整方法報告閱讀。臨床方法的 deliverables 已明定 `table_one_required=false`、`required_descriptive_figures=0`，但稽核仍顯示 `table_one=❌, crude=0/0` 且扣除不適用的分數。Agent 將它誤讀為「投稿表格有缺口」。

`run_audit` 現在用同一個 `_publication_bundle_check` 計算分數及說明：

- 按固定 deliverables 決定 Table 1、描述圖、方法圖是否適用；非必要項明示 `not_required_by_locked_scope`，不扣分。
- 一般 EDA 未提供特定契約時，仍預設 Table 1／3 張描述圖／6 張方法圖；真正缺漏不會被免除。
- 描述性研究仍標示此項不適用、0/0，不宣稱投稿就緒。
- 通過依據仍是不可變方法收據、所需圖表及 `minimum_publication_bundle_met`，不是單純圖檔計數或 letter grade。研究科學性與投稿審閱不因此核准。
- 歷史 audit/report 不改寫；新執行才產生新收據。Workbench 對舊收據另外要求以 failed checks／missing requirements 解讀，不能從物理缺檔符號推定必須新增分析。

回歸涵蓋只需要方法圖、真正缺少方法圖、一般 EDA 缺 Table 1、描述性不適用。相關 59 tests 通過；完整 `python -m pytest -q`：1,105 passed／81 skipped（490.72 秒）。實際新版 MCP／平台驗收及發布收據記錄於 Workbench `docs/REAL_DATA_SMOKE_20261013.md`，不可用此單元測試紀錄代替真實 Agent 重驗。
