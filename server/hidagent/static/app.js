// Control page: live phone, bilingual live log, and a wall of step screenshots.
const $ = (id) => document.getElementById(id);

// Theme follows the OS unless the user selects light or dark.
let theme = "system";
try {
  theme = localStorage.getItem("theme") || "system";
} catch {}
const systemTheme = matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  document.documentElement.dataset.theme =
    theme === "system" ? (systemTheme.matches ? "dark" : "light") : theme;
  $("theme").textContent = { system: "◐", dark: "☾", light: "☀" }[theme];
  $("theme").title = `Theme: ${theme}`;
}
$("theme").onclick = () => {
  theme = { system: "dark", dark: "light", light: "system" }[theme] || "system";
  try {
    localStorage.setItem("theme", theme);
  } catch {}
  applyTheme();
};
systemTheme.addEventListener("change", applyTheme);
applyTheme();
let recipes = [],
  routerReady = false,
  startingTask = false;
async function loadWorkflows() {
  try {
    const response = await fetch("/api/workflows");
    if (!response.ok)
      throw new Error("Cannot load workflows; check the host configuration.");
    recipes = await response.json();
    $("workflow-name").replaceChildren(
      ...recipes.map((r) => {
        const option = document.createElement("option");
        option.value = r.name;
        option.textContent = r.name;
        return option;
      }),
    );
    if (!recipes.length) {
      const option = document.createElement("option");
      option.textContent = "No workflows";
      option.value = "";
      $("workflow-name").append(option);
    }
    $("workflow-name").onchange();
  } catch (e) {
    $("workflow-precondition").textContent = e.message;
  }
}
$("workflow-name").onchange = () => {
  const recipe = recipes.find((r) => r.name === $("workflow-name").value);
  $("workflow-precondition").textContent = recipe
    ? `Requires: ${recipe.precondition}`
    : "No workflows.";
};
$("run-workflow").onclick = async () => {
  try {
    await post("/api/workflows/run", { name: $("workflow-name").value });
  } catch (e) {
    $("msg").textContent = e.message;
  }
};
loadWorkflows();

// ---- language ------------------------------------------------------------------------

let lang = "en";
try {
  lang = localStorage.getItem("lang") || "en";
} catch {
  /* private mode */
}
const t = (key) => I18N[lang][key] ?? I18N.en[key] ?? key;

function applyLang() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  document
    .querySelectorAll("#lang button")
    .forEach((b) => b.classList.toggle("on", b.dataset.lang === lang));
  $("examples").replaceChildren(
    ...t("examples").map((text) => {
      const b = document.createElement("button");
      b.textContent = text;
      b.addEventListener("click", () => {
        $("task").value = text;
        start(text);
      }); // one click runs the demo
      return b;
    }),
  );
  shown = ""; // re-render steps in the new language
  if (typeof applyMotion === "function") applyMotion();
}
document.querySelectorAll("#lang button").forEach((b) =>
  b.addEventListener("click", () => {
    lang = b.dataset.lang;
    try {
      localStorage.setItem("lang", lang);
    } catch {
      /* private mode */
    }
    applyLang();
  }),
);

// ---- motion (tap ripples, flowing swipe paths); remembered per browser -------------------

let motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
try {
  motion = (localStorage.getItem("motion") || (motion ? "on" : "off")) === "on";
} catch {
  /* private mode */
}
function applyMotion() {
  document.body.classList.toggle("still", !motion);
  $("motion").textContent = t(motion ? "motionOn" : "motionOff");
}
$("motion").addEventListener("click", () => {
  motion = !motion;
  try {
    localStorage.setItem("motion", motion ? "on" : "off");
  } catch {
    /* private mode */
  }
  applyMotion();
});

const say = (key) => {
  $("msg").textContent = key ? t(key) : "";
};
const clientId = (() => {
  try {
    let id = sessionStorage.getItem("iphone-client");
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("iphone-client", id);
    }
    return id;
  } catch {
    return `dashboard-${Math.random().toString(36).slice(2)}`;
  }
})();
const headers = {
  "Content-Type": "application/json",
  "X-iPhone-Client": clientId,
  "X-iPhone-Source": "dashboard",
  "X-iPhone-Name": "Dashboard",
};
async function post(path, body) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body || {}),
    });
    const data = await r.json().catch(() => ({}));
    $("msg").textContent = r.ok
      ? ""
      : (typeof data.detail === "string"
          ? data.detail
          : "Check the input values.") || r.statusText;
    if (r.ok) poll();
    return r.ok ? data : null;
  } catch {
    $("msg").textContent =
      "Connection lost. Check the connection to this host.";
    return null;
  }
}

