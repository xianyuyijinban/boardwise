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
class BridgeDaemon:
    """Routes frames between CLI callers and the editor connector."""

    token: str
    home: Path = field(default_factory=lambda: BOARDWISE_HOME)
    #: The connected editor extension, if any. Only one is tracked: a second
    #: connector takes over (the editor may have been restarted).
    connector: ServerConnection | None = None
    #: id -> Future resolved by the connector's response.
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
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

        return Connection(
            role=role,
            client=client,
            protocol=reported or PROTOCOL_VERSION,
            connector_version=version,
            authenticated=True,
        )

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
        if self.connector is not None:
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
            return {
                "pong": True,
                "connector": self.connector is not None,
                # Fingerprint only — `bridge status` prints this, and the log
                # panel and terminal are both places a secret must never reach.
                "pairedFingerprint": connector_fingerprint(
                    load_connector_token(self.home)
                ),
            }
        # "hello" during the request phase is a protocol violation.
        raise BridgeError(
            ErrorCodes.PROTOCOL_VIOLATION, "hello may only be sent once, as the first frame"
        )

    async def _forward(self, action: str, params: dict[str, Any], role: str) -> Any:
        if self.connector is None:
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
                self.connector = None
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(
                        BridgeError(ErrorCodes.CONNECTOR_ERROR, "connector disconnected")
                    )
            self.audit(action="disconnect", role=connection.role or "-", ok=True,
                       peer=peer, actions=connection.seen_actions)

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
        }))

        if connection.role == ROLE_CONNECTOR:
            previous = self.connector
            self.connector = websocket
            if previous is not None and previous is not websocket:
                await self._close(previous, ErrorCodes.PROTOCOL_VIOLATION, "replaced by a new connector")
            # Every connection leaves the connector's build behind. "Which
            # version was actually running?" has been unanswerable twice after
            # a sideload that did not take, and this line is the answer.
            self.audit(
                action="hello", role=connection.role, ok=True,
                client=client_with_version(connection.client, connection.connector_version),
                connectorVersion=connection.connector_version or None,
            )

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
