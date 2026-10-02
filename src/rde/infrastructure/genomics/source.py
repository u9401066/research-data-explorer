"""Verify the complete approved, multi-source R handoff; never fit a model.

The trusted Workbench adapter parses original CSV/Excel bytes. This independent
boundary checks that those saved tables, approved roles and exact R input agree.
It does not certify biological identity or a cryptographic human signature.
"""

import csv
import gzip
import math
import re

from rde.infrastructure.evidence.workflow import JS_SPACE
from rde.infrastructure.genomics import workflow as w
from rde.infrastructure.genomics.contract import publication_result, require

NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def identifier(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and value.strip(JS_SPACE) == value
        and not re.search(r"[\x00-\x1f\x7f]", value)
    )


def numeric(text):
    require(isinstance(text, str) and NUMERIC.fullmatch(text), "source has invalid numeric text")
    value = float(text)
    require(math.isfinite(value), "source contains nonfinite numbers")
    return value


def table_shape(table):
    columns, rows = table["columns"], table["rows"]
    require(
        isinstance(columns, list)
        and columns
        and all(identifier(c) for c in columns)
        and len(set(columns)) == len(columns),
        "source columns are not unique valid identities",
    )
    require(
        isinstance(rows, list)
        and all(
            isinstance(row, list)
            and len(row) == len(columns)
            and all(isinstance(c, str) for c in row)
            for row in rows
        ),
        "source row shape differs",
    )
    return columns, rows


def verify_tables(tables, audit, options):
    columns, rows = table_shape(tables["counts"])
    mc, mr = table_shape(tables["sample_metadata"])
    require(
        2 <= len(rows) <= 100_000
        and 5 <= len(columns) <= 501
        and len(rows) * (len(columns) - 1) <= 5_000_000,
        "count matrix size differs",
    )
    gi = columns.index(options["geneIdColumn"])
    sample_columns = [(i, c) for i, c in enumerate(columns) if i != gi]
    genes = [r[gi] for r in rows]
    require(
        all(identifier(g) for g in genes) and len(set(genes)) == len(genes),
        "gene identities differ",
    )
    require(
        audit["genes"] == genes
        and audit["inputGenes"] == len(rows)
        and audit["inputSamples"] == len(sample_columns),
        "audit gene/sample dimensions differ",
    )
    counts = [[numeric(row[i]) for i, _ in sample_columns] for row in rows]
    require(
        all(v.is_integer() and 0 <= v <= 2_147_483_647 for row in counts for v in row),
        "source is not a nonnegative integer count matrix",
    )
    require(audit["counts"] == counts, "R counts differ from complete original table")
    mi = mc.index(options["sampleIdColumn"])
    metadata = {row[mi]: (index, row) for index, row in enumerate(mr)}
    require(
        len(metadata) == len(mr) == len(sample_columns)
        and set(metadata) == {name for _, name in sample_columns},
        "sample join is not exact",
    )
    role_columns = [
        options["sampleIdColumn"],
        options["conditionColumn"],
        *([options["batchColumn"]] if options.get("batchColumn") else []),
        *([options["subjectColumn"]] if options.get("subjectColumn") else []),
        *options["numericCovariates"],
    ]
    require(
        set(role_columns) <= set(mc) and len(set(role_columns)) == len(role_columns),
        "sample design roles differ",
    )
    samples, conditions = [], {}
    for j, (column, name) in enumerate(sample_columns):
        index, row = metadata[name]
        condition = row[mc.index(options["conditionColumn"])]
        require(identifier(condition), "invalid condition identity")
        conditions[condition] = conditions.get(condition, 0) + 1
        sample = {
            "id": name,
            "condition": condition,
            "covariates": [numeric(row[mc.index(c)]) for c in options["numericCovariates"]],
            "metadataRow": index + 2,
            "countColumn": column + 1,
            "totalCounts": sum(r[j] for r in counts),
            "detectedGenes": sum(r[j] > 0 for r in counts),
        }
        require(sample["totalCounts"] > 0, "all-zero sample")
        for role in ("batch", "subject"):
            if options.get(role + "Column"):
                sample[role] = row[mc.index(options[role + "Column"])]
                require(identifier(sample[role]), "invalid sample design identity")
        samples.append(sample)
    require(
        audit["samples"] == samples and audit["conditions"] == conditions,
        "R sample mapping or totals differ from original metadata/counts",
    )
    require(
        options["numerator"] in conditions
        and options["reference"] in conditions
        and min(conditions.values()) >= 2,
        "unconfirmed or unreplicated comparison",
    )
    require(1 <= options["minSamples"] <= len(samples), "prefilter exceeds sample count")
    for i, _ in enumerate(options["numericCovariates"]):
        require(len({s["covariates"][i] for s in samples}) > 1, "constant covariate")
    if options.get("batchColumn"):
        require(len({s["batch"] for s in samples}) > 1, "constant batch")
    if options.get("subjectColumn"):
        require(len(conditions) == 2, "paired design needs exactly two conditions")
        for subject in {s["subject"] for s in samples}:
            pair = [s for s in samples if s["subject"] == subject]
            require(len(pair) == 2 and len({s["condition"] for s in pair}) == 2, "incomplete pair")
    if "gene_sets" not in tables:
        require(audit["geneSets"] == [] and "geneSetAudit" not in audit, "unapproved gene sets")
        return
    sc, sr = table_shape(tables["gene_sets"])
    require(len(sr) <= 100_000, "too many gene memberships")
    si, gsi = sc.index("set_id"), sc.index("gene_id")
    sets, duplicate, outside, gene_ids = {}, 0, 0, set(genes)
    for row in sr:
        name, gene = row[si], row[gsi]
        require(identifier(name) and identifier(gene), "invalid set/gene identity")
        members = sets.setdefault(name, {})
        if gene in members:
            duplicate += 1
        elif gene not in gene_ids:
            outside += 1
        members[gene] = None
    require(
        len(sets) <= 5000
        and audit["geneSets"]
        == [{"id": name, "genes": list(members)} for name, members in sets.items()],
        "R gene memberships differ from complete source table",
    )
    require(
        audit["geneSetAudit"]
        == {
            "inputMemberships": len(sr),
            "duplicateMemberships": duplicate,
            "outsideCounts": outside,
        },
        "membership review differs",
    )


