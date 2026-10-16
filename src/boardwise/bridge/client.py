"""Small async client used by the CLI (and by the tests' fake connector).

Kept separate from :mod:`boardwise.bridge.daemon` so the daemon never has to
import client code, and so a second transport (pipes, unix socket) could be
added without touching either side.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets
from websockets.asyncio.client import connect

from .protocol import (
    PROTOCOL_VERSION,
    BridgeError,
    ErrorCodes,
    decode_frame,
    frame_kind,
    new_id,
    request_frame,
)

__all__ = ["BridgeClient", "connect_client", "daemon_version_warning"]

#: How a daemon that predates the field is named in the warning below. Not a
#: version: the point of the wording is that nobody read one.
UNKNOWN_DAEMON_VERSION = "未知（不上报版本）"

#: The daemon versions this process has already complained about (187c). The
#: finding is about *this machine's daemon*, not about one connection, so a
#: command that opens a second socket (or retries) must not print it again —
#: and keying on the version rather than on a boolean keeps the three states
#: separable for a caller that talks to two daemons.
_drift_reported: set[str] = set()


def daemon_version_warning(daemon_version: Any) -> str | None:
    """The warning for a daemon that is not this CLI's build, or ``None`` (187c).

    The daemon is a **long-running process holding the action catalogue as a
    load-time constant** (``bridge.protocol.ACTIONS``), so a CLI upgraded under a
    running daemon talks to the old table: a new action answers
    ``UNKNOWN_ACTION``, an old one keeps a meaning that has since been fixed, and
    nothing on the wire says why. `boardwise doctor` has diagnosed this since
    069c, but only when someone runs it — this is the same fact noticed on the
    handshake **every** bridge command already performs.

    A daemon that reports **no** version is the same finding: the field is what
    this build added, so a daemon without it is older by construction. It is
    named as unknown rather than as ``≠ <version>``, because printing a
    comparison against a version nobody read would be inventing one.

    The fix is never taken here. Restarting a daemon cuts every online
    connector's socket, which is a real-machine action (and in EasyEDA it is the
    window, not the daemon, that decides when to come back) — so this warns and
    leaves the decision where it belongs.
    """
    from .. import __version__ as cli_version

    reported = str(daemon_version or "").strip()
    if reported == cli_version:
        return None
    running = reported or UNKNOWN_DAEMON_VERSION
    return (
        f"boardwise bridge: daemon 运行 {running} ≠ CLI {cli_version}"
        "（动作表是加载期常量，新动作/修复在旧 daemon 里不存在）；"
        "用 `boardwise bridge start` 重启 daemon"
    )


class BridgeClient:
    """One authenticated connection to the daemon."""

    def __init__(self, websocket: Any, token: str, role: str, client: str = "") -> None:
        self._websocket = websocket
        self._token = token
        self._role = role
        self._client = client

    @classmethod
    async def open(cls, uri: str, token: str, role: str, client: str = "") -> "BridgeClient":
        # `proxy=None` disables it explicitly. On websockets 17 the default is
        # `proxy=True`, i.e. "use whatever HTTPS_PROXY / HTTP_PROXY / ALL_PROXY
        # says" — and the daemon is on **loopback**, where a proxy can only be
        # wrong. Measured 2026-09-16: with the sandbox's proxy env set, a
        # `ws://127.0.0.1:61190/eda` connect went to the proxy and came back
        # `InvalidProxyStatus: proxy rejected connection: HTTP 502`, which reads
        # as "the daemon is down" while the daemon is fine.
        websocket = await connect(uri, max_size=None, open_timeout=10, proxy=None)
        instance = cls(websocket, token, role, client)
        try:
            greeting = await instance.hello()
        except BaseException:
            await websocket.close()
            raise
        # 187c: the handshake every command already makes is where a daemon
        # built from another revision becomes visible. See
        # :func:`daemon_version_warning` for why this warns instead of acting.
        instance.report_version_drift(greeting)
        return instance

    @staticmethod
    def report_version_drift(greeting: Any) -> None:
        """Print the version-mismatch warning to stderr, once per process.

        Once per *state*, not per call: a caller that opens two connections to
        the same drifted daemon has one finding, and repeating the paragraph
        would bury the command's own answer. stderr, because it is a
        diagnostic about this machine and the command's answer is on stdout.
        """
        import sys

        reported = str((greeting or {}).get("version") or "").strip() if isinstance(
            greeting, dict
        ) else ""
        if reported in _drift_reported:
            return
        warning = daemon_version_warning(reported)
        if warning is None:
            return
        _drift_reported.add(reported)
        print(warning, file=sys.stderr, flush=True)

    async def hello(self) -> dict[str, Any]:
        return await self.call("hello", {
            "token": self._token,
            "role": self._role,
            "protocol": PROTOCOL_VERSION,
            "client": self._client,
        }, id="hello")

    async def call(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        target_project: str | None = None,
        target_instance: str | None = None,
    ) -> Any:
        """Send one request and return ``data``; raises :class:`BridgeError`.

        A transport death is normalised into ``BridgeError(DISCONNECTED)`` right
        here, because this is the only layer that knows about ``websockets``. It
        matters beyond tidiness: a write whose connection died mid-flight may
        still have reached the editor, so a caller must be able to tell "the
        daemon went away" apart from "the action failed" — the draw flow reads
        exactly that code to decide whether the page's state is unknown rather
        than assuming nothing happened (M0-P0d follow-up, 2026-09-18).

        ``target_project`` (023) is the window hint the daemon routes by: the
        project name or uuid whose editor window should answer. ``None`` (the
        default, and what every caller that does not pass it sends) omits the
        field entirely, so a request without a hint is the pre-023 frame — which
        is also what keeps a one-window daemon working with no ceremony at all.

        ``target_instance`` is the same hint by instance id, and it is the one
        that still works when a window has no project to be named by: the editor
        tells the daemon its instance id at the handshake, long before any action
        proves it can read a project. Passing both sends both; the daemon prefers
        the instance.
        """
        frame_id = id or new_id()
        try:
            await self._websocket.send(
                request_frame(
                    action,
                    params,
                    id=frame_id,
                    target_project=target_project or "",
                    target_instance=target_instance or "",
                )
            )
            frame = await self._recv_response()
        except (websockets.ConnectionClosed, OSError) as exc:
            raise BridgeError(
                ErrorCodes.DISCONNECTED,
                f"the daemon connection closed while {action!r} was in flight "
                f"({type(exc).__name__}); the action's outcome is unknown",
                {"action": action, "frameId": frame_id, "cause": type(exc).__name__},
            ) from exc
        if frame.get("ok"):
            return frame.get("data")
        error = frame.get("error") or {}
        raise BridgeError(
            str(error.get("code") or ErrorCodes.INTERNAL),
            str(error.get("message") or "request failed"),
            error.get("detail"),
        )

    async def _recv_response(self) -> dict[str, Any]:
        """Read until a frame that is not an event, then return it.

        The daemon sends a banner event the moment the socket opens
        (:func:`boardwise.bridge.protocol.banner_frame`), so a single ``recv``
        can legitimately hand back an event instead of the answer. Events are
        dropped rather than surfaced: this client is synchronous
        request/response, and a stray event is not an error.
        """
        while True:
            frame = decode_frame(await self._websocket.recv())
            if frame_kind(frame) != "event":
                return frame

    async def close(self) -> None:
        """Close the socket; a socket that is already gone is not an error.

        `close()` runs from a `finally` in the CLI, including on the path where
        the daemon died mid-run — so raising here would replace a failed-but-
        reported draw with a traceback, losing the report that says *which*
        writes are unaccounted for.
        """
        try:
            await self._websocket.close()
        except (websockets.ConnectionClosed, OSError):
            pass


async def connect_client(uri: str, token: str, role: str, client: str = "") -> BridgeClient:
    return await BridgeClient.open(uri, token, role, client)


def uri_for(host: str = "127.0.0.1", port: int = 61190) -> str:
    """The URL the CLI dials.

    Carries the ``/eda`` path because that is what the known-working
    ``easyeda-agent`` connector uses, and our daemon ignores paths entirely
    (measured — see ``docs/bridge.md`` §12). One spelling for both sides means
    there is no second form to discover when something does not connect.
    """
    return f"ws://{host}:{port}/eda"
