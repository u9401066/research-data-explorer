"""Derive bounded comparisons from the same native summary cards available to a reader."""


def study_relations(cards, kind):
    enabled = {
        "table": ("mean_difference", "median_difference", "range", "quartiles"),
        "distribution": ("range",),
        "group_spread": ("quartiles",),
        "spread_range": ("range", "quartiles"),
        "group_contrasts": ("mean_difference", "median_difference"),
    }.get(kind)
    if not enabled:
        return None
    index = {}
    pairs = []
    for key, card in cards.items():
        group, field = card.get("group"), card["statistic"]
        if group is None:
            continue
        index[(group, field)] = {"id": "R" + key, "value": card["value"], "unit": card["unit"]}
        if field == "mean_difference":
            pairs.append((group, card.get("reference_group")))
    results = []
    for group, reference in pairs[:3]:
        entry = {"comparison": group, "reference": reference}
        for field in enabled:
            if field.endswith("_difference"):
                metric = field.removesuffix("_difference")
                inputs = {
                    role: index.get(key)
                    for role, key in (
                        ("comparison", (group, metric)),
                        ("reference", (reference, metric)),
                        ("native_difference", (group, field)),
                    )
                }
                present = all(c and type(c["value"]) in (float, int) for c in inputs.values())
                sign = None
                if present:
                    v = inputs["native_difference"]["value"]
                    sign = "positive" if v > 0 else "negative" if v < 0 else "zero"
                entry[field] = {
                    "status": "computed" if present else "unavailable",
                    "sign": sign,
                    "inputs": inputs,
                }
            else:
                low, high = ("min", "max") if field == "range" else ("q1", "q3")
                inputs = {
                    prefix + "_" + metric: index.get((g, metric))
                    for prefix, g in (("comparison", group), ("reference", reference))
                    for metric in (low, high)
                }
                interval = None
                status = "unavailable"
                if all(c and type(c["value"]) in (float, int) for c in inputs.values()):
                    lower = max(
                        inputs["comparison_" + low]["value"], inputs["reference_" + low]["value"]
                    )
                    upper = min(
                        inputs["comparison_" + high]["value"], inputs["reference_" + high]["value"]
                    )
                    if lower <= upper:
                        interval = [lower, upper]
                    status = (
                        "disjoint" if lower > upper else "touching" if lower == upper else "overlap"
                    )
                entry[field] = {"status": status, "intersection": interval, "inputs": inputs}
        results.append(entry)
    return {
        "status": "available" if pairs else "unavailable",
        "available_comparisons": len(pairs),
        "included_comparisons": len(results),
        "comparisons": results,
        "direction": "comparison minus reference",
        "interval_definition": "closed intersection: [max(lower endpoints), min(upper endpoints)] if nonempty",
        "limits": "摘要區間重疊不能判定個別觀測值相同，也無法推定分類機率、分布重疊比例或療效。",
    }
