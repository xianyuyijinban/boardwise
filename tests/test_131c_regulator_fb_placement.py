"""Task 131 stick 3 (131c): the integration fix and
``pcb-regulator-fb-placement``.

Two things land here, and they are tested together because the second is
unreadable without the first.

**The integration fix.** 131b's ``pcb-regulator-cap-distance`` read a *netlist*
model that the production path never handed it: ``run_pcb_review`` filled
``PcbReviewContext.model`` with the **schematic** view, while the rule's own
docstring claimed it read the PCB view. The two views name the same wires
differently and neither is right by default — on 毕设FOC 1.0.0 the schematic says
``NET11`` where the board says ``$1N66612`` — so the rule measured the right
parts and attributed them to the wrong net. 131c adds ``ctx.pcb_model``, builds
it **per PCB document**, and points the rule at it. Both ends are pinned here:
the wrong rows before (reproduced by passing the schematic model into
``pcb_model``, which is exactly what the old code did) and the right rows after,
in a **real offline ``checkup``** rather than a synthetic call.

**The new rule.** A feedback divider is recognised by the four mechanical
criteria ``rules/params.py`` already established, plus **one** filter — the tap
must reach a regulator's pin whose *name* reads as ``FB`` — because those four
alone cannot tell a feedback divider from a current-sense or an ``EN``
threshold one. Measured across the corpus, the filter is what takes 毕设FOC 1.0.0
from two divider groups to one, and it is pinned on the group it rejects
(``R26``/``R35`` into the STM32's ``PC4``) as well as the one it keeps.

**The acceptance anchor, in the task book's own words:** U11 (LM5164, FB on
``$1N66466``) must be found, and the real suspicious item — ``R14`` sitting on
the ``+5V`` rail rather than at the output node — must be reported. Both are
pinned below, and so is the *number* that makes the second one legible: ``R14``
shares ``+5V`` with the output capacitors, so the net comparison alone cannot
see the problem, and the nearest output capacitor is **745.2 mil** away.

Every fixture here is read-only. Nothing runs an editor or a daemon.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.core.pinrole import pin_role
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import load_epro2_source
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule
from boardwise.rules.pcb.fbplacement import (
    SENSE_CAP_END,
    SENSE_CAP_RAIL,
    RegulatorFbPlacement,
    fb_dividers,
)
from boardwise.rules.pcb.regulator import (
    HF_POOL_FARADS,
    POOL_HF,
    POOL_STORAGE,
    REGULATOR_CATEGORIES,
    RegulatorCapDistance,
    _regulator_readings,
)
from boardwise.rules.facts import default_library_path
from boardwise.core.parts import load_parts

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"

REPO = Path(__file__).resolve().parents[1]


def _shelf() -> PartLibrary:
    """A real shelf with one entry, injected so the synthetic states are pinned."""
    return PartLibrary(parts=[
        PartEntry(key="test.synthreg.c0", mpn="SYNTHREG", lcsc="C0", category="ic.buck")
    ])


# ---------------------------------------------------------------------------
# part 0 — the contract
# ---------------------------------------------------------------------------


def test_the_rule_is_mounted_once_and_says_what_it_is():
    rule = RegulatorFbPlacement()
    assert rule.id == "pcb-regulator-fb-placement"
    assert rule.level == "L1-pcb-geometry"
    assert rule.source == "house rule（岳 2026-10 待裁）"
    assert [r.id for r in BUILTIN_PCB_RULES].count(rule.id) == 1
    for mounted in BUILTIN_PCB_RULES:
        assert isinstance(mounted, PcbRule)
        assert mounted.id.startswith("pcb-")
    # 131c inserted it *after* 131b's rule, not appended: both read the same
    # measurement primitive on the same object, one question further along the
    # power path each.
    ids = [r.id for r in BUILTIN_PCB_RULES]
    assert ids.index("pcb-regulator-fb-placement") == (
        ids.index("pcb-regulator-cap-distance") + 1
    )


def test_no_threshold_constant_exists_yet():
    """131c measures; it must not carry a number waiting for 岳's ruling.

    Same pin 131b carries, asserted over this module's own names.
    """
    import boardwise.rules.pcb.fbplacement as module

    assert [n for n in dir(module) if "DISTANCE_MIL" in n] == []


def test_the_filter_is_the_fb_pin_role_and_nothing_looser():
    """The sieve is exactly 「a regulator's pin named FB」 — pinned from both sides.

    ``FB`` is a strict reading, and that strictness is load-bearing: on the DCDC
    board the ``EN``/``UVLO`` threshold divider ``R7``/``R9`` lands on a
    **regulator's** pin, so 「some regulator pin」 would admit it while
    ``pin_role`` does not. And an LDO with no ``FB`` pin (ROBOT's ``U8`` =
    ``AMS1117-3.3``) contributes nothing at all.
    """
    assert pin_role("FB") == "FB"
    assert pin_role("VFB") == "FB"
    assert pin_role("EN") == "EN", "an EN threshold divider is not a feedback one"
    assert pin_role("SW") == "SW"

    # The **real** shelf: the fixture's regulators are classified by MPN there,
    # and a synthetic shelf would not classify them at all — which is the point
    # of the 「no category, no guessing」 discipline and not something to paper
    # over in a test about a real board.
    library = load_parts(default_library_path())
    # 1.0.0: exactly one FB divider, and the rejected group is named.
    model, _geometry = cli._load_model(FOC_100, view="pcb")
    dividers = fb_dividers(model, library)
    assert [(d.ic, d.upper, d.lower) for d in dividers] == [("U11", "R14", "R21")]
    # The group the mechanical criteria alone would have admitted, and why not.
    assert ("R26", "R35") not in [(d.upper, d.lower) for d in dividers]
    assert model.components["R26"].pins[1].net == "$1N66392"
    assert pin_role(model.components["U1"].pins[31].name or "") is None, (
        "the rejected divider feeds U1 pin 32, PC4, whose name is not FB"
    )

    # The DCDC board: its EN threshold divider's member IS a regulator.
    dcdc = next(FIXTURES.glob("DCDC*.epro2"))
    dcdc_model, _geometry = cli._load_model(dcdc, view="pcb")
    u9 = dcdc_model.components["U9"]
    assert "EN" in [pin_role(p.name) for p in u9.pins], "the corpus has this case"
    # R5/R6 IS a real feedback divider and R7/R9 is the EN threshold one, so
    # the pair is decided by the pin name and not by the topology. U9 itself is
    # absent from the shelf's ic.ldo/ic.buck set (the shelf holds five regulator
    # entries and the TPS560430 is not one of them), so nothing is claimed for
    # this board — a stated consequence of 131b's category discipline, not a
    # gap in the sieve.
    assert fb_dividers(dcdc_model, library) == []
    assert "TPS560430X3FDBVR" not in {
        entry.mpn for entry in library.parts if entry.category in REGULATOR_CATEGORIES
    }

    # ROBOT: an LDO with no FB pin at all is silence, not a row.
    robot, _geometry = cli._load_model(ROBOT, view="pcb")
    assert fb_dividers(robot, library) == []


# ---------------------------------------------------------------------------
# part 0 — the integration fix, structurally
# ---------------------------------------------------------------------------


def test_build_design_model_scopes_to_one_document_without_breaking_callers():
    """The document-scope parameter is **additive**: no argument is the old read.

    131c's parser change is the one that closes the first-document blind spot,
    and the pin that matters is that every existing caller (cli._load_model's
    pcb view, and the tests that call it bare) keeps reading the first document.
    """
    source = load_epro2_source(FOC_100)
    documents = source.documents_of_type("PCB")
    assert len(documents) == 2, "1.0.0 carries PCB1 and PCB2"

    bare = build_design_model(source)
    first = build_design_model(source, documents[0])
    second = build_design_model(source, documents[1])
    # The bare call is exactly the first document, not a merged project.
    assert set(bare.components) == set(first.components)
    assert set(bare.nets) == set(first.nets)
    # And the second document really is a different, much smaller board whose
    # designators overlap the first's (a project reuses C1/R1 across boards), so
    # the pin is on the *count* rather than on disjointness.
    assert len(second.components) == 10
    assert len(first.components) == 122
    assert set(second.components) != set(first.components)


def test_the_runner_hands_each_document_its_own_netlist():
    """``ctx.pcb_model`` is per document, and 1.1.0's PCB1 is the proof.

    1.1.0 places its three regulators on ``PCB1`` (105 components) and none on
    ``PCB3`` (33), the *first* document. A runner that built one model for the
    whole review would see nothing; one that builds it per document sees PCB1.
    """
    source = load_epro2_source(FOC_110)
    by_uuid = {d.uuid: d for d in source.documents_of_type("PCB")}
    sizes = {
        build_design_model(source, document) for document in []  # placeholder
    } if False else {}
    for document in source.documents_of_type("PCB"):
        sizes[document.uuid] = build_design_model(source, document)
    loaded = [sizes[u] for u in sizes]
    counts = sorted(len(m.components) for m in loaded)
    assert counts == [11, 33, 105], counts
    # Only the 105-component document carries a regulator the shelf knows.
    with_regulators = [
        m for m in loaded
        if {r.designator for r in _regulator_readings(m, load_parts(default_library_path()))}
    ]
    assert len(with_regulators) == 1
    assert len(with_regulators[0].components) == 105


def test_a_context_without_a_pcb_model_is_silence_not_a_wrong_answer():
    """``pcb_model=None`` must produce nothing, in both regulator rules.

    This is the mutation the task book asks for: point the rules back at the
    schematic view (or at nothing) and the honest outcome is silence, not a row
    attributed to ``NET11``. Pinned as a contract so a later batch that adds a
    fallback reading knows it has to come here first.
    """
    board = BoardGeometry(source="synthetic", name="SYNTH")
    for rule in (RegulatorCapDistance(), RegulatorFbPlacement()):
        ctx = PcbReviewContext(board=board, board_title="SYNTH", model=object())
        assert rule.check(ctx) == []
    ctx = PcbReviewContext(board=None, board_title="SYNTH", pcb_model=object())
    for rule in (RegulatorCapDistance(), RegulatorFbPlacement()):
        assert rule.check(ctx) == []


def test_the_established_pcb_rules_still_read_the_schematic_model():
    """131c added a field; it did not repoint the rules that were already right.

    ``pcb-decap-distance`` and the IPC pair were established over
    ``ctx.model``. If 131c had moved them, the decap rows in 126b's tables would
    have moved with it — so the pin is that the field they read is unchanged.
    """
    from boardwise.rules.pcb import distance, ipc

    for module, marker in (
        (distance, "ctx.model"),
        (ipc, "ctx.model"),
    ):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "ctx.pcb_model" not in source, (
            f"{module.__name__} was repointed at pcb_model by 131c"
        )
        assert marker in source


# ---------------------------------------------------------------------------
# part 0 — the integration fix, end to end through a real checkup
# ---------------------------------------------------------------------------


def _run_checkup(fixture: Path, out: Path) -> dict:
    """Run the **real** CLI checkup offline and return its report.

    Not a call into :func:`boardwise.cli._cmd_checkup` and not a synthetic
    context: the defect 131c fixes lived in the wiring *between* the runner and
    the rule, so only the real path reproduces it. Nothing here touches an
    editor or a daemon — ``--file`` is the documented offline tier.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "boardwise.cli", "checkup",
            "--file", str(fixture), "--out", str(out),
        ],
        cwd=REPO, capture_output=True, text=True,
        # The report is written in Chinese and the console codepage on this
        # machine is GBK, so the default decode raises inside the reader thread
        # and the captured text is silently empty. utf-8 with a replace fallback
        # is what the assertion below actually needs: it only checks for a
        # traceback and for the report file existing.
        encoding="utf-8", errors="replace",
    )
    # exit 1 is 「ERROR present」 and is expected on these fixtures; the report is
    # still written, and a crash is not.
    assert "Traceback" not in result.stderr, result.stderr
    report = out / "report.json"
    assert report.is_file(), f"no report written: {result.stdout}\n{result.stderr}"
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checkup_100(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("checkup_100")
    return _run_checkup(FOC_100, out)


def _cap_rows(report: dict) -> list[dict]:
    return [f for f in report["findings"] if f["rule_id"] == "pcb-regulator-cap-distance"]


def test_the_real_checkup_reports_the_output_caps_on_their_own_nets(checkup_100):
    """**The flip.** U5 and U6's output rows now name the board's own nets.

    Before 131c, in a real ``checkup`` on this fixture, the schematic view's
    ``NET11`` / ``NET3`` were the nets the rule searched, and both of them
    produced a 「no energy storage capacitor on this net」 row — while ``C3`` and
    ``C64`` sat on the board's real output nets 41.8 and 91.4 mil from the pins.
    The 冤案 131b was written to remove was still live in the shipped path; only
    the test harness (which passed the PCB model by hand) saw the fix.
    """
    rows = _cap_rows(checkup_100)
    assert rows, "the regulator rule fires in a real checkup"
    by_net: dict[str, dict] = {}
    for row in rows:
        nets = row["target"]["net_refs"]
        if nets:
            by_net.setdefault(nets[0], {})[row["message"].split("'")[1] if "'" in row["message"] else ""] = row
    # U5's VOUT is the board's own $1N66612, and C3 is measured on it.
    u5 = [r for r in rows if r["target"]["component_ref"] == "U5"
          and "VOUT" in r["message"]]
    assert any(r["target"]["net_refs"] == ["$1N66612"] for r in u5), (
        "U5's output rows must name the board's own net, not NET11"
    )
    measured = [r for r in u5 if r["target"]["counterpart_ref"]]
    assert measured and measured[0]["target"]["counterpart_ref"] == "C3"
    assert measured[0]["target"]["measurement"] == {
        "kind": "distance", "value": 41.8, "unit": "mil",
    }
    # U6's VOUT likewise, with the storage capacitor it had been missing.
    u6 = [r for r in rows if r["target"]["component_ref"] == "U6"
          and "VOUT" in r["message"]]
    assert any(r["target"]["net_refs"] == ["$1N66627"] for r in u6)
    storage = [r for r in u6 if "energy storage" in r["message"]]
    assert storage and storage[0]["target"]["counterpart_ref"] == "C64", (
        "U6's VOUT storage pool read empty in a real checkup before 131c"
    )
    assert storage[0]["target"]["measurement"]["value"] == 91.4
    # And no row anywhere in the report names a schematic-side NETn output.
    for row in rows:
        assert "VOUT net 'NET" not in row["message"]


def test_the_whole_real_checkup_table_is_pinned(checkup_100):
    """Every ``pcb-regulator-cap-distance`` row the real checkup emits.

    Pinned **from the report**, not from a direct rule call, because the wiring
    is what 131c changed. The numbers are 131b's own, unchanged — only the nets
    they are attributed to are now the board's.
    """
    assert {
        (r["target"]["component_ref"], r["target"]["net_refs"][0] if r["target"]["net_refs"] else "",
         r["target"]["counterpart_ref"],
         (r["target"]["measurement"] or {}).get("value"))
        for r in _cap_rows(checkup_100)
    } == {
        ("U11", "+24V", "", None),
        ("U11", "+24V", "C89", 99.5),
        ("U11", "", "", None),
        ("U5", "+5V", "C93", 521.2),
        ("U5", "+5V", "C5", 95.9),
        ("U5", "$1N66612", "C3", 41.8),
        ("U5", "$1N66612", "", None),
        ("U6", "+5V", "C98", 107.5),
        ("U6", "+5V", "C101", 118.7),
        ("U6", "$1N66627", "C13", 244.8),
        ("U6", "$1N66627", "C64", 91.4),
    }


def test_the_wrong_rows_are_reproducible_and_they_are_different(checkup_100):
    """**Both ends of the flip, in one test.** The pre-fix rows are pinned too.

    The pre-fix behaviour is reproduced *deliberately* rather than recalled: the
    schematic model is put into ``pcb_model`` — which is exactly what the old
    code did, since ``ctx.model`` **was** the schematic model — and the rows that
    come back are asserted here. A reader can therefore see both answers from one
    fixture without checking out the parent commit, and the test fails if the
    fix is reverted because the two tables stop differing.
    """
    # Reproduce the pre-fix wiring exactly: ``ctx.pcb_model`` is the field the
    # rule reads, and the old code filled the *only* netlist field there with
    # the schematic model. So the pre-fix reading is the rule run with the
    # schematic model in the slot 131c now fills with the board's own view.
    schematic, _geometry = cli._load_model(FOC_100, view="schematic")
    source = load_epro2_source(FOC_100)
    from boardwise.parsers.epru import extract_board
    from boardwise.rules.pcb.distance import _board_models

    first_document = source.documents_of_type("PCB")[0]
    board = extract_board(first_document, source.footprints(), source.stats)
    ctx = PcbReviewContext(
        board=board,
        board_title="PCB1",
        model=schematic,
        pcb_model=schematic,  # <- what run_pcb_review used to hand the rule
    )
    findings = RegulatorCapDistance().check_with_library(
        ctx, load_parts(default_library_path())
    )
    wrong = {
        (f.target.component_ref, f.target.net_refs[0] if f.target.net_refs else "",
         f.target.counterpart_ref, (f.target.measurement or {}).get("value"))
        for f in findings
    }
    # The two rows 131c exists to remove.
    assert ("U5", "NET11", "", None) in wrong, (
        "the schematic view is what the old path handed the rule"
    )
    assert ("U6", "NET3", "", None) in wrong
    assert ("U5", "$1N66612", "C3", 41.8) not in wrong, (
        "with NET11 the rule cannot find C3 at all"
    )
    # ... and they are not the fixed table.
    right = {
        (row["target"]["component_ref"],
         row["target"]["net_refs"][0] if row["target"]["net_refs"] else "",
         row["target"]["counterpart_ref"],
         (row["target"]["measurement"] or {}).get("value"))
        for row in _cap_rows(checkup_100)
    }
    assert wrong != right


# ---------------------------------------------------------------------------
# part 1 — the acceptance anchor on 毕设FOC 1.0.0
# ---------------------------------------------------------------------------


def _fb_rows(fixture: Path = FOC_100) -> list:
    schematic, _geometry = cli._load_model(fixture, view="schematic")
    findings, _section = run_pcb_review(
        fixture, model=schematic, rules=[RegulatorFbPlacement()]
    )
    return findings


def test_the_anchor_u11_and_its_divider_are_found():
    """**Anchor 1.** U11 (LM5164, ``FB`` on ``$1N66466``) with R14/R21.

    Exactly one divider on the whole board, and the task book's own figure —
    R14 is the upper leg on ``+5V``, R21 the lower leg on ``PGND``.
    """
    rows = _fb_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.target.component_ref == "U11"
    assert row.target.counterpart_ref == "R14"
    assert row.target.net_refs == ["$1N66466"]
    assert row.severity == "INFO"
    assert row.board == "PCB1"
    assert "R14/R21" in row.message and "U11.5" in row.message
    evidence = " ".join(row.evidence)
    assert "ic.buck" in evidence
    assert "R14 spans '$1N66466' to '+5V'" in evidence
    assert "R21 spans '$1N66466' to 'PGND'" in evidence


def test_the_anchor_distances_are_pinned():
    """**Anchor 2.** The three distances, with their pad pairs.

    ``U11 -> R14`` **37.2 mil** (pads 6/1), ``U11 -> R21`` **47.4 mil** (pads
    5/1), ``U11 -> C92`` (the FB-node capacitor) **638.8 mil** (pads 8/1). The
    legs are tight to the pin; the node capacitor is not, and reporting all
    three is the difference between 「the divider is here」 and 「the node is
    filtered here」.
    """
    row = _fb_rows()[0]
    assert "upper leg R14 at 37.2 mil (pads 6 / 1)" in row.message
    assert "lower leg R21 at 47.4 mil (pads 5 / 1)" in row.message
    assert "FB-node capacitor C92 at 638.8 mil from U11 (pads 8 / 1)" in row.message
    assert row.target.measurement == {
        "kind": "distance", "value": 37.2, "unit": "mil",
    }


def test_the_anchor_sense_point_is_reported_with_both_nets_quoted():
    """**Anchor 3, and the one the task book calls 「真实可疑项」.**

    ``R14``'s non-tap end is on ``+5V``. The rule reports the net comparison
    (same net as the output capacitors → :data:`SENSE_CAP_END`) **and** the
    distance that makes it interesting: the nearest energy-storage capacitor on
    the output node is ``C101`` at **745.2 mil** from ``R14``. Both sides of the
    comparison are in the row so a reader can reject the premise, not just the
    tool's conclusion.
    """
    row = _fb_rows()[0]
    assert SENSE_CAP_END in row.message
    assert SENSE_CAP_RAIL not in row.message, (
        "R14 is on +5V, the net the output capacitors sit on, so the net "
        "comparison says the output-capacitor end"
    )
    assert "'+5V'" in row.message
    assert "C101 at 745.2 mil from the upper leg R14" in row.message
    assert "energy storage" in row.message, "the pool label names which capacitor"
    evidence = " ".join(row.evidence)
    # How the output node was established is stated, not assumed: U11 has no
    # pin named VOUT, so the answer came from the inductor after the switch node.
    assert "no pin name resolves to OUT" in evidence
    assert "$1N66672" in evidence and "inductor" in evidence


def test_the_buck_output_node_comes_from_the_inductor_and_is_stated_as_such():
    """A buck names no output pin, so the answer comes from the inductor.

    1.0.0's U11 (LM5164) has ``SW`` on ``$1N66672`` and no pin whose name
    resolves to OUT, so the output is taken one hop through ``L4`` to ``+5V``.
    The row has to **say that**, because it is a walk and not a declaration: a
    reader who believes the output is somewhere else can see the step and reject
    it. The docstring of the LDO branch below is deliberately *not* tested here,
    because no fixture in the corpus has a feedback divider on an LDO — the
    AMS1117 (ROBOT) and the two TPLP2981/RT9013 (1.1.0) have no ``FB`` pin at
    all. The branch is pinned synthetically instead, so the claim is not
    carried by a case that does not exist.
    """
    row = _fb_rows()[0]
    evidence = " ".join(row.evidence)
    assert "no pin name resolves to OUT" in evidence
    assert "one hop from the switching net $1N66672 through the inductor" in evidence
    assert "a buck's output is behind the inductor" in evidence
    # And the SW net itself is NOT claimed as the output.
    assert "this regulator's output pin net(s): +5V" in evidence
    assert "this regulator's output pin net(s): $1N66672" not in evidence


def test_an_ldo_style_output_is_read_off_its_out_named_pin():
    """The other branch, built synthetically because no fixture exercises it.

    The corpus has no feedback divider on an LDO, so asserting the OUT-pin
    branch against a fixture would be asserting nothing. Built here instead: an
    IC with a ``VOUT``-named pin, and the reading must come off that pin with
    no inductor walk at all.
    """
    from boardwise.rules.pcb.fbplacement import _output_nets_of

    component = Component(
        uid="u-U1", designator="U1", mpn="SYNTHREG", lcsc_part="C0",
        pins=[
            Pin("1", "GND", "PGND"),
            Pin("2", "VOUT", "OUT_RAIL"),
            Pin("3", "VIN", "+24V"),
            Pin("4", "SW", "SW_NODE"),
        ],
    )
    reading = type("R", (), {"component": component, "designator": "U1"})()
    nets, basis = _output_nets_of(reading, DesignModel())
    assert nets == ("OUT_RAIL",)
    assert "OUT role" in basis
    assert "inductor" not in basis, (
        "an IC that names its output is not walked through anything"
    )


def test_an_unestablished_output_node_is_not_judged_as_a_rail_verdict():
    """No output node means no sense-point answer — the row says so instead.

    The failure mode this guards is the one that would make the rule assert a
    defect it did not establish: with an empty ``output_nets`` the comparison
    has nothing to compare against, and defaulting it to 「rail」 would dress a
    missing reading as a finding.
    """
    library = _shelf()
    from boardwise.rules.pcb.fbplacement import _output_nets_of

    # An IC with no pin whose name reads as OUT or SW.
    component = Component(
        uid="u-U1", designator="U1", mpn="SYNTHREG", lcsc_part="C0",
        pins=[Pin("1", "GND", "GND"), Pin("2", "VIN", "+24V")],
    )
    nets, basis = _output_nets_of(
        type("R", (), {"component": component, "designator": "U1"})(), DesignModel()
    )
    assert nets == ()
    assert "no pin name resolves to the OUT or SW role" in basis


# ---------------------------------------------------------------------------
# part 1 — the other boards
# ---------------------------------------------------------------------------


def test_1_1_0_finds_its_buck_on_pcb1_only():
    """1.1.0: one row, on ``PCB1``, and silence on the other two documents.

    1.1.0's ``PCB3`` is the backup's *first* document and places no regulator;
    ``PCB1`` (105 components) places all three. That the row appears at all is
    131c's document-scoping working, on the board the earlier scope left blind.
    """
    rows = _fb_rows(FOC_110)
    assert len(rows) == 1
    assert rows[0].board == "PCB1"
    assert rows[0].target.component_ref == "U7"
    assert "R20/R23" in rows[0].message
    assert "upper leg R20 at 646.4 mil" in rows[0].message
    assert "FB-node capacitor C22 at 38.8 mil" in rows[0].message


def test_robot_names_no_feedback_divider():
    """ROBOT's only regulator is an AMS1117-3.3, which has no ``FB`` pin.

    Silence, and the rule still ran — the ``checksRun`` assertion below is what
    distinguishes 「ran and found nothing」 from 「was never asked」.
    """
    schematic, _geometry = cli._load_model(ROBOT, view="schematic")
    findings, section = run_pcb_review(
        ROBOT, model=schematic, rules=[RegulatorFbPlacement()]
    )
    assert findings == []
    model, _geometry = cli._load_model(ROBOT, view="pcb")
    assert {r.designator for r in _regulator_readings(model)} == {"U8"}
    assert pin_role("") is None
    assert all(
        "pcb-regulator-fb-placement" in b["checksRun"] for b in section["boards"]
    )


def test_llc_names_no_regulator_either():
    """llc's shelf has no ``ic.ldo`` / ``ic.buck`` entry, so the rule is silent."""
    model, _geometry = cli._load_model(LLC, view="pcb")
    assert _regulator_readings(model) == []
    schematic, _geometry = cli._load_model(LLC, view="schematic")
    findings, section = run_pcb_review(
        LLC, model=schematic, rules=[RegulatorFbPlacement()]
    )
    assert findings == []
    assert all(
        "pcb-regulator-fb-placement" in b["checksRun"] for b in section["boards"]
    )


def test_an_en_threshold_divider_on_a_real_regulator_is_not_a_feedback_one():
    """**The role half of the sieve, on a board where the category half passes.**

    The DCDC fixture's ``R7``/``R9`` would be the perfect case except that
    ``U9`` (TPS560430) is not in the shelf's regulator set, so it is rejected by
    the *category* half and proves nothing about the *role* half. So the case is
    built here, where the member **is** ``ic.buck`` and its pin is named ``EN``:
    the mechanical criteria hold (upper leg on ``+12V``, tap shared, lower leg
    grounded, tap loaded) and only the ``FB`` role stands between it and a
    finding.

    This is the assertion that makes the role test load-bearing. Delete the role
    check and this becomes a reported 「feedback divider」 on an enable pin —
    which is what 126b's net-pooled reading looked like on ``+5V``, and exactly
    the false positive the sieve exists to prevent.
    """
    def _resistor(designator: str, a: str, b: str) -> Component:
        return Component(
            uid=f"u-{designator}", designator=designator, value="100k",
            pins=[Pin("1", "1", a), Pin("2", "2", b)],
        )

    ic = Component(
        uid="u-U1", designator="U1", mpn="SYNTHREG", lcsc_part="C0",
        pins=[
            Pin("1", "GND", "PGND"),
            Pin("2", "VIN", "+12V"),
            Pin("3", "EN/UVLO", "EN_TAP"),
            Pin("4", "FB", "FB_TAP"),
        ],
    )
    components = [
        ic,
        _resistor("R1", "+12V", "EN_TAP"),      # upper leg of the EN threshold
        _resistor("R2", "EN_TAP", "PGND"),     # lower leg
        _resistor("R3", "+5V", "FB_TAP"),      # upper leg of the real divider
        _resistor("R4", "FB_TAP", "PGND"),     # lower leg
    ]
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for component in components:
        for pin in component.pins:
            if pin.net:
                nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                    (component.designator, pin.number)
                )
    model.nets = nets

    dividers = fb_dividers(model, _shelf())
    assert [(d.ic, d.upper, d.lower, d.tap_net) for d in dividers] == [
        ("U1", "R3", "R4", "FB_TAP"),
    ], "the EN threshold divider must not be reported as a feedback one"
    # And the two are told apart by the role alone: same IC, same category,
    # same tap shape, one name different.
    assert pin_role("EN/UVLO") == "EN"
    assert pin_role("FB") == "FB"


