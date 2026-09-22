/* The PCB half of the front end: the build specification form, the cost
   sheet that totals as you type, and the settings page.

   Every figure shown here is worked out by the server (pcb.py), not in the
   browser, so the screen, the printed sheet and any export can never
   disagree about what an order costs. */

/* ------------------------------------------------------------- controls */

const SPEC_SECTIONS = [
  { title: 'QUOTATION', fields: ['quote_date', 'quote_ref', 'contact_person'] },
  { title: 'WHAT IT IS', fields: ['product_type', 'ipc_class', 'ccl_material'] },
  { title: 'SIZE & PANEL',
    fields: ['pcb_x_mm', 'pcb_y_mm', 'array_x_mm', 'array_y_mm', 'ups',
             'panel_code'] },
  { title: 'STACK-UP',
    fields: ['layers', 'thickness_mm', 'thickness_tol_pct', 'copper_outer_oz',
             'copper_inner_oz', 'surface_finish', 'finish_thickness',
             'impedance', 'impedance_note'] },
  { title: 'DRILLING',
    fields: ['min_drill_mm', 'min_drill_count', 'total_drill_count', 'bvh',
             'bvh_layers'] },
  { title: 'ORDER', fields: ['options', 'qty', 'lots'] },
];

/* Fields that offer a list but still accept anything typed. */
const SPEC_LISTS = {
  /* Everyone already on a customer record, so a contact is picked rather
     than retyped — and spelled the same way every time, which is what
     makes it worth searching for later. */
  contact_person: () => Array.from(new Set(
    (S.boot.companies || []).map(c => c.contact_name).filter(Boolean))).sort(),
  product_type: () => S.boot.prefs.product_types,
  ipc_class: () => S.boot.prefs.ipc_classes,
  ccl_material: () => S.boot.prefs.ccl_materials,
  surface_finish: () => S.boot.prefs.surface_finishes,
};

const SPEC_HINTS = {
  pcb_x_mm: 'mm', pcb_y_mm: 'mm', array_x_mm: 'mm', array_y_mm: 'mm',
  thickness_mm: 'mm', thickness_tol_pct: '%', copper_outer_oz: 'oz',
  copper_inner_oz: 'oz', min_drill_mm: 'mm', finish_thickness: "e.g. 1µ, 3–5µ\"",
  bvh_layers: 'e.g. 1-2, 5-6', ups: 'per array',
};

function specLabel(name) {
  const found = (S.boot.spec_fields || []).find(f => f.name === name);
  return found ? found.label : name.replace(/_/g, ' ').toUpperCase();
}

function specKind(name) {
  const all = (S.boot.spec_fields || []).concat(S.boot.cost_fields || []);
  const found = all.find(f => f.name === name);
  return found ? found.kind : 'text';
}

function specField(prefix, name, values) {
  const id = prefix + '-' + name;
  const raw = values ? values[name] : null;
  const kind = specKind(name);
  const hint = SPEC_HINTS[name] ? `<i class="fhint">${esc(SPEC_HINTS[name])}</i>` : '';

  if (kind === 'bool') {
    /* Two cells, like every other field, so the grid stays in step. */
    return `<label class="lbl chk" for="${id}">
              <input type="checkbox" id="${id}" ${raw ? 'checked' : ''}>
              ${esc(specLabel(name))}</label>
            <div class="fld"></div>`;
  }

  let control;
  if (name === 'panel_code') {
    const panels = S.boot.prefs.panel_sizes || [];
    control = `<select id="${id}">
      <option value="">—</option>
      ${panels.map(p => `<option value="${esc(p.code)}"
        ${String(raw || '') === p.code ? 'selected' : ''}>${esc(p.code)}
        — ${p.x} × ${p.y}</option>`).join('')}
    </select>`;
  } else if (SPEC_LISTS[name]) {
    const listId = 'dl-' + name;
    control = `<input id="${id}" list="${listId}" value="${esc(raw ?? '')}">
      <datalist id="${listId}">
        ${(SPEC_LISTS[name]() || []).map(v => `<option value="${esc(v)}">`).join('')}
      </datalist>`;
  } else if (kind === 'date') {
    /* Quotes are nearly always dated the day they are written, and a date
       box is a fiddly thing to fill in with a mouse. */
    control = `<input id="${id}" type="date" value="${esc(raw ?? '')}">
      <button type="button" class="btn today" data-today="${id}"
              title="Put today's date in">TODAY</button>`;
  } else if (kind === 'number' || kind === 'int') {
    const step = kind === 'int' ? '1' : 'any';
    control = `<input id="${id}" type="number" step="${step}"
                      value="${raw ?? ''}" inputmode="decimal">`;
  } else {
    control = `<input id="${id}" value="${esc(raw ?? '')}">`;
  }

  return `<label class="lbl" for="${id}">${esc(specLabel(name))}${hint}</label>
          <div class="fld">${control}</div>`;
}

