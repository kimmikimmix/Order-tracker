/* Disputes and defect claims, and the log of what was done about each one.
 *
 * The list answers "what is outstanding and what do I owe someone today".
 * The case itself answers "what exactly happened, and when did we say so" —
 * which is the question that actually comes up six months later, so every
 * entry keeps its date, its author and its full text.
 */

const CASES = {
  items: [],
  followUps: [],
  summary: { open: 0, overdue: 0, open_actions: 0, late_actions: 0, claim_krw: 0 },
  filter: { open: '1', status: '', q: '' },
};

const SEVERITY_COLOUR = {
  LOW: 'var(--dim)', MEDIUM: 'var(--blue)',
  HIGH: 'var(--amber)', CRITICAL: 'var(--red)',
};

/* Money in the case list. Named apart from the spec sheet's krw(), which
   prints a won sign and a bare zero; here an empty claim should read as
   nothing at all. Two scripts on one page share one set of names. */
function claimKrw(value) {
  const number = Number(value || 0);
  return number ? number.toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' KRW' : '—';
}

function claimUsd(value) {
  const rate = Number((S.boot.prefs || {}).fx_rate || 1050);
  const number = Number(value || 0);
  return number ? '$' + (number / rate).toLocaleString(undefined,
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '';
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

async function renderCases() {
  const el = $('#view-cases');
  el.innerHTML = '<div class="empty">reading the case book…</div>';
  await loadCases();
}

async function loadCases() {
  const query = new URLSearchParams();
  if (CASES.filter.open === '1') query.set('open', '1');
  if (CASES.filter.status) query.set('status', CASES.filter.status);
  if (CASES.filter.q) query.set('q', CASES.filter.q);
  query.set('days', '14');
  try {
    const result = await api('/api/cases?' + query.toString());
    CASES.items = result.cases || [];
    CASES.followUps = result.follow_ups || [];
    CASES.summary = result.summary || CASES.summary;
  } catch (err) { toast(err.message, 'err'); return; }
  paintCases();
}

function paintCases() {
  const el = $('#view-cases');
  const sum = CASES.summary;
  const statuses = S.boot.case_statuses || [];

  const tile = (label, value, sub, kind) => `
    <div class="tile ${kind || ''}">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      <div class="sub">${sub || ''}</div>
    </div>`;

  el.innerHTML = `
    <div class="tiles">
      ${tile('OPEN CASES', sum.open, 'not yet settled', sum.open ? 'amber' : '')}
      ${tile('PAST THEIR DATE', sum.overdue, 'answer overdue', sum.overdue ? 'red' : '')}
      ${tile('ACTIONS OUTSTANDING', sum.open_actions,
             `${sum.late_actions} already late`, sum.late_actions ? 'red' : 'blue')}
      ${tile('VALUE IN DISPUTE', claimKrw(sum.claim_krw), claimUsd(sum.claim_krw), 'green')}
    </div>

    <h2 class="sect">Follow-ups due</h2>
    ${CASES.followUps.length ? `
    <table class="grid">
      <thead><tr>
        <th style="width:110px">DUE</th><th style="width:110px">CASE</th>
        <th style="width:140px">${fieldLabel('product_name')}</th>
        <th style="width:180px">CUSTOMER</th>
        <th>WHAT NEEDS DOING</th><th style="width:90px"></th>
      </tr></thead>
      <tbody>
        ${CASES.followUps.map(f => `
          <tr data-case="${f.case_id}">
            <td style="color:${f.late ? 'var(--red)' : 'var(--amber)'}">
              ${esc(f.follow_up_at)}${f.late ? ' · LATE' : ''}</td>
            <td>${esc(f.ref)}</td>
            <td>${f.order_no ? esc(orderName(f)) : '—'}</td>
            <td>${esc(f.company || '—')}</td>
            <td>${esc(f.summary)}
              <span class="subtle">${esc(f.title || '')}</span></td>
            <td><button class="btn" data-done="${f.id}">DONE</button></td>
          </tr>`).join('')}
      </tbody>
    </table>` : '<div class="empty">Nothing to chase in the next two weeks.</div>'}

    <h2 class="sect">Cases</h2>
    <div class="filterbar">
      <button class="btn ${CASES.filter.open === '1' ? 'primary' : ''}" data-open="1">OPEN ONLY</button>
      <button class="btn ${CASES.filter.open === '' ? 'primary' : ''}" data-open="">ALL</button>
      <select id="c-status">
        <option value="">every status</option>
        ${statuses.map(s => `<option value="${esc(s)}"
          ${CASES.filter.status === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
      </select>
      <input id="c-q" placeholder="title, reference, order or customer…"
             value="${esc(CASES.filter.q)}" style="width:280px">
      <span class="spacer"></span>
      <button class="btn accent" id="c-new">OPEN A CASE</button>
    </div>

    ${CASES.items.length ? `
    <table class="grid">
      <thead><tr>
        <th style="width:100px">CASE</th><th style="width:100px">OPENED</th>
        <th>TITLE</th><th style="width:170px">CUSTOMER</th>
        <th style="width:120px">${fieldLabel('product_name')}</th>
        <th style="width:110px">KIND</th>
        <th style="width:90px">SEVERITY</th><th style="width:150px">STATUS</th>
        <th class="num" style="width:70px">QTY</th>
        <th class="num" style="width:120px">CLAIM</th>
        <th style="width:120px">NEXT ACTION</th>
      </tr></thead>
      <tbody>
        ${CASES.items.map(c => `
          <tr data-case="${c.id}">
            <td style="color:var(--amber)">${esc(c.ref)}</td>
            <td style="color:var(--dim)">${esc(c.opened_at || '')}</td>
            <td><b>${esc(c.title)}</b>
              ${c.open_actions ? `<span class="chip">${c.open_actions} ACTION(S)</span>` : ''}</td>
            <td>${esc(c.company || '—')}</td>
            <td>${c.order_no ? esc(orderName(c)) : '—'}</td>
            <td>${esc(c.kind)}</td>
            <td style="color:${SEVERITY_COLOUR[c.severity] || 'var(--dim)'}">${esc(c.severity)}</td>
            <td><span class="chip ${c.open ? 'a-DUESOON' : 'ok'}">${esc(c.status)}</span>
              ${c.overdue ? '<span class="chip a-OVERDUE">LATE</span>' : ''}</td>
            <td class="num">${c.qty_affected || '—'}</td>
            <td class="num">${claimKrw(c.claim_krw)}</td>
            <td style="color:var(--dim)">${esc(c.next_action_at || '—')}</td>
          </tr>`).join('')}
      </tbody>
    </table>` : `<div class="empty">No cases${CASES.filter.open === '1'
        ? ' are open' : ' on file'}. Open one from here or from an order.</div>`}`;

  $('#c-new').onclick = () => newCaseModal({});
  $('#c-status').onchange = event => {
    CASES.filter.status = event.target.value; loadCases();
  };
  let typing = null;
  $('#c-q').oninput = event => {
    clearTimeout(typing);
    const text = event.target.value;
    typing = setTimeout(() => { CASES.filter.q = text; loadCases(); }, 250);
  };
  $$('#view-cases [data-open]').forEach(button => {
    button.onclick = () => { CASES.filter.open = button.dataset.open; loadCases(); };
  });

  el.onclick = async event => {
    const done = event.target.closest('[data-done]');
    if (done) {
      event.stopPropagation();
      await postJSON('/api/case-entries/' + done.dataset.done, { done: true });
      toast('Ticked off', 'ok');
      loadCases(); reloadBoot();
      return;
    }
    const row = event.target.closest('[data-case]');
    if (row) openCase(Number(row.dataset.case));
  };
}

/* ---- one case ---- */

function caseFieldsHTML(prefix, values, orderOptionsHTML) {
  const kinds = S.boot.case_kinds || ['OTHER'];
  const severities = S.boot.case_severities || ['MEDIUM'];
  const statuses = S.boot.case_statuses || ['OPEN'];
  const pick = (list, chosen) => list.map(item =>
    `<option ${item === chosen ? 'selected' : ''}>${esc(item)}</option>`).join('');

  return `
    <div class="formgrid">
      <div class="lbl">TITLE *</div>
      <div class="wide"><input id="${prefix}-title" value="${esc(values.title || '')}"
        placeholder="what is wrong, in one line"></div>

      ${orderOptionsHTML ? `
      <div class="lbl">ORDER *</div>
      <div class="wide"><select id="${prefix}-order_id">${orderOptionsHTML}</select></div>` : ''}

      <div class="lbl">KIND</div>
      <div><select id="${prefix}-kind">${pick(kinds, values.kind)}</select></div>
      <div class="lbl">SEVERITY</div>
      <div><select id="${prefix}-severity">${pick(severities, values.severity || 'MEDIUM')}</select></div>

      <div class="lbl">STATUS</div>
      <div><select id="${prefix}-status">${pick(statuses, values.status)}</select></div>
      <div class="lbl">HANDLED BY</div>
      <div><input id="${prefix}-owner" value="${esc(values.owner || '')}"></div>

      <div class="lbl">OPENED</div>
      <div><input id="${prefix}-opened_at" type="date"
        value="${esc(values.opened_at || today())}"></div>
      <div class="lbl">ANSWER DUE</div>
      <div><input id="${prefix}-due_at" type="date" value="${esc(values.due_at || '')}"></div>

      <div class="lbl">QTY AFFECTED</div>
      <div><input id="${prefix}-qty_affected" type="number"
        value="${values.qty_affected != null ? values.qty_affected : ''}"></div>
      <div class="lbl">VALUE CLAIMED (KRW)</div>
      <div><input id="${prefix}-claim_krw" type="number" step="1"
        value="${values.claim_krw != null ? values.claim_krw : ''}"></div>

      <div class="lbl">LOT / BATCH</div>
      <div class="wide"><input id="${prefix}-lot_ref" value="${esc(values.lot_ref || '')}"
        placeholder="which shipment or panel lot"></div>

      <div class="lbl">WHAT IS WRONG</div>
      <div class="wide"><textarea id="${prefix}-detail" rows="3">${esc(values.detail || '')}</textarea></div>
      <div class="lbl">ROOT CAUSE</div>
      <div class="wide"><textarea id="${prefix}-root_cause" rows="2">${esc(values.root_cause || '')}</textarea></div>
      <div class="lbl">RESOLUTION</div>
      <div class="wide"><textarea id="${prefix}-resolution" rows="2">${esc(values.resolution || '')}</textarea></div>
    </div>`;
}

function readCaseFields(prefix, withOrder) {
  const value = id => {
    const node = $('#' + prefix + '-' + id);
    return node ? node.value : '';
  };
  const out = {
    title: value('title'), kind: value('kind'), severity: value('severity'),
    status: value('status'), owner: value('owner'),
    opened_at: value('opened_at'), due_at: value('due_at'),
    qty_affected: value('qty_affected'), claim_krw: value('claim_krw'),
    lot_ref: value('lot_ref'), detail: value('detail'),
    root_cause: value('root_cause'), resolution: value('resolution'),
  };
  if (withOrder) out.order_id = value('order_id');
  return out;
}

async function newCaseModal(seed) {
  await loadInboxOrders();
  const orderId = seed.orderId || (S.openOrder ? S.openOrder.id : '');
  modal('OPEN A CASE', `
    <div class="note">A case is how a defect or a dispute is chased: what is
      wrong, how much is at stake, and every call and mail about it from here
      on. It always belongs to an order.</div>
    ${caseFieldsHTML('nc', {
      title: seed.title || '', kind: seed.kind || '', detail: seed.detail || '',
      status: (S.boot.case_statuses || ['OPEN'])[0],
    }, orderOptions(orderId))}
  `, [
    { label: 'CANCEL', action: closeModal },
    { label: 'OPEN THE CASE', primary: true, action: async () => {
        const body = readCaseFields('nc', true);
        try {
          const result = await postJSON('/api/cases', body);
          closeModal();
          toast('Case ' + result.case.ref + ' opened', 'ok');
          if (seed.email) {
            await postJSON(`/api/cases/${result.id}/entries`, {
              kind: seed.email.direction === 'OUT' ? 'EMAIL OUT' : 'EMAIL IN',
              happened_at: (seed.email.sent_at || '').slice(0, 10),
              who: seed.email.from_name || seed.email.from_email,
              summary: seed.email.subject || '(no subject)',
              detail: seed.email.summary || '',
              email_id: seed.email.id, doc_id: seed.email.doc_id,
            });
          }
          reloadBoot();
          if (S.view === 'cases') loadCases();
          if (S.openOrder) openOrder(S.openOrder.id);
          openCase(result.id);
        } catch (err) { toast(err.message, 'err'); }
      } },
  ]);
}

const ENTRY_COLOUR = {
  'EMAIL IN': 'var(--blue)', 'EMAIL OUT': 'var(--blue)',
  CALL: 'var(--green)', MEETING: 'var(--green)', VISIT: 'var(--green)',
  ACTION: 'var(--amber)', DECISION: 'var(--amber)',
};

async function openCase(caseId) {
  let item;
  try { item = await api('/api/cases/' + caseId); }
  catch (err) { toast(err.message, 'err'); return; }
  setHash('case/' + caseId);

  const kinds = S.boot.case_entry_kinds || ['NOTE'];

  modal(`${esc(item.ref)} — ${esc(item.company || '')}
         ${item.order_no ? '· ' + esc(orderName(item)) : ''}`, `
    <div class="mtabs">
      <button data-ctab="log" class="active">LOG (${item.entries.length})</button>
      <button data-ctab="case">THE CASE</button>
      <span class="spacer"></span>
      <a class="btn" href="/print/case/${item.id}" target="_blank">PRINT REPORT</a>
    </div>

    <div class="mpane" id="cpane-log">
      <div class="formgrid entryform">
        <div class="lbl">WHAT HAPPENED *</div>
        <div class="wide"><input id="ce-summary"
          placeholder="e.g. called Ha-eun, agreed to rework 12 boards"></div>
        <div class="lbl">KIND</div>
        <div><select id="ce-kind">${kinds.map(k =>
          `<option>${esc(k)}</option>`).join('')}</select></div>
        <div class="lbl">WHEN</div>
        <div><input id="ce-happened_at" type="date" value="${today()}"></div>
        <div class="lbl">WHO</div>
        <div><input id="ce-who" placeholder="who you spoke to"></div>
        <div class="lbl">FOLLOW UP BY</div>
        <div><input id="ce-follow_up_at" type="date"></div>
        <div class="lbl">DETAIL</div>
        <div class="wide"><textarea id="ce-detail" rows="2"
          placeholder="what was said, agreed, or promised"></textarea></div>
      </div>
      <div class="filterbar" style="padding:4px 0 12px">
        <button class="btn primary" id="ce-add">ADD TO THE LOG</button>
        <button class="btn hidden" id="ce-cancel">CANCEL</button>
        <span class="note" id="ce-hint">Every entry keeps its date.
          EDIT brings one back up here to correct.</span>
      </div>

      <div class="timeline caselog">
        ${item.entries.map(entry => `
          <div class="ev ${entry.late ? 'late' : ''}">
            <div>
              <span class="chip" style="color:${ENTRY_COLOUR[entry.kind] || 'var(--dim)'}">
                ${esc(entry.kind)}</span>
              <b>${esc(entry.summary)}</b>
              ${entry.detail ? `<div class="subtle">${esc(entry.detail)}</div>` : ''}
              ${entry.filename ? `<div class="subtle">file:
                <a href="/api/documents/${entry.doc_id}/file" target="_blank"
                   style="color:var(--blue)">${esc(entry.filename)}</a></div>` : ''}
              ${entry.follow_up_at ? `
                <div class="followup">
                  ${entry.done_at
                    ? `<span style="color:var(--green)">done ${esc(String(entry.done_at).slice(0, 10))}</span>`
                    : `<span style="color:${entry.late ? 'var(--red)' : 'var(--amber)'}">
                         follow up by ${esc(entry.follow_up_at)}${entry.late ? ' · LATE' : ''}</span>`}
                  <button class="btn" data-toggle="${entry.id}"
                    >${entry.done_at ? 'REOPEN' : 'MARK DONE'}</button>
                </div>` : ''}
            </div>
            <div class="when">${esc(entry.happened_at || '')}
              ${entry.who ? ' · ' + esc(entry.who) : ''}
              <button class="btn" data-edit-entry="${entry.id}">EDIT</button>
              <button class="btn danger" data-del-entry="${entry.id}">DEL</button></div>
          </div>`).join('') || '<div class="note">Nothing logged yet.</div>'}
      </div>
    </div>

    <div class="mpane hidden" id="cpane-case">
      ${caseFieldsHTML('ec', item, '')}
      <div class="note">Opened ${esc(item.opened_at || '')}
        ${item.age_days != null ? `· ${item.age_days} days ago` : ''}
        ${item.closed_at ? `· closed ${esc(item.closed_at)}` : ''}
        ${item.claim_krw ? `· claim ${claimKrw(item.claim_krw)} ${claimUsd(item.claim_krw)}` : ''}</div>
      <div class="filterbar" style="padding:8px 0 0">
        <button class="btn danger" id="ec-delete">DELETE THIS CASE</button>
      </div>
    </div>
  `, [
    { label: 'CLOSE', action: closeModal },
    { label: 'SAVE THE CASE', primary: true, action: async () => {
        try {
          await postJSON('/api/cases/' + caseId, readCaseFields('ec', false));
          toast('Case saved', 'ok');
          closeModal();
          if (S.view === 'cases') loadCases();
          if (S.openOrder) openOrder(S.openOrder.id);
          reloadBoot(); refreshSaved();
        } catch (err) { toast(err.message, 'err'); }
      } },
  ]);

  $$('#modal [data-ctab]').forEach(button => {
    button.onclick = () => {
      $$('#modal [data-ctab]').forEach(b => b.classList.toggle('active', b === button));
      $$('#modal .mpane').forEach(pane =>
        pane.classList.toggle('hidden', pane.id !== 'cpane-' + button.dataset.ctab));
    };
  });

  /* EDIT puts an entry back into the box it was typed in; the button
     then saves the correction instead of adding another line. */
  let editing = null;

  const stopEditing = () => {
    editing = null;
    ['ce-summary', 'ce-who', 'ce-detail', 'ce-follow_up_at']
      .forEach(id => { $('#' + id).value = ''; });
    $('#ce-happened_at').value = today();
    $('#ce-add').textContent = 'ADD TO THE LOG';
    $('#ce-cancel').classList.add('hidden');
  };

  $('#ce-cancel').onclick = stopEditing;

  $('#ce-add').onclick = async () => {
    const body = {
      summary: $('#ce-summary').value, kind: $('#ce-kind').value,
      happened_at: $('#ce-happened_at').value, who: $('#ce-who').value,
      detail: $('#ce-detail').value, follow_up_at: $('#ce-follow_up_at').value,
    };
    try {
      if (editing) await postJSON('/api/case-entries/' + editing, body);
      else await postJSON(`/api/cases/${caseId}/entries`, body);
      toast(editing ? 'Corrected' : 'Added to the log', 'ok');
      openCase(caseId);
      if (S.view === 'cases') loadCases();
      reloadBoot(); refreshSaved();
    } catch (err) { toast(err.message, 'err'); }
  };

  $('#ec-delete').onclick = async () => {
    if (!confirm('Delete this case and its whole log? This cannot be undone.')) return;
    await api('/api/cases/' + caseId, { method: 'DELETE' });
    closeModal();
    toast('Case deleted', 'ok');
    if (S.view === 'cases') loadCases();
    if (S.openOrder) openOrder(S.openOrder.id);
    reloadBoot();
  };

  $('.caselog', $('#modal')).onclick = async event => {
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
      const wasDone = toggle.textContent.trim() === 'REOPEN';
      await postJSON('/api/case-entries/' + toggle.dataset.toggle, { done: !wasDone });
      openCase(caseId); reloadBoot();
      return;
    }
    const edit = event.target.closest('[data-edit-entry]');
    if (edit) {
      const entry = item.entries.find(
        e => e.id === Number(edit.dataset.editEntry));
      if (!entry) return;
      editing = entry.id;
      $('#ce-summary').value = entry.summary || '';
      $('#ce-kind').value = entry.kind || '';
      $('#ce-happened_at').value = String(entry.happened_at || '').slice(0, 10);
      $('#ce-who').value = entry.who || '';
      $('#ce-detail').value = entry.detail || '';
      $('#ce-follow_up_at').value = entry.follow_up_at || '';
      $('#ce-add').textContent = 'SAVE THE CHANGE';
      $('#ce-cancel').classList.remove('hidden');
      $('#ce-summary').focus();
      return;
    }
    const remove = event.target.closest('[data-del-entry]');
    if (remove) {
      if (!confirm('Remove this entry from the log?')) return;
      await api('/api/case-entries/' + remove.dataset.delEntry, { method: 'DELETE' });
      openCase(caseId);
    }
  };
}
