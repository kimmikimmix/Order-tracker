/* Order Tracker — front end.
   Plain DOM and fetch, no build step and no frameworks, so this file can be
   opened and edited by anyone who needs to change a column or a label. */

'use strict';

/* ------------------------------------------------------------------ utils */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

/** FTS returns matches wrapped in [ ], which we turn into highlights. */
function highlight(snippet) {
  return esc(snippet).replace(/\[(.*?)\]/g, '<b>$1</b>');
}

const money = (value, currency) => {
  const n = Number(value || 0);
  const text = n.toLocaleString(undefined, { minimumFractionDigits: 0,
                                             maximumFractionDigits: 0 });
  return currency ? `${text} ${currency}` : text;
};

const cls = status => 's-' + String(status || '').replace(/[^A-Za-z]/g, '');
const acls = alert => 'a-' + String(alert || '').replace(/[^A-Za-z]/g, '');

/* ---- what an order is called ----------------------------------------
   The office thinks in boards, not in sales-order numbers, so the product
   name leads wherever an order is named and the number follows it quietly.
   Orders booked before anybody knew what was being made keep the number as
   their name, which is never empty.  Mirrors headline() on the server. */

function orderName(o) {
  if (!o) return '';
  return (o.product_name || o.product_code || o.order_no || '').toString();
}

function orderSub(o) {
  if (!o) return '';
  const bits = [o.order_no];
  if (o.product_name && o.product_code) bits.push(o.product_code);
  return bits.filter(Boolean).join(' · ');
}

function dayText(days) {
  if (days === null || days === undefined) return '<span style="color:var(--dimmer)">—</span>';
  if (days < 0) return `<span style="color:var(--red)">${days}d late</span>`;
  if (days === 0) return '<span style="color:var(--amber)">today</span>';
  if (days <= 7) return `<span style="color:var(--amber)">${days}d</span>`;
  return `<span style="color:var(--dim)">${days}d</span>`;
}

function bytes(n) {
  if (!n) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

function toast(message, kind = '') {
  const node = document.createElement('div');
  node.className = 'toastmsg ' + kind;
  node.innerHTML = esc(message);
  $('#toast').appendChild(node);
  setTimeout(() => node.remove(), kind === 'err' ? 7000 : 3500);
}

function status(message) { $('#statusmsg').textContent = message; }

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response;
  }
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || 'request failed');
  return data;
}

const postJSON = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/* ------------------------------------------------------------------ state */

const S = {
  view: 'dash',
  boot: null,
  orders: [],
  selected: 0,
  openOrder: null,
  detailTab: 'order',
  mapData: null,
  sort: { key: 'promise_date', dir: 'asc' },
  filters: { status: '', company_id: '', owner: '', alert: '', closed: '1' },
  importFile: null,
  importPreview: null,
};

/* ----------------------------------------------------------------- splash */

const WELCOME = window.__WELCOME__ || { name: '', show: true };
const SPLASH_MIN_MS = 1400;          // long enough to read, short enough to forgive
const splashShownAt = Date.now();
let splashFinished = false;

function dismissSplash(immediately = false) {
  if (splashFinished) return;
  const node = $('#splash');
  if (!node) { splashFinished = true; return; }

  const waited = Date.now() - splashShownAt;
  const remaining = immediately ? 0 : Math.max(0, SPLASH_MIN_MS - waited);
  setTimeout(() => {
    splashFinished = true;
    node.classList.add('gone');
    setTimeout(() => node.remove(), 600);
  }, remaining);
}

function splashError(message) {
  const hint = $('#splashhint');
  const bar = $('#splashbar');
  if (hint) { hint.textContent = message; hint.style.color = 'var(--red)'; }
  if (bar) bar.remove();
}

function setUpSplash() {
  if (!WELCOME.show) {
    splashFinished = true;
    const node = $('#splash');
    if (node) node.remove();
    return;
  }
  const name = $('#splashname');
  if (name) name.textContent = WELCOME.name || '';
  const node = $('#splash');
  if (node) node.addEventListener('click', () => dismissSplash(true));
}

setUpSplash();

/* ------------------------------------------------------------------- boot */

async function boot() {
  try {
    S.boot = await api('/api/bootstrap');
  } catch (err) {
    status('could not reach the server — is run.py still going?');
    toast('Cannot reach the server: ' + err.message, 'err');
    splashError('Cannot reach the server. Is the black window still open?');
    return;
  }
  renderTopStats();
  applyHash();
  dismissSplash();
  tickClock();
  refreshSaved();
  setInterval(tickClock, 1000);
  setInterval(refreshQuietly, 60000);
  setInterval(refreshSaved, 60000);
}

async function reloadBoot() {
  S.boot = await api('/api/bootstrap');
  renderTopStats();
}

async function refreshQuietly() {
  try {
    await reloadBoot();
    if (S.view === 'dash') renderDash();
    // Redrawn so the customers' local times do not sit there going stale.
    if (S.view === 'companies') renderCompanies();
    refreshSaved();
  } catch (err) { /* the server may simply have been stopped */ }
}

function tickClock() {
  const now = new Date();
  $('#clock').textContent =
    now.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short' })
      .toUpperCase() + '  ' + now.toLocaleTimeString();
}

function renderTopStats() {
  const d = S.boot.dashboard;
  const a = d.alerts;
  $('#topstats').innerHTML = `
    <div class="st"><i>OPEN</i><b>${d.open_orders}</b></div>
    <div class="st"><i>VALUE</i><b>${money(d.open_value)}</b></div>
    <div class="st"><i>LATE</i><b style="color:var(--red)">${a['OVERDUE'] || 0}</b></div>
    <div class="st"><i>DUE</i><b style="color:var(--amber)">${a['DUE SOON'] || 0}</b></div>
    <div class="st"><i>DOCS</i><b>${d.document_count}</b></div>`;
  renderNavCounts();
}

/* A count on the nav button itself, so an unread tray or a late follow-up
   is visible from every page rather than only from the dashboard. */
function renderNavCounts() {
  const d = S.boot.dashboard;
  const mail = d.mail || {};
  const cases = d.cases || {};
  const badge = (node, count, colour) => {
    if (!node) return;
    node.textContent = count ? String(count) : '';
    node.style.background = count ? colour : 'transparent';
  };
  badge($('#navmail'), mail.needs_review, 'var(--amber)');
  const folders = d.folders || {};
  badge($('#navfolders'), folders.due, folders.overdue ? 'var(--red)'
                                                       : 'var(--amber)');
  badge($('#navcases'), (cases.overdue || 0) + (cases.late_actions || 0),
        'var(--red)');
}

/* ----------------------------------------------------------------- routes */
/* The address bar mirrors where you are, so a view, a filter or a single
   order can be bookmarked or pasted to a colleague on the same machine. */

const NAV_VIEWS = ['dash', 'graph', 'orders', 'companies', 'inbox',
                   'folders', 'cases', 'docs', 'import', 'setup'];

function setHash(fragment) {
  const next = '#' + fragment;
  if (location.hash !== next) history.replaceState(null, '', next);
}

function applyHash() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, ''));
  if (!raw) { show('dash'); return; }

  /* The order book used to be called the blotter; old bookmarks still work. */
  const head = raw.split('/')[0] === 'blotter' ? 'orders' : raw.split('/')[0];
  const rest = raw.split('/').slice(1).join('/');

  if (head === 'order' && rest) {
    const [orderId, tab] = rest.split('/');
    show('orders');
    openOrder(Number(orderId), tab);
    return;
  }
  if (head === 'new') {
    show('orders');
    newOrderModal(rest);          // #new/spec opens straight on the spec
    return;
  }
  if (head === 'graph') {
    GRAPH.at = rest || '';
    GRAPH.trail = [];
    show('graph');
    return;
  }
  if (head === 'folder' && rest) {
    show('folders');
    openFolder(Number(rest));
    return;
  }
  if (head === 'case' && rest) {
    show('cases');
    openCase(Number(rest));
    return;
  }
  if (head === 'mail' && rest) {
    show('inbox');
    openMail(Number(rest));
    return;
  }
  if (head === 'search' && rest) {
    $('#cmd').value = rest;
    runSearch(rest);
    return;
  }
  show(NAV_VIEWS.includes(head) ? head : 'dash');
}

window.addEventListener('hashchange', applyHash);

/* ------------------------------------------------------------------ views */

function show(view) {
  S.view = view;
  setHash(view);
  $$('#nav button[data-view]').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => v.classList.add('hidden'));
  $('#view-' + view).classList.remove('hidden');

  if (view === 'dash') renderDash();
  if (view === 'orders') loadOrders();
  if (view === 'companies') renderCompanies();
  if (view === 'inbox') renderInbox();
  if (view === 'graph') renderGraph();
  if (view === 'folders') renderFolders();
  if (view === 'cases') renderCases();
  if (view === 'docs') renderDocs();
  if (view === 'import') renderImport();
  if (view === 'setup') renderSetup();
  if (view !== 'dash') MapView.stop();
  if (view !== 'graph') stopGraph();
}

