# 獨立兩組均差的非劣性研究契約

本 family 使用成熟 Python 套件執行預先指定的 Welch 均差非劣性分析，適用於每人一筆、兩組獨立、連續終點。`method="welch_mean"` 是唯一可執行方法。二元風險差、比例、存活非劣性、成對／群集／交叉設計、分層調整及等效性不在此版範圍；不得將二元非劣性請求改成 Welch 或 Wald。

此 family 已接入原生 `inspect_clinical_study`／`run_clinical_study`、計畫 gate、報告 readiness 與 publication edition；平台／Agent 的端到端操作另需驗證。單元測試通過不代表臨床 margin、族群、試驗設計或研究結論已獲驗證。

## 計畫與輸入

以下 JSON 是完整範例；研究定義與 margin 來源必須來自實際計畫，不能照抄範例的假設。

```json
{
  "family": "noninferiority",
  "subject": "participant_id",
  "treatment": "arm",
  "treatment_levels": ["control", "active"],
  "treatment_definition": "預先指定的新介入與標準對照之比較",
  "outcome": "outcome_score",
  "outcome_definition": "依研究計畫指定量表的總分",
  "outcome_window": "基線後第十二週的預定測量窗",
  "outcome_unit": "score points",
  "method": "welch_mean",
  "direction": "higher_is_better",
  "margin": 2.0,
  "margin_scale": "outcome_unit",
  "margin_basis": "僅供契約示範；正式研究需提供預先指定且可審查的臨床依據",
  "population_definition": "符合計畫納入條件且兩組皆有固定時間窗終點的獨立受試者",
  "context": "僅供契約示範，不構成真實研究定義",
  "study_design": "randomized_parallel",
  "independent_rows": true,
  "missing_strategy": "complete_case",
  "one_sided_alpha": 0.025,
  "confidence_level": 0.975
}
```

除 `family`（預設 `noninferiority`）和 `confidence_level`（預設 `0.975`）外，其餘欄位必填。未知欄位拒絕；沒有 `outcome_levels` 或 binary estimator 選項。`NoninferioritySpec.parse`、`to_dict`、`variables` 提供共同介面。

| 設定 | 確切語意與限制 |
| --- | --- |
| `subject` | 不可空白、不可重複；即使該筆終點缺失也要先核對身份。 |
| `treatment_levels` | 恰好兩個不同原始代碼，順序固定為 `[control, treatment]`，不依排序或樣本量猜方向。 |
| `direction` | `higher_is_better` 或 `lower_is_better`，以研究問題預先指定。 |
| `margin` / `margin_scale` | 正且有限，`margin_scale="outcome_unit"`；與終點同一原始單位，不是相對效果或百分比換算。 |
| `margin_basis` | 非空的明確來源／理由；文字存在不代表臨床合理性、assay sensitivity 或 constancy 已驗證。 |
| `population_definition` | 明確描述來源族群；不能只填「ITT」或「PP」，也不會自動核准這些標籤。 |
| `study_design` | `randomized_parallel`、`observational_cohort`、`cross_sectional`；觀察性差異不能解讀為因果治療非劣性。 |
| `missing_strategy` | 只允許 `complete_case`；沒有插補、nonresponder 或自動族群重分類。 |
| `one_sided_alpha` | 嚴格介於 `0` 與 `.5`。 |
| `confidence_level` | **單側下限**水準，必須等於 `1-one_sided_alpha`；例如 `.025 → .975`。這個數字不可當作同水準的雙側 CI。 |

來源容許 10–100,000 列，完整個案至少 10 人且每組至少 2 人；這是執行邊界，不是樣本數充分性證明。每組樣本變異數必須正且有限。完整終點若只有一或兩個不同數值則阻擋，避免以連續方法替代 binary NI；這個保守門檻也可能拒絕高度離散的連續量測，需另外審查，不能自動抖動或增加值。

## 前置核對、計算及決策

`prepare_noninferiority(df, spec)` 回傳分析 frame、`case_ledger`、來源 hash。先檢查原始欄位／身份／所有非缺失代碼及數值，再剔除缺失列，因此非法代碼不能躲在另一欄缺失的列內。來源 hash 含所有原始選用欄位與列順序；ledger 的 `data_row` 是不含表頭的一起算原始列序。`population_membership_verification="not_performed"` 明確保留，沒有從完整個案推導 ITT／PP。

`noninferiority_preflight(df, spec)` 回傳 `noninferiority-preflight-v1`，包含各組分母、樣本變異數、缺失、阻擋原因與 `can_execute`，不產生檢定或信賴界值。`run_noninferiority(df, spec)` 只在通過資料邊界時執行。

令原始效果 `D = mean(treatment) - mean(control)`，改善方向 `s=+1`（越高越好）或 `s=-1`（越低越好），則 `B=sD` 為有利方向差異，`M>0` 為 margin。虛無假設為 `B <= -M`，對立假設為 `B > -M`。

執行使用 SciPy `ttest_ind_from_stats`，明訂 `equal_var=False` 與單側 `alternative="greater"`，對均差加入 margin 後檢定零界值。標準誤為兩組 `sample_variance/n` 相加後開根號，自由度採 Welch–Satterthwaite。下限為 `L = B - t_(1-alpha,df) × SE`，與檢定使用同一標準誤、自由度及 alpha。[SciPy 官方介面](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind_from_stats.html)

