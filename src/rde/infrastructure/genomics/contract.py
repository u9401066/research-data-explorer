"""Check the complete, saved DESeq2 plotting data before any figure is written.

These consistency checks do not establish biological sample identity or approval.
The source workflow must separately verify the original inputs and execution.
"""

from copy import deepcopy
import math
import re

from rde.infrastructure.prediction.splits import digest


def require(ok, message):
    if not ok:
        raise ValueError(f"Genomics publication: {message}")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def number(value, label, minimum=None, maximum=None, nullable=False):
    if value is None and nullable:
        return
    require(finite(value), f"{label} must be finite")
    require(minimum is None or value >= minimum, f"{label} below its range")
    require(maximum is None or value <= maximum, f"{label} above its range")


def identity(rows, key, label):
    require(isinstance(rows, list), f"{label} must be an array")
    names = [r[key] for r in rows]
    require(
        all(isinstance(v, str) and v and "\x00" not in v for v in names)
        and len(set(names)) == len(names),
        f"{label} identities must be nonempty and unique",
    )
    return names


def validate_result(a):
    require(a["schema"] == "genomics-publication-data-v1", "unsupported plotting data")
    require(re.fullmatch(r"[a-f0-9]{64}", a["analysisHash"]) is not None, "analysis hash")
    o, method, summary = a["options"], a["method"], a["summary"]
    require(o["assay"] == "bulk_rna_seq" and o["scale"] == "raw_counts", "bulk raw counts only")
    require(
        o["rawCountsConfirmed"] is True and o["biologicalReplicatesConfirmed"] is True,
        "raw counts and biological replication confirmations are required",
    )
    require(o["numerator"] != o["reference"], "comparison direction is identical")
    number(o["alpha"], "alpha", 0.001, 0.2)
    number(o["lfcThreshold"], "fold-change null", 0, 10)
    require(
        method["alpha"] == o["alpha"]
        and method["lfcThreshold"] == o["lfcThreshold"]
        and method["pAdjust"] == "BH"
        and method["alternative"] == "greaterAbs"
        and method["lfc"] == "unshrunken maximum-likelihood log2 fold change"
        and method["confidenceLevel"] == 0.95
        and method["automaticCountReplacement"] is False
        and method["independentFiltering"] == o["independentFiltering"]
        and method["sizeFactor"] == o["sizeFactor"]
        and method["fitRequested"] == o["fitType"],
        "method differs from the requested DESeq2 specification",
    )
    require(a["package"]["DESeq2"] == "1.52.0", "unsupported DESeq2 numerical contract")
    genes = identity(a["genes"], "gene_id", "gene")
    samples = identity(a["samples"], "sample_id", "sample")
    require(2 <= len(genes) <= 100_000 and 3 <= len(samples) <= 500, "input dimensions")
    require(
        summary["inputGenes"] == len(genes) and summary["samples"] == len(samples),
        "summary dimensions differ",
    )
    design = a["design"]
    require(
        design["valid"] is True
        and design["sampleOrder"] == samples
        and design["n"] == len(samples)
        and design["rank"] == design["parameters"]
        and design["residualDf"] == len(samples) - design["rank"] > 0
        and design["direction"] == {"numerator": o["numerator"], "reference": o["reference"]},
        "sample order, design or direction differs",
    )
    require(
        {o["numerator"], o["reference"]} <= {s["condition"] for s in a["samples"]},
        "comparison groups are missing",
    )
    for s in a["samples"]:
        for k in ("total_counts", "detected_genes", "retained_counts"):
            require(type(s[k]) is int and s[k] >= 0, f"sample {k} must be a nonnegative integer")
        number(s["size_factor"], "size factor", 0)
        require(
            s["size_factor"] > 0
            and s["retained_counts"] <= s["total_counts"]
            and s["detected_genes"] <= len(genes),
            "sample QC bounds",
        )
    states = {
        "all_zero",
        "low_count",
        "tested",
        "independent_filtered",
        "cooks_outlier",
        "not_estimable",
    }
    retained = []
    for g in a["genes"]:
        require(g["status"] in states and type(g["significant"]) is bool, "unknown gene status")
        number(g["baseMean"], "normalized mean", 0)
        for k in ("log2FoldChange", "lfcLower95", "lfcUpper95", "stat"):
            number(g[k], k, nullable=True)
        for k in ("lfcSE", "dispersion"):
            number(g[k], k, 0, nullable=True)
        for k in ("pvalue", "padj"):
            number(g[k], k, 0, 1, nullable=True)
        require(
            g["significant"] == (g["padj"] is not None and g["padj"] < o["alpha"]),
            "FDR selection differs from saved adjusted p values",
        )
        if g["status"] in {"all_zero", "low_count"}:
            require(
                all(
                    g[k] is None
                    for k in (
                        "log2FoldChange",
                        "lfcSE",
                        "lfcLower95",
                        "lfcUpper95",
                        "stat",
                        "pvalue",
                        "padj",
                        "dispersion",
                    )
                ),
                "excluded genes cannot have fitted estimates",
            )
        else:
            retained.append(g["gene_id"])
            require(g["dispersion"] is not None and g["dispersion"] > 0, "retained dispersion")
        if g["status"] == "tested":
            require(
                all(g[k] is not None for k in ("pvalue", "padj", "log2FoldChange", "lfcSE")),
                "tested gene is incomplete",
            )
        elif g["status"] == "independent_filtered":
            require(
                o["independentFiltering"] is True and g["pvalue"] is not None and g["padj"] is None,
                "independent-filtered p values",
            )
        else:
            require(
                g["pvalue"] is None and g["padj"] is None, "unavailable p values must remain null"
            )
        if g["log2FoldChange"] is not None:
            require(g["lfcSE"] is not None and g["lfcSE"] > 0, "fold-change uncertainty missing")
            require(
                g["lfcLower95"] is not None
                and g["lfcUpper95"] is not None
                and g["lfcLower95"] <= g["log2FoldChange"] <= g["lfcUpper95"],
                "confidence interval order",
            )
    expected = {
        "prefilterRetained": len(retained),
        **{
            key: sum(g["status"] == state for g in a["genes"])
            for key, state in [
                ("allZero", "all_zero"),
                ("lowCount", "low_count"),
                ("tested", "tested"),
                ("independentFiltered", "independent_filtered"),
                ("cooksOutlier", "cooks_outlier"),
                ("notEstimable", "not_estimable"),
            ]
        },
        "significant": sum(g["significant"] for g in a["genes"]),
        "up": sum(g["significant"] and g["log2FoldChange"] > 0 for g in a["genes"]),
        "down": sum(g["significant"] and g["log2FoldChange"] < 0 for g in a["genes"]),
    }
    require(
        all(summary[k] == v for k, v in expected.items()), "gene summary differs from full rows"
    )
    require(identity(a["dispersion"], "gene_id", "dispersion") == retained, "dispersion gene order")
    retained_set = set(retained)
    retained_rows = {g["gene_id"]: g for g in a["genes"] if g["gene_id"] in retained_set}
    for d in a["dispersion"]:
        g = retained_rows[d["gene_id"]]
        require(
            d["baseMean"] == g["baseMean"] and d["final"] == g["dispersion"],
            "dispersion values differ",
        )
        for key in ("geneWise", "fitted", "final"):
            number(d[key], key, 0, nullable=key == "geneWise")
    require(
        identity(a["sample_distances"], "sample_id", "distance") == samples, "distance sample order"
    )
    require(
        all(
            isinstance(row["values"], list) and len(row["values"]) == len(samples)
            for row in a["sample_distances"]
        ),
        "distance matrix shape",
    )
    for i, row in enumerate(a["sample_distances"]):
        for j, value in enumerate(row["values"]):
            number(value, "sample distance", 0)
            require(value == a["sample_distances"][j]["values"][i], "distance matrix is asymmetric")
        require(row["values"][i] == 0, "distance diagonal must be zero")
    pca = a["pca"]
    if pca["status"] == "completed":
        require(identity(a["pca_coordinates"], "sample_id", "PCA") == samples, "PCA sample order")
        require(
            isinstance(pca["genes"], list)
            and 2 <= len(pca["genes"]) <= 500
            and len(set(pca["genes"])) == len(pca["genes"])
            and set(pca["genes"]) <= set(retained),
            "PCA genes differ from retained genes",
        )
        for key in ("PC1", "PC2"):
            number(pca[key], "PCA variance", 0, 1)
        require(pca["PC1"] + pca["PC2"] <= 1 + 1e-12, "PCA variance exceeds one")
        for row, sample in zip(a["pca_coordinates"], a["samples"], strict=True):
            require(row["condition"] == sample["condition"], "PCA condition differs")
            for key in ("PC1", "PC2"):
                number(row[key], "PCA coordinate")
    else:
        require(
            pca["status"] == "not_estimable" and pca.get("reason") and a["pca_coordinates"] == [],
            "unavailable PCA cannot carry coordinates",
        )
    sets = a["gene_sets"]
    identity(sets, "set_id", "gene set")
    if "geneSets" not in o:
        require(
            a["enrichment"] == {"status": "not_requested"} and sets == [], "unrequested gene sets"
        )
    else:
        e, spec = a["enrichment"], o["geneSets"]
        universe = summary["tested"]
        selected = summary[{"up": "up", "down": "down", "both": "significant"}[spec["direction"]]]
        require(
            e["source"] == spec["source"]
            and e["version"] == spec["version"]
            and e["direction"] == spec["direction"]
            and e["universeSize"] == universe
            and e["selected"] == selected
            and e["sets"] == len(sets),
            "gene-set source or universe differs",
        )
        for row in sets:
            for key in (
                "original_size",
                "universe_size",
                "eligible_size",
                "outside_universe",
                "selected_genes",
                "overlap",
            ):
                require(
                    type(row[key]) is int and row[key] >= 0,
                    "gene-set counts must be nonnegative integers",
                )
            require(
                row["universe_size"] == universe
                and row["selected_genes"] == selected
                and row["eligible_size"] <= universe
                and row["original_size"] == row["eligible_size"] + row["outside_universe"]
                and row["overlap"] <= min(selected, row["eligible_size"]),
                "gene-set counts differ",
            )
            state = (
                "empty_universe"
                if universe == 0
                else "below_min_size"
                if row["eligible_size"] < spec["minSize"]
                else "above_max_size"
                if row["eligible_size"] > spec["maxSize"]
                else "tested"
            )
            require(row["status"] == state, "gene-set eligibility differs")
            for key in ("pvalue", "padj"):
                number(row[key], key, 0, 1, nullable=state != "tested")
                require(
                    state == "tested" or row[key] is None, "untested gene-set p must remain null"
                )
            number(row["fold_enrichment"], "fold enrichment", 0, nullable=True)
        require(
            e["tested"] == sum(s["status"] == "tested" for s in sets)
            and e["significant"]
            == sum(s["padj"] is not None and s["padj"] < o["alpha"] for s in sets),
            "gene-set summary differs",
        )


def publication_result(analysis, provenance):
    """Seal a numerical rendering receipt after the caller verifies source bytes."""
    validate_result(analysis)
    require(isinstance(provenance, dict) and provenance, "source provenance is required")
    value = {
        "status": "completed",
        "spec": {"family": "genomics"},
        "analysis": deepcopy(analysis),
        "source": deepcopy(provenance),
    }
    return {**value, "receipt_sha256": digest(value)}
