"""
Rapport PDF employé — ReportLab Platypus, design Distriprot, thème clair.
"""

import io
import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.platypus.flowables import KeepTogether

# ── Palette ──────────────────────────────────────────────────────────────────
C_BLUE   = colors.HexColor("#1a6ead")
C_BLUE2  = colors.HexColor("#155e96")
C_CARD   = colors.HexColor("#f4f7fb")
C_HEAD   = colors.HexColor("#f0f5fb")
C_BORDER = colors.HexColor("#e0eaf5")
C_WHITE  = colors.white
C_DARK   = colors.HexColor("#1a3a5c")
C_MUTED  = colors.HexColor("#8a9bb0")
C_ORANGE = colors.HexColor("#f0a500")
C_GREEN  = colors.HexColor("#2eaa6e")
C_RED    = colors.HexColor("#d94040")
C_AMBER  = colors.HexColor("#fff3d6")
C_AMBER_T= colors.HexColor("#b07a00")
C_BG     = colors.HexColor("#f4f7fb")

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ── Styles ────────────────────────────────────────────────────────────────────
def _s(name, **kw):
    defaults = dict(fontName="Helvetica", fontSize=10, leading=13,
                    textColor=C_DARK, spaceAfter=0, spaceBefore=0)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)

S_NORMAL  = _s("normal")
S_BOLD    = _s("bold",   fontName="Helvetica-Bold")
S_MUTED   = _s("muted",  textColor=C_MUTED, fontSize=8)
S_WHITE   = _s("white",  textColor=C_WHITE)
S_WBOLD   = _s("wbold",  textColor=C_WHITE, fontName="Helvetica-Bold")
S_ORANGE  = _s("orange", textColor=C_ORANGE, fontName="Helvetica-Bold")
S_GREEN   = _s("green",  textColor=C_GREEN,  fontName="Helvetica-Bold")
S_RED     = _s("red",    textColor=C_RED,    fontName="Helvetica-Bold")
S_SECTION = _s("section", textColor=C_WHITE, fontName="Helvetica-Bold",
               fontSize=9, leading=11)
S_KV      = _s("kv",     fontName="Helvetica-Bold", fontSize=18, leading=20, textColor=C_DARK)
S_KL      = _s("kl",     fontSize=7, leading=9, textColor=C_MUTED)

def _p(text, style=None): return Paragraph(str(text), style or S_NORMAL)
def _sp(h=4):             return Spacer(1, h)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _section_header(title, width=None):
    """Blue header row with white bold title."""
    w = width or CONTENT_W
    tbl = Table([[_p(f"<b>{title.upper()}</b>", S_SECTION)]], colWidths=[w])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_BLUE),
        ("LINEBELOW",     (0,0), (-1,-1), 2,   C_BLUE2),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ]))
    return tbl


def _kpi_cell(value, label, color=None):
    val_style = _s("kvc", fontName="Helvetica-Bold", fontSize=18, leading=20,
                   textColor=color or C_DARK)
    return [_p(str(value), val_style), _p(label.upper(), S_KL)]


