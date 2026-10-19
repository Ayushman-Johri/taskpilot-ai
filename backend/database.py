"""SQLite access, schema creation/migration and demo seed data.
Swap this module for PostgreSQL / SQL Server in production."""
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from typing import Optional

from config import DB_PATH, SEED_DEMO_DATA, DEMO_AGENT_LETTERS
from utils import now_utc, to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','agent')),
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
    action TEXT NOT NULL, status TEXT, progress INTEGER, note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    task_id INTEGER, type TEXT NOT NULL, ref TEXT, message TEXT NOT NULL,
    created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL, meta TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_actions (
    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), tool TEXT NOT NULL, args TEXT NOT NULL,
    summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
-- Answer cache: same (normalised) question + same data -> reuse answer, 0 tokens
CREATE TABLE IF NOT EXISTS ai_cache (
    scope TEXT NOT NULL, qkey TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
    data_version TEXT NOT NULL, tokens INTEGER NOT NULL DEFAULT 0, hits INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, PRIMARY KEY (scope, qkey)
);
-- Token usage log (for the AI efficiency card)
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


def _columns(conn, table: str) -> set:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn) -> None:
    """Upgrade databases created by older versions (v3 / v4)."""
    if "meta" not in _columns(conn, "chat_messages"):
        conn.execute("ALTER TABLE chat_messages ADD COLUMN meta TEXT")
    if "token_version" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
    conn.execute("DROP TABLE IF EXISTS sessions")


def init_db() -> None:
    from auth import hash_password  # local import avoids a circular import

    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = [("admin", "Admin", "admin", "admin123")]
            users += [(f"agent_{l.lower()}", f"Agent {l}", "agent", "agent123") for l in DEMO_AGENT_LETTERS]
            for username, name, role, pwd in users:
                pw_hash, salt = hash_password(pwd)
                conn.execute("INSERT INTO users(username, display_name, role, password_hash, salt) VALUES (?,?,?,?,?)",
                             (username, name, role, pw_hash, salt))
        if SEED_DEMO_DATA and conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
            _seed_demo_tasks(conn)


def _seed_demo_tasks(conn) -> None:
    admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    agents = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users WHERE role='agent'")}
    if not all(f"agent_{l.lower()}" in agents for l in DEMO_AGENT_LETTERS):
        return
    n = now_utc()
    # (agent, title, description, deadline offset days, priority, status, progress, est. hours, completed days ago)
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
        conn.execute("INSERT INTO task_updates(task_id, user_id, action, status, progress, note, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (cur.lastrowid, admin_id, "created", "Not Started", 0,
                                                "Task created and assigned", to_iso(n - timedelta(days=6))))
