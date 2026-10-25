"""537D1a — the read-only projections ``boardwise review-read`` serves.

Why this module exists. 537D §2: a routine review used to answer every question
by hand-writing a one-off JSON parser (`python -c '...json.load(...)...'`) over
``report.json``. Those scripts were not wrong in one place, they were wrong in
one *direction*: a missing key read as 「零问题」, a sentence from
``summary.conclusion`` was re-quoted as the verdict, a ``needs-manual`` row was
counted as closed, a report with no ``pcb_review`` was read as 「跨视图一致」,
and a pre-537C report's missing evidence ledger simply disappeared. Each is the
same mistake — **reading an absence as an answer**.

This module is the one place that reads, and it reads in exactly one direction:
``report dict → payload``. It never re-gates, never renders, never writes, and
never derives a conclusion from prose:

* ``verdict`` carries ``report.conclusion`` and says ``status: "missing"`` when
  the section is absent. ``summary.conclusion`` is a **sentence**, not a
  substitute section — the board-level answer has one authority (185/537D) and
  recomputing it here would be a second one;
* ``findings`` reads the two ledgers and counts them through checkup's own
  predicates (:func:`boardwise.engines.checkup.triage_slot_is_closed` /
  :func:`~boardwise.engines.checkup.triage_slot_is_manual`) so 「pending」 and
  「needs manual」 cannot drift from the console, ``report.md`` and
  ``completion``. A ledger that is missing or of the wrong type is a
  ``ValueError``, never an empty list: "the report did not say" is not "there
  were no problems";
* ``crossView`` copies each board's ``crossView`` **verbatim** — ``checked:
  false`` stays false, ``suspected`` stays suspected, candidate mappings are not
  resolved — because 537D's non-goals forbid compressing the two possible causes
  into one conclusion. No board carrying a section at all is
  ``status: "missing"`` with ``boards: []``: a report without ``pcb_review`` is
  not evidence that the two views agree;
* ``coverage`` copies ``environment`` / ``evidence`` as they are and names every
  section it did not find in ``missingSections`` (environment, evidence,
  completion — the frozen order). An old report stays **readable**: it says what
  it lacks instead of being repaired with guesses;
* ``netlist`` (537D1a2a) serves the live capture's own parsed netlist as sorted
  rows. It is the one projection that cannot decide anything from the report
  alone — reading the netlist file is I/O and belongs to the CLI — so the CLI
  hands in ``live_model`` **and** the capture artifact only after it verified the
  identity, the ``liveSchematic`` channel and the artifact's bytes/hash. Without
  both, this module answers ``status: "missing"`` with a concrete reason and an
  empty component/net list: an archive ``report.model`` summary is never
  promoted to a live netlist. A member the current component/pin map cannot
  resolve (a repeated designator keeps only its last placement) keeps its row
  with ``pinName: null`` and is named in ``unresolvedPins`` — ``null`` is
  unknown, ``""`` is a real empty name, and neither hides the member.
* ``artifacts`` (537D1a2b) lists **only** the files the report's own machine
  fields cite, in a frozen order: the canvas images the renderer wrote, every
  channel's ``artifacts`` in :data:`~boardwise.engines.evidence.CHANNEL_ORDER`,
  the live capture's own ``artifacts`` and its ``captureFile``, then the five
  standard outputs by name (the delivery set). Nothing is guessed from the
  directory listing and nothing is read from prose: an unreferenced
  ``netlist_raw.json`` sitting in the directory is simply not part of the
  evidence chain. ``archivePcb.artifacts`` are board-level readings
  (``title``/``components``/``copperLayers``, no file), so they are not file
  citations and stay out of the list; every other source that is supposed to
  cite a file keeps its row even without one. Each row is
  ``{source, channel, artifact}`` with the artifact
  deep-copied; the *file facts* (``path`` / ``exists`` / ``bytesOnDisk`` /
  ``bytesMatch`` / ``sha256Matches`` / ``error``) are the CLI's step, because
  only the CLI may touch the disk. ``missingOutputs`` is ``None`` here for the
  same reason — a pure projection cannot know which standard outputs are absent,
  and an empty list would read as 「都在」.

``payload`` is a deep copy throughout, so a caller cannot reach back into the
report through what it was handed. The envelope, the file and the exit codes
belong to :func:`boardwise.cli._cmd_review_read`; this module has no CLI, no
filesystem and no I/O.

The section vocabulary and the envelope are frozen here so the plugin can parse
them today.
"""

