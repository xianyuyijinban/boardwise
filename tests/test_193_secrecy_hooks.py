"""193 §B: the four secrecy gates — a commit message, an artifact, and the hooks.

The gates themselves are ``tools/check_repo_hygiene.py`` modes; the hooks are
shell scripts git runs, and the thing that makes them live is
``git config core.hooksPath``. So the tests here are of two kinds:

* **in-process** for the modes (``--message`` / ``--assets``): what the gate
  decides about text and bytes, including the exe's compressed payloads, which
  no plain read can see;
* **end to end** for the hooks: a throwaway git repository, the installer run
  twice, a real ``git commit`` that the ``commit-msg`` hook refuses, and a
  second commit that it lets through. The repository under test is never
  configured — the installer is exercised where a mistake costs nothing.

Every word used as a needle is read **from the sensitive list at run time**, not
written into this file: a test fixture spelling out the owner's project name
would be the leak it is testing for. Tests skip when the list is absent, which
is every clone and every CI run — the list is gitignored by design (186 §D).
"""

from __future__ import annotations

import functools
import locale
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HYGIENE = REPO / "tools" / "check_repo_hygiene.py"
EXE_SCANNER = REPO / "packaging" / "check_exe_secrets.py"
WORDS_FILE = REPO / ".sensitive-words"


def _load_hygiene():
    """``check_repo_hygiene`` as a module: ``main`` and the reports, in-process."""
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import check_repo_hygiene
    finally:
        sys.path.pop(0)
    return check_repo_hygiene


hygiene = _load_hygiene()


def _words() -> list[str]:
    """The sensitive list's words, in file order (exemptions included as words)."""
    return hygiene.sensitive_words(WORDS_FILE)


def _needle(words: list[str]) -> str:
    """One word from the list to hang a test on — never printed by the assertions."""
    if not words:
        pytest.skip(f"{WORDS_FILE.name} is not on this machine: the word gate is off here")
    return words[0]


def _run_hygiene(*args: str, stdin: bytes | None = None) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    completed = subprocess.run(
        [sys.executable, str(HYGIENE), *args],
        cwd=REPO,
        capture_output=True,
        input=stdin,
        env=env,
    )
    return completed.returncode, (completed.stdout + completed.stderr).decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# --message
# ---------------------------------------------------------------------------


def test_message_mode_flags_a_word_and_passes_clean_text(tmp_path):
    word = _needle(_words())
    clean = tmp_path / "msg_clean.txt"
    clean.write_text("feat: add a thing\n\nbody without any names\n", encoding="utf-8")
    dirty = tmp_path / "msg_dirty.txt"
    dirty.write_text(f"feat: {word} support\n", encoding="utf-8")

    code, text = _run_hygiene("--message", str(clean))
    assert code == 0, text

    code, text = _run_hygiene("--message", str(dirty))
    assert code == 1, text
    # The hit is reported by number, and the word itself never leaves the list.
    assert "命中敏感词表第" in text, text
    assert word not in text, "the report echoed the word it is keeping out of the repo"


def test_message_mode_reads_stdin_and_needs_a_value(tmp_path):
    word = _needle(_words())
    code, text = _run_hygiene("--message", "-", stdin=f"fix: {word}\n".encode("utf-8"))
    assert code == 1, text

    code, text = _run_hygiene("--message")
    assert code == 2, text


def test_message_mode_refuses_an_input_it_cannot_read(tmp_path):
    """S3#2: "cannot read the message" used to be one printed line and exit 0.

    An unreadable commit message is the one input a message gate must not answer
    "clean" about — it never saw a byte of it. The refusal is exit 1, and it does
    not depend on the word list: whether a file could be opened has nothing to do
    with what the vocabulary contains (so this test does not skip without a list).
    """
    code, text = _run_hygiene("--message", str(tmp_path / "no-such-message.txt"))
    assert code == 1, text
    assert "UNREADABLE" in text, text
    assert "没有扫" in text, text

    # …and a message that *can* be read still passes, so the fix is not "refuse
    # everything": the same missing path next to a clean one is still exit 1, but
    # a lone readable file is exit 0.
    readable = tmp_path / "message.txt"
    readable.write_text("feat: nothing to see here\n", encoding="utf-8")
    assert _run_hygiene("--message", str(readable))[0] == 0


