"""Tests for the annotation-set loader (task 011a)."""

from __future__ import annotations

import pytest

from boardwise.core.annotations import (
    SCHEMA,
    AnnotationError,
    annotations_from_json,
    load_annotations,
)


def _valid_body() -> dict:
    return {
        "schema": SCHEMA,
        "board": "toy-board",
        "source": "tests/fixtures/toy.epro2",
        "items": [
            {
                "ref": "C1",
                "rule_hint": "some-rule",
                "kind": "defect",
                "severity": "WARN",
                "note": "wrong value",
            },
            {
                "ref": "X1",
                "rule_hint": "some-rule",
                "kind": "exception",
                "note": "grounded case",
            },
            {
                "ref": "U9",
                "rule_hint": "",
                "kind": "query",
                "note": "what is U9?",
            },
        ],
    }


def test_a_valid_set_round_trips():
    aset = annotations_from_json(_valid_body(), "<test>")
    assert aset.board == "toy-board"
    assert aset.split_default == "dev"
    assert [item.kind for item in aset.items] == ["defect", "exception", "query"]
    assert not aset.is_reviewed


def test_the_default_split_reaches_items_that_do_not_override_it():
    body = _valid_body()
    body["split_default"] = "holdout"
    aset = annotations_from_json(body, "<test>")
    assert all(item.effective_split == "holdout" for item in aset.items)
    assert aset.items_for_split("dev") == []
    assert len(aset.items_for_split("all")) == 3


def test_a_per_item_split_overrides_the_default():
    body = _valid_body()
    body["items"][0]["split"] = "holdout"
    aset = annotations_from_json(body, "<test>")
    assert [item.effective_split for item in aset.items] == ["holdout", "dev", "dev"]


def test_unknown_top_level_keys_are_rejected():
    body = _valid_body()
    body["extra"] = 1
    with pytest.raises(AnnotationError, match="unknown key"):
        annotations_from_json(body, "<test>")


def test_a_wrong_schema_is_rejected():
    body = _valid_body()
    body["schema"] = "boardwise-review-annotations/0"
    with pytest.raises(AnnotationError, match="schema"):
        annotations_from_json(body, "<test>")


@pytest.mark.parametrize("kind", ["defect", "exception"])
def test_defects_and_exceptions_must_name_a_rule(kind):
    body = _valid_body()
    for item in body["items"]:
        if item["kind"] == "query":
            body["items"].remove(item)
            break
    body["items"] = [body["items"][0]]
    body["items"][0]["kind"] = kind
    if kind == "exception":
        body["items"][0]["severity"] = ""
    body["items"][0]["rule_hint"] = ""
    with pytest.raises(AnnotationError, match="rule_hint"):
        annotations_from_json(body, "<test>")


def test_a_defect_must_state_an_expected_severity():
    body = _valid_body()
    body["items"] = [body["items"][0]]
    body["items"][0]["severity"] = ""
    with pytest.raises(AnnotationError, match="severity"):
        annotations_from_json(body, "<test>")


def test_only_defects_carry_an_expected_severity():
    body = _valid_body()
    body["items"] = [body["items"][1]]  # the exception
    body["items"][0]["severity"] = "ERROR"
    with pytest.raises(AnnotationError, match="severity"):
        annotations_from_json(body, "<test>")


def test_severity_vocabulary_is_enforced():
    body = _valid_body()
    body["items"] = [body["items"][0]]
    body["items"][0]["severity"] = "CRITICAL"
    with pytest.raises(AnnotationError, match="severity"):
        annotations_from_json(body, "<test>")


def test_unknown_kinds_and_splits_are_rejected():
    body = _valid_body()
    body["items"][0]["kind"] = "hunch"
    with pytest.raises(AnnotationError, match="kind"):
        annotations_from_json(body, "<test>")
    body = _valid_body()
    body["items"][0]["split"] = "sometimes"
    with pytest.raises(AnnotationError, match="split"):
        annotations_from_json(body, "<test>")


def test_duplicate_records_are_rejected():
    body = _valid_body()
    body["items"].append(dict(body["items"][0]))
    with pytest.raises(AnnotationError, match="duplicate"):
        annotations_from_json(body, "<test>")


def test_every_record_must_carry_a_note():
    body = _valid_body()
    body["items"][0]["note"] = "  "
    with pytest.raises(AnnotationError, match="note"):
        annotations_from_json(body, "<test>")


def test_load_annotations_reads_the_real_file():
    from pathlib import Path

    aset = load_annotations(Path("reviewsets/ch340g_golden.json"))
    assert aset.board == "ch340g-golden"
    kinds = sorted(item.kind for item in aset.items)
    # 011d sec.1 oracle rulings: the V3 query became the second defect (the
    # board never powered up, so the manual's 3.3V-mode wiring governs).
    assert kinds == ["defect", "defect", "exception", "exception", "exception"]
    # The draft ships unreviewed: the report must say so until Yue signs it.
    assert aset.reviewed_by == ""


