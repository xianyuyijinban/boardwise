"""191A: `parts accept-unknown` — the datasheet gate's second exit,真通道.

186 documented a clearing channel the CLI did not have: 「工程师明示
accept-unknown」. Everything else about the gate was already there (the shelf's
verified facts close it; a reviewer's mark *adds* to it), so a part whose unknowns
are acceptable — a jumper, a parameter the engineer characterised by other means —
either blocked `completion.verdict` at `incomplete` forever or got a datasheet
nobody needed.

What this file pins, one section each:

* **the contract** — `acceptedUnknown[]` is an *added* top-level key (the schema
  stays closed: an unknown key inside an entry, or a missing `reason`, is refused
  by name), it is written **only when non-empty** (every contract written before
  this batch keeps its bytes and its digest), and the clerk is idempotent per
  `(part, board)` with a case-folded token;
* **the command** — `boardwise parts accept-unknown <MPN|designator> --reason …
  [--board …] [--revoke]` writes the *same file the next `checkup` reads* (the
  user-level default for the project's `projectUuid`), creates it when missing,
  and refuses (exit 2) a missing `--reason` or a `--revoke` with nothing to revoke;
* **the report** — the part leaves `unreviewed_parts` for `accepted_unknown[]`,
  `completion.verdict` stops being `incomplete` **because of it** (it becomes
  `complete-with-open-items`: the part was not judged, it was accepted), and
  `summary.conclusion` says 「另有 N 颗工程师接受未审」 — the batch's own wording.
  With `--revoke` the part is back on the 未审 list;
* **the stale path** — an acceptance whose part the drawing no longer has is kept
  and marked (`stale: true`, a row in the report, a line in `report.md`, a
  `staleEntries` row in the `intent` section), never deleted and never a crash
  (189B's path, one section over).

The fixture is the tracked synthetic/DIY board and the shelf is built beside the
test; the CLI is the real one. R4b: no real project or part name is typed here —
the designator is taken from the board's own unreviewed list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.model import Component, DesignModel
from boardwise.core.parts import PartLibrary, load_parts, save_parts
from boardwise.engines.checkup import (
    STATE_ACCEPTED,
    STATE_ACCEPTED_NOT_UNREVIEWED,
    STATE_ACCEPTED_STALE,
    STATE_ACCEPTED_STALE_ELSEWHERE,
    UNREVIEWED_CLEARING_NOTE,
    accepted_unknown_counts,
    accepted_unknown_section,
    render_report_markdown,
    unreviewed_parts,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "tests" / "fixtures" / "llc_board.epro2"
REASON = "这颗的未知我接受：参数已用别的手段量过，不需要手册"


# --------------------------------------------------------------------------
# helpers: a board's own part token, and an empty shelf beside the test
# --------------------------------------------------------------------------


def _shelf(tmp_path: Path) -> Path:
    """An **empty** shelf: nothing on it can judge anything (the empty-gate run).

    Written through the real writer so the loader accepts it — a hand-rolled
    `{"parts": []}` fails the `kind` marker and would quietly turn the run into
    "no shelf at all" (a different reading, and not the one under test).
    """
    path = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=[]), path)
    return path


def _first_unreviewed(board: Path, shelf: Path) -> tuple[str, str]:
    """``(designator, mpn)`` of the first U-prefix part the shelf cannot judge."""
    model, _board = cli._load_model(board, view="schematic")
    rows = unreviewed_parts(model, library=load_parts(shelf))
    for row in rows:
        designator = str(row.get("designator") or "")
        if designator.startswith("U"):
            return designator, str(row.get("mpn") or "")
    pytest.skip("the fixture board no longer holds an unreviewed U-prefix part")


def _contract(tmp_path: Path) -> Path:
    return tmp_path / "home" / "design-intent" / "file-23e5c70d38bf.json"


def _checkup(tmp_path: Path, shelf: Path, out: str, *extra: str) -> dict:
    code = cli.main([
        "checkup", "--file", str(BOARD), "--out", str(tmp_path / out),
        "--library", str(shelf), *extra,
    ])
    assert code in (0, 1, 3), f"checkup exited {code}"
    return json.loads(
        (tmp_path / out / "report.json").read_text(encoding="utf-8")
    )


def _accept(tmp_path: Path, shelf: Path, token: str, *extra: str) -> int:
    return cli.main([
        "parts", "accept-unknown", token, "--reason", REASON, "--who", "tester",
        "--file", str(BOARD), "--library", str(shelf), *extra,
    ])


# --------------------------------------------------------------------------
# the contract: the schema is closed, added to, and never loses an answer
# --------------------------------------------------------------------------


def test_an_empty_document_does_not_grow_the_key_it_has_nothing_to_say_about():
    """Rule 1 one level up: a contract written before 191A keeps its exact bytes.

    The whole reason this matters is that several rules pin a contract's sha256 as
    the source of their reading — an always-present empty `acceptedUnknown` would
    have moved every existing document's digest for a section it does not have.
    """
    empty = di.DesignIntent()
    written = empty.to_jsonable()
    assert set(written) == {"intentVersion", "requirements", "blocks", "decisions"}
    assert written == di.parse_json(di.render_json(empty)).to_jsonable()

    updated, change = di.accept_unknown(
        empty, "U7", reason="接受", who="tester", when="2026-10-17T10:00:00+0800"
    )
    assert "new acceptance" in change
    payload = updated.to_jsonable()
    assert payload["acceptedUnknown"] == [
        {
            "part": "U7",
            "reason": "接受",
            "who": "tester",
            "when": "2026-10-17T10:00:00+0800",
            "provenance": "user_stated",
        }
    ]
    assert empty.to_jsonable() == written, "the merge never mutates its input"
    assert updated.sha256() != empty.sha256()


def test_an_acceptance_without_a_reason_is_refused_by_the_reader_and_the_writer():
    """The one field the channel exists for: a skipped judgement **stated**.

    Both halves are asserted because both are load-bearing: the writer refuses to
    record one (so the CLI's exit 2 is not the only guard) and the *reader* refuses
    a hand-written file that carries none — an acceptance nobody can read the
    reason of would be the silent green light this batch forbids.
    """
    document = di.DesignIntent()
    with pytest.raises(di.DesignIntentError, match="--reason"):
        di.accept_unknown(document, "U7", reason="   ")
    with pytest.raises(di.DesignIntentError, match="empty"):
        di.accept_unknown(document, "", reason=REASON)

    hand_written = (
        '{"intentVersion": 1, "acceptedUnknown": [{"part": "U7"}]}'
    )
    with pytest.raises(di.DesignIntentError, match=r"acceptedUnknown\[0\]\.reason"):
        di.parse_json(hand_written)

    unknown_key = (
        '{"intentVersion": 1, "acceptedUnknown": '
        '[{"part": "U7", "reason": "接受", "becase": "x"}]}'
    )
    with pytest.raises(di.DesignIntentError, match=r"unknown key\(s\) becase"):
        di.parse_json(unknown_key)


def test_the_same_acceptance_twice_is_one_entry_and_revoking_removes_it():
    """Idempotent per `(part, board)`, with the token compared case-folded.

    The token is compared folded but **stored as written** — the update keeps the
    spelling of the answer that arrived last, which is why the third call below
    asks with the same spelling to get the byte-identical answer.
    """
    document = di.DesignIntent()
    once, _ = di.accept_unknown(document, "U7", reason="第一次", who="a", when="t1")
    twice, change = di.accept_unknown(once, "u7", reason="改个理由", who="b", when="t2")
    assert len(twice.accepted_unknown) == 1
    assert "已存在，已更新" in change
    entry = twice.accepted_unknown[0]
    assert (entry.part, entry.reason, entry.who) == ("u7", "改个理由", "b")
    assert entry.provenance == di.PROVENANCE_USER_STATED

    same, change = di.accept_unknown(twice, "u7", reason="改个理由", who="b", when="t2")
    assert len(same.accepted_unknown) == 1 and "逐字相同" in change

    # Scoping: an acceptance for another board is a different answer, not a
    # rewrite of this one.
    other, _ = di.accept_unknown(twice, "u7", reason="只在 Board2 接受", board="Board2")
    assert len(other.accepted_unknown) == 2

    revoked, change = di.revoke_unknown(other, "U7", board="Board2")
    assert "撤销" in change and len(revoked.accepted_unknown) == 1
    assert revoked.accepted_unknown[0].board == ""

    untouched, change = di.revoke_unknown(revoked, "U7", board="Board2")
    assert change == "" and untouched.to_jsonable() == revoked.to_jsonable()

    # Scoping: an acceptance for another board is a different answer, not a
    # rewrite of this one.
    other, _ = di.accept_unknown(twice, "U7", reason="只在 Board2 接受", board="Board2")
    assert len(other.accepted_unknown) == 2

    revoked, change = di.revoke_unknown(other, "U7", board="Board2")
    assert "撤销" in change and len(revoked.accepted_unknown) == 1
    assert revoked.accepted_unknown[0].board == ""

    untouched, change = di.revoke_unknown(revoked, "U7", board="Board2")
    assert change == "" and untouched.to_jsonable() == revoked.to_jsonable()


def test_regenerating_the_contract_keeps_every_acceptance_byte_for_byte():
    """`merge` is the regenerator (`arch --intent`), and rule 4 is absolute."""
    document, _ = di.accept_unknown(
        di.DesignIntent(), "U7", reason=REASON, who="tester", when="2026-10-17T10:00:00+0800"
    )
    merged, facts = di.merge(document, [])
    assert [entry.to_jsonable() for entry in merged.accepted_unknown] == [
        entry.to_jsonable() for entry in document.accepted_unknown
    ]
    # …and it is not counted as an intent slot, nor does it weaken the document's
    # provenance reading: an acceptance is not a requirement about the board.
    assert facts["slots"] == 0 and facts["provenance"] == document.provenance


# --------------------------------------------------------------------------
# the command: it writes the file the next checkup reads
# --------------------------------------------------------------------------


def test_the_command_writes_the_default_contract_and_refuses_an_empty_reason(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    shelf = _shelf(tmp_path)
    designator, _mpn = _first_unreviewed(BOARD, shelf)
    path = _contract(tmp_path)
    assert not path.exists()

    assert _accept(tmp_path, shelf, designator) == 0
    capsys.readouterr()
    assert path.is_file(), "the default path is the one checkup resolves"
    document = di.DesignIntent.load(path)
    assert [entry.part for entry in document.accepted_unknown] == [designator]
    assert document.accepted_unknown[0].reason == REASON
    assert document.accepted_unknown[0].who == "tester"
    assert document.accepted_unknown[0].when, "the audit clock is written"

    # No reason → exit 2 and the file is not touched (byte-for-byte).
    before = path.read_bytes()
    assert cli.main([
        "parts", "accept-unknown", designator, "--file", str(BOARD),
        "--library", str(shelf),
    ]) == 2
    assert path.read_bytes() == before

    # Neither --file nor --intent → exit 2: there is no contract to guess at.
    assert cli.main(["parts", "accept-unknown", designator, "--reason", REASON]) == 2

    # Revoking something that is not there is a **missing target**, not a
    # successful cleanup (R3): exit 2, file unchanged.
    assert cli.main([
        "parts", "accept-unknown", "NOSUCH3", "--revoke", "--intent", str(path),
    ]) == 2
    assert path.read_bytes() == before


def test_revoking_puts_the_part_back_on_the_unreviewed_list(tmp_path, monkeypatch, capsys):
    """Accept → 未审 loses the row; revoke → it is back (the batch's own test)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    shelf = _shelf(tmp_path)
    designator, _mpn = _first_unreviewed(BOARD, shelf)

    before = _checkup(tmp_path, shelf, "out-before")
    listed = {row["designator"] for row in before["unreviewed_parts"]}
    assert designator in listed

    assert _accept(tmp_path, shelf, designator) == 0
    capsys.readouterr()
    accepted = _checkup(tmp_path, shelf, "out-accepted")
    assert designator not in {row["designator"] for row in accepted["unreviewed_parts"]}
    assert {row["designator"] for row in accepted["unreviewed_parts"]} == listed - {designator}
    rows = accepted["accepted_unknown"]
    assert [row["part"] for row in rows] == [designator]
    assert rows[0]["state"] == STATE_ACCEPTED and rows[0]["stale"] is False
    assert rows[0]["reason"] == REASON and rows[0]["who"] == "tester"
    # The worklist is the other half of the same statement: the row left it too.
    assert designator not in {row["part"] for row in accepted["needs_datasheet"]}
    assert accepted["completion"]["acceptedUnknown"] == 1

    assert cli.main([
        "parts", "accept-unknown", designator, "--revoke", "--intent", str(_contract(tmp_path)),
    ]) == 0
    capsys.readouterr()
    after = _checkup(tmp_path, shelf, "out-after")
    assert {row["designator"] for row in after["unreviewed_parts"]} == listed
    assert after["accepted_unknown"] == []
    assert after["completion"]["acceptedUnknown"] == 0


# --------------------------------------------------------------------------
# the verdict and the conclusion: not silent, and not a pass either
# --------------------------------------------------------------------------


def test_the_accepted_part_moves_the_verdict_off_incomplete_and_the_line_says_how_many(
    tmp_path, monkeypatch, capsys
):
    """The acceptance is the **only** thing that changes here.

    `unreviewed_parts` and the triage slots are pinned to one row and zero so the
    two runs differ by exactly the contract — which is what makes the verdict
    movement, the exit code and the sentence readable as one cause.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    shelf = _shelf(tmp_path)
    designator, mpn = _first_unreviewed(BOARD, shelf)
    row = {
        "designator": designator,
        "name": "",
        "value": "",
        "footprint": "",
        "mpn": mpn,
        "supplier": "",
        "reasons": ["货架没有这颗料"],
        "question": "这颗料是什么？",
        "isIc": True,
        "onShelf": False,
        "shelfKey": "",
        "shelfMatchedBy": "",
        "factsVerified": None,
        "factsPresent": [],
        "missingFacts": [],
        "channels": {},
    }
    monkeypatch.setattr(cli, "unreviewed_parts", lambda *a, **kw: [dict(row)])
    monkeypatch.setattr(cli, "warning_triage_slots", lambda **kw: [])

    before = _checkup(tmp_path, shelf, "out-before")
    assert before["completion"]["verdict"] == "incomplete"
    assert before["summary"]["conclusion"] == (
        "DRC/连接性已审，1 颗器件缺手册未审"
    ) or before["summary"]["conclusion"].startswith("DRC/连接性已审，1 颗器件缺手册未审")
    assert "接受未审" not in before["summary"]["conclusion"]

    assert _accept(tmp_path, shelf, designator) == 0
    capsys.readouterr()
    after = _checkup(tmp_path, shelf, "out-after")
    assert after["unreviewed_parts"] == []
    # Not `complete`: nobody judged the part — an open item is a statement with a
    # hole named in it, which is exactly what this is.
    assert after["completion"]["verdict"] == "complete-with-open-items"
    assert any("接受未审" in reason for reason in after["completion"]["verdictWhy"])
    assert after["summary"]["exitCode"] == 0, "073's mapping: only `incomplete` raises 0→3"
    assert cli.main([
        "checkup", "--file", str(BOARD), "--out", str(tmp_path / "out-after2"),
        "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    line = after["summary"]["conclusion"]
    assert "另有 1 颗工程师接受未审" in line, line
    assert "不是审过" in line, "the sentence must not read as a pass"
    assert after["summary"]["mayClaimPassed"] is True, (
        "053's narrow field answers 'did the datasheet gate leave an *unaccounted* "
        "part?' — an accepted one is accounted for (186 lists this as a clearing "
        "channel); the wide answer is completion.verdict, which stays open"
    )
    board_line = after["board_report"]["verdict"]
    assert board_line["canShip"] is False and "接受未审" in board_line["line"]
    assert after["conclusion"]["mayQuotePassed"] is False
    assert "接受未审" in after["conclusion"]["oneLiner"]

    markdown = (tmp_path / "out-after" / "report.md").read_text(encoding="utf-8")
    assert "## 工程师接受未审（accepted_unknown：1）" in markdown
    assert f"| {designator} | 本轮接受（已从 未审 移出）" in markdown
    assert REASON in markdown


def test_the_conclusion_is_exactly_wu_error_exactly_when_the_verdict_is_complete():
    """#21's invariant, with 191A's gate in the product (the 039c cross-check).

    The clause and the verdict must be one arithmetic: if the accepted count caps
    the verdict at `complete-with-open-items`, the quotable sentence may not be a
    bare 「无 ERROR」 — and if it were 0, the sentence must not grow a clause about
    parts nobody accepted.
    """
    import itertools

    from boardwise.cli import (
        _completion_coverage_gates,
        _completion_section,
        _conclusion_skeleton_gates,
        _review_conclusion,
    )
    from boardwise.engines.checkup import TRIGGER_MARKED, marked_parts

    model = DesignModel()
    checked = 0
    for errors, unreviewed, marked, accepted in itertools.product(
        (0, 1), (0, 2), (0, 1), (0, 2)
    ):
        summary = {"errorCount": errors, "countsIncomplete": False}
        unreviewed_rows = [{"designator": f"U{i}"} for i in range(unreviewed)]
        marked_rows = [{"trigger": TRIGGER_MARKED, "part": f"U{i}"} for i in range(marked)]
        accepted_rows = [
            {
                "part": f"U9{i}",
                "state": STATE_ACCEPTED,
                "reason": "接受",
                "stale": False,
            }
            for i in range(accepted)
        ]
        completion = _completion_section(
            model=model,
            summary=summary,
            unreviewed=unreviewed_rows,
            triage=[],
            architecture={"totals": {"slots": 8, "filled": 8, "stale": 0}},
            needs_datasheet=marked_rows,
            accepted=accepted_rows,
        )
        conclusion = _review_conclusion(
            summary,
            unreviewed_count=len(unreviewed_rows),
            marked_count=len(marked_parts(marked_rows)),
            pending_triage=int(completion["warningsPendingTriage"] or 0),
            accepted_unknown=int(completion["acceptedUnknown"] or 0),
            **_conclusion_skeleton_gates(
                architecture={"totals": {"slots": 8, "filled": 8, "stale": 0}},
                completion=completion,
            ),
            **_completion_coverage_gates(completion=completion),
        )
        checked += 1
        assert (conclusion == "无 ERROR") == (completion["verdict"] == "complete"), (
            f"errors={errors} unreviewed={unreviewed} marked={marked} "
            f"accepted={accepted}: conclusion={conclusion!r} "
            f"verdict={completion['verdict']!r}"
        )
        if accepted:
            assert f"另有 {accepted} 颗工程师接受未审" in conclusion
    assert checked == 2 ** 4


def test_an_acceptance_that_skipped_nothing_does_not_open_the_verdict(
    tmp_path, monkeypatch, capsys
):
    """Only the rows that actually left the 未审 list gate.

    A `not-unreviewed` acceptance is reported (the engineer's answer is not thrown
    away) but it owes nothing: nothing was skipped, so it can neither cap the
    verdict nor make the conclusion claim an acceptance.
    """
    model = DesignModel()
    completion = cli._completion_section(
        model=model,
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 0, "filled": 0, "stale": 0}},
        accepted=[{
            "part": "U9",
            "state": STATE_ACCEPTED_NOT_UNREVIEWED,
            "reason": "接受",
            "stale": False,
        }],
    )
    assert completion["verdict"] == "complete"
    assert completion["acceptedUnknown"] == 0
    assert completion["acceptedUnknownTotal"] == 1
    assert "接受未审" not in "；".join(completion["verdictWhy"])


# --------------------------------------------------------------------------
# the stale path: kept, marked, reported — and never a crash
# --------------------------------------------------------------------------


def test_an_acceptance_whose_part_left_the_board_is_marked_not_deleted(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    shelf = _shelf(tmp_path)
    path = _contract(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document, _ = di.accept_unknown(
        di.DesignIntent(), "UNSOLDERED9",
        reason="这版先不装", who="tester", when="2026-10-17T10:00:00+0800",
    )
    path.write_text(di.render_json(document), encoding="utf-8")

    report = _checkup(tmp_path, shelf, "out-stale")
    rows = report["accepted_unknown"]
    assert [row["part"] for row in rows] == ["UNSOLDERED9"]
    assert rows[0]["state"] == STATE_ACCEPTED_STALE and rows[0]["stale"] is True
    assert "图纸上没有这颗件" in rows[0]["why"]
    # It moved nothing: no unreviewed row, no verdict consequence.
    assert report["completion"]["acceptedUnknown"] == 0
    assert report["completion"]["acceptedUnknownStale"] == 1
    assert report["summary"]["conclusion"].startswith("DRC/连接性已审")
    assert "接受未审" not in report["summary"]["conclusion"].split("；另有")[-1]
    # 189B's path, one section over: a `{section, object}` row in the intent
    # section, rendered by the renderer that already knows this shape.
    intent = report["intent"]
    assert {"section": "acceptedUnknown", "object": "UNSOLDERED9"} in intent["staleEntries"]
    # 192B ⑨: the standing total carries the folded acceptance mark; the delta
    # (this regeneration's own marks) does not — that pass marked nothing.
    assert intent["totals"]["staleTotal"] >= 1
    assert intent["totals"]["newlyStale"] == 0
    markdown = (tmp_path / "out-stale" / "report.md").read_text(encoding="utf-8")
    assert "合同里记着、图纸里已没有的件（1，不删只标）" in markdown
    assert "`UNSOLDERED9`（acceptedUnknown）—— 值保留，只标 stale" in markdown
    # The contract itself is untouched by the run: reading never writes.
    assert di.DesignIntent.load(path).accepted_unknown[0].reason == "这版先不装"


def test_the_engine_pairs_a_row_by_designator_or_mpn_and_honours_the_board():
    """`accepted_unknown_section` is the one pairing rule, exercised directly.

    Three properties the report depends on: either token matches (the command's
    own `<MPN|designator>`), an acceptance that names no board accepts it wherever
    it sits, and one that names a board only moves the placement on that board —
    the other board's row stays on the 未审 list, with the acceptance reported as
    `not-unreviewed` rather than silently dropped.
    """
    model = DesignModel()
    model.components["U1"] = Component(
        uid="uid-u1", designator="U1", mpn="MPN-A", lcsc_part="C1"
    )
    model.components["U2"] = Component(
        uid="uid-u2", designator="U2", mpn="MPN-B", lcsc_part="C2"
    )
    rows = [
        {
            "designator": "U1", "mpn": "MPN-A", "reasons": ["货架没有这颗料"],
            "boards": ["Board1"],
        },
        {
            "designator": "U2", "mpn": "MPN-B", "reasons": ["货架没有这颗料"],
            "boards": ["Board2"],
        },
    ]
    by_mpn = di.IntentAccepted(part="mpn-a", reason="接受", who="t", when="t")
    remaining, accepted = accepted_unknown_section(model, rows, [by_mpn])
    assert [row["designator"] for row in remaining] == ["U2"]
    assert [row["part"] for row in accepted] == ["mpn-a"]
    assert accepted[0]["state"] == STATE_ACCEPTED
    assert accepted[0]["matchedBy"] == "mpn" and accepted[0]["mpn"] == "MPN-A"

    scoped = di.IntentAccepted(
        part="U2", reason="只在 B1 接受", who="t", when="t", board="Board1"
    )
    remaining, accepted = accepted_unknown_section(model, rows, [scoped])
    assert sorted(row["designator"] for row in remaining) == ["U1", "U2"], (
        "the board scope did not move U2 — it is on Board2"
    )
    assert accepted[0]["state"] == STATE_ACCEPTED_NOT_UNREVIEWED
    assert accepted[0]["stale"] is False

    # 192B ⑦: `stale` split in two — a part that is nowhere on the drawing and one
    # that is only not on the board the acceptance named send the reader to two
    # different places (a contract entry to revoke vs a board name to fix).
    counts = accepted_unknown_counts(accepted)
    assert counts == {
        STATE_ACCEPTED: 0, STATE_ACCEPTED_NOT_UNREVIEWED: 1,
        STATE_ACCEPTED_STALE: 0, STATE_ACCEPTED_STALE_ELSEWHERE: 0,
    }
    assert accepted_unknown_counts([]) == {
        STATE_ACCEPTED: 0, STATE_ACCEPTED_NOT_UNREVIEWED: 0,
        STATE_ACCEPTED_STALE: 0, STATE_ACCEPTED_STALE_ELSEWHERE: 0,
    }


# --------------------------------------------------------------------------
# 191C 遗留（191A 交付）：netIdNote 也要到人读的 Markdown 上
# --------------------------------------------------------------------------


def test_the_lost_net_ids_are_rendered_on_the_human_report():
    """`pcb_review.boards[].netIdNote` reaches `report.md` / `board-report.md`.

    191C wrote the note into `report.json` and stopped there — the renderer carried
    `outlineNote` (bug98's channel) and not this one, so a reader of the Markdown
    saw a board whose nets all have names while the name-driven checks (the
    differential-pair inventory, the per-rail decap bands) could not see some of
    them. Same channel, same place, same wording: the note rides the board link
    (`_board_links`) into the board section and is printed under the heading.

    Both link shapes are exercised, because they are two code paths: a PCB
    document linked to a schematic board by `boardUuid`, and one standing alone.
    """
    from boardwise.engines.checkup import board_report_section, render_board_report
    from boardwise.engines.pcbreview import run_pcb_review

    fixture = ROOT / "tests" / "fixtures" / "kicad_min" / "kicad_bare_net.kicad_pcb"
    _findings, pcb_section = run_pcb_review(fixture)
    entry = pcb_section["boards"][0]
    note = entry["netIdNote"]
    assert note, "the fixture is the bare-net shape; 191C's disclosure must be there"

    linked = {
        "summary": {"errorCount": 0, "errors": [], "exitCode": 0, "mayClaimPassed": True},
        "findings": [],
        "modules": [],
        "model": {
            "boards": [{
                "uuid": "board-1", "title": "Board1",
                "components": entry["components"], "pages": [],
            }],
        },
        # The KiCad entry itself carries no `boardUuid` (a `.kicad_pcb` names no
        # schematic board), so the link is injected here: the note has to survive
        # **both** `_board_links` branches, and the first one is the one an
        # `.epro2`'s PCB document takes.
        "pcb_review": {**pcb_section, "boards": [{**entry, "boardUuid": "board-1"}]},
    }
    section = board_report_section(linked, modules=[])
    assert section["boards"][0]["board"] == "Board1"
    assert section["boards"][0]["netIdNote"] == note
    markdown = render_board_report(linked, section)
    assert f"> ⚠️ {note}" in markdown

    # A PCB document with no schematic board to link to keeps its own entry — the
    # second `_board_links` branch, which had the same hole.
    standalone = dict(linked, model={}, pcb_review=pcb_section)
    section = board_report_section(standalone, modules=[])
    assert any(board.get("netIdNote") == note for board in section["boards"])
    assert f"> ⚠️ {note}" in render_board_report(standalone, section)

    # And a board that lost nothing gains no line (absent, not empty — 钉 5).
    named_fixture = ROOT / "tests" / "fixtures" / "kicad_min" / "kicad_min.kicad_pcb"
    _f, named_section = run_pcb_review(named_fixture)
    assert "netIdNote" not in named_section["boards"][0]
    clean = dict(linked, pcb_review=named_section)
    clean_section = board_report_section(clean, modules=[])
    # The board section carries the key with a `None` (the same shape `outlineNote`
    # has); what must not appear is the **line**.
    assert not clean_section["boards"][0].get("netIdNote")
    assert "网序号查不到名字" not in render_board_report(clean, clean_section)


# --------------------------------------------------------------------------
# the instruction the reader follows
# --------------------------------------------------------------------------


def test_the_unreviewed_section_names_the_channel_that_now_exists():
    """186's line said this CLI had no `accept-unknown`; 191A appended it.

    Asserted as a **prefix** (187b's rule: the constant may only grow at the end)
    plus the new command's own spelling, so the next batch cannot quietly rewrite
    the older instruction while adding to it.
    """
    assert "parts add" in UNREVIEWED_CLEARING_NOTE
    assert "need-datasheet" in UNREVIEWED_CLEARING_NOTE
    assert "parts accept-unknown" in UNREVIEWED_CLEARING_NOTE
    assert "--revoke" in UNREVIEWED_CLEARING_NOTE
    report = {
        "summary": {"unreviewedParts": 1},
        "unreviewed_parts": [{"designator": "U1"}],
        "accepted_unknown": [],
    }
    assert "parts accept-unknown" in render_report_markdown(report)
