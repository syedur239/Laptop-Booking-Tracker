/* Smart Laptop Tracker — single-page app (vanilla JS, no build step). */

const S = {
  config: null,
  tab: "dashboard",
  serverOffset: 0,
  dashFilter: "all",
  overview: null,
};

/* ---------------- helpers ---------------- */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body || {}) });

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function serverNow() { return new Date(Date.now() + S.serverOffset); }
function parseTs(ts) { return new Date(String(ts).replace(" ", "T")); }
function pad2(n) { return String(n).padStart(2, "0"); }
function hhmm(d) { return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; }
function dateStr(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }

function fmtDur(min) {
  if (min == null) return "—";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function dayLabel(dstr) {
  const today = dateStr(serverNow());
  const t = parseTs(dstr + " 00:00:00");
  const base = parseTs(today + " 00:00:00");
  const diff = Math.round((t - base) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return t.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function friendlyTs(ts) {
  const d = parseTs(ts);
  return `${dayLabel(dateStr(d))} ${hhmm(d)}`;
}

const STATUS_LABEL = { "available": "Available", "in-use": "In use", "maintenance": "Maintenance" };

/* ---------------- clock ---------------- */

function startClock() {
  const timeEl = document.getElementById("clock-time");
  const dateEl = document.getElementById("clock-date");
  const tick = () => {
    const n = serverNow();
    timeEl.textContent = `${hhmm(n)}:${pad2(n.getSeconds())}`;
    dateEl.textContent = n.toLocaleDateString(undefined, {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
  };
  tick();
  setInterval(tick, 1000);
}

/* ---------------- tabs ---------------- */

const loaders = {
  dashboard: loadDashboard,
  book: renderBookTab,
  bookings: loadBookings,
  history: loadHistory,
  manage: loadManage,
};

function switchTab(name) {
  S.tab = name;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name));
  loaders[name]();
}

function view(html) { document.getElementById("view").innerHTML = html; }
const loading = () => view('<div class="loading">Loading…</div>');

/* ---------------- dashboard ---------------- */

async function loadDashboard(silent) {
  if (!silent) loading();
  try {
    const data = await api("/api/overview");
    S.overview = data;
    renderDashboard(data);
  } catch (e) { if (!silent) view(`<div class="empty">⚠ ${esc(e.message)}</div>`); }
}

function renderDashboard(data) {
  const { stats, laptops, rooms } = data;
  const cards = [
    { n: stats.available, l: "Available now", c: "green" },
    { n: stats.in_use, l: "Out on loan", c: "red" },
    { n: stats.reserved_today, l: "Reserved today", c: "amber" },
    { n: stats.active_overdue, l: "Overdue returns", c: "blue" },
    { n: stats.maintenance, l: "In maintenance", c: "grey" },
  ].map(s => `<div class="stat-card ${s.c}"><div class="num">${s.n}</div><div class="lbl">${s.l}</div></div>`).join("");

  const chips = [["all", "All"], ["available", "Available"], ["in-use", "In use"],
                 ["reserved", "Reserved today"], ["maintenance", "Maintenance"]]
    .map(([k, l]) => `<button class="chip ${S.dashFilter === k ? "active" : ""}" onclick="setFilter('${k}')">${l}</button>`).join("");

  const filtered = laptops.filter((l) => {
    if (S.dashFilter === "all") return true;
    if (S.dashFilter === "reserved") return !!l.next_booking && l.status !== "in-use";
    return l.status === S.dashFilter;
  });

  const grid = filtered.map(laptopCard).join("") ||
    `<div class="empty">No laptops match this filter.</div>`;

  const roomList = rooms.map(r =>
    `<div class="usage-bar-row"><div>${esc(r.room)}</div>
      <div class="usage-bar-track"><div class="usage-bar-fill" style="width:${Math.round(r.count / stats.total * 100)}%"></div></div>
      <div class="muted">${r.count} laptop${r.count === 1 ? "" : "s"}</div></div>`).join("");

  view(`
    <div class="stats-row">${cards}</div>
    <h2 class="section-title">💻 Fleet status <span class="muted small">(auto-refreshes every 30s)</span></h2>
    <div class="filter-chips">${chips}</div>
    <div class="laptop-grid">${grid}</div>
    <h2 class="section-title">📍 Where the laptops are</h2>
    <div class="panel"><div class="usage-bars">${roomList}</div></div>
  `);
}

function laptopCard(l) {
  let meta = "";
  if (l.status === "in-use" && l.current_session) {
    const elapsed = Math.max(1, Math.round((serverNow() - parseTs(l.current_session.checkout_at)) / 60000));
    meta = `<div class="meta">👤 <strong>${esc(l.current_session.teacher)}</strong><br>Out for ${fmtDur(elapsed)} (since ${esc(l.current_session.checkout_at.slice(11, 16))})</div>`;
  } else if (l.status === "maintenance") {
    meta = `<div class="meta">🛠️ ${esc(l.notes || "Under maintenance")}</div>`;
  } else if (l.next_booking) {
    meta = `<div class="meta">🔖 Booked <strong>${esc(l.next_booking.start_time)}–${esc(l.next_booking.end_time)}</strong> · ${esc(l.next_booking.teacher)}</div>`;
  }
  return `<div class="laptop-card ${l.status}">
    <div class="laptop-head"><span class="asset-tag">${esc(l.asset_tag)}</span>
      <span class="badge ${l.status}">${STATUS_LABEL[l.status] || l.status}</span></div>
    <div class="model">${esc(l.model)}</div>
    <div class="room-line">📍 ${esc(l.current_room)}</div>
    ${meta}
  </div>`;
}

function setFilter(k) { S.dashFilter = k; if (S.overview) renderDashboard(S.overview); }

/* ---------------- book tab ---------------- */

function renderBookTab() {
  const cfg = S.config;
  const now = serverNow();
  const startD = new Date(now.getTime());
  startD.setMinutes(startD.getMinutes() < 30 ? 30 : 60, 0, 0);
  const endD = new Date(startD.getTime() + 3600000);

  view(`
    <div class="two-col">
      <div class="panel">
        <h2 class="section-title">🗓️ Book laptops</h2>
        <form id="book-form" class="form-grid" onsubmit="return submitBooking(event)">
          <label class="fld">Teacher
            <input name="teacher" list="teachers-list" placeholder="e.g. ${esc(cfg.teachers[0])}" required maxlength="60" />
          </label>
          <label class="fld">Room
            <select name="room">${cfg.rooms.map(r => `<option ${r === "ICT Office" ? "" : ""}>${esc(r)}</option>`).join("")}</select>
          </label>
          <label class="fld">Date
            <input name="date" type="date" value="${dateStr(now)}" min="${dateStr(now)}" required />
          </label>
          <label class="fld">Number of laptops
            <input name="quantity" type="number" min="1" max="20" value="3" required />
          </label>
          <label class="fld">Start time
            <input name="start_time" type="time" value="${hhmm(startD)}" required />
          </label>
          <label class="fld">End time
            <input name="end_time" type="time" value="${hhmm(endD)}" required />
          </label>
          <div class="full avail-box" id="avail-box">Pick a time slot to check availability…</div>
          <div class="full"><button class="btn primary" type="submit" id="book-btn" style="width:100%">Book laptops ⚡</button></div>
        </form>
      </div>
      <div class="panel">
        <h2 class="section-title">⚙️ How the automation works</h2>
        <div class="usage-bars" style="gap:14px; font-size:14px; color:var(--muted)">
          <p>🤖 <strong>Smart allocation</strong> — the system assigns specific laptops for you, choosing the <em>least-used</em> ones first to balance wear across the fleet.</p>
          <p>🚫 <strong>Conflict protection</strong> — double-booking a laptop is impossible; availability is checked live as you type.</p>
          <p>🕑 <strong>Automatic logging</strong> — check-out and check-in are one click each; every session is recorded with exact start, end and duration.</p>
          <p>⏰ <strong>Overdue detection</strong> — unreturned laptops are flagged automatically, and uncollected bookings expire on their own.</p>
        </div>
      </div>
    </div>
  `);

  const form = document.getElementById("book-form");
  let timer = null;
  const queueCheck = () => { clearTimeout(timer); timer = setTimeout(checkAvailability, 300); };
  form.date.addEventListener("input", queueCheck);
  form.start_time.addEventListener("input", queueCheck);
  form.end_time.addEventListener("input", queueCheck);
  form.quantity.addEventListener("input", queueCheck);
  checkAvailability();
}

async function checkAvailability() {
  const form = document.getElementById("book-form");
  if (!form) return;
  const box = document.getElementById("avail-box");
  const btn = document.getElementById("book-btn");
  const { date, start_time, end_time, quantity } = form;
  if (!date.value || !start_time.value || !end_time.value) return;
  try {
    const q = new URLSearchParams({ date: date.value, start: start_time.value, end: end_time.value });
    const data = await api("/api/availability?" + q);
    const need = parseInt(quantity.value || "1", 10);
    if (data.count === 0) {
      box.className = "full avail-box bad";
      box.textContent = "❌ No laptops free for this slot — try another time.";
      btn.disabled = true;
    } else if (data.count < need) {
      box.className = "full avail-box bad";
      box.textContent = `⚠ Only ${data.count} laptop(s) free for this slot — reduce the quantity.`;
      btn.disabled = true;
    } else {
      box.className = "full avail-box ok";
      box.innerHTML = `✅ <strong>${data.count}</strong> laptops available — smart allocation will pick the least-used ${Math.min(need, data.count)}.`;
      btn.disabled = false;
    }
  } catch (e) {
    box.className = "full avail-box bad";
    box.textContent = "⚠ " + e.message;
    btn.disabled = true;
  }
}

async function submitBooking(ev) {
  ev.preventDefault();
  const f = ev.target;
  const payload = {
    teacher: f.teacher.value.trim(),
    room: f.room.value,
    date: f.date.value,
    start_time: f.start_time.value,
    end_time: f.end_time.value,
    quantity: parseInt(f.quantity.value, 10),
  };
  try {
    const { booking } = await post("/api/bookings", payload);
    toast(`Booked! Allocated: ${booking.laptops.join(", ")} — ${booking.start_time}–${booking.end_time} in ${booking.room}`, "success");
    refreshBadge();
    switchTab("bookings");
  } catch (e) {
    toast(e.message, "error");
    checkAvailability();
  }
  return false;
}

/* ---------------- bookings tab ---------------- */

async function loadBookings(silent) {
  if (!silent) loading();
  try {
    const data = await api("/api/bookings");
    renderBookings(data.bookings);
    updateBadge(data.bookings);
  } catch (e) { if (!silent) view(`<div class="empty">⚠ ${esc(e.message)}</div>`); }
}

function updateBadge(bookings) {
  const n = bookings.filter(b => b.can_checkout || b.overdue).length;
  const el = document.getElementById("bookings-badge");
  el.textContent = n;
  el.classList.toggle("hidden", n === 0);
}

function refreshBadge() { api("/api/bookings").then(d => updateBadge(d.bookings)).catch(() => {}); }

function bookingCard(b) {
  const badges = [`<span class="badge ${b.status}">${b.status}</span>`];
  if (b.overdue) badges.push(`<span class="badge overdue">⏰ Overdue</span>`);
  const tags = b.laptops.map(t => `<span class="tag-chip">${esc(t)}</span>`).join("");
  let actions = "";
  const btns = [];
  if (b.can_checkout) btns.push(`<button class="btn success small" onclick="bookingAction(${b.id},'checkout')">Check out ▸</button>`);
  if (b.can_checkin) btns.push(`<button class="btn primary small" onclick="bookingAction(${b.id},'checkin')">Check in ▸</button>`);
  if (b.can_cancel) btns.push(`<button class="btn danger-outline small" onclick="cancelBooking(${b.id})">Cancel</button>`);
  if (btns.length) actions = `<div class="actions">${btns.join("")}</div>`;
  let hint = "";
  if (b.status === "booked" && !b.can_checkout) {
    const collect = b.start_time;
    hint = `<div class="muted small">Collect from ${collect} (up to ${S.config.checkout_early_minutes} min early)</div>`;
  }
  return `<div class="booking-card ${b.status} ${b.finished ? "finished" : ""}">
    <div class="booking-main">
      <div class="booking-title">${esc(b.teacher)} — ${esc(b.room)} ${badges.join(" ")}</div>
      <div class="muted small">${dayLabel(b.date)} · ${esc(b.start_time)}–${esc(b.end_time)} · ${b.quantity} laptop${b.quantity === 1 ? "" : "s"}</div>
      <div class="booking-tags">${tags}</div>
      ${hint}
    </div>
    ${actions}
  </div>`;
}

function renderBookings(bookings) {
  const actionNeeded = bookings.filter(b => b.overdue || b.can_checkout);
  const active = bookings.filter(b => b.status === "active" && !b.overdue);
  const upcoming = bookings.filter(b => b.status === "booked" && !b.can_checkout);
  const finished = bookings.filter(b => b.finished).sort((a, b2) => (b2.date + b2.end_time).localeCompare(a.date + a.end_time));

  const section = (title, icon, list, emptyMsg) => list.length
    ? `<h2 class="section-title">${icon} ${title} <span class="badge-pill hidden"></span></h2><div class="list">${list.map(bookingCard).join("")}</div>`
    : (emptyMsg ? `<h2 class="section-title">${icon} ${title}</h2><div class="empty">${emptyMsg}</div>` : "");

  view(`
    ${section("Needs action", "🚨", actionNeeded)}
    ${section("Active sessions", "🔴", active)}
    ${section("Upcoming bookings", "🗓️", upcoming)}
    ${section("Finished today", "✅", finished)}
    ${!bookings.length ? '<div class="empty">No bookings yet — head to <strong>Book Laptops</strong> to create one.</div>' : ""}
  `);
}

async function bookingAction(id, action) {
  try {
    await post(`/api/bookings/${id}/${action}`);
    toast(action === "checkout"
      ? "Checked out — laptops marked in use, logging started."
      : "Checked in — session durations logged automatically.", "success");
    loadBookings(true);
  } catch (e) { toast(e.message, "error"); loadBookings(true); }
}

async function cancelBooking(id) {
  if (!confirm("Cancel this booking? The reserved laptops will be released.")) return;
  try {
    await post(`/api/bookings/${id}/cancel`);
    toast("Booking cancelled.", "success");
    loadBookings(true);
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- history tab ---------------- */

async function loadHistory(silent) {
  if (!silent) loading();
  try {
    const data = await api("/api/history");
    renderHistory(data);
  } catch (e) { if (!silent) view(`<div class="empty">⚠ ${esc(e.message)}</div>`); }
}

function renderHistory({ logs, summary }) {
  const cards = [
    { n: summary.sessions, l: "Sessions logged", c: "blue" },
    { n: fmtDur(summary.minutes), l: "Total usage time", c: "green" },
    { n: fmtDur(summary.avg_minutes), l: "Average session", c: "amber" },
  ].map(s => `<div class="stat-card ${s.c}"><div class="num" style="font-size:24px">${s.n}</div><div class="lbl">${s.l}</div></div>`).join("");

  const maxMin = Math.max(1, ...summary.top.map(t => t.minutes));
  const bars = summary.top.map(t =>
    `<div class="usage-bar-row"><div>${esc(t.asset_tag)}</div>
      <div class="usage-bar-track"><div class="usage-bar-fill" style="width:${Math.round(t.minutes / maxMin * 100)}%"></div></div>
      <div class="muted">${fmtDur(t.minutes)} · ${t.sessions}×</div></div>`).join("") ||
    '<div class="muted">No usage recorded yet.</div>';

  const rowsHtml = logs.map(l => `<tr>
      <td>${friendlyTs(l.checkout_at)}</td>
      <td><strong>${esc(l.asset_tag)}</strong></td>
      <td>${esc(l.teacher)}</td>
      <td>${esc(l.room)}</td>
      <td>${l.checkin_at ? friendlyTs(l.checkin_at) : '<span class="badge active">out now</span>'}</td>
      <td>${l.duration_minutes != null ? fmtDur(l.duration_minutes) : "—"}</td>
    </tr>`).join("");

  view(`
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px">
      <h2 class="section-title" style="margin:0">🕑 Usage history — the paper log, automated</h2>
      <a class="btn ghost small" href="/api/history.csv" download>⬇ Export CSV</a>
    </div>
    <div class="stats-row" style="margin-top:14px">${cards}</div>
    <h2 class="section-title">🏆 Most-used laptops</h2>
    <div class="panel"><div class="usage-bars">${bars}</div></div>
    <h2 class="section-title">📖 Full log</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Checked out</th><th>Laptop</th><th>Teacher</th><th>Room</th><th>Returned</th><th>Duration</th></tr></thead>
      <tbody>${rowsHtml || '<tr><td colspan="6" class="muted">No sessions yet.</td></tr>'}</tbody>
    </table></div>
  `);
}

/* ---------------- manage tab ---------------- */

async function loadManage(silent) {
  if (!silent) loading();
  try {
    const data = await api("/api/overview");
    S.overview = data;
    renderManage(data.laptops);
  } catch (e) { if (!silent) view(`<div class="empty">⚠ ${esc(e.message)}</div>`); }
}

function renderManage(laptops) {
  const roomOpts = (current, disabled) =>
    `<select ${disabled ? "disabled" : ""} onchange="moveLaptop(this, this.value)">
      ${S.config.rooms.map(r => `<option ${r === current ? "selected" : ""}>${esc(r)}</option>`).join("")}
    </select>`;

  const rowsHtml = laptops.map(l => {
    const inUse = l.status === "in-use";
    const maint = l.status === "maintenance";
    const btn = maint
      ? `<button class="btn success small" onclick="toggleMaintenance(${l.id}, false)">Return to service</button>`
      : `<button class="btn ghost small" ${inUse ? "disabled" : ""} onclick="toggleMaintenance(${l.id}, true)">Flag maintenance</button>`;
    return `<tr>
      <td><strong>${esc(l.asset_tag)}</strong></td>
      <td>${esc(l.model)}</td>
      <td><span class="badge ${l.status}">${STATUS_LABEL[l.status] || l.status}</span></td>
      <td data-lid="${l.id}">${roomOpts(l.current_room, inUse)}</td>
      <td><input id="note-${l.id}" placeholder="Maintenance note…" value="${esc(l.notes)}" ${maint ? "" : "disabled"} style="min-width:200px"/></td>
      <td>${btn}</td>
    </tr>`;
  }).join("");

  view(`
    <h2 class="section-title">🛠️ Manage fleet</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Asset</th><th>Model</th><th>Status</th><th>Room</th><th>Note</th><th></th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table></div>
    <div class="panel" style="margin-top:18px; font-size:13.5px; color:var(--muted)">
      🤖 <strong>Automation built in:</strong> flagging a laptop for maintenance automatically
      moves its future bookings onto other free laptops, and checked-out laptops report their
      room themselves on return.
    </div>
    <div class="panel" style="margin-top:14px; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap">
      <div><strong>Demo data</strong><div class="muted small">Reset the fleet, bookings and logs back to a fresh demo state.</div></div>
      <button class="btn danger-outline" onclick="resetDemo()">Reset demo data</button>
    </div>
  `);
}

async function toggleMaintenance(id, on) {
  const noteEl = document.getElementById(`note-${id}`);
  try {
    const res = await post(`/api/laptops/${id}/maintenance`, {
      on, notes: noteEl ? noteEl.value : "",
    });
    toast(on ? "Laptop flagged for maintenance." : "Laptop back in service.", "success");
    (res.messages || []).forEach((m) => toast(m, m.startsWith("⚠") ? "error" : "info"));
    loadManage(true);
    refreshBadge();
  } catch (e) { toast(e.message, "error"); }
}

async function moveLaptop(sel, room) {
  const lid = sel.closest("td").dataset.lid;
  try {
    await post(`/api/laptops/${lid}/move`, { room });
    toast(`Moved to ${room}.`, "success");
  } catch (e) { toast(e.message, "error"); loadManage(true); }
}

async function resetDemo() {
  if (!confirm("Reset ALL data back to the fresh demo state?")) return;
  try {
    await post("/api/reset");
    toast("Demo data reset.", "success");
    loadManage();
    refreshBadge();
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- init ---------------- */

function fillDatalists(cfg) {
  document.getElementById("teachers-list").innerHTML =
    cfg.teachers.map(t => `<option value="${esc(t)}">`).join("");
  document.getElementById("rooms-list").innerHTML =
    cfg.rooms.map(r => `<option value="${esc(r)}">`).join("");
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (btn) switchTab(btn.dataset.tab);
});

(async function init() {
  try {
    const cfg = await api("/api/config");
    S.config = cfg;
    S.serverOffset = parseTs(cfg.server_time) - Date.now();
    fillDatalists(cfg);
    startClock();
    switchTab("dashboard");
    refreshBadge();
    // Keep live tabs fresh without clobbering the booking form.
    setInterval(() => {
      if (["dashboard", "bookings", "manage"].includes(S.tab)) loaders[S.tab](true);
    }, 30000);
  } catch (e) {
    view(`<div class="empty">⚠ Could not start the app: ${esc(e.message)}</div>`);
  }
})();
