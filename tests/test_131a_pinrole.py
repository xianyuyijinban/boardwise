"""Task 131a: pin names on the PCB-side model, and the pin-role classifier.

The substrate is one measured fact: a ``.epro2`` backup writes pin names only in
SYMBOL documents (``ATTR key="Pin Name"`` hung off a ``PIN`` row by
``parentId``), and ``split_documents`` used to drop those documents — so
``Pin.name`` was empty on every ``.epro2`` board and
``core.architecture._SUPPLY_PIN`` matched nothing there.

Three groups of tests:

* **synthetic** — a hand-built stream, so the parentId filing rule is pinned on
  its own (including the 3.2.186 displacement where a pin's attributes are
  appended to the end of the SYMBOL document) rather than only on a fixture
  that happens to exercise it.
* **fixtures** — the three acceptance boards, named pin by pin.
* **pin_role** — the classifier's word list, its compound-name splitting and the
  names it deliberately declines.
"""

import json
from pathlib import Path

import pytest

from boardwise.core.geometry import ParseStats
from boardwise.core.pinrole import PIN_ROLES, ROLE_PRECEDENCE, pin_role
from boardwise.parsers.epro2_model import (
    build_design_model,
    symbol_pin_names,
)
from boardwise.parsers.epru import Epro2Source, load_epro2_source, split_documents

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"


# --------------------------------------------------------------------------
# synthetic .epru helpers (same encoding as tests/test_epro2_model.py)
# --------------------------------------------------------------------------


def _line(record_type: str, body: dict | None = None, record_id: str | None = None) -> str:
    envelope: dict = {"type": record_type}
    if record_id is not None:
        envelope["id"] = record_id
    payload = "" if body is None else json.dumps(body)
    return json.dumps(envelope) + "||" + payload + "|"


def _dochead(doc_type: str, uuid: str) -> str:
    return _line("DOCHEAD", {"docType": doc_type, "uuid": uuid, "editVersion": "3.2.91"})


def _source_from_text(text: str) -> Epro2Source:
    stats = ParseStats(source="<synthetic>")
    return Epro2Source(
        source="<synthetic>",
        stats=stats,
        documents=split_documents(text, stats),
        project_meta={"title": "synthetic"},
    )


def _symbol_doc(uuid: str, pins: list[tuple[str, str]], *, displaced: bool = False) -> list[str]:
    """One SYMBOL document: a ``PIN`` row per pin, then its Pin Number/Name.

    ``displaced`` writes every pin's attributes **after** the last ``PIN`` row,
    which is what a 3.2.186 incremental save does and what makes position-only
    attribution wrong (``parsers/schematic.py::_commit_symbol``). Otherwise each
    pin's attributes follow its own row.
    """
    lines = [_dochead("SYMBOL", uuid), _line("META", {"title": "SYM"}, "META")]
    for index, (number, name) in enumerate(pins, start=1):
        lines.append(_line("PIN", {"x": index * 10, "y": 0, "zIndex": index}, f"pin{index}"))
    if displaced:
        tail = [
            _line("ATTR", {"parentId": f"pin{i}", "key": "Pin Number", "value": number})
            for i, (number, _name) in enumerate(pins, start=1)
        ] + [
            _line("ATTR", {"parentId": f"pin{i}", "key": "Pin Name", "value": name})
            for i, (_number, name) in enumerate(pins, start=1)
        ]
        return lines + tail
    for index, (number, name) in enumerate(pins, start=1):
        lines.append(_line("ATTR", {"parentId": f"pin{index}", "key": "Pin Number", "value": number}))
        lines.append(_line("ATTR", {"parentId": f"pin{index}", "key": "Pin Name", "value": name}))
    return lines


