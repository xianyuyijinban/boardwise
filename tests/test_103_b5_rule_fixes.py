"""103 / B5: the two rule defects the external audit filed as #14 and #17.

Both were verified against the shipped byte before anything was changed; the
docstrings below record the *reading* each test replaced, so a future change
that reintroduces it fails here with the number in hand.

* **#14** ``rules/params.py`` — ``param-led-current`` emitted one path entry per
  far net and then **summed** them, so two 2.2 kΩ in parallel were reported as
  ``4400 Ω`` with a WARN above the oracle's ``[470, 2200]`` window (the real
  resistance is 1.1 kΩ, inside it), and one part whose both ends sit on the
  LED's own nets was listed once per net and added to itself.
* **#17** ``engines/bom.py`` — a placement with no ``value`` param printed the
  entry's **MPN fallback**, and ``build_bom`` compared that string as if it
  were a second value: a part whose three placements all agree came back
  ``ok=False`` with the JLC ``Comment`` cell blanked and one nonsense open
  question per silent placement.

The #17 shapes use ``tests/test_bom.py``'s own builders, which is how the audit
reproduced them.
"""

from __future__ import annotations

from boardwise.core.blocks import BoardSpec
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.bom import build_bom
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.params import LedCurrent
from tests.test_bom import component, instance, part, spec_with, template

PROV = "test datasheet, p.1, http://example.com/ds.pdf"


def _led_entry() -> PartEntry:
    return PartEntry(
        key="led.test", value="LED-X", mpn="LED-X", lcsc="C1", category="led",
        facts={"led": {"vf_v": [2.7, 3.2], "if_max_ma": 30.0,
                       "provenance": PROV}},
    )


