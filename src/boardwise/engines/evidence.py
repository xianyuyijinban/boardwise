"""537C3a: the six-channel evidence / coverage ledger.

Why this module exists. The 537 review measured a run that read the live
schematic, reviewed the archived PCB, failed to read the live PCB and produced
no PCB image — and the report disclosed none of it in a machine-readable place.
A reader could not tell「PCB 查过，干净」from「PCB 从没读过」, and a partial
delivery was hidden behind one coarse verdict.

So this module builds **one** section that says, per channel, what was
collected and what was not:

* the six channels, in a frozen order —
  ``liveSchematic / archivePcb / livePcb / schematicImage / pcbImage /
  datasheets``;
* five statuses, and they are not interchangeable —
  ``ok`` (a real reading exists), ``failed`` (a read was attempted and it did
  not produce usable evidence), ``missing`` (not collected — including "PCB
  existence unknown"), ``unavailable`` (the datasheet gate owes evidence),
  ``not-applicable`` (confirmed nothing to read — e.g. no PCB document);
* ``coverage`` — the status map **derived from** ``channels``, so there is one
  status per channel and never a second hand-kept copy to drift;
* ``delivery`` — ``complete`` only when every channel is ``ok`` or
  ``not-applicable``, else ``partial``, with a note that says this is
  evidence/coverage only and **not** a board-level pass or fail, plus one
  ``requiredDisclosures[]`` row per open channel.
* 537C3b2: :func:`merge_live_capture` folds one ``boardwise.live-evidence/1``
  capture into an existing section — it replaces only the four live rows, keeps
  ``archivePcb`` / ``datasheets`` verbatim, stores the capture metadata under
  ``liveCapture`` (outside ``channels``), and derives two **non-channel**
  disclosures after the six: unverified identity and a failed focus restore.
  Neither can be cancelled by ``capture.ok``.

What this module is not: a gate. ``delivery`` is a *reading*. The old
``completion.verdict``, ``summary.exitCode`` and the process exit code do not
read it (537C3a §二.6). C3b owns the live collection that upgrades
``livePcb`` / ``pcbImage`` / ``liveSchematic`` from ``missing``; C3b2 only
merges that capture and never treats ``capture.ok`` as a board conclusion.

Import discipline: this module is imported **by** ``engines.checkup`` (for the
shared Markdown renderer), so it must never import ``engines.checkup`` or
``boardwise.cli`` back. It handles data and text only.
"""

from __future__ import annotations

import copy
from typing import Iterable

#: The report key the section lives under. One name, read by `report.json`,
#: `report.md`, `review-summary.md` and the console line.
EVIDENCE_KEY = "evidence"

#: The section's own schema id. Independent of ``CHECKUP_SCHEMA``: the checkup
#: report's id does not bump for a reading (537C3a §二.6), and a consumer that
#: wants to know the ledger's shape asks this.
EVIDENCE_SCHEMA = "boardwise.review-evidence/1"

#: The six channel ids, in the frozen order every renderer follows.
CHANNEL_LIVE_SCHEMATIC = "liveSchematic"
CHANNEL_ARCHIVE_PCB = "archivePcb"
CHANNEL_LIVE_PCB = "livePcb"
CHANNEL_SCHEMATIC_IMAGE = "schematicImage"
CHANNEL_PCB_IMAGE = "pcbImage"
CHANNEL_DATASHEETS = "datasheets"

CHANNEL_ORDER: tuple[str, ...] = (
    CHANNEL_LIVE_SCHEMATIC,
    CHANNEL_ARCHIVE_PCB,
    CHANNEL_LIVE_PCB,
    CHANNEL_SCHEMATIC_IMAGE,
    CHANNEL_PCB_IMAGE,
    CHANNEL_DATASHEETS,
)

#: Where each channel's reading comes from. Frozen: the renderer prints it, and
#: `archive` vs `live-sch` is exactly the distinction this ledger exists to keep.
CHANNEL_SOURCES: dict[str, str] = {
    CHANNEL_LIVE_SCHEMATIC: "live-sch",
    CHANNEL_ARCHIVE_PCB: "archive",
    CHANNEL_LIVE_PCB: "live-pcb",
    CHANNEL_SCHEMATIC_IMAGE: "image",
    CHANNEL_PCB_IMAGE: "image",
    CHANNEL_DATASHEETS: "datasheet",
}

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_MISSING = "missing"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_APPLICABLE = "not-applicable"

CHANNEL_STATUSES: tuple[str, ...] = (
    STATUS_OK,
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_UNAVAILABLE,
    STATUS_NOT_APPLICABLE,
)

#: The statuses that close a channel: a real reading, or a confirmed "there is
#: nothing of this kind here". Everything else is an open debt.
CLOSED_STATUSES: frozenset[str] = frozenset({STATUS_OK, STATUS_NOT_APPLICABLE})

DELIVERY_COMPLETE = "complete"
DELIVERY_PARTIAL = "partial"

#: The note that travels with every delivery status. It is part of the contract:
#: `partial` is a statement about **evidence coverage**, and a reader must not be
#: able to read it as 「板子没通过」 either.
DELIVERY_NOTE = (
    "delivery 只描述证据/交付覆盖，不是板级通过或不通过；"
    "它不改变 completion.verdict、summary.exitCode 或进程退出码。"
)

