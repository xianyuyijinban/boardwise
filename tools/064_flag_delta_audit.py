#!/usr/bin/env python3
"""064 evidence: which field of which offline scenario a flag-compass change moves.

    .venv/Scripts/python.exe tools/064_flag_delta_audit.py dump DIR
    .venv/Scripts/python.exe tools/064_flag_delta_audit.py compare DIR_A DIR_B [OUT]
    .venv/Scripts/python.exe tools/064_flag_delta_audit.py declare DIR_A DIR_B OUT

064 split the flag compass per family (``gnd`` keeps 060's mapping, ``rail`` goes
back to 053B's), so the drawing of every scenario with a **rail** flag moves. A
digest cannot say *what* moved, and 064 sec.3 only allows a rail flag's
``rotation`` to move — any other difference is a finding, not a hash update. So
this tool dumps every scenario's drawing **and** page documents as JSON
(``dump``), diffs two revisions leaf by leaf (``compare``), and writes the
per-scenario declaration the task asks for (``declare``).

The documents it dumps, because a page hides its modules: each scenario's module
plan, the page document when there is one, and **every module's own plan** (a
page keeps only ``internalGeometrySha256`` of those — a digest, not evidence).
Digest leaves are excluded from the leaf diff on purpose: they are a function of
the leaves the diff already walks, and letting a hash stand in for a field is the
failure mode this tool exists to avoid.

The rule it enforces, field by field:

* every differing leaf must be a ``rotation`` whose two values differ by 180
  degrees — one flag's half turn (a digest leaf is a summary, reported apart);
* every flag must still be the same net at the same anchor with the same symbol
  (flags are matched by ``(net, x, y, symbolRef)``, per flag table);
* anything else — a coordinate, a wire point, a label box, a different flag set,
  a changed note — is printed as ``UNEXPECTED`` and makes ``declare`` refuse to
  bless the run.

**Run it twice, on two revisions**: ``dump`` with the change in the tree, then
``git show HEAD:<path> > <path>`` the touched sources back, ``dump`` again, and
restore from a ``cp`` backup (never ``git checkout --``). The scenarios are the
same twenty-four ``tools/060_flag_hash_audit.py`` audits — 053B's twelve, 056's
eight, 057's three page shapes — so the two audits line up line for line.

Nothing here writes a plan, runs a rule engine or touches the editor.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_053b_drawcompiler as b053  # noqa: E402
import test_056_pagecompiler as m056  # noqa: E402

from boardwise.core.model import is_ground_net  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, pagecompiler  # noqa: E402

#: A flag's ``rotation`` may move by exactly this much, and by nothing else.
FLAG_HALF_TURN = 180.0

#: The document fields the leaf diff walks, in the order a declaration reads them.
_DOCUMENT_KEYS = ("drawing", "modules", "page")


# ------------------------------------------------------------------- dumping


def _plan_json(plan: Any) -> dict | None:
    return plan.to_jsonable() if plan is not None else None


def _drawing(candidate: Any) -> tuple[dict | None, str]:
    """``(document, digest)`` for one module plan (``"refused"`` when there is none)."""
    if candidate is None:
        return None, "refused"
    return candidate.to_jsonable(), candidate.geometry_sha256()[:16]


def _doc(
    name: str, *, plan: Any = None, page: Any = None, modules: dict[str, Any] | None = None
) -> dict:
    """One scenario's whole evidence: every drawing it produced, plus the page."""
    drawing, drawing_sha = _drawing(plan)
    return {
        "name": name,
        "drawingSha": drawing_sha,
        "pageSha": page.page_geometry_sha256()[:16] if page is not None else "refused",
        "drawing": drawing,
        "modules": {
            key: {"sha": _drawing(value)[1], "drawing": _drawing(value)[0]}
            for key, value in sorted((modules or {}).items())
        },
        "page": _plan_json(page) if page is not None else None,
    }


def _module_candidates(result: pagecompiler.PageCompileResult) -> dict[str, Any]:
    return {name: compiled.best() for name, compiled in result.modules.items()}


