/* The network view: one hub, its neighbours fanned around it.
 *
 * Customers float around the middle. Click one and it takes the centre,
 * with its orders on one side and its folders and disputes on the other.
 * Click an order and the centre becomes the order, with the stages it has
 * been through on one side and everything filed on it on the other.
 *
 * Drawn as plain SVG, built here rather than fetched from anywhere. The
 * gentle drift is not decoration alone: a still diagram of forty dots is
 * hard to follow with the eye, and movement separates them.
 */

const GRAPH = {
  at: '',                 // '', 'company/3', 'order/12'
  trail: [],              // where we came from, for the breadcrumb
  data: null,
  selected: null,
  nodes: [],              // {node, el, x, y, phase, edge}
  frame: null,
  started: 0,
};

const GRAPH_TONE = {
  late: 'var(--red)', due: 'var(--amber)', open: 'var(--blue)',
  done: 'var(--green)', idle: 'var(--dimmer)',
};

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([key, value]) =>
    el.setAttribute(key, String(value)));
  return el;
}

function clip(text, chars = 34) {
  const value = String(text || '');
  return value.length > chars ? value.slice(0, chars - 1) + '…' : value;
}

async function renderGraph() {
  const el = $('#view-graph');
  el.innerHTML = '<div class="empty">drawing the network…</div>';
  await loadGraph(GRAPH.at);
}

async function loadGraph(at) {
  try {
    GRAPH.data = await api('/api/graph?at=' + encodeURIComponent(at || ''));
  } catch (err) { toast(err.message, 'err'); return; }
  GRAPH.at = GRAPH.data.at || '';
  GRAPH.selected = null;
  paintGraph();
}

function graphGoTo(at) {
  if (at === GRAPH.at) return;
  if (!at) GRAPH.trail = [];
  else if (GRAPH.trail[GRAPH.trail.length - 1] !== GRAPH.at) {
    GRAPH.trail.push(GRAPH.at);
  }
  setHash(at ? 'graph/' + at : 'graph');
  loadGraph(at);
}

function graphBack() {
  const previous = GRAPH.trail.pop();
  setHash(previous ? 'graph/' + previous : 'graph');
  loadGraph(previous || '');
}

function stopGraph() {
  if (GRAPH.frame) cancelAnimationFrame(GRAPH.frame);
  GRAPH.frame = null;
}

function paintGraph() {
  stopGraph();
  const el = $('#view-graph');
  const data = GRAPH.data;
  if (!data) return;

  const crumbs = [{ label: 'ALL CUSTOMERS', at: '' }];
  GRAPH.trail.forEach(step => crumbs.push({ label: step, at: step }));
  if (GRAPH.at) crumbs.push({ label: data.hub.label, at: GRAPH.at });

  el.innerHTML = `
    <div class="filterbar graphbar">
      ${GRAPH.at ? '<button class="btn" id="g-back">← BACK</button>' : ''}
      <span class="crumbs">
        ${crumbs.map((crumb, i) => `
          <span class="crumb ${i === crumbs.length - 1 ? 'here' : ''}"
                data-at="${esc(crumb.at)}">${esc(clip(crumb.label, 30))}</span>
        `).join('<span class="sep">›</span>')}
      </span>
      <span class="spacer"></span>
      <span class="note">click a customer to open it · click an order to see
        where it is</span>
      <button class="btn" id="g-refresh">REFRESH</button>
    </div>

    <div class="graphwrap">
      <div class="graphcanvas" id="g-canvas"></div>
      <aside class="graphside" id="g-side"></aside>
    </div>`;

  if ($('#g-back')) $('#g-back').onclick = graphBack;
  $('#g-refresh').onclick = () => loadGraph(GRAPH.at);
  $$('#view-graph .crumb').forEach(crumb => {
    crumb.onclick = () => {
      const at = crumb.dataset.at;
      GRAPH.trail = [];
      setHash(at ? 'graph/' + at : 'graph');
      loadGraph(at);
    };
  });

  drawGraph();
  showGraphDetail(null);
}

