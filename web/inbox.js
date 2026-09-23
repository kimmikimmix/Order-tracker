/* The inbox: saved emails, read and filed.
 *
 * Nothing here talks to a mail server. Emails arrive as files you drop on
 * the page, and everything shown about them — the summary, the subject
 * matter, the customer it was matched to — was worked out on this machine
 * by the code in mail.py. The reasons for every match are shown next to it,
 * because a filing decision you cannot see the reason for is one you cannot
 * correct.
 */

const MAIL = {
  items: [],
  tray: { total: 0, needs_review: 0, unfiled: 0, by_category: {} },
  filter: { review: 'all', category: '', direction: '', q: '' },
  orders: null,            // filled the first time a mail needs filing
};

function mailWhen(item) {
  const raw = item.sent_at || item.filed_at || '';
  return String(raw).slice(0, 16).replace('T', ' ');
}

function mailWho(item) {
  return item.from_name || item.from_email || 'unknown sender';
}

/* Which way the mail went. The guess is from your own addresses; a person
   can say otherwise, and then it stays said. */
function directionChip(item) {
  return item.direction === 'OUT'
    ? '<span class="chip dir-out">SENT</span>'
    : '<span class="chip dir-in">IN</span>';
}

function confidenceChip(item) {
  if (!item.order_id && !item.company_id) {
    return '<span class="chip a-NOPO">NO MATCH</span>';
  }
  if (item.needs_review) {
    return `<span class="chip a-DUESOON">CHECK ${Math.round(item.confidence * 100)}%</span>`;
  }
  return `<span class="chip ok">FILED ${Math.round(item.confidence * 100)}%</span>`;
}

async function loadInboxOrders() {
  if (MAIL.orders) return MAIL.orders;
  const result = await api('/api/orders?closed=1&sort=order_no&dir=asc');
  MAIL.orders = result.orders || [];
  return MAIL.orders;
}

function orderOptions(selectedId) {
  const rows = (MAIL.orders || []).map(o =>
    `<option value="${o.id}" ${Number(selectedId) === o.id ? 'selected' : ''}>
       ${esc(o.order_no)} — ${esc(o.company)}${o.po_number ? ' · PO ' + esc(o.po_number) : ''}
     </option>`).join('');
  return `<option value="">— not filed against an order —</option>${rows}`;
}

async function renderInbox() {
  const el = $('#view-inbox');
  el.innerHTML = '<div class="empty">reading the tray…</div>';
  await loadInbox();
}

async function loadInbox() {
  const query = new URLSearchParams();
  if (MAIL.filter.review !== 'all') query.set('review', MAIL.filter.review);
  if (MAIL.filter.category) query.set('category', MAIL.filter.category);
  if (MAIL.filter.direction) query.set('direction', MAIL.filter.direction);
  if (MAIL.filter.q) query.set('q', MAIL.filter.q);

  try {
    const result = await api('/api/mail?' + query.toString());
    MAIL.items = result.mail || [];
    MAIL.tray = result.tray || MAIL.tray;
  } catch (err) {
    toast(err.message, 'err');
    return;
  }
  paintInbox();
}

