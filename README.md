# TaskPilot AI v6

AI-powered task management with **dynamic, database-driven roles and permissions**.
Python Flask · vanilla JS · SQLite · JWT · Groq `openai/gpt-oss-120b`.

## Run
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env  -> set GROQ_API_KEY
python app.py                 # http://127.0.0.1:5000
```
Upgrading from v5? Copy your old `backend/taskpilot.db` here. It is migrated automatically
(`admin` users -> Admin role, `agent` users -> Agent role). Everyone logs in once again.

| Demo user | Password | Role |
|---|---|---|
| admin | admin123 | Admin (locked, full access except updating progress) |
| agent_a … agent_f | agent123 | Agent |
| viewer | viewer123 | Viewer (team dashboard + all tasks, read-only) |
| hr | hr12345 | User Manager (add / edit users only) |

## Roles & permissions (v6)
Roles live in the database: `roles` + `role_permissions`, and `users.role_id`.
Admins create roles from **Roles & Access**, tick the permissions, and assign the role to users.
Changes apply on the user's very next request (permissions are loaded from the DB on every request).

| Permission | Allows |
|---|---|
| dashboard.team | Team dashboard & analytics |
| tasks.view_all | See every task |
| tasks.create / tasks.edit / tasks.delete | Create & assign / edit details & reassign / delete |
| tasks.view_own | See own assigned tasks |
| tasks.update_own | Be assigned tasks and update their status / progress |
| users.view / users.create / users.edit / users.delete | Team members |
| roles.manage | Create roles, edit permissions, change users' roles |
| audit.view | Audit log (page + AI) |
| ai.use | AI assistant |

Rules
* **Only the assignee can update status/progress.** Nobody else - not even Admin - can change it (UI, API and AI).
* Progress and status stay consistent: setting 70% on a "Not Started" task moves it to "In Progress"; 100% -> Completed.
* No privilege escalation: you can only grant a role (or manage a user) whose permissions you hold yourself.
* The Admin role is locked; system roles can't be deleted; a role in use can't be deleted;
  at least one user always keeps `roles.manage`; nobody can change their own role or delete themselves.
* Dependencies are added automatically (e.g. `tasks.create` needs `tasks.view_all`).

## AI assistant
One endpoint (`/api/ai/chat`); its data, tools and suggestions come from the user's permissions.
* Agent: "update my progress of CRM task to 70%" -> `update_my_progress` tool (finds the task by name or id).
* Admin: progress requests are refused with a clear reason; "show me audit logs" / "audit log of task #12" -> instant answer.
* Read-only roles: change requests are refused before the model is called.
* The model may only report changes when a tool result says UPDATED / CREATED / AWAITING_CONFIRMATION.
* Token saving from v5 is kept: guards, instant answers, answer cache, compact data, static prompts.

## Structure
```
backend/  app.py config.py permissions.py database.py auth.py jwt_utils.py
          repository.py (tasks) users.py roles.py notifications.py
          ai/ assistant.py tools.py instant.py cache.py context.py prompts.py guard.py scope.py ratelimit.py audit_view.py
          routes/ auth, tasks, dashboard, users (users + roles + audit), notifications, ai
frontend/ index.html app.html css/style.css js/(theme api ui markdown login app).js
```
