"""540B1: one shared net-name vocabulary for the reviewer and the drawing chain.

Two pure name tests used to live in the rule modules that first needed them —
``rules/pcb/focground.domain_of`` (with its two prefix tuples) and
``rules/facts.is_auto_net`` (with its regex). The drawing chain read them
through those rule modules, which is why 540B0.1 carried three ``draw → review``
legacy edges. This batch moved the *implementations* to
``core/netdomains.py`` (shared) and left the rule modules re-exporting the very
same objects, so there is one word list, one regex, and no engine→rules import.

What this file pins, in order:

1. **The callable/constant identity** across the old and new import surfaces —
   an ``is`` check, not equality, because a copied tuple would still compare
   equal and drift later;
2. **The frozen behaviour**, case by case, hardcoded here (the ignored
   ``evidence/540/naming-baseline.json`` was the measurement; this test must not
   read it, because a permanently ignored file cannot be a permanent oracle);
3. **The absence of legacy edges after B3** and the manifest's ``shared`` owner;
4. **The purity of the vocabulary** and the emptiness of the rules import set in
   the three drawing modules (``islandlayout``'s equivalent scan lives here,
   where the 173/C exception used to be described in the compiler test).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from boardwise.core import netdomains
from boardwise.engines import drawapply, drawcompiler, islandlayout
from boardwise.rules import facts
from boardwise.rules.pcb import focground

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "boardwise"

#: ``(net, expected)`` — the pre-540B1 answers, straight from the baseline
#: measurement. ``None`` is included because callers hand it in.
DOMAIN_BASELINE = [
    ("PGND", "power"),
    ("pgnd_analog", "power"),
    ("P_GND", "power"),
    ("POWER_GND", "power"),
    ("EARTH", "power"),
    ("EARTHING", "power"),
    ("GND", "logic"),
    ("AGND", "logic"),
    ("DGND", "logic"),
    ("EGND", "logic"),
    ("SGND", "logic"),
    ("VSS", "logic"),
    ("SEC_GND", ""),
    ("ISO_VSS", ""),
    ("+24V", ""),
    ("", ""),
    (" gnd ", "logic"),
    (None, ""),
]

#: ``(name, expected)`` — the same frozen answers for the editor's auto names.
AUTO_NET_BASELINE = [
    ("NET1", True),
    ("net7", True),
    ("$57N2", True),
    ("$", False),
    ("NET_OUT", False),
    ("GND", False),
    ("", False),
    (" NET12 ", True),
    ("$57 N2", False),
    (None, False),
]


def _ids(cases: list[tuple[object, object]]) -> list[str]:
    return [repr(case[0]) for case in cases]


# ---------------------------------------------------------------------------
# 1. The old import surface and the shared module are the same objects
# ---------------------------------------------------------------------------


def test_the_historical_import_surfaces_are_the_same_objects():
    """Identity, not equality: two equal tuples would drift on the next edit."""
    assert focground.domain_of is netdomains.domain_of
    assert facts.is_auto_net is netdomains.is_auto_net
    assert (
        focground.GROUND_DOMAIN_POWER_PREFIXES
        is netdomains.GROUND_DOMAIN_POWER_PREFIXES
    )
    assert (
        focground.GROUND_DOMAIN_LOGIC_PREFIXES
        is netdomains.GROUND_DOMAIN_LOGIC_PREFIXES
    )


def test_the_word_lists_keep_their_old_names_and_public_surface():
    assert "domain_of" in focground.__all__
    assert "GROUND_DOMAIN_POWER_PREFIXES" in focground.__all__
    assert "GROUND_DOMAIN_LOGIC_PREFIXES" in focground.__all__
    # The engine's own public name is unchanged, too (drawcompiler imports it
    # at module level; islandlayout and drawapply use the same function).
    assert drawcompiler.domain_of is netdomains.domain_of
    assert islandlayout.domain_of is netdomains.domain_of


def test_the_vocabulary_is_verbatim_in_order_and_semantics():
    """The lists are copied character for character, order included.

    Order is behaviour: the power family is consulted first, so a name both
    families could claim lands on the power side.
    """
    assert netdomains.GROUND_DOMAIN_POWER_PREFIXES == (
        "PGND",
        "P_GND",
        "POWER_GND",
        "EARTH",
    )
    assert netdomains.GROUND_DOMAIN_LOGIC_PREFIXES == (
        "GND",
        "AGND",
        "DGND",
        "EGND",
        "SGND",
        "VSS",
    )
    assert netdomains.AUTO_NET_RE.pattern == r"^(NET\d+|\$\S+)$"
    assert netdomains.AUTO_NET_RE.flags & re.IGNORECASE


# ---------------------------------------------------------------------------
# 2. The frozen behaviour, item by item
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("net", "expected"), DOMAIN_BASELINE, ids=_ids(DOMAIN_BASELINE))
def test_domain_of_matches_the_frozen_baseline(net: str | None, expected: str):
    assert netdomains.domain_of(net) == expected
    # The old spelling is the same callable, so it must answer the same row.
    assert focground.domain_of(net) == expected


@pytest.mark.parametrize(
    ("name", "expected"), AUTO_NET_BASELINE, ids=_ids(AUTO_NET_BASELINE)
)
def test_is_auto_net_matches_the_frozen_baseline(name: str | None, expected: bool):
    assert netdomains.is_auto_net(name) is expected
    assert facts.is_auto_net(name) is expected


def test_power_is_consulted_before_logic():
    """``PGND`` starts with ``P`` *and* contains ``GND``; the power word wins."""
    assert netdomains.domain_of("PGND") == "power"
    assert netdomains.domain_of("PGND_GND") == "power"
    assert netdomains.domain_of("gnd") == "logic"


def test_an_empty_name_is_not_an_auto_net_and_not_a_domain():
    assert netdomains.domain_of("") == ""
    assert netdomains.domain_of("   ") == ""
    assert netdomains.is_auto_net("") is False
    assert netdomains.is_auto_net("   ") is False


# ---------------------------------------------------------------------------
# 3. The eliminated legacy edges and the manifest
# ---------------------------------------------------------------------------


def _owner_rules():
    """Load ``tests/test_owner_rules.py`` as a module — its tables are the guard."""
    path = Path(__file__).with_name("test_owner_rules.py")
    spec = importlib.util.spec_from_file_location("_owner_rules_540b1", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_legacy_edges_remain_after_b1_b2_and_b3():
    assert _owner_rules().LEGACY_EDGES == frozenset()


def test_the_manifest_owns_the_vocabulary_as_shared():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["modules"]["core/netdomains.py"] == "shared"
    assert data["batch"] == "540B6"


# ---------------------------------------------------------------------------
# 4. Purity: the vocabulary imports no rules, and the drawing chain is free
# ---------------------------------------------------------------------------


def _in_package_imports(source: Path) -> set[str]:
    """In-package modules imported by ``source``, as package-relative paths.

    Mirrors ``tests/test_owner_rules.py``'s scanner: absolute and relative
    forms, ``from package import submodule``, and function-local imports.
    """
    relative = source.relative_to(PACKAGE).as_posix()
    parts = relative[: -len(".py")].split("/")
    package = parts[:-1]
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target == "boardwise":
                target = ""
            elif target.startswith("boardwise."):
                target = target[len("boardwise.") :]
            stem = target.split(".") if target else []
            candidates = ["/".join(stem) + ".py"] if stem else []
            candidates += [
                "/".join(stem + [alias.name]) + ".py" for alias in node.names
            ]
            found.update(
                candidate for candidate in candidates if (PACKAGE / candidate).is_file()
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "boardwise":
                    continue
                if name.startswith("boardwise."):
                    name = name[len("boardwise.") :]
                candidate = name.replace(".", "/") + ".py"
                if (PACKAGE / candidate).is_file():
                    found.add(candidate)
    return found


def test_the_vocabulary_is_pure_and_imports_nothing_in_the_package():
    source = PACKAGE / "core" / "netdomains.py"
    assert _in_package_imports(source) == set()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    external = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert external <= {"re"}, f"the vocabulary grew an outside dependency: {external}"
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("boardwise")
        for node in ast.walk(tree)
    ), "the vocabulary must not import the package at all"


@pytest.mark.parametrize(
    "engine",
    ["engines/drawcompiler.py", "engines/islandlayout.py", "engines/drawapply.py"],
)
def test_no_drawing_module_imports_the_rules_layer(engine: str):
    """173/C's exception is retired: the word list is shared now, not borrowed.

    This is the island-layout counterpart of
    ``test_053b_drawcompiler.py::test_the_compiler_imports_nothing_above_its_layer``.
    """
    imports = _in_package_imports(PACKAGE / engine)
    rules_edges = sorted(path for path in imports if path.startswith("rules/"))
    assert rules_edges == [], f"{engine} still reaches into the rules layer: {rules_edges}"
    assert "core/netdomains.py" in imports
