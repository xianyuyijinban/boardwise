"""189A1: ``PadGeometry.layer_id`` is gone, and nothing reads it any more.

**Why this file exists.** 127b fixed every *reader* of the footprint's layer id,
but it left the field's **name** alone, and the name said the wrong thing. On a
real board a user took ``pad.layer_id`` (a landmine: the footprint's hardcoded
value, not rewritten when the part is flipped) and computed a clearance finding
that was **not there** — a wrong number, reported silently, handed to an
engineer. The stub is now ``footprint_layer_id`` and the retired name raises
with both replacements spelled out (:meth:`PadGeometry.__getattr__`).

Four locks, one per way the hole could reopen:

1. **the trap** — the old name raises (it does not return a number, and does not
   silently become a default), and the message names both replacements;
2. **the API shape** — no such field in ``dataclasses.fields`` / ``asdict``, and
   no such keyword in ``__init__`` (positional-order compatibility is kept);
3. **the measured facts 127b pinned are unchanged** — the 毕设FOC 1.0.0 fixture's
   28 bottom-face SMD pads still read ``footprint_layer_id == 1`` while their
   ``effective_layer_ids`` is ``[2]`` (that pair *is* the point: one part, two
   different facts, two names);
4. **the grep-level lock** — no expression in ``src/`` reads ``.layer_id`` off a
   pad (including the comprehension-variable form ``p.layer_id for p in
   board.pads``), and nothing constructs a ``PadGeometry`` with ``layer_id=``.
   A line carrying the batch number ``189A1`` is exempt, as the task book asks.

The same trap also makes lock 4 almost redundant — every src path is exercised by
the suite, so a leftover reader would raise instead of passing quietly. It is
kept anyway, because the point of a landmine is to be caught *before* someone
steps on it in a script that no test covers.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from boardwise.core.geometry import MULTI_LAYER_ID, PadGeometry
from boardwise.parsers.epru import extract_board, load_epro2_source

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
SRC = Path(__file__).resolve().parents[1] / "src" / "boardwise"
TESTS = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def pcb1():
    """毕设FOC 1.0.0's main PCB document — the board 127a measured the 28 on.

    Read through the public parser entry points (``load_epro2_source`` +
    ``extract_board``), and the title is asserted so the reading cannot quietly
    move to the project's two other PCB documents.
    """
    source = load_epro2_source(FOC)
    document = max(
        source.documents_of_type("PCB"),
        key=lambda d: sum(1 for r in d.records if r.type == "COMPONENT"),
    )
    title = ""
    for record in document.records:
        if record.type == "META" and record.body is not None:
            title = str(record.body.get("title") or "")
            break
    assert title == "PCB1", "the 28-pad reading belongs to PCB1"
    return extract_board(document, source.footprints(), source.stats)


BOTTOM_PARTS = ("U4", "U6", "R17", "C14")


# ---------------------------------------------------------------------------
# 1. the trap itself
# ---------------------------------------------------------------------------


def test_the_retired_name_raises_and_names_both_replacements():
    """``pad.layer_id`` is an ``AttributeError``, not a number and not a default.

    Both halves of the message matter: the point of the removal was that a
    reader could not tell which of the two facts they were holding, so a caller
    who trips the trap is told which name to use for which question.
    """
    pad = PadGeometry(
        id="R1.1", component="R1", footprint_layer_id=1, effective_layer_ids=[2]
    )
    with pytest.raises(AttributeError) as caught:
        pad.layer_id  # noqa: B018 - the read is the subject of the test
    message = str(caught.value)
    assert "footprint_layer_id" in message, message
    assert "effective_layer_ids" in message, message
    assert "127b" in message, "the message says why it is gone: " + message

    # The trap is a real absence, not a property that lies: ``hasattr`` agrees,
    # and ``getattr``'s default is reached (which is how a caller that already
    # wrote ``getattr(pad, "layer_id", None)`` keeps its own fallback).
    assert not hasattr(pad, "layer_id")
    assert getattr(pad, "layer_id", "DEFAULT") == "DEFAULT"

    # An unrelated missing name is still the ordinary AttributeError.
    with pytest.raises(AttributeError, match="no attribute 'not_a_field'"):
        pad.not_a_field


def test_the_trap_fires_on_a_real_flipped_pad(pcb1):
    """The landmine, on the fixture where it was a wrong answer.

    Every one of the 28 bottom-face SMD pads used to answer ``1`` here — top
    copper — while the copper is on the bottom of a 1.6 mm board. The read is
    now refused, and the two named readings answer the two different questions.
    """
    pad = pcb1.pads_for_component("U4")[0]
    assert pad.footprint_layer_id == 1, "the footprint's own value is preserved"
    assert pad.effective_layer_ids == [2], "the copper is on the bottom face"
    with pytest.raises(AttributeError) as caught:
        pad.layer_id  # noqa: B018 - the read is the subject of the test
    assert "footprint_layer_id" in str(caught.value)


# ---------------------------------------------------------------------------
# 2. the API shape (a rename, not a second field)
# ---------------------------------------------------------------------------


def test_the_dataclass_carries_no_layer_id_field():
    names = [f.name for f in dataclasses.fields(PadGeometry)]
    assert "layer_id" not in names, names
    assert "footprint_layer_id" in names, names
    # Position, not just presence: ``footprint_layer_id`` took over the slot the
    # old field held (after ``net``, before ``effective_layer_ids``), so a
    # positional caller keeps meaning the same thing.
    assert names.index("footprint_layer_id") == names.index("net") + 1
    assert names.index("effective_layer_ids") == names.index("footprint_layer_id") + 1
    dumped = dataclasses.asdict(PadGeometry(id="p", footprint_layer_id=3))
    assert "layer_id" not in dumped
    assert dumped["footprint_layer_id"] == 3


def test_the_constructor_refuses_the_retired_keyword():
    with pytest.raises(TypeError, match="layer_id"):
        PadGeometry(id="p", layer_id=1)  # type: ignore[call-arg]


def test_a_copy_still_carries_the_field():
    """``__getattr__`` must not swallow the dunder probes ``copy``/``pickle`` make.

    A trap that raised a bare ``AttributeError`` for *every* missing name, or
    that returned something for ``__deepcopy__``, would break the copy paths
    this model is passed through (the memoised review caches deepcopy boards).
    """
    import copy
    import pickle

    pad = PadGeometry(
        id="p", component="R1", footprint_layer_id=7, effective_layer_ids=[1, 2]
    )
    for clone in (copy.copy(pad), copy.deepcopy(pad), pickle.loads(pickle.dumps(pad))):
        assert isinstance(clone, PadGeometry)
        assert clone.footprint_layer_id == 7
        assert clone.effective_layer_ids == [1, 2]
        assert clone == pad


# ---------------------------------------------------------------------------
# 3. 127b's measured facts are unchanged by the rename
# ---------------------------------------------------------------------------


def test_the_28_bottom_pads_keep_both_readings(pcb1):
    """The fixture anchor: 28 pads, footprint layer 1, effective face 2.

    127a's measurement (`COMPONENT.layerId == 2` for U4 / U6 / R17 / C14 while
    all 28 of their SMD pads say ``layerId == 1``) is the fact the whole split
    rests on, and the rename is not allowed to move either half of it.
    """
    pads = [
        pad for designator in BOTTOM_PARTS for pad in pcb1.pads_for_component(designator)
    ]
    assert len(pads) == 28, f"127a measured 28 pads on {BOTTOM_PARTS}"
    for designator in BOTTOM_PARTS:
        assert pcb1.component(designator).layer_id == 2, (
            f"{designator} really is on the bottom face"
        )
    for pad in pads:
        assert pad.footprint_layer_id == 1, (
            f"{pad.component}.{pad.pin_number}: the footprint's own layer is "
            "still 1 — the rename does not rewrite the raw value"
        )
        assert pad.effective_layer_ids == [2], (
            f"{pad.component}.{pad.pin_number}: the effective reading is still "
            "the placement's face"
        )


def test_the_through_hole_pads_keep_their_footprint_value(pcb1):
    """SWD1's barrel pads still say ``layerId == 12`` (Multi-Layer) as stored."""
    pads = pcb1.pads_for_component("SWD1")
    assert len(pads) == 4, "SWD1 is a 4-pin through-hole header on PCB1"
    for pad in pads:
        assert pad.footprint_layer_id == MULTI_LAYER_ID
        assert pad.effective_layer_ids == [1, 2, 15, 16], (
            "the barrel reading is the four-layer stackup, unchanged"
        )


