"""The PCB review runner (task 126a, 阶段 C 的棒 1：地基).

A **parallel** runner to :mod:`boardwise.engines.review`: it does not touch
``BUILTIN_RULES``, does not share its rule base's ``check(model)`` signature, and
produces its own report section. What it does share is the *finding contract* —
the findings it returns are ordinary :class:`~boardwise.rules.base.Finding`
objects, so ``review-mark`` and ``warning_triage`` read PCB findings out of the
same ``findings[]`` array as schematic ones, and module attribution comes for
free from ``refs`` / ``target.component_ref``.

Three things live here:

* :func:`build_module_of` — the **module attribution** builder (钉 2), a pure
  function so it can be unit-tested without a board;
* :data:`BUILTIN_PCB_RULES` — the ordered rule list. Empty in 126a (地基);
  126b filled it with the two distance rules and 126c adds the IPC ones, and
  the structure gate pins the list as the truth (a rule that exists but is not
  listed does not run);
* :func:`run_pcb_review` — the per-document driver. An ``.epro2`` path →
  :class:`~boardwise.parsers.epru.Epro2Source` → one
  :class:`~boardwise.core.geometry.BoardGeometry` per PCB document, named by its
  ``META`` title (钉 4: documents are selected by **title**, never by a magic
  count such as "the one with the most components"). **166**: the path is the
  *only* thing this driver asks for, which is why the online `checkup` can use it
  unchanged — its `project-file` tier downloads the whole project, writes it to a
  temporary ``.epro2`` and passes that file here, so a live run and an offline
  run over the same archive are two readings of one pipeline rather than two
  implementations of one question.

UNKNOWN discipline (钉 6): a rule that lacks a fact (current, voltage, contract)
states so through an :class:`~boardwise.rules.base.Outcome` and names the missing
fact — it never assumes. This batch wires the plumbing those rules will use; the
rules themselves arrive in 126b/126c.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..core.geometry import FRAGMENT_KIND_EXTRA_RECORDS, FRAGMENT_KIND_STROKE_PIECE
from ..core.measure import read_stackup
from ..core.model import ProjectModel
from ..core.netdomains import is_auto_net
from ..rules.pcb.base import PcbReviewContext, PcbRule
from ..rules.pcb.derating import DeratingPackage
from ..rules.pcb.distance import (
    MIN_OUTLINE_CORNERS,
    BoardOffEdge,
    ComponentSpacing,
    DecapDistance,
)
from ..rules.pcb.footprint import FootprintConsistency
from ..rules.pcb.polarity import PolarityOrientation
from ..rules.pcb.silk import SilkDesignator
from ..rules.pcb.ipc import TrackAmpacity, VoltageSpacing
from ..rules.pcb.keepout import KeepoutViolation
from ..rules.pcb.crystal import McuCrystalPlacement
from ..rules.pcb.crystalkeepout import McuCrystalKeepout
from ..rules.pcb.foc import (
    FocDecapProximity,
    FocGateTraceWidth,
    FocGroundPlane,
    FocPowerLoopArea,
    FocTrackCorners,
)
from ..rules.pcb.focground import (
    FocGroundDomains,
    FocGroundTie,
    FocReturnPath,
)
from ..rules.pcb.focthermal import (
    FocThermalExitPath,
    FocThermalViaArray,
    FocThermalViaStyle,
)
from ..rules.pcb.mcusupply import McuSupplyGroups
from ..rules.pcb.mcureset import McuResetBoot
from ..rules.pcb.regulator import RegulatorCapDistance
from ..rules.pcb.fbplacement import RegulatorFbPlacement
from ..rules.pcb.highspeed import (
    CrossSplit,
    DiffPairInventory,
    DiffPairSkew,
    DiffPairViaParity,
    GroundViaCompanion,
)
from ..rules.base import SEVERITY_ORDER, Finding

#: The rules this runner applies, in execution order. Empty in 126a (地基);
#: 126b added the two distance rules, 126c added the two IPC-2221 ones, 131b
#: added the regulator input/output capacitor rule, 131c the regulator
#: feedback-divider rule, 131d ``pcb-mcu-crystal-placement`` and 131f
#: ``pcb-mcu-crystal-keepout`` — the six
#: L1-geometry readers of *placement* sit together, ahead of the
#: standards-derived readings, each batch adding to this list and to the
#: structure gate that says "the list is the truth". The ordering is the
#: execution order (like ``BUILTIN_RULES``), and the
#: report's ``pcb_review.boards[].checksRun`` records it so a reader can tell
#: what ran.
#:
#: The order below is **declaration order in this list**, and it is the order a
#: reader of ``findings[]`` sees before the per-board severity sort: the
#: decoupling question first (a capacitor in the wrong place is the defect that
#: changes the circuit), then the geometry sweep (collisions and the board
#: frame, which are assembly and manufacturing facts), then the two standards-
#: derived readings (载流 is a safety fact, 安规间距 is a compliance fact — the
#: severity sort puts them first in `findings[]` regardless of where they are
#: declared). Nothing depends on it — no rule reads another's output — so it is
#: a reading choice, and each batch appends rather than reordering. 131b's
#: ``pcb-regulator-cap-distance``, 131c's ``pcb-regulator-fb-placement``, 131d's
#: ``pcb-mcu-crystal-placement`` and 131f's ``pcb-mcu-crystal-keepout`` are the
#: four inserts rather than appends, and they sit together: the first two read
#: the same measurement primitive on the same object (one regulator), one
#: question further along its power path each, 131d moves to the next object
#: over (one MCU's oscillator network) and 131f looks at that same crystal
#: along the other axis (straight through the board) — all placement questions,
#: each answering what the one before could not.
#:
#: **133b inserted the five FOC rules as a contiguous block** after
#: ``pcb-mcu-reset-boot`` and ahead of the geometry sweep, in the task book's
#: own table order (R16 → R31 → R11 → R13 → R20). They go there rather than at
#: the end because they are the same shape as the block above — L1 geometry
#: readers that measure placement — and a reader scanning the list wants the
#: whole 「what does this board's layout say」 family together. The intra-block
#: order is the order of the questions (the driver's bypass, then the board's
#: planes, then the traces, then the bends, then the loop) and again nothing
#: depends on it: no FOC rule reads another's output.
#:
#: **133c appends the three ground-system rules to that same block**, right after
#: ``pcb-foc-power-loop-area`` and still ahead of the geometry sweep. They are
#: the same L1-geometry shape and they sit after the loop-area rule because that
#: is the last of 133b's five and these three answer what comes *next* in the
#: question order — the two ground domains and how they join (R1, R1b), then
#: what the gate / switching / sense traces see under them (R5).
#:
#: **151 (E 阶段第一棒, 封装一致性) inserts ``pcb-footprint-consistency``
#: immediately before the geometry sweep** — after the FOC block and ahead of
#: ``pcb-component-spacing``. It is the roadmap's 第三步「器件检查」第一条, and
#: it goes there rather than at the end because it is the same shape as
#: ``pcb-mcu-reset-boot``: a rule whose answer is a fact read off the netlist +
#: the library, not a distance. Placing it at the head of the tail keeps the
#: list readable as 「power-path readings → device readings → board-frame
#: sweep」, and nothing depends on the position (no rule reads another's
#: output). What it adds to the list is the **first** PCB rule that reads the
#: *schematic* model by name rather than through ``module_of`` — and it is the
#: reason :attr:`PcbReviewContext.board_uuid` exists.
#:
#: **152 (E 阶段第二棒) added ``pcb-polarity-orientation`` and
#: ``pcb-silk-designator``** right after it, and **153 (第三棒) adds
#: ``pcb-derating-package``** after those two: the three device-reading rules
#: of 第三步 sit together at the head of the tail, in the roadmap's own order
#: (封装 → 极性/丝印 → 降额的物理层). 153 is the first PCB rule at ``L2-facts``
#: rather than ``L1-pcb-geometry`` — its limits are datasheet columns, not
#: distances — and it is placed among the device readings because that is the
#: family whose subject is a *part* rather than a pair or a plane.
#:
#: **R2-1 appends ``pcb-keepout-violation``** at the very end: the first reader
#: of 162b's ``prohibit_regions``, a board-frame sweep like the IPC pair before
#: it, and independent of every other rule's output.
#:
#: **bug98-A inserts ``pcb-component-off-board`` immediately after
#: ``pcb-component-spacing``**: 126b shipped the board-frame error *inside*
#: ``pcb-component-spacing``, and bug98-A split the two questions apart so a
#: board whose own frame did not read can no longer bury the spacing rows under
#: a hundred identical-looking ERRORs. It sits where it was born (its rows used
#: to be the spacing rule's ERRORs), so a reader diffing two reports sees the
#: same rows under a different id and nothing moved position.
#:
#: **182 appends ``pcb-hs-diffpair-inventory``** at the very end, and it is the
#: first row of a new family rather than a reading like the rows above it: every
#: batch before 182 added a *judgement* (a distance, a width, a comparison),
#: while this one prints the high-speed family's **inventory** — one ``INFO``
#: naming each differential pair the board declares or its net names imply
#: (``rules/pcb/highspeed.py``). It goes last because nothing follows it yet:
#: 0.6.0's length / split / impedance rules will be appended *after* this row,
#: each of them a reading of the pairs this one lists. It has no threshold,
#: ``INFO`` severity throughout, and reads no other rule's output, so its
#: position is a reading choice like every other append above.
#:
#: **200B appends ``pcb-hs-cross-split``** after 182's inventory: the first
#: *judgement* of the high-speed family, and the first reader of 182's
#: inventory output — it measures each high-speed track's copper coverage on
#: its physical reference layer and files one ``WARN`` per track that crosses a
#: split. It goes after the inventory because the inventory is the list it
#: reads, and it is a ``WARN`` (a house rule, 200B, iterable) rather than an
#: ``ERROR`` because the goods are still being tuned.
#:
#: **200C1 appends ``pcb-hs-via-ground-companion``** after 200B's split rule:
#: the family's first question about **vias** rather than copper, and the first
#: reader of 182's high-speed net set from the via side — one ``WARN`` per
#: high-speed via whose nearest ground-class via centre is farther than the
#: house radius (``core.highspeed.GROUND_VIA_RADIUS_MIL``). It goes last
#: because it judges a different object: 182 lists pairs, 200B judges the
#: copper a pair runs on, this one judges the transition between layers. It
#: reads no other rule's output, has no ordering dependency, and is a ``WARN``
#: (a house rule, 200C1, iterable) for the same reason 200B is.
#:
#: **200C2 appends two more**, both readers of one
#: :class:`~boardwise.core.highspeed.DiffPairReading` and neither of the other's
#: output: ``pcb-hs-diffpair-skew`` (one ``WARN`` per pair that is out of
#: tolerance in length or whose two sides use different layer sets) and
#: ``pcb-hs-diffpair-via-parity`` (one ``INFO`` per pair whose two sides use
#: different via counts). They come after 200C1 because they ask about a
#: **pair** as a unit, which is 182's object, and not about one track or one
#: via; the skew rule's threshold is a house rule
#: (``core.highspeed.DIFFPAIR_SKEW_MIL``), the parity row grades nothing.
BUILTIN_PCB_RULES: list[PcbRule] = [
    DecapDistance(),
    RegulatorCapDistance(),
    RegulatorFbPlacement(),
    McuCrystalPlacement(),
    McuCrystalKeepout(),
    McuSupplyGroups(),
    McuResetBoot(),
    FocDecapProximity(),
    FocGroundPlane(),
    FocGateTraceWidth(),
    FocTrackCorners(),
    FocPowerLoopArea(),
    FocGroundDomains(),
    FocGroundTie(),
    FocReturnPath(),
    FocThermalViaStyle(),
    FocThermalViaArray(),
    FocThermalExitPath(),
    FootprintConsistency(),
    PolarityOrientation(),
    SilkDesignator(),
    DeratingPackage(),
    ComponentSpacing(),
    BoardOffEdge(),
    TrackAmpacity(),
    VoltageSpacing(),
    KeepoutViolation(),
    DiffPairInventory(),  # 182, the high-speed family's inventory
    CrossSplit(),  # 200B, the family's first judgement
    GroundViaCompanion(),  # 200C1, the family's via-side question
    DiffPairSkew(),  # 200C2, the pair's own length / layer question
    DiffPairViaParity(),  # 200C2, the pair's own via-count question
]

#: The runner identity a report carries, so a reader can tell which engine
#: produced the section without importing anything.
RUNNER_ID = "boardwise.engines.pcbreview"


def build_module_of(
    model: Any = None,
    intent: Any = None,
    modules_section: list[dict] | None = None,
) -> dict[str, str]:
    """Designator → module name, from the two sources that exist (钉 2).

    **Priority: an engineer-declared ``intent.blocks[].parts`` wins over the
    report's own ``report.modules[]``.** The contract is a statement of function
    ("these parts are the current-sense front end"); ``modules[]`` is the
    tool's own reading (page split, or connectivity clustering) and is only a
    guess about structure. The ROBOT project has a contract, so its blocks
    override; a board with no contract (毕设FOC) falls back entirely to
    ``modules[]``.

    Both sources are read the same way and merged by designator: a designator
    that appears in a contract block takes that block's name; a designator that
    appears only in ``modules[]`` keeps the module name that reading gave it. A
    designator named by **two** blocks keeps the first in document order (the
    contract's own order is the engineer's) — the ambiguity is real but resolving
    it differently per caller would be worse.

    ``modules[]`` entries are ``{name, basis, components, ...}`` (see
    :func:`boardwise.engines.checkup.modules_section`); every basis is accepted
    (``page`` / ``connectivity`` / ``unattributed``) because the basis is *how* the
    tool grouped the parts, not *whether* it grouped them. A part in the
    ``未归属`` module is still attributed — to the catch-all — so a PCB finding
    about it lands somewhere rather than nowhere.

    **First-wins inside one source.** A designator that appears in two
    ``modules[]`` entries (a multi-board project's ``C1`` sits on each board, and
    each board's reading names it) keeps the **first** module that claims it.
    ``module_of`` is keyed by designator alone — that is 钉 1's shape, and it is
    the shape ``refs`` / ``target.component_ref`` are in — so on a multi-board
    project the last board read would otherwise silently overwrite the first,
    which is precisely the silent loss 040b spent a batch removing. PCB findings
    are stamped with the PCB document's title and are matched to modules by the
    report's own per-board pass, so first-wins here loses no attribution: it only
    decides which of two identically-named modules the *hint* points at.

    Pure: no I/O, no board, no globals. That is what makes it unit-testable and
    what keeps the CLI free to rebuild it on every run without cost.

    ``model`` is accepted and deliberately **not read**: the two sources that
    exist (钉 2) are the contract and the report's own ``modules[]``, and neither
    needs the netlist. It is in the signature because 126 钉 2 names the builder
    as ``build_module_of(model, intent, modules)`` — the model's designators are
    what the caller has already filtered ``modules[]`` by — so a future source
    that does need the netlist (a connectivity-based block, say) can be added
    without changing every call site.
    """
    mapping: dict[str, str] = {}
    # The contract, in its own document order, first block wins for a designator
    # named twice (U1 is in both senseU and senseW on the ROBOT contract).
    declared: dict[str, str] = {}
    for block in (getattr(intent, "blocks", None) or []) if intent is not None else []:
        name = str(getattr(block, "id", "") or "")
        if not name:
            continue
        for designator in getattr(block, "parts", None) or []:
            ref = str(designator or "").strip()
            if ref:
                declared.setdefault(ref, name)
    # Lower priority first, so the contract overwrites it (钉 2).
    for entry in modules_section or []:
        name = str(entry.get("name") or "")
        if not name:
            continue
        for designator in entry.get("components") or []:
            ref = str(designator or "").strip()
            if ref:
                mapping.setdefault(ref, name)
    # The contract wins where it speaks at all; everything else keeps whatever
    # the tool's own `modules[]` reading gave the designator.
    mapping.update(declared)
    return mapping


#: 189A2: 「多焊盘器件」 for the cross-view check — a symbol with more than two
#: pins. Two-pin passives are out of its scope on purpose: their pin-to-net
#: question is the one the schematic view has always answered, and a 2-pin part
#: whose poses disagree would show up as a missing wire endpoint instead.
CROSS_VIEW_MIN_PINS = 3


def schematic_board_for(model: Any, board_uuid: str) -> Any:
    """The schematic board a PCB document belongs to, or ``None`` (154's link).

    ``board_uuid`` is the PCB document's own ``META board`` (151), which
    ``BoardRef.uuid`` carries on the schematic side — the same link
    ``pcb_review.boards[].boardUuid`` exposes. Three readings, and the third is
    the honest one:

    * a **project** model (``ProjectModel``) is looked up by uuid;
    * a **single-board** model (a ``DesignModel``/``BoardModel``, or a KiCad
      project whose board has no uuid) is that board, and is returned when the
      caller has no uuid to match on — one model, one PCB document, nothing to
      guess;
    * anything else — a project whose link names no board (「板链读不出」), or a
      document whose uuid names a board the model does not hold — returns
      ``None``, and the caller says so rather than picking a board by position.
    """
    if model is None:
        return None
    if isinstance(model, ProjectModel):
        if board_uuid:
            for board in model.boards:
                if str(getattr(board.board, "uuid", "") or "") == board_uuid:
                    return board
            return None
        return model.boards[0] if len(model.boards) == 1 else None
    # A single board model (a BoardModel, a plain DesignModel, a KiCad read): the
    # board in hand is the only candidate, and it is used when it states no
    # identity of its own or states the document's own — never merely because it
    # is the only one.
    ref_uuid = str(getattr(getattr(model, "board", None), "uuid", "") or "")
    if board_uuid and ref_uuid and ref_uuid != board_uuid:
        return None
    return model


def _pin_sort_key(number: str) -> tuple[int, float, str]:
    """Sort pin numbers the way a person reads them: ``2`` before ``10``.

    The same reading ``parsers.epro2_model`` sorts a component's pins by. Here it
    is a *display* concern only — the rows are otherwise identical — but a note
    line that says ``U1.10、U1.11、U1.18、U1.19、U1.20、U1.8…`` looks like a
    defect and buries the pin it truncated.
    """
    try:
        return (0, float(int(number)), "")
    except (TypeError, ValueError):
        return (1, float("inf"), str(number))


def cross_view_lonely_pins(
    schematic: Any, pcb_model: Any, *, min_pins: int = CROSS_VIEW_MIN_PINS
) -> list[dict]:
    """Pins the schematic view leaves **alone** on a net the PCB view says has company.

    One archive, two views: the schematic document (``model``, what
    ``checkup --file`` reviews) and the PCB document's own netlist
    (``ctx.pcb_model``, 131c). They are the same design read twice, and 189A2 is
    why the difference is now reported instead of being left for the user to
    find by cross-checking by hand: on the real board of that task, four
    obsolete-bridge/TRIAC/connector symbols were read with **every connected pin
    on its own one-member net** (``NET13``…), the schematic view's ``nets[].pins``
    said "this pin reaches nothing", and the report grew phantom rails out of it.

    The check is deliberately the artifact's own shape and not "any difference":
    a pin the *schematic* view puts on a one-member net while the *PCB* view puts
    it on a net with more members. Net **names** are not comparably identified
    (this tool's auto names are ``NET7``, the editor's are ``$1N66612`` — pit 24
    in ``docs/pits.md``), so the comparison is by **membership**, pin by pin,
    joined on ``(designator, pin number)``.

    What it deliberately does **not** claim: which view is right. A pin alone in
    the schematic can be a parser error (189A2's shape) or a genuinely new
    unconnected pin whose PCB copy was never re-synced (017's stale-board
    warning, which runs the other way). The row carries both readings and the
    caller discloses them as a difference, not as a verdict.

    Two pins are deliberately **left out**, both because their absence is not this
    question:

    * a pin the schematic *component* does not carry at all — that is a parse
      drop, and the drops have their own counters (020);
    * a pin whose schematic net is listed in ``unproven_nets`` — 107's ruling is
      that such a net may not be concluded about in **either** direction, and
      "the schematic leaves this pin alone" is a conclusion. Its member list came
      out short because a dropped placement was not written into it, which is a
      knowledge gap the model already discloses (``unproven_reasons``), so the
      row would read as a finding where the file says 「不知道」.

    Both are **structural**, not a measurement that can drift: the loop below
    ``continue``s on either, so a returned row cannot name a pin the schematic
    component lacks and cannot point at an unproven net. What *is* a reading is
    how many rows there are — 34 across the five board entries of the four
    archives measured in `outputs/189a2c/evidence.md` — so the number lives
    there, with its provenance, and not in this docstring. (The 「23 rows across
    the 14 fixtures」 that used to be here was a **mismatched** reading: the probe
    paired `boards[0]` with `docs[0]` instead of following the 154 board link, so
    on two of the four archives it counted a different board's rows — 8 where the
    link says 10, 2 where it says 10.)

    Rows are sorted by ``(designator, pin number)`` and are
    ``{designator, pin, schematicNet, schematicMembers, pcbNet, pcbMembers}``.
    An empty list is a real reading («the two views agree on these pins»); a
    caller that could not pair a schematic board with the document must not call
    this at all, so "not checked" never reads as "agreed".

    ``min_pins`` is the 「多焊盘器件」 floor (:data:`CROSS_VIEW_MIN_PINS`): the
    task's minimum scope. It is a parameter so a caller can widen it to every
    component, which on the repo's own fixtures is a much noisier question —
    those boards carry long-standing schematic-vs-PCB differences (a PCB that was
    never re-synced, a designator whose pins were renumbered) that this check is
    not the instrument for.
    """
    if schematic is None or pcb_model is None:
        return []
    pcb_members: dict[tuple[str, str], tuple[str, int]] = {}
    for name, net in pcb_model.nets.items():
        for designator, number in net.pins:
            pcb_members.setdefault((designator, number), (name, len(net.pins)))
    schematic_members: dict[tuple[str, str], tuple[str, int]] = {}
    for name, net in schematic.nets.items():
        for designator, number in net.pins:
            schematic_members.setdefault((designator, number), (name, len(net.pins)))
    unproven = set(getattr(schematic, "unproven_nets", None) or ())
    rows: list[dict] = []
    for (designator, number), (pcb_net, pcb_count) in sorted(
        pcb_members.items(), key=lambda item: (item[0][0], _pin_sort_key(item[0][1]))
    ):
        if pcb_count < 2:
            continue  # the board agrees this pin is alone: nothing to compare
        component = schematic.components.get(designator)
        if component is None or len(component.pins) < min_pins:
            continue
        if not any(pin.number == number for pin in component.pins):
            continue
        got = schematic_members.get((designator, number))
        schematic_count = got[1] if got else 0
        if schematic_count > 1:
            continue  # the schematic gives it company too: the views agree
        if got is not None and got[0] in unproven:
            # 107: a net whose member list came out short may not be concluded
            # about in either direction — and 「the schematic leaves this pin
            # alone」 is exactly such a conclusion. The gap is disclosed by
            # `unproven_reasons`; it may not be restated here as a difference.
            continue
        rows.append({
            "designator": designator,
            "pin": number,
            "schematicNet": got[0] if got else None,
            "schematicMembers": schematic_count,
            "pcbNet": pcb_net,
            "pcbMembers": pcb_count,
        })
    return rows


#: 537C1：``crossView.candidateMappings[].evidence`` 的三段出处。
#:
#: 两侧都是**归档**读数——``checkup --file`` 读的就是这两份归档导出，谁都不是
#: live 证据，所以证据里不写 "live" 也不写哪个「对」。``basis`` 说明候选是按
#: **同名网**取的：PCB 行的 ``pcbNet`` 与原理图 ``nets`` 的键名逐字相等时，成员才
#: 是候选；名字不同（这个工具的自动名 ``NET7`` 对编辑器的 ``$1N66612``，pits.md
#: 坑 24）就无从比对，宁可给空。
CROSS_VIEW_MAPPING_EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "archiveSchematic",
    "basis": "same-net-name",
}


def _net_member_refs(net: Any) -> list[str]:
    """``REF.pin`` for every member of ``net``, deduplicated, read like a person reads.

    ``Net.pins`` holds ``(designator, pin number)`` tuples and can carry the same
    member twice (two wires of one net record) — the mapping states the net's
    **real member list**, so a repeat would read as two parts on one pin and is
    written once. Order is ``(designator, pin number)`` through
    :func:`_pin_sort_key`, the same reading the lonely rows use, so ``U9.2``
    precedes ``U9.10``.
    """
    seen: set[tuple[str, str]] = set()
    members: list[tuple[str, str]] = []
    for designator, number in (getattr(net, "pins", None) or ()):
        key = (str(designator), str(number))
        if key in seen:
            continue
        seen.add(key)
        members.append(key)
    members.sort(key=lambda item: (item[0], _pin_sort_key(item[1])))
    return [f"{designator}.{number}" for designator, number in members]


def _cross_view_candidate_mappings(
    schematic: Any, pcb_model: Any, lonely: list[dict]
) -> list[dict]:
    """One suspected mapping per lonely row, from the **same-named** schematic net.

    189A2's rows say «the schematic leaves this pin alone, the PCB gives it
    company» and then stop: the reader is left to open both archives and work out
    by hand which schematic pins the PCB net might correspond to. That hand work
    is where a candidate gets mis-typed — or where a same net **name** gets read
    as «confirmed». This function does the mechanical half only:

    ``pcbPin`` is ``designator.pin`` of the lonely row; ``pcbMembers`` is the
    PCB net's **real** whole member list (the row itself carried a count); and
    ``schematicCandidates`` is the whole member list of the schematic net whose
    **key equals** ``pcbNet``, or ``[]`` when there is no net by that name. A
    candidate is never inferred from the PCB members or from what the circuit
    probably is, and a member of the *same designator on another pin* (``U9.3``
    beside ``U9.1``) is **kept**: 「this is a renumbering」 is one of the two
    readings the difference allows, and dropping it would be picking a side.

    What this deliberately does **not** do: decide which view is right. Both
    sides are **archive** readings (``checkup --file`` reviews the exported
    schematic and PCB documents; neither is live evidence), so the mapping is a
    machine-assembled candidate list for a person to check, and the section says
    ``status: suspected`` for exactly that reason. It is not a confirmation, and
    no ``confirmed`` verdict is written anywhere by this module.

    An exception out of here is **not** swallowed into a partial mapping list:
    the caller runs this inside the same ``try`` as the comparison, so a broken
    read comes back as the existing ``checked: false`` disclosure instead of a
    ``checked: true`` section that quietly lost its mappings.
    """
    pcb_nets = getattr(pcb_model, "nets", None) or {}
    schematic_nets = getattr(schematic, "nets", None) or {}
    mappings: list[dict] = []
    for row in lonely:
        name = row["pcbNet"]
        pcb_net = pcb_nets.get(name)
        candidate_net = schematic_nets.get(name)
        mappings.append({
            "pcbPin": f"{row['designator']}.{row['pin']}",
            "pcbNet": name,
            "pcbMembers": _net_member_refs(pcb_net),
            "schematicCandidates": _net_member_refs(candidate_net),
            "evidence": dict(CROSS_VIEW_MAPPING_EVIDENCE),
        })
    return mappings


#: 自动网候选别名的 ``evidence``（C，2026-10-30）：三段出处 + 一句候选说明。
#:
#: 两侧仍是**归档**读数（``checkup --file`` 读的导出文档），所以 ``pcb`` /
#: ``schematic`` 与 537C 的映射写同一对出处；``basis`` 换成
#: ``same-pin-members``——这条别名认的是**同一脚集合**，不是同名，也不是编辑器
#: 的内部派生算法（``$1N{序号}`` 的编号稀疏且会变，原理图归档里没有派生规则）。
#: ``note`` 把「候选」写在证据里而不只是 ``status``，因为读者可能只抄这一段。
CROSS_VIEW_ALIAS_EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "archiveSchematic",
    "basis": "same-pin-members",
    "note": "候选别名：同一脚集合，不是确认同一网",
}


def _auto_net_buckets(model: Any) -> dict[tuple[str, ...], list[str]]:
    """``member-set -> [net names]`` for the **auto-named** nets of one view.

    A net belongs here only when :func:`~boardwise.core.netdomains.is_auto_net`
    recognises its name (``NET`` 加数字 / ``$…``): a net a person named carries
    intent, and two different names for it are not this question. Members are
    :func:`_net_member_refs`'s deduplicated, pin-sorted ``REF.pin`` list, so the
    bucket key is the net's **real** member set — an empty one is dropped, since
    two nets that both reach nothing say nothing about each other.

    Several nets can land in one bucket (a net recorded twice, or two islands the
    views joined differently); the caller reads the list length as 「这个桶不唯一」
    and withholds the alias rather than picking one.
    """
    buckets: dict[tuple[str, ...], list[str]] = {}
    for name, net in (getattr(model, "nets", None) or {}).items():
        if not is_auto_net(name):
            continue
        members = tuple(_net_member_refs(net))
        if not members:
            continue
        buckets.setdefault(members, []).append(str(name))
    return buckets


def _cross_view_auto_net_aliases(schematic: Any, pcb_model: Any) -> list[dict]:
    """Auto-named nets that hold **exactly the same pins** in both views (C).

    The user-reported shape: the design's own model calls a net ``NET34`` while
    the PCB/editor netlist calls the very same net ``$1N436``. Both names are
    editor-generated — neither says what the net *is* — so an alias is only read
    when the **pin sets** are fully equal, and it is recorded as a candidate:

    ``{schematicNet, pcbNet, members, status: "candidate", evidence}`` with
    ``members`` the shared, deduplicated ``REF.pin`` list, ``status`` the word
    that keeps this from being read as confirmation, and ``evidence`` naming the
    basis (``same-pin-members``) and both **archive** sides.

    What it deliberately does **not** do:

    * no derived naming — ``$1N436`` is an internal id whose numbering is sparse
      and moves between captures, and the archive schematic holds no rule from
      which it could be computed; nothing here invents a ``$1N{index}``. The
      one real ``NET34 ↔ $1N436`` pair in the user's report is their oracle, and
      the tests reproduce it synthetically rather than claiming it as measured;
    * no name-only match: equal names are 537C's ``same-net-name`` candidate,
      and this function only emits pairs whose names **differ**;
    * no subset, no superset, no 「probably the same rail」: equality is on the
      whole set, so one shared pin out of five is not an alias;
    * no ambiguous bucket: if **either** side has two auto nets with the same
      member set, the whole bucket is withheld — picking one would be a guess
      dressed as a reading;
    * no rewrite of rules, findings or ``Net.name``: the alias is a disclosure
      under ``crossView``, and every rule message keeps the name it read.
    """
    schematic_buckets = _auto_net_buckets(schematic)
    pcb_buckets = _auto_net_buckets(pcb_model)
    aliases: list[dict] = []
    for members, schematic_names in schematic_buckets.items():
        pcb_names = pcb_buckets.get(members)
        if not pcb_names:
            continue
        if len(schematic_names) != 1 or len(pcb_names) != 1:
            continue  # 重复/歧义桶：整桶不出别名
        schematic_name = schematic_names[0]
        pcb_name = pcb_names[0]
        if schematic_name == pcb_name:
            continue
        aliases.append({
            "schematicNet": schematic_name,
            "pcbNet": pcb_name,
            "members": list(members),
            "status": "candidate",
            "evidence": dict(CROSS_VIEW_ALIAS_EVIDENCE),
        })
    aliases.sort(key=lambda alias: (alias["schematicNet"], alias["pcbNet"]))
    return aliases


def _pcb_documents(source: Any) -> list[tuple[str, str, Any]]:
    """``(META title, META board, document)`` for every PCB document, in file order.

    The title is read from the document's own ``META`` record (钉 4). A document
    whose META carries no title falls back to its uuid so it is still
    addressable and still distinguishable — but the two real fixtures all name
    themselves ("PCB1"/"PCB2"/"PCB3"), which is what the test pins.

    ``board`` is the same META's declared link to the schematic board (151): it
    is the uuid of a ``BOARD`` document, which is exactly what
    :class:`~boardwise.core.model.BoardRef` carries. Measured on the three
    acceptance boards: 毕设FOC 1.0.0's PCB1 → ``d5c055266ef55000`` (Board1) and
    PCB2 → ``5455a645b144c024`` (Board2); 1.1.0's PCB3 → ``7dca2922104db3df``
    (Board3); ROBOT's PCB1 → ``258938d3e4719586`` (Board1) — six documents, six
    hits, no fallback needed. Empty string when the document states none, which
    a rule reads as 「板链读不出」 rather than as board 0.
    """
    titled: list[tuple[str, str, Any]] = []
    for document in source.documents_of_type("PCB"):
        title = ""
        parent_board = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                title = str(record.body.get("title") or "")
                parent_board = str(record.body.get("board") or "")
                if title:
                    break
        if not title:
            title = str(document.uuid or "")
        titled.append((title, parent_board, document))
    return titled


def _outline_aspect_ratio(outline: Any) -> float | None:
    """The bbox's long side over its short one (188a), or ``None`` when it has none.

    :attr:`BoardOutline.bbox` is the geometry layer's own reading of the ring, so
    this does not measure it a second time: the question the report asks is "how
    slender is the ring in hand", and the ring in hand is ``points``.
    """
    bbox = getattr(outline, "bbox", None)
    if bbox is None:
        return None
    short = min(bbox.width, bbox.height)
    if short <= 0:
        return None
    return max(bbox.width, bbox.height) / short


#: 板框细长比（bbox 长边/短边）的披露阈值（188a）。**只披露不拒收**：窄板、
#: 细条灯板、长条形拼板都真实存在，这个数不是判定语义，报告说的是「请人工确认
#: 拼合正确」而不是「这不是板框」。
#:
#: 定在 20 的实板对照：仓库里的真板 1:1–4:1（毕设FOC 主机板、CH340G 小板都是
#: 矩形），细条灯板/拼条的 bbox 可达 10–20:1，而 187A 遗留的那个「2000 mil 板框
#: 回程错开 0.9 mil」的退化环是 2000/0.9 = **2222:1**——阈值落在 20 把退化形态
#: 框进来，又不碰真细长板。
OUTLINE_SLENDER_ASPECT_RATIO = 20.0

#: 191C：`netIdNote` 里最多列出几个丢了名字的网序号。披露的是**计数**，列名只是
#: 让人能去文件里找——一块序号全丢的板可以有几百个 `net#N`，全列出来会把这条
#: 披露本身淹掉，所以超出就截断（`…`）。
NET_ID_NOTE_LIMIT = 8


def cross_view_section(
    schematic_board: Any, pcb_model: Any
) -> dict:
    """The ``crossView`` disclosure of one board entry (189A2).

    ``{checked: true, minPins, lonely: [...]}`` when the two views could be
    compared — ``lonely`` empty is the reading «they agree on these pins» — and
    ``{checked: false, reason}`` when they could not, in the same shape the
    three DRC sections use for 「没查」. Both keys are always present on a board
    entry, because 「没配对」 and 「对上了」 are two different statements and a
    missing key cannot tell them apart (钉 5).

    **537C adds two keys, and only when there is something to suspect.** With a
    non-empty ``lonely`` the section also carries ``status: "suspected"`` and one
    ``candidateMappings`` entry per row, in the rows' own order, assembled by
    :func:`_cross_view_candidate_mappings` from the **same-named** schematic net.
    With an empty ``lonely`` the dict is ``{checked, minPins, lonely}`` exactly as
    before: 「the views agree on these pins」 may not acquire a status, and
    nothing here writes ``confirmed`` — a net **name** shared by the two archives
    is a candidate, never a confirmation. The same holds for every
    ``checked: false`` path: no partial ``status`` and no empty
    ``candidateMappings``, because a section that says 「没查」 may not also look
    half-checked.

    **C (2026-10-30) adds a third optional key, ``autoNetAliases``.** When both
    views hold auto-named nets (``is_auto_net``: ``NET`` 加数字 / ``$…``) with
    **exactly the same, non-empty pin set** and **different** names, the section
    carries one candidate per such pair, assembled by
    :func:`_cross_view_auto_net_aliases` — that is the ``NET34 ↔ $1N436`` shape
    the user reported. The key is additive and appears only under
    ``checked: true`` **and** only when at least one alias exists: no empty
    array, and the ``checked: false`` shapes are untouched. It is a
    cross-view **candidate alias**, not the editor's internal derivation, not a
    confirmation that the two nets are one, and it rewrites no rule message —
    ``Net.name`` and the findings keep the names they were read with.

    Both sides of a mapping are **archive** readings (``checkup --file`` reviews
    the exported schematic and PCB documents; neither is live evidence), so the
    mapping is a machine-assembled candidate list for a person to check — it does
    **not** judge which view is right, and 189A2's two possible readings (a
    parser/pose artifact versus a genuinely unconnected pin whose board copy was
    never re-synced) both stay open.

    An exception out of the comparison — or out of the candidate read, which runs
    inside the same ``try`` — is **the third** ``checked: false``, and it is
    caught here on purpose: this reading is extra evidence beside the rules, so a
    model it chokes on may not take the whole ``pcb_review`` section down with it
    (the runner's own contract is that one broken check never kills the report —
    169 did the same for a raising rule, whose id is *named* in ``rules_errored``).
    The reason names the exception, so 「检查崩了」 is a reading the report carries
    rather than a silence a reader would take for agreement. Running the mapping
    pass inside this ``try`` is also what guarantees the shape 537C forbids never
    appears: a ``checked: true`` section whose ``lonely`` has rows but whose
    ``candidateMappings`` is missing.
    """
    if schematic_board is None:
        return {
            "checked": False,
            "reason": "该 PCB 档未能与原理图板配对（板链读不出），"
                      "跨视图网表一致性未查（没查，不是一致）",
        }
    if pcb_model is None:
        return {
            "checked": False,
            "reason": "该档没有自己的网表读数（pcb_model 缺席），"
                      "跨视图网表一致性未查（没查，不是一致）",
        }
    try:
        lonely = cross_view_lonely_pins(schematic_board, pcb_model)
        mappings = (
            _cross_view_candidate_mappings(schematic_board, pcb_model, lonely)
            if lonely
            else None
        )
        aliases = _cross_view_auto_net_aliases(schematic_board, pcb_model)
    except Exception as exc:  # noqa: BLE001 — named below, never silently dropped
        return {
            "checked": False,
            "reason": f"跨视图网表一致性检查未完成（{type(exc).__name__}: {exc}）"
                      "—— 没查，不是一致",
        }
    section = {
        "checked": True,
        "minPins": CROSS_VIEW_MIN_PINS,
        "lonely": lonely,
    }
    if mappings is not None:
        section["status"] = "suspected"
        section["candidateMappings"] = mappings
    if aliases:
        section["autoNetAliases"] = aliases
    return section


#: 537C3b3：实时候选的三种状态。词汇与 537C 的覆盖账同一套（``ok / missing /
#: unavailable``），但这里是**一条映射的实时半边**，不是通道覆盖：``missing`` 是
#: 「实时网表里没有这个同名网」，``unavailable`` 是「有网，但名字在这份实时网表里
#: 不能唯一定位」。
LIVE_CANDIDATE_OK = "ok"
LIVE_CANDIDATE_MISSING = "missing"
LIVE_CANDIDATE_UNAVAILABLE = "unavailable"

#: 本棒往每条 mapping 上追加的两个键，顺序固定在归档 ``evidence`` 之后。
LIVE_CANDIDATE_KEYS = ("liveSchematicCandidates", "liveCandidateEvidence")

#: 实时侧 evidence 的固定四段，与归档侧逐字分开：``schematic`` 只有在这里才是
#: ``liveSchematic``——归档 mapping 自己那份永远写 ``archiveSchematic``。
LIVE_CANDIDATE_EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "liveSchematic",
    "basis": "same-net-name",
}


def _live_netlist_binding(netlist_artifact: Any) -> dict:
    """A deep copy of the netlist artifact that **binds** the live candidates.

    A live candidate list without a provenance binding is worse than none: the
    reader cannot say which netlist produced it. ``file`` and ``sha256`` are
    therefore mandatory and non-empty (``netlistType`` may ride along), and the
    caller gets a ``ValueError`` instead of a candidate with no origin.
    """
    if not isinstance(netlist_artifact, dict):
        raise ValueError(
            "live 候选需要 netlist artifact（含非空 file/sha256），"
            f"拿到的是 {type(netlist_artifact).__name__}——不生成无出处候选"
        )
    for key in ("file", "sha256"):
        value = netlist_artifact.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"live 候选的 netlist artifact 缺非空 {key}——不生成无出处候选"
            )
    return copy.deepcopy(netlist_artifact)


def _live_repeated_designators(live_model: Any) -> set[str]:
    """Names this live model cannot resolve to one placement (consumer view).

    ``DesignModel.repeated_designators()`` is the consumer-facing reading (040
    §WI-3): a repeated designator is ambiguous even where it is not a defect.
    The method is preferred; the bare lists are the fallback for a model-shaped
    stand-in.
    """
    repeated = getattr(live_model, "repeated_designators", None)
    if callable(repeated):
        return {str(name) for name in repeated()}
    names = getattr(live_model, "duplicate_designators", None) or ()
    return {str(name) for name in names}


def _live_evidence(netlist: dict, status: str, **extra: Any) -> dict:
    evidence: dict = {"status": status}
    evidence.update(LIVE_CANDIDATE_EVIDENCE)
    evidence["netlist"] = netlist
    evidence.update(extra)
    return evidence


def _live_candidates_for_net(
    live_model: Any,
    net_name: str,
    *,
    repeated: set[str],
    nets: dict,
    netlist_artifact: dict,
) -> tuple[list[dict], dict]:
    """``([{pin, pinName}, …], evidence)`` for one mapping's live same-named net.

    The members are the **live** net's own ``(designator, pin number)`` list —
    never the archive ``schematicCandidates`` and never the archive ``pcbMembers``.
    A member's ``pinName`` is read from the live component's pin with that exact
    number; an empty name stays ``""`` (no guessing). The pin **number** on the
    live net is authoritative precisely because the original session measured
    that it can differ from the archive's (``U9.11`` archive vs ``U9.33`` live).

    Three refusals, all stated rather than papered over:

    * no net by that name, or a net with no members → ``missing``;
    * the live model repeats a designator on this net → ``unavailable`` with
      ``ambiguousDesignators``; the net is not resolved by picking one placement;
    * a member cannot be resolved to a component/pin of the live model →
      ``unavailable`` with ``unresolvedPins``.

    The last two deliberately return **no** candidates at all: a partially
    certain list would read as "these are the live members" while some of them
    were silently dropped.
    """
    net = nets.get(net_name)
    if net is None:
        return [], _live_evidence(
            copy.deepcopy(netlist_artifact),
            LIVE_CANDIDATE_MISSING,
            reason=(
                f"实时网表里没有名为 {net_name} 的网——不拿归档候选或 PCB 成员补"
            ),
        )
    members = getattr(net, "pins", None)
    if members is None:
        members = ()
    if not isinstance(members, (list, tuple)):
        raise ValueError(f"实时网 {net_name} 的 pins 不是成员列表，读不出候选")
    if not members:
        return [], _live_evidence(
            copy.deepcopy(netlist_artifact),
            LIVE_CANDIDATE_MISSING,
            reason=f"实时网 {net_name} 没有成员——不拿归档候选或 PCB 成员补",
        )

    components = getattr(live_model, "components", None)
    if not isinstance(components, dict):
        components = {}

    ambiguous: set[str] = set()
    unresolved: set[tuple[str, str]] = set()
    candidates: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for designator, number in members:
        designator, number = str(designator), str(number)
        if (designator, number) in seen:
            continue
        seen.add((designator, number))
        if designator in repeated:
            # Ambiguity is a property of the name being on this net, not of the
            # pin resolving: a repeated designator may not be resolved by
            # picking one placement, whether or not this pin reads.
            ambiguous.add(designator)
        component = components.get(designator)
        if component is None:
            unresolved.add((designator, number))
            continue
        pin = next(
            (
                pin
                for pin in (getattr(component, "pins", None) or ())
                if str(getattr(pin, "number", "")) == number
            ),
            None,
        )
        if pin is None:
            unresolved.add((designator, number))
            continue
        candidates.append((designator, number, str(getattr(pin, "name", "") or "")))

    netlist = copy.deepcopy(netlist_artifact)
    if ambiguous or unresolved:
        extra: dict[str, Any] = {}
        if ambiguous:
            extra["ambiguousDesignators"] = sorted(ambiguous)
        if unresolved:
            extra["unresolvedPins"] = [
                f"{designator}.{number}"
                for designator, number in sorted(
                    unresolved, key=lambda item: (item[0], _pin_sort_key(item[1]))
                )
            ]
        return [], _live_evidence(
            netlist,
            LIVE_CANDIDATE_UNAVAILABLE,
            reason=(
                f"实时网 {net_name} 含重复位号或无法精确解析的成员，"
                "不能给出唯一候选（不给部分确定的列表）"
            ),
            **extra,
        )

    candidates.sort(key=lambda item: (item[0], _pin_sort_key(item[1])))
    return (
        [{"pin": f"{designator}.{number}", "pinName": name}
         for designator, number, name in candidates],
        _live_evidence(netlist, LIVE_CANDIDATE_OK),
    )


def enrich_cross_view_live_candidates(
    cross_view: dict,
    live_model: Any,
    *,
    netlist_artifact: dict,
    identity_verified: bool,
) -> dict:
    """Add the **live** half of every crossView candidate mapping (537C3b3).

    ``cross_view`` is :func:`cross_view_section`'s dict (or one read out of a
    saved report). Each existing ``candidateMappings[]`` entry keeps every
    archive field it had — ``pcbPin`` / ``pcbNet`` / ``pcbMembers`` /
    ``schematicCandidates`` / ``evidence`` are **not** rewritten — and gains, in
    this order after the archive ``evidence``:

    * ``liveSchematicCandidates``: ``[{"pin": "U9.33", "pinName": "PB11"}, …]``,
      the real members of the live net whose name equals ``pcbNet``, deduplicated
      and sorted through :func:`_net_member_refs`' reading (designator, then
      pin number numerically). ``pinName`` comes from that live component's pin
      with the exact same number; an empty name stays ``""``;
    * ``liveCandidateEvidence``: ``{status, pcb: "archivePcb", schematic:
      "liveSchematic", basis: "same-net-name", netlist: <deep copy>}`` plus, when
      status is not ``ok``, a concrete ``reason`` (and ``ambiguousDesignators`` /
      ``unresolvedPins`` for ``unavailable``).

    **Why the live net's members and not the archive refs:** the original
    session measured that an archive ``pcbPin`` (``U9.11``) can be a *different*
    pin number from the live same-named net's member (``U9.33``). Naming the old
    archive refs from the live netlist would attach the wrong pin name to a
    physical pin; the live candidate list is therefore rebuilt from the live
    net, and the archive list is left standing beside it as the other reading.

    Purity and idempotence: the input dict is deep-copied and never mutated; the
    netlist artifact is deep-copied per mapping and never aliased. Old
    ``liveSchematicCandidates`` / ``liveCandidateEvidence`` are removed from
    **every** mapping first, so a second call replaces the previous live half
    and a verified→unverified call strips it entirely.

    What this deliberately does **not** do:

    * it never writes ``status: confirmed`` and never changes the section's own
      ``status`` — a live netlist that agrees on membership proves the live
      reading, not which archive view was wrong, so ``suspected`` stays;
    * with ``identity_verified=False`` it stops right after stripping: the live
      candidates may belong to another project, so the archive section is
      returned as it is and no model is consulted (a caller needs no model on
      this path);
    * with an empty ``lonely``, a missing ``candidateMappings`` or an unchecked
      (``checked: false``) section it does not call a model at all: there is no
      mapping to enrich, and 「没查」 may not acquire a live reading.

    A live candidate list without provenance is refused: ``netlist_artifact``
    must carry a non-empty ``file`` and ``sha256`` (a ``netlistType`` may ride
    along), otherwise ``ValueError``. A ``live_model`` that must be read but
    cannot be (``None``, no readable ``nets``) is also a ``ValueError`` — this
    function does not guess what a broken model meant.
    """
    if not isinstance(cross_view, dict):
        raise ValueError(
            f"crossView 必须是 dict，拿到的是 {type(cross_view).__name__}"
        )
    enriched = copy.deepcopy(cross_view)

    mappings = enriched.get("candidateMappings")
    if mappings is None:
        return enriched
    if not isinstance(mappings, list):
        raise ValueError("crossView.candidateMappings 不是列表，无法补实时候选")

    stripped: list[dict] = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("crossView.candidateMappings 里有非 mapping 条目")
        stripped.append(
            {key: value for key, value in mapping.items() if key not in LIVE_CANDIDATE_KEYS}
        )
    enriched["candidateMappings"] = stripped

    if enriched.get("checked") is not True:
        # 「没查」/「没配对」 may never look half-checked: no mapping is enriched,
        # even if a malformed report carried one.
        return enriched
    if not identity_verified:
        return enriched
    if not stripped:
        return enriched

    nets = getattr(live_model, "nets", None)
    if not isinstance(nets, dict):
        raise ValueError(
            "补实时候选需要可读的 live_model.nets（身份已核实时仍缺，不猜）"
        )
    netlist_artifact = _live_netlist_binding(netlist_artifact)
    repeated = _live_repeated_designators(live_model)

    for mapping in stripped:
        net_name = mapping.get("pcbNet")
        if not isinstance(net_name, str) or not net_name:
            raise ValueError("candidateMapping 没有可核对的 pcbNet，无法取实时同名网")
        candidates, evidence = _live_candidates_for_net(
            live_model,
            net_name,
            repeated=repeated,
            nets=nets,
            netlist_artifact=netlist_artifact,
        )
        mapping["liveSchematicCandidates"] = candidates
        mapping["liveCandidateEvidence"] = evidence
    return enriched


def _board_entry(
    *,
    title: str,
    board: Any,
    board_uuid: str,
    checks_run: list[str],
    finding_indexes: list[int],
    cross_view: dict | None = None,
) -> dict:
    """One entry of ``pcb_review.boards[]``.

    ``copperLayers`` is the read of the physical stackup (125's
    :func:`boardwise.core.measure.read_stackup`) — the number of copper layers,
    which for the 毕设FOC main board is 4, read from ``LAYER_PHYS`` and not from
    the 34 ``LAYER`` definitions the editor carries.

    ``boardUuid`` is the document's own META link to a schematic ``BOARD``
    document (151's ``board_uuid``), carried into the section by 154 so the
    integrated report can put a ``PCB1`` finding under the same heading as the
    schematic ``Board1`` findings — the two name spaces are otherwise unrelated
    (a PCB document is titled by its **META title**, a schematic board by its
    ``BoardRef`` title). Empty string when the document states none, which the
    reader treats as 「板链读不出」 rather than as a board. Additive: no existing
    key moves.

    ``outlineNote`` (bug98 on) is the disclosure channel of the PCB block, and
    188a adds one **INFO** line to it: a ring whose bbox is longer than
    :data:`OUTLINE_SLENDER_ASPECT_RATIO` to its short side gets 「板框极细长…请人工
    确认拼合正确」. It is a disclosure and never a refusal — narrow boards are
    real. What it is *for*: the shapes 187A's H1 left standing are rings that do
    close and do carry area but are a line's width thick (its leftover ①: the
    0.9 mil mis-join of a 2000 mil frame, 2222:1), where the frame the off-board
    rule measures against is inside a stitching error rather than around the
    board. The threshold is placed where the repo's own boards can check it: a
    real board is ~1:1–4:1, a strip light board or a panel can reach 10–20:1, so
    20 puts the degenerate shapes in scope without touching a real narrow board.

    ``crossView`` (189A2) is the one **always-present** addition: the same
    archive read through both views, disclosing the pins the schematic view
    leaves alone on a net the PCB view says has company. See
    :func:`cross_view_section` for the two shapes it carries and why a missing
    key would have been the wrong way to say 「没配对」.

    ``netIdNote`` (191C, extended by 192A-3/4) is the KiCad board's **net-table
    disclosure**, and it is present only when there is something to disclose —
    absent, not empty, when the file was clean. Two facts ride on it, joined by
    「；」:

    * a **lost name** — a pad, track, via or zone stating a bare ``(net N)``
      whose id no ``(net N "NAME")`` row of the file's own table explains. The
      reader keeps those as ``net#N`` and never invents a name; the count comes
      from :func:`boardwise.parsers.kicad.unnamed_net_names` — **the reader's own
      yardstick, called and never re-implemented here** (192A-3: a second prefix
      filter is a second answer waiting to drift) — because the checks that find
      a net **by name** (the differential-pair inventory, the per-rail decap
      bands) cannot see such a net at all;
    * a **contradicted id** (192A-4) — the file's own table gave one id more than
      one name (``board.net_table_conflicts``). The reader keeps the **first**
      name; the note names every name that id was given, because the ignored one
      is not cosmetic: the bare-``(net N)`` copper now sits on the first name,
      and a reader who is not told would take the two nets for one.
    """
    info = read_stackup(board)
    entry = {
        "title": title,
        "boardUuid": board_uuid,
        "components": len(board.components),
        "copperLayers": info.copper_count,
        "checksRun": list(checks_run),
        # Indices into the finding array **this runner** returns. A caller that
        # merges these into the report's own `findings[]` (cli._cmd_checkup does)
        # shifts them by however many findings came first; `checkup`'s PCB block
        # carries that comment where the shift happens.
        "findings": list(finding_indexes),
    }
    if cross_view is not None:
        entry["crossView"] = dict(cross_view)
    # bug98（岳转的现场报告）：板框读不出来时「出板框」检查是**没跑**，不是
    # 「全过」——这件事必须长在报告上。圆角矩形拆成 16 段 BOARD_OUTLINE 而
    # 拼合失败的板，曾经在报告里淹出 98 条假 ERROR（只认了第一段弧）。
    # 审计 325 又钉了两档：单段**开放**折线（closed=False）同样不许量；
    # 成了环但有碎段/多余闭环没入环（outline_fragments>0）检查照跑、碎段披露。
    # bug98-B 钉第三档：多段只认一环、且那一环读出来是**描边**（fragment_kind =
    # "stroke_piece"）才是碎片、不是板：检查已抑制、改出 1 条 WARN——这句与
    # 「照跑」那句互斥。187A（M2）把这一档收窄到「描边碎片」：同一档里「完整板框 +
    # 多余闭合记录（内槽/拼板）」拿到的是**整板**，照 bug98-A 的照跑走，
    # 碎段照旧披露（不抑制）。
    # 有好板框且无碎段的板不带此键（逐字节不变）。
    outline = getattr(board, "outline", None)
    fragments = int(getattr(board, "outline_fragments", 0) or 0)
    outline_notes: list[str] = []
    if outline is None:
        if fragments > 1:
            outline_notes.append(
                f"板框由 {fragments} 段 BOARD_OUTLINE 组成且未能拼合成闭环"
            )
        else:
            outline_notes.append("未读出有效板框（无 BOARD_OUTLINE 记录）")
        outline_notes.append("「出板框」检查未运行（没跑，不是全过）")
    else:
        if not outline.closed:
            outline_notes.append(
                "板框未闭环（单段开放折线或退化轮廓）——「出板框」检查未运行"
                "（没跑，不是全过）"
            )
        elif len(outline.points) < MIN_OUTLINE_CORNERS:
            outline_notes.append(
                f"板框退化（{len(outline.points)} 个角点 < "
                f"{MIN_OUTLINE_CORNERS:g}，疑似没画完的框）——「出板框」检查未运行"
                "（没跑，不是全过）"
            )
        kind = getattr(outline, "fragment_kind", None)
        if getattr(outline, "stitched", None) is False and kind == FRAGMENT_KIND_STROKE_PIECE:
            # bug98-B 护栏：多段只认一环、那一环读出来是描边 = 拿到的是**碎片**，
            # 出板框检查已抑制。这句必须与「照跑」那句互斥——同一份报告不能既说
            # 照跑又说抑制。
            outline_notes.append(
                f"板框 {outline.segments} 段只认了其中一环、另有 {fragments} 段未入环"
                "——多段拼合失败（那一环读出来是描边，拿到的是碎片），"
                "「出板框」检查已抑制并改出 1 条 WARN（没跑，不是全过）"
            )
        elif fragments and kind == FRAGMENT_KIND_EXTRA_RECORDS:
            # 187A M2：赢家是**画出来的整环**（不是描边），旁边的记录是多余闭环
            # （内槽/拼板）——照 bug98-A 照跑，碎段只披露。
            outline_notes.append(
                f"板框 {outline.segments} 段：多余记录未入环（{fragments} 段，"
                "完整板框旁的多余闭环，如内槽/拼板），「出板框」检查按所选闭环照跑"
            )
        elif fragments:
            outline_notes.append(
                f"另有 {fragments} 段板框记录未入环（多余闭环或碎段），"
                "「出板框」检查按所成闭环照跑"
            )
        welds = int(getattr(outline, "tolerance_welds", 0) or 0)
        if welds:
            outline_notes.append(
                f"板框含 {welds} 处容差焊缝（端点非逐字相等）——"
                "容差内的缝隙（面板缝、描边错位）可能被误焊，人工核"
            )
        note = str(getattr(outline, "note", "") or "")
        if note:
            outline_notes.append(note)
        # 188a：极细长环只披露、不拒收。位置在最后——前面几句说的是「这一次读数
        # 怎么来的」，这一句是对同一个环的**形状**再加一条人工核项。
        ratio = _outline_aspect_ratio(outline)
        if ratio is not None and ratio > OUTLINE_SLENDER_ASPECT_RATIO:
            outline_notes.append(
                f"板框极细长（{ratio:.0f}:1）——细长板/拼板请人工确认拼合正确"
            )
    if outline_notes:
        entry["outlineNote"] = "；".join(outline_notes)
    # 191C：KiCad 的焊盘/走线可以只写裸 `(net N)`——名字在文件自己的
    # `(net N "NAME")` 表里，查不到就按 `net#N` 保留（parsers.kicad）。那是一条
    # **丢名字**的记录，必须在报告上说出来：网是**按名字**认的，一块序号全丢的板
    # 正是按网名读的检查（差分对清单、按轨分档）看不见的板。门只对 KiCad 读数开
    # ——`net#N` 是 KiCad 读盘器自己写的形状，EasyEDA 板的网名不是它造的。
    from ..parsers.kicad import is_kicad_path, unnamed_net_names

    if is_kicad_path(str(getattr(board, "source", "") or "")):
        # 192A-3：读法是读盘器自己的那一个（`unnamed_net_names`），不是这里重写
        # 一遍前缀匹配——两把尺必然漂移，而这条披露的全部价值就是「数与
        # `parsers.kicad` 说的一致」。
        unnamed = unnamed_net_names(board)
        notes: list[str] = []
        if unnamed:
            shown = "、".join(unnamed[:NET_ID_NOTE_LIMIT]) + ("…" if len(unnamed) > NET_ID_NOTE_LIMIT else "")
            notes.append(
                f"文件里有 {len(unnamed)} 个网序号查不到名字（{shown}），已按 net#N 保留"
                "——按网名认网的检查（差分对清单、按轨分档）看不到这些网"
            )
        # 192A-4：文件自己的表给同一个序号写了不止一次（先写的胜出，后写的被
        # 忽略）。这也是一条必须在报告上说出来的话——被忽略的那个名字标注过的
        # 铜，现在归在第一个名字名下，而一条裸 `(net N)` 的走线正是查表得到名字
        # 的；不说，读报告的人会以为文件里只有第一个名字。
        conflicts = getattr(board, "net_table_conflicts", None) or {}
        if conflicts:
            rows = "、".join(
                f"{ident}（{'、'.join(names)}）"
                for ident, names in list(conflicts.items())[:NET_ID_NOTE_LIMIT]
            )
            notes.append(
                f"文件自己的 (net N \"NAME\") 表有 {len(conflicts)} 个序号写了不止一次（{rows}），"
                "已按首次出现的名字保留——后写的名字被忽略，它标注的铜已归到首个名字名下"
            )
        if notes:
            entry["netIdNote"] = "；".join(notes)
    return entry


def _review_units(source_path: str | Path) -> list[tuple[str, str, Any, Any]]:
    """``(title, board uuid, read board, read pcb model)`` for every board in a file.

    The two readers are deferred so an ``.epro2`` with three PCB documents
    still parses one board at a time, exactly as before R3. An ``.epro2`` gives
    one unit per PCB document (titled by its ``META``, 钉 4). A KiCad project
    (R3) gives **one** unit — a ``.kicad_pcb`` is one board — titled by the
    board file's stem, with no schematic-board link (``board_uuid`` empty: KiCad
    has no such container). An empty list is 「no board in this file」.
    """
    from ..parsers.kicad import (
        is_kicad_path,
        kicad_project_files,
        read_kicad_board,
        read_kicad_board_model,
    )

    if is_kicad_path(source_path):
        _sch, pcb = kicad_project_files(source_path)
        if pcb is None:
            return []
        return [(
            pcb.stem,
            "",
            lambda: read_kicad_board(pcb),
            lambda board: read_kicad_board_model(pcb, board),
        )]

    from ..parsers.epro2_model import build_design_model
    from ..parsers.epru import extract_board, load_epro2_source

    source = load_epro2_source(source_path)
    documents = _pcb_documents(source)
    if not documents:
        return []
    footprints = source.footprints()
    artwork = source.footprint_artwork()
    return [
        (
            title,
            board_uuid,
            lambda document=document: extract_board(document, footprints, source.stats, artwork),
            lambda _board, document=document: build_design_model(source, document),
        )
        for title, board_uuid, document in documents
    ]


def run_pcb_review(
    source_path: str | Path,
    model: Any = None,
    intent: Any = None,
    modules: list[dict] | None = None,
    *,
    rules: list[PcbRule] | None = None,
    boards_out: list[Any] | None = None,
) -> tuple[list[Finding], dict | None]:
    """Run every PCB rule over **every PCB document** of ``source_path``.

    ``boards_out`` (189C) is the **optional** out-parameter for a caller that needs the
    geometry itself and not only the section: one :class:`~boardwise.core.geometry.
    BoardGeometry` per board, appended in the same order as ``boards[]`` (so
    ``boards_out[i]`` is the board ``boards[i]`` was read from and measured on).
    ``checkup --file`` passes a list and renders ``canvas-<board>.svg`` from it; a
    caller that passes nothing is unaffected and the parse count is unchanged —
    which is the whole reason it is an out-parameter rather than a second reader
    (a canvas that re-parsed the archive would be a third parse per run and could
    in principle disagree with the board the findings came from).

    ``source_path`` is any readable ``.epro2`` backup, and **166** is why that
    sentence is worth spelling out: the online `checkup` calls this function too,
    handing it the archive its `project-file` tier downloaded from
    ``sys.get_project_file`` (written to a temporary file for the duration of the
    call). The two callers differ in where the file came from and in nothing
    else — same parser, same document selection, same rules — so an online and an
    offline reading of one board cannot drift apart.

    Returns ``(findings, section)``. ``section`` is the ``pcb_review`` report
    section, or ``None`` when the backup has no PCB document — the *absent, not
    empty* rule (钉 5): "no PCB to review" and "the PCB was reviewed and nothing
    was found" are two different statements, and only the second one is a
    section.

    Each PCB document is read on its own, through the public
    :func:`~boardwise.parsers.epru.extract_board` path, and each is named by its
    ``META`` title — never by a magic "most components" count (钉 4). So the
    毕设FOC fixture (three PCB documents: PCB3/PCB1/PCB2) yields three
    ``boards[]`` entries, and each carries its own component count and copper
    layer count.

    ``model`` (the same project's schematic DesignModel), ``intent`` (the
    design-intent contract or ``None``) and ``modules`` (the report's own
    ``modules[]``) all flow into the context the rules see, so a rule can ask
    about a net or a module without re-reading anything.

    **Each document also gets its own netlist view** as ``ctx.pcb_model``
    (131c). The runner already walks one PCB document at a time, so it builds
    :func:`~boardwise.parsers.epro2_model.build_design_model` for the document
    in hand and hands it over beside the geometry. That is what closes the
    first-document blind spot 131b recorded: the default
    :func:`~boardwise.parsers.epro2_model.build_design_model` reads the backup's
    *first* PCB document only, which on 毕设FOC 1.1.0 is ``PCB3`` — a board that
    places none of the three regulators, while ``PCB1`` (105 components) places
    all of them. It is also what keeps a rule from answering 「which capacitors
    share U5's output net」 in the schematic view's net names (``NET11``) while
    measuring the geometry of a board whose own nets are ``$1N66612``.

    The two views are **not** interchangeable and neither replaces the other:
    ``ctx.model`` stays the schematic model, which is what the established
    decap and IPC rules read, and ``ctx.pcb_model`` is added beside it. A
    caller that supplies its own ``rules`` and a context of its own is
    unaffected — ``pcb_model`` defaults to ``None`` and a rule that needs it
    treats that as 「no netlist for this document」.

    **Each board entry also carries a ``crossView`` reading** (189A2): the same
    archive's schematic and PCB netlists compared pin by pin, disclosing the pins
    the schematic view leaves on a one-member net while the PCB view says that
    net has company (:func:`cross_view_lonely_pins`). It runs outside the rule
    list — it is not a rule, it is not in ``checksRun``, and no rule's answer
    depends on it — because what it measures is the *parser's* reading rather
    than the board's. On the real board of 189A2 it is what would have made the
    four phantom single-pin nets (and the phantom power rail the report grew out
    of one of them) visible in the report instead of in the user's own
    cross-check.

    The rules are :data:`BUILTIN_PCB_RULES` unless the caller overrides. One
    broken rule does **not** kill the report: a rule that raises is skipped
    exactly like ``engines.review._run_rules`` does, its id is left out of that
    board's ``boards[].checksRun`` so the list never claims a check that did not
    run, and the id is **named** in the section's ``rules_errored`` (169).

    ``rules_errored`` is the section's flat disclosure of the second half — the
    ids of every rule that raised, deduplicated and sorted. Before 169 the
    ``except: continue`` was silent: the rule simply vanished from
    ``checksRun``, the finding count dropped by whatever it would have said, and
    nothing in the report distinguished 「the rule ran and found nothing」 from
    「the rule raised and was skipped」 (the measured incident: a run where
    ``pcb-polarity-orientation`` was absent — 59 rows became 57 — and could not
    be reproduced afterwards). This is the same channel ``engines.review`` has
    had since fork 2 on the schematic side (``completion.coverage.rulesErrored``);
    the shape is deliberately identical so a reader does not have to learn two.
    The runner still **never** re-raises: a caller that wants the exception
    keeps it by not using this runner, exactly as ``_run_rules`` forks.
    """
    rule_list = BUILTIN_PCB_RULES if rules is None else rules
    units = _review_units(source_path)
    if not units:
        return [], None  # 缺席而非空: nothing was reviewed, so nothing is claimed

    module_of = build_module_of(model, intent, modules)
    findings: list[Finding] = []
    boards: list[dict] = []
    # 169: every rule that raised, on **any** board. A rule may raise on one
    # board and answer on another (the two views differ per document), so the
    # list is flat and covers the whole run, like ``coverage.rulesErrored``.
    rules_errored: list[str] = []

    for title, board_uuid, read_board, read_pcb_model in units:
        board = read_board()
        if boards_out is not None:
            boards_out.append(board)
        pcb_model = read_pcb_model(board)
        ctx = PcbReviewContext(
            board=board,
            board_title=title,
            model=model,
            intent=intent,
            module_of=module_of,
            pcb_model=pcb_model,
            board_uuid=board_uuid,
        )
        # 189A2: the two views of this one document, compared — outside the rule
        # list on purpose, so it is not a ``checksRun`` entry and cannot change
        # what the rules see.
        cross_view = cross_view_section(
            schematic_board_for(model, board_uuid), pcb_model
        )
        checks_run: list[str] = []
        board_findings: list[Finding] = []
        for rule in rule_list:
            try:
                found = rule.check(ctx)
            except Exception:  # noqa: BLE001 — one broken rule may not kill the report
                # 169: named rather than silent. The rule stays out of
                # `checks_run` below, so the two statements agree.
                rules_errored.append(rule.id)
                continue
            checks_run.append(rule.id)
            for finding in found:
                # A PCB finding is stamped with the PCB document's title (钉 4).
                finding.board = title
                board_findings.append(finding)
        # Most severe first within the board, then by rule id — the same order
        # `engines.review` applies, so the two halves of `findings[]` read alike.
        board_findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
        start = len(findings)
        findings.extend(board_findings)
        boards.append(
            _board_entry(
                title=title,
                board=board,
                board_uuid=board_uuid,
                checks_run=checks_run,
                finding_indexes=list(range(start, len(findings))),
                cross_view=cross_view,
            )
        )
    section = {
        "available": True,
        "boards": boards,
        "runner": RUNNER_ID,
        # 169: the ids of the rules that raised, sorted and deduplicated — the
        # same flat shape `completion.coverage.rulesErrored` has, and the reason
        # 「a rule is missing from checksRun」 is no longer ambiguous. Empty (not
        # absent) when every rule answered: the section exists because rules
        # ran, so "none raised" is a reading this run really has.
        "rules_errored": sorted(set(rules_errored)),
    }
    return findings, section