def verify_csv(path, rows):
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        saved = list(reader)
    require(len(saved) == len(rows), f"{path.name}: numerical row count differs")
    for actual, expected in zip(saved, rows, strict=True):
        require(set(actual) == set(expected) - {"_row"}, f"{path.name}: numerical columns differ")
        for key, value in expected.items():
            if key == "_row":
                continue
            text = actual[key]
            if value is None:
                valid = text in {"", "NA"}
            elif type(value) is bool:
                valid = text == ("TRUE" if value else "FALSE")
            elif type(value) in (int, float):
                # write.csv rounds at 15 significant digits; JSON retains doubles.
                valid = bool(NUMERIC.fullmatch(text)) and math.isclose(
                    float(text), value, rel_tol=5e-14, abs_tol=0
                )
            else:
                valid = text == value
            require(valid, f"{path.name}: numerical {key} differs")


def verify_membership(directory, files, audit, options, drawing):
    """Check saved membership and integer summaries, without rerunning tests."""
    filters, retained = [], []
    for gene, counts, result in zip(audit["genes"], audit["counts"], drawing["genes"], strict=True):
        above = sum(v >= options["minCount"] for v in counts)
        total = sum(counts)
        keep = above >= options["minSamples"]
        reason = "all_zero" if total == 0 else "retained" if keep else "low_count"
        require(
            (result["status"] not in {"all_zero", "low_count"}) == keep
            and (keep or result["status"] == reason),
            "gene filtering differs from original counts",
        )
        filters.append(
            {
                "gene_id": gene,
                "above_min_count": above,
                "total_count": total,
                "retained": keep,
                "reason": reason,
            }
        )
        if keep:
            retained.append(counts)
    verify_csv(w.safe_path(directory, "engine/gene-filter.csv"), filters)
    for i, sample in enumerate(drawing["samples"]):
        require(
            sample["retained_counts"] == sum(row[i] for row in retained),
            "retained sample totals differ",
        )
    if not options.get("geneSets"):
        return
    universe = [g["gene_id"] for g in drawing["genes"] if g["padj"] is not None]
    direction = options["geneSets"]["direction"]
    selected = [
        g["gene_id"]
        for g in drawing["genes"]
        if g["significant"]
        and (
            direction == "both"
            or (g["log2FoldChange"] > 0 if direction == "up" else g["log2FoldChange"] < 0)
        )
    ]
    require(
        [g["set_id"] for g in drawing["gene_sets"]] == [g["id"] for g in audit["geneSets"]],
        "gene-set output identities differ",
    )
    genes, background, chosen = set(audit["genes"]), set(universe), set(selected)
    members = []
    for original, result in zip(audit["geneSets"], drawing["gene_sets"], strict=True):
        ids = set(original["genes"])
        require(
            result["original_size"] == len(ids)
            and result["eligible_size"] == len(ids & background)
            and result["overlap"] == len(ids & background & chosen),
            "gene-set output membership differs",
        )
        members.extend(
            {
                "set_id": original["id"],
                "gene_id": gene,
                "in_counts": gene in genes,
                "in_universe": gene in background,
                "selected": gene in chosen,
            }
            for gene in original["genes"]
        )
    for filename, rows in (
        ("enrichment-universe.csv", [{"gene_id": g} for g in universe]),
        ("enrichment-selected.csv", [{"gene_id": g} for g in selected]),
        ("gene-set-membership-audit.csv", members),
    ):
        # An empty membership table has no audit file in the fixed R executor.
        if filename == "gene-set-membership-audit.csv" and not members:
            continue
        require("engine/" + filename in files, "missing gene-set membership evidence")
        verify_csv(w.safe_path(directory, "engine/" + filename), rows)


