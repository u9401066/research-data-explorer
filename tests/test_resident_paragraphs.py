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
def protocol(tmp_path, request):
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
        "manuscript_protocol": getattr(request, "param", "paragraph-v2"),
    }

    if scope["manuscript_protocol"] == "paragraph-v3":
        scope["question"] += "\n依核准方向比較並解釋樣本涵蓋的限制。"
        scope["source_note"] += "。arm 欄：A=室內、B=室外。"
        scope["semantic_review"] = "required"

    def call(op, turn=0, attempt=1, response="", semantic_review=None):
        return run(
            project, entry, scope, op, turn, attempt, response, semantic_review=semantic_review
        )

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


def prose_fixture(turn):
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
    return words


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
        words = prose_fixture(turn)
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


@pytest.mark.parametrize("protocol", ["paragraph-v3"], indirect=True)
def test_v3_typed_intent_targeted_revision_fresh_revisit_and_external_review(protocol):
    from rde.interface.mcp.resident_reasoning import sentence_slices
    from rde.interface.mcp.action_review import digest

    call, csv = protocol
    opened = call("open")
    assert opened["protocol"] == "paragraph-v3" and opened["max_paragraph_attempts"] == 12
    request = opened["researcher_request"]
    assert request == "不同組別的測量值呈現何種描述性差異？\n依核准方向比較並解釋樣本涵蓋的限制。"

    def check_request(result):
        assert result["researcher_request"] == request
        assert result["prompt"].count(json.dumps(request, ensure_ascii=False)) == 1

    check_request(opened)
    bad = {
        "action": "group_estimates",
        "reason": "核對分組列數。",
        "purpose": "describe_group_means",
        "intended_fields": ["group_spread.iqr"],
    }
    assert call("observe", 1, response=json.dumps(bad))["issues"] == ["FIELD_OUTSIDE_ACTION"]
    options = opened
    for n, a in enumerate(PARAGRAPH_ACTIONS, 2):
        c = opened["capabilities"][a]
        evidence = {}
        if options["prior_evidence"]:
            evidence = {
                "evidence_use": "independent_check",
                "unresolved_question": "這項指定統計在各組的可用資料中呈現何種數值？",
                "prior_refs": [],
            }
            if n == 3:
                evidence.update(
                    evidence_use="follow_up", prior_refs=[next(iter(options["prior_evidence"]))]
                )
        raw = json.dumps(
            {
                "action": a,
                "intended_fields": [next(iter(c["fields"]))],
                "purpose": c["purpose"],
                "reason": "核對本次授權欄位的實際觀測。",
                **evidence,
            }
        )
        options = call("observe", n, response=raw)
        check_request(options)
        assert options["status"] == "observed", options["issues"]
        obs = options["observation_receipt"]
        assert obs["artifact_id"] and len(obs["sha256"]) == 64
        assert call("observe", n, response=raw)["observation_receipt"] == obs
        if evidence:
            assert options["intent"]["evidence_use"] == evidence["evidence_use"]

    def reviewer(reply, prose, which=None):
        def h(s):
            return hashlib.sha256(s.encode()).hexdigest()

        findings = (
            []
            if which is None
            else [
                {
                    "sentence": which,
                    "issue": "unverified_attribution",
                    "reason": "核對來源對這項主張的支持。",
                    "claim": sentence_slices(prose)[which][:6],
                    "basis": "scope.dictionary",
                }
            ]
        )
        output = json.dumps({"findings": findings}, ensure_ascii=False)
        sentences = [i for i, s in enumerate(sentence_slices(prose)) if s.strip()]
        reviews = []
        for i in sentences:
            raw = output if i == which else json.dumps({"findings": []}, ensure_ascii=False)
            reviews.append(
                {"sentence": i, "reviewer_response": raw, "reviewer_response_sha256": h(raw)}
            )
            if i == which:
                break
        return {
            **({"sentence_reviews": reviews} if 2 <= len(sentences) <= 4 else {}),
            "source_sha256": h(csv.read_text("utf-8")),
            "response_sha256": h(reply),
            "author_source_sha256": h(prose),
            "reviewer_response": output,
            "reviewer_response_sha256": h(output),
            "reviewer": "fixture-reviewer",
            "verdict": "repair" if findings else "accept",
            "diagnostics": [
                {
                    "issue": f["issue"],
                    "quote": sentence_slices(prose)[f["sentence"]],
                    "repair": f["reason"],
                }
                for f in findings
            ],
        }

    def payload(draft, turn):
        kind = TASKS[turn][1] if turn else "design"
        stats = {
            "data_quality": "rows",
            "group_completeness": "missing_percent",
            "group_estimates": "mean",
            "group_spread": "iqr",
            "distribution": "median",
            "group_contrasts": "mean_difference",
        }
        choices = (
            [
                next(k for k, c in draft["editor_evidence"].items() if c["statistic"] == stats[a])
                for a in actions_for(kind)
            ]
            if kind != "table"
            else []
        )
        return {
            "prose": "".join(sentence_slices(prose_fixture(turn))[:3]),
            "evidence_ids": choices,
            "group_table": kind == "table",
            "source_ids": [],
            "link_source": kind == "source",
        }

    for turn in range(20):
        draft = call("draft", turn)
        check_request(draft)
        assert draft["editorial_basis_version"] == 1
        assert draft["editorial_slices_version"] == 1
        assert draft["authored_evidence_version"] == 1
        assert draft["evidence_receipts"].keys() == draft["editor_evidence"].keys()
        assert draft["source_scope"]["method_definitions"]["iqr"]["formula"] == "q3 - q1"
        assert draft["source_scope"]["observed_group_levels"] == ["A", "B"]
        model = payload(draft, turn)
        if turn == 1:
            model["prose"] += "arm 欄位：A 表示室內、B 代表室外。"
        if turn == 9:
            model["prose"] += "A組中位數為四點零零 cm。"
        author = model["prose"]
        reply = json.dumps(model, ensure_ascii=False)
        verdict = reviewer(reply, author, 0 if turn == 0 else None)
        if turn == 0:
            with pytest.raises(ValueError, match="EXTERNAL_REVIEW_REQUIRED"):
                call("review", turn, response=reply)
        result = call("review", turn, response=reply, semantic_review=verdict)
        assert result["presentation"] == {k: v for k, v in model.items() if k != "prose"}
        if turn == 0:
            assert "EXTERNAL_SCIENTIFIC_REVIEW" in result["issues"]
            with pytest.raises(ValueError, match="REPLAY_CHANGED"):
                call("review", turn, response=reply, semantic_review=reviewer(reply, author))
            for attempt in (2, 3):
                draft = call("draft", turn, attempt)
                check_request(draft)
                t = draft["repair_target"]["sentence"]
                assert draft["repair_target"]["basis"] == "scope.dictionary"
                assert (
                    draft["response_schema"]["properties"]["edits"]["items"]["properties"][
                        "sentence"
                    ]["const"]
                    == t
                )
                bad = json.dumps(
                    dict(
                        result["presentation"], edits=[{"sentence": t + 1, "text": "錯誤的句位。"}]
                    ),
                    ensure_ascii=False,
                )
                result = call("review", turn, attempt, bad, reviewer(bad, author, 0))
                assert "INVALID_TARGETED_EDIT" in result["issues"] and not result["edit_applied"]
            with pytest.raises(ValueError, match="EARLIER_PARAGRAPH"):
                call("draft", turn, 4)
        else:
            assert result["status"] == "observed", result["diagnostics"]
            if turn == 9:
                check = result["native_number_checks"][0]
                assert check["verified"] and check["match_method"] == "selected_evidence"
                assert model["prose"][check["start"] : check["end"]] == "四點零零"
                assert (
                    check["native_value"] == 4
                    and check["pointer"].endswith("/median")
                    and len(check["sha256"]) == 64
                )
            if turn == 1:
                assert [m["code"] for m in result["dictionary_checks"]] == ["A", "B"]
            if turn == 8:
                assert (
                    len(result["native_null_checks"]) == 1
                    and result["native_null_checks"][0]["native_null"]
                )
    assert call("assemble")["status"] == "withheld"
    revisit = call("draft", 0, 4)
    check_request(revisit)
    assert revisit["mode"] == "author_json" and [
        r["turn"] for r in revisit["revisit_context"]["accepted_paragraphs"]
    ] == list(range(1, 20))
    model = payload(revisit, 0)
    reply = json.dumps(model, ensure_ascii=False)
    assert (
        "UNCHANGED_FAILED_CANDIDATE"
        in call("review", 0, 4, reply, reviewer(reply, model["prose"]))["issues"]
    )
    for attempt in range(5, 12):
        targeted = call("draft", 0, attempt)
        bad = json.dumps(
            dict(
                targeted["base_presentation"],
                edits=[
                    {
                        "sentence": targeted["repair_target"]["sentence"],
                        "text": "第一個完整句。另一個完整句。",
                    }
                ],
            ),
            ensure_ascii=False,
        )
        assert (
            "INVALID_TARGETED_EDIT"
            in call("review", 0, attempt, bad, reviewer(bad, model["prose"]))["issues"]
        )
    final = call("draft", 0, 12)
    target = final["repair_target"]["sentence"]
    parts = final["sentences"].copy()
    parts[target] = (
        "這次重訪以資料字典中的原始變項界定問題，具體交待量測單位和登錄資料可觀察的範圍，使讀者能夠區分檔案內的記錄和樣本以外的情況。"
    )
    last = json.dumps(
        dict(final["base_presentation"], edits=[{"sentence": target, "text": parts[target]}]),
        ensure_ascii=False,
    )
    assert call("review", 0, 12, last, reviewer(last, "".join(parts)))["status"] == "observed"
    result = call("assemble")
    assert result["status"] == "independent_review_required"
    assert result["manuscript"].splitlines()[0] == "# 不同組別的測量值呈現何種描述性差異？"
    assert "依核准方向比較並解釋樣本涵蓋的限制。" not in result["manuscript"]
    records = [p for group in result["authorship"] for p in group["paragraphs"]]
    assert records[0]["attempt"] == 12 and records[0]["base_attempt"] == 11
    assert all(p["attachments_sha256"] == digest(p["attachments"]) for p in records)
    tables = records[8]["attachments"][0]["rendered"]
    assert (
        sum(line.startswith("| ---") for line in tables.splitlines()) == 5
        and "無法估計[R" in tables
        and "4.00[R" in tables
    )
    assert (
        records[8]["author_source"] == "".join(sentence_slices(prose_fixture(8))[:3])
        and tables not in records[8]["author_source"]
    )


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
