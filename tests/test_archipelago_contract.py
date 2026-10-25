"""Production contract tests for the archipelago reading (536).

The reference validators this file used to carry are gone: every rule lives in
the module that owns it, and these tests read it through the public API rather
than restating it. Three owners, three jobs:

* :meth:`PresentationSpec.from_dict` — the raw JSON boundary: the closed key
  sets, the closed ``role`` / ``kind`` / ``side`` vocabularies, the implicit
  island's reserved id, coordinate-shaped keys, and the structure pass it shares
  with the parser (`islands.validate_archipelago_structure`: one group per part,
  islands ⊆ their group, one core island per group, every owner inside it).
* :func:`boardwise.core.archipelago.validate_archipelago` — the half that needs
  the circuit: whether a satellite touches its owner, whether a ``decoupling``
  island holds a signal net, whether it shares a power net, and whether the two
  documents place the same parts.
* :func:`boardwise.core.archipelago.derive_archipelago_ports` — the ports, from
  ``net.members → part → island`` and nothing else (§2.1 / §8). The draft states
  no ``ports`` key at all, and the schema has none.

Every refusal is a ``ValueError`` naming who and why, which is what makes the
negative cases readable with ``pytest.raises(match=…)``: the match is the text
production actually emits, not a rule loosened so that a test can pass.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from boardwise.core.archipelago import derive_archipelago_ports, validate_archipelago
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.islands import IMPLICIT_ISLAND_ID
from boardwise.core.presentationspec import PresentationSpec

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "archipelago_min"
CIRCUIT = EXAMPLES / "mcu_cluster.circuit.json"
PRESENTATION = EXAMPLES / "mcu_cluster.presentation.draft.json"

#: §7 的四个子岛，逐字对照（§8 的端口表见 ``EXPECTED_PORTS``）。None = side 省略。
EXPECTED_PARTITION = {
    "mcu_core": (("U1",), "core", None),
    "mcu_decoupling": (("C1", "C2"), "decoupling", "left"),
    "mcu_clock": (("C3", "C4", "Y1"), "clock", "right"),
    "mcu_swd": (("H1",), "programming", "top"),
}
EXPECTED_PORTS: dict[str, set[str]] = {
    "mcu_core": {"VDD", "GND", "SWDIO", "SWCLK", "OSC_IN", "OSC_OUT"},
    "mcu_decoupling": {"VDD", "GND"},
    "mcu_clock": {"GND", "OSC_IN", "OSC_OUT"},
    "mcu_swd": {"VDD", "GND", "SWDIO", "SWCLK"},
}


def validate_contract(
    circuit: CircuitSpec, raw_dict: dict[str, Any]
) -> PresentationSpec:
    """Parse the raw draft, then let production read it against the circuit.

    Parse first, because the JSON boundary is where the document's own facts are
    decided (closed keys, vocabularies, structure); :func:`validate_archipelago`
    only adds the readings that need the netlist. The parsed spec is returned so
    a caller can read the partition it just validated.
    """
    spec = PresentationSpec.from_dict(raw_dict)
    validate_archipelago(circuit, spec)
    return spec


def derive_ports(
    circuit: CircuitSpec, raw_dict: dict[str, Any]
) -> tuple[dict[str, set[str]], set[str]]:
    """A valid draft's ports: parse → validate → derive (§2.1 / §8)."""
    return derive_archipelago_ports(circuit, validate_contract(circuit, raw_dict))


def _island_entry(draft: dict[str, Any], island_id: str) -> dict[str, Any]:
    """The raw ``islands[]`` entry with this id, for the mutation cases below."""
    return next(island for island in draft["islands"] if island["id"] == island_id)


@pytest.fixture(scope="module")
def circuit() -> CircuitSpec:
    return CircuitSpec.load(CIRCUIT)


@pytest.fixture(scope="module")
def presentation() -> dict[str, Any]:
    return json.loads(PRESENTATION.read_text(encoding="utf-8"))


@pytest.fixture()
def draft(presentation: dict[str, Any]) -> dict[str, Any]:
    """A private deep copy: each mutation below touches nothing else."""
    return copy.deepcopy(presentation)


def test_reference_draft_satisfies_every_invariant(circuit, presentation):
    spec = validate_contract(circuit, presentation)
    assert spec.is_archipelago, "the draft states group/owner/kind on its islands"


