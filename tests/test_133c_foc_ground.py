"""Task 133c: the three FOC ground-system rules — ``rules/pcb/focground.py``.

133a landed ``return_path_projection``; 133b landed the five quick wins in
``rules/pcb/foc.py``; 133c is the batch that reads the **ground system**: the
power-vs-logic domain split, how the two domains join, and what the gate /
switching / sense traces see under them. Three rules, all ``INFO``:

* **R1 ``pcb-foc-ground-domains``** — one row per (power ground net, logic
  ground net) pair: does their copper **meet on a shared layer**, how near is
  the nearest pair, and how many copper islands does each side carry.
* **R1b ``pcb-foc-ground-tie``** — 岳's rulings: the domains join through a
  **0 Ω per domain pair** (2026-10-08 supplied the 0 Ω form; **2026-10-11** fixed
  the unit — 「每对地域各一颗 0R 即合规」), and that 0 Ω should sit near the
  power-stage bulk electrolytic. Branches reported: one 0 Ω per pair (**合规**,
  with its distance to the nearest bulk cap), several / non-zero /
  directly-copper-connected *on that pair*, nothing joining that pair
  (「要么不连，要么单点」), a part whose resistance is UNKNOWN, and a 0 Ω part that
  sits inside one domain (a jumper, not a tie).
* **R5 ``pcb-foc-return-path``** — the return-path projection of every gate /
  switching-node / sense net, with **PLANE-layer semantics** (岳's ruling: a
  ``layerType == "PLANE"`` reference layer is 构造性完整覆盖), plus an explicit
  未识别清单 of the power-stage nets whose names the sieve does not recognise.

**The measured answer to the task book's own question.** 「1.0.0 的 PGND↔GND
到底有没有真铜连」 — measured here, and the answer is **no**: PGND↔GND reads
**68.9 mil** and PGND↔AGND reads **18.1 mil** edge-to-edge, with
``overlapping=False`` on both, and an exhaustive shape-pair sweep (104 PGND
shapes × 180 GND shapes, 104 × 77 AGND) finds **zero** pairs at distance 0.
So the 127a 「0.0 mil 贴脸」 history does **not** recur on this board between
these two domains: 127b's pad-layer fix is holding, and the six pairs 127a
attributed to a parser defect were indeed all top-side × bottom-side.

**The measured answer to the second question.** 「板上有没有 0R 单点件」 — **yes,
two of them**, and this is 153b's correction to what this file first recorded,
while 155a's per-pair ruling is what makes them the *compliant* answer.
毕设FOC 1.0.0's PCB1 joins its two ground domains with ``R48`` (``0R``,
``GND``↔``PGND``) and ``R49`` (``0R``, ``AGND``↔``PGND``) — **one 0 Ω per domain
pair**, which is 岳's 2026-10-11 shape (「每对地域各一颗 0R 即合规」) — plus a
third 0 Ω, ``R31``, on ``+24V``↔``$1N74269``, which bridges no ground domain and
is reported as a jumper. The **PCB document's own copies** of ``R48``/``R49`` say
``10K``, which is what the rule used to read and why this file once recorded
「two 10 kΩ resistors, no 0 Ω at all」; that reading was the stale copy talking,
and ``focground``'s value chain now reads the schematic page first (the module
docstring's 「which value field」 section). Before 155a the same two 0 Ω were
reported as 「not a single point」, because 岳's earlier board-wide wording asked
for exactly one 0 Ω for the whole ground system; the ruling of 2026-10-11 moved
**the unit the count is taken over**, from the board to the domain pair, and no
per-pair count on this board exceeds one. ROBOT is the mirror image — it places
a 0 Ω (``R8``, ``0Ω``, ``CRCW06030000Z0EAHP``) on ``GND``↔``$1N251``, so it is a
**jumper**, not a tie, and it has no power domain at all to be a tie between.
ROBOT's ``R8`` is also the measured instance of the **fallback**: the schematic
page states no value for it, so the value comes from the PCB document and the row
says so.

**PLANE is the third measured anchor.** 毕设FOC 1.0.0's PCB1 declares layers
15 and 16 as ``PLANE`` and **neither carries a single pour polygon** — so read
literally every power net would report ``none`` on every layer, a statement
about the model rather than the board. With 岳's PLANE reading all fifteen of
1.0.0's power-path nets read ``covered-by-construction``. ROBOT's layer 16 is
``SIGNAL`` (and carries a real pour), which is why the same rule there goes
through the POUR data.
"""

from __future__ import annotations

import re
from pathlib import Path

