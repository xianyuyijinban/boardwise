"""537D1a2b: ``boardwise review-read --section artifacts`` — cited files, verified.

Why this section exists. 537D1a answered 「报告怎么说」; the next question every
review asks is 「它引用的文件真的在吗、还是它说的那份」. Before this section that
was a hand-written loop over ``report.json`` — and the loop read an unreferenced
file in the directory as evidence (the netlist 537C3b3 measured), or a missing
PNG as 「图已落盘」 because the key existed.

This file pins the two halves apart:

* the **projection** (:mod:`boardwise.engines.reviewread`) collects *only* the
  files the report's machine fields cite, in one frozen order — the canvas
  images, each channel's ``artifacts`` in ``CHANNEL_ORDER``, the live capture's
  own ``artifacts`` and ``captureFile``, then the five standard outputs. Nothing
  is read from prose or guessed from a file name; a ``netlist_raw.json`` no row
  cites is not evidence. Rows are ``{source, channel, artifact}``, deep-copied,
  duplicates inside one source de-duplicated while a *different* source citing
  the same file stays a separate claim. The engine touches no disk, so
  ``missingOutputs`` is ``None`` there, not ``[]``;
* the **CLI** fills in the file facts for every row: ``path``, ``exists``,
  ``bytesOnDisk``, ``bytesMatch``, ``sha256Matches``, ``error``. A relative path
  is joined to ``--out``; an absolute outside path or a ``..`` escape is
  ``outside-review-directory`` *before* it is resolved, stat-ed or opened, and
  the tests prove that with a guard that fails the moment an outside path is
  touched. A missing cited file is ``missing``, a directory is ``not-file``, a
  declared ``bytes``/``sha256`` that does not hold is an error, and a citation
  with **no** declaration leaves both flags ``null`` — 「没有声明」 is not
  「验证通过」. Files are hashed in bounded chunks (a whole-file read is refused
  by the test), and nothing is written.

The final ``status`` is this section's own answer: ``unavailable`` when any row
has an error, ``missing`` when no file at all exists, ``ok`` otherwise. The five
standard outputs are the only absence that does *not* make it ``unavailable``:
they are routed to ``missingOutputs``, so a pre-537C report with no
``live-evidence.json`` can still be ``ok``.

Everything here is anonymous and synthetic — no editor, daemon, project, real
report, netlist or image.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.evidence import CHANNEL_ORDER
from boardwise.engines.reviewread import (
    REVIEW_OUTPUT_ARTIFACTS,
    REVIEW_OUTPUT_SOURCE,
    REVIEW_READ_SCHEMA,
    REVIEW_READ_SECTIONS,
    review_read_section,
)

PROJECT = "proj-537d1a2b-synthetic"

CANVAS_NAME = "canvas-SYNTH-B1.svg"
CANVAS_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><title>SYNTH</title></svg>\n'

SCH_IMAGE_NAME = "live-sch-SYNTH-1.png"
SCH_IMAGE = b"\x89PNG\r\n\x1a\n" + b"synthetic schematic image bytes"

PCB_IMAGE_NAME = "live-pcb-SYNTH-2.png"
PCB_IMAGE = b"\x89PNG\r\n\x1a\n" + b"synthetic pcb image bytes"

NETLIST_NAME = "live-netlist-SYNTH-1.txt"
NETLIST_TEXT = b'{"components": {"g-u1": {"props": {"Designator": "U1"}}}}\n'

REPORT_MD_SENTINEL = b"# synthetic report.md - review-read must not rewrite this\n"
BOARD_MD_SENTINEL = b"# synthetic board-report.md - read only\n"
SUMMARY_SENTINEL = (
    b"# synthetic review-summary\n\n| spot | verdict | evidence |\n"
    b"| --- | --- | --- |\n| PWR/TP1 | hand-written, must survive | eyes |\n"
)
LIVE_EVIDENCE_BYTES = b'{"schema": "boardwise.live-evidence/1", "sentinel": true}\n'

PROTECTED = (
    "report.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "live-evidence.json",
)

#: The files the synthetic report cites, written beside it by :func:`write_out`.
DEFAULT_FILES = {
    CANVAS_NAME: CANVAS_SVG,
    SCH_IMAGE_NAME: SCH_IMAGE,
    PCB_IMAGE_NAME: PCB_IMAGE,
    NETLIST_NAME: NETLIST_TEXT,
}

ROW_KEYS = [
    "source",
    "channel",
    "artifact",
    "path",
    "exists",
    "bytesOnDisk",
    "bytesMatch",
    "sha256Matches",
    "error",
]


# ---------------------------------------------------------------------------
# synthetic report + directory
# ---------------------------------------------------------------------------


def declared(name: str, data: bytes, **overrides) -> dict:
    """One artifact row shaped like the collector writes it."""
    row = {
        "file": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    row.update(overrides)
    return row


def channel_row(artifacts: list[dict] | None = None, *, status: str = "ok") -> dict:
    return {
        "status": status,
        "source": "synthetic",
        "detail": "",
        "artifacts": list(artifacts or []),
        "errors": [],
        "steps": [],
    }


def synthetic_report(
    *,
    with_capture: bool = True,
    with_canvas: bool = True,
    with_channels: bool = True,
) -> dict:
    """A report whose machine fields cite real (synthetic) files, in order."""
    channels = {name: channel_row([], status="missing") for name in CHANNEL_ORDER}
    if with_channels:
        channels["liveSchematic"] = channel_row(
            [declared(NETLIST_NAME, NETLIST_TEXT, kind="netlist", page="SYNTH/1")]
        )
        channels["schematicImage"] = channel_row(
            [declared(SCH_IMAGE_NAME, SCH_IMAGE, kind="image", page="SYNTH/1")]
        )
    report: dict = {
        "schema": "boardwise.checkup/7",
        "source": {"project": {"projectUuid": PROJECT, "name": "SYNTH"}},
        "conclusion": {"verdict": "incomplete", "mayClaimPassed": False},
        "findings": [],
        "warning_triage": [],
        "evidence": {
            "schema": "boardwise.review-evidence/1",
            "channels": channels,
            "delivery": {"status": "partial"},
        },
    }
    if with_canvas:
        report["ai_slots"] = {
            "canvas_images": [
                {
                    "board": "SYNTH-B1",
                    "source": "geometry-render",
                    "file": CANVAS_NAME,
                    "bytes": len(CANVAS_SVG),
                    "findings": 0,
                }
            ]
        }
    if with_capture:
        report["evidence"]["liveCapture"] = {
            "schema": "boardwise.live-evidence/1",
            "ok": True,
            "identity": {
                "expectedProjectUuid": PROJECT,
                "verifiedAgainstReport": True,
                "ok": True,
            },
            "artifacts": [
                declared(
                    NETLIST_NAME, NETLIST_TEXT, kind="netlist",
                    channel="liveSchematic",
                ),
                declared(
                    PCB_IMAGE_NAME, PCB_IMAGE, kind="image", channel="pcbImage",
                ),
            ],
            "captureFile": declared("live-evidence.json", LIVE_EVIDENCE_BYTES),
            "focusRestore": {"status": "restored", "originalUuid": "page-1"},
        }
    return report


def write_out(
    tmp_path: Path,
    report: dict | None = None,
    *,
    extra: dict[str, bytes] | None = None,
    outputs: tuple[str, ...] | None = None,
) -> Path:
    """A review directory: report.json, the protected products, cited files.

    ``outputs`` names which of the five standard outputs are written; leaving
    one out is how the tests model a pre-537C directory **without** deleting
    anything.
    """
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    payload = synthetic_report() if report is None else report
    blob = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (out / "report.json").write_bytes(blob.encode("utf-8"))
    written = set(outputs) if outputs is not None else set(PROTECTED)
    for name, data in (
        ("report.md", REPORT_MD_SENTINEL),
        ("board-report.md", BOARD_MD_SENTINEL),
        ("review-summary.md", SUMMARY_SENTINEL),
        ("live-evidence.json", LIVE_EVIDENCE_BYTES),
    ):
        if name in written:
            (out / name).write_bytes(data)
    for name, data in {**DEFAULT_FILES, **(extra or {})}.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return out


def run_cli(*argv: str) -> int:
    return cli.main(["review-read", *argv])


def read_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    assert captured.out.endswith("\n")
    return json.loads(captured.out)


def hashes(out: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
        for name in PROTECTED
        if (out / name).exists()
    }


def rows_of(payload: dict) -> dict[tuple[str, object, object], dict]:
    """Rows keyed by (source, channel, file) — the identity the section promises."""
    return {
        (row["source"], row["channel"], row["artifact"].get("file")): row
        for row in payload["artifacts"]
    }


def artifacts_payload(report: dict, out: Path) -> dict:
    """The pure projection plus the CLI's documented verification step."""
    return cli._review_read_artifacts_payload(
        review_read_section(report, "artifacts"), out
    )


