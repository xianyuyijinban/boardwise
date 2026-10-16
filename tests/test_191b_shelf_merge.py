"""191B: the user's shelf and the exe's shelf are **one** shelf, and part rows
say which boards in **one** shape.

Two holes, one batch (task 191B):

* **the merge.** 186-H2 made a frozen process prefer the user's shelf, which
  fixed the write/read split and created the next hole: the user's file is a
  snapshot of the bundled shelf taken the first time anything wrote, so every
  entry an **upgrade** added to the exe's copy was shadowed by the whole shelf —
  invisible to the review, since `default_library_path()` answered with one
  file. The fix is by identity (MPN / C-number / shelf key): the user's entry
  wins for the same part, everything else on the exe's shelf stays visible, and
  every entry can say which shelf it came from.
* **`boards` — one shape.** 185-中1 gave `needs_datasheet[].boards` a dict per
  placement (`{board, mpn, name, value}`) while `unreviewed_parts[].boards` kept
  a bare list of titles, so a reader (and the fold itself) had two shapes to get
  right. The dict list is the shape; a title list is still read.

The frozen state is simulated the way PyInstaller creates it (``sys.frozen`` +
``sys._MEIPASS``, the same fixture `tests/test_resources.py` uses), the user
shelf's home is redirected through ``BOARDWISE_HOME``, and no fixture here is
written to: the merge is a **read**, and the test asserts the files are
byte-identical afterwards.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from boardwise import cli, resources
from boardwise.core.model import Component
from boardwise.core.parts import (
    SHELF_BUILTIN,
    SHELF_USER,
    SHELF_USER_OVERRIDES,
    load_parts,
    merge_libraries,
)
from boardwise.engines.checkup import (
    board_rows,
    board_titles,
    needs_datasheet_section,
    unreviewed_parts,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
THREE_BOARD = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
SHELF = REPO / "blocklib" / "parts.json"


# ---------------------------------------------------------------------------
# the unit: two shelves, one answer
# ---------------------------------------------------------------------------


def _entry(key: str, *, mpn: str = "", lcsc: str = "", value: str = "") -> dict:
    """One shelf entry, in the shape the loader validates."""
    return {
        "key": key,
        "value": value,
        "mpn": mpn,
        "lcsc": lcsc,
        "manufacturer": "",
        "deviceUuid": f"device-{key}",
        "libraryUuid": "a" * 32,
        "footprint_name": "R0402",
        "footprint_name_verified": None,
        "params": {},
        "datasheetUrl": "",
        "datasheetPdfUrl": "",
        "basic": None,
        "category": "resistor",
        "provenance": {"kind": "manual-curation", "source": "", "designators": [], "note": ""},
        "notes": [],
    }


def _library(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "kind": "boardwise-part-library",
                "version": 2,
                "sources": [],
                "notes": [],
                "parts": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_a_user_entry_over_the_builtin_one_and_the_rest_of_the_builtin_shelf(tmp_path):
    """The hole, in one assertion: same part, plus the entry the user never had.

    Three entries, two facts: the part both shelves carry is the user's (the
    builtin copy of it is gone, and the label says why), and the part **only**
    the exe's shelf carries is still there — which is what an upgrade brings and
    what the user's snapshot used to hide.
    """
    user_path, builtin_path = tmp_path / "user.json", tmp_path / "builtin.json"
    _library(user_path, [_entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001", value="10kΩ")])
    _library(
        builtin_path,
        [
            _entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001", value="10kΩ"),
            _entry("res.4k7_0402", mpn="RC0402-4K7", lcsc="C1002", value="4.7kΩ"),
        ],
    )
    merged = merge_libraries(load_parts(user_path), load_parts(builtin_path))

    assert [part.key for part in merged.parts] == ["res.10k_0402", "res.4k7_0402"], (
        "合并后按 key 排序，两部分都在"
    )
    assert merged.origin_of("res.10k_0402") == SHELF_USER_OVERRIDES
    assert merged.origin_of("res.4k7_0402") == SHELF_BUILTIN
    assert merged.get("res.4k7_0402").value == "4.7kΩ"


def test_an_entry_only_the_user_has_is_not_labelled_as_an_override(tmp_path):
    """`user` and `user-overrides-builtin` are different claims.

    "I added a part the exe's shelf does not have" and "I changed what the exe
    ships" send a reader to different places (add a fact / check a fact), so a
    single `user` label for both would lose the one thing the merge knows.
    """
    user_path, builtin_path = tmp_path / "user.json", tmp_path / "builtin.json"
    _library(user_path, [_entry("res.100k_0402", mpn="RC0402-100K", lcsc="C1009")])
    _library(builtin_path, [_entry("res.4k7_0402", mpn="RC0402-4K7", lcsc="C1002")])
    merged = merge_libraries(load_parts(user_path), load_parts(builtin_path))
    assert merged.origin_of("res.100k_0402") == SHELF_USER
    assert merged.origin_of("res.4k7_0402") == SHELF_BUILTIN


def test_identity_is_mpn_c_number_or_shelf_key(tmp_path):
    """The three keys the task book names — plus the key, which is how two
    shelves can address one part differently."""
    user_path, builtin_path = tmp_path / "user.json", tmp_path / "builtin.json"
    # Same C-number, different shelf key and a different MPN spelling.
    _library(user_path, [_entry("res.mine", mpn="MINE-1", lcsc="C1001")])
    _library(builtin_path, [_entry("res.theirs", mpn="THEIRS-1", lcsc="C1001")])
    merged = merge_libraries(load_parts(user_path), load_parts(builtin_path))
    assert [part.key for part in merged.parts] == ["res.mine"], "按 C 号认出是同一颗"

    # Same shelf key, nothing else in common.
    _library(builtin_path, [_entry("res.mine", mpn="THEIRS-2", lcsc="C2002")])
    merged = merge_libraries(load_parts(user_path), load_parts(builtin_path))
    assert [part.key for part in merged.parts] == ["res.mine"], "同一个 key 只能有一条"

    # Same MPN.
    _library(builtin_path, [_entry("res.other", mpn="MINE-1", lcsc="C3003")])
    merged = merge_libraries(load_parts(user_path), load_parts(builtin_path))
    assert [part.key for part in merged.parts] == ["res.mine"], "同一个 MPN 认同一颗"


def test_a_single_shelf_is_not_merged_and_carries_no_labels(tmp_path):
    """`load_libraries` with one path is the plain read — byte-identical answer.

    A single-file shelf must not grow labels: "which shelf did this come from"
    has no answer when there is one shelf, and inventing `builtin` would be a
    claim about a merge that never happened.
    """
    from boardwise.core.parts import load_libraries

    path = tmp_path / "one.json"
    _library(path, [_entry("res.4k7_0402", mpn="RC0402-4K7", lcsc="C1002")])
    library = load_libraries((str(path),))
    assert library.origins == {}
    assert library.origin_of("res.4k7_0402") == ""
    assert [part.key for part in library.parts] == [part.key for part in load_parts(path).parts]


# ---------------------------------------------------------------------------
# the frozen read side: which shelves, and who sees them
# ---------------------------------------------------------------------------


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """A frozen process with a bundled shelf and a user shelf that disagree."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    bundle = tmp_path / "mei" / resources.FROZEN_SUBDIR / "blocklib"
    _library(
        bundle / "parts.json",
        [
            _entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001", value="10kΩ"),
            # …the entry an upgrade added: verified facts on it, so a rule may act
            # on it, and a class, so the datasheet gate counts it as judged.
            {
                **_entry("ic.newpart", mpn="NEWPART-1", lcsc="C9001", value=""),
                "category": "ic.ldo",
                "footprint_name": "SOT-23",
                "facts": {
                    "supply_pins": [
                        {
                            "pins": ["1"],
                            "name": "VIN",
                            "v_operating": [2.0, 6.0],
                            "provenance": "https://example.invalid/ds.pdf p.3",
                        }
                    ]
                },
            },
        ],
    )
    user = home / "parts.json"
    _library(user, [_entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001", value="10kΩ")])
    return {"bundle": bundle, "user": user}


def test_the_read_side_is_the_pair_while_the_write_target_stays_one_file(frozen):
    """191B's split, stated in one test: **read both, write the user's.**

    `default_library_path()` (the write target, and the path `report.json`
    quotes back in its clearing instruction) must stay the user's file — a
    reader sent to curate a file inside the exe's extraction directory is
    186-H2's hole. The reading is the pair, and `read_default_library()` is the
    merge.
    """
    from boardwise.rules.facts import (
        default_library_path,
        default_library_paths,
        read_default_library,
    )

    assert default_library_path() == str(frozen["user"])
    assert default_library_paths() == (str(frozen["user"]), str(frozen["bundle"] / "parts.json"))
    merged = read_default_library()
    assert [part.key for part in merged.parts] == ["ic.newpart", "res.10k_0402"]
    assert merged.origin_of("ic.newpart") == SHELF_BUILTIN
    assert merged.origin_of("res.10k_0402") == SHELF_USER_OVERRIDES


def test_the_merge_reads_only_and_leaves_both_files_byte_identical(frozen):
    """A merge that wrote would be a second writer on the user's shelf."""
    from boardwise.rules.facts import read_default_library

    files = (frozen["user"], frozen["bundle"] / "parts.json")
    before = {path: path.read_bytes() for path in files}
    read_default_library()
    read_default_library()
    assert {path: path.read_bytes() for path in files} == before


def test_the_upgraded_builtin_entry_reaches_the_review(frozen):
    """The hole itself: an entry an upgrade added is judged, not "no such part".

    `U1` is a part only the **bundled** shelf has (verified facts, a class). With
    the merge it is judged by the shelf and leaves `unreviewed_parts`; with the
    user's shelf alone it is "the shelf does not have this part" — which is what
    a frozen exe reported for it before 191B.
    """
    from boardwise.rules.facts import read_default_library

    component = Component(
        uid="c-1",
        designator="U1",
        mpn="NEWPART-1",
        lcsc_part="C9001",
        value="",
        footprint="SOT-23",
        props={"device_name": "NEWPART-1"},
    )
    model = type("M", (), {"components": {"U1": component}, "nets": {}})()

    assert unreviewed_parts(model, library=read_default_library()) == []
    alone = unreviewed_parts(model, library=load_parts(frozen["user"]))
    assert len(alone) == 1 and "货架没有这颗料" in alone[0]["reasons"]


def test_the_rules_read_the_merged_shelf_too(frozen):
    """One answer for the rules and the report — the whole point of one reader.

    A rule that reads the user's snapshot while `unreviewed_parts` reads the
    merge would judge the same board two ways (`FactsRule.library` is the
    un-injected route every facts rule takes).
    """
    from boardwise.engines.review import BUILTIN_RULES
    from boardwise.rules.facts import FactsRule

    rule = FactsRule()
    assert [part.key for part in rule.library.parts] == ["ic.newpart", "res.10k_0402"], (
        "未注入货架的规则也必须读到合并架"
    )
    assert any(isinstance(builtin, FactsRule) for builtin in _facts_rules(BUILTIN_RULES))


def _facts_rules(rules):
    from boardwise.rules.facts import FactsRule

    return [rule for rule in rules if isinstance(rule, FactsRule)]


# ---------------------------------------------------------------------------
# the CLI: `parts list` labels every row
# ---------------------------------------------------------------------------


def test_parts_list_labels_every_row_on_a_frozen_process(frozen, capsys):
    code = cli.main(["parts", "list"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "user-overrides-builtin" in out and "res.10k_0402" in out
    assert "ic.newpart" in out and SHELF_BUILTIN in out, out
    assert "2 entries" in out


def test_parts_list_json_is_the_machine_shape(frozen, capsys):
    code = cli.main(["parts", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["merged"] is True
    assert payload["shelfPaths"] == [str(frozen["user"]), str(frozen["bundle"] / "parts.json")]
    assert payload["shelfPath"] == str(frozen["user"])
    assert payload["originCounts"] == {
        SHELF_USER: 0, SHELF_BUILTIN: 1, SHELF_USER_OVERRIDES: 1,
    }
    sources = {row["key"]: row["source"] for row in payload["entries"]}
    assert sources == {"ic.newpart": SHELF_BUILTIN, "res.10k_0402": SHELF_USER_OVERRIDES}


def test_parts_list_with_an_explicit_library_is_that_one_shelf(monkeypatch, tmp_path, capsys):
    """`--library` wins and nothing is merged into it: the user named one file."""
    monkeypatch.delenv("BOARDWISE_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    path = tmp_path / "shelf.json"
    _library(path, [_entry("res.4k7_0402", mpn="RC0402-4K7", lcsc="C1002")])
    code = cli.main(["parts", "list", "--library", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["merged"] is False
    assert payload["shelfPaths"] == [str(path)]
    assert [row["source"] for row in payload["entries"]] == [""], (
        "一个货架没有来源可说——不编一个 builtin 出来"
    )


def test_a_checkout_lists_the_repo_shelf_without_labels(capsys):
    code = cli.main(["parts", "list", "--limit", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "user-overrides-builtin" not in out
    assert "109 entries" in out, out


# ---------------------------------------------------------------------------
# `boards` — one shape for the part rows
# ---------------------------------------------------------------------------


def test_board_titles_reads_both_shapes_and_board_rows_normalizes():
    """The compatibility read, stated as a unit: a title list is still read."""
    rows = [{"board": "Board1", "mpn": "M1", "name": "N1", "value": "V1"}]
    assert board_titles(rows) == ["Board1"]
    assert board_titles(["Board1", "Board3"]) == ["Board1", "Board3"]
    assert board_titles([]) == []
    assert board_titles(None) == []
    # Garbage is skipped, never a crash: one bad field must not lose the row.
    assert board_titles([42, {"board": "Board2"}]) == ["Board2"]

    assert board_rows(["Board1"], mpn="M1", name="N1", value="V1") == rows
    assert board_rows(rows) == rows, "dict rows are returned as they stand"
    assert board_rows(["Board1", "Board1"]) == [
        {"board": "Board1", "mpn": "", "name": "", "value": ""}
    ], "去重"


def test_the_two_part_row_sections_speak_one_shape(tmp_path, monkeypatch):
    """The end-to-end claim, measured over the 3-board fixture.

    `unreviewed_parts[]` and `needs_datasheet[]` are compared field by field:
    both carry placement rows with the same four keys, and the fold's rows for a
    designator are exactly the rows `unreviewed_parts[]` has for it.
    """
    out = tmp_path / "out"
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    cli.main(["checkup", "--file", str(THREE_BOARD), "--out", str(out), "--library", str(SHELF)])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    placements: dict[str, list[dict]] = {}
    for row in report["unreviewed_parts"]:
        for entry in row.get("boards") or []:
            assert set(entry) == {"board", "mpn", "name", "value"}, entry
            assert isinstance(entry["board"], str) and entry["board"]
            placements.setdefault(str(row["designator"]), []).append(entry)
    assert placements, "夹具上应该有带板别的未审行"

    for row in report["needs_datasheet"]:
        folded = row.get("boards") or []
        for entry in folded:
            assert set(entry) == {"board", "mpn", "name", "value"}, entry
        assert sorted(folded, key=_placement_key) == sorted(
            placements.get(str(row["part"]), []), key=_placement_key
        ), row["part"]

    # The old title shape is still what a reader of an older report sees, and the
    # compat read gives the same answer as the new one.
    titles = [entry["board"] for entry in report["unreviewed_parts"][0]["boards"]]
    assert board_titles(report["unreviewed_parts"][0]["boards"]) == titles
    assert board_rows(
        [{"board": t} for t in titles]
    ) == board_rows(titles, mpn="", name="", value="")


def _placement_key(entry: dict) -> tuple:
    return (entry["board"], entry["mpn"], entry["name"], entry["value"])


def test_a_folded_row_still_reads_a_title_list():
    """The compat read on the fold itself: 187B's own seed shape still works.

    This is the shape every report written before 191B has, and the shape a
    caller that builds a seed by hand passes — the fold expands it with the
    row's identity exactly as it did in 185-中1.
    """
    seeds = [
        {"designator": "C2", "boards": ["Board1"], "name": "CAP_0603", "value": "",
         "mpn": "", "supplier": "", "reasons": ["无 MPN"]},
        {"designator": "C2", "boards": ["Board3"], "name": "CGA0603", "value": "100nF",
         "mpn": "CGA0603", "supplier": "C1", "reasons": ["供应商字段为空"]},
    ]
    section = needs_datasheet_section(seeds, [], [])
    assert section[0]["boards"] == [
        {"board": "Board1", "mpn": "", "name": "CAP_0603", "value": ""},
        {"board": "Board3", "mpn": "CGA0603", "name": "CGA0603", "value": "100nF"},
    ]


def test_the_frozen_paths_helper_does_not_invent_a_second_shelf(monkeypatch, tmp_path):
    """No user shelf → one path, and from a checkout → one path.

    `default_library_paths()` must never name a shelf that is not read: an empty
    pair is a merge of nothing, and a report would then say "two shelves" about
    a run that read one.
    """
    from boardwise.rules.facts import DEFAULT_LIBRARY_PATH, default_library_paths

    monkeypatch.delenv("BOARDWISE_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert default_library_paths() == (DEFAULT_LIBRARY_PATH,)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    (tmp_path / resources.FROZEN_SUBDIR / "blocklib").mkdir(parents=True)
    shutil.copyfile(SHELF, tmp_path / resources.FROZEN_SUBDIR / "blocklib" / "parts.json")
    assert default_library_paths() == (
        str(tmp_path / resources.FROZEN_SUBDIR / "blocklib" / "parts.json"),
    ), "用户架不存在时只有内置架一条"