# ---------------------------------------------------------------------------
# --assets
# ---------------------------------------------------------------------------


def test_assets_mode_flags_plain_text(tmp_path):
    word = _needle(_words())
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing to see here\n", encoding="utf-8")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text(f"a note about {word}\n", encoding="utf-8")

    assert _run_hygiene("--assets", str(clean))[0] == 0
    code, text = _run_hygiene("--assets", str(dirty))
    assert code == 1, text
    assert word not in text


def _fake_exe(path: Path, needle_word: str) -> None:
    """An exe-shaped file whose only occurrence of the word is **compressed**.

    Built with zlib rather than PyInstaller: shipping a real one-file build in
    the test suite would cost a minute and a PyInstaller version to reproduce
    what the gate actually reads — the streams (193 §B.3's own note).
    """
    payload = ("padding" * 40 + f"build for {needle_word} board" + "padding" * 40).encode("utf-8")
    path.write_bytes(b"MZ" + b"\0" * 128 + zlib.compress(payload) + b"\0" * 128)


def test_assets_mode_reads_the_compressed_streams_of_an_exe(tmp_path):
    word = _needle(_words())
    fake = tmp_path / "boardwise.exe"
    _fake_exe(fake, word)

    code, text = _run_hygiene("--assets", str(fake))
    assert code == 1, text
    assert "压缩流 #1" in text, text
    assert "命中敏感词表第" in text, text

    # The same bytes under a name that is not an executable: no stream is
    # decompressed, nothing is found. That is what makes the finding above the
    # stream reader's doing rather than a raw-bytes coincidence.
    plain = tmp_path / "same-bytes.txt"
    plain.write_bytes(fake.read_bytes())
    code, text = _run_hygiene("--assets", str(plain))
    assert code == 0, text


def test_assets_mode_passes_a_clean_exe_and_reports_how_much_it_opened(tmp_path):
    clean = tmp_path / "clean.exe"
    clean.write_bytes(b"MZ" + b"\0" * 256 + zlib.compress(b"nothing to see " * 20))
    code, text = _run_hygiene("--assets", str(clean))
    assert code == 0, text
    assert "个 exe 压缩流" in text, "a clean run must still say how much of the artifact it opened"


def test_assets_mode_discloses_and_refuses_an_input_it_cannot_read(tmp_path):
    """S3#2: the artifact gate counted a file it never opened as scanned.

    The old line said "扫了 1 个文件、0 个 exe 压缩流" for a path that does not
    exist, and exited 0 — a release artifact nobody read, reported clean. The
    count is now `opened/given`, the unreadable inputs are named, and the run
    refuses.
    """
    code, text = _run_hygiene("--assets", str(tmp_path / "no-such.exe"))
    assert code == 1, text
    assert "UNREADABLE" in text, text
    assert "扫了 0/1 个文件" in text, text

    # One readable, one not: the readable half is still scanned and the count
    # says 1/2 — the disclosure is about the input, not about the artifact kind.
    clean = tmp_path / "clean.exe"
    clean.write_bytes(b"MZ" + b"\0" * 256 + zlib.compress(b"nothing to see " * 20))
    code, text = _run_hygiene("--assets", str(clean), str(tmp_path / "gone.exe"))
    assert code == 1, text
    assert "扫了 1/2 个文件" in text, text
    assert "压缩流" in text, text


