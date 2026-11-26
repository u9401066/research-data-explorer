"""Feedback on one observable action. No task IDs, benchmark answers or model-authored reference text."""

from __future__ import annotations

import base64
import json
import math
import re
from decimal import Decimal
from hashlib import sha256

from rde.interface.mcp.results import read_artifact_page

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024


def digest(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def delivery(result, arguments):
    """A receipt for a delivery, including errors or replay, without exposing raw arguments."""
    return {
        "schema": "rde-action-review-v1",
        "invocation_id": result.invocation_id,
        "tool": result.tool,
        "input_sha256": digest(arguments or {}),
        "disposition": "repair" if result.status == "error" else "observe",
        "error_code": result.error.code if result.error else None,
        "source_sha256": [s.sha256 for s in result.context.sources],
        "artifact_sha256": [a.sha256 for a in result.artifacts],
    }


def pointer(value, locator):
    if not isinstance(locator, str) or not locator.startswith("/") or len(locator) > 500:
        raise ValueError("INVALID_LOCATOR")
    for part in locator[1:].split("/"):
        if re.search(r"~(?![01])", part):
            raise ValueError("INVALID_LOCATOR")
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("INVALID_LOCATOR")
    return value


def artifact_json(project_id, artifact, revision):
    chunks = []
    offset = 0
    while True:
        page = read_artifact_page(project_id, artifact, revision, offset, 262144)
        if page["artifact"]["bytes"] > MAX_EVIDENCE_BYTES or not page["artifact"][
            "relative_path"
        ].lower().endswith(".json"):
            raise ValueError("UNSUPPORTED_EVIDENCE")
        chunks.append(base64.b64decode(page["content_base64"], validate=True))
        offset = page["next_offset"]
        if offset is None:
            break
    raw = b"".join(chunks)
    if sha256(raw).hexdigest() != revision:
        raise ValueError("STALE_EVIDENCE")
    return json.loads(raw)


def compare_scalar(actual, asserted, decimals=None):
    if decimals is None:
        if type(actual) is bool or type(asserted) is bool:
            return type(actual) is type(asserted) and actual == asserted
        return isinstance(actual, (str, float, int)) and actual == asserted
    if type(decimals) is not int or not 0 <= decimals <= 8:
        return False
    if type(actual) not in (float, int) or type(asserted) not in (float, int):
        return False
    if not math.isfinite(actual) or not math.isfinite(asserted):
        return False
    value = Decimal(str(asserted))
    precision = Decimal(10) ** -decimals
    return value == value.quantize(precision) and abs(Decimal(str(actual)) - value) <= precision / 2


def review(project_id, utterance, claims, *, reader=artifact_json):
    """Return locator-level diagnostics, never replacement findings or manuscript text."""
    if not isinstance(utterance, str) or not utterance.strip() or len(utterance) > 20000:
        raise ValueError("Invalid utterance")
    if not isinstance(claims, list) or len(claims) > 32:
        raise ValueError("Invalid claim inventory")
    checks = []
    cache = {}
    for index, claim in enumerate(claims):
        issue = None
        if not isinstance(claim, dict) or set(claim) - {
            "quote",
            "artifact_id",
            "sha256",
            "pointer",
            "value",
            "decimals",
        }:
            issue = "INVALID_CLAIM"
        elif (
            not isinstance(claim.get("quote"), str)
            or not claim["quote"].strip()
            or claim["quote"] not in utterance
        ):
            issue = "QUOTE_NOT_IN_MESSAGE"
        elif not all(
            isinstance(claim.get(k), str) and re.fullmatch("[a-f0-9]{64}", claim[k])
            for k in ("artifact_id", "sha256")
        ):
            issue = "MISSING_ARTIFACT_BINDING"
        else:
            key = (claim["artifact_id"], claim["sha256"])
            try:
                if key not in cache:
                    cache[key] = reader(project_id, *key)
                native = pointer(cache[key], claim.get("pointer"))
                if not compare_scalar(native, claim.get("value"), claim.get("decimals")):
                    issue = "VALUE_MISMATCH"
                elif type(native) in (float, int) and not any(
                    Decimal(n) == Decimal(str(claim["value"]))
                    for n in re.findall(
                        r"(?<![A-Za-z0-9.])-?[0-9]+(?:\.[0-9]+)?(?![0-9.])", claim["quote"]
                    )
                ):
                    issue = "VALUE_NOT_IN_QUOTE"
                elif isinstance(native, str) and native not in claim["quote"]:
                    issue = "VALUE_NOT_IN_QUOTE"
            except (ValueError, TypeError, KeyError, IndexError, OSError, ArithmeticError):
                issue = "STALE_OR_INVALID_REFERENCE"
        checks.append({"claim": index, "issue": issue})
    issues = [c for c in checks if c["issue"]]
    return {
        "schema": "rde-dialogue-review-v1",
        "utterance_sha256": sha256(utterance.encode()).hexdigest(),
        "claims_sha256": digest(claims),
        "checks": checks,
        "disposition": "repair" if issues or not checks else "continue",
        "issues": ["NO_EVIDENCE_CLAIMS"] if not checks else [c["issue"] for c in issues],
        "coverage": "submitted_claims_only",
        "scientific_release": "requires_independent_review",
    }
