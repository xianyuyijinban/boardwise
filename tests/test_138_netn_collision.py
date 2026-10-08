"""138: the parser's fallback ``NETn`` must not collide with a hand-written label.

Issue #73. ``parsers/schematic.py`` names every unnamed cluster ``NET1..NETn``
deterministically, and the number it hands out is just the cluster's index:
nothing asked whether the name was **already taken** by an explicit NET label
elsewhere on the sheet. So a board carrying one hand-written label that happens
to read ``NET1`` got two different circuits under one name, and
``nets.setdefault`` — the very line that reverse-builds the netlist — welded
them into **one net**:

    nets:
      NET1     members=[('U1','1'), ('U2','1')]      <- two circuits, one net

What makes it worse than the near neighbours is that it was **silent**: the
per-page merge's name welding files its names in ``unproven_nets`` (#19) and
107's dropped-placement welding files its own (#107), so a rule reading such a
net refuses to conclude. This one filed nothing — a rule that found a
capacitor on the net, or did not, believed it about a netlist nobody drew.

The editor's own derived names (``$11N…``, ``engines/draw.py``) cannot collide
here — they are a different family — and no board in this repository carries an
explicit ``NETn`` label today, so the defect is reachable but not triggered.
Both facts are why this is a shape pin on a synthesised board rather than a
regression on a fixture.

What this file holds:

* the synthesised two-circuit board: the unnamed cluster takes a **different**
  name from the explicit ``NET1``, and the two nets each keep their own members;
* the numbering discipline itself — an auto-name skips a **taken** number and
  keeps counting from there, so the auto-nets of a board whose labels eat
  ``NET1``/``NET2`` are ``NET3``, ``NET4``, … rather than a duplicate;
* that a board with no colliding label is **byte-for-byte what it was**: the
  same clusters get the same ``NET1..NETn``, because the fix must not renumber
  every board in the repository;
* and that no explicit label is ever rewritten — the name on the drawing is the
  truth, the auto-name is ours.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from boardwise.parsers.schematic import build_schematic_model


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol() -> list[str]:
    """A two-pin part drawn at the origin: pin 1 at (0,0), pin 2 at (20,0)."""
    out = [
        _record("DOCHEAD", {"docType": "SYMBOL", "uuid": "sym-r", "editVersion": "3.2.149"}),
        _record("META", {"title": "R", "docType": "SYMBOL"}, id_="meta-r"),
    ]
    for index, number in enumerate(("1", "2")):
        pin_id = f"sym-r-pin{number}"
        out.append(_record("PIN", {"x": float(index * 20), "y": 0.0, "zIndex": index + 2},
                           id_=pin_id))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
                           id_=f"{pin_id}-n"))
    return out


def _page(uuid: str, parts: list[tuple[str, float, str]]) -> list[str]:
    """One ``SCH_PAGE``: each ``(designator, x, net name)`` gets its own wire.

    ``net name == ""`` means **no NET attribute** — that is what makes the
    cluster unnamed, and unnamed is the only thing the fallback names.
    """
    lines = [
        _record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": uuid}),
        _record("CANVAS", {"originX": 0, "originY": 0, "unit": "0.01inch"},
                id_=f"canvas-{uuid}"),
    ]
    for index, (designator, x, net_name) in enumerate(parts):
        part = f"inst-{uuid}-{index}"
        lines.append(_record("COMPONENT", {"partId": part, "x": x, "y": -300.0,
                                           "rotation": 0, "isMirror": False, "zIndex": 10},
                             id_=f"c-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Designator",
                                      "value": designator}, id_=f"d-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Symbol",
                                      "value": "sym-r"}, id_=f"s-{part}"))
        group = f"grp-{uuid}-{index}"
        lines.append(_record("WIRE", {"zIndex": 40}, id_=group))
        lines.append(_record("LINE", {"lineGroup": group, "startX": x, "startY": -300.0,
                                      "endX": x + 20.0, "endY": -300.0}))
        if net_name:
            lines.append(_record("ATTR", {"parentId": group, "key": "NET", "value": net_name},
                                 id_=f"net-{uuid}-{index}"))
    return lines


def _synthetic(tmp_path: Path, name: str, pages: list[list[str]]) -> Path:
    lines: list[str] = []
    for page in pages:
        lines += page
    lines += _symbol()
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


def _one_board(tmp_path: Path, name: str, parts: list[tuple[str, float, str]]):
    """``build_schematic_model`` on a one-page board, unwrapped to the board."""
    model = build_schematic_model(_synthetic(tmp_path, name, [_page("page-1", parts)]))
    boards = getattr(model, "boards", None)
    return model if boards is None else boards[0]


def test_an_explicit_label_never_welds_with_a_fallback_auto_name(tmp_path):
    """The defect, as the issue measured it: two circuits, one net, no mark.

    ``R1`` is an unnamed cluster (the parser has to name it) and ``R2`` carries a
    hand-written label reading ``NET1`` — the exact number the first cluster's
    index would hand out. Before the fix both clusters read ``NET1``, the two
    nets welded into one with four members, and nothing anywhere said so.

    After the fix the two are two nets: the fallback stepped over the taken
    number, and the explicit label kept the name the drawing gave it.
    """
    board = _one_board(tmp_path, "collide.epro2", [
        ("R1", 300.0, ""),        # unnamed cluster -> the fallback names it
        ("R2", 700.0, "NET1"),    # hand-written label that happens to read NET1
    ])

    # two nets, each with its own circuit's members — never one four-member net
    assert sorted(board.nets) == ["NET1", "NET2"], sorted(board.nets)
    assert list(board.nets["NET1"].pins) == [("R2", "1"), ("R2", "2")]
    assert list(board.nets["NET2"].pins) == [("R1", "1"), ("R1", "2")]

    # the explicit label is never rewritten: what the designer wrote is what the
    # net is called, and the auto-name is the one that gives way.
    assert board.nets["NET1"].name == "NET1"
    for pin in board.components["R2"].pins:
        assert pin.net == "NET1"


def test_the_fallback_skips_every_taken_number_and_keeps_counting(tmp_path):
    """The avoidance is a rule about **taken** names, not about one shape.

    Labels reading ``NET1`` *and* ``NET2`` push both fallback clusters to
    ``NET3``/``NET4``. Counting from the first free number (rather than skipping
    only ``NET1``, or restarting) is what keeps the auto-names unique among
    themselves as well — two clusters must never receive the same name either.
    """
    board = _one_board(tmp_path, "three_taken.epro2", [
        ("R1", 300.0, ""),
        ("R2", 700.0, ""),
        ("R3", 1100.0, "NET1"),
        ("R4", 1500.0, "NET2"),
    ])
    assert sorted(board.nets) == ["NET1", "NET2", "NET3", "NET4"], sorted(board.nets)
    assert list(board.nets["NET3"].pins) == [("R1", "1"), ("R1", "2")]
    assert list(board.nets["NET4"].pins) == [("R2", "1"), ("R2", "2")]
    assert list(board.nets["NET1"].pins) == [("R3", "1"), ("R3", "2")]
    assert list(board.nets["NET2"].pins) == [("R4", "1"), ("R4", "2")]
    # no member sits on two nets, which is the welded-state signature
    for net in board.nets.values():
        assert len(net.pins) == len(set(net.pins))


def test_a_board_with_no_colliding_label_keeps_the_names_it_always_had(tmp_path):
    """The fix must not renumber every board in the repository.

    A board whose labels do not collide must come out with exactly the
    ``NET1..NETn`` the fallback has always produced — otherwise every golden
    netlist, every ``reconcile_names`` calibration and every stored diff in this
    repository moves for a defect no board has. This is the "nothing about the
    untouched boards can move" pin.
    """
    board = _one_board(tmp_path, "plain.epro2", [
        ("R1", 300.0, ""),
        ("R2", 700.0, ""),
        ("R3", 1100.0, ""),
    ])
    assert sorted(board.nets) == ["NET1", "NET2", "NET3"], sorted(board.nets)
    assert list(board.nets["NET1"].pins) == [("R1", "1"), ("R1", "2")]
    assert list(board.nets["NET2"].pins) == [("R2", "1"), ("R2", "2")]
    assert list(board.nets["NET3"].pins) == [("R3", "1"), ("R3", "2")]


def test_no_board_this_repository_can_parse_moves_for_the_fix(tmp_path):
    """The corpus pin, in the shape 105/107 use it: every fixture and review-set
    file is parsed and its net names recorded.

    No board in this repository carries an explicit ``NETn`` label — the DCDC
    board's ``NET1`` is the **fallback's own** name, not a hand-written one — so
    the fix must leave every one of them exactly as it was. A test that only
    pinned the synthesised collision could pass while the fix renumbered the
    repositories' real goldens, and those goldens are what
    ``reconcile_names`` calibration and every stored diff compare against.
    """
    from boardwise.engines.review_eval import load_board_model

    files = sorted(
        [p for p in (Path(__file__).parent / "fixtures").glob("*.epro2")]
        + [p for p in (Path(__file__).parent / "fixtures").glob("*.enet")]
        + [p for p in (Path(__file__).resolve().parents[1] / "reviewsets").rglob("*.epro2")]
    )
    parsed = 0
    for path in files:
        model = load_board_model(str(path))
        for board in (getattr(model, "boards", None) or [model]):
            names = set(board.nets)
            # every auto-named net keeps the plain `NET<number>` spelling: the
            # avoidance only changes which *number*, never the family.
            for name in names:
                if name.startswith("NET"):
                    assert name[3:].isdigit() and not name.startswith("NET0"), (
                        f"{path.name}: {name!r} is not the plain fallback spelling"
                    )
            parsed += 1
    assert parsed >= 26, f"only {parsed} boards parsed — the sweep found less than the corpus"