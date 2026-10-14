"""Small HTTP client shared by the CLI and the controller-side MCP bridge."""

import os
import re
import socket
import time

import httpx


class IPhoneClient:
    def __init__(self, url: str | None = None, *, transport=None,
                 client_id: str | None = None, name: str | None = None):
        url = url or os.environ.get("IPHONE_AGENT_URL", "http://127.0.0.1:8890")
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host or parsed.query or parsed.fragment:
            raise ValueError("IPHONE_AGENT_URL must be an HTTP(S) server URL")
        client_id = client_id or os.environ.get("IPHONE_AGENT_CLIENT_ID", f"cli:{socket.gethostname()}")
        name = name or os.environ.get("IPHONE_AGENT_NAME", "CLI controller")
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=60, transport=transport, trust_env=False,
                                 headers={"X-iPhone-Client": client_id, "X-iPhone-Name": name})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def request(self, method: str, path: str, body: dict | None = None):
        response = self.http.request(method, path, json=body)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"iPhone API {response.status_code}: {detail}")
        return response

    def status(self) -> dict:
        return self.request("GET", "/api/status").json()

    def capabilities(self) -> dict:
        return self.request("GET", "/api/capabilities").json()

    def workflows(self) -> list:
        return self.request("GET", "/api/workflows").json()

    def workflow(self, name=None, recipe=None, timeout_s=60) -> dict:
        return self.request("POST", "/api/workflows/run", {
            "name": name, "recipe": recipe, "timeout_s": timeout_s,
        }).json()

    def route(self, goal: str, context: str) -> dict:
        return self.request("POST", "/api/workflows/route", {"goal": goal, "context": context}).json()

    def dispatch(self, goal: str, context: str) -> dict:
        return self.request("POST", "/api/workflows/dispatch", {"goal": goal, "context": context}).json()

    def screenshot(self) -> bytes:
        return self.request("GET", "/api/frame.jpg").content

    def observe(self) -> dict:
        return self.request("GET", "/api/observation").json()

    def perform(self, action: str, **arguments) -> dict:
        return self.request("POST", "/api/control/action", {"action": action, "arguments": arguments}).json()

    def claim(self, ttl_s: int = 120) -> dict:
        return self.request("POST", "/api/control/claim", {"ttl_s": ttl_s}).json()

    def release(self) -> dict:
        return self.request("POST", "/api/control/release").json()

    def tasks(self) -> list[dict]:
        return self.request("GET", "/api/tasks").json()

    def action(self, name: str, **arguments) -> dict:
        if name not in ("tap", "swipe", "scroll", "type", "key", "home", "back",
                        "multi_tap", "long_press", "edit_text", "shortcut"):
            raise ValueError("unknown control action")
        return self.request("POST", f"/api/{name}", arguments or None).json()

    def calibrate(self, x: float | None = None, y: float | None = None) -> dict:
        if x is None and y is None:
            return self.request("POST", "/api/calibrate/start").json()
        if x is None or y is None:
            raise ValueError("provide both pointer coordinates")
        return self.request("POST", "/api/calibrate/finish", {"x": x, "y": y}).json()

    def delegate(self, goal: str, max_steps: int = 40, timeout_s: float = 600) -> dict:
        return self.request("POST", "/api/tasks", {
            "goal": goal, "max_steps": max_steps, "timeout_s": timeout_s,
        }).json()

    @staticmethod
    def _task_path(run_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("task id must be the 32-character id returned by delegate")
        return f"/api/tasks/{run_id}"

    def task_status(self, run_id: str) -> dict:
        return self.request("GET", self._task_path(run_id)).json()

    def stop(self, run_id: str | None = None) -> dict:
        path = self._task_path(run_id) + "/stop" if run_id else "/api/agent/stop"
        return self.request("POST", path).json()

    def wait(self, run_id: str, timeout_s: float = 600, poll_s: float = 1) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            result = self.task_status(run_id)
            if result["state"] != "running":
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"wait expired; task {run_id} continues remotely; poll task-status or stop it")
            time.sleep(min(poll_s, remaining))
