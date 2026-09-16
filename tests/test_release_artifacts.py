from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
import re
import tomllib

import pytest

from scripts.audit_release_artifacts import check_members, check_source

ROOT = Path(__file__).resolve().parents[1]


def test_marketplace_previews_are_not_svg_and_canonical_assets_match():
    readme = (ROOT / "vscode-extension/README.md").read_text(encoding="utf-8")
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
    assert images and all(not image.endswith(".svg") for image in images)
    manifest = (ROOT / "vscode-extension/scripts/asset-manifest.mjs").read_text(encoding="utf-8")
    pairs = re.findall(r"\['([^']+)', '([^']+)'\]", manifest)
    assert len(pairs) >= 7
    for source, target in pairs:
        assert (ROOT / source).read_bytes() == (ROOT / "vscode-extension" / target).read_bytes()


def test_source_distribution_has_explicit_private_data_safe_allowlist():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert set(included) == {
        "/src/rde",
        "/pyproject.toml",
        "/README.md",
        "/README.zh-TW.md",
        "/LICENSE",
    }


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
