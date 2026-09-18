"""Per-instance designators (008c item 6): the rule, in isolation.

The rule is short enough to state: an instance's designator is its template's
with the numeric part offset by `DESIGNATOR_STRIDE` per ordinal, ordinal 0 being
the template's own numbering. What the tests pin is the parts that are easy to
get subtly wrong — the shape that must be *refused*, the boundary the stride
implies, and the fact that "the same block" is decided by the template's
identity rather than by its name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.blocks import (
    DESIGNATOR_STRIDE,
    BlockError,
    BlockInstance,
    BoardSpec,
    derive_designator,
    designator_map,
    instance_ordinals,
    load_block_template,
    load_board_spec,
    repeated_templates,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"


def test_the_stride_is_the_only_thing_that_sets_the_gap():
    """One constant, so the limit (padding width) can be read off a number."""
    assert DESIGNATOR_STRIDE == 100
    assert derive_designator("R1", 1) == "R101"
    assert derive_designator("R1", 2) == "R201"
    assert derive_designator("R1", 0) == "R1"


def test_a_designator_keeps_its_letter_prefix():
    """`LED1` is one prefix, not `L` + `ED1` — the split is greedy."""
    assert derive_designator("LED1", 1) == "LED101"
    assert derive_designator("USB1", 1) == "USB101"
    assert derive_designator("X25", 1) == "X125"


def test_a_shape_nobody_has_seen_is_refused_not_mangled():
    for ref in ("X1A", "1", "R", "R-1", "R1/2"):
        with pytest.raises(BlockError, match="letter-plus-digit"):
            derive_designator(ref, 1)
        # Ordinal 0 never derives anything, so even a strange ref is fine there:
        # a single instance uses the template verbatim, whatever it says.
        assert derive_designator(ref, 0) == ref


def test_a_negative_ordinal_is_a_programming_error():
    with pytest.raises(BlockError, match="negative"):
        derive_designator("R1", -1)


def _spec_with(*blocks) -> BoardSpec:
    """A minimal spec around hand-built instances (no file, no template load)."""
    return BoardSpec(
        name="t", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=list(blocks), connections=[], params={}, sheet_attrs={},
        sheet_origin=(0.0, 0.0),
    )


def _instance(block_id: str, template_path: str, name: str) -> BlockInstance:
    raw = {
        "kind": "boardwise-block-template", "version": 1, "name": name,
        "description": "", "provenance": {"kind": "textbook", "source": "hand"},
        "origin_file": [0.0, 0.0], "bbox_file": [0.0, 0.0, 10.0, 10.0], "notes": [],
        "interface": [], "params": [],
        "symbols": {"s": {"offsets": {"1": [0.0, 0.0]}, "body": [0.0, 0.0, 5.0, 5.0]}},
        "components": [
            {"ref": "R1", "symbol": "s", "placement": {"x": 0.0, "y": 0.0},
             "device": {"lcsc": "C1"}, "params": {}, "pins": []}
        ],
        "geometry": {"wires": [], "flags": [], "labels": []},
    }
    from boardwise.core.blocks import template_from_json

    template = template_from_json(raw, where=name)
    return BlockInstance(
        id=block_id, template_path=template_path, template=template, at=(0.0, 0.0)
    )


def test_the_same_block_is_the_same_template_artifact_not_the_same_name():
    same_a = _instance("a", "/x/blk.json", "blk")
    same_b = _instance("b", "/x/blk.json", "blk")
    other = _instance("c", "/x/other.json", "blk")  # same *name*, other artifact
    spec = _spec_with(same_a, same_b, other)
    assert instance_ordinals(spec) == {"a": 0, "b": 1, "c": 0}
    assert repeated_templates(spec) == {"/x/blk.json": ["a", "b"]}
    # The first instance keeps the refs, the second is offset, the unrelated one
    # with the same display name is not.
    refs = designator_map(spec)
    assert refs["a"]["R1"] == "R1"
    assert refs["b"]["R1"] == "R101"
    assert refs["c"]["R1"] == "R1"


def test_a_hand_built_instance_without_a_path_keys_on_the_template_name():
    """Documented fallback, because `at`/path are what a loaded spec always has."""
    first = _instance("a", "", "blk")
    second = _instance("b", "", "blk")
    spec = _spec_with(first, second)
    assert instance_ordinals(spec) == {"a": 0, "b": 1}
    assert designator_map(spec)["b"]["R1"] == "R101"


def test_duplicate_block_ids_are_refused_by_the_ordinal_helper():
    spec = _spec_with(_instance("a", "/x/blk.json", "blk"), _instance("a", "/y/other.json", "o"))
    with pytest.raises(BlockError, match="share the id"):
        instance_ordinals(spec)


def test_a_one_instance_spec_derives_nothing():
    """The strongest statement of backward compatibility: the committed CH340
    spec's map is the identity map, so 008a's output is unchanged."""
    spec = load_board_spec(SPEC)
    refs = designator_map(spec)
    assert set(refs) == {block.id for block in spec.blocks}
    for block_id, table in refs.items():
        assert table == {ref: ref for ref in table}, block_id
    assert repeated_templates(spec) == {}
    assert set(instance_ordinals(spec).values()) == {0}


def test_the_stride_is_a_documented_limit_not_a_discovery():
    """`R100` in instance 0 and `R1`+stride in instance 1 land on the same name —
    which is exactly why `_check_designators` still refuses it."""
    assert derive_designator("R1", 1) == derive_designator("R101", 0) == "R101"


def test_the_real_templates_refs_are_all_derivable():
    """A template whose refs cannot be derived would only fail at assembly time."""
    for path in sorted((ROOT / "blocklib" / "blocks").glob("*.json")):
        template = load_block_template(path)
        for component in template.components:
            assert derive_designator(component.ref, 1).startswith(
                component.ref.rstrip("0123456789")
            ), (path.name, component.ref)
