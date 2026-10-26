"""Tests for task 126 stick 1 (126a): the PCB review plumbing (地基).

126a built the **plumbing** the PCB rules run on. 126b filled the rule list
with the two distance rules, so three of this file's pins were **flipped** by
that stick rather than broken by it, and each flipped pin says why inline:

* the ``PcbRule`` / ``PcbReviewContext`` contract (架构钉 1) is unchanged, and
  the structure gate moved from "the list is empty" (126a's honest statement of
  a 地基 with no rules) to "the list is the distance pair, in that order" — the
  gate was always about the list being the truth, not about it being empty;
* :func:`build_module_of` — the two-source module attribution and its
  **priority** (架构钉 2: an engineer-declared ``intent.blocks[].parts`` beats the
  report's own ``modules[]``; a board with no contract falls back entirely to
  ``modules[]``), exercised on both real fixtures — ROBOT ctrl FOC (has a
  contract) and 毕设FOC (none);
* :func:`run_pcb_review` reading **every** PCB document of a backup and naming
  each by its ``META`` title (架构钉 4), so the three-document 毕设FOC fixture
  yields three ``boards[]`` entries, each with its own component and copper-layer
  count. 126b added the assertion that each board's ``checksRun`` names the two
  rules and that every finding index the section carries is that board's own;
* the CLI's ``pcb_review`` **report section**: present when the offline ``.epro2``
  carries a PCB document, **absent** when it does not (架构钉 5: absent, not
  empty), with the verdict / schema untouched (that is 126d's gate). 126b added
  the runner to ``BUILTIN_PCB_RULES`` and moved its call site **after**
  ``modules_section``; the three properties of that move (summary counts, triage
  module attribution, board index arithmetic) are pinned in
  ``test_126b_pcb_distance_rules.py``, which is where the reorder's own
  regression tests live;
* the recursive ``rulebody_fingerprint`` — the audit trail that the new
  ``rules/pcb/`` subpackage is inside the recipe. The digest has moved twice as
  this tree grew (``9c7cc335`` after 126a, ``a9f76763`` after 126b's
  ``rules/pcb/distance.py``); the numbers are recomputed and pinned at the
  bottom of this file.

The offline fixtures are read-only. Nothing here runs an editor or a daemon.
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise import cli
from boardwise.core.designintent import DesignIntent
from boardwise.core.geometry import BoardGeometry
from boardwise.engines.checkup import modules_section
from boardwise.engines.pcbreview import (
    BUILTIN_PCB_RULES,
    RUNNER_ID,
    build_module_of,
    run_pcb_review,
)
from boardwise.engines.review import BUILTIN_RULES
from boardwise.rules.base import Finding, FindingTarget
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
#: A backup with **no** PCB document — the "段缺席" fixture (架构钉 5).
NO_PCB = FIXTURES / "ProPrj_CH340G_2026-09-13.epro2"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"
ROBOT_INTENT = Path(__file__).resolve().parents[1] / "blocklib" / "intents" / "robot-ctrl-foc.intent.json"


# ---------------------------------------------------------------------------
# the rule base contract (架构钉 1)
# ---------------------------------------------------------------------------


def test_a_pcb_rule_takes_a_context_not_a_design_model():
    """A PCB rule's subject is one PCB document's geometry, not a netlist.

    This is the whole reason the PCB side is a parallel runner: ``PcbRule.check``
    takes a :class:`PcbReviewContext`, and a rule can reach the schematic netlist
    only through ``ctx.model``. Pinned as a shape (the signature differs from
    ``rules.base.Rule.check``) rather than as a behaviour — the behaviours are
    126b/126c's.
    """
    import inspect

    assert list(inspect.signature(PcbRule.check).parameters) == ["self", "ctx"]
    # It is still a ``Rule`` for everything that introspects "is this a rule?".
    from boardwise.rules.base import Rule

    assert issubclass(PcbRule, Rule)


def test_the_context_carries_the_five_facts_a_pcb_rule_reads():
    """钉 1's context fields, by name — the runner fills every one of them.

    **131c added the sixth.** ``pcb_model`` is the netlist view of the PCB
    document in hand, and it exists because the two views do not agree on net
    names (``$1N66612`` vs ``NET11`` on 毕设FOC 1.0.0) and because the default
    :func:`~boardwise.parsers.epro2_model.build_design_model` reads only the
    *first* PCB document. The five 钉 1 fields are unchanged — this is an
    addition, not a reshaping, which is what this pin is for.

    **151 added the seventh.** ``board_uuid`` is the PCB document's own
    ``META.board`` — the container's declared link to a schematic
    :class:`~boardwise.core.model.BoardRef`. 151's footprint rule needs it
    because it reads the *schematic* model by designator, and on the 毕设FOC
    project "which board am I comparing against" cannot be answered by title or
    by designator overlap (Board1 and Board3 both own ``R1``…``R6``). Same
    shape as 131c's addition: one more declared fact, nothing reshaped, and the
    default is empty so a synthetic context is unaffected.
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(PcbReviewContext)}
    assert fields == {
        "board", "board_title", "model", "intent", "module_of", "pcb_model",
        "board_uuid",
    }
    ctx = PcbReviewContext(board=BoardGeometry(), board_title="PCB1")
    assert (
        ctx.model is None and ctx.intent is None
        and ctx.module_of == {} and ctx.pcb_model is None
        and ctx.board_uuid == ""
    )


