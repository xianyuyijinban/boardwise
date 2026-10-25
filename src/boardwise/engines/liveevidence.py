"""537C3b1: independent live evidence collection for one editor window.

Why this module exists. The 537 review's live PCB reading was a hand-written
shell loop: `doc.open` then `pcb.readback` then `pcb.geometry` then
`export.render`, chained with `&&`-like assumptions. A render failure erased a
readback that had succeeded, a timeout after `doc.open` left the editor on a
different page while the next action read it, and the original tab was never put
back. The report then had one coarse "live PCB failed" with no per-step record.

So this module collects live evidence **once**, step by step, and returns a
JSON-serialisable capture:

* ``identity`` — the focused project from ``doc.list`` compared with the
  report's expectation. A mismatch (or an unreadable expectation) is a
  structured refusal **before any navigation**; an empty expectation collects
  but never claims the design was verified (``verifiedAgainstReport: false``).
* ``selection`` — which schematic pages / PCBs were requested, which unknown ids
  were rejected before navigation, and whether the selection covered **all**
  documents of that type. An explicit subset that succeeded is ``missing`` in the
  channel, never ``ok``: it is coverage, not evidence quality.
* ``steps`` — one row per action:
  ``{documentUuid, action, status, stdout, stderr, exitCode, error}`` with
  ``status`` in ``ok / failed / skipped``, ``exitCode`` 0 / 1 / null, stdout a
  truncated JSON rendering (≤2000 chars), and ``executor: bridge-client`` at the
  capture level. There is no shell and no shell exit code to launder: an action
  that returned 0 but whose evidence is unusable (readback ``problems`` /
  ``unreadable``, geometry ``meta.unreadable``, an empty netlist, a non-PNG
  render) is a **failed step**.
* ``channels`` — only the four live channels
  (``liveSchematic / livePcb / schematicImage / pcbImage``), in the same row
  shape as 537C3a's ledger (``status / source / detail / artifacts / errors /
  steps``). Archive and datasheet channels are deliberately not fabricated.
* ``artifacts`` — every file written, relative to ``out_dir``, with byte count
  and sha256; images only after ``format == image/png`` + non-empty valid base64
  (a zip container or a broken payload is never written).
* ``focusRestore`` — the original tab, restored in ``finally`` and verified
  again through ``document.current``. A failed restore is disclosed
  (``ok: false`` + ``error``) and makes ``capture.ok`` false.

Focus safety is the hard part, so it is mechanical: before the first action on
a document, ``doc.open`` is called and then ``document.current`` is read
independently. Only its real ``active.uuid`` (connector ``documentCurrent``)
counts as proof; a missing ``active`` or non-empty ``problems`` is *not*
verified. A document whose focus cannot be proven gets its remaining steps
``skipped`` — nothing is read from the wrong page — while the other documents
continue. If the original ``active.uuid`` is unreadable and any document must be
opened, the whole collection refuses **before** navigation: an editor state that
cannot be restored must not be moved.

What this module is not: a CLI, a gate, or the owner of the client. It never
opens or closes the client (the CLI owns its lifetime), never runs a shell, and
never touches a real project. It imports only constants from
``engines.evidence``; it does not import ``engines.checkup`` or ``cli``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from .evidence import (
    CHANNEL_LIVE_PCB,
    CHANNEL_LIVE_SCHEMATIC,
    CHANNEL_PCB_IMAGE,
    CHANNEL_SCHEMATIC_IMAGE,
    CHANNEL_SOURCES,
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_NOT_APPLICABLE,
    STATUS_OK,
)

#: The capture's own schema id. A capture is one run's collection record; it is
#: not a checkup report and its id never bumps for a report change.
LIVE_EVIDENCE_SCHEMA = "boardwise.live-evidence/1"

#: Every step's executor. There is no shell process: one `client.call` is one
#: action and the action's own answer is the only status there is.
LIVE_EVIDENCE_EXECUTOR = "bridge-client"

#: The four live channels, in the frozen order the report reads them.
LIVE_CHANNEL_ORDER: tuple[str, ...] = (
    CHANNEL_LIVE_SCHEMATIC,
    CHANNEL_LIVE_PCB,
    CHANNEL_SCHEMATIC_IMAGE,
    CHANNEL_PCB_IMAGE,
)

#: `stdout` is the JSON rendering of an action's answer, capped. The cap is a
#: contract (a step row must not grow a full page render into the capture).
STEP_STDOUT_LIMIT = 2000

#: One page render's leash. A correct render answers in ~100–200 ms; 10 s also
#: keeps a hung host (pit 23) from freezing the editor's progress toast for
#: longer than a human should wait.
RENDER_TIMEOUT_MS = 10_000

#: The only render payload this module accepts as an image.
RENDER_FORMAT = "image/png"

#: The 8-byte PNG signature. A payload that merely *claims* `image/png` in a
#: well-formed base64 string is not a picture; only these bytes are.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: The netlist flavour the connector's own vocabulary uses.
NETLIST_TYPE = "EasyEDA"

#: The statuses that close a live channel (same vocabulary as 537C3a).
CLOSED_STATUSES: frozenset[str] = frozenset({STATUS_OK, STATUS_NOT_APPLICABLE})

#: Actions each channel's row carries as its own steps (restore steps are
#: deliberately excluded: they belong to the capture, not to a reading).
_CHANNEL_ACTIONS: dict[str, frozenset[str]] = {
    CHANNEL_LIVE_SCHEMATIC: frozenset(
        {"doc.open", "document.current", "sch.readback", "sch.netlist"}
    ),
    CHANNEL_LIVE_PCB: frozenset(
        {"doc.open", "document.current", "pcb.readback", "pcb.geometry"}
    ),
    CHANNEL_SCHEMATIC_IMAGE: frozenset(
        {"doc.open", "document.current", "export.render"}
    ),
    CHANNEL_PCB_IMAGE: frozenset(
        {"doc.open", "document.current", "export.render"}
    ),
}

#: Per-document actions a channel needs to be `ok`.
_REQUIRED_ACTIONS: dict[str, tuple[str, ...]] = {
    CHANNEL_LIVE_SCHEMATIC: ("doc.open", "document.current", "sch.readback"),
    CHANNEL_LIVE_PCB: (
        "doc.open", "document.current", "pcb.readback", "pcb.geometry"
    ),
    CHANNEL_SCHEMATIC_IMAGE: ("doc.open", "document.current", "export.render"),
    CHANNEL_PCB_IMAGE: ("doc.open", "document.current", "export.render"),
}


# ---------------------------------------------------------------------------
# small value helpers
# ---------------------------------------------------------------------------


def _error(code: str, message: str, **extra: Any) -> dict:
    row = {"code": code, "message": message}
    row.update(extra)
    return row


def _error_text(error: dict) -> str:
    return f"{error.get('code')}: {error.get('message')}"


def _exception_error(exc: BaseException) -> dict:
    """A bridge error's own code/message, or the exception class as a code.

    Duck-typed on purpose: importing the bridge client here would pull the
    websocket stack into an engine module and invite a cycle. A real
    ``BridgeError`` carries ``code`` / ``message``; anything else is named by
    its type so a crash is never silently flattened into「失败」.
    """
    code = str(getattr(exc, "code", "") or type(exc).__name__)
    message = str(getattr(exc, "message", "") or exc) or type(exc).__name__
    return _error(code, message)


def _stdout(payload: Any) -> str:
    """A truncated JSON rendering of an action's answer (≤2000 chars)."""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = json.dumps(str(payload), ensure_ascii=False)
    return text[:STEP_STDOUT_LIMIT]


