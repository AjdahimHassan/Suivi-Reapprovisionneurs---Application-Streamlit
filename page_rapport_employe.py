"""
Page Rapport Employé — Vue complète par réapprovisionneur.

Sections :
  A. Hero — identité, semaine, taux de complétion
  B. KPIs hebdomadaires + barre de progression
  C. Détail par jour (5 cartes, lun–ven)
  D. Chargements : tableau statut par salle + justification des non-faites
  E. Picklist : taux de conformité (excluant les salles non faites)
  F. Pointage (placeholder)
  G. Quartix (placeholder)
"""

import io
import datetime
from collections import defaultdict

import pandas as pd
import streamlit as st

from planning_parser import JOURS
from mongo_storage import load_plannings_from_mongo, load_all_quartix_vehicles
from chargement_parser import croiser_planning_chargement
from page_picklist import (
    parse_picklist,
    analyser as _analyser_picklist,
    _stats_machine,
    _couleur_conformite,
    _COULEURS,
    _styler,
)


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

_CSS_DARK = """<style>
.re-section-label {
    font-size: 0.70rem; font-weight: 700; letter-spacing: 0.15em;
    text-transform: uppercase; color: #7BC4E8;
    display: flex; align-items: center; gap: 10px;
    margin: 28px 0 14px;
}
.re-section-label::after {
    content: ""; flex: 1; height: 1px;
    background: linear-gradient(to right, rgba(42,74,107,0.7), transparent);
}
.re-section-label .count { color: #8FA8C8; font-weight: 500; letter-spacing: 0.04em; font-size: 0.68rem; }

.re-avatar {
    width: 72px; height: 72px; border-radius: 50%;
    background: linear-gradient(135deg, #2A4A6B, #1E2E42);
    border: 1px solid #2A4A6B;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.9rem; font-weight: 700; color: #7BC4E8;
    font-family: "Inter", sans-serif; letter-spacing: -0.02em;
    flex-shrink: 0;
}

.re-hero-name {
    font-size: 1.7rem; font-weight: 800; color: #E8EEF7;
    letter-spacing: -0.02em;
    display: flex; align-items: center; gap: 10px; margin: 0 0 6px;
}
.re-code-chip {
    font-family: "JetBrains Mono", "Courier New", monospace;
    font-size: 0.7rem; font-weight: 600; color: #7BC4E8;
    background: rgba(123,196,232,0.10); border: 1px solid rgba(123,196,232,0.25);
    border-radius: 6px; padding: 3px 8px;
}
.re-meta {
    color: #8FA8C8; font-size: 0.82rem;
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    margin-top: 2px;
}
.re-meta b { color: #E8EEF7; font-weight: 600; }
.re-meta .sep { width: 3px; height: 3px; border-radius: 50%; background: #2A4A6B; display: inline-block; }
.re-pills { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 10px; }
.re-pill {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 2px 9px; border-radius: 99px;
    font-size: 0.7rem; font-weight: 600; border: 1px solid transparent;
}
.re-pill .dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.re-pill-green  { color: #52b788; background: rgba(46,125,50,0.14); border-color: rgba(46,125,50,0.38); }
.re-pill-orange { color: #E8922A; background: rgba(232,146,42,0.12); border-color: rgba(232,146,42,0.33); }
.re-pill-red    { color: #ef5350; background: rgba(198,40,40,0.14); border-color: rgba(198,40,40,0.38); }
.re-pill-blue   { color: #7BC4E8; background: rgba(123,196,232,0.11); border-color: rgba(123,196,232,0.28); }
.re-pill-purple { color: #ce93d8; background: rgba(156,39,176,0.14); border-color: rgba(156,39,176,0.33); }
.re-pill-muted  { color: #8FA8C8; background: #1E2E42; border-color: #2A4A6B; }

.re-kpi {
    background: #1A2535; border: 1px solid #2A4A6B; border-radius: 12px;
    padding: 1rem 1.25rem;
}
.re-kpi .kl { font-size: 0.68rem; font-weight: 600; color: #8FA8C8; text-transform: uppercase; letter-spacing: 0.1em; }
.re-kpi .kv { font-size: 2.1rem; font-weight: 800; color: #E8EEF7; letter-spacing: -0.03em; margin: 6px 0 8px; line-height: 1; }
.re-kpi .kf { font-size: 0.74rem; color: #8FA8C8; }
.re-kpi .kf b { color: #E8EEF7; font-weight: 600; }
.re-kpi-done { border-color: rgba(46,125,50,0.35) !important; }
.re-kpi-miss { border-color: rgba(198,40,40,0.30) !important; }
.re-kpi-joker { border-color: rgba(156,39,176,0.30) !important; }

.re-progress {
    background: #1A2535; border: 1px solid #2A4A6B; border-radius: 12px;
    padding: 1rem 1.25rem; margin-top: 14px;
}
.re-progress .ph { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.re-progress .pt { font-size: 0.73rem; color: #8FA8C8; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }
.re-progress .pv { font-size: 1.35rem; font-weight: 800; letter-spacing: -0.02em; }
.re-progress .pv .obj { font-size: 0.68rem; color: #8FA8C8; font-weight: 500; margin-left: 8px; }
.re-bar-track { height: 10px; background: rgba(42,74,107,0.5); border-radius: 99px; position: relative; overflow: visible; }
.re-bar-fill { height: 100%; border-radius: 99px; position: absolute; top: 0; left: 0; }
.re-bar-target { position: absolute; top: -3px; bottom: -3px; width: 2px; background: #E8922A; box-shadow: 0 0 0 1px rgba(232,146,42,0.3); }
.re-bar-target-lbl {
    position: absolute; top: -18px; left: 50%; transform: translateX(-50%);
    font-size: 0.6rem; color: #E8922A; white-space: nowrap; font-weight: 600; letter-spacing: 0.04em;
}

.re-day {
    background: #1A2535; border: 1px solid #2A4A6B;
    border-left: 3px solid #2A4A6B; border-radius: 10px;
    padding: 14px 16px;
}
.re-day.full    { border-left-color: #52b788; }
.re-day.partial { border-left-color: #E8922A; }
.re-day.miss    { border-left-color: #ef5350; }
.re-day.empty   { opacity: 0.55; }
.re-day .dn { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: #8FA8C8; }
.re-day .dc { font-size: 1.5rem; font-weight: 800; margin-top: 6px; letter-spacing: -0.02em; color: #E8EEF7; line-height: 1; }
.re-day .dc .denom { color: #8FA8C8; font-weight: 500; font-size: 1rem; }
.re-day .dm { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 8px; }
.re-minibar { display: flex; height: 4px; border-radius: 4px; overflow: hidden; background: rgba(42,74,107,0.5); margin-top: 7px; }
.re-minibar span { display: block; height: 100%; }
.re-mb-done   { background: #52b788; }
.re-mb-joker  { background: #ce93d8; }
.re-mb-miss   { background: #ef5350; }

.re-placeholder {
    background: #1A2535; border: 1px dashed #2A4A6B; border-radius: 12px;
    padding: 36px 24px; text-align: center;
}
.re-placeholder .ph-icon { font-size: 2rem; margin-bottom: 8px; display: block; }
.re-placeholder .ph-title { color: #E8EEF7; font-weight: 700; font-size: 1rem; margin-bottom: 4px; display: block; }
.re-placeholder .ph-sub { color: #8FA8C8; font-size: 0.83rem; display: block; }

.re-inc-row {
    background: #1A2535; border: 1px solid #2A4A6B;
    border-left: 3px solid #2A4A6B; border-radius: 10px;
    padding: 12px 16px; margin-bottom: 8px;
}
.re-inc-row.miss  { border-left-color: #ef5350; }
.re-inc-row.joker { border-left-color: #ce93d8; }
.re-inc-row.done  { border-left-color: #52b788; }
.re-inc-row.decale { border-left-color: #7BC4E8; }
.re-inc-row .salle { font-weight: 600; color: #E8EEF7; font-size: 0.9rem; }
.re-inc-row .machine { color: #8FA8C8; font-size: 0.75rem; margin-top: 2px; font-family: monospace; }
</style>"""

_CSS_LIGHT_PATCH = """<style>
.re-kpi, .re-progress, .re-day, .re-placeholder, .re-inc-row {
    background: #f8f9fb !important; border-color: #d8e4f0 !important;
}
.re-hero-name, .re-day .dc, .re-kpi .kv, .re-placeholder .ph-title { color: #1B3D6F !important; }
.re-meta, .re-day .dn, .re-kpi .kl, .re-progress .pt,
.re-placeholder .ph-sub, .re-inc-row .machine { color: #5a7190 !important; }
.re-meta b, .re-kpi .kf b { color: #1B3D6F !important; }
.re-kpi .kf { color: #5a7190 !important; }
.re-section-label { color: #1B3D6F !important; }
.re-section-label::after { background: linear-gradient(to right, rgba(27,61,111,0.25), transparent) !important; }
.re-section-label .count { color: #5a7190 !important; }
.re-code-chip { color: #1B3D6F !important; background: rgba(27,61,111,0.08) !important; border-color: rgba(27,61,111,0.2) !important; }
.re-pill-green  { color: #155724 !important; background: rgba(40,167,69,0.10) !important; border-color: rgba(40,167,69,0.28) !important; }
.re-pill-orange { color: #7d4e00 !important; background: rgba(232,146,42,0.10) !important; border-color: rgba(232,146,42,0.28) !important; }
.re-pill-red    { color: #721c24 !important; background: rgba(220,53,69,0.10) !important; border-color: rgba(220,53,69,0.28) !important; }
.re-pill-blue   { color: #004085 !important; background: rgba(0,100,200,0.09) !important; border-color: rgba(0,100,200,0.22) !important; }
.re-pill-purple { color: #5b2080 !important; background: rgba(156,39,176,0.10) !important; border-color: rgba(156,39,176,0.25) !important; }
.re-pill-muted  { color: #5a7190 !important; background: #e8eef5 !important; border-color: #c8d8e8 !important; }
.re-bar-track { background: rgba(0,0,0,0.09) !important; }
.re-minibar { background: rgba(0,0,0,0.09) !important; }
.re-inc-row .salle { color: #1B3D6F !important; }
</style>"""


# ─────────────────────────────────────────────────────────────────────────────
# SMALL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _inject_css() -> None:
    st.markdown(_CSS_DARK, unsafe_allow_html=True)
    if not st.session_state.get("dark_mode", False):
        st.markdown(_CSS_LIGHT_PATCH, unsafe_allow_html=True)


def _section_label(text: str, count: str = "") -> None:
    count_html = f'<span class="count">— {count}</span>' if count else ""
    st.markdown(
        f'<div class="re-section-label">{text}{count_html}</div>',
        unsafe_allow_html=True,
    )


