"""Bridge: the daemon that connects boardwise to a live EasyEDA canvas.

Stage-1 review runs entirely on files; this package is the optional live
channel (P1). Imported lazily by the CLI so a missing ``websockets`` install
never breaks offline review.
"""

from .protocol import (
    ACTIONS,
    PROTOCOL_VERSION,
    BridgeError,
    ErrorCodes,
    decode_frame,
    error_frame,
    request_frame,
    response_frame,
)

__all__ = [
    "ACTIONS",
    "PROTOCOL_VERSION",
    "BridgeError",
    "ErrorCodes",
    "decode_frame",
    "error_frame",
    "request_frame",
    "response_frame",
]
