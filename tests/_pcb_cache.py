"""C7: **one PCB review per (board, model, rule set) per worker process**.

**Why this file exists.** :func:`boardwise.engines.pcbreview.run_pcb_review` is
the whole PCB rule engine: one call re-parses the backup, extracts the geometry
of every PCB document in it, rebuilds each document's netlist view and runs all
~30 PCB rules. It is the largest single engine entry in the suite — measured
(``outputs/perf/heatmap.md`` §2.1) at **383 calls / 444.2 s of worker time** in
one full run, and the call count is the *test* count, not the fixture count:
``test_133d`` 35 calls, ``test_133b`` 26, ``test_131e`` 25, ``test_133c`` 20,
``test_155a`` 18 — all of them over the same four boards, with the same models.

The modules under test already cache the *schematic* half of that work (each
file's ``_PROJECTS`` / ``_project(path)``, 170) and nothing cached the runner's
own answer, so every test in a file paid the archive parse, the geometry
extraction and all 30 rules again for an answer it already had. This file is
that missing cache, and it is the same design as ``_golden.py``'s (159): **share
the expensive answer, hand every caller its own copy**.

**What the key is.** Two levels, because the pieces have different comparability:

* the bucket is ``(resolved path, sha256 of the file's bytes, cwd, parts-shelf
  identity)``. Content, not mtime — a rewritten fixture must not hit, and the
  suite does write fixtures into ``tmp_path`` — plus the two things the rules
  read besides the archive: the shelf comes from a **cwd-relative** path
  (``facts.DEFAULT_LIBRARY_PATH = "blocklib/parts.json"``), so a test that
  chdirs or rewrites the shelf must not be served a stale answer;
* inside the bucket, the entry is ``(model, intent, modules)`` compared **by
  value** — first by identity (the common case: a file's own
  ``_project(path)`` cache hands the same object to every test in it), then with
  ``==`` (``build_project_model(path)`` builds a fresh-but-equal model, and an
  equal model is the same question — the same relation ``_golden.py``'s
  ``solver_plan_or_cache`` already keys its own cache on).

**What is never cached.** Only the built-in rule list, and only by identity with
the list **this module found at import** (``_BUILTIN``): a call whose resolved
rule list is anything else goes straight to the real runner. That is not
defensiveness — it is two live cases in this suite: ``test_126a`` replaces the
list with a stand-in and ``test_169`` appends a broken rule to it, both through
``checkup`` end to end, and both must see the rules they installed. It also
keeps every ``rules=[...]`` call in the suite (the polarity, silk, derating,
keepout, supply-view and online-silk callers) out of the cache by construction:
those tests are about *one rule*, not about the whole engine.

The comparison has to be against the captured object and not against the
attribute, and that is a measured point rather than a stylistic one: both of
those tests pass ``rules=None``, and ``None`` resolves to *whatever the
attribute holds at call time* — so ``rule_list is pcbreview.BUILTIN_PCB_RULES``
is true for the stand-in too, and a cache keyed that way files the stand-in's
reading as the real one. ``tests/test_pcb_review_cache.py`` pins both directions
and was red on exactly this while this file was being written.

The rest of the suite's monkeypatching is safe by measurement, not by hope: the
only ``setattr`` targets reachable from a *default-rule* run are the rule list
itself (handled above) and ``facts.default_library_path`` (``test_126b``, which
then calls a rule's own helper, never the runner); every other mutation test in
the PCB files mutates in-process and calls the rule *function*, never the
runner. The ``--library`` argument of ``checkup`` is not part of this at all:
the runner never takes a library, and the rules read the default shelf.

**A copy goes out.** Findings and the section are handed to tests that filter,
index and assert over them, and one test mutating a finding it was given would
otherwise mutate it for every later test in that worker. The copy is cheap and
measured — 1.12 ms for 毕设FOC 1.0.0's reading (132 findings) against the 2.72 s
that reading took — see ``outputs/perf02B/copy_cost.txt``.

**How it is installed.** Importing this module *replaces*
``boardwise.engines.pcbreview.run_pcb_review`` with the caching wrapper;
``tests/conftest.py`` imports it, so it is in place before any test module is
imported and every ``from boardwise.engines.pcbreview import run_pcb_review``
binds the cached name. Nothing in ``src/`` knows this file exists, and a test
that replaces the attribute itself (126d, 166) still does.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import os
from typing import Any

from boardwise.engines import pcbreview
from boardwise.rules import facts

#: The real runner, captured before anything replaces it. The wrapper calls this
#: by reference, so a test that patches ``pcbreview.run_pcb_review`` (126d, 166)
#: changes what *its* call sites see without disarming the cache underneath.
_REAL = pcbreview.run_pcb_review

#: The built-in rule list **as this module found it**. Held as an object of our
#: own because "the default list" is not a name, it is a particular list: 126a
#: and 169 replace ``pcbreview.BUILTIN_PCB_RULES`` and then call through
#: ``checkup`` with ``rules=None`` — where ``rule_list is
#: pcbreview.BUILTIN_PCB_RULES`` is **true** whatever that attribute holds, so
#: comparing against the live name would cache the stand-in's reading as if it
#: were the built-in one (measured: the pin test in
#: ``tests/test_pcb_review_cache.py`` was red on exactly this).
_BUILTIN = pcbreview.BUILTIN_PCB_RULES

#: ``bucket -> [(model, intent, modules, result), ...]``. One bucket per board
#: file, then a linear scan: a file's tests differ in which model spelling they
#: hand over, and there are a handful of models per fixture, not hundreds.
_CACHE: dict[tuple, list[tuple[Any, Any, Any, Any]]] = {}

#: A cache, not a ledger. The suite reviews ~12 fixture files, so this bound is
#: only ever reached by a session that keeps writing new boards; dropping the
#: table then costs a re-run, never a wrong answer.
_MAX_BUCKETS = 64

#: Read by the tests that pin this cache and by the perf evidence run.
stats = {"hits": 0, "misses": 0, "bypassed": 0}


def clear() -> None:
    """Drop every cached reading (the counters are left alone)."""
    _CACHE.clear()


def reset_stats() -> None:
    for name in stats:
        stats[name] = 0


def _digest(path: str) -> str:
    """``sha256`` of the board file's **bytes** — the cache invalidates on content."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _shelf() -> tuple[Any, Any, Any]:
    """The parts shelf the rules read, as ``(path, mtime_ns, size)``.

    The default shelf is a **cwd-relative** constant (``"blocklib/parts.json"``,
    ``rules.facts``), and the PCB rules load it inside ``check()``, so the
    answer depends on which directory the process is in and on what is in that
    file. A missing shelf is a reading of its own (the rules narrow rather than
    fail), so it is recorded as ``(path, None, None)`` rather than refused.
    """
    path = facts.default_library_path()
    try:
        info = os.stat(path)
    except OSError:
        return (path, None, None)
    return (path, info.st_mtime_ns, info.st_size)


