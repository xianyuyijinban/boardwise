"""Task 164a: the FOC rules' **view truth** — schematic declaration first, PCB copy only as a fallback.

岳's ruling (tasks/158) is that a PCB document view's ``Value`` field is a
**systematic placeholder**, not data: measured, 毕设FOC 1.1.0's PCB1 contradicts
the schematic page on 45 of its 105 placed parts (23 read ``100nF`` and 20 read
``10K`` whatever the page says), and 1.0.0's PCB1 reads 37 the same way. 153b
already established the fix for ``pcb-foc-ground-tie``'s 0 Ω test
(:func:`~boardwise.rules.pcb.focground.schematic_board_of` +
:func:`~boardwise.rules.pcb.focground._value_ohms`) and this batch is the rest of
the same module family reading through the same channel:

* **F6** — ``pcb-foc-ground-tie``'s **bulk electrolytic pool** still read
  ``ctx.pcb_model``'s copies through :func:`~boardwise.rules.pcb.foc.bulk_capacitors_of`
  while the 0 Ω half of the same rule already read the page: one module, two
  value口径.
* **F8-foc** — the same pool as ``pcb-foc-power-loop-area`` (R20) reads it, and as
  ``pcb-foc-return-path`` (R5) reads it to decide 「which nets sit on a
  power-stage part」.
* **foc-decap-proximity** (R16) — its ``declared value`` read.
* **F7** — ``pcb-regulator-fb-placement`` recognised a **divider leg** by
  ``parse_resistance_ohms(copy) > 0``, so 1.0.0's schematic ``0R`` parts (the
  copy says ``10K``) were admitted as legs.
* **D1** — ``all_zero_ohm_parts_of``'s pin fallback could answer a single-ground-
  pin part with **the same pin twice**, printing 「GND↔GND」 on the ledger.
* **D2** — ``split_ground_domains`` sieved with ``core.model.is_ground_net``
  (which did not carry ``EARTH`` then) *before* asking ``domain_of`` (which does), so
  a bare ``EARTH`` net vanished from every domain without a word. 171 put ``EARTH``
  in ``core.model.GROUND_NET_PREFIXES``, so the sieve knows the name itself now and
  the union ``focground`` sieves with is redundant for it (the module keeps the
  union for ``P_GND`` / ``POWER_GND``, which core does not claim).

**What this file pins, and what it deliberately does not.**

* Every value assertion is about **which view** a number came from, so the
  divergence sentence 「原理图 X / PCB 文档 Y」 is asserted on the row, not merely
  the number.
* The **netlist** reads (pin nets, net membership, geometry attribution) stay on
  ``ctx.pcb_model`` and are pinned as *staying*: 131c's whole point was that the
  board's own net names must be used where the geometry is measured (the
  schematic calls a wire ``NET11`` where the board calls it ``$1N66612``), and a
  value fix must not drag the netlist with it.
* The 162a/162b geometry truths (which pads are where, which nets carry which
  copper) are **not** touched: every test here reads values, identifications and
  sentences, never a geometry pin.

All fixtures are read-only; nothing opens an editor or a daemon.
"""

from __future__ import annotations

from pathlib import Path

from boardwise.core.geometry import BoardGeometry, NetGeometry
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.core.parts import PartLibrary, load_parts
from boardwise.core.values import parse_capacitance_farads
from boardwise.engines.pcbreview import _pcb_documents, run_pcb_review
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import extract_board, load_epro2_source
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.facts import default_library_path
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.fbplacement import (
    RegulatorFbPlacement,
    _resistors,
    fb_dividers,
)
from boardwise.rules.pcb.foc import (
    FocDecapProximity,
    FocPowerLoopArea,
    _value_farads,
    bulk_capacitors_of,
    power_mosfets_of,
    schematic_page_of,
)
from boardwise.rules.pcb.focground import (
    all_zero_ohm_parts_of,
    domain_of,
    split_ground_domains,
    _value_ohms,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"

#: An **empty** shelf, not ``None``: the rules' documented ``library=None``
#: contract degrades to an empty shelf, and ``core.parts.find_facts`` dereferences
#: its argument. Several tests here want the *narrowest* reading (designator
#: family only), which is exactly the empty shelf.
EMPTY_SHELF = PartLibrary()


def _shelf() -> PartLibrary:
    return load_parts(default_library_path())


_PROJECTS: dict[Path, object] = {}


def _project(path: Path):
    project = _PROJECTS.get(path)
    if project is None:
        project = _PROJECTS[path] = build_project_model(path)
    return project


def _pcb_view(path: Path, title: str = "PCB1"):
    """``(board, netlist view)`` for one PCB document of a fixture."""
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
                extract_board(
                    document,
                    source.footprints(),
                    source.stats,
                    source.footprint_artwork(),
                ),
                build_design_model(source, document),
            )
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


