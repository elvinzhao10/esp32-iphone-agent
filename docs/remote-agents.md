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

## Control-room dashboard and ownership

The dashboard now reports the **server's actual control state**, independently of
which workflow panel you are browsing:

| State | Who acts | Dashboard behavior |
|---|---|---|
| Manual | A dashboard user, or nobody yet | Live taps, swipes, typing, calibration |
| External agent | A CLI/MCP control session | Observe only; shows the controller and lease expiry |
| Delegated task | The local vision agent executing an external agent's goal | Observe progress/result; stop or take over |
| Local agent | The local vision agent executing a dashboard goal | Shows model readiness, limits, plan, progress and result |

The workflow cards select what you want to do; they do not pretend to change
ownership. Input is locked in both the UI and API when another controller owns the
phone. **Take control** explicitly cancels a running task, releases the pointer,
and revokes the previous session. **Emergency stop** remains available to every
trusted controller. A revoked session must explicitly claim again; it cannot
silently resume sending actions after the user takes over.

Direct-control sessions last 120 seconds without activity (explicit claims allow
15–300 seconds), and successful control requests renew them. Reads do not claim
or renew control. Call `release_control` or `iphone-agent release` when done.
The activity feed shows ownership changes and direct actions; task history lets
you inspect recent results. Task/session metadata remains in memory and is reset
on server restart. These leases coordinate trusted users; they are **not** a new
authentication boundary. Tailnet access restrictions still matter.

Each MCP bridge process generates a distinct client ID. CLI invocations on one
computer share an identity by default so sequences work across shell invocations.
For independent CLI agents, set a distinct `IPHONE_AGENT_CLIENT_ID` per agent and
optionally `IPHONE_AGENT_NAME` for its dashboard label. Raw API clients should send
stable `X-iPhone-Client` and `X-iPhone-Name` headers. Dashboard requests also send
`X-iPhone-Source: dashboard`; other clients are considered external. These labels
are client supplied, not verified identities.

Additional HTTP endpoints:

- `GET /api/observation`: control state plus JPEG, dimensions and frame timestamp.
- `POST /api/control/action`: `{ "action": "tap", "arguments": {"x":0.5,"y":0.4} }`;
  holds the gesture lock, executes the action, waits briefly, and returns the
  resulting JPEG in the same response. Keyboard and gesture arguments match the
  existing API. Remote actions require screen mirroring.
- `POST /api/control/claim`: optional `{ "ttl_s": 120 }`.
- `POST /api/control/release`: release your session.
- `POST /api/control/takeover`: explicit stop/revoke/takeover.
- `GET /api/tasks`: recent task summaries, newest first.

Direct taps now default to `precise: true`, using screenshot-based pointer
correction before clicking. Set it false on the HTTP/MCP tap tool to trade
accuracy for lower latency. Swipes and edge gestures can still require tuning.

The live preview fetches at most two frames per second while visible and pauses
frame requests in hidden tabs. Task/ownership status continues at a lower rate.

## A closer Codex workflow

Codex supports stdio MCP servers. Register the installed bridge with its absolute
path (substitute your path and Pi Tailscale IP):

```sh
codex mcp add iphone --env IPHONE_AGENT_NAME=Codex -- \
  /absolute/path/to/repo/server/.venv/bin/iphone-agent \
  --url http://100.x.y.z:8890 mcp
codex mcp list
```

Start a new Codex chat or reload its MCP connection after registration. This is a
custom MCP integration, not a replacement for the Codex app's built-in native
computer-use surface. See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

For direct use, ask Codex to:

1. Call `iphone_observe` for the live image, dimensions, and current owner.
2. Use the action tools. They now return **the resulting screenshot in the same
   tool response**, saving a separate screenshot call after each action.
3. Check that result before choosing the next action; do not execute guesses based
   on a stale screen. Stop if ownership changes or a tool reports a conflict.
4. Call `release_control` when finished.

For delegation, call `delegate_task`, retain its ID, and poll `task_status`.
`claim_control` is available for an explicit session or renewal. Observation and
status tools are marked read-only in MCP metadata. All 16 tools use the same
Tailscale-bound API. No additional model API key is needed for Codex's direct
control; delegated/local tasks still require the Pi's model configuration.
