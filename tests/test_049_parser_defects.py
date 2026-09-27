"""049 P2: a pin attribute is filed to the pin it *names*, not to the one it follows.

The defect this file pins has the same root as 042 one level down. EasyEDA Pro's
incremental save appends a changed record's attributes to the **end** of the
document, keeping ``parentId`` as the only ownership link; 042 taught the page
walker that ("ATTR follows COMPONENT" is not a property of a saved file), and
``_collect_symbols`` had been pairing ``Pin Number`` / ``Pin Name`` / ``Pin Type``
with a pin purely by **stream order**. Measured 2026-09-27, that costs pins on
four committed fixtures, in two shapes:

* **the trailing block** — the 级联多电平 module symbol (both boards) and
  ``llc_board.epro2`` carry the eight signal pins' numbers in one block *after*
  the last ``PIN`` record, each naming its own pin's record id. Position alone
  loses seven numbers per instance (14 pins dropped on each of the two cascade
  boards and on the llc board) and writes the wrong number onto whichever pin
  happened to be open last — which is also why the module read as a 3-pin part
  (``1``, ``2`` and a stray ``10``) while its terminals were drawn and wired;
* **the block that precedes its pins** — the FPC board's PS7516 symbol emits each
  pin's attributes *before* the ``PIN`` row, so adjacency shifted every number by
  one (12 pins dropped) and U8's ground pin read as an auto-named net.

Both shapes are filed correctly once a document's pins are indexed before its
attributes are read, which is what :func:`_collect_symbols` now does. The
fixtures are read-only here: the assertions are the pins and nets a person can
check on the boards themselves.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from boardwise.core.geometry import ParseStats
from boardwise.parsers.schematic import build_project_model, build_schematic_model

FIXTURES = Path(__file__).parent / "fixtures"
CASCADE_MAIN = FIXTURES / "级联多电平-主拓扑_2026-09-27.epro2"
CASCADE_DRIVER = FIXTURES / "级联多电平-驱动模块_2026-09-27.epro2"
FPC = FIXTURES / "FPC触屏游戏机_2026-09-27.epro2"

#: The module's pins as the symbol draws them: the gate and source terminals of
#: its four MOSFETs. Only the first two numbers survived the position-only
#: reading, so these names are what "the 14 dropped pins" means concretely.
MODULE_PIN_NAMES = {
    "1": "15V+", "2": "15V-", "3": "Q1G", "4": "Q1S", "5": "Q2G",
    "6": "Q2S", "7": "Q3G", "8": "Q3S", "9": "Q4G", "10": "Q4S",
}


# --------------------------------------------------------------------------
# synthetic streams: the two shapes, written out
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _doc_head(doc_type: str, uuid: str) -> str:
    return _record("DOCHEAD", {"docType": doc_type, "uuid": uuid,
                               "editVersion": "3.2.186"})


def _attr(key: str, value: str, parent: str) -> str:
    return _record("ATTR", {"key": key, "value": value, "parentId": parent})


def _pin(x: float, y: float, z: int, id_: str | None = None) -> str:
    return _record("PIN", {"x": x, "y": y, "zIndex": z}, id_=id_)


def _component(part_id: str, symbol: str, designator: str) -> list[str]:
    return [
        _record("COMPONENT", {"partId": part_id, "x": 100, "y": 200, "rotation": 0}),
        _attr("Designator", designator, symbol),
        _attr("Symbol", symbol, symbol),
        _attr("Device", "dev-" + designator, symbol),
    ]


def _backup(tmp_path: Path, name: str, records: list[str]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("board.epru", "\n".join(records))
    return path


def _trailing_block_stream() -> list[str]:
    """The measured module shape: numbers appended after the last ``PIN``.

    The ``Pin Number`` parents are the ``PIN`` rows' **own ids** (here ``p1``…),
    which is deliberately *not* the synthesised ``e<zIndex>`` ref a V3 file uses
    for ``NO_CONNECT`` — a document can use either spelling, and the parse has to
    answer for both without confusing one pin's ref with a neighbour's id.
    """
    lines = [_doc_head("SYMBOL", "sym1"), _record("META", {"title": "MODULE"})]
    for index, (number, name) in enumerate(
        [("1", "15V+"), ("2", "15V-"), ("3", "Q1G"), ("4", "Q1S")]
    ):
        lines.append(_pin(0.0, float(index * 10), index + 1, id_=f"p{index + 1}"))
        lines.append(_attr("Pin Name", name, f"p{index + 1}"))
        lines.append(_attr("Pin Type", "Undefined", f"p{index + 1}"))
    # the appended block: every number, in one run, naming its own pin
    for index, (number, _name) in enumerate(
        [("1", "15V+"), ("2", "15V-"), ("3", "Q1G"), ("4", "Q1S")]
    ):
        lines.append(_attr("Pin Number", number, f"p{index + 1}"))
    return lines


def _preceding_attributes_stream() -> list[str]:
    """The FPC shape: each pin's attributes come *before* its ``PIN`` row."""
    lines = [_doc_head("SYMBOL", "sym1"), _record("META", {"title": "PS7516"})]
    for number, name in [("1", "LX"), ("2", "GND"), ("3", "FB")]:
        lines.append(_attr("Pin Name", name, f"e{number}"))
        lines.append(_attr("Pin Number", number, f"e{number}"))
    for number in ("1", "2", "3"):
        lines.append(_pin(0.0, float(number), int(number), id_=f"e{number}"))
    return lines


