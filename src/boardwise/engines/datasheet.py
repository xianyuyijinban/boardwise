"""Candidate facts from a datasheet's own text (039 批② §WI-1).

This is the "提取候选事实" half of `parts fetch`: a **conservative** reader of
datasheet text that proposes `supply_pins` / `required_caps` / `nc_pins` records,
each quoting the line it came from and the page it was on. Three rules govern it,
and they are the same three the facts library has always had:

* **A page and a quote, or nothing.** Provenance is
  ``<label>, p.N（自动提取：'…'）, <url>`` — a person can check every proposal in
  seconds against the PDF, which is the only reason an unverified candidate is
  useful at all;
* **Never guess a shape.** `required_caps` needs a pin, `supply_pins` needs a pin
  and a name; a sentence with a voltage but no pin produces nothing rather than a
  record with an invented pin;
* **Operating and absolute maximum are different facts.** A range found under an
  *Absolute Maximum Ratings* heading becomes `v_abs_max`; under *Recommended
  Operating Conditions* / *Electrical Characteristics* it becomes `v_operating`.
  Reading an abs-max line as an operating range is the classic way to make a
  part look misapplied when it is not.

Everything that comes out of here is written with ``facts_verified: false``: 岳's
rule is that a fact extracted in-session may be *used* in the session, but it
drives no rule until a human vouches for it (039 批①'s gate).
"""

from __future__ import annotations

import re
from typing import Iterable

#: How many records of one kind to propose. A datasheet has hundreds of
#: candidate lines; the tool's job is to hand over a short, checkable list, not a
#: dump — the rest of the text is in the `.txt` beside it for the curator.
MAX_PER_KIND = 4

#: Pin names that mean "this pin is a supply". Kept as a table rather than a
#: pattern so `VS` (an op-amp's supply) and `VOUT` (not one) do not both match.
SUPPLY_NAMES = (
    "VCC", "VDD", "VDDIO", "VLOGIC", "VIN", "VBAT", "VBUS", "AVDD", "DVDD", "VS",
    # An op-amp's positive rail is spelled `V+`; its negative rail (`V-`) is the
    # return of a single supply in this project, so the operating range is kept on
    # the positive pin (the 039 批① curation made the same choice).
    "V+",
)

_PIN_NUMBER = re.compile(r"\b(?:pin|pins|PIN|Pins|引脚)\s*#?\s*(\d{1,3})\b")
#: A range must end in a **unit** `V`, not in the first letter of the next word:
#: the 039 批② demo caught `Figure 4-24 VDD - off comparator` being read as
#: "4 V to 24 V" with pin 24 (the figure number). `(?![\w])` is what makes `V`
#: a unit again.
_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*V?\s*(?:to|~|–|—|-|\.\.)\s*(\d+(?:\.\d+)?)\s*V(?![\w+/])"
    r"|(\d+(?:\.\d+)?)\s*V\s*(?:to|~|–|—|-)\s*(\d+(?:\.\d+)?)\s*V(?![\w+/])",
    re.IGNORECASE,
)
_TRIPLE = re.compile(r"\b(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*V(?![\w+/])")
#: The most common table shape in a TI/Infineon specification row: a **min and a
#: max** with one unit — `Supply voltage, VCC 3 3.6 V`, `VDD -0.5 6.5 V`.
_PAIR = re.compile(r"(?<![\d.])([−–—-]?\s?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*V(?![\w+/])")
#: Figure and table **captions** are not specifications: "Figure 4-24 VDD - off
#: comparator" is a pointer to a picture, and every number on it belongs to the
#: numbering, not to the part.
_CAPTION = re.compile(r"^\s*(?:figure|fig\.?|table|图|表)\s*[\d.\-–]", re.IGNORECASE)

#: Text-extraction artefacts: PDFs kern pin names apart, and an Infineon datasheet
#: hands back `6V DD - Supply Voltage` where the pin table says `6 VDD`. Matching
#: runs on a normalised copy while the **quote stays the file's own line**, so a
#: human can still find it in the text dump with a search.
_SPLIT_TOKENS = tuple(
    (re.compile(rf"\b{letter}\s+{rest}\b"), letter + rest)
    for letter, rest in (
        ("V", "DD"), ("V", "CC"), ("V", "IN"), ("V", "BAT"), ("V", "BUS"),
        ("V", "LOGIC"), ("G", "ND"), ("A", "VDD"), ("D", "VDD"),
    )
)


def _probe(line: str) -> str:
    """The line as the patterns see it: extraction artefacts folded back in."""
    text = line
    for pattern, replacement in _SPLIT_TOKENS:
        text = pattern.sub(replacement, text)
    return text