def _pill(text: str, color: str = "blue") -> str:
    return (
        f'<span class="re-pill re-pill-{color}">'
        f'<span class="dot"></span>{text}</span>'
    )


def _mini_ring_svg(pct: float | None, label: str, color: str = "#52b788") -> str:
    r = 28
    circumference = 2 * 3.14159265 * r
    if pct is None:
        offset   = circumference
        pct_txt  = "—"
        stroke   = "rgba(42,74,107,0.55)"
    else:
        offset   = circumference * (1 - max(0.0, min(100.0, pct)) / 100)
        pct_txt  = f"{pct:.0f}%"
        stroke   = color
    txt_fill = "#E8EEF7" if st.session_state.get("dark_mode", False) else "#1B3D6F"
    return (
        f'<div style="display:inline-flex;flex-direction:column;align-items:center;gap:6px;">'
        f'<svg width="72" height="72" viewBox="0 0 70 70">'
        f'<g transform="rotate(-90 35 35)">'
        f'<circle cx="35" cy="35" r="{r}" fill="none" stroke="rgba(42,74,107,0.55)" stroke-width="6"/>'
        f'<circle cx="35" cy="35" r="{r}" fill="none" stroke="{stroke}" stroke-width="6"'
        f' stroke-linecap="round" stroke-dasharray="{circumference:.2f}"'
        f' stroke-dashoffset="{offset:.2f}"/>'
        f'</g>'
        f'<text x="35" y="40" text-anchor="middle" font-family="Inter,sans-serif"'
        f' font-size="13" font-weight="800" fill="{txt_fill}">{pct_txt}</text>'
        f'</svg>'
        f'<div style="font-size:0.63rem;font-weight:600;color:#8FA8C8;text-transform:uppercase;'
        f'letter-spacing:0.09em;text-align:center;">{label}</div>'
        f'</div>'
    )


def _ring_svg(pct: float, color: str = "#52b788") -> str:
    r = 44
    cx = cy = 55
    circumference = 2 * 3.14159265 * r
    offset = circumference * (1 - max(0.0, min(100.0, pct)) / 100)
    txt_fill = "#E8EEF7" if st.session_state.get("dark_mode", False) else "#1B3D6F"
    return (
        f'<svg width="110" height="110" viewBox="0 0 110 110">'
        f'<g transform="rotate(-90 55 55)">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(42,74,107,0.55)" stroke-width="8"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="8"'
        f' stroke-linecap="round" stroke-dasharray="{circumference:.2f}"'
        f' stroke-dashoffset="{offset:.2f}"/>'
        f'</g>'
        f'<text x="55" y="50" text-anchor="middle" font-family="Inter,sans-serif"'
        f' font-size="17" font-weight="800" fill="{txt_fill}">{pct:.1f}%</text>'
        f'<text x="55" y="66" text-anchor="middle" font-family="Inter,sans-serif"'
        f' font-size="9" font-weight="600" fill="#8FA8C8" letter-spacing="1">TAUX</text>'
        f'<text x="55" y="82" text-anchor="middle" font-family="Inter,sans-serif"'
        f' font-size="8" font-weight="500" fill="#8FA8C8">COMPLÉTION</text>'
        f'</svg>'
    )


def _bar_html(pct: float, obj_pct: float = 90.0) -> str:
    if pct >= obj_pct:
        fill_class = "re-bar-fill"
        fill_style = "background: linear-gradient(to right, #52b788, #74c69d);"
        val_color  = "#52b788"
    elif pct >= obj_pct * 0.8:
        fill_class = "re-bar-fill"
        fill_style = "background: linear-gradient(to right, #E8922A, #f4b06b);"
        val_color  = "#E8922A"
    else:
        fill_class = "re-bar-fill"
        fill_style = "background: linear-gradient(to right, #ef5350, #f57f7e);"
        val_color  = "#ef5350"

    obj_left = min(obj_pct, 100)
    fill_pct = min(pct, 100)

    return f"""
<div class="re-progress">
  <div class="ph">
    <span class="pt">Taux de complétion</span>
    <span class="pv" style="color:{val_color};">{pct:.1f}%</span>
  </div>
  <div class="re-bar-track" style="height:10px;">
    <div class="{fill_class}" style="width:{fill_pct:.1f}%;{fill_style}"></div>
    <div class="re-bar-target" style="left:{obj_left:.1f}%;">
      <span class="re-bar-target-lbl">obj. {obj_pct:.0f}%</span>
    </div>
  </div>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=300)
def _get_plannings():
    return load_plannings_from_mongo()


def _parse_adv_as_chargement_dict(content: bytes) -> dict:
    """
    Parse le fichier ADV/ERP (format picklist, colonnes : Stock Destination,
    Ressource, Quantité, Type tâche, Statut, Nom client) et retourne le même
    format que parse_chargement_csv :
      { machine_id: [{'employe', 'client', 'is_fait', 'val_ref', 'statut'}] }

    Accepte aussi l'ancien format quotidien (Machine, Employé, Val. Ref) en
    essayant les deux mappings successivement.
    """
    df = None
    read_errors = []
    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            _df = pd.read_csv(
                io.BytesIO(content), sep=";", dtype=str,
                encoding=enc, on_bad_lines="skip",
            )
            if len(_df.columns) >= 4:
                df = _df
                break
        except Exception as exc:
            read_errors.append(str(exc))

    if df is None:
        raise ValueError(f"Impossible de lire le fichier ADV. Erreurs : {read_errors}")

    df.columns = [c.strip().strip('"') for c in df.columns]
    col_lower  = {c.lower(): c for c in df.columns}

    def _find(*candidates):
        for cand in candidates:
            if cand in col_lower:
                return col_lower[cand]
        return None

    # ADV/ERP column names first, then legacy daily-chargement names
    machine_col = _find("stock destination", "machine", "équipement", "equipement")
    employe_col = _find("ressource", "employé", "employe", "technicien", "agent")
    # Prefer monetary amount (Montant HT ≈ Val. Ref), fall back to quantity
    valeur_col  = _find("montant ht", "montant", "val. ref", "val.ref", "quantité", "quantite", "valeur", "prix")
    statut_col  = _find("statut", "status", "état", "etat")   # optional in ADV format
    client_col  = _find("nom client", "tiers", "client", "salle", "site")
    type_col    = _find("type tâche", "type tache", "type")
    qty_col     = _find("quantité", "quantite", "quantity")   # used for is_fait when no statut

    missing = [
        label for label, col in [
            ("machine (Stock Destination / Machine)", machine_col),
            ("employé (Ressource / Employé)",          employe_col),
        ] if col is None
    ]
    if missing:
        raise ValueError(
            f"Colonnes introuvables dans le fichier ADV : {missing}.\n"
            f"Colonnes présentes : {list(df.columns)}"
        )

    # Filter on task type when the column exists
    if type_col:
        mask = df[type_col].str.strip().str.strip('"').isin(
            ["Chargement machine", "Chargement"]
        )
        df = df[mask]

    df = df.dropna(subset=[machine_col])
    df = df[df[machine_col].astype(str).str.strip() != ""]

    def _parse_val(v):
        try:
            return float(str(v).replace(",", ".").replace(" ", "").replace("\xa0", ""))
        except Exception:
            return 0.0

    result: dict = defaultdict(list)
    for _, row in df.iterrows():
        statut  = str(row[statut_col]).strip().capitalize() if statut_col else "Fait"
        valeur  = _parse_val(row[valeur_col]) if valeur_col else 0.0
        qty     = _parse_val(row[qty_col])    if qty_col    else valeur
        employe = str(row[employe_col]).strip()
        machine = str(row[machine_col]).strip()
        client  = (
            str(row[client_col]).strip()
            if client_col and pd.notna(row.get(client_col))
            else ""
        )
        # is_fait: quantity loaded > 0 (ADV format has no explicit Statut)
        # OR legacy daily format: Fait/Annulé + val ≠ 0
        is_fait = (qty > 0) or (statut in ("Fait", "Annulé") and valeur != 0.0)
        result[machine].append({
            "employe": employe,
            "client":  client,
            "statut":  statut,
            "is_fait": is_fait,
            "val_ref": valeur,
        })

    return dict(result)


def _croiser_semaine(plannings: dict, chargement: dict, employe: str) -> dict:
    """Cross-reference planning vs chargement for all 5 days. Returns {jour: data}."""
    out = {}
    for jour in JOURS:
        jour_results = croiser_planning_chargement(plannings, chargement, jour)
        out[jour] = jour_results.get(employe, {
            "salles_prevues":    [],
            "salles_faites":     [],
            "salles_non_faites": [],
            "tournee_decalee":   None,
        })
    return out


def _parse_adv_for_picklist(content: bytes, employe: str | None = None) -> pd.DataFrame:
    """
    Parse le fichier ADV pour l'analyse picklist.
    Filtre optionnellement sur la colonne Ressource = employe.
    Retourne un DataFrame compatible avec analyser() de page_picklist.
    """
    df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.strip('"')

    if "Type tâche" in df.columns:
        df = df[df["Type tâche"].str.strip().str.strip('"') == "Chargement machine"]

    if employe and "Ressource" in df.columns:
        df = df[df["Ressource"].str.strip() == employe.strip()]

    for col in ["Stock Destination", "Libellé produit", "Nom client"]:
        if col in df.columns:
            df[col] = df[col].str.strip().str.strip('"')

    if "Quantité" in df.columns:
        df["Quantité"] = (
            pd.to_numeric(df["Quantité"].str.strip(), errors="coerce")
            .fillna(0)
            .astype(int)
        )

    rename_map = {}
    if "Stock Destination" in df.columns:
        rename_map["Stock Destination"] = "Code Machine"
    if "Nom client" in df.columns:
        rename_map["Nom client"] = "Nom client charg"
    if rename_map:
        df = df.rename(columns=rename_map)

    if "Code Machine" not in df.columns or "Quantité" not in df.columns:
        return pd.DataFrame(
            columns=["Code Machine", "Nom client charg", "Libellé produit", "Quantité"]
        )

    group_cols = [c for c in ["Code Machine", "Nom client charg", "Libellé produit"] if c in df.columns]
    return df.groupby(group_cols, as_index=False)["Quantité"].sum()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION RENDERERS
# ─────────────────────────────────────────────────────────────────────────────

def _render_hero(employe: str, weekly: dict, meta: dict) -> None:
    """Section A — Identity hero with completion ring."""
    total_prevu = sum(len(d["salles_prevues"])    for d in weekly.values())
    total_fait  = sum(len(d["salles_faites"])      for d in weekly.values())
    nb_joker    = sum(
        sum(1 for s in d["salles_faites"] if s.get("is_joker"))
        for d in weekly.values()
    )
    taux = round((total_fait / total_prevu * 100) if total_prevu > 0 else 0.0, 1)

    ring_color = "#52b788" if taux >= 90 else ("#E8922A" if taux >= 75 else "#ef5350")

    if taux >= 90:
        status_pill = _pill("Objectif atteint", "green")
    elif taux >= 75:
        status_pill = _pill("En cours", "orange")
    else:
        status_pill = _pill("Sous objectif", "red")

    iso_year, iso_week, _ = datetime.date.today().isocalendar()
    semaine_label = f"S{iso_week} · {iso_year}"
    prenom   = meta.get("prenom", employe)
    initiale = prenom[0].upper() if prenom else employe[0].upper()

    # Build meta line
    meta_parts = []
    if meta.get("zone"):
        meta_parts.append(f"Zone **{meta['zone']}**")
    if meta.get("responsable"):
        meta_parts.append(f"Responsable **{meta['responsable']}**")
    meta_parts.append(f"**{total_prevu}** salles planifiées")
    meta_line = " · ".join(meta_parts)

    # Use st.columns so layout is reliable regardless of Streamlit version
    col_avatar, col_info = st.columns([1, 8])

    with col_avatar:
        st.markdown(
            f'<div class="re-avatar" style="margin-top:8px;">{initiale}</div>',
            unsafe_allow_html=True,
        )

    with col_info:
        st.markdown(
            f'<div class="re-hero-name">{prenom}'
            f'<span class="re-code-chip">{employe}</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(meta_line)
        pills_html = (
            status_pill
            + _pill(semaine_label, "blue")
            + (_pill(f"{nb_joker} joker(s)", "purple") if nb_joker else "")
        )
        st.markdown(
            f'<div class="re-pills" style="margin-top:6px;">{pills_html}</div>',
            unsafe_allow_html=True,
        )


def _render_kpis(weekly: dict) -> None:
    """Section B — 4 KPI cards + progress bar."""
    total_prevu  = sum(len(d["salles_prevues"])    for d in weekly.values())
    total_fait   = sum(len(d["salles_faites"])      for d in weekly.values())
    total_nf     = sum(len(d["salles_non_faites"])  for d in weekly.values())
    nb_joker     = sum(
        sum(1 for s in d["salles_faites"] if s.get("is_joker"))
        for d in weekly.values()
    )
    taux = round((total_fait / total_prevu * 100) if total_prevu > 0 else 0.0, 1)

    kpi_html = lambda cls, label, value, foot: f"""