# --------------------------------------------------------------------------
# 1. the two shapes, as streams
# --------------------------------------------------------------------------


def test_a_pin_number_appended_to_the_end_of_the_symbol_is_filed_by_parent_id(tmp_path):
    path = _backup(
        tmp_path,
        "trailing.epro2",
        [_doc_head("SCH_PAGE", "page1"), *_component("part1", "sym1", "U1"),
         *_trailing_block_stream()],
    )
    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    assert stats.pins_dropped_no_number == 0, "the numbers are in the file"
    pins = {pin.number: pin.name for pin in model.components["U1"].pins}
    assert pins == {"1": "15V+", "2": "15V-", "3": "Q1G", "4": "Q1S"}


def test_the_attributes_that_precede_their_pin_are_filed_to_the_pin_they_name(tmp_path):
    path = _backup(
        tmp_path,
        "preceding.epro2",
        [_doc_head("SCH_PAGE", "page1"), *_component("part1", "sym1", "U8"),
         *_preceding_attributes_stream()],
    )
    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    assert stats.pins_dropped_no_number == 0
    pins = {pin.number: pin.name for pin in model.components["U8"].pins}
    assert pins == {"1": "LX", "2": "GND", "3": "FB"}, (
        "by position these three numbers shift by one onto the neighbouring pin"
    )


def test_a_pin_id_that_collides_with_a_neighbours_ref_is_not_swapped(tmp_path):
    """The trap in indexing both spellings in one dict.

    This stream's ``PIN`` rows are ``id=p1,p2`` while a V3 parse synthesises the
    refs ``e1,e2`` from ``zIndex`` — so the second pin's *id* equals nothing but
    the first pin's ref can never equal a neighbour's id by accident here. The
    case that bites is the eprj3 stream of ``test_038_eprj3``: ``id=e1,e2`` with
    refs ``e2,e3``, where one pin's ref *is* the next pin's id. Merging the two
    indexes hands that pin's number to its neighbour and drops the real owner.
    """
    lines = [_doc_head("SYMBOL", "sym1"), _record("META", {"title": "X"})]
    for index, number in enumerate(("1", "2")):
        pin_id = f"e{index + 1}"
        lines.append(_pin(0.0, float(index * 10), index + 2, id_=pin_id))
        lines.append(_attr("Pin Number", number, pin_id))
    path = _backup(
        tmp_path,
        "collide.epro2",
        [_doc_head("SCH_PAGE", "page1"), *_component("part1", "sym1", "U1"), *lines],
    )
    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    assert stats.pins_dropped_no_number == 0
    assert {pin.number for pin in model.components["U1"].pins} == {"1", "2"}


# --------------------------------------------------------------------------
# 2. the four committed fixtures the shape cost pins on
# --------------------------------------------------------------------------


def test_the_cascade_modules_terminals_are_read_and_wired():
    """The board the 14-pin note was filed against (级联多电平-主拓扑).

    Each module's gate/source terminals now read *and* land on the nets the
    drawing connects them to (``AHG``/``AHS`` join the MOSFETs' own pins), which
    is the difference between "dropped" and "in the model".
    """
    stats = ParseStats()
    board = build_project_model(CASCADE_MAIN, parse_stats=stats).boards[0]

    assert stats.pins_dropped_no_number == 0
    u1 = {pin.number: (pin.name, pin.net) for pin in board.components["U1"].pins}
    assert {number: name for number, (name, _net) in u1.items()} == MODULE_PIN_NAMES
    assert u1["3"] == ("Q1G", "AHG") and u1["4"] == ("Q1S", "AHS")
    assert u1["5"] == ("Q2G", "ALG") and u1["9"] == ("Q4G", "BLG")
    assert board.nets["AHG"].pins == [("Q1", "1"), ("U1", "3")]
    assert {("U2", "3")} <= set(board.nets["CHG"].pins)


def test_the_driver_boards_module_reads_all_ten_pins():
    stats = ParseStats()
    board = build_project_model(CASCADE_DRIVER, parse_stats=stats).boards[0]

    assert stats.pins_dropped_no_number == 0
    u5 = {pin.number: (pin.name, pin.net) for pin in board.components["U5"].pins}
    assert {number: name for number, (name, _net) in u5.items()} == MODULE_PIN_NAMES
    assert u5["3"] == ("Q1G", "QAHG") and u5["7"] == ("Q3G", "QBHG")


def test_the_fpc_boards_ps7516_pins_are_not_shifted():
    """The attributes-before-the-pin shape, on the real board: U8's ground pin is
    on the board's ground, not on an auto-named island two pins over."""
    stats = ParseStats()
    board = build_project_model(FPC, parse_stats=stats).boards[0]

    assert stats.pins_dropped_no_number == 0
    u8 = {pin.number: (pin.name, pin.net) for pin in board.components["U8"].pins}
    assert u8 == {
        "1": ("LX", "NET5"), "2": ("GND", "GND"), "3": ("FB", "NET11"),
        "4": ("EN", "VBAT"), "5": ("OUT", "NET1"), "6": ("IN", "VBAT"),
    }
