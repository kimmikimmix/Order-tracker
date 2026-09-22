/* The settings page: everything you can change without touching code.

   The lists — panel sizes, surface finishes, materials — are edited as plain
   text, one entry per line, because that is quicker than any grid of boxes
   and it is obvious how to add a line. */

const SetupView = { data: null };

const lines = list => (list || []).join('\n');
const fromLines = text => String(text || '').split('\n')
  .map(s => s.trim()).filter(Boolean);

function panelLines(panels) {
  return (panels || []).map(p => `${p.code} | ${p.x} | ${p.y}`).join('\n');
}

function panelsFromLines(text) {
  return fromLines(text).map(line => {
    const parts = line.split('|').map(s => s.trim());
    return { code: parts[0], x: Number(parts[1]) || 0, y: Number(parts[2]) || 0 };
  }).filter(p => p.code);
}

const when = stamp => stamp ? String(stamp).replace('T', ' ') : 'never';

async function renderSetup() {
  const el = $('#view-setup');
  el.innerHTML = '<div class="note">loading…</div>';

  let data;
  try {
    data = await api('/api/prefs');
    data.status = await api('/api/status');
  } catch (err) { el.innerHTML = `<div class="empty">${esc(err.message)}</div>`; return; }
  SetupView.data = data;

  const p = data.prefs;
  const st = data.status;
  const box = (id, value, attrs = '') =>
    `<input id="set-${id}" value="${esc(value ?? '')}" ${attrs}>`;
  const numbox = (id, value) =>
    `<input id="set-${id}" type="number" step="any" value="${value ?? ''}">`;
  const area = (id, value, rows = 6) =>
    `<textarea id="set-${id}" rows="${rows}" spellcheck="false">${esc(value)}</textarea>`;

  el.innerHTML = `
    <div class="setupcols">

      <section class="card">
        <h2 class="sect">Where your data lives</h2>
        <table class="grid calc"><tbody>
          <tr><td class="ck">ORDERS &amp; DOCUMENTS</td>
              <td class="path">${esc(data.paths.data)}</td></tr>
          <tr><td class="ck">DOCUMENT FILES</td>
              <td class="path">${esc(data.paths.documents)}</td></tr>
          <tr><td class="ck">THE APP ITSELF</td>
              <td class="path">${esc(data.paths.app)}</td></tr>
          <tr><td class="ck">PORTABLE MODE</td>
              <td>${data.paths.portable
                    ? '<span class="chip a-ONHOLD">ON</span> data stays in the app folder'
                    : 'off — the data folder is remembered separately'}</td></tr>
        </tbody></table>
      </section>

      <section class="card">
        <h2 class="sect">Move it to another drive</h2>
        <div class="note" style="margin-bottom:8px">Copies the app and
          everything you have stored to a folder you pick, sets the copy to
          keep its data in its own folder, and points your desktop icon at
          it. Nothing here is deleted.</div>
        <div class="formgrid">
          <div class="lbl">NEW FOLDER</div>
          <div class="wide"><input id="set-move_dir"
            placeholder="G:\\my folder\\Order Tracker"></div>
        </div>
        <div class="filterbar" style="padding:8px 0">
          <button class="btn" id="set-move-check">CHECK THE FOLDER</button>
          <button class="btn primary" id="set-move-go">COPY EVERYTHING THERE</button>
        </div>
        <div id="set-move-out"></div>
      </section>

      <section class="card">
        <h2 class="sect">Saving and backup</h2>
        <table class="grid calc"><tbody>
          <tr><td class="ck">LAST SAVED</td>
              <td><b id="set-lastsaved">${esc(when(st.saved_at))}</b> UTC</td></tr>
          <tr><td class="ck">ORDER BOOK SIZE</td>
              <td>${bytes(st.db_size || 0)}</td></tr>
          <tr><td class="ck">LAST BACKUP</td>
              <td>${esc(when(st.last_backup_at))}</td></tr>
        </tbody></table>

        <div class="formgrid" style="margin-top:10px">
          <div class="lbl">BACKUP FOLDER</div>
          <div class="wide">${box('backup_dir', p.backup_dir,
            'placeholder="D:\\\\Backups  or  a network folder"')}</div>
          <div class="lbl">KEEP</div>
          <div>${numbox('backup_keep', p.backup_keep)}</div>
          <label class="lbl chk" for="set-backup_on_start">
            <input type="checkbox" id="set-backup_on_start"
              ${p.backup_on_start ? 'checked' : ''}> BACK UP AT STARTUP</label>
          <div></div>
        </div>
        <div class="filterbar" style="padding:8px 0">
          <button class="btn primary" id="set-backup-now">BACK UP NOW</button>
          <span class="note" id="set-backup-msg"></span>
        </div>
        ${st.snapshots && st.snapshots.length ? `
          <div class="note">${st.snapshots.length} copies in
            ${esc(st.folder)}:</div>
          <div class="doclist">
            ${st.snapshots.slice(0, 6).map(s => `<div class="docrow">
              <span class="dname">${esc(s.name)}</span>
              <span class="dmeta">${bytes(s.size)}</span></div>`).join('')}
          </div>` : ''}
      </section>

      <section class="card">
        <h2 class="sect">Money</h2>
        <div class="formgrid">
          <div class="lbl">EXCHANGE RATE <i class="fhint">KRW per USD</i></div>
          <div>${numbox('fx_rate', p.fx_rate)}</div>
          <div class="lbl">INFLATION <i class="fhint">× multiplier</i></div>
          <div>${numbox('inflation_rate', p.inflation_rate)}</div>
          <div class="lbl">MARKUP <i class="fhint">%</i></div>
          <div>${numbox('markup_pct', p.markup_pct)}</div>
          <div class="lbl">STENCIL PRICE <i class="fhint">KRW each</i></div>
          <div>${numbox('stencil_unit_krw', p.stencil_unit_krw)}</div>
          <div class="lbl">STENCIL RANGE <i class="fhint">low / high</i></div>
          <div style="display:flex;gap:6px">
            ${numbox('stencil_min_krw', p.stencil_min_krw)}
            ${numbox('stencil_max_krw', p.stencil_max_krw)}</div>
        </div>
        <div class="note">These are the starting values for a new order. An
          order keeps the rates it was quoted at, so changing them here never
          moves an old quote.</div>
      </section>

      <section class="card">
        <h2 class="sect">Alerts</h2>
        <div class="formgrid">
          <div class="lbl">DUE SOON <i class="fhint">days ahead</i></div>
          <div>${numbox('due_soon_days', p.due_soon_days)}</div>
          <div class="lbl">STALLED <i class="fhint">days untouched</i></div>
          <div>${numbox('stalled_days', p.stalled_days)}</div>
          <div class="lbl">PANEL MARGIN <i class="fhint">mm per side</i></div>
          <div>${numbox('panel_margin_mm', p.panel_margin_mm)}</div>
          <div class="lbl">HOME COUNTRY</div>
          <div><select id="set-home_country">
            ${(S.boot.countries || []).map(c => `<option value="${esc(c.code)}"
              ${c.code === p.home_country ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          </select></div>
        </div>
      </section>

      <section class="card">
        <h2 class="sect">Welcome screen</h2>
        <div class="formgrid">
          <div class="lbl">YOUR NAME</div>
          <div class="wide">${box('welcome_name', data.welcome.name,
            'placeholder="shown under WELCOME at startup"')}</div>
          <label class="lbl chk" for="set-welcome_show">
            <input type="checkbox" id="set-welcome_show"
              ${data.welcome.show ? 'checked' : ''}> SHOW IT AT STARTUP</label>
          <div></div>
        </div>
      </section>

      <section class="card wide2">
        <h2 class="sect">Lists on the order form</h2>
        <div class="listcols">
          <div><div class="lbl">WORKING PANELS
              <i class="fhint">CODE | width | height, in mm</i></div>
            ${area('panel_sizes', panelLines(p.panel_sizes), 7)}</div>
          <div><div class="lbl">SURFACE FINISHES</div>
            ${area('surface_finishes', lines(p.surface_finishes), 7)}</div>
          <div><div class="lbl">CCL MATERIALS</div>
            ${area('ccl_materials', lines(p.ccl_materials), 7)}</div>
          <div><div class="lbl">PRODUCT TYPES</div>
            ${area('product_types', lines(p.product_types), 3)}
            <div class="lbl" style="margin-top:8px">CLASSES</div>
            ${area('ipc_classes', lines(p.ipc_classes), 3)}</div>
        </div>
      </section>
    </div>

    <div class="filterbar setupbar">
      <button class="btn primary" id="set-save">SAVE SETTINGS</button>
      <button class="btn" id="set-reload">DISCARD CHANGES</button>
      <span class="spacer"></span>
      <button class="btn danger" id="set-reset">RESET EVERYTHING TO DEFAULTS</button>
    </div>`;

  $('#set-save').onclick = saveSetup;
  $('#set-reload').onclick = renderSetup;
  $('#set-reset').onclick = async () => {
    if (!confirm('Put every setting back to the way it shipped?\n\n'
                 + 'Your orders and documents are not touched.')) return;
    await postJSON('/api/prefs/reset', {});
    toast('Settings reset', 'ok');
    await reloadBoot();
    renderSetup();
  };
  $('#set-backup-now').onclick = backupNow;
  $('#set-move-check').onclick = () => checkMove(false);
  $('#set-move-go').onclick = () => checkMove(true);
}

/* ---- moving to another drive ---- */

function moveOut(html) { $('#set-move-out').innerHTML = html; }

async function checkMove(thenCopy) {
  const folder = $('#set-move_dir').value.trim();
  if (!folder) {
    toast('Type the folder you want it copied to first.', 'err');
    $('#set-move_dir').focus();
    return;
  }

  moveOut('<div class="note">checking…</div>');
  let report;
  try {
    report = await postJSON('/api/move/check', { folder });
  } catch (err) { moveOut(`<div class="moveerr">${esc(err.message)}</div>`); return; }

  if (report.problem) {
    moveOut(`<div class="moveerr">${esc(report.problem)}</div>`);
    return;
  }

  const lines = [
    ['THE APP', report.source],
    ['WOULD GO TO', report.destination],
    ['YOUR ORDERS', `${esc(report.data_source)}<br>
      <i>${esc(report.stored || 'nothing stored yet')}</i>`],
    ['WOULD END UP IN', report.data_destination],
  ];
  const table = `<table class="grid calc"><tbody>${lines.map(
    ([k, v]) => `<tr><td class="ck">${k}</td><td class="path">${v}</td></tr>`
  ).join('')}</tbody></table>`;

  if (!thenCopy) {
    moveOut(table + `<div class="note">That folder can be written to.
      Nothing has been copied — press COPY EVERYTHING THERE when you are
      ready.${report.not_empty ? ' It is not empty; files with the same '
        + 'names will be overwritten.' : ''}</div>`);
    return;
  }

  const sure = confirm(
    `Copy Order Tracker to:\n\n${report.destination}\n\n`
    + `Your orders (${report.stored || 'none yet'}) come too.\n`
    + 'Nothing in the current folder is deleted.');
  if (!sure) { moveOut(table); return; }

  moveOut(table + '<div class="note">copying… this can take a minute on a '
    + 'slow drive. Leave this page open.</div>');

  let result;
  try {
    result = await postJSON('/api/move', { folder });
  } catch (err) {
    moveOut(table + `<div class="moveerr">${esc(err.message)}</div>`);
    return;
  }

  moveOut(`
    <div class="movedone">
      <b>Done — it now lives in ${esc(result.destination)}</b>
      <ul>${result.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ul>
      <p>To start using the copy: click <b>QUIT</b> at the top of this page,
        then open Order Tracker from your desktop icon — it points at the new
        folder now. Check the bottom of the screen says the new location.</p>
      <p class="note">The folder it was copied from is untouched. Delete
        ${esc(result.source)} yourself once you are happy.</p>
    </div>`);
  toast('Copied to ' + result.destination, 'ok');
}

async function saveSetup() {
  const value = id => $('#set-' + id).value;
  const number = id => Number($('#set-' + id).value);
  const body = {
    fx_rate: number('fx_rate'),
    inflation_rate: number('inflation_rate'),
    markup_pct: number('markup_pct'),
    stencil_unit_krw: number('stencil_unit_krw'),
    stencil_min_krw: number('stencil_min_krw'),
    stencil_max_krw: number('stencil_max_krw'),
    due_soon_days: number('due_soon_days'),
    stalled_days: number('stalled_days'),
    panel_margin_mm: number('panel_margin_mm'),
    home_country: value('home_country'),
    backup_dir: value('backup_dir'),
    backup_keep: number('backup_keep'),
    backup_on_start: $('#set-backup_on_start').checked,
    panel_sizes: panelsFromLines(value('panel_sizes')),
    surface_finishes: fromLines(value('surface_finishes')),
    ccl_materials: fromLines(value('ccl_materials')),
    product_types: fromLines(value('product_types')),
    ipc_classes: fromLines(value('ipc_classes')),
    welcome: { name: value('welcome_name'), show: $('#set-welcome_show').checked },
  };
  try {
    await postJSON('/api/prefs', body);
    toast('Settings saved', 'ok');
    await reloadBoot();
    renderSetup();
  } catch (err) { toast(err.message, 'err'); }
}

async function backupNow() {
  const message = $('#set-backup-msg');
  const folder = $('#set-backup_dir').value.trim();
  if (!folder) {
    toast('Type a backup folder first, then press BACK UP NOW.', 'err');
    return;
  }
  message.textContent = 'copying…';
  try {
    /* Save the folder first so the next startup backup goes to the same
       place as the one about to be taken. */
    await postJSON('/api/prefs', { backup_dir: folder });
    const result = await postJSON('/api/backup', { folder });
    message.textContent = `saved ${bytes(result.size)} to ${result.path}`;
    toast('Backup written', 'ok');
    renderSetup();
  } catch (err) {
    message.textContent = '';
    toast(err.message, 'err');
  }
}
