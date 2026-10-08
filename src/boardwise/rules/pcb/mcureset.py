"""An MCU's reset and boot handling, as an inventory of what is on those nets (task 131e).

131e gave the MCU package two halves that read the same object (one
``ic.mcu`` part) by two different routes. :mod:`boardwise.rules.pcb.mcusupply`
asks 「does every supply net have a bypass near it」; this module asks the two
questions that are not about bypasses at all and have been waiting on the same
netlist view:

* **复位** — the ``NRST`` net's **membership**. Whether the reset net has a
  pull-up, a capacitor to ground, and a button on it is a connectivity fact that
  the netlist already answers and geometry does not: the answer is the set of
  members, not a distance. A board whose ``NRST`` carries nothing but the MCU
  itself works (every STM32 has an internal pull-up) and is a *different board*
  from one whose reset net has an RC and a switch — so the row reports the
  inventory and, when the inventory is empty, says so in those words.
* **启动** — the ``BOOT0`` pin's handling. Whether ``BOOT0`` is pulled down to
  run from flash, tied high to boot the system memory, or left floating is again
  a membership fact: the net's other members and where they go.

**The pin is found by name, and the name is the whole method.** ``NRST`` appears
as ``NRST`` (毕设FOC 1.0.0 U1 pin 14) and as ``PG10-NRST`` (ROBOT U1 pin 7,
药箱 U1 pin 7), ``BOOT0`` as ``BOOT0`` (1.0.0 pin 94) and ``PB8-BOOT0`` (ROBOT
pin 61). Both are read as a **substring of the pin name**, never off the net:
ROBOT's ``NRST`` *net* is right and its ``NRESET`` net (pins ``PA5`` / ``PB14``,
going out to the gate driver ``DRV1``) is a different signal entirely, and a
net-name test would have pulled the driver's fault line into a reset audit. The
name is also what makes the row able to say *which pin* it means.

**Why no verdict.** Neither question has a ruling. 岳 has decided no reset-time
constant, no acceptable ``NRST`` RC, and no rule for how close the reset button
has to be — and 1.0.0 measures why a threshold here would be premature rather
than merely unpinned: its reset net has all three parts (``R30`` 10 K pull-up,
``C73`` 100 nF, the ``RST`` button) and **all three sit between 608 and 638 mil
from the H743**. That is simultaneously a well-formed RC reset network and a
placement question no one has ruled on, so the distances are printed and the
judgement is not made.

**Empty is a row, and its wording is the finding.** A reset net carrying only the
MCU prints 「NRST 网上除 MCU 外无外部元件（纯内部上拉复位）」 — ROBOT's is exactly
that, and it is a real gap in the board rather than a gap in the tool, so the row
names it rather than passing over it in silence. The same shape applies to
``BOOT0``: a pin whose net carries nothing else is reported as such, because
「nobody fitted a boot resistor」 and 「nobody looked」 must not read the same.

**Measured, not judged**, as in 131b–131e: every row is ``INFO`` and there is no
distance threshold in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from ...core.measure import component_distance
from ...core.model import is_ground_net
from ...core.parts import category_of, find_facts, load_parts
from ..decap import looks_like_capacitor
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .crystal import MCU_CATEGORIES
from .distance import _measurement, _mil

__all__ = [
    "BOOT0_NAME_MARKER",
    "NRST_NAME_MARKER",
    "McuReset",
    "McuResetBoot",
    "boot0_pins_of",
    "reset_pins_of",
]


#: The substring an MCU pin's **name** must carry for it to be the reset pin.
#:
#: Read case-insensitively on the uppercased name. ``NRST`` and ``PG10-NRST``
#: both match and ``NRESET`` does not — which is correct and load-bearing, because
#: on ROBOT the ``NRESET`` net is the gate driver's fault output (pins ``PA5`` /
#: ``PB14`` → ``DRV1``), a different signal that a name test on ``NR`` would have
#: swept in. The substring is ``NRST``, not ``RESET``, for exactly that reason.
NRST_NAME_MARKER = "NRST"

#: The substring an MCU pin's **name** must carry for it to be the boot-mode pin.
#:
#: ``BOOT0`` and ``PB8-BOOT0`` both match. A part with more than one boot pin
#: (``BOOT0``/``BOOT1``) yields more than one row rather than being folded: they
#: are separate straps with separate resistors, and merging them would hide a
#: ``BOOT1`` that was left floating.
BOOT0_NAME_MARKER = "BOOT"


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


@dataclass(frozen=True)
class _NamedPin:
    """One MCU pin found by a name marker, with what it sits on."""

    number: str = ""
    name: str = ""
    net: str = ""


def reset_pins_of(component: object) -> list[_NamedPin]:
    """This part's **reset** pins — a name carrying ``NRST``, that carry a net."""
    return [
        _NamedPin(
            number=str(getattr(pin, "number", "") or ""),
            name=str(getattr(pin, "name", "") or ""),
            net=str(getattr(pin, "net", "") or ""),
        )
        for pin in (getattr(component, "pins", ()) or ())
        if NRST_NAME_MARKER in _upper(getattr(pin, "name", ""))
        and getattr(pin, "net", "")
    ]


