# Assisted research intake

`run_intake(pii_policy="pseudonymize")` is an explicit host policy that prepares a research view and continues intake. Standalone calls retain the existing default `block`; `allow_pii=true` remains a separate raw-value override.

The native loader preserves original bytes and row order. Name/linkage signals use deterministic HMAC-SHA256 codes, with nulls and duplicate relations retained. Recognizable identifiers within free text are replaced by spans rather than erasing the whole clinical column. Birth dates and ambiguous telephone/range shapes remain available for research with an explicit review note. Technical labels such as `drug_name` are not treated as person names solely by their name.

The receipt fixes `policy`, `source_sha256`, a key fingerprint, column actions and aggregate signal counts. It contains no original values or mapping table. The per-study key lives at `RDE_PRIVACY_KEY_FILE`, or the standalone workspace `.research-privacy.key`; creation is atomic and permissions are private. Hosts must scope it to a study, share it across that study's dataset/run workspaces, and back it up outside report artifacts. Equal source values preserve equality across columns; that does not establish correct joins or patient identity.

`privacy_receipt.json`, `research_view.csv`, intake and schema expose the processing. Rehydration and source-frame binding load the same recipe. Host analysis runs pass the saved recipe and verify the research-view SHA before executing a plan. Schema marks transformed identifiers as IDs, not measurements; clinical-date/ambiguous items retain an explicit action rather than pretending there was no signal.

This is pseudonymization, not certified anonymization. Unrecognized names, dates, quasi-identifiers and retained ambiguous text may remain. Original downloads, custom plugins and relational raw-source tools are separate scopes. Historical approved plans are not rewritten. Tests cover full-column scanning, mixed clinical text, duplicate/null keys, cross-table equality, key/source drift, native schema/lineage/restart, and host plan-to-report execution.