from __future__ import annotations

import copy
import json

from .checkup import triage_slot_is_closed, triage_slot_is_manual
from .evidence import CHANNEL_ARCHIVE_PCB, CHANNEL_ORDER

#: The envelope every section is wrapped in by the CLI. Frozen: the 537D3 plugin
#: and the finalize validator both key off it, and it deliberately carries no
#: ``ok``-ish field — a successful *read* must not be mistakable for a passed
#: *board*.
REVIEW_READ_SCHEMA = "boardwise.review-read/1"

#: The questions this command answers. Order is the CLI's ``--section`` choices
#: order: verdict first because it is the board-level answer; ``artifacts``
#: before ``netlist`` because a file list is the shallower question — it says
#: which cited files are on disk and match their recorded bytes/sha256, while
#: ``netlist`` reads the live netlist's *content* (and only after the capture's
#: identity and ``liveSchematic`` channel proved it may).
REVIEW_READ_SECTIONS = (
    "verdict",
    "findings",
    "crossView",
    "coverage",
    "artifacts",
    "netlist",
)

#: Where the board-level answer lives, spelled out in the payload so no reader
#: has to remember which of the report's five verdict-ish fields is authoritative.
VERDICT_AUTHORITY = "report.conclusion"

#: The ``coverage`` section's missing-section order — fixed, because a list whose
#: order depends on the report's key order is one more thing a consumer has to
#: second-guess.
COVERAGE_SECTIONS = ("environment", "evidence", "completion")

#: The ``artifacts`` row source of the five standard outputs. The CLI routes
#: their absence into ``missingOutputs`` instead of an ``error``: they are the
#: delivery set, not a cited evidence chain (an old report that never wrote
#: ``live-evidence.json`` is still a readable report).
REVIEW_OUTPUT_SOURCE = "review-output"

#: The five files a review directory is expected to deliver, with the role each
#: one plays (the row's ``kind``). Frozen, and the CLI's
#: ``REVIEW_READ_PROTECTED_FILES`` is the same five names: a read command that
#: could rewrite one of them would be a way to destroy the evidence it is
#: reading, so a test pins the two lists equal.
REVIEW_OUTPUT_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("report.json", "report-json"),
    ("report.md", "report-markdown"),
    ("board-report.md", "board-report"),
    ("review-summary.md", "review-summary"),
    ("live-evidence.json", "live-evidence"),
)


def _projection_problem(report: object) -> str:
    """Why this object cannot be read as a report, or ``''`` when it can."""
    if not isinstance(report, dict):
        return f"report 不是一个 report 对象（{type(report).__name__}）"
    return ""


def _verdict_projection(report: dict) -> dict:
    """Board-level answer: ``report.conclusion`` and nothing derived from prose.

    ``summary.exitCode`` and ``evidence.delivery`` travel beside it because a
    reader always asks for them next, but neither is a verdict: the exit code is
    the process's, delivery describes evidence coverage (537C3a's own note).
    Both are reads — absent means ``None``, never a computed default.
    """
    conclusion = report.get("conclusion")
    has_conclusion = isinstance(conclusion, dict)
    completion = report.get("completion")
    summary = report.get("summary")
    evidence = report.get("evidence")
    delivery = evidence.get("delivery") if isinstance(evidence, dict) else None
    return {
        # `missing` is the whole point: a report without the section cannot say
        # whether the board passed, and the summary's sentence is not a licence
        # to answer on its behalf.
        "status": "ok" if has_conclusion else "missing",
        "conclusion": copy.deepcopy(conclusion) if has_conclusion else None,
        "completion": copy.deepcopy(completion) if isinstance(completion, dict) else None,
        "summaryExitCode": summary.get("exitCode") if isinstance(summary, dict) else None,
        "delivery": copy.deepcopy(delivery) if isinstance(delivery, dict) else None,
        "authority": VERDICT_AUTHORITY,
    }


