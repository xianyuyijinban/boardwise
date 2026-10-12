"""Task 171 A: the capacitance reader eats a **trailing annotation** (``330uF 400V``).

The gap this batch closes was measured on llc: the schematic page states ``330uF
400V`` in ``C3`` / ``C4``'s Value field, and ``core.values.parse_capacitance_farads``
answered ``None`` for it, because :data:`_CAP_RE` requires the unit to **end** the
field. 164a worked around that in ``rules/pcb/foc.py::_farads_of`` with a two-stage
read (whole field first, the field's leading token second) and recorded the gap as
the measured one (``tests/test_164a_foc_view_truth.py`` asserts
``parse_capacitance_farads("330uF 400V") is None`` and calls it 「the measured gap」).

The proposal is that the **reader** owns that read, not one rule: 071 §2's 「one
verdict has one implementation」 is why the parsers live in ``core`` at all, and a
Value field carrying its voltage rating beside its capacitance is a shape every
consumer meets (compare / bom / params read the same fields foc does). So
:func:`parse_capacitance_farads` now reads the field's **leading token** when the
whole field is neither of its two grammars, and ``foc._farads_of`` is the delegation
it always claimed to be.

**What is pinned here, and the boundaries that are pinned as *refusals*.**

* read: ``<value> <annotation>`` — any whitespace-separated tail. The reading is
  the leading token's own reading, so this is not a second grammar: it is the same
  grammars handed the piece the decoders read at all (``core.values._too_long``'s
  own doctrine — the first whitespace-separated token is the piece a decoder looks
  at).
* refused: the **joined** spelling (``100nF63V``, ``22uF50V``). A tail has to *be*
  a separate token to be a tail, and the joined strings are exactly the shape a
  merchant part number has — the one the whole-field anchoring exists to refuse.
* refused: a field whose leading token is not a capacitance (``SMCJ28CA 400V``,
  ``2N2222 50V``, ``10K 400V``, a bare ``400V``). A rating alone is not a value.
* refused: ``0.1 uF 50V`` — disclosed, not hidden. ``0.1 uF`` (the suffix grammar's
  own ``number \\s* unit`` shape) reads, but with a tail the leading token is
  ``0.1``, which names no unit. Widening this needs a third grammar (a
  unit-terminated *prefix*), which no witness here asks for; it is listed as the
  batch's open edge rather than guessed at.
* refused: a first token past :data:`_MAX_DECODED_CHARS` (issue #27's cap). The
  whole field being long is fine, because the cap is measured on the first token.

The row-level half (``foc._token_note``, the sentence that says a field was read by
its leading token) is pinned too: the core change moves *where* that read happens
and must not change one byte of what a row says.
"""

from __future__ import annotations

import pytest

from boardwise.core.compare import _quantity, values_equal
from boardwise.core.model import Component
from boardwise.core.values import parse_capacitance_farads
from boardwise.engines.bom import _values_agree
from boardwise.rules.params import _kind_of, _stated_quantity

#: ``(field, farads)`` for every annotation shape this reader now reads. The
#: second element is the **leading token's own reading** — see the equivalence
#: test below — so these are not new numbers: they are the numbers the same
#: grammars have always produced for the value half of the field.
TAILED_FIELDS = (
    ("330uF 400V", 330e-6),
    ("330UF 400V", 330e-6),
    ("330uF 400 V", 330e-6),
    ("22uF 50V", 22e-6),
    ("0.1uF 50V", 1e-7),
    ("100nF 50V", 100e-9),
    ("1mF 50V", 1e-3),
    ("22\u03bcF 50V", 22e-6),  # GREEK SMALL LETTER MU
    ("22\u00b5F 50V", 22e-6),  # MICRO SIGN
    ("4u7 50V", 4.7e-6),  # the trade's mid-letter notation, tailed
    ("2n2 100V", 2.2e-9),
    ("5p1 50V", 5.1e-12),
    ("160n 50V", 160e-9),
    ("10uF 16V 25V", 10e-6),  # a two-word annotation
    ("330uF  ", 330e-6),  # trailing whitespace is not a tail
)

#: Fields this reader goes on refusing, with the reason pinned in the test bodies.
REFUSED_FIELDS = (
    "100nF63V",  # joined: the tail is not a token, it is more of the string
    "22uF50V",
    "330uF400V",
    "0.1 uF 50V",  # the leading token names no unit — see the module docstring
    "SMCJ28CA 400V",  # a merchant part number is not a value
    "GRM188 400V",
    "2N2222 50V",
    "10K 400V",  # a resistance value is not a capacitance
    "400V",  # a rating alone states no capacitance
    "只看图不看值",
    "只看图不看值 50V",
    "",
    "   ",
)


