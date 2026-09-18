"""The online path: mocked, ranked, and never on the network by accident.

Task 008b says the online comparison is an explicit ``--online`` and that
**tests must not touch the network**. Both halves are enforced here: the
fetcher is a seam, and one test replaces ``urllib.request.urlopen`` with
something that raises, so a regression that reaches for the real endpoint fails
loudly instead of quietly depending on the internet.

The catalog response below is **hand-built to the documented shape** (the key
names the reference implementation recorded). It is not a recording of the live
service: nothing in this repository has ever called it, and the task's
acceptance does not require that it should. The client is written so that a
different shape produces empty fields and a note rather than a silent empty
list.
"""

from __future__ import annotations

import asyncio
import urllib.request
from decimal import Decimal

import pytest

from boardwise.engines.catalog import CatalogCandidate, CatalogClient, CatalogError
from boardwise.engines.select import Resolution, resolve_by_lcsc, select_online

#: One catalog row in the documented shape. `componentLibraryType` is `base` for
#: JLC basic parts and `expand` otherwise; `attributes` carries the named
#: electrical parameters the value gate reads.
def row(
    code: str,
    *,
    mpn: str = "",
    describe: str = "",
    library_type: str = "expand",
    stock: int = 10000,
    preferred: bool = False,
    prices: list[dict] | None = None,
    attributes: list[dict] | None = None,
    category: str = "Chip Resistor - Surface Mount",
) -> dict:
    return {
        "componentCode": code,
        "componentModelEn": mpn,
        "componentBrandEn": "UNI-ROYAL",
        "componentSpecificationEn": describe,
        "describe": describe,
        "componentTypeEn": category,
        "stockCount": stock,
        "componentLibraryType": library_type,
        "preferredComponentFlag": preferred,
        "componentPrices": prices
        if prices is not None
        else [{"startNumber": 1, "endNumber": 999, "productPrice": 0.01}],
        "attributes": attributes if attributes is not None else [],
    }


def response(rows: list[dict]) -> dict:
    return {"code": 200, "data": {"componentPageInfo": {"list": rows}}}


def attribute(name: str, value: str) -> dict:
    return {"attribute_name_en": name, "attribute_value_name": value}


CLIENT = CatalogClient(fetcher=lambda payload: response([]))


# --------------------------------------------------------------------------
# the client
# --------------------------------------------------------------------------


def test_a_row_maps_to_the_pipeline_vocabulary():
    client = CatalogClient(
        fetcher=lambda payload: response(
            [
                row(
                    "C52548",
                    mpn="0805W8F330LT5E",
                    describe="330mΩ ±1% 0805",
                    library_type="base",
                    preferred=True,
                    attributes=[attribute("Resistance", "330mΩ")],
                )
            ]
        )
    )
    (candidate,) = client.search("330mΩ 0805")
    assert candidate.lcsc == "C52548"
    assert candidate.mpn == "0805W8F330LT5E"
    assert candidate.basic is True
    assert candidate.preferred is True
    assert candidate.stock == 10000
    assert candidate.attributes == {"Resistance": "330mΩ"}


def test_the_comparison_query_merges_base_and_general_and_deduplicates():
    """Basic parts only surface with `componentLibraryType='base'`."""
    seen: list[dict] = []

    def fetcher(payload: dict) -> dict:
        seen.append(payload)
        if payload.get("componentLibraryType") == "base":
            return response([row("C25744", library_type="base"), row("C999", library_type="base")])
        return response([row("C999"), row("C888", library_type="expand")])

    client = CatalogClient(fetcher=fetcher)
    merged = client.compare("10k 0402")
    assert [payload.get("componentLibraryType") for payload in seen] == ["base", None]
    assert {c.lcsc for c in merged} == {"C25744", "C999", "C888"}
    # the first occurrence wins, so a part basic in both lists stays basic
    assert next(c for c in merged if c.lcsc == "C999").basic is True


def test_a_changed_response_shape_is_reported_not_silently_empty():
    client = CatalogClient(fetcher=lambda payload: {"code": 200, "data": {}})
    assert client.search("x") == []
    assert any("componentPageInfo" in note for note in client.notes)


def test_a_row_without_a_c_number_is_not_a_part():
    client = CatalogClient(fetcher=lambda payload: response([{"describe": "junk"}]))
    assert client.search("x") == []


