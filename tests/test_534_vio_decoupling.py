"""534 (VIO follow-up) — the CH343G's VIO rail gets its own local 100 nF.

The gap this file pins is a datasheet obligation the shipped four-island board
did not meet: the CH343G wants a decoupling capacitor on VIO, and the spec's
``VCC`` net — the UART-side I/O level rail the peer board feeds in on the header
— carried only ``U1.15`` and ``H1.9``, i.e. the chip pin and the header pin with
nothing between them.  ``C1`` sits on VDD5 and ``C3`` on the V3 regulator
output, so neither one is the VIO decoupler.

The fix is one part: ``C4`` (``C0603-100nF-C1590``, 100 nF, C1590) from ``VCC``
to ``GND``, placed in the ``ch343_power`` island — the supply group beside the
chip, where ``VCC`` arrives from the header.  That is a drawing placement: the datasheet asks
for the cap on the VIO rail, it does not say this island is where the copper
sits.  These tests read the two specs back and check the electrical facts, not
the drawing: the cap's two ends, which rails they may and may not touch, that
its symbol is one the library can actually draw, and that the island the
presentation promises really carries it.

They are written to fail on the two ways the fix regresses: delete ``C4`` (every
test here loses the part or the decoupler) and put ``C4.1`` on ``+5V`` instead of
``VCC`` (the rail check, the 5 V-confusion check and the local-decoupler check
all go red).  ``evidence/534/vio-decoupling.md`` records both mutations.
"""

from __future__ import annotations

import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
BOARD = "ch343_uart"

VIO = "VCC"
GND = "GND"
FIVE_VOLT = "+5V"
DECOUPLER = "C4"
DECOUPLER_PROFILE = "C0603-100nF-C1590"
DECOUPLER_LCSC = "C1590"


@pytest.fixture(scope="module")
def circuit() -> CircuitSpec:
    return CircuitSpec.load(SPECS / f"{BOARD}.circuit.json")


@pytest.fixture(scope="module")
def presentation() -> PresentationSpec:
    return PresentationSpec.load(SPECS / f"{BOARD}.presentation.json")


@pytest.fixture(scope="module")
def library():
    return drawapply.load_library(SPECS / f"{BOARD}.library.json")


def _net(circuit: CircuitSpec, net_id: str):
    return next(net for net in circuit.nets if net.id == net_id)


def _members(circuit: CircuitSpec, net_id: str) -> list[str]:
    return list(_net(circuit, net_id).members)


def _part(circuit: CircuitSpec, part_id: str):
    return next(part for part in circuit.parts if part.id == part_id)


def _pins_of(circuit: CircuitSpec, part_id: str) -> dict[str, str]:
    """``{"1": "VCC", "2": "GND"}`` — the net each pin of ``part_id`` sits on."""
    pins: dict[str, str] = {}
    for net in circuit.nets:
        for member in net.members:
            owner, _, pin = member.partition(".")
            if owner == part_id:
                assert pin not in pins, f"{part_id}.{pin} is on {pins[pin]} and {net.id}"
                pins[pin] = net.id
    return pins


def test_c4_is_the_vio_decoupler(circuit):
    """``C4`` exists, is a 100 nF C1590, and hangs from VIO to ground."""
    part = _part(circuit, DECOUPLER)
    assert part.value == "100nF", part.value
    assert part.lcsc == DECOUPLER_LCSC, part.lcsc
    assert part.symbol_ref == DECOUPLER_PROFILE, part.symbol_ref
    assert part.provenance == "engineer_confirmed", part.provenance
    assert _pins_of(circuit, DECOUPLER) == {"1": VIO, "2": GND}