// ---- step helpers --------------------------------------------------------------------

const fmt = (sec) =>
  sec == null ? "–" : sec < 10 ? `${sec.toFixed(1)}s` : `${Math.round(sec)}s`;
const isPlan = (s) => s.action.includes("plan");
const isBad = (s) => ["hiccup", "error", "fail"].includes(s.action);
const what = (s) => describeStep(s)[lang === "zh" ? 1 : 0];
// the model answers in English; a Chinese version is shown when it gives one
const why = (s) =>
  (lang === "zh" && s.thought_zh) || s.thought || s.answer || s.reason || "";
const planText = (s) => (lang === "zh" && s.plan_zh) || s.plan || "";
const times = (s) =>
  [
    s.think_s != null && `${t("thinking")} ${fmt(s.think_s)}`,
    s.act_s != null && `${t("doing")} ${fmt(s.act_s)}`,
  ]
    .filter(Boolean)
    .join(" · ");
const where = (s) =>
  (
    ({
      tap: () => ` (${s.x}, ${s.y})${s.precise ? " · precise" : ""}`,
      swipe: () => ` (${s.x1}, ${s.y1}) → (${s.x2}, ${s.y2})`,
      path: () => ` · ${s.points.length} pts`,
      circle: () => ` (${s.x}, ${s.y}) r=${s.r}`,
    })[s.action] || (() => "")
  )();

