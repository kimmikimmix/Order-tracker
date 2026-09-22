"""The PCB half of an order: build specification and costing.

An order in the blotter says who, how much and when. This module holds what
is actually being made — layers, materials, finish, drills — and turns the
won figures typed on the cost sheet into the dollar totals a customer sees.

Everything here is pure arithmetic on a dictionary, so the same numbers come
out on screen, on the printed sheet and in an export.
"""

from . import prefs

# --- Field definitions -----------------------------------------------------
# (name, kind). The kind decides how a value is cleaned on the way in and
# which control the form draws. Keep the order: it is the order of the form.

SPEC_FIELDS = [
    ("quote_date", "date"),
    ("quote_ref", "text"),
    ("contact_person", "text"),

    ("product_type", "text"),
    ("ipc_class", "text"),
    ("ccl_material", "text"),

    ("pcb_x_mm", "number"),
    ("pcb_y_mm", "number"),
    ("array_x_mm", "number"),
    ("array_y_mm", "number"),
    ("ups", "int"),
    ("panel_code", "text"),

    ("surface_finish", "text"),
    ("finish_thickness", "text"),

    ("layers", "int"),
    ("thickness_mm", "number"),
    ("thickness_tol_pct", "number"),
    ("copper_outer_oz", "number"),
    ("copper_inner_oz", "number"),

    ("impedance", "bool"),
    ("impedance_note", "text"),

    ("min_drill_mm", "number"),
    ("min_drill_count", "int"),
    ("total_drill_count", "int"),
    ("bvh", "bool"),
    ("bvh_layers", "text"),

    ("options", "text"),
    ("qty", "int"),
    ("lots", "int"),
]

COST_FIELDS = [
    ("pcb_total_krw", "number"),
    ("pcb_unit_krw", "number"),
    ("turnkey", "bool"),
    ("smt_total_krw", "number"),
    ("smt_unit_krw", "number"),
    ("stencil_count", "int"),
    ("stencil_unit_krw", "number"),
    ("parts_total_krw", "number"),
    ("parts_unit_krw", "number"),
    ("inflation_on", "bool"),
    ("inflation_rate", "number"),
    ("markup_on", "bool"),
    ("markup_pct", "number"),
    ("fx_rate", "number"),
]

ALL_FIELDS = SPEC_FIELDS + COST_FIELDS
FIELD_KINDS = dict(ALL_FIELDS)
FIELD_NAMES = [name for name, _ in ALL_FIELDS]

# Human labels, used by the form, the detail panel and the printed sheet.
LABELS = {
    "quote_date": "QUOTE DATE",
    "quote_ref": "QUOTE REF",
    "contact_person": "CONTACT PERSON",
    "product_type": "PRODUCT TYPE",
    "ipc_class": "CLASS",
    "ccl_material": "CCL MATERIAL",
    "pcb_x_mm": "PCB SIZE X (mm)",
    "pcb_y_mm": "PCB SIZE Y (mm)",
    "array_x_mm": "ARRAY X (mm)",
    "array_y_mm": "ARRAY Y (mm)",
    "ups": "UPS PER ARRAY",
    "panel_code": "WORKING PANEL",
    "surface_finish": "SURFACE FINISH",
    "finish_thickness": "FINISH THICKNESS",
    "layers": "LAYERS",
    "thickness_mm": "THICKNESS T (mm)",
    "thickness_tol_pct": "THICKNESS TOL (%)",
    "copper_outer_oz": "COPPER OUTER (oz)",
    "copper_inner_oz": "COPPER INNER (oz)",
    "impedance": "IMPEDANCE",
    "impedance_note": "IMPEDANCE NOTE",
    "min_drill_mm": "MIN DRILL (mm)",
    "min_drill_count": "MIN DRILL QTY",
    "total_drill_count": "TOTAL DRILLS",
    "bvh": "BVH",
    "bvh_layers": "BVH LAYERS",
    "options": "OPTIONS",
    "qty": "QTY PER LOT",
    "lots": "LOTS",
}

# One ounce of copper spread over a square foot is this thick.
OZ_TO_UM = 34.79


# --- Cleaning --------------------------------------------------------------

def as_number(value, default=None):
    """A float from anything a person or a spreadsheet might supply."""
    if value is None or value is True or value is False:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def as_int(value, default=None):
    number = as_number(value, None)
    return default if number is None else int(round(number))


