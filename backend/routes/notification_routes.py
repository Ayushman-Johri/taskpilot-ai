from flask import Blueprint, jsonify, g

from auth import require_role
import notifications

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@require_role()
def list_notifications():
    return jsonify(notifications.list_for_user(g.user.id))


@bp.post("/<int:notification_id>/read")
@require_role()
def read_one(notification_id):
    notifications.mark_read(g.user.id, notification_id)
    return jsonify({"ok": True})


@bp.post("/read-all")
@require_role()
def read_all():
    notifications.mark_all_read(g.user.id)
    return jsonify({"ok": True})
