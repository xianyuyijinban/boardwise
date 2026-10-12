"""173/C: the drawing keeps isolated ground domains apart.

**The backlog item.** 155's 岳裁③ closed the P22 questions and left this one on
the drawing line: 「AI 画的时候没有按隔离分地（画图棒重启时要带上地族）」. The
compiler chose one flag for every ground net — `_flag_plan` read
``budget.gnd_flag`` for the whole ``gnd`` class — so on a page with two isolated
grounds (``PGND`` and ``SEC_GND``) both were drawn with the same ``Ground-GND``
glyph. Two grounds the circuit keeps apart read as one.

**What this batch connects.** The mapping 「网的域 → 旗标族」: ``_flag_ref`` asks
``rules/pcb/focground.domain_of`` (read-only; that is the word list 155/164a audit
the isolation domains with) for the domain a ground net's name spells, and when a
page's ``gnd`` nets spell **more than one** domain, each asks for the flag named
after itself (``PWR-<net>``) instead of the family's shared symbol. A page whose
grounds all sit in one domain has nothing to isolate and is untouched.

**The residual is pinned, not hidden.** Where the library carries no per-domain
symbol the shared family symbol is kept (test 4). That is not the compiler
deciding anything: this repo's flyback book titles its one ground flag
「the source-side (PGND) and the secondary-side (SEC_GND) ground families」, so
one glyph for both is what that book states. Closing the residual is a library
addition (a symbol per domain), which is a curation act and outside this batch.
"""

from __future__ import annotations

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability

PROV = "verified_recipe"


# ------------------------------------------------------------------ 最小夹具
#
# Hand-written spec + library, like `test_053b_drawcompiler`'s: this file judges
# *compilation*, so the library is plain pin spans and the flags are glyph boxes
# with no pins. Nothing here reads a fixture file.


def _resistor(ref: str = "R0402") -> SymbolProfile:
    return SymbolProfile(
        symbol_ref=ref, title="Resistor", body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
    )


def _flag(ref: str) -> SymbolProfile:
    """A rail/ground flag: a glyph box and no pins."""
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-6.0, 0.0, 6.0, 18.0), pins=[],
    )


