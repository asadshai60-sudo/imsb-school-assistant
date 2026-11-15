(() => {
  // Public website: content now comes from the backend API (shared database),
  // so updates published by the school admin are visible to every visitor.
  const state = { homework: [], exams: [], notices: [], photos: {} };
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const prettyDate = (value) => { if (!value) return "Date not set"; const d = new Date(value + "T00:00:00"); return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}); };
  const empty = (message) => `<div class="empty-state">${message}</div>`;
  const getJSON = async (url) => { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); };

  function renderHomework() {
    const list = document.getElementById("homeworkList"); if (!list) return;
    const selected = document.getElementById("homeworkClass").value;
    const items = state.homework.filter(x => selected === "All" || x.className === selected);
    list.innerHTML = items.length ? items.map(x=>`<div class="data-item"><div class="data-date">${escapeHTML(x.className)}</div><div class="data-content"><strong>${escapeHTML(x.subject)}</strong><small>Due: ${escapeHTML(prettyDate(x.dueDate))}</small><p>${escapeHTML(x.details)}</p></div></div>`).join("") : empty("No homework has been published for this selection.");
  }
  function renderExams() {
    const list = document.getElementById("examList"); if (!list) return;
    const items = [...state.exams].sort((a,b)=>(a.examDate||"").localeCompare(b.examDate||""));
    list.innerHTML = items.length ? items.map(x=>`<div class="data-item"><div class="data-date">${escapeHTML(prettyDate(x.examDate))}</div><div class="data-content"><strong>${escapeHTML(x.examName)} · ${escapeHTML(x.subject)}</strong><small>${escapeHTML(x.className)}</small>${x.details?`<p>${escapeHTML(x.details)}</p>`:""}</div></div>`).join("") : empty("No examination schedule has been published yet.");
  }
  function renderNotices() {
    const list = document.getElementById("noticeList"); if (!list) return;
    list.innerHTML = state.notices.length ? state.notices.map(x=>`<div class="notice-item"><strong>${escapeHTML(x.title)}</strong><small>${escapeHTML(prettyDate(x.date))}</small><p>${escapeHTML(x.details)}</p></div>`).join("") : empty("There are no school notices at the moment.");
  }
  function renderPhotos() {
    Object.entries(state.photos).forEach(([id,src])=>{ const el=document.getElementById(id); if(el){ el.style.backgroundImage=`url("${src}")`; el.style.backgroundSize="cover"; el.style.backgroundPosition="center"; const content=el.querySelector(".placeholder-content"); if(content) content.style.display="none"; } });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("year").textContent = new Date().getFullYear();
    document.getElementById("homeworkClass").addEventListener("change", renderHomework);
    document.querySelectorAll(".class-card").forEach(card=>card.addEventListener("click",()=>{ const sel=document.getElementById("homeworkClass"); sel.value=card.dataset.class; renderHomework(); }));
    const toggle=document.getElementById("menuToggle"), nav=document.getElementById("mainNav");
    toggle.addEventListener("click",()=>{ const open=nav.classList.toggle("open"); toggle.setAttribute("aria-expanded",String(open)); });
    nav.querySelectorAll("a").forEach(a=>a.addEventListener("click",()=>{ nav.classList.remove("open"); toggle.setAttribute("aria-expanded","false"); }));

    try {
      const [homework, exams, notices, photos] = await Promise.all([
        getJSON("/api/homework"), getJSON("/api/exams"), getJSON("/api/notices"), getJSON("/api/photos")
      ]);
      state.homework = homework; state.exams = exams; state.notices = notices; state.photos = photos;
    } catch (e) {
      // Backend unreachable (e.g. opening the file directly): show empty states.
    }
    renderHomework(); renderExams(); renderNotices(); renderPhotos();
  });
})();
