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

from pathlib import Path
from typing import Any

from ..core.measure import read_stackup
from ..rules.pcb.base import PcbReviewContext, PcbRule
from ..rules.pcb.derating import DeratingPackage
from ..rules.pcb.distance import ComponentSpacing, DecapDistance
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
    TrackAmpacity(),
    VoltageSpacing(),
    KeepoutViolation(),
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


def _board_entry(
    *,
    title: str,
    board: Any,
    board_uuid: str,
    checks_run: list[str],
    finding_indexes: list[int],
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
    """
    info = read_stackup(board)
    return {
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
) -> tuple[list[Finding], dict | None]:
    """Run every PCB rule over **every PCB document** of ``source_path``.

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
        ctx = PcbReviewContext(
            board=board,
            board_title=title,
            model=model,
            intent=intent,
            module_of=module_of,
            pcb_model=read_pcb_model(board),
            board_uuid=board_uuid,
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