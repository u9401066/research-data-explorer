# Data Aggregation: native, typed preparation rules

Data Aggregation is part of the existing `data_preparation(project_id, request)`
MCP tool. It turns explicit source tables into one traceable row per declared
patient, encounter or event. It does not require another MCP server, generated
Python/SQL, or a second aggregation engine. Candidate preview and preparation
draft execute the same native preparation engine.

This document describes the implementation on the development branch. It does
not announce a published release. A successful preview is not a released dataset,
an approved research plan, a completed analysis, or clinical validation.

## Discover before composing

Call `data_preparation(project_id=project_id, request={"op": "contract"})`.
The result contains `schema="rde-data-preparation-contract-v1"` and:

| Contract field | Use |
| --- | --- |
| `source`, `specification`, `review` | Native JSON schemas for source identity, scientific rules and review |
| `aggregation.schema` | `rde-aggregation-contract-v1` |
| `aggregation.methods` | All supported methods, input types, relation kinds, window requirements, null/tie/trace semantics and output roles |
| `aggregation.unit_schema`, `definitions_schema` | Small initial candidate inputs |
| `aggregation.operation_schema` | Discriminated union of typed local edits |
| `aggregation.reference_schema` | Complete candidate identity |
| `aggregation.compose_schema`, `patch_schema` | Complete request schemas |
| `aggregation.execution_semantics`, `contract_sha256` | Execution boundaries and aggregation contract fingerprint |

Read the returned schemas and semantics; do not reconstruct them from these
examples. `inspect` receives byte-pinned sources and returns a
`rde-source-table-schema-v1` for each actual table: column order, raw text storage,
parser settings, observed missingness/uniqueness, source hash and schema hash.
Candidate keys and same-named columns are suggestions, not confirmed identity or
clinical meaning. This raw-source schema differs from a draft's typed
`analysis.schema.json` and downstream intake's semantic variable classification.

The host supplies the project, verified source descriptors, new UUIDs and an
attributed author. Agents choose supported rules using observed schemas and known
research definitions. Missing domain facts remain explicit; neither a column name
nor a valid JSON response supplies those facts.

## Ten native methods

Every relation reduces its records independently before features are combined.
Three labs plus two medications therefore do not become six patient rows.
All methods return one scalar per analysis unit. Only `unique` is supported for a
`lookup` relation; the other nine require `events`.

| Method | Input and window | Meaning and retained contributors |
| --- | --- | --- |
| `unique` | Explicit value column; text, number or datetime | One distinct nonmissing typed/converted value across the **whole selected relation/window**. Unequal values block. Retains all nonmissing compared records. It is neither a list nor a distinct-value count. |
| `count` | Selected records; value column unnecessary | Number of selected event records, including records whose feature value is missing. Retains those records; does not count people, nonmissing values or distinct values. |
| `exists` | Selected records; value column unnecessary | `1` if at least one record is selected, independent of feature-value missingness. Retains selected records. |
| `sum` | Explicit numeric column | Sum of finite nonmissing values after declared conversion; all contributing records retained. |
| `mean` | Explicit numeric column | Arithmetic mean; denominator is contributing values, not all event records. All contributors retained. |
| `min` | Explicit text, number or datetime column | Minimum declared typed value. Retains all compared nonmissing records, not just the minimum witness. Text comparison is lexical. |
| `max` | Explicit text, number or datetime column | Maximum declared typed value. Retains all compared nonmissing records, not just the maximum witness. Text comparison is lexical. |
| `first` | Explicit value column **and event-time window** | Earliest timestamp with a nonmissing typed/converted value. Equal-valued ties retain every member; unequal values at that time block. |
| `last` | Explicit value column **and event-time window** | Latest timestamp with a nonmissing typed/converted value. Equal-valued ties retain every member; unequal values at that time block. |
| `days_to_first` | Event-time window and unit index; value column unnecessary | Earliest selected event minus index in fractional 24-hour days. May be negative for baseline events. Retains all records at the earliest time; feature-value missingness is not consulted. |