_CAP_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*(µ|μ|u|n|p)\s?F\b", re.IGNORECASE)
_DECOUPLING = re.compile(r"bypass|decoupl|退耦|去耦", re.IGNORECASE)
_NC_LINE = re.compile(r"\bNC\b|空脚|no connect", re.IGNORECASE)
_NC_VERDICT = re.compile(
    r"not internally connected|no connect|must be left|leave (?:it )?unconnected|"
    r"空脚|不连接|not connected",
    re.IGNORECASE,
)
_NC_PINS = re.compile(r"(\d{1,2}(?:\s*[,、和及]\s*\d{1,2})*)\s*[\w\s,、]{0,14}?\bNC\b")
_SECTION = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.、]?\s*)?"
    r"(Absolute Maximum Ratings|Recommended Operating Conditions|"
    r"Recommended Operating|Electrical Characteristics|Specifications|"
    r"Pin Configuration and Functions|Pin Functions|Pin Descriptions|"
    r"绝对最大值|推荐工作条件|电气特性|引脚)",
    re.IGNORECASE,
)
_ABS_MAX = re.compile(r"absolute maximum|绝对最大", re.IGNORECASE)
#: Any *numbered* heading starts a new section, recognized or not. The WCH manual's
#: `6.2. 5V电气参数` is not in :data:`_SECTION`'s vocabulary, and without this the
#: absolute-maximum section above it stayed "current" — every operating range on
#: page 5 came back as an absolute maximum.
_NUMBERED_HEADING = re.compile(r"^\s*\d+(?:\.\d+)*[.、]?\s+\S")


def pages_from_marked_text(text: str) -> list[str]:
    """`pdf_text`'s marked output → one string per page, in order.

    A page marker with nothing after it is an *empty* page, kept as an empty
    string: dropping it would shift every later page number, and a page number is
    what the provenance cites.
    """
    pages: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        match = re.match(r"^<<<page (\d+)>>>$", line.strip())
        if match:
            if current is not None:
                pages.append("\n".join(current))
            current = []
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        pages.append("\n".join(current))
    return pages


def _pin_is_a_voltage(pin: str, volts: list[float]) -> bool:
    """Is this "pin number" really one end of the voltage range on the same line?

    The row-shaped pin lookup ("the first number after the pin name") is right for
    a pin table and wrong for a specification row, and those two shapes share a
    page in every datasheet: `VCC 3 Supply` (pin 3) versus
    `Supply voltage, VCC 3 3.6 V` (3 V to 3.6 V). Comparing the candidate against
    the range's own endpoints is what tells them apart.
    """
    text = str(pin).strip()
    for value in volts:
        for spelling in (f"{value:g}", f"{value:.1f}", f"{value:.2f}"):
            if text == spelling or text == spelling.rstrip("0").rstrip("."):
                return True
    return False


