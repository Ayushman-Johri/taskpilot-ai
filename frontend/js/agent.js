/* Agent workspace: dashboard, own tasks (view + update status/progress/note only), private AI bot.
   No create / assign / edit / delete controls - the backend rejects those calls anyway. */
(async function () {
  const me = await guardPage("agent").catch(() => null);
  if (!me) return;

  let META = { statuses: [], priorities: [] }, filter = "pending", TASKS = [];
  initHeader(me, { onShortcut: (k) => {
    if (k === "ai") { navigate("assistant"); chat.focus(); }
    if (k === "search") { navigate("tasks"); $("#f-search").focus(); }
    if (k === "new") { const top = $("#focus-list [data-update]"); top ? openUpdateById(+top.dataset.update) : toast("No pending tasks 🎉", "success"); }
  } });
  META = await api("/api/tasks/meta");
  window.TaskPreviewActions = (t) => t.status === "Completed" ? [] : [{ label: "Update progress", icon: "edit", primary: true, onClick: () => openUpdate(t) }];
  $("#hello").textContent = `${greeting()}, ${me.display_name} 👋`;

  /* ------------------------- Dashboard ------------------------- */
  async function loadDashboard() {
    const d = await api("/api/dashboard/agent"), c = d.counts, ins = d.insights;
    const today = ins.calendar[0]?.count || 0;
    $("#hello-sub").textContent = c.total === 0 ? "No tasks are assigned to you yet."
      : c.pending ? `You have ${c.pending} pending task${c.pending > 1 ? "s" : ""}${today ? `, ${today} due today` : ""}. Let's get going!`
      : "All your tasks are completed. Great job! 🎉";
    $("#hero-pills").innerHTML = [
      c.overdue ? `<span class="hp bad">${icon("alert")}${c.overdue} overdue</span>` : `<span class="hp ok">${icon("check")}Nothing overdue</span>`,
      `<span class="hp">${icon("check")}${ins.week_completed} done this week</span>`,
      `<span class="hp">${icon("chart")}${c.avg_progress_pct}% avg progress</span>`,
    ].join("");
    $("#agent-stats").innerHTML = [
      statCard("Assigned to me", c.total, "list", "indigo", `${c.pending} pending`, "all"),
      statCard("Completed", c.completed, "check", "green", `${ins.week_completed} this week`, "completed"),
      statCard("In progress", c.in_progress, "play", "blue", "", "pending"),
      statCard("Partially done", c.partially_completed, "half", "amber", "", "pending"),
      statCard("Not started", c.not_started, "pause", "slate", c.on_hold ? `${c.on_hold} on hold` : "", "pending"),
      statCard("Overdue", c.overdue, "alert", "red", c.overdue ? "act now" : "all on track", "overdue"),
    ].join("");
    countUp($("#agent-stats"));
    $$("#agent-stats [data-go]").forEach((b) => b.addEventListener("click", () => { setTab(b.dataset.go); navigate("tasks"); }));
    $("#focus-list").innerHTML = d.top_priorities.length ? d.top_priorities.map((t, i) => `
      <div class="focus-item pop-in" data-task="${t.id}" style="--i:${i}"><div class="rank">${t.rank}</div>
        <div class="focus-body"><div class="focus-title"><b>${esc(t.title)}</b>${priorityBadge(t.priority)}</div>
          <div class="focus-meta">${statusBadge(t.status)} ${timeChip({ ...t, remaining_human: t.time_left, is_overdue: t.overdue })}</div>
          <div class="mini-prog">${progressBar(t.progress, t.status)}<span>${t.progress}%</span></div>
          <div class="focus-why">${t.reasons.map((r) => `<span>${esc(r)}</span>`).join("")}</div></div>
        <button class="btn sm primary" data-update="${t.id}">Update</button></div>`).join("") : emptyState("No pending tasks — you're all done! 🎉", "check");
    $("#my-progress").innerHTML = `${donut(c.completion_rate_pct, "Completed")}
      <div class="tp-legend"><div><span class="dot green"></span>Completed <b>${c.completed}</b></div><div><span class="dot blue"></span>In progress <b>${c.in_progress}</b></div>
        <div><span class="dot amber"></span>Partial <b>${c.partially_completed}</b></div><div><span class="dot purple"></span>On hold <b>${c.on_hold}</b></div>
        <div><span class="dot slate"></span>Not started <b>${c.not_started}</b></div></div>`;
    $("#week-done").textContent = `${ins.week_completed} done`;
    $("#trend").innerHTML = trendChart(ins.trend);
    $("#calendar").innerHTML = calendarStrip(ins.calendar);
    $("#attention").innerHTML = attentionList(ins.attention, false);
    $$("#view-dashboard [data-update]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openUpdateById(+b.dataset.update); }));
    $$("#view-dashboard [data-task]").forEach((el) => el.addEventListener("click", () => showTaskDetail(el.dataset.task)));
  }

  /* ------------------------- My tasks ------------------------- */
  function setTab(f) { filter = f; $$("#task-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.filter === f)); }
  async function loadTasks() {
    const qs = new URLSearchParams(), q = $("#f-search").value.trim();
    if (q) qs.set("q", q);
    if (filter === "pending") qs.set("pending_only", "true");
    if (filter === "overdue") qs.set("overdue_only", "true");
    if (filter === "completed") qs.set("status", "Completed");
    TASKS = await api("/api/tasks?" + qs);
    const grid = $("#task-grid");
    if (!TASKS.length) { grid.innerHTML = emptyState(filter === "overdue" ? "No overdue tasks 🎉" : filter === "completed" ? "No completed tasks yet" : "No tasks here", "tasks"); return; }
    grid.innerHTML = TASKS.map((t, i) => `
      <article class="task-card pop-in ${t.is_overdue ? "overdue" : ""} ${t.status === "Completed" ? "is-done" : ""}" style="--i:${Math.min(i, 12)}" data-card="${t.id}">
        <div class="tc-top">${priorityBadge(t.priority)}
          <div class="status-menu"><button type="button" class="status-trigger" data-menu="${t.id}" ${t.status === "Completed" ? "disabled" : ""}>${statusBadge(t.status)}${t.status === "Completed" ? "" : '<span class="caret">▾</span>'}</button>
            <div class="status-pop" id="pop-${t.id}">${META.statuses.filter((s) => s !== t.status).map((s) => `<button type="button" data-quick="${t.id}" data-status="${esc(s)}">${statusBadge(s)}</button>`).join("")}</div></div></div>
        <h3>${esc(t.title)}</h3><p class="tc-desc">${esc(t.description || "No description")}</p>
        <div class="tc-progress"><div class="tc-progress-head"><span>Progress</span><b>${t.progress}%</b></div>${progressBar(t.progress, t.status)}</div>
        <div class="tc-meta"><div><small>Deadline</small><span>${esc(t.deadline_local)}</span></div><div>${timeChip(t)}</div></div>
        <div class="tc-actions">
          <button class="btn ghost sm" data-act="view" data-id="${t.id}">${icon("eye")}Details</button>
          ${t.status === "Not Started" ? `<button class="btn ghost sm" data-act="start" data-id="${t.id}">${icon("play")}Start</button>` : ""}
          ${t.status !== "Completed" ? `<button class="btn ghost sm success" data-act="done" data-id="${t.id}">${icon("check")}Done</button><button class="btn primary sm" data-act="update" data-id="${t.id}">${icon("edit")}Update</button>` : ""}
        </div></article>`).join("");
    $$("#task-grid [data-act]").forEach((b) => b.addEventListener("click", async () => {
      const t = TASKS.find((x) => x.id === +b.dataset.id);
      try {
        if (b.dataset.act === "view") await showTaskDetail(t.id);
        if (b.dataset.act === "update") openUpdate(t);
        if (b.dataset.act === "start") await saveProgress(t.id, { status: "In Progress", progress: Math.max(t.progress, 10) }, "Task started 🚀");
        if (b.dataset.act === "done" && await confirmDialog("Mark as completed", `Mark "${t.title}" as completed?`, "Mark completed", false)) await saveProgress(t.id, { status: "Completed" }, "Great job! Task completed 🎉", t.id);
      } catch (e) { toast(e.message, "error"); }
    }));
    $$("#task-grid [data-menu]").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const pop = $(`#pop-${b.dataset.menu}`), open = pop.classList.contains("open");
      $$(".status-pop.open").forEach((p) => p.classList.remove("open")); if (!open) pop.classList.add("open");
    }));
    $$("#task-grid [data-quick]").forEach((b) => b.addEventListener("click", async () => {
      const t = TASKS.find((x) => x.id === +b.dataset.quick), s = b.dataset.status;
      if (s === "Partially Completed") return openUpdate({ ...t, status: s });
      try { await saveProgress(t.id, { status: s }, s === "Completed" ? "Great job! Task completed 🎉" : `Moved to ${s}`, s === "Completed" ? t.id : null); } catch (e) { toast(e.message, "error"); }
    }));
  }
  document.addEventListener("click", () => $$(".status-pop.open").forEach((p) => p.classList.remove("open")));
  async function saveProgress(id, body, msg, celebrateId = null) {
    await api(`/api/tasks/${id}/progress`, { method: "PATCH", body });
    if (celebrateId) { const card = $(`[data-card="${celebrateId}"]`); card && card.classList.add("celebrate"); await new Promise((r) => setTimeout(r, 450)); }
    toast(msg || "Task updated", "success"); refreshAll();
  }
  async function openUpdateById(id) { try { const { task } = await api(`/api/tasks/${id}`); openUpdate(task); } catch (e) { toast(e.message, "error"); } }
  const HELP = { "Not Started": "Haven't begun yet", "In Progress": "Actively working on it", "Partially Completed": "Part of the work is done", "On Hold": "Blocked / waiting on something", "Completed": "All work is finished" };
  function openUpdate(t) {
    openModal({
      title: "Update task progress", submitText: "Save update",
      body: `<div class="upd-head"><b>${esc(t.title)}</b><div>${priorityBadge(t.priority)} ${timeChip(t)}</div></div>
        <label>Status</label><div class="status-options">${META.statuses.map((s) => `<label class="status-opt"><input type="radio" name="status" value="${esc(s)}" ${s === t.status ? "checked" : ""}><span>${statusBadge(s)}<small>${esc(HELP[s] || "")}</small></span></label>`).join("")}</div>
        <label>Progress: <b id="pv">${t.progress}%</b></label><input type="range" name="progress" min="0" max="100" step="5" value="${t.progress}" class="range">
        <div class="range-marks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><div class="hint" id="p-hint"></div>
        <label>Note / comment <span class="muted small">(optional)</span></label><textarea name="note" rows="3" maxlength="1000" placeholder="e.g. Completed data collection, report formatting pending"></textarea>`,
      onSubmit: async (form) => {
        const status = form.querySelector("input[name=status]:checked")?.value;
        if (!status) throw new Error("Please choose a status.");
        const progress = Number(form.progress.value), note = form.note.value.trim();
        if (status === "Partially Completed" && (progress < 1 || progress > 99)) throw new Error("For Partially Completed, progress must be between 1% and 99%.");
        await saveProgress(t.id, { status, progress, note }, status === "Completed" ? "Great job! Task completed 🎉" : "Progress saved");
      },
    });
    const form = $("#modal form"), range = form.progress, pv = $("#pv"), hint = $("#p-hint");
    const paint = () => range.style.setProperty("--val", range.value + "%");
    const sync = (fromStatus) => {
      const status = form.querySelector("input[name=status]:checked")?.value;
      let v = Number(range.value); range.disabled = false; hint.textContent = "";
      if (status === "Completed") { v = 100; range.disabled = true; hint.textContent = "Completed tasks are always 100%."; }
      else if (status === "Not Started") { v = 0; range.disabled = true; hint.textContent = "Not started tasks are 0%."; }
      else { if (v >= 100) v = 95; if (status === "Partially Completed" && v < 5) v = fromStatus ? 50 : Math.max(v, 5); if (status === "Partially Completed") hint.textContent = "Drag to show how much is done."; }
      range.value = v; pv.textContent = v + "%"; paint();
    };
    $$("input[name=status]", form).forEach((r) => r.addEventListener("change", () => sync(true)));
    range.addEventListener("input", () => {
      pv.textContent = range.value + "%"; paint();
      const checked = form.querySelector("input[name=status]:checked");
      if (checked && checked.value === "Not Started" && +range.value > 0) form.querySelector('input[name=status][value="In Progress"]').checked = true;
    });
    sync(false);
  }

  /* ------------------------- Wiring ------------------------- */
  $$("#task-tabs .tab").forEach((tab) => tab.addEventListener("click", () => { setTab(tab.dataset.filter); safe(loadTasks); }));
  let debounce;
  $("#f-search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => safe(loadTasks), 250); });
  let current = "dashboard";
  const loaders = { dashboard: loadDashboard, tasks: loadTasks };
  function safe(fn) { return fn && fn().catch((e) => toast(e.message, "error")); }
  const navigate = initNav((view) => { current = view; safe(loaders[view]); });
  function refreshAll() { safe(loadDashboard); safe(loadTasks); loadNotifications(); }
  const chat = initChat({
    scope: "agent",
    greeting: { title: `Hi ${me.display_name}, I'm your personal task assistant`, text: "I can only see your own tasks. Ask me what to work on next, what's overdue, or for a quick summary." },
    suggestions: ["Summarize my tasks", "Analyze my pending tasks and arrange them in order of priority. Tell me which tasks I should complete first and why.",
      "Which of my tasks are overdue?", "Which tasks have not been started?"],
  });
  bindQuickAsk(navigate, chat);
  setInterval(() => { if (current !== "assistant" && !$("#modal")) safe(loaders[current]); }, 60000);
})();