/* ---- dashboard ---- */

function renderDash() {
  const d = S.boot.dashboard;
  const a = d.alerts;
  const mail = d.mail || {};
  const disputes = d.cases || {};
  const el = $('#view-dash');

  const tile = (label, value, sub, kind, onclick) => `
    <div class="tile ${kind || ''} ${onclick ? 'clickable' : ''}"
         ${onclick ? `data-act="${onclick}"` : ''}>
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      <div class="sub">${sub || ''}</div>
    </div>`;

  const maxStatus = Math.max(1, ...d.by_status.map(s => s.count));

  el.innerHTML = `
    ${todayHTML(d.today)}

    ${MapView.html()}

    <div class="tiles">
      ${tile('OPEN ORDERS', d.open_orders, `${d.total_orders} on file`, 'blue', 'open')}
      ${tile('OPEN VALUE', money(d.open_value), 'across all customers', 'green')}
      ${tile('OVERDUE', a['OVERDUE'] || 0, 'past promise date', 'red', 'alert:OVERDUE')}
      ${tile('DUE SOON', a['DUE SOON'] || 0,
             `next ${S.boot.thresholds.due_soon_days} days`, 'amber', 'alert:DUE SOON')}
      ${tile('STALLED', a['STALLED'] || 0,
             `untouched ${S.boot.thresholds.stalled_days}d+`, 'amber', 'alert:STALLED')}
      ${tile('MISSING PO', a['NO PO'] || 0, 'no PO on file', 'red', 'alert:NO PO')}
      ${tile('CUSTOMERS', d.company_count, 'with orders', '', 'companies')}
      ${tile('DOCUMENTS', d.document_count, 'indexed and searchable', '', 'docs')}
      ${tile('MAIL TO CHECK', mail.needs_review || 0,
             `${mail.total || 0} email(s) read`,
             mail.needs_review ? 'amber' : '', 'inbox')}
      ${tile('FOLDERS DUE', (d.folders || {}).due || 0,
             `${(d.folders || {}).open || 0} conversation(s) running`,
             (d.folders || {}).overdue ? 'red'
               : ((d.folders || {}).due ? 'amber' : ''), 'folders')}
      ${tile('OPEN CASES', disputes.open || 0,
             disputes.late_actions
               ? `${disputes.late_actions} action(s) late`
               : `${disputes.open_actions || 0} action(s) outstanding`,
             (disputes.overdue || disputes.late_actions) ? 'red' : '', 'cases')}
    </div>

    <h2 class="sect">Needs attention</h2>
    ${d.attention.length ? `
    <table class="grid">
      <thead><tr>
        <th>PRODUCT</th><th>ORDER</th><th>CUSTOMER</th><th>DESCRIPTION</th><th>STATUS</th>
        <th>PROMISED</th><th class="num">DUE IN</th><th class="num">VALUE</th><th>FLAGS</th>
      </tr></thead>
      <tbody>
        ${d.attention.map(o => `
          <tr data-open="${o.id}">
            <td><b>${esc(orderName(o))}</b></td>
            <td style="color:var(--amber)">${esc(o.order_no)}</td>
            <td>${esc(o.company)}</td>
            <td style="color:var(--dim)">${esc(o.description || '')}</td>
            <td><span class="chip ${cls(o.status)}">${esc(o.status)}</span></td>
            <td>${esc(o.promise_date || '')}</td>
            <td class="num">${dayText(o.days_to_promise)}</td>
            <td class="num">${money(o.value, o.currency)}</td>
            <td>${o.alerts.map(f =>
              `<span class="chip ${acls(f)}">${esc(f)}</span>`).join('')}</td>
          </tr>`).join('')}
      </tbody>
    </table>` : '<div class="empty">Nothing is flagged. Every open order is on track.</div>'}

    <h2 class="sect">Pipeline</h2>
    <table class="grid">
      <tbody>
        ${d.by_status.map(s => `
          <tr data-status="${esc(s.status)}">
            <td style="width:150px"><span class="chip ${cls(s.status)}">${esc(s.status)}</span></td>
            <td class="num" style="width:50px">${s.count}</td>
            <td><div class="bar"><span style="width:${(s.count / maxStatus * 100).toFixed(1)}%"></span></div></td>
          </tr>`).join('')}
      </tbody>
    </table>

    <h2 class="sect">Open business by customer</h2>
    <table class="grid">
      <thead><tr>
        <th>CUSTOMER</th><th class="num">OPEN</th><th class="num">VALUE</th>
        <th class="num">FLAGGED</th><th></th>
      </tr></thead>
      <tbody>
        ${d.by_company.map(c => {
          const top = d.by_company[0].value || 1;
          return `<tr data-company="${esc(c.company)}">
            <td>${esc(c.company)}</td>
            <td class="num">${c.open}</td>
            <td class="num">${money(c.value)}</td>
            <td class="num" style="color:${c.alerts ? 'var(--red)' : 'var(--dimmer)'}">${c.alerts || '—'}</td>
            <td style="width:40%"><div class="bar"><span style="width:${(c.value / top * 100).toFixed(1)}%"></span></div></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;

  loadMap();

  el.onclick = event => {
    const todayRow = event.target.closest('.today [data-link]');
    if (todayRow) {
      const link = todayRow.dataset.link;
      if (NAV_VIEWS.includes(link)) show(link);
      else location.hash = '#' + link;
      return;
    }
    const pin = event.target.closest('.pin[data-company]');
    if (pin) {
      S.filters = { ...S.filters, company_id: pin.dataset.company,
                    alert: '', closed: '0' };
      show('orders');
      return;
    }
    const tileNode = event.target.closest('[data-act]');
    if (tileNode) {
      const act = tileNode.dataset.act;
      if (act === 'open') { S.filters = { ...S.filters, alert: '', closed: '0' }; show('orders'); }
      else if (act.startsWith('alert:')) {
        S.filters = { ...S.filters, alert: act.slice(6), closed: '0' };
        show('orders');
      } else if (act === 'companies') show('companies');
      else if (act === 'docs') show('docs');
      else if (act === 'inbox') show('inbox');
      else if (act === 'cases') show('cases');
      else if (act === 'folders') show('folders');
      return;
    }
    const row = event.target.closest('[data-open]');
    if (row) { openOrder(Number(row.dataset.open)); return; }
    const statusRow = event.target.closest('[data-status]');
    if (statusRow) {
      S.filters = { ...S.filters, status: statusRow.dataset.status, alert: '', closed: '1' };
      show('orders');
      return;
    }
    const companyRow = event.target.closest('[data-company]');
    if (companyRow) {
      const match = S.boot.companies.find(c => c.name === companyRow.dataset.company);
      if (match) {
        S.filters = { ...S.filters, company_id: String(match.id), alert: '', closed: '0' };
        show('orders');
      }
    }
  };
}

/* ---- what needs doing today ---- */

/* The first thing on the first page. Everything that wants attention, from
   wherever it was hiding — the tray, the folders, the case log, the order
   book — with the reason kept, because the reason is most of what tells you
   how long it will take. */
function todayHTML(today) {
  if (!today) return '';
  const when = new Date().toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long' });

  if (!today.total) {
    return `
      <section class="today clear">
        <div class="todayhead">
          <b>TODAY</b><span>${esc(when)}</span>
          <span class="spacer"></span>
          <span class="allclear">nothing is waiting on you</span>
        </div>
        <div class="note">No email to check, no action due, nothing overdue.
          Whatever you do next is your own choice.</div>
      </section>`;
  }

  const line = item => `
    <div class="todayrow ${item.late ? 'late' : ''}" data-link="${esc(item.link)}">
      <span class="tw">${esc(item.when || '')}</span>
      <span class="tt">${esc(item.title)}
        <span class="subtle">${esc(item.detail || '')}</span></span>
      ${item.chip ? `<span class="chip">${esc(item.chip)}</span>` : ''}
    </div>`;

  const SHOWN = 5;
  return `
    <section class="today">
      <div class="todayhead">
        <b>TODAY</b><span>${esc(when)}</span>
        <span class="spacer"></span>
        <span><b>${today.total}</b> thing(s) waiting</span>
        ${today.late ? `<span class="latecount">${today.late} late</span>` : ''}
      </div>
      <div class="todaycols">
        ${today.groups.map(group => `
          <div class="todaygroup">
            <h3>${esc(group.title)}
              <span class="count">${group.items.length}</span></h3>
            ${group.items.slice(0, SHOWN).map(line).join('')}
            ${group.items.length > SHOWN ? `
              <div class="todayrow more" data-link="${esc(group.view)}">
                <span class="tw"></span>
                <span class="tt">+ ${group.items.length - SHOWN} more →</span>
              </div>` : ''}
          </div>`).join('')}
      </div>
    </section>`;
}

