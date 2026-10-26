"""540C: a preview must name a file — the schema refuses the shapes that made the
two runners disagree on a basename: the empty string, a path ending in a
separator, and a path whose final segment is `.` or `..` (with `/` and `\\` read
alike, on every host).

The pattern lives in `contracts/json/draw-compile-result-v1.schema.json` and, for
page documents, in `contracts/json/draw-page-compile-result-v1.schema.json` under
the same rule. It is deliberately lookahead/backreference-free: Python's `re` and
Rust's `regex` crate both have to accept it.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath

import pytest

from tools import build_differential_fixtures as fixtures
from tools import differential as differential_module
from tools.contract_validate import ContractValidationError, assert_valid, load_path
from tools.differential import _preview_names, project_case, project_payload

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "json" / "draw-compile-result-v1.schema.json"
PAGE_SCHEMA_PATH = ROOT / "contracts" / "json" / "draw-page-compile-result-v1.schema.json"
GOLDEN = ROOT / "contracts" / "differential" / "inputs" / "divider-compile-result.json"
PAGE_GOLDEN = ROOT / "contracts" / "differential" / "inputs" / "page-compile-result.json"
BC = chr(92)

BAD_PREVIEWS = [
    "",
    ".",
    "..",
    "out/dir/",
    "out/dir" + BC,
    "cand1.svg/",
    "/",
    "a" + BC,
    # A final segment of `.` or `..` is not a file, and the two runners split it
    # differently: `Path("a/.").name` is "a" while the Rust rsplit gives ".".
    "a/.",
    "./.",
    "a/./.",
    "../.",
    "a/..",
    "out/dir/..",
    "a" + BC + "..",
    "a" + BC + ".",
    "C:" + BC + "proj" + BC + "out" + BC + ".",
]
GOOD_PREVIEWS = [
    "cand1.svg",
    "out/dir/cand1.svg",
    "C:" + BC + "proj" + BC + "out" + BC + "cand1.svg",
    "/abs/cand1.svg",
    ".." + BC + "up" + BC + "c.svg",
    "C:/abs/x.svg",
    ".hidden",
    "a",
    "a/./b.svg",
    # Only the exact `.`/`..` segments are refused; a name that merely starts
    # with dots is a file both runners name the same way.
    "..x",
    "...",
    ".a",
]


def _schema() -> dict:
    return load_path(SCHEMA_PATH)


def _payload(previews: list[str]) -> dict:
    payload = deepcopy(load_path(GOLDEN))
    payload["previews"] = previews
    return payload


def _page_payload(previews: list[str]) -> dict:
    payload = deepcopy(load_path(PAGE_GOLDEN))
    payload["previews"] = previews
    return payload


@pytest.mark.parametrize("preview", BAD_PREVIEWS)
def test_preview_paths_that_do_not_name_a_file_are_refused(preview: str) -> None:
    with pytest.raises(ContractValidationError) as error:
        assert_valid(_payload([preview]), _schema())
    message = str(error.value)
    assert "does not match" in message or "shorter than minLength" in message, message


@pytest.mark.parametrize("preview", GOOD_PREVIEWS)
def test_preview_paths_that_name_a_file_are_accepted(preview: str) -> None:
    assert_valid(_payload([preview]), _schema())


def test_the_page_contract_states_the_same_preview_rule_as_the_module_one() -> None:
    """One rule, two documents: the page case must not relax the basename gate.

    The `x-meaning` annotation is per document and says why; the enforced subset
    (the keywords the validator reads) has to be identical.
    """
    module = _schema()["properties"]["previews"]
    page = load_path(PAGE_SCHEMA_PATH)["properties"]["previews"]
    assert page["type"] == module["type"] == "array"
    assert _enforced(page) == _enforced(module)


def _enforced(previews_schema: dict) -> dict:
    """Every keyword this contract's validator actually reads, minus annotations."""
    return {
        key: value
        for key, value in previews_schema["items"].items()
        if not key.startswith("x-")
    }


@pytest.mark.parametrize("preview", BAD_PREVIEWS)
def test_a_page_preview_that_does_not_name_a_file_is_refused(preview: str) -> None:
    with pytest.raises(ContractValidationError) as error:
        assert_valid(_page_payload([preview]), load_path(PAGE_SCHEMA_PATH))
    message = str(error.value)
    assert "does not match" in message or "shorter than minLength" in message, message


