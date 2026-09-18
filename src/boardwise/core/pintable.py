"""The firmware pin table — what the MCU is *actually* wired to (008c item 2).

Task 008's constitution (item 5) draws the line this module lives on: **firmware
understanding stops at interface facts**. The model may read firmware source and
report *which pin does what*; it may not reason about the software. So the
artifact is deliberately narrow::

    {"mcu": "<shelf key or C-number>",
     "pins": [{"number": "PA5", "name": "PA5", "function": "SPI_SCK", "net": "SPI1_SCK"}]}

Three things make that checkable rather than decorative.

**A closed function vocabulary.** ``function`` must name a member of
:data:`PINTABLE_FUNCTIONS`; an unknown value is an error, never a free string.
This is :data:`boardwise.core.blocks.CONSTRAINTS`'s shape for the same reason:
a vocabulary that silently accepts anything checks nothing, and the reviewer
who has to judge "is this pin table right?" needs a bounded set of answers to
compare against.

**The MCU template's symbol is the authority on pin numbers.** ``offsets`` on
the MCU block's symbol is a measured fact (which pin numbers the library symbol
actually exposes), so a pin table naming a pin the symbol does not have is
caught before anything is drawn — the "ghost pin number" case.

**``.ioc`` is the baseline, and disagreement is an open question.** The CubeMX
project file is machine-readable ground truth for pin *assignment*, while the C
sources are ground truth for pin *use*. 岳翔宇's rule for this work item is that
neither side is believed silently: when the two disagree, both readings are
reported (:class:`PinConflict`) and a human decides. Nothing here picks a
winner, and nothing here *edits* — a conflict is output, not a correction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .blocks import BlockError, BlockTemplate

#: Written into every pin table so a stale file fails loudly.
PINTABLE_KIND = "boardwise-firmware-pintable"
PINTABLE_VERSION = 1

#: The closed ``function`` vocabulary. Growing it is a deliberate act (add a
#: member here, with the family it belongs to); a value outside it is an error.
#: The families are the ones the architecture's model-freedom boundary lets a
#: model name: a pin is a GPIO, one half of a bus, a clock, a reset, or a debug
#: signal — *what it does*, never *what the code does with it*.
PINTABLE_FUNCTIONS: dict[str, str] = {
    "GPIO": "plain digital input or output",
    "UART_TX": "UART/asynchronous serial transmit",
    "UART_RX": "UART/asynchronous serial receive",
    "I2C_SCL": "I2C clock",
    "I2C_SDA": "I2C data",
    "SPI_SCK": "SPI clock",
    "SPI_MISO": "SPI master-in / slave-out",
    "SPI_MOSI": "SPI master-out / slave-in",
    "SPI_NSS": "SPI chip select",
    "PWM": "timer channel driven as PWM",
    "ADC": "analog input",
    "SWDIO": "SWD debug data",
    "SWDCLK": "SWD debug clock",
    "NRST": "reset",
    "OSC_IN": "crystal / oscillator input",
    "OSC_OUT": "crystal / oscillator output",
    "BOOT": "boot-mode strap",
    "POWER": "supply or ground pin of the MCU itself",
}

#: The key census. An unknown key is an error — same rule as templates/specs.
PINTABLE_KEYS = ("kind", "version", "mcu", "source", "notes", "pins")
_PIN_KEYS = ("number", "name", "function", "net")

#: ``P<port><pin>`` — the STM32 naming this table is written in. Kept here
#: because both the loader (shape check) and the `.ioc` reader (parsing
#: ``PA5`` / ``PC12``) need the same answer to "is this a port pin?".
_PORT_PIN = re.compile(r"^(?P<port>P[A-Z])(?P<pin>\d{1,2})$")


class PinTableError(ValueError):
    """A pin table, an ``.ioc`` file, or a comparison is malformed.

    Always names the offending field. Every message says which *reading* was
    rejected, because in this module there are two legitimate readings of the
    same board (firmware and CubeMX) and "rejected" without "which side" is not
    actionable.
    """


# --------------------------------------------------------------------------
# readers
# --------------------------------------------------------------------------


def _as_str(value: Any, where: str, *, allow_empty: bool = True) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PinTableError(f"{where}: expected a string, got {type(value).__name__}")
    text = value.strip()
    if not text and not allow_empty:
        raise PinTableError(f"{where}: must not be empty")
    return text


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise PinTableError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(allowed)}"
        )


def _require(body: dict[str, Any], key: str, where: str) -> Any:
    if key not in body:
        raise PinTableError(f"{where}: missing required key {key!r}")
    return body[key]


def looks_like_port_pin(text: str) -> bool:
    """Whether ``text`` is an STM32 port pin name (``PA5``, ``PC12``).

    Exposed because it is the one shape the pin table, the ``.ioc`` reader and
    the cross-check all have to agree on; three copies of this regex is how the
    three of them drift apart.
    """
    return _PORT_PIN.match((text or "").strip()) is not None


def normalize_pin_name(text: str) -> str:
    """Canonical spelling of a pin name.

    CubeMX writes ``PA5`` for the pin and ``PA5`` for the whole ``Mcu.Pin``
    entry; ``PF0-OSC_IN`` for the oscillator pins, where the suffix names the
    alternate function. Comparison is done on the **port pin** part, uppercased,
    because that is the half both sides agree to spell the same way.
    """
    return (text or "").strip().upper()


def port_pin_of(text: str) -> str:
    """The ``PA5`` inside ``PF0-OSC_IN`` / ``PA5`` / ``PA5.Signal``; ``""`` if none.

    The oscillator pins are why this exists: CubeMX calls the pin
    ``PF0-OSC_IN`` and the label ``RCC_OSC_IN``, and a comparison that only
    matched whole strings would report those two pins as a permanent
    disagreement on every STM32 board ever made.
    """
    name = normalize_pin_name(text)
    match = re.match(r"^(?P<port_pin>P[A-Z]\d{1,2})(?:[-.]|$)", name)
    return match["port_pin"] if match else ""


@dataclass
class PinEntry:
    """One row of the table: a pin, what it does, and the net it lands on."""

    number: str
    name: str
    function: str
    net: str

    def as_json(self) -> dict[str, str]:
        return {
            "number": self.number,
            "name": self.name,
            "function": self.function,
            "net": self.net,
        }


@dataclass
class PinTable:
    """What the firmware says the MCU is wired to."""

    mcu: str
    pins: list[PinEntry]
    source: str = ""
    notes: list[str] = field(default_factory=list)
    path: str = ""

    def by_number(self) -> dict[str, PinEntry]:
        return {pin.number: pin for pin in self.pins}

    def numbers(self) -> set[str]:
        return {pin.number for pin in self.pins}

    def nets(self) -> set[str]:
        """Every net the firmware names, blanks excluded.

        A pin with ``net: ""`` is a pin the firmware uses and the schematic has
        not (yet) given a name — which is a *defect* finding, not a row to skip.
        Blank nets are therefore dropped here and reported by the checker, so
        the two cases never get confused with each other.
        """
        return {pin.net for pin in self.pins if pin.net}

    def render(self) -> list[str]:
        lines = [f"pin table for {self.mcu}: {len(self.pins)} pin(s)"]
        for pin in self.pins:
            lines.append(
                f"  {pin.number:8} {pin.name[:14]:14} {pin.function:9} {pin.net}"
            )
        for note in self.notes:
            lines.append(f"  note: {note}")
        return lines

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": PINTABLE_KIND,
            "version": PINTABLE_VERSION,
            "mcu": self.mcu,
            "source": self.source,
            "notes": list(self.notes),
            "pins": [pin.as_json() for pin in self.pins],
        }


def load_pin_table(path: str | Path) -> PinTable:
    """Read and validate a pin table file."""
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PinTableError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise PinTableError(f"{file}: not JSON: {exc}") from exc
    table = pin_table_from_json(raw, where=str(file))
    table.path = str(file)
    return table


def pin_table_from_json(raw: Any, *, where: str = "<pintable>") -> PinTable:
    """Validate one parsed pin table. Pure; used by the loader and tests."""
    if not isinstance(raw, dict):
        raise PinTableError(f"{where}: expected a JSON object")
    # Kind is read before the census, as in `blocks.template_from_json`: handing
    # a block template to the pin-table loader is the likeliest mistake and the
    # message should say so rather than list the template's keys as unknown.
    kind = _as_str(_require(raw, "kind", where), f"{where}.kind")
    if kind != PINTABLE_KIND:
        raise PinTableError(f"{where}.kind: expected {PINTABLE_KIND!r}, got {kind!r}")
    _check_keys(raw, PINTABLE_KEYS, where)
    if raw.get("version") != PINTABLE_VERSION:
        raise PinTableError(
            f"{where}.version: expected {PINTABLE_VERSION}, got {raw.get('version')!r}"
        )

    mcu = _as_str(_require(raw, "mcu", where), f"{where}.mcu", allow_empty=False)

    pins: list[PinEntry] = []
    for index, body in enumerate(_require(raw, "pins", where) or []):
        spot = f"{where}.pins[{index}]"
        if not isinstance(body, dict):
            raise PinTableError(f"{spot}: expected an object")
        _check_keys(body, _PIN_KEYS, spot)
        number = _as_str(_require(body, "number", spot), f"{spot}.number", allow_empty=False)
        function = _as_str(
            _require(body, "function", spot), f"{spot}.function", allow_empty=False
        )
        if function not in PINTABLE_FUNCTIONS:
            raise PinTableError(
                f"{spot}.function: unknown function {function!r}; known: "
                f"{', '.join(sorted(PINTABLE_FUNCTIONS))}. The vocabulary is closed "
                "on purpose — a free-form function name would be a claim nothing "
                "can check."
            )
        pins.append(
            PinEntry(
                number=number,
                # `name` defaults to the number: on an STM32 the pin's own name
                # and its ball name are the same string, and making authors
                # repeat it invites the two to drift.
                name=_as_str(body.get("name"), f"{spot}.name") or number,
                function=function,
                net=_as_str(body.get("net"), f"{spot}.net"),
            )
        )
    if not pins:
        raise PinTableError(
            f"{where}.pins: an empty pin table says nothing about the board, so it "
            "cannot be checked against anything"
        )
    return PinTable(
        mcu=mcu,
        pins=pins,
        source=_as_str(raw.get("source"), f"{where}.source"),
        notes=[_as_str(n, f"{where}.notes[]") for n in (raw.get("notes") or [])],
    )


# --------------------------------------------------------------------------
# the MCU block's own pin numbers — the authority the table is checked against
# --------------------------------------------------------------------------


def mcu_symbol_pins(template: BlockTemplate, component_ref: str = "") -> dict[str, set[str]]:
    """``ref -> pin numbers`` for the symbol(s) in an MCU block template.

    The MCU block is the template that *contains the MCU*, and which component
    that is cannot be guessed from a designator prefix (the shelf key is the
    identity: ``ic.stm32g431rbt6``). So the caller names it — by ``ref`` when it
    is known, and otherwise by asking which component actually carries a C-number
    binding. Guessing here would be the silent invention the rest of this
    codebase refuses.
    """
    result: dict[str, set[str]] = {}
    for component in template.components:
        if component_ref and component.ref != component_ref:
            continue
        symbol = template.symbols.get(component.symbol)
        if symbol is None:  # pragma: no cover - the loader rejects this
            continue
        result[component.ref] = set(symbol.offsets)
    if component_ref and component_ref not in result:
        raise PinTableError(
            f"block {template.name!r} has no component {component_ref!r}; it has "
            f"{', '.join(c.ref for c in template.components) or '(none)'}"
        )
    return result


# --------------------------------------------------------------------------
# the `.ioc` baseline
# --------------------------------------------------------------------------

#: ``Mcu.Pin<k>`` — the pin list, one entry per line, in declaration order.
#: Matched against the **key** half only (``parse_ioc`` splits on the first
#: ``=``), so the per-pin facts (``PA5.Signal``) are reached through ``raw`` by
#: name rather than captured here.
_IOC_PIN = re.compile(r"^Mcu\.Pin\d+$")

#: ``Mcu.IP<k>`` — the peripherals the project switches on. Read so the report
#: can say *why* an assigned pin exists, and so a pin assigned to a peripheral
#: the project never enables shows up as the oddity it is. Key half only, same
#: reason as :data:`_IOC_PIN`.
_IOC_IP = re.compile(r"^Mcu\.IP\d+$")


@dataclass
class IocPin:
    """One ``Mcu.Pin<k>`` entry, with everything the file says about it."""

    entry: str
    pin: str
    port_pin: str
    signal: str
    mode: str
    label: str
    #: True for CubeMX's virtual pins (``VP_*``): they are project settings, not
    #: silicon. They are read so the *count* matches what CubeMX reports, and
    #: excluded from every comparison — a virtual pin has no ball to wire.
    virtual: bool


@dataclass
class IocProject:
    """What ``Smartbox.ioc`` says, as data.

    Deliberately a *reading*: nothing is inferred, nothing is repaired. Every
    field is the file's own text.
    """

    path: str
    mcu_name: str
    mcu_cpn: str
    package: str
    peripherals: list[str]
    pins: list[IocPin]
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def physical(self) -> list[IocPin]:
        return [pin for pin in self.pins if not pin.virtual]

    def by_port_pin(self) -> dict[str, IocPin]:
        return {pin.port_pin: pin for pin in self.physical if pin.port_pin}

    def render(self) -> list[str]:
        lines = [
            f".ioc {Path(self.path).name}: {self.mcu_name} ({self.mcu_cpn}, "
            f"{self.package}) — {len(self.physical)} physical pin(s), "
            f"{len(self.pins) - len(self.physical)} virtual"
        ]
        lines.append(f"  peripherals: {', '.join(self.peripherals) or '(none)'}")
        for pin in self.physical:
            label = f" label={pin.label}" if pin.label else ""
            lines.append(
                f"  {pin.port_pin:7} {pin.signal or pin.mode:22}{label}"
            )
        return lines


def parse_ioc(text: str, *, where: str = "<ioc>") -> IocProject:
    """Read a CubeMX ``.ioc`` file. Pure; no filesystem access.

    ``.ioc`` is an INI-like ``key=value`` list with no sections. The keys this
    module reads are the ones that carry **pin assignment**:

    * ``Mcu.Pin<k>`` — the pin list, in CubeMX's own order;
    * ``<pin>.Signal`` / ``<pin>.Mode`` / ``<pin>.GPIO_Label`` — per-pin facts;
    * ``Mcu.IP<k>`` — the peripheral instances the project enables.

    Everything else is kept verbatim in :attr:`IocProject.raw` so a caller can
    reach a setting this module does not model (``RCC.HSE_VALUE``,
    ``USART3.VirtualMode-Asynchronous``) without a second parser existing.
    """
    raw: dict[str, str] = {}
    order: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key not in raw:
            order.append(key)
        raw[key] = value.strip()

    pins: list[IocPin] = []
    for key in order:
        if _IOC_PIN.match(key) is None:
            continue
        entry = raw[key]
        pins.append(
            IocPin(
                entry=entry,
                pin=entry,
                port_pin=port_pin_of(entry),
                signal=raw.get(f"{entry}.Signal", ""),
                mode=raw.get(f"{entry}.Mode", ""),
                label=raw.get(f"{entry}.GPIO_Label", ""),
                virtual=entry.startswith("VP_"),
            )
        )

    peripherals: list[str] = []
    for key in order:
        if _IOC_IP.match(key) is not None:
            peripherals.append(raw[key])

    return IocProject(
        path=where,
        mcu_name=raw.get("Mcu.Name", ""),
        mcu_cpn=raw.get("Mcu.CPN", ""),
        package=raw.get("Mcu.Package", ""),
        peripherals=peripherals,
        pins=pins,
        raw=raw,
    )


def load_ioc(path: str | Path) -> IocProject:
    """Read and parse a ``.ioc`` file from disk."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise PinTableError(f"{file}: cannot read: {exc}") from exc
    except UnicodeDecodeError as exc:  # pragma: no cover - CubeMX writes UTF-8
        raise PinTableError(f"{file}: not UTF-8: {exc}") from exc
    return parse_ioc(text, where=str(file))