<div class="re-kpi {cls}">
  <div class="kl">{label}</div>
  <div class="kv">{value}</div>
  <div class="kf">{foot}</div>
</div>"""

    fait_propre = total_fait - nb_joker
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_html("", "◈ Planifiées", total_prevu,
                             "Total machines cette semaine"), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_html("re-kpi-done", "✓ Faites", total_fait,
                             f"<b>{fait_propre}</b> par vous · <b>{nb_joker}</b> joker(s)"),
                    unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_html("re-kpi-joker", "⇄ Jokers", nb_joker,
                             "Faites par un collègue"), unsafe_allow_html=True)
    with c4:
        nf_delta = f'<b style="color:#ef5350;">−{total_nf}</b>' if total_nf else "Aucune"
        st.markdown(kpi_html("re-kpi-miss", "✕ Non faites", total_nf,
                             f"{nf_delta} vs planning"), unsafe_allow_html=True)

    st.markdown(_bar_html(taux), unsafe_allow_html=True)


def _render_day_strip(weekly: dict) -> None:
    """Section C — 5 day cards (visual only)."""
    cols = st.columns(5)
    for i, jour in enumerate(JOURS):
        d         = weekly[jour]
        nb_prevu  = len(d["salles_prevues"])
        nb_fait   = len(d["salles_faites"])
        nb_joker  = sum(1 for s in d["salles_faites"] if s.get("is_joker"))
        nb_miss   = len(d["salles_non_faites"])
        nb_propre = nb_fait - nb_joker

        if nb_prevu == 0:
            day_cls = "empty"
        elif nb_miss == 0:
            day_cls = "full"
        elif nb_fait == 0:
            day_cls = "miss"
        else:
            day_cls = "partial"

        # mini bar proportions
        done_pct  = (nb_propre / nb_prevu * 100) if nb_prevu else 0
        joker_pct = (nb_joker  / nb_prevu * 100) if nb_prevu else 0
        miss_pct  = (nb_miss   / nb_prevu * 100) if nb_prevu else 0
        minibar = (
            f'<span class="re-mb-done"   style="width:{done_pct:.0f}%"></span>'
            f'<span class="re-mb-joker"  style="width:{joker_pct:.0f}%"></span>'
            f'<span class="re-mb-miss"   style="width:{miss_pct:.0f}%"></span>'
        )

        pills = ""
        if nb_miss == 0 and nb_prevu > 0:
            pills += _pill("Complet", "green")
        if nb_joker:
            pills += _pill(f"+{nb_joker} joker(s)", "purple")
        if nb_miss:
            pills += _pill(f"−{nb_miss}", "red")
        if nb_prevu == 0:
            pills += _pill("Repos", "muted")

        with cols[i]:
            st.markdown(f"""
<div class="re-day {day_cls}">
  <div class="dn">{jour}</div>
  <div class="dc">{nb_fait}<span class="denom">/{nb_prevu}</span></div>
  <div class="re-minibar">{minibar}</div>
  <div class="dm">{pills}</div>
