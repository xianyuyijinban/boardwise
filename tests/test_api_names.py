"""The generated probe table must keep matching the type package.

`connector/src/api-names.ts` is what `sys.probe` `checks: true` verifies
against. It is *generated* by `tools/api_names.py`, so the failure this guards
is silent drift: bump `@jlceda/pro-api-types`, and the table still lists the
old surface while every test stays green — the probe would confidently report
a method missing that the new package declares.

The check re-runs the generator in memory and compares. It needs the type
package on disk, which is a `connector/npm install` away; when it is absent the
test skips rather than fails, because a missing devDependency is not a
regression in *this* repo's source.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "connector" / "src" / "api-names.ts"
TYPES = ROOT / "connector" / "node_modules" / "@jlceda" / "pro-api-types" / "index.d.ts"

# The namespaces the generator is invoked with (see the module docstring in the
# generated file, and `docs/draw.md`'s machine-probe list).
NAMESPACES = [
    "sch_ManufactureData",
    "dmt_EditorControl",
    "dmt_Schematic",
    "dmt_Pcb",
    "sch_Document",
    # 006b-F3 recon: the primitive namespaces that carry the *placed* pin
    # geometry (`getAllPinsByPrimitiveId`) and the real net-flag API
    # (`createNetFlag`) — the seventh path to a pin that the six-path table
    # had missed.
    "sch_PrimitiveComponent",
    "sch_PrimitivePin",
    # 025 batch 1: the DRC namespaces and where a project leaves the editor.
    # `pcb_Drc.check` is the one DRC that returns per-item errors; `sch_Drc.check`
    # returns aggregate counts only (measured 2026-09-22, 025 §0); the two
    # `sys_FileManager` reads are the zero-export paths under a permission gate;
    # `sys_Tool` is the host's own comparison lane, probed alongside them.
    "pcb_Drc",
    "sch_Drc",
    "sys_FileManager",
    "sys_Tool",
]


def _load_generator():
    """Import `tools/api_names.py` by path — `tools/` is not a package.

    The module must be registered in `sys.modules` *before* execution: it uses
    `@dataclass`, and dataclass field resolution looks the defining module up
    by name, so an unregistered module raises `AttributeError: 'NoneType'`.
    """
    name = "boardwise_test_api_names"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "api_names.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not TYPES.exists(), reason="type package not installed")
def test_generated_probe_table_matches_the_type_package():
    generator = _load_generator()
    ns_to_type, classes = generator.parse_types(TYPES)
    expected = generator.emit_typescript(ns_to_type, classes, NAMESPACES)
    actual = GENERATED.read_text(encoding="utf-8")
    assert actual == expected, (
        "connector/src/api-names.ts is stale — regenerate it:\n"
        f"    python tools/api_names.py --emit-ts connector/src/api-names.ts "
        f"{' '.join(NAMESPACES)}"
    )


@pytest.mark.skipif(not TYPES.exists(), reason="type package not installed")
def test_every_checked_name_is_really_declared():
    # The generated table is only useful if its names exist in the package: a
    # typo would turn into a permanent "missing" in every probe report.
    generator = _load_generator()
    ns_to_type, classes = generator.parse_types(TYPES)
    for namespace in NAMESPACES:
        parsed = generator.resolve(ns_to_type, classes, namespace)
        assert parsed is not None, f"{namespace} is not declared in the type package"
        text = GENERATED.read_text(encoding="utf-8")
        block = re.search(
            rf"^  {namespace}: \[(.*?)^  \],", text, re.MULTILINE | re.DOTALL
        )
        assert block, f"{namespace} has no block in the generated table"
        listed = re.findall(r"'([^']+)'", block.group(1))
        assert listed == parsed.methods, (
            f"{namespace}: generated names disagree with the package"
        )


def test_the_generator_parses_the_bundled_surface():
    # Sanity independent of the npm install: the generator's own fixtures.
    generator = _load_generator()
    sample = ROOT / "tests" / "fixtures" / "api-names-sample.d.ts"
    if not sample.exists():
        pytest.skip("sample fixture not present")
    ns_to_type, classes = generator.parse_types(sample)
    parsed = generator.resolve(ns_to_type, classes, "sch_Thing")
    assert parsed is not None
    assert parsed.methods == ["doIt", "getIt"]


def test_the_generator_ignores_prose_braces():
    # The bug that made this tool report 544 members on one class: a
    # `{@link https://…}` inside a doc comment left an orphan `{` after
    # comment-stripping, inflating the running depth forever.
    generator = _load_generator()
    assert generator._brace_delta(" * see {@link https://example.com/a}") == 0
    assert generator._brace_delta("class X {") == 1
    assert generator._brace_delta("}") == -1
    assert generator._brace_delta("  f(): Promise<{ a: string }>;") == 0
