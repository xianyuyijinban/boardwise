"""Regenerate the public/synthetic 540C differential inputs, golden and manifest.

Run from the repository root: `.venv/Scripts/python.exe -m tools.build_differential_fixtures`.

Every artifact is rendered in memory first — sanitized, checked for machine paths,
projected and hashed — and only then written, each with ``\\n`` line endings. A
projection, schema or sanitization failure therefore publishes nothing at all. The
publish step itself is a loop of single-file writes, deliberately *not* described as
a filesystem-wide transaction: a failure inside that loop can still leave the files
it already wrote, but no compute failure can reach it.

Each run produces into a **fresh** directory under :data:`WORK`. That is not
housekeeping: `checkup --out` reads ``<out>/design-intent.md`` back as the intent
records and only creates that file when it is missing, so a second run over the same
output directory would fold the first run's own TODO template into the report — the
second regeneration of the same sources produced a different ``review-report.json``
until this was fixed. The run directory name is sanitized to ``<OUT>`` below, so the
published bytes do not depend on it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from tools.contract_validate import assert_valid, load_path
from tools.differential import SCHEMAS, project_payload
from tools.differential_compare import write_text_lf

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".tmp_540" / "differential_build"
INPUTS = ROOT / "contracts" / "differential" / "inputs"
CASES = ROOT / "contracts" / "differential" / "cases.json"
MANIFEST = ROOT / "contracts" / "differential" / "manifest.json"
FIXTURES = ROOT / "tests" / "fixtures"
DRAW = FIXTURES / "drawapply"
#: Public/synthetic specs that only the page case reads (not fixture-draw inputs).
SOURCES = ROOT / "contracts" / "differential" / "sources"

#: The per-run output directory, set by :func:`_produce` and mapped to ``<OUT>``.
RUN_ROOT: Path | None = None

INPUTS_RELATIVE = "contracts/differential/inputs"
CASES_RELATIVE = "contracts/differential/cases.json"
# One public name per case kind; `_render` publishes in the order `_produce` returns.
INPUT_NAMES = {
    "review-report-projection": "review-report.json",
    "layout-plan-geometry": "divider-cand1.layout.json",
    "compile-result-projection": "divider-compile-result.json",
    "compile-page-result-projection": "page-compile-result.json",
    "lint-result-projection": "empty-page-lint-result.json",
}

# An absolute path that survived sanitization, whatever machine it came from: a
# Windows drive (D:/..., E:\... as it appears inside JSON) or a POSIX home/temp
# root. The markers in `_forbidden_markers` know this checkout and this user; this
# pattern is the machine-independent net under them.
RESIDUAL_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|/(?:home|Users|root|mnt|Volumes|private|var/folders)/)"
)


def _run(argv: list[str], accepted: set[int]) -> None:
    result = subprocess.run(argv, cwd=ROOT)
    if result.returncode not in accepted:
        raise RuntimeError(f"producer exited {result.returncode}, expected {sorted(accepted)}: {argv}")


def _produce() -> dict[str, Path]:
    global RUN_ROOT
    WORK.mkdir(parents=True, exist_ok=True)
    # A fresh directory per run: `checkup --out` reads `<out>/design-intent.md` back
    # as intent records, so two runs sharing one output directory disagree.
    RUN_ROOT = Path(tempfile.mkdtemp(prefix="run-", dir=WORK))
    python = str(ROOT / ".venv" / "Scripts" / "python.exe")
    _run([
        python, "-m", "boardwise.cli", "checkup", "--file",
        "tests/fixtures/ch340_golden.epro2", "--out", str(RUN_ROOT / "checkup"),
    ], {0, 3})
    _run([
        python, "-m", "boardwise.cli", "draw", "compile",
        "--circuit", "tests/fixtures/drawapply/divider.circuit.json",
        "--presentation", "tests/fixtures/drawapply/divider.presentation.json",
        "--profiles", "tests/fixtures/drawapply/library.json",
        "--page-box", "0,-1000,1200,0",
        "--out", str(RUN_ROOT / "compile"),
        "--json", str(RUN_ROOT / "compile-result.json"),
    ], {0})
    # The fifth case is the *page* document: a presentation with several islands
    # plus a sheet box makes `draw compile` draw a page, and that result states
    # `pages` instead of `candidates` — the shape the module contract refuses.
    page_circuit = (SOURCES / "page.circuit.json").relative_to(ROOT).as_posix()
    page_presentation = (SOURCES / "page.presentation.json").relative_to(ROOT).as_posix()
    _run([
        python, "-m", "boardwise.cli", "draw", "compile",
        "--circuit", page_circuit,
        "--presentation", page_presentation,
        "--profiles", "tests/fixtures/drawapply/library.json",
        "--page-box", "0,0,1169,826",
        "--out", str(RUN_ROOT / "compile-page"),
        "--json", str(RUN_ROOT / "page-compile-result.json"),
    ], {0})
    snapshot = {
        "components": [{
            "primitiveId": "sheet1",
            "state": {
                "PrimitiveType": "Component",
                "ComponentType": "sheet",
                "PrimitiveId": "sheet1",
            },
        }],
        "wires": [],
        "pins": [],
        "netlabels": [],
        "bboxes": {"sheet1": {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}},
        "meta": {"sheets": ["sheet1"]},
    }
    write_text_lf(
        RUN_ROOT / "lint-snapshot.json",
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
    )
    write_text_lf(RUN_ROOT / "lint-render.svg", "<svg></svg>\n")
    _run([
        python, "-m", "boardwise.cli", "draw", "lint",
        "--snapshot", str(RUN_ROOT / "lint-snapshot.json"),
        "--render", str(RUN_ROOT / "lint-render.svg"),
        "--json", str(RUN_ROOT / "lint-result.json"),
    ], {0})
    return {
        "review-report-projection": RUN_ROOT / "checkup" / "report.json",
        "layout-plan-geometry": RUN_ROOT / "compile" / "cand1.layout.json",
        "compile-result-projection": RUN_ROOT / "compile-result.json",
        "compile-page-result-projection": RUN_ROOT / "page-compile-result.json",
        "lint-result-projection": RUN_ROOT / "lint-result.json",
    }


def _clean_text(value: str) -> str:
    text = value.replace("\\", "/")
    home = str(Path.home()).replace("\\", "/")
    work = str(WORK).replace("\\", "/")
    replacements = []
    if RUN_ROOT is not None:
        # Before WORK: the run directory lives under it, so replacing WORK first
        # would leave the per-run name in the golden.
        replacements.append((str(RUN_ROOT).replace("\\", "/"), "<OUT>"))
    replacements += [
        (work, "<OUT>"),
        ("tests/fixtures/", "<FIXTURES>/"),
        (home + "/.boardwise/", "<HOME>/"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _sanitize(value: Any, key: str = "") -> Any:
    if key == "generatedAt":
        return "<GENERATED_AT>"
    if isinstance(value, dict):
        return {name: _sanitize(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _clean_text(value)
    return value


def _dump(value: Any) -> str:
    """The exact text every contract artifact is written as (LF line endings)."""
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _sha_text(text: str) -> str:
    """The hash of the bytes `write_text_lf` will write for this text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _forbidden_markers(root: Path | None = None, home: Path | None = None) -> list[str]:
    """Machine paths that must never reach a public golden, derived at run time.

    Derived from this checkout and this user rather than written out as literals:
    a repository under `D:/work/...` and a home at `/home/...` have to be caught by
    the same code that guards `E:/boardwise` and `C:/Users/...`.
    """
    root = ROOT if root is None else root
    home = Path.home() if home is None else home
    markers = {
        ".tmp_540",
        str(root),
        str(root).replace("\\", "/"),
        str(home),
        str(home).replace("\\", "/"),
    }
    return sorted(marker for marker in markers if len(marker) > 3)


