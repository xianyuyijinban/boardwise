"""Task 182: the high-speed scaffold — data layer, diff-pair engine, one inventory rule.

182's subject is an *absence*: the review engine could read a board's copper but
not one word of what the board declares about its nets, so the whole high-speed
family (length matching, splits, impedance — 0.6.0) had no place to stand. This
file holds the three layers of what 182 added to the testable contract:

* **the data layer** — the EasyEDA ``NET`` record's declaration
  (``differentialName`` / ``isPositiveNet``) into
  :class:`~boardwise.core.geometry.NetMeta`, the two dielectric columns of a
  ``LAYER_PHYS`` record (Er / Df) into
  :class:`~boardwise.core.geometry.StackupEntry`, and KiCad's ``net_settings``
  and ``(setup (stackup …))`` into the same two;
* **the engine** — :func:`~boardwise.core.highspeed.match_dp_suffix` (a port of
  KiCad's own ``DRC_ENGINE::MatchDpSuffix``) and
  :func:`~boardwise.core.highspeed.identify_diff_pairs` (declaration first, then
  the heuristic over the board's net table);
* **the rule** — ``pcb-hs-diffpair-inventory`` in ``BUILTIN_PCB_RULES``, one
  ``INFO`` per pair through :func:`~boardwise.engines.pcbreview.run_pcb_review`,
  and **zero** findings when there is no pair.

Every number below was read off the fixture it names. Two of them are worth
pointing out before they are read, because both say 「do not normalise this」:

* ``isPositiveNet`` is ``true`` on ``D-`` and ``CAN_L`` of 毕设FOC 1.0.0, while
  the *same* project's 2026-09-17 backup declares ``D+`` positive — the flag is
  the file's statement and 182 carries it verbatim;
* KiCad spells the dielectric columns ``epsilon_r`` / ``loss_tangent``, not
  ``permittivity`` / ``lossTangent`` as the EasyEDA side does, and a KiCad stackup
  entry has no boardwise layer id to carry — the trade-off is
  :func:`boardwise.parsers.kicad._read_stackup`'s docstring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.geometry import BoardGeometry, NetGeometry, NetMeta
from boardwise.core.highspeed import DiffPair, identify_diff_pairs, match_dp_suffix
from boardwise.core.measure import read_stackup
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.parsers.epru import PCB_DOC_TYPE, extract_board, load_epro2_source, parse_epro2
from boardwise.parsers.kicad import (
    KicadFormatError,
    NetSettings,
    load_kicad,
    read_kicad_board,
    read_project_net_settings,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.highspeed import DiffPairInventory

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_SEP = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"
KICAD_HS_PCB = FIXTURES / "kicad_hs" / "kicad_hs.kicad_pcb"
KICAD_HS_PRO = FIXTURES / "kicad_hs" / "kicad_hs.kicad_pro"
KICAD_MIN_PCB = FIXTURES / "kicad_min" / "kicad_min.kicad_pcb"

RULE_ID = "pcb-hs-diffpair-inventory"

MM = 1.0 / 0.0254  # mm → mil, the conversion the reader applies


def _rows(path: Path) -> list:
    """The inventory rows a full ``run_pcb_review`` produces for one board file."""
    findings, _section = run_pcb_review(path)
    return [row for row in findings if row.rule_id == RULE_ID]


def _board(names, meta=()) -> BoardGeometry:
    """A hand-built board: exactly the net table and the declarations given."""
    board = BoardGeometry(source="synthetic")
    board.nets = {name: NetGeometry(name=name) for name in names}
    board.net_meta = {item.name: item for item in meta}
    return board


# ---------------------------------------------------------------------------
# 1. the EasyEDA NET record → NetMeta
# ---------------------------------------------------------------------------


def test_foc_100_net_records_declare_dp1_and_dp2():
    """毕设FOC 1.0.0's ``PCB1``: ``D+/D-`` is ``DP1``, ``CAN_H/CAN_L`` is ``DP2``.

    The two declarations are the only ones on the board (measured: 115 ``NET``
    records, four of them carrying a ``differentialName``).
    """
    board = parse_epro2(FOC_100)

    assert board.net_meta["D+"].diff_pair == "DP1"
    assert board.net_meta["D-"].diff_pair == "DP1"
    assert board.net_meta["CAN_H"].diff_pair == "DP2"
    assert board.net_meta["CAN_L"].diff_pair == "DP2"
    declared = {name for name, meta in board.net_meta.items() if meta.diff_pair}
    assert declared == {"D+", "D-", "CAN_H", "CAN_L"}
    assert board.net_meta["D+"].equal_length_group is None


def test_the_polarity_flag_is_the_files_statement_and_is_carried_verbatim():
    """``isPositiveNet`` says ``D-``, not ``D+``, and the older backup says the opposite.

    This is the reason 182 carries the flag instead of deriving polarity from the
    net name: measured on the fixtures, the *same* ``D+/D-`` pair is declared
    ``D+`` positive in 毕设FOC's 2026-09-17 backup (its 4-layer ``PCB`` document, the
    second one in the stream) and ``D-`` positive in the 1.0.0 backup a month
    later. Neither is 「wrong」 as far as this reader can tell, so it reports
    what the file says.
    """
    board = parse_epro2(FOC_100)
    assert board.net_meta["D-"].diff_positive is True
    assert board.net_meta["D+"].diff_positive is False
    assert board.net_meta["CAN_L"].diff_positive is True
    assert board.net_meta["CAN_H"].diff_positive is False

    # A second board, a third statement: ROBOT's single PCB document writes the
    # same way as 1.0.0 (D- positive), and 智能药箱 too.
    robot = parse_epro2(ROBOT)
    assert robot.net_meta["D-"].diff_positive is True
    assert robot.net_meta["D+"].diff_positive is False

    source = load_epro2_source(FOC_SEP)
    documents = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE]
    older = [
        extract_board(document, source.footprints(), source.stats) for document in documents
    ]
    declaring = [
        board for board in older if any(meta.diff_pair == "DP1" for meta in board.net_meta.values())
    ]
    assert len(declaring) == 1, "exactly one of the three PCB documents declares DP1"
    assert declaring[0].net_meta["D+"].diff_positive is True
    assert declaring[0].net_meta["D-"].diff_positive is False


def test_the_net_table_is_what_net_meta_covers_and_an_empty_body_declares_nothing():
    """115 ``NET`` records, 27 with an empty body, one with an empty name.

    The rows are the records that state something: a body-less record declares
    nothing, so its net has no entry — the same 「absent, not empty」 the rest of
    the parser follows. Measured: 87 entries, and they are exactly the board's
    net table (``len(board.nets) == 87``).
    """
    board = parse_epro2(FOC_100)

    assert len(board.net_meta) == 87
    assert len(board.nets) == 87
    assert set(board.net_meta) == set(board.nets)
    assert "VSENA" not in board.net_meta, "VSENA's NET record carries no body"
    assert "" not in board.net_meta, "the no-net row is not a net"
    # A net that declares no pair still has a row: it declares that it is not
    # positive, which is a statement and not an absence.
    assert board.net_meta["GND"].diff_pair is None
    assert board.net_meta["GND"].diff_positive is False


# ---------------------------------------------------------------------------
# 2. the two dielectric columns
# ---------------------------------------------------------------------------


def test_the_fixture_that_writes_zero_permittivity_reads_none():
    """毕设FOC 1.0.0 writes ``permittivity: 0`` on **all** 13 ``LAYER_PHYS`` records.

    A zero is 未声明, not a value: every entry of that board's stackup reads
    ``None`` for both columns, and the entry that *is* a dielectric (361, the
    ``7628 RC49% 8.6mil`` core) reads ``None`` too.
    """
    board = parse_epro2(FOC_100)

    assert len(board.stackup) == 13
    assert {entry.permittivity for entry in board.stackup} == {None}
    assert {entry.loss_tangent for entry in board.stackup} == {None}
    core = [entry for entry in board.stackup if entry.layer_id == 361]
    assert len(core) == 1 and core[0].material == "7628 RC49% 8.6mil"


def test_llc_reads_both_columns_off_the_same_records():
    """llc's stackup: the substrate has an Er, the mask layers have Er *and* Df.

    Measured — ``LAYER_PHYS`` 361 (``FR4``, the core) carries ``permittivity 4.5``
    and ``lossTangent 0``; layers 5 and 6 (the two solder masks) carry
    ``3.3`` / ``0.02``. The core's ``0`` reads ``None`` (未声明), the mask's
    ``0.02`` reads ``0.02``: the rule is about the value, not the layer.
    """
    board = parse_epro2(LLC)
    by_id = {entry.layer_id: entry for entry in board.stackup}

    assert by_id[361].material == "FR4"
    assert by_id[361].permittivity == pytest.approx(4.5)
    assert by_id[361].loss_tangent is None, "the file writes 0 here — 未声明"
    assert by_id[5].permittivity == pytest.approx(3.3)
    assert by_id[5].loss_tangent == pytest.approx(0.02)
    assert by_id[6].permittivity == pytest.approx(3.3)
    assert by_id[1].permittivity is None, "a copper layer declares no Er"
    # At least one entry is a real dielectric: Er read and > 1.
    assert any(
        entry.permittivity is not None and entry.permittivity > 1
        for entry in board.stackup
    )


def test_the_two_new_fields_do_not_move_the_stackup_memo():
    """``read_stackup``'s perf-02A memo keys on containers and lengths, not on entries.

    The memo's fingerprint is ``(container identity, length)`` over ``layers`` /
    ``stackup`` / ``pads`` / ``tracks`` / ``pours``, so adding fields to
    :class:`StackupEntry` cannot invalidate it — and a caller that edits one of
    the new columns in place gets the same cached answer, exactly as it did
    before 182 for ``thickness``. Documented in ``BoardGeometry._stackup_cache``;
    asserted here because a data-model change must not silently move a cache.
    """
    board = parse_epro2(FOC_100)
    first = read_stackup(board)

    board.stackup[0].permittivity = 9.9
    board.stackup[0].loss_tangent = 0.5

    assert read_stackup(board) is first, "the memo still answers, unchanged"
    assert first.copper_count == 4


# ---------------------------------------------------------------------------
# 3. KiCad's MatchDpSuffix, ported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("D+", ("D", "D-", 1)),
        ("D-", ("D", "D+", -1)),
        ("USB_P", ("USB_", "USB_N", 1)),
        ("USB_N", ("USB_", "USB_P", -1)),
        ("DDR_DQ3P", ("DDR_DQ3", "DDR_DQ3N", 1)),
        ("DDR_DQ3N", ("DDR_DQ3", "DDR_DQ3P", -1)),
        # A1_P / A1_N: the `_` before the polarity character stays in the base
        # (KiCad only strips what it skipped *after* the polarity character).
        ("A1_P", ("A1_", "A1_N", 1)),
        ("A1_N", ("A1_", "A1_P", -1)),
        # FOO_P3: the tail after the polarity character is kept and re-attached.
        ("FOO_P3", ("FOO_", "FOO_N3", 1)),
        # A name that is no polarity suffix at all.
        ("GND", None),
        ("SDA", None),
        ("MOSI", None),
        ("12_3", None),
        # Lower case is not a polarity character: KiCad compares 'N'/'P' only.
        ("DDR_DQ3p", None),
        # Leading '_' is skipped on the way to the polarity character.
        ("_P", ("_", "_N", 1)),
        # A lone polarity character: KiCad's base is empty and the complement is
        # the single character.
        ("P", ("", "N", 1)),
        ("N", ("", "P", -1)),
    ],
)
def test_match_dp_suffix_is_kicads_own_reading(name, expected):
    """Table-driven: KiCad's ``DRC_ENGINE::MatchDpSuffix``, character for character."""
    assert match_dp_suffix(name) == expected


