import asyncio
import uuid

import pytest

from rde.interface.mcp.canvas import canvas_contract, validate_connection
from rde.interface.mcp.server import create_server
from rde.application.session import get_session
from test_sample_size_workflow import draft, tool
from test_sample_size_planning import planning_spec


def facts(**changes):
    return {**dict.fromkeys(canvas_contract()["facts"], False), **changes}


def test_typed_ports_and_phase_gates_are_independent():
    for source in ["preparation", "dataset", "question"]:
        assert not validate_connection(source, "create_plan", facts(preparationUnready=True))[
            "allowed"
        ]
        assert validate_connection(source, "create_plan", facts())["allowed"]
    assert validate_connection("plan_draft", "sample_size", facts())["allowed"]
    for source in ["plan_approved", "analysis", "exploration", "result"]:
        assert not validate_connection(source, "sample_size", facts())["allowed"]
    assert not validate_connection("question", "sample_size", facts(analysisBound=True))["allowed"]
    assert not validate_connection("plan_draft", "sample_size", facts(executionStarted=True))[
        "allowed"
    ]
    assert not validate_connection("plan_approved", "run_analysis", facts())["allowed"]
    assert validate_connection("analysis", "revise_plan", facts(hasPlan=True))["allowed"]
    with pytest.raises(ValueError):
        validate_connection("question", "sample_size", {})
    with pytest.raises(ValueError):
        validate_connection("question", "sample_size", {**facts(), "analysisBound": "false"})


def test_mcp_exposes_identical_contract_and_validates_without_mutating():
    server = create_server()
    contract = asyncio.run(server.call_tool("get_workflow_contract", {}))
    assert contract.structured_content["data"]["canvas_contract"] == canvas_contract()
    response = asyncio.run(
        server.call_tool(
            "validate_workflow_connection",
            {
                "source_type": "analysis",
                "transition": "sample_size",
                "facts": facts(hasPlan=True),
            },
        )
    )
    assert not response.is_error
    assert response.structured_content["data"]["allowed"] is False
    assert get_session().active_project_id is None


def test_native_sample_draft_cannot_bypass_a_locked_analysis_project():
    project, previous = draft()
    pipeline = get_session().get_pipeline(project.id)
    pipeline.plan_locked = True
    blocked = tool(
        "draft_sample_size_plan",
        {
            "project_id": project.id,
            "plan_id": str(uuid.uuid4()),
            "planning_options": planning_spec("independent_means").to_dict(),
        },
        error=True,
    )
    assert "前瞻樣本數規劃須在計畫鎖定前" in blocked
    retained = tool(
        "get_sample_size_plan", {"project_id": project.id, "plan_id": previous["plan_id"]}
    )
    assert retained["plan"]["receipt_sha256"] == previous["receipt_sha256"]
