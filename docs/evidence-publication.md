# Fixed evidence-synthesis publication core

Development checkpoint, 2026-10-02. Version remains 0.5.0. This module is not yet
registered as an MCP workflow or deployed to Research Workbench. It does not grant
an external R analysis the individual-level RDE pipeline's audit status.

`infrastructure/evidence/contract.py` validates the typed `evidence-synthesis-v2`
receipt produced by Workbench's pinned netmeta 3.7.0 / meta 8.5.0 executor. It checks
source-row decisions, study/treatment identities, direction, complete direct-pair
membership, within-pair weights, topology counts, all network contrasts, reference
selection, local availability and the direct-minus-indirect analysis scale.
The eventual importing workflow must additionally verify real source files,
approved settings, execution and output hashes, and confined project paths.

`publication.py` draws from a frozen numerical receipt without estimating any
model or test. It exports six formats with English captions, Chinese explanations,
original source identities and exact plot data. Treatment names are represented by
codes on the canvas and mapped back in captions/data. Study forests retain all
rows across pages; the pooled diamond always uses the full direct comparison.
Dense or colliding networks use complete adjacency cells. Missing indirect paths
remain not estimable. The disposition figure counts comparison rows, not PRISMA
records. Bias judgments are researcher-provided and are not GRADE/CINeMA scores.

Random-effects direct pairwise models estimate separate REML variances; SIDE
direct/indirect components use the network's common variance. An inconsistency
contrast is direct minus indirect, on the log-ratio scale for OR/RR, with null zero.
All confidence intervals and p values are unadjusted across comparisons. See
[official netsplit documentation](https://search.r-project.org/CRAN/refmans/netmeta/html/netsplit.html)
and [metagen documentation](https://search.r-project.org/CRAN/refmans/meta/html/metagen.html).
The installed 3.7.0 S3 method was also inspected because the online reference can
describe another package version.

The fixture directory preserves actual R input/output bytes, executor source,
container image ID and hashes from four synthetic execution cases. No numerical
result was manually rewritten. Workbench's real-R suite independently checks GLS,
inverse-variance and two-study REML references. These are software fixtures, not
clinical evidence. Reproduction starts with Workbench's
`RUN_EVIDENCE_INTEGRATION=1 EVIDENCE_QA_DIR=...` integration suite and a fixed
`EVIDENCE_IMAGE`.

Focused QA: 17 passed with authorized local Arial; five presets produced 45 OR
figures, and tree/paged pairwise/dense-network MD cases produced 42 more figures.
All 522 exported files were checked, including original drawing rows, source
directions, CI/weights, physical size, DPI and image formats. Visual inspection
found overlapping log ticks in the first narrow preset; sparse ticks and an actual
rendered-label overlap regression now cover that failure. No publication
compliance claim is inferred solely from a preset.

Full non-vendor suite: 801 passed, 61 environment/optional skipped and five
vendor tests deselected in 185.31 seconds. The focused 17-test figure run above
separately enabled the authorized Arial directory and exercised every preset.

Remaining integration: a typed MCP source/import/edition workflow, source and
approval binding to Workbench, immutable version editing, restart/cancellation,
full reports and search, real LLM reading, publicly sourced clinical replication,
maximum-network budget tests, RR-specific exports and deployment with preservation
checks. Current tests cover a 9-treatment matrix, not the complete 40-treatment
production limit. This checkpoint does not mark these requirements complete.