def test_the_tier_price_covers_the_quantity():
    candidate = CatalogCandidate(
        lcsc="C1",
        prices=[
            {"startNumber": 1, "endNumber": 99, "productPrice": 0.05},
            {"startNumber": 100, "endNumber": 999, "productPrice": 0.02},
            {"startNumber": 1000, "endNumber": None, "productPrice": 0.005},
        ],
    )
    assert candidate.unit_price(10) == Decimal("0.05")
    assert candidate.unit_price(100) == Decimal("0.02")
    assert candidate.unit_price(5000) == Decimal("0.005")
    assert CatalogCandidate(lcsc="C1").unit_price(10) is None


def test_a_network_failure_is_one_readable_error():
    def boom(payload: dict) -> dict:
        raise CatalogError("JLC SMT request failed: connection refused")

    with pytest.raises(CatalogError):
        CatalogClient(fetcher=boom).search("x")


# --------------------------------------------------------------------------
# ranking: spec match -> buildable -> basic -> preferred -> cheapest
# --------------------------------------------------------------------------


def _online(rows: list[dict], query: str, qty: int = 100):
    return select_online(
        query, qty=qty, client=CatalogClient(fetcher=lambda payload: response(rows))
    )


def test_the_ranking_order_is_the_one_the_task_names():
    rows = [
        row("C1", mpn="A", library_type="base", stock=50),           # basic, not enough stock
        row("C2", mpn="B", library_type="expand", stock=10000),      # in stock, extended
        row("C3", mpn="C", library_type="base", stock=10000, preferred=True),
    ]
    result = _online(rows, "resistor", qty=100)
    # buildability beats the basic flag: the in-stock basic wins...
    assert [c.lcsc for c in result.candidates] == ["C3", "C2", "C1"]
    assert result.candidates[0].in_stock and result.candidates[-1].in_stock is False


def test_a_cheaper_basic_part_beats_a_dearer_one():
    rows = [
        row("C1", mpn="A", library_type="base",
            prices=[{"startNumber": 1, "endNumber": None, "productPrice": 0.05}]),
        row("C2", mpn="B", library_type="base",
            prices=[{"startNumber": 1, "endNumber": None, "productPrice": 0.01}]),
    ]
    assert [c.lcsc for c in _online(rows, "resistor").candidates] == ["C2", "C1"]


def test_preferred_breaks_a_price_tie():
    rows = [
        row("C1", mpn="A", library_type="base"),
        row("C2", mpn="B", library_type="base", preferred=True),
    ]
    assert [c.lcsc for c in _online(rows, "resistor").candidates] == ["C2", "C1"]


def test_an_extended_part_can_win_when_the_basic_one_is_out_of_stock():
    rows = [
        row("C1", mpn="A", library_type="base", stock=10),
        row("C2", mpn="B", library_type="expand", stock=10000),
    ]
    assert [c.lcsc for c in _online(rows, "resistor", qty=500).candidates] == ["C2", "C1"]


# --------------------------------------------------------------------------
# the resistance gate on catalog rows
# --------------------------------------------------------------------------


def test_the_gate_reads_the_named_resistance_attribute():
    rows = [
        row("C52548", mpn="0805W8F330LT5E", attributes=[attribute("Resistance", "330mΩ")]),
        row("C25150", mpn="0805W8F330JT5E", attributes=[attribute("Resistance", "33Ω")]),
    ]
    result = _online(rows, "330mΩ 0805")
    assert [c.lcsc for c in result.candidates] == ["C52548"]
    assert result.candidates[0].resistance == {
        "raw": "330mΩ", "ohms": "0.33", "from": "attributes.Resistance",
    }
    other = _online(rows, "33Ω 0805")
    assert [c.lcsc for c in other.candidates] == ["C25150"]


def test_a_part_number_is_never_the_source_of_a_resistance():
    """#202: `330mΩ` must not be answered by a part whose *name* contains 330."""
    rows = [row("C25150", mpn="0805W8F330JT5E", describe="330 0805 resistor")]
    result = _online(rows, "330mΩ 0805")
    assert result.candidates == []
    assert result.exit_code == 1


def test_an_inductor_with_a_resistance_attribute_is_not_a_resistor():
    """A DCR is not the component being asked for."""
    rows = [
        row("C1", mpn="DFE252012PD-2R2M", category="Power Inductors",
            attributes=[attribute("Resistance", "330mΩ")]),
    ]
    assert _online(rows, "330mΩ").candidates == []