def _quote(line: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", line).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _pin_from(line: str, name: str) -> str:
    """The pin number this line gives, either by `pin N` or by a table row."""
    match = _PIN_NUMBER.search(line)
    if match:
        return match.group(1)
    # A pin-table row usually starts (or restarts after the name) with the number:
    # "13 VDD Power supply voltage", "VCC 13 Supply".
    before = line[: line.upper().find(name)] if name in line.upper() else ""
    after = line[line.upper().find(name) + len(name) :] if name in line.upper() else ""
    for candidate in (before, after):
        numbers = re.findall(r"(?<![\d.])(\d{1,2})(?![\d.])", candidate)
        if numbers:
            return numbers[0] if candidate is after else numbers[-1]
    return ""


def _range_of(line: str) -> list[float] | None:
    match = _RANGE.search(line)
    if match:
        low_text, high_text = match.group(1) or match.group(3), match.group(2) or match.group(4)
        low, high = float(low_text), float(high_text)
        return [low, high] if low < high else None
    match = _TRIPLE.search(line)
    if match:
        low, high = float(match.group(1)), float(match.group(3))
        return [low, high] if low < high else None
    match = _PAIR.search(line)
    if match:
        # A datasheet writes a negative limit with a typographic minus as often as
        # with `-`: `VCC –0.3 6 V` is -0.3 V, and reading it as +0.3 V would turn a
        # below-ground allowance into an operating range.
        low = float(match.group(1).replace("−", "-").replace("–", "-").replace("—", "-").replace(" ", ""))
        high = float(match.group(2))
        return [low, high] if low < high else None
    return None


_NAMES_RE = "|".join(re.escape(name) for name in SUPPLY_NAMES)
#: `19 16 7 5 VCC` / `13 VDD` — a number **immediately** before the name. Only the
#: adjacent one counts, which is what makes a multi-package column table resolve
#: to the last column (the manual's SOP-8 pin) rather than to another package's.
_PIN_BEFORE_NAME = re.compile(rf"(?<![\w.])(\d{{1,2}})\s+(?=(?:{_NAMES_RE})\b)")
#: `VCC 3 Supply` / `V+ 8 — Positive` — the name, the number, then a word. The
#: trailing word is required: `VCC / 2` (a reference-output row) and
#: `VCC = low power` (a mode note) are not pin rows, and both are shapes that
#: would otherwise become "pin 2" and "pin 10" out of unrelated numbers.
_PIN_AFTER_NAME = re.compile(
    rf"\b({_NAMES_RE})\s+(\d{{1,2}})\s+(?:[—–−:\-|(]\s*)?(?=[A-Za-z\u4e00-\u9fff])"
)


def _pin_table_line(probe: str) -> tuple[str, str] | None:
    """``(name, pin)`` when this line really is a **pin table** row.

    The measured shapes: `VCC 3 Supply …` (TI), `13 VDD Power supply …` (a QFN pin
    table), `19 16 7 5 VCC 电源` (the WCH manual's per-package columns), and the
    Infineon one after normalisation (`6VDD - Supply Voltage`). A number merely
    *on the same line* as a supply name is not a pin — that reading is what turned
    `VCC / 2 reference output` into "pin 65" in the first version.
    """
    if match := _PIN_AFTER_NAME.search(probe):
        return match.group(1), match.group(2)
    if match := _PIN_BEFORE_NAME.search(probe):
        pin = match.group(1)
        if int(pin) > 0:
            rest = probe[match.end() :]
            name = re.search(rf"(?:{_NAMES_RE})\b", rest)
            if name:
                return name.group(0), pin
    return None


def candidate_facts(
    pages: Iterable[str], *, label: str, url: str
) -> tuple[dict, list[str]]:
    """``(facts, notes)`` — the proposed facts and what the curator should read.

    Two passes over each page, because a datasheet states a supply in two places
    and neither half is a fact on its own:

    1. **pin table** rows — `VCC 3 Supply` (which pin) — and **specification**
       rows — `Supply voltage, VCC 3 3.6 V` (which range);
    2. the join, when both are on the same page: a `supply_pins` record whose
       provenance quotes *both* lines. That join is the whole reason this is not
       two separate greps: without it a TI datasheet yields nothing but
       near-misses, and with it the record cites the two statements it came from.

    A range found under an *Absolute Maximum Ratings* heading becomes
    `v_abs_max`; anywhere else it is `v_operating`. Nothing else is inferred: no
    pin ⇒ no record, and a "pin" that turns out to be the range's own end number
    is not a pin (:func:`_pin_is_a_voltage`).
    """
    supply: list[dict] = []
    caps: list[dict] = []
    nc_pins: list[str] = []
    nc_provenance = ""
    notes: list[str] = []
    near_misses: list[str] = []
    seen_supply: set[tuple[str, object, str]] = set()
    seen_caps: set[tuple[str, str]] = set()
    #: Pin rows and specification rows are collected across the **whole document**,
    #: not per page: measured, the pin table and the recommended-operating table
    #: sit on neighbouring pages in every datasheet this was tried on, and joining
    #: only within one page produced nothing for TI parts and a wrong abs-max-only
    #: record for the CAN transceiver.
    pin_rows: dict[str, list[tuple[int, str, str]]] = {}
    range_rows: dict[str, list[tuple[int, list[float], bool, str]]] = {}

    previous = ""
    for number, page in enumerate(pages, start=1):
        section = ""
        for line in page.splitlines():
            if _SECTION.match(line) or _NUMBERED_HEADING.match(line):
                section = line.strip()
            if _CAPTION.match(line):
                previous = line
                continue  # a figure/table number is not a specification
            probe = _probe(line)
            upper = probe.upper()
            if re.search(r"\b(" + "|".join(SUPPLY_NAMES) + r")\b", upper):
                row = _pin_table_line(probe)
                volts = _range_of(probe)
                name = row[0] if row else next(
                    (candidate for candidate in SUPPLY_NAMES
                     if re.search(rf"\b{candidate}\b", upper)),
                    "",
                )
                pin = row[1] if row else ""
                if pin and volts is not None and _pin_is_a_voltage(pin, volts):
                    pin = ""  # the number was the range's own end, not a pin
                absolute = bool(_ABS_MAX.search(section)) or bool(_ABS_MAX.search(line))
                if pin and volts is None:
                    pin_rows.setdefault(name, []).append((number, pin, line))
                elif volts is not None:
                    # Registered under **every** supply name on the line: one
                    # datasheet calls the positive rail `VS` in the table and `V+`
                    # in the pin list, and the join has to be able to meet.
                    for alias in {name, *(
                        candidate for candidate in SUPPLY_NAMES
                        if re.search(rf"\b{candidate}\b", upper)
                    )}:
                        range_rows.setdefault(alias, []).append(
                            (number, volts, absolute, line)
                        )
                    if not pin:
                        near_misses.append(
                            f"p.{number}: '{_quote(line)}'（有电压范围但没有引脚号，对着引脚表补）"
                        )
            if _DECOUPLING.search(probe) and re.search(r"\bpin", probe, re.IGNORECASE):
                value = _CAP_VALUE.search(probe)
                pin = _pin_from(probe, "PIN")
                if value is not None and pin and len(caps) < MAX_PER_KIND:
                    # µ/μ fold to `u`: the shelf spells caps `0.1uF` / `100nF`,
                    # and a value that cannot be compared is not a value.
                    unit = value.group(2).lower().replace("µ", "u").replace("μ", "u")
                    text = f"{value.group(1)}{unit}F"
                    key = (pin, text)
                    if key not in seen_caps:
                        seen_caps.add(key)
                        caps.append({
                            "pin": pin, "value": text,
                            "provenance": f"{label}, p.{number}（自动提取：'{_quote(line)}'）, {url}",
                        })
            if _NC_LINE.search(probe) and _NC_VERDICT.search(probe) and not nc_pins:
                match = _NC_PINS.search(probe)
                if match:
                    numbers = re.findall(r"\d{1,2}", match.group(1))
                    if numbers and match.start(1) == 0:
                        # The list may have been wrapped by the PDF: a line that
                        # *starts* with numbers is the continuation of the previous
                        # one ("2, 3, 4, 5, 14," / "15, 16, 17 Y Y NC"), and taking
                        # only the visible tail would under-report the NC set.
                        tail = re.findall(r"\d{1,2}", previous.rstrip().rstrip(","))
                        numbers = [*tail, *numbers]
                    if numbers:
                        nc_pins = sorted(set(numbers), key=int)
                        nc_provenance = (
                            f"{label}, p.{number}（自动提取：'{_quote(line)}'"
                            + ("；上一行是接续" if match.start(1) == 0 else "")
                            + f"）, {url}"
                        )
            previous = line

    # --- the join: a pin from the pin table, a range from the specification row.
    # Only the **first** pin row is joined. A datasheet of one part in four
    # packages repeats the pin table per package (the TLV9062 lists `V+ 8` for the
    # SOIC-8 and `V+ 2` for a 5-pin package), and emitting a record per package
    # would turn one part into a list of mutually exclusive answers. The others are
    # named in a note instead, where a curator can see them and pick.
    for name in sorted(set(pin_rows) & set(range_rows)):
        others = [f"{pin}(p.{page})" for page, pin, _line in pin_rows[name][1:]]
        if others:
            near_misses.append(
                f"引脚表里 {name} 还出现在别的封装：{'、'.join(others)}"
                "（不同封装，按你用的封装选）"
            )
        pin_page, pin, pin_line = pin_rows[name][0]
        for range_page, volts, absolute, range_line in range_rows[name]:
            if len(supply) >= MAX_PER_KIND:
                break
            key = (pin, tuple(volts), "abs" if absolute else "op")
            if key in seen_supply:
                continue
            seen_supply.add(key)
            record: dict = {"pins": [pin], "name": name}
            record["v_abs_max" if absolute else "v_operating"] = volts
            supply.append({
                **record,
                "provenance": (
                    f"{label}, p.{pin_page} 引脚表：'{_quote(pin_line)}'；"
                    f"p.{range_page} {'绝对最大值' if absolute else '工作范围'}："
                    f"'{_quote(range_line)}', {url}"
                ),
            })

    facts: dict = {}
    if supply:
        facts["supply_pins"] = supply
    if caps:
        facts["required_caps"] = caps
    if nc_pins:
        facts["nc_pins"] = {"pins": nc_pins, "provenance": nc_provenance}

    if not facts:
        notes.append(
            "没有可自动提取的候选事实（本工具的规则很窄：只有「引脚表 + 规格行都在同一页」"
            "或「一行里引脚号与电压/电容值齐全」才提）。全文已经落在同目录的 .txt 里，"
            "由 AI 读全文再填。"
        )
    else:
        notes.append(
            "自动提取的候选事实只认窄句式，且**未经入库核验**（facts_verified: false）："
            "逐条对着 provenance 里的页码与引文核一遍，再决定入库。"
        )
    if near_misses:
        notes.append(
            "以下行像供电规格但缺一项（引脚号或电压范围），工具没有替它猜 —— 按页码回原文看："
            + "；".join(near_misses[:6])
        )
    return facts, notes