#: One fixed disclosure code per channel. A code is a stable machine handle —
#: changing one is a contract change, not a wording change.
DISCLOSURE_CODES: dict[str, str] = {
    CHANNEL_LIVE_SCHEMATIC: "live-schematic-evidence",
    CHANNEL_ARCHIVE_PCB: "archive-pcb-evidence",
    CHANNEL_LIVE_PCB: "live-pcb-evidence",
    CHANNEL_SCHEMATIC_IMAGE: "schematic-visual-review",
    CHANNEL_PCB_IMAGE: "pcb-visual-review",
    CHANNEL_DATASHEETS: "datasheet-evidence",
}

#: The heading both Markdown products print. Unnumbered for the same reason
#: `environment` is (537C2): the review-summary's 1/2/3/4 numbering is what the
#: SOP and `tests/test_069a` name.
EVIDENCE_HEADING = "## 证据覆盖（evidence）"

#: 537C3b2: the live capture merged into the section, at the root and **outside**
#: `channels`. It is metadata about the collection, not a seventh channel.
LIVE_CAPTURE_KEY = "liveCapture"

#: The capture's own schema id. A literal, not an import from
#: ``engines.liveevidence``: that module imports *this* one, so the reverse edge
#: would be a cycle.
LIVE_EVIDENCE_SCHEMA = "boardwise.live-evidence/1"

#: The four channels a live capture may replace. Archive and datasheet evidence
#: are never available from the live collector, so the merge must leave them
#: alone.
LIVE_CHANNEL_ORDER: tuple[str, ...] = (
    CHANNEL_LIVE_SCHEMATIC,
    CHANNEL_LIVE_PCB,
    CHANNEL_SCHEMATIC_IMAGE,
    CHANNEL_PCB_IMAGE,
)

#: The capture metadata copied — deep — into ``liveCapture``. Machine-auditable
#: collection facts only; the capture's own ``channels`` are already merged into
#: the ledger and are not duplicated here.
LIVE_CAPTURE_META_KEYS: tuple[str, ...] = (
    "schema",
    "ok",
    "executor",
    "identity",
    "selection",
    "focusRestore",
    "artifacts",
    "steps",
)

#: Two fixed disclosure codes that are **not** coverage channels. Identity and
#: focus restoration are collection facts, so they cannot be expressed as a
#: seventh and eighth channel without lying about the frozen six.
DISCLOSURE_IDENTITY_UNVERIFIED = "live-identity-unverified"
DISCLOSURE_FOCUS_RESTORE_FAILED = "live-focus-restore-failed"

#: The ``source`` an extra disclosure row carries. A reader can tell it apart
#: from a channel row without a `channel` value to dereference.
LIVE_CAPTURE_SOURCE = LIVE_CAPTURE_KEY

#: The offline tier id. A literal, not an import from `cli`, so this module has
#: no dependency on the CLI (the import would be circular and the id is frozen).
OFFLINE_TIER = "file"
ARCHIVE_TIERS: frozenset[str] = frozenset({"file", "project-file"})
NETLIST_TIER = "netlist"

#: `needs_datasheet[]`'s reviewer-mark trigger, as `engines.checkup` writes it.
#: Literal on purpose: this module must not import `checkup` (it is imported *by*
#: checkup for the shared renderer, so the reverse edge would be a cycle).
TRIGGER_MARKED = "marked"

#: `accepted_unknown[]`'s one state that is a **current** datasheet debt: the
#: engineer accepted an unknown and the part left this run's `unreviewed_parts`.
#: The other states are records, not debts — `stale` / `stale-elsewhere` point at
#: parts the drawing (or this board) no longer has, and `not-unreviewed` says the
#: part was already judged, so none of them may downgrade `datasheets` on its
#: own. Literals again: no import edge to `checkup`.
STATE_ACCEPTED = "accepted"
STATE_ACCEPTED_STALE = "stale"
STATE_ACCEPTED_STALE_ELSEWHERE = "stale-elsewhere"

#: The canvas-item metadata copied into `artifacts[]`. Only keys the item really
#: carries are copied — no invented width/height/page numbers.
_ARTIFACT_KEYS: tuple[str, ...] = (
    "page",
    "pageUuid",
    "board",
    "file",
    "bytes",
    "sha256",
    "source",
    "format",
    "pngError",
)


# ---------------------------------------------------------------------------
# channel rows
# ---------------------------------------------------------------------------


def _channel(
    status: str,
    source: str,
    detail: str,
    *,
    artifacts: Iterable[dict] | None = None,
    errors: Iterable[str] | None = None,
) -> dict:
    """One channel row in the frozen shape.

    ``steps`` is always present and empty in 537C3a: C3b's live collection will
    record per-step stdout/stderr/exit/error there, and the shape must not change
    under it.
    """
    if status not in CHANNEL_STATUSES:  # pragma: no cover — internal misuse
        raise ValueError(f"unknown evidence status: {status!r}")
    return {
        "status": status,
        "source": source,
        "detail": detail,
        "artifacts": [dict(row) for row in artifacts or []],
        "errors": [str(error) for error in errors or []],
        "steps": [],
    }


def _marked_parts(entries: Iterable[dict] | None) -> list[str]:
    """The distinct parts the reviewer marked, in report order (058 §二).

    The same predicate `engines.checkup.marked_parts` uses — one definition read
    twice, but this copy exists because importing `checkup` here would be a
    cycle. It counts **parts**, not pins: one datasheet answers a part.
    """
    out: list[str] = []
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("trigger") != TRIGGER_MARKED:
            continue
        part = str(entry.get("part") or "")
        if part and part not in out:
            out.append(part)
    return out


def _model_counts_text(components: int | None, nets: int | None) -> str:
    if components is None or nets is None:
        return ""
    return f"{components} 器件 / {nets} 网"


# ---------------------------------------------------------------------------
# the channels' frozen semantics
# ---------------------------------------------------------------------------


