"""143c: the seven holes `outputs/143_dig/03/report.md` found in `readability.py`.

Each case here is the *family*, not the witness the dig script happened to hit:
`outputs/143_dig/03/p*.py` is the "before", and what these tests pin is the rule —
one ruler for a spec pin's spelling, a flag's glyph as an object of the text and
page constraints, a reason sentence that says what it actually measured, one
object per rule, and "the other module" meaning *another* module.

Fixtures are handwritten literals, like `test_053b_readability.py`: the contract
is "what the checker reads from the plan and the two specs", and a generator
fixture would drag the generator's behaviour into it.
"""

from __future__ import annotations

import pytest

from boardwise.core.circuitspec import (
    CircuitSpec,
    SpecNet,
    SpecNoConnect,
    SpecPart,
)
from boardwise.core.layoutplan import (
    LayoutEvidence,
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core.pagelayoutplan import PageLayoutPlan, PageModule
from boardwise.core.presentationspec import PresentationModule, PresentationSpec
from boardwise.core.symbolprofile import (
    SymbolPin,
    SymbolProfile,
    flag_glyph_box,
)
from boardwise.engines import pagecompiler, readability
from boardwise.engines.readability import (
    KIND_GEOMETRY_OUTSIDE_FRAMES,
    KIND_NC_PIN_CONNECTED,
    KIND_NETLIST_PARTITION,
    KIND_OUT_OF_PAGE,
    KIND_SHARED_NET_EXPRESSION_SPLIT,
    KIND_TEXT_OVERLAP,
    UNMEASURED,
    check,
    check_page,
)

HASH = "a" * 64
RES = "R-VERT"
DIODE = "DIODE-2P"
REG = "REG-4P"
FLAG = "PWR-VCC"

#: number "1"/"2", name "A"/"K" — the flyback D1 shape the 115-② comment in
#: `_role_node_expectations` describes. One pad, two legal spellings.
DIODE_PROFILE = SymbolProfile(
    symbol_ref=DIODE, title="Diode", body=(-10.0, -20.0, 10.0, 20.0),
    pins=[
        SymbolPin(number="1", tip=(0.0, 50.0), name="A", direction="up"),
        SymbolPin(number="2", tip=(0.0, -50.0), name="K", direction="down"),
    ],
)
RES_PROFILE = SymbolProfile(
    symbol_ref=RES, title="Resistor", body=(-10.0, -20.0, 10.0, 20.0),
    pins=[
        SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
        SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
    ],
)
#: The measured AMS1117 shape (`role_siblings`'s own docstring): one electrical
#: role on two pads, on opposite sides, with *different* names "VOUT"/"VO".
REG_PROFILE = SymbolProfile(
    symbol_ref=REG, title="Regulator, 4-pin", body=(-20.0, -20.0, 20.0, 20.0),
    pins=[
        SymbolPin(number="1", tip=(50.0, 0.0), name="VOUT", direction="right",
                  electrical_role="VOUT"),
        SymbolPin(number="2", tip=(-50.0, 0.0), name="VO", direction="left",
                  electrical_role="VOUT"),
        SymbolPin(number="3", tip=(0.0, -50.0), name="GND", direction="down"),
        SymbolPin(number="4", tip=(0.0, 50.0), name="VIN", direction="up"),
    ],
)
#: A pin-less profile **is** what this repo calls a flag (053B's convention): the
#: origin is the connection point and the body is the glyph, hanging away from it.
FLAG_PROFILE = SymbolProfile(
    symbol_ref=FLAG, title="Power-VCC", body=(-6.0, 0.0, 6.0, 18.0), pins=[],
)
PROFILES = {
    DIODE: DIODE_PROFILE, RES: RES_PROFILE, REG: REG_PROFILE, FLAG: FLAG_PROFILE,
}


def _plan(**named) -> LayoutPlan:
    return LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        **named,
    )


def _kinds(result, kind) -> list:
    return [item for item in result.hard_violations if item.kind == kind]


def _one_module(part_id: str) -> PresentationSpec:
    return PresentationSpec(
        modules=[PresentationModule(id="main", parts=[part_id])],
        grammar_ref="voltage-divider",
    )


