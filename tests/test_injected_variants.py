"""The injected-defect board family (task 011d sec.4 + its follow-ups).

Two layers, and the tests keep them apart:

* **fixed-base** -- the golden page with the oracle's two 2026-09-19
  corrections (U3's MPN, V3 tied to VCC). It carries no defect of its own and
  no findings at all;
* **the variants** -- each derived from that base by one edit, with an
  annotation set whose single defect record names the rule that has to catch it.

The base is what makes a variant meaningful: an injected fault only proves
something if the board it was injected into did not already have it. So every
variant is checked twice -- it fires on its own board, and it does *not* fire
on the base.

Three properties arrived with 011e and are pinned here:

* ``v3-decap-missing`` is **retired** (sec.1.2). Its file stays on disk so the
  content guard keeps covering it, but it is in no split, carries no
  records, and the gate refuses to author it. The measurement behind the
  retirement -- removing C1 is invisible to ``decap-required-caps`` on this
  topology -- is still asserted, because a retirement nobody can re-check is
  folklore;
* the dev/holdout split (sec.2) is **derived** from ``sha1(id)``, never picked,
  and the concrete result is frozen here so re-rolling it is a visible change;
* ``value-mpn-mismatch`` used to carry a second effect -- the wider series
  resistance also dragged the computed LED current out of bounds. The oracle's
  2026-09-19 revision of ``param-led-current`` (judge the resistance against
  [470, 2200] ohm in the 3V3 domain) removed it *at 2.2k*, the value the
  injection carried then, and the test below pinned the single-fault shape.
  **Batch 2 (2026-09-21) took it back**: 2.2k against the 1k MPN is 2.20x,
  below that ruling's 3x R tolerance, so the injected value moved to 4.7k and
  the second effect returned -- 4.7k is outside the LED window. The board is
  no longer a single-fault fixture, and the test below now pins *that*, with
  the consequence in the dev measurement written down rather than hoped for.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.annotations import load_annotations
from boardwise.engines.review import BUILTIN_RULES
from boardwise.engines.review_eval import evaluate_annotations, load_board_model
from boardwise.rules.decap import DecapRequiredCaps
from boardwise.rules.params import LedCurrent, ValueMpnMatch

ROOT = Path(__file__).resolve().parents[1]
INJECTED = ROOT / "reviewsets" / "injected"
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
BASE = INJECTED / "fixed-base.epro2"
GOLDEN_SET = ROOT / "reviewsets" / "ch340g_golden.json"
EXPECTED_MPN = "FRC0805J102 TS"


def _generator():
    """Load the generator by path: it is a script, not part of the package."""
    spec = importlib.util.spec_from_file_location(
        "make_variants", INJECTED / "make_variants.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _board_ids() -> list[str]:
    """Every variant file on disk, retired ones included."""
    return sorted(
        path.stem for path in INJECTED.glob("*.epro2") if path.stem != "fixed-base"
    )


def _eval_ids() -> list[str]:
    """The variants that take part in grading: the generator's own ledger."""
    return sorted(_generator().eval_ids())


def _holdout_ids() -> list[str]:
    return sorted(_generator().holdout_ids())


def _dev_ids() -> list[str]:
    return sorted(_generator().dev_ids())


#: The split as of 2026-09-20, from ``sha1(id)`` ordering over
#: ``value-mpn-mismatch, overvoltage-rail, ...`` (see make_variants.py). Frozen
#: so that re-rolling the split -- the thing sec.2 exists to prevent -- shows up
#: as a failing test rather than as a quiet new number in a report.
FROZEN_HOLDOUT = ["duplicate-designator", "nc-pin-grounded"]
FROZEN_DEV = ["ldo-no-headroom", "overvoltage-rail", "value-mpn-mismatch"]

#: Retired 2026-09-20 (sec.1.2): on disk, in no split, with no records.
RETIRED = "v3-decap-missing"


def _pin(model, designator: str, number: str):
    return next(p for p in model.components[designator].pins if p.number == number)


