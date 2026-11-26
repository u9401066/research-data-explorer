"""Source-bound descriptive exploration with a bounded dialogue and immutable observation records."""

from __future__ import annotations

import json
import math
import re

import pandas as pd

from rde.infrastructure.adapters.dataframe_lineage import dataset_version
from rde.interface.mcp.action_review import digest, review
from rde.interface.mcp.research_plans import read_sealed, write_once
from rde.interface.mcp.results import artifact_reference

ACTIONS = ("data_quality", "group_estimates", "distribution")
SECTIONS = ("研究問題與資料", "方法與分母", "主要結果", "資料品質與替代解釋", "限制與可重現性")


def observations(frame, scope, action):
    group, measure = scope["group"], scope["measure"]
    if group == measure or group not in frame or measure not in frame:
        raise ValueError("UNKNOWN_OR_DUPLICATE_COLUMN")
    values = pd.to_numeric(frame[measure], errors="coerce")
    if (frame[measure].notna() & values.isna()).any() or not all(
        map(math.isfinite, values.dropna())
    ):
        raise ValueError("NON_NUMERIC_MEASURE")
    if not 1 <= frame[group].nunique() <= 20:
        raise ValueError("GROUP_CARDINALITY_OUT_OF_SCOPE")
    if action == "data_quality":
        return {
            "rows": len(frame),
            "missing_group": int(frame[group].isna().sum()),
            "missing_measure": int(values.isna().sum()),
            "complete": int((frame[group].notna() & values.notna()).sum()),
        }
    if action not in ACTIONS:
        raise ValueError("UNKNOWN_ACTION")
    groups = []
    for label, positions in frame.groupby(group, observed=True, sort=True).indices.items():
        subset = values.iloc[positions].dropna()
        row = {"group": str(label), "observed": len(subset), "rows": len(positions)}
        if action == "group_estimates":
            row["mean"] = float(subset.mean()) if len(subset) else None
        else:
            for name in ("median", "min", "max"):
                row[name] = float(getattr(subset, name)()) if len(subset) else None
        groups.append(row)
    return {"groups": groups}


def card_index(project, folder):
    cards = {}
    for action in ACTIONS:
        path = folder / (action + ".json")
        if not path.exists():
            continue
        doc = read_sealed(path)["payload"]
        ref = artifact_reference(project, path.relative_to(project.output_dir).as_posix(), path)

        def visit(value, pointer, label):
            if isinstance(value, list):
                for i, item in enumerate(value):
                    visit(item, f"{pointer}/{i}", f"{label}/{item['group']}")
            elif isinstance(value, dict):
                for key, item in value.items():
                    visit(item, f"{pointer}/{key}", f"{label}/{key}")
            elif value is not None:
                key = f"{ACTIONS.index(action)+1}.{len([k for k in cards if k.startswith(str(ACTIONS.index(action)+1)+'.')])+1}"
                cards[key] = {
                    "label": label,
                    "value": value,
                    "pointer": pointer,
                    "artifact_id": ref.artifact_id,
                    "sha256": ref.sha256,
                }

        visit(doc["observation"], "/payload/observation", action)
    return cards


def section_review(project_id, text, cards, section):
    issues = []
    claims = []
    used = set()
    # The resident places each locator beside the raw or rounded number it supports.
    pattern = r"(-?\d+(?:\.\d+)?)\s*\[R(\d+\.\d+)\]"
    for match in re.finditer(pattern, text):
        number, key = match.groups()
        card = cards.get(key)
        if not card:
            issues.append("UNKNOWN_REFERENCE")
            continue
        used.add(key)
        claims.append(
            {k: card[k] for k in ("pointer", "artifact_id", "sha256")}
            | {
                "quote": match.group(),
                "value": float(number),
                "decimals": min(8, len(number.partition(".")[2])),
            }
        )
    if len(used) != len(set(re.findall(r"\[R(\d+\.\d+)\]", text))):
        issues.append("UNBOUND_REFERENCE")
    native = review(project_id, text, claims) if claims else None
    if native:
        issues.extend(native["issues"])
    if section == 2:
        if any(
            card["label"].endswith(("/observed", "/mean"))
            and card["label"].startswith("group_estimates/")
            and key not in used
            for key, card in cards.items()
        ):
            issues.append("MISSING_GROUP_ESTIMATE_OR_DENOMINATOR")
    if len(text.strip()) < 350:
        issues.append("SECTION_TOO_SHORT")
    if re.search(r"XX\.XX|\{\s*\"(?:observation|artifact_id|text)\"\s*:|待填寫", text):
        issues.append("PLACEHOLDER_OR_RAW_RECEIPT")
    return {"issues": list(dict.fromkeys(issues)), "review": native, "used": sorted(used)}


