"""WebSocket daemon: the bridge's server side.

The daemon is the only listening socket in the system. It accepts two kinds of
client (see :mod:`boardwise.bridge.protocol`) and does three jobs:

1. **Authenticate** — every connection must open with ``hello``; anything else
   is closed immediately. The two roles use *different* secrets:
   ``cli`` presents ``~/.boardwise/token`` (written by ``bridge start``, copied
   by the user), while ``connector`` uses trust-on-first-use pairing (below).
2. **Route** — daemon-owned actions (``hello``, ``ping``) are answered here;
   everything else is forwarded to the single connected ``connector`` and its
   answer is relayed back.
3. **Audit** — every request is appended to ``~/.boardwise/audit/<date>.jsonl``
   with role, action, duration and outcome.
4. **Hold exactly one connector** — one editor instance owns the bridge; a
   second one is refused with ``CONNECTOR_ALREADY_ACTIVE`` (audited as
   ``connector_rejected``, announced on the console) while only an instance
   whose socket is already gone is taken over, which is the reload path. Two
   windows taking turns here is what made writes land in whichever project the
   window that happened to be winning had focused (task 018 §A, measured
   2026-09-21).

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
from typing import Any, Awaitable, Callable

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
    decode_frame,
    error_frame,
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
    "AUDIT_CONNECTOR_REJECTED",
    "CONNECTOR_ALREADY_ACTIVE",
    "MIN_CONNECTOR_VERSION",
    "MAX_RECENT_REJECTIONS",
    "UNKNOWN_CONNECTOR_VERSION",
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
    "RejectionNotice",
    "ActiveConnector",
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

#: The audit record that says a connector was **turned away** because another
#: editor instance already holds the bridge (018 §A). Like the lifecycle names
#: above it is not a wire action, so it is not in the action catalogue — it is
#: the record an investigation greps for, which is why the task book fixes it.
AUDIT_CONNECTOR_REJECTED = "connector_rejected"

#: The wire code a refused connector is answered with, before its socket is
#: closed (018 §A). The code itself is declared in
#: :class:`boardwise.bridge.protocol.ErrorCodes` — it travels in ``error.code``
#: and is therefore part of the protocol's vocabulary, not the daemon's. This
#: name stays because it is how the refusal site, the audit reader and the
#: tests already refer to it; the two are the same string by identity, and the
#: contract test in ``tests/test_action_catalogue.py`` pins that.
CONNECTOR_ALREADY_ACTIVE = ErrorCodes.CONNECTOR_ALREADY_ACTIVE

#: Oldest connector build this daemon works with, announced in the ``hello``
#: ack as ``minConnectorVersion`` so the extension can tell the user to update
#: instead of failing later, mysteriously (018 §A/§B). Equal to the shipped
#: connector version today, so nothing is refused *now*: the field exists so
#: that the day a protocol change makes an old bundle dangerous, the mismatch
#: arrives as a toast rather than as a stack trace.
MIN_CONNECTOR_VERSION = "0.4.10"

#: How many refusals the daemon keeps in memory for ``bridge status``. The audit
#: log keeps all of them; this list is bounded because a refused connector backs
#: off and retries, and the extra window may stay open for hours.
MAX_RECENT_REJECTIONS = 5

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
    """The active-instance and refusal lines ``boardwise bridge status`` prints.

    Takes the ``ping`` answer the CLI has already fetched and returns the extra
    lines for it — empty when there is nothing to say, so a fresh daemon with no
    connector and no refusals prints exactly what it printed before. The
    wording lives here rather than in the CLI so it cannot drift from the wire
    keys it renders (018 §A); ``data`` is documented in :meth:`BridgeDaemon._local_action`.

    These are the two lines that answer "why did my write land somewhere else",
    which used to require reading the audit log: *who* holds the bridge, and who
    was turned away for trying to take it.

    **The project half (021 §2.3).** Since 2026-09-22 every connector announces
    its own window's project in ``hello``, so each of those lines ends with a
    ``[project …]`` suffix and one ``projects seen:`` line lists them together.
    That list is the only way to see the *other* windows at all: the bridge
    talks to exactly one editor window, and a window it turns away is still a
    project the user has open. A window that named no project — an old build, or
    a read that failed — gets no suffix and is counted, never guessed at. Lines
    that existed before are unchanged in every byte up to the suffix, so old
    output readers and old greps still match.
    """
    lines: list[str] = []
    active = data.get("activeInstance")
    if isinstance(active, dict) and active.get("instanceId"):
        version = active.get("connectorVersion") or UNKNOWN_CONNECTOR_VERSION
        note = (
            ""
            if active.get("instanceIdSource") == "hello"
            else "  [no instanceId sent — named by connection]"
        )
        lines.append(
            f"  active instance: {active['instanceId']} (connector {version}){note}"
            f"{_project_suffix(active)}"
        )
        if active.get("peer"):
            lines.append(
                f"    peer: {active['peer']}"
                f"  connected: {_clock(active.get('connectedAt'))}"
            )
    for record in data.get("recentRejections") or []:
        if not isinstance(record, dict):
            continue
        version = record.get("connectorVersion") or UNKNOWN_CONNECTOR_VERSION
        lines.append(
            f"  refused connector: {record.get('instanceId') or '?'}"
            f" (connector {version}) at {_clock(record.get('ts'))}"
            f" — {record.get('reason') or 'refused'}"
            f"{_project_suffix(record)}"
        )
    seen = _projects_seen(data)
    if seen:
        lines.append(seen)
    return lines


def _project_label(record: dict[str, Any]) -> str:
    """``name (uuid)`` from one status record, or ``""`` when neither is known.

    Both halves are optional on the wire, so all four combinations are real and
    each is rendered as itself: a connector may have a name and no uuid, or the
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