def test_partition_is_exactly_the_four_islands_of_the_route_document(circuit, presentation):
    spec = validate_contract(circuit, presentation)
    islands = spec.effective_islands()
    stated = {
        island.id: (tuple(sorted(island.parts)), island.kind, island.side or None)
        for island in islands
    }
    assert stated == EXPECTED_PARTITION
    assert {island.group for island in islands} == {"mcu_cluster"}
    assert {island.owner for island in islands} == {"U1"}
    placed = [part for island in islands for part in island.parts]
    assert sorted(placed) == sorted(circuit.part_ids()) and len(placed) == len(set(placed))


def test_derived_ports_match_the_documented_tables(circuit, presentation):
    ports, internal = derive_ports(circuit, presentation)
    assert ports == EXPECTED_PORTS, "§8's four port tables, net for net"
    assert internal == set(), "the minimal example has no net that stays inside one island"


def test_ports_are_derived_from_the_netlist_not_the_presentation(circuit, presentation):
    spec = validate_contract(circuit, presentation)
    normal = derive_archipelago_ports(circuit, spec)
    assert normal[0] == EXPECTED_PORTS
    # A `ports` claim the document itself would refuse (see the negative case
    # below) is injected where derivation would see it if it read one at all.
    for island in spec.islands or ():
        setattr(island, "ports", {"VDD", "NOT-A-NET"})
    assert all(hasattr(island, "ports") for island in spec.islands or ())
    assert derive_archipelago_ports(circuit, spec) == normal


def test_rejects_a_part_claimed_by_a_second_module(circuit, draft):
    # A schema-valid second module (`role` is required by the parser): the only
    # breach under test is that U1 would then sit in two groups.
    draft["modules"].append({"id": "aux_cluster", "parts": ["U1"], "role": "auxiliary", "core": "U1"})
    with pytest.raises(ValueError, match="more than one module"):
        validate_contract(circuit, draft)


def test_rejects_an_island_holding_another_modules_part(circuit, draft):
    draft["modules"][0]["parts"].remove("Y1")
    draft["modules"].append({"id": "aux_cluster", "parts": ["Y1"], "role": "auxiliary", "core": "Y1"})
    # Every part still has one module and one island; the first breach is island ⊆ group.
    with pytest.raises(ValueError, match="does not claim"):
        validate_contract(circuit, draft)


def test_rejects_the_same_part_in_two_islands(circuit, draft):
    _island_entry(draft, "mcu_decoupling")["parts"].append("U1")
    with pytest.raises(ValueError, match="more than one island"):
        validate_contract(circuit, draft)


def test_rejects_an_owner_outside_the_core_island(circuit, draft):
    _island_entry(draft, "mcu_swd")["owner"] = "H1"
    with pytest.raises(ValueError, match="not in the core island"):
        validate_contract(circuit, draft)


def test_rejects_an_unknown_island_field(circuit, draft):
    _island_entry(draft, "mcu_clock")["colour"] = "blue"
    with pytest.raises(ValueError, match="colour"):
        validate_contract(circuit, draft)


def test_rejects_an_unknown_module_field(circuit, draft):
    draft["modules"][0]["colour"] = "blue"
    with pytest.raises(ValueError, match="colour"):
        validate_contract(circuit, draft)


def test_rejects_an_invalid_electrical_role(circuit, draft):
    _island_entry(draft, "mcu_decoupling")["role"] = "decoupling"
    with pytest.raises(ValueError, match="role"):
        validate_contract(circuit, draft)


def test_rejects_an_unknown_group(circuit, draft):
    _island_entry(draft, "mcu_swd")["group"] = "missing"
    with pytest.raises(ValueError, match="not a module"):
        validate_contract(circuit, draft)


def test_rejects_the_reserved_implicit_island_id(circuit, draft):
    _island_entry(draft, "mcu_core")["id"] = IMPLICIT_ISLAND_ID
    with pytest.raises(ValueError, match="implicit island"):
        validate_contract(circuit, draft)


def test_rejects_handwritten_ports(circuit, draft):
    _island_entry(draft, "mcu_core")["ports"] = ["VDD"]
    with pytest.raises(ValueError, match="ports"):
        validate_contract(circuit, draft)


