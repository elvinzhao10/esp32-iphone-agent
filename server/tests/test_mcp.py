"""Real MCP initialize/list/call over stdio, with a disposable HTTP backend."""

import asyncio
import base64
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

pytest.importorskip("mcp")


def test_stdio_bridge_delivers_images_and_task_results():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    image = io.BytesIO()
    Image.new("RGB", (16, 32), "white").save(image, format="JPEG")
    task_id = "a" * 32
    seen = []

    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def do_GET(self):
            if self.path == "/api/observation":
                data = json.dumps({"control": {"mode": "manual"}, "frame": {
                    "data": base64.b64encode(image.getvalue()).decode(), "width": 16, "height": 32,
                }}).encode()
                mime = "application/json"
            elif self.path == "/api/frame.jpg":
                data, mime = image.getvalue(), "image/jpeg"
            elif self.path == f"/api/tasks/{task_id}":
                data = json.dumps({"id": task_id, "state": "succeeded", "result": "Done"}).encode()
                mime = "application/json"
            else:
                data, mime = b'{"device": true, "screen": true, "calibrated": true}', "application/json"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"id": task_id, "state": "running"}
            if self.path == "/api/control/action":
                response = {"ok": True, "frame": {"data": base64.b64encode(image.getvalue()).decode()}}
            self.wfile.write(json.dumps(response).encode())

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "hidagent.cli", "--url", f"http://127.0.0.1:{backend.server_port}", "mcp",
        ])
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {"iphone_tap", "iphone_screenshot", "delegate_task", "task_status", "stop_task",
                    "device_capabilities", "list_workflows", "run_workflow", "route_workflow"} <= tools
            status = await session.call_tool("iphone_status", {})
            assert not status.isError
            shot = await session.call_tool("iphone_screenshot", {})
            assert not shot.isError
            assert shot.content[0].type == "image"
            assert shot.content[0].mimeType == "image/jpeg"
            observed = await session.call_tool("iphone_observe", {})
            assert not observed.isError
            assert any(part.type == "image" for part in observed.content)
            tapped = await session.call_tool("iphone_tap", {"x": .5, "y": .4})
            assert not tapped.isError
            assert any(part.type == "image" for part in tapped.content)
            delegated = await session.call_tool("delegate_task", {"goal": "Open Settings"})
            assert not delegated.isError
            assert task_id in delegated.content[0].text
            workflow = await session.call_tool("run_workflow", {"name": "known-recipe", "timeout_s": 30})
            assert not workflow.isError
            assert task_id in workflow.content[0].text
            result = await session.call_tool("task_status", {"task_id": task_id})
            assert "succeeded" in result.content[0].text
            invalid = await session.call_tool("task_status", {"task_id": "../status"})
            assert invalid.isError

    try:
        asyncio.run(scenario())
        assert seen == [
            ("/api/control/action", {"action": "tap", "arguments": {"x": .5, "y": .4, "precise": True}}),
            ("/api/tasks", {"goal": "Open Settings", "max_steps": 40, "timeout_s": 600}),
            ("/api/workflows/run", {"name": "known-recipe", "recipe": None, "timeout_s": 30}),
        ]
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
