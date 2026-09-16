import pytest


@pytest.fixture(autouse=True)
def reset_session_registry(monkeypatch, tmp_path):
    import rde.application.session as session_module

    session_module._session = None
    monkeypatch.setenv("RDE_WORKSPACE", str(tmp_path / "workspace"))
    yield
    session_module._session = None