def _findings_projection(report: dict) -> dict:
    """The findings list plus the triage ledger and its two counts.

    The counts are the **same arithmetic** as ``completion``: one predicate
    (:func:`triage_slot_is_closed`) decides 「closed」, so a ``needs-manual`` row —
    and a row nobody judged, and one hand-edited to a word outside the
    vocabulary — stays pending, and the manual rows are counted apart under their
    own question (「还有几条要人去看」) instead of being silently closed by the
    three-word path.

    Both ledgers must be **lists**. A report that lacks ``findings`` (or carries
    a dict) is refused by name rather than read as zero findings: the 537D review
    scripts' most expensive failure was exactly that substitution.
    """
    findings = report.get("findings")
    triage = report.get("warning_triage")
    problems = [
        name
        for name, value in (("findings", findings), ("warning_triage", triage))
        if not isinstance(value, list)
    ]
    if problems:
        raise ValueError(
            "report.json 的 " + " / ".join(problems)
            + " 不是 list（缺键或类型不对）——「报告没写」不等于「没有问题」，"
            "本命令不把它读成空列表"
        )
    # A non-dict row is still a row: it cannot be closed by any vocabulary, so it
    # counts as pending, and `triage_slot_is_manual` (which needs a `verdict`)
    # cannot call it manual. Reading it as `{}` is the honest shape for both
    # predicates and never invents a judgement.
    slots = [slot if isinstance(slot, dict) else {} for slot in triage]
    return {
        "status": "ok",
        "findings": copy.deepcopy(findings),
        "warning_triage": copy.deepcopy(triage),
        "warningsPendingTriage": sum(
            1 for slot in slots if not triage_slot_is_closed(slot)
        ),
        "warningsNeedsManual": sum(1 for slot in slots if triage_slot_is_manual(slot)),
    }


def _cross_view_projection(report: dict) -> dict:
    """Every board that carries a ``crossView`` dict, verbatim and in order.

    Nothing is filtered by ``suspected`` / ``missing`` / ``unavailable`` and the
    candidate mappings are copied as they are: the section's own 537C1 note says
    it does **not** judge which side is right, and a read command is the last
    place to start compressing that.

    ``status`` is about **presence**, not agreement: at least one board with a
    section is ``ok`` (a ``checked: false`` section is still the report's own
    statement and its flag is preserved), and no section anywhere is
    ``missing`` with an empty board list. A report that never had ``pcb_review``
    must not read as 「跨视图一致」.
    """
    section = report.get("pcb_review")
    boards = section.get("boards") if isinstance(section, dict) else None
    rows: list[dict] = []
    if isinstance(boards, list):
        for board in boards:
            if not isinstance(board, dict):
                continue
            cross_view = board.get("crossView")
            if not isinstance(cross_view, dict):
                continue
            rows.append(
                {
                    "title": board.get("title"),
                    "boardUuid": board.get("boardUuid"),
                    "crossView": copy.deepcopy(cross_view),
                }
            )
    return {"status": "ok" if rows else "missing", "boards": rows}