def test_a_regulator_whose_fb_pin_reaches_no_divider_says_so():
    """A named ``FB`` pin with no divider on its net is one row, not silence.

    「This regulator has no feedback network drawn」 is actionable; silence
    would read as a clean bill of health. Built synthetically because no fixture
    has the case, and the synthetic board is where an unexercised branch belongs.
    """

    def _pad(component: str, pin: str, *, x: float, y: float, net: str) -> PadGeometry:
        return PadGeometry(
            id=f"{component}.{pin}", component=component, pin_number=pin, net=net,
            layer_id=1, x=x, y=y, width=40.0, height=40.0, shape="RECT", angle=0.0,
        )

    component = Component(
        uid="u-U1", designator="U1", mpn="SYNTHREG", lcsc_part="C0",
        pins=[Pin("1", "GND", "PGND"), Pin("2", "FB", "FB_NET"), Pin("3", "VIN", "+24V")],
    )
    model = DesignModel(components={"U1": component})
    model.nets = {"FB_NET": Net(name="FB_NET", pins=[("U1", "2")])}
    board = BoardGeometry(
        source="synthetic", name="SYNTH",
        components=[ComponentPlacement(id="c-U1", designator="U1", x=0.0, y=0.0, layer_id=1)],
        pads=[_pad("U1", "1", x=0.0, y=0.0, net="PGND"),
              _pad("U1", "2", x=0.0, y=0.0, net="FB_NET"),
              _pad("U1", "3", x=0.0, y=0.0, net="+24V")],
    )
    ctx = PcbReviewContext(board=board, board_title="SYNTH", pcb_model=model)
    rows = RegulatorFbPlacement().check_with_library(ctx, _shelf())
    assert len(rows) == 1
    assert "no feedback divider reaches it" in rows[0].message
    assert "FB_NET" in rows[0].message
    assert rows[0].severity == "INFO"
    assert rows[0].target.net_refs == ["FB_NET"]