# ------------------------------------------------------------------ H1 --------
# The NC exclusion set was built from the spec's raw spelling while the derived
# netlist keys on the profile's numbers, so the same pad spelled `D1.K` was not
# excluded and got a second, wrongly-attributed violation on top of constraint 8.


def _h1_plan() -> LayoutPlan:
    """D1 at (100, 300), R2 at (100, 100); a wire joins D1.2's tip to R2.1's."""
    return _plan(
        parts=[
            LayoutPart(part_id="D1", symbol_ref=DIODE, symbol_hash=HASH,
                       x=100.0, y=300.0),
            LayoutPart(part_id="R2", symbol_ref=RES, symbol_hash=HASH,
                       x=100.0, y=100.0),
        ],
        segments=[LayoutSegment(net="VIN", points=[(100.0, 250.0), (100.0, 150.0)])],
    )


def _h1_circuit(nc_spelling: str) -> CircuitSpec:
    return CircuitSpec(
        parts=[
            SpecPart(id="D1", symbol_ref=DIODE, value="SS34"),
            SpecPart(id="R2", symbol_ref=RES, value="10k"),
        ],
        nets=[SpecNet(id="VIN", cls="power", members=["R2.1"])],
        nc=[SpecNoConnect(pin=nc_spelling)],
    )


@pytest.mark.parametrize("spelling", ["D1.K", "D1.2"])
def test_an_nc_pin_is_found_whatever_token_the_spec_spells_it_with(spelling):
    """H1, the witness: both spellings name pin 2, so both must give one finding.

    Two rulers gave two answers — 2 hard violations for `D1.K` (constraint 8 plus
    a `netlist-partition-mismatch` blaming the drawing for an "undeclared
    connection" that the spec's own NC declared) against 1 for `D1.2`.
    """
    result = check(_h1_plan(), _h1_circuit(spelling), _one_module("D1"), PROFILES)
    assert len(result.hard_violations) == 1
    found = _kinds(result, KIND_NC_PIN_CONNECTED)
    assert len(found) == 1
    # The object name is the key both documents share, while the evidence still
    # quotes the spec's own token: `pins[D1.K]` is not a key the netlist has.
    assert found[0].objects == (f"circuitSpec.nc[{spelling}]", "pins[D1.2]")
    assert spelling in found[0].evidence


def test_an_nc_pin_is_excluded_from_the_naming_check_too():
    """H1, the third use of the one set: a name on an NC node is not a mismatch.

    Constraint 8 already owns "the NC pin got connected"; constraint 1's naming
    loop skipping only the *raw* spelling made an NC pin spelled by name report
    the same mistake a second time as "the spec does not put them on any net".
    """
    plan = _plan(
        parts=[
            LayoutPart(part_id="D1", symbol_ref=DIODE, symbol_hash=HASH,
                       x=100.0, y=300.0),
            LayoutPart(part_id="R2", symbol_ref=RES, symbol_hash=HASH,
                       x=100.0, y=100.0),
        ],
        labels=[LayoutLabel(net="VIN", text="VIN", x=100.0, y=250.0,
                            bbox=(102.0, 240.0, 120.0, 260.0))],
    )
    result = check(plan, _h1_circuit("D1.K"), _one_module("D1"), PROFILES)
    assert _kinds(result, KIND_NC_PIN_CONNECTED), "the label is a conductor on it"
    assert _kinds(result, KIND_NETLIST_PARTITION) == []


def test_the_three_readers_of_nc_share_one_normalised_set():
    """H1, the structural half: one set, not three normalisations.

    `_canonical_nc_pins` is the single answer, and constraint 1's domain skip,
    constraint 8's lookup and the role-sibling guard all read it. If a future
    edit gives one of them its own ruler, this fails before the dig does.
    """
    circuit = _h1_circuit("D1.K")
    assert readability._canonical_nc_pins(circuit, PROFILES) == {"D1.2"}
    # The name spelling names the profile's number, and a token the profile
    # genuinely lacks stays itself (constraint 9's "no such pin").
    assert readability._canonical_pin(circuit, PROFILES, "D1.K") == "D1.2"
    assert readability._canonical_pin(circuit, PROFILES, "D1.9") == "D1.9"
    assert readability._canonical_pin(circuit, PROFILES, "D9.1") == "D9.1"


