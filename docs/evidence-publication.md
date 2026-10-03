# Fixed evidence-synthesis publication core

Development checkpoint, 2026-10-02. Version remains 0.5.0. The source/figure workflow is registered in the development MCP server; it is not
yet wired into the production Workbench pipeline or deployed. It does not grant
an external R analysis the individual-level RDE pipeline's audit status.

`infrastructure/evidence/contract.py` validates the typed `evidence-synthesis-v2`
receipt produced by Workbench's pinned netmeta 3.7.0 / meta 8.5.0 executor. It checks
source-row decisions, study/treatment identities, direction, complete direct-pair
membership, within-pair weights, topology counts, all network contrasts, reference
selection, local availability and the direct-minus-indirect analysis scale.
The importing workflow additionally verifies real source files, approved settings,
execution/output hashes and confined project paths, as described below.

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

Remaining product integration: connect the verified adapter/MCP workflow to the
Workbench pipeline and publication UI, full reports and search, real LLM reading, publicly sourced clinical replication,
maximum-network budget tests, RR-specific exports and deployment with preservation
checks. Current tests cover a 9-treatment matrix, not the complete 40-treatment
production limit. This checkpoint does not mark these requirements complete.

## External source workflow (development branch)

`import_evidence_source` → `render_evidence_study` →
`render_evidence_publication` now register in the live MCP server.
`get_evidence_source` restores sources and every completed, failed or unfinished
baseline-render attempt after restart. These tools use a separate
`artifacts/evidence_publication/` tree and append-only decision log; they do not
create patient datasets, approve research or advance EDA phases.

A trusted Workbench adapter writes the bundle under the initialized native
project's `incoming/evidence/<source_uuid>/`. The server accepts only this fixed
location, an exact bundle-file SHA256, normalized confined paths and no symlinks.
Limits are 128 inventoried files, 100 MiB per ordinary file, 512 MiB total and
16 MiB per JSON record. The exact `engine/network-model.rds` member may use the
512 MiB shared total budget: complete fits at 2,000 contrasts retain large
covariance and weight matrices. Other files do not inherit that exception.
Import copies and re-verifies every byte before committing an
immutable source. Subsequent reads use that copy, independent of incoming files.

The 2026-10-02 dense Workbench capacity run imported a complete approximately
280 MB RDS and rendered 856 RR figures for 40 treatments, 500 trials and 2,000
contrasts (618 direct pairs). All source/figure bytes and restart state were
verified. This is synthetic software validation, not public clinical evidence.
The resource-boundary regression uses the actual immutable R fixture and checks
the separate model limit, unchanged ordinary-file limit and shared total limit.
Focused workflow checks: 24 passed; full suite: 829 passed, 66 optional skipped.

The `evidence-source-bundle-v1` contains:

- Native project/source identity and Workbench project/dataset/plan/job/node UUIDs.
- Original CSV/Excel bytes, selected sheet, exact schema and the complete parsed
  string table, including excluded comparison rows.
- Exact compact JSON bytes of the reviewed draft, approved plan, options and
  complete review. Workbench's approval/options/input hashes are SHA256 of its
  literal `JSON.stringify` bytes, not Python canonical JSON hashes.
- Actual R script, engine input, completed execution with immutable Docker image
  ID and confirmed container cleanup, numerical receipt, and complete engine
  output-hash inventory. No numerical estimates are manually translated.

Import verifies the reviewed draft hash and its semantic identity to the approved
plan, source/schema binding, approved synthesis step, settings, every table row
and disposition, engine input/script/review hashes, all output hashes and the
v2 numerical contract. These hashes establish saved-byte consistency, not a
signature, independent source extraction, truthful literature, or clinical
appropriateness; the adapter and the original human review remain trust boundaries.

Initial rendering preserves a started marker and partial files; a failure adds a
failure receipt. A successful render stores six formats per figure plus a Chinese
report with English captions. Same-ID retry verifies and returns the completed
record without rendering again. An interrupted/failed ID is retained and requires
a new render ID; that new attempt uses the same frozen numerical receipt. File
locks serialize workflow operations across processes. Journal editions share the
existing immutable figure-edition engine; edits preserve all original numbers and
plot data. Rendering is separate from R execution.

`tests/fixtures/evidence-publication/workbench-handoff.zip` preserves the full
synthetic OR handoff exported from the previously completed Workbench browser QA
(Workbench numerical executor `8423077`; RDE figure core `7affbf7`). Its 28 files
include the bundle and 27 inventoried source files; the ZIP keeps literal compact
JSON bytes from being reformatted by source-code hooks. SHA256:
`3cedb20b499dfe23fc203ba55c22620327b67ab5be63be8bd8044ba1436492ae`.
Only the transport project/source IDs are assigned to each isolated test project;
R/source/approval bytes remain fixed. This is synthetic engineering evidence.

The Workbench production pipeline and publication UI are not yet wired to this
new workflow. The existing R PNGs remain in use there. Adapter/MCP integration
checks are separate from browser or public-clinical-data validation.

## Workbench numerical checkpoints and retry lineage

