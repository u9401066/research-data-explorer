"""Real discovery and dispatcher coverage; not numerical-method validation."""

import asyncio
import importlib
import json

from mcp import Client
import pandas as pd
import pytest

from rde.interface.mcp import analysis_catalog as catalog
from rde.interface.mcp.contracts import CONTRACTS
from rde.interface.mcp.server import create_server


def test_checked_declaration_matches_live_schemas_and_source_contracts():
    generated = asyncio.run(catalog.build_catalog())
    assert catalog.load_catalog() == generated
    assert generated["catalog_sha256"] == catalog.declaration_hash(generated)
    assert len(generated["families"]) == 24
    assert len(generated["groups"]) == 6
    assert set(sum([group["family_ids"] for group in generated["groups"]], [])) == {
        family["id"] for family in generated["families"]
    }
    for family in generated["families"]:
        for item in family["bindings"]:
            assert item["tool"] in CONTRACTS
            schema = family["tool_input_schemas"][item["tool"]]
            assert schema["type"] == "object"
            if "argument" in item:
                assert item["argument"] in schema["properties"]
        assert family["requirements"] and family["limitations"] and family["outputs"]
        assert family["contract_sources"]
        assert family["execution"]["availability"] == "not_probed"


def test_hash_projection_is_explicit_and_tampering_fails_closed(tmp_path, monkeypatch):
    full = catalog.load_catalog()
    summary = catalog.get_catalog()
    selected = catalog.get_catalog("survival")
    assert summary["catalog_sha256"] == selected["catalog_sha256"] == full["catalog_sha256"]
    assert summary["hash_scope"] == "complete_catalog_declaration"
    assert summary["detail"] == "summary"
    assert selected["detail"] == "full"
    assert all(
        "options_schema" not in f and "tool_input_schemas" not in f for f in summary["families"]
    )
    assert len(selected["families"]) == 1 and selected["families"][0]["options_schema"]
    response = catalog.get_catalog(detail=True)
    response.pop("selection")
    response.pop("detail")
    assert catalog.declaration_hash(response) == full["catalog_sha256"]
    full["families"][0]["title"] = "changed"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(full), encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    with pytest.raises(ValueError, match="verification"):
        catalog.load_catalog()


@pytest.mark.parametrize("family", [f["id"] for f in catalog.family_declarations()])
def test_each_family_is_discoverable_with_real_schema_scope(family):
    item = catalog.get_catalog(family)["families"][0]
    assert item["id"] == family
    assert item["tool_input_schemas"] and item["schema_scope"]
    if family in catalog.SPEC_TYPES or family == "preparation":
        schema = item["options_schema"]
        assert schema["type"] == "object" and schema["properties"] and schema["required"]
        assert schema["additionalProperties"] is False
    else:
        # No guessed empty schema for opaque dict/heterogeneous parameters.
        assert "options_schema" not in item


def test_real_mcp_discovery_without_project_and_unknown_family_error(tmp_path, monkeypatch):
    from rde.application.session import get_session
    import httpx

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: pytest.fail("Discovery performed a network probe")
    )

    async def run():
        async with Client(create_server()) as client:
            tools = (await client.list_tools()).tools
            tool = next(item for item in tools if item.name == "get_analysis_catalog")
            assert tool.annotations.read_only_hint is True
            assert set(tool.input_schema["properties"]) == {"family", "detail"}
            result = await client.call_tool("get_analysis_catalog", {})
            assert not result.is_error
            data = result.structured_content["data"]
            assert len(data["families"]) == 24
            assert result.structured_content["artifacts"] == []
            complete = await client.call_tool("get_analysis_catalog", {"detail": True})
            complete_data = complete.structured_content["data"]
            assert complete_data.pop("selection") == {"family": None}
            assert complete_data.pop("detail") == "full"
            assert complete_data == catalog.load_catalog()
            detail = await client.call_tool("get_analysis_catalog", {"family": "prediction"})
            assert (
                detail.structured_content["data"]["families"][0]["options_schema"]["title"]
                == "PredictionSpec"
            )
            error = await client.call_tool("get_analysis_catalog", {"family": "not_a_method"})
            assert error.is_error
            assert error.structured_content["error"]["code"] == "ANALYSIS_CATALOG_ERROR"
            resource = await client.read_resource("rde://capabilities")
            capabilities = json.loads(resource.contents[0].text)
            assert capabilities["analysis_catalog"]["catalog_sha256"] == data["catalog_sha256"]
            assert len(capabilities["analysis_catalog"]["family_ids"]) == 24
            assert "legacy adapter subset" in capabilities["clinical_methods_scope"]

    before = set(tmp_path.rglob("*"))
    assert get_session().active_project_id is None
    asyncio.run(run())
    assert get_session().active_project_id is None
    assert set(tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "family", [f for f in catalog.SPEC_TYPES if f not in {"sample_size", "prediction"}]
)
def test_clinical_family_selector_reaches_its_actual_parser(family, monkeypatch):
    from rde.interface.mcp.tools.clinical_tools import parse_clinical_spec

    module, name = catalog.SPEC_TYPES[family]
    spec = getattr(importlib.import_module(module), name)
    monkeypatch.setattr(spec, "parse", lambda options: (name, options))
    item = catalog.get_catalog(family)["families"][0]
    for declared in item["methods"]:
        assert parse_clinical_spec(declared["selector"]) == (name, declared["selector"])


