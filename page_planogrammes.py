"""
Page Planogrammes — interface Streamlit complète.
Données sauvegardées dans MongoDB (collections planogrammes + produits_lib).
"""

import streamlit as st
import pandas as pd
import datetime
import io
import re
from pathlib import Path

from planogrammes_storage import (
    load_planogrammes, save_planogramme, delete_planogramme, duplicate_planogramme,
    load_produits, save_produit, delete_produit,
)

# ── Palettes couleurs disponibles pour les slots ────────
SLOT_COLORS = {
    "Aucune":   "",
    "Bleu":     "#1a2f47",
    "Vert":     "#12302a",
    "Ambre":    "#2e2a14",
    "Corail":   "#2e1a1a",
    "Violet":   "#1f1a3a",
    "Sarcelle": "#12302a",
    "Rose":     "#2a1a2a",
    "Gris":     "#2a2a2a",
}

SLOT_COLORS_DISPLAY = {
    "":         "#2e3450",
    "#1a2f47":  "#1a2f47",
    "#12302a":  "#12302a",
    "#2e2a14":  "#2e2a14",
    "#2e1a1a":  "#2e1a1a",
    "#1f1a3a":  "#1f1a3a",
    "#2a1a2a":  "#2a1a2a",
    "#2a2a2a":  "#2a2a2a",
}


# ════════════════════════════════════════════════════════
# HELPERS SESSION STATE
# ════════════════════════════════════════════════════════