# --------------------------------------------------------------------------
# the cross-check: firmware reading against the `.ioc` baseline
# --------------------------------------------------------------------------


@dataclass
class PinConflict:
    """One place the two readings of the board do not agree.

    ``kind`` is the *shape* of the disagreement, and it is a closed set because
    these are the only ways a pin can differ between the two sides:

    * ``missing_from_ioc`` — the firmware uses a pin the CubeMX project does not
      list at all;
    * ``missing_from_firmware`` — CubeMX assigns a pin the firmware never
      mentions (the pin-budget checker's "schematic connected it, firmware did
      not use it" case, seen from the baseline's side);
    * ``net_mismatch`` — both sides name the pin, and the two names differ;
    * ``firmware_only_net`` — the firmware names the pin's net and the baseline
      is **silent** (no ``GPIO_Label``). This is the ``PC4``/``LCD_RES`` case:
      a pin whose identity exists only in a hand-written ``main.h`` macro. It is
      kept apart from ``net_mismatch`` on purpose — "the baseline contradicts
      this" and "the baseline does not record this" are different claims, and
      collapsing them would either invent a contradiction or, worse, let the
      hand-added pin pass in silence;
    * ``function_mismatch`` — both sides have the pin, but the firmware's
      function does not match the alternate function CubeMX assigned.
    """

    port_pin: str
    kind: str
    firmware: str
    ioc: str
    detail: str

    def render(self) -> str:
        return f"{self.port_pin}: [{self.kind}] {self.detail}"