function paintInbox() {
  const el = $('#view-inbox');
  const categories = S.boot.mail_categories || [];
  const f = MAIL.filter;

  el.innerHTML = `
    <div class="dropzone" id="m-drop">
      Drop saved emails here — <b>.msg</b> from Outlook or <b>.eml</b> from
      anything else. They are read on this machine: sender, subject, a short
      summary, and any attachment worth keeping.
      <input type="file" id="m-file" multiple class="hidden"
             accept=".msg,.eml,.mht,.mhtml,.txt">
    </div>

    <div class="filterbar">
      <span class="note">To save one: in Outlook, drag the email into a
        folder, or File → Save As → Outlook Message Format.</span>
      <span class="spacer"></span>
      <span class="note">${MAIL.tray.total} in the tray ·
        <b style="color:${MAIL.tray.needs_review ? 'var(--amber)' : 'var(--dim)'}">
          ${MAIL.tray.needs_review} to check</b></span>
    </div>

    <div class="filterbar">
      <button class="btn ${f.review === 'all' ? 'primary' : ''}" data-rev="all">ALL</button>
      <button class="btn ${f.review === '1' ? 'primary' : ''}" data-rev="1">NEEDS CHECKING</button>
      <button class="btn ${f.review === '0' ? 'primary' : ''}" data-rev="0">FILED</button>
      <select id="m-cat">
        <option value="">every subject</option>
        ${categories.map(c => `
          <option value="${esc(c)}" ${f.category === c ? 'selected' : ''}>
            ${esc(c)}${MAIL.tray.by_category[c] ? ' (' + MAIL.tray.by_category[c] + ')' : ''}
          </option>`).join('')}
      </select>
      <select id="m-dir">
        <option value="">in and out</option>
        <option value="IN" ${f.direction === 'IN' ? 'selected' : ''}>received</option>
        <option value="OUT" ${f.direction === 'OUT' ? 'selected' : ''}>sent</option>
      </select>
      <input id="m-q" placeholder="sender, subject or summary…" value="${esc(f.q)}"
             style="width:260px">
      <span class="spacer"></span>
      <button class="btn" id="m-refresh">REFRESH</button>
    </div>

    ${MAIL.items.length ? `
    <table class="grid mailgrid">
      <thead><tr>
        <th style="width:120px">WHEN</th>
        <th style="width:170px">FROM</th>
        <th>SUBJECT &amp; SUMMARY</th>
        <th style="width:110px">ABOUT</th>
        <th style="width:180px">FILED TO</th>
        <th style="width:110px">MATCH</th>
      </tr></thead>
      <tbody>
        ${MAIL.items.map(item => `
          <tr data-mail="${item.id}" class="${item.needs_review ? 'needsreview' : ''}">
            <td style="color:var(--dim)">${esc(mailWhen(item))}</td>
            <td>${directionChip(item)} ${esc(mailWho(item))}
              <div class="subtle">${esc(item.from_email || '')}</div></td>
            <td><b>${esc(item.subject || '(no subject)')}</b>
              <div class="subtle">${esc(item.summary || 'nothing readable in the body')}</div>
              ${item.attachments ? `<span class="chip">${item.attachments} ATTACHMENT(S)</span>` : ''}
            </td>
            <td><span class="chip k-${esc(item.category)}">${esc(item.category)}</span></td>
            <td>${item.order_no
                  ? `<a href="#order/${item.order_id}" class="ordlink">${esc(item.order_no)}</a>`
                  : (item.folder_ref
                      ? `<a href="#folder/${item.thread_id}" class="ordlink">${esc(item.folder_ref)}</a>`
                      : '<span class="subtle">no order</span>')}
              <div class="subtle">${esc(item.company || 'no customer')}
                ${item.order_no && item.folder_ref
                  ? '· ' + esc(item.folder_ref) : ''}</div></td>
            <td>${confidenceChip(item)}</td>
          </tr>`).join('')}
      </tbody>
    </table>` : `
    <div class="empty">
      ${f.review === '1' ? 'Nothing is waiting to be checked.'
                         : 'No emails yet. Drop some above.'}
    </div>`}`;

  wireMailDrop();

  $('#m-refresh').onclick = loadInbox;
  $('#m-cat').onchange = event => {
    MAIL.filter.category = event.target.value;
    loadInbox();
  };
  $('#m-dir').onchange = event => {
    MAIL.filter.direction = event.target.value;
    loadInbox();
  };
  let typing = null;
  $('#m-q').oninput = event => {
    clearTimeout(typing);
    const text = event.target.value;
    typing = setTimeout(() => { MAIL.filter.q = text; loadInbox(); }, 250);
  };
  $$('#view-inbox [data-rev]').forEach(button => {
    button.onclick = () => { MAIL.filter.review = button.dataset.rev; loadInbox(); };
  });

  const table = $('#view-inbox table');
  if (table) table.onclick = event => {
    if (event.target.closest('.ordlink')) return;
    const row = event.target.closest('[data-mail]');
    if (row) openMail(Number(row.dataset.mail));
  };
}

function wireMailDrop() {
  const zone = $('#m-drop');
  const input = $('#m-file');
  if (!zone || !input) return;
  zone.onclick = () => input.click();
  input.onchange = () => uploadMail(input.files);
  ['dragover', 'dragenter'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.remove('over');
  }));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    uploadMail(e.dataTransfer.files);
  });
}

async function uploadMail(files, orderId) {
  if (!files || !files.length) return;
  const form = new FormData();
  Array.from(files).forEach(f => form.append('files', f));
  if (orderId) form.append('order_id', String(orderId));

  status(`reading ${files.length} email(s)…`);
  try {
    const result = await api('/api/mail/upload', { method: 'POST', body: form });
    const filed = result.mail.filter(m => m.order_id && !m.needs_review).length;
    const check = result.mail.filter(m => m.needs_review).length;
    const again = result.mail.filter(m => m.duplicate).length;

    let message = `${result.mail.length} email(s) read`;
    if (filed) message += `, ${filed} filed`;
    if (check) message += `, ${check} to check`;
    if (again) message += `, ${again} already in the tray`;
    toast(message, check ? '' : 'ok');
    result.failed.forEach(f => toast(`${f.filename}: ${f.error}`, 'err'));

    status('ready');
    await reloadBoot();
    if (S.view === 'inbox') await loadInbox();
    if (S.openOrder) openOrder(S.openOrder.id);
    refreshSaved();
  } catch (err) {
    toast(err.message, 'err');
    status('could not read those emails');
  }
}

