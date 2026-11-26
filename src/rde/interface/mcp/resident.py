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
from rde.interface.mcp.resident_bindings import edited_blocks, expand

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
    for action_number, action in enumerate(ACTIONS, 1):
        path = folder / (action + ".json")
        if not path.exists():
            continue
        doc = read_sealed(path)["payload"]
        ref = artifact_reference(project, path.relative_to(project.output_dir).as_posix(), path)

        card_number = 0

        def visit(value, pointer, label):
            nonlocal card_number
            if isinstance(value, list):
                for i, item in enumerate(value):
                    visit(item, f"{pointer}/{i}", f"{label}/{item['group']}")
            elif isinstance(value, dict):
                for key, item in value.items():
                    visit(item, f"{pointer}/{key}", f"{label}/{key}")
            elif value is not None:
                card_number += 1
                key = f"{action_number}.{card_number}"
                cards[key] = {
                    "label": label,
                    "value": value,
                    "pointer": pointer,
                    "artifact_id": ref.artifact_id,
                    "sha256": ref.sha256,
                }

        visit(doc["observation"], "/payload/observation", action)
    return cards


def scope_diagnostics(text, scope):
    """Locate unsupported affirmative claims in a descriptive-only study."""
    approved = scope["source_note"] + " " + scope["population"]
    out = []
    for match in re.finditer(r"[^。！？\n；]+", text):
        clause = match.group().strip()
        if re.search(
            r"未|無法|(?:並|而|亦)?非隨機|不是|並不|不(?:應|宜|足|能|明|確定)|是否|若|缺乏|假設|避免|難以",
            clause,
        ):
            continue
        unsupported = any(
            term in clause and term not in approved
            for term in ("隨機分派", "隨機分配", "隨機分組", "雙盲", "前瞻性試驗")
        )
        if unsupported:
            code = "UNDOCUMENTED_STUDY_DESIGN"
        elif re.search(
            r"統計(?:學)?(?:上)?顯著|顯著(?:提升|降低|增加|增長|高於|低於)|因果鏈", clause
        ):
            code = "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE"
        else:
            continue
        out.append(
            {"issue": code, "start": match.start(), "end": match.end(), "quote": clause[:220]}
        )
    return out


def scope_issues(text, scope):
    return list(dict.fromkeys(d["issue"] for d in scope_diagnostics(text, scope)))


def cited_claims(text, cards, unit):
    """Bind each bracket occurrence to the author's own nearby value, including shared citations."""
    claims, used, diagnostics = [], set(), []
    previous_end, number_match = -1, None
    optional_unit = r"(?:筆|人|名|隻|位|例|%" + ("|" + re.escape(unit) if unit else "") + r")?"
    value_end = re.compile(
        r"(?<![A-Za-z0-9.])(-?\d+(?:\.\d+)?)\*{0,2}\s*" + optional_unit + r"\s*\*{0,2}\s*$"
    )
    for match in re.finditer(r"\[R(\d+\.\d+)\]", text):
        key = match.group(1)
        if previous_end < 0 or not re.fullmatch(r"[\s*、,，]*", text[previous_end : match.start()]):
            number_match = value_end.search(text, 0, match.start())
        card = cards.get(key)
        previous_end = match.end()
        if not card or not number_match:
            diagnostics.append(
                {
                    "issue": "UNKNOWN_REFERENCE" if not card else "UNBOUND_REFERENCE",
                    "reference": "R" + key,
                    "start": match.start(),
                    "end": match.end(),
                    "quote": text[max(0, match.start() - 32) : match.end()],
                }
            )
            continue
        number = number_match.group(1)
        claim = {k: card[k] for k in ("pointer", "artifact_id", "sha256")}
        claim["quote"] = text[number_match.start() : match.end()]
        if isinstance(card["value"], str):
            claim["value"] = number
        else:
            claim.update(value=float(number), decimals=min(8, len(number.partition(".")[2])))
        claims.append(claim)
        used.add(key)
    return claims, used, diagnostics