def _project_name(record: dict[str, Any]) -> str:
    """The project's *name* for the summary line, falling back to its uuid.

    Deliberately not :func:`_project_label`: the summary groups windows by
    project, and it stays readable only if the uuid — which is already printed
    on the instance's own line — is left out of it.
    """
    name = str(record.get("projectName") or "")
    return name or str(record.get("projectUuid") or "")


def _projects_seen(data: dict[str, Any]) -> str:
    """One line naming every project the daemon has been told about, or ``""``.

    Answers 岳's question — "看得到我开了哪几个工程吗?" — from ``bridge status``
    alone: the active window's project, plus one entry per distinct project
    among the refused instances, which are the other editor windows (021
    §实测记录 A1: three projects in three windows of one process).

    Deduplicated by project rather than by refusal: a refused window retries
    every 20–40 s, so the raw list is the same project over and over. A project
    that is both active and refused is spelled that way rather than collapsed —
    the same project in two windows is exactly the case where the bridge's
    single slot matters. Instances that named no project are counted by
    instance id, never listed under a made-up name.

    Silent when *no* project is known: an old connector's output must not grow
    a line saying that nothing is known (see the byte-for-byte test).
    """
    roles: dict[str, list[str]] = {}

    def note(label: str, role: str) -> None:
        entry = roles.setdefault(label, [])
        if role not in entry:
            entry.append(role)

    active = data.get("activeInstance")
    if isinstance(active, dict):
        label = _project_name(active)
        if label:
            note(label, "active")

    unnamed: list[str] = []
    for record in data.get("recentRejections") or []:
        if not isinstance(record, dict):
            continue
        label = _project_name(record)
        if label:
            note(label, "refused")
            continue
        instance = str(record.get("instanceId") or record.get("peer") or "")
        if instance and instance not in unnamed:
            unnamed.append(instance)

    if not roles:
        return ""
    parts = [f"{label} ({', '.join(kinds)})" for label, kinds in roles.items()]
    if unnamed:
        parts.append(f"{len(unnamed)} instance(s) naming no project")
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