# ------------------------------------------------------------------ H2 --------
# The role-sibling NC guard compared a bare token ("2") against dotted keys
# ({"U1.2"}), so it never fired and a correctly drawn NC sibling was demanded to
# be wired.


def _h2_circuit(nc_spelling: str) -> CircuitSpec:
    return CircuitSpec(
        parts=[SpecPart(id="U1", symbol_ref=REG, value="AMS1117-3.3")],
        nets=[SpecNet(id="5V", cls="power", members=["U1.VOUT"])],
        nc=[SpecNoConnect(pin=nc_spelling)],
    )


def _h2_plan() -> LayoutPlan:
    """U1 at (200, 200): pad 1 (250, 200) wired to a 5V flag, pad 2 (150, 200) bare.

    That is the correct drawing of "one role on two pads, pad 2 explicitly NC".
    """
    return _plan(
        parts=[LayoutPart(part_id="U1", symbol_ref=REG, symbol_hash=HASH,
                          x=200.0, y=200.0)],
        segments=[LayoutSegment(net="5V", points=[(250.0, 200.0), (350.0, 200.0)])],
        power_symbols=[LayoutPowerSymbol(symbol_ref="PWR-5V", symbol_hash=HASH,
                                         net="5V", x=350.0, y=200.0)],
    )


@pytest.mark.parametrize("spelling", ["U1.VO", "U1.2"])
def test_an_nc_role_sibling_is_not_demanded_to_be_wired(spelling):
    """H2: a correct drawing, refused for doing exactly what the spec said."""
    result = check(_h2_plan(), _h2_circuit(spelling), _one_module("U1"), PROFILES)
    assert result.hard_violations == []


def test_the_nc_sibling_guard_reads_the_key_the_netlist_stores():
    """H2, the structural half: the guard is live, in the netlist's key space.

    The NC pad is *out* of the expectation map (so `_check_netlist` cannot demand
    it), and the sibling that is *not* NC is still in (so the rule still holds).
    """
    expectations = readability._role_node_expectations(_h2_circuit("U1.VO"), PROFILES)
    assert expectations == {"U1.1": "5V"}
    assert readability._role_node_expectations(_h2_circuit("U1.2"), PROFILES) == {
        "U1.1": "5V"
    }


# ------------------------------------------------------------------ H3 --------
# A `LayoutPowerSymbol` had no box in any of the checker's object sets, so a rail
# flag's glyph could lie on a body, over a label, off the page or inside a
# keep-out with every constraint silent.


def _h3_components(anchor, *, as_label):
    """The same glyph box at the same place, once as a flag and once as a label."""
    glyph = flag_glyph_box(FLAG_PROFILE, rotation=0.0, anchor=anchor)
    part = LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                      x=100.0, y=100.0)
    label = LayoutLabel(net="VCC", text="VCC", x=100.0, y=50.0,
                        bbox=(102.0, 40.0, 120.0, 60.0))
    circuit = CircuitSpec(
        parts=[SpecPart(id="R1", symbol_ref=RES, value="10k")],
        nets=[SpecNet(id="VCC", cls="power", members=["R1.2"])],
    )
    if as_label:
        plan = _plan(parts=[part], labels=[label, LayoutLabel(
            net="VCC", text="VCC", x=anchor[0], y=anchor[1], bbox=glyph)])
    else:
        plan = _plan(parts=[part], labels=[label], power_symbols=[
            LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH, net="VCC",
                              x=anchor[0], y=anchor[1])])
    return plan, circuit, glyph


@pytest.mark.parametrize("as_label", [True, False])
def test_a_flag_glyph_on_a_body_is_a_text_overlap_just_as_a_label_is(as_label):
    """Uh H3, constraint 5: the glyph is a net name printed on the canvas."""
    plan, circuit, glyph = _h3_components((100.0, 110.0), as_label=as_label)
    result = check(plan, circuit, _one_module("R1"), PROFILES)
    found = _kinds(result, KIND_TEXT_OVERLAP)
    assert len(found) == 1
    assert "parts[R1]" in found[0].objects
    assert readability._overlap(glyph, (90.0, 80.0, 110.0, 120.0))


