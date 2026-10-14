"""The pins for C7's test-side PCB-review cache (``tests/_pcb_cache.py``).

That module is the one thing in the suite that **replaces a production
function** — ``boardwise.engines.pcbreview.run_pcb_review`` becomes the caching
wrapper, and every PCB test file then reaches the cache through its own
top-level import. A mechanism of that shape needs its own witnesses, and these
are them: not "the cache is faster" (that is ``outputs/perf02B/``) but "the
cache answers with what the real runner would have, and never with something
else's answer".

Every test here drives a **recording stand-in for the real runner** (the
wrapper calls whichever function sits in ``_pcb_cache._REAL``), over a board
file of four bytes in ``tmp_path``. No fixture is parsed, so the whole file
costs milliseconds, and what is measured is the key — which is the only thing
that can be wrong.
"""

from __future__ import annotations

import os

import pytest

import _pcb_cache
from boardwise.engines import pcbreview


class _Recorder:
    """A stand-in for the real runner: counts calls, returns a marked reading."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, source_path, model=None, intent=None, modules=None, *, rules=None):
        self.calls.append((str(source_path), model, intent, modules, rules))
        return (
            [{"call": len(self.calls), "model": model, "board": str(source_path)}],
            {"available": True, "call": len(self.calls)},
        )


@pytest.fixture(autouse=True)
def _cold_cache():
    """Each test starts with an empty table: a leak between tests *is* a bug.

    ``BOARDWISE_NO_PCB_CACHE=1`` switches the whole mechanism off for a session
    (that switch is what the before/after timing in ``outputs/perf02B/`` runs
    on), and with it off there is nothing here to pin — so this module **skips**
    rather than failing the arm it is not measuring. It is not a "flaky test"
    exit: the skip says exactly which switch did it, and the arm that has the
    cache installed runs every one of these.
    """
    if os.environ.get("BOARDWISE_NO_PCB_CACHE"):
        pytest.skip("BOARDWISE_NO_PCB_CACHE=1: the runner cache is switched off")
    _pcb_cache.clear()
    _pcb_cache.reset_stats()
    yield
    _pcb_cache.clear()


@pytest.fixture
def board(tmp_path):
    """A four-byte "board", enough for the key: what is cached is the runner's
    answer, and the runner is a stand-in here."""
    path = tmp_path / "board.epro2"
    path.write_bytes(b"board")
    return path


@pytest.fixture
def recorder(monkeypatch):
    """Swaps the real runner underneath the wrapper for the recording one."""
    stand_in = _Recorder()
    monkeypatch.setattr(_pcb_cache, "_REAL", stand_in)
    return stand_in


def test_the_installed_runner_is_the_cache_and_the_real_one_is_still_reachable():
    """The installation is the mechanism, so it is asserted rather than assumed.

    ``functools.wraps`` means the name a caller imports is still spelled
    ``run_pcb_review`` and still carries the production docstring and signature
    (``__wrapped__``), while the module attribute is the caching wrapper.
    """
    import inspect

    assert pcbreview.run_pcb_review is _pcb_cache._CACHED
    assert pcbreview.run_pcb_review.__name__ == "run_pcb_review"
    assert pcbreview.run_pcb_review.__wrapped__ is _pcb_cache._REAL
    assert inspect.signature(pcbreview.run_pcb_review) == inspect.signature(
        _pcb_cache._REAL
    )


def test_the_second_call_for_the_same_board_and_model_is_a_hit(recorder, board):
    """One board, one model spelling, two calls: the runner runs once."""
    first = pcbreview.run_pcb_review(board, model={"u1": 1})
    second = pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 1, "the second call went to the runner"
    assert first == second
    assert (_pcb_cache.stats["hits"], _pcb_cache.stats["misses"]) == (1, 1)


def test_an_equal_but_fresh_model_is_the_same_question(recorder, board):
    """By **value**: ``build_project_model(path)`` is rebuilt per call by 131d/131e.

    Identity alone would miss on every one of those files — the measured case
    that makes this cache worth having — so an equal model must hit, and a
    *different* model must not.
    """
    pcbreview.run_pcb_review(board, model={"u1": 1})
    pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 1
    pcbreview.run_pcb_review(board, model={"u1": 2})
    assert len(recorder.calls) == 2, "a different model was served from the cache"


def test_a_missing_model_is_not_an_empty_model(recorder, board):
    """``None`` (no schematic view) and an empty model are different questions.

    126a asks the first and 133c/133d ask the second about the same files; a
    key that treats them as equal would hand one of them the other's reading.
    """
    pcbreview.run_pcb_review(board)
    pcbreview.run_pcb_review(board, model={})
    pcbreview.run_pcb_review(board, model=None, intent="contract")
    assert len(recorder.calls) == 3


def test_a_caller_gets_its_own_copy_of_the_reading(recorder, board):
    """The read-only contract, pinned by writing to what came back.

    The suite hands these findings to tests that filter, index and assert over
    them; one of them mutating a finding it was given must not change what the
    next test in that worker reads. Splitting or sorting a *copy* is what makes
    sharing the runner's one reading safe.

    **Both halves are written to**, and that is the measured point rather than
    thoroughness for its own sake: tampering with the first (uncached) answer
    alone does not catch a cache that hands the *cached* object out on the hit
    path — the first answer was already a private object, so the corruption
    never reaches the table (this test passed against exactly that mutation
    until the second half was added, ``outputs/perf02B/mut_M2.txt``).
    """
    findings, section = pcbreview.run_pcb_review(board, model={"u1": 1})
    findings[0]["tampered"] = True
    findings.append("not a finding")
    section["available"] = False

    again, again_section = pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 1, "the second call was not a hit"
    assert "tampered" not in again[0]
    assert len(again) == 1
    assert again_section["available"] is True

    again[0]["tampered"] = True
    again.append("not a finding")
    again_section["available"] = False

    third, third_section = pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 1
    assert "tampered" not in third[0], "the hit handed out the cached object itself"
    assert len(third) == 1
    assert third_section["available"] is True


def test_a_rewritten_board_is_not_served_from_the_cache(recorder, board):
    """Content, not path: the suite writes drifted fixtures into ``tmp_path``."""
    pcbreview.run_pcb_review(board, model={"u1": 1})
    board.write_bytes(b"B0ARD")
    pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 2


def test_a_chdir_moves_the_shelf_and_so_moves_the_key(recorder, board, tmp_path, monkeypatch):
    """The rules read a **cwd-relative** shelf (``blocklib/parts.json``).

    A reading taken in one directory is not the reading of another, so the
    working directory is part of the key even though the board file is
    absolute.
    """
    pcbreview.run_pcb_review(board, model={"u1": 1})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    pcbreview.run_pcb_review(board, model={"u1": 1})
    assert len(recorder.calls) == 2, "the shelf moved but the cache did not notice"


def test_a_caller_that_names_its_own_rules_is_never_cached(recorder, board):
    """``rules=[...]`` is the whole answer for those callers — cache nothing.

    152, 153, 164b, r2_1, 126a's probe and the online silk path all hand in a
    rule list; their readings are about *that* list, and two different lists on
    one board must never share an entry.
    """
    pcbreview.run_pcb_review(board, model={"u1": 1}, rules=[object()])
    pcbreview.run_pcb_review(board, model={"u1": 1}, rules=[object()])
    assert len(recorder.calls) == 2
    assert _pcb_cache.stats["bypassed"] == 2


def test_a_stand_in_rule_list_at_the_module_attribute_is_never_cached(recorder, board):
    """126a and 169 replace ``BUILTIN_PCB_RULES`` and run ``checkup`` end to end.

    ``rules=None`` means "the module's list", and the runner reads that
    attribute *at call time* — which is exactly what lets those two tests
    install a stand-in rule and see its rows. A cache that keyed only on the
    board, the model and the report's modules would hand the stand-in's caller
    the real rule set's reading (or hand the real rules the stand-in's), so the
    comparison is identity against the live attribute, and a replaced list
    takes the uncached path.

    The list is swapped by hand rather than through ``monkeypatch``: the
    ``recorder`` fixture already holds that fixture, and ``undo()`` would put
    the real runner back under the wrapper mid-test.
    """
    real = pcbreview.BUILTIN_PCB_RULES
    pcbreview.BUILTIN_PCB_RULES = [object()]
    try:
        pcbreview.run_pcb_review(board, model={"u1": 1})
        pcbreview.run_pcb_review(board, model={"u1": 1})
        assert len(recorder.calls) == 2

        # ...and the two lists do not share entries either way round.
        pcbreview.BUILTIN_PCB_RULES = real
        pcbreview.run_pcb_review(board, model={"u1": 1})
        assert len(recorder.calls) == 3, "the stand-in's reading was reused"
    finally:
        pcbreview.BUILTIN_PCB_RULES = real


def test_the_default_list_named_explicitly_is_the_default_list(recorder, board):
    """``rules=None`` and ``rules=BUILTIN_PCB_RULES`` are one question, not two."""
    pcbreview.run_pcb_review(board, model={"u1": 1})
    pcbreview.run_pcb_review(board, model={"u1": 1}, rules=pcbreview.BUILTIN_PCB_RULES)
    assert len(recorder.calls) == 1