def _schematic_page(path: Path, title: str = "PCB1"):
    """The schematic page this PCB document declares, off ``META.board``."""
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


def _page(
    values: dict[str, str],
    pins: dict[str, list[tuple[str, str, str]]] | None = None,
) -> DesignModel:
    """A stand-in schematic page: ``designator -> Value`` (and optional pins).

    A :class:`DesignModel` with **no** ``boards`` is its own page as far as
    :func:`~boardwise.rules.pcb.focground.schematic_board_of` is concerned, which
    is what lets a test hand a rule a page whose declarations it controls while
    the board and the netlist stay the fixture's real ones.

    ``pins`` exists so a test can give the page **schematic-style** net names
    (``NET11``) and prove the rule does *not* read nets off this view.
    """
    made = {}
    for designator, value in values.items():
        made[designator] = Component(
            uid=designator,
            designator=designator,
            value=value,
            pins=[
                Pin(number=number, name=name, net=net)
                for number, name, net in (pins or {}).get(designator, [])
            ],
        )
    return DesignModel(components=made)


def _placed(
    designator: str, value: str, pins: list[tuple[str, str, str]]
) -> Component:
    return Component(
        uid=designator,
        designator=designator,
        value=value,
        pins=[Pin(number=n, name=nm, net=net) for n, nm, net in pins],
    )


def _evidence(row) -> str:
    return "\n".join(row.evidence)


# ---------------------------------------------------------------------------
# 一、the value view itself — the chain focground's ``_value_ohms`` established
# ---------------------------------------------------------------------------


def test_every_rule_resolves_the_same_page_off_the_same_board_link():
    """The channel's root: ``schematic_page_of`` walks the **declared** board link.

    Four rules in two modules now read through it, so it is worth pinning that it
    answers with *this document's own* page on a real fixture (1.0.0's PCB1 →
    ``Board1``) and with ``None`` — the ordinary 「no schematic view」 — for a
    context the runner never wired. ``None`` is what makes the fallback paths
    expressible at all: a rule handed no page must still answer, and say so.
    """
    board, model = _pcb_view(FOC_100)
    uuid = next(
        doc_uuid
        for doc_title, doc_uuid, _doc in _pcb_documents(load_epro2_source(FOC_100))
        if doc_title == "PCB1"
    )
    ctx = PcbReviewContext(
        board=board,
        board_title="PCB1",
        model=_project(FOC_100),
        pcb_model=model,
        board_uuid=uuid,
    )
    page = schematic_page_of(ctx)
    assert page is not None and page is _schematic_page(FOC_100), (
        "the page is this document's own, resolved off META.board"
    )
    assert str(page.components["R48"].value) == "0R"

    # No project model: 「no schematic view for this document」, not an error.
    assert schematic_page_of(PcbReviewContext(board=board, pcb_model=model)) is None
    # A link that matches no board resolves to nothing rather than to board 0.
    assert (
        schematic_page_of(
            PcbReviewContext(
                board=board,
                pcb_model=model,
                model=_project(FOC_100),
                board_uuid="00000000-0000-0000-0000-000000000000",
            )
        )
        is None
    )
    # A synthetic page (a model with no ``boards``) is its own page.
    synthetic = _page({"C1": "330uF"})
    assert schematic_page_of(
        PcbReviewContext(board=board, pcb_model=model, model=synthetic)
    ) is synthetic