def _fault_is_present(variant: str, model) -> bool:
    """Is the variant's injected fault visible in the parsed board?"""
    if variant == "v3-decap-missing":
        return "C1" not in model.components
    if variant == "duplicate-designator":
        return model.duplicate_designators == ["R24"]
    if variant == "nc-pin-grounded":
        return _pin(model, "U5", "4").net == "GND"
    if variant == "overvoltage-rail":
        return "+9V" in model.nets
    if variant == "ldo-no-headroom":
        return _pin(model, "U5", "1").net == "VCC"
    if variant == "value-mpn-mismatch":
        return model.components["U3"].value == "4.7k\u03a9"
    raise AssertionError(f"no fault check for {variant!r}")


def _findings(board: Path) -> list:
    model = load_board_model(board)
    return [finding for rule in BUILTIN_RULES for finding in rule.check(model)]


def _evaluation(annotation: Path, board: Path, *, split: str = "all"):
    """Per-board grading, with the split filter opened.

    ``split="all"`` on purpose: these tests ask "does the rule catch this
    board's fault", which is a question about one board. The harness default
    is ``dev``, so a holdout board would otherwise contribute nothing here --
    correct behaviour, wrong question. The default is pinned separately, in
    ``test_review_eval``.
    """
    aset = load_annotations(annotation)
    return aset, evaluate_annotations(
        aset, load_board_model(board), BUILTIN_RULES, split=split
    )


def _metric(evaluation, rule_id):
    return next(m for m in evaluation.metrics if m.rule_id == rule_id)


# ---------------------------------------------------------------------------
# the table, the gate, determinism
# ---------------------------------------------------------------------------


def test_every_table_entry_is_built_and_nothing_else_is():
    module = _generator()
    assert [b["id"] for b in module.BASES] == ["fixed-base"]
    variants = [v["id"] for v in module.VARIANTS]
    # Every entry is either live-and-signed or retired; a third state
    # ("neither") would be a proposal the gate cannot describe.
    for entry in module.VARIANTS:
        assert entry["signed"] or entry.get("retired"), entry["id"]
        assert not (entry["signed"] and entry.get("retired")), entry["id"]
    for board_id in ["fixed-base"] + variants:
        assert (INJECTED / f"{board_id}.epro2").is_file()
        assert (INJECTED / f"{board_id}.json").is_file()
    assert sorted(variants) == _board_ids(), "a stray board is not in the table"


def test_the_split_is_derived_from_sha1_and_matches_the_frozen_ledger():
    """sec.2: the held-back slice is computed, not chosen.

    The rule is ``sha1(id)`` ordering, first ``HOLDOUT_SIZE``; the concrete
    outcome is frozen in this file. Both halves matter: the derivation stops
    anyone re-picking after a number comes in, and the frozen copy stops the
    derivation itself from changing silently.
    """
    module = _generator()
    derived = sorted(
        module.eval_ids(),
        key=lambda v: hashlib.sha1(v.encode()).hexdigest(),
    )
    assert sorted(module.holdout_ids()) == sorted(derived[: module.HOLDOUT_SIZE])
    assert _holdout_ids() == FROZEN_HOLDOUT
    assert _dev_ids() == FROZEN_DEV
    assert sorted(_holdout_ids() + _dev_ids()) == _eval_ids()
    # At least a third of the graded boards, as sec.2 requires.
    assert len(_holdout_ids()) * 3 >= len(_eval_ids())


def test_the_retired_board_is_watched_but_not_graded(capsys):
    """sec.1.2, and the distinction is the whole point of the arrangement."""
    module = _generator()
    # Watched: the guard still rebuilds it and compares the content, member for
    # member (issue #1 -- not the archive bytes, which belong to the zlib).
    assert RETIRED in module._tracked_ids()
    assert module.check() == 0
    # Not graded: in no split, and its annotation set claims nothing.
    assert RETIRED in _board_ids()
    assert RETIRED not in _eval_ids()
    assert RETIRED not in _holdout_ids()
    assert RETIRED not in _dev_ids()
    raw = json.loads((INJECTED / f"{RETIRED}.json").read_text(encoding="utf-8"))
    assert raw["items"] == [], "a retired board must make no ground-truth claim"
    assert "RETIRED" in raw["notes"] and raw["reviewed_by"] == ""
    # And the gate refuses to author it again.
    assert module.generate([RETIRED]) == 2
    assert "retired" in capsys.readouterr().err


