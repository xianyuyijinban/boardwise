"""The gates a board spec must pass, in two families (008c item 4; 009-M0 P0).

A board spec is a *claim*: these blocks, these numbers, these connections. The
gates split by whose discipline they enforce, because "a user is drawing a new
board" and "we are grading a generation run" are different questions:

**Product gates** — what any spec must satisfy before anything may be drawn
from it. They always run:

1. **sources** — every declared input is real: the file is there to be read,
   the shelf holds the cited part (:data:`core.blocks.SpecReference`);
2. **pin budget** — the firmware's pin table and the schematic's MCU block must
   agree in both directions, and the block cannot use more pins than its symbol
   exposes;
3. **levels** — a signal net joins ports that speak the same IO domain. One net
   carries one domain; there is no declaration that licenses mixing two, because
   a level shifter's low side and high side are *two different nets* (2026-09-18
   ruling, M0-P0c — the old ``level_shifter`` exemption only ever let real
   errors through with a note);
4. **power tree** — every power rail has exactly one source, and every sink on
   it asks for the voltage that source provides. Ground is exempt: ground is the
   sink.

**Benchmark gate** — the discipline of a *generation evaluation*, run only when
``benchmark=True`` (CLI: ``validate --benchmark``), reported as *skipped* with
the reason otherwise:

5. **closed book** — nothing generation-side may trace back to the target board
   itself, and every field must name the declared input that justifies it. The
   evidence ledger lives here because it is how a benchmark spec proves the
   generator did not invent — or copy — the page. A user drawing a new board
   owes sound electricity, not a bibliography, so the product run does not ask
   for one; and the committed CH340 spec carries no ledger at all, which under
   a product-side ledger rule could never be drawn.

Two rules of the house are carried into the code:

* **fail closed.** Anything any gate cannot judge is reported as
  *undecidable*, and an undecidable result blocks exactly like a violation
  does. A pass-by-silence is worse than a stop, because nobody re-reads a green
  report.
* **"could not run" is its own answer.** A gate whose inputs were never
  supplied is reported as *skipped* with the reason stated, and printing it says
  plainly that nothing was checked. Skipping does **not** block — there are
  boards with no MCU — but it can never be confused with having agreed.

Port metadata is optional on purpose (see :class:`core.blocks.BlockPort`), so a
template written before 008c item 4 loads unchanged and is *silent*; the levels
and power-tree gates answer "cannot tell" for it rather than passing it. For
blocks cut out of a board the metadata lives in the sidecar
(:mod:`core.portmeta`) rather than in the file, because a declaration is not
something the board's geometry says and the file has to stay reproducible:

    validate_spec(load_board_spec(p, port_meta=load_port_meta(SIDECAR)), ...)

without that argument the same board comes back "cannot tell" — which blocks,
because pretending to agree is the one thing these gates must never do.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..core.blocks import BoardSpec, BlockPort
from ..core.parts import PartLibrary
from ..core.pintable import PinTable
from .pintable_check import PinFinding, check_pin_table

#: How a finding is to be read. ``violation`` and ``undecidable`` both block;
#: ``note`` is context a reader needs and nothing more.
VIOLATION = "violation"
UNDECIDABLE = "undecidable"
NOTE = "note"

#: Gate statuses. Skipped is deliberately not "pass": see the module docstring.
PASS = "pass"
FAIL = "fail"
UNDECIDABLE_GATE = "undecidable"
SKIPPED = "skipped"

#: The order gates run and print in. The closed-book gate is first because it is
#: the one about honesty: if the page was copied from the answer, every other
#: agreement it shows is worthless. It is benchmark discipline, so a product run
#: prints it as *skipped* with the reason — never as a quiet pass.
GATE_ORDER = ("closed-book", "sources", "pin-budget", "levels", "power-tree")

_DATE_SUFFIX = re.compile(r"^(?P<head>.+?)_(?P<date>\d{4}-\d{2}-\d{2})$")


@dataclass
class Finding:
    """One thing one gate has to say."""

    kind: str  # 'violation' | 'undecidable' | 'note'
    rule: str
    message: str
    evidence: list[str] = field(default_factory=list)

    @property
    def is_violation(self) -> bool:
        return self.kind == VIOLATION

    @property
    def is_undecidable(self) -> bool:
        return self.kind == UNDECIDABLE

    @property
    def blocks(self) -> bool:
        return self.kind in (VIOLATION, UNDECIDABLE)

    def render(self) -> str:
        where = f" ({'; '.join(self.evidence)})" if self.evidence else ""
        return f"[{self.kind}] {self.rule}: {self.message}{where}"

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rule": self.rule,
            "message": self.message,
            "evidence": list(self.evidence),
        }


@dataclass
class Gate:
    """One gate's whole answer. Either it ran (``findings``) or it did not."""

    name: str
    title: str
    findings: list[Finding] = field(default_factory=list)
    #: Non-empty when the gate's inputs were absent; the reason is *required*
    #: text, so a skipped gate can never be printed as a quiet blank.
    skipped: str = ""

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.is_violation]

    @property
    def undecidables(self) -> list[Finding]:
        return [f for f in self.findings if f.is_undecidable]

    @property
    def status(self) -> str:
        if self.skipped:
            return SKIPPED
        if self.violations:
            return FAIL
        if self.undecidables:
            return UNDECIDABLE_GATE
        return PASS

    def render(self) -> list[str]:
        status = self.status
        head = f"{self.name} — {self.title}: {status}"
        if self.skipped:
            return [head, f"  {self.skipped}"]
        counts = (
            f"{len(self.violations)} violation(s), "
            f"{len(self.undecidables)} undecidable, "
            f"{len(self.findings) - len(self.violations) - len(self.undecidables)} note(s)"
        )
        return [f"{head} ({counts})"] + [f"  {f.render()}" for f in self.findings]

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "status": self.status,
            "skipped": self.skipped,
            "findings": [f.as_json() for f in self.findings],
        }


