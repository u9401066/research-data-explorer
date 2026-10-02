# Saved DESeq2 publication figures

Development checkpoint, 2026-10-02. RDE remains 0.5.0. The rendering core and
governed multi-source MCP handoff are implemented and tested through real
Workbench CSV/Excel intake and pinned R execution. Workbench automatic publication,
checkpoint reuse and journal UI now pass synthetic browser/restart tests; public
airway analysis still follows. This development branch is not deployed and does not establish a
completed patient-level RDE analysis.

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
Caption/number edits preserve the original caption and receipt. The governed MCP
workflow below supplies immutable source/render/edition IDs and restart verification.

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

## Governed MCP handoff

`init_project` → trusted adapter prepares
`incoming/genomics/<source_uuid>/bundle.json` → `import_genomics_source` with the
exact bundle SHA256 → `render_genomics_study` with the returned source receipt
SHA256 and a new render UUID → `render_genomics_publication` with the study receipt
SHA256, a preset and a new edition UUID. `get_genomics_source` re-verifies saved
sources and lists completed, failed and unfinished render attempts after restart.
These tools do not create a patient dataset, fit a model or advance EDA phases.

The `genomics-source-bundle-v1` envelope contains the native project/source IDs,
Workbench project/dataset/plan/job/node UUIDs, a `files` map of exact bytes/SHA256,
and a `source` map with `counts`, `sample_metadata`, and optional `gene_sets`.
Every role records its dataset, original filename/selected sheet, raw bytes,
source schema and complete parsed string table. Schema bytes pin the original
file hash/name/sheet, so identical table shapes on different sheets cannot share
an approved source binding. The raw file parser is the trusted Workbench adapter;
RDE independently checks saved table values and mappings, not Excel extraction.

The handoff retains exact reviewed-plan bytes and approval hash, approved options,
complete audit and R input, fixed image/script/execution, output hashes, fitted
RDS objects, numerical receipts, every gene and plotting coordinate. A separate
`analysis-binding.json` retains the exact JavaScript `{options,audit}` bytes used
for the analysis hash; Python never guesses JavaScript numeric serialization.
RDE checks every count, metadata join/condition/batch/pair/covariate, sample total,
filter membership, optional gene-set membership/universe/overlap, and plotting
CSV/JSON agreement. It checks saved values without loading RDS or rerunning tests.
CSV roundoff is limited to the producer's 15-significant-digit representation.
Missing adjusted p values and filtered genes remain in the full source ledger.

Ordinary receipts retain a 16 MiB JSON limit. Count/audit/plotting JSON and the
sealed numerical receipt may reach 256 MiB; every file is bounded at 256 MiB and
the complete bundle at 1 GiB. Imports are copied and re-verified before atomic
publication. Existing IDs cannot be overwritten. A failed or killed renderer
retains its started marker, partial outputs and any failure receipt; a new render
ID uses the frozen numbers. Every restoration rechecks the complete source and
figure closure. Journal editions identify `source_genomics_id` and retain the
same numerical receipt and byte-identical plot-data CSVs.

`tests/test_genomics_workflow.py` covers rehashed source tampering, changed roles,
primary-sheet binding, duplicate datasets, unapproved plans, false input hashes,
failed execution, mismatched numerical CSV, missing RDS, foreign projects,
symlinks/traversal, unbound files, capacity/locking, failed render retention,
restart without redraw and a sealed JSON receipt above 16 MiB. The pinned
`workbench-handoff.zip` fixture and its manifest retain a real synthetic R run.
Workbench's external stdio integration additionally kills an actual renderer
and restores a new process; it covers three-source CSV/Excel and two-source paired
counts without gene sets. No public biological dataset has been analyzed here.

## Workbench numerical checkpoints

When supplied, `execution-origin.json` and `execution-checkpoint.json` must both
be present and match their file hashes. The importer verifies the original and
current execution IDs, approved-plan hash, fixed R image/input/script and complete
output inventory. Every role pins dataset ID, raw bytes, schema, filename and
selected worksheet, including the primary counts workbook. Reused results retain
the original R execution bytes; their current render has a new job/node identity.
External saved sources without Workbench checkpoint lineage remain supported;
the optional lineage is never an unchecked display-only flag.

`workbench-checkpoint.zip` is a genuine synthetic Workbench run with deliberately
failed rendering, service restart and numerical reuse, SHA256
`046452fb160babe1fd237c195e20c35572fac6eb0b874d4202c00de4138c2960`.
It preserves all original R/source bytes. Fifteen additional checks accept genuine
reuse and reject self-rehashed false identities, missing lineage, changed counts,
metadata, sets, worksheets, role swaps and member locations. Full suite: 946 passed,
62 skipped, 3,550 existing dependency warnings. Workbench additionally verifies
that corrupt vault data blocks reuse without another R execution. This is provenance
consistency, not a cryptographic approval signature or biological validation.
