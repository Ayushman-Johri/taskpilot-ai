"""AI chat engine - cheapest path first, and every path respects the user's role permissions:

  1. guard / topic filter ........ fixed reply            (0 tokens)
  2. instant answer ............... built from DB          (0 tokens)
  3. answer cache ................. same question + data  (0 tokens)
  4. READ  (questions) ............ ONE LLM call, compact data, no tools
  5. ACT   (change requests) ...... LLM + only the tools the role allows"""
import json
import time
from datetime import timedelta
from typing import List

import requests

from auth import User
from config import (GROQ_API_KEY, GROQ_MODEL, GROQ_FALLBACK_MODEL, GROQ_URL, GROQ_TIMEOUT_SEC, MAX_TOOL_ROUNDS,
                    CHAT_CONTEXT_MESSAGES, HISTORY_MSG_MAX_CHARS, TOOL_RESULT_MAX_CHARS, AI_REASONING_EFFORT,
                    AI_MAX_OUTPUT_TOKENS, AI_MAX_RETRY_WAIT_SEC, AI_INSTANT_ANSWERS)
from database import get_conn, audit
from errors import ServiceUnavailable, AppError, TooManyRequests
from utils import now_utc, to_iso, fmt_local
from . import ratelimit, cache, instant
from .context import snapshot, now_line, people_line
from .guard import guard
from .prompts import read_prompt, act_prompt
from .scope import classify, OFF_TOPIC_REPLY, GREETING_REPLY
from .tools import tools_for, execute_tool, ToolContext, get_actions, WRITE_INTENT_RE, READ_ONLY_START

_supports_reasoning_effort = True


# ---- chat history (per user) --------------------------------------------------------
def save_message(user_id: int, role: str, content: str, meta: dict = None) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO chat_messages(user_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
                     (user_id, role, content, json.dumps(meta) if meta else None, to_iso(now_utc())))


def _raw_history(user_id: int, limit: int) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT role, content, meta, created_at FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
                            (user_id, limit)).fetchall()
    return list(reversed(rows))


def get_history(user: User, limit: int = 50) -> List[dict]:
    out = []
    for r in _raw_history(user.id, limit):
        meta = json.loads(r["meta"]) if r["meta"] else {}
        item = {"role": r["role"], "content": r["content"], "time": fmt_local(r["created_at"]),
                "source": meta.get("source"), "tokens": meta.get("tokens")}
        if meta.get("actions"):
            item["actions"] = get_actions(user, meta["actions"])
        out.append(item)
    return out


def clear_history(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_messages WHERE user_id=?", (user_id,))
        conn.execute("UPDATE ai_actions SET status='cancelled', result='Chat cleared.' WHERE user_id=? AND status='pending'", (user_id,))


def _context_msgs(user_id: int, n: int) -> list:
    msgs = []
    for r in _raw_history(user_id, n):
        meta = json.loads(r["meta"]) if r["meta"] else {}
        if meta.get("source") in ("guard", "greeting"):
            continue
        text = r["content"]
        msgs.append({"role": r["role"], "content": text[:HISTORY_MSG_MAX_CHARS] + (" …" if len(text) > HISTORY_MSG_MAX_CHARS else "")})
    return msgs


def _last_was_act_question(user_id: int) -> bool:
    rows = _raw_history(user_id, 1)
    if not rows or rows[0]["role"] != "assistant":
        return False
    meta = json.loads(rows[0]["meta"]) if rows[0]["meta"] else {}
    return meta.get("mode") == "act" and rows[0]["content"].rstrip().endswith("?")


def _known_names(user: User) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT display_name, username FROM users WHERE is_active=1").fetchall()
    return [v for r in rows for v in (r["display_name"], r["username"], r["display_name"].split()[0])]


# ---- usage ---------------------------------------------------------------------------------
def _log_usage(user_id: int, source: str, usage: dict = None) -> None:
    usage = usage or {}
    with get_conn() as conn:
        conn.execute("INSERT INTO ai_usage(user_id, source, prompt_tokens, cached_tokens, completion_tokens, created_at) VALUES (?,?,?,?,?,?)",
                     (user_id, source, usage.get("prompt", 0), usage.get("cached", 0), usage.get("completion", 0), to_iso(now_utc())))


def usage_stats(days: int = 7) -> dict:
    since = to_iso(now_utc() - timedelta(days=days))
    with get_conn() as conn:
        rows = conn.execute("SELECT source, COUNT(*) n, SUM(prompt_tokens) p, SUM(cached_tokens) c, SUM(completion_tokens) o "
                            "FROM ai_usage WHERE created_at >= ? GROUP BY source", (since,)).fetchall()
        hits = conn.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0]
    by = {r["source"]: dict(r) for r in rows}
    z = {"n": 0, "p": 0, "c": 0, "o": 0}
    ai, act = by.get("ai", z), by.get("act", z)
    avg = round((ai["p"] or 0) / ai["n"]) if ai["n"] else 1500
    free = sum(by.get(s, z)["n"] for s in ("instant", "cache"))
    total = sum(r["n"] for r in rows)
    return {"days": days, "questions": total, "instant": by.get("instant", z)["n"], "cache": by.get("cache", z)["n"],
            "llm": (ai["n"] or 0) + (act["n"] or 0), "blocked": sum(by.get(s, z)["n"] for s in ("guard", "greeting")),
            "prompt_tokens": (ai["p"] or 0) + (act["p"] or 0), "cached_prompt_tokens": (ai["c"] or 0) + (act["c"] or 0),
            "completion_tokens": (ai["o"] or 0) + (act["o"] or 0), "avg_prompt_tokens": avg,
            "tokens_saved_est": free * avg, "free_pct": round(free / total * 100) if total else 0, "cached_answers": hits}


