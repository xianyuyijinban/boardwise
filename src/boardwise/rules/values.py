"""Forwarding shim: the value parsers now live in :mod:`boardwise.core.values`.

Moved in 083. Until then this module held the implementation — the board value
grammar (``parse_resistance_ohms``, ``parse_capacitance_farads``,
``parse_voltage_volts``) and the MPN decoders beside them. It is now
:mod:`boardwise.core.values`, and this file exists for one reason: **nothing
that imported from here should have to know.** ``from boardwise.rules.values
import parse_capacitance_farads`` resolves exactly as it did, and so does the
private-name access the rules' own tests and monkeypatches use.

Why it moved, in one sentence: #51 and #52 wanted ``core`` to use the one
authoritative value parser (071 §2) and could not, because 006c's executable
layering forbids ``core`` importing ``rules`` at any depth.

**New code should import :mod:`boardwise.core.values` directly.** The arrow this
shim travels is ``rules -> core``, which is legal; the reverse is not, and that
is the whole reason the file exists in two places.

What is re-exported and how:

* **public names** come from the star import below, so they are the *same
  objects*, not copies — a value parsed here and a value parsed by
  ``core.values`` are the same number because it is the same function;
* **private names** (``_too_long``, ``_MAX_DECODED_CHARS``,
  ``_without_leading_size``, the module's regex tables) are not bound by a star
  import, and ``tests/test_011d_rules.py`` reaches for several of them, so
  :func:`__getattr__` (PEP 562) forwards anything the namespace does not hold.
  That is also what makes ``monkeypatch.setattr(values, "_too_long", ...)`` work
  against this module.

The star import is why :data:`__all__` is spelled out rather than left to
Python's "everything public": an explicit list is the one thing that can be
*checked*. It is **computed** from the implementation's namespace rather than
restated, so the two cannot drift, and ``tests/test_083_value_unification.py``
asserts that every name this shim promises is reachable — a name added to the
implementation without being re-exported here fails a test instead of failing
at somebody's import. (The two stdlib modules the implementation imports are
the only names the star binds that are not part of the module's own vocabulary,
and they are not part of what this shim promises.)

Deleting this shim is a separate, deliberate step: it is the one that may
delete the 11 ``from boardwise.rules.values import ...`` statements in the
repository, and until someone does that sweep, the import is what keeps this
file honest.
"""

from __future__ import annotations

from boardwise.core import values as _implementation
from boardwise.core.values import *  # noqa: F401,F403

#: The names the implementation's own ``import math`` / ``import re`` /
#: ``from __future__ import annotations`` left in its namespace. They are
#: modules and a compiler flag, not vocabulary, and a star import binds them;
#: this shim does not promise them to anyone.
_NOT_VOCABULARY = frozenset({"math", "re", "annotations"})

#: Every public name this shim promises, computed from the implementation so the
#: two lists cannot drift. The star import above is what actually binds them.
__all__ = sorted(
    name
    for name in vars(_implementation)
    if not name.startswith("_") and name not in _NOT_VOCABULARY
)


def __getattr__(name: str):
    """Forward a name this namespace does not hold to the implementation.

    PEP 562's module-level ``__getattr__``, which is consulted only when normal
    attribute lookup fails — so this never shadows a real attribute, and a
    ``monkeypatch.setattr`` on this module still wins over the implementation
    (which is what the rules' own tests rely on when they stub
    ``_too_long`` or widen ``_MAX_DECODED_CHARS``).

    A missing name raises :class:`AttributeError` from the implementation, which
    is the honest error: the shim did not invent it and will not pretend to.
    """
    return getattr(_implementation, name)


def __dir__() -> list[str]:
    """The names a reader should see: the promise plus what actually resolves.

    Without this, ``dir(boardwise.rules.values)`` would list the shim's own
    three globals and none of the parsers, which is how a module stops looking
    like the one it was.
    """
    return sorted({*globals(), *__all__, *dir(_implementation)})
