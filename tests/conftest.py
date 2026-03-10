import pytest


@pytest.fixture(autouse=True)
def reset_session_registry():
    import rde.application.session as session_module

    session_module._session = None
    yield
    session_module._session = None