No usable value produces `null`. Only `count`/`exists` may produce zero when no
records are selected, and only for **complete** coverage with `no_record`,
`outside_window` or `filtered_out`. Unknown/not-exported coverage, `link_failed`
and `not_available` do not establish zero. A positive count under unknown coverage
is an observed count, not evidence of complete capture. All-missing value features
retain selected records as missingness evidence.

For example, values `10` on Monday and `20` on Tuesday satisfy `last=20` but fail
`unique`; adding `unique` as a latest-time tie check changes the research rule.
Two Tuesday values of `20` both contribute to `last`; Tuesday values `20` and `30`
block instead of choosing by row order. If Tuesday's value is missing, `last`
looks back to the latest usable value. A `lookup` is not repaired by switching it
to `first`/`last` simply to silence an error elsewhere.

`median`, `count_nonmissing`, `count_distinct`, arbitrary expressions and custom
code are not native method names. Do not silently substitute another estimand.
Numeric `gt/gte/lt/lte` predicates take finite literal constants; cross-column or
index-relative date comparisons belong in the window contract.

## Candidate operations and exact identity

All requests below are `request` objects passed to the same MCP tool with the
owning `project_id`. The current candidate reference has six required fields:

| Field | Meaning |
| --- | --- |
| `candidate_id` | UUID of the candidate history |
| `revision_id` | UUID of this immutable revision |
| `revision` | Strict positive integer in that history |
| `receipt_sha256` | Sealed candidate receipt hash |
| `specification_sha256` | Canonical, fully normalized specification hash |
| `source_set_sha256` | Exact source descriptors, including parser/path identity |

Copy the entire returned reference. A title, array position, revision number or
specification hash alone is not an identity. Project ownership is also checked.

| Operation | Request fields beyond `op` | Result and boundary |
| --- | --- | --- |
| `aggregation_compose` | `candidate_id`, `revision_id`, `sources`, `author`, `reason`; either `unit` plus optional `definitions`, or `from_specification` | `rde-aggregation-candidate-v1`: project, reference, normalized specification and completeness diagnostics. Do not mix the two input forms, even by supplying null `unit`/`definitions`. |
| `aggregation_patch` | `candidate_ref`, new `revision_id`, `operations`, `author`, `reason` | New immutable revision and rule diff. Applies 1–32 typed operations atomically to the latest exact base. |
| `aggregation_read` | `candidate_ref` | Exact historical candidate and completeness diagnostics; no implicit head selection. Saved preview evidence uses the additional fields below. |
| `aggregation_preview` | `candidate_ref` | `rde-aggregation-preview-v1`: `preview_sha256`, diagnostics, summary, `ready_for_draft`, `advisory_only`, `clinical_validation`. Persists preview evidence; creates no preparation draft/release. |
| `aggregation_diff` | `before`, `after` (complete references) | Stable-target rule changes and, when both previews exist, population/value/member changes. Sources must have the same `source_set_sha256`; references may be from separate candidates in the same project. |

Compose permits unknown definition strings and not-yet-handled sources. These
produce `DEFINITION_*` / `SOURCE_RULE_REQUIRED` diagnostics, not invented defaults.
Schema or source-column binding errors reject the request. Incomplete candidates
remain editable, but cannot become drafts until the native preview is ready.

### Typed patch targets

Unmentioned rules stay unchanged. The entire resulting specification is validated
before committing; a rejected edit does not partially change the previous revision.