async function loadMap() {
  try {
    S.mapData = await api('/api/map');
  } catch (err) {
    S.mapData = { points: [], unplaced: [] };
  }
  if (S.view === 'dash') MapView.mount(S.mapData);
}

/* Shows in the status bar, so it is always clear the work is safely stored. */
async function refreshSaved() {
  try {
    const saved = await api('/api/status');
    const stamp = saved.saved_at ? String(saved.saved_at).slice(0, 16) : 'never';
    const backup = saved.last_backup_at
      ? 'backed up ' + String(saved.last_backup_at).slice(0, 16)
      : (saved.configured ? 'backup pending' : 'no backup folder set');
    const node = $('#saved');
    if (node) node.innerHTML =
      `saved <b>${esc(stamp)}</b> UTC &nbsp;·&nbsp; ${esc(backup)}`;
  } catch (err) { /* the server may simply have been stopped */ }
}

/* ---- the order book ---- */

const COLUMNS = [
  { key: 'product',      label: 'PRODUCT',  sort: 'product_name' },
  { key: 'order_no',     label: 'ORDER',    sort: 'order_no' },
  { key: 'company',      label: 'CUSTOMER', sort: 'company' },
  { key: 'po_number',    label: 'CUST PO',  sort: 'po_number' },
  { key: 'description',  label: 'DESCRIPTION' },
  { key: 'status',       label: 'STATUS',   sort: 'status' },
  { key: 'promise_date', label: 'PROMISED', sort: 'promise_date' },
  { key: 'days',         label: 'DUE IN',   num: true },
  { key: 'value',        label: 'VALUE',    sort: 'value', num: true },
  { key: 'owner',        label: 'OWNER',    sort: 'owner' },
  { key: 'docs',         label: 'DOCS',     num: true },
  { key: 'alerts',       label: 'FLAGS' },
];

async function loadOrders() {
  const params = new URLSearchParams();
  Object.entries(S.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
  params.set('sort', S.sort.key);
  params.set('dir', S.sort.dir);
  if (S.filters.closed !== '1') params.set('closed', '0');

  status('loading orders…');
  try {
    const data = await api('/api/orders?' + params.toString());
    S.orders = data.orders;
    S.selected = Math.min(S.selected, Math.max(0, S.orders.length - 1));
    renderOrders();
    status(`${S.orders.length} orders`);
  } catch (err) {
    toast(err.message, 'err');
    status('failed to load orders');
  }
}

function renderOrders() {
  const companies = S.boot.companies;
  const owners = [...new Set(S.orders.map(o => o.owner).filter(Boolean))].sort();
  const totalValue = S.orders.reduce((sum, o) => sum + (o.value || 0), 0);

  $('#view-orders').innerHTML = `
    <div class="filterbar">
      <label class="f">STATUS
        <select id="f-status">
          <option value="">all</option>
          ${S.boot.all_statuses.map(s =>
            `<option ${S.filters.status === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
        </select>
      </label>
      <label class="f">CUSTOMER
        <select id="f-company">
          <option value="">all</option>
          ${companies.map(c =>
            `<option value="${c.id}" ${String(S.filters.company_id) === String(c.id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
        </select>
      </label>
      <label class="f">OWNER
        <select id="f-owner">
          <option value="">all</option>
          ${owners.map(o =>
            `<option ${S.filters.owner === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}
        </select>
      </label>
      <label class="f">FLAG
        <select id="f-alert">
          <option value="">any</option>
          ${['OVERDUE', 'DUE SOON', 'STALLED', 'NO PO', 'ON HOLD'].map(a =>
            `<option ${S.filters.alert === a ? 'selected' : ''}>${esc(a)}</option>`).join('')}
        </select>
      </label>
      <label class="toggle">
        <input type="checkbox" id="f-closed" ${S.filters.closed === '1' ? 'checked' : ''}>
        show closed
      </label>
      <button class="btn" id="f-clear">CLEAR</button>
      <span class="spacer"></span>
      <span class="note">${S.orders.length} rows · ${money(totalValue)} total</span>
    </div>

    <table class="grid" id="ordertable">
      <thead><tr>
        ${COLUMNS.map(c => `
          <th class="${c.sort ? 'sortable' : ''} ${c.num ? 'num' : ''}"
              ${c.sort ? `data-sort="${c.sort}"` : ''}>
            ${c.label}${S.sort.key === c.sort ? `<span class="arrow"> ${S.sort.dir === 'asc' ? '▲' : '▼'}</span>` : ''}
          </th>`).join('')}
      </tr></thead>
      <tbody>
        ${S.orders.length ? S.orders.map((o, i) => rowHTML(o, i)).join('')
                          : `<tr><td colspan="${COLUMNS.length}" class="empty">
                               No orders match these filters.</td></tr>`}
      </tbody>
    </table>`;

  const view = $('#view-orders');
  $('#f-status', view).onchange = e => { S.filters.status = e.target.value; loadOrders(); };
  $('#f-company', view).onchange = e => { S.filters.company_id = e.target.value; loadOrders(); };
  $('#f-owner', view).onchange = e => { S.filters.owner = e.target.value; loadOrders(); };
  $('#f-alert', view).onchange = e => { S.filters.alert = e.target.value; loadOrders(); };
  $('#f-closed', view).onchange = e => { S.filters.closed = e.target.checked ? '1' : '0'; loadOrders(); };
  $('#f-clear', view).onclick = () => {
    S.filters = { status: '', company_id: '', owner: '', alert: '', closed: '1' };
    loadOrders();
  };

  $$('#ordertable th[data-sort]', view).forEach(th => {
    th.onclick = () => {
      const key = th.dataset.sort;
      S.sort = { key, dir: (S.sort.key === key && S.sort.dir === 'asc') ? 'desc' : 'asc' };
      loadOrders();
    };
  });

  $('#ordertable tbody', view).onclick = event => {
    const tr = event.target.closest('tr[data-id]');
    if (!tr) return;
    S.selected = Number(tr.dataset.index);
    markSelection();
    openOrder(Number(tr.dataset.id));
  };
  markSelection();
}

function rowHTML(o, index) {
  const closed = o.status === 'PAID' || o.status === 'CANCELLED';
  return `<tr data-id="${o.id}" data-index="${index}" class="${closed ? 'muted' : ''}">
    <td>${o.product_name || o.product_code
           ? `<b>${esc(o.product_name || o.product_code)}</b>`
             + (o.product_name && o.product_code
                 ? `<div class="subtle">${esc(o.product_code)}</div>` : '')
           : '<span style="color:var(--dimmer)">—</span>'}</td>
    <td style="color:var(--amber)">${esc(o.order_no)}</td>
    <td>${esc(o.company)}</td>
    <td style="color:var(--dim)">${esc(o.po_number || '—')}</td>
    <td style="color:var(--dim)">${esc(o.description || '')}</td>
    <td><span class="chip ${cls(o.status)}">${esc(o.status)}</span></td>
    <td>${esc(o.promise_date || '—')}</td>
    <td class="num">${dayText(closed ? null : o.days_to_promise)}</td>
    <td class="num">${money(o.value, o.currency)}</td>
    <td class="prio-${esc(o.priority)}">${esc(o.owner || '—')}</td>
    <td class="num" style="color:${o.doc_count ? 'var(--text)' : 'var(--dimmer)'}">${o.doc_count || '—'}</td>
    <td>${o.alerts.map(f => `<span class="chip ${acls(f)}">${esc(f)}</span>`).join('')}</td>
  </tr>`;
}

function markSelection() {
  $$('#ordertable tbody tr').forEach(tr =>
    tr.classList.toggle('sel', Number(tr.dataset.index) === S.selected));
  const row = $(`#ordertable tbody tr[data-index="${S.selected}"]`);
  if (row) row.scrollIntoView({ block: 'nearest' });
}

/* ---- customers ---- */

function renderCompanies() {
  const companies = S.boot.companies;
  $('#view-companies').innerHTML = `
    <div class="filterbar">
      <button class="btn primary" id="c-new">+ ADD CUSTOMER</button>
      <span class="spacer"></span>
      <span class="note">${companies.length} customers</span>
    </div>
    <table class="grid">
      <thead><tr>
        <th>CUSTOMER</th><th>CODE</th><th>WHERE</th><th>LOCAL TIME</th>
        <th>CONTACT</th><th>EMAIL</th><th class="num">ORDERS</th><th class="num">OPEN</th><th class="num">OPEN VALUE</th><th class="num">FOLDERS</th><th></th>
      </tr></thead>
      <tbody>
        ${companies.map(c => `
          <tr data-company-id="${c.id}">
            <td>${esc(c.name)}</td>
            <td style="color:var(--dim)">${esc(c.code || '')}</td>
            <td style="color:var(--dim)">${esc([c.city, c.country].filter(Boolean).join(', ') || '—')}</td>
            <td class="ltime ${c.timezone ? awake(c.timezone, new Date()) : ''}">
              ${c.timezone ? esc(timeIn(c.timezone, new Date())) : '—'}</td>
            <td style="color:var(--dim)">${esc(c.contact_name || '')}</td>
            <td style="color:var(--blue)">${esc(c.contact_email || '')}</td>
            <td class="num">${c.order_count}</td>
            <td class="num">${c.open_count}</td>
            <td class="num">${money(c.open_value)}</td>
            <td class="num"><button class="btn" data-folders="${c.id}"
              title="Enquiries and requests from this customer">${
                c.open_folders || 0}${c.folders > (c.open_folders || 0)
                  ? ' / ' + c.folders : ''}</button></td>
            <td><button class="btn" data-edit="${c.id}">EDIT</button></td>
          </tr>`).join('')}
      </tbody>
    </table>`;

  $('#c-new').onclick = () => companyModal(null);
  $('#view-companies').onclick = event => {
    const foldersBtn = event.target.closest('[data-folders]');
    if (foldersBtn) {
      FOLDERS.filter = { open: '1', company_id: foldersBtn.dataset.folders,
                         status: '', q: '' };
      show('folders');
      return;
    }
    const editBtn = event.target.closest('[data-edit]');
    if (editBtn) {
      const company = S.boot.companies.find(c => c.id === Number(editBtn.dataset.edit));
      companyModal(company);
      return;
    }
    const row = event.target.closest('[data-company-id]');
    if (row) {
      S.filters = { status: '', company_id: row.dataset.companyId, owner: '',
                    alert: '', closed: '1' };
      show('orders');
    }
  };
}

/* ---- documents ---- */

async function renderDocs(unfiledOnly = false) {
  const data = await api('/api/documents' + (unfiledOnly ? '?unfiled=1' : ''));
  const docs = data.documents;

  $('#view-docs').innerHTML = `
    <div class="filterbar">
      <label class="toggle">
        <input type="checkbox" id="d-unfiled" ${unfiledOnly ? 'checked' : ''}>
        show only unfiled
      </label>
      <button class="btn" id="d-autofile">AUTO-FILE UNFILED</button>
      <span class="spacer"></span>
      <span class="note">${docs.length} documents</span>
    </div>

    <div class="dropzone" id="d-drop">
      Drop files here, or click to choose — purchase orders, invoices, packing
      lists, saved emails. Their text is read and indexed, and each one is filed
      against the order it names.
      <input type="file" id="d-file" multiple class="hidden">
    </div>

    <table class="grid" style="margin-top:10px">
      <thead><tr>
        <th>FILE</th><th>KIND</th><th>FILED AGAINST</th><th>CUSTOMER</th>
        <th class="num">SIZE</th><th class="num">TEXT</th><th>ADDED</th><th></th>
      </tr></thead>
      <tbody>
        ${docs.length ? docs.map(d => `
          <tr>
            <td><a href="/api/documents/${d.id}/file" target="_blank"
                   style="color:var(--text)">${esc(d.filename)}</a></td>
            <td class="k-${esc(d.kind || 'OTHER')}">${esc(d.kind || 'OTHER')}</td>
            <td>${d.order_no
                  ? `<a href="#" data-open-order="${d.order_id}" class="ordlink">${esc(orderName(d))}</a>`
                    + `<div class="subtle">${esc(orderSub(d))}</div>`
                  : '<span style="color:var(--red)">unfiled</span>'}</td>
            <td style="color:var(--dim)">${esc(d.company || '')}</td>
            <td class="num" style="color:var(--dim)">${bytes(d.size)}</td>
            <td class="num" style="color:${d.text_len ? 'var(--green)' : 'var(--dimmer)'}">
              ${d.text_len ? bytes(d.text_len) : '—'}</td>
            <td style="color:var(--dim)">${esc((d.uploaded_at || '').slice(0, 16))}</td>
            <td>
              <button class="btn" data-text="${d.id}">TEXT</button>
              <button class="btn danger" data-del-doc="${d.id}">DEL</button>
            </td>
          </tr>`).join('')
        : '<tr><td colspan="8" class="empty">No documents yet. Drop some in above.</td></tr>'}
      </tbody>
    </table>`;

  const view = $('#view-docs');
  $('#d-unfiled', view).onchange = e => renderDocs(e.target.checked);
  $('#d-autofile', view).onclick = autofileAll;
  wireDropzone($('#d-drop', view), $('#d-file', view), null, () => renderDocs(unfiledOnly));

  view.onclick = async event => {
    const textBtn = event.target.closest('[data-text]');
    if (textBtn) { showDocumentText(Number(textBtn.dataset.text)); return; }

    const delBtn = event.target.closest('[data-del-doc]');
    if (delBtn) {
      const row = delBtn.closest('tr');
      const name = row ? row.querySelector('a').textContent : 'this document';
      if (!confirm(`Delete "${name}"? The file is removed from the documents folder.`)) return;
      await api('/api/documents/' + delBtn.dataset.delDoc, { method: 'DELETE' });
      toast('Document deleted', 'ok');
      renderDocs(unfiledOnly);
      reloadBoot();
      return;
    }

    const orderLink = event.target.closest('[data-open-order]');
    if (orderLink) { event.preventDefault(); openOrder(Number(orderLink.dataset.openOrder)); }
  };
}

async function autofileAll() {
  const data = await api('/api/documents?unfiled=1');
  if (!data.documents.length) { toast('Nothing is unfiled.'); return; }
  let filed = 0;
  for (const doc of data.documents) {
    const result = await postJSON(`/api/documents/${doc.id}`, { autofile: true })
      .catch(() => null);
    if (result && result.document && result.document.order_id) filed++;
  }
  toast(`${filed} of ${data.documents.length} filed automatically`, filed ? 'ok' : '');
  renderDocs();
  reloadBoot();
}

async function showDocumentText(docId) {
  const data = await api(`/api/documents/${docId}/text`);
  modal(`TEXT — ${esc(data.filename)}`, `
    ${data.note ? `<div class="note warn" style="margin-bottom:8px">${esc(data.note)}</div>` : ''}
    <pre class="textdump">${esc(data.text) || '(no text could be read from this file)'}</pre>`,
    [{ label: 'CLOSE', action: closeModal }]);
}

/* ---- import ---- */

function renderImport() {
  $('#view-import').innerHTML = `
    <h2 class="sect">Import orders from a spreadsheet</h2>
    <div class="note" style="max-width:760px;margin-bottom:12px">
      Take whatever your ERP, portal or order book exports — .csv or .xlsx —
      and drop it in. The columns are matched up automatically; check the
      mapping, then import. Orders already here are updated in place and
      matched on their order number, so re-importing a fresh export is how you
      refresh statuses in bulk.
    </div>

    <div class="dropzone" id="i-drop">
      Drop a .csv or .xlsx file here, or click to choose
      <input type="file" id="i-file" accept=".csv,.xlsx,.xlsm,.tsv,.txt" class="hidden">
    </div>

    <div id="i-result"></div>`;

  const drop = $('#i-drop');
  const input = $('#i-file');
  drop.onclick = () => input.click();
  input.onchange = () => { if (input.files[0]) previewImport(input.files[0]); };
  ['dragover', 'dragenter'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.remove('over');
  }));
  drop.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) previewImport(file);
  });
}