def _coverage_projection(report: dict) -> dict:
    """The two ledgers, the completion's coverage reading, and what is absent.

    ``environment`` and ``evidence`` are copied exactly; ``completionCoverage``
    and ``verdict`` come from ``completion``'s own keys (``None`` when the key is
    not there, never a recomputed value). ``missingSections`` names every section
    whose shape is not a dict, in the frozen order — a pre-537C report is readable
    and discloses its gaps instead of being filled in by guesswork (537D's
    "旧报告缺新节必须可读地披露，不能补猜").
    """
    missing: list[str] = []
    environment = report.get("environment")
    if not isinstance(environment, dict):
        environment = None
        missing.append("environment")
    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        evidence = None
        missing.append("evidence")
    completion = report.get("completion")
    if not isinstance(completion, dict):
        completion = None
        missing.append("completion")
    completion_coverage = (
        completion.get("coverage") if completion is not None else None
    )
    verdict = completion.get("verdict") if completion is not None else None
    return {
        "status": "missing" if missing else "ok",
        "environment": copy.deepcopy(environment) if environment is not None else None,
        "evidence": copy.deepcopy(evidence) if evidence is not None else None,
        "completionCoverage": (
            copy.deepcopy(completion_coverage)
            if completion_coverage is not None
            else None
        ),
        "verdict": copy.deepcopy(verdict),
        "missingSections": missing,
    }


def _live_capture(report: dict) -> dict | None:
    """``report.evidence.liveCapture`` when it is a dict, else ``None``.

    ``None`` (no capture) and a capture that is not an object are the same
    answer here — the machine fields simply are not there — and the missing
    reason says which one it found.
    """
    evidence = report.get("evidence")
    capture = evidence.get("liveCapture") if isinstance(evidence, dict) else None
    return capture if isinstance(capture, dict) else None


def _netlist_machine_fields(report: dict) -> tuple[dict | None, dict | None]:
    """``(identity, liveSchematic)``, each ``None`` when absent.

    The two live in different places, per the 537C3b2a merge contract:
    ``evidence.liveCapture`` keeps the capture **metadata** (``identity``,
    ``artifacts``, ``focusRestore``, …) and carries no ``channels`` — the four
    live channel rows are merged into the report's own
    ``evidence.channels``. Reading ``liveSchematic`` off the capture would see
    ``None`` on every real enhanced report, which is exactly the integration bug
    a capture-shaped fixture used to hide.

    Both are copied as they are: the projection reports what the collector
    recorded, and never recomputes ``verifiedAgainstReport`` or a channel status.
    """
    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        return None, None
    capture = evidence.get("liveCapture")
    identity = capture.get("identity") if isinstance(capture, dict) else None
    channels = evidence.get("channels")
    live = channels.get("liveSchematic") if isinstance(channels, dict) else None
    return (
        identity if isinstance(identity, dict) else None,
        live if isinstance(live, dict) else None,
    )


def _netlist_artifact_rows(capture: dict) -> list[dict]:
    """Every ``kind=netlist`` / ``channel=liveSchematic`` artifact row, in order."""
    artifacts = capture.get("artifacts")
    return [
        row
        for row in (artifacts if isinstance(artifacts, list) else [])
        if isinstance(row, dict)
        and row.get("kind") == "netlist"
        and row.get("channel") == "liveSchematic"
    ]


def _netlist_missing_reason(
    report: dict, live_model: object | None, netlist_artifact: dict | None
) -> str:
    """One concrete sentence for why no live netlist is projected.

    The order is the CLI's own gate: capture → identity → channel → artifact →
    the parse it handed over. A reason names the first fact that is not there so
    a reader can tell 「没采」 from 「采了但身份没核」 from 「哈希不对」 (the last one
    never reaches here — it is exit 2 upstream) instead of reading an empty list
    as an empty board.
    """
    if (live_model is None) != (netlist_artifact is None):
        absent = "parsed live_model" if live_model is None else "netlist artifact"
        return (
            "没有同时给出 parsed live_model 与 netlist artifact"
            f"（缺 {absent}）——不声称读到了实时网表"
        )
    capture = _live_capture(report)
    if capture is None:
        return (
            "报告没有 evidence.liveCapture（未做实时采集，或这是旧报告）——"
            "不从目录里的文件名或 summary 文案猜实时网表"
        )
    identity, live = _netlist_machine_fields(report)
    if identity is None or identity.get("verifiedAgainstReport") is not True:
        return (
            "identity.verifiedAgainstReport 不是 true——身份未核实，"
            "不把可能属于另一个工程的网表读成这块板的实时网表"
        )
    if live is None or live.get("status") != "ok":
        status = live.get("status") if isinstance(live, dict) else None
        return (
            f"channels.liveSchematic.status={status!r}——实时原理图证据不是 ok，"
            "不读网表"
        )
    rows = _netlist_artifact_rows(capture)
    if not rows:
        return (
            "capture.artifacts 没有 kind='netlist' 且 channel='liveSchematic' 的记录"
            "——没有可核对的实时网表文件"
        )
    if len(rows) > 1:
        return (
            f"capture.artifacts 有 {len(rows)} 条实时网表记录，必须恰好一条"
            "——不猜哪份属于本次读数"
        )
    return (
        "没有给出 parsed live_model 与 netlist artifact——只投影报告摘要，"
        "不声称从归档恢复实时网表"
    )


