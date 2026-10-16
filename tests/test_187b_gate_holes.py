"""187B: the four release-gate holes 186/185 left open.

One file, four subjects, each with the reproducer the audit swarm measured
(swarm agent-344's probes in ``.tmp_audit186/``; agent-343's report for 185-中1):

* **186-H1** — four PCB rules still read the shelf by MPN/C-number only, so a
  board part whose only identity is its device name was judged by `checkup`'s
  gate and *not* by the rules. Fixed by routing them through
  `resolve_component_facts`; pinned by a grep-level invariant over ``rules/``.
* **186-H2** — on a frozen exe the write path (`parts add`) and the read path
  (rules / checkup) were two different files, so the report's own clearing
  instruction was a no-op on the artifact a friend runs.
* **hygiene 中4/中5/中6** — the sensitive-word gate could not read UTF-16/GBK
  files (silently), had no baseline (permanently red once switched on), and cost
  one full scan per word.
* **185-中1** — the folded `needs_datasheet[]` row dropped board identity, and
  `needsDatasheetTotal` read as "one part, one datasheet" in a project where one
  designator is a different part on every board.

Fixtures are read-only; nothing here talks to a bridge or an editor.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from boardwise import cli, resources
from boardwise.engines.checkup import (
    UNREVIEWED_CLEARING_NOTE,
    needs_datasheet_section,
    render_report_markdown,
    render_review_summary,
    unreviewed_clearing_note,
    unreviewed_parts,
)

REPO = Path(__file__).resolve().parents[1]
RULES_DIR = REPO / "src" / "boardwise" / "rules"
GUARD = REPO / "tools" / "check_repo_hygiene.py"
SHELF = REPO / "blocklib" / "parts.json"
FIXTURES = Path(__file__).parent / "fixtures"
#: The 3-board project fixture 185-中1 was measured on: one designator, several
#: boards, different identity per board.
THREE_BOARD = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"

#: The batch tag an exemption in the H1 invariant has to carry.
BATCH_TAG = "187B"


def _guard():
    spec = importlib.util.spec_from_file_location("check_repo_hygiene_187b", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 186-H1 — no rule calls find_facts any more
# ---------------------------------------------------------------------------


def _rule_source_lines() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for path in sorted(RULES_DIR.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            out.append((path, number, line))
    return out


def test_no_rule_module_calls_find_facts():
    """`rules/` must go through the identity **chain**, and this pins it.

    A grep-level invariant rather than a behaviour test, because the hole was a
    *pattern*: the four sites were correct-looking calls with the right
    arguments, and the next rule author would have copied whichever form they
    found first. `find_facts` is MPN → C-number only, so a rule that calls it
    disagrees with `checkup`'s gate about the same shelf — measured: a name-only
    part was judged (rules ran on its facts) and invisible (the rules read only
    MPN/C-number) at once.

    An exemption has to carry the batch number in the **comment block** it sits
    in: a prose mention of the retired call is legitimate history, and the tag is
    what makes it a decision rather than a leftover.
    """
    offenders: list[str] = []
    block: list[tuple[Path, int, str]] = []
    for entry in [*_rule_source_lines(), (Path("<end>"), 0, "")]:
        path, number, line = entry
        if line.strip().startswith("#"):
            block.append(entry)
            continue
        if "find_facts(" in line:
            # A **call** — comments are handled by the block rule below, and this
            # line is not one.
            offenders.append(f"{path.relative_to(REPO)}:{number}")
        if block:
            text = "\n".join(item[2] for item in block)
            if "find_facts(" in text and BATCH_TAG not in text:
                offenders += [
                    f"{item[0].relative_to(REPO)}:{item[1]}"
                    for item in block
                    if "find_facts(" in item[2]
                ]
            block = []
    assert offenders == [], (
        "规则里还有 find_facts( 调用（没有批号豁免注释）：" + "、".join(offenders)
    )


def test_the_four_migrated_rules_go_through_the_shared_chain():
    """The positive half: the four files really do call the chain now.

    Without this, deleting the lookup entirely would satisfy the invariant above.
    """
    for name in ("mcusupply.py", "mcureset.py", "regulator.py", "focground.py"):
        text = (RULES_DIR / "pcb" / name).read_text(encoding="utf-8")
        assert "resolve_component_facts" in text, name
        assert "find_facts" not in text, name


def test_a_name_only_part_is_seen_by_all_four_rules():
    """The reproducer, end to end at the rule level (agent-344's `demo_rules2`).

    One shelf, one board part with an empty MPN and an empty C-number: every one
    of the four rules must find it by its device name, exactly as the gate does.
    """
    from boardwise.core.model import Component, DesignModel, Pin
    from boardwise.core.parts import PartEntry, PartLibrary
    from boardwise.rules.pcb.focground import _looks_like_resistor
    from boardwise.rules.pcb.mcureset import _read_mcus as _reset_readings
    from boardwise.rules.pcb.mcusupply import _read_mcus as _supply_readings
    from boardwise.rules.pcb.regulator import _regulator_readings

    shelf = PartLibrary(parts=[
        PartEntry(key="ic.mcu.by_name", mpn="ACME-MCU-1", lcsc="", category="ic.mcu"),
        PartEntry(key="ic.ldo.by_name", mpn="ACME-LDO-1", lcsc="", category="ic.ldo"),
        PartEntry(key="res.by_name", mpn="ACME-RES-1", lcsc="", category="resistor"),
    ])

    def board(designator: str, name: str) -> DesignModel:
        return DesignModel(
            components={
                designator: Component(
                    uid=designator.lower(), designator=designator, mpn="", lcsc_part="",
                    props={"device_name": name},
                    pins=[Pin("1", "VDD", "+3V3"), Pin("2", "NRST", "NRST")],
                )
            },
            nets={},
        )

    assert len(_supply_readings(board("U3", "ACME-MCU-1"), shelf)) == 1
    assert len(_reset_readings(board("U3", "ACME-MCU-1"), shelf)) == 1
    assert len(_regulator_readings(board("U5", "ACME-LDO-1"), shelf)) == 1
    assert _looks_like_resistor("U7", "", board("U7", "ACME-RES-1"), shelf)[0] is True
    # A None shelf is still "no shelf", not a crash (focground's own contract).
    assert _looks_like_resistor("R1", "0R", DesignModel(components={}, nets={}), None)[0] is True


# ---------------------------------------------------------------------------
# 186-H2 — the frozen write and the frozen read name one shelf
# ---------------------------------------------------------------------------


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """A process shaped exactly like a PyInstaller one-file bundle."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


def _bundle_shelf(frozen: Path) -> Path:
    bundle = frozen / resources.FROZEN_SUBDIR / "blocklib"
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SHELF, bundle / "parts.json")
    return bundle / "parts.json"


