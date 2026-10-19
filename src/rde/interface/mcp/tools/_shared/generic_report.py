"""Full report projections of verified saved generic studies and branches.

No dataset loading, fitting, promotion or implicit selection of a latest result.
The figure publication contract remains separate from numerical report evidence.
"""

import hashlib
import json
import re

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.clinical.advanced_report import markdown
from rde.infrastructure.visualization.advanced_publication import METHODS


def primary_reports_markdown(project, store):
    from .advanced_study import advanced_study_source

    sections = []
    phase = PipelinePhase.EXECUTE_EXPLORATION
    for name in sorted(store.list_phase_artifacts(phase)):
        if not re.fullmatch(r"advanced_study_[a-f0-9]{16}\.json", name):
            continue
        path = store.get_path(phase, name)
        _, record = advanced_study_source(
            project, name, hashlib.sha256(path.read_bytes()).hexdigest()
        )
        text = markdown(
            record["analysis_result"],
            source_binding=record["input_evidence"]["source_binding"],
            artifact_path=name,
        )
        if text is None:
            raise ValueError("Verified advanced study has no supported report renderer.")
        sections.append(text)
    return "\n\n".join(sections)


def branch_reports_markdown(project, store):
    from .branch_publication import branch_report_source

    phase = PipelinePhase.EXECUTE_EXPLORATION
    events = store.load(phase, "branch_experiment_results.jsonl") or []
    root = project.output_dir.resolve()
    sections = []
    for event in events:
        if event.get("status") != "completed":
            continue
        path = (root / event["artifact"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Branch report ledger points outside its saved project.")
        wrapper = json.loads(path.read_text(encoding="utf8"))
        contract = wrapper.get("task", {}).get("analysis_contract", {})
        if contract.get("tool") != "run_advanced_analysis":
            continue
        if contract.get("analysis_type") not in METHODS:
            continue
        source, record = branch_report_source(
            project,
            event["branch_id"],
            event["experiment_id"],
            wrapper["contract_execution"]["artifact_sha256"],
        )
        text = markdown(
            record["analysis_result"],
            exploratory=True,
            source_binding=record["input_evidence"]["source_binding"],
            artifact_path=str(source.relative_to(root)),
        )
        if text is None:
            raise ValueError("Verified advanced branch has no supported report renderer.")
        sections.append(
            f"## 探索分支 {record['branch_id']} · {record['experiment_id']}\n\n"
            f"執行：`{record['run_id']}`。本結果不取代主要分析；"
            "以此分支自己的納排、估計與不確定性解讀。\n\n" + text
        )
    return "\n\n".join(sections)