def _library(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _states(rule, model) -> dict[str, list]:
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for outcome in rule.outcomes(model):
        grouped[outcome.state].append(outcome)
    return grouped


def _board(led_pins, resistors) -> DesignModel:
    """One LED, its resistors, and the nets their pins imply."""
    model = DesignModel()
    model.components["LED1"] = Component(
        uid="led", designator="LED1", mpn="LED-X", lcsc_part="C1",
        footprint="LED0603",
        pins=[Pin(number, name, net) for number, name, net in led_pins],
    )
    nets: dict[str, Net] = {}
    for number, _name, net in led_pins:
        nets.setdefault(net, Net(net, [])).pins.append(("LED1", number))
    for designator, value, pins in resistors:
        model.components[designator] = Component(
            uid=designator.lower(), designator=designator, value=value,
            pins=[Pin(number, name, net) for number, name, net in pins],
        )
        for number, _name, net in pins:
            nets.setdefault(net, Net(net, [])).pins.append((designator, number))
    model.nets = nets
    return model


# ------------------------------------------------------------------ #14
# param-led-current: parallel branches are not added, and one part is one part.


def test_14_two_resistors_in_parallel_are_one_resistance_not_a_sum():
    """Audit #14, first shape.

    R5 and R6 both bridge the LED's own net to the same rail: two 2.2 kΩ in
    parallel, 1.1 kΩ — inside the oracle's window, so the row is OK and there
    is nothing to warn about. The shipped rule summed the path and read
    ``R5(2200Ω)+R6(2200Ω) = 4400 Ω``, WARN "above the window [470, 2200]":
    the opposite verdict, from one addition.
    """
    model = _board(
        led_pins=[("1", "K", "GND"), ("2", "A", "NET4")],
        resistors=[
            ("R5", "2.2kΩ", [("1", "A", "NET4"), ("2", "B", "3V3")]),
            ("R6", "2.2kΩ", [("1", "A", "NET4"), ("2", "B", "3V3")]),
        ],
    )
    rule = LedCurrent(library=_library(_led_entry()))
    states = _states(rule, model)
    ok = [o for o in states["OK"] if o.subject == "LED1"]
    assert len(ok) == 1, [o.message for o in states["VIOLATION"]]
    assert "R5(2200\u03a9)\u2225R6(2200\u03a9)" in ok[0].message
    # 1/(1/2200 + 1/2200), the number the window is judged on.
    assert any(line.endswith("= 1100 \u03a9") for line in ok[0].evidence)
    assert "4400" not in ok[0].message
    assert not states["VIOLATION"]
    assert rule.check(model) == []


def test_14_one_part_across_the_led_is_counted_once():
    """Audit #14, second shape: the same part, twice.

    A resistor whose both ends sit on the LED's own nets has no far net, so
    ``_series_resistance`` listed it **once per net** and the sum read one
    2.2 kΩ part as 4400 Ω. Both ends must be nameable rails for the duplicate to
    reach the total, which is why this board's LED sits between two spellings of
    one rail (3V3 / 3.3V) — the welded-name world the rule's own docstring
    describes. One part, one 2.2 kΩ, inside the window.
    """
    model = _board(
        led_pins=[("1", "K", "3V3"), ("2", "A", "3.3V")],
        resistors=[("R9", "2.2kΩ", [("1", "A", "3V3"), ("2", "B", "3.3V")])],
    )
    rule = LedCurrent(library=_library(_led_entry()))
    states = _states(rule, model)
    ok = [o for o in states["OK"] if o.subject == "LED1"]
    assert len(ok) == 1, [o.message for o in states["VIOLATION"]]
    assert "4400" not in ok[0].message
    assert ok[0].message.count("R9") == 1, ok[0].message
    assert any("R9" in line for line in ok[0].evidence)
    assert not states["VIOLATION"]


def test_14_resistors_on_opposite_sides_of_the_led_are_series_and_still_add():
    """The other half of the semantics, pinned so "fix" cannot mean "never sum".

    R5 (1 kΩ, the LED's anode side to 3V3) and R7 (1 kΩ, its cathode side to
    3.3V) are two segments of one loop: series, so they add to 2 kΩ, inside the
    window. This is what the rule reads today and what it must keep reading.
    """
    model = _board(
        led_pins=[("1", "K", "NET5"), ("2", "A", "NET4")],
        resistors=[
            ("R5", "1kΩ", [("1", "A", "NET4"), ("2", "B", "3V3")]),
            ("R7", "1kΩ", [("1", "A", "NET5"), ("2", "B", "3.3V")]),
        ],
    )
    rule = LedCurrent(library=_library(_led_entry()))
    ok = [o for o in _states(rule, model)["OK"] if o.subject == "LED1"]
    assert len(ok) == 1, [o.message for o in rule.outcomes(model)]
    assert "R5(1000\u03a9)+R7(1000\u03a9)" in ok[0].message
    assert "series resistance R5(1000\u03a9)+R7(1000\u03a9) = 2000 \u03a9" \
        in ok[0].evidence


def test_14_a_parallel_pair_and_a_series_segment_add_up():
    """Both halves at once: R5∥R6 (2.2 kΩ each, 1.1 kΩ) is one segment of the
    loop, R7 (1 kΩ) is the other, and the reading is 1.1 k + 1 k = 2.1 k.

    Summing every entry reads 5.4 k (WARN); summing only same-side entries
    reads 5.4 k too; the parallel merge is what makes this a pass.
    """
    model = _board(
        led_pins=[("1", "K", "NET5"), ("2", "A", "NET4")],
        resistors=[
            ("R5", "2.2kΩ", [("1", "A", "NET4"), ("2", "B", "3V3")]),
            ("R6", "2.2kΩ", [("1", "A", "NET4"), ("2", "B", "3V3")]),
            ("R7", "1kΩ", [("1", "A", "NET5"), ("2", "B", "3.3V")]),
        ],
    )
    rule = LedCurrent(library=_library(_led_entry()))
    ok = [o for o in _states(rule, model)["OK"] if o.subject == "LED1"]
    assert len(ok) == 1, [o.message for o in rule.outcomes(model)]
    assert "R5(2200\u03a9)\u2225R6(2200\u03a9)+R7(1000\u03a9)" in ok[0].message
    assert any(line.endswith("= 2100 \u03a9") for line in ok[0].evidence)
    assert not rule.check(model)


# ------------------------------------------------------------------ #17
# build_bom: a placement that declares no value is not a second value.
#
# The boards below are built with ``tests/test_bom.py``'s own constructors --
# the shape the audit reproduced #17 with -- so this file cannot drift from the
# module it is judging: `component(ref, value_param=...)`,
# `template(*components, params=[...])`, `instance(...)`, `spec_with(...)`.


def _bom_part() -> PartEntry:
    return part("res.5k1_0402", "C2906948", value="5.1kΩ",
                mpn="RC0402FR-075K1L")


def _bom_param(name: str, default: str) -> dict:
    return {"name": name, "role": "pull-down", "default": default,
            "constraint": "resistor_value", "provenance": "hand"}


def _bom_spec(*refs: tuple[str, str], params=(("r", "5.1kΩ"),)) -> BoardSpec:
    """A spec placing ``(ref, value_param)`` pairs of one C-numbered part."""
    return spec_with(
        instance(
            "a",
            template(
                *[component(ref, lcsc="C2906948", value_param=value_param)
                  for ref, value_param in refs],
                params=[_bom_param(name, default) for name, default in params],
            ),
        )
    )


def test_17_a_silent_placement_is_not_a_second_value():
    """Audit #17, first shape: three placements of one 5.1 kΩ part, one of them
    declaring the value.

    The two silent placements print the entry's **MPN fallback**, and the
    shipped rule compared that string against the declared value: ``ok=False``,
    a blanked ``Comment`` cell, and one open question per silent placement —
    for a part whose placements all agree.
    """
    library = PartLibrary(parts=[_bom_part()])
    spec = _bom_spec(("R1", "r"), ("R2", ""), ("R3", ""))
    report = build_bom(spec, library)
    assert report.open_questions == []
    assert report.ok
    (row,) = report.rows
    assert row.quantity == 3
    assert row.comment == "5.1kΩ"
    assert "5.1kΩ" in report.csv()
    assert "RC0402FR-075K1L" not in report.csv()


def test_17_the_entry_fallback_is_not_a_value_either():
    """The same board with the silent placement **first**, which is the audit's
    sentence read the other way round: the row is created from the fallback, and
    the placement that does declare a value was then judged against the MPN.
    The declaration names the row — the fallback is what a row prints only while
    nothing has declared a value."""
    library = PartLibrary(parts=[_bom_part()])
    spec = _bom_spec(("R1", ""), ("R2", "r"))
    report = build_bom(spec, library)
    assert report.open_questions == []
    (row,) = report.rows
    assert row.comment == "5.1kΩ"


def test_17_two_declared_values_are_still_a_conflict():
    """The disagreement this module exists for is untouched: two placements that
    both declare a value still print neither — and the silent third adds no
    question of its own."""
    library = PartLibrary(parts=[_bom_part()])
    spec = _bom_spec(("R1", "r"), ("R2", "r2"), ("R3", ""),
                     params=(("r", "5.1kΩ"), ("r2", "10kΩ")))
    report = build_bom(spec, library)
    assert not report.ok
    assert len(report.open_questions) == 1, report.open_questions
    assert "two components carry different values" in report.open_questions[0]
    assert report.rows[0].comment == ""


def test_17_a_row_that_declares_nothing_keeps_printing_the_fallback():
    """No placement declares a value at all: the row prints the entry's MPN,
    exactly as before this batch. Nothing about the fallback moved."""
    library = PartLibrary(parts=[_bom_part()])
    spec = _bom_spec(("R1", ""), ("R2", ""))
    report = build_bom(spec, library)
    assert report.ok
    assert report.rows[0].comment == "RC0402FR-075K1L"
