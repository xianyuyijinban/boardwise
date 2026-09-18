"""Module hygiene: a top-level name is defined **once** (task 008b, item 4).

`engines/replay.py` carried `_on_segment`, `_key` and `split_at_junctions`
twice — the two copies byte-identical, so behaviour was correct and every test
passed. That is exactly what makes the shape dangerous: Python keeps the *last*
definition, so editing the first copy does nothing at all, silently, and the
file goes on looking like it has the change. The task book's verdict for the
cleanup was "existing tests green with zero modifications"; this file is what
keeps the shape from coming back, because nothing else would notice.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "boardwise"


def duplicate_toplevel_definitions(source: str) -> dict[str, list[int]]:
    """``name -> [line numbers]`` for names defined more than once at module level.

    Only the module body is inspected: a nested function or a method legitimately
    shares a name with something else, and one module defining `_key` while
    another also does is normal (they are not the same scope).
    """
    tree = ast.parse(source)
    seen: dict[str, list[int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seen.setdefault(node.name, []).append(node.lineno)
    return {name: lines for name, lines in seen.items() if len(lines) > 1}


def test_the_scan_recognises_the_shape_it_exists_for():
    # Positive control: if this stops matching, the guard is dead weight.
    sample = "def a():\n    pass\n\n\ndef a():\n    pass\n"
    assert duplicate_toplevel_definitions(sample) == {"a": [1, 5]}
    assert duplicate_toplevel_definitions("def a():\n    def a():\n        pass\n") == {}
    assert duplicate_toplevel_definitions("class C:\n    pass\n\n\nclass C:\n    pass\n") == {
        "C": [1, 5]
    }


def test_no_module_defines_a_top_level_name_twice():
    offenders: list[str] = []
    files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
    assert len(files) > 15, f"only {len(files)} modules found — is PACKAGE right?"
    for path in files:
        for name, lines in duplicate_toplevel_definitions(
            path.read_text(encoding="utf-8")
        ).items():
            offenders.append(f"{path.relative_to(PACKAGE)}: {name} at lines {lines}")
    assert offenders == [], (
        "a name is defined twice at module level; the earlier definition is dead "
        "code that silently shadows nothing:\n  " + "\n  ".join(offenders)
    )


def test_replay_defines_its_junction_helpers_exactly_once():
    """The change this guard was written for, pinned by name."""
    source = (PACKAGE / "engines" / "replay.py").read_text(encoding="utf-8")
    for name in ("_on_segment", "_key", "split_at_junctions"):
        assert duplicate_toplevel_definitions(source).get(name) is None, name
    # and the surviving copy is the one the replay actually calls
    assert source.count("def split_at_junctions(") == 1
    assert "= split_at_junctions(plan.wires)" in source
    assert "from boardwise.engines.replay import split_at_junctions" in (
        PACKAGE / "engines" / "draw.py"
    ).read_text(encoding="utf-8")
