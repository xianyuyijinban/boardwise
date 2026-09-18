"""Coordinate-space guards (006c, work item 3).

Two rules about *which spatial vocabulary a module may speak*:

* `engines/**` works in canvas coordinates. A mil→mm conversion showing up
  there means the conversion escaped its boundary and is now happening in two
  places.
* `parsers/**` works in file coordinates (`.epru` records as recorded). Naming
  something `canvas*` in a parser means file and canvas have been conflated —
  the exact confusion that produced two off-by-sign bugs (see
  `docs/architecture.md`, "Three coordinate spaces").

Why a source scan rather than a behavioural test: the defect is a *word*
appearing in the wrong module, and the two spaces are numerically identical
for many inputs (a y-down canvas and a mirrored y-up file agree at y=0), so a
test that compares numbers can pass while the units are wrong.

Scope, stated honestly:

* Only **identifiers and numeric literals** are inspected, via `tokenize`.
  Comments and docstrings are prose: `parsers/schematic.py` must be free to
  *document* the file→canvas conversion it performs at its boundary, and
  `epru.py` legitimately lists `"CANVAS"` as an `.epru` **record type** — that
  word is format vocabulary, not a coordinate claim.
* These are tripwires for the named shapes, not a proof of unit-correctness.
  They catch a conversion in the wrong module; they cannot catch a conversion
  that is arithmetically wrong in the right one.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "boardwise"
ENGINES = PACKAGE / "engines"
PARSERS = PACKAGE / "parsers"

#: `25.4` mm per inch and `39.37` inches per metre — the two factors that
#: appear whenever someone converts mil ↔ mm by hand.
FORBIDDEN_ENGINE_NUMBERS = {"25.4", "39.37", "0.0254", "0.03937"}
FORBIDDEN_ENGINE_NAMES = re.compile(r"mil_to_mm|mm_to_mil|mil2mm|mm2mil")
FORBIDDEN_PARSER_NAMES = re.compile(r"canvas", re.IGNORECASE)


def _python_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _tokens(path: Path):
    source = path.read_text(encoding="utf-8")
    return list(tokenize.generate_tokens(io.StringIO(source).readline))


def _code_tokens(path: Path):
    """Tokens that carry a claim about units: names, numbers, operators.

    Comments and strings are dropped on purpose; see the module docstring.
    """
    for token in _tokens(path):
        if token.type in (tokenize.NAME, tokenize.NUMBER):
            yield token


def test_the_scan_is_looking_at_real_files():
    # A guard over an empty directory passes forever.
    engines = _python_files(ENGINES)
    parsers = _python_files(PARSERS)
    assert len(engines) >= 5, f"only found {len(engines)} engine modules"
    assert len(parsers) >= 3, f"only found {len(parsers)} parser modules"
    assert any(path.name == "draw.py" for path in engines)
    assert any(path.name == "schematic.py" for path in parsers)


def test_engines_never_convert_between_mil_and_mm():
    offenders = []
    for path in _python_files(ENGINES):
        for token in _code_tokens(path):
            if token.type == tokenize.NAME and FORBIDDEN_ENGINE_NAMES.search(token.string):
                offenders.append(f"{path.name}:{token.start[0]} uses {token.string!r}")
            elif token.type == tokenize.NUMBER and token.string in FORBIDDEN_ENGINE_NUMBERS:
                offenders.append(
                    f"{path.name}:{token.start[0]} carries the conversion factor {token.string}"
                )
    assert offenders == [], (
        "engines work in canvas coordinates only; a mil↔mm conversion here means "
        "the conversion left its boundary (parsers + canvas_pin_offsets):\n  "
        + "\n  ".join(offenders)
    )


def test_parsers_never_name_anything_canvas():
    offenders = []
    for path in _python_files(PARSERS):
        for token in _code_tokens(path):
            if token.type == tokenize.NAME and FORBIDDEN_PARSER_NAMES.search(token.string):
                offenders.append(f"{path.name}:{token.start[0]} defines {token.string!r}")
    assert offenders == [], (
        "parsers speak file coordinates only; canvas-named identifiers here mean "
        "file and canvas were conflated:\n  " + "\n  ".join(offenders)
    )


def _docstring_lines(path: Path) -> set[int]:
    """Line numbers of module/class/function docstrings — prose, not data."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            lines.add(body[0].value.lineno)
    return lines


def test_canvas_in_a_parser_string_is_only_file_format_vocabulary():
    """The word is allowed in strings — but only as a *format* token.

    `epru.py` lists `"CANVAS"` among the `.epru` record types, and the parsers
    must stay free to *document* the file→canvas conversion they perform at
    their own boundary. What this notices is a parser emitting canvas-flavoured
    **keys**, which is how the vocabulary would actually reach a caller.
    """
    allowed = {"CANVAS"}  # an .epru record type, nothing to do with coordinates
    found = set()
    for path in _python_files(PARSERS):
        docstrings = _docstring_lines(path)
        for token in _tokens(path):
            if token.type != tokenize.STRING or token.start[0] in docstrings:
                continue
            if "canvas" in token.string.lower():
                found.add(ast.literal_eval(token.string))
    unexpected = {value for value in found if value not in allowed}
    assert unexpected == set(), (
        f"unexpected canvas-flavoured string literals in parsers: {sorted(unexpected)}"
    )


def test_the_guards_fire_on_the_shapes_they_exist_for():
    # Positive control: if these patterns stop matching, the guards are dead
    # weight and must be fixed rather than weakened.
    assert FORBIDDEN_ENGINE_NAMES.search("mm = mil_to_mm(value)")
    assert FORBIDDEN_ENGINE_NAMES.search("return mm2mil(x)")
    assert "25.4" in FORBIDDEN_ENGINE_NUMBERS
    assert FORBIDDEN_PARSER_NAMES.search("canvas_x")
    assert FORBIDDEN_PARSER_NAMES.search("to_canvas(")

    # Sanity: the allowed spellings must keep passing.
    assert FORBIDDEN_ENGINE_NAMES.search("mil_per_unit") is None
    assert FORBIDDEN_PARSER_NAMES.search("file_y") is None
    assert FORBIDDEN_PARSER_NAMES.search("sheet_origin") is None


@pytest.mark.parametrize("name", ["draw.py", "replay.py", "generate.py"])
def test_the_only_legal_conversion_entry_points_are_named(name):
    """The seam is a *named* thing, not a habit.

    `canvas_pin_offsets` (in `engines/generate.py`) is the sanctioned file→canvas
    entry point for pin geometry; `replay.py` owns the wire/page conversion. If
    either disappears the boundary documented in `docs/architecture.md` no
    longer describes the code.
    """
    source = (ENGINES / name).read_text(encoding="utf-8")
    if name == "generate.py":
        assert "canvas_pin_offsets" in source, (
            "generate.py no longer defines canvas_pin_offsets — the documented "
            "conversion entry point is gone"
        )
