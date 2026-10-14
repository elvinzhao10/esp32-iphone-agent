# Remote agents and task delegation

Use the Pi as an iPhone tool server. A powerful agent can run on your laptop or
another machine; the Pi keeps the AirPlay receiver, calibration, and USB bridge.
There is no extra always-on agent framework or local model on the Pi.

Two modes share the existing web/API port:

- **Direct control:** your external vision agent reads screenshots and calls taps,
  swipes, typing, keys, Home, and Back. It uses its own model; no model API key is
  needed on the Pi for these controls.
- **Delegation:** submit a goal to the Pi's specialized planner/actor. The Pi needs
  its own vision-model API configuration, mirroring, controller, and calibration.
  Submission returns immediately with a task ID; poll for progress and results.

## Network access

The API has the same access as the web UI. It has **no application authentication**;
only expose it to trusted controllers. Bind `HOST` to the Pi's Tailscale IPv4 address
and restrict port 8890 using your tailnet ACLs. Do not expose it to the internet.

On the Pi, set in `server/.env`:

```sh
HOST=100.x.y.z   # replace with `tailscale ip -4` on the Pi
PORT=8890
```

Restart the server after editing. This binds only the web/API listener; the ESP32
still connects on LAN TCP 7300 and AirPlay still uses the LAN. Binding the web UI
alone does not authenticate or restrict those separate protocols.

No new inbound port is needed for MCP: its stdio bridge runs on the **controlling
computer**, forwards to the Pi through Tailscale, and returns screenshots as MCP
image content. Tailscale must be connected on both machines. A cloud agent without
access to your tailnet cannot reach this address directly.

## CLI

On the controlling computer, from your clone:

```sh
python3 -m venv .venv
.venv/bin/pip install -e './server[mcp]'
export IPHONE_AGENT_URL=http://100.x.y.z:8890
.venv/bin/iphone-agent status
.venv/bin/iphone-agent screenshot screen.jpg
.venv/bin/iphone-agent tap 0.5 0.4
.venv/bin/iphone-agent swipe 0.5 0.8 0.5 0.3
.venv/bin/iphone-agent type 'Hello from my agent'
.venv/bin/iphone-agent key enter
.venv/bin/iphone-agent home
.venv/bin/iphone-agent back
```

**All remote-control coordinates are screen fractions from 0 to 1**, unlike the
built-in actor's internal 0–1000 coordinates. Text input supports printable ASCII
on one line; use `key enter` rather than embedding a newline. Observe a new
screenshot after each action whose outcome determines what happens next.

Calibration can be started with `iphone-agent calibrate`. If it returns `auto:
false`, the user must identify the visible pointer; finish with
`iphone-agent calibrate --pointer X Y`. Recalibrate after changing orientation,
AssistiveTouch speed, or the controlled phone.

```sh
# Asynchronous delegation (JSON includes id and status_url):
.venv/bin/iphone-agent task 'Open Settings and find Wi-Fi' --max-steps 30 --timeout 300
.venv/bin/iphone-agent task-status TASK_ID
.venv/bin/iphone-agent stop TASK_ID

# Wait for a result, or emergency-stop the currently running agent:
.venv/bin/iphone-agent task 'Open Settings' --wait
.venv/bin/iphone-agent stop
```

CLI stdout contains JSON (or MCP protocol messages in `mcp` mode). Diagnostics go
to stderr. Exit codes: 0 success/submission, 1 failed/cancelled task when waiting,
2 transport/input/API error. A client wait timeout does not cancel a remote task;
poll its ID again or stop it explicitly. The remote deadline still applies.

## MCP configuration

Register a **stdio** server in any MCP host. Use absolute paths, replacing the
example paths and Tailscale IP:

```json
{
  "mcpServers": {
    "iphone": {
      "command": "/absolute/path/to/repo/.venv/bin/iphone-agent",
      "args": ["--url", "http://100.x.y.z:8890", "mcp"]
    }
  }
}
```

Tools: `iphone_status`, `iphone_screenshot`, `iphone_tap`, `iphone_swipe`,
`iphone_scroll`, `iphone_type`, `iphone_key`, `iphone_home`, `iphone_back`,
`iphone_calibrate`, `delegate_task`, `task_status`, `stop_task`.

For direct operation, instruct your agent to observe the screenshot, act on one
visible target, and observe again. For delegation, call `delegate_task`, retain
its ID, and poll `task_status` until `succeeded`, `failed`, or `cancelled`.
Only claim success when the returned result supports it. Do not run competing
agents against the same phone. Individual HTTP gestures are serialized; the
caller is responsible for coordinating multi-call direct-control workflows.

## HTTP endpoints

The same FastAPI server publishes `/docs` and `/openapi.json`. Existing direct
controls are `/api/status`, `/api/frame.jpg`, `/api/tap`, `/api/swipe`, `/api/scroll`,
`/api/type`, `/api/key`, `/api/home`, `/api/back`, and `/api/calibrate/{start,finish}`.

```sh
curl "$IPHONE_AGENT_URL/api/status"
curl -X POST "$IPHONE_AGENT_URL/api/tasks" \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Open Settings","max_steps":30,"timeout_s":300}'
curl "$IPHONE_AGENT_URL/api/tasks/TASK_ID"
curl -X POST "$IPHONE_AGENT_URL/api/tasks/TASK_ID/stop"
```

`POST /api/tasks` returns HTTP 202 with `id`, `state`, and `status_url`. A status
response includes the goal, plan, timestamps, steps, result, and error. HTTP 409
means busy or not ready; 422 means invalid arguments; 404 means unknown/expired
ID. One delegated task owns the phone at a time: direct/manual controls and new
tasks are rejected until it completes or is stopped. Status and screenshots
remain available. Emergency stop cancels the task, waits for cleanup, and releases
the pointer. The last 10 previous task results and current result are kept **in
memory**, and disappear on server restart. Only 32 recent step images are retained;
older step image URLs return 404. Debug traces can retain all images on disk.

## Built-in agent improvements

The original planner/actor remains available for providers that only support text
replies. Configure each role independently through the existing `PLANNER_*` and
`ACTOR_*` variables (model, API base URL, API key, extra request body).

```sh
# Optional: for a vision model/provider supporting Chat Completions tool calls.
ACTOR_MODE=tools
# Default: ask the planner to check the final screenshot before accepting done.
VERIFY_COMPLETION=1
```

Tool mode asks for one structured action per screenshot, validates its arguments,
and retries invalid replies with validation feedback. It deliberately does not
silently fall back when a provider rejects tool calling: set `ACTOR_MODE=text`
for those providers. Both modes validate action ranges and keyboard input. The
agent rechecks screen availability after model calls, has bounded step/time
budgets, and uses the planner to reject unsupported completion claims. Verification
is another model judgment, not proof; test your selected models on your workflows.

The Pi runs no local vision model. Runtime RAM figures for unrelated frameworks
are not measurements of this stack; AirPlay/video decoding and screenshot storage
still contribute to total memory. MCP dependencies are optional and belong on the
controller unless you specifically need them on the Pi.