# ---------------------------------------------------------------------------
# 1) the pure projection: what the report cites, in the frozen order
# ---------------------------------------------------------------------------


def test_projection_collects_every_machine_source_in_the_frozen_order():
    report = synthetic_report()

    payload = review_read_section(report, "artifacts")

    assert payload["status"] == "ok"
    assert payload["missingOutputs"] is None, (
        "a pure projection cannot know which files are absent; [] would read as "
        "「都在」 and an absence must not become an answer"
    )
    assert [(row["source"], row["channel"]) for row in payload["artifacts"]] == [
        ("ai_slots.canvas_images", None),
        ("evidence.channels", "liveSchematic"),
        ("evidence.channels", "schematicImage"),
        ("liveCapture.artifacts", "liveSchematic"),
        ("liveCapture.artifacts", "pcbImage"),
        ("liveCapture.captureFile", None),
        *[(REVIEW_OUTPUT_SOURCE, None)] * 5,
    ]
    # The rows keep the report's own bytes/kind declarations verbatim.
    assert payload["artifacts"][0]["artifact"]["file"] == CANVAS_NAME
    assert payload["artifacts"][1]["artifact"]["kind"] == "netlist"
    assert [row["artifact"]["file"] for row in payload["artifacts"][-5:]] == list(PROTECTED)
    # Each artifact is a deep copy: a caller cannot reach back into the report.
    assert payload["artifacts"][0]["artifact"] is not report["ai_slots"]["canvas_images"][0]
    assert payload["artifacts"][0]["artifact"] == report["ai_slots"]["canvas_images"][0]