def test_the_two_modules_share_one_value_channel_and_one_sentence():
    """foc.py's reader is the **same** reading, not a second one.

    ``_value_ohms`` (focground, 153b) and ``_value_farads`` (foc.py, this batch)
    answer the same three cases with the same sentences — asserted directly, so a
    later batch cannot quietly give the module family two口径 again (which is
    exactly the F6 defect: one half of R1b reading the page and the other half
    reading the copy).
    """
    placed = _placed("C1", "330uF", [("1", "A", "+24V"), ("2", "B", "PGND")])
    page = _page({"C1": "47uF"})

    ohms = _value_ohms(placed, page.components["C1"])
    farads = _value_farads(placed, page.components["C1"])
    assert farads.value == "47uF" and farads.schematic_value == "47uF"
    assert farads.pcb_value == "330uF"
    assert farads.basis == ohms.basis, (
        "the divergence sentence is one sentence across the module family: "
        f"{ohms.basis!r}"
    )
    assert "两视图不一致" in farads.basis and "PCB 文档" in farads.basis

    # the fallback case, same wording as 153b's
    unstated = _page({"C1": ""})
    fallback = _value_farads(placed, unstated.components["C1"])
    assert fallback.value == "330uF" and "回退 PCB 文档值" in fallback.basis


def test_the_bulk_pool_reads_the_schematic_page_in_both_directions():
    """F6, on the pool itself: the page moves a part **in** and **out**.

    A copy-only pool cannot tell these two apart, and both directions matter —
    「the page promotes a part the copy calls small」 and 「the page demotes a part
    the copy calls bulk」 are the same fact read twice.
    """
    model = DesignModel(
        components={
            "C1": _placed("C1", "330uF", [("1", "A", "+24V"), ("2", "B", "PGND")]),
            "C2": _placed("C2", "47uF", [("1", "A", "+24V"), ("2", "B", "PGND")]),
        }
    )
    page = _page({"C1": "47uF", "C2": "330uF"})

    copy_pool = {des for des, _v, _f in bulk_capacitors_of(model)}
    assert copy_pool == {"C1"}, "the copies put C1 over the floor and C2 under it"

    page_pool = {
        des: (value, farads) for des, value, farads in bulk_capacitors_of(model, None, page)
    }
    assert set(page_pool) == {"C2"}, page_pool
    assert page_pool["C2"][0] == "330uF"
    assert page_pool["C2"][1] == 330e-6


def test_the_bulk_pool_falls_back_to_the_pcb_copy_when_the_page_states_nothing():
    """The fallback is real and needed — ROBOT's ``R8`` shape, on a capacitor.

    毕设FOC 1.0.0's ``C115``/``C116`` are the measured instance: the page states
    no value at all and the copy's ``330uF`` is the only declaration there is.
    """
    model = DesignModel(
        components={"C1": _placed("C1", "330uF", [("1", "A", "+24V"), ("2", "B", "PGND")])}
    )
    view = _value_farads(model.components["C1"], _page({}).components.get("C1"))
    assert view.value == "330uF" and view.schematic_value == ""
    assert "回退 PCB 文档值" in view.basis
    assert [des for des, _v, _f in bulk_capacitors_of(model, None, _page({}))] == ["C1"]


def test_an_unreadable_schematic_value_is_not_rescued_by_the_copy():
    """The refusal 153b established, kept for capacitance.

    Letting the copy answer when the page states something unreadable is the
    same invention facing the other way: it would promote a part into the bulk
    pool out of the view this fix demotes.
    """
    model = DesignModel(
        components={"C1": _placed("C1", "330uF", [("1", "A", "+24V"), ("2", "B", "PGND")])}
    )
    page = _page({"C1": "只看图不看值"})
    view = _value_farads(model.components["C1"], page.components["C1"])
    assert view.value == "只看图不看值" and view.farads is None
    assert bulk_capacitors_of(model, None, page) == []
    assert parse_capacitance_farads("只看图不看值") is None


