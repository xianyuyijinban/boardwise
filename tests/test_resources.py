"""Where the shipped resources are found: checkout vs frozen exe (028 batch 3a).

Two states, one API, and the difference is the whole point of the batch: the
single exe has to carry its own connector bundle, its own SKILL.md and its own
curated part shelf, so the paths a friend's machine resolves must come out of
PyInstaller's extraction directory rather than out of
``Path(__file__).parents[2]`` — which, frozen, points at a directory that does
not exist.

The shelf is the resource with a second consumer shape: the rules read it as the
default of a path spelling that used to be relative to the working directory, so
"the default shelf" is pinned here through the rule that reads it, not only
through the path helper (044b).

The frozen state is simulated the way PyInstaller creates it: ``sys.frozen`` set
and ``sys._MEIPASS`` pointing at the extraction root.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

from boardwise import resources
from boardwise.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = REPO_ROOT / "packaging" / "boardwise.spec"


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """A process that looks exactly like a PyInstaller one-file bundle."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


def test_a_checkout_resolves_to_the_repo():
    assert resources.is_frozen() is False
    assert resources.describe_state() == "a checkout"
    assert resources.resource_root() == REPO_ROOT
    assert resources.connector_bundle() == REPO_ROOT / "connector" / "dist" / "index.js"
    assert resources.connector_extension_json() == REPO_ROOT / "connector" / "extension.json"
    assert resources.skill_md() == REPO_ROOT / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"
    assert resources.parts_library() == REPO_ROOT / "blocklib" / "parts.json"


def test_the_checkout_paths_are_real_files():
    # A resolution rule that points at nothing is the failure this batch exists
    # to prevent, so the repo state is asserted against the filesystem too.
    assert resources.connector_bundle().is_file()
    assert resources.connector_extension_json().is_file()
    assert resources.skill_md().is_file()
    assert resources.parts_library().is_file()


def test_a_frozen_process_resolves_inside_the_bundle(frozen):
    assert resources.is_frozen() is True
    assert resources.describe_state() == "a frozen exe"
    assert resources.resource_root() == frozen / resources.FROZEN_SUBDIR
    assert resources.connector_bundle() == (
        frozen / resources.FROZEN_SUBDIR / "connector" / "dist" / "index.js"
    )
    assert resources.connector_extension_json() == (
        frozen / resources.FROZEN_SUBDIR / "connector" / "extension.json"
    )
    assert resources.skill_md() == (
        frozen / resources.FROZEN_SUBDIR / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"
    )
    assert resources.parts_library() == (
        frozen / resources.FROZEN_SUBDIR / "blocklib" / "parts.json"
    )
    # Not the checkout: that is the bug being pinned. Frozen, the repo may not
    # exist at all (a friend's machine), so the resolved paths must not be the
    # repo's own — asserted against the paths rather than against containment,
    # because the test temp directory itself lives inside the repo.
    assert resources.resource_root() != REPO_ROOT
    assert resources.connector_bundle() != REPO_ROOT / "connector" / "dist" / "index.js"


def test_frozen_without_an_extraction_root_says_so(monkeypatch):
    # A frozen process whose bootstrap did not set _MEIPASS is broken, and a
    # guessed path would report "resource missing" instead of the real cause.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    with pytest.raises(RuntimeError, match="_MEIPASS"):
        resources.resource_root()


