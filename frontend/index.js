// KIRO diagnostics tab for the Minishop admin user card (frontend host API v1).
const API = "/api/admin/kiro-diagnostics/users/";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const gib = (bytes) => {
  const n = Number(bytes || 0);
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} ГБ`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} МБ`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} КБ`;
  return `${n} Б`;
};

const flag = (cc) =>
  cc && /^[A-Za-z]{2}$/.test(cc)
    ? String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)))
    : "";

const when = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  let ago;
  if (diff < 0) ago = "";
  else if (diff < 90) ago = "только что";
  else if (diff < 3600) ago = `${Math.round(diff / 60)} мин назад`;
  else if (diff < 86400 * 2) ago = `${Math.round(diff / 3600)} ч назад`;
  else ago = `${Math.round(diff / 86400)} дн назад`;
  const abs = d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
  return ago ? `${abs} <span class="kd-muted">(${ago})</span>` : abs;
};

const bar = (used, limit) => {
  if (!limit) return `<span>${gib(used)} <span class="kd-muted">/ без лимита</span></span>`;
  const pct = Math.min(100, Math.round((Number(used) / Number(limit)) * 100));
  const cls = pct >= 100 ? "kd-bad" : pct >= 80 ? "kd-warn" : "kd-ok";
  return `<div class="kd-bar"><div class="kd-fill ${cls}" style="width:${pct}%"></div></div>
    <span>${gib(used)} / ${gib(limit)} <span class="kd-muted">(${pct}%)</span></span>`;
};

const row = (label, value) => `<div class="kd-row"><span class="kd-label">${esc(label)}</span><span class="kd-value">${value}</span></div>`;

const STYLE = `
.kd{display:flex;flex-direction:column;gap:12px;color:var(--text);font-size:14px;min-width:0;max-width:100%}
.kd [data-body]{display:flex;flex-direction:column;gap:12px;min-width:0}
.kd-card{border:1px solid var(--border);border-radius:var(--radius,12px);padding:12px 14px;background:var(--bg);min-width:0;overflow-x:auto}
.kd-card h4{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.kd-row{display:flex;justify-content:space-between;gap:12px;padding:3px 0;align-items:center}
.kd-label{color:var(--muted);flex-shrink:0}
.kd-value{text-align:right;min-width:0;overflow-wrap:anywhere}
.kd-muted{color:var(--muted)}
.kd-warn-list{display:flex;flex-direction:column;gap:6px}
.kd-w{padding:6px 10px;border-radius:8px;border-left:3px solid}
.kd-w.error{border-color:#e5484d;background:rgba(229,72,77,.10)}
.kd-w.warn{border-color:#f5a524;background:rgba(245,165,36,.10)}
.kd-w.info{border-color:var(--accent);background:rgba(127,127,127,.08)}
.kd-okmsg{padding:6px 10px;border-radius:8px;border-left:3px solid #30a46c;background:rgba(48,164,108,.10)}
.kd-bar{height:6px;border-radius:3px;background:rgba(127,127,127,.2);overflow:hidden;margin:4px 0}
.kd-fill{height:100%}.kd-ok{background:#30a46c}.kd-warn{background:#f5a524}.kd-bad{background:#e5484d}
.kd-table{width:100%;border-collapse:collapse;font-size:13px}
.kd-table td,.kd-table th{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top;overflow-wrap:anywhere}
.kd-table th{color:var(--muted);font-weight:500;white-space:nowrap}
.kd-nw{white-space:nowrap}
.kd a{color:var(--accent)}
.kd-tag{display:inline-block;padding:1px 6px;margin:1px;border-radius:6px;border:1px solid var(--border);font-size:12px}
.kd-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.kd-btn{border:1px solid var(--border);background:transparent;color:var(--text);border-radius:8px;padding:4px 10px;cursor:pointer}
.kd-btn:disabled{opacity:.5;cursor:default}
.kd-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px;min-width:0}
.kd-grid>*{min-width:0}
`;

function render(data) {
  const w = data.warnings || [];
  const warnings = w.length
    ? `<div class="kd-warn-list">${w.map((x) => `<div class="kd-w ${esc(x.level)}">${esc(x.text)}</div>`).join("")}</div>`
    : `<div class="kd-okmsg">Проблем не найдено</div>`;

  const s = data.shop || {};
  const sub = data.subscription;
  const p = data.panel;

  const shopCard = `<div class="kd-card"><h4>Магазин</h4>
    ${row("ID", `${esc(s.user_id)} <span class="kd-muted">${esc(s.minishop_id || "")}</span>`)}
    ${row("Telegram", s.telegram_id ? `<a href="tg://user?id=${esc(s.telegram_id)}">${esc(s.telegram_id)}</a>${s.username ? " @" + esc(s.username) : ""}` : "—")}
    ${row("Регистрация", when(s.registered_at))}
    ${sub ? row("Тариф", `${esc(sub.tariff || "—")}${sub.active ? "" : ' <span class="kd-muted">(неактивна)</span>'}`) : ""}
    ${sub ? row("Действует до", when(sub.end_date)) : ""}
    ${sub ? row("Автопродление", sub.auto_renew ? "вкл" : "выкл") : ""}
    ${sub ? `<div class="kd-row"><span class="kd-label">Трафик</span></div>${bar(sub.traffic_used, sub.traffic_limit)}` : ""}
    ${sub && (sub.premium_limit || sub.premium_used) ? `<div class="kd-row"><span class="kd-label">Premium (белые списки)</span><span class="kd-value">${sub.premium_unlimited ? "безлимит" : sub.premium_limited ? "лимит" : "доступ открыт"}</span></div>${bar(sub.premium_used, sub.premium_unlimited ? 0 : sub.premium_limit)}` : ""}
  </div>`;

  let panelCards = `<div class="kd-card"><h4>Панель Remnawave</h4><span class="kd-muted">Нет данных из панели</span></div>`;
  if (p) {
    const last = p.last_node
      ? `${flag(p.last_node.country)} ${esc(p.last_node.name)} ${p.last_node.online ? "" : '<span class="kd-muted">(офлайн)</span>'}`
      : "—";
    const panelCard = `<div class="kd-card"><h4>Панель Remnawave</h4>
      ${row("Статус", esc(p.status || "—"))}
      ${row("Истекает", when(p.expire_at))}
      ${row("Был онлайн", when(p.online_at))}
      ${row("Последняя нода", last)}
      ${row("Первое подключение", when(p.first_connected_at))}
      <div class="kd-row"><span class="kd-label">Трафик в панели</span></div>${bar(p.traffic_used, p.traffic_limit)}
      ${row("За всё время", gib(p.traffic_lifetime))}
      ${row("Сквады", (p.squads || []).map((x) => `<span class="kd-tag">${esc(x)}</span>`).join("") || "—")}
    </div>`;

    const accessible = (p.accessible_nodes || []).length
      ? `<table class="kd-table"><tr><th>Нода</th><th>Инбаунды</th></tr>${p.accessible_nodes
          .map((n) => `<tr><td>${flag(n.country)} ${esc(n.name)}${n.online ? "" : ' <span class="kd-muted">офлайн</span>'}</td><td>${(n.inbounds || []).map((i) => `<span class="kd-tag">${esc(i)}</span>`).join("")}</td></tr>`)
          .join("")}</table>`
      : `<span class="kd-muted">Нет доступных нод</span>`;

    const usage = (rows) =>
      rows && rows.length
        ? `<table class="kd-table">${rows.map((r) => `<tr><td>${flag(r.country)} ${esc(r.name)}</td><td style="text-align:right">${gib(r.bytes)}</td></tr>`).join("")}</table>`
        : `<span class="kd-muted">Нет трафика</span>`;

    const devices = (p.devices || []).length
      ? `<table class="kd-table"><tr><th>Устройство</th><th>Приложение</th><th>Последний раз</th></tr>${p.devices
          .map((d) => `<tr><td>${esc([d.platform, d.os].filter(Boolean).join(" "))}<br><span class="kd-muted">${esc(d.model || "")}</span></td><td>${esc(d.app || "—")}</td><td>${when(d.last_seen)}</td></tr>`)
          .join("")}</table>`
      : `<span class="kd-muted">Нет устройств</span>`;

    const history = (p.sub_requests || []).length
      ? `<table class="kd-table"><tr><th>Когда</th><th>IP</th><th>Приложение</th></tr>${p.sub_requests
          .map((h) => `<tr><td>${when(h.at)}</td><td class="kd-nw">${esc(h.ip || "—")}</td><td>${esc(h.app || "—")}</td></tr>`)
          .join("")}</table>`
      : `<span class="kd-muted">Запросов не было</span>`;

    panelCards = `${panelCard}
      <div class="kd-card"><h4>Доступные ноды и инбаунды</h4>${accessible}</div>
      <div class="kd-card"><h4>Трафик по нодам: 7 дней</h4>${usage(p.usage_week)}<h4 style="margin-top:10px">С начала месяца</h4>${usage(p.usage_month)}</div>
      <div class="kd-card"><h4>Устройства (HWID ${esc((p.devices || []).length)}${p.hwid_limit ? " / " + esc(p.hwid_limit) : ""})</h4>${devices}</div>
      <div class="kd-card"><h4>Запросы подписки</h4>${history}</div>`;
  }

  const payments = (data.payments || []).length
    ? `<table class="kd-table"><tr><th>Дата</th><th>Сумма</th><th>Статус</th></tr>${data.payments
        .map((x) => `<tr><td>${when(x.created_at)}</td><td>${esc(x.amount)} ${esc(x.currency)}<br><span class="kd-muted">${esc(x.provider)}${x.funding_source && x.funding_source !== "external" ? " · " + esc(x.funding_source) : ""}</span></td><td class="kd-nw">${esc(x.status)}</td></tr>`)
        .join("")}</table>`
    : `<span class="kd-muted">Платежей нет</span>`;

  return `${warnings}<div class="kd-grid">${shopCard}${panelCards}<div class="kd-card"><h4>Последние платежи</h4>${payments}</div></div>`;
}

function userRef(props) {
  const u = props && props.user;
  if (!u) return "";
  const id = u.user_id ?? u.id ?? "";
  return String(id);
}

async function load(state) {
  const ref = userRef(state.props);
  if (!ref || state.loading) return;
  state.loading = true;
  state.button.disabled = true;
  state.status.textContent = "Загрузка…";
  try {
    const res = await fetch(API + encodeURIComponent(ref), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (state.disposed) return;
    state.body.innerHTML = render(data);
    state.loadedRef = ref;
    state.status.textContent = `Обновлено ${new Date(data.generated_at).toLocaleTimeString("ru-RU")}`;
  } catch (err) {
    if (!state.disposed) {
      state.status.textContent = "";
      state.body.innerHTML = `<div class="kd-w error">Не удалось загрузить диагностику: ${esc(err.message || err)}</div>`;
    }
  } finally {
    state.loading = false;
    state.button.disabled = false;
  }
}

export function mountView(view, target, props) {
  const root = document.createElement("div");
  root.className = "kd";
  root.innerHTML = `<style>${STYLE}</style>
    <div class="kd-head"><span class="kd-muted" data-status></span><button type="button" class="kd-btn">Обновить</button></div>
    <div data-body><span class="kd-muted">Откройте вкладку, чтобы загрузить данные</span></div>`;
  target.replaceChildren(root);
  const state = {
    view,
    props,
    root,
    body: root.querySelector("[data-body]"),
    status: root.querySelector("[data-status]"),
    button: root.querySelector("button"),
    loading: false,
    loadedRef: "",
    disposed: false,
  };
  state.button.addEventListener("click", () => load(state));
  if (props.active !== false) load(state);
  return state;
}

export function updateView(state, props) {
  state.props = props;
  const ref = userRef(props);
  if (props.active !== false && ref && ref !== state.loadedRef) load(state);
}

export function unmountView(state) {
  if (!state) return;
  state.disposed = true;
  state.root.remove();
}
