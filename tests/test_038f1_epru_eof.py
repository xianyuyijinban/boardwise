"""038F1 — the empty body whose terminator is missing at end of stream.

A real V4 (`.eprj3`) export ends every document stream with ``{envelope}||``:
an **empty body** that also lacks the final record terminator. The framing
layer stripped the trailing ``|`` unconditionally, which ate the *second* half
of the field separator and left ``{envelope}|`` — "no separator", counted
malformed. Every page and the PCB reported one damaged line, and the offline
checkup called a healthy export "possibly truncated or corrupt".

The three shapes that must stay apart:

* ``{envelope}|||``  — empty body, terminated            -> ``empty_body_records``
* ``{envelope}||``   — empty body, terminator missing    -> ``empty_body_records``
* ``{envelope}||{body`` — truncated non-empty body       -> ``malformed_records``

Nothing here is a real project file: the lines are synthesized, and the counts
of the actual sample are re-measured in ``outputs/review/v4-eof-frame.md``.
"""

from __future__ import annotations

from boardwise.core.geometry import ParseStats
from boardwise.parsers.epru_stream import (
    FIELD_SEP,
    iter_epru_records,
    split_documents,
)

HEAD = '{"type":"DOCHEAD","ticket":0,"id":"d1"}'
HEAD_BODY = '{"docType":"PCB","uuid":"u1"}'


def _lines(*rows: str) -> str:
    return "\n".join(rows)


def _stats(text: str) -> tuple[list, ParseStats]:
    stats = ParseStats()
    records = list(iter_epru_records(text, stats))
    return records, stats


# --------------------------------------------------------------------------
# the shapes that were already fine
# --------------------------------------------------------------------------


def test_a_terminated_record_decodes_as_it_always_did():
    records, stats = _stats(_lines('{"type":"VIA","ticket":1,"id":"v1"}||{"netName":"A"}|'))

    assert [(r.type, r.id, r.body) for r in records] == [("VIA", "v1", {"netName": "A"})]
    assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (1, 0, 0)


def test_a_final_record_without_its_terminator_decodes_the_same():
    terminated, _ = _stats(_lines(f'{{"type":"VIA","ticket":1,"id":"v1"}}{FIELD_SEP}'
                                  f'{{"netName":"A"}}|'))
    unterminated, stats = _stats(_lines(f'{{"type":"VIA","ticket":1,"id":"v1"}}{FIELD_SEP}'
                                        f'{{"netName":"A"}}'))

    assert [(r.type, r.id, r.body) for r in unterminated] == [
        (r.type, r.id, r.body) for r in terminated
    ]
    assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (1, 0, 0)


def test_a_terminated_empty_body_is_counted_and_skipped():
    records, stats = _stats(_lines(f'{{"type":"ATTR","ticket":7,"id":"a1"}}{FIELD_SEP}|'))

    assert [(r.type, r.id, r.body) for r in records] == [("ATTR", "a1", None)]
    assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (1, 0, 1)


# --------------------------------------------------------------------------
# the shape 038F1 fixes
# --------------------------------------------------------------------------


def test_the_v4_end_of_stream_empty_body_is_counted_not_malformed():
    records, stats = _stats(_lines(f'{{"type":"ATTR","ticket":7,"id":"a1"}}{FIELD_SEP}'))

    assert [(r.type, r.ticket, r.id, r.body) for r in records] == [("ATTR", 7, "a1", None)]
    assert stats.malformed_records == 0, "an empty body at EOF is not a damaged line"
    assert stats.empty_body_records == 1
    assert stats.total_records == 1, "the count/line-number contract does not drift"


