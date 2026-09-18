"""Offline selection: the resistance gate, the vocabulary, exit codes.

The sharp version of the #202 negative lives here: a library holding **both** a
`330mΩ` and a `33Ω` part, where the query has to pick the right one and reject
the other. On the harvested library alone that case cannot be tested, because
neither board places a 330mΩ resistor — so the test builds the pair.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.parts import PartEntry, PartLibrary, PartProvenance, load_parts
from boardwise.engines.select import Candidate, select, select_offline

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "blocklib" / "parts.json"


def part(key: str, *, value: str, footprint: str, lcsc: str, mpn: str = "", basic=True):
    return PartEntry(
        key=key,
        value=value,
        mpn=mpn,
        lcsc=lcsc,
        manufacturer="ACME",
        deviceUuid=f"dev-{lcsc}",
        libraryUuid="lib-1",
        footprint_name=footprint,
        basic=basic,
        provenance=PartProvenance(
            kind="board-extract", source="synthetic", designators=[f"{key}@board"]
        ),
    )


@pytest.fixture
def pair_library() -> PartLibrary:
    """A 330mΩ and a 33Ω 0805 resistor — the #202 trap, both present."""
    return PartLibrary(
        parts=[
            part("res.330m_0805", value="330mΩ", footprint="R0805", lcsc="C52548",
                 mpn="0805W8F330LT5E", basic=False),
            part("res.33_0805", value="33Ω", footprint="R0805", lcsc="C25150",
                 mpn="0805W8F330JT5E", basic=True),
            part("res.330k_0805", value="330kΩ", footprint="R0805", lcsc="C99999"),
        ]
    )


def test_a_milliohm_query_picks_the_milliohm_part_and_only_it(pair_library):
    """`330mΩ` must never be answered with `33Ω` — and the parts are both here."""
    result = select_offline("330mΩ 0805", pair_library)
    assert [c.lcsc for c in result.candidates] == ["C52548"]
    assert result.exit_code == 0
    assert result.candidates[0].resistance["ohms"] == "0.33"
    assert result.candidates[0].resistance["from"] == "value"


def test_the_same_library_answers_the_ohm_query_with_the_ohm_part(pair_library):
    result = select_offline("33Ω 0805", pair_library)
    assert [c.lcsc for c in result.candidates] == ["C25150"]


def test_a_megaohm_query_is_not_answered_by_a_milliohm_part(pair_library):
    result = select_offline("330MΩ 0805", pair_library)
    assert result.candidates == []
    assert result.exit_code == 1


def test_a_gated_query_with_no_candidate_exits_one(pair_library):
    result = select_offline("10kΩ 0805", pair_library)
    assert result.candidates == []
    assert result.gated
    assert result.exit_code == 1
    assert any("no curated part matches" in n for n in result.notes)


def test_a_malformed_resistance_fails_closed_without_a_fuzzy_fallback(pair_library):
    for query in ("1/2Ω 0805", "3e3ohm"):
        result = select_offline(query, pair_library)
        assert result.candidates == [], query
        assert result.exit_code == 1, query
        assert any("cannot be read as exactly one number" in n for n in result.notes)


def test_a_fuzzy_query_that_finds_nothing_is_not_an_error(pair_library):
    """The reference draws the same line: only a gated miss is a failure."""
    result = select_offline("nosuchpart", pair_library)
    assert result.candidates == []
    assert not result.gated
    assert result.exit_code == 0


def test_a_word_outside_the_vocabulary_table_does_not_constrain(pair_library):
    result = select_offline("33Ω 9999", pair_library)
    assert result.unmapped_words == ["9999"]
    assert any("not in the footprint vocabulary table" in n for n in result.notes)
    # no mapping means no constraint: the 0805 part still answers
    assert [c.lcsc for c in result.candidates] == ["C25150"]


def test_a_category_word_narrows_the_table_without_narrowing_anything_else():
    library = PartLibrary(
        parts=[
            part("res.100_0402", value="100Ω", footprint="R0402", lcsc="C1"),
            part("cap.100p_0402", value="100pF", footprint="C0402", lcsc="C2"),
            part("led.100_0402", value="", footprint="LED0402", lcsc="C3"),
        ]
    )
    # A bare size is a filter: all four library names it maps to are accepted,
    # and with no other search term the order is the deterministic key order.
    plain = select_offline("0402", library)
    assert {c.lcsc for c in plain.candidates} == {"C1", "C2", "C3"}
    assert [c.lcsc for c in plain.candidates] == ["C2", "C3", "C1"]
    assert [c.lcsc for c in select_offline("0402", library).candidates] == [
        c.lcsc for c in plain.candidates
    ]
    # A category word narrows the table and nothing else.
    assert [c.lcsc for c in select_offline("cap 0402", library).candidates] == ["C2"]
    assert [c.lcsc for c in select_offline("电容 0402", library).candidates] == ["C2"]
    assert [c.lcsc for c in select_offline("res 0402", library).candidates] == ["C1"]
    # A size the user already spelled as a library name is accepted as written.
    assert [c.lcsc for c in select_offline("LED0402", library).candidates] == ["C3"]


