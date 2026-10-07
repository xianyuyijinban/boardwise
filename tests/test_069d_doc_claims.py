"""issue #69's three rules, pinned **in the documents** (doc-claims batch 2).

`tests/test_doc_claims.py` v1 pinned README's claims about the rule constants. This
is the same discipline applied to the SOP, and it exists because all three of issue
#69's fixes are **half prose**: the code does half the work and the document has to
make the other half binding. A rule that lives only in a Markdown file does not fail
a test when it is deleted — it just quietly stops being followed, which is exactly
how issue #8 and issue #11 happened.

So each rule is pinned by its **load-bearing sentence**, and the pin checks two
things at once:

* the sentence is still there (deleting it goes red), **and**
* the thing it names still exists in the code (renaming `review-summary.md`, or
  dropping `bridge status`'s conclusion line, goes red).

The second half is what makes these claims rather than prose. 「收尾必须补全
review-summary.md」 is only true if a file by that name is written into `--out`, and
「AI 开工第一句报连接状态」 is only actionable if `bridge status` has a conclusion
line to copy. Both are checked against the source, not against a copy of the text.
"""

from __future__ import annotations

import re
from pathlib import Path

from boardwise import cli
from boardwise.bridge import daemon as daemon_module

REPO = Path(__file__).resolve().parent.parent
SOP = (REPO / "docs" / "review-sop.md").read_text(encoding="utf-8")
GETTING_STARTED = (REPO / "docs" / "getting-started.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 条 1: the AI-side rule — 「收尾必须补全 review-summary.md，工程师只看这份」
# --------------------------------------------------------------------------


def test_the_sop_makes_filling_the_skeleton_a_step_not_a_suggestion():
    """The rule is a numbered step inside 3.1, with its own name.

    Pinned as a *heading* rather than as a sentence in the middle of a paragraph: a
    step that is part of a list can be skipped by a reader who skims, while a
    heading is what a reader looks for. The number is ⓹ because it comes after the
    four steps it depends on (⓪–③) — putting it first would ask for a summary
    before there is anything to summarise.
    """
    assert "⓹ 收尾死一步：补全 `review-summary.md`" in SOP
    section = SOP.split("**⓹ 收尾死一步")[1].split("**不要重算工具")[0]
    # The three things the rule has to name, because each one is a way to comply
    # with the letter of it while ignoring the intent.
    assert "定位链" in section, "the prefilled part is what the model must NOT re-derive"
    assert "未标注" in section, "a missing link is a question for the model, not a gap"
    assert "工程师" in section, "the audience is named, so 'who reads this' is not in doubt"
    assert "聊天窗口" in section, "the failure mode the issue was filed against"
    assert "覆盖" in section, "the file is regenerated, so a filled copy must be delivered"


def test_the_skeleton_the_sop_names_is_the_file_the_code_writes():
    """The sentence names a file; the code has to write exactly that file.

    Without this half the pin above is decorative: rename the artefact and the SOP
    goes on telling the model to fill a file nobody produces. Read from the code's
    own constant so a rename on either side goes red.
    """
    assert cli.REVIEW_SUMMARY_FILE in SOP, (
        "docs/review-sop.md names a summary file that cli.REVIEW_SUMMARY_FILE "
        "does not: the SOP would be asking the model to fill a file no run writes"
    )
    # …and it is written into `--out` beside the two ledgers, not somewhere else.
    source = (REPO / "src" / "boardwise" / "cli.py").read_text(encoding="utf-8")
    assert "_write_review_summary(out_dir" in source
    assert "REVIEW_SUMMARY_FILE" in source


def test_the_sop_lists_the_skeleton_as_a_checkup_product():
    """The 产出 list is what a reader checks to learn what a run produced.

    A file that is written but not listed is one nobody opens — and this one is
    the deliverable, so being invisible in the product list defeats the feature.
    """
    products = SOP.split("产出（`--out` 目录内）：")[1].split("\n\n")[0]
    assert "review-summary.md" in products
    # The other two artefacts' ownership markers are untouched by this issue.
    assert "自动生成、每次覆盖" in products, "architecture.md's own rule still reads as it did"
    assert "工程师所有" in products, "design-intent.md's ownership is unchanged"


# --------------------------------------------------------------------------
# 条 2: the SOP's connection-status rule, and the line it points at
# --------------------------------------------------------------------------


def test_the_sop_says_the_first_sentence_is_the_connection_status():
    """The rule has to be a **named step at the top**, before 3.1.

    Placed inside 3.1 it would be read as part of running a checkup, which is
    exactly the case where it does not help (the user is already waiting on the
    command). The heading is what makes it the first thing, and the numbering
    (3.0, before 3.1) is the pin.
    """
    assert "### 3.0 开工第一句必须报连接状态" in SOP
    assert SOP.index("### 3.0") < SOP.index("### 3.1 审板子")
    section = SOP.split("### 3.0")[1].split("### 3.1")[0]
    # Both directions of the rule, because "报连接状态" alone does not say what to
    # do when the answer is "not connected" — and that is the case a new user hits.
    assert "哪个工程" in section and "哪个窗口" in section, (
        "the connected case must name both the project and the window"
    )
    assert "怎么修" in section, "the unconnected case names the repair"
    assert "bridge start" in section, "and the repair is the command, not a gesture"


def test_the_line_the_sop_tells_the_model_to_copy_really_exists():
    """「照抄 `bridge status` 的结论行」 — so the conclusion line has to be one line.

    The two shapes the rule quotes (`已连接 N 个窗口：…` and the 未连接 repair) are
    asserted against `status_summary` rather than against a copy of the text, so a
    reword of the daemon's sentence goes red here instead of leaving the SOP
    quoting a sentence that no longer appears.
    """
    connected = daemon_module.status_summary({
        "connector": True, "windows": [{"windowKey": "a", "projectName": "毕设FOC驱动板"}],
    })
    assert connected.startswith("已连接 1 个窗口：")
    assert "\n" not in connected
    unconnected = daemon_module.status_summary({"connector": False})
    assert unconnected.startswith("未连接")
    for line in (connected, unconnected):
        # Every arrow/quote the SOP shows the model is a shape that exists.
        assert " " in line
    assert "已连接" in SOP and "未连接" in SOP, (
        "the SOP quotes both shapes of the conclusion line; one of them is not "
        "what the daemon prints any more"
    )


def test_the_sop_does_not_invent_a_third_way_to_report_status():
    """The rule's last line forbids paraphrasing, so the SOP must point at the
    machine's two sources and nothing else.

    If a third instruction appeared here (「也可以说已就绪」), the two commands and
    the SOP would be three places to keep in agreement, which is the drift this
    issue is trying to remove.
    """
    section = SOP.split("### 3.0")[1].split("### 3.1")[0]
    assert "boardwise doctor" in section
    assert "boardwise bridge status" in section
    assert "不许你另编一套说法" in section


# --------------------------------------------------------------------------
# 条 3: the doctor's pointers and the manual's steps
# --------------------------------------------------------------------------


def test_every_step_doctor_points_at_is_a_step_the_manual_has():
    """The anti-drift pin, at the document level (69 条 3: 「检查器不过时，文档会过时」).

    `test_069c` asserts the same table against the same file from the code's side;
    this one is the documentation claim — if a future edit renumbers
    `getting-started.md`, this is what says 「the pointers are now wrong」, in the
    file whose job is to hold the claims.
    """
    sections = {int(number) for number in
                re.findall(r"^## 第 (\d+) 步", GETTING_STARTED, re.MULTILINE)}
    assert sections, "getting-started.md's step headings are what doctor points at"
    pointed = {hint for hint in cli.DOCTOR_STEP_HINTS.values() if hint}
    assert pointed <= sections, (
        f"doctor points at steps {sorted(pointed - sections)} that "
        "docs/getting-started.md does not have"
    )


def test_the_manual_documents_the_guided_walkthrough_that_doctor_prints():
    """The manual must describe the block the reader will actually see.

    If `doctor` grew an ordered 「按这个顺序做」 block and the manual still said
    「每一条都自己带修复建议」, a reader following the manual would read the output
    as ten separate facts rather than five steps. One sentence is enough, and it
    has to name what changed.
    """
    assert "按这个顺序做" in GETTING_STARTED
    assert "归并" in GETTING_STARTED or "合并" in GETTING_STARTED, (
        "the manual must say that red lines are grouped, or the step count will "
        "look like checks went missing"
    )


def test_the_manual_and_the_sop_agree_on_which_file_the_engineer_reads():
    """One audience, one file, stated in both places.

    The SOP tells the model to fill `review-summary.md`; the manual tells the
    engineer what they will receive. If the manual still said 「report.md 就是给你看的那份」
    the two documents would send the reader to different files, and the split this
    issue exists to create would be invisible to the person it was made for.
    """
    assert cli.REVIEW_SUMMARY_FILE in SOP
    assert cli.REVIEW_SUMMARY_FILE in GETTING_STARTED
