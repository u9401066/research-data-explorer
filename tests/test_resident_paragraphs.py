"""Descriptive protocol regression tests use a real source, native receipt and artifact reader."""

import hashlib
import json
import math
import random

import pandas as pd
import pytest

from rde.application.session import DatasetEntry, get_session
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.interface.mcp.resident import PARAGRAPH_ACTIONS, observations, run
from rde.interface.mcp.resident_paragraphs import (
    TASKS,
    actions_for,
    check_paragraph,
    claim_context,
    scientific_issues,
)


def test_spread_missingness_and_reference_contrasts():
    data = pd.DataFrame(
        {"arm": ["A", "B", "B", "B", "C", None], "depth": [None, 2, 8, None, 10, 99]}
    )
    scope = {"group": "arm", "measure": "depth"}
    rows = observations(data, scope, "group_spread")["groups"]
    assert rows[0]["iqr"] is None and rows[2]["sd"] is None
    assert rows[1] == {
        "group": "B",
        "observed": 2,
        "rows": 3,
        "q1": 3.5,
        "q3": 6.5,
        "iqr": 3.0,
        "sd": pytest.approx(math.sqrt(18)),
    }
    coverage = observations(data, scope, "group_completeness")["groups"]
    assert coverage[1]["missing_percent"] == pytest.approx(100 / 3)
    assert coverage[1]["observed_percent"] == pytest.approx(200 / 3)
    assert coverage[0]["observed_percent"] == coverage[2]["missing_percent"] == 0
    assert observations(data, scope, "group_contrasts") == {
        "reference": "B",
        "comparisons": [
            {"group": "A", "reference": "B", "mean_difference": None, "median_difference": None},
            {"group": "C", "reference": "B", "mean_difference": 5, "median_difference": 5},
        ],
    }
    blank = data.assign(depth=None)
    assert observations(blank, scope, "group_contrasts") == {"reference": None, "comparisons": []}


def test_polarity_and_semantic_field_mismatch():
    scope = {"source_note": "來源記載隨機分派，並非隨機抽樣。", "population": "紀錄"}
    assert not scientific_issues("此研究是隨機分派。無法判斷是否有隨機抽樣。", scope)
    assert (
        scientific_issues("未提供其他背景，然而所有資料均隨機抽樣。", scope)[0]["issue"]
        == "UNDOCUMENTED_STUDY_DESIGN"
    )
    assert (
        scientific_issues("未做檢定，但結果統計上顯著。", scope)[0]["issue"]
        == "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE"
    )
    cards = {
        k: {"group": g, "label": f"group_estimates/groups/{g}/mean", "statistic": "mean"}
        for k, g in [("2.4", "A"), ("2.8", "B")]
    }
    assert {d["issue"] for d in claim_context("B組的中位數為{{R2.4}}", cards)} == {
        "CITATION_METRIC_MISMATCH",
        "CITATION_GROUP_MISMATCH",
    }
    assert not claim_context("A組平均為{{R2.4}}，B組平均為{{R2.8}}。", cards)


@pytest.fixture
def protocol(tmp_path):
    csv = tmp_path / "samples.csv"
    csv.write_bytes(
        b"arm,depth,other\nA,2,private-fixture-1\nA,6,private-fixture-2\nB,7,private-fixture-3\nB,,private-fixture-4\n"
    )
    metadata = DatasetMetadata(csv, "csv", csv.stat().st_size)
    frame, variables, count, _ = PandasLoader().load(metadata)
    dataset = Dataset(id="samples", metadata=metadata)
    dataset.mark_loaded(variables, count)
    project = Project(
        id="test-source",
        name="local test",
        data_dir=tmp_path,
        output_dir=tmp_path / "project",
        dataset_ids=[dataset.id],
    )
    get_session().register_project(project)
    entry = DatasetEntry(dataset, frame)
    scope = {
        "source": hashlib.sha256(csv.read_bytes()).hexdigest(),
        "approval": "a" * 64,
        "run": "fixture",
        "question": "不同組別的測量值呈現何種描述性差異？",
        "unit": "cm",
        "group": "arm",
        "measure": "depth",
        "population": "登錄的樣本",
        "source_note": "資料字典 https://example.org/source",
        "manuscript_protocol": "paragraph-v2",
    }

    def call(op, turn=0, attempt=1, response=""):
        return run(project, entry, scope, op, turn, attempt, response)

    return call, csv