def test_the_gate_refuses_an_unsigned_entry_without_writing_anything(capsys, monkeypatch):
    """The gate stays exercised even though every live entry is signed today.

    A future proposal arrives unsigned; when it does, ``--generate`` must
    refuse the whole request and leave the tree untouched. Simulated here by
    blanking one live entry's signature, so the mechanism cannot rot unnoticed.
    """
    module = _generator()
    live = next(v for v in module.VARIANTS if v["signed"])
    monkeypatch.setitem(live, "signed", "")
    before = sorted(path.name for path in INJECTED.iterdir())
    assert module.generate([live["id"]]) == 2
    assert "not signed" in capsys.readouterr().err
    assert sorted(path.name for path in INJECTED.iterdir()) == before


def test_rebuilding_a_retired_board_is_a_maintenance_verb_only(tmp_path, capsys):
    """The guard's door, and it is the guard's alone.

    ``--check`` has to rebuild the retired board or it would stop watching a
    file that is still committed. That door is opened by an argument nobody
    reaches for by accident, and the retired board still lands in no split.
    Both builds go to a scratch directory: a test must not write the fixtures
    it is checking.
    """
    module = _generator()
    assert module.generate([RETIRED], out_dir=tmp_path, rebuild_retired=True) == 0
    assert (tmp_path / f"{RETIRED}.epro2").is_file()
    assert RETIRED not in module.holdout_ids() + module.dev_ids()

    # The default build leaves it out entirely.
    capsys.readouterr()
    assert module.generate([], out_dir=tmp_path / "default") == 0
    assert RETIRED not in capsys.readouterr().out


def test_the_gate_refuses_a_name_that_is_not_in_the_table(capsys):
    module = _generator()
    assert module.generate(["no-such-variant"]) == 2
    assert "unknown board" in capsys.readouterr().err


def test_regeneration_reproduces_the_committed_content():
    """Ids are derived and the archive timestamp is fixed, so a rebuild is stable.

    Stability is what makes the guard readable; *content* is what it compares
    (issue #1: member content, never the deflate stream -- see
    ``test_the_guard_compares_content_not_the_compression_stream``).
    """
    assert _generator().check() == 0


def test_check_reports_drift_without_rewriting_the_fixture(capsys):
    """The guard must be read-only, and this is not a hypothetical.

    The first version built the boards into the fixture directory and compared
    afterwards. A drifted build therefore *became* the committed fixture, and
    every later check agreed with it -- a mutation that should have been caught
    was reported as surviving. The guard now builds into a scratch directory;
    this test drives a drifted fixture through it and requires both that the
    drift is reported -- by member name, as content -- and that the file on
    disk is left exactly as it was.
    """
    module = _generator()
    target = INJECTED / "v3-decap-missing.epro2"
    original = target.read_bytes()
    drifted = GOLDEN.read_bytes()
    assert original != drifted
    try:
        target.write_bytes(drifted)
        assert module.check() == 1
        err = capsys.readouterr().err
        assert "member content" in err and "v3-decap-missing.epro2" in err, err
        # The report names the member that moved, not just the file: an
        # unnamed "drift" would leave the reader to diff two zips by hand.
        assert "CH340G.epru" in err, err
        assert target.read_bytes() == drifted, "the guard rewrote what it checked"
    finally:
        target.write_bytes(original)
    assert module.check() == 0, "the fixture is back and the guard agrees"


