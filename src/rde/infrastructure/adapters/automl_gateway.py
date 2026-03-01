"""AutomlGateway — Adapter implementing AutomlGatewayPort.

Anti-Corruption Layer (ACL) for the automl-stat-mcp submodule.
Translates between RDE's domain model and automl-stat-mcp's API.
"""

from __future__ import annotations

from typing import Any

import httpx

from rde.domain.ports import AutomlGatewayPort


class AutomlGateway(AutomlGatewayPort):
    """Gateway to automl-stat-mcp Docker service.

    Communicates via HTTP to the automl-mcp-server running
    at localhost:8002. This adapter translates RDE domain
    concepts into automl-stat-mcp's API format.
    """

    def __init__(self, base_url: str = "http://localhost:8002") -> None:
        self._base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=120)

    def create_project(self, name: str, data_path: str) -> str:
        """Create an automl project."""
        response = self._client.post(
            "/api/projects",
            json={"name": name, "data_path": data_path},
        )
        response.raise_for_status()
        return response.json()["project_id"]

    def upload_data(self, project_id: str, data: Any) -> None:
        """Upload data to automl engine."""
        # Serialize DataFrame to CSV for upload
        import io

        buffer = io.StringIO()
        data.to_csv(buffer, index=False)

        response = self._client.post(
            f"/api/projects/{project_id}/data",
            files={"file": ("data.csv", buffer.getvalue(), "text/csv")},
        )
        response.raise_for_status()

    def run_analysis(self, project_id: str, config: dict[str, Any]) -> dict[str, Any]:
        """Run analysis in automl engine."""
        response = self._client.post(
            f"/api/projects/{project_id}/analyze",
            json=config,
        )
        response.raise_for_status()
        return response.json()

    def is_available(self) -> bool:
        """Check if automl-stat-mcp service is running."""
        try:
            response = self._client.get("/health")
            return response.status_code == 200
        except httpx.ConnectError:
            return False

    def close(self) -> None:
        self._client.close()