# ---------------------------------------------------------------------------
# 4. the grep-level lock
# ---------------------------------------------------------------------------

_BATCH = "189A1"
_PAD_NAME = re.compile(r"(?:^|_)pads?$")
_PAD_CALL = re.compile(r"\bpads_for_\w+\(")


def _is_pad_ish(text: str) -> bool:
    """Does this expression name a pad, or a collection of them?

    ``pad`` / ``cap_pads`` / ``board.pads`` / ``cap_pads[0]`` (tail name), and
    the accessors ``board.pads_for_component(...)`` / ``pads_for_net(...)``.
    ``pad_island`` / ``pad_count`` are *not* matched — the lock is on names that
    can be an element of the pad list, and a false positive here would fail on
    an unrelated class's legitimate ``layer_id``.
    """
    tail = re.sub(r"\[[^\]]*\]$", "", text).rsplit(".", 1)[-1]
    return bool(_PAD_NAME.search(tail)) or bool(_PAD_CALL.search(text))


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for elt in node.elts for name in _target_names(elt)]
    return []


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _bound_to_pad_collection(
    node: ast.AST, name: str, parents: dict[ast.AST, ast.AST]
) -> bool:
    """Is ``name``, at this node, a loop variable over a pad collection?

    Without this, the exact form 189A1 had to fix —
    ``[p.layer_id for p in board.pads]`` — would slip through a receiver-name
    scan, because the variable is called ``p``. The binding is resolved through
    the node's own enclosing comprehensions / ``for`` loops, so the neighbouring
    ``[p.layer_id for p in board.pours]`` on the same expression is *not* caught
    by the pad binding.
    """
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
            clauses: list[ast.AST] = list(cur.generators)
        elif isinstance(cur, ast.For):
            clauses = [cur]
        else:
            continue
        for clause in clauses:
            target = getattr(clause, "target", None)
            iterable = getattr(clause, "iter", None)
            if target is None or iterable is None:
                continue
            if _is_pad_ish(ast.unparse(iterable)) and name in _target_names(target):
                return True
    return False


