"""Normalized design model for boardwise.

Stage 1 only consumes EasyEDA Pro schematic netlists (``.enet``), but this
model is the long-term contract: the review engine, and later the generator
and the simulator, all operate on these types.

The ``role`` / ``block`` fields on :class:`Component` are reserved intent
metadata for the stage-2 generator. Nothing populates them yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Net-name prefixes treated as ground. Module-level so it can become
#: configurable later without touching rule code. ``VEE`` is deliberately
#: absent: it is a *negative supply* in analog/ECL circuits, not a ground
#: (2026-09-18 ruling, M0-P0c).
GROUND_NET_PREFIXES: tuple[str, ...] = (
    "GND",
    "AGND",
    "DGND",
    "PGND",
    "EGND",
    "SGND",
    "VSS",
)


def is_ground_net(name: str | None) -> bool:
    """Return True for common ground net names (GND, AGND, PGND, VSS, ...).

    Prefix match on the upper-cased name, so ``GNDA`` and ``VSSA`` also count.
    ``None`` and empty names are never ground.

    **The name is only a candidate.** A net's role should come from declared
    intent and from device facts (a part's pin function, a rail's source); this
    inference exists so that rules have something to say about a name they were
    handed, and it is deliberately narrow — a name it does not recognise is
    "not known to be ground", not "not ground". ``VEE`` used to be listed here,
    which made a negative supply read as ground; it is now left to the
    declarations and device facts that should have been deciding it.
    """
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(prefix) for prefix in GROUND_NET_PREFIXES)


@dataclass
class Pin:
    """One pin of a component."""

    number: str
    name: str
    net: str | None = None


#: Why a reading cannot prove a net. ``WELDED_BY_NAME`` is issue #19's gap —
#: the per-page merge joined two pages because they spelled a net name the same
#: way, which may be two boards. The two truncation codes are 107's: the parser
#: kept only the first placement of a repeated designator (049's one-designator-
#: one-component contract), so a placement that is drawn on the sheet and does
#: connect to the net is missing from ``Net.pins`` — the net's member list came
#: out short, and a rule that looks a part up *on that net* is looking at a
#: netlist with a hole in it.
WELDED_BY_NAME = "welded-by-name"
TRUNCATED_BY_DESIGNATOR = "truncated-by-duplicate-designator"
TRUNCATED_BY_CROSS_PAGE_DESIGNATOR = "truncated-by-cross-page-designator"


@dataclass
class Component:
    """One placed component, keyed by designator inside the model."""

    uid: str
    designator: str
    value: str = ""
    footprint: str = ""
    lcsc_part: str = ""
    manufacturer: str = ""
    mpn: str = ""
    datasheet: str = ""
    props: dict[str, Any] = field(default_factory=dict)
    pins: list[Pin] = field(default_factory=list)
    # Reserved intent metadata for the stage-2 generator. Unused today.
    role: str | None = None
    block: str | None = None


@dataclass
class Net:
    """One named net. ``pins`` holds (designator, pin_number) tuples."""

    name: str
    pins: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DesignModel:
    """The normalized board model.

    - ``components``: designator -> Component
    - ``nets``: net name -> Net (reverse-built by the parser)
    - ``raw``: untouched top-level blocks from the source file
      (designRule / differentialPair / netClass / equalLengthNetGroup),
      kept verbatim because future rules will consume them.
    """

    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    #: Designators placed **twice on one page**: two parts answer to one name
    #: in one netlist, which is what CONN-1 is about. The dict key above keeps
    #: only the first placement, so without this list the clash would be silent
    #: (task 011c sec.3.2). Empty for single-page boards without clashes.
    duplicate_designators: list[str] = field(default_factory=list)
    #: Designator -> the pages it is placed on, for designators that appear on
    #: **more than one page** (one placement each). A multi-board project
    #: numbers each board's parts independently, so this is information, not a
    #: defect — 040 §WI-3 split it out of ``duplicate_designators``, which used
    #: to hold both kinds under one name. ``repeated_designators()`` is what a
    #: consumer that merely needs "is this name ambiguous here?" should call.
    cross_page_designators: dict[str, list[str]] = field(default_factory=dict)
    #: Net names whose **membership is not a verified connection**, with the
    #: pages each name was seen on. Empty for every model that comes out of one
    #: export — which is every model except the merged per-page one (issue #19,
    #: :func:`boardwise.cli._merge_schematic_models`): a single export's netlist
    #: *is* its connectivity, so its nets are proven by construction.
    #:
    #: The per-page tier reads one page at a time and holds no document that says
    #: which board a page belongs to. Merging two pages by net **name** therefore
    #: welds two boards' netlists together wherever the names agree (`VCC`,
    #: `+5V`, `GND` are the common ones), and a rule that then finds a capacitor
    #: on "VCC" cannot tell whose board it is on. A name listed here was seen on
    #: more than one page, so a rule whose conclusion depends on which *other*
    #: parts sit on it must refuse (``boardwise.rules.unproven``) rather than
    #: conclude pass or fail.
    #:
    #: The value is the page uuids the name was seen on. As with
    #: :attr:`cross_page_designators`, an **empty tuple** is what a caller states
    #: when it knows the name is on more than one page but cannot name them (a
    #: merge of models that carry no page ids) — so the test is ``is not None``,
    #: never truthiness.
    unproven_nets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: net name -> ``(reason code, one sentence naming the placements that were
    #: left out)`` for the names this reading cannot prove **and why**, per the
    #: codes above. An absent entry means :data:`WELDED_BY_NAME` — the issue #19
    #: merge, which is still the whole story for a model that came out of one
    #: export — so a reader written before this field keeps its wording, and a
    #: net whose membership a dropped placement may have truncated says so
    #: instead of being read as a net two pages happened to share a name with
    #: (107). The sentence is stored rather than rebuilt because only the parser
    #: knows which placement it dropped; it is quoted, never parsed.
    unproven_reasons: dict[str, tuple[str, str]] = field(default_factory=dict)

    def unproven_pages(self, name: str | None) -> tuple[str, ...] | None:
        """The pages ``name`` was seen on when it is unproven, else ``None``.

        ``()`` is a real answer ("more than one page, page ids unknown"), so
        callers test ``is not None``.
        """
        if not name:
            return None
        return self.unproven_nets.get(name)

    def unproven_reason(self, name: str | None) -> tuple[str, str]:
        """``(reason code, detail)`` for an unproven ``name``.

        :data:`WELDED_BY_NAME` with an empty detail is what a name listed in
        :attr:`unproven_nets` without one says — the pre-107 shape, which is
        every net of a single-export reading and every name the per-page merge
        welded.
        """
        if not name:
            return (WELDED_BY_NAME, "")
        return self.unproven_reasons.get(name, (WELDED_BY_NAME, ""))

    def repeated_designators(self) -> list[str]:
        """Every designator this model cannot resolve to exactly one placement.

        Both kinds are ambiguous for a *consumer* even though only one of them
        is a defect: a repair plan or a per-page report cannot tell which
        placement is meant. Rules that judge the drawing use
        :attr:`duplicate_designators` instead — the distinction is 040 §WI-3's
        whole point.
        """
        return sorted(set(self.duplicate_designators) | set(self.cross_page_designators))


class MultiBoardProjectError(ValueError):
    """A single-board consumer was handed a multi-board project (040b §WI-2).

    Raised instead of returning one board's model or a pooled one: both would be
    silent — the first drops boards, the second re-welds them (040's F1/F2/F3
    exist because that weld was read as a board reading). A ``ValueError``
    subclass so existing ``except ValueError`` handlers degrade to a message
    rather than a traceback.

    It lives in ``core`` because it is a statement about the model contract, and
    because the façade below has to be able to raise it without importing a
    parser (``core`` must not import ``parsers``).
    """


@dataclass(frozen=True)
class BoardRef:
    """Which board a model belongs to, and which pages it was drawn on.

    040b: a project's pages are grouped into boards through the container's own
    document chain (see :func:`boardwise.parsers.schematic.board_partition`);
    this is that grouping as data. ``uuid`` is the container's board id and is
    empty for a board that exists only implicitly (a project with no BOARD
    document, or a folder project whose index has no ``profile.boards``).

    A board may hold **several pages** (measured: 毕设 Board1 owns page
    ``5f0f…`` and the empty ``b034…``), which is why pages, not boards, are
    what a ``COMPONENT`` record's coordinates belong to.
    """

    uuid: str = ""
    title: str = ""
    page_uuids: tuple[str, ...] = ()


@dataclass
class BoardModel(DesignModel):
    """One board's design model — the unit every rule runs on (040b §WI-2).

    "One designator, one component" is narrowed to **one board**: two boards may
    each hold their own ``R1``, and both placements live on in their own board's
    model instead of the later one silently overwriting the earlier (which is
    what a project-wide dict did).

    ``cross_board_designators`` is the one project-scoped fact a board model
    carries: for a designator placed on more than one board, the *titles of every
    board that has it*, in project order (so the first entry is the board that
    reports it — see :class:`boardwise.rules.connectivity.DuplicateDesignators`).
    A rule that only ever sees one board can therefore still say "this name is
    also used on Board3", which is the difference between a same-board repeat
    and a cross-board one (040b §WI-3; the oracle's A1 ruling is unchanged).
    """

    board: BoardRef = field(default_factory=BoardRef)
    cross_board_designators: dict[str, list[str]] = field(default_factory=dict)

    def repeated_designators(self) -> list[str]:
        """As :meth:`DesignModel.repeated_designators`, plus the cross-board names.

        On a board, a designator resolves to one placement *within* the board;
        it is still ambiguous for a consumer that has to name a part in a
        project-scoped artefact (a BOM, an edit plan), which is why the
        cross-board names are included here and not in
        :attr:`duplicate_designators`.
        """
        return sorted(
            set(super().repeated_designators()) | set(self.cross_board_designators)
        )


@dataclass
class ProjectModel:
    """A project's boards, each a :class:`BoardModel` (040b §WI-2).

    What this replaces: a single designator-keyed dict fed by every page of the
    project. That shape could not hold a multi-board project at all — the second
    board's ``C1`` overwrote the first's (040 measured 30 such refs on the 毕设
    board, and 040b's two U2s are the worked example).

    **The single-board façade.** ``components``, ``nets``,
    ``duplicate_designators`` and ``cross_page_designators`` read straight
    through to the project's one board, so a consumer written before boards
    existed keeps working — and a **multi-board** project raises
    :class:`MultiBoardProjectError` naming the boards instead of quietly
    answering with board 0. That refusal is the point: the alternative
    (first-board-wins) is exactly the silent loss this batch removes, one level
    up. Consumers that can be board-aware use :attr:`boards` directly.

    ``unproven_nets`` is read here too, with one deliberate difference — it
    **answers** on a multi-board project instead of raising, because there is
    nothing welded to report there (see its own docstring). A rule is handed
    whatever model the caller has, so "cannot answer" must not become a crash.

    ``project_raw`` keeps the untouched top-level blocks of the *project*;
    ``raw`` (the façade) keeps reading the single board's, as before.
    """

    boards: list[BoardModel] = field(default_factory=list)
    source: str = ""
    project_raw: dict[str, Any] = field(default_factory=dict)

    # --- board-aware reads (what multi-board consumers use) -----------------

    def board_titles(self) -> list[str]:
        """Every board title, in project order (what a finding's ``board`` names)."""
        return [board.board.title for board in self.boards]

    def designators(self) -> list[str]:
        """The project's distinct designators, sorted (names, not placements)."""
        return sorted({name for board in self.boards for name in board.components})

    def component_count(self) -> int:
        """Placed parts across every board (155 for the 毕设 project, not 121 names)."""
        return sum(len(board.components) for board in self.boards)

    def net_count(self) -> int:
        """Net instances across every board — per-board nets are not one netlist."""
        return sum(len(board.nets) for board in self.boards)

    def multi_board_designators(self) -> dict[str, list[str]]:
        """Designator -> the titles of every board carrying it, for names on >1 board."""
        seen: dict[str, list[str]] = {}
        for board in self.boards:
            for designator in board.components:
                titles = seen.setdefault(designator, [])
                if board.board.title not in titles:
                    titles.append(board.board.title)
        return {
            designator: titles
            for designator, titles in sorted(seen.items())
            if len(titles) > 1
        }

    def repeated_designators(self) -> list[str]:
        """Every name a project-scoped consumer cannot resolve to one placement."""
        names = {name for board in self.boards for name in board.repeated_designators()}
        return sorted(names)

    # --- single-board façade (refuses a multi-board project by name) --------

    def single_board(self) -> BoardModel:
        """The project's one board, or :class:`MultiBoardProjectError`."""
        if len(self.boards) != 1:
            raise MultiBoardProjectError(
                f"this project has {len(self.boards)} boards "
                f"({', '.join(self.board_titles()) or 'none'}) — ask for a board "
                "model instead of reading the project as one"
            )
        return self.boards[0]

    @property
    def components(self) -> dict[str, Component]:
        """The one board's components (040b façade; refuses a multi-board project)."""
        return self.single_board().components

    @property
    def nets(self) -> dict[str, Net]:
        """The one board's nets (040b façade)."""
        return self.single_board().nets

    @property
    def raw(self) -> dict[str, Any]:
        """The one board's raw blocks (040b façade)."""
        return self.single_board().raw

    @property
    def duplicate_designators(self) -> list[str]:
        """The one board's same-page repeats (040b façade)."""
        return self.single_board().duplicate_designators

    @property
    def cross_page_designators(self) -> dict[str, list[str]]:
        """The one board's several-page repeats (040b façade)."""
        return self.single_board().cross_page_designators

    @property
    def unproven_nets(self) -> dict[str, tuple[str, ...]]:
        """The project's welded net names — empty unless it is one merged board.

        Not the raising façade the fields above use, deliberately: a **multi-board
        project** has nothing welded, because the container's own document chain
        attributes every page to a board (:func:`boardwise.parsers.schematic.board_partition`),
        so each board's netlist is its own. And the rules are handed whatever
        model the caller has, so a read that cannot answer "unproven?" must answer
        "no" rather than raise out of a rule run.
        """
        if len(self.boards) != 1:
            return {}
        return self.boards[0].unproven_nets

    def unproven_pages(self, name: str | None) -> tuple[str, ...] | None:
        """As :meth:`DesignModel.unproven_pages`, on the project's one board.

        ``None`` for a multi-board project — which is what every net there is:
        attributed to a board by the container, therefore proven.
        """
        if len(self.boards) != 1:
            return None
        return self.boards[0].unproven_pages(name)

    @property
    def unproven_reasons(self) -> dict[str, tuple[str, str]]:
        """The one board's reasons for its unproven names — ``{}`` if many."""
        if len(self.boards) != 1:
            return {}
        return self.boards[0].unproven_reasons

    def unproven_reason(self, name: str | None) -> tuple[str, str]:
        """As :meth:`DesignModel.unproven_reason`, on the project's one board.

        ``WELDED_BY_NAME`` for a multi-board project, like every net there.
        """
        if len(self.boards) != 1:
            return (WELDED_BY_NAME, "")
        return self.boards[0].unproven_reason(name)