def test_match_dp_suffix_does_not_depend_on_the_net_table():
    """The port is a pure function of the name — the existence test is the caller's."""
    assert match_dp_suffix("FOO_P") == ("FOO_", "FOO_N", 1)
    assert identify_diff_pairs(_board(["FOO_P"])) == []


# ---------------------------------------------------------------------------
# 4. identify_diff_pairs: declaration first, then the heuristic
# ---------------------------------------------------------------------------


def test_a_declared_group_wins_over_the_heuristic_on_the_same_nets():
    board = _board(
        ["D+", "D-"],
        [
            NetMeta(name="D+", diff_pair="DP7", diff_positive=True),
            NetMeta(name="D-", diff_pair="DP7", diff_positive=False),
        ],
    )
    pairs = identify_diff_pairs(board)

    assert pairs == [DiffPair(group="DP7", positive="D+", negative="D-", source="declared")]


def test_the_declared_polarity_decides_which_net_is_positive():
    """``diff_positive`` picks the roles — the net names are not consulted."""
    board = _board(
        ["D+", "D-"],
        [
            NetMeta(name="D+", diff_pair="DP7", diff_positive=False),
            NetMeta(name="D-", diff_pair="DP7", diff_positive=True),
        ],
    )
    assert identify_diff_pairs(board) == [
        DiffPair(group="DP7", positive="D-", negative="D+", source="declared")
    ]


