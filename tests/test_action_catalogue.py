"""The action catalogue's own rules (006c, work item 1).

`connector/tests/contract-drift.test.mjs` checks that the catalogue and the
connector registry agree. This file checks the catalogue against *itself*: that
it has not quietly degraded in the ways a growing hand-written table does.

Both guards exist because the table is written by hand and read by two
programs. A name that drifts out of the naming domain, a duplicate entry, or a
`create` action missing the parameter its own gate demands are all invisible
until something fails on the machine.
"""

from __future__ import annotations

import re

import pytest

from boardwise.bridge.protocol import ACTIONS, ErrorCodes, describe_actions

#: `hello` / `ping` are answered by the daemon itself and predate the
#: `domain.verb` convention; everything else is lowercase, dot-separated.
RESERVED_NAMES = frozenset({"hello", "ping"})

#: Two segments (`sch.netlist`) or three (`lib.device.get`).
#:
#: 006c §1 words the rule as `^(…|[a-z]+\.[a-z_]+)$`, i.e. exactly two segments.
#: Measured 2026-09-16: **seven** existing entries are three-segment and predate
#: this task — `lib.<entity>.<verb>` (symbol/device/footprint get+search) and
#: `{sch,pcb}.doc.<verb>` (new/save). Rather than rename entries the task also
#: forbids touching, the rule is encoded as what the codebase actually observes
#: (lowercase dotted segments), and the *deliberate* three-segment families are
#: pinned below so a new one has to be a decision rather than an accident.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,2}$")

#: The three-segment families that exist on purpose.
THREE_SEGMENT_FAMILIES = (
    re.compile(r"^lib\.[a-z_]+\.(get|search)$"),
    re.compile(r"^(sch|pcb)\.doc\.(new|save)$"),
)

OWNERS = frozenset({"connector", "daemon"})
RISKS = frozenset({"read", "write", "create"})


def test_names_are_unique():
    """A duplicate entry is silently absorbed by the frozenset and the dict.

    Measured 2026-09-16: `lib.device.search` appeared **twice** in the table —
    a bad merge — and nothing noticed, because `ACTION_NAMES` deduplicates and
    `_ACTIONS_BY_NAME` keeps the last one. The rendered `--help` table showed it
    twice while every lookup agreed with itself.
    """
    names = [action.name for action in ACTIONS]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == [], f"duplicate catalogue entries: {duplicates}"


def test_names_stay_in_the_naming_domain():
    """Lowercase, dot-separated — two segments normally, three where declared."""
    wrong = []
    for action in ACTIONS:
        if action.name in RESERVED_NAMES:
            continue
        if not NAME_PATTERN.match(action.name):
            wrong.append(action.name)
    assert wrong == [], (
        f"action names outside the lowercase dotted domain: {wrong}. "
        "Reserved daemon names are hello/ping; a new one needs a reason."
    )


def test_three_segment_names_belong_to_a_declared_family():
    unexpected = []
    for action in ACTIONS:
        if action.name in RESERVED_NAMES or action.name.count(".") < 2:
            continue
        if not any(pattern.match(action.name) for pattern in THREE_SEGMENT_FAMILIES):
            unexpected.append(action.name)
    assert unexpected == [], (
        f"three-segment names outside a declared family: {unexpected}. Either use "
        "`domain.verb` or add the family here deliberately — the extra depth is "
        "what the catalogue's readers have to reason about."
    )


def test_the_parse_of_the_rule_actually_rejects_bad_names():
    # Positive control: the pattern above must be a rule, not a rubber stamp.
    for bad in ("Sch.netlist", "sch..netlist", "sch", "sch.", "sch.Netlist", "1sch.x", "sch.x.y.z"):
        assert NAME_PATTERN.match(bad) is None, f"{bad!r} should not be a valid action name"
    for good in ("sch.netlist", "lib.device.get", "pcb.doc.new", "doc.list", "sys.probe"):
        assert NAME_PATTERN.match(good) is not None, f"{good!r} should be valid"


def test_reserved_names_are_actually_reserved():
    # The exemption above must not become a hiding place for sloppy names.
    reserved = {action.name for action in ACTIONS if action.name in RESERVED_NAMES}
    assert reserved == set(RESERVED_NAMES), (
        f"expected exactly {sorted(RESERVED_NAMES)} to use the reserved form, got {sorted(reserved)}"
    )


def test_owner_is_one_of_the_two_sides():
    for action in ACTIONS:
        assert action.owner in OWNERS, f"{action.name}: owner={action.owner!r}"


def test_params_are_unique_within_an_action():
    for action in ACTIONS:
        duplicates = sorted({p for p in action.params if action.params.count(p) > 1})
        assert duplicates == [], f"{action.name}: duplicate params {duplicates}"


@pytest.mark.parametrize("obsolete", ["total", "reqId", "id"])
def test_params_do_not_include_transport_fields(obsolete):
    # The envelope carries these; a catalogue entry that names one is describing
    # the wire format instead of the action's own inputs.
    users = [action.name for action in ACTIONS if obsolete in action.params]
    assert users == []


def test_every_action_declares_a_risk():
    """The gate is only as good as this field's coverage, so it has no default."""
    for action in ACTIONS:
        assert action.risk in RISKS, f"{action.name}: risk={action.risk!r}"


def test_create_actions_declare_confirm():
    """A `create` action must expose the parameter its own gate demands.

    The daemon refuses a `create` action unless `params.confirm is True`. If a
    `create` entry forgot to declare `confirm`, the refusal could never be
    lifted by a caller and the action would be permanently dead — a gate that
    reads correct but blocks its own subject.
    """
    for action in ACTIONS:
        if action.risk != "create":
            continue
        assert "confirm" in action.params, (
            f"{action.name} is a create action but does not declare confirm — "
            "no caller could ever satisfy CONFIRMATION_REQUIRED"
        )


def test_only_document_producing_actions_are_create():
    """`create` means "produces a new document", and the list is short on purpose.

    Placement actions write into an existing page; they do not bring a new
    document into the project, so they are `write`. If this set grows, the
    question to answer is "does this bring a new document into existence?".
    """
    creators = {action.name for action in ACTIONS if action.risk == "create"}
    assert creators == {"sch.doc.new", "pcb.doc.new"}, (
        f"create actions are {sorted(creators)}; a new one needs the gate's "
        "reasoning re-checked, not just a label"
    )


def test_the_three_write_surfaces_are_where_they_belong():
    # Cheap tripwire for the labels that matter most: naming, attributes, save.
    assert {a.name for a in ACTIONS if a.risk == "write"} >= {
        "sch.place_component",
        "sch.place_wire",
        "sch.set_component_attribute",
        "doc.rename",
        "sch.doc.save",
    }


def test_read_actions_never_claim_to_write():
    for action in ACTIONS:
        if action.risk != "read":
            continue
        assert "confirm" not in action.params, (
            f"{action.name} is a read action but takes confirm — reads are not gated"
        )


def test_confirmation_required_is_a_real_error_code():
    assert ErrorCodes.CONFIRMATION_REQUIRED == "CONFIRMATION_REQUIRED"


def test_the_rendered_table_shows_every_action_and_its_risk():
    rendered = describe_actions()
    for action in ACTIONS:
        assert action.name in rendered, f"{action.name} is missing from --help"
        assert action.risk in rendered
    assert rendered.count("doc.list") == 1, "the rendered table has duplicates"
