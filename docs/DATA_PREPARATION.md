# Governed relational data preparation

`data_preparation(project_id, request)` is a native MCP workflow before intake.
Discover `op=contract` for the exact typed source, specification and review schemas.
It accepts CSV, TSV and values-only XLSX sheets. Lexical identifiers are preserved;
no fuzzy linkage, implicit Cartesian join or silent negative recoding is performed.

1. `inspect` profiles explicit sources and suggests single/composite candidate keys.
   It returns counts and column names, not example clinical values. Matching names
   or high match rates do not establish correct clinical linkage.
2. `draft` takes a new UUID, byte-pinned sources, a specification, reason and author.
   It saves originals, rules, typed output, CSV, denominators, exceptions, SVG flow,
   per-value source references and an implementation fingerprint. Each relation
   reduces its records separately to one row per declared patient/encounter/event.
3. `page` and `trace` expose exceptions, included/excluded units and original source
   records using the exact draft hash. `approve` requires no blockers, the exact
   warning acknowledgements, an attributed reviewer, sampled unit IDs and explicit
   denominator confirmation. A synthetic oracle review is labelled `synthetic_only`;
   a data-manager attestation is recorded separately and is not certified truth.
4. `release` pins the approval. `bundle` exports the complete immutable closure.
   An existing release remains historical evidence when its original uploads change.
   A new draft/release requires current sources and the current implementation.
5. `run_intake(directory=..., prepared_source={bundle_path, bundle_sha256,
   release_sha256})` verifies the complete bundle and the sole analysis CSV, retains
   its sources in the target project, and loads the approved typed values without
   header normalization, sentinel guessing or empty-column removal. Restart and
   isolated analysis workspaces retain that contract. Data-version identity binds
   the release and bundle as well as subsequent recorded cleaning operations.

Root output columns default to text with only the literal empty string treated as
missing. `unit.columns` explicitly selects numeric types and missing tokens;
identifier columns must remain text. Derived features declare types, aggregation,
unit conversion and missing tokens. Baseline windows cannot extend past index;
availability time is separately checked. Follow-up features carry a time-role
label for downstream plan review. Source record indices address parsed records,
not physical CSV lines. XLSX numeric identifiers require explicit review of original
precision; a parser cannot recover zeros or digits already lost by Excel.

To revise, create a new preparation UUID with the exact parent reference. Approvals
and releases are immutable; an interrupted draft has a persisted intent and retry
attempts, with at most one published version. Changed inputs, recipes or code cannot
reuse the old approval. Unresolved clinical definitions intentionally block release.

Verification includes predeclared multi-table truth compared cell-by-cell with an
independent SQLite oracle, shuffled rows, source changes, compound keys, null and
duplicate keys, partial linkage states, temporal ambiguity and availability,
immutable approval, interrupted preparation, complete bundle integrity, lexical
values and actual MCP intake/session recovery. These software tests do not replace
real-data manager case and denominator review.