def test_the_guard_compares_content_not_the_compression_stream(monkeypatch):
    """Issue #1. A ``.epro2`` is a zip; the deflate stream is the writer's zlib.

    Same content, different zlib: two machines build the identical board and
    the archive bytes differ, because the compressor -- not the fixture --
    decides how the members are wrapped. The guard's first version compared
    those bytes, so a fresh clone (Python 3.12, zlib 1.3.1) failed three tests
    with every fixture content-correct.

    The rebuild below is driven with a different compression level, which is
    the same failure mode with the same fix in view: the archives must really
    differ in bytes, and the guard must stay green.
    """
    module = _generator()
    committed = {
        path.name: path.read_bytes()
        for path in INJECTED.glob("*.epro2")
    }
    byte_differences: list[str] = []

    def compress_differently(members, epru_name, text, out: Path):
        members = dict(members)
        members[epru_name] = text.encode("utf-8")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload, compresslevel=1)
        # Recorded here, not after ``check``: the guard deletes its scratch
        # directory on the way out, which is part of what makes it read-only.
        if committed.get(out.name) != out.read_bytes():
            byte_differences.append(out.name)

    monkeypatch.setattr(module, "_write_archive", compress_differently)
    assert module.check() == 0, "compression is not content"
    assert byte_differences, (
        "the rebuild reproduced the committed bytes exactly, so this test "
        "proved nothing about compression -- pick a level that really differs"
    )


def test_drift_is_reported_member_by_member(tmp_path):
    """One changed member, one removed member: both named, nothing else claimed.

    The guard's unit of comparison is the member, so this drives the
    comparison directly rather than through ``check`` (which rebuilds the whole
    family): the committed board, a copy with one member's content altered, and
    a copy with a member gone.
    """
    module = _generator()
    source = INJECTED / "fixed-base.epro2"
    with zipfile.ZipFile(source) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    text_member = next(n for n in members if n.lower().endswith(".epru"))
    body = members[text_member].decode("utf-8")
    others = [n for n in members if n != text_member]
    assert others, "the board is expected to carry more than the .epru member"

    altered = tmp_path / "altered.epro2"
    module._write_archive(dict(members), text_member, body + " \n", altered)
    without = tmp_path / "without.epro2"
    module._write_archive(
        {n: payload for n, payload in members.items() if n != others[0]},
        text_member,
        body,
        without,
    )

    want = module._content_digests(source)
    assert module._drift_labels(want, module._content_digests(altered)) == [text_member]
    assert module._drift_labels(want, module._content_digests(without)) == [
        f"{others[0]} (member missing)"
    ]
    # The member set is part of the comparison, and the label spells both halves
    # the way the guard's report does.
    assert module._artifact_label("fixed-base", "epro2", text_member) == (
        f"fixed-base.epro2 :: {text_member}"
    )
    # A plain file has no members; its label is just the file.
    assert module._artifact_label("fixed-base", "json", "") == "fixed-base.json"


def test_line_endings_are_not_content(tmp_path):
    """Issue #1's second half: the ``.json`` blobs are LF, a checkout may not be.

    The committed annotation sets are LF. The generator writes LF too, but
    Python's text mode turns that into CRLF on Windows, and a clone with
    ``core.autocrlf=false`` holds LF -- so the same generator output reached the
    guard as two different byte strings. Line endings are not content here.
    """
    module = _generator()
    lf = tmp_path / "set.json"
    lf.write_bytes(b'{\n  "items": []\n}\n')
    crlf = tmp_path / "set-crlf.json"
    crlf.write_bytes(b'{\r\n  "items": []\r\n}\r\n')
    assert module._content_digests(lf) == module._content_digests(crlf)

    # Inside an archive, member for member -- and the two files really do differ
    # in bytes, so the equality above is the normalisation's doing.
    plain = tmp_path / "plain.epro2"
    re_spelled = tmp_path / "re-spelled.epro2"
    module._write_archive({}, "CH340G.epru", "a\nb\n", plain)
    module._write_archive({}, "CH340G.epru", "a\r\nb\r\n", re_spelled)
    assert plain.read_bytes() != re_spelled.read_bytes()
    assert module._content_digests(plain) == module._content_digests(re_spelled)

    # Content still counts: the same member carrying one more line is drift.
    changed = tmp_path / "changed.epro2"
    module._write_archive({}, "CH340G.epru", "a\nb\nc\n", changed)
    assert module._drift_labels(
        module._content_digests(plain), module._content_digests(changed)
    ) == ["CH340G.epru"]