| Operation | Stable target and replacement payload |
| --- | --- |
| `unit_set` | Complete `unit` |
| `definition_set` | `field` (`unit`, `linkage`, `time`, `missingness`) and `value` |
| `relation_add` / `relation_remove` | Complete new `relation` / existing `relation_id` |
| `relation_update` | `relation_id`, explicit `changes`; cannot rename the relation or change its source |
| `feature_set` / `feature_remove` | `relation_id` and complete `feature` keyed by `feature.output` / `feature_output` |
| `window_set` | `relation_id`, complete `window` or explicit `null` |
| `filters_set` | `relation_id`, complete ordered `filters` list |
| `cohort_set` / `cohort_remove` | Complete `rule` keyed by `rule.id` / `rule_id` |
| `cohort_order` | Complete `rule_ids` sequence; each current rule exactly once |
| `omission_set` / `omission_remove` | `source_id` plus explicit nonblank `reason` / `source_id` |
| `exclusion_add` / `exclusion_remove` | Complete attributed `row` / `source_id`, zero-based `record_index`, `row_sha256` |

`relation_update.changes` supports native join keys, kind, record keys, duplicate
policy, key normalization, coverage, event reuse, `at_index_basis`, excluded statuses
and reason. Features, windows and filters have their own operations. A complete
feature replacement must retain the intended type, missing tokens and unit mapping;
omitted optional fields take native defaults. Renaming an output requires explicit
remove/add and any dependent cohort edits in the same atomic patch.

There is no generic JSON Patch, array-offset mutation, source-path edit or arbitrary
SQL/Python operation. A changed source or parser requires a new candidate. Removing
a relation does not invent a reason to omit that source, and removing a feature
cannot leave a dangling `after_links` cohort dependency.

### Request examples

These are MCP-call templates, not data-processing scripts. `project_id`, `sources`,
UUIDs and returned objects are supplied by the host. The column names below are
synthetic labels; use `inspect` to obtain the actual source schema before choosing
any keys or fields. Do not copy these research definitions into a real study.

```python
contract = data_preparation(project_id=project_id, request={"op": "contract"})
inspection = data_preparation(project_id=project_id,
                             request={"op": "inspect", "sources": sources})
candidate = data_preparation(project_id=project_id, request={
    "op": "aggregation_compose",
    "candidate_id": new_candidate_uuid,
    "revision_id": new_revision_uuid,
    "sources": sources,
    "unit": {
        "source_id": "people", "kind": "patient",
        "keys": ["site", "pid"], "subject_keys": ["site", "pid"],
        "index_column": "index_at"
    },
    "author": author,
    "reason": "Begin with the explicitly defined synthetic unit"
})
```

This initial candidate deliberately leaves definitions and other source rules
unresolved. Supply known definitions with `definition_set` and new relations with
`relation_add`; do not invent omissions to make a preview green. For an existing
`labs` event relation, this is a valid local operation **inside** the patch's
`operations` array:

```json
{
  "op": "feature_set",
  "relation_id": "labs",
  "feature": {
    "output": "lab_latest",
    "column": "value",
    "aggregate": "last",
    "value_type": "number",
    "missing_tokens": [""]
  }
}
```

It requires an explicit window. A complete window operation for a synthetic
seven-day baseline with separate availability time is:

```json
{
  "op": "window_set",
  "relation_id": "labs",
  "window": {
    "event_column": "taken_at",
    "available_column": "known_at",
    "availability": "column",
    "start_days": -7,
    "end_days": 0,
    "bounds": "both",
    "purpose": "baseline"
  }
}
```

If a relation lacks its required window, submit both changes in one patch;
intermediate invalid revisions are not required. Use the complete returned base:

```python
revised = data_preparation(project_id=project_id, request={
    "op": "aggregation_patch", "candidate_ref": candidate["candidate_ref"],
    "revision_id": next_revision_uuid, "operations": typed_operations,
    "author": author, "reason": known_revision_reason
})
preview = data_preparation(project_id=project_id, request={
    "op": "aggregation_preview", "candidate_ref": revised["candidate_ref"]
})
```