</div>""", unsafe_allow_html=True)


def _render_chargements_detail(weekly: dict, employe: str) -> None:
    """
    Section D — Tableau détaillé des salles avec statuts.
    Permet de marquer les salles non faites comme justifiées ou non.
    """
    st.session_state.setdefault("re_justifications", {})

    for jour in JOURS:
        d = weekly[jour]
        nb_prevu = len(d["salles_prevues"])
        nb_fait  = len(d["salles_faites"])
        nb_nf    = len(d["salles_non_faites"])

        if nb_prevu == 0:
            continue

        decale = d.get("tournee_decalee")
        extra = ""
        if decale:
            extra = f" · 📅 tournée du {decale['jour_detecte']} détectée"

        label = f"{jour} — {nb_fait}/{nb_prevu} salles faites"
        if nb_nf:
            label += f" · {nb_nf} non faite(s)"
        if extra:
            label += extra

        with st.expander(label, expanded=(nb_nf > 0)):

            # Salles faites (propres + jokers)
            rows_faites = []
            for s in d["salles_faites"]:
                if s.get("is_joker"):
                    statut_disp = "🔄 Joker"
                    statut_cls  = "joker"
                else:
                    statut_disp = "✅ Fait"
                    statut_cls  = "done"
                rows_faites.append({
                    "Statut":      statut_disp,
                    "Client / Salle": s["client"],
                    "Machine":     s["machine"],
                    "Fait par":    s.get("employe_reel", ""),
                    "Val. Réf (€)":  s.get("val_ref", ""),
                })

            # Tournée décalée
            if decale:
                st.info(
                    f"📅 **Tournée décalée** — {decale['nb_machines_faites']} machine(s) faite(s) "
                    f"correspondent au planning du **{decale['jour_detecte']}** plutôt qu'aujourd'hui.",
                    icon=None,
                )

            if rows_faites:
                df_f = pd.DataFrame(rows_faites)

                def _color_fait(row):
                    if "Joker" in str(row["Statut"]):
                        return ["background-color:rgba(156,39,176,0.18);color:#ce93d8;font-weight:600"] * len(row)
                    return ["background-color:rgba(46,125,50,0.15);color:#52b788;font-weight:600"] * len(row)

                st.dataframe(
                    df_f.style.apply(_color_fait, axis=1),
                    use_container_width=True,
                    hide_index=True,
                    height=min(40 + 35 * len(df_f), 400),
                )

            # Salles non faites + justification
            if d["salles_non_faites"]:
                st.markdown(
                    f'<div style="margin:12px 0 8px;font-size:0.8rem;font-weight:700;'
                    f'color:#ef5350;">❌ Salles non faites — justification</div>',
                    unsafe_allow_html=True,
                )
                for salle in d["salles_non_faites"]:
                    machine = salle["machine"]
                    client  = salle["client"]
                    jkey    = f"{employe}_{jour}_{machine}"
                    justifs = st.session_state["re_justifications"]

                    col_info, col_statut, col_comment = st.columns([2, 1.5, 3])
                    with col_info:
                        st.markdown(
                            f'<div class="re-inc-row miss">'
                            f'<div class="salle">❌ {client}</div>'
                            f'<div class="machine">{machine}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with col_statut:
                        current_statut = justifs.get(jkey, {}).get("type", "Non justifié")
                        choix = st.selectbox(
                            "Statut",
                            ["Non justifié", "Justifié"],
                            index=0 if current_statut == "Non justifié" else 1,
                            key=f"sel_{jkey}",
                            label_visibility="collapsed",
                        )
                    with col_comment:
                        current_comment = justifs.get(jkey, {}).get("comment", "")
                        comment = st.text_input(
                            "Justification",
                            value=current_comment,
                            placeholder="Motif (optionnel)...",
                            key=f"txt_{jkey}",
                            label_visibility="collapsed",
                        )

                    # Persist to session state
                    justifs[jkey] = {"type": choix, "comment": comment}


def _render_picklist(adv_bytes: bytes | None, employe: str, machines_faites: set) -> None:
    """
    Section E — Picklist vs chargement réel.
    Upload picklist(s) séparément ; le fichier ADV vient de la section principale.
    Les machines non faites sont exclues même si justifiées.
    """
    st.markdown(
        '<div style="color:#8FA8C8;font-size:0.85rem;margin-bottom:1rem;">'
        "Importez une ou plusieurs picklists. Le fichier ADV uploadé en début de page est utilisé "
        "pour identifier les machines chargées par cet employé (<b>Ressource</b>) et pour le chargement réel. "
        "Les salles non faites (absentes de l'ADV) sont automatiquement exclues du calcul."
        "</div>",
        unsafe_allow_html=True,
    )

    pick_files = st.file_uploader(
        "Picklist(s) CSV",
        type=["csv"],
        accept_multiple_files=True,
        key="re_pick_upload",
        label_visibility="collapsed",
    )

    if not pick_files:
        st.info("📋 Déposez une ou plusieurs picklists pour analyser la conformité de chargement.")
        return

    if adv_bytes is None:
        st.warning("⚠️ Uploadez d'abord le fichier ADV dans la section principale (en haut de page).")
        return

    col_btn, _ = st.columns([1, 5])
    with col_btn:
        if st.button("🔍 Analyser la picklist", type="primary",
                     use_container_width=True, key="re_pick_analyser"):
            try:
                # Machines chargées par cet employé dans l'ADV (Ressource = employe)
                charg_df = _parse_adv_for_picklist(adv_bytes, employe)
                machines_employe_adv = set(charg_df["Code Machine"].unique()) if not charg_df.empty else set()

                # N'utiliser que les machines à la fois dans l'ADV de l'employé
                # ET dans machines_faites (planning croisé) — exclut les non-faites
                machines_scope = machines_employe_adv & machines_faites if machines_faites else machines_employe_adv

                picks = []
                for pf in pick_files:
                    df_p = parse_picklist(pf.read())
                    picks.append(df_p)

                if not picks or all(p.empty for p in picks):
                    st.error("❌ Aucune ligne trouvée dans la/les picklist(s).")
                    return

                picklist_df = pd.concat(picks, ignore_index=True)

                # Filtrer la picklist sur les machines de l'employé (via ADV)
                # et exclure les machines non faites
                if machines_scope:
                    picklist_df = picklist_df[
                        picklist_df["Code Machine"].isin(machines_scope)
                    ].reset_index(drop=True)
                elif machines_employe_adv:
                    # Fallback : pas de planning chargé, utiliser uniquement l'ADV
                    picklist_df = picklist_df[
                        picklist_df["Code Machine"].isin(machines_employe_adv)
                    ].reset_index(drop=True)

                if picklist_df.empty:
                    st.warning(
                        "⚠️ Aucune machine de la picklist ne correspond aux chargements de "
                        f"{employe} dans l'ADV. Vérifiez que la colonne **Ressource** de l'ADV "
                        "contient bien le code réappro (ex : RIDF1)."
                    )
                    return

                result = _analyser_picklist(picklist_df, charg_df)
                st.session_state["re_pick_result"] = result

            except Exception as e:
                st.error(f"❌ Erreur analyse picklist : {e}")

    result = st.session_state.get("re_pick_result")
    if result is None:
        return

    # ── Produits en rupture ───────────────────────────────────────────────────
    tous_produits = sorted(result["Libellé produit"].unique())
    ruptures = st.multiselect(
        "🚫 Produits en rupture (exclure de l'analyse)",
        options=tous_produits,
        key="re_ruptures_picklist",
        placeholder="Sélectionner les produits à exclure...",
    )
    if ruptures:
        result = result[~result["Libellé produit"].isin(ruptures)].reset_index(drop=True)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    a_charger = result[result["Picklist"] > 0]
    total_g   = len(a_charger)
    conf_g    = int((a_charger["Statut"] == "Conforme").sum())
    pct_g     = round(conf_g / total_g * 100) if total_g else 0
    nc_g      = int((a_charger["Statut"] == "Non chargé").sum())
    insuf_g   = int((a_charger["Statut"] == "Insuffisant").sum())
    surplus_g = int((a_charger["Statut"] == "Surplus").sum())

    kpi_html = lambda cls, label, value, foot: (
        f'<div class="re-kpi {cls}">'
        f'<div class="kl">{label}</div>'
        f'<div class="kv">{value}</div>'
        f'<div class="kf">{foot}</div>'
        f'</div>'
    )

    conf_cls = "re-kpi-done" if pct_g >= 75 else ("re-kpi-joker" if pct_g >= 50 else "re-kpi-miss")
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(kpi_html(conf_cls, "🎯 Conformité", f"{pct_g} %", f"<b>{conf_g}</b> conformes sur <b>{total_g}</b>"), unsafe_allow_html=True)
    with k2:
        st.markdown(kpi_html("re-kpi-done", "✓ Conformes", conf_g, f"sur {total_g} lignes picklist"), unsafe_allow_html=True)
    with k3:
        foot3 = f'<b style="color:#ef5350;">{nc_g}</b> ligne(s)' if nc_g else "Aucun"
        st.markdown(kpi_html("re-kpi-miss" if nc_g else "", "✕ Non chargés", nc_g, foot3), unsafe_allow_html=True)
    with k4:
        foot4 = f'<b style="color:#FFA726;">{insuf_g}</b> ligne(s)' if insuf_g else "Aucun"
        st.markdown(kpi_html("re-kpi-joker" if insuf_g else "", "⚠ Insuffisants", insuf_g, foot4), unsafe_allow_html=True)
    with k5:
        foot5 = f'<b style="color:#8FA8C8;">{surplus_g}</b> ligne(s)' if surplus_g else "Aucun"
        st.markdown(kpi_html("" if not surplus_g else "re-kpi-joker", "↑ Surplus", surplus_g, foot5), unsafe_allow_html=True)

    # ── Résumé par machine ─────────────────────────────────────────────────────
    machines_list = (
        result.drop_duplicates("Code Machine")
        .sort_values("Nom client")["Code Machine"]
        .tolist()
    )

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    rows_recap = []
    for m in machines_list:
        df_m = result[result["Code Machine"] == m]
        nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
        s    = _stats_machine(df_m)
        rows_recap.append({
            "": "✅" if s["pct"] >= 75 else ("⚠️" if s["pct"] >= 50 else "🚫"),
            "Machine":      m,
            "Client":       nom,
            "Conformes":    f"{s['conformes']} / {s['total']}",
            "Non chargés":  s["non_charges"],
            "Insuffisants": s["insuffisants"],
            "Surplus":      s["surplus"],
            "Conformité":   f"{s['pct']} %",
            "_pct":         s["pct"],
        })

    df_recap = pd.DataFrame(rows_recap)
    pcts     = df_recap.pop("_pct").tolist()

    def _style_recap(row):
        idx   = df_recap.index.get_loc(row.name)
        pct_v = pcts[idx]
        bg    = _couleur_conformite(pct_v)
        color = "color:white;" if pct_v < 35 or pct_v > 80 else "color:#1a1a1a;"
        return [f"background-color:{bg};{color}"] * len(row)

    with st.expander(f"📊 Résumé par machine ({len(machines_list)} machines)", expanded=False):
        st.dataframe(
            df_recap.style.apply(_style_recap, axis=1),
            use_container_width=True,
            height=min(40 + 35 * len(df_recap), 500),
            hide_index=True,
        )


def _parse_pointage(content: bytes) -> pd.DataFrame:
    """
    Parse un fichier de pointage CSV (séparateur ;).
    Colonnes : ID établissement, ID utilisateur, Prénom, Nom,
               Début prévu, Fin prévue, Pause prévue, Type d'absence,
               Badge entrée, Badge sortie, Pauses, Durée pause, ...
    """
    df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.strip('"')

    def _clean(s):
        v = str(s).strip().strip('"')
        return None if v in ("", "nan") else v

    def _parse_dt(s):
        v = _clean(s)
        if not v:
            return pd.NaT
        for fmt in ["%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"]:
            try:
                return pd.Timestamp(datetime.datetime.strptime(v, fmt))
            except ValueError:
                pass
        return pd.NaT

    def _parse_min(s):
        v = _clean(s)
        if not v:
            return 0
        try:
            return int(float(v))
        except ValueError:
            return 0

    df["debut_prevu"]   = df["Début prévu"].apply(_parse_dt)
    df["fin_prevue"]    = df["Fin prévue"].apply(_parse_dt)
    df["badge_entree"]  = df["Badge entrée"].apply(_parse_dt)
    df["badge_sortie"]  = df["Badge sortie"].apply(_parse_dt)
    df["pause_prevue"]  = df["Pause prévue"].apply(_parse_min)
    df["duree_pause"]   = df["Durée pause"].apply(_parse_min)
    df["type_absence"]  = df["Type d'absence"].apply(_clean)
    df["prenom"]        = df["Prénom"].apply(lambda s: str(s).strip().strip('"'))
    df["nom"]           = df["Nom"].apply(lambda s: str(s).strip().strip('"'))
    df["nom_complet"]   = df["prenom"] + " " + df["nom"]
    df["date"]          = df["badge_entree"].dt.date.where(
        df["badge_entree"].notna(),
        df["debut_prevu"].dt.date,
    )
    return df


def _minutes_to_hhmm(minutes: float) -> str:
    if pd.isna(minutes) or minutes == 0:
        return "—"
    sign   = "-" if minutes < 0 else ""
    m      = int(abs(minutes))
    return f"{sign}{m // 60}h{m % 60:02d}"


def _render_pointage(prenom_hint: str) -> None:
    """Section F — Pointage : absences, pauses, temps de travail."""
    st.markdown(
        '<div style="color:#8FA8C8;font-size:0.85rem;margin-bottom:1rem;">'
        "Importez un ou plusieurs fichiers de pointage (export badgings). "
        "Sélectionnez ensuite l'employé dans la liste pour voir ses statistiques."
        "</div>",
        unsafe_allow_html=True,
    )

    ptg_files = st.file_uploader(
        "Fichier(s) pointage CSV",
        type=["csv"],
        accept_multiple_files=True,
        key="re_ptg_upload",
        label_visibility="collapsed",
    )

    if not ptg_files:
        st.info("⏱️ Déposez un ou plusieurs fichiers de pointage pour analyser les présences.")
        return

    # Parse and concat
    try:
        frames = [_parse_pointage(f.read()) for f in ptg_files]
        df_all = pd.concat(frames, ignore_index=True)
    except Exception as e:
        st.error(f"❌ Erreur lecture pointage : {e}")
        return

    # Employee selector — try to pre-match on prenom_hint
    noms = sorted(df_all["nom_complet"].unique())
    default_idx = 0
    if prenom_hint:
        hint_up = prenom_hint.upper()
        for i, n in enumerate(noms):
            if hint_up in n.upper():
                default_idx = i
                break

    sel_nom = st.selectbox(
        "Employé dans le fichier pointage",
        noms,
        index=default_idx,
        key="re_ptg_employe_sel",
    )

    df = df_all[df_all["nom_complet"] == sel_nom].copy().sort_values("date")

    if df.empty:
        st.warning("Aucune donnée pour cet employé.")
        return

    # ── Calculs par ligne ─────────────────────────────────────────────────────
    df["duree_travail_min"] = (
        (df["badge_sortie"] - df["badge_entree"]).dt.total_seconds() / 60 - df["duree_pause"]
    ).where(df["badge_entree"].notna() & df["badge_sortie"].notna(), other=pd.NA)

    df["duree_prevue_min"] = (
        (df["fin_prevue"] - df["debut_prevu"]).dt.total_seconds() / 60 - df["pause_prevue"]
    ).where(df["debut_prevu"].notna() & df["fin_prevue"].notna(), other=pd.NA)

    # Catégories
    absent_types  = df[df["type_absence"].notna()]
    presents      = df[df["type_absence"].isna()]
    sans_entree   = presents[presents["badge_entree"].isna()]
    sans_sortie   = presents[presents["badge_entree"].notna() & presents["badge_sortie"].isna()]
    depart_tot    = presents[
        presents["badge_sortie"].notna() & presents["fin_prevue"].notna()
        & ((presents["badge_sortie"] - presents["fin_prevue"]).dt.total_seconds() / 60 < -10)
    ]

    # Distinguish congés payés from other absences
    conges        = absent_types[absent_types["type_absence"].str.contains("congé", case=False, na=False)]
    autres_abs    = absent_types[~absent_types["type_absence"].str.contains("congé", case=False, na=False)]

    nb_jours      = len(df)
    nb_presents   = int(presents["badge_entree"].notna().sum())
    nb_conges     = len(conges)
    nb_autres_abs = len(autres_abs)
    nb_sans_badge = len(sans_entree)

    # Cache summary for hero section
    st.session_state["re_ptg_summary"] = {
        "nb_jours": nb_jours,
        "nb_presents": nb_presents,
        "nb_conges": nb_conges,
        "nb_autres_abs": nb_autres_abs,
        "nb_sans_badge": nb_sans_badge,
    }

    # ── KPI cards ─────────────────────────────────────────────────────────────
    kpi_html = lambda cls, label, value, foot: (
        f'<div class="re-kpi {cls}">'
        f'<div class="kl">{label}</div>'
        f'<div class="kv">{value}</div>'
        f'<div class="kf">{foot}</div>'
        f'</div>'
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(kpi_html("", "◈ Jours analysés", nb_jours, "Période couverte"), unsafe_allow_html=True)
    with k2:
        st.markdown(kpi_html("re-kpi-done", "✓ Présences", nb_presents, f"<b>{nb_presents}</b> avec badge entrée"), unsafe_allow_html=True)
    with k3:
        foot3 = f"<b>{nb_conges}</b> jour(s)" if nb_conges else "Aucun congé"
        st.markdown(kpi_html("", "✈ Congés payés", nb_conges, foot3), unsafe_allow_html=True)
    with k4:
        foot4 = f'<b style="color:#ef5350;">−{nb_autres_abs}</b> jour(s)' if nb_autres_abs else "Aucune absence"
        st.markdown(kpi_html("re-kpi-miss" if nb_autres_abs else "", "✕ Absences", nb_autres_abs, foot4), unsafe_allow_html=True)
    with k5:
        foot5 = f'<b style="color:#FFA726;">{nb_sans_badge}</b> jour(s) sans pointage' if nb_sans_badge else "Tous badgés"
        st.markdown(kpi_html("re-kpi-joker" if nb_sans_badge else "", "⚠ Sans badge", nb_sans_badge, foot5), unsafe_allow_html=True)

    # ── Absences par type ─────────────────────────────────────────────────────
    if not absent_types.empty:
        by_type = absent_types["type_absence"].value_counts()
        pills_abs = " ".join(
            _pill(f"{t} · {c}", "blue" if "congé" in t.lower() else ("red" if "injustifiée" in t.lower() else "orange"))
            for t, c in by_type.items()
        )
        st.markdown(
            f'<div class="re-pills" style="margin:12px 0 4px;">{pills_abs}</div>',
            unsafe_allow_html=True,
        )

    # ── Moyennes ──────────────────────────────────────────────────────────────
    pres_badged = presents[presents["badge_entree"].notna()]

    avg_travail    = pres_badged["duree_travail_min"].mean() if not pres_badged.empty else None
    avg_pause      = pres_badged["duree_pause"].mean()       if not pres_badged.empty else None

    def _avg_time(col):
        vals = pres_badged[col].dropna()
        if vals.empty:
            return None
        mins = vals.dt.hour * 60 + vals.dt.minute
        return mins.mean()

    avg_entree_min = _avg_time("badge_entree")
    avg_sortie_min = _avg_time("badge_sortie")

    def _min_to_time(m):
        if m is None or pd.isna(m):
            return "—"
        h, mn = divmod(int(round(m)), 60)
        return f"{h:02d}:{mn:02d}"

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(kpi_html("", "🕐 Arrivée moy.", _min_to_time(avg_entree_min), "Heure de badge entrée"), unsafe_allow_html=True)
    with s2:
        st.markdown(kpi_html("", "🕔 Départ moy.", _min_to_time(avg_sortie_min), "Heure de badge sortie"), unsafe_allow_html=True)
    with s3:
        st.markdown(kpi_html("", "⏱ Travail moyen", _minutes_to_hhmm(avg_travail) if avg_travail else "—", "Durée nette (hors pause)"), unsafe_allow_html=True)
    with s4:
        st.markdown(kpi_html("", "☕ Pause moyenne", _minutes_to_hhmm(avg_pause) if avg_pause else "—", "Durée de pause réelle"), unsafe_allow_html=True)

    # ── Anomalies ─────────────────────────────────────────────────────────────
    anomalies = []
    for _, row in sans_entree.iterrows():
        anomalies.append(("⚠️ Pas de badge entrée", row["date"], "orange"))
    for _, row in sans_sortie.iterrows():
        anomalies.append(("⚠️ Pas de badge sortie", row["date"], "orange"))
    for _, row in depart_tot.iterrows():
        delta = (row["badge_sortie"] - row["fin_prevue"]).total_seconds() / 60
        anomalies.append((f"🏃 Départ anticipé {_minutes_to_hhmm(delta)}", row["date"], "orange"))

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    if anomalies:
        with st.expander(f"🔴 {len(anomalies)} anomalie(s) détectée(s)", expanded=False):
            for label, d, _color in sorted(anomalies, key=lambda x: str(x[1])):
                date_str = d.strftime("%d/%m/%Y") if pd.notna(d) and d is not None else str(d)
                st.markdown(
                    f'<div class="re-inc-row miss" style="margin-bottom:6px;display:flex;gap:16px;align-items:center;">'
                    f'<span style="font-size:0.85rem;font-weight:600;">{label}</span>'
                    f'<span style="color:#8FA8C8;font-size:0.8rem;">{date_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.success("✅ Aucune anomalie détectée sur la période.")

    # ── Tableau détail ────────────────────────────────────────────────────────
    with st.expander("📋 Détail jour par jour", expanded=False):
        rows_detail = []
        for _, row in df.iterrows():
            d = row["date"]
            date_str = d.strftime("%d/%m/%Y") if pd.notna(d) and d is not None else str(d)

            if row["type_absence"]:
                statut = f"❌ {row['type_absence']}"
            elif pd.isna(row["badge_entree"]) or row["badge_entree"] is pd.NaT:
                statut = "⚠️ Non badgé"
            else:
                statut = "✅ Présent"

            entree_str  = row["badge_entree"].strftime("%H:%M") if pd.notna(row["badge_entree"]) else "—"
            sortie_str  = row["badge_sortie"].strftime("%H:%M") if pd.notna(row["badge_sortie"]) else "—"
            travail_str = _minutes_to_hhmm(row["duree_travail_min"]) if pd.notna(row["duree_travail_min"]) else "—"
            pause_str   = f"{int(row['duree_pause'])} min" if row["duree_pause"] > 0 else "—"

            rows_detail.append({
                "Date":    date_str,
                "Statut":  statut,
                "Entrée":  entree_str,
                "Sortie":  sortie_str,
                "Travail": travail_str,
                "Pause":   pause_str,
            })

        if rows_detail:
            df_detail = pd.DataFrame(rows_detail)

            def _color_detail(row):
                if "❌" in str(row["Statut"]):
                    return ["background-color:rgba(198,40,40,0.18);"] * len(row)
                if "⚠️" in str(row["Statut"]):
                    return ["background-color:rgba(232,146,42,0.18);"] * len(row)
                return ["background-color:rgba(46,125,50,0.10);"] * len(row)

            st.dataframe(
                df_detail.style.apply(_color_detail, axis=1),
                use_container_width=True,
                hide_index=True,
                height=min(40 + 35 * len(df_detail), 500),
            )


def _render_quartix(prenom_hint: str) -> None:
    """Section G — Quartix : trajets hors horaires + activité weekend."""
    from datetime import time as _dtime
    from page_quartix import COLS, _to_km, _clean_addr, _JOURS_FR, _MIN_TRIP_KM

    st.markdown(
        '<div style="color:#8FA8C8;font-size:0.85rem;margin-bottom:1rem;">'
        "Importez un rapport Quartix (Excel multi-feuilles, semaine complète). "
        "Sélectionnez ensuite la feuille correspondant au véhicule de cet employé."
        "</div>",
        unsafe_allow_html=True,
    )

    qtx_file = st.file_uploader(
        "Rapport Quartix Excel",
        type=["xls", "xlsx"],
        key="re_qtx_upload",
        label_visibility="collapsed",
    )

    if not qtx_file:
        st.info("🗺️ Déposez un fichier Excel Quartix pour analyser les trajets de la semaine.")
        return

    try:
        xls = pd.ExcelFile(qtx_file)
    except Exception as e:
        st.error(f"❌ Impossible de lire le fichier : {e}")
        return

    sheets = xls.sheet_names
    if len(sheets) <= 1:
        st.error("Fichier invalide : au moins 2 feuilles attendues (résumé + 1 par véhicule).")
        return

    vehicle_sheets = sheets[1:]

    # Pre-select sheet matching prenom_hint
    default_sheet_idx = 0
    if prenom_hint:
        hint_up = prenom_hint.upper()
        for i, s in enumerate(vehicle_sheets):
            if hint_up in s.upper():
                default_sheet_idx = i
                break

    sel_sheet = st.selectbox(
        "Feuille / véhicule",
        vehicle_sheets,
        index=default_sheet_idx,
        key="re_qtx_sheet_sel",
    )

    # Parse selected sheet
    try:
        df_raw = pd.read_excel(xls, sheet_name=sel_sheet, header=4, usecols="B:N")
        df_raw.columns = COLS
        df_raw["_dep"] = pd.to_datetime(
            df_raw["Départ"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True),
            errors="coerce",
        )
        df_raw["_arr"] = pd.to_datetime(
            df_raw["Arrivée"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True),
            errors="coerce",
        )
        df_raw = df_raw.dropna(subset=["_dep"]).sort_values("_dep").reset_index(drop=True)
        for col in ["Lieu de départ", "Lieu d'arrivée"]:
            df_raw[col] = df_raw[col].astype(str).map(_clean_addr)
    except Exception as e:
        st.error(f"❌ Erreur parsing feuille : {e}")
        return

    if df_raw.empty:
        st.warning("Aucune donnée valide dans cette feuille.")
        return

    date_min = df_raw["_dep"].dt.date.min()
    date_max = df_raw["_dep"].dt.date.max()

    # Cutoff time
    cutoff = st.time_input(
        "Heure limite de fin de tournée",
        value=_dtime(18, 0),
        key="re_qtx_cutoff",
        help="Tout trajet ≥ 1 km dont le départ ou l'arrivée dépasse cette heure sera signalé.",
    )

    # ── Analyse ───────────────────────────────────────────────────────────────
    total_trajets = len(df_raw)
    total_km      = df_raw["Distance totale"].apply(_to_km).sum()

    # Hors horaires (semaine, ≥ 1 km, départ ou arrivée après cutoff)
    weekday_df = df_raw[
        (df_raw["_dep"].dt.weekday < 5) &
        (df_raw["Distance totale"].apply(_to_km) >= _MIN_TRIP_KM)
    ].copy()
    mask_late = weekday_df["_dep"].dt.time > cutoff
    mask_arr  = weekday_df["_arr"].notna() & (weekday_df["_arr"].dt.time > cutoff)
    late_df   = weekday_df[mask_late | mask_arr]

    late_trips = [
        {
            "date":        row["_dep"].date(),
            "jour":        _JOURS_FR[row["_dep"].weekday()],
            "heure_dep":   row["_dep"].strftime("%H:%M"),
            "heure_arr":   row["_arr"].strftime("%H:%M") if pd.notna(row["_arr"]) else "—",
            "lieu_dep":    str(row["Lieu de départ"]),
            "lieu_arr":    str(row["Lieu d'arrivée"]),
            "distance_km": _to_km(row["Distance totale"]),
        }
        for _, row in late_df.iterrows()
    ]

    # Weekend (≥ 1 km)
    wkend_df = df_raw[
        (df_raw["_dep"].dt.weekday >= 5) &
        (df_raw["Distance totale"].apply(_to_km) >= _MIN_TRIP_KM)
    ]
    weekend_trips = [
        {
            "date":        row["_dep"].date(),
            "jour":        _JOURS_FR[row["_dep"].weekday()],
            "heure_dep":   row["_dep"].strftime("%H:%M"),
            "distance_km": _to_km(row["Distance totale"]),
        }
        for _, row in wkend_df.iterrows()
    ]

    nb_late   = len(late_trips)
    nb_wkend  = len(weekend_trips)
    nb_ok     = total_trajets - nb_late - nb_wkend

    # ── KPI cards ─────────────────────────────────────────────────────────────
    kpi_html = lambda cls, label, value, foot: (
        f'<div class="re-kpi {cls}">'
        f'<div class="kl">{label}</div>'
        f'<div class="kv">{value}</div>'
        f'<div class="kf">{foot}</div>'
        f'</div>'
    )

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(kpi_html("", "◈ Période", f"{date_min.strftime('%d/%m')} → {date_max.strftime('%d/%m/%Y')}", f"<b>{total_trajets}</b> trajets analysés"), unsafe_allow_html=True)
    with k2:
        st.markdown(kpi_html("", "📍 Distance totale", f"{total_km:.0f} km", "kilométrage semaine"), unsafe_allow_html=True)
    with k3:
        cls3 = "re-kpi-miss" if nb_late else "re-kpi-done"
        foot3 = f'<b style="color:#ef5350;">{nb_late}</b> trajet(s) après {cutoff.strftime("%H:%M")}' if nb_late else "Aucun trajet hors horaires"
        st.markdown(kpi_html(cls3, "⏰ Hors horaires", nb_late, foot3), unsafe_allow_html=True)
    with k4:
        cls4 = "re-kpi-miss" if nb_wkend else "re-kpi-done"
        foot4 = f'<b style="color:#ef5350;">{nb_wkend}</b> trajet(s) weekend' if nb_wkend else "Aucune activité weekend"
        st.markdown(kpi_html(cls4, "🗓️ Weekend", nb_wkend, foot4), unsafe_allow_html=True)

    # ── Trajets hors horaires ─────────────────────────────────────────────────
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    if not late_trips and not weekend_trips:
        st.success("✅ Aucune anomalie détectée sur la période — tous les trajets sont dans les horaires.")
        return

    if late_trips:
        with st.expander(f"⚠️ {nb_late} trajet(s) hors horaires (après {cutoff.strftime('%H:%M')})", expanded=True):
            for t in late_trips:
                date_str = t["date"].strftime("%d/%m/%Y")
                st.markdown(
                    f'<div class="re-inc-row miss" style="margin-bottom:8px;padding:10px 14px;'
                    f'display:flex;flex-wrap:wrap;gap:16px;align-items:center;">'
                    f'<span style="font-weight:700;font-size:0.85rem;min-width:80px;">{t["jour"]} {date_str}</span>'
                    f'<span style="color:#FFA726;font-weight:600;font-size:0.85rem;">{t["heure_dep"]} → {t["heure_arr"]}</span>'
                    f'<span style="color:#8FA8C8;font-size:0.82rem;flex:1;min-width:180px;">'
                    f'{t["lieu_dep"]} <span style="color:#4A6B8A;">→</span> {t["lieu_arr"]}</span>'
                    f'<span style="color:#E8EEF7;font-size:0.82rem;font-weight:600;white-space:nowrap;">{t["distance_km"]:.1f} km</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Activité weekend ──────────────────────────────────────────────────────
    if weekend_trips:
        with st.expander(f"🗓️ {nb_wkend} trajet(s) weekend", expanded=True):
            for t in weekend_trips:
                date_str = t["date"].strftime("%d/%m/%Y")
                st.markdown(
                    f'<div class="re-inc-row miss" style="margin-bottom:8px;padding:10px 14px;'
                    f'display:flex;flex-wrap:wrap;gap:16px;align-items:center;">'
                    f'<span style="font-weight:700;font-size:0.85rem;min-width:80px;">{t["jour"]} {date_str}</span>'
                    f'<span style="color:#ef5350;font-weight:600;font-size:0.85rem;">{t["heure_dep"]}</span>'
                    f'<span style="color:#E8EEF7;font-size:0.82rem;font-weight:600;white-space:nowrap;">{t["distance_km"]:.1f} km</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT — HTML + PDF
# ─────────────────────────────────────────────────────────────────────────────

_ALL_SECTIONS = ["chargement", "non_faites", "picklist", "pointage"]
_SECTION_LABELS = {
    "chargement": "Chargement hebdomadaire",
    "non_faites": "Salles non faites & justifications",
    "picklist":   "Conformité picklist",
    "pointage":   "Pointage",
}


def _export_data(employe, weekly, meta, pick_result, ptg_summary, justifications):
    """Pre-compute all export data shared between HTML and PDF builders."""
    prenom   = meta.get("prenom", employe)
    zone     = meta.get("zone", "")
    resp     = meta.get("responsable", "")
    iso_year, iso_week, _ = datetime.date.today().isocalendar()

    total_prevu = sum(len(d["salles_prevues"])   for d in weekly.values())
    total_fait  = sum(len(d["salles_faites"])     for d in weekly.values())
    total_nf    = sum(len(d["salles_non_faites"]) for d in weekly.values())
    nb_joker    = sum(
        sum(1 for s in d["salles_faites"] if s.get("is_joker"))
        for d in weekly.values()
    )
    taux = round((total_fait / total_prevu * 100) if total_prevu > 0 else 0.0, 1)

    emp_justifs = {k: v for k, v in justifications.items() if k.startswith(employe + "_")}
    nf_list = []
    for jour, data in weekly.items():
        for s in data["salles_non_faites"]:
            machine = s["machine"] if isinstance(s, dict) else s
            justif  = emp_justifs.get(f"{employe}_{jour}_{machine}", {})
            nf_list.append({
                "jour": jour, "machine": machine,
                "statut": justif.get("type", "Non justifié"),
                "motif":  justif.get("comment", ""),
            })

    pick_stats = None
    pick_machines = []
    if pick_result is not None and not pick_result.empty:
        a_ch = pick_result[pick_result["Picklist"] > 0]
        tot  = len(a_ch)
        pick_stats = {
            "pct":      round(int((a_ch["Statut"] == "Conforme").sum()) / tot * 100) if tot else 0,
            "conf":     int((a_ch["Statut"] == "Conforme").sum()),
            "total":    tot,
            "nc":       int((a_ch["Statut"] == "Non chargé").sum()),
            "insuf":    int((a_ch["Statut"] == "Insuffisant").sum()),
            "surplus":  int((a_ch["Statut"] == "Surplus").sum()),
        }
        for m in (pick_result.drop_duplicates("Code Machine")
                  .sort_values("Nom client")["Code Machine"].tolist()):
            df_m = pick_result[pick_result["Code Machine"] == m]
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            s    = _stats_machine(df_m)
            pick_machines.append({"code": m, "nom": nom, **s})

    return {
        "prenom": prenom, "zone": zone, "resp": resp,
        "semaine": f"S{iso_week} · {iso_year}", "gen_date": datetime.date.today().strftime("%d/%m/%Y"),
        "iso_week": iso_week, "iso_year": iso_year,
        "total_prevu": total_prevu, "total_fait": total_fait,
        "total_nf": total_nf, "nb_joker": nb_joker, "taux": taux,
        "weekly": weekly, "nf_list": nf_list,
        "pick_stats": pick_stats, "pick_machines": pick_machines,
        "ptg": ptg_summary,
    }


def _build_rapport_html(employe: str, d: dict, sections: set) -> str:
    taux_color = "#16a34a" if d["taux"] >= 90 else ("#d97706" if d["taux"] >= 75 else "#dc2626")
    meta_parts = []
    if d["zone"]: meta_parts.append(f"Zone {d['zone']}")
    if d["resp"]: meta_parts.append(f"Resp. {d['resp']}")
    meta_line = " · ".join(meta_parts)

    charg_html = ""
    if "chargement" in sections:
        jours_rows = ""
        for jour, data in d["weekly"].items():
            nf = len(data["salles_non_faites"])
            nc = "#dc2626" if nf > 0 else "#16a34a"
            jours_rows += (
                f"<tr><td><b>{jour}</b></td><td>{len(data['salles_prevues'])}</td>"
                f"<td style='color:#16a34a;font-weight:600;'>{len(data['salles_faites'])}</td>"
                f"<td style='color:{nc};font-weight:600;'>{nf}</td>"
                f"<td>{'✓' if data.get('tournee_decalee') else ''}</td></tr>"
            )
        charg_html = f"""