def as_bool(value) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in ("1", "y", "yes", "true", "on") else 0
    return 1 if value else 0


def clean(data: dict) -> dict:
    """Take only the fields we know, in the shape the database wants."""
    from .orders import normalise_date

    out = {}
    for name, kind in ALL_FIELDS:
        if name not in data:
            continue
        value = data[name]
        if kind == "number":
            out[name] = as_number(value)
        elif kind == "int":
            out[name] = as_int(value)
        elif kind == "bool":
            out[name] = as_bool(value)
        elif kind == "date":
            out[name] = normalise_date(value)
        else:
            text = "" if value is None else str(value).strip()
            out[name] = text or None
    return out


def is_empty(spec: dict) -> bool:
    """True when nothing worth keeping was filled in."""
    for name, kind in ALL_FIELDS:
        value = spec.get(name)
        if value in (None, "", 0) or (kind == "bool" and not value):
            continue
        return False
    return True


# --- Derived engineering figures -------------------------------------------

def copper(oz):
    """Copper weight in the three units a fabricator quotes."""
    if oz is None:
        return None
    micron = oz * OZ_TO_UM
    return {"oz": oz, "um": round(micron, 2), "mm": round(micron / 1000.0, 4)}


def panel_for(code, settings=None):
    """Look up a working panel by its code."""
    settings = settings or prefs.load()
    for panel in settings.get("panel_sizes", []):
        if str(panel.get("code", "")).strip().upper() == str(code or "").strip().upper():
            return {"code": panel["code"],
                    "x": as_number(panel.get("x"), 0) or 0,
                    "y": as_number(panel.get("y"), 0) or 0}
    return None


