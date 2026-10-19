from flask import Blueprint, request, jsonify, g

import auth
from database import audit

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    token, user, exp = auth.login(body.get("username"), body.get("password"))
    return jsonify({"token": token, "token_type": "Bearer", "expires_at": exp, "user": user.to_dict(),
                    "home": "/admin.html" if user.is_admin else "/agent.html"})


@bp.post("/logout")
@auth.require_role()
def logout():
    auth.logout(g.token)
    audit(g.user.id, "logout", "")
    return jsonify({"ok": True})


@bp.get("/me")
@auth.require_role()
def me():
    return jsonify(g.user.to_dict())