// Draw what the AI did on its screenshot (coordinates are 0-1000): yellow on black, plus a hand for taps.
// .ripple and .flow shapes are animated in CSS; body.still turns the motion off.
let aspect = 0.461; // frame width / height, from the server
function overlay(s) {
  const svg = (inner) =>
    `<svg viewBox="0 0 1000 1000" preserveAspectRatio="none">${inner}</svg>`;
  const stroke = (
    shape, // black casing under a yellow line, so it shows on any background
  ) =>
    `${shape.replace("/>", ` style="stroke:#000;fill:none" stroke-width="9" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>`)}
     ${shape.replace("/>", ` style="stroke:var(--hl);fill:none" stroke-width="5" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>`)}`;
  const dot = (x, y, r) =>
    `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${r * aspect}" style="fill:var(--hl);stroke:#000" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  const pts = (list) => list.map(([x, y]) => `${x},${y}`).join(" ");
  const flow = (
    list, // dashes that travel along the stroke, in its direction
  ) =>
    `<polyline class="flow" points="${pts(list)}" style="stroke:#000;fill:none" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linecap="round"/>`;
  switch (s.action) {
    case "tap":
    case "multi_tap":
    case "long_press": {
      // red, so the tap point stands out from the yellow swipe paths
      const ring = (cls, r, w, color) =>
        `<ellipse class="${cls}" cx="${s.x}" cy="${s.y}" rx="${r}" ry="${r * aspect}" style="stroke:${color};fill:none" stroke-width="${w}" vector-effect="non-scaling-stroke"/>`;
      return svg(
        ring("ripple", 100, 7, "var(--tap)") +
          ring("", 100, 11, "#000") +
          ring("", 100, 6, "var(--tap)") +
          `<ellipse cx="${s.x}" cy="${s.y}" rx="22" ry="${22 * aspect}" style="fill:var(--tap);stroke:#fff" stroke-width="3" vector-effect="non-scaling-stroke"/>`,
      );
    }
    case "swipe": {
      const a = Math.atan2((s.y2 - s.y1) / aspect, s.x2 - s.x1),
        l = 45;
      const head = (d) => [
        s.x2 - l * Math.cos(a + d),
        s.y2 - l * aspect * Math.sin(a + d),
      ];
      return svg(
        stroke(
          `<polyline points="${pts([
            [s.x1, s.y1],
            [s.x2, s.y2],
          ])}"/>`,
        ) +
          flow([
            [s.x1, s.y1],
            [s.x2, s.y2],
          ]) +
          stroke(
            `<polyline points="${pts([head(0.5), [s.x2, s.y2], head(-0.5)])}"/>`,
          ) +
          dot(s.x1, s.y1, 14),
      );
    }
    case "path":
      return svg(
        stroke(`<polyline points="${pts(s.points)}"/>`) +
          flow(s.points) +
          dot(...s.points[0], 12),
      );
    case "circle":
      return svg(
        stroke(
          `<ellipse cx="${s.x}" cy="${s.y}" rx="${s.r}" ry="${s.r * aspect}"/>`,
        ),
      );
    default:
      return "";
  }
}
// the 👆 sits on top of the svg as text, so it is not stretched
function hand(s) {
  if (!["tap", "multi_tap", "long_press"].includes(s.action)) return "";
  return `<span class="hand" style="left:${s.x / 10}%;top:${s.y / 10}%">👆</span>`;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

// Log line in the chosen language, newest at the bottom.
function logLine(s) {
  const li = el("li", isBad(s) ? "bad" : "");
  const head = el("div");
  head.append(
    el("span", "time", new Date(s.t * 1000).toLocaleTimeString()),
    el("span", "what", what(s) + where(s)),
  );
  li.append(head);
  const text = planText(s) || why(s);
  if (text) li.append(el("div", "why", text));
  if (times(s)) li.append(el("div", "meta", times(s)));
  return li;
}

// Wall card: screenshot with the action drawn on it.
function card(s, index, number, scale, runId) {
  const c = el("div", "card" + (isBad(s) ? " bad" : ""));
  if (s.shot) {
    const shot = el("div", "shot");
    const img = el("img");
    img.loading = "lazy";
    img.src = `/api/steps/${index}.jpg?run=${runId}`;
    const ov = el("div", "overlay");
    ov.innerHTML = overlay(s) + hand(s);
    shot.append(img, ov);
    shot.addEventListener("click", () => zoom(img.src, s));
    c.append(shot);
  }
  const body = el("div", "body");
  body.append(
    el(
      "div",
      "no",
      isPlan(s)
        ? t("planner")
        : lang === "zh"
          ? `第 ${number} 步`
          : `${t("step")} ${number}`,
    ),
    el("div", "what", what(s)),
    el("div", "why", isPlan(s) ? "" : why(s)),
  );
  if (s.think_s != null) {
    const bar = el("div", "bar");
    const a = el("div", "think"),
      b = el("div", "act");
    a.style.width = `${(s.think_s / scale) * 100}%`;
    b.style.width = `${((s.act_s || 0) / scale) * 100}%`;
    bar.append(a, b);
    body.append(bar, el("div", "times", times(s)));
  }
  c.append(body);
  return c;
}

function zoom(src, s) {
  $("zoom-img").src = src;
  $("zoom-overlay").innerHTML = overlay(s) + hand(s);
  $("zoom-text").textContent = `${what(s)} — ${why(s)}`;
  $("zoom").showModal();
}
$("zoom").addEventListener("click", () => $("zoom").close());

// ---- server-owned control state -------------------------------------------------------
let latest = null,
  inputAllowed = false,
  actionBusy = false,
  shown = "",
  selectedPanel = "manual";
let detectedMode = null;
let historyAt = 0,
  viewedRun = null,
  lastFrameAt = 0,
  calibrating = false,
  down = null;
const live = $("live");
const modes = {
  manual: "Manual",
  external: "External agent",
  local: "Local agent",
};
function choosePanel(panel) {
  selectedPanel = panel;
  document.querySelectorAll("[data-panel]").forEach((b) => {
    b.classList.toggle("selected", b.dataset.panel === panel);
    b.setAttribute("aria-pressed", String(b.dataset.panel === panel));
  });
  for (const name of ["manual", "external", "local"])
    $("panel-" + name).hidden = name !== panel;
}
document
  .querySelectorAll("[data-panel]")
  .forEach((b) =>
    b.addEventListener("click", () => choosePanel(b.dataset.panel)),
  );
$("mcp-command").textContent =
  `codex mcp add iphone --env IPHONE_AGENT_NAME=Codex -- /absolute/path/to/iphone-agent --url ${location.origin} mcp`;
$("copy-mcp").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("mcp-command").textContent);
    $("copy-mcp").textContent = "Copied";
  } catch {
    $("msg").textContent = "Select and copy the command above.";
  }
});
$("show-current").addEventListener("click", () => {
  viewedRun = null;
  shown = "";
  if (latest)
    renderRun(
      { ...latest.agent, goal: latest.agent.task },
      latest.agent.available_shots || [],
    );
});
$("take-control").addEventListener("click", async () => {
  if (await post("/api/control/takeover")) {
    viewedRun = null;
    choosePanel("manual");
  }
});
$("release-control").addEventListener("click", () =>
  post("/api/control/release"),
);