#: A two-pad regulator: the placement names no symbol, so the join has to go
#: placement -> DEVICE -> DEVICE["Symbol"] -> SYMBOL.
SYNTHETIC_NAMED = "\n".join(
    [
        # --- SYMBOL: two pins, names declared -----------------------------
        *_symbol_doc("sym1", [("1", "VIN"), ("2", "VOUT")], displaced=True),
        # --- SYMBOL whose Pin Name sits before its Pin Number --------------
        _dochead("SYMBOL", "sym2"),
        _line("META", {"title": "SYM2"}, "META"),
        _line("PIN", {"x": 0, "y": 0, "zIndex": 1}, "q1"),
        _line("ATTR", {"parentId": "q1", "key": "Pin Name", "value": "GND/ADJ"}),
        _line("ATTR", {"parentId": "q1", "key": "Pin Number", "value": "1"}),
        _line("PIN", {"x": 10, "y": 0, "zIndex": 2}, "q2"),
        _line("ATTR", {"parentId": "q2", "key": "Pin Number", "value": "2"}),
        _line("ATTR", {"parentId": "q2", "key": "Pin Name", "value": "NC"}),
        # --- DEVICES, pointing at those symbols ---------------------------
        _dochead("DEVICE", "dev1"),
        _line("META", {"title": "REG_5V", "attributes": {"Symbol": "sym1"}}, "META"),
        _dochead("DEVICE", "dev2"),
        _line("META", {"title": "AMS1117", "attributes": {"Symbol": "sym2"}}, "META"),
        _dochead("DEVICE", "dev3"),
        _line("META", {"title": "NO_SYMBOL_DEV"}, "META"),
        # --- FOOTPRINT: two pads ------------------------------------------
        _dochead("FOOTPRINT", "fp1"),
        _line("META", {"title": "SOT-23-5"}, "META"),
        _line("PAD", {"num": "1", "centerX": -30, "centerY": 0, "defaultPad": {"width": 40, "height": 40}}, "p1"),
        _line("PAD", {"num": "2", "centerX": 30, "centerY": 0, "defaultPad": {"width": 40, "height": 40}}, "p2"),
        # --- PCB: three placements ----------------------------------------
        _dochead("PCB", "pcb1"),
        _line("COMPONENT", {"x": 0, "y": 0, "angle": 0, "attrs": {}}, "c1"),
        _line("ATTR", {"parentId": "c1", "key": "Designator", "value": "U1"}),
        _line("ATTR", {"parentId": "c1", "key": "Device", "value": "dev1"}),
        _line("ATTR", {"parentId": "c1", "key": "Footprint", "value": "fp1"}),
        _line("COMPONENT", {"x": 500, "y": 0, "angle": 0, "attrs": {}}, "c2"),
        _line("ATTR", {"parentId": "c2", "key": "Designator", "value": "U2"}),
        _line("ATTR", {"parentId": "c2", "key": "Device", "value": "dev2"}),
        _line("ATTR", {"parentId": "c2", "key": "Footprint", "value": "fp1"}),
        _line("COMPONENT", {"x": 900, "y": 0, "angle": 0, "attrs": {}}, "c3"),
        _line("ATTR", {"parentId": "c3", "key": "Designator", "value": "U3"}),
        _line("ATTR", {"parentId": "c3", "key": "Device", "value": "dev3"}),
        _line("ATTR", {"parentId": "c3", "key": "Footprint", "value": "fp1"}),
        _line("PAD_NET", {"padNet": "+24V"}, '["PAD_NET","c1","1","p1"]'),
        _line("PAD_NET", {"padNet": "+5V"}, '["PAD_NET","c1","2","p2"]'),
        _line("PAD_NET", {"padNet": "GND"}, '["PAD_NET","c2","1","p1"]'),
        _line("PAD_NET", {"padNet": ""}, '["PAD_NET","c2","2","p2"]'),
        _line("PAD_NET", {"padNet": "VCC"}, '["PAD_NET","c3","1","p1"]'),
    ]
)


# --------------------------------------------------------------------------
# synthetic: symbol_pin_names
# --------------------------------------------------------------------------


def test_symbol_pin_names_reads_number_and_name():
    names = symbol_pin_names(_source_from_text(SYNTHETIC_NAMED))
    assert names["sym1"] == {"1": "VIN", "2": "VOUT"}
    # Pin Name emitted *before* Pin Number still lands on the right pin.
    assert names["sym2"] == {"1": "GND/ADJ", "2": "NC"}