Preserve each request's IDs and full intent before sending it. Repeating the exact
compose/patch request after a lost reply returns the same receipt, including after
restart. Reusing a revision UUID with a different author, reason or rule fails
`IMMUTABLE_CONFLICT`. A new patch against a superseded base fails `STALE_CANDIDATE`;
do not substitute the newest reference and blindly replay the old edit. Read and
reconcile, or compose a separate candidate from the selected historical
`from_specification`. Forking preserves the original candidate/approval; the host
must retain that parent relationship and use the exact parent preparation when
creating the subsequent draft.

Historical reads verify sealed receipts, the full retained parent chain and source
snapshots. Compose replay, patch, preview and draft additionally verify live source
bytes and the implementation fingerprint. Old history remains readable after live
source drift, but cannot silently authorize a new execution.

## Diagnostics, denominators and paged trace

Schema/binding edit rejection returns `rde-aggregation-edit-rejected-v1` with
`status="rejected"` and diagnostics; absence of an exception is not candidate
success. Identity/integrity failures such as stale references or source drift may
instead be MCP errors. A saved candidate's diagnostics are completeness checks;
execute `aggregation_preview` to discover data-dependent conflicts and counts.

Read `code`, `severity`, `errorStage`, `occurrence_count` and available locators
(`relation_id`, `feature_output`, `source_id`, `column`, `rule_id`, `field`). Grouped
preview diagnostics provide at most 20 example `unit_ids`; this is not an exhaustive
affected-case list. Page the underlying issues. For example,
`UNIQUE_VALUE_CONFLICT` on `labs.lab_latest` addresses that feature; it does not
justify changing an unrelated patient lookup. `EVENT_TIME_VALUE_CONFLICT` requires
resolving the selected-time ambiguity, not selecting a convenient row.

The summary contains `population`, sequential cohort `flow`, `relationships`,
`feature_quality`, blockers and warnings. Each relationship's `selection_flow`
reports linked records, each filter, event window and availability stages:

- `event_pairs`: source-record-to-unit pairs, including reuse across units;
- `distinct_source_records`: unique source records at that stage;
- `analysis_units_with_records` and `subjects_with_records`: distinct denominators;
- `evaluated_analysis_units` and `analysis_units_at_relation_start`: evaluation scope.

These stages precede feature missing-value aggregation and relation-level
exclusions. A relation may select seven available events while `last` yields five
values for five units. Never interpret event pairs as people. Use feature quality and exact
cell members to explain the final denominator. `exclude_statuses` removes the
**entire unit**; filtering unusable events alone does not require dropping its unit.

Preview paging uses `aggregation_read`, not a separate `aggregation_page` operation:

```python
page = data_preparation(project_id=project_id, request={
    "op": "aggregation_read", "candidate_ref": revised["candidate_ref"],
    "preview_sha256": preview["preview_sha256"],
    "section": "output", "offset": 0, "limit": 30
})
```

Keep both hashes fixed and follow `next_offset` until null. Limits are 1–100 and
offsets are nonnegative integers. The result schema is
`rde-aggregation-preview-page-v1`:

| `section` | Returned evidence |
| --- | --- |
| `issues` | Paged original issue records, not only grouped messages |
| `units` | All included/excluded units: `unit_id`, `subject_id`, `root`, `included`, `exclusions`, `values` |
| `output` | Only included units in the same record shape; this is preview data, not a published analysis CSV |
| `trace`, with `unit_id` | Unit facts and `traceable_columns` when `column` is omitted |
| `trace`, with `unit_id` and `column` | `value`, `rule`, `root_reference`, `relation_rule`, linkage status/coverage/counts, and paged `source_records` (`reference`, original `values`) |

Obtain `unit_id` and `column` from this exact preview. Each source reference binds
source hash, optional sheet, zero-based parsed record index and row hash, optionally
a column. Parsed records are not physical CSV line numbers. Null feature values
still have root/rule/linkage evidence. Reading trace can disclose source values;
the host must enforce account/project access and appropriate data exposure.