def test_the_frozen_read_prefers_the_users_own_shelf(frozen, monkeypatch, tmp_path):
    """Read order: the user's file when it exists, else the exe's copy.

    186-H2's other half. The write half is pinned in `test_resources.py` (where
    the frozen path pins live); this one is the *read* rule the write needs.
    """
    from boardwise.rules.facts import default_library_path

    home = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    monkeypatch.chdir(frozen)
    _bundle_shelf(frozen)

    assert default_library_path() == str(resources.parts_library())
    home.mkdir()
    (home / "parts.json").write_text('{"parts": []}\n', encoding="utf-8")
    assert default_library_path() == str(home / "parts.json"), (
        "用户货架存在时读侧没优先它——写完读不到，清闸指令就是废话"
    )
    # A checkout ignores the user shelf entirely: the repository's own file is
    # the answer there, `parts add` writes it, and nothing changed.
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert default_library_path() == "blocklib/parts.json"


def test_the_report_names_the_shelf_it_read_and_quotes_it_back(tmp_path, monkeypatch):
    """The clearing instruction carries the path, in JSON and in both ledgers.

    A reader who follows «把 facts 写进货架» has to know *which* shelf: the two
    ends differ between a checkout and an exe, and the whole hole was that the
    instruction named neither.
    """
    shelf = tmp_path / "my-shelf.json"
    shutil.copyfile(SHELF, shelf)
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    cli.main([
        "checkup", "--file", str(THREE_BOARD), "--out", str(out), "--library", str(shelf),
    ])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["shelfPath"] == str(shelf)
    note = unreviewed_clearing_note(report["shelfPath"])
    assert UNREVIEWED_CLEARING_NOTE in note, "清闸文案的原文丢了（只许在后面补）"
    assert f"--library {shelf}" in note
    for name in ("report.md", "review-summary.md"):
        text = (out / name).read_text(encoding="utf-8")
        assert f"--library {shelf}" in text, name
    # A report with no shelf path (hand-built, or an older file) degrades to the
    # original wording rather than printing an empty `--library`.
    assert unreviewed_clearing_note("") == UNREVIEWED_CLEARING_NOTE
    fake = {"summary": {"unreviewedParts": 1}, "unreviewed_parts": [{"designator": "U1"}]}
    assert UNREVIEWED_CLEARING_NOTE in render_report_markdown(fake)
    assert UNREVIEWED_CLEARING_NOTE in render_review_summary(fake, [])