def _step(
    document_uuid: str,
    action: str,
    status: str,
    *,
    stdout: str = "",
    stderr: str = "",
    error: dict | None = None,
) -> dict:
    exit_code = 0 if status == STATUS_OK else 1 if status == STATUS_FAILED else None
    return {
        "documentUuid": str(document_uuid or ""),
        "action": action,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": exit_code,
        "error": error,
    }


def _nonempty(value: Any) -> bool:
    """True when a payload field is present and says something.

    ``unreadable`` is a **count** in readback (0 = clean) but a list of reasons
    in geometry, so both numeric and container shapes are read here.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        return len(value) > 0
    return bool(value)


def _safe_stem(name: Any, fallback: str = "page") -> str:
    """The file-name stem rule ``cli._file_stem`` uses (031), reproduced here.

    Reproduced rather than imported: this engine module must not import the CLI.
    """
    stem = re.sub(r"[^A-Za-z0-9._\u4e00-\u9fff-]+", "_", str(name or "")).strip("_")
    return stem[:48] or fallback


def _short_uuid(uuid: Any) -> str:
    """A file-name-safe suffix that keeps two same-named documents apart."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(uuid or ""))[:8]
    if cleaned:
        return cleaned
    return hashlib.sha256(str(uuid).encode("utf-8")).hexdigest()[:8]


