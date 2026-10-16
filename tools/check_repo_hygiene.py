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
    python tools/check_repo_hygiene.py --staged   # pre-commit: read the index

``--staged`` is the pre-commit mode, and it reads the **index** for both halves:
the path list (`git diff --cached`) and the content (:func:`index_blobs`, the blob
`git show :<path>` would print — see 188B 低3). The working tree is not consulted,
because a file edited after staging is not what the commit carries.

Exit 0 = clean, 1 = violations found (they are listed on stderr).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

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
#
# The file's format (187B):
#
#     AcmeCorp                       # a word to watch, everywhere in the index
#     docs/notes.md<TAB>AcmeCorp     # the **baseline**: this word on this path
#                                    # is grandfathered — reported, never fatal
#
# **Every spelling has to be listed** (188B 低7): matching is per *token* and the
# only normalisation is case-insensitivity, so `AcmeCorp`, `ACME Corp` and
# `acme-corp` are three entries — the list file is the whole vocabulary, and a
# spelling nobody wrote down is a leak this gate reports clean about. See
# :func:`_word_pattern`.
#
# The baseline exists because a leak detector switched on over a repository that
# already contains the word has only two honest options, and before 187B it had
# neither: stay off, or be permanently red on hits nobody is going to fix (the
# 178/108/63 hits measured on 2026-10-16). With the baseline the owner writes the
# existing hits down once and the gate then reports only what is **new**.
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

#: How to read a line of the list: everything before a ``#`` (so a note may
#: follow on the same line), trimmed. Blank lines and comment-only lines are
#: not entries.
_WORD_COMMENT_SPLIT = "#"

#: The **baseline** separator (中5 / 187B): ``path<TAB>word`` is not a word but
#: a statement that this one word on this one path is grandfathered — the shape
#: of every list that has to be switched on over a repository that already
#: contains the word. A tab, because a path may contain a space and a word almost
#: never contains a tab; the line is otherwise as free as a word line (a trailing
#: `#` note included).
_EXEMPT_SEPARATOR = "\t"

#: Extensions whose contents this gate cannot read as text and whose being
#: unreadable says nothing a reader can act on: images, archives, binaries and
#: the project containers the first gate exists for. Named here so the unscanned
#: report can lead with the files that **do** need a look; nothing is skipped by
#: this list — every file is still counted and still scanned for a word when its
#: bytes do decode (中4).
_BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svgz",
    ".pdf", ".zip", ".7z", ".gz", ".tar", ".whl", ".xlsx", ".docx", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".bin",
    ".epro", ".epro2", ".eprj2", ".eprj3", ".epru", ".esch", ".esch2", ".epcb",
    ".woff", ".woff2", ".ttf", ".mp4", ".webm",
)


