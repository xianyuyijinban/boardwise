"""The drawing grammars of 053 stage B (053 sec.3, 052 sec.5).

Three grammars, one per idiom the first slice is about, each a `bind` over the
two specs of stage A:

    voltage-divider   两电阻竖排同轴，抽头可见
    rc-lowpass        in→R→out 主干水平，C 从 out 节点向下支路到地
    ldo               in 左 core 中 out 右，电容各归所属节点

Two things this package is not. It does not compute coordinates — the compiler
does, and `RelativeConstraint` has no place to put one (053 sec.4). And it does
not check the resulting drawing — `engines/readability.py` does that
independently, over the LayoutPlan (053 sec.2; see the TODO in `base.py` for the
signature it will be called with).

The entry points, in the order a caller wants them:

    result = grammar.bind(circuit, presentation, profiles)      # dispatcher
    result = grammar.grammar_for("ldo", profiles).bind(c, p)    # by name

`bind` reads `presentation.grammar_ref`; a spec that names no grammar, or names
one this build does not have, comes back as a `facts-missing` refusal rather than
as a guess — a grammar is a set of promises about what will be visible, and
pretending to keep promises nobody wrote is worse than saying the grammar is not
known (052 sec.5).
"""

from __future__ import annotations

from typing import Mapping

from ...core.circuitspec import CircuitSpec
from ...core.presentationspec import GRAMMARS, PresentationSpec
from ...core.symbolprofile import SymbolProfile
from . import ldo, rc_lowpass, voltage_divider
from .base import (
    ABOVE,
    ADJACENT,
    BELOW,
    CONSTRAINT_KINDS,
    DIRECT_WIRE,
    FAILURE_CATEGORIES,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
    HORIZONTAL_TAP,
    LEFT_OF,
    MAX_CHAIN_ARMS,
    NEAR,
    NET_ROLES,
    OBLIGATION_KINDS,
    OWNED_BRANCH,
    PROVENANCE_UNSTATED,
    RIGHT_OF,
    SAME_COLUMN,
    SAME_ROW,
    UNIFORM_GND,
    VERTICAL_TAP,
    VISIBLE_TAP,
    DrawingGrammar,
    GrammarError,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    refused_result,
)

#: The three grammar names this build implements, spelled as `GRAMMARS` in
#: `presentationspec` spells them: the spec's literal and the implementation's
#: name are the same string, so a lookup cannot half-match.
NAMES: tuple[str, ...] = (voltage_divider.NAME, rc_lowpass.NAME, ldo.NAME)

_CLASSES: dict[str, type] = {
    voltage_divider.NAME: voltage_divider.VoltageDividerGrammar,
    rc_lowpass.NAME: rc_lowpass.RcLowpassGrammar,
    ldo.NAME: ldo.LdoGrammar,
}

#: Every role any grammar may bind, per grammar, table roles first and this
#: batch's additions after them (see each module for why the addition exists).
ROLES_BY_GRAMMAR: dict[str, tuple[str, ...]] = {
    voltage_divider.NAME: voltage_divider.ROLES + voltage_divider.EXTRA_ROLES,
    rc_lowpass.NAME: rc_lowpass.ROLES,
    ldo.NAME: ldo.ROLES + ldo.EXTRA_ROLES,
}

__all__ = [
    "NAMES",
    "ROLES_BY_GRAMMAR",
    "bind",
    "grammar_for",
    "ldo",
    "rc_lowpass",
    "voltage_divider",
    # the shared vocabulary, re-exported so a consumer imports one module
    "ABOVE",
    "ADJACENT",
    "BELOW",
    "CONSTRAINT_KINDS",
    "DIRECT_WIRE",
    "DrawingGrammar",
    "FAILURE_CATEGORIES",
    "FAILURE_CIRCUIT_INVALID",
    "FAILURE_FACTS_MISSING",
    "FAILURE_LAYOUT_UNSAT",
    "FAILURE_PRESENTATION_POOR",
    "GrammarError",
    "GrammarFailure",
    "GrammarObligation",
    "GrammarResult",
    "HORIZONTAL_TAP",
    "LEFT_OF",
    "MAX_CHAIN_ARMS",
    "NEAR",
    "NET_ROLES",
    "OBLIGATION_KINDS",
    "OWNED_BRANCH",
    "PROVENANCE_UNSTATED",
    "RIGHT_OF",
    "RelativeConstraint",
    "RoleBinding",
    "SAME_COLUMN",
    "SAME_ROW",
    "UNIFORM_GND",
    "VERTICAL_TAP",
    "VISIBLE_TAP",
    "bound_result",
    "refused_result",
]


def grammar_for(
    name: str, profiles: Mapping[str, SymbolProfile] | None = None
) -> DrawingGrammar:
    """The grammar with this name, holding the profiles it may read.

    An unknown name raises :class:`GrammarError`: that is a programming error at
    the call site, not a model's input (a spec naming an unknown grammar is
    answered by :func:`bind` with a refusal instead).
    """
    if name not in _CLASSES:
        raise GrammarError(
            f"unknown grammar {name!r}; this build knows {list(NAMES)} "
            f"(and `presentationspec.GRAMMARS` is {list(GRAMMARS)})"
        )
    return _CLASSES[name](profiles)


def bind(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | None = None,
    *,
    grammar_name: str = "",
) -> GrammarResult:
    """Bind the presentation's own grammar over this circuit.

    `grammar_name` overrides `presentation.grammar_ref` for a caller that
    already decided (the compiler binds each module it was handed); when it is
    empty the document's choice is used. Either way the name must be one this
    build has: a missing or unknown one is a `facts-missing` refusal naming where
    the choice belongs, never a silent fallback to a generic layout.
    """
    name = grammar_name or presentation.grammar_ref
    if not name:
        return refused_result([
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "the presentation states no drawing grammar "
                    "(PresentationSpec.grammarRef is empty), so there is nothing "
                    "to promise about what the drawing must make visible"
                ),
                action=(
                    "set grammarRef to one of " + ", ".join(NAMES) + " — the "
                    "grammar decides which roles, relations and visible "
                    "topologies the drawing owes"
                ),
            )
        ])
    if name not in _CLASSES:
        return refused_result([
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    f"the presentation asks for grammar {name!r}, which this "
                    f"build does not have (it has {list(NAMES)})"
                ),
                action=(
                    "use one of " + ", ".join(NAMES) + ", or state the circuit "
                    "as one of them if that is what it is"
                ),
            )
        ])
    return _CLASSES[name](profiles).bind(circuit, presentation)
