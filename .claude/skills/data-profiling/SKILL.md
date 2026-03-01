---
name: data-profiling
description: "Data profiling and schema analysis workflow. Use when user wants to understand data structure, quality, distributions. Triggers: profiling, schema, 資料品質, data quality, describe, 看資料, overview, 概況."
---

# Data Profiling Workflow

## 描述
Phase 2 的資料 profiling 工作流，包括型別推論、品質評估、統計前提檢查。

## 觸發條件
- 「看看資料長什麼樣」「資料品質如何」「profile」「schema」

## 流程

### Step 1: 載入資料
```
load_dataset(filepath)
→ 自動推論型別、識別 PII
```

### Step 2: Schema 建構
```
build_schema()
→ schema.json: 變數名稱、型別、基礎統計
```

### Step 3: 完整 Profiling
```
profile_dataset(dataset_id)
→ 嘗試 ydata-profiling
→ 如不可用 → 自動降級為 basic-fallback engine
```

### Step 4: 品質評估
```
assess_quality(dataset_id)
→ quality_report.json: 品質問題 + 嚴重度
```

## 自動檢查

| Constraint | 檢查內容 | 動作 |
|-----------|----------|------|
| S-001 | 各數值變數的常態性 | Shapiro-Wilk / K-S |
| S-004 | 偏態分佈 | 建議 log/sqrt 轉換 |
| S-005 | 缺失模式 | MCAR/MAR/MNAR 判斷 |
| S-006 | 極端值 | skewness/kurtosis 評估 |
| S-007 | 多重共線性 | VIF 計算 |
| H-004 | PII 偵測 | 自動標記可疑變數 |

## 輸出

每段分析都附加 Agent 建議：
```
📊 變數 `age`
- 類型: continuous
- 缺失: 3.2%
- 常態性: Shapiro-Wilk p=0.034 (非常態)
  💡 [S-001] 建議使用無母數檢定
  💡 [S-004] 偏態 1.23 → 考慮 log 轉換
```