def test_a_truncated_zlib_header_does_not_swallow_the_streams_behind_it(tmp_path):
    """S3#3 — the probe's shape: a decodable but **cut-off** header ate the file.

    zlib reports no error for a stream that was simply cut short, so a truncated
    decoy was accepted like a complete one; a stream that never ended has no
    ``unused_data``, so the scan "resumed" at EOF and every real stream after the
    decoy went unseen. The decoy is what a byte pair inside a PyInstaller build's
    loader already looks like — four offsets in 65 thousand are a valid zlib
    header — so this is a live path, not a contrived one.
    """
    sys.path.insert(0, str(REPO / "packaging"))
    try:
        import check_exe_secrets
    finally:
        sys.path.pop(0)

    word = "SENSITIVEWORDHERE"  # synthetic: the real vocabulary is never spelled in a test
    real = zlib.compress(f"build for {word} board".encode("utf-8"))
    decoy = zlib.compress(b"Q" * 4096, 0)[:40]  # header + a truncated stored block
    body = b"\x90" * 16 + decoy + b"\x55" * 8 + real + b"\x90" * 16

    streams = list(check_exe_secrets.iter_zlib_streams(body))
    assert streams == [f"build for {word} board".encode("utf-8")], streams

    decoy_file = tmp_path / "decoy.exe"
    decoy_file.write_bytes(body)
    control = tmp_path / "control.exe"
    control.write_bytes(b"\x90" * 16 + b"\x55" * 8 + real + b"\x90" * 16)
    written = hygiene.assets_report([str(decoy_file)], [word])
    plain = hygiene.assets_report([str(control)], [word])
    assert plain["hits"], "the control must hit: the same bytes without the decoy"
    assert written["streams"] == 1
    assert written["hits"], "the leak behind a truncated header was not found"

    code, text = _run_hygiene("--assets", str(decoy_file))
    assert code == 0, "no vocabulary match for a synthetic word: the gate itself is clean"
    assert "1 个 exe 压缩流" in text, text


def test_exe_stream_reader_agrees_with_zlib(tmp_path):
    """The scanner's own contract: the streams it yields are the ones zlib wrote."""
    sys.path.insert(0, str(REPO / "packaging"))
    try:
        import check_exe_secrets
    finally:
        sys.path.pop(0)
    payloads = [b"first stream" * 4, ("中文 stream" * 8).encode("utf-8")]
    blob = b"junk" + b"".join(zlib.compress(payload) for payload in payloads) + b"tail"
    assert list(check_exe_secrets.iter_zlib_streams(blob)) == payloads


# ---------------------------------------------------------------------------
# The word list itself is a tracked file: both existing modes must refuse it
# ---------------------------------------------------------------------------


def test_the_word_list_is_refused_by_both_source_modes(monkeypatch, tmp_path):
    """§B.4: a `.sensitive-words` in the index is a hit in either source mode.

    Reproduced in-process by making the *tracked* list contain the list file
    itself — the gate's own check (`SENSITIVE_WORDS_FILE in tracked`), which a
    test cannot produce for real without a `git add` (and this suite does not
    write to the repository's index).
    """
    if not _words():
        pytest.skip(f"{WORDS_FILE.name} is not on this machine: the word gate is off here")
    monkeypatch.setattr(hygiene, "_git", lambda *args: [hygiene.SENSITIVE_WORDS_FILE])
    assert hygiene.main(["check_repo_hygiene.py"]) == 1
    assert hygiene.main(["check_repo_hygiene.py", "--staged"]) == 1


# ---------------------------------------------------------------------------
# The hooks, in a throwaway repository
# ---------------------------------------------------------------------------

#: The legacy bare hook, spelled out: what used to live in ``.git/hooks`` — the
#: same guard, hard-wired to this repository's ``.venv``. The installer has to
#: recognise it (it is *this* guard, moved) without deleting a hook somebody
#: wrote by hand.
_LEGACY_PRE_COMMIT = (
    "#!/bin/sh\n"
    "# Repo hygiene guard (tools/check_repo_hygiene.py): block project\n"
    "# containers outside the allowlist from ever being committed.\n"
    'exec "$(git rev-parse --show-toplevel)/.venv/Scripts/python.exe" '
    '"$(git rev-parse --show-toplevel)/tools/check_repo_hygiene.py" --staged\n'
)

_INSTALLER = REPO / "scripts" / "install-hooks.bat"
_INSTALLER_SH = REPO / "scripts" / "install-hooks.sh"

_skip_without_windows = pytest.mark.skipif(os.name != "nt", reason="install-hooks.bat is a batch file")
_skip_without_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