def test_a_schematic_value_with_a_trailing_rating_is_read_by_its_leading_token():
    """llc's measured shape: the page writes ``330uF 400V``.

    The shared grammar used to require the unit to **end** the field, so this rule
    read the field's **leading token** itself — the piece ``core.values._too_long``
    already declares the decoders read — and the row says it did so. 171 moved that
    read into the reader (:func:`~boardwise.core.values.parse_capacitance_farads`,
    one verdict one implementation, 071 §2), so the line that pinned the *gap* now
    pins the *reading*: the number the rule produced by hand is the number core
    states, and the row's sentence is unchanged.
    """
    assert parse_capacitance_farads("330uF 400V") == 330e-6, "171 closed the gap"
    assert parse_capacitance_farads("330uF") == 330e-6

    model = DesignModel(
        components={"C1": _placed("C1", "330uF", [("1", "A", "DC+"), ("2", "B", "DC-")])}
    )
    page = _page({"C1": "330uF 400V"})
    view = _value_farads(model.components["C1"], page.components["C1"])
    assert view.value == "330uF 400V" and view.farads == 330e-6
    assert "'330uF'" in view.basis and "首个词" in view.basis
    assert [des for des, _v, _f in bulk_capacitors_of(model, None, page)] == ["C1"]


def test_llc_keeps_its_two_bulk_electrolytics_under_the_page_reading():
    """The acceptance guard for the flip: llc's real 330 µF pair stays in.

    Read off the **fixture's own two views** (no rule): the page says
    ``330uF 400V`` and the copy says ``330uF``, so the page is the declaration
    judged on and the value it yields is 330 µF either way.
    """
    _board, model = _pcb_view(LLC)
    page = _schematic_page(LLC)
    assert str(page.components["C3"].value) == "330uF 400V"
    assert str(model.components["C3"].value) == "330uF"

    pool = {des: value for des, value, _f in bulk_capacitors_of(model, None, page)}
    assert pool == {"C3": "330uF 400V", "C4": "330uF 400V"}, pool


# ---------------------------------------------------------------------------
# 二、F6 — R1b's bulk pool and its evidence line
# ---------------------------------------------------------------------------


def test_r1b_bulk_pool_evidence_names_the_view_it_read():
    """F6's evidence half: the bulk pool line says which view each value came from.

    1.0.0's ``C115``/``C116`` are the page-states-nothing case, so the line says
    it fell back to the PCB document's copy; and the 0 Ω half of the same row
    already carried 153b's sentence — the two are now read through one口径.
    """
    findings, _section = run_pcb_review(FOC_100, model=_project(FOC_100))
    rows = [f for f in findings if f.rule_id == "pcb-foc-ground-tie"]
    assert rows
    text = "\n".join(_evidence(row) for row in rows)
    assert "C115" in text and "C116" in text, "the bulk pool is on the row"
    assert "原理图声明优先，PCB 文档值仅作回退" in text
    assert "原理图页未写该值，**回退 PCB 文档值**" in text, (
        "1.0.0's bulk pair: the page states no value, so the copy is the "
        "fallback — and the row has to say so"
    )


# ---------------------------------------------------------------------------
# 三、foc-decap-proximity (R16) — the declared value
# ---------------------------------------------------------------------------


def test_decap_proximity_reports_the_schematic_declared_value():
    """R16's ``declared value`` comes from the page, with both views on the row.

    毕设FOC 1.0.0's ``U10`` is decoupled by ``C22`` (page and copy agree: 1 µF),
    so the page is overridden with a divergent value here — the mechanism is what
    is being pinned, and the production answer is pinned by
    ``test_decap_proximity_keeps_the_board_netlist_for_pins_and_candidates``.
    """
    board, model = _pcb_view(FOC_100)
    page = _page({"C22": "2.2uF"})
    ctx = PcbReviewContext(board=board, board_title="PCB1", model=page, pcb_model=model)
    rows = FocDecapProximity().check_with_library(ctx, _shelf())
    rows = [r for r in rows if r.target.component_ref == "C22"]
    assert len(rows) == 1, [r.target.component_ref for r in rows]
    row = rows[0]
    assert "declared value '2.2uF'" in row.message, row.message
    assert "2.2 µF" in row.message, "the capacitance figure follows the page"
    assert "原理图 '2.2uF' / PCB 文档 '1uF'" in _evidence(row), _evidence(row)