// ---- live screen, precision taps, and complete gestures -------------------------------
function frac(e) {
  const r = live.getBoundingClientRect(),
    ratio = live.naturalWidth / live.naturalHeight || r.width / r.height;
  const w = Math.min(r.width, r.height * ratio),
    h = w / ratio;
  return {
    x: Math.min(Math.max((e.clientX - r.left - (r.width - w) / 2) / w, 0), 1),
    y: Math.min(Math.max((e.clientY - r.top - (r.height - h) / 2) / h, 0), 1),
  };
}
async function input(path, body) {
  if (!inputAllowed || actionBusy) {
    $("input-state").textContent = actionBusy
      ? "Input in progress · try again when ready"
      : "View only";
    return;
  }
  actionBusy = true;
  const started = performance.now();
  $("input-state").textContent = "Sending input…";
  try {
    const result = await post(path, body);
    $("input-state").textContent = result
      ? `Input sent · ${Math.round(performance.now() - started)} ms`
      : "Input not sent";
    return result;
  } finally {
    actionBusy = false;
  }
}
live.addEventListener("pointerdown", (e) => {
  if (!inputAllowed) return;
  if (e.button !== 0 || actionBusy) return;
  e.preventDefault();
  down = {
    ...frac(e),
    points: [frac(e)],
    startedAt: performance.now(),
    startX: e.clientX,
    startY: e.clientY,
  };
  feedback(frac(e));
  live.setPointerCapture(e.pointerId);
});
live.addEventListener("pointermove", (e) => {
  if (!down) return;
  const point = frac(e),
    last = down.points.at(-1);
  if (
    Math.hypot(point.x - last.x, point.y - last.y) > 0.01 &&
    down.points.length < 31
  )
    down.points.push(point);
});
live.addEventListener("pointercancel", () => {
  down = null;
});
live.addEventListener("pointerup", async (e) => {
  if (!down || !inputAllowed) return;
  const up = frac(e),
    from = down;
  down = null;
  if (calibrating) {
    const result = await input("/api/calibrate/finish", up);
    calibrating = !result;
    calibrationHint(result ? "calOk" : "calNow");
  } else if (Math.hypot(e.clientX - from.startX, e.clientY - from.startY) < 7) {
    const gesture = $("gesture-mode").value;
    const duration = performance.now() - from.startedAt;
    if (gesture === "hold" || duration >= 450)
      await input("/api/long_press", {
        ...up,
        duration_ms: Math.min(2000, Math.max(600, Math.round(duration))),
        precise: $("precision").checked,
      });
    else if (gesture !== "1")
      await input("/api/multi_tap", {
        ...up,
        count: Number(gesture),
        precise: $("precision").checked,
      });
    else await input("/api/tap", { ...up, precise: $("precision").checked });
  } else
    await input("/api/gesture", { points: [...from.points, up], flick: true });
});
let wheelDelta = 0,
  wheelTimer = null;
function flushWheel() {
  wheelTimer = null;
  if (!inputAllowed) {
    wheelDelta = 0;
    return;
  }
  if (actionBusy) {
    wheelTimer = setTimeout(flushWheel, 50);
    return;
  }
  if (!wheelDelta) return;
  const delta = wheelDelta;
  wheelDelta = 0;
  const lines =
    -Math.sign(delta) *
    Math.min(12, Math.max(1, Math.round(Math.abs(delta) / 40)));
  input("/api/scroll", { x: 0.5, y: 0.5, lines });
}
live.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    if (!inputAllowed) return;
    wheelDelta +=
      e.deltaY *
      (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? live.clientHeight : 1);
    wheelDelta = Math.min(1000, Math.max(-1000, wheelDelta));
    if (!wheelTimer) wheelTimer = setTimeout(flushWheel, 80);
  },
  { passive: false },
);
function showFrame(url) {
  const old = live.src;
  if (url) live.src = url;
  else live.removeAttribute("src");
  if (old.startsWith("blob:")) URL.revokeObjectURL(old);
  $("hint").hidden = Boolean(url);
}
async function refreshLive() {
  const started = performance.now();
  if (!document.hidden) {
    let url = "";
    try {
      const r = await fetch("/api/frame.jpg", { cache: "no-store" });
      if (r.ok) {
        url = URL.createObjectURL(await r.blob());
        const next = new Image();
        next.src = url;
        await next.decode();
        aspect = next.naturalWidth / next.naturalHeight;
        fitPreview();
        showFrame(url);
        url = "";
        lastFrameAt = Date.now();
      } else showFrame("");
    } catch {
      if (Date.now() - lastFrameAt > 3000) showFrame("");
    } finally {
      if (url) URL.revokeObjectURL(url);
    }
  }
  setTimeout(
    refreshLive,
    document.hidden ? 2500 : Math.max(25, 125 - (performance.now() - started)),
  );
}
function fitPreview() {
  const factor = Number($("preview-size").value);
  const frame = document.querySelector(".screen");
  frame.style.aspectRatio = String(aspect);
  frame.style.setProperty("--device-aspect", String(aspect));
  document
    .querySelector("main")
    .style.setProperty(
      "--preview-width",
      `${Math.min(720, (aspect > 0.85 ? 560 : 350) * factor)}px`,
    );
}
$("preview-size").onchange = fitPreview;
function feedback(point) {
  const marker = document.createElement("span");
  marker.className = "input-feedback";
  marker.style.left = `${point.x * 100}%`;
  marker.style.top = `${point.y * 100}%`;
  live.parentElement.append(marker);
  setTimeout(() => marker.remove(), 400);
}
function calibrationHint(key) {
  $("caption").hidden = !key;
  $("caption").textContent = key ? t(key) : "";
  $("caption").classList.toggle("callout", Boolean(key));
  live.parentElement.classList.toggle("calibrating", key === "calNow");
}
document
  .querySelectorAll("[data-post]")
  .forEach((b) => b.addEventListener("click", () => input(b.dataset.post)));