def test_the_led_overcurrent_proposal_is_gone():
    """Ruled out by the oracle: not built, not listed, no edit function."""
    module = _generator()
    assert "led-overcurrent" not in [v["id"] for v in module.VARIANTS]
    assert "led_overcurrent" not in module.BUILDERS
    assert not (INJECTED / "led-overcurrent.epro2").exists()
    assert not (INJECTED / "led-overcurrent.json").exists()


# ---------------------------------------------------------------------------
# the clean base
# ---------------------------------------------------------------------------


def test_the_base_applies_the_oracles_two_corrections():
    model = load_board_model(BASE)
    assert model.components["U3"].mpn == EXPECTED_MPN
    assert _pin(model, "U1", "4").net == "VCC", "V3 must be tied to VCC"
    # V3 joined VCC, so the board has one net fewer than the golden and pin 4
    # is a member of the same net as pin 16. (The auto-named leftovers get
    # renumbered, so the name "NET1" simply moves to another cluster.)
    golden = load_board_model(GOLDEN)
    assert len(model.nets) == len(golden.nets) - 1
    assert _pin(model, "U1", "16").net == "VCC"
    assert ("U1", "16") in model.nets["VCC"].pins


def test_the_base_has_no_findings_at_all():
    """Not just "no false positives": nothing fires, by any rule."""
    assert _findings(BASE) == []


def test_the_two_native_defects_are_gone_from_the_base_and_still_there_on_the_golden():
    """The base is a correction, not a loosened harness.

    One of the golden board's two defects is no longer *detected*: U3's
    value/MPN pair is 2.13x, under batch 2's R tolerance, so
    ``param-value-mpn-match`` reports OK and the signed record goes to the
    missed column (the oracle knew: see the constant's comment in
    ``rules/params.py``). The V3 decoupling defect is untouched, and the point
    of this test -- the base, which carries the oracle's corrections, still
    fires nothing -- is unchanged.
    """
    golden_set = load_annotations(GOLDEN_SET)
    expected_detected = {"decap-required-caps": 1, "param-value-mpn-match": 0}
    for board in (BASE, GOLDEN):
        evaluation = evaluate_annotations(
            golden_set, load_board_model(board), BUILTIN_RULES
        )
        defects = [item for item in golden_set.items if item.kind == "defect"]
        assert len(defects) == 2, "the golden set's two defects"
        for item in defects:
            want = 0 if board == BASE else expected_detected[item.rule_hint]
            metric = _metric(evaluation, item.rule_hint)
            assert metric.detected == want, (board.name, item.ref)
            assert metric.violations == want, (board.name, item.ref)
    # The golden board's mpn defect is a *miss*, not silence about the part:
    # the rule still speaks about U3, and says the amplitude out loud.
    model = load_board_model(GOLDEN)
    waived = [
        o for o in ValueMpnMatch().outcomes(model)
        if o.subject == "U3" and o.state == "OK"
    ]
    assert len(waived) == 1 and "2.13x" in waived[0].message


# ---------------------------------------------------------------------------
# the variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", _board_ids())
def test_the_variant_carries_its_injected_fault_and_the_base_does_not(variant):
    """Every board on disk, retired ones included: the edit must still be there.

    Retirement withdraws the *claim*, not the board -- and the content guard
    only means something if the board it covers still carries the edit
    it was built with.
    """
    assert _fault_is_present(variant, load_board_model(INJECTED / f"{variant}.epro2"))
    assert not _fault_is_present(variant, load_board_model(BASE))


