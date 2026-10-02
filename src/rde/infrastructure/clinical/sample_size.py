"""Integer prospective planning, with actual design power and preserved scenarios."""

from decimal import Decimal, ROUND_CEILING
from importlib.metadata import version
import math

from rde.domain.models.sample_size import SampleSizeSpec
from .survival import digest


METHOD_CONTRACT = {
    "id": "rde-prospective-sample-size-v1",
    "null_difference": 0,
    "alternative": "two-sided",
    "independent_means": "Noncentral t; pooled common variance; df=n1+n2-2; both rejection tails.",
    "paired_means": "Noncentral t on complete-pair differences; df=pairs-1; both rejection tails.",
    "independent_proportions": "Normal approximation; pooled null/unpooled alternative variance; no continuity correction; both tails.",
    "integer_search": "Smallest integer multiple of the reduced allocation ratio meeting target power; at least two observations per group or two pairs.",
    "enrollment": "ceil(evaluable allocation blocks/(1-common loss rate)); paired n denotes intended pairs, not measurements.",
    "sources": [
        "https://database.ich.org/sites/default/files/E9_Guideline.pdf",
        "https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.html",
        "https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.html",
        "https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.power_proportions_2indep.html",
    ],
}

LIMITATIONS = [
    "這是核准假設成立時的前瞻規劃，不是已觀察資料的事後 power，也不驗證假設來源的真實性或臨床適用性。",
    "單一主要雙側檢定、零差值虛無假設；不含多重主要結果、期中分析、群集、等效性／非劣性或精確罕見事件檢定。",
    "共同失訪率只調整預期可分析數，不保證留存、不處理失訪偏差，也不修正不依從或治療交叉造成的效果稀釋。",
    "主情境在計算前固定；敏感度情境不自動替代主情境。Power 曲線是固定假設下的設計量，不是信賴區間。",
]


def design_power(spec: SampleSizeSpec, scenario: dict, blocks: int) -> float:
    from statsmodels.stats.power import TTestIndPower, TTestPower
    from statsmodels.stats.proportion import power_proportions_2indep

    if spec.design == "paired_means":
        value = TTestPower().power(
            abs(scenario["difference"] / scenario["sd"]),
            blocks,
            spec.alpha,
            alternative="two-sided",
        )
    else:
        n1, n2 = [n * blocks for n in spec.allocation]
        if spec.design == "independent_means":
            value = TTestIndPower().power(
                abs(scenario["difference"] / scenario["sd"]),
                n1,
                spec.alpha,
                ratio=n2 / n1,
                alternative="two-sided",
            )
        else:
            p1, p2 = scenario["probabilities"]
            value = power_proportions_2indep(
                diff=p1 - p2,
                prop2=p2,
                nobs1=n1,
                ratio=n2 / n1,
                alpha=spec.alpha,
                alternative="two-sided",
                return_results=False,
            )
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Power calculation returned a nonfinite or out-of-range result.")
    return float(value)


def design_counts(spec, blocks):
    if spec.design == "paired_means":
        return {"pairs": blocks, "group_1": None, "group_2": None, "total_units": blocks}
    n1, n2 = [n * blocks for n in spec.allocation]
    return {"pairs": None, "group_1": n1, "group_2": n2, "total_units": n1 + n2}


def calculate_sample_size(spec: SampleSizeSpec):
    spec.validate()
    unit_count = sum(spec.allocation) if spec.allocation else 1
    minimum = max(math.ceil(2 / n) for n in spec.allocation) if spec.allocation else 2
    maximum = spec.max_evaluable // unit_count
    if maximum < minimum:
        raise ValueError("The maximum evaluable count is below the smallest permitted allocation.")
    results = []
    for scenario in spec.scenarios:
        low, high = minimum - 1, minimum
        while design_power(spec, scenario, high) < spec.target_power:
            low = high
            if high == maximum:
                raise ValueError(
                    f"Scenario {scenario['id']!r} cannot reach target power within max_evaluable; revise the plan explicitly."
                )
            high = min(high * 2, maximum)
        while high - low > 1:
            middle = (high + low) // 2
            if design_power(spec, scenario, middle) >= spec.target_power:
                high = middle
            else:
                low = middle
        blocks = high
        power = design_power(spec, scenario, blocks)
        previous = design_power(spec, scenario, blocks - 1) if blocks > minimum else None
        if power < spec.target_power or (previous is not None and previous >= spec.target_power):
            raise ValueError("Integer sample-size minimality verification failed.")
        retained = Decimal(1) - Decimal(str(scenario["loss_rate"]))
        recruit_blocks = int((Decimal(blocks) / retained).to_integral_value(rounding=ROUND_CEILING))
        evaluable, enrollment = design_counts(spec, blocks), design_counts(spec, recruit_blocks)
        curve_end = min(maximum, max(blocks + 1, math.ceil(blocks * 1.4)))
        curve_blocks = sorted(
            {
                minimum,
                blocks,
                *([blocks - 1] if blocks > minimum else []),
                *(minimum + (curve_end - minimum) * i // 60 for i in range(61)),
            }
        )
        warnings = []
        expected_cells = None
        if spec.design == "independent_proportions":
            p1, p2 = scenario["probabilities"]
            n1, n2 = evaluable["group_1"], evaluable["group_2"]
            pooled = (n1 * p1 + n2 * p2) / (n1 + n2)
            expected_cells = {
                "alternative": [n1 * p1, n1 * (1 - p1), n2 * p2, n2 * (1 - p2)],
                "pooled_null": [n1 * pooled, n1 * (1 - pooled), n2 * pooled, n2 * (1 - pooled)],
            }
            if min(v for values in expected_cells.values() for v in values) < 10:
                warnings.append(
                    "至少一格預期事件或非事件數少於 10；這是常態近似的診斷提示，不是精確檢定或適用性保證。需另審閱近似品質。"
                )
        results.append(
            {
                "scenario_id": scenario["id"],
                "label": scenario["label"],
                "primary": scenario["id"] == spec.primary_scenario_id,
                "assumptions": scenario,
                "allocation_blocks": blocks,
                "evaluable": evaluable,
                "enrollment": enrollment,
                "enrollment_blocks": recruit_blocks,
                "achieved_power": power,
                "previous_allocation": None
                if previous is None
                else {
                    **design_counts(spec, blocks - 1),
                    "power": previous,
                },
                "expected_retained_units": float(Decimal(enrollment["total_units"]) * retained),
                "expected_cells": expected_cells,
                "warnings": warnings,
                "power_curve": [
                    {
                        **design_counts(spec, b),
                        "allocation_blocks": b,
                        "power": design_power(spec, scenario, b),
                    }
                    for b in curve_blocks
                ],
            }
        )
    result = {
        "schema": "sample-size-result-v1",
        "status": "completed",
        "spec": spec.to_dict(),
        "method_contract": METHOD_CONTRACT,
        "assumptions_sha256": digest(spec.to_dict()),
        "engine_versions": {
            name: version(name)
            for name in ("research-data-explorer", "statsmodels", "scipy", "numpy")
        },
        "scenarios": results,
        "limitations": LIMITATIONS,
        "n_definition": "complete independent pairs"
        if spec.design == "paired_means"
        else "independent subjects, total across both groups",
    }
    result["receipt_sha256"] = digest(result)
    return result
