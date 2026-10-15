"""Deterministic research views, with a private per-study key and no value map.

This is pseudonymization, not a claim of anonymous/clinically validated data.
Original bytes and clinical time variables are never overwritten.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets

import pandas as pd

from rde.domain.services.variable_classifier import VariableClassifier, PII_VALUE_PATTERNS
from rde.domain.models.variable import VariableType

POLICY = "rde-research-privacy-v1"
_DIRECT_KEY = re.compile(
    r"(?:^(?:.*_)?(?:patient_?id|subject_?id|person_?id|medical_?record(?:_?(?:id|no|number))?|chart_?(?:id|no)|mrn)$|病歷(?:號|編號)?$|身[份分]證(?:字號)?)",
    re.I,
)
_DATE = re.compile(r"(?:birthday|birthdate|date.?of.?birth|dob|出生|生日)", re.I)


def _key():
    target = os.environ.get("RDE_PRIVACY_KEY_FILE")
    if not target:
        target = str(Path(os.environ.get("RDE_WORKSPACE", ".")) / ".research-privacy.key")
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Atomic publish: another worker must never read an empty/partial new key.
    if not path.exists():
        pending = path.with_name(path.name + "." + secrets.token_hex(12))
        try:
            with pending.open("xb") as stream:
                os.chmod(pending, 0o600)
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(pending, path)
            except FileExistsError:
                pass
        finally:
            pending.unlink(missing_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Research privacy key must be a private regular file.")
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError(
            "Research privacy key is invalid; existing identities must not be replaced."
        )
    return key


def _value(value):
    # Preserve literal leading zeros; numeric 17 and 17.0 denote the same parsed key.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def propose_privacy(frame, source_sha256):
    classifier = VariableClassifier()
    columns = []
    for name in frame.columns:
        values = frame[name].dropna()
        reasons = classifier._pii_reasons(name, [])
        # Full-column scan: rare identifiers after the profiling sample still count.
        signals = {
            str(i): sum(bool(pattern.search(str(value))) for value in values)
            for i, pattern in enumerate(PII_VALUE_PATTERNS)
        }
        signals = {i: count for i, count in signals.items() if count}
        if signals:
            reasons.append("value_pattern")
        if _DATE.search(name):
            reasons.append("clinical_date")
        if _DIRECT_KEY.search(name):
            reasons.append("linkage_identifier")
        if reasons:
            columns.append(
                {
                    "column": name,
                    "action": (
                        "retain_clinical_date"
                        if _DATE.search(name)
                        else "pseudonymize"
                        if "name_pattern" in reasons or "linkage_identifier" in reasons
                        else "redact_identifier_spans"
                        if any(i != "2" for i in signals)
                        else "retain_ambiguous_signal"
                    ),
                    "signal_counts": signals,
                    "reasons": sorted(set(reasons)),
                }
            )
    if not columns:
        return None
    key = _key()
    return {
        "policy": POLICY,
        "source_sha256": source_sha256,
        "key_id": hashlib.sha256(key).hexdigest(),
        "columns": columns,
        "limitations": "Pseudonymized research view; dates and unrecognized identifiers may remain. Not certified anonymous; original source retained. No identity truth or clinical validation inferred.",
    }


def apply_privacy(frame, variables, privacy, *, source_path):
    if not privacy:
        return frame, variables
    key = _key()
    if privacy.get("policy") != POLICY or privacy.get("key_id") != hashlib.sha256(key).hexdigest():
        raise ValueError(
            "Research privacy policy/key changed; refusing to silently change saved identities."
        )
    with Path(source_path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != privacy.get("source_sha256"):
        raise ValueError("Research privacy source has changed.")
    frame = frame.copy()
    known = {v.name: v for v in variables}
    seen = set()
    for item in privacy["columns"]:
        name, action = item["column"], item["action"]
        if name not in known or name in seen:
            raise ValueError("Research privacy columns no longer match the source.")
        seen.add(name)
        variable = known[name]
        if action == "pseudonymize":
            frame[name] = frame[name].map(
                lambda value: pd.NA
                if pd.isna(value)
                else "RID_"
                + hmac.new(key, _value(value).encode("utf-8"), hashlib.sha256).hexdigest()
            )
            variable.dtype = str(frame[name].dtype)
            variable.variable_type = VariableType.ID
            variable.is_pii_suspect = False
        elif action == "redact_identifier_spans":

            def redact(value):
                if pd.isna(value):
                    return value
                text = str(value)
                for i, pattern in enumerate(PII_VALUE_PATTERNS):
                    if i != 2:  # bare phone/range shapes are ambiguous clinical text
                        text = pattern.sub(
                            lambda m: "[RID_"
                            + hmac.new(key, m.group().encode("utf-8"), hashlib.sha256).hexdigest()
                            + "]",
                            text,
                        )
                return text

            frame[name] = frame[name].map(redact)
        elif action not in {"retain_clinical_date", "retain_ambiguous_signal"}:
            raise ValueError("Unsupported research privacy action.")
        variable.extra["privacy_action"] = action
    return frame, variables


def protected_variable(previous, current):
    action = previous.extra.get("privacy_action")
    if action:
        current.extra["privacy_action"] = action
    if action == "pseudonymize":
        current.is_pii_suspect = False
        current.variable_type = VariableType.ID
    return current
