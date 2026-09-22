"""WebSocket daemon: the bridge's server side.

The daemon is the only listening socket in the system. It accepts two kinds of
client (see :mod:`boardwise.bridge.protocol`) and does four jobs:

1. **Authenticate** — every connection must open with ``hello``; anything else
   is closed immediately. The two roles use *different* secrets:
   ``cli`` presents ``~/.boardwise/token`` (written by ``bridge start``, copied
   by the user), while ``connector`` uses trust-on-first-use pairing (below).
2. **Register** — every authenticated connector joins a **hub**: one entry per
   editor window, keyed by the instance id it claims, carrying its socket and
   what that window has told us about itself (project, page, build).
3. **Route** — daemon-owned actions (``hello``, ``ping``) are answered here;
   every other action is resolved to **one** window and forwarded there — by the
   caller's ``targetInstance`` hint (the window's own instance id, which is the
   only name that survives an editor which cannot yet read a project), else by
   its ``targetProject`` hint, else directly when only one window is connected.
   With several windows and no hint the daemon refuses with
   ``WINDOW_UNSPECIFIED`` and lists them, because picking one would be exactly
   the silent wrong-window write that 018 measured and 023 exists to end.
4. **Audit** — every request is appended to ``~/.boardwise/audit/<date>.jsonl``
   with role, action, duration, outcome and **which window answered it**.

**The hub (023).** Until 2026-09-22 this daemon held exactly one connector and
refused the second with ``CONNECTOR_ALREADY_ACTIVE``, because two windows taking
turns in a single slot is how writes landed in whichever project the winning
window had focused (018 §A). A hardware engineer opens three or four windows as
a matter of course, so the single slot was the wrong fix: contention is now
answered by *routing* instead of by exclusion. ``easyeda-agent``'s daemon is the
model — a ``windowID`` per connection, a live ``context`` refreshed on every
response, ``windowForProject`` to turn a project hint into a window, and a
per-window lock so two writes to the same window serialise while different
windows run in parallel.

The refusal code survives in :class:`boardwise.bridge.protocol.ErrorCodes` as a
retired name (it is read by connector builds in the field); nothing here raises
it any more. The safety property 018 wanted is kept differently and more
honestly: the second window is no longer *hidden*, it is a first-class row in
``bridge status``, a line in the audit log, and a routing target.

Security posture, stated plainly because it is the whole threat model:

- Binds ``127.0.0.1`` only. There is no code path that listens on a public
  interface.
- The CLI token is a 32-byte random secret in ``~/.boardwise/token``, mode 0600
  on POSIX. A connection without it is closed before it can ask for anything.
- The connector is *not* sandboxed: whatever ``eda.*`` exposes, an
  authenticated caller can reach. The token is the only gate, which is why the
  file is never logged or echoed.

**Connector pairing (trust on first use).** An editor extension cannot read
``~/.boardwise/token``, and making the user paste a 64-hex secret into a dialog
was the worst part of the v0 experience. So the connector generates its *own*
random token and the daemon stores it in ``~/.boardwise/connector-token`` the
first time one arrives:

- no ``connector-token`` file → the first connector to say ``hello`` is trusted
  and its token is written down (audited as ``pairing``);
- file present → the presented token must match it exactly, or the connection
  is refused with ``UNAUTHENTICATED``;
- ``boardwise bridge revoke`` deletes the file, so the next connector re-pairs.

That is the correct strength for this threat model, and the threat model is the
reason: the daemon is loopback-only, so what pairing has to resist is *another
local process or a web page* getting there first — not a process that can
already read the user's home directory, which has won regardless. The window
is therefore the first connection only, it is announced loudly on the console,
and it is one command to undo.

Run it with :func:`serve_forever`, or drive it in-process with
:func:`start_server` (used by the tests).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

import websockets
from websockets.asyncio.server import ServerConnection, serve

from .. import __version__ as BOARDWISE_VERSION
from .protocol import (
    HELLO_TIMEOUT,
    PROTOCOL_VERSION,
    ROLE_CLI,
    ROLE_CONNECTOR,
    Action,
    BridgeError,
    Connection,
    ErrorCodes,
    action_spec,
    banner_frame,
    context_of,
    decode_frame,
    error_frame,
    merge_context,
    request_frame,
    response_frame,
    timeout_for,
)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "BOARDWISE_HOME",
    "AUDIT_PAIRING",
    "AUDIT_REVOKE",
    "AUDIT_REPAIRING",
    "AUDIT_DRAW_PERSISTENCE",
    "AUDIT_PERSISTENCE_VERIFIED",
    "MIN_CONNECTOR_VERSION",
    "UNKNOWN_CONNECTOR_VERSION",
    "WINDOW_KEY_SEPARATOR",
    "client_with_version",
    "token_path",
    "connector_token_path",
    "audit_dir",
    "load_token",
    "ensure_token",
    "load_connector_token",
    "store_connector_token",
    "revoke_connector_token",
    "connector_fingerprint",
    "check_origin",
    "client_headers",
    "append_audit",
    "PairingNotice",
    "WindowConnection",
    "PendingCall",
    "window_listing",
    "status_lines",
    "BridgeDaemon",
    "start_server",
    "serve_forever",
    "resolve_port",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 61190

#: Audit record names for the pairing lifecycle. They are not wire actions and
#: therefore not in the action catalogue — they only ever appear in the log.
AUDIT_PAIRING = "pairing"
AUDIT_REVOKE = "revoke"
#: A connector that re-paired because its storage was reset (a sideload),
#: distinguished from a first-ever pairing because the two want different
#: reactions: the first is "check this is yours", the second is "yes, you just
#: reinstalled".
AUDIT_REPAIRING = "re-pairing"

#: How far a `draw` run's write actually got, recorded by the CLI process
#: (M0-P0d). The daemon's own per-action records say `ok` and nothing about
#: persistence — an action can be `ok: true` while the page was never saved,
#: and `saved: true` never reached the log at all because the daemon does not
#: record action payloads (audit F, 2026-09-18). These two names are what make
#: the three states distinguishable in the log rather than only on stdout.
#: `draw.persistence` is written by every draw run; `persistence.verified` only
#: by a run that compared a page across a real close-and-reopen.
AUDIT_DRAW_PERSISTENCE = "draw.persistence"
AUDIT_PERSISTENCE_VERIFIED = "persistence.verified"

#: The audit record that said a connector was **turned away** because another
#: editor instance already held the bridge (018 §A). **Retired in 023**: nothing
#: is turned away any more, so this name has no writer. Kept — deliberately
#: outside ``__all__``, since it is no longer part of the live API — because a
#: reader grepping yesterday's logs for ``connector_rejected`` should be able to
#: find out here why the record stopped, instead of concluding the daemon broke.
AUDIT_CONNECTOR_REJECTED = "connector_rejected"

#: Oldest connector build this daemon works with, announced in the ``hello``
#: ack as ``minConnectorVersion`` so the extension can tell the user to update
#: instead of failing later, mysteriously (018 §A/§B). Equal to the shipped
#: connector version today, so nothing is refused *now*: the field exists so
#: that the day a protocol change makes an old bundle dangerous, the mismatch
#: arrives as a toast rather than as a stack trace.
MIN_CONNECTOR_VERSION = "0.4.10"

#: Separator between a window's instance id and the disambiguating counter the
#: hub appends when two **live** sockets claim the same id (023). ``inst-x~2``.
#: Chosen because it is not a character EasyEDA puts in an instance id, so a
#: suffixed key can never collide with a claimed one, and it reads as "the same
#: window, again" rather than as a different window.
WINDOW_KEY_SEPARATOR = "~"

#: Rendered in the audit log for a connector that does not announce its build.
#: Spelled out rather than left empty on purpose: an absent field is easy to
#: read as "the daemon forgot to record it", and the whole point of the field
#: is that a version question is answerable afterwards.
UNKNOWN_CONNECTOR_VERSION = "(version unknown)"

#: Home for token, audit log and future state. Overridable so tests never
#: touch the real one.
BOARDWISE_HOME = Path(
    os.environ.get("BOARDWISE_HOME", Path.home() / ".boardwise")
)

#: A screenshot is megabytes of base64; the 1 MiB default would reject it.
MAX_FRAME_BYTES = 32 * 1024 * 1024

AUDIT_FILE_TEMPLATE = "{date}.jsonl"


# --------------------------------------------------------------------------
# token & paths
# --------------------------------------------------------------------------


def token_path(home: Path | None = None) -> Path:
    return (home or BOARDWISE_HOME) / "token"


def connector_token_path(home: Path | None = None) -> Path:
    """The paired connector's token — deliberately a *different* file.

    Kept separate from :func:`token_path` so that pairing a connector can never
    change, weaken or leak the CLI's credential, and so that ``revoke`` has
    something precise to delete. The CLI flow is untouched by design.
    """
    return (home or BOARDWISE_HOME) / "connector-token"


def audit_dir(home: Path | None = None) -> Path:
    return (home or BOARDWISE_HOME) / "audit"


def resolve_port() -> int:
    """Port the daemon listens on: ``BOARDWISE_PORT`` or 61190."""
    raw = os.environ.get("BOARDWISE_PORT", "")
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def load_token(home: Path | None = None) -> str | None:
    """Return the stored token, or ``None`` when it was never created."""
    path = token_path(home)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # POSIX-only; Windows silently keeps default ACLs
        pass


def ensure_token(home: Path | None = None) -> str:
    """Return the token, creating it on first use.

    Created 0600 because it is the only thing standing between a local
    process and full editor control.
    """
    existing = load_token(home)
    if existing:
        return existing
    token = secrets.token_hex(32)
    _write_secret(token_path(home), token)
    return token


def load_connector_token(home: Path | None = None) -> str | None:
    """The paired connector's token, or ``None`` if no connector is paired.

    Read from disk on every use rather than cached: ``bridge revoke`` deletes
    the file from a *different* process while the daemon is running, and a
    cached copy would silently keep honouring a credential the user just
    revoked.
    """
    path = connector_token_path(home)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def store_connector_token(token: str, home: Path | None = None) -> None:
    """Persist the first connector's token as the pairing record."""
    _write_secret(connector_token_path(home), token)