# ---------------------------------------------------------------------------
# hygiene 中4 / 中5 / 中6 — encodings, the baseline, and one pass
# ---------------------------------------------------------------------------


def _write_list(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path


def test_the_three_states_are_unchanged(tmp_path):
    """186's gate semantics stay: no list = off, a word = a hit, a near miss is not."""
    guard = _guard()
    (tmp_path / "clean.md").write_text("nothing to see", encoding="utf-8")
    (tmp_path / "dirty.md").write_text("line one\nsee AcmeCorp here\n", encoding="utf-8")
    assert guard.sensitive_words(tmp_path / "missing-words") == []
    words = guard.sensitive_words(_write_list(tmp_path / "w", "AcmeCorp\n"))
    hits = guard.sensitive_violations(tmp_path, words, ["clean.md", "dirty.md"])
    assert hits == ["dirty.md:2 (word #1)"]
    assert all("AcmeCorp" not in hit for hit in hits), "命中报告不许把词本身印出来"


def test_the_list_file_is_read_in_every_encoding_it_arrives_in(tmp_path):
    """中4: a BOM/UTF-16/GBK list is read, and its words are live.

    Measured: a UTF-8 BOM list yielded ``'\\ufeffAcmeCorp'`` (a word that can
    never match) and a UTF-16 list — what a PowerShell redirect writes — made
    every run exit 2.
    """
    guard = _guard()
    bom = guard.sensitive_words(_write_list(tmp_path / "bom", "AcmeCorp\n", "utf-8-sig"))
    assert bom == ["AcmeCorp"]
    assert guard._word_pattern(bom[0]).search("see AcmeCorp here")
    assert guard.sensitive_words(_write_list(tmp_path / "u16", "AcmeCorp\n", "utf-16")) == [
        "AcmeCorp"
    ]
    assert guard.sensitive_words(_write_list(tmp_path / "gbk", "智能药箱\n", "gbk")) == [
        "智能药箱"
    ]
    # A list nobody can decode is not "no list": the gate must not fail open.
    bad = tmp_path / "bad"
    bad.write_bytes(b"\x00\xff\x00\xfe\x00")
    with pytest.raises(SystemExit) as info:
        guard.sensitive_words(bad)
    assert info.value.code == 2


def test_a_hit_is_found_in_utf16_and_gbk_files(tmp_path):
    """中4: the *files* too — 154 tracked files were invisible to the old reader.

    The old reader decoded everything as UTF-8 with ``errors="replace"``, so a
    UTF-16 or GBK file's content never matched: the gate reported clean about
    files it had not actually read. Measured on this repository: 17 UTF-16 files
    and two GBK text dumps, one of them carrying a project name.
    """
    guard = _guard()
    (tmp_path / "u8.md").write_text("the AcmeCorp board\n", encoding="utf-8")
    (tmp_path / "u16.md").write_bytes("the AcmeCorp board\n".encode("utf-16"))
    (tmp_path / "gbk.md").write_bytes("本项目 AcmeCorp 评审\n".encode("gbk"))
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\xff\xfe\x00binary blob")
    report = guard.sensitive_report(tmp_path, ["AcmeCorp"], ["u8.md", "u16.md", "gbk.md", "bin.dat"])
    assert report["hits"] == [
        "gbk.md:1 (word #1)", "u16.md:1 (word #1)", "u8.md:1 (word #1)",
    ]
    # …and the file it could not read is disclosed, not silently skipped.
    assert report["unscanned"] == ["bin.dat"]
    # The disclosure distinguishes what a reader can act on: an image is
    # expected to be unreadable, a `.md` is a case to look at. Nothing is
    # skipped by this classification — `unscanned` above lists both.
    assert guard._is_binary_name("docs/gs-01.png") is True
    assert guard._is_binary_name("notes/board.md") is False
    assert guard._is_binary_name("bin.dat") is False


def test_the_baseline_grandfathers_a_hit_without_hiding_it(tmp_path):
    """中5: ``path<TAB>word`` is the baseline — reported, never fatal.

    The three states a baseline needs: an exempt hit (reported as baselined), a
    **new** hit on the same word elsewhere (a violation), and a file the word
    never appeared in (clean). The exit code reflects only the second.
    """
    guard = _guard()
    (tmp_path / "old.md").write_text("line one\nAcmeCorp here\n", encoding="utf-8")
    (tmp_path / "new.md").write_text("AcmeCorp appears again\n", encoding="utf-8")
    (tmp_path / "clean.md").write_text("nothing\n", encoding="utf-8")
    words_file = _write_list(
        tmp_path / ".sensitive-words",
        "# the baseline\nAcmeCorp\nold.md\tAcmeCorp\n",
    )
    words = guard.sensitive_words(words_file)
    exemptions = guard.sensitive_exemptions(words_file)
    assert words == ["AcmeCorp"], "豁免行不改变词表：它只选择哪些命中算存量"
    assert exemptions == [("old.md", "AcmeCorp")]
    report = guard.sensitive_report(
        tmp_path, words, ["old.md", "new.md", "clean.md"], exemptions
    )
    assert report["hits"] == ["new.md:1 (word #1)"]
    assert report["exempt"] == ["old.md:2 (word #1)"]
    # The exit code is the non-exempt half only — the whole point of the baseline.
    assert guard.sensitive_violations(tmp_path, words, ["old.md"], exemptions) == []
    assert guard.sensitive_violations(tmp_path, words, ["new.md"], exemptions) == [
        "new.md:1 (word #1)"
    ]
    # A backslash spelling of the same path is the same path (Windows list files).
    assert guard.sensitive_violations(tmp_path, words, ["old.md"], [("old.md", "AcmeCorp")]) == []


def test_the_real_guard_exit_code_follows_only_the_new_hits(tmp_path, monkeypatch):
    """The same rule through ``main()``: green with a baseline, red without.

    ``_git`` is stubbed, so this is the guard's own arithmetic on a temp tree —
    the repository is never scanned from a unit test (that is what
    `tests/test_repo_hygiene.py` does, containers only).
    """
    guard = _guard()
    (tmp_path / "old.md").write_text("AcmeCorp here\n", encoding="utf-8")
    (tmp_path / "new.md").write_text("AcmeCorp again\n", encoding="utf-8")
    tracked = ["old.md"]
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "_git", lambda *a: tracked)
    monkeypatch.setattr(sys, "argv", ["check_repo_hygiene.py"])

    _write_list(tmp_path / ".sensitive-words", "AcmeCorp\nold.md\tAcmeCorp\n")
    assert guard.main(["check_repo_hygiene.py"]) == 0, (
        "存量命中（已写进基线）不该让闸变红——否则岳本机一启用名单就永久红"
    )
    # The same list against a file that just gained the word: that is a new leak.
    tracked = ["old.md", "new.md"]
    assert guard.main(["check_repo_hygiene.py"]) == 1, "新增命中必须红"
    _write_list(tmp_path / ".sensitive-words", "# nothing to watch\n")
    assert guard.main(["check_repo_hygiene.py"]) == 0