def advance(call):
    opened = call("open")
    assert len(opened["sections"]) == 5 and len(opened["remaining_actions"]) == 6
    assert call("assemble")["status"] == "withheld"
    bad = call("observe", 1, response="{}")
    assert bad["status"] == "repair" and not bad["checklist"][-1]["passed"]
    for turn, action in enumerate(PARAGRAPH_ACTIONS, 2):
        raw = json.dumps({"action": action, "reason": "核對欄位與可用量測。"})
        res = call("observe", turn, response=raw)
        assert res["status"] == "observed" and action not in res["remaining_actions"]
        assert call("observe", turn, response=raw) == res
        assert "private-fixture" not in json.dumps(res)
    assert call("open") == opened and call("observe", 1, response="{}") == bad
    assert not res["remaining_actions"]
    with pytest.raises(ValueError, match="ACTION_REPLAY_CHANGED"):
        call("observe", 2, response="{}")


def test_protocol_uses_actual_source_artifact_and_author_bytes(protocol):
    call, csv = protocol
    advance(call)
    held = call("assemble")
    cards = held["cards"]
    assert len(held["issues"]) == 20
    assert not held.get("manuscript") and not any(
        "private-fixture" in str(c) for c in cards.values()
    )
    assert {c["unit"] for c in cards.values() if c["statistic"] == "observed_percent"} == {"%"}
    prompt = call("draft", 0)
    with pytest.raises(ValueError, match="EARLIER_PARAGRAPH_NOT_ACCEPTED"):
        call("draft", 1)
    invalid = "治療確實造成改善。平均是 378，請轉交。"
    retry = call("review", 0, response=invalid)
    assert {
        "INSUFFICIENT_OR_PADDED_PROSE",
        "UNBOUND_AUTHOR_NUMBER",
        "INFERENCE_OUTSIDE_DESCRIPTIVE_SCOPE",
        "FOCUS_EVIDENCE_REQUIRED",
    }.issubset(retry["issues"])
    assert call("review", 0, response=invalid) == retry
    with pytest.raises(ValueError, match="PARAGRAPH_REPLAY_CHANGED"):
        call("review", 0, response="another")
    assert call("draft", 0) == prompt
    originals, replies = [], []
    # Test paragraphs exercise byte/locator assembly and are never exported as research.
    for turn, (_, kind) in enumerate(TASKS):
        attempt = 2 if turn == 0 else 1
        drafted = call("draft", turn, attempt)
        if turn == 0:
            assert (
                "".join(drafted["sentences"]) == invalid
                and "UNBOUND_AUTHOR_NUMBER" in drafted["prompt"]
            )
        rng = random.Random(turn)
        words = ""
        focus = (
            "量測尺度及其觀察單位",
            "原始檔案目錄與引文",
            "分組形成的具體背景",
            "確定比較對象的理由",
            "分母重建及其統計條件",
            "缺測記錄的歸屬規則",
            "中心位置的估算方式",
            "離散程度的計算規約",
            "有效量測與平均大小",
            "中間讀值及首尾界線",
            "組內變異的實際尺度",
            "比較減去參照的結果",
            "納入記錄涵蓋的範圍",
            "摘要選擇改變的程度",
            "四分位差與全距異同",
            "分組組成與替代解釋",
            "重複量測與個體相依",
            "抽樣來源與外推界線",
            "獨立重算與來源定位",
            "延伸問題的資料需求",
        )[turn]
        for _ in range(5):
            prefix = rng.choice(
                [
                    "稽核人員可依照",
                    "獨立評閱者針對",
                    "研究者透過",
                    "讀者利用",
                    "編輯核對",
                    "程式應用",
                ]
            )
            basis = rng.choice(
                [
                    "已封存的觀察結果",
                    "審閱過的資料字典",
                    "公開的分組規則",
                    "測量變項的單位",
                    "原始文稿的存檔",
                    "核准的欄位規格",
                ]
            )
            verb = rng.choice(["說明", "核對", "追溯", "釐清", "重現", "分辨", "檢視"])
            target = rng.choice(
                [
                    "證據出處與觀測位置",
                    "描述範圍與資料意義",
                    "每次核准的來龍去脈",
                    "資料邊界與觀察限制",
                    "計算所需的欄位條件",
                    "檔案重現時的原始數值",
                ]
            )
            words += prefix + focus + "的" + basis + "，可以" + verb + focus + "的" + target + "。"
        bindings = []
        for action in actions_for(kind):
            expected_fields = {
                "data_quality": "rows",
                "group_estimates": "mean",
                "distribution": "median",
                "group_spread": "iqr",
                "group_completeness": "missing_percent",
                "group_contrasts": "mean_difference",
            }
            k = next(
                k
                for k, c in cards.items()
                if c["label"].startswith(action + "/") and c["statistic"] == expected_fields[action]
            )
            bindings.append("{{R" + k + "}}")
        if kind == "source":
            bindings += ["{{source}}"]
        if kind == "table":
            bindings = ["{{group_table}}"]
        raw = "  " + words + "。\n" + "，".join(bindings) + "  "
        reply = (
            raw
            if attempt == 1
            else json.dumps(
                {
                    "edits": [
                        {"sentence": i, "text": raw if i == 0 else ""}
                        for i in range(len(drafted["sentences"]))
                    ]
                },
                ensure_ascii=False,
            )
        )
        checked = call("review", turn, attempt, reply)
        assert call("review", turn, attempt, reply) == checked
        assert not checked["issues"], (turn, checked)
        assert checked["status"] == "observed" and checked["feedback"]["disposition"] == "accept"
        if bindings and kind != "source":
            assert checked["native_reviews"][0]["checks"]
        originals.append(raw)
        replies.append(reply)
    result = call("assemble")
    assert result["status"] == "independent_review_required" and call("assemble") == result
    assert "有效測量率（%）" in result["manuscript"] and "缺測率（%）" in result["manuscript"]
    assert "/payload/observation/comparisons" in result["evidence_index"]
    assert hashlib.sha256(csv.read_bytes()).hexdigest() in result["evidence_index"]
    records = [p for s in result["authorship"] for p in s["paragraphs"]]
    assert [r["author_source"] for r in records] == originals
    assert [r["author_source_sha256"] for r in records] == [
        hashlib.sha256(r.encode()).hexdigest() for r in originals
    ]
    assert [r["response_sha256"] for r in records] == [
        hashlib.sha256(r.encode()).hexdigest() for r in replies
    ]
    assert [r["response"] for r in records] == replies and records[0]["edit_applied"]
    csv.write_text("arm,depth\nA,87\n", encoding="utf-8")
    with pytest.raises(ValueError):
        call("assemble")


