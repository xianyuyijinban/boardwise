"""Module-layer rules (006c, work item 2 — the constitution, executable).

`docs/architecture.md` states the import rules. Stated rules that nobody checks
decay, so this file is the executable version of that section: the same rules,
enforced on every run.

It was written immediately after it found a live violation. While drafting the
section, `core/candidate.py` was importing `_transform_point` — a **private**
name — from `parsers/schematic.py`, inside a function body, to keep the import
out of sight:

* `core` must not import `parsers` at all (the arrow only points the other
  way), and
* a private name crossing a layer boundary means the boundary is being worked
  around rather than used.

`transform_point` now lives in `core/geometry.py`, where both `parsers` and
`engines` may import it (see `docs/architecture.md`, "Three coordinate
spaces"). The rules below are what keeps the next one from happening quietly.

The layering graph (allowed imports, arrows point one way):

    cli / __init__   (assembly — may import anything)
      └── engines    → core, parsers, rules
      └── bridge     → itself only
      └── parsers    → core
      └── rules      → core
      └── core       → nothing inside the package
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "boardwise"

LAYERS = ("core", "parsers", "rules", "engines", "bridge", "render")

ALLOWED = {
    "core": frozenset(),
    "parsers": frozenset({"core"}),
    "rules": frozenset({"core"}),
    "engines": frozenset({"core", "parsers", "rules"}),
    # The bridge speaks its own protocol; it reaches the brain through the
    # daemon's imports, not by importing engines from inside a frame handler.
    "bridge": frozenset(),
    "render": frozenset({"core"}),
    # cli.py and the package __init__ are where the layers are assembled.
    "(top)": frozenset(LAYERS),
}

SELF = object()  # sentinel: an import that stays inside its own layer


def _layer_of(path: Path) -> str:
    relative = path.relative_to(PACKAGE)
    return relative.parts[0] if len(relative.parts) > 1 else "(top)"


def _python_files() -> list[Path]:
    return sorted(
        path for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts
    )


def _imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    """`(layer, names)` for every in-package import, absolute or relative.

    Positions are not reported: a function-local import is exactly the shape
    that hid the violation, so the rule does not care *where* it appears.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                try:
                    relative = base.relative_to(PACKAGE)
                except ValueError:
                    continue
                parts = str(relative).replace("\\", ".").split(".")
                head = parts[0] if parts and parts[0] else ""
                if (node.module or ""):
                    head = (node.module or "").split(".")[0]
                layer = head if head in LAYERS else ""
                names = tuple(alias.name for alias in node.names)
                found.append((layer or head, names))
            else:
                module = node.module or ""
                head = module.split(".")[0]
                if head == "boardwise":
                    parts = module.split(".")[1:]
                    head = parts[0] if parts else ""
                names = tuple(alias.name for alias in node.names)
                found.append((head, names))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                head = parts[0]
                if head == "boardwise":
                    head = parts[1] if len(parts) > 1 else ""
                found.append((head, ()))
    return [(layer, names) for layer, names in found if layer]


def test_the_scan_sees_the_package():
    files = _python_files()
    assert len(files) > 15, f"only found {len(files)} modules — is PACKAGE right?"
    layers = {_layer_of(path) for path in files}
    assert layers >= {"core", "parsers", "engines", "bridge"}, layers


def test_no_layer_imports_against_the_arrows():
    violations = []
    for path in _python_files():
        layer = _layer_of(path)
        allowed = ALLOWED.get(layer, frozenset())
        for target, _names in _imports(path):
            if target == layer or target in allowed:
                continue
            if target not in LAYERS:
                continue  # a third-party or stdlib name
            violations.append(
                f"{path.relative_to(PACKAGE)}: {layer} imports {target} "
                f"(allowed: {sorted(allowed) or 'nothing'})"
            )
    assert violations == [], (
        "import direction violated — see docs/architecture.md, 'Module rules':\n  "
        + "\n  ".join(violations)
    )


def test_no_private_name_crosses_a_layer():
    """A `_name` imported from another layer means the seam is being bypassed.

    006c fixed the one instance and work item 4 removed the other (a private
    framing helper in the copper builder). Both were function-local imports,
    which is why this checks every import regardless of depth.
    """
    crossings = []
    for path in _python_files():
        layer = _layer_of(path)
        for target, names in _imports(path):
            if target not in LAYERS or target == layer:
                continue
            for name in names:
                if name.startswith("_"):
                    crossings.append(
                        f"{path.relative_to(PACKAGE)}: imports {target}.{name} (private)"
                    )
    assert crossings == [], (
        "a private name crosses a layer boundary; make it public in its own "
        "layer, or move it to the layer that owns it:\n  " + "\n  ".join(crossings)
    )


def test_core_imports_nothing_from_the_package():
    """`core` is the bottom; anything it needs from above it must not need.

    Checked separately from the table above because it is the rule most likely
    to be broken under deadline pressure — a helper in `parsers` or `engines`
    is always closer to hand than a new `core` module.
    """
    offenders = []
    for path in _python_files():
        if _layer_of(path) != "core":
            continue
        for target, names in _imports(path):
            # `target == "core"` is a sibling module inside this layer, which
            # is exactly what a layer is allowed to do.
            if target in LAYERS and target != "core":
                offenders.append(f"{path.relative_to(PACKAGE)} imports {target}.{names}")
    assert offenders == [], "\n  ".join(offenders)


def test_the_rules_are_not_a_rubber_stamp():
    """Positive control: the tables must actually reject something.

    Written as a check on the *data* in this file, because a layering test that
    accidentally allows everything passes forever.
    """
    assert "connectors" not in ALLOWED
    assert ALLOWED["core"] == frozenset(), "core must be allowed nothing"
    assert ALLOWED["parsers"] == frozenset({"core"})
    assert "parsers" not in ALLOWED["parsers"]
    assert "engines" not in ALLOWED["bridge"], "the bridge must not import engines"
    assert set(ALLOWED["(top)"]) == set(LAYERS), "the assembly layer imports everything"


@pytest.mark.parametrize("module", ["core", "parsers", "engines", "bridge"])
def test_the_named_conversion_seam_is_where_it_is_documented(module):
    """`canvas_pin_offsets` and the parsers' boundary conversions are *named*.

    The coordinate rule ("conversions happen at the parser boundary and in
    `canvas_pin_offsets`") is only checkable because those entry points have
    names. If one is renamed, the rule in architecture.md stops describing the
    code.
    """
    if module == "engines":
        source = (PACKAGE / "engines" / "generate.py").read_text(encoding="utf-8")
        assert "def canvas_pin_offsets" in source
    elif module == "core":
        source = (PACKAGE / "core" / "geometry.py").read_text(encoding="utf-8")
        assert "def transform_point" in source, (
            "the symbol→page transform belongs in core so both parsers and "
            "engines can use it without a layer inversion"
        )
    elif module == "parsers":
        source = (PACKAGE / "parsers" / "schematic.py").read_text(encoding="utf-8")
        assert "transform_point" in source
    else:
        source = (PACKAGE / "bridge" / "protocol.py").read_text(encoding="utf-8")
        assert "ACTIONS" in source
