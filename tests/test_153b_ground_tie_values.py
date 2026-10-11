"""Task 153b: the ground-tie value reading — schematic page first, PCB copy as fallback.

``pcb-foc-ground-tie`` judges 岳's 2026-10-08 「恰好一颗 0R」 convention, and until
153b it read the value from **``ctx.pcb_model`` — the PCB document's own
``component.value``**. That field is a systematically stale copy: measured on
毕设FOC 1.1.0's PCB1, **45 of its 105** placed parts carry a value the schematic
page contradicts (23 of them read ``100nF``, 20 read ``10K``, regardless of what
the schematic says), and 1.0.0's PCB1 reads 37 the same way. So the rule
fabricated the facts it judged: 1.0.0's ``R48``/``R49`` — both ``0R`` on the
schematic — came back ``10K``, and the board was reported as 「two 10 kΩ
resistors, no 0 Ω at all」.

The fix is 153's ``derating._schematic_component`` reading, ported:
:func:`~boardwise.rules.pcb.focground.schematic_board_of` resolves **this PCB
document's own schematic page** off ``META.board`` (151/153's chain, never
designator overlap), the page's declaration wins, the PCB document's copy is used
only when the page states nothing, and :func:`_value_view_evidence` writes both
views onto the row whenever they disagree.

This file pins, in order:

* **the defect's data** — the copy really is stale, on all three 毕设FOC boards
  plus ROBOT's one empty-value case, measured rather than assumed;
* **the reading** — the three cases (page states a value / page states nothing /
  neither states one), the divergence rule, and the refusal to let the copy
  rescue an unreadable schematic value;
* **the acceptance anchors** — 1.0.0 and 1.1.0's corrected tie accounts, ROBOT's
  fallback, and the row counts on every acceptance board;
* **the branch reachability** — no fixture reaches the *non-zero* or *UNKNOWN*
  branch any more, so they are built synthetically, which is also what keeps the
  structural (not value-filtered) pool justified;
* **the two mutations** — flipping the priority back to the PCB copy, and letting
  an unreadable value read as zero. Each is applied to the source, observed red,
  and reverted byte-for-byte (``cp`` + ``sha256``); ``outputs/153b/mutations/``
  keeps the transcripts.
"""

from __future__ import annotations

from pathlib import Path