def test_one_pass_over_the_words_not_one_pass_each(tmp_path):
    """中6: the cost is O(one pass), not O(words × file).

    Measured on 2026-10-16: 12 words over this repository's 51.2 MB cost 10.5 s
    (0.87 s per word) because every word scanned every file. Two assertions, one
    structural and one wall-clock: the per-word patterns are compiled a fixed
    number of times (they are not the scanning engine any more), and 12 words
    over a 16 MB file stay inside the 3 s target.
    """
    guard = _guard()
    words = [f"SensitiveWord{i:02d}" for i in range(12)]
    big = tmp_path / "big.md"
    chunk = "nothing to see here, " * 400 + "\n"
    with big.open("w", encoding="utf-8") as fh:
        while fh.tell() < 16 * 1024 * 1024:
            fh.write(chunk)
    (tmp_path / "hit.md").write_text("…SensitiveWord03…\n", encoding="utf-8")

    compiled: list[str] = []
    real = guard._word_pattern

    def counting(word: str):
        compiled.append(word)
        return real(word)

    guard._word_pattern = counting
    try:
        started = time.perf_counter()
        report = guard.sensitive_report(tmp_path, words, ["big.md", "hit.md"])
        elapsed = time.perf_counter() - started
    finally:
        guard._word_pattern = real
    assert report["hits"] == ["hit.md:1 (word #4)"]
    assert compiled == words, (
        "per-word patterns were compiled per file — the scan is back to O(words × files)"
    )
    assert elapsed < 3.0, f"12 词 16 MB 用了 {elapsed:.2f}s（目标 < 3s）"


