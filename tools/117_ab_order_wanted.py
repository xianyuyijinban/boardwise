#!/usr/bin/env python3
"""117③ A/B：`_order_wanted` 修前 / 修后，**两个子进程**，逐点比全部变体。

    .venv/Scripts/python.exe tools/117_ab_order_wanted.py

输出一个 JSON 到 stdout：每个真实输入、每个变体、每个原点，**修前**与**修后**
各一份，外加两个 sha256。

**为什么必须是子进程**：两版只差一个函数体，在同一进程里只能靠
monkeypatch 换——而本模块里 `_order_wanted` 被 `_order_direction` 直接引用，
monkeypatch 能换函数对象，但换不掉任何**已经算好的缓存**。子进程里换整张表
（`_order_wanted = _order_wanted_116`）则干净：另一个进程读的是另一次
import，不存在任何共享状态。

**为什么关系闸要关掉**：闸会在第一个拒绝处停下，活下来的变体才量得到——那样
量到的只是"能过闸的那部分"，字节闸会假绿。关掉之后**每个变体**都能落子，
包括那些被闸拒掉的。坐标全量比，才是真的零效应。

**116 的旧表**（照抄 116 §四 的实测表，subject 端）：
``left-of=+1  right-of=-1  above=+1  below=-1``
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.engines import drawcompiler as dc  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
OLD_TABLE = {
    "left-of": (0, -1.0), "right-of": (0, 1.0),
    "above": (1, -1.0), "below": (1, 1.0),
}


def _order_wanted_116(kind: str, own: bool) -> tuple[int, float]:
    """116 shipped this table — the object factor inverted, the horizontal
    sign factor inverted too, which cancelled out on the two vertical kinds."""
    index, sign = OLD_TABLE[kind]
    return index, -sign


def _inputs():
    from importlib import import_module

    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec

    for name, module_name in (("088b", "test_088b_followups"),
                              ("098", "test_098_ic_periphery")):
        module = import_module(module_name)
        yield name, module.sample(), module.library()
    yield (
        "flyback",
        (CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
         PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")),
        import_module("test_113_flyback_grammar")._library_from(
            SPECS / "flyback_uc3845.library.json"),
    )


def _measure() -> list:
    """One line per variant per input: every origin, sorted, fully expanded."""
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx, placed: []
    try:
        out = []
        for name, sample, book in _inputs():
            circuit, presentation = sample
            binding = dc.bind_grammar(circuit, presentation, book)
            prepared = dc._prepare(circuit, presentation, binding, book,
                                   dc.CompileBudget(max_candidates=64))
            if prepared.context is None:
                out.append(f"{name}: no context")
                continue
            ctx = prepared.context
            for variant in dc._variants(ctx):
                placed, _ = dc._place(ctx, variant)
                if placed is None:
                    out.append(f"{name} {variant.label}: refused")
                    continue
                origins = ";".join(
                    f"{part_id}={placed.origins[part_id][0]:.6g},"
                    f"{placed.origins[part_id][1]:.6g}"
                    for part_id in sorted(placed.origins)
                )
                out.append(f"{name} {variant.label}: {origins}")
        return out
    finally:
        dc._relation_failures = saved


def _digest(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "--list":
        sys.stdout.write("\n".join(_measure()) + "\n")
        return 0
    if which in ("before", "after"):
        # Child rung: this process *is* one of the two versions.
        if which == "before":
            dc._order_wanted = _order_wanted_116
        lines = _measure()
        sys.stdout.write(json.dumps(
            {"lines": lines, "digest": _digest(lines)}))
        return 0

    # Parent: two real subprocesses, one per table. See the module docstring
    # for why this is not done in-process.
    import subprocess

    out = {}
    for rung in ("before", "after"):
        result = subprocess.run(
            [sys.executable, __file__, rung],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ROOT),
        )
        if result.returncode != 0:
            sys.stderr.write(f"{rung}: {result.stdout}{result.stderr}")
            return result.returncode
        out[rung] = json.loads(result.stdout)
    sys.stdout.write(json.dumps({
        "before": out["before"]["lines"],
        "after": out["after"]["lines"],
        "digest_before": out["before"]["digest"],
        "digest_after": out["after"]["digest"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
