"""Permission catalogue. Roles are stored in the database (roles + role_permissions tables);
this file only defines WHICH permissions exist, their dependencies and the system role defaults."""

# (code, group, label)
PERMISSIONS = [
    ("dashboard.team", "Dashboard", "View team dashboard & analytics"),
    ("tasks.view_all", "Tasks", "View all tasks"),
    ("tasks.create", "Tasks", "Create & assign tasks"),
    ("tasks.edit", "Tasks", "Edit task details (title, deadline, priority, reassign)"),
    ("tasks.delete", "Tasks", "Delete tasks"),
    ("tasks.view_own", "My work", "View own assigned tasks"),
    ("tasks.update_own", "My work", "Work on tasks: can be assigned tasks and update their progress"),
    ("users.view", "Users", "View team members"),
    ("users.create", "Users", "Add users"),
    ("users.edit", "Users", "Rename users & reset passwords"),
    ("users.delete", "Users", "Delete users"),
    ("roles.manage", "Roles", "Create roles, edit permissions, change users' roles"),
    ("audit.view", "Audit", "View audit log"),
    ("ai.use", "AI", "Use the AI assistant"),
]
CODES = [p[0] for p in PERMISSIONS]
LABELS = {code: label for code, _, label in PERMISSIONS}

# Granting a permission automatically grants what it needs to work.
DEPENDS = {
    "dashboard.team": {"tasks.view_all"},
    "tasks.create": {"tasks.view_all"},
    "tasks.edit": {"tasks.view_all"},
    "tasks.delete": {"tasks.view_all"},
    "tasks.update_own": {"tasks.view_own"},
    "users.create": {"users.view"},
    "users.edit": {"users.view"},
    "users.delete": {"users.view"},
    "roles.manage": {"users.view"},
}

# Progress is updated ONLY by the person the task is assigned to, so admins don't get "my work".
ADMIN_PERMS = set(CODES) - {"tasks.view_own", "tasks.update_own"}
AGENT_PERMS = {"tasks.view_own", "tasks.update_own", "ai.use"}
# Basic "do your own work" permissions anyone who can add users may grant.
BASE_GRANTABLE = set(AGENT_PERMS)
WRITE_PERMS = {"tasks.create", "tasks.edit", "tasks.delete", "tasks.update_own",
               "users.create", "users.edit", "users.delete", "roles.manage"}

DEMO_ROLES = [
    ("Viewer", "Read-only manager view: team dashboard and all tasks",
     {"dashboard.team", "tasks.view_all", "ai.use"}),
    ("User Manager", "Adds team members and resets passwords; no task access",
     {"users.view", "users.create", "users.edit", "ai.use"}),
]


def normalize(perms) -> set:
    """Validate codes and add dependencies."""
    out = {p for p in (perms or []) if p in LABELS}
    changed = True
    while changed:
        changed = False
        for p in list(out):
            for d in DEPENDS.get(p, ()):
                if d not in out:
                    out.add(d)
                    changed = True
    return out


def catalogue() -> list:
    return [{"code": c, "group": g, "label": l, "requires": sorted(DEPENDS.get(c, ()))} for c, g, l in PERMISSIONS]
