# Independent comparison numerical contract

Updated 2026-10-02. RDE stays at 0.5.0. New `compare_groups` receipts identify
`method_contract: comparison-inference-v2`. This fixes numerical inference and
reporting prerequisites; it does **not** complete publication figure support.

## Corrected behavior

- Groups follow first observed identity in the input, before outcome exclusions.
  The engine receives that explicit order. Counts, U statistics, effect direction,
  contingency matrices, and reports retain the same order. Outcome categories in
  contingency tables follow first appearance among analyzed rows; their order is
  recorded and does not imply that the first category is a clinical event.
- Mann–Whitney uses SciPy's first-sample U. Signed rank-biserial correlation is
  `2*U_first/(n_first*n_second)-1`, equivalent to the difference in the proportions
  of favorable and unfavorable cross-group pairs. Ties contribute neither sign.
  The old implementation lost the sign and halved the magnitude. It also returned
  a different U convention under the default lightweight backend.
- Two-sided Mann–Whitney is exact when the smaller sample has at most 8 values
  and there are no ties. Otherwise SciPy's asymptotic p-value includes tie and
  continuity corrections. Small tied samples receive an explicit approximation
  warning; no permutation analysis or median-difference estimate is invented.
- Categorical selection uses expected **cell** counts, not group totals. A 2×2
  table with any expected count below 5 uses two-sided Fisher exact. A sparse
  larger table stops and requires an explicit suitable model; no automatic
  category merging or mislabeled 2×2 Fisher fallback occurs. This is a conservative
  automatic-selection policy, not a universal validity theorem.
- Fisher always calls SciPy's exact test. The old default incorrectly substituted
  a chi-square approximation. The effect estimate is the **sample** odds ratio
  `a*d/(b*c)`, with recorded outcome rows and group columns. A zero denominator
  produces JSON `null` plus `positive_infinity`, shown as `+∞` with an explanation;
  it is not missing analysis or a population infinite effect. A zero numerator
  remains the valid finite estimate 0. No half-cell correction is silently added.
- Pearson chi-square uses its actual chi-square reference distribution with
  `correction=False`; Cramér's V uses that uncorrected statistic. The environment
  no longer switches this analysis between Yates correction and an approximation.
- Kruskal–Wallis uses SciPy's tie-corrected H and chi-square reference p-value.
  Groups with fewer than 5 observations receive an approximation warning. A
  degenerate all-identical outcome fails explicitly instead of claiming a valid H.

These independent tests always use SciPy, regardless of `RDE_STATS_BACKEND`.
Legacy power helpers are outside this change. Student/Welch and ANOVA engine
entry points also retain explicit group order; a two-group t-test now rejects
three or more groups instead of ignoring them.

`test_details` preserves actual engine/version, method, group identities/counts,
contingency/expected counts where applicable, effect definition and selection
rationale. Raw p-values stay separate from the locked within-call multiplicity
policy. The assembled report includes all endpoints, effects, direction,
denominators, boundary explanations and approximation warnings. These comparisons
do not yet estimate effect confidence intervals, and the report says so.

## Verification and history

Regression edges cover signed/full-range dominance, ties/constants, first-row
missingness, exact Fisher probabilities, zero/infinite OR, expected-count selection,
sparse larger tables, unused categories and numeric group codes. The first eight
cases failed against the previous implementation, preserving the failure evidence.

`scripts/smoke_comparison_mcp.py DESTINATION` runs seven synthetic engineering cases
through external stdio MCP, with actual intake, schema, reviewed/locked plans,
analysis, collection, reports and process restart. R 4.5.3 in the existing pinned
evidence image independently computes the p-values and non-Fisher statistics;
the script asserts agreement and preserves the image identity, R expressions,
source hashes, calls and receipts. Each case retained all 46 artifact hashes
across restart. A deliberately narrow numerical QA plan explicitly opts out of
the full publication bundle; its report remains **not publication ready**.

R `fisher.test` returns a conditional MLE odds ratio, while SciPy's 2×2 statistic
is the sample/unconditional MLE; their effect estimates are not falsely asserted
equal. The exact p-values agree. Workbench browser verification additionally
checks the actual report, CSV/Excel flows, reload and mobile navigation.

Historical artifacts are not rewritten or numerically relabeled. Before this
deployment, the workbench had seven legacy comparison receipts (Mann–Whitney and
chi-square) without this contract. Their original files remain fixed. Reusing
their numbers for publication requires a separately recorded rerun/review; a
new figure style cannot repair an old numerical result.

## Method sources

Checked 2026-10-02; local validation used SciPy 1.16.3, and receipts retain the
actual installed engine version:

- [SciPy Mann–Whitney](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html)
- [Rank-biserial definition](https://easystats.github.io/effectsize/reference/rank_biserial.html)
- [SciPy Fisher exact](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html)
- [R Fisher exact and conditional estimation](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/fisher.test.html)
- [SciPy Pearson chi-square](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html)
- [SciPy Kruskal–Wallis](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kruskal.html)


## 明確指定效果量的新研究契約

開發版 `family="comparison"` 的固定對比、信賴區間、完整校正家族與投稿圖另見 [獨立組比較研究](independent-comparison-study.md)。此新增功能不改寫本頁的 `compare_groups` 既有收據；Workbench 操作流程與正式部署需另行整合驗證。