def _kpi_row(cells, n=4):
    """n evenly-spaced KPI boxes."""
    w = (CONTENT_W - (n-1)*3) / n
    data  = [[cell[0] for cell in cells],
             [cell[1] for cell in cells]]
    style = TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_CARD),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("LEFTPADDING",   (0,0),(-1,-1), 9),
        ("RIGHTPADDING",  (0,0),(-1,-1), 9),
        ("SPAN",          (0,0),(0,1)),   # handled per-cell below
    ])
    # Build as separate mini-tables for each cell, laid out in one row
    cell_tbls = []
    for cell in cells:
        ct = Table([[cell[0]], [cell[1]]], colWidths=[w])
        ct.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_CARD),
            ("TOPPADDING",    (0,0),(-1,-1), 7),
            ("BOTTOMPADDING", (0,0),(-1,-1), 7),
            ("LEFTPADDING",   (0,0),(-1,-1), 9),
            ("RIGHTPADDING",  (0,0),(-1,-1), 9),
        ]))
        cell_tbls.append(ct)

    gaps   = [3] * (n - 1)
    widths = []
    row    = []
    for i, ct in enumerate(cell_tbls):
        widths.append(w)
        row.append(ct)
        if i < n - 1:
            widths.append(3)
            row.append("")

    outer = Table([row], colWidths=widths)
    outer.setStyle(TableStyle([
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))
    return outer


def _progress_bar(pct, label, color=C_ORANGE):
    pct = max(0, min(100, float(pct)))
    fill = CONTENT_W * pct / 100
    rest = CONTENT_W - fill

    bar_data  = [["", ""]]
    bar_widths = [fill, rest] if rest > 0 else [CONTENT_W, 0.1]
    bar = Table(bar_data, colWidths=bar_widths)
    bar.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,0), color),
        ("BACKGROUND",    (1,0),(1,0), C_BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))

    header = Table(
        [[_p(label, S_MUTED), _p(f"<b>{pct:.1f}%</b>", _s("pv", textColor=color, fontName="Helvetica-Bold", fontSize=9))]],
        colWidths=[CONTENT_W * 0.7, CONTENT_W * 0.3],
    )
    header.setStyle(TableStyle([
        ("ALIGN",         (1,0),(1,0), "RIGHT"),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))
    return [header, bar]


def _section_divider():
    """Thin orange accent line used as a visual separator between sections."""
    return HRFlowable(width=CONTENT_W, thickness=2, color=C_ORANGE, spaceAfter=8, spaceBefore=8)


def _card(header_title, inner_flowables):
    """Wrap flowables with a blue section header and bottom padding."""
    elements = [_section_header(header_title), _sp(8)]
    elements += inner_flowables
    elements.append(_sp(6))
    return elements


def _tag(text, bg, fg):
    t = Table([[_p(f"<b>{text}</b>", _s("tag", fontSize=8, textColor=fg, fontName="Helvetica-Bold"))]])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_chargement(c):
    items = []
    # KPI row
    items.append(_kpi_row([
        _kpi_cell(c["planifiees"], "Planifiées"),
        _kpi_cell(c["faites"],    "Faites",    C_GREEN),
        _kpi_cell(c["non_faites"],"Non faites",C_ORANGE),
        _kpi_cell(c["jokers"],    "Jokers"),
    ]))
    items.append(_sp(8))

    # Progress bar
    for fl in _progress_bar(c["taux"], "Taux de complétion chargements"):
        items.append(fl)
    items.append(_sp(10))

    # Day table
    day_data = [[
        _p("<b>Jour</b>",       S_MUTED),
        _p("<b>Faites</b>",     S_MUTED),
        _p("<b>Non faites</b>", S_MUTED),
        _p("<b>Statut</b>",     S_MUTED),
    ]]
    for j in c.get("jours", []):
        nf = j["non_faites"]
        tag = _tag("OK", colors.HexColor("#e4f5ec"), colors.HexColor("#1a8050")) if nf == 0 \
              else _tag(f"{nf} NF", C_AMBER, C_AMBER_T)
        day_data.append([
            _p(j["nom"], S_BOLD),
            _p(f"{j['faites']}/{j['prevues']}", S_NORMAL),
            _p(str(nf), _s("nf", textColor=C_ORANGE if nf else C_GREEN, fontName="Helvetica-Bold")),
            tag,
        ])
    cw = [CONTENT_W*0.28, CONTENT_W*0.22, CONTENT_W*0.22, CONTENT_W*0.28]
    day_tbl = Table(day_data, colWidths=cw)
    day_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1, 0), C_HEAD),
        ("LINEBELOW",     (0,0),(-1, 0), 0.5, C_BORDER),
        ("LINEBELOW",     (0,1),(-1,-1), 0.3, C_BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    items.append(day_tbl)
    return _card("Chargement — Performance globale", items)


def _build_non_faites(nf_list, nb_just, nb_nonjust):
    items = []
    # Pills
    pills = Table([[
        _tag(f"{nb_just} justifiée{'s' if nb_just!=1 else ''}",
             colors.HexColor("#e4f5ec"), colors.HexColor("#1a8050")),
        _tag(f"{nb_nonjust} non justifiée{'s' if nb_nonjust!=1 else ''}",
             colors.HexColor("#fce8e8"), colors.HexColor("#b03030")),
    ]])
    pills.setStyle(TableStyle([
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 4),
    ]))
    items.append(pills)

    # NF table
    nf_data = [[
        _p("<b>Jour</b>",    S_MUTED),
        _p("<b>Salle</b>",   S_MUTED),
        _p("<b>Statut</b>",  S_MUTED),
    ]]
    for r in nf_list:
        tag = _tag("Justifié",     colors.HexColor("#e4f5ec"), colors.HexColor("#1a8050")) \
              if r.get("justifie") \
              else _tag("Non justifié", colors.HexColor("#fce8e8"), colors.HexColor("#b03030"))
        nf_data.append([
            _p(r.get("jour_court",""), S_MUTED),
            _p(r.get("client",""),    S_NORMAL),
            tag,
        ])
    cw = [CONTENT_W*0.15, CONTENT_W*0.55, CONTENT_W*0.30]
    tbl = Table(nf_data, colWidths=cw)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1, 0), C_HEAD),
        ("LINEBELOW",     (0,0),(-1, 0), 0.5, C_BORDER),
        ("LINEBELOW",     (0,1),(-1,-1), 0.3, C_BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    items.append(tbl)
    return _card("Salles non faites & justifications", items)


def _build_picklist(p):
    items = []

    # ── Row 1 : big % (leading must match fontSize) ───────────────────────────
    badge = Table(
        [[_p(f"<b>{p['taux']}%</b>",
             _s("bp", fontSize=28, fontName="Helvetica-Bold",
                leading=34, textColor=C_ORANGE, alignment=TA_CENTER)),
          _p("Conformité\nglobale",
             _s("cgl", fontSize=9, textColor=C_MUTED, leading=13, alignment=TA_LEFT))]],
        colWidths=[30 * mm, CONTENT_W - 30 * mm],
    )
    badge.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))
    items.append(badge)
    items.append(_sp(8))

    # ── Row 2 : 4 KPI boxes ──────────────────────────────────────────────────
    items.append(_kpi_row([
        _kpi_cell(p["conformes"],    "Conformes",    C_GREEN),
        _kpi_cell(p["non_charges"],  "Non chargés",  C_RED),
        _kpi_cell(p["insuffisants"], "Insuffisants", C_ORANGE),
        _kpi_cell(p["surplus"],      "Surplus",      C_MUTED),
    ]))
    items.append(_sp(8))

    # ── Row 3 : meilleure & pire salle seulement ─────────────────────────────
    machines = p.get("machines", [])
    m_val_w  = 26 * mm
    m_lbl_w  = 28 * mm
    m_name_w = CONTENT_W - m_val_w - m_lbl_w
    m_data   = [[
        _p("<b>Salle</b>",      S_MUTED),
        _p("<b></b>",           S_MUTED),
        _p("<b>Conf.</b>",      S_MUTED),
    ]]
    if machines:
        best  = max(machines, key=lambda m: m["taux"])
        worst = min(machines, key=lambda m: m["taux"])
        for m, lbl, lbl_col in [
            (best,  "Meilleure", C_GREEN),
            (worst, "Pire",      C_RED),
        ]:
            t   = m["taux"]
            col = C_RED if t == 0 else (C_AMBER_T if t < 25 else C_GREEN)
            m_data.append([
                _p(m["client"], _s("mn", fontSize=9, textColor=C_DARK)),
                _tag(lbl, colors.HexColor("#e4f5ec") if lbl_col == C_GREEN else colors.HexColor("#fce8e8"), lbl_col),
                _p(f"<b>{t}%</b>", _s("mp", fontSize=9, fontName="Helvetica-Bold", textColor=col)),
            ])
    m_tbl = Table(m_data, colWidths=[m_name_w, m_lbl_w, m_val_w])
    m_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1, 0), C_HEAD),
        ("LINEBELOW",     (0,0),(-1, 0), 0.5, C_BORDER),
        ("LINEBELOW",     (0,1),(-1,-1), 0.3, C_BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("ALIGN",         (2,0),(2,-1), "RIGHT"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    items.append(m_tbl)
    return _card("Conformité picklist", items)


def _build_kpi_2x2(kpis, width=None):
    """2-row × 2-col KPI grid. width = total available width."""
    total = width if width is not None else CONTENT_W
    w = (total - 3) / 2
    rows = []
    for i in range(0, len(kpis), 2):
        row = []
        for cell in kpis[i:i+2]:
            ct = Table([[cell[0]], [cell[1]]], colWidths=[w])
            ct.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,-1), C_CARD),
                ("TOPPADDING",    (0,0),(-1,-1), 7),
                ("BOTTOMPADDING", (0,0),(-1,-1), 7),
                ("LEFTPADDING",   (0,0),(-1,-1), 9),
                ("RIGHTPADDING",  (0,0),(-1,-1), 9),
            ]))
            row.append(ct)
        if len(row) == 1:
            row.append("")
        rows.append(row)
        if i + 2 < len(kpis):
            rows.append(["", ""])   # spacer row

    grid = Table(rows, colWidths=[w, w], rowHeights=None)
    rh_style = []
    for idx, r in enumerate(rows):
        if r == ["", ""]:
            rh_style.append(("ROWHEIGHT", (0, idx), (-1, idx), 3))
    style = [
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ] + rh_style
    grid.setStyle(TableStyle(style))
    return grid


