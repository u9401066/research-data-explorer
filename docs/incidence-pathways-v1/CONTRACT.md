# TriNetX 公開分析範圍參考：發生／盛行與治療路徑 v1 候選契約

狀態：**設計與 synthetic SQL oracle 已核對；尚無 native MCP 執行能力。** 原始程式盤點固定於 `6c620bb62223a20e6eab97e1c96e5f5542e7c8f6`；本文件與小案例為設計證據，不註冊可執行分析工具。沒有改動 RDE runtime、catalog、平台、matching 分支或任何真實研究成果。核對日為 2026-10-15。

目的：沿用成熟 Python 套件與現有 RDE 來源／計畫／成果契約，補足 longitudinal denominators 和 treatment episodes。這是通用、可追溯的研究定義，**不能宣稱重現 TriNetX 的數值、內部演算法、詞彙對映、隱私抑制或資料完整度**。

## 1. 官方七類與本次邊界

[TriNetX 官方 Advanced Analytics](https://trinetx.com/solutions/trinetx-live/advanced-analytics/) 現列七類：

| 官方類別 | 此次核對的公開能力摘要 | 本次契約責任 |
|---|---|---|
| Advanced explore cohort | 以 index 前後指定時間窗描述族群 | 重用明確 index／時間窗與分母，不另做全功能盤點 |
| Analyze outcomes | 整體風險、時間事件、檢驗分布及事件頻率 | 初發率與風險必須分清；不把重複紀錄當初發 |
| Compare cohorts | 比較特徵、檢驗與資料可取得性 | 後續比較必須沿用相同族群定義 |
| Compare outcomes | 比較風險、HR、事件與檢驗結果 | 本版不添加新的比較估計器 |
| Incidence and prevalence | 多個期間與人口學分層 | 本文件的第一個候選 family |
| Treatment pathways | 治療使用、順序、期間及轉換 | 本文件的第二個候選 family |
| Competing risks | 多種互斥事件的發生機率 | 死亡不可在固定期限風險中任意刪除或當獨立失訪 |

官方上述頁面沒有公開：初發 washout／分母規則、同時事件優先順序、coverage 推導、處方重疊、grace、療程分線或各步分母。因此下面每個規則都是 **RDE 候選契約的明確決策**，不是 TriNetX 的既定實作。七個類別名稱相同也不代表所有子功能均已實作。

## 2. 兩個 family 共用的輸入及來源契約

### 2.1 必要角色

| 表 | 唯一單位與必填欄位 | 不能從資料外觀推定的資訊 |
|---|---|---|
| `people` | 一人一列；非空 lexical `subject_id`；`index_at`；死亡時間可空但須死亡資料取得性宣告；預先固定 strata | 隨機性、clinical eligibility、index 的臨床意義 |
| `observation_intervals` | 唯一 `coverage_id`、subject、`start_at`、`end_at`、domain、完整度／依據 | 首末就醫日期不自動表示中間完整可觀察 |
| `events` | 唯一 `event_id`、subject、`event_at`、endpoint code、原列 ref | 診斷紀錄不自動等於新發疾病／新 episode |
| `condition_states` | 唯一 `condition_id`、subject、active start/end、狀態定義／取得性依據 | 一次 diagnosis code 不代表之後永久 active |
| `treatment_exposures` | 唯一 exposure ID、subject、原碼、已審閱 class 對映、start/end、duration basis | 處方、領藥、實際給藥或依從性不能混為一談 |

發生／盛行依所選 measure 要求 events 或 condition_states；治療路徑要求 exposures。不得為了湊欄位，自行從診斷建永久疾病狀態、從單次處置填一日療程、從下一次處方猜療程終點。現有的資料準備可產出研究定義，但仍須保留規則與審閱。

每張表均綁定 exact source SHA、bytes、sheet／parser、source set SHA、preparation release SHA、角色欄位對映、列 ref（source ID + source SHA + record index + row SHA）。來源期間 `source_period=[start,end)` 與 `data_cutoff` 必填；檔案更新或 parser 更新不沿用舊分析。

### 2.2 時間、coverage 及資料品質規則

- v1 使用已確認精度的 UTC instants，區間統一 `[start,end)`，秒差除 86,400 得人日；顯示人年時使用契約明訂的 `days_per_year`（例如 365.25），不得暗改尺度。只有日期的來源先在準備階段明訂時區與 inclusive-date → exclusive-end 轉換，保留原日期精度，不能宣稱知道同日事件先後。
- 同人、同 domain 的 complete coverage 區間只合併重疊或相接者；有正長度缺口不得填補。合併需 running maximum end，單純比較上一列 end 會誤判巢狀區間。unknown/not_exported/link_failed 均不能建立無事件或無治療。
- coverage 的「完整」是研究可用性的有依據宣告，不是觀察系統全知。須記錄 enrollment、closed claims、reviewed EHR approximation 等來源及限制；若只是 EHR 首末接觸，要求明確審閱其假設，不由 agent 自動寫成 complete。[OMOP observation-period 原始規範](https://ohdsi.github.io/CommonDataModel/cdm54.html#observation_period) 與 [EHR coverage 考量](https://ohdsi.github.io/CommonDataModel/ehrObsPeriods.html) 提供這個區分，並非要求採用 OMOP runtime。
- 非法 subject/code、孤兒鍵、非有限或無法解析的時間、反向／零長區間、同 ID 不同內容，**先於任何納排檢查而阻擋**。完全相同來源重複也不得默默雙算；v1 預設阻擋，若經準備層明示去重則保留全部 duplicate refs。
- 死亡、coverage 結束、行政期末同時時，terminal reason 優先順序固定為 death → coverage_end → administrative_end，另保存全部同時觸發原因。事件恰等於 censor/end 在 half-open 規則下排除，另列 boundary ledger；同日精度無法解答研究所需順序時，不用隨機 tie-breaking。
- v1 固定 baseline cohort，沒有 delayed entry 或失訪後 re-entry；多個時間窗各自重新計算 eligibility／washout，不能將重疊窗的人數相加當獨立樣本。人口學 strata 用 baseline 固定值、明確 levels 與 unknown 組；不由模型補 race、sex、ethnicity。先支援分層描述，不附上未核准的多重比較 p 值。

## 3. `incidence_prevalence` 候選 v1

### 3.1 精確 measure 與數學定義

令研究窗為 `[a,b)`；`O_i` 為 outcome-domain 可觀察區間 union；`d_i` 為死亡時間，無已知死亡時為 infinity（須揭露死亡取得性）。`u_i` 為包含 `a` 的連續 coverage 區間終點；`c_i=min(b,u_i,d_i,source_end)`。來源必須涵蓋所要求的期間，不能把缺少的 source history 當陰性。以下的 true/false 均基於有 coverage 的觀察定義，不能外推為所有生物學發病。

| `method` | 分子／分母及 gate | 對外名稱 |
|---|---|---|
| `first_recorded_incidence_rate` | baseline eligible 集合 `I`：活到 a、完整連續 coverage 包含 `[a-L,a]`、已匯出的可確認歷史中沒有 `event_at<=a`、符合納排。`t_i=min{t:a<t<c_i}`。`D=Σ 1(t_i exists)`；`T=Σ(min(t_i,c_i)-a)/86400`，無 t 使用 c。`rate=D/T`。T 必須 >0。 | 首次紀錄發生密度（指定 washout）；不是 lifetime first onset |
| `full_followup_incidence_proportion` | 同一 I；僅當所有人在首事件前均無提早 coverage loss，且本版無期末前 competing death 時，回傳 `D/|I|`。否則 measure `unavailable`，保留全部原分母及理由，不能刪除失訪者再報風險。 | 固定期間初發比例；本版的保守適用界線 |
| `point_active_prevalence` | 點 p 的 eligible `P`：alive(p)、p 在完整 coverage 中、active-condition 狀態可取得。分子為 `Σ1(∃ state:[s,e),s<=p<e)`；分母 `|P|`。同人多個 overlapping state 只算一次。 | 指定點、可觀察族群的 active-condition 盛行比例 |
| `period_active_prevalence` | baseline alive，從 a 連續可觀察至 `min(b,d_i)` 且狀態可取得的集合 Q。分子為 Q 中至少有一個 state 與 `[a,min(b,d_i))` 正長度交集者；分母 `|Q|`，期間死亡者保留在分母，death timestamp 開始的 state 不算。 | 對完整可觀察至期末或死亡者的期間盛行比例；不是全體原始族群估計 |

L 是**有研究依據的預先指定 washout**，不是確認終生無病。只要有明確 prior case，即使早於 L 也排除於初發族群；coverage 不足者另列。尚無 active interval 的診斷資料只能另作「期間紀錄到該診斷的比例」，不得冒稱 active prevalence。v1 不自動以預設 persistence 將診斷建立疾病歷程。

期間盛行的 Q 會排除中途 unknown coverage 者，這是明示的目標族群限制與潛在 selection bias；報告必須同時提供 baseline N、各原因排除 N、Q，以及在排除人中已觀察到的 positive／未知數量（不納入 Q 的分子）。不可用可觀察 subset 的結果宣稱全院或總人口盛行率。

初發率保留死亡前人時；死亡與疾病可能競爭，因此 rate **不是**在某期限內發病的機率。需要有競爭風險的 cumulative incidence 時，應另建已核准 competing-risk plan，而不是偷偷用 KM 或刪除死亡者。簡單 `D/N` 在失訪時不會自動獲得風險解釋。[CDC morbidity measures](https://archive.cdc.gov/www_cdc_gov/csels/dsepd/ss1978/lesson3/section2.html) 提供初發比例、人時率、點／期間盛行的概念區分；本表中的特定 coverage gate 是 RDE 的界線。

### 3.2 重複事件與統計套件

- 每位 eligible person 在該窗最多一個 incident case。相同時間的多筆臨床紀錄保留全部 witnesses，但只計一人；重複事件與 censor 之後的事件各自列 ledger，不能把 3 次回診當 3 個初發。
- 本版**不提供 recurrent-event incidence rate、gap-time 模型或計數 Poisson p 值**。若研究定義需要復發，要先定義新 episode／間隔與 intra-person dependence，再採核准模型；不是將分子從人改成紀錄數就完成。
- `statsmodels.stats.rates.confint_poisson(D,T,method="exact-c",alpha=1-confidence_level,alternative="two-sided")` 用於 rate 的 **working Poisson** count interval。其 exact 指 Poisson count inversion，不代表異質危險率、依賴事件或 informative censoring 下具有精確臨床覆蓋率。0 events + positive T 保留 rate=0 與正上限；T=0 則 unavailable，不能加 0.5。[官方 API](https://www.statsmodels.org/stable/generated/statsmodels.stats.rates.confint_poisson.html)
- `statsmodels.stats.proportion.proportion_confint(D,N,method="wilson",alpha=1-confidence_level,alternative="two-sided")` 用於適用的比例，獨立個體的近似二項區間。N=0 unavailable；D=0 或 D=N 不切換到 Wald。[官方 API](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html)
- v1 沒有 age standardization、national weighting、抽樣權重、相依／叢集調整、rate ratio 或多重假說比較。分層只是按固定 baseline levels 分別回傳分母，不聲稱各 CI 是 simultaneous。

### 3.3 候選 schema 與結果

```json
{
  "schema": "incidence-prevalence-spec-v1",
  "family": "incidence_prevalence",
  "input_release": {"release_id": "immutable_temporal_bundle", "release_sha256": "64hex"},
  "methods": ["first_recorded_incidence_rate", "point_active_prevalence"],
  "subject_role": "people.subject_id",
  "endpoint_definition": {"code_set_sha256": "64hex", "basis": "reviewed clinical definition"},
  "coverage_domain": "endpoint",
  "source_period": ["UTC start", "UTC exclusive end"],
  "windows": [{"id": "period_1", "start": "UTC instant", "end": "UTC instant"}],
  "prevalence_points": ["UTC instant"],
  "washout_seconds": 31536000,
  "prior_case_policy": "any_recorded_history_including_index",
  "reentry": "disabled",
  "event_at_censor": "exclude_and_ledger",
  "confidence_level": 0.95,
  "rate_ci": "poisson_exact_c_working_model",
  "proportion_ci": "wilson",
  "strata": [],
  "definitions": {"population": "required", "outcome": "required", "observation_basis": "required", "washout_basis": "required"}
}
```

上例表示欄位形狀，不是合法可執行 request；示意時間、hash 不得通過實際 preflight。methods 依 roles 檢查，不能讓沒有 state 的輸入獲得 prevalence 能力。source_period 外的要求應 fail closed；未知 coverage 保留排除，不自動延伸。

`preflight` 應回傳 source／spec／dataframe-set／design hash、role 檢查、各 source rows/subjects、初步 eligibility、unknown coverage N、boundary diagnostics、可估的 measures、阻擋原因；不得把 can_execute 解讀為已核對真實臨床定義。`run` 回傳 `clinical-result-v1` + `incidence-prevalence-study-v1`，每個 period/stratum/measure 各有 `status`, numerator, denominator（人或人日明示）, value, CI, unit, scope、package versions。全域 n 只代表 baseline subjects，不能拿人日或所有分層的人數總和填入。

必要 artifacts：`participants.csv`（每人每窗 eligibility、停止原因、first_event refs、人時）、`coverage.csv`（union 及來源 refs）、`event_dispositions.csv`、`prevalence_membership.csv`、`measure_summary.csv`、`trace.jsonl`、英文 cohort flow／rate-and-prevalence plots、英文 caption 與另列中文 context。率與比例不得共用沒有單位的 y 軸；unavailable 不畫成 0。

## 4. `treatment_pathways` 候選 v1

### 4.1 有界定義

此版處理 **recorded treatment exposure-state trajectories**，不是自動推論腫瘤 line of therapy、用藥 adherence、換藥理由或因果療效。同一類藥的用途須有明確 class mapping，原始名稱／代碼仍保留。具有可確認 start/end 的處置期間可用相同 interval 模式；單次瞬時 procedure 只有 utilization／時間序列資訊，**尚不能用此 duration 模式冒充一日療程**。完整涵蓋官方「medication and procedure order」還需要後續獨立的 point-event sequence 契約與 fixture。

每個人只有一個 reviewed index，從 `[index,index+horizon)` 的第一個連續 treatment-domain coverage 區間開始，遇死亡、coverage end 或行政結束即停止。baseline 不在 coverage 中者不進路徑、另列原因。第二段 coverage 不接回來，也不把 gap 畫成停藥。死亡取得性、index、followup 與 exposure interval 必須明確。

1. **原 exposure**：保留 source start/end；clip 到可觀察 followup，保留 clipped-left/right 與來源理由。允許 carry-in，但標記為 index 前已開始；這不是 new-user cohort。未知終點不套下一張處方、期末或中位療程。
2. **同 treatment class 的 episode**：先 union 重疊／相接 intervals，不累加重疊天數、不 stockpile。相隔 `gap<=persistence_gap_seconds` 可在已核准規則下合併；gap 是 **assumed persistence**，另保存 gap 的前後 exposure IDs、長度，以及原始 observed exposure duration。不可把 grace 時間說成實際服藥。
3. **重疊治療**：不同 class 同時有效時 state 是 canonical sorted set，例如 `A+B`，不任意選「主要藥」。所有 classes 的 start/end 邊界切成不重疊 segments，再合併相鄰且相同 state；每個 episode 是最大連續 constant-state 區間。
4. **無紀錄**：在確定 treatment-domain 完整觀察區間內，空集合顯示 `NO_RECORDED_TREATMENT`（fixture 縮為 NONE）；其意義仍是指定 class 範圍內無紀錄，不是保證沒有任何治療。未匯出與 coverage unknown 用獨立排除／terminal，不能顯示 NONE。
5. **轉換**：`A→B` 是 observed replacement；`A→A+B` 是 addition；`A+B→B` 是 removal；`A→NONE` 是 observed exposure ending；`NONE→A` 是 observed initiation/resumption。這些是資料狀態，不是臨床原因。中間有 NONE 時，不略過 gap 直接叫 switch。
6. **終點**：`death`, `coverage_end`, `administrative_end` 是 terminal，與下一個 treatment episode 分開。遇 truncation 不宣稱該療程已完成；observed segment duration 為部分可觀察長度，不自動估計完整療程的 median survival time。

本版只支援明示 gap、固定無 stockpiling 的 interval rules，沒有 dose escalation、組合療程容忍期、最短有效藥日數、不同病種的 LOT 引擎或自動依 p 值調規則。[OMOP drug-exposure／era 規範](https://ohdsi.github.io/CommonDataModel/cdm54.html#drug_era) 說明 persistence window 與實際 gap time 並不相同；這裡不沿用其預設天數，也不依賴 OHDSI 執行套件。

### 4.2 每一步分母、顯示與 trace

令 eligible 有 N 人。每人有 K_i 個可觀察 nonterminal episodes；`N_k=Σ1(K_i>=k)`。第 k 步 state s 的節點人數 `n_ks=Σ1(K_i>=k and state_ik=s)`，節點提供 **`n_ks/N_k` 與 `n_ks/N` 兩個清楚命名的比例**。N_k 不是該時間點的 survival risk set；每人的第 k 次轉換可能發生於不同時間。

從節點 (k,s) 的每個人必須有下一個 state 或一個 terminal，所以 `Σ_destination n(k,s→destination)=n_ks`，含死亡／失聯／期末，禁止省略 terminal 讓線寬看似所有人都換藥。同人可在不同 step 重現相同 state，跨 step 加總不是獨立人數。

若 UI 為樹狀路線，node identity 需含 `(step, full_prefix)` 才保留完整歷程；若以 `(step,state)` 合併為 Sankey，必須標註已彙總不同前史，提供查詢到個體 path。長路徑只可顯示折疊／截斷標記，完整 trace 與每步人數仍可下載。不能把變更配色或 episode 次序當成新的研究。

利用率另外算 `unique users with any observed exposure / N`，不是把各 episode 人數相加。期間表同時輸出 raw union drug-time、grace-bridged era-time、state-time；同一個 combination 的 A 與 B drug-time 可各計一次，但 state-time 加總必須等於總可觀察人時。不同 censoring 下的 average observed duration 僅是描述，不比較完整療程長短。

每一 episode trace 至少包含 subject ID、ordinal、state、start/end、carry-in／truncated flags、direct exposure refs、episode union dependency refs、bridged-gap refs、coverage refs、停止原因。NONE 的來源是 coverage 證據與全 exposure inventory 查詢規則，不是造一筆「未治療」來源列。terminal 保留所觸發的死亡／coverage／source cutoff refs。

### 4.3 候選 shape 與成熟實作路線

```json
{
  "schema": "treatment-pathways-spec-v1",
  "family": "treatment_pathways",
  "input_release": {"release_id": "immutable_temporal_bundle", "release_sha256": "64hex"},
  "method": "recorded_exposure_states",
  "subject_role": "people.subject_id",
  "index_role": "people.index_at",
  "coverage_domain": "treatment",
  "horizon_seconds": 31536000,
  "class_mapping_sha256": "64hex",
  "entry_exposure_policy": "include_and_mark_carry_in",
  "persistence_gap_seconds": 0,
  "bridge_policy": "assumed_persistence_with_separate_gap_ledger",
  "overlap_policy": "same_class_union_distinct_class_combination",
  "stockpiling": "disabled",
  "reentry": "disabled",
  "terminal_priority": ["death", "coverage_end", "administrative_end"],
  "definitions": {"population": "required", "index": "required", "exposure_basis": "required", "duration_basis": "required", "persistence_basis": "required"}
}
```

候選方法不需自製統計引擎：Pandas 的排序、groupby/cummax、interval boundary table 加上現有 Python datetime 完成有限集合與區間代數；SQLite 標準函式庫提供**獨立測試 oracle**。不是透過 agent 寫 SQL／Python 去改真實資料。圖由現有 Matplotlib 輸出向量 SVG/PDF 與 300 dpi PNG。沒有 p 值或假造轉移機率模型；若未來需 survival-adjusted switching risk，必須另加模型與驗證。

`preflight` 檢查 exact source roles/refs、區間／對映完整度、coverage、可觀察族群、carry-in／未知時長／邊界數量、class 數與 projected segment resource budget；`run` 使用 `clinical-result-v1` + `treatment-pathways-study-v1`。n=eligible unique people；episode_count、transition_count、person_time 各有獨立欄位。結果包括 person ledger、raw intervals、era intervals、gap ledger、episodes、step denominators、prefix-aware transitions、utilization、terminal ledger、trace。資料與規則 hash 不一致時不重用舊圖。

## 5. 現有 RDE 可重用點與真正需要新增的界線

以下都是 baseline 6c620bb 的唯讀程式核對，並非宣稱新 family 已接上。

| 現有檔案／介面 | 可重用 | 此需求不能直接當作已有能力 |
|---|---|---|
| `src/rde/domain/models/preparation.py`：Source、Unit、Relation、Coverage、Window | lexical subject／複合鍵、record keys、明示 coverage、時間窗／availability、typed rules | Coverage 是 relation-level 或 root column 完整度，沒有 longitudinal interval union；需要 domain-specific temporal metadata |
| `src/rde/infrastructure/preparation/sources.py`：load、Table.ref、file_hash/digest | source snapshot、parser、row SHA、column refs、穩定序列化 | 不能將「有該檔案」等同整個研究窗完整觀察 |
| `src/rde/infrastructure/preparation/engine.py`：valid_rows、population、step、select_window、feature | 鍵與重複檢查、人／事件分母、flow、來源 cells/relations/exclusions trace、獨立事件先聚合避免笛卡兒乘積 | `count` 是紀錄數、非人數；`days_to_first` 不能代替完整 eligibility／人時。`followup_end_column` 現以 `event>followup_end` 排除，恰等於終點仍接受，不能直接用來實作本案 half-open censor 規則 |
| `src/rde/infrastructure/preparation/aggregation.py`：contract、compose／patch／preview | typed 操作、候選版本、來源漂移拒絕、語意完整度與 approval 分離 | 現有十種 aggregation 都輸出每單位一個 scalar，不提供 episode timeline。不可用一長字串或 JSON cell 偷塞患者整段歷程冒充 typed dataset |
| `src/rde/infrastructure/preparation/workflow.py`：draft、approve、release、trace | immutable intent、implementation inventory、source/spec/review/release hash、逐列可追溯與人數 flow | release 目前以一份 analysis.csv 為資料集；需要明示的 temporal bundle／table-role manifest，不能未驗證地讀旁邊資料夾其他 CSV |
| `src/rde/infrastructure/preparation/portable.py` | 可攜來源／規則／成果與 hash 核對模式 | 必須擴充 bundle contract 才能保證多張 temporal tables 都受 approval 和 source-set hash 約束 |
| `clinical` inspect/run/result/report/readiness 機制 | locked spec、正式執行、frozen numerical receipts、artifact integrity、publication caption、完成狀態 | 既有單一 dataframe 的 native binding 不能假裝是多表來源；不得讓 no-op table attach 通過 plan lock |

建議實作路徑：**RDE data preparation 先產出受控 temporal release → plan 選 incidence/prevalence 或 pathways typed spec → RDE native inspect/run → 平台只投影狀態與 artifact**。維持同一 RDE MCP，不需要另做一個自由碼代理服務。multi-table source authority 應先設計完成；可沿用現有 tool 名稱，但必須擴充 typed dispatch，不能在平台另寫不同的人時或 episode 算法。

結果 gate：source／code／catalog 變更須新執行；不因值為 0、NI 類陰性或所有人無治療而顯示工作失敗。某 measure unavailable 與來源不合法應分開：前者可以保留其他有效描述並清楚說明，後者在任何寫入／正式分析之前拒絕。正式 plan 尚未設計探索政策前，兩個 family 的 legacy inferential 與 autoresearch 入口應 fail closed；允許保留已核對資料的純描述圖，不以新模型替代正式結果。

## 6. 事先固定的 SQL 小案例及實測結果

`fixture.json` 的時間 tick 是自 `2025-01-01T00:00:00Z` 起的整數 UTC 日，乘 86400 可一對一換成秒；這是純合成、已知正確答案的 tiny fixture。`expected.json` 先以人逐一手算固定，`oracle.py` 使用獨立 SQLite queries 算區間 union、eligibility、病例、人時、episodes 與 transition；沒有呼叫 RDE 實作。

| 驗算項目 | 固定答案與用意 |
|---|---|
| 9 位來源病人，5 人初發 eligible | P3/P6 是 prior 或 index cases；P4 washout 不足；P7 coverage unknown |
| 首次發生／人時 | P1 event day 4；其他 P2=6、P5=7、P8=10、P9=10 人日；合計 D=1、T=37。P1 的第二次紀錄不新增病例 |
| 嚴格邊界 | P2 event 恰在 coverage end、P5 event 恰在 death、P9 event 恰在期末均另列排除；P2 再出現的第二段 coverage 不 re-enter |
| 巢狀／相接 coverage | P9 的 [-5,2)、[-3,1)、[2,10) 合成 [-5,10)，不能誤造中間缺口 |
| 固定期限風險 | 全體 5 人中有 early loss/death，unavailable。額外手算 subset P1/P8/P9 為 1/3，但**不替代原 target**；此數字只驗算限制 |
| 點盛行 p=2 | 8 人可觀察、P3/P6 active，共 2/8 |
| 期間盛行 [0,10) | 完整觀察至期末或死亡 7 人，P1/P3/P4/P6 有 active condition，共 4/7；P5死亡仍在分母 |
| Pathway 6 人來源 | T6 unknown coverage 排除；eligible 5 人、12 個 nonterminal episodes、36 人日 |
| overlap／grace | T1 A[0,3)+A[4,6) 以 g=1 接成 A[0,6)，明示 1 assumed day；加 B[5,8) 後路徑 A→A+B→B→NONE |
| 停藥與失聯 | T2 coverage day7 截斷 B；T5 day3 失聯，不把後續未觀察期間畫 NONE；T4 death day6 截斷 A |
| 每步分母 | N₁=5、N₂=3、N₃=3、N₄=1；每個節點所有 outgoing（含 terminal）人數恰等於該節點人數 |
| duration accounting | raw A=14、bridged A=15、B=6 人日；state A=14、A+B=1、B=5、NONE=16，共36；unique users A=4/5、B=2/5 |

首輪通過 **79 checks**：所有預先固定答案、5 次列序打亂（兩個 family）、trace 不變、轉換人數守恆、人時分割、duplicate／orphan／反向及零長區間／未知藥碼拒絕。套件數值另以 Python `NormalDist` 的 Wilson 明式與 finite Poisson CDF + `scipy.optimize.brentq` 反演比對；不以同一個套件函式互相比對。已驗 0/37、1/37、5/100 的 Poisson interval，0/8、2/8、4/7、8/8 的 Wilson interval；實際 statsmodels 0.15.0。

這個 oracle 驗證的是**固定定義的獨立小案例與套件數值邊界**，不是 RDE native MCP、Qwen、Canvas、臨床分母或 TriNetX 相容性驗收。不能將 79 checks 改寫成兩個 family 已上線。

重跑：

```bash
python3 docs/incidence-pathways-v1/oracle.py
```

## 7. Native v1 實作前仍需完成的驗收

1. temporal bundle 的 draft/review/approval/release、角色完整度、所有來源／spec／code／結果 hash 及 portable replay；不接受 ambient files。
2. fractional UTC times／date precision、不同時區／DST 正規化、boundaries、同時事件、缺失／非法碼先驗檢查、分層 unknown；上下文未提供的臨床定義留 unknown，不能由 agent 假造。
3. instance fixture 逐值對 SQL oracle；新增 zero denominator/zero events、同時多來源 event witnesses、巢狀藥物區間、gap threshold 前後、carry-in、source cutoff、死亡取得性 unknown 等實際 native 回歸；目前 scratch 不能取代這些測試。
4. locked plan 正常執行、重用、重啟、source/plan/artifact tamper 拒絕；未授權方法／legacy inference／autoresearch 無旁路。小案例 resource limits 以外須測記憶體與取消，不放任 agent 生成任意大 patient-day grid。
5. 真 MCP 報告／表／圖、人數／人時／比例單位與 unavailable 敘述；沒有 p 值的 pathway 不產生「顯著換藥」句子；英文投稿圖說、中文平台解釋，原始中文研究問題另列 context。
6. 平台資料清單、Canvas typed nodes、節點的分母與觀察窗、episode/terminal 的可視差異、prefix trace 與可下載原始帳本；Qwen 自動規劃必須使用 catalog advertised methods，不寫出還沒有的能力。
7. 真實資料管理者抽查部分病例、coverage 來源、事件／治療時長與總分母。高 match rate 或 SQL pass 不能取代臨床定義與資料完整性的核對。
