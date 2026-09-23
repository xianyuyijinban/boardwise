"""Where the shipped resources are found: checkout vs frozen exe (028 batch 3a).

Two states, one API, and the difference is the whole point of the batch: the
single exe has to carry its own connector bundle and its own SKILL.md, so the
paths a friend's machine resolves must come out of PyInstaller's extraction
directory rather than out of ``Path(__file__).parents[2]`` — which, frozen,
points at a directory that does not exist.

The frozen state is simulated the way PyInstaller creates it: ``sys.frozen`` set
and ``sys._MEIPASS`` pointing at the extraction root.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from boardwise import resources
from boardwise.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_the_checkout_paths_are_real_files():
    # A resolution rule that points at nothing is the failure this batch exists
    # to prevent, so the repo state is asserted against the filesystem too.
    assert resources.connector_bundle().is_file()
    assert resources.connector_extension_json().is_file()
    assert resources.skill_md().is_file()


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