@pytest.mark.parametrize(
    "metas",
    [
        pytest.param([NetMeta(name="A_P", diff_pair="DPX", diff_positive=True)], id="one-net"),
        pytest.param(
            [
                NetMeta(name="A_P", diff_pair="DPX", diff_positive=True),
                NetMeta(name="A_N", diff_pair="DPX", diff_positive=False),
                NetMeta(name="A_G", diff_pair="DPX", diff_positive=False),
            ],
            id="three-nets",
        ),
        pytest.param(
            [
                NetMeta(name="A_P", diff_pair="DPX", diff_positive=True),
                NetMeta(name="A_N", diff_pair="DPX", diff_positive=True),
            ],
            id="both-positive",
        ),
        pytest.param(
            [
                NetMeta(name="A_P", diff_pair="DPX"),
                NetMeta(name="A_N", diff_pair="DPX"),
            ],
            id="nobody-positive",
        ),
    ],
)
def test_a_declaration_that_is_not_a_pair_is_not_reported_and_its_nets_are_not_re_paired(metas):
    """1 net, 3 nets, two positives, none positive: no row, and no heuristic row either.

    0.6.0 owns 「声明残缺」 as a finding of its own (182's task book says so in
    as many words). What this test pins is the second half: the nets of a broken
    declaration are still **declared**, so the heuristic does not quietly pair
    ``A_P`` with ``A_N`` behind its back.
    """
    board = _board([meta.name for meta in metas] + ["A_G"], metas)

    assert identify_diff_pairs(board) == []


