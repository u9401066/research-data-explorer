"""Read-only, release-bound preparation evidence for research reports.

Rendered prose is a projection of retained receipts, not a new statistical result
or a claim that automated structural checks establish clinical validity.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from rde.infrastructure.preparation.portable import verify_bundle_folder
from rde.infrastructure.preparation.workflow import read_sealed


def preparation_evidence(project, intake):
    binding = (intake or {}).get("preparation")
    if binding is None:
        return None
    try:
        sha = binding["bundle_sha256"]
        if binding["schema"] != "rde-prepared-intake-v1" or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("invalid prepared intake identity")
        root = Path(project.output_dir).resolve()
        folder = root / "artifacts/data_preparation/imports" / sha
        if Path(binding["folder"]).resolve() != folder or not folder.resolve().is_relative_to(root):
            raise ValueError("prepared evidence is outside this analysis project")
        plan, release = verify_bundle_folder(folder, binding["release_sha256"])
        for key in (
            "project_id",
            "dataset",
            "unit",
            "population",
            "column_roles",
            "clinical_validation",
        ):
            if binding.get(key) != release.get(key):
                raise ValueError(f"prepared intake {key} differs from its release")
        if binding["preparation_id"] != plan["preparation_id"]:
            raise ValueError("prepared intake references a different preparation")
        for key in ("sha256", "bytes"):
            if intake.get("source", {}).get(key) != release["dataset"][key]:
                raise ValueError("analysis intake differs from the released dataset")
        if intake.get("row_count") != release["population"]["rows"]:
            raise ValueError("analysis intake denominator differs from the release")
        # These are hash-verified files from the closure checked above.
        specification = json.loads((folder / "specification.json").read_text())
        validation = json.loads((folder / "validation.json").read_text())
        if specification != plan["specification"] or validation != plan["summary"]:
            raise ValueError("saved preparation definitions/denominators disagree")
        return dict(
            plan=plan,
            release=release,
            approval=read_sealed(folder / "approval.json"),
            bundle_sha256=sha,
        )
    except (KeyError, TypeError, OSError, ValueError) as error:
        raise ValueError(f"PREPARATION_REPORT_EVIDENCE_INVALID: {error}") from error


def _text(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")


def preparation_abstract(evidence):
    release = evidence["release"]
    unit, population = release["unit"], release["population"]
    return (
        f"本次分析使用已發布、可追溯的多表準備資料集，共 {population['rows']} 列、"
        f"{population['units']} 個分析單位、{population['subjects']} 個受試者識別。"
        f"宣告分析單位為 {_text(unit['kind'])}，單位鍵 {_text(unit['keys'])}，"
        f"受試者鍵 {_text(unit['subject_keys'])}；index 欄位為 {_text(unit.get('index_column') or '未宣告')}。"
        "這些是準備收據的操作定義與分母，不代表受試者獨立性或臨床有效性已獲證實。"
    )


def preparation_markdown(evidence):
    plan, release, approval = (evidence[k] for k in ("plan", "release", "approval"))
    spec, summary = plan["specification"], plan["summary"]
    lines = [
        "### 已發布資料準備的方法與來源",
        "",
        preparation_abstract(evidence),
        "",
        "以下為已保存、雜湊核對的準備規格與收據；描述來源與執行，不補猜臨床事實。",
        f"- 準備版本：{_text(plan['preparation_id'])}；來源準備專案：{_text(plan['project_id'])}。",
        f"- 核准種類：{_text(approval.get('review', {}).get('kind', '未記錄'))}；clinical_validation：{_text(release['clinical_validation'])}。",
        "- 自動化核對只證實來源、規則、數值與追溯的一致性；not_performed 表示未進行臨床驗證，不能解讀為人工臨床核准。",
        "",
        "#### 已宣告的研究定義",
        "",
    ]
    labels = dict(unit="研究族群與分析單位", linkage="關聯", time="時間", missingness="缺失")
    lines.extend(f"- {labels.get(k, k)}：{_text(v)}" for k, v in spec["definitions"].items())
    lines.extend(
        [
            f"- 根表：{_text(spec['unit']['source_id'])}；鍵正規化：{_text(spec['unit']['key_normalization'])}；時區：{_text(spec['unit'].get('timezone'))}。",
            f"- 明訂族群篩選：{_text(spec.get('cohort', []))}；明訂來源排除：{_text(spec.get('excluded_rows', []))}。",
            "",
            "#### 來源檔案與身份",
            "",
            "| 來源 | 檔案 | 位元組 | SHA-256 |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for item in plan["source_snapshots"]:
        source = item["source"]
        lines.append(
            f"| {_text(source['id'])} | {_text(Path(source['path']).name)} | {source['bytes']} | {source['sha256']} |"
        )
    lines.extend(["", "#### 關聯、時間窗與聚合規則", ""])
    for relation in spec["relations"]:
        lines.extend(
            [
                f"- {_text(relation['id'])}：{_text(relation['kind'])}；來源 {_text(relation['source_id'])}；"
                f"{_text(relation['left_keys'])} = {_text(relation['right_keys'])}（{_text(relation['key_normalization'])}）。",
                f"  篩選：{_text(relation['filters'])}；時間窗：{_text(relation['window'])}；可用時點依據：{_text(relation['at_index_basis'])}。",
                f"  覆蓋宣告：{_text(relation['coverage'])}；重複鍵處理：{_text(relation['duplicates'])}；事件重用：{_text(relation['reuse_events'])}；排除狀態：{_text(relation['exclude_statuses'])}。",
            ]
        )
        for feature in relation["features"]:
            lines.append(f"  衍生欄位 {_text(feature['output'])}：{_text(feature)}。")
    lines.extend(
        [
            "first/last 在時間窗內選第一／最後一個非缺失值；同時點異值會阻擋發布，不以列序擇一。unique 核對整個選取集合的非缺失值是否一致。",
            "",
            "#### 準備階段納排分母",
            "",
            "以下為準備分母；分析方法本身的缺失排除或模型分母仍需另行報告。",
            "| 步驟 | 之前列／單位／受試者 | 之後列／單位／受試者 | 排除列 |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for flow in summary["flow"]:
        counts = [
            " / ".join(str(flow[side].get(k, "未記錄")) for k in ("rows", "units", "subjects"))
            for side in ("before", "after")
        ]
        lines.append(
            f"| {_text(flow['step'])} | {counts[0]} | {counts[1]} | {flow['excluded_rows']} |"
        )
    for relation in summary["relationships"]:
        lines.extend(
            [
                "",
                f"##### {_text(relation['id'])} 的篩選流量",
                "",
                "事件與單位配對數、不同來源紀錄數、分析單位數與受試者數是不同分母；配對數不能當成人數。以下在特徵缺失值聚合前計數。",
                "| 階段 | 事件配對 | 不同來源紀錄 | 有紀錄分析單位 | 有紀錄受試者 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for flow in relation.get("selection_flow", []):
            stage = flow["stage"] + (f"[{flow['filter_index']}]" if "filter_index" in flow else "")
            lines.append(
                f"| {_text(stage)} | {flow['event_pairs']} | {flow['distinct_source_records']} | {flow['analysis_units_with_records']} | {flow['subjects_with_records']} |"
            )
        if not relation.get("selection_flow"):
            lines.append("逐步事件篩選流量未保存在此版本收據，不能由最終分母推定。")
        lines.append(
            f"技術關聯狀態（分析單位）：{_text(relation['statuses'])}；來源空連結鍵列：{relation['null_link_rows']}。"
        )
    lines.extend(
        [
            "",
            "技術狀態區分 link_failed（未連結）、filtered_out（規則篩除）、outside_window（窗外）、not_available（時點不可得）等；"
            "matched_partial 表示已配對但來源覆蓋非完整宣告，不等於配對失敗。這些狀態不能證明未量測的臨床原因、疾病陰性或照護完整性。",
            "",
            "#### 衍生欄位可得性",
            "",
            "| 欄位 | 有值 | 缺失 |",
            "| --- | ---: | ---: |",
        ]
    )
    for name, quality in summary["feature_quality"].items():
        lines.append(f"| {_text(name)} | {quality['observed']} | {quality['missing']} |")
    lines.extend(
        [
            "",
            "#### 可重算證據",
            "",
            "逐列追溯保存於 trace.jsonl；未連結／排除紀錄保存於 exceptions.jsonl；規格、validation.json 與 analysis.schema.json 隨同來源快照保留。",
            f"- 輸入資料 SHA-256：{release['dataset']['sha256']}。",
            f"- 規格 SHA-256：{release['specification_sha256']}。",
            f"- 準備計畫 SHA-256：{plan['receipt_sha256']}。",
            f"- 核准收據 SHA-256：{approval['receipt_sha256']}。",
            f"- 發布收據 SHA-256：{release['receipt_sha256']}。",
            f"- 匯入封裝 SHA-256：{evidence['bundle_sha256']}。",
        ]
    )
    return "\n".join(lines)
