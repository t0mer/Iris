import json

import pytest

from app.classify.quality import metrics, paired_comparison, promotion_gate


def rows():
    return [
        {
            "conversation": f"private-chat-{i}",
            "human": verdict,
            "baseline": verdict,
            "candidate": verdict,
            "language": "he",
        }
        for i, verdict in enumerate(["harmful"] * 50 + ["safe"] * 50)
    ]


def report(data):
    return {
        "source": "held_out_human_reviews",
        "model_identity": {"classifier": "a" * 64},
        "expected": len(data),
        "evaluated": len(data),
        "failures": 0,
        "baseline": metrics(data, "baseline"),
        "candidate": metrics(data, "candidate"),
        "paired": paired_comparison(data, unit="conversation"),
        "languages": {
            lang: {
                stage: metrics([r for r in data if r["language"] == lang], stage)
                for stage in ["baseline", "candidate"]
            }
            for lang in ["he", "en"]
        },
    }


def improved():
    data = rows()
    for r in data[:5]:
        r["baseline"] = "safe"
    return data


def test_independent_conversation_improvements_can_qualify_without_auto_promotion():
    result = report(improved())
    assert result["paired"]["one_sided_p"] == 1 / 32
    assert promotion_gate(result) == {"eligible": True, "reasons": [], "automatic_promotion": False}
    assert "private-chat" not in json.dumps(result)


def test_repeated_wins_in_one_conversation_cannot_manufacture_significance():
    data = improved()
    for r in data[:5]:
        r["conversation"] = "one-private-conversation"
    result = report(data)
    assert result["paired"]["improved"] == 1
    assert result["paired"]["one_sided_p"] == 0.5
    assert not promotion_gate(result)["eligible"]


def test_apparent_single_case_improvement_is_insufficient():
    data = rows()
    data[0]["baseline"] = "safe"
    assert not promotion_gate(report(data))["eligible"]


def test_review_workload_is_not_hidden_as_reduced_false_alerts():
    data = improved()
    data[50]["candidate"] = "review"
    result = report(data)
    assert result["candidate"]["safe_review"] == 1
    assert "The candidate increases manual review workload." in promotion_gate(result)["reasons"]


def test_language_regression_is_blocked_despite_better_overall_result():
    data = rows()
    for i, r in enumerate(data):
        r["language"] = "he" if i % 50 < 25 else "en"
    for r in data[:10]:
        r["baseline"] = "safe"
    data[25]["candidate"] = "safe"
    result = report(data)
    assert result["candidate"]["false_negative"] < result["baseline"]["false_negative"]
    assert result["paired"]["one_sided_p"] < 0.05
    assert (
        "The candidate must not regress in any evaluated language."
        in promotion_gate(result)["reasons"]
    )


@pytest.mark.parametrize("value", [False, float("nan"), -1, 0.1])
def test_invalid_or_insignificant_statistics_are_blocked(value):
    result = report(improved())
    result["paired"]["one_sided_p"] = value
    assert not promotion_gate(result)["eligible"]


def test_incomplete_mismatched_or_missing_language_evidence_is_blocked():
    result = report(improved())
    assert not promotion_gate({**result, "expected": 101})["eligible"]
    assert not promotion_gate({**result, "languages": {}})["eligible"]
    result["candidate"]["samples"] = 99
    assert not promotion_gate(result)["eligible"]


def test_unknown_human_or_model_verdict_is_never_assumed_safe():
    with pytest.raises(ValueError):
        metrics([{"human": "review", "candidate": "safe"}], "candidate")
    with pytest.raises(ValueError):
        metrics([{"human": "safe", "candidate": "unknown"}], "candidate")


@pytest.mark.parametrize("identity", [None, {}, {"classifier": "model-name"}, {"classifier": True}])
def test_promotion_requires_valid_model_provenance(identity):
    result = report(improved())
    result["model_identity"] = identity
    gate = promotion_gate(result)
    assert not gate["eligible"]
    assert "Verified model digests are required before promotion." in gate["reasons"]