def _live_schematic(
    *, tier: str, model_empty: bool, components: int | None, nets: int | None
) -> dict:
    """Live schematic evidence — **archive is not live** (537C3a 主代理 H4).

    `project-file` / `per-page` only ever got an *archived* export; the original
    session's live schematic reading was a direct readback/netlist. So only the
    `netlist` tier (which reads `sch.netlist` / `sch.geometry` directly) may say
    ``ok``; the archive tiers say ``missing`` until C3b collects live evidence.
    An empty model on any online tier is ``failed``: an empty reading is not
    usable evidence. The offline tier never attempted a live read, so it is
    ``missing`` rather than ``failed``.
    """
    source = CHANNEL_SOURCES[CHANNEL_LIVE_SCHEMATIC]
    if tier == OFFLINE_TIER:
        return _channel(
            STATUS_MISSING,
            source,
            "离线文件（--file）：没有连编辑器，模型来自归档而不是实时回读，"
            "实时原理图证据未采集。",
        )
    if model_empty:
        return _channel(
            STATUS_FAILED,
            source,
            f"在线 tier {tier} 读回空模型（0 器件 0 网络）：空模型不是可用证据，"
            "不能当作已读原理图。",
        )
    if tier == NETLIST_TIER:
        counts = _model_counts_text(components, nets)
        return _channel(
            STATUS_OK,
            source,
            "在线网表档直接读 sch.netlist / sch.geometry"
            + (f"（{counts}）" if counts else "")
            + "：这是实时原理图证据。",
        )
    return _channel(
        STATUS_MISSING,
        source,
        f"当前只取得归档（tier {tier}），尚未直接实时原理图采集："
        "archive 不等于 live，实时原理图证据记为未采集（等 537C3b 独立采集）。",
    )


def _archive_pcb(
    *, tier: str, pcb_had_documents: bool | None, pcb_review: dict | None
) -> dict:
    """The archived PCB review (`pcb_review`), and the two absences kept apart.

    ``pcb_had_documents`` is **only trusted where the archive tiers actually
    read an archive**: `file` and `project-file`. On `per-page` / `netlist`
    there is no whole-project archive at all, so whether a PCB exists is
    *unknown* — and unknown is ``missing``, never ``not-applicable``.
    """
    source = CHANNEL_SOURCES[CHANNEL_ARCHIVE_PCB]
    boards: list = []
    available = False
    if isinstance(pcb_review, dict):
        boards = pcb_review.get("boards") or []
        available = pcb_review.get("available") is True
    if available and boards:
        artifacts = [
            {
                key: board.get(key)
                for key in ("title", "components", "copperLayers")
                if key in board
            }
            for board in boards
            if isinstance(board, dict)
        ]
        return _channel(
            STATUS_OK,
            source,
            f"归档 PCB 审查 {len(boards)} 块板：pcb_review.available=true 且 boards 非空，"
            "读数见 pcb_review 节。",
            artifacts=artifacts,
        )
    if pcb_review is not None:
        # A section that exists but cannot be read is not a missing channel: the
        # runner answered, and the answer is unusable.
        if not available:
            return _channel(
                STATUS_FAILED,
                source,
                "pcb_review 一节存在但 available 不是 true：归档 PCB 证据不可用。",
                errors=["pcb_review.available 不是 true"],
            )
        return _channel(
            STATUS_FAILED,
            source,
            "pcb_review 一节存在但 boards 为空：有 PCB 文档却没有任何板级读数，"
            "归档 PCB 证据不可用。",
            errors=["pcb_review.boards 为空"],
        )
    known = tier in ARCHIVE_TIERS and pcb_had_documents is not None
    if known and pcb_had_documents:
        return _channel(
            STATUS_FAILED,
            source,
            "归档里有 PCB 文档（pcb_had_documents=true）但本次没有 pcb_review 一节："
            "PCB 版面审查没有发生，归档 PCB 证据缺失。",
        )
    if known:
        return _channel(
            STATUS_NOT_APPLICABLE,
            source,
            "已确认没有 PCB 文档（pcb_had_documents=false 且没有 pcb_review 一节）："
            "没有可审的 PCB 版面，归档 PCB 通道不适用。",
        )
    return _channel(
        STATUS_MISSING,
        source,
        f"tier {tier} 没有整工程归档，是否存在 PCB 未知：归档 PCB 证据未采集——"
        "未知不是「没有 PCB」。",
    )


def _live_pcb(*, archive_status: str) -> dict:
    """Live PCB readback. 537C3a does not collect it; C3b will.

    A channel that was never attempted is ``missing`` when a PCB may exist, and
    ``not-applicable`` when the run confirmed there is no PCB at all. It is
    **never** ``ok`` from `pcb.drc_check` — the host DRC is a different reading,
    not a live board readback.
    """
    source = CHANNEL_SOURCES[CHANNEL_LIVE_PCB]
    if archive_status == STATUS_NOT_APPLICABLE:
        return _channel(
            STATUS_NOT_APPLICABLE,
            source,
            "已确认没有 PCB：没有可实时回读的 PCB，本通道不适用。",
        )
    return _channel(
        STATUS_MISSING,
        source,
        "未完成实时 PCB 回读：537C3a 不采集实时 PCB（pcb.drc_check 不等于 PCB 回读），"
        "PCB 结论只来自归档或完全没有；等 537C3b 独立采集。",
    )