def test_projection_dedupes_one_source_and_keeps_a_second_source_citing_it():
    report = synthetic_report()
    report["ai_slots"]["canvas_images"].extend(
        [
            copy.deepcopy(report["ai_slots"]["canvas_images"][0]),
            copy.deepcopy(report["ai_slots"]["canvas_images"][0]),
        ]
    )
    # The same netlist row twice inside one channel is one file, not two.
    report["evidence"]["channels"]["liveSchematic"]["artifacts"].append(
        copy.deepcopy(report["evidence"]["channels"]["liveSchematic"]["artifacts"][0])
    )
    # And a *second* source citing a file it also cites: same file, distinct
    # evidence chains — both rows survive.
    report["evidence"]["liveCapture"]["artifacts"].append(
        declared(SCH_IMAGE_NAME, SCH_IMAGE, kind="image")
    )

    payload = review_read_section(report, "artifacts")
    rows = payload["artifacts"]

    canvas = [row for row in rows if row["source"] == "ai_slots.canvas_images"]
    channel = [row for row in rows if row["source"] == "evidence.channels"]
    capture = [row for row in rows if row["source"] == "liveCapture.artifacts"]
    assert len(canvas) == 1
    assert len(channel) == 2  # netlist + schematic image, one row each
    assert [row["artifact"]["file"] for row in capture] == [
        NETLIST_NAME,
        PCB_IMAGE_NAME,
        SCH_IMAGE_NAME,
    ]
    assert len({id(row) for row in rows}) == len(rows)


def test_archive_pcb_board_readings_are_not_file_citations(tmp_path, capsys):
    """The measured real shape: `_archive_pcb` artifacts carry no file at all."""
    report = synthetic_report()
    readings = [{"title": "SYNTH-B1", "components": 12, "copperLayers": 4}]
    report["evidence"]["channels"]["archivePcb"] = channel_row(copy.deepcopy(readings))

    payload = review_read_section(report, "artifacts")

    assert all(row["channel"] != "archivePcb" for row in payload["artifacts"])
    assert payload["status"] == "ok"
    # The reading is not lost: it stays readable in the coverage ledger.
    coverage = review_read_section(report, "coverage")
    assert coverage["evidence"]["channels"]["archivePcb"]["artifacts"] == readings

    out = write_out(tmp_path, report)
    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    assert payload["status"] == "ok", "a board reading is not a missing file"
    assert all(row["artifact"].get("title") is None for row in payload["artifacts"])


