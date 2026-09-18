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

__all__ = ["BridgeClient", "connect_client"]


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
            await instance.hello()
        except BaseException:
            await websocket.close()
            raise
        return instance

    async def hello(self) -> dict[str, Any]:
        return await self.call("hello", {
            "token": self._token,
            "role": self._role,
            "protocol": PROTOCOL_VERSION,
            "client": self._client,
        }, id="hello")

    async def call(self, action: str, params: dict[str, Any] | None = None, *, id: str | None = None) -> Any:
        """Send one request and return ``data``; raises :class:`BridgeError`."""
        frame_id = id or new_id()
        await self._websocket.send(request_frame(action, params, id=frame_id))
        frame = await self._recv_response()
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
        await self._websocket.close()


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
