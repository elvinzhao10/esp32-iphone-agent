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
  $("theme").textContent = `Theme: ${theme}`;
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
let recipes = [];
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
      option.textContent = "No workflows configured";
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
    ? `Start only when: ${recipe.precondition}`
    : "Configure WORKFLOWS_FILE on this host to add reusable recipes.";
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
    case "tap": {
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
  if (s.action !== "tap") return "";
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
let historyAt = 0,
  viewedRun = null,
  lastFrameAt = 0,
  calibrating = false,
  down = null;
const live = $("live");
const modes = {
  manual: "Manual",
  external: "External agent",
  delegated: "Delegated task",
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
  if (!inputAllowed || actionBusy) return;
  actionBusy = true;
  try {
    return await post(path, body);
  } finally {
    actionBusy = false;
  }
}
live.addEventListener("pointerdown", (e) => {
  if (!inputAllowed) return;
  down = frac(e);
  live.setPointerCapture(e.pointerId);
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
  } else if (Math.hypot(up.x - from.x, up.y - from.y) < 0.02) {
    await input("/api/tap", { ...up, precise: true });
  } else
    await input("/api/swipe", { x1: from.x, y1: from.y, x2: up.x, y2: up.y });
});
let wheelAt = 0;
live.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    if (!inputAllowed || Date.now() - wheelAt < 400) return;
    wheelAt = Date.now();
    input("/api/scroll", { ...frac(e), lines: e.deltaY > 0 ? -3 : 3 });
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
  if (!document.hidden) {
    try {
      const r = await fetch("/api/frame.jpg", { cache: "no-store" });
      showFrame(r.ok ? URL.createObjectURL(await r.blob()) : "");
      if (r.ok) lastFrameAt = Date.now();
    } catch {
      showFrame("");
    }
  }
  setTimeout(refreshLive, document.hidden ? 2500 : 500);
}
function calibrationHint(key) {
  $("caption").textContent = t(key || "liveCaption");
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
  if (await input("/api/type", { text: $("text").value })) $("text").value = "";
});
$("press").addEventListener("click", () =>
  input("/api/key", { text: $("key").value }),
);
async function start(goal) {
  if (!goal.trim()) return say("needTask");
  const result = await post("/api/tasks", {
    goal,
    max_steps: Number($("max-steps").value),
    timeout_s: Number($("task-timeout").value),
  });
  if (result) {
    viewedRun = null;
    choosePanel("local");
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
        : [el("p", "empty", "Completed and stopped tasks will appear here.")]),
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
async function poll() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("status unavailable");
    const s = await response.json();
    latest = s;
    $("server-state").textContent = "Host connected";
    $("server-dot").classList.add("on");
    const c = s.control,
      a = s.agent,
      own = !c.client_id || c.client_id === clientId;
    inputAllowed = c.mode === "manual" && own && s.device && s.screen;
    document.body.dataset.mode = c.mode;
    $("mode-badge").textContent = modes[c.mode];
    $("owner").textContent = c.owner;
    $("ownership-detail").textContent =
      c.mode === "delegated"
        ? "Your external agent handed this task to the phone agent."
        : c.mode === "local"
          ? "The local vision agent is operating the phone."
          : c.mode === "external"
            ? "External tools own input. This dashboard is observing."
            : own
              ? "Ready for your input."
              : "Another dashboard owns input.";
    $("take-control").textContent = a.running
      ? "Stop & take control"
      : "Take control";
    $("release-control").hidden = !c.client_id || !own;
    $("input-lock").hidden = inputAllowed;
    $("input-lock").textContent = s.screen
      ? "View only · take control to interact"
      : "Screen sharing offline";
    $("external-owner").textContent =
      c.mode === "external" || c.mode === "delegated"
        ? `Connected: ${c.owner}`
        : "No external controller currently owns input";
    $("lease-time").textContent = c.expires_at
      ? `Session expires in ${Math.max(0, Math.ceil(c.expires_at - Date.now() / 1000))}s without activity`
      : "";
    $("frame-state").textContent =
      s.screen && Date.now() - lastFrameAt < 4000
        ? "Live · 2 fps preview"
        : "Waiting for mirroring";
    $("setup")
      .querySelectorAll("li")
      .forEach((li) => li.classList.toggle("done", Boolean(s[li.dataset.key])));
    const ready =
      s.device && s.screen && s.calibrated && s.configuration.model_ready;
    $("run").disabled = a.running || !ready || !own || c.mode === "external";
    $("examples")
      .querySelectorAll("button")
      .forEach((b) => {
        b.disabled = $("run").disabled;
      });
    document
      .querySelectorAll("[data-post], #cal, #type, #press")
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
      ? "Models configured"
      : "Model setup needed";
    $("model-warning").hidden = s.configuration.model_ready;
    $("model-warning").textContent =
      "Configure the model endpoint, model name, and API key in server/.env on this host, then restart the service. External direct control uses its own model.";
    aspect = s.aspect || aspect;
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
      ...(logs.length
        ? logs.map(logLine)
        : [
            el(
              "li",
              "empty",
              "Nothing running. Your device is ready when you are.",
            ),
          ]),
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
    $("input-lock").hidden = false;
    $("input-lock").textContent = "Connection lost";
    document
      .querySelectorAll("[data-post], #cal, #type, #press")
      .forEach((b) => {
        b.disabled = true;
      });
  }
  setTimeout(poll, document.hidden ? 2500 : latest?.agent.running ? 500 : 1000);
}
applyLang();
applyMotion();
choosePanel("manual");
refreshLive();
poll();