def test_decap_proximity_keeps_the_board_netlist_for_pins_and_candidates():
    """The value fix must **not** drag the netlist with it (131c's lesson).

    A page that names the same pins ``NET11``/``NET12`` changes nothing about
    this rule: the supply net, the bypass candidates and the pin numbers are read
    off ``ctx.pcb_model``, because that is the view the geometry was measured in
    (the schematic's ``NET11`` is the board's ``$1N66612``). Pinned on the
    **production** run, so the two rows below are what a reader gets.
    """
    findings, _section = run_pcb_review(FOC_100, model=_project(FOC_100))
    rows = [f for f in findings if f.rule_id == "pcb-foc-decap-proximity"]
    assert rows
    for row in rows:
        assert row.target.net_refs, row.message
        for net in row.target.net_refs:
            assert net.startswith("$1N") or net in ("+24V",), (net, row.message)
        assert "NET11" not in row.message and "NET11" not in _evidence(row)

    # And the same through a synthetic page carrying schematic-style pins: the
    # page's own pin nets are not read.
    board, model = _pcb_view(FOC_100)
    page = _page(
        {"C22": "2.2uF"},
        pins={"C22": [("1", "A", "NET11"), ("2", "B", "NET12")]},
    )
    ctx = PcbReviewContext(board=board, board_title="PCB1", model=page, pcb_model=model)
    synthetic = [
        r
        for r in FocDecapProximity().check_with_library(ctx, _shelf())
        if r.target.component_ref == "C22"
    ]
    assert len(synthetic) == 1
    assert synthetic[0].target.net_refs == ["$1N66497"], synthetic[0].target.net_refs
    assert "NET11" not in synthetic[0].message


# ---------------------------------------------------------------------------
# 四、F8-foc (first half) — R20's bulk pool
# ---------------------------------------------------------------------------


def test_power_loop_area_reads_the_schematic_bulk_value_and_names_both_views():
    """R20's row judges on the page's declaration for llc's ``330uF 400V``.

    llc is the corpus's measured divergence for a bulk capacitor: the page states
    ``330uF 400V``, the copy ``330uF``. The row quotes the page's text (not the
    copy's), states the farads that text yields, and carries the divergence in
    its own words.
    """
    findings, _section = run_pcb_review(LLC, model=_project(LLC))
    rows = [f for f in findings if f.rule_id == "pcb-foc-power-loop-area"]
    assert len(rows) == 4, "llc's full-bridge power stage keeps its four loops"
    for row in rows:
        assert "330uF 400V" in row.message, row.message
        assert "330 µF" in _evidence(row), _evidence(row)
        assert "原理图 '330uF 400V' / PCB 文档 '330uF'" in _evidence(row), (
            _evidence(row)
        )


def test_power_loop_area_pool_is_the_same_pool_the_page_says():
    """And the pool behind those rows is the page's pool, not the copy's.

    All four of llc's loops pair with ``C3`` — the rule pairs each FET with the
    **nearest** bulk capacitor on a net it shares, and measured (before and after
    this fix, since both views yield the same two parts) ``C3`` is nearest to all
    four. That is the rule's documented pairing, quoted here so the count is not
    mistaken for the pool's size.
    """
    board, model = _pcb_view(LLC)
    page = _schematic_page(LLC)
    rows = FocPowerLoopArea()._loops(board, model, _shelf(), page)
    assert len(rows) == 4, [r.bulk for r in rows]
    assert {r.bulk for r in rows} == {"C3"}, [r.bulk for r in rows]
    for reading in rows:
        assert reading.bulk_value == "330uF 400V"
        assert reading.bulk_farads == 330e-6
        assert "原理图 '330uF 400V' / PCB 文档 '330uF'" in reading.bulk_value_basis


def test_power_mosfets_of_reads_the_bulk_pool_through_the_page():
    """The Q-door's bus test follows the same pool (or the two would disagree).

    ``power_mosfets_of``'s second door is 「a Q transistor sitting on a net a
    **bulk** capacitor also sits on」, so its pool has to be the same one R20
    ranks against — otherwise one rule admits a FET the other cannot pair.
    """
    board, model = _pcb_view(FOC_100)
    page = _page({"C115": "10uF", "C116": "10uF"})
    with_copy = {des for des, _c, _b in power_mosfets_of(board, model, EMPTY_SHELF)}
    with_page = {des for des, _c, _b in power_mosfets_of(board, model, EMPTY_SHELF, page)}
    assert with_copy == {"Q1", "Q3", "Q7"}, with_copy
    assert with_page == set(), (
        "the page demotes C115/C116 below the bulk floor, so no bus net is left "
        "and the Q-door closes"
    )


