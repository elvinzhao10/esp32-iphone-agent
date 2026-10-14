"""Small, expiring ownership leases and an inspectable activity feed.

This coordinates trusted tailnet clients; client ids are not authentication.
"""

import time
from collections import deque


class ControlState:
    def __init__(self):
        self.lease = None
        self.events = deque(maxlen=100)
        self.revoked = {}

    def record(self, kind: str, owner: str, detail: str):
        self.events.append({"t": time.time(), "kind": kind, "owner": owner, "detail": detail})

    def expire(self):
        now = time.time()
        self.revoked = {key: until for key, until in self.revoked.items() if until > now}
        if self.lease and self.lease["expires_at"] <= now:
            self.record("released", self.lease["owner"], "Control lease expired")
            self.lease = None

    def check(self, client_id: str):
        self.expire()
        if client_id in self.revoked:
            raise RuntimeError("control was taken over; request an explicit new control session")
        if self.lease and self.lease["client_id"] != client_id:
            raise RuntimeError(f"phone is controlled by {self.lease['owner']}; release it or use dashboard takeover")

    def claim(self, client_id: str, owner: str, source: str, ttl: int = 120, explicit: bool = False):
        self.expire()
        if explicit:
            self.revoked.pop(client_id, None)
        self.check(client_id)
        if not self.lease:
            self.record("claimed", owner, f"{source.title()} control session started")
        self.lease = {"client_id": client_id, "owner": owner, "source": source,
                      "expires_at": time.time() + ttl}
        return dict(self.lease)

    def release(self, client_id: str | None = None, revoke: bool = False):
        self.expire()
        if self.lease:
            if client_id is not None and self.lease["client_id"] != client_id:
                raise RuntimeError("only the current owner can release this session")
            if revoke:
                self.revoked[self.lease["client_id"]] = time.time() + 600
            self.record("released", self.lease["owner"], "Control released" if not revoke else "Control taken over")
            self.lease = None

    def status(self, run: dict, running: bool):
        self.expire()
        if running:
            return {"mode": "external" if run.get("source") == "external" else "local",
                    "activity": "delegated" if run.get("source") == "external" else "executing",
                    "engine": run.get("engine", "vision"),
                    "owner": run.get("owner", "Local agent"), "task_id": run["id"],
                    "client_id": self.lease["client_id"] if self.lease else None, "expires_at": None}
        if self.lease:
            return {"mode": "external" if self.lease["source"] == "external" else "manual",
                    **self.lease, "task_id": None, "activity": "direct"}
        return {"mode": "manual", "owner": "Available", "client_id": None, "task_id": None, "expires_at": None}
