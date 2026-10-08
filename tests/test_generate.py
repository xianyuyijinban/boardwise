"""Tests for the 006 action-plan generator (``engines.generate``, rev 3/4).

The golden board is the real fixture: the plan must cover every component
and every multi-pin net of it, leave the NC pins explicitly listed, put
the host chip and its decoupling capacitors where the task says they go —
and, since revision 3, carry ZERO self-check violations.
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.generate import (
    DEFAULT_NAMING_STRATEGY,
    NAMING_STRATEGIES,
    _is_power_net,
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

GOLDEN = "tests/fixtures/ch340_golden.epro2"


@pytest.fixture(scope="module")
def golden() -> DesignModel:
    return build_schematic_model(GOLDEN)


@pytest.fixture(scope="module")
def golden_offsets() -> dict:
    return canvas_pin_offsets(build_pin_offsets(GOLDEN))


@pytest.fixture(scope="module")
def golden_plan(golden, golden_offsets):
    """Built once: `generate_plan` is a few seconds of grid search per call."""
    return generate_plan(golden, golden_offsets)


# --------------------------------------------------------------------------
# generate_plan on the real golden board
# --------------------------------------------------------------------------


def test_plan_covers_every_component(golden, golden_plan):
    plan = golden_plan
    placed = {step.designator for step in plan.placements}
    assert placed == set(golden.components)


def test_plan_host_chip_is_first(golden, golden_plan):
    plan = golden_plan
    # U1 (CH340G) has 16 pins — more than anything else on the board.
    assert plan.placements[0].designator == "U1"


def test_plan_places_decoupling_caps_beside_the_host(golden, golden_plan):
    plan = golden_plan
    order = [s.designator for s in plan.placements]
    by_des = {p.designator: p for p in plan.geometry}
    # Cap-like parts sharing a net with U1 (the V3 and crystal caps) come
    # right after it in placement order — and land in the same shelf row,
    # i.e. their boxes share U1's band. C4/C6/C7 share no net with U1
    # (measured on the golden board), so they don't count.
    caps = ("C1", "C25", "C3")
    for designator in caps:
        assert order.index(designator) == 1 + caps.index(designator)
    u1_band = (by_des["U1"].bbox.y0, by_des["U1"].bbox.y1)
    for designator in caps:
        box = by_des[designator].bbox
        assert box.y0 < u1_band[1] and box.y1 > u1_band[0], (
            f"{designator} should share the host's row band"
        )


def test_plan_lists_nc_pins_explicitly(golden, golden_plan):
    plan = golden_plan
    nc = set(plan.nc_pins)
    # Golden U1 pins 9-15 are NO_CONNECT in the schematic.
    assert {f"U1.{n}" for n in range(9, 16)} <= {f"{d}.{p}" for d, p in nc}


def test_plan_resolution_prefers_lcsc_then_keyword(golden, golden_plan):
    plan = golden_plan
    by_des = {s.designator: s for s in plan.placements}
    # U1 resolves by LCSC: its DEVICE META carries C14267 (joined since F1 —
    # before the join the instance's empty `Supplier Part` was all we saw).
    assert by_des["U1"].lcsc == "C14267"
    # R24 has no LCSC in the instance *or* the DEVICE META, so the keyword
    # path must carry it — and the keyword must be footprint-constrained, or
    # a bare "5.1K" resolves to whatever 5.1K part the library ranks first
    # (round 4, §E: the golden 0402 became a 0603 and every wire missed).
    assert by_des["R24"].lcsc == ""
    assert by_des["R24"].footprint == "0402"
    assert by_des["R24"].keyword == "5.1K 0402"


def test_plan_is_stable(golden, golden_offsets, golden_plan):
    """Pure: the same model and offsets give the same plan, every time."""
    assert generate_plan(golden, golden_offsets) == golden_plan


def test_empty_model_yields_note():
    plan = generate_plan(DesignModel(), {})
    assert plan.placements == []
    assert plan.notes


def test_golden_plan_wires_every_multi_pin_net(golden, golden_plan):
    """Every multi-pin net is *wired*, under any naming policy.

    The second half of what 006b asserted, and the one that is still true: a
    net's existence is carried by its wires (the editor's netlist reads the
    wire's own net attribute, measured 2026-09-14), never by a name.
    """
    plan = golden_plan
    multi = {
        name
        for name, net in golden.nets.items()
        if len(net.pins) >= 2
    }
    wired = {wire.net for wire in plan.wires}
    assert multi <= wired, "every multi-pin net is wired"


def test_golden_plan_names_only_the_nets_that_need_a_name(golden, golden_plan):
    """134: naming is on demand, so the set of names is a *subset*, not an equality.

    The CH340G golden board's longest signal net runs 1395 units, under
    :data:`LONG_NET_LABEL_UNITS`, and it is single-page — so under ``auto`` its
    signal nets carry no name and only the rails are flagged. The invariant that
    matters is the one this pins: **no signal net is named outside the policy**,
    and every rail still is.
    """
    from boardwise.engines.layout import _net_kind

    plan = golden_plan
    multi = {
        name
        for name, net in golden.nets.items()
        if len(net.pins) >= 2
    }
    named = {step.net for step in plan.net_names}
    assert named <= multi, "a name was placed on a net that has fewer than two pins"
    rails = {name for name in multi if _net_kind(name) in ("Ground", "Power")}
    assert rails <= named, "every rail keeps its flag"
    assert plan.naming_strategy == "auto"


def test_every_golden_name_lands_on_its_wire(golden, golden_plan):
    """A name that got placed still has to be attached — on-demand is not care-free.

    The rails' flags are the names this board still places under ``auto``, and
    each must sit on its own wire's geometry.
    """
    def on_wire(point, wire_points):
        for (ax, ay), (bx, by) in zip(wire_points, wire_points[1:]):
            if abs(ay - by) < 1e-9 and abs(point[1] - ay) < 0.51 and \
                    min(ax, bx) - 0.51 <= point[0] <= max(ax, bx) + 0.51:
                return True
            if abs(ax - bx) < 1e-9 and abs(point[0] - ax) < 0.51 and \
                    min(ay, by) - 0.51 <= point[1] <= max(ay, by) + 0.51:
                return True
        return False

    plan = golden_plan
    assert plan.net_names, "rails are still flagged"
    for step in plan.net_names:
        assert any(
            on_wire((step.x, step.y), wire.points)
            for wire in plan.wires
            if wire.net == step.net
        ), f"net {step.net} annotation at {step.x},{step.y} floats off its wire"


# --------------------------------------------------------------------------
# synthetic models: naming rules
# --------------------------------------------------------------------------


def _synthetic_model() -> DesignModel:
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.components["R1"] = Component(
        uid="r1", designator="R1", pins=[Pin(number="1", name="")]
    )
    model.nets["GND"] = Net(name="GND", pins=[("U1", "1"), ("R1", "1")])
    model.nets["RX"] = Net(name="RX", pins=[("U1", "2"), ("R1", "1")])
    # R1.1 doubles as the RX member; give it its own pin instead
    model.components["R1"].pins.append(Pin(number="2", name=""))
    model.nets["RX"].pins = [("U1", "2"), ("R1", "2")]
    return model


def _synthetic_offsets() -> dict:
    return {
        "U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0)},
        "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
    }


def test_power_nets_get_one_flag_on_the_wire():
    plan = generate_plan(_synthetic_model(), _synthetic_offsets())
    gnd_flags = [n for n in plan.net_names if n.net == "GND"]
    assert len(gnd_flags) == 1, "one flag names the whole net"
    assert gnd_flags[0].kind == "Ground"
    assert any(w.net == "GND" for w in plan.wires), "the flag's net is wired"
    assert plan.violations == []


def test_a_negative_supply_is_not_flagged_as_a_ground():
    """``VEE`` is a negative rail, so no ground symbol may hang off it (M0-P0c).

    ``_is_power_net`` is what decides whether a net is drawn as a flag. ``VEE``
    used to answer yes to the ground half of it, which put a symbol meaning
    "this is 0 V" on a supply that is not — so the plan here must name the net
    as an ordinary one and hang no flag on it.
    """
    assert not _is_power_net("VEE")
    assert not _is_power_net("VEE-5V")
    assert not _is_power_net("vee")

    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.components["R1"] = Component(
        uid="r1", designator="R1",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.nets["VEE"] = Net(name="VEE", pins=[("U1", "1"), ("R1", "1")])
    model.nets["SIG"] = Net(name="SIG", pins=[("U1", "2"), ("R1", "2")])
    offsets = {
        "U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0)},
        "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
    }
    plan = generate_plan(model, offsets)
    named = {(step.net, step.kind) for step in plan.net_names}
    assert not any(kind == "Ground" for _, kind in named), named
    assert not any(kind == "Power" for _, kind in named), (
        f"VEE is not a rail this flow flags: {named}"
    )
    # Under the 134 default (``auto``) VEE is a short single-page net and is
    # therefore unnamed; what matters is that *no* flag of any kind hangs on it.
    # Under ``text`` — the pre-134 policy that names everything — it is still
    # named, just as ordinary text and never as a ground symbol.
    under_text = generate_plan(model, offsets, strategy="text")
    text_named = {(step.net, step.kind) for step in under_text.net_names}
    assert ("VEE", "text") in text_named, f"VEE must still be nameable: {text_named}"
    assert not any(kind == "Ground" for _, kind in text_named), text_named
    assert plan.violations == []


def test_signal_nets_get_wires_and_no_name_by_default():
    """134 flipped the default: a short single-page net is read off its wires.

    Everything else this test pinned is still asserted below — the wire exists,
    it is Manhattan, ports stay banned, and the plan self-checks clean. What
    changed is the one line the ruling changed: the net no longer carries a
    decorative text name by default, because in EasyEDA Pro a label is a network
    port in all but name and a screenful of them buries real connections.
    """
    plan = generate_plan(_synthetic_model(), _synthetic_offsets())
    rx_names = [n for n in plan.net_names if n.net == "RX"]
    assert not rx_names, "a short single-page signal net gets no name primitive"
    assert plan.naming_strategy == "auto"
    assert not any(n.kind == "port" for n in plan.net_names), "ports are banned"
    rx_wires = [w for w in plan.wires if w.net == "RX"]
    assert rx_wires, "the signal net is wired"
    for wire in rx_wires:
        for (x1, y1), (x2, y2) in zip(wire.points, wire.points[1:]):
            assert x1 == x2 or y1 == y2, "Manhattan only"
    assert plan.violations == []


def test_the_text_strategy_keeps_its_decorative_name():
    """The pre-134 behaviour survives as a switch, not as a default.

    The decisive assertion is that the *name rides on the wire* too: dropping
    the visible name under ``auto`` must not drop the electrical one.
    """
    plan = generate_plan(_synthetic_model(), _synthetic_offsets(), strategy="text")
    rx_names = [n for n in plan.net_names if n.net == "RX"]
    assert len(rx_names) == 1
    assert rx_names[0].kind == "text", "the text strategy draws the name as text"
    assert rx_names[0].decorative is True
    assert [w for w in plan.wires if w.net == "RX"], "the wire still carries the net"


def test_signal_naming_follows_the_strategy():
    model, offsets = _synthetic_model(), _synthetic_offsets()

    wire_only = generate_plan(model, offsets, strategy="wire")
    assert not [n for n in wire_only.net_names if n.net == "RX"], (
        "the wire carries the name itself; nothing is placed"
    )
    assert [w for w in wire_only.wires if w.net == "RX"], "the wire is still there"

    native = generate_plan(model, offsets, strategy="label")
    rx = [n for n in native.net_names if n.net == "RX"]
    assert len(rx) == 1 and rx[0].kind == "label" and not rx[0].decorative

    auto = generate_plan(model, offsets, strategy="auto")
    assert not [n for n in auto.net_names if n.net == "RX"], (
        "a short single-page net needs no name under auto"
    )

    silent = generate_plan(model, offsets, strategy="none")
    assert not [n for n in silent.net_names if n.net == "RX"]

    # An unknown strategy is reported as the default, never silently obeyed.
    unknown = generate_plan(model, offsets, strategy="nonsense")
    assert unknown.naming_strategy == DEFAULT_NAMING_STRATEGY == "auto"


def test_rails_keep_their_flags_under_every_strategy():
    for strategy in NAMING_STRATEGIES:
        plan = generate_plan(_synthetic_model(), _synthetic_offsets(), strategy=strategy)
        kinds = {n.kind for n in plan.net_names}
        assert kinds <= {"Ground", "Power", "text", "label"}, (
            f"{strategy} produced {kinds}"
        )
        # synthetic model's GND rail is flagged whatever the signal policy is
        assert "Ground" in kinds


def test_missing_offsets_report_no_violations_but_skip_the_net():
    offsets = {"U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0)}}
    plan = generate_plan(_synthetic_model(), offsets)
    # R1 has no offsets: it is parked unbounded (the diff would flag a
    # missing component), but nothing can be wired to or from it
    by_des = {p.designator: p for p in plan.geometry}
    assert by_des["R1"].bbox is None
    assert "RX" not in {n.net for n in plan.net_names}, (
        "a net whose members are not all placeable is not named either"
    )


# --------------------------------------------------------------------------
# dangling nets
# --------------------------------------------------------------------------


def test_strip_dangling_nets_clears_single_member_nets():
    model = _synthetic_model()
    model.nets["DANGLING"] = Net(name="DANGLING", pins=[("U1", "1")])
    # U1.1 now dangles: GND keeps its R1 side only
    model.nets["GND"].pins = [("R1", "1")]
    strip_dangling_nets(model)
    assert "DANGLING" not in model.nets
    assert model.components["U1"].pins[0].net is None