def _write_unique(out_dir: Path, stem: str, suffix: str, blob: bytes) -> str:
    """Write ``blob`` under a name that cannot overwrite an existing file.

    Returns the path **relative to ``out_dir``** — the reader of a capture sits
    beside the files, so a machine-specific absolute path would be useless.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate = out_dir / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    candidate.write_bytes(blob)
    return candidate.name


# ---------------------------------------------------------------------------
# reading the listing (doc.list) — identity, documents, selection
# ---------------------------------------------------------------------------


def _focused_project_uuid(listing: Any) -> str:
    if not isinstance(listing, dict):
        return ""
    for row in listing.get("projects") or []:
        if isinstance(row, dict) and row.get("focused") is True:
            uuid = str(row.get("projectUuid") or "")
            if uuid:
                return uuid
    return ""


def _active_uuid(listing: Any) -> str:
    if not isinstance(listing, dict):
        return ""
    active = listing.get("active")
    if not isinstance(active, dict):
        return ""
    return str(active.get("uuid") or "")


def _listing_valid(listing: Any) -> bool:
    """Whether ``doc.list`` returned the document tree this collector needs.

    ``documents`` must be a **list**. A missing key, a string (the non-focused
    project brief) or a non-dict answer means the document set is *unknown* —
    never "confirmed no PCB / no schematic page". Unknown must not be promoted
    to ``not-applicable`` / ``failed``: those claim something was confirmed.
    """
    return isinstance(listing, dict) and isinstance(listing.get("documents"), list)


def _listing_error(listing: Any) -> dict | None:
    """The step-level check for ``doc.list`` (exit 0 is not a usable answer)."""
    if not isinstance(listing, dict):
        return _error("DOC_LIST_INVALID", "doc.list 没有返回对象：文档清单未知")
    if not isinstance(listing.get("documents"), list):
        return _error(
            "DOC_LIST_INVALID",
            "doc.list 没有 documents 数组：文档清单未知（不能按「没有 PCB/原理图页」处理）",
        )
    return None


def _documents(listing: Any) -> list[dict]:
    """The listing's documents, normalised to ``schematic`` / ``pcb``.

    Only these two kinds are collectable. Unknown kinds are left out rather than
    guessed at; a uuid of the wrong kind is consequently an unknown id for the
    kind the caller asked about (and is rejected before navigation).
    """
    if not isinstance(listing, dict):
        return []
    raw_documents = listing.get("documents")
    if not isinstance(raw_documents, list):
        return []
    rows: list[dict] = []
    for row in raw_documents:
        if not isinstance(row, dict):
            continue
        uuid = str(row.get("uuid") or "")
        if not uuid:
            continue
        raw_type = str(row.get("type") or "")
        if raw_type == "pcb":
            kind = "pcb"
        elif raw_type in ("page", "schematic"):
            kind = "schematic"
        else:
            continue
        rows.append(
            {
                "uuid": uuid,
                "name": str(row.get("name") or row.get("title") or uuid),
                "type": kind,
            }
        )
    return rows


def _requested_ids(requested: Iterable[str] | None) -> list[str] | None:
    """An explicit selection, deduplicated in request order; ``None`` = all."""
    if requested is None:
        return None
    out: list[str] = []
    for value in requested:
        uuid = str(value or "")
        if uuid and uuid not in out:
            out.append(uuid)
    return out


def _selection_row(
    documents: list[dict], requested: list[str] | None
) -> dict:
    """One kind's selection, including whether it covered every document.

    ``coversAll`` is set equality between the chosen ids and the documents the
    listing actually has. It is deliberately **false** for an empty project: a
    type with no document is not "fully covered", it is "nothing to collect"
    (the channel decides between failed and not-applicable).
    """
    available = [row["uuid"] for row in documents]
    explicit = requested is not None
    chosen = list(available) if requested is None else list(requested)
    known = set(available)
    unknown = [uuid for uuid in chosen if uuid not in known]
    by_uuid = {row["uuid"]: row for row in documents}
    selected = [by_uuid[uuid] for uuid in chosen if uuid in by_uuid]
    return {
        "explicit": explicit,
        "requested": chosen,
        "available": available,
        "selected": [row["uuid"] for row in selected],
        "unknown": unknown,
        "coversAll": bool(documents) and set(chosen) == known,
        "_documents": selected,
    }


def _public_selection(row: dict) -> dict:
    return {key: value for key, value in row.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# focus verification
# ---------------------------------------------------------------------------


def _current_uuid(payload: Any) -> tuple[str | None, str | None]:
    """The focused document uuid from ``document.current``, or why it is unknown.

    The real connector (``documentCurrent``, connector/src/actions.ts 873–944)
    answers ``{project, pcb, schematicPage, active: {uuid, type, ...}, ...}``:
    the current document is ``active.uuid``. ``active`` missing/unreadable or a
    non-empty ``problems`` is **not** proof of focus. The old top-level shapes
    are accepted only as a fallback when there is no ``active`` box at all.
    """
    if not isinstance(payload, dict):
        return None, "document.current 没有返回对象"
    problems = payload.get("problems")
    if _nonempty(problems):
        return None, "document.current 报告 problems：" + "; ".join(
            str(item) for item in problems
        )
    if "active" in payload:
        active = payload.get("active")
        if not isinstance(active, dict):
            return None, "document.current 的 active 不可读（null 或非对象）"
        uuid = str(active.get("uuid") or "")
        if not uuid:
            return None, "document.current 的 active.uuid 为空"
        return uuid, None
    uuid = str(payload.get("uuid") or "")
    document = payload.get("document")
    if not uuid and isinstance(document, dict):
        uuid = str(document.get("uuid") or "")
    if not uuid:
        return None, "document.current 读不出当前文档 uuid"
    return uuid, None


def _focus_check(expected: str) -> Callable[[Any], dict | None]:
    """A check that turns a focus reading into a failed step when it disagrees."""

    def check(payload: Any) -> dict | None:
        actual, problem = _current_uuid(payload)
        if problem is not None:
            return _error("FOCUS_UNREADABLE", problem)
        if actual != expected:
            return _error(
                "FOCUS_MISMATCH",
                f"document.current 的 active.uuid 是 {actual!r}，不是目标 {expected!r}："
                "不在错误页面上继续读取",
                expected=expected,
                actual=actual,
            )
        return None

    return check


# ---------------------------------------------------------------------------
# evidence checks: exit 0 is not the same as usable evidence
# ---------------------------------------------------------------------------


def _readback_error(data: Any, *, expected_kind: str) -> dict | None:
    """A readback is usable only when it names the namespace that was asked for.

    ``kind`` is the connector's own marker (``sch`` / ``pcb``). A schematic
    readback answered with PCB rows — or one that cannot say which namespace it
    read — is a failed evidence step even at exit 0: without this check a
    wrong-page read looks exactly like a clean one.

    An empty ``components`` list is a **valid reading of an empty board** — it
    is not a failure (and geometry may still be called with no ids).
    """
    if not isinstance(data, dict):
        return _error("READBACK_BAD_PAYLOAD", "readback 没有返回对象")
    actual_kind = str(data.get("kind") or "")
    if actual_kind != expected_kind:
        return _error(
            "READBACK_KIND_MISMATCH",
            f"readback 的 kind={actual_kind!r} 与请求的 {expected_kind!r} 不一致："
            "命名空间错位，读数不能当作本次证据",
            expected=expected_kind,
            actual=actual_kind,
        )
    if not isinstance(data.get("components"), list):
        return _error("READBACK_BAD_PAYLOAD", "readback 没有 components 数组读数")
    problems = data.get("problems")
    unreadable = data.get("unreadable")
    if not _nonempty(problems) and not _nonempty(unreadable):
        return None
    parts: list[str] = []
    if _nonempty(problems):
        parts.append(
            "problems: " + "; ".join(str(item) for item in problems)
            if isinstance(problems, (list, tuple, set))
            else f"problems: {problems}"
        )
    if _nonempty(unreadable):
        parts.append(f"unreadable: {unreadable}")
    return _error(
        "READBACK_PROBLEMS",
        "退出码 0 但读数不可用（" + "；".join(parts) + "）",
    )


def _sch_readback_error(data: Any) -> dict | None:
    return _readback_error(data, expected_kind="sch")


def _pcb_readback_error(data: Any) -> dict | None:
    return _readback_error(data, expected_kind="pcb")


def _geometry_error(data: Any) -> dict | None:
    """``pcb.geometry`` is usable only when its own ``meta`` proves completeness.

    The real connector always answers ``meta`` with ``available.bboxes``,
    ``requested`` / ``measured`` and per-id ``unreadable`` reasons. A missing
    ``meta``, an unavailable bbox API, or ``requested > measured`` is *not* a
    clean measurement: the caller would otherwise report a geometry it never
    took (172's whole point).
    """
    if not isinstance(data, dict):
        return _error("GEOMETRY_BAD_PAYLOAD", "pcb.geometry 没有返回对象")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return _error(
            "GEOMETRY_NO_META",
            "pcb.geometry 没有 meta：无法判断测量是否完整，不能算成功",
        )
    unreadable = meta.get("unreadable")
    reasons = meta.get("reasons")
    if _nonempty(unreadable) or _nonempty(reasons):
        parts: list[str] = []
        if _nonempty(unreadable):
            parts.append(f"unreadable: {unreadable}")
        if _nonempty(reasons):
            parts.append(f"reasons: {reasons}")
        return _error("GEOMETRY_UNREADABLE", "；".join(parts))
    available = meta.get("available")
    if not isinstance(available, dict) or available.get("bboxes") is not True:
        return _error(
            "GEOMETRY_UNAVAILABLE",
            "meta.available.bboxes 不是 true：本机几何测量 API 不可用，不能算成功",
        )
    requested = meta.get("requested")
    measured = meta.get("measured")
    if not isinstance(requested, int) or not isinstance(measured, int):
        return _error(
            "GEOMETRY_INCOMPLETE",
            "meta 缺 requested/measured：无法确认每个 id 都测到，不能算成功",
        )
    if requested > measured:
        return _error(
            "GEOMETRY_INCOMPLETE",
            f"requested={requested} > measured={measured}：有 id 没有测到，"
            "几何读数不完整",
        )
    return None


def _component_ids(data: dict) -> list[str]:
    out: list[str] = []
    for row in data.get("components") or []:
        if not isinstance(row, dict):
            continue
        primitive = str(row.get("primitiveId") or "")
        if primitive and primitive not in out:
            out.append(primitive)
    return out


# ---------------------------------------------------------------------------
# the collector
# ---------------------------------------------------------------------------


class _Capture:
    """Records steps/artifacts and owns the only place ``client.call`` happens."""

    def __init__(self, client: Any, out_dir: Path, route_kwargs: dict | None):
        self.client = client
        self.out_dir = Path(out_dir)
        self.route_kwargs = dict(route_kwargs or {})
        self.steps: list[dict] = []
        self.artifacts: list[dict] = []
        self.navigated = False

    async def call(
        self,
        document_uuid: str,
        action: str,
        params: dict | None = None,
        *,
        check: Callable[[Any], dict | None] | None = None,
    ) -> tuple[Any, dict]:
        """One action, one step. Any exception becomes a failed step, never a
        traceback out of the collector."""
        data: Any = None
        error: dict | None = None
        try:
            data = await self.client.call(
                action, dict(params or {}), **self.route_kwargs
            )
            if check is not None:
                error = check(data)
        except Exception as exc:  # noqa: BLE001 — an action failure is data here
            data = None
            error = _exception_error(exc)
        if error is None:
            step = _step(document_uuid, action, STATUS_OK, stdout=_stdout(data))
        else:
            step = _step(
                document_uuid,
                action,
                STATUS_FAILED,
                stdout=_stdout(data) if data is not None else "",
                stderr=_error_text(error),
                error=error,
            )
        self.steps.append(step)
        return data, step

    def skip(self, document_uuid: str, action: str, code: str, message: str) -> dict:
        error = _error(code, message)
        step = _step(
            document_uuid,
            action,
            "skipped",
            stderr=_error_text(error),
            error=error,
        )
        self.steps.append(step)
        return step

    def png_check(self, document: dict, channel: str) -> Callable[[Any], dict | None]:
        """Validate one render payload and write the PNG only if it is one."""

        def check(payload: Any) -> dict | None:
            if not isinstance(payload, dict):
                return _error("RENDER_BAD_PAYLOAD", "export.render 没有返回对象")
            if payload.get("format") != RENDER_FORMAT:
                return _error(
                    "RENDER_NOT_PNG",
                    f"render 回的是 {payload.get('format')!r}，不是 {RENDER_FORMAT}"
                    "（不落盘）",
                )
            encoded = payload.get("data")
            if not isinstance(encoded, str) or not encoded:
                return _error("RENDER_EMPTY", "render 没有回非空 base64 data")
            try:
                blob = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return _error("RENDER_BAD_BASE64", "render 的 data 不是合法 base64")
            if not blob:
                return _error("RENDER_EMPTY", "render 的 data 解码后为空")
            if blob[:4] == b"PK\x03\x04":
                return _error(
                    "RENDER_NOT_IMAGE", "render 的 data 是 zip 容器，不是 PNG（不落盘）"
                )
            if not blob.startswith(PNG_SIGNATURE):
                return _error(
                    "RENDER_NOT_IMAGE",
                    "render 的 data 不是 PNG（缺 8 字节 PNG 签名，不落盘）",
                )
            prefix = "live-sch" if channel == CHANNEL_SCHEMATIC_IMAGE else "live-pcb"
            stem = f"{prefix}-{_safe_stem(document['name'])}-{_short_uuid(document['uuid'])}"
            relative = _write_unique(self.out_dir, stem, ".png", blob)
            self.artifacts.append(
                {
                    "channel": channel,
                    "documentUuid": document["uuid"],
                    "kind": "image",
                    "page": document["name"],
                    "file": relative,
                    "bytes": len(blob),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "format": RENDER_FORMAT,
                }
            )
            return None

        return check

    def netlist_check(self, document: dict) -> Callable[[Any], dict | None]:
        """A netlist is evidence only when its text is non-empty; save it."""

        def check(payload: Any) -> dict | None:
            if not isinstance(payload, dict):
                return _error("NETLIST_BAD_PAYLOAD", "sch.netlist 没有返回对象")
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                return _error("NETLIST_EMPTY", "sch.netlist 没有回非空 text")
            blob = text.encode("utf-8")
            stem = (
                f"live-netlist-{_safe_stem(document['name'])}-"
                f"{_short_uuid(document['uuid'])}"
            )
            relative = _write_unique(self.out_dir, stem, ".txt", blob)
            self.artifacts.append(
                {
                    "channel": CHANNEL_LIVE_SCHEMATIC,
                    "documentUuid": document["uuid"],
                    "kind": "netlist",
                    "page": document["name"],
                    "file": relative,
                    "bytes": len(blob),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "format": "text/plain",
                    "netlistType": str(payload.get("type") or NETLIST_TYPE),
                }
            )
            return None

        return check


async def _open_and_verify(capture: _Capture, document: dict) -> bool:
    """Open one document, then prove through ``document.current`` that it is in
    front. Returns False (after recording why) when focus cannot be proven."""
    capture.navigated = True  # before the call: a timeout may already have switched
    _, open_step = await capture.call(document["uuid"], "doc.open", {"uuid": document["uuid"]})
    if open_step["status"] != STATUS_OK:
        return False
    _, current_step = await capture.call(
        document["uuid"],
        "document.current",
        {},
        check=_focus_check(document["uuid"]),
    )
    return current_step["status"] == STATUS_OK


async def _render_page(
    capture: _Capture, document: dict, channel: str
) -> dict:
    params = {
        "format": "png",
        "scope": "page",
        "pageUuid": document["uuid"],
        "fileName": (
            ("live-sch-" if channel == CHANNEL_SCHEMATIC_IMAGE else "live-pcb-")
            + f"{_safe_stem(document['name'])}-{_short_uuid(document['uuid'])}.png"
        ),
        "timeoutMs": RENDER_TIMEOUT_MS,
    }
    _, step = await capture.call(
        document["uuid"],
        "export.render",
        params,
        check=capture.png_check(document, channel),
    )
    return step


async def _collect_schematic(
    capture: _Capture, documents: list[dict]
) -> None:
    """One schematic page at a time; each reading has its own try."""
    netlist_attempted = False
    for document in documents:
        if not await _open_and_verify(capture, document):
            uuid = document["uuid"]
            capture.skip(uuid, "sch.readback", "SKIPPED", "焦点未核实，不在错误页面回读")
            if not netlist_attempted:
                capture.skip(uuid, "sch.netlist", "SKIPPED", "焦点未核实，不读网表")
            capture.skip(uuid, "export.render", "SKIPPED", "焦点未核实，不在错误页面出图")
            continue

        await capture.call(
            document["uuid"],
            "sch.readback",
            {"includePrimitives": True},
            check=_sch_readback_error,
        )
        if not netlist_attempted:
            # Exactly one netlist for the whole run, on the first page whose
            # focus was actually proven. It is project-level (pit 30), so which
            # page it rides on does not change the reading.
            netlist_attempted = True
            await capture.call(
                document["uuid"],
                "sch.netlist",
                {"type": NETLIST_TYPE},
                check=capture.netlist_check(document),
            )
        await _render_page(capture, document, CHANNEL_SCHEMATIC_IMAGE)


async def _collect_pcb(capture: _Capture, documents: list[dict]) -> None:
    """One PCB at a time. Render runs even when readback/geometry failed."""
    for document in documents:
        if not await _open_and_verify(capture, document):
            uuid = document["uuid"]
            capture.skip(uuid, "pcb.readback", "SKIPPED", "焦点未核实，不在错误页面回读")
            capture.skip(uuid, "pcb.geometry", "SKIPPED", "焦点未核实，不测几何")
            capture.skip(uuid, "export.render", "SKIPPED", "焦点未核实，不在错误页面出图")
            continue

        readback_data, readback_step = await capture.call(
            document["uuid"],
            "pcb.readback",
            {"includePrimitives": True},
            check=_pcb_readback_error,
        )
        if readback_step["status"] == STATUS_OK and isinstance(readback_data, dict):
            await capture.call(
                document["uuid"],
                "pcb.geometry",
                {"bboxIds": _component_ids(readback_data)},
                check=_geometry_error,
            )
        else:
            # Geometry's ids come from readback. A failed readback is not an
            # empty board: measuring with no ids would be a success-shaped lie.
            capture.skip(
                document["uuid"],
                "pcb.geometry",
                "DEPENDENCY_MISSING",
                "pcb.readback 没有给出可用组件读数，bboxIds 依赖缺失，几何未测量",
            )
        # Independent of both: the picture may still be the evidence that lands.
        await _render_page(capture, document, CHANNEL_PCB_IMAGE)


async def _restore_focus(
    capture: _Capture,
    original_uuid: str,
    restore_hint: dict | None,
) -> dict:
    """Put the original tab back and verify it; disclose any failure."""
    if not capture.navigated:
        if restore_hint is not None:
            return dict(restore_hint)
        return {
            "ok": True,
            "attempted": False,
            "status": "not-applicable",
            "originalUuid": original_uuid or None,
            "error": None,
        }
    if not original_uuid:
        # The refusal happens before navigation; this is a last-resort branch.
        return {
            "ok": False,
            "attempted": True,
            "status": "unavailable",
            "originalUuid": None,
            "error": _error(
                "FOCUS_UNAVAILABLE",
                "原活动页 uuid 在导航前不可读，无法核实已恢复到原焦点",
            ),
        }
    _, open_step = await capture.call(
        original_uuid, "doc.open", {"uuid": original_uuid}
    )
    if open_step["status"] != STATUS_OK:
        return {
            "ok": False,
            "attempted": True,
            "status": "failed",
            "originalUuid": original_uuid,
            "error": open_step["error"],
        }
    _, current_step = await capture.call(
        original_uuid,
        "document.current",
        {},
        check=_focus_check(original_uuid),
    )
    if current_step["status"] != STATUS_OK:
        return {
            "ok": False,
            "attempted": True,
            "status": "failed",
            "originalUuid": original_uuid,
            "error": current_step["error"],
        }
    return {
        "ok": True,
        "attempted": True,
        "status": "restored",
        "originalUuid": original_uuid,
        "error": None,
    }


# ---------------------------------------------------------------------------
# channels — derived from what really happened
# ---------------------------------------------------------------------------


def _channel_row(
    status: str,
    channel: str,
    detail: str,
    *,
    steps: list[dict],
    artifacts: list[dict],
    errors: list[str],
) -> dict:
    return {
        "status": status,
        "source": CHANNEL_SOURCES[channel],
        "detail": detail,
        "artifacts": [dict(row) for row in artifacts],
        "errors": errors,
        "steps": [dict(step) for step in steps],
    }


def _failures_for(
    channel: str,
    selected: list[dict],
    index: dict[tuple[str, str], dict],
    steps: list[dict],
) -> list[str]:
    failures: list[str] = []
    for document in selected:
        for action in _REQUIRED_ACTIONS[channel]:
            step = index.get((document["uuid"], action))
            if step is None:
                failures.append(f"{action} ({document['uuid']}): 没有该步骤记录")
            elif step["status"] == STATUS_FAILED:
                error = step.get("error") or {}
                failures.append(
                    f"{action} ({document['uuid']}): "
                    f"{error.get('code')}: {error.get('message')}"
                )
    if channel == CHANNEL_LIVE_SCHEMATIC and selected:
        netlist_ok = any(
            step["action"] == "sch.netlist" and step["status"] == STATUS_OK
            for step in steps
        )
        if not netlist_ok:
            failures.append("sch.netlist: 没有一次成功的非空网表")
    return failures


def _build_channels(
    *,
    documents: dict[str, list[dict]],
    listing_valid: bool,
    selection: dict[str, dict],
    steps: list[dict],
    artifacts: list[dict],
    abort: dict | None,
) -> dict:
    """Derive the four channel rows from the steps that really ran.

    Status rules, in this order (537C3b1 三):
    * an unusable ``doc.list`` → **missing**: the document set is unknown;
    * no PCB document → ``not-applicable``; no schematic page → ``failed``;
    * a refused run (identity/selection/focus) → ``missing``: nothing was read;
    * any attempted required step failed → ``failed`` (successes stay listed);
    * an explicit subset that has not failed → ``missing`` (coverage, not quality);
    * every required step ok (and a non-empty netlist) → ``ok``;
    * anything else → ``failed`` (attempted but incomplete evidence is not a pass).
    """
    index: dict[tuple[str, str], dict] = {}
    for step in steps:
        index.setdefault((step["documentUuid"], step["action"]), step)

    channels: dict[str, dict] = {}
    for channel in LIVE_CHANNEL_ORDER:
        kind = "pcb" if channel in (CHANNEL_LIVE_PCB, CHANNEL_PCB_IMAGE) else "schematic"
        all_documents = documents[kind]
        selected = selection[kind].get("_documents") or []
        selected_uuids = {row["uuid"] for row in selected}
        channel_steps = [
            step
            for step in steps
            if step["documentUuid"] in selected_uuids
            and step["action"] in _CHANNEL_ACTIONS[channel]
        ]
        channel_artifacts = [
            row
            for row in artifacts
            if row.get("channel") == channel
            and row.get("documentUuid") in selected_uuids
        ]
        failures = _failures_for(channel, selected, index, steps)

        if not listing_valid:
            status = STATUS_MISSING
            detail = (
                "doc.list 不可用或缺 documents 数组：文档集合未知，未导航采集。"
                "unknown 不能写成 not-applicable（确认无 PCB）或 failed（确认无页）。"
            )
        elif kind == "pcb" and not all_documents:
            status = STATUS_NOT_APPLICABLE
            detail = (
                "doc.list 没有 PCB 文档：没有可实时回读的 PCB，"
                "本通道不适用（N/A 不是「读过且干净」）。"
            )
        elif kind == "schematic" and not all_documents:
            status = STATUS_FAILED
            detail = (
                "doc.list 没有原理图页：没有可采集的实时原理图证据，"
                "本通道记为 failed（不是 missing——这是确认没有页）。"
            )
        elif abort is not None:
            status = STATUS_MISSING
            detail = f"未导航采集：{abort.get('message') or abort.get('code')}"
        elif failures:
            status = STATUS_FAILED
            detail = (
                f"{len(failures)} 个必需步骤未成功：{failures[0]}。"
                "已成功的证据仍保留在 steps / artifacts。"
            )
        elif not selection[kind].get("coversAll"):
            status = STATUS_MISSING
            detail = (
                f"显式选择只覆盖 {len(selected)}/{len(all_documents)} 个"
                f"{'PCB' if kind == 'pcb' else '原理图页'}：其余未采集，"
                "覆盖不全只能记 missing（不是 ok，也不是 failed）。"
            )
        elif not selected:
            status = STATUS_FAILED
            detail = "有该类型文档但没有任何页被选中：没有证据可记，本通道 failed。"
        elif channel == CHANNEL_LIVE_SCHEMATIC:
            status = STATUS_OK
            detail = (
                f"{len(selected)} 个原理图页 readback 成功，网表 1 次非空："
                "这是直接实时证据，不是归档。"
            )
        elif channel == CHANNEL_LIVE_PCB:
            status = STATUS_OK
            detail = f"{len(selected)} 块 PCB readback + geometry 全部成功。"
        else:
            status = STATUS_OK
            detail = (
                f"{len(selected)} 页 PNG 全部落盘（format=image/png，"
                "bytes/sha256 见 artifacts）。"
            )

        errors = [
            f"{step['action']} ({step['documentUuid']}): "
            f"{(step.get('error') or {}).get('code')}: "
            f"{(step.get('error') or {}).get('message')}"
            for step in channel_steps
            if step["status"] == STATUS_FAILED
        ]
        if status == STATUS_FAILED and not errors:
            errors = list(failures) or [detail]

        channels[channel] = _channel_row(
            status,
            channel,
            detail,
            steps=channel_steps,
            artifacts=channel_artifacts,
            errors=errors,
        )
    return channels


# ---------------------------------------------------------------------------
# the public entry point
# ---------------------------------------------------------------------------


async def collect_live_evidence(
    client,
    *,
    out_dir: Path,
    route_kwargs: dict | None = None,
    page_uuids: Iterable[str] | None = None,
    pcb_uuids: Iterable[str] | None = None,
    expected_project_uuid: str = "",
) -> dict:
    """Collect one run's live schematic/PCB evidence through ``client``.

    The client is only ever *called*: this function never opens or closes it.
    ``out_dir`` is the only place evidence files are written. Every refusal and
    every failure is a value in the returned dict — nothing is raised for an
    action failure, and the original focus is restored in ``finally``.
    """
    capture = _Capture(client, out_dir, route_kwargs)
    listing, listing_step = await capture.call(
        "", "doc.list", {}, check=_listing_error
    )
    listing_valid = _listing_valid(listing)

    documents = _documents(listing)
    by_kind = {
        "schematic": [row for row in documents if row["type"] == "schematic"],
        "pcb": [row for row in documents if row["type"] == "pcb"],
    }
    active_uuid = _active_uuid(listing)
    project_uuid = _focused_project_uuid(listing)

    expected = str(expected_project_uuid or "")
    identity: dict = {
        "ok": True,
        "expectedProjectUuid": expected,
        "projectUuid": project_uuid,
        "activeUuid": active_uuid or None,
        "verifiedAgainstReport": bool(expected) and bool(project_uuid) and project_uuid == expected,
        "problems": [],
        "error": None,
    }
    if not expected:
        if not project_uuid:
            identity["problems"].append(
                "doc.list 没有可读的 focused projectUuid：本次不声称已核实同一设计"
            )
    elif not project_uuid:
        identity["ok"] = False
        identity["verifiedAgainstReport"] = False
        identity["error"] = _error(
            "PROJECT_IDENTITY_UNREADABLE",
            "给了 expected_project_uuid，但 doc.list 读不出 focused projectUuid："
            "不能核实身份，拒绝导航",
            expected=expected,
            actual="",
        )
    elif project_uuid != expected:
        identity["ok"] = False
        identity["verifiedAgainstReport"] = False
        identity["error"] = _error(
            "PROJECT_IDENTITY_MISMATCH",
            f"焦点工程 {project_uuid!r} 与报告期望 {expected!r} 不一致："
            "拒绝导航，避免读写别的设计",
            expected=expected,
            actual=project_uuid,
        )

    schematic_selection = _selection_row(
        by_kind["schematic"], _requested_ids(page_uuids)
    )
    pcb_selection = _selection_row(by_kind["pcb"], _requested_ids(pcb_uuids))
    selection: dict = {
        "ok": True,
        "schematic": _public_selection(schematic_selection),
        "pcb": _public_selection(pcb_selection),
        "error": None,
    }
    unknown = {
        "schematic": schematic_selection["unknown"],
        "pcb": pcb_selection["unknown"],
    }
    if unknown["schematic"] or unknown["pcb"]:
        selection["ok"] = False
        parts = []
        if unknown["schematic"]:
            parts.append("原理图页 " + ", ".join(unknown["schematic"]))
        if unknown["pcb"]:
            parts.append("PCB " + ", ".join(unknown["pcb"]))
        selection["error"] = _error(
            "UNKNOWN_DOCUMENT_UUID",
            "显式选择含 doc.list 里不存在的文档 id（" + "；".join(parts) + "）："
            "在任何导航前拒绝",
            unknown=unknown,
        )

    selected_document_count = len(schematic_selection["_documents"]) + len(
        pcb_selection["_documents"]
    )
    abort: dict | None = None
    if not listing_valid:
        abort = {
            "code": "DOC_LIST_INVALID",
            "message": (
                "doc.list 不可用或缺 documents 数组：文档清单未知，未导航采集"
            ),
            "reason": listing_step.get("error"),
        }
    elif identity["error"] is not None:
        abort = {
            "code": identity["error"]["code"],
            "message": "工程身份未核实，未导航采集",
        }
    elif selection["error"] is not None:
        abort = {
            "code": selection["error"]["code"],
            "message": "显式选择未通过，未导航采集",
        }
    elif selected_document_count and not active_uuid:
        # An unknown "no active page" state cannot be restored once we move the
        # editor. Refuse before navigation instead of switching first and
        # confessing afterwards.
        abort = {
            "code": "FOCUS_UNAVAILABLE",
            "message": "doc.list 的 active.uuid 不可读：需要导航，但无法承诺恢复原焦点",
        }

    restore_hint: dict | None = None
    if abort is not None and abort["code"] == "FOCUS_UNAVAILABLE":
        restore_hint = {
            "ok": False,
            "attempted": False,
            "status": "unavailable",
            "originalUuid": None,
            "error": _error(
                "FOCUS_UNAVAILABLE",
                "doc.list 的 active.uuid 不可读，无法保证恢复原焦点：未调用 doc.open",
            ),
        }

    restore: dict
    restore_split: int
    try:
        if abort is None:
            await _collect_schematic(
                capture, schematic_selection["_documents"]
            )
            await _collect_pcb(capture, pcb_selection["_documents"])
    except Exception as exc:  # noqa: BLE001 — the capture must survive a bug
        error = _exception_error(exc)
        capture.steps.append(
            _step("", "collect", STATUS_FAILED, stderr=_error_text(error), error=error)
        )
    finally:
        restore_split = len(capture.steps)
        restore = await _restore_focus(capture, active_uuid, restore_hint)

    channels = _build_channels(
        documents=by_kind,
        listing_valid=listing_valid,
        selection={
            "schematic": schematic_selection,
            "pcb": pcb_selection,
        },
        steps=capture.steps[:restore_split],
        artifacts=capture.artifacts,
        abort=abort,
    )
    ok = (
        identity["ok"] is True
        and restore["ok"] is True
        and all(
            channels[channel]["status"] in CLOSED_STATUSES
            for channel in LIVE_CHANNEL_ORDER
        )
    )
    return {
        "schema": LIVE_EVIDENCE_SCHEMA,
        "ok": ok,
        "executor": LIVE_EVIDENCE_EXECUTOR,
        "identity": identity,
        "selection": selection,
        "channels": channels,
        "steps": capture.steps,
        "artifacts": capture.artifacts,
        "focusRestore": restore,
    }
