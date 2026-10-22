/* Shared UI helpers and widgets */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ICONS = {
  check: '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>',
  alert: '<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
  clock: '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z"/>',
  list: '<path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  pause: '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>',
  half: '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18V4a8 8 0 010 16z"/>',
  edit: '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>',
  trash: '<path d="M6 19a2 2 0 002 2h8a2 2 0 002-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>',
  eye: '<path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 110-10 5 5 0 010 10zm0-8a3 3 0 100 6 3 3 0 000-6z"/>',
  key: '<path d="M12.65 10A6 6 0 101 12a6 6 0 0011.65 2H17v4h4v-4h2v-4H12.65zM7 14a2 2 0 110-4 2 2 0 010 4z"/>',
  copy: '<path d="M16 1H4a2 2 0 00-2 2v14h2V3h12V1zm3 4H8a2 2 0 00-2 2v14a2 2 0 002 2h11a2 2 0 002-2V7a2 2 0 00-2-2zm0 16H8V7h11v14z"/>',
  users: '<path d="M16 11a3 3 0 100-6 3 3 0 000 6zm-8 0a3 3 0 100-6 3 3 0 000 6zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.33 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
  shield: '<path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/>',
  lock: '<path d="M18 8h-1V6a5 5 0 00-10 0v2H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V10a2 2 0 00-2-2zm-6 9a2 2 0 110-4 2 2 0 010 4zm3.1-9H8.9V6a3.1 3.1 0 016.2 0v2z"/>',
  up: '<path d="M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z"/>',
  close: '<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>',
  sparkle: '<path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z"/>',
  bolt: '<path d="M7 2v11h3v9l7-12h-4l4-8z"/>',
  recycle: '<path d="M12 6v3l4-4-4-4v3a8 8 0 00-6.76 12.26l1.46-1.46A6 6 0 0112 6zm6.76 1.74L17.3 9.2A6 6 0 0112 18v-3l-4 4 4 4v-3a8 8 0 006.76-12.26z"/>',
  log: '<path d="M13 3a9 9 0 00-9 9H1l3.9 3.9.1.1L9 12H6a7 7 0 112.05 4.95l-1.42 1.42A9 9 0 1013 3zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/>',
  tasks: '<path d="M9 11l3 3L22 4l-1.4-1.4L12 11.2 10.4 9.6 9 11zM20 12v7a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1h9V2H5a3 3 0 00-3 3v14a3 3 0 003 3h14a3 3 0 003-3v-7h-2z"/>',
  bell: '<path d="M12 22a2 2 0 002-2h-4a2 2 0 002 2zm6-6V11c0-3.07-1.64-5.64-4.5-6.32V4a1.5 1.5 0 00-3 0v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>',
  sun: '<path d="M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5a6 6 0 100 12 6 6 0 000-12zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z"/>',
  moon: '<path d="M12 3a9 9 0 109 9c0-.46-.04-.92-.1-1.36a5.39 5.39 0 01-4.4 2.26 5.4 5.4 0 01-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>',
  refresh: '<path d="M17.65 6.35A7.96 7.96 0 0012 4a8 8 0 108 8h-2a6 6 0 11-1.76-4.24L13 11h7V4l-2.35 2.35z"/>',
  chart: '<path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/>',
};
const icon = (name, cls = "") => `<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

/* ---------- Permissions ---------- */
let ME = null;
const can = (...p) => !!ME && p.every((x) => ME.permissions.includes(x));
const canAny = (...p) => !!ME && p.some((x) => ME.permissions.includes(x));

/* ---------- Badges & small components ---------- */
const STATUS_CLASS = { "Not Started": "st-notstarted", "In Progress": "st-progress", "Partially Completed": "st-partial", "On Hold": "st-hold", "Completed": "st-done" };
const statusBadge = (s) => `<span class="badge ${STATUS_CLASS[s] || ""}">${esc(s)}</span>`;
const priorityBadge = (p) => `<span class="badge pr-${esc(String(p).toLowerCase())}">${esc(p)}</span>`;
function roleBadge(name) {
  const palette = ["rb-a", "rb-b", "rb-c", "rb-d", "rb-e", "rb-f"];
  const cls = name === "Admin" ? "rb-admin" : name === "Agent" ? "rb-agent" : palette[[...String(name)].reduce((a, c) => a + c.charCodeAt(0), 0) % palette.length];
  return `<span class="badge ${cls}">${name === "Admin" ? icon("shield") : ""}${esc(name)}</span>`;
}
function progressBar(pct, status) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  const cls = status === "Completed" ? "done" : status === "On Hold" ? "hold" : "";
  return `<div class="progress ${cls}" title="${p}%"><span style="--w:${p}%"></span></div>`;
}
function timeChip(t) {
  if (t.status === "Completed") return `<span class="time-chip ok">${icon("check")} Completed</span>`;
  const left = t.remaining_human ?? t.time_left, secs = t.remaining_seconds, overdue = t.is_overdue ?? t.overdue;
  const cls = overdue ? "bad" : secs !== undefined && secs !== null && secs < 86400 ? "warn" : "";
  return `<span class="time-chip ${cls}">${icon(overdue ? "alert" : "clock")} ${esc(left)}</span>`;
}
function statCard(label, value, iconName, tone, sub = "", go = "") {
  return `<button type="button" class="stat-card tone-${tone} ${go ? "clickable" : ""}" ${go ? `data-go="${esc(go)}"` : "disabled"}>
    <div class="stat-icon">${icon(iconName)}</div>
    <div class="stat-body"><div class="stat-value" data-count="${Number(value) || 0}">0</div><div class="stat-label">${esc(label)}</div>
    ${sub ? `<div class="stat-sub">${esc(sub)}</div>` : ""}</div>${go ? `<span class="stat-go">→</span>` : ""}</button>`;
}
function countUp(root = document) {
  $$("[data-count]", root).forEach((el) => {
    const target = Number(el.dataset.count), start = performance.now();
    const step = (now) => { const k = Math.min(1, (now - start) / 650); el.textContent = Math.round(target * (1 - Math.pow(1 - k, 3))).toLocaleString(); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });
}
function donut(pct, label = "Completion") {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="donut" style="--p:${p}"><div class="donut-inner"><b>${p}%</b><small>${esc(label)}</small></div></div>`;
}
const emptyState = (text, iconName = "tasks") => `<div class="empty">${icon(iconName)}<p>${esc(text)}</p></div>`;
const initials = (name) => String(name || "?").replace(/\(removed\)/, "").trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