def _pcb_image(*, archive_status: str) -> dict:
    """The PCB visual review. Not collected in 537C3a."""
    source = CHANNEL_SOURCES[CHANNEL_PCB_IMAGE]
    if archive_status == STATUS_NOT_APPLICABLE:
        return _channel(
            STATUS_NOT_APPLICABLE,
            source,
            "已确认没有 PCB：没有可复核的 PCB 版面，本通道不适用。",
        )
    return _channel(
        STATUS_MISSING,
        source,
        "未完成 PCB 视觉复核：本次没有 PCB 渲染图，PCB 版面没有经过视觉确认。",
    )


def _schematic_image(*, tier: str, canvas: Iterable[dict] | None) -> dict:
    """The live schematic image(s) rendered by the canvas stage.

    Offline, the geometry SVG draws a PCB — it is not a live schematic image, so
    the channel stays ``missing`` even when the canvas is full. Online, "a page
    did not render" and "the set rendered" are different claims: any error or any
    file-less entry makes the whole channel ``failed`` while the successful
    artifacts are still listed (a failure must not erase the evidence that did
    land), and a model with no canvas at all is ``failed`` too — the run had the
    model and produced no picture, which is not the same as "ok".
    """
    source = CHANNEL_SOURCES[CHANNEL_SCHEMATIC_IMAGE]
    if tier == OFFLINE_TIER:
        return _channel(
            STATUS_MISSING,
            source,
            "离线文件（--file）：离线几何 SVG 画的是 PCB 版面几何，不是实时原理图图，"
            "不能当作原理图视觉复核。",
        )
    items = [
        item
        for item in (canvas or [])
        if isinstance(item, dict) and (item.get("page") or item.get("pageUuid"))
    ]
    artifacts: list[dict] = []
    errors: list[str] = []
    for item in items:
        label = item.get("page") or item.get("pageUuid")
        if item.get("file"):
            artifacts.append(
                {key: item[key] for key in _ARTIFACT_KEYS if key in item}
            )
        if item.get("error"):
            errors.append(f"{label}: {item['error']}")
        elif not item.get("file"):
            errors.append(f"{label}: canvas 条目没有 file（render 未落盘）")
    if not items:
        return _channel(
            STATUS_FAILED,
            source,
            "本次在线已有模型，但一页画布图也没有拿到：原理图视觉复核未完成。",
        )
    if errors:
        return _channel(
            STATUS_FAILED,
            source,
            f"应出图 {len(items)} 页，其中 {len(errors)} 项失败或未落盘："
            "原理图视觉复核未完成（成功的图仍列在 artifacts）。",
            artifacts=artifacts,
            errors=errors,
        )
    return _channel(
        STATUS_OK,
        source,
        f"实时原理图图 {len(artifacts)} 页全部落盘；PNG 回退/渲染错误记录保留在 "
        "artifacts（有有效图即算落盘，不否认既有回退历史）。",
        artifacts=artifacts,
    )


def _datasheets(
    *,
    model_empty: bool,
    unreviewed: Iterable[dict] | None,
    accepted_unknown: Iterable[dict] | None,
    needs_datasheet: Iterable[dict] | None,
) -> dict:
    """The datasheet evidence gate, as a coverage channel.

    Four independent debts make it ``unavailable``; an engineer's
    ``accepted_unknown`` is **not** a verified datasheet (it is an accepted
    unknown), and a reviewer's mark is a debt whether or not the facts seed
    already listed the part.

    Only ``state == "accepted"`` counts from the accepted list: that is the row
    that really left this run's `unreviewed_parts`. A `stale` /
    `stale-elsewhere` / `not-unreviewed` row is a **record**, not a current gap —
    it stays visible in the detail (and in the existing sections) but must not
    downgrade the channel on its own.

    The detail keeps the counts **apart** and does not sum them into a
    「唯一器件数」 — the same part can be in more than one list, and the three are
    three different jobs.
    """
    source = CHANNEL_SOURCES[CHANNEL_DATASHEETS]
    unreviewed_count = len(list(unreviewed or []))
    accepted_rows = [row for row in (accepted_unknown or []) if isinstance(row, dict)]
    accepted_count = sum(
        1 for row in accepted_rows if str(row.get("state")) == STATE_ACCEPTED
    )
    stale_count = sum(
        1 for row in accepted_rows
        if str(row.get("state")) in (STATE_ACCEPTED_STALE, STATE_ACCEPTED_STALE_ELSEWHERE)
    )
    marked_count = len(_marked_parts(needs_datasheet))
    counts = (
        f"未审 {unreviewed_count} 条 / 工程师接受未审（本轮缺口）{accepted_count} 条 / "
        f"审查者标记 {marked_count} 个器件（三类是不同来源的欠账，不相加，"
        "也不等于手册已核）"
    )
    if stale_count:
        counts += (
            f"；另有 {stale_count} 条接受记录是 stale/stale-elsewhere（失效记录，"
            "仍披露，但不构成本轮手册缺口）"
        )
    if model_empty:
        return _channel(
            STATUS_UNAVAILABLE,
            source,
            f"空模型（0 器件 0 网络）不能提供手册证据；{counts}。",
        )
    if unreviewed_count or accepted_count or marked_count:
        return _channel(
            STATUS_UNAVAILABLE,
            source,
            f"手册证据未齐/待核：{counts}；相关规格结论只能待核。",
        )
    return _channel(
        STATUS_OK,
        source,
        f"本报告没有手册欠账（{counts}）；没有欠账不等于每颗器件都逐页核过手册，"
        "只表示本闸没有未决项。",
    )


# ---------------------------------------------------------------------------
# coverage / delivery — derived, one direction only
# ---------------------------------------------------------------------------


