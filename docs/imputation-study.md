# 標準多重插補：Python PMM v1

此模組以既有 Python `statsmodels` 執行有界的標準 multiple imputation，
不引入 R 或另一套語言引擎。科學 kernel、來源契約、原生 MCP、計畫鎖定、
readiness、中文報告與英文投稿圖已整合，並由實際 MCP server dispatch 驗證。
Workbench／Qwen 實機驗收另行記錄；本文件不代表已部署或所有期刊方法皆可執行。

本版在 statsmodels **0.15.0** 驗證，要求 `MICEData` 提供明確的 `rng` 參數，
讓每個研究使用獨立 RNG；舊引擎會留下明確失敗收據，不以全域 seed 模擬隔離。
發布環境須滿足此 Python capability，不需額外語言服務。

## 方法與範圍

`ImputationSpec.family="imputation"` 限單層、獨立個案及連續／二元欄位。
每欄的來源名稱、原始單位、binary 的 `[reference,event]` 代碼、是否可插補、
條件模型 predictors 都必須事先固定。ID 不放進任何模型；每份完成資料是同一批
受試者的另一個插補版本，不是新增病人。

- 插補使用 `statsmodels.imputation.mice.MICEData` 的 predictive mean matching。
  連續欄以 OLS、二元欄以 GLM Binomial(logit) 建立 conditional mean model；
  Gaussian parameter perturbation 後，**兩者都從觀察 donor 抽值**。
  Binary 仍保留 0／1，不宣稱是 R `mice::logreg` 的獨立 Bernoulli draws。
- `k_pmm` 是整個物件的同一個 donor count，不能逐欄不同。
  `m`、burn-in cycles、每份完成資料之間的 cycles、seed 都固定在計畫中。
  每輪先更新缺值較少的欄；同數量依規格欄序。內部個案順序依正規化唯一 ID
  排序，來源列號另外保存，所以來源重排不會重新分派 RNG 抽樣。
- 每份資料跑相同的加法 Gaussian OLS 或 binary logistic GLM；使用 model-based
  covariance，不冒稱 HC3 或 robust。沒有交互作用、樣條或自動選變項。
- `statsmodels.MICE.combine()` 合併 estimates 與完整 covariance：
  `T = U_bar + (1 + 1/m) B`。保存每份 estimates／covariance 及 pooled
  within／between／total covariance。
- 信賴區間與 p 值明確採**逐項未校正的漸近常態 Wald**；沒有 Barnard–Rubin
  小樣本自由度。`missing_information_ratio` 是 `(1+1/m) B_jj / T_jj`，
  不稱作已作 finite-df 修正的 FMI。
- 保存原本 outcome＋analysis predictors 完整者的同規格模型，讓人比較分母與
  估計變化；若該模型不足、分離或不可估，明列原因。這不是 MNAR 敏感度檢定，
  也不能從兩份結果的差異證明 MAR 或沒有偏差。

不支援多層／時序／survival-specific MI、序位／多分類、substantive-model-compatible
MI、reference-based MI、delta／NARFCS、結構性缺失、自動 convergence 認證。
來源不明的 MAR、獨立性與可插補範圍不能由程式代替研究定義。

## 來源與分母

`prepare_imputation(df,spec)` 回傳 `(frame, case_ledger, dataframe_sha256)`。
準備過程不填任何缺值；來源不被改寫。

1. 原始 role columns 與原始列共同計算 source-frame hash；正式 orchestrator
   另綁上傳檔案 byte hash／sheet／schema／dictionary 與核准計畫。
2. 依宣告 cohort 限制後，先檢查 ID 缺失／重複與非法代碼；不能被其他欄缺值遮住。
3. 全部 imputation roles 都缺失的個案**明確拒絕**，避免 MICEData 初始化自行刪除。
4. `impute=false` 欄的缺失依明訂 `nonimputable_missing="exclude"` 排除並記帳；
   其他待插補個案保留。`impute` 欄位不代表一定有缺值。
5. 沒有剩餘缺值時拒絕人工製造 MI，改用原 regression 流程。
6. 保存 input/cohort/included/excluded 人數、每欄缺失、每格插補位置、原始完整者、
   analysis 完整者、抽樣順序對來源列號的映射。沒有名為 `complete_data_rows`
   的偽共同完整人口；新 family 的 readiness 必須使用自己的 ledger。

所有條件模型與 analysis design 都需 full rank、足夠 residual cases、有限正定
covariance；binary separation、未收斂、模型警告都保留失敗，不換方法、不自動丟欄，
也不減少事先指定的 m。m／iterations／檔案 cell budget 是工程上限，不是 precision
或統計充分性的保證。

## 整合介面與成果

