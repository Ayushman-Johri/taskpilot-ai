# TaskPilot AI v5 – Task Management + AI (Flask + Groq `openai/gpt-oss-120b`)

## Run
```bash
cd backend
pip install -r requirements.txt
copy .env.example .env        # Linux/Mac: cp .env.example .env
# edit .env -> GROQ_API_KEY=gsk_...
python app.py
```
Open http://127.0.0.1:5000 — `admin / admin123`, `agent_a … agent_f / agent123`.
Upgrading? Copy your old `backend/taskpilot.db` here – it is migrated automatically.

## How the AI saves tokens (cheapest path first)
| Step | What happens | Tokens |
|---|---|---|
| 1. Guards | off-topic / other agent's data / greetings → fixed reply | 0 |
| 2. Instant answers (`ai/instant.py`) | summary, overdue, not started, in progress, completed, on hold, due soon, priorities, completion rate, highest pending, workload … built from the DB | 0 |
| 3. Answer cache (`ai/cache.py`) | same question (order/filler-word insensitive) + same data + < 30 min → reuse answer | 0 |
| 4. Read question → LLM | ONE call, no tools, compact pipe-separated data snapshot | ~600–1,500 |
| 5. Change request (admin) → LLM + tools | static tool list, short text tool results | ~1,500–3,000 |

* System prompts and tool lists are **static** and placed first; time, names and data go last →
  Groq prefix-cache hits (cached tokens are cheaper and do not count toward rate limits).
* Any task change invalidates cached answers automatically (data fingerprint).
* Each chat answer shows a tag: ⚡ Instant · ♻ Cached · ✨ AI (tokens used / cached).
* Admin dashboard → **AI efficiency** card: % of 0-token answers, tokens used, tokens saved.

Settings in `.env`: `AI_INSTANT_ANSWERS`, `AI_CACHE_TTL_MIN`, `SNAPSHOT_MAX_ROWS`, `AI_MAX_OUTPUT_TOKENS`,
`AI_REASONING_EFFORT`, `GROQ_FALLBACK_MODEL`.

## Dashboard (v5)
Hero with greeting + quick-ask AI box, clickable KPI cards, 7-day completion chart, team progress donut,
pending-by-priority bars, 7-day deadline calendar, agent workload, "Needs attention" list,
agent performance table, AI efficiency card, recent activity. Light & dark mode.

## Features kept from v4
JWT auth, admin/agent roles (promote/demote/add admin), clickable notifications with task preview,
agent-only progress updates, confirmation cards for deletes/role changes, guardrails, rate-limit handling.