# ---------------------------------------------------------------------------
# 五、F8-foc (second half) — R5's power-stage parts
# ---------------------------------------------------------------------------


def test_return_path_power_parts_read_the_bulk_pool_through_the_page():
    """R5's 未识别清单 is decided by the power-stage part set, values included.

    毕设FOC 1.0.0's ``+24V`` is the rule's own measured instance of an
    unrecognised power-path name, and the parts that put it on the power stage are
    ``C115``/``C116`` (bulk) and the three high-side FETs admitted *through* them.
    A page that demotes the two capacitors below the floor must take the whole
    row with it — otherwise the rule would keep naming a net on the strength of a
    value the drawing does not state.
    """
    from boardwise.rules.pcb.focground import FocReturnPath

    board, model = _pcb_view(FOC_100)
    copy_row = [
        r
        for r in FocReturnPath().check_with_library(
            PcbReviewContext(board=board, board_title="PCB1", pcb_model=model),
            EMPTY_SHELF,
        )
        if "未识别清单" in r.message
    ]
    assert copy_row and "+24V" in _evidence(copy_row[0])

    page = _page({"C115": "10uF", "C116": "10uF"})
    page_rows = [
        r
        for r in FocReturnPath().check_with_library(
            PcbReviewContext(
                board=board, board_title="PCB1", model=page, pcb_model=model
            ),
            EMPTY_SHELF,
        )
        if "未识别清单" in r.message
    ]
    assert page_rows == [], (
        "the page says these two are 10 µF, so no power-stage part is left on "
        "+24V and there is nothing unrecognised to list"
    )


# ---------------------------------------------------------------------------
# 六、F7 — the feedback divider's leg pool
# ---------------------------------------------------------------------------


def test_the_resistor_pool_drops_a_schematic_zero_ohm_leg():
    """F7 on the pool: a ``0R`` on the page is not a leg, whatever the copy says.

    ``_resistors``' contract is 「a resistor is a part whose value parses as ohms
    **and is above zero**」 — a 0 Ω link is a jumper, not a divider leg. Reading
    the copy turned 1.0.0's ``R31``/``R48``/``R49`` (all ``0R`` on the page) into
    ``10K`` legs.
    """
    model = DesignModel(
        components={
            "R1": _placed("R1", "10K", [("1", "A", "NET11"), ("2", "B", "GND")]),
            "R2": _placed("R2", "10K", [("1", "A", "NET11"), ("2", "B", "GND")]),
        }
    )
    page = _page({"R1": "0R", "R2": "15K"})
    assert set(_resistors(model)) == {"R1", "R2"}, "both are legs to the copy"
    assert set(_resistors(model, page)) == {"R2"}, (
        "the page says R1 is a 0 Ω link, so it is not a leg"
    )


def test_the_bisce_foc_100_leg_pool_loses_exactly_its_three_zero_ohm_parts():
    """The fixture's own answer, before and after, and what it changes.

    1.0.0's PCB1: the copy-only pool is 38 parts and the divider found is
    ``U11`` on ``R14``/``R21``; the page-correct pool is **35** — ``R31``,
    ``R48``, ``R49`` are the three ``0R`` the copy called ``10K`` — and the
    divider is unchanged, because none of the three was a leg.
    """
    _board, model = _pcb_view(FOC_100)
    page = _schematic_page(FOC_100)
    shelf = _shelf()

    copy_pool = set(_resistors(model))
    page_pool = set(_resistors(model, page))
    assert len(copy_pool) == 38, len(copy_pool)
    assert len(page_pool) == 35, sorted(page_pool)
    assert copy_pool - page_pool == {"R31", "R48", "R49"}, sorted(copy_pool - page_pool)
    assert all(str(page.components[d].value) == "0R" for d in ("R31", "R48", "R49"))

    copy_dividers = {
        (d.ic, d.upper, d.lower) for d in fb_dividers(model, shelf)
    }
    page_dividers = {
        (d.ic, d.upper, d.lower) for d in fb_dividers(model, shelf, page)
    }
    assert copy_dividers == page_dividers == {("U11", "R14", "R21")}, (
        copy_dividers, page_dividers
    )