def test_unknown_clinical_family_is_rejected_by_native_parser():
    from rde.interface.mcp.tools.clinical_tools import parse_clinical_spec

    with pytest.raises(ValueError):
        parse_clinical_spec({"family": "unknown_family"})


def test_advanced_selectors_dispatch_through_actual_normalization(monkeypatch):
    import rde.infrastructure.adapters.analysis_delegator as delegation
    from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine

    engine = ScipyStatisticalEngine
    reached = []
    for display, target in engine._TEST_DISPATCH.items():
        monkeypatch.setattr(
            engine, target, lambda *a, _display=display, **k: {"dispatch": _display}
        )
    monkeypatch.setattr(engine, "generate_table_one", lambda *a, **k: {"dispatch": "table_one"})
    monkeypatch.setattr(
        delegation,
        "run_clinical_analysis",
        lambda df, method, config: {"dispatch": method},
    )
    monkeypatch.setattr(delegation.AnalysisDelegator, "_check_automl", lambda self: False)
    monkeypatch.setattr(
        delegation.AnalysisDelegator,
        "_run_local_advanced_lite",
        lambda self, df, method, config: {"result": {"dispatch": method}},
    )
    monkeypatch.setattr(
        delegation.AnalysisDelegator,
        "_run_learning_curve_cusum",
        lambda *a, **k: {"dispatch": "learning_curve_cusum"},
    )
    delegator = delegation.AnalysisDelegator()
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [2, 3, 4]})
    item = catalog.get_catalog("advanced")["families"][0]
    for declared in item["methods"]:
        result = delegator.run_analysis(
            frame, declared["selector"]["analysis_type"], {"variables": ["x", "y"]}
        )["result"]
        if declared["id"] == "automl":
            assert declared["execution_kind"] == "optional_vendor"
            assert "does not support" in result["error"]
        elif declared["id"] == "descriptive":
            assert set(result["summary"]) == {"x", "y"}
        else:
            assert "error" not in result and result["dispatch"]
            reached.append(result["dispatch"])
    assert set(engine._TEST_DISPATCH) <= set(reached)
    assert set(delegation.CLINICAL_METHODS) <= set(reached)
    assert set(delegation.LOCAL_ADVANCED_LITE) <= set(reached)
    assert "kolmogorov_smirnov" not in {m["id"] for m in item["methods"]}
    unknown = delegator.run_analysis(frame, "not_a_real_method", {"variables": ["x"]})
    assert "Unsupported test" in unknown["result"]["error"]