async function previewImport(file) {
  S.importFile = file;
  const form = new FormData();
  form.append('file', file);
  status('reading ' + file.name + '…');
  try {
    S.importPreview = await api('/api/import/preview', { method: 'POST', body: form });
  } catch (err) {
    toast(err.message, 'err');
    return;
  }
  status('ready to import');
  renderImportPreview();
}

function renderImportPreview() {
  const p = S.importPreview;
  const fields = S.boot.import_fields;

  const columnOptions = index => `
    <option value="">— not imported —</option>
    ${p.headers.map((h, i) =>
      `<option value="${i}" ${p.mapping[index] === i ? 'selected' : ''}>
         ${esc(h || '(column ' + (i + 1) + ')')}</option>`).join('')}`;

  $('#i-result').innerHTML = `
    <h2 class="sect">${esc(p.filename)} — ${p.total} rows</h2>

    <div class="previewwrap">
      <table class="grid">
        <thead><tr>${p.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
        <tbody>
          ${p.rows.map(r => `<tr>${p.headers.map((_, i) =>
            `<td>${esc(r[i] !== undefined ? r[i] : '')}</td>`).join('')}</tr>`).join('')}
        </tbody>
      </table>
    </div>

    <h2 class="sect">Column mapping</h2>
    <div class="mapgrid" style="max-width:620px">
      ${fields.map(f => `
        <label class="f" style="justify-content:flex-end">
          ${f.replace(/_/g, ' ').toUpperCase()}${f === 'order_no' ? ' *' : ''}
        </label>
        <select data-field="${f}">${columnOptions(f)}</select>`).join('')}
    </div>

    <div class="filterbar" style="margin-top:14px">
      <label class="toggle">
        <input type="checkbox" id="i-update" checked>
        update orders that are already here
      </label>
      <label class="f">DEFAULT STATUS
        <select id="i-default">
          ${S.boot.all_statuses.map(s => `<option>${esc(s)}</option>`).join('')}
        </select>
      </label>
      <button class="btn primary" id="i-run">IMPORT ${p.total} ROWS</button>
    </div>`;

  $('#i-run').onclick = runImport;
}