from boardwise.core.model import Component, DesignModel
from boardwise.core.parts import PartLibrary
from boardwise.engines.pcbreview import _pcb_documents, run_pcb_review
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import load_epro2_source
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.focground import (
    FocGroundTie,
    _placed_on,
    _value_ohms,
    _value_view_evidence,
    all_zero_ohm_parts_of,
    bridging_parts_of,
    schematic_board_of,
    zero_ohm_resistors_of,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

R1B = "pcb-foc-ground-tie"
EMPTY_SHELF = PartLibrary()

_PROJECTS: dict[Path, object] = {}


def _project(path: Path):
    project = _PROJECTS.get(path)
    if project is None:
        project = _PROJECTS[path] = build_project_model(path)
    return project


def _findings(path: Path) -> list:
    findings, _section = run_pcb_review(path, model=_project(path))
    return findings


def _rows(path: Path, rule_id: str = R1B) -> list:
    return [f for f in _findings(path) if f.rule_id == rule_id]


def _schematic_page(path: Path, title: str):
    """The schematic page a PCB document declares, off ``META.board``."""
    for doc_title, board_uuid, _document in _pcb_documents(load_epro2_source(path)):
        if doc_title != title:
            continue
        for board in getattr(_project(path), "boards", []) or []:
            if str(
                getattr(getattr(board, "board", None), "uuid", "") or ""
            ) == str(board_uuid):
                return board
        return None
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


def _pcb_view(path: Path, title: str = "PCB1"):
    """``(board, pcb_model)`` for one PCB document of a fixture."""
    from boardwise.parsers.epru import extract_board

    source = load_epro2_source(path)
    for document in source.documents_of_type("PCB"):
        document_title = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                document_title = str(record.body.get("title") or "")
                if document_title:
                    break
        if document_title == title:
            return (
                extract_board(document, source.footprints(), source.stats),
                build_design_model(source, document),
            )
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


def _page(values: dict[str, str]) -> DesignModel:
    """A stand-in schematic page: ``designator -> Value`` and nothing else.

    A :class:`DesignModel` with no ``boards`` **is** its own page as far as
    :func:`schematic_board_of` is concerned, which is what lets a test hand the
    rule a page whose declarations it controls while the board and the netlist
    stay the fixture's real ones.
    """
    return DesignModel(
        components={
            designator: Component(
                uid=designator, designator=designator, value=value
            )
            for designator, value in values.items()
        }
    )


# ---------------------------------------------------------------------------
# 一、the defect's data — why the PCB document's copy cannot be the source
# ---------------------------------------------------------------------------


def test_the_pcb_documents_value_is_a_stale_copy_on_the_bisce_boards():
    """**The defect, measured**: the PCB copy contradicts the page, en masse.

    Per board, the designators whose two views disagree, and — the shape that
    makes it a *placeholder* rather than ordinary drift — how many of them read
    the same two strings. 毕设FOC 1.1.0's PCB1 is the worst of the corpus: 45 of
    105 placed parts, of which 23 read ``100nF`` and 20 read ``10K`` whatever the
    schematic page says. 1.0.0's PCB1 is the same shape at 37 of 122 (24 read
    ``10K``, 8 read ``100nF``, and the other five are real drift).

    Read straight off the two views (no rule involved), so this test fails if the
    *fixtures* change, not merely if the rule does.
    """
    measured = {}
    for path, title in (
        (FOC_100, "PCB1"),
        (FOC_110, "PCB1"),
        (FOC_110, "PCB3"),
        (ROBOT, "PCB1"),
        (LLC, "PCB1"),
    ):
        _board, pcb_model = _pcb_view(path, title)
        page = {
            str(des): str(getattr(comp, "value", "") or "")
            for des, comp in (getattr(_schematic_page(path, title), "components", {}) or {}).items()
        }
        placed = getattr(pcb_model, "components", {}) or {}
        divergent = {
            str(des): (page.get(str(des), ""), str(getattr(comp, "value", "") or ""))
            for des, comp in placed.items()
            if page.get(str(des), "")
            and str(getattr(comp, "value", "") or "")
            and page[str(des)] != str(getattr(comp, "value", "") or "")
        }
        measured[(path.name, title)] = divergent

    f100 = measured[(FOC_100.name, "PCB1")]
    assert len(f100) == 37, len(f100)
    assert sum(1 for _s, p in f100.values() if p == "10K") == 24
    assert sum(1 for _s, p in f100.values() if p == "100nF") == 8
    assert sum(1 for _s, p in f100.values() if p in ("5mΩ", "470Ω")) == 5, (
        "the other five are real drift rather than the placeholder — 1.0.0's "
        "shunts (10mΩ on the page / 5mΩ in the copy) and two ICs whose 'value' "
        "field drifted; the fix reads the page for them too"
    )
    assert f100["R48"] == ("0R", "10K") and f100["R49"] == ("0R", "10K"), (
        "1.0.0's two ground ties: the page says 0R, the copy says 10K — this "
        "pair is the rule's headline defect"
    )
    assert f100["R31"] == ("0R", "10K"), "and 1.0.0's third 0R, a jumper"

    f110 = measured[(FOC_110.name, "PCB1")]
    assert len(f110) == 45, len(f110)
    assert sum(1 for _s, p in f110.values() if p == "100nF") == 23
    assert sum(1 for _s, p in f110.values() if p == "10K") == 20
    assert f110["R11"] == ("0R", "10K") and f110["R25"] == ("0R", "10K")
    assert f110["R3"] == ("0R", "10K")

    f110_pcb3 = measured[(FOC_110.name, "PCB3")]
    assert set(f110_pcb3) == {"R8", "R18", "R43"}, sorted(f110_pcb3)
    assert all(p == "5mΩ" and s == "10mΩ" for s, p in f110_pcb3.values()), (
        "PCB3's drift is a different, real one (4-wire shunt values), not the "
        "10K/100nF placeholder — the fix reads the page there too, and the "
        "voltage-divider rules already do"
    )

    robot = measured[(ROBOT.name, "PCB1")]
    assert len(robot) == 12, len(robot)
    assert "R8" not in robot, (
        "ROBOT's R8 is **absent** from the divergent set on purpose: its page "
        "states nothing at all, which is the *fallback* case, not a divergence"
    )
    assert sum(1 for _s, p in robot.values() if p == "100nF") == 6
    assert sum(1 for _s, p in robot.values() if p == "10K") == 6


def test_the_copy_is_not_the_source_on_the_one_part_that_decides_the_row():
    """The same fact narrowed to the rule's own object, both surveys at once.

    ``R48`` is a ``0R`` on the page and a ``10K`` in the PCB document. Which one
    the rule reads is the whole of 153b, so it is asserted directly on the two
    views as well as through the rule.
    """
    _board, pcb_model = _pcb_view(FOC_100, "PCB1")
    page = _schematic_page(FOC_100, "PCB1")
    assert str(page.components["R48"].value) == "0R"
    assert str(pcb_model.components["R48"].value) == "10K"
    assert str(page.components["R48"].value) != str(pcb_model.components["R48"].value)


# ---------------------------------------------------------------------------
# 二、the reading — schematic first, copy as fallback
# ---------------------------------------------------------------------------


def test_schematic_board_of_walks_the_declared_board_link():
    """The page is found by ``META.board``, never by designator overlap.

    毕设FOC 1.0.0's PCB1 declares ``Board1`` and PCB2 ``Board2``, and the project
    has one board per document — so a rule that matched pages by refdes (Board1
    and Board3 share ``C1``…``R6``) would answer with the wrong one. 智能药箱's
    PCB1 declares **no** link at all, which is the honest ``None`` the rule
    degrades on.
    """
    _board, pcb_model = _pcb_view(FOC_100, "PCB1")
    ctx = PcbReviewContext(
        board=_board, pcb_model=pcb_model, model=_project(FOC_100),
        board_uuid="d5c055266ef55000",
    )
    page = schematic_board_of(ctx)
    assert str(page.board.title) == "Board1"
    assert "R48" in page.components

    ctx2 = PcbReviewContext(
        board=_board, pcb_model=pcb_model, model=_project(FOC_100),
        board_uuid="5455a645b144c024",
    )
    assert str(schematic_board_of(ctx2).board.title) == "Board2"

    assert schematic_board_of(PcbReviewContext(board=_board, pcb_model=pcb_model)) is None, (
        "no project model at all: no schematic view, and the pools then read the "
        "PCB document's copies and say they are fallbacks"
    )
    pillbox = _pcb_view(PILLBOX, "PCB1")
    assert schematic_board_of(
        PcbReviewContext(
            board=pillbox[0], pcb_model=pillbox[1], model=_project(PILLBOX),
            board_uuid="",
        )
    ) is not None, (
        "智能药箱's PCB1 declares no META.board (measured: the link is empty), and "
        "its project has exactly **one** board — a single board is no choice at "
        "all, so that page is used rather than the PCB document's copy"
    )
    multi = PcbReviewContext(
        board=_board, pcb_model=pcb_model, model=_project(FOC_100), board_uuid=""
    )
    assert schematic_board_of(multi) is None, (
        "with several boards and no link there is nothing to resolve: 「板链读不出」, "
        "never a guess at board 0"
    )
    unknown = PcbReviewContext(
        board=_board, pcb_model=pcb_model, model=_project(FOC_100),
        board_uuid="ffffffffffffffff",
    )
    assert schematic_board_of(unknown) is None, (
        "a link that matches no board is also None rather than a guess at board 0"
    )


def test_value_ohms_prefers_the_page_and_records_both_views():
    """The three cases, each with its own ``basis`` sentence.

    1. page and copy both state a value → the **page's** is judged on, and the
       divergence is written out;
    2. the page states nothing → the copy is used, and the basis says it is a
       fallback;
    3. neither states one → ``""``/``None``, UNKNOWN.
    """
    _board, pcb_model = _pcb_view(FOC_100, "PCB1")
    r48 = pcb_model.components["R48"]

    divergent = _value_ohms(r48, _page({"R48": "0R"}).components["R48"])
    assert divergent.value == "0R" and divergent.ohms == 0.0
    assert divergent.schematic_value == "0R" and divergent.pcb_value == "10K"
    assert "两视图不一致" in divergent.basis and "原理图" in divergent.basis

    agreeing = _value_ohms(r48, _page({"R48": "10K"}).components["R48"])
    assert agreeing.value == "10K" and agreeing.ohms == 10000.0
    assert "两视图不一致" not in agreeing.basis
    assert "PCB 文档同值" in agreeing.basis

    fallback = _value_ohms(r48, _page({}).components.get("R48"))
    assert fallback.value == "10K" and fallback.ohms == 10000.0
    assert fallback.schematic_value == "" and fallback.pcb_value == "10K"
    assert "回退" in fallback.basis

    unstated = _value_ohms(_page({"R48": ""}).components["R48"], None)
    assert unstated.value == "" and unstated.ohms is None
    assert "都没有写值" in unstated.basis

    assert _placed_on(_page({"R48": "0R"}), "R48") is not None
    assert _placed_on(_page({"R48": "0R"}), "R99") is None
    assert _placed_on(None, "R48") is None


def test_the_copy_cannot_rescue_an_unreadable_schematic_value():
    """A page that states something unreadable is **UNKNOWN**, not the copy's zero.

    The invented single point facing the other way: if the page declares a value
    the grammar cannot read and the PCB copy happens to say ``0R``, taking the
    copy would manufacture a 0 Ω tie out of the view this fix demotes. The value
    read is the page's (so UNKNOWN), and both views are on the record.
    """
    drawn = _value_ohms(
        _page({"R7": "0R"}).components["R7"], _page({"R7": "???"}).components["R7"]
    )
    assert drawn.value == "???" and drawn.ohms is None, (
        "the page's unreadable declaration is UNKNOWN — the copy is not allowed "
        "to turn it into a 0 Ω"
    )
    assert drawn.pcb_value == "0R"
    assert "两视图不一致" in drawn.basis


def test_value_view_evidence_names_the_divergent_and_the_fallback_parts():
    """The row's one auditable line: who drifted, and who had to fall back."""
    _board, pcb_model = _pcb_view(FOC_100, "PCB1")
    page = _schematic_page(FOC_100, "PCB1")
    r48 = bridging_parts_of(pcb_model, EMPTY_SHELF, page)
    line = _value_view_evidence(r48, header="R48/R49")
    assert line.startswith("R48/R49：")
    assert "原理图声明优先" in line and "回退" in line
    assert "R48 原理图 '0R' / PCB 文档 '10K'" in line
    assert "R49 原理图 '0R' / PCB 文档 '10K'" in line
    assert "(无)" == line.split("回退 PCB 文档值**的件：")[1], (
        "the fallback half is empty here: both parts state a page value"
    )

    robot_board, robot_model = _pcb_view(ROBOT, "PCB1")
    robot_page = _schematic_page(ROBOT, "PCB1")
    assert bridging_parts_of(robot_model, EMPTY_SHELF, robot_page) == []
    zeros = all_zero_ohm_parts_of(robot_model, EMPTY_SHELF, robot_page)
    robot_line = _value_view_evidence(zeros)
    assert "R8 ('0Ω')" in robot_line.split("回退 PCB 文档值**的件：")[1], (
        "ROBOT's R8 is the measured fallback case and is named as one"
    )


# ---------------------------------------------------------------------------
# 三、the acceptance anchors — the corrected accounts
# ---------------------------------------------------------------------------


def test_r1b_reads_100_as_two_0r_ties_plus_one_jumper():
    """1.0.0's corrected answer, straight off the production entry point.

    Two ``0R`` cross-domain ties (``R48`` ``GND``↔``PGND``, ``R49``
    ``AGND``↔``PGND``), one 0 Ω jumper inside neither domain (``R31`` on
    ``+24V``↔``$1N74269``), and no 10 kΩ bridge anywhere. The 「not a single
    point」 branch is unchanged in *form* — 岳's convention is one 0 Ω for the
    whole ground system, and this board ties the power domain to the logic domain
    twice — but the account is now the board's own.
    """
    rows = [r for r in _rows(FOC_100) if r.board == "PCB1"]
    assert len(rows) == 2, [r.message[:70] for r in rows]
    account = next(r for r in rows if "not a single point" in r.message)
    assert "2 0 Ω resistor(s) (R48 'GND'↔'PGND', R49 'AGND'↔'PGND')" in account.message
    assert "非零" not in account.message and "**non-zero**" not in account.message
    assert "原理图 '0R' / PCB 文档 '10K'" in "\n".join(account.evidence)
    assert account.target.net_refs == [], (
        "the account row is not a per-part row; the ties are named in its text"
    )

    jumper = next(r for r in rows if r is not account)
    assert "R31" in jumper.message and jumper.target.component_ref == "R31"
    assert "not a ground-domain tie" in jumper.message


def test_r1b_reads_110_as_two_0r_ties_on_pcb1():
    """1.1.0's corrected answer, and its own two jumpers' board is PCB3.

    1.1.0's PCB1 carries the power stage: ``R25`` (``0R``, ``GND``↔``PGND``) and
    ``R11`` (``0R``, ``AGND``↔``PGND``) are its two cross-domain ties, plus
    ``R3`` (``0R``, ``+24V``↔``$1N74457``) as a jumper. Its PCB3 carries a
    ``PGND`` and no logic ground at all, and PCB2 no power ground — the same two
    structural rows as before, unaffected by the value fix.
    """
    rows = [r for r in _rows(FOC_110) if r.board == "PCB1"]
    assert len(rows) == 2, [r.message[:70] for r in rows]
    account = next(r for r in rows if "not a single point" in r.message)
    assert "2 0 Ω resistor(s) (R11 'AGND'↔'PGND', R25 'GND'↔'PGND')" in account.message
    assert "**non-zero**" not in account.message
    assert "原理图 '0R' / PCB 文档 '10K'" in "\n".join(account.evidence)
    for part in ("R11", "R25", "R3"):
        assert f"{part} 原理图 '0R' / PCB 文档 '10K'" in "\n".join(account.evidence)

    jumper = next(r for r in rows if r is not account)
    assert jumper.target.component_ref == "R3"

    pcb3 = [r for r in _rows(FOC_110) if r.board == "PCB3"]
    assert len(pcb3) == 1 and "no logic/analog ground" in pcb3[0].message
    pcb2 = [r for r in _rows(FOC_110) if r.board == "PCB2"]
    assert len(pcb2) == 1 and "no power-domain ground" in pcb2[0].message


def test_r1b_uses_the_pcb_documents_value_when_the_page_states_none():
    """ROBOT's ``R8``: the measured **fallback**, and no fixture reaches a tie.

    The page states no value for ``R8`` and the PCB document's ``0Ω`` is the only
    one there is, so the rule uses it — and says it is a fallback. The part's pins
    sit on ``GND`` and ``$1N251``, one ground net and one not, so it is a jumper
    and ROBOT (no ``PGND`` at all) still takes the no-power-domain row.
    """
    _board, pcb_model = _pcb_view(ROBOT, "PCB1")
    page = _schematic_page(ROBOT, "PCB1")
    zeros = all_zero_ohm_parts_of(pcb_model, EMPTY_SHELF, page)
    assert [p.designator for p in zeros] == ["R8"]
    assert zeros[0].value == "0Ω" and "回退" in zeros[0].value_basis
    assert bridging_parts_of(pcb_model, EMPTY_SHELF, page) == []
    assert zero_ohm_resistors_of(pcb_model, EMPTY_SHELF, page) == []

    rows = _rows(ROBOT)
    assert len(rows) == 1 and "no power-domain ground" in rows[0].message


def test_the_row_counts_are_unchanged_on_the_four_boards_without_a_tie():
    """R1 and R5 do not read a value, so only R1b's counts move — and only on the
    two 毕设FOC boards. Pinned as a whole-board tally so a silent extra row is one
    failure rather than a puzzle.

    Measured: 1.0.0 → PCB1 2 R1b rows + PCB2 1 = **3**; 1.1.0 → PCB3 1 + PCB1 2 +
    PCB2 1 = **4**; ROBOT / 药箱 / llc → **1** each. R1 and R5 counts are the ones
    133c measured (the fix touches neither).
    """
    tally = {
        FOC_100: {
            "pcb-foc-ground-domains": 3,
            "pcb-foc-ground-tie": 3,
            "pcb-foc-return-path": 16,
        },
        FOC_110: {
            "pcb-foc-ground-domains": 4,
            "pcb-foc-ground-tie": 4,
            "pcb-foc-return-path": 25,
        },
        ROBOT: {
            "pcb-foc-ground-domains": 1,
            "pcb-foc-ground-tie": 1,
            "pcb-foc-return-path": 1,
        },
        PILLBOX: {
            "pcb-foc-ground-domains": 1,
            "pcb-foc-ground-tie": 1,
            "pcb-foc-return-path": 1,
        },
        LLC: {
            "pcb-foc-ground-domains": 1,
            "pcb-foc-ground-tie": 1,
            "pcb-foc-return-path": 1,
        },
    }
    for path, expected in tally.items():
        findings = _findings(path)
        counts = {
            rid: sum(1 for f in findings if f.rule_id == rid) for rid in expected
        }
        assert counts == expected, (path.name, counts, expected)
        mine = [f for f in findings if f.rule_id in expected]
        assert all(f.severity == "INFO" for f in mine), path.name


def test_the_same_board_read_without_the_project_model_is_the_old_false_answer():
    """**The fix's own mutation, kept as a pin** (153b).

    Production passes the project model (``cli.py``); a context without one has
    no schematic view and falls back to the PCB copy, which is the state the code
    was in before the fix. On 1.0.0 that produces 「0 0 Ω resistor(s), 2
    resistor(s) of a **non-zero** value」 — the false account — so this test fails
    if the schematic threading is ever dropped at a call site, which is the one
    way the defect can come back.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=pcb_model), EMPTY_SHELF
    )
    account = [r for r in rows if "not a single point" in r.message]
    assert len(account) == 1
    assert "0 0 Ω resistor(s), 2 resistor(s) of a **non-zero** value" in (
        account[0].message
    )
    assert "R31" not in "".join(r.message for r in rows), (
        "and the third 0R is invisible to that reading, exactly as it was before"
    )
    assert "回退 PCB 文档值" in "\n".join(account[0].evidence)


# ---------------------------------------------------------------------------
# 四、branch reachability — the two branches no fixture reaches any more
# ---------------------------------------------------------------------------


def test_the_non_zero_branch_is_reachable_and_the_pool_stays_structural():
    """A 10 kΩ bridge: reported as 「non-zero」, and a 0 Ω-only pool would miss it.

    No fixture reaches this branch after 153b (every cross-domain bridge in the
    corpus is ``0R`` on its schematic page), so the rule is handed a **synthetic
    page** whose ``R48``/``R49`` declare ``10K`` while the board and netlist stay
    1.0.0's real ones. That exercises the branch end to end through the real rule
    and shows why the pool cannot be value-filtered: a 0 Ω-only pool would report
    this board as joined by **nothing**, which is a different answer from 「not
    connected at all」 and only one of the two is 岳's 「不连」 branch.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    ctx = PcbReviewContext(
        board=board,
        pcb_model=pcb_model,
        model=_page({"R48": "10K", "R49": "10K"}),
        board_uuid="d5c055266ef55000",
    )
    rows = FocGroundTie().check_with_library(ctx, EMPTY_SHELF)
    account = [r for r in rows if "not a single point" in r.message]
    assert len(account) == 1, [r.message[:70] for r in rows]
    assert "0 0 Ω resistor(s), 2 resistor(s) of a **non-zero** value" in (
        account[0].message
    )
    assert "R48 '10K' 'GND'↔'PGND'" in account[0].message
    assert "R49 '10K' 'AGND'↔'PGND'" in account[0].message
    assert "not connected at all" not in "".join(r.message for r in rows)

    # The value-filtered pool over the same view: nothing at all.
    zeros = zero_ohm_resistors_of(
        pcb_model, EMPTY_SHELF, _page({"R48": "10K", "R49": "10K"})
    )
    assert zeros == [], (
        "a 0 Ω-only pool sees no tie here — which is why the pool is structural"
    )


