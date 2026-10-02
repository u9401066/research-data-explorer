# Binary trial-arm preparation

Development workflow for aggregate binary trial arms, separate from the
patient-level EDA phases. It prepares complete log-OR or log-RR contrasts;
it does not fit a meta-analysis, adjudicate clinical eligibility, or establish
that different study labels identify independent trials. Version remains 0.5.0.

## MCP contract and sequence

Call `evidence_arm_preparation(project_id="", request={"op":"contract"})`
for the strict operation/schema contract and calculation rules. Unknown keys,
implicit coercion and incomplete choices are rejected. The registered tool is
conservatively annotated as mutating because its facade includes approval and
execution; those actions remain separately gated in the application.

1. Initialize an RDE project. A trusted client copies the original CSV/TSV/XLSX
   to `<project.output_dir>/incoming/evidence-arms/<preparation_uuid>/<filename>`.
   Sources are nonempty and at most 20 MiB. Arbitrary absolute paths and symlink
   substitutions are rejected.
2. `inspect` reads the incoming source before clinical mapping is available. Supply
   its exact SHA256, filename, preparation UUID and `selection: {sheet: ...}`.
   It creates no draft or clinical decision. Read all hash-pinned grid pages;
   continuations also verify the incoming bytes, so source changes stop the read.
   Offsets are Unicode code points, not JavaScript UTF-16 code units.
3. `draft` supplies that exact source SHA256, filename, new preparation UUID and
   specification. Select the worksheet and exact one-based data rows/columns;
   explain every outside row range, missing code, treatment mapping, denominator,
   endpoint, follow-up, metadata and method choice. Numeric missing codes,
   including zero, are unsupported. A blank code needs its own stated meaning.
4. Read complete `plan`, `grid` and `review` records with `read`. Read offsets
   count Unicode characters; every continuation must pin `expected_text_sha256`.
   Assemble every `text_excerpt` and verify its UTF-8 SHA256. Source grid retains
   multilevel/duplicate headers and blank records; CSV row numbers mean logical
   records, with physical line-end numbers also preserved. XLSX numeric XML
   tokens retain their lexical precision; dates remain ISO values. The source
   worksheet part and parser warnings are recorded. Original bytes are never
   rewritten or normalized. XLSX parts used for this mapping must be UTF-8 XML
   with no DTDs/entities or ambiguous duplicate archive/cell identities.
5. Unreviewed treatment/row decisions may be `unresolved`. They block approval
   and are **neither included nor excluded**. Invalid counts, duplicated arm IDs,
   unknown flags, body formulas/merges, inconsistent metadata, disconnected
   networks and unsupported limits also block. No effect or SE is calculated
   in a draft. Identity labels with surrounding whitespace are currently rejected;
   reconciliation requires a new explicit source mapping, not silent trimming.
6. `approve` pins the plan receipt SHA256 and records reviewer, note and all five
   explicit confirmations. This records an assertion of review, not a verified
   human identity/signature or proof that the assumptions are clinically valid.
7. `execute` pins both plan and approval hashes with a new run UUID. Only an
   unchanged source/review/method implementation can begin a new calculation.
   A completed ID verifies and returns the original result without recalculating,
   including after an MCP process restart. Failed/interrupted attempts remain;
   use a new run ID to retry. Source, result or file inventory changes are rejected.

Changing sources or decisions requires a new draft and approval. Drafts, reviews,
approvals, results, CSVs and attempt records are immutable under
`artifacts/evidence_arm_preparation/<preparation_uuid>/`. The workflow shares
the external-evidence lock and appends events to
`artifacts/evidence_publication/decision_log.jsonl`; it never advances EDA phases.

## Arithmetic and provenance

All policies are explicit; there is no inferred default method. Supported counts
are at most `2^53-1`, with up to 24 significant digits and 20 decimal places.
Denominators must be positive integers. Fractions require the explicit
`author_imputed` policy **and** the corresponding source flag. Unknown flag values
or unflagged fractions stop the calculation; values are never rounded to counts.

The optional merge sums disjoint arms of the same treatment before correction,
retaining every original arm ID, row, raw value and missingness reason. A study
left with fewer than two treatments, or with all participants having the same
outcome, is excluded only under the explicitly reviewed exclusion policy.
Individual arm exclusions stay in the preparation ledger; canonical output does
not mix included and excluded comparison rows within a study.

