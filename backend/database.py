"""SQLite access, schema creation/migration and demo seed data.

Roles and permissions live in the database:
  roles(id, name, description, is_system, locked)      e.g. Admin (locked), Agent, Viewer ...
  role_permissions(role_id, permission)                 one row per granted permission
  users.role_id -> roles.id
"""
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from typing import Optional

from config import DB_PATH, SEED_DEMO_DATA, DEMO_AGENT_LETTERS
from permissions import ADMIN_PERMS, AGENT_PERMS, DEMO_ROLES, normalize
from utils import now_utc, to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    is_system INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    token_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    assigned_to INTEGER NOT NULL REFERENCES users(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    deadline TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    estimated_hours REAL,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL, status TEXT, progress INTEGER, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
    task_id INTEGER, type TEXT NOT NULL, ref TEXT, message TEXT NOT NULL,
    created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')), content TEXT NOT NULL, meta TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_actions (
    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), tool TEXT NOT NULL, args TEXT NOT NULL,
    summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_cache (
    scope TEXT NOT NULL, qkey TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
    data_version TEXT NOT NULL, tokens INTEGER NOT NULL DEFAULT 0, hits INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, PRIMARY KEY (scope, qkey)
);
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, source TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS ix_updates_task ON task_updates(task_id);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS ix_chat_user ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS ix_actions_user ON ai_actions(user_id, status);
CREATE INDEX IF NOT EXISTS ix_usage_time ON ai_usage(created_at);
CREATE INDEX IF NOT EXISTS ix_role_perm ON role_permissions(permission);
CREATE INDEX IF NOT EXISTS ix_users_role ON users(role_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(user_id: Optional[int], action: str, detail: str = "") -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO audit_log(user_id, action, detail, created_at) VALUES (?,?,?,?)",
                     (user_id, action, (detail or "")[:2000], to_iso(now_utc())))


def role_permissions(conn, role_id: int) -> set:
    return {r[0] for r in conn.execute("SELECT permission FROM role_permissions WHERE role_id=?", (role_id,))}


def set_role_permissions(conn, role_id: int, perms) -> None:
    conn.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    conn.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?,?)",
                     [(role_id, p) for p in sorted(normalize(perms))])


def users_with_permission(conn, perm: str) -> list:
    return [r[0] for r in conn.execute(
        "SELECT u.id FROM users u WHERE u.is_active=1 AND u.role_id IN "
        "(SELECT role_id FROM role_permissions WHERE permission=?)", (perm,))]


def _ensure_role(conn, name, description, perms, is_system=0, locked=0) -> int:
    row = conn.execute("SELECT id FROM roles WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    rid = conn.execute("INSERT INTO roles(name, description, is_system, locked, created_at) VALUES (?,?,?,?,?)",
                       (name, description, is_system, locked, to_iso(now_utc()))).lastrowid
    set_role_permissions(conn, rid, perms)
    return rid


def _ensure_system_roles(conn):
    admin_id = _ensure_role(conn, "Admin", "Full access. Cannot update task progress - only the assignee can.",
                            ADMIN_PERMS, is_system=1, locked=1)
    agent_id = _ensure_role(conn, "Agent", "Works on assigned tasks and updates their progress.",
                            AGENT_PERMS, is_system=1)
    # The locked Admin role always has every admin permission (new permissions are added on upgrade).
    set_role_permissions(conn, admin_id, ADMIN_PERMS)
    return admin_id, agent_id


def _columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_users_to_roles() -> None:
    """v3-v5 databases had users.role = 'admin' | 'agent' with a CHECK constraint.
    Rebuild the users table with role_id (SQLite cannot drop a CHECK constraint in place)."""
    raw = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    try:
        exists = raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not exists:
            return
        cols = _columns(raw, "users")
        if "role_id" in cols:
            return
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("PRAGMA legacy_alter_table = ON")
        raw.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS users")[0])   # roles + role_permissions
        raw.execute("BEGIN")
        admin_id, agent_id = _ensure_system_roles(raw)
        tv = "token_version" if "token_version" in cols else "0"
        raw.execute("""CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
            role_id INTEGER NOT NULL REFERENCES roles(id), password_hash TEXT NOT NULL, salt TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1, token_version INTEGER NOT NULL DEFAULT 0)""")
        raw.execute(f"""INSERT INTO users_new(id, username, display_name, role_id, password_hash, salt, is_active, token_version)
                        SELECT id, username, display_name, CASE role WHEN 'admin' THEN ? ELSE ? END,
                               password_hash, salt, is_active, {tv} + 1 FROM users""", (admin_id, agent_id))
        raw.execute("DROP TABLE users")
        raw.execute("ALTER TABLE users_new RENAME TO users")
        raw.execute("COMMIT")
    except Exception:
        try:
            raw.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        raw.close()