The development Workbench now snapshots a completed R execution before attempting
publication rendering. A later attempt with the same approved plan, source/schema,
sheet, input, script and immutable image can recover these saved bytes instead of
starting R again. The new graph node uses the original checkpoint artifact; old
failed render attempts remain unchanged. Corrupt snapshots stop recovery without
silently rerunning the analysis. Mutable working copies are not recovery sources.

Bundles using this facility include `execution-checkpoint.json` and
`execution-origin.json`. They bind the original and current Workbench identities,
the exact checkpoint bytes, plan/source/input/script/image, each saved artifact's
identity/hash/size and its original location. RDE validates all of these against
the actual bundle and complete engine inventory before importing or reading it.
An executed origin must be the current execution; a reused origin must name a
different job/node under the same project/dataset/approved plan. This preserves
provenance without claiming that R ran again for the new rendering. External
fixed R sources may omit Workbench-specific checkpoints; incomplete or false
lineage supplied by a caller is rejected. These are byte/identity consistency
checks, not independent cryptographic proof of an external execution.

`tests/fixtures/evidence-publication/workbench-checkpoint.zip` freezes 28 exact
files from an actual synthetic OR retry on 2026-10-02: completed Docker/R → actual
RDE font failure → Workbench service reconstruction → successful RDE figures,
with one R execution in total. Numeric/execution bytes were unchanged; a damaged
working copy was recovered from the vault, while a corrupt vault checkpoint was
rejected without reanalysis. ZIP SHA256:
`e2b5ffc2f3c63134c8bcb21c9e8872efed0ec67977e50396e945f9ab4f6290b4`
(347,248 bytes). Tests preserve those bytes and change only transport IDs or
explicit adversarial lineage fields. This is software verification, not a real
clinical dataset. No tool inventory or package version changes were required.

Handoff verification on 2026-10-02: 14 MCP edge tests passed with the actual saved
Workbench fixture. Two live Workbench/R/Docker/external-stdio flows passed for
CSV OR and explicitly selected Excel MD. Each created nine baseline figures and
nine Nature single-column edition figures: 36 figures, 216 six-format files and
four reports, all 220 artifact hashes checked. Exact data CSVs and numerical
receipts stayed fixed across editions and newly started MCP processes. After the
first raster, terminating the owned MCP process left an unfinished attempt;
new-ID rendering from the frozen source succeeded, with the partial attempt kept.
A graceful client shutdown can allow a short rendering to complete; the earlier
incorrect unfinished-only test expectation is preserved in the private QA logs.
Representative OR forest, MD direct/indirect forest and disposition PNGs were
visually reviewed. No browser or public-clinical-data validation is claimed here.

The complete non-vendor suite passed **819 tests**, with 61 optional/environment
skips and five vendor tests deselected. After keeping the shared-edition adapter
at the MCP interface boundary, the final focused MCP/source/inventory suite passed
**39 tests**. Extension compilation and all **40 extension tests**, asset sync,
local VSIX packaging and repository pre-commit checks passed. Versions remain
RDE 0.5.0 and Workbench 0.1.0; no release or production deployment was performed.

## Reviewed comparison dictionaries (2026-10-03)

`render_evidence_publication` accepts a reviewed `display_dictionary` under the
shared publication-dictionary-v1 contract. The complete saved R source closure
is verified before resolving annotations against its immutable comparison table.
The source SHA256, selected sheet, approved plan identity (when selected), review
revision and original codes remain bound to the edition. The allowed columns are
study_id, report_id, treatment, comparator, effect, se, outcome, timepoint,
population and effect_modifiers; decision and risk-of-bias controls are excluded.

One treatment identity must have the same reviewed meaning in treatment and
comparator. Exact original spelling is retained, including the executor's existing
JavaScript whitespace normalization. Effect and SE labels must retain log OR,
log RR or the declared MD unit. Annotations cannot convert values, merge
treatments, equate doses, change eligibility or establish transitivity. Compact
treatment codes remain on dense figures; full reviewed mappings and limitations
are mandatory in every caption, including author-overridden captions.

Actual MCP regression checks cover approved/current dictionaries, long names,
immutable source bytes, byte-identical plot CSVs, idempotent reads and rejection of
wrong source/sheet/plan, changed units, absent codes, control columns and conflicting
treatment meanings. Edition rendering is tested with external process launch
forbidden. Three new tests passed; together with existing evidence workflow checks,
27 passed. The complete suite passed 1044 tests, with five optional vendor skips
(506.51 s). A subsequent caption clarification passed the three focused tests.

Real Workbench/R/MCP/browser verification used explicitly synthetic OR and RR CSVs
and a two-sheet MD workbook (only Comparisons selected). Each saved analysis has
five independent synthetic studies and seven included comparison rows, not five
clinical trials. Four Nature/PLOS editions contain 36 figures and 216 downloads;
all data CSVs remain byte-identical. Every PNG and rendered PDF page was visually
reviewed. This validates software behavior, not clinical source adjudication or
the suitability of a real meta-analysis. Workbench retains the private deployment
and browser evidence; versions remain unchanged.