def _build_pointage(ptg):
    """Section Pointage pleine largeur."""
    items = []
    items.append(_kpi_row([
        _kpi_cell(ptg["jours_analyses"], "Jours analysés"),
        _kpi_cell(ptg["presences"],      "Présences",      C_GREEN),
        _kpi_cell(ptg["conges"],         "Congés"),
        _kpi_cell(ptg["absences"],       "Absences",
                  C_ORANGE if ptg["absences"] > 0 else None),
    ]))
    if ptg.get("sans_badge", 0) > 0:
        items.append(_sp(6))
        nb = ptg["sans_badge"]
        alert_tbl = Table(
            [[_p(f"<b>⚠ {nb} jour{'s' if nb != 1 else ''} sans badge</b>",
                 _s("al", fontSize=9, textColor=C_AMBER_T, fontName="Helvetica-Bold"))]],
            colWidths=[CONTENT_W],
        )
        alert_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_AMBER),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ]))
        items.append(alert_tbl)
    return _card("Pointage", items)


def _build_quartix(qtx):
    """Section Quartix pleine largeur."""
    items = []
    items.append(_kpi_row([
        _kpi_cell(qtx["trajets"],       "Trajets"),
        _kpi_cell(qtx["distance_km"],   "Distance (km)"),
        _kpi_cell(qtx["hors_horaires"], "Hors horaires",
                  C_RED if qtx["hors_horaires"] > 0 else C_GREEN),
        _kpi_cell(qtx["weekend"],       "Weekend",
                  C_RED if qtx["weekend"] > 0 else C_GREEN),
    ]))
    if qtx.get("periode"):
        items.append(_sp(5))
        per_tbl = Table(
            [[_p(qtx["periode"],
                 _s("per", fontSize=9, textColor=C_MUTED, alignment=TA_CENTER))]],
            colWidths=[CONTENT_W],
        )
        per_tbl.setStyle(TableStyle([
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
            ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ]))
        items.append(per_tbl)
    return _card("Quartix — Véhicule", items)