def test_regulator_fb_placement_no_longer_uses_a_zero_ohm_leg():
    """F7 end to end, through the rule: a 0 Ω lower leg is no divider.

    毕设FOC 1.0.0's ``U11`` divider is ``R14``/``R21``. Handed a page that says
    ``R21`` is a ``0R`` link, the rule must report the **no-divider** row for
    ``U11`` instead of placing a divider through a link — the same class of
    mistake the copy manufactured on ``R48``/``R49``.
    """
    board, model = _pcb_view(FOC_100)
    shelf = _shelf()

    production = [
        f
        for f in RegulatorFbPlacement().check_with_library(
            PcbReviewContext(
                board=board,
                board_title="PCB1",
                model=_project(FOC_100),
                pcb_model=model,
            ),
            shelf,
        )
        if f.target.component_ref == "U11"
    ]
    assert production and any("divider recognised mechanically" in _evidence(f) for f in production)

    page = _page({"R21": "0R"})
    zero_leg = [
        f
        for f in RegulatorFbPlacement().check_with_library(
            PcbReviewContext(
                board=board, board_title="PCB1", model=page, pcb_model=model
            ),
            shelf,
        )
        if f.target.component_ref == "U11"
    ]
    assert zero_leg, "U11 still has an FB pin, so the rule still has something to say"
    assert not any("divider recognised mechanically" in _evidence(f) for f in zero_leg), (
        [f.message for f in zero_leg]
    )
    assert any("no feedback divider reaches it" in f.message for f in zero_leg)


# ---------------------------------------------------------------------------
# 七、D1 — the 0 Ω pin fallback
# ---------------------------------------------------------------------------


def test_a_zero_ohm_with_one_ground_pin_reports_two_different_nets():
    """D1: the fallback must not answer with the same pin twice.

    ``all_zero_ohm_parts_of`` prefers the *grounded* pins and falls back to pin
    order. With **one** grounded pin the old code took ``grounded[0]`` and then
    ``pins[1]`` — which, when the grounded pin *is* ``pins[1]``, is the same pin,
    so the ledger printed a net against itself.
    """
    model = DesignModel(
        components={
            # pin 1 on a rail, pin 2 on ground: exactly the shape that degenerates
            "R99": _placed("R99", "0R", [("1", "A", "+24V"), ("2", "B", "GND")]),
        }
    )
    readings = all_zero_ohm_parts_of(model, None, _page({"R99": "0R"}))
    assert len(readings) == 1
    reading = readings[0]
    assert reading.net_a != reading.net_b, (reading.net_a, reading.net_b)
    assert {reading.net_a, reading.net_b} == {"+24V", "GND"}
    assert (reading.pin_a, reading.pin_b) == ("1", "2")


def test_the_two_ground_pin_case_still_prefers_the_grounded_pins():
    """The documented preference is preserved: two grounded pins are reported.

    The D1 fix narrows the *degenerate* case only — a part whose two pins land in
    two different ground domains keeps reporting exactly those two pins, which is
    what R1b's bridge partition reads.
    """
    model = DesignModel(
        components={
            "R48": _placed("R48", "0R", [("1", "A", "GND"), ("2", "B", "PGND")]),
            # pin order reversed, on purpose: the grounded pair decides, not I/O order
            "R49": _placed("R49", "0R", [("1", "A", "AGND"), ("2", "B", "PGND")]),
        }
    )
    readings = {r.designator: r for r in all_zero_ohm_parts_of(model, None, _page({}))}
    assert (readings["R48"].net_a, readings["R48"].net_b) == ("GND", "PGND")
    assert (readings["R49"].net_a, readings["R49"].net_b) == ("AGND", "PGND")


def test_the_zero_ohm_ledger_never_prints_a_net_against_itself():
    """D1's report half: 「R99 (0R, pins GND/GND)」 must not be printable.

    The sentence is the one ``_not_connected`` writes, and it is produced from
    the same reading — so this pins the row a reader actually sees.
    """
    from boardwise.rules.pcb.focground import FocGroundTie

    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        nets={
            "PGND": NetGeometry(name="PGND"),
            "GND": NetGeometry(name="GND"),
        },
    )
    model = DesignModel(
        components={
            "R99": _placed("R99", "0R", [("1", "A", "+24V"), ("2", "B", "GND")]),
        }
    )
    ctx = PcbReviewContext(
        board=board, board_title="SYNTH", pcb_model=model, model=_page({"R99": "0R"})
    )
    rows = FocGroundTie().check_with_library(ctx, EMPTY_SHELF)
    text = "\n".join(_evidence(r) + r.message for r in rows)
    assert "R99" in text, rows
    assert "'GND'/'GND'" not in text, text
    assert "'+24V'/'GND'" in text, text