@pytest.mark.parametrize("as_label", [True, False])
def test_a_flag_glyph_that_leaves_the_page_is_reported(as_label):
    """H3, constraint 6's page half."""
    plan, circuit, _glyph = _h3_components((1005.0, 100.0), as_label=as_label)
    result = check(plan, circuit, _one_module("R1"), PROFILES,
                   page_box=(0.0, 0.0, 1000.0, 800.0))
    found = _kinds(result, KIND_OUT_OF_PAGE)
    assert len(found) == 1
    assert found[0].objects[0].startswith("powerSymbols" if not as_label else "labels")
    assert "leaves the page" in found[0].evidence


@pytest.mark.parametrize("as_label", [True, False])
def test_a_flag_glyph_inside_a_keep_out_is_reported(as_label):
    """H3, constraint 6's keep-out half — and the flag half of it too."""
    plan, circuit, _glyph = _h3_components((100.0, 110.0), as_label=as_label)
    result = check(plan, circuit, _one_module("R1"), PROFILES,
                   page_box=(-1000.0, -1000.0, 1000.0, 1000.0),
                   keepouts=[(95.0, 100.0, 115.0, 130.0)])
    inside = [
        item for item in _kinds(result, KIND_OUT_OF_PAGE)
        if "keep-out" in item.evidence
    ]
    what = "labels[1]" if as_label else "powerSymbols[0]"
    assert any(item.objects == (what,) for item in inside)


def test_the_flag_glyph_is_in_the_text_box_set_and_has_no_owner():
    """H3, the structural half: `_text_boxes` now honours its own docstring.

    It said "every text on the canvas" while returning two of the three kinds.
    The flag's owner is empty on purpose: it belongs to no part, so constraint 5
    treats its name as foreign to every body.
    """
    plan, _circuit, glyph = _h3_components((200.0, 110.0), as_label=False)
    boxes = {
        name: (box, owner, text)
        for name, box, owner, text in readability._text_boxes(plan, PROFILES)
    }
    assert boxes["powerSymbols[0]"][0] == flag_glyph_box(
        FLAG_PROFILE, rotation=0.0, anchor=(200.0, 110.0)
    )
    assert boxes["powerSymbols[0]"][1] == ""
    assert boxes["powerSymbols[0]"][2] == "VCC"
    assert boxes["powerSymbols[0]"][0] == glyph


def test_a_flag_whose_symbol_has_no_profile_adds_no_box_and_raises_nothing():
    """H3's unmeasurable case: no profile, no glyph extent, no invented box.

    Unlike a *part* (whose missing profile is refused — a pin tip cannot be
    guessed), a flag's box is only ever a bound to check against; a zero-area
    stand-in would silently intersect nothing and read as "checked".
    """
    plan = _plan(
        parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                          x=100.0, y=100.0)],
        power_symbols=[LayoutPowerSymbol(symbol_ref="PWR-UNKNOWN", net="VCC",
                                         x=100.0, y=110.0)],
    )
    assert [name for name, *_ in readability._text_boxes(plan, PROFILES)] == []
    circuit = CircuitSpec(
        parts=[SpecPart(id="R1", symbol_ref=RES, value="10k")],
        nets=[SpecNet(id="VCC", cls="power", members=["R1.2"])],
    )
    result = check(plan, circuit, _one_module("R1"), PROFILES,
                   page_box=(-1000.0, -1000.0, 1000.0, 1000.0))
    assert _kinds(result, KIND_TEXT_OVERLAP) == []
    assert _kinds(result, KIND_OUT_OF_PAGE) == []


def test_a_flag_glyph_over_another_text_box_is_reported():
    """H3, constraint 5's pair half: a flag printed over a value."""
    plan = _plan(
        parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                          x=100.0, y=100.0)],
        texts=[LayoutText(kind="value", text="10k", part_id="R2",
                          bbox=(95.0, 110.0, 115.0, 125.0))],
        power_symbols=[LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH,
                                         net="VCC", x=100.0, y=110.0)],
    )
    result = check(plan, _two_part_circuit(), _one_module("R1"), PROFILES)
    found = _kinds(result, KIND_TEXT_OVERLAP)
    assert any(
        set(item.objects) == {"powerSymbols[0]", "texts[0]"} for item in found
    ), [item.render() for item in found]