If zero-cell correction is authorized, add 0.5 to events and non-events of **all
retained merged arms in that affected study**, once before constructing pairs.
Each corrected denominator increases by 1. This differs from correcting each
pair independently. All unordered pairs are emitted for multiarm studies with
consistent arm contributions; the downstream model must account for covariance.

For each arm, OR uses `log(events)-log(non_events)` and variance
`1/events+1/non_events`; RR uses `log(events)-log(total)` and variance
`non_events/(events*total)`. A contrast subtracts arm log contributions and its
SE is the square root of their summed variances. Direction is treatment minus
comparator. The clinically favorable direction is not inferred.

Each result retains raw-to-merged-to-corrected derivations, source SHA256/rows,
all source decisions and complete method assumptions. `contrasts.csv` is a
machine-readable canonical analysis input, not a clinical report. It must be
passed with its full preparation/source/approval closure into the downstream
Workbench audit; exporting a CSV alone is not sufficient provenance. Workbench
now has development HTTP/MCP source inspection, editable source mapping,
immutable draft review, explicit approval and conversion. A derived comparison
dataset carries `workbench-arm-source-v1` identity from its first persistence.
Downstream synthesis imports all nine frozen source/preparation/approval/run
files, verifies their exact inventory and bytes, and binds the original source,
native project, preparation, approval and run to the Workbench project/dataset.
The prepared CSV must exactly match both the derived source and parsed table;
endpoint, follow-up and effect scale cannot change. Publication provenance keeps
this origin. Reads of imported evidence never re-parse the original workbook or
recalculate effects. Public clinical adjudication and analysis are still pending.

These Wald inverse-variance estimates differ from a binomial likelihood NMA.
Fractional author estimates also have uncertainty not modeled here. No GRADE,
CINeMA, dose selection or clinical interpretation is fabricated.

## Actual verification

`scripts/smoke_evidence_arms_mcp.py --destination <new-directory> --r-image
sha256:<immutable-image-id>` starts external MCP processes, completely reads the
reviews, tests missing/stale approvals, executes OR/RR and restarts before replay.
It checks every frozen file hash and compares to independent `meta::metabin`
calculations from the raw synthetic fixture. `netmeta` also validates its complete
three-arm comparisons. The pinned environment is R 4.5.3 / meta 8.5.0 /
netmeta 3.7.0. The fixture combines duplicate-treatment merging, author-imputed
fractions, a zero-event arm, partial arm exclusion, and explicitly excluded
uniform-outcome/single-treatment studies. This is software QA, not a clinical
analysis. Source/approval/precision/failure edges also run through the normal
pytest suite.

`scripts/review_evidence_arms_mcp.py --source <original-file> --source-sha256
<sha256> --specification <json> --destination <new-directory>` only creates a
draft and reads its complete plan/grid/review through external MCP. It never
approves or executes, and can retain unresolved clinical source questions.

The source-inspection addition passes 50 focused source/tool/document tests and
the full RDE suite (858 passed, 66 skipped). Workbench additionally exercised
real external MCP for CSV and multi-sheet XLSX, astral Unicode paging, source
changes, missing saved project metadata and exact draft recovery after restarting
both the service and MCP. Its browser review retained the original Cipriani
workbook's complete 1268-row/37-column grid and the selected 1199 unresolved
arms. These are source/draft checks, not a completed clinical analysis.

The subsequent portable-lineage addition passes the full RDE suite (871 passed,
66 skipped), including missing/extra files, changed approval/raw bytes/parsed
table, foreign identities and altered synthesis endpoint/scale. A frozen bundle
remains verifiable after the original native directory is removed; the test
explicitly forbids source parsing and effect recalculation. Workbench's actual
HTTP/MCP/R integration simulates interrupted delivery after successful native
calculation, restarts the service and MCP, recovers the same receipt and dataset,
then completes synthesis and publication with all original lineage. Desktop and
mobile browser QA approves only synthetic engineering data; the real Cipriani
workbook retains all 1199 unresolved arms and cannot be approved.