# ---- Groq --------------------------------------------------------------------------
def _post(payload: dict):
    try:
        return requests.post(GROQ_URL, json=payload, timeout=GROQ_TIMEOUT_SEC,
                             headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise ServiceUnavailable(f"Could not reach the AI service: {e}")


def _call_groq(messages: list, tools: list = None):
    global _supports_reasoning_effort
    if not GROQ_API_KEY:
        raise ServiceUnavailable("AI is not configured. Set GROQ_API_KEY in backend/.env and restart the server.")
    model, attempts, tool_retry = GROQ_MODEL, 0, False
    while True:
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_completion_tokens": AI_MAX_OUTPUT_TOKENS}
        if tools:
            payload["tools"], payload["tool_choice"] = tools, "auto"
        if _supports_reasoning_effort and AI_REASONING_EFFORT:
            payload["reasoning_effort"] = AI_REASONING_EFFORT
        ratelimit.wait_for_budget(ratelimit.estimate_tokens(len(json.dumps(payload, separators=(",", ":"))), AI_MAX_OUTPUT_TOKENS))
        resp = _post(payload)
        ratelimit.update_from_headers(resp.headers)
        if resp.status_code < 400:
            body = resp.json()
            u = body.get("usage") or {}
            return body["choices"][0]["message"], {"prompt": u.get("prompt_tokens", 0), "completion": u.get("completion_tokens", 0),
                                                   "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}
        try:
            err = resp.json().get("error", {}) or {}
        except ValueError:
            err = {"message": resp.text}
        msg = str(err.get("message", ""))
        if resp.status_code == 401:
            raise ServiceUnavailable("Groq rejected the API key. Please check GROQ_API_KEY.")
        if resp.status_code == 400 and "reasoning_effort" in msg and _supports_reasoning_effort:
            _supports_reasoning_effort = False
            continue
        if resp.status_code == 400 and err.get("code") == "tool_use_failed" and not tool_retry:
            tool_retry = True
            continue
        if resp.status_code == 413 or "request too large" in msg.lower():
            raise TooManyRequests("This request is too large for the AI's limit. Ask a narrower question or clear the chat.")
        if resp.status_code == 429:
            wait = ratelimit.parse_duration(resp.headers.get("retry-after")) or 5
            attempts += 1
            if wait <= AI_MAX_RETRY_WAIT_SEC and attempts <= 2:
                time.sleep(wait + 0.2)
                continue
            if GROQ_FALLBACK_MODEL and model != GROQ_FALLBACK_MODEL:
                model = GROQ_FALLBACK_MODEL
                continue
            raise TooManyRequests(f"The AI is busy right now (rate limit). Please try again in {int(wait) + 1} seconds.", retry_after=int(wait) + 1)
        if resp.status_code >= 500 and attempts < 1:
            attempts += 1
            time.sleep(1.5)
            continue
        raise ServiceUnavailable(f"AI service error ({resp.status_code}): {msg[:200]}")


def _clean(text: str) -> str:
    return (text or "").replace("\u202f", " ").replace("\u00a0", " ").strip()


def _add(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in ("prompt", "cached", "completion")}


def _reply(user, message, answer, source, audit_action=None, tokens=None, actions=None, notices=None, changed=False, mode=None) -> dict:
    if audit_action:
        audit(user.id, audit_action, message)
    meta = {"source": source}
    if tokens:
        meta["tokens"] = tokens
    if actions:
        meta["actions"] = [a["id"] for a in actions]
    if mode:
        meta["mode"] = mode
    save_message(user.id, "user", message)
    save_message(user.id, "assistant", answer, meta)
    _log_usage(user.id, source if source in ("instant", "cache", "guard", "greeting") else mode or "ai", tokens)
    return {"answer": answer, "source": source, "tokens": tokens, "actions": actions or [], "notices": notices or [], "changed": changed}


def chat(user: User, message: str) -> dict:
    message = (message or "").strip()
    if not message:
        raise AppError("Please type a question.")
    if len(message) > 1000:
        raise AppError("Message is too long (max 1000 characters).")

    refusal = guard(user, message)
    if refusal:
        return _reply(user, message, refusal, "guard", "ai_access_denied")
    topic = classify(message, _known_names(user))
    if topic == "off_topic":
        return _reply(user, message, OFF_TOPIC_REPLY, "guard", "ai_off_topic")
    if topic == "greeting":
        return _reply(user, message, GREETING_REPLY, "greeting")

    tools = tools_for(user)
    write_tools = [t for t in tools if t["function"]["name"] not in ("get_tasks", "list_roles", "get_audit_log")]
    wants_change = bool(WRITE_INTENT_RE.search(message)) and not (READ_ONLY_START.search(message) and "?" in message)
    act = bool(write_tools) and (wants_change or _last_was_act_question(user.id))

    if not act:
        if AI_INSTANT_ANSWERS:
            text = instant.answer(user, message)
            if text:
                return _reply(user, message, text, "instant")
        hit = cache.get(user, message)
        if hit:
            return _reply(user, message, hit["answer"], "cache", tokens={"saved": hit["tokens_saved"]})

    ratelimit.check_user_limit(user.id)
    audit(user.id, "ai_query", message)

    if not act:
        messages = [{"role": "system", "content": read_prompt(user)}, *_context_msgs(user.id, 2),
                    {"role": "user", "content": f"DATA\n{snapshot(user, message)}\n\nQUESTION: {message}"}]
        msg, usage = _call_groq(messages)
        answer = _clean(msg.get("content")) or "Sorry, I couldn't answer that. Please rephrase."
        if answer.strip('"') != OFF_TOPIC_REPLY:
            cache.put(user, message, answer, usage.get("prompt", 0))
        return _reply(user, message, answer, "ai", tokens=usage, mode="ai")

    ctx, usage, answer = ToolContext(), {}, ""
    messages = [{"role": "system", "content": act_prompt(user)}, *_context_msgs(user.id, CHAT_CONTEXT_MESSAGES),
                {"role": "user", "content": f"{now_line()}\n{people_line(user)}\n\nREQUEST: {message}"}]
    for _ in range(MAX_TOOL_ROUNDS):
        msg, u = _call_groq(messages, tools)
        usage = _add(usage, u)
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = _clean(msg.get("content"))
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"}}
            for c in calls]})
        for c in calls:
            res = execute_tool(user, c["function"]["name"], c["function"].get("arguments"), ctx)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": res[:TOOL_RESULT_MAX_CHARS]})
    if not answer:
        answer = "Done - see the details above." if (ctx.changed or ctx.actions) else "Sorry, I couldn't complete that."
    if ctx.changed:
        cache.clear()
    return _reply(user, message, answer, "ai", tokens=usage, actions=ctx.actions, notices=ctx.notices, changed=ctx.changed, mode="act")