def evidence_coverage(channels: dict | None) -> dict:
    """The status map, **derived from** ``channels`` (537C3a §一).

    A caller that needs "which channels are ok" reads this, and it cannot
    disagree with the rows above because it is computed from them. An unknown
    channel id in ``channels`` is ignored; a missing one reads ``missing`` (an
    absent row is not a pass).
    """
    channels = channels or {}
    return {
        name: str((channels.get(name) or {}).get("status") or STATUS_MISSING)
        for name in CHANNEL_ORDER
    }


def _disclosure_message(channel: str, status: str, detail: str) -> str:
    """One specific sentence per open channel — what the gap costs.

    The three high-risk channels are spelled out (537C3a §二): live PCB is
    「未完成实时 PCB 回读」, PCB image is 「未完成 PCB 视觉复核」, datasheets is
    「手册证据未齐/待核」. The rest fall back to the channel's own detail, which
    is real collection information rather than a second opinion.
    """
    fixed = {
        (CHANNEL_LIVE_SCHEMATIC, STATUS_FAILED): (
            "实时原理图回读得到空模型（0 器件 0 网络）：空模型不是可用证据，"
            "不能当作已读原理图。"
        ),
        (CHANNEL_LIVE_SCHEMATIC, STATUS_MISSING): (
            "未采集实时原理图证据：本次只取得归档或离线文件，archive 不等于 live。"
        ),
        (CHANNEL_ARCHIVE_PCB, STATUS_FAILED): (
            "归档 PCB 证据缺失：归档里有 PCB 文档但没有可读的 pcb_review 读数，"
            "PCB 版面审查没有完成。"
        ),
        (CHANNEL_ARCHIVE_PCB, STATUS_MISSING): (
            "归档 PCB 证据未采集：本次没有整工程归档，是否存在 PCB 未知——"
            "未知不是「没有 PCB」。"
        ),
        (CHANNEL_LIVE_PCB, STATUS_MISSING): (
            "未完成实时 PCB 回读：本次没有从编辑器实时读取 PCB，"
            "PCB 结论只来自归档或完全没有。"
        ),
        (CHANNEL_SCHEMATIC_IMAGE, STATUS_FAILED): (
            "原理图视觉复核未完成：本次有模型但画布图缺失或渲染失败。"
        ),
        (CHANNEL_SCHEMATIC_IMAGE, STATUS_MISSING): (
            "未采集实时原理图图：离线几何图是 PCB 版面几何，不是实时原理图图。"
        ),
        (CHANNEL_PCB_IMAGE, STATUS_MISSING): (
            "未完成 PCB 视觉复核：本次没有 PCB 渲染图，PCB 版面没有经过视觉确认。"
        ),
        (CHANNEL_DATASHEETS, STATUS_UNAVAILABLE): (
            "手册证据未齐/待核：仍有器件缺已核验的手册事实（含工程师接受未审、"
            "审查者标记与空模型），相关规格结论只能待核，不能写成已与手册核对。"
        ),
    }
    return fixed.get((channel, status)) or f"{channel} 的证据状态是 {status}：{detail}"


def _error_reason(error: object) -> str:
    """The readable part of a capture error, keeping its code (a disclosure with
    only「失败」would not tell a reader what to fix)."""
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        message = str(error.get("message") or "")
        if code and message:
            return f"{code}: {message}"
        if code or message:
            return code or message
        return ""
    if error:
        return str(error)
    return ""


def _live_capture_disclosures(live_capture: object) -> list[dict]:
    """The two non-channel disclosures a live capture owes, in frozen order.

    Identity first, focus second. Both are derived from the capture itself, not
    from ``capture.ok``: a verified project and a restored tab are facts, and a
    coarse "ok" cannot stand in for either. A capture without an identity record
    is unverified (never a silent pass); a focus record whose ``ok`` is not
    ``True`` is disclosed even when ``attempted`` is false or its status is
    ``unavailable`` — the editor's original tab is still not proven restored.

    Only ``None`` means "this report predates live collection" and owes nothing.
    Any other present value — ``{}``, or a non-dict — is an untrusted record and
    fails closed with both disclosures; an empty record must not read ``complete``.
    """
    if live_capture is None:
        # The one value that means "this report predates live collection".
        return []
    if not isinstance(live_capture, dict):
        # Present but unusable is not absent: fail closed below, with both
        # disclosures, rather than treating an unreadable record as no capture.
        live_capture = {}

    rows: list[dict] = []
    identity = live_capture.get("identity")
    if not isinstance(identity, dict) or identity.get("verifiedAgainstReport") is not True:
        identity = identity if isinstance(identity, dict) else {}
        error = identity.get("error")
        status = STATUS_FAILED if error else STATUS_MISSING
        reason = _error_reason(error) or "未记录可核实的期望工程身份"
        ids = [
            f"{key}={identity[key]}"
            for key in ("expectedProjectUuid", "projectUuid")
            if identity.get(key)
        ]
        ids_text = f"；{'，'.join(ids)}" if ids else ""
        rows.append({
            "code": DISCLOSURE_IDENTITY_UNVERIFIED,
            "channel": None,
            "source": LIVE_CAPTURE_SOURCE,
            "status": status,
            "message": (
                "工程身份未核实：本次实时采集没有证明焦点工程与本报告是同一报告/"
                f"同一设计（{reason}{ids_text}）。identity.ok / capture.ok 不能抵消"
                "本项披露，delivery 至少为 partial。"
            ),
        })

    focus = live_capture.get("focusRestore")
    focus_row = focus if isinstance(focus, dict) else {}
    if focus_row.get("ok") is not True:
        reason = _error_reason(focus_row.get("error")) or "未记录恢复错误"
        rows.append({
            "code": DISCLOSURE_FOCUS_RESTORE_FAILED,
            "channel": None,
            "source": LIVE_CAPTURE_SOURCE,
            "status": STATUS_FAILED,
            "message": (
                f"原焦点未恢复：{reason}（attempted={focus_row.get('attempted')}，"
                f"status={focus_row.get('status')}）。即使未尝试恢复或状态为 "
                "unavailable，本项也必须披露；capture.ok 不能抵消，delivery 至少为 "
                "partial。"
            ),
        })
    return rows


