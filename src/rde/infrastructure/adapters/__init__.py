"""Infrastructure Adapters."""

from typing import Any

from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.adapters.ydata_profiler import YDataProfiler
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.adapters.cleaning_executor import CleaningExecutor
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.adapters.docx_exporter import DocxExporter
from rde.infrastructure.adapters.analysis_delegator import (
    AnalysisDelegator,
    get_analysis_delegator,
)
from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer

try:
    from rde.infrastructure.adapters.automl_gateway import AutomlGateway as _AutomlGateway
except ImportError:  # pragma: no cover - optional dependency in lightweight runtimes
    AutomlGateway: Any = None
else:
    AutomlGateway = _AutomlGateway

__all__ = [
    "PandasLoader",
    "YDataProfiler",
    "AutomlGateway",
    "ScipyStatisticalEngine",
    "CleaningExecutor",
    "MarkdownReportRenderer",
    "DocxExporter",
    "MatplotlibVisualizer",
    "AnalysisDelegator",
    "get_analysis_delegator",
]