def _bucket(source_path: Any) -> tuple:
    """``(resolved path, content digest, cwd, shelf)`` for one board file."""
    resolved = os.path.abspath(os.fspath(source_path))
    return (resolved, _digest(resolved), os.getcwd(), _shelf())


def _same(left: Any, right: Any) -> bool:
    """Identity first, then value; a comparison that raises is a miss.

    ``None`` is the common case on one side or the other (the runner is called
    with and without a schematic model), and the two must not be conflated with
    a model: identity covers ``None``, a value comparison that refuses to answer
    is treated as "different", and a wrong *hit* is the only failure mode here
    that matters.
    """
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:  # noqa: BLE001 — an uncomparable model is simply not equal
        return False


def _cached_run_pcb_review(
    source_path: Any,
    model: Any = None,
    intent: Any = None,
    modules: list[dict] | None = None,
    *,
    rules: list | None = None,
) -> tuple[list, dict | None]:
    """``pcbreview.run_pcb_review``, served from the session cache.

    Signature-compatible with the real runner (the same one this module
    replaced), so every call site — the tests' own, and ``cli._run_pcb_runner``'s
    lazy import — reaches it unchanged.
    """
    rule_list = pcbreview.BUILTIN_PCB_RULES if rules is None else rules
    if rule_list is not _BUILTIN:
        stats["bypassed"] += 1
        return _REAL(source_path, model, intent, modules, rules=rules)
    try:
        key = _bucket(source_path)
    except OSError:
        # An unreadable archive is the runner's own error to report, and it
        # cannot be cached: there is no digest to file it under.
        stats["bypassed"] += 1
        return _REAL(source_path, model, intent, modules, rules=rules)
    for held_model, held_intent, held_modules, result in _CACHE.get(key, ()):
        if (
            _same(held_model, model)
            and _same(held_intent, intent)
            and _same(held_modules, modules)
        ):
            stats["hits"] += 1
            return copy.deepcopy(result)
    stats["misses"] += 1
    result = _REAL(source_path, model, intent, modules, rules=rules)
    if len(_CACHE) >= _MAX_BUCKETS:
        _CACHE.clear()
    _CACHE.setdefault(key, []).append((model, intent, modules, result))
    return copy.deepcopy(result)


#: ``functools.wraps`` keeps the name, the docstring and ``inspect.signature``
#: (through ``__wrapped__``) pointing at the real runner: a test that reads the
#: signature of what it imported reads the production one.
_CACHED = functools.wraps(_REAL)(_cached_run_pcb_review)


def install() -> bool:
    """Point ``pcbreview.run_pcb_review`` at the cache; idempotent.

    ``BOARDWISE_NO_PCB_CACHE=1`` leaves the patch off entirely. That is the
    switch the perf evidence uses (``outputs/perf02B/``): the same tree, the same
    command and the same machine, with the wrapper as the **only** difference —
    which is what makes the before/after timing an attribution rather than a
    coincidence. It is also the way out if this cache ever misbehaves in a
    session nobody can debug from inside pytest.
    """
    if os.environ.get("BOARDWISE_NO_PCB_CACHE"):
        return False
    if pcbreview.run_pcb_review is not _CACHED:
        pcbreview.run_pcb_review = _CACHED
        return True
    return False


install()