def verify(project, source_id, directory, expected):
    w.canonical_id(source_id)
    require(isinstance(expected, str) and w.HEX.fullmatch(expected), "bundle SHA256 required")
    bundle_path = w.safe_path(directory, "bundle.json")
    require(w.file_hash(bundle_path) == expected, "bundle differs from requested SHA256")
    bundle = w.load_json(bundle_path)
    require(
        bundle.get("schema") == "genomics-source-bundle-v1"
        and bundle.get("project_id") == project.id
        and bundle.get("source_id") == source_id,
        "unsupported or foreign source bundle",
    )
    identity, files = bundle["identity"], bundle["files"]
    require(
        set(identity) == {"project_id", "dataset_id", "plan_id", "job_id", "node_id"},
        "incomplete identity",
    )
    for value in identity.values():
        w.canonical_id(value)
    require(isinstance(files, dict) and 20 <= len(files) <= 128, "invalid file inventory")
    total = 0
    for name, metadata in files.items():
        path = w.safe_path(directory, name)
        require(name != "bundle.json" and path.is_file(), "missing inventory file")
        size = path.stat().st_size
        require(
            type(metadata.get("bytes")) is int and size == metadata["bytes"] and size <= w.MAX_FILE,
            "file size differs or exceeds limit",
        )
        total += size
        require(
            total <= w.MAX_TOTAL and w.file_hash(path) == metadata.get("sha256"),
            "file SHA256 differs or bundle exceeds limit",
        )
    required = {
        "approved-plan.json",
        "reviewed-plan.json",
        "options.json",
        "review.json",
        "analysis-binding.json",
        "engine/engine-input.json",
        "engine/execution.json",
        "engine/analyze.R",
        "engine/output-hashes.json",
        "engine/numeric-result.json",
        "engine/result.json",
        "engine/publication-data.json",
        "engine/differential-expression.csv",
        "engine/sample-qc.csv",
        "engine/dispersion-estimates.csv",
        "engine/sample-distances.csv.gz",
        "engine/deseq2-fit.rds",
        "engine/deseq2-results.rds",
        "engine/gene-filter.csv",
        "engine/design-audit.json",
        "engine/design-matrix.csv",
        "engine/session.txt",
        "engine/packages.csv",
        "engine/independent-filtering.json",
        "engine/normalized-counts.csv.gz",
        "engine/variance-stabilized-counts.csv.gz",
    }
    require(required <= files.keys(), "missing required source evidence")

    def read(name):
        require(name in files, "unlisted source record")
        return w.load_json(w.safe_path(directory, name))

    approved, reviewed = read("approved-plan.json"), read("reviewed-plan.json")
    require(
        approved.get("status") == "approved"
        and approved.get("approvedAt")
        and approved.get("scopePolicy") == "approved-only"
        and approved.get("domainId") == "genomics",
        "approved genomics plan required",
    )
    require(
        approved.get("approvalHash") == files["reviewed-plan.json"]["sha256"],
        "reviewed bytes differ from approval",
    )
    draft = {k: v for k, v in approved.items() if k not in {"approvedAt", "approvalHash"}}
    draft["status"] = "draft"
    require(draft == reviewed, "approved plan differs from reviewed draft")
    for key, field in (("id", "plan_id"), ("projectId", "project_id"), ("datasetId", "dataset_id")):
        require(approved.get(key) == identity[field], "approved plan ownership differs")
    options, audit = read("options.json"), read("review.json")
    payload, execution = read("engine/engine-input.json"), read("engine/execution.json")
    result, numeric_result, drawing = (
        read("engine/result.json"),
        read("engine/numeric-result.json"),
        read("engine/publication-data.json"),
    )
    require(
        options
        == approved.get("genomics")
        == payload.get("options")
        == result.get("options")
        == drawing.get("options"),
        "numerical settings differ from approved plan",
    )
    steps = [s for s in approved.get("steps", []) if s.get("tool") == "genomics"]
    require(
        len(steps) == 1 and steps[0].get("args", {}).get("options") == options,
        "unapproved genomics workflow",
    )
    require(
        audit.get("valid") is True
        and audit.get("contract") == "genomics-audit-v1"
        and audit.get("issues") == []
        and payload.get("audit") == audit
        and audit.get("optionsHash") == files["options.json"]["sha256"],
        "input audit differs",
    )
    require(
        read("analysis-binding.json") == {"options": options, "audit": audit},
        "analysis binding differs",
    )
    analysis_hash = files["analysis-binding.json"]["sha256"]
    require(
        all(
            item.get("analysisHash") == analysis_hash
            for item in (payload, execution, result, numeric_result, drawing)
        ),
        "analysis hash differs from exact input binding",
    )
    roles = {"counts", "sample_metadata"} | ({"gene_sets"} if options.get("geneSets") else set())
    sources = bundle["source"]
    require(
        set(sources) == roles and len({s["dataset_id"] for s in sources.values()}) == len(roles),
        "source roles differ",
    )
    additional = approved.get("additionalSources", [])
    require(
        len(additional) == len(roles) - 1 and {s["role"] for s in additional} == roles - {"counts"},
        "approved source roles differ",
    )
    tables, declared_paths = {}, []
    for role, source in sources.items():
        w.canonical_id(source["dataset_id"])
        require(
            isinstance(source.get("filename"), str)
            and source["filename"]
            and (source.get("sheet") is None or isinstance(source["sheet"], str)),
            "source filename/sheet differs",
        )
        prefix = f"sources/{role}/"
        require(
            source["file"].startswith(prefix + "data.")
            and source["schema_file"] == prefix + "source-schema.json"
            and source["table_file"] == prefix + "source-table.json",
            "source role path differs",
        )
        for key in ("file", "schema_file", "table_file"):
            require(source[key] in files, "missing source role evidence")
            declared_paths.append(source[key])
        require(
            source["sha256"] == files[source["file"]]["sha256"]
            and source["schema_sha256"] == files[source["schema_file"]]["sha256"],
            "source role file/schema SHA256 differs",
        )
        binding = {
            "role": role,
            "datasetId": source["dataset_id"],
            "filename": source["filename"],
            "sourceHash": source["sha256"],
            "schemaHash": source["schema_sha256"],
        }
        if source.get("sheet") is not None:
            binding["sheet"] = source["sheet"]
        if role == "counts":
            require(
                source["dataset_id"] == identity["dataset_id"]
                and source["sha256"] == approved["sourceHash"]
                and source["schema_sha256"] == approved["schemaHash"],
                "counts plan binding differs",
            )
        else:
            require(binding in additional, "additional source plan binding differs")
            target = (
                options["metadataDatasetId"]
                if role == "sample_metadata"
                else options["geneSets"]["datasetId"]
            )
            require(source["dataset_id"] == target, "source role differs from options")
        tables[role] = read(source["table_file"])
        columns, rows = table_shape(tables[role])
        schema = read(source["schema_file"])
        require(
            schema.get("dataset_id") == source["dataset_id"] and schema.get("intake") == "tabular",
            "source schema belongs to another intake/dataset",
        )
        require(
            schema.get("source")
            == {
                "sha256": source["sha256"],
                "filename": source["filename"],
                "sheet": source.get("sheet"),
            },
            "schema does not pin original filename/sheet",
        )
        require(
            schema["row_count"] == len(rows)
            and schema["column_count"] == len(columns)
            and [v["name"] for v in schema["variables"]] == columns,
            "source schema/table shape differs",
        )
    require(len(set(declared_paths)) == len(declared_paths), "source roles alias the same file")
    require(
        execution.get("status") == "completed"
        and execution.get("containerRemoved") is True
        and re.fullmatch(r"sha256:[a-f0-9]{64}", execution.get("image", "")),
        "completed pinned R execution required",
    )
    for key, name in (
        ("inputSha256", "engine/engine-input.json"),
        ("scriptSha256", "engine/analyze.R"),
    ):
        require(execution.get(key) == files[name]["sha256"], "R input/script binding differs")
    engine_hashes = read("engine/output-hashes.json")
    require(
        set(engine_hashes)
        == {n[7:] for n in files if n.startswith("engine/")} - {"output-hashes.json"},
        "incomplete R output inventory",
    )
    for name, value in engine_hashes.items():
        require(
            "/" not in name and files[f"engine/{name}"]["sha256"] == value,
            "R output binding differs",
        )
    require(
        set(files) == set(declared_paths) | required | {"engine/" + n for n in engine_hashes},
        "unexpected or missing source files",
    )
    verify_tables(tables, audit, options)
    require(result.get("contract") == "genomics-deseq2-v1", "unsupported numerical contract")
    for key, value in numeric_result.items():
        if key != "warnings":
            require(result.get(key) == value, "final result differs from numerical checkpoint")
    for key in (
        "options",
        "method",
        "package",
        "design",
        "summary",
        "samples",
        "pca",
        "enrichment",
    ):
        require(result[key] == drawing[key], "drawing data differs from R result")
    require(
        set(numeric_result["warnings"]) <= set(drawing["warnings"]) <= set(result["warnings"]),
        "R warning lineage differs",
    )
    require(
        [g["gene_id"] for g in drawing["genes"]] == audit["genes"],
        "drawing gene order/membership differs",
    )
    by_gene = {g["gene_id"]: g for g in drawing["genes"]}
    require(
        all(g == by_gene[g["gene_id"]] for g in result["topGenes"]),
        "top genes differ from full results",
    )
    require(len(drawing["samples"]) == len(audit["samples"]), "drawing sample count differs")
    for sample, original in zip(drawing["samples"], audit["samples"], strict=True):
        require(
            sample["sample_id"] == original["id"]
            and sample["condition"] == original["condition"]
            and sample["total_counts"] == original["totalCounts"]
            and sample["detected_genes"] == original["detectedGenes"],
            "drawing sample differs from source",
        )
        for role in ("batch", "subject"):
            require(sample.get(role) == original.get(role), "drawing sample design differs")
    for name, key in (
        ("differential-expression.csv", "genes"),
        ("sample-qc.csv", "samples"),
        ("dispersion-estimates.csv", "dispersion"),
    ):
        verify_csv(w.safe_path(directory, "engine/" + name), drawing[key])
    if drawing["pca"]["status"] == "completed":
        require("engine/pca-coordinates.csv" in files, "missing PCA coordinates")
        verify_csv(w.safe_path(directory, "engine/pca-coordinates.csv"), drawing["pca_coordinates"])
    if options.get("geneSets"):
        require("engine/gene-set-enrichment.csv" in files, "missing gene set results")
        verify_csv(w.safe_path(directory, "engine/gene-set-enrichment.csv"), drawing["gene_sets"])
    with gzip.open(
        w.safe_path(directory, "engine/sample-distances.csv.gz"), "rt", newline="", encoding="utf-8"
    ) as file:
        distances = list(csv.reader(file))
    names = [s["id"] for s in audit["samples"]]
    require(
        distances[0] == ["sample_id", *names] and len(distances) == len(names) + 1,
        "distance CSV dimensions differ",
    )
    for row, original in zip(distances[1:], drawing["sample_distances"], strict=True):
        require(
            row[0] == original["sample_id"]
            and len(row) == len(names) + 1
            and all(
                math.isclose(numeric(v), saved, rel_tol=5e-14, abs_tol=0)
                for v, saved in zip(row[1:], original["values"], strict=True)
            ),
            "distance CSV differs",
        )
    verify_membership(directory, files, audit, options, drawing)
    frozen = publication_result(
        drawing,
        {
            "contract": "verified-external-r-genomics-v1",
            "project_id": project.id,
            "source_id": source_id,
            "identity": identity,
            "source": sources,
            "bundle_sha256": expected,
            "numeric_file_sha256": files["engine/publication-data.json"]["sha256"],
            "image": execution["image"],
            "script_sha256": execution["scriptSha256"],
            "verification_scope": "saved source bytes, trusted adapter parsed tables, approved roles/options, complete R input and outputs; not biological truth, independent extraction or patient EDA audit",
        },
    )
    return bundle, frozen