def _two_part_circuit() -> CircuitSpec:
    """R1 placed, R2 only referenced by the text above — enough for the box test."""
    return CircuitSpec(
        parts=[
            SpecPart(id="R1", symbol_ref=RES, value="10k"),
            SpecPart(id="R2", symbol_ref=RES, value="10k"),
        ],
        nets=[
            SpecNet(id="VCC", cls="power", members=["R1.2"]),
            SpecNet(id="OUT", cls="signal", members=["R2.1"]),
        ],
    )


# ------------------------------------------------------------------ H4 --------
# `min_text_gap`'s reason sentence counted `gap == 0.0` as "overlap", but that
# number is also what two boxes that merely touch edge to edge get — so it told
# the reader to go look at `text-overlap` violations that did not exist.


def _two_texts(box_b) -> LayoutPlan:
    return _plan(
        parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                          x=100.0, y=100.0)],
        texts=[
            LayoutText(kind="reference", text="R1", part_id="R1",
                       bbox=(0.0, 0.0, 10.0, 10.0)),
            LayoutText(kind="value", text="10k", part_id="R1", bbox=box_b),
        ],
    )


def test_a_touching_text_pair_is_not_reported_as_overlapping():
    """H4, the 121c shape: gap 0, zero text-overlap violations, honest reason."""
    result = check(
        _two_texts((10.0, 0.0, 20.0, 10.0)), _two_part_circuit(),
        _one_module("R1"), PROFILES,
    )
    assert result.soft_metrics["min_text_gap"] == 0.0
    assert _kinds(result, KIND_TEXT_OVERLAP) == []
    reasons = " ".join(result.soft_reasons["min_text_gap"])
    assert "touch edge to edge" in reasons
    assert "genuinely intersect" not in reasons


def test_a_really_overlapping_pair_is_reported_as_overlapping():
    """The other half of the same split, so the sentence cannot be switched off."""
    result = check(
        _two_texts((5.0, 0.0, 15.0, 10.0)), _two_part_circuit(),
        _one_module("R1"), PROFILES,
    )
    assert result.soft_metrics["min_text_gap"] == 0.0
    assert _kinds(result, KIND_TEXT_OVERLAP), "the pair really does intersect"
    reasons = " ".join(result.soft_reasons["min_text_gap"])
    assert "genuinely intersect" in reasons
    assert "touch edge to edge" not in reasons


# ------------------------------------------------------------------ H5 --------
# The label branch of `geometry-outside-module-frames` used an `and`, stricter
# than the "a name anchor" the contract names, and its evidence sentence was
# false in both mixed cases it could fire on.


FRAME = (80.0, 40.0, 120.0, 160.0)  # holds the part's whole extent


def _h5_page(anchor, bbox) -> PageLayoutPlan:
    return PageLayoutPlan(
        plan=_plan(
            parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                              x=100.0, y=100.0)],
            labels=[LayoutLabel(net="VIN", text="VIN", x=anchor[0], y=anchor[1],
                                bbox=bbox)],
        ),
        modules=[PageModule(id="main", parts=["R1"], frame=FRAME)],
        page_box=(-1000.0, -1000.0, 1000.0, 1000.0),
    )


@pytest.mark.parametrize(
    "anchor, bbox, expected, why",
    [
        ((110.0, 100.0), (110.0, 90.0, 118.0, 110.0), 0, "both inside"),
        ((112.0, 100.0), (112.0, 90.0, 140.0, 110.0), 0,
         "the anchor (the named object) is inside; the box reaching past the "
         "frame edge is not this rule's business"),
        ((300.0, 100.0), (110.0, 90.0, 118.0, 110.0), 1,
         "the anchor is outside, whatever the box says"),
        ((300.0, 100.0), (300.0, 90.0, 320.0, 110.0), 1, "both outside"),
    ],
)
def test_the_label_object_of_geometry_outside_frames_is_its_anchor(
    anchor, bbox, expected, why
):
    """H5: one object per rule — a name anchor — and a sentence that is true."""
    circuit = CircuitSpec(
        parts=[SpecPart(id="R1", symbol_ref=RES, value="10k")],
        nets=[SpecNet(id="VIN", cls="power", members=["R1.1"])],
    )
    result = check_page(_h5_page(anchor, bbox), circuit, _one_module("R1"), PROFILES)
    found = _kinds(result, KIND_GEOMETRY_OUTSIDE_FRAMES)
    labels = [item for item in found if item.objects[0].startswith("labels")]
    assert len(labels) == expected, why
    for item in labels:
        assert "neither" not in item.evidence
        assert "which is in no module frame" in item.evidence


