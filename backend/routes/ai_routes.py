"""Two separate bots: /api/ai/admin/*  (admins only)  and  /api/ai/agent/*  (agents only)."""
from flask import Blueprint, request, jsonify, g

from auth import require_role
from ai import assistant, cache
from ai.tools import resolve_action

admin_bp = Blueprint("ai_admin", __name__, url_prefix="/api/ai/admin")
agent_bp = Blueprint("ai_agent", __name__, url_prefix="/api/ai/agent")


def _register(bp, role):
    @bp.post("/chat", endpoint=f"{role}_chat")
    @require_role(role)
    def chat():
        return jsonify(assistant.chat(g.user, (request.get_json(silent=True) or {}).get("message", "")))

    @bp.get("/history", endpoint=f"{role}_history")
    @require_role(role)
    def history():
        return jsonify(assistant.get_history(g.user))

    @bp.delete("/history", endpoint=f"{role}_clear")
    @require_role(role)
    def clear():
        assistant.clear_history(g.user.id)
        return jsonify({"ok": True})


_register(admin_bp, "admin")
_register(agent_bp, "agent")


@admin_bp.post("/actions/<action_id>/confirm")
@require_role("admin")
def confirm_action(action_id):
    return jsonify(resolve_action(g.user, action_id, confirm=True))


@admin_bp.post("/actions/<action_id>/cancel")
@require_role("admin")
def cancel_action(action_id):
    return jsonify(resolve_action(g.user, action_id, confirm=False))


@admin_bp.get("/stats")
@require_role("admin")
def stats():
    return jsonify(assistant.usage_stats(7))


@admin_bp.delete("/cache")
@require_role("admin")
def clear_cache():
    cache.clear()
    return jsonify({"ok": True})
