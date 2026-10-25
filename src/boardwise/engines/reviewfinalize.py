"""537D2a1: the **content** validator for one finalized ``review-summary.md``.

Why this module exists. ``boardwise checkup`` writes ``review-summary.md`` as a
skeleton: every finding gets a row whose location chain is prefilled from the
machine ledger, and the model fills the two blank columns, the connection
status, the pending questions and the next steps. Nothing checked the filled
file. A summary could keep the skeleton comments, claim a pass the report does
not support, copy ``summary.conclusion`` (the *narrow* sentence) into the
``**结论：**`` line instead of ``conclusion.oneLiner``, or prune the evidence
disclosures — and every one of those reads as a delivered review.

So this module compares **two things it was handed** — the already-written
``report.json`` (a dict) and the filled summary (a string) — and returns the
disagreements as a list of ``{code, path, message}`` rows. It is deliberately
not a gate and not a renderer:

* it **reads** its two arguments; it never recomputes a verdict, never writes a
  file, and never opens a socket or the editor;
* ``[]`` means **the delivered text agrees with the report** — it does *not*
  mean the board is ok. A review with pending warnings, a needs-manual row and a
  ``partial`` delivery is a perfectly consistent delivery and validates clean;
* every judgement it can make is reused from the section that owns it —
  ``engines.checkup`` (location chains, the skeleton's blank cells, the triage
  predicates, the conclusion vocabulary, the environment section) and
  ``engines.evidence`` (the six channels and the derived coverage/delivery).
  There is no second arithmetic for pending counts or coverage here;
* the order is fixed (the seven check groups below, then the report's own input
  order inside each group), so the same two inputs always produce the same list.

It also owns the step's one **synchronizing** function,
``synchronize_review_summary_sections``. A delivery's two machine sections —
environment and evidence — are re-rendered from the report through the *same*
renderers ``checkup`` wrote them with (no second format, no recomputed
coverage), and every byte outside those two headings is left exactly as the
human wrote it. That function is a pure text transform too: no file is opened
here; the CLI is the only caller that writes.

The seven groups, in the order they are checked:

1. the main findings table — ``## 2. 逐条问题（N 条）``, seven columns, one row
   per ``report.location_chains`` entry compared field by field. Only that one
   table is parsed: a second, hand-written table (2b) is outside this
   validator's contract, and its rows are never read as findings;
2. the human sections that must be filled (1 连接状态 / 3 待确认 / 4 下一步) and
   the skeleton's own comments and blank cells, which must be gone;
3. the one authoritative conclusion — ``report.conclusion`` and the
   ``**结论：**`` line;
4. the warning triage ledger, recomputed through checkup's predicates and
   compared with the completion counts and the summary's own numbers;
5. the environment / evidence disclosure, recomputed through
   ``evidence_coverage`` / ``evidence_delivery``;
6. datasheet wording that may not be used while the datasheet channel is open;
7. a ``suspected`` cross-view, which may not be delivered as confirmed.

Nothing here imports ``boardwise.cli``: the CLI is the caller's business, and a
pure validator that needed it would be the wrong shape for the finalize step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .checkup import (
    ALLOWED_NEXT_ACTIONS,
    CHAINS_KEY,
    ENVIRONMENT_HEADING,
    REVIEW_SUMMARY_BLANK_ADVICE,
    REVIEW_SUMMARY_BLANK_ANALYSIS,
    VERDICT_COMPLETE,
    chain_text,
    render_environment_markdown,
    triage_slot_is_closed,
    triage_slot_is_manual,
    unreviewed_clearing_note,
)
from .evidence import (
    CHANNEL_ORDER,
    CHANNEL_STATUSES,
    DISCLOSURE_FOCUS_RESTORE_FAILED,
    EVIDENCE_HEADING,
    STATUS_NOT_APPLICABLE,
    STATUS_OK,
    evidence_coverage,
    evidence_delivery,
    render_evidence_markdown,
)

# ---------------------------------------------------------------------------
# the table's frozen shape
# ---------------------------------------------------------------------------

#: ``review-summary.md``'s main table has exactly these seven columns. The
#: number is the contract: a row that splits into eight is a pipe that was not
#: escaped (``checkup._cell`` escapes every ``|`` in a cell as ``\|``), and a
#: row that splits into six has lost a column. Neither is compared field-wise.
TABLE_COLUMNS = 7

ANALYSIS_COLUMN = 5
ADVICE_COLUMN = 6

#: The zero-findings body row `checkup.render_review_summary` writes. It is the
#: **only** row allowed when the report has no findings: a hand-written
#: 「没有发现」 row would be prose in a table whose columns mean something else.
EMPTY_ROW_CELLS = ("—", "—", "—", "—", "本次审查没有 finding", "—", "—")

#: The three skeleton comments the finalize step must have replaced. They are
#: prefixes on purpose: the rest of each comment is wording, and a wording edit
#: must not turn a leftover comment into a clean file. The header comment at the
#: top of the skeleton is **not** in this list — issue #69's 收尾 step names
#: these three, and a validator that judged the header would be inventing a rule
#: the SOP never wrote.
SKELETON_COMMENTS: tuple[tuple[str, str], ...] = (
    ("<!-- AI 在这里写", "第 1 节「连接状态」的骨架注释还在"),
    ("<!-- needs_datasheet 非空时", "第 3 节「待确认」的骨架注释还在"),
    ("<!-- 1. / 2. / 3.", "第 4 节「下一步」的骨架注释还在"),
)

#: ``allowedNextActions`` ids this tool may offer (537C2's frozen three). The
#: report owns the list; the validator only asks whether a row names something
#: else, because a fourth id would be a next step nobody authorised.
ALLOWED_NEXT_ACTION_IDS = frozenset(action["id"] for action in ALLOWED_NEXT_ACTIONS)

#: ``TODO`` / ``TBD`` / ``待填`` are placeholders wherever a human was supposed
#: to write. Word-ish boundaries only, so a designator such as ``TBD1`` is not
#: read as a placeholder — that is a legal reference name, not a note to self.
_TODO_RE = re.compile(r"(?<![A-Za-z])(?:TODO|TBD)(?![A-Za-z])|待填", re.IGNORECASE)

#: The four section headings the SOP numbers. Section 2 is matched separately
#: because its heading also carries the finding count.
_SECTION_1_RE = re.compile(r"^1\s*[.．]\s*连接状态")
_SECTION_2_RE = re.compile(r"^2\s*[.．]\s*逐条问题")
_SECTION_3_RE = re.compile(r"^3\s*[.．]\s*待确认")
_SECTION_4_RE = re.compile(r"^4\s*[.．]\s*下一步")
#: The count inside section 2's heading. Tolerant of full-width parentheses,
#: which is what the renderer prints, and half-width ones, which a hand edit may.
_HEADING_COUNT_RE = re.compile(r"[（(]\s*(\d+)\s*条\s*[）)]")

#: The one authoritative line the SOP writes above the sections.
_CONCLUSION_PREFIX = "**结论："
_CONCLUSION_LINE_RE = re.compile(r"^\*\*结论：(?P<text>.*?)\*\*(?P<tail>.*)$")

#: The positive phrasings a summary may not use while ``mayQuotePassed`` is
#: false. They are the words a reader takes as 「板子过了」; an exit code is not
#: one of them (``exitCode 0 ≠ 可投板``, 188B).
_PASS_CLAIMS = ("审查通过", "已通过", "可以投板", "可投板", "可以打样", "可打样")

#: Negations that make a positive phrase part of a legitimate disclosure
#: (「不能写成已与手册核对」「未证实」). They only license a phrase in **their own
#: clause**, and only when they sit close to it: a negation anywhere earlier in
#: the line does not excuse a later claim (「未完成 PCB 视觉复核；可以投板」 is a
#: pass claim, not a disclosure).
_NEGATIONS = (
    "不能", "不得", "不许", "不可", "无法", "未", "禁止", "严禁", "不是", "并非",
)

#: Where a clause ends. A negation does not reach across one of these.
_CLAUSE_BOUNDARIES = "，,。.；;！!？?\n"

#: The conjunctions that also cut a clause without punctuation: 「未完成 PCB 视觉
#: 复核**但**可以投板」 negates the read, not the claim. Longest first, so `但是`
#: cuts after both characters rather than after `但`.
_CLAUSE_WORDS = ("但是", "然而", "不过", "同时", "但", "却")

#: The words that may sit **between** a negation and the claim it negates. The
#: operator is what gets negated (「不得当作已确认」), or the claim is quoted
#: rather than made (「不能写「审查通过」」). Deliberately a closed lexicon and
#: not a length window: 「未完成 PCB 视觉复核可以投板」 has ordinary words in
#: between, and those make it a claim, not a disclosure.
_NEGATION_CONNECTORS = (
    "据此", "直接", "认定", "声称", "视为", "看作", "看做", "写成", "当作",
    "当成", "写", "说", "称", "保证", "确认", "判断", "标记", "算作",
)

#: Quotes and brackets are formatting, not words: 「不能写「审查通过」」 leaves
#: `写「` between the negation and the phrase, and the bracket is not content.
_NEGATION_IGNORED = "「」『』“”\"'《》【】（）() \t"

#: The triage sentences the summary may carry, and what each one means. Closed =
#: every slot that is **not** pending (537B's arithmetic, not a second one).
_CLOSED_CLAIM_RE = re.compile(r"(\d+)\s*条\s*(?:warning|警告|警告项)?\s*已\s*分诊")
_CLOSED_CLAIM_ALT_RE = re.compile(r"已\s*分诊\s*[:：]?\s*(\d+)")
_PENDING_CLAIM_RE = re.compile(r"待\s*分诊\s*[:：]?\s*(\d+)")
_PENDING_CLAIM_ALT_RE = re.compile(r"(\d+)\s*条?\s*待\s*分诊")
_MANUAL_CLAIM_RE = re.compile(
    r"(?:needsManual|needs-manual|需人工|人工复核)\s*[:：]?\s*(\d+)", re.IGNORECASE
)
#: ``N 条/项 需人工`` **and** the measure-word-free form the real summary uses:
#: 「7 条 warning 已分诊（12 条中 5 条待核 / 1 需人工看）」. The quantifier is
#: optional because the delivered text omits it, and a number the reader can see
#: is a number this validator has to compare.
_MANUAL_CLAIM_ALT_RE = re.compile(
    r"(\d+)\s*(?:条|项)?\s*(?:需人工|needsManual)", re.IGNORECASE
)
#: The words that count as the needs-manual disclosure at all.
_MANUAL_WORD_RE = re.compile(r"needs[-_ ]?manual|needsManual|需人工|人工复核", re.IGNORECASE)

#: The sentence that must not appear while anything is still pending.
_ALL_TRIAGED = "全部已分诊"

#: Datasheet wording that is only allowed when the channel is closed **and** no
#: part was accepted unknown. Each entry is (label, pattern); the label travels
#: in the message so the reader knows which claim was seen.
_DATASHEET_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "checked-with-manual",
        re.compile(r"已[与和][^。；\n]{0,40}?手册[^。；\n]{0,20}?核对"),
    ),
    (
        "agrees-with-manual",
        re.compile(r"与[^。；\n]{0,40}?手册[^。；\n]{0,10}?(?:一致|相符)"),
    ),
    ("manual-confirmed", re.compile(r"手册已确认")),
    ("manual-number-claim", re.compile(r"手册(?:要求|规定|显示)[^。；\n]{0,60}?\d")),
)

#: A ``suspected`` cross-view is a *question*. The same line may not resolve it.
_CROSSVIEW_CONTEXT = ("crossView", "PCB", "原理图", "错版", "引脚", "焊盘")
_CROSSVIEW_CONFIRMED = ("实锤", "已确认", "证实")
_CROSSVIEW_SUSPECTED = "疑似"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _issue(code: str, path: str, message: str) -> dict:
    """One row of the result: a stable code, where it is, and why it matters."""
    return {"code": code, "path": path, "message": message}


def _dedupe(issues: Iterable[dict]) -> list[dict]:
    """Drop exact repeats, keeping the first — a fixed walk cannot shuffle."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for issue in issues:
        key = (issue["code"], issue["path"], issue["message"])
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _int_or_none(value: Any) -> int | None:
    """An int this validator may compare, or none. ``bool`` is not a count."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _expected_cell(value: Any) -> str:
    """The text a table cell must carry, under the renderer's own semantics.

    ``checkup._cell`` escapes ``|`` as ``\\|``, folds a newline into a space and
    strips both ends. :func:`split_markdown_row` undoes the escape; the newline
    and the strip have to be undone here or a legal multi-line problem text
    would be reported as a mismatch.
    """
    return str("" if value is None else value).replace("\n", " ").strip()


def split_markdown_row(line: str) -> list[str] | None:
    """One GFM table row as its cells, with ``\\|`` unescaped to a literal ``|``.

    This is the inverse of ``checkup._cell`` and it is the one parser the
    finalize path shares with the markdown readers: a ``|`` that was escaped by
    the renderer belongs **inside** a cell, so a location chain such as
    ``J1|J2`` stays one cell and the row still has seven columns. Only the
    two-character escape ``\\|`` is special; every other backslash is literal
    (the renderer never emits one before a pipe, and guessing otherwise would
    silently drop text).

    ``None`` when the line is not a table row at all (no leading ``|``), so a
    caller can tell 「not a row」 from 「a row with no cells」.
    """
    if not isinstance(line, str):
        return None
    text = line.strip()
    if not text.startswith("|"):
        return None
    body = text[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    buffer: list[str] = []
    position = 0
    length = len(body)
    while position < length:
        char = body[position]
        if char == "\\" and position + 1 < length and body[position + 1] == "|":
            buffer.append("|")
            position += 2
            continue
        if char == "|":
            cells.append("".join(buffer))
            buffer = []
            position += 1
            continue
        buffer.append(char)
        position += 1
    cells.append("".join(buffer))
    return cells


def _is_separator_row(cells: list[str] | None) -> bool:
    """``|---|---|…|`` — the delimiter GFM requires under a header.

    It must have **the same seven columns** as the header. A one-cell
    ``|---|`` renders as a table header with no body columns, so a complete
    header above it is not a table: the rows would not be read as findings by
    anything downstream.
    """
    if not cells or len(cells) != TABLE_COLUMNS:
        return False
    for cell in cells:
        text = cell.strip()
        if not text or set(text) - set("-:"):
            return False
        if "-" not in text:
            return False
    return True


def _clause_start(line: str, position: int) -> int:
    """Where the clause holding ``position`` begins.

    After the last punctuation boundary **or** contrast conjunction — 「但」 and
    its family turn the sentence around, so what was negated before them is
    about something else.
    """
    head = line[: max(position, 0)]
    start = 0
    for index in range(len(head) - 1, -1, -1):
        if head[index] in _CLAUSE_BOUNDARIES:
            start = index + 1
            break
    for word in _CLAUSE_WORDS:
        index = head.rfind(word)
        if index >= 0:
            start = max(start, index + len(word))
    return start


def _negation_connector_ok(connector: str) -> bool:
    """Whether everything between a negation and the claim is connector only.

    An empty connector is the direct case (「未证实」). Otherwise the connector
    has to be built from :data:`_NEGATION_CONNECTORS` — 「据此认定」「直接声称」
    「写成」「当作」 are, 「完成 PCB 视觉复核」 is not.
    """
    text = connector
    for char in _NEGATION_IGNORED:
        text = text.replace(char, "")
    if not text:
        return True
    ordered = sorted(_NEGATION_CONNECTORS, key=len, reverse=True)
    position = 0
    while position < len(text):
        for word in ordered:
            if text.startswith(word, position):
                position += len(word)
                break
        else:
            return False
    return True


def _negated_before(line: str, position: int) -> bool:
    """Whether the **clause** before ``position`` negates the phrase there.

    Three things must all hold, and each one has a measured false positive
    behind it:

    * the negation is before the phrase — 「不能写通过」 is a disclosure, while
      「通过，不是问题」 is still a pass claim;
    * it is in the **same clause**. 「未完成 PCB 视觉复核；可以投板」 puts 「可以投板」
      after a boundary, where nothing negates it; the old whole-line reading
      waved it through. The same holds for the conjunction cut —
      「未完成 PCB 视觉复核但可以投板」, 「未读手册但与 X 手册一致」, and, under a
      suspected cross-view, 「未完成逐脚核对但 PCB 错版已确认」;
    * what sits between the negation and the phrase is **connector** only
      (:func:`_negation_connector_ok`) — the operator is the thing being
      negated (「不得当作已确认」, 「不能据此认定可以投板」), not a distant word
      that happens to be negative. A length window cannot tell those apart:
      「未完成 PCB 视觉复核可以投板」 and 「不能据此认定可以投板」 are the same
      length and opposite meanings.

    「未证实」 stays a disclosure because the connector is empty;
    「与手册不一致」 is handled by the caller, which knows the suffix.
    """
    clause = line[_clause_start(line, position) : max(position, 0)]
    if not clause:
        return False
    nearest = -1
    connector = ""
    for token in _NEGATIONS:
        index = clause.rfind(token)
        if index < 0:
            continue
        end = index + len(token)
        if end > nearest:
            nearest = end
            connector = clause[end:]
    if nearest < 0:
        return False
    return _negation_connector_ok(connector)


@dataclass
class _Section:
    """One ``## `` block of the summary: its heading, line and body lines."""

    heading: str
    line: int
    body: list[tuple[int, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(text for _number, text in self.body)


def _split_sections(summary: str) -> list[_Section]:
    """Split at ``## `` headings, keeping every line's 1-based number.

    Line numbers are the ``path`` of a content issue: they point a reader (and a
    test) at the exact line without depending on a section's own internal
    numbering.
    """
    sections: list[_Section] = []
    current: _Section | None = None
    for number, text in enumerate(summary.splitlines(), 1):
        stripped = text.strip()
        if stripped.startswith("## "):
            current = _Section(heading=stripped[3:].strip(), line=number)
            sections.append(current)
            continue
        if current is not None:
            current.body.append((number, text))
    return sections


def _find_section(sections: Iterable[_Section], pattern: re.Pattern[str]) -> _Section | None:
    """The first section whose heading matches — the renderer writes one of each."""
    for section in sections:
        if pattern.match(section.heading):
            return section
    return None


def _strip_comments(text: str) -> str:
    """Remove HTML comments, including an unterminated one.

    An unfilled skeleton section contains a comment and nothing else. A regex
    that only removed *closed* comments would read the leftover ``<!-- …`` as
    content and let an empty section pass, so anything from an unclosed ``<!--``
    to the end is removed too.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    head, marker, _tail = text.partition("<!--")
    return head if marker else text


def _meaningful_text(text: str) -> str:
    """What is left of a section once blank lines and rules are dropped."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) == {"-", "*", "_", " "}:
            continue
        lines.append(stripped)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the machine-section sync (537D2b1): two headings, re-rendered from the report
# ---------------------------------------------------------------------------

#: The **only** sections ``review finalize`` may rewrite, in the order they are
#: synchronised. Each row is (exact heading, report key, the renderer that owns
#: the format); the shared renderers are the compatibility promise — this module
#: must never grow a second spelling of either section.
_MACHINE_SECTIONS = (
    (ENVIRONMENT_HEADING, "environment", render_environment_markdown),
    (EVIDENCE_HEADING, "evidence", render_evidence_markdown),
)


def _section_newline(line: str) -> str:
    """The line terminator a section will use: its heading line's own."""
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return "\n"


def _replace_machine_section(text: str, heading: str, lines: list[str]) -> str:
    """Replace one exact heading's block; return ``text`` untouched when absent.

    The block runs from the heading line to the next ``## `` heading (the same
    boundary :func:`_split_sections` uses), or to EOF. Everything before and
    after it is spliced back verbatim, which is what keeps a CRLF file's human
    prose, a 2b analysis block and sections 3/4 byte-identical.
    """
    offset = 0
    starts: list[tuple[int, str]] = []
    for line in text.splitlines(keepends=True):
        starts.append((offset, line))
        offset += len(line)
    for index, (start, line) in enumerate(starts):
        if line.rstrip("\r\n") != heading:
            continue
        end = len(text)
        for after in range(index + 1, len(starts)):
            if starts[after][1].strip().startswith("## "):
                end = starts[after][0]
                break
        newline = _section_newline(line)
        # The renderer puts one separator newline before the **next** section, so
        # a real skeleton has three newlines (two blank lines) between two
        # machine sections. The gap belongs to the text being replaced, and its
        # exact bytes (count *and* CRLF-or-LF) are carried through: the rendered
        # lines replace the content, never the spacing a file already uses.
        tail = re.search(r"(?:\r\n|\r|\n)+\Z", text[start:end])
        trailing = tail.group(0) if tail else newline
        block = newline.join(lines).rstrip("\r\n") + trailing
        return text[:start] + block + text[end:]
    return text


def synchronize_review_summary_sections(report: dict, summary: str) -> str:
    """Re-render the two machine sections of ``summary`` from ``report``.

    The returned text differs from the input **only** inside
    ``## 审查环境与权限（environment）`` and ``## 证据覆盖（evidence）``; those
    blocks are the authoritative ``render_environment_markdown`` /
    ``render_evidence_markdown`` output for the report's own sections. Every
    byte between and around them — the conclusion line, the findings table's
    human analysis/advice, a 2b block, sections 3/4, the file's CRLF endings —
    is carried through exactly.

    Fails closed in the two honest ways a text transform can:

    * a heading that is **not** in the text is not injected: the validator's
      ``summary-*-heading-missing`` remains the answer, never a guessed section;
    * a report with no (or an empty) ``environment``/``evidence`` section leaves
      its block alone: a missing machine section is ``*-missing``, not text this
      function may blank or invent. A section the shared renderer cannot read (a
      nested field of the wrong shape) is left alone for the same reason — the
      validator names the structural problem, and nothing here guesses a
      disclosure.

    Neither argument is mutated and no file is touched. Deterministic and
    idempotent: the second call over this function's own output is a no-op.
    """
    if not isinstance(report, dict) or not isinstance(summary, str):
        return summary
    for heading, key, render in _MACHINE_SECTIONS:
        try:
            rendered = render(report.get(key))
        except (AttributeError, KeyError, TypeError):
            # A section the shared renderer cannot read (a nested field of the
            # wrong shape) is not one this function may invent or blank. Leave
            # the human's text untouched and let the validator's own structural
            # checks answer — no traceback, no guessed disclosure.
            continue
        if not rendered:
            continue
        summary = _replace_machine_section(summary, heading, rendered)
    return summary


# ---------------------------------------------------------------------------
# 1. the main findings table
# ---------------------------------------------------------------------------


def _chain_rows(report: dict, issues: list[dict]) -> tuple[list[tuple[int, dict]], int | None]:
    """``[(index, chain)]`` from the report, plus the finding count (or none).

    The two ledgers must agree: ``location_chains`` is the machine's one row per
    finding, and a summary table cannot be checked against a ledger that is
    missing, is not a list, or has a different length. None of those is read as
    zero findings.
    """
    findings = report.get("findings")
    chains = report.get(CHAINS_KEY)
    if not isinstance(findings, list):
        issues.append(
            _issue(
                "findings-not-list",
                "report.findings",
                "report.json 的 findings 必须是 list；缺键或类型不对不等于「没有 finding」。",
            )
        )
        findings = None
    if chains is None:
        issues.append(
            _issue(
                "location-chains-missing",
                f"report.{CHAINS_KEY}",
                f"report.json 缺 {CHAINS_KEY} 节：主表没有可对拍的机器账。",
            )
        )
        chains = None
    elif not isinstance(chains, list):
        issues.append(
            _issue(
                "location-chains-not-list",
                f"report.{CHAINS_KEY}",
                f"report.json 的 {CHAINS_KEY} 必须是 list（每行一条 finding），实际是 "
                f"{type(chains).__name__}。",
            )
        )
        chains = None
    if findings is not None and chains is not None and len(chains) != len(findings):
        issues.append(
            _issue(
                "location-chains-count-mismatch",
                f"report.{CHAINS_KEY}",
                f"findings 有 {len(findings)} 条，{CHAINS_KEY} 有 {len(chains)} 行；"
                "两张账必须先对齐，主表才有意义。",
            )
        )

    rows: list[tuple[int, dict]] = []
    for position, chain in enumerate(chains or []):
        if not isinstance(chain, dict):
            issues.append(
                _issue(
                    "location-chains-row-not-dict",
                    f"report.{CHAINS_KEY}[{position}]",
                    "定位链每一行必须是 dict（index/severity/rule_id/…）；"
                    "本行没有可读字段，不能参与对拍。",
                )
            )
            continue
        index = _int_or_none(chain.get("index"))
        if index is None:
            issues.append(
                _issue(
                    "location-chains-index-missing",
                    f"report.{CHAINS_KEY}[{position}].index",
                    "定位链行缺整数 index：主表的 # 列没有对拍对象（按输入位置兜底时"
                    "顺序/重复都不可信）。",
                )
            )
            index = position
        rows.append((index, chain))

    if findings is not None:
        expected: int | None = len(findings)
    elif chains is not None:
        expected = len(chains)
    else:
        expected = None
    return rows, expected


def _check_section_two(
    summary: str,
    rows: list[tuple[int, dict]],
    expected_count: int | None,
    issues: list[dict],
) -> None:
    """Compare ``## 2. 逐条问题`` with the report's chains, field by field."""
    sections = _split_sections(summary)
    section = _find_section(sections, _SECTION_2_RE)
    if section is None:
        issues.append(
            _issue(
                "summary-findings-heading-missing",
                "summary#2",
                "找不到 `## 2. 逐条问题（N 条）`：主表是逐条交付的主体，不能整节省略。",
            )
        )
        return
    match = _HEADING_COUNT_RE.search(section.heading)
    heading_count = int(match.group(1)) if match else None
    if heading_count is None:
        issues.append(
            _issue(
                "summary-findings-heading-count-missing",
                "summary#2",
                f"标题 {section.heading!r} 里没有可读的「N 条」：无法对拍条数。",
            )
        )
    elif expected_count is not None and heading_count != expected_count:
        issues.append(
            _issue(
                "summary-findings-count-mismatch",
                "summary#2",
                f"标题写 {heading_count} 条，report.json 里是 {expected_count} 条。",
            )
        )

    table = [(number, text) for number, text in section.body if text.lstrip().startswith("|")]
    if not table:
        issues.append(
            _issue(
                "summary-findings-table-missing",
                "summary#2",
                "第 2 节没有主表（找不到以 `|` 开头的行）：该节只有标题等于没写。",
            )
        )
        return
    header = split_markdown_row(table[0][1])
    separator = split_markdown_row(table[1][1]) if len(table) > 1 else None
    if header is None or len(header) != TABLE_COLUMNS:
        issues.append(
            _issue(
                "summary-findings-table-header",
                f"summary:line-{table[0][0]}",
                f"表头不是 {TABLE_COLUMNS} 列（解出 {len(header) if header else 0} 列）。",
            )
        )
    elif not (
        header[0].strip() == "#"
        and header[1].strip() == "级别"
        and header[2].strip() == "规则"
        and "定位链" in header[3]
        and header[4].strip() == "问题"
        and header[5].strip() == "分析"
        and header[6].strip() == "建议"
    ):
        issues.append(
            _issue(
                "summary-findings-table-header",
                f"summary:line-{table[0][0]}",
                f"表头七列须是 # / 级别 / 规则 / 定位链 / 问题 / 分析 / 建议，"
                f"实际是 {[cell.strip() for cell in header]}。",
            )
        )
    if not _is_separator_row(separator):
        issues.append(
            _issue(
                "summary-findings-table-separator",
                f"summary:line-{table[1][0] if len(table) > 1 else table[0][0]}",
                "表头下面缺 GFM 分隔行（`|---|---|…|`），表格在渲染时不会成立。",
            )
        )

    data = [(number, split_markdown_row(text)) for number, text in table[2:]]

    if not rows:
        if expected_count:
            # The ledger itself is unreadable (reported above): there is nothing
            # to compare the rows with, and calling the table "zero findings"
            # here would turn a missing ledger into a clean empty table.
            return
        # Zero findings: the skeleton's em-dash row is the only legal body.
        parsed = [cells for _number, cells in data if cells is not None]
        legal = [
            [cell.strip() for cell in cells] == list(EMPTY_ROW_CELLS) for cells in parsed
        ]
        if len(parsed) != 1 or not legal[0]:
            issues.append(
                _issue(
                    "summary-findings-table-zero-row",
                    "summary#2",
                    "report 里没有 finding 时，表体只许骨架那一行 "
                    "`| — | — | — | — | 本次审查没有 finding | — | — |`；"
                    f"实际 {len(parsed)} 行。",
                )
            )
        return

    if not data:
        issues.append(
            _issue(
                "summary-findings-table-row-count",
                "summary#2",
                f"report 有 {len(rows)} 条 finding，表体一行都没有。",
            )
        )
        return
    if len(data) != len(rows):
        issues.append(
            _issue(
                "summary-findings-table-row-count",
                "summary#2",
                f"表体 {len(data)} 行，report 有 {len(rows)} 条 finding。",
            )
        )

    expected_indexes = [str(index) for index, _chain in rows]
    parsed_indexes: list[str] = []
    for number, cells in data:
        if cells is None or len(cells) != TABLE_COLUMNS:
            issues.append(
                _issue(
                    "summary-findings-table-row-columns",
                    f"summary:line-{number}",
                    f"该行解出 {len(cells) if cells else 0} 列，不是 {TABLE_COLUMNS} 列；"
                    "单元格里的 `|` 必须先转义成 `\\|`（checkup 的骨架就是这么写的），"
                    "未转义的 `|` 会把一行拆成两行。",
                )
            )
            continue
        parsed_indexes.append(cells[0].strip())

    for index_text in parsed_indexes:
        if index_text not in expected_indexes:
            issues.append(
                _issue(
                    "summary-findings-table-row-unknown",
                    "summary#2",
                    f"表里有一行的 # 是 {index_text!r}，report 的定位链里没有这个 index。",
                )
            )
    for index_text in expected_indexes:
        count = parsed_indexes.count(index_text)
        if count == 0:
            issues.append(
                _issue(
                    "summary-findings-table-row-missing",
                    f"summary#2:index-{index_text}",
                    f"定位链 #{index_text} 在主表里没有对应行：逐条交付缺了一条。",
                )
            )
        elif count > 1:
            issues.append(
                _issue(
                    "summary-findings-table-row-duplicate",
                    f"summary#2:index-{index_text}",
                    f"定位链 #{index_text} 在主表里出现了 {count} 次。",
                )
            )
    if (
        parsed_indexes
        and len(parsed_indexes) == len(expected_indexes)
        and sorted(parsed_indexes) == sorted(expected_indexes)
        and parsed_indexes != expected_indexes
    ):
        issues.append(
            _issue(
                "summary-findings-table-row-order",
                "summary#2",
                f"主表行序与 report 的定位链不一致：表里是 {parsed_indexes}，"
                f"report 是 {expected_indexes}。",
            )
        )

    by_index: dict[str, tuple[int, list[str]]] = {}
    for number, cells in data:
        if cells is None or len(cells) != TABLE_COLUMNS:
            continue
        by_index.setdefault(cells[0].strip(), (number, cells))

    for index, chain in rows:
        entry = by_index.get(str(index))
        if entry is None:
            continue
        number, cells = entry
        _compare_row(number, cells, chain, str(index), issues)


def _compare_row(
    number: int, cells: list[str], chain: dict, index_text: str, issues: list[dict]
) -> None:
    """Field-by-field comparison of one parsed row against its chain."""
    path = f"summary:line-{number}"
    if cells[0].strip() != index_text:
        issues.append(
            _issue(
                "summary-findings-table-number",
                path,
                f"# 列写 {cells[0].strip()!r}，定位链 index 是 {index_text!r}。",
            )
        )
    pairs = (
        ("severity", cells[1], _expected_cell(chain.get("severity")), "级别"),
        ("rule", cells[2], _expected_cell(chain.get("rule_id")), "规则"),
        ("chain", cells[3], _expected_cell(chain_text(chain)), "定位链"),
        ("problem", cells[4], _expected_cell(chain.get("problem")), "问题"),
    )
    for suffix, actual, expected, label in pairs:
        if actual.strip() != expected:
            issues.append(
                _issue(
                    f"summary-findings-table-{suffix}",
                    path,
                    f"{label}列与 report 不一致：表里 {actual.strip()!r}，"
                    f"report 是 {expected!r}（定位链不许改字，只许填分析/建议）。",
                )
            )
    _check_blank_column(number, cells[ANALYSIS_COLUMN], "analysis", issues)
    _check_blank_column(number, cells[ADVICE_COLUMN], "advice", issues)


def _check_blank_column(number: int, cell: str, suffix: str, issues: list[dict]) -> None:
    """The two columns the model fills must be filled with prose, not a comment."""
    label = "分析" if suffix == "analysis" else "建议"
    text = cell.strip()
    path = f"summary:line-{number}"
    if not text:
        issues.append(
            _issue(
                f"summary-findings-table-{suffix}-empty",
                path,
                f"{label}列是空的：SOP 收尾要求逐行填{label}，空着等于没交付。",
            )
        )
        return
    placeholder = (
        REVIEW_SUMMARY_BLANK_ANALYSIS if suffix == "analysis" else REVIEW_SUMMARY_BLANK_ADVICE
    )
    if "<!--" in text or text == placeholder:
        issues.append(
            _issue(
                f"summary-findings-table-{suffix}-placeholder",
                path,
                f"{label}列还是骨架注释/未删的 HTML 注释，不是给工程师看的文字。",
            )
        )
    match = _TODO_RE.search(text)
    if match:
        issues.append(
            _issue(
                f"summary-findings-table-{suffix}-todo",
                path,
                f"{label}列留着占位 {match.group(0)!r}：这是待填，不是内容。",
            )
        )


# ---------------------------------------------------------------------------
# 2. the human sections, the skeleton's comments and the blank cells
# ---------------------------------------------------------------------------


def _check_human_sections(
    report: dict, summary: str, sections: list[_Section], issues: list[dict]
) -> None:
    """Sections 1 / 3 / 4 must say something, and the skeleton must be gone."""
    for key, pattern in (
        ("1", _SECTION_1_RE),
        ("3", _SECTION_3_RE),
        ("4", _SECTION_4_RE),
    ):
        section = _find_section(sections, pattern)
        if section is None:
            issues.append(
                _issue(
                    f"summary-section-{key}-missing",
                    f"summary#{key}",
                    "人工填写的那一段不在（标题 `## {0}. …` 找不到）。".format(key),
                )
            )
            continue
        body = _strip_comments(section.text)
        if key == "3":
            # 537C2's skeleton prints the clearing instruction in this section
            # every time. It is machine boilerplate, not an answer, so it cannot
            # be what makes an empty section look filled.
            body = body.replace(
                unreviewed_clearing_note(str(report.get("shelfPath") or "")), ""
            )
        if not _meaningful_text(body):
            issues.append(
                _issue(
                    f"summary-section-{key}-empty",
                    f"summary#{key}",
                    f"第 {key} 节只有标题/注释，没有内容：SOP 收尾要求这一段是写给人看的。",
                )
            )
        match = _TODO_RE.search(body)
        if match:
            issues.append(
                _issue(
                    f"summary-section-{key}-todo",
                    f"summary#{key}",
                    f"第 {key} 节留着占位 {match.group(0)!r}：这不是交付内容。",
                )
            )

    lines = summary.splitlines()
    for marker, why in SKELETON_COMMENTS:
        position = next(
            (number for number, text in enumerate(lines, 1) if marker in text), None
        )
        if position is not None:
            issues.append(
                _issue(
                    "summary-skeleton-comment-residue",
                    f"summary:line-{position}",
                    f"{why}：收尾必须把它替换成内容，其余骨架注释一并删掉。",
                )
            )
    for blank in (REVIEW_SUMMARY_BLANK_ANALYSIS, REVIEW_SUMMARY_BLANK_ADVICE):
        position = next(
            (number for number, text in enumerate(lines, 1) if blank in text), None
        )
        if position is not None:
            issues.append(
                _issue(
                    "summary-blank-placeholder-residue",
                    f"summary:line-{position}",
                    f"骨架的空白占位 {blank!r} 还整段留在文件里。",
                )
            )


# ---------------------------------------------------------------------------
# 3. the one authoritative conclusion
# ---------------------------------------------------------------------------


def _conclusion_line(
    lines: list[str],
) -> tuple[int | None, str | None, bool]:
    """``(line number, text inside **, malformed)`` for the top conclusion line."""
    for number, text in enumerate(lines, 1):
        stripped = text.strip()
        if not stripped.startswith(_CONCLUSION_PREFIX):
            continue
        match = _CONCLUSION_LINE_RE.match(stripped)
        if match is None:
            return number, None, True
        return number, match.group("text"), False
    return None, None, False


def _check_conclusion(report: dict, summary: str, issues: list[dict]) -> None:
    """The report's conclusion is the only verdict; the line must quote it."""
    conclusion = report.get("conclusion")
    lines = summary.splitlines()
    number, text, malformed = _conclusion_line(lines)

    if not isinstance(conclusion, dict) or not conclusion:
        issues.append(
            _issue(
                "conclusion-not-dict",
                "report.conclusion",
                "report.json 缺 conclusion 节（或不是非空 dict）：板级结论没有唯一权威，"
                "summary 里那句就没有可对拍的来源。",
            )
        )
        if number is None:
            issues.append(
                _issue(
                    "summary-conclusion-line-missing",
                    "summary",
                    "找不到 `**结论：…**` 行。",
                )
            )
        return

    one_liner = conclusion.get("oneLiner")
    verdict = conclusion.get("verdict")
    may_quote = conclusion.get("mayQuotePassed")
    one_liner_text = one_liner.strip() if isinstance(one_liner, str) else ""
    if not one_liner_text:
        issues.append(
            _issue(
                "conclusion-oneLiner-missing",
                "report.conclusion.oneLiner",
                "conclusion.oneLiner 缺失或为空：顶部那句话没有权威来源。",
            )
        )
    if not isinstance(verdict, str) or not verdict.strip():
        issues.append(
            _issue(
                "conclusion-verdict-missing",
                "report.conclusion.verdict",
                "conclusion.verdict 缺失或为空。",
            )
        )
    if not isinstance(may_quote, bool):
        issues.append(
            _issue(
                "conclusion-mayQuotePassed-missing",
                "report.conclusion.mayQuotePassed",
                "conclusion.mayQuotePassed 缺失或不是布尔：脚本判读的唯一开关不可读。",
            )
        )

    if number is None:
        issues.append(
            _issue(
                "summary-conclusion-line-missing",
                "summary",
                "找不到 `**结论：…**` 行：交付件顶部没有结论。",
            )
        )
    elif malformed:
        issues.append(
            _issue(
                "summary-conclusion-line-malformed",
                f"summary:line-{number}",
                "`**结论：` 行没有闭合的 `**`，无法读出那句结论。",
            )
        )
    elif one_liner_text and text is not None and text.strip() != one_liner_text:
        hint = ""
        report_summary = report.get("summary")
        if isinstance(report_summary, dict) and text.strip() == str(
            report_summary.get("conclusion") or ""
        ).strip():
            hint = "（这是 `summary.conclusion` 的窄义句子，不是 `conclusion.oneLiner`）"
        issues.append(
            _issue(
                "summary-conclusion-mismatch",
                f"summary:line-{number}",
                f"顶部结论与 `conclusion.oneLiner` 不一致：写的是 {text.strip()!r}，"
                f"report 的唯一权威是 {one_liner_text!r}{hint}。",
            )
        )

    completion = report.get("completion")
    if isinstance(completion, dict):
        completion_verdict = completion.get("verdict")
        if (
            isinstance(verdict, str) and verdict.strip()
            and isinstance(completion_verdict, str) and completion_verdict.strip()
            and verdict != completion_verdict
        ):
            issues.append(
                _issue(
                    "conclusion-verdict-mismatch",
                    "report.conclusion.verdict",
                    f"conclusion.verdict={verdict!r}，completion.verdict="
                    f"{completion_verdict!r}：同一份报告两个判决。",
                )
            )

    report_summary = report.get("summary")
    if isinstance(report_summary, dict):
        if conclusion.get("exitCode") != report_summary.get("exitCode"):
            issues.append(
                _issue(
                    "conclusion-exitCode-mismatch",
                    "report.conclusion.exitCode",
                    f"conclusion.exitCode={conclusion.get('exitCode')!r} 与 "
                    f"summary.exitCode={report_summary.get('exitCode')!r} 不一致。",
                )
            )
    else:
        issues.append(
            _issue(
                "report-summary-not-dict",
                "report.summary",
                "report.json 的 summary 必须是 dict（exitCode 从这里读）。",
            )
        )

    if isinstance(may_quote, bool) and isinstance(verdict, str) and verdict.strip():
        expected_quote = verdict == VERDICT_COMPLETE
        if may_quote != expected_quote:
            issues.append(
                _issue(
                    "conclusion-mayQuotePassed-mismatch",
                    "report.conclusion.mayQuotePassed",
                    f"mayQuotePassed={may_quote}，但 verdict={verdict!r}；"
                    "该布尔只能是 `verdict == 'complete'`。",
                )
            )

    if may_quote is False:
        _check_pass_claims(lines, issues)


def _check_pass_claims(lines: list[str], issues: list[dict]) -> None:
    """A non-quotable review may not read as a pass, however it is phrased."""
    for number, line in enumerate(lines, 1):
        for phrase in _PASS_CLAIMS:
            start = line.find(phrase)
            while start >= 0:
                if not _negated_before(line, start):
                    issues.append(
                        _issue(
                            "summary-pass-claim",
                            f"summary:line-{number}",
                            f"`conclusion.mayQuotePassed` 是 false，这一行却写「{phrase}」："
                            "exitCode 0 不等于可投板，否定语境之外不许出现积极措辞。",
                        )
                    )
                    break
                start = line.find(phrase, start + 1)


# ---------------------------------------------------------------------------
# 4. triage consistency
# ---------------------------------------------------------------------------


def _triage_counts(report: dict, issues: list[dict]) -> tuple[int, int, int] | None:
    """Recompute ``(total, pending, manual)`` through checkup's predicates.

    ``None`` when the report cannot be read that way — a missing ledger is a
    named issue, never 「0 条待分诊」.

    A row that is not a dict is **named** and still counted as ``{}``: the two
    predicates read it as 「nobody judged this」 (pending) and 「no needs-manual
    verdict」 (not manual), which is the honest reading — but counting it
    silently would let a ledger of ``[null, null]`` pass as two judged-pending
    rows with no defect stated.
    """
    triage = report.get("warning_triage")
    if not isinstance(triage, list):
        issues.append(
            _issue(
                "triage-ledger-not-list",
                "report.warning_triage",
                "report.json 的 warning_triage 必须是 list；缺键或类型不对会被读成"
                "「没有警告」，那是把未知当零。",
            )
        )
        return None
    slots: list[dict] = []
    for position, slot in enumerate(triage):
        if isinstance(slot, dict):
            slots.append(slot)
            continue
        issues.append(
            _issue(
                "triage-slot-not-dict",
                f"report.warning_triage[{position}]",
                f"该行是 {type(slot).__name__}，不是槽位 dict：它既没有 verdict 也没有"
                " text/key，只能按「未判定」计 pending，不能被当成一条正常槽位。",
            )
        )
        slots.append({})
    pending = sum(1 for slot in slots if not triage_slot_is_closed(slot))
    manual = sum(1 for slot in slots if triage_slot_is_manual(slot))
    return len(slots), pending, manual


def _manual_slot_keys(report: dict) -> list[str]:
    """The ``key`` of every needs-manual slot, in the ledger's own order.

    This is the sequence ``completion.manualReviewRequired`` has to name — one
    row per row a human still owes a look, in the same order. A list of the
    right length naming something else is not the same debt.
    """
    triage = report.get("warning_triage")
    if not isinstance(triage, list):
        return []
    keys: list[str] = []
    for slot in triage:
        if not isinstance(slot, dict) or not triage_slot_is_manual(slot):
            continue
        keys.append(str(slot.get("key") or ""))
    return keys


def _check_triage(report: dict, summary: str, issues: list[dict]) -> None:
    """The completion counts, the ledger and the summary's sentences must agree."""
    counts = _triage_counts(report, issues)
    completion = report.get("completion")
    if not isinstance(completion, dict) or not completion:
        issues.append(
            _issue(
                "completion-not-dict",
                "report.completion",
                "report.json 缺 completion 节（或不是非空 dict）：分诊计数没有对拍对象。",
            )
        )
        return
    if counts is None:
        return
    total, pending, manual = counts
    closed = total - pending

    stored_pending = completion.get("warningsPendingTriage")
    if stored_pending != pending:
        issues.append(
            _issue(
                "triage-pending-count-mismatch",
                "report.completion.warningsPendingTriage",
                f"存的是 {stored_pending!r}，按 warning_triage 重算（triage_slot_is_closed）"
                f"是 {pending} 条待分诊。",
            )
        )
    stored_manual = completion.get("warningsNeedsManual")
    if stored_manual != manual:
        issues.append(
            _issue(
                "triage-manual-count-mismatch",
                "report.completion.warningsNeedsManual",
                f"存的是 {stored_manual!r}，按 needs-manual 重算是 {manual} 条。",
            )
        )
    stored_list = completion.get("manualReviewRequired")
    expected_keys = _manual_slot_keys(report)
    if not isinstance(stored_list, list):
        issues.append(
            _issue(
                "triage-manual-list-missing",
                "report.completion.manualReviewRequired",
                "manualReviewRequired 缺失或不是 list：需人工复核的清单不可读"
                "（没有 needs-manual 行时也必须是 []）。",
            )
        )
    else:
        stored_keys = [
            str(row.get("key") or "") if isinstance(row, dict) else ""
            for row in stored_list
        ]
        if len(stored_list) != manual:
            issues.append(
                _issue(
                    "triage-manual-list-mismatch",
                    "report.completion.manualReviewRequired",
                    f"清单 {len(stored_list)} 行，needs-manual 行数是 {manual}。",
                )
            )
        elif stored_keys != expected_keys:
            issues.append(
                _issue(
                    "triage-manual-list-keys",
                    "report.completion.manualReviewRequired",
                    f"清单的 key 序列是 {stored_keys}，账里的 needs-manual 槽位是 "
                    f"{expected_keys}：等长但点的是别的行，不是同一笔债。",
                )
            )

    lines = summary.splitlines()
    for number, line in enumerate(lines, 1):
        path = f"summary:line-{number}"
        for pattern in (_CLOSED_CLAIM_RE, _CLOSED_CLAIM_ALT_RE):
            for match in pattern.finditer(line):
                value = int(match.group(1))
                if value != closed:
                    issues.append(
                        _issue(
                            "summary-triage-closed-count-mismatch",
                            path,
                            f"写「{value} 条已分诊」，重算已分诊是 {closed} 条"
                            f"（{total} 条里 {pending} 条仍待分诊）。",
                        )
                    )
        for pattern in (_PENDING_CLAIM_RE, _PENDING_CLAIM_ALT_RE):
            for match in pattern.finditer(line):
                value = int(match.group(1))
                if value != pending:
                    issues.append(
                        _issue(
                            "summary-triage-pending-count-mismatch",
                            path,
                            f"写待分诊 {value} 条，重算是 {pending} 条。",
                        )
                    )
        for pattern in (_MANUAL_CLAIM_RE, _MANUAL_CLAIM_ALT_RE):
            for match in pattern.finditer(line):
                value = int(match.group(1))
                if value != manual:
                    issues.append(
                        _issue(
                            "summary-manual-count-mismatch",
                            path,
                            f"写需人工 {value} 条，重算是 {manual} 条。",
                        )
                    )

    if manual > 0 and not _MANUAL_WORD_RE.search(summary):
        issues.append(
            _issue(
                "summary-manual-undisclosed",
                "summary",
                f"有 {manual} 条 warning 需要人工复核，summary 通篇没提 "
                "needs-manual / 需人工 / 人工复核：读者会以为全部分诊完了。",
            )
        )
    if pending > 0 and _ALL_TRIAGED in summary:
        issues.append(
            _issue(
                "summary-pending-denied",
                "summary",
                f"还有 {pending} 条待分诊，却写「{_ALL_TRIAGED}」。",
            )
        )


# ---------------------------------------------------------------------------
# 5. environment / evidence disclosure
# ---------------------------------------------------------------------------


def _disclosure_codes(delivery: object) -> list[str]:
    """The ordered codes of a delivery's ``requiredDisclosures[]``."""
    rows = delivery.get("requiredDisclosures") if isinstance(delivery, dict) else None
    rows = rows if isinstance(rows, list) else []
    return [
        str(row.get("code") or "")
        for row in rows
        if isinstance(row, dict) and row.get("code")
    ]


def _check_environment(report: dict, summary: str, issues: list[dict]) -> None:
    """``environment`` must be readable, read-only, and disclosed in the text."""
    environment = report.get("environment")
    if not isinstance(environment, dict) or not environment:
        issues.append(
            _issue(
                "environment-missing",
                "report.environment",
                "report.json 缺 environment 节（或为空）：连接器版本、写权限、"
                "限制都没有可读记录。",
            )
        )
    else:
        if environment.get("writeAllowed") is not False:
            issues.append(
                _issue(
                    "environment-write-allowed",
                    "report.environment.writeAllowed",
                    f"writeAllowed 只能是 false，实际 {environment.get('writeAllowed')!r}："
                    "review 不授权写。",
                )
            )
        actions = environment.get("allowedNextActions")
        if not isinstance(actions, list):
            issues.append(
                _issue(
                    "environment-next-actions-missing",
                    "report.environment.allowedNextActions",
                    "allowedNextActions 缺失或不是 list：允许的下一步不可读。",
                )
            )
        else:
            for position, action in enumerate(actions):
                action_id = action.get("id") if isinstance(action, dict) else None
                if action_id not in ALLOWED_NEXT_ACTION_IDS:
                    issues.append(
                        _issue(
                            "environment-next-action-unexpected",
                            f"report.environment.allowedNextActions[{position}]",
                            f"next action id {action_id!r} 不在 "
                            f"{sorted(ALLOWED_NEXT_ACTION_IDS)} 之内。",
                        )
                    )
        limitations = environment.get("limitations")
        if not isinstance(limitations, list):
            issues.append(
                _issue(
                    "environment-limitations-missing",
                    "report.environment.limitations",
                    "limitations 缺失或不是 list：本次环境没证实的项不可读。",
                )
            )
        else:
            for position, row in enumerate(limitations):
                code = row.get("code") if isinstance(row, dict) else None
                path = f"report.environment.limitations[{position}]"
                if not isinstance(code, str) or not code.strip():
                    issues.append(
                        _issue(
                            "environment-limitation-code-missing",
                            path,
                            "该限制行缺 code：无法在 summary 里核对披露。",
                        )
                    )
                elif code not in summary:
                    issues.append(
                        _issue(
                            "environment-limitation-undisclosed",
                            path,
                            f"限制 {code!r} 没有出现在 summary 里：环境限制必须在交付件里"
                            "逐条披露。",
                        )
                    )
    if ENVIRONMENT_HEADING not in summary:
        issues.append(
            _issue(
                "summary-environment-heading-missing",
                "summary",
                f"summary 缺 {ENVIRONMENT_HEADING!r} 整节。",
            )
        )


#: The list containers one evidence record carries, in the frozen order they are
#: walked. ``artifacts`` rows are records (a dict each); ``errors``/``steps`` are
#: only required to be lists here — their items are the collectors' wording and
#: this gate has no schema for them.
_EVIDENCE_CONTAINER_FIELDS = ("artifacts", "errors", "steps")
_LIVE_CAPTURE_CONTAINER_FIELDS = ("artifacts", "steps")


def _check_container_fields(
    row: dict,
    base_path: str,
    fields: tuple[str, ...],
    issues: list[dict],
    *,
    not_list_code: str,
    artifact_code: str,
    label: str,
) -> None:
    """Name every unreadable list container of one raw evidence record.

    ``row`` is already known to be a dict. A field that is **absent** owes
    nothing: the reports written before these containers existed keep their old
    compatibility, and this check never asks for a field to be back-filled.
    A field that is **present** has to be a list — an empty list is the record
    saying 「没有」, while a string/dict says something this build cannot read as
    evidence — and each of ``artifacts``' items has to be a dict (a bare string
    is not an artifact claim). ``errors``/``steps`` items are left alone: only
    the container is this gate's business.

    Every row carries the field's exact path (``…artifacts[2]`` for an item), so
    the engineer is pointed at the record that has to be fixed.
    """
    for field in fields:
        if field not in row:
            continue
        value = row[field]
        path = f"{base_path}.{field}"
        if not isinstance(value, list):
            issues.append(
                _issue(
                    not_list_code,
                    path,
                    f"{label} 的 {field!r} 若存在必须是 list（空列表才表示「没有」），"
                    f"实际是 {type(value).__name__}：这一项读不出任何证据，"
                    "不能当空放过。",
                )
            )
            continue
        if field != "artifacts":
            continue
        for position, item in enumerate(value):
            if not isinstance(item, dict):
                issues.append(
                    _issue(
                        artifact_code,
                        f"{path}[{position}]",
                        f"{label} 的 {field} 第 {position} 项必须是 dict（证据条目是"
                        f"记录），实际是 {type(item).__name__}：这一条不是可读的证据。",
                    )
                )


def _check_evidence(report: dict, summary: str, issues: list[dict]) -> None:
    """Recompute coverage/delivery, and require every disclosure code to appear.

    An **existing** channel row must be a dict whose ``status`` is one of the
    frozen ``CHANNEL_STATUSES``: a row the rest of the report cannot read, or a
    status outside that vocabulary, is a named issue here — a delivery cannot be
    signed on a state the ledger has no word for, and it is not silently re-read
    as "missing". A channel row that is simply **absent** keeps its existing
    semantics (coverage reads ``missing``); this check never invents rows.
    """
    # The heading belongs to the delivered text, so it is asked **before** the
    # report's own section is read: a report with no evidence still owes the
    # reader the section that says so.
    if EVIDENCE_HEADING not in summary:
        issues.append(
            _issue(
                "summary-evidence-heading-missing",
                "summary",
                f"summary 缺 {EVIDENCE_HEADING!r} 整节。",
            )
        )
    evidence = report.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        issues.append(
            _issue(
                "evidence-missing",
                "report.evidence",
                "report.json 缺 evidence 节（或为空）：六通道覆盖与必披露没有可读记录。",
            )
        )
        return
    channels = evidence.get("channels")
    if not isinstance(channels, dict):
        issues.append(
            _issue(
                "evidence-channels-missing",
                "report.evidence.channels",
                "evidence.channels 缺失或不是 dict：coverage/delivery 无从重算。",
            )
        )
        channels = {}
    # 537D2b1 follow-up: the frozen status vocabulary is a contract, and an
    # existing row that is not a dict (or whose status is a word outside it)
    # cannot be read as a coverage answer. The issues come in CHANNEL_ORDER;
    # unreadable rows are dropped from the *local* derivation only, so the
    # shared `evidence_coverage` algorithm is unchanged and the report itself is
    # never mutated. A missing row is untouched: it still reads `missing`.
    unreadable_channels: list[str] = []
    for name in CHANNEL_ORDER:
        if name not in channels:
            continue
        row = channels[name]
        if not isinstance(row, dict):
            issues.append(
                _issue(
                    "evidence-channel-not-dict",
                    f"report.evidence.channels.{name}",
                    f"通道 {name!r} 的行必须是 dict（status/source/detail…），"
                    f"实际是 {type(row).__name__}：这一行读不出任何覆盖结论。",
                )
            )
            unreadable_channels.append(name)
            continue
        status = row.get("status")
        if status not in CHANNEL_STATUSES:
            issues.append(
                _issue(
                    "evidence-channel-status-invalid",
                    f"report.evidence.channels.{name}.status",
                    f"通道 {name!r} 的 status 是 {status!r}，不在固定词表 "
                    f"{CHANNEL_STATUSES} 内：词表外状态不能签发。",
                )
            )
        # 537D2b1 last slice: the row's own raw containers are part of the
        # record. `reviewread` skips a shape it cannot read (tolerance), but a
        # delivery cannot be signed on a record whose `artifacts`/`errors`/
        # `steps` this build has no reading for — absence stays compatible,
        # presence is checked.
        _check_container_fields(
            row,
            f"report.evidence.channels.{name}",
            _EVIDENCE_CONTAINER_FIELDS,
            issues,
            not_list_code="evidence-channel-field-not-list",
            artifact_code="evidence-channel-artifact-not-dict",
            label=f"通道 {name!r}",
        )
    live_capture = evidence.get("liveCapture")
    if isinstance(live_capture, dict):
        # Same discipline for the capture record. A non-dict `liveCapture` keeps
        # its existing focus semantics (`focus-not-restored`) — this check never
        # invents a reading for it.
        _check_container_fields(
            live_capture,
            "report.evidence.liveCapture",
            _LIVE_CAPTURE_CONTAINER_FIELDS,
            issues,
            not_list_code="evidence-live-capture-field-not-list",
            artifact_code="evidence-live-capture-artifact-not-dict",
            label="liveCapture",
        )
        if "captureFile" in live_capture:
            capture_file = live_capture.get("captureFile")
            if not isinstance(capture_file, dict):
                issues.append(
                    _issue(
                        "evidence-live-capture-file-not-dict",
                        "report.evidence.liveCapture.captureFile",
                        "liveCapture.captureFile 若存在必须是 dict（file/bytes/"
                        f"sha256 的记录），实际是 {type(capture_file).__name__}："
                        "读不出这次采集对应哪个文件。",
                    )
                )
    checked_channels = channels
    if unreadable_channels:
        checked_channels = {
            name: row
            for name, row in channels.items()
            if name not in unreadable_channels
        }
    coverage = evidence_coverage(checked_channels)

    stored_coverage = evidence.get("coverage")
    if not isinstance(stored_coverage, dict):
        issues.append(
            _issue(
                "evidence-coverage-missing",
                "report.evidence.coverage",
                "evidence.coverage 缺失或不是 dict。",
            )
        )
    else:
        for name in CHANNEL_ORDER:
            stored = stored_coverage.get(name)
            actual = coverage[name]
            if stored != actual:
                issues.append(
                    _issue(
                        "evidence-coverage-stale",
                        f"report.evidence.coverage.{name}",
                        f"存的是 {stored!r}，按 channels 重算 {actual!r}："
                        "coverage 是派生物，不能与通道状态不一致。",
                    )
                )

    recomputed_delivery = evidence_delivery(checked_channels, live_capture)
    stored_delivery = evidence.get("delivery")
    if not isinstance(stored_delivery, dict):
        issues.append(
            _issue(
                "evidence-delivery-missing",
                "report.evidence.delivery",
                "evidence.delivery 缺失或不是 dict。",
            )
        )
        stored_codes: list[str] = []
    else:
        if stored_delivery.get("status") != recomputed_delivery["status"]:
            issues.append(
                _issue(
                    "evidence-delivery-stale",
                    "report.evidence.delivery.status",
                    f"存的是 {stored_delivery.get('status')!r}，重算是 "
                    f"{recomputed_delivery['status']!r}；stale complete 不可放过。",
                )
            )
        stored_codes = _disclosure_codes(stored_delivery)
        expected_codes = _disclosure_codes(recomputed_delivery)
        if stored_codes != expected_codes:
            issues.append(
                _issue(
                    "evidence-delivery-disclosures-stale",
                    "report.evidence.delivery.requiredDisclosures",
                    f"存的是 {stored_codes}，重算是 {expected_codes}。",
                )
            )

    # Every required code has to be in the delivered text — the recomputed ones
    # and any the stored delivery still names (neither side may hide a gap).
    codes: list[str] = []
    for code in _disclosure_codes(recomputed_delivery) + stored_codes:
        if code not in codes:
            codes.append(code)
    for code in codes:
        if code == DISCLOSURE_FOCUS_RESTORE_FAILED:
            continue  # owned by `focus-not-restored`, below
        if code not in summary:
            issues.append(
                _issue(
                    "summary-disclosure-undisclosed",
                    "summary",
                    f"必披露 {code!r} 没有出现在 summary 里：证据缺口必须在交付件里点名。",
                )
            )

    if live_capture is not None:
        # 537C's hard constraint: a live capture that did not restore the
        # original focus **blocks** the finalize step. Disclosing it is not
        # enough — the summary writing the code down is what the old check
        # accepted, and that made a failed restore indistinguishable from a
        # clean one. `liveCapture is None` (a report that predates live
        # collection) is the only value that owes nothing; `{}` fails closed.
        focus = live_capture.get("focusRestore") if isinstance(live_capture, dict) else None
        restored = isinstance(focus, dict) and focus.get("ok") is True
        if not restored:
            issues.append(
                _issue(
                    "focus-not-restored",
                    "summary",
                    "liveCapture 在，但 focusRestore.ok 不是 true：原焦点未恢复阻止 finalize；"
                    "披露本身不能抵消这一项"
                    f"（{DISCLOSURE_FOCUS_RESTORE_FAILED}）。",
                )
            )

    _check_datasheet_wording(report, summary, coverage, issues)


# ---------------------------------------------------------------------------
# 6. datasheet wording while the channel is open
# ---------------------------------------------------------------------------


def _check_datasheet_wording(
    report: dict, summary: str, coverage: dict, issues: list[dict]
) -> None:
    """No 「已与手册核对」 claim while the datasheet channel is open.

    The trigger is the ledger's own reading: the ``datasheets`` channel is not
    ``ok``/``not-applicable``, or the engineer accepted an unknown part. The
    *legitimate* disclosures (「缺手册」「尚未与手册核对」「待手册」「按手册修改」
    「去要 PDF」) must survive — the patterns are claims, and a negation in the
    same clause cancels one (「不能写成已与手册核对」 is a disclosure, not a
    claim).
    """
    status = coverage.get("datasheets")
    completion = report.get("completion")
    accepted = 0
    if isinstance(completion, dict):
        accepted = _int_or_none(completion.get("acceptedUnknown")) or 0
    open_channel = status is not None and status not in (STATUS_OK, STATUS_NOT_APPLICABLE)
    if not open_channel and accepted <= 0:
        return
    reason = (
        f"datasheets={status}"
        if open_channel
        else f"completion.acceptedUnknown={accepted}"
    )
    for number, line in enumerate(summary.splitlines(), 1):
        for label, pattern in _DATASHEET_CLAIM_PATTERNS:
            for match in pattern.finditer(line):
                if _datasheet_match_negated(line, match):
                    continue
                issues.append(
                    _issue(
                        "datasheet-claim-forbidden",
                        f"summary:line-{number}",
                        f"手册证据未齐（{reason}），这一行却写 {match.group(0)!r}"
                        f"（{label}）：只能写「待核/缺手册/去要 PDF」。",
                    )
                )


def _datasheet_match_negated(line: str, match: re.Match[str]) -> bool:
    """Whether this manual claim is actually a disclosure of a missing manual."""
    matched = match.group(0)
    if matched.endswith(("不一致", "不相符")):
        return True
    return _negated_before(line, match.start())


# ---------------------------------------------------------------------------
# 7. a suspected cross-view stays suspected
# ---------------------------------------------------------------------------


def _suspected_boards(report: dict) -> list[int]:
    """Positions of boards whose ``crossView.status`` is ``suspected``."""
    section = report.get("pcb_review")
    boards = section.get("boards") if isinstance(section, dict) else None
    if not isinstance(boards, list):
        return []
    rows: list[int] = []
    for position, board in enumerate(boards):
        if not isinstance(board, dict):
            continue
        cross_view = board.get("crossView")
        if isinstance(cross_view, dict) and str(cross_view.get("status") or "") == "suspected":
            rows.append(position)
    return rows


def _check_cross_view(report: dict, summary: str, issues: list[dict]) -> None:
    """``suspected`` must be delivered as 疑似, never升级成 confirmed."""
    suspected = _suspected_boards(report)
    if not suspected:
        return
    if _CROSSVIEW_SUSPECTED not in summary:
        issues.append(
            _issue(
                "crossview-suspected-undisclosed",
                "summary",
                f"report 里 {len(suspected)} 块板的 crossView 是 suspected，"
                "summary 通篇没有「疑似」。",
            )
        )
    for number, line in enumerate(summary.splitlines(), 1):
        if not any(token in line for token in _CROSSVIEW_CONTEXT):
            continue
        for token in _CROSSVIEW_CONFIRMED:
            start = line.find(token)
            while start >= 0:
                if not _negated_before(line, start):
                    issues.append(
                        _issue(
                            "crossview-confirmed-claim",
                            f"summary:line-{number}",
                            f"crossView 是 suspected，这一行却写「{token}」："
                            "finalize 不能把疑似升成已确认。",
                        )
                    )
                    start = -1
                    break
                start = line.find(token, start + 1)


# ---------------------------------------------------------------------------
# the public entry point
# ---------------------------------------------------------------------------


def validate_review_summary(report: dict, summary: str) -> list[dict]:
    """Every disagreement between the filled summary and the report it quotes.

    ``report`` is the ``report.json`` dict, ``summary`` the text of the
    finalized ``review-summary.md``. Both are **read only**: this function does
    not open a file, does not touch the editor or the daemon, does not import
    the CLI, and never mutates either argument.

    The result is deterministic: the seven groups are walked in a fixed order
    and each group keeps the report's (or the text's) own order, so the same two
    inputs always give the same list of ``{code, path, message}`` rows.

    ``[]`` means **the delivery is internally consistent** — the table matches
    the ledger, the conclusion is the one authoritative sentence, the triage
    and evidence disclosures are not stale or missing. It does **not** mean the
    board passed: a review with pending warnings (「待分诊」), ``needs-manual``
    rows and a ``partial`` evidence delivery is exactly what a consistent
    delivery looks like, and it validates clean.
    """
    if not isinstance(report, dict):
        return [
            _issue(
                "report-not-dict",
                "report",
                f"report 必须是 report.json 的 dict，实际是 {type(report).__name__}。",
            )
        ]
    if not isinstance(summary, str):
        return [
            _issue(
                "summary-not-str",
                "summary",
                f"summary 必须是 review-summary.md 的文本，实际是 {type(summary).__name__}。",
            )
        ]

    issues: list[dict] = []
    rows, expected_count = _chain_rows(report, issues)
    _check_section_two(summary, rows, expected_count, issues)
    sections = _split_sections(summary)
    _check_human_sections(report, summary, sections, issues)
    _check_conclusion(report, summary, issues)
    _check_triage(report, summary, issues)
    _check_environment(report, summary, issues)
    _check_evidence(report, summary, issues)
    _check_cross_view(report, summary, issues)
    return _dedupe(issues)
