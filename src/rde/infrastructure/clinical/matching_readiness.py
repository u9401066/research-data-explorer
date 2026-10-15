"""Structural and scalar consistency of frozen matching evidence, without refitting."""

import math


def check_cases(result):
    try:
        ledger, rows, pairs = result["case_ledger"], result["source_case_ledger"], result["pairs"]
        matched = ledger["complete_data_rows"]
        used = [p[key] for p in pairs for key in ("treated_data_row", "control_data_row")]
        identities = [p[key] for p in pairs for key in ("treated_id", "control_id")]
        by_row = {r["source_data_row"]: r for r in rows}
        return (
            [r["source_data_row"] for r in rows] == list(range(1, ledger["input_rows"] + 1))
            and len(used) == len(set(used)) == len(set(identities)) == result["n"] == 2 * len(pairs)
            and sorted(used) == matched
            and sorted(matched + ledger["matching_excluded_data_rows"])
            == ledger["propensity_complete_data_rows"]
            and all(
                [r["source_data_row"] for r in rows if r["status"] == status] == ledger[key]
                for status, key in [
                    ("matched", "complete_data_rows"),
                    ("unmatched", "matching_excluded_data_rows"),
                    ("outside_cohort", "filter_excluded_data_rows"),
                    ("missing_required", "missing_excluded_data_rows"),
                ]
            )
            and all(
                by_row[p[f"{role}_data_row"]]["subject_id"] == p[f"{role}_id"]
                and by_row[p[f"{role}_data_row"]]["pair_id"] == p["pair_id"]
                and by_row[p[f"{role}_data_row"]]["treatment_code"] == code
                for p in pairs
                for role, code in [("control", 0), ("treated", 1)]
            )
            and all(
                p["absolute_logit_distance"] <= result["matching"]["absolute_logit_caliper"]
                for p in pairs
            )
        )
    except (KeyError, TypeError, ValueError):
        return False


def check_inference(result):
    try:
        effect, pairs, population = result["effect"], result["pairs"], result["matching_population"]
        values = [p["treated_outcome"] - p["control_outcome"] for p in pairs]
        finite = all(
            math.isfinite(effect[k])
            for k in ["estimate", "standard_error", "statistic", "p_value", "ci_lower", "ci_upper"]
        )
        binary = result["paired_binary"]
        binary_ok = (
            binary is None
            if result["spec"]["outcome_type"] == "continuous"
            else (
                binary["cells"]
                == [
                    [
                        sum(p["control_outcome"] == c and p["treated_outcome"] == t for p in pairs)
                        for t in (0, 1)
                    ]
                    for c in (0, 1)
                ]
                and binary["discordant_pairs"] == binary["cells"][0][1] + binary["cells"][1][0]
            )
        )
        return (
            finite
            and effect["standard_error"] > 0
            and 0 <= effect["p_value"] <= 1
            and effect["ci_lower"] <= effect["estimate"] <= effect["ci_upper"]
            and effect["df"] == len(pairs) - 1
            and len(pairs) >= 5
            and effect["n_pairs"] == population["matched_pairs"] == len(pairs)
            and population["matched_people"] == result["n"]
            and population["complete_cases"]
            == len(result["case_ledger"]["propensity_complete_data_rows"])
            and population["unmatched_treated"] + population["unmatched_controls"] + result["n"]
            == population["complete_cases"]
            and math.isclose(
                effect["estimate"], sum(values) / len(values), rel_tol=1e-10, abs_tol=1e-12
            )
            and math.isclose(
                effect["confidence_level"], result["spec"]["confidence_level"], abs_tol=1e-12
            )
            and result["propensity"]["converged"] is True
            and result["matching"]["replacement"] is False
            and result["matching"]["ratio"] == "1:1"
            and result["multiplicity"]["members"] == ["matched_treated_contrast"]
            and bool(result["balance"])
            and bool(result["basis_balance"])
            and bool(result["diagnostics"]["quality_policy"])
            and binary_ok
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
