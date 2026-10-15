#!/usr/bin/env python3
"""Repo hygiene guard: real schematic/PCB project containers never enter the repo.

Real projects (especially **company boards**) are read-only review input. Their
files must stay on the machine they came from — a commit leaks the design into
public history forever (deleting the file afterwards does NOT remove it).

The only project containers allowed tracked are the ones already reviewed and
approved, frozen in :data:`ALLOWLIST` below. Adding a legitimate new fixture
means appending its path to that list **in the same commit**, deliberately —
which is exactly the review moment this guard exists to force.

Usage:
    python tools/check_repo_hygiene.py            # check every tracked file
    python tools/check_repo_hygiene.py --staged   # check staged files (pre-commit)

Exit 0 = clean, 1 = violations found (they are listed on stderr).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: The repository this guard belongs to — read off the file's own location, so
#: the gates run against *this* checkout and not against whatever directory a
#: caller happened to be in (`--staged` from a pre-commit hook, a script from
#: anywhere).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Project-container formats this guard watches. `.eprj3` is a *directory*
# (V4 folder format), so the pattern matches any path containing it. `.esch2` is
# the V4 sheet file inside such a folder: `esch` followed by a version digit,
# which the `(/|$)` anchor never sees — the file was invisible to this guard
# until 047, and a company V4 sheet could have entered the repo silently. It is
# listed before `esch` for readability only; the anchor makes the order moot.
#
# The `(?:\.[^/]*)?` before the anchor (080, #41) closes the derived-suffix
# escape: `board.eprj2.bak`, `.orig`, `.backup`, `.old`, `.txt` are the same
# project container under another name, and every one of them would otherwise
# have walked straight past this guard while staying untracked-by-gitignore.
# 047 decided the opposite way — that a derived copy is "not the container the
# pattern is about" — and 080 reverses it: the red line outranks the false
# positive, because a false positive costs one allowlist line in the same commit
# while a false negative leaks a company board into public history. The leading
# dot is what keeps this from eating the `docs/esch2-format-notes.md` and
# `notes/epro2.md` shape, where the container name is the stem rather than an
# extension, and the `[^/]*` cannot run past a directory boundary.
_CONTAINER_RE = re.compile(
    r"\.(epro2|epro|eprj2|eprj3|epru|esch2|esch|epcb)(?:\.[^/]*)?(/|$)", re.IGNORECASE
)

# The project containers tracked as of 2026-10-15, each individually approved
# (own teaching/DIY boards + synthetic/golden fixtures). Frozen.
# (Paths are matched against NUL-separated `git ls-files -z` output, so
# non-ASCII names compare literally — never add the quoted/escaped form.)
#
# The four company boards under `blocklib/sources/` were listed here until
# 2026-10-15, when the owner had them scrubbed from git's **entire history**.
# That path is a local drop box now (`.gitignore` keeps it out of the index), so
# there is no tracked container left to allow — and a `blocklib/sources/` entry
# reappearing in this list would mean the private boards had come back into the
# index, which is the one thing this guard exists to stop.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "reviewsets/injected/duplicate-designator.epro2",
        "reviewsets/injected/fixed-base.epro2",
        "reviewsets/injected/ldo-no-headroom.epro2",
        "reviewsets/injected/nc-pin-grounded.epro2",
        "reviewsets/injected/overvoltage-rail.epro2",
        "reviewsets/injected/v3-decap-missing.epro2",
        "reviewsets/injected/value-mpn-mismatch.epro2",
        "tests/fixtures/CH340G.eprj2",
        "tests/fixtures/CH340G_backup/CH340G_2026-09-13-18-21.epro2",
        "tests/fixtures/CH340G_backup/CH340G_2026-09-13-20-21.epro2",
        "tests/fixtures/DCDC-12V9V转5V3V3_2026-09-27.epro2",
        "tests/fixtures/FPC触屏游戏机_2026-09-27.epro2",
        "tests/fixtures/ProPrj_CH340G_2026-09-13.epro2",
        "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
        "tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2",
        # 毕设FOC 1.0.0 真机导出（127b，岳亲验版本——盲审终验基准）
        "tests/fixtures/ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2",
        "tests/fixtures/ProPrj_智能药箱_2026-09-17.epro2",
        "tests/fixtures/ProPrj_高速电机控制器_2026-09-16.epro2",
        "tests/fixtures/ch340_golden.epro2",
        "tests/fixtures/eprj3_synth/eprj3_synth.eprj3",
        # The synthetic V4 fixture's own sheet file (038). Approved when it was
        # added; the regex simply could not see it until 047, which is why the
        # allowlist grew rather than the file being moved.
        "tests/fixtures/eprj3_synth/sch/Schematic1/P1.esch2",
        "tests/fixtures/llc_board.epro2",
        "tests/fixtures/毕设滤波采样_2026-09-27.epro2",
        "tests/fixtures/级联多电平-主拓扑_2026-09-27.epro2",
        "tests/fixtures/级联多电平-驱动模块_2026-09-27.epro2",
        "tests/fixtures/超声波_2026-09-27.epro2",
        "tools/eprj2-recon/ch340g_decrypted.epru",
        "tools/eprj2-recon/ch340g_final.epru",
        "tools/eprj2-recon/ch340g_merged.epru",
    }
)

_BANNER = (
    "repo hygiene: project container(s) outside the allowlist —\n"
    "  real boards (above all COMPANY boards) must never be committed;\n"
    "  public history keeps them even after deletion. If a file is a\n"
    "  deliberately reviewed new fixture, add its path to ALLOWLIST in\n"
    "  tools/check_repo_hygiene.py in the same commit."
)

# ---------------------------------------------------------------------------
# The second gate: a local list of words that must not appear (task 186 §D)
# ---------------------------------------------------------------------------
#
# The container gate above catches a *file*; it cannot catch a company's name
# typed into a markdown line, a test fixture or a comment — which is how the
# 183/184 rounds leaked what they leaked. The list of words lives in a file the
# repository never contains (`SENSITIVE_WORDS_FILE`, gitignored), so:
#
#   * **with the file** the owner gets a real leak detector on their machine;
#   * **without it** — every clone, every CI run — this gate is **off**, by
#     construction rather than by a flag someone may set wrong.
#
# That asymmetry is the point: a list of an organisation's own project names
# cannot be shipped with the guard that reads it.
SENSITIVE_WORDS_FILE = ".sensitive-words"

_BANNER_SENSITIVE = (
    "repo hygiene: tracked file content matches an entry in "
    f"{SENSITIVE_WORDS_FILE} —\n"
    "  that file is a local-only list (gitignored) of strings that must not\n"
    "  enter this repository. The word itself is NOT printed below: this list\n"
    "  is the one place its owner's names live, and a leak report that repeats\n"
    "  them into a terminal, a log or a CI transcript would be the same leak.\n"
    "  Fix the file content (or, if the match is genuinely innocent, edit the\n"
    "  list — it is yours)."
)

#: How to read a word from the list: everything before a ``#`` (so a note may
#: follow on the same line), trimmed. Blank lines and comment-only lines are
#: not words.
_WORD_COMMENT_SPLIT = "#"


def sensitive_words(path: str | Path) -> list[str]:
    """The list, in file order, comments and blanks dropped.

    One word per line; ``#`` starts a comment (whole-line or trailing). A
    missing file is an **empty** list, not an error: that is what "this clone
    has no list" means, and it is the documented off switch.
    """
    file = Path(path)
    if not file.is_file():
        return []
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"repo hygiene: cannot read {file}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    words: list[str] = []
    for line in text.splitlines():
        word = line.split(_WORD_COMMENT_SPLIT, 1)[0].strip()
        if word and word not in words:
            words.append(word)
    return words


def _word_pattern(word: str) -> "re.Pattern[str]":
    """The word as a **token**, case-insensitively.

    Boundaries are "no ASCII letter/digit on either side", so a short name does
    not fire inside a longer word (``OCS`` inside ``docs``), while
    ``OCS-project``, ``(OCS)`` and ``the OCS board`` all match. Non-ASCII
    neighbours are boundaries by definition, which is what lets a Chinese name
    match inside a Chinese sentence.
    """
    return re.compile(
        r"(?<![0-9A-Za-z])" + re.escape(word) + r"(?![0-9A-Za-z])", re.IGNORECASE
    )


def sensitive_violations(
    root: str | Path, words: list[str], paths: list[str]
) -> list[str]:
    """``file:line (word #n)`` for every tracked file matching a listed word.

    The **word is never echoed** — the list is local-only by design, and a
    report that printed it would move the secret into whatever log reads the
    report. ``word #n`` is 1-based, so the owner can find the entry in their own
    file without it being repeated anywhere.

    Whole-file text, not a line-by-line match, because the interesting hits
    straddle nothing in particular: a name in a table cell, a code block, an
    HTML comment. Line numbers come from counting newlines before each match, so
    a hit inside a long line still reports the right line.
    """
    if not words:
        return []
    base = Path(root)
    patterns = [(index + 1, _word_pattern(word)) for index, word in enumerate(words)]
    found: list[str] = []
    for relative in paths:
        if relative == SENSITIVE_WORDS_FILE:
            # The list is not scanned by its own contents: every line of it
            # would match itself, and the hit would say nothing.
            continue
        file = base / relative
        if not file.is_file():
            continue
        try:
            text = file.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        for index, pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{relative}:{line} (word #{index})")
    return sorted(found)


def _git(*args: str) -> list[str]:
    # `-z`: NUL-separated, no quoting — git's default quotepath escaping would
    # hide non-ASCII paths from the container regex (the closing quote breaks
    # the `(/|$)` anchor), which is exactly the path a company board takes.
    out = subprocess.run(["git", *args, "-z"], capture_output=True, cwd=REPO_ROOT)
    if out.returncode != 0:
        print(
            f"repo hygiene: git {' '.join(args)} failed: {out.stderr.decode('utf-8', 'replace').strip()}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def violations(paths: list[str]) -> list[str]:
    return sorted(p for p in paths if _CONTAINER_RE.search(p) and p not in ALLOWLIST)


def main(argv: list[str]) -> int:
    if "--staged" in argv[1:]:
        paths = _git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    else:
        paths = _git("ls-files")
    tracked = _git("ls-files")
    status = 0

    bad = violations(paths)
    if bad:
        print(_BANNER, file=sys.stderr)
        for p in bad:
            print(f"  OFFENDING: {p}", file=sys.stderr)
        status = 1

    # The second gate. Scanning the **whole index**, not just this commit's
    # files: a word that entered the repository three commits ago is still in
    # it, and "it was fine last time" is how a leak becomes permanent.
    words = sensitive_words(REPO_ROOT / SENSITIVE_WORDS_FILE)
    if words:
        suspects = sorted(set(tracked) | set(paths))
        hits = sensitive_violations(REPO_ROOT, words, suspects)
        if SENSITIVE_WORDS_FILE in tracked:
            hits = [*hits, f"{SENSITIVE_WORDS_FILE} itself is tracked"]
        if hits:
            print(_BANNER_SENSITIVE, file=sys.stderr)
            for hit in hits:
                print(f"  HIT: {hit}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