Preview files are saved under
`artifacts/data_preparation/candidates/{candidate_id}/previews/{revision_id}/`:
`preview.json`, `validation.json`, `issues.jsonl`, `trace.jsonl`. The sealed preview
receipt binds every file. The API calls its receipt hash `preview_sha256`; the
on-disk sealed object stores it as `receipt_sha256`. A cached preview is reused only
after verification, not rerun just to page it.

`aggregation_diff` always compares rules. Its `outcomes.status="compared"` requires
both exact saved previews and populations; it returns before/after populations,
added/removed units, changed-value units by column, changed-source-member units by
column, and relationship summaries. Otherwise `outcomes.status="not_evaluated"`
explains why. It does not execute missing previews. Unit identity changes may appear
as removed/added units rather than a value edit; inspect the rule diff too.

## From candidate to approved analysis input

After interpreting the complete preview and resolving scientific-definition gaps,
create an immutable preparation through the existing workflow:

```python
draft = data_preparation(project_id=project_id, request={
    "op": "draft", "preparation_id": new_preparation_uuid,
    "candidate_ref": revised["candidate_ref"],
    "author": author, "reason": known_draft_reason
})
```

Do not mix `candidate_ref` with `sources` or `specification`. `draft` verifies the
candidate and its readiness, executes native preparation, and retains the exact
candidate reference. A revision of an existing preparation additionally supplies
`parent={"preparation_id": ..., "receipt_sha256": ...}`. Candidate history and
preparation approval history are different identities; neither is inferred from a
matching title.

Draft output includes `analysis.schema.json`, typed rows, CSV, complete flow,
exceptions and cell trace. Continue through complete draft review, `approve`,
`release`, `bundle`, then `run_intake(prepared_source=...)`. See
[the preparation workflow](DATA_PREPARATION.md) for review modes and exact hashes.
An authorized automatic path uses the server-generated `automated_review` receipt;
it cannot replace it with caller-supplied booleans or claim a human review.
`clinical_validation` remains `not_performed` for automated checks.

Preview/draft success does not prove clinical identity, research-intent alignment,
causality, independence or report completeness. Existing approvals, releases,
intake versions and autoresearch inputs remain fixed when a new candidate is edited.
Use a newly reviewed preparation for changed values instead of post-release cleaning.

## Limits and verification sources

- One declared root and directly keyed relations to that root; no arbitrary multi-hop
  joins, fuzzy/probabilistic linkage, inferred patient matching or generated code.
- Native limits currently include 1–16 sources, at most 15 relations, 50 features
  per relation, 50 cohort rules, 32 edits per patch and 100 records per page. Each
  source is at most 25 MiB, 250,000 rows and 5,000,000 cells; inspect the installed
  contract/parser limits before assuming a larger export is supported.
- Source values are lexical. Root typed output supports text or finite numbers;
  dates/booleans remain text unless explicitly numeric. Datetime feature values are
  stored as ISO text. Numeric identifiers already damaged by Excel cannot be repaired
  by this workflow. XLSX formulas/errors require a reviewed values-only export.
- An explicit `at_index_basis` attests availability for an untimed relation; it is
  not evidence recovered by software. Do not add a fictitious baseline window or
  attestation solely to silence a descriptive-time warning.
- Same-source preview differences compare execution outcomes, not clinical truth.
  Independent SQL/R or a data-manager review is separate evidence; neither a match
  rate nor a technical audit is a clinical validation certificate.

Implementation: [typed edits](../src/rde/domain/models/preparation_edit.py),
[method registry/candidates](../src/rde/infrastructure/preparation/aggregation.py),
[scientific rule schema](../src/rde/domain/models/preparation.py), and
[preparation workflow](../src/rde/infrastructure/preparation/workflow.py).
Regression coverage: [candidate replay, guards, paging and differences](../tests/test_preparation_aggregation.py),
[independent SQL truth and aggregation semantics](../tests/test_preparation_engine.py).
