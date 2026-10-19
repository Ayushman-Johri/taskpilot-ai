/* Admin console: dashboard, tasks, team (agents + admins, roles), admin AI bot, audit log */
(async function () {
  const me = await guardPage("admin").catch(() => null);
  if (!me) return;

  let META = { statuses: [], priorities: [] }, AGENTS = [], ADMINS = [], teamTab = "agents";
  initHeader(me, { onShortcut: (k) => {
    if (k === "ai") { navigate("assistant"); chat.focus(); }
    if (k === "search") { if (current !== "tasks" && current !== "team") navigate("tasks"); $(current === "team" ? "#team-search" : "#f-search").focus(); }
    if (k === "new") current === "team" ? userForm() : taskForm();
  } });
  META = await api("/api/tasks/meta");
  $("#f-status").innerHTML += META.statuses.map((s) => `<option>${esc(s)}</option>`).join("");
  $("#f-priority").innerHTML += META.priorities.map((p) => `<option>${esc(p)}</option>`).join("");
  $("#hello").textContent = `${greeting()}, ${me.display_name} 👋`;

  window.TaskPreviewActions = (t) => [
    { label: "Edit task", icon: "edit", primary: true, onClick: () => taskForm(t) },
    { label: `Show all ${t.agent_name} tasks`, icon: "list", onClick: () => openAgentTasks(t.agent_username) },
  ];

  async function reloadPeople() {
    [AGENTS, ADMINS] = await Promise.all([api("/api/admin/agents"), api("/api/admin/admins")]);
    const sel = $("#f-agent"), cur = sel.value;
    sel.innerHTML = `<option value="">All agents</option>` + AGENTS.map((a) => `<option value="${esc(a.username)}">${esc(a.display_name)}</option>`).join("");
    sel.value = AGENTS.some((a) => a.username === cur) ? cur : "";
    $("#count-agents").textContent = AGENTS.length; $("#count-admins").textContent = ADMINS.length;
  }
  await reloadPeople();

  /* ------------------------- Dashboard ------------------------- */
  async function loadDashboard() {
    const [d, stats] = await Promise.all([api("/api/dashboard/admin"), api("/api/ai/admin/stats").catch(() => null)]);
    const c = d.counts, ins = d.insights;
    $("#hello-sub").textContent = c.pending
      ? `${c.pending} pending task${c.pending > 1 ? "s" : ""} across ${d.per_agent.length} agents · ${ins.week_completed} completed this week.`
      : "Everything is completed. Great work, team! 🎉";
    $("#hero-pills").innerHTML = [
      c.overdue ? `<span class="hp bad">${icon("alert")}${c.overdue} overdue</span>` : `<span class="hp ok">${icon("check")}Nothing overdue</span>`,
      `<span class="hp">${icon("clock")}${d.upcoming.length} due in 72h</span>`,
      `<span class="hp">${icon("chart")}${c.completion_rate_pct}% complete</span>`,
    ].join("");
    $("#admin-stats").innerHTML = [
      statCard("Total tasks", c.total, "list", "indigo", `${c.pending} pending`, "all"),
      statCard("Completed", c.completed, "check", "green", `${ins.week_completed} this week`, "Completed"),
      statCard("In progress", c.in_progress, "play", "blue", "", "In Progress"),
      statCard("Partially done", c.partially_completed, "half", "amber", "", "Partially Completed"),
      statCard("Not started", c.not_started, "pause", "slate", c.on_hold ? `${c.on_hold} on hold` : "", "Not Started"),
      statCard("Overdue", c.overdue, "alert", "red", c.overdue ? `${ins.overdue_to_pending_pct}% of pending` : "all on track", "overdue"),
    ].join("");
    countUp($("#admin-stats"));
    $$("#admin-stats [data-go]").forEach((b) => b.addEventListener("click", () => {
      clearFilters(false);
      if (b.dataset.go === "overdue") $("#f-overdue").checked = true; else if (b.dataset.go !== "all") $("#f-status").value = b.dataset.go;
      navigate("tasks");
    }));
    $("#week-done").textContent = `${ins.week_completed} done`;
    $("#trend").innerHTML = trendChart(ins.trend);
    $("#team-progress").innerHTML = `${donut(c.completion_rate_pct, "Completed")}
      <div class="tp-legend">
        <div><span class="dot green"></span>Completed <b>${c.completed}</b></div><div><span class="dot blue"></span>In progress <b>${c.in_progress}</b></div>
        <div><span class="dot amber"></span>Partial <b>${c.partially_completed}</b></div><div><span class="dot purple"></span>On hold <b>${c.on_hold}</b></div>
        <div><span class="dot slate"></span>Not started <b>${c.not_started}</b></div><div class="muted small">Avg progress <b>${c.avg_progress_pct}%</b></div></div>`;
    $("#prio-mix").innerHTML = priorityMix(ins.priority_mix);
    $("#calendar").innerHTML = calendarStrip(ins.calendar);
    $("#attention").innerHTML = attentionList(ins.attention, true);

    const maxTotal = Math.max(1, ...d.per_agent.map((a) => a.total));
    $("#agent-bars").innerHTML = d.per_agent.map((a) => {
      const active = a.in_progress + a.partially_completed + a.on_hold, pct = (n) => (n / maxTotal) * 100;
      return `<div class="bar-row clickable" data-agent-filter="${esc(a.agent)}" title="Show ${esc(a.agent)}'s tasks">
        <div class="bar-label"><span class="avatar sm">${initials(a.agent)}</span><span class="ellipsis">${esc(a.agent)}</span></div>
        <div class="stack"><span class="seg done" style="width:${pct(a.completed)}%"></span><span class="seg prog" style="width:${pct(active)}%"></span><span class="seg ns" style="width:${pct(a.not_started)}%"></span></div>
        <div class="bar-num">${a.total}${a.overdue ? ` <span class="od-pill">${a.overdue} overdue</span>` : ""}</div></div>`;
    }).join("") || emptyState("No agents yet - add one from the Team page", "users");
    $("#agent-table").innerHTML = `<thead><tr><th>Agent</th><th>Total</th><th>Done</th><th>Active</th><th>Not started</th><th>Overdue</th><th>Completion</th></tr></thead><tbody>` +
      (d.per_agent.map((a) => `<tr class="clickable" data-agent-filter="${esc(a.agent)}">
        <td><div class="agent-chip"><span class="avatar sm">${initials(a.agent)}</span>${esc(a.agent)}</div></td>
        <td>${a.total}</td><td>${a.completed}</td><td>${a.in_progress + a.partially_completed + a.on_hold}</td><td>${a.not_started}</td>
        <td class="${a.overdue ? "text-red strong" : ""}">${a.overdue}</td>
        <td><div class="prog-wrap">${progressBar(a.completion_rate_pct, a.completion_rate_pct === 100 ? "Completed" : "")}<span>${a.completion_rate_pct}%</span></div></td></tr>`).join("")
        || `<tr><td colspan="7">${emptyState("No agents yet", "users")}</td></tr>`) + "</tbody>";
    $$("#view-dashboard [data-agent-filter]").forEach((r) => r.addEventListener("click", () => openAgentTasks(AGENTS.find((x) => x.display_name === r.dataset.agentFilter)?.username)));
    $("#ai-stats").innerHTML = stats ? aiStatsCard(stats) : emptyState("No AI usage yet", "sparkle");
    $("#admin-activity").innerHTML = d.recent_activity.length ? d.recent_activity.map((h) => `<div class="mini-item" data-task="${h.task_id}">
        <span class="avatar sm">${initials(h.by_name)}</span><div><b>${esc(h.title)}</b><small>${esc(h.by_name)} · ${esc(h.created_local)}${h.note ? " · " + esc(h.note) : ""}</small></div>${h.status ? statusBadge(h.status) : ""}</div>`).join("") : emptyState("No activity yet", "log");
    $$("#view-dashboard [data-task]").forEach((el) => el.addEventListener("click", () => showTaskDetail(el.dataset.task)));
  }
  $("#clear-cache").addEventListener("click", async () => { await api("/api/ai/admin/cache", { method: "DELETE" }); toast("AI answer cache cleared", "success"); safe(loadDashboard); });

  /* ------------------------- Tasks ------------------------- */
  function clearFilters(reload = true) {
    $("#f-search").value = ""; $("#f-agent").value = ""; $("#f-status").value = ""; $("#f-priority").value = ""; $("#f-overdue").checked = false;
    if (reload) safe(loadTasks);
  }
  async function loadTasks() {
    const qs = new URLSearchParams();
    if ($("#f-search").value.trim()) qs.set("q", $("#f-search").value.trim());
    if ($("#f-agent").value) qs.set("agent", $("#f-agent").value);
    if ($("#f-status").value) qs.set("status", $("#f-status").value);
    if ($("#f-priority").value) qs.set("priority", $("#f-priority").value);
    if ($("#f-overdue").checked) qs.set("overdue_only", "true");
    $("#f-clear").hidden = ![...qs.keys()].length;
    const tasks = await api("/api/tasks?" + qs), table = $("#tasks-table");
    if (!tasks.length) { table.innerHTML = `<tbody><tr><td>${emptyState("No tasks match these filters")}</td></tr></tbody>`; return; }
    table.innerHTML = `<thead><tr><th>Task</th><th>Assigned to</th><th>Priority</th><th>Status</th><th>Progress</th><th>Deadline</th><th class="right">Actions</th></tr></thead><tbody>` +
      tasks.map((t, i) => `<tr class="clickable row-in ${t.is_overdue ? "row-overdue" : ""}" data-row="${t.id}" style="--i:${Math.min(i, 15)}">
        <td class="task-cell"><b>${esc(t.title)}</b><small>#${t.id}${t.description ? " · " + esc(t.description) : ""}</small></td>
        <td><div class="agent-chip ${t.agent_active ? "" : "removed"}"><span class="avatar sm">${initials(t.agent_name)}</span>${esc(t.agent_name)}</div></td>
        <td>${priorityBadge(t.priority)}</td><td>${statusBadge(t.status)}</td>
        <td><div class="prog-wrap">${progressBar(t.progress, t.status)}<span>${t.progress}%</span></div></td>
        <td class="deadline-cell"><div>${esc(t.deadline_local)}</div>${timeChip(t)}</td>
        <td class="right nowrap"><button class="icon-btn" title="Edit" data-act="edit" data-id="${t.id}">${icon("edit")}</button>
          <button class="icon-btn danger" title="Delete" data-act="delete" data-id="${t.id}">${icon("trash")}</button></td></tr>`).join("") + "</tbody>";
    $$("#tasks-table [data-row]").forEach((r) => r.addEventListener("click", (e) => { if (!e.target.closest("button")) showTaskDetail(r.dataset.row); }));
    $$("#tasks-table [data-act]").forEach((b) => b.addEventListener("click", () => { const t = tasks.find((x) => x.id === +b.dataset.id); b.dataset.act === "edit" ? taskForm(t) : deleteTask(t); }));
  }

  function taskForm(t = null) {
    if (!AGENTS.length) { toast("Add an agent first (Team page).", "error"); return; }
    const isEdit = !!t, pad = (n) => String(n).padStart(2, "0");
    const opt = (list, sel) => list.map((v) => `<option ${v === sel ? "selected" : ""}>${esc(v)}</option>`).join("");
    const agentOpts = (isEdit && !t.agent_active ? `<option value="" selected disabled>${esc(t.agent_name)} - choose a new agent</option>` : "") +
      AGENTS.map((a) => `<option value="${esc(a.username)}" ${t && t.agent_username === a.username ? "selected" : ""}>${esc(a.display_name)} (${a.pending} pending)</option>`).join("");
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
        ${isEdit ? `<div><label>Status</label><select name="status">${opt(META.statuses, t.status)}</select></div><div><label>Progress %</label><input name="progress" type="number" min="0" max="100" value="${t.progress}"></div>` : ""}
      </div>`,
      onSubmit: async (form) => {
        const f = Object.fromEntries(new FormData(form).entries());
        if (!f.title.trim()) throw new Error("Title is required.");
        if (!f.assigned_to) throw new Error("Please choose an agent.");
        if (!f.deadline) throw new Error("Deadline is required.");
        if (!isEdit && new Date(f.deadline) < new Date()) throw new Error("Deadline must be in the future.");
        const body = { title: f.title.trim(), description: f.description.trim(), assigned_to: f.assigned_to, priority: f.priority, deadline: f.deadline,
          estimated_hours: f.estimated_hours === "" ? null : Number(f.estimated_hours) };
        if (isEdit) { body.status = f.status; body.progress = f.progress === "" ? null : Number(f.progress); await api(`/api/tasks/${t.id}`, { method: "PUT", body }); toast("Task updated", "success"); }
        else { await api("/api/tasks", { method: "POST", body }); toast(`Task assigned to ${AGENTS.find((a) => a.username === f.assigned_to)?.display_name}`, "success"); }
        refreshAll();
      },
    });
    const m = $("#modal");
    $$(".seg-btn", m).forEach((b) => b.addEventListener("click", () => { $$(".seg-btn", m).forEach((x) => x.classList.toggle("on", x === b)); m.querySelector("[name=priority]").value = b.dataset.v; }));
    $$(".quick-dates .chip", m).forEach((b) => b.addEventListener("click", () => {
      const d = new Date(); d.setDate(d.getDate() + Number(b.dataset.days));
      m.querySelector("[name=deadline]").value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T18:00`;
    }));
    if (isEdit) {
      const st = m.querySelector("[name=status]"), pr = m.querySelector("[name=progress]");
      st.addEventListener("change", () => {
        if (st.value === "Completed") pr.value = 100; else if (st.value === "Not Started") pr.value = 0; else if (+pr.value >= 100) pr.value = 90;
        pr.readOnly = st.value === "Completed" || st.value === "Not Started";
      });
      st.dispatchEvent(new Event("change"));
    }
  }
  async function deleteTask(t) {
    if (!(await confirmDialog("Delete task", `Delete "${t.title}" assigned to ${t.agent_name}? This cannot be undone.`, "Delete"))) return;
    try { await api(`/api/tasks/${t.id}`, { method: "DELETE" }); toast("Task deleted", "success"); refreshAll(); } catch (e) { toast(e.message, "error"); }
  }

  /* ------------------------- Team ------------------------- */
  function renderTeam() {
    const q = $("#team-search").value.trim().toLowerCase();
    const match = (u) => !q || u.display_name.toLowerCase().includes(q) || u.username.includes(q);
    const grid = $("#team-grid");
    if (teamTab === "agents") {
      const list = AGENTS.filter(match);
      grid.innerHTML = list.length ? list.map((a, i) => `
        <article class="agent-card pop-in" style="--i:${i}">
          <div class="ac-top"><span class="avatar xl">${initials(a.display_name)}</span><div class="ac-name"><b>${esc(a.display_name)}</b><small>@${esc(a.username)}</small></div>${roleBadge("agent")}</div>
          <div class="ac-stats"><div><b>${a.total}</b><small>Total</small></div><div><b>${a.pending}</b><small>Pending</small></div><div><b>${a.completed}</b><small>Done</small></div><div class="${a.overdue ? "text-red" : ""}"><b>${a.overdue}</b><small>Overdue</small></div></div>
          <div class="prog-wrap">${progressBar(a.completion_rate_pct, a.completion_rate_pct === 100 ? "Completed" : "")}<span>${a.completion_rate_pct}%</span></div>
          <div class="ac-actions">
            <button class="btn ghost sm" data-act="tasks" data-u="${esc(a.username)}">${icon("tasks")}Tasks</button><button class="btn ghost sm" data-act="edit" data-u="${esc(a.username)}">${icon("edit")}Edit</button>
            <button class="btn ghost sm" data-act="reset" data-u="${esc(a.username)}">${icon("key")}Password</button><button class="btn ghost sm promote" data-act="promote" data-u="${esc(a.username)}">${icon("shield")}Make admin</button>
            <button class="btn ghost sm danger-ghost" data-act="delete" data-u="${esc(a.username)}">${icon("trash")}Delete</button></div></article>`).join("")
        : emptyState(q ? "No agents match your search" : "No agents yet. Click 'Add User'.", "users");
    } else {
      const list = ADMINS.filter(match), lock = (a) => a.is_you || ADMINS.length < 2 ? "disabled title='Not allowed for yourself / last admin'" : "";
      grid.innerHTML = list.length ? list.map((a, i) => `
        <article class="agent-card admin-card pop-in" style="--i:${i}">
          <div class="ac-top"><span class="avatar xl admin">${initials(a.display_name)}</span><div class="ac-name"><b>${esc(a.display_name)}${a.is_you ? ' <span class="you">(you)</span>' : ""}</b><small>@${esc(a.username)}</small></div>${roleBadge("admin")}</div>
          <p class="muted small">Full access: manage tasks, users and roles; team-wide AI assistant.</p>
          <div class="ac-actions"><button class="btn ghost sm" data-act="edit" data-u="${esc(a.username)}">${icon("edit")}Edit</button><button class="btn ghost sm" data-act="reset" data-u="${esc(a.username)}">${icon("key")}Password</button>
            <button class="btn ghost sm" data-act="demote" data-u="${esc(a.username)}" ${lock(a)}>${icon("down")}Make agent</button><button class="btn ghost sm danger-ghost" data-act="delete" data-u="${esc(a.username)}" ${lock(a)}>${icon("trash")}Delete</button></div></article>`).join("")
        : emptyState("No admins match your search", "shield");
    }
    $$("#team-grid [data-act]").forEach((b) => b.addEventListener("click", () => {
      const u = [...AGENTS, ...ADMINS].find((x) => x.username === b.dataset.u);
      ({ tasks: () => openAgentTasks(u.username), edit: () => userForm(u), reset: () => resetPassword(u),
         promote: () => roleOrDelete(u, "promote"), demote: () => roleOrDelete(u, "demote"), delete: () => roleOrDelete(u, "delete") })[b.dataset.act]();
    }));
  }
  async function loadTeam() { await reloadPeople(); renderTeam(); }
  const setTeamTab = (tab) => { teamTab = tab; $$("#team-tabs .tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab)); };
  $$("#team-tabs .tab").forEach((t) => t.addEventListener("click", () => { setTeamTab(t.dataset.tab); renderTeam(); }));
  function openAgentTasks(username) { clearFilters(false); $("#f-agent").value = username || ""; navigate("tasks"); }

  function userForm(u = null) {
    const isEdit = !!u, role = isEdit ? u.role : (teamTab === "admins" ? "admin" : "agent");
    openModal({
      title: isEdit ? `Edit ${u.display_name}` : "Add a new user", submitText: isEdit ? "Save changes" : "Add user",
      body: `${isEdit ? "" : `<label>Role</label><div class="role-pick">
          <label class="role-opt"><input type="radio" name="role" value="agent" ${role === "agent" ? "checked" : ""}><span>${icon("users")}<b>Agent</b><small>Sees &amp; updates own tasks</small></span></label>
          <label class="role-opt"><input type="radio" name="role" value="admin" ${role === "admin" ? "checked" : ""}><span>${icon("shield")}<b>Admin</b><small>Full access to everything</small></span></label></div>`}
        <label>Full name *</label><input name="name" maxlength="50" required value="${esc(u?.display_name || "")}" placeholder="e.g. Rahul Sharma">
        <label>Username ${isEdit ? "" : '<span class="muted small">(auto-filled, you can change it)</span>'}</label><input name="username" maxlength="30" value="${esc(u?.username || "")}" placeholder="e.g. rahul_sharma" autocomplete="off">
        ${isEdit ? `<p class="hint">Changing the username logs the user out.</p>` : `<label>Password <span class="muted small">(leave empty to auto-generate)</span></label><input name="password" type="text" minlength="6" placeholder="min 6 characters" autocomplete="new-password">`}`,
      onSubmit: async (form) => {
        const name = form.name.value.trim(), username = form.username.value.trim().toLowerCase();
        if (name.length < 2) throw new Error("Name must be at least 2 characters.");
        if (isEdit) {
          const body = {};
          if (name !== u.display_name) body.name = name;
          if (username && username !== u.username) body.username = username;
          if (!Object.keys(body).length) throw new Error("Nothing changed.");
          await api(`/api/admin/users/${encodeURIComponent(u.username)}`, { method: "PUT", body }); toast("User updated", "success"); refreshAll();
        } else {
          const password = form.password.value;
          if (password && password.length < 6) throw new Error("Password must be at least 6 characters.");
          const r = form.querySelector("input[name=role]:checked").value;
          const res = await api("/api/admin/users", { method: "POST", body: { name, role: r, username: username || null, password: password || null } });
          setTeamTab(r === "admin" ? "admins" : "agents"); refreshAll();
          setTimeout(() => showCredentials({ title: `New ${res.role}: ${res.display_name}`, username: res.username, password: res.password }), 60);
        }
      },
    });
    if (!isEdit) {
      const n = $("#modal [name=name]"), un = $("#modal [name=username]"); let touched = false;
      un.addEventListener("input", () => (touched = true));
      n.addEventListener("input", () => { if (!touched) un.value = n.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30); });
    }
  }
  function resetPassword(u) {
    openModal({
      title: `Reset password · ${u.display_name}`, submitText: "Reset password",
      body: `<label>New password <span class="muted small">(leave empty to auto-generate)</span></label><input name="password" type="text" minlength="6" placeholder="min 6 characters" autocomplete="new-password">
        <p class="hint">${u.username === me.username ? "This is your own account." : "The user will be logged out and must sign in with the new password."}</p>`,
      onSubmit: async (form) => {
        const pwd = form.password.value;
        if (pwd && pwd.length < 6) throw new Error("Password must be at least 6 characters.");
        const res = await api(`/api/admin/users/${encodeURIComponent(u.username)}`, { method: "PUT", body: pwd ? { password: pwd } : { reset_password: true } });
        setTimeout(() => showCredentials({ title: `Password reset: ${res.display_name}`, username: res.username, password: res.password }), 60);
      },
    });
  }
  function roleOrDelete(u, mode) {
    const hasPending = u.role === "agent" && u.pending > 0, others = AGENTS.filter((x) => x.username !== u.username);
    const cfg = {
      promote: { title: `Make ${u.display_name} an admin`, btn: "Make admin", danger: false, ic: "shield", text: `<b>${esc(u.display_name)}</b> will get full admin access and will be logged out once to apply it.` },
      demote: { title: `Change ${u.display_name} to agent`, btn: "Make agent", danger: false, ic: "down", text: `<b>${esc(u.display_name)}</b> will lose admin access and will be logged out.` },
      delete: { title: `Delete ${u.display_name}`, btn: "Delete user", danger: true, ic: "alert", text: `<b>${esc(u.display_name)}</b> (@${esc(u.username)}) will lose access immediately.${u.completed ? ` ${u.completed} completed task(s) are kept for reports.` : ""}` },
    }[mode];
    openModal({
      title: cfg.title, submitText: cfg.btn, danger: cfg.danger,
      body: `<div class="warn-box ${cfg.danger ? "" : "info"}">${icon(cfg.ic)}<div>${cfg.text}</div></div>
        ${hasPending ? `<label>What should happen to the ${u.pending} pending task(s)?</label><div class="radio-list">
            <label class="radio-opt"><input type="radio" name="mode" value="reassign" ${others.length ? "checked" : "disabled"}><span>Reassign them to <select name="reassign_to" ${others.length ? "" : "disabled"}>${others.map((o) => `<option value="${esc(o.username)}">${esc(o.display_name)} (${o.pending} pending)</option>`).join("")}</select></span></label>
            <label class="radio-opt"><input type="radio" name="mode" value="delete" ${others.length ? "" : "checked"}><span>Delete them permanently</span></label></div>` : ""}
        <div class="preview-box" id="rd-preview"></div>`,
      onSubmit: async (form) => {
        const body = {};
        if (hasPending) {
          const m = form.querySelector("input[name=mode]:checked")?.value;
          if (m === "reassign") body.reassign_to = form.reassign_to.value; else if (m === "delete") body.delete_tasks = true; else throw new Error("Choose what to do with the pending tasks.");
        }
        const path = `/api/admin/users/${encodeURIComponent(u.username)}`;
        if (mode === "delete") { const r = await api(`${path}/delete`, { method: "POST", body }); toast(`${r.name} deleted`, "success"); }
        else { const r = await api(`${path}/role`, { method: "POST", body: { ...body, role: mode === "promote" ? "admin" : "agent" } }); toast(`${r.name} is now an ${r.to_role}`, "success"); setTeamTab(r.to_role === "admin" ? "admins" : "agents"); }
        refreshAll();
      },
    });
    const preview = async () => {
      const form = $("#modal form"); if (!form) return;
      const qs = new URLSearchParams(), m = form.querySelector("input[name=mode]:checked")?.value;
      if (m === "reassign" && form.reassign_to) qs.set("reassign_to", form.reassign_to.value);
      if (m === "delete") qs.set("delete_tasks", "true");
      if (mode !== "delete") qs.set("role", mode === "promote" ? "admin" : "agent");
      try { $("#rd-preview").textContent = (await api(`/api/admin/users/${encodeURIComponent(u.username)}/${mode === "delete" ? "delete" : "role"}-preview?${qs}`)).summary; }
      catch (e) { $("#rd-preview").textContent = e.message; }
    };
    $$("#modal input[name=mode], #modal select[name=reassign_to]").forEach((el) => el.addEventListener("change", preview));
    preview();
  }

  /* ------------------------- Audit log ------------------------- */
  async function loadAudit() {
    const rows = await api("/api/admin/audit");
    $("#audit-table").innerHTML = `<thead><tr><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td class="nowrap">${esc(r.created_local)}</td><td>${esc(r.display_name || "—")}</td>
        <td><span class="badge ${/denied|failed|delete|off_topic/.test(r.action) ? "pr-critical" : /create|done|role/.test(r.action) ? "st-done" : "st-notstarted"}">${esc(r.action)}</span></td>
        <td class="muted">${esc(r.detail)}</td></tr>`).join("") + "</tbody>";
  }

  /* ------------------------- Wiring ------------------------- */
  let debounce;
  $("#f-search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => safe(loadTasks), 250); });
  ["#f-agent", "#f-status", "#f-priority", "#f-overdue"].forEach((s) => $(s).addEventListener("change", () => safe(loadTasks)));
  $("#f-clear").addEventListener("click", () => clearFilters());
  $("#new-task-btn").addEventListener("click", () => taskForm());
  $("#new-user-btn").addEventListener("click", () => userForm());
  $("#team-search").addEventListener("input", renderTeam);
  $("#refresh-audit").addEventListener("click", () => safe(loadAudit));

  let current = "dashboard";
  const loaders = { dashboard: loadDashboard, tasks: loadTasks, team: loadTeam, activity: loadAudit };
  function safe(fn) { return fn && fn().catch((e) => toast(e.message, "error")); }
  const navigate = initNav((view) => { current = view; safe(loaders[view]); });
  async function refreshAll() { await reloadPeople().catch(() => {}); renderTeam(); safe(loadDashboard); safe(loadTasks); loadNotifications(); }

  const chat = initChat({
    scope: "admin", onDataChanged: refreshAll,
    greeting: { title: "Hi Admin, I'm your team assistant", text: "Ask about workload and deadlines, or tell me what to do: assign or update tasks, add users, change roles." },
    suggestions: ["Give me a team summary", "Which tasks are overdue across the team?", "Which agent has the highest number of pending tasks?",
      "Assign a task 'Prepare weekly report' to Agent A by tomorrow 6 PM, priority High", "Add a new agent named Rahul Sharma", "Make Agent F an admin"],
  });
  bindQuickAsk(navigate, chat);
  setInterval(() => { if (!["assistant", "team"].includes(current) && !$("#modal")) safe(loaders[current]); }, 60000);
})();