def _offending_reads(source: str) -> list[str]:
    """Every ``.layer_id`` read off a pad in one module, as ``line`` rows."""
    tree = ast.parse(source)
    parents = _parents(tree)
    lines = source.splitlines()
    out: list[str] = []
    for node in ast.walk(tree):
        receiver: ast.AST | None = None
        if isinstance(node, ast.Attribute) and node.attr == "layer_id":
            receiver = node.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "layer_id"
        ):
            receiver = node.args[0]
        if receiver is None:
            continue
        text = ast.unparse(receiver)
        if not (
            _is_pad_ish(text)
            or _bound_to_pad_collection(receiver, text, parents)
        ):
            continue
        line = lines[node.lineno - 1]
        if _BATCH in line:
            continue
        out.append(f"line {node.lineno}: {line.strip()}")
    return out


def test_no_src_module_reads_the_retired_field_off_a_pad():
    """``src/`` may not read ``.layer_id`` from a pad, in any spelling.

    ``TrackSegment`` / ``PourShape`` / ``LayerInfo`` / ``PadTemplate`` /
    ``ComponentPlacement`` all still own a field with that name — the rename is
    about *the pad's* stub, and a board-wide ban would be a different (and wrong)
    claim. What is banned is the receiver: a name that can hold a ``PadGeometry``.
    A line carrying ``189A1`` is exempt, so a deliberate mention has to say so.
    """
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        violations.extend(
            f"{path.relative_to(SRC.parent.parent)}: {row}"
            for row in _offending_reads(text)
        )
    assert not violations, (
        "these read the removed pad field; use footprint_layer_id (the "
        "footprint's own value) or effective_layer_ids (where the copper is):\n"
        + "\n".join(violations)
    )


def _layer_id_keywords(text: str, path: Path) -> list[str]:
    tree = ast.parse(text)
    lines = text.splitlines()
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "PadGeometry":
            continue
        for kw in node.keywords:
            if kw.arg == "layer_id":
                line = lines[kw.value.lineno - 1]
                if _BATCH in line:
                    continue
                out.append(f"{path.name}:{kw.value.lineno}: {line.strip()}")
    return out


def test_nothing_constructs_a_pad_with_the_retired_keyword():
    """The constructor is the other half of the public API — ``src/`` *and* the
    suite's fixture builders must speak the new name (127b's measurements are
    kept by ``footprint_layer_id``, not by a compatibility keyword)."""
    violations: list[str] = []
    for root, skip in ((SRC, None), (TESTS, "test_189a_layer_id.py")):
        for path in sorted(root.rglob("*.py")):
            if skip is not None and path.name == skip:
                continue
            if "__pycache__" in path.parts:
                continue
            violations.extend(_layer_id_keywords(path.read_text(encoding="utf-8"), path))
    assert not violations, "layer_id= keyword on PadGeometry:\n" + "\n".join(violations)


def test_the_source_scan_catches_the_forms_189a1_removed():
    """Negative control for the two scans above: prove they have teeth.

    A grep-level lock that cannot fail is decoration. Each string here is a form
    the audit found (or the retired keyword itself), and each must be reported;
    the counter-cases are the neighbouring classes that legitimately keep the
    name, and each must stay silent.
    """
    for bad in (
        "x = [p.layer_id for p in board.pads]\n",
        "for pad in board.pads:\n    print(pad.layer_id)\n",
        "for ic_pad in board.pads_for_component('U1'):\n    print(ic_pad.layer_id)\n",
        "if cap_pads[0].layer_id == 1:\n    pass\n",
        "getattr(ic_pad, 'layer_id', None)\n",
        "y = pads_for_net('GND')[0].layer_id\n",
    ):
        assert _offending_reads(bad), f"the scan missed: {bad!r}"
    for good in (
        "x = [t.layer_id for t in board.tracks]\n",
        "x = [p.layer_id for p in board.pours]\n",
        "x = [e.layer_id for e in board.stackup]\n",
        "y = pad.footprint_layer_id\n",
        "y = pad.effective_layer_ids\n",
        "y = shape.layer_id\n",
        "y = component.layer_id\n",
    ):
        assert not _offending_reads(good), f"false positive: {good!r}"
    assert _layer_id_keywords("PadGeometry(id='p', layer_id=1)\n", Path("probe.py"))
    assert not _layer_id_keywords(
        "PourShape(id='p', layer_id=1)\n", Path("probe.py")
    )