@pytest.mark.parametrize("variant", _eval_ids())
def test_no_variant_fires_on_the_clean_base(variant):
    """The base-fires half of the acceptance criterion, for the graded set."""
    aset, evaluation = _evaluation(INJECTED / f"{variant}.json", BASE)
    metric = _metric(evaluation, aset.items[0].rule_hint)
    assert (metric.defects_hinted, metric.detected, metric.violations) == (1, 0, 0)


def test_a_default_dev_run_grades_none_of_the_holdout_boards():
    """sec.2's mechanism, on the real family rather than a toy set.

    The harness default is ``dev``, so a held-back board contributes nothing --
    no detection, no denominator -- and the exclusion is *announced*, so a
    reader can tell "nothing wrong here" from "nothing was looked at".
    """
    for variant in _holdout_ids():
        aset, on_dev = _evaluation(
            INJECTED / f"{variant}.json",
            INJECTED / f"{variant}.epro2",
            split="dev",
        )
        assert on_dev.excluded_holdout >= 1
        assert _metric(on_dev, aset.items[0].rule_hint).defects_hinted == 0
        # The same board *is* graded once the filter is opened: the exclusion
        # is a filter, not a missing record.
        _same, on_holdout = _evaluation(
            INJECTED / f"{variant}.json",
            INJECTED / f"{variant}.epro2",
            split="holdout",
        )
        assert _metric(on_holdout, aset.items[0].rule_hint).detected == 1


def test_a_default_dev_run_still_grades_every_dev_board():
    for variant in _dev_ids():
        aset, on_dev = _evaluation(
            INJECTED / f"{variant}.json",
            INJECTED / f"{variant}.epro2",
            split="dev",
        )
        assert _metric(on_dev, aset.items[0].rule_hint).detected == 1


#: What each variant's rule reports on its own board. Five are caught;
#: ``v3-decap-missing`` is silent, and the test below says why.
CAUGHT = {
    "duplicate-designator": "conn-duplicate-designators",
    "nc-pin-grounded": "conn-nc-and-must-connect",
    "overvoltage-rail": "pwr-domain-vs-range",
    "ldo-no-headroom": "path-ldo-dropout",
    "value-mpn-mismatch": "param-value-mpn-match",
}


@pytest.mark.parametrize("variant,rule_id", sorted(CAUGHT.items()))
def test_the_expected_rule_catches_the_injected_fault(variant, rule_id):
    aset, evaluation = _evaluation(
        INJECTED / f"{variant}.json", INJECTED / f"{variant}.epro2"
    )
    assert evaluation.unregistered == [], "a signed hint must name a real rule"
    item = aset.items[0]
    assert item.rule_hint == rule_id and len(aset.items) == 1
    metric = _metric(evaluation, rule_id)
    assert (metric.defects_hinted, metric.detected) == (1, 1), metric
    assert (metric.missed, metric.caught_by_other) == (0, 0), metric
    assert metric.precision == 1.0 and metric.recall == 1.0, metric

    # The severity the annotation claims is the severity the rule reports.
    rule = next(r for r in BUILTIN_RULES if r.id == rule_id)
    findings = [
        f for f in rule.check(load_board_model(INJECTED / f"{variant}.epro2"))
        if item.ref in f.message or any(item.ref in e for e in f.evidence)
    ]
    assert findings, "the rule fired, but nothing in its finding names the ref"
    assert all(f.severity == item.severity for f in findings), [
        (f.severity, f.message[:80]) for f in findings
    ]