<div class="section">
  <h2>Performance hebdomadaire — Chargement</h2>
  <div class="kpi-row">
    <div class="kpi"><div class="kl">Taux</div><div class="kv" style="font-size:32px;color:{taux_color};">{d['taux']}%</div></div>
    <div class="kpi"><div class="kl">Planifiées</div><div class="kv">{d['total_prevu']}</div></div>
    <div class="kpi"><div class="kl">Faites</div><div class="kv" style="color:#16a34a;">{d['total_fait']}</div></div>
    <div class="kpi"><div class="kl">Jokers</div><div class="kv">{d['nb_joker']}</div></div>
    <div class="kpi"><div class="kl">Non faites</div><div class="kv" style="color:{'#dc2626' if d['total_nf'] else '#16a34a'};">{d['total_nf']}</div></div>
  </div>
  <table><thead><tr><th>Jour</th><th>Prévues</th><th>Faites</th><th>Non faites</th><th>Décalée</th></tr></thead>
  <tbody>{jours_rows}</tbody></table>
</div>"""

    nf_html = ""
    if "non_faites" in sections and d["nf_list"]:
        nf_rows = "".join(
            f"<tr><td>{r['jour']}</td><td>{r['machine']}</td>"
            f"<td style='color:{'#d97706' if r['statut']=='Justifié' else '#dc2626'};font-weight:600;'>{r['statut']}</td>"
            f"<td style='color:#555;'>{r['motif']}</td></tr>"
            for r in d["nf_list"]
        )
        nf_html = f"""
