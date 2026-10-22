/* TaskPilot single app page. Every section, button and AI suggestion is shown according to the
   logged-in user's PERMISSIONS (loaded from the database). The backend checks the same permissions again. */
(async function () {
  ME = await requireLogin().catch(() => null);
  if (!ME) return;

  // ---- show only allowed navigation ----
  $$(".nav-link[data-view]").forEach((l) => {
    const perms = (l.dataset.perm || "").split(",").filter(Boolean);
    l.hidden = perms.length > 0 && !canAny(...perms);
  });
  const META = await api("/api/tasks/meta");
  let PEOPLE = [], ROLES = [], ASSIGNEES = [], PERMS = [], current = "dashboard";
  const pad = (n) => String(n).padStart(2, "0");
  function safe(fn) { return fn && fn().catch((e) => toast(e.message, "error")); }

  initHeader(ME, { onShortcut: (k) => {
    if (k === "ai" && can("ai.use")) { navigate("assistant"); chat && chat.focus(); }
    if (k === "search") { navigate(current === "team" ? "team" : "tasks"); ($(current === "team" ? "#team-search" : can("tasks.view_all") ? "#f-search" : "#m-search") || {}).focus?.(); }
    if (k === "new") { if (current === "team" && can("users.create")) userForm(); else if (current === "roles") roleForm(); else if (can("tasks.create")) taskForm(); }
  } });

  window.TaskPreviewActions = (t) => {
    const acts = [];
    if (t.agent_username === ME.username && can("tasks.update_own") && t.status !== "Completed")
      acts.push({ label: "Update progress", icon: "edit", primary: true, onClick: () => openUpdate(t) });
    if (can("tasks.edit")) acts.push({ label: "Edit task", icon: "edit", primary: !acts.length, onClick: () => taskForm(t) });
    if (can("tasks.view_all")) acts.push({ label: `All ${t.agent_name} tasks`, icon: "list", onClick: () => openAgentTasks(t.agent_username) });
    return acts;
  };

  async function reloadLookups() {
    const jobs = [];
    jobs.push(canAny("tasks.create", "tasks.edit", "tasks.view_all", "users.view") ? api("/api/users/assignees") : Promise.resolve([]));
    jobs.push(can("users.view") ? api("/api/users") : Promise.resolve([]));
    jobs.push(canAny("roles.manage", "users.view", "users.create") ? api("/api/roles") : Promise.resolve([]));
    [ASSIGNEES, PEOPLE, ROLES] = await Promise.all(jobs);
    const sel = $("#f-agent"), cur = sel.value;
    sel.innerHTML = `<option value="">All assignees</option>` + ASSIGNEES.map((a) => `<option value="${esc(a.username)}">${esc(a.display_name)}</option>`).join("");
    sel.value = ASSIGNEES.some((a) => a.username === cur) ? cur : "";
    const rs = $("#team-role"), rcur = rs.value;
    rs.innerHTML = `<option value="">All roles</option>` + ROLES.map((r) => `<option>${esc(r.name)}</option>`).join("");
    rs.value = ROLES.some((r) => r.name === rcur) ? rcur : "";
  }
  await reloadLookups();
  $("#f-status").innerHTML += META.statuses.map((s) => `<option>${esc(s)}</option>`).join("");
  $("#f-priority").innerHTML += META.priorities.map((p) => `<option>${esc(p)}</option>`).join("");

  /* ===================================== DASHBOARD ===================================== */
  const SK = '<div class="skeleton" style="height:96px"></div>'.repeat(6);
  function heroHTML(chips, ph) {
    return `<div class="hero ${can("tasks.view_all") ? "" : "hero-green"}"><div class="hero-text"><h2>${esc(greeting())}, ${esc(ME.display_name)} 👋</h2><p id="hello-sub"></p><div class="hero-pills" id="hero-pills"></div></div>
      ${can("ai.use") ? `<form class="quick-ask" id="quick-ask" autocomplete="off"><label>✨ Ask TaskPilot AI</label>
        <div class="qa-row"><input name="q" placeholder="${esc(ph)}"><button class="btn light" type="submit">${icon("sparkle")}</button></div>
        <div class="qa-chips">${chips.map(([l, q]) => `<button type="button" class="chip" data-q="${esc(q)}">${esc(l)}</button>`).join("")}</div></form>` : ""}</div>`;
  }
  function bindQuickAsk() {
    const f = $("#quick-ask");
    if (!f) return;
    f.addEventListener("submit", (e) => { e.preventDefault(); const q = f.q.value.trim(); if (!q) return; f.q.value = ""; navigate("assistant"); chat.ask(q); });
    $$("#quick-ask .chip").forEach((c) => c.addEventListener("click", () => { navigate("assistant"); chat.ask(c.dataset.q); }));
  }

  async function loadDashboard() {
    if (can("dashboard.team")) return teamDashboard();
    if (can("tasks.view_own")) return myDashboard();
    const links = $$(".nav-link[data-view]").filter((l) => !l.hidden && l.dataset.view !== "dashboard");
    $("#dash").innerHTML = heroHTML([], "Ask about your work...") + `<div class="card"><div class="card-head"><h3>Your access</h3><span class="muted small">Role: ${esc(ME.role)}</span></div>
      <div class="quick-links">${links.map((l) => `<button class="quick-link" data-go="${l.dataset.view}">${l.querySelector("svg").outerHTML}<b>${esc(l.dataset.title)}</b></button>`).join("") || emptyState("Your role has no pages yet. Ask an administrator for access.", "lock")}</div>
      <h4 class="section-title">Permissions in your role</h4><div class="perm-chips">${ME.permissions.map((p) => `<span class="perm-chip">${esc(p)}</span>`).join("")}</div></div>`;
    $("#hello-sub").textContent = "Here is what your role lets you do.";
    $$(".quick-link").forEach((b) => b.addEventListener("click", () => navigate(b.dataset.go)));
    bindQuickAsk();
  }

  async function teamDashboard() {
    if (!$("#admin-stats")) {
      $("#dash").innerHTML = heroHTML([["⚡ Overdue", "Which tasks are overdue across the team?"], ["⚡ Workload", "Give me a team summary"], ["⚡ Completion rate", "What is the overall task completion rate?"]], "e.g. Who has the most pending tasks?") +
        `<div class="stats-grid" id="admin-stats">${SK}</div><div class="dash-grid">
          <div class="card span-5"><div class="card-head"><h3>Completed · last 7 days</h3><span class="pill-num" id="week-done"></span></div><div id="trend"></div></div>
          <div class="card span-4"><div class="card-head"><h3>Team progress</h3></div><div class="team-progress compact" id="team-progress"></div></div>
          <div class="card span-3"><div class="card-head"><h3>Pending by priority</h3></div><div id="prio-mix"></div></div>
          <div class="card span-7"><div class="card-head"><h3>Next 7 days</h3><span class="muted small">Hover a day to see tasks</span></div><div id="calendar"></div>
            <h4 class="section-title">Workload <span class="legend"><i class="lg done"></i>Done <i class="lg prog"></i>Active <i class="lg ns"></i>Not started</span></h4><div id="agent-bars"></div></div>
          <div class="card span-5"><div class="card-head"><h3>🚨 Needs attention</h3></div><div id="attention"></div></div>
          <div class="card span-7"><div class="card-head"><h3>Performance by assignee</h3><span class="muted small">Click a row to see their tasks</span></div><div class="table-wrap"><table class="table" id="agent-table"></table></div></div>
          <div class="card span-5" id="ai-card" ${canAny("dashboard.team", "audit.view") ? "" : "hidden"}><div class="card-head"><h3>AI efficiency</h3><button class="link-btn" id="clear-cache">Clear cache</button></div><div id="ai-stats"></div></div>
          <div class="card span-12"><div class="card-head"><h3>🕒 Recent activity</h3></div><div id="admin-activity" class="activity-grid"></div></div></div>`;
      $("#clear-cache").addEventListener("click", async () => { await api("/api/ai/cache", { method: "DELETE" }); toast("AI answer cache cleared", "success"); safe(loadDashboard); });
      bindQuickAsk();
    }
    const [d, stats] = await Promise.all([api("/api/dashboard/team"), api("/api/ai/stats").catch(() => null)]);
    const c = d.counts, ins = d.insights;
    $("#hello-sub").textContent = c.pending ? `${c.pending} pending task${c.pending > 1 ? "s" : ""} across ${d.per_agent.length} people · ${ins.week_completed} completed this week.` : "Everything is completed. Great work, team! 🎉";
    $("#hero-pills").innerHTML = [c.overdue ? `<span class="hp bad">${icon("alert")}${c.overdue} overdue</span>` : `<span class="hp ok">${icon("check")}Nothing overdue</span>`,
      `<span class="hp">${icon("clock")}${d.upcoming.length} due in 72h</span>`, `<span class="hp">${icon("chart")}${c.completion_rate_pct}% complete</span>`].join("");
    $("#admin-stats").innerHTML = [statCard("Total tasks", c.total, "list", "indigo", `${c.pending} pending`, "all"),
      statCard("Completed", c.completed, "check", "green", `${ins.week_completed} this week`, "Completed"), statCard("In progress", c.in_progress, "play", "blue", "", "In Progress"),
      statCard("Partially done", c.partially_completed, "half", "amber", "", "Partially Completed"),
      statCard("Not started", c.not_started, "pause", "slate", c.on_hold ? `${c.on_hold} on hold` : "", "Not Started"),
      statCard("Overdue", c.overdue, "alert", "red", c.overdue ? `${ins.overdue_to_pending_pct}% of pending` : "all on track", "overdue")].join("");
    countUp($("#admin-stats"));
    $$("#admin-stats [data-go]").forEach((b) => b.addEventListener("click", () => {
      clearFilters(false);
      if (b.dataset.go === "overdue") $("#f-overdue").checked = true; else if (b.dataset.go !== "all") $("#f-status").value = b.dataset.go;
      navigate("tasks");
    }));
    $("#week-done").textContent = `${ins.week_completed} done`;
    $("#trend").innerHTML = trendChart(ins.trend);
    $("#team-progress").innerHTML = `${donut(c.completion_rate_pct, "Completed")}<div class="tp-legend">
      <div><span class="dot green"></span>Completed <b>${c.completed}</b></div><div><span class="dot blue"></span>In progress <b>${c.in_progress}</b></div>
      <div><span class="dot amber"></span>Partial <b>${c.partially_completed}</b></div><div><span class="dot purple"></span>On hold <b>${c.on_hold}</b></div>
      <div><span class="dot slate"></span>Not started <b>${c.not_started}</b></div><div class="muted small">Avg progress <b>${c.avg_progress_pct}%</b></div></div>`;
    $("#prio-mix").innerHTML = priorityMix(ins.priority_mix);
    $("#calendar").innerHTML = calendarStrip(ins.calendar);
    $("#attention").innerHTML = attentionList(ins.attention, true);
    const maxTotal = Math.max(1, ...d.per_agent.map((a) => a.total));
    $("#agent-bars").innerHTML = d.per_agent.map((a) => {
      const active = a.in_progress + a.partially_completed + a.on_hold, pct = (n) => (n / maxTotal) * 100;
      return `<div class="bar-row clickable" data-u="${esc(a.username)}"><div class="bar-label"><span class="avatar sm">${initials(a.agent)}</span><span class="ellipsis">${esc(a.agent)}</span></div>
        <div class="stack"><span class="seg done" style="width:${pct(a.completed)}%"></span><span class="seg prog" style="width:${pct(active)}%"></span><span class="seg ns" style="width:${pct(a.not_started)}%"></span></div>
        <div class="bar-num">${a.total}${a.overdue ? ` <span class="od-pill">${a.overdue} overdue</span>` : ""}</div></div>`;
    }).join("") || emptyState("Nobody can be assigned tasks yet", "users");
    $("#agent-table").innerHTML = `<thead><tr><th>Assignee</th><th>Total</th><th>Done</th><th>Active</th><th>Not started</th><th>Overdue</th><th>Completion</th></tr></thead><tbody>` +
      (d.per_agent.map((a) => `<tr class="clickable" data-u="${esc(a.username)}"><td><div class="agent-chip"><span class="avatar sm">${initials(a.agent)}</span>${esc(a.agent)}</div></td>
        <td>${a.total}</td><td>${a.completed}</td><td>${a.in_progress + a.partially_completed + a.on_hold}</td><td>${a.not_started}</td><td class="${a.overdue ? "text-red strong" : ""}">${a.overdue}</td>
        <td><div class="prog-wrap">${progressBar(a.completion_rate_pct, a.completion_rate_pct === 100 ? "Completed" : "")}<span>${a.completion_rate_pct}%</span></div></td></tr>`).join("")
        || `<tr><td colspan="7">${emptyState("No assignees yet", "users")}</td></tr>`) + "</tbody>";
    $$("#dash [data-u]").forEach((r) => r.addEventListener("click", () => openAgentTasks(r.dataset.u)));
    $("#ai-stats").innerHTML = stats ? aiStatsCard(stats) : emptyState("No AI usage yet", "sparkle");
    $("#admin-activity").innerHTML = d.recent_activity.length ? d.recent_activity.map((h) => `<div class="mini-item" data-task="${h.task_id}"><span class="avatar sm">${initials(h.by_name)}</span>
        <div><b>${esc(h.title)}</b><small>${esc(h.by_name)} · ${esc(h.created_local)}${h.note ? " · " + esc(h.note) : ""}</small></div>${h.status ? statusBadge(h.status) : ""}</div>`).join("") : emptyState("No activity yet", "log");
    $$("#dash [data-task]").forEach((el) => el.addEventListener("click", () => showTaskDetail(el.dataset.task)));
  }

  async function myDashboard() {
    if (!$("#agent-stats")) {
      $("#dash").innerHTML = heroHTML([["⚡ Plan my day", "Analyze my pending tasks and arrange them in order of priority. Tell me which tasks I should complete first and why."], ["⚡ Summary", "Summarize my tasks"], ["⚡ Overdue", "Which of my tasks are overdue?"]], "e.g. Update CRM task to 70%") +
        `<div class="stats-grid" id="agent-stats">${SK}</div><div class="dash-grid">
          <div class="card span-7"><div class="card-head"><h3>🎯 Focus next</h3><span class="muted small">Ranked by deadline, priority &amp; effort</span></div><div id="focus-list" class="focus-list"></div></div>
          <div class="card span-5"><div class="card-head"><h3>My progress</h3></div><div class="team-progress compact" id="my-progress"></div>
            <h4 class="section-title">Completed · last 7 days <span class="pill-num" id="week-done"></span></h4><div id="trend"></div></div>
          <div class="card span-7"><div class="card-head"><h3>Next 7 days</h3></div><div id="calendar"></div></div>
          <div class="card span-5"><div class="card-head"><h3>🚨 Needs attention</h3></div><div id="attention"></div></div></div>`;
      bindQuickAsk();
    }
    const d = await api("/api/dashboard/me"), c = d.counts, ins = d.insights, today = ins.calendar[0]?.count || 0;
    $("#hello-sub").textContent = c.total === 0 ? "No tasks are assigned to you yet." : c.pending ? `You have ${c.pending} pending task${c.pending > 1 ? "s" : ""}${today ? `, ${today} due today` : ""}. Let's get going!` : "All your tasks are completed. Great job! 🎉";
    $("#hero-pills").innerHTML = [c.overdue ? `<span class="hp bad">${icon("alert")}${c.overdue} overdue</span>` : `<span class="hp ok">${icon("check")}Nothing overdue</span>`,
      `<span class="hp">${icon("check")}${ins.week_completed} done this week</span>`, `<span class="hp">${icon("chart")}${c.avg_progress_pct}% avg progress</span>`].join("");
    $("#agent-stats").innerHTML = [statCard("Assigned to me", c.total, "list", "indigo", `${c.pending} pending`, "all"), statCard("Completed", c.completed, "check", "green", `${ins.week_completed} this week`, "completed"),
      statCard("In progress", c.in_progress, "play", "blue", "", "pending"), statCard("Partially done", c.partially_completed, "half", "amber", "", "pending"),
      statCard("Not started", c.not_started, "pause", "slate", c.on_hold ? `${c.on_hold} on hold` : "", "pending"), statCard("Overdue", c.overdue, "alert", "red", c.overdue ? "act now" : "all on track", "overdue")].join("");
    countUp($("#agent-stats"));
    $$("#agent-stats [data-go]").forEach((b) => b.addEventListener("click", () => { setTab(b.dataset.go); navigate("tasks"); }));
    $("#focus-list").innerHTML = d.top_priorities.length ? d.top_priorities.map((t, i) => `<div class="focus-item pop-in" data-task="${t.id}" style="--i:${i}"><div class="rank">${t.rank}</div>
        <div class="focus-body"><div class="focus-title"><b>${esc(t.title)}</b>${priorityBadge(t.priority)}</div>
          <div class="focus-meta">${statusBadge(t.status)} ${timeChip({ ...t, remaining_human: t.time_left, is_overdue: t.overdue })}</div>
          <div class="mini-prog">${progressBar(t.progress, t.status)}<span>${t.progress}%</span></div>
          <div class="focus-why">${t.reasons.map((r) => `<span>${esc(r)}</span>`).join("")}</div></div>
        ${can("tasks.update_own") ? `<button class="btn sm primary" data-update="${t.id}">Update</button>` : ""}</div>`).join("") : emptyState("No pending tasks — you're all done! 🎉", "check");
    $("#my-progress").innerHTML = `${donut(c.completion_rate_pct, "Completed")}<div class="tp-legend"><div><span class="dot green"></span>Completed <b>${c.completed}</b></div>
      <div><span class="dot blue"></span>In progress <b>${c.in_progress}</b></div><div><span class="dot amber"></span>Partial <b>${c.partially_completed}</b></div>
      <div><span class="dot purple"></span>On hold <b>${c.on_hold}</b></div><div><span class="dot slate"></span>Not started <b>${c.not_started}</b></div></div>`;
    $("#week-done").textContent = `${ins.week_completed} done`;
    $("#trend").innerHTML = trendChart(ins.trend);
    $("#calendar").innerHTML = calendarStrip(ins.calendar);
    $("#attention").innerHTML = attentionList(ins.attention, false);
    $$("#dash [data-update]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openUpdateById(+b.dataset.update); }));
    $$("#dash [data-task]").forEach((el) => el.addEventListener("click", () => showTaskDetail(el.dataset.task)));
  }

  /* ===================================== TASKS ===================================== */
  $("#tasks-all").hidden = !can("tasks.view_all");
  $("#tasks-mine").hidden = !can("tasks.view_own");
  $("#new-task-btn").hidden = !can("tasks.create");

  function clearFilters(reload = true) {
    $("#f-search").value = ""; $("#f-agent").value = ""; $("#f-status").value = ""; $("#f-priority").value = ""; $("#f-overdue").checked = false;
    if (reload) safe(loadAllTasks);
  }
  function openAgentTasks(username) { clearFilters(false); $("#f-agent").value = username || ""; navigate("tasks"); }

  async function loadTasks() {
    const jobs = [];
    if (can("tasks.view_all")) jobs.push(loadAllTasks());
    if (can("tasks.view_own")) jobs.push(loadMyTasks());
    await Promise.all(jobs);
  }
  async function loadAllTasks() {
    const qs = new URLSearchParams();
    if ($("#f-search").value.trim()) qs.set("q", $("#f-search").value.trim());
    if ($("#f-agent").value) qs.set("agent", $("#f-agent").value);
    if ($("#f-status").value) qs.set("status", $("#f-status").value);
    if ($("#f-priority").value) qs.set("priority", $("#f-priority").value);
    if ($("#f-overdue").checked) qs.set("overdue_only", "true");
    $("#f-clear").hidden = ![...qs.keys()].length;
    const tasks = await api("/api/tasks?" + qs), table = $("#tasks-table");
    if (!tasks.length) { table.innerHTML = `<tbody><tr><td>${emptyState("No tasks match these filters")}</td></tr></tbody>`; return; }
    const actions = can("tasks.edit") || can("tasks.delete");
    table.innerHTML = `<thead><tr><th>Task</th><th>Assigned to</th><th>Priority</th><th>Status</th><th>Progress</th><th>Deadline</th>${actions ? '<th class="right">Actions</th>' : ""}</tr></thead><tbody>` +
      tasks.map((t, i) => `<tr class="clickable row-in ${t.is_overdue ? "row-overdue" : ""}" data-row="${t.id}" style="--i:${Math.min(i, 15)}">
        <td class="task-cell"><b>${esc(t.title)}</b><small>#${t.id}${t.description ? " · " + esc(t.description) : ""}</small></td>
        <td><div class="agent-chip ${t.agent_active ? "" : "removed"}"><span class="avatar sm">${initials(t.agent_name)}</span>${esc(t.agent_name)}</div></td>
        <td>${priorityBadge(t.priority)}</td><td>${statusBadge(t.status)}</td>
        <td><div class="prog-wrap" title="Progress is updated by the assignee">${progressBar(t.progress, t.status)}<span>${t.progress}%</span></div></td>
        <td class="deadline-cell"><div>${esc(t.deadline_local)}</div>${timeChip(t)}</td>
        ${actions ? `<td class="right nowrap">${can("tasks.edit") ? `<button class="icon-btn" title="Edit details" data-act="edit" data-id="${t.id}">${icon("edit")}</button>` : ""}
          ${can("tasks.delete") ? `<button class="icon-btn danger" title="Delete" data-act="delete" data-id="${t.id}">${icon("trash")}</button>` : ""}</td>` : ""}</tr>`).join("") + "</tbody>";
    $$("#tasks-table [data-row]").forEach((r) => r.addEventListener("click", (e) => { if (!e.target.closest("button")) showTaskDetail(r.dataset.row); }));
    $$("#tasks-table [data-act]").forEach((b) => b.addEventListener("click", () => { const t = tasks.find((x) => x.id === +b.dataset.id); b.dataset.act === "edit" ? taskForm(t) : deleteTask(t); }));
  }

  function taskForm(t = null) {
    const isEdit = !!t;
    if (!ASSIGNEES.length) { toast("Nobody can be assigned tasks yet. Give a role the 'Work on tasks' permission first.", "error"); return; }
    const agentOpts = (isEdit && !t.agent_active ? `<option value="" selected disabled>${esc(t.agent_name)} - choose someone new</option>` : "") +
      ASSIGNEES.map((a) => `<option value="${esc(a.username)}" ${t && t.agent_username === a.username ? "selected" : ""}>${esc(a.display_name)} (${a.pending} pending)</option>`).join("");
    const def = new Date(Date.now() + 2 * 86400000); def.setMinutes(0, 0, 0);
    const defDeadline = `${def.getFullYear()}-${pad(def.getMonth() + 1)}-${pad(def.getDate())}T${pad(def.getHours())}:00`;
    openModal({
      title: isEdit ? `Edit task #${t.id}` : "Create & assign a task", submitText: isEdit ? "Save changes" : "Create task",
      body: `<div class="form-grid">
        <div class="full"><label>Title *</label><input name="title" maxlength="200" required value="${esc(t?.title || "")}" placeholder="e.g. Prepare monthly sales report"></div>
        <div class="full"><label>Description</label><textarea name="description" rows="3" placeholder="What needs to be done?">${esc(t?.description || "")}</textarea></div>
        <div><label>Assign to *</label><select name="assigned_to" required>${agentOpts}</select></div>
        <div><label>Priority *</label><div class="seg-group">${META.priorities.map((p) => `<button type="button" class="seg-btn pr-${p.toLowerCase()} ${p === (t?.priority || "Medium") ? "on" : ""}" data-v="${p}">${p}</button>`).join("")}</div><input type="hidden" name="priority" value="${esc(t?.priority || "Medium")}"></div>
        <div><label>Deadline *</label><input name="deadline" type="datetime-local" required value="${esc(t?.deadline_input || defDeadline)}">
          <div class="quick-dates">${[["Today 6PM", 0], ["Tomorrow", 1], ["+3 days", 3], ["+1 week", 7]].map(([l, d]) => `<button type="button" class="chip xs" data-days="${d}">${l}</button>`).join("")}</div></div>
        <div><label>Estimated effort (hours)</label><input name="estimated_hours" type="number" min="0" step="0.5" value="${t?.estimated_hours ?? ""}" placeholder="optional"></div>
        ${isEdit ? `<div class="full info-line">${icon("lock")} Status (${esc(t.status)}) and progress (${t.progress}%) can only be updated by ${esc(t.agent_name)}.</div>` : ""}
      </div>`,
      onSubmit: async (form) => {
        const f = Object.fromEntries(new FormData(form).entries());
        if (!f.title.trim()) throw new Error("Title is required.");
        if (!f.assigned_to) throw new Error("Please choose an assignee.");
        if (!f.deadline) throw new Error("Deadline is required.");
        if (!isEdit && new Date(f.deadline) < new Date()) throw new Error("Deadline must be in the future.");
        const body = { title: f.title.trim(), description: f.description.trim(), assigned_to: f.assigned_to, priority: f.priority, deadline: f.deadline,
          estimated_hours: f.estimated_hours === "" ? null : Number(f.estimated_hours) };
        if (isEdit) { await api(`/api/tasks/${t.id}`, { method: "PUT", body }); toast("Task updated", "success"); }
        else { await api("/api/tasks", { method: "POST", body }); toast(`Task assigned to ${ASSIGNEES.find((a) => a.username === f.assigned_to)?.display_name}`, "success"); }
        refreshAll();
      },
    });
    const m = $("#modal");
    $$(".seg-btn", m).forEach((b) => b.addEventListener("click", () => { $$(".seg-btn", m).forEach((x) => x.classList.toggle("on", x === b)); m.querySelector("[name=priority]").value = b.dataset.v; }));
    $$(".quick-dates .chip", m).forEach((b) => b.addEventListener("click", () => {
      const d = new Date(); d.setDate(d.getDate() + Number(b.dataset.days));
      m.querySelector("[name=deadline]").value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T18:00`;
    }));
  }
  async function deleteTask(t) {
    if (!(await confirmDialog("Delete task", `Delete "${t.title}" assigned to ${t.agent_name}? This cannot be undone.`, "Delete"))) return;
    try { await api(`/api/tasks/${t.id}`, { method: "DELETE" }); toast("Task deleted", "success"); refreshAll(); } catch (e) { toast(e.message, "error"); }
  }

  // ---- my tasks (cards) ----
  let filter = "pending", MINE = [];
  function setTab(f) { filter = f; $$("#task-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.filter === f)); }
  async function loadMyTasks() {
    const qs = new URLSearchParams({ mine: "true" }), q = $("#m-search").value.trim();
    if (q) qs.set("q", q);
    if (filter === "pending") qs.set("pending_only", "true");
    if (filter === "overdue") qs.set("overdue_only", "true");
    if (filter === "completed") qs.set("status", "Completed");
    MINE = await api("/api/tasks?" + qs);
    const grid = $("#task-grid"), upd = can("tasks.update_own");
    if (!MINE.length) { grid.innerHTML = emptyState(filter === "overdue" ? "No overdue tasks 🎉" : filter === "completed" ? "No completed tasks yet" : "No tasks here", "tasks"); return; }
    grid.innerHTML = MINE.map((t, i) => `<article class="task-card pop-in ${t.is_overdue ? "overdue" : ""} ${t.status === "Completed" ? "is-done" : ""}" style="--i:${Math.min(i, 12)}" data-card="${t.id}">
        <div class="tc-top">${priorityBadge(t.priority)}<div class="status-menu"><button type="button" class="status-trigger" data-menu="${t.id}" ${t.status === "Completed" || !upd ? "disabled" : ""}>${statusBadge(t.status)}${t.status === "Completed" || !upd ? "" : '<span class="caret">▾</span>'}</button>
          <div class="status-pop" id="pop-${t.id}">${META.statuses.filter((s) => s !== t.status).map((s) => `<button type="button" data-quick="${t.id}" data-status="${esc(s)}">${statusBadge(s)}</button>`).join("")}</div></div></div>
        <h3>${esc(t.title)}</h3><p class="tc-desc">${esc(t.description || "No description")}</p>
        <div class="tc-progress"><div class="tc-progress-head"><span>Progress</span><b>${t.progress}%</b></div>${progressBar(t.progress, t.status)}</div>
        <div class="tc-meta"><div><small>Deadline</small><span>${esc(t.deadline_local)}</span></div><div>${timeChip(t)}</div></div>
        <div class="tc-actions"><button class="btn ghost sm" data-act="view" data-id="${t.id}">${icon("eye")}Details</button>
          ${upd && t.status === "Not Started" ? `<button class="btn ghost sm" data-act="start" data-id="${t.id}">${icon("play")}Start</button>` : ""}
          ${upd && t.status !== "Completed" ? `<button class="btn ghost sm success" data-act="done" data-id="${t.id}">${icon("check")}Done</button><button class="btn primary sm" data-act="update" data-id="${t.id}">${icon("edit")}Update</button>` : ""}</div></article>`).join("");
    $$("#task-grid [data-act]").forEach((b) => b.addEventListener("click", async () => {
      const t = MINE.find((x) => x.id === +b.dataset.id);
      try {
        if (b.dataset.act === "view") await showTaskDetail(t.id);
        if (b.dataset.act === "update") openUpdate(t);
        if (b.dataset.act === "start") await saveProgress(t.id, { status: "In Progress", progress: Math.max(t.progress, 10) }, "Task started 🚀");
        if (b.dataset.act === "done" && await confirmDialog("Mark as completed", `Mark "${t.title}" as completed?`, "Mark completed", false)) await saveProgress(t.id, { status: "Completed" }, "Great job! Task completed 🎉", t.id);
      } catch (e) { toast(e.message, "error"); }
    }));
    $$("#task-grid [data-menu]").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation(); const pop = $(`#pop-${b.dataset.menu}`), open = pop.classList.contains("open");
      $$(".status-pop.open").forEach((p) => p.classList.remove("open")); if (!open) pop.classList.add("open");
    }));
    $$("#task-grid [data-quick]").forEach((b) => b.addEventListener("click", async () => {
      const t = MINE.find((x) => x.id === +b.dataset.quick), s = b.dataset.status;
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
  const HELP = { "Not Started": "Haven't begun yet", "In Progress": "Actively working on it", "Partially Completed": "Part of the work is done", "On Hold": "Blocked / waiting", "Completed": "All work is finished" };
  function openUpdate(t) {
    openModal({
      title: "Update task progress", submitText: "Save update",
      body: `<div class="upd-head"><b>${esc(t.title)}</b><div>${priorityBadge(t.priority)} ${timeChip(t)}</div></div>
        <label>Status</label><div class="status-options">${META.statuses.map((s) => `<label class="status-opt"><input type="radio" name="status" value="${esc(s)}" ${s === t.status ? "checked" : ""}><span>${statusBadge(s)}<small>${esc(HELP[s])}</small></span></label>`).join("")}</div>
        <label>Progress: <b id="pv">${t.progress}%</b></label><input type="range" name="progress" min="0" max="100" step="5" value="${t.progress}" class="range">
        <div class="range-marks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><div class="hint" id="p-hint"></div>
        <label>Note <span class="muted small">(optional)</span></label><textarea name="note" rows="3" maxlength="1000" placeholder="e.g. Data collected, formatting pending"></textarea>`,
      onSubmit: async (form) => {
        const status = form.querySelector("input[name=status]:checked")?.value, progress = Number(form.progress.value), note = form.note.value.trim();
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
      else if (status === "Not Started") { v = 0; hint.textContent = "Move the slider to start - status becomes In Progress."; }
      else { if (v >= 100) v = 95; if (status === "Partially Completed" && v < 5) v = fromStatus ? 50 : Math.max(v, 5); }
      range.value = v; pv.textContent = v + "%"; paint();
    };
    $$("input[name=status]", form).forEach((r) => r.addEventListener("change", () => sync(true)));
    range.addEventListener("input", () => {
      pv.textContent = range.value + "%"; paint();
      const checked = form.querySelector("input[name=status]:checked"), v = +range.value;
      if (checked?.value === "Not Started" && v > 0) form.querySelector('input[value="In Progress"]').checked = true;
      if (v === 100) { form.querySelector('input[value="Completed"]').checked = true; sync(false); }
    });
    sync(false);
  }

  /* ===================================== TEAM ===================================== */
  $("#new-user-btn").hidden = !can("users.create");
  function renderTeam() {
    const q = $("#team-search").value.trim().toLowerCase(), role = $("#team-role").value;
    const list = PEOPLE.filter((u) => (!role || u.role === role) && (!q || u.display_name.toLowerCase().includes(q) || u.username.includes(q)));
    $("#team-grid").innerHTML = list.length ? list.map((u, i) => {
      const manage = u.manageable && !u.is_you;
      return `<article class="agent-card pop-in ${u.role === "Admin" ? "admin-card" : ""}" style="--i:${i}">
        <div class="ac-top"><span class="avatar xl ${u.role === "Admin" ? "admin" : ""}">${initials(u.display_name)}</span>
          <div class="ac-name"><b>${esc(u.display_name)}${u.is_you ? ' <span class="you">(you)</span>' : ""}</b><small>@${esc(u.username)}</small></div>${roleBadge(u.role)}</div>
        ${u.assignable && u.total !== undefined ? `<div class="ac-stats"><div><b>${u.total}</b><small>Total</small></div><div><b>${u.pending}</b><small>Pending</small></div><div><b>${u.completed}</b><small>Done</small></div><div class="${u.overdue ? "text-red" : ""}"><b>${u.overdue}</b><small>Overdue</small></div></div>
          <div class="prog-wrap">${progressBar(u.completion_rate_pct, u.completion_rate_pct === 100 ? "Completed" : "")}<span>${u.completion_rate_pct}%</span></div>` : `<p class="muted small">${u.assignable ? "Works on assigned tasks." : "Does not work on tasks."}</p>`}
        <div class="ac-actions">
          ${u.assignable && can("tasks.view_all") ? `<button class="btn ghost sm" data-act="tasks" data-u="${esc(u.username)}">${icon("tasks")}Tasks</button>` : ""}
          ${can("users.edit") && manage ? `<button class="btn ghost sm" data-act="edit" data-u="${esc(u.username)}">${icon("edit")}Edit</button><button class="btn ghost sm" data-act="reset" data-u="${esc(u.username)}">${icon("key")}Password</button>` : ""}
          ${can("roles.manage") && manage ? `<button class="btn ghost sm promote" data-act="role" data-u="${esc(u.username)}">${icon("shield")}Change role</button>` : ""}
          ${can("users.delete") && manage ? `<button class="btn ghost sm danger-ghost" data-act="delete" data-u="${esc(u.username)}">${icon("trash")}Delete</button>` : ""}
          ${u.is_you ? `<button class="btn ghost sm" data-act="reset" data-u="${esc(u.username)}">${icon("key")}My password</button>` : ""}</div></article>`;
    }).join("") : emptyState("No people match", "users");
    $$("#team-grid [data-act]").forEach((b) => b.addEventListener("click", () => {
      const u = PEOPLE.find((x) => x.username === b.dataset.u);
      ({ tasks: () => openAgentTasks(u.username), edit: () => userForm(u), reset: () => resetPassword(u), role: () => roleOrDelete(u, "role"), delete: () => roleOrDelete(u, "delete") })[b.dataset.act]();
    }));
  }
  async function loadTeam() { await reloadLookups(); renderTeam(); }
  const roleOptions = (selected) => ROLES.filter((r) => r.grantable).map((r) => `<option value="${esc(r.name)}" ${r.name === selected ? "selected" : ""}>${esc(r.name)}</option>`).join("");

  function userForm(u = null) {
    const isEdit = !!u;
    openModal({
      title: isEdit ? `Edit ${u.display_name}` : "Add a new user", submitText: isEdit ? "Save changes" : "Add user",
      body: `${isEdit ? "" : `<label>Role</label><select name="role">${roleOptions("Agent")}</select><div class="hint" id="role-hint"></div>`}
        <label>Full name *</label><input name="name" maxlength="50" required value="${esc(u?.display_name || "")}" placeholder="e.g. Rahul Sharma">
        <label>Username ${isEdit ? "" : '<span class="muted small">(auto-filled)</span>'}</label><input name="username" maxlength="30" value="${esc(u?.username || "")}" autocomplete="off">
        ${isEdit ? `<p class="hint">Changing the username signs the user out.</p>` : `<label>Password <span class="muted small">(leave empty to auto-generate)</span></label><input name="password" type="text" minlength="6" autocomplete="new-password">`}`,
      onSubmit: async (form) => {
        const name = form.name.value.trim(), username = form.username.value.trim().toLowerCase();
        if (name.length < 2) throw new Error("Name must be at least 2 characters.");
        if (isEdit) {
          const body = {};
          if (name !== u.display_name) body.name = name;
          if (username && username !== u.username) body.username = username;
          if (!Object.keys(body).length) throw new Error("Nothing changed.");
          await api(`/api/users/${encodeURIComponent(u.username)}`, { method: "PUT", body }); toast("User updated", "success"); refreshAll();
        } else {
          const password = form.password.value;
          if (password && password.length < 6) throw new Error("Password must be at least 6 characters.");
          const res = await api("/api/users", { method: "POST", body: { name, role: form.role.value, username: username || null, password: password || null } });
          refreshAll();
          setTimeout(() => showCredentials({ title: `New user: ${res.display_name} (${res.role})`, username: res.username, password: res.password }), 60);
        }
      },
    });
    if (!isEdit) {
      const n = $("#modal [name=name]"), un = $("#modal [name=username]"), rs = $("#modal [name=role]"); let touched = false;
      un.addEventListener("input", () => (touched = true));
      n.addEventListener("input", () => { if (!touched) un.value = n.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30); });
      const hint = () => { const r = ROLES.find((x) => x.name === rs.value); $("#role-hint").textContent = r ? `${r.permissions.length} permissions: ${r.permissions.join(", ")}` : ""; };
      rs.addEventListener("change", hint); hint();
    }
  }
  function resetPassword(u) {
    openModal({
      title: `Reset password · ${u.display_name}`, submitText: "Reset password",
      body: `<label>New password <span class="muted small">(leave empty to auto-generate)</span></label><input name="password" type="text" minlength="6" autocomplete="new-password">
        <p class="hint">${u.is_you ? "This is your own account." : "The user will be signed out and must log in with the new password."}</p>`,
      onSubmit: async (form) => {
        const pwd = form.password.value;
        if (pwd && pwd.length < 6) throw new Error("Password must be at least 6 characters.");
        const res = await api(`/api/users/${encodeURIComponent(u.username)}`, { method: "PUT", body: pwd ? { password: pwd } : { reset_password: true } });
        setTimeout(() => showCredentials({ title: `Password reset: ${res.display_name}`, username: res.username, password: res.password }), 60);
      },
    });
  }
  function roleOrDelete(u, mode) {
    const others = ASSIGNEES.filter((x) => x.username !== u.username), hasPending = u.assignable && (u.pending || 0) > 0;
    const isRole = mode === "role";
    openModal({
      title: isRole ? `Change role · ${u.display_name}` : `Delete ${u.display_name}`, submitText: isRole ? "Change role" : "Delete user", danger: !isRole,
      body: `<div class="warn-box ${isRole ? "info" : ""}">${icon(isRole ? "shield" : "alert")}<div>${isRole ? `Current role: <b>${esc(u.role)}</b>. The user will be signed out once so the new access applies.` : `<b>${esc(u.display_name)}</b> will lose access immediately. Completed tasks are kept for reports.`}</div></div>
        ${isRole ? `<label>New role</label><select name="role">${roleOptions(u.role === "Agent" ? "Viewer" : "Agent")}</select>` : ""}
        ${hasPending ? `<label>If they stop working on tasks, what happens to their ${u.pending} pending task(s)?</label><div class="radio-list">
            <label class="radio-opt"><input type="radio" name="mode" value="reassign" ${others.length ? "checked" : "disabled"}><span>Reassign to <select name="reassign_to" ${others.length ? "" : "disabled"}>${others.map((o) => `<option value="${esc(o.username)}">${esc(o.display_name)} (${o.pending} pending)</option>`).join("")}</select></span></label>
            <label class="radio-opt"><input type="radio" name="mode" value="delete" ${others.length ? "" : "checked"}><span>Delete them</span></label></div>` : ""}
        <div class="preview-box" id="rd-preview"></div>`,
      onSubmit: async (form) => {
        const body = {}, m = form.querySelector("input[name=mode]:checked")?.value;
        if (hasPending) { if (m === "reassign") body.reassign_to = form.reassign_to.value; else if (m === "delete") body.delete_tasks = true; }
        const path = `/api/users/${encodeURIComponent(u.username)}`;
        if (isRole) { const r = await api(`${path}/role`, { method: "POST", body: { ...body, role: form.role.value } }); toast(`${r.name} now has the role '${r.to_role}'`, "success"); }
        else { const r = await api(`${path}/delete`, { method: "POST", body }); toast(`${r.name} deleted`, "success"); }
        refreshAll();
      },
    });
    const preview = async () => {
      const form = $("#modal form"); if (!form) return;
      const qs = new URLSearchParams(), m = form.querySelector("input[name=mode]:checked")?.value;
      if (hasPending && m === "reassign" && form.reassign_to) qs.set("reassign_to", form.reassign_to.value);
      if (hasPending && m === "delete") qs.set("delete_tasks", "true");
      if (isRole) qs.set("role", form.role.value);
      try { $("#rd-preview").textContent = (await api(`/api/users/${encodeURIComponent(u.username)}/${isRole ? "role" : "delete"}-preview?${qs}`)).summary; }
      catch (e) { $("#rd-preview").textContent = e.message; }
    };
    $$("#modal input[name=mode], #modal select").forEach((el) => el.addEventListener("change", preview));
    preview();
  }

  /* ===================================== ROLES ===================================== */
  const PRESETS = {
    "Full admin": ["dashboard.team", "tasks.view_all", "tasks.create", "tasks.edit", "tasks.delete", "users.view", "users.create", "users.edit", "users.delete", "roles.manage", "audit.view", "ai.use"],
    "Agent (works on tasks)": ["tasks.view_own", "tasks.update_own", "ai.use"],
    "Viewer (read-only)": ["dashboard.team", "tasks.view_all", "ai.use"],
    "Task manager": ["dashboard.team", "tasks.view_all", "tasks.create", "tasks.edit", "ai.use"],
    "User manager": ["users.view", "users.create", "users.edit", "ai.use"],
  };
  async function loadRoles() {
    if (!PERMS.length) PERMS = await api("/api/permissions");
    await reloadLookups();
    const label = Object.fromEntries(PERMS.map((p) => [p.code, p.label]));
    $("#role-grid").innerHTML = ROLES.map((r, i) => `<article class="role-card pop-in" style="--i:${i}">
      <div class="rc-head"><div>${roleBadge(r.name)}${r.locked ? ` <span class="muted small">${icon("lock")} locked</span>` : r.is_system ? ' <span class="muted small">system</span>' : ""}</div>
        <span class="muted small">${r.user_count} user${r.user_count === 1 ? "" : "s"}</span></div>
      <p class="muted small">${esc(r.description || "No description")}</p>
      <div class="perm-chips">${r.permissions.map((p) => `<span class="perm-chip" title="${esc(label[p] || p)}">${esc(label[p] || p)}</span>`).join("")}</div>
      <div class="ac-actions">${!r.locked && r.grantable ? `<button class="btn ghost sm" data-edit="${r.id}">${icon("edit")}Edit permissions</button>` : ""}
        ${!r.is_system && r.grantable ? `<button class="btn ghost sm danger-ghost" data-del="${r.id}" ${r.user_count ? "disabled title='Change these users\\' role first'" : ""}>${icon("trash")}Delete</button>` : ""}</div></article>`).join("");
    $$("#role-grid [data-edit]").forEach((b) => b.addEventListener("click", () => roleForm(ROLES.find((r) => r.id === +b.dataset.edit))));
    $$("#role-grid [data-del]").forEach((b) => b.addEventListener("click", async () => {
      const r = ROLES.find((x) => x.id === +b.dataset.del);
      if (!(await confirmDialog("Delete role", `Delete the role "${r.name}"?`, "Delete"))) return;
      try { await api(`/api/roles/${r.id}`, { method: "DELETE" }); toast("Role deleted", "success"); safe(loadRoles); } catch (e) { toast(e.message, "error"); }
    }));
  }
  async function roleForm(r = null) {
    if (!PERMS.length) PERMS = await api("/api/permissions");
    const isEdit = !!r, groups = [...new Set(PERMS.map((p) => p.group))], selected = new Set(r ? r.permissions : PRESETS["Agent (works on tasks)"]);
    openModal({
      title: isEdit ? `Edit role · ${r.name}` : "Create a role", submitText: isEdit ? "Save role" : "Create role", wide: true,
      body: `<div class="form-grid"><div><label>Role name *</label><input name="name" maxlength="40" required value="${esc(r?.name || "")}" ${r?.is_system ? "readonly" : ""} placeholder="e.g. Team Lead"></div>
        <div><label>Description</label><input name="description" maxlength="200" value="${esc(r?.description || "")}" placeholder="What is this role for?"></div></div>
        <label>Start from a preset</label><div class="qa-chips preset-chips">${Object.keys(PRESETS).map((k) => `<button type="button" class="chip xs" data-preset="${esc(k)}">${esc(k)}</button>`).join("")}</div>
        <div class="perm-groups">${groups.map((g) => `<fieldset class="perm-group"><legend>${esc(g)}</legend>${PERMS.filter((p) => p.group === g).map((p) => {
          const mine = ME.permissions.includes(p.code) || ["tasks.view_own", "tasks.update_own", "ai.use"].includes(p.code);
          return `<label class="perm-opt ${mine ? "" : "disabled"}" title="${mine ? "" : "You can only grant permissions you have yourself"}"><input type="checkbox" name="perm" value="${p.code}" ${selected.has(p.code) ? "checked" : ""} ${mine ? "" : "disabled"}>
            <span><b>${esc(p.label)}</b><small>${esc(p.code)}${p.requires.length ? ` · needs ${esc(p.requires.join(", "))}` : ""}</small></span></label>`; }).join("")}</fieldset>`).join("")}</div>
        <div class="hint" id="perm-count"></div>`,
      onSubmit: async (form) => {
        const permissions = $$("input[name=perm]:checked", form).map((x) => x.value);
        if (!permissions.length) throw new Error("Select at least one permission.");
        const body = { name: form.name.value.trim(), description: form.description.value.trim(), permissions };
        if (isEdit) { const res = await api(`/api/roles/${r.id}`, { method: "PUT", body }); toast(`Role saved${res.added.length || res.removed.length ? ` (+${res.added.length} / -${res.removed.length})` : ""}. Users get the new access immediately.`, "success"); }
        else { await api("/api/roles", { method: "POST", body }); toast("Role created", "success"); }
        await reloadLookups(); safe(loadRoles); if (current === "team") renderTeam();
      },
    });
    const form = $("#modal form"), boxes = $$("input[name=perm]", form);
    const deps = Object.fromEntries(PERMS.map((p) => [p.code, p.requires]));
    const count = () => ($("#perm-count").textContent = `${boxes.filter((b) => b.checked).length} permissions selected`);
    boxes.forEach((b) => b.addEventListener("change", () => {
      if (b.checked) (deps[b.value] || []).forEach((d) => { const x = boxes.find((y) => y.value === d); if (x && !x.disabled) x.checked = true; });
      else boxes.forEach((x) => { if (x.checked && (deps[x.value] || []).includes(b.value)) x.checked = false; });
      count();
    }));
    $$("[data-preset]", form).forEach((c) => c.addEventListener("click", () => { const set = new Set(PRESETS[c.dataset.preset]); boxes.forEach((b) => { if (!b.disabled) b.checked = set.has(b.value); }); count(); }));
    count();
  }
  $("#new-role-btn").addEventListener("click", () => roleForm());

  /* ===================================== AUDIT ===================================== */
  async function loadAudit() {
    const rows = await api("/api/audit");
    $("#audit-table").innerHTML = `<thead><tr><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td class="nowrap">${esc(r.created_local)}</td><td>${esc(r.display_name || "—")}</td>
        <td><span class="badge ${/denied|failed|delete|off_topic/.test(r.action) ? "pr-critical" : /create|done|role/.test(r.action) ? "st-done" : "st-notstarted"}">${esc(r.action)}</span></td>
        <td class="muted">${esc(r.detail)}</td></tr>`).join("") + "</tbody>";
  }

  /* ===================================== WIRING ===================================== */
  let debounce;
  $("#f-search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => safe(loadAllTasks), 250); });
  $("#m-search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => safe(loadMyTasks), 250); });
  ["#f-agent", "#f-status", "#f-priority", "#f-overdue"].forEach((s) => $(s).addEventListener("change", () => safe(loadAllTasks)));
  $("#f-clear").addEventListener("click", () => clearFilters());
  $$("#task-tabs .tab").forEach((tab) => tab.addEventListener("click", () => { setTab(tab.dataset.filter); safe(loadMyTasks); }));
  $("#new-task-btn").addEventListener("click", () => taskForm());
  $("#new-user-btn").addEventListener("click", () => userForm());
  $("#team-search").addEventListener("input", renderTeam);
  $("#team-role").addEventListener("change", renderTeam);
  $("#refresh-audit").addEventListener("click", () => safe(loadAudit));

  const loaders = { dashboard: loadDashboard, tasks: loadTasks, team: loadTeam, roles: loadRoles, activity: loadAudit };
  const navigate = initNav((view) => { current = view; safe(loaders[view]); });
  async function refreshAll() {
    await reloadLookups().catch(() => {});
    if (can("users.view")) renderTeam();
    safe(loadDashboard);
    if (canAny("tasks.view_all", "tasks.view_own")) safe(loadTasks);
    if (current === "roles") safe(loadRoles);
    loadNotifications();
  }

  // ---- AI assistant: suggestions follow the permissions ----
  let chat = null;
  if (can("ai.use")) {
    const sugg = [];
    if (can("tasks.view_all")) sugg.push("Which tasks are overdue across the team?", "Give me a team summary");
    if (can("tasks.view_own")) sugg.push("Summarize my tasks", "Which tasks should I complete first and why?");
    if (can("tasks.update_own")) sugg.push("Update my CRM task progress to 50%");
    if (can("tasks.create")) sugg.push("Assign a task 'Prepare weekly report' to Agent A by tomorrow 6 PM, priority High");
    if (can("users.create")) sugg.push("Add a new agent named Rahul Sharma");
    if (can("audit.view")) sugg.push("Show me the audit log");
    $("#bot-sub").textContent = `Role: ${ME.role} · follows your permissions`;
    chat = initChat({
      onDataChanged: refreshAll, suggestions: sugg.slice(0, 6),
      greeting: { title: `Hi ${ME.display_name}, I'm your TaskPilot assistant`, text: "I can only see and change what your role allows. Ask a question or tell me what to update." },
    });
  }
  setInterval(() => { if (!["assistant", "team", "roles"].includes(current) && !$("#modal")) safe(loaders[current]); }, 60000);
})();