# ------------------------------------------------------------------ H6 --------
# `shared-net-expression-split` compared the two *lists* of modules for
# non-emptiness rather than asking for two *different* modules, so a single
# module that stated one net both ways was refused with "a label on a and a flag
# on a".


H6_CIRCUIT = CircuitSpec(
    parts=[
        SpecPart(id="R1", symbol_ref=RES, value="10k"),
        SpecPart(id="R2", symbol_ref=RES, value="10k"),
    ],
    nets=[SpecNet(id="VIN", cls="power", members=["R1.1", "R2.1"])],
)
H6_PRESENTATION = PresentationSpec(
    modules=[
        PresentationModule(id="a", parts=["R1"]),
        PresentationModule(id="b", parts=["R2"]),
    ],
    grammar_ref="voltage-divider",
)
H6_FRAME_A = (0.0, 0.0, 200.0, 200.0)
H6_FRAME_B = (300.0, 0.0, 500.0, 200.0)


def _h6_page(*, label_in_a: bool, flag_in_a: bool, flag_in_b: bool):
    plan = _plan(
        parts=[
            LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                       x=50.0, y=50.0),
            LayoutPart(part_id="R2", symbol_ref=RES, symbol_hash=HASH,
                       x=350.0, y=50.0),
        ],
        labels=([LayoutLabel(net="VIN", text="VIN", x=50.0, y=20.0,
                             bbox=(50.0, 10.0, 70.0, 30.0))] if label_in_a else []),
        power_symbols=(
            [LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH, net="VIN",
                               x=160.0, y=100.0)] if flag_in_a else []
        ) + (
            [LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH, net="VIN",
                               x=460.0, y=100.0)] if flag_in_b else []
        ),
    )
    return PageLayoutPlan(
        plan=plan,
        modules=[
            PageModule(id="a", parts=["R1"], frame=H6_FRAME_A),
            PageModule(id="b", parts=["R2"], frame=H6_FRAME_B),
        ],
        page_box=(-100.0, -100.0, 700.0, 400.0),
    )


def _h6_findings(page):
    result = check_page(page, H6_CIRCUIT, H6_PRESENTATION, PROFILES)
    return _kinds(result, KIND_SHARED_NET_EXPRESSION_SPLIT)


def test_one_module_stating_a_net_both_ways_is_one_voice():
    """H6: a label beside the module's own rail flag is not two drawings."""
    found = _h6_findings(_h6_page(label_in_a=True, flag_in_a=True, flag_in_b=False))
    assert found == [], [item.render() for item in found]


def test_two_modules_disagreeing_about_one_net_is_the_rule():
    """H6's positive control: a label on `a` and a flag on `b` still refuses."""
    found = _h6_findings(_h6_page(label_in_a=True, flag_in_a=False, flag_in_b=True))
    assert len(found) == 1
    evidence = found[0].evidence
    assert "a label on a and a flag on b" in evidence
    assert "a flag on a" not in evidence


def test_a_net_stated_with_both_kinds_in_both_modules_is_not_the_rule():
    """The neighbouring shape: neither module is the odd one out."""
    found = _h6_findings(_h6_page(label_in_a=True, flag_in_a=False, flag_in_b=False))
    assert found == []
    found = _h6_findings(_h6_page(label_in_a=False, flag_in_a=True, flag_in_b=True))
    assert found == []


# ------------------------------------------------------------------ H7 --------
# The `-1` sentinel: a real *ratio* could spell it exactly, and it could enter an
# ascending ranking key as if it were the smallest measurement.