/* ---------- Dashboard widgets ---------- */
function trendChart(trend) {
  const max = Math.max(1, ...trend.map((d) => d.count));
  return `<div class="bar-chart">${trend.map((d, i) => `<div class="bc-col" title="${esc(d.date)}: ${d.count} completed"><span class="bc-val">${d.count || ""}</span>
      <div class="bc-bar ${i === trend.length - 1 ? "today" : ""}" style="--h:${Math.max(4, (d.count / max) * 100)}%; --i:${i}"></div>
      <span class="bc-lbl">${esc(i === trend.length - 1 ? "Today" : d.day)}</span></div>`).join("")}</div>`;
}
function calendarStrip(cal) {
  return `<div class="cal-strip">${cal.map((d, i) => `<div class="cal-day ${i === 0 ? "today" : ""} ${d.count ? "has" : ""} ${d.critical ? "hot" : ""}" title="${esc(d.titles.join("\n") || "Nothing due")}">
      <span class="cal-dow">${esc(i === 0 ? "Today" : d.day)}</span><b>${esc(d.date)}</b><span class="cal-mon">${esc(d.month)}</span>
      <span class="cal-count">${d.count ? `${d.count} due` : "—"}</span></div>`).join("")}</div>`;
}
function priorityMix(mix) {
  const total = Object.values(mix).reduce((a, b) => a + b, 0) || 1;
  return `<div class="mix">${Object.entries(mix).reverse().map(([p, n]) => `<div class="mix-row"><span class="mix-lbl">${priorityBadge(p)}</span>
      <div class="mix-track"><span class="mix-fill pf-${p.toLowerCase()}" style="--w:${(n / total) * 100}%"></span></div><b>${n}</b></div>`).join("")}</div>`;
}
function attentionList(items, showAgent) {
  if (!items.length) return emptyState("Nothing needs attention right now 🎉", "check");
  const cls = { overdue: "bad", "due in 24h": "warn", "on hold": "hold" };
  return `<div class="attn">${items.map((t) => `<div class="attn-item" data-task="${t.id}"><span class="attn-tag ${cls[t.reason] || ""}">${esc(t.reason)}</span>
      <div class="attn-body"><b>${esc(t.title)}</b><small>${showAgent ? esc(t.agent) + " · " : ""}${esc(t.time_left)}</small></div>${priorityBadge(t.priority)}</div>`).join("")}</div>`;
}
function aiStatsCard(s) {
  return `<div class="ai-stats"><div class="ai-ring" style="--p:${s.free_pct}"><div><b>${s.free_pct}%</b><small>0-token</small></div></div>
    <div class="ai-nums"><div><span>${icon("bolt")} Instant answers</span><b>${s.instant}</b></div><div><span>${icon("recycle")} From cache</span><b>${s.cache}</b></div>
      <div><span>${icon("sparkle")} AI calls</span><b>${s.llm}</b></div><div><span>${icon("chart")} Tokens used</span><b>${(s.prompt_tokens + s.completion_tokens).toLocaleString()}</b></div>
      <div class="good"><span>${icon("check")} Tokens saved (est.)</span><b>~${s.tokens_saved_est.toLocaleString()}</b></div></div></div>
    <p class="muted small">Last ${s.days} days · ${s.questions} questions · ${s.cached_prompt_tokens.toLocaleString()} prompt tokens served from Groq's prefix cache</p>`;
}

