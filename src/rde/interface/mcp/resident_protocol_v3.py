"""Typed descriptive intents, scoped editorial evidence and bounded resident revision tasks."""

from hashlib import sha256
from urllib.parse import urlsplit
import json
import re

from rde.interface.mcp.resident_reasoning import LIMITS, sentence_slices
from rde.interface.mcp.resident_citations import render
from rde.interface.mcp.resident_tables import display_stat


def empty_presentation():
    return {"evidence_ids": [], "group_table": False, "source_ids": [], "link_source": False}


def presentation_schema(evidence, sources, table, target=None):
    def ids(keys, maximum):
        return {
            "type": "array",
            "uniqueItems": True,
            "maxItems": min(maximum, len(keys)),
            "items": {"type": "string", **({"enum": list(keys)} if keys else {})},
        }

    props = {
        "evidence_ids": ids(evidence, 3),
        "source_ids": ids(sources, 2),
        "group_table": {"type": "boolean", "enum": [False, True] if table else [False]},
        "link_source": {"type": "boolean"},
    }
    if target is None:
        props["prose"] = {"type": "string", "maxLength": 5000}
    else:
        props["edits"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "integer", "const": target},
                    "text": {"type": "string", "maxLength": 5000},
                },
                "required": ["sentence", "text"],
                "additionalProperties": False,
            },
        }
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def parse_author(raw, draft):
    obj = json.loads(raw)
    t = draft.get("repair_target", {}).get("sentence")
    presentation = empty_presentation()
    if not isinstance(obj, dict) or set(obj) != set(presentation) | (
        {"prose"} if t is None else {"edits"}
    ):
        raise ValueError("INVALID_AUTHOR_ENVELOPE")
    for k, options, cap in (
        ("evidence_ids", draft["editor_evidence"], 3),
        ("source_ids", draft["source_dictionary"], 2),
    ):
        ids = obj[k]
        if (
            not isinstance(ids, list)
            or len(ids) > cap
            or not all(isinstance(i, str) and i in options for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("INVALID_PRESENTATION_IDS")
    if (
        type(obj["link_source"]) is not bool
        or type(obj["group_table"]) is not bool
        or obj["group_table"] not in draft["response_schema"]["properties"]["group_table"]["enum"]
    ):
        raise ValueError("INVALID_PRESENTATION_CHOICE")
    presentation = {k: obj[k] for k in presentation}
    if t is None:
        prose = obj["prose"]
        if not isinstance(prose, str) or len(prose) > 5000:
            raise ValueError("INVALID_AUTHOR_PROSE")
        return prose, presentation
    edits = obj["edits"]
    if (
        not isinstance(edits, list)
        or len(edits) != 1
        or not isinstance(edits[0], dict)
        or set(edits[0]) != {"sentence", "text"}
    ):
        raise ValueError("INVALID_TARGETED_EDIT")
    e = edits[0]
    if (
        type(e["sentence"]) is not int
        or e["sentence"] != t
        or not isinstance(e["text"], str)
        or len(e["text"]) > 5000
    ):
        raise ValueError("INVALID_TARGETED_EDIT")
    parts = draft["sentences"].copy()
    parts[t] = e["text"]
    return "".join(parts), presentation


def compose(prose, presentation, cards, scope):
    base, changes = render(prose, cards, scope)
    out = []
    ids = presentation["evidence_ids"]
    if ids:
        bits = []
        for id_ in ids:
            card = cards[id_[1:]]
            dims = []
            if card.get("group") is not None:
                dims.append(str(card["group"]) + "組")
            if card.get("reference_group") is not None:
                dims.append("減參照" + str(card["reference_group"]) + "組")
            dims.append(card["statistic_title"])
            bits.append(" ".join(dims) + " " + display_stat(card) + "[" + id_ + "] " + card["unit"])
        out.append(
            {"kind": "evidence", "id": ",".join(ids), "rendered": "依據：" + "；".join(bits)}
        )
    sequence = [("table", "group_table")] if presentation["group_table"] else []
    sequence.extend(("dictionary", id_) for id_ in presentation["source_ids"])
    if presentation["link_source"]:
        sequence.append(("source", "source"))
    for kind, id_ in sequence:
        value, _ = render("{{" + id_ + "}}", cards, scope)
        out.append({"kind": kind, "id": id_, "rendered": value})
    return base + "".join("\n\n" + a["rendered"] for a in out), changes, out


FIELDS = {
    "data_quality": (
        "source_rows",
        "audit_dataset_denominators",
        ("rows", "missing_group", "missing_measure", "complete"),
    ),
    "group_estimates": ("group", "describe_group_means", ("rows", "observed", "mean")),
    "distribution": ("group", "describe_location_and_range", ("observed", "median", "min", "max")),
    "group_spread": (
        "group",
        "describe_within_group_variability",
        ("observed", "q1", "q3", "iqr", "sd"),
    ),
    "group_completeness": (
        "group",
        "audit_measurement_coverage",
        ("rows", "observed", "missing", "observed_percent", "missing_percent"),
    ),
    "group_contrasts": (
        "comparison_minus_reference",
        "describe_signed_group_differences",
        ("mean_difference", "median_difference"),
    ),
}
BASIS = {
    "rows": "all_assigned_rows",
    "observed": "assigned_rows_with_measure",
    "complete": "rows_with_both_columns",
    "missing_group": "rows_without_group",
    "missing_measure": "rows_without_measure",
    "missing": "assigned_rows_without_measure",
}


def capabilities(scope, definitions):
    out = {}
    for action, (level, purpose, fields) in FIELDS.items():
        specs = {}
        for field in fields:
            kind = (
                "count"
                if field in BASIS
                else "percentage"
                if field.endswith("_percent")
                else "signed_difference"
                if field.endswith("_difference")
                else "measurement"
            )
            spec = {
                "field": field,
                "level": level,
                "kind": kind,
                "unit": {"count": "筆", "percentage": "%"}.get(kind, scope["unit"]),
            }
            if kind == "count":
                spec["basis"] = (
                    "all_source_rows" if (level, field) == ("source_rows", "rows") else BASIS[field]
                )
            elif kind == "percentage":
                spec.update(numerator=field.removesuffix("_percent"), denominator="rows")
            elif kind == "signed_difference":
                spec["direction"] = "comparison_minus_reference"
            specs[action + "." + field] = spec
        out[action] = {
            "purpose": purpose,
            "fields": specs,
            "outputs": definitions[action],
            "limits": LIMITS[action],
        }
    return out


def choice_schema(available, contracts, prior):
    props = {
        "action": {"type": "string", "enum": available},
        "purpose": {"type": "string", "enum": [contracts[a]["purpose"] for a in available]},
        "intended_fields": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "string",
                "enum": [k for a in available for k in contracts[a]["fields"]],
            },
        },
        "reason": {"type": "string"},
    }
    if prior:
        props["prior_refs"] = {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "enum": list(prior)},
        }
    return {
        "type": "object",
        "properties": props,
        "required": ["action", "purpose", "intended_fields", "reason"],
        "additionalProperties": False,
    }