$("cal").addEventListener("click", async () => {
  calibrationHint("calFinding");
  const r = await input("/api/calibrate/start");
  if (!r) return calibrationHint(null);
  calibrating = !r.auto;
  calibrationHint(r.auto ? "calOk" : "calNow");
});
$("type").addEventListener("click", async () => {
  if (
    await input("/api/edit_text", {
      text: $("text").value,
      replace: $("replace-text").checked,
      submit: $("submit-text").checked,
    })
  )
    $("text").value = "";
});
$("press").addEventListener("click", () =>
  input("/api/key", { text: $("key").value }),
);
async function start(goal) {
  if (!goal.trim()) return say("needTask");
  if (startingTask) return;
  startingTask = true;
  $("run").disabled = true;
  try {
    let result;
    if ($("fast-workflows").checked && routerReady) {
      $("msg").textContent = "Routing…";
      result = await post("/api/workflows/dispatch", {
        goal,
        context:
          "Controller connected and screen mirroring live. Screen contents have not been interpreted.",
      });
      if (!result) return;
    }
    if (!result || result.needs_remote)
      result = await post("/api/tasks", {
        goal,
        max_steps: Number($("max-steps").value),
        timeout_s: Number($("task-timeout").value),
      });
    if (result?.id) {
      viewedRun = null;
      choosePanel("local");
    }
  } finally {
    startingTask = false;
    poll();
  }
}
$("run").addEventListener("click", () => start($("task").value.trim()));
const stop = () => post("/api/agent/stop");
$("stop").addEventListener("click", stop);
$("estop").addEventListener("click", stop);
$("clear").addEventListener("click", async () => {
  if (await post("/api/agent/clear")) {
    $("task").value = "";
    viewedRun = null;
    say(null);
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("zoom").open) stop();
});