def revoke_connector_token(home: Path | None = None) -> str | None:
    """Delete the pairing record. Returns the fingerprint it had, if any.

    The next connector to connect re-pairs automatically, so this is a reset
    rather than a lockout — there is no way to lock the user out of their own
    editor, which is why it is a plain command and not a confirmation dialog.
    """
    path = connector_token_path(home)
    previous = load_connector_token(home)
    try:
        path.unlink()
    except OSError:
        return None
    return connector_fingerprint(previous) if previous else None


def client_with_version(client: str, connector_version: str | None) -> str:
    """The audit-log `client` string, carrying the connector's own build.

    `client` has always said who the editor is (`boardwise-connector/3.2.186`).
    Since 0.4.1 it also says which *connector* build that was, because the two
    drift apart: a sideload that does not take leaves the editor's version
    unchanged and the bundle a revision behind, and the audit log is the only
    place where that difference is visible after the fact.

    A connector that predates the field is **not** refused — it is recorded as
    ``(version unknown)``, which is honest about what we know instead of
    quietly looking like a modern build that forgot its name.
    """
    version = (connector_version or "").strip()
    return f"{client} connector={version or UNKNOWN_CONNECTOR_VERSION}"


def connector_fingerprint(token: str | None) -> str | None:
    """Short, stable, non-reversible id for a token: first 8 hex of SHA-256.

    This is the *only* representation of a token that may appear in a log, a
    status line or a console message. Eight hex characters are plenty to tell
    two tokens apart by eye and useless for recovering the 32-byte secret.
    """
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def append_audit(home: Path | None, **fields: Any) -> None:
    """Append one JSON line to today's audit log. Never raises.

    A module-level function rather than a daemon method so that the CLI can
    record events that happen *without* a daemon — ``bridge revoke`` is the
    case that matters: it has to work precisely when nothing is listening.
    """
    try:
        directory = audit_dir(home)
        directory.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), **fields}
        path = directory / AUDIT_FILE_TEMPLATE.format(date=time.strftime("%Y-%m-%d"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def status_lines(data: dict[str, Any]) -> list[str]:
    """The window table ``boardwise bridge status`` prints.

    Takes the ``ping`` answer the CLI has already fetched and returns the lines
    for it — empty when there is nothing to say, so a fresh daemon with no
    connector prints exactly what it printed before. The wording lives here
    rather than in the CLI so it cannot drift from the wire keys it renders
    (018 §A); ``data`` is documented in :meth:`BridgeDaemon._local_action`.

    **Multi-window (023).** One block per connected window: its hub key, its
    connector build, its project and page, when it arrived, when it was last
    heard from, and how many calls it has answered. This is the answer to "which
    projects do I have open, and which one is boardwise talking to?" — a question
    that used to have no answer at all, and then (018) only had one for the
    single privileged window. Reading the audit log is now the fallback, not the
    first step.

    The old ``active instance:`` line is gone: with a hub there is no "the"
    instance. ``projects seen:`` stays and is upgraded from *roles* ("active",
    "refused") to the online windows themselves, because every window in it is
    now reachable and named.

    A window that named no project — an old build, or a read that failed — gets
    no suffix and is counted, never guessed at.
    """
    lines: list[str] = []
    windows = _status_windows(data)
    if windows:
        lines.append(f"  windows: {len(windows)} connected")
    for window in windows:
        version = window.get("connectorVersion") or UNKNOWN_CONNECTOR_VERSION
        key = str(window.get("windowKey") or window.get("instanceId") or "?")
        note = (
            ""
            if window.get("instanceIdSource") == "hello"
            else "  [no instanceId sent — named by connection]"
        )
        lines.append(
            f"  window: {key} (connector {version}){note}{_project_suffix(window)}"
        )
        detail = (
            f"    peer: {window.get('peer') or '-'}"
            f"  connected: {_clock(window.get('connectedAt'))}"
            f"  last seen: {_clock(window.get('lastSeen'))}"
        )
        routed = window.get("routed")
        if isinstance(routed, int) and routed:
            detail += f"  routed: {routed}"
        lines.append(detail)
        page = _page_line(window)
        if page:
            lines.append(page)
    seen = _projects_seen(windows)
    if seen:
        lines.append(seen)
    return lines


def _status_windows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``windows`` list out of a ``ping`` answer, defensively.

    Anything that is not a usable dict is dropped rather than rendered as a
    broken line: this reads a frame from another process, and a status command
    that raises on a malformed field is worse than one that shows the windows it
    could read.
    """
    raw = data.get("windows")
    if not isinstance(raw, list):
        return []
    return [
        window
        for window in raw
        if isinstance(window, dict) and (window.get("windowKey") or window.get("instanceId"))
    ]


def _project_label(record: dict[str, Any]) -> str:
    """``name (uuid)`` from one status record, or ``""`` when neither is known.

    Both halves are optional on the wire, so all four combinations are real and
    each is rendered as itself: a window may have a name and no uuid, or the
    other way round. Nothing is padded and nothing is truncated — a uuid that
    cannot be copied is not much use to someone deciding which window to close.
    """
    name = str(record.get("projectName") or "")
    uuid = str(record.get("projectUuid") or "")
    if name and uuid:
        return f"{name} ({uuid})"
    return name or uuid


def _project_suffix(record: dict[str, Any]) -> str:
    """The ``  [project …]`` tail on a status line, empty when nothing is known."""
    label = _project_label(record)
    return f"  [project {label}]" if label else ""


def _page_line(record: dict[str, Any]) -> str:
    """The ``    page: sch <uuid>`` line, or ``""`` when no page is known.

    The page (023) is what a caller is really aiming at most of the time, and it
    is the one field that moves while a window stays connected — so it is printed
    on its own line rather than folded into the window's own, where a reader
    would have to compare two whole lines to see that it changed.
    """
    page_type = str(record.get("pageType") or "")
    page_uuid = str(record.get("pageUuid") or "")
    if not (page_type or page_uuid):
        return ""
    return f"    page: {page_type or '?'} {page_uuid or '(no uuid)'}"


def _project_name(record: dict[str, Any]) -> str:
    """The project's *name* for the summary line, falling back to its uuid.

    Deliberately not :func:`_project_label`: the summary groups windows by
    project, and it stays readable only if the uuid — which is already printed
    on the window's own line — is left out of it.
    """
    name = str(record.get("projectName") or "")
    return name or str(record.get("projectUuid") or "")


def _projects_seen(windows: list[dict[str, Any]]) -> str:
    """One line naming every project the online windows have open, or ``""``.

    The upgrade of 021 §2.3's line (023): it used to group *the active window
    plus every refused one*, because a refused socket was the only evidence the
    other projects existed. Every window is a hub row now, so the line groups the
    windows that are actually connected and names each by its key — which is what
    a caller needs to write back into ``--project``.

    Silent when *no* window named a project: an old connector's output must not
    grow a line saying that nothing is known. Windows that named no project are
    counted only once something else is named, for the same reason (the old
    output-shape tests pin this).
    """
    groups: dict[str, list[str]] = {}
    unnamed = 0
    for window in windows:
        label = _project_name(window)
        key = str(window.get("windowKey") or window.get("instanceId") or "?")
        if not label:
            unnamed += 1
            continue
        keys = groups.setdefault(label, [])
        if key not in keys:
            keys.append(key)

    if not groups:
        return ""
    parts = [f"{label} ({', '.join(keys)})" for label, keys in groups.items()]
    if unnamed:
        parts.append(f"{unnamed} window(s) naming no project")
    return "  projects seen: " + ", ".join(parts)


# --------------------------------------------------------------------------
# request headers (evidence gathering)
# --------------------------------------------------------------------------


def client_headers(websocket: Any) -> dict[str, str | None]:
    """``Origin`` / ``User-Agent`` of the WebSocket handshake, missing → ``None``.

    Recorded because a browser can open a WebSocket to loopback and we have no
    measurement yet of what the editor's ``sys_WebSocket`` sends. See
    :func:`check_origin`.
    """
    request = getattr(websocket, "request", None)
    headers = getattr(request, "headers", None)

    def read(name: str) -> str | None:
        if headers is None:
            return None
        try:
            value = headers.get(name)
        except (AttributeError, TypeError):
            return None
        # Careful: `str(value) or None` would return the *string* "None" for an
        # absent header, which is exactly the distinction 004d needs to make.
        if value is None:
            return None
        return str(value) or None

    return {"origin": read("Origin"), "user_agent": read("User-Agent")}


def check_origin(headers: Any) -> bool:
    """Whether to accept a handshake carrying these headers.

    **Always true, on purpose, and only until task 004d.** The rule that will
    replace this body (refuse ``http(s)://`` origins, allow a missing origin and
    the extension host's own) cannot be written from evidence we do not have
    yet: whether ``eda.sys_WebSocket`` sends an ``Origin`` at all, and what
    value it carries, is unmeasured. So 004c records and 004d decides.

    One function, one decision: 004d changes this body and nothing else.
    """
    return True


# --------------------------------------------------------------------------
# daemon
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PairingNotice:
    """What the daemon learned when it paired a connector.

    ``repaired`` distinguishes the two ways a pairing record gets written: a
    first-ever pairing ("check this is yours") and a re-pair after the
    connector's storage was reset — which is what sideloading a new build does
    (004f item 2). The wording has to differ, because telling someone to
    revoke a pairing they just legitimately re-made is bad advice.
    """

    fingerprint: str
    client: str
    peer: str
    repaired: bool = False
    #: The fingerprint this pairing replaced, when it replaced one.
    replaced: str | None = None

    def console_lines(self) -> list[str]:
        """The exact text ``bridge start`` prints, in order.

        Fixed here rather than in the CLI so that the message the user is
        *told to act on* ("run: boardwise bridge revoke") and the message the
        tests assert cannot drift apart.
        """
        if self.repaired:
            return [
                f"boardwise bridge: re-paired connector (fingerprint {self.fingerprint}"
                + (f", replacing {self.replaced}" if self.replaced else "")
                + ") — no connector was attached, so this is the usual sign of a "
                "sideloaded build whose extension storage was reset",
                f"  client: {self.client or 'unknown'}  peer: {self.peer}",
                "  if this was not you, run: boardwise bridge revoke",
            ]
        return [
            f"boardwise bridge: paired new connector (fingerprint {self.fingerprint}); "
            "if this was not you, run: boardwise bridge revoke",
            f"  client: {self.client or 'unknown'}  peer: {self.peer}",
        ]


@dataclass
class PendingCall:
    """One forwarded action, waiting for a specific window's answer (023).

    The window is part of the record rather than a second table, because
    everything the daemon does with a pending call is window-scoped: a socket
    closing fails **its own** calls and nobody else's, and a response frame is
    accepted only from the window the request went to. Correlating on the request
    id alone — which is all a single-connector daemon needs — would let the
    second window answer the first window's call, and with several windows open
    that is a routing bug that arrives looking like a correct answer.
    """

    action: str
    window: "WindowConnection"
    future: asyncio.Future[dict[str, Any]]


@dataclass
class WindowConnection:
    """One connected editor window: its socket plus what the daemon knows of it.

    The hub's unit (023). Three questions have to be answerable about each one
    without reading a log — which window it is, which connector build it runs,
    and what it has open — so the answers are kept here rather than derived from
    the socket at every use.

    ``key`` is the daemon's handle for the connection and the identity used in
    every routing decision, error message and audit line. It *is* the instance id
    the window claimed, unless a second **live** socket claimed the same one — in
    which case the newcomer's key is suffixed (``inst-x~2``). Two windows, one
    id, two rows: dropping either would be the invisible failure this hub exists
    to end, and the ambiguity is reported by routing rather than resolved by
    guesswork (023 §今晚不做: no dedup yet).
    """

    websocket: Any
    key: str
    instance_id: str
    client: str = ""
    connector_version: str = ""
    peer: str = "-"
    connected_at: float = field(default_factory=time.time)
    #: ``hello`` when the window named itself, ``connection`` when the id was
    #: invented for this socket because the build predates the field. Recorded
    #: rather than hidden: the two mean different things about what the daemon
    #: can tell apart, and a fabricated id that looks real would be worse than no
    #: id at all.
    instance_id_source: str = "hello"
    #: The project and page this window last reported — from its ``hello`` (021
    #: §2.3) and then refreshed by every response frame's ``context`` (023), so
    #: a user switching projects or documents is followed instead of being frozen
    #: at the handshake. The daemon cannot read any of it itself: ``eda`` is
    #: scoped to one editor window, so all of this is a claim by the connector,
    #: recorded as such. Empty means "not named", never "no project".
    project_name: str = ""
    project_uuid: str = ""
    page_uuid: str = ""
    page_type: str = ""
    #: When this window was last heard from (its ``hello``, or any response frame
    #: it sent). A window connected-but-silent for an hour and one that answered
    #: a second ago look identical in a socket list, and "is the window I am
    #: about to write into still moving?" is the question this answers.
    last_seen: float = field(default_factory=time.time)
    #: How many forwarded calls this window has answered. Per window, because the
    #: interesting fact in a multi-window session is *which* one the AI has been
    #: talking to — something 018's single slot could not express at all.
    routed: int = 0
    #: Serialises this window's **write** actions (023 §per-window 写互斥). Writes
    #: to one editor serialise because that editor is a single thread of truth:
    #: two placements racing in one window is how a half-drawn page happens.
    #: Writes to *different* windows run in parallel, which is the point of a hub.
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_open(self) -> bool:
        """Whether this window's socket is still usable — see :func:`_socket_is_open`."""
        return _socket_is_open(self.websocket)

    def touch(self) -> None:
        self.last_seen = time.time()

    def describe(self) -> str:
        """One line naming this window, for a console or an error message."""
        version = self.connector_version or UNKNOWN_CONNECTOR_VERSION
        return f"window {self.key} (connector {version}, peer {self.peer})"

    def as_status(self) -> dict[str, Any]:
        """The shape carried by ``ping`` and printed by :func:`status_lines`."""
        return {
            # Both ids, always: the key is what a caller routes with, the instance
            # id is what the window calls itself, and when they differ the
            # difference is the news (two connections claiming one id).
            "windowKey": self.key,
            "instanceId": self.instance_id,
            "instanceIdSource": self.instance_id_source,
            "client": self.client,
            "connectorVersion": self.connector_version or None,
            "peer": self.peer,
            "connectedAt": self.connected_at,
            "lastSeen": self.last_seen,
            "routed": self.routed,
            # Added 2026-09-22 (021 §2.3), and always present so a caller can use
            # `is None` rather than `in`. `None` is the field's own way of
            # saying "this window named no project". The page joined them in 023
            # and is `None` until the connector answers something.
            "projectName": self.project_name or None,
            "projectUuid": self.project_uuid or None,
            "pageUuid": self.page_uuid or None,
            "pageType": self.page_type or None,
        }


def window_listing(windows: Iterable[WindowConnection]) -> str:
    """``projectName (instanceId)`` for each window, comma-separated (023).

    The single rendering of "which windows are online", used by every routing
    error. A caller told its project hint matched nothing needs the list more
    than it needs the sentence around it, so the format is the one the task book
    fixes — and the key, not the instance id, is what is printed, because the key
    is what is unambiguous when two connections claim one id.

    Empty list → ``"(none)"``, so a message built from it can never end in a
    dangling colon.
    """
    rendered = [
        f"{window.project_name or window.project_uuid or '(no project)'} ({window.key})"
        for window in windows
    ]
    return ", ".join(rendered) if rendered else "(none)"


@dataclass
class BridgeDaemon:
    """Routes frames between CLI callers and the connected editor windows."""

    token: str
    home: Path = field(default_factory=lambda: BOARDWISE_HOME)
    #: Every connected editor window, keyed by its hub key (the ``hello``
    #: ``instanceId``, suffixed when two live sockets claim one). **All of them**:
    #: 023 replaced the single-active slot with a registry, so a second window is
    #: registered instead of refused, and this dict is what a caller routes into.
    #: Insertion order is connection order, which is also the order ``status``
    #: prints — the window that has been there longest first.
    windows: dict[str, WindowConnection] = field(default_factory=dict)
    #: request id -> the call, its target window and its future. The window is
    #: part of the value so a response can be checked against the window it was
    #: sent to (023): with several windows open, "some socket answered with this
    #: id" is not the same fact as "the window I asked answered".
    pending: dict[str, PendingCall] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    #: Called once per first-time pairing, so the operator is told out loud.
    #: A callback rather than a print: this module is a library, and the tests
    #: collect notices instead of capturing stdout.
    on_pairing: Callable[[PairingNotice], None] | None = None

    # -- handshake ------------------------------------------------------

    async def _handshake(self, websocket: ServerConnection, peer: str = "-") -> Connection:
        """Validate the opening ``hello`` and return the authenticated role.

        Order matters, and is not the historical order: **role, then the empty
        token check, then protocol version, then the secret.** Version comes
        before pairing on purpose — committing a pairing record for a connector
        we cannot talk to would lock out the working one that comes next, with
        an ``UNAUTHENTICATED`` that says nothing about the real problem.
        """
        raw = await asyncio.wait_for(websocket.recv(), timeout=HELLO_TIMEOUT)
        frame = decode_frame(raw)
        if frame.get("action") != "hello":
            raise BridgeError(
                ErrorCodes.PROTOCOL_VIOLATION,
                "first frame must be 'hello'",
                {"action": frame.get("action")},
            )
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            raise BridgeError(ErrorCodes.BAD_REQUEST, "hello.params must be an object")

        role = params.get("role")
        if role not in (ROLE_CONNECTOR, ROLE_CLI):
            raise BridgeError(
                ErrorCodes.BAD_REQUEST,
                f"hello.params.role must be one of connector|cli, got {role!r}",
            )

        provided = params.get("token")
        # Pairing is not a way in for a client with no random source of its
        # own: an absent or empty token is refused before either branch, and
        # therefore never becomes a pairing record.
        if not isinstance(provided, str) or not provided:
            raise BridgeError(ErrorCodes.UNAUTHENTICATED, "bad or missing token")

        reported = str(params.get("protocol") or "")
        if reported and _major(reported) != _major(PROTOCOL_VERSION):
            raise BridgeError(
                ErrorCodes.VERSION_MISMATCH,
                f"connector speaks {reported}, daemon speaks {PROTOCOL_VERSION}",
            )

        client = str(params.get("client") or "")
        # Optional, and deliberately so: a connector built before 0.4.1 does
        # not send it and must still be able to connect. Its absence is
        # recorded as "(version unknown)" rather than treated as a fault.
        version = params.get("connectorVersion")
        version = version.strip() if isinstance(version, str) else ""
        if role == ROLE_CLI:
            if not _tokens_equal(provided, self.token):
                raise BridgeError(ErrorCodes.UNAUTHENTICATED, "bad or missing token")
        else:
            self._authenticate_connector(provided, client, peer)

        connection = Connection(
            role=role,
            client=client,
            protocol=reported or PROTOCOL_VERSION,
            connector_version=version,
            authenticated=True,
        )
        # Daemon-side bookkeeping, not wire-visible (see `Connection`'s own
        # docstring): which extension *instance* this socket claims to be. Set
        # here because this is the only place the `hello` params exist; read by
        # `_serve`, which decides whether the instance may have the bridge, and
        # by the `disconnect` record so the log names it. A CLI connection has
        # no instance and gets none — inventing one would only make `status`
        # noisier.
        if role == ROLE_CONNECTOR:
            connection.instance_id, connection.instance_id_source = _instance_identity(params)
            # Which project this *window* has open (021 §2.3). Optional, like
            # `instanceId`, and optional for a stronger reason: the daemon has
            # no way of reading it itself (`eda` is window-scoped), so an
            # absent value is recorded as absent rather than filled with the
            # focused project — which would be the project of a different window.
            connection.project_name, connection.project_uuid = _project_identity(params)
        return connection

    def _authenticate_connector(self, provided: str, client: str, peer: str) -> None:
        """Trust the first connector; require an exact match afterwards.

        Reads the pairing record from disk every time (see
        :func:`load_connector_token`) so a ``revoke`` from another process
        takes effect on the very next connection.

        One exception, added 2026-09-16 (004f item 2). **Sideloading a new
        connector build resets the editor's extension storage**, so the new
        build generates a fresh token and is then refused by the pairing it
        itself wrote on the previous run — an ``UNAUTHENTICATED`` loop that
        cost several manual ``bridge revoke`` round trips. The fix keys on the
        one fact that makes the new connector legitimate: **no connector is
        currently attached**. The paired one is gone (editor closed, or its
        storage — and therefore its socket — was reset), so the newcomer is
        not displacing a live peer; it is the only candidate there is.

        When a connector *is* attached the refusal stands. Displacing a live,
        correctly-paired connector would let anything on loopback steal the
        pairing, which is precisely what pairing exists to prevent. That case
        is also self-explanatory to the user, so the error names it.

        **"Attached" means any window (023).** With a hub there is no single
        active instance to ask, so the test is :meth:`has_connector` — one live
        connector socket, any number of them. The strength of the rule is
        unchanged: an unknown token may only take over a pairing **nobody** is
        using, never one a live window is connected with. What changed is only
        that "live" is now a set rather than a slot.
        """
        paired = load_connector_token(self.home)
        if paired is None:
            self._pair(provided, client, peer, repaired=False)
            return
        if _tokens_equal(provided, paired):
            return
        # Liveness read from the sockets themselves (:meth:`live_windows`), not
        # from whether the handler has cleared its bookkeeping yet: a reload
        # closes the old socket and the next instance arrives while that
        # `finally` is still pending, and that path has to work (018 §A).
        if self.has_connector():
            raise BridgeError(
                ErrorCodes.UNAUTHENTICATED,
                "this connector is not the paired one and a connector is already "
                "connected; if you just sideloaded a new build, close it (or run "
                "'boardwise bridge revoke' on the daemon host) and try again",
                {"pairedFingerprint": connector_fingerprint(paired)},
            )
        previous = connector_fingerprint(paired)
        self._pair(provided, client, peer, repaired=True, previous=previous)

    def _pair(
        self,
        provided: str,
        client: str,
        peer: str,
        *,
        repaired: bool,
        previous: str | None = None,
    ) -> None:
        """Write the pairing record and announce it, for a first or a re-pair."""
        store_connector_token(provided, self.home)
        fingerprint = connector_fingerprint(provided) or ""
        self.audit(
            action=AUDIT_REPAIRING if repaired else AUDIT_PAIRING,
            role=ROLE_CONNECTOR, ok=True, client=client, peer=peer,
            fingerprint=fingerprint,
            **({"replacedFingerprint": previous} if repaired and previous else {}),
        )
        if self.on_pairing is not None:
            try:
                self.on_pairing(PairingNotice(
                    fingerprint=fingerprint,
                    client=client,
                    peer=peer,
                    repaired=repaired,
                    replaced=previous,
                ))
            except Exception:  # a noisy console must not fail the handshake
                pass

    # -- the hub (023) ---------------------------------------------------

    def live_windows(self) -> list[WindowConnection]:
        """Every registered window whose socket is still open, oldest first.

        Liveness is read from the socket, not from bookkeeping: a socket that is
        no longer ``OPEN`` is *not* an online window even if its handler has not
        yet run its ``finally``. That gap is exactly where a reload happens — the
        old socket dies, the new one arrives — and calling a dying socket
        "connected" would route the next request into a socket that is gone.

        This is the single answer to "which windows are online", and every
        routing message is built out of it.
        """
        return [window for window in self.windows.values() if window.is_open()]

    def has_connector(self) -> bool:
        """Whether any connector socket is open right now.

        The same liveness rule as :meth:`live_windows`, and deliberately the one
        ``ping``, the pairing check and the routing all use: a status that says
        "connected" while routing refuses, or the reverse, is worse than either
        answer on its own.
        """
        return any(window.is_open() for window in self.windows.values())

    def window_for_instance(self, instance_id: str) -> WindowConnection | None:
        """The live window that answers to this name, or ``None``.

        Two spellings both resolve, because a caller writing ``--instance`` has
        one of them in hand and no way to tell which: the **hub key** a
        connection registered under, and the **instance id** the window claimed
        for itself. They differ only when two live sockets claimed one id — where
        the second got a suffixed key (``inst-x~2``) — and that is exactly the
        case this ordering settles: the **key** is matched first, so ``inst-x``
        reaches the unsuffixed connection and ``inst-x~2`` the other one, both
        without a guess. Falling back to the instance id afterwards keeps the
        ordinary case (one connection per id, key == id) a plain lookup.

        Matching the *live* windows only: a hub entry whose socket is gone is not
        a window anybody can address, and returning it would route the next
        request into a socket that no longer exists.
        """
        wanted = str(instance_id or "").strip()
        if not wanted:
            return None
        live = self.live_windows()
        for window in live:
            if window.key == wanted:
                return window
        for window in live:
            if window.instance_id == wanted:
                return window
        return None

    def window_of(self, connection: Connection, websocket: Any = None) -> WindowConnection | None:
        """The hub entry a connection registered as, if it registered one.

        ``websocket`` is optional and, when given, must be the entry's own socket:
        a reload can hand the same key to a *new* socket while the old one's
        ``finally`` is still running, and "the key matches" is then true of two
        different windows.
        """
        window = self.windows.get(connection.window_key) if connection.window_key else None
        if window is None:
            return None
        if websocket is not None and window.websocket is not websocket:
            return None
        return window

    def register(
        self,
        websocket: ServerConnection,
        connection: Connection,
        peer: str = "-",
    ) -> WindowConnection:
        """Welcome one authenticated connector into the hub (023).

        This replaced 018's refusal. There is no slot to take any more, so two,
        three or four windows all register and each stays reachable — which is
        what 岳 asked for: three or four windows is an ordinary Tuesday, not a
        contention to resolve.

        The ``hello`` audit record is written here, before the ack goes out, as
        it always was, and now carries the hub key plus how many windows are
        online: "which windows were open at 17:10?" has to be answerable after
        one of them has closed.
        """
        key, took_over, duplicate = self._claim_key(connection.instance_id)
        now = time.time()
        window = WindowConnection(
            websocket=websocket,
            key=key,
            instance_id=connection.instance_id or key,
            client=connection.client,
            connector_version=connection.connector_version,
            peer=peer,
            connected_at=now,
            instance_id_source=connection.instance_id_source or "hello",
            project_name=connection.project_name,
            project_uuid=connection.project_uuid,
            page_uuid=connection.page_uuid,
            page_type=connection.page_type,
            last_seen=now,
        )
        self.windows[key] = window
        # The connection and the hub entry both need to know the key: the handler
        # addresses the hub by it, and a CLI connection (which registers nothing)
        # leaves it empty.
        connection.window_key = key
        self.audit(
            action="hello", role=connection.role, ok=True, peer=peer,
            client=client_with_version(connection.client, connection.connector_version),
            connectorVersion=connection.connector_version or None,
            instanceId=window.instance_id,
            instanceIdSource=window.instance_id_source,
            windowKey=key,
            tookOverFrom=took_over,
            duplicateInstanceId=duplicate,
            projectName=window.project_name or None,
            projectUuid=window.project_uuid or None,
            # How many windows are online *after* this one joined, so "was this
            # the first or the fourth?" needs no reconstruction from the log.
            windowsOnline=len(self.live_windows()),
        )
        return window

    def _claim_key(self, instance_id: str) -> tuple[str, str | None, str | None]:
        """Pick this connection's hub key: ``(key, took_over, duplicate)``.

        Three cases, and the third is why this exists as a method at all:

        - **key free** — the ordinary case: nobody, or nobody still registered,
          holds this instance id;
        - **key held by a socket that is gone** — the reload path, which has to
          stay smooth: the dead entry is displaced, the key is reused, and the
          takeover is *reported* so the log names what it replaced;
        - **key held by a live socket** — the same window connected twice (the
          3.2.175 double activation). Both are kept and the newcomer gets a
          suffixed key (``inst-x~2``). 023 §今晚不做 says no dedup tonight, and
          the honest answer to two connections claiming one id is two rows plus a
          routing ambiguity when they also claim one project — never a silently
          dropped connection.
        """
        claimed = (instance_id or "").strip() or f"conn-{secrets.token_hex(8)}"
        existing = self.windows.get(claimed)
        if existing is None:
            return claimed, None, None
        if existing.is_open():
            index = 2
            while f"{claimed}{WINDOW_KEY_SEPARATOR}{index}" in self.windows:
                index += 1
            return f"{claimed}{WINDOW_KEY_SEPARATOR}{index}", None, claimed
        del self.windows[claimed]
        return claimed, claimed, None

    def unregister(self, window: WindowConnection) -> None:
        """Remove one window from the hub. Idempotent, and identity-checked.

        Identity rather than key: a reload can reuse a key while the dead
        socket's handler is still on its way here, and removing by key would then
        delete the *new* window — the reload path failing in the one place 018
        already taught us to be careful about.
        """
        if self.windows.get(window.key) is window:
            del self.windows[window.key]

    def _drop_socket(self, connection: Connection, websocket: Any) -> WindowConnection | None:
        """Forget the window on this socket, if it registered one. Returns it.

        Called from the handler's single ``finally``, so every way a socket can
        end leaves the hub without it: clean close, refused handshake, gone peer.
        A CLI connection, or one that never finished its handshake, registered
        nothing and this is a no-op for it.
        """
        window = self.window_of(connection, websocket)
        if window is None:
            # Identity sweep, for the case where the key was reassigned to a new
            # socket before this ran: the old socket must still leave no trace.
            window = next(
                (w for w in self.windows.values() if w.websocket is websocket), None
            )
        if window is not None:
            self.unregister(window)
        return window

    def apply_response_context(self, window: WindowConnection, frame: dict[str, Any]) -> tuple[str, ...]:
        """Merge a response frame's ``context`` into the window's bookkeeping.

        Thin wrapper over :func:`boardwise.bridge.protocol.merge_context`, in one
        place because two things happen together here: the window is marked as
        *just heard from* (any response proves it alive, with or without a
        context), and whatever it reported about its project and page becomes the
        truth the router works from. Frozen routing information is the bug this
        refresh exists to prevent — 岳 switching documents mid-session must move
        the routing, not be ignored until the next reconnect.
        """
        window.touch()
        return merge_context(window, frame.get("context"))

    # -- routing (023) ---------------------------------------------------

    def route(
        self,
        target_project: Any = "",
        action: str = "",
        target_instance: Any = "",
    ) -> WindowConnection:
        """Decide which window answers this request, or refuse and say why.

        The rule, in the order the caller's information runs out:

        - **an instance hint, matching a window** → that window. Checked *first*
          and by exact key / instance id (:meth:`window_for_instance`), because
          an instance id names one connection while a project name can be
          claimed by several — and because it is the only hint that still works
          when no window can read a project at all (editor just restarted:
          measured 2026-09-22, three windows, every ``context`` null);
        - **an instance hint, no match** → ``WINDOW_NOT_CONNECTED``, listing the
          windows that are online. Same shape as the project refusal below:
          the caller names one of *those*;
        - **a project hint, exactly one match** → that window. Matched by project
          *name* or *uuid* against each window's live context, so a user who
          switched project a minute ago is found under their new project;
        - **a project hint, no match** → ``PROJECT_NOT_CONNECTED``, listing the
          windows that are online. The caller names one; nothing is guessed;
        - **a project hint, several matches** → ``PROJECT_AMBIGUOUS``, listing
          the candidates. Deliberately not resolved by "pick the newest": a write
          sent to the wrong window is the failure 018 measured, and a plausible
          guess is exactly what makes it invisible;
        - **no hint, one window** → that window. The single-window case is
          unchanged, which is what keeps every existing caller working;
        - **no hint, several windows** → ``WINDOW_UNSPECIFIED``, listing them.
          "Which window did I mean?" is a question only the caller can answer,
          and an error it can read is cheaper than a write that landed somewhere
          plausible.

        No window at all is ``NO_CONNECTOR`` — the same code and sentence as
        before the hub, because when nothing is connected "is EasyEDA running?"
        is a better thing to say than "that project is not open".
        """
        live = self.live_windows()
        if not live:
            prefix = f"{action} " if action else ""
            raise BridgeError(
                ErrorCodes.NO_CONNECTOR,
                f"{prefix}needs the editor: no connector is connected. "
                "Is EasyEDA running with the boardwise extension enabled?",
            )
        instance = self._target_instance(target_instance)
        if instance:
            window = self.window_for_instance(instance)
            if window is not None:
                return window
            raise BridgeError(
                ErrorCodes.WINDOW_NOT_CONNECTED,
                f"no connected window is instance {instance!r}; online windows: "
                f"{window_listing(live)}",
                {"targetInstance": instance, "candidates": [w.as_status() for w in live]},
            )
        hint = self._target_project(target_project)
        if hint:
            matched = [
                window
                for window in live
                if hint in (window.project_name, window.project_uuid)
            ]
            if len(matched) == 1:
                return matched[0]
            if not matched:
                raise BridgeError(
                    ErrorCodes.PROJECT_NOT_CONNECTED,
                    f"no connected window has project {hint!r} open; online windows: "
                    f"{window_listing(live)} — a window can also be named by its "
                    "instance id (boardwise bridge call --instance INSTANCE_ID)",
                    {"targetProject": hint, "candidates": [w.as_status() for w in live]},
                )
            raise BridgeError(
                ErrorCodes.PROJECT_AMBIGUOUS,
                f"project {hint!r} matches {len(matched)} connected windows "
                f"({window_listing(matched)}); nothing was forwarded — close the "
                "duplicate window or name one of them",
                {"targetProject": hint, "candidates": [w.as_status() for w in matched]},
            )
        if len(live) == 1:
            return live[0]
        raise BridgeError(
            ErrorCodes.WINDOW_UNSPECIFIED,
            f"{len(live)} editor windows are connected and the request named no "
            "project; re-send with a project hint (boardwise bridge call --project "
            "NAME_OR_UUID) or an instance id (boardwise bridge call --instance "
            f"INSTANCE_ID) — online windows: {window_listing(live)}",
            {"candidates": [w.as_status() for w in live]},
        )

    @staticmethod
    def _target_instance(value: Any) -> str:
        """Validate the caller's ``targetInstance`` hint into a plain string.

        The same rule as :meth:`_target_project`, and for the same reason: a
        non-string is a ``BAD_REQUEST`` rather than "treated as absent", because
        silently dropping a hint sends the call to a window the caller did not
        choose. Stripped, so a shell's stray whitespace cannot turn a correct
        instance id into a refusal.
        """
        if value is None:
            return ""
        if not isinstance(value, str):
            raise BridgeError(
                ErrorCodes.BAD_REQUEST,
                "targetInstance must be an instance id string, got "
                f"{type(value).__name__}",
            )
        return value.strip()

    @staticmethod
    def _target_project(value: Any) -> str:
        """Validate the caller's ``targetProject`` hint into a plain string.

        A non-string is a ``BAD_REQUEST`` rather than "treated as absent": a
        caller that sent ``{"name": "test2"}`` meant to route somewhere, and
        silently dropping the hint would send the call to a window it did not
        choose — the failure this whole feature is about, arrived at through
        politeness.
        """
        if value is None:
            return ""
        if not isinstance(value, str):
            raise BridgeError(
                ErrorCodes.BAD_REQUEST,
                "targetProject must be a project name or uuid string, got "
                f"{type(value).__name__}",
            )
        return value.strip()

    # -- dispatch -------------------------------------------------------

    async def handle_request(
        self,
        action: str,
        params: dict[str, Any],
        role: str,
        target_project: Any = "",
        routed: dict[str, Any] | None = None,
        target_instance: Any = "",
    ) -> Any:
        """Answer one request. Shared by the socket handler and the tests.

        ``target_project`` / ``target_instance`` are the caller's window hints —
        the frame's top-level ``targetProject`` / ``targetInstance`` (023) — and
        ``routed`` is an out-parameter that receives ``{"windowKey": …}`` once a
        window has been chosen: the handler writes the audit line and the relayed
        frame, so it is the caller that needs to know *which* window this request
        went to, and a return value cannot carry it (an error has one too).
        """
        spec = action_spec(action)
        if spec is None:
            raise BridgeError(ErrorCodes.UNKNOWN_ACTION, f"unknown action {action!r}")
        if spec.owner == "daemon":
            return self._local_action(action)
        params = self._gate_confirmation(spec, params)
        window = self.route(target_project, action, target_instance)
        if routed is not None:
            routed["windowKey"] = window.key
        if spec.risk == "read":
            return await self._forward(action, params, role, window)
        # Writes serialise **per window** and only per window (023 §per-window
        # 写互斥). One editor is a single thread of truth — two placements racing
        # inside one window is how a half-drawn page happens — while two windows
        # are two editors, and making them wait for each other would turn the
        # hub back into a queue. Reads never take the lock: `doc.list` cannot
        # corrupt anything.
        async with window.write_lock:
            return await self._forward(action, params, role, window)

    def context_for_frame(self, routed: dict[str, Any] | None) -> dict[str, Any]:
        """The answering window's context, for the frame relayed back to the caller.

        Read *after* the call, deliberately: the connector refreshes its context
        in every response, so this is the window's state at the moment it ran the
        action — which is the fact a caller verifying "did that land in test2?"
        actually needs. Empty when no window was routed to (a routing refusal) or
        when the window named nothing.
        """
        key = str((routed or {}).get("windowKey") or "")
        window = self.windows.get(key) if key else None
        return context_of(window) if window is not None else {}

    def _routed_audit_fields(self, routed: dict[str, Any] | None) -> dict[str, Any]:
        """The audit fields naming the window a request was routed to.

        Every forwarded call records `windowKey` and, when the window named one,
        its project. "Which project did that write land in?" has to be answerable
        from the request's own line: the window may well be closed by the time
        anyone asks, and the alternative — reconstructing it from the `hello` and
        `disconnect` records around it — is the kind of inference that gets
        written down wrong.
        """
        key = str((routed or {}).get("windowKey") or "")
        if not key:
            return {}
        window = self.windows.get(key)
        fields: dict[str, Any] = {"windowKey": key}
        if window is not None and window.project_name:
            fields["projectName"] = window.project_name
        return fields

    def _gate_confirmation(self, spec: Action, params: dict[str, Any]) -> dict[str, Any]:
        """Enforce the creation gate, and consume ``confirm`` either way.

        ``create`` actions produce a new document, and 岳翔宇's hard rule is that
        creating one must be asked for first — so this is the **single** choke
        point, on the daemon, rather than a check each caller is trusted to
        repeat. The connector stays unaware of the concept: the parameter is
        stripped here so it never appears in a forwarded frame, which also
        means a connector-side action cannot be talked into creating something
        the daemon declined.

        The decision is keyed on ``risk``, **not** on whether the entry lists
        ``confirm`` among its params. Keying it on the params list would make
        the gate fail *open*: an entry that forgot to declare the parameter
        would silently never be refused. Missing documentation must not disable
        a gate — the self-consistency test asserts the declaration separately,
        so a caller can still discover the parameter from ``--help``.

        ``confirm is True`` (identity, not truthiness): ``"yes"``, ``1`` and
        ``"true"`` are all refused, because a gate that accepts anything
        truthy is a gate nobody can reason about.
        """
        forwarded = {key: value for key, value in params.items() if key != "confirm"}
        if spec.risk != "create":
            return forwarded
        if params.get("confirm") is True:
            return forwarded
        raise BridgeError(
            ErrorCodes.CONFIRMATION_REQUIRED,
            f"{spec.name} creates a new document; re-send with confirm: true "
            f"(got {params.get('confirm')!r}). Nothing was forwarded to the editor.",
            {"action": spec.name, "risk": spec.risk, "confirm": params.get("confirm")},
        )

    def _local_action(self, action: str) -> dict[str, Any]:
        if action == "ping":
            return {
                "pong": True,
                # The daemon's own version, so a caller can tell "the daemon
                # answering me" from "the daemon I or my CLI was built from".
                # `boardwise doctor` is that caller: the action catalogue is a
                # load-time constant, so a daemon left running across a
                # checkout answers the new actions with UNKNOWN_ACTION, and
                # this field is what turns that into a diagnosis.
                "version": BOARDWISE_VERSION,
                "connector": self.has_connector(),
                # Fingerprint only — `bridge status` prints this, and the log
                # panel and terminal are both places a secret must never reach.
                "pairedFingerprint": connector_fingerprint(
                    load_connector_token(self.home)
                ),
                # Every online window, oldest first (023) — what `bridge status`
                # renders, and what a caller reads to decide which window to
                # address. This was one `activeInstance` plus a `recentRejections`
                # list before the hub existed; the rejections are gone because
                # nobody is turned away any more, and the list of *reachable*
                # windows is strictly better information than a list of the ones
                # that were not.
                "windows": [window.as_status() for window in self.live_windows()],
            }
        # "hello" during the request phase is a protocol violation.
        raise BridgeError(
            ErrorCodes.PROTOCOL_VIOLATION, "hello may only be sent once, as the first frame"
        )

    async def _forward(
        self,
        action: str,
        params: dict[str, Any],
        role: str,
        window: WindowConnection,
    ) -> Any:
        """Send one action to **one window** and wait for that window's answer.

        The window is handed in by :meth:`handle_request` rather than looked up
        here, so the routing decision and the send cannot disagree — and so a
        request can never be written into a socket whose per-window lock nobody
        took.
        """
        if role != ROLE_CLI:
            raise BridgeError(
                ErrorCodes.BAD_REQUEST, f"role {role!r} may not call editor actions"
            )
        request_id = f"{action}-{secrets.token_hex(4)}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[request_id] = PendingCall(action=action, window=window, future=future)
        window.routed += 1
        window.touch()
        try:
            await window.websocket.send(request_frame(action, params, id=request_id))
            frame = await asyncio.wait_for(future, timeout=timeout_for(action))
        except asyncio.TimeoutError:
            raise BridgeError(
                ErrorCodes.TIMEOUT,
                f"{action} timed out after {timeout_for(action):.0f}s",
            ) from None
        finally:
            self.pending.pop(request_id, None)
        if frame.get("ok"):
            return frame.get("data")
        error = frame.get("error") or {}
        raise BridgeError(
            str(error.get("code") or ErrorCodes.CONNECTOR_ERROR),
            str(error.get("message") or "connector failed"),
            error.get("detail"),
        )

    def resolve_connector_response(
        self,
        frame: dict[str, Any],
        window: WindowConnection | None = None,
    ) -> bool:
        """Hand a connector frame to whoever is waiting for it.

        ``window`` is the hub entry the frame arrived on. When it is given, the
        answer is accepted **only** if it came from the window the request went
        to (023): with several windows open, the request id is a correlation hint
        rather than a proof, and a second window answering the first window's
        call would arrive looking exactly like a correct answer. Returns whether
        the frame resolved anything.
        """
        call = self.pending.get(str(frame.get("id")))
        if call is None or call.future.done():
            return False
        if window is not None and call.window is not window:
            return False
        call.future.set_result(frame)
        return True

    # -- audit ----------------------------------------------------------

    def audit(self, **fields: Any) -> None:
        """Append one JSON line. Never raises: logging must not break a call."""
        append_audit(self.home, **fields)

    # -- socket ---------------------------------------------------------

    async def handler(self, websocket: ServerConnection) -> None:
        """Audit `connect` / `disconnect` around one socket's whole life.

        The `disconnect` record is written from a single `finally`, so *every*
        way a socket can end — banner refused, no hello, bad token, clean
        close — produces a matching pair. Getting this wrong cost real
        debugging time in task 004b: "did the editor ever connect, and if so
        what happened to it?" has to be answerable from the log alone, and a
        missing record is indistinguishable from a connection that never was.
        """
        connection = Connection()
        peer = _peer_of(websocket)
        headers = client_headers(websocket)
        # Checked before the banner, so a peer we refuse is refused at the
        # handshake rather than after being told what this daemon is.
        if not check_origin(headers):
            self.audit(action="connect", role="-", ok=False, peer=peer,
                       error="origin refused", **headers)
            try:
                await websocket.close()
            except (websockets.ConnectionClosed, OSError):
                pass
            return
        # Audited before anything else: when a real editor fails to connect,
        # "did a TCP connection even arrive?" is the first question, and the
        # audit log is the only place that answers it. The Origin/User-Agent
        # are recorded here as evidence for task 004d's rule (task 004c).
        self.audit(action="connect", role="-", ok=True, peer=peer, **headers)
        try:
            await self._serve(websocket, connection, peer)
        except (websockets.ConnectionClosed, OSError):
            pass
        finally:
            # The window leaves the hub here and nowhere else, so *every* way a
            # socket can end — clean close, bad token, gone peer, editor reload —
            # takes it out of the routing table. A connection that is still in
            # the table after its socket died is a request that will be sent into
            # nothing.
            window = self._drop_socket(connection, websocket)
            # Only this socket's calls fail. With one connector, "the connector
            # disconnected" could fail them all; with a hub, failing another
            # window's in-flight call because a *different* window closed would
            # invent a failure that never happened.
            for call in list(self.pending.values()):
                if call.window.websocket is websocket and not call.future.done():
                    call.future.set_exception(
                        BridgeError(ErrorCodes.CONNECTOR_ERROR, "connector disconnected")
                    )
            self.audit(action="disconnect", role=connection.role or "-", ok=True,
                       peer=peer, actions=connection.seen_actions,
                       **({"instanceId": connection.instance_id}
                          if connection.instance_id else {}),
                       **({"windowKey": window.key} if window is not None else {}),
                       # The window's project and page *as last known*, recorded
                       # at the moment it leaves: the audit is where the identity
                       # of a window that has since closed survives — which is
                       # what makes "that write went to the window on 反激辅助电源"
                       # checkable after the fact.
                       **({"projectName": window.project_name or None,
                           "projectUuid": window.project_uuid or None,
                           "pageUuid": window.page_uuid or None,
                           "pageType": window.page_type or None,
                           "routed": window.routed}
                          if window is not None else {}))

    async def _serve(self, websocket: ServerConnection, connection: Connection, peer: str) -> None:
        """Banner, handshake, then serve frames until the socket closes."""
        # Speak first. The editor's socket API gives no connect callback we can
        # rely on (task 004b: our hello used to be sent from that callback and
        # never went out), so the connector cannot know the socket is up until
        # something arrives on it. This frame is that something.
        try:
            await websocket.send(banner_frame())
        except (websockets.ConnectionClosed, OSError):
            self.audit(action="connect", role="-", ok=False, peer=peer,
                       error="banner refused")
            return

        try:
            authenticated = await self._handshake(websocket, peer)
        except asyncio.TimeoutError:
            # Silence now means something specific: the client got our banner
            # and did not answer, so the fault is on its side of the wire.
            reason = f"no hello within {HELLO_TIMEOUT:.0f}s"
            self.audit(action="hello", role="-", ok=False, peer=peer,
                       error=ErrorCodes.UNAUTHENTICATED, reason=reason)
            await self._close(websocket, ErrorCodes.UNAUTHENTICATED, reason)
            return
        except BridgeError as exc:
            self.audit(action="hello", role="-", ok=False, peer=peer, error=exc.code)
            await self._close(websocket, exc.code, exc.message)
            return
        except (websockets.ConnectionClosed, OSError):
            self.audit(action="hello", role="-", ok=False, peer=peer,
                       error="closed before hello")
            return

        # Copied into the object the caller's `finally` audits, so the close
        # record names the role instead of a bare "-".
        connection.role = authenticated.role
        connection.client = authenticated.client
        connection.protocol = authenticated.protocol
        connection.connector_version = authenticated.connector_version
        connection.authenticated = True
        connection.instance_id = authenticated.instance_id
        connection.instance_id_source = authenticated.instance_id_source
        # Same reason as the instance id above: the handshake parsed these off
        # the `hello` params, and this is the object the rest of the daemon
        # (the hub, `status`, the audit) reads them from (021 §2.3). 023 added
        # the page, which cannot be known at handshake time — no action has run
        # yet — so it starts empty and is filled by the first response context.
        connection.project_name = authenticated.project_name
        connection.project_uuid = authenticated.project_uuid

        # Every authenticated connector is registered (023), before the ack goes
        # out, exactly where the single-active guard used to run. There is no
        # check-then-install pair left to keep atomic: registering cannot
        # conflict with registering, so a second window arriving in the same
        # instant as the first just... registers. What 018 defended (a write
        # landing in a project nobody chose) is now defended by *routing*: the
        # caller names the window, and an unnamed request among several is
        # refused rather than resolved.
        if connection.role == ROLE_CONNECTOR:
            self.register(websocket, connection, peer)

        await websocket.send(response_frame("hello", {
            "role": connection.role,
            "protocol": PROTOCOL_VERSION,
            "serverTime": time.time(),
            # What the daemon has on file for this connector, so the editor can
            # show the same fingerprint in `About…` that `bridge status` shows.
            # A fingerprint and not the token: this frame is logged, and the
            # token is the only secret in the system that must never be.
            "paired": load_connector_token(self.home) is not None,
            "fingerprint": connector_fingerprint(
                load_connector_token(self.home)
            ),
            # The oldest connector build this daemon works with, so a build that
            # is too old can say so in the editor instead of failing later at
            # some unrelated action (018 §A/§B). Announced, not enforced: the
            # refusal path for a *version* would have to run before the token is
            # checked, and a version comparison is not a reason to hang up on a
            # connector that still works.
            "minConnectorVersion": MIN_CONNECTOR_VERSION,
            # How many windows this daemon is holding after this one joined
            # (023), so the extension can *tell the user* that other windows are
            # connected instead of discovering it when a call comes back
            # WINDOW_UNSPECIFIED. Reported, not acted on: deciding which window a
            # caller meant is the daemon's business, not the connector's.
            "windowsOnline": len(self.live_windows()),
            # The hub key this connection registered under, so the editor can name
            # itself the way the daemon (and `bridge status`) does — including the
            # ``~2`` suffix when a second socket claimed the same instance id.
            "windowKey": connection.window_key or None,
        }))

        try:
            async for raw in websocket:
                await self._on_frame(websocket, connection, raw)
        except websockets.ConnectionClosed:
            pass

    async def _on_frame(self, websocket: ServerConnection, connection: Connection, raw: Any) -> None:
        started = time.perf_counter()
        try:
            frame = decode_frame(raw)
        except BridgeError as exc:
            await websocket.send(error_frame(None, exc))
            return

        # A connector frame carrying ok= is an answer to something we sent. It
        # also carries that window's live context (023), which is merged here —
        # the one moment the daemon learns anything new about a window it did not
        # ask about.
        if connection.role == ROLE_CONNECTOR and "ok" in frame:
            window = self.window_of(connection, websocket)
            if window is not None:
                self.apply_response_context(window, frame)
            self.resolve_connector_response(frame, window)
            return

        action = str(frame.get("action") or "")
        frame_id = frame.get("id")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        connection.seen_actions.append(action)
        routed: dict[str, Any] = {}
        try:
            data = await self.handle_request(
                action,
                params,
                connection.role,
                frame.get("targetProject", ""),
                routed,
                frame.get("targetInstance", ""),
            )
        except BridgeError as exc:
            self.audit(action=action, role=connection.role, ok=False, error=exc.code,
                       ms=round((time.perf_counter() - started) * 1000, 1),
                       **self._routed_audit_fields(routed))
            await websocket.send(error_frame(
                frame_id, exc, context=self.context_for_frame(routed)))
            return
        except Exception as exc:  # never let a handler kill the socket loop
            self.audit(action=action, role=connection.role, ok=False,
                       error=ErrorCodes.INTERNAL, ms=round((time.perf_counter() - started) * 1000, 1),
                       **self._routed_audit_fields(routed))
            await websocket.send(error_frame(frame_id, BridgeError(
                ErrorCodes.INTERNAL, f"{type(exc).__name__}: {exc}"),
                context=self.context_for_frame(routed)))
            return
        self.audit(action=action, role=connection.role, ok=True,
                   ms=round((time.perf_counter() - started) * 1000, 1),
                   **self._routed_audit_fields(routed))
        await websocket.send(response_frame(
            frame_id, data, context=self.context_for_frame(routed)))

    async def _close(self, websocket: ServerConnection, code: str, message: str) -> None:
        try:
            await websocket.send(error_frame(None, BridgeError(code, message)))
        except (websockets.ConnectionClosed, OSError):
            return
        try:
            await websocket.close()
        except (websockets.ConnectionClosed, OSError):
            pass


def _tokens_equal(provided: Any, expected: str) -> bool:
    return isinstance(provided, str) and secrets.compare_digest(provided, expected)


def _peer_of(websocket: Any) -> str:
    """Best-effort ``host:port`` of the far end, for the audit log.

    Deliberately not a security control — it is only there so that "the
    editor never connected" can be distinguished from "it connected and said
    nothing", which is the difference that mattered during task 004b.
    """
    address = getattr(websocket, "remote_address", None)
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return "-"


def _major(version: str) -> str:
    return version.split(".")[0]


def _socket_is_open(websocket: Any) -> bool:
    """Whether a socket is still usable, per ``websockets``' own state.

    Used instead of "is the attribute set" everywhere the daemon asks whether a
    connector is *attached* (018 §A, and every hub question in 023). The two are
    not the same: the socket dies the moment the peer goes away, while its hub
    entry is only removed when the handler reaches its ``finally`` — and the new
    window arrives inside that gap, which is precisely the reload the routing has
    to keep working through.

    Unknown state counts as open. A socket object with no ``state`` is either an
    older ``websockets`` or a test double, and inventing "closed" for it would
    turn a missing attribute into a vanished window.
    """
    state = getattr(websocket, "state", None)
    if state is None:
        return True
    return str(getattr(state, "name", state)).upper() == "OPEN"


def _instance_identity(params: dict[str, Any]) -> tuple[str, str]:
    """The connector instance id for one connection, and where it came from.

    A connector built before 018 §A sends no ``instanceId``. It must still
    connect — refusing an older editor would break every existing install — so
    the daemon invents an id for **this connection**. The second element of the
    pair says so, because the two are not equally strong evidence: a claimed id
    can tell two windows apart for as long as they live, an invented one can only
    name a socket. In the hub (023) this id is also the connection's key, which is
    why an invented one is spelled ``conn-…``: a key that looked like a claimed
    instance id would hide which windows the daemon can actually tell apart.
    """
    claimed = params.get("instanceId")
    if isinstance(claimed, str) and claimed.strip():
        return claimed.strip(), "hello"
    return f"conn-{secrets.token_hex(8)}", "connection"


def _project_identity(params: dict[str, Any]) -> tuple[str, str]:
    """The project the connecting window reported in ``hello`` (021 §2.3).

    Two optional strings, and their absence means absence. There is nothing to
    fall back to: the daemon's own view of "the current project" is the project
    of whichever window a request was routed to, so filling a blank in with it
    would attribute one window's project to another — the exact confusion this
    field exists to remove, and with several windows in the hub a *guess* about
    the project is a routing decision made out of nothing. Anything that is not a
    non-empty string is treated as not sent, which is also how an old connector
    (neither field) and a newer one that could not read its project arrive here.
    """
    def read(key: str) -> str:
        value = params.get(key)
        return value.strip() if isinstance(value, str) else ""

    return read("projectName"), read("projectUuid")


def _clock(value: Any) -> str:
    """A timestamp as local wall-clock, or ``?`` when it is missing or absurd."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


async def start_server(
    daemon: BridgeDaemon,
    host: str = DEFAULT_HOST,
    port: int = 0,
) -> Any:
    """Start listening and return the ``websockets`` server object.

    ``port=0`` asks the OS for a free port — what the tests use, so they never
    collide with a real daemon on 61190.
    """
    return await serve(
        daemon.handler,
        host,
        port,
        max_size=MAX_FRAME_BYTES,
        ping_interval=None,  # the connector has its own heartbeat
    )


async def serve_forever(
    daemon: BridgeDaemon,
    host: str = DEFAULT_HOST,
    port: int | None = None,
    on_ready: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    """Run until cancelled. Used by ``boardwise bridge start``."""
    server = await start_server(daemon, host, port if port is not None else resolve_port())
    actual = _bound_port(server)
    if on_ready is not None:
        await on_ready(actual)
    try:
        await server.wait_closed()
    except asyncio.CancelledError:
        server.close()
        await server.wait_closed()
        raise


def _bound_port(server: Any) -> int:
    sockets = getattr(server, "sockets", None) or []
    for sock in sockets:
        return int(sock.getsockname()[1])
    return 0