def test_the_heuristic_pairs_two_names_that_really_exist_on_the_board():
    """Both halves must be in the net table — a lone ``FOO_P`` is not a pair."""
    pairs = identify_diff_pairs(_board(["D+", "D-", "USB_P", "USB_N", "GND"]))

    assert pairs == [
        DiffPair(group="D", positive="D+", negative="D-", source="heuristic"),
        DiffPair(group="USB_", positive="USB_P", negative="USB_N", source="heuristic"),
    ]


def test_a_net_is_paired_at_most_once_and_the_result_is_ordered():
    """Declared pairs first (group order), then heuristic ones (base-name order)."""
    board = _board(
        ["A_P", "A_N", "B_N", "B_P", "C+", "C-"],
        [
            NetMeta(name="C+", diff_pair="DP1", diff_positive=True),
            NetMeta(name="C-", diff_pair="DP1", diff_positive=False),
        ],
    )
    pairs = identify_diff_pairs(board)

    assert [pair.source for pair in pairs] == ["declared", "heuristic", "heuristic"]
    assert [pair.group for pair in pairs] == ["DP1", "A_", "B_"]
    assert [pair.positive for pair in pairs] == ["C+", "A_P", "B_P"]
    # C+/C- were declared, so the heuristic did not report them a second time.
    assert sum(1 for pair in pairs if {pair.positive, pair.negative} & {"C+", "C-"}) == 1
    assert sum(1 for pair in pairs if len({pair.positive, pair.negative}) == 2) == 3


def test_an_empty_board_has_no_pairs():
    assert identify_diff_pairs(BoardGeometry()) == []


