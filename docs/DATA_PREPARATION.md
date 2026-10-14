# Governed relational data preparation

`data_preparation(project_id, request)` is a native MCP workflow before intake.
Discover `op=contract` for the exact typed source, specification and review schemas,
including the native [Data Aggregation part](DATA_AGGREGATION.md). Its ten-method
registry and typed local edits let agents compose and correct rules without
generating analysis code or rewriting an entire specification on every attempt.
It accepts CSV, TSV and values-only XLSX sheets. Lexical identifiers are preserved;
no fuzzy linkage, implicit Cartesian join or silent negative recoding is performed.
Each version declares one root analysis unit and directly keyed relations to that
root. Arbitrary multi-hop joins and probabilistic identity resolution are outside
this contract; resolve those into an explicitly governed source before use.

1. `inspect` profiles explicit sources, returns a hash-bound
   `rde-source-table-schema-v1` for each table, and suggests single/composite
   candidate keys. The schema records actual column order, lexical storage, parser
   and observed constraints; it does not infer clinical roles or confirmed keys.
   Matching names or high match rates do not establish correct clinical linkage.
2. Start an immutable candidate with `aggregation_compose` using a declared unit
   and known definitions, or `from_specification` for an existing recipe. Read
   `contract.aggregation`, then use `aggregation_patch` against the complete returned
   `candidate_ref`, targeting stable relation IDs and feature outputs. Unmentioned
   rules remain unchanged; new source bytes/parser settings require a new candidate.
   `aggregation_preview` evaluates the native rules and saves hash-pinned evidence;
   `aggregation_read` pages issues, units, output and cell trace using both the exact
   candidate reference and `preview_sha256`. `aggregation_diff` compares rules and
   already-saved outcomes without rerunning them. Source values are available in
   these governed pages, so the host must enforce project/account access.
   Every derived feature reports observed/missing counts. An all-missing feature
   raises a warning even when all root patients remain, so a plausible denominator
   cannot hide a bad value filter. Repair the located rule rather than changing an
   unrelated lookup or dropping an unsupported research requirement. The host owns
   its retry budget, cancellation and independent requirement review; RDE does not
   prescribe three complete model proposals. `ready_for_draft` means technical
   completeness, never human approval or alignment with the research question.
   The direct `preview` operation remains available for a supplied full specification;
   unlike candidate preview, it does not retain a version for paged evidence.
3. `draft` takes a new preparation UUID, exact `candidate_ref`, reason and author.
   Alternatively it accepts byte-pinned `sources` plus `specification`; these input
   forms cannot be mixed. Candidate resolution requires a ready native preview.
   It saves originals, rules, typed output, CSV, denominators, exceptions, SVG flow,
   per-value source references and an implementation fingerprint. Each relation
   reduces its records separately to one row per declared patient/encounter/event.
4. `page`, `trace` and `source_row` expose exceptions, included/excluded units and original source
   records using the exact draft hash. `approve` requires no blockers, the exact
   warning acknowledgements, an attributed reviewer, sampled unit IDs and explicit
   denominator confirmation. A synthetic oracle review is labelled `synthetic_only`;
   a data-manager attestation is recorded separately and is not certified truth.
   For an authorized automatic path, `automated_review` takes `preparation_id` and
   `expected_sha256` (the draft receipt hash). It verifies live sources, saved files,
   typed schema/headers/identifiers, all included trace identities and denominators,
   and every CSV/typed output value. Its sealed
   `rde-preparation-automated-checks-v1` receipt supplies up to 100 actual
   `reviewed_unit_ids`. Approval with `review.kind="automated_checks"` sets
   `review.automated_receipt_sha256` to that receipt's `receipt_sha256`, with the same ordered unit IDs, explicit
   denominator confirmation and notes. The server revalidates the evidence; caller
   assertions do not replace it. Automated approval and release retain
   `clinical_validation="not_performed"`. This is technical consistency checking,
   not independent statistical recomputation, clinical validation or human review.
5. `release` pins the approval. `bundle` exports the complete immutable closure,
   including the automated review receipt when used.
   An existing release remains historical evidence when its original uploads change.
   A new draft/release requires current sources and the current implementation.
6. `run_intake(directory=..., prepared_source={bundle_path, bundle_sha256,
   release_sha256})` verifies the complete bundle and the sole analysis CSV, retains
   its sources in the target project, and loads the approved typed values without
   header normalization, sentinel guessing or empty-column removal. Restart and
   isolated analysis workspaces retain that contract. Data-version identity binds
   the release and bundle. Post-release cleaning is blocked: revise and approve
   a new preparation so intake and autoresearch cannot silently use different values.

Root output columns default to text with only the literal empty string treated as
missing. `unit.columns` explicitly selects numeric types and missing tokens;
identifier columns must remain text. Root cleaning precedes eligibility evaluation,
while linkage uses lexical source keys. Derived features declare types, aggregation,
unit conversion and missing tokens. Baseline windows cannot extend past index;
availability time is separately checked. Follow-up features carry a time-role
label for downstream plan review. Untimed sources require an explicit
`at_index_basis` to label their features as baseline; otherwise they are descriptive,
with an unverified-time warning. Observed events with unknown export coverage remain
`matched_partial`. Even absent values have root, coverage and rule trace evidence.
Source record indices address parsed records,
not physical CSV lines. XLSX numeric identifiers require explicit review of original
precision; a parser cannot recover zeros or digits already lost by Excel.

To revise, create a new preparation UUID with the exact parent reference. Approvals
and releases are immutable; an interrupted draft has a persisted intent and retry
attempts, with at most one published version. Changed inputs, recipes or code cannot
reuse the old approval. Unresolved clinical definitions intentionally block release.
Candidate revision identity is separate from preparation approval identity. To
branch from a historical candidate without advancing its current head, compose a
new candidate from its saved specification and retain the parent relationship.
Preview success alone does not complete any of the research-plan, analysis, report
or clinical-validation stages. See [candidate identity, replay, diagnostics and
limits](DATA_AGGREGATION.md) for the precise native operations.

Verification includes predeclared multi-table truth compared cell-by-cell with an
independent SQLite oracle, shuffled rows, source changes, compound keys, null and
duplicate keys, partial linkage states, temporal ambiguity and availability,
immutable approval, interrupted preparation, complete bundle integrity, lexical
values and actual MCP intake/session recovery. These software tests do not replace
real-data manager case and denominator review.
