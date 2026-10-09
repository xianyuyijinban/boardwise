"""143f: the four `core/symbolprofile.py` holes from `outputs/143_dig/07`.

Each one is a **second answer** to a question the module (or the tree) already
answers somewhere else, which is why every test here compares two readings of the
same value instead of asserting a literal:

* 洞3 — :meth:`SymbolProfile.role_pins` did not fall back to the pin *name* while
  :func:`role_of_pin` (and ``grammar.base.role_pins_of``, which copies it) did;
* 洞4 — :func:`role_siblings` resolved its token in **list order** while the whole
  rest of the tree resolves "number first, then name";
* 洞5 — :func:`_pin_sort_key` gave ``"1"`` and ``"01"`` the same key (so
  `geometry_hash` depended on emission order) and called ``int()`` on ``"²"``
  (a bare `ValueError` outside `SymbolProfileError`);
* 洞6 — :func:`_attr_map` normalized its keys to `str` while
  :func:`from_parsed_symbol` looked them up by the caller's original key, so an
  int-keyed parser value lost every name, `Pin Type` and role without a word.

Reproductions: `outputs/143_dig/07/p1_sortkey_and_hash.py`,
`p3_role_rulers.py` (A/B), `p5_key_and_token.py`.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from boardwise.core.symbolprofile import (
    ROLE_BY_PIN_NAME,
    SymbolPin,
    SymbolProfile,
    _pin_sort_key,
    from_parsed_symbol,
    role_of_pin,
    role_siblings,
)
from boardwise.engines.grammar.base import role_pins_of

SPECS = Path(__file__).resolve().parents[1] / "blocklib" / "specs"


# --------------------------------------------------------------------------
# 洞3: two definitions of "which role does this pin have"
# --------------------------------------------------------------------------


def _named_pins():
    """A profile whose roles can only come from the **names** (no electricalRole).

    That is the shape hand-written library documents have — the CH340G this hole
    was measured on ships ``GND``/``VCC`` with an empty ``electricalRole`` — so a
    role read from the field alone is empty while the pin is plainly the ground.
    """
    return SymbolProfile(
        symbol_ref="NAMEONLY-1",
        pins=[
            SymbolPin(number="1", tip=(-40.0, 0.0), name="GND"),
            SymbolPin(number="2", tip=(40.0, 0.0), name="VCC"),
            SymbolPin(number="3", tip=(0.0, -40.0), name="EP"),
        ],
    )


def test_role_pins_falls_back_to_the_pin_name_like_role_of_pin():
    profile = _named_pins()
    ground = profile.pin("1")
    assert ground.electrical_role == "", "the fixture states no role on the field"
    assert role_of_pin(ground) == "GND", "the module's own role rule reads the name"

    assert profile.role_pins("GND") == [ground], (
        "the method used to answer [] for a pin role_of_pin answers 'GND' for — "
        "two rulers for one pin inside one module"
    )
    assert profile.role_pins("VIN") == [profile.pin("2")]


def test_role_pins_and_role_of_pin_disagree_on_no_profile_the_repo_ships():
    """The family check: every profile in `blocklib/specs` reads the same both ways.

    Not just the CH340G witness — a profile whose pin names *are* the roles is
    the common case in this corpus, and a method that reads only
    ``electricalRole`` would answer for none of them.
    """
    files = sorted(SPECS.glob("*.library.json"))
    assert files, "the shipped library is the corpus this claim is about"
    seen = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["profiles"]:
            profile = SymbolProfile.from_dict(entry)
            for role in set(role_of_pin(pin) for pin in profile.pins) - {""}:
                expected = [pin for pin in profile.pins if role_of_pin(pin) == role]
                assert profile.role_pins(role) == expected, (path.name, role)
                seen += 1
    assert seen, "no role was read anywhere — the sweep would prove nothing"


def test_role_pins_and_role_pins_of_are_the_same_reading():
    """`grammar.base.role_pins_of` is the tree's ruler; this method must not differ."""
    for path in sorted(SPECS.glob("*.library.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["profiles"]:
            profile = SymbolProfile.from_dict(entry)
            for role, pins in role_pins_of(profile).items():
                assert profile.role_pins(role) == list(pins), (path.name, role)


# --------------------------------------------------------------------------
# 洞4: one token, two rulers
# --------------------------------------------------------------------------


def test_role_siblings_takes_the_number_first_then_the_name():
    """A pin *name* equal to another pin's *number* — the tree's ruler decides.

    ``VOUT`` is pin 2's number and pin 1's name here, and the two pins carry
    different roles, so the old list-order reading and the number's reading hold
    up **different sibling sets**. `drawcompiler._pin_of_token` and
    `grammar.base.profile_pin_for` are the yardstick: number first.
    """
    profile = SymbolProfile(
        symbol_ref="CRAFTED",
        pins=[
            SymbolPin(number="1", tip=(-20.0, 0.0), name="VOUT"),
            SymbolPin(number="VOUT", tip=(20.0, 0.0), name="GND"),
            SymbolPin(number="9", tip=(0.0, -20.0), name="GND"),
        ],
    )
    # The number's owner is pin 2, whose name is GND → the role is GND → the
    # siblings are the other GND pins.
    assert role_siblings(profile, "VOUT") == (profile.pin("9"),), (
        "role_siblings matched pin 1 (by *name*) where the tree's ruler matches "
        "pin 2 (by *number*)"
    )
    # And the same profile read through the tree's own ruler:
    assert profile.pin("VOUT") is profile.pins[1], "`SymbolProfile.pin` is by number"


def test_a_token_no_pin_answers_is_still_empty():
    profile = SymbolProfile(
        symbol_ref="CRAFTED", pins=[SymbolPin(number="1", tip=(0.0, 0.0), name="A")]
    )
    assert role_siblings(profile, "") == ()
    assert role_siblings(profile, "NOPE") == ()
    assert role_siblings(profile, "A") == (), "the only pin has no siblings"


# --------------------------------------------------------------------------
# 洞5: the sort key, and the hash that rests on it
# --------------------------------------------------------------------------


def _doc(pins):
    return {"symbolRef": "HASHED-1", "body": [-10.0, -10.0, 10.0, 10.0], "pins": pins}


def test_equal_numbers_still_have_one_order():
    """``"1"`` and ``"01"`` are one number; the key now says which comes first."""
    assert _pin_sort_key("1") != _pin_sort_key("01"), "the keys used to collide"
    # Which one comes first is the text's business; that **one** of them always
    # does is the point — the old key left it to the file's emission order.
    assert sorted(["1", "01"], key=_pin_sort_key) == sorted(["01", "1"], key=_pin_sort_key)
    assert sorted(["10", "2", "A1"], key=_pin_sort_key) == ["2", "10", "A1"]


def _two_pin_doc(order):
    """One symbol — pin ``"1"`` at x=0, pin ``"01"`` at x=10 — in a given list order."""
    tips = {"1": [0.0, 0.0], "01": [10.0, 0.0]}
    return _doc([{"number": number, "tip": tips[number]} for number in order])


def test_the_hash_does_not_depend_on_the_order_a_file_emits_its_pins():
    """The promise `canonical_json` makes: one symbol, one geometry, one hash.

    049 measured the same symbol emitted in different orders by two container
    formats, so this is a real reading, not a contrived one.
    """
    first = SymbolProfile.from_dict(_two_pin_doc(("1", "01")))
    second = SymbolProfile.from_dict(_two_pin_doc(("01", "1")))
    assert sorted(first.pin_numbers()) == sorted(second.pin_numbers()), "the same two pins"
    assert first.geometry_hash() == second.geometry_hash()


def test_a_non_ascii_digit_pin_number_is_a_name_and_never_an_int():
    """`"²"` passes ``isdigit()`` and fails ``int()`` — a bare `ValueError` before.

    A pin number is a free string the file chooses, so the fallback is to order
    it as text; `SymbolProfileError` is the only error this module promises
    (`SymbolProfile.load`), and nothing may escape it.
    """
    assert _pin_sort_key("²") == (1, 0, "²")
    assert _pin_sort_key("①")[0] == 1
    profile = SymbolProfile.from_dict(_doc([{"number": "²", "tip": [0.0, 0.0]}]))
    digest = profile.geometry_hash()
    assert len(digest) == 64 and digest.isalnum(), "hashed, not crashed"


# --------------------------------------------------------------------------
# 洞6: the maps the parser gives, and the key space they are read in
# --------------------------------------------------------------------------


@dataclasses.dataclass
class _Parsed:
    """`parsers.schematic.SymbolDetail`'s shape — the fields `from_parsed_symbol` reads."""

    uuid: str
    offsets: dict
    title: str = ""
    pin_names: dict = dataclasses.field(default_factory=dict)
    pin_types: dict = dataclasses.field(default_factory=dict)
    body: tuple | None = None


def test_an_int_keyed_pin_map_keeps_its_names_types_and_roles():
    """The caller's key type must not decide whether the name survives."""
    ints = from_parsed_symbol(_Parsed(
        uuid="sym-int", offsets={1: (-30.0, 0.0), 2: (30.0, 0.0)},
        pin_names={1: "VIN", 2: "GND"}, pin_types={1: "Power", 2: "Power"},
    ))
    # The same value with the parser's own contract (`dict[str, …]`): the two
    # readings are one value, so they must give one profile.
    strings = from_parsed_symbol(_Parsed(
        uuid="sym-int", offsets={"1": (-30.0, 0.0), "2": (30.0, 0.0)},
        pin_names={"1": "VIN", "2": "GND"}, pin_types={"1": "Power", "2": "Power"},
    ))
    assert [(p.number, p.name, p.electrical_role, p.pin_type) for p in ints.pins] == [
        (p.number, p.name, p.electrical_role, p.pin_type) for p in strings.pins
    ]
    assert ints.pins[0].name == "VIN" and ints.pins[0].electrical_role == "VIN"
    assert ints.pins[0].pin_type == "Power"


def test_a_map_keyed_apart_from_the_offsets_says_so_in_notes():
    """"The parser did not give one" and "the name was lost" must not look alike."""
    profile = from_parsed_symbol(_Parsed(
        uuid="sym-mismatch", offsets={"1": (0.0, 0.0)}, pin_names={"P1": "VIN"},
    ))
    assert profile.pins[0].name == ""
    assert any("pin_names" in note for note in profile.notes), profile.notes
    # A symbol that genuinely states no names stays quiet about it.
    quiet = from_parsed_symbol(_Parsed(uuid="sym-none", offsets={"1": (0.0, 0.0)}))
    assert not any("pin_names" in note for note in quiet.notes), quiet.notes


def test_the_role_table_is_still_a_fallback_and_not_a_writer():
    """Nothing above made a name up: an unmapped name still yields no role."""
    profile = from_parsed_symbol(_Parsed(
        uuid="sym-x", offsets={"1": (0.0, 0.0)}, pin_names={"1": "IAMBIGUOUS"},
    ))
    assert profile.pins[0].name == "IAMBIGUOUS"
    assert profile.pins[0].electrical_role == "" and profile.pins[0].role_source == ""
    assert "IAMBIGUOUS" not in ROLE_BY_PIN_NAME