function specFormHTML(prefix, values) {
  return SPEC_SECTIONS.map(section => `
    <div class="specsect">
      <h3>${section.title}</h3>
      <div class="specgrid">
        ${section.fields.map(f => specField(prefix, f, values)).join('')}
      </div>
    </div>`).join('');
}

/* ------------------------------------------------------------ cost form */

function costFormHTML(prefix, values) {
  const v = values || {};
  const p = S.boot.prefs;
  const num = (name, fallback) => `
    <input id="${prefix}-${name}" type="number" step="any" inputmode="decimal"
           value="${v[name] ?? (fallback ?? '')}">`;

  return `
    <div class="specsect">
      <h3>RATES</h3>
      <div class="specgrid">
        <label class="lbl" for="${prefix}-fx_rate">EXCHANGE RATE
          <i class="fhint">KRW per USD</i></label>
        <div class="fld">${num('fx_rate', p.fx_rate)}</div>

        <label class="lbl chk" for="${prefix}-inflation_on">
          <input type="checkbox" id="${prefix}-inflation_on"
                 ${v.inflation_on ? 'checked' : ''}> APPLY INFLATION</label>
        <div class="fld">${num('inflation_rate', p.inflation_rate)}
          <i class="fhint">× multiplier</i></div>

        <label class="lbl chk" for="${prefix}-markup_on">
          <input type="checkbox" id="${prefix}-markup_on"
                 ${v.markup_on ? 'checked' : ''}> APPLY MARKUP</label>
        <div class="fld">${num('markup_pct', p.markup_pct)}
          <i class="fhint">% — usually 20 to 30</i></div>
      </div>
    </div>

    <div class="specsect">
      <h3>PCB MANUFACTURING <span class="note">enter won — leave one blank
        and it is worked out from the quantity</span></h3>
      <div class="specgrid">
        <label class="lbl" for="${prefix}-pcb_total_krw">PCB TOTAL
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('pcb_total_krw')}</div>
        <label class="lbl" for="${prefix}-pcb_unit_krw">PCB PER PIECE
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('pcb_unit_krw')}</div>
      </div>
    </div>

    <div class="specsect">
      <h3><label class="chk inline" for="${prefix}-turnkey">
        <input type="checkbox" id="${prefix}-turnkey"
               ${v.turnkey ? 'checked' : ''}> TURNKEY — SMT &amp; COMPONENTS
      </label></h3>
      <div class="specgrid turnkeyonly ${v.turnkey ? '' : 'off'}"
           id="${prefix}-turnkeyblock">
        <label class="lbl" for="${prefix}-smt_total_krw">SMT TOTAL
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('smt_total_krw')}</div>
        <label class="lbl" for="${prefix}-smt_unit_krw">SMT PER PIECE
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('smt_unit_krw')}</div>

        <label class="lbl" for="${prefix}-stencil_count">STENCILS
          <i class="fhint">2 when both sides are populated</i></label>
        <div class="fld"><select id="${prefix}-stencil_count">
          ${[0, 1, 2].map(n => `<option value="${n}"
            ${Number(v.stencil_count || 0) === n ? 'selected' : ''}>${n}</option>`).join('')}
        </select></div>
        <label class="lbl" for="${prefix}-stencil_unit_krw">PER STENCIL
          <i class="fhint">KRW — ${Number(p.stencil_min_krw).toLocaleString()}
            to ${Number(p.stencil_max_krw).toLocaleString()}</i></label>
        <div class="fld">${num('stencil_unit_krw', p.stencil_unit_krw)}</div>

        <label class="lbl" for="${prefix}-parts_total_krw">COMPONENTS TOTAL
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('parts_total_krw')}</div>
        <label class="lbl" for="${prefix}-parts_unit_krw">COMPONENTS PER PIECE
          <i class="fhint">KRW</i></label>
        <div class="fld">${num('parts_unit_krw')}</div>
      </div>
    </div>`;
}