def boot0_pins_of(component: object) -> list[_NamedPin]:
    """This part's **boot-mode** pins — a name carrying ``BOOT``, that carry a net."""
    return [
        _NamedPin(
            number=str(getattr(pin, "number", "") or ""),
            name=str(getattr(pin, "name", "") or ""),
            net=str(getattr(pin, "net", "") or ""),
        )
        for pin in (getattr(component, "pins", ()) or ())
        if BOOT0_NAME_MARKER in _upper(getattr(pin, "name", ""))
        and getattr(pin, "net", "")
    ]


def _nearest_placed(
    board, mcu: str, designators: list[str]
) -> tuple[float, str] | None:
    """``(mil, designator)`` for the nearest member this document places, or ``None``.

    The same house measurement as the supply rule —
    :func:`~boardwise.core.measure.component_distance`, which refuses same-net
    pad pairs by design, so on a reset net the number is the gap between the
    part bodies rather than between two pads the board wired together. A member
    this PCB document does not place is **not measured**, not 「infinitely far」,
    and a row whose every member is unplaced prints the members without a
    distance rather than a fabricated one.
    """
    rows = [
        (_mil(distance.edge_distance), designator)
        for designator in designators
        for distance in (component_distance(board, designator, mcu),)
        if distance is not None
    ]
    return min(rows) if rows else None


@dataclass(frozen=True)
class McuReset:
    """One MCU's reset and boot pins, with the two nets they name."""

    designator: str = ""
    category: str = ""
    board_model: object = None
    reset_pins: tuple[_NamedPin, ...] = ()
    boot_pins: tuple[_NamedPin, ...] = ()


#: How a reset-net member is described: the bucket it falls into.
#:
#: Deliberately coarse and deliberately **stated in the row** rather than graded.
#: The buckets are the four things a reset network is made of, and the row names
#: which one each member is so a reader can disagree with a classification
#: without having to re-derive it.
PART_PULLUP = "pull-up candidate (a resistor reaching a supply net)"
PART_CAP_TO_GROUND = "capacitor to ground"
PART_SWITCH = "switch / button"
PART_OTHER = "other member (unclassified)"


def _bucket(model: object, designator: str, net: str, library) -> str:
    """Which of the four reset-network buckets this member falls into.

    The test is the part's **own declared shape** plus where its other terminals
    go — never its designator prefix alone and never the net name. A resistor
    whose other end is a supply-class net is a pull-up candidate; a resistor
    whose other end is a ground net is a pull-**down**, which for a reset net
    means something different and is reported as :data:`PART_OTHER` rather than
    being counted as the pull-up the row is looking for. That asymmetry is the
    reason the two directions are checked separately rather than by
    "reaches a power net" in the abstract.
    """
    component = (getattr(model, "components", {}) or {}).get(designator)
    if component is None:
        return PART_OTHER
    category = category_of(
        str(getattr(component, "footprint", "") or ""), designator
    )
    others = {
        pin.net
        for pin in (getattr(component, "pins", ()) or ())
        if pin.net and pin.net != net
    }
    if looks_like_capacitor(
        component.designator,
        component.value or "",
        component.mpn or "",
        component.lcsc_part or "",
        library,
        footprint=component.footprint or "",
    ):
        return PART_CAP_TO_GROUND if any(is_ground_net(o) for o in others) else PART_OTHER
    if category == "res":
        return (
            PART_PULLUP
            if any(not is_ground_net(o) for o in others)
            else PART_OTHER
        )
    if category in ("sw", "switch"):
        return PART_SWITCH
    if category == "conn":
        return PART_SWITCH
    return PART_OTHER


def _read_mcus(model: object, library) -> list[McuReset]:
    """Every ``ic.mcu`` part, with its reset and boot pins read.

    The same exact-MPN-then-LCSC shelf lookup 131b–131e make, so all four MCU
    rules agree on which parts are microcontrollers.
    """
    readings: list[McuReset] = []
    components = getattr(model, "components", {}) or {}
    for designator in sorted(components):
        component = components[designator]
        entry = find_facts(
            library,
            mpn=str(getattr(component, "mpn", "") or ""),
            lcsc=str(getattr(component, "lcsc_part", "") or ""),
        )
        category = (entry.category or "") if entry is not None else ""
        if category not in MCU_CATEGORIES:
            continue
        readings.append(
            McuReset(
                designator=str(designator),
                category=category,
                board_model=model,
                reset_pins=tuple(reset_pins_of(component)),
                boot_pins=tuple(boot0_pins_of(component)),
            )
        )
    return readings


