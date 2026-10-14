"""Remote iPhone controls and bounded task delegation. Run `iphone-agent --help`."""

import argparse
import json
import sys
from pathlib import Path

import httpx

from .client import IPhoneClient


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--url", help="Device host URL; defaults to IPHONE_AGENT_URL or http://127.0.0.1:8890")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    shot = sub.add_parser("screenshot")
    shot.add_argument("output", type=Path)
    for name, keys in {"tap": ("x", "y"), "swipe": ("x1", "y1", "x2", "y2"),
                       "scroll": ("x", "y", "lines")}.items():
        action = sub.add_parser(name, help="coordinates are screen fractions from 0 to 1")
        for key in keys:
            action.add_argument(key, type=int if key == "lines" else float)
    for name in ("type", "key"):
        action = sub.add_parser(name)
        action.add_argument("text")
    for name in ("home", "back", "mcp", "claim", "release", "tasks", "capabilities", "workflows"):
        sub.add_parser(name)
    workflow = sub.add_parser("workflow", help="run a registered recipe or a JSON recipe file")
    workflow.add_argument("--name")
    workflow.add_argument("--file", type=Path)
    workflow.add_argument("--timeout", type=float, default=60)
    workflow.add_argument("--wait", action="store_true")
    route = sub.add_parser("route", help="Jev recipe selection only; does not execute")
    route.add_argument("goal")
    route.add_argument("context", help="current observed screen description")
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--pointer", nargs=2, type=float, metavar=("X", "Y"))
    task = sub.add_parser("task")
    task.add_argument("goal")
    task.add_argument("--max-steps", type=int, default=40)
    task.add_argument("--timeout", type=float, default=600, help="remote task deadline in seconds")
    task.add_argument("--wait", action="store_true")
    task_status = sub.add_parser("task-status")
    task_status.add_argument("id")
    stop = sub.add_parser("stop")
    stop.add_argument("id", nargs="?")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "mcp":
            from .mcp import serve
            serve(args.url)
            return 0
        with IPhoneClient(args.url) as client:
            match args.command:
                case "status": result = client.status()
                case "capabilities": result = client.capabilities()
                case "workflows": result = {"workflows": client.workflows()}
                case "route": result = client.route(args.goal, args.context)
                case "workflow":
                    recipe = json.loads(args.file.read_text()) if args.file else None
                    result = client.workflow(args.name, recipe, args.timeout)
                    if args.wait:
                        result = client.wait(result["id"], args.timeout + 15)
                case "claim": result = client.claim()
                case "release": result = client.release()
                case "tasks": result = {"tasks": client.tasks()}
                case "screenshot":
                    args.output.write_bytes(client.screenshot())
                    result = {"path": str(args.output.resolve())}
                case "tap": result = client.action("tap", x=args.x, y=args.y)
                case "swipe": result = client.action("swipe", x1=args.x1, y1=args.y1, x2=args.x2, y2=args.y2)
                case "scroll": result = client.action("scroll", x=args.x, y=args.y, lines=args.lines)
                case "type" | "key": result = client.action(args.command, text=args.text)
                case "home" | "back": result = client.action(args.command)
                case "calibrate": result = client.calibrate(*(args.pointer or []))
                case "task":
                    result = client.delegate(args.goal, args.max_steps, args.timeout)
                    if args.wait:
                        print(json.dumps(result), file=sys.stderr, flush=True)
                        result = client.wait(result["id"], args.timeout + 15)
                case "task-status": result = client.task_status(args.id)
                case "stop": result = client.stop(args.id)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("state") in ("failed", "cancelled") else 0
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