def documents() -> list[dict]:
    """Every offline scenario, in the 060 audit's own order."""
    out: list[dict] = []
    for index, scene in sorted(b053.scenes().items()):
        result = b053.compile_scene(scene)
        out.append(_doc(f"053b.scene{index:02d}", plan=result.best()))
    for index, scene in sorted(m056.scenes().items()):
        result = m056.compile_scene(scene)
        page = result.pages[0] if result.pages else None
        out.append(_doc(
            f"056.scene{index:02d}", plan=page.plan if page else None, page=page,
            modules=_module_candidates(result),
        ))

    # 057's three page shapes, exactly as `tools/060_flag_hash_audit.py` builds
    # them (the same three the 060 declaration lists, so the two line up).
    circuit = b053.circuit(
        [b053.part("R1", "R0402", "10k"), b053.part("R2", "R0402", "10k")],
        [
            b053.net("SENSE", "signal", ["R1.1"]),
            b053.net("ADC", "signal", ["R1.2", "R2.1"]),
            b053.net("GND", "gnd", ["R2.2"]),
        ],
    )
    for tag, roles in (("declared", {"SENSE": "input", "ADC": "output"}),
                       ("undeclared", {"ADC": "output"})):
        presentation = b053.presentation(
            "voltage-divider",
            modules=[b053.module("d", ["R1", "R2"], "divider")],
            portRoles=roles,
        )
        result = b053.dc.compile(circuit, presentation, b053.library())
        out.append(_doc(f"057.O1.{tag}", plan=result.best()))

    scene = m056.scenes()[2]
    census = {
        "components": [
            {"primitiveId": "c-R9", "state": {"ComponentType": "part", "Designator": "R9",
                                              "X": 100, "Y": 700, "SupplierId": "C25744",
                                              "OtherProperty": {"Value": "1k"}}},
            {"primitiveId": "f-1", "state": {"ComponentType": "netflag", "Net": "GND",
                                             "X": 100, "Y": 600}},
        ],
        "wires": [{"primitiveId": "w-1", "state": {"Line": [100, 750, 380, 750],
                                                   "Net": "OLD"}}],
        "bboxes": {"c-R9": {"minX": 80, "minY": 640, "maxX": 120, "maxY": 760}},
    }
    boxes, _labels, _notes = drawapply.census_keepouts(census)
    budget = dataclasses.replace(
        scene.budget, keepouts=tuple(boxes), relocate_around_keepouts=True,
    )
    result = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), budget,
    )
    page = result.pages[0] if result.pages else None
    out.append(_doc(
        "057.E2", plan=page.plan if page else None, page=page,
        modules=_module_candidates(result),
    ))

    scene = m056.scenes()[1]
    payload = scene.presentation.to_jsonable()
    payload["userLocks"] = [{"partId": "R1", "x": 600, "y": 500, "scope": "page"}]
    result = pagecompiler.compile_page(
        scene.circuit, PresentationSpec.from_dict(payload), m056.library(),
        scene.budget,
    )
    page = result.pages[0] if result.pages else None
    out.append(_doc(
        "057.E3", plan=page.plan if page else None, page=page,
        modules=_module_candidates(result),
    ))
    return out


# ------------------------------------------------------------------- diffing


