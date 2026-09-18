"""The firmware pin table, and the gates that make it checkable (008c item 2).

The rules this file pins, in the order they matter:

* the ``function`` vocabulary is **closed** — a value outside it is an error and
  not a free string, because a vocabulary that accepts anything checks nothing;
* a pin number must exist on the MCU block's symbol ("ghost pin" negative case);
* one pin number, one row ("one pin under two names" negative case);
* the two-way difference against the spec: firmware uses a pin the schematic
  does not connect ⇒ **defect**; the schematic connects a signal port the
  firmware never names ⇒ **open question**, listed but not blocking;
* ``.ioc`` is the baseline, and a disagreement between it and the firmware is
  **reported, never resolved** — neither side is believed silently.

The last one is the point of the whole work item, so it is pinned from both
ends: a project file that agrees with the firmware produces nothing, and each of
the five disagreement shapes is reproduced by a test of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import BlockConnection, BlockInstance, BoardSpec, template_from_json
from boardwise.core.pintable import (
    PINTABLE_FUNCTIONS,
    PinTableError,
    cross_check,
    load_ioc,
    load_pin_table,
    parse_ioc,
    pin_table_from_json,
    port_pin_of,
)
from boardwise.engines.pintable_check import (
    DEFECT,
    NOTE,
    OPEN_QUESTION,
    check_pin_table,
)

ROOT = Path(__file__).resolve().parents[1]
PINTABLE = ROOT / "inputs" / "smart_pillbox" / "pintable.json"
IOC = ROOT / "inputs" / "smart_pillbox" / "firmware-mcu" / "Smartbox.ioc"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def table(*pins, mcu: str = "ic.stm32g431rbt6", **extra):
    """Build a pin table from ``(number, function, net)`` triples."""
    body = {
        "kind": "boardwise-firmware-pintable",
        "version": 1,
        "mcu": mcu,
        "pins": [
            {"number": number, "name": number, "function": function, "net": net}
            for number, function, net in pins
        ],
    }
    body.update(extra)
    return pin_table_from_json(body, where="synthetic")


def mcu_template(*pin_numbers: str, ref: str = "U1"):
    """A one-component MCU block whose symbol has exactly ``pin_numbers``."""
    return template_from_json(
        {
            "kind": "boardwise-block-template", "version": 1, "name": "mcu",
            "description": "", "provenance": {"kind": "textbook", "source": "hand"},
            "origin_file": [0.0, 0.0], "bbox_file": [0.0, 0.0, 10.0, 10.0], "notes": [],
            "interface": [
                {"role": "PA3", "net": "PA3", "net_class": "signal"},
                {"role": "PB6", "net": "PB6", "net_class": "signal"},
                {"role": "GND", "net": "GND", "net_class": "gnd"},
            ],
            "params": [],
            "symbols": {
                "u": {
                    "offsets": {number: [0.0, 0.0] for number in pin_numbers},
                    "body": [0.0, 0.0, 5.0, 5.0],
                    "pin_names": {number: number for number in pin_numbers},
                }
            },
            "components": [
                {
                    "ref": ref, "symbol": "u",
                    "placement": {"x": 0.0, "y": 0.0},
                    "device": {"lcsc": "C431633"}, "footprint": "LQFP-64", "params": {},
                    "pins": [],
                }
            ],
            "geometry": {"wires": [], "flags": [], "labels": []},
        },
        where="mcu-block",
    )


def spec_connecting(template, *pairs, block_id: str = "mcu"):
    """A spec wiring the MCU's ports onto nets, as ``(net, port role)`` pairs.

    The role must be one the template actually declares — hand-built specs
    bypass `load_board_spec`, so a role the block does not have would quietly
    produce a connection nothing can be compared against.
    """
    return BoardSpec(
        name="synthetic", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=[BlockInstance(id=block_id, template_path="/t/mcu.json",
                              template=template, at=(0.0, 0.0))],
        connections=[
            BlockConnection(net=net, ports=[(block_id, role), ("other", role)])
            for net, role in pairs
        ],
        params={}, sheet_attrs={}, sheet_origin=(0.0, 0.0),
    )


def ioc(**pins) -> str:
    """``ioc(PA3="GPIO_Output")`` → a minimal ``.ioc`` text with those pins.

    Signal and label are written as CubeMX writes them: ``<pin>.Signal=`` and
    ``<pin>.GPIO_Label=``, plus ``Mcu.Pin<k>`` to put the pin on the list.
    """
    lines = ["Mcu.Name=STM32G431R(6-8-B)Tx", "Mcu.CPN=STM32G431RBT6"]
    for index, (pin, body) in enumerate(pins.items()):
        lines.append(f"Mcu.Pin{index}={pin}")
        if isinstance(body, tuple):
            signal, label = body
        else:
            signal, label = body, ""
        if signal:
            lines.append(f"{pin}.Signal={signal}")
        if label:
            lines.append(f"{pin}.GPIO_Label={label}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# the vocabulary is closed
# --------------------------------------------------------------------------


def test_the_vocabulary_is_a_registry_not_a_free_string():
    assert "GPIO" in PINTABLE_FUNCTIONS and "UART_TX" in PINTABLE_FUNCTIONS
    assert "I2C_SCL" in PINTABLE_FUNCTIONS and "I2C_SDA" in PINTABLE_FUNCTIONS
    assert "PWM" in PINTABLE_FUNCTIONS and "ADC" in PINTABLE_FUNCTIONS
    assert "SWDIO" in PINTABLE_FUNCTIONS and "SWDCLK" in PINTABLE_FUNCTIONS
    # Every member says what it means: a reviewer reads the vocabulary itself.
    assert all(isinstance(doc, str) and doc for doc in PINTABLE_FUNCTIONS.values())


def test_a_function_outside_the_vocabulary_is_refused():
    with pytest.raises(PinTableError) as caught:
        table(("PA5", "SPI_CLOCK", "SPI1_SCK"))
    message = str(caught.value)
    assert "unknown function 'SPI_CLOCK'" in message
    assert "GPIO" in message, "the error must list what *is* known"
    assert "closed on purpose" in message


def test_a_pin_table_that_is_not_a_pin_table_is_named_as_such():
    with pytest.raises(PinTableError) as caught:
        pin_table_from_json({"kind": "boardwise-block-template", "version": 1})
    assert "expected 'boardwise-firmware-pintable'" in str(caught.value)


def test_a_table_with_no_pins_says_nothing_and_is_refused():
    with pytest.raises(PinTableError) as caught:
        table()
    assert "empty pin table" in str(caught.value)


def test_the_name_defaults_to_the_pin_number():
    # On an STM32 the ball name and the pin name are the same string; making an
    # author repeat it is how the two drift apart.
    pintable = table(("PA5", "SPI_SCK", "SPI1_SCK"))
    assert pintable.pins[0].name == "PA5"


def test_an_unknown_key_is_an_error_not_a_silently_ignored_field():
    with pytest.raises(PinTableError) as caught:
        pin_table_from_json(
            {"kind": "boardwise-firmware-pintable", "version": 1, "mcu": "x",
             "pins": [], "peripheral": "SPI1"}
        )
    assert "unknown key(s) peripheral" in str(caught.value)


# --------------------------------------------------------------------------
# gate 1: the pin number exists on the MCU block's symbol
# --------------------------------------------------------------------------


def test_a_pin_the_symbol_does_not_have_is_a_defect():
    tmpl = mcu_template("PA3", "PB6")
    pintable = table(("PA3", "GPIO", "LED1"), ("PC99", "GPIO", "KEY1"))
    report = check_pin_table(pintable, mcu_block=tmpl, mcu_component="U1")
    assert not report.ok
    ghosts = [f for f in report.defects if f.rule == "pin-numbers-exist"]
    assert len(ghosts) == 1
    assert "PC99" in ghosts[0].message
    assert "not on the symbol" in ghosts[0].message


def test_every_pin_present_is_not_a_defect():
    tmpl = mcu_template("PA3", "PB6")
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    report = check_pin_table(pintable, mcu_block=tmpl, mcu_component="U1")
    assert not [f for f in report.defects if f.rule == "pin-numbers-exist"]


def test_a_gate_that_could_not_run_says_so_rather_than_passing():
    # "No MCU block" must not read as "the pin numbers were fine".
    report = check_pin_table(table(("PC99", "GPIO", "KEY1")))
    assert report.ok, "a gate that cannot run is not a defect"
    notes = [f for f in report.notes if f.rule == "pin-numbers-exist"]
    assert notes and "not checked against a symbol" in notes[0].message


def test_naming_the_wrong_component_is_reported_not_guessed():
    tmpl = mcu_template("PA3", ref="U1")
    pintable = table(("PA3", "GPIO", "LED1"))
    report = check_pin_table(pintable, mcu_block=tmpl, mcu_component="U9")
    assert report.ok, "an unchecked gate is not a defect"
    assert any("has no component 'U9'" in f.message for f in report.notes)


# --------------------------------------------------------------------------
# gate 2: one pin, one row
# --------------------------------------------------------------------------


def test_one_pin_under_two_names_is_a_defect():
    pintable = table(("PA3", "GPIO", "LED1"), ("PA3", "UART_TX", "USART1_TX"))
    report = check_pin_table(pintable)
    assert not report.ok
    repeat = [f for f in report.defects if f.rule == "one-pin-one-row"]
    assert len(repeat) == 1
    assert "appears twice" in repeat[0].message
    assert "silently win" in repeat[0].message
    # Both readings are in the evidence: the reader has to be able to see them.
    assert len(repeat[0].evidence) == 2


def test_the_same_number_is_still_one_row_when_its_name_differs():
    # The count is by number, not by name — a pin renamed is one pin.
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    assert check_pin_table(pintable).ok


# --------------------------------------------------------------------------
# gate 3: the two-way difference against the spec
# --------------------------------------------------------------------------


def test_firmware_naming_a_net_the_spec_never_connects_is_a_defect():
    tmpl = mcu_template("PA3", "PB6")
    spec = spec_connecting(tmpl, ("LED1", "PA3"))
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    report = check_pin_table(pintable, spec=spec, mcu_block_id="mcu")
    assert not report.ok
    orphan = [f for f in report.defects if f.rule == "spec-difference"]
    assert len(orphan) == 1
    assert "USART1_TX" in orphan[0].message
    assert "schematic does not wire" in orphan[0].message


def test_a_pin_the_firmware_uses_without_naming_a_net_is_a_defect():
    tmpl = mcu_template("PA3")
    spec = spec_connecting(tmpl, ("LED1", "PA3"))
    pintable = table(("PA3", "GPIO", ""))
    report = check_pin_table(pintable, spec=spec, mcu_block_id="mcu")
    assert not report.ok
    assert any("names no net" in f.message for f in report.defects)


def test_a_spec_port_the_firmware_never_uses_is_an_open_question_not_a_defect():
    # The board may legitimately have a pin the firmware has not grown into;
    # calling that a defect would make the checker wrong about real boards.
    tmpl = mcu_template("PA3", "PB6")
    spec = spec_connecting(tmpl, ("LED1", "PA3"), ("PB6", "PB6"))
    pintable = table(("PA3", "GPIO", "LED1"))
    report = check_pin_table(pintable, spec=spec, mcu_block_id="mcu")
    assert report.ok, "an open question does not block"
    questions = [f for f in report.open_questions if f.rule == "spec-difference"]
    assert len(questions) == 1
    assert questions[0].kind == OPEN_QUESTION
    assert "PB6" in questions[0].message
    assert "never uses it" in questions[0].message


def test_the_matched_nets_are_counted():
    tmpl = mcu_template("PA3", "PB6")
    spec = spec_connecting(tmpl, ("LED1", "PA3"), ("USART1_TX", "PB6"))
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    report = check_pin_table(pintable, spec=spec, mcu_block_id="mcu")
    assert report.ok and report.matched_nets == 2
    assert report.checked_pins == 2


def test_a_spec_without_the_named_block_is_not_a_defect():
    tmpl = mcu_template("PA3")
    report = check_pin_table(table(("PA3", "GPIO", "LED1")),
                             spec=spec_connecting(tmpl, ("LED1", "PA3")),
                             mcu_block_id="nope")
    assert report.ok
    assert any("has no block 'nope'" in f.message for f in report.notes)


def test_only_signal_ports_are_compared():
    # A power or ground port on the MCU is not a "pin the firmware forgot".
    tmpl = mcu_template("PA3")
    spec = BoardSpec(
        name="synthetic", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=[BlockInstance(id="mcu", template_path="/t/mcu.json",
                              template=tmpl, at=(0.0, 0.0))],
        connections=[
            BlockConnection(net="GND", ports=[("mcu", "GND"), ("other", "GND")]),
            BlockConnection(net="LED1", ports=[("mcu", "PA3"), ("other", "LED1")]),
        ],
        params={}, sheet_attrs={}, sheet_origin=(0.0, 0.0),
    )
    report = check_pin_table(table(("PA3", "GPIO", "LED1")), spec=spec, mcu_block_id="mcu")
    assert report.ok
    assert not report.open_questions, "GND is not a port the firmware forgot"


# --------------------------------------------------------------------------
# `.ioc` — the baseline
# --------------------------------------------------------------------------


def test_an_ioc_file_is_read_as_data_with_nothing_inferred():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED1"), PB6="USART1_TX"))
    assert project.mcu_cpn == "STM32G431RBT6"
    pins = project.by_port_pin()
    assert set(pins) == {"PA3", "PB6"}
    assert pins["PA3"].signal == "GPIO_Output" and pins["PA3"].label == "LED1"
    assert pins["PB6"].signal == "USART1_TX" and pins["PB6"].label == ""


def test_virtual_pins_are_read_and_then_excluded():
    # CubeMX's VP_* entries are project settings, not silicon: a virtual pin has
    # no ball to wire, so it must never reach a comparison.
    project = parse_ioc(ioc(PA3="GPIO_Output") + "Mcu.Pin9=VP_RTC_VS_RTC\n")
    assert len(project.pins) == 2
    assert len(project.physical) == 1
    assert project.physical[0].port_pin == "PA3"


def test_the_port_pin_is_pulled_out_of_a_hyphenated_name():
    # `PF0-OSC_IN` is why this exists: comparing whole strings would report the
    # oscillator pins as a permanent disagreement on every STM32 board.
    assert port_pin_of("PF0-OSC_IN") == "PF0"
    assert port_pin_of("PC12") == "PC12"
    assert port_pin_of("VP_RTC_VS_RTC") == ""


def test_unmodelled_settings_stay_reachable():
    # RCC.HSE_VALUE is not modelled here, and a second parser must not be needed
    # to reach it.
    project = parse_ioc(ioc(PA3="GPIO_Output") + "RCC.HSE_VALUE=8000000\n")
    assert project.raw["RCC.HSE_VALUE"] == "8000000"


def test_comments_and_blank_lines_are_skipped():
    project = parse_ioc("#MicroXplorer Configuration settings\n\nPA3.Signal=x\n")
    assert project.physical == []


# --------------------------------------------------------------------------
# the cross-check: neither side is believed silently
# --------------------------------------------------------------------------


def test_two_readings_that_agree_produce_nothing():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED1"), PB6="USART1_TX"))
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    assert cross_check(pintable, project) == []


def test_a_pin_only_the_firmware_knows_is_missing_from_the_baseline():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED1")))
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"))
    conflicts = cross_check(pintable, project)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "missing_from_ioc"
    assert conflicts[0].port_pin == "PB6"


def test_a_pin_only_the_baseline_assigns_is_missing_from_the_firmware():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED1"), PB6="USART1_TX"))
    pintable = table(("PA3", "GPIO", "LED1"))
    conflicts = cross_check(pintable, project)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "missing_from_firmware"
    assert "USART1_TX" in conflicts[0].detail


def test_a_contradictory_net_name_is_a_mismatch():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED_RED")))
    pintable = table(("PA3", "GPIO", "LED1"))
    conflicts = cross_check(pintable, project)
    assert len(conflicts) == 1 and conflicts[0].kind == "net_mismatch"
    assert conflicts[0].ioc == "LED_RED" and conflicts[0].firmware == "LED1"


def test_a_function_the_baseline_assigns_differently_is_a_mismatch():
    project = parse_ioc(ioc(PA3=("USART1_TX", "")))
    pintable = table(("PA3", "GPIO", "LED1"))
    # One wrong pin disagrees in two independent ways — what it *is* and what
    # it is *called* — and both are reported rather than the first one winning.
    kinds = {c.kind: c for c in cross_check(pintable, project)}
    assert set(kinds) == {"function_mismatch", "net_mismatch"}
    assert kinds["function_mismatch"].ioc == "UART_TX"
    assert kinds["function_mismatch"].firmware == "GPIO"


def test_a_gpio_direction_is_not_a_net_name():
    # `GPIO_Output` is a direction. Treating it as a net name is what made every
    # GPIO pin look named while PC4 — whose real name lives only in main.h —
    # looked silently fine.
    project = parse_ioc(ioc(PC4="GPIO_Output"))
    pintable = table(("PC4", "GPIO", "LCD_RES"))
    conflicts = cross_check(pintable, project)
    assert len(conflicts) == 1 and conflicts[0].kind == "firmware_only_net"
    assert "LCD_RES" in conflicts[0].detail


def test_a_peripheral_signal_is_the_baselines_net_name():
    # The other half of the same rule: `USART1_TX` *is* what the schematic calls
    # the net, so agreeing with it is not "firmware only".
    project = parse_ioc(ioc(PB6="USART1_TX"))
    pintable = table(("PB6", "UART_TX", "USART1_TX"))
    assert cross_check(pintable, project) == []


def test_conflicts_are_ordered_by_port_pin():
    project = parse_ioc(ioc(PA3=("GPIO_Output", "LED1")))
    pintable = table(("PA3", "GPIO", "LED1"), ("PB6", "UART_TX", "USART1_TX"),
                     ("PC9", "I2C_SDA", "I2C3_SDA"))
    kinds = [(c.port_pin, c.kind) for c in cross_check(pintable, project)]
    assert kinds == [("PB6", "missing_from_ioc"), ("PC9", "missing_from_ioc")]


# --------------------------------------------------------------------------
# the real inputs
# --------------------------------------------------------------------------


def test_the_pillbox_pin_table_loads_and_is_complete():
    pintable = load_pin_table(PINTABLE)
    assert pintable.mcu == "ic.stm32g431rbt6"
    # 28 physical pins: the number the .ioc itself reports (Mcu.PinsNb=34 minus
    # six VP_* virtual pins).
    assert len(pintable.pins) == 28
    assert pintable.nets(), "every pin names a net"


def test_the_pillbox_pin_table_agrees_with_the_ioc_on_every_pin_but_one():
    pintable = load_pin_table(PINTABLE)
    project = load_ioc(IOC)
    assert len(project.physical) == 28
    assert project.mcu_cpn == "STM32G431RBT6"

    conflicts = cross_check(pintable, project)
    assert [c.port_pin for c in conflicts] == ["PC4"], (
        f"unexpected disagreement(s): {[c.render() for c in conflicts]}"
    )
    # PC4's name exists only in main.h's hand-written LCD_RES macro; the .ioc
    # gives it no label and `GPIO_Output` is a direction, not a name.
    assert conflicts[0].kind == "firmware_only_net"
    assert "LCD_RES" in conflicts[0].detail


def test_the_pillbox_pin_table_uses_only_registered_functions():
    pintable = load_pin_table(PINTABLE)
    for pin in pintable.pins:
        assert pin.function in PINTABLE_FUNCTIONS, pin.number


def test_the_pillbox_pin_table_has_no_repeated_pin():
    pintable = load_pin_table(PINTABLE)
    numbers = [pin.number for pin in pintable.pins]
    assert len(numbers) == len(set(numbers))


def test_the_pillbox_ioc_lists_the_peripherals_the_project_enables():
    project = load_ioc(IOC)
    assert "USART3" in project.peripherals
    assert "I2C2" in project.peripherals and "I2C3" in project.peripherals
    assert "SPI1" in project.peripherals and "TIM1" in project.peripherals


def test_the_report_renders_and_serialises():
    pintable = load_pin_table(PINTABLE)
    report = check_pin_table(pintable)
    lines = report.render()
    assert lines and lines[0].startswith("pin table check:")
    payload = report.as_json()
    assert json.dumps(payload)  # serialisable
    assert payload["checked_pins"] == 28
    assert payload["ok"] is True