def test_real_archive_pcb_channel_shape_is_not_a_file_citation(tmp_path, capsys):
    """The builder's own row, not a hand-made fixture: no file key at all."""
    from boardwise.engines.evidence import evidence_section

    evidence = evidence_section(
        tier="project-file",
        pcb_review={
            "available": True,
            "boards": [{"title": "SYNTH-B1", "components": 12, "copperLayers": 4}],
        },
        pcb_had_documents=True,
    )
    channel = evidence["channels"]["archivePcb"]
    assert channel["status"] == "ok"
    assert channel["artifacts"] == [
        {"title": "SYNTH-B1", "components": 12, "copperLayers": 4}
    ]

    report = synthetic_report(with_capture=False)
    report["evidence"] = evidence
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    assert payload["status"] == "ok"
    assert payload["missingOutputs"] == []
    assert all(row["channel"] != "archivePcb" for row in payload["artifacts"])


def test_conflicting_citations_of_one_file_are_both_kept_and_checked(
    tmp_path, capsys
):
    """Same file + different sha256 is a contradiction, not a duplicate."""
    report = synthetic_report()
    good = declared(SCH_IMAGE_NAME, SCH_IMAGE, kind="image")
    stale = dict(good, sha256="0" * 64)
    report["evidence"]["channels"]["schematicImage"]["artifacts"] = [
        good,
        copy.deepcopy(stale),
    ]

    payload = review_read_section(report, "artifacts")
    rows = [row for row in payload["artifacts"] if row["channel"] == "schematicImage"]
    assert len(rows) == 2
    assert {row["artifact"]["sha256"] for row in rows} == {
        hashlib.sha256(SCH_IMAGE).hexdigest(),
        "0" * 64,
    }

    out = write_out(tmp_path, report)
    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    rows = [row for row in payload["artifacts"] if row["channel"] == "schematicImage"]
    assert len(rows) == 2
    assert {row["sha256Matches"] for row in rows} == {True, False}
    assert payload["status"] == "unavailable", "the conflict must not be swallowed"


def test_resolve_failure_fails_closed_and_never_touches_the_target(
    tmp_path, capsys, monkeypatch
):
    """No proof of containment → no stat, no open, no `ok`."""
    target = SCH_IMAGE_NAME
    out = write_out(tmp_path)
    target_key = os.path.normcase(str((out / target).resolve()))

    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):
        if os.path.normcase(str(self)) == target_key:
            raise OSError("synthetic: containment cannot be proven")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    touched: list[str] = []

    for name in ("stat", "open", "read_bytes"):
        real = getattr(Path, name)

        def spy(self, *args, __real=real, __name=name, **kwargs):
            if os.path.normcase(str(self)) == target_key:
                touched.append(__name)
            return __real(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, spy)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    row = rows_of(payload)[("evidence.channels", "schematicImage", target)]
    assert row["error"] == "outside-review-directory"
    assert row["exists"] is None
    assert row["bytesOnDisk"] is None
    assert row["bytesMatch"] is None
    assert row["sha256Matches"] is None
    assert touched == [], "unproven containment must not be stat-ed or opened"
    assert payload["status"] == "unavailable"


def test_projection_old_report_lists_only_the_standard_outputs(tmp_path):
    report = synthetic_report(
        with_capture=False, with_canvas=False, with_channels=False
    )
    write_out(tmp_path, report, extra={"netlist_raw.json": NETLIST_TEXT})

    payload = review_read_section(report, "artifacts")

    assert payload["status"] == "missing", "the report cites no evidence file"
    assert [(row["source"], row["artifact"]["file"]) for row in payload["artifacts"]] == [
        (REVIEW_OUTPUT_SOURCE, name) for name in PROTECTED
    ]
    # The directory is irrelevant to a projection: no path is stat-ed here and
    # no file that happens to sit beside the report becomes evidence.
    assert all(row["artifact"].get("file") != "netlist_raw.json" for row in payload["artifacts"])
    assert set(row["artifact"].get("file") for row in payload["artifacts"]) == set(PROTECTED)


