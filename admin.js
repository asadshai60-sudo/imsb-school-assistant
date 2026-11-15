(() => {
  // Admin dashboard: talks to the backend API. Publishing/deleting requires
  // a logged-in session (see /api/login in server.py).
  let loggedIn = false;
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const date = v => { if (!v) return "Date not set"; const d = new Date(v + "T00:00:00"); return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}); };

  async function api(url, options = {}) {
    const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
    if (r.status === 401) { loggedIn = false; updateLoginUI(); throw new Error("Login required"); }
    if (!r.ok) { let msg = "Request failed"; try { msg = (await r.json()).error || msg; } catch {} throw new Error(msg); }
    return r.json();
  }
  const getJSON = (url) => api(url);

  function updateLoginUI() {
    const status = document.getElementById("loginStatus");
    const form = document.getElementById("loginForm");
    const logout = document.getElementById("logoutBtn");
    if (loggedIn) {
      status.textContent = "You are logged in. You can publish and delete content below.";
      form.style.display = "none"; logout.style.display = "";
    } else {
      status.textContent = "You are not logged in. Enter the admin password to publish or delete content.";
      form.style.display = ""; logout.style.display = "none";
    }
  }
  function needLogin() {
    if (loggedIn) return true;
    alert("Please login first with the admin password (top of this page).");
    document.getElementById("loginCard").scrollIntoView({ behavior: "smooth" });
    return false;
  }

  function renderList(target, items, labelFn, kind) {
    const el = document.getElementById(target);
    el.innerHTML = items.length ? items.map(x => `<div class="manage-row"><div><strong>${labelFn(x)}</strong><small>${esc(x.details || "")}</small></div><button class="delete-btn" data-delete="${esc(x.id)}" data-kind="${kind}">Delete</button></div>`).join("") : '<div class="empty-state">Nothing published yet.</div>';
  }
  async function refresh() {
    try {
      const [homework, exams, notices] = await Promise.all([getJSON("/api/homework"), getJSON("/api/exams"), getJSON("/api/notices")]);
      renderList("adminHomeworkList", homework, x => `${esc(x.className)} · ${esc(x.subject)} · Due ${esc(date(x.dueDate))}`, "homework");
      renderList("adminExamList", exams, x => `${esc(x.examName)} · ${esc(x.className)} · ${esc(x.subject)} · ${esc(date(x.examDate))}`, "exams");
      renderList("adminNoticeList", notices, x => `${esc(x.title)} · ${esc(date(x.date))}`, "notices");
    } catch (e) {
      document.getElementById("adminHomeworkList").innerHTML = '<div class="empty-state">Could not load data. Is the backend server running?</div>';
    }
  }

  function bindForm(formId, kind) {
    document.getElementById(formId).addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!needLogin()) return;
      const data = Object.fromEntries(new FormData(e.currentTarget).entries());
      try {
        await api(`/api/${kind}`, { method: "POST", body: JSON.stringify(data) });
        e.currentTarget.reset(); refresh(); alert("Published. It is now visible on the public website for all visitors.");
      } catch (err) { alert(err.message); }
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll(".admin-tab").forEach(btn => btn.addEventListener("click", () => {
      document.querySelectorAll(".admin-tab").forEach(x => x.classList.toggle("active", x === btn));
      document.querySelectorAll(".admin-panel").forEach(x => x.classList.toggle("active", x.id === btn.dataset.tab));
    }));

    // Login / logout
    try { loggedIn = !!(await getJSON("/api/me")).loggedIn; } catch { loggedIn = false; }
    updateLoginUI();
    document.getElementById("loginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const password = new FormData(e.currentTarget).get("password");
      try {
        await api("/api/login", { method: "POST", body: JSON.stringify({ password }) });
        loggedIn = true; updateLoginUI(); e.currentTarget.reset(); alert("Logged in successfully.");
      } catch { alert("Wrong password. Please try again."); }
    });
    document.getElementById("logoutBtn").addEventListener("click", async () => {
      try { await api("/api/logout", { method: "POST", body: "{}" }); } catch {}
      loggedIn = false; updateLoginUI();
    });

    bindForm("homeworkForm", "homework");
    bindForm("examForm", "exams");
    bindForm("noticeForm", "notices");

    document.body.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-delete]"); if (!b) return;
      if (!needLogin()) return;
      if (!confirm("Delete this item?")) return;
      try { await api(`/api/${b.dataset.kind}/${encodeURIComponent(b.dataset.delete)}`, { method: "DELETE" }); refresh(); }
      catch (err) { alert(err.message); }
    });

    document.getElementById("photoForm").addEventListener("submit", (e) => {
      e.preventDefault();
      if (!needLogin()) return;
      const f = e.currentTarget.elements.photo.files[0], slot = e.currentTarget.elements.slot.value, status = document.getElementById("photoStatus");
      if (!f) return;
      if (!f.type.startsWith("image/")) { status.textContent = "Please choose an image file."; return; }
      if (f.size > 1.5 * 1024 * 1024) { status.textContent = "Please use an image under 1.5 MB."; return; }
      const reader = new FileReader();
      reader.onload = async () => {
        try { await api("/api/photos", { method: "POST", body: JSON.stringify({ slot, dataUrl: reader.result }) }); status.textContent = "Photo saved on the server. Refresh the public website to see it."; }
        catch (err) { status.textContent = err.message; }
      };
      reader.readAsDataURL(f);
    });

    document.getElementById("resetDemo").addEventListener("click", async () => {
      if (!needLogin()) return;
      if (!confirm("Delete ALL published homework, exams, notices and photos from the server?")) return;
      try { await api("/api/reset", { method: "POST", body: "{}" }); refresh(); document.getElementById("photoStatus").textContent = "All content deleted."; }
      catch (err) { alert(err.message); }
    });

    refresh();
  });
})();