def intent_issues(choice, contracts, prior):
    action = choice["action"]
    contract = contracts[action]

    def problem(code, repair):
        return [{"issue": code, "repair": repair, "capability": contract}]

    if set(choice) - {"action", "intended_fields", "purpose", "reason", "prior_refs"}:
        return problem("INVALID_INTENT_KEYS", "只填原生 schema 中的鍵。")
    if choice.get("purpose") != contract["purpose"]:
        return problem("PURPOSE_OUTSIDE_ACTION", "此動作的授權用途為 " + contract["purpose"])
    fields = choice.get("intended_fields")
    if (
        not isinstance(fields, list)
        or not 1 <= len(fields) <= 6
        or not all(isinstance(f, str) and f in contract["fields"] for f in fields)
        or len(set(fields)) != len(fields)
    ):
        return problem(
            "FIELD_OUTSIDE_ACTION", "逐項選擇此動作輸出的完整 field ID，核對計數基準及單位。"
        )
    refs = choice.get("prior_refs", [])
    if (
        not isinstance(refs, list)
        or len(refs) > 4
        or not all(isinstance(f, str) and f in prior for f in refs)
    ):
        return problem("PRIOR_EVIDENCE_NOT_OBSERVED", "僅可引用先前已取得的彙總卡。")
    return []