def _assert_clean(
    where: str, text: str, markers: Sequence[str] | None = None
) -> None:
    """Refuse a serialized artifact that still names a machine path."""
    for marker in _forbidden_markers() if markers is None else markers:
        if marker in text:
            raise RuntimeError(
                f"{where}: unsanitized machine path {marker!r} survived — golden "
                "artifacts must not name the machine that generated them"
            )
    leak = RESIDUAL_ABSOLUTE_PATH.search(text)
    if leak:
        raise RuntimeError(
            f"{where}: residual absolute path {leak.group(0)!r} survived sanitization"
        )


def _render(produced: Mapping[str, Path]) -> dict[Path, str]:
    """Render every artifact in memory; write nothing and touch no final file."""
    input_texts: dict[Path, str] = {}
    input_hashes: dict[str, str] = {}
    case_rows: list[dict[str, Any]] = []
    producer_versions: dict[str, Any] | None = None
    schema_hashes: dict[str, str] = {}
    for kind, source in produced.items():
        # Strict loader: a producer that emitted NaN/Infinity/1e999 has produced a
        # file the Rust side cannot even read, so it must never reach the golden.
        raw = load_path(source)
        payload = _sanitize(raw)
        text = _dump(payload)
        _assert_clean(kind, text)
        # The schema the Python runner gates this very input with (`SCHEMAS` lives
        # in tools.differential, the module that reads the case book), read through
        # the same strict loader and enforced *before* anything is projected or
        # published. Dropping this check was a real regression: projection alone
        # happily emitted a golden from a contract-invalid file.
        schema_path = ROOT / "contracts" / "json" / SCHEMAS[kind]
        assert_valid(payload, load_path(schema_path))
        schema_hashes[schema_path.relative_to(ROOT).as_posix()] = _sha(schema_path)
        name = INPUT_NAMES[kind]
        # Projected from the sanitized payload itself, not from a file on disk: the
        # expected value can only describe the object about to be published.
        expected = project_payload(kind, payload)
        relative = f"{INPUTS_RELATIVE}/{name}"
        input_texts[INPUTS / name] = text
        input_hashes[relative] = _sha_text(text)
        case_rows.append({
            "id": kind,
            "kind": kind,
            "input": relative,
            "expected": expected,
        })
        if kind == "review-report-projection":
            # Provenance copied from the report this run actually publishes — never
            # re-derived, so the manifest cannot claim a rule set the golden is not
            # showing.
            versions = payload.get("completion", {}).get("sourceVersions")
            if not isinstance(versions, dict) or not versions:
                raise RuntimeError(
                    "the review report carries no completion.sourceVersions; "
                    "producerVersions would be a guess"
                )
            producer_versions = dict(versions)
    if producer_versions is None:
        raise RuntimeError(
            "no review-report case was produced; producerVersions cannot be recorded"
        )
    book = {
        "schema": "boardwise.differential-cases/1",
        "normalization": {
            "keyOrder": "lexicographic in report comparisons; input object order is preserved where the contract requires it",
            "paths": "previews are compared by basename; timestamps and machine paths are sanitized",
            "numbers": "JSON numbers are preserved; LayoutPlan geometry uses canonical compact JSON sorted by key",
        },
        "cases": case_rows,
    }
    book_text = _dump(book)
    _assert_clean("cases", book_text)
    sources = [
        FIXTURES / "ch340_golden.epro2",
        DRAW / "divider.circuit.json",
        DRAW / "divider.presentation.json",
        DRAW / "library.json",
        SOURCES / "page.circuit.json",
        SOURCES / "page.presentation.json",
    ]
    manifest = {
        "schema": "boardwise.differential-manifest/1",
        "sources": {
            path.relative_to(ROOT).as_posix(): _sha(path) for path in sources
        },
        # The rule-set/rule-body digests the published review report states, copied
        # from its `completion.sourceVersions` (see `_render`).
        "producerVersions": producer_versions,
        # The four schemas this case book's inputs are validated against, hashed.
        "schemas": schema_hashes,
        "producers": [
            "python -m boardwise.cli checkup --file tests/fixtures/ch340_golden.epro2 --out <OUT>/checkup (accept 0 or 3)",
            "python -m boardwise.cli draw compile --circuit <FIXTURES>/divider.circuit.json --presentation <FIXTURES>/divider.presentation.json --profiles <FIXTURES>/library.json --page-box 0,-1000,1200,0 --out <OUT>/compile --json <OUT>/compile-result.json",
            "python -m boardwise.cli draw compile --circuit contracts/differential/sources/page.circuit.json --presentation contracts/differential/sources/page.presentation.json --profiles <FIXTURES>/library.json --page-box 0,0,1169,826 --out <OUT>/compile-page --json <OUT>/page-compile-result.json",
            "python -m boardwise.cli draw lint --snapshot <OUT>/lint-snapshot.json --render <OUT>/lint-render.svg --json <OUT>/lint-result.json",
        ],
        "regenerate": ".venv/Scripts/python.exe -m tools.build_differential_fixtures",
        "sanitization": [
            "generatedAt -> <GENERATED_AT>",
            "repository work paths -> <OUT>",
            "tests/fixtures paths -> <FIXTURES>",
            "user .boardwise paths -> <HOME>",
            "backslashes in strings -> forward slashes",
            "no real project container is read or copied; inputs come only from the public/synthetic sources above",
        ],
        "inputs": input_hashes,
        # The repo-relative name of the case book, not `CASES` computed against
        # whatever working directory this run happens to use.
        "caseBook": {"path": CASES_RELATIVE, "sha256": _sha_text(book_text)},
    }
    manifest_text = _dump(manifest)
    _assert_clean("manifest", manifest_text)
    return {**input_texts, CASES: book_text, MANIFEST: manifest_text}


def _publish(rendered: Mapping[Path, str]) -> None:
    """Write finished artifacts with LF endings.

    Nothing here can fail on projection, schema, sanitization or hashing — all of
    that ran in `_render`. This is still a loop of single-file writes: it is
    all-or-nothing with respect to *compute* failures, not a filesystem-wide
    transaction, and a failure inside the loop can leave the files it wrote.
    """
    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, text)


def _regenerate(produced: Mapping[str, Path]) -> None:
    """Render everything, then publish; no final file is written before render returns."""
    _publish(_render(produced))


def main() -> int:
    _regenerate(_produce())
    print(f"wrote {len(INPUT_NAMES)} differential cases: {CASES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
