"""PCB-side rules (task 126, 阶段 C).

A **parallel** rule family: these rules read one PCB document's geometry
(:class:`boardwise.core.geometry.BoardGeometry`) rather than a schematic
:class:`~boardwise.core.model.DesignModel`, and they live in their own runner
(:mod:`boardwise.engines.pcbreview`). Nothing here touches
:data:`boardwise.engines.review.BUILTIN_RULES` — the schematic side keeps its own
21 rules and its own ``len(ids) == 21`` pin.

Layout of the package as the batches land:

* ``base`` — :class:`PcbRule` and :class:`PcbReviewContext` (126a).
* ``distance`` — the house-rule distance checks (126b).
* ``ipc`` — the IPC-2221 checks (126c).
* ``regulator`` — per-regulator input/output capacitor placement (131b).
* ``fbplacement`` — feedback-divider placement (131c).
* ``crystal`` — an MCU's crystal and load-capacitor placement (131d).
* ``mcusupply`` — an MCU's supply groups and their bypass/reservoir columns (131e).
* ``mcureset`` — an MCU's ``NRST`` net and ``BOOT`` strap inventory (131e).
* ``foc`` — the five FOC / 功率驱动 quick wins (133b): a power driver's bypass
  proximity, the ground-plane island inventory, the gate-trace width
  distribution, the non-obtuse fold list, and the high-current loop area.

The package is importable from the start; ``BUILTIN_PCB_RULES`` was **empty**
in 126a and its structure gate (the test that says "the list is the truth") is
the pin that a rule arriving must flip.
"""