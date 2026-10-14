"""Controller-side MCP stdio bridge; forwards to the Pi over its existing HTTP API."""

from .client import IPhoneClient


def create_server(url: str | None = None):
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as e:
        raise RuntimeError('Install MCP support on the controlling computer: pip install -e "server[mcp]"') from e

    mcp = FastMCP("iPhone Agent", instructions=(
        "Observe with iphone_screenshot before acting. Coordinates are fractions 0–1 of the image. "
        "Use either direct controls or delegate_task, not both simultaneously. "
        "Poll task_status until terminal. stop_task is the emergency stop. "
        "Only act on the user's requested device task."))

    @mcp.tool()
    def iphone_status() -> dict:
        """Read controller, screen, calibration, and current task readiness."""
        with IPhoneClient(url) as client:
            return client.status()

    @mcp.tool()
    def iphone_screenshot() -> Image:
        """Get the current iPhone screenshot as an image, not a file path."""
        with IPhoneClient(url) as client:
            return Image(data=client.screenshot(), format="jpeg")

    @mcp.tool()
    def iphone_tap(x: float, y: float) -> dict:
        """Tap a visible target at normalized coordinates 0–1. Observe again afterward."""
        with IPhoneClient(url) as client:
            return client.action("tap", x=x, y=y)

    @mcp.tool()
    def iphone_swipe(x1: float, y1: float, x2: float, y2: float) -> dict:
        """Swipe from one normalized screen point to another; inspect the resulting screenshot."""
        with IPhoneClient(url) as client:
            return client.action("swipe", x1=x1, y1=y1, x2=x2, y2=y2)

    @mcp.tool()
    def iphone_scroll(x: float, y: float, lines: int) -> dict:
        """Scroll at a screen fraction x,y; lines must be between -100 and 100."""
        with IPhoneClient(url) as client:
            return client.action("scroll", x=x, y=y, lines=lines)

    @mcp.tool()
    def iphone_type(text: str) -> dict:
        """Type printable ASCII into the visibly focused field. No newlines or control characters."""
        with IPhoneClient(url) as client:
            return client.action("type", text=text)

    @mcp.tool()
    def iphone_key(combo: str) -> dict:
        """Press a keyboard combination, e.g. enter, backspace, or cmd+a."""
        with IPhoneClient(url) as client:
            return client.action("key", text=combo)

    @mcp.tool()
    def iphone_home() -> dict:
        """Swipe to the iPhone home screen."""
        with IPhoneClient(url) as client:
            return client.action("home")

    @mcp.tool()
    def iphone_back() -> dict:
        """Perform the iPhone back gesture."""
        with IPhoneClient(url) as client:
            return client.action("back")

    @mcp.tool()
    def iphone_calibrate(x: float | None = None, y: float | None = None) -> dict:
        """Start auto-calibration. If auto=false, have the user locate the pointer and supply x,y to finish."""
        with IPhoneClient(url) as client:
            return client.calibrate(x, y)

    @mcp.tool()
    def delegate_task(goal: str, max_steps: int = 40, timeout_s: float = 600) -> dict:
        """Delegate an iPhone goal to its configured vision agent. Returns a task id immediately.

        Requires controller, mirroring, calibration, and model configuration. Poll task_status for results.
        """
        with IPhoneClient(url) as client:
            return client.delegate(goal, max_steps, timeout_s)

    @mcp.tool()
    def task_status(task_id: str) -> dict:
        """Read delegated task state, plan, action history, result, and error by task id."""
        with IPhoneClient(url) as client:
            return client.task_status(task_id)

    @mcp.tool()
    def stop_task(task_id: str | None = None) -> dict:
        """Cancel a task and release the pointer. Omit task_id for an emergency stop of the current agent."""
        with IPhoneClient(url) as client:
            return client.stop(task_id)

    return mcp


def serve(url: str | None = None):
    create_server(url).run(transport="stdio")
