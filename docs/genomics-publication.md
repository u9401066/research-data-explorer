# Saved DESeq2 publication figures

Development checkpoint, 2026-10-02. RDE remains 0.5.0. The rendering core is
implemented; its governed external-source MCP workflow and Workbench adapter
are not yet connected. Do not advertise this as a deployed genomics publication
workflow or as a completed patient-level RDE analysis.

`rde.infrastructure.genomics.contract.publication_result` checks complete saved
`genomics-publication-data-v1` values and seals a numerical rendering receipt.
Its caller must separately verify source bytes, approved plans, source roles,
the pinned R execution and output hashes. The function does not establish
biological identity, consent, independent replicates or source truth.

The Workbench DESeq2 1.52.0 executor now writes `publication-data.json` and
`dispersion-estimates.csv` while its fitted model is in memory. The saved payload
contains every input gene and exclusion state, exact sample order and condition,
PCA gene membership/coordinates/explained variance, all VST sample distances,
gene-wise/fitted/final dispersions, full differential results and optional ORA
results. Raw counts and existing fitted results are unchanged. Rendering does
not load RDS, refit DESeq2, rerun PCA, cluster samples or calculate new tests.

## Figures and source fidelity

The renderer uses the shared journal-neutral, Nature single/double-column and
PLOS column/full-width presets. Every figure produces PDF, SVG, PNG, RGB LZW
TIFF, an English caption with Chinese explanation, and plot-data CSV. Actual
dimensions, font hash, resolution and source numerical receipt are recorded.
Presets are technical formatting specifications, not journal acceptance.

1. Mutually exclusive gene filtering/estimability counts, with every gene in CSV.
2. Raw library totals and detected genes, paginated at 20 samples per figure;
   all pages share the same axis limits.
3. Saved PCA, or an explicit unavailable panel. Batch effects are not removed.
4. Complete saved sample-distance matrix in count-column order, without clustering.
5. MA display of every finite unshrunken log2 fold change, retaining missing FDR states.
6. Volcano display of finite adjusted p values. Missing p is never zero; numerical
   zero or p below 1e-300 is displayed at height 300 while the original value remains.
7. Saved gene-wise, fitted and final dispersion values on log axes. The trend is
   connected in saved mean-count order, not re-estimated.
8. Optional ORA, all size-eligible sets in input order, 20 per page with shared
   axis limits. Each CSV retains
   every set and exclusion state; no significant-only selection or invented pathway.

Short sample/set codes keep long or non-English identities intact in CSV and
captions without guessing English translations. PCA distinguishes numerator,
reference and other conditions; the latter is explicitly a display grouping.
Caption/number edits preserve the original caption and receipt. This core alone
does not yet supply persistent edition IDs or server restart recovery.

The [DESeq2 official workflow](https://bioconductor.org/packages/3.23/bioc/vignettes/DESeq2/inst/doc/DESeq2.html)
is the method reference. The producer's explicit unshrunken estimates, greaterAbs
null, separate gene/set BH families, filtering and original sample design remain
fixed; changing visual style cannot change those choices.

## Verification

`tests/fixtures/genomics-publication/` contains an actual pinned-R output from
the Workbench synthetic fixture (603 genes, 12 samples), with input/script/data
SHA256 and an explicit non-biological scope. It is not a public biological dataset.
The Workbench independent reference reads the original CSVs and checks DESeq2,
PCA, variance fractions, sample distances and all three dispersion estimates.

Focused tests cover all five presets and all six files, exact full-row mapping,
FDR/missing values, source receipt changes, direction, sample order, PCA membership,
distances, dispersion, ORA background, long Unicode names, pagination, unavailable
PCA, numerical-zero display and caption preservation. Test duplications used to
stress layout are explicitly synthetic geometry, never new biological inference.
See the Workbench `docs/GENOMICS_PUBLICATION_PROGRESS.md` for actual run counts,
visual review, public-source acquisition and outstanding integration work.
