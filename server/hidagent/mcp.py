"""Controller-side MCP stdio bridge; forwards to a device host over its existing HTTP API."""

import base64
import json
import os
import uuid

from .client import IPhoneClient


def create_server(url: str | None = None):
    try:
        from mcp.server.fastmcp import FastMCP, Image
        from mcp.types import TextContent, ToolAnnotations
    except ImportError as e:
        raise RuntimeError('Install MCP support on the controlling computer: pip install -e "server[mcp]"') from e

    client_id = os.environ.get("IPHONE_AGENT_CLIENT_ID") or f"mcp:{uuid.uuid4().hex}"
    name = os.environ.get("IPHONE_AGENT_NAME", "MCP agent")

    def connect():
        return IPhoneClient(url, client_id=client_id, name=name)

    def with_image(result):
        frame = result.pop("frame", None)
        content = [TextContent(type="text", text=json.dumps(result))]
        if frame:
            content[0].text = json.dumps({**result, "screen": {k: v for k, v in frame.items() if k != "data"}})
            content.append(Image(data=base64.b64decode(frame["data"]), format="jpeg").to_image_content())
        return content

    mcp = FastMCP("iPhone Agent", instructions=(
        "Start with iphone_observe. Action tools return the resulting screenshot; use that before the next action. "
        "Coordinates are fractions 0–1 of the image. Use release_control when finished. "
        "On an ownership conflict or dashboard takeover, stop and ask the user before claiming control again. "
        "Use direct controls, run_workflow for known short sequences, or delegate_task for vision reasoning. "
        "Never mix them concurrently. "
        "Poll task_status until terminal. stop_task is the emergency stop. "
        "Only act on the user's requested device task."))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def iphone_status() -> dict:
        """Read controller, screen, calibration, and current task readiness."""
        with connect() as client:
            return client.status()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def iphone_screenshot() -> Image:
        """Get the current iPhone screenshot as an image, not a file path."""
        with connect() as client:
            return Image(data=client.screenshot(), format="jpeg")

    @mcp.tool()
    def iphone_tap(x: float, y: float, precise: bool = True) -> list:
        """Tap a visible target at normalized coordinates 0–1. Observe again afterward."""
        with connect() as client:
            return with_image(client.perform("tap", x=x, y=y, precise=precise))

    @mcp.tool()
    def iphone_swipe(x1: float, y1: float, x2: float, y2: float) -> list:
        """Swipe from one normalized screen point to another; inspect the resulting screenshot."""
        with connect() as client:
            return with_image(client.perform("swipe", x1=x1, y1=y1, x2=x2, y2=y2))

    @mcp.tool()
    def iphone_scroll(x: float, y: float, lines: int) -> list:
        """Scroll at a screen fraction x,y; lines must be between -100 and 100."""
        with connect() as client:
            return with_image(client.perform("scroll", x=x, y=y, lines=lines))

    @mcp.tool()
    def iphone_type(text: str) -> list:
        """Type printable ASCII into the visibly focused field. No newlines or control characters."""
        with connect() as client:
            return with_image(client.perform("type", text=text))

    @mcp.tool()
    def iphone_key(combo: str) -> list:
        """Press a keyboard combination, e.g. enter, backspace, or cmd+a."""
        with connect() as client:
            return with_image(client.perform("key", text=combo))

    @mcp.tool()
    def iphone_home() -> list:
        """Swipe to the iPhone home screen."""
        with connect() as client:
            return with_image(client.perform("home"))

    @mcp.tool()
    def iphone_back() -> list:
        """Perform the iPhone back gesture."""
        with connect() as client:
            return with_image(client.perform("back"))

    @mcp.tool()
    def iphone_calibrate(x: float | None = None, y: float | None = None) -> dict:
        """Start auto-calibration. If auto=false, have the user locate the pointer and supply x,y to finish."""
        with connect() as client:
            return client.calibrate(x, y)

    @mcp.tool()
    def delegate_task(goal: str, max_steps: int = 40, timeout_s: float = 600) -> dict:
        """Delegate an iPhone goal to its configured vision agent. Returns a task id immediately.

        Requires controller, mirroring, calibration, and model configuration. Poll task_status for results.
        """
        with connect() as client:
            return client.delegate(goal, max_steps, timeout_s)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def task_status(task_id: str) -> dict:
        """Read delegated task state, plan, action history, result, and error by task id."""
        with connect() as client:
            return client.task_status(task_id)

    @mcp.tool()
    def stop_task(task_id: str | None = None) -> dict:
        """Cancel a task and release the pointer. Omit task_id for an emergency stop of the current agent."""
        with connect() as client:
            return client.stop(task_id)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def iphone_observe() -> list:
        """Get control ownership and the live screenshot together. Reading never takes control."""
        with connect() as client:
            return with_image(client.observe())

    @mcp.tool()
    def claim_control(ttl_s: int = 120) -> dict:
        """Explicitly claim or renew a control session. Ask the user first after a takeover/conflict."""
        with connect() as client:
            return client.claim(ttl_s)

    @mcp.tool()
    def release_control() -> dict:
        """Release this agent's phone session so the dashboard or another agent can take control."""
        with connect() as client:
            return client.release()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def device_capabilities() -> dict:
        """Discover device profile, coordinates, interfaces and limits. Works with any MCP agent."""
        with connect() as client:
            return client.capabilities()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_workflows() -> list:
        """Read small reusable recipes, their exact actions and required starting screen."""
        with connect() as client:
            return client.workflows()

    @mcp.tool()
    def run_workflow(name: str | None = None, recipe: dict | None = None, timeout_s: float = 60) -> dict:
        """Execute a known finite recipe without LLM calls. Supply exactly one of name or recipe.

        Observe and verify its precondition first. Inline recipe: name, description, precondition,
        steps:[{action,arguments,require_change:false}]. Coordinates 0–1; key arguments use combo.
        Up to 32 steps. Poll task_status; observe final screen to verify. Stop/takeover cancels it.
        """
        with connect() as client:
            return client.workflow(name, recipe, timeout_s)

    @mcp.tool()
    def route_workflow(goal: str, context: str) -> dict:
        """Optional Jev text router: choose a registered recipe or escalate. Does not execute it.

        Supply current observed screen context. Configure the router in the host dashboard. Sends
        goal/context and recipe descriptions to the configured TypeSafe or OpenAI-compatible endpoint.
        Verify preconditions before run_workflow.
        """
        with connect() as client:
            return client.route(goal, context)

    @mcp.tool()
    def iphone_multi_tap(x: float, y: float, count: int = 2, interval_ms: int = 100, precise: bool = False) -> list:
        """Double/triple click one visible target. Mouse HID; does not emulate multi-finger touch."""
        with connect() as client:
            return with_image(client.perform("multi_tap", x=x, y=y, count=count,
                                             interval_ms=interval_ms, precise=precise))

    @mcp.tool()
    def iphone_long_press(x: float, y: float, duration_ms: int = 600, precise: bool = False) -> list:
        """Hold one visible target for 300–2000 ms; returns the resulting screen."""
        with connect() as client:
            return with_image(client.perform("long_press", x=x, y=y, duration_ms=duration_ms, precise=precise))

    @mcp.tool()
    def iphone_edit_text(text: str, replace: bool = False, submit: bool = False) -> list:
        """Edit a visibly focused field in one call. Optional select-all and Enter. ASCII only.

        submit may send a message or confirm a form; use only when the user authorized that action.
        """
        with connect() as client:
            return with_image(client.perform("edit_text", text=text, replace=replace, submit=submit))

    @mcp.tool()
    def iphone_shortcut(name: str) -> list:
        """Keyboard shortcut: search, switch_app, select_all, copy, paste, undo, redo, next,
        previous, activate, escape, keyboard_home. iPad/app/iOS support varies; inspect the result.
        Clipboard is the device clipboard, not the controlling computer's clipboard.
        """
        with connect() as client:
            return with_image(client.perform("shortcut", name=name))

    @mcp.tool()
    def dispatch_workflow(goal: str, context: str) -> dict:
        """Explicitly route AND execute a known workflow with Jev; escalate if uncertain.

        Observe first and supply current screen context. Poll task_status; observe to verify completion.
        Unlike route_workflow, this tool executes device actions on a confident match.
        """
        with connect() as client:
            return client.dispatch(goal, context)

    return mcp


def serve(url: str | None = None):
    create_server(url).run(transport="stdio")
