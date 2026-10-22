"""One assistant endpoint for everyone; WHAT it can see and do comes from the user's role permissions.
Chat history is stored per user, so conversations never mix."""
from flask import Blueprint, request, jsonify, g

from auth import require
from ai import assistant, cache
from ai.tools import resolve_action

bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@bp.post("/chat")
@require("ai.use")
def chat():
    return jsonify(assistant.chat(g.user, (request.get_json(silent=True) or {}).get("message", "")))


@bp.get("/history")
@require("ai.use")
def history():
    return jsonify(assistant.get_history(g.user))


@bp.delete("/history")
@require("ai.use")
def clear():
    assistant.clear_history(g.user.id)
    return jsonify({"ok": True})


@bp.post("/actions/<action_id>/confirm")
@require("ai.use")
def confirm_action(action_id):
    return jsonify(resolve_action(g.user, action_id, confirm=True))


@bp.post("/actions/<action_id>/cancel")
@require("ai.use")
def cancel_action(action_id):
    return jsonify(resolve_action(g.user, action_id, confirm=False))


@bp.get("/stats")
@require("dashboard.team", "audit.view", any_of=True)
def stats():
    return jsonify(assistant.usage_stats(7))


@bp.delete("/cache")
@require("dashboard.team", "roles.manage", any_of=True)
def clear_cache():
    cache.clear()
    return jsonify({"ok": True})
