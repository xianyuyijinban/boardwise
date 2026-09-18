"""The two layout engines and the one place that chooses between them.

006b's architecture decision was that the golden replay is the **default** and
the generic solver is a **fallback**, used only when there is no golden layout
to replay. 006c (work item 5) asks for that boundary to be explicit rather
than incidental — the risk being two planners whose selection is spread across
call sites, so a failure cannot be attributed to either.

Measured 2026-09-16: the boundary already exists and is single —
`replay.engines.replay.replay_or_solver` is the only chooser, `draw.py` calls
it, and the engines themselves live in separate modules (`replay.py` for
golden, `generate.py` + `layout.py` for the solver). So this item is
**verification plus documentation**, not a refactor; these tests are what make
the verification repeatable.

The properties pinned here are the ones a future refactor would quietly break:

1. the default is replay;
2. the fallback happens for a *named* reason and says so in the plan notes;
3. nothing bypasses the chooser by calling an engine directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from boardwise.engines.generate import strip_dangling_nets
from boardwise.engines.replay import (
    replay_or_solver,
    sheet_frame_from_geometry,
)
from boardwise.parsers.schematic import (
    build_pin_offsets,
    build_schematic_model,
    collect_page_layout,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = "tests/fixtures/ch340_golden.epro2"
ENGINES = ROOT / "src" / "boardwise" / "engines"


@pytest.fixture(scope="module")
def golden():
    page = collect_page_layout(GOLDEN)
    return {
        "model": strip_dangling_nets(build_schematic_model(GOLDEN)),
        "page": page,
        "offsets": build_pin_offsets(GOLDEN),
        "frame": sheet_frame_from_geometry(
            {}, declared=page.sheet_attrs, origin=page.sheet_origin
        ),
    }


def test_replay_is_the_default_engine(golden):
    # Called exactly as the draw flow calls it: no `prefer_replay` passed.
    plan, source = replay_or_solver(
        golden["model"], golden["page"], golden["frame"], golden["offsets"]
    )
    assert source == "golden replay"
    assert plan.wires, "the replay produced a plan, not an empty one"
    assert not any("solver" in note for note in plan.notes)


def test_the_solver_is_reached_only_without_a_golden_layout(golden):
    plan, source = replay_or_solver(
        golden["model"], golden["page"], None, golden["offsets"]
    )
    assert source == "generic solver"
    assert any("sheet frame" in note for note in plan.notes), (
        "falling back must be explained in the plan, not just reported as a source"
    )


def test_an_empty_golden_page_falls_back_with_its_own_reason(golden):
    class EmptyPage:
        parts: list = []

    plan, source = replay_or_solver(
        golden["model"], EmptyPage(), golden["frame"], golden["offsets"]
    )
    assert source == "generic solver"
    assert any("no golden layout available" in note for note in plan.notes)


def test_a_blank_page_can_still_be_solved(golden):
    """`page=None` is the "no golden at all" case, and it must still plan."""
    plan, source = replay_or_solver(
        golden["model"], None, None, golden["offsets"]
    )
    assert source == "generic solver"
    assert plan.placements, "the solver produced no placements"


def test_prefer_replay_false_is_honoured(golden):
    """The escape hatch exists (006b used it to compare the two engines)."""
    plan, source = replay_or_solver(
        golden["model"], golden["page"], golden["frame"], golden["offsets"],
        prefer_replay=False,
    )
    assert source == "generic solver"
    assert plan.placements


def test_the_engines_live_in_separate_modules():
    replay = (ENGINES / "replay.py").read_text(encoding="utf-8")
    generate = (ENGINES / "generate.py").read_text(encoding="utf-8")
    layout = (ENGINES / "layout.py").read_text(encoding="utf-8")

    assert "def build_replay_plan" in replay
    assert "def generate_plan" in generate
    # They are not two names for the same file.
    assert "def build_replay_plan" not in generate
    assert "def generate_plan" not in replay
    # The solver's geometry primitives are their own module, not mixed into
    # the router.
    assert "class Rect" in layout
    assert "class Rect" not in replay
    assert "class Rect" not in generate


def test_the_chooser_is_the_only_thing_that_picks():
    """Draw must not call either engine directly, or the choice stops being one place."""
    draw = (ENGINES / "draw.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in draw.splitlines() if not line.lstrip().startswith("#")
    )
    assert "replay_or_solver(" in body, "draw.py no longer goes through the chooser"
    direct_replay = [
        match.group(0)
        for match in re.finditer(r"(?<!def )\bbuild_replay_plan\s*\(", body)
    ]
    assert direct_replay == [], (
        f"draw.py calls the replay engine directly ({direct_replay}) — the "
        "engine choice must stay in replay_or_solver"
    )
    assert not re.search(r"(?<!def )\bgenerate_plan\s*\(", body), (
        "draw.py calls the solver directly — the engine choice must stay in "
        "replay_or_solver"
    )


def test_the_chooser_reports_which_engine_ran(golden):
    """The source string is part of the contract: the report prints it.

    A silently different layout strategy is what makes a failure
    unreproducible, so "which engine" has to be an answerable question.
    """
    _, source = replay_or_solver(
        golden["model"], golden["page"], golden["frame"], golden["offsets"]
    )
    assert isinstance(source, str) and source
    assert source in {"golden replay", "generic solver"}

    draw = (ENGINES / "draw.py").read_text(encoding="utf-8")
    assert "plan_source" in draw
    assert "plan source" in draw, "the report must print the engine that ran"
