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

_skip_without_windows = pytest.mark.skipif(os.name != "nt", reason="install-hooks.bat is a batch file")
_skip_without_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check
    )


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
    if WORDS_FILE.is_file():
        shutil.copy2(WORDS_FILE, repo / ".sensitive-words")
    _git(repo, "init", "-q")
    return repo


def _install(repo: Path) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["cmd", "/c", str(repo / "scripts" / "install-hooks.bat")],
        cwd=repo,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # the script's final `pause`
    )
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