/* ---------- Toasts / modal ---------- */
function toast(msg, type = "info") {
  let box = $("#toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === "error" ? "alert" : type === "info" ? "bell" : "check")}<span>${esc(msg)}</span>`;
  el.addEventListener("click", () => el.remove());
  box.appendChild(el);
  setTimeout(() => el.classList.add("hide"), 3600); setTimeout(() => el.remove(), 4100);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard", "success"); } catch { toast("Copy failed - please copy manually", "error"); }
}
function openModal({ title, body, submitText = "Save", onSubmit, wide = false, hideFooter = false, danger = false }) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.id = "modal"; wrap.className = "modal-backdrop";
  wrap.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
      <div class="modal-head"><h3>${esc(title)}</h3><button class="icon-btn" type="button" data-close aria-label="Close">${icon("close")}</button></div>
      <form class="modal-body" novalidate>${body}<div class="form-error" hidden></div>
        ${hideFooter ? "" : `<div class="modal-foot"><button type="button" class="btn ghost" data-close>Cancel</button>
        <button type="submit" class="btn ${danger ? "danger" : "primary"}">${esc(submitText)}</button></div>`}</form></div>`;
  document.body.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("show"));
  $$("[data-close]", wrap).forEach((b) => b.addEventListener("click", closeModal));
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) closeModal(); });
  const form = $("form", wrap);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!onSubmit) return closeModal();
    const btn = $("button[type=submit]", form), err = $(".form-error", form);
    err.hidden = true; btn.disabled = true; btn.classList.add("loading");
    try { const keepOpen = await onSubmit(form); if (keepOpen !== true) closeModal(); }
    catch (ex) { err.textContent = ex.message; err.hidden = false; }
    finally { btn.disabled = false; btn.classList.remove("loading"); }
  });
  const first = $("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select, textarea", form);
  if (first) setTimeout(() => first.focus(), 60);
  return wrap;
}
function closeModal() { const m = $("#modal"); if (m) m.remove(); }
function confirmDialog(title, message, confirmText = "Confirm", danger = true) {
  return new Promise((resolve) => {
    let done = false;
    openModal({ title, danger, body: `<p class="confirm-text">${esc(message)}</p>`, submitText: confirmText, onSubmit: async () => { done = true; resolve(true); } });
    $$("#modal [data-close]").forEach((b) => b.addEventListener("click", () => { if (!done) resolve(false); }));
  });
}
function credentialsHTML(n) {
  return `<div class="cred-card"><div class="cred-head">${icon("key")}<b>${esc(n.title)}</b></div>
    <div class="cred-row"><span>Username</span><code>${esc(n.username)}</code><button type="button" class="icon-btn sm" data-copy="${esc(n.username)}" title="Copy">${icon("copy")}</button></div>
    <div class="cred-row"><span>Password</span><code>${esc(n.password)}</code><button type="button" class="icon-btn sm" data-copy="${esc(n.password)}" title="Copy">${icon("copy")}</button></div>
    <div class="cred-note">Share these securely. The password is shown only once and is not stored in chat.</div></div>`;
}
function bindCopy(root) { $$("[data-copy]", root).forEach((b) => b.addEventListener("click", () => copyText(b.dataset.copy))); }
function showCredentials(n) { openModal({ title: "Login details", hideFooter: true, body: credentialsHTML(n) }); bindCopy($("#modal")); }

/* ---------- Task preview (page adds buttons via window.TaskPreviewActions) ---------- */
async function showTaskDetail(taskId) {
  let data;
  try { data = await api(`/api/tasks/${taskId}`); }
  catch (e) { toast(e.status === 404 ? "This task no longer exists or you can't see it." : e.message, "error"); return; }
  const { task: t, history } = data;
  const hist = history.map((h) => `<li><div class="tl-dot"></div><div><div class="tl-head"><b>${esc(h.by_name)}</b> · ${esc(h.created_local)}</div>
      <div class="tl-body">${h.status ? statusBadge(h.status) : ""} ${h.progress !== null && h.progress !== undefined ? `<span class="muted">${h.progress}%</span>` : ""}
      ${h.note ? `<div class="tl-note">${esc(h.note)}</div>` : ""}</div></div></li>`).join("");
  const actions = (window.TaskPreviewActions ? window.TaskPreviewActions(t) : []) || [];
  openModal({
    title: `Task #${t.id}`, wide: true, hideFooter: true,
    body: `<div class="detail"><div class="detail-top"><h2>${esc(t.title)}</h2><div class="detail-badges">${priorityBadge(t.priority)}${statusBadge(t.status)}</div></div>
      <p class="muted">${esc(t.description || "No description")}</p>
      <div class="detail-grid"><div><label>Assigned to</label><div class="agent-chip"><span class="avatar sm">${initials(t.agent_name)}</span>${esc(t.agent_name)}</div></div>
        <div><label>Deadline</label><div>${esc(t.deadline_local)}</div></div><div><label>Time left</label>${timeChip(t)}</div>
        <div><label>Estimated effort</label><div>${t.estimated_hours ? esc(t.estimated_hours) + " h" : "—"}</div></div></div>
      <div class="detail-progress"><label>Progress — ${t.progress}%</label>${progressBar(t.progress, t.status)}</div>
      ${actions.length ? `<div class="detail-actions">${actions.map((a, i) => `<button type="button" class="btn ${a.primary ? "primary" : "ghost"} sm" data-pa="${i}">${a.icon ? icon(a.icon) : ""}${esc(a.label)}</button>`).join("")}</div>` : ""}
      <h4 class="section-title">Activity</h4><ul class="timeline">${hist || "<li>No activity yet</li>"}</ul></div>`,
  });
  $$("#modal [data-pa]").forEach((b) => b.addEventListener("click", () => { const a = actions[+b.dataset.pa]; closeModal(); a.onClick(t); }));
}