def _book(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    book = {"R0402": _resistor(), "PWR-VIN": _flag("PWR-VIN"), "PWR-GND": _flag("PWR-GND")}
    book.update(overrides)
    return book


def _part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def _net(net_id: str, cls: str, members: list[str]) -> dict:
    return {"id": net_id, "class": cls, "members": list(members), "provenance": PROV}


def _ladder(second_ground: str) -> tuple[CircuitSpec, PresentationSpec]:
    """A three-rung ladder whose bottom rung returns to ``second_ground``.

    R1/R2 form the divider with ``TAP`` between them and R3 hangs the tap to a
    **second** ground net — the shape a dual-domain board has (two `gnd`-class
    nets on one page), reduced to what the compiler has to decide.
    """
    circuit = CircuitSpec.from_dict({
        "parts": [_part("R1", "R0402", "10k"), _part("R2", "R0402", "10k"),
                  _part("R3", "R0402", "1k")],
        "nets": [
            _net("VIN", "power", ["R1.1"]),
            _net("TAP", "signal", ["R1.2", "R2.1", "R3.1"]),
            _net("GND", "gnd", ["R2.2"]),
            _net(second_ground, "gnd", ["R3.2"]),
        ],
    })
    presentation = PresentationSpec.from_dict({
        "grammarRef": "voltage-divider",
        "modules": [{"id": "ladder", "parts": ["R1", "R2", "R3"], "role": "ladder"}],
        "portRoles": {"VIN": "input"},
        "directWiringObligations": [
            {"nets": ["VIN", "TAP", "GND"], "note": "the ladder is wired"},
        ],
    })
    return circuit, presentation


def _refs(plan) -> dict[str, str]:
    """``net -> symbol_ref`` for the plan's flags (one flag per net here)."""
    return {symbol.net: symbol.symbol_ref for symbol in plan.power_symbols}


def _compile(circuit, presentation, book):
    result = dc.compile(circuit, presentation, book, dc.CompileBudget())
    assert result.ok, [item.detail for item in result.failures]
    return result.candidates[0]


# ------------------------------------------------------------------- 域的口径


def test_a_ground_net_is_keyed_to_its_isolation_domain():
    """``domain_of``'s two buckets, and an unclassified ground keyed by its name.

    ``domain_of('SEC_GND')`` is ``''`` — 145a taught the *ground* vocabulary that
    name, but this table is a two-prefix test (power ``PGND``/``EARTH``, logic
    ``GND``/``AGND``/``DGND``). ``''`` is not a domain, so the net keys on its own
    name: filing ``SEC_GND`` under the logic domain would be a claim the word list
    does not make, and this repo reports UNKNOWN rather than guessing.
    """
    assert dc._ground_domain("PGND") == "power"
    assert dc._ground_domain("EARTH") == "power"
    assert dc._ground_domain("AGND") == "logic"
    assert dc._ground_domain("GND") == "logic"
    assert dc._ground_domain("SEC_GND") == "SEC_GND"
    assert dc._ground_domain("SEC_12V") == "SEC_12V", "not ground, but still keyed"


def test_the_page_domain_count_is_over_the_gnd_class_only():
    """Rails are not grounds, and a ground net that is not on the page counts not.

    The count is what decides whether there is anything to isolate, so it must be
    a fact about this circuit's ``gnd`` nets and nothing else: ``VIN`` is a power
    net and ``R0402`` is not a net at all.
    """
    circuit, _presentation = _ladder("SEC_GND")
    ctx = _context(circuit)
    assert dc._ground_domains(ctx) == {"logic", "SEC_GND"}
    # and a page whose two grounds are both the logic domain really is one domain
    same_domain, _presentation2 = _ladder("AGND")
    assert dc._ground_domains(_context(same_domain)) == {"logic"}


def _context(circuit: CircuitSpec) -> dc._Context:
    """A ``_Context`` carrying only what the flag chooser reads.

    ``_flag_ref`` / ``_ground_domains`` read ``ctx.circuit``, ``ctx.book`` and
    ``ctx.budget`` and nothing else, so the geometry stages are left unbuilt —
    this is the unit half of the same question the compile tests ask end to end.
    """
    return dc._Context(
        circuit=circuit,
        presentation=PresentationSpec.from_dict({"grammarRef": "voltage-divider"}),
        binding=None,
        book=_book(),
        budget=dc.CompileBudget(),
        axis="x",
        progress=(1.0, 0.0),
        chain_net_rank={},
        slots={},
        chain=[],
        accepted={},
        body_dirs={},
    )


# ------------------------------------------------------- 两域各挂各旗（编译级）


def test_two_domains_get_the_flag_named_after_each_net():
    """The backlog item, end to end: the second domain stops sharing the glyph."""
    circuit, presentation = _ladder("SEC_GND")
    book = _book(**{"PWR-SEC_GND": _flag("PWR-SEC_GND")})
    plan = _compile(circuit, presentation, book)
    assert _refs(plan) == {"VIN": "PWR-VIN", "GND": "PWR-GND", "SEC_GND": "PWR-SEC_GND"}


def test_both_power_and_logic_domains_are_covered():
    """``PGND`` (power domain) takes its own flag on the same shape."""
    circuit, presentation = _ladder("PGND")
    book = _book(**{"PWR-PGND": _flag("PWR-PGND")})
    plan = _compile(circuit, presentation, book)
    assert _refs(plan) == {"VIN": "PWR-VIN", "GND": "PWR-GND", "PGND": "PWR-PGND"}


def test_a_single_domain_page_keeps_the_family_symbol():
    """One domain has nothing to isolate: the shared symbol is its own symbol.

    ``GND`` and ``AGND`` are both the logic domain by this word list, so a page
    carrying the two of them is still a one-domain page and nothing is renamed —
    the same claim ``focground`` makes when it pairs a power net against the
    whole logic side.
    """
    circuit = CircuitSpec.from_dict({
        "parts": [_part("R1", "R0402", "10k"), _part("R2", "R0402", "10k"),
                  _part("R3", "R0402", "1k")],
        "nets": [
            _net("VIN", "power", ["R1.1"]),
            _net("TAP", "signal", ["R1.2", "R2.1", "R3.1"]),
            _net("GND", "gnd", ["R2.2"]),
            _net("AGND", "gnd", ["R3.2"]),
        ],
    })
    presentation = PresentationSpec.from_dict({
        "grammarRef": "voltage-divider",
        "modules": [{"id": "ladder", "parts": ["R1", "R2", "R3"], "role": "ladder"}],
        "portRoles": {"VIN": "input"},
        "directWiringObligations": [{"nets": ["VIN", "TAP", "GND"], "note": "wired"}],
    })
    book = _book(**{"PWR-AGND": _flag("PWR-AGND")})
    plan = _compile(circuit, presentation, book)
    assert _refs(plan) == {"VIN": "PWR-VIN", "GND": "PWR-GND", "AGND": "PWR-GND"}


def test_the_library_without_a_split_symbol_keeps_the_family_symbol():
    """The residual, pinned: no per-domain symbol in the book → the shared one.

    This is the state of every library this repo ships, so it is asserted rather
    than left to chance: the mapping takes effect when the book carries the
    symbol, and until then the page draws one family glyph — the same glyph the
    book's own title says stands for both ground families.
    """
    circuit, presentation = _ladder("SEC_GND")
    plan = _compile(circuit, presentation, _book())
    assert _refs(plan) == {"VIN": "PWR-VIN", "GND": "PWR-GND", "SEC_GND": "PWR-GND"}


# --------------------------------------------------------------- 无跨域并地


def test_no_conductor_joins_two_ground_domains():
    """The picture's own netlist, read back: two domains, two nodes, two names.

    ``derive_netlist`` is the checker's independent reading of the drawing (it
    consults no spec), so this is the end-to-end statement the backlog asked for:
    the two grounds are **not one node**, and each is named by its own flag. Run
    under both books — a split symbol is about which glyph, never about
    connectivity.
    """
    for book in (_book(), _book(**{"PWR-SEC_GND": _flag("PWR-SEC_GND")})):
        circuit, presentation = _ladder("SEC_GND")
        plan = _compile(circuit, presentation, book)
        netlist = readability.derive_netlist(plan, book)
        assert netlist.group_of("R2.2") != netlist.group_of("R3.2"), (
            f"the two ground domains were drawn as one node: {netlist.groups}"
        )
        assert netlist.names_of("R2.2") == ("GND",), netlist.names_of("R2.2")
        assert netlist.names_of("R3.2") == ("SEC_GND",), netlist.names_of("R3.2")
        # and the checker agrees the drawing is legal
        checked = readability.check(
            plan, circuit, presentation, book, page_box=None,
            grid=dc.CompileBudget().grid,
        )
        assert not checked.hard_violations, [
            item.render() for item in checked.hard_violations
        ]
