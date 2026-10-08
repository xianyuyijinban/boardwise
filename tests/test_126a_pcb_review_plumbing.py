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
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(PcbReviewContext)}
    assert fields == {
        "board", "board_title", "model", "intent", "module_of", "pcb_model",
    }
    ctx = PcbReviewContext(board=BoardGeometry(), board_title="PCB1")
    assert (
        ctx.model is None and ctx.intent is None
        and ctx.module_of == {} and ctx.pcb_model is None
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

    ``BUILTIN_RULES`` (the schematic 20) is left untouched by this file — read
    rather than re-stated where the point is "this file did not move it", so
    the assertion is that the two lists are separate objects and that the PCB
    one grew on its own.
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
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]
    assert all(isinstance(rule, PcbRule) for rule in BUILTIN_PCB_RULES)
    # The schematic side is untouched by this file: its list is the 011-family
    # set, and it is a *separate object* (mutating one must not touch the other).
    assert len(BUILTIN_RULES) == 20
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
            "pcb-component-spacing",
            "pcb-track-ampacity", "pcb-voltage-spacing",
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
        "pcb-component-spacing", "pcb-voltage-spacing",
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

    # The old recipe (direct *.py only) over today's tree.
    old = hashlib.sha256()
    for path in sorted(rules_dir.glob("*.py")):
        old.update(path.name.encode("utf-8"))
        old.update(b"\x00")
        old.update(path.read_bytes())
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
    assert recursive != old_digest, "the subpackage is inside the recipe now"
    assert old_digest == "98b1d462"
    assert recursive == "98706289", (
        "the measured value of the widened recipe over this tree; if a rule body "
        "changed since, update this together with the note in test_017"
    )