# Descriptive study contract

`run_descriptive_study` supplies a productive, governed path when sampling, independence, outcome timing or primary endpoint are unknown. It uses the existing MCP server, source intake and locked plan; it is not an implicit approval or a separate analysis engine.

The locked plan has exactly one `run_descriptive_study` entry. Its `variables` must equal `execution_arguments.descriptive_options.columns` in order. Options contain exactly `columns` (1–80 unique names), `identifiers` (0–8 of those columns) and `unresolved` (0–12 distinct explanatory strings). The plan uses pairwise per-column missing denominators and multiplicity `none`; alpha is not used by this method. Methodology expansion is disabled for this scope. Preflight keeps the pipeline integrity gates but skips normality, missing-mechanism and collinearity tests.

Every original row is retained. The report gives observed/missing denominators and distinct values per column, candidate-identifier multiplicity and overall duplicate-row count, finite numeric quantiles and bounded original-code frequencies. The report also records selected-column coverage and actual joint missingness patterns (up to 20); equal marginal missing counts do not prove that the same rows are missing. Identifier values and high-cardinality categories are not enumerated. No imputation, first-event selection, statistical tests, confidence intervals or causal/model claims are made. Distinct identifiers do not establish distinct people or independent units.

Results bind the verified source, parser, effective frame and cleaning chain using `rde-data-version-v1`. `descriptive_study.json` retains settings, version, report hash and receipt hash. Reuse requires the same plan, source/preparation version and report bytes. Changed evidence fails without overwriting saved results.

Report readiness checks the locked scope, evidence hashes and pipeline artifacts, and labels readiness as `descriptive_evidence_only`. It does not certify inferential or publication readiness. Generic inferential autoresearch start/resume/execute and branch execution reject a descriptive plan; new hypotheses require a separately reviewed research revision.

Hosts should guide broad initial requests toward this plan instead of repeatedly demanding unknown facts. An explicitly requested inferential method cannot be silently replaced and reported as completed. Human/automatic approval remains a host authorization decision with its own review record.