def test_the_vio_rail_carries_a_local_100nf_to_ground(circuit):
    """The property, not the designator: VIO has a 100 nF of its own to GND.

    Written over the parts rather than over ``C4``'s name, because the obligation
    is "the rail is decoupled", and a second 100 nF added later (or a renamed
    one) must satisfy it too.  A board whose only VIO members are the chip pin
    and the header pin — today's vanilla state — has no such part.
    """
    decouplers = [
        part.id
        for part in circuit.parts
        if part.value == "100nF"
        and _pins_of(circuit, part.id).get("1") == VIO
        and _pins_of(circuit, part.id).get("2") == GND
    ]
    assert decouplers, (
        "no 100 nF part bridges VCC to GND: "
        f"VCC carries {_members(circuit, VIO)}"
    )


def test_the_vio_end_is_not_the_five_volt_rail(circuit):
    """``C4.1`` is on VIO and VIO is not ``+5V`` — the mistake this batch avoids.

    The datasheet decouples the I/O level rail; the 5 V VBUS rail already has
    ``C1``/``C2``.  Asserting both halves separately means a copy-paste that put
    the cap's top on ``+5V`` fails twice: the pin is missing from ``VCC`` *and*
    it turned up on ``+5V``.
    """
    charge = _members(circuit, VIO)
    assert f"{DECOUPLER}.1" in charge, charge
    assert f"{DECOUPLER}.1" not in _members(circuit, FIVE_VOLT)
    assert not set(charge) & set(_members(circuit, FIVE_VOLT)), (
        "VCC and +5V share a member — the two rails are shorted"
    )
    assert not set(charge) & set(_members(circuit, GND))


def test_the_c4_symbol_is_one_the_library_can_draw(circuit, library):
    """The profile the part names is in the library, and it is a capacitor."""
    assert DECOUPLER_PROFILE in library, sorted(library)
    profile = library[DECOUPLER_PROFILE]
    assert profile.symbol_ref == DECOUPLER_PROFILE
    assert len(profile.pins) == 2, [pin.name for pin in profile.pins]


def test_the_vio_entry_island_carries_c4(circuit, presentation):
    """The island where VCC enters owns the decoupler — and every part is owned.

    ``C4`` sits in ``ch343_power`` (the supply group beside the chip, with
    ``C1``/``C3``) rather than in ``ch343`` or ``hdr``: the datasheet asks for the
    cap on the VIO rail, and this is where the drawing puts the supply group.  That is a placement on
    the *drawing*, not a claim about the assembled board's copper — nothing here
    says the part is physically bonded to the chip.

    A part left out of ``modules[].parts`` has no island to be drawn in, so the
    two readings move together; the catch-all below also notices a part that
    fell out of every island while the spec still connects it.
    """
    # 534 formal migration: the VIO decoupler shares the supply island with C1/C3
    # (`ch343_power`), next to the chip it decouples; `hdr` is the connector alone.
    power = next(module for module in presentation.modules
                 if module.id == "ch343_power")
    assert DECOUPLER in power.parts, power.parts
    assert {"C1", "C3"} <= set(power.parts), power.parts
    hdr = next(module for module in presentation.modules if module.id == "hdr")
    assert "H1" in hdr.parts
    assert DECOUPLER not in hdr.parts, hdr.parts
    ch343 = next(module for module in presentation.modules if module.id == "ch343")
    assert "U1" in ch343.parts
    assert DECOUPLER not in ch343.parts, ch343.parts
    owned = [part for module in presentation.modules for part in module.parts]
    assert sorted(owned) == sorted({part.id for part in circuit.parts}), (
        "every specified part must belong to exactly one island"
    )


def test_the_census_is_the_one_this_batch_measured(circuit):
    """11 parts / 17 nets / 55 net pins / 58 physical pins / 3 NC.

    The same five readings the batch's compile evidence records: adding a part
    to an island changes these numbers on purpose, so a later edit that grows or
    loses a connection here is a decision this test asks to be made explicitly.
    """
    source_pins = sum(len(net.members) for net in circuit.nets)
    assert len(circuit.parts) == 11
    assert len(circuit.nets) == 17
    assert source_pins == 55
    assert source_pins + len(circuit.nc) == 58
    assert len(circuit.nc) == 3