def test_relevance_decides_first_and_basic_breaks_the_tie():
    library = PartLibrary(
        parts=[
            part("res.10k_0603", value="10kΩ", footprint="R0603", lcsc="C1", basic=False),
            part("res.10k_0603.b", value="10kΩ", footprint="R0603", lcsc="C2", basic=True),
        ]
    )
    result = select_offline("10kΩ 0603", library)
    assert [c.lcsc for c in result.candidates] == ["C2", "C1"]


def test_an_offline_candidate_claims_no_stock_or_price():
    """`stock: 0` would read as "out of stock" — a claim nobody made."""
    library = PartLibrary(parts=[part("res.10k_0603", value="10kΩ", footprint="R0603", lcsc="C1")])
    candidate = select_offline("10kΩ 0603", library).candidates[0]
    payload = candidate.as_json()
    assert "stock" not in payload and "unit_price" not in payload and "in_stock" not in payload
    assert payload["source"] == "blocklib/parts.json"
    # ...whereas a catalog candidate does carry them
    live = Candidate(source="jlcpcb.com", lcsc="C1", stock=1000, in_stock=True)
    assert "stock" in live.as_json() and live.as_json()["stock"] == 1000


# --------------------------------------------------------------------------
# against the harvested library, and through the CLI
# --------------------------------------------------------------------------


def test_the_committed_library_answers_a_capacitor_query():
    result = select_offline("100nF 0805", load_parts(LIBRARY))
    assert result.candidates
    assert all(c.lcsc for c in result.candidates)
    assert {c.basic for c in result.candidates} <= {True}


def test_the_committed_library_answers_by_mpn_and_by_part_name():
    library = load_parts(LIBRARY)
    assert select_offline("CH340N", library).candidates
    assert select_offline("STM32G431RBT6", library).candidates


def test_the_committed_library_answers_the_shunt_by_its_milliohms():
    result = select_offline("5mΩ 2512", load_parts(LIBRARY))
    assert [c.lcsc for c in result.candidates] == ["C46634460"]
    assert result.candidates[0].resistance["ohms"] == "0.005"


def test_the_library_now_answers_the_pull_down_the_ch340_board_needed():
    """The 0402 5.1k that 006b had to hand-pick — harvested from a later board.

    It arrived with the two `.epro2` exports (the boards that could not be read
    as local projects), which is why having both readers matters beyond tidiness:
    the shelf now answers `5.1kΩ 0402` with a verified part instead of nothing.
    """
    result = select_offline("5.1kΩ 0402", load_parts(LIBRARY))
    assert [c.lcsc for c in result.candidates] == ["C2906948"]
    assert result.candidates[0].key == "res.5k1_0402"
    assert result.candidates[0].resistance["ohms"] == "5100"
    # The size still constrains: the same value in another package is not offered.
    assert select_offline("5.1kΩ 0603", load_parts(LIBRARY)).candidates == []


def test_the_cli_reports_a_gated_miss_with_exit_code_one(capsys):
    code = cli.main(["parts", "select", "330mΩ 2512", "--library", str(LIBRARY)])
    out = capsys.readouterr().out
    assert code == 1
    assert "resistance gate: 0.330 Ω" in out
    assert "no candidate" in out


