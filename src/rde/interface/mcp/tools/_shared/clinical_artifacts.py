"""Immutable complete presentation inventory over a frozen clinical result."""

import hashlib
from pathlib import Path, PurePosixPath

from rde.interface.mcp.research_plans import read_sealed, write_once

CONTRACT = "clinical-artifact-inventory-v1"
ROLES = {"report", "tables", "figures", "derived", "source"}


def inventory_path(record, root):
    run = record["run_id"]
    if not isinstance(run, str) or not run.isalnum():
        raise ValueError("Invalid clinical run identity")
    return root / "artifacts/phase_08_execute_exploration" / f"clinical_{run}_inventory.json"


def _relative(path, root):
    raw = Path(path)
    absolute = raw if raw.is_absolute() else root / raw
    if any(p.is_symlink() for p in [absolute, *absolute.parents]):
        raise ValueError("Clinical artifacts cannot use symlinks")
    resolved = absolute.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Clinical artifact is outside the project")
    return resolved.relative_to(root.resolve()).as_posix()


def _payload(record, root):
    if record.get("artifact_contract") != CONTRACT:
        raise ValueError(
            "LEGACY_CLINICAL_INVENTORY: explicit new study required; no retroactive seal"
        )
    manifest = inventory_path(record, root).relative_to(root).as_posix()
    files = [a for a in record["artifacts"] if a["path"] != manifest]
    paths = [a["path"] for a in files]
    if not files or len(set(paths)) != len(paths):
        raise ValueError("Clinical inventory must have unique complete file references")
    if any(PurePosixPath(p).is_absolute() or p != _relative(p, root) or "\\" in p for p in paths):
        raise ValueError("Clinical inventory paths must be canonical project-relative paths")
    roles = record["artifact_roles"]
    if set(roles) != ROLES or any(not isinstance(v, list) for v in roles.values()):
        raise ValueError("Clinical artifact roles must be complete")
    assigned = [p for values in roles.values() for p in values]
    if sorted(assigned) != sorted(paths):
        raise ValueError("Each clinical file must have exactly one declared role")
    prefix = f"clinical_{record['run_id']}"
    family = record["result"]["spec"]["family"]
    protocol_name = prefix + "_target_trial_protocol.json"
    if (
        len(roles["report"]) != 1
        or Path(roles["report"][0]).name != prefix + ".md"
        or not roles["tables"]
        or not any(p.endswith(".csv") for p in roles["tables"])
        or any(
            not Path(p).name.startswith(prefix + "_")
            or not (
                p.endswith(".csv") or (family == "target_trial" and Path(p).name == protocol_name)
            )
            for p in roles["tables"]
        )
    ):
        raise ValueError("Clinical report and result tables are required")
    figures = record["figures"]
    plotted = [
        _relative(path, root)
        for figure in figures
        for path in figure["publication"]["files"].values()
    ]
    if not figures or sorted(plotted) != sorted(roles["figures"]):
        raise ValueError("Clinical publication inventory is incomplete")
    if any(
        set(figure["publication"]["files"]) != {"png", "svg", "pdf", "tiff", "caption", "data"}
        for figure in figures
    ):
        raise ValueError("Every clinical figure requires its complete publication bundle")
    derived = [a["path"] for a in record.get("derived_artifacts", [])]
    source = record.get("target_trial_source_artifact")
    if sorted(roles["derived"]) != sorted(derived) or bool(derived) != (family == "imputation"):
        raise ValueError("Clinical derived-data inventory differs")
    if roles["source"] != ([source["path"]] if source else []) or bool(source) != (
        family == "target_trial"
    ):
        raise ValueError("Clinical source evidence inventory differs")
    return {
        "schema": CONTRACT,
        "dataset_id": record["dataset_id"],
        "run_id": record["run_id"],
        "source": record["source"],
        "spec_sha256": record["result"]["spec_sha256"],
        "numerical_receipt_sha256": record["result"]["receipt_sha256"],
        "files": files,
        "roles": roles,
        "figures": figures,
        "derived_artifacts": record.get("derived_artifacts", []),
        "target_trial_source_artifact": source,
    }


def seal_inventory(record, root):
    path = inventory_path(record, root)
    write_once(path, _payload(record, root))
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def verify_inventory(record, root):
    try:
        path = inventory_path(record, root)
        ref = record["artifact_manifest"]
        if (
            ref["path"] != path.relative_to(root).as_posix()
            or _relative(ref["path"], root) != ref["path"]
        ):
            return False
        matching = [a for a in record["artifacts"] if a["path"] == ref["path"]]
        if matching != [ref]:
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
            return False
        return read_sealed(path)["payload"] == _payload(record, root)
    except (KeyError, TypeError, ValueError, OSError):
        return False
