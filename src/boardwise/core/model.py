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
    #: only the last placement, so without this list the clash would be silent
    #: (task 011c sec.3.2). Empty for single-page boards without clashes.
    duplicate_designators: list[str] = field(default_factory=list)
    #: Designator -> the pages it is placed on, for designators that appear on
    #: **more than one page** (one placement each). A multi-board project
    #: numbers each board's parts independently, so this is information, not a
    #: defect — 040 §WI-3 split it out of ``duplicate_designators``, which used
    #: to hold both kinds under one name. ``repeated_designators()`` is what a
    #: consumer that merely needs "is this name ambiguous here?" should call.
    cross_page_designators: dict[str, list[str]] = field(default_factory=dict)

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