// ---- task details and bounded history -------------------------------------------------
function renderRun(a, available = []) {
  const steps = a.steps || [],
    running = a.state === "running" || a.running;
  $("current-task").hidden = !a.id;
  if (!a.id) return;
  $("current-goal").textContent = a.goal || a.task;
  $("task-origin").textContent =
    `${a.engine === "workflow" ? "FINITE WORKFLOW" : a.source === "external" ? "DELEGATED VISION" : "LOCAL VISION"} · ${a.owner || "Dashboard"} · ${a.id.slice(0, 8)}`;
  $("st-state").textContent =
    {
      running: "Working",
      succeeded: "Complete",
      failed: "Failed",
      cancelled: "Stopped",
    }[a.state] || "Idle";
  const actions = steps.filter((s) => s.act_s != null);
  $("st-steps").textContent = actions.length;
  $("st-time").textContent = a.started_at
    ? fmt((a.finished_at || Date.now() / 1000) - a.started_at)
    : "–";
  $("st-step").textContent = actions.length
    ? fmt(
        actions.reduce((sum, s) => sum + (s.think_s || 0) + s.act_s, 0) /
          actions.length,
      )
    : "–";
  $("task-progress").max = a.max_steps || 40;
  $("task-progress").value = a.rounds || 0;
  $("task-progress").title =
    `${a.rounds || 0} of ${a.max_steps || 40} decision rounds`;
  $("task-result").textContent =
    a.result ||
    a.error ||
    (running ? "Watching the screen and choosing the next action…" : "");
  const key = lang + a.id + JSON.stringify(steps) + available.join(",");
  if (key === shown) return;
  shown = key;
  const plan = [...steps].reverse().find((s) => s.plan);
  $("plan").hidden = !plan;
  if (plan)
    $("plan-list").replaceChildren(
      ...planText(plan)
        .split("\n")
        .map((l) => l.replace(/^\s*\d+[.)]\s*/, "").trim())
        .filter(Boolean)
        .map((l) => el("li", "", l)),
    );
  const scale = Math.max(
    1,
    ...steps.map((s) => (s.think_s || 0) + (s.act_s || 0)),
  );
  let n = 0;
  $("wall").replaceChildren(
    ...steps
      .map((s, i) =>
        card(
          { ...s, shot: s.shot && available.includes(i) },
          i,
          isPlan(s) ? n : ++n,
          scale,
          a.id,
        ),
      )
      .reverse(),
  );
}
async function refreshHistory() {
  try {
    const r = await fetch("/api/tasks");
    if (!r.ok) return;
    const runs = await r.json();
    $("history").replaceChildren(
      ...(runs.length
        ? runs.map((run) => {
            const b = el("button", "history-row");
            b.append(
              el("span", "history-goal", run.goal),
              el("span", "badge", run.state),
            );
            b.addEventListener("click", async () => {
              const r = await fetch(`/api/tasks/${run.id}`);
              if (!r.ok) return;
              viewedRun = await r.json();
              renderRun(viewedRun, []);
              $("current-task").scrollIntoView({
                behavior: "smooth",
                block: "nearest",
              });
            });
            return b;
          })
        : [el("p", "empty", "No tasks")]),
    );
  } catch {
    /* keep the last history during reconnect */
  }
}
document.querySelectorAll("[data-feed]").forEach((b) =>
  b.addEventListener("click", () => {
    const history = b.dataset.feed === "history";
    document
      .querySelectorAll("[data-feed]")
      .forEach((tab) => tab.classList.toggle("selected", tab === b));
    $("history").hidden = !history;
    $("log").hidden = history;
    $("feed-caption").textContent = history
      ? "Recent task results · retained until restart"
      : "Live operations and ownership changes";
    if (history) refreshHistory();
  }),
);

// ---- poll the authoritative state; viewing never claims the phone ----------------------
let pollTimer = null,
  polling = false;
