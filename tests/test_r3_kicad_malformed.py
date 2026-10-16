"""R3 / fixB: a malformed KiCad file must refuse, never traceback.

PR #80's review found that a board or schematic with a missing ``start`` /
``end`` / ``mid`` / ``center`` / ``at`` (a hand-edit, a truncation, a rename
between KiCad versions) reached ``_first(...)[1]`` and came out as a
``TypeError`` / ``IndexError`` — ``review --view pcb`` printed a Python
traceback instead of exit 2. The reader's own law is 「读不懂 → 结构化拒绝」:
every boundary branch ends in :class:`KicadFormatError` (a ``ValueError``) or in
``None``.

One case per shape the review named, plus the four the task asked for:
a truncated file, a missing section, a bad number, an empty field. Each asserts
the *class* is exactly ``KicadFormatError`` — a bare ``TypeError`` would also
satisfy ``pytest.raises(TypeError, ...)``, so the plain ``pytest.raises`` here
is deliberate (``KicadFormatError`` is not a ``TypeError``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise.parsers.kicad import (
    KicadFormatError,
    read_kicad_board,
    read_kicad_schematic_model,
    schematic_connectivity,
)

FIX = Path(__file__).parent / "fixtures" / "kicad_min"
REPO = Path(__file__).resolve().parents[1]

_LAYERS = '(layers (0 "F.Cu" signal) (2 "B.Cu" signal))'


def _board(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "t.kicad_pcb"
    path.write_text(
        f'(kicad_pcb (version 20260206) (generator "pcbnew")\n{_LAYERS}\n{body}\n)',
        encoding="utf-8",
    )
    return path


def _sheet(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "t.kicad_sch"
    path.write_text(
        f'(kicad_sch (version 20260306) (generator "eeschema")\n{body}\n)',
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# the four shapes the task named
# ---------------------------------------------------------------------------


def test_a_truncated_file_is_refused_not_traced(tmp_path):
    path = tmp_path / "t.kicad_pcb"
    path.write_text('(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal)', encoding="utf-8")
    with pytest.raises(KicadFormatError):
        read_kicad_board(path)
    # and the schematic side, truncated mid-token
    sch = tmp_path / "t.kicad_sch"
    sch.write_text('(kicad_sch (version 20260306) (symbol (lib_id "Device:R"', encoding="utf-8")
    with pytest.raises(KicadFormatError):
        schematic_connectivity(sch)


def test_a_missing_section_is_refused_by_name(tmp_path):
    # a symbol is placed but the schematic carries no `lib_symbols` section
    path = _sheet(tmp_path, '(symbol (lib_id "Device:R") (at 1 2 0) (property "Reference" "R1"))')
    with pytest.raises(KicadFormatError, match="not in the schematic's lib_symbols"):
        read_kicad_schematic_model(path)


def test_a_bad_number_is_refused_not_read_as_zero(tmp_path):
    # `start` is present but its x is not a number — it must not quietly read 0
    path = _board(tmp_path, '(segment (start xx 5) (end 10 5) (layer "F.Cu") (width 0.25) (net "GND"))')
    with pytest.raises(KicadFormatError, match="not a number"):
        read_kicad_board(path)


def test_an_empty_field_is_refused(tmp_path):
    path = _board(tmp_path, '(via (at) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu"))')
    with pytest.raises(KicadFormatError):
        read_kicad_board(path)


# ---------------------------------------------------------------------------
# the entities the PR#80 review named, one by one
# ---------------------------------------------------------------------------

_MALFORMED_BOARDS = {
    "gr_line missing end": '(gr_line (start 0 0) (layer "Edge.Cuts") (width 0.1))',
    "gr_rect missing start": '(gr_rect (end 10 10) (layer "Edge.Cuts") (width 0.1) (fill none))',
    "gr_circle missing center": '(gr_circle (end 5 0) (layer "Edge.Cuts") (width 0.1) (fill none))',
    "gr_arc missing mid": '(gr_arc (start 0 0) (end 10 0) (layer "Edge.Cuts") (width 0.1))',
    "gr_poly point with no numbers": '(gr_poly (pts (xy 0 0) (xy 1) (xy 0 1)) (layer "Edge.Cuts"))',
    "segment missing start": '(segment (end 10 5) (layer "F.Cu") (width 0.25) (net "GND"))',
    "arc missing mid": '(arc (start 0 0) (end 10 0) (layer "F.Cu") (width 0.25) (net "GND"))',
    "via missing at": '(via (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu"))',
    "zone polygon point with no numbers": '(zone (net "GND") (layer "F.Cu") (polygon (pts (xy 0 0) (xy 1))))',
    "pad missing size": (
        '(footprint "X:R_0402" (layer "F.Cu") (uuid "fp") (at 0 0) (property "Reference" "R1")'
        ' (pad "1" smd roundrect (at 0 0) (layers "F.Cu") (net "GND")))'
    ),
    "pad at with a bad number": (
        '(footprint "X:R_0402" (layer "F.Cu") (uuid "fp") (at 0 0) (property "Reference" "R1")'
        ' (pad "1" smd roundrect (at q 0) (size 1 1) (layers "F.Cu") (net "GND")))'
    ),
    # 191C: the **numeric** bare id — the case this dict used to carry as
    # 「a bare pre-6 (net N) id」 — is no longer malformed: it is read against
    # the file's own `(net N "NAME")` table, and an id that table does not name
    # is kept as `net#N` and counted (tests/test_191c_kicad_bare_net.py). What
    # is still refused is a bare argument that is neither an id nor a name.
    "a bare (net abc) that is neither an id nor a name": '(segment (start 0 0) (end 1 0) (layer "F.Cu") (width 0.25) (net abc))',
}


@pytest.mark.parametrize("body", _MALFORMED_BOARDS.values(), ids=list(_MALFORMED_BOARDS))
def test_a_malformed_board_entity_is_refused_by_class(tmp_path, body):
    with pytest.raises(KicadFormatError):
        read_kicad_board(_board(tmp_path, body))


_MALFORMED_SHEETS = {
    "junction with an empty at": '(junction (at))',
    "wire with a one-number point": '(wire (pts (xy 0 0) (xy 1)))',
    "wire point with a bad number": '(wire (pts (xy bad 0) (xy 1 0)))',
    "a label with no name": '(label (at 1 1 0))',
}


@pytest.mark.parametrize("body", _MALFORMED_SHEETS.values(), ids=list(_MALFORMED_SHEETS))
def test_a_malformed_schematic_entity_is_refused_by_class(tmp_path, body):
    with pytest.raises(KicadFormatError):
        schematic_connectivity(_sheet(tmp_path, body))


# ---------------------------------------------------------------------------
# the user-visible consequence: exit 2, no traceback
# ---------------------------------------------------------------------------


def test_review_of_a_malformed_board_exits_2_without_a_traceback(tmp_path):
    path = _board(tmp_path, '(gr_line (start 0 0) (layer "Edge.Cuts") (width 0.1))')
    proc = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "review", str(path), "--view", "pcb"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 2, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "KicadFormatError" in proc.stderr or "gr_line" in proc.stderr


# ---------------------------------------------------------------------------
# the good fixture still reads (no boundary got over-eager)
# ---------------------------------------------------------------------------


def test_the_real_fixture_still_reads_after_the_strict_reader():
    board = read_kicad_board(FIX / "kicad_min.kicad_pcb")
    assert (len(board.components), len(board.pads), len(board.tracks)) == (7, 16, 8)
    assert board.outline is not None and len(board.outline.points) == 4
    assert sorted(read_kicad_schematic_model(FIX / "kicad_min.kicad_sch").components) == [
        "C1", "C2", "R1", "R3", "R4", "U1",
    ]
