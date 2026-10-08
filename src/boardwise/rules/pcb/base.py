"""The PCB rule base class and what a PCB rule is handed (task 126a, 钉 1).

A PCB rule judges **one PCB document's geometry**, which is why it takes a
:class:`PcbReviewContext` and not a :class:`~boardwise.core.model.DesignModel`:
the measurements all come from :mod:`boardwise.core.measure` (task 125), and the
netlist is present only so a rule can ask which parts share a net.

What is deliberately **not** here:

* no severity ladder of its own — ``rules.base.Severity`` is the same three
  steps, and ``SEVERITY_ORDER`` is unchanged (钉 1). "第二步权重最高" is expressed
  by report ordering and ``verdictWhy``, never by a fourth grade;
* no per-rule threshold table — each rule annotates its own constants with the
  document they come from (钉 7: IPC-2221 / house rule 待裁 / oracle ruling);
* no ``check()`` return contract of its own — the findings are ordinary
  :class:`~boardwise.rules.base.Finding` objects so ``review-mark`` and
  ``warning_triage`` consume PCB findings through the very same array as
  schematic ones (侦察结论).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Finding
from ..base import Rule as SchematicRule


@dataclass
class PcbReviewContext:
    """What one PCB rule sees when it is run on one PCB document.

    ``board`` is the geometry of **one** PCB document, never a project's
    collection: :func:`boardwise.engines.pcbreview.run_pcb_review` builds one
    context per document so a rule never has to ask "which board is this?".
    ``board_title`` is that document's ``META`` title (``"PCB1"``), which is what
    a finding's ``board`` field carries (钉 4) — the schematic side stamps a
    *schematic* page title, so the two kinds are told apart by the document type
    rather than by an extra field.

    ``model`` is the same project's schematic model: module attribution and
    power-net identification read it (a decoupling rule asks which capacitors
    share an IC's supply net, which is a netlist question, not a geometry one).
    ``intent`` is the design-intent contract, or ``None`` — a rule with no
    contract follows the UNKNOWN discipline (钉 6) rather than guessing a
    current or a voltage.

    ``pcb_model`` is the **netlist view of the PCB document this rule is
    running on** (:func:`boardwise.parsers.epro2_model.build_design_model`,
    scoped to one document since 131c), or ``None`` when the caller has none.
    It exists because the two views do **not** agree on net names: a backup's
    PCB documents carry the editor's real net names (``+24V``, ``$1N66466``)
    while the schematic view of the same file renumbers them (``NET11``,
    ``NET16``), and a rule that asks 「which capacitors share U5's output net」
    has to be answered in the same view it is measuring geometry in.
    ``pcb-decap-distance`` / ``pcb-*-ipc`` deliberately keep reading
    ``model`` — their questions are established over the schematic — while the
    regulator rules read ``pcb_model``, and a rule that needs both may read
    both.
    """

    board: object
    board_title: str = ""
    model: object | None = None
    intent: object | None = None
    #: designator -> module name. Built by
    #: :func:`boardwise.engines.pcbreview.build_module_of`; a designator that is
    #: in no module is simply absent (the report's `未归属` module catches it).
    module_of: dict[str, str] = field(default_factory=dict)
    #: The netlist view of ``board``'s own PCB document, or ``None``. See the
    #: class docstring: same geometry, the editor's own net names.
    pcb_model: object | None = None


class PcbRule(SchematicRule):
    """Base class for every PCB rule (钉 1).

    A subclass sets ``id`` (prefix ``pcb-``), ``title`` and ``source``, and
    implements :meth:`check`. ``source`` is not decoration: it is where the
    threshold came from, and a house rule has to say it is 待裁 — see 钉 7.

    It derives from ``rules.base.Rule`` rather than from nothing, so a PCB rule
    carries the same four declarative attributes and reads as a rule everywhere
    the report introspects one; the only thing that differs is the argument
    :meth:`check` takes.
    """

    id: str = ""
    title: str = ""
    level: str = ""
    source: str = ""

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        raise NotImplementedError