def test_a_trailing_annotation_is_read_by_the_fields_leading_token():
    """llc's own field is the witness: ``330uF 400V`` is 330 µF."""
    for text, farads in TAILED_FIELDS:
        assert parse_capacitance_farads(text) == pytest.approx(farads), text


def test_the_reading_is_the_leading_tokens_own_reading():
    """Not a second grammar: every tailed field reads what its token reads.

    This is what makes the core change *additive* — nothing the two existing
    grammars already read changes value, because the fallback hands the same
    grammars a shorter string (the token), never a different one.
    """
    for text, _farads in TAILED_FIELDS:
        token = text.strip().split(maxsplit=1)[0]
        read, by_token = parse_capacitance_farads(text), parse_capacitance_farads(token)
        assert read == pytest.approx(by_token), text


def test_the_joined_spelling_is_still_refused():
    """A tail is a **separate token**; ``100nF63V`` is one string, and it is refused.

    The joined shapes are the ones the whole-field anchoring exists for (the
    merchant part numbers of 071 §1 C), so a tail grammar that ate them would
    undo the anchoring it sits beside.
    """
    for text in ("100nF63V", "22uF50V", "330uF400V", "330uF400", "100nF0805"):
        assert parse_capacitance_farads(text) is None, text


def test_a_leading_token_that_is_not_a_capacitance_is_still_refused():
    """A rating, a part number, a resistance and prose are all ``None``."""
    for text in REFUSED_FIELDS:
        assert parse_capacitance_farads(text) is None, text


def test_the_space_inside_the_suffix_grammar_needs_the_unit_to_end_the_field():
    """The disclosed edge: ``0.1 uF`` reads, ``0.1 uF 50V`` does not.

    The suffix grammar's ``number \\s* unit`` shape is a *whole-field* shape
    (``_CAP_RE`` is anchored at both ends), so with an annotation behind it the
    field's leading token is ``0.1`` — a number with no unit, which this module
    has refused since 011. Reading it would need a third grammar (a
    unit-terminated prefix of the field), and no witness asks for one; the edge is
    pinned rather than left to be discovered.
    """
    assert parse_capacitance_farads("0.1 uF") == pytest.approx(1e-7)
    assert parse_capacitance_farads("0.1 uF 50V") is None
    assert parse_capacitance_farads("1 mF") == pytest.approx(1e-3)
    assert parse_capacitance_farads("1 mF 50V") is None


def test_the_length_cap_is_still_measured_on_the_first_token():
    """Issue #27's bound is unchanged, and a long *tail* is not a long value.

    ``_too_long`` reads the first whitespace-separated token, so a 200-character
    annotation is harmless (the decoders run on a bounded string) while a 400-digit
    *value* is refused — the same answer this reader gave before, one token along.
    """
    assert parse_capacitance_farads("330uF " + "x" * 200) == pytest.approx(330e-6)
    assert parse_capacitance_farads("1" * 400 + " 400V") is None
    assert parse_capacitance_farads("1" * 400 + "uF") is None


def test_a_leading_token_the_grammar_already_reads_is_read_with_its_tail_too():
    """The disclosed cost, measured: the fallback adds no shape, it applies the token's.

    ``4N60`` (a MOSFET part number) is read as 4.6 nF by the trade's mid-letter
    notation **on its own** — that is 077's grammar, not this batch's (the
    two-digit fraction after the ``N`` is what ``2N2222``'s four digits are refused
    by). 171 adds the same reading for the *tailed* spelling, which the corpus sweep
    in ``outputs/171/probe_cap_corpus.txt`` shows once in this repository (a prose
    string, not a Value field). What does **not** widen is the shape: the anchoring
    still refuses the merchant part numbers the notation hides inside
    (``2N2222 50V``, ``IRF540N 100V``), which is the guard 071 §1 C put there.
    """
    assert parse_capacitance_farads("4N60") == pytest.approx(4.6e-9)
    assert parse_capacitance_farads("4N60 600V") == pytest.approx(4.6e-9)
    assert parse_capacitance_farads("IRF540N 100V") is None
    assert parse_capacitance_farads("2N2222 50V") is None