def test_projection_never_mutates_or_aliases_the_report():
    report = synthetic_report()
    before = copy.deepcopy(report)

    payload = review_read_section(report, "artifacts")
    payload["artifacts"][0]["artifact"]["file"] = "tampered.png"
    payload["artifacts"].append({"injected": True})
    payload["missingOutputs"] = []

    assert report == before


def test_projection_touches_no_filesystem(monkeypatch):
    def refuse(*args, **kwargs):  # pragma: no cover - only on the wrong path
        raise AssertionError("the artifacts projection must not touch the disk")

    for name in ("stat", "open", "read_bytes", "read_text", "resolve"):
        monkeypatch.setattr(Path, name, refuse)

    payload = review_read_section(synthetic_report(), "artifacts")

    assert payload["status"] == "ok"
    assert payload["missingOutputs"] is None


def test_artifacts_is_registered_between_coverage_and_netlist():
    assert "artifacts" in REVIEW_READ_SECTIONS
    assert REVIEW_READ_SECTIONS.index("artifacts") == REVIEW_READ_SECTIONS.index("coverage") + 1
    assert REVIEW_READ_SECTIONS[-1] == "netlist"


def test_review_output_rows_are_the_protected_inputs():
    names = tuple(name for name, _kind in REVIEW_OUTPUT_ARTIFACTS)
    assert names == cli.REVIEW_READ_PROTECTED_FILES
    assert len({kind for _name, kind in REVIEW_OUTPUT_ARTIFACTS}) == 5


def test_the_row_error_vocabulary_is_frozen():
    assert cli.REVIEW_READ_ARTIFACT_ERRORS == (
        "missing-file",
        "missing",
        "not-file",
        "unreadable",
        "outside-review-directory",
        "bytes-mismatch",
        "sha256-mismatch",
    )


# ---------------------------------------------------------------------------
# 2) the CLI's file facts
# ---------------------------------------------------------------------------


def test_cli_verifies_relative_and_absolute_inside_paths(tmp_path, capsys):
    out = tmp_path / "out"
    report = synthetic_report()
    report["ai_slots"]["canvas_images"][0]["file"] = str(out / CANVAS_NAME)
    write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    assert payload["status"] == "ok"
    assert payload["missingOutputs"] == []
    canvas = payload["artifacts"][0]
    assert canvas["source"] == "ai_slots.canvas_images"
    assert canvas["path"] == str((out / CANVAS_NAME).resolve())
    assert canvas["exists"] is True
    assert canvas["bytesOnDisk"] == len(CANVAS_SVG)
    assert canvas["bytesMatch"] is True
    assert canvas["sha256Matches"] is None, "no sha256 declared: null, never a pass"
    assert canvas["error"] is None

    netlist = next(
        row for row in payload["artifacts"]
        if row["source"] == "evidence.channels"
        and row["artifact"].get("file") == NETLIST_NAME
    )
    assert netlist["path"] == str((out / NETLIST_NAME).resolve())
    assert netlist["bytesMatch"] is True
    assert netlist["sha256Matches"] is True
    assert netlist["error"] is None
    assert all(list(row) == ROW_KEYS for row in payload["artifacts"]), (
        "every row carries the same nine fields, in the same order"
    )


def install_outside_guard(monkeypatch, out: Path) -> None:
    """Fail any read of a path outside ``out`` — the refusal must not read it."""
    root = os.path.normcase(str(out.resolve()))

    def outside(path: Path) -> bool:
        key = os.path.normcase(str(path))
        return not (key == root or key.startswith(root + os.sep))

    for name in ("resolve", "stat", "open", "read_bytes"):
        real = getattr(Path, name)

        def guard(self, *args, __real=real, __name=name, **kwargs):
            if outside(self):
                raise AssertionError(
                    f"a refused artifact was touched with Path.{__name}: {self}"
                )
            return __real(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, guard)


def test_cli_refuses_an_absolute_outside_path_before_reading(tmp_path, capsys, monkeypatch):
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"synthetic": "outside"}\n')
    before = outside.read_bytes()

    report = synthetic_report()
    report["evidence"]["channels"]["schematicImage"]["artifacts"].append(
        declared(str(outside), outside.read_bytes(), kind="image")
    )
    out = write_out(tmp_path, report)
    install_outside_guard(monkeypatch, out)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    row = next(
        row for row in payload["artifacts"]
        if row["artifact"].get("file") == str(outside)
    )
    assert row["error"] == "outside-review-directory"
    assert row["exists"] is None
    assert row["bytesOnDisk"] is None
    assert row["bytesMatch"] is None
    assert row["sha256Matches"] is None
    assert payload["status"] == "unavailable"
    # builtins.open is not patched by the guard: the sentinel is read here to
    # prove the refused citation never was.
    with open(outside, "rb") as handle:
        assert handle.read() == before, "a refusal must not be a read"
    assert row["path"] == str(outside), "the refusal names the lexical path"


