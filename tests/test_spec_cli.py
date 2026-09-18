"""The spec-driven CLI surface (task 008a, items 3-4; 009-M0 P0).

Three commands grew a ``--spec`` path: ``compare`` (the spec netlist as the
candidate — work item 4), ``lint`` (the assembled plan, offline, no editor) and
``draw`` (assemble and then execute through the existing chain — work items 3
and 5).

What is under test here is the *decisions* the CLI makes, not the socket: the
draw tests stub the bridge to refuse the connection, so they observe the order
— product validation gates, then assembly, then the double check, and only
then the editor — without a daemon. The one thing worse than no acceptance run
is an acceptance run that silently created a page in someone's project, so the
stub also *counts* how often it was opened: a refused spec must open it zero
times.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.blocks import load_board_spec
from boardwise.engines.assemble import assemble

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "blocklib" / "specs"
SPEC = SPEC_DIR / "ch340g_usb_uart.json"
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
SIDECAR = ROOT / "tests" / "fixtures" / "ch340_golden.overrides.json"

#: The acceptance command for task 008a work item 4: the specification against
#: the *corrected* golden (the sidecar is named, not assumed — see the note in
#: `_cmd_compare`).
COMPARE_SPEC = ["compare", "--spec", str(SPEC), "--golden", str(GOLDEN), "--overrides", str(SIDECAR)]


@pytest.fixture
def stub_bridge(monkeypatch):
    """A bridge that never connects, and counts how often it was asked to.

    The draw flow must reach for the editor only after every offline gate has
    passed; the counter is what proves a refused spec never got that far.
    """
    from boardwise.bridge.protocol import BridgeError

    class _StubClient:
        opens = 0

        @staticmethod
        async def open(*_args, **_kwargs):
            _StubClient.opens += 1
            raise OSError("connection refused")

    class _StubDaemon:
        @staticmethod
        def resolve_port() -> int:
            return 1

        @staticmethod
        def ensure_token() -> str:
            return "token"

    class _StubModule:
        BridgeClient = _StubClient

    monkeypatch.setattr(
        cli, "_bridge_modules", lambda: (_StubModule, _StubDaemon, BridgeError)
    )
    return _StubClient


@pytest.fixture
def variant(tmp_path):
    """A modified copy of the spec, in tmp (so the repository stays clean).

    Template paths are absolutised on the way out: a spec resolves its blocks
    relative to itself, so a copy that lives elsewhere must say where they are.
    """
    counter = [0]

    def make(**changes) -> Path:
        raw = json.loads(SPEC.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if key == "params":
                raw["params"].update(value)
            else:
                raw[key] = value
        for block in raw["blocks"]:
            block["template"] = str((SPEC_DIR / block["template"]).resolve())
        counter[0] += 1
        path = tmp_path / f"variant_{counter[0]}.json"
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    return make


def test_compare_spec_matches_the_golden(capsys):
    code = cli.main(COMPARE_SPEC)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "no differences — designs match" in out
    assert "candidate spec" in out
    # the sidecar's corrections are named, with their provenance
    assert "golden override: U3" in out and "人为错误" in out


def test_compare_without_the_sidecar_stays_a_raw_comparison(capsys):
    """`compare`'s task-005 contract: a file against a file, nothing corrected.

    The spec states the corrected design, so a raw comparison shows the three
    corrections as differences. That is the honest output — and saying so is
    what keeps "no differences" from meaning "we quietly fixed the fixture".
    """
    code = cli.main(["compare", "--spec", str(SPEC), "--golden", str(GOLDEN)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "golden override:" not in out
    assert "R24: lcsc differs" in out
    assert "U3: value differs" in out
    assert "net 0, pin 0" in out  # only component rows; connectivity is equal


def test_compare_spec_shows_a_changed_parameter_as_a_difference(variant, capsys):
    path = variant(params={"usb.r24_value": "10K"})
    code = cli.main(
        ["compare", "--spec", str(path), "--golden", str(GOLDEN), "--overrides", str(SIDECAR)]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "[component] R24: value differs" in out
    assert "total: 1 difference(s)" in out


def test_compare_wants_exactly_one_candidate_source(capsys):
    assert cli.main(["compare", "--golden", str(GOLDEN)]) == 2
    assert "give a candidate .epro2 or --spec" in capsys.readouterr().err
    code = cli.main(
        ["compare", str(GOLDEN), "--spec", str(SPEC), "--golden", str(GOLDEN)]
    )
    assert code == 2
    assert "two different candidate sources" in capsys.readouterr().err


def test_lint_spec_is_clean(capsys):
    code = cli.main(["lint", "--spec", str(SPEC)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "layout lint: 0 violations" in out
    assert "plan source: golden replay" in out
    # the assembly is described at the top, not buried
    assert "block usb <- ch340_usb_input" in out
    assert "connections (page net <- ports):" in out
    assert "D+       <- usb.D+(D+), core.D+(D+)" in out


def test_lint_spec_lints_the_decorative_text_strategy_by_name(capsys):
    cli.main(["lint", "--spec", str(SPEC), "--naming", "text"])
    assert "drawn as TEXT (decorative, not native net labels)" in capsys.readouterr().out


def test_lint_spec_reports_a_bad_layout(variant, capsys):
    """Stacking every block on one spot must be reported, not tolerated."""
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    for block in raw["blocks"]:
        block["at"] = [20.0, -250.0]
    path = variant(blocks=raw["blocks"])
    code = cli.main(["lint", "--spec", str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "violation(s)" in out


def test_lint_wants_exactly_one_plan_source(capsys):
    assert cli.main(["lint"]) == 2
    assert "give --from" in capsys.readouterr().err
    assert cli.main(["lint", "--spec", str(SPEC), "--from", str(GOLDEN)]) == 2
    assert "two plan sources" in capsys.readouterr().err


def test_draw_refuses_two_design_sources(capsys):
    code = cli.main(["draw", "--spec", str(SPEC), "--from", str(GOLDEN)])
    assert code == 2
    assert "two design sources" in capsys.readouterr().err


def test_draw_refuses_the_solver_with_a_spec(capsys):
    """The generic solver places parts unrotated; block geometry is not."""
    code = cli.main(["draw", "--spec", str(SPEC), "--solver"])
    assert code == 2
    assert "cannot lay out block geometry" in capsys.readouterr().err


def test_the_double_check_passes_on_the_committed_spec(capsys):
    design = assemble(load_board_spec(SPEC))
    code = cli._double_check_spec(design.model, str(GOLDEN), str(SPEC))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "reproduces the golden" in out


def test_the_double_check_aborts_on_a_spec_that_does_not(capsys):
    """The gate that stands between a wrong specification and a mutated project."""
    spec = load_board_spec(SPEC)
    spec.params["core.c1_value"] = "1uF"
    design = assemble(spec)
    code = cli._double_check_spec(design.model, str(GOLDEN), str(SPEC))
    out = capsys.readouterr().out
    assert code == 2
    assert "DOES NOT REPRODUCE THE GOLDEN" in out
    assert "C1: value differs" in out


def test_draw_spec_validates_assembles_and_double_checks_before_the_bridge(stub_bridge, capsys):
    """The pre-flight gates are offline; the bridge is opened after all of them.

    The connector is stubbed to refuse the connection, so the test observes the
    *order* without a daemon: product validation -> assembly -> double check ->
    (then, and only then) an attempt to reach the editor. On a real run the
    same order is what keeps a wrong specification from mutating someone's
    project.
    """
    code = cli.main(["draw", "--spec", str(SPEC), "--golden", str(GOLDEN)])
    captured = capsys.readouterr()
    assert code == 2
    # the product validation gates ran first and passed the committed spec
    assert "spec validation (spec sha256:" in captured.out
    assert "closed-book" in captured.out and "skipped" in captured.out
    assert "verdict: may proceed" in captured.out
    # then the assembly and the double check
    assert "assembly from" in captured.out
    assert "block usb <- ch340_usb_input" in captured.out
    assert "the specification reproduces the golden" in captured.out
    # in that order, and only after all three did it try to reach the editor
    assert captured.out.index("verdict: may proceed") < captured.out.index("assembly from")
    assert "daemon not reachable" in captured.err
    assert stub_bridge.opens == 1


# --------------------------------------------------------------------------
# 009-M0 P0: the pre-draw product gates, and the benchmark flag
# --------------------------------------------------------------------------


def _with_bogus_level_clash(raw: dict) -> dict:
    """Join a 3V3 UART pin to a USB pin: two IO domains, no shifter on the net."""
    raw["connections"].append({"net": "BOGUS", "ports": [["uart", "TX"], ["usb", "D+"]]})
    return raw


def test_draw_refuses_a_spec_with_an_electrical_fault(stub_bridge, variant, capsys):
    """A level clash is a pre-flight stop: no assembly, and no bridge call —
    zero writes is the whole point of running the gates first."""
    raw = _with_bogus_level_clash(json.loads(SPEC.read_text(encoding="utf-8")))
    path = variant(connections=raw["connections"])
    code = cli.main(["draw", "--spec", str(path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "level-domain" in captured.out
    assert "verdict: STOPPED" in captured.out
    assert "assembly from" not in captured.out, "validation precedes assembly"
    assert "failed validation; nothing was executed" in captured.err
    assert stub_bridge.opens == 0


def test_draw_rechecks_the_spec_on_every_run(stub_bridge, tmp_path, capsys):
    """No caching: the same path is re-read, and a pass does not outlive an
    edit — the printed sha256 is bound to the bytes that were checked."""
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    for block in raw["blocks"]:
        block["template"] = str((SPEC_DIR / block["template"]).resolve())
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    first = cli.main(["draw", "--spec", str(path)])
    captured = capsys.readouterr()
    assert first == 2, captured.out  # validation passed; the stub bridge refused
    assert "verdict: may proceed" in captured.out
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    assert f"spec sha256:{digest}" in captured.out
    assert "daemon not reachable" in captured.err
    assert stub_bridge.opens == 1

    _with_bogus_level_clash(raw)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    second = cli.main(["draw", "--spec", str(path)])
    captured = capsys.readouterr()
    assert second == 2
    assert "verdict: STOPPED" in captured.out
    assert "level-domain" in captured.out
    new_digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    assert new_digest != digest
    assert f"spec sha256:{new_digest}" in captured.out
    assert stub_bridge.opens == 1, "a refused spec must never reach the bridge"


def test_validate_leaves_the_closed_book_out_of_product_validation(capsys):
    """The committed spec's blocks were cut out of its own golden; product
    validation does not care — only the benchmark grades that."""
    code = cli.main(["validate", "--spec", str(SPEC)])
    captured = capsys.readouterr()
    assert code == 0, captured.out
    assert "closed-book" in captured.out and "skipped" in captured.out
    assert "self-reference" not in captured.out


def test_validate_benchmark_still_catches_the_leak(capsys):
    """--benchmark is the generation evaluation: the same spec, the same
    blocks, and now tracing them to the target board is a refusal."""
    code = cli.main(
        ["validate", "--spec", str(SPEC), "--benchmark", "--target", str(GOLDEN)]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "self-reference" in captured.out