def evidence_delivery(
    channels: dict | None, live_capture: dict | None = None
) -> dict:
    """The delivery reading, derived from the channels **and** the live capture.

    ``complete`` only when **every** channel is ``ok`` or ``not-applicable``
    **and** the live capture has no non-channel disclosure; anything else is
    ``partial``. It carries one ``requiredDisclosures[]`` row per open channel,
    in the frozen channel order, then — when a capture is present — the identity
    disclosure and the focus-restore disclosure, in that order. This is a
    reading about evidence coverage and never a board-level pass/fail.

    ``live_capture=None`` is exactly the 537C3a behaviour: six channels only.
    """
    channels = channels or {}
    coverage = evidence_coverage(channels)
    disclosures: list[dict] = []
    for name in CHANNEL_ORDER:
        status = coverage[name]
        if status in CLOSED_STATUSES:
            continue
        row = channels.get(name) or {}
        disclosures.append({
            "code": DISCLOSURE_CODES[name],
            "channel": name,
            "status": status,
            "message": _disclosure_message(
                name, status, str(row.get("detail") or "")
            ),
        })
    disclosures.extend(_live_capture_disclosures(live_capture))
    return {
        "status": DELIVERY_COMPLETE if not disclosures else DELIVERY_PARTIAL,
        "note": DELIVERY_NOTE,
        "requiredDisclosures": disclosures,
    }


# ---------------------------------------------------------------------------
# 537C3b2: merging one live capture into an existing section
# ---------------------------------------------------------------------------


def _validated_rows(
    section: object,
    *,
    schema: str,
    required: tuple[str, ...],
    label: str,
) -> dict:
    """The rows a merge is allowed to trust, or ``ValueError``.

    A merge may not repair a broken section: an unknown status or a missing row
    is a caller bug (or a report from another schema), and guessing here would
    put an invented reading beside real evidence. The CLI maps ``ValueError`` to
    exit 2.
    """
    if not isinstance(section, dict) or not section:
        raise ValueError(f"{label} 必须是完整 section（dict），不能为空")
    if section.get("schema") != schema:
        raise ValueError(
            f"{label}.schema 必须是 {schema!r}，实际是 {section.get('schema')!r}"
        )
    channels = section.get("channels")
    if not isinstance(channels, dict):
        raise ValueError(f"{label}.channels 必须是 dict")
    rows: dict = {}
    for name in required:
        row = channels.get(name)
        if not isinstance(row, dict):
            raise ValueError(f"{label}.channels[{name!r}] 缺失或不是 dict")
        status = row.get("status")
        if status not in CHANNEL_STATUSES:
            raise ValueError(
                f"{label}.channels[{name!r}].status 非法：{status!r}；"
                f"合法状态是 {CHANNEL_STATUSES}"
            )
        rows[name] = row
    return rows


def _validated_capture_meta(capture: dict) -> dict:
    """The capture metadata the section will carry, or ``ValueError``.

    Identity and focus restoration drive disclosures, so a capture without them
    cannot be merged: treating a missing read as "unverified" would be an
    invented answer rather than the collector's record.
    """
    missing = [key for key in LIVE_CAPTURE_META_KEYS if key not in capture]
    if missing:
        raise ValueError(f"capture 缺元数据字段：{', '.join(missing)}")
    for key in ("identity", "focusRestore"):
        if not isinstance(capture[key], dict):
            raise ValueError(f"capture[{key!r}] 必须是 dict")
    for key in ("artifacts", "steps"):
        if not isinstance(capture[key], list):
            raise ValueError(f"capture[{key!r}] 必须是 list")
    return capture


def _merged_live_row(channel: str, row: dict) -> dict:
    """One live channel row in the frozen six-key shape, deep-copied."""
    artifacts = row.get("artifacts")
    errors = row.get("errors")
    steps = row.get("steps")
    return {
        "status": row["status"],
        "source": str(row.get("source") or CHANNEL_SOURCES[channel]),
        "detail": str(row.get("detail") or ""),
        "artifacts": copy.deepcopy(artifacts) if isinstance(artifacts, list) else [],
        "errors": [str(error) for error in errors] if isinstance(errors, list) else [],
        "steps": copy.deepcopy(steps) if isinstance(steps, list) else [],
    }