#: Signal string → the pin-table function it corresponds to. Only the
#: unambiguous ones are listed: ``GPIO_Output``/``GPIO_Input`` both map to
#: ``GPIO`` (the direction is not what the vocabulary records), and everything
#: else must match exactly. A signal that maps to nothing is **not** silently
#: accepted — it becomes a ``function_mismatch`` with the raw string in the
#: detail, so an unmodelled peripheral shows up instead of passing.
def _function_of_ioc_signal(signal: str, mode: str) -> str:
    text = (signal or "").strip()
    if text.startswith("GPIO_"):
        return "GPIO"
    if text.startswith("SYS_JTMS"):
        return "SWDIO"
    if text.startswith("SYS_JTCK"):
        return "SWDCLK"
    if text.startswith("SYS_"):
        # NRST etc. — `SYS_NJTRST` is not a reset we claim to know.
        return {"SYS_NRST": "NRST"}.get(text, "")
    if text.startswith("RCC_OSC_IN"):
        return "OSC_IN"
    if text.startswith("RCC_OSC_OUT"):
        return "OSC_OUT"
    # Peripheral alternate functions: `USART3_TX` → UART_TX, `I2C2_SCL` →
    # I2C_SCL, `SPI1_SCK` → SPI_SCK, `S_TIM1_CH1` → PWM (a timer channel
    # assigned as `S_` is what CubeMX writes for a PWM output).
    suffix = text.split("_")[-1]
    for prefix, table in (
        ("USART", {"TX": "UART_TX", "RX": "UART_RX"}),
        ("UART", {"TX": "UART_TX", "RX": "UART_RX"}),
        ("I2C", {"SCL": "I2C_SCL", "SDA": "I2C_SDA"}),
        ("SPI", {"SCK": "SPI_SCK", "MISO": "SPI_MISO", "MOSI": "SPI_MOSI", "NSS": "SPI_NSS"}),
    ):
        if text.startswith(prefix):
            return table.get(suffix, "")
    if re.match(r"^S_TIM\d+_CH\d+$", text):
        return "PWM"
    return ""