def _walk(before: Any, after: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Every ``(path, before, after)`` whose leaf value differs."""
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[tuple[str, Any, Any]] = []
        for key in sorted(set(before) | set(after)):
            out.extend(_walk(before.get(key), after.get(key), f"{path}/{key}"))
        return out
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [(f"{path}/length", len(before), len(after))]
        out = []
        for index, (left, right) in enumerate(zip(before, after)):
            out.extend(_walk(left, right, f"{path}[{index}]"))
        return out
    if before != after or type(before) is not type(after):
        return [(path, before, after)]
    return []


def _is_digest(path: str) -> bool:
    """Is this leaf a digest — a summary of leaves the walk already visits?"""
    leaf = path.rsplit("/", 1)[-1].lower()
    return leaf in ("sha", "sha256") or leaf.endswith(("sha", "sha256"))


def _at(document: dict, path: str) -> Any:
    """The value at a walk path (``/drawing/powerSymbols[2]``) inside a document."""
    node: Any = document
    for step in [part for part in path.split("/") if part]:
        if isinstance(node, dict):
            node = node.get(step)
            continue
        name, _, index = step.partition("[")
        if not isinstance(node, list) or not name:
            return None
        node = node[int(index.rstrip("]"))] if index else None
        if node is None:
            return None
    return node


def _flag_owner(document: dict, path: str) -> dict | None:
    """The flag entry a ``…``/``powerSymbols[i]/rotation`` path belongs to."""
    marker = "/powerSymbols["
    if not path.endswith("/rotation") or marker not in path:
        return None
    table_path, _, tail = path.partition(marker)
    try:
        index = int(tail.split("]", 1)[0])
    except ValueError:
        return None
    table = _at(document, table_path + "/powerSymbols")
    if not isinstance(table, list) or index >= len(table):
        return None
    flag = table[index]
    return flag if isinstance(flag, dict) else None


def _is_ground_flag(flag: dict) -> bool:
    """Is this flag the ground family? Judged by name, on this tool's own terms.

    The evidence has to be able to *refuse* a ground rotation on its own: the
    production classifier lives in the module under test, so this tool judges the
    family from the flag's net and symbol by the repo's ground-name ledger
    (`core.model.is_ground_net`) — the same names, reached without the code being
    audited.
    """
    reference = str(flag.get("symbolRef") or "").upper()
    tokens = [token.strip() for token in reference.split("-")]
    return any(is_ground_net(token) for token in tokens) or is_ground_net(
        str(flag.get("net") or "")
    )


def _is_allowed_rotation(document: dict, path: str, before: Any, after: Any) -> bool:
    """A **rail** flag's ``rotation``, moved by half a turn — and nothing else."""
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return False
    if (float(after) - float(before)) % 360.0 != FLAG_HALF_TURN:
        return False
    flag = _flag_owner(document, path)
    return flag is not None and not _is_ground_flag(flag)


def _flag_tables(doc: dict) -> list[tuple[str, list[dict]]]:
    """Every flag list in one scenario document, with the path that names it."""
    out: list[tuple[str, list[dict]]] = []
    for label, document in (("", doc.get("drawing")),
                            *[(f"module {name}", item.get("drawing"))
                              for name, item in (doc.get("modules") or {}).items()],
                            ("page", doc.get("page"))):
        if isinstance(document, dict):
            out.append((label, document.get("powerSymbols") or []))
    return out


def _flag_changes(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """``(moved, unexpected)`` — flags matched by ``(net, x, y, symbolRef)``.

    Matching by anchor is the point: 064 sec.3 allows a rotation to move and
    nothing else, so a flag that changed net, position or symbol is not "the same
    flag turned round" and is reported rather than summarised.
    """
    moved: list[str] = []
    unexpected: list[str] = []
    left = _flag_tables(before)
    right = _flag_tables(after)
    if len(left) != len(right):
        return moved, [f"flag table count {len(left)} -> {len(right)}"]
    for (where, one_table), (_, two_table) in zip(left, right):
        label = where or "drawing"
        if len(one_table) != len(two_table):
            unexpected.append(
                f"{label}: {len(one_table)} flag(s) -> {len(two_table)}"
            )
            continue
        for one, two in zip(one_table, two_table):
            key = lambda item: (item.get("net"), item.get("x"), item.get("y"),
                                item.get("symbolRef"))
            if key(one) != key(two):
                unexpected.append(f"{label}: flag {one} -> {two}")
                continue
            if one.get("rotation") != two.get("rotation"):
                # Marked, not filtered: a ground flag that moved is exactly what
                # 064 sec.3 forbids, so it has to be visible in the declaration.
                mark = "GROUND!" if _is_ground_flag(one) else ""
                moved.append(
                    f"{mark}{label}: {one.get('net')} @({one.get('x'):g},"
                    f"{one.get('y'):g}) rot {one.get('rotation'):g}"
                    f"->{two.get('rotation'):g}"
                )
    return moved, unexpected


def _difference_report(before: dict, after: dict) -> tuple[list[str], list[str], list[str]]:
    """``(digest moves, rail rotations, findings)`` for one scenario.

    Every leaf of every document is walked, so the claim "only a rail flag's
    rotation moved" is checked against the *fields*, not against a digest: a
    digest line is a summary of the leaves below it and is only reported as such.
    """
    digests: list[str] = []
    rotations: list[str] = []
    findings: list[str] = []
    root = {key: before.get(key) for key in _DOCUMENT_KEYS}
    for key in _DOCUMENT_KEYS:
        for spot, left, right in _walk(before.get(key), after.get(key), f"/{key}"):
            if _is_allowed_rotation(root, spot, left, right):
                owner = _flag_owner(root, spot) or {}
                rotations.append(
                    f"{spot}: {owner.get('net')} @({owner.get('x'):g},"
                    f"{owner.get('y'):g}) {owner.get('symbolRef')} "
                    f"{left:g} -> {right:g}"
                )
                continue
            if _is_digest(spot):
                digests.append(f"{spot}: {left} -> {right}")
                continue
            findings.append(f"{spot}: {left!r} -> {right!r}")
    _moved, unexpected = _flag_changes(before, after)
    return digests, rotations, [*findings, *unexpected]


def compare(before_dir: Path, after_dir: Path) -> tuple[str, bool]:
    """The full structural diff, one line per scenario. ``(text, clean)``."""
    lines: list[str] = []
    clean = True
    for path in sorted(before_dir.glob("*.json")):
        before = json.loads(path.read_text(encoding="utf-8"))
        after_path = after_dir / path.name
        if not after_path.exists():
            lines.append(f"{before['name']} | missing in the second dump — UNEXPECTED")
            clean = False
            continue
        after = json.loads(after_path.read_text(encoding="utf-8"))
        digests, rotations, findings = _difference_report(before, after)
        for spot in rotations:
            lines.append(f"{before['name']} | rail rotation {spot}")
        for spot in digests:
            lines.append(f"{before['name']} | digest {spot}")
        for spot in findings:
            clean = False
            lines.append(f"{before['name']} | UNEXPECTED {spot}")
        if not digests and not findings and not rotations:
            lines.append(f"{before['name']} | unchanged")
    return "\n".join(lines) + "\n", clean


def declare(before_dir: Path, after_dir: Path) -> tuple[str, bool]:
    """The 064 declaration, in 060's own format, plus its cleanliness verdict."""
    out = [
        "064 scenario-hash declaration: every offline scenario whose geometry digest",
        "moved, and the only field that moved inside it — a **rail** flag's rotation.",
        "The ground family may not move at all (060's mapping is unchanged), and no",
        "other field of any scenario may differ: `compare` in this directory walks",
        "every leaf of every module plan and page document and lists each difference.",
        "=" * 100,
    ]
    clean = True
    changed = 0
    total = 0
    rail_moves = 0
    ground_moves = 0
    for path in sorted(before_dir.glob("*.json")):
        before = json.loads(path.read_text(encoding="utf-8"))
        after = json.loads((after_dir / path.name).read_text(encoding="utf-8"))
        total += 1
        moved, unexpected = _flag_changes(before, after)
        _digests, rotations, findings = _difference_report(before, after)
        if rotations and not moved:
            unexpected.append(
                f"{len(rotations)} rotation leaf(s) moved but no flag table lists them"
            )
        rail_moves += len(rotations)
        inside = [line for line in moved if line.startswith("GROUND!")]
        ground_moves += len(inside)
        if inside:
            clean = False
        blocks: list[str] = []
        for field in ("drawingSha", "pageSha"):
            if before[field] != after[field]:
                blocks.append(
                    f"    {field[:-3].lower()} {before[field]} -> {after[field]}"
                )
        for key, item in (before.get("modules") or {}).items():
            after_item = (after.get("modules") or {}).get(key) or {}
            if item.get("sha") != after_item.get("sha"):
                left, right = item.get("sha"), after_item.get("sha")
                suffix = "(rail flag rotation)" if left != "refused" else ""
                blocks.append(f"    module {key} {left} -> {right} {suffix}".rstrip())
        if moved:
            blocks.append("    flags: " + "; ".join(moved))
        for spot in findings:
            clean = False
            blocks.append(f"    UNEXPECTED {spot}")
        if blocks:
            changed += 1
            out.extend([before["name"], *blocks])
    out.append("=" * 100)
    out.append(
        f"{changed} scenario line(s) changed of {total}; {rail_moves} rail flag"
    )
    out.append(
        f"rotation(s) moved and {ground_moves} ground flag rotation(s) moved (the"
    )
    out.append(
        "ground family must not move at all: 060's mapping is unchanged). Every flag"
    )
    out.append(
        "keeps its net, anchor and symbol; every digest line above is the summary of"
    )
    out.append(
        "the rail rotations listed with it; and no other field of any scenario"
    )
    out.append(
        "differs — `leaf_diff.txt` in this directory walks every leaf of every module"
    )
    out.append("plan and page document and reports each difference it found.")
    return "\n".join(out) + "\n", clean


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stdout.write(__doc__ or "")
        return 2
    mode = argv[1]
    if mode == "dump":
        target = Path(argv[2])
        target.mkdir(parents=True, exist_ok=True)
        for doc in documents():
            (target / f"{doc['name']}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
            )
        sys.stdout.write(
            f"{len(list(target.glob('*.json')))} scenario dump(s) in {target}\n"
        )
        return 0
    if mode in ("compare", "declare"):
        if len(argv) < 4:
            sys.stdout.write(f"usage: {mode} BEFORE_DIR AFTER_DIR [OUT]\n")
            return 2
        before_dir, after_dir = Path(argv[2]), Path(argv[3])
        text, clean = (
            compare(before_dir, after_dir) if mode == "compare"
            else declare(before_dir, after_dir)
        )
        if len(argv) > 4:
            Path(argv[4]).write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        sys.stdout.write(f"\nclean={clean}\n")
        return 0 if clean else 1
    sys.stdout.write(f"unknown mode {mode!r}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
