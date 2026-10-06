# 結構化 MCP 結果與成果讀取

所有工具的 `outputSchema` 描述 `rde-result-v1`。`structuredContent` 固定包含：

- `status`、`error.code/message/detail/suggestion/retryable`：機器控制流程；錯誤同時設定 MCP `isError`。不可從 Markdown 表情符號推斷成功與否。
- `tool`、`invocation_id`：實際呼叫身分。
- `message`：供人閱讀的原始工具說明。
- `data`：工具的 JSON 結果；收件包含 dataset ID，schema 包含完整變項結構。純說明工具的 data 可以是空物件。
- `context`：選定的 project ID、伺服器端 project root、所屬 dataset IDs，以及收件時核對的來源 SHA256、bytes、檔名和 Excel 工作表。舊收件紀錄若未保存來源 hash，sources 為空，不補造歷史來源。沒有有效專案時不回退到其他專案。
- `artifacts`：此次新增或更新的檔案引用，包含 project ID、artifact ID、相對位置、角色、位元組長度、SHA256。revision 為內容 SHA256；相同位置維持相同 artifact ID。

`read_artifact(project_id, artifact_id, expected_sha256, offset, limit)` 提供最多 262144 bytes 的 base64 分頁；依 `next_offset` 讀到 null，拼接原始 bytes 並驗證完整 SHA256。UTF-8 可跨 byte page，必須先組合再解碼。不可用另一个專案讀取引用，不跟隨檔案／目錄 symlink，也不接受任意來源路徑。可變成果已改變時回傳 `STALE_ARTIFACT`，不偷偷替換成新版本。

引用不表示把每個可變成果都保存了歷史副本。需要歷史版本時，由研究版本／執行收據保存的不可變成果引用負責；工作台現有 vault 也持續保留下載成果。

`read_artifact` 是只讀操作；其他工具原有 phase、確認及執行限制仍有效。結構化契約不代表已通過研究方法或語意審查。artifact 清單列出目前呼叫結束後可觀察到的新增／變動檔案，並非交易或執行恰好一次的保證。
