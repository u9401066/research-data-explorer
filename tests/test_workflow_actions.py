import asyncio
import shutil
from pathlib import Path

from mcp import Client

from rde.interface.mcp.server import create_server


def test_workflow_actions_follow_real_drafts_confirmations_and_artifacts(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures/iris_sample.csv", raw / "iris.csv")

    async def run():
        async with Client(create_server()) as client:

            async def call(tool, **args):
                response = await client.call_tool(tool, args)
                assert not response.is_error, response.content
                return response.structured_content

            bootstrap = (await call("get_workflow_contract"))["data"]["action_contract"]
            assert bootstrap["actions"][0]["status"] == "needs_input"
            setup = await call("init_project", name="action-contract", data_dir=str(raw))
            pid = setup["context"]["project_id"]

            async def actions():
                contract = (await call("get_workflow_contract", project_id=pid))["data"][
                    "action_contract"
                ]
                return contract, {action["id"]: action for action in contract["actions"]}

            before, states = await actions()
            assert states["intake"]["status"] == "ready"
            assert states["schema"]["status"] == "blocked"
            assert (await actions())[0]["revision"] == before["revision"]
            intake = await call("run_intake", project_id=pid, directory=str(raw))
            ds = intake["data"]["dataset_id"]
            await call("build_schema", project_id=pid, dataset_id=ds)
            contract, states = await actions()
            assert contract["revision"] != before["revision"]
            assert states["draft_alignment"]["status"] == "needs_input"
            assert states["draft_alignment"]["required_facts"][0]["provider"] == "user"
            args = dict(
                project_id=pid,
                dataset_id=ds,
                research_question="Compare sepal_length by species",
                variable_roles={"outcome": "sepal_length", "group": "species"},
            )
            await call("align_concept", **args, confirm=False)
            _, states = await actions()
            assert states["review_alignment"]["status"] == "needs_confirmation"
            assert not states["review_alignment"]["can_automate"]
            assert states["draft_plan"]["status"] == "blocked"
            await call("align_concept", **args, confirm=True)
            _, states = await actions()
            assert states["draft_plan"]["status"] == "ready"
            assert states["draft_plan"]["can_automate"]
            # Existing in-memory completion must not conceal a missing prerequisite file.
            schema = (
                Path(setup["context"]["project_root"])
                / "artifacts/phase_02_schema_registry/schema.json"
            )
            schema.unlink()
            _, states = await actions()
            assert states["draft_alignment"]["status"] == "blocked"
            assert any(
                b["code"] == "MISSING_ARTIFACT" for b in states["draft_alignment"]["blockers"]
            )

    asyncio.run(run())