def _netlist_components(live_model: object) -> list[dict]:
    """Components as sorted rows; each pin list keeps the model's own order.

    ``pins`` is deliberately **not** sorted: the order is the parser's reading
    of the editor's own pin map, and a projection does not have a reason to
    reorder it. Components are sorted by designator so two equal reads compare
    equal, and a duplicate designator stays one row (the model's own dict
    contract) while ``repeatedDesignators`` discloses the ambiguity.
    """
    components = getattr(live_model, "components", None)
    if not isinstance(components, dict):
        raise ValueError(
            "live_model 没有 components 映射（不是 candidate_from_netlist 的产物）"
            "——不能为 netlist section 编一份"
        )
    rows: list[dict] = []
    for designator in sorted(components, key=str):
        component = components[designator]
        pins = [
            {
                "number": str(getattr(pin, "number", "")),
                "name": str(getattr(pin, "name", "") or ""),
                "net": getattr(pin, "net", None),
            }
            for pin in (getattr(component, "pins", None) or [])
        ]
        rows.append(
            {
                "uid": str(getattr(component, "uid", "") or ""),
                "designator": str(designator),
                "value": str(getattr(component, "value", "") or ""),
                "footprint": str(getattr(component, "footprint", "") or ""),
                "mpn": str(getattr(component, "mpn", "") or ""),
                "pins": pins,
            }
        )
    return rows


def _pin_name_index(live_model: object) -> dict[str, dict[str, str]]:
    """designator → (pin number → pin name), read from the live components only.

    A name is looked up by the **exact** pin-number string, so ``U9.3`` never
    borrows ``U9.33``'s name (537D's measured mismatch). A designator/pin the
    model does not carry has no entry here, which the net projection reports as
    ``pinName: null`` + ``unresolvedPins`` — never as a guessed name or an empty
    one.
    """
    components = getattr(live_model, "components", None)
    index: dict[str, dict[str, str]] = {}
    if not isinstance(components, dict):
        return index
    for designator, component in components.items():
        per_pin: dict[str, str] = {}
        for pin in getattr(component, "pins", None) or []:
            number = str(getattr(pin, "number", ""))
            per_pin.setdefault(number, str(getattr(pin, "name", "") or ""))
        index[str(designator)] = per_pin
    return index


def _netlist_member_sort_key(item: tuple[str, str]) -> tuple[str, int, object]:
    """Sort by designator, then by **numeric** pin number where there is one.

    ``U9.2`` sorts before ``U9.11`` (the reason a plain string sort is not used),
    and a non-numeric pin (``A1``) sorts after the numeric ones in its
    component, by its spelling. The flag keeps the tuple comparable: the types
    in the third slot are only compared inside one flag group.
    """
    designator, number = item
    try:
        return (designator, 0, int(number))
    except (TypeError, ValueError):
        return (designator, 1, number)


