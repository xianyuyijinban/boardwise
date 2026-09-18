"""Task 005: golden-board comparison — the referee for AI-drawn designs.

The fixture assertions double as a regression net for the schematic parser
(``parsers/schematic.py``): if parsing silently degrades (empty pins, lost
power nets), the reflexive-comparison test below fails instead of letting a
meaningless "0 differences" pass.
"""

from __future__ import annotations

import copy
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from boardwise.core.compare import compare_models, values_equal
from boardwise.core.model import DesignModel
from boardwise.parsers.schematic import build_schematic_model

GOLDEN = Path(__file__).parent / "fixtures" / "ch340_golden.epro2"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def golden_model() -> DesignModel:
    return build_schematic_model(GOLDEN)


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    from boardwise.cli import main

    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["boardwise", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main()
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
# fixture sanity — the schematic parser must produce a meaningful model
# --------------------------------------------------------------------------


def test_golden_parses_into_a_meaningful_model():
    model = golden_model()
    assert len(model.components) == 17
    u1 = model.components.get("U1")
    assert u1 is not None, "CH340G must be present under designator U1"
    assert len(u1.pins) == 16, "CH340G is a 16-pin part"
    # U1's known nets (visually verified against the golden schematic):
    by_number = {p.number: p.net for p in u1.pins}
    assert by_number["1"] == "GND"
    assert by_number["16"] == "VCC"
    assert by_number["5"] == "D+"
    assert by_number["6"] == "D-"
    assert by_number["2"] == "RX"
    assert by_number["3"] == "TX"
    # pins 9..15 are marked no-connect on the golden schematic
    assert all(by_number[str(n)] is None for n in range(9, 16))
    # power nets exist with real members
    assert ("U1", "1") in model.nets["GND"].pins
    assert ("USB1", "2") in model.nets["+5V"].pins


# --------------------------------------------------------------------------
# comparison semantics
# --------------------------------------------------------------------------


def test_golden_vs_golden_is_zero_differences():
    report = compare_models(golden_model(), golden_model())
    assert report.is_empty
    assert report.total == 0


def test_a_deleted_component_is_a_component_level_difference():
    model = golden_model()
    del model.components["C6"]
    report = compare_models(golden_model(), model)
    assert not report.is_empty
    subjects = [d.subject for d in report.component_differences]
    assert "C6" in subjects
    assert any("missing" in d.detail for d in report.component_differences)


def test_an_extra_component_is_a_component_level_difference():
    model = golden_model()
    model.components["X99"] = copy.deepcopy(model.components["C6"])
    model.components["X99"].designator = "X99"
    report = compare_models(golden_model(), model)
    assert "X99" in [d.subject for d in report.component_differences]


def test_a_changed_pin_net_is_a_pin_level_difference():
    model = golden_model()
    for pin in model.components["U1"].pins:
        if pin.number == "2":
            pin.net = "SOMETHING_ELSE"
    report = compare_models(golden_model(), model)
    pins = [d for d in report.pin_differences if d.subject == "U1.2"]
    assert pins, "the U1.2 remapping must be caught at pin level"
    assert pins[0].golden == "RX" and pins[0].candidate == "SOMETHING_ELSE"


def test_a_changed_value_is_caught_but_normalisation_passes():
    model = golden_model()
    for component in model.components.values():
        if component.value == "100nF":
            component.value = "220nF"
    report = compare_models(golden_model(), model)
    assert any(
        d.subject == "C1" and "value" in d.detail
        for d in report.component_differences
    ), "a genuinely different value must be reported"


def test_a_renamed_net_is_a_net_level_difference():
    model = golden_model()
    net = model.nets.pop("RX")
    net.name = "UART_RX"
    model.nets["UART_RX"] = net
    for component in model.components.values():
        for pin in component.pins:
            if pin.net == "RX":
                pin.net = "UART_RX"
    report = compare_models(golden_model(), model)
    subjects = [d.subject for d in report.net_differences]
    assert "RX" in subjects and "UART_RX" in subjects


# --------------------------------------------------------------------------
# value normalisation rules (fixed by the task sheet)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("10k", "10K", True),  # case-insensitive
        ("10k", "10000", True),  # engineering notation
        ("10K", "10000", True),
        ("4R7", "4.7", True),  # resistor decimal marker
        ("1kΩ", "1000", True),  # explicit unit
        ("472M", "472M 1KV", False),  # multi-token degrades to string compare
        ("472M", "10000", False),  # 472M != 10k — never guess
        ("10m", "10000", False),  # lowercase m is ambiguous: refuse to parse
        ("100nF", "220nF", False),
        ("", "", True),
        ("abc", "ABC", True),  # unparseable: case-insensitive string
    ],
)
def test_values_equal_rules(a, b, expected):
    assert values_equal(a, b) is expected


# --------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------


def test_cli_golden_vs_golden_exits_zero():
    code, out, _ = run_cli(
        ["compare", str(GOLDEN), "--golden", str(GOLDEN)]
    )
    assert code == 0
    assert "no differences" in out


def test_cli_bad_input_exits_two_without_traceback():
    bad = Path(__file__).parent / "fixtures" / "no_such_backup.epro2"
    code, out, err = run_cli(["compare", str(bad)])
    assert code == 2
    assert "Traceback" not in err
    assert err.strip(), "the reason must be on stderr, not silent"


def test_cli_json_output_is_parseable_and_reports_differences():
    model = golden_model()
    # a candidate that differs: drop C6 through a temp file would need disk;
    # instead use the LLC board, which is a different design entirely.
    other = Path(__file__).parent / "fixtures" / "llc_board.epro2"
    code, out, _ = run_cli(
        ["compare", str(other), "--golden", str(GOLDEN), "--json"]
    )
    assert code == 1
    payload = json.loads(out)
    assert payload["total"] > 0
    assert set(payload) == {"component", "net", "pin", "total"}