function drawGraph() {
  const holder = $('#g-canvas');
  const data = GRAPH.data;
  const width = Math.max(560, holder.clientWidth || 900);
  const height = Math.max(420, holder.clientHeight || 600);

  const svg = svgEl('svg', { width, height, viewBox: `0 0 ${width} ${height}`,
                             class: 'graphsvg' });
  const edgeLayer = svgEl('g', { class: 'edges' });
  const nodeLayer = svgEl('g', { class: 'nodes' });
  svg.append(edgeLayer, nodeLayer);

  const cx = width / 2;
  const cy = height / 2;

  /* Split the groups into a left fan and a right fan, the way the eye
     reads them: what it is made of on one side, what is attached on the
     other. A single group of customers is split down the middle. */
  const left = [];
  const right = [];
  (data.groups || []).forEach(group => {
    if (group.side === 'left') left.push(...group.nodes.map(n => [group, n]));
    else if (group.side === 'right') right.push(...group.nodes.map(n => [group, n]));
    else {
      group.nodes.forEach((node, i) =>
        (i % 2 ? right : left).push([group, node]));
    }
  });

  GRAPH.nodes = [];
  const place = (list, side) => {
    const many = list.length;
    if (!many) return;
    const top = 54;
    const span = height - top * 2;
    const step = many > 1 ? span / (many - 1) : 0;
    const x = side === 'left' ? cx - width * 0.26 : cx + width * 0.26;

    list.forEach(([group, node], index) => {
      const y = many > 1 ? top + index * step : cy;
      const colour = GRAPH_TONE[node.tone] || GRAPH_TONE.open;

      const edge = svgEl('path', { class: 'gedge', stroke: colour });
      edgeLayer.appendChild(edge);

      const holderEl = svgEl('g', { class: 'gnode', 'data-id': node.id });
      const dot = svgEl('circle', {
        r: Math.min(9, 4 + Math.log2(1 + (node.weight || 1)) * 1.6),
        fill: colour, class: 'gdot' });
      const label = svgEl('text', {
        x: side === 'left' ? -14 : 14, y: 4,
        'text-anchor': side === 'left' ? 'end' : 'start',
        class: 'glabel' });
      label.textContent = clip(node.label);
      holderEl.append(dot, label);

      if (node.sub) {
        const sub = svgEl('text', {
          x: side === 'left' ? -14 : 14, y: 16,
          'text-anchor': side === 'left' ? 'end' : 'start',
          class: 'gsub' });
        sub.textContent = clip(node.sub, 40);
        holderEl.appendChild(sub);
      }
      nodeLayer.appendChild(holderEl);

      GRAPH.nodes.push({ node, group, el: holderEl, edge, side,
                         x, y, phase: Math.random() * Math.PI * 2 });
    });
  };
  place(left, 'left');
  place(right, 'right');

  /* The hub last, so it sits over the lines that reach it. */
  const hub = data.hub;
  const hubColour = GRAPH_TONE[hub.tone] || 'var(--amber)';
  const hubGroup = svgEl('g', { class: 'ghub', transform: `translate(${cx},${cy})` });
  hubGroup.append(
    svgEl('circle', { r: 46, class: 'ghalo', fill: hubColour }),
    svgEl('circle', { r: 26, fill: hubColour, class: 'ghubdot' }));
  const hubLabel = svgEl('text', { y: 48, 'text-anchor': 'middle',
                                   class: 'ghublabel' });
  hubLabel.textContent = clip(hub.label, 30);
  const hubSub = svgEl('text', { y: 63, 'text-anchor': 'middle', class: 'gsub' });
  hubSub.textContent = clip(hub.sub || '', 40);
  hubGroup.append(hubLabel, hubSub);
  nodeLayer.appendChild(hubGroup);

  /* Group headings, where the reference has them: above each fan. */
  (data.groups || []).forEach(group => {
    if (!group.nodes.length || group.side === 'both') return;
    const heading = svgEl('text', {
      x: group.side === 'left' ? cx - width * 0.26 - 14 : cx + width * 0.26 + 14,
      y: 26,
      'text-anchor': group.side === 'left' ? 'end' : 'start',
      class: 'gheading' });
    heading.textContent = group.title;
    nodeLayer.appendChild(heading);
  });

  holder.innerHTML = '';
  holder.appendChild(svg);

  holder.onclick = event => {
    const target = event.target.closest('.gnode');
    if (!target) { showGraphDetail(null); return; }
    const found = GRAPH.nodes.find(n => n.node.id === target.dataset.id);
    if (found) openGraphNode(found.node);
  };
  holder.onmousemove = event => {
    const target = event.target.closest('.gnode');
    if (!target) return;
    const found = GRAPH.nodes.find(n => n.node.id === target.dataset.id);
    if (found && GRAPH.selected !== found.node.id) {
      GRAPH.selected = found.node.id;
      showGraphDetail(found.node);
    }
  };

  GRAPH.started = performance.now();
  floatGraph(cx, cy);
}

/* Nodes drift a little, and their edges follow. */
function floatGraph(cx, cy) {
  const tick = now => {
    const t = (now - GRAPH.started) / 1000;
    GRAPH.nodes.forEach(item => {
      const driftY = Math.sin(t * 0.5 + item.phase) * 4;
      const driftX = Math.cos(t * 0.35 + item.phase) * 3;
      const x = item.x + driftX;
      const y = item.y + driftY;
      item.el.setAttribute('transform', `translate(${x.toFixed(1)},${y.toFixed(1)})`);
      const pull = item.side === 'left' ? -1 : 1;
      item.edge.setAttribute('d',
        `M ${cx + pull * 26} ${cy} C ${cx + pull * 150} ${cy}, `
        + `${x - pull * 90} ${y}, ${x} ${y}`);
    });
    GRAPH.frame = requestAnimationFrame(tick);
  };
  GRAPH.frame = requestAnimationFrame(tick);
}