async function runImport() {
  const mapping = {};
  $$('#i-result select[data-field]').forEach(sel => {
    if (sel.value !== '') mapping[sel.dataset.field] = Number(sel.value);
  });
  if (mapping.order_no === undefined) {
    toast('Map a column to ORDER NO first — it is how rows are matched.', 'err');
    return;
  }

  const form = new FormData();
  form.append('file', S.importFile);
  form.append('mapping', JSON.stringify(mapping));
  form.append('update_existing', $('#i-update').checked ? '1' : '0');
  form.append('default_status', $('#i-default').value);

  $('#i-run').disabled = true;
  status('importing…');
  try {
    const result = await api('/api/import/run', { method: 'POST', body: form });
    toast(`${result.created} created, ${result.updated} updated, ${result.skipped} skipped`, 'ok');
    if (result.errors && result.errors.length) {
      $('#i-result').insertAdjacentHTML('beforeend', `
        <h2 class="sect bad">${result.error_count} rows had problems</h2>
        <pre class="textdump">${esc(result.errors.join('\n'))}</pre>`);
    }
    await reloadBoot();
    status('import finished');
  } catch (err) {
    toast(err.message, 'err');
    status('import failed');
  } finally {
    $('#i-run').disabled = false;
  }
}

/* ---- search ---- */

let searchTimer = null;

function onSearchInput(text) {
  clearTimeout(searchTimer);
  if (!text.trim()) { show(S.view === 'search' ? 'orders' : S.view); return; }
  searchTimer = setTimeout(() => runSearch(text), 180);
}

async function runSearch(text) {
  let data;
  try {
    data = await api('/api/search?q=' + encodeURIComponent(text));
  } catch (err) { toast(err.message, 'err'); return; }

  S.view = 'search';
  setHash('search/' + encodeURIComponent(text));
  $$('.view').forEach(v => v.classList.add('hidden'));
  $$('#nav button[data-view]').forEach(b => b.classList.remove('active'));
  $('#view-search').classList.remove('hidden');

  $('#view-search').innerHTML = `
    <h2 class="sect">Orders matching "${esc(text)}" — ${data.orders.length}</h2>
    ${data.orders.length ? `
      <table class="grid"><thead><tr>
        <th>PRODUCT</th><th>ORDER</th><th>CUSTOMER</th><th>CUST PO</th><th>DESCRIPTION</th>
        <th>STATUS</th><th>PROMISED</th><th class="num">VALUE</th><th>FLAGS</th>
      </tr></thead><tbody>
        ${data.orders.map(o => `
          <tr data-open="${o.id}">
            <td><b>${esc(orderName(o))}</b></td>
            <td style="color:var(--amber)">${esc(o.order_no)}</td>
            <td>${esc(o.company)}</td>
            <td style="color:var(--dim)">${esc(o.po_number || '—')}</td>
            <td style="color:var(--dim)">${esc(o.description || '')}</td>
            <td><span class="chip ${cls(o.status)}">${esc(o.status)}</span></td>
            <td>${esc(o.promise_date || '—')}</td>
            <td class="num">${money(o.value, o.currency)}</td>
            <td>${o.alerts.map(f => `<span class="chip ${acls(f)}">${esc(f)}</span>`).join('')}</td>
          </tr>`).join('')}
      </tbody></table>` : '<div class="empty">No orders match.</div>'}

    <h2 class="sect">Inside documents — ${data.documents.length}</h2>
    ${data.documents.length ? `
      <table class="grid"><thead><tr>
        <th style="width:240px">FILE</th><th style="width:140px">ORDER</th>
        <th style="width:180px">CUSTOMER</th><th>MATCH</th><th></th>
      </tr></thead><tbody>
        ${data.documents.map(d => `
          <tr>
            <td><a href="/api/documents/${d.id}/file" target="_blank"
                   style="color:var(--text)">${esc(d.filename)}</a></td>
            <td>${d.order_id
                  ? `<a href="#" data-open-order="${d.order_id}" class="ordlink">${esc(orderName(d))}</a>`
                    + `<div class="subtle">${esc(orderSub(d))}</div>`
                  : '<span style="color:var(--red)">unfiled</span>'}</td>
            <td style="color:var(--dim)">${esc(d.company || '')}</td>
            <td class="snippet">${highlight(d.snippet || '')}</td>
            <td><button class="btn" data-text="${d.id}">TEXT</button></td>
          </tr>`).join('')}
      </tbody></table>`
      : '<div class="empty">Nothing found inside any document.</div>'}`;

  $('#view-search').onclick = event => {
    const row = event.target.closest('[data-open]');
    if (row) { openOrder(Number(row.dataset.open)); return; }
    const link = event.target.closest('[data-open-order]');
    if (link) { event.preventDefault(); openOrder(Number(link.dataset.openOrder)); return; }
    const textBtn = event.target.closest('[data-text]');
    if (textBtn) showDocumentText(Number(textBtn.dataset.text));
  };
  status(`${data.orders.length} orders, ${data.documents.length} documents matched`);
}

/* --------------------------------------------------------- detail panel */

async function openOrder(orderId, tab) {
  try {
    S.openOrder = await api('/api/orders/' + orderId);
  } catch (err) { toast(err.message, 'err'); return; }
  if (tab) S.detailTab = tab;
  setHash('order/' + orderId
          + (S.detailTab && S.detailTab !== 'order' ? '/' + S.detailTab : ''));
  renderDetail();
}

function closeDetail() {
  S.openOrder = null;
  $('#detail').classList.add('hidden');
  setHash(NAV_VIEWS.includes(S.view) ? S.view : 'orders');
}