def _netlist_nets(live_model: object) -> tuple[list[dict], list[str]]:
    """``(nets, unresolvedPins)`` — sorted net rows plus members with no pin.

    Members are de-duplicated (a model may carry one pair twice) and sorted by
    designator + numeric pin. ``pinName`` comes from the same live component's
    exact pin number: an archive name, a neighbouring pin's name or an empty
    guess is exactly the substitution 537C3b3 measured and refused.

    A member that the current component/pin map cannot resolve (the candidate
    parser keeps only the last placement of a repeated designator, so an earlier
    placement's pin can be missing) gets ``pinName: None`` and its ``REF.pin``
    in ``unresolvedPins``. ``None`` is not ``""``: a pin that exists with an
    empty name is a known empty name, a pin that does not exist is unknown, and
    the two must stay distinguishable. The member itself is never dropped — the
    net still says the editor put something there.
    """
    nets = getattr(live_model, "nets", None)
    if not isinstance(nets, dict):
        raise ValueError(
            "live_model 没有 nets 映射（不是 candidate_from_netlist 的产物）"
            "——不能为 netlist section 编一份"
        )
    names = _pin_name_index(live_model)
    unresolved: set[str] = set()
    rows: list[dict] = []
    for name in sorted(nets, key=str):
        net = nets[name]
        members: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pair in getattr(net, "pins", None) or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            designator, number = str(pair[0]), str(pair[1])
            if (designator, number) in seen:
                continue
            seen.add((designator, number))
            members.append((designator, number))
        members.sort(key=_netlist_member_sort_key)
        row_members: list[dict] = []
        for designator, number in members:
            per_pin = names.get(designator)
            if per_pin is None or number not in per_pin:
                unresolved.add(f"{designator}.{number}")
                pin_name: str | None = None
            else:
                pin_name = per_pin[number]
            row_members.append(
                {"pin": f"{designator}.{number}", "pinName": pin_name}
            )
        rows.append({"name": str(name), "members": row_members})
    return rows, sorted(unresolved)


def _netlist_repeated_designators(live_model: object) -> list[str]:
    """The model's own ambiguous names, through its own method, or ``[]``.

    The ambiguity is **disclosed**, not hidden and not resolved: a projection
    that silently kept one placement would answer a different question than the
    one the capture asked. A model without the method has no names to report.
    """
    method = getattr(live_model, "repeated_designators", None)
    if not callable(method):
        return []
    try:
        names = method()
    except Exception:  # noqa: BLE001 — a model that cannot answer has no names
        return []
    return [str(name) for name in names] if isinstance(names, (list, tuple)) else []


def _netlist_projection(
    report: dict,
    *,
    live_model: object | None = None,
    netlist_artifact: dict | None = None,
) -> dict:
    """The live netlist as sorted rows, or ``missing`` with a concrete reason.

    ``status: "ok"`` requires **both** the parsed ``live_model`` and the artifact
    that proved the file: one without the other is exactly the 「从归档恢复实时
    网表」 claim this section exists to prevent. ``report.model`` rides along as a
    deep copy because a reader asks for it next, but it is never the source of
    ``components`` / ``nets`` — those only come from the live parse.

    Nothing is aliased: the report's summary, the machine fields and the
    artifact are deep-copied, and the component/net rows are freshly built.
    """
    identity, live = _netlist_machine_fields(report)
    model_summary = report.get("model")
    ok = live_model is not None and netlist_artifact is not None
    nets, unresolved = _netlist_nets(live_model) if ok else ([], [])
    return {
        "status": "ok" if ok else "missing",
        "reason": (
            "" if ok else _netlist_missing_reason(report, live_model, netlist_artifact)
        ),
        "model": copy.deepcopy(model_summary) if isinstance(model_summary, dict) else None,
        "liveSchematic": copy.deepcopy(live),
        "identity": copy.deepcopy(identity),
        "artifact": copy.deepcopy(netlist_artifact) if netlist_artifact is not None else None,
        "components": _netlist_components(live_model) if ok else [],
        "nets": nets,
        "repeatedDesignators": (
            _netlist_repeated_designators(live_model) if ok else []
        ),
        "unresolvedPins": unresolved,
    }


