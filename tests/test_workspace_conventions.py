"""540A: executable guards for the workspace/evidence directory convention."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _check_ignore(path: str) -> int:
    """Ask git itself; --no-index also checks paths that are already tracked."""
    return subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", path],
        cwd=ROOT,
        check=False,
    ).returncode


@pytest.mark.parametrize(
    "path",
    [
        "evidence/540/report.md",
        "outputs/review/540/report.json",
        "outputs/experiments/example/result.json",
        ".tmp_540/probes/probe.py",
        ".tmp_pt_540/case/output.json",
        ".pytest_cache/v/cache/lastfailed",
        "__pycache__/probe.pyc",
    ],
)
def test_generated_and_local_evidence_paths_are_ignored(path: str):
    assert _check_ignore(path) == 0, f"local artifact is not ignored: {path}"


def test_root_hunt_residue_is_not_hidden_by_gitignore():
    # Root hunts must stay visible until their approved recycle-bin cleanup;
    # ignoring the pattern would disguise the problem instead of fixing it.
    assert _check_ignore("hunt520-example/hunt-audit.jsonl") == 1


@pytest.mark.parametrize(
    "path",
    [
        "src/boardwise/cli.py",
        "tests/test_workspace_conventions.py",
        "tasks/540_pre060_platform.md",
        "experiments/example/README.md",
    ],
)
def test_source_tasks_and_experiment_readmes_are_not_ignored(path: str):
    assert _check_ignore(path) == 1, f"source-like path unexpectedly ignored: {path}"


def test_the_authoritative_document_names_every_working_destination():
    text = (ROOT / "docs" / "workspace-conventions.md").read_text(encoding="utf-8")
    for token in (
        "evidence/<批号>/",
        "outputs/review/<批号>/",
        "experiments/<名称>/",
        "outputs/experiments/<名称>/",
        ".tmp_<批号>/",
        ".tmp_pt_<批号>",
        "保留 / 归档 / 可回收",
        "git worktree list --porcelain",
        "tests/test_workspace_conventions.py",
    ):
        assert token in text, token


def test_the_520_hunt_helper_has_no_process_temp_fallback():
    source = (ROOT / "tests" / "test_520_parts_hunt.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "tempfile" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "tempfile"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert not (
                node.func.attr == "mkdtemp"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "tempfile"
            ), "the helper must never create a process-tempdir fallback"


def test_the_editor_view_hides_only_tmp_scaffolding():
    """``files.exclude`` 只隐藏 ``.tmp_`` 脚手架，不许顺手藏源码。

    A broad pattern (``**``, ``**/*``) or one whose core is ``src`` / ``docs`` /
    ``tests`` would make the tree look clean while the files are still there —
    visual hiding is not cleanup, and it must not hide the code being reviewed.
    """
    settings = json.loads((ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    exclude = settings["files.exclude"]
    assert exclude["**/.tmp_*"] is True
    for pattern, value in exclude.items():
        assert value is True, f"unexpected non-true entry: {pattern}"
        assert pattern not in ("**", "**/*", "*", "**/"), f"too broad: {pattern}"
        core = pattern.removeprefix("**/").strip("/")
        assert core not in ("src", "docs", "tests"), f"would hide {core}: {pattern}"
        assert core.startswith(".tmp_"), f"only .tmp_ scaffolding may be hidden: {pattern}"