@dataclass
class ValidationReport:
    """Every gate's answer, in :data:`GATE_ORDER`, bound to one spec revision.

    ``spec_hash`` is the sha256 of the spec file's bytes, cut to 12 hex chars:
    "it passed" about a *previous* revision of the spec is the failure mode the
    digest exists to forbid, and nothing is cached — every run re-reads the
    file. It is empty for a spec that was never on disk.
    """

    gates: list[Gate] = field(default_factory=list)
    spec_hash: str = ""

    @property
    def violations(self) -> list[Finding]:
        return [f for gate in self.gates for f in gate.violations]

    @property
    def undecidables(self) -> list[Finding]:
        return [f for gate in self.gates for f in gate.undecidables]

    @property
    def skipped(self) -> list[Gate]:
        return [gate for gate in self.gates if gate.status == SKIPPED]

    @property
    def blocking(self) -> list[Finding]:
        return self.violations + self.undecidables

    @property
    def ok(self) -> bool:
        """True when nothing blocks. Skipped gates do not block."""
        return not self.blocking

    def gate(self, name: str) -> Gate | None:
        return next((g for g in self.gates if g.name == name), None)

    def render(self) -> list[str]:
        digest = f" (spec sha256:{self.spec_hash})" if self.spec_hash else ""
        lines = [
            f"spec validation{digest}: {len(self.violations)} violation(s), "
            f"{len(self.undecidables)} undecidable, "
            f"{len(self.skipped)} gate(s) skipped"
        ]
        for gate in self.gates:
            lines.extend(f"  {line}" for line in gate.render())
        lines.append(
            "verdict: may proceed"
            if self.ok
            else "verdict: STOPPED — nothing downstream may use this spec"
        )
        return lines

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "spec_hash": self.spec_hash,
            "violations": [f.as_json() for f in self.violations],
            "undecidables": [f.as_json() for f in self.undecidables],
            "gates": [g.as_json() for g in self.gates],
            "rendered": self.render(),
        }


# --------------------------------------------------------------------------
# gate 1 — the closed book (benchmark discipline)
# --------------------------------------------------------------------------


