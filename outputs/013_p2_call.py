"""One-off probe helper for 013 batch 2 (real host).

Same path as `boardwise bridge call`, but prints the full JSON payload
including an error's `detail` — which `bridge call` discards. Read-only
against the editor: it only sends the action the caller names.

usage: python outputs/013_p2_call.py <action> ['<params json>'] [--yes]
"""

import asyncio
import json
import sys

sys.path.insert(0, "src")

from boardwise.bridge import client as bridge_client  # noqa: E402
from boardwise.bridge import daemon as bridge_daemon  # noqa: E402


async def main() -> int:
    action = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else {}
    if "--yes" in sys.argv:
        params["confirm"] = True
    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli"
    )
    try:
        data = await client.call(action, params)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
        print(json.dumps(
            {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
            ensure_ascii=False, indent=2))
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