@dataclass(frozen=True)
class RejectionNotice:
    """What the daemon learned when it refused a second connector (018 §A).

    The wording lives here rather than in the CLI for the same reason
    :class:`PairingNotice`'s does: the line a user is told to act on and the
    line the tests assert must not be able to drift apart. It is Chinese
    because the person reading it is the editor's user, mid-task, with two
    EasyEDA windows open — not a developer reading a log.
    """

    #: The instance that already holds the bridge (the one to close).
    active_instance_id: str
    active_connector_version: str
    #: The instance that was turned away, for the audit trail and `status`.
    instance_id: str = ""
    connector_version: str = ""
    peer: str = "-"

    def console_lines(self) -> list[str]:
        """The single line the daemon prints, in the task book's wording.

        One line on purpose: it arrives under whatever else the daemon is
        printing, and the only thing it has to achieve is that the user closes
        the other window.
        """
        version = self.active_connector_version or UNKNOWN_CONNECTOR_VERSION
        return [
            "boardwise bridge: 另一个编辑器实例已连接"
            f"（instance {self.active_instance_id}, connector {version}）。"
            "若非预期，请关闭多余的 EasyEDA 窗口"
        ]

    def fallback_lines(self) -> list[str]:
        """The same message in ASCII, for a console that cannot render Chinese.

        Not decoration: a Windows console whose code page is not a CJK one raises
        ``UnicodeEncodeError`` on the line above, and losing it would lose the
        *only* warning the user gets that two windows are fighting over the
        bridge. Same facts, same instruction, different characters.
        """
        version = self.active_connector_version or UNKNOWN_CONNECTOR_VERSION
        return [
            "boardwise bridge: another editor instance is already connected"
            f" (instance {self.active_instance_id}, connector {version}). "
            "If that is not what you expected, close the extra EasyEDA window."
        ]


@dataclass(frozen=True)
class ActiveConnector:
    """The one editor instance that holds the bridge (018 §A).

    Kept apart from the socket it rides on so that three questions are
    answerable without reading the log: which window is connected, which
    connector build it runs, and when it arrived.
    """

    instance_id: str
    client: str
    connector_version: str
    peer: str
    connected_at: float
    #: ``hello`` when the connector named itself, ``connection`` when the id was
    #: invented for this socket because the build predates the field. Recorded
    #: rather than hidden: the two mean different things about what the daemon
    #: can tell apart, and a fabricated id that looks real would be worse than
    #: no id at all.
    instance_id_source: str = "hello"
    #: The project this window reported in ``hello`` (021 §2.3), or empty strings
    #: when it reported none. The daemon cannot read it itself — `eda` is scoped
    #: to one editor window — so this is a claim by the connector, recorded as
    #: such; empty means "not named", never "no project".
    project_name: str = ""
    project_uuid: str = ""

    def describe(self) -> str:
        """One line naming this instance, for a console or a `status` command."""
        version = self.connector_version or UNKNOWN_CONNECTOR_VERSION
        return f"instance {self.instance_id} (connector {version}, peer {self.peer})"

    def as_status(self) -> dict[str, Any]:
        """The shape carried by ``ping`` and printed by :func:`status_lines`."""
        return {
            "instanceId": self.instance_id,
            "instanceIdSource": self.instance_id_source,
            "client": self.client,
            "connectorVersion": self.connector_version or None,
            "peer": self.peer,
            "connectedAt": self.connected_at,
            # Added 2026-09-22 (021 §2.3), and always present so a caller can use
            # `is None` rather than `in`. `None` is the field's own way of
            # saying "this window named no project".
            "projectName": self.project_name or None,
            "projectUuid": self.project_uuid or None,
        }