def _init_state():
    defaults = {
        "pg_current_id":    None,   # _id du planogramme en cours d'édition
        "pg_current":       None,   # dict planogramme en mémoire
        "pg_view":          "list", # "list" | "editor" | "library"
        "pg_sel_slot":      None,   # "r-c" du slot sélectionné
        "pg_dirty":         False,  # modifications non sauvegardées
        "pg_search_lib":    "",
        "pg_planogrammes":  None,   # cache liste
        "pg_produits":      None,   # cache bibliothèque
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reload_planogrammes():
    st.session_state.pg_planogrammes = load_planogrammes()


def _reload_produits():
    st.session_state.pg_produits = load_produits()


def _get_planogrammes():
    if st.session_state.pg_planogrammes is None:
        _reload_planogrammes()
    return st.session_state.pg_planogrammes or []


def _get_produits():
    if st.session_state.pg_produits is None:
        _reload_produits()
    return st.session_state.pg_produits or []


def _new_slots(rows, cols):
    return {f"{r}-{c}": {"product": "", "price": "", "qty": "", "color": ""}
            for r in range(rows) for c in range(cols)}


def _set_current(plano: dict):
    st.session_state.pg_current    = plano
    st.session_state.pg_current_id = plano.get("_id")
    st.session_state.pg_sel_slot   = None
    st.session_state.pg_dirty      = False
    st.session_state.pg_view       = "editor"


def _mark_dirty():
    st.session_state.pg_dirty = True


# ════════════════════════════════════════════════════════
# COMPOSANTS UI RÉUTILISABLES
# ════════════════════════════════════════════════════════

def _slot_color_badge(color: str) -> str:
    bg = color if color else "#2e3450"
    return f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{bg};border:1px solid rgba(255,255,255,0.2);vertical-align:middle;margin-right:4px"></span>'


def _render_grid_preview(plano: dict, editable: bool = True):
    """Affiche la grille du distributeur sous forme de tableau HTML cliquable."""
    rows    = plano.get("rows", 1)
    cols    = plano.get("cols", 1)
    slots   = plano.get("slots", {})
    labels  = plano.get("row_labels", [f"R{i+1}" for i in range(rows)])
    sel     = st.session_state.pg_sel_slot

    # Calcul largeur colonne
    col_w = max(60, min(110, int(900 / (cols + 1))))

    html = f"""
    <style>
    .vm-grid {{ border-collapse: collapse; width: 100%; font-family: -apple-system, sans-serif; }}
    .vm-grid th {{
        background: #1e2130; color: #9ba3b8; font-size: 10px; font-weight: 600;
        padding: 4px 2px; text-align: center; border: 1px solid rgba(255,255,255,0.06);
        width: {col_w}px; min-width: 44px;
    }}
    .vm-grid td.label {{
        background: #262b3d; color: #9ba3b8; font-size: 10px; font-weight: 700;
        padding: 5px 6px; text-align: center; border: 1px solid rgba(255,255,255,0.08);
        white-space: nowrap; min-width: 28px;
    }}
    .vm-grid td.slot {{
        border: 1px solid rgba(255,255,255,0.08); padding: 4px 3px; text-align: center;
        vertical-align: top; font-size: 10px; min-width: 44px; width: {col_w}px;
        cursor: pointer; transition: outline 0.1s;
    }}
    .vm-grid td.slot:hover {{ outline: 1.5px solid #4d9de0; outline-offset: -1px; }}
    .vm-grid td.slot.selected {{ outline: 2px solid #4d9de0; outline-offset: -1px; }}
    .slot-product {{ font-weight: 600; color: #e8eaf0; line-height: 1.3; word-break: break-word; }}
    .slot-price {{ color: #4d9de0; margin-top: 2px; }}
    .slot-qty {{ color: #9ba3b8; }}
    .slot-empty {{ color: #3d4460; font-size: 12px; }}
    </style>
    <table class="vm-grid">
    <thead><tr><th style="width:28px"></th>"""

    for c in range(cols):
        html += f"<th>C{c+1}</th>"
    html += "</tr></thead><tbody>"

    for r in range(rows):
        lbl = labels[r] if r < len(labels) else f"R{r+1}"
        html += f'<tr><td class="label">{lbl}</td>'
        for c in range(cols):
            key = f"{r}-{c}"
            s   = slots.get(key, {})
            bg  = s.get("color", "") or "#1e2130"
            is_sel = (sel == key)
            cls = "slot selected" if is_sel else "slot"
            html += f'<td class="{cls}" style="background:{bg}">'
            if s.get("product"):
                html += f'<div class="slot-product">{s["product"]}</div>'
                if s.get("price"):
                    try:
                        html += f'<div class="slot-price">{float(s["price"]):.2f} €</div>'
                    except Exception:
                        html += f'<div class="slot-price">{s["price"]} €</div>'
                if s.get("qty"):
                    html += f'<div class="slot-qty">×{s["qty"]}</div>'
            else:
                html += '<div class="slot-empty">—</div>'
            html += "</td>"
        html += "</tr>"

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# VUE : LISTE DES PLANOGRAMMES
# ════════════════════════════════════════════════════════

def _view_list():
    planogrammes = _get_planogrammes()

    # ── Header ──
    hc1, hc2 = st.columns([5, 3])
    with hc1:
        st.markdown("### 📋 Tous les planogrammes")
    with hc2:
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("+ Nouveau", use_container_width=True, type="primary"):
                st.session_state.pg_view = "new"
                st.rerun()
        with bc2:
            if st.button("📦 Bibliothèque", use_container_width=True):
                st.session_state.pg_view = "library"
                st.rerun()

    if not planogrammes:
        st.info("Aucun planogramme. Créez-en un avec le bouton **+ Nouveau**.")
        return

    # ── Grille de cartes ──
    cols_per_row = 3
    for i in range(0, len(planogrammes), cols_per_row):
        row_planos = planogrammes[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, p in enumerate(row_planos):
            with cols[j]:
                filled = sum(1 for s in p.get("slots", {}).values() if s.get("product"))
                total  = p.get("rows", 0) * p.get("cols", 0)
                upd    = p.get("updated_at", "—")

                with st.container(border=True):
                    st.markdown(f"**{p['nom']}**")
                    st.caption(
                        f"{'Double' if p.get('type')=='double' else 'Simple'} · "
                        f"{p.get('rows',0)} × {p.get('cols',0)} · "
                        f"{filled}/{total} remplis"
                    )
                    st.caption(f"Modifié le {upd}")

                    bc1, bc2, bc3 = st.columns(3)
                    with bc1:
                        if st.button("✏️ Éditer", key=f"edit_{p['_id']}", use_container_width=True):
                            _set_current(p)
                            st.rerun()
                    with bc2:
                        if st.button("⎘ Copier", key=f"dup_{p['_id']}", use_container_width=True):
                            new_id = duplicate_planogramme(p["_id"])
                            if new_id:
                                _reload_planogrammes()
                                st.toast(f"Copie créée.")
                                st.rerun()
                    with bc3:
                        if st.button("🗑️", key=f"del_{p['_id']}", use_container_width=True):
                            st.session_state[f"confirm_del_{p['_id']}"] = True
                            st.rerun()

                    # Confirmation suppression
                    if st.session_state.get(f"confirm_del_{p['_id']}"):
                        st.warning(f"Supprimer **{p['nom']}** ?")
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            if st.button("Oui, supprimer", key=f"yes_{p['_id']}", type="primary"):
                                delete_planogramme(p["_id"])
                                st.session_state.pop(f"confirm_del_{p['_id']}", None)
                                _reload_planogrammes()
                                st.rerun()
                        with cc2:
                            if st.button("Annuler", key=f"no_{p['_id']}"):
                                st.session_state.pop(f"confirm_del_{p['_id']}", None)
                                st.rerun()


# ════════════════════════════════════════════════════════
# VUE : NOUVEAU PLANOGRAMME
# ════════════════════════════════════════════════════════

def _view_new():
    st.markdown("### ➕ Nouveau planogramme")

    with st.form("form_new_plano"):
        nom  = st.text_input("Nom", placeholder="Double BF Octobre 2025")
        c1, c2, c3 = st.columns(3)
        with c1:
            type_dist = st.selectbox("Type", ["simple", "double"])
        with c2:
            rows = st.number_input("Rangées", min_value=1, max_value=20, value=5)
        with c3:
            cols = st.number_input("Colonnes", min_value=1, max_value=24, value=7)

        submitted = st.form_submit_button("Créer", type="primary", use_container_width=True)

    if submitted:
        if not nom.strip():
            st.error("Le nom est obligatoire.")
            return
        plano = {
            "nom":        nom.strip(),
            "type":       type_dist,
            "rows":       int(rows),
            "cols":       int(cols),
            "row_labels": [f"R{i+1}" for i in range(int(rows))],
            "slots":      _new_slots(int(rows), int(cols)),
        }
        new_id = save_planogramme(plano)
        plano["_id"] = new_id
        _reload_planogrammes()
        _set_current(plano)
        st.rerun()

    if st.button("← Retour"):
        st.session_state.pg_view = "list"
        st.rerun()


# ════════════════════════════════════════════════════════
# VUE : ÉDITEUR
# ════════════════════════════════════════════════════════

def _view_editor():
    p = st.session_state.pg_current
    if not p:
        st.session_state.pg_view = "list"
        st.rerun()
        return

    # ── Barre d'outils éditeur ──
    tc1, tc2, tc3, tc4, tc5, tc6, tc7 = st.columns([3, 1, 1, 1, 1, 1, 1])
    with tc1:
        st.markdown(f"### ✏️ {p['nom']}")
    with tc2:
        if st.button("← Liste", use_container_width=True):
            st.session_state.pg_view = "list"
            st.session_state.pg_sel_slot = None
            st.rerun()
    with tc3:
        dirty_label = "💾 Sauvegarder*" if st.session_state.pg_dirty else "💾 Sauvegarder"
        if st.button(dirty_label, use_container_width=True, type="primary"):
            save_planogramme(p)
            _reload_planogrammes()
            st.session_state.pg_dirty = False
            st.toast("✅ Sauvegardé dans MongoDB.")
    with tc4:
        if st.button("⎘ Dupliquer", use_container_width=True):
            new_id = duplicate_planogramme(p["_id"])
            if new_id:
                _reload_planogrammes()
                st.toast("Copie créée.")
    with tc5:
        if st.button("↓ Excel", use_container_width=True):
            _do_export_excel(p)
    with tc6:
        if st.button("↓ PDF", use_container_width=True):
            _do_export_pdf(p)
    with tc7:
        if st.button("🗑️ Suppr.", use_container_width=True):
            st.session_state["confirm_del_editor"] = True

    if st.session_state.get("confirm_del_editor"):
        st.warning(f"Supprimer **{p['nom']}** définitivement ?")
        cc1, cc2, _ = st.columns([1, 1, 4])
        with cc1:
            if st.button("Oui, supprimer", type="primary"):
                delete_planogramme(p["_id"])
                st.session_state.pop("confirm_del_editor", None)
                st.session_state.pg_current    = None
                st.session_state.pg_current_id = None
                st.session_state.pg_view       = "list"
                _reload_planogrammes()
                st.rerun()
        with cc2:
            if st.button("Annuler"):
                st.session_state.pop("confirm_del_editor", None)
                st.rerun()

    st.divider()

    # ── Deux colonnes : paramètres | grille ──
    left, right = st.columns([1, 3])

    with left:
        # Paramètres généraux
        with st.expander("⚙️ Paramètres", expanded=True):
            new_nom = st.text_input("Nom", value=p["nom"], key="ed_nom")
            if new_nom != p["nom"]:
                p["nom"] = new_nom; _mark_dirty()

            new_type = st.selectbox("Type", ["simple", "double"],
                                    index=0 if p.get("type") == "simple" else 1, key="ed_type")
            if new_type != p.get("type"):
                p["type"] = new_type; _mark_dirty()

            new_cols = st.number_input("Colonnes", 1, 24, value=p["cols"], key="ed_cols")
            if int(new_cols) != p["cols"]:
                old_cols = p["cols"]
                p["cols"] = int(new_cols)
                # Ajouter ou retirer les colonnes dans les slots
                for r in range(p["rows"]):
                    for c in range(int(new_cols)):
                        k = f"{r}-{c}"
                        if k not in p["slots"]:
                            p["slots"][k] = {"product": "", "price": "", "qty": "", "color": ""}
                _mark_dirty()

        # Rangées
        with st.expander("📏 Rangées", expanded=True):
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("+ Rangée", use_container_width=True):
                    r = p["rows"]
                    p["rows"] += 1
                    p["row_labels"].append(f"R{p['rows']}")
                    for c in range(p["cols"]):
                        p["slots"][f"{r}-{c}"] = {"product": "", "price": "", "qty": "", "color": ""}
                    _mark_dirty(); st.rerun()
            with bc2:
                if st.button("− Rangée", use_container_width=True, disabled=(p["rows"] <= 1)):
                    r = p["rows"] - 1
                    for c in range(p["cols"]):
                        p["slots"].pop(f"{r}-{c}", None)
                    p["rows"] -= 1
                    if p["row_labels"]:
                        p["row_labels"].pop()
                    _mark_dirty(); st.rerun()

            labels = p.get("row_labels", [])
            for i in range(p["rows"]):
                cur = labels[i] if i < len(labels) else f"R{i+1}"
                new_lbl = st.text_input(f"R{i+1}", value=cur, key=f"lbl_{i}", label_visibility="collapsed")
                if new_lbl != cur:
                    while len(p["row_labels"]) <= i:
                        p["row_labels"].append(f"R{len(p['row_labels'])+1}")
                    p["row_labels"][i] = new_lbl
                    _mark_dirty()

        # Import CSV rapide
        with st.expander("↑ Import CSV"):
            st.caption("Format : une ligne = une rangée. Cellules séparées par `;` : `Produit;prix;qté`")
            csv_file = st.file_uploader("Fichier CSV", type=["csv"], key="ed_csv_import", label_visibility="collapsed")
            if csv_file and st.button("Importer", key="do_csv_import"):
                _import_csv_to_plano(p, csv_file.read())
                _mark_dirty(); st.rerun()

    with right:
        st.caption(
            f"**{p['nom']}** · {'Double' if p.get('type')=='double' else 'Simple'} · "
            f"{p['rows']} rangées × {p['cols']} colonnes · "
            f"Cliquez sur un emplacement pour le modifier"
        )

        # Grille visuelle
        _render_grid_preview(p)

        # Sélecteur de slot via selectbox (alternative cliquable)
        st.markdown("**Sélectionner un emplacement :**")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sel_row = st.selectbox(
                "Rangée", range(p["rows"]),
                format_func=lambda i: p["row_labels"][i] if i < len(p["row_labels"]) else f"R{i+1}",
                key="sel_row"
            )
        with sc2:
            sel_col = st.selectbox("Colonne", range(p["cols"]),
                                   format_func=lambda c: f"C{c+1}", key="sel_col")
        with sc3:
            if st.button("✏️ Modifier cet emplacement", use_container_width=True):
                st.session_state.pg_sel_slot = f"{sel_row}-{sel_col}"
                st.rerun()

        # Éditeur de slot
        sel = st.session_state.pg_sel_slot
        if sel and sel in p["slots"]:
            s = p["slots"][sel]
            r_i, c_i = sel.split("-")
            row_lbl = p["row_labels"][int(r_i)] if int(r_i) < len(p["row_labels"]) else f"R{int(r_i)+1}"

            st.divider()
            st.markdown(f"**Emplacement : {row_lbl} · C{int(c_i)+1}**")

            # Bouton depuis bibliothèque
            produits = _get_produits()
            if produits:
                prod_names = ["— Choisir dans la bibliothèque —"] + [pr["nom"] for pr in produits]
                choice = st.selectbox("Bibliothèque de produits", prod_names, key="lib_pick")
                if choice != "— Choisir dans la bibliothèque —":
                    prod_obj = next((pr for pr in produits if pr["nom"] == choice), None)
                    if prod_obj and st.button("Appliquer ce produit", type="primary"):
                        p["slots"][sel] = {
                            "product": prod_obj["nom"],
                            "price":   prod_obj.get("prix", ""),
                            "qty":     prod_obj.get("quantite", ""),
                            "color":   prod_obj.get("couleur", ""),
                        }
                        _mark_dirty(); st.rerun()

            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                new_prod = st.text_input("Produit", value=s.get("product", ""), key=f"s_prod_{sel}")
            with ec2:
                new_price = st.text_input("Prix (€)", value=s.get("price", ""), key=f"s_price_{sel}")
            with ec3:
                new_qty = st.text_input("Quantité ×", value=s.get("qty", ""), key=f"s_qty_{sel}")

            color_names = list(SLOT_COLORS.keys())
            cur_color = s.get("color", "")
            cur_color_name = next((n for n, v in SLOT_COLORS.items() if v == cur_color), "Aucune")
            new_color_name = st.selectbox("Couleur de fond", color_names,
                                          index=color_names.index(cur_color_name), key=f"s_color_{sel}")
            new_color = SLOT_COLORS[new_color_name]

            uc1, uc2 = st.columns([2, 1])
            with uc1:
                if st.button("✅ Appliquer les modifications", use_container_width=True, type="primary"):
                    p["slots"][sel] = {
                        "product": new_prod,
                        "price":   new_price,
                        "qty":     new_qty,
                        "color":   new_color,
                    }
                    _mark_dirty(); st.rerun()
            with uc2:
                if st.button("🗑️ Vider", use_container_width=True):
                    p["slots"][sel] = {"product": "", "price": "", "qty": "", "color": ""}
                    _mark_dirty(); st.rerun()


# ════════════════════════════════════════════════════════
# VUE : BIBLIOTHÈQUE PRODUITS
# ════════════════════════════════════════════════════════

def _view_library():
    produits = _get_produits()

    hc1, hc2, hc3 = st.columns([4, 2, 2])
    with hc1:
        st.markdown("### 📦 Bibliothèque de produits")
    with hc2:
        if st.button("+ Ajouter un produit", use_container_width=True, type="primary"):
            st.session_state.pg_view = "new_product"
            st.rerun()
    with hc3:
        if st.button("← Retour aux planogrammes", use_container_width=True):
            st.session_state.pg_view = "list"
            st.rerun()

    search = st.text_input("🔍 Rechercher", placeholder="Nom ou catégorie…", key="lib_search")

    filtered = [p for p in produits
                if not search or search.lower() in p["nom"].lower()
                or search.lower() in p.get("categorie", "").lower()]

    if not filtered:
        st.info("Aucun produit." + (" Aucun résultat pour cette recherche." if search else " Ajoutez-en un !"))
        return

    cols_per_row = 4
    for i in range(0, len(filtered), cols_per_row):
        batch = filtered[i:i + cols_per_row]
        cols  = st.columns(cols_per_row)
        for j, pr in enumerate(batch):
            with cols[j]:
                with st.container(border=True):
                    color_dot = _slot_color_badge(pr.get("couleur", ""))
                    st.markdown(
                        f'{color_dot}<strong>{pr["nom"]}</strong>',
                        unsafe_allow_html=True
                    )
                    info = []
                    if pr.get("prix"):     info.append(f"{float(pr['prix']):.2f} €")
                    if pr.get("quantite"): info.append(f"×{pr['quantite']}")
                    if pr.get("categorie"): info.append(pr["categorie"])
                    st.caption(" · ".join(info) if info else "—")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("✏️", key=f"editpr_{pr['_id']}", use_container_width=True):
                            st.session_state["edit_product_id"] = pr["_id"]
                            st.session_state.pg_view = "new_product"
                            st.rerun()
                    with bc2:
                        if st.button("🗑️", key=f"delpr_{pr['_id']}", use_container_width=True):
                            delete_produit(pr["_id"])
                            _reload_produits()
                            st.rerun()


# ════════════════════════════════════════════════════════
# VUE : FORMULAIRE PRODUIT (création / édition)
# ════════════════════════════════════════════════════════

def _view_new_product():
    edit_id  = st.session_state.get("edit_product_id")
    produits = _get_produits()
    existing = next((p for p in produits if p["_id"] == edit_id), None) if edit_id else None

    title = "✏️ Modifier le produit" if existing else "➕ Ajouter un produit"
    st.markdown(f"### {title}")

    with st.form("form_product"):
        nom  = st.text_input("Nom du produit *", value=existing["nom"] if existing else "")
        c1, c2 = st.columns(2)
        with c1:
            prix = st.text_input("Prix (€)", value=existing.get("prix", "") if existing else "")
        with c2:
            qte  = st.text_input("Quantité ×", value=existing.get("quantite", "") if existing else "")
        cat  = st.text_input("Catégorie", value=existing.get("categorie", "") if existing else "",
                             placeholder="Boissons, Barres, Accessoires…")
        color_names = list(SLOT_COLORS.keys())
        cur_color = existing.get("couleur", "") if existing else ""
        cur_color_name = next((n for n, v in SLOT_COLORS.items() if v == cur_color), "Aucune")
        col_choice = st.selectbox("Couleur", color_names, index=color_names.index(cur_color_name))

        submitted = st.form_submit_button("Enregistrer", type="primary", use_container_width=True)

    if submitted:
        if not nom.strip():
            st.error("Le nom est obligatoire.")
            return
        produit = {
            "nom":       nom.strip(),
            "prix":      prix.strip(),
            "quantite":  qte.strip(),
            "categorie": cat.strip(),
            "couleur":   SLOT_COLORS[col_choice],
        }
        if existing:
            produit["_id"] = existing["_id"]
        save_produit(produit)
        st.session_state.pop("edit_product_id", None)
        _reload_produits()
        st.toast("✅ Produit enregistré.")
        st.session_state.pg_view = "library"
        st.rerun()

    if st.button("← Annuler"):
        st.session_state.pop("edit_product_id", None)
        st.session_state.pg_view = "library"
        st.rerun()


# ════════════════════════════════════════════════════════
# IMPORT CSV
# ════════════════════════════════════════════════════════

def _import_csv_to_plano(p: dict, raw: bytes):
    try:
        text  = raw.decode("utf-8-sig").strip()
        lines = text.split("\n")
        rows  = len(lines)
        cols  = max(len(l.split(";")) for l in lines)
        p["rows"]       = rows
        p["cols"]       = cols
        p["row_labels"] = [f"R{i+1}" for i in range(rows)]
        p["slots"]      = {}
        for r, line in enumerate(lines):
            cells = line.split(";")
            for c in range(cols):
                cell = cells[c].strip() if c < len(cells) else ""
                price_m = re.search(r"(\d+[.,]\d{2})\s*€?", cell)
                qty_m   = re.search(r"[xX×]\s*(\d+)", cell)
                price   = price_m.group(1).replace(",", ".") if price_m else ""
                qty     = qty_m.group(1) if qty_m else ""
                product = re.sub(r"\d+[.,]\d{2}\s*€?", "", cell)
                product = re.sub(r"[xX×]\s*\d+", "", product).strip()
                p["slots"][f"{r}-{c}"] = {"product": product, "price": price, "qty": qty, "color": ""}
        st.toast(f"CSV importé : {rows} rangées × {cols} colonnes.")
    except Exception as e:
        st.error(f"Erreur import CSV : {e}")


# ════════════════════════════════════════════════════════
# EXPORTS
# ════════════════════════════════════════════════════════

def _do_export_excel(p: dict):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = p["nom"][:31]

        # En-tête
        header = ["Rangée"] + [f"C{c+1}" for c in range(p["cols"])]
        ws.append(header)
        for cell in ws[1]:
            cell.font      = Font(bold=True, color="FFFFFF")
            cell.fill      = PatternFill("solid", fgColor="1F4E79")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for r in range(p["rows"]):
            lbl = p["row_labels"][r] if r < len(p["row_labels"]) else f"R{r+1}"
            row_data = [lbl]
            for c in range(p["cols"]):
                s = p["slots"].get(f"{r}-{c}", {})
                if s.get("product"):
                    cell_val = s["product"]
                    if s.get("qty"):   cell_val += f" ×{s['qty']}"
                    if s.get("price"):
                        try: cell_val += f" {float(s['price']):.2f}€"
                        except: cell_val += f" {s['price']}€"
                    row_data.append(cell_val)
                else:
                    row_data.append("")
            ws.append(row_data)

        # Style corps
        for row in ws.iter_rows(min_row=2):
            for i, cell in enumerate(row):
                cell.border    = border
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                if i == 0:
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill("solid", fgColor="E8EAF0")

        # Largeurs colonnes
        ws.column_dimensions["A"].width = 10
        for c in range(1, p["cols"] + 1):
            ws.column_dimensions[get_column_letter(c + 1)].width = 18

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        safe_name = re.sub(r"[^\w\s-]", "_", p["nom"])
        st.download_button(
            label="⬇️ Télécharger Excel",
            data=buf.getvalue(),
            file_name=f"{safe_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.error(f"Erreur export Excel : {e}")


def _do_export_pdf(p: dict):
    """Export PDF via HTML imprimable (fallback sans dépendance externe)."""
    col_w = max(55, int(660 / p["cols"]))
    rows_html = ""
    for r in range(p["rows"]):
        lbl = p["row_labels"][r] if r < len(p["row_labels"]) else f"R{r+1}"
        rows_html += f'<tr><td class="lbl">{lbl}</td>'
        for c in range(p["cols"]):
            s  = p["slots"].get(f"{r}-{c}", {})
            bg = s.get("color", "") or "#ffffff"
            rows_html += f'<td style="background:{bg};width:{col_w}px">'
            if s.get("product"):
                rows_html += f'<div class="pname">{s["product"]}</div>'
                if s.get("price"):
                    try:    rows_html += f'<div class="pprice">{float(s["price"]):.2f} €</div>'
                    except: rows_html += f'<div class="pprice">{s["price"]} €</div>'
                if s.get("qty"):
                    rows_html += f'<div class="pqty">×{s["qty"]}</div>'
            else:
                rows_html += '<div class="empty">—</div>'
            rows_html += "</td>"
        rows_html += "</tr>"

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{p["nom"]}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; }}
  h1 {{ font-size: 16px; color: #1F4E79; margin-bottom: 4px; }}
  .sub {{ font-size: 11px; color: #666; margin-bottom: 14px; }}
  table {{ border-collapse: collapse; }}
  td {{ border: 1px solid #ddd; padding: 4px 3px; text-align: center; vertical-align: top; font-size: 10px; min-width: {col_w}px; }}
  td.lbl {{ background: #f0f0ee; font-weight: bold; font-size: 11px; white-space: nowrap; width: 30px; }}
  .pname {{ font-weight: bold; line-height: 1.3; color: #1a1a18; }}
  .pprice {{ color: #185FA5; margin-top: 2px; }}
  .pqty {{ color: #888; }}
  .empty {{ color: #ccc; }}
  button {{ padding: 8px 18px; background: #1F4E79; color: white; border: none; border-radius: 6px; cursor: pointer; margin-bottom: 14px; font-size: 13px; }}
  @media print {{ button {{ display: none; }} }}
</style></head>
<body>
<h1>{p["nom"]}</h1>
<div class="sub">{'Double' if p.get('type')=='double' else 'Simple'} — {p['rows']} rangées × {p['cols']} colonnes — Exporté le {datetime.date.today().strftime('%d/%m/%Y')}</div>
<button onclick="window.print()">🖨️ Imprimer / Enregistrer en PDF</button>
<table>{rows_html}</table>
</body></html>"""

    safe_name = re.sub(r"[^\w\s-]", "_", p["nom"])
    st.download_button(
        label="⬇️ Télécharger PDF (impression)",
        data=html.encode("utf-8"),
        file_name=f"{safe_name}.html",
        mime="text/html",
    )
    st.caption("Ouvrez le fichier HTML téléchargé → Ctrl+P → 'Enregistrer en PDF'.")


# ════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ════════════════════════════════════════════════════════

def render():
    _init_state()

    view = st.session_state.pg_view

    if view == "list":
        _view_list()
    elif view == "new":
        _view_new()
    elif view == "editor":
        _view_editor()
    elif view == "library":
        _view_library()
    elif view == "new_product":
        _view_new_product()
    else:
        st.session_state.pg_view = "list"
        st.rerun()