def test_a_glued_stream_ending_a_page_with_that_shape_is_clean_too():
    """`eprj3` glues page files with newlines, so each page's EOF is mid-stream.

    A reader that only forgave the **last physical line** would still report one
    damaged record per page after the first — which is exactly what the V4 sample
    showed (P1 and P2 both end this way, and the merged stream counted two).
    """
    page = _lines(
        f'{HEAD}{FIELD_SEP}{HEAD_BODY}|',
        f'{{"type":"ATTR","ticket":2,"id":"a1"}}{FIELD_SEP}',
    )
    records, stats = _stats(_lines(page, page))

    assert [r.id for r in records] == ["d1", "a1", "d1", "a1"]
    assert [r.line_no for r in records] == [0, 1, 2, 3]
    assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (4, 0, 2)


def test_the_document_split_survives_the_new_shape():
    text = _lines(
        f'{HEAD}{FIELD_SEP}{HEAD_BODY}|',
        f'{{"type":"VIA","ticket":1,"id":"v1"}}{FIELD_SEP}{{"netName":"A"}}|',
        f'{{"type":"META","ticket":2,"id":"m1"}}{FIELD_SEP}',
    )
    stats = ParseStats()
    documents = split_documents(text, stats)

    assert [doc.doc_type for doc in documents] == ["PCB"]
    assert [r.type for r in documents[0].records] == ["DOCHEAD", "VIA", "META"]
    assert documents[0].records[-1].body is None
    assert (stats.malformed_records, stats.empty_body_records) == (0, 1)


# --------------------------------------------------------------------------
# what must keep failing
# --------------------------------------------------------------------------


def test_a_truncated_non_empty_body_is_still_malformed():
    cases = [
        f'{{"type":"VIA","ticket":1}}{FIELD_SEP}{{"netName":"A"',   # no terminator, cut
        f'{{"type":"VIA","ticket":1}}{FIELD_SEP}{{"netName":"A"|',  # terminated, cut
        f'{{"type":"VIA","ticket":1}}{FIELD_SEP}{{"name":"a|',       # cut right after a "|"
        f'{{"type":"VIA","ticket":1}}{FIELD_SEP}',                   # separator only, see below
    ]
    for case in cases[:3]:
        records, stats = _stats(_lines(case))
        assert records == [], case
        assert (stats.total_records, stats.malformed_records) == (1, 1), case

    # The separator-only line is the empty body, not a truncated one: nothing of
    # the body ever arrived, so there is no payload to call damaged.
    records, stats = _stats(_lines(cases[3]))
    assert [(r.type, r.body) for r in records] == [("VIA", None)]
    assert (stats.malformed_records, stats.empty_body_records) == (0, 1)


def test_a_record_missing_the_separator_is_still_malformed():
    for case in ('{"type":"VIA","ticket":1}|', '{"type":"VIA","ticket":1}'):
        records, stats = _stats(_lines(case))
        assert records == [], case
        assert (stats.total_records, stats.malformed_records) == (1, 1), case


def test_a_broken_envelope_is_malformed_in_both_empty_body_shapes():
    for case in ('{oops||', '{oops|||', '{oops||{"a":1}|', '[1,2]||', '[1,2]|||'):
        records, stats = _stats(_lines(case))
        assert records == [], case
        assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (
            1, 1, 0), case


def test_the_terminator_is_not_simply_optional_everywhere():
    """The fix must not become "accept every line that lacks a terminator".

    A line with no separator at all is what truncation looks like; the empty-body
    tolerance keys on the *separator being present*, not on the terminator being
    absent.
    """
    text = _lines(
        f'{HEAD}{FIELD_SEP}{HEAD_BODY}|',
        f'{{"type":"VIA","ticket":1,"id":"v1"}}{FIELD_SEP}{{"netName":"A"}}|',
        '{"type":"VIA","ticket":2,"id":"v2"}',
        f'{{"type":"VIA","ticket":3,"id":"v3"}}{FIELD_SEP}',
    )
    records, stats = _stats(text)

    assert [r.id for r in records] == ["d1", "v1", "v3"]
    assert records[-1].body is None
    assert (stats.total_records, stats.malformed_records, stats.empty_body_records) == (4, 1, 1)
    assert stats.records_by_type == {"DOCHEAD": 1, "VIA": 2}