from boardwise.core.geometry import (
    BBox,
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
)
from boardwise.core.measure import net_clearance, return_path_projection
from boardwise.core.parts import PartLibrary
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule
from boardwise.rules.pcb.focground import (
    GROUND_DOMAIN_LOGIC_PREFIXES,
    GROUND_DOMAIN_POWER_PREFIXES,
    PLANE_LAYER_TYPE,
    DomainPairReading,
    FocGroundDomains,
    FocGroundTie,
    FocReturnPath,
    all_zero_ohm_parts_of,
    bridging_parts_of,
    domain_of,
    return_path_cover,
    split_ground_domains,
    zero_ohm_resistors_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

R1 = "pcb-foc-ground-domains"
R1B = "pcb-foc-ground-tie"
R5 = "pcb-foc-return-path"
RULE_IDS = [R1, R1B, R5]


#: Which project model each fixture parses to, built once per path. The rules
#: are run the way **production** runs them (``cli.py`` passes ``model=`` into
#: ``run_pcb_review``), because 153b's value reading needs the project's
#: schematic boards: a run with ``model=None`` has no schematic view at all and
#: falls back to the PCB document's stale ``component.value`` copies. Measured
#: on 1.0.0's PCB1: with the model its two bridges read ``0R`` (the schematic's
#: declaration), without it they read ``10K`` (the copy) — so a helper that left
#: the model out would pin the very defect 153b fixed.
_PROJECTS: dict[Path, object] = {}


def _rows(path: Path, rule_id: str) -> list:
    return [f for f in _findings(path) if f.rule_id == rule_id]


def _findings(path: Path) -> list:
    """Every finding of a run wired the way production wires it (see ``_PROJECTS``)."""
    from boardwise.parsers.schematic import build_project_model

    model = _PROJECTS.get(path)
    if model is None:
        model = _PROJECTS[path] = build_project_model(path)
    findings, _section = run_pcb_review(path, model=model)
    return findings


#: An **empty** shelf, not ``None``. The rules' documented contract is that
#: ``library=None`` degrades to an empty shelf (131b/131d's wording), and the
#: synthetic cases here lean on exactly that degradation: with no shelf entry a
#: part can only be recognised by its designator, which is the condition under
#: which 「a 0 Ω part is catalogue-less」 is being exercised. ``None`` itself is
#: not the empty shelf — ``core.parts.find_facts`` dereferences it — so these
#: tests pass a real (empty) library rather than a missing one.
EMPTY_SHELF = PartLibrary()


def _evidence(row) -> str:
    return "\n".join(row.evidence)


def _model_for(path: Path, title: str = "PCB1"):
    """``(board, netlist view)`` for one PCB document, named by its META title."""
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import extract_board, load_epro2_source

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


def _schematic_page(path: Path, title: str = "PCB1"):
    """The **schematic page this PCB document declares**, off ``META.board``.

    The board chain 153b's value reading walks (151/153's own lookup): the PCB
    document's ``META.board`` uuid against the project model's boards — never
    designator overlap, which on 毕设FOC would answer with the wrong page
    (Board1 and Board3 share ``C1``…``R6``). ``None`` when the document declares
    no link (智能药箱's PCB1 does not), which is the honest 「no schematic view」
    the rule degrades on.
    """
    from boardwise.engines.pcbreview import _pcb_documents
    from boardwise.parsers.epru import load_epro2_source

    model = _PROJECTS.get(path)
    if model is None:
        from boardwise.parsers.schematic import build_project_model

        model = _PROJECTS[path] = build_project_model(path)
    for doc_title, board_uuid, _document in _pcb_documents(load_epro2_source(path)):
        if doc_title != title:
            continue
        for board in getattr(model, "boards", []) or []:
            if str(
                getattr(getattr(board, "board", None), "uuid", "") or ""
            ) == str(board_uuid):
                return board
        return None
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


# ---------------------------------------------------------------------------
# 一、structure: the ids, their order, and their sources
# ---------------------------------------------------------------------------


def test_the_three_rules_sit_in_the_foc_block_after_133b_five():
    """The 133c placement, as one assertion.

    The three land as a **contiguous continuation** of 133b's five — same block,
    same shape (L1 geometry readers), still ahead of the geometry sweep — and in
    the task book's own 133c table order (R1 → R1b → R5). The whole list is
    pinned by value, not as a set: no rule reads another's output, so the order
    is a reading choice, and pinning it is what stops a later batch from
    reordering by accident.

    **133d widened this list again** (its R7 / R8 / R9 land after 133c's three),
    which is the second time this pin has had to move for a new FOC batch — the
    pattern rather than an accident, and the reason the list is spelled out in
    full each time.
    """
    assert [rule.id for rule in BUILTIN_PCB_RULES] == [
        "pcb-decap-distance",
        "pcb-regulator-cap-distance",
        "pcb-regulator-fb-placement",
        "pcb-mcu-crystal-placement",
        "pcb-mcu-crystal-keepout",
        "pcb-mcu-supply-groups",
        "pcb-mcu-reset-boot",
        "pcb-foc-decap-proximity",
        "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width",
        "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        R1,
        R1B,
        R5,
        "pcb-foc-thermal-via-style",
        "pcb-foc-thermal-via-array",
        "pcb-foc-thermal-exit-path",
        "pcb-footprint-consistency",
        "pcb-polarity-orientation",
        "pcb-silk-designator",
        "pcb-derating-package",
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
        "pcb-keepout-violation",  # R2-1, appended last
    ]
    assert all(isinstance(rule, PcbRule) for rule in BUILTIN_PCB_RULES)
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert [i for i in ids if i.startswith("pcb-foc")] == [
        "pcb-foc-decap-proximity",
        "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width",
        "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        R1,
        R1B,
        R5,
        "pcb-foc-thermal-via-style",
        "pcb-foc-thermal-via-array",
        "pcb-foc-thermal-exit-path",
    ], (
        "the FOC block is contiguous: 133b's five, then 133c's three, then "
        "133d's three"
    )


def test_each_rule_declares_where_its_authority_comes_from():
    """钉 7: ``source`` says **where the number came from**, each one its own.

    R1 and R5 cite **TI SLVA959B** sections (this pack's design basis); R1b
    cites an **oracle ruling**, because 岳's 0 Ω convention is *not* a TI
    citation and TI SLVA959B says nothing about a 0 Ω resistor or its position.
    Pinning the distinction is the point: a rule that claimed TI authority for
    the 0 Ω form would be claiming a standard it is not measured against, which
    is the failure 133b's source-pin discipline exists to stop.

    **155a moved R1b's source, not R1/R5's.** 岳's 2026-10-11 ruling
    (「每对地域各一颗 0R 即合规」) is now the line this rule grades against, so
    the source names **both** rulings — the 2026-10-08 one that supplied the 0 Ω
    form and the 2026-10-11 one that supplied the unit it counts over — and it
    still says which half TI backs. R1 and R5 remain measurements 出数不出判定.
    """
    sources = {R1: "1.3.1", R5: "1.2"}
    for rule in BUILTIN_PCB_RULES:
        if rule.id not in sources and rule.id != R1B:
            continue
        assert rule.level == "L1-pcb-geometry", rule.id
        assert rule.title, rule.id
        if rule.id in sources:
            assert rule.source.startswith("TI SLVA959B §"), rule.id
            assert sources[rule.id] in rule.source, (rule.id, rule.source)
            assert "出数不出判定" in rule.source or "待岳裁" in rule.source, rule.id
        else:
            assert "oracle ruling" in rule.source, rule.id
            assert "岳 2026-10-08" in rule.source, rule.id
            assert "2026-10-11" in rule.source and "每对地域各一颗 0R" in rule.source, (
                "R1b's source must name 岳's per-pair ruling, which is the "
                "conclusion this rule reports as 合规"
            )
            assert "TI SLVA959B 只背书物理隔离" in rule.source, (
                "R1b's source must say which half came from TI and which half "
                "is 岳's engineering convention"
            )


def test_no_rule_grades_a_measurement_against_a_threshold():
    """The pack's core discipline, asserted on the source rather than trusted.

    ``ZERO_OHMS`` is the one number that looks like a threshold and is not:
    「恰好一颗 0R」 is 岳's *stated form*, and the rule reports every outcome
    anyway rather than raising on a board that does not follow it. So the pin is
    that the module never **compares a distance or an area** against a constant,
    and never maps an outcome onto a severity other than ``INFO``.
    """
    import inspect

    from boardwise.rules.pcb import focground

    source = inspect.getsource(focground)
    # No distance/area/width comparison against a named mil constant. The only
    # comparison against a constant this file makes is `== ZERO_OHMS`, which
    # decides *which of 岳's four branches* a part falls into — a classification,
    # not a grade — so it is the one name allowed to appear on a right-hand side.
    for name in ("BULK_FARADS", "MULTILAYER_THRESHOLD", "OBTUSE_CORNER_DEG"):
        assert not re.search(rf"(?:<|>|<=|>=)\s*[^(\n]*{name}\b", source), (
            f"{name} must not be the right-hand side of a comparison in 133c; "
            "this pack is 出数不出判定 until 岳 rules a threshold"
        )
    # And every severity the module can emit is INFO.
    for match in re.finditer(r'severity="([A-Z0-9-]+)"', source):
        assert match.group(1) == "INFO", (
            f"133c emitted severity {match.group(1)!r}; the pack is INFO 起手 "
            "and 岳 has ruled no threshold"
        )


# ---------------------------------------------------------------------------
# 二、R1 — pcb-foc-ground-domains
# ---------------------------------------------------------------------------


def test_r1_finds_the_power_logic_pair_and_names_the_classification():
    """Acceptance anchor: 1.0.0's ``PGND`` against ``AGND`` / ``GND``.

    The word lists are **name tests** (a net has no shelf category that says
    「power ground」), so the row has to say which net landed in which domain and
    which prefix family put it there — 「不许静默」 is the task book's own
    requirement and it is asserted here on every row.
    """
    rows = [r for r in _rows(FOC_100, R1) if r.board == "PCB1"]
    assert len(rows) == 2, [(r.board, r.message[:70]) for r in rows]
    assert all(r.severity == "INFO" for r in rows)

    for row in rows:
        assert "PGND" in row.message
        ev = _evidence(row)
        # The classification evidence, every time.
        assert "power domain" in ev and "logic/analog domain" in ev
        assert "ground-domain classification" in ev
        assert "name test" in ev
        # Both word lists are quoted so a reader can audit the sieve.
        assert all(repr(p) in ev for p in GROUND_DOMAIN_POWER_PREFIXES)
        assert all(repr(p) in ev for p in GROUND_DOMAIN_LOGIC_PREFIXES)
        # The island reading, per domain — 131f made it physical.
        assert "copper island(s) over" in ev
        assert "pour_connectivity" in ev
        # 127b's layer-attribution lesson is on the row.
        assert "127a" in ev and "shared_layer_ids" in ev


def test_r1_reads_no_direct_copper_connection_between_pgnd_and_the_logic_grounds():
    """**The task book's own question, answered with the board's real data.**

    「1.0.0 的 PGND↔GND 到底有没有真铜连」 — the answer is **no**, and this test
    pins it three ways so it cannot pass by accident:

    1. through the rule (both rows say 「no direct copper connection」);
    2. through ``net_clearance`` directly, asserting ``overlapping is False``
       and ``shared_layer_ids`` is a real shared layer (so the reading is a
       same-layer gap, not a cross-layer projection);
    3. through an **exhaustive** shape-pair sweep — every PGND shape against
       every GND and every AGND shape — asserting **zero** pairs at distance 0.

    The third is the one that matters: ``net_clearance`` returns the *minimum*
    pair, so a single touching pair elsewhere would be the minimum and would be
    reported. Sweeping all pairs is what turns 「the nearest pair is 68.9 mil」
    into 「no pair touches at all」. It also settles 127a's history for these two
    nets: the six 0.0 mil pairs 127a found on this board were all top-side ×
    bottom-side, and with 127b's pad-layer fix in place they do not reappear
    between PGND and the logic grounds.
    """
    board, _model = _model_for(FOC_100)

    rows = {
        tuple(r.target.net_refs): r
        for r in _rows(FOC_100, R1)
        if r.board == "PCB1"
    }
    assert ("PGND", "AGND") in rows, sorted(rows)
    assert ("PGND", "GND") in rows, sorted(rows)
    for pair, row in rows.items():
        assert "**no direct copper connection**" in row.message, (pair, row.message)

    # (2) through the primitive
    pgnd_agnd = net_clearance(board, "PGND", "AGND")
    pgnd_gnd = net_clearance(board, "PGND", "GND")
    assert pgnd_agnd is not None and pgnd_gnd is not None
    for result in (pgnd_agnd, pgnd_gnd):
        assert result.overlapping is False, (
            f"{result.net_a}↔{result.net_b} overlap on "
            f"{result.shared_layer_ids}: that IS a direct copper connection"
        )
        assert result.shared_layer_ids, (
            "the nearest pair must share a layer, or the distance is a "
            "cross-layer projection and says nothing about a short"
        )
        assert result.distance > 0.0, result.distance

    # (3) exhaustive: no shape pair touches at all
    from boardwise.core import measure as M

    for logic in ("GND", "AGND"):
        shapes_a = M._net_shapes(board, board.net("PGND"))
        shapes_b = M._net_shapes(board, board.net(logic))
        assert shapes_a and shapes_b
        touching = []
        for x in shapes_a:
            for y in shapes_b:
                distance = M._capsule_distance(x, y, connectivity=False)
                if distance is not None and distance <= 0.0:
                    touching.append((x.label, y.label, sorted(x.layers & y.layers)))
        assert touching == [], (
            f"PGND↔{logic} has {len(touching)} shape pair(s) at distance 0 "
            f"out of {len(shapes_a)}×{len(shapes_b)}: {touching[:5]} — a direct "
            "copper connection exists and R1 must say so"
        )


def test_r1_isolation_row_is_info_and_states_a_number_not_a_verdict():
    """The 「隔离成立」 row is a measurement, and says which pairs it measured.

    岳's requirement is 「如实出『隔离成立』的 INFO 行」 — so the row exists, is
    ``INFO``, carries the gap in mils, and explicitly says the isolation holds
    *by this measurement* rather than 「passes」.
    """
    rows = [r for r in _rows(FOC_100, R1) if r.board == "PCB1"]
    assert rows
    for row in rows:
        assert row.severity == "INFO"
        assert "holds by this measurement" in row.message
        assert "not as a verdict" in row.message
        assert "mil edge-to-edge" in row.message
        assert row.target.measurement is not None
        assert row.target.measurement["unit"] == "mil"
        assert row.target.measurement["value"] > 0.0
        assert "§1.3.1" in _evidence(row)
        assert "engineering convention" in _evidence(row), (
            "R1 states that the *form* of the join is 岳's convention, "
            "and that it is R1b's subject rather than this row's"
        )


def test_r1_says_so_on_a_board_with_no_power_domain():
    """Acceptance anchor: ROBOT / 药箱 / llc have no ``PGND`` at all.

    R1 asks whether **two** ground domains touch. With one domain there is no
    pair, so the rule emits exactly one INFO row naming what it did find — the
    「absent, not empty」 discipline 133b applied to R16/R20. A rule that filed a
    finding for a missing domain would bury the FOC boards.
    """
    for path in (ROBOT, PILLBOX, LLC):
        rows = _rows(path, R1)
        assert len(rows) == 1, (path.name, len(rows))
        row = rows[0]
        assert row.severity == "INFO"
        assert "no power-domain ground" in row.message
        assert all(repr(p) in row.message for p in GROUND_DOMAIN_POWER_PREFIXES)
        ev = _evidence(row)
        assert "ground-domain classification" in ev
        assert "absent, not empty" in row.message or "absent, not empty" in ev
        # No clearance is claimed for a pair that does not exist.
        assert row.target.measurement is None
        assert row.target.net_refs == []


def test_r1_domain_split_is_two_way_and_names_the_unclassified():
    """The split is auditable: two domains, and a third bucket for 「neither」.

    A ground-class net whose name matches **neither** word list is UNKNOWN, not
    「logic」 — and it is reported by name rather than filed under whichever side
    happened to be checked second. This is asserted on a synthetic board so it
    does not depend on whether the corpus happens to carry such a net today.
    """
    board = _synthetic_board()
    split = split_ground_domains(board)
    assert split.power == ("PGND",)
    assert split.logic == ("AGND", "GND")
    assert split.unclassified == (), (
        "every net on this synthetic board matches one of the two families"
    )
    assert split.has_power

    assert domain_of("PGND") == "power"
    assert domain_of("pgnd_analog") == "power", "the test is case-insensitive"
    assert domain_of("AGND") == "logic"
    assert domain_of("VSS") == "logic"
    assert domain_of("") == ""
    assert domain_of("+24V") == "", "a supply rail is not a ground domain"
    assert domain_of("EARTH") == "power"


def test_r1_reports_a_cross_layer_zero_distance_as_no_connection():
    """A ``distance == 0`` that is **cross-layer** is not a short.

    1.1.0's PCB1 is the measured instance: ``PGND`` ↔ ``GND`` read distance
    ``0.0`` but ``overlapping=False`` with **no** shared layer — the plan-view
    projections of two shapes separated by prepreg. ``ClearanceResult``'s own
    docstring calls this out (127b), and the rule must say 「no copper
    connection is claimed」 rather than either reporting a short or silently
    calling 0.0 a gap.
    """
    board, _model = _model_for(FOC_110)
    result = net_clearance(board, "PGND", "GND")
    assert result is not None
    assert result.distance == 0.0, (
        "the measured instance: 1.1.0's PGND↔GND read distance 0"
    )
    assert result.overlapping is False
    assert result.shared_layer_ids == [], (
        "and it is a cross-layer pair, which is what makes it a projection"
    )

    reading = DomainPairReading(power="PGND", logic="GND", clearance=result)
    assert reading.directly_connected is False, (
        "the rule's direct-connection test is `overlapping and "
        "shared_layer_ids` — both. A cross-layer 0.0 is ordinary routing."
    )


# ---------------------------------------------------------------------------
# 三、R1b — pcb-foc-ground-tie
# ---------------------------------------------------------------------------


def test_r1b_reads_100_as_one_0r_per_domain_pair_and_reports_compliance():
    """**The acceptance anchor 155a moved**: 1.0.0 joins each pair with one 0 Ω.

    Before 155a this anchor said 「not a single point」, which was 岳's 2026-10-08
    board-wide wording talking: 「全板恰好一颗 0R」 counts one 0 Ω for the whole
    ground system, and 1.0.0's PCB1 carries **two** (``R48`` ``GND``↔``PGND``,
    ``R49`` ``AGND``↔``PGND``). 岳's 2026-10-11 ruling fixes the unit —
    「每对地域各一颗 0R 即合规」 — so the same measurement is now reported as
    **合规 on both pairs**, one row per pair. Nothing about the values moved:
    both ``R48``/``R49`` read ``0R`` from the schematic page (153b) while the
    PCB document's copies still say ``10K``, and each row still writes both views
    into its evidence.

    The rows are the ruling's own shape: **per pair**, each naming its tie, the
    other pair's independence, and 岳's sentence. ``R31`` — the third ``0R`` on
    the schematic page, on ``+24V``↔``$1N74269`` — is still a **jumper** row:
    neither of its pins is a ground net, so it belongs to no pair.
    """
    rows = [r for r in _rows(FOC_100, R1B) if r.board == "PCB1"]
    assert len(rows) == 3, [(r.board, r.message[:80]) for r in rows]
    pairs = [r for r in rows if "每对域恰好一颗 0R — 合规" in r.message]
    assert len(pairs) == 2, [r.message[:80] for r in pairs]
    jumper = next(r for r in rows if r not in pairs)
    assert all(r.severity == "INFO" for r in rows)

    by_tie = {r.target.component_ref: r for r in pairs}
    assert set(by_tie) == {"R48", "R49"}, by_tie
    r48, r49 = by_tie["R48"], by_tie["R49"]
    assert "'GND'" in r48.message and "'PGND'" in r48.message
    assert "'AGND'" in r49.message and "'PGND'" in r49.message
    for row in pairs:
        assert "岳 2026-10-11 裁" in row.message
        assert "出数不出判定" in row.message, "the bulk-cap distance is 出数"
        assert "distance to the nearest power-stage bulk electrolytic" in row.message
        blob = "\n".join(row.evidence)
        assert "每对地域各一颗 0R 即合规" in blob
        assert "推翻 2026-10-08" in blob, (
            "the row says which wording it overturns, so the change is auditable"
        )
        assert "the other pairs of this board are judged on their own rows" in blob
        assert "原理图 '0R' / PCB 文档 '10K'" in blob, (
            "the two views' disagreement is written down for the part it judged"
        )
        assert "岳's 2026-10-08 convention is 「0R 近功率电解电容」" in blob
        assert "not a TI citation" in blob

    assert "R31" in jumper.message and "not a ground-domain tie" in jumper.message
    assert "'+24V'" in jumper.message, jumper.message
    assert jumper.target.component_ref == "R31"
    assert not [r for r in rows if "not a single point" in r.message], (
        "no pair of this board is joined twice, so the account branch is not "
        "reached — that is the whole content of the 2026-10-11 ruling"
    )


def test_r1b_the_bridging_pool_is_structural_not_value_based():
    """The pool is 「two pins in two domains」; the value decides *which branch*.

    Asserted three ways on the corrected values: ``R48``/``R49`` **are** in the
    pool as ``0R`` ties, ``U1`` (which bridges ``AGND``↔``GND`` — two pins in the
    *same* domain) is **not**, and ``zero_ohm_resistors_of`` holds exactly those
    two.

    The pool stays structural even though 153b's value fix makes every bridge on
    this board a 0 Ω: a pool filtered by value cannot tell 「the two domains are
    not connected」 from 「they are joined by a part that is not 0 Ω」, and only the
    first of those is 岳's 「不连」 branch. The non-zero and UNKNOWN branches are
    exercised on synthetic boards (``_unvalued_bridge_board`` here, and
    ``tests/test_153b_ground_tie_values.py`` for the non-zero one) because no
    fixture reaches them any more.
    """
    _board, model = _model_for(FOC_100)
    schematic = _schematic_page(FOC_100, "PCB1")

    bridges = {
        part.designator: part
        for part in bridging_parts_of(model, EMPTY_SHELF, schematic)
    }
    assert set(bridges) == {"R48", "R49"}, sorted(bridges)

    r48 = bridges["R48"]
    assert (r48.net_a, r48.net_b) == ("GND", "PGND"), (r48.net_a, r48.net_b)
    assert r48.ohms == 0.0
    assert r48.is_zero_ohm is True
    assert r48.value == "0R", "judged on the schematic page's declaration"
    assert r48.schematic_value == "0R" and r48.pcb_value == "10K", (
        "both views are kept on the reading, which is what lets a row write "
        "「原理图 0R / PCB 文档 10K」"
    )

    assert "U1" not in bridges, (
        "U1 bridges AGND↔GND — two pins in the *same* domain — so the "
        "two-domain test excludes it and it is not a ground-domain tie"
    )

    assert [
        part.designator for part in zero_ohm_resistors_of(model, EMPTY_SHELF, schematic)
    ] == ["R48", "R49"], (
        "1.0.0's two cross-domain ties are both 0 Ω on the schematic page"
    )

    # The same pool read with **no** schematic view is the defect 153b removed:
    # the PCB document's copies say 10K and the same two parts read as non-zero.
    without_schematic = {
        part.designator: part for part in bridging_parts_of(model, EMPTY_SHELF)
    }
    assert without_schematic["R48"].value == "10K", (
        "with no schematic view the pool can only read the stale copy — which "
        "is why every entry point takes one"
    )
    assert without_schematic["R48"].value_basis.startswith("原理图页未写"), (
        "and it says so rather than presenting the copy as the drawing's word"
    )


def test_r1b_reads_the_0r_spelling_the_shared_value_parser_declines():
    """``0R`` is the spelling boards use, and ``core.values`` refuses it.

    Measured: :func:`boardwise.core.values.parse_resistance_ohms` returns
    ``None`` for ``"0R"`` — its leading-``R`` branch claims the ``R`` for the
    ``R010`` → 0.01 Ω spelling and cannot read what is left — while ``0`` /
    ``0.0`` / ``0Ω`` / ``0R0`` / ``R0`` all parse correctly. So the gap is one
    spelling, and it happens to be the spelling 岳's own ruling names
    (「恰好一颗 0R」).

    133c handles it **locally**, in
    :data:`~boardwise.rules.pcb.focground.EXPLICIT_ZERO_OHM_SPELLINGS`, rather
    than editing ``core`` — 133c's scope is three rules, and a shared grammar
    change belongs in its own batch. The list is exactly zero: nothing near zero
    is admitted, because a 0.5 Ω part is not 岳's single point.
    """
    from boardwise.core.values import parse_resistance_ohms
    from boardwise.rules.pcb.focground import EXPLICIT_ZERO_OHM_SPELLINGS

    # The measured gap this rule exists to cover.
    assert parse_resistance_ohms("0R") is None, (
        "if core.values starts reading 0R, this module's fallback becomes "
        "redundant — which is worth knowing rather than assuming"
    )
    assert parse_resistance_ohms("0") == 0.0
    assert parse_resistance_ohms("0Ω") == 0.0
    assert parse_resistance_ohms("0R0") == 0.0

    board, model = _single_zero_ohm_board()
    assert bridging_parts_of(model, EMPTY_SHELF)[0].ohms == 0.0, (
        "the 0R-spelled tie is read as 0 Ω through the fallback"
    )

    # The list is exactly zero and admits nothing close to it.
    assert "0R" in EXPLICIT_ZERO_OHM_SPELLINGS
    assert not (EXPLICIT_ZERO_OHM_SPELLINGS & {"0.1R", "0R1", "0.5", "1R"})
    board_5r, model_5r = _value_spelled_board("0.5R")
    assert bridging_parts_of(model_5r, EMPTY_SHELF)[0].ohms is None, (
        "a 0.5 Ω part is UNKNOWN here, not a 0 Ω and not a near miss"
    )


def test_r1b_names_a_0_ohm_part_that_is_not_the_tie():
    """Acceptance anchor: ROBOT *does* place a 0 Ω — and it is **not** the tie.

    ROBOT's ``R8`` is a genuine 0 Ω (``0Ω``, ``CRCW06030000Z0EAHP``), found by
    the real value parser. Its pins sit on ``GND`` and ``$1N251`` — one ground
    net and one not — so it bridges nothing between the two domains. The rule
    must say so by name rather than staying silent, because 「a 0 Ω exists on
    this board but is not the single point」 is exactly what a reader checking
    岳's convention needs to know.

    ROBOT has no power domain at all, so it takes R1b's *no-power-domain* row
    instead; the jumper reading is asserted through the pool, which is where the
    part is actually found.

    **153b**: this part is also the corpus's measured instance of the
    **fallback**. ROBOT's schematic page states **no** value for ``R8`` (measured:
    ``''``), so the ``0Ω`` in the PCB document is the only value there is — and
    the reading records that it is a fallback rather than the drawing's own word.
    An empty schematic value is a *different* case from a stale one, and both are
    distinguished on the row (``value_basis``).
    """
    _board, model = _model_for(ROBOT)
    schematic = _schematic_page(ROBOT, "PCB1")
    zeros = all_zero_ohm_parts_of(model, EMPTY_SHELF, schematic)
    assert [part.designator for part in zeros] == ["R8"], [
        (p.designator, p.value) for p in zeros
    ]
    r8 = zeros[0]
    assert r8.ohms == 0.0 and r8.is_zero_ohm
    assert r8.net_a == "GND"
    assert r8.net_b == "$1N251", (
        "the far pin is not a ground net, so this 0 Ω bridges no domain pair"
    )
    assert r8.value == "0Ω" and r8.schematic_value == "" and r8.pcb_value == "0Ω", (
        "the schematic page states nothing for R8, so the PCB document's value "
        "is used"
    )
    assert "回退" in r8.value_basis, (
        "and the reading says it is a fallback rather than the page's own word"
    )
    assert bridging_parts_of(model, EMPTY_SHELF, schematic) == [], (
        "and therefore it is not in the cross-domain bridging pool either"
    )


def test_r1b_is_silent_by_construction_on_a_board_with_no_power_domain():
    """Acceptance anchor: ROBOT / 药箱 / llc — one INFO row, and no tie search.

    Each takes the same branch: there is no ``PGND``, so there is no power/logic
    pair to tie and no 0 Ω to look for. The row says which prefixes were
    searched, so the silence is attributable rather than a mystery.
    """
    for path in (ROBOT, PILLBOX, LLC):
        rows = _rows(path, R1B)
        assert len(rows) == 1, (path.name, len(rows))
        row = rows[0]
        assert row.severity == "INFO"
        assert "no power-domain ground" in row.message
        assert all(repr(p) in row.message for p in GROUND_DOMAIN_POWER_PREFIXES)
        assert "R1b is silent by construction" in row.message
        assert _evidence(row).count("ground-domain classification") == 1


def test_r1b_reports_the_not_connected_branch_when_no_part_and_no_copper():
    """The 「不连」 branch: **one INFO row per pair**, naming the 0 Ω parts it did find.

    岳: 「要么不连，要么单点」 — both count, so a pair with nothing joining its two
    nets is reported with the same seriousness as one with a single 0 Ω, and the
    row says which branch it took. Under the 2026-10-11 per-pair ruling the unit
    is the pair, so this synthetic board — ``PGND`` against two logic grounds,
    ``GND`` and ``AGND`` — produces **two** 不连 rows rather than one board-level
    one: each pair answers for itself.

    The synthetic board is built so the branch is reached by the real rule rather
    than by mocking it. The evidence must also state the 0 Ω pool's contents,
    because 「no tie here」 and 「there is a 0 Ω here but it is elsewhere」 are
    different answers.
    """
    board, model = _isolated_domains_board()
    findings = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    rows = [f for f in findings if "not connected at all" in f.message]
    assert len(rows) == 2, [f.message[:70] for f in findings]
    assert {tuple(sorted(r.target.net_refs)) for r in rows} == {
        ("GND", "PGND"),
        ("AGND", "PGND"),
    }, [r.target.net_refs for r in rows]
    for row in rows:
        assert row.rule_id == R1B and row.severity == "INFO"
        assert "「要么不连，要么单点」" in row.message
        assert "this pair is not connected at all" in row.message
        ev = _evidence(row)
        assert "岳 2026-10-11 裁" in ev
        assert "bridging-part pool" in ev
        assert "the 0 Ω parts anywhere on this board are" in ev
        assert "R9" in ev, "the board's other 0 Ω (a jumper on AGND↔+5V) is named"
        assert "bulk electrolytics on this board" in ev, (
            "the bulk-cap pool is named even when there is no tie to measure, so "
            "a reader can see the proximity question had nothing to work with"
        )
        assert "the other pairs of this board are judged on their own rows" in ev
    assert not [f for f in findings if "每对域恰好一颗 0R — 合规" in f.message]


def test_r1b_reports_one_zero_ohm_tie_with_its_distance_to_the_bulk_cap():
    """The 「每对域一颗 0R → 合规，并量它到最近功率级电解电容的距离」 branch.

    Built on a synthetic board so the branch is exercised end to end: one 0 Ω
    bridging the two domain nets, and one 330 µF bulk electrolytic at a known
    gap. The row must report **合规** (岳 2026-10-11: 每对域恰好一颗 0R), and it
    must report **the gap in mils** and **name the capacitor** — 岳's convention
    is 「0R 近功率电解电容」 but he has ruled **no distance threshold**, so the
    number is 出数 and the row says so rather than grading it.
    """
    board, model = _single_zero_ohm_board()
    findings = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    rows = [f for f in findings if "每对域恰好一颗 0R — 合规" in f.message]
    assert len(rows) == 1, [f.message[:70] for f in findings]
    assert not [f for f in findings if "not a single point" in f.message]
    assert not [f for f in findings if "not connected at all" in f.message]
    row = rows[0]
    assert "R1" in row.message and "PGND" in row.message
    assert "岳 2026-10-11 裁" in row.message
    assert "distance to the nearest power-stage bulk electrolytic" in row.message
    assert "出数不出判定" in row.message, "the gap is quoted, not graded"

    ev = _evidence(row)
    assert "parses to 0.0 Ω" in ev
    assert "structural test" in ev, "the two-domain test is stated"
    assert "每对地域各一颗 0R 即合规" in ev
    assert "C9" in row.message and "bulk" in ev
    assert "岳's 2026-10-08 convention is 「0R 近功率电解电容」" in ev
    assert "not a TI citation" in ev, (
        "the 0 Ω form is 岳's convention; the row must not let it read as TI"
    )
    assert "毕设FOC 1.0.0's" in ev and "compliant on both of their pairs" in ev, (
        "the row carries the measured corpus evidence for the ruling it applies"
    )
    assert row.target.component_ref == "R1"
    assert row.target.measurement is not None
    assert row.target.measurement["unit"] == "mil"


def test_r1b_an_unreadable_value_is_never_a_zero_ohm_tie():
    """UNKNOWN is not zero — and an unstated part is not invented into a tie.

    The synthetic part states **no** value at all. It bridges the two domains
    (so it is on the ledger as a bridging part) but it cannot be a 0 Ω single
    point, because nothing says its resistance is zero. Dropping the part
    entirely would also be wrong, so the assertion is both halves: in
    :func:`zero_ohm_resistors_of` it is absent, and in the row it appears with
    its resistance stated as UNKNOWN.
    """
    board, model = _unvalued_bridge_board()
    assert zero_ohm_resistors_of(model, EMPTY_SHELF) == [], (
        "a part with no stated value cannot be a 0 Ω tie"
    )
    bridges = bridging_parts_of(model, EMPTY_SHELF)
    assert [part.designator for part in bridges] == ["R7"], [
        p.designator for p in bridges
    ]
    assert bridges[0].ohms is None and bridges[0].is_zero_ohm is False

    findings = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    rows = [f for f in findings if "no readable resistance" in f.message]
    assert len(rows) == 1, [f.message[:70] for f in findings]
    row = rows[0]
    assert row.rule_id == R1B and row.severity == "INFO"
    assert "R7" in row.message
    ev = _evidence(row)
    assert "UNKNOWN, never zero" in ev, (
        "UNKNOWN must be stated, not rounded to zero or dropped"
    )
    assert "does **not** demote a real single 0 Ω" in ev, (
        "and an unstated part must not be allowed to outvote a real single "
        "point on the same board"
    )
    assert row.target.component_ref == "R7"


# ---------------------------------------------------------------------------
# 四、R5 — pcb-foc-return-path
# ---------------------------------------------------------------------------


def test_r5_reads_plane_layers_as_constructive_coverage():
    """**岳's PLANE ruling, and the 1.0.0 baseline the task book states.**

    The task book's own baseline: 「L1 的参考层是 L15（PLANE）→ covered-by-
    construction」. Every one of 1.0.0's fifteen power-path nets projects onto
    layer 15 or 16, both ``PLANE``, and **neither carries a pour polygon** — so
    read literally every net would report ``none``, which is a statement about
    the model and not about the board.

    The evidence must therefore carry 「plane 层，分割不在模型内」, and the row
    must **not** also report a gap for a net it just called covered — that
    self-contradiction was real during development (the gap list was reading the
    primitive's raw ``cover_status``) and this test is what pins it shut.
    """
    rows = _rows(FOC_100, R5)
    per_net = [r for r in rows if "未识别清单" not in r.message]
    assert len(per_net) == 15, (
        [r.message[:50] for r in per_net],
        "1.0.0's fifteen power-path nets (6 gate + 6 sense + 3 switching node)",
    )
    for row in per_net:
        assert "covered-by-construction" in row.message, row.message
        assert "no gap found on any reference layer" in row.message, (
            f"{row.message[:120]} — a net reported as covered by construction "
            "cannot simultaneously carry gaps"
        )
        ev = _evidence(row)
        assert "PLANE" in ev, "the layer's own type is quoted so it is checkable"
        assert "构造性完整覆盖" in ev, (
            "the reading is named in 岳's own words, not paraphrased"
        )
        assert "covered-by-construction" in ev
        assert "a plane's splitting" in ev and "in this model" in ev, (
            "the row must say **why** a plane is constructive: its splitting is "
            "not in the model, so a gap read off it would be a statement about "
            "the model rather than about the board"
        )

    board, _model = _model_for(FOC_100)
    for layer_id in (15, 16):
        info = board.layer(layer_id)
        assert info is not None and info.layer_type == PLANE_LAYER_TYPE
        assert not [
            p for p in board.pours
            if p.layer_id == layer_id and p.kind in ("fill", "poly", "pour")
        ], (
            f"layer {layer_id} carries no pour polygon — which is exactly why "
            "the PLANE ruling is load-bearing rather than cosmetic"
        )


def test_r5_goes_through_pour_data_on_a_signal_reference_layer():
    """A ``SIGNAL`` reference layer is **not** constructive — POUR decides.

    ROBOT's layer 16 is ``SIGNAL`` (1.0.0's two inner layers are both
    ``PLANE``), and ROBOT's own ``TIM1_CH1`` traces drop to it. So the same rule
    takes the other branch on the same corpus, which is what makes the PLANE
    reading a **conditional** semantic rather than a blanket 「everything is
    covered」 that would have hidden every real gap.
    """
    board, _model = _model_for(ROBOT)
    info = board.layer(16)
    assert info is not None and info.layer_type == "SIGNAL"
    assert board.layer(15).layer_type == PLANE_LAYER_TYPE, (
        "ROBOT's layer 15 is PLANE, so the two boards exercise both branches"
    )

    # ``TIM1_CH1`` runs on layers 1 and 16 on this board, but the net is
    # chosen by measurement rather than assumed — whichever of the candidates
    # actually reaches the SIGNAL inner layer is the one the anchor uses.
    net = next(
        n
        for n in ("TIM1_CH1", "U+", "W+")
        if any(
            row.reference_layer_id == 16
            for row in return_path_projection(board, n).rows
        )
    )
    counts, notes = return_path_cover(board, net)
    assert counts, (net, counts)
    assert "covered-by-construction" in counts, (
        "the layer-15 half of this net is PLANE and reads constructively"
    )
    # The layer-16 half goes through the POUR data. What that reading *is* on
    # this board is measured rather than assumed: TIM1_CH1 has tracks on layers
    # 1 and 16, and layer 16 is SIGNAL, so at least one row must carry the
    # primitive's own status rather than the plane reading. Asserting the
    # specific status would pin the corpus's pour geometry into the test; what
    # matters for this batch is that the two branches are taken on the right
    # layers, so the assertion is on the notes and on the row-to-layer mapping.
    report_rows = return_path_projection(board, net).rows
    signal_rows = [r for r in report_rows if r.reference_layer_id == 16]
    plane_rows = [r for r in report_rows if r.reference_layer_id == 15]
    assert signal_rows, "this net drops to the SIGNAL inner layer"
    assert plane_rows, "and it also runs on the top layer beside the PLANE one"
    assert counts["covered-by-construction"] == len(plane_rows)
    assert sum(counts.values()) == len(report_rows), (
        "every projected row is counted under exactly one status"
    )
    assert any("SIGNAL" in note and "POUR data" in note for note in notes), notes
    assert any("PLANE" in note and "covered-by-construction" in note for note in notes)


def test_r5_gives_one_row_per_power_path_net_and_lists_the_unrecognised():
    """The per-net summary and the 未识别清单, as the task book specifies.

    R5's object is a name test (the ROBOT ``TIM1_CH*`` lesson is in 133b's
    docstring), so the nets the sieve cannot place must land in an **explicit
    list** rather than being dropped: the task book says 「认不出的网如实进
    「未识别」清单」, and ROBOT's ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3`` are
    the measured instance — they are plainly gate nets to a reader and
    UNKNOWN to this rule, and saying so is the whole point.
    """
    rows = _rows(ROBOT, R5)
    unrecognised = [r for r in rows if "未识别清单" in r.message]
    assert len(unrecognised) == 1, [r.message[:60] for r in unrecognised]
    row = unrecognised[0]

    # ROBOT's recognised power-path set is empty (133b measured this), so the
    # only R5 row it produces is the list.
    assert len(rows) == 1, [r.message[:60] for r in rows]

    ev = _evidence(row)
    assert "TIM1_CH1" in ev and "TIM1_CH2" in ev and "TIM1_CH3" in ev
    assert "DRV1" in ev, "the power-stage part that puts the nets on the power stage"
    assert "UNKNOWN" in row.message
    assert "UNKNOWN here, not" in row.message, (
        "an unrecognised net is UNKNOWN, not 「signal」 — the ROBOT lesson"
    )
    assert "no projection is claimed for them" in row.message, (
        "and the row claims no projection for a net it cannot place"
    )
    assert "133b's R11 docstring records the same finding" in ev, (
        "the ROBOT TIM1_CH* cost was already measured by 133b; R5 inherits it "
        "rather than rediscovering it silently"
    )
    assert row.target.net_refs, "the unrecognised nets are named as targets"


def test_r5_excludes_ground_nets_from_the_unrecognised_list():
    """A ground net is not an 「unrecognised power-path signal」.

    The list's job is to surface nets whose *function* is unknown, and a return
    trace sitting on a bulk capacitor is a ground net — R1 already has a word
    list for those. Including them would bury ROBOT's three ``TIM1_CH*`` gate
    nets under every return trace on the board, which is the failure the
    未识别清单 is supposed to prevent.

    This one runs through the **real shelf** rather than the empty one, because
    ROBOT's ``DRV1`` is found by its shelf category (``ic.motor-driver``) and an
    empty shelf would leave the power-stage pool empty — with nothing to hang
    the list off, which is the 「absent, not empty」 case the sibling test pins
    for 药箱 instead.
    """
    from boardwise.core.model import is_ground_net
    from boardwise.core.parts import load_parts
    from boardwise.rules.facts import default_library_path
    from boardwise.rules.pcb.focground import FocReturnPath

    board, model = _model_for(ROBOT)
    ctx = PcbReviewContext(board=board, pcb_model=model)
    findings = FocReturnPath().check_with_library(
        ctx, load_parts(default_library_path())
    )
    listed = [r for r in findings if "未识别清单" in r.message]
    assert len(listed) == 1, [r.message[:60] for r in findings]
    nets = listed[0].target.net_refs
    assert nets, "the row names its nets"
    assert "GND" not in nets, (
        "the board's own ground net is not an unrecognised power-path net"
    )
    assert all(not is_ground_net(n) for n in nets), [
        n for n in nets if is_ground_net(n)
    ]
    assert "TIM1_CH1" in nets and "TIM1_CH2" in nets and "TIM1_CH3" in nets


def test_r5_says_nothing_on_a_board_with_no_power_stage_at_all():
    """Acceptance anchor: 药箱 produces **no** R5 row; llc produces only its list.

    药箱 places no ``ic.motor-driver``, no bulk electrolytic and no power FET, so
    the power-stage part pool (which is what makes the 未识别清单 reachable) is
    empty and the recognised set is empty too. The rule returns **nothing**
    rather than a row about every net it has — 「absent, not empty」.

    **llc is the near-miss and it is instructive, not a miss.** llc places four
    power FETs and two 330 µF bulk capacitors — a full bridge — so it *does* get
    a 未识别清单 row naming the eight nets on that power stage (``DC+`` /
    ``DC-`` / ``DHG`` / ``DHS`` / ``DLG`` / ``CHG`` / ``CHS`` / ``CLG``). None of
    them matches a power-path prefix, and the rule says so rather than guessing
    that ``DHG`` is 「driver high-side gate」. The task book's acceptance note
    calls llc 「无功率地域」, which is true of its **ground domains** (R1/R1b take
    the no-power-domain branch there) but not of its **power stage** — it has
    one, and R5 reports it.
    """
    # 药箱 is the measured instance for the **fet** door: the shelf *does*
    # classify its ``U2`` (2N7002K) as ``fet``, so the power-stage pool is
    # non-empty and the list reaches two nets off that part — ``$1N1614`` and
    # ``TIM1_PWM1``. Neither is a power-path net by name and neither is guessed
    # to be one.
    pillbox_rows = _rows(PILLBOX, R5)
    assert len(pillbox_rows) == 1, [r.message[:60] for r in pillbox_rows]
    assert "**未识别清单**" in pillbox_rows[0].message
    assert "2 net(s)" in pillbox_rows[0].message
    assert set(pillbox_rows[0].target.net_refs) == {"$1N1614", "TIM1_PWM1"}

    llc_rows = _rows(LLC, R5)
    assert len(llc_rows) == 1, [r.message[:60] for r in llc_rows]
    row = llc_rows[0]
    assert "**未识别清单**" in row.message
    assert "8 net(s)" in row.message
    ev = _evidence(row)
    for net in ("DC+", "DC-", "DHG", "DHS", "DLG", "CHG", "CHS", "CLG"):
        assert net in ev, net


def test_r5_one_row_per_net_on_bishe_foc_and_the_counts_are_the_measured_ones():
    """The measured baseline, per net, as the task book's summary asks for it.

    Each row is one net with its covered / partial / none counts and its gap
    positions. 1.0.0's fifteen nets read ``covered-by-construction`` on every
    trace because both inner layers are PLANE; the trace counts are 133a's own
    measured numbers, re-derived here through the rule.
    """
    counts = {
        "GHA": 7, "GHB": 4, "GHC": 9,
        "GLA": 7, "GLB": 5, "GLC": 4,
        "IA": 7, "IA+": 12, "IB": 6, "IB+": 14, "IC": 6, "IC+": 8,
        "MOTA": 7, "MOTB": 4, "MOTC": 4,
    }
    rows = {
        r.target.net_refs[0]: r
        for r in _rows(FOC_100, R5)
        if "未识别清单" not in r.message
    }
    assert set(rows) == set(counts), (sorted(rows), sorted(counts))
    for net, total in counts.items():
        row = rows[net]
        assert f"covered-by-construction {total}" in row.message, (
            net, row.message
        )
        assert f"over {total} trace(s)" in row.message
        assert row.severity == "INFO"
        assert "出数不出判定" in row.message
        assert "return_path_projection" in _evidence(row)
        assert "PLANE-layer semantics" in _evidence(row)


# ---------------------------------------------------------------------------
# 五、the acceptance matrix across five boards
# ---------------------------------------------------------------------------


def test_the_133c_acceptance_matrix_across_five_boards():
    """Every acceptance anchor in one place, so a regression is one failure.

    The task book's table: 毕设FOC 1.0.0 gives the domain pairs, the 0 R answer
    and the projection summary; ROBOT gives its own rows; llc / 药箱 have **no
    power ground at all** so R1 and R1b take their no-power-domain branch. The
    counts are measured, not aspirational.

    **Two batches moved cells here, and both moves are the ruling rather than a
    regression.** 153b moved 1.0.0's PCB1 from one R1b row to two (the corrected
    ``0R`` values plus the ``R31`` jumper row). **155a moved it again, to three**:
    under 岳's 2026-10-11 per-pair ruling each of the board's two domain pairs
    reports its own 合规 row, and the jumper row stays — so PCB1 carries three
    rows where the board-wide wording produced one. 1.1.0's PCB1 reads the same
    way (two pair rows + one jumper), and its total moves 4 → 5. No other cell
    moved: R1 and R5 never read a value.
    """
    matrix = {
        # board fixture -> {PCB document title: {rule id: exact row count}}
        # 毕设FOC 1.0.0 is a **three-document** project and the counts are per
        # document, not per project: PCB1 carries the power stage and produces
        # the domain pairs / the per-pair tie rows / the fifteen projection rows,
        # while PCB2 (a two-layer sensor board) has one ``GND`` and no ``PGND`` at
        # all, so it takes the no-power-domain branch. Counting the project as a
        # whole would hide that second branch, which is exactly what this matrix
        # exists to make visible.
        FOC_100: {
            "PCB1": {R1: 2, R1B: 3, R5: 16},  # 15 nets + 1 unrecognised list
            "PCB2": {R1: 1, R1B: 1, R5: 0},
        },
        ROBOT: {"PCB1": {R1: 1, R1B: 1, R5: 1}},   # no power ground; 1 list
        PILLBOX: {"PCB1": {R1: 1, R1B: 1, R5: 1}},  # 1 unrecognised list
        LLC: {"PCB1": {R1: 1, R1B: 1, R5: 1}},     # 1 unrecognised list
    }
    for path, per_board in matrix.items():
        findings = _findings(path)
        for title, expected in per_board.items():
            counts = {
                rid: sum(
                    1 for f in findings
                    if f.rule_id == rid and f.board == title
                )
                for rid in RULE_IDS
            }
            assert counts == expected, (path.name, title, counts, expected)


# ---------------------------------------------------------------------------
# 六、mutations — the tests above must go red when the rules change
# ---------------------------------------------------------------------------


def test_mutation_dropping_the_shared_layer_test_breaks_r1():
    """Mutation: drop the ``shared_layer_ids`` half of R1's connection test.

    The mutation is applied **in process** and reverted, and the point is that a
    rule which had lost the shared-layer half could no longer pass
    :func:`test_r1_reads_no_direct_copper_connection_between_pgnd_and_the_logic_grounds`
    — specifically 1.1.0's cross-layer ``PGND``↔``GND`` pair, whose measured
    ``distance`` is **0.0** with ``overlapping=False`` and no shared layer. With
    the shared-layer test removed, ``overlapping`` alone would still be False for
    that pair, so the mutation below goes further: it makes ``directly_connected``
    depend on ``distance <= 0`` alone, which is the reading a naive
    implementation would have. On 1.1.0 that turns a 0.0 mil cross-layer pair
    into 「direct copper connection」 — a false short on a board 127b already
    cleared.

    Applied and reverted here so the failure is *observable*, not asserted.
    """
    from boardwise.rules.pcb.focground import DomainPairReading as D

    board, _model = _model_for(FOC_110)
    real = net_clearance(board, "PGND", "GND")
    assert real is not None and real.distance == 0.0 and not real.overlapping

    # The real reading: no direct connection.
    assert D(power="PGND", logic="GND", clearance=real).directly_connected is False

    class Mutated(D):
        @property
        def directly_connected(self) -> bool:  # noqa: D102 — the mutation
            # A naive reading: 「touching」 means distance zero, layer or not.
            return self.clearance is not None and self.clearance.distance <= 0.0

    assert Mutated(
        power="PGND", logic="GND", clearance=real
    ).directly_connected is True, (
        "with the shared-layer test gone, 1.1.0's cross-layer 0.0 mil pair "
        "reads as a direct copper connection — the false positive 127b fixed, "
        "and what the pin above would catch"
    )

    # Reverted (the subclass is local): the real predicate is untouched.
    assert D(power="PGND", logic="GND", clearance=real).directly_connected is False


def test_mutation_removing_the_plane_reading_turns_100_into_all_none():
    """Mutation: drop ``PLANE_LAYER_TYPE`` → 1.0.0's whole R5 flips to ``none``.

    This is the task book's second named mutation: 「R5 的 PLANE 构造性覆盖删掉
    → 1.0.0 全变 none → 红」. Applied to a copy of the predicate, it is
    observable directly: every one of 1.0.0's fifteen power-path nets reads
    ``none`` on every one of its traces under the literal reading, because
    layers 15 and 16 carry no pour polygon at all.

    The mutation is applied to a subclass of the row builder rather than to the
    module, so no source file is edited and nothing has to be restored — the
    same discipline the 133b mutations used, and the reason this file is safe to
    run repeatedly.
    """
    board, _model = _model_for(FOC_100)

    # The real reading: constructive coverage everywhere.
    real_counts, _notes = return_path_cover(board, "GHA")
    assert real_counts == {"covered-by-construction": 7}, real_counts

    # The mutated reading: the primitive's own cover_status, plane or not.
    from boardwise.core.measure import return_path_projection

    report = return_path_projection(board, "GHA")
    mutated: dict[str, int] = {}
    for row in report.rows:
        status = (
            "no_reference_layer"
            if row.reference_layer_id is None
            else row.cover_status
        )
        mutated[status] = mutated.get(status, 0) + 1
    assert mutated == {"none": 7}, mutated
    assert mutated != real_counts, (
        "the mutated reading differs from the real one — this is the red the "
        "task book asks for"
    )
    assert set(mutated) == {"none"} and set(real_counts) == {
        "covered-by-construction"
    }, "the two readings do not merely differ in count, they disagree in kind"

    # And the same holds for the whole power-path set, not just GHA.
    from boardwise.rules.pcb.foc import gate_nets_of

    nets = gate_nets_of(board)
    assert len(nets) == 15, len(nets)
    for net in nets:
        counts, _ = return_path_cover(board, net)
        assert counts == {
            "covered-by-construction": return_path_projection(board, net).row_count
        }, (net, counts)
        raw = return_path_projection(board, net)
        assert all(r.cover_status == "none" for r in raw.rows), (
            f"{net}: the literal reading finds no ground copper anywhere, so "
            "every one of its rows is none"
        )


def test_mutation_reading_only_the_pcb_document_brings_100s_10k_back():
    """Mutation: read the PCB document's copy alone → 1.0.0's two 0 Ω vanish.

    This is **153b's own defect**, re-applied in process so the failure it caused
    is observable rather than asserted. With the value read from the PCB document
    alone, ``R48``/``R49`` come back ``10K`` (the copy's placeholder), both land in
    the *non-zero* bucket instead of the 0 Ω one, and **both** of the board's
    pairs take the 「not a single point」 branch with 「1 resistor(s) of a
    **non-zero** value」 — and ``R31``, the third ``0R``, disappears from the
    ledger entirely.

    The mutation is applied by handing the rule a context with **no project
    model** — which is exactly the state the code was in before the fix, since it
    had no way to take a schematic view at all. Nothing is edited on disk, so
    nothing has to be restored.

    155a sharpens the mutation's signature rather than changing it: the real
    board produces **two 合规 rows and no account row at all**, and the mutated
    one produces **two account rows and no 合规 row** — the two readings disagree
    in kind on every pair, not merely in a count.
    """
    from boardwise.rules.pcb.focground import FocGroundTie

    board, model = _model_for(FOC_100)
    schematic = _schematic_page(FOC_100, "PCB1")

    real = bridging_parts_of(model, EMPTY_SHELF, schematic)
    assert len(real) == 2 and all(part.is_zero_ohm for part in real), [
        (p.designator, p.value, p.ohms) for p in real
    ]

    mutated = bridging_parts_of(model, EMPTY_SHELF)
    assert len(mutated) == 2
    assert all(part.ohms == 10000.0 for part in mutated), [
        (p.designator, p.value, p.ohms) for p in mutated
    ]
    assert [p.designator for p in zero_ohm_resistors_of(model, EMPTY_SHELF)] == []
    assert [
        p.designator for p in zero_ohm_resistors_of(model, EMPTY_SHELF, schematic)
    ] == ["R48", "R49"], "the two readings disagree in kind, not merely in value"

    # The mutated rule output, from the same board: a context with no project
    # model, i.e. the pre-153b code's whole world.
    mutated_rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    mutated_account = [r for r in mutated_rows if "not a single point" in r.message]
    assert len(mutated_account) == 2, [r.message[:70] for r in mutated_rows]
    for row in mutated_account:
        assert "0 0 Ω resistor(s), 1 resistor(s) of a **non-zero** value" in (
            row.message
        ), (
            "with no schematic view each pair is reported as joined by one "
            "**non-zero** resistor and no 0 Ω at all — the false account 153b fixed"
        )
    assert not [
        r for r in mutated_rows if "每对域恰好一颗 0R — 合规" in r.message
    ], "and nothing on the mutated board is compliant, which is the defect"

    rows = [r for r in _rows(FOC_100, R1B) if r.board == "PCB1"]
    assert len(rows) == 3
    assert len([r for r in rows if "每对域恰好一颗 0R — 合规" in r.message]) == 2
    assert not [r for r in rows if "not a single point" in r.message], (
        "the real rule must NOT take the account branch on a board whose two "
        "pairs each carry exactly one 0 Ω"
    )
    assert not [r for r in rows if "not connected at all" in r.message], (
        "nor the 不连 branch: both pairs are joined"
    )


# ---------------------------------------------------------------------------
# helpers — synthetic boards for the branches no fixture reaches
# ---------------------------------------------------------------------------


def _all_parts(model) -> list:
    """``[(designator, value)]`` for every part of a netlist view."""
    return [
        (str(des), str(getattr(comp, "value", "") or ""))
        for des, comp in sorted((getattr(model, "components", {}) or {}).items())
    ]


def _strip_ohms(value: str) -> str:
    """A value field reduced to what a 0 Ω-only (naive) pool would match on."""
    return (value or "").replace("\u03a9", "").replace("\u03a9", "").strip()


def _board_with(
    *,
    layers: dict[int, str],
    stackup: list[StackupEntry],
    nets: dict[str, list[tuple[str, str, float, float]]],
    components: dict[str, tuple[int, float, float]],
    pours: list[PourShape] | None = None,
    name: str = "SYNTH",
) -> BoardGeometry:
    """A minimal :class:`BoardGeometry` built from plain data.

    Enough of the shape for these three rules and nothing more: no outline (so
    no board-area share is computed), no vias, and pads that are plain
    rectangles **on the layer their component's ``layer_id`` names** — which is
    127b's reading, and is what makes a synthetic board's same-layer answer
    meaningful rather than accidentally cross-layer.

    ``nets`` maps a net name to ``[(designator, pin, x, y)]``: the pins that sit
    on it. ``components`` maps a designator to ``(layer_id, x, y)``. Every net
    also gets two short tracks on its first component's layer, so R5's
    projection has something to read without each fixture having to spell out
    routing.
    """
    from boardwise.core.geometry import ComponentPlacement, NetGeometry

    pads: list[PadGeometry] = []
    tracks: list[TrackSegment] = []
    per_net: dict[str, tuple[list[PadGeometry], list[TrackSegment], set[str]]] = {
        net: ([], [], set()) for net in nets
    }
    index = 0
    for net, entries in nets.items():
        net_pads, net_tracks, designators = per_net[net]
        for designator, pin, x, y in entries:
            index += 1
            pad = PadGeometry(
                id=f"{designator}-{pin}",
                component=designator,
                pin_number=pin,
                net=net,
                layer_id=components[designator][0],
                effective_layer_ids=[components[designator][0]],
                # The caller supplies (x, y) as a *rank*, not a coordinate:
                # pads are laid out on their own well-separated rows so that no
                # two nets' pads — and no net's pad and any net's track — can
                # touch. A synthetic board whose nets accidentally overlap would
                # silently answer the very question these fixtures exist to ask.
                x=200.0 * x,
                y=100000.0 + 400.0 * index,
                width=60.0,
                height=60.0,
                shape="rect",
            )
            pads.append(pad)
            net_pads.append(pad)
            designators.add(designator)
        layer_id = components[sorted(designators)[0]][0] if designators else 1
        # Each net's two tracks sit in a **wide** band of their own, far from
        # every other net's band. Without this the auto-generated tracks of two
        # nets would lie on top of one another (all at y≈1, 2, 3…), read as
        # same-layer copper overlap, and every synthetic board would look
        # electrically shorted — which would silently decide the very question
        # these fixtures exist to ask.
        band = 500.0 * list(nets).index(net)
        for k in range(2):
            index += 1
            track = TrackSegment(
                id=f"T{index}",
                net=net,
                layer_id=layer_id,
                start=Point(0.0, band + 250.0 * k),
                end=Point(2000.0, band + 250.0 * k),
                width=10.0,
            )
            tracks.append(track)
            net_tracks.append(track)

    placements = [
        ComponentPlacement(
            id=des, designator=des, x=x, y=y, angle=0.0, layer_id=layer_id
        )
        for des, (layer_id, x, y) in sorted(components.items())
    ]
    return BoardGeometry(
        name=name,
        layers={
            k: LayerInfo(layer_id=k, name=f"L{k}", layer_type=v)
            for k, v in layers.items()
        },
        stackup=stackup,
        components=placements,
        pads=pads,
        tracks=tracks,
        vias=[],
        pours=list(pours or []),
        outline=None,
        nets={
            net: NetGeometry(
                name=net, pads=net_pads, tracks=net_tracks
            )
            for net, (net_pads, net_tracks, _des) in per_net.items()
        },
    )


def _two_layer_stackup() -> list[StackupEntry]:
    return [
        StackupEntry(layer_id=1, z_index=1000, material="copper", thickness=1.378),
        StackupEntry(layer_id=362, z_index=1001, material="FR4", thickness=12.0),
        StackupEntry(layer_id=2, z_index=9000, material="copper", thickness=1.378),
    ]


def _synthetic_board() -> BoardGeometry:
    """One power net, two logic nets, one rail — enough to see the split."""
    return _board_with(
        layers={1: "TOP", 2: "BOTTOM"},
        stackup=_two_layer_stackup(),
        nets={
            "PGND": [("J1", "1", 0.0, 0.0)],
            "AGND": [("J1", "2", 300.0, 0.0)],
            "GND": [("J1", "3", 600.0, 0.0)],
            "+24V": [("J1", "4", 900.0, 0.0)],
        },
        components={"J1": (1, 0.0, 0.0)},
    )


def _isolated_domains_board():
    """Two domains, **nothing** joining them — plus a 0 Ω that is *not* a tie.

    Every part stays **inside one domain** (``U1`` is the logic-side IC on
    ``GND``, ``C1`` the power-side bulk on ``PGND``), so the structural pool
    finds no cross-domain bridge. ``R9`` is a genuine 0 Ω but on
    ``AGND``↔``+5V`` — one ground net and a rail — so it is a jumper, not a
    tie, and the 「不连」 row's evidence has a real 0 Ω pool to report. That
    distinguishes 「no tie here」 from 「this board has no 0 Ω at all」.
    """
    board = _board_with(
        layers={1: "TOP", 2: "BOTTOM"},
        stackup=_two_layer_stackup(),
        nets={
            "PGND": [("C1", "1", 0.0, 0.0)],
            "GND": [("U1", "VSS", 600.0, 0.0)],
            "AGND": [("R9", "1", 1200.0, 0.0)],
            "+5V": [("U1", "VCC", 1800.0, 0.0), ("R9", "2", 2400.0, 0.0)],
        },
        components={
            "U1": (1, 1200.0, 0.0), "C1": (1, 0.0, 0.0), "R9": (1, 1800.0, 0.0)
        },
    )
    model = _model_with(
        {
            "U1": ("", [("VSS", "VSS", "GND"), ("VCC", "VCC", "+5V")]),
            "C1": ("330uF", [("1", "1", "PGND")]),
            "R9": ("0R", [("1", "1", "AGND"), ("2", "2", "+5V")]),
        }
    )
    return board, model


def _single_zero_ohm_board():
    """One 0 Ω across the domains, and one 330 µF bulk electrolytic to measure to."""
    board = _board_with(
        layers={1: "TOP", 2: "BOTTOM"},
        stackup=_two_layer_stackup(),
        nets={
            "PGND": [("R1", "1", 0.0, 0.0), ("C9", "2", 2400.0, 0.0)],
            "GND": [("R1", "2", 200.0, 0.0), ("U1", "VSS", 1200.0, 0.0)],
        },
        components={
            "R1": (1, 0.0, 0.0),
            "C9": (1, 2400.0, 0.0),
            "U1": (1, 1200.0, 0.0),
        },
    )
    model = _model_with(
        {
            "R1": ("0R", [("1", "1", "PGND"), ("2", "2", "GND")]),
            "C9": ("330uF", [("1", "1", "PGND"), ("2", "2", "PGND")]),
            "U1": ("", [("VSS", "VSS", "GND")]),
        }
    )
    return board, model


def _value_spelled_board(value: str):
    """A single part bridging the two domains whose value field is ``value``.

    The point is the **spelling**, not the topology, so the board is as small as
    the rules allow: one part, two nets, two domains.
    """
    board = _board_with(
        layers={1: "TOP", 2: "BOTTOM"},
        stackup=_two_layer_stackup(),
        nets={
            "PGND": [("R1", "1", 0.0, 0.0)],
            "GND": [("R1", "2", 300.0, 0.0)],
        },
        components={"R1": (1, 0.0, 0.0)},
    )
    model = _model_with({"R1": (value, [("1", "1", "PGND"), ("2", "2", "GND")])})
    return board, model


def _unvalued_bridge_board():
    """A part bridging the two domains that states **no** value at all."""
    board = _board_with(
        layers={1: "TOP", 2: "BOTTOM"},
        stackup=_two_layer_stackup(),
        nets={
            "PGND": [("R7", "1", 0.0, 0.0)],
            "GND": [("R7", "2", 300.0, 0.0)],
        },
        components={"R7": (1, 0.0, 0.0)},
    )
    model = _model_with({"R7": ("", [("1", "1", "PGND"), ("2", "2", "GND")])})
    return board, model


def _model_with(parts: dict[str, tuple[str, list[tuple[str, str, str]]]]):
    """A :class:`DesignModel` from ``{designator: (value, [(pin, name, net)])}``.

    This is the netlist view the three rules read their **structural** facts
    from — R1b's 「two pins in two domains」 and R5's power-stage part pool both
    come through here rather than through geometry, which is what makes them
    statements about the drawing's own connectivity.
    """
    from boardwise.core.model import Component, DesignModel, Net, Pin

    nets: dict[str, Net] = {}
    components: dict[str, Component] = {}
    for designator, (value, pins) in sorted(parts.items()):
        pin_objects = []
        net_pins: dict[str, list[tuple[str, str]]] = {}
        for number, name, net_name in pins:
            pin_objects.append(Pin(number=number, name=name, net=net_name))
            net_pins.setdefault(net_name, []).append((number, name))
        for net_name, entries in net_pins.items():
            nets[net_name] = Net(name=net_name, pins=entries)
        components[designator] = Component(
            uid=designator, designator=designator, value=value, pins=pin_objects
        )
    return DesignModel(components=components, nets=nets)