# ---------------------------------------------------------------------------
# 八、D2 — the bare ``EARTH`` net
# ---------------------------------------------------------------------------


def _board_with(*nets: str) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        nets={name: NetGeometry(name=name) for name in nets},
    )


def test_a_bare_earth_net_lands_in_the_power_domain():
    """D2: the sieve and the word list must not disagree about ``EARTH``.

    ``split_ground_domains`` sieved with ``core.model.is_ground_net`` — which did
    **not** carry ``EARTH`` (it was not in ``GROUND_NET_PREFIXES`` and ``EARTH``
    has no ``_``-separated tail) — and only then asked :func:`domain_of`, whose
    own word list **does** carry it
    (:data:`~boardwise.rules.pcb.focground.GROUND_DOMAIN_POWER_PREFIXES`). So the
    one name the module claims as a power ground was filtered out before the
    classifier saw it and vanished from every domain in silence.

    171 closed the vocabulary gap (``EARTH`` is a ``GROUND_NET_PREFIXES`` word now),
    so the union sieve is redundant for this name — the split, which is what this
    test is about, is the same either way.
    """
    split = split_ground_domains(_board_with("EARTH", "GND"))
    assert split.power == ("EARTH",), split
    assert split.logic == ("GND",), split
    assert split.unclassified == (), split
    assert domain_of("EARTH") == "power", "the word list this module declares"


def test_suffix_ground_names_stay_unclassified():
    """The sieve's other half is preserved: ``SEC_GND`` is ground-class, no domain.

    145a's suffix vocabulary makes ``SEC_GND`` ground-class to
    ``is_ground_net``, and ``domain_of``'s word list is a **prefix** list, so it
    lands in ``unclassified`` — 「the drawing spells its ground something this
    word list does not carry」. The D2 fix must not swallow it into either domain.
    """
    split = split_ground_domains(_board_with("SEC_GND", "GND", "PGND"))
    assert split.unclassified == ("SEC_GND",), split
    assert split.power == ("PGND",) and split.logic == ("GND",)


def test_r1b_judges_a_bare_earth_pair_instead_of_calling_the_board_domainless():
    """D2 end to end: an ``EARTH`` board gets a **pair row**, not 「no power domain」.

    Before the fix ``split.power`` was empty on such a board and R1b filed its
    「no power-domain ground on this board」 row — a false statement about a board
    whose drawing says ``EARTH``, and the pair was never judged.
    """
    from boardwise.rules.pcb.focground import FocGroundTie

    board = _board_with("EARTH", "GND")
    ctx = PcbReviewContext(
        board=board, board_title="SYNTH", pcb_model=DesignModel(), model=None
    )
    rows = FocGroundTie().check_with_library(ctx, EMPTY_SHELF)
    assert len(rows) == 1, [r.message for r in rows]
    row = rows[0]
    assert "no power-domain ground" not in row.message, row.message
    assert "'EARTH'" in row.message and "'GND'" in row.message, row.message
    assert "不连" in row.message, "nothing bridges the pair, so it is 岳's 「不连」"
    assert "'EARTH'" in _evidence(row), _evidence(row)


def test_the_split_evidence_prints_the_power_family_it_actually_uses():
    """The classification evidence names the words that placed each net.

    「域名分类证据写进每条 finding」 is the rule's own contract, and after D2 the
    line has to be true of the sieve: ``EARTH`` is a member of the power family
    it is listed under.
    """
    from boardwise.rules.pcb.focground import GROUND_DOMAIN_POWER_PREFIXES, _domain_evidence

    assert "EARTH" in GROUND_DOMAIN_POWER_PREFIXES
    text = "\n".join(_domain_evidence(split_ground_domains(_board_with("EARTH", "GND"))))
    assert "'EARTH'" in text
    power_line = next(line for line in text.splitlines() if line.startswith("power domain"))
    assert "'EARTH'" in power_line, power_line