def test_cli_refuses_a_dotdot_escape_before_reading(tmp_path, capsys, monkeypatch):
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside, not evidence")
    outside_path = str(outside)
    out = write_out(tmp_path)
    install_outside_guard(monkeypatch, out)
    # The citation is a *relative* escape: out/../outside.png.
    report = synthetic_report()
    report["evidence"]["channels"]["schematicImage"]["artifacts"].append(
        declared("../outside.png", b"outside, not evidence", kind="image")
    )
    write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    row = next(
        row for row in payload["artifacts"]
        if row["artifact"].get("file") == "../outside.png"
    )
    assert row["error"] == "outside-review-directory"
    assert row["exists"] is None
    assert row["bytesMatch"] is None
    assert payload["status"] == "unavailable"
    assert row["path"] == outside_path, (
        "the refusal names the lexical path it refused, without resolving it"
    )


def test_cli_missing_citation_is_missing_and_never_ok(tmp_path, capsys):
    report = synthetic_report()
    report["evidence"]["channels"]["pcbImage"] = channel_row(
        [declared("pcb-image-gone.png", b"never written", kind="image")]
    )
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    row = next(
        row for row in payload["artifacts"]
        if row["artifact"].get("file") == "pcb-image-gone.png"
    )
    assert row["exists"] is False
    assert row["error"] == "missing"
    assert row["bytesOnDisk"] is None
    assert row["bytesMatch"] is None
    assert row["sha256Matches"] is None
    assert payload["status"] == "unavailable", "a cited file that cannot be produced"
    assert "pcb-image-gone.png" not in payload["missingOutputs"], (
        "missingOutputs is the five standard outputs only"
    )


def test_cli_directory_citation_is_not_a_file(tmp_path, capsys):
    out = write_out(tmp_path)
    (out / "nested").mkdir()
    report = synthetic_report()
    report["evidence"]["channels"]["pcbImage"] = channel_row(
        [declared("nested", b"", kind="image")]
    )
    write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    row = next(
        row for row in payload["artifacts"] if row["artifact"].get("file") == "nested"
    )
    assert row["exists"] is True
    assert row["error"] == "not-file"
    assert row["bytesOnDisk"] is None
    assert row["bytesMatch"] is None
    assert payload["status"] == "unavailable"


def test_cli_bytes_and_sha_mismatches_are_errors(tmp_path, capsys):
    report = synthetic_report()
    # Same file, one declared byte too many: the count is wrong, the hash is not.
    report["evidence"]["channels"]["livePcb"] = channel_row(
        [declared(SCH_IMAGE_NAME, SCH_IMAGE, kind="image", bytes=len(SCH_IMAGE) + 1)]
    )
    # Same length, different content: the hash is wrong, the count is not.
    wrong_sha = {"file": PCB_IMAGE_NAME, "bytes": len(PCB_IMAGE), "sha256": "0" * 64}
    report["evidence"]["channels"]["archivePcb"] = channel_row(
        [{**wrong_sha, "kind": "image"}]
    )
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    rows = rows_of(payload)

    bytes_row = rows[("evidence.channels", "livePcb", SCH_IMAGE_NAME)]
    assert bytes_row["bytesMatch"] is False
    assert bytes_row["sha256Matches"] is True
    assert bytes_row["error"] == "bytes-mismatch"

    sha_row = rows[("evidence.channels", "archivePcb", PCB_IMAGE_NAME)]
    assert sha_row["bytesMatch"] is True
    assert sha_row["sha256Matches"] is False
    assert sha_row["error"] == "sha256-mismatch"
    assert payload["status"] == "unavailable"