def test_rejects_a_signal_part_in_a_decoupling_island(circuit, draft):
    _island_entry(draft, "mcu_clock")["parts"].remove("Y1")
    _island_entry(draft, "mcu_decoupling")["parts"].append("Y1")
    with pytest.raises(ValueError, match="may not hold signal net"):
        validate_contract(circuit, draft)


def test_rejects_a_satellite_with_no_net_shared_with_its_owner(circuit, draft):
    local_circuit = copy.deepcopy(circuit)
    for net in local_circuit.nets:
        net.members = [member for member in net.members if not member.startswith("H1.")]
    with pytest.raises(ValueError, match="shares no net"):
        validate_contract(local_circuit, draft)


def test_rejects_decoupling_without_a_shared_power_net(circuit, draft):
    local_circuit = copy.deepcopy(circuit)
    vdd = local_circuit.net("VDD")
    assert vdd is not None
    vdd.cls = "other"  # still connected, but no longer a power rail
    with pytest.raises(ValueError, match="shares no power net"):
        validate_contract(local_circuit, draft)


def test_presentation_draft_carries_no_netlist(circuit, presentation):
    validate_contract(circuit, presentation)  # the reference draft states no netlist
    draft = copy.deepcopy(presentation)
    draft["nets"] = [{"id": "VDD", "members": ["U1.1"]}]
    with pytest.raises(ValueError, match="nets"):
        validate_contract(circuit, draft)


def test_presentation_draft_carries_no_pre_drawn_frame(circuit, presentation):
    validate_contract(circuit, presentation)  # §4: no box precedes the parts
    draft = copy.deepcopy(presentation)
    draft["islands"][0].update({"x": 10, "y": 20})
    with pytest.raises(ValueError, match=r"islands\[0\]\.x"):
        validate_contract(circuit, draft)


def test_owner_can_be_another_part_of_a_multi_part_core_island(circuit, draft):
    """A core island may hold the actual peer even when module.core is U1."""
    _island_entry(draft, "mcu_core")["parts"].append("H1")
    draft["islands"] = [
        island for island in draft["islands"] if island["id"] != "mcu_swd"
    ]
    _island_entry(draft, "mcu_decoupling")["owner"] = "H1"
    spec = validate_contract(circuit, draft)
    module = spec.module("mcu_cluster")
    assert module is not None and module.core == "U1"
    assert _island_entry(draft, "mcu_decoupling")["owner"] == "H1"


def test_legacy_port_derivation_skips_parts_the_spec_does_not_place(circuit, presentation):
    """Legacy keeps 520j's partial-presentation reading; arch would refuse instead."""
    raw = copy.deepcopy(presentation)
    for island in raw["islands"]:
        for key in ("group", "owner", "kind", "side"):
            island.pop(key, None)
    spec = PresentationSpec.from_dict(raw)
    assert not spec.is_archipelago
    local_circuit = copy.deepcopy(circuit)
    extra = copy.deepcopy(local_circuit.parts[0])
    extra.id = "X9"
    local_circuit.parts.append(extra)
    vdd = local_circuit.net("VDD")
    assert vdd is not None
    vdd.members.append("X9.2")
    outside = copy.deepcopy(local_circuit.nets[0])
    outside.id = "X_ONLY"
    outside.members = ["X9.1"]
    local_circuit.nets.append(outside)
    ports, internal = derive_archipelago_ports(local_circuit, spec)
    assert ports == EXPECTED_PORTS
    assert "X_ONLY" not in internal
    assert all("X_ONLY" not in island_ports for island_ports in ports.values())


def test_bulk_kind_is_a_first_class_rail_island(circuit, draft):
    _island_entry(draft, "mcu_decoupling")["kind"] = "bulk"
    spec = validate_contract(circuit, draft)
    island = next(item for item in spec.effective_islands() if item.id == "mcu_decoupling")
    assert island.kind == "bulk"


def test_rejects_a_circuit_part_the_presentation_does_not_place(circuit, draft):
    local_circuit = copy.deepcopy(circuit)
    extra = copy.deepcopy(local_circuit.parts[0])
    extra.id = "X9"
    local_circuit.parts.append(extra)
    with pytest.raises(ValueError, match="does not place"):
        validate_contract(local_circuit, draft)