def _fit(panel_x, panel_y, item_x, item_y):
    """How many item rectangles fit on a panel, trying both rotations."""
    if min(panel_x, panel_y, item_x, item_y) <= 0:
        return 0
    straight = int(panel_x // item_x) * int(panel_y // item_y)
    turned = int(panel_x // item_y) * int(panel_y // item_x)
    return max(straight, turned)


def derive(spec: dict, settings=None) -> dict:
    """Everything that follows from the specification without being typed."""
    settings = settings or prefs.load()
    out = {}

    out["copper_outer"] = copper(as_number(spec.get("copper_outer_oz")))
    out["copper_inner"] = copper(as_number(spec.get("copper_inner_oz")))

    thickness = as_number(spec.get("thickness_mm"))
    tolerance = as_number(spec.get("thickness_tol_pct"))
    if thickness is not None and tolerance is not None:
        span = thickness * tolerance / 100.0
        out["thickness_tol_mm"] = round(span, 3)
        out["thickness_min_mm"] = round(thickness - span, 3)
        out["thickness_max_mm"] = round(thickness + span, 3)

    qty = as_int(spec.get("qty"), 0) or 0
    lots = max(1, as_int(spec.get("lots"), 1) or 1)
    out["total_qty"] = qty * lots

    # Panel yield: how many boards come off one working panel, and how many
    # panels the order needs. Sales gets asked this on every enquiry.
    panel = panel_for(spec.get("panel_code"), settings)
    array_x = as_number(spec.get("array_x_mm"))
    array_y = as_number(spec.get("array_y_mm"))
    ups = as_int(spec.get("ups"), 1) or 1
    if panel:
        out["panel"] = panel
        margin = as_number(settings.get("panel_margin_mm"), 0) or 0
        usable_x = max(0.0, panel["x"] - 2 * margin)
        usable_y = max(0.0, panel["y"] - 2 * margin)
        out["panel_usable"] = {"x": round(usable_x, 1), "y": round(usable_y, 1)}
        if array_x and array_y:
            per_panel = _fit(usable_x, usable_y, array_x, array_y)
            out["arrays_per_panel"] = per_panel
            out["pcs_per_panel"] = per_panel * ups
            if per_panel and panel["x"] and panel["y"]:
                used = per_panel * array_x * array_y
                out["panel_use_pct"] = round(used / (panel["x"] * panel["y"]) * 100, 1)
            if out["total_qty"] and out.get("pcs_per_panel"):
                out["panels_needed"] = -(-out["total_qty"] // out["pcs_per_panel"])

    pcb_x = as_number(spec.get("pcb_x_mm"))
    pcb_y = as_number(spec.get("pcb_y_mm"))
    if pcb_x and pcb_y:
        out["pcb_area_mm2"] = round(pcb_x * pcb_y, 1)
        if out["total_qty"]:
            out["total_area_m2"] = round(pcb_x * pcb_y * out["total_qty"] / 1e6, 3)

    return out


# --- Costing ---------------------------------------------------------------

def _pair(total, unit, qty):
    """Fill in whichever of total and unit price was left blank."""
    total = as_number(total)
    unit = as_number(unit)
    if total is None and unit is not None and qty:
        total = unit * qty
    if total is not None and (unit is None or not unit) and qty:
        unit = total / qty
    return (total or 0.0), (unit or 0.0)


def cost_sheet(spec: dict, settings=None) -> dict:
    """Every money figure for an order, in won and dollars.

    Each section is shown three ways: what it costs, what it becomes after
    the inflation factor, and what it is quoted at once markup is added.
    """
    settings = settings or prefs.load()

    fx = as_number(spec.get("fx_rate")) or as_number(settings["fx_rate"]) or 1.0
    inflation_on = bool(spec.get("inflation_on"))
    inflation = as_number(spec.get("inflation_rate"))
    if inflation is None:
        inflation = as_number(settings["inflation_rate"], 1.0)
    markup_on = bool(spec.get("markup_on"))
    markup = as_number(spec.get("markup_pct"))
    if markup is None:
        markup = as_number(settings["markup_pct"], 0.0)

    qty = derive(spec, settings)["total_qty"]
    turnkey = bool(spec.get("turnkey"))

    pcb_total, pcb_unit = _pair(spec.get("pcb_total_krw"),
                                spec.get("pcb_unit_krw"), qty)

    stencil_count = as_int(spec.get("stencil_count"), 0) or 0
    stencil_unit = as_number(spec.get("stencil_unit_krw"))
    if stencil_unit is None:
        stencil_unit = as_number(settings["stencil_unit_krw"], 0.0)
    stencil_total = stencil_count * stencil_unit if turnkey else 0.0

    if turnkey:
        smt_total, smt_unit = _pair(spec.get("smt_total_krw"),
                                    spec.get("smt_unit_krw"), qty)
        parts_total, parts_unit = _pair(spec.get("parts_total_krw"),
                                        spec.get("parts_unit_krw"), qty)
    else:
        smt_total = smt_unit = parts_total = parts_unit = 0.0

    def section(label, base_krw, note=""):
        inflated = base_krw * inflation if inflation_on else base_krw
        quoted = inflated * (1 + markup / 100.0) if markup_on else inflated
        return {
            "label": label,
            "note": note,
            "base_krw": round(base_krw, 2),
            "inflated_krw": round(inflated, 2),
            "quoted_krw": round(quoted, 2),
            "quoted_usd": round(quoted / fx, 2) if fx else 0.0,
            "unit_krw": round(quoted / qty, 2) if qty else 0.0,
            "unit_usd": round(quoted / qty / fx, 4) if qty and fx else 0.0,
        }

    sections = [section("PCB MANUFACTURING", pcb_total)]
    if turnkey:
        stencil_note = (f"{stencil_count} stencil"
                        f"{'s' if stencil_count != 1 else ''} "
                        f"@ {stencil_unit:,.0f} KRW" if stencil_count else "")
        sections.append(section("SMT ASSEMBLY", smt_total + stencil_total,
                                stencil_note))
        sections.append(section("COMPONENTS", parts_total))

    grand_base = sum(s["base_krw"] for s in sections)
    grand = section("TOTAL", grand_base)

    return {
        "qty": qty,
        "turnkey": turnkey,
        "fx_rate": fx,
        "inflation_on": inflation_on,
        "inflation_rate": inflation,
        "markup_on": markup_on,
        "markup_pct": markup,
        "entered": {
            "pcb_total_krw": round(pcb_total, 2),
            "pcb_unit_krw": round(pcb_unit, 2),
            "smt_total_krw": round(smt_total, 2),
            "smt_unit_krw": round(smt_unit, 2),
            "stencil_count": stencil_count,
            "stencil_unit_krw": round(stencil_unit, 2),
            "stencil_total_krw": round(stencil_total, 2),
            "smt_with_stencil_krw": round(smt_total + stencil_total, 2),
            "parts_total_krw": round(parts_total, 2),
            "parts_unit_krw": round(parts_unit, 2),
        },
        "sections": sections,
        "total": grand,
    }
