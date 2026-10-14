import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from hidagent.agent import Agent
from hidagent.client import IPhoneClient
from hidagent.debug import Trace


class Model:
    model = "fake-vision"

    async def chat(self, system, text, image=None, **kwargs):
        if "Check task completion" in system:
            return "YES"
        if "You plan tasks" in system:
            return "1. Inspect Settings"
        return "THINK: Settings is visible.\nDO: done Settings is open"


class Phone:
    calibrated = True

    def __init__(self):
        self.device = SimpleNamespace(connected=True)
        self.calls = []

    async def tap(self, x, y):
        self.calls.append((x, y))

    async def reset(self):
        self.calls.append("reset")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("HIDAGENT_DATA", str(tmp_path))
    module = importlib.import_module("hidagent.app")
    phone = Phone()
    screen = SimpleNamespace(live=True, frame=b"jpeg", aspect=0.46)
    agent = Agent(phone, screen, Model(), Model(), Trace(None))
    monkeypatch.setattr(module, "phone", phone)
    monkeypatch.setattr(module, "device", phone.device)
    monkeypatch.setattr(module, "screen", screen)
    monkeypatch.setattr(module, "agent", agent)
    monkeypatch.setattr(module, "control_lock", asyncio.Lock())
    return module


def connect(api):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test")


def test_delegated_task_completes_and_retains_its_result(api):
    async def scenario():
        async with connect(api) as client:
            response = await client.post("/api/tasks", json={"goal": "Open Settings"})
            assert response.status_code == 202
            task = response.json()
            await api.agent.wait_stopped()
            result = (await client.get(task["status_url"])).json()
            assert result["state"] == "succeeded"
            assert result["result"] == "Settings is open"
            assert result["started_at"] <= result["finished_at"]
            assert result["steps"][-1]["action"] == "done"
            second = await client.post("/api/tasks", json={"goal": "Inspect Settings again"})
            await api.agent.wait_stopped()
            assert second.json()["id"] != task["id"]
            assert (await client.get(task["status_url"])).json() == result
            assert (await client.get("/api/tasks/missing")).status_code == 404

    asyncio.run(scenario())


def test_readiness_and_bounds_are_enforced(api):
    async def scenario():
        async with connect(api) as client:
            for goal in ("", " " * 5):
                response = await client.post("/api/tasks", json={"goal": goal})
                assert response.status_code in (409, 422)
            for field, value in (("max_steps", 0), ("max_steps", 121), ("timeout_s", 3601)):
                assert (await client.post("/api/tasks", json={"goal": "Test", field: value})).status_code == 422
            api.phone.calibrated = False
            assert (await client.post("/api/tasks", json={"goal": "Test"})).status_code == 409
            for coords in ({"x": -0.1, "y": 0.5}, {"x": 0.5, "y": 2}):
                assert (await client.post("/api/tap", json=coords)).status_code == 422
            assert (await client.post("/api/type", json={"text": "hello\nclick"})).status_code == 422
            assert api.phone.calls == []

    asyncio.run(scenario())


def test_manual_gesture_excludes_other_controls_and_task_start(api):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_tap(x, y):
            entered.set()
            await release.wait()

        api.phone.tap = slow_tap
        async with connect(api) as client:
            first = asyncio.create_task(client.post("/api/tap", json={"x": 0.5, "y": 0.5}))
            await entered.wait()
            assert (await client.post("/api/tap", json={"x": 0.1, "y": 0.1})).status_code == 409
            assert (await client.post("/api/tasks", json={"goal": "Test"})).status_code == 409
            release.set()
            assert (await first).status_code == 200

    asyncio.run(scenario())


