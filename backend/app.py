"""TaskPilot AI - Flask backend entry point.   Run:  python app.py  ->  http://127.0.0.1:5000"""
from flask import Flask, jsonify, request, send_from_directory, redirect
from werkzeug.exceptions import HTTPException

from config import FRONTEND_DIR, HOST, PORT, ALLOWED_ORIGINS, GROQ_API_KEY, GROQ_MODEL
from database import init_db
from errors import AppError
from notifications import start_deadline_watcher
from routes import auth_routes, task_routes, dashboard_routes, user_routes, notification_routes, ai_routes


def create_app(start_watcher: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    init_db()
    for bp in (auth_routes.bp, task_routes.bp, dashboard_routes.bp, user_routes.bp, notification_routes.bp, ai_routes.bp):
        app.register_blueprint(bp)

    @app.errorhandler(AppError)
    def handle_app_error(e: AppError):
        body, headers = {"error": e.message}, {}
        if e.retry_after:
            body["retry_after"] = e.retry_after
            headers["Retry-After"] = str(e.retry_after)
        return jsonify(body), e.status_code, headers

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        return (jsonify({"error": e.description}), e.code) if request.path.startswith("/api/") else e

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        app.logger.exception(e)
        return jsonify({"error": "Something went wrong on the server. Please try again."}), 500

    @app.after_request
    def cors(resp):
        origin = request.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Expose-Headers"] = "Retry-After"
        if request.path.endswith((".html", ".js", ".css")) or request.path == "/":
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/api/<path:_any>", methods=["OPTIONS"])
    def preflight(_any):
        return ("", 204)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/admin.html")
    @app.get("/agent.html")
    def old_pages():                      # v5 bookmarks -> new single app page
        return redirect("/app.html")

    @app.get("/<path:path>")
    def frontend(path):
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(FRONTEND_DIR, path)

    if start_watcher:
        start_deadline_watcher()
    return app


if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY is not set - instant answers work, but full AI answers are disabled.")
    print(f"TaskPilot AI v6 | model: {GROQ_MODEL} | open http://{HOST}:{PORT}")
    create_app().run(host=HOST, port=PORT, debug=False, use_reloader=False)