def source_scope(scope, cards):
    urls = re.findall(r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+", scope["source_note"])
    groups = list(
        dict.fromkeys(
            c["value"]
            for c in cards.values()
            if c["label"].startswith("group_estimates/") and c["label"].endswith("/group")
        )
    )
    return {
        "source_sha256": scope["source"],
        "approved_dictionary": scope["source_note"],
        "source_urls": urls,
        "source_domains": sorted({urlsplit(u).hostname for u in urls if urlsplit(u).hostname}),
        "group_column": scope["group"],
        "observed_group_levels": groups,
        "measure_column": scope["measure"],
        "measurement_unit": scope["unit"],
        "approved_population": scope["population"],
        "count_unit": "資料列；觀測對象或重複量測關係依核准來源／資料字典判定。",
        "available_methods": list(FIELDS),
        "not_measured": [
            "隨機抽樣的代表性",
            "選樣偏差是否為零",
            "統計顯著性與信賴區間",
            "治療療效與因果效應",
            "未記載的設計程序或資料作者",
        ],
    }


def editing_evidence(cards, actions):
    return {
        "R" + k: {
            f: c[f]
            for f in (
                "statistic",
                "statistic_title",
                "group",
                "reference_group",
                "value",
                "unit",
                "measure_column",
                "group_column",
            )
            if f in c
        }
        for k, c in cards.items()
        if c["label"].split("/")[0] in actions and type(c["value"]) in (int, float)
    }


def target_sentence(previous):
    sentences = sentence_slices(previous["author_source"])
    diagnostics = previous["result"]["diagnostics"]
    for d in diagnostics:
        i = d.get("sentence")
        if type(i) is not int:
            quote = d.get("quote")
            i = next(
                (
                    j
                    for j, s in enumerate(sentences)
                    if isinstance(quote, str) and quote and quote in s
                ),
                None,
            )
        if type(i) is int and 0 <= i < len(sentences):
            break
    else:
        # Missing evidence/insufficient prose can legitimately require adding a sentence.
        i = next((j for j in reversed(range(len(sentences))) if sentences[j].strip()), 0)
        d = diagnostics[0]
    raw = sentences[i]
    return {
        "sentence": i,
        "issue": d["issue"],
        "previous_text": raw,
        "source_sha256": sha256(raw.encode()).hexdigest(),
        "mode": "replace_sentence",
        "repair": d.get("repair", d["issue"]),
    }


def validate_external(value, source, response, author):
    """Verify the actual referee reply hash, its author binding and each quoted location."""
    if not isinstance(value, dict):
        raise ValueError("INVALID_EXTERNAL_REVIEW")
    exact = {
        "verdict",
        "reviewer",
        "source_sha256",
        "response_sha256",
        "author_source_sha256",
        "reviewer_response_sha256",
        "reviewer_response",
        "diagnostics",
    }

    def h(t):
        return sha256(t.encode()).hexdigest()

    if (
        set(value) != exact
        or value["verdict"] not in ("accept", "repair")
        or not isinstance(value["reviewer"], str)
        or not value["reviewer"].strip()
        or value["source_sha256"] != source
        or value["response_sha256"] != h(response)
        or value["author_source_sha256"] != h(author)
        or not isinstance(value["reviewer_response"], str)
        or h(value["reviewer_response"]) != value["reviewer_response_sha256"]
    ):
        raise ValueError("EXTERNAL_REVIEW_IDENTITY_MISMATCH")
    try:
        raw = json.loads(value["reviewer_response"])
    except ValueError as ex:
        raise ValueError("INVALID_EXTERNAL_REVIEW_JSON") from ex
    if (
        not isinstance(raw, dict)
        or set(raw) != {"findings"}
        or not isinstance(raw["findings"], list)
        or ("repair" if raw["findings"] else "accept") != value["verdict"]
    ):
        raise ValueError("EXTERNAL_VERDICT_MISMATCH")
    issues = value["diagnostics"]
    if (
        not isinstance(issues, list)
        or len(issues) > 20
        or bool(issues) != (value["verdict"] == "repair")
    ):
        raise ValueError("EXTERNAL_REVIEW_DIAGNOSTICS_MISMATCH")
    sentences = sentence_slices(author)
    if len(issues) != len(raw["findings"]):
        raise ValueError("EXTERNAL_REVIEW_DIAGNOSTICS_MISMATCH")
    for d, f in zip(issues, raw["findings"], strict=True):
        if (
            not isinstance(d, dict)
            or set(d) != {"issue", "quote", "repair"}
            or any(not isinstance(v, str) or not v.strip() for v in d.values())
            or d["quote"] not in author
        ):
            raise ValueError("EXTERNAL_QUOTE_NOT_IN_AUTHOR_SOURCE")
        if (
            not isinstance(f, dict)
            or set(f) != {"sentence", "issue", "reason"}
            or type(f["sentence"]) is not int
            or not 0 <= f["sentence"] < len(sentences)
            or d["quote"] not in sentences[f["sentence"]]
            or d["issue"] != f["issue"]
            or d["repair"] != f["reason"]
        ):
            raise ValueError("EXTERNAL_FINDING_QUOTE_MISMATCH")
    return [
        {
            "issue": "EXTERNAL_SCIENTIFIC_REVIEW",
            "finding": d["issue"],
            "quote": d["quote"],
            "repair": d["repair"],
            "sentence": f["sentence"],
        }
        for d, f in zip(issues, raw["findings"], strict=True)
    ]