def test_busy_agent_excludes_controls_and_can_be_cancelled(api):
    async def scenario():
        entered = asyncio.Event()

        async def blocked():
            entered.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                api.agent._record(action="stopped")
                raise

        api.agent._run = blocked
        async with connect(api) as client:
            task = (await client.post("/api/tasks", json={"goal": "Wait"})).json()
            await entered.wait()
            assert (await client.post("/api/tap", json={"x": 0.2, "y": 0.3})).status_code == 409
            assert (await client.post("/api/tasks", json={"goal": "Other"})).status_code == 409
            stopped = await client.post(f"/api/tasks/{task['id']}/stop")
            assert stopped.json()["state"] == "cancelled"
            assert api.phone.calls == ["reset"]
            assert (await client.post("/api/tasks/wrong/stop")).status_code == 409

    asyncio.run(scenario())


def test_task_deadline_is_a_failure_and_screenshots_are_bounded(api):
    async def scenario():
        async def slow():
            await asyncio.sleep(60)
        api.agent._run = slow
        api.agent.start("Wait", timeout_s=1)
        await api.agent.wait_stopped()
        assert api.agent.run_info()["state"] == "failed"
        assert api.agent.run_info()["error"] == "task deadline exceeded"
        for _ in range(80):
            api.agent._record(b"jpeg", action="wait")
        assert len(api.agent.shots) == 32

    asyncio.run(scenario())


def test_completion_is_not_accepted_without_visual_verification(api):
    class Uncertain(Model):
        async def chat(self, system, text, image=None, **kwargs):
            return "NO: The goal is not visible" if "Check task completion" in system else await super().chat(
                system, text, image, **kwargs)

    async def scenario():
        api.agent.planner = Uncertain()
        api.agent.start("Open Settings")
        await api.agent.wait_stopped()
        assert api.agent.run_info()["state"] == "failed"
        assert api.agent.run_info()["error"] == "completion could not be verified"
        assert not any(s["action"] == "done" for s in api.agent.steps)

    asyncio.run(scenario())


def test_http_client_and_cli_forward_exact_commands(monkeypatch, capsys):
    from hidagent import cli
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(cli, "IPhoneClient", lambda url: IPhoneClient(url, transport=httpx.MockTransport(handle)))
    assert cli.main(["--url", "http://test", "tap", "0.25", "0.75"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert seen == [("POST", "/api/tap", {"x": 0.25, "y": 0.75})]
    assert cli.main(["--url", "http://test", "task-status", "../status"]) == 2
    assert len(seen) == 1


def test_client_wait_returns_terminal_result_and_does_not_cancel_on_timeout():
    run_id = "a" * 32
    states = iter(["running", "succeeded"])
    with IPhoneClient("http://test", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"id": run_id, "state": next(states)}))) as client:
        assert client.wait(run_id, poll_s=0)["state"] == "succeeded"
    with IPhoneClient("http://test", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"id": run_id, "state": "running"}))) as client:
        with pytest.raises(TimeoutError, match="continues remotely"):
            client.wait(run_id, timeout_s=0)


def test_screen_loss_during_model_call_prevents_any_action(api):
    from hidagent.agent import BlindError

    class LosingScreen(Model):
        async def chat(self, *args, **kwargs):
            api.screen.live = False
            return "DO: tap 500 500"

    api.agent.actor = LosingScreen()
    with pytest.raises(BlindError, match="while waiting"):
        asyncio.run(api.agent._next_actions())
    assert api.phone.calls == []


def test_structured_actor_retries_invalid_coordinates_with_feedback(api):
    prompts = []

    class Structured(Model):
        async def chat(self, system, text, image=None, **kwargs):
            prompts.append(text)
            assert kwargs["tools"]
            return json.dumps({"action": "tap", "x": 1200 if len(prompts) == 1 else 500, "y": 300})

    api.agent.actor_mode = "tools"
    api.agent.actor = Structured()
    actions = asyncio.run(api.agent._next_actions())
    assert actions[0]["x"] == 500
    assert "invalid" in prompts[1]
    assert api.phone.calls == []


def test_immediate_cancel_has_a_terminal_timestamp(api):
    async def scenario():
        task_id = api.agent.start("Open Settings")
        api.agent.stop()
        await api.agent.wait_stopped()
        result = api.agent.run_info(task_id)
        assert result["state"] == "cancelled"
        assert result["finished_at"] is not None

    asyncio.run(scenario())