def test_symbol_pin_names_survive_displaced_attributes():
    """A pin's attributes appended after the last PIN are still its own.

    The 3.2.186 incremental save this reproduces (``sym1`` above) is why the
    walk files attributes by ``parentId``: attributing by position hands every
    one of them to whichever pin happens to be open last.
    """
    names = symbol_pin_names(_source_from_text(SYNTHETIC_NAMED))
    assert names["sym1"] == {"1": "VIN", "2": "VOUT"}


def test_symbol_pin_names_empty_without_symbol_documents():
    text = "\n".join(
        [
            _dochead("DEVICE", "dev1"),
            _line("META", {"title": "R_10k", "attributes": {"Symbol": "symX"}}, "META"),
        ]
    )
    assert symbol_pin_names(_source_from_text(text)) == {}


def test_build_design_model_fills_pin_names_through_the_library():
    model = build_design_model(_source_from_text(SYNTHETIC_NAMED))
    assert [(p.number, p.name, p.net) for p in model.components["U1"].pins] == [
        ("1", "VIN", "+24V"),
        ("2", "VOUT", "+5V"),
    ]
    assert [(p.number, p.name, p.net) for p in model.components["U2"].pins] == [
        ("1", "GND/ADJ", "GND"),
        ("2", "NC", None),
    ]


def test_device_without_a_symbol_pointer_leaves_names_empty():
    """U3's DEVICE declares no ``Symbol``; its pins keep ``name=""``.

    An absent name is not an empty name the parser read — it is a name it could
    not find, and every consumer must be able to tell those apart.
    """
    model = build_design_model(_source_from_text(SYNTHETIC_NAMED))
    u3 = model.components["U3"]
    assert [(p.number, p.name, p.net) for p in u3.pins] == [
        ("1", "", "VCC"), ("2", "", None),
    ]


def test_pin_names_do_not_disturb_connectivity():
    """The change is additive: numbers and nets are byte-for-byte unchanged."""
    model = build_design_model(_source_from_text(SYNTHETIC_NAMED))
    assert {net: sorted(net_obj.pins) for net, net_obj in model.nets.items()} == {
        "+24V": [("U1", "1")],
        "+5V": [("U1", "2")],
        "GND": [("U2", "1")],
        "VCC": [("U3", "1")],
    }


# --------------------------------------------------------------------------
# fixtures: the acceptance boards, pin by pin
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "designator, expected",
    [
        # LM5164 buck, SO-8-EP. Every pin, including the three the rules care
        # about most: 5=FB (the divider tap), 8=SW (the inductor node), 9=EP
        # (the thermal pad, tied to PGND).
        ("U11", [("1", "GND"), ("2", "VIN"), ("3", "EN/UVLO"), ("4", "RON"),
                 ("5", "FB"), ("6", "PGOOD"), ("7", "BST"), ("8", "SW"), ("9", "EP")]),
        # TPLP2981 LDO: pin 5 is VOUT (measured on net $1N66627).
        ("U6", [("1", "VIN"), ("2", "GND"), ("3", "EN"), ("4", "NC"), ("5", "VOUT")]),
        ("U5", [("1", "VIN"), ("2", "GND"), ("3", "EN"), ("4", "NC"), ("5", "VOUT")]),
    ],
)
def test_bishe_foc_pin_names(designator, expected):
    model = build_design_model(load_epro2_source(FOC_100))
    component = model.components[designator]
    assert [(p.number, p.name) for p in component.pins] == expected


def test_bishe_foc_regulator_pin_nets_line_up_with_the_names():
    """The name and the net must agree, or the join has mis-attached a pin."""
    model = build_design_model(load_epro2_source(FOC_100))
    by_number = {p.number: p for p in model.components["U11"].pins}
    assert by_number["2"].net == "+24V"   # VIN
    assert by_number["9"].net == "PGND"   # EP
    assert by_number["6"].net is None      # PGOOD, unconnected
    u6 = {p.number: p for p in model.components["U6"].pins}
    assert u6["1"].net == "+5V"           # VIN
    assert u6["4"].net is None            # NC


def test_robot_board_pin_names():
    model = build_design_model(load_epro2_source(ROBOT))
    assert [(p.number, p.name) for p in model.components["U8"].pins] == [
        ("1", "GND/ADJ"), ("2", "Output"), ("3", "Input"), ("4", "Output"),
    ]