def merge_live_capture(evidence: dict | None, capture: dict) -> dict:
    """Merge one ``boardwise.live-evidence/1`` capture into an evidence section.

    Pure: neither argument is mutated, and the returned section owns its rows
    and metadata (deep copies). Only the four live channels are replaced —
    ``archivePcb`` and ``datasheets`` stay verbatim — ``coverage`` is recomputed
    from the six rows, ``delivery`` is recomputed with the capture's identity and
    focus disclosures, and the capture metadata is stored at
    ``liveCapture`` (outside ``channels``). The capture's own ``ok`` is copied,
    never recomputed and never read as a board-level conclusion.
    """
    evidence_rows = _validated_rows(
        evidence, schema=EVIDENCE_SCHEMA, required=CHANNEL_ORDER, label="evidence"
    )
    capture_rows = _validated_rows(
        capture,
        schema=LIVE_EVIDENCE_SCHEMA,
        required=LIVE_CHANNEL_ORDER,
        label="capture",
    )
    _validated_capture_meta(capture)

    live_capture = {
        key: copy.deepcopy(capture[key]) for key in LIVE_CAPTURE_META_KEYS
    }
    channels = {
        name: copy.deepcopy(evidence_rows[name]) for name in CHANNEL_ORDER
    }
    for name in LIVE_CHANNEL_ORDER:
        channels[name] = _merged_live_row(name, capture_rows[name])
    return {
        "schema": EVIDENCE_SCHEMA,
        "channels": channels,
        "coverage": evidence_coverage(channels),
        "delivery": evidence_delivery(channels, live_capture=live_capture),
        LIVE_CAPTURE_KEY: live_capture,
    }


# ---------------------------------------------------------------------------
# the section builder (537C3a: what `checkup` actually collected)
# ---------------------------------------------------------------------------


def evidence_section(
    *,
    tier: str,
    model_empty: bool = False,
    model_components: int | None = None,
    model_nets: int | None = None,
    pcb_had_documents: bool | None = None,
    pcb_review: dict | None = None,
    canvas: Iterable[dict] | None = None,
    unreviewed: Iterable[dict] | None = None,
    accepted_unknown: Iterable[dict] | None = None,
    needs_datasheet: Iterable[dict] | None = None,
) -> dict:
    """Assemble the section from what the run **really** collected.

    Every input is a value the caller already holds — no section is guessed from
    ``source.notes`` prose. ``pcb_had_documents`` is ``True``/``False`` when the
    run actually read an archive, ``None`` when it did not (unknown, not absent).
    ``canvas`` is the canvas stage's own item list (file/bytes/sha256/error), and
    the three datasheet lists are the report's own sections.
    """
    archive = _archive_pcb(
        tier=tier, pcb_had_documents=pcb_had_documents, pcb_review=pcb_review
    )
    channels = {
        CHANNEL_LIVE_SCHEMATIC: _live_schematic(
            tier=tier,
            model_empty=model_empty,
            components=model_components,
            nets=model_nets,
        ),
        CHANNEL_ARCHIVE_PCB: archive,
        CHANNEL_LIVE_PCB: _live_pcb(archive_status=archive["status"]),
        CHANNEL_SCHEMATIC_IMAGE: _schematic_image(tier=tier, canvas=canvas),
        CHANNEL_PCB_IMAGE: _pcb_image(archive_status=archive["status"]),
        CHANNEL_DATASHEETS: _datasheets(
            model_empty=model_empty,
            unreviewed=unreviewed,
            accepted_unknown=accepted_unknown,
            needs_datasheet=needs_datasheet,
        ),
    }
    return {
        "schema": EVIDENCE_SCHEMA,
        "channels": channels,
        "coverage": evidence_coverage(channels),
        "delivery": evidence_delivery(channels),
    }


def refresh_datasheets(
    evidence: dict | None,
    *,
    model_empty: bool = False,
    unreviewed: Iterable[dict] | None = None,
    accepted_unknown: Iterable[dict] | None = None,
    needs_datasheet: Iterable[dict] | None = None,
) -> dict | None:
    """Recompute the **datasheets** channel after a re-gate, in place.

    `boardwise need-datasheet` adds a reviewer mark to an existing report and
    re-renders it. The report's own `needs_datasheet[]` section changes, so a
    ledger that still said ``datasheets: ok`` would be the exact drift this
    section exists to stop. Only that one channel can move on a re-gate (no
    model, canvas or PCB was re-read), and coverage/delivery are recomputed from
    the rows — not patched by hand.

    A report built before 537C3a has no section: ``None`` in, ``None`` out, and
    nothing is invented.

    537C3b2: an existing ``liveCapture`` is carried through untouched and
    passed to :func:`evidence_delivery`, so the identity / focus disclosures a
    re-gate did not re-collect are not silently dropped when delivery is
    recomputed.
    """
    if not isinstance(evidence, dict) or not evidence:
        return evidence
    channels = dict(evidence.get("channels") or {})
    channels[CHANNEL_DATASHEETS] = _datasheets(
        model_empty=model_empty,
        unreviewed=unreviewed,
        accepted_unknown=accepted_unknown,
        needs_datasheet=needs_datasheet,
    )
    evidence["channels"] = channels
    evidence["coverage"] = evidence_coverage(channels)
    # 537C3b2: the identity / focus disclosures come from `liveCapture`, which a
    # re-gate must keep. Recomputing delivery from channels alone would silently
    # drop them exactly when the report is being re-rendered.
    evidence["delivery"] = evidence_delivery(
        channels, live_capture=evidence.get(LIVE_CAPTURE_KEY)
    )
    return evidence


def default_evidence(
    *,
    tier: str,
    model_section: dict | None = None,
    pcb_had_documents: bool | None = None,
    pcb_review: dict | None = None,
    unreviewed: Iterable[dict] | None = None,
    accepted_unknown: Iterable[dict] | None = None,
    needs_datasheet: Iterable[dict] | None = None,
) -> dict:
    """The fallback builder for a caller that has no canvas reading (a hand-built
    report, an older re-gate path).

    Deliberately **not** a second truth: it fills the channels it can from the
    report's own sections and leaves the rest ``missing`` where the run could not
    have collected them. `_cmd_checkup` does not use this — it passes the real
    canvas / pcb / datasheet inputs to :func:`evidence_section`.
    """
    section = model_section or {}
    components = section.get("components")
    nets = section.get("nets")
    # `None` counts mean "the caller did not say", which is not "empty": an
    # unknown model must not be reported as an empty-model failure.
    model_empty = components == 0 and nets == 0
    return evidence_section(
        tier=tier,
        model_empty=model_empty,
        model_components=components if isinstance(components, int) else None,
        model_nets=nets if isinstance(nets, int) else None,
        pcb_had_documents=pcb_had_documents,
        pcb_review=pcb_review,
        canvas=None,
        unreviewed=unreviewed,
        accepted_unknown=accepted_unknown,
        needs_datasheet=needs_datasheet,
    )


