from io import BytesIO
from zipfile import ZipFile

import pytest

from scripts.audit_release_artifacts import check_members, check_source


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "/absolute",
        "C:/data",
        "a\\secret",
        "extension/data/patient.csv",
        "extension/.venv/bin/python",
        "rde/__pycache__/a.pyc",
        "rde/a.pyc",
    ],
)
def test_release_rejects_unsafe_or_private_members(name):
    with pytest.raises(AssertionError):
        check_members([name])


def test_release_allows_source_and_diagrams():
    check_members(["rde/interface/mcp/server.py", "extension/resources/evidence-chain.svg"])


def test_release_detects_stale_packaged_source(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"new source")
    with ZipFile(BytesIO(), "w") as archive:
        archive.writestr("source.py", b"old source")
        with pytest.raises(AssertionError, match="Stale packaged"):
            check_source(archive, "source.py", source)
