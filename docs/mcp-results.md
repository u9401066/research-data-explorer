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

## 原生計畫版本

`research_plan(project_id, request)` 提供 draft/read/approve/attach_results/reuse/bind_execution。draft 接受 UUID plan_id、完整 protocol（含 question、steps、sourceHash、schemaHash、sampleSizeBasis 等）、可獨立核對的 sources（absolute path、sha256、bytes）、intent、reason；revise/append 必須指定 parent.plan_id/sha256。保存不可變計畫、JSON pointer 差異、核准者及結果來源。approve、attach_results、reuse 均需 exact expected_sha256。

成果沿用只在父／子完整 scientific protocol 相同時成立，需新計畫核准、原 execution_id 及可核對的原成果。沿用保存 `reused_reference_only`，不重新計算、不更改原結果歸屬。這個計畫目錄不解鎖既有 Phase 6、不取代分析方法／前置檢查，也不證明假設真實。

### 核准研究定義進入執行報告

若計畫目錄與實際分析是不同原生專案，主機在執行專案完成 `register_analysis_plan` 後，呼叫 `research_plan(project_id=<執行專案>, request=...)`：

```text
op: bind_execution
plan_id: 精確核准計畫 UUID
expected_sha256: plan.json 內 sealed payload 的 sha256
execution_id: 本次執行 UUID
dataset_id: 本執行專案實際收件的 dataset ID
plan_file: {path: 原 plan.json 絕對路徑, sha256: 整檔 SHA256, bytes: 整檔長度}
approval_file: {path: 原 approval.json 絕對路徑, sha256: 整檔 SHA256, bytes: 整檔長度}
```

原生工具驗證檔案與內部 seal、核准對應、來源及 catalog schema 的原始檔案，再比對執行來源、收件身分和鎖定方法／alpha／缺失及多重比較設定。執行專案重新產生的 schema 可有不同原生 dataset ID，不將它誤當 catalog schema 的同一檔案；兩者來源仍須一致。回覆 `schema=rde-research-execution-context-v1`，包含 project/execution/plan IDs、`plan_sha256`、`approval_sha256`、`source_sha256`、`context_sha256` 及固定 `relative_path=artifacts/research_execution/context.json`。回覆的 approval hash 是 sealed payload hash，不是 approval 整檔 SHA。

`research_execution/` 保存原始 plan／approval bytes 與不可變 context；另在 `phase_06_plan_registration/research_execution.json` 保存 seal marker。相同身分可安全重試；原方法重新登錄的時間戳可變，科學設定與排程不可變。不能以相同執行改綁新計畫、來源或核准。MCP artifacts 即使無新檔變更仍回傳四個必要引用，並沿用 execution_key 的不可變回放規則。

assemble_report、正式 DOCX/PDF 匯出與 claim provenance 每次讀取都重新核對 context、marker、原始收據 copies、來源 closure 與鎖定設定；缺失／竄改必須拒絕，不能悄悄退回未綁定報告。報告保留核准 `researchDetails`、限制、來源 hash，以及已封存 `plan.payload.reason` 原始研究者需求，讓代碼／單位定義與獨立假設有明確出處。這些是已核准的來源陳述，`clinical_validation=not_performed`，不證明研究事實或假設成立，也不表示原始需求中的所有延伸問題均已執行。不補猜臨床編碼、不重算模型、不修改舊研究成果。

未曾綁定的既有原生研究仍可按原流程產生報告，但不宣稱具有此核准 protocol。刪除既有 context 或 marker 會拒絕報告；歷史輸出不自動補造或覆寫，需在獨立新執行／私有複本明確驗證。

## 可恢復的執行收據

有副作用的工具（除了 init_project）新增選填 `execution_key`，為主機分配的 64 位十六進位 key，每個邏輯步驟固定一個。先保存 intent，再執行原工具的全部既有 gate，完成後保存密封結果和不可變成果副本。相同 project/key/tool/arguments/implementation 只回傳同 invocation_id 的已完成收據；成功和失敗收據都不重跑。成果副本由 read_artifact 依完整 ID/SHA 分頁讀取，原 mutable artifact 改變不會替換歷史結果。

key 不同表示不同操作；主機負責避免以新 key 偷偷重試同一步。只有 intent 無完整結果時回傳 EXECUTION_INDETERMINATE，必須核對既有資料，不推測是否執行成功。參數／程式版本不符回傳 EXECUTION_CONFLICT，成果損毀拒絕回放。尚未建立 project 的 init_project 不在這個收據機制內。get_workflow_contract 的 execution_receipts 提供 tool、狀態、invocation_id、收據 hash；未知結果保留 indeterminate。

這個機制是受核對的已完成收據回放與保守的恢復界線，不是任意外部服務或主機斷電情境的 exactly-once 保證。原始收件、來源真實性、統計意義與期刊外觀仍需分別審查。
