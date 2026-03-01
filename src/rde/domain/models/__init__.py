"""Domain Models — Entities, Value Objects, Aggregate Roots."""

from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableType
from rde.domain.models.profile import DataProfile, VariableProfile
from rde.domain.models.quality import QualityReport, QualityIssue, Severity
from rde.domain.models.analysis import AnalysisResult, StatisticalTest
from rde.domain.models.report import EDAReport, ReportSection
from rde.domain.models.cleaning import CleaningPlan, CleaningAction
from rde.domain.models.project import Project, ProjectStatus

__all__ = [
    "Dataset", "Variable", "VariableType",
    "DataProfile", "VariableProfile",
    "QualityReport", "QualityIssue", "Severity",
    "AnalysisResult", "StatisticalTest",
    "EDAReport", "ReportSection",
    "CleaningPlan", "CleaningAction",
    "Project", "ProjectStatus",
]