def test_pcb_and_schematic_views_agree_on_pin_names():
    """The two views of one board must not disagree about a pin's identity.

    Before 131a the pcb view had no names at all while the schematic view had
    them, so a rule that ran on one view and a human reading the other saw
    different parts.
    """
    from boardwise.parsers.schematic import build_project_model

    pcb = build_design_model(load_epro2_source(FOC_100))
    sch = build_project_model(FOC_100).boards[0]
    for designator in ("U11", "U5", "U6", "U20"):
        pcb_names = {p.number: p.name for p in pcb.components[designator].pins}
        sch_names = {p.number: p.name for p in sch.components[designator].pins}
        assert pcb_names == sch_names


# --------------------------------------------------------------------------
# pin_role
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, role",
    [
        ("VIN", "IN"), ("VCC", "IN"), ("VDD", "IN"), ("VDDA", "IN"), ("VM", "IN"),
        ("VBUS", "IN"), ("VBAT", "IN"), ("Input", "IN"), ("V+", "IN"),
        ("VOUT", "OUT"), ("VOUTA", "OUT"), ("Output", "OUT"),
        ("SW", "SW"), ("LX", "SW"),
        ("FB", "FB"), ("VFB", "FB"),
        ("EN", "EN"), ("ENABLE", "EN"), ("CE", "EN"),
        ("BST", "BST"),
        ("EP", "EP"), ("EPAD", "EP"),
        ("GND", "GND"), ("AGND", "GND"), ("PGND", "GND"), ("VSS", "GND"),
        ("VSSA", "GND"), ("VEE", "GND"), ("0V", "GND"),
    ],
)
def test_pin_role_known_names(name, role):
    assert pin_role(name) == role


@pytest.mark.parametrize(
    "name",
    ["NC", "PGOOD", "RON", "RESV", "REGOUT",
     "INA", "INB", "INA+", "INA-", "INB+", "INB-", "OUTA", "OUTB",
     "OUT A", "OUT B", "IN A+", "IN A-",
     "+", "-", "15V+", "A", "K", "D", "S", "R", "G", "C",
     "PA7", "BOOT0", "nFAULT", "SDA", "SCK", "CANH",
     "", "   ", None],
)
def test_pin_role_declines(name):
    """No role is claimed for a name that does not declare one.

    ``PGOOD`` and ``RON`` are the two the task names explicitly: both are real
    pins with real jobs and neither is a supply role, so guessing ``OUT`` for
    them would put a decoupling rule on a status pin.
    """
    assert pin_role(name) is None


@pytest.mark.parametrize(
    "name, role",
    [
        # The compound names the fixtures actually carry.
        ("EN/UVLO", "EN"),   # 毕设FOC U11.3, 高速板 U7.3
        ("VEE/GND", "GND"),  # 毕设FOC U14/15/16.4, measured on net AGND
        ("GND/ADJ", "GND"),  # ROBOT U8.1
        ("VSS_1", "GND"),    # underscore-joined family
    ],
)
def test_pin_role_splits_compound_names(name, role):
    assert pin_role(name) == role


def test_ground_outranks_out_in_a_compound_name():
    """``VEE/GND`` is a return written beside a supply name, not an output.

    This is the load-bearing ordering decision: reading it as ``OUT`` would put
    a decoupling rule on a ground pad.
    """
    assert pin_role("VEE/GND") == "GND"
    assert ROLE_PRECEDENCE.index("GND") < ROLE_PRECEDENCE.index("OUT")


def test_blocklisted_token_voids_a_compound_name():
    """A channel half written beside a direction word is still a channel pin."""
    assert pin_role("INA/OUT") is None


def test_pin_role_is_case_and_space_insensitive():
    assert pin_role("fb") == "FB"
    assert pin_role("  fb  ") == "FB"
    assert pin_role("Fb") == "FB"


def test_pin_role_never_returns_a_role_outside_the_declared_set():
    """Every value the table can produce is one of PIN_ROLES."""
    probes = [
        "VIN", "VOUT", "SW", "FB", "EN/UVLO", "BST", "EP", "GND",
        "VEE/GND", "GND/ADJ", "LX", "VSS", "Output", "NC", "", "PA7",
    ]
    assert all(pin_role(name) in PIN_ROLES for name in probes if pin_role(name))