def _hook_shell() -> Path | None:
    """Git's **own** shell — the one every hook actually runs under.

    Git for Windows executes a hook with ``<install>/usr/bin/sh.exe``, and the
    ``git`` on PATH lives in that same installation (``<install>/cmd/git.exe``),
    so both are derived from the one :func:`shutil.which` lookup that
    ``_skip_without_git`` already trusts. A clone where ``sh`` is only some other
    shell on PATH would not be measuring the hook chain, so ``shutil.which("sh")``
    is a last resort, not the first choice.
    """
    git = shutil.which("git")
    if git is not None:
        git_path = Path(git).resolve()
        for base in (git_path.parent, git_path.parent.parent):
            candidate = base / "usr" / "bin" / "sh.exe"
            if candidate.is_file():
                return candidate
    found = shutil.which("sh")
    return Path(found) if found is not None else None


@functools.lru_cache(maxsize=1)
def _msys_hook_shell_problem() -> str | None:
    """Why git's hook shell cannot start here, or ``None`` when it can.

    Probed **once** per session (``lru_cache``) with ``sh -c true``: no hook, no
    repository, nothing that could fail for a passing reason. Only Windows is
    probed — the failure this guards against is MSYS2's own: ``sh.exe`` needs a
    ``\\BaseNamedObjects\\msys-2.0...`` shared object, and a restricted token
    (the DSH sandbox is one) refuses ``NtCreateDirectoryObject`` with
    ``0xC0000022``. Git exits non-zero before the hook script's first line, so
    the hook chain is untestable **here** — it is not broken.

    A missing ``sh``/``git`` is not a verdict from this probe: "git is not on
    PATH" belongs to ``_skip_without_git``, and inventing a skip for it would
    hide the real reason.
    """
    if os.name != "nt":
        return None
    shell = _hook_shell()
    if shell is None:
        return None
    try:
        completed = subprocess.run(
            [str(shell), "-c", "true"], capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"本环境 sh 起不来，钩链不可测：{shell} -c true 失败（{error}）"
    text = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    if completed.returncode == 0 and "NtCreateDirectoryObject" not in text:
        return None
    if "NtCreateDirectoryObject" in text or "0xC0000022" in text:
        return (
            "本环境 sh 建不了共享对象，钩链不可测"
            f"（{shell.name} -c true 退出 {completed.returncode}，"
            "stderr 含 NtCreateDirectoryObject 0xC0000022）"
        )
    return f"本环境 sh 跑不了 sh -c true，钩链不可测（{shell.name} 退出 {completed.returncode}）"


def _skip_without_msys_shared_objects(fn):
    """Skip the tests that drive a **real** git hook chain under this sandbox.

    The decorator is evaluated at import, and the probe is cached, so the three
    tests share one ``sh -c true``. It skips only when that probe fails — a
    normal terminal's ``sh`` starts cleanly, so these tests stay live there.
    """
    problem = _msys_hook_shell_problem()
    if problem is not None:
        return pytest.mark.skip(reason=problem)(fn)
    return fn


def _decode(raw: bytes) -> str:
    """The child's output, decoded by **what it actually is**.

    532 made this explicit, and the measurement is two-sided — which is why the
    answer is not "always UTF-8" and not "always the code page":

    * `scripts/install-hooks.bat` run under `cmd` writes **cp936** on this machine
      (measured: its 803 bytes are not valid UTF-8 — ``0xc7`` at offset 781 — and
      decode cleanly as ``cp936``). It is the console's encoding, not the file's;
    * `tools/check_repo_hygiene.py` run under git's own pipe writes **UTF-8**, and
      ``text=True`` (which uses the preferred encoding, cp936 here) turns every
      Chinese line of it into mojibake — the failure 531 recorded, whose symptom was
      a `None` `stdout` three lines away from its cause.

    So the decode is chosen by result: UTF-8 first, and the machine's preferred
    encoding when the UTF-8 pass leaves replacement characters. ``errors="replace"``
    keeps a half-decodable line readable instead of fatal; the assertions below are
    what decide whether the text is right.
    """
    text = raw.decode("utf-8", "replace")
    if "\ufffd" in text:
        try:
            fallback = raw.decode(locale.getpreferredencoding(False), "replace")
        except (LookupError, ValueError):
            return text
        if "\ufffd" not in fallback:
            return fallback
    return text


def _decoded(completed: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    """A ``CompletedProcess`` whose streams are text — decoded by :func:`_decode`.

    Assigning the attributes rather than passing `encoding=` to `subprocess.run` is
    the point: the encoding depends on the **result**, and nothing in the call can
    know it in advance.
    """
    if isinstance(completed.stdout, bytes):
        completed.stdout = _decode(completed.stdout)
    if isinstance(completed.stderr, bytes):
        completed.stderr = _decode(completed.stderr)
    return completed


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _decoded(subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=check,
    ))


@pytest.fixture
def hook_repo(tmp_path):
    """A throwaway git repository carrying the hooks and the word list."""
    repo = tmp_path / "hookrepo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    (repo / "tools").mkdir()
    (repo / "packaging").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    for hook in sorted((REPO / ".githooks").iterdir()):
        shutil.copy2(hook, repo / ".githooks" / hook.name)
    shutil.copy2(HYGIENE, repo / "tools" / "check_repo_hygiene.py")
    shutil.copy2(EXE_SCANNER, repo / "packaging" / "check_exe_secrets.py")
    shutil.copy2(_INSTALLER, repo / "scripts" / "install-hooks.bat")
    if _INSTALLER_SH.is_file():
        shutil.copy2(_INSTALLER_SH, repo / "scripts" / "install-hooks.sh")
    if WORDS_FILE.is_file():
        shutil.copy2(WORDS_FILE, repo / ".sensitive-words")
    _git(repo, "init", "-q")
    return repo


def _install(repo: Path) -> subprocess.CompletedProcess:
    """Run the installer, decoding its output by what it is (532 — see :func:`_decode`).

    Measured: the batch file's bytes are **cp936** under `cmd` (not UTF-8), so a
    fixed `encoding="utf-8"` leaves replacement characters in every Chinese line —
    and `text=True` alone chose the code page, which is right for *this* call and
    wrong for the gate's. Neither constant is the answer; the decode is chosen by
    the result.
    """
    completed = _decoded(subprocess.run(
        ["cmd", "/c", str(repo / "scripts" / "install-hooks.bat")],
        cwd=repo,
        capture_output=True,
        stdin=subprocess.DEVNULL,  # the script's final `pause`
    ))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


@_skip_without_windows
@_skip_without_git
def test_installer_is_idempotent_and_migrates_the_legacy_hook(hook_repo):
    """The legacy bare hook is recognised and recycled, then the script is a no-op.

    Recognised in either of the two shapes the installer accepts: the file is
    byte-identical to .githooks/pre-commit, or it carries the legacy guard's
    signature (check_repo_hygiene.py + --staged — the shape it has when the
    tracked hook has moved on since). Both are the same guard, so both go.
    """
    legacy = hook_repo / ".git" / "hooks" / "pre-commit"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(_LEGACY_PRE_COMMIT, encoding="utf-8", newline="")

    first = _install(hook_repo)
    assert _git(hook_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert not legacy.exists(), "the legacy bare pre-commit should have been migrated away"
    assert "moved to the recycle bin" in first.stdout, first.stdout

    second = _install(hook_repo)  # idempotent: no legacy hook left, same config
    assert _git(hook_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert "nothing to migrate" in second.stdout, second.stdout


@_skip_without_windows
@_skip_without_git
def test_installer_migrates_a_byte_identical_copy_too(hook_repo):
    """The other recognisable shape: the tracked hook, copied verbatim."""
    legacy = hook_repo / ".git" / "hooks" / "pre-commit"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / ".githooks" / "pre-commit", legacy)

    completed = _install(hook_repo)
    assert not legacy.exists()
    assert "byte-identical" in completed.stdout, completed.stdout


@_skip_without_windows
@_skip_without_git
def test_a_custom_pre_commit_is_left_alone(hook_repo):
    """The migration deletes the *legacy guard*, not whatever is there."""
    custom = hook_repo / ".git" / "hooks" / "pre-commit"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    completed = _install(hook_repo)
    assert custom.exists() and "echo mine" in custom.read_text(encoding="utf-8")
    assert "[keep]" in completed.stdout, completed.stdout


@_skip_without_windows
@_skip_without_git
@_skip_without_msys_shared_objects
def test_commit_msg_hook_refuses_a_message_with_a_word(hook_repo):
    """The whole chain: core.hooksPath → hook script → the gate, on a real commit.

    Also the no-list case: with no `.sensitive-words` in the clone the gate is
    off by construction and the commit goes through — which is why the clean
    commit is asserted too, so a hook that simply refused everything could not
    pass this test.
    """
    word = _needle(_words())
    _install(hook_repo)
    identity = ("-c", "user.name=guard-test", "-c", "user.email=guard@example.invalid")
    (hook_repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _git(hook_repo, "add", "file.txt")

    clean = _git(hook_repo, *identity, "commit", "-q", "-m", "feat: a clean message", check=False)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    (hook_repo / "file2.txt").write_text("hello again\n", encoding="utf-8")
    _git(hook_repo, "add", "file2.txt")
    bad = _git(
        hook_repo, *identity, "commit", "-q", "-m", f"feat: {word} support", check=False
    )
    assert bad.returncode != 0, bad.stdout
    combined = bad.stdout + bad.stderr
    assert "命中敏感词表第" in combined, combined
    assert word not in combined


# ---------------------------------------------------------------------------
# The pre-push hook: a range it cannot resolve is not "nothing to push" (S3#1)
# ---------------------------------------------------------------------------

_IDENTITY = ("-c", "user.name=guard-test", "-c", "user.email=guard@example.invalid")


def _git_raw(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Git with the output decoded **by hand**.

    The hooks write UTF-8, and `text=True` would decode it with the console code
    page (cp936 on this machine) — the assertions below are on Chinese lines the
    hooks wrote, so the bytes are decoded as UTF-8, explicitly.
    """
    return subprocess.run(["git", *args], cwd=repo, capture_output=True)


def _out(completed: subprocess.CompletedProcess) -> str:
    return (completed.stdout + completed.stderr).decode("utf-8", "replace")


def _commit(repo: Path, name: str, message: str) -> str:
    """One commit, staging **only its own file**.

    Not `git add -A`: the fixture's `.sensitive-words` is the real vocabulary
    (that is the point of it), and the pre-commit hook this repository's own
    `.githooks` supplies would — correctly — refuse to commit the list into the
    index.
    """
    (repo / f"{name}.txt").write_text(f"{message}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, *_IDENTITY, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _bare_remote_with_a_stranger(tmp_path: Path) -> tuple[Path, str]:
    """A bare remote whose `main` is a commit **this clone never fetched**.

    That is what makes the pushed range unresolvable locally, and it is the
    ordinary case: the branch belongs to somebody else, or this is a shallow
    clone. Git advertises the remote's sha on every push, so the hook receives it
    with nothing behind it.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], cwd=tmp_path, capture_output=True)
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=stranger, capture_output=True)
    _commit(stranger, "far", "a commit this clone never saw")
    pushed = _git_raw(stranger, "push", "-q", str(remote), "HEAD:refs/heads/main")
    assert pushed.returncode == 0, _out(pushed)
    sha = _out(_git_raw(tmp_path, "--git-dir", str(remote), "rev-parse", "refs/heads/main")).strip()
    return remote, sha


@_skip_without_git
@_skip_without_msys_shared_objects
def test_pre_push_refuses_a_range_it_cannot_resolve(hook_repo, tmp_path):
    """S3#1: `git rev-list --count` **failing** read as "0 commits to push".

    `count=$(git rev-list --count "$revs" || echo 0)` collapsed two different
    facts: "the range holds no commits" and "the range could not be resolved at
    all". The second `continue`s the loop, skips both scans, and leaves the hook
    at exit 0 — a push that was never scanned, reported clean by the one gate
    whose whole job is the moment the leak leaves the machine.

    The `--force` makes the pre-fix failure mode visible: two unrelated root
    commits are a non-fast-forward, so without the fix the hook waves the push
    through and the remote's `main` moves.
    """
    remote, stranger_sha = _bare_remote_with_a_stranger(tmp_path)
    _git(hook_repo, "config", "core.hooksPath", ".githooks")
    _commit(hook_repo, "local", "unrelated local history")

    push = _git_raw(hook_repo, *_IDENTITY, "push", "--force", str(remote), "HEAD:refs/heads/main")
    text = _out(push)
    assert push.returncode != 0, text
    assert "无法解析要推出的提交范围" in text, text
    assert "两个扫描都没跑" in text, text
    landed = _out(_git_raw(tmp_path, "--git-dir", str(remote), "rev-parse", "refs/heads/main")).strip()
    assert landed == stranger_sha, "the refused push landed anyway"


@_skip_without_git
@_skip_without_msys_shared_objects
def test_pre_push_still_scans_a_range_it_can_resolve(hook_repo, tmp_path):
    """The other direction: the refusal above must not be "refuse everything".

    A second push hands the hook a remote sha this clone **has**. The range
    resolves to the one new commit, both scans run, the count is printed, and the
    push goes through.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], cwd=tmp_path, capture_output=True)
    _git(hook_repo, "config", "core.hooksPath", ".githooks")
    _commit(hook_repo, "one", "first commit")
    first = _git_raw(hook_repo, *_IDENTITY, "push", "-q", str(remote), "HEAD:refs/heads/main")
    assert first.returncode == 0, _out(first)

    second_sha = _commit(hook_repo, "two", "second commit")
    push = _git_raw(hook_repo, *_IDENTITY, "push", str(remote), "HEAD:refs/heads/main", "-v")
    text = _out(push)
    assert push.returncode == 0, text
    assert "扫 refs/heads/main" in text, text
    assert "1 个提交" in text, text
    assert "无法解析" not in text, text
    landed = _out(_git_raw(tmp_path, "--git-dir", str(remote), "rev-parse", "refs/heads/main")).strip()
    assert landed == second_sha


# ---------------------------------------------------------------------------
# S3#6: the hooks must be **executable** in the index, or POSIX git skips them
# ---------------------------------------------------------------------------


def test_the_tracked_hooks_are_executable_in_the_index():
    """S3#6: mode 100644 in the index means git never runs the hook — silently.

    Git runs a hook only if the file is executable, and on POSIX the mode that
    binds is the one the **index** carries, because that is what a clone writes
    out. All three hooks were 100644, so a POSIX clone got `core.hooksPath`
    pointing at three files git would never execute: no warning, no refusal, the
    commit just goes out unguarded. The 193 hooks worked on this machine only
    because Git for Windows does not consult the bit — which is also why the
    end-to-end tests in this file never noticed.

    The failing direction is not reproducible here (this machine's git ignores
    the bit), so the index **is** the observable: `git ls-files -s`.
    """
    listing = _git(REPO, "ls-files", "-s", ".githooks").stdout
    modes = {
        line.split("\t", 1)[1].strip(): line.split()[0]
        for line in listing.splitlines()
        if line.strip()
    }
    for hook in (".githooks/pre-commit", ".githooks/commit-msg", ".githooks/pre-push"):
        assert modes.get(hook) == "100755", (
            f"{hook} is {modes.get(hook)!r} in the index, not 100755 — POSIX git skips it "
            "without a word (fix: git update-index --chmod=+x " + hook + ")"
        )


@_skip_without_git
def test_the_posix_installer_sets_hooks_path_and_the_exec_bit(hook_repo):
    """`scripts/install-hooks.sh` — the POSIX half install-hooks.bat cannot do.

    The batch file can only set `core.hooksPath`; it says so itself ("a clone that
    checks these hooks out needs them executable ... this batch file cannot do it
    for you"). The shell script sets the config **and** chmods the hooks, so the
    documented POSIX route stops at one command.
    """
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no `sh` on PATH: the POSIX installer cannot be driven here")
    assert _INSTALLER_SH.is_file(), f"{_INSTALLER_SH} must be tracked with the Windows installer"
    completed = subprocess.run(
        [shell, str(hook_repo / "scripts" / "install-hooks.sh")],
        cwd=hook_repo,
        capture_output=True,
    )
    text = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    assert completed.returncode == 0, text
    assert _git(hook_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert "chmod +x" in text, text