def _migrate(conn) -> None:
    if "meta" not in _columns(conn, "chat_messages"):
        conn.execute("ALTER TABLE chat_messages ADD COLUMN meta TEXT")
    conn.execute("DROP TABLE IF EXISTS sessions")
    conn.execute("DELETE FROM ai_cache")   # answers may depend on old role logic


def init_db() -> None:
    from auth import hash_password  # local import avoids a circular import

    _migrate_users_to_roles()
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        admin_id, agent_id = _ensure_system_roles(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = [("admin", "Admin", admin_id, "admin123")]
            users += [(f"agent_{l.lower()}", f"Agent {l}", agent_id, "agent123") for l in DEMO_AGENT_LETTERS]
            if SEED_DEMO_DATA:
                viewer = _ensure_role(conn, *DEMO_ROLES[0])
                manager = _ensure_role(conn, *DEMO_ROLES[1])
                users += [("viewer", "Riya Viewer", viewer, "viewer123"), ("hr", "Harsh HR", manager, "hr12345")]
            for username, name, rid, pwd in users:
                pw_hash, salt = hash_password(pwd)
                conn.execute("INSERT INTO users(username, display_name, role_id, password_hash, salt) VALUES (?,?,?,?,?)",
                             (username, name, rid, pw_hash, salt))
        if SEED_DEMO_DATA and conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
            _seed_demo_tasks(conn)


def _seed_demo_tasks(conn) -> None:
    admin = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    agents = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users WHERE username LIKE 'agent_%'")}
    if not admin or not all(f"agent_{l.lower()}" in agents for l in DEMO_AGENT_LETTERS):
        return
    admin_id, n = admin[0], now_utc()
    demo = [
        ("agent_a", "Prepare monthly sales report", "Compile September sales data and charts", 2, "High", "In Progress", 40, 4, None),
        ("agent_a", "Update CRM contacts", "Remove duplicate contacts in CRM", 5, "Medium", "Not Started", 0, 3, None),
        ("agent_a", "Vendor invoice reconciliation", "Match vendor invoices with purchase orders", -1, "Critical", "Partially Completed", 60, 6, None),
        ("agent_a", "Client onboarding call notes", "Upload call notes to SharePoint", -3, "Low", "Completed", 100, 1, 4),
        ("agent_b", "Inventory audit - Warehouse 2", "Physical stock count and variance report", 1, "Critical", "In Progress", 30, 8, None),
        ("agent_b", "Draft SOP for returns", "Document the new returns workflow", 7, "Medium", "Not Started", 0, 5, None),
        ("agent_b", "Weekly stock email", "Send weekly stock summary", -2, "Low", "Completed", 100, 1, 2),
        ("agent_c", "Customer complaint follow-ups", "Close 15 open complaint tickets", 0.5, "High", "Partially Completed", 70, 3, None),
        ("agent_c", "Quarterly KPI deck", "Slides for Q3 business review", -2, "High", "Completed", 100, 4, 1),
        ("agent_d", "Training material review", "Review the onboarding training module", 3, "Low", "Not Started", 0, 2, None),
        ("agent_d", "Supplier contract renewal", "Waiting for legal approval", 4, "Medium", "On Hold", 20, 3, None),
        ("agent_e", "Payment gateway testing", "UAT for the new payment gateway", -0.5, "Critical", "In Progress", 50, 6, None),
        ("agent_e", "Refund policy FAQ", "Update FAQ page", -4, "Medium", "Completed", 100, 2, 5),
        ("agent_f", "Social media calendar", "Plan November social posts", 10, "Medium", "Completed", 100, 2, 0),
    ]
    for uname, title, desc, days, prio, status, progress, est, done_ago in demo:
        cur = conn.execute(
            """INSERT INTO tasks(title, description, assigned_to, created_by, created_at, deadline, priority,
               status, progress, estimated_hours, completed_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (title, desc, agents[uname], admin_id, to_iso(n - timedelta(days=6)), to_iso(n + timedelta(days=days)),
             prio, status, progress, est, to_iso(n - timedelta(days=done_ago, hours=2)) if done_ago is not None else None,
             to_iso(n)))
        conn.execute("INSERT INTO task_updates(task_id, user_id, action, status, progress, note, created_at) VALUES (?,?,?,?,?,?,?)",
                     (cur.lastrowid, admin_id, "created", "Not Started", 0, "Task created and assigned", to_iso(n - timedelta(days=6))))