# ---------------------------------------------------------------------------
# 185-中1 — the folded worklist says which boards it stands for
# ---------------------------------------------------------------------------


def test_a_folded_row_carries_the_first_placement_identity_and_the_boards(tmp_path):
    """The unit: one designator, two boards, two different parts.

    ``unreviewed_parts[]`` has one row per **placement**; the worklist folds by
    designator. The fold keeps the first placement's identity (unchanged, 185-中1
    只加) and now also says what it folded together.
    """
    seeds = [
        {
            "designator": "C2", "boards": ["Board1"], "name": "CAP_0603",
            "value": "", "mpn": "", "supplier": "", "reasons": ["无 MPN"],
            "channels": {}, "missingFacts": ["value"],
        },
        {
            "designator": "C2", "boards": ["Board3"], "name": "CGA0603X7R104K500JT",
            "value": "100nF", "mpn": "CGA0603X7R104K500JT", "supplier": "C12345",
            "reasons": ["供应商字段为空"], "channels": {}, "missingFacts": [],
        },
        {
            "designator": "U1", "boards": [], "name": "MCU", "value": "STM32",
            "mpn": "STM32-1", "supplier": "C1", "reasons": [], "channels": {},
            "missingFacts": [],
        },
    ]
    section = needs_datasheet_section(seeds, [], [])
    rows = {row["part"]: row for row in section}
    assert len(section) == 2, "折叠是按位号的：两个位号两条"
    folded = rows["C2"]
    assert folded["mpn"] == "" and folded["missingFacts"] == ["value"], (
        "首到 placement 的身份字段必须原样保留（185-中1 只加）"
    )
    assert folded["boards"] == [
        {"board": "Board1", "mpn": "", "name": "CAP_0603", "value": ""},
        {
            "board": "Board3", "mpn": "CGA0603X7R104K500JT",
            "name": "CGA0603X7R104K500JT", "value": "100nF",
        },
    ]
    # A model with no board identity carries an **empty** list, never no key.
    assert rows["U1"]["boards"] == []
    # A marked row carries it too, sourced from the same seed rows.
    marked = needs_datasheet_section(seeds, [{"part": "C2", "pin": "1", "reason": "看不清"}], [])
    assert len(marked) == 2
    assert {row["part"]: row for row in marked}["C2"]["boards"] == folded["boards"]


