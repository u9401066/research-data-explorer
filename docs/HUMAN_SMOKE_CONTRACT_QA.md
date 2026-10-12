# 平台真人操作 smoke：RDE 契約修正

2026-10-12 分階段進行中，版本維持 0.5.2。配合 Research Workbench 的實機瀏覽器操作，真實 qwen3.8／官方 Harness 暴露下列契約缺口：模型把規則理由當作已執行的納排，獨立核對回合也誤解 coverage、可得時間及 exclude_statuses。

data_preparation contract 新增 execution_semantics，說明單一 cohort predicate、右表固定常數 filters、精確相對時間、基線可得時間內建限制、涵蓋狀態、整個分析單位排除、描述性角色與獨立事件彙總。這是現有引擎的執行語意，不新增臨床假設、不改計算演算法。平台草擬與核對保存並讀取同份 live 契約 hash。

canvas contract 新增由 host 保存狀態推導的 preparationUnready。未完成核對、核准、發布及採用的準備分支與後代不能建立分析計畫；拓樸相容不代表執行核准。Workbench 保存同份契約副本，兩端不一致會拒絕。

真實 UI 主路徑：CSV＋Excel 兩工作表，76 次住院／64 人 → 成人 74／62 → 首次住院 62／62；57 筆匹配，五種其他狀態各 1。62 列、930 個欄位以獨立 SQLite 答案比對；3 筆檢驗與 2 筆用藥獨立彙總，未生成 6 個人。CSV 下載以 1e-12 容差再次核對；識別碼保留前導零。原始來源包、個案／逐值追溯、核准與採用均由 UI 操作完成。

聚焦測試 tests/test_preparation_workflow.py、tests/test_preparation_engine.py、tests/test_canvas_contract.py：32 passed。完整套件與部署複驗另行記錄。合成驗證與模型核對不代表真實臨床連結已由資料管理者核實。

## Readiness report correction

The live UI run found S-007 treating outcome–predictor association as predictor collinearity. Exclude the declared outcome from the continuous predictor screen; an explicit empty column list must check no columns. Wording now states pairwise screening rather than claiming VIF or absence of multicollinearity. Five focused tests passed, including the MCP readiness scope integration. The original report remains retained; a new real UI execution verified only age/lab_mean are screened; the outcome remains excluded, while the numerical analysis is unchanged. Previous full suite: 1,091 passed, 76 skipped, 5 deselected (vendor integration excluded).

## 已核准分析的自主探索埠

2026-10-12 實機迴歸畫布仍提供探索入口，但平台 API 已禁止依顯著性重選模型。共同契約新增 `explorationSupported` 與 `baselineCompleted`，由 host 的保存計畫／工作推導；`explore` 同時要求已核准計畫、適用方法及該版已完成分析。不是以同研究的任意完成工作代替。RDE 仍驗證完整布林事實與 port 規則，native 執行仍保有資料版本與方法限制。

聚焦 canvas 4 tests passed；Workbench 的真正外部 MCP 全節點／轉換／階段矩陣一致。既有共線性修正後完整套件 1,093 passed、76 skipped、5 deselected；此次新增契約測試另驗。Web 前端、Agent 背景與 API 使用相同方法資格判定，未開放鎖定方法的泛用探索。

補充：實機 readiness 將類別水準 M／F／A／B 誤列為不存在的變項。變項收集器改為只接受明示變項欄位下的字串，仍遞迴尋找巢狀設定；不再把 levels 等任意陣列當作欄名。6 項聚焦回歸包含真正遺失欄名仍須列出，數值分析不受更動。前一契約版本完整套件 1,094 passed；此補充提交另跑完整檢查。

最終 RDE 完整回歸（含類別水準修正）：1,095 passed、76 skipped、5 deselected，489.62 秒；pre-commit 全通過。extension lint／40 tests／VSIX package／validate 全通過。平台實機另完成真 Qwen 全自動計畫修訂核准執行、配對樣本數 34／38 的方向修正、統計 autoresearch 停止重啟續跑，並以獨立數值實作核對結果。原版 GPU worker 無可用 profile，沒有宣稱訓練已驗證。部署與完整證據索引見 Workbench `docs/HUMAN_SMOKE_QA_20261012.md`。