def _artifact_rows(report: dict) -> list[dict]:
    """Every artifact the report's **machine fields** cite, in the frozen order.

    The order is the evidence chain a reviewer reads it in, not the report's key
    order: what the renderer drew, what each live channel wrote, what the live
    capture recorded itself, then the five standard outputs.

    Only machine fields are read. The directory listing, ``summary`` prose and
    file names are never consulted: a ``netlist_raw.json`` that no
    ``artifacts`` row cites is not evidence, and a picture named like a report's
    image is not that image (537D's 「不从文件名猜 artifact」). Rows that are
    not objects are skipped — they are not artifacts — while an object without a
    usable ``file`` is still a row: the CLI names that as an error instead of
    silently dropping a citation the report made.

    One deliberate exception, measured on a real enhanced report:
    ``archivePcb.artifacts`` are **board-level readings** — ``{title,
    components, copperLayers}`` from ``evidence._archive_pcb``, which writes no
    file at all. Those rows carry no ``file`` key and are not file citations, so
    they are not part of this list (the readings stay readable in ``coverage``).
    The exception is that channel only: every other source that is supposed to
    cite a file keeps its row even without one, so an empty citation cannot
    vanish into green.

    ``liveCapture`` keeps **metadata only** in a merged report (C3b2a): its own
    ``artifacts`` and ``captureFile`` are here, but the four live channel rows
    live in ``evidence.channels`` and are read from there. Reading channels off
    the capture would see none on every real enhanced report.
    """
    rows: list[dict] = []

    ai_slots = report.get("ai_slots")
    canvas = ai_slots.get("canvas_images") if isinstance(ai_slots, dict) else None
    for item in canvas if isinstance(canvas, list) else []:
        if isinstance(item, dict):
            rows.append(
                {
                    "source": "ai_slots.canvas_images",
                    "channel": None,
                    "artifact": copy.deepcopy(item),
                }
            )

    evidence = report.get("evidence")
    channels = evidence.get("channels") if isinstance(evidence, dict) else None
    if isinstance(channels, dict):
        for name in CHANNEL_ORDER:
            channel = channels.get(name)
            artifacts = channel.get("artifacts") if isinstance(channel, dict) else None
            for item in artifacts if isinstance(artifacts, list) else []:
                if not isinstance(item, dict):
                    continue
                if name == CHANNEL_ARCHIVE_PCB and item.get("file") is None:
                    # A board reading, not a file: `_archive_pcb` writes
                    # `{title, components, copperLayers}` and no path. Kept out
                    # of the file list instead of being reported as a missing
                    # file it was never meant to be.
                    continue
                rows.append(
                    {
                        "source": "evidence.channels",
                        "channel": name,
                        "artifact": copy.deepcopy(item),
                    }
                )

    capture = evidence.get("liveCapture") if isinstance(evidence, dict) else None
    if isinstance(capture, dict):
        artifacts = capture.get("artifacts")
        for item in artifacts if isinstance(artifacts, list) else []:
            if not isinstance(item, dict):
                continue
            channel = item.get("channel")
            rows.append(
                {
                    "source": "liveCapture.artifacts",
                    "channel": channel if isinstance(channel, str) and channel else None,
                    "artifact": copy.deepcopy(item),
                }
            )
        capture_file = capture.get("captureFile")
        if isinstance(capture_file, dict):
            rows.append(
                {
                    "source": "liveCapture.captureFile",
                    "channel": None,
                    "artifact": copy.deepcopy(capture_file),
                }
            )

    for name, kind in REVIEW_OUTPUT_ARTIFACTS:
        rows.append(
            {
                "source": REVIEW_OUTPUT_SOURCE,
                "channel": None,
                "artifact": {"file": name, "kind": kind},
            }
        )
    return rows


