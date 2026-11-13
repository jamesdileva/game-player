"""Minimal MCP HTTP client: one tool call per invocation (Sprint 8 demo).

Usage:
    python testbed/mcp_call.py screenshot [--save out.jpg]
    python testbed/mcp_call.py key --name enter
    python testbed/mcp_call.py click --x 100 --y 200
    python testbed/mcp_call.py done --claim "battle won"

Connects to the persistent agb serve --transport http server; the session
(recording, caps, state) lives server-side between calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tool")
    p.add_argument("args", nargs="*")
    p.add_argument("--url", default="http://127.0.0.1:8931/mcp")
    p.add_argument("--save", default=None, help="screenshot: save the image here")
    a = p.parse_args()

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(a.url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            args: dict = {}
            if a.tool == "screenshot":
                args = {}
            elif a.tool == "key":
                args = {"name": a.args[0]}
                if len(a.args) > 1:
                    args["hold_ms"] = int(a.args[1])
            elif a.tool == "click":
                args = {"x": int(a.args[0]), "y": int(a.args[1])}
            elif a.tool == "done":
                args = {"claim": " ".join(a.args) or "done"}
            result = await s.call_tool(a.tool, args)
            texts = [c.text for c in result.content if hasattr(c, "text")]
            payload = json.loads(texts[0]) if texts else {}
            if a.tool == "screenshot" and payload.get("image_base64"):
                if a.save:
                    import base64 as b64mod

                    open(a.save, "wb").write(b64mod.b64decode(payload["image_base64"]))
                    payload["image_base64"] = f"<{len(payload['image_base64'])} b64 chars>"
            print(json.dumps(payload, indent=1)[:1200])


if __name__ == "__main__":
    asyncio.run(main())
