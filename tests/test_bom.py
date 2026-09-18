"""The BOM a spec implies (008c item 1).

The rules this file pins, in the order they matter:

* every designator traces back to a **shelf entry** through its C-number, and a
  binding that resolves to nothing is an open question rather than a choice;
* a part with no binding at all is *named* in that list — a BOM that quietly
  omits a part is worse than no BOM;
* one C-number carrying two values is a defect and prints neither value;
* the designators in the file are the **page** designators, so a board that
  places one block twice gets one row with both instances' refs.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from boardwise.core.blocks import BlockInstance, BoardSpec, template_from_json
from boardwise.core.parts import PartLibrary
from boardwise.engines.bom import (
    CSV_COLUMNS,
    BomError,
    build_bom,
    load_library,
    resolve_binding,
    write_csv,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"
LIBRARY = ROOT / "blocklib" / "parts.json"


def part(key: str, lcsc: str, *, value: str = "", mpn: str = "", footprint: str = "R0402"):
    from tests.test_parts_library import entry

    return entry(key=key, lcsc=lcsc, value=value, mpn=mpn, footprint_name=footprint)


def template(*components: dict, params=(), name: str = "blk"):
    return template_from_json(
        {
            "kind": "boardwise-block-template", "version": 1, "name": name,
            "description": "", "provenance": {"kind": "textbook", "source": "hand"},
            "origin_file": [0.0, 0.0], "bbox_file": [0.0, 0.0, 10.0, 10.0], "notes": [],
            "interface": [], "params": list(params),
            "symbols": {"s": {"offsets": {"1": [0.0, 0.0]}, "body": [0.0, 0.0, 5.0, 5.0]}},
            "components": list(components),
            "geometry": {"wires": [], "flags": [], "labels": []},
        },
        where=name,
    )


def component(ref: str, *, lcsc: str = "", name: str = "", value_param: str = "", footprint: str = "R0402"):
    body: dict = {
        "ref": ref, "symbol": "s", "placement": {"x": 0.0, "y": 0.0},
        "device": {"lcsc": lcsc}, "footprint": footprint, "pins": [],
    }
    if name:
        body["device"]["name"] = name
    if value_param:
        body["params"] = {"value": value_param}
    return body


def spec_with(*blocks) -> BoardSpec:
    return BoardSpec(
        name="synthetic", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=list(blocks), connections=[], params={}, sheet_attrs={},
        sheet_origin=(0.0, 0.0),
    )


def instance(block_id: str, tmpl, path: str = "/t/blk.json"):
    return BlockInstance(id=block_id, template_path=path, template=tmpl, at=(0.0, 0.0))


# --------------------------------------------------------------------------
# Resolving a binding
# --------------------------------------------------------------------------


def test_a_binding_resolves_through_its_c_number():
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    from boardwise.core.blocks import DeviceBinding

    found, reason = resolve_binding(DeviceBinding(lcsc="C2906948"), library)
    assert found is not None and reason == ""
    assert found.key == "res.5k1_0402"


def test_a_part_that_is_not_on_the_shelf_is_never_substituted():
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    from boardwise.core.blocks import DeviceBinding

    found, reason = resolve_binding(DeviceBinding(lcsc="C99999999"), library)
    assert found is None
    assert "not on the shelf" in reason and "will not substitute" in reason
    # A near miss must not be returned: the shelf's nearest entry is not an answer.
    assert "C2906948" not in reason


def test_a_binding_with_no_c_number_says_what_the_block_claimed():
    from boardwise.core.blocks import DeviceBinding

    found, reason = resolve_binding(DeviceBinding(name="Res_0603"), PartLibrary())
    assert found is None
    assert "binds no C-number" in reason and "Res_0603" in reason


# --------------------------------------------------------------------------
# The bill
# --------------------------------------------------------------------------


def test_one_lcsc_becomes_one_line_with_every_designator():
    library = PartLibrary(parts=[part("cap.100n_0402", "C1525", value="100nF")])
    spec = spec_with(
        instance(
            "a",
            template(
                component("C1", lcsc="C1525", value_param="v"),
                component("C2", lcsc="C1525", value_param="v"),
                params=[{"name": "v", "role": "decoupling", "default": "100nF",
                         "constraint": "capacitor_value", "provenance": "hand"}],
            ),
        )
    )
    report = build_bom(spec, library)
    assert report.ok
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.lcsc == "C1525" and row.quantity == 2 and row.comment == "100nF"
    assert sorted(row.designators) == ["C1", "C2"]
    assert row.footprint == "R0402"  # the library's vocabulary, as stored
    assert report.parts == 2


def test_the_spec_value_wins_over_the_template_default():
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948", value="5.1kΩ")])
    spec = spec_with(
        instance(
            "a",
            template(
                component("R1", lcsc="C2906948", value_param="r"),
                params=[{"name": "r", "role": "pull-down", "default": "10kΩ",
                         "constraint": "resistor_value", "provenance": "hand"}],
            ),
        )
    )
    spec.params = {"a.r": "5.1kΩ"}
    row = build_bom(spec, library).rows[0]
    assert row.comment == "5.1kΩ", "the spec's assignment is the value that is drawn"


def test_a_component_with_no_binding_is_named_as_an_open_question():
    """The negative the task asks for: never skipped in silence."""
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    spec = spec_with(
        instance("a", template(component("R1", lcsc="C2906948"), component("R2", name="Res_0603")))
    )
    report = build_bom(spec, library)
    assert not report.ok
    assert [row.designators for row in report.rows] == [["R1"]]
    assert len(report.open_questions) == 1
    assert "R2" in report.open_questions[0] and "Res_0603" in report.open_questions[0]
    # The CSV keeps the part it could resolve; the question is what says the
    # file is incomplete.
    assert "R2" not in report.csv()


def test_two_values_for_one_c_number_print_neither():
    library = PartLibrary(parts=[part("cap.100n_0402", "C1525")])
    spec = spec_with(
        instance(
            "a",
            template(
                component("C1", lcsc="C1525", value_param="v1"),
                component("C2", lcsc="C1525", value_param="v2"),
                params=[
                    {"name": "v1", "role": "a", "default": "100nF",
                     "constraint": "capacitor_value", "provenance": "hand"},
                    {"name": "v2", "role": "b", "default": "1uF",
                     "constraint": "capacitor_value", "provenance": "hand"},
                ],
            ),
        )
    )
    report = build_bom(spec, library)
    assert not report.ok
    assert any("two components carry different values" in question for question in report.open_questions)
    assert report.rows[0].comment == "", "the export picked one of the two values"
    assert report.rows[0].quantity == 2, "the part is still placed; only its value is unclear"


def test_the_designators_are_the_page_designators_not_the_template_refs():
    """Which is the whole point of deriving them: the BOM matches the drawing."""
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    tmpl = template(component("R1", lcsc="C2906948"))
    first, second = instance("a", tmpl, "/t/x.json"), instance("b", tmpl, "/t/x.json")
    spec = spec_with(first, second)
    report = build_bom(spec, library)
    row = report.rows[0]
    assert sorted(row.designators) == ["R1", "R101"]
    assert row.quantity == 2
    assert "R1,R101" in report.csv().replace('"', "")


def test_designators_are_sorted_the_way_a_human_reads_them():
    library = PartLibrary(parts=[part("cap.1u_0402", "C1")])
    spec = spec_with(
        instance("a", template(*[component(f"C{n}", lcsc="C1") for n in (10, 2, 1, 21)]))
    )
    row = build_bom(spec, library).rows[0]
    assert row.designators == ["C10", "C2", "C1", "C21"]  # insertion order kept
    assert row.csv_row()[1] == "C1,C2,C10,C21"  # but the CSV is ordered


def test_the_csv_shape_is_the_five_jlc_columns():
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948", mpn="0805W8F5101T5E")])
    spec = spec_with(instance("a", template(component("R1", lcsc="C2906948"))))
    report = build_bom(spec, library)
    rows = list(csv.reader(io.StringIO(report.csv())))
    assert rows[0] == list(CSV_COLUMNS)
    assert rows[1] == ["0805W8F5101T5E", "R1", "R0402", "C2906948", "1"]
    assert report.csv().endswith("\n") and "\r\n" not in report.csv()


def test_the_report_carries_the_machine_readable_form():
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    spec = spec_with(instance("a", template(component("R1", lcsc="C2906948"))))
    payload = json.loads(json.dumps(build_bom(spec, library).as_json()))
    assert payload["spec"] == "synthetic" and payload["placed_parts"] == 1
    assert payload["lines"][0]["designators"] == ["R1"]
    assert payload["columns"] == list(CSV_COLUMNS)


def test_writing_the_csv_creates_the_file(tmp_path):
    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    spec = spec_with(instance("a", template(component("R1", lcsc="C2906948"))))
    path = write_csv(build_bom(spec, library), tmp_path / "out" / "bom.csv")
    assert path.read_text(encoding="utf-8").startswith("Comment,Designator,Footprint,LCSC,Qty")


# --------------------------------------------------------------------------
# The real spec, and the CLI
# --------------------------------------------------------------------------


def _cli(argv):
    from boardwise import cli

    return cli.main(argv)


def test_the_ch340_spec_exports_and_names_what_the_shelf_cannot_answer(capsys):
    """Measured 2026-09-17: this board's parts are mostly *not* on the shelf.

    The shelf was seeded from four other boards, so the CH340 golden's C-numbers
    are largely absent. The export says so per designator and exits 1 — the
    honest outcome, and the opposite of quietly printing a shorter BOM.
    """
    code = _cli(["bom", "export", "--spec", str(SPEC), "--library", str(LIBRARY)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "open question" in out
    assert "C14267 is not on the shelf" in out
    # The two parts that *are* on the shelf come out with library footprint names.
    assert "C2765186" in out and "C47773" in out
    assert "library's** name for the package" in out


def test_the_cli_exits_zero_when_everything_resolves(tmp_path, capsys):
    import json as _json

    library = PartLibrary(parts=[part("res.5k1_0402", "C2906948")])
    saved = tmp_path / "parts.json"
    from boardwise.core.parts import save_parts

    save_parts(library, saved)
    spec = spec_with(instance("a", template(component("R1", lcsc="C2906948"))))
    spec_path = _write_spec(spec, tmp_path)
    out_csv = tmp_path / "bom.csv"
    code = _cli([
        "bom", "export", "--spec", str(spec_path), "--library", str(saved),
        "--out", str(out_csv),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert out_csv.read_text(encoding="utf-8").count("\n") == 2
    assert "written:" in printed

    code = _cli([
        "bom", "export", "--spec", str(spec_path), "--library", str(saved), "--json",
    ])
    payload = _json.loads(capsys.readouterr().out)
    assert payload["lines"][0]["lcsc"] == "C2906948"


def test_the_cli_refuses_a_spec_path_that_is_not_a_spec(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    code = _cli(["bom", "export", "--spec", str(bad)])
    assert code == 2
    assert "boardwise bom export" in capsys.readouterr().err


def test_the_cli_refuses_a_spec_that_cannot_be_assembled(tmp_path, capsys):
    """A part list for a page that cannot be drawn is not worth exporting."""
    spec = spec_with(
        instance("a", template(component("R1", lcsc="C1")), "/t/x.json"),
        instance("b", template(component("R1", lcsc="C1")), "/t/y.json"),
    )
    path = _write_spec(spec, tmp_path)
    code = _cli(["bom", "export", "--spec", str(path)])
    assert code == 2
    assert "cannot be assembled" in capsys.readouterr().err


def test_a_missing_library_file_is_an_empty_shelf_not_a_crash():
    library = load_library("/nonexistent/parts.json")
    assert library.parts == []


def _write_spec(spec: BoardSpec, tmp_path: Path) -> Path:
    """Serialise a hand-built spec to disk.

    The templates live in memory, so the spec's `template` field points at a file
    this test also writes — one tiny template JSON, shared by every block, with a
    distinct path per identity when the test needs distinctness.
    """
    import json as _json

    from boardwise.core.blocks import template_to_json

    written: dict[str, dict] = {}
    blocks = []
    for block in spec.blocks:
        rel = Path(block.template_path).name if block.template_path else "blk.json"
        key = str(block.template_path or rel)
        if key not in written:
            (tmp_path / rel).write_text(
                _json.dumps(template_to_json(block.template), ensure_ascii=False),
                encoding="utf-8",
            )
            written[key] = {"path": rel}
        blocks.append({"id": block.id, "template": rel, "at": list(block.at)})
    payload = {
        "kind": "boardwise-board-spec", "version": 1, "name": spec.name,
        "description": "", "provenance": {"kind": "textbook", "source": "hand"},
        "blocks": blocks, "connections": [], "params": dict(spec.params),
    }
    path = tmp_path / "spec.json"
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path