非劣性通過需同時滿足 `p < alpha` 和 `L > -M`。界值等號不通過；統計量接近臨界值（相對容差 `1e-10`、絕對容差 `1e-12`）會明確回傳 `boundary_not_demonstrated`。若非邊界情形出現檢定與 CI 決策不一致則報錯，不產生成功結論。零變異數、非有限推論不會以加值或其他估計法替代。

一般 superiority 的 `p > .05` 不是非劣性證據；NI 未通過也不等於已證明劣效。`status="completed"` 只代表計算完成，實際結論必須讀取 `noninferiority.passed` 和 `decision`，不能用節點「完成」取代統計決策。

## 結果及可追溯性

結果使用 `clinical-result-v1`、`method_schema="independent-noninferiority-v1"`：

- `groups`：control／treatment 各組原始代碼、n、樣本變異數、均值與來源列。
- `noninferiority`：有利方向差異與原始 treatment−control 差異、單側 p、SE、df、單側下限、margin、方向、alpha、明確 decision。上限為 `null` 並註明 `upper_bound_kind="unbounded"`，不輸出 JSON Infinity。
- `case_ledger`、逐列 `observations`、完整 spec／來源／receipt hashes、NumPy／pandas／SciPy 版本。
- 單一預定假設與明確 multiplicity 範圍；不涵蓋多終點、反覆查看、等效性或事後 superiority 切換。

## 為何本版不開放 binary risk-difference NI

2026-10-15 在已安裝 statsmodels `0.15.0`、SciPy `1.16.3` 的合成邊界核對中，觀察到特定非零虛無差值的 constrained probability 未滿足原始二項 likelihood 的一階條件。官方 source 同時可見這段係數：`tmp1 = (count0 * diff - nobs - 2 * count0) * diff + count`。這是本版暫停該方法的具體證據，不是對其他 statsmodels 方法的全面否定。[官方 score-test source](https://www.statsmodels.org/stable/_modules/statsmodels/stats/proportion.html#score_test_proportions_2indep)

合成 fixture：treatment 90/100、control 88/100，虛無差值 `-0.10`，`compare="diff"`、`correction=True`、`alternative="larger"`。本機函式 source SHA-256：`b6d4c6adf6b64dcc6f9418ea7675a234e9d97a119a269806de6f97b938d46098`。

| 核對量 | 套件輸出 | 獨立 likelihood 核對 |
| --- | ---: | ---: |
| 虛無下 p1 | 0.815850933317849 | 0.819939137494906 |
| 虛無下 p2 | 0.915850933317849 | 0.919939137494906 |
| 對 p2 的 log-likelihood 導數 | 9.491866159659963 | 約 1.42e-13 |

在 `p1=p2-.1` 下，直接微分可得 `90/p1 - 10/(1-p1) + 88/p2 - 12/(1-p2)`；內點最大值必須為零。獨立檢查使用 scalar likelihood 最佳化及該導數求根確認同一內點。套件在此例回傳 z `2.510655678603107`、**單側** p `0.006025358689814088`，但虛無參數的一階條件不符，因此不把這些輸出當成已驗證的 binary NI 結果。

這份 discrepancy 記錄只作文件證據。RDE 不修補／覆寫套件 cubic、不自建 constrained-score estimator，也不改用 Wald、Welch 或 pseudo-counts。「binary unsupported」有獨立拒絕測試，待成熟套件與獨立數值驗證都符合後才能另行擴充；目前不能宣稱完整 binary NI 支援。

## 驗證範圍

`tests/test_clinical_noninferiority.py` 用有理數手算均值／變異數／Welch 公式，再以 incomplete-beta 恆等式核對 t 上尾與反演臨界值；沒有拿同一 `ttest_ind_from_stats` 呼叫當獨立答案。涵蓋正負統計量、方向與組別反轉、原始單位換算、margin 邊界不通過、來源重排、缺失列追溯、異常原始值、零變異數、binary 請求拒絕與完整 JSON 收據。這些是合成資料的軟體驗證，沒有提供真實研究的 margin 合理性、缺失機制或外部效度證明。


## 原生 MCP 整合與投稿成果

計畫以單一 `run_clinical_study` bundle 保存完整 `clinical_options`；頂層必須使用 `missing_strategy="listwise"`、`multiple_comparison_method="none"`，且 `alpha=one_sided_alpha=1-confidence_level`。雙側 CI 混用、binary 方法、未宣告角色或與鎖定計畫不同的 margin 皆拒絕。

計算先保存數值收據，再產生研究報告／五張 CSV 與兩組投稿圖：個案流量表、含 NI 界線與單側無界信賴集合的均差圖。每圖提供英文 SVG／PDF、300 dpi PNG／TIFF、英文圖說、中文解釋與實際繪圖數據。非劣性未通過與界值結果也可正常完成報告，不能用 readiness 或完成狀態篩掉陰性結果。

重取與重新出圖驗證 spec、來源檔、載入資料及成果 hash；不同來源要求另立分析分支。renderer 中斷後可沿用已保存數值補圖，沒有重新估計。`render_publication_figures` 建立新的圖版，保持原收據與繪圖數據不變。

`tests/test_noninferiority_workflow.py` 實際透過 `create_server().call_tool` 執行 inspect、計畫註冊、run、collect、report、publication；核對陽性／陰性／界值結果、鎖定與三種 hash 邊界、圖片格式與畫布、renderer 恢復及禁止重估。此範圍屬原生 MCP 整合驗證，不宣稱網站瀏覽器或 Qwen 已通過端到端測試。