def _target_names(targets: Iterable[str]) -> list[str]:
    """The board names a spec may not cite, one token per declared target.

    A target is given as it exists on disk — ``tests/fixtures/ProPrj_智能药箱
    _2026-09-17.epro2`` — and one board has several aliases worth recognising:
    the file name as written, and the name without its export date (the same
    design exported next week is the same board, and "we re-exported it" must
    not be a loophole).
    """
    names: list[str] = []
    for target in targets:
        text = str(target).strip().replace("\\", "/")
        if not text:
            continue
        stem = Path(text).stem if Path(text).suffix else text
        dated = _DATE_SUFFIX.match(stem)
        for candidate in (stem, dated["head"] if dated else ""):
            name = candidate.lower()
            if name and name not in names:
                names.append(name)
    return names


def _traces_to(source: str, names: Iterable[str]) -> str:
    """Return the board name ``source`` belongs to, else ``""``.

    Comparing whole paths is not enough on its own: one board is often one
    design under two names (``blocklib/sources/smart_pillbox.eprj2`` and an
    export of it), and both are off-limits. So every *path segment* is tried
    against every name — the raw spelling and the resolved one, because a
    reference may be relative.

    A segment that merely starts with the name still counts (``smart_pillbox_core``
    was cut out of ``smart_pillbox``) but only across a separator, so ``ch340x``
    is never condemned for being named like ``ch340``. Each segment is compared
    with and without its extension: ``ch340_golden.epro2`` and the directory
    ``ch340_golden`` are the same thing to this check.
    """
    text = str(source).strip().replace("\\", "/")
    if not text:
        return ""
    try:
        forms = [text, str(Path(source).resolve()).replace("\\", "/")]
    except OSError:  # a path that cannot be resolved is still a string to read
        forms = [text]
    for name in names:
        for form in forms:
            for segment in re.split(r"[/\\]+", form):
                low = segment.lower()
                bare = Path(low).stem if Path(low).suffix else low
                for candidate in (low, bare):
                    if (
                        candidate == name
                        or candidate.startswith(name + "_")
                        or candidate.startswith(name + "-")
                    ):
                        return name
    return ""


def _spec_text(spec: BoardSpec) -> str:
    """The spec's own text, lower-cased; ``""`` when it is not on disk.

    A hand-built spec (tests) has no file, and that is stated rather than
    silently treated as "no leaks found".
    """
    if not spec.path:
        return ""
    file = Path(spec.path)
    if not file.is_file():
        return ""
    return file.read_text(encoding="utf-8", errors="replace").lower()


def _find_reference_path(ref_path: str, root: str | Path | None) -> Path | None:
    candidates: list[Path] = []
    candidate = Path(ref_path)
    if candidate.is_absolute():
        candidates.append(candidate)
    elif root is not None:
        candidates.append(Path(root) / candidate)
    for item in candidates:
        if item.exists():
            return item
    return None