def test_a_mixed_board_reports_one_0r_and_one_non_zero_bridge_together():
    """Both branches at once: ``R48`` 0 Ω, ``R49`` non-zero.

    The mixed case is what the 「several ways, one of them not 0 Ω」 account is
    for, and it also shows the single-point branch is **not** taken: one 0 Ω plus
    a non-zero bridge is not 岳's 「恰好一颗 0R」.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    ctx = PcbReviewContext(
        board=board,
        pcb_model=pcb_model,
        model=_page({"R48": "0R", "R49": "10K"}),
        board_uuid="d5c055266ef55000",
    )
    rows = FocGroundTie().check_with_library(ctx, EMPTY_SHELF)
    assert not [r for r in rows if "exactly one 0 Ω single point" in r.message]
    account = [r for r in rows if "not a single point" in r.message]
    assert len(account) == 1
    assert "1 0 Ω resistor(s) (R48 'GND'↔'PGND')" in account[0].message
    assert "1 resistor(s) of a **non-zero** value" in account[0].message
    assert "R49 '10K' 'AGND'↔'PGND'" in account[0].message


def test_the_unknown_branch_is_unaffected_by_the_view_and_never_zero():
    """A bridge whose **page** states something unreadable is UNKNOWN, not zero.

    The page is the authority here — this synthetic page *is* the drawing — so a
    value it cannot parse leaves the reading UNKNOWN even though the PCB copy
    states a number. No 0 Ω branch and no non-zero branch is claimed, and each row
    says UNKNOWN is never zero.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    ctx = PcbReviewContext(
        board=board,
        pcb_model=pcb_model,
        model=_page({"R48": "unstated?", "R49": "unstated?"}),
        board_uuid="d5c055266ef55000",
    )
    rows = FocGroundTie().check_with_library(ctx, EMPTY_SHELF)
    unknown = [r for r in rows if "no readable resistance" in r.message]
    assert len(unknown) == 2, [r.message[:70] for r in rows]
    assert all("UNKNOWN, never zero" in "\n".join(r.evidence) for r in unknown)
    assert all("两视图不一致" in "\n".join(r.evidence) for r in unknown), (
        "and both views are on the record: the copy's number is visible beside "
        "the page's unreadable declaration"
    )
    assert not [r for r in rows if "not a single point" in r.message]
    assert not [r for r in rows if "exactly one 0 Ω single point" in r.message]
