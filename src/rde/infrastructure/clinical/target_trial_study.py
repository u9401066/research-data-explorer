"""Native baseline target-trial wrapper; the weighting estimator is unchanged."""

from dataclasses import dataclass
import json
from pathlib import Path

from rde.infrastructure.preparation import sources, workflow
from .survival import digest
from .target_trial_contract import TargetTrialProtocol
from .weighting_contract import WeightingSpec


@dataclass(frozen=True)
class TargetTrialSpec:
    weighting: WeightingSpec
    protocol: TargetTrialProtocol
    family: str = "target_trial"

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) != {"family", "weighting", "protocol"}:
            raise ValueError(
                "Target trial requires exactly family, weighting and the full typed protocol."
            )
        spec = cls(
            WeightingSpec.parse(options["weighting"]),
            TargetTrialProtocol.parse(options["protocol"]),
            options["family"],
        )
        spec.validate()
        return spec

    def validate(self):
        if self.family != "target_trial":
            raise ValueError(
                "Use the distinct target_trial family; ordinary weighting cannot ignore a protocol."
            )
        self.weighting.validate()
        if self.protocol.analysis.weighting_spec_sha256 != digest(self.weighting.to_dict()):
            raise ValueError(
                "TTE_WEIGHTING_SPEC: protocol must bind the exact weighting specification."
            )

    def to_dict(self):
        return {
            "family": self.family,
            "weighting": self.weighting.to_dict(),
            "protocol": self.protocol.to_dict(),
        }

    def variables(self):
        return self.weighting.variables()

    @property
    def confidence_level(self):
        return self.weighting.confidence_level


def persist_source_check(check, directory: Path, root: Path):
    """Immutable, content-addressed full source ledger, separately downloadable."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"target_trial_source_{check['receipt_sha256']}.json"
    workflow.write_bytes(path, (sources.canonical(check) + "\n").encode())
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sources.file_hash(path),
        "bytes": path.stat().st_size,
    }


def target_trial_preflight(spec, check, artifact):
    base = check["weighting_preflight"]
    return {
        **base,
        "schema": "target-trial-preflight-v1",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "source_check": {
            "schema": check["schema"],
            "receipt_sha256": check["receipt_sha256"],
            "protocol_sha256": check["protocol_sha256"],
            "binding": check["binding"],
            "clinical_validation": check["clinical_validation"],
            "population": {
                key: value
                for key, value in check["population"].items()
                if not key.endswith("_unit_ids")
            },
            "artifact": artifact,
        },
        "scope": "Complete source-backed baseline protocol and exact eligible population; no fitted effect or verified causal identification.",
    }


def run_target_trial(dataframe, spec, check):
    """Only the native locked caller can provide a freshly source-verified check."""
    from .weighting import run_weighting

    spec.validate()
    if (
        check.get("protocol") != spec.protocol.to_dict()
        or check.get("weighting_spec") != spec.weighting.to_dict()
    ):
        raise ValueError("TTE_SOURCE_SPEC: source receipt and locked study differ.")
    numerical = run_weighting(dataframe, spec.weighting)
    if numerical["case_ledger"] != check["weighting_preflight"]["case_ledger"]:
        raise ValueError(
            "TTE_ANALYSIS_POPULATION: weighting changed the verified eligible population."
        )
    result = {
        "schema": "target-trial-study-v1",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": numerical["dataframe_sha256"],
        "design_sha256": numerical["design_sha256"],
        "n": numerical["n"],
        "case_ledger": numerical["case_ledger"],
        "source_check": check,
        "source_check_sha256": check["receipt_sha256"],
        "weighting_result": numerical,
        "weighting_receipt_sha256": numerical["receipt_sha256"],
        "scope": "Baseline point-treatment emulation with complete fixed follow-up, unchanged prespecified weighting, and unverified causal-identification assumptions.",
    }
    result["receipt_sha256"] = digest(result)
    if not verify_target_trial_result(result):
        raise ValueError("TTE_RESULT_INTEGRITY: source and numerical evidence do not agree.")
    return result


def verify_target_trial_result(result):
    """Check frozen protocol/source/numerical links without reading live sources or fitting."""
    try:
        spec = TargetTrialSpec.parse(result["spec"])
        check, numerical = result["source_check"], result["weighting_result"]
        ledger, population = result["case_ledger"], check["population"]
        included = [row["unit_id"] for row in check["rows"] if row["included"]]
        excluded = [row["unit_id"] for row in check["rows"] if not row["included"]]
        return all(
            [
                result["schema"] == "target-trial-study-v1",
                result["status"] == "completed",
                all(
                    digest({k: v for k, v in item.items() if k != "receipt_sha256"})
                    == item["receipt_sha256"]
                    for item in [result, check, numerical]
                ),
                result["spec_sha256"] == digest(spec.to_dict()),
                check["status"] == "passed",
                check["protocol"] == spec.protocol.to_dict(),
                check["protocol_sha256"] == digest(spec.protocol.to_dict()),
                check["binding"] == spec.protocol.binding.model_dump(),
                numerical["spec"] == check["weighting_spec"] == spec.weighting.to_dict(),
                numerical["spec_sha256"]
                == check["weighting_spec_sha256"]
                == digest(spec.weighting.to_dict()),
                result["source_check_sha256"] == check["receipt_sha256"],
                result["weighting_receipt_sha256"] == numerical["receipt_sha256"],
                result["dataframe_sha256"]
                == numerical["dataframe_sha256"]
                == check["weighting_preflight"]["dataframe_sha256"],
                result["design_sha256"]
                == numerical["design_sha256"]
                == check["weighting_preflight"]["design_sha256"],
                result["n"]
                == numerical["n"]
                == population["analysis_n"]
                == population["included"]
                == len(included),
                ledger == numerical["case_ledger"] == check["weighting_preflight"]["case_ledger"],
                ledger["complete_data_rows"] == list(range(1, result["n"] + 1)),
                not ledger["missing_excluded_data_rows"]
                and not ledger["filter_excluded_data_rows"],
                population["root_records"] == len(check["rows"]) == len(set(included + excluded)),
                population["included_unit_ids"] == included,
                population["excluded_unit_ids"] == excluded,
                population["excluded_by_baseline_eligibility"] == len(excluded),
                population["included_unit_set_sha256"] == digest(sorted(included)),
            ]
        )
    except (KeyError, ValueError, TypeError):
        return False


def verify_target_trial_artifacts(record, root):
    try:
        result = record["result"]
        if not verify_target_trial_result(result):
            return False
        item = record["target_trial_source_artifact"]
        return (
            verify_source_artifact(item, root, result["source_check"])
            and sum(
                a["path"] == item["path"] and a["sha256"] == item["sha256"]
                for a in record["artifacts"]
            )
            == 1
        )
    except (OSError, KeyError, TypeError, ValueError):
        return False


def verify_source_artifact(item, root, check):
    try:
        original = root / item["path"]
        path = original.resolve()
        return (
            path.is_relative_to(root.resolve())
            and not original.is_symlink()
            and path.is_file()
            and path.name == f"target_trial_source_{check['receipt_sha256']}.json"
            and sources.file_hash(path) == item["sha256"]
            and path.stat().st_size == item["bytes"]
            and json.loads(path.read_text()) == check
        )
    except (OSError, KeyError, TypeError, ValueError):
        return False