def test_version_prints_both_the_cli_and_the_connector(capsys):
    # 028 §二.3: a friend's bug report needs "which boardwise" and "which
    # extension it carries", and the second number only exists inside the build.
    with pytest.raises(SystemExit) as exit_info:
        cli_main(["--version"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    lines = [line for line in text.strip().splitlines() if line.strip()]
    assert len(lines) == 2, text
    from boardwise import __version__

    assert lines[0].startswith(f"boardwise {__version__} ")
    assert "a checkout" in lines[0]
    assert lines[1].startswith("connector bundle 0."), text
    # The bundle's own version, read from the manifest beside it — never guessed.
    import json

    manifest = json.loads(resources.connector_extension_json().read_text(encoding="utf-8"))
    assert manifest["version"] in lines[1]
    assert str(resources.connector_bundle()) in lines[1]


def test_version_says_unknown_with_the_path_it_looked_at(frozen, capsys):
    # Nothing embedded (a mis-built exe): the report still names the file it
    # wanted, because that path is what turns "it doesn't work" into a fix.
    with pytest.raises(SystemExit) as exit_info:
        cli_main(["--version"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    assert "connector bundle unknown" in text
    assert "extension.json" in text


def test_the_default_shelf_is_the_bundled_copy_when_frozen(frozen, monkeypatch):
    """The default shelf follows the process, never the working directory.

    The bug this pins: the shelf's default was the *relative* spelling
    ``blocklib/parts.json``, and ``core.parts.load_parts`` reads a missing file
    as an empty shelf — so a friend's exe, started in the folder it was
    downloaded into, judged every board against nothing at all, silently. The
    frozen answer is the copy the exe carries; a checkout keeps the relative
    spelling it always had.
    """
    from boardwise.rules.facts import DEFAULT_LIBRARY_PATH, FactsRule, default_library_path

    shelf = frozen / resources.FROZEN_SUBDIR / "blocklib"
    shelf.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "blocklib" / "parts.json", shelf / "parts.json")
    monkeypatch.chdir(frozen)

    assert resources.is_frozen() is True
    assert default_library_path() == str(resources.parts_library())
    # The old spelling resolves to nothing from here — which is exactly what it
    # did on a friend's machine, and why the rule now asks this function.
    assert not Path(DEFAULT_LIBRARY_PATH).is_file()

    rule = FactsRule()
    assert rule.library_path == ""  # un-injected: "this process's shelf"
    assert len(rule.library.parts) > 50  # the bundled shelf, not an empty one


def test_a_checkout_still_uses_the_relative_shelf_spelling():
    from boardwise.rules.facts import DEFAULT_LIBRARY_PATH, default_library_path

    assert resources.is_frozen() is False
    assert default_library_path() == DEFAULT_LIBRARY_PATH


def test_a_frozen_process_without_an_extraction_root_keeps_the_old_answer(monkeypatch):
    # A broken bootstrap must not turn into a new exception out of whichever
    # rule happened to touch the shelf: the constant is returned and the run
    # behaves exactly as it did before this function existed.
    from boardwise.rules.facts import DEFAULT_LIBRARY_PATH, default_library_path

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert default_library_path() == DEFAULT_LIBRARY_PATH


def _spec_datas() -> set[tuple[str, ...]]:
    """The frozen-relative path of every ``DATAS`` entry in ``boardwise.spec``.

    Read as text: a spec is executed by PyInstaller, not importable, so the
    agreement below is checked against its source — the same text the build
    reads.
    """
    body = SPEC.read_text(encoding="utf-8").split("DATAS = [", 1)[1].split("\nfor _source", 1)[0]
    embedded = set()
    for source, target in re.findall(r'REPO\s*((?:\s*/\s*"[^"]+")+)\s*,\s*"([^"]+)"', body):
        source_parts = tuple(re.findall(r'"([^"]+)"', source))
        # A DATAS target is a directory; the file keeps its own name under it.
        embedded.add(tuple(target.split("/"))[1:] + (source_parts[-1],))
    return embedded


def test_the_spec_embeds_every_resource_this_module_resolves():
    """The spec's ``DATAS`` and this module's paths are one list, not two.

    Both files spell the frozen layout out, and a resource that one of them
    knows and the other does not is a friend's machine reporting "missing" for a
    file the build never put there — the failure the spec's own docstring says
    this file is what catches.
    """
    root = resources.resource_root()  # a checkout: the resolved paths are real
    resolved = {
        resolver().relative_to(root).parts
        for resolver in (
            resources.connector_bundle,
            resources.connector_extension_json,
            resources.skill_md,
            resources.parts_library,
        )
    }
    assert _spec_datas() == resolved


def test_no_project_container_is_embedded_in_the_exe():
    """The hygiene red line, applied to what the exe would carry (044b).

    ``blocklib/sources/`` holds 22 MB of project containers kept as read-only
    review input; a downloadable exe is the last place they may end up.
    """
    containers = [
        parts
        for parts in _spec_datas()
        if any(part.endswith((".epro2", ".eprj2", ".eprj3")) for part in parts)
    ]
    assert containers == []
