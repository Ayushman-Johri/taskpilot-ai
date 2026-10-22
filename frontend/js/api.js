/* API client + JWT session (sessionStorage = one login per browser tab, so two users in two tabs never mix). */
const API_BASE = "";
const Session = {
  get token() { return sessionStorage.getItem("tp_token"); },
  get user() { try { return JSON.parse(sessionStorage.getItem("tp_user")); } catch { return null; } },
  get expiresAt() { return Number(sessionStorage.getItem("tp_exp") || 0); },
  save(token, user, exp) {
    if (token) sessionStorage.setItem("tp_token", token);
    if (user) sessionStorage.setItem("tp_user", JSON.stringify(user));
    if (exp) sessionStorage.setItem("tp_exp", String(exp));
  },
  clear() { ["tp_token", "tp_user", "tp_exp"].forEach((k) => sessionStorage.removeItem(k)); },
};
class ApiError extends Error {
  constructor(message, status, retryAfter) { super(message); this.status = status; this.retryAfter = retryAfter || 0; }
}
async function api(path, { method = "GET", body } = {}) {
  if (Session.token && Session.expiresAt && Date.now() / 1000 > Session.expiresAt) {
    Session.clear(); window.location.replace("/index.html?expired=1"); throw new ApiError("Session expired", 401);
  }
  const headers = { "Content-Type": "application/json" };
  if (Session.token) headers.Authorization = "Bearer " + Session.token;
  let res;
  try { res = await fetch(API_BASE + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined }); }
  catch { throw new ApiError("Cannot reach the server. Is the backend running?", 0); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    Session.clear(); window.location.replace("/index.html?expired=1"); throw new ApiError(data.error || "Session expired", 401);
  }
  if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status})`, res.status, data.retry_after || Number(res.headers.get("Retry-After") || 0));
  return data;
}
/* Loads the current user (with permissions fresh from the database). */
async function requireLogin() {
  if (!Session.token) { window.location.replace("/index.html"); return null; }
  const me = await api("/api/auth/me");
  Session.save(null, me);
  return me;
}
async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
  Session.clear(); window.location.replace("/index.html");
}