# ─────────────────────────────────────────────────────────────────────────────
# HEADER / FOOTER on canvas
# ─────────────────────────────────────────────────────────────────────────────

def _make_header_footer(meta):
    def _draw(canvas, doc):
        canvas.saveState()

        # Blue header band
        band_h = 44
        canvas.setFillColor(C_BLUE)
        canvas.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)

        # DISTRIPROT
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(MARGIN, PAGE_H - 22, "DISTRI")
        canvas.setFillColor(C_ORANGE)
        canvas.setFont("Helvetica-Bold", 16)
        x2 = MARGIN + canvas.stringWidth("DISTRI", "Helvetica-Bold", 16)
        canvas.drawString(x2, PAGE_H - 22, "PROT")

        # Subtitle
        canvas.setFillColor(colors.HexColor("#aaccee"))
        canvas.setFont("Helvetica", 9)
        canvas.drawString(MARGIN, PAGE_H - 35, "Rapport de performance")

        # Week tag + date (right side)
        tag_text = f"Semaine {meta.get('semaine','')} · {meta.get('annee','')}"
        canvas.setFillColor(colors.HexColor("#2a7fbe"))
        tag_w = canvas.stringWidth(tag_text, "Helvetica-Bold", 9) + 16
        canvas.roundRect(PAGE_W - MARGIN - tag_w, PAGE_H - 25, tag_w, 14, 3, fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(PAGE_W - MARGIN - tag_w + 8, PAGE_H - 18, tag_text)

        canvas.setFillColor(colors.HexColor("#aaccee"))
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 35,
                               f"Généré le {meta.get('date_gen','')}")

        # Employee name band
        canvas.setFillColor(C_BLUE2)
        canvas.rect(0, PAGE_H - band_h - 30, PAGE_W, 30, fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(MARGIN, PAGE_H - band_h - 20, meta.get("code", ""))
        if meta.get("zone"):
            canvas.setFont("Helvetica", 9)
            canvas.setFillColor(colors.HexColor("#aaccee"))
            name_w = canvas.stringWidth(meta["code"], "Helvetica-Bold", 18) + 12
            canvas.drawString(MARGIN + name_w, PAGE_H - band_h - 19,
                              f"Zone {meta['zone']}")

        # Footer band
        canvas.setFillColor(C_BLUE)
        canvas.rect(0, 0, PAGE_W, 22, fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, 7, "DISTRIPROT")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#aaccee"))
        canvas.drawString(MARGIN + 58, 7, "· Rapport hebdomadaire automatisé")
        canvas.drawRightString(PAGE_W - MARGIN, 7,
                               f"S{meta.get('semaine','')} · {meta.get('annee','')}")

        canvas.restoreState()
    return _draw


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def generate_pdf_report(data: dict) -> bytes:
    """Génère un PDF A4 Distriprot. Retourne les bytes."""
    meta       = data.get("meta", {})
    chargement = data.get("chargement")
    picklist   = data.get("picklist")
    pointage   = data.get("pointage")
    quartix    = data.get("quartix")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=82,    # space for header bands
        bottomMargin=28, # space for footer
    )

    story = []
    sections_built = 0

    def _add_section(flowables):
        nonlocal sections_built
        if sections_built > 0:
            story.append(_section_divider())
        for fl in flowables:
            story.append(fl)
        sections_built += 1

    if chargement:
        _add_section(_build_chargement(chargement))

    if picklist:
        _add_section(_build_picklist(picklist))

    if pointage:
        _add_section(_build_pointage(pointage))

    if quartix:
        _add_section(_build_quartix(quartix))

    doc.build(story, onFirstPage=_make_header_footer(meta),
              onLaterPages=_make_header_footer(meta))
    return buf.getvalue()
