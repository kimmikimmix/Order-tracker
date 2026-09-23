"""The printable specification and cost sheet for one order.

Built as a plain, self-contained page rather than inside the terminal UI, so
Ctrl+P produces something on white paper that a customer could be shown: no
dark background to drain the toner, no navigation, and the same figures the
screen shows because both come from pcb.cost_sheet.
"""

import html
from datetime import datetime

from . import geo, orders, pcb, prefs


def _text(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def _num(value, digits=0, suffix=""):
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    formatted = f"{number:,.{digits}f}"
    return html.escape(formatted + suffix)


def _krw(value):
    return _num(value, 0, " KRW")


def _usd(value):
    """Dollars, with more decimals for figures under one."""
    try:
        small = value not in (None, "") and 0 < abs(float(value)) < 1
    except (TypeError, ValueError):
        small = False
    return "$" + _num(value, 4 if small else 2)


def _yn(value):
    return "YES" if value else "NO"


def _rows(pairs) -> str:
    """A two-column block of label/value rows, skipping the empty ones."""
    cells = [f"<tr><th>{html.escape(label)}</th><td>{value}</td></tr>"
             for label, value in pairs if value not in (None, "", "—")]
    return "".join(cells) or '<tr><td colspan="2" class="none">not specified</td></tr>'


def _spec_blocks(order, spec) -> str:
    values = spec["values"]
    derived = spec["derived"]
    label = pcb.LABELS

    size = None
    if values.get("pcb_x_mm") and values.get("pcb_y_mm"):
        size = (f"{_num(values['pcb_x_mm'], 2)} × {_num(values['pcb_y_mm'], 2)} mm"
                + (f" &nbsp; ({_num(derived.get('pcb_area_mm2'), 1)} mm²)"
                   if derived.get("pcb_area_mm2") else ""))
    array = None
    if values.get("array_x_mm") and values.get("array_y_mm"):
        array = (f"{_num(values['array_x_mm'], 2)} × {_num(values['array_y_mm'], 2)} mm"
                 + (f" &nbsp; {_num(values.get('ups'))} up" if values.get("ups") else ""))

    panel = derived.get("panel")
    panel_text = None
    if panel:
        parts = [f"{html.escape(panel['code'])} &nbsp; "
                 f"{_num(panel['x'], 0)} × {_num(panel['y'], 0)} mm"]
        if derived.get("arrays_per_panel"):
            parts.append(f"{derived['arrays_per_panel']} array(s) / panel")
        if derived.get("pcs_per_panel"):
            parts.append(f"{derived['pcs_per_panel']} pcs / panel")
        if derived.get("panels_needed"):
            parts.append(f"{derived['panels_needed']} panels needed")
        if derived.get("panel_use_pct"):
            parts.append(f"{derived['panel_use_pct']}% used")
        panel_text = " &nbsp;·&nbsp; ".join(parts)

    thickness = None
    if values.get("thickness_mm"):
        thickness = f"{_num(values['thickness_mm'], 3)} mm"
        if derived.get("thickness_tol_mm") is not None:
            thickness += (f" &nbsp; ± {_num(values.get('thickness_tol_pct'), 1)}%"
                          f" (± {_num(derived['thickness_tol_mm'], 3)} mm"
                          f" → {_num(derived.get('thickness_min_mm'), 3)}"
                          f"–{_num(derived.get('thickness_max_mm'), 3)} mm)")

    def copper_text(entry):
        if not entry:
            return None
        return (f"{_num(entry['oz'], 2)} oz &nbsp; "
                f"({_num(entry['um'], 1)} µm / {_num(entry['mm'], 4)} mm)")

    drill = None
    if values.get("min_drill_mm") or values.get("total_drill_count"):
        bits = []
        if values.get("min_drill_mm"):
            bits.append(f"min ø{_num(values['min_drill_mm'], 3)} mm")
        if values.get("min_drill_count"):
            bits.append(f"{_num(values['min_drill_count'])} at min size")
        if values.get("total_drill_count"):
            bits.append(f"{_num(values['total_drill_count'])} holes total")
        drill = " &nbsp;·&nbsp; ".join(bits)

    quantity = None
    if values.get("qty"):
        quantity = f"{_num(values['qty'])} pcs / lot"
        if (values.get("lots") or 1) > 1:
            quantity += (f" × {_num(values['lots'])} lots"
                         f" = {_num(derived.get('total_qty'))} pcs")
        if derived.get("total_area_m2"):
            quantity += f" &nbsp; ({_num(derived['total_area_m2'], 3)} m²)"

    return f"""
    <h2>Quotation</h2>
    <table class="kv">{_rows([
        ("QUOTE DATE", _text(values.get("quote_date"))),
        ("QUOTE REF", _text(values.get("quote_ref"))),
        ("PRODUCT NO", _text(order.get("product_code"))),
        ("PRODUCT NAME", _text(order.get("product_name"))),
        ("CUSTOMER", _text(order.get("company"))),
        ("CONTACT", _text(values.get("contact_person") or order.get("contact_name"))),
        ("CUSTOMER PO", _text(order.get("po_number"))),
        ("ORDER DATE", _text(order.get("order_date"))),
        ("PROMISED", _text(order.get("promise_date"))),
    ])}</table>

    <h2>Build specification</h2>
    <table class="kv">{_rows([
        (label["product_type"], _text(values.get("product_type"))),
        (label["ipc_class"], _text(values.get("ipc_class"))),
        (label["ccl_material"], _text(values.get("ccl_material"))),
        ("PCB SIZE", size),
        ("ARRAY", array),
        ("WORKING PANEL", panel_text),
        (label["layers"], _text(values.get("layers"))),
        ("THICKNESS", thickness),
        ("COPPER OUTER", copper_text(derived.get("copper_outer"))),
        ("COPPER INNER", copper_text(derived.get("copper_inner"))),
        ("SURFACE FINISH", " ".join(filter(None, [
            html.escape(str(values.get("surface_finish") or "")),
            html.escape(str(values.get("finish_thickness") or "")),
        ])).strip() or None),
        ("IMPEDANCE", (_yn(values.get("impedance"))
                       + (f" — {html.escape(str(values.get('impedance_note')))}"
                          if values.get("impedance_note") else ""))
                      if values.get("impedance") or values.get("impedance_note") else None),
        ("DRILLING", drill),
        ("BVH", (_yn(values.get("bvh"))
                 + (f" — layers {html.escape(str(values.get('bvh_layers')))}"
                    if values.get("bvh_layers") else ""))
                if values.get("bvh") or values.get("bvh_layers") else None),
        (label["options"], _text(values.get("options"))),
        ("QUANTITY", quantity),
    ])}</table>"""


def _cost_block(cost) -> str:
    if not cost["sections"] or not cost["total"]["base_krw"]:
        return '<h2>Cost</h2><p class="none">No prices have been entered yet.</p>'

    notes = []
    if cost["inflation_on"]:
        notes.append(f"inflation × {cost['inflation_rate']:g}")
    if cost["markup_on"]:
        notes.append(f"markup {cost['markup_pct']:g}%")
    notes.append(f"1 USD = {cost['fx_rate']:,.0f} KRW")

    body = "".join(
        f"""<tr>
              <td class="sect">{html.escape(section['label'])}
                {f'<span class="note">{html.escape(section["note"])}</span>'
                 if section['note'] else ''}</td>
              <td class="num">{_krw(section['base_krw'])}</td>
              <td class="num">{_krw(section['quoted_krw'])}</td>
              <td class="num">{_usd(section['quoted_usd'])}</td>
              <td class="num">{_usd(section['unit_usd'])}</td>
            </tr>"""
        for section in cost["sections"]
    )
    total = cost["total"]
    return f"""
    <h2>Cost</h2>
    <table class="cost">
      <thead><tr>
        <th>ITEM</th><th class="num">COST (KRW)</th><th class="num">QUOTED (KRW)</th>
        <th class="num">QUOTED (USD)</th><th class="num">PER PIECE (USD)</th>
      </tr></thead>
      <tbody>{body}</tbody>
      <tfoot><tr>
        <td class="sect">TOTAL{f" — {cost['qty']:,} pcs" if cost['qty'] else ''}</td>
        <td class="num">{_krw(total['base_krw'])}</td>
        <td class="num">{_krw(total['quoted_krw'])}</td>
        <td class="num">{_usd(total['quoted_usd'])}</td>
        <td class="num">{_usd(total['unit_usd'])}</td>
      </tr></tfoot>
    </table>
    <p class="note">{html.escape(' · '.join(notes))}</p>"""


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 11pt/1.45 "Segoe UI", system-ui, sans-serif; color: #111;
       background: #fff; margin: 0; padding: 22mm 18mm; }
h1 { font-size: 17pt; margin: 0 0 2px; letter-spacing: .3px; }
h2 { font-size: 10pt; letter-spacing: 1.2px; text-transform: uppercase;
     color: #555; border-bottom: 1.5px solid #111; padding-bottom: 4px;
     margin: 22px 0 8px; }
.sub { color: #555; font-size: 10pt; margin: 0 0 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-start;
        border-bottom: 3px solid #111; padding-bottom: 10px; }
.badge { border: 1.5px solid #111; padding: 3px 10px; font-size: 9pt;
         letter-spacing: 1px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; }
table.kv th { text-align: left; width: 33%; font-weight: 600; font-size: 9pt;
              letter-spacing: .6px; color: #444; padding: 5px 10px 5px 0;
              vertical-align: top; border-bottom: 1px solid #e3e3e3; }
table.kv td { padding: 5px 0; border-bottom: 1px solid #e3e3e3;
              vertical-align: top; }
table.cost th { font-size: 9pt; letter-spacing: .6px; color: #444;
                text-align: left; border-bottom: 1.5px solid #111; padding: 6px 4px; }
table.cost td { padding: 7px 4px; border-bottom: 1px solid #e3e3e3; }
table.cost tfoot td { border-top: 2px solid #111; border-bottom: none;
                      font-weight: 700; font-size: 11.5pt; }
.num { text-align: right; font-variant-numeric: tabular-nums;
       font-family: "Consolas", ui-monospace, monospace; }
.sect { font-weight: 600; }
.note { color: #666; font-size: 9pt; font-weight: 400; }
.sect .note { display: block; }
.none { color: #888; font-style: italic; }
.docs li { margin: 2px 0; }
footer { margin-top: 26px; border-top: 1px solid #ccc; padding-top: 8px;
         color: #777; font-size: 8.5pt; display: flex; justify-content: space-between; }
.toolbar { position: fixed; top: 10px; right: 10px; }
.toolbar button { font: inherit; padding: 8px 18px; cursor: pointer;
                  border: 1.5px solid #111; background: #111; color: #fff; }
@media print { .toolbar { display: none; } body { padding: 0; } }
@page { margin: 16mm; }
"""


def render(order_id: int) -> str | None:
    """The whole printable page for one order, or None when it is gone."""
    order = orders.get_order(order_id)
    if order is None:
        return None
    spec = order["spec"]
    settings = prefs.load()
    cost = spec["cost"]

    where = ""
    if order.get("company"):
        found = geo.locate(order.get("country"), order.get("city"))
        where = found["city"] if found else ""

    documents = "".join(
        f"<li>{html.escape(doc['kind'] or 'OTHER')} — {html.escape(doc['filename'])}</li>"
        for doc in order["documents"]
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(order['order_no'])} — specification and cost</title>
<style>{CSS}</style></head>
<body>
<div class="toolbar"><button onclick="window.print()">PRINT</button></div>

<div class="head">
  <div>
    <h1>{html.escape(order['order_no'])}</h1>
    <p class="sub">{html.escape(order.get('company') or '')}
      {(' · ' + html.escape(where)) if where else ''}<br>
      {html.escape(' '.join(filter(None, (order.get('product_code'),
                                          order.get('product_name')))))}
      {'<br>' if (order.get('product_code') or order.get('product_name')) else ''}
      {html.escape(order.get('description') or '')}</p>
  </div>
  <div style="text-align:right">
    <div class="badge">{html.escape(order['status'])}</div>
    <p class="sub" style="margin-top:8px">ORDER TRACKER<br>
      {datetime.now().strftime('%d %b %Y')}</p>
  </div>
</div>

{_spec_blocks(order, spec)}
{_cost_block(cost)}

{'<h2>Documents on file</h2><ul class="docs">' + documents + '</ul>' if documents else ''}

{('<h2>Notes</h2><p>' + html.escape(order['notes']).replace(chr(10), '<br>') + '</p>')
 if order.get('notes') else ''}

<footer>
  <span>{html.escape(order['order_no'])} · {html.escape(order.get('company') or '')}</span>
  <span>1 USD = {settings['fx_rate']:,.0f} KRW · printed
    {datetime.now().strftime('%d %b %Y %H:%M')}</span>
</footer>
</body></html>"""


# --- the case report -------------------------------------------------------

def case_sheet(case_id: int) -> str:
    """A printable report of one dispute: the position and the whole log.

    This is the document you take into a meeting, or attach to a credit
    note. It has to stand on its own, so every entry is printed in full —
    a log that hides its detail behind a click proves nothing on paper.
    """
    from . import cases

    case = cases.get_case(case_id)
    if case is None:
        return ""

    settings = prefs.load()
    claim_usd = ""
    if case.get("claim_krw"):
        rate = float(settings.get("fx_rate") or 1050)
        claim_usd = f" &nbsp; ({_usd(float(case['claim_krw']) / rate)})"

    position = _rows([
        ("CUSTOMER", _text(case.get("company"))),
        ("ORDER", _text(case.get("order_no"))),
        ("CUSTOMER PO", _text(case.get("po_number"))),
        ("LOT / BATCH", _text(case.get("lot_ref"))),
        ("KIND", _text(case.get("kind"))),
        ("SEVERITY", _text(case.get("severity"))),
        ("STATUS", _text(case.get("status"))),
        ("OPENED", _text(case.get("opened_at"))),
        ("ANSWER DUE", _text(case.get("due_at"))),
        ("CLOSED", _text(case.get("closed_at"))),
        ("QUANTITY AFFECTED", _num(case.get("qty_affected"))),
        ("VALUE CLAIMED", (_krw(case["claim_krw"]) + claim_usd)
         if case.get("claim_krw") else "—"),
        ("HANDLED BY", _text(case.get("owner"))),
    ])

    def block(title, text):
        if not text:
            return ""
        return (f"<h2>{html.escape(title)}</h2><p>"
                + html.escape(str(text)).replace("\n", "<br>") + "</p>")

    entries = "".join(
        f"""<tr>
              <td class="nowrap">{_text(entry.get('happened_at'))}</td>
              <td class="nowrap">{_text(entry.get('kind'))}</td>
              <td>{_text(entry.get('who'))}</td>
              <td>{_text(entry.get('summary'))}
                {('<div class="detail">'
                  + html.escape(entry['detail']).replace(chr(10), '<br>')
                  + '</div>') if entry.get('detail') else ''}
                {('<div class="detail">file: '
                  + html.escape(entry['filename']) + '</div>')
                 if entry.get('filename') else ''}</td>
              <td class="nowrap">{
                  (('DONE ' + str(entry['done_at'])[:10]) if entry.get('done_at')
                   else _text(entry.get('follow_up_at')))}</td>
            </tr>"""
        for entry in sorted(case["entries"],
                            key=lambda e: (e.get("happened_at") or "", e["id"]))
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(case['ref'])} — {html.escape(case['title'])}</title>
<style>{CSS}
.detail {{ color:#444; font-size:10.5px; margin-top:3px; white-space:normal }}
.nowrap {{ white-space:nowrap }}
table.log th {{ background:#f0f0f0; text-align:left }}
table.log td {{ vertical-align:top }}
</style></head>
<body>
<div class="toolbar"><button onclick="window.print()">PRINT</button></div>

<div class="head">
  <div>
    <h1>{html.escape(case['ref'])}</h1>
    <p class="sub">{html.escape(case['title'])}<br>
      {html.escape(case.get('company') or '')}
      {(' · ' + html.escape(case['order_no'])) if case.get('order_no') else ''}</p>
  </div>
  <div style="text-align:right">
    <div class="badge">{html.escape(case['status'])}</div>
    <p class="sub" style="margin-top:8px">ORDER TRACKER<br>
      {datetime.now().strftime('%d %b %Y')}</p>
  </div>
</div>

<h2>The position</h2>
<table>{position}</table>

{block('What is wrong', case.get('detail'))}
{block('Root cause', case.get('root_cause'))}
{block('Resolution', case.get('resolution'))}

<h2>Log of communications and actions</h2>
<table class="log">
  <tr><th>DATE</th><th>KIND</th><th>WHO</th><th>WHAT HAPPENED</th>
      <th>FOLLOW-UP</th></tr>
  {entries or '<tr><td colspan="5" class="none">nothing logged yet</td></tr>'}
</table>

<footer>
  <span>{html.escape(case['ref'])} · {html.escape(case.get('company') or '')}</span>
  <span>printed {datetime.now().strftime('%d %b %Y %H:%M')}</span>
</footer>
</body></html>"""


# --- the folder sheet ------------------------------------------------------

def folder_sheet(folder_id: int) -> str:
    """A printable summary of one enquiry folder: topic, position, log.

    What you print before a call, so the whole conversation to date fits on
    one sheet in front of you.
    """
    from . import threads

    folder = threads.get_folder(folder_id)
    if folder is None:
        return ""

    position = _rows([
        ("CUSTOMER", _text(folder.get("company"))),
        ("CONTACT", _text(folder.get("contact_name"))),
        ("EMAIL", _text(folder.get("contact_email"))),
        ("KIND", _text(folder.get("kind"))),
        ("STATUS", _text(folder.get("status"))),
        ("PRIORITY", _text(folder.get("priority"))),
        ("OPENED", _text(folder.get("opened_at"))),
        ("COME BACK TO IT", _text(folder.get("follow_up_at"))),
        ("CLOSED", _text(folder.get("closed_at"))),
        ("ORDER", _text(folder.get("order_no"))),
        ("WORTH", _usd(folder["value_usd"]) if folder.get("value_usd") else "—"),
        ("HANDLED BY", _text(folder.get("owner"))),
    ])

    def block(title, text):
        if not text:
            return ""
        return (f"<h2>{html.escape(title)}</h2><p>"
                + html.escape(str(text)).replace("\n", "<br>") + "</p>")

    entries = "".join(
        f"""<tr>
              <td class="nowrap">{_text(entry.get('happened_at'))}</td>
              <td class="nowrap">{_text(entry.get('kind'))}</td>
              <td>{_text(entry.get('who'))}</td>
              <td>{_text(entry.get('summary'))}
                {('<div class="detail">'
                  + html.escape(entry['detail']).replace(chr(10), '<br>')
                  + '</div>') if entry.get('detail') else ''}</td>
              <td class="nowrap">{
                  (('DONE ' + str(entry['done_at'])[:10]) if entry.get('done_at')
                   else _text(entry.get('follow_up_at')))}</td>
            </tr>"""
        for entry in sorted(folder["entries"],
                            key=lambda e: (e.get("happened_at") or "", e["id"]))
    )

    emails = "".join(
        f"<li>{_text(str(mail.get('sent_at') or mail.get('filed_at'))[:10])}"
        f" — {html.escape(mail.get('subject') or '(no subject)')}"
        f" <i>{html.escape(mail.get('from_name') or mail.get('from_email') or '')}</i></li>"
        for mail in folder.get("emails", []))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(folder['ref'])} — {html.escape(folder['topic'])}</title>
<style>{CSS}
.detail {{ color:#444; font-size:10.5px; margin-top:3px; white-space:normal }}
.nowrap {{ white-space:nowrap }}
table.log th {{ background:#f0f0f0; text-align:left }}
table.log td {{ vertical-align:top }}
</style></head>
<body>
<div class="toolbar"><button onclick="window.print()">PRINT</button></div>

<div class="head">
  <div>
    <h1>{html.escape(folder['ref'])}</h1>
    <p class="sub">{html.escape(folder['topic'])}<br>
      {html.escape(folder.get('company') or '')}</p>
  </div>
  <div style="text-align:right">
    <div class="badge">{html.escape(folder['status'])}</div>
    <p class="sub" style="margin-top:8px">ORDER TRACKER<br>
      {datetime.now().strftime('%d %b %Y')}</p>
  </div>
</div>

<h2>The folder</h2>
<table>{position}</table>

{block('What they want', folder.get('summary'))}
{block('Where it stands', folder.get('situation'))}

<h2>Log of communications and actions</h2>
<table class="log">
  <tr><th>DATE</th><th>KIND</th><th>WHO</th><th>WHAT HAPPENED</th>
      <th>FOLLOW-UP</th></tr>
  {entries or '<tr><td colspan="5" class="none">nothing logged yet</td></tr>'}
</table>

{'<h2>Email in this folder</h2><ul class="docs">' + emails + '</ul>' if emails else ''}

<footer>
  <span>{html.escape(folder['ref'])} · {html.escape(folder.get('company') or '')}</span>
  <span>printed {datetime.now().strftime('%d %b %Y %H:%M')}</span>
</footer>
</body></html>"""
