"""Parser tests against the real fixture: a 24 V motor driver board export."""

from pathlib import Path

import pytest

from boardwise.core.model import is_ground_net
from boardwise.parsers.enet import parse_enet

FIXTURE = Path(__file__).parent / "fixtures" / "board24v.enet"


@pytest.fixture(scope="module")
def model():
    return parse_enet(FIXTURE)


def test_parses_all_components(model):
    assert len(model.components) == 50


def test_c116_identity_and_nets(model):
    c116 = model.components["C116"]
    assert c116.value == "330uF"
    nets_by_pin = {pin.number: pin.net for pin in c116.pins}
    assert nets_by_pin["1"] == "VM"
    assert nets_by_pin["2"] == "PGND"


def test_net_membership(model):
    vm = model.nets["VM"]
    pgnd = model.nets["PGND"]
    assert ("C116", "1") in vm.pins
    assert ("C116", "2") in pgnd.pins
    # Counts verified by inspecting the fixture export directly.
    assert len(vm.pins) == 32
    assert len(pgnd.pins) == 22


def test_unconnected_pin_net_is_none(model):
    # EasyEDA exports unconnected pins with "net": "" — normalized to None.
    screw1 = model.components["SCREW1"]
    assert screw1.pins[0].net is None


def test_raw_top_level_blocks_preserved(model):
    for key in ("designRule", "differentialPair", "netClass", "equalLengthNetGroup"):
        assert key in model.raw
    assert isinstance(model.raw["designRule"], dict) and model.raw["designRule"]
    assert model.raw["netClass"] == {}
    assert model.raw["differentialPair"] == {}
    assert model.raw["equalLengthNetGroup"] == {}


def test_props_kept_verbatim(model):
    c116 = model.components["C116"]
    assert c116.props["Supplier Part"] == "C46550457"
    assert c116.lcsc_part == "C46550457"
    assert c116.mpn == "PA50V330M10x15"


def test_is_ground_net():
    for name in ("GND", "AGND", "DGND", "PGND", "EGND", "SGND", "VSS", "gnd"):
        assert is_ground_net(name), name
    # VEE is a negative supply in analog/ECL circuits, not ground: it moved out
    # of the ground set in the 2026-09-18 ruling (M0-P0c). Reading it as ground
    # made a negative rail hang a ground symbol off itself.
    for name in ("VM", "+24V", "VCC", "VEE", "VEE-5V", "vee", "", None):
        assert not is_ground_net(name), name
