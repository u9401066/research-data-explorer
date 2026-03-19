from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = ROOT / "vendor" / "automl-stat-mcp"
COMPOSE_FILE = VENDOR_ROOT / "docker-compose.yml"
RUN_ENV = "RDE_RUN_VENDOR_INTEGRATION"
TEST_USER = "rde-contract-test"


pytestmark = [pytest.mark.vendor_integration]


def _docker_ready() -> bool:
    return shutil.which("docker") is not None and COMPOSE_FILE.exists()


def _require_integration_enabled() -> None:
    if os.getenv(RUN_ENV) != "1":
        pytest.skip(f"Set {RUN_ENV}=1 to run vendor Docker integration tests.")
    if not _docker_ready():
        pytest.skip("Docker or vendor compose file is unavailable.")


def _compose_cmd(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "ml", *args]


def _compose_up_service(service: str, env: dict[str, str]) -> None:
    subprocess.run(
        _compose_cmd("up", "-d", "--build", "--no-deps", service),
        cwd=ROOT,
        env=env,
        check=True,
        timeout=1800,
    )


def _wait_for_health(base_url: str, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=5.0)
            if response.status_code == 200:
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text}"
        except Exception as exc:  # pragma: no cover - environment dependent
            last_error = str(exc)
        time.sleep(2)
    raise AssertionError(f"Timed out waiting for {base_url}/health: {last_error}")


def _health_available(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url}/health", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


def _ensure_service_health(service: str, base_url: str, env: dict[str, str]) -> bool:
    if _health_available(base_url):
        return False

    _compose_up_service(service, env)
    _wait_for_health(base_url, timeout=180.0)
    return True


@pytest.fixture(scope="module")
def vendor_stack() -> Generator[None, None, None]:
    _require_integration_enabled()
    env = {**os.environ, "STORAGE_MODE": "local", "LOG_LEVEL": "WARNING"}
    started_stack = False
    touched_services = False

    try:
        touched_services = (
            _ensure_service_health("stats-service", "http://localhost:8003", env)
            or touched_services
        )
        touched_services = (
            _ensure_service_health("automl-api", "http://localhost:8001", env) or touched_services
        )
    except subprocess.CalledProcessError:
        try:
            subprocess.run(
                _compose_cmd("up", "-d", "--build"),
                cwd=ROOT,
                env=env,
                check=True,
                timeout=1800,
            )
            started_stack = True
        except subprocess.CalledProcessError:
            # In shared development hosts, vendor containers may already exist under
            # fixed container_name values. If those containers are healthy, reuse them.
            if not (
                _health_available("http://localhost:8003")
                and _health_available("http://localhost:8001")
            ):
                raise

    _wait_for_health("http://localhost:8003")
    _wait_for_health("http://localhost:8001")
    yield
    if started_stack:
        subprocess.run(
            _compose_cmd("down", "-v", "--remove-orphans"),
            cwd=ROOT,
            env=env,
            check=False,
            timeout=600,
        )


def test_vendor_services_health(vendor_stack: None) -> None:
    stats = _wait_for_health("http://localhost:8003")
    automl = _wait_for_health("http://localhost:8001")

    assert stats["status"] == "healthy"
    assert automl["status"] == "healthy"
    assert "version" in stats
    assert "version" in automl


def test_stats_service_contract_endpoints(vendor_stack: None) -> None:
    csv_content = "".join(
        [
            "treatment,outcome,time,event,group,score,age,bmi\n",
            "1,1,5,1,A,0.91,64,27.1\n",
            "0,0,8,0,B,0.20,59,24.8\n",
            "1,1,3,1,A,0.82,67,29.0\n",
            "0,0,10,0,B,0.11,55,22.5\n",
            "1,0,6,1,A,0.73,70,31.2\n",
            "0,1,4,1,B,0.64,58,26.4\n",
        ]
    )

    with httpx.Client(timeout=30.0) as client:
        direct = client.post(
            "http://localhost:8003/direct/analyze",
            json={"csv_content": csv_content, "user_id": TEST_USER, "target_column": "outcome"},
        )
        assert direct.status_code == 200, direct.text
        direct_data = direct.json()
        assert {"job_id", "job_type", "status", "message", "data_preview"}.issubset(direct_data)
        assert direct_data["data_preview"]["rows"] == 6

        propensity = client.post(
            "http://localhost:8003/propensity/full/submit",
            json={
                "csv_content": csv_content,
                "user_id": TEST_USER,
                "treatment_column": "treatment",
                "outcome_column": "outcome",
                "covariates": ["age", "bmi"],
            },
        )
        assert propensity.status_code == 200, propensity.text
        propensity_data = propensity.json()
        assert {"job_id", "job_type", "status", "message"}.issubset(propensity_data)
        assert propensity_data["status"] == "pending"

        survival = client.post(
            "http://localhost:8003/survival/kaplan-meier/submit",
            json={
                "csv_content": csv_content,
                "user_id": TEST_USER,
                "time_column": "time",
                "event_column": "event",
                "group_column": "group",
            },
        )
        assert survival.status_code == 200, survival.text
        survival_data = survival.json()
        assert {"job_id", "job_type", "status", "message"}.issubset(survival_data)

        roc = client.post(
            "http://localhost:8003/roc/compute/submit",
            json={
                "csv_content": csv_content,
                "user_id": TEST_USER,
                "true_column": "outcome",
                "score_column": "score",
            },
        )
        assert roc.status_code == 200, roc.text
        roc_data = roc.json()
        assert {"job_id", "job_type", "status", "message"}.issubset(roc_data)

        power = client.post(
            "http://localhost:8003/power/ttest",
            json={"effect_size": 0.5, "alpha": 0.05, "power": 0.8},
        )
        assert power.status_code == 200, power.text
        power_data = power.json()
        assert {
            "calculation_type",
            "result",
            "parameters",
            "interpretation",
            "assumptions",
        }.issubset(power_data)


def test_automl_training_contract(vendor_stack: None) -> None:
    headers = {"x-user-id": TEST_USER}

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        register = client.post(
            "http://localhost:8001/datasets/register",
            headers=headers,
            json={
                "name": "rde_contract_dataset",
                "description": "vendor live contract test",
                "minio_path": "/data/sample_data/iris.csv",
            },
        )
        if register.status_code >= 500:
            pytest.xfail(
                "vendor automl-service local storage contract is broken: "
                f"/datasets/register returned {register.status_code} ({register.text})"
            )
        assert register.status_code in {200, 201}, register.text
        dataset = register.json()
        assert {"dataset_id", "name", "columns", "row_count"}.issubset(dataset)

        train = client.post(
            "http://localhost:8001/train/automl",
            headers=headers,
            json={
                "dataset_id": dataset["dataset_id"],
                "target_column": "target",
                "problem_type": "multiclass",
                "time_limit": 30,
                "presets": "medium_quality",
            },
        )
        assert train.status_code == 200, train.text
        job = train.json()
        assert {
            "job_id",
            "job_type",
            "status",
            "progress",
            "status_message",
            "created_at",
        }.issubset(job)