class McuResetBoot(PcbRule):
    """An MCU's ``NRST`` net and its ``BOOT`` straps: what is actually on them.

    One row per reset pin and one per boot pin, each carrying the net's **other**
    members — because the question is not 「is there a capacitor near pin 14」 but
    「what else is on this net」, and that is the netlist's answer rather than a
    measurement.

    * **复位**: the ``NRST`` net's members, bucketed into pull-up / capacitor-to-
      ground / switch by :func:`_bucket`, each with its distance to the MCU
      printed. A net with **no** member besides the MCU prints the pure
      internal-pull-up row, which is ROBOT's measured case and a real gap.
    * **启动**: the boot pin's net members and where each one's other terminals
      land, so a ``10K`` to ``GND`` (run from flash) reads differently from a tie
      to ``VCC`` (boot the system bootloader) — the difference is the pin, and
      saying only 「a resistor is there」 would lose it.

    **No verdict anywhere.** Every row is ``INFO``: no reset-time constant, no
    ``NRST`` RC requirement and no reset-button distance has been ruled on, and
    1.0.0's own numbers (all three parts 608–638 mil away) are exactly why that
    gap is not papered over. See the module head.
    """

    id = "pcb-mcu-reset-boot"
    title = "An MCU's reset net and boot straps carry the parts they need"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf on the same contract 131b,
        131c, 131d and the supply half of 131e honour.
        """
        model = ctx.pcb_model
        board = ctx.board
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for mcu in _read_mcus(model, library):
            for pin in mcu.reset_pins:
                findings.append(self._one_reset(mcu, board, pin, library))
            for pin in mcu.boot_pins:
                findings.append(self._one_boot(mcu, board, pin, library))
        return findings

    # -- rows -------------------------------------------------------------

    def _identity(self, mcu: McuReset) -> list[str]:
        return [
            f"{mcu.designator} read as an MCU because the shelf category is "
            f"{mcu.category!r}",
            "reset and boot pins are read off the pin **name** as a substring, "
            "never off the net name — a net-name test would have swept in "
            "ROBOT's `NRESET` net, which carries the gate driver's fault "
            f"output (DRV1), not this pin's reset",
        ]

    def _others(
        self, mcu: McuReset, net: str
    ) -> list[tuple[str, str, str]]:
        """``(designator, value, category)`` for every member but the MCU.

        De-duplicated: an MCU reaches a net through one pin per terminal, so a
        part listed once per pin would print several times.
        """
        net_obj = (getattr(mcu.board_model, "nets", {}) or {}).get(net)
        seen: list[tuple[str, str, str]] = []
        for designator, _pin in (getattr(net_obj, "pins", None) or []):
            owner = str(designator)
            if owner == mcu.designator or any(row[0] == owner for row in seen):
                continue
            component = (getattr(mcu.board_model, "components", {}) or {}).get(owner)
            if component is None:
                continue
            seen.append(
                (
                    owner,
                    str(getattr(component, "value", "") or ""),
                    category_of(
                        str(getattr(component, "footprint", "") or ""), owner
                    ),
                )
            )
        return seen

    def _lands_on(self, model: object, designator: str, net: str) -> str:
        """Where a member's **other** terminals land — the direction that matters.

        「a resistor on ``NRST``」 does not say whether the reset is pulled up or
        down, and for a reset net those are different circuits; the bucket
        (:func:`_bucket`) uses this same reading, so the row and the judgement
        cannot disagree.
        """
        component = (getattr(model, "components", {}) or {}).get(designator)
        others = sorted(
            {
                pin.net
                for pin in (getattr(component, "pins", ()) or ())
                if pin.net and pin.net != net
            }
        )
        return ", ".join(others) or "(this net only — both terminals here)"

    def _placement(self, board, designator: str, mcu: str) -> str:
        distance = component_distance(board, designator, mcu)
        if distance is None:
            return "not placed by this PCB document"
        return f"{_mil(distance.edge_distance):.1f} mil edge-to-edge"

    def _one_reset(
        self, mcu: McuReset, board, pin: _NamedPin, library
    ) -> Finding:
        """The reset row: what else is on ``NRST``, bucketed, and how far."""
        model = mcu.board_model
        others = self._others(mcu, pin.net)
        buckets = {bucket: [] for bucket in
                   (PART_PULLUP, PART_CAP_TO_GROUND, PART_SWITCH, PART_OTHER)}
        lines: list[str] = []
        for designator, value, _category in others:
            bucket = _bucket(model, designator, pin.net, library)
            buckets[bucket].append(designator)
            placement = self._placement(board, designator, mcu.designator)
            lines.append(
                f"{designator} value {value or '(nobody wrote one down)'}, "
                f"category {category_of(str(getattr((model.components or {})[designator], 'footprint', '') or ''), designator)!r} "
                f"→ {bucket} (other terminals on "
                f"{self._lands_on(model, designator, pin.net)}), {placement}"
            )
        placed = _nearest_placed(board, mcu.designator, [d for d, _v, _c in others])
        if others:
            summary = (
                f"{mcu.designator} pin {pin.number} {pin.name!r} @ {pin.net!r}: "
                f"{len(others)} external member(s) — "
                + "; ".join(
                    f"{label}: "
                    + (", ".join(sorted(names)) if names else "(none)")
                    for label, names in buckets.items()
                )
                + (
                    f"; nearest external member **{placed[1]}** at "
                    f"{placed[0]:.1f} mil edge-to-edge"
                    if placed
                    else ""
                )
            )
        else:
            summary = (
                f"{mcu.designator} pin {pin.number} {pin.name!r} @ {pin.net!r}: "
                f"**{pin.net} 网上除 {mcu.designator} 外无外部元件（纯内部上拉复位）** "
                "— no pull-up resistor, no capacitor to ground, no switch and no "
                "connector reaches this reset net, so the part relies entirely "
                "on the MCU's internal pull-up; that is a real board fact, not a "
                "gap in this reading"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                summary
                + " — inventory only, no reset-time / RC / button-distance "
                "threshold has been ruled on, and 毕设FOC 1.0.0's own three "
                "parts sit 608–638 mil away, which is why this rule prints the "
                "numbers and does not judge them"
            ),
            evidence=[
                *self._identity(mcu),
                f"reset pin found by a substring of its **name** on "
                f"{NRST_NAME_MARKER!r}: pin {pin.number} {pin.name!r} @ "
                f"{pin.net!r}",
                f"net {pin.net!r} members other than {mcu.designator}: "
                + (", ".join(f"{d} ({v!r})" for d, v, _ in others) or "(none)"),
                *(lines or [f"net {pin.net!r} carries nothing but the MCU"]),
                "a member is bucketed by its own declared shape and by where its "
                "*other* terminals land, never by its designator prefix alone; "
                "a resistor reaching a ground net is reported as other rather "
                "than as the pull-up the row is looking for",
            ],
            target=FindingTarget(
                component_ref=mcu.designator,
                pin_refs=[pin.number],
                net_refs=[pin.net],
                counterpart_ref=placed[1] if placed else None,
                measurement=_measurement("distance", placed[0]) if placed else None,
            ),
        )

    def _one_boot(
        self, mcu: McuReset, board, pin: _NamedPin, library
    ) -> Finding:
        """The boot row: the strap's direction, which is the whole answer."""
        model = mcu.board_model
        others = self._others(mcu, pin.net)
        if not others:
            summary = (
                f"{mcu.designator} pin {pin.number} {pin.name!r} @ {pin.net!r} "
                "carries **no other member** — the boot strap is left to the "
                "MCU's own internal pull-down, so boot mode is whatever the "
                "part defaults to and nothing on this board sets it"
            )
        else:
            directions = "; ".join(
                f"{designator} value {value or '(nobody wrote one down)'} → other "
                f"terminals on {self._lands_on(model, designator, pin.net)}"
                f" ({self._placement(board, designator, mcu.designator)})"
                for designator, value, _category in others
            )
            summary = (
                f"{mcu.designator} pin {pin.number} {pin.name!r} @ {pin.net!r}: "
                f"{len(others)} member(s) set the strap — {directions}"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                summary
                + " — inventory only, no boot-mode requirement has been ruled on"
            ),
            evidence=[
                *self._identity(mcu),
                f"boot pin found by a substring of its **name** on "
                f"{BOOT0_NAME_MARKER!r}: pin {pin.number} {pin.name!r} @ "
                f"{pin.net!r}",
                f"net {pin.net!r} members other than {mcu.designator}: "
                + (", ".join(f"{d} ({v!r})" for d, v, _ in others) or "(none)"),
                "the direction matters more than the presence: a resistor to a "
                "ground net and a resistor to a supply net are different boot "
                "modes, so each member's other terminals are printed rather than "
                "collapsed to 'a resistor is there'",
            ],
            target=FindingTarget(
                component_ref=mcu.designator,
                pin_refs=[pin.number],
                net_refs=[pin.net],
            ),
        )