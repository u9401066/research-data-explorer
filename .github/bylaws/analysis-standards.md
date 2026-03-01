# Analysis Standards Bylaw

> Version: 1.0.0 | 依據：CONSTITUTION.md Article II §6

## §1 統計前提檢查

### 1.1 常態性 (S-001)

| 樣本量 | 檢定方法 | 閾值 |
| ---- | ---- | ---- |
| n < 50 | Shapiro-Wilk | p < 0.05 → 非常態 |
| n ≥ 50 | Kolmogorov-Smirnov | p < 0.05 → 非常態 |

非常態 → 使用無母數檢定（Mann-Whitney U, Kruskal-Wallis 等）。

### 1.2 等變異數

組間比較前需 Levene's test：
- p < 0.05 → 使用 Welch's t-test 或其他修正

### 1.3 獨立性

- 配對設計 → 配對 t-test / Wilcoxon signed-rank
- 獨立設計 → 獨立 t-test / Mann-Whitney U

## §2 多重比較校正 (S-002)

| 比較數 | 建議方法 |
| ---- | ---- |
| 2-5 | Bonferroni |
| > 5 | Benjamini-Hochberg (FDR) |

Agent 必須在結果中顯示校正前後的 p 值。

## §3 效果量 (S-009)

### 必須報告效果量

每個統計顯著的結果**必須**附帶效果量：

| 檢定 | 效果量 | 小/中/大 |
| ---- | ---- | ---- |
| t-test | Cohen's d | 0.2 / 0.5 / 0.8 |
| Mann-Whitney U | rank-biserial r | 0.1 / 0.3 / 0.5 |
| Chi-square | Cramer's V | 依 df |
| ANOVA | Eta-squared η² | 0.01 / 0.06 / 0.14 |
| Correlation | r | 0.1 / 0.3 / 0.5 |

### 臨床意義

- p < 0.05 但效果量 < 小 → 提醒「統計顯著但臨床意義可能有限」
- p ≥ 0.05 但效果量 ≥ 中 → 提醒「可能 underpowered」

## §4 檢定力分析 (S-010)

### Post-hoc Power

- 非顯著結果 + n < 100 → 自動計算 post-hoc power
- Power < 0.80 → 標記「可能 Type II error」

### 樣本量建議

- 如計算出 power < 0.80，附帶「達到 0.80 power 所需 n」

## §5 缺失值處理 (S-005)

### 缺失模式判斷

| 機制 | 檢定 | 處理 |
| ---- | ---- | ---- |
| MCAR | Little's MCAR test | 完全隨機 → listwise / MI |
| MAR | 無直接檢定，依域知識 | 多重插補 (MI) |
| MNAR | 無直接檢定 | 敏感度分析 |

### 缺失率閾值

| 缺失率 | 處理策略 |
| ---- | ---- |
| < 5% | 通常可忽略 |
| 5-20% | 需要插補 |
| 20-50% | 需要仔細評估+ 敏感度分析 |
| > 50% | 考慮移除該變數 |

## §6 極端值處理 (S-006)

### 偵測方法

| 方法 | 適用 |
| ---- | ---- |
| IQR (1.5×) | 一般分佈 |
| Z-score (> 3) | 近似常態 |
| Modified Z-score | 偏態分佈 |

### 處理選項（需記錄理由）

1. 保留（預設，除非有明確理由移除）
2. Winsorization（取代為百分位閾值）
3. 移除（必須附理由並做敏感度分析）
4. 使用 robust 統計方法

## §7 automl-stat-mcp 委派標準

### 委派給 automl 的分析

以下分析**應**委派給 automl-stat-mcp：

| 分析類型 | automl 工具 |
| ---- | ---- |
| Propensity Score | `propensity_score_matching` |
| Survival Analysis | `survival_analysis` |
| ROC/AUC | `roc_auc_analysis` |
| Power Analysis (進階) | `power_analysis_*` |
| AutoML 建模 | `run_automl` |
| 多重迴歸 | `regression_analysis` |

### 本地處理的分析

| 分析類型 | 本地工具 |
| ---- | ---- |
| 描述統計 | ScipyStatisticalEngine |
| t-test / Mann-Whitney | ScipyStatisticalEngine |
| Chi-square | ScipyStatisticalEngine |
| Correlation | ScipyStatisticalEngine |
| Shapiro-Wilk | ScipyStatisticalEngine |
| Table 1 | tableone |

### 切換邏輯

```
if automl_gateway.is_available():
    → 委派給 automl-stat-mcp
else:
    → ScipyStatisticalEngine 處理
    → 如為進階分析 → 告知用戶 automl 不可用
```