def test_native_schemas_keep_null_nested_shapes_and_scientific_parser_guards():
    from rde.infrastructure.clinical.survival import SurvivalSpec
    from rde.infrastructure.prediction.contract import PredictionSpec

    survival = {
        "family": "survival",
        "time": "days",
        "event": "event",
        "event_value": "1",
        "censor_value": "0",
        "time_origin": "Date of study entry",
        "time_unit": "days",
        "independent_rows": True,
    }
    assert SurvivalSpec.parse(survival).family == "survival"
    properties = catalog.get_catalog("survival")["families"][0]["options_schema"]["properties"]
    assert {s["type"] for s in properties["group"]["anyOf"]} == {"string", "null"}
    assert properties["references"]["additionalProperties"]["type"] == "string"
    for malformed in [
        {**survival, "independent_rows": False},
        {**survival, "invented": True},
        {"family": "survival"},
    ]:
        with pytest.raises(ValueError):
            SurvivalSpec.parse(malformed)
    prediction = {
        "target": "outcome",
        "predictors": ["age"],
        "prediction_time_definition": "Study entry before the outcome",
        "study_design": "observational_cohort",
        "sampling": "single_gate",
        "sampling_description": "One common entry path",
        "target_definition": "Synthetic prespecified binary endpoint",
        "features_available_at_prediction": True,
    }
    assert PredictionSpec.parse(prediction).task == "binary"
    with pytest.raises(ValueError):
        PredictionSpec.parse({**prediction, "features_available_at_prediction": False})
    with pytest.raises(ValueError):
        PredictionSpec.parse({**prediction, "task": "imaginary"})
    prepared = catalog.get_catalog("preparation")["families"][0]["options_schema"]
    assert prepared["$defs"] and all(schema for schema in prepared["$defs"].values())


def test_external_receipts_are_not_advertised_as_native_model_fitting():
    for family in ("external_evidence", "external_genomics"):
        item = catalog.get_catalog(family)["families"][0]
        assert item["execution"]["kind"] == "external_receipt"
        assert all(m["execution_kind"] == "external_receipt" for m in item["methods"])
        assert all(not b["tool"].startswith("run_") for b in item["bindings"])


@pytest.mark.parametrize("value", ["", "Survival", "does_not_exist", 1, False, []])
def test_unknown_or_malformed_family_never_falls_back(value):
    with pytest.raises(ValueError):
        catalog.get_catalog(value)


