from __future__ import annotations

import pandas as pd

from rde.application.use_cases.analyze_variable import AnalyzeVariableUseCase
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableType
from rde.domain.ports import StatisticalEnginePort
from rde.domain.services.numeric_plausibility import apply_numeric_plausibility_filters


class DummyStatisticalEngine(StatisticalEnginePort):
    def __init__(self) -> None:
        self.last_data = None

    def run_test(self, data, test_name, variables, **kwargs):
        self.last_data = data.copy()
        return {"statistic": 0.95, "p_value": 0.2, "interpretation": "ok"}

    def generate_table_one(self, data, group_var, variables, **kwargs):
        raise NotImplementedError


def test_apply_numeric_plausibility_filters_masks_implausible_adult_anthropometrics() -> None:
    df = pd.DataFrame(
        {
            "age_years": [77, 67, 59, 89, 65],
            "bmi": [555.37, 232.48, 2.54, 8.28, 24.6],
            "height_cm": [55.0, 43.8, 166.0, 163.0, 170.0],
            "weight_kg": [168.0, 44.6, 7.0, 22.0, 71.0],
        }
    )

    cleaned, findings = apply_numeric_plausibility_filters(df, ["bmi", "height_cm", "weight_kg"])
    finding_map = {finding.variable_name: finding for finding in findings}

    assert cleaned["bmi"].notna().sum() == 1
    assert cleaned["height_cm"].notna().sum() == 3
    assert cleaned["weight_kg"].notna().sum() == 3
    assert finding_map["bmi"].excluded_count == 4
    assert finding_map["height_cm"].excluded_count == 2
    assert finding_map["weight_kg"].excluded_count == 2


def test_analyze_variable_excludes_implausible_values_before_statistics() -> None:
    df = pd.DataFrame(
        {
            "age_years": [61, 72, 77, 84],
            "bmi": [24.0, 26.0, 555.0, 8.2],
        }
    )
    dataset = Dataset(
        variables=[
            Variable(name="age_years", dtype="float64", variable_type=VariableType.CONTINUOUS),
            Variable(name="bmi", dtype="float64", variable_type=VariableType.CONTINUOUS),
        ],
        row_count=len(df),
    )
    engine = DummyStatisticalEngine()

    profile = AnalyzeVariableUseCase(engine).execute(dataset, df, "bmi")

    assert profile.count == 2
    assert profile.missing_count == 2
    assert profile.descriptive is not None
    assert round(profile.descriptive["mean"], 2) == 25.0
    assert round(profile.descriptive["max"], 2) == 26.0
    assert profile.advisories is not None
    assert any("排除 2 筆不合理值" in advisory for advisory in profile.advisories)
    assert engine.last_data is not None
    assert engine.last_data["bmi"].dropna().tolist() == [24.0, 26.0]