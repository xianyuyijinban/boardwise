"""Module owners and the cross-owner import guard (540B0.1).

`tests/test_layer_rules.py` checks the **layer** arrows of `docs/architecture.md`
(core / parsers / rules / engines / bridge / render). This file checks a finer
boundary that the layer table cannot see: every production module under
`src/boardwise` is owned by exactly one of four owners, and an import may only
cross into an owner that is allowed to be crossed into.

    shared    may import shared only
    review    may import shared, review
    draw      may import shared, draw
    assembly  may import anything — it is where the layers are wired

The four owners are not the six layers: `rules/**` is split (`rules.base` and
`rules.values` are the shared contract, the rest is review), `core/**` is split
(`annotations`/`railquery` are review, the drawing model is draw, the rest is
shared), and `engines/**` is split three ways. A vocabulary of layers cannot
express "the drawing chain must not reach into the reviewer's rule objects",
which is why this guard exists next to the layer guard instead of replacing it.

Two files carry the rules and must agree:

* `contracts/module-owners.json` — the manifest, one entry per module. Hand
  maintained (adding a module without an owner is a red test, not a silent
  `shared` default), and the only place an owner is written down.
* this file — the direction table, the AST scanner, and the legacy exceptions.

No cross-owner exceptions remain after 540B3. 540B0.1 registered five legacy
**draw → review** edges; B1 retired three through `core/netdomains.py`, B2
retired the pin-patch edge through `core/connectivity.py`, and B3 retired the
last `rules.decap` edge through `core/decap.py`. Everything is rejected outright:
`shared → review/draw` and `review → draw` have no exception list at all, and the
size of the registered set is asserted so a later batch that deletes a
workaround (or adds one) cannot pass quietly.

One owner was decided by this batch rather than taken from the layer table:
**`engines/assemble.py` is shared** (540B0.1, ruling B). It turns a `BoardSpec`
into the public model and imports nothing but `core.blocks`, `core.geometry`,
`core.model` and `parsers.schematic` — it imports no layout, no replay and no
compiler, so the BOM and the draw chain consume the same public artifact instead
of one reaching into the other. The rule is executable below
(`test_the_assembler_is_shared_and_only_builds_the_model`): if the assembler
ever grows a draw dependency, its owner is wrong and the test says so.

Where the scan looks: the whole module, at any depth. A function-local import is
exactly how the 006c violation hid from review (`test_layer_rules.py`, module
docstring), so `ast.walk` is used rather than the module body — the legacy edge
`patchpin → rules.facts` is inside a function body and would disappear from a
module-level-only scan.

Two import shapes need care, and both are covered by tests below:

* `from boardwise.core import values` imports the *module* `values`, not the
  `boardwise` package. Reading only the first dotted segment would blame the
  assembly `__init__` for a perfectly ordinary shared import.
* `from . import addcomponent` is relative to the file's own package, so
  `engines/drawapply.py` reaches `engines/addcomponent.py` — and
  `engines/grammar/__init__.py` reaches `engines/grammar/base.py`, not
  `engines/base.py`.

One exemption, stated because it is invisible otherwise: `from .. import
__version__` resolves to `boardwise/__init__.py`, which the manifest owns as
assembly. It is not a module edge — the root package holds a docstring and one
string, imports nothing, and re-exports no module (asserted below, so the
exemption dies the moment somebody puts a real module API there).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Iterable

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "boardwise"
MANIFEST = Path(__file__).resolve().parents[1] / "contracts" / "module-owners.json"

ROOT_MODULE = "boardwise"

OWNERS = ("shared", "review", "draw", "assembly")

#: What each owner may import. Itself included: a layer may always use its own
#: modules, and "may import itself" is the whole point of owning a boundary.
ALLOWED = {
    "shared": frozenset({"shared"}),
    "review": frozenset({"shared", "review"}),
    "draw": frozenset({"shared", "draw"}),
    "assembly": frozenset(OWNERS),
}

#: No tolerated cross-owner imports remain after 540B3. B1 retired the naming
#: edges, B2 retired patchpin → rules.facts, and B3 retired addcomponent →
#: rules.decap by moving the shared inventory/decision to `core/decap.py`.
#: Any new cross-owner edge must be justified in a later batch and reviewed.
LEGACY_EDGES = frozenset()


def _dotted(rel: str) -> str:
    """`engines/grammar/base.py` → `boardwise.engines.grammar.base`."""
    body = rel[: -len(".py")].replace("/", ".")
    if body == "__init__":
        return ROOT_MODULE
    if body.endswith(".__init__"):
        return f"{ROOT_MODULE}.{body[: -len('.__init__')]}"
    return f"{ROOT_MODULE}.{body}"


def _source_files() -> list[str]:
    return sorted(
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*.py")
        if "__pycache__" not in path.parts
    )


PATHS = tuple(_source_files())
PATH_OF_MODULE = {_dotted(rel): rel for rel in PATHS}


def _owners() -> dict[str, str]:
    """The manifest, `path → owner`. No default: a missing key is a KeyError."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return dict(data["modules"])