def _gate_closed_book(
    spec: BoardSpec,
    *,
    targets: list[str],
    benchmark: bool,
) -> Gate:
    findings: list[Finding] = []
    title = (
        "no field may come from the target board, and every field must cite a "
        "declared input"
    )
    if not benchmark:
        return Gate(
            name="closed-book",
            title=title,
            skipped=(
                "benchmark discipline, not run: the closed book grades a "
                "generation run — nothing may trace to the target board, and "
                "every field must cite a declared input. A board being drawn "
                "owes sound electricity, not a bibliography; re-run with "
                "benchmark=True (CLI: --benchmark) to grade it"
            ),
        )

    names = _target_names(targets)
    if not names:
        findings.append(
            Finding(
                kind=UNDECIDABLE,
                rule="closed-book",
                message=(
                    "no target board was named, so nothing was checked — this is "
                    "*not* a pass: without knowing whose board this is, \"we did "
                    "not copy the answer\" is an untested claim"
                ),
            )
        )
        return Gate(name="closed-book", title=title, findings=findings)

    # ---- the answer may not appear anywhere generation-side
    own = _traces_to(spec.provenance_source, names)
    if own:
        findings.append(
            Finding(
                kind=VIOLATION,
                rule="self-reference",
                message=(
                    f"the spec itself says it comes from the target board {own!r} "
                    "— the answer may only appear on the compare side"
                ),
                evidence=[f"spec.provenance.source = {spec.provenance_source}"],
            )
        )
    for block in spec.blocks:
        matched = _traces_to(block.template.provenance_source, names)
        if matched:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="self-reference",
                    message=(
                        f"block {block.id!r} comes from a template cut out of the "
                        f"target board {matched!r}; generating this page from the "
                        "page it is graded against proves nothing"
                    ),
                    evidence=[
                        f"{block.template.name}: provenance.source = "
                        f"{block.template.provenance_source}"
                    ],
                )
            )

    text = _spec_text(spec)
    if not text:
        findings.append(
            Finding(
                kind=NOTE,
                rule="answer-leak",
                message=(
                    "the spec is not on disk, so its text could not be scanned "
                    "for mentions of the target board"
                ),
            )
        )
    else:
        for name in names:
            if name in text:
                findings.append(
                    Finding(
                        kind=VIOLATION,
                        rule="answer-leak",
                        message=(
                            f"the target board's name ({name!r}) appears in the spec "
                            "file itself; a generation-side artifact may not even "
                            "talk about the answer"
                        ),
                        evidence=[f"spec text mentions {name!r}"],
                    )
                )

    # ---- the answer may not be smuggled in as a declared input either
    for ref in spec.references:
        matched = _traces_to(ref.path, names) if ref.path else ""
        if matched:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="self-reference",
                    message=(
                        f"declared input {ref.id!r} is the target board itself "
                        f"({matched!r}); declaring the answer as an authority is "
                        "how copying launders itself into the record"
                    ),
                    evidence=[f"{ref.id}: {ref.path}"],
                )
            )

    # ---- every field must carry evidence
    declared = {ref.id: ref for ref in spec.references}
    used: set[str] = set()

    def _check_ids(ids: Iterable[str], spot: str) -> None:
        for name in ids:
            used.add(name)
            if name not in declared:
                findings.append(
                    Finding(
                        kind=VIOLATION,
                        rule="evidence-declared",
                        message=(
                            f"{spot} cites {name!r}, which the spec never declares "
                            "as an input; the whole point of the closed book is "
                            "that nothing outside the declared list counts"
                        ),
                        evidence=[
                            f"declared: {', '.join(sorted(declared)) or '(none)'}"
                        ],
                    )
                )

    for block in spec.blocks:
        if not block.evidence:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="evidence-present",
                    message=(
                        f"block {block.id!r} ({block.template.name}) cites nothing — "
                        "nothing declares why it is on this page"
                    ),
                    evidence=[f"block {block.id}"],
                )
            )
        else:
            _check_ids(block.evidence, f"block {block.id!r}")

    for key in sorted(spec.params):
        evidence = spec.param_evidence.get(key)
        if not evidence:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="evidence-present",
                    message=(
                        f"parameter value {key!r} = {spec.params[key]!r} cites "
                        "nothing; a number with no authority behind it is a guess"
                    ),
                    evidence=[f"{key} = {spec.params[key]}"],
                )
            )
        else:
            _check_ids(evidence, f"parameter value {key!r}")

    for connection in spec.connections:
        ports = ", ".join(f"{b}.{r}" for b, r in connection.ports)
        if not connection.evidence:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="evidence-present",
                    message=(
                        f"connection {connection.net!r} ({ports}) cites nothing; "
                        "joining two blocks is a decision and must be owned"
                    ),
                    evidence=[f"net {connection.net}: {ports}"],
                )
            )
        else:
            _check_ids(connection.evidence, f"connection {connection.net!r}")

    orphans = sorted(set(declared) - used)
    if orphans:
        findings.append(
            Finding(
                kind=NOTE,
                rule="evidence-present",
                message=(
                    f"declared but never cited: {', '.join(orphans)} — kept because "
                    "reading them helps, counted because they prove nothing yet"
                ),
            )
        )

    if not spec.references:
        findings.append(
            Finding(
                kind=VIOLATION,
                rule="evidence-present",
                message=(
                    "the spec declares no inputs at all, so no field can cite one; "
                    "a closed book nobody opened is not a closed book"
                ),
            )
        )
    return Gate(name="closed-book", title=title, findings=findings)