@pytest.mark.parametrize("preview", GOOD_PREVIEWS)
def test_a_page_preview_that_names_a_file_is_accepted(preview: str) -> None:
    assert_valid(_page_payload([preview]), load_path(PAGE_SCHEMA_PATH))


def test_the_committed_golden_still_projects_the_same_six_names() -> None:
    payload = load_path(GOLDEN)
    assert_valid(payload, _schema())
    projection = project_case(
        {"kind": "compile-result-projection", "input": "contracts/differential/inputs/divider-compile-result.json"},
        ROOT,
    )
    assert projection["previewNames"] == [
        "cand1.svg",
        "cand1.layout.json",
        "cand2.svg",
        "cand2.layout.json",
        "cand3.svg",
        "cand3.layout.json",
    ]


def test_the_shapes_where_the_two_basenames_disagree_are_refused_up_front() -> None:
    """`Path("out/dir/").name` is "dir" while an rsplit gives ""; `Path("a/.").name`
    is "a" while the split gives ".". The schema refuses every one of them, so a
    disagreement can never reach a projection."""
    for text in ("out/dir/", ".", "a/.", "./.", "a/./.", "../."):
        python_name = Path(text).name
        rust_name = text.replace(BC, "/").rsplit("/", 1)[-1]
        assert python_name != rust_name, text
        with pytest.raises(ContractValidationError):
            assert_valid(_payload([text]), _schema())


@pytest.mark.parametrize("text", GOOD_PREVIEWS + BAD_PREVIEWS)
def test_preview_names_match_the_rust_split_on_every_host(text: str) -> None:
    """The projection states the segment the Rust runner derives, wherever the
    Python side happens to run: both separators, last segment."""
    assert _preview_names([text]) == [text.replace(BC, "/").rsplit("/", 1)[-1]]


def test_preview_names_do_not_follow_the_host_path_flavour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSIX `Path` treats a backslash as an ordinary character, so the old
    `Path(item).name` projected a Windows preview as one long name there while
    Windows and Rust both said `cand1.svg`. Patching the module's `Path` to a
    POSIX flavour makes that host dependence visible instead of theoretical."""
    monkeypatch.setattr(differential_module, "Path", PurePosixPath)
    payload = deepcopy(load_path(GOLDEN))
    payload["previews"] = [
        "C:" + BC + "proj" + BC + "out" + BC + "cand1.svg",
        "out/dir/cand2.svg",
    ]
    projection = project_payload("compile-result-projection", payload)
    assert projection["previewNames"] == ["cand1.svg", "cand2.svg"]


def test_the_pattern_is_expressible_in_both_regex_engines() -> None:
    pattern = _schema()["properties"]["previews"]["items"]["pattern"]
    assert isinstance(pattern, str) and pattern.startswith("^") and pattern.endswith("$")
    for forbidden in ("(?=", "(?!", "(?<=", "(?<!", "(?P=", BC + "1", BC + "2"):
        assert forbidden not in pattern, f"{forbidden!r} is not portable to Rust's regex"
    re.compile(pattern)  # Python accepts it; the Rust side compiles it in its own test


def test_a_producer_preview_that_names_no_file_cannot_be_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generator gates the payload before publishing, so a trailing separator
    in a producer output aborts the batch instead of freezing a divergent basename."""
    compile_result = load_path(GOLDEN)
    compile_result["previews"] = ["out/dir/"]
    poisoned = tmp_path / "compile-result.json"
    poisoned.write_text(
        json.dumps(compile_result, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(fixtures, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(fixtures, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(fixtures, "MANIFEST", tmp_path / "manifest.json")
    produced = {
        "review-report-projection": ROOT / "contracts/differential/inputs/review-report.json",
        "layout-plan-geometry": ROOT / "contracts/differential/inputs/divider-cand1.layout.json",
        "compile-result-projection": poisoned,
        "compile-page-result-projection": PAGE_GOLDEN,
        "lint-result-projection": ROOT / "contracts/differential/inputs/empty-page-lint-result.json",
    }
    with pytest.raises(ContractValidationError):
        fixtures._regenerate(produced)
    assert not (tmp_path / "inputs").exists()
    assert not (tmp_path / "cases.json").exists()
    assert not (tmp_path / "manifest.json").exists()
