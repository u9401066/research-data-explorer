import pandas as pd

from rde.domain.models.variable import Variable, VariableRole, VariableType
from rde.domain.services.collinearity_checker import check_collinearity
from rde.interface.mcp.tools.plan_tools import _build_readiness_variable_scope


def test_outcome_association_does_not_become_a_collinearity_warning():
    variables = [
        Variable("outcome", "float64", VariableType.CONTINUOUS, VariableRole.OUTCOME),
        Variable("age", "float64", VariableType.CONTINUOUS, VariableRole.COVARIATE),
        Variable("lab", "float64", VariableType.CONTINUOUS, VariableRole.PREDICTOR),
    ]
    scope = _build_readiness_variable_scope(
        variables=variables,
        plan={"analyses": [{"variables": ["outcome", "age", "lab"]}]},
        roles={"outcome": "outcome", "covariates": ["age", "lab"]},
    )
    assert scope["continuous_variables"] == ["outcome", "age", "lab"]
    assert scope["collinearity_variables"] == ["age", "lab"]
    df = pd.DataFrame({"outcome": [2, 4, 6, 8], "age": [1, 2, 3, 4], "lab": [1, 3, 3, 1]})
    assert check_collinearity(df).has_collinearity
    assert not check_collinearity(df, scope["collinearity_variables"]).has_collinearity
    # Genuine predictor collinearity must still be detected.
    df["lab"] = df["age"] * 3
    assert check_collinearity(df, scope["collinearity_variables"]).has_collinearity


def test_empty_predictor_scope_does_not_silently_scan_all_numeric_columns():
    df = pd.DataFrame({"outcome": [2, 4, 6], "id": [1, 2, 3]})
    assert check_collinearity(df).has_collinearity
    assert not check_collinearity(df, []).has_collinearity
