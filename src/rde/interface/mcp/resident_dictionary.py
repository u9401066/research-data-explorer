"""Bind explicit categorical code/label declarations to the approved source dictionary."""

from hashlib import sha256
import re


CODE = r"[A-Za-zＡ-Ｚａ-ｚ0-9０-９][A-Za-zＡ-Ｚａ-ｚ0-9０-９_\-]*"
PAIR = re.compile(
    rf"(?:[`「『\x22']?(?P<code>{CODE})[`」』\x22']?)\s*"
    r"(?:=|＝|:|：|為|代表|表示|對應(?:於)?|意指|means\b|stands for\b)\s*"
    r"(?P<label>[^、,，;；。！？!?()（）\r\n]{1,120})",
    re.I,
)
SEPARATOR = re.compile(r"\s*[、,，;；]\s*")
SOURCE_URL = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+")


def declared_mappings(text, scope):
    columns = {scope["group"], scope["measure"]}
    # A new column or prose statement ends the mapping list. Never carry a
    # column name over a separate sentence or infer labels from the data rows.
    names = "|".join(re.escape(c) for c in sorted(columns, key=len, reverse=True))
    heading = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<column>{names})(?![A-Za-z0-9_])[`」』]?\s*"
        r"(?:(?:欄位?|變項|變數|的|代碼|編碼|分組|組別|分類|取值|來源字典|字典|欄值|column|codes?|coding)\s*)*"
        r"(?:為|是|以|包含)?\s*[（(:：=，,]?\s*",
        re.I,
    )
    mappings = []
    for head in heading.finditer(text):
        start = head.end()
        while match := PAIR.match(text, start):
            code = match.group("code")
            label = match.group("label").strip(" \t「」『』`\x22'")
            if not label or "://" in label:
                break
            mappings.append(
                {
                    "column": head.group("column"),
                    "code": code,
                    "label": label,
                    "start": match.start(),
                    "end": match.end(),
                    "quote": match.group(),
                }
            )
            separator = SEPARATOR.match(text, match.end())
            if not separator:
                break
            start = separator.end()
    return mappings


def dictionary_claims(raw, scope):
    authored = declared_mappings(raw, scope)
    if not authored:
        return [], []
    note = scope["source_note"]
    source = declared_mappings(note, scope)
    urls = sorted({m.group().rstrip(".,;") for m in SOURCE_URL.finditer(note)})
    checks, issues = [], []
    for declaration in authored:
        candidates = [
            row
            for row in source
            if (row["column"].casefold(), row["code"])
            == (declaration["column"].casefold(), declaration["code"])
        ]
        meanings = {row["label"] for row in candidates}
        if meanings == {declaration["label"]} and len(urls) == 1:
            entry = candidates[0]
            checks.append(
                {
                    **declaration,
                    "dictionary_start": entry["start"],
                    "dictionary_end": entry["end"],
                    "dictionary_quote": entry["quote"],
                    "dictionary_sha256": sha256(note.encode()).hexdigest(),
                    "source_url": urls[0],
                }
            )
        else:
            issues.append(
                {
                    **declaration,
                    "issue": "DICTIONARY_CODE_MISMATCH"
                    if candidates
                    else "DICTIONARY_CODE_UNVERIFIED",
                    "dictionary_matches": candidates,
                    "repair": "核對該欄的代碼、正式標籤及核准來源。如無唯一且有出處的定義，請省略未核實的對應。",
                }
            )
    return checks, issues
