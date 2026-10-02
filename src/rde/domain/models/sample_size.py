"""Prospective, source-supported designs; no patient data or observed-power mode."""

from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from math import gcd, isfinite
import re


def text(value, name, *, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} requires nonempty text (at most {limit} characters).")


def number(value, name, lower, upper, *, closed=False):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name} requires a finite number, not a boolean or string.")
    if not (lower <= value <= upper if closed else lower < value < upper):
        raise ValueError(f"{name} is outside the supported range ({lower}, {upper}).")


def identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", value):
        raise ValueError(f"{name} requires a lowercase identifier, at most 40 characters.")


@dataclass(frozen=True)
class SampleSizeSpec:
    design: str
    population: str
    endpoint: str
    time_horizon: str
    outcome_unit: str
    contrast: str
    group_labels: list[str]
    independent_units: bool
    normal_model: str
    alpha: float
    target_power: float
    allocation: list[int] | None
    max_evaluable: int
    sources: list[dict]
    design_source_ids: list[str]
    primary_scenario_id: str
    scenarios: list[dict]
    family: str = "sample_size"
    purpose: str = "prospective_superiority"
    alternative: str = "two-sided"

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown sample-size settings; use the prospective design contract.")
        try:
            spec = cls(**deepcopy(options))
        except TypeError as error:
            raise ValueError(f"Missing sample-size assumptions: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def validate(self):
        if (self.family, self.purpose, self.alternative) != (
            "sample_size",
            "prospective_superiority",
            "two-sided",
        ):
            raise ValueError(
                "Only prospective two-sided superiority with a zero null difference is supported."
            )
        models = {
            "independent_means": "common_normal_sd",
            "paired_means": "normal_differences",
            "independent_proportions": "not_applicable",
        }
        if self.design not in models or self.normal_model != models[self.design]:
            raise ValueError(
                "Specify independent_means/common_normal_sd, paired_means/normal_differences or independent_proportions/not_applicable."
            )
        if self.independent_units is not True:
            raise ValueError(
                "Confirm independent subjects (or independent pairs); clustered designs need another contract."
            )
        for name in ("population", "endpoint", "time_horizon", "outcome_unit", "contrast"):
            text(getattr(self, name), name)
        if self.design == "independent_proportions" and self.outcome_unit != "probability":
            raise ValueError(
                "Proportion planning uses outcome_unit=probability on the 0..1 scale; percentages must be converted explicitly."
            )
        if not isinstance(self.group_labels, list) or len(self.group_labels) != 2:
            raise ValueError(
                "Specify exactly two group or paired-measurement labels, in contrast order 1 minus 2."
            )
        for label in self.group_labels:
            text(label, "group label", limit=100)
        if self.group_labels[0].strip() == self.group_labels[1].strip():
            raise ValueError("Group or paired-measurement labels must be distinct.")
        number(self.alpha, "alpha", 0.0001, 0.2, closed=True)
        number(self.target_power, "target power", 0.5, 0.9999, closed=True)
        if type(self.max_evaluable) is not int or not 4 <= self.max_evaluable <= 1_000_000:
            raise ValueError(
                "max_evaluable must be an integer from 4 to 1,000,000 (complete pairs for paired designs)."
            )
        if self.design == "paired_means":
            if self.allocation is not None:
                raise ValueError("Paired designs use complete pairs and require allocation=null.")
        elif (
            not isinstance(self.allocation, list)
            or len(self.allocation) != 2
            or any(type(n) is not int or not 1 <= n <= 20 for n in self.allocation)
            or gcd(*self.allocation) != 1
        ):
            raise ValueError(
                "Independent designs require a reduced integer allocation [n1 units, n2 units], each 1..20."
            )
        if not isinstance(self.sources, list) or not 1 <= len(self.sources) <= 20:
            raise ValueError("Record 1..20 explicit assumption sources.")
        ids = set()
        for source in self.sources:
            if not isinstance(source, dict) or set(source) != {
                "id",
                "kind",
                "citation",
                "locator",
                "justification",
            }:
                raise ValueError("Each source needs id, kind, citation, locator and justification.")
            identifier(source["id"], "source id")
            if source["id"] in ids:
                raise ValueError("Source IDs must be unique.")
            ids.add(source["id"])
            if source["kind"] not in {
                "published",
                "prior_study",
                "clinical_judgment",
                "engineering_fixture",
            }:
                raise ValueError("Unknown assumption source kind.")
            for key in ("citation", "locator", "justification"):
                text(source[key], f"source {key}")

        def references(value, name):
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(v, str) or v not in ids for v in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError(f"{name} must refer to distinct recorded assumption sources.")

        references(self.design_source_ids, "Design rationale")
        if not isinstance(self.scenarios, list) or not 1 <= len(self.scenarios) <= 5:
            raise ValueError("Prespecify 1..5 scenarios, including one primary scenario.")
        scenario_ids, labels = set(), set()
        for scenario in self.scenarios:
            keys = {
                "id",
                "label",
                "loss_rate",
                "loss_source_ids",
                "effect_source_ids",
                "nuisance_source_ids",
            }
            keys |= (
                {"probabilities"}
                if self.design == "independent_proportions"
                else {"difference", "sd"}
            )
            if not isinstance(scenario, dict) or set(scenario) != keys:
                raise ValueError(
                    "Scenario fields must match the selected design, including effect, nuisance and loss sources."
                )
            identifier(scenario["id"], "scenario id")
            text(scenario["label"], "English scenario label", limit=60)
            if not scenario["label"].isascii() or not scenario["label"].isprintable():
                raise ValueError(
                    "Scenario labels must use printable English text for publication figures."
                )
            if scenario["id"] in scenario_ids or scenario["label"].strip() in labels:
                raise ValueError("Scenario IDs and labels must be distinct.")
            scenario_ids.add(scenario["id"])
            labels.add(scenario["label"].strip())
            for role in ("effect", "nuisance", "loss"):
                references(scenario[f"{role}_source_ids"], f"{role} assumptions")
            number(
                scenario["loss_rate"],
                "Common missing-outcome/incomplete-pair rate",
                0,
                0.8,
                closed=True,
            )
            if self.design == "independent_proportions":
                probabilities = scenario["probabilities"]
                if not isinstance(probabilities, list) or len(probabilities) != 2:
                    raise ValueError("Specify the two alternative probabilities [p1, p2].")
                for p in probabilities:
                    number(p, "probability", 0, 1)
                if probabilities[0] == probabilities[1]:
                    raise ValueError(
                        "Alternative probabilities must differ from the zero-difference null."
                    )
            else:
                number(
                    scenario["difference"], "Clinically important signed difference", -1e12, 1e12
                )
                number(scenario["sd"], "Common SD or SD of paired differences", 0, 1e12)
                if scenario["difference"] == 0:
                    raise ValueError("A nonzero clinically important difference is required.")
                number(
                    abs(scenario["difference"] / scenario["sd"]),
                    "Standardized planning difference",
                    1e-8,
                    1000,
                )
        if self.primary_scenario_id not in scenario_ids:
            raise ValueError(
                "Choose one of the prespecified scenarios as primary before calculation."
            )
