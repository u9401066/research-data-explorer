"""Validate saved meta/netmeta results without fitting models or imputing evidence."""

from copy import deepcopy
from itertools import combinations, permutations
import math
import re

from rde.infrastructure.prediction.splits import digest


def _require(condition, message):
    if not condition:
        raise ValueError(f"Evidence publication receipt: {message}")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _same(a, b):
    return _finite(a) and _finite(b) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-11)


def _unique(rows, key):
    values = [r[key] for r in rows]
    _require(len(values) == len(set(values)), f"duplicate {key}")
    return {r[key]: r for r in rows}


def _effect(row, measure, *, unavailable=False):
    fields = ("effect", "se", "lower_effect", "upper_effect", "estimate", "lower", "upper", "p")
    complete = all(_finite(row.get(k)) for k in fields)
    if unavailable:
        _require(not complete, "unavailable comparison contains a complete estimate")
        _require(
            all(row.get(k) is None or _finite(row.get(k)) for k in fields), "nonfinite estimate"
        )
        return
    _require(complete, "missing or nonfinite effect/interval")
    _require(row["se"] > 0 and 0 <= row["p"] <= 1, "invalid SE or p value")
    _require(row["lower_effect"] <= row["effect"] <= row["upper_effect"], "inverted interval")
    for transformed, raw in (
        ("estimate", "effect"),
        ("lower", "lower_effect"),
        ("upper", "upper_effect"),
    ):
        try:
            value = row[raw] if measure == "MD" else math.exp(row[raw])
        except OverflowError as error:
            raise ValueError("Evidence publication receipt: ratio scale overflow") from error
        _require(
            _same(row[transformed], value), "effect display scale differs from saved analysis scale"
        )


