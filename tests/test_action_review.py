from copy import deepcopy
from types import SimpleNamespace as NS

from rde.interface.mcp.action_review import compare_scalar, delivery, review

DOC = {"cohorts": [{"unit": "hours", "mean": 3.146, "n": 8}]}


def test_dialogue_locates_an_exact_quote_and_native_value_without_rewriting_it():
    claim = {
        "quote": "3.15 hours",
        "artifact_id": "a" * 64,
        "sha256": "b" * 64,
        "pointer": "/cohorts/0/mean",
        "value": 3.15,
        "decimals": 2,
    }
    text = "Observed mean was 3.15 hours."

    def read(project, artifact, revision):
        return DOC

    passed = review("project", text, [claim], reader=read)
    assert passed["disposition"] == "continue" and passed["coverage"] == "submitted_claims_only"
    wrong = deepcopy(claim)
    wrong["pointer"] = "/cohorts/0/n"
    rejected = review("project", text, [wrong], reader=read)
    assert rejected["issues"] == ["VALUE_MISMATCH"] and "text" not in rejected
    assert review("project", "Reported 4.80 hours", [dict(claim, quote="4.80 hours")], reader=read)[
        "issues"
    ] == ["VALUE_NOT_IN_QUOTE"]
    assert review("project", text, [], reader=read)["issues"] == ["NO_EVIDENCE_CLAIMS"]


def test_stale_receipt_refuses_credit_and_does_not_replace_result():
    def stale(*args):
        raise ValueError("STALE_ARTIFACT")

    claim = {
        "quote": "8 people",
        "artifact_id": "a" * 64,
        "sha256": "b" * 64,
        "pointer": "/n",
        "value": 8,
    }
    assert review("project", "8 people", [claim], reader=stale)["issues"] == [
        "STALE_OR_INVALID_REFERENCE"
    ]
    assert not compare_scalar(True, 1)
    assert not compare_scalar(8, 8.3, 0)


def test_delivery_links_an_error_to_the_invocation_without_leaking_arguments():
    result = NS(
        invocation_id="inv",
        tool="test",
        status="error",
        error=NS(code="SCOPE"),
        context=NS(sources=[]),
        artifacts=[],
    )
    feedback = delivery(result, {"secret": "private phrase"})
    assert feedback["disposition"] == "repair" and feedback["error_code"] == "SCOPE"
    assert "private phrase" not in repr(feedback) and len(feedback["input_sha256"]) == 64