def test_a_ratio_never_spells_the_unmeasured_sentinel():
    """H7, the collision: `occupied == 2.0` used to give `whitespace == -1.0`.

    `UNMEASURED` is negative and the ratio is `1 - occupied`, so an out-of-domain
    measurement was written in the same number as "cannot measure". The ratio is
    clamped into its own domain instead: boxes covering more than the whole page
    are constraint 6's finding, not a second way to say "unmeasured".
    """
    # A page of 10x10 = 100 units^2 covered by exactly two 10x10 boxes that do
    # not overlap: the union is 200, so `occupied == 2.0` and the old complement
    # was `1.0 - 2.0 == -1.0`, i.e. the sentinel, to the last bit.
    plan = _plan(
        parts=[],
        texts=[
            LayoutText(kind="reference", text="R1", part_id="R1",
                       bbox=(0.0, 0.0, 10.0, 10.0)),
            LayoutText(kind="value", text="10k", part_id="R1",
                       bbox=(10.0, 0.0, 20.0, 10.0)),
        ],
    )
    result = check(plan, _two_part_circuit(), _one_module("R1"), PROFILES,
                   page_box=(0.0, 0.0, 10.0, 10.0))
    assert 1.0 - 2.0 == UNMEASURED, "the collision this test exists for"
    assert result.soft_metrics["occupied_ratio"] == 1.0
    assert result.soft_metrics["whitespace_ratio"] == 0.0
    assert result.soft_metrics["whitespace_ratio"] != UNMEASURED
    assert "clamped" in " ".join(result.soft_reasons["whitespace_ratio"])


def test_a_measured_ratio_is_still_measured():
    """H7's positive control: the clamp does not touch a ratio inside [0, 1]."""
    plan = _plan(
        parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                          x=100.0, y=100.0)],
    )
    result = check(plan, _two_part_circuit(), _one_module("R1"), PROFILES,
                   page_box=(0.0, 0.0, 100.0, 100.0))
    assert result.soft_metrics["occupied_ratio"] == pytest.approx(800.0 / 10000.0)
    assert result.soft_metrics["whitespace_ratio"] == pytest.approx(1.0 - 0.08)


def test_the_page_ranking_key_cannot_be_won_by_an_unmeasured_metric():
    """H7, the ranking half: the sentinel may not enter an ascending key.

    `page_layered_key`'s compactness layer is compared ascending, so
    `page_area = -1` (no frames on the page) used to outrank every real page.
    The key now reads absence as the worst value — and a *missing* key too, which
    used to default to `0.0` and claim "zero crossings" for a page nobody
    measured.
    """
    page = PageLayoutPlan(
        plan=_plan(),
        page_evidence=LayoutEvidence(soft_metrics={"page_area": UNMEASURED}),
    )
    assert pagecompiler._measure(page).key[-1] == float("inf")

    measured = PageLayoutPlan(
        plan=_plan(),
        page_evidence=LayoutEvidence(soft_metrics={"page_area": 40000.0}),
    )
    assert pagecompiler._measure(measured).key[-1] == 40000.0
    assert (
        pagecompiler._measure(measured).key < pagecompiler._measure(page).key
    )

    assert pagecompiler._rankable({}, "page_crossings") == float("inf")
    assert pagecompiler._rankable({"page_crossings": 0.0}, "page_crossings") == 0.0
    assert pagecompiler._rankable({"page_crossings": float("nan")}, "page_crossings") == float("inf")


def test_page_area_is_still_the_sentinel_in_the_evidence():
    """H7's boundary: the *evidence* keeps `UNMEASURED`; only the key may not.

    The document is where "there is no value" is stated, and a reader can see it;
    what changed is that a comparison never treats it as one.
    """
    result = check_page(
        PageLayoutPlan(
            plan=_plan(
                parts=[LayoutPart(part_id="R1", symbol_ref=RES, symbol_hash=HASH,
                                  x=100.0, y=100.0)],
            ),
            modules=[],
            page_box=(0.0, 0.0, 1000.0, 1000.0),
        ),
        CircuitSpec(parts=[SpecPart(id="R1", symbol_ref=RES, value="10k")], nets=[]),
        PresentationSpec(modules=[], grammar_ref="voltage-divider"),
        PROFILES,
    )
    assert result.soft_metrics["page_area"] == UNMEASURED
    assert "no module on the page" in result.soft_reasons["page_area"][0]
