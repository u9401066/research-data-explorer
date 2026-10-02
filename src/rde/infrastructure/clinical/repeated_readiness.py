"""Check saved pairing and denominators without rerunning a statistical estimate."""

import math


def check_cases(result):
    try:
        return _check_cases(result)
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def _check_cases(result):
    spec, ledger = result["spec"], result["case_ledger"]
    columns = [m["column"] for m in spec["measurements"]]
    cohort, masks = ledger["cohort_data_rows"], ledger["observed_bitmask_by_cohort_row"]
    full_mask = (1 << len(columns)) - 1
    if (
        len(cohort) != ledger["cohort_rows"]
        or len(cohort) != len(masks)
        or any(type(v) is not int or not 0 <= v <= full_mask for v in masks)
        or cohort != sorted(set(cohort))
        or sorted(cohort + ledger["filter_excluded_data_rows"])
        != list(range(1, ledger["input_rows"] + 1))
    ):
        return False
    common = [r for r, mask in zip(cohort, masks, strict=True) if mask == full_mask]
    missing = [r for r, mask in zip(cohort, masks, strict=True) if mask != full_mask]
    if (
        common != ledger["complete_data_rows"]
        or missing != ledger["missing_excluded_data_rows"]
        or len(common) != result["n"]
        or result["n"] != ledger["n"]
        or result["n"] < 5
    ):
        return False
    for i, column in enumerate(columns):
        observed = sum(bool(mask & (1 << i)) for mask in masks)
        if (
            ledger["observed_by_occasion"][column] != observed
            or ledger["missing_by_role"][column] != len(cohort) - observed
        ):
            return False
    if [o["column"] for o in result["occasions"]] != columns or any(
        o["n"] != len(common) for o in result["occasions"]
    ):
        return False
    if [p["data_row"] for p in result["observations"]] != common:
        return False
    values = {}
    for point in result["observations"]:
        if len(point["values"]) != len(columns):
            return False
        for column, value in zip(columns, point["values"], strict=True):
            if type(value) not in (int, float) or not math.isfinite(value):
                return False
            values[point["data_row"], column] = value
    if len(result["contrasts"]) != len(spec["contrasts"]) or len(ledger["contrasts"]) != len(
        spec["contrasts"]
    ):
        return False
    for i, (pair, planned, actual) in enumerate(
        zip(spec["contrasts"], ledger["contrasts"], result["contrasts"], strict=True)
    ):
        pair_mask = sum(1 << columns.index(c) for c in pair)
        expected = (
            common
            if spec["case_strategy"] == "complete"
            else [r for r, mask in zip(cohort, masks, strict=True) if mask & pair_mask == pair_mask]
        )
        if (
            actual["id"] != planned["id"]
            or actual["id"] != f"contrast_{i+1}"
            or actual["columns"] != pair
            or planned["columns"] != pair
            or actual["data_rows"] != expected
            or planned["complete_data_rows"] != expected
            or planned["missing_excluded_data_rows"] != sorted(set(cohort) - set(expected))
            or actual["n"] != len(expected)
            or planned["n"] != len(expected)
            or actual["difference_summary"]["n"] != len(expected)
            or [p["data_row"] for p in actual["observations"]] != expected
        ):
            return False
        for point in actual["observations"]:
            for column, name in zip(pair, ["first", "second"], strict=True):
                value = point[name]
                if type(value) not in (int, float) or not math.isfinite(value):
                    return False
                key = (point["data_row"], column)
                if key in values and values[key] != value:
                    return False
                values[key] = value
            if point["difference"] != point["first"] - point["second"]:
                return False
    omnibus = result["omnibus"]
    if spec["omnibus"]:
        if (
            not omnibus
            or omnibus["data_rows"] != common
            or omnibus["n"] != len(common)
            or omnibus["effect_kind"] != "kendall_w"
        ):
            return False
    elif omnibus is not None:
        return False
    return True
