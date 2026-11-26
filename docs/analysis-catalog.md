# 研究能力目錄

`get_analysis_catalog()` 不需要建立研究或上傳資料，會回傳 6 個問題導向群組、20 個研究能力族群及固定工具綁定。原先 `rde://capabilities.clinical_methods` 只是舊版 adapter 的 7 個方法，不是完整清單；resource 現在也提供完整目錄的 hash 與查詢工具。

| 查詢 | 內容 |
| --- | --- |
| `get_analysis_catalog()` | 全部族群的摘要、方法 ID 與工具綁定 |
| `get_analysis_catalog(family="survival")` | 該族群的輸入角色、輸出、前提、限制、原生結構 schema 與實際 MCP tool input schemas |
| `get_analysis_catalog(detail=true)` | 完整 canonical 宣告，供 host 首次比對與同步 |

未知 family 拒絕；不猜測、不替換成其他方法。工具為唯讀，不探测模型服務或可選 vendor，也不建立研究與成果。`availability=not_probed` 不能解讀成服務已就緒。

能力分為 `native`、`external_receipt`，個別方法另有 `optional_vendor`。統合研究和基因體項目接收外部計算的完整來源／結果收據，RDE 本身不在這些工具內執行 meta-analysis 或 DESeq2。外部 AutoML 需要 vendor，沒有本機 fallback；host 是否已接上這些能力應由平台另外標示。

固定 selector 僅是工具派送片段，不能直接作為完整分析請求。Clinical／prediction／sample-size 的 `options_schema` 從目前原生 dataclass 型別產生，資料準備使用原生 Pydantic `Specification` schema；不會為無法描述的部分偽造完整 schema。Dataclass 的原生 `parse/validate` 還會檢查 nested dict、科學前提、允許的方法、編碼與跨欄位条件，結構 schema 通過不代表研究規格合法。其餘工具提供真正的 MCP input schema，opaque object 的額外規則由明示的原生契約負責。

Agent 應先取摘要，再讀所選 family 的細節，依實際資料 inspect／preflight，將完整設定寫入研究計畫，核准、鎖定並通過 readiness 後才執行。目錄不授權計畫、不代替真實資料或核准事實，也不把探索升格為確認性研究。結果仍以 `rde-result-v1` 的 status、error、來源與 artifact ID/hash 核對，數值與圖文完整度要按各方法審查。

Canonical 檔案為 [analysis_catalog.json](../src/rde/interface/mcp/analysis_catalog.json)，來源為 [analysis_catalog.py](../src/rde/interface/mcp/analysis_catalog.py)。`catalog_sha256` 對完整宣告（排除自身欄位）做 sorted-key、UTF-8、無空白、非 ASCII 原字元的 JSON SHA256；整數值的浮點數先正規化為整數（例如 `0.0` → `0`），以便跨語言重算。摘要／單一族群仍引用完整 hash，不能對摘要自行重算比對；只有 `detail=true` 且沒有 family 的完整結果可以移除 response-only `selection/detail` 後驗證。

每次讀取同時核對目前安裝的全部 RDE Python 來源清單與檔案 SHA256，包括計算引擎、validator、registry 與目錄 generator。修改、新增或刪除原生程式卻未重建目錄會明確拒絕；檔案 hash 快取依檔案身分、大小與修改狀態失效，不能用舊宣告繼續分析。可選 vendor 與第三方套件的執行狀態仍不由此宣告保證。修改程式後須重新產生目錄並重啟部署的 MCP 程序。

修改方法、來源契約或工具參數後執行：

```bash
python -m rde.interface.mcp.analysis_catalog --write
python -m rde.interface.mcp.analysis_catalog --check
python -m pytest tests/test_analysis_catalog.py tests/test_docs_and_tool_sync.py
```

`--check` 只核對目前來源、真實工具 schema 與完整宣告，不寫入檔案；有任何差異以非零狀態結束，適合 CI 與服務啟動前的部署檢查。

測試核對 checked JSON 與實際註冊工具、原生 schema、來源檔案 hash，以及真 MCP discovery、未知拒絕、無 project 讀取、clinical family parser 與進階方法 dispatcher。另驗證 runtime 程式漂移拒絕、wheel 安裝路徑、跨 Python／JavaScript 的完整宣告 hash，以及診斷契約 `first=參考標準`、`second=檢測` 的實際編碼。這是能力與派送契約驗證，各方法的數值正確性另由其研究回歸測試驗證。

## Resident descriptive manuscripts

`resident_exploration` accepts the opt-in scope member
`"manuscript_protocol":"paragraph-v2"`. Reuse the approved project, dataset, original
SHA-256, approval and run across calls. The group must be an approved public category.
The measure must be finite numeric or missing. Only approved context and aggregates are
delivered to the resident. Existing chapter runs keep their original protocol.

* `open` returns the five sections, twenty paragraph tasks and remaining action names.
  Choose an available action and provide the model's reason to `observe` (turns 1–18).
  A rejected choice consumes one turn. Continue until all six observations are recorded.
* `data_quality` counts rows, missing groups, missing measures and joint complete rows.
  `group_estimates` gives assigned rows, observed measures and arithmetic mean.
  `distribution` gives median, minimum and maximum. Group-level analyses exclude missing
  group labels and calculate each statistic using nonmissing measurements in that group.