<div class="section">
  <h2>Salles non faites & justifications</h2>
  <table><thead><tr><th>Jour</th><th>Machine</th><th>Justification</th><th>Motif</th></tr></thead>
  <tbody>{nf_rows}</tbody></table>
</div>"""

    pick_html = ""
    if "picklist" in sections and d["pick_stats"]:
        ps = d["pick_stats"]
        pc = "#16a34a" if ps["pct"] >= 75 else ("#d97706" if ps["pct"] >= 50 else "#dc2626")
        mach_rows = "".join(
            f"<tr><td>{m['code']}</td><td>{m['nom']}</td>"
            f"<td style='color:{'#16a34a' if m['pct']>=75 else ('#d97706' if m['pct']>=50 else '#dc2626')};font-weight:700;'>{m['pct']}%</td>"
            f"<td>{m['conformes']}/{m['total']}</td><td>{m['non_charges']}</td><td>{m['insuffisants']}</td></tr>"
            for m in d["pick_machines"]
        )
        pick_html = f"""
<div class="section">
  <h2>Conformité picklist</h2>
  <div class="kpi-row">
    <div class="kpi"><div class="kl">Conformité</div><div class="kv" style="color:{pc};">{ps['pct']}%</div></div>
    <div class="kpi"><div class="kl">Conformes</div><div class="kv">{ps['conf']} / {ps['total']}</div></div>
    <div class="kpi"><div class="kl">Non chargés</div><div class="kv" style="color:{'#dc2626' if ps['nc'] else '#16a34a'};">{ps['nc']}</div></div>
    <div class="kpi"><div class="kl">Insuffisants</div><div class="kv" style="color:{'#d97706' if ps['insuf'] else '#16a34a'};">{ps['insuf']}</div></div>
    <div class="kpi"><div class="kl">Surplus</div><div class="kv">{ps['surplus']}</div></div>
  </div>
  <table><thead><tr><th>Machine</th><th>Client</th><th>Conformité</th><th>Conformes</th><th>Non chargés</th><th>Insuffisants</th></tr></thead>
  <tbody>{mach_rows}</tbody></table>