# --------------------------------------------------------------------------
# gate 2 — the sources
# --------------------------------------------------------------------------


def _gate_sources(
    spec: BoardSpec,
    *,
    root: str | Path | None,
    library: PartLibrary | None,
) -> Gate:
    """Every declared input is real — the one ledger rule a product spec owes.

    A spec declares what it stands on; this gate checks the declarations are
    *applicable*: the file is there to be read, the shelf holds the cited part.
    Whether every field then *cites* one of those inputs is the benchmark's
    business (the closed book), not a product question.
    """
    title = "every declared input is real"
    findings: list[Finding] = []
    for ref in spec.references:
        if ref.kind == "part":
            if library is None:
                findings.append(
                    Finding(
                        kind=UNDECIDABLE,
                        rule="declared-input-exists",
                        message=(
                            f"declared input {ref.id!r} cites shelf key {ref.ref!r} "
                            "but no library was supplied, so the cited part could "
                            "not be looked up — this is *not* a pass"
                        ),
                        evidence=[f"{ref.id}: {ref.ref}"],
                    )
                )
            elif library.get(ref.ref) is None:
                findings.append(
                    Finding(
                        kind=VIOLATION,
                        rule="declared-input-exists",
                        message=(
                            f"declared input {ref.id!r} cites shelf key {ref.ref!r}, "
                            "which is not on the shelf"
                        ),
                        evidence=[f"{ref.id}: {ref.ref}"],
                    )
                )
            continue
        if not ref.path:
            continue
        if root is None:
            findings.append(
                Finding(
                    kind=NOTE,
                    rule="declared-input-exists",
                    message=(
                        f"declared input {ref.id!r} points at {ref.path!r} and no "
                        "root was supplied, so it was not checked"
                    ),
                )
            )
        elif _find_reference_path(ref.path, root) is None:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="declared-input-exists",
                    message=(
                        f"declared input {ref.id!r} points at {ref.path!r}, which is "
                        "not there — a citation nobody can read is not evidence"
                    ),
                    evidence=[f"{ref.id}: {ref.path}"],
                )
            )
    return Gate(name="sources", title=title, findings=findings)


# --------------------------------------------------------------------------
# gate 3 — the pin budget
# --------------------------------------------------------------------------


def _mcu_block(spec: BoardSpec, table: PinTable, mcu_block_id: str) -> Any | None:
    """The spec's MCU block, or ``None`` when it cannot be named without a guess.

    Two instantiations of the same MCU template (008c item 6) make the choice
    genuinely ambiguous, and a pin table can only describe one pin allocation,
    so ambiguity is reported rather than resolved by picking the first.
    """
    if mcu_block_id:
        return spec.instance(mcu_block_id)
    named = [block for block in spec.blocks if _template_is(block.template.name, table.mcu)]
    if len(named) == 1:
        return named[0]
    fallback = [block for block in spec.blocks if block.id == "mcu"]
    if len(fallback) == 1 and not named:
        return fallback[0]
    return None


def _template_is(name: str, mcu: str) -> bool:
    """Whether template ``name`` is the part the pin table's ``mcu`` names.

    The table says ``ic.stm32g431rbt6``; a block may be named for the same part
    with or without the leading category, so both spellings are tried — but
    only whole names, never substrings, because ``stm32g4`` and ``stm32g431``
    are different parts.
    """
    if not name or not mcu:
        return False
    left = {name.lower(), name.rsplit(".", 1)[-1].lower()}
    right = {mcu.lower(), mcu.rsplit(".", 1)[-1].lower()}
    return bool(left & right)


def _mcu_component_of(template: Any, mcu_component: str) -> tuple[str, str]:
    """``(ref, why-not)`` for the component whose symbol carries the pins."""
    if mcu_component:
        return mcu_component, ""
    if len(template.components) == 1:
        return template.components[0].ref, ""
    return "", (
        f"block {template.name!r} has {len(template.components)} components and no "
        "MCU one was named, so the pin count has nothing to be compared against"
    )


