"""Web API + control page. Run with `python -m hidagent`."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .debug import Trace
from .device import Device, DeviceError
from .llm import LLM
from .phone import Phone
from .screen import Screen

DATA_DIR = Path(os.environ.get("HIDAGENT_DATA", Path.home() / ".hidagent"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG = os.environ.get("HIDAGENT_DEBUG") == "1"

device = Device()
screen = Screen(os.environ.get("AIRPLAY_NAME", "iPhone Agent"))
phone = Phone(device, DATA_DIR / "calibration.json", screen)
agent = Agent(phone, screen, LLM.from_env("ACTOR"), LLM.from_env("PLANNER"),
              Trace(DATA_DIR / "traces" if DEBUG else None))


@asynccontextmanager
async def lifespan(_):
    server = await device.serve("0.0.0.0", int(os.environ.get("DEVICE_PORT", 7300)))
    screen.start()
    awake = asyncio.create_task(device.keep_awake(screen=screen))
    try:
        yield
    finally:
        agent.stop()
        await agent.wait_stopped()
        awake.cancel()
        try:
            await awake
        except asyncio.CancelledError:
            pass
        screen.stop()
        server.close()
        await server.wait_closed()
        await agent.actor._http.aclose()
        await agent.planner._http.aclose()


control_lock = asyncio.Lock()


@asynccontextmanager
async def control():
    if agent.running:
        raise HTTPException(409, "agent owns the phone; stop its task before manual control")
    if control_lock.locked():
        raise HTTPException(409, "phone is busy")
    async with control_lock:
        yield


app = FastAPI(lifespan=lifespan)
class Static(StaticFiles):
    """Static files that browsers re-check on every load, so a new version shows up on refresh."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", Static(directory=Path(__file__).parent / "static"), name="static")


Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Point(BaseModel):
    x: Coordinate
    y: Coordinate


class Swipe(BaseModel):
    x1: Coordinate
    y1: Coordinate
    x2: Coordinate
    y2: Coordinate


class Scroll(Point):
    lines: int = Field(ge=-100, le=100)


class Text(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def act(coro):
    try:
        async with control():
            await coro
    except (DeviceError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e
    finally:
        coro.close()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
def status():
    return {"device": device.connected, "screen": screen.live, "calibrated": phone.calibrated,
            "debug": DEBUG, "trace": str(agent.trace.dir or ""), "aspect": round(screen.aspect, 4),
            "models": {"planner": agent.planner.model, "actor": agent.actor.model},
            "agent": {"running": agent.running, "task": agent.task, "steps": agent.steps,
                      "id": agent.run_id, "state": agent.run_info()["state"]}}


@app.get("/api/frame.jpg")
def frame():
    if not screen.live:
        raise HTTPException(404, "no live screen: start screen mirroring on the phone")
    return Response(screen.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/steps/{index}.jpg")
def step_shot(index: int):
    if index not in agent.shots:
        raise HTTPException(404)
    return Response(agent.shots[index], media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/tap")
async def tap(p: Point):
    return await act(phone.tap(p.x, p.y))


@app.post("/api/swipe")
async def swipe(s: Swipe):
    return await act(phone.swipe(s.x1, s.y1, s.x2, s.y2))


@app.post("/api/scroll")
async def scroll(s: Scroll):
    return await act(phone.scroll(s.x, s.y, s.lines))


@app.post("/api/type")
async def type_text(t: Text):
    if not t.text.isascii() or any(ord(c) < 32 for c in t.text):
        raise HTTPException(422, "text must be printable ASCII on one line")
    return await act(phone.type(t.text))


@app.post("/api/key")
async def key(t: Text):
    if not t.text.isascii() or any(ord(c) < 32 for c in t.text):
        raise HTTPException(422, "key combo must be printable ASCII on one line")
    return await act(phone.key(t.text))


@app.post("/api/home")
async def home():
    return await act(phone.go_home())


@app.post("/api/back")
async def back():
    return await act(phone.go_back())


@app.post("/api/raw")
async def raw(t: Text):
    """Debug only: send one protocol line to the board as-is."""
    if not DEBUG:
        raise HTTPException(404)
    return await act(device.send(t.text))


@app.post("/api/calibrate/start")
async def calibrate_start():
    """Calibrate the pointer. {"auto": true}: done by itself; otherwise the user clicks the pointer next."""
    try:
        async with control():
            return {"ok": True, "auto": await phone.start_calibration(), "span": phone.span}
    except (DeviceError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/calibrate/finish")
async def calibrate_finish(p: Point):
    if not p.x or not p.y:
        raise HTTPException(422, "pointer coordinates must be greater than zero")
    async with control():
        phone.finish_calibration(p.x, p.y)
        return {"ok": True, "span": phone.span}


@app.post("/api/agent")
async def agent_start(t: Text):
    try:
        async with control():
            run_id = agent.start(t.text)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "id": run_id}


@app.post("/api/agent/stop")
async def agent_stop():
    """Emergency stop: cancel the agent and release the mouse button."""
    async with control_lock:
        agent.stop()
        await agent.wait_stopped()
        if device.connected:
            try:
                await phone.reset()
            except (DeviceError, RuntimeError) as e:
                raise HTTPException(409, str(e)) from e
        return {"ok": True}


@app.post("/api/agent/clear")
async def agent_clear():
    """Forget the last run (steps, screenshots, plan) so the page starts clean."""
    try:
        agent.clear()
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


class TaskRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=40, ge=1, le=120)
    timeout_s: float = Field(default=600, ge=1, le=3600, allow_inf_nan=False)


@app.post("/api/tasks", status_code=202)
async def task_start(request: TaskRequest):
    """Delegate a bounded task; poll its returned URL for progress and a terminal result."""
    try:
        async with control():
            run_id = agent.start(request.goal, request.max_steps, request.timeout_s)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"id": run_id, "state": "running", "status_url": f"/api/tasks/{run_id}"}


@app.get("/api/tasks/{run_id}")
async def task_status(run_id: str):
    try:
        return agent.run_info(run_id)
    except KeyError as e:
        raise HTTPException(404, "unknown or expired task") from e


@app.post("/api/tasks/{run_id}/stop")
async def task_stop(run_id: str):
    if run_id != agent.run_id:
        raise HTTPException(409, "task is not the current task")
    await agent_stop()
    return agent.run_info(run_id)