function renderDetail() {
  const o = S.openOrder;
  const panel = $('#detail');
  panel.classList.remove('hidden');

  const pipelineIndex = S.boot.pipeline.indexOf(o.status);
  const tab = S.detailTab || 'order';
  const spec = o.spec || { values: {}, derived: {}, cost: null };

  // A spec with no contact on it yet gets the one from the customer record,
  // ready to save. Anything already saved is never overwritten.
  const specValues = { ...(spec.values || {}) };
  if (!specValues.contact_person && o.contact_name) {
    specValues.contact_person = o.contact_name;
  }

  const tabs = [
    ['order', 'ORDER'],
    ['spec', 'SPEC'],
    ['cost', 'COST'],
    ['docs', `DOCS (${o.documents.length})`],
    ['mail', `MAIL (${(o.emails || []).length})`],
    ['cases', `CASES (${(o.cases || []).length})`],
    ['history', 'HISTORY'],
  ];

  const openCases = (o.cases || []).filter(c => c.open).length;

  panel.innerHTML = `
    <div class="dhead">
      <span class="ono">${esc(orderName(o))}</span>
      <span class="ono-no">${esc(orderSub(o))}</span>
      <span class="co">${esc(o.company)}</span>
      <span class="chip ${cls(o.status)}">${esc(o.status)}</span>
      ${o.alerts.map(f => `<span class="chip ${acls(f)}">${esc(f)}</span>`).join('')}
      <button class="btn dclose" id="d-close">ESC</button>
    </div>

    <div class="dbody">
      <div class="pipeline">
        ${S.boot.pipeline.map((step, i) => `
          <div class="step ${i < pipelineIndex ? 'done' : ''} ${i === pipelineIndex ? 'here' : ''}"
               data-step="${esc(step)}" title="Move this order to ${esc(step)}">
            ${esc(step)}
          </div>`).join('')}
      </div>

      <div class="dtabs">
        ${tabs.map(([key, label]) => `
          <button data-tab="${key}" class="${tab === key ? 'active' : ''}">${label}</button>`).join('')}
        <span class="spacer"></span>
        <a class="btn" href="/print/order/${o.id}" target="_blank"
           title="A printable specification and cost sheet">PRINT</a>
      </div>

      <div class="dpane ${tab === 'order' ? '' : 'hidden'}" id="pane-order">
        <div class="filterbar" style="padding-bottom:12px">
          ${S.boot.special_statuses.map(s => `
            <button class="btn" data-step="${esc(s)}">${esc(s)}</button>`).join('')}
          <span class="spacer"></span>
          <button class="btn danger" id="d-delete">DELETE ORDER</button>
        </div>

        <div class="kv">
          <div class="k">CUSTOMER PO</div>
          <div class="v"><input id="e-po_number" value="${esc(o.po_number || '')}"></div>
          <div class="k">PRODUCT NO</div>
          <div class="v"><input id="e-product_code" value="${esc(o.product_code || '')}"></div>
          <div class="k">PRODUCT NAME</div>
          <div class="v"><input id="e-product_name" value="${esc(o.product_name || '')}"></div>
          <div class="k">DESCRIPTION</div>
          <div class="v"><input id="e-description" value="${esc(o.description || '')}"></div>
          <div class="k">VALUE</div>
          <div class="v" style="display:flex;gap:6px">
            <input id="e-value" type="number" step="0.01" value="${o.value || 0}" style="flex:2">
            <input id="e-currency" value="${esc(o.currency || 'USD')}" style="flex:1">
          </div>
          <div class="k">ORDER DATE</div>
          <div class="v"><input id="e-order_date" type="date" value="${esc(o.order_date || '')}"></div>
          <div class="k">PROMISED</div>
          <div class="v"><input id="e-promise_date" type="date" value="${esc(o.promise_date || '')}"></div>
          <div class="k">SHIPPED</div>
          <div class="v"><input id="e-ship_date" type="date" value="${esc(o.ship_date || '')}"></div>
          <div class="k">OWNER</div>
          <div class="v"><input id="e-owner" value="${esc(o.owner || '')}"></div>
          <div class="k">PRIORITY</div>
          <div class="v"><select id="e-priority">
            ${['LOW', 'NORMAL', 'HIGH', 'URGENT'].map(p =>
              `<option ${o.priority === p ? 'selected' : ''}>${p}</option>`).join('')}
          </select></div>
          <div class="k">NOTES</div>
          <div class="v"><textarea id="e-notes" rows="3">${esc(o.notes || '')}</textarea></div>
        </div>

        <div class="filterbar" style="padding:10px 0 4px">
          <button class="btn primary" id="d-save">SAVE CHANGES</button>
          <span class="note">contact: ${esc(o.contact_name || '—')}
            ${o.contact_email ? `· <a href="mailto:${esc(o.contact_email)}" style="color:var(--blue)">${esc(o.contact_email)}</a>` : ''}</span>
        </div>
      </div>

      <div class="dpane ${tab === 'spec' ? '' : 'hidden'}" id="pane-spec">
        <div class="filterbar" style="padding:0 0 10px">
          <button class="btn" id="d-reorder">COPY FROM PREVIOUS ORDER</button>
          <span class="spacer"></span>
          <span class="note">${spec.updated_at
            ? 'spec saved ' + esc(spec.updated_at) + ' UTC' : 'no spec saved yet'}</span>
        </div>
        ${specFormHTML('s', specValues)}
        <h2 class="sect">Worked out for you</h2>
        <div id="spec-derived"></div>
        <div class="filterbar" style="padding:10px 0 4px">
          <button class="btn primary" id="d-savespec">SAVE SPEC &amp; COST</button>
        </div>
      </div>

      <div class="dpane ${tab === 'cost' ? '' : 'hidden'}" id="pane-cost">
        ${costFormHTML('s', specValues)}
        <h2 class="sect">Totals</h2>
        <div id="spec-cost"></div>
        <div class="filterbar" style="padding:10px 0 4px">
          <button class="btn primary" id="d-savecost">SAVE SPEC &amp; COST</button>
          <a class="btn" href="/print/order/${o.id}" target="_blank">PRINT SHEET</a>
        </div>
      </div>

      <div class="dpane ${tab === 'docs' ? '' : 'hidden'}" id="pane-docs">
        <div class="dropzone" id="o-drop" style="margin-bottom:8px">
          Drop files here to file them against ${esc(orderName(o))}
          <input type="file" id="o-file" multiple class="hidden">
        </div>
        <div class="doclist">
          ${o.documents.length ? o.documents.map(d => `
            <div class="docrow">
              <span class="chip k-${esc(d.kind || 'OTHER')}">${esc(d.kind || 'OTHER')}</span>
              <a class="dname" href="/api/documents/${d.id}/file" target="_blank">${esc(d.filename)}</a>
              <span class="dmeta">${bytes(d.size)}</span>
              <span class="dmeta" title="${esc(d.extract_note || 'text indexed')}"
                    style="color:${d.text_len ? 'var(--green)' : 'var(--dimmer)'}">
                ${d.text_len ? 'indexed' : 'no text'}</span>
              <button class="btn" data-text="${d.id}">TEXT</button>
              <button class="btn danger" data-del-doc="${d.id}">DEL</button>
            </div>`).join('')
          : '<div class="note">Nothing filed against this order yet.</div>'}
        </div>
      </div>

      <div class="dpane ${tab === 'mail' ? '' : 'hidden'}" id="pane-mail">
        <div class="dropzone" id="o-maildrop" style="margin-bottom:8px">
          Drop saved emails here to file them against ${esc(orderName(o))}
          <input type="file" id="o-mailfile" multiple class="hidden"
                 accept=".msg,.eml,.mht,.mhtml,.txt">
        </div>
        <div class="doclist">
          ${(o.emails || []).length ? (o.emails || []).map(m => `
            <div class="docrow mailrow" data-mail="${m.id}">
              <span class="chip k-${esc(m.category || 'GENERAL')}">${esc(m.category || 'GENERAL')}</span>
              <span class="dname">${esc(m.subject || '(no subject)')}
                <span class="subtle">${esc(m.from_name || m.from_email || '')}
                  · ${esc(String(m.sent_at || m.filed_at || '').slice(0, 10))}</span>
                <div class="subtle">${esc(m.summary || '')}</div></span>
              ${m.attachments ? `<span class="dmeta">${m.attachments} file(s)</span>` : ''}
              ${m.needs_review ? '<span class="chip a-DUESOON">CHECK</span>' : ''}
            </div>`).join('')
          : '<div class="note">No email filed against this order yet.</div>'}
        </div>
      </div>

      <div class="dpane ${tab === 'cases' ? '' : 'hidden'}" id="pane-cases">
        <div class="filterbar" style="padding:0 0 10px">
          <button class="btn accent" id="d-newcase">OPEN A CASE ON THIS ORDER</button>
          <span class="spacer"></span>
          <span class="note">${openCases
            ? openCases + ' still open' : 'nothing outstanding'}</span>
        </div>
        <div class="doclist">
          ${(o.cases || []).length ? (o.cases || []).map(c => `
            <div class="docrow caserow" data-case="${c.id}">
              <span class="chip ${c.open ? 'a-DUESOON' : 'ok'}">${esc(c.status)}</span>
              <span class="dname">${esc(c.ref)} — ${esc(c.title)}
                <div class="subtle">${esc(c.kind)} · ${esc(c.severity)}
                  · opened ${esc(c.opened_at || '')}
                  ${c.qty_affected ? '· ' + c.qty_affected + ' pcs' : ''}
                  ${c.claim_krw ? '· ' + Number(c.claim_krw).toLocaleString() + ' KRW' : ''}</div></span>
              ${c.open_actions ? `<span class="chip a-OVERDUE">${c.open_actions} ACTION(S)</span>` : ''}
              ${c.overdue ? '<span class="chip a-OVERDUE">LATE</span>' : ''}
            </div>`).join('')
          : '<div class="note">No disputes or defect claims on this order.</div>'}
        </div>
      </div>

      <div class="dpane ${tab === 'history' ? '' : 'hidden'}" id="pane-history">
        <div class="timeline">
          ${o.history.map(h => `
            <div class="ev">
              <div>${h.from_status && h.from_status !== h.to_status
                      ? `<span class="chip ${cls(h.from_status)}">${esc(h.from_status)}</span> →
                         <span class="chip ${cls(h.to_status)}">${esc(h.to_status)}</span>`
                      : `<span class="chip ${cls(h.to_status)}">${esc(h.to_status)}</span>`}
                ${h.note ? `<span style="color:var(--dim)"> — ${esc(h.note)}</span>` : ''}</div>
              <div class="when">${esc(h.changed_at)}${h.changed_by ? ' · ' + esc(h.changed_by) : ''}</div>
            </div>`).join('')}
        </div>
      </div>
    </div>`;

  $('#d-close').onclick = closeDetail;
  $('#d-save').onclick = saveOrderEdits;
  $('#d-delete').onclick = deleteOpenOrder;
  $('#d-savespec').onclick = saveSpec;
  $('#d-savecost').onclick = saveSpec;
  $('#d-reorder').onclick = () => pickPreviousSpec(o.company, values => {
    fillSpecForm('s', values);
    dateQuoteToday('s');
    refreshSpecCalc();
    toast('Specification copied and dated today — check it, '
          + 'then SAVE SPEC & COST', 'ok');
  });

  const wideTabs = ['spec', 'cost'];
  panel.classList.toggle('wide', wideTabs.includes(tab));

  $$('#detail .dtabs button').forEach(button => {
    button.onclick = () => {
      S.detailTab = button.dataset.tab;
      setHash('order/' + o.id + (S.detailTab === 'order' ? '' : '/' + S.detailTab));
      $$('#detail .dtabs button').forEach(b =>
        b.classList.toggle('active', b === button));
      $$('#detail .dpane').forEach(pane =>
        pane.classList.toggle('hidden', pane.id !== 'pane-' + S.detailTab));
      panel.classList.toggle('wide', wideTabs.includes(S.detailTab));
    };
  });

  $$('#detail .pipeline [data-step], #detail #pane-order [data-step]')
    .forEach(node => { node.onclick = () => changeStatus(node.dataset.step); });

  wireSpecForm('s', refreshSpecCalc);
  refreshSpecCalc();

  wireDropzone($('#o-drop'), $('#o-file'), o.id, () => openOrder(o.id));

  const mailZone = $('#o-maildrop');
  const mailInput = $('#o-mailfile');
  if (mailZone && mailInput) {
    mailZone.onclick = () => mailInput.click();
    mailInput.onchange = () => uploadMail(mailInput.files, o.id);
    ['dragover', 'dragenter'].forEach(ev => mailZone.addEventListener(ev, e => {
      e.preventDefault(); mailZone.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach(ev => mailZone.addEventListener(ev, e => {
      e.preventDefault(); mailZone.classList.remove('over');
    }));
    mailZone.addEventListener('drop', e => {
      e.preventDefault();
      uploadMail(e.dataTransfer.files, o.id);
    });
    $('#pane-mail').onclick = event => {
      const row = event.target.closest('[data-mail]');
      if (row) openMail(Number(row.dataset.mail));
    };
  }

  $('#d-newcase').onclick = () => newCaseModal({ orderId: o.id });
  $('#pane-cases').onclick = event => {
    const row = event.target.closest('[data-case]');
    if (row) openCase(Number(row.dataset.case));
  };

  $('.doclist', panel).onclick = async event => {
    const textBtn = event.target.closest('[data-text]');
    if (textBtn) { showDocumentText(Number(textBtn.dataset.text)); return; }
    const delBtn = event.target.closest('[data-del-doc]');
    if (delBtn) {
      if (!confirm('Delete this document?')) return;
      await api('/api/documents/' + delBtn.dataset.delDoc, { method: 'DELETE' });
      toast('Document deleted', 'ok');
      openOrder(o.id);
      reloadBoot();
    }
  };
}

function refreshSpecCalc() {
  quoteFromForm('s', 'spec-derived', 'spec-cost');
}

async function saveSpec() {
  const o = S.openOrder;
  if (!o) return;
  try {
    await postJSON('/api/orders/' + o.id + '/spec', readSpecForm('s'));
    toast('Specification and cost saved', 'ok');
    await openOrder(o.id);
    refreshSaved();
  } catch (err) { toast(err.message, 'err'); }
}

async function changeStatus(newStatus) {
  const o = S.openOrder;
  if (!o || newStatus === o.status) return;
  const note = prompt(`Move ${orderName(o)} to ${newStatus}.\nAdd a note (optional):`, '');
  if (note === null) return;
  try {
    await postJSON('/api/orders/' + o.id, { status: newStatus, note });
    toast(`${orderName(o)} → ${newStatus}`, 'ok');
    await openOrder(o.id);
    await reloadBoot();
    if (S.view === 'orders') loadOrders(); else if (S.view === 'dash') renderDash();
  } catch (err) { toast(err.message, 'err'); }
}

async function saveOrderEdits() {
  const o = S.openOrder;
  const body = {};
  ['po_number', 'product_code', 'product_name', 'description', 'value',
   'currency', 'order_date', 'promise_date', 'ship_date', 'owner', 'priority',
   'notes'].forEach(field => {
    const input = $('#e-' + field);
    if (input) body[field] = input.value;
  });
  try {
    await postJSON('/api/orders/' + o.id, body);
    toast('Saved', 'ok');
    await openOrder(o.id);
    await reloadBoot();
    if (S.view === 'orders') loadOrders();
  } catch (err) { toast(err.message, 'err'); }
}

async function deleteOpenOrder() {
  const o = S.openOrder;
  if (!confirm(`Delete ${orderName(o)} (${o.order_no}) and its ${o.documents.length} document(s)?\nThis cannot be undone.`)) return;
  await api('/api/orders/' + o.id, { method: 'DELETE' });
  toast(`${orderName(o)} deleted`, 'ok');
  closeDetail();
  await reloadBoot();
  if (S.view === 'orders') loadOrders(); else renderDash();
}

/* ------------------------------------------------------------- uploading */

function wireDropzone(zone, input, orderId, onDone) {
  if (!zone || !input) return;
  zone.onclick = () => input.click();
  input.onchange = () => uploadFiles(input.files, orderId, onDone);

  ['dragover', 'dragenter'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.remove('over');
  }));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    uploadFiles(e.dataTransfer.files, orderId, onDone);
  });
}

