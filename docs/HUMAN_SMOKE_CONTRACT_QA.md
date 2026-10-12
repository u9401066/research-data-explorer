# 平台真人操作 smoke：RDE 契約修正

2026-10-12 分階段進行中，版本維持 0.5.2。配合 Research Workbench 的實機瀏覽器操作，真實 qwen3.8／官方 Harness 暴露下列契約缺口：模型把規則理由當作已執行的納排，獨立核對回合也誤解 coverage、可得時間及 exclude_statuses。

data_preparation contract 新增 execution_semantics，說明單一 cohort predicate、右表固定常數 filters、精確相對時間、基線可得時間內建限制、涵蓋狀態、整個分析單位排除、描述性角色與獨立事件彙總。這是現有引擎的執行語意，不新增臨床假設、不改計算演算法。平台草擬與核對保存並讀取同份 live 契約 hash。

canvas contract 新增由 host 保存狀態推導的 preparationUnready。未完成核對、核准、發布及採用的準備分支與後代不能建立分析計畫；拓樸相容不代表執行核准。Workbench 保存同份契約副本，兩端不一致會拒絕。

真實 UI 主路徑：CSV＋Excel 兩工作表，76 次住院／64 人 → 成人 74／62 → 首次住院 62／62；57 筆匹配，五種其他狀態各 1。62 列、930 個欄位以獨立 SQLite 答案比對；3 筆檢驗與 2 筆用藥獨立彙總，未生成 6 個人。CSV 下載以 1e-12 容差再次核對；識別碼保留前導零。原始來源包、個案／逐值追溯、核准與採用均由 UI 操作完成。

聚焦測試 tests/test_preparation_workflow.py、tests/test_preparation_engine.py、tests/test_canvas_contract.py：32 passed。完整套件與部署複驗另行記錄。合成驗證與模型核對不代表真實臨床連結已由資料管理者核實。