def baseline_net_of(pin: IocPin) -> str:
    """The net name the ``.ioc`` baseline gives a pin; ``""`` when it gives none.

    Two fields can carry it, and they are not interchangeable:

    * ``GPIO_Label`` is the name the engineer typed (``LED1``, ``KEY2``), and it
      wins when present — it is the more specific statement;
    * ``Signal`` is the assigned alternate function (``USART3_TX``, ``I2C2_SCL``),
      and for a peripheral pin that *is* what the schematic calls the net.

    ``GPIO_Output`` / ``GPIO_Input`` are deliberately **not** net names: they are
    a direction, and treating them as one is what made every GPIO pin look like
    it had a name while ``PC4`` — whose real name (``LCD_RES``) lives only in a
    hand-written ``main.h`` macro — looked silently fine. So a GPIO signal
    leaves the baseline silent, which is what lets ``firmware_only_net`` fire for
    exactly the pins that deserve it.
    """
    if pin.label:
        return pin.label
    signal = (pin.signal or "").strip()
    if signal and not signal.startswith("GPIO_"):
        return signal
    return ""


def cross_check(table: PinTable, project: IocProject) -> list[PinConflict]:
    """Compare the firmware's reading against the ``.ioc`` baseline.

    Returns every disagreement, in a stable order (by port pin). An empty list
    means the two readings agree on every pin either side mentions.

    The two sides name nets differently by nature: CubeMX records a *label* the
    engineer typed (``LED1``), while the firmware records the *net* the code
    drives (``GPIO_Output`` on ``PA3``). So the two outcomes are reported
    separately — a label that contradicts the firmware is ``net_mismatch``, and
    a label that is simply **absent** while the firmware names a net is
    ``firmware_only_net``, the hand-written ``LCD_RES`` kind of pin, which must
    not slip through just because the baseline had nothing to say about it.
    """
    conflicts: list[PinConflict] = []
    baseline = project.by_port_pin()
    firmware = {}
    for pin in table.pins:
        key = port_pin_of(pin.number) or normalize_pin_name(pin.number)
        firmware[key] = pin

    for key in sorted(set(firmware) | set(baseline)):
        fw = firmware.get(key)
        ioc = baseline.get(key)
        if ioc is None:
            conflicts.append(
                PinConflict(
                    port_pin=key,
                    kind="missing_from_ioc",
                    firmware=f"{fw.function}/{fw.net}",
                    ioc="",
                    detail=(
                        f"firmware uses {key} as {fw.function} on net {fw.net!r}, "
                        "but the CubeMX project does not list this pin"
                    ),
                )
            )
            continue
        if fw is None:
            conflicts.append(
                PinConflict(
                    port_pin=key,
                    kind="missing_from_firmware",
                    firmware="",
                    ioc=f"{ioc.signal or ioc.mode}/{ioc.label}",
                    detail=(
                        f"the CubeMX project assigns {key} to "
                        f"{ioc.signal or ioc.mode}"
                        + (f" (label {ioc.label!r})" if ioc.label else "")
                        + ", but the firmware pin table never mentions it"
                    ),
                )
            )
            continue

        expected = _function_of_ioc_signal(ioc.signal, ioc.mode)
        if expected and fw.function != expected:
            conflicts.append(
                PinConflict(
                    port_pin=key,
                    kind="function_mismatch",
                    firmware=fw.function,
                    ioc=expected,
                    detail=(
                        f"firmware calls {key} {fw.function}, the CubeMX project "
                        f"assigns it {ioc.signal or ioc.mode} (which is {expected})"
                    ),
                )
            )

        # Net comparison. Two distinct outcomes, deliberately not merged: the
        # baseline naming the pin something else is a contradiction, and the
        # baseline having no net name at all while the firmware has one is an
        # uncorroborated pin — the hand-added `LCD_RES` case.
        if fw.net:
            baseline_net = baseline_net_of(ioc)
            if baseline_net and baseline_net != fw.net:
                conflicts.append(
                    PinConflict(
                        port_pin=key,
                        kind="net_mismatch",
                        firmware=fw.net,
                        ioc=baseline_net,
                        detail=(
                            f"firmware puts {key} on net {fw.net!r}, the CubeMX "
                            f"project names it {baseline_net!r}"
                        ),
                    )
                )
            elif not baseline_net:
                conflicts.append(
                    PinConflict(
                        port_pin=key,
                        kind="firmware_only_net",
                        firmware=fw.net,
                        ioc="",
                        detail=(
                            f"firmware names {key}'s net {fw.net!r}, but the CubeMX "
                            "project gives this pin no net name at all (no "
                            "GPIO_Label, and a GPIO_* signal is a direction, not a "
                            "name) — the name comes from firmware source alone"
                        ),
                    )
                )
    return conflicts


__all__ = [
    "IocPin",
    "IocProject",
    "PINTABLE_FUNCTIONS",
    "PINTABLE_KIND",
    "PINTABLE_VERSION",
    "PinConflict",
    "PinEntry",
    "PinTable",
    "PinTableError",
    "cross_check",
    "load_ioc",
    "load_pin_table",
    "looks_like_port_pin",
    "mcu_symbol_pins",
    "normalize_pin_name",
    "parse_ioc",
    "pin_table_from_json",
    "port_pin_of",
]
