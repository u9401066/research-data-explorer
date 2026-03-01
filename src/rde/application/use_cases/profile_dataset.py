"""ProfileDatasetUseCase — Pipeline Step 2.

Runs profiling engine on loaded data and classifies variables.
"""

from __future__ import annotations

from typing import Any

from rde.application.dto import DatasetSummary, VariableSummary
from rde.domain.models.dataset import Dataset
from rde.domain.models.profile import DataProfile
from rde.domain.ports import ProfilerPort
from rde.domain.services.variable_classifier import VariableClassifier


class ProfileDatasetUseCase:
    """Profile a loaded dataset and classify its variables."""

    def __init__(self, profiler: ProfilerPort) -> None:
        self._profiler = profiler
        self._classifier = VariableClassifier()

    def execute(self, dataset: Dataset, raw_data: Any) -> tuple[DataProfile, DatasetSummary]:
        """Run profiling and return profile + summary DTO."""
        profile = self._profiler.profile(raw_data, dataset.id)
        dataset.mark_profiled()

        # Classify variables from profiling results
        for vp in profile.variable_profiles:
            var = self._classifier.classify(
                name=vp.variable_name,
                dtype=vp.dtype,
                n_unique=vp.unique_count,
                n_total=vp.count,
            )
            var.n_missing = vp.missing_count
            # Update dataset's variable list
            for i, dv in enumerate(dataset.variables):
                if dv.name == var.name:
                    dataset.variables[i] = var
                    break

        summary = DatasetSummary(
            dataset_id=dataset.id,
            file_name=dataset.metadata.file_path.name if dataset.metadata else "",
            row_count=dataset.row_count,
            column_count=len(dataset.variables),
            status=dataset.status.value,
            variables=[
                VariableSummary(
                    name=v.name,
                    dtype=v.dtype,
                    variable_type=v.variable_type.value,
                    missing_rate=v.missing_rate,
                    n_unique=v.n_unique,
                    is_pii_suspect=v.is_pii_suspect,
                )
                for v in dataset.variables
            ],
        )

        return profile, summary