</div>"""

    ptg_html = ""
    if "pointage" in sections and d["ptg"]:
        p = d["ptg"]
        ptg_html = f"""
<div class="section">
  <h2>Pointage</h2>
  <div class="kpi-row">
    <div class="kpi"><div class="kl">Jours analysés</div><div class="kv">{p['nb_jours']}</div></div>
    <div class="kpi"><div class="kl">Présences</div><div class="kv" style="color:#16a34a;">{p['nb_presents']}</div></div>
    <div class="kpi"><div class="kl">Congés payés</div><div class="kv">{p['nb_conges']}</div></div>
    <div class="kpi"><div class="kl">Absences</div><div class="kv" style="color:{'#dc2626' if p['nb_autres_abs'] else '#16a34a'};">{p['nb_autres_abs']}</div></div>
    <div class="kpi"><div class="kl">Sans badge</div><div class="kv" style="color:{'#d97706' if p['nb_sans_badge'] else '#16a34a'};">{p['nb_sans_badge']}</div></div>
  </div>
</div>"""

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<title>Rapport {d['prenom']} ({employe}) — {d['semaine']}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#1a1a2e;background:#fff;padding:32px 36px}}
  h1{{font-size:24px;font-weight:900;color:#1B3D6F;margin-bottom:4px}}
  h2{{font-size:11px;font-weight:700;color:#1B3D6F;text-transform:uppercase;letter-spacing:.12em;border-bottom:2px solid #d0dff0;padding-bottom:5px;margin-bottom:14px}}
  .header{{margin-bottom:28px;padding-bottom:18px;border-bottom:3px solid #1B3D6F;display:flex;justify-content:space-between;align-items:flex-end}}
  .header-left .sub{{color:#5a7190;font-size:12px;margin-top:5px}}
  .header-right{{text-align:right;color:#8FA8C8;font-size:11px}}
  .chip{{display:inline-block;background:#dbeafe;color:#1B3D6F;font-weight:700;font-size:12px;border-radius:6px;padding:2px 9px;margin-left:8px;vertical-align:middle}}
  .section{{margin-bottom:28px;page-break-inside:avoid}}
  .kpi-row{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}}
  .kpi{{background:#f0f4fa;border-radius:10px;padding:10px 14px;flex:1;min-width:90px;border:1px solid #d0dff0}}
  .kl{{font-size:9px;font-weight:700;color:#5a7190;text-transform:uppercase;letter-spacing:.09em}}
  .kv{{font-size:22px;font-weight:900;color:#1B3D6F;margin-top:3px;line-height:1}}
  table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}}
  th{{background:#1B3D6F;color:#fff;padding:7px 10px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em}}
  td{{padding:6px 10px;border-bottom:1px solid #e8eef7}}
  tr:nth-child(even) td{{background:#f8fafc}}
  @media print{{body{{padding:12px 16px}}.section{{page-break-inside:avoid}}}}
</style></head><body>
<div class="header">
  <div class="header-left">
    <h1>{d['prenom']}<span class="chip">{employe}</span></h1>
    <div class="sub">{d['semaine']}{(" · " + meta_line) if meta_line else ""}</div>
  </div>
  <div class="header-right">Généré le {d['gen_date']}</div>
</div>
{charg_html}{nf_html}{pick_html}{ptg_html}
</body></html>"""