/* ---------- Navigation & header ---------- */
function initNav(onChange) {
  const links = $$(".nav-link[data-view]").filter((l) => !l.hidden);
  const show = (view) => {
    if (!links.some((l) => l.dataset.view === view)) view = links[0]?.dataset.view;
    links.forEach((l) => l.classList.toggle("active", l.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    $("#page-title").textContent = links.find((l) => l.dataset.view === view)?.dataset.title || "";
    document.body.classList.remove("nav-open");
    history.replaceState(null, "", `#${view}`);
    onChange && onChange(view);
  };
  links.forEach((l) => l.addEventListener("click", (e) => { e.preventDefault(); show(l.dataset.view); }));
  $("#menu-btn")?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
  show(location.hash.slice(1));
  return show;
}
function themeIcon() { return icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon"); }
function initHeader(me, { onShortcut } = {}) {
  $("#user-name").textContent = me.display_name;
  $("#user-role").textContent = me.role;
  $("#user-avatar").textContent = initials(me.display_name);
  $("#role-pill").textContent = me.role;
  $("#today").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#logout-btn").addEventListener("click", logout);
  const tbtn = $("#theme-btn");
  tbtn.innerHTML = themeIcon();
  tbtn.addEventListener("click", () => { toggleTheme(); tbtn.innerHTML = themeIcon(); });
  const bell = $("#bell-btn"), panel = $("#notif-panel");
  bell.addEventListener("click", (e) => { e.stopPropagation(); panel.classList.toggle("open"); });
  document.addEventListener("click", (e) => { if (!panel.contains(e.target)) panel.classList.remove("open"); });
  $("#mark-read").addEventListener("click", async (e) => { e.stopPropagation(); await api("/api/notifications/read-all", { method: "POST" }); loadNotifications(); });
  loadNotifications(); setInterval(loadNotifications, 30000);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeModal(); panel.classList.remove("open"); return; }
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); onShortcut && onShortcut("ai"); return; }
    if (typing || $("#modal")) return;
    if (e.key === "/") { e.preventDefault(); onShortcut && onShortcut("search"); }
    else if (e.key.toLowerCase() === "n") onShortcut && onShortcut("new");
    else if (e.key.toLowerCase() === "t") { toggleTheme(); tbtn.innerHTML = themeIcon(); }
  });
}
const NOTIF_ICON = { assigned: ["tasks", "blue"], overdue: ["alert", "red"], deadline_approaching: ["clock", "amber"], completed: ["check", "green"],
  priority_changed: ["up", "orange"], deadline_changed: ["clock", "blue"], reassigned: ["refresh", "purple"], status_changed: ["play", "blue"],
  on_hold: ["pause", "purple"], task_removed: ["trash", "red"], role_changed: ["shield", "purple"], profile_changed: ["users", "slate"] };