def test_a_description_is_only_a_fallback_and_must_be_unambiguous():
    single = [row("C1", describe="330mΩ ±1%")]
    assert [c.lcsc for c in _online(single, "330mΩ").candidates] == ["C1"]
    assert _online(single, "330mΩ").candidates[0].resistance["from"] == "describe"
    # two quantities in the prose is ambiguous, so it is not a declaration
    assert _online([row("C1", describe="330mΩ to 33Ω")], "330mΩ").candidates == []
    # a conflicting declared attribute wins nothing either
    conflicting = [
        row("C1", attributes=[attribute("Resistance", "330mΩ"), attribute("阻值", "33Ω")])
    ]
    assert _online(conflicting, "330mΩ").candidates == []


def test_a_gated_online_miss_exits_one():
    result = _online([row("C1", attributes=[attribute("Resistance", "10kΩ")])], "330mΩ")
    assert result.candidates == []
    assert result.exit_code == 1


# --------------------------------------------------------------------------
# the network is never reached by accident
# --------------------------------------------------------------------------


def test_the_injected_fetcher_is_the_only_thing_that_can_reach_the_network(monkeypatch):
    def forbidden(*_args, **_kwargs):  # pragma: no cover - only on a mistake
        raise AssertionError("a test reached for the network")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    rows = [row("C1", attributes=[attribute("Resistance", "330mΩ")])]
    result = select_online(
        "330mΩ 0805", client=CatalogClient(fetcher=lambda payload: response(rows))
    )
    assert [c.lcsc for c in result.candidates] == ["C1"]


# --------------------------------------------------------------------------
# resolving an online pick's identity (bridge; exact key only)
# --------------------------------------------------------------------------


class FakeBridge:
    """A `BridgeClient` that answers from a table, and records what it was asked."""

    def __init__(self, items: list[dict] | None = None, error: Exception | None = None):
        self.items = items or []
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call(self, action: str, params: dict) -> dict:
        self.calls.append((action, params))
        if self.error is not None:
            raise self.error
        return {"keyword": params.get("keyword"), "returned": len(self.items),
                "shown": len(self.items), "items": self.items}


def resolve(items: list[dict] | None = None, error: Exception | None = None) -> Resolution:
    return asyncio.run(resolve_by_lcsc(FakeBridge(items, error), "C52548"))


def test_resolving_by_c_number_is_an_exact_match():
    result = resolve(
        [
            {"uuid": "dev-1", "supplierId": "C99999", "footprintName": "R0805"},
            {"uuid": "dev-2", "supplierId": "C52548", "footprintName": "R0805",
             "libraryUuid": "lib-1"},
        ]
    )
    assert result.resolved
    assert result.deviceUuid == "dev-2"
    assert result.libraryUuid == "lib-1"
    assert result.footprint_name == "R0805"
    # the key that carried the C-number is reported, not assumed
    assert result.matched_key == "supplierId"
    assert result.items_seen == 2


def test_a_fuzzy_hit_is_not_an_identity():
    """A keyword search that returned *something* proves nothing."""
    result = resolve([{"uuid": "dev-1", "description": "a 330mΩ resistor"}])
    assert not result.resolved
    assert "refusing to guess" in result.reason


def test_an_ambiguous_c_number_is_refused():
    result = resolve(
        [
            {"uuid": "dev-1", "supplierId": "C52548"},
            {"uuid": "dev-2", "supplierId": "C52548"},
        ]
    )
    assert not result.resolved
    assert "must be unique" in result.reason


def test_a_match_without_a_device_uuid_is_refused():
    result = resolve([{"supplierId": "C52548", "footprintName": "R0805"}])
    assert not result.resolved
    assert "no device uuid" in result.reason


def test_a_bridge_failure_is_reported_not_swallowed():
    result = resolve(error=RuntimeError("daemon not reachable"))
    assert not result.resolved
    assert "daemon not reachable" in result.reason


def test_the_search_is_asked_for_the_c_number_itself():
    bridge = FakeBridge([{"uuid": "dev-1", "supplierId": "C52548"}])
    asyncio.run(resolve_by_lcsc(bridge, "C52548", limit=5))
    assert bridge.calls == [("lib.device.search", {"keyword": "C52548", "limit": 5})]


def test_an_empty_c_number_is_refused_before_any_call():
    bridge = FakeBridge()
    result = asyncio.run(resolve_by_lcsc(bridge, "  "))
    assert not result.resolved and bridge.calls == []
