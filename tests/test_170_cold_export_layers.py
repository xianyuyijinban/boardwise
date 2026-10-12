"""170: an online export that lost its layer physics says so instead of reading 0.

166 真机对拍 measured this on a real editor: the **first** ``sys.get_project_file``
after the editor connects was 4531 B smaller than the same export taken warm, and
the difference was the PCB documents' layer records. The observable is
``pcb_review.boards[].copperLayers == 0`` where the board's truth is 2, and rules
that quote the count print it (``pcb-foc-ground-plane``: 「reads 0 copper
layer(s)」). Once the editor had walked its own DRC stage the export was complete
again.

The archive is still a real export — the geometry, the placements and every other
reading off it are the ones the editor sent, so the batch does **not** turn this
into a verdict gate (126d's ``pcbReviewMissing`` stays offline-only, and 166's
``pcbReviewNotRun`` is about a review that did not run at all). What it does is
put a sentence in ``source.notes`` — the channel ``report.md`` renders and the
console prints — so a report whose layer counts came from a cold export cannot be
read as a warm one's.

Two asymmetries are deliberate and pinned below:

* **only the online project-file branch discloses.** Offline, the user chose the
  file, and a file a human exported carries its layer data; the same cold archive
  read through ``--file`` therefore says nothing (it is still read — the note is
  not a gate on the reading either way);
* **the trigger is the observable, not the cause.** The note fires when a board
  in the section reads 0 copper layers, whatever dropped them. (A board that
  keeps its ``LAYER`` definitions but loses ``LAYER_PHYS`` reads 34 — 125's own
  pitfall — and is *not* this disclosure's case.)

The fake bridge is the one ``tests/test_checkup_cli.py`` established; the cold
archive is built in memory from the read-only ROBOT fixture, so no fixture is
edited and nothing here touches a daemon.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import test_checkup_cli as base  # noqa: E402 — the fake bridge, reused, not respelled
from boardwise.cli import _cmd_checkup

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: A real export that carries PCB documents (PCB1 / 49 placements / 4 copper
#: layers) — the fixture 166 used for the online/offline comparison.
WARM_ARCHIVE = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"

#: The substring every cold-export note carries, so the assertions below name the
#: sentence rather than depend on its whole wording.
COLD_MARK = "层物理信息"

fake_bridge = base.fake_bridge


def _cold_export_bytes(path: Path = WARM_ARCHIVE) -> bytes:
    """The same export with the PCB documents' layer block removed.

    The stream is one record per line inside the container's ``.epru`` member, so
    the layer records are dropped by type and the container rebuilt in memory. It
    is a *real* archive minus those records — the geometry and the placements
    survive — which is what makes it the 166 shape (an export whose layer physics
    never made it into the file) rather than a corrupt-file edge case.
    """
    with zipfile.ZipFile(path) as archive:
        members = [
            info for info in archive.infolist() if info.filename.lower().endswith(".epru")
        ]
        member = max(members, key=lambda info: info.file_size)
        text = archive.read(member).decode("utf-8-sig")
    dropped = ('"type":"LAYER_PHYS"', '"type":"LAYER"')
    kept = [
        line for line in text.splitlines()
        if not any(marker in line for marker in dropped)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as rebuilt:
        rebuilt.writestr(member.filename, "\n".join(kept).encode("utf-8"))
    return buffer.getvalue()


def _answers(blob: bytes) -> dict:
    """The fake daemon's answers, with ``blob`` as the whole-project archive."""
    answers = base._live_answers(drc=False)
    answers["sys.get_project_file"] = base._archive_payload(
        blob, scope="project", name=WARM_ARCHIVE.name
    )
    return answers


def _checkup(path: Path, **overrides) -> int:
    return _cmd_checkup(base._checkup_args(out=str(path), **overrides))


def _report(path: Path) -> dict:
    return json.loads((path / "report.json").read_text(encoding="utf-8"))


def _notes(report: dict) -> str:
    return " ".join(report["source"]["notes"])


# ---------------------------------------------------------------------------
# the online project-file branch discloses
# ---------------------------------------------------------------------------