def copy_package(tmp_path, monkeypatch):
    import shutil

    installed = tmp_path / "site-packages"
    shutil.copytree(
        catalog.SOURCE_ROOT / "rde",
        installed / "rde",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setattr(catalog, "SOURCE_ROOT", installed)
    monkeypatch.setattr(
        catalog, "CATALOG_PATH", installed / "rde/interface/mcp/analysis_catalog.json"
    )
    return installed


def test_runtime_verifies_installed_wheel_layout_and_invalidates_cached_source_hash(
    tmp_path, monkeypatch
):
    import os

    installed = copy_package(tmp_path, monkeypatch)
    original = catalog.load_catalog()
    assert any(
        item["path"].endswith("/analysis_catalog.py") for item in original["declaration_sources"]
    )
    target = installed / "rde/infrastructure/clinical/measurement.py"
    old_stat = target.stat()
    raw = target.read_bytes()
    # Same length and deliberately restored mtime must still invalidate cache.
    target.write_bytes(raw.replace(b"measurement", b"MEASUREMENT", 1))
    os.utime(target, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    with pytest.raises(ValueError, match="source drift"):
        catalog.load_catalog()
    target.write_bytes(raw)
    assert catalog.load_catalog()["catalog_sha256"] == original["catalog_sha256"]


@pytest.mark.parametrize("change", ["new", "removed", "generator"])
def test_runtime_detects_inventory_and_generator_drift(tmp_path, monkeypatch, change):
    installed = copy_package(tmp_path, monkeypatch)
    catalog.load_catalog()
    if change == "new":
        (installed / "rde/unregistered_capability.py").write_text(
            "# undeclared new implementation\n"
        )
    elif change == "removed":
        (installed / "rde/interface/mcp/contracts.py").unlink()
    else:
        path = installed / "rde/interface/mcp/analysis_catalog.py"
        path.write_bytes(path.read_bytes() + b"\n# changed declaration\n")
    with pytest.raises(ValueError, match="source (inventory changed|drift)"):
        catalog.load_catalog()


def test_real_mcp_returns_structured_error_on_runtime_source_drift(tmp_path, monkeypatch):
    installed = copy_package(tmp_path, monkeypatch)
    target = installed / "rde/infrastructure/clinical/survival.py"
    target.write_bytes(target.read_bytes() + b"\n# native algorithm changed\n")

    async def run():
        async with Client(create_server()) as client:
            result = await client.call_tool("get_analysis_catalog", {"family": "survival"})
            assert result.is_error
            assert result.structured_content["error"]["code"] == "ANALYSIS_CATALOG_ERROR"
            assert "source drift" in result.structured_content["message"]
            assert result.structured_content["artifacts"] == []

    asyncio.run(run())


def test_full_declaration_hash_matches_javascript_number_and_unicode_serialization():
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the cross-language golden hash check")
    value = catalog.load_catalog()
    javascript = r"""
const fs = require('node:fs'); const { createHash } = require('node:crypto');
const value = JSON.parse(fs.readFileSync(0, 'utf8'));
delete value.catalog_sha256;
const canonical = v => Array.isArray(v) ? v.map(canonical)
  : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v;
process.stdout.write(createHash('sha256').update(JSON.stringify(canonical(value)), 'utf8').digest('hex'));
"""
    result = subprocess.run(
        [node, "-e", javascript],
        input=json.dumps(value, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == value["catalog_sha256"]
    assert catalog.canonical_bytes({"值": [-0.0, 0.0, 1.0, 0.95]}) == '{"值":[0,0,1,0.95]}'.encode()


def test_diagnostic_catalog_roles_follow_reference_first_test_second_native_semantics():
    from rde.infrastructure.clinical.measurement import (
        MeasurementSpec,
        measurement_preflight,
        prepare_measurement,
    )

    item = catalog.get_catalog("diagnostic_accuracy")["families"][0]
    roles = {role["id"]: role["label"] for role in item["input_roles"]}
    assert roles["first"] == "參考標準" and roles["second"] == "檢測"
    spec = MeasurementSpec.parse(
        {
            "family": "diagnostic_accuracy",
            "first": "reference",
            "second": "test",
            "context": "Prespecified synthetic diagnostic fixture",
            "independent_rows": True,
            "diagnostic": {
                "positive": "D",
                "negative": "N",
                "reference_description": "Independent reference standard",
                "reference_independence": "independent",
                "sampling": "single_gate",
                "test_kind": "binary",
                "threshold": None,
                "positive_direction": None,
                "test_positive": "T",
                "test_negative": "F",
                "threshold_basis": "Prespecified source test classification",
                "threshold_status": "prespecified",
                "reference_indeterminate": [],
                "test_indeterminate": [],
            },
        }
    )
    frame = pd.DataFrame(
        {
            "reference": ["D"] * 5 + ["N"] * 3,
            "test": ["T", "T", "F", "F", "F", "T", "F", "F"],
        }
    )
    prepared, _, _ = prepare_measurement(frame, spec)
    assert int(prepared["first"].sum()) == 5
    assert int(prepared["second"].sum()) == 3
    assert measurement_preflight(frame, spec)["reference_positive"] == 5


def test_cli_check_is_read_only_and_rejects_source_drift(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    installed = copy_package(tmp_path, monkeypatch)
    env = {**os.environ, "PYTHONPATH": str(installed), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-m", "rde.interface.mcp.analysis_catalog", "--check"]
    original = catalog.CATALOG_PATH.read_bytes()
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (
        "24 families" in result.stdout and catalog.load_catalog()["catalog_sha256"] in result.stdout
    )
    assert catalog.CATALOG_PATH.read_bytes() == original
    target = installed / "rde/infrastructure/clinical/measurement.py"
    target.write_bytes(target.read_bytes() + b"\n# changed runtime code\n")
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert failed.returncode != 0 and "source drift" in failed.stderr
    assert catalog.CATALOG_PATH.read_bytes() == original


def test_matching_catalog_binds_exact_native_method_and_required_caliper():
    result = catalog.get_catalog("matching")["families"][0]
    assert result["id"] + "." + result["methods"][0]["id"] == "matching.optimal_1to1_logit_caliper"
    assert (
        result["options_schema"]["properties"]["method"]["default"] == "optimal_1to1_logit_caliper"
    )
    assert result["options_schema"]["properties"]["inference"]["default"] == "pair_cluster_cr1_t"
    assert "caliper_sd" in result["options_schema"]["required"]
    assert result["options_schema"]["additionalProperties"] is False
    assert any("matched_treated" in text for text in result["limitations"])