def _symbol_pin_numbers(template: Any, component_ref: str) -> set[str]:
    component = next((c for c in template.components if c.ref == component_ref), None)
    if component is None:
        return set()
    symbol = template.symbols.get(component.symbol)
    return set(symbol.offsets) if symbol is not None else set()


def _from_pin_finding(finding: PinFinding) -> Finding:
    """Map a pin-table finding into this module's vocabulary.

    Open questions stay non-blocking here as they are there: a signal the
    schematic wires and the firmware never uses is a question for whoever owns
    the firmware, not a reason to stop the page.
    """
    kind = VIOLATION if finding.kind == "defect" else NOTE
    return Finding(
        kind=kind, rule=finding.rule, message=finding.message, evidence=list(finding.evidence)
    )


def _gate_pin_budget(
    spec: BoardSpec,
    table: PinTable | None,
    *,
    mcu_block_id: str,
    mcu_component: str,
) -> Gate:
    title = "the firmware's pins and the schematic's MCU block agree, and fit"
    if table is None:
        return Gate(
            name="pin-budget",
            title=title,
            skipped=(
                "no pin table was supplied, so nothing was checked — a page whose "
                "MCU carries no firmware is not a failing page, but this run says "
                "nothing about its pins"
            ),
        )

    findings: list[Finding] = []
    block = _mcu_block(spec, table, mcu_block_id)
    if block is None:
        candidates = ", ".join(b.id for b in spec.blocks) or "(none)"
        findings.append(
            Finding(
                kind=UNDECIDABLE,
                rule="mcu-found",
                message=(
                    f"the pin table names MCU {table.mcu!r} but no block in the spec "
                    f"is that part (blocks: {candidates}), so the two were never "
                    "compared — this is *not* a pass"
                ),
                evidence=[f"blocks: {candidates}"],
            )
        )
        return Gate(name="pin-budget", title=title, findings=findings)

    component, why_not = _mcu_component_of(block.template, mcu_component)
    if why_not:
        findings.append(
            Finding(kind=UNDECIDABLE, rule="mcu-component", message=why_not)
        )
        return Gate(name="pin-budget", title=title, findings=findings)

    report = check_pin_table(
        table,
        mcu_block=block.template,
        mcu_component=component,
        spec=spec,
        mcu_block_id=block.id,
    )
    findings.extend(_from_pin_finding(f) for f in report.findings)

    # ---- the second half: how many of the MCU's pins the page uses
    numbers = _symbol_pin_numbers(block.template, component)
    if not numbers:
        findings.append(
            Finding(
                kind=UNDECIDABLE,
                rule="pin-budget",
                message=(
                    f"the symbol of {component} in block {block.id!r} exposes no pin "
                    "numbers, so the number of pins the page uses cannot be compared "
                    "against anything"
                ),
                evidence=[f"{block.id}.{component}"],
            )
        )
        return Gate(name="pin-budget", title=title, findings=findings)

    used = [
        role
        for connection in spec.connections
        for joins, role in connection.ports
        if joins == block.id
    ]
    if len(used) > len(numbers):
        findings.append(
            Finding(
                kind=VIOLATION,
                rule="pin-budget",
                message=(
                    f"block {block.id!r} connects {len(used)} port(s) but the symbol "
                    f"of {component} exposes {len(numbers)} pin(s) — the page asks "
                    "for more pins than the part has"
                ),
                evidence=[", ".join(sorted(used))],
            )
        )
    else:
        findings.append(
            Finding(
                kind=NOTE,
                rule="pin-budget",
                message=(
                    f"block {block.id!r} connects {len(used)} of {component}'s "
                    f"{len(numbers)} pin(s)"
                ),
            )
        )
    return Gate(name="pin-budget", title=title, findings=findings)


# --------------------------------------------------------------------------
# gate 4 — levels
# --------------------------------------------------------------------------


