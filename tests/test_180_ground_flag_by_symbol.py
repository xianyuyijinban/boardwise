"""180: a ground flag rides its **library symbol**, and the fallback is observed.

178b measured the defect this batch answers: `sch.place_power(kind=Ground, net=X)`
lands one `Ground-GND` for *every* ground net — it picks the symbol by **kind**,
not by net — so a page cannot tell a PGND from a SEC_GND on the canvas. The library
device `Ground-PGND` *does* place as a flag (ComponentType `netflag`, Global Net
Name `PGND`) through `sch.place_component` (probed live 2026-10-13; the uuid-level
reading is in `outputs/180/live/`). So `draw apply` now:

* places a **ground** flag by its library symbol when the host library carries a
  device named `Ground-<net>` (one `lib.device.search` per net, cached);
* falls back to `sch.place_power` when it does not, and writes that fallback to the
  plan's notes — an observation, never a refusal (168's rule);
* observes when ≥2 ground families share one host glyph (`两族同形`), on the same
  notes channel.

The fakes are 054's (`_FakeEditor`), extended in 180 with `ground_symbols` (the
library's per-net ground devices) and the `lib.device.search` / by-symbol
`sch.place_component` legs; an empty `ground_symbols` reproduces the old fallback
path byte for byte, which is why every pre-180 054/057 test still passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_054_draw_cli as m054

from boardwise import cli
from boardwise.engines import drawapply


# ------------------------------------------------- the judgement (unit)

def test_two_ground_families_on_one_glyph_are_observed():
    """The 178b defect read at the canvas: two families, one glyph → one note."""
    notes = drawapply.ground_family_observations(
        {"GND": "place_power Ground", "PGND": "place_power Ground"},
        {"GND": "PWR-GND", "PGND": "PWR-PGND"},
    )
    assert len(notes) == 1
    note = notes[0]
    assert "两族同形观察（180）" in note
    assert "GND" in note and "PGND" in note
    assert "PWR-GND" in note and "PWR-PGND" in note, (
        "the note names the plan's own refs, not just the nets"
    )


def test_distinct_glyphs_or_a_single_family_are_silent():
    """Two families each on their own glyph is the thing done right — no note."""
    assert drawapply.ground_family_observations(
        {"GND": "symbol dev-gnd", "PGND": "symbol dev-pgnd"},
        {"GND": "PWR-GND", "PGND": "PWR-PGND"},
    ) == []
    assert drawapply.ground_family_observations({"GND": "place_power Ground"}) == [], (
        "one ground family has nothing to be confused with"
    )
    assert drawapply.ground_family_observations({}) == []


# ------------------------------------------------------- the flow (e2e)

def _apply(monkeypatch, tmp_path, plan_path, editor, capsys) -> dict:
    m054._stub_editor(monkeypatch, editor)
    m054._stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    return json.loads(report.read_text(encoding="utf-8"))


def test_a_ground_flag_rides_its_library_symbol(monkeypatch, tmp_path, capsys):
    """Library carries `Ground-GND` → the flag is placed by symbol, not by kind."""
    plan_path, plan = m054._plan(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    editor.ground_symbols = {
        "Ground-GND": {"uuid": "dev-gnd", "libraryUuid": "lib-1"},
    }
    payload = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)

    by_symbol = [p for a, p in editor.writes
                 if a == "sch.place_component" and p.get("deviceUuid")]
    assert by_symbol, "the GND flag went through `sch.place_component`, not `sch.place_power`"
    gnd = by_symbol[-1]
    assert gnd["deviceUuid"] == "dev-gnd" and gnd["libraryUuid"] == "lib-1"
    assert gnd["pageUuid"] == editor.page, "every write carries the page guard"
    # the power (VIN) flag keeps the kind-based action — 180 changes grounds only
    assert any(a == "sch.place_power" and p.get("net") == "VIN"
               for a, p in editor.writes)
    # the flag is a netflag named GND, and no fallback was announced
    assert any(f["net"] == "GND" for f in editor.flags)
    assert not any("地旗回落" in note for note in payload["notes"])
    assert not any("两族同形" in note for note in payload["notes"])
    # the report says which route each flag took, so the evidence is machine-readable
    routes = {row["net"]: row["placement"] for row in payload["write"]["connections"]
              if row.get("kind") == "power-flag"}
    assert routes.get("GND") == "sch.place_component"
    assert routes.get("VIN") == "sch.place_power"


def test_a_ground_without_a_library_symbol_falls_back_and_is_noted(
        monkeypatch, tmp_path, capsys):
    """No `Ground-GND` in the library → `sch.place_power`, and the plan is told."""
    plan_path, plan = m054._plan(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    payload = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)

    assert not [p for a, p in editor.writes
                if a == "sch.place_component" and p.get("deviceUuid")], (
        "an empty library sends every ground flag back to `sch.place_power`"
    )
    assert any(a == "sch.place_power" and p.get("net") == "GND"
               for a, p in editor.writes)
    assert any("地旗回落（180）" in note for note in payload["notes"]), (
        "the fallback is visible at the top level (`_render_draw_apply` prints it)"
    )
    assert any("地旗回落（180）" in note for note in payload["plan"]["notes"]), (
        "and on the plan's own notes channel"
    )
    assert not any("两族同形" in note for note in payload["notes"]), (
        "one ground family is not a two-family page"
    )


def _plan_with_a_second_ground(tmp_path: Path):
    """054's plan plus a second ground family (PGND), so a page has two."""
    plan_path, plan = m054._plan(tmp_path)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    data["change"]["flags"].append({
        "net": "PGND", "kind": "Ground", "symbolRef": "PWR-PGND",
        "symbolHash": data["change"]["flags"][-1]["symbolHash"],
        "x": 95.0, "y": -270.0, "rotation": 0.0, "onPin": "",
    })
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    return plan_path, plan


