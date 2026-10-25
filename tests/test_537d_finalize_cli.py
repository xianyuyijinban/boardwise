"""537D2a2: ``boardwise review finalize --out DIR`` — the accepted validator, wired in.

537D2a1 built the **content** validator (``engines.reviewfinalize.validate_review_summary``):
a pure function over ``report.json`` and the filled ``review-summary.md``. It had no
command, no artifact verification and no recompute, so every one of its findings was
something a caller had to remember to ask for.

This file pins the command that asks. What it must do:

1. **Shape.** ``review finalize --out DIR``; ``finalize`` is a *positional* word, not a
   subcommands tree, so the existing ``review`` parser keeps serving files. ``--out`` is
   the only flag finalize takes — mixing it with ``--live`` / ``--latest`` / ``--view`` /
   ``--json`` / ``--md`` is exit 2 before anything is read;
2. **Exit codes of its own.** missing ``report.json`` → 3; unusable input (bad JSON, a
   non-object, a missing/non-UTF-8 summary, an unreadable or wrongly-shaped triage
   sidecar, a ``warning_triage`` that is not a list of objects) → 2; a content or artifact
   disagreement → 1; 0 only means **this delivery validated**, never that the board
   passed;
3. **Recompute in memory only.** The report it validates is a ``deepcopy`` with the triage
   sidecar folded back in, ``completion``/``summary`` re-gated, the ``datasheets`` channel
   refreshed and ``board_report``/``conclusion`` re-derived — exactly what the writers do
   on the next ``checkup``. Stale stored counts therefore cannot validate a stale
   delivery, and a ``renderErrors`` that survives derivation is a failure, not something
   to sign;
4. **Artifacts are verified, standard outputs are not failures.** ``review-read``'s own
   artifacts projection + the CLI's file facts are reused; any non-``review-output`` row
   with an error, or any error left on a standard output, is a named issue. A standard
   output that is simply not there yet (``report.md``/``board-report.md`` are written by
   *this* command, ``live-evidence.json`` may never exist) is ``missingOutputs``
   information, not a gate. ``archivePcb``'s board-level readings cite no file and are not
   misses;
5. **Zero writes before the gate opens.** Every byte of the six review files is untouched
   on 1/2/3 and no ``finalize.json`` is ever created. Only after the gate opens may the
   summary's two machine sections (environment/evidence) be re-synced from the recomputed
   report; the human content around them is never rewritten. The one thing written after
   the sync is the deterministic **CLI delivery receipt** (537D2b2): it lists the final
   on-disk bytes/sha256 of the four required outputs, the optional sidecars that exist and
   every file the report's machine fields cite, sorted by relative POSIX path. It is a
   *delivery* receipt (``scope: delivery-content``), never a board verdict and never a
   DSH Session authorisation — ``report.conclusion`` stays the board authority;
6. **On success only**, the existing writers run (``_write_checkup_report``,
   ``_write_checkup_markdown``, ``_write_board_report``), so ``report.json`` /
   ``report.md`` / ``board-report.md`` are the same files the rest of the project already
   reads; ``review-summary.md`` is written back only when those two machine sections
   actually changed.

Everything here is anonymous and synthetic: the acceptance fixture is
``tests/test_537d_finalize_validation.py``'s own report, run through the *existing*
re-gate functions and the *existing* writer so it is what ``checkup`` would have left on
disk. No daemon, no editor, no canvas, no bridge import.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath

import pytest

from boardwise import cli
from boardwise.engines.checkup import (
    CHAINS_KEY,
    ENVIRONMENT_HEADING,
    REVIEW_SUMMARY_BLANK_ADVICE,
    REVIEW_SUMMARY_BLANK_ANALYSIS,
    conclusion_section,
    render_board_report,
    render_report_markdown,
    render_review_summary,
)
from boardwise.engines.evidence import EVIDENCE_HEADING, refresh_datasheets

import test_537d_finalize_validation as fx

#: The six files a finalize run may never change before the gate opens. A file
#: that does not exist must still not exist afterwards, so the comparison is over
#: the whole ``(name -> bytes | absent)`` map.
PROTECTED = (
    "report.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "warning-triage.json",
    "live-evidence.json",
)

SIDECAR = "warning-triage.json"
FINALIZE_RECEIPT = "finalize.json"

#: The three skeleton comments the model replaces — reused verbatim from the
#: validator's own fixture so this file fills a *real* skeleton.
SKELETON_1_RE = fx.SKELETON_1_RE
SKELETON_3_RE = fx.SKELETON_3_RE
SKELETON_4_RE = fx.SKELETON_4_RE


# ---------------------------------------------------------------------------
# fixtures and helpers
# ---------------------------------------------------------------------------


def _normalised(report: dict) -> dict:
    """The report as a finalize re-gate would compute it, using **existing** pieces.

    Deliberately not the new command: this is the state ``checkup`` (or a re-gate)
    leaves behind, and the acceptance fixture has to be that state or a change of
    derivation would make a *correct* delivery look stale. Only the two functions
    the project already exposes are called here — ``_apply_warning_triage`` and
    ``refresh_datasheets`` — and the writer does the derivation.
    """
    regated = copy.deepcopy(report)
    cli._apply_warning_triage(regated, regated["warning_triage"])
    if isinstance(regated.get("evidence"), dict):
        regated["evidence"] = refresh_datasheets(
            regated["evidence"],
            model_empty=bool(
                ((regated.get("completion") or {}).get("coverage") or {}).get("modelEmpty")
            ),
            unreviewed=regated.get("unreviewed_parts") or [],
            accepted_unknown=regated.get("accepted_unknown") or [],
            needs_datasheet=regated.get("needs_datasheet") or [],
        )
    return regated


def _filled(report: dict) -> str:
    """The real skeleton rendered from ``report`` and really filled.

    ``fx._filled`` hard-codes the fixture's ``**结论：0**`` placeholder; a real
    report carries the narrow ``summary.conclusion`` there (that is what
    ``render_review_summary`` prints), so the line is found from the section and
    replaced by the one authoritative ``conclusion.oneLiner`` — the SOP's 收尾
    step, not a test convenience.
    """
    text = render_review_summary(report, report[CHAINS_KEY])
    one_liner = report["conclusion"]["oneLiner"]
    narrow = str((report.get("summary") or {}).get("conclusion") or "")
    for placeholder in (
        f"**结论：{narrow}**" if narrow else "**结论：0**",
        "**结论：0**",
    ):
        if placeholder in text:
            text = text.replace(placeholder, f"**结论：{one_liner}**", 1)
            break
    else:  # pragma: no cover - a renderer change, not a delivery state
        raise AssertionError("skeleton 的结论行形状变了，填充助手要跟着改")
    text = SKELETON_1_RE.sub(lambda _m: fx.CONNECTION, text)
    text = SKELETON_3_RE.sub(lambda _m: fx._section3(report), text)
    text = SKELETON_4_RE.sub(lambda _m: fx.NEXT_STEPS, text)
    assert "<!-- AI 在这里写" not in text
    assert "<!-- needs_datasheet 非空时" not in text
    assert "<!-- 1. / 2. / 3." not in text
    text = text.replace(REVIEW_SUMMARY_BLANK_ANALYSIS, fx.ANALYSIS)
    text = text.replace(REVIEW_SUMMARY_BLANK_ADVICE, fx.ADVICE)
    return text


def _make_review(tmp_path: Path, *, summary: bool = True, **kwargs) -> tuple[Path, dict]:
    """A review directory as ``checkup`` leaves it, plus the filled summary.

    Returns ``(out_dir, written_report)``. ``written_report`` is the report.json
    on disk, re-read, so an assertion never tests an object the writer mutated
    after the fact.
    """
    out = tmp_path / "review"
    report = _normalised(fx._report(**kwargs))
    cli._write_checkup_report(out, report)
    written = json.loads((out / "report.json").read_text(encoding="utf-8"))
    if summary:
        (out / "review-summary.md").write_text(_filled(written), encoding="utf-8")
    return out, written


def _rewrite_report(out: Path, report: dict) -> None:
    """Put a hand-built/stale report back exactly as the writer spells it."""
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _files(out: Path) -> dict[str, bytes | None]:
    """The six protected files as ``name -> bytes`` (or ``None`` when absent)."""
    return {
        name: (out / name).read_bytes() if (out / name).is_file() else None
        for name in PROTECTED
    }


def _run(out: Path, *extra: str) -> int:
    return cli.main(["review", "finalize", "--out", str(out), *extra])


def _issues(text: str) -> list[dict]:
    """The ``{code, path, message}`` rows the command printed, one per line."""
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and {"code", "path", "message"} <= set(payload):
            rows.append(payload)
    return rows


def _codes(text: str) -> list[str]:
    return [row["code"] for row in _issues(text)]


def _assert_untouched(out: Path, before: dict[str, bytes | None], capsys) -> None:
    """Nothing of the six moved, no receipt, and no traceback on the way out."""
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert _files(out) == before
    assert not (out / FINALIZE_RECEIPT).exists()


#: The receipt's frozen envelope (537D2b2). A consumer reads *these* names; a
#: timestamp / random id / absolute path / board-level pass must never appear.
RECEIPT_SCHEMA = "boardwise.review-finalize/1"
RECEIPT_SCOPE = "delivery-content"
RECEIPT_AUTHORITY = "report.conclusion"
RECEIPT_REQUIRED = (
    "board-report.md",
    "report.json",
    "report.md",
    "review-summary.md",
)


def _receipt(out: Path) -> dict:
    return json.loads((out / FINALIZE_RECEIPT).read_text(encoding="utf-8"))


def _all_files(out: Path) -> dict[str, bytes]:
    """Every file in the directory, keyed by relative POSIX path (receipt included)."""
    return {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }


def _assert_receipt_shape(out: Path) -> dict:
    """The frozen shape, the sorted/unique POSIX paths and the **actual** bytes/sha.

    Every number is recomputed here from the file on disk: a receipt that echoed a
    declared ``bytes`` / ``sha256`` from the report would pass a weaker test.
    """
    receipt = _receipt(out)
    assert list(receipt) == [
        "schema",
        "ok",
        "scope",
        "boardConclusionAuthority",
        "files",
    ]
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["ok"] is True
    assert receipt["scope"] == RECEIPT_SCOPE
    assert receipt["boardConclusionAuthority"] == RECEIPT_AUTHORITY

    rows = receipt["files"]
    assert isinstance(rows, list) and rows
    paths = [row["path"] for row in rows]
    assert paths == sorted(paths), paths
    assert len(paths) == len(set(paths)), paths
    assert FINALIZE_RECEIPT not in paths
    assert set(RECEIPT_REQUIRED) <= set(paths), set(RECEIPT_REQUIRED) - set(paths)

    for row in rows:
        assert list(row) == ["path", "bytes", "sha256"]
        relative = PurePosixPath(row["path"])
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        assert "\\" not in row["path"]
        target = out / Path(*relative.parts)
        assert target.is_file(), row["path"]
        blob = target.read_bytes()
        assert row["bytes"] == len(blob), row["path"]
        assert row["sha256"] == hashlib.sha256(blob).hexdigest(), row["path"]
    return receipt


def _receipt_sha(receipt: dict, name: str) -> str:
    return next(row["sha256"] for row in receipt["files"] if row["path"] == name)


def _add_citation(out: Path, source: str, artifact: dict) -> None:
    """Put one cited artifact into the machine field named by ``source``."""
    written = json.loads((out / "report.json").read_text(encoding="utf-8"))
    evidence = written["evidence"]
    if source == "canvas":
        written["ai_slots"] = {"canvas_images": [artifact]}
    elif source == "channel":
        evidence["channels"]["schematicImage"]["artifacts"] = [artifact]
    elif source == "live-channel":
        evidence["channels"]["liveSchematic"]["artifacts"] = [artifact]
    elif source == "capture-artifacts":
        evidence["liveCapture"]["artifacts"] = [artifact]
    elif source == "capture-file":
        evidence["liveCapture"]["captureFile"] = artifact
    else:  # pragma: no cover - a typo in the test, not a delivery state
        raise AssertionError(source)
    _rewrite_report(out, written)



# ---------------------------------------------------------------------------
# 1. the command shape
# ---------------------------------------------------------------------------


def test_parser_routes_finalize_with_out_and_leaves_old_review_alone():
    parser = cli.build_parser()
    args = parser.parse_args(["review", "finalize", "--out", "DIR"])
    assert args.command == "review"
    assert args.file == "finalize"
    assert args.out == "DIR"
    # The old review flags keep their defaults, so the dispatch can refuse a mix.
    assert args.live is False
    assert args.latest is None
    assert args.view is None
    assert args.json_path is None
    assert args.md_path is None

    old = parser.parse_args(["review", "board.enet", "--json", "report.json"])
    assert old.file == "board.enet"
    assert old.out == ""  # --out exists for finalize only; the old path ignores it
    assert old.json_path == "report.json"


def test_finalize_without_out_is_two(capsys):
    assert cli.main(["review", "finalize"]) == 2
    captured = capsys.readouterr()
    assert "--out" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "extra",
    [
        ["--live"],
        ["--latest"],
        ["--view", "pcb"],
        ["--json", "537d-unused.json"],
        ["--md", "537d-unused.md"],
    ],
)
def test_finalize_refuses_old_review_flags(tmp_path, extra, capsys):
    out, _written = _make_review(tmp_path)
    before = _files(out)
    assert _run(out, *extra) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert _files(out) == before
    assert not (out / FINALIZE_RECEIPT).exists()
    assert not (Path.cwd() / "537d-unused.json").exists()
    assert not (Path.cwd() / "537d-unused.md").exists()


@pytest.mark.parametrize("flag", ["--json", "--md"])
def test_finalize_refuses_empty_old_flag_value(tmp_path, flag, capsys):
    """``--json ""`` is still the caller *giving* ``--json``.

    An empty value names stdout-or-a-path in the old review route; it is not the
    same statement as omitting the flag. The mix must therefore be refused on
    the flag's **presence** — and refused before even looking for report.json
    (a directory without one would otherwise be exit 3, not 2).
    """
    bare = tmp_path / "no-report-here"
    bare.mkdir()
    assert cli.main(["review", "finalize", "--out", str(bare), flag, ""]) == 2
    captured = capsys.readouterr()
    assert "只认 --out DIR" in captured.err
    assert flag in captured.err
    assert not (bare / "report.json").exists()

    out, _written = _make_review(tmp_path)
    before = _files(out)
    assert _run(out, flag, "") == 2
    captured = capsys.readouterr()
    assert "只认 --out DIR" in captured.err
    assert flag in captured.err
    assert "Traceback" not in captured.err
    assert _files(out) == before
    assert not (out / FINALIZE_RECEIPT).exists()


def test_missing_report_json_is_three_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "review"
    out.mkdir()
    (out / "review-summary.md").write_text("synthetic\n", encoding="utf-8")
    before = _files(out)
    assert _run(out) == 3
    _assert_untouched(out, before, capsys)


# ---------------------------------------------------------------------------
# 2. unusable input is 2, never a traceback
# ---------------------------------------------------------------------------


def _break(out: Path, case: str, written: dict) -> None:
    """Apply one structural break to an otherwise good review directory."""
    if case == "report-json":
        (out / "report.json").write_text("{ not json", encoding="utf-8")
        return
    if case == "report-list":
        (out / "report.json").write_text("[]", encoding="utf-8")
        return
    if case == "summary-not-utf8":
        (out / "review-summary.md").write_bytes(b"\xff\xfe\x00 not utf-8")
        return
    if case == "sidecar-json":
        (out / SIDECAR).write_text("{ broken", encoding="utf-8")
        return
    if case == "sidecar-shape":
        (out / SIDECAR).write_text('{"version": 1, "entries": 5}', encoding="utf-8")
        return
    if case == "sidecar-entries":
        (out / SIDECAR).write_text('{"version": 1, "entries": [1, 2]}', encoding="utf-8")
        return
    stale = copy.deepcopy(written)
    if case == "triage-not-list":
        stale["warning_triage"] = [None]
    elif case == "triage-missing":
        stale.pop("warning_triage", None)
    else:  # pragma: no cover - the parametrisation is the contract
        raise AssertionError(case)
    _rewrite_report(out, stale)


@pytest.mark.parametrize(
    "case",
    [
        "report-json",
        "report-list",
        "summary-not-utf8",
        "sidecar-json",
        "sidecar-shape",
        "sidecar-entries",
        "triage-not-list",
        "triage-missing",
    ],
)
def test_unusable_input_is_two_and_writes_nothing(tmp_path, case, capsys):
    out, written = _make_review(tmp_path)
    _break(out, case, written)
    before = _files(out)
    assert _run(out) == 2
    _assert_untouched(out, before, capsys)


def test_missing_review_summary_is_two(tmp_path, capsys):
    out, _written = _make_review(tmp_path, summary=False)
    before = _files(out)
    assert _run(out) == 2
    _assert_untouched(out, before, capsys)


@pytest.mark.parametrize(
    "case, path",
    [
        ("report", "report.schema"),
        ("evidence", "report.evidence.schema"),
        ("liveCapture", "report.evidence.liveCapture.schema"),
    ],
)
def test_foreign_schema_is_structural_two_before_any_recompute(
    tmp_path, case, path, capsys
):
    """A foreign schema id is unusable **input**, checked before every recompute.

    The three ids are the current build's contract: a report from another
    version cannot be re-gated by guessing what its fields meant. This is exit 2
    (like bad JSON), not a content 1 — and it is decided before the summary is
    read, before any derivation and before any writer.
    """
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    if case == "report":
        stale["schema"] = "boardwise.checkup/999"
    elif case == "evidence":
        stale["evidence"]["schema"] = "boardwise.evidence/999"
    else:
        stale["evidence"]["liveCapture"]["schema"] = "boardwise.live-evidence/999"
    _rewrite_report(out, stale)
    before = _files(out)

    assert _run(out) == 2
    captured = capsys.readouterr()
    assert path in captured.err
    assert "999" in captured.err
    assert "Traceback" not in captured.err
    _assert_untouched(out, before, capsys)
    assert not (out / FINALIZE_RECEIPT).exists()


# ---------------------------------------------------------------------------
# 3. the acceptance case: pending + needsManual + partial validates
# ---------------------------------------------------------------------------


def test_good_report_with_pending_manual_and_partial_finalizes(tmp_path, capsys):
    out, written = _make_review(tmp_path)
    # The premises, asserted rather than assumed: this is an *open* review, and
    # an open review is a consistent delivery.
    assert written["completion"]["warningsPendingTriage"] == 1
    assert written["completion"]["warningsNeedsManual"] == 1
    assert written["evidence"]["delivery"]["status"] == "partial"
    assert written["conclusion"]["mayQuotePassed"] is False
    summary_before = (out / "review-summary.md").read_bytes()

    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    text = captured.out
    assert "finalize validation: ok" in text
    assert "pending 1" in text
    assert "needsManual 1" in text
    assert "delivery partial" in text
    # Success is a delivery statement, not a board verdict, and the CLI delivery
    # receipt is the only thing it signs — both must be on the console, together
    # with the sentence that a DSH Session still needs D3.
    assert "不是板级通过" in text
    assert "收据" in text
    assert "finalize.json" in text
    assert "delivery-content" in text
    assert "DSH" in text and "D3" in text

    after = json.loads((out / "report.json").read_text(encoding="utf-8"))
    # The fixture carries no architecture skeleton, so the *recomputed* verdict
    # is `incomplete` — the point is that it is the one the sections support, and
    # that an open review (`incomplete` included) still validates clean.
    assert after["completion"]["verdict"] == written["completion"]["verdict"]
    assert after["conclusion"]["verdict"] == after["completion"]["verdict"]
    assert after["conclusion"]["exitCode"] == after["summary"]["exitCode"]
    assert f"verdict {after['completion']['verdict']}" in text
    # `refresh_datasheets` must carry the live capture's identity/focus
    # disclosures through the re-gate — they were not re-collected here.
    capture = after["evidence"]["liveCapture"]
    assert capture["identity"]["verifiedAgainstReport"] is True
    assert capture["focusRestore"]["ok"] is True
    assert after["evidence"]["delivery"]["status"] == "partial"
    # Same generator, read back: the section is the report's own derivation.
    assert after["conclusion"] == conclusion_section(after)

    # Only the two machine sections are this command's to re-sync; a delivery
    # that is already in sync is not rewritten at all.
    assert (out / "review-summary.md").read_bytes() == summary_before
    # The delivery receipt is signed from what is now on disk — the four required
    # outputs are exactly the fixture's delivery set.
    receipt = _assert_receipt_shape(out)
    assert [row["path"] for row in receipt["files"]] == list(RECEIPT_REQUIRED)
    assert not (out / SIDECAR).exists()

    # The three sync writers ran, and the Markdown is exactly the existing
    # renderers' output — not a second rendering path.
    assert (out / "report.md").is_file()
    assert (out / "board-report.md").is_file()
    assert (out / "report.md").read_text(encoding="utf-8") == render_report_markdown(after)
    assert (out / "board-report.md").read_text(encoding="utf-8") == render_board_report(after)
    assert after["conclusion"]["oneLiner"] in (out / "board-report.md").read_text(
        encoding="utf-8"
    )


def test_repeat_finalize_is_byte_stable(tmp_path, capsys):
    out, _written = _make_review(tmp_path)
    assert _run(out) == 0
    # The whole directory — the signed receipt included — is byte-identical after
    # the second run: the receipt has no timestamp and no random id.
    first = _all_files(out)
    assert (out / FINALIZE_RECEIPT).is_file()
    assert _run(out) == 0
    capsys.readouterr()
    assert _all_files(out) == first



# ---------------------------------------------------------------------------
# 3b. the machine-section sync (537D2b1): two sections are re-rendered
# ---------------------------------------------------------------------------

#: Human prose that sits between the machine sections and section 3 — a 2b
#: analysis block. It is not the machine's, and no sync may touch it.
HUMAN_2B = (
    "## 2b. 人工补充（补充分析）\n\n"
    "人工结论：这一段是工程师写的，机器段同步一个字都不许动。\n\n"
)


def _with_human_2b(text: str) -> str:
    marker = "## 3. 待确认"
    assert text.count(marker) == 1
    return text.replace(marker, HUMAN_2B + marker, 1)


def test_stale_machine_sections_are_synced_and_human_text_and_crlf_survive(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    original = _with_human_2b(
        (out / "review-summary.md").read_text(encoding="utf-8")
    )
    # A Windows editor wrote this delivery: every newline is CRLF.
    crlf = original.replace("\n", "\r\n")
    stale = crlf.replace("期望 `0.5.0`", "期望 `0.4.0`", 1)
    assert stale != crlf
    (out / "review-summary.md").write_bytes(stale.encode("utf-8"))

    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "finalize validation: ok" in captured.out
    assert "Traceback" not in captured.err
    # The success console names what it did and what it did not do.
    assert "environment/evidence" in captured.out
    assert "review-summary.md 未改" not in captured.out

    data = (out / "review-summary.md").read_bytes()
    # Byte-exact: the stale machine section was replaced by the authoritative
    # rendering, and **nothing else** moved — 2b, sections 3/4 and the CRLF
    # line endings are exactly what the engineer left.
    assert data == crlf.encode("utf-8")
    text = data.decode("utf-8")
    assert "期望 `0.5.0`" in text
    assert "期望 `0.4.0`" not in text
    assert HUMAN_2B.replace("\n", "\r\n") in text
    assert b"\n" not in data.replace(b"\r\n", b"")

    first = _all_files(out)
    assert _run(out) == 0
    capsys.readouterr()
    assert _all_files(out) == first
    # The receipt hashes the *synced* summary, not the stale bytes it replaced.
    assert _receipt_sha(_receipt(out), "review-summary.md") == hashlib.sha256(
        data
    ).hexdigest()


@pytest.mark.parametrize(
    "heading, code",
    [
        (ENVIRONMENT_HEADING, "summary-environment-heading-missing"),
        (EVIDENCE_HEADING, "summary-evidence-heading-missing"),
    ],
)
def test_missing_machine_heading_is_rejected_and_never_invented(
    tmp_path, heading, code, capsys
):
    out, _written = _make_review(tmp_path)
    text = (out / "review-summary.md").read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.index("## ", start + len(heading))
    (out / "review-summary.md").write_bytes(
        (text[:start] + text[end:]).encode("utf-8")
    )
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    assert code in _codes(captured.out)
    _assert_untouched(out, before, capsys)
    # The synchronizer did not put the heading back: a missing machine section
    # is the validator's to reject, not the sync's to guess.
    assert heading not in (out / "review-summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "key, value",
    [
        ("environment", []),
        ("environment", "not-a-section"),
        ("evidence", []),
        ("evidence", "not-a-section"),
    ],
)
def test_malformed_machine_section_is_one_and_never_raises(
    tmp_path, key, value, capsys
):
    """A list/string section is the validator's ``*-missing``, not a crash.

    537D2b1 must not let the new synchronisation call turn a malformed section
    into a traceback, and must not guess an empty disclosure to make the shared
    renderer accept it: the text stays as delivered, every file is untouched,
    and the existing ``environment-missing`` / ``evidence-missing`` answers.
    """
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale[key] = value
    _rewrite_report(out, stale)
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    assert f"{key}-missing" in _codes(captured.out)
    assert "Traceback" not in captured.err
    _assert_untouched(out, before, capsys)


def test_channel_status_outside_the_vocabulary_is_one_and_writes_nothing(
    tmp_path, capsys
):
    """A mystery status cannot be signed — even though the sync would render it.

    Finalize recomputes coverage/delivery from the channels, so a ``mystery``
    status survives into the in-memory summary; the validator must refuse it
    before a byte lands. ``delivery.requiredDisclosures`` is a derived section
    and is not what this check changes.
    """
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale["evidence"]["channels"]["liveSchematic"]["status"] = "mystery"
    _rewrite_report(out, stale)
    before = _files(out)
    summary_before = (out / "review-summary.md").read_bytes()

    assert _run(out) == 1
    captured = capsys.readouterr()
    rows = _issues(captured.out)
    status_rows = [
        row for row in rows if row["code"] == "evidence-channel-status-invalid"
    ]
    assert len(status_rows) == 1
    assert status_rows[0]["path"] == (
        "report.evidence.channels.liveSchematic.status"
    )
    assert "mystery" in status_rows[0]["message"]
    assert "Traceback" not in captured.err
    # Zero writes, no receipt, and the in-memory sync never landed.
    _assert_untouched(out, before, capsys)
    assert (out / "review-summary.md").read_bytes() == summary_before
    assert "mystery" not in (out / "review-summary.md").read_text(encoding="utf-8")


def test_failed_validation_does_not_write_the_synced_machine_sections(
    tmp_path, capsys
):
    out, written = _make_review(tmp_path)
    text = (out / "review-summary.md").read_text(encoding="utf-8")
    one_liner = written["conclusion"]["oneLiner"]
    stale = text.replace("期望 `0.5.0`", "期望 `0.4.0`", 1)
    stale = stale.replace(f"**结论：{one_liner}**", "**结论：已通过**", 1)
    assert stale != text
    (out / "review-summary.md").write_bytes(stale.encode("utf-8"))
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    assert "summary-conclusion-mismatch" in _codes(captured.out)
    # The sync happened in memory only: the stale machine section is still on
    # disk, byte for byte, exactly as every other protected file.
    _assert_untouched(out, before, capsys)
    assert (out / "review-summary.md").read_text(encoding="utf-8") == stale


def test_console_help_and_docstring_describe_the_machine_section_sync(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    assert _run(out) == 0
    console = capsys.readouterr().out
    assert "environment/evidence" in console
    assert "人工" in console
    assert "review-summary.md 未改" not in console
    # The old「未创建」claim is false now: a delivery receipt is created, and the
    # console says exactly what it is (and is not).
    assert "finalize.json 未创建" not in console
    assert "finalize.json" in console
    assert "收据" in console
    assert "delivery-content" in console
    assert "DSH" in console and "D3" in console
    assert "不是板级通过" in console

    with pytest.raises(SystemExit) as exc:
        cli.main(["review", "finalize", "--help"])
    assert exc.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "environment/evidence" in help_text
    assert "human content" in help_text
    assert "finalize.json" in help_text
    assert "DSH" in help_text and "D3" in help_text
    docstring = cli._cmd_review_finalize.__doc__ or ""
    assert "environment/evidence" in docstring
    assert "人工" in docstring
    assert "finalize.json" in docstring
    assert "DSH" in docstring and "D3" in docstring
    assert "delivery-content" in docstring
    assert "不是板级" in docstring


# ---------------------------------------------------------------------------
# 4. stale stored values are recomputed, never trusted
# ---------------------------------------------------------------------------


def test_stale_completion_and_evidence_are_recomputed(tmp_path, capsys):
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    # Every one of these is a claim the *stored* report makes about itself and
    # the recompute can answer from the sections: counts, verdict, delivery,
    # channel coverage, and the conclusion that projects them.
    stale["completion"]["warningsPendingTriage"] = 0
    stale["completion"]["warningsNeedsManual"] = 0
    stale["completion"]["manualReviewRequired"] = []
    stale["completion"]["verdict"] = "complete"
    stale["summary"]["exitCode"] = 0
    stale["summary"]["conclusion"] = "已通过（存储的旧值）"
    stale["evidence"]["delivery"]["status"] = "complete"
    stale["evidence"]["delivery"]["requiredDisclosures"] = []
    stale["evidence"]["coverage"]["datasheets"] = "unavailable"
    stale["conclusion"]["verdict"] = "complete"
    stale["conclusion"]["mayQuotePassed"] = True
    stale["conclusion"]["oneLiner"] = "存储的旧结论"
    stale["conclusion"]["blockers"] = []
    _rewrite_report(out, stale)
    summary_before = (out / "review-summary.md").read_bytes()

    assert _run(out) == 0
    capsys.readouterr()
    after = json.loads((out / "report.json").read_text(encoding="utf-8"))

    assert after["completion"]["warningsPendingTriage"] == 1
    assert after["completion"]["warningsNeedsManual"] == 1
    expected_verdict = written["completion"]["verdict"]
    assert expected_verdict != "complete"
    assert after["completion"]["verdict"] == expected_verdict
    assert after["completion"]["manualReviewRequired"][0]["key"] == "w3"
    assert after["evidence"]["delivery"]["status"] == "partial"
    assert after["evidence"]["coverage"]["datasheets"] == "ok"  # recomputed channel
    assert any(
        row["code"] == "delivery-live-pcb-missing"
        or row["channel"] == "livePcb"
        for row in after["evidence"]["delivery"]["requiredDisclosures"]
    )
    assert after["conclusion"]["verdict"] == after["completion"]["verdict"]
    assert after["conclusion"]["oneLiner"] != "存储的旧结论"
    assert after["conclusion"] == conclusion_section(after)
    # The filled summary still matches the *recomputed* conclusion: the command
    # did not invent a second conclusion from stale prose.
    assert (out / "review-summary.md").read_bytes() == summary_before


# ---------------------------------------------------------------------------
# 5. the triage sidecar: folded in, refusal disclosed, said once
# ---------------------------------------------------------------------------


def test_sidecar_merge_and_refusal_notes_are_appended_once(tmp_path, capsys):
    out, _written = _make_review(tmp_path)
    entries = {
        "version": 1,
        "entries": [
            {
                "key": "w1",
                "verdict": "有益",
                "reason": "合成理由：重复执行也不改结论",
                "source": "host-erc",
                "text": "合成的 warning 文本",
            },
            {
                # A three-word verdict against a text-less slot: refused by
                # `triage_verdict_is_admissible`, disclosed, never applied.
                "key": "w3",
                "verdict": "有害",
                "reason": "合成理由：非法三词",
                "source": "host-erc",
                "text": "",
            },
        ],
    }
    (out / SIDECAR).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sidecar_before = (out / SIDECAR).read_bytes()

    assert _run(out) == 0
    capsys.readouterr()
    first = json.loads((out / "report.json").read_text(encoding="utf-8"))
    notes = first["source"]["notes"]
    merged_notes = [note for note in notes if "已并入本次报告" in note]
    refused_notes = [note for note in notes if "被拒收" in note]
    assert len(merged_notes) == 1
    assert len(refused_notes) == 1
    # The merge landed on the slot; the refusal did not (w3 stays needs-manual).
    slots = {slot["key"]: slot for slot in first["warning_triage"]}
    assert slots["w1"]["reason"] == "合成理由：重复执行也不改结论"
    assert slots["w3"]["verdict"] == "needs-manual"
    # The audit trail is not this command's to edit.
    assert (out / SIDECAR).read_bytes() == sidecar_before

    first_bytes = (out / "report.json").read_bytes()
    assert _run(out) == 0
    capsys.readouterr()
    second = json.loads((out / "report.json").read_text(encoding="utf-8"))
    # Same exact sentence, once — a second finalize of the same input does not
    # append its own note again, and the file is byte-identical.
    assert second["source"]["notes"].count(merged_notes[0]) == 1
    assert second["source"]["notes"].count(refused_notes[0]) == 1
    assert (out / "report.json").read_bytes() == first_bytes
    assert (out / SIDECAR).read_bytes() == sidecar_before
    # The sidecar is an audit trail, not a delivered output: it is tracked in the
    # receipt because it exists, and it is never rewritten.
    receipt = _assert_receipt_shape(out)
    assert SIDECAR in [row["path"] for row in receipt["files"]]
    assert _receipt_sha(receipt, SIDECAR) == hashlib.sha256(sidecar_before).hexdigest()


# ---------------------------------------------------------------------------
# 6. content failures: 1, every file untouched
# ---------------------------------------------------------------------------


def test_summary_content_issue_is_one_and_writes_nothing(tmp_path, capsys):
    out, written = _make_review(tmp_path)
    text = (out / "review-summary.md").read_text(encoding="utf-8")
    one_liner = written["conclusion"]["oneLiner"]
    tampered = text.replace(f"**结论：{one_liner}**", "**结论：已通过**")
    assert tampered != text
    (out / "review-summary.md").write_text(tampered, encoding="utf-8")
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    codes = _codes(captured.out)
    assert "summary-conclusion-mismatch" in codes
    _assert_untouched(out, before, capsys)
    assert not (out / "report.md").exists()
    assert not (out / "board-report.md").exists()


def test_failed_focus_restore_is_one(tmp_path, capsys):
    out, written = _make_review(tmp_path, focus_ok=False)
    assert written["evidence"]["liveCapture"]["focusRestore"]["ok"] is False
    before = _files(out)
    assert _run(out) == 1
    captured = capsys.readouterr()
    assert "focus-not-restored" in _codes(captured.out)
    _assert_untouched(out, before, capsys)


@pytest.mark.parametrize("key", ["environment", "evidence"])
def test_missing_disclosure_section_is_one(tmp_path, key, capsys):
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale.pop(key)
    _rewrite_report(out, stale)
    before = _files(out)
    assert _run(out) == 1
    captured = capsys.readouterr()
    assert f"{key}-missing" in _codes(captured.out)
    _assert_untouched(out, before, capsys)


def test_stored_render_errors_block_the_run(tmp_path, capsys):
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale["renderErrors"] = ["合成的派生失败：board_report 节"]
    _rewrite_report(out, stale)
    before = _files(out)
    assert _run(out) == 1
    captured = capsys.readouterr()
    assert "render-errors" in _codes(captured.out)
    _assert_untouched(out, before, capsys)


@pytest.mark.parametrize(
    "value",
    [
        "合成的派生失败：board_report 节",
        "",
        {"board_report": "合成的派生失败"},
        {},
        0,
    ],
)
def test_non_list_render_errors_block_the_run(tmp_path, value, capsys):
    """``renderErrors`` is a *list of failures*; any other shape is unreadable.

    The recompute only replaces the field when derivation itself fails, so a
    stored string/dict survives to the gate. Ignoring it would sign a report
    whose derivation state this command could not read — fail closed instead,
    and note that an empty string/empty dict (and a falsy ``0``) are still the
    wrong **type**, not 「no errors」.
    """
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale["renderErrors"] = value
    _rewrite_report(out, stale)
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    rows = [row for row in _issues(captured.out) if row["code"] == "render-errors"]
    assert len(rows) == 1
    assert rows[0]["path"] == "report.renderErrors"
    assert type(value).__name__ in rows[0]["message"]
    _assert_untouched(out, before, capsys)
    assert not (out / "report.md").exists()
    assert not (out / "board-report.md").exists()


@pytest.mark.parametrize("value", [None, []])
def test_absent_render_errors_are_not_a_failure(tmp_path, value, capsys):
    """No derivation error is ``[]`` … and the field may simply be absent/None."""
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    stale["renderErrors"] = value
    _rewrite_report(out, stale)

    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "finalize validation: ok" in captured.out
    assert "Traceback" not in captured.err
    _assert_receipt_shape(out)


# ---------------------------------------------------------------------------
# 7. artifact verification
# ---------------------------------------------------------------------------


def _cite(out: Path, artifact: dict) -> None:
    """Add one cited artifact to a channel and put the report back on disk."""
    written = json.loads((out / "report.json").read_text(encoding="utf-8"))
    channels = written["evidence"]["channels"]
    channels["schematicImage"]["artifacts"] = [artifact]
    _rewrite_report(out, written)


@pytest.mark.parametrize(
    "case, expected",
    [
        ("bytes", "artifact-bytes-mismatch"),
        ("sha", "artifact-sha256-mismatch"),
        ("missing", "artifact-missing"),
        ("outside", "artifact-outside-review-directory"),
        ("not-file", "artifact-not-file"),
    ],
)
def test_artifact_evidence_errors_are_one(tmp_path, case, expected, capsys):
    out, _written = _make_review(tmp_path)
    canvas = out / "canvas"
    canvas.mkdir()
    if case == "bytes":
        (canvas / "p1.png").write_bytes(b"png")
        _cite(out, {"file": "canvas/p1.png", "kind": "image", "bytes": 99999})
    elif case == "sha":
        (canvas / "p1.png").write_bytes(b"png")
        _cite(out, {"file": "canvas/p1.png", "kind": "image", "sha256": "0" * 64})
    elif case == "missing":
        _cite(out, {"file": "canvas/absent.png", "kind": "image"})
    elif case == "outside":
        _cite(out, {"file": "../outside.png", "kind": "image"})
    else:  # not-file
        (canvas / "p1.png").mkdir()
        _cite(out, {"file": "canvas/p1.png", "kind": "image"})
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    codes = _codes(captured.out)
    assert expected in codes, (expected, codes)
    _assert_untouched(out, before, capsys)
    assert not (out / "report.md").exists()


def test_archive_pcb_board_readings_are_not_file_citations(tmp_path, capsys):
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    # `_archive_pcb` writes board-level readings with no `file` key. They are not
    # citations and must not be read as missing files.
    stale["evidence"]["channels"]["archivePcb"]["artifacts"] = [
        {"title": "Board1", "components": 12, "copperLayers": 2}
    ]
    _rewrite_report(out, stale)
    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "finalize validation: ok" in captured.out
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# 8. no bridge, no editor, no second authority
# ---------------------------------------------------------------------------


def test_finalize_path_never_touches_the_bridge():
    source = inspect.getsource(cli._cmd_review_finalize)
    for token in (
        "BridgeClient",
        "asyncio",
        "_open_cli",
        "subprocess",
        "boardwise.bridge",
        "_load_model",
        "run_review",
    ):
        assert token not in source, f"finalize 的入口不许碰 {token}"


def test_finalize_calls_the_accepted_validator():
    """The accepted validator is the one the command calls — no second copy."""
    source = inspect.getsource(cli._cmd_review_finalize)
    assert "validate_review_summary" in source
    # ...and the artifacts answer comes from the 537D1a projections, not a
    # second walk of the report.
    assert "review_read_section" in source
    assert "_review_read_artifacts_payload" in source


# ---------------------------------------------------------------------------
# 9. the raw evidence containers: six anonymous inputs that used to be exit 0
# ---------------------------------------------------------------------------
#
# `reviewread`'s artifacts projection tolerates these shapes by skipping them,
# so before this slice every one of them validated and signed a delivery whose
# own evidence record could not be read. They are content disagreements now:
# exit 1, zero writes, no receipt, no traceback.


def _break_container(report: dict, case: str) -> None:
    evidence = report["evidence"]
    if case == "channel-artifacts-str":
        evidence["channels"]["liveSchematic"]["artifacts"] = "bad"
    elif case == "channel-artifacts-item":
        evidence["channels"]["liveSchematic"]["artifacts"] = ["bad"]
    elif case == "channel-errors":
        evidence["channels"]["liveSchematic"]["errors"] = "bad"
    elif case == "channel-steps":
        evidence["channels"]["liveSchematic"]["steps"] = "bad"
    elif case == "capture-artifacts":
        evidence["liveCapture"]["artifacts"] = "bad"
    elif case == "capture-file":
        evidence["liveCapture"]["captureFile"] = "bad"
    else:  # pragma: no cover - a typo in the parametrisation, not a state
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case, code, path",
    [
        (
            "channel-artifacts-str",
            "evidence-channel-field-not-list",
            "report.evidence.channels.liveSchematic.artifacts",
        ),
        (
            "channel-artifacts-item",
            "evidence-channel-artifact-not-dict",
            "report.evidence.channels.liveSchematic.artifacts[0]",
        ),
        (
            "channel-errors",
            "evidence-channel-field-not-list",
            "report.evidence.channels.liveSchematic.errors",
        ),
        (
            "channel-steps",
            "evidence-channel-field-not-list",
            "report.evidence.channels.liveSchematic.steps",
        ),
        (
            "capture-artifacts",
            "evidence-live-capture-field-not-list",
            "report.evidence.liveCapture.artifacts",
        ),
        (
            "capture-file",
            "evidence-live-capture-file-not-dict",
            "report.evidence.liveCapture.captureFile",
        ),
    ],
)
def test_unreadable_evidence_container_is_one_and_writes_nothing(
    tmp_path, case, code, path, capsys
):
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    _break_container(stale, case)
    _rewrite_report(out, stale)
    before = _files(out)

    assert _run(out) == 1
    captured = capsys.readouterr()
    rows = [row for row in _issues(captured.out) if row["code"] == code]
    assert len(rows) == 1, (case, _codes(captured.out))
    assert rows[0]["path"] == path
    assert "Traceback" not in captured.err
    # Zero writes: the in-memory sync never lands and nothing is signed.
    assert _files(out) == before
    assert not (out / FINALIZE_RECEIPT).exists()
    assert not (out / "report.md").exists()
    assert not (out / "board-report.md").exists()


def test_absent_containers_still_finalize_clean(tmp_path, capsys):
    """Missing fields keep the old compatibility end to end: still exit 0."""
    out, written = _make_review(tmp_path)
    stale = copy.deepcopy(written)
    for row in stale["evidence"]["channels"].values():
        for field in ("artifacts", "errors", "steps"):
            row.pop(field, None)
    stale["evidence"]["liveCapture"].pop("artifacts", None)
    stale["evidence"]["liveCapture"].pop("steps", None)
    _rewrite_report(out, stale)

    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "finalize validation: ok" in captured.out
    assert "Traceback" not in captured.err
    receipt = _assert_receipt_shape(out)
    # No citations survive, so the receipt is the four required outputs only;
    # the optional live-evidence.json was never here and is not invented.
    assert [row["path"] for row in receipt["files"]] == list(RECEIPT_REQUIRED)


# ---------------------------------------------------------------------------
# 10. the deterministic CLI delivery receipt (537D2b2)
# ---------------------------------------------------------------------------
#
# `exit 0` now signs one receipt: `finalize.json`, `scope: delivery-content`,
# built **after** the four outputs are on disk and from their final bytes. It is
# a delivery fact, not a board pass; `report.conclusion` stays the board
# authority and a DSH Session still needs D3. Every failure path below must leave
# no receipt at all — the atomic write is the only way one appears.


def test_success_signs_a_deterministic_delivery_receipt(tmp_path, capsys):
    out, _written = _make_review(tmp_path)
    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    receipt = _assert_receipt_shape(out)
    # The plain fixture cites no artifact and carries no optional sidecar: the
    # delivery set is exactly the four required outputs.
    assert [row["path"] for row in receipt["files"]] == list(RECEIPT_REQUIRED)
    # Non-negotiable console framing: receipt created, CLI-only, DSH still D3,
    # and not a board pass.
    assert "finalize.json" in captured.out
    assert "收据" in captured.out
    assert "delivery-content" in captured.out
    assert "DSH" in captured.out and "D3" in captured.out
    assert "不是板级通过" in captured.out
    # No timestamp, no random id, no absolute path, no board-level pass field.
    raw = (out / FINALIZE_RECEIPT).read_text(encoding="utf-8")
    assert str(tmp_path) not in raw
    lowered = raw.lower()
    assert "timestamp" not in lowered
    assert "generatedat" not in lowered
    assert "boardpass" not in lowered.replace(" ", "")
    assert '"passed"' not in lowered

    # Reading it back is not a verification entry point: the CLI's only flag is
    # --out, and nothing consumes an existing receipt as authority.
    parser = cli.build_parser()
    args = parser.parse_args(["review", "finalize", "--out", str(out)])
    assert getattr(args, "receipt", None) is None


def test_receipt_covers_optional_sidecars_and_every_cited_artifact(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    (out / "canvas").mkdir()
    (out / "canvas" / "p1.png").write_bytes(b"anonymous-png")
    (out / "captures").mkdir()
    (out / "captures" / "live.json").write_bytes(b'{"live": true}\n')
    (out / "captures" / "netlist_raw.json").write_bytes(b'{"nets": []}\n')

    # The same file cited by two machine fields is one path in the receipt; the
    # channel, the live capture and its captureFile are each tracked once.
    _add_citation(out, "canvas", {"file": "canvas/p1.png", "kind": "image"})
    _add_citation(out, "channel", {"file": "canvas/p1.png", "kind": "image"})
    # The same PNG cited by the same channel again, this time by its absolute
    # path inside --out: de-duplication is on the resolved path, and the receipt
    # still names it by the one relative POSIX path.
    written = json.loads((out / "report.json").read_text(encoding="utf-8"))
    written["evidence"]["channels"]["schematicImage"]["artifacts"].append(
        {"file": str((out / "canvas" / "p1.png").resolve()), "kind": "image"}
    )
    _rewrite_report(out, written)
    _add_citation(
        out, "live-channel", {"file": "captures/netlist_raw.json", "kind": "netlist"}
    )
    _add_citation(
        out,
        "capture-artifacts",
        {
            "file": "captures/netlist_raw.json",
            "kind": "netlist",
            "channel": "liveSchematic",
        },
    )
    _add_citation(
        out, "capture-file", {"file": "captures/live.json", "kind": "live-capture"}
    )
    (out / "architecture.md").write_text("anonymous architecture\n", encoding="utf-8")
    (out / "design-intent.md").write_text("anonymous intent\n", encoding="utf-8")
    (out / SIDECAR).write_text(
        json.dumps({"version": 1, "entries": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "live-evidence.json").write_text(
        json.dumps({"schema": "boardwise.live-evidence/1"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert _run(out) == 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    receipt = _assert_receipt_shape(out)
    paths = [row["path"] for row in receipt["files"]]
    expected = set(RECEIPT_REQUIRED) | {
        "warning-triage.json",
        "live-evidence.json",
        "architecture.md",
        "design-intent.md",
        "canvas/p1.png",
        "captures/live.json",
        "captures/netlist_raw.json",
    }
    assert expected <= set(paths), expected - set(paths)
    # Dedupe really happened: the twice-cited files appear once each.
    assert paths.count("canvas/p1.png") == 1
    assert paths.count("captures/netlist_raw.json") == 1
    # Sorting is over the relative POSIX path, and every row hash is the file's.
    assert paths == sorted(paths)
    for name in expected:
        assert _receipt_sha(receipt, name) == hashlib.sha256(
            (out / name).read_bytes()
        ).hexdigest()


def test_receipt_hashes_the_final_synced_bytes_not_declared_values(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    summary_path = out / "review-summary.md"
    stale = summary_path.read_bytes().replace(b"0.5.0", b"0.4.0", 1)
    assert stale != summary_path.read_bytes()
    summary_path.write_bytes(stale)
    stale_sha = hashlib.sha256(stale).hexdigest()

    assert _run(out) == 0
    capsys.readouterr()
    final = summary_path.read_bytes()
    assert b"0.4.0" not in final and b"0.5.0" in final
    receipt = _assert_receipt_shape(out)
    # The receipt was signed after the sync: it hashes the two-machine-section
    # sync's output, not the stale bytes the human's editor left.
    assert _receipt_sha(receipt, "review-summary.md") == hashlib.sha256(final).hexdigest()
    assert _receipt_sha(receipt, "review-summary.md") != stale_sha


def test_success_replaces_a_handwritten_receipt_without_trusting_it(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    (out / FINALIZE_RECEIPT).write_text(
        '{"schema": "boardwise.review-finalize/1", "ok": true, '
        '"scope": "board-pass", "files": []}\n',
        encoding="utf-8",
    )
    assert _run(out) == 0
    capsys.readouterr()
    receipt = _assert_receipt_shape(out)
    assert receipt["scope"] == RECEIPT_SCOPE
    assert FINALIZE_RECEIPT not in [row["path"] for row in receipt["files"]]
    # A second run replaces it with the same deterministic bytes.
    first = (out / FINALIZE_RECEIPT).read_bytes()
    assert _run(out) == 0
    capsys.readouterr()
    assert (out / FINALIZE_RECEIPT).read_bytes() == first


def test_handwritten_receipt_grants_no_session_privilege(tmp_path, capsys):
    """A hand-written `ok: true` changes nothing: no entry point reads it."""
    out, written = _make_review(tmp_path)
    handwritten = (
        '{"schema": "boardwise.review-finalize/1", "ok": true, '
        '"scope": "delivery-content", "files": []}\n'
    )
    (out / FINALIZE_RECEIPT).write_text(handwritten, encoding="utf-8")
    stale = copy.deepcopy(written)
    stale["renderErrors"] = "not-a-list"
    _rewrite_report(out, stale)

    assert _run(out) == 1
    captured = capsys.readouterr()
    assert "finalize validation: failed" in captured.out
    assert "render-errors" in _codes(captured.out)
    # The failure did not rewrite the hand-written file and signed nothing new.
    assert (out / FINALIZE_RECEIPT).read_text(encoding="utf-8") == handwritten


# ---- failures and exceptions: exit 2, no receipt, honest about partial sync -


def _assert_post_gate_failure(out: Path, capsys) -> str:
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert not (out / FINALIZE_RECEIPT).exists()
    # The writers may already have run: never claim the whole directory is
    # untouched after the gate opened.
    assert "一个字没写" not in captured.err
    assert "部分" in captured.err
    return captured.err


def test_writer_failure_is_two_and_signs_no_receipt(tmp_path, capsys, monkeypatch):
    out, _written = _make_review(tmp_path)

    def explode(*_args, **_kwargs):
        raise OSError("synthetic markdown writer")

    monkeypatch.setattr(cli, "_write_checkup_markdown", explode)
    assert _run(out) == 2
    _assert_post_gate_failure(out, capsys)


def test_summary_writer_failure_is_two_and_signs_no_receipt(
    tmp_path, capsys, monkeypatch
):
    out, _written = _make_review(tmp_path)
    summary_path = out / "review-summary.md"
    stale = summary_path.read_bytes().replace(b"0.5.0", b"0.4.0", 1)
    assert stale != summary_path.read_bytes()
    summary_path.write_bytes(stale)

    original = Path.write_bytes

    def guarded(self, data):
        if self == summary_path:
            raise OSError("synthetic summary writer")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", guarded)
    assert _run(out) == 2
    _assert_post_gate_failure(out, capsys)


def test_missing_required_output_after_writers_is_two_and_signs_no_receipt(
    tmp_path, capsys, monkeypatch
):
    out, _written = _make_review(tmp_path)
    # A writer that silently produces nothing: pre-gate absence of report.md is
    # ordinary (this command writes it), so the gate opens — and the receipt
    # rebuild must then refuse to sign a delivery missing one of its four.
    monkeypatch.setattr(cli, "_write_checkup_markdown", lambda *_a, **_k: None)
    assert _run(out) == 2
    err = _assert_post_gate_failure(out, capsys)
    assert "report.md" in err


def test_receipt_hash_failure_is_two_and_signs_no_receipt(
    tmp_path, capsys, monkeypatch
):
    out, _written = _make_review(tmp_path)

    def explode(_path):
        raise OSError("synthetic hash failure")

    monkeypatch.setattr(cli, "_review_read_artifact_sha256", explode)
    assert _run(out) == 2
    _assert_post_gate_failure(out, capsys)


def test_post_write_artifact_recheck_failure_is_two_and_signs_no_receipt(
    tmp_path, capsys, monkeypatch
):
    out, _written = _make_review(tmp_path)
    original = cli._review_read_artifacts_payload
    calls: list[int] = []

    def flaky(payload, out_dir):
        calls.append(1)
        if len(calls) > 1:
            raise ValueError("synthetic post-write recheck")
        return original(payload, out_dir)

    monkeypatch.setattr(cli, "_review_read_artifacts_payload", flaky)
    assert _run(out) == 2
    # The artifacts were projected once before the gate and re-proved once after
    # the writes — the receipt is not signed from the pre-write answer.
    assert len(calls) == 2
    _assert_post_gate_failure(out, capsys)


def test_receipt_rename_failure_leaves_no_half_receipt(
    tmp_path, capsys, monkeypatch
):
    out, _written = _make_review(tmp_path)
    original = os.replace

    def explode(src, dst):
        if Path(dst).name == FINALIZE_RECEIPT:
            raise OSError("synthetic receipt rename")
        return original(src, dst)

    monkeypatch.setattr(os, "replace", explode)
    assert _run(out) == 2
    _assert_post_gate_failure(out, capsys)


def test_optional_sidecar_that_is_not_a_regular_file_is_two_and_signs_no_receipt(
    tmp_path, capsys
):
    out, _written = _make_review(tmp_path)
    # An optional file that is present but not a regular file cannot be hashed
    # into a receipt; it is refused after the writers, with no receipt.
    (out / "architecture.md").mkdir()
    assert _run(out) == 2
    err = _assert_post_gate_failure(out, capsys)
    assert "architecture.md" in err
