"""Central configuration. Values come from environment variables or backend/.env."""
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE per line, inline ' #' comments allowed)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0]
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _jwt_secret() -> str:
    if os.getenv("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    f = BASE_DIR / ".jwt_secret"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


# --- Auth (JWT) --------------------------------------------------------------
JWT_SECRET = _jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "taskpilot"
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
MIN_PASSWORD_LEN = 6

# --- AI (Groq) -----------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT_SEC = 60
AI_REASONING_EFFORT = os.getenv("AI_REASONING_EFFORT", "low")
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "900"))
MAX_TOOL_ROUNDS = 5
CHAT_CONTEXT_MESSAGES = 4
HISTORY_MSG_MAX_CHARS = 300
TOOL_RESULT_MAX_CHARS = 4000
SNAPSHOT_MAX_ROWS = int(os.getenv("SNAPSHOT_MAX_ROWS", "60"))
AI_ACTION_EXPIRY_MIN = 15
AI_USER_MSGS_PER_MIN = int(os.getenv("AI_USER_MSGS_PER_MIN", "8"))
AI_MAX_RETRY_WAIT_SEC = 20
AI_INSTANT_ANSWERS = os.getenv("AI_INSTANT_ANSWERS", "1") == "1"
AI_CACHE_TTL_MIN = int(os.getenv("AI_CACHE_TTL_MIN", "30"))

# --- App -------------------------------------------------------------------------
DB_PATH = os.getenv("TASK_DB", str(BASE_DIR / "taskpilot.db"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5000"))
LOCAL_TZ = ZoneInfo(os.getenv("APP_TZ", "Asia/Kolkata"))
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "1") == "1"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")
DEADLINE_WARNING_HOURS = 24
WATCHER_INTERVAL_SEC = 300

# --- Domain ----------------------------------------------------------------------
STATUS_NOT_STARTED = "Not Started"
STATUS_IN_PROGRESS = "In Progress"
STATUS_PARTIAL = "Partially Completed"
STATUS_ON_HOLD = "On Hold"
STATUS_COMPLETED = "Completed"
STATUSES = [STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_PARTIAL, STATUS_ON_HOLD, STATUS_COMPLETED]
PRIORITIES = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
DEMO_AGENT_LETTERS = ["A", "B", "C", "D", "E", "F"]