/* --------------------------------------------------------- reading back */

function readSpecForm(prefix) {
  const out = {};
  const names = (S.boot.spec_fields || []).concat(S.boot.cost_fields || []);
  names.forEach(({ name, kind }) => {
    const input = document.getElementById(prefix + '-' + name);
    if (!input) return;
    out[name] = kind === 'bool' ? (input.checked ? 1 : 0) : input.value;
  });
  return out;
}

function wireSpecForm(prefix, onChange) {
  const names = (S.boot.spec_fields || []).concat(S.boot.cost_fields || []);
  let pending = null;
  const fire = () => {
    clearTimeout(pending);
    pending = setTimeout(onChange, 220);
  };
  names.forEach(({ name }) => {
    const input = document.getElementById(prefix + '-' + name);
    if (!input) return;
    input.addEventListener('input', fire);
    input.addEventListener('change', fire);
  });
  document.querySelectorAll(`[data-today^="${prefix}-"]`).forEach(button => {
    button.onclick = () => {
      const field = document.getElementById(button.dataset.today);
      if (!field) return;
      field.value = todayISO();
      field.dispatchEvent(new Event('change', { bubbles: true }));
    };
  });

  const turnkey = document.getElementById(prefix + '-turnkey');
  const block = document.getElementById(prefix + '-turnkeyblock');
  if (turnkey && block) {
    turnkey.addEventListener('change', () =>
      block.classList.toggle('off', !turnkey.checked));
  }
}

/* Today where the user is, not in UTC: a quote written on the evening of
   the 3rd in Seoul is dated the 3rd, not the 2nd. */
function todayISO() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
}

/* A copied specification is a new quotation, so it carries today's date
   rather than the date of the order it came from. */
function dateQuoteToday(prefix) {
  const field = document.getElementById(prefix + '-quote_date');
  if (field) field.value = todayISO();
}

/* The customer's contact, for filling the quotation section in. */
function contactFor(companyName) {
  const name = String(companyName || '').trim().toLowerCase();
  if (!name) return null;
  return (S.boot.companies || []).find(
    c => String(c.name || '').trim().toLowerCase() === name) || null;
}

/* Put the customer's contact in, unless a person has typed one. Marked as
   ours so that changing the customer changes it too, while anything typed
   by hand is left exactly as it was. */
function fillContactFrom(prefix, companyName) {
  const field = document.getElementById(prefix + '-contact_person');
  if (!field) return;
  if (!field.dataset.watched) {
    field.dataset.watched = '1';
    field.dataset.auto = field.value ? '0' : '1';
    // The moment somebody types their own contact in, it is theirs, and
    // changing the customer afterwards must not take it away again.
    field.addEventListener('input', () => { field.dataset.auto = '0'; });
  }
  if (field.dataset.auto !== '1') return;
  const company = contactFor(companyName);
  field.value = (company && company.contact_name) || '';
}

/* --------------------------------------------------------- the read-out */

const krw = n => (Number(n) || 0).toLocaleString(undefined,
  { maximumFractionDigits: 0 }) + ' ₩';