def test_cli_without_declarations_leaves_the_flags_null(tmp_path, capsys):
    report = synthetic_report()
    # The canvas row declares bytes only; this channel row declares neither.
    report["evidence"]["channels"]["pcbImage"] = channel_row(
        [{"file": PCB_IMAGE_NAME, "kind": "image"}]
    )
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    rows = rows_of(payload)

    canvas = rows[("ai_slots.canvas_images", None, CANVAS_NAME)]
    assert canvas["bytesMatch"] is True
    assert canvas["sha256Matches"] is None
    assert canvas["error"] is None

    undeclared = rows[("evidence.channels", "pcbImage", PCB_IMAGE_NAME)]
    assert undeclared["exists"] is True
    assert undeclared["bytesOnDisk"] == len(PCB_IMAGE)
    assert undeclared["bytesMatch"] is None
    assert undeclared["sha256Matches"] is None
    assert undeclared["error"] is None
    # No declaration is not a pass — and it is not an error either: the status
    # only says the files are there and nothing contradicts them.
    assert payload["status"] == "ok"


def test_cli_hashes_in_bounded_chunks_and_never_reads_the_file_whole(
    tmp_path, capsys, monkeypatch
):
    data = b"S" * (cli.REVIEW_READ_ARTIFACT_CHUNK * 2 + 3)
    report = synthetic_report()
    report["evidence"]["channels"]["pcbImage"] = channel_row(
        [declared("big.bin", data, kind="image")]
    )
    out = write_out(tmp_path, report, extra={"big.bin": data})

    def refuse_whole_file(*args, **kwargs):  # pragma: no cover - the wrong path
        raise AssertionError("the artifact hash must not read the file whole")

    monkeypatch.setattr(Path, "read_bytes", refuse_whole_file)

    sizes: list[int] = []
    real_open = Path.open

    class Spy:
        def __init__(self, handle):
            self._handle = handle

        def read(self, size=-1):
            sizes.append(size)
            return self._handle.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def spy_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        handle = real_open(self, *args, **kwargs)
        return Spy(handle) if "b" in mode else handle

    monkeypatch.setattr(Path, "open", spy_open)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    row = rows_of(payload)[("evidence.channels", "pcbImage", "big.bin")]

    assert row["sha256Matches"] is True
    assert row["bytesMatch"] is True
    assert sizes, "the hash never read the file"
    assert all(size > 0 for size in sizes), "an unbounded read(size=-1)"
    assert all(size <= cli.REVIEW_READ_ARTIFACT_CHUNK for size in sizes)
    assert len(sizes) > 1, "the file was hashed in one read"


def test_cli_capture_file_is_verified_and_a_changed_capture_fails(tmp_path, capsys):
    out = write_out(tmp_path)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    row = rows_of(payload)[("liveCapture.captureFile", None, "live-evidence.json")]
    assert row["exists"] is True
    assert row["bytesMatch"] is True
    assert row["sha256Matches"] is True
    assert row["error"] is None
    assert payload["status"] == "ok"

    # The capture is rewritten after the report fingerprinted it: the citation
    # no longer describes the bytes on disk.
    (out / "live-evidence.json").write_bytes(b'{"tampered": true}\n')

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]
    row = rows_of(payload)[("liveCapture.captureFile", None, "live-evidence.json")]
    assert row["bytesMatch"] is False
    assert row["sha256Matches"] is False
    assert row["error"] == "bytes-mismatch"
    assert payload["status"] == "unavailable"


def test_cli_absent_standard_output_is_missing_output_not_unavailable(tmp_path, capsys):
    report = synthetic_report(with_capture=False)
    out = write_out(
        tmp_path,
        report,
        outputs=("report.json", "report.md", "board-report.md", "review-summary.md"),
    )

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    assert payload["missingOutputs"] == ["live-evidence.json"]
    row = rows_of(payload)[(REVIEW_OUTPUT_SOURCE, None, "live-evidence.json")]
    assert row["exists"] is False
    assert row["error"] is None, "a standard output that was never written is not an error"
    assert payload["status"] == "ok", "an old report is still a readable report"


def test_artifacts_status_semantics(tmp_path):
    rows = [
        {"exists": False, "error": None},
        {"exists": False, "error": None},
    ]
    assert cli._review_read_artifacts_status(rows) == "missing"
    assert cli._review_read_artifacts_status(rows + [{"exists": True, "error": None}]) == "ok"
    assert (
        cli._review_read_artifacts_status(
            rows + [{"exists": True, "error": "sha256-mismatch"}]
        )
        == "unavailable"
    )
    assert cli._review_read_artifacts_status([]) == "missing"


