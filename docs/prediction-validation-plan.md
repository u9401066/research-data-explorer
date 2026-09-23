# 預測研究執行契約

目標：回溯研究可選關聯推論或預測建模；後者真正以訓練內模型比較、獨立保留資料驗證，取代樣本內 ROC 被當成已驗證模型的做法。

- RDE 新增 `run_prediction_study` MCP，固定來源、特徵、結果編碼、split、seed、候選、CV folds、閾值、信賴水準和 bootstrap 預算。
- 二元分類（regularized logistic / random forest）與連續結果（ridge / random forest）；候選只在訓練集 CV 比較，最後只評估所選模型的保留集。
- 隨機獨立列、受試者分组、時間 cutoff 分割。時間分割遇到跨界受試者，移除其訓練列，保留未來驗證列；內層時間 CV 也排除跨界個案。同一日期不拆進兩側。
- numeric median + scaling，categorical mode + one-hot 全部在各訓練 fold fit。全缺失訓練特徵、ID／時間欄位進入 predictors、缺失 split key、無效結果與不可估計分割要明確處理，不補結果值、不自動換 seed。
- 保存來源零起始列位置、排除原因、每 fold／candidate 成敗、訓練轉換參數、選擇準則、保留集 predictions、版本及 hash；每個圖表/報告取回完整來源。
- Binary: AUROC、average precision、Brier、log loss、固定閾值 confusion、calibration；continuous: MAE/RMSE/R²、residuals。CI 為固定模型下的驗證集（必要時 subject-cluster）bootstrap，非重新訓練不確定性或外部驗證。
- 報告走預測專用完整性檢查，不能為湊一般 EDA 方法／圖表數量而對保留集加上不相關檢定。保留 RDE 概念／計畫確認、readiness、decision、collect/report/audit/export 階段。
- Workbench 型別化表單、計畫參數、graph candidate branches、下載/檢索/局部討論與說明。一般關聯探索不得在預測研究中重用全資料；模型探索限制在預定訓練 CV。

驗證必須包含：更改保留集數值不改訓練轉換／CV 選擇、subject 與時間不重疊、missing/categorical unseen處理、失敗不製造效能、原始資料不變、實際 MCP/瀏覽器與重啟取回。以 scikit-learn 1.9.1 官方 Pipeline／CV 契約及 TRIPOD+AI 作報告參考，不宣稱自動符合所有臨床適用要求。

來源：[scikit-learn CV](https://scikit-learn.org/stable/modules/cross_validation.html)、[Pipeline](https://scikit-learn.org/1.8/modules/compose.html)、[TRIPOD](https://www.tripod-statement.org/)。

2026-09-23：RDE 核心與 MCP 已實作並通過完整 Python suite（451 passed、5 個外部整合 skipped）與 extension suite（40 passed）；公開工具契約共 51 項。預測專用 21 項回歸涵蓋資料隔離、真實 MCP 收斂／報告、已看過保留集的重用限制、圖表失敗後復原而不重訓。Workbench 瀏覽器與部署驗證另記錄於其 QA 文件。

執行上限：200,000 列、50 個原始特徵；每個訓練類別特徵至多 200 種值，編碼特徵預算 5,000。隨機森林固定 64 棵、深度 8、葉節點至少 5 列，全部估計器限制單執行緒。每個訓練／驗證 partition 至少 20／10 列只是軟體執行門檻，並非臨床樣本數論證。時間預算為 300 秒，呼叫端仍須終止無法消費取消通知的同步運算程序。

完整數值先保存後產圖；圖表故障可從保存結果繼續。完成研究再次呼叫只檢查並讀取原 receipt，來源或設定改變會拒絕。JSON 保留 SHA256、每個 CV split 與 fit、bootstrap seed／抽樣 hash；CSV 保留所有驗證觀察列及預測。報告區間對可估计 bootstrap 少於 20 次者不顯示上下界，0 次代表停用區間估計。