def test_the_docstring_stops_claiming_nothing_else_changed():
    """The sentence that was false: «everything else about it is unchanged».

    185-中1's whole finding is that a folded row is **not** the placement row it
    came from, and the docstring said the opposite. Source-level, like 185 B's
    key pin: this text is the contract the next reader trusts.
    """
    doc = inspect.getdoc(needs_datasheet_section) or ""
    assert "everything else about it is unchanged" not in doc
    assert "boards" in doc and "designator" in doc


def test_the_worklist_of_a_three_board_project_names_the_boards(tmp_path, monkeypatch):
    """The measured case, end to end over the 3-board fixture.

    Drift-proof by construction: the folded `boards` are compared against what
    ``unreviewed_parts[]`` itself says for that designator (both come out of one
    report), plus the two structural claims — every row has the key, and at least
    one designator really is on more than one board with a different identity.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    cli.main([
        "checkup", "--file", str(THREE_BOARD), "--out", str(out), "--library", str(SHELF),
    ])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    placements: dict[str, set[tuple[str, str, str, str]]] = {}
    for row in report["unreviewed_parts"]:
        # 191B: `unreviewed_parts[].boards` and `needs_datasheet[].boards` are one
        # shape now — placement rows, each one `{board, mpn, name, value}` — so the
        # comparison below is dict-to-dict, not title-to-dict as it was in 187B.
        for entry in row.get("boards") or [{}]:
            placements.setdefault(str(row["designator"]), set()).add(
                (
                    str(entry.get("board") or ""),
                    str(entry.get("mpn") or ""),
                    str(entry.get("name") or ""),
                    str(entry.get("value") or ""),
                )
            )
    worklist = report["needs_datasheet"]
    assert worklist, "3 板工程应该有未审位号"
    for row in worklist:
        assert "boards" in row, row["part"]
        assert [entry["board"] for entry in row["boards"]] == [
            board for board, _mpn, _name, _value in sorted(placements.get(row["part"], set()))
        ], f"{row['part']} 的板别与 unreviewed_parts 不一致"
        assert {
            (entry["board"], entry["mpn"], entry["name"], entry["value"])
            for entry in row["boards"]
        } == placements.get(row["part"], set()), row["part"]

    multi = [row for row in worklist if len(row["boards"]) > 1]
    assert multi, "3 板夹具上应该有多板同位号——这就是 185-中1 的实测现场"
    different = [
        row for row in multi
        if len({(entry["mpn"], entry["name"], entry["value"]) for entry in row["boards"]}) > 1
    ]
    assert different, "多板同位号里必须有身份不同的（否则折叠无害，这洞不成立）"

    # The counts: `needsDatasheetTotal` is the **folded, deduplicated** length.
    assert report["completion"]["needsDatasheetTotal"] == len(worklist)
    assert len(worklist) < len(report["unreviewed_parts"]), (
        "多板工程里折叠应当真的少于 placement 行数"
    )

    # …and the human ledger says it out loud, for the row the reader would
    # otherwise take for one part.
    markdown = (out / "report.md").read_text(encoding="utf-8")
    for row in different:
        assert f"- `{row['part']}`：" in markdown, row["part"]
        for entry in row["boards"]:
            assert entry["board"] in markdown


def test_a_single_board_report_is_unchanged_by_the_new_field(tmp_path, monkeypatch):
    """「schema 只加」: a report that never had boards gains an empty list.

    The old keys keep their values byte for byte — the guard against a widened
    section that quietly changes what an existing reader sees.
    """
    model = type("M", (), {"components": {}, "nets": {}})()
    assert needs_datasheet_section([], [], []) == []
    assert unreviewed_parts(model) == []
    fake = {
        "summary": {"unreviewedParts": 0},
        "unreviewed_parts": [],
        "needs_datasheet": [
            {"part": "U1", "pins": [], "trigger": "marked", "reason": "看不清",
             "dependentFindings": [], "factSeed": False, "channels": {}, "mpn": "",
             "supplier": "", "missingFacts": [], "boards": []}
        ],
        "shelfPath": "blocklib/parts.json",
    }
    markdown = render_report_markdown(fake)
    assert "### 审查者标记" in markdown
    assert "多块板上" not in markdown, "单板上位号不该出现多板提示"