async function uploadFiles(files, orderId, onDone) {
  if (!files || !files.length) return;
  const form = new FormData();
  Array.from(files).forEach(f => form.append('files', f));
  if (orderId) form.append('order_id', String(orderId));

  status(`uploading ${files.length} file(s)…`);
  try {
    const result = await api('/api/documents/upload', { method: 'POST', body: form });
    const autofiled = result.saved.filter(s => s.autofiled_to).length;
    const duplicates = result.saved.filter(s => s.duplicate).length;
    let message = `${result.saved.length} file(s) stored`;
    if (autofiled) message += `, ${autofiled} filed automatically`;
    if (duplicates) message += `, ${duplicates} already on file`;
    toast(message, 'ok');

    result.saved.filter(s => s.extract_note).forEach(s =>
      toast(`${s.filename}: ${s.extract_note}`));
    result.failed.forEach(f => toast(`${f.filename}: ${f.error}`, 'err'));

    status('ready');
    await reloadBoot();
    if (onDone) onDone();
  } catch (err) {
    toast(err.message, 'err');
    status('upload failed');
  }
}

/* ---------------------------------------------------------------- modals */

function modal(title, bodyHTML, buttons) {
  $('#modal').classList.remove('hidden');
  $('#modal').innerHTML = `
    <div class="mbox">
      <div class="mhead">${title}</div>
      <div class="mbody">${bodyHTML}</div>
      <div class="mfoot">
        ${buttons.map((b, i) =>
          `<button class="btn ${b.primary ? 'primary' : ''}" data-b="${i}">${esc(b.label)}</button>`).join('')}
      </div>
    </div>`;
  $$('#modal [data-b]').forEach(btn => {
    btn.onclick = () => buttons[Number(btn.dataset.b)].action();
  });
  const firstInput = $('#modal input, #modal select');
  if (firstInput) firstInput.focus();
}

function closeModal() {
  $('#modal').classList.add('hidden');
  $('#modal').innerHTML = '';
  // A case or an email opened from a link put itself in the address bar;
  // closing it puts the view back, so a refresh lands where you are.
  if (!S.openOrder && NAV_VIEWS.includes(S.view)) setHash(S.view);
}