def _build_rapport_pdf(employe: str, d: dict, sections: set) -> bytes:
    import io as _io
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rl_colors

    W, H   = A4
    PAD    = 18 * mm
    CW     = W - 2 * PAD

    # Palette matching the page
    C_BG     = rl_colors.HexColor("#0F1923")
    C_CARD   = rl_colors.HexColor("#1A2535")
    C_BORDER = rl_colors.HexColor("#2A4A6B")
    C_HDR    = rl_colors.HexColor("#1B3D6F")
    C_TXT    = rl_colors.HexColor("#E8EEF7")
    C_MUTED  = rl_colors.HexColor("#8FA8C8")
    C_GREEN  = rl_colors.HexColor("#52b788")
    C_ORANGE = rl_colors.HexColor("#E8922A")
    C_RED    = rl_colors.HexColor("#ef5350")
    C_PURPLE = rl_colors.HexColor("#CE93D8")
    C_ACCENT = rl_colors.HexColor("#4A90D9")

    buf = _io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    y   = [H - PAD]  # mutable so closures can write it

    def _bg():
        c.setFillColor(C_BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)

    def _new_page():
        c.showPage()
        _bg()
        y[0] = H - PAD

    def _need(h):
        if y[0] - h < PAD + 8 * mm:
            _new_page()

    def _section_title(title):
        _need(14 * mm)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.4)
        c.line(PAD, y[0], W - PAD, y[0])
        y[0] -= 5 * mm
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(PAD, y[0], title.upper())
        y[0] -= 7 * mm

    def _kpi_row(kpis):
        n      = len(kpis)
        card_w = (CW - (n - 1) * 2.5 * mm) / n
        card_h = 17 * mm
        _need(card_h + 5 * mm)
        x = PAD
        for label, value, vc in kpis:
            c.setFillColor(C_CARD)
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.4)
            c.roundRect(x, y[0] - card_h, card_w, card_h, 2.5 * mm, fill=1, stroke=1)
            c.setFillColor(C_MUTED)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawCentredString(x + card_w / 2, y[0] - 5 * mm, label.upper()[:22])
            c.setFillColor(vc or C_TXT)
            c.setFont("Helvetica-Bold", 17)
            c.drawCentredString(x + card_w / 2, y[0] - 13 * mm, str(value))
            x += card_w + 2.5 * mm
        y[0] -= card_h + 4 * mm

    def _table(headers, rows, col_w=None):
        n = len(headers)
        if col_w is None:
            col_w = [CW / n] * n
        rh = 6.5 * mm
        hh = 7.5 * mm
        _need(hh + rh)
        # Header
        c.setFillColor(C_HDR)
        c.rect(PAD, y[0] - hh, CW, hh, fill=1, stroke=0)
        c.setFillColor(C_TXT)
        c.setFont("Helvetica-Bold", 7.5)
        cx = PAD
        for i, h in enumerate(headers):
            c.drawString(cx + 2 * mm, y[0] - 5 * mm, str(h))
            cx += col_w[i]
        y[0] -= hh
        # Rows
        for ri, row in enumerate(rows):
            _need(rh)
            bg = rl_colors.HexColor("#1A2535") if ri % 2 == 0 else rl_colors.HexColor("#162030")
            c.setFillColor(bg)
            c.rect(PAD, y[0] - rh, CW, rh, fill=1, stroke=0)
            cx = PAD
            c.setFont("Helvetica", 7.5)
            for i, cell in enumerate(row):
                text  = cell[0] if isinstance(cell, tuple) else str(cell)
                color = cell[1] if isinstance(cell, tuple) else C_TXT
                c.setFillColor(color)
                c.drawString(cx + 2 * mm, y[0] - 4.5 * mm, str(text)[:35])
                cx += col_w[i]
            y[0] -= rh
        y[0] -= 4 * mm

    # ── Draw page background + header band ────────────────────────────────────
    _bg()
    hdr_h = 30 * mm
    c.setFillColor(C_HDR)
    c.rect(0, H - hdr_h, W, hdr_h, fill=1, stroke=0)
    # Subtle accent stripe
    c.setFillColor(rl_colors.HexColor("#2A5A9F"))
    c.rect(0, H - hdr_h, 4 * mm, hdr_h, fill=1, stroke=0)

    c.setFillColor(C_TXT)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(PAD, H - 13 * mm, d["prenom"])
    c.setFont("Helvetica", 20)
    c.drawString(PAD + c.stringWidth(d["prenom"], "Helvetica-Bold", 20) + 4 * mm,
                 H - 13 * mm, f"  ·  {employe}")

    sub_parts = [d["semaine"]]
    if d["zone"]:  sub_parts.append(f"Zone {d['zone']}")
    if d["resp"]:  sub_parts.append(f"Resp. {d['resp']}")
    sub_parts.append(f"Généré le {d['gen_date']}")
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(PAD, H - 22 * mm, "  ·  ".join(sub_parts))

    y[0] = H - hdr_h - 10 * mm

    # ── Chargement ────────────────────────────────────────────────────────────
    if "chargement" in sections:
        taux = d["taux"]
        tc   = C_GREEN if taux >= 90 else (C_ORANGE if taux >= 75 else C_RED)
        _section_title("Performance hebdomadaire — Chargement")
        _kpi_row([
            ("Taux de complétion", f"{taux}%", tc),
            ("Planifiées",  d["total_prevu"],              C_TXT),
            ("Faites",      d["total_fait"],               C_GREEN),
            ("Jokers",      d["nb_joker"],                 C_PURPLE),
            ("Non faites",  d["total_nf"], C_RED if d["total_nf"] else C_GREEN),
        ])
        jours_rows = []
        for jour, data in d["weekly"].items():
            nf = len(data["salles_non_faites"])
            jours_rows.append([
                jour,
                str(len(data["salles_prevues"])),
                (str(len(data["salles_faites"])), C_GREEN),
                (str(nf), C_RED if nf else C_GREEN),
                "✓" if data.get("tournee_decalee") else "",
            ])
        _table(
            ["Jour", "Prévues", "Faites", "Non faites", "Décalée"],
            jours_rows,
            [38*mm, 32*mm, 32*mm, 38*mm, 32*mm],
        )

    # ── Non-faites ────────────────────────────────────────────────────────────
    if "non_faites" in sections and d["nf_list"]:
        _section_title("Salles non faites & justifications")
        _table(
            ["Jour", "Machine", "Justification", "Motif"],
            [
                [r["jour"], r["machine"],
                 (r["statut"], C_ORANGE if r["statut"] == "Justifié" else C_RED),
                 r["motif"][:40]]
                for r in d["nf_list"]
            ],
            [32*mm, 38*mm, 42*mm, 60*mm],
        )

    # ── Picklist ──────────────────────────────────────────────────────────────
    if "picklist" in sections and d["pick_stats"]:
        ps = d["pick_stats"]
        pc = C_GREEN if ps["pct"] >= 75 else (C_ORANGE if ps["pct"] >= 50 else C_RED)
        _section_title("Conformité picklist")
        _kpi_row([
            ("Conformité",   f"{ps['pct']}%",          pc),
            ("Conformes",    f"{ps['conf']}/{ps['total']}", C_GREEN),
            ("Non chargés",  ps["nc"],   C_RED    if ps["nc"]    else C_GREEN),
            ("Insuffisants", ps["insuf"], C_ORANGE if ps["insuf"] else C_GREEN),
            ("Surplus",      ps["surplus"],             C_TXT),
        ])
        _table(
            ["Machine", "Client", "Conformité", "Conformes", "Non chargés", "Insuffisants"],
            [
                [m["code"], m["nom"][:28],
                 (f"{m['pct']}%", C_GREEN if m["pct"] >= 75 else (C_ORANGE if m["pct"] >= 50 else C_RED)),
                 f"{m['conformes']}/{m['total']}", str(m["non_charges"]), str(m["insuffisants"])]
                for m in d["pick_machines"]
            ],
            [28*mm, 52*mm, 24*mm, 24*mm, 24*mm, 20*mm],
        )

    # ── Pointage ──────────────────────────────────────────────────────────────
    if "pointage" in sections and d["ptg"]:
        p = d["ptg"]
        _section_title("Pointage")
        _kpi_row([
            ("Jours analysés", p["nb_jours"],       C_TXT),
            ("Présences",      p["nb_presents"],     C_GREEN),
            ("Congés payés",   p["nb_conges"],       C_ACCENT if p["nb_conges"] else C_TXT),
            ("Absences",       p["nb_autres_abs"],   C_RED    if p["nb_autres_abs"]  else C_GREEN),
            ("Sans badge",     p["nb_sans_badge"],   C_ORANGE if p["nb_sans_badge"]  else C_GREEN),
        ])

    c.save()
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render() -> None:
    _inject_css()

    st.markdown('<div class="main-title">👤 Rapport Employé</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Vue complète par réapprovisionneur — performance, chargements, picklist.</div>',
        unsafe_allow_html=True,
    )

    # ── Chargement des plannings ───────────────────────────────────────────────
    plannings, planning_errors = _get_plannings()
    if not plannings:
        st.error("❌ Aucun planning trouvé en base. Importez les plannings depuis la page Tournées.")
        if planning_errors:
            for k, v in planning_errors.items():
                st.caption(f"{k}: {v}")
        return

    # ── Sélecteur employé ──────────────────────────────────────────────────────
    col_emp, col_adv = st.columns([1, 2])
    with col_emp:
        employe_options = sorted(plannings.keys())
        employe_sel     = st.selectbox(
            "Réapprovisionneur",
            employe_options,
            key="re_employe_sel",
        )
    with col_adv:
        adv_file = st.file_uploader(
            "📂 Fichier ADV / chargement (CSV)",
            type=["csv"],
            key="re_adv_upload",
            label_visibility="visible",
        )
        if adv_file is not None:
            st.session_state["re_adv_bytes"] = adv_file.getvalue()

    adv_bytes = st.session_state.get("re_adv_bytes")

    # Si pas de fichier, on s'arrête ici après les placeholders vides
    if adv_bytes is None:
        st.info("📂 Déposez le fichier ADV pour lancer l'analyse.")
        return

    # ── Lancer l'analyse ───────────────────────────────────────────────────────
    run_key = f"re_weekly_{employe_sel}"
    if st.button("🚀 Analyser", type="primary", key="re_btn_analyser"):
        with st.spinner("Analyse en cours..."):
            try:
                chargement = _parse_adv_as_chargement_dict(adv_bytes)
                weekly     = _croiser_semaine(plannings, chargement, employe_sel)
                st.session_state[run_key]         = weekly
                st.session_state["re_pick_result"] = None  # invalidate picklist on re-run
                st.toast(f"✅ Analyse terminée pour {employe_sel}")
            except Exception as e:
                st.error(f"❌ Erreur parsing ADV : {e}")
                return
        st.rerun()

    weekly = st.session_state.get(run_key)
    if weekly is None:
        st.caption("Cliquez sur **Analyser** pour générer le rapport.")
        return

    # Metadata (Quartix vehicles) — optional
    try:
        vehicles = load_all_quartix_vehicles()
        meta = next(
            (v for v in vehicles.values() if v.get("employe") == employe_sel),
            {}
        )
    except Exception:
        meta = {}

    # ── Section A — Hero ───────────────────────────────────────────────────────
    _section_label("Identité & taux de complétion")
    _render_hero(employe_sel, weekly, meta)

    # ── Section B — KPIs ───────────────────────────────────────────────────────
    _section_label("Performance hebdomadaire")
    _render_kpis(weekly)

    # ── Section C — Détail par jour ────────────────────────────────────────────
    _section_label("Détail par jour")
    _render_day_strip(weekly)

    # ── Section D — Chargements (statuts + justifications) ────────────────────
    _section_label("Chargements — statuts & justifications")
    _render_chargements_detail(weekly, employe_sel)

    # Export justifications
    justifs = st.session_state.get("re_justifications", {})
    emp_justifs = {k: v for k, v in justifs.items() if k.startswith(employe_sel + "_")}
    if emp_justifs:
        rows_j = []
        for key, val in emp_justifs.items():
            parts = key.split("_", 2)
            if len(parts) == 3:
                _, jour_j, machine_j = parts
                rows_j.append({
                    "Réappro":  employe_sel,
                    "Jour":     jour_j,
                    "Machine":  machine_j,
                    "Statut":   val.get("type", ""),
                    "Motif":    val.get("comment", ""),
                })
        if rows_j:
            with st.expander("📋 Récap justifications", expanded=False):
                df_j = pd.DataFrame(rows_j)

                def _color_j(row):
                    if row["Statut"] == "Justifié":
                        return ["background-color:rgba(232,146,42,0.18);font-weight:600"] * len(row)
                    return ["background-color:rgba(198,40,40,0.18);font-weight:600"] * len(row)

                st.dataframe(
                    df_j.style.apply(_color_j, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )

    # ── Section E — Picklist ───────────────────────────────────────────────────
    _section_label("Conformité picklist")
    machines_faites: set = set()
    for jour_data in weekly.values():
        for s in jour_data["salles_faites"]:
            machines_faites.add(s["machine"])

    _render_picklist(adv_bytes, employe_sel, machines_faites)

    # ── Section F — Pointage ───────────────────────────────────────────────────
    _section_label("Pointage")
    prenom_hint = meta.get("prenom", employe_sel)
    _render_pointage(prenom_hint)

    # ── Section G — Quartix ────────────────────────────────────────────────────
    _section_label("Véhicule & tournée — Quartix")
    _render_quartix(prenom_hint)

    # ── Export PDF ─────────────────────────────────────────────────────────────
    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
    st.divider()
    st.markdown(
        '<div style="color:#8FA8C8;font-size:0.8rem;margin-bottom:8px;">'
        "📄 Le fichier HTML s'ouvre dans le navigateur — faites <b>Ctrl+P → Enregistrer en PDF</b> "
        "pour obtenir le PDF. Toutes les sections sont développées, aucun bouton n'est inclus."
        "</div>",
        unsafe_allow_html=True,
    )
    html_bytes = _build_rapport_html(
        employe      = employe_sel,
        weekly       = weekly,
        meta         = meta,
        pick_result  = st.session_state.get("re_pick_result"),
        ptg_summary  = st.session_state.get("re_ptg_summary"),
        justifications = st.session_state.get("re_justifications", {}),
    ).encode("utf-8")

    iso_year, iso_week, _ = datetime.date.today().isocalendar()
    st.download_button(
        label            = f"📄 Exporter le rapport — {employe_sel} S{iso_week}",
        data             = html_bytes,
        file_name        = f"rapport_{employe_sel}_S{iso_week}_{iso_year}.html",
        mime             = "text/html",
        type             = "primary",
        use_container_width = True,
        key              = "re_export_pdf",
    )