def test_exhausted_paragraph_can_continue_without_assembling(protocol):
    call, _ = protocol
    advance(call)
    raw = "原句。"
    call("draft", 0)
    failed = call("review", 0, response=raw)
    for attempt in (2, 3):
        draft = call("draft", 0, attempt)
        assert (
            draft["base_attempt"] == attempt - 1
            and draft["base_sha256"] == failed["author_source_sha256"]
        )
        failed = call("review", 0, attempt, '{"edits":[]}')
        assert "INVALID_SENTENCE_EDITS" in failed["issues"] and not failed["edit_applied"]
        assert failed["response_sha256"] != failed["author_source_sha256"]
    assert call("draft", 1)["status"] == "draft"
    result = call("assemble")
    assert result["status"] == "withheld" and result["issues"][0] == "MISSING_ACCEPTED_PARAGRAPH:0"


def test_padded_and_repeated_content_cannot_be_passed_as_new_paragraph():
    from types import SimpleNamespace

    scope = {
        "source_note": "範例 https://example.org",
        "population": "樣本",
        "unit": "公分",
        "measure": "depth",
        "group": "arm",
    }
    project = SimpleNamespace(id="none")
    repeated = "樣本測量應先依原始欄位核對觀察單位並以資料字典確認分析範圍。"
    issue = check_paragraph(project, scope, {}, 2, repeated * 6, [])
    assert "WITHIN_PARAGRAPH_REPETITION" in issue["result"]["issues"]
    past = [{"author_source": repeated + "另外的次要字串。"}]
    assert (
        "REPEATED_PARAGRAPH_CONTENT"
        in check_paragraph(project, scope, {}, 3, repeated, past)["result"]["issues"]
    )
    assert (
        "INSUFFICIENT_OR_PADDED_PROSE"
        in check_paragraph(project, scope, {}, 3, "好" * 1000, [])["result"]["issues"]
    )