const usd = n => {
  const value = Number(n) || 0;
  /* A cheap board can sell for a few cents, so small figures get more
     decimal places rather than rounding away to $0.00. */
  const places = value !== 0 && Math.abs(value) < 1 ? 4 : 2;
  return '$' + value.toLocaleString(undefined,
    { minimumFractionDigits: places, maximumFractionDigits: places });
};
const mm = (n, d = 2) => n === null || n === undefined || n === ''
  ? '—' : Number(n).toFixed(d);

function derivedHTML(derived) {
  const rows = [];
  const copper = (label, entry) => {
    if (!entry) return;
    rows.push([label, `${mm(entry.oz)} oz = ${mm(entry.um, 1)} µm
                       = ${mm(entry.mm, 4)} mm`]);
  };
  copper('COPPER OUTER', derived.copper_outer);
  copper('COPPER INNER', derived.copper_inner);

  if (derived.thickness_tol_mm !== undefined) {
    rows.push(['THICKNESS RANGE',
      `± ${mm(derived.thickness_tol_mm, 3)} mm &nbsp;
       (${mm(derived.thickness_min_mm, 3)} – ${mm(derived.thickness_max_mm, 3)} mm)`]);
  }
  if (derived.panel) {
    rows.push(['WORKING PANEL',
      `${esc(derived.panel.code)} &nbsp; ${derived.panel.x} × ${derived.panel.y} mm`
      + (derived.panel_usable
         ? ` &nbsp;<i>usable ${derived.panel_usable.x} × ${derived.panel_usable.y}</i>`
         : '')]);
  }
  if (derived.arrays_per_panel !== undefined) {
    rows.push(['PANEL YIELD',
      `${derived.arrays_per_panel} array(s) / panel &nbsp;·&nbsp;
       ${derived.pcs_per_panel || 0} pcs / panel`
      + (derived.panel_use_pct ? ` &nbsp;·&nbsp; ${derived.panel_use_pct}% used` : '')]);
  }
  if (derived.panels_needed) {
    rows.push(['PANELS NEEDED', `${derived.panels_needed}`]);
  }
  if (derived.total_qty) {
    rows.push(['TOTAL QUANTITY', `${derived.total_qty.toLocaleString()} pcs`
      + (derived.total_area_m2 ? ` &nbsp;·&nbsp; ${derived.total_area_m2} m²` : '')]);
  }

  if (!rows.length) {
    return '<div class="note">Fill in sizes, copper and quantity and the '
      + 'conversions appear here.</div>';
  }
  return `<table class="grid calc"><tbody>
    ${rows.map(([k, v]) => `<tr><td class="ck">${k}</td><td>${v}</td></tr>`).join('')}
  </tbody></table>`;
}

function costHTML(cost) {
  if (!cost || !cost.total || !cost.total.base_krw) {
    return '<div class="note">No prices entered yet. Fill in the PCB total '
      + 'or the price per piece.</div>';
  }
  const flags = [];
  if (cost.inflation_on) flags.push(`inflation × ${cost.inflation_rate}`);
  if (cost.markup_on) flags.push(`markup ${cost.markup_pct}%`);
  flags.push(`1 USD = ${Number(cost.fx_rate).toLocaleString()} ₩`);
  if (cost.qty) flags.push(`${cost.qty.toLocaleString()} pcs`);

  const row = (section, isTotal) => `
    <tr class="${isTotal ? 'grand' : ''}">
      <td>${esc(section.label)}
        ${section.note ? `<i class="fhint">${esc(section.note)}</i>` : ''}</td>
      <td class="num">${krw(section.base_krw)}</td>
      <td class="num">${krw(section.quoted_krw)}</td>
      <td class="num">${usd(section.quoted_usd)}</td>
      <td class="num">${cost.qty ? usd(section.unit_usd) : '—'}</td>
    </tr>`;

  return `
    <table class="grid costtable">
      <thead><tr>
        <th>ITEM</th><th class="num">COST ₩</th><th class="num">QUOTED ₩</th>
        <th class="num">QUOTED $</th><th class="num">PER PIECE $</th>
      </tr></thead>
      <tbody>${cost.sections.map(s => row(s, false)).join('')}</tbody>
      <tfoot>${row(cost.total, true)}</tfoot>
    </table>
    <div class="note">${esc(flags.join('  ·  '))}</div>`;
}