def test_a_kicad_netclass_is_not_a_declared_pair():
    """KiCad stores no per-net differential field: its pairs come from the names.

    The fixture assigns ``CAN_H``/``CAN_L`` to one netclass and ``USB_D+`` /
    ``USB_D-`` to another; only the USB pair is reported, because a netclass says
    which two nets *share routing rules*, not which two are a pair.
    """
    board = read_kicad_board(KICAD_HS_PCB)

    assert board.net_meta["CAN_H"].net_class == "HS_CAN"
    assert board.net_meta["CAN_H"].diff_pair is None
    assert identify_diff_pairs(board) == [
        DiffPair(group="USB_D", positive="USB_D+", negative="USB_D-", source="heuristic")
    ]


# ---------------------------------------------------------------------------
# 5. KiCad: the project's net_settings
# ---------------------------------------------------------------------------


def test_the_project_net_settings_are_read_with_units_converted():
    """``classes[]`` names and both diff-pair sizes, mm → mil, plus the two tables."""
    settings = read_project_net_settings(KICAD_HS_PRO)

    assert isinstance(settings, NetSettings)
    assert sorted(settings.classes) == ["Default", "HS_CAN", "USB2"]
    assert settings.classes["HS_CAN"].diff_pair_width == pytest.approx(0.2 * MM)
    assert settings.classes["HS_CAN"].diff_pair_gap == pytest.approx(0.25 * MM)
    assert settings.classes["Default"].diff_pair_width == pytest.approx(0.1524 * MM)
    assert settings.assignments == {"CAN_H": "HS_CAN", "/CAN_L": "HS_CAN"}
    assert settings.patterns == [("GND", "Default"), ("USB_*", "USB2")]


def test_the_netclass_of_a_net_comes_from_the_assignment_first_then_the_patterns():
    settings = read_project_net_settings(KICAD_HS_PRO)

    # An assignment, written both as a bare name and in KiCad's path form.
    assert settings.netclass_of("CAN_H") == "HS_CAN"
    assert settings.netclass_of("CAN_L") == "HS_CAN"
    # A pattern, read with fnmatchcase so Windows and Linux agree.
    assert settings.netclass_of("GND") == "Default"
    assert settings.netclass_of("USB_D+") == "USB2"
    # A net in no class.
    assert settings.netclass_of("SENSE") is None


def test_the_netclass_lands_in_net_meta_with_the_declared_sizes():
    """The board read off the ``.kicad_pcb`` picks its sibling project's classes up."""
    board = read_kicad_board(KICAD_HS_PCB)

    hs = board.net_meta["CAN_H"]
    assert (hs.net_class, hs.diff_pair) == ("HS_CAN", None)
    assert hs.declared_diff_width == pytest.approx(0.2 * MM)
    assert hs.declared_diff_gap == pytest.approx(0.25 * MM)
    assert board.net_meta["CAN_L"].net_class == "HS_CAN", "the path form resolves too"
    assert board.net_meta["GND"].net_class == "Default"
    assert board.net_meta["GND"].declared_diff_width == pytest.approx(6.0)
    assert board.net_meta["USB_D+"].net_class == "USB2"
    # A net whose class nothing declares ... the fixture's SENSE net is in no
    # class at all, so it has no row (the absent-not-empty rule).
    assert "SENSE" in board.nets and "SENSE" not in board.net_meta


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("not json at all", id="not-json"),
        pytest.param([1, 2, 3], id="not-an-object"),
        pytest.param({"meta": {"version": 3}}, id="no-net-settings"),
        pytest.param(
            {"net_settings": {"classes": "Default", "netclass_assignments": [], "netclass_patterns": {}}},
            id="wrong-types",
        ),
        pytest.param(
            {"net_settings": {"classes": [{"diff_pair_width": 0.2}, "HS"], "netclass_patterns": [{}]}},
            id="rows-without-keys",
        ),
    ],
)
def test_a_project_file_this_reader_cannot_use_yields_nothing_rather_than_raising(tmp_path, body):
    """宽容优先: every unusable shape answers 「no net metadata」, never an exception.

    The empty answer is the *same* one a missing file gives, and that is the
    point: the netclass columns are extra columns, and a review must not fail
    over a settings block.
    """
    path = tmp_path / "broken.kicad_pro"
    path.write_text(json.dumps(body) if not isinstance(body, str) else body, encoding="utf-8")

    settings = read_project_net_settings(path)
    assert settings is None or settings == NetSettings()