def test_a_regulator_with_no_fb_pin_at_all_produces_nothing():
    """The other half of the branch, and the one no fixture exercises.

    131b's own row already names the unclassified pin names for a part like
    this; a second row saying 「no FB pin」 would duplicate that without adding
    anything, so the rule stays out of it.
    """
    component = Component(
        uid="u-U1", designator="U1", mpn="SYNTHREG", lcsc_part="C0",
        pins=[Pin("1", "GND", "PGND"), Pin("2", "VOUT", "OUT"), Pin("3", "VIN", "+24V")],
    )
    model = DesignModel(components={"U1": component})
    model.nets = {"OUT": Net(name="OUT", pins=[("U1", "2")])}
    board = BoardGeometry(
        source="synthetic", name="SYNTH",
        components=[ComponentPlacement(id="c-U1", designator="U1", x=0.0, y=0.0, layer_id=1)],
    )
    ctx = PcbReviewContext(board=board, board_title="SYNTH", pcb_model=model)
    assert RegulatorFbPlacement().check_with_library(ctx, _shelf()) == []


# ---------------------------------------------------------------------------
# part 1 — the pools and the categories are the same objects as 131b's
# ---------------------------------------------------------------------------


def test_this_rule_reuses_131b_s_pools_and_categories_rather_than_reinventing_them():
    """裁定 ③'s 1 µF floor and the two shelf categories, shared by value.

    The nearest-output-capacitor reading files a part into 裁定 ③'s pools through
    :func:`~boardwise.rules.pcb.regulator.regulator_role`, so 「energy storage」
    means the same thing here as in 131b's rows. Pinned over the *identities*,
    because two modules growing separate copies of a boundary is how 127b's
    ``4.7uF`` disagreement happened in the first place.
    """
    import boardwise.rules.pcb.fbplacement as fb
    import boardwise.rules.pcb.regulator as reg

    assert fb.REGULATOR_CATEGORIES is reg.REGULATOR_CATEGORIES
    assert fb.POOL_HF is reg.POOL_HF
    assert fb.POOL_STORAGE is reg.POOL_STORAGE
    assert fb.regulator_role is reg.regulator_role
    assert reg.HF_POOL_FARADS == 1e-6