async function poll() {
  if (polling) return;
  clearTimeout(pollTimer);
  polling = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("status unavailable");
    const s = await response.json();
    latest = s;
    $("server-state").textContent = "Connected";
    $("server-dot").classList.add("on");
    const c = s.control,
      a = s.agent,
      own = !c.client_id || c.client_id === clientId;
    inputAllowed = c.mode === "manual" && own && s.device && s.screen;
    const controlKey = `${c.mode}:${c.activity || ""}:${c.task_id || ""}`;
    if (detectedMode !== controlKey) {
      detectedMode = controlKey;
      choosePanel(c.mode);
    }
    document.body.dataset.mode = c.mode;
    $("mode-badge").textContent = modes[c.mode];
    $("owner").textContent = c.owner;
    $("take-control").textContent = a.running
      ? "Stop & take control"
      : "Take control";
    $("release-control").hidden = !c.client_id || !own;
    $("input-lock").hidden = inputAllowed;
    $("input-lock").textContent = s.screen ? "View only" : "Start mirroring";
    $("external-activity").textContent =
      c.mode === "external"
        ? c.activity === "delegated"
          ? `Hybrid · ${c.engine === "workflow" ? "Workflow" : "Vision"}`
          : "Direct"
        : "Direct · Hybrid";
    $("external-owner").textContent =
      c.mode === "external" ? `Connected: ${c.owner}` : "Not connected";
    $("lease-time").textContent = c.expires_at
      ? `Session expires in ${Math.max(0, Math.ceil(c.expires_at - Date.now() / 1000))}s without activity`
      : "";
    $("frame-state").textContent =
      s.screen && Date.now() - lastFrameAt < 4000 ? "Live" : "Offline";
    $("setup")
      .querySelectorAll("li")
      .forEach((li) => li.classList.toggle("done", Boolean(s[li.dataset.key])));
    const ready =
      s.device &&
      s.screen &&
      s.calibrated &&
      (s.configuration.model_ready || routerReady);
    $("save-providers").disabled = a.running || !own || c.mode === "external";
    $("run").disabled =
      startingTask || a.running || !ready || !own || c.mode === "external";
    $("examples")
      .querySelectorAll("button")
      .forEach((b) => {
        b.disabled = $("run").disabled;
      });
    document
      .querySelectorAll(
        "[data-post], [data-shortcut], #live-keyboard, #cal, #type, #press",
      )
      .forEach((b) => {
        b.disabled = !inputAllowed;
      });
    $("stop").hidden = !a.running;
    $("clear").hidden =
      a.running || !a.id || Boolean(viewedRun && viewedRun.id !== a.id);
    $("show-current").hidden = !viewedRun || viewedRun.id === a.id;
    $("live-dot").classList.toggle("on", a.running);
    $("m-planner").textContent = s.models.planner || "Not configured";
    $("m-actor").textContent = s.models.actor || "Not configured";
    $("m-planner-s").textContent = s.configuration.planner_key_set
      ? "API key configured"
      : "No API key supplied";
    $("m-actor-s").textContent = s.configuration.actor_key_set
      ? "API key configured"
      : "No API key supplied";
    $("actor-format").textContent =
      s.configuration.actor_mode === "tools"
        ? "Structured tools"
        : "Text actions";
    $("verification-state").textContent = s.configuration.verify_completion
      ? "Completion verification on"
      : "Completion verification off";
    $("model-health").textContent = s.configuration.model_ready
      ? "Ready"
      : "Model needed";
    $("model-warning").hidden = s.configuration.model_ready;
    $("model-warning").textContent = "Set up a vision model in Settings.";
    aspect = s.aspect || aspect;
    fitPreview();
    document.querySelector(".screen").style.aspectRatio = String(aspect);
    document
      .querySelector(".screen")
      .style.setProperty("--device-aspect", String(aspect));
    $("run-workflow").disabled =
      !s.device ||
      !s.screen ||
      !s.calibrated ||
      a.running ||
      !inputAllowed ||
      !recipes.length;
    if (!viewedRun || viewedRun.id === a.id)
      renderRun({ ...a, goal: a.task }, a.available_shots || []);
    const events = (s.activity || []).map((e) => ({
      t: e.t,
      action: e.kind,
      reason: `${e.owner} · ${e.detail}`,
    }));
    const logs = [...events, ...a.steps].sort((x, y) => x.t - y.t).slice(-60);
    $("log").replaceChildren(
      ...(logs.length ? logs.map(logLine) : [el("li", "empty", "No activity")]),
    );
    if (Date.now() - historyAt > 5000 && !$("history").hidden) {
      historyAt = Date.now();
      refreshHistory();
    }
  } catch {
    inputAllowed = false;
    $("server-state").textContent = "Reconnecting…";
    $("server-dot").classList.remove("on");
    $("run").disabled = true;
    $("run-workflow").disabled = true;
    $("save-providers").disabled = true;
    $("input-lock").hidden = false;
    $("input-lock").textContent = "Connection lost";
    document
      .querySelectorAll(
        "[data-post], [data-shortcut], #live-keyboard, #cal, #type, #press",
      )
      .forEach((b) => {
        b.disabled = true;
      });
  }
  polling = false;
  pollTimer = setTimeout(poll, document.hidden ? 2500 : 500);
}
applyLang();
applyMotion();
choosePanel("manual");
refreshLive();
poll();

