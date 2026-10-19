"""527D3 fix (第三十批之二）—— the tier gate's six measured holes, pinned.

**Why this file exists.** 527D3 gave every direct ``entry.category`` reader one
choke point (:func:`boardwise.core.partkind.declared_category`) and one way to
say *why* a class may not be read
(:func:`boardwise.core.partkind.category_verdict`), and
``tests/test_527d3_declared_category.py`` pins the three answers per read point.
What that file could **not** catch is the half the independent red team then
measured: several read points answer ``bool`` / ``float`` / ``None`` rather than
a row, so a ``candidate`` (draft) class was neither accepted nor *disclosed* —
it was **absent**. Three consequences, all of them worse than the raw read the
gate replaced, and all three reproduced before anything was changed:

* **S1** — DECAP-1 flipped its honest UNKNOWN (「a capacitor is present, its value
  cannot be established」) into a false **VIOLATION** (「no grounded capacitor
  found on net 'DECAP'」) for a net that has one, carrying a ``FindingTarget``
  into the repair path;
* **S2** — a rail left ``pcb-decap-distance``'s range **silently**, because
  ``_supply_nets`` read only ``KNOWN`` domains;
* **S3** — one report said both 「the loop was measured」 and 「the loop was not
  measured」 about the same designator, because ``found`` and ``gated`` were
  independent lists.

Three more are the same class of defect at a smaller radius: **S4** (a gated
member settling a net by netlist order), **S5** (two more silent drops) and
**S6** (a 免责 sentence asked at a tier other than the gate's, so its work order
named the wrong field). ``S7``/``S8`` were ledger/probe hygiene and are fixed in
place (``tests/test_126a_pcb_review_plumbing.py``,
``tests/test_527d3_declared_category.py``); ``S9`` was wording plus the
structured-output judgement asserted at the bottom here.

**What every test below has in common**, and the reason the second half of the
batch exists: the assertion is on the **product**, not on the gate. 「the reader
said gated」 is not the contract — 「the report speaks, and it does not lie about
the board」 is.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.partkind import CATEGORY_GATED, category_verdict
from boardwise.core.parts import (
    FACTS_TRUST_CANDIDATE,
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_VERIFIED,
    PartEntry,
    PartLibrary,
    resolve_component_facts,
)
from boardwise.rules.base import Outcome

FIXTURES = Path(__file__).parent / "fixtures"
#: The board the red team measured S3 on: 1.0.0's PCB1 carries the six
#: ``MCAC53N06Y-TP`` MOSFETs, three on the ``+24V`` bus (``Q1``/``Q3``/``Q7``) and
#: three on the switching nodes (``Q2``/``Q4``/``Q8``).
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
_FOC_FET_MPN = "MCAC53N06Y-TP"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _ldo_entry(tier: str = FACTS_TRUST_VERIFIED, **kwargs) -> PartEntry:
    return PartEntry(
        key="ic.ldo.probe",
        mpn="ACME-LDO-PROBE",
        lcsc="",
        category="ic.ldo",
        category_trust=tier,
        facts={"required_caps": [{"pin": "2", "value": "100nF"}]},
        **kwargs,
    )


def _decap_board(tier: str) -> tuple[DesignModel, PartLibrary]:
    """The S1 board: an LDO demanding a capacitor, and one capacitor that is it.

    The capacitor is deliberately the hard shape — its value is **not on the
    board** and its designator is not self-evident evidence (no MPN code, no
    chip-size footprint) — so ``looks_like_capacitor``'s routes 1 and 3 both
    fail and the shelf's class is the only signal there is. That is exactly the
    board on which the class's *tier* used to decide between UNKNOWN and
    VIOLATION.
    """
    shelf = PartLibrary(
        parts=[
            _ldo_entry(),
            PartEntry(
                key="capacitor.probe",
                mpn="",
                lcsc="C999",
                category="capacitor",
                category_trust=tier,
            ),
        ]
    )
    components = {
        "U1": Component(
            uid="u1",
            designator="U1",
            lcsc_part="",
            mpn="ACME-LDO-PROBE",
            props={},
            pins=[Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "DECAP")],
        ),
        "C9": Component(
            uid="c9",
            designator="C9",
            lcsc_part="C999",
            mpn="",
            props={},
            pins=[Pin("1", "1", "DECAP"), Pin("2", "2", "GND")],
        ),
    }
    nets = {
        "+5V": Net(name="+5V", pins=[("U1", "1")]),
        "DECAP": Net(name="DECAP", pins=[("U1", "2"), ("C9", "1")]),
        "GND": Net(name="GND", pins=[("C9", "2")]),
    }
    return DesignModel(components=components, nets=nets), shelf


def _decap_rows(model: DesignModel, shelf: PartLibrary) -> list[Outcome]:
    from boardwise.rules.decap import DecapRequiredCaps

    return [
        outcome for outcome, _severity in DecapRequiredCaps(library=shelf)._rows(model)
    ]


# ---------------------------------------------------------------------------
# S1 — a draft class must not turn a real capacitor into a VIOLATION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tier",
    [FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE],
)
def test_the_decap_verdict_is_the_same_shape_at_every_tier(tier: str):
    """S1, and the batch's own judged criterion (裁决 1).

    One board, one field changed (``category_trust``). The product has to be
    「UNKNOWN, or a row carrying a 免责 sentence」 at **every** tier — never a
    VIOLATION, never a missing row. At HEAD the draft tier produced
    ``VIOLATION WARN U1 pin2: no grounded capacitor found on net 'DECAP'``: a
    false statement about a net that carries a capacitor, and one that arrives
    with a ``FindingTarget`` (``component_ref`` / ``pin_refs`` /
    ``suggested_after``) attached, i.e. usable as the basis for 「add a
    capacitor」.
    """
    model, shelf = _decap_board(tier)
    rows = _decap_rows(model, shelf)

    assert rows, f"tier={tier}: DECAP-1 said nothing at all about this board"
    assert not [row for row in rows if row.state == "VIOLATION"], (
        f"tier={tier}: a capacitor whose class this tier may not read was "
        f"reported as absent: {[row.message for row in rows]}"
    )
    assert all(row.message.strip() for row in rows), (
        f"tier={tier}: a row with no printable sentence: {rows!r}"
    )
    unknown = [row for row in rows if row.state == "UNKNOWN"]
    assert unknown, f"tier={tier}: expected the UNKNOWN row: {rows!r}"
    # …and the UNKNOWN names the capacitor, so a reader learns the part exists.
    assert all("C9" in row.message for row in unknown), [row.message for row in unknown]


def test_the_draft_capacitor_stays_in_the_inventory_and_drives_no_number():
    """The two halves of the same reading, side by side.

    The class is **not** read (the tier gate's whole point — a draft drives no
    number), and the part is **not** dropped (the disclosure's whole point). The
    pool is where those two meet: ``C9`` is in it, and its value is still
    unknown, so the decision is ``unreadable`` rather than ``satisfied``.
    """
    from boardwise.rules.decap import (
        cap_candidates_on,
        decide_required_cap,
        looks_like_capacitor,
        same_net_capacitors_on,
    )

    model, shelf = _decap_board(FACTS_TRUST_CANDIDATE)

    assert looks_like_capacitor("C9", "", "", "C999", shelf) is False, (
        "a draft class must not answer 「is this a capacitor」 on its own"
    )
    pool = cap_candidates_on(model, "DECAP", shelf)
    assert [candidate.designator for candidate in pool] == ["C9"]
    decision = decide_required_cap("100nF", pool, shelf)
    assert decision.state == "unreadable", decision

    # The same-net half reads the same way: a draft-class capacitor drawn closed
    # on one net is a bridging part with a name, not a net that has none.
    same_net, shelf2 = _decap_board(FACTS_TRUST_CANDIDATE)
    same_net.nets["DECAP"].pins.append(("C9", "2"))
    same_net.nets.pop("GND")
    same_net.components["C9"].pins[1] = Pin("2", "2", "DECAP")
    assert [c.designator for c in same_net_capacitors_on(same_net, "DECAP", shelf2)] == [
        "C9"
    ]


# ---------------------------------------------------------------------------
# S2 — a gated rail must not leave pcb-decap-distance's range in silence
# ---------------------------------------------------------------------------


def _ldo_rail_model() -> DesignModel:
    return DesignModel(
        components={
            "U1": Component(
                uid="u1",
                designator="U1",
                lcsc_part="",
                mpn="ACME-LDO-PROBE",
                props={},
                pins=[Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "RAIL_A")],
            )
        },
        nets={
            "+5V": Net(name="+5V", pins=[("U1", "1")]),
            "RAIL_A": Net(name="RAIL_A", pins=[("U1", "2")]),
        },
    )


def _rail_shelf(tier: str) -> PartLibrary:
    return PartLibrary(
        parts=[
            PartEntry(
                key="ic.ldo.probe",
                mpn="ACME-LDO-PROBE",
                lcsc="",
                category="ic.ldo",
                category_trust=tier,
                facts={
                    "supply_pins": [{"pins": ["1"]}],
                    "required_caps": [{"pin": "2"}],
                    "ldo": {
                        "fixed_output": {"volts": 3.3, "provenance": "ds.pdf, p.3"}
                    },
                },
            )
        ]
    )


@pytest.mark.parametrize(
    "tier", [FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE]
)
def test_the_regulator_rail_stays_a_supply_net_at_every_tier(tier: str, monkeypatch):
    """S2: ``rules/pcb/distance._supply_nets`` is the rail's only gatekeeper.

    ``pcb-decap-distance`` asks it 「which nets are in range at all」 (its
    ``check`` filters on the set), so a rail missing from here is a rail the rule
    never even **asks** about — no WARN, no INFO, nothing. Before the fix a
    ``machine_verified`` or ``candidate`` class took the rail out of the set and
    said nothing anywhere: the loss of coverage was invisible.

    The second half of the ruling is about *what the rail is graded against*: an
    UNKNOWN-domain guess carries ``volts is None``, so nothing downstream can read
    a fabricated number off a class nobody signed. At the tier this rule actually
    asks (``allow_machine=True`` — a spacing threshold, 522's number line) a
    ``machine_verified`` class may still name the voltage; a **draft** may not, and
    there the rail is in range with no voltage at all.
    """
    from boardwise.core.power_domains import domain_of, infer_net_domains
    from boardwise.rules import facts as facts_module
    from boardwise.rules.pcb.distance import _supply_nets

    shelf = _rail_shelf(tier)
    model = _ldo_rail_model()
    monkeypatch.setattr(facts_module, "read_default_library", lambda: shelf)

    assert "RAIL_A" in _supply_nets(model), (
        f"tier={tier}: the regulator's output rail left pcb-decap-distance's "
        "range with no row anywhere saying so"
    )

    guesses = infer_net_domains(model, shelf, allow_machine=True)
    volts, _source, why = domain_of(guesses, "RAIL_A")
    if tier == FACTS_TRUST_CANDIDATE:
        assert volts is None, f"tier={tier}: a draft class named a voltage"
        assert why, "a rail whose domain is undetermined must say why"
    else:
        assert volts == 3.3, (
            f"tier={tier}: the tier this rule asks at still reads this class"
        )


def test_the_supply_set_is_not_widened_by_nets_nobody_mentions(monkeypatch):
    """The negative control for S2 — the fix must not add every net.

    ``infer_net_domains`` writes no entry at all for a net nothing speaks for, so
    a stray ``NET7`` stays out of the supply set. Widening to 「every net「 would
    have made ``pcb-decap-distance`` measure the whole board.
    """
    from boardwise.rules import facts as facts_module
    from boardwise.rules.pcb.distance import _supply_nets

    model = _ldo_rail_model()
    model.nets["NET7"] = Net(name="NET7", pins=[("U1", "1")])
    monkeypatch.setattr(facts_module, "read_default_library", lambda: _rail_shelf(
        FACTS_TRUST_VERIFIED
    ))

    supply = _supply_nets(model)
    assert "RAIL_A" in supply
    assert "NET7" not in supply


# ---------------------------------------------------------------------------
# S3 — a part that was measured must not also be disclaimed as unmeasured
# ---------------------------------------------------------------------------

_MPN = "ACME-FET-PROBE"


class _PlacedBoard:
    """Just enough board for :func:`power_mosfets_of`'s ``Q``-plus-bus door."""

    def __init__(self, placed: tuple[str, ...], nets=None) -> None:
        self._placed = set(placed)
        self._nets = {
            str(name): [str(des) for des in members]
            for name, members in (nets or {}).items()
        }

    def component(self, designator: str):
        return object() if designator in self._placed else None

    def net_names(self) -> list[str]:
        return sorted(self._nets)

    def net(self, name: str):
        return _PlacedNet(self._nets.get(str(name), []))


class _PlacedNet:
    def __init__(self, components: list[str]) -> None:
        self.components = list(components)


def _two_fets_one_bus() -> DesignModel:
    """``Q1`` on the bulk capacitor's net, ``Q2`` off it — same part number."""
    components = {
        "C115": Component(
            uid="c115", designator="C115", lcsc_part="", mpn="", props={},
            value="330uF",
        )
    }
    for designator, net in (("Q1", "+24V"), ("Q2", "MOTB")):
        components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            lcsc_part="",
            mpn=_MPN,
            props={"device_name": _MPN},
            pins=[Pin("1", "D", net), Pin("2", "S", "GND")],
        )
    nets = {
        "+24V": Net(name="+24V", pins=[("C115", "1"), ("Q1", "1")]),
        "MOTB": Net(name="MOTB", pins=[("Q2", "1")]),
        "GND": Net(name="GND", pins=[("Q1", "2"), ("Q2", "2")]),
    }
    return DesignModel(components=components, nets=nets)


@pytest.mark.parametrize(
    "tier", [FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE]
)
def test_the_power_fet_pool_and_the_disclaimer_never_overlap(tier: str):
    """S3 at the reader: the ``Q``-plus-bus door is independent of the class door.

    ``Q1`` sits on the bulk capacitor's net, so the designator door admits it even
    though the shelf's class is refused; ``Q2`` does not, so it is the part the
    免责 row is genuinely about. Before the fix ``Q1`` was in both lists and each
    caller wrote it a row asserting 「所以它的（体电容，功率管）环路没有量」 — right
    next to the row that measured that loop.
    """
    from boardwise.rules.pcb.foc import power_mosfets_of

    shelf = PartLibrary(
        parts=[
            PartEntry(
                key="fet.probe", mpn=_MPN, lcsc="", category="fet",
                category_trust=tier,
            )
        ]
    )
    board = _PlacedBoard(
        ("Q1", "Q2", "C115"), nets={"+24V": ("C115", "Q1"), "MOTB": ("Q2",)}
    )
    fets, gated = power_mosfets_of(board, _two_fets_one_bus(), shelf)
    measured = {designator for designator, _category, _basis in fets}
    disclaimed = {designator for designator, _category, _tier in gated}

    assert measured & disclaimed == set(), (
        f"tier={tier}: a designator the reading measured is also disclaimed as "
        f"unmeasured: measured={sorted(measured)} gated={sorted(disclaimed)}"
    )
    assert "Q1" in measured, f"tier={tier}: the bus door stopped admitting Q1"
    if tier != FACTS_TRUST_VERIFIED:
        assert disclaimed == {"Q2"}, (
            f"tier={tier}: the refused, off-bus FET lost its 免责 row: {sorted(disclaimed)}"
        )


#: 170's shape: one parse per fixture path, shared by the tests below.
_PROJECTS: dict[Path, object] = {}
_BOARDS: dict[Path, object] = {}


def _designator_of(message: str) -> str:
    """The designator a 免责 row is about, read off the sentence it opens with.

    ``category_gate_finding`` builds a row with **no** :class:`FindingTarget` —
    deliberately, because the row asserts nothing about the drawing and a target
    is what a repair hangs off. Its subject is still the part, and it is written
    as the first token of the message (``Q2: 货架把它分类为 …``).
    """
    match = re.match(r"^([A-Za-z]+\d+)\s*[:：]", message)
    return match.group(1) if match else ""


def _paired_fet_of(message: str) -> str:
    """The power FET in R20's 「loop」 sentence (``… ↔ Q1: polygon area …``).

    R20's ``FindingTarget`` anchors on the **capacitor** — the part a repair would
    move — so the FET the row is about is the one after the arrow.
    """
    match = re.search(r"↔\s*([A-Za-z]+\d+)", message)
    return match.group(1) if match else ""


def _fixture(path: Path):
    """``(board, model)`` for one fixture archive, parsed once (the parse is the
    expensive half and three tests below read the same board)."""
    if path not in _BOARDS:
        from boardwise.parsers.epro2_model import build_design_model
        from boardwise.parsers.epru import extract_board, load_epro2_source

        source = load_epro2_source(path)
        document = source.documents_of_type("PCB")[0]
        _BOARDS[path] = extract_board(document, source.footprints(), source.stats)
        _PROJECTS[path] = build_design_model(source, document)
    return _BOARDS[path], _PROJECTS[path]


def _reclassified(shared: PartLibrary, mpn: str, category: str, tier: str) -> PartLibrary:
    """The factory shelf with **one** MPN's entry moved to another tier.

    ``dataclasses.replace`` rather than a hand-built ``PartEntry``: every other
    field (the facts, the citation record, the params) has to survive, or the
    test would be measuring a different part than the shelf describes.
    """
    return PartLibrary(
        parts=[
            dataclasses.replace(entry, category=category, category_trust=tier)
            if (entry.mpn or "").upper() == mpn.upper()
            else entry
            for entry in shared.parts
        ]
    )


@pytest.mark.parametrize(
    "tier", [FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE]
)
def test_one_report_never_says_both_measured_and_not_measured(tier: str):
    """S3 on the real board the red team measured (裁决 2's judged criterion).

    毕设FOC 1.0.0's PCB1 carries six ``MCAC53N06Y-TP`` FETs; three
    (``Q1``/``Q3``/``Q7``) sit on the ``+24V`` bus that ``C115`` also sits on.
    With the shelf entry moved to a refused tier, the fix's contract is: R20
    either measures a designator's loop **or** writes it a 免责 row — never both.
    """
    from boardwise.core.parts import load_parts
    from boardwise.rules.pcb.base import PcbReviewContext
    from boardwise.rules.pcb.foc import FocPowerLoopArea, power_mosfets_of
    from boardwise.rules.facts import default_library_path

    board, model = _fixture(FOC_100)
    shelf = _reclassified(
        load_parts(default_library_path()), _FOC_FET_MPN, "fet", tier
    )
    entry, _matched = resolve_component_facts(shelf, model.components["Q1"])
    assert entry is not None and entry.category == "fet", "the fixture lost its FET entry"

    _fets, gated = power_mosfets_of(board, model, shelf)
    disclaimed = {designator for designator, _category, _tier in gated}

    context = PcbReviewContext(board=board, board_title="PCB1", pcb_model=model)
    findings = FocPowerLoopArea().check_with_library(context, shelf)

    # The measured row's subject is 「bulk capacitor ↔ power FET」, and its
    # `FindingTarget` anchors on the **capacitor** (the repair hangs off the part
    # that would move), so the FET this file is about is read off the sentence.
    measured = {
        _paired_fet_of(finding.message)
        for finding in findings
        if "high-current loop" in finding.message
    }
    measured.discard("")
    # The 免责 row is `category_gate_finding`'s, and it carries **no**
    # `FindingTarget` on purpose (it asserts nothing about the drawing, so there is
    # nothing to repair); its designator is the one the sentence opens with.
    disclaiming = {
        _designator_of(finding.message)
        for finding in findings
        if "没有量" in finding.message
    }
    disclaiming.discard("")

    assert not (measured & disclaiming), (
        f"tier={tier}: one report measured and disclaimed the same designator: "
        f"{sorted(measured & disclaiming)}"
    )
    # The rows that assert a missing measurement are exactly the parts the reader
    # refused **and** did not admit through the designator door.
    assert disclaiming == disclaimed, (
        f"tier={tier}: the 免责 rows and the reader's own list disagree: "
        f"rows={sorted(disclaiming)} reader={sorted(disclaimed)}"
    )
    if tier == FACTS_TRUST_VERIFIED:
        assert measured and not disclaimed, (
            "a signed class must drive the shelf door and owe no 免责 row"
        )


def test_a_measured_designator_gets_no_disclaimer_through_the_return_path_too():
    """The same invariant on R1b, which shares :func:`power_mosfets_of`.

    R1b (``pcb-foc-return-path``) builds its 未识别清单 from the same reader plus
    two more doors, and writes the same 「没有量」 sentence. Filtering inside the
    reader is what keeps the two callers from having to remember.
    """
    from boardwise.core.parts import load_parts
    from boardwise.rules.facts import default_library_path
    from boardwise.rules.pcb.base import PcbReviewContext
    from boardwise.rules.pcb.focground import FocReturnPath

    board, model = _fixture(FOC_100)
    shelf = _reclassified(
        load_parts(default_library_path()), _FOC_FET_MPN, "fet", FACTS_TRUST_MACHINE
    )
    context = PcbReviewContext(board=board, board_title="PCB1", pcb_model=model)
    findings = FocReturnPath().check_with_library(context, shelf)

    disclaimed: set[str] = set()
    for finding in findings:
        if "没有量" not in finding.message:
            continue
        designator = _designator_of(finding.message)
        if designator:
            disclaimed.add(designator)

    # ``Q1``/``Q3``/``Q7`` are the three the bus door measures; none of them may
    # appear in a 「没有量」 row.
    assert not ({"Q1", "Q3", "Q7"} & disclaimed), (
        f"R1b disclaimed a designator it measured: {sorted(disclaimed)}"
    )
    # …while the three off-bus FETs of the same part number are exactly the ones
    # the tier gate refused and nothing else admitted.
    assert {"Q2", "Q4", "Q8"} <= disclaimed, sorted(disclaimed)


# ---------------------------------------------------------------------------
# S4 — a gated member must not settle a net by netlist order
# ---------------------------------------------------------------------------

_OPAMP_MPNS = {"U1": "ACME-OPA-MACHINE", "U2": "ACME-OPA-SIGNED"}


class _StubRule:
    """Enough of a ``FactsRule`` for :func:`_opamp_output`'s two questions."""

    REQUIRES_HUMAN_VERIFIED = True

    def __init__(self, library: PartLibrary) -> None:
        self.library = library

    def entry_for(self, component):
        entry, _matched = resolve_component_facts(self.library, component)
        return entry


def _two_opamp_net(order: tuple[str, ...]) -> tuple[DesignModel, PartLibrary]:
    """One net, two amplifiers — one signed, one not — in ``order``.

    ``facts.output_pins`` names the output pin on the **signed** one, so the rule
    has a definite answer available on this net; the unsigned one has no such
    fact (which is why it could not answer even if its class were readable).
    """
    shelf = PartLibrary(
        parts=[
            PartEntry(
                key="ic.opamp.machine", mpn=_OPAMP_MPNS["U1"], lcsc="",
                category="ic.opamp", category_trust=FACTS_TRUST_MACHINE,
            ),
            PartEntry(
                key="ic.opamp.signed", mpn=_OPAMP_MPNS["U2"], lcsc="",
                category="ic.opamp", category_trust=FACTS_TRUST_VERIFIED,
                facts={"output_pins": ["2"]},
            ),
        ]
    )
    components = {
        designator: Component(
            uid=designator.lower(),
            designator=designator,
            lcsc_part="",
            mpn=_OPAMP_MPNS[designator],
            props={},
            pins=[Pin("2", "N", "BIAS")],
        )
        for designator in ("U1", "U2")
    }
    nets = {
        "BIAS": Net(
            name="BIAS",
            pins=[(designator, "2") for designator in order],
        )
    }
    return DesignModel(components=components, nets=nets), shelf


def test_the_opamp_answer_does_not_depend_on_the_netlist_order():
    """S4: remembering the gated member and continuing the walk (裁决 3).

    ``U1``'s class is machine-granted and this rule draws a conclusion, so ``U1``
    may not decide. Before the fix the walk **returned** on the first gated member
    it met, so the same electrically identical net answered ``U2`` when the
    netlist listed ``U2`` first and UNKNOWN when it listed ``U1`` first — a
    verdict chosen by member order.
    """
    from boardwise.rules.archclosure import _opamp_output

    answers = {}
    for order in (("U1", "U2"), ("U2", "U1")):
        model, shelf = _two_opamp_net(order)
        answer = _opamp_output(model, _StubRule(shelf), "BIAS")
        assert answer is not None, order
        designator, _name, because, gated = answer
        answers[order] = (designator, bool(because), gated)

    assert answers[("U1", "U2")][0] == answers[("U2", "U1")][0] == "U2", answers
    assert answers[("U1", "U2")][1] and answers[("U2", "U1")][1], answers
    assert not answers[("U1", "U2")][2] and not answers[("U2", "U1")][2], answers


def test_the_gated_answer_is_still_given_when_no_signed_member_exists():
    """The other half of 裁决 3: the walk finishing with nothing readable still
    owes the UNKNOWN, and it names the review rather than going silent."""
    from boardwise.rules.archclosure import _opamp_output

    model, shelf = _two_opamp_net(("U1", "U2"))
    # Drop the signed amplifier's output-pin fact … and its signature.
    shelf = PartLibrary(
        parts=[
            dataclasses.replace(entry, category_trust=FACTS_TRUST_MACHINE)
            for entry in shelf.parts
        ]
    )
    designator, _name, because, gated = _opamp_output(model, _StubRule(shelf), "BIAS")
    assert designator == "U1"
    assert not because
    assert gated, "a net with only an unsignable class owes the review sentence"


# ---------------------------------------------------------------------------
# S5 — the two remaining silent drops
# ---------------------------------------------------------------------------


def _resistor_board(tier: str) -> tuple[DesignModel, PartLibrary]:
    shelf = PartLibrary(
        parts=[
            PartEntry(
                key="resistor.probe", mpn=_MPN, lcsc="", category="resistor",
                category_trust=tier,
            )
        ]
    )
    component = Component(
        uid="u1", designator="U1", lcsc_part="", mpn=_MPN,
        props={"device_name": _MPN}, pins=[],
    )
    return DesignModel(components={"U1": component}, nets={}), shelf


@pytest.mark.parametrize(
    "tier", [FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE]
)
def test_a_shelf_named_resistor_always_gets_a_row_from_value_mpn_match(tier: str):
    """S5(a): ``rules/params._kind_of``'s ``None`` meant two things at once.

    ``ValueMpnMatch`` skipped them with the same ``continue``: 「nothing names this
    part's kind」 (a mounting screw — correctly silent) and 「the shelf names it and
    this tier may not read the name」 (a real resistor, silently gone). The board
    below has no value field, so the unit cannot answer either, and the only
    thing that can speak is the class — which is why the row has to exist.
    """
    from boardwise.rules.params import ValueMpnMatch

    model, shelf = _resistor_board(tier)
    rows = [
        outcome
        for outcome, _severity in ValueMpnMatch(library=shelf)._rows(model)
    ]
    assert rows, f"tier={tier}: the part vanished from value-vs-MPN"
    assert all(row.message.strip() for row in rows), rows


def test_a_gated_diode_class_gets_a_row_when_the_designator_door_is_shut():
    """S5(b): ``paramspec.TvsStandoffRail``'s two doors, neither of them open.

    ``U1`` here carries a ``diode`` class nobody signed and no ``D`` designator,
    so the shelf door is refused *and* the designator door does not answer. Both
    failed, and the rule used to ``return None`` — the part disappeared from the
    TVS selection rules without a word. With the fix the part still gets no
    verdict (correct: the class may not be read) but it does get a row naming the
    review that would let it be judged.
    """
    from boardwise.rules.paramspec import TvsStandoffRail

    shelf = PartLibrary(
        parts=[
            PartEntry(
                key="diode.probe", mpn=_MPN, lcsc="", category="diode",
                category_trust=FACTS_TRUST_CANDIDATE, params={"Type": "TVS"},
            )
        ]
    )
    component = Component(
        uid="u1", designator="U1", lcsc_part="", mpn=_MPN,
        props={"device_name": _MPN},
        pins=[Pin("1", "A", "RAIL_A"), Pin("2", "K", "GND")],
    )
    model = DesignModel(
        components={"U1": component},
        nets={
            "RAIL_A": Net(name="RAIL_A", pins=[("U1", "1")]),
            "GND": Net(name="GND", pins=[("U1", "2")]),
        },
    )
    rows = [outcome for outcome, _severity in TvsStandoffRail(library=shelf)._rows(model)]
    assert rows, "the gated diode class vanished from the TVS rules"
    assert all("档位" in (row.missing_fact or "") for row in rows), rows
    assert all("diode" in row.message for row in rows), [row.message for row in rows]


def test_a_gated_neighbour_reaches_the_caller_as_a_reason():
    """S5(c): ``independent_rail_price``'s third slot (裁决 1).

    The reader may not use a refused class to price a rail — that is the gate.
    What it must **not** do is leave through the same door as 「there is no other
    regulator here」, because the two are different work orders: one is answered by
    writing a contract, the other by signing a class.
    """
    from boardwise.core.power_domains import infer_net_domains
    from boardwise.rules.paramspec import independent_rail_price, sel_rail_voltage

    model = _ldo_rail_model()
    for tier, expected_volts in (
        (FACTS_TRUST_VERIFIED, 3.3),
        (FACTS_TRUST_MACHINE, 3.3),
        (FACTS_TRUST_CANDIDATE, None),
    ):
        shelf = PartLibrary(
            parts=[
                dataclasses.replace(
                    _rail_shelf(tier).parts[0],
                    params={"Output Voltage": "3.3V"},
                )
            ]
        )
        volts, source, gated = independent_rail_price(
            model, shelf, "RAIL_A", subject="U9"
        )
        assert volts == expected_volts, (tier, volts, source)
        if tier == FACTS_TRUST_CANDIDATE:
            assert gated, "a refused neighbour's class must say so"
            assert "draft" in gated, gated
            # …and the caller's own ``why_not`` carries it, rather than the
            # 「no source names this voltage」 a board with no regulator gets.
            _v, _s, why = sel_rail_voltage(
                None,
                infer_net_domains(model, shelf, allow_machine=True),
                "RAIL_A",
                subject="U9",
                model=model,
                library=shelf,
            )
            assert "档位" in why, why
        else:
            assert not gated, (tier, gated)


# ---------------------------------------------------------------------------
# S6 — the sentence is asked at the gate's own tier
# ---------------------------------------------------------------------------


def test_the_disclaimer_names_the_field_that_actually_blocked_the_rule():
    """S6 (裁决 4): judge and sentence must ask the same question.

    ``LdoDissipation.REQUIRES_HUMAN_VERIFIED`` is ``False`` — ``P = (Vin - Vout) x
    I`` is a number — so the rule **does** read machine-verified parameters;
    asking the sentence at ``allow_machine=False`` picked the **facts** branch for
    an entry whose parameters a human had signed and whose *class* was the draft,
    and told the reader to go and sign ``facts_trust``. The work order pointed at
    the wrong field.
    """
    from boardwise.core.designintent import DesignIntent, IntentSource
    from boardwise.rules.railratings import LdoDissipation

    shelf = PartLibrary(
        parts=[
            PartEntry(
                key="ic.ldo.probe",
                mpn="ACME-LDO-PROBE",
                lcsc="",
                category="ic.ldo",
                facts_trust=FACTS_TRUST_MACHINE,
                category_trust=FACTS_TRUST_CANDIDATE,
                facts={
                    "supply_pins": [{"pins": ["1"]}],
                    "required_caps": [{"pin": "2"}],
                    "ldo": {"max_dissipation_mw": 500},
                },
            )
        ]
    )
    rule = LdoDissipation(
        library=shelf,
        intent=IntentSource(
            document=DesignIntent(rails=[]), path="mem://527d3fix-contract.json"
        ),
    )
    rows = rule._rows(_ldo_rail_model())
    unknown = [outcome for outcome, _severity in rows if outcome.state == "UNKNOWN"]
    assert unknown, rows
    message = unknown[0].message
    assert "category" in message and "draft" in message, message
    # The **facts** branch — the one that tells the reader to sign `facts_trust`
    # and declares the rule needs a human — must not be the sentence here.
    assert "machine-verified and this rule needs a human" not in message, (
        "the row is sending the reader to sign the half that was already signed: "
        + message
    )


# ---------------------------------------------------------------------------
# S9(b) — the third state on the structured side of the architecture walk
# ---------------------------------------------------------------------------


def test_the_architecture_section_carries_the_gated_classifications():
    """S9(b): ``gated_classifications`` had exactly one call site, the markdown.

    ``_render_board`` fills a per-board dict that is the machine half of the
    ``arch`` result — 053 §2.2's own framing is that a consumer of that section
    never parses the prose (the slot join key exists for precisely that). A third
    state that only exists in the markdown is therefore invisible to a machine
    consumer, so the list travels in the board record too.
    """
    from boardwise.core.architecture import generate_architecture

    component = Component(
        uid="u1", designator="U1", lcsc_part="", mpn=_MPN,
        props={"device_name": _MPN},
        pins=[Pin("1", "VDD", "+3V3"), Pin("2", "NRST", "NRST"),
              Pin("3", "BOOT0", "BOOT0"), Pin("4", "PF0", "OSC1")],
    )
    model = DesignModel(
        components={"U1": component},
        nets={
            "+3V3": Net(name="+3V3", pins=[("U1", "1")]),
            "NRST": Net(name="NRST", pins=[("U1", "2")]),
            "BOOT0": Net(name="BOOT0", pins=[("U1", "3")]),
            "OSC1": Net(name="OSC1", pins=[("U1", "4")]),
        },
    )
    signed = generate_architecture(
        model,
        library=PartLibrary(
            parts=[PartEntry(key="ic.mcu.probe", mpn=_MPN, lcsc="", category="ic.mcu")]
        ),
    )
    assert signed.section["boards"][0]["gatedClassifications"] == []

    gated = generate_architecture(
        model,
        library=PartLibrary(
            parts=[
                PartEntry(
                    key="ic.mcu.probe", mpn=_MPN, lcsc="", category="ic.mcu",
                    category_trust=FACTS_TRUST_MACHINE,
                )
            ]
        ),
    )
    record = gated.section["boards"][0]
    assert record["gatedClassifications"] == [
        {"designator": "U1", "category": "ic.mcu"}
    ]
    # …and the prose still says it, unchanged: the two views agree.
    assert "分类档位不足" in gated.markdown


def test_the_gated_class_verdict_is_still_the_gate_not_the_output():
    """A guard on the whole file: nothing here widened the gate itself.

    ``category_verdict``'s answers are what 527D3 pinned; the fix moved only what
    the *callers* do with the third one. A regression that 「disclosed」 the draft
    by letting it through would satisfy several assertions above and must not.
    """
    from boardwise.core.partkind import declared_category

    draft = PartEntry(
        key="any", mpn=_MPN, lcsc="", category="capacitor",
        category_trust=FACTS_TRUST_CANDIDATE,
    )
    assert (
        category_verdict(draft, frozenset({"capacitor"}), allow_machine=True)
        == CATEGORY_GATED
    )
    assert declared_category(draft, allow_machine=True) is None
