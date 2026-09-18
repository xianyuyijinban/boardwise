"""Instrument calibration: golden P1 model vs the editor's own netlist.

The fixture ``ch340_p1_editor_netlist.json`` is the *raw* EasyEDA Pro
netlist export of the golden board's own page, captured from a real editor
on 2026-09-13 (connector 0.3.x, editor 3.2.186). The golden model is parsed
from ``ch340_golden.epro2`` — a completely independent code path. If the
instrument is accurate, the two must agree per pin once the editor's ``$1N``
naming convention is reconciled by membership.

Every difference that is *not* a library enrichment (the editor fills empty
golden attributes from the library device) is a parser or compare bug —
this file is the tripwire for both.
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise.core.candidate import candidate_from_geometry, candidate_from_netlist
from boardwise.core.compare import compare_models, reconcile_names
from boardwise.parsers.schematic import build_schematic_model

GOLDEN = "tests/fixtures/ch340_golden.epro2"
EDITOR_NETLIST = Path("tests/fixtures/ch340_p1_editor_netlist.json")


def _editor_model():
    text = EDITOR_NETLIST.read_text(encoding="utf-8")
    return candidate_from_netlist(text, "EasyEDA")


def test_calibration_zero_real_differences():
    """The tripwire: golden model vs the editor's own netlist, per pin."""
    golden = build_schematic_model(GOLDEN)
    candidate = reconcile_names(_editor_model(), golden)
    report = compare_models(golden, candidate)

    # Directional enrichment, not a defect. Since F1 the golden side joins
    # the DEVICE document's META into each component, so a field the golden
    # *instance* left blank (U3's `Supplier Part`) is now populated on the
    # golden side from the library device. The netlist export has no such
    # join — it emits only instance attributes — so golden-non-empty /
    # candidate-empty on the *metadata* fields (lcsc, manufacturer, mpn,
    # datasheet) is the golden knowing more than the export, which is the
    # exact asymmetry the join was built to create. A one-sided gap in
    # value/footprint would still be a real bug, so only metadata is waived.
    _METADATA_DETAILS = {"lcsc differs", "manufacturer differs", "mpn differs",
                         "datasheet differs"}
    real = [
        d for d in report.component_differences
        if d.golden.strip()
        and not (d.detail in _METADATA_DETAILS and not d.candidate.strip())
    ]
    assert not real, f"real component differences: {[d.render() for d in real]}"
    assert not report.net_differences, (
        f"real net differences: {[d.render() for d in report.net_differences]}"
    )
    assert not report.pin_differences, (
        f"real pin differences: {[d.render()[:200] for d in report.pin_differences]}"
    )


def test_calibration_components_and_nets_present():
    golden = build_schematic_model(GOLDEN)
    candidate = _editor_model()
    assert set(candidate.components) == set(golden.components)
    assert len(candidate.nets) == len(golden.nets)


def test_flag_net_names_resolved_from_device_titles():
    """Ten board flags carry no Global Net Name/Name — the device title
    (``Ground-GND`` / ``Power-VCC`` / ``Power-5V``) is their net name."""
    golden = build_schematic_model(GOLDEN)
    for net_name in ("GND", "+5V", "VCC"):
        assert net_name in golden.nets
    # The merged rails must equal the editor's own membership exactly: same
    # name flags unite wire clusters that would otherwise stay separate nets.
    editor = _editor_model()
    for net_name in ("GND", "+5V", "VCC"):
        assert frozenset(golden.nets[net_name].pins) == frozenset(
            editor.nets[net_name].pins
        ), f"{net_name} rail membership differs from the editor's"


def test_editor_unnamed_nets_reconcile_by_membership():
    """$1N-style names must vanish after reconcile, matched by membership."""
    golden = build_schematic_model(GOLDEN)
    raw = _editor_model()
    dollar_nets = [n for n in raw.nets if n.startswith("$")]
    assert dollar_nets, "the fixture should contain editor-style unnamed nets"
    reconciled = reconcile_names(raw, golden)
    assert not [n for n in reconciled.nets if n.startswith("$")]
    assert set(reconciled.nets) == set(golden.nets)


def test_geometry_path_calibration_zero_real_differences():
    """Revision-4 calibration: the GEOMETRY readback path (the one usable
    on API-placed pages, where the netlist export fails) must reproduce the
    golden board per pin from the captured golden-page geometry dump."""
    from boardwise.parsers.schematic import (
        collect_part_placements,
        collect_symbol_defs,
    )

    golden = build_schematic_model(GOLDEN)
    geo = json.loads(Path("tests/fixtures/ch340_p1_geometry.json").read_text(encoding="utf-8"))
    # The geometry dump's Symbol state is an EMPTY object (the editor
    # refuses to serialize the symbol reference), so symbol offsets are
    # keyed by DESIGNATOR — the golden model's component uid IS the file's
    # symbol uuid.
    all_defs = collect_symbol_defs(GOLDEN)
    symbol_defs = {
        des: all_defs[comp.uid]
        for des, comp in golden.components.items()
        if comp.uid in all_defs
    }
    part_positions = collect_part_placements(GOLDEN)
    candidate = candidate_from_geometry(
        geo, symbol_defs=symbol_defs, part_positions=part_positions
    )

    assert set(candidate.components) == set(golden.components), (
        "every golden part must be recognized on the captured page"
    )
    report = compare_models(golden, reconcile_names(candidate, golden))
    # The geometry instrument cannot read component attributes (its state
    # carries only a Name template) — attribute rows are an instrument
    # limitation, the verdict rides on presence + per-pin connectivity.
    real = [
        d for d in report.component_differences
        if d.golden.strip() and d.candidate.strip()
    ]
    assert not real, f"real component differences: {[d.render() for d in real]}"
    assert not report.net_differences, (
        f"real net differences: {[d.render() for d in report.net_differences]}"
    )
    assert not report.pin_differences, (
        f"real pin differences: {[d.render()[:200] for d in report.pin_differences]}"
    )