let _lastUnread = null;
async function loadNotifications() {
  try {
    const { unread, items } = await api("/api/notifications");
    const badge = $("#bell-count");
    badge.textContent = unread > 99 ? "99+" : unread; badge.hidden = !unread;
    if (_lastUnread !== null && unread > _lastUnread && items[0]) { toast(items[0].message, "info"); $("#bell-btn").classList.add("ring"); setTimeout(() => $("#bell-btn").classList.remove("ring"), 1200); }
    _lastUnread = unread;
    $("#notif-sub").textContent = unread ? `${unread} unread` : "All caught up";
    $("#notif-list").innerHTML = items.length ? items.map((n) => {
      const [ic, tone] = NOTIF_ICON[n.type] || ["bell", "slate"];
      return `<div class="notif ${n.is_read ? "" : "unread"} ${n.task_id ? "clickable" : ""}" data-id="${n.id}" data-task="${n.task_id || ""}" tabindex="0">
        <div class="notif-ico tone-${tone}">${icon(ic)}</div><div class="notif-body"><div class="notif-msg">${esc(n.message)}</div>
        <div class="notif-time">${esc(n.created_local)}${n.task_id ? ' · <span class="notif-link">View task →</span>' : ""}</div></div></div>`;
    }).join("") : `<div class="notif-empty">${icon("bell")}<p>You're all caught up 🎉</p></div>`;
    $$("#notif-list .notif").forEach((el) => {
      const open = async () => {
        if (el.classList.contains("unread")) { api(`/api/notifications/${el.dataset.id}/read`, { method: "POST" }).then(loadNotifications).catch(() => {}); el.classList.remove("unread"); }
        if (el.dataset.task) { $("#notif-panel").classList.remove("open"); await showTaskDetail(el.dataset.task); }
      };
      el.addEventListener("click", open); el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  } catch { /* silent */ }
}

/* ---------- AI chat ---------- */
function sourceTag(source, tokens) {
  if (source === "instant") return `<span class="src src-instant" title="Answered from the database - no AI tokens">${icon("bolt")}Instant · 0 tokens</span>`;
  if (source === "cache") return `<span class="src src-cache" title="Same question, same data">${icon("recycle")}Cached · 0 tokens${tokens?.saved ? ` (saved ~${tokens.saved})` : ""}</span>`;
  if (source === "ai" && tokens) {
    const total = (tokens.prompt || 0) + (tokens.completion || 0);
    return `<span class="src src-ai">${icon("sparkle")}AI · ${total.toLocaleString()} tokens${tokens.cached ? ` (${tokens.cached} cached)` : ""}</span>`;
  }
  return "";
}
function initChat({ suggestions, greeting: greet, onDataChanged }) {
  const log = $("#chat-log"), input = $("#chat-input"), sendBtn = $("#chat-send");
  let busy = false;
  const LABEL = { done: "Done", cancelled: "Cancelled", expired: "Expired", failed: "Failed" };
  const actionCardHTML = (a) => {
    const pending = a.status === "pending";
    return `<div class="action-card st-${esc(a.status)}" data-action="${esc(a.id)}">
      <div class="action-head">${icon(pending ? "alert" : a.status === "done" ? "check" : "close")}<b>${pending ? "Confirmation needed" : esc(LABEL[a.status] || a.status)}</b></div>
      <div class="action-summary">${esc(a.summary)}</div>${a.result && !pending ? `<div class="action-result">${esc(a.result)}</div>` : ""}
      ${pending ? `<div class="action-btns"><button type="button" class="btn ghost sm" data-act="cancel">Cancel</button><button type="button" class="btn danger sm" data-act="confirm">Confirm</button></div>` : ""}</div>`;
  };
  const bindActionCards = (root) => $$(".action-card", root).forEach((card) => $$("[data-act]", card).forEach((btn) => btn.addEventListener("click", async () => {
    $$("button", card).forEach((b) => (b.disabled = true)); btn.classList.add("loading");
    try {
      const res = await api(`/api/ai/actions/${card.dataset.action}/${btn.dataset.act}`, { method: "POST" });
      card.outerHTML = actionCardHTML(res);
      if (res.status === "done") { toast(res.result, "success"); onDataChanged && onDataChanged(); } else if (res.status === "failed") toast(res.result, "error");
    } catch (e) { toast(e.message, "error"); $$("button", card).forEach((b) => (b.disabled = false)); btn.classList.remove("loading"); }
  })));
  const bubble = (role, content, { time = "", actions = [], notices = [], source = "", tokens = null } = {}) => {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    const body = role === "assistant" ? `<div class="md">${renderMarkdown(content)}</div>` : `<div class="user-text">${esc(content)}</div>`;
    const extras = notices.map(credentialsHTML).join("") + actions.map(actionCardHTML).join("");
    el.innerHTML = `<div class="msg-avatar">${role === "assistant" ? icon("sparkle") : initials(ME?.display_name)}</div>` +
      `<div class="msg-bubble">${body}${extras ? `<div class="msg-extras">${extras}</div>` : ""}` +
      `<div class="msg-meta">${role === "assistant" ? sourceTag(source, tokens) : ""}${time ? `<span>${esc(time)}</span>` : ""}` +
      `${role === "assistant" && content ? `<button type="button" class="msg-copy" title="Copy">${icon("copy")}</button>` : ""}</div></div>`;
    log.appendChild(el); bindActionCards(el); bindCopy(el);
    $(".msg-copy", el)?.addEventListener("click", () => copyText(content));
    log.scrollTop = log.scrollHeight;
    return el;
  };
  const welcome = () => {
    log.innerHTML = `<div class="chat-welcome">${icon("sparkle")}<h3>${esc(greet.title)}</h3><p>${esc(greet.text)}</p>
      <div class="legend-src"><span class="src src-instant">${icon("bolt")}Instant</span> common questions, 0 tokens
      <span class="src src-cache">${icon("recycle")}Cached</span> repeated questions, 0 tokens</div>
      <p class="kbd-hint"><kbd>Ctrl</kbd> + <kbd>K</kbd> opens the assistant from anywhere</p></div>`;
  };
  $("#chat-suggestions").innerHTML = suggestions.map((s) => `<button class="chip" type="button">${esc(s)}</button>`).join("");
  $$("#chat-suggestions .chip").forEach((c) => c.addEventListener("click", () => { input.value = c.textContent; send(); }));
  async function loadHistory() {
    try {
      const hist = await api("/api/ai/history");
      if (!hist.length) return welcome();
      log.innerHTML = "";
      hist.forEach((m) => bubble(m.role, m.content, { time: m.time, actions: m.actions || [], source: m.source, tokens: m.tokens }));
    } catch { welcome(); }
  }
  function rateLimitBubble(text, seconds) {
    const el = bubble("assistant", ""); el.classList.add("warn");
    const md = $(".md", el); let left = seconds;
    const render = () => {
      md.innerHTML = left > 0 ? `<p class="rl-line">${icon("clock")} The AI is busy (rate limit). You can retry in <b>${left}s</b>.</p>`
        : `<p class="rl-line">${icon("check")} Ready. <button type="button" class="btn primary sm retry-btn">${icon("refresh")}Retry now</button></p>`;
      $(".retry-btn", md)?.addEventListener("click", () => { el.remove(); input.value = text; send(); });
    };
    render();
    const t = setInterval(() => { left--; render(); if (left <= 0) clearInterval(t); }, 1000);
  }
  async function send() {
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    $(".chat-welcome", log)?.remove();
    input.value = ""; autoGrow();
    bubble("user", text);
    const typing = bubble("assistant", "");
    $(".md", typing).innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
    try {
      const res = await api("/api/ai/chat", { method: "POST", body: { message: text } });
      typing.remove();
      bubble("assistant", res.answer, { actions: res.actions || [], notices: res.notices || [], source: res.source, tokens: res.tokens });
      if (res.changed && onDataChanged) onDataChanged();
    } catch (e) {
      typing.remove();
      if (e.status === 429 && e.retryAfter) rateLimitBubble(text, e.retryAfter);
      else { const el = bubble("assistant", ""); el.classList.add("error"); $(".md", el).innerHTML = `<p>⚠️ ${esc(e.message)}</p>`; }
    } finally { busy = false; sendBtn.disabled = false; input.focus(); log.scrollTop = log.scrollHeight; }
  }
  const autoGrow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; };
  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  sendBtn.addEventListener("click", send);
  $("#chat-clear").addEventListener("click", async () => {
    if (!(await confirmDialog("Clear chat", "Delete your conversation history with the assistant?", "Clear"))) return;
    await api("/api/ai/history", { method: "DELETE" }); welcome(); toast("Chat cleared", "success");
  });
  loadHistory();
  return { ask: (q) => { input.value = q; send(); }, focus: () => input.focus() };
}