def test_a_plain_field_is_not_a_tail_and_reads_what_it_always_did():
    """The additive check from the other side: no tail, no fallback, same numbers."""
    for text, farads in (
        ("330uF", 330e-6),
        ("100nF", 1e-7),
        ("4u7", 4.7e-6),
        ("160n", 160e-9),
        ("1mF", 1e-3),
    ):
        assert parse_capacitance_farads(text) == pytest.approx(farads), text


# ---------------------------------------------------------------------------
# the rule half: foc's reader is now the core reader, and its row says the same
# ---------------------------------------------------------------------------


def test_foc_farads_of_is_the_core_reader():
    """``foc._farads_of`` is a delegation, so it answers what core answers.

    The two-stage read 164a wrote lived in that rule; the whole-field/leading-token
    split is core's now (071 §2), and the wrapper is kept so the rule's call sites
    and its evidence wording do not move. On every witness — tailed, plain, prose,
    part numbers, over-long — the two are one function.
    """
    from boardwise.rules.pcb.foc import _farads_of

    for text in (
        "330uF 400V",
        "330uF",
        "4u7 50V",
        "100nF63V",
        "0.1 uF 50V",
        "SMCJ28CA 400V",
        "只看图不看值",
        "",
        "   ",
        "1" * 400 + " 400V",
        "330uF " + "x" * 200,
    ):
        assert _farads_of(text) == parse_capacitance_farads(text), text


def test_the_row_still_says_the_field_was_read_by_its_leading_token():
    """``_token_note``'s sentence is byte-identical, and its condition is unchanged.

    164a's row for llc quoted 「该值字段共享电容语法读不整串——'330uF 400V' 带尾注——
    按其首个词 '330uF' 读出」, and ``tests/test_164a_foc_view_truth.py`` reads that
    sentence's substrings off ``view.basis``. The core change moves the read, not
    the disclosure: the note fires exactly on the fields it fired on before — the
    field carries a tail (so core read it by its leading token) and that token alone
    is a readable capacitance — and says exactly the same thing.
    """
    from boardwise.rules.pcb.foc import _token_note

    assert _token_note("330uF 400V") == (
        "（该值字段共享电容语法读不整串——'330uF 400V' 带尾注——按其首个词 '330uF' 读出）"
    )
    assert "首个词" in _token_note("4u7 50V")
    for text in ("330uF", "0.1 uF", "", "   ", "只看图不看值", "只看图不看值 50V"):
        assert _token_note(text) == "", text


# ---------------------------------------------------------------------------
# the consumption faces this reader has: compare / bom / params
# ---------------------------------------------------------------------------


def test_compare_reads_a_tailed_field_as_the_quantity_it_states():
    """``core.compare``: a tailed field is now a comparable quantity.

    Before this batch the two spellings of one part (``100nF 50V`` on one board,
    ``100nF`` on the other) fell through to the string comparison and were reported
    as a difference; the reader's gap was the *silent* kind 011 exists about.
    """
    kind, amount = _quantity("330uF 400V")
    assert kind == "capacitance" and amount == pytest.approx(330e-6)
    assert values_equal("100nF 50V", "100nF")
    assert values_equal("330uF 400V", "330uF")
    # A tailed resistance is still a resistance, and the two kinds do not mix.
    assert values_equal("10K 1%", "10K") is False


def test_bom_calls_two_spellings_of_one_tailed_part_one_value():
    """``engines.bom``: the Comment comparison reads the same fields the same way."""
    assert _values_agree("100nF 50V", "0.1uF")
    assert _values_agree("330uF 400V", "330uF")
    assert _values_agree("100nF 50V", "10uF") is False


def test_params_can_now_classify_and_compare_a_tailed_field():
    """``rules.params``: the unit guess and the contract comparison both read it.

    ``_kind_of`` decides 「is this field a capacitance」 by the unit, so a tailed
    field used to be ``None`` — an unclassified part the rule skipped in silence
    (087 §8's 「silence, not a miss」). ``_stated_quantity`` reads a written
    contract (``0.1Ω`` / ``100mΩ``'s sibling for capacitance), and ``330uF 400V``
    is exactly the shape a person writes there.
    """
    assert (
        _kind_of(Component(uid="c1", designator="C1", value="100nF 50V"), None)
        == "capacitor"
    )
    assert _stated_quantity("330uF 400V", "capacitor") == pytest.approx(330e-6)
