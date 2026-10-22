(function () {
  const form = document.getElementById("login-form"), alertBox = document.getElementById("login-alert");
  const btn = document.getElementById("login-btn"), themeBtn = document.getElementById("theme-btn");
  const paint = () => (themeBtn.textContent = document.documentElement.dataset.theme === "dark" ? "☀️" : "🌙");
  paint(); themeBtn.addEventListener("click", () => { toggleTheme(); paint(); });
  const showAlert = (msg) => { alertBox.textContent = msg; alertBox.hidden = false; form.classList.remove("shake"); void form.offsetWidth; form.classList.add("shake"); };
  if (new URLSearchParams(location.search).get("expired")) showAlert("Your session expired. Please sign in again.");
  if (Session.token && Session.user) { window.location.replace("/app.html"); return; }
  document.getElementById("pw-toggle").addEventListener("click", (e) => {
    const p = form.password; p.type = p.type === "password" ? "text" : "password"; e.target.textContent = p.type === "password" ? "Show" : "Hide";
  });
  document.querySelectorAll(".demo-chips .chip").forEach((c) => c.addEventListener("click", () => { form.username.value = c.dataset.u; form.password.value = c.dataset.p; btn.focus(); }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); alertBox.hidden = true; btn.disabled = true; btn.textContent = "Signing in...";
    try {
      const res = await api("/api/auth/login", { method: "POST", body: { username: form.username.value.trim(), password: form.password.value } });
      Session.save(res.token, res.user, res.expires_at);
      document.body.classList.add("leaving"); setTimeout(() => window.location.replace(res.home), 200);
    } catch (err) { showAlert(err.message); } finally { btn.disabled = false; btn.textContent = "Sign in"; }
  });
})();