def _artifact_identity(row: dict) -> tuple[object, ...] | None:
    """The de-duplication key of one collected row, or ``None`` when it has none.

    The key is ``(source, channel, <whole artifact>)``. Only a **byte-identical**
    repetition is a duplicate: the same record listed twice inside one source is
    one file, and the first occurrence keeps its place. Everything else is a
    distinct claim, deliberately including two rows with the same
    ``file``/``kind`` but a different ``bytes``/``sha256`` — those are a
    *contradiction*, and collapsing them would hide one half of it (the CLI must
    be able to verify both and answer ``unavailable``). A *different* source
    citing the same file is not a duplicate either: two evidence chains reaching
    one artifact are two claims.

    The artifact is serialised with ``sort_keys`` so key order in the report does
    not change identity; a value that cannot be serialised simply has no key and
    is kept.
    """
    artifact = row.get("artifact")
    if not isinstance(artifact, dict):
        return None
    try:
        declaration = json.dumps(
            artifact, ensure_ascii=False, sort_keys=True, default=str
        )
    except (TypeError, ValueError):  # circular or otherwise unserialisable
        return None
    return (row.get("source"), row.get("channel"), declaration)


def _dedupe_artifact_rows(rows: list[dict]) -> list[dict]:
    """Drop byte-identical repeated rows, keeping the first, in order."""
    seen: set[tuple[object, ...]] = set()
    kept: list[dict] = []
    for row in rows:
        key = _artifact_identity(row)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(row)
    return kept


def _artifacts_projection(report: dict) -> dict:
    """The report's cited artifacts, as ``{source, channel, artifact}`` rows.

    The file facts are **not** here: ``path`` / ``exists`` / ``bytesOnDisk`` /
    ``bytesMatch`` / ``sha256Matches`` / ``error`` are the CLI's step, because
    this module has no filesystem. ``missingOutputs`` is ``None`` for the same
    reason — only a reader that can see the directory knows which standard
    outputs are absent, and ``[]`` would be read as 「都在」, exactly the
    absence-as-answer mistake this command exists to prevent.

    ``status`` is about **the collection**: ``ok`` when the report cites at
    least one artifact of its own (a channel row, a canvas image, a capture
    file), ``missing`` when its only rows are the five standard outputs — «this
    report cites no evidence file». The CLI replaces it with the file-verified
    answer.
    """
    rows = _dedupe_artifact_rows(_artifact_rows(report))
    cited = [row for row in rows if row.get("source") != REVIEW_OUTPUT_SOURCE]
    return {
        "status": "ok" if cited else "missing",
        "artifacts": rows,
        "missingOutputs": None,
    }


#: ``--section`` name → projection. One table, so the CLI's argparse choices and
#: the dispatch cannot drift apart (a new section is one row, not two edits).
_PROJECTIONS = {
    "verdict": _verdict_projection,
    "findings": _findings_projection,
    "crossView": _cross_view_projection,
    "coverage": _coverage_projection,
    "artifacts": _artifacts_projection,
    "netlist": _netlist_projection,
}


def review_read_section(
    report: dict,
    section: str,
    *,
    live_model: object | None = None,
    netlist_artifact: dict | None = None,
) -> dict:
    """The payload for one ``--section``, or ``ValueError`` on unusable input.

    The only public entry point. It is pure — no I/O, no writes, no re-gate, no
    render — so a caller (the CLI, a test) gets the same dict for the same report
    every time, and a ``ValueError`` means the report cannot answer that question
    (a missing/non-list ledger, an unknown section name), which the CLI maps to
    exit 2.

    ``live_model`` / ``netlist_artifact`` are only meaningful for
    ``section="netlist"``: the CLI reads the capture's netlist file, proves its
    bytes/sha256 and parses it, then hands the parse here. Every other section
    ignores them (and the CLI never passes them), so old callers are unchanged.

    An unknown ``section`` is refused by name rather than defaulting to one: a
    typo must not silently serve a different question's answer.
    """
    problem = _projection_problem(report)
    if problem:
        raise ValueError(problem)
    projection = _PROJECTIONS.get(section)
    if projection is None:
        raise ValueError(
            f"未知的 section {section!r}；合法值：{', '.join(REVIEW_READ_SECTIONS)}"
        )
    if section == "netlist":
        return projection(
            report,
            live_model=live_model,
            netlist_artifact=netlist_artifact,
        )
    return projection(report)