function newOrderModal(openTab) {
  const today = new Date().toISOString().slice(0, 10);
  modal('NEW ORDER', `
    <div class="mtabs">
      <button data-mtab="basics" class="active">ORDER</button>
      <button data-mtab="spec">PCB SPEC</button>
      <button data-mtab="cost">COST</button>
      <span class="spacer"></span>
      <button class="btn" id="n-reorder">REPEAT A PREVIOUS ORDER</button>
    </div>

    <div class="mpane" id="mpane-basics">
      <div class="formgrid">
        <div class="lbl">ORDER NO *</div>
        <div><input id="n-order_no" placeholder="SO-1234"></div>
        <div class="lbl">CUSTOMER *</div>
        <div><input id="n-company" list="companylist" placeholder="start typing…">
          <datalist id="companylist">
            ${S.boot.companies.map(c => `<option value="${esc(c.name)}">`).join('')}
          </datalist>
          <datalist id="productcodelist">
            ${(S.boot.products || []).filter(p => p.code).map(p =>
              `<option value="${esc(p.code)}">${esc(p.name || '')}</option>`).join('')}
          </datalist>
          <datalist id="productnamelist">
            ${(S.boot.products || []).filter(p => p.name).map(p =>
              `<option value="${esc(p.name)}">`).join('')}
          </datalist></div>

        <div class="lbl">CUSTOMER PO</div><div><input id="n-po_number"></div>
        <div class="lbl">STATUS</div>
        <div><select id="n-status">
          ${S.boot.all_statuses.map(s =>
            `<option ${s === S.boot.pipeline[1] ? 'selected' : ''}>${esc(s)}</option>`).join('')}
        </select></div>

        <div class="lbl">PRODUCT NO</div>
        <div><input id="n-product_code" list="productcodelist"
          placeholder="part number"></div>
        <div class="lbl">PRODUCT NAME</div>
        <div><input id="n-product_name" list="productnamelist"
          placeholder="what the board is called"></div>

        <div class="lbl">DESCRIPTION</div>
        <div class="wide"><input id="n-description" placeholder="what was ordered"></div>

        <div class="lbl">VALUE</div><div><input id="n-value" type="number" step="0.01" value="0"></div>
        <div class="lbl">CURRENCY</div><div><input id="n-currency" value="USD"></div>

        <div class="lbl">ORDER DATE</div><div><input id="n-order_date" type="date" value="${today}"></div>
        <div class="lbl">PROMISED</div><div><input id="n-promise_date" type="date"></div>

        <div class="lbl">OWNER</div><div><input id="n-owner"></div>
        <div class="lbl">PRIORITY</div>
        <div><select id="n-priority">
          <option>LOW</option><option selected>NORMAL</option>
          <option>HIGH</option><option>URGENT</option>
        </select></div>

        <div class="lbl">NOTES</div>
        <div class="wide"><textarea id="n-notes" rows="2"></textarea></div>
      </div>
      <div class="note">The PCB SPEC and COST tabs are optional — an order can
        be created with just the two fields marked *, and the rest filled in
        later.</div>
    </div>

    <div class="mpane hidden" id="mpane-spec">
      ${specFormHTML('n', null)}
    </div>

    <div class="mpane hidden" id="mpane-cost">
      ${costFormHTML('n', null)}
      <h2 class="sect">Totals</h2>
      <div id="n-calc"></div>
    </div>`,
    [
      { label: 'CANCEL', action: closeModal },
      { label: 'CREATE ORDER', primary: true, action: createOrder },
    ]);

  $$('#modal .mtabs [data-mtab]').forEach(button => {
    button.onclick = () => {
      $$('#modal .mtabs [data-mtab]').forEach(b =>
        b.classList.toggle('active', b === button));
      $$('#modal .mpane').forEach(pane =>
        pane.classList.toggle('hidden', pane.id !== 'mpane-' + button.dataset.mtab));
    };
  });

  if (openTab) {
    const wanted = $(`#modal .mtabs [data-mtab="${openTab}"]`);
    if (wanted) wanted.click();
  }

  $('#n-reorder').onclick = () =>
    pickPreviousSpec($('#n-company') ? $('#n-company').value : '', values => {
      newOrderModal();
      fillSpecForm('n', values);
      dateQuoteToday('n');
      quoteFromForm('n', 'n-calc', 'n-calc');
      toast('Specification copied and dated today. Give it an order '
            + 'number and a customer.', 'ok');
    });

  wireSpecForm('n', () => quoteFromForm('n', 'n-calc', 'n-calc'));

  // A new order is nearly always a new quotation, so it is dated today
  // until somebody says otherwise.
  const quoteDate = $('#n-quote_date');
  if (quoteDate && !quoteDate.value) quoteDate.value = todayISO();

  // Choosing the customer brings their contact person across.
  const companyField = $('#n-company');
  if (companyField) {
    const followCustomer = () => fillContactFrom('n', companyField.value);
    companyField.addEventListener('change', followCustomer);
    companyField.addEventListener('blur', followCustomer);
    followCustomer();
  }
  quoteFromForm('n', 'n-calc', 'n-calc');
}

async function createOrder() {
  const body = {};
  ['order_no', 'company', 'po_number', 'product_code', 'product_name',
   'status', 'description', 'value', 'currency', 'order_date', 'promise_date',
   'owner', 'priority', 'notes'].forEach(field => {
    const input = $('#n-' + field);
    if (input) body[field] = input.value;
  });
  if (!body.order_no.trim() || !body.company.trim()) {
    toast('An order number and a customer are both required.', 'err');
    return;
  }
  body.spec = readSpecForm('n');
  try {
    const result = await postJSON('/api/orders', body);
    closeModal();
    toast(`${body.order_no} created`, 'ok');
    await reloadBoot();
    openOrder(result.id);
    if (S.view === 'orders') loadOrders();
    refreshSaved();
  } catch (err) { toast(err.message, 'err'); }
}

function companyModal(company) {
  const c = company || {};
  modal(company ? 'EDIT CUSTOMER' : 'NEW CUSTOMER', `
    <div class="formgrid">
      <div class="lbl">NAME *</div><div class="wide"><input id="co-name" value="${esc(c.name || '')}"></div>
      <div class="lbl">CODE</div><div><input id="co-code" value="${esc(c.code || '')}"></div>
      <div class="lbl">CONTACT</div><div><input id="co-contact_name" value="${esc(c.contact_name || '')}"></div>
      <div class="lbl">EMAIL</div><div><input id="co-contact_email" value="${esc(c.contact_email || '')}"></div>
      <div class="lbl">PHONE</div><div><input id="co-phone" value="${esc(c.phone || '')}"></div>

      <div class="lbl">COUNTRY <i class="fhint">puts them on the map</i></div>
      <div><select id="co-country">
        <option value="">—</option>
        ${(S.boot.countries || []).map(country => `<option value="${esc(country.code)}"
          ${country.code === (c.country || '') ? 'selected' : ''}>${esc(country.name)}</option>`).join('')}
      </select></div>
      <div class="lbl">CITY <i class="fhint">optional</i></div>
      <div><input id="co-city" list="citylist" value="${esc(c.city || '')}">
        <datalist id="citylist">
          ${(S.boot.cities || []).map(city => `<option value="${esc(city.city)}">`).join('')}
        </datalist></div>

      <div class="lbl">NOTES</div><div class="wide"><textarea id="co-notes" rows="2">${esc(c.notes || '')}</textarea></div>
    </div>
    <div class="note">Leave the position blank and it is taken from the
      country — or the city, when it is one we know. The local time on the
      dashboard follows from it.</div>`,
    [
      { label: 'CANCEL', action: closeModal },
      { label: 'SAVE', primary: true, action: async () => {
        const body = { id: c.id };
        ['name', 'code', 'contact_name', 'contact_email', 'phone', 'notes',
         'country', 'city'].forEach(f => { body[f] = $('#co-' + f).value; });
        /* Let the server place them afresh whenever the country or city
           changes, rather than keeping a position from the old one. */
        body.lat = '';
        body.lon = '';
        body.timezone = '';
        try {
          await postJSON('/api/companies', body);
          closeModal();
          toast('Customer saved', 'ok');
          await reloadBoot();
          renderCompanies();
          loadMap();
        } catch (err) { toast(err.message, 'err'); }
      } },
    ]);
}

/* -------------------------------------------------------------- keyboard */

function isTyping(target) {
  return target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
                    || target.tagName === 'SELECT');
}

document.addEventListener('keydown', event => {
  if (!splashFinished) { dismissSplash(true); return; }

  if (event.key === 'Escape') {
    if (!$('#modal').classList.contains('hidden')) { closeModal(); return; }
    if (isTyping(event.target)) { event.target.blur(); return; }
    if (S.openOrder) { closeDetail(); return; }
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    $('#cmd').focus();
    $('#cmd').select();
    return;
  }

  if (isTyping(event.target)) return;

  if (event.key === '/') { event.preventDefault(); $('#cmd').focus(); return; }

  const views = { '1': 'dash', '2': 'graph', '3': 'orders', '4': 'companies',
                  '5': 'inbox', '6': 'folders', '7': 'cases', '8': 'docs',
                  '9': 'import', '0': 'setup' };
  if (views[event.key]) { show(views[event.key]); return; }

  if (event.key === 'n' || event.key === 'N') { newOrderModal(); return; }

  if (S.view === 'orders' && S.orders.length) {
    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      S.selected = Math.min(S.selected + 1, S.orders.length - 1);
      markSelection();
    } else if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      S.selected = Math.max(S.selected - 1, 0);
      markSelection();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      openOrder(S.orders[S.selected].id);
    }
  }
});

/* ----------------------------------------------------------- global drop */

let dragDepth = 0;
window.addEventListener('dragenter', e => {
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes('Files')) return;
  dragDepth++;
  if (!e.target.closest('.dropzone')) $('#dropveil').classList.remove('hidden');
});
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $('#dropveil').classList.add('hidden');
});
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  dragDepth = 0;
  $('#dropveil').classList.add('hidden');
  if (e.target.closest('.dropzone')) return;   // its own handler deals with it
  e.preventDefault();
  const orderId = S.openOrder ? S.openOrder.id : null;
  uploadFiles(e.dataTransfer.files, orderId, () => {
    if (S.openOrder) openOrder(S.openOrder.id);
    else if (S.view === 'docs') renderDocs();
  });
});

/* ------------------------------------------------------------------ wire */

$('#cmd').addEventListener('input', e => onSearchInput(e.target.value));
$('#cmd').addEventListener('keydown', e => {
  if (e.key === 'Enter') runSearch(e.target.value);
});
$$('#nav button[data-view]').forEach(b => { b.onclick = () => show(b.dataset.view); });
$('#btn-new').onclick = newOrderModal;
$('#btn-quit').onclick = quitApp;

async function quitApp() {
  const confirmed = confirm(
    'Stop Order Tracker?\n\n'
    + 'Your data is saved as you go, so nothing is lost. Start it again from '
    + 'the desktop icon.');
  if (!confirmed) return;

  try {
    await postJSON('/api/quit', {});
  } catch (err) {
    // The server often drops the connection as it stops, which is expected.
  }
  $('#stopped').classList.remove('hidden');
}

boot();