// Shared provider configuration; stored keys are represented only by key_set.
async function loadProviders() {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) throw new Error("Provider settings unavailable");
    const settings = await response.json();
    routerReady = Boolean(
      settings.jev.model &&
        (settings.jev.key_set || settings.jev.protocol === "openai"),
    );
    $("provider-fields").replaceChildren();
    for (const [role, title] of [
      ["actor", "Actor"],
      ["planner", "Planner"],
      ["jev", "Jev / Router"],
    ]) {
      const box = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = title;
      box.append(legend);
      const values = settings[role];
      const fields =
        role === "jev"
          ? ["protocol", "base_url", "model", "api_key", "min_confidence"]
          : ["base_url", "model", "api_key"];
      for (const key of fields) {
        const label = document.createElement("label");
        label.textContent = {
          protocol: "API protocol",
          base_url: "Base URL",
          model: "Model",
          api_key: "API key",
          min_confidence: "Confidence",
        }[key];
        const field = document.createElement(
          key === "protocol" ? "select" : "input",
        );
        field.name = `${role}.${key}`;
        if (key === "protocol") {
          for (const [value, text] of [
            ["typesafe", "TypeSafe System One"],
            ["openai", "OpenAI-compatible"],
          ]) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            field.append(option);
          }
        } else
          field.type =
            key === "api_key"
              ? "password"
              : key === "min_confidence"
                ? "number"
                : "text";
        if (key === "api_key") {
          field.autocomplete = "new-password";
          field.placeholder = values.key_set
            ? "Configured · blank keeps key if URL unchanged"
            : "Not configured";
        } else field.value = values[key] ?? "";
        if (key === "min_confidence") {
          field.min = 0;
          field.max = 1;
          field.step = 0.01;
        }
        label.append(field);
        box.append(label);
      }
      $("provider-fields").append(box);
    }
  } catch (e) {
    $("provider-result").textContent = e.message;
  }
}
$("providers-form").onsubmit = async (e) => {
  e.preventDefault();
  const patch = { actor: {}, planner: {}, jev: {} };
  for (const [name, value] of new FormData(e.currentTarget)) {
    const [role, key] = name.split(".");
    if (key === "api_key" && !value) continue;
    patch[role][key] = key === "min_confidence" ? Number(value) : value;
  }
  $("save-providers").disabled = true;
  const result = await post("/api/settings", patch);
  if (result) {
    $("provider-result").textContent = "Saved";
    await loadProviders();
  } else $("provider-result").textContent = "Could not save settings";
};
loadProviders();

$("open-settings").onclick = () => {
  const panel = $("provider-settings");
  panel.open = !panel.open;
  if (panel.open)
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
};

// Focused keyboard forwarding only; browser/global shortcuts remain untouched elsewhere.
let keyQueue = [],
  keySending = false;
function queueKey(path, body) {
  if (!inputAllowed) return;
  const last = keyQueue.at(-1);
  if (
    path === "/api/type" &&
    last?.path === path &&
    last.body.text.length + body.text.length <= 4000
  )
    last.body.text += body.text;
  else if (keyQueue.length < 32) keyQueue.push({ path, body });
  else {
    $("msg").textContent = "Keyboard queue full";
    return;
  }
  flushKeys();
}
async function flushKeys() {
  if (keySending) return;
  keySending = true;
  try {
    while (keyQueue.length && inputAllowed) {
      if (actionBusy) {
        await new Promise((resolve) => setTimeout(resolve, 30));
        continue;
      }
      const item = keyQueue.shift();
      if (!(await input(item.path, item.body))) {
        keyQueue = [];
        break;
      }
    }
    if (!inputAllowed) keyQueue = [];
  } finally {
    keySending = false;
  }
}
function queueText(text) {
  if (!text || !/^[\x20-\x7e]+$/.test(text)) {
    $("msg").textContent = "USB keyboard supports ASCII only";
    return;
  }
  queueKey("/api/type", { text });
}
$("live-keyboard").addEventListener("input", (e) => {
  if (e.isComposing) return;
  const text = e.target.value;
  e.target.value = "";
  if (text) queueText(text);
});
$("live-keyboard").addEventListener("keydown", (e) => {
  if (e.isComposing) return;
  const special = {
    Enter: "enter",
    Backspace: "backspace",
    Tab: "tab",
    ArrowUp: "up",
    ArrowDown: "down",
    ArrowLeft: "left",
    ArrowRight: "right",
  };
  const mods = [
    e.metaKey ? "cmd" : null,
    e.ctrlKey ? "ctrl" : null,
    e.altKey ? "alt" : null,
    e.shiftKey ? "shift" : null,
  ].filter(Boolean);
  if (
    special[e.key] ||
    ((e.metaKey || e.ctrlKey || e.altKey) &&
      e.key.length === 1 &&
      e.key !== "+")
  ) {
    e.preventDefault();
    e.stopPropagation();
    queueKey("/api/key", {
      text: [
        ...mods,
        special[e.key] || (e.key === " " ? "space" : e.key.toLowerCase()),
      ].join("+"),
    });
  }
});
live.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  if (e.button === 2 && inputAllowed && !calibrating)
    input("/api/long_press", { ...frac(e), duration_ms: 600 });
});
document
  .querySelectorAll("[data-shortcut]")
  .forEach(
    (button) =>
      (button.onclick = () =>
        input("/api/shortcut", { name: button.dataset.shortcut })),
  );