def test_the_builtin_pcb_rule_list_is_the_126b_distance_pair_then_the_126c_pair():
    """126b flipped this pin from "empty" to "the distance pair, in order";
    126c appended the IPC pair.

    126a pinned ``BUILTIN_PCB_RULES == []`` as the honest statement of a 地基
    with no rules. 126b is the batch that landed the first two, so the pin
    becomes the **structure gate the task book always meant**: the list is the
    truth, its order is the execution order, and both are pinned by value so a
    rule that exists but is not listed — or is listed in the wrong place — is
    caught here rather than by a reader wondering why a report is quiet.

    The order is declaration order and is asserted as a list, not as a set: the
    rules are independent (none reads another's output), so the order is a
    *reading* choice, and pinning it is what stops a later batch from reordering
    by accident. 126c appended its two to the end rather than interleaving them,
    which is why this pin reads as 「house rules first (126b), then the
    standards-derived readings (126c)」 with **131b's** regulator rule inserted
    inside the house-rule block — after ``pcb-decap-distance``, because it
    answers the same measurement question on a narrower object (one regulator's
    VIN/VOUT pins rather than every IC's every supply net). Both are still
    re-sorted by severity per board before a reader sees them, so the
    declaration order is about the report's ``checksRun``, not about which row
    comes first.

    ``BUILTIN_RULES`` (the schematic set — 22 since 064, and not this file's
    number to own) is left untouched by this file — read
    rather than re-stated where the point is "this file did not move it", so
    the assertion is that the two lists are separate objects and that the PCB
    one grew on its own.

    **182 appends ``pcb-hs-diffpair-inventory``** (R2-1's ``pcb-keepout-violation``
    stays where it was, still the last of the board-frame sweep group): the new
    row is the high-speed family's *inventory* — one ``INFO`` per differential
    pair — so it lands after every judgement rule, and the 0.6.0 rules that read
    its output will be appended after it.
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
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        "pcb-foc-thermal-via-style",
        "pcb-foc-thermal-via-array",
        "pcb-foc-thermal-exit-path",
        "pcb-footprint-consistency",
        "pcb-polarity-orientation",
        "pcb-silk-designator",
        "pcb-derating-package",
        "pcb-component-spacing",
        "pcb-component-off-board",  # bug98-A, the split-out board-frame rule
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
        "pcb-keepout-violation",  # R2-1, appended last
        "pcb-hs-diffpair-inventory",  # 182, the high-speed family's inventory
    ]
    assert all(isinstance(rule, PcbRule) for rule in BUILTIN_PCB_RULES)
    # The schematic side is untouched by this file: its list is the 011-family
    # set, and it is a *separate object* (mutating one must not touch the other).
    # 22 since 064 added the two selection rules (`sel-tvs-standoff-rail`,
    # `sel-ldo-fixed-output`), 23 since 176 added `path-sampling-bias` — read
    # through ``len`` rather than by value, which is what keeps this pin about
    # "the PCB file did not move the schematic list"; the length belonging to
    # 064/176 is pinned in test_064's own registry test and in test_011d's count.
    assert len(BUILTIN_RULES) == 23
    assert BUILTIN_PCB_RULES is not BUILTIN_RULES


# ---------------------------------------------------------------------------
# module attribution (架构钉 2)
# ---------------------------------------------------------------------------


def test_build_module_of_reads_the_reports_own_modules_section():
    """With no contract, ``module_of`` is exactly what ``modules[]`` says.

    A hand-built ``modules[]`` so the answer is not a property of a fixture: the
    builder is a pure function over two inputs.
    """
    modules = [
        {"name": "power", "basis": "connectivity", "components": ["U1", "C1"]},
        {"name": "sense", "basis": "page", "components": ["U2", "R4"]},
        {"name": "未归属", "basis": "unattributed", "components": ["SCREW1"]},
    ]
    mapping = build_module_of(None, None, modules)
    assert mapping == {
        "U1": "power", "C1": "power", "U2": "sense", "R4": "sense",
        "SCREW1": "未归属",
    }


def test_build_module_of_prefers_the_contract_over_modules():
    """钉 2: the engineer-declared block beats the tool's own reading.

    ``U1`` sits in the report's ``sense-cluster`` module here, but the contract
    says it is the power IC (``power``), so the contract wins for ``U1`` while
    ``C1`` (in no block) keeps the module name.
    """
    contract = DesignIntent(blocks=[_block("power", parts=["U1"])])
    modules = [
        {"name": "sense-cluster", "basis": "connectivity", "components": ["U1", "C1"]},
    ]
    mapping = build_module_of(None, contract, modules)
    assert mapping["U1"] == "power", "the contract overrides the module reading"
    assert mapping["C1"] == "sense-cluster", "a part in no block keeps its module"


def test_build_module_of_keeps_the_first_block_that_names_a_designator():
    """A designator in two blocks is the contract's own ambiguity, not ours.

    On the real ROBOT contract ``U1`` is in **both** ``senseU`` and ``senseW``
    (the MCU is the part both current-sense chains read from). Rather than pick
    last or invent a merge name, the builder takes the **first** block in the
    document's own order and the rest of the mapping stays untouched.
    """
    contract = DesignIntent(blocks=[
        _block("senseU", parts=["U1"]),
        _block("senseW", parts=["U1"]),
    ])
    mapping = build_module_of(None, contract, [])
    assert mapping == {"U1": "senseU"}


def test_build_module_of_on_the_real_robot_contract_overrides_the_module_reading():
    """The ROBOT fixture end-to-end: contract wins, module reading fills the rest.

    Reads the real ``robot-ctrl-foc.intent.json`` and the real ``modules[]`` the
    checkup build produces for the ROBOT board. Asserts only what the contract
    states (its five block ids) and that a part in no block still gets a module —
    not a fixture-specific cluster name.
    """
    contract = DesignIntent.load(ROBOT_INTENT)
    model, _board = cli._load_model(ROBOT, view="schematic")
    modules, _facts = modules_section(model=model, findings=[])
    mapping = build_module_of(model, contract, modules)

    # The contract's own order decides where a designator is in two blocks, so
    # the expectation is built the same way (first block wins).
    block_of: dict[str, str] = {}
    for block in contract.blocks:
        for ref in block.parts:
            block_of.setdefault(ref, block.id)
    for ref, block_id in block_of.items():
        assert mapping[ref] == block_id, ref
    # A part the contract does not name keeps whatever modules[] said — it is in
    # some module (the report never drops an unattributed part).
    others = [ref for ref in model.components if ref not in block_of]
    assert others
    assert any(ref in mapping for ref in others)


def test_build_module_of_on_bishe_foc_falls_back_entirely_to_modules():
    """毕设FOC has no contract, so it is entirely ``modules[]``'s answer.

    No intent is loaded (that is the point). The fixture is a **three-board**
    project, and 34 of its designators appear in more than one board's module
    (``C1`` sits on Board1, Board2 and Board3), so the equality is checked the
    way the builder actually resolves them: first module in the list that claims
    a designator wins. The pin is "the contract contributed nothing", not a
    specific winner.
    """
    model, _board = cli._load_model(FOC, view="schematic")
    modules, _facts = modules_section(model=model, findings=[])
    assert modules, "the fixture yields modules to fall back to"
    mapping = build_module_of(model, None, modules)

    expected: dict[str, str] = {}
    for entry in modules:
        for ref in entry.get("components") or []:
            expected.setdefault(ref, entry["name"])
    assert mapping == expected
    # A multi-board project really does collide, or the test above would pass on
    # any board: pin the collision so the first-wins resolution stays deliberate.
    claimed = [
        ref for ref in mapping
        if sum(ref in (entry.get("components") or []) for entry in modules) > 1
    ]
    assert claimed, "the fixture has designators on several boards"


def _block(block_id: str, parts: list[str]):
    from boardwise.core.designintent import IntentBlock

    return IntentBlock(id=block_id, parts=parts)


# ---------------------------------------------------------------------------
# the runner reads every PCB document (架构钉 4)
# ---------------------------------------------------------------------------


def test_run_pcb_review_reads_every_pcb_document_of_the_foc_fixture():
    """The three-document fixture yields three ``boards[]`` entries.

    毕设FOC's measured identity (040b / 125a, not guessed here): PCB3 (33 parts,
    2-layer), PCB1 (105 parts, 4-layer), PCB2 (11 parts, 2-layer). Documents are
    named by their ``META`` title and **every** one runs — the runner must not
    collapse to a single "main" board (that magic-count idiom is what 125a's
    test used for its own anchor, and 126 钉 4 forbids it here).

    **126b changed what runs**: the two distance rules now execute on each
    document, so ``checksRun`` names them and the documents carry findings. The
    *structure* assertions here are 126a's and unchanged — three boards, named
    by title, each with its own component and copper-layer count. The findings'
    content is 126b's and is pinned in ``test_126b_pcb_distance_rules.py``;
    what is asserted here is that the plumbing distributes them across the
    right documents (each index in the right range) without assuming how many
    there are, so 126c's IPC rules will not have to touch this test.
    """
    findings, section = run_pcb_review(FOC)
    assert section["available"] is True
    assert section["runner"] == RUNNER_ID
    titles = [board["title"] for board in section["boards"]]
    assert titles == ["PCB3", "PCB1", "PCB2"]
    by_title = {board["title"]: board for board in section["boards"]}
    assert by_title["PCB3"]["components"] == 33
    assert by_title["PCB1"]["components"] == 105
    assert by_title["PCB2"]["components"] == 11
    # copperLayers is read off the physical stackup (125a), not the LAYER table.
    assert by_title["PCB3"]["copperLayers"] == 2
    assert by_title["PCB1"]["copperLayers"] == 4, "PCB1 is the 4-layer driver"
    assert by_title["PCB2"]["copperLayers"] == 2
    # 126b added the two distance rules, **126c appended the two IPC-2221
    # ones**, **131b inserted the regulator rule after the decap one**,
    # **131c inserted the feedback-divider rule after that one** and **131d
    # inserted the crystal rule after that one**, so the executed list is now
    # seven ids in declaration order (the pin's own statement is "the list is
    # the truth, in order"). Only the rule *set* moved; what is asserted here —
    # the plumbing distributing findings across the right documents without
    # assuming how many there are — is unchanged.
    for board in section["boards"]:
        assert board["checksRun"] == [
            "pcb-decap-distance", "pcb-regulator-cap-distance",
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
            "pcb-foc-ground-domains",
            "pcb-foc-ground-tie",
            "pcb-foc-return-path",
            "pcb-foc-thermal-via-style",
            "pcb-foc-thermal-via-array",
            "pcb-foc-thermal-exit-path",
            "pcb-footprint-consistency",
            "pcb-polarity-orientation",
            "pcb-silk-designator",
            "pcb-derating-package",
            "pcb-component-spacing",
            "pcb-component-off-board",  # bug98-A, the split-out board-frame rule
            "pcb-track-ampacity", "pcb-voltage-spacing",
            "pcb-keepout-violation",  # R2-1, the sweep's last
            "pcb-hs-diffpair-inventory",  # 182, the high-speed inventory
        ]
        for index in board["findings"]:
            assert findings[index].board == board["title"]
    assert findings, "126b/126c run four rules; the fixture is not clean"


def test_run_pcb_review_returns_no_section_for_a_backup_with_no_pcb_document():
    """架构钉 5, runner side: no PCB document → ``(findings, None)``.

    ``None``, not an empty section — "there was no PCB to review" is not "the PCB
    was reviewed and nothing was found". Unchanged by 126b: having rules to run
    is not a reason to claim a section for a backup that carries no board.
    """
    findings, section = run_pcb_review(NO_PCB)
    assert findings == []
    assert section is None


def test_run_pcb_review_runs_the_rules_it_is_given_and_stamps_the_board_title():
    """With one stand-in rule, the runner runs it once **per PCB document**.

    The rule is a stand-in (126b/126c write the real ones): it exists here to pin
    the *plumbing* — a rule is handed a context whose ``board`` is that document's
    geometry, and each returned finding carries the document's ``META`` title in
    ``finding.board`` (架构钉 4), so the schematic side's board titles and the PCB
    side's never collide.
    """
    seen: list[str] = []

    class _Probe(PcbRule):
        id = "pcb-probe-standin"
        title = "stand-in"
        source = "house rule（岳 2026-10 待裁）"

        def check(self, ctx: PcbReviewContext) -> list[Finding]:
            seen.append(ctx.board_title)
            return [Finding(
                rule_id=self.id, severity="INFO", message="stand-in",
                level="L1", evidence=[f"{ctx.board_title} probe"],
                target=FindingTarget(component_ref="U1"),
            )]

    findings, section = run_pcb_review(FOC, rules=[_Probe()])
    assert seen == ["PCB3", "PCB1", "PCB2"], "one context per PCB document"
    assert [f.board for f in findings] == ["PCB3", "PCB1", "PCB2"]
    # Every finding belongs to its board's index range in the section.
    for board in section["boards"]:
        for index in board["findings"]:
            assert findings[index].board == board["title"]
    # checksRun now names what actually ran.
    assert all(board["checksRun"] == ["pcb-probe-standin"] for board in section["boards"])


# ---------------------------------------------------------------------------
# the CLI report section (架构钉 5)
# ---------------------------------------------------------------------------


def test_checkup_offline_with_a_pcb_document_carries_the_pcb_review_section(
    capsys, tmp_path, monkeypatch
):
    """离线 ``.epro2`` + PCB 文档 → ``pcb_review`` 段 + findings 合并点就位.

    Runs the real ``checkup --file`` on the 毕设FOC fixture. Asserts: the section
    is present, its ``boards`` carry the three documents, the runner is named,
    and the section coexists with everything else — the schema stays ``/6`` and
    the verdict is untouched (126d owns the verdict gate and the bump to /7).

    **126b changed the middle of this**: the section is no longer finding-free,
    because the two distance rules are in ``BUILTIN_PCB_RULES`` and the fixture
    is not clean. What 126a was pinning — the section's *presence*, its three
    documents, the runner id, the unchanged schema, and the merge's index
    arithmetic — is unchanged and still asserted here; the ``pcb-`` rows in
    ``findings`` are 126b's and are pinned in ``test_126b`` and by the merge
    test below. The stand-in injection is gone for the same reason: there are
    now real PCB rules to run, so injecting one would only add a third id to
    the same array and prove nothing the real rules do not.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "foc"
    code = cli.main([
        "checkup", "--file", str(FOC), "--out", str(out), "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    assert "pcb_review" in report, "a backup with a PCB document carries the section"
    section = report["pcb_review"]
    assert section["available"] is True
    assert section["runner"] == RUNNER_ID
    assert [board["title"] for board in section["boards"]] == ["PCB3", "PCB1", "PCB2"]
    # 126b added the two distance rules, **126c added the two IPC-2221 ones**,
    # **131b added the regulator capacitor rule**, **131c the feedback-
    # divider rule** and **131d the MCU crystal rule**; their findings are in
    # the one array
    # too. Note what is *not* here:
    # `pcb-track-ampacity` produces no row on this fixture, because 毕设FOC has
    # **no design-intent contract** and the rule's subject is the contract's net
    # — 92 UNKNOWN rows saying "nobody declared a current" would be a wash. That
    # absence is 126c's own discipline, pinned in `test_126c_pcb_ipc_rules.py`,
    # and is asserted here only as "the id set is the two that fired".
    # `pcb-regulator-cap-distance` does fire here, on Board1, where 毕设FOC's
    # three regulators live (`U7` = the LM5164 buck, `U11`/`U13` = the two
    # LDOs) — the rules are mounted and the checkup path reaches them. What is
    # *not* asserted here is its row set: `test_131b_regulator_cap_distance.py`
    # owns those numbers, and this test only pins that the id appears in the one
    # merged `findings[]` array. 131c's `pcb-regulator-fb-placement` fires on the
    # same board for the same reason and its rows are owned by
    # `test_131c_regulator_fb_placement.py`; 131d's
    # `pcb-mcu-crystal-placement` fires on Board1 too (the STM32H743's `U1` with
    # its `X1` crystal) and its rows are owned by
    # `test_131d_mcu_crystal_placement.py`; 131e's `pcb-mcu-supply-groups` and
    # `pcb-mcu-reset-boot` fire on Board1 for the same reason (the same H743,
    # read as supply groups and as a reset/boot inventory) and their rows are
    # owned by `test_131e_mcu_supply_reset.py`. 131f's
    # `pcb-mcu-crystal-keepout` fires on the **same** `X1` — it reads that same
    # crystal along the other axis, so the set below grew by exactly one id,
    # and its rows are owned by `test_131f_mcu_crystal_keepout.py`.
    pcb_rows = [f for f in report["findings"] if f["rule_id"].startswith("pcb-")]
    assert pcb_rows, "the rules are in BUILTIN_PCB_RULES and several fire here"
    # **133b moved the PCB family, and this pin moved with it** — the five FOC
    # rules are in ``BUILTIN_PCB_RULES`` and four of them fire on 毕设FOC
    # 1.1.0's PCB1/PCB3, so they belong in the set. Their own behaviour is
    # `test_133b_foc_rules.py`'s subject; this pin says only that they ran.
    # **182 moved it once more**: ``pcb-hs-diffpair-inventory`` fires here with
    # two INFO rows on PCB1 (``D+/D-`` declared ``DP1`` and ``CAN_H/CAN_L``
    # declared ``DP2``), pinned in `tests/test_182_highspeed_scaffold.py`. The
    # claim this pin makes — the mounted rules reach the merged ``findings[]``
    # array through ``checkup --file`` — is unchanged.
    assert {f["rule_id"] for f in pcb_rows} == {
        "pcb-decap-distance", "pcb-regulator-cap-distance",
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
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        "pcb-foc-thermal-via-style",
        "pcb-foc-thermal-via-array",
        "pcb-foc-thermal-exit-path",
        "pcb-footprint-consistency",
        "pcb-polarity-orientation",
        "pcb-silk-designator",
        "pcb-derating-package",
        "pcb-component-spacing", "pcb-voltage-spacing",
        "pcb-hs-diffpair-inventory",  # 182, the high-speed inventory
    }
    # 126a did not touch the schema or the verdict; **126d did**, by bumping the
    # id to `/7` and adding `coverage.pcbReviewMissing`. This fixture has PCB
    # documents and the runner ran, so the new gate does not fire and the verdict
    # is exactly what it was before 126d — which is the point of pinning it here:
    # a `/7` bump that changed every offline verdict would have shown up in this
    # assertion. `test_126d_pcb_verdict_gate.py` is where the gate itself is
    # pinned, in all three states.
    assert report["schema"] == "boardwise.checkup/7"
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert report["completion"]["verdict"]  # whatever the fixture says, unchanged
    assert isinstance(code, int)


def test_checkup_offline_without_a_pcb_document_the_section_is_absent(
    capsys, tmp_path, monkeypatch
):
    """架构钉 5, CLI side: no PCB document → **no** ``pcb_review`` key.

    ``ProPrj_CH340G`` carries no PCB document. The report must not carry an empty
    section: absence says "nothing was reviewed", an empty section would read as
    "the PCB was reviewed and found clean".
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "no-pcb"
    cli.main([
        "checkup", "--file", str(NO_PCB), "--out", str(out), "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert "pcb_review" not in report, "absent, not empty"


def test_checkup_merges_pcb_findings_into_the_one_findings_array(
    capsys, tmp_path, monkeypatch
):
    """A PCB finding lands in the **same** ``findings[]``, with a real index.

    The stand-in rule is injected into ``BUILTIN_PCB_RULES`` (which the runner
    reads at call time) so the merge path is exercised end to end without any
    126b rule existing yet. What is pinned: the finding is in the one array the
    module walk and review-mark read, its ``board`` is the PCB document's title,
    and ``pcb_review.boards[].findings`` indexes that array correctly — i.e. the
    offset arithmetic is right, not off by the schematic findings' count.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "boardwise.engines.pcbreview.BUILTIN_PCB_RULES",
        [_StandInRule()],
        raising=True,
    )
    out = tmp_path / "merged"
    cli.main([
        "checkup", "--file", str(FOC), "--out", str(out), "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    pcb_rows = [row for row in report["findings"] if row["rule_id"] == _STANDIN_ID]
    # One per PCB document, all three of them.
    assert len(pcb_rows) == 3
    assert [row["board"] for row in pcb_rows] == ["PCB3", "PCB1", "PCB2"]

    section = report["pcb_review"]
    assert section["runner"] == RUNNER_ID
    for board in section["boards"]:
        # Every index the section names must point at a finding that really is
        # that board's stand-in row in the merged array.
        assert board["findings"], "the merged section still carries indices"
        for index in board["findings"]:
            row = report["findings"][index]
            assert row["rule_id"] == _STANDIN_ID
            assert row["board"] == board["title"]


_STANDIN_ID = "pcb-standin-126a"


class _StandInRule(PcbRule):
    """A stand-in PCB rule that always reports one INFO finding per board."""

    id = _STANDIN_ID
    title = "stand-in"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return [Finding(
            rule_id=self.id, severity="INFO", message="stand-in", level="L1",
            evidence=[ctx.board_title], target=FindingTarget(component_ref="U1"),
        )]


# ---------------------------------------------------------------------------
# the rulebody digest now covers the subpackage (架构钉 4 / 126 侦察结论)
# ---------------------------------------------------------------------------


def test_the_rulebody_digest_covers_the_pcb_subpackage():
    """The new ``rules/pcb/`` subpackage is inside the fingerprint's recipe.

    Without this, editing a PCB rule would leave the reported ``rulebody``
    unchanged — the ledger would say "the rules did not change" while the PCB
    side had. Asserted by digest comparison: the recursive recipe over the tree
    *including* ``pcb/`` differs from one computed the old (direct-files-only)
    way, which is exactly why the recipe had to widen.
    """
    import hashlib

    from boardwise.engines.review_eval import rulebody_fingerprint

    rules_dir = Path(__file__).resolve().parents[1] / "src" / "boardwise" / "rules"
    recursive = rulebody_fingerprint(rules_dir)
    assert recursive is not None

    # The old recipe (direct *.py only) over today's tree, with the same
    # CRLF -> LF fold the recursive recipe applies (see the eol entry below).
    old = hashlib.sha256()
    for path in sorted(rules_dir.glob("*.py")):
        old.update(path.name.encode("utf-8"))
        old.update(b"\x00")
        old.update(path.read_bytes().replace(b"\r\n", b"\n"))
    old_digest = old.hexdigest()[:8]

    # The two differ exactly because pcb/ is now in the recipe; the values are
    # the measured audit trail of each change to the tree:
    #   direct-only over this tree: 98b1d462   (126a-126c b04153f3 -> 128 e51b8a86:
    #                                              128 edited rules/facts.py and
    #                                              rules/archclosure.py, both
    #                                              direct files
    #                             -> 129 98b1d462:
    #                                              this batch (#66's refusal
    #                                              predicate, #67's guards and
    #                                              #68's usb-cc window) moved
    #                                              rules/facts.py,
    #                                              rules/railratings.py and
    #                                              rules/unproven.py, all direct
    #                                              files. Recorded, not loosened —
    #                                              the pin's job is to notice a rule
    #                                              body moved without anyone saying
    #                                              why)
    #   recursive (the widened recipe):
    #     9c7cc335 — after pcb/base.py and the FindingTarget widening (126a)
    #     a9f76763 — after rules/pcb/distance.py landed (126b)
    #     62bfe7f8 — after rules/pcb/ipc.py landed (126c)
    #     e3c6645e — after 128 (#63) retired IC_PATTERN out of rules/facts.py
    #                for `core.parts.is_ic_designator`, and corrected the
    #                archclosure docstring that described the retired regex
    #     ab898f6b — after 127b (blind-review fixes) changed the rule bodies of
    #                rules/pcb/distance.py and rules/pcb/ipc.py. Both moved, and
    #                for the same underlying reason: 127a had measured that the
    #                PCB rules were reading a pad's footprint layer as its
    #                physical face, so 127b gave PadGeometry an
    #                `effective_layer_ids` (parser-side) and taught both rule
    #                modules to ask for it. distance.py additionally replaced
    #                the pin-count IC test with the schematic-device-fact test
    #                and split capacitors into bulk / high-frequency pools;
    #                ipc.py gained the same-potential and cross-layer
    #                exemptions. rules/facts.py and rules/archclosure.py were NOT
    #                touched, which is why the direct-only digest above is
    #                unchanged at e51b8a86 — that pair is itself the evidence
    #                that 127b stayed inside rules/pcb/. (59b22cca was the
    #                intermediate value after the behaviour change and before the
    #                measured-claims docstrings were brought up to date; a
    #                docstring is source too, and the pin does not care why.)
    #     bd3c240b — after 129 (#66/#67/#68) changed the rule bodies of
    #                rules/facts.py (the usb-cc ±10 % window, the
    #                unreadable-declaration UNKNOWN, and the order-independent
    #                pull-down search), of rules/railratings.py (the
    #                zero-voltage and zero-limit guards) and of
    #                rules/unproven.py (which gained the refusal predicate the
    #                coverage gate now asks). Both digests moved for the same
    #                reason as every entry above: source is source, and a
    #                docstring that now describes the code is part of it.
    #     e1ac0c59 — after 131b landed rules/pcb/regulator.py, the
    #                `pcb-regulator-cap-distance` rule. One new file inside the
    #                pcb/ subpackage, so only the recursive digest moves and the
    #                direct-only one stays at 98b1d462 — which is itself the
    #                evidence that 131b stayed inside rules/pcb/, exactly as 127b
    #                did before it.
    #     ddd201dd — after 131c. Two files inside `rules/` moved:
    #                `rules/pcb/fbplacement.py` arrived (the new
    #                `pcb-regulator-fb-placement` rule) and
    #                `rules/pcb/regulator.py`'s rule body now reads
    #                `ctx.pcb_model` instead of `ctx.model` — a rule body that
    #                changed, which is the digest doing exactly its job. The
    #                direct-only one stays at 98b1d462 for the fourth time, so
    #                131c also stayed inside the subpackage as a *rule* change.
    #                131c's **third** file, `parsers/epro2_model.py`
    #                (`build_design_model` gained a document-scope argument), is
    #                **outside the recipe by construction** — `rulebody`
    #                digests rule bodies, not the parsers they call. That is a
    #                known and pre-existing limit of what the number claims, and
    #                it is stated here rather than left for a reader to infer
    #                from a digest that did not move.
    #     12874b28 — after 131d. One new file inside the subpackage,
    #                `rules/pcb/crystal.py` (the new `pcb-mcu-crystal-placement`
    #                rule). The direct-only digest stays at 98b1d462 for the
    #                fifth consecutive time, so 131d also stayed inside
    #                `rules/pcb/` as a rule change. (The first value measured
    #                for this batch was c157920f, before the rule body was
    #                tidied to use `distance._mil` — 131b's canonical
    #                rounding — instead of a local `round(x, 1)`. A docstring
    #                and a rounding call are source too, and the pin does not
    #                care why; the number is the number.)
    #                131d's **second** file is `core/pinrole.py` — the OSC
    #                short-circuit that stopped `PF0-OSC_IN` reading as a supply
    #                `IN`. That is **outside the recipe by construction** (the
    #                recipe covers `src/boardwise/rules/`), which is the same
    #                known limit 131c recorded: a report's `rulebody` number
    #                does not move for a change to a helper a rule *calls* from
    #                `core/`, and the report prints the commit alongside for
    #                exactly that reason.
    #     6c3d6168 — after 131e. Two new files inside the subpackage,
    #                `rules/pcb/mcusupply.py` (`pcb-mcu-supply-groups`) and
    #                `rules/pcb/mcureset.py` (`pcb-mcu-reset-boot`) — the MCU
    #                pack's fourth and fifth rules, both house-rule inserts with
    #                every row `INFO` and no distance threshold in force. The
    #                direct-only digest stays at 98b1d462 for the sixth
    #                consecutive time, so 131e also stayed inside `rules/pcb/`
    #                as a rule change.
    #                131e *reads* `core/pinrole.pin_role` and needs three
    #                supply names the table declines (`VREF+` / `VREF-` /
    #                `VREF`, so that 毕设FOC 1.0.0's capacitor-less `VREF` net
    #                is reported empty rather than absent). It adds them in its
    #                **own** module rather than by editing `core/pinrole.py`,
    #                deliberately: `core/` is outside this recipe, so an edit
    #                there would move no number at all, and the residue is
    #                131e's object rather than the classifier's.
    #     f88ca40e — after 131f. One new file inside the subpackage,
    #                `rules/pcb/crystalkeepout.py` (`pcb-mcu-crystal-keepout`).
    #                The direct-only digest stays at 98b1d462 for the seventh
    #                consecutive time, so 131f also stayed inside `rules/pcb/`
    #                as a rule change.
    #                131f's **other** two files are `parsers/epru.py` (POUR
    #                records now parse into `kind="pour"` polygons, so
    #                `stats.unconsumed_types` no longer carries them) and
    #                `core/measure.py` (the new `region_copper` primitive, and
    #                `_net_shape_records` now accepts `kind="pour"`). Both are
    #                **outside the recipe by construction** — the recipe covers
    #                `src/boardwise/rules/` — which is the same known limit
    #                131c and 131d recorded: a report's `rulebody` number does
    #                not move for a change to a parser or a measurement helper a
    #                rule calls, and the report prints the commit alongside for
    #                exactly that reason. 131f is the batch where that limit
    #                bites hardest, because it is a **data-model** change (a
    #                previously-unread record type became real copper) rather
    #                than a wording one.
    #     0bb1cb0b — after 133b. One new file inside the subpackage,
    #                `rules/pcb/foc.py`, carrying all five FOC rules
    #                (`pcb-foc-decap-proximity`, `pcb-foc-ground-plane`,
    #                `pcb-foc-gate-trace-width`, `pcb-foc-track-corners`,
    #                `pcb-foc-power-loop-area`) — the FOC pack's first rules,
    #                all `INFO` with every TI figure quoted and none applied.
    #                The direct-only digest stays at 98b1d462 for the eighth
    #                consecutive time, so 133b also stayed inside `rules/pcb/`
    #                as a rule change.
    #                133b's **other** file is `engines/pcbreview.py` (the
    #                registration of the five ids in `BUILTIN_PCB_RULES`),
    #                which is **outside the recipe by construction** — the
    #                recipe covers `src/boardwise/rules/` and not `engines/`.
    #                That is the same known limit 131c and 131d recorded: a
    #                rule can be registered in the runner without any rule
    #                body moving, and the `rulebody` number will not say so.
    #                The list-order pin in `test_126a`'s own first structure
    #                test is what catches that case.
    #                133a, the batch before, was the **only** one to land
    #                entirely outside the recipe: its primitives went into
    #                `core/measure.py` (`via_geometry`, `track_corner_angle`,
    #                `return_path_projection`), which the recipe does not
    #                cover — so **f88ca40e is unchanged by 133a** and the
    #                move recorded here is 133b's alone.
    #     1149d428 — after 133d. One new file inside the subpackage,
    #                `rules/pcb/focthermal.py`, carrying the three thermal-design
    #                rules (`pcb-foc-thermal-via-style`, `pcb-foc-thermal-via-array`,
    #                `pcb-foc-thermal-exit-path`) — R7 / R8 / R9 of the FOC pack.
    #                The direct-only digest stays at 98b1d462 for the **tenth**
    #                consecutive time, so 133d also stayed inside `rules/pcb/`
    #                as a rule change.
    #                133d's **other** file is `engines/pcbreview.py` (the
    #                registration of the three ids in `BUILTIN_PCB_RULES`),
    #                **outside the recipe by construction** — the third batch to
    #                record this same limit (133b and 133c did too), which is
    #                what makes it a structural property of the recipe rather
    #                than an accident. The list-order pin in `test_126a`'s own
    #                first structure test (extended by 133c and again by 133d)
    #                is what catches it.
    #                133d reads 133a's `via_geometry` queries (`vias_on_pad`,
    #                `via_layers`) and 131f's `region_copper` / `pour_connectivity`
    #                primitives out of `core/measure.py`, which is the same
    #                import-rather-than-re-derive choice 133c made for its
    #                object pools.
    #     1d76f67c — after 133c. One new file inside the subpackage,
    #                `rules/pcb/focground.py`, carrying the three ground-system
    #                rules (`pcb-foc-ground-domains`, `pcb-foc-ground-tie`,
    #                `pcb-foc-return-path`) — R1 / R1b / R5 of the FOC pack.
    #                The direct-only digest stays at 98b1d462 for the **ninth**
    #                consecutive time, so 133c also stayed inside `rules/pcb/`
    #                as a rule change.
    #                133c's **other** file is `engines/pcbreview.py` (the
    #                registration of the three ids in `BUILTIN_PCB_RULES`),
    #                which is **outside the recipe by construction** — the same
    #                limit 133b recorded for itself, and it recurs rather than
    #                being a one-off: the list-order pin in `test_126a`'s own
    #                first structure test (extended by 133c) is what catches it.
    #                133c reads 133a's primitives out of `core/measure.py`
    #                (`return_path_projection`) and 133b's object pools out of
    #                `rules/pcb/foc.py`, which is a choice to import rather
    #                than re-derive: two FOC modules that must agree about what
    #                a bulk electrolytic is, sharing one implementation.
    # Both are measured, not guessed. The recursive digest moves whenever any
    # rule body moves - which is the whole point of the recipe, and the reason
    # this number is updated by hand together with the note in test_017 rather
    # than removed: a stale pin is the signal that the digest moved and nobody
    # recorded why.
    # 135 moved this digest 1149d428 -> 92fa6ff9, and the alarm did its job.
    # The cause was **docstrings only**: `rules/pcb/focthermal.py`'s R9 prose
    # carried the pre-135 island figures (island 42, 24 523 sq mil, ROBOT's
    # single 289-member / 7 494 300 sq mil island), which 135's parsing work
    # made wrong, and 133d's R9 anchors moved with them. No rule **body** moved
    # — `git diff` over `src/boardwise/rules/` is 32 insertions / 11 deletions,
    # all of them prose inside a module or function docstring. The measured
    # numbers themselves are pinned in `tests/test_133d_foc_thermal.py`, so the
    # correction is verified there rather than being a bare digest bump.
    # 138 moved this digest 98b1d462 -> a5a3911a (direct) and 92fa6ff9 ->
    # 07080d07 (recursive), and the alarm did its job. The cause was
    # **docstrings and one guard, in `rules/railratings.py` only** (issue #72):
    # the module docstring's reading-order list now says a package size in a
    # `Value` field is refused rather than read as a rating, and `_rows` asks
    # `core.values.states_package_size` before handing a bare token to the
    # voltage parser. No verdict changed: the behaviour pins are
    # `tests/test_092_rail_ratings.py`, and the direct digest recomputed over
    # HEAD's `railratings.py` alone returns `98b1d462` exactly — measured, not
    # assumed.
    # 064 moved both digests again — a5a3911a -> f9160d36 (direct) and
    # 07080d07 -> 42dc76c6 (recursive) — and the **direct** one moving is this
    # batch's own news: it had held at 98b1d462 from 126b through 131c and then
    # at a5a3911a since 138, because every batch in between landed inside
    # `rules/pcb/` or outside the package. The cause is three files sitting
    # directly in `rules/`: `paramspec.py` (new — the two selection rules),
    # `i18n.py` (their two Chinese names) and `unproven.py` (both ids joined
    # `NET_MEMBERSHIP_RULES`). Measured, not assumed: recomputing this recipe
    # over the tree with `paramspec.py` omitted and `i18n.py`/`unproven.py` read
    # from HEAD returns exactly `a5a3911a` / `07080d07`, i.e. the pre-064 tree —
    # so the move is accounted for by 064's three files and by nothing else.
    # 139's close-out (the rail-voltage key bookkeeping) moved both again —
    # f9160d36 -> 4f056aaf (direct) and 42dc76c6 -> 2243dd42 (recursive) — and
    # the **direct** one moving is the news: the batch landed in
    # `rules/railratings.py` alone, a direct file. The cause is the two contract
    # voltage slots being read as **one** answer (`_stated_rail_voltage`, the
    # writer in `core/railquery.py` writing both) plus the prose that says so;
    # the verdicts are pinned in `tests/test_092_rail_ratings.py` and
    # `tests/test_139_intent_rails.py`. Measured, not assumed: recomputing both
    # recipes over this tree with `railratings.py` read from HEAD returns exactly
    # `f9160d36` / `42dc76c6`, i.e. 064's tree — so the move is 139's one file
    # and nothing else.
    # **151 moved the recursive digest only** — 2243dd42 -> b67694ec — and the
    # **direct** one staying at `4f056aaf` is the news this time: the batch
    # landed entirely inside `rules/pcb/`. Three files there moved: a new
    # `footprint.py` (the `pcb-footprint-consistency` rule), `base.py`
    # (`PcbReviewContext` gained `board_uuid`) and `__init__.py` (the package
    # map's one new line). The engine half of the batch,
    # `engines/pcbreview.py`, is **outside the recipe by construction** — the
    # recipe covers `src/boardwise/rules/` — which is the same known limit
    # 131c/131d/131f recorded: a report's `rulebody` does not move for a change
    # to the runner that calls the rules. Measured, not assumed: recomputing
    # this recipe over the tree with `rules/pcb/footprint.py` omitted and
    # `base.py`/`__init__.py` read from HEAD returns exactly `2243dd42`, i.e.
    # 139's tree. (The value was measured as `357c12ed` first; the batch's own
    # last docstring tidy — the ``CHIP_SIZE_CODES`` table's comment — moved it to
    # `b67694ec`, which is the digest doing its job on prose.)
    # **152 moved the recursive digest only again** — b67694ec -> 315a1e72 — and
    # the **direct** one stays at `4f056aaf` for the twelfth batch running: E2
    # landed entirely inside `rules/pcb/`. Two new files are the cause
    # (`polarity.py` for `pcb-polarity-orientation`, `silk.py` for
    # `pcb-silk-designator`); the other files of the batch — `parsers/epru.py`,
    # `core/geometry.py`, `engines/pcbreview.py` — are outside this recipe by
    # construction, which is the known limit recorded above (152 is the first
    # batch whose *data source* work also lands outside it: the silk shapes and
    # designator text it reads are new fields on `BoardGeometry`). Measured, not
    # assumed: recomputing this recipe over the tree with `polarity.py` and
    # `silk.py` omitted returns exactly `b67694ec`, i.e. 151's tree. (The value
    # was measured as `a38e8e4f` first and as `089b6efa` mid-run — the batch's own
    # last tidy *while the sweep was running*: dropping a now-unused
    # `_box_inside` helper and turning a `min(key=-worst)` into
    # `max(key=worst)` in the silk rule moved it twice more. Both intermediate
    # values were read off half-edited files, which is 151's measurement race
    # exactly; the stable value over the delivered tree is `315a1e72`.)
    # **E2b moved it once more** — 315a1e72 -> 0196dc79 — 岳 2026-10-11 裁
    # 「方向不统一」WARN 降 INFO，改了 polarity.py 的 severity 与文案
    # （test_152 四处期望同步改 INFO）。
    # **153 moved the recursive digest again** — 0196dc79 -> 34fddd02 — and the
    # **direct** one stays at `4f056aaf` for the fourteenth batch running: E3
    # landed entirely inside `rules/pcb/` as well. One new file is the cause
    # (`derating.py`, the `pcb-derating-package` rule) plus a prose line in
    # `rules/pcb/__init__.py`'s package map. 153's other edits —
    # `engines/pcbreview.py` (the registration in `BUILTIN_PCB_RULES`, the
    # docstring note and the import) — are **outside the recipe by
    # construction**, and so is every list-position pin those edits move:
    # `test_126a`'s own first structure test, `test_126b`'s llc pin,
    # `test_126c`'s order pin and `test_151`/`test_152`'s neighbour pins all
    # name the shifted device block by hand, which is what catches a
    # registration that this digest cannot see.
    # **153b moved the recursive digest once more** — 34fddd02 -> aea4ae7b — and
    # the **direct** one stays at `4f056aaf` for the fifteenth batch running: the
    # fix again landed entirely inside `rules/pcb/`, in **one file**,
    # `focground.py`. The cause is the 0 Ω value reading: `pcb-foc-ground-tie`
    # used to read the PCB document's own `component.value`, which is a
    # systematically stale copy (measured: 1.0.0's PCB1 drifts on 37 of 122
    # parts, 1.1.0's on 45 of 105), so 1.0.0's `R48`/`R49` — both `0R` on the
    # schematic page — read as `10K` and the board was reported as 「two 10 kΩ
    # resistors, no 0 Ω at all」. The module now resolves **this document's own
    # schematic page** off `META.board` (`schematic_board_of`, 151/153's chain),
    # prefers its declaration and falls back to the copy only when the page
    # states nothing, writing both views into the row's evidence when they
    # disagree. Measured, not assumed: recomputing this recipe over the tree with
    # `focground.py` read from HEAD returns exactly `34fddd02`, i.e. 153's tree —
    # so the move is that one file and nothing else. The values are pinned in
    # `tests/test_153b_ground_tie_values.py` and the acceptance anchors in
    # `tests/test_133c_foc_ground.py`, which is what makes the bump verified
    # rather than a bookkeeping line.
    # **155a moved the recursive digest once more** — aea4ae7b -> 85a0822b — and
    # the **direct** one holds at `4f056aaf` for the **sixteenth** batch running:
    # 岳 2026-10-11 的两条裁定又整批落在 `rules/pcb/` 内，动的是**四个既有文件**：
    # `focground.py`（0R 单点改成按域对计，每对一行「合规 / 报账 / 不连」）、
    # `foc.py`（R16 的 200 mil 从「引文」变成判定线，`over = gap > 200`）、
    # `crystalkeepout.py`（净空区内**别网铜**升级 WARN）、`distance.py`（两条既有
    # 阈值补上裁定出处，行为未动）。行为锚点在
    # `tests/test_155a_ruling_upgrades.py`、`tests/test_133c_foc_ground.py`、
    # `tests/test_153b_ground_tie_values.py`、`tests/test_133b_foc_rules.py` 与
    # `tests/test_131f_mcu_crystal_keepout.py`，所以 bump 是被验证过的，不是记账。
    # **164c moved the recursive digest once more** — 85a0822b -> f838d122 — and
    # the **direct** one holds at `4f056aaf` for the **seventeenth** batch
    # running: 164c（161 挖洞审计的 F3/F4/F5 + D5 + 两条几何口径）整批落在
    # `rules/pcb/` 内，动的是**五个既有文件**——`derating.py` 与 `polarity.py`
    # （板链为空 + 多板工程时 `if uuid and uuid != …` 恒假、静默命中遍历到的第一块
    # 板：改成 153b 的 `schematic_board_of` 语义，并把「板链读不出、未判断」写进
    # 证据）、`ipc.py`（跨板电压冲突落进 notes、负压轨不再被 `value <= 0.0` 丢掉、
    # UNKNOWN 文案分清「没有源报电压」与「两源互相矛盾」）、`distance.py`（去耦距离
    # 对齐到「同网焊盘边到边」这一条 TI 口径；板框越界从 AABB 改成真多边形包含）、
    # `focthermal.py`（旋转焊盘的投影从 AABB 改成真旋转矩形过滤）。行为锚点是
    # `tests/test_164c_silent_truth.py`（17 条，修前逐条红）与既有的
    # test_126b/126c/133d/152/153/153b，所以 bump 是被验证过的，不是记账。
    # **164a/164b moved it once more** — f838d122 -> f6c8ac35 — direct 仍
    # `4f056aaf`：158 实施（岳裁「电气语义以原理图为准」）——164a 落在
    # `foc.py`/`focground.py`/`fbplacement.py`（bulk 池/去耦/FB 腿池改原理图优先、
    # 0R 错句、EARTH 域筛；判决零翻转只换真值），164b 落在
    # `regulator.py`/`mcusupply.py`/`mcureset.py`/`crystal.py`/`crystalkeepout.py`
    # （HF/储能池分类、CL 计算、复位启动值全改原理图优先，证据句写明两视图各是什么）。
    # 行为锚点是 `tests/test_164a_foc_view_truth.py`（24 条）与
    # `tests/test_164b_supply_view_truth.py`（15 条），bump 同样是被验证过的。
    # **171 moved the recursive digest once more** — f6c8ac35 -> 64c84fc5 —
    # direct 仍 `4f056aaf`：本批落在 `rules/pcb/foc.py` 一个文件（`_farads_of`
    # 的两段读撤掉，改委托 `core.values.parse_capacitance_farads`——尾注读进了
    # reader，071 §2 一处判定一处实现；`_token_note` 的判据重述为「字段带尾注且
    # 首个词可读」，文案逐字未动）。行为锚点是新建
    # `tests/test_171_capacitance_tail.py` 与翻转后仍绿的
    # `tests/test_164a_foc_view_truth.py`。171 的另一半（`EARTH` 入
    # `core.model.GROUND_NET_PREFIXES`）落在 `core/`，按本 recipe 的定义
    # **不进摘要**（与 131c/131d 记过的同一条限制），锚点是
    # `tests/test_171_earth_net.py`。
    # **注意：本值是在一棵还有另一批未提交改动的树上量的** —— 同一工作树的
    # `rules/pcb/silk.py` 当时正被另一批改（171 不碰它），它也在本 recipe 里，
    # 所以 `64c84fc5` 是**这棵树**的值而不是 171 单独的值；后落地的那批按同一
    # 规矩再量一次即可（命令：`.venv/Scripts/python.exe -c "from pathlib import
    # Path;from boardwise.engines.review_eval import rulebody_fingerprint as f;
    # print(f(Path('src/boardwise/rules')))"`）。
    # **172 moved the recursive digest again** — 64c84fc5 -> a771a738 — and the
    # **direct** one still holds at `4f056aaf`（第十九批连任）：岳 2026-10-11 裁
    # 「丝印字宽改走宿主渲染 bbox（参考 easyeda-agent）：实测不估算、测不到就
    # 诚实降级」，整批又落在 `rules/pcb/`，只动 **一个文件** `silk.py`。它多了
    # 第二种宽度来源：`SilkDesignator(measured=...)`（键 `(板名, 位号文字)`）在
    # 有实测盒时取代 `ADVANCE_BAND` 那条估算带，且**每个数字都带着自己的来源**
    # （`WIDTH_SOURCE_LABEL`：「实测（宿主 primitive bbox）」/「估算值（字宽比带，
    # 非读数）」），小结行再报一次实测/估算的盘账。离线 `--file` 的判决一个字没变
    # （没有宿主可问，仍在估算那一态，只是现在逐条说明）。接线落在 `cli.py` 与
    # 桥的动作表**之外**——桥里能测 bbox 的只有 `sch.geometry` 的 `bboxIds`，
    # 本批不许加新动作，所以真机端到端的「实测」演示缺席（test 工程的 PCB1 是
    # 空板），原因与全部真机探针记在 `outputs/172/evidence.md`。行为锚点是新建
    # `tests/test_172_silk_measured_width.py`（16 条），判决账仍是逐条未动的
    # `tests/test_152_polarity_silk.py`。
    # **175 moved it once more** — a771a738 -> 2db8ca69 — direct 仍 `4f056aaf`：
    # 只动 `focground.py` 的两处过时散文与 `_domain_evidence` 的证据行
    # （硬编码筛子词表改从 `core.model.GROUND_NET_PREFIXES` 动态取，171 的 EARTH
    # 入词表后不再漏列），无判定语义变化。
    # **176 moved BOTH** — 2db8ca69 -> a1d0a231，direct `4f056aaf` -> `0c244efa`：
    # 本批第一次把 `rules/` 直下加了新文件（`sensebias.py`，`path-sampling-bias`，
    # issue #76），并顺手改了三个直下文件——`__init__.py`（导出）、`i18n.py`
    # （中文名）、`unproven.py`（那句「两个 L1 启发」的散文，本条是第三个）。
    # 判定语义本身只多了一条规则，没有既有规则被改动：旧规则的行为锚
    # （test_040b 的冻结表、test_094 等）只有 ROBOT 那张表的 WARN 计数从 3 变 5，
    # 原因写在那张表的注释里。行为锚点是新建 `tests/test_176_sampling_bias.py`
    # （21 条）。
    # **177 moved both** — a1d0a231 -> bb1b77c7，direct 0c244efa -> aa012db3 ——
    # 零判决语义：本批消灭了 `rules/pcb/focthermal.py` 里与 core 逐字相同的私有
    # `_point_in_polygon` 副本（改为 import 公开的 `core.measure.point_in_polygon`，
    # 4412 条对拍 0 分歧，`outputs/177/`），给 `rules/pcb/silk.py` 那份**故意不同**
    # 的纯 even-odd 变体钉了 docstring，修了 `rules/pcb/distance.py` 一句失效引用；
    # direct 移动的全部原因是 `rules/connectivity.py` 的一段 docstring（裁决：
    # 50mΩ 与 path-sampling-bias 的 0.5Ω 是分工不是洞）。行为锚：test_135 /
    # test_133d / test_162a，变异 2 组 CAUGHT。钉值含 177 审计（agent-303 的 LOW
    # 发现）驱动的 silk 措辞修正：原钉「boundary does not count as inside」不准确
    # （纯 even-odd 对底/左边的边界点实测答 True），改为「无压边规则、边界答案随
    # 边方向摆动」的准确表述。
    # **eol 修正（wushi2333 2026-10-13，规则体零改动）** — bb1b77c7 -> f3a69124，
    # direct aa012db3 -> 8269e601：配方改为哈希前把 CRLF 折成 LF。177 的两个钉值
    # 量的是**那台机器的检出**而不是源码：git 里 30 个规则文件全是 LF，而
    # 钉值只在「archclosure/base/decap/facts + pcb/distance/fbplacement/footprint/
    # ipc 这 8 个是 CRLF、其余 LF」的混合工作区上成立（穷举 2^13 / 2^17 种
    # LF/CRLF 组合反推，唯一解）——任何新 clone（autocrlf=true 全 CRLF 得
    # 6929c7fc，false 全 LF 得 8269e601）都红在这一行。折行后数字只随提交的
    # 字节动。新钉值 = 折行配方在 177 树上的读数（与全 LF 检出一致）；行为锚：
    # `tests/test_017_eval_metrics.py` 的
    # `test_the_rule_body_digest_does_not_read_the_checkouts_line_endings`。
    # **R2-4 moved the recursive one** — f3a69124 -> c0a45f39，direct 仍
    # `8269e601`（wushi2333 2026-10-13，零判决语义）：`rules/pcb/distance.py` 的
    # `_point_in_outline` / `_point_segment_mil` 与 `rules/pcb/focthermal.py` 的
    # `_point_segment_distance` 三份私有几何副本删除，改 import
    # `core.measure.point_in_polygon` / `point_segment_distance`（后者由私有提升为
    # 公开、守卫统一为 `length_sq <= 1e-18`）。守卫选型有数据：14 夹具全量 PCB 审查
    # 652 万次真实调用中两守卫逐位不同 24 次，全换任一守卫 881 条 PCB finding 逐条
    # 不变（`outputs/R2/guard_flip_experiment.json`），精确零守卫在下溢边上除零。
    # 行为锚：`tests/test_r2_4_geometry_consolidation.py` + 既有 126b/133d/164c 冻结表。
    # **R2-1 moved the recursive one again** — c0a45f39 -> f45cfd99，direct 仍
    # `8269e601`（wushi2333 2026-10-13）：`rules/pcb/` 新增 `keepout.py`
    # （`pcb-keepout-violation`，162b 解析的 REGION 禁布区的第一个读者；类型词表
    # 与「哪种禁布约束哪类图元、按什么层」取自立创 EDA Pro 3.2.186 自身代码），
    # `rules/pcb/__init__.py` 包说明加一条。既有规则零改动、14 夹具零新增 finding；
    # 行为锚：`tests/test_r2_1_keepout.py`（合成板逐类 + 电机板注入两例）。
    # **fixA moved the recursive one** — f45cfd99 -> dad6b777，direct 仍
    # `8269e601`（主代理 2026-10-13，PR#79 审查修复）：`rules/pcb/keepout.py`
    # 三条 LOW 修（混合词补「不确定」/ PLANE-only 与空 prohibitType 加披露行 /
    # 缺 regionType 的 PROHIBIT 默认文档化）；同批的 plated 哨兵语义修在
    # parsers/+core/，不在本 recipe。行为锚：tests/test_r2_1b_keepout_disclosure.py
    # + test_r2_2b_plated_consumed.py。
    # **bug98 moved the recursive one** — dad6b777 -> 0f524f9d（含审计 325 修补：closed 护栏消费、焊缝计数、措辞修），direct 仍
    # `8269e601`（主代理 2026-10-13，现场「98 条出板框误报」修复波）：
    # `rules/pcb/distance.py` 拆出 `BoardOffEdge`（pcb-component-off-board），
    # `rules/pcb/__init__.py` 注册；`rules/pcb/footprint.py` 吃库件 id→封装名
    # 回退（档内 FOOTPRINT 文档 META.title，provenance 记 `footprint=library-id`）。
    # 行为锚：tests/test_bug98a_outline_stitch.py + test_151b_footprint_id_fallback.py。
    # **182 moved the recursive one** — 0f524f9d -> 68ecaf84，direct 仍
    # `8269e601`（第二十批连任）：本批落在 `rules/pcb/` 的**两个文件**——
    # 新规则 `highspeed.py`（`pcb-hs-diffpair-inventory`，差分对清单，一条 INFO
    # 一对、零对零行）与 `__init__.py` 的包说明。规则之外的五个文件
    # （新模块 `core/highspeed.py`、`core/geometry.py` 的 `NetMeta`/`net_meta`、
    # `parsers/epru.py` 的 NET + LAYER_PHYS 读取、`parsers/kicad.py` 的
    # net_settings/stackup 读取，以及注册那一笔所在的 `engines/pcbreview.py`）
    # 按本 recipe 的定义**不进摘要**——它只覆盖 `src/boardwise/rules/`——与
    # 131c/131d/131f 记过的同一条限制；注册那一笔由本文件上方的逐字序列表兜住。
    # 行为锚：新建 `tests/test_182_highspeed_scaffold.py`（夹具读数 + 启发式表 +
    # 端到端）。本规则在 14 个夹具里出账的是：毕设FOC 1.0.0 的 PCB1 两行
    # （声明 DP1/DP2）、ROBOT 与智能药箱各一行（声明 DP1）、超声波四行（声明
    # DP1–DP4）、llc 与级联多电平-主拓扑各两行、FPC 两行、高速电机控制器与
    # 毕设FOC 2026-09-17 各四行、毕设滤波采样一行、KiCad 合成夹具一行、
    # 其余六个夹具零行（逐板扫过，命令与输出在 `outputs/182_highspeed_scaffold/
    # evidence.md`）。
    # **bug98-B moved the recursive one** — 68ecaf84 -> 38cb7b23，direct 仍
    # `8269e601`（第二十一批连任）：本批落在 `rules/pcb/` 的**一个文件**——
    # `rules/pcb/distance.py` 的 `BoardOffEdge` 加护栏（`_frame_is_a_piece`）：
    # 多段板框只认了一环（`BoardOutline.stitched is False`）且另有段未入环时，
    # 不出逐器件 ERROR，改出 1 条 WARN 点名段数与处置。判据与实现都在
    # `parsers/epru.py`（描边中心线拼合）与 `core/geometry.py`（新字段
    # `stitched`/`note`）——两个文件都在本 recipe 之外，与 131c/131d/131f 记过的
    # 同一条限制一致；规则里只有这一处判定变化。原样保留的锚：本文件上方逐字
    # 序列表（规则清单未动）、`test_bug98a_outline_stitch.py` 20 条、14 夹具
    # 003 秒级对拍（bug98-B 实板对拍见 `outputs/183_bug98b/evidence.md`）。
    # **186 moved both**（首次同时移动）— recursive 38cb7b23 -> ada814c6，
    # direct 8269e601 -> b4d75a74：本批把「板上的器件 → 货架条目」的**身份链**
    # 收成一个共享入口 `core.parts.resolve_facts` / `resolve_component_facts`
    # （MPN → C 码 → **器件名**，每步仍是精确匹配），并让 10 处板→条目查找改走它
    # （`rules/facts.py`、`rules/paramspec.py`、`rules/decap.py`、`rules/pcb/`
    # 的 crystal/distance/foc 三个文件都在本 recipe 内，故 direct 也被移动；
    # `engines/checkup.py`、`core/architecture.py`、`core/power_domains.py`、
    # `cli.py` 四处按本 recipe 的定义不进摘要）。判决语义：**今天零翻转**——
    # 全库扫过 4 张常用夹具 + 现场实板，器件名恰好等于某条货架 MPN 的元件
    # **0 个**（`outputs/186_pdf_facts/evidence.md` §2），实板 未审清单 34 条
    # 前后逐条同因同序。判据与锚：新建 `tests/test_186_pdf_facts_path.py`
    # （身份链证据序/精确性、端到端清闸、报告分栏、hygiene 三态）。
    # **187A moved both** — recursive ada814c6 -> 2033fcbd，direct b4d75a74 ->
    # 946e8610：本批落在 `rules/pcb/distance.py` **一个文件**——`BoardOffEdge`
    # 的护栏从「多段只认一环（`stitched is False`）一刀切抑制」收窄到「拿到的那
    # 一环读出来是**描边**（`BoardOutline.fragment_kind == "stroke_piece"`）才
    # 抑制」，完整板框 + 内槽那种多余闭环记录改回照跑。判据与字段在
    # `core/geometry.py`（新字段 `fragment_kind`）与 `parsers/epru.py`（H1 的形状
    # 不变量、M1 的实算计数、M3 的 capsule 焊缝地板值），**两个文件都在本 recipe
    # 之外**，与
    # 131c/131d/131f 记过的同一条限制一致。
    # **注意：本值量在一棵还有另一批未提交改动的树上** —— 同一工作树的
    # `rules/decap.py`、`rules/facts.py`、`rules/pcb/{focground,mcureset,mcusupply,
    # regulator}.py` 当时正被另一批改（187A 不碰它们），所以 `2033fcbd` 是**这棵
    # 树**的值而不是 187A 单独的值。实测拆分（同一棵树的副本里按文件还原 HEAD）：
    # 只把 187A 之外的上述 6 个文件还原回 HEAD → recursive `472fd377`、direct 仍
    # `b4d75a74`（= 187A 单独的值）；只把 187A 的 `distance.py` 还原回 HEAD →
    # recursive `0283930c`、direct `946e8610`（= 另一批单独的值）。direct 被移动的
    # 全部原因是另一批动了两个 `rules/` 直下文件（`decap.py`、`facts.py`），187A
    # 一个直下文件都没动。后落地的那批按同一规矩再量一次即可（命令同上方 171 条）。
    # 行为锚：新建 `tests/test_187a_outline_holes.py`（21 条：H1 两条拼合路径的退化
    # 环、M1「入环段数 + fragments == 段数」、M2 内槽照跑/描边碎片抑制两形态、
    # M3 焊缝地板值），既有 `tests/test_183_bug98b_capsule_outline.py` 与
    # `tests/test_bug98a_outline_stitch.py` 逐条未改仍绿；现场实板对拍
    # （16 段全入环、off-board 0 条）见 `outputs/187a_outline_holes/evidence.md`。
    # **187B 的账（同一棵树上，与 187A 合并量）**：上一段里的六处
    # 「另一批」= 187B —— `rules/pcb/{mcusupply,mcureset,regulator,focground}.py`
    # 四处把 `find_facts(mpn, lcsc)`（两键）改走 `resolve_component_facts`
    # （三键身份链，多一步**器件名**），`rules/facts.py` 改
    # `default_library_path`（冻结态读侧先用户货架 `~/.boardwise/parts.json`），
    # `rules/decap.py` 改了一行注释（历史提及 + 批号豁免注释）。判决语义：四处
    # 会**多**认出「只有器件名」的料，这是修洞不是回归（186-H1：同一颗料被
    # checkup 闸门判过、又被规则当不认识）；库内夹具实测无翻转，锚
    # `tests/test_187b_gate_holes.py`（grep 级不变量 + 四规则同名可见 + 冻结态
    # 读写同一架 + hygiene 三态/编码/单遍 + 3 板折叠行），证据
    # `outputs/187b_gate_holes/evidence.md`。187B 未再动 `rules/`，故本段钉值
    # `2033fcbd` / `946e8610` 对合并树有效。
    # **189A1 moved the recursive one only** — 2033fcbd -> c7bed2de，direct 仍
    # `946e8610`（第二十二批连任）：本批撤掉 `PadGeometry.layer_id`（改名
    # `footprint_layer_id` + `__getattr__` 拦截），落在 `rules/pcb/` 的**一处、
    # 且只是散文**——`rules/pcb/foc.py` 的 `pcb-foc-decap-proximity` 证据行里
    # 那句「the footprint's layer_id is not where the copper physically is」，
    # 字段已不存在，照读会把人引到一个已删的名字上，故写成
    # 「the footprint's own layer id (``footprint_layer_id``, the ``layer_id``
    # 189A1 removed)」。**判决语义零变化**：该规则的层读法本来就是
    # `pad.effective_layers()`（127b 起），本批没动任何规则取值路径；全库
    # `rules/` 内 `.layer_id` 的接收者全是 track/pour/region/text/row/corner/info/
    # island/placement，没有一处是 pad（逐处裁决表见
    # `outputs/189a1/evidence.md`）。行为锚：新建 `tests/test_189a_layer_id.py`
    # （10 条：拦截抛错带两个替代名、dataclass/构造签名形态、copy/pickle、
    # 毕设FOC 28 个底面焊盘两个读数回归、src 级 grep 锁 + 负控），
    # 127b/162b/125 系列既有锚逐条未改仍绿。变异 1 组 CAUGHT（删 `__getattr__`
    # 拦截 → `test_the_retired_name_raises_and_names_both_replacements` 红 →
    # cp 备份还原，sha256 一致）。
    # **189B moved the recursive one only** — c7bed2de -> 5162fe2d，direct 仍
    # `946e8610`（第二十三批连任；量在一棵**还合着 189A1/189A2 未提交改动**的树上）：
    # 本批落在 `rules/pcb/` 的**两个文件**——`derating.py`（判型读立创元数据：
    # `declared_type_text` 读 `Type`/`LCSC Part Name`/`Supplier Footprint` 三格，
    # `check()` 那一处从 `props["Type"]` 换过来；`_is_resistor` 的 docstring 写明
    # 「位号前缀不参与判型」）与 `distance.py`（`pcb-decap-distance` 每一行加
    # 「按哪条轨量的 + 这条轨在这颗器件上是 VIN/VOUT 哪一侧」披露，读者是
    # `core.pinrole.pin_role`，与 `pcb-regulator-cap-distance` 同一个）。
    # **判决语义**：derating 侧 14 夹具全量对拍只有一处读数变化——FPC 板的 `R2`
    # （贴片NTC热敏电阻：`LCSC Part Name` 写着类型、`Type` 为空）从「未认出」进到
    # 「认出 1 颗电阻」，零新增 WARN、零新增 verdict（对拍见
    # `outputs/189b/fixture_diff_derating.txt`）；distance 侧只是措辞与证据行，
    # 严重度与阈值零变化（test_126b/131b 逐条未改仍绿）。行为锚：新建
    # `tests/test_189b_mid_pack.py`（19 条：intent 三态 / stale 两个形状都印且不炸 /
    # 渲染兜底两层 / 元数据优先判型 + 前缀不是门 / 轨归因披露 / skill 备份窗 3 份 +
    # 回收站）。变异 2 组 CAUGHT（④ 接缝改回读 `facts["stale"]`、⑦ 判型改回只读
    # `Type`）。
    # **190 moved BOTH** — recursive 5162fe2d -> cd5e433e，direct 946e8610 ->
    # `a31a7c03`（第二十四批；量在一棵**只合着 190 自己的未提交改动**的树上——
    # 190S 的 `rules/pcb/silk.py` / `core/geometry.py` 当时与 HEAD 逐字节相同，
    # 两者 sha256 分别是 `b92fd20a…` / `44792b47…`；190S 落地后 recursive 会再
    # 动一次，由后落地的那批按同一规矩再量）。direct 被移动的原因是 190 改了
    # **三个 `rules/` 直下文件**：`connectivity.py`（`DecouplingPerIC` /
    # `ShuntSenseLink` 两处判型改走公共入口，`decoupling-per-ic` 的 message 不再
    # 自称「matches designator prefixes only」）、`facts.py`（`ics()` 逐件回路
    # 改走 `classify_part(library=…, pin_floor=False)` + 保留 039 的 NOT_APPLICABLE
    # 披露）、`sensebias.py`（运放半门的位号那半改走判型，货架 category 也交给
    # 它读）。recursive 另多 `rules/pcb/` 两个文件：`distance.py`（`classify_device`
    # 变成 `core.partkind.classify_part` 的薄封装，判据与词表搬去 `core/partkind.py`；
    # `pcb-decap-distance` 的超限行在 **VOUT 侧降一级为 INFO**）与
    # `derating.py`（判型走公共入口 + NTC/PTC 按 thermistor 放行）。
    # **判决语义**：14 块夹具 + 实板A 的全量对拍（finding 逐条 message/evidence
    # 比对：`outputs/190/fixture_compare.txt`）逐块可见——`decoupling-per-ic`
    # 实板A 3 条 WARN → 0；`board24v.enet`/KiCad 两块夹具的读数变化与原因见
    # `outputs/190/evidence.md` 的对照表。行为锚：新建 `tests/test_190_part_kind.py`
    # （24 条：读序/basis/039 门/3 脚地板/⑦ 两向/U 位号电阻不再要电容/
    # C 位号连接器不算电容/分流与 IC 两半/facts 主体面/NOT_APPLICABLE 披露保留/
    # thermistor 独立 kind 与值码/热敏不进 unknown_parts/VOUT 降级与阈值不动/
    # 6R3 电压码与 EIA 字母码清单/shelfMatchedBy）。变异 2 组 CAUGHT（见
    # `outputs/190/evidence.md` §变异）。
    # **190S + 191B + 191D merged (主代理统一重钉)** — recursive cd5e433e ->
    # 9b1fcf61，direct a31a7c03 -> 6ad63b13（第二十五批；量在合着四批未提交改动
    # 的同一棵树上）。三批落点：190S 只动 `rules/pcb/silk.py` 一句证据文案（底层
    # 文字框的几何改在 `core/geometry.py::SilkText`，不在指纹里）；191D 动
    # `rules/pcb/distance.py`（去耦四档阈值 200/300/500/200 mil、撤 190 的 VOUT
    # 降 INFO，超限恒 WARN）与 `rules/pcb/foc.py`（只改注释）；191B 动
    # `rules/facts.py`（读侧 `read_default_library()`：用户架 + 内置架合并读）与
    # `rules/pcb/` 十一个文件的读架口（`load_parts(default_library_path())` ->
    # `read_default_library()`，判决语义只多「内置新条目可见」）。191A/191C 未动
    # `rules/`。逐批对拍与变异见 `outputs/{190s,191b,191d}/evidence.md`。
    # 合并时另把 `rules/facts.py` 一处 docstring 里的企业归档文件名换成「实板A」（186 带入的保密洞，纯散文）。
    # **192B moved BOTH (主代理统一重钉)** — recursive 9b1fcf61 -> fc23ac00，direct
    # 6ad63b13 -> 3de90bc4（第二十六批；v0.5.14 发版前挖洞修复）。落点：`rules/connectivity.py`
    # （DecouplingPerIC 判型带货架）、`rules/sensebias.py` 与 `rules/pcb/distance.py`（039 门
    # 过 `facts_verified`；`_tier_pin` 剥脚名尾号）。判型词表改词边界在 `core/partkind.py`，
    # 不在指纹里；192A 的底层焊盘翻转在 `core/geometry.py`，也不在。夹具判型翻转 2 条
    # （毕设滤波采样/U1、超声波/U1 回到 IC），IC->非IC 0 条，见 `outputs/192b/evidence.md`。
    # **516A moved the recursive one only** — fc23ac00 -> 10a9d541，direct 仍
    # `3de90bc4`（第二十七批；岳真机反馈 516 的 A1/A2）。落点是 `rules/pcb/ipc.py`
    # 一个文件：A1 把「标称同电位」豁免收窄成「双地或几何重合」、其余按摆幅上限
    # `max(|a|,|b|)` 判（`_same_potential` / `_one_pair`）；A2 把 `pcb-track-ampacity`
    # 的主体从「网名」展开成「铜的连通分量」（`_conductor_component` / `_one_component`）。
    # 判决语义的钉在 `tests/test_516_same_potential_spacing.py` 与
    # `tests/test_516_ampacity_component.py`；本批的 checkup/CLI 改动（A3/B1/B2/C）
    # 都在 `engines/checkup.py` 与 `cli.py`，不在本配方里。
    # **522 moved BOTH (主代理重钉)** — direct 3de90bc4 -> 5eceec18，recursive
    # 10a9d541 -> 9235d428 -> eb48cb9b（第二十八批 522 及其挖洞修复）；`facts_verified` 布尔拆成 `facts_trust`
    # 三档）。落点全在 `rules/`：`_category_state` 加 `allow_machine` 关键字参数、
    # `FactsRule.REQUIRES_HUMAN_VERIFIED` 与十一条算数字的规则设 False（域/压差/
    # 去耦/LED/分压/RC/TVS/LDO/distance/rail-clash）、`present_rows` 统一贴
    # `machine_trust_note` 的「未人工确认」标注、`SenseBias`/`RailRatings` 的档位
    # 判断。**判决语义**的钉在 `tests/test_522_facts_trust.py`（档位闸、标注、
    # verdict 不涂绿）；`core/parts.py`、`core/power_domains.py`、
    # `core/partkind.py`、`engines/checkup.py` 的改动不在本配方里。
    assert recursive != old_digest, "the subpackage is inside the recipe now"
    # 527D 的挖洞修复（第二十九批之二）：H5 给 `_category_state` 加了 candidate
    # 分类的无条件闸、L1 把 `_category_absent_reason` 的分支顺序对齐，两处都在
    # `rules/facts.py` 一个直接文件里 ⇒ 当时的两个钉值是 4733469e/78b346aa。
    # 527D3 落在同一棵树上，把这两个值又各自推了一格（见下）。
    # **527D3 moved BOTH** — direct 4733469e -> b05d3384，recursive 78b346aa ->
    # 674e07e1（第三十批 527D3，H3 的收口：`entry.category` 的十四个直读点改走
    # `core.partkind.declared_category` + `category_verdict`）。本批落在
    # `rules/` **十五个文件**：六个**直接**文件 —— `facts.py`（`_category_state`
    # 改为走共享入口，并新增 `category_gate_finding`：机器档/草稿分类的那一行免责
    # 文案与形状写一次）、`decap.py`、`params.py`、`paramspec.py`、
    # `archclosure.py`、`railratings.py`；九个 `pcb/` 下的 —— `crystal.py`、
    # `crystalkeepout.py`、`fbplacement.py`、`foc.py`、`focground.py`、
    # `focthermal.py`、`mcureset.py`、`mcusupply.py`、`regulator.py`。
    # 三个读点在 `core/`（`partkind.py` 的新入口、`architecture.py` 的四个读点与
    # `gated_classifications` 披露行、`power_domains.py` 的推断），按本配方
    # 的定义**不进摘要** —— 与 131c/131d/131f 记过的同一条限制一致。
    # **判决语义**：人签档的产物逐字节不变（无夹具条目带机器档分类，见
    # `tests/test_527d3_declared_category.py` 的端到端两条）；机器档/草稿档从
    # 「静默跳过」变成「出免责行或 UNKNOWN」。两个值都在**只含 527D3 的 `rules/`
    # 树上**直接量得（命令同上方 171 条）；同一工作树另有 `cli.py`、
    # `engines/router.py`、`connector/`、`bridge/protocol.py` 等未提交改动，均不在
    # 本配方内。**本段的两个数就是 527D3 落地时那两条断言里的值，一字不差**（红队
    # S7：本段粗体曾写成 e3540c5a/297f629d，与同一段的断言不同，账本里同一件事出现
    # 三组数、后来者无从判断哪组权威；错的是散文，不是断言）。后来的批次若又动了
    # `rules/`，按本文件惯例在末尾另起一段记新值，**不动本段**。
    # eb48cb9b -> 5c878604（517：191D 的稳压器输出档 500 -> 800 与「输入档一个
    # 电容都没有 -> WARN」，外加 A1 的同层测量 `net_clearance(same_layer_only)`）。
    # 三处都在 `rules/pcb/` 与 `core/measure.py` 里，所以两个摘要一起动。
    # **527D moved BOTH** — direct 46e1f698 -> 4eb1135e，recursive 5c878604 ->
    # d8cc0aa7（第二十九批 527D，TASKMAP 523）：`parts classify` 要有一条一等入口
    # 把 `category` 写进货架，而规则侧必须回答「这条分类是谁签的」，于是
    # `rules/facts.py` 的 `_category_state` / `_category_absent_reason` 各加一道
    # `category_trust` 闸（机器核验的分类对**结论类**规则仍是 UNKNOWN，只喂
    # `allow_machine=True` 的算数字规则；原因文案换一句，说清「分类是机器核验的、
    # 本规则要人签字」）。落点只有 `rules/facts.py` 一个**直接**文件（多一个
    # `FACTS_TRUST_VERIFIED` 导入），所以两个摘要一起动；`rules/pcb/` 一个字没改。
    # 两个值均在**只替换该文件为 HEAD 版**的树上复量过：46e1f698 / 5c878604 正是
    # 换掉本批改动后的读数，即两个摘要的位移全部来自 527D，与工作区里别的未提交
    # 改动无关（`core/designintent.py`、`tasks/088b-…` 不在本配方里）。
    # **判决语义**的钉在 `tests/test_527_parts_classify.py`（词表闸、两个档位、
    # 引文闸、机器档只喂计算、旧条目逐字不变）。
    # **527D3 fix moved BOTH** — direct b05d3384 -> acb185c4，recursive
    # 674e07e1 -> 94153a7f（第三十批 527D3 的挖洞修复：红队 S1/S2/S5 的共同根因
    # 「草稿档的类在数字类读点被折成 ABSENT，连一句免责都不出」）。落点又是
    # `rules/` 的**七个文件**：直接文件 `decap.py`（`cap_candidates_on` /
    # `same_net_capacitors_on` 保留「货架说它是电容、档位不采信」的件，
    # 标 unreadable 而不是剔除 —— DECAP-1 走 UNKNOWN，不再出假 WARN）、
    # `params.py`（`_kind_of` 改三态 + 免责行）、`paramspec.py`
    # （`independent_rail_price` 的第三槽、`TvsStandoffRail` 的双门都不接纳时出
    # UNKNOWN）、`archclosure.py`（gated 成员记下继续走，结论不再依赖网表顺序）、
    # `railratings.py`（免责句的 `allow_machine` 跟判闸同一个值），
    # 以及 `pcb/` 下的 `distance.py`（`_supply_nets` 收 UNKNOWN 态的 guess ——
    # 轨不再悄悄退出 `pcb-decap-distance` 的射程）与 `foc.py`
    # （`power_mosfets_of` 的 gated 只收 `found` 没接纳的件，同一份报告不再既量了
    # 环路又说环路没量）。两个值都在本工作树上直接量得（命令同上方 171 条）；
    # 同一工作树另有 `cli.py`、`engines/router.py`、`connector/`、
    # `bridge/protocol.py` 等未提交改动，均不在本配方内。
    # **判决语义**：人签档/机器档的产物逐字节不变（无夹具条目带这两档），
    # 草稿档从「假 WARN / 一行没有」变成「UNKNOWN 或带免责的行」。
    # **8586 moved BOTH** — direct acb185c4 -> b6b6f2dd，recursive 94153a7f ->
    # 3342b109（issue #85 / #86，岳 2026-10-22 提；量在一棵**还合着 #83 等未提交
    # 改动**的树上，其中 `core/measure.py` 与本配方无关，`rules/` 下只有本批）。
    # 落点**四个文件**：**直接**文件两个 —— `rules/decap.py`（#86：
    # `CapCandidate` 加 `value_source`，新增 `recovered_capacitance` /
    # `recovered_farads` / `value_source_label`，`cap_candidates_on` 在原理图
    # `Value` 为**空**时按「货架（MPN / C 号）→ MPN 的 EIA 码」补出容值并标注来源）
    # `rules/pcb/ipc.py`（#85：`pcb-voltage-spacing` 的 `_one_pair` 在最近对
    # **双侧都是同一颗器件的焊盘**时判成封装脚距、降 INFO 并同时给出排除该器件后的
    # 最近外部对（`_gap` 走 `net_clearance(ignore_within_component=…)`）；新增
    # `_clearance_measurement` 把 element_a/b 与 component_a/b 结构化进
    # `target.measurement`）；`pcb/` 下两个 —— `pcb/distance.py`（`capacitor_role`
    # 在模型字段读不出时接受恢复值并在 reason 里点名来源；`pcb-decap-distance` 的
    # 超限行的 evidence 补上「判 IC 的根据 + 每个候选的档位与决定它的值」，与两条空池
    # INFO 行对齐）、`pcb/regulator.py`（`regulator_role` / `_pool_reason` 走同一个
    # 共享读数 `_pool_reading`）。
    # **判决语义**：#85 只在最近对双侧同属一颗器件的焊盘时改严重度（实板A 10 条 WARN
    # 里 4 条同颗 → INFO，2 条「走线对同颗焊盘」不动；重叠即短路的仍 WARN）；
    # #86 只在原理图字段**空白**时补值（写了 `DNP` 这种读不出的字面不动）。
    # 库内夹具实测翻转：毕设FOC PCB1 的 `pcb-decap-distance` **4 条 INFO → 3 条**，
    # 且出现本板第一条 WARN —— `U11/+5V` 变 WARN（最近 HF 候选 `C30` **561.3 mil**，
    # 超该轨 300 mil 的稳压器输入档），`U13/+5V` 的假 INFO「网上没有高频去耦电容」
    # 消失（`C30` 实测 **113.97 mil**，在档内）。根因是 `C30` 的 `Value` 为空、MPN
    # `CC0805KRX7R9BB104` 的 `104` = 100 nF —— 正是 #86 的形态；两条既有断言因此按
    # 证据改写（`test_126b_*` 的「four infos and no warn」、`test_127b_*` 的
    # 「no candidate pool is a high-frequency one」，旧断言的前提就是 #86 修掉的
    # 那条）。**判决语义的锚**：新建 `tests/test_85_footprint_pitch.py` 与
    # `tests/test_86_legacy_value.py`（后者含 `value_source` 的四形态不变量）。
    # 变异验证（cp 备份 + sha256 还原，禁 `git checkout --`）见
    # `evidence/8586/mutation_log.txt`。
    # **84 moved the recursive one only** — recursive 3342b109 -> **22eb8d3e**，
    # direct 仍 `b6b6f2dd`（issue #84，岳 2026-10-22 提；量在**还合着 #83/#85/#86 等
    # 未提交改动**的树上，`core/measure.py` 不在本配方内）。落点只有
    # `rules/pcb/ipc.py` 一个文件：`pcb-track-ampacity`
    # 的 `_one_component` 把每层读数从 `track_width_stats` 换成
    # `core/measure.conductor_copper`（**分段**分辨率），判定前先问
    # `_load_bearing` —— 同一导体上另有一段「≥ max(3 × 该层最窄段, 该层所需宽度)」
    # 的干线或铺铜时，该层过窄的段按**宽度档**逐档出 UNKNOWN 行
    # （`_branch_rows`：段数 / 总长 / 坐标跨度 / 每段自身端点），不再按最小线宽判
    # ERROR；`BRANCH_WIDTH_RATIO = 3.0` 是屋规（写进常量 docstring，不进 `source`，
    # `source` 仍只引 IPC-2221）。`core/measure.py` 的 `LayerCopper` /
    # `ConductorCopper` / `conductor_copper` 是新增读数，按本配方定义**不进摘要**
    # （与 131c/131d/131f/527D3 记过的同一条限制一致）。
    # 本批内摘要还推过两次、均由同一批自己的真实源码变化引起（判层优先的两趟搜索
    # 与 Severity 段的散文收口），中间值为 a9839df1 / c5b42df1；**只记最终值**，
    # 中间值不单独断言（同一批内不该出现三组权威数）。
    # **判决语义**：库内夹具只有 ROBOT 一条有合同，实测 **6 条 ERROR 一条不动** ——
    # `U+` 最宽 15.0 mil、`W+` 14.0 mil、两网都没有铺铜，而门槛是 53.8（外层）/
    # 140.0（内层），所以门槛不开（`tests/test_126c_pcb_ipc_rules.py` 与
    # `tests/test_090/092/127b` 的六条断言原样绿）。真正翻转的是 516 A2 那两条**合成**
    # 断言：60 mil 干线 + 10 mil 细线的形状正是 #84 判成「支路」的形态，两条按证据
    # 改写（把宽铜降到门槛以下的 40 mil，保住它们要钉的**连通分量闭包**与 ERROR 通路；
    # 60/10 的形状改由新建 `tests/test_84_ampacity_branch.py` 按 #84 的口径钉）。
    # 变异验证（cp 备份 + sha256 还原）见 `evidence/84/mutation_log.txt`。
    # **537F moved BOTH** — direct b6b6f2dd -> cda23a06，recursive 22eb8d3e ->
    # 83d0e91c。537F 在三个**直接**文件（`rules/facts.py`、`rules/archclosure.py`、
    # `rules/sensebias.py`）里引入共享的 `ResistanceReading`：`Value` 为空、MPN 唯一
    # 可解析时恢复阻值，并把同一份读数共享给**存在性**判读与 **Thévenin** 计算；
    # **0Ω 仍算「存在」**（存在性不因阻值为零而丢），非正值由算术层排除。
    # **公式与阈值未改**，判决语义的锚是 `tests/test_094_sense_bias.py`（最终
    # 41 passed）；两个值都是在**当前这棵工作树**上按本文件上方 171 条同一配方直接
    # 量得（direct 走 `*.py` 直读、recursive 走 `rulebody_fingerprint`）。
    # **540B1–B3 moved BOTH** — direct cda23a06 -> 7e3ac51a，recursive 83d0e91c ->
    # 43979be9。相对 539 提交，`rules/` 只有三个文件变化：`pcb/focground.py` 的
    # 地网域词表下移 `core/netdomains.py`（B1）；`facts.py` 的自动网名与引脚连通
    # 原语分别下移 `core/netdomains.py` / `core/connectivity.py`（B1/B2）；
    # `decap.py` 的候选库存、门控电容识别、值恢复与 CapDecision 下移
    # `core/decap.py`（B3）。旧导入面仍 re-export 同一对象；Finding、严重度、
    # 模式和同网检查包装留在 review。摘要是源码位置指纹，不是行为指纹：这里的
    # 位移来自源码下沉，三个 `core/` 新文件按本配方定义不进摘要；行为锚是
    # `tests/test_540_shared_{naming,connectivity,decap}.py` 及各自邻域回归。
    # 两个值均在当前树上直接量得，没有改判规则、公式或阈值。
    # **540B2 adversarial hardening moved BOTH** — direct 7e3ac51a -> **ea1d06e0**，
    # recursive 43979be9 -> **25b7de70**。原因是**权威化**而非判决变化：修复让
    # `component_net(comp, pin)` 成为调用方所持 component 的**唯一**连通读数，
    # `facts._pin_net` 直接别名它（`facts._pin_net is connectivity.component_net`，
    # 见 `test_facts_pin_net_is_the_shared_reading_not_a_second_copy`），于是
    # **detached**（模型里没有这颗）、**key-mismatch**（字典键不是位号）、
    # **stale-copy**（模型里是同位的旧副本）三种输入不再被 model lookup 覆盖，
    # 一律按调用方手里那个对象的引脚作答。落点仍是源码位置：直读面只有
    # `rules/facts.py`（别名收口），其余在 `core/connectivity.py` 等
    # `core/` 下沉文件里 —— 后者按本配方定义（只读 `rules/` 的 `*.py` 直读 /
    # `rules/` 下递归）本来就不进 direct 摘要，recursive 只随 `rules/` 内变化移动。
    # **这里没有改公式、阈值或 verdict**：摘要移动是源码位置指纹的预期结果。
    # 行为锚是 `tests/test_540_shared_connectivity.py` 的五条：上面那条身份断言
    # 加 `test_a_detached_component_answers_about_its_own_pins` /
    # `test_a_component_under_a_different_key_still_answers_about_itself` /
    # `test_a_stale_copy_is_judged_on_its_own_pins_not_the_models` /
    # `test_an_attached_component_keeps_the_frozen_answer_and_one_net`（attached
    # 时三路读数同网且判决保持冻结）；变异与 SHA-256 恢复证据见
    # `evidence/540/b-behavior-equivalence.md` 与
    # `evidence/540/final-mutation-restoration-check.log`。两个值同样在**当前这棵
    # 工作树**上按上方同一配方直接量得，recursive 与
    # `contracts/differential/manifest.json` 的 `producerVersions.rulebody` 一致。
    assert old_digest == "ea1d06e0"
    assert recursive == "25b7de70", (
        "the measured value of the widened recipe over this tree; if a rule body "
        "changed since, update this together with the note in test_017"
    )