def _import_targets(rel: str, tree: ast.Module) -> set[str]:
    """Paths of the in-package modules `rel` imports, at any nesting depth.

    Positions are deliberately not reported — a function-local import is the
    shape that hid the 006c violation, so where it sits does not matter.
    """
    module = _dotted(rel)
    package = module if rel.endswith("__init__.py") else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                for _ in range(node.level - 1):
                    base = base[:-1]
                anchor = ".".join(base)
                target = f"{anchor}.{node.module}" if node.module else anchor
            else:
                target = node.module or ""
            names = [alias.name for alias in node.names]
            submodules = [
                f"{target}.{name}" for name in names if f"{target}.{name}" in PATH_OF_MODULE
            ]
            if submodules:
                found.update(submodules)
            elif target in PATH_OF_MODULE:
                found.add(target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in PATH_OF_MODULE:
                    found.add(alias.name)
    # `from .. import __version__`: the root package is assembly's front door,
    # but it re-exports no module — see the module docstring.
    found.discard(ROOT_MODULE)
    return {PATH_OF_MODULE[target] for target in found}


def _imports_of(rel: str) -> set[str]:
    tree = ast.parse((PACKAGE / rel).read_text(encoding="utf-8"))
    return _import_targets(rel, tree)


def _synthetic(rel: str, source: str) -> set[str]:
    """Imports of `source` read as if it were the file `rel` — nothing on disk."""
    return _import_targets(rel, ast.parse(source))


def _violations(pairs: Iterable[tuple[str, str]], owners: dict[str, str]) -> set[str]:
    """The cross-owner lines among `(source, target)` path pairs."""
    lines = set()
    for source, target in pairs:
        source_owner = owners[source]
        target_owner = owners[target]
        if target_owner in ALLOWED[source_owner]:
            continue
        lines.add(f"{source} -> {target} ({source_owner} -> {target_owner})")
    return lines


def _package_edges() -> set[tuple[str, str]]:
    return {(rel, target) for rel in PATHS for target in _imports_of(rel)}


# --------------------------------------------------------------------------
# The manifest: every module, exactly one owner, nothing stale
# --------------------------------------------------------------------------


def test_the_scan_sees_the_package():
    assert len(PATHS) == 142, (
        f"found {len(PATHS)} modules, expected the 142 this batch owns — "
        "a new module needs an owner line in contracts/module-owners.json"
    )
    assert {"core", "parsers", "rules", "engines", "bridge"} <= {
        rel.split("/")[0] for rel in PATHS
    }


def test_every_module_has_exactly_one_owner():
    owners = _owners()
    missing = sorted(set(PATHS) - set(owners))
    stale = sorted(set(owners) - set(PATHS))
    assert missing == [], f"modules with no owner in the manifest: {missing}"
    assert stale == [], f"manifest entries with no module behind them: {stale}"


def test_the_manifest_uses_only_the_four_owners():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(data["owners"]) == set(OWNERS), (
        "an owner was invented or dropped; the four names are the contract"
    )
    owners = data["modules"]
    assert all(isinstance(value, str) for value in owners.values()), (
        "an owner must be one name, not a list — a module has exactly one"
    )
    unknown = {rel: owner for rel, owner in owners.items() if owner not in OWNERS}
    assert unknown == {}, f"unknown owners: {unknown}"


def test_the_owner_lookup_has_no_default():
    """A `dict.get(path, "shared")` would make a new module silently shared."""
    owners = _owners()
    try:
        owners["engines/this_module_does_not_exist.py"]
    except KeyError:
        return
    raise AssertionError("looking up an unowned module must fail, not default")


# --------------------------------------------------------------------------
# The guard: the registered legacy edges and nothing else
# --------------------------------------------------------------------------


def test_no_import_crosses_an_owner_boundary():
    violations = _violations(_package_edges(), _owners())
    extra = sorted(violations - LEGACY_EDGES)
    gone = sorted(LEGACY_EDGES - violations)
    assert violations == set(LEGACY_EDGES), (
        "cross-owner imports changed — a new edge must be justified and registered "
        "in this file, a removed legacy edge must be deleted from it:\n"
        f"  new/unregistered: {extra or 'none'}\n"
        f"  registered but gone: {gone or 'none'}"
    )


def test_the_legacy_set_is_empty_after_b1_b2_and_b3():
    assert LEGACY_EDGES == frozenset(), (
        "540B3 retires the last legacy edge; any new cross-owner import must "
        "be reviewed as a new architectural decision, not hidden in this set"
    )


def test_all_four_owners_are_actually_used():
    """A vocabulary with a dead owner would let a whole class of edge through."""
    counts = {}
    for owner in _owners().values():
        counts[owner] = counts.get(owner, 0) + 1
    assert set(counts) == set(OWNERS), counts
    assert min(counts.values()) >= 1, counts


# --------------------------------------------------------------------------
# Positive controls: the table rejects what it must, and the scan sees depth
# --------------------------------------------------------------------------


def test_the_guard_rejects_every_forbidden_direction():
    """Synthetic edges — no file on disk has to violate the rules to prove it."""
    owners = _owners()
    rejected = _violations(
        [
            ("engines/islandlayout.py", "rules/pcb/focground.py"),  # draw -> review
            ("engines/review.py", "engines/islandlayout.py"),  # review -> draw
            ("core/geometry.py", "core/annotations.py"),  # shared -> review
            ("core/geometry.py", "core/islands.py"),  # shared -> draw
        ],
        owners,
    )
    assert rejected == {
        "engines/islandlayout.py -> rules/pcb/focground.py (draw -> review)",
        "engines/review.py -> engines/islandlayout.py (review -> draw)",
        "core/geometry.py -> core/annotations.py (shared -> review)",
        "core/geometry.py -> core/islands.py (shared -> draw)",
    }


def test_the_guard_allows_legal_edges():
    owners = _owners()
    allowed = _violations(
        [
            ("parsers/schematic.py", "core/geometry.py"),  # shared -> shared
            ("engines/islandlayout.py", "core/islands.py"),  # draw -> shared
            ("engines/islandlayout.py", "engines/router.py"),  # draw -> draw
            ("rules/facts.py", "core/geometry.py"),  # review -> shared
            ("rules/facts.py", "rules/decap.py"),  # review -> review
            ("cli.py", "core/geometry.py"),  # assembly -> shared
            ("cli.py", "engines/bom.py"),  # assembly -> review
            ("cli.py", "engines/assemble.py"),  # assembly -> shared
            ("engines/bom.py", "engines/assemble.py"),  # review -> shared (ruling B)
            ("cli.py", "__init__.py"),  # assembly -> assembly
        ],
        owners,
    )
    assert allowed == set()


def test_the_assembler_is_shared_and_only_builds_the_model():
    """Ruling B (540B0.1), executable: the owner follows the dependency set.

    `engines/assemble.py` maps a spec onto the public model. The moment it
    imports a layout, a replay or a compiler, "shared" stops being true and this
    test — not a review comment — is what catches it.
    """
    owners = _owners()
    assert owners["engines/assemble.py"] == "shared"
    targets = _imports_of("engines/assemble.py")
    foreign = sorted(target for target in targets if owners[target] != "shared")
    assert targets and foreign == [], (
        "the assembler may only import shared modules; it now reaches "
        f"{foreign}. Move the module to the owner it actually depends on."
    )


def test_the_scan_sees_imports_at_every_depth():
    """Module body, function body, class body — one scan, all of them."""
    source = (
        "from ..rules.decap import CapDecision\n"
        "def f():\n"
        "    from .assemble import assemble\n"
        "class C:\n"
        "    if True:\n"
        "        from ..core import values\n"
    )
    assert _synthetic("engines/bom_probe.py", source) == {
        "rules/decap.py",
        "engines/assemble.py",
        "core/values.py",
    }


# --------------------------------------------------------------------------
# Import shapes: absolute, relative, `__init__.py`, and the root package
# --------------------------------------------------------------------------


def test_from_package_import_submodule_is_the_submodule_not_assembly():
    """`from boardwise.core import values` is core.values, not `boardwise`."""
    assert _synthetic("engines/drawlint.py", "from boardwise.core import values\n") == {
        "core/values.py"
    }
    assert _synthetic("engines/drawlint.py", "from boardwise import resources\n") == {
        "resources.py"
    }


def test_sibling_and_parent_relative_imports():
    assert _synthetic("engines/drawapply.py", "from . import addcomponent\n") == {
        "engines/addcomponent.py"
    }
    assert _synthetic(
        "engines/patchpin.py", "from ..rules import facts as facts_rules\n"
    ) == {"rules/facts.py"}
    assert _synthetic(
        "engines/islandlayout.py", "from ..rules.pcb.focground import domain_of\n"
    ) == {"rules/pcb/focground.py"}


def test_init_imports_are_relative_to_their_own_package():
    """`engines/grammar/__init__.py` reaches `grammar.base`, not `engines.base`."""
    assert _synthetic("engines/grammar/__init__.py", "from . import base\n") == {
        "engines/grammar/base.py"
    }
    assert _synthetic("rules/pcb/__init__.py", "from . import foc\n") == {
        "rules/pcb/foc.py"
    }


def test_the_root_package_is_only_a_version_string():
    """The one exemption the scan makes, kept honest by this test.

    `from .. import __version__` (bridge/client.py, bridge/daemon.py,
    engines/review_eval.py) resolves to `boardwise/__init__.py`. That file may
    stay outside the guard only while it is a docstring and a version string: no
    imports, no re-exported modules. Put real API there and the exemption is no
    longer safe — this test fails first.
    """
    source = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    kinds = [type(node).__name__ for node in tree.body]
    assert kinds == ["Expr", "Assign"], kinds
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)
    ), "the root package must not import anything"
    assignment = tree.body[1]
    assert isinstance(assignment, ast.Assign) and len(assignment.targets) == 1
    target = assignment.targets[0]
    assert isinstance(target, ast.Name) and target.id == "__version__", (
        "the root package may publish exactly one constant, `__version__`"
    )
    assert isinstance(assignment.value, ast.Constant) and isinstance(
        assignment.value.value, str
    ), "the version must stay a literal — no code runs at import time"
    assert _synthetic("bridge/client.py", "from .. import __version__\n") == set(), (
        "a root-package attribute import is not a module edge"
    )