def section_review(project_id, text, cards, section, unit=""):
    claims, used, diagnostics = cited_claims(text, cards, unit)
    issues = [d["issue"] for d in diagnostics]
    for m in re.finditer(r"\[E?\d+(?:\.\d+)?\]", text):
        issues.append("UNRESOLVED_CITATION")
        diagnostics.append(
            {"issue": "UNRESOLVED_CITATION", "quote": m.group(), "start": m.start(), "end": m.end()}
        )
    if len(claims) > 32 or len(text) > 20000:
        issues.append("REVIEW_SIZE_LIMIT")
    native = (
        review(project_id, text, claims) if claims and "REVIEW_SIZE_LIMIT" not in issues else None
    )
    if native:
        issues.extend(native["issues"])
        for check in native["checks"]:
            if check["issue"]:
                claim = claims[check["claim"]]
                diagnostics.append(
                    {"issue": check["issue"], "quote": claim["quote"], "pointer": claim["pointer"]}
                )
    if section == 2:
        missing = [
            f"R{key} {card['label']}"
            for key, card in cards.items()
            if card["label"].endswith(("/observed", "/mean"))
            and card["label"].startswith("group_estimates/")
            and key not in used
        ]
        if missing:
            issues.append("MISSING_GROUP_ESTIMATE_OR_DENOMINATOR")
            diagnostics.append({"issue": issues[-1], "missing": missing})
    if len(text.strip()) < 350:
        issues.append("SECTION_TOO_SHORT")
    if re.search(r'XX\.XX|\{\s*"(?:observation|artifact_id|text)"\s*:|待填寫', text):
        issues.append("PLACEHOLDER_OR_RAW_RECEIPT")
    return {
        "issues": list(dict.fromkeys(issues)),
        "review": native,
        "used": sorted(used),
        "diagnostics": diagnostics,
    }


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
            "reason 要根據已取得的觀察指出缺口。所有計數都以資料列為單位；受試者人數須依研究設計另行核對。"
            "data_quality 查分母與缺失，group_estimates 查分組平均，"
            "distribution 查中位與範圍。\n研究範圍 "
            + json.dumps(scope, ensure_ascii=False)
            + "\n尚可用 "
            + json.dumps(available)
            + "\n已取得 "
            + json.dumps(compact(), ensure_ascii=False)
        )

    def compact():
        return {
            "R" + k: {
                "field": v["label"],
                "value": v["value"],
                **(
                    {"citation": f"{round(v['value'], 4)}[R{k}]"}
                    if type(v["value"]) in (float, int)
                    else {}
                ),
            }
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
        elif scope_issues(choice["reason"], scope):
            issue = "UNDOCUMENTED_STUDY_DESIGN"
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
        authorship = []
        for i, title in enumerate(SECTIONS):
            attempts = sorted(folder.glob(f"section-{i}-*.json"))
            if not attempts:
                raise ValueError("MISSING_SECTION")
            record = read_sealed(attempts[-1])["payload"]
            chapters.append("## " + title + "\n\n" + record["text"])
            dispositions.append(record["issues"])
            authorship.append(
                {
                    "title": title,
                    "attempt": record.get("attempt", int(attempts[-1].stem.split("-")[-1])),
                    "source": record.get("author_source", record["text"]),
                    "replacements": record.get("replacements", []),
                    "edit_applied": record.get("edit_applied", False),
                }
            )
        return {
            "status": "withheld" if any(dispositions) else "independent_review_required",
            "issues": dispositions,
            "manuscript": "\n\n".join(chapters),
            "authorship": authorship,
            "cards": card_index(project, folder),
            "source": scope["source"],
            "question": scope["question"],
        }
    if turn not in range(len(SECTIONS)) or attempt not in (1, 2, 3):
        raise ValueError("INVALID_CHAPTER")
    if attempt > 1:
        previous = read_sealed(folder / f"section-{turn}-{attempt-1}.json")["payload"]
        previous.setdefault("author_source", previous["text"])
        previous.setdefault("diagnostics", [])
        if not previous["issues"]:
            raise ValueError("CHAPTER_ALREADY_VERIFIED")
    if op == "draft":
        prompt = (
            "用繁體中文為這份研究撰寫指定章節，直接輸出 Markdown 正文，目標 900 至 1150 字。"
            "根據已批准的問題及公開資料說明作答。研究問題、方法、結果、敏感性及限制各章要有不同功能。"
            "第一章交代問題、來源及估計目標，方法章寫可重做的步驟與缺值處理，"
            "結果章以表格及文字比較，資料品質章檢視觀察到的分布及替代解釋，末章交代設計邊界與重查方式。"
            "證據卡的 citation 欄有數值加索引，引用時逐字複製到句子或表格，再接單位。"
            "所有計數均為資料列，是否可換算成獨立觀測對象須以資料說明查證。"
            "談及分派方式、收案或因果時須以給定的資料說明為準。"
            "討論資料來源時使用核准的公開資料字典連結。請直接寫章節內文，無須重複章名。"
            "主要結果章以表格呈現每一組有效人數與平均，每格有自己的引用。"
            "保留原有的觀測層級、單位及族群限制。\n章節 "
            + SECTIONS[turn]
            + "\n研究範圍 "
            + json.dumps(scope, ensure_ascii=False)
            + "\n可核對的證據卡 "
            + json.dumps(compact(), ensure_ascii=False)
        )
        prompt += (
            "\n研究能支持的分析只有已執行的分組描述。請將觀測結果和推測逐段區分。"
            "每個推測須指出何種尚未取得的資料才能檢查。觀測列數、隨機抽樣和隨機分派是不同條件。"
            "重現資訊應指出欄位、有效分母、計算順序和資料字典。網址寫成 Markdown 連結，使用來源所給的完整 URL。"
        )
        prompt += (
            "\n請自行選擇要引用的 RDE 證據。主要結果章可在獨立段落輸入 {{group_table}} 以插入核准欄位的原生結果表。"
            "正文要使用數值時，單獨寫證據卡的代號，例如 {{R1.1}}，工具會排入你選擇的數值與索引。"
            "引用資料字典寫 {{source}}。每個分析判斷及段落都由你撰寫，工具只排版所選欄位。"
            "請用段落說明問題、觀察及邊界，避免宣稱取得工具未計算的檢定、介入機制或病人層級因果效果。"
        )
        if attempt == 2:
            prompt += (
                "\n重新撰寫本章。下列原文片段有審核問題，需核對、刪去或自行改寫。請勿將回饋貼進正文。"
                + json.dumps(
                    {"issues": previous["issues"], "locations": previous["diagnostics"][:18]},
                    ensure_ascii=False,
                )
            )
        if attempt == 3:
            blocks = re.split(r"\n\s*\n", previous["author_source"].strip())
            prompt += (
                "\n最後一次為逐段修改。只輸出 JSON，格式為 "
                + '{"edits":[{"block":0,"text":"你改寫的完整段落"}]}'
                + (
                    "。block 是下列原文的零起始索引。只修改有問題的段落，可用空字串刪除無根據的段落。"
                    "含結果數表的段落可替換為 {{group_table}}。其他段落會逐字保留。\n"
                )
                + json.dumps(
                    {
                        "blocks": list(enumerate(blocks)),
                        "issues": previous["issues"],
                        "locations": previous["diagnostics"][:18],
                    },
                    ensure_ascii=False,
                )
            )
        return {"prompt": prompt, "status": "draft"}
    author_source = response
    edit_issue = None
    if attempt == 3:
        try:
            author_source = edited_blocks(previous["author_source"], response)
        except (ValueError, TypeError):
            author_source, edit_issue = previous["author_source"], "INVALID_EDIT_SET"
    cards = card_index(project, folder)
    rendered, replacements = expand(author_source, cards, scope)
    checked = section_review(project.id, rendered, cards, turn, scope["unit"])
    if edit_issue:
        checked["issues"].append(edit_issue)
    if re.search(r"\{\{[^{}]+\}\}", rendered):
        checked["issues"].append("UNKNOWN_FIELD_BINDING")
    design = scope_diagnostics(rendered, scope)
    checked["issues"] = list(dict.fromkeys(checked["issues"] + [item["issue"] for item in design]))
    checked["diagnostics"].extend(design)
    write_once(
        folder / f"section-{turn}-{attempt}.json",
        {
            "text": rendered,
            "attempt": attempt,
            "author_source": author_source,
            "response": response,
            "replacements": replacements,
            "edit_applied": attempt == 3 and not edit_issue,
            **checked,
        },
    )
    return {"status": "repair" if checked["issues"] else "observed", **checked}