def test_the_cli_prints_the_machine_readable_shape(capsys):
    import json

    code = cli.main(["parts", "select", "5mΩ 2512", "--library", str(LIBRARY), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["source"] == "blocklib/parts.json"
    assert payload["resistance"]["ohms"] == "0.005"
    assert payload["candidates"][0]["lcsc"] == "C46634460"
    assert payload["candidates"][0]["key"] == "res.5m_2512"


def test_the_cli_rejects_an_unreadable_library(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.main(["parts", "select", "x", "--library", str(bad)]) == 2
    assert "not JSON" in capsys.readouterr().err


def test_select_is_the_front_door_and_stays_offline_by_default(monkeypatch):
    """`select(..., online=False)` must not be able to reach a network."""
    import boardwise.engines.catalog as catalog

    def explode(*_args, **_kwargs):  # pragma: no cover - only reached on a mistake
        raise AssertionError("the offline path built a network client")

    monkeypatch.setattr(catalog, "urllib_fetcher", explode)
    result = select("5mΩ 2512", load_parts(LIBRARY), online=False)
    assert result.candidates and not result.online


# --------------------------------------------------------------------------
# --resolve / --write: the identity loop, with the bridge stubbed
# --------------------------------------------------------------------------


class _StubClient:
    """A `BridgeClient` that answers `lib.device.search` from a table."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    @classmethod
    async def open(cls, *_args, **_kwargs):
        return _OPENED[-1]

    async def call(self, action, params):
        self.calls.append((action, params))
        return {"keyword": params.get("keyword"), "returned": len(self.items),
                "shown": len(self.items), "items": self.items}

    async def close(self) -> None:
        return None


_OPENED: list = []


def _stub_bridge(monkeypatch, items):
    from boardwise.bridge.protocol import BridgeError

    class _StubDaemon:
        @staticmethod
        def resolve_port() -> int:
            return 1

        @staticmethod
        def ensure_token() -> str:
            return "token"

    class _StubModule:
        BridgeClient = _StubClient

    client = _StubClient(items)
    _OPENED.append(client)
    monkeypatch.setattr(cli, "_bridge_modules", lambda: (_StubModule, _StubDaemon, BridgeError))
    return client


def test_resolve_reports_the_identity_it_found(monkeypatch, capsys):
    bridge = _stub_bridge(
        monkeypatch,
        [{"uuid": "dev-1", "supplierId": "C46634460", "libraryUuid": "lib-1",
          "footprintName": "R2512"}],
    )
    code = cli.main(["parts", "select", "5mΩ 2512", "--library", str(LIBRARY), "--resolve"])
    out = capsys.readouterr().out
    assert code == 0
    assert "resolve C46634460: ok" in out
    assert "deviceUuid=dev-1" in out and "footprint=R2512" in out
    assert bridge.calls[0][0] == "lib.device.search"


def test_resolve_refuses_a_fuzzy_hit_and_does_not_write(monkeypatch, capsys, tmp_path):
    _stub_bridge(monkeypatch, [{"uuid": "dev-1", "description": "some resistor"}])
    target = tmp_path / "parts.json"
    target.write_bytes(LIBRARY.read_bytes())
    before = target.read_text(encoding="utf-8")
    code = cli.main(
        [
            "parts", "select", "5mΩ 2512", "--library", str(target),
            "--resolve", "--write",
        ]
    )
    assert code == 2
    assert "not writing an unresolved identity" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == before


def test_write_adds_the_resolved_pick_to_the_library(monkeypatch, capsys, tmp_path):
    _stub_bridge(
        monkeypatch,
        [{"uuid": "dev-9", "supplierId": "C46634460", "libraryUuid": "lib-1",
          "footprintName": "R2512"}],
    )
    target = tmp_path / "parts.json"
    target.write_bytes(LIBRARY.read_bytes())
    code = cli.main(
        [
            "parts", "select", "5mΩ 2512", "--library", str(target),
            "--resolve", "--write",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    # The C-number is already curated *from a board*, which is the stronger
    # claim; the online row must not downgrade it to a catalog selection.
    assert "already curates C46634460 (board-extract)" in out
    assert target.read_text(encoding="utf-8") == LIBRARY.read_text(encoding="utf-8")


def test_write_records_a_new_online_pick_with_catalog_provenance(
    monkeypatch, capsys, tmp_path
):
    _stub_bridge(
        monkeypatch,
        [{"uuid": "dev-new", "supplierId": "C1234567", "libraryUuid": "lib-1",
          "footprintName": "R0603"}],
    )
    # A query the curated library cannot answer, but whose C-number resolves.
    # `_cmd_parts_select` imports `select` inside the function, so the patch goes
    # on the module that owns the name.
    import boardwise.engines.select as select_module

    monkeypatch.setattr(select_module, "select", lambda *a, **k: _fake_result())
    target = tmp_path / "parts.json"
    target.write_bytes(LIBRARY.read_bytes())
    code = cli.main(
        ["parts", "select", "anything", "--library", str(target), "--resolve", "--write"]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "written:" in out
    import json as _json

    payload = _json.loads(target.read_text(encoding="utf-8"))
    added = next(p for p in payload["parts"] if p["lcsc"] == "C1234567")
    assert added["provenance"]["kind"] == "catalog-select"
    assert added["deviceUuid"] == "dev-new"
    assert added["footprint_name"] == "R0603"
    assert payload["parts"] == sorted(payload["parts"], key=lambda p: p["key"])


def _fake_result():
    from boardwise.engines.select import SelectionResult, Candidate
    from boardwise.core.parts import ResistanceQuery

    return SelectionResult(
        query="anything",
        resistance=ResistanceQuery(active=False, ohms=None, remainder="anything"),
        candidates=[
            Candidate(
                source="jlcpcb.com", lcsc="C1234567", mpn="ACME-1", brand="ACME",
                description="a part", stock=1000, in_stock=True, basic=True,
                unit_price=Decimal("0.01"),
            )
        ],
    )
