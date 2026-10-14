"""Web API + control page. Run with `python -m hidagent`."""

import asyncio
import base64
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from .agent import Agent
from .control import ControlState
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
        if device._writer is not None:
            device._writer.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 5)
        except asyncio.TimeoutError:
            pass  # the process is exiting; do not hang on an abandoned controller socket
        await agent.actor._http.aclose()
        await agent.planner._http.aclose()


control_lock = asyncio.Lock()
ownership = ControlState()


def identity(request: Request):
    source = "dashboard" if request.headers.get("x-iphone-source") == "dashboard" else "external"
    client_id = request.headers.get("x-iphone-client") or f"api:{request.client.host if request.client else 'unknown'}"
    owner = request.headers.get("x-iphone-name") or ("Dashboard" if source == "dashboard" else "API client")
    return client_id[:120], owner[:80], source


@asynccontextmanager
async def control(request: Request, claim: bool = True):
    if agent.running:
        raise HTTPException(409, "agent owns the phone; stop its task before manual control")
    if control_lock.locked():
        raise HTTPException(409, "phone is busy")
    async with control_lock:
        client_id, owner, source = identity(request)
        try:
            ownership.check(client_id)
            if claim:
                ownership.claim(client_id, owner, source)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
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


class Tap(Point):
    precise: bool = True


class Swipe(BaseModel):
    x1: Coordinate
    y1: Coordinate
    x2: Coordinate
    y2: Coordinate


class Scroll(Point):
    lines: int = Field(ge=-100, le=100)