def _ports_of(spec: BoardSpec, connection: Any) -> list[tuple[Any, Any, BlockPort]]:
    """``(block instance, block id, port)`` for the ports a net joins."""
    out: list[tuple[Any, Any, BlockPort]] = []
    for join_id, role in connection.ports:
        instance = spec.instance(join_id)
        if instance is None:
            continue
        port = instance.template.port(role)
        if port is not None:
            out.append((instance, join_id, port))
    return out


def _gate_levels(spec: BoardSpec) -> Gate:
    title = "a signal net joins ports that speak one IO domain"
    findings: list[Finding] = []
    for connection in spec.connections:
        entries = _ports_of(spec, connection)
        if not entries or any(not port.is_signal for _, _, port in entries):
            continue
        stated = [(who, port) for instance, who, port in entries if port.level]
        domains = {port.level for _, port in stated}
        ports = ", ".join(f"{who}.{port.role}" for who, port in stated) or "(none)"
        if len(domains) > 1:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="level-domain",
                    message=(
                        f"net {connection.net!r} joins ports in two IO domains "
                        f"({', '.join(sorted(domains))}) — a net carries one domain, "
                        "so this is a mix-up unless the two ends belong on two "
                        "different nets"
                    ),
                    evidence=[ports],
                )
            )
            continue
        silent = [
            f"{who}.{port.role}"
            for instance, who, port in entries
            if not port.level
        ]
        # `entries` is non-empty (line above) and this branch means *no* port
        # stated a level, so every entry is silent and `silent` cannot be empty
        # here. The evidence is the silent list itself; an "or <fallback>" used
        # to sit here naming an undefined variable, which only ever proved it
        # was unreachable (M0-P0c).
        if not domains:
            findings.append(
                Finding(
                    kind=UNDECIDABLE,
                    rule="level-domain",
                    message=(
                        f"net {connection.net!r} has no port declaring a level, so "
                        f"the domains were not compared ({', '.join(silent)}) — this "
                        "is *not* a pass"
                    ),
                    evidence=silent,
                )
            )
            continue
        if silent:
            findings.append(
                Finding(
                    kind=UNDECIDABLE,
                    rule="level-domain",
                    message=(
                        f"net {connection.net!r} declares {domains.pop()!r} on some "
                        f"ports but not on {', '.join(silent)}, so whether the two "
                        "ends agree cannot be decided — a silent port is not a "
                        "matching port"
                    ),
                    evidence=silent,
                )
            )
    return Gate(name="levels", title=title, findings=findings)


# --------------------------------------------------------------------------
# gate 5 — the power tree
# --------------------------------------------------------------------------