# ---------------------------------------------------------------------------
# renderings: Markdown (report.md + review-summary.md) and the console line
# ---------------------------------------------------------------------------


def _artifact_text(artifact: dict) -> str:
    return "、".join(f"{key}={value}" for key, value in artifact.items())


def render_evidence_markdown(
    evidence: object, *, heading: str = EVIDENCE_HEADING
) -> list[str]:
    """The section as Markdown lines, shared by `report.md` and `review-summary.md`.

    **Empty in, empty out**: a report built before this section existed (or by a
    hand-built test) renders exactly what it rendered before — the old rendering
    is the compatibility promise.

    Bullets only, deliberately: the review-summary's row arithmetic counts
    ``|``-lines, and a table here would be read as findings rows.
    """
    if not isinstance(evidence, dict) or not evidence:
        return []
    channels = evidence.get("channels") or {}
    coverage = evidence.get("coverage") or evidence_coverage(channels)
    delivery = evidence.get("delivery") or evidence_delivery(
        channels, live_capture=evidence.get(LIVE_CAPTURE_KEY)
    )
    lines = [
        heading,
        "",
        f"- 交付覆盖（delivery）：`{delivery.get('status')}` —— {delivery.get('note')}",
        "- 覆盖（coverage，由 channels 派生）："
        + "、".join(f"`{name}={coverage.get(name)}`" for name in CHANNEL_ORDER),
        "- 通道（channels，固定顺序）：",
    ]
    for name in CHANNEL_ORDER:
        row = channels.get(name) or {}
        lines.append(
            f"  - `{name}`（source `{row.get('source') or CHANNEL_SOURCES[name]}`）："
            f"`{row.get('status') or coverage.get(name)}` —— {row.get('detail') or ''}"
        )
        for artifact in row.get("artifacts") or []:
            lines.append(f"    - artifact：{_artifact_text(artifact)}")
        for error in row.get("errors") or []:
            lines.append(f"    - error：{error}")
        for step in row.get("steps") or []:
            lines.append(f"    - step：{step}")
    disclosures = delivery.get("requiredDisclosures") or []
    if disclosures:
        lines.append("- 必披露（requiredDisclosures）：")
        for row in disclosures:
            channel = row.get("channel")
            if channel:
                scope = f"`{channel}`"
            else:
                # 537C3b2: identity/focus rows carry no channel, so printing
                # `channel=None` would be both ugly and misleading. Their
                # `source` is the honest scope.
                scope = f"`{row.get('source') or LIVE_CAPTURE_SOURCE}`"
            lines.append(
                f"  - `{row.get('code')}`（{scope}："
                f"`{row.get('status')}`）—— {row.get('message')}"
            )
    else:
        lines.append("- 必披露（requiredDisclosures）：无——六通道均为 ok 或 not-applicable")
    lines.append("")
    return lines


def evidence_console_line(evidence: object) -> str:
    """The one-line console summary, or ``''`` when the section is absent.

    Read **from the section**: the delivery status and the open-channel list are
    derived from the ledger, not hard-coded, so the console cannot disagree with
    `report.json`. Only channels that are neither ``ok`` nor ``not-applicable``
    are listed — those are the ones a reader has to act on. 537C3b2 adds the
    capture's non-channel disclosure codes to that list, so six closed channels
    plus an unverified identity is not a bare, context-free ``partial``.
    """
    if not isinstance(evidence, dict) or not evidence:
        return ""
    channels = evidence.get("channels") or {}
    coverage = evidence.get("coverage") or evidence_coverage(channels)
    delivery = evidence.get("delivery") or evidence_delivery(
        channels, live_capture=evidence.get(LIVE_CAPTURE_KEY)
    )
    open_rows = [
        f"{name}={coverage[name]}"
        for name in CHANNEL_ORDER
        if coverage[name] not in CLOSED_STATUSES
    ]
    # 537C3b2: a capture's identity/focus disclosures are not channels, so they
    # are printed by their fixed code. Without this, six closed channels plus a
    # disclosure would print a bare `partial` with no context.
    extra_codes = [
        str(row.get("code"))
        for row in (delivery.get("requiredDisclosures") or [])
        if isinstance(row, dict) and not row.get("channel") and row.get("code")
    ]
    status = delivery.get("status")
    if status not in (DELIVERY_COMPLETE, DELIVERY_PARTIAL):
        status = (
            DELIVERY_COMPLETE
            if not open_rows and not extra_codes
            else DELIVERY_PARTIAL
        )
    elif extra_codes and status == DELIVERY_COMPLETE:
        # A stale `complete` cannot survive a disclosure it forgot; the ledger
        # must not print `complete (live-identity-unverified)`.
        status = DELIVERY_PARTIAL
    parts = open_rows + extra_codes
    # `complete` has nothing to list: printing an empty `()` would read like a
    # channel called nothing. `partial` always lists every open channel and every
    # extra disclosure code.
    if not parts:
        return f"evidence: {status}"
    return f"evidence: {status} ({', '.join(parts)})"