def test_the_retired_variant_stays_unverifiable_and_the_measurement_is_still_asserted():
    """Why ``v3-decap-missing`` was retired (sec.1.2), kept re-checkable.

    Removing C1 changes nothing that ``decap-required-caps`` asks about on this
    topology: the CH340's V3 capacitor record is tagged ``mode: 5V``, so on a
    3.3V rail it never applies, and the requirement that *does* apply (VCC
    needs 0.1uF) is met by C9's 2.2uF whether C1 is there or not. With C1 gone
    the rule's outcomes are identical to the base's, line for line.

    The variant is retired rather than fixed, because making it visible would
    mean editing three capacitors at once -- building a defect to fit the rule.
    This test is what keeps that claim checkable instead of folklore.
    """
    variant = INJECTED / f"{RETIRED}.epro2"
    assert "C1" not in load_board_model(variant).components, "the edit did happen"

    rule = DecapRequiredCaps()
    on_base = [(o.subject, o.state) for o in rule.outcomes(load_board_model(BASE))]
    on_variant = [(o.subject, o.state) for o in rule.outcomes(load_board_model(variant))]
    assert on_variant == on_base, "the injection is invisible: identical outcomes"
    assert ("U1 pin4", "OK") in on_variant and ("U1 pin16", "OK") in on_variant
    assert not [o for o in rule.outcomes(load_board_model(variant))
                if o.state == "VIOLATION"]
    assert _findings(variant) == []


def test_value_mpn_mismatch_carries_two_findings_and_the_second_is_unclaimed():
    """Batch 2's trade, pinned where it bites: 4.7k catches the MPN fault and
    takes the LED window with it.

    History, so the loss is not mistaken for an oversight. At 2.2k this board
    was a clean single-fault fixture: 2.2k sat exactly on the oracle's
    [470, 2200] ohm window ceiling, so ``param-led-current`` was quiet. Batch
    2 rules 2.2k/1k = 2.20x **below** the 3x R tolerance, which means the
    injection stopped being caught at all -- the variant would have bought a
    quieter rule at the price of a dead fixture. The injected value is now
    4.7k (4.70x, a violation), and 4.7k is above the window ceiling.

    The conflict is structural, not slack in the fixture: the window's ceiling
    is 2200 ohm, i.e. 2.20x of this board's own 1k MPN, so **no** value-field
    edit can be simultaneously >= 3x and inside the window. Reported to the
    oracle; the numbers it costs in the dev measurement are in
    ``outputs/015b_eval_dev.txt`` (one high-priority finding with no record to
    explain it).
    """
    led = lambda board: {  # noqa: E731 - a one-line reader, used twice
        o.subject: o.state for o in LedCurrent().outcomes(load_board_model(board))
    }
    assert led(BASE)["LED1"] == "OK", "the base stays clean"
    assert led(INJECTED / "value-mpn-mismatch.epro2")["LED1"] == "VIOLATION"

    # The base agrees with itself; the variant's MPN rule fires on the ref its
    # record names, and the LED rule fires on a ref no record claims.
    value_mpn = {
        o.subject: o.state
        for o in ValueMpnMatch().outcomes(load_board_model(BASE))
    }
    assert value_mpn["U3"] == "OK", "the base has value and MPN agreeing"
    findings = _findings(INJECTED / "value-mpn-mismatch.epro2")
    assert sorted(f.rule_id for f in findings) == [
        "param-led-current", "param-value-mpn-match",
    ]
    assert all(f.severity == "WARN" for f in findings)
    aset = load_annotations(INJECTED / "value-mpn-mismatch.json")
    assert [item.ref for item in aset.items] == ["U3"], (
        "the LED finding is deliberately not claimed by a second record: the "
        "annotation set is the oracle's, and re-writing it is his call"
    )


def test_the_base_annotation_set_carries_the_exceptions_but_no_defects():
    raw = json.loads((INJECTED / "fixed-base.json").read_text(encoding="utf-8"))
    assert [item["kind"] for item in raw["items"]] == ["exception"] * 3
    assert raw["reviewed_by"] and raw["reviewed_at"]
    # ...and they are the golden set's own exception records, not a paraphrase
    # that could drift: same refs, same hints.
    golden = load_annotations(GOLDEN_SET)
    assert [(i["ref"], i["rule_hint"]) for i in raw["items"]] == [
        (i.ref, i.rule_hint) for i in golden.items if i.kind == "exception"
    ]
