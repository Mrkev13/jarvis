// MRK-156: okno nastavení Jarvise pro PC. Jen vlastní příkazy aplikace přes window.__TAURI__.core.invoke;
// texty se vkládají přes textContent (žádné innerHTML s daty).
"use strict";

const invoke = (cmd, args) => window.__TAURI__.core.invoke(cmd, args);
const $ = (id) => document.getElementById(id);
let busy = false;

function show(el, on) { el.hidden = !on; }

function flash(text, ok = true) {
  const el = ok ? $("notice") : $("error");
  el.textContent = text;
  show(el, true);
  if (ok) setTimeout(() => show(el, false), 4000);
}

function statusOf(v) {
  if (!v.paired) return ["Nespárováno", "idle"];
  if (v.state.unauthorized) return ["Odvoláno v Hubu", "bad"];
  if (v.paused) return ["Pozastaveno", "idle"];
  if (v.state.connected) return ["Připojeno", "ok"];
  return ["Nepřipojeno", "bad"];
}

function powerLabel(p) {
  if (!p) return "";
  const [action, secs] = p;
  const label = { shutdown: "Vypnutí", sleep: "Uspání", lock: "Zamknutí" }[action] || action;
  return secs >= 60 ? `${label} za ${Math.ceil(secs / 60)} min` : `${label} za ${secs} s`;
}

function timeLabel(unix) {
  return new Date(unix * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
}

function renderApps(apps) {
  const ul = $("apps");
  ul.replaceChildren();
  if (!apps.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "Zatím žádné – klikni na Najít znovu nebo přidej ručně.";
    ul.append(li);
    return;
  }
  for (const a of apps) {
    const li = document.createElement("li");
    const meta = document.createElement("div");
    meta.className = "meta";
    const name = document.createElement("span");
    name.textContent = `${a.name}${a.detected ? " · nalezeno" : ""}`;
    const target = document.createElement("span");
    target.className = "muted";
    target.textContent = a.target;
    target.title = a.target;
    meta.append(name, target);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ghost";
    remove.textContent = "Odebrat";
    remove.setAttribute("aria-label", `Odebrat ${a.name}`);
    remove.addEventListener("click", () => act(() => invoke("remove_app", { id: a.id })));
    li.append(meta, remove);
    ul.append(li);
  }
}

function renderRecent(recent) {
  const ul = $("recent");
  ul.replaceChildren();
  if (!recent.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "Zatím nic.";
    ul.append(li);
    return;
  }
  for (const r of recent) {
    const li = document.createElement("li");
    const meta = document.createElement("div");
    meta.className = "meta";
    const head = document.createElement("span");
    head.textContent = `${timeLabel(r.at_unix)} · ${r.label}`;
    const msg = document.createElement("span");
    msg.className = r.ok ? "ok-text" : "bad-text";
    msg.textContent = r.message;
    meta.append(head, msg);
    li.append(meta);
    ul.append(li);
  }
}

async function refresh() {
  let v;
  try {
    v = await invoke("get_state");
  } catch (e) {
    flash(String(e), false);
    return;
  }
  const [text, cls] = statusOf(v);
  const pill = $("status");
  pill.textContent = text;
  pill.className = `pill ${cls}`;
  show($("pair-card"), !v.paired || v.state.unauthorized);
  show($("device-card"), v.paired && !v.state.unauthorized);
  if (v.paired) {
    $("device-name").textContent = v.device_name || "Počítač";
    $("device-hub").textContent = v.hub_url;
    $("pause").textContent = v.paused ? "Obnovit" : "Pozastavit";
    $("pause").dataset.paused = v.paused ? "1" : "";
  }
  if (!$("hub-url").value && v.hub_url) $("hub-url").value = v.hub_url;
  const err = v.paired && !v.paused ? v.state.last_error : null;
  if (v.state.unauthorized) {
    $("error").textContent = "Hub tohle zařízení odmítl (odvoláno?). Spáruj ho znovu novým kódem.";
    show($("error"), true);
  } else if (err) {
    $("error").textContent = err;
    show($("error"), true);
  } else {
    show($("error"), false);
  }
  show($("power"), !!v.state.pending_power);
  $("power-label").textContent = powerLabel(v.state.pending_power);
  $("autostart").checked = v.autostart;
  renderApps(v.apps);
  renderRecent(v.state.recent);
  $("version").textContent = `Verze ${v.version}`;
}

async function act(fn, ok) {
  if (busy) return;
  busy = true;
  try {
    const res = await fn();
    if (ok) flash(typeof ok === "function" ? ok(res) : ok);
  } catch (e) {
    flash(String(e), false);
  } finally {
    busy = false;
    refresh();
  }
}

$("pair-form").addEventListener("submit", (e) => {
  e.preventDefault();
  $("pair-submit").disabled = true;
  act(() => invoke("pair", { hubUrl: $("hub-url").value, code: $("code").value, name: $("name").value }), (msg) => msg)
    .finally(() => { $("pair-submit").disabled = false; $("code").value = ""; });
});

$("pause").addEventListener("click", () => act(() => invoke("set_paused", { paused: !$("pause").dataset.paused })));
$("unpair").addEventListener("click", () => {
  if (confirm("Odpárovat tenhle počítač? V Hubu ho pak ještě odvolej.")) act(() => invoke("unpair"), "Odpárováno.");
});
$("power-cancel").addEventListener("click", () => act(() => invoke("cancel_power"), "Časovač zrušen."));
$("detect").addEventListener("click", () => act(() => invoke("detect_apps"), (n) => `Nalezeno aplikací: ${n}`));
$("autostart").addEventListener("change", (e) => act(() => invoke("set_autostart", { enabled: e.target.checked })));
$("app-form").addEventListener("submit", (e) => {
  e.preventDefault();
  act(() => invoke("add_app", {
    name: $("app-name").value, target: $("app-target").value, args: $("app-args").value, process: $("app-process").value,
  }), "Aplikace přidána.").then(() => $("app-form").reset());
});

refresh();
setInterval(refresh, 2000);
