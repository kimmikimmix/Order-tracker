/* Folders: one per running conversation with a customer.
 *
 * An order has a number and a date and behaves itself. Everything before it
 * — the price request, the sample, the question about a stack-up, the chase
 * about a delivery — is a conversation, and a conversation needs a topic on
 * the front, the mail kept together, and a date to come back to it.
 *
 * So each folder is shown as a card: what it is about, what they want,
 * where it stands, and when it next needs attention.
 */

const FOLDERS = {
  items: [],
  followUps: [],
  due: [],
  summary: { open: 0, due: 0, overdue: 0, open_actions: 0, late_actions: 0 },
  filter: { open: '1', company_id: '', status: '', q: '' },
};

function folderDue(folder) {
  if (!folder.follow_up_at) return '<span class="subtle">no date set</span>';
  const days = Math.round(
    (new Date(folder.follow_up_at) - new Date(todayISO())) / 86400000);
  const colour = folder.overdue ? 'var(--red)'
    : days <= 1 ? 'var(--amber)' : 'var(--dim)';
  const when = days < 0 ? `${-days}d late` : days === 0 ? 'today'
    : days === 1 ? 'tomorrow' : `in ${days}d`;
  return `<span style="color:${colour}">${esc(folder.follow_up_at)} · ${when}</span>`;
}

async function renderFolders() {
  $('#view-folders').innerHTML = '<div class="empty">opening the folders…</div>';
  await loadFolders();
}

async function loadFolders() {
  const query = new URLSearchParams();
  if (FOLDERS.filter.open === '1') query.set('open', '1');
  if (FOLDERS.filter.company_id) query.set('company_id', FOLDERS.filter.company_id);
  if (FOLDERS.filter.status) query.set('status', FOLDERS.filter.status);
  if (FOLDERS.filter.q) query.set('q', FOLDERS.filter.q);
  query.set('days', '14');
  try {
    const result = await api('/api/threads?' + query.toString());
    FOLDERS.items = result.folders || [];
    FOLDERS.followUps = result.follow_ups || [];
    FOLDERS.due = result.due || [];
    FOLDERS.summary = result.summary || FOLDERS.summary;
  } catch (err) { toast(err.message, 'err'); return; }
  paintFolders();
}