def _decode_text(data: bytes) -> str | None:
    """Bytes → text, sniffing the encoding, or ``None`` when it is not text.

    Three candidates, tried in the order a file's own first bytes make them
    likely (中4 / 187B): a BOM is authoritative (`utf-8-sig` for a UTF-8 BOM,
    `utf-16` for either UTF-16 order), otherwise plain UTF-8, then GBK — the
    Windows console/redirect encoding that produced the files this gate used to
    skip in silence. ``None`` means "not text this guard can read": a binary, or
    a charset none of the candidates knows.

    Why it matters: the original reader decoded everything as UTF-8 with
    ``errors="replace"``, so a UTF-16 or GBK file's *content* never matched a
    word pattern even when the word was right there in it — a leak detector that
    reported "clean" about files it could not read at all.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig",)
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8", "gbk")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _read_entry_file(file: Path) -> str:
    """The list file's text, or ``SystemExit(2)`` when it cannot be read.

    The list is the owner's own file, and the one thing this guard must not do is
    fail **open**: an unreadable list is not "no list" (which is the documented
    off switch), it is "the detector cannot run". (187B: the encodings the reader
    now sniffs are the ones the file plausibly arrives in — a PowerShell redirect
    wrote UTF-16 until now and turned every commit into a hard failure.)
    """
    try:
        data = file.read_bytes()
    except OSError as exc:
        print(f"repo hygiene: cannot read {file}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    text = _decode_text(data)
    if text is None:
        print(
            f"repo hygiene: {file} is not text this guard can read "
            "(tried utf-8-sig / utf-16 / utf-8 / gbk): an unreadable list is not "
            "an empty one, so this run stops instead of reporting clean",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return text


def _is_binary_name(relative: str) -> bool:
    """Whether a path's *name* says "not a text file", for the unscanned report.

    Used only to decide how the unscanned list is **printed** — the file is
    counted either way, and :func:`sensitive_report` never filters it. The
    distinction is what makes the disclosure readable: a `.png` this guard cannot
    decode is expected and unfixable (image text is not text this gate can read),
    while a `.md` that failed to decode is the case worth a second look.
    """
    return relative.lower().endswith(_BINARY_SUFFIXES)


def _word_list(path: str | Path) -> tuple[list[str], list[tuple[str, str]]]:
    """``(words, exemptions)`` from one list file, in file order.

    A line is a **word** (``AcmeCorp``) or, when it carries a tab, an
    **exemption** (``docs/notes.md<TAB>AcmeCorp``: that word on that path is part
    of the baseline). ``#`` starts a comment, whole-line or trailing. A missing
    file is ``([], [])``, not an error: that is what "this clone has no list"
    means, and it is the documented off switch.
    """
    file = Path(path)
    if not file.is_file():
        return [], []
    words: list[str] = []
    exemptions: list[tuple[str, str]] = []
    for line in _read_entry_file(file).splitlines():
        entry = line.split(_WORD_COMMENT_SPLIT, 1)[0].strip()
        if not entry:
            continue
        if _EXEMPT_SEPARATOR in entry:
            exempt_path, _, word = entry.partition(_EXEMPT_SEPARATOR)
            exempt_path = exempt_path.strip().replace("\\", "/")
            word = word.strip()
            if exempt_path and word:
                pair = (exempt_path, word)
                if pair not in exemptions:
                    exemptions.append(pair)
                if word not in words:
                    # The baseline does not switch the word off elsewhere on the
                    # machine — an exemption is per path by construction, and a
                    # word that appears in only one exempt line is still a word
                    # the rest of the repository is scanned for.
                    words.append(word)
                continue
        if entry not in words:
            words.append(entry)
    return words, exemptions


def sensitive_words(path: str | Path) -> list[str]:
    """The words, in file order, comments and blanks dropped.

    The exemptions travel separately (:func:`sensitive_exemptions`): they select
    which *hits* are baselined, they never remove a word from the vocabulary.
    """
    return _word_list(path)[0]


def sensitive_exemptions(path: str | Path) -> list[tuple[str, str]]:
    """``(path, word)`` pairs grandfathered by the list file, in file order."""
    return _word_list(path)[1]


def _word_pattern(word: str) -> "re.Pattern[str]":
    """The word as a **token**, case-insensitively.

    Boundaries are "no ASCII letter/digit on either side", so a short name does
    not fire inside a longer word (``OCS`` inside ``docs``), while
    ``OCS-project``, ``(OCS)`` and ``the OCS board`` all match. Non-ASCII
    neighbours are boundaries by definition, which is what lets a Chinese name
    match inside a Chinese sentence.

    **The list must spell out every variant** (188B 低7): matching is on the
    token, with no normalisation of case-in-word, punctuation, hyphens, spacing
    or abbreviated forms — ``AcmeCorp``, ``ACME Corp`` and ``acme-corp`` are
    three words, and one line in the list only covers the spelling it names.
    Write each one down (the file has no limit on lines, and a missed spelling is
    a leak this gate reports clean about). The one normalisation that *is*
    applied is case-insensitivity (``re.IGNORECASE``), so ``acmecorp`` and
    ``AcmeCorp`` are one entry.
    """
    return re.compile(
        r"(?<![0-9A-Za-z])" + re.escape(word) + r"(?![0-9A-Za-z])", re.IGNORECASE
    )


def _any_word_pattern(words: list[str]) -> "re.Pattern[str] | None":
    """One alternation over every word — the single pass (中6 / 187B).

    The same token boundaries, hoisted out of the alternation so they are applied
    once to whichever word matched. The per-word patterns are still what answers
    *which* word and *where*; this one only answers "is there anything here at
    all", which is the question that has to be asked of every file, and the one
    that used to cost one full scan **per word** (12 words × 51 MB measured
    10.5 s; the target is a single pass under 3 s).
    """
    if not words:
        return None
    alternatives = "|".join(re.escape(word) for word in words)
    return re.compile(
        r"(?<![0-9A-Za-z])(?:" + alternatives + r")(?![0-9A-Za-z])", re.IGNORECASE
    )


def sensitive_report(
    root: str | Path,
    words: list[str],
    paths: list[str],
    exemptions: list[tuple[str, str]] | None = None,
    read_bytes: "Callable[[str], bytes | None] | None" = None,
) -> dict:
    """Everything the word gate found: ``hits`` / ``exempt`` / ``unscanned``.

    * ``hits`` — ``file:line (word #n)`` for every match that is **not** in the
      baseline. The word is never echoed: it lives in the owner's own file, and
      a report that printed it would move the secret into whatever log reads the
      report. ``word #n`` is 1-based so the owner can find the entry.
    * ``exempt`` — the same shape for matches the baseline grandfathers. They are
      reported *and* printed (中5: the baseline decides the exit code, never the
      visibility) so "the gate is green" cannot be read as "nothing matched".
    * ``unscanned`` — files whose bytes are not text this guard can read. Counted
      and named rather than skipped in silence: an unreadable file is exactly
      where a leak hides, and the old reader's silent skip was the blind spot
      (中4).

    Whole-file text, not a line-by-line match, because the interesting hits
    straddle nothing in particular: a name in a table cell, a code block, an HTML
    comment. Line numbers come from counting newlines before each match, so a hit
    inside a long line still reports the right line.

    ``read_bytes`` is **where the content comes from** (188B 低3): the default
    reads the working tree under ``root``; a ``--staged`` run passes
    :func:`index_blobs`' reader instead, so the bytes scanned are the ones the
    commit would carry. ``None`` from a reader means "no such content"
    (untracked, or absent from the index) and is skipped exactly as a missing
    working-tree file was — the caller has already decided which paths are worth
    asking about.
    """
    hits: list[str] = []
    exempt_hits: list[str] = []
    unscanned: list[str] = []
    if not words:
        return {"hits": hits, "exempt": exempt_hits, "unscanned": unscanned}
    base = Path(root)
    grandfathered = {
        (str(path).replace("\\", "/"), word) for path, word in (exemptions or [])
    }
    patterns = [(index + 1, word, _word_pattern(word)) for index, word in enumerate(words)]
    combined = _any_word_pattern(words)
    for relative in paths:
        if relative == SENSITIVE_WORDS_FILE:
            # The list is not scanned by its own contents: every line of it
            # would match itself, and the hit would say nothing.
            continue
        if read_bytes is not None:
            data = read_bytes(relative)
            if data is None:
                continue
        else:
            file = base / relative
            if not file.is_file():
                continue
            try:
                data = file.read_bytes()
            except OSError:
                continue
        text = _decode_text(data)
        if text is None:
            unscanned.append(relative)
            continue
        # One pass decides whether this file is worth a per-word look at all;
        # the words themselves are then searched from that match's offset, which
        # is their first occurrence in the file (nothing earlier matched).
        first = combined.search(text)
        if first is None:
            continue
        for index, word, pattern in patterns:
            match = pattern.search(text, first.start())
            if match is None:
                continue
            line = text.count("\n", 0, match.start()) + 1
            entry = f"{relative}:{line} (word #{index})"
            if (str(relative).replace("\\", "/"), word) in grandfathered:
                exempt_hits.append(entry)
            else:
                hits.append(entry)
    return {
        "hits": sorted(hits),
        "exempt": sorted(exempt_hits),
        "unscanned": sorted(unscanned),
    }


def sensitive_violations(
    root: str | Path,
    words: list[str],
    paths: list[str],
    exemptions: list[tuple[str, str]] | None = None,
    read_bytes: "Callable[[str], bytes | None] | None" = None,
) -> list[str]:
    """Just the ``hits`` half of :func:`sensitive_report` — the exit-code half."""
    return sensitive_report(root, words, paths, exemptions, read_bytes)["hits"]


def _git_raw(args: list[str]) -> bytes:
    """git's stdout, undecoded — needed for blob content (see :func:`index_blobs`)."""
    out = subprocess.run(["git", *args], capture_output=True, cwd=REPO_ROOT)
    if out.returncode != 0:
        print(
            f"repo hygiene: git {' '.join(args)} failed: "
            f"{out.stderr.decode('utf-8', 'replace').strip()}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return out.stdout


def index_blobs() -> dict[str, bytes]:
    """``{path: bytes}`` for **every tracked file, as the index holds it** (188B 低3).

    What a ``--staged`` run should scan: the content the commit would carry, not
    the working tree a caller may have edited after staging (or staged and then
    edited — the case a pre-commit hook exists for). The path list has always come
    from the index (`git ls-files`); this makes the **content** match.

    Read as one batch — `git ls-files -s` for the blob ids, then a single
    `git cat-file --batch` — because the per-path spelling of the same read
    (`git show :<path>`, one process each) costs ~2.5 s per 50 files on this
    repository: ~65 s for its 1305 tracked files, on a hook that has to run before
    every commit. The batch is the same bytes, once, in ~0.3 s.

    A path whose blob cannot be read is simply absent from the result: the caller
    treats "no content" as "nothing to scan", exactly as it treated a missing
    working-tree file before. Blob content is what git stored, so a `text=auto`
    working tree may differ from it in line endings — that is the point, and
    matching is per token, so it changes no verdict.
    """
    wanted: dict[str, str] = {}
    for record in _git_raw(["ls-files", "-s", "-z"]).split(b"\0"):
        meta, _, path = record.partition(b"\t")
        fields = meta.split()
        if len(fields) < 3 or not path:
            continue
        wanted[path.decode("utf-8", "surrogateescape")] = fields[1].decode("ascii")
    if not wanted:
        return {}
    shas = sorted(set(wanted.values()))
    out = subprocess.run(
        ["git", "cat-file", "--batch"],
        input=("\n".join(shas) + "\n").encode("ascii"),
        capture_output=True,
        cwd=REPO_ROOT,
    )
    if out.returncode != 0:
        print(
            "repo hygiene: git cat-file --batch failed: "
            f"{out.stderr.decode('utf-8', 'replace').strip()}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    by_sha: dict[str, bytes] = {}
    cursor = 0
    data = out.stdout
    for sha in shas:
        end = data.find(b"\n", cursor)
        if end < 0:
            break
        header = data[cursor:end].split()
        cursor = end + 1
        if len(header) < 3 or header[1] != b"blob":
            continue  # `missing`, or something that is not a blob: no content.
        size = int(header[2])
        by_sha[sha] = data[cursor:cursor + size]
        cursor += size + 1
    return {path: by_sha[sha] for path, sha in wanted.items() if sha in by_sha}


def index_reader(blobs: dict[str, bytes] | None = None) -> "Callable[[str], bytes | None]":
    """A :func:`sensitive_report` reader over the **index** rather than the tree.

    A closure rather than the dict itself, so the caller has one read function and
    the content is fetched **once**: the gate asks about every tracked path
    (~1300 here) and the batch in :func:`index_blobs` already holds all of their
    bytes. ``None`` for a path the index does not have is the reader's "no
    content", which is what a missing working-tree file used to mean.
    """
    if blobs is None:
        blobs = index_blobs()
    return lambda relative: blobs.get(relative)


# `-z`: NUL-separated, no quoting — git's default quotepath escaping would hide
# non-ASCII paths from the container regex (the closing quote breaks the
# `(/|$)` anchor), which is exactly the path a company board takes.
def _git(*args: str) -> list[str]:
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
    staged = "--staged" in argv[1:]
    if staged:
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
    words, exemptions = _word_list(REPO_ROOT / SENSITIVE_WORDS_FILE)
    if words:
        suspects = sorted(set(tracked) | set(paths))
        # 188B 低3: under `--staged` the bytes come from the **index**, which is
        # what the commit will carry — the working tree may have been edited after
        # (or before) staging, and a hook that reads it reports on a file nobody
        # is about to commit. `git show :<path>` is that read, batched (see
        # `index_blobs`); a plain run keeps reading the working tree.
        reader = index_reader() if staged else None
        report = sensitive_report(REPO_ROOT, words, suspects, exemptions, reader)
        if SENSITIVE_WORDS_FILE in tracked:
            report["hits"] = [*report["hits"], f"{SENSITIVE_WORDS_FILE} itself is tracked"]
        if report["hits"] or report["exempt"]:
            print(_BANNER_SENSITIVE, file=sys.stderr)
            for hit in report["hits"]:
                print(f"  HIT: {hit}", file=sys.stderr)
            for hit in report["exempt"]:
                print(f"  baselined（豁免，不拦）: {hit}", file=sys.stderr)
        if report["unscanned"]:
            # Never silent (中4): a file this guard could not read is not a file
            # it checked, and "0 hits" over unreadable bytes is the one reading a
            # leak could hide behind. The **count** is always printed; the list is
            # split, because on this repository 126 of the 154 non-UTF-8 files are
            # images, and a wall of `.png` lines would train the reader to skip the
            # one line that matters (a UTF-16 markdown file the reader failed on).
            text_like = [name for name in report["unscanned"] if not _is_binary_name(name)]
            others = len(report["unscanned"]) - len(text_like)
            print(
                f"repo hygiene: {len(report['unscanned'])} 个跟踪文件不是可读文本"
                "（utf-8-sig/utf-16/utf-8/gbk 都解不出），本次**没有扫**"
                f"（其中 {others} 个按扩展名判是图片/压缩/工程容器）：",
                file=sys.stderr,
            )
            for name in text_like[:10]:
                print(f"  unscanned: {name}", file=sys.stderr)
            if len(text_like) > 10:
                print(f"  … 另有 {len(text_like) - 10} 个", file=sys.stderr)
        # Only the non-exempt hits move the exit code (中5).
        if report["hits"]:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