def _gate_power_tree(spec: BoardSpec) -> Gate:
    title = "every rail has exactly one source, and it feeds what the sinks ask for"
    findings: list[Finding] = []
    for connection in spec.connections:
        entries = _ports_of(spec, connection)
        rails = [(who, port) for _, who, port in entries if port.net_class == "power"]
        if not rails:
            continue  # ground is the sink and nothing else; signals are gate 3's

        def where(port: BlockPort, who: str) -> str:
            return f"{who}.{port.role}"

        silent = [f"{who}.{port.role}" for who, port in rails if not port.direction]
        if silent:
            findings.append(
                Finding(
                    kind=UNDECIDABLE,
                    rule="one-source",
                    message=(
                        f"net {connection.net!r} carries {', '.join(silent)} with no "
                        "`direction`, so whether it has exactly one source cannot be "
                        "counted — this is *not* a pass"
                    ),
                    evidence=silent,
                )
            )
            continue
        sources = [f"{who}.{port.role}" for who, port in rails if port.is_source]
        sinks = [f"{who}.{port.role}" for who, port in rails if port.is_sink]
        if not sources:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="one-source",
                    message=(
                        f"net {connection.net!r} has sinks ({', '.join(sinks) or 'none'}) "
                        "but no source — a rail nobody drives is dead copper"
                    ),
                    evidence=sinks or [f"ports: {len(rails)}"],
                )
            )
            continue
        if len(sources) > 1:
            findings.append(
                Finding(
                    kind=VIOLATION,
                    rule="one-source",
                    message=(
                        f"net {connection.net!r} has {len(sources)} sources "
                        f"({', '.join(sources)}); two drivers never agree exactly, "
                        "and the difference is current nobody designed for"
                    ),
                    evidence=sources,
                )
            )
            continue
        source = next(port for who, port in rails if port.is_source)
        source_name = sources[0]
        if not source.voltage:
            findings.append(
                Finding(
                    kind=UNDECIDABLE,
                    rule="voltage-match",
                    message=(
                        f"source {source_name} on net {connection.net!r} declares no "
                        "`voltage`, so its sinks cannot be checked against it — this "
                        "is *not* a pass"
                    ),
                    evidence=[source_name],
                )
            )
            continue
        for who, port in rails:
            if not port.is_sink:
                continue
            if not port.voltage:
                findings.append(
                    Finding(
                        kind=UNDECIDABLE,
                        rule="voltage-match",
                        message=(
                            f"sink {where(port, who)} on net {connection.net!r} "
                            "declares no `voltage`, so what it needs cannot be "
                            f"compared against {source_name}'s {source.voltage!r}"
                        ),
                        evidence=[where(port, who), f"source: {source.voltage}"],
                    )
                )
            elif port.voltage != source.voltage:
                findings.append(
                    Finding(
                        kind=VIOLATION,
                        rule="voltage-match",
                        message=(
                            f"sink {where(port, who)} asks for {port.voltage!r} on net "
                            f"{connection.net!r} but the only source, {source_name}, "
                            f"provides {source.voltage!r}"
                        ),
                        evidence=[f"sink: {port.voltage}", f"source: {source.voltage}"],
                    )
                )
    return Gate(name="power-tree", title=title, findings=findings)


# --------------------------------------------------------------------------
# all five together
# --------------------------------------------------------------------------


def _spec_digest(spec: BoardSpec) -> str:
    """sha256 of the spec file's bytes, cut to 12 hex chars; ``""`` off-disk."""
    if not spec.path:
        return ""
    try:
        return hashlib.sha256(Path(spec.path).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def validate_spec(
    spec: BoardSpec,
    *,
    table: PinTable | None = None,
    library: PartLibrary | None = None,
    target: str | Iterable[str] | None = None,
    root: str | Path | None = None,
    mcu_block_id: str = "",
    mcu_component: str = "",
    benchmark: bool = False,
) -> ValidationReport:
    """Run every gate over one board spec, in :data:`GATE_ORDER`.

    The product gates (sources, pin budget, levels, power tree) always run.
    The closed book is *benchmark discipline* and runs only with
    ``benchmark=True``; otherwise it reports itself skipped with the reason,
    because "the generation was not graded" must never read as "the generation
    was clean".

    Every gate runs even when an earlier one has already failed: a page that is
    both copied from the answer and mis-wired wants both facts said at once,
    not one discovered after the other is fixed.

    ``target`` names the board being generated (once, or several aliases of
    it). Only the closed book consults it, and a benchmark run without one is
    undecidable, which blocks.
    """
    targets: list[str] = []
    if isinstance(target, str):
        targets = [target]
    elif target is not None:
        targets = [str(item) for item in target]

    gates = [
        _gate_closed_book(spec, targets=targets, benchmark=benchmark),
        _gate_sources(spec, root=root, library=library),
        _gate_pin_budget(spec, table, mcu_block_id=mcu_block_id, mcu_component=mcu_component),
        _gate_levels(spec),
        _gate_power_tree(spec),
    ]
    order = {name: index for index, name in enumerate(GATE_ORDER)}
    gates.sort(key=lambda gate: order.get(gate.name, len(order)))
    return ValidationReport(gates=gates, spec_hash=_spec_digest(spec))


__all__ = [
    "FAIL",
    "GATE_ORDER",
    "NOTE",
    "PASS",
    "SKIPPED",
    "UNDECIDABLE",
    "UNDECIDABLE_GATE",
    "VIOLATION",
    "Finding",
    "Gate",
    "ValidationReport",
    "validate_spec",
]