/* Ask the server to price whatever is on the form right now. The two
   read-outs can live in different places, or be the same node. */
async function quoteFromForm(prefix, derivedId, costId) {
  const derivedNode = derivedId && document.getElementById(derivedId);
  const costNode = costId && document.getElementById(costId);
  if (!derivedNode && !costNode) return null;
  try {
    const result = await postJSON('/api/quote', readSpecForm(prefix));
    if (derivedNode === costNode && derivedNode) {
      derivedNode.innerHTML = derivedHTML(result.derived) + costHTML(result.cost);
    } else {
      if (derivedNode) derivedNode.innerHTML = derivedHTML(result.derived);
      if (costNode) costNode.innerHTML = costHTML(result.cost);
    }
    return result;
  } catch (err) {
    const message = `<div class="note">could not total: ${esc(err.message)}</div>`;
    if (derivedNode) derivedNode.innerHTML = message;
    if (costNode && costNode !== derivedNode) costNode.innerHTML = message;
    return null;
  }
}

/* ------------------------------------------------------- repeat orders */

async function pickPreviousSpec(companyName, onPicked) {
  let list = [];
  try {
    const company = (S.boot.companies || []).find(c => c.name === companyName);
    const query = company ? '?company_id=' + company.id : '';
    list = (await api('/api/reorder-sources' + query)).orders;
  } catch (err) { toast(err.message, 'err'); return; }

  if (!list.length) {
    toast('No earlier order has a specification saved yet.', '');
    return;
  }

  modal('COPY SPECIFICATION FROM', `
    <div class="note" style="margin-bottom:8px">Pick the order this one
      repeats. Everything on the spec and cost sheet is copied across; the
      order number, dates and PO are left alone.</div>
    <table class="grid pick">
      <thead><tr><th>ORDER</th><th>CUSTOMER</th><th>DESCRIPTION</th>
        <th>TYPE</th><th class="num">LAYERS</th><th class="num">QTY</th>
        <th>QUOTE REF</th></tr></thead>
      <tbody>
        ${list.map(o => `<tr data-pick="${o.id}">
          <td style="color:var(--amber)">${esc(o.order_no)}</td>
          <td>${esc(o.company)}</td>
          <td style="color:var(--dim)">${esc(o.description || '')}</td>
          <td>${esc(o.product_type || '')}</td>
          <td class="num">${o.layers || ''}</td>
          <td class="num">${o.qty ? o.qty.toLocaleString() : ''}</td>
          <td>${esc(o.quote_ref || '')}</td>
        </tr>`).join('')}
      </tbody>
    </table>`,
    [{ label: 'CANCEL', action: closeModal }]);

  $('#modal .pick').onclick = async event => {
    const row = event.target.closest('[data-pick]');
    if (!row) return;
    try {
      const spec = await api('/api/orders/' + row.dataset.pick + '/spec');
      closeModal();
      onPicked(spec.values);
    } catch (err) { toast(err.message, 'err'); }
  };
}

function fillSpecForm(prefix, values) {
  Object.entries(values || {}).forEach(([name, value]) => {
    const input = document.getElementById(prefix + '-' + name);
    if (!input) return;
    if (input.type === 'checkbox') input.checked = !!value;
    else input.value = value === null || value === undefined ? '' : value;
  });
  const turnkey = document.getElementById(prefix + '-turnkey');
  const block = document.getElementById(prefix + '-turnkeyblock');
  if (turnkey && block) block.classList.toggle('off', !turnkey.checked);
}