def test_two_ground_families_on_one_glyph_are_noted(monkeypatch, tmp_path, capsys):
    """GND and PGND both fall back → both on `place_power Ground` → one note."""
    plan_path, plan = _plan_with_a_second_ground(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    payload = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)

    assert {f["net"] for f in editor.flags} >= {"GND", "PGND"}
    two_family = [note for note in payload["notes"] if "两族同形" in note]
    assert len(two_family) == 1, payload["notes"]
    assert "GND" in two_family[0] and "PGND" in two_family[0]
    assert any("两族同形" in note for note in payload["plan"]["notes"])


def test_two_ground_families_each_on_their_own_glyph_are_silent(
        monkeypatch, tmp_path, capsys):
    """GND by symbol, PGND on the fallback → two glyphs → nothing to observe."""
    plan_path, plan = _plan_with_a_second_ground(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    editor.ground_symbols = {
        "Ground-GND": {"uuid": "dev-gnd", "libraryUuid": "lib-1"},
    }
    payload = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)

    assert not any("两族同形" in note for note in payload["notes"]), payload["notes"]
    assert any("地旗回落（180）" in note and "PGND" in note
               for note in payload["notes"]), "PGND's fallback is still announced"


def test_a_failed_lookup_is_not_worded_as_no_symbol(monkeypatch, tmp_path, capsys):
    """「查询未应答」不许说成「库没有」（180 审计 LOW-b）。

    `lib.device.search` 从未回答过时，回落仍然发生（不拦），但观察的措辞必须
    把「不知道有没有」和「查过了、没有」分开——后者是有证据的陈述，前者不是。
    """
    plan_path, plan = m054._plan(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    editor.unresolved.add("lib.device.search")
    payload = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)

    fallback = [n for n in payload["notes"] if "地旗回落（180）" in n]
    assert fallback, payload["notes"]
    assert any("查询未应答" in n for n in fallback), fallback
    assert not any("宿主库没有与 net" in n for n in fallback), payload["notes"]


def test_a_failed_placement_is_not_counted_in_the_two_family_note(
        monkeypatch, tmp_path, capsys):
    """落旗失败的网不进两族同形（180 审计 LOW-c1）：旗没落地就没有「挂」。

    两颗地旗都走回落（同一个 `place_power Ground` 字形键），PGND 那颗被拒——
    若登记不看落没落点，两族同形会声称两颗「挂在同一字形」，而 PGND 的旗根本
    不在画布上。
    """
    plan_path, plan = _plan_with_a_second_ground(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    editor.place_power_refused.add("PGND")
    m054._stub_editor(monkeypatch, editor)
    m054._stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    cli.main([  # 落旗失败可能改动退出码，本测试只看 notes —— 不断言 code
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert not any("两族同形" in note for note in payload["notes"]), (
        f"PGND's flag never landed, so there is no shared glyph to report: "
        f"{payload['notes']}"
    )