@dataclass
class BridgeDaemon:
    """Routes frames between CLI callers and the editor connector."""

    token: str
    home: Path = field(default_factory=lambda: BOARDWISE_HOME)
    #: The connected editor extension, if any. **At most one**, and it is never
    #: displaced: while this socket is open a second connector is refused
    #: (018 §A). Which *instance* it is — and that it is still worth trusting —
    #: is :attr:`active` / :meth:`active_instance`, not this field alone.
    connector: ServerConnection | None = None
    #: Which connector instance holds the bridge, when one does.
    active: ActiveConnector | None = None
    #: The last few refusals, newest first, so ``bridge status`` can show them
    #: without anyone parsing a log file (018 §A). Bounded — see
    #: :data:`MAX_RECENT_REJECTIONS`.
    recent_rejections: list[dict[str, Any]] = field(default_factory=list)
    #: id -> Future resolved by the connector's response.
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    #: Called once per first-time pairing, so the operator is told out loud.
    #: A callback rather than a print: this module is a library, and the tests
    #: collect notices instead of capturing stdout.
    on_pairing: Callable[[PairingNotice], None] | None = None
    #: Called once per refused connector, for the same reason — and unlike
    #: :attr:`on_pairing` it has a default action: with no callback installed the
    #: daemon prints the line itself, because the requirement is that the
    #: *console* says it (018 §A) and ``bridge start`` installs no
    #: callback for this yet.
    on_rejection: Callable[[RejectionNotice], None] | None = None

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
        """
        paired = load_connector_token(self.home)
        if paired is None:
            self._pair(provided, client, peer, repaired=False)
            return
        if _tokens_equal(provided, paired):
            return
        # "Attached" now means a socket that is *still open*
        # (:meth:`active_instance`), not merely one the handler has not cleared
        # yet: a reload closes the old socket and the next instance arrives
        # while that `finally` is still pending, and that path has to work
        # (018 §A).
        if self.active_instance() is not None:
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

    # -- single active instance (018 §A) ---------------------------------

    def active_instance(self) -> ActiveConnector | None:
        """The instance that holds the bridge, or ``None`` when nobody does.

        Liveness is read from the socket, not from bookkeeping: a socket that is
        no longer ``OPEN`` is *not* an active instance even if the handler has
        not yet run its ``finally``. That window is exactly where a reload
        happens — the old socket dies, the new instance arrives — and calling a
        dying socket "connected" would refuse the connection that is supposed to
        replace it.
        """
        if self.connector is None or not _socket_is_open(self.connector):
            return None
        return self.active

    def refuse_if_held(self, connection: Connection, peer: str = "-") -> ActiveConnector | None:
        """The instance that turns this newcomer away, or ``None`` if none does.

        Called on every connector ``hello``, **before the ack goes out**: a
        refused instance is never told it is the connected one and, the part
        that matters, is never installed as the active connector — so it cannot
        become the one a later write is forwarded to.

        Tri-state, in the order the task book states it:

        - no active instance → accept (returns ``None``);
        - an active instance whose socket is gone → accept; it takes over, which
          is the ordinary reload path and must stay smooth;
        - an active instance whose socket is open → **refuse**: records
          ``connector_rejected``, says so on the console, and returns the holder
          so the caller can name it on the wire too.

        A connector presenting a **different token** never reaches this point:
        the pairing check refuses it first, with ``UNAUTHENTICATED``, because
        since 004f an unattached pairing may be re-taken and only an attached one
        is defended. Both are refusals; only this one is about *who else is
        here*, and the two are recorded under their own names on purpose.
        """
        active = self.active_instance()
        if active is None:
            return None
        instance_id = str(getattr(connection, "instance_id", "") or "")
        version = connection.connector_version or ""
        record: dict[str, Any] = {
            "ts": time.time(),
            "peer": peer,
            "instanceId": instance_id,
            "instanceIdSource": str(getattr(connection, "instance_id_source", "") or ""),
            "connectorVersion": version or None,
            "client": client_with_version(connection.client, connection.connector_version),
            "activeInstanceId": active.instance_id,
            "activeConnectorVersion": active.connector_version or None,
            "activePeer": active.peer,
            # The *refused* window's project (021 §2.3). This is the field that
            # makes the refusal readable as a fact about the user's editor: a
            # refused instance is not an error to be explained away, it is
            # another project that is open right now and that the bridge cannot
            # reach.
            "projectName": str(getattr(connection, "project_name", "") or "") or None,
            "projectUuid": str(getattr(connection, "project_uuid", "") or "") or None,
            "reason": "another editor instance is already connected",
        }
        self.audit(action=AUDIT_CONNECTOR_REJECTED, role=ROLE_CONNECTOR, ok=False, **record)
        # Newest first, and bounded: the refused window backs off and retries,
        # so an unbounded list would grow for as long as it stays open.
        self.recent_rejections.insert(0, record)
        del self.recent_rejections[MAX_RECENT_REJECTIONS:]
        self._announce_rejection(RejectionNotice(
            active_instance_id=active.instance_id,
            active_connector_version=active.connector_version,
            instance_id=instance_id,
            connector_version=version,
            peer=peer,
        ))
        return active

    def _announce_rejection(self, notice: RejectionNotice) -> None:
        """Say it out loud. This line is the whole safety mechanism.

        With no callback installed the daemon prints it itself — the requirement
        is that the *console* carries the line (018 §A), and the process that
        happens to own that console is an implementation detail. Nothing here
        may fail the handshake: a refusal that manages to raise would leave a
        socket open that we already decided to close.
        """
        if self.on_rejection is not None:
            try:
                self.on_rejection(notice)
            except Exception:
                pass
            return
        try:
            print("\n".join(notice.console_lines()), flush=True)
        except UnicodeEncodeError:
            # A console that cannot render the Chinese line still has to hear
            # this — see `RejectionNotice.fallback_lines`. Folded in here rather
            # than left to the user's code page.
            try:
                print("\n".join(notice.fallback_lines()), flush=True)
            except Exception:
                pass
        except Exception:
            pass

    # -- dispatch -------------------------------------------------------

    async def handle_request(self, action: str, params: dict[str, Any], role: str) -> Any:
        """Answer one request. Shared by the socket handler and the tests."""
        spec = action_spec(action)
        if spec is None:
            raise BridgeError(ErrorCodes.UNKNOWN_ACTION, f"unknown action {action!r}")
        if spec.owner == "daemon":
            return self._local_action(action)
        params = self._gate_confirmation(spec, params)
        return await self._forward(action, params, role)

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
            active = self.active_instance()
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
                # Which editor instance holds the bridge, and who was turned
                # away — the two facts that answer "why did my write land in the
                # other project?" without anyone reading a log file (018 §A).
                # `status_lines` renders them; the keys are wire data.
                "activeInstance": active.as_status() if active is not None else None,
                "recentRejections": [dict(record) for record in self.recent_rejections],
            }
        # "hello" during the request phase is a protocol violation.
        raise BridgeError(
            ErrorCodes.PROTOCOL_VIOLATION, "hello may only be sent once, as the first frame"
        )

    def has_connector(self) -> bool:
        """Whether a connector socket is open right now.

        The same liveness rule as :meth:`active_instance`, and deliberately the
        one both `ping` and :meth:`_forward` use: a status line that says
        "connected" while the forward path refuses, or the reverse, is worse
        than either answer on its own.
        """
        return self.connector is not None and _socket_is_open(self.connector)

    async def _forward(self, action: str, params: dict[str, Any], role: str) -> Any:
        # `has_connector`, not `self.connector is not None`: a socket that died
        # without the handler having noticed yet is not something to send a
        # write to — it deserves the same NO_CONNECTOR the caller would get a
        # second later, not an INTERNAL from a send on a closed socket.
        if not self.has_connector():
            raise BridgeError(
                ErrorCodes.NO_CONNECTOR,
                f"{action} needs the editor: no connector is connected. "
                "Is EasyEDA running with the boardwise extension enabled?",
            )
        if role != ROLE_CLI:
            raise BridgeError(
                ErrorCodes.BAD_REQUEST, f"role {role!r} may not call editor actions"
            )
        request_id = f"{action}-{secrets.token_hex(4)}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.connector.send(request_frame(action, params, id=request_id))
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

    def resolve_connector_response(self, frame: dict[str, Any]) -> bool:
        """Hand a connector frame to whoever is waiting for it."""
        future = self.pending.get(str(frame.get("id")))
        if future is None or future.done():
            return False
        future.set_result(frame)
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
            if self.connector is websocket:
                # Both together: the socket and the instance it stood for. The
                # next connector to arrive finds no active instance and takes
                # the bridge — the reload path (018 §A).
                self.connector = None
                self.active = None
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(
                        BridgeError(ErrorCodes.CONNECTOR_ERROR, "connector disconnected")
                    )
            self.audit(action="disconnect", role=connection.role or "-", ok=True,
                       peer=peer, actions=connection.seen_actions,
                       **({"instanceId": connection.instance_id}
                          if getattr(connection, "instance_id", "") else {}))

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
        connection.instance_id = getattr(authenticated, "instance_id", "")
        connection.instance_id_source = getattr(authenticated, "instance_id_source", "")
        # Same reason as the instance id above: the handshake parsed these off
        # the `hello` params, and this is the object the rest of the daemon
        # (refusal records, `status`, the audit) reads them from (021 §2.3).
        connection.project_name = getattr(authenticated, "project_name", "")
        connection.project_uuid = getattr(authenticated, "project_uuid", "")

        # Single-active-connector guard + install (018 §A), both *before* the ack
        # is sent: a refused instance must never be told it is the connected one,
        # and must never become the socket a later write is forwarded to. Two
        # windows used to take turns here, minutes apart, and each write landed
        # in whichever project the window that happened to be winning had in
        # focus.
        #
        # The install sits immediately after the check, with no `await` between
        # them, so the slot cannot be handed to two connectors that arrive in the
        # same instant — the check-then-install pair has to be atomic, and the
        # `await` that makes it non-atomic is the ack itself.
        if connection.role == ROLE_CONNECTOR:
            holder = self.refuse_if_held(connection, peer)
            if holder is not None:
                await self._close(websocket, CONNECTOR_ALREADY_ACTIVE,
                                  _refusal_message(holder))
                return
            self._install_connector(websocket, connection, peer)

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
        }))

        try:
            async for raw in websocket:
                await self._on_frame(websocket, connection, raw)
        except websockets.ConnectionClosed:
            pass

    def _install_connector(self, websocket: ServerConnection, connection: Connection, peer: str) -> None:
        """Give this instance the bridge, and put the handover on the record.

        There is no displacement here any more. Until 2026-09-22 this method's
        body closed whatever was there and took over — which is how two editor
        windows ended up taking turns, five minutes apart, with every write
        landing in the project the winning window had focused (018 §A). A socket
        holding the bridge is now refused before we get here, so the only
        previous holder this can replace is one whose socket is already gone.
        """
        previous = self.active
        self.connector = websocket
        self.active = ActiveConnector(
            instance_id=str(getattr(connection, "instance_id", "") or ""),
            client=connection.client,
            connector_version=connection.connector_version,
            peer=peer,
            connected_at=time.time(),
            instance_id_source=str(getattr(connection, "instance_id_source", "") or "hello"),
            project_name=str(getattr(connection, "project_name", "") or ""),
            project_uuid=str(getattr(connection, "project_uuid", "") or ""),
        )
        # Every connection leaves the connector's build behind. "Which version
        # was actually running?" has been unanswerable twice after a sideload
        # that did not take, and this line is the answer. The instance id was
        # added for 018 §A for the same reason: after the fact, "which window
        # was this?" has to be answerable from the log. The project joined them
        # on 2026-09-22 (021 §2.3) — "which window was this?" is only half an
        # answer when three windows are open, and the audit is where the
        # project of a window that has since closed survives.
        self.audit(
            action="hello", role=connection.role, ok=True, peer=peer,
            client=client_with_version(connection.client, connection.connector_version),
            connectorVersion=connection.connector_version or None,
            instanceId=self.active.instance_id,
            instanceIdSource=self.active.instance_id_source,
            tookOverFrom=previous.instance_id if previous is not None else None,
            projectName=self.active.project_name or None,
            projectUuid=self.active.project_uuid or None,
        )

    async def _on_frame(self, websocket: ServerConnection, connection: Connection, raw: Any) -> None:
        started = time.perf_counter()
        try:
            frame = decode_frame(raw)
        except BridgeError as exc:
            await websocket.send(error_frame(None, exc))
            return

        # A connector frame carrying ok= is an answer to something we sent.
        if connection.role == ROLE_CONNECTOR and "ok" in frame:
            self.resolve_connector_response(frame)
            return

        action = str(frame.get("action") or "")
        frame_id = frame.get("id")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        connection.seen_actions.append(action)
        try:
            data = await self.handle_request(action, params, connection.role)
        except BridgeError as exc:
            self.audit(action=action, role=connection.role, ok=False, error=exc.code,
                       ms=round((time.perf_counter() - started) * 1000, 1))
            await websocket.send(error_frame(frame_id, exc))
            return
        except Exception as exc:  # never let a handler kill the socket loop
            self.audit(action=action, role=connection.role, ok=False,
                       error=ErrorCodes.INTERNAL, ms=round((time.perf_counter() - started) * 1000, 1))
            await websocket.send(error_frame(frame_id, BridgeError(
                ErrorCodes.INTERNAL, f"{type(exc).__name__}: {exc}")))
            return
        self.audit(action=action, role=connection.role, ok=True,
                   ms=round((time.perf_counter() - started) * 1000, 1))
        await websocket.send(response_frame(frame_id, data))

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
    connector is *attached* (018 §A). The two are not the same: the socket dies
    the moment the peer goes away, while ``self.connector`` is only cleared when
    the handler reaches its ``finally`` — and the new instance arrives inside
    that window, which is precisely the reload the guard has to let through.

    Unknown state counts as open. A socket object with no ``state`` is either an
    older ``websockets`` or a test double, and inventing "closed" for it would
    turn a missing attribute into a refusal.
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
    can tell two windows apart for as long as they live, an invented one can
    only name a socket.
    """
    claimed = params.get("instanceId")
    if isinstance(claimed, str) and claimed.strip():
        return claimed.strip(), "hello"
    return f"conn-{secrets.token_hex(8)}", "connection"


def _project_identity(params: dict[str, Any]) -> tuple[str, str]:
    """The project the connecting window reported in ``hello`` (021 §2.3).

    Two optional strings, and their absence means absence. There is nothing to
    fall back to: the daemon's own view of "the current project" is the project
    of whichever window holds the bridge, so filling a blank in with it would
    attribute one window's project to another — the exact confusion this field
    exists to remove. Anything that is not a non-empty string is treated as not
    sent, which is also how an old connector (neither field) and a newer one that
    could not read its project arrive here.
    """
    def read(key: str) -> str:
        value = params.get(key)
        return value.strip() if isinstance(value, str) else ""

    return read("projectName"), read("projectUuid")


def _refusal_message(active: ActiveConnector) -> str:
    """The wire message a refused connector is closed with.

    Says what happened, who holds the bridge, and what to do about it. The
    connector logs this and shows it; the person reading it is looking at two
    EasyEDA windows and needs to know which one to close.
    """
    return (
        f"another editor instance already holds the bridge "
        f"({active.describe()}); this connection was refused so that writes "
        f"cannot land in the wrong project — close the extra EasyEDA window, or "
        f"run 'boardwise bridge status' to see which instance is connected"
    )


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
