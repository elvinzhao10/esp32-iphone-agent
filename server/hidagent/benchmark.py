"""Repeatable, non-submitting Spotlight edit trials. Run on the device host.

Prepare focused Spotlight with the on-screen keyboard visible. No Enter, app launch,
clipboard operation or message submission is used. Model verification time is separate.
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from .client import IPhoneClient
from .llm import LLM
from .settings import load_settings
from .workflows import catalog, route

GOAL = "Replace the already focused Spotlight search query with Calendar. Do not open a result or submit."
CONTEXT = "Spotlight search field is visibly focused with its on-screen keyboard showing."
RECIPE = {"name": "trial-calendar", "description": GOAL, "precondition": CONTEXT, "settle": "final",
          "steps": [{"action": "edit_text", "arguments": {"text": "Calendar", "replace": True}}]}


async def run(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    provider = load_settings().actor
    verifier = LLM(provider.base_url, provider.model, provider.api_key)
    verifier._http.timeout = httpx.Timeout(30)
    rows = []
    router = httpx.AsyncClient(timeout=8, trust_env=False)
    client_id = "benchmark:control"
    with IPhoneClient(args.url, client_id=client_id, name="Control trials") as client:
        state = client.status()
        if state["agent"]["running"] or state["control"].get("client_id") not in (None, client_id):
            raise RuntimeError("device owned by another session; release it before trials")
        if not all(state[key] for key in ("device", "screen", "calibrated")):
            raise RuntimeError("controller, mirroring and calibration are required")
        client.claim(300)
        try:
            if not args.preflight_confirmed:
                reply = await verifier.chat("Answer YES or NO only based on the screenshot.",
                                            "Is this iOS Spotlight with its search field focused and keyboard visible?",
                                            client.screenshot(), max_tokens=100)
                if reply.strip().upper() != "YES":
                    raise RuntimeError("Spotlight precondition not verified; no text trial started")
            modes = args.modes.split(",")
            for trial in range(args.trials):
                order = modes[trial % len(modes):] + modes[:trial % len(modes)]
                for mode in order:
                    state = client.status()
                    if (state["control"].get("client_id") != client_id or state["agent"]["running"]
                            or not state["screen"] or not state["device"]):
                        raise RuntimeError("control session changed; stopping trials")
                    # Reset is identical and untimed for every mode; never press Enter.
                    client.action("edit_text", text="Notes", replace=True)
                    await asyncio.sleep(.4)
                    row = {"trial": trial + 1, "mode": mode}
                    started = time.perf_counter()
                    try:
                        if mode == "direct":
                            client.perform("key", text="cmd+a")
                            client.perform("type", text="Calendar")
                            row["state"] = "executed"
                        elif mode == "edit":
                            client.perform("edit_text", text="Calendar", replace=True)
                            row["state"] = "executed"
                        elif mode == "workflow":
                            job = client.workflow(recipe=RECIPE, timeout_s=30)
                            row["state"] = client.wait(job["id"], 40, .1)["state"]
                        elif mode == "jev":
                            job = await route(GOAL, CONTEXT, catalog(), client=router)
                            job["state"] = "needs_remote" if job["needs_remote"] else "selected"
                            if job["workflow"]:
                                job.update(client.workflow(name=job["workflow"], timeout_s=30))
                            row.update({k: v for k, v in job.items() if k in (
                                "route_ms", "confidence", "eligibility", "workflow", "state")})
                            if job.get("id"):
                                row["state"] = client.wait(job["id"], 75, .1)["state"]
                        elif mode == "vision":
                            job = client.delegate(GOAL, max_steps=3, timeout_s=60)
                            result = client.wait(job["id"], 75, .2)
                            row["state"] = result["state"]
                            row["rounds"] = result.get("rounds")
                            row["model_seconds"] = round(sum(s.get("think_s", 0) for s in result["steps"]), 3)
                        else:
                            raise ValueError("unknown trial mode")
                    except Exception as e:
                        row["state"], row["error"] = "error", str(e)[:200]
                    row["execution_s"] = round(time.perf_counter() - started, 3)
                    check_started = time.perf_counter()
                    await asyncio.sleep(.4)
                    shot = client.screenshot()
                    (output / f'{trial + 1}-{mode}.jpg').write_bytes(shot)
                    try:
                        reply = await verifier.chat("Answer YES or NO only based on visible evidence.",
                                                    "Is this Spotlight, with the search query exactly Calendar? "
                                                    "A search result mentioning Calendar alone is not enough.",
                                                    shot, max_tokens=100)
                        row["verified"] = reply.strip().upper() == "YES"
                        row["verification_reply"] = reply[:200]
                    except Exception as e:
                        row["verified"], row["verification_error"] = None, str(e)[:200]
                    row["verification_s"] = round(time.perf_counter() - check_started, 3)
                    rows.append(row)
                    (output / "results.json").write_text(json.dumps({"goal": GOAL, "rows": rows}, indent=2))
                    print(json.dumps(row), flush=True)
                    if row["verified"] is False:
                        raise RuntimeError("visible result failed verification; inspect the screen before more trials")
            summary = {mode: {"n": len(selected := [r for r in rows if r["mode"] == mode]),
                              "median_execution_s": statistics.median(r["execution_s"] for r in selected),
                              "verified": sum(r["verified"] is True for r in selected)} for mode in modes}
            (output / "summary.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps({"summary": summary}), flush=True)
        finally:
            try:
                state = client.status()
                if state["control"].get("client_id") == client_id:
                    if state["agent"]["running"]:
                        client.stop(state["agent"]["id"])
                    client.release()
            finally:
                await verifier._http.aclose()
                await router.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8890")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--modes", default="direct,edit,workflow,jev")
    parser.add_argument("--preflight-confirmed", action="store_true",
                        help="operator has visually verified focused Spotlight; record this in the trial report")
    args = parser.parse_args()
    if any(mode not in ("direct", "edit", "workflow", "jev", "vision") for mode in args.modes.split(",")):
        parser.error("unsupported mode")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