def test_a_cold_export_is_disclosed_in_source_notes_and_moves_no_verdict(
    fake_bridge, tmp_path, capsys
):
    """The 166 shape, online: a section whose layer count reads 0 is flagged.

    The three things this test holds apart are the point of the batch: the layer
    count really does read 0 (so the silence was the only defect), the sentence
    lands in the channel a human reads (``source.notes`` → ``report.md`` → the
    console), and the report's own verdict does not move for it.
    """
    cold = _cold_export_bytes()
    base._FakeBridgeClient.answers = _answers(cold)
    out = tmp_path / "cold"
    assert _checkup(out) == 3, (
        "073: this fixture's verdict is incomplete for its own reasons "
        "(unreviewed parts), exactly as it is with the warm archive — the layer "
        "count is what this test is about"
    )
    printed = capsys.readouterr().out
    report = _report(out)

    assert report["source"]["tier"] == "project-file"
    # The observable: the archive is readable and its boards are read — the layer
    # count is the one reading that came back 0.
    boards = report["pcb_review"]["boards"]
    assert [board["title"] for board in boards] == ["PCB1"]
    assert [board["copperLayers"] for board in boards] == [0]
    assert boards[0]["components"] == 49, "the placements survived the strip"

    notes = _notes(report)
    assert COLD_MARK in notes
    assert "copperLayers=0" in notes
    assert "冷启动" in notes, "the note names the likely cause, not just the symptom"
    assert COLD_MARK in printed, "the console carries the same sentence"

    # The reading is disclosed, not gated: the section exists, the run reviewed
    # the board, and neither the offline gate nor the online not-run disclosure
    # is raised by a layer count.
    assert report["pcb_review"]["available"] is True
    assert report["pcb_review"]["boards"][0]["findings"], (
        "the review still ran over the archive it was handed"
    )
    coverage = report["completion"]["coverage"]
    assert coverage["pcbReviewMissing"] is False
    assert "pcbReviewNotRun" not in coverage
    assert not any("PCB" in why for why in report["completion"]["verdictWhy"])


def test_a_warm_export_says_nothing_about_layers(fake_bridge, tmp_path, capsys):
    """The other side of the pin: a complete export gets no such note.

    Without this, a note that was always appended would pass the test above while
    telling every user their export was suspect.
    """
    base._FakeBridgeClient.answers = _answers(WARM_ARCHIVE.read_bytes())
    out = tmp_path / "warm"
    assert _checkup(out) == 3
    capsys.readouterr()
    report = _report(out)

    assert [b["copperLayers"] for b in report["pcb_review"]["boards"]] == [4]
    assert COLD_MARK not in _notes(report)
    assert "copperLayers=0" not in _notes(report)


def test_an_archive_with_no_pcb_document_is_not_this_disclosure(
    fake_bridge, tmp_path
):
    """No PCB document at all is 166's 「nothing to review」, not a layer problem.

    Both end up with no copper count anywhere, which is exactly why they have to
    be told apart by the section rather than by the number: this run carries
    ``pcbReviewNotRun`` and must not carry the layer sentence.
    """
    base._FakeBridgeClient.answers = _answers(base.GOLDEN_BYTES)
    out = tmp_path / "nopcb"
    assert _checkup(out) == 3
    report = _report(out)

    assert "pcb_review" not in report
    assert "pcbReviewNotRun" in report["completion"]["coverage"]
    assert COLD_MARK not in _notes(report)


# ---------------------------------------------------------------------------
# the offline path is deliberately untouched
# ---------------------------------------------------------------------------


def test_the_offline_path_does_not_disclose_the_same_archive(fake_bridge, tmp_path):
    """``--file`` reads a file the user chose, so this batch adds nothing there.

    Pinned as a **decision**, not as a side effect: the offline run over the very
    same cold archive still reads ``copperLayers == 0`` and still finds nothing to
    say about it, because the file in hand is the file the user exported and
    boardwise has no basis to call it cold. A future batch that wants the note
    offline has to change this test on purpose.
    """
    cold = tmp_path / "cold.epro2"
    cold.write_bytes(_cold_export_bytes())
    out = tmp_path / "offline"
    assert _checkup(out, file=str(cold)) == 3
    report = _report(out)

    assert report["source"]["tier"] == "file"
    assert [b["copperLayers"] for b in report["pcb_review"]["boards"]] == [0]
    assert COLD_MARK not in _notes(report)
