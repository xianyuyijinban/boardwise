"""191C — the bare ``(net N)`` form: the id is read, the name is looked up.

KiCad 10 writes a net's name inline on every pad, track, via and zone
(``(net "CAN_H")``) and keeps no table; KiCad 6–9 wrote both the id and the
name inline (``(net 1 "CAN_H")``) *beside* a top-level ``(net N "NAME")`` table.
A file can also carry the **bare id alone** — ``(net 1)`` — and that is the
form this reader used to refuse by name: without the name, a high-speed check
that recognises a differential pair by its net name is reading a board whose
nets have no names at all.

What the batch does, and what these tests hold it to:

* the id is looked up in the file's own ``(net N "NAME")`` table, so a bare id
  and a named id that the table says are the same net are **the same net** here
  (:func:`test_a_bare_id_and_a_named_id_read_as_the_same_net`);
* an id the table does not name is kept as ``net#N`` and **counted**, never
  given an invented name (:func:`test_an_id_the_table_never_names_is_kept_and_counted`);
* an id the table declares nameless (``(net 0 "")`` — KiCad's own 「no net」) is
  no net at all, and is not a lost name either
  (:func:`test_an_id_the_table_declares_nameless_is_no_net`);
* the count is **disclosed** on the board entry, because the name-driven checks
  cannot see those nets (:func:`test_the_lost_names_are_disclosed_on_the_board_entry`),
  and a board that lost nothing gains no such line;
* the inline name still wins over the table when the two disagree, and the
  refusals that were real stay refusals.

**The fixture is hand-written.** ``kicad_min/kicad_bare_net.kicad_pcb`` was
written for this shape — no KiCad-written file in this repository carries a
bare ``(net N)`` next to a table, and this container has no KiCad to measure
against — so these tests pin *this reader's* contract, not a measurement of
KiCad. That is why every case names the fixture's own elements rather than
quoting a KiCad reading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.engines.pcbreview import run_pcb_review
from boardwise.parsers.kicad import (
    KicadFormatError,
    read_kicad_board,
    read_kicad_board_model,
    unnamed_net_names,
)

FIX = Path(__file__).parent / "fixtures" / "kicad_min"
BARE = FIX / "kicad_bare_net.kicad_pcb"
NAMED = FIX / "kicad_min.kicad_pcb"


def _board(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "t.kicad_pcb"
    path.write_text(
        '(kicad_pcb (version 20230121) (generator "pcbnew")\n'
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal))\n'
        f"{body}\n)",
        encoding="utf-8",
    )
    return path


def _pads_of(board, net: str) -> list[tuple[str, str]]:
    return [(p.component, p.pin_number) for p in board.net(net).pads]


# ---------------------------------------------------------------------------
# the bare id and the named id are one net
# ---------------------------------------------------------------------------


def test_a_bare_id_and_a_named_id_read_as_the_same_net():
    """J1.1 states ``(net 1)``; R1.1 states ``(net 1 "CAN_H")`` — one net.

    Both the id and the table row are the fixture's own; the point is that the
    bare form no longer loses the net, which is what the high-speed shelf reads
    (``pcb-hs-diffpair-inventory`` matches a pair by the names ``*_H``/``*_L``).
    """
    board = read_kicad_board(BARE)
    assert _pads_of(board, "CAN_H") == [("J1", "1"), ("R1", "1")]
    # and the same net's track is the one drawn as a **bare** id
    assert [t.net for t in board.tracks if t.net == "CAN_H"]
    starts = sorted(round(t.start.x, 3) for t in board.net("CAN_H").tracks)
    assert len(starts) == 1, "one bare-id segment on CAN_H, and it is on that net"
    assert board.net("CAN_L").pads, "the other pair member read too"
    assert unnamed_net_names(board) == ["net#7"], "no *named* net was mistaken for an unnamed one"
    # the model view of the same file agrees net for net
    model = read_kicad_board_model(BARE)
    assert sorted(model.nets) == ["CAN_H", "CAN_L", "net#7"]
    assert sorted(model.nets["CAN_H"].pins) == [("J1", "1"), ("R1", "1")]


def test_the_inline_name_wins_over_a_disagreeing_table_row(tmp_path):
    """The element's own name is the name; the table is only the fallback.

    A file where the two disagree is a broken file, and this reader does not
    adjudicate between them: the element states a name, so that is the net.
    """
    board = read_kicad_board(_board(
        tmp_path,
        '(net 1 "FROM_TABLE")\n'
        '(segment (start 0 0) (end 1 0) (layer "F.Cu") (width 0.25) (net 1 "INLINE"))\n'
        '(segment (start 0 5) (end 1 5) (layer "F.Cu") (width 0.25) (net 1))',
    ))
    assert sorted(board.net_names()) == ["FROM_TABLE", "INLINE"]
    assert [t.net for t in board.tracks if round(t.start.y, 3) == 0.0] == ["INLINE"]


# ---------------------------------------------------------------------------
# the id the table never names
# ---------------------------------------------------------------------------


def test_an_id_the_table_never_names_is_kept_and_counted():
    """``net#7`` is this reader's marker for a lost name, and it is counted.

    The fixture's table has 0/1/2 and nothing else, so the id ``7`` that R2.1,
    one segment and one via state is a name the file lost. Inventing one — say
    ``N7`` — would hand the rules a net that does not exist; dropping it would
    hand them copper with no net at all.
    """
    board = read_kicad_board(BARE)
    assert "net#7" in board.net_names()
    assert _pads_of(board, "net#7") == [("R2", "1")]
    assert len(board.net("net#7").tracks) == 1 and len(board.net("net#7").vias) == 1
    assert unnamed_net_names(board) == ["net#7"], "the count is this list's length: one id"
    # The model view counts the pads that stated it — 1 pad, and only pads, so
    # its number is the pads' and never a stand-in for the board's.
    model = read_kicad_board_model(BARE)
    assert model.raw["netIdsWithoutNames"] == {"7": 1}
    assert unnamed_net_names(read_kicad_board(NAMED)) == []
    assert "netIdsWithoutNames" not in read_kicad_board_model(NAMED).raw, "absent, not empty"


def test_an_id_the_table_declares_nameless_is_no_net():
    """``(net 0)`` against ``(net 0 "")``: KiCad's own 「this id is not a net」.

    R1.2 states it. The two answers a lookup can give are not the same answer:
    「the file says this id has no name」 is a pin with no net, while 「the file
    says nothing about this id」 is a name that was lost and is counted.
    """
    board = read_kicad_board(BARE)
    assert [(p.component, p.pin_number, p.net) for p in board.pads if p.net is None] == [("R1", "2", None)]
    assert unnamed_net_names(board) == ["net#7"], "net 0 is a declaration, not a lost name"
    assert read_kicad_board_model(BARE).raw["netIdsWithoutNames"] == {"7": 1}


# ---------------------------------------------------------------------------
# the disclosure
# ---------------------------------------------------------------------------


def test_the_lost_names_are_disclosed_on_the_board_entry():
    """The report says how many ids lost their names — a silent `net#N` is not enough.

    Nets are found **by name** (the differential-pair inventory, the per-rail
    decap bands), so a board whose ids lost their names is a board those checks
    cannot see. The count therefore rides on the board entry, and it names the
    ids so a reader can go and look in the file.
    """
    _findings, section = run_pcb_review(BARE)
    entry = section["boards"][0]
    assert "1 个网序号" in entry["netIdNote"]
    assert "net#7" in entry["netIdNote"]
    assert section["rules_errored"] == [], "the new form must not make a rule raise"


def test_a_board_that_lost_no_name_carries_no_such_line():
    """Absent, not empty (钉 5): 「nothing was lost」 gets no line at all."""
    _findings, section = run_pcb_review(NAMED)
    assert "netIdNote" not in section["boards"][0]
    assert not [n for n in read_kicad_board(NAMED).net_names() if n.startswith("net#")]


# ---------------------------------------------------------------------------
# the refusals that were real stay refusals
# ---------------------------------------------------------------------------


def test_a_bare_argument_that_is_neither_an_id_nor_a_name_is_refused(tmp_path):
    """``(net abc)`` is none of the three written forms — refuse, never guess."""
    with pytest.raises(KicadFormatError, match="neither a net id nor a quoted name"):
        read_kicad_board(_board(
            tmp_path, '(segment (start 0 0) (end 1 0) (layer "F.Cu") (width 0.25) (net abc))'
        ))
