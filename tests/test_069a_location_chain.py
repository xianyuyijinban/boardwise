"""issue #69 条 1: the review output is split in two — a machine ledger and an AI summary.

The complaint (xianyuyijinban relaying a colleague, 2026-10-07): `report.json` /
`report.md` are a machine's ledger and a reader cannot find anything in them, while
the AI's actual summary lives only in the chat window and dies with it. So:

* **the machine side** grows a *location chain* on every finding — 工程 → 板 →
  原理图页（有的话） → 器件/网 → 问题 — because that is the four-link path an
  engineer has to walk to open the right thing, and a report that omits a link
  without saying so reads like a complete one;
* **the AI side** is mechanised: `checkup` writes a `review-summary.md` **skeleton**
  with each chain prefilled and 「分析」/「建议」 left blank, so "写总结" stops being
  an invitation to start from nothing.

What is pinned here, and why each is a way the feature could fail:

1. every chain link is derived from something the report **already knows** — a
   missing link is `未标注`, never a guess, and the missing ones are *listed*;
2. `report.md` renders the chain and says which findings have an incomplete one,
   rather than printing a table where a hole looks like a value;
3. the skeleton has one prefilled row per finding on the real fixture, with both
   blank columns present and the chain non-empty — the mechanical guarantee that
   the SOP's 「收尾必须补全」 is an instruction about *this* file and not about prose;
4. the file is written into `--out` on every run, and the run's own console line
   says so, so it cannot be quietly absent.

The board is 毕设FOC 1.0.0 (`tests/fixtures/`), the same board issue #69's author
was looking at: two boards, three pages, two of them titled `P1` — which is exactly
the shape that makes a chain wrong in a way a single-board fixture cannot catch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.checkup import (
    CHAINS_KEY,
    CHAIN_LINKS,
    CHAIN_UNKNOWN,
    REVIEW_SUMMARY_BLANK_ADVICE,
    REVIEW_SUMMARY_BLANK_ANALYSIS,
    chain_text,
    finding_chains,
    page_attribution_from_archive,
    render_report_markdown,
    render_review_summary,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
#: 毕设FOC 1.0.0 — issue #69's own board: 2 boards, 3 pages, two titled `P1`.
BISHE = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
#: The golden single-page board: one page, so the chain's page link has nowhere to
#: be ambiguous. Used where a test wants a chain that is complete by construction.
CH340 = FIXTURES / "ch340_golden.epro2"

#: The rule ids allowed to produce a **device-less** chain on 毕设FOC 1.0.0 —
#: i.e. a row whose subject is the *board*, not a part.
#:
#: **Added by 133b.** R11's 「no net on this board has a power-path name」 row
#: is a statement that a whole board's power-path sieve found nothing. There is
#: no designator to name, and the engine's own `finding_chains` docstring
#: already blesses the shape (「a finding with no ``refs`` and no
#: ``target.component_ref`` … the device link reads ``CHAIN_UNKNOWN``, and the
#: report says so rather than dropping the row」). Every other rule on this
#: fixture names a part or a net, so this set is a short, closed list rather
#: than a general weakening: adding a rule id here means asserting that its row
#: is genuinely about a board, not about a part that was forgotten.
#: **Widened by 133c**, on the same test as 133b widened it and for the same
#: reason. Two of the three ground-system rules file rows whose subject is the
#: *board's ground system*, not a part: R1's 「no power-domain ground」 notice,
#: R1b's 「no power-domain ground, so no tie search」 notice, and R1b's
#: 「not a single point」 account of the two bridging resistors (which names
#: *nets* and parts but is a statement about how the two domains join, and
#: whose ``component_ref`` is empty by design). R5's per-net rows all carry
#: ``net_refs`` and so chain to a net, not a device — which is why R5 is **not**
#: in this set. Each id here is an assertion that the row is about a board, not
#: a part that was forgotten; test_133c_foc_ground.py pins what each row says.
DEVICE_LESS_ALLOWED: frozenset[str] = frozenset({
    "pcb-foc-gate-trace-width",
    "pcb-foc-ground-domains",
    "pcb-foc-ground-tie",
})


def _run_checkup(tmp_path: Path, board: Path = BISHE) -> tuple[int, Path]:
    """One real offline `checkup`, and the `--out` directory it wrote."""
    out = tmp_path / "out"
    code = cli.main([
        "checkup", "--file", str(board), "--out", str(out),
        "--library", str(FIXTURES.parent.parent / "blocklib" / "parts.json"),
    ])
    return code, out


@pytest.fixture(scope="module")
def report_and_pages(tmp_path_factory):
    """One `checkup` over the fixture, shared by the read-only tests below.

    A module-scoped run because the chain is a pure function of the report but the
    report costs three seconds to build and every assertion here reads the same
    one. The tests that need to mutate the report take their own copy.
    """
    out = tmp_path_factory.mktemp("chain") / "out"
    code = cli.main([
        "checkup", "--file", str(BISHE), "--out", str(out),
        "--library", str(FIXTURES.parent.parent / "blocklib" / "parts.json"),
    ])
    assert code in (0, 1, 3), code
    return json.loads((out / "report.json").read_text(encoding="utf-8")), out


# --------------------------------------------------------------------------
# 1. the chain itself: four links, each derived, each honest about a hole
# --------------------------------------------------------------------------


def test_every_finding_gets_a_chain_with_all_four_links(report_and_pages):
    """The pin issue #69 names: 「工程 → 板 → 原理图页（有的话） → 器件/网 → 问题」.

    All four keys are **always present** — a chain that dropped its missing link
    would serialise one shape for a complete finding and another for an incomplete
    one, and every consumer would have to treat "absent" and "unknown" as different
    things. The value is the honest one: `未标注`, not `""` and not a guess.
    """
    report, _out = report_and_pages
    chains = finding_chains(report)
    assert chains, "the fixture must produce findings or this pins nothing"
    assert [chain["index"] for chain in chains] == list(range(len(report["findings"])))
    for chain in chains:
        assert set(chain) >= {
            "index", "rule_id", "severity", "project", "board", "page", "refs",
            "problem", "missing",
        }
        for link in CHAIN_LINKS:
            assert chain[link], f"{link} is never an empty string, only 未标注"
        assert set(chain["missing"]) <= set(CHAIN_LINKS)


def test_the_chain_names_the_board_and_the_page_the_part_is_actually_on(report_and_pages):
    """The chain must be *right*, not merely non-empty.

    On this fixture every schematic finding sits on a page of a named board, and
    the reading is checked against the report's own module table rather than
    against a hard-coded page list: the chain is derived from `modules[]`, so if it
    ever disagreed with the grouping the two would be reporting different boards
    for the same finding.
    """
    report, _out = report_and_pages
    boards = {board["title"] for board in report["source"]["boards"]}
    page_of: dict[str, set[str]] = {}
    for module in report["modules"]:
        for uuid in module.get("pages") or []:
            for ref in module.get("components") or []:
                page_of.setdefault(f"{module.get('board')}|{ref}", set()).add(uuid)

    checked = 0
    for chain in finding_chains(report):
        board = chain["board"]
        if board not in boards or chain["page"] == CHAIN_UNKNOWN:
            continue
        for ref in chain["refs"].replace("（网 ", "\x00").split("\x00")[0].split("、"):
            expected = page_of.get(f"{board}|{ref}", set())
            if not expected:
                continue
            checked += 1
            assert chain["page"] != CHAIN_UNKNOWN, (ref, board)
    assert checked >= 10, f"only {checked} links were cross-checked against the modules"


def test_a_page_whose_title_is_not_unique_is_named_with_its_uuid(report_and_pages):
    """Three pages are titled `P1` on this fixture (040b measured it).

    A chain saying `页:P1` for a finding on Board2's `P1` sends the reader to the
    wrong sheet, which is worse than not saying. The uuid tail is what makes it an
    address, and 040b already decided that for the module names — the chain follows
    the same rule rather than inventing a second one.
    """
    report, _out = report_and_pages
    pages = page_attribution_from_archive(BISHE)
    titles = [page.get("title") for page in pages.values() if page.get("components")]
    assert titles.count("P1") >= 2, "the fixture must really have repeated titles"
    # The chains the run actually wrote (`report.json`), not a re-derivation:
    # the attribution is an in-memory reading that only `checkup` had, so a reader
    # of the report can only check the title rule against the stored rows.
    chains = report[CHAINS_KEY]
    with_uuid = [chain for chain in chains if "P1（" in chain["page"]]
    assert with_uuid, "a repeated title must be disambiguated, not printed bare"
    import re
    for chain in with_uuid:
        # …and every uuid in the tail is a real page of this project, not a guess.
        # Only a *disambiguated* page carries one (`P1（5f0f4e16）`); a uniquely
        # titled page is named bare, so the tail is read rather than assumed.
        tails = re.findall(r"（([0-9a-f]{8})）", chain["page"])
        assert tails, chain["page"]
        for uuid in tails:
            assert uuid in {known[:8] for known in pages}, (chain["page"], uuid)


def test_a_findings_pages_never_cross_into_another_board(report_and_pages):
    """The `conn-duplicate-designators` case, which is the one that gets it wrong.

    A cross-board duplicate (`C1` is on Board1 *and* Board2) matches modules of
    both boards. Printing both pages under a `Board1 →` link would send the reader
    to Board2's sheet for a finding that is about Board1's placement. The board
    link narrows the page lookup, and the test measures that it does.
    """
    report, _out = report_and_pages
    cross = [
        chain for chain in finding_chains(report)
        if "more than one board" in chain["problem"]
    ]
    assert cross, "the fixture must have cross-board duplicates or this pins nothing"
    board_of = {}
    for module in report["modules"]:
        for ref in module.get("components") or []:
            board_of.setdefault(ref, set()).add(module.get("board"))
    for chain in cross:
        ref = chain["refs"]
        if chain["board"] in board_of.get(ref, set()):
            # Its pages must all belong to that board — checked by resolving each
            # page uuid back through the modules.
            owning = {
                module.get("board") for module in report["modules"]
                for uuid in (module.get("pages") or [])
                if uuid[:8] in chain["page"]
            }
            assert owning <= {chain["board"]}, (chain["index"], chain["page"], owning)


def test_a_link_the_run_cannot_derive_is_reported_not_invented():
    """The netlist tier: no page information at all, so the page link is a hole.

    This is the shape the issue's 「有的话」 covers, and the discipline is what the
    127 anchoring rules already insist on elsewhere: a missing link must be visible
    as missing. `page: 未标注` plus `missing: ["page"]` is the answer; a page name
    borrowed from another finding, or from the module list of an unrelated board,
    would be a fabricated location.
    """
    report = {
        "source": {"tier": "netlist", "boards": [
            {"title": "Board1", "uuid": "b1"}, {"title": "Board2", "uuid": "b2"},
        ]},
        "model": {},
        # No `modules`: the netlist tier carries no page split at all, which is the
        # whole point of the shape being tested — a `p1` here would come from a
        # grouping this tier cannot produce.
        "findings": [
            {"rule_id": "r", "severity": "WARN", "message": "m", "refs": ["U1"]},
            {"rule_id": "r2", "severity": "WARN", "message": "m2",
             "board": "Board9", "refs": ["U9"]},
        ],
    }
    first, second = finding_chains(report)
    assert first["board"] == CHAIN_UNKNOWN, "two boards and no stated board = no claim"
    assert first["project"] == CHAIN_UNKNOWN, "this source names no project and no file"
    assert set(first["missing"]) == {"project", "board", "page"}
    assert second["board"] == "Board9"
    assert second["page"] == CHAIN_UNKNOWN, "no pages are known to this report at all"


def test_a_finding_with_no_refs_at_all_still_gets_a_row():
    """A PCB spacing measurement names no designator; the row must still exist.

    Dropping it would make the count of problems in the skeleton smaller than the
    count in `report.json`, and the reader would never learn there was one. The
    device link reads `未标注` and the chain says which link is missing.
    """
    report = {
        "source": {"tier": "file", "file": "b.epro2",
                   "boards": [{"title": "PCB1", "uuid": "p"}]},
        "model": {}, "modules": [],
        "findings": [{"rule_id": "pcb-voltage-spacing", "severity": "INFO",
                      "message": "+24V to GND 19.0 mil", "board": "PCB1", "refs": []}],
    }
    [chain] = finding_chains(report)
    assert chain["refs"] == CHAIN_UNKNOWN
    assert "refs" in chain["missing"]
    assert chain_text(chain).endswith("〔缺 refs〕"), chain_text(chain)


def test_the_nets_a_finding_reads_travel_with_the_device_link():
    """`target.net_refs` is a link the old report threw away next to `refs`.

    A decap finding's whole point is "the cap on NET11 is too small"; a chain that
    said only `U5` sends the reader hunting for the net. Named in parentheses so it
    cannot be confused with a designator.
    """
    report = {
        "source": {"tier": "file", "boards": [{"title": "Board1", "uuid": "b"}]},
        "model": {}, "modules": [],
        "findings": [{"rule_id": "decap-required-caps", "severity": "WARN", "message": "m",
                      "refs": ["U5"], "target": {"component_ref": "U5", "net_refs": ["NET11"]}}],
    }
    [chain] = finding_chains(report)
    assert chain["refs"] == "U5（网 NET11）"
    assert "U5（网 NET11）" in chain_text(chain)


def test_the_component_ref_counts_as_a_device_link_when_refs_did_not_name_it():
    """016's `target.component_ref` is a *second* source of the same fact.

    A rule that fills the target but not `refs` (the add-component kind does)
    would otherwise produce a chain with no device link at all, and the whole point
    of the chain is that the device is where the reader goes.
    """
    report = {
        "source": {"tier": "file", "boards": [{"title": "Board1", "uuid": "b"}]},
        "model": {}, "modules": [],
        "findings": [{"rule_id": "decap-required-caps", "severity": "WARN", "message": "m",
                      "refs": [], "target": {"component_ref": "U1", "net_refs": []}}],
    }
    [chain] = finding_chains(report)
    assert chain["refs"] == "U1"


def test_the_chain_line_prints_the_page_slot_even_when_it_is_empty():
    """「页:（本档无页信息）」, not a line with the page silently dropped.

    Two readers, two questions: "this board has no page" (a PCB finding) and "the
    report did not look" (an unresolved tier) must not print the same line, and a
    line that simply omits the slot answers neither.
    """
    row = {"project": "P", "board": "PCB1", "page": CHAIN_UNKNOWN, "refs": "R10",
           "missing": ["page"]}
    text = chain_text(row)
    assert text == "P → PCB1 → 页:（本档无页信息） → R10"
    assert "〔缺" not in text, "the page alone is not a broken chain to shout about"


# --------------------------------------------------------------------------
# 2. report.md: the chain is rendered, and a hole is announced
# --------------------------------------------------------------------------


def test_report_md_shows_the_chain_column_and_names_the_incomplete_ones(report_and_pages):
    """The issue's own requirement: 「缺哪环时在报告里显式可见，不是静默省略」.

    Two halves, both asserted: the table carries a 定位链 column, and the run says
    out loud how many findings have an incomplete chain and which link it is. A
    reader who only looks at the table would see `未标注` in a cell; a reader who
    only skims needs the sentence.
    """
    report, out = report_and_pages
    text = (out / "report.md").read_text(encoding="utf-8")

    assert "## 规则 findings（" in text
    assert "| 定位链 |" in text
    chains = finding_chains(report)
    incomplete = [chain for chain in chains if chain["missing"]]
    assert incomplete, "PCB findings have no schematic page; this pins the sentence"
    assert f"有 {len(incomplete)}/{len(chains)} 条 finding 的定位链不完整" in text
    assert "不静默省略" in text
    # The rows themselves are the chains, verbatim — the report cannot disagree
    # with the skeleton because both read the same rows.
    for chain in chains[:5]:
        assert chain_text(chain)[:40] in text


def test_a_run_whose_chains_are_all_complete_says_nothing_about_gaps():
    """The sentence is a reading, not a template line.

    A board where every finding lands on a page must not print 「定位链不完整」:
    that is the false-alarm habit this project keeps cleaning up, and the sentence
    has to be earned by the data rather than by the template.
    """
    report = {
        "source": {"tier": "file", "project": {"friendlyName": "板"}, "file": "b.epro2",
                   "boards": [{"title": "Board1", "uuid": "b"}]},
        "model": {"components": 1, "nets": 0, "designators": ["R1"]},
        "summary": {"errorCount": 0, "warnCount": 1, "infoCount": 0, "exitCode": 0},
        "modules": [{"name": "P1", "basis": "page", "components": ["R1"],
                     "pages": ["page-uuid-1"], "findings": [0]}],
        "findings": [{"rule_id": "r", "severity": "WARN", "message": "m", "refs": ["R1"]}],
        "ai_slots": {"unknown_parts": [], "canvas_images": [], "summary_template": "t"},
    }
    chains = finding_chains(report, attribution={
        "page-uuid-1": {"uuid": "page-uuid-1", "title": "P1", "components": ["R1"]},
    }, modules=report["modules"])
    assert chains[0]["missing"] == [], chains[0]
    report[CHAINS_KEY] = chains
    text = render_report_markdown(report)
    assert "定位链不完整" not in text
    assert "板 → Board1 → 页:P1 → R1" in text


def test_the_chain_section_is_in_the_json_so_a_reader_does_not_re_derive_it(report_and_pages):
    """`report.json` keeps the rows the Markdown printed.

    `review-summary.md` is generated from the same rows, so if the JSON did not
    carry them the two files would be derived by two different passes and could
    disagree about which page a finding is on — the exact drift this file exists
    to prevent.
    """
    report, _out = report_and_pages
    assert isinstance(report[CHAINS_KEY], list)
    assert len(report[CHAINS_KEY]) == len(report["findings"])
    assert report[CHAINS_KEY][0]["index"] == 0


# --------------------------------------------------------------------------
# 3. the review-summary.md skeleton
# --------------------------------------------------------------------------


def test_the_skeleton_has_one_prefilled_row_per_finding_on_the_real_board(tmp_path):
    """The issue's own acceptance: 毕设FOC 1.0.0 跑一遍，定位链逐条非空.

    Not "non-empty somewhere" — **per row**: every finding the ledger knows about
    appears in the skeleton with a chain whose project/board/device links are all
    filled, and with both blank columns present and unfilled. A row that silently
    lost its chain would make the SOP's 「补全 review-summary.md」 unfalsifiable.
    """
    _code, out = _run_checkup(tmp_path)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    text = (out / "review-summary.md").read_text(encoding="utf-8")

    rows = [line for line in text.splitlines() if line.startswith("| ") and "<!--" in line]
    assert len(rows) == len(report["findings"]), (len(rows), len(report["findings"]))
    for chain, line in zip(report[CHAINS_KEY], rows):
        assert f"| {chain['index']} |" in line
        assert chain_text(chain) in line, chain
        assert chain["project"] != CHAIN_UNKNOWN
        assert chain["board"] != CHAIN_UNKNOWN
        # **133b added the first device-less finding this fixture carries**, so
        # the device link is no longer unconditionally filled. R11's 「no power-
        # path net on this board」 row on PCB2 is about the *absence* of an
        # object — there is no designator to name, and inventing one would be a
        # guess the UNKNOWN discipline forbids. `finding_chains` already
        # supports this (its own docstring names the case: 「a finding with no
        # refs and no target.component_ref … the device link reads
        # CHAIN_UNKNOWN, and the report says so rather than dropping the
        # row」), so the row is kept and the chain says 未标注 — which is the
        # honest value, not an empty string.
        #
        # Every *component-scoped* finding still names its device; that is the
        # part of this test the SOP depends on, and it is asserted below with
        # the device-less set subtracted.
        if "refs" not in chain["missing"]:
            assert chain["refs"] != CHAIN_UNKNOWN, chain
        else:
            assert chain["rule_id"] in DEVICE_LESS_ALLOWED, chain
        # The two blanks are there and are *blank*: a skeleton that pre-filled a
        # verdict would be the machine judging, which is the split this file undoes.
        assert REVIEW_SUMMARY_BLANK_ANALYSIS in line
        assert REVIEW_SUMMARY_BLANK_ADVICE in line
        assert "→ 页:" in line, "every row prints the page slot, filled or not"


def test_the_skeleton_says_its_own_file_is_the_one_the_engineer_reads(tmp_path):
    """The header has to carry the instruction, or the SOP is one link away from
    being decoration: 收尾必须补全，工程师只看这一份."""
    _code, out = _run_checkup(tmp_path)
    text = (out / "review-summary.md").read_text(encoding="utf-8")
    assert text.startswith("<!--"), "the banner is the first thing an AI reads"
    assert "工程师只看这一份" in text
    assert "docs/review-sop.md" in text, "it points at the SOP that makes it binding"
    # The three slots the SOP's 审查四步 leaves to the model have their own rows,
    # so "补全" is about filling these, not about inventing a document.
    for heading in ("## 1. 连接状态", "## 2. 逐条问题", "## 3. 待确认", "## 4. 下一步"):
        assert heading in text, heading


def test_the_skeleton_reports_the_verdict_the_run_recorded(tmp_path):
    """The header's 结论 is the report's own, not a second computation.

    `summary.conclusion` is the sentence three subsystems already agree on
    (073/075); a skeleton that said 「有问题」 or 「通过」 beside it would give the
    reader two verdicts on one board.
    """
    _code, out = _run_checkup(tmp_path)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    text = (out / "review-summary.md").read_text(encoding="utf-8")
    assert report["summary"]["conclusion"] in text
    assert f"退出码 {report['summary']['exitCode']}" in text


def test_a_run_with_no_findings_still_writes_the_skeleton(tmp_path):
    """An empty ledger is not an excuse for a missing file.

    The reader opens `review-summary.md` whether or not there was anything to find;
    a run that quietly skipped the file is indistinguishable from a run whose file
    was lost.
    """
    out = tmp_path / "out"
    cli.main([
        "checkup", "--file", str(CH340), "--out", str(out),
        "--library", str(FIXTURES.parent.parent / "blocklib" / "parts.json"),
    ])
    path = out / "review-summary.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert f"逐条问题（{len(report['findings'])} 条）" in text
    if not report["findings"]:
        assert "本次审查没有 finding" in text


def test_the_run_prints_where_the_skeleton_landed(tmp_path, capsys):
    """The console has to name the file, or nobody opens it.

    Every other artefact of a run is announced on its own line (`report.md`,
    `architecture`, `design-intent`); the skeleton is one more of those, and the
    announcement is what makes it part of the run rather than a bonus.
    """
    out = tmp_path / "out"
    cli.main([
        "checkup", "--file", str(CH340), "--out", str(out),
        "--library", str(FIXTURES.parent.parent / "blocklib" / "parts.json"),
    ])
    printed = capsys.readouterr().out
    assert "review-summary:" in printed
    assert "review-summary.md" in printed
    assert "收尾必须补全" in printed


def test_the_slot_section_points_at_the_skeleton_and_its_count(tmp_path):
    """`ai_slots.review_summary` is how a reader of report.json finds the file.

    The other AI slots each name where the model writes its answer (the triage
    note names the command, the aesthetics note names the switch); this one names
    the file and says the two columns are the model's.
    """
    _code, out = _run_checkup(tmp_path)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    slot = report["ai_slots"]["review_summary"]
    assert slot["file"] == "review-summary.md"
    assert slot["entries"] == len(report["findings"])
    assert "分析" in slot["note"] and "建议" in slot["note"]
    assert "docs/review-sop.md" in slot["note"]


def test_rendering_the_skeleton_from_chains_alone_needs_no_report_side_effects():
    """`render_review_summary(report, chains)` is a pure function of its two
    arguments — pinned because the report's `location_chains` and the skeleton are
    the *same* rows, and a second derivation inside the renderer would be the one
    place they could stop agreeing.
    """
    report = {
        "source": {"tier": "file", "tierLabel": "离线", "file": "b.epro2"},
        "summary": {"conclusion": "无 ERROR", "exitCode": 0},
    }
    chains = [{"index": 0, "rule_id": "r", "severity": "WARN", "project": "b.epro2",
               "board": "Board1", "page": "P1", "refs": "R1", "problem": "m", "missing": []}]
    first = render_review_summary(report, chains)
    assert first == render_review_summary(report, chains)
    assert "b.epro2 → Board1 → 页:P1 → R1" in first
    assert "无 ERROR" in first