```python
spec = ImputationSpec.parse(clinical_options)
preflight = imputation_preflight(dataframe, spec)
# Only after the orchestrator verifies the exact source/specification approval:
result = run_imputation(dataframe, spec, output_dir=new_analysis_directory)
```

`output_dir` 必須尚不存在；同一路徑不覆寫、不重新估計。失敗保存 `failure.json`
與已完成的局部檔，沒有成功 `result.json`，也不能以局部 completed CSV 宣稱研究完成。

成功目錄包含：

| 檔案 | 內容 |
|---|---|
| `recipe.json` | 規格、Python 套件版本、來源 hash、safe names 對照與 case ledger |
| `completed-001.csv` … | 全部完成資料，使用來源欄名；binary 以已記錄的 0／1 編碼；來源列 locator，不匯出 ID 值 |
| `models.json` | 每份完整模型參數、covariance、n、residual df、完成的 cycle |
| `chain-diagnostics.json` | 每輪各缺值欄的插補平均、SD、range；不是 convergence 通過證明 |
| `complete-case-comparison.json` | 原分析完整人口的模型或不可估原因 |
| `manifest.json` | 衍生檔案 SHA-256／bytes，原觀察格未改及來源未修改聲明 |
| `result.json` | 完整科學收據、manifest reference、receipt SHA、限制 |

每輪與每份完成資料均核對原觀察格逐值不變；每個 PMM 值必須來自該欄觀察 donors。
CSV 使用 17 位有效數字保存 binary64 round-trip。保留欄名
`__rde_source_data_row__` 供一基底來源列號，不接受來源角色佔用。

`artifact_files` 包含 manifest 與其上游檔案；為避免循環雜湊，`result.json` 不包含
自己的 file hash。MCP orchestrator 把它連同其他產物納入外層 clinical receipt
的完整檔案 inventory；重用時同時比對內外清單、全部 hash、檔案大小及 result。
發布、重繪與重用讀取保存值，不重新插補。

## 原生 MCP 與投稿圖

1. `inspect_clinical_study` 回傳完整 `spec`、來源檔／frame／spec hashes 與 ledger。
2. `register_analysis_plan` 僅接受單一 `run_clinical_study` bundle，頂層
   `missing_strategy="multiple_imputation"`、`multiple_comparison_method="none"`，
   `alpha=1-confidence_level`。通用 EDA 不因這個 family 而獲得插補執行權限。
3. 原生計畫核准、鎖定與 readiness 通過後才執行；來源或規格變更必須建立明確修訂。
4. `collect_results`、`report_readiness` 與 `assemble_report` 核對 included ledger、
   全部 m 份模型／CSV 及圖表。每個模型的 n 都是原個案數，不累加為 n×m。
5. `render_publication_figures` 只讀取保存的數值收據重繪新版本，不重新插補或估計。

預設產出 population flow、每欄插補格數、pooled coefficient 與 MICE cycle traces；
欄位多時分頁，英文圖用 V1 等別名、附來源對照圖說，另有中文解釋。保存向量 SVG／PDF、
300 dpi PNG／TIFF、caption 與逐值 CSV，全部綁定來源收據。Trace 展示單鏈過程，
不以看似穩定的圖形認證 MAR 或收斂。

數值完成而繪圖失敗時保留全部數值與衍生檔，之後只補繪圖；任何缺檔、hash 改變、
內外 inventory 不一致均拒絕重用，不能靠重新估計蓋過損壞。數值執行失敗保存原生
attempt、failure.json 與已完成局部檔，不計為計畫完成。執行途中來源檔改變亦拒絕完成。

## 驗證範圍

`tests/test_clinical_imputation.py` 實跑 continuous／binary PMM 與模型，使用
獨立 scalar `math.fsum` 公式逐項核對 Rubin estimates／完整 covariance，並以
`erfc` 核對常態 p 值；不呼叫 production pooling helper 當作 oracle。

另核對來源不變、逐格 observed conservation、donor membership、binary coding、
所有 CSV/hash、來源列重排與固定 seed、全域 RNG 不變、literal source names、
全部缺失列、ID／非法碼先於缺失排除、rank/separation、完整資料拒絕、
單一分析失敗不能縮減 m、原成果路徑不能覆寫。

`tests/test_missing_stratified_workflow.py` 另經實際 MCP dispatch 驗證 inspect、鎖定規格、
原生計畫 policy、執行、報告 readiness、組裝報告、凍結值重繪、全部輸出 hash／DPI、
來源變更、插補失敗保存與繪圖失敗後的免重估恢復。合成工程／數值測試不能取代
平台與 Qwen 實際選用契約、程序終止／重啟及真實資料審閱驗收。