function paintFolders() {
  const el = $('#view-folders');
  const sum = FOLDERS.summary;
  const f = FOLDERS.filter;
  const statuses = S.boot.thread_statuses || [];

  const tile = (label, value, sub, kind) => `
    <div class="tile ${kind || ''}">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      <div class="sub">${sub || ''}</div>
    </div>`;

  el.innerHTML = `
    <div class="tiles">
      ${tile('OPEN FOLDERS', sum.open, 'conversations running', sum.open ? 'blue' : '')}
      ${tile('DUE NOW', sum.due, `${sum.overdue} past their date`,
             sum.overdue ? 'red' : (sum.due ? 'amber' : ''))}
      ${tile('ACTIONS OUTSTANDING', sum.open_actions,
             `${sum.late_actions} already late`, sum.late_actions ? 'red' : '')}
      ${tile('IN PLAY', money(FOLDERS.items.reduce(
               (total, item) => total + (Number(item.value_usd) || 0), 0)),
             'across the folders shown', 'green')}
    </div>

    <div class="filterbar">
      <button class="btn ${f.open === '1' ? 'primary' : ''}" data-open="1">OPEN ONLY</button>
      <button class="btn ${f.open === '' ? 'primary' : ''}" data-open="">ALL</button>
      <select id="f-company">
        <option value="">every customer</option>
        ${(S.boot.companies || []).map(c => `<option value="${c.id}"
          ${String(f.company_id) === String(c.id) ? 'selected' : ''}>${esc(c.name)}
          ${c.open_folders ? ' (' + c.open_folders + ')' : ''}</option>`).join('')}
      </select>
      <select id="f-status">
        <option value="">every status</option>
        ${statuses.map(s => `<option value="${esc(s)}"
          ${f.status === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
      </select>
      <input id="f-q" placeholder="topic, customer or what they want…"
             value="${esc(f.q)}" style="width:280px">
      <span class="spacer"></span>
      <button class="btn accent" id="f-new">+ NEW FOLDER</button>
    </div>

    ${FOLDERS.followUps.length ? `
    <h2 class="sect">Actions due</h2>
    <table class="grid">
      <thead><tr>
        <th style="width:110px">DUE</th><th style="width:100px">FOLDER</th>
        <th style="width:180px">CUSTOMER</th><th>WHAT NEEDS DOING</th>
        <th style="width:90px"></th>
      </tr></thead>
      <tbody>
        ${FOLDERS.followUps.map(a => `
          <tr data-folder="${a.thread_id}">
            <td style="color:${a.late ? 'var(--red)' : 'var(--amber)'}">
              ${esc(a.follow_up_at)}${a.late ? ' · LATE' : ''}</td>
            <td>${esc(a.ref)}</td>
            <td>${esc(a.company || '—')}</td>
            <td>${esc(a.summary)}<span class="subtle">${esc(a.topic || '')}</span></td>
            <td><button class="btn" data-done="${a.id}">DONE</button></td>
          </tr>`).join('')}
      </tbody>
    </table>` : ''}

    <h2 class="sect">${f.open === '1' ? 'Open folders' : 'All folders'}
      <span class="note">${FOLDERS.items.length}</span></h2>
    ${FOLDERS.items.length ? `
      <div class="foldergrid">
        ${FOLDERS.items.map(folderCard).join('')}
      </div>` : `
      <div class="empty">No folders${f.open === '1' ? ' are open' : ' yet'}.
        Open one from here, or from an email in the inbox.</div>`}`;

  $('#f-new').onclick = () => newFolderModal({});
  $('#f-company').onchange = event => {
    FOLDERS.filter.company_id = event.target.value; loadFolders();
  };
  $('#f-status').onchange = event => {
    FOLDERS.filter.status = event.target.value; loadFolders();
  };
  let typing = null;
  $('#f-q').oninput = event => {
    clearTimeout(typing);
    const text = event.target.value;
    typing = setTimeout(() => { FOLDERS.filter.q = text; loadFolders(); }, 250);
  };
  $$('#view-folders [data-open]').forEach(button => {
    button.onclick = () => { FOLDERS.filter.open = button.dataset.open; loadFolders(); };
  });

  el.onclick = async event => {
    const done = event.target.closest('[data-done]');
    if (done) {
      event.stopPropagation();
      await postJSON('/api/thread-entries/' + done.dataset.done, { done: true });
      toast('Ticked off', 'ok');
      loadFolders(); reloadBoot();
      return;
    }
    const card = event.target.closest('[data-folder]');
    if (card) openFolder(Number(card.dataset.folder));
  };
}

/* The topic box: the headline of the folder, and what is inside it. */
function folderCard(folder) {
  return `
    <div class="foldercard ${folder.overdue ? 'late' : ''}" data-folder="${folder.id}">
      <div class="fhead">
        <span class="fref">${esc(folder.ref)}</span>
        <span class="chip">${esc(folder.kind || 'ENQUIRY')}</span>
        <span class="chip ${folder.open ? 'a-DUESOON' : 'ok'}">${esc(folder.status)}</span>
        ${folder.order_no ? `<span class="chip">${esc(orderName(folder))}</span>` : ''}
      </div>
      <div class="ftopic">${esc(folder.topic)}</div>
      <div class="fwho">${esc(folder.company)}
        ${folder.value_usd ? ' · ' + money(folder.value_usd) : ''}</div>

      <div class="fkv">
        <div class="k">WHAT THEY WANT</div>
        <div class="v">${esc(folder.summary || '—')}</div>
        <div class="k">WHERE IT STANDS</div>
        <div class="v">${esc(folder.situation || 'nothing noted yet')}</div>
        <div class="k">COME BACK</div>
        <div class="v">${folderDue(folder)}</div>
      </div>

      ${cardShotsHTML(folder.attachments)}

      <div class="ffoot">
        <span>${folder.email_count || 0} email(s)</span>
        <span>${folder.entries || 0} logged</span>
        <span style="color:${folder.open_actions ? 'var(--amber)' : 'var(--dimmer)'}">
          ${folder.open_actions || 0} action(s)</span>
        <span class="spacer"></span>
        <span class="subtle">opened ${esc(folder.opened_at || '')}</span>
      </div>
    </div>`;
}

/* ---- one folder ---- */

function folderFieldsHTML(prefix, values, withCustomer) {
  const kinds = S.boot.thread_kinds || ['ENQUIRY'];
  const statuses = S.boot.thread_statuses || ['OPEN'];
  const pick = (list, chosen) => list.map(item =>
    `<option ${item === chosen ? 'selected' : ''}>${esc(item)}</option>`).join('');

  return `
    <div class="formgrid">
      <div class="lbl">TOPIC *</div>
      <div class="wide"><input id="${prefix}-topic" value="${esc(values.topic || '')}"
        placeholder="one line: what is this conversation about"></div>

      ${withCustomer ? `
      <div class="lbl">CUSTOMER *</div>
      <div class="wide"><input id="${prefix}-company" list="folder-companylist"
        value="${esc(values.company || '')}" placeholder="start typing…">
        <datalist id="folder-companylist">
          ${(S.boot.companies || []).map(c =>
            `<option value="${esc(c.name)}">`).join('')}
        </datalist></div>` : ''}

      <div class="lbl">WHAT THEY WANT</div>
      <div class="wide"><textarea id="${prefix}-summary" rows="2"
        placeholder="the request in your own words">${esc(values.summary || '')}</textarea></div>

      <div class="lbl">WHERE IT STANDS</div>
      <div class="wide"><textarea id="${prefix}-situation" rows="2"
        placeholder="what is happening right now, and who has the ball">${esc(values.situation || '')}</textarea></div>

      <div class="lbl">KIND</div>
      <div><select id="${prefix}-kind">${pick(kinds, values.kind)}</select></div>
      <div class="lbl">STATUS</div>
      <div><select id="${prefix}-status">${pick(statuses, values.status)}</select></div>

      <div class="lbl">COME BACK BY</div>
      <div><input id="${prefix}-follow_up_at" type="date"
        value="${esc(values.follow_up_at || '')}"></div>
      <div class="lbl">OPENED</div>
      <div><input id="${prefix}-opened_at" type="date"
        value="${esc(values.opened_at || todayISO())}"></div>

      <div class="lbl">WORTH (USD)</div>
      <div><input id="${prefix}-value_usd" type="number" step="any"
        value="${values.value_usd != null ? values.value_usd : ''}"
        placeholder="if it becomes an order"></div>
      <div class="lbl">HANDLED BY</div>
      <div><input id="${prefix}-owner" value="${esc(values.owner || '')}"></div>

      <div class="lbl">AGAINST AN ORDER</div>
      <div class="wide"><select id="${prefix}-order_id">
        ${orderOptions(values.order_id)}</select></div>
    </div>`;
}

function readFolderFields(prefix, withCustomer) {
  const value = id => {
    const node = $('#' + prefix + '-' + id);
    return node ? node.value : '';
  };
  const out = {
    topic: value('topic'), summary: value('summary'),
    situation: value('situation'), kind: value('kind'), status: value('status'),
    follow_up_at: value('follow_up_at'), opened_at: value('opened_at'),
    value_usd: value('value_usd'), owner: value('owner'),
    order_id: value('order_id') || null,
  };
  if (withCustomer) out.company = value('company');
  return out;
}

async function newFolderModal(seed) {
  await loadInboxOrders();
  modal('NEW FOLDER', `
    <div class="note">A folder holds one running conversation with a
      customer — a price request, a sample, a question, a chase. Emails go
      inside it, and it keeps a date to come back to.</div>
    ${folderFieldsHTML('nf', {
      topic: seed.topic || '', summary: seed.summary || '',
      company: seed.company || '', kind: seed.kind || '',
      status: (S.boot.thread_statuses || ['OPEN'])[0],
      owner: seed.owner || '',
    }, true)}
  `, [
    { label: 'CANCEL', action: closeModal },
    { label: 'OPEN THE FOLDER', primary: true, action: async () => {
        try {
          const result = await postJSON('/api/threads',
                                        readFolderFields('nf', true));
          closeModal();
          toast('Folder ' + result.folder.ref + ' opened', 'ok');
          if (seed.email) {
            await postJSON(`/api/threads/${result.id}/emails`,
                           { email_id: seed.email.id });
          }
          reloadBoot();
          if (S.view === 'folders') loadFolders();
          openFolder(result.id);
        } catch (err) { toast(err.message, 'err'); }
      } },
  ]);
}

async function openFolder(folderId) {
  let folder;
  try { folder = await api('/api/threads/' + folderId); }
  catch (err) { toast(err.message, 'err'); return; }
  setHash('folder/' + folderId);
  await loadInboxOrders();

  // Emails that are not in any folder yet, so one can be pulled in from
  // here as well as pushed from the inbox. Catching up on a conversation
  // usually means starting from the folder, not from the tray.
  let loose = [];
  try {
    loose = (await api('/api/mail?review=all')).mail
      .filter(mail => !mail.thread_id)
      .slice(0, 60);
  } catch (err) { loose = []; }

  const kinds = S.boot.case_entry_kinds || ['NOTE'];

  modal(`${esc(folder.ref)} — ${esc(folder.company)}`, `
    <div class="mtabs">
      <button data-ftab="log" class="active">LOG (${folder.entries.length})</button>
      <button data-ftab="mail">EMAIL (${folder.emails.length})</button>
      <button data-ftab="folder">THE FOLDER</button>
      <span class="spacer"></span>
      <a class="btn" href="/print/folder/${folder.id}" target="_blank">PRINT</a>
    </div>

    <div class="topicbox">
      <div class="ttopic">${esc(folder.topic)}</div>
      <div class="tkv">
        <div class="k">WHAT THEY WANT</div>
        <div class="v">${esc(folder.summary || '—')}</div>
        <div class="k">WHERE IT STANDS</div>
        <div class="v">${esc(folder.situation || 'nothing noted yet')}</div>
        <div class="k">COME BACK</div>
        <div class="v">${folderDue(folder)}
          ${folder.open_actions
            ? `· <span style="color:var(--amber)">${folder.open_actions} action(s) outstanding</span>`
            : ''}</div>
      </div>
      ${attachStripHTML('threads', folder.id, folder.attachments,
                        'pictures of this enquiry — drop or paste one anywhere here')}
    </div>

    <div class="mpane" id="fpane-log">
      <div class="formgrid entryform">
        <div class="lbl">WHAT HAPPENED *</div>
        <div class="wide"><input id="fe-summary"
          placeholder="e.g. sent the quote, or rang and left a message"></div>
        <div class="lbl">KIND</div>
        <div><select id="fe-kind">${kinds.map(k =>
          `<option>${esc(k)}</option>`).join('')}</select></div>
        <div class="lbl">WHEN</div>
        <div><input id="fe-happened_at" type="date" value="${todayISO()}"></div>
        <div class="lbl">WHO</div>
        <div><input id="fe-who" placeholder="who you spoke to"></div>
        <div class="lbl">FOLLOW UP BY</div>
        <div><input id="fe-follow_up_at" type="date"></div>
        <div class="lbl">DETAIL</div>
        <div class="wide"><textarea id="fe-detail" rows="2"
          placeholder="what was said, agreed, or promised"></textarea></div>
      </div>
      ${attachBoxHTML('fentry')}
      <div class="filterbar" style="padding:4px 0 12px">
        <button class="btn primary" id="fe-add">ADD TO THE LOG</button>
        <button class="btn hidden" id="fe-cancel">CANCEL</button>
        <span class="note">Every entry keeps its date.
          EDIT brings one back up here to correct.</span>
      </div>

      <div class="timeline caselog">
        ${folder.entries.map(entry => `
          <div class="ev ${entry.late ? 'late' : ''}">
            <div>
              <span class="chip" style="color:${ENTRY_COLOUR[entry.kind] || 'var(--dim)'}">
                ${esc(entry.kind)}</span>
              <b>${esc(entry.summary)}</b>
              ${entry.detail ? `<div class="subtle">${esc(entry.detail)}</div>` : ''}
              ${entry.filename ? `<div class="subtle">file:
                <a href="/api/documents/${entry.doc_id}/file" target="_blank"
                   style="color:var(--blue)">${esc(entry.filename)}</a></div>` : ''}
              ${picturesHTML(entry.attachments)}
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

    <div class="mpane hidden" id="fpane-mail">
      <div class="filterbar" style="padding:0 0 8px">
        <select id="ff-mail" style="min-width:420px">
          <option value="">— an email to put in this folder —</option>
          ${loose.map(mail => `<option value="${mail.id}">
            ${esc(String(mail.sent_at || mail.filed_at || '').slice(0, 10))}
            · ${esc(mail.from_name || mail.from_email || 'unknown')}
            · ${esc((mail.subject || '(no subject)').slice(0, 60))}
          </option>`).join('')}
        </select>
        <button class="btn" id="ff-add">ADD TO THIS FOLDER</button>
      </div>
      <div class="note">An email with no customer of its own takes this
        folder's customer when you file it here. No order reference needed.</div>
      <div class="doclist" style="margin-top:8px">
        ${folder.emails.length ? folder.emails.map(mail => `
          <div class="docrow mailrow">
            <span class="chip k-${esc(mail.category || 'GENERAL')}">${
              mail.direction === 'OUT' ? 'SENT' : 'RECEIVED'}</span>
            <span class="dname" data-openmail="${mail.id}">
              ${esc(mail.subject || '(no subject)')}
              <span class="subtle">${esc(mail.from_name || mail.from_email || '')}
                · ${esc(String(mail.sent_at || mail.filed_at || '').slice(0, 10))}</span>
              <div class="subtle">${esc(mail.summary || '')}</div></span>
            ${mail.attachments ? `<span class="dmeta">${mail.attachments} file(s)</span>` : ''}
            <button class="btn danger" data-unfile="${mail.id}">REMOVE</button>
          </div>`).join('')
        : '<div class="note">No email filed in this folder yet.</div>'}
      </div>
    </div>

    <div class="mpane hidden" id="fpane-folder">
      ${folderFieldsHTML('ef', folder, false)}
      <div class="filterbar" style="padding:8px 0 0">
        <button class="btn danger" id="ef-delete">DELETE THIS FOLDER</button>
        <span class="note">Deleting a folder leaves its emails where they
          are — only the folder goes.</span>
      </div>
    </div>
  `, [
    { label: 'CLOSE', action: closeModal },
    { label: 'SAVE THE FOLDER', primary: true, action: async () => {
        try {
          await postJSON('/api/threads/' + folderId,
                         readFolderFields('ef', false));
          toast('Folder saved', 'ok');
          closeModal();
          if (S.view === 'folders') loadFolders();
          reloadBoot(); refreshSaved();
        } catch (err) { toast(err.message, 'err'); }
      } },
  ]);

  $$('#modal [data-ftab]').forEach(button => {
    button.onclick = () => {
      $$('#modal [data-ftab]').forEach(b => b.classList.toggle('active', b === button));
      $$('#modal .mpane').forEach(pane =>
        pane.classList.toggle('hidden', pane.id !== 'fpane-' + button.dataset.ftab));
    };
  });

  /* EDIT puts an entry back into the box it was typed in; the button
     then saves the correction instead of adding another line. */
  let editing = null;

  const stopEditing = () => {
    editing = null;
    ['fe-summary', 'fe-who', 'fe-detail', 'fe-follow_up_at']
      .forEach(id => { $('#' + id).value = ''; });
    $('#fe-happened_at').value = todayISO();
    $('#fe-add').textContent = 'ADD TO THE LOG';
    $('#fe-cancel').classList.add('hidden');
  };

  $('#fe-cancel').onclick = stopEditing;
  wireAttachBox('fentry', $('#modal'));

  // Anything dropped or pasted on this folder, other than on the box
  // under the log form, belongs to the folder itself.
  $('#modal').dataset.attachOwner = 'threads';
  $('#modal').dataset.attachId = String(folder.id);
  wireAttachStrip('threads', folder.id, $('#modal'));
  $('.topicbox', $('#modal')).onclick = event =>
    handlePictureClick(event, () => { openFolder(folderId); loadFolders(); });

  $('#fe-add').onclick = async () => {
    const body = {
      summary: $('#fe-summary').value, kind: $('#fe-kind').value,
      happened_at: $('#fe-happened_at').value, who: $('#fe-who').value,
      detail: $('#fe-detail').value, follow_up_at: $('#fe-follow_up_at').value,
    };
    try {
      let written = { id: editing };
      if (editing) await postJSON('/api/thread-entries/' + editing, body);
      else written = await postJSON(`/api/threads/${folderId}/entries`, body);
      await sendPending('fentry', 'thread_entries', written.id);
      toast(editing ? 'Corrected' : 'Added to the log', 'ok');
      openFolder(folderId);
      if (S.view === 'folders') loadFolders();
      reloadBoot(); refreshSaved();
    } catch (err) { toast(err.message, 'err'); }
  };

  $('#ef-delete').onclick = async () => {
    if (!confirm('Delete this folder and its log? The emails stay on file.')) return;
    await api('/api/threads/' + folderId, { method: 'DELETE' });
    closeModal();
    toast('Folder deleted', 'ok');
    if (S.view === 'folders') loadFolders();
    reloadBoot();
  };

  $('.caselog', $('#modal')).onclick = async event => {
    if (await handlePictureClick(event, () => openFolder(folderId))) return;
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
      const wasDone = toggle.textContent.trim() === 'REOPEN';
      await postJSON('/api/thread-entries/' + toggle.dataset.toggle, { done: !wasDone });
      openFolder(folderId); reloadBoot();
      return;
    }
    const edit = event.target.closest('[data-edit-entry]');
    if (edit) {
      const entry = (folder.entries || []).find(
        e => e.id === Number(edit.dataset.editEntry));
      if (!entry) return;
      editing = entry.id;
      $('#fe-summary').value = entry.summary || '';
      $('#fe-kind').value = entry.kind || '';
      $('#fe-happened_at').value = String(entry.happened_at || '').slice(0, 10);
      $('#fe-who').value = entry.who || '';
      $('#fe-detail').value = entry.detail || '';
      $('#fe-follow_up_at').value = entry.follow_up_at || '';
      $('#fe-add').textContent = 'SAVE THE CHANGE';
      $('#fe-cancel').classList.remove('hidden');
      $('#fe-summary').focus();
      return;
    }
    const remove = event.target.closest('[data-del-entry]');
    if (remove) {
      if (!confirm('Remove this entry from the log?')) return;
      await api('/api/thread-entries/' + remove.dataset.delEntry, { method: 'DELETE' });
      openFolder(folderId);
    }
  };

  $('#ff-add').onclick = async () => {
    const emailId = $('#ff-mail').value;
    if (!emailId) { toast('Choose an email first', 'err'); return; }
    try {
      await postJSON(`/api/threads/${folderId}/emails`, { email_id: emailId });
      toast('Added to the folder', 'ok');
      openFolder(folderId);
      reloadBoot(); refreshSaved();
    } catch (err) { toast(err.message, 'err'); }
  };

  $('#fpane-mail').onclick = async event => {
    const unfile = event.target.closest('[data-unfile]');
    if (unfile) {
      await api(`/api/threads/${folderId}/emails/${unfile.dataset.unfile}`,
                { method: 'DELETE' });
      toast('Taken out of the folder', 'ok');
      openFolder(folderId);
      return;
    }
    const open = event.target.closest('[data-openmail]');
    if (open) { closeModal(); openMail(Number(open.dataset.openmail)); }
  };
}