function openGraphNode(node) {
  if (node.drill) { graphGoTo(node.drill); return; }
  if (!node.link) { showGraphDetail(node); return; }
  followGraphLink(node.link);
}

function followGraphLink(link) {
  if (NAV_VIEWS.includes(link)) { show(link); return; }
  if (link.startsWith('print/') || link.startsWith('document/')) {
    const url = link.startsWith('document/')
      ? '/api/documents/' + link.split('/')[1] + '/file'
      : '/' + link;
    window.open(url, '_blank');
    return;
  }
  if (link.startsWith('company-orders/')) {
    S.filters = { ...S.filters, company_id: link.split('/')[1], alert: '',
                  closed: '1' };
    show('orders');
    return;
  }
  if (link.startsWith('company-folders/')) {
    FOLDERS.filter = { open: '1', company_id: link.split('/')[1], status: '',
                       q: '' };
    show('folders');
    return;
  }
  if (link.startsWith('company-edit/')) {
    const company = S.boot.companies.find(
      c => c.id === Number(link.split('/')[1]));
    if (company) companyModal(company);
    return;
  }
  location.hash = '#' + link;
}

/* ---- the panel beside it ---- */

function showGraphDetail(node) {
  const side = $('#g-side');
  if (!side) return;
  const data = GRAPH.data;
  const detail = data.detail || {};
  const money = new Set(detail.money_rows || []);

  /* Nothing hovered: the hub's own figures, which is what the view is of. */
  if (!node || node.id === data.hub.id) {
    side.innerHTML = `
      <div class="ghead">
        <div class="gtitle">${esc(detail.title || data.hub.label)}</div>
        <div class="gkind">${esc(detail.kind || data.hub.kind)}</div>
      </div>
      ${detail.pipeline ? pipelineHTML(detail.pipeline) : ''}
      ${(detail.alerts || []).length ? `<div class="gflags">
        ${detail.alerts.map(a => `<span class="chip ${acls(a)}">${esc(a)}</span>`).join('')}
      </div>` : ''}
      <table class="grid calc"><tbody>
        ${(detail.rows || []).map(([label, value]) => `
          <tr><td class="ck">${Array.isArray(label)
                ? `${esc(label[0])}<span class="lbl-en">${esc(label[1])}</span>`
                : esc(label)}</td>
              <td>${money.has(label) ? esc(moneyOr(value)) : esc(String(value))}</td></tr>`).join('')}
      </tbody></table>
      <div class="glinks">
        ${(detail.links || []).map(([label, link]) =>
          `<button class="btn" data-link="${esc(link)}">${esc(label)}</button>`).join('')}
      </div>
      <div class="note">Hover a dot to read it. Click a customer or an order
        to go in; click a folder, a dispute, an email or a document to open
        it.</div>`;
  } else {
    side.innerHTML = `
      <div class="ghead">
        <div class="gtitle">${esc(node.label)}</div>
        <div class="gkind" style="color:${GRAPH_TONE[node.tone]}">
          ${esc(node.kind)}</div>
      </div>
      <div class="gsubline">${esc(node.sub || '')}</div>
      ${node.badges.length ? `<div class="gflags">
        ${node.badges.map(b => `<span class="chip">${esc(b)}</span>`).join('')}
      </div>` : ''}
      <div class="glinks">
        ${node.drill ? `<button class="btn primary" data-link="::drill"
          >GO IN →</button>` : ''}
        ${node.link ? `<button class="btn" data-link="${esc(node.link)}"
          >OPEN IT</button>` : ''}
      </div>
      <div class="note">${node.drill
        ? 'Clicking the dot goes in as well.'
        : 'Clicking the dot opens it.'}</div>`;
  }

  $$('#g-side [data-link]').forEach(button => {
    button.onclick = () => {
      const link = button.dataset.link;
      if (link === '::drill') graphGoTo(node.drill);
      else followGraphLink(link);
    };
  });
}

function moneyOr(value) {
  const number = Number(value);
  return Number.isFinite(number) && number ? money(number) : '—';
}

function pipelineHTML(pipeline) {
  const here = pipeline.stages.indexOf(pipeline.here);
  return `<div class="pipeline graphpipe">
    ${pipeline.stages.map((stage, i) => `
      <div class="step ${i < here ? 'done' : ''} ${i === here ? 'here' : ''}">
        ${esc(stage)}</div>`).join('')}
  </div>`;
}