def validate_result(result):
    """Check identity, direction, complete membership and display-scale consistency."""
    _require(result.get("contract") == "evidence-synthesis-v2", "unsupported numerical contract")
    o = result["options"]
    _require(o["mode"] in {"pairwise", "network"}, "invalid mode")
    _require(
        o["model"] in {"common", "random"} and o["measure"] in {"OR", "RR", "MD"}, "invalid method"
    )
    _require(_finite(o["confidence"]) and 0.8 <= o["confidence"] <= 0.999, "invalid confidence")
    _require(
        o["measure"] != "MD" or bool(o.get("outcomeUnit", "").strip()), "MD needs a declared unit"
    )
    treatments = _unique(result["treatment_map"], "code")
    studies = _unique(result["study_map"], "code")
    _require(2 <= len(treatments) <= 40 and 2 <= len(studies) <= 500, "invalid identity counts")
    _require(
        list(treatments) == [f"T{i+1:03}" for i in range(len(treatments))],
        "invalid treatment codes",
    )
    _require(list(studies) == [f"S{i+1:03}" for i in range(len(studies))], "invalid study codes")
    _unique(list(treatments.values()), "label")
    _unique(list(studies.values()), "study_id")
    reference = [r["code"] for r in treatments.values() if r["label"] == o["reference"]]
    _require(len(reference) == 1, "unknown reference")
    reference = reference[0]

    def identity(row):
        a, b = row["treatment_code"], row["comparator_code"]
        _require(a in treatments and b in treatments and a != b, "invalid comparison identity")
        _require(
            row["treatment"] == treatments[a]["label"]
            and row["comparator"] == treatments[b]["label"],
            "raw treatment label mismatch",
        )
        return a, b

    original = _unique(result["observations"], "row")
    review = result["review"]
    decisions = _unique(review["decisions"], "row")
    _require(
        1 <= review["inputRows"] <= 2000
        and set(decisions) == set(range(2, review["inputRows"] + 2)),
        "incomplete source decision ledger",
    )
    for field in ("inputHash", "optionsHash"):
        _require(bool(re.fullmatch("[a-f0-9]{64}", review[field])), "invalid source hash")
    _require(
        all(r["decision"] in {"include", "exclude"} for r in decisions.values()), "unreviewed row"
    )
    _require(
        set(original) == {k for k, r in decisions.items() if r["decision"] == "include"},
        "included rows differ from review",
    )
    _require(
        result["study_count"] == len(studies) and result["contrast_count"] == len(original),
        "incorrect study/comparison counts",
    )
    for row in original.values():
        identity(row)
        _require(
            row["study_code"] in studies
            and studies[row["study_code"]]["study_id"] == row["study_id"],
            "study identity mismatch",
        )
        _require(
            _finite(row["effect"]) and _finite(row["se"]) and row["se"] > 0, "invalid source effect"
        )
        for key in ("study_id", "report_id", "source"):
            _require(row[key] == decisions[row["row"]][key], "source row lineage mismatch")
    _require(
        {r["study_code"] for r in original.values()} == set(studies), "unused or missing study"
    )
    for code in studies:
        rows = [r for r in original.values() if r["study_code"] == code]
        arms = {c for r in rows for c in identity(r)}
        _require(len(rows) == len(arms) * (len(arms) - 1) // 2, "incomplete multi-arm study")
        for field in (
            "risk_of_bias",
            "bias_reason",
            "source",
            "report_id",
            "population",
            "effect_modifiers",
        ):
            _require(len({r[field] for r in rows}) == 1, f"inconsistent study-level {field}")
        _require(
            rows[0]["risk_of_bias"] in {"low", "some_concerns", "high", "unclear"},
            "unknown bias judgment",
        )
    pair_sources = {}
    for row in original.values():
        key = ":".join(sorted(identity(row)))
        pair_sources.setdefault(key, []).append(row)
    pooled = _unique(result["pairwise"], "pair")
    direct = _unique(result["direct_observations"], "row")
    _require(
        set(pooled) == set(pair_sources) and set(direct) == set(original),
        "incomplete direct effects",
    )
    for key, rows in pair_sources.items():
        p = pooled[key]
        _require(":".join(identity(p)) == key, "pooled direction mismatch")
        _effect(p, o["measure"])
        _require(p["studies"] == len(rows), "incorrect direct study count")
        _require(
            len({r["study_code"] for r in rows}) == len(rows), "duplicate study in one direct pair"
        )
        weights = []
        for row in rows:
            v = direct[row["row"]]
            a, b = identity(v)
            _require(v["pair"] == key and f"{a}:{b}" == key, "direct pair mismatch")
            _require(
                v["study_code"] == row["study_code"] and v["study_id"] == row["study_id"],
                "direct study mismatch",
            )
            reversed_direction = row["treatment_code"] != a
            _require(
                v["source_direction_reversed"] is reversed_direction,
                "source direction flag mismatch",
            )
            _require(
                _same(v["effect"], row["effect"] * (-1 if reversed_direction else 1))
                and _same(v["se"], row["se"]),
                "direct effect differs from input",
            )
            _effect(v, o["measure"])
            _require(_finite(v["weight"]) and v["weight"] > 0, "invalid study weight")
            _require(
                _finite(v["weight_percent"]) and v["weight_percent"] > 0, "invalid relative weight"
            )
            weights.append(v["weight"])
        for row in rows:
            v = direct[row["row"]]
            _require(
                _same(v["weight_percent"], v["weight"] / sum(weights) * 100),
                "weights are not within-pair percentages",
            )
    topology = result["topology"]
    nodes = _unique(topology["nodes"], "code")
    edges = _unique(topology["edges"], "pair")
    _require(
        set(nodes) == set(treatments) and set(edges) == set(pair_sources), "incomplete topology"
    )
    for item in [*nodes.values(), *edges.values()]:
        if "pair" in item:
            _require(
                f"{item['treatment_code']}:{item['comparator_code']}" == item["pair"],
                "edge identity mismatch",
            )
        else:
            _require(item["label"] == treatments[item["code"]]["label"], "node label mismatch")
        rows = (
            pair_sources[item["pair"]]
            if "pair" in item
            else [r for r in original.values() if item["code"] in identity(r)]
        )
        codes = {r["study_code"] for r in rows}
        _require(
            set(item["rows"]) == {r["row"] for r in rows} and len(item["rows"]) == len(rows),
            "topology source rows mismatch",
        )
        _require(
            set(item["study_codes"]) == codes
            and len(item["study_codes"]) == len(codes)
            and item["studies"] == len(codes),
            "network counts are not independent studies",
        )
    if o["mode"] == "pairwise":
        _require(
            len(treatments) == 2 and result["network"] is None and len(result["reference"]) == 1,
            "invalid pairwise scope",
        )
        row = result["reference"][0]
        _require(identity(row)[1] == reference, "incorrect selected reference direction")
        _effect(row, o["measure"])
        pooled_row = next(iter(pooled.values()))
        _require(
            _same(
                row["effect"],
                pooled_row["effect"]
                * (1 if row["treatment_code"] == pooled_row["treatment_code"] else -1),
            ),
            "reference changes pooled estimate",
        )
    else:
        _require(len(treatments) >= 3, "network needs three treatments")
        network = result["network"]
        pairs = [identity(r) for r in network["estimates"]]
        _require(
            len(pairs) == len(set(pairs)) and set(pairs) == set(permutations(treatments, 2)),
            "missing network contrasts",
        )
        for row in network["estimates"]:
            _effect(row, o["measure"])
        expected = [r for r in network["estimates"] if r["comparator_code"] == reference]
        _require(network["reference"] == expected, "reference table differs from full network")
        local = result["diagnostics"]["local"]
        _require(local["method"] == "Back-calculation", "unreviewed local splitting method")
        groups = {}
        for row in local["rows"]:
            a, b = identity(row)
            kind = row["component"]
            _require(a < b and kind in {"direct", "indirect", "compare"}, "invalid split identity")
            _require(kind not in groups.setdefault((a, b), {}), "duplicate local component")
            groups[a, b][kind] = row
            _require(row["status"] in {"estimated", "not_estimable"}, "unknown local availability")
            _effect(
                row,
                "MD" if kind == "compare" else o["measure"],
                unavailable=row["status"] == "not_estimable",
            )
        _require(set(groups) == set(combinations(treatments, 2)), "missing local contrasts")
        for rows in groups.values():
            _require(set(rows) == {"direct", "indirect", "compare"}, "missing local component")
            d, i, c = [rows[k] for k in ("direct", "indirect", "compare")]
            if c["status"] == "estimated":
                _require(
                    _same(c["effect"], d["effect"] - i["effect"])
                    and _same(c["se"], math.hypot(d["se"], i["se"])),
                    "inconsistency difference is not direct minus indirect",
                )
    return result


def publication_result(analysis, source):
    """Build a renderer input after the importing workflow verifies actual source files."""
    validate_result(analysis)
    result = {
        "status": "completed",
        "spec": {"family": "evidence_synthesis"},
        "source": deepcopy(source),
        "analysis": deepcopy(analysis),
    }
    result["receipt_sha256"] = digest(result)
    return result