def test_cli_never_guesses_a_file_from_the_directory(tmp_path, capsys):
    out = write_out(
        tmp_path,
        synthetic_report(
            with_capture=False, with_canvas=False, with_channels=False
        ),
        extra={
            "netlist_raw.json": NETLIST_TEXT,
            "canvas-ORPHAN.svg": b"<svg/>\n",
            "live-sch-ORPHAN.png": b"\x89PNG\r\n\x1a\norphan",
        },
    )

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    assert [row["source"] for row in payload["artifacts"]] == [REVIEW_OUTPUT_SOURCE] * 5
    files = [row["artifact"]["file"] for row in payload["artifacts"]]
    assert files == list(PROTECTED)
    assert "netlist_raw.json" not in files
    assert not any("ORPHAN" in name for name in files)
    assert payload["status"] == "ok"
    assert payload["missingOutputs"] == []


# ---------------------------------------------------------------------------
# 3) CLI envelope: bytes, inputs, exit codes
# ---------------------------------------------------------------------------


def test_stdout_and_file_bytes_are_the_same_and_inputs_are_untouched(tmp_path, capsys):
    out = write_out(tmp_path)
    before_hashes = hashes(out)
    before_report = (out / "report.json").read_bytes()
    target = tmp_path / "projection.json"

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    stdout_blob = capsys.readouterr().out.encode("utf-8")
    assert run_cli(
        "--out", str(out), "--section", "artifacts", "--json", str(target)
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""

    assert target.read_bytes() == stdout_blob
    envelope = json.loads(stdout_blob.decode("utf-8"))
    assert envelope["schema"] == REVIEW_READ_SCHEMA
    assert envelope["section"] == "artifacts"
    assert set(envelope) == {"schema", "section", "report", "payload"}
    assert set(envelope["payload"]) == {"status", "artifacts", "missingOutputs"}

    assert hashes(out) == before_hashes
    assert (out / "report.json").read_bytes() == before_report


def test_cli_artifacts_payload_is_the_projection_plus_the_one_verification_step(
    tmp_path, capsys
):
    out = write_out(tmp_path)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    assert payload == artifacts_payload(synthetic_report(), out)
    # And the pure half is still exactly what the engine promises.
    projection = review_read_section(synthetic_report(), "artifacts")
    assert [row["source"] for row in payload["artifacts"]] == [
        row["source"] for row in projection["artifacts"]
    ]


@pytest.mark.parametrize("section", ["verdict", "findings", "crossView", "coverage"])
def test_other_sections_are_unchanged(section, tmp_path, capsys):
    out = write_out(tmp_path)

    assert run_cli("--out", str(out), "--section", section) == 0
    envelope = read_json(capsys)

    assert envelope["payload"] == review_read_section(synthetic_report(), section)
    assert set(envelope["payload"]) != {"status", "artifacts", "missingOutputs"}


def test_a_citation_without_a_usable_file_is_an_error(tmp_path, capsys):
    report = synthetic_report()
    report["ai_slots"]["canvas_images"].append({"board": "SYNTH-B2"})
    report["evidence"]["channels"]["datasheets"]["artifacts"].append({"file": "  "})
    # A file-citing source is not exempt either: a capture artifact without a
    # file is a citation that cannot be checked, not a board reading.
    report["evidence"]["liveCapture"]["artifacts"].append({"kind": "image"})
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "artifacts") == 0
    payload = read_json(capsys)["payload"]

    blank = [
        row for row in payload["artifacts"]
        if row["source"] == "ai_slots.canvas_images" and row["artifact"].get("file") is None
    ]
    assert len(blank) == 1
    assert blank[0]["error"] == "missing-file"
    assert blank[0]["path"] is None
    assert blank[0]["exists"] is None
    whitespace = [
        row for row in payload["artifacts"]
        if row["artifact"].get("file") == "  "
    ]
    assert whitespace and whitespace[0]["error"] == "missing-file"
    capture = [
        row for row in payload["artifacts"]
        if row["source"] == "liveCapture.artifacts" and row["error"] == "missing-file"
    ]
    assert len(capture) == 1 and capture[0]["artifact"] == {"kind": "image"}
    assert payload["status"] == "unavailable"