async function openMail(mailId) {
  let item;
  try {
    item = await api('/api/mail/' + mailId);
    await loadInboxOrders();
  } catch (err) { toast(err.message, 'err'); return; }
  setHash('mail/' + mailId);

  const refs = item.refs || {};
  const allRefs = [...(refs.po || []), ...(refs.quote || []), ...(refs.codes || [])];
  const cases = (await api('/api/cases?open=1')).cases
    .filter(c => !item.order_id || c.order_id === item.order_id);
  // Every open folder, not just this customer's: an email nobody could
  // place is exactly the one that needs filing by hand, and it has no
  // customer to look folders up by.
  const folders = (await api('/api/threads?open=1')).folders;
  const mine = folders.filter(f => f.company_id === item.company_id);
  const others = folders.filter(f => f.company_id !== item.company_id);
  const folderOption = f => `<option value="${f.id}"
    ${String(item.thread_id) === String(f.id) ? 'selected' : ''}
    >${esc(f.ref)} · ${esc(f.topic)}</option>`;

  modal(`EMAIL — ${esc(item.category || 'GENERAL')}`, `
    <div class="kv mailhead">
      <div class="k">FROM</div>
      <div class="v">${esc(item.from_name || '')}
        &lt;${esc(item.from_email || 'unknown')}&gt;</div>
      <div class="k">TO</div><div class="v">${esc(item.to_addrs || '—')}</div>
      <div class="k">SENT</div>
      <div class="v">${esc(mailWhen(item))} UTC</div>
      <div class="k">WHICH WAY</div>
      <div class="v">
        <button class="btn ${item.direction === 'OUT' ? '' : 'primary'}"
                data-dir="IN">RECEIVED</button>
        <button class="btn ${item.direction === 'OUT' ? 'primary' : ''}"
                data-dir="OUT">SENT</button>
        <span class="note">${item.direction === 'OUT'
          ? 'treated as one you sent'
          : 'treated as one that came in'} — change it if that is wrong</span>
      </div>
      <div class="k">SUBJECT</div><div class="v"><b>${esc(item.subject || '')}</b></div>
    </div>

    <h2 class="sect">What it says</h2>
    <div class="summarybox">${esc(item.summary || 'Nothing readable in the body.')}</div>
    ${item.keywords ? `<div class="note">recurring words: ${esc(item.keywords)}</div>` : ''}
    ${allRefs.length ? `<div class="note">references written in it:
      ${allRefs.map(r => `<span class="chip">${esc(r)}</span>`).join(' ')}</div>` : ''}

    <h2 class="sect">Where it was filed, and why</h2>
    <div class="formgrid">
      <div class="lbl">CUSTOMER</div>
      <div class="wide"><select id="mm-company">
        <option value="">— no customer yet —</option>
        ${(S.boot.companies || []).map(c => `<option value="${c.id}"
          ${Number(item.company_id) === c.id ? 'selected' : ''}
          >${esc(c.name)}</option>`).join('')}
      </select></div>
      <div class="lbl">ORDER</div>
      <div class="wide"><select id="mm-order">${orderOptions(item.order_id)}</select></div>
    </div>
    <div class="note">An order is not needed. A customer on their own is a
      perfectly good place for an email to live.</div>
    <ul class="reasons">
      ${(item.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')
        || '<li>filed by hand</li>'}
    </ul>

    <h2 class="sect">Keep it in a folder</h2>
    <div class="filterbar" style="padding:0">
      <select id="mm-folder" style="min-width:340px">
        <option value="">— choose a folder —</option>
        ${mine.length ? `<optgroup label="${esc(item.company || 'this customer')}">
          ${mine.map(folderOption).join('')}</optgroup>` : ''}
        ${others.length ? `<optgroup label="${mine.length ? 'other customers'
                                                         : 'every open folder'}">
          ${others.map(folderOption).join('')}</optgroup>` : ''}
      </select>
      <button class="btn" id="mm-file">FILE IT IN</button>
      <button class="btn" id="mm-newfolder">START A FOLDER FROM THIS EMAIL</button>
    </div>
    ${item.folder_ref
      ? `<div class="note">In folder <b>${esc(item.folder_ref)}</b> —
         ${esc(item.folder_topic || '')}</div>`
      : (item.company_id
          ? ''
          : `<div class="note">No order number, and nobody we recognise? File
             it into a folder anyway — the email takes that folder's customer
             as its own, and no order reference is needed.</div>`)}

    ${item.order_id ? `
    <h2 class="sect">Log it against a dispute</h2>
    <div class="filterbar" style="padding:0">
      <select id="mm-case" style="min-width:260px">
        <option value="">— choose an open case —</option>
        ${cases.map(c => `<option value="${c.id}">${esc(c.ref)} · ${esc(c.title)}</option>`).join('')}
      </select>
      <button class="btn" id="mm-log">LOG TO CASE</button>
      <button class="btn" id="mm-newcase">OPEN A NEW CASE FROM THIS EMAIL</button>
    </div>` : ''}

    <h2 class="sect">The email itself</h2>
    <pre class="mailbody">${esc((item.body || '').slice(0, 20000))}</pre>
  `, [
    { label: 'DELETE', action: async () => {
        if (!confirm('Delete this email and its stored copy?')) return;
        await api('/api/mail/' + mailId, { method: 'DELETE' });
        closeModal(); toast('Email deleted', 'ok');
        loadInbox(); reloadBoot();
      } },
    { label: 'OPEN THE ORDER', action: () => {
        const chosen = Number($('#mm-order').value);
        if (!chosen) { toast('No order chosen', 'err'); return; }
        closeModal(); openOrder(chosen);
      } },
    { label: 'CLOSE', action: closeModal },
    { label: 'SAVE FILING', primary: true, action: async () => {
        const chosen = $('#mm-order').value;
        const customer = $('#mm-company').value;
        try {
          await postJSON('/api/mail/' + mailId,
                         { order_id: chosen || null,
                           company_id: customer || null, confirmed: true });
          toast('Filed — and remembered for the next mail from this sender', 'ok');
          closeModal();
          loadInbox(); reloadBoot(); refreshSaved();
        } catch (err) { toast(err.message, 'err'); }
      } },
  ]);

  if ($('#mm-log')) {
    $('#mm-log').onclick = async () => {
      const caseId = $('#mm-case').value;
      if (!caseId) { toast('Choose a case first', 'err'); return; }
      try {
        await postJSON(`/api/cases/${caseId}/entries`, {
          kind: item.direction === 'OUT' ? 'EMAIL OUT' : 'EMAIL IN',
          happened_at: (item.sent_at || '').slice(0, 10),
          who: item.from_name || item.from_email,
          summary: item.subject || '(no subject)',
          detail: item.summary || '',
          email_id: item.id,
          doc_id: item.doc_id,
        });
        toast('Logged against the case', 'ok');
        closeModal();
        if (S.openOrder) openOrder(S.openOrder.id);
      } catch (err) { toast(err.message, 'err'); }
    };
  }
  $$('#modal [data-dir]').forEach(button => {
    button.onclick = async () => {
      const wanted = button.dataset.dir;
      if (wanted === (item.direction || 'IN')) return;
      try {
        await postJSON('/api/mail/' + mailId, { direction: wanted });
        toast(wanted === 'OUT' ? 'Labelled as sent' : 'Labelled as received',
              'ok');
        loadInbox();
        openMail(mailId);        // redrawn, so the folder log reads right too
      } catch (err) { toast(err.message, 'err'); }
    };
  });

  if ($('#mm-file')) {
    $('#mm-file').onclick = async () => {
      const folderId = $('#mm-folder').value;
      if (!folderId) { toast('Choose a folder first', 'err'); return; }
      try {
        const result = await postJSON(`/api/threads/${folderId}/emails`,
                                      { email_id: item.id });
        toast(item.company_id
          ? 'Filed in ' + result.folder.ref
          : 'Filed in ' + result.folder.ref + ' — and given to '
            + result.folder.company, 'ok');
        closeModal();
        loadInbox(); reloadBoot();
      } catch (err) { toast(err.message, 'err'); }
    };
  }
  if ($('#mm-newfolder')) {
    $('#mm-newfolder').onclick = () => {
      closeModal();
      newFolderModal({
        company: item.company || '',
        topic: item.subject || '',
        summary: item.summary || '',
        kind: item.category === 'QUOTE' ? 'QUOTE REQUEST'
          : item.category === 'DEFECT' ? 'COMPLAINT'
          : item.category === 'DELIVERY' ? 'DELIVERY' : '',
        email: item,
      });
    };
  }
  if ($('#mm-newcase')) {
    $('#mm-newcase').onclick = () => {
      closeModal();
      newCaseModal({
        orderId: item.order_id,
        title: item.subject || '',
        detail: item.summary || '',
        kind: item.category === 'DEFECT' ? 'DEFECT' : '',
        email: item,
      });
    };
  }
}