def test_a_missing_project_file_is_the_same_absence(tmp_path):
    assert read_project_net_settings(tmp_path / "nowhere.kicad_pro") is None


def test_a_broken_input_project_file_is_still_refused_by_name(tmp_path):
    """**Input** vs sidecar: a ``.kicad_pro`` handed to the loader is validated."""
    path = tmp_path / "broken.kicad_pro"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(KicadFormatError):
        load_kicad(path, view="pcb")


def test_the_project_less_kicad_fixture_reads_no_net_meta():
    """``kicad_min`` has no ``net_settings`` — no rows, and no crash."""
    board = read_kicad_board(KICAD_MIN_PCB)

    assert board.net_meta == {}
    assert identify_diff_pairs(board) == []


# ---------------------------------------------------------------------------
# 6. KiCad: the stackup
# ---------------------------------------------------------------------------


def test_the_kicad_stackup_is_read_with_its_own_key_names():
    """``epsilon_r`` / ``loss_tangent``, thickness mm → mil, position as z_index.

    Measured on the synthetic fixture, whose numbers were taken from KiCad's own
    stackup shape: 8 entries, four of them non-copper, and the two dielectrics
    read Er 4.5 / 4.3 with Df 0.02 / (0 → ``None``).
    """
    board = read_kicad_board(KICAD_HS_PCB)
    by_z = {entry.z_index: entry for entry in board.stackup}

    assert len(board.stackup) == 8
    assert [entry.z_index for entry in board.stackup] == list(range(8))
    # Copper entries carry the same boardwise ids every pad and track gets.
    assert {entry.layer_id for entry in board.stackup} == {1, 15, 2, -1, -2, -4, -6, -8}
    assert by_z[2].layer_id == 1, "F.Cu"
    assert by_z[4].layer_id == 15, "In1.Cu"
    assert by_z[6].layer_id == 2, "B.Cu"
    prepreg = by_z[3]
    assert (prepreg.material, prepreg.permittivity, prepreg.loss_tangent) == (
        "FR4",
        pytest.approx(4.5),
        pytest.approx(0.02),
    )
    assert prepreg.thickness == pytest.approx(0.2104 * MM)
    core = by_z[5]
    assert core.permittivity == pytest.approx(4.3)
    assert core.loss_tangent is None, "the fixture writes 0 — 未声明"
    assert core.thickness == pytest.approx(1.51 * MM)
    # A non-dielectric entry states no dielectric columns at all.
    assert (by_z[1].permittivity, by_z[1].loss_tangent) == (None, None)
    assert by_z[1].thickness == pytest.approx(0.01 * MM), "the top solder mask"


def test_the_non_copper_stackup_entries_are_marked_and_never_read_as_copper():
    """A kicad stackup entry with no boardwise id gets a negative one.

    ``read_stackup`` treats an entry as copper only through ``board.layers``, so
    a dielectric can never be counted as one — asserted here rather than assumed,
    because 0.6.0's impedance work will read these columns.
    """
    board = read_kicad_board(KICAD_HS_PCB)

    assert read_stackup(board).copper_count == 3
    dielectric = [entry for entry in board.stackup if entry.layer_id < 0]
    assert dielectric, "the fixture has dielectric / mask entries"
    assert all(entry.layer_id not in board.layers for entry in dielectric)


def test_a_kicad_board_without_a_stackup_reads_an_empty_one():
    board = read_kicad_board(KICAD_MIN_PCB)

    assert board.stackup == []
    assert read_stackup(board).copper_count == 2, "the LAYER table fallback still works"


# ---------------------------------------------------------------------------
# 7. the rule, end to end
# ---------------------------------------------------------------------------


