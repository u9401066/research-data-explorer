"""Verify versioned wheel/VSIX contents against the reviewed source tree."""

import json
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".venv", "venv", "__pycache__", "node_modules", "data", ".git"}


def check_members(names: list[str]) -> None:
    """Reject accidental data/caches and unsafe archive member names."""
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts, name
        assert "\\" not in name and ":" not in name, name
        assert not FORBIDDEN.intersection(path.parts), name
        assert path.suffix not in {".pyc", ".pyo"}, name


def check_source(archive: ZipFile, member: str, source: Path) -> None:
    assert archive.read(member) == source.read_bytes(), f"Stale packaged source: {member}"


def audit(root: Path = ROOT) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    ext = root / "vscode-extension"
    package = json.loads((ext / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ext / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == version
    wheel = root / "dist" / f"research_data_explorer-{version}-py3-none-any.whl"
    sdist = root / "dist" / f"research_data_explorer-{version}.tar.gz"
    vsix = ext / f"research-data-explorer-{version}.vsix"
    with ZipFile(wheel) as built:
        check_members(built.namelist())
        for source in (root / "src/rde").rglob("*.py"):
            check_source(built, source.relative_to(root / "src").as_posix(), source)
        metadata = built.read(f"research_data_explorer-{version}.dist-info/METADATA").decode()
        assert f"Version: {version}\n" in metadata
    with tarfile.open(sdist) as built:
        check_members(built.getnames())
    with ZipFile(vsix) as built:
        check_members(built.namelist())
        check_source(built, "extension/package.json", ext / "package.json")
        check_source(built, "extension/bundled/tool/pyproject.toml", root / "pyproject.toml")
        for source in (root / "src/rde").rglob("*.py"):
            member = "extension/bundled/tool/src/" + source.relative_to(root / "src").as_posix()
            check_source(built, member, source)
        for name in (
            "evidence-chain.svg",
            "autoresearch.svg",
            "evidence-chain.png",
            "autoresearch.png",
        ):
            check_source(built, f"extension/resources/{name}", root / "docs/assets" / name)
        check_source(built, "extension/agents/eda.agent.md", root / ".github/agents/eda.agent.md")
    return {"version": version, "wheel": str(wheel), "sdist": str(sdist), "vsix": str(vsix)}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