def test_load_annotations_reads_the_bishe_a_and_b_rulings():
    """011e sec.3 rulings A1/A2 plus section B (2026-09-19), signed 2026-09-20.

    The contract worth pinning is that the records and the board agree: the refs
    were derived from the parser and from the rule's own output, so a ref that
    no longer shows up (or one that shows up and the set forgot) has to fail
    here rather than quietly shrink the measurement. 014 landed the three final
    rulings and the signature: the U1.12 defect (unregistered hint) and the X1
    exception joined the items, the "B3 still pending" observation left, and
    the DRAFT stamp is gone. The holdout default stays -- a real board never
    enters rule tuning's sight, signed or not.
    """
    from pathlib import Path

    from boardwise.core.parts import load_parts
    from boardwise.engines.review_eval import load_board_model
    from boardwise.rules.decap import DecapRequiredCaps
    from boardwise.rules.params import ValueMpnMatch

    aset = load_annotations(Path("reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json"))
    # 014: the three final rulings landed and the set is signed -- the DRAFT
    # stamp must be gone now that every line of section B is ruled.
    assert aset.reviewed_by == "Yue Xiangyu"
    assert aset.reviewed_at == "2026-09-20"
    assert aset.split_default == "holdout"

    defects = [item for item in aset.items if item.kind == "defect"]
    exceptions = [item for item in aset.items if item.kind == "exception"]
    # 011e: 30 duplicates + B1. 014 added the U1.12 defect (unregistered hint)
    # and the X1 exception, bringing 31 -> 32 and 10 -> 11.
    assert len(defects) == 32 and len(exceptions) == 11
    duplicates = [item for item in defects if item.rule_hint == "conn-duplicate-designators"]
    b1 = [item for item in defects if item.rule_hint == "decap-required-caps"]
    assert len(duplicates) == 30 and len(b1) == 1
    assert {item.severity for item in duplicates} == {"ERROR"}
    assert b1[0].severity == "WARN" and b1[0].ref == "U11"
    assert {item.severity for item in exceptions} == {""}, (
        "only defects carry an expected severity (loader default is empty)"
    )
    osc = [i for i in defects if i.rule_hint == "conn-osc-pin-net"]
    assert len(osc) == 1 and osc[0].ref == "U1" and osc[0].severity == "ERROR"
    assert osc[0].effective_split == "holdout"
    x1 = [i for i in exceptions if i.rule_hint == "xtal-load-caps"]
    assert len(x1) == 1 and x1[0].ref == "X1"
    # Escaped on purpose: the oracle's own words for the cause ("an oversight
    # at the time"), quoted verbatim in every A1 record.
    assert all("\u5f53\u65f6\u758f\u5ffd" in item.note for item in duplicates)

    # The B2/B4/B5 rulings are observations, not item records. 011e landed
    # nine; 014 deleted the "B3 still pending" one and rewrote the opener, so
    # eight remain and none of them calls section B open any more.
    assert len(aset.observations) == 8
    topics = " ".join(o.topic for o in aset.observations)
    assert "B2 ruled" in topics and "B4 ruled" in topics and "B5 ruled" in topics
    assert "still pending" not in topics
    # 014: B2's ref list shrank 5 -> 3 after the 013 parser fix -- the two
    # dropped refs must not creep back into the topic line.
    b2 = next(o for o in aset.observations if "B2 ruled" in o.topic)
    assert "(U1, U8, USB1)" in b2.topic
    assert "U7" not in b2.topic and "U6" not in b2.topic

    model = load_board_model(aset.source)
    assert sorted(item.ref for item in duplicates) == sorted(
        model.duplicate_designators
    )
    # The 10 mpn-exception refs are exactly the findings the rule reports, so
    # the two sides cannot drift apart from the board they describe. (014: the
    # X1 exception is asserted separately above -- it pairs no finding by
    # design, the rule went quiet after 013.)
    mpn_exceptions = [i for i in exceptions if i.rule_hint == "param-value-mpn-match"]
    reported = {
        outcome.subject
        for outcome in ValueMpnMatch(
            library=load_parts("blocklib/parts.json")
        ).outcomes(model)
        if outcome.state == "VIOLATION"
    }
    assert sorted(item.ref for item in mpn_exceptions) == sorted(reported)
    # ... and the same for B1: the defect is the finding the rule reports.
    decap = DecapRequiredCaps(library=load_parts("blocklib/parts.json"))
    violations = [o for o in decap.outcomes(model) if o.state == "VIOLATION"]
    assert [o.subject for o in violations] == ["U11 pin5"]