class Text(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def observation():
    if not screen.live or not screen.frame:
        raise HTTPException(404, "no live screen: start screen mirroring on the phone")
    with Image.open(io.BytesIO(screen.frame)) as image:
        width, height = image.size
    return {"mime_type": "image/jpeg", "data": base64.b64encode(screen.frame).decode(),
            "width": width, "height": height, "updated_at": getattr(screen, "updated", None)}


async def act(coro, request: Request, capture: bool = False):
    try:
        async with control(request):
            await coro
            _, owner, _ = identity(request)
            detail = getattr(request.state, "action", request.url.path.rsplit("/", 1)[-1].title())
            ownership.record("action", owner, detail)
            if capture:
                await screen.settled(quiet=0.2, least=0.2, most=1.5)
                return {"ok": True, "control": ownership.status(agent.run_info(), agent.running),
                        "frame": observation() if screen.live else None}
    except (DeviceError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e
    finally:
        coro.close()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
async def status():
    run = agent.run_info()
    return {"device": device.connected, "screen": screen.live, "calibrated": phone.calibrated,
            "debug": DEBUG, "trace": str(agent.trace.dir or ""), "aspect": round(screen.aspect, 4),
            "models": {"planner": agent.planner.model, "actor": agent.actor.model},
            "agent": {"running": agent.running, "task": agent.task, "steps": agent.steps,
                      "id": agent.run_id, "engine": agent.engine, "state": run["state"], "source": agent.source,
                      "owner": agent.owner, "max_steps": agent.max_steps, "rounds": agent.rounds,
                      "started_at": agent.started_at, "finished_at": agent.finished_at,
                      "result": run["result"], "error": run["error"],
                      "available_shots": list(agent.shots)},
            "control": ownership.status(run, agent.running),
            "activity": list(ownership.events)[-30:],
            "configuration": {"model_ready": bool(agent.actor.model and agent.planner.model
                                                     and getattr(agent.actor, "ready", True)
                                                     and getattr(agent.planner, "ready", True)),
                              "actor_mode": agent.actor_mode, "verify_completion": agent.verify_completion,
                              "actor_key_set": bool(getattr(agent.actor, "authenticated", False)),
                              "planner_key_set": bool(getattr(agent.planner, "authenticated", False))}}


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
async def tap(p: Tap, request: Request):
    return await act(phone.tap(p.x, p.y, aim=p.precise), request)


@app.post("/api/swipe")
async def swipe(s: Swipe, request: Request):
    return await act(phone.swipe(s.x1, s.y1, s.x2, s.y2), request)


@app.post("/api/scroll")
async def scroll(s: Scroll, request: Request):
    return await act(phone.scroll(s.x, s.y, s.lines), request)


@app.post("/api/type")
async def type_text(t: Text, request: Request):
    if not t.text.isascii() or any(ord(c) < 32 for c in t.text):
        raise HTTPException(422, "text must be printable ASCII on one line")
    return await act(phone.type(t.text), request)


@app.post("/api/key")
async def key(t: Text, request: Request):
    if not t.text.isascii() or any(ord(c) < 32 for c in t.text):
        raise HTTPException(422, "key combo must be printable ASCII on one line")
    return await act(phone.key(t.text), request)


@app.post("/api/home")
async def home(request: Request):
    return await act(phone.go_home(), request)


@app.post("/api/back")
async def back(request: Request):
    return await act(phone.go_back(), request)


@app.post("/api/raw")
async def raw(t: Text, request: Request):
    """Debug only: send one protocol line to the board as-is."""
    if not DEBUG:
        raise HTTPException(404)
    return await act(device.send(t.text), request)


@app.post("/api/calibrate/start")
async def calibrate_start(request: Request):
    """Calibrate the pointer. {"auto": true}: done by itself; otherwise the user clicks the pointer next."""
    try:
        async with control(request):
            return {"ok": True, "auto": await phone.start_calibration(), "span": phone.span}
    except (DeviceError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/calibrate/finish")
async def calibrate_finish(p: Point, request: Request):
    if not p.x or not p.y:
        raise HTTPException(422, "pointer coordinates must be greater than zero")
    async with control(request):
        phone.finish_calibration(p.x, p.y)
        return {"ok": True, "span": phone.span}


@app.post("/api/agent")
async def agent_start(t: Text, request: Request):
    try:
        async with control(request, claim=False):
            _, owner, source = identity(request)
            run_id = agent.start(t.text, source=source, owner=owner)
            ownership.release()
            ownership.record("task", owner, "Started local agent task")
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "id": run_id}


@app.post("/api/agent/stop")
async def agent_stop():
    """Emergency stop: cancel the agent and release the mouse button."""
    async with control_lock:
        agent.stop()
        await agent.wait_stopped()
        ownership.release(revoke=True)
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
async def task_start(task: TaskRequest, request: Request):
    """Delegate a bounded task; poll its returned URL for progress and a terminal result."""
    try:
        async with control(request, claim=False):
            _, owner, source = identity(request)
            run_id = agent.start(task.goal, task.max_steps, task.timeout_s, source=source, owner=owner)
            ownership.release()
            ownership.record("task", owner, "Delegated task" if source == "external" else "Started local agent task")
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


class ClaimRequest(BaseModel):
    ttl_s: int = Field(default=120, ge=15, le=300)


@app.post("/api/control/claim")
async def claim_control(body: ClaimRequest, request: Request):
    if agent.running or control_lock.locked():
        raise HTTPException(409, "phone is busy")
    async with control_lock:
        try:
            return ownership.claim(*identity(request), ttl=body.ttl_s, explicit=True)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e


@app.post("/api/control/release")
async def release_control(request: Request):
    async with control_lock:
        try:
            ownership.release(identity(request)[0])
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
    return {"ok": True}


@app.post("/api/control/takeover")
async def takeover_control(request: Request):
    """Explicitly cancel the current task/session and hand control to this caller."""
    async with control_lock:
        agent.stop()
        await agent.wait_stopped()
        ownership.release(revoke=True)
        lease = ownership.claim(*identity(request), explicit=True)
        if device.connected:
            try:
                await phone.reset()
            except (DeviceError, RuntimeError):
                ownership.record("warning", lease["owner"], "Controller disconnected during takeover")
        return lease


@app.get("/api/observation")
async def observe():
    return {"control": ownership.status(agent.run_info(), agent.running), "frame": observation()}


class ActionRequest(BaseModel):
    action: Literal["tap", "swipe", "scroll", "type", "key", "home", "back"]
    arguments: dict = Field(default_factory=dict)


@app.post("/api/control/action")
async def perform_action(body: ActionRequest, request: Request):
    """Act, wait briefly for the screen, and return the resulting image in one request."""
    if not screen.live:
        raise HTTPException(409, "screen mirroring is required before remote actions")
    name, args = body.action, body.arguments
    request.state.action = name.title()
    try:
        if name == "tap":
            p = Tap(**args)
            coro = phone.tap(p.x, p.y, aim=p.precise)
        elif name == "swipe":
            s = Swipe(**args)
            coro = phone.swipe(s.x1, s.y1, s.x2, s.y2)
        elif name == "scroll":
            s = Scroll(**args)
            coro = phone.scroll(s.x, s.y, s.lines)
        elif name in ("type", "key"):
            t = Text(**args)
            if not t.text.isascii() or any(ord(c) < 32 for c in t.text):
                raise HTTPException(422, "keyboard input must be printable ASCII on one line")
            coro = phone.type(t.text) if name == "type" else phone.key(t.text)
        elif args:
            raise HTTPException(422, "this action takes no arguments")
        else:
            coro = phone.go_home() if name == "home" else phone.go_back()
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e
    return await act(coro, request, capture=True)


@app.get("/api/tasks")
async def list_tasks():
    runs = list(agent._history.values())
    if agent.run_id:
        runs.append(agent.run_info())
    return [{k: v for k, v in run.items() if k != "steps"} for run in reversed(runs)]


@app.get("/api/capabilities")
def capabilities():
    """Host-independent discovery for MCP, REST, and CLI clients."""
    return {"protocol_version": "1", "device": {"kind": os.environ.get("DEVICE_KIND", "iphone"),
            "name": os.environ.get("DEVICE_NAME", screen.name if hasattr(screen, "name") else "iOS device"),
            "transport": "esp32-usb-hid", "screen": "airplay", "coordinates": "normalized_0_1",
            "ipad": "experimental; calibrate separately; gestures/layout differ"},
            "interaction": ["manual", "direct", "workflow", "vision_task"],
            "interfaces": {"mcp": "stdio bridge on any client host", "rest": "/openapi.json", "cli": "iphone-agent"},
            "workflow": {"max_steps": 32, "persistent_memory": False,
                         "jev_ready": bool(os.environ.get("TYPESAFE_API_KEY"))},
            "limitations": ["ASCII keyboard input", "one device per server instance",
                            "trusted private network required"]}


@app.get("/api/workflows")
def workflows_list():
    from .workflows import catalog
    try:
        return [r.model_dump() for r in catalog().values()]
    except (ValueError, OSError) as e:
        raise HTTPException(409, str(e)) from e


class WorkflowRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    recipe: dict | None = None
    timeout_s: float = Field(default=60, ge=1, le=300, allow_inf_nan=False)


@app.post("/api/workflows/run", status_code=202)
async def workflow_start(body: WorkflowRequest, request: Request):
    from .workflows import Recipe, catalog
    if (body.name is None) == (body.recipe is None):
        raise HTTPException(422, "provide exactly one of name or recipe")
    try:
        recipe = Recipe.model_validate(body.recipe) if body.recipe is not None else catalog()[body.name]
        recipe.commands()
    except KeyError as e:
        raise HTTPException(404, "unknown workflow") from e
    except (ValueError, OSError) as e:
        raise HTTPException(422, str(e)) from e
    try:
        async with control(request, claim=False):
            _, owner, source = identity(request)
            run_id = agent.start(recipe.description, len(recipe.steps), body.timeout_s,
                                 source=source, owner=owner, workflow=recipe)
            ownership.release()
            ownership.record("workflow", owner, recipe.name)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"id": run_id, "state": "running", "engine": "workflow", "status_url": f"/api/tasks/{run_id}"}


class RouteRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    context: str = Field(min_length=1, max_length=4000)


@app.post("/api/workflows/route")
async def workflow_route(body: RouteRequest):
    """Optional text-only Jev selection. This endpoint never moves the device."""
    from .workflows import catalog, route
    try:
        return await route(body.goal, body.context, catalog())
    except (RuntimeError, ValueError, OSError) as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Jev routing unavailable; use the remote agent") from e