def test_the_inventory_rule_is_registered_with_its_declared_identity():
    rules = {rule.id: rule for rule in BUILTIN_PCB_RULES}

    assert RULE_ID in rules
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    # 182 was the last row when it landed; **200B appended after it** (the first
    # judgement of the family, reading this inventory), **200C1 appended after
    # 200B** (the family's via-side question) and **200C2 appended its two pair
    # rules after 200C1**, so the pin is that the inventory comes immediately
    # *before* those four rather than last.
    assert ids[-5:] == [
        RULE_ID,
        "pcb-hs-cross-split",
        "pcb-hs-via-ground-companion",
        "pcb-hs-diffpair-skew",
        "pcb-hs-diffpair-via-parity",
    ]
    rule = rules[RULE_ID]
    assert isinstance(rule, DiffPairInventory)
    assert rule.level == "L1-pcb-geometry"
    assert rule.source == "boardwise highspeed scaffold（182）"


def test_foc_100_reports_its_two_declared_pairs_and_nothing_else():
    """The whole chain on one real board: two rows, both ``INFO``, both declared."""
    rows = _rows(FOC_100)

    assert len(rows) == 2
    assert all(row.severity == "INFO" for row in rows)
    assert all(row.level == "L1-pcb-geometry" for row in rows)
    assert {row.board for row in rows} == {"PCB1"}
    by_group = {row.evidence[0].split(":")[0]: row for row in rows}
    assert sorted(by_group) == ["DP1", "DP2"]
    assert by_group["DP1"].target.net_refs == ["D-", "D+"]
    assert by_group["DP2"].target.net_refs == ["CAN_L", "CAN_H"]
    text = "\n".join(f"{row.message}\n{' | '.join(row.evidence)}" for row in rows)
    for fragment in ("DP1", "DP2", "D+", "D-", "CAN_H", "CAN_L", "编辑器声明", "declared"):
        assert fragment in text, fragment


def test_the_kicad_fixture_reports_its_heuristic_pair_through_the_runner():
    """The same rule, the other host: one row, ``heuristic``, from the net names."""
    rows = _rows(KICAD_HS_PCB)

    assert len(rows) == 1
    row = rows[0]
    assert row.board == "kicad_hs"
    assert row.target.net_refs == ["USB_D+", "USB_D-"]
    assert "heuristic" in row.evidence[0]
    assert "网名启发式" in row.message
    assert "MatchDpSuffix" in "\n".join(row.evidence)


def test_a_board_with_no_pair_gets_no_row_at_all_and_still_runs_the_check():
    findings, section = run_pcb_review(KICAD_MIN_PCB)

    assert [row for row in findings if row.rule_id == RULE_ID] == []
    board_entry = section["boards"][0]
    assert RULE_ID in board_entry["checksRun"], "the rule ran; it found nothing"
    assert section["rules_errored"] == []


def test_an_empty_board_produces_zero_findings_without_raising():
    findings = DiffPairInventory().check(PcbReviewContext(board=BoardGeometry()))

    assert findings == []


def test_a_synthetic_pair_produces_one_row_carrying_both_nets():
    board = _board(
        ["HS_P", "HS_N"],
        [
            NetMeta(name="HS_P", diff_pair="DP9", diff_positive=True),
            NetMeta(name="HS_N", diff_pair="DP9", diff_positive=False),
        ],
    )
    findings = DiffPairInventory().check(PcbReviewContext(board=board, board_title="synthetic"))

    assert len(findings) == 1
    row = findings[0]
    assert row.severity == "INFO" and row.rule_id == RULE_ID
    assert row.target.net_refs == ["HS_P", "HS_N"]
    assert "DP9" in row.message and "HS_P" in row.message and "HS_N" in row.message


def test_a_declared_pair_whose_nets_carry_no_copper_says_so():
    """A declaration can name a net the board has no copper for; the row discloses it."""
    board = _board(
        ["D+", "D-"],
        [
            NetMeta(name="D+", diff_pair="DP1", diff_positive=True),
            NetMeta(name="D-", diff_pair="DP1", diff_positive=False),
        ],
    )
    board.nets = {"D+": NetGeometry(name="D+")}

    row = DiffPairInventory().check(PcbReviewContext(board=board))[0]
    assert any("没有铜" in item for item in row.evidence)