* `group_spread` gives the first and third quartiles by linear interpolation at
  zero-based position `(n−1)p`, IQR = Q3 − Q1 and sample SD (denominator n−1).
  SD is absent for n < 2. For n = 0 measure-based statistics are null.
  `group_completeness` gives rows, observed, missing and both percentages against rows.
  `group_contrasts` subtracts the first observed group in native group sort order from
  each other group's mean and median. Contrasts keep the original measurement units.
* `draft` and `review` alternate at the same flat paragraph turn (0–19). Attempt 1
  requests short Traditional Chinese prose. Attempts 2 and 3 request targeted model edits
  to indexed sentences in the preceding reply. Join unchanged sentences and model-supplied
  replacements as exact UTF-8 text. Each draft retains the raw reply and composed-author
  hashes. Exhausted paragraphs can be followed by the next task. Replays use the same parameters and raw
  UTF-8 reply. `review` returns exact locators, actual feedback, issues and a checklist.
* `assemble` withholds incomplete drafts. Completed results include model-authorship
  records with raw UTF-8 hashes, the manuscript, rich native cards and a separate
  reader-facing Markdown `evidence_index`. The host can export the index alongside
  the manuscript. It includes units, direction, unrounded values, JSON pointers and
  artifact revisions. `independent_review_required` requires a separate assessment of
  coverage, scientific interpretation, study design and unsupported qualitative claims.
* The model can cite a native field through `{{R…}}`, or give a rounded number, unit,
  group and matching statistic with an adjacent author-selected citation. Numeric
  dictionary facts use `{{S…}}` for an exact approved excerpt with offsets and source URL.

### Typed authoring and independent editorial feedback

`paragraph-v3` keeps the same source and approval anchors. Its action contracts declare
the output level, count basis, unit, percentage denominator and contrast direction.
The resident selects a permitted purpose and intended fields before each observation.
Once prior cards exist, each choice declares an unresolved question and whether
it follows an earlier observation or independently checks another aspect of the
study. Follow-ups identify the original cards and explain the link in the
author's own words. Receipts preserve the selected fields, rationale, previous
values and actual new observation for independent assessment of this decision.

Fresh author replies carry model-written prose and four presentation choices,
`evidence_ids`, `group_table`, `source_ids` and `link_source`. The selected cards,
source excerpts, and compact denominator, location, spread and contrast tables are
attached to the prose. The numeric cells retain native locators. Counts stay integers,
measurement statistics display at least two decimals, and unavailable estimates bind
to the actual JSON null. Model-authorship and attachment hashes are recorded separately.
In drafts marked `editorial_basis_version=1`, the author writes 120–230 Unicode
characters in two to four sentences about the assigned question. An inline
numeric reference must be one of the paragraph's own selected fields. Chinese
decimal words and full-width figures are checked against the same native statistic,
group, unit and precision as an Arabic decimal. The source scope includes the
quantile, IQR, standard deviation, signed comparison and percentage definitions.

Attempts 2 and 3 may edit only the diagnosed sentence of the preceding draft. After
the twenty initial tasks have been reviewed, exhausted paragraphs can have one fresh
attempt 4 informed by the other completed tasks, then targeted edits up to the
maximum in the original sealed open receipt. New runs allow attempts 5–12.
Each edit replaces or deletes the diagnosed sentence. Schema version 1 caps
replacement text at 120 Unicode characters and checks that it is one sentence.
An identical failed prose/presentation cannot advance by resubmission. Set
`scope.semantic_review="required"` to bind each review to a separate reviewer's raw
JSON findings, the source, both author hashes and exact sentence quotations. New
reviewers may give the exact disputed substring and an available statistical card
or approved scope field. The native check verifies both before routing the
feedback to the author. A reviewer
can withhold a draft. Native checks and independent publication review still apply.

Exploration, first drafts and targeted revisions receive the complete approved
researcher request in a separate field. The manuscript title can use the first
question, while later comparison directions and scope limits remain visible at
each decision. A handwritten signed difference must name the comparison and
reference in the native subtraction order. Row counts retain their record unit.
The rationale and the unresolved question undergo the same review. A literal prior
card must be both available and declared. Reported contrast signs must agree with
the original observation.

With `editorial_slices_version=1`, complete paragraphs of two to four nonempty
sentence slices have one independent review per sentence in author order. A first
adverse finding ends the sequence. An acceptance covers every nonempty slice.
Native replay checks the raw review JSON, digest, source sentence and final verdict.
Other paragraph sizes still receive whole-draft feedback and native size validation.

Drafts declaring `authored_evidence_version=1` give each allowed statistical
field a separate `evidence_receipts` entry containing
its artifact, digest and JSON pointer. An author can state a raw numeric value
without an inline card by selecting the uniquely matching statistic, group, unit,
direction and precision. The paragraph keeps the author's original characters
and displays the selected card in its evidence attachment. Reviews and assembly
preserve the exact authored span, surrounding clause and independently read native
value. A numeric repair shows up to three relevant fields for the author to choose.
An explicit categorical code and label can be bound to a matching named column
in the approved dictionary. The binding records both exact spans, the digest of the
approved dictionary and its single source URL. Conflicting or unknown codes require
revision.

Relevant paragraphs receive source-bound signs and closed interval intersections.
Range comparisons use minimum and maximum. Quartile comparisons use Q1 and Q3.
Metadata distinguishes overlap, touching, disjoint intervals and unavailable
estimates. Each input points to its original card. These comparisons describe
summary intervals and do not estimate individual classification probabilities.