def run(project, entry, scope, op, turn, attempt, response):
    required = {
        "approval",
        "run",
        "source",
        "question",
        "group",
        "measure",
        "unit",
        "population",
        "source_note",
    }
    if set(scope) != required or not all(
        isinstance(v, str) and 0 < len(v.strip()) <= 4000 for v in scope.values()
    ):
        raise ValueError("INVALID_APPROVED_SCOPE")
    if not all(re.fullmatch("[0-9a-f]{64}", scope[k]) for k in ("source", "approval")):
        raise ValueError("INVALID_SOURCE_OR_APPROVAL")
    folder = (
        project.artifacts_dir / "resident_exploration" / digest([scope["approval"], scope["run"]])
    )
    if op == "open":
        version = dataset_version(project, entry)
        if version["source_status"] != "verified" or version["source"]["sha256"] != scope["source"]:
            raise ValueError("UNVERIFIED_SOURCE")
        write_once(
            folder / "scope.json",
            {"scope": scope, "version": version["version_sha256"], "dataset_id": entry.dataset.id},
        )
    anchor = read_sealed(folder / "scope.json")["payload"]
    if anchor["scope"] != scope or anchor["dataset_id"] != entry.dataset.id:
        raise ValueError("SCOPE_CHANGED")

    def action_prompt():
        available = [k for k in ACTIONS if not (folder / f"{k}.json").exists()]
        return (
            "你負責選擇下一項有助回答問題的 RDE 查詢。只輸出 JSON，鍵為 action 和 reason。"
            "reason 要根據已取得的觀察指出缺口。data_quality 查分母與缺失，group_estimates 查分組平均，"
            "distribution 查中位與範圍。\n研究範圍 "
            + json.dumps(scope, ensure_ascii=False)
            + "\n尚可用 "
            + json.dumps(available)
            + "\n已取得 "
            + json.dumps(compact(), ensure_ascii=False)
        )

    def compact():
        return {
            k: {"field": v["label"], "value": v["value"]}
            for k, v in card_index(project, folder).items()
        }

    if op == "open":
        return {"prompt": action_prompt(), "status": "explore"}
    if op == "observe":
        if turn not in range(1, 5) or (
            turn > 1 and not (folder / f"action-{turn-1}.json").exists()
        ):
            raise ValueError("INVALID_ACTION_SEQUENCE")
        try:
            choice = json.loads(response)
        except ValueError:
            choice = None
        action = choice.get("action") if isinstance(choice, dict) else None
        path = folder / f"action-{turn}.json"
        if path.exists():
            old = read_sealed(path)["payload"]
            if old["response"] != response:
                raise ValueError("ACTION_REPLAY_CHANGED")
            return old["result"]
        issue = None
        if (
            action not in ACTIONS
            or not isinstance(choice.get("reason"), str)
            or not choice["reason"].strip()
        ):
            issue = "INVALID_ACTION_OR_REASON"
        elif (folder / f"{action}.json").exists():
            issue = "REPEATED_ACTION"
        else:
            if dataset_version(project, entry)["version_sha256"] != anchor["version"]:
                raise ValueError("DATASET_CHANGED")
            write_once(
                folder / f"{action}.json",
                {
                    "source": scope["source"],
                    "version": anchor["version"],
                    "observation": observations(entry.dataframe, scope, action),
                },
            )
        result = {
            "status": "repair" if issue else "observed",
            "issue": issue,
            "action": action,
            "prompt": (f"上個動作需修正 {issue}。\n" if issue else "") + action_prompt(),
        }
        write_once(path, {"turn": turn, "response": response, "result": result})
        return result
    if op not in {"draft", "review", "assemble"}:
        raise ValueError("UNKNOWN_OPERATION")
    missing = [
        k for k in ("data_quality", "group_estimates") if not (folder / f"{k}.json").exists()
    ]
    if missing:
        return {"status": "withheld", "issues": ["MISSING_OBSERVATION:" + k for k in missing]}
    if op == "assemble":
        chapters = []
        dispositions = []
        for i, title in enumerate(SECTIONS):
            attempts = sorted(folder.glob(f"section-{i}-*.json"))
            if not attempts:
                raise ValueError("MISSING_SECTION")
            record = read_sealed(attempts[-1])["payload"]
            chapters.append("## " + title + "\n\n" + record["text"])
            dispositions.append(record["issues"])
        return {
            "status": "withheld" if any(dispositions) else "independent_review_required",
            "issues": dispositions,
            "manuscript": "\n\n".join(chapters),
            "cards": card_index(project, folder),
            "source": scope["source"],
            "question": scope["question"],
        }
    if turn not in range(len(SECTIONS)) or attempt not in (1, 2):
        raise ValueError("INVALID_CHAPTER")
    if attempt == 2:
        previous = read_sealed(folder / f"section-{turn}-1.json")["payload"]
        if not previous["issues"]:
            raise ValueError("CHAPTER_ALREADY_VERIFIED")
    if op == "draft":
        prompt = (
            "用繁體中文為這份研究撰寫指定章節，直接輸出 Markdown 正文，目標 500 至 700 字。"
            "根據已批准的問題及公開資料說明作答。研究問題、方法、結果、敏感性及限制各章要有不同功能。"
            "量測數字使用 數字[R編號]，單位跟在引用後。例如引用格式是 數字[R卡號]。"
            "主要結果章以表格呈現每一組有效人數與平均，每格有自己的引用。"
            "保留原有的觀測層級、單位及族群限制。\n章節 "
            + SECTIONS[turn]
            + "\n研究範圍 "
            + json.dumps(scope, ensure_ascii=False)
            + "\n可核對的證據卡 "
            + json.dumps(compact(), ensure_ascii=False)
        )
        if attempt == 2:
            prompt += "\n剛才章節的審核原因和原文，請自行修改 " + json.dumps(
                previous, ensure_ascii=False
            )
        return {"prompt": prompt, "status": "draft"}
    checked = section_review(project.id, response, card_index(project, folder), turn)
    write_once(folder / f"section-{turn}-{attempt}.json", {"text": response, **checked})
    return {"status": "repair" if checked["issues"] else "observed", **checked}
