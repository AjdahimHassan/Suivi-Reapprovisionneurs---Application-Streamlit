"""
Application Streamlit - Outil Réappro
  ├── 📦 Suivi Réapprovisionneurs
  └── 🗂️  Planogrammes
"""

import streamlit as st
import pandas as pd
import datetime

from planning_parser import get_today_day_str, JOURS
import page_machines
import page_no_audit
import page_cr
import page_planogrammes
import page_inventaires
import page_commandes
import page_indefinis
import page_quartix
import page_picklist
from mongo_storage import load_plannings_from_mongo
from chargement_parser import parse_chargement_csv, croiser_planning_chargement
from excel_export import generer_excel

# ────────────────────────────────────────────────────────
# CONFIG PAGE
# ────────────────────────────────────────────────────────
DARK_CSS = """<style>
/* ── DARK MODE OVERRIDE ── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: #0F1923 !important;
    color: #E8EEF7 !important;
}
[data-testid="block-container"],
.block-container {
    background-color: #0F1923 !important;
}
[data-testid="stSidebar"] {
    background-color: #1A2535 !important;
}
.main-title { color: #7BC4E8 !important; }
.subtitle   { color: #8FA8C8 !important; }
p, span, label, div { color: #E8EEF7 !important; }
.stButton > button[kind="secondary"] {
    color: #7BC4E8 !important;
    border-color: #2A4A6B !important;
    background-color: transparent !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #1E2E42 !important;
    border-color: #E8922A !important;
    color: #E8922A !important;
}
[data-testid="metric-container"] {
    background-color: #1A2535 !important;
    border: 1px solid #2A4A6B !important;
    border-radius: 0.5rem !important;
    padding: 0.5rem !important;
}
[data-testid="metric-container"] label,
[data-testid="metric-container"] [data-testid="stMetricLabel"] { color: #7BC4E8 !important; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #E8EEF7 !important; }
[data-testid="metric-container"] [data-testid="stMetricDelta"] { color: #8FA8C8 !important; }
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
[data-testid="stSelectbox"] > div > div,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {
    background-color: #1A2535 !important;
    color: #E8EEF7 !important;
    border-color: #2A4A6B !important;
}
[data-baseweb="popover"],
[data-baseweb="menu"],
ul[data-baseweb="menu"] {
    background-color: #1E2E42 !important;
    border-color: #2A4A6B !important;
}
[data-baseweb="menu"] li { color: #E8EEF7 !important; }
[data-baseweb="menu"] li:hover { background-color: #2A4A6B !important; }
[data-testid="stDataFrame"] > div,
.stDataFrame { background-color: #1A2535 !important; }
[data-testid="stDataFrame"] > div > div { border-color: #2A4A6B !important; }
[data-testid="stExpander"] {
    border-color: #2A4A6B !important;
    background-color: #1A2535 !important;
}
[data-testid="stExpander"] summary {
    color: #E8EEF7 !important;
    background-color: #1A2535 !important;
}
[data-testid="stExpander"] summary:hover { background-color: #1E2E42 !important; }
[data-testid="stTabs"] [role="tablist"] { border-bottom-color: #2A4A6B !important; }
[data-testid="stTabs"] button[role="tab"] { color: #8FA8C8 !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #E8922A !important;
    border-bottom-color: #E8922A !important;
}
hr { border-color: rgba(123,196,232,0.2) !important; }
[data-testid="stFileUploader"],
[data-testid="stFileUploaderDropzone"],
section[data-testid="stFileUploaderDropzone"] {
    background-color: #1A2535 !important;
    border-color: #2A4A6B !important;
}
[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] p {
    color: #E8EEF7 !important;
}
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzone"] button span {
    background-color: #1E2E42 !important;
    color: #7BC4E8 !important;
    border-color: #2A4A6B !important;
}
[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover span {
    background-color: #2A4A6B !important;
    border-color: #7BC4E8 !important;
    color: #E8EEF7 !important;
}
[data-testid="stAlert"] {
    background-color: #1E2E42 !important;
    border-color: #2A4A6B !important;
}
.stCaption, [data-testid="stCaptionContainer"] { color: #8FA8C8 !important; }
.stDownloadButton > button {
    background-color: #1E2E42 !important;
    color: #7BC4E8 !important;
    border-color: #2A4A6B !important;
}
.stDownloadButton > button:hover {
    background-color: #2A4A6B !important;
    border-color: #7BC4E8 !important;
}
[data-baseweb="tag"] { background-color: #2A4A6B !important; }
[data-baseweb="tag"] span { color: #E8EEF7 !important; }
</style>"""

st.set_page_config(
    page_title="Distriprot Data",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
/* Cache le bouton toggle de la sidebar */
[data-testid="collapsedControl"] { display: none !important; }

/* Titres */
.main-title { font-size:2rem; font-weight:800; color:#1B3D6F; margin-bottom:0.2rem; }
.subtitle   { font-size:1rem; color:#555; margin-bottom:1.5rem; }

/* Bouton primaire (nav actif + actions principales) */
.stButton > button[kind="primary"] {
    background-color: #E8922A !important;
    border-color: #E8922A !important;
    color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #D07A1A !important;
    border-color: #D07A1A !important;
    color: #ffffff !important;
}

/* Bouton secondaire (nav inactif) */
.stButton > button[kind="secondary"] {
    color: #1B3D6F !important;
    border-color: #7BC4E8 !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #EEF5FC !important;
    border-color: #E8922A !important;
    color: #E8922A !important;
}

/* Métriques */
[data-testid="metric-container"] label { color: #1B3D6F; }

/* Empêche le retour à la ligne dans les boutons nav */
.stButton > button { white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis; }

/* Remonte le contenu au maximum en haut */
[data-testid="stHeader"] { display: none !important; }
.block-container { padding-top: 0.5rem !important; }

/* Bouton toggle thème */
.theme-toggle-btn > button {
    background-color: transparent !important;
    border: 1px solid #7BC4E8 !important;
    color: #1B3D6F !important;
    font-size: 1.1rem !important;
    height: 2rem !important;
    width: 2.6rem !important;
    min-height: 0 !important;
    border-radius: 50% !important;
    padding: 0.2rem 0.5rem !important;
}
.theme-toggle-btn > button:hover {
    background-color: #EEF5FC !important;
    border-color: #E8922A !important;
}
</style>
""", unsafe_allow_html=True)

if st.session_state.get("dark_mode", False):
    st.markdown(DARK_CSS, unsafe_allow_html=True)

# ────────────────────────────────────────────────────────
# SESSION STATE
# ────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "machines"
if "results" not in st.session_state:
    st.session_state.results = {}
if "jour_analyse" not in st.session_state:
    st.session_state.jour_analyse = get_today_day_str()
if "chargement_bytes" not in st.session_state:
    st.session_state["chargement_bytes"] = None
if "excel_bytes" not in st.session_state:
    st.session_state["excel_bytes"] = None
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# ────────────────────────────────────────────────────────
# NAVIGATION — barre en haut de la page principale
# ────────────────────────────────────────────────────────
import os as _os

# Logo — ligne dédiée, aligné à gauche
_logo_path = "assets/logo.png"
_logo_col, _theme_col, _ = st.columns([1, 1, 8])
with _logo_col:
    if _os.path.exists(_logo_path):
        st.image(_logo_path, width=90)
    else:
        st.markdown('<div style="font-size:1.3rem;font-weight:900;color:#1B3D6F;">DP</div>', unsafe_allow_html=True)
with _theme_col:
    _icon = "🌙" if not st.session_state.dark_mode else "☀️"
    st.markdown('<div class="theme-toggle-btn">', unsafe_allow_html=True)
    if st.button(_icon, key="toggle_dark_mode", help="Basculer mode sombre/clair"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# Barre de navigation — 10 boutons
nav_c1, nav_c2, nav_c3, nav_c4, nav_c5, nav_c6, nav_c7, nav_c8, nav_c9, nav_c10 = st.columns(10)
with nav_c1:
    if st.button(
        "🖥️ Machines",
        key="nav_machines",
        use_container_width=True,
        type="primary" if st.session_state.page == "machines" else "secondary",
    ):
        st.session_state.page = "machines"
        st.rerun()
with nav_c2:
    if st.button(
        "📦 Tournées",
        key="nav_suivi",
        use_container_width=True,
        type="primary" if st.session_state.page == "suivi" else "secondary",
    ):
        st.session_state.page = "suivi"
        st.rerun()
with nav_c3:
    if st.button(
        "📉 No Audit",
        key="nav_no_audit",
        use_container_width=True,
        type="primary" if st.session_state.page == "no_audit" else "secondary",
    ):
        st.session_state.page = "no_audit"
        st.rerun()
with nav_c4:
    if st.button(
        "🗂️ Planogrammes",
        key="nav_plano",
        use_container_width=True,
        type="primary" if st.session_state.page == "planogrammes" else "secondary",
    ):
        st.session_state.page = "planogrammes"
        st.rerun()
with nav_c5:
    if st.button(
        "📊 Inventaires",
        key="nav_inv",
        use_container_width=True,
        type="primary" if st.session_state.page == "inventaires" else "secondary",
    ):
        st.session_state.page = "inventaires"
        st.rerun()
with nav_c6:
    if st.button(
        "🛒 Commandes",
        key="nav_cmd",
        use_container_width=True,
        type="primary" if st.session_state.page == "commandes" else "secondary",
    ):
        st.session_state.page = "commandes"
        st.rerun()
with nav_c7:
    if st.button(
        "❓ Indéfinis",
        key="nav_indef",
        use_container_width=True,
        type="primary" if st.session_state.page == "indefinis" else "secondary",
    ):
        st.session_state.page = "indefinis"
        st.rerun()
with nav_c8:
    if st.button(
        "📝 CR",
        key="nav_cr",
        use_container_width=True,
        type="primary" if st.session_state.page == "cr" else "secondary",
    ):
        st.session_state.page = "cr"
        st.rerun()
with nav_c9:
    if st.button(
        "🗺️ Quartix",
        key="nav_quartix",
        use_container_width=True,
        type="primary" if st.session_state.page == "quartix" else "secondary",
    ):
        st.session_state.page = "quartix"
        st.rerun()
with nav_c10:
    if st.button(
        "📋 Picklist",
        key="nav_picklist",
        use_container_width=True,
        type="primary" if st.session_state.page == "picklist" else "secondary",
    ):
        st.session_state.page = "picklist"
        st.rerun()

st.divider()



# ════════════════════════════════════════════════════════
# PAGE : MACHINES
# ════════════════════════════════════════════════════════
if st.session_state.page == "machines":

    st.markdown('<div class="main-title">🖥️ Parc Machines</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Visualisez et gérez le parc de distributeurs automatiques en exploitation.</div>',
        unsafe_allow_html=True,
    )

    page_machines.render()


# ════════════════════════════════════════════════════════
# PAGE : NO AUDIT / SANS VENTES
# ════════════════════════════════════════════════════════
elif st.session_state.page == "no_audit":

    st.markdown('<div class="main-title">📉 No Audit / Sans Ventes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Identifiez les salles absentes de la télémétrie ou sans ventes sur une période donnée.</div>',
        unsafe_allow_html=True,
    )

    page_no_audit.render()


# ════════════════════════════════════════════════════════
# PAGE : SUIVI RÉAPPROVISIONNEURS
# ════════════════════════════════════════════════════════
elif st.session_state.page == "suivi":

    @st.cache_data(show_spinner=False, ttl=300)
    def _get_plannings():
        return load_plannings_from_mongo()

    plannings, planning_errors = _get_plannings()

    st.markdown('<div class="main-title">📦 Suivi des Réapprovisionneurs</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="subtitle">Analyse du <b>{st.session_state.jour_analyse}</b> — '
        f'{datetime.date.today().strftime("%d/%m/%Y")}</div>',
        unsafe_allow_html=True,
    )

    if not plannings:
        st.stop()

    # ── Plannings chargés ─────────────────────────────────
    st.divider()
    st.markdown("### ⚙️ Plannings chargés")
    if plannings:
        st.success(f"✅ {len(plannings)} plannings chargés — `MongoDB Atlas`")
        with st.expander("Voir les réappros"):
            for emp, p in sorted(plannings.items()):
                total = sum(len(v) for v in p.values())
                st.caption(f"**{emp}** — {total} salles/semaine")
    else:
        st.error("❌ Aucun planning trouvé.")
        for k, v in planning_errors.items():
            st.error(f"{k}: {v}")
    if planning_errors and plannings:
        with st.expander(f"⚠️ {len(planning_errors)} erreur(s)"):
            for k, v in planning_errors.items():
                st.warning(f"{k}: {v}")

    with st.expander("📥 Mettre à jour les plannings"):
        st.caption("Déposer un ou plusieurs fichiers CSV nommés `{réappro}.csv`")
        plan_files = st.file_uploader(
            "Fichiers planning CSV",
            type=["csv"],
            accept_multiple_files=True,
            key="planning_uploader",
            label_visibility="collapsed",
        )
        if plan_files:
            col_imp, _ = st.columns([1, 4])
            with col_imp:
                if st.button("📥 Importer", use_container_width=True, key="btn_import_planning"):
                    from mongo_storage import upsert_planning
                    from planning_parser import parse_planning_file
                    ok, errs = [], []
                    for f in plan_files:
                        employe = f.name.removesuffix(".csv").strip()
                        try:
                            planning, semaine = parse_planning_file(f.read(), employe)
                            upsert_planning(employe, planning, semaine)
                            total = sum(len(v) for v in planning.values())
                            ok.append(f"{employe} ({total} salles, {semaine})")
                        except Exception as e:
                            errs.append(f"{employe} : {e}")
                    for msg in ok:
                        st.success(f"✅ {msg}")
                    for msg in errs:
                        st.error(f"❌ {msg}")
                    if ok:
                        _get_plannings.clear()
                        st.rerun()

    with st.expander("🗑️ Supprimer un planning"):
        if plannings:
            to_delete = st.multiselect(
                "Réappros à supprimer",
                options=sorted(plannings.keys()),
                key="planning_to_delete",
                label_visibility="collapsed",
            )
            if to_delete:
                col_del, _ = st.columns([1, 4])
                with col_del:
                    if st.button(
                        f"🗑️ Supprimer ({len(to_delete)})",
                        use_container_width=True,
                        key="btn_delete_planning",
                        type="primary",
                    ):
                        from mongo_storage import delete_planning
                        errs = []
                        for emp in to_delete:
                            try:
                                delete_planning(emp)
                            except Exception as e:
                                errs.append(f"{emp} : {e}")
                        deleted = [e for e in to_delete if e not in [err.split(" :")[0] for err in errs]]
                        for emp in deleted:
                            st.success(f"✅ {emp} supprimé")
                        for msg in errs:
                            st.error(f"❌ {msg}")
                        _get_plannings.clear()
                        st.rerun()
        else:
            st.caption("_Aucun planning à supprimer._")

    # ── Jour d'analyse ────────────────────────────────────
    st.divider()
    jour_col, _ = st.columns([1, 4])
    with jour_col:
        st.markdown("**Jour d'analyse**")
        jour_selectionne = st.selectbox(
            "Jour", JOURS,
            index=JOURS.index(st.session_state.jour_analyse)
            if st.session_state.jour_analyse in JOURS else 0,
            label_visibility="collapsed",
            key="jour_analyse_select",
        )
        if jour_selectionne != st.session_state.jour_analyse:
            st.session_state.jour_analyse = jour_selectionne
            st.rerun()

    # ── Export Excel ───────────────────────────────────────
    st.divider()
    st.markdown("### 📥 Export Excel")
    if st.session_state.results:
        col_exp, _ = st.columns([1, 4])
        with col_exp:
            if st.button("📊 Générer le fichier Excel", use_container_width=True):
                with st.spinner("Génération..."):
                    try:
                        st.session_state["excel_bytes"] = generer_excel(
                            st.session_state.results, st.session_state.jour_analyse
                        )
                        st.session_state["excel_jour"] = st.session_state.jour_analyse
                    except Exception as e:
                        st.error(f"Erreur Excel : {e}")

            # Bouton download TOUJOURS rendu en dehors du if st.button(...)
            if st.session_state.get("excel_bytes"):
                date_str = datetime.date.today().strftime("%Y%m%d")
                jour_export = st.session_state.get("excel_jour", st.session_state.jour_analyse)
                st.download_button(
                    label="⬇️ Télécharger Excel",
                    data=st.session_state["excel_bytes"],
                    file_name=f"suivi_reappro_{date_str}_{jour_export}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
    else:
        st.caption("_Analysez un fichier de chargement pour générer l'export._")

    st.divider()
    st.markdown("### 📂 Déposer le fichier de chargement machine du jour")
    uploaded = st.file_uploader(
        "Fichier export chargement (CSV)", type=["csv"],
        key="chargement_uploader", label_visibility="collapsed",
    )

    # Persister les bytes en session pour survivre aux st.rerun()
    if uploaded is not None:
        st.session_state["chargement_bytes"] = uploaded.getvalue()

    has_file = st.session_state.get("chargement_bytes") is not None

    col_btn, _ = st.columns([1, 5])
    with col_btn:
        lancer = st.button(
            "🚀 Lancer l'analyse", type="primary",
            use_container_width=True, disabled=(not has_file),
        )

    if lancer and has_file:
        with st.spinner("Analyse en cours..."):
            try:
                chargement = parse_chargement_csv(st.session_state["chargement_bytes"])
                results = croiser_planning_chargement(
                    plannings, chargement, st.session_state.jour_analyse
                )
                st.session_state.results = results
                st.session_state["excel_bytes"] = None  # Invalider l'ancien export
                st.toast(f"✅ Analyse terminée — {len(results)} réappros traités")
            except Exception as e:
                st.error(f"Erreur : {e}")
                st.stop()
        st.rerun()  # Force re-render : Export Excel voit maintenant st.session_state.results

    if not st.session_state.results:
        st.stop()

    results = st.session_state.results

    jour = st.session_state.jour_analyse

    # KPIs
    st.divider()
    total_prev   = sum(len(d["salles_prevues"])    for d in results.values())
    total_fait   = sum(len(d["salles_faites"])     for d in results.values())
    total_nf     = sum(len(d["salles_non_faites"]) for d in results.values())
    total_joker  = sum(sum(1 for s in d["salles_faites"] if s["is_joker"]) for d in results.values())
    total_decale = sum(1 for d in results.values() if d.get("tournee_decalee"))
    taux_global  = round((total_fait / total_prev * 100) if total_prev > 0 else 0, 1)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("📋 Prévues",     total_prev)
    k2.metric("✅ Faites",      total_fait)
    k3.metric("❌ Non faites",  total_nf,
              delta=f"-{total_nf}" if total_nf else None, delta_color="inverse")
    k4.metric("🔄 Jokers",      total_joker)
    k5.metric("📅 Décalées",    total_decale)
    k6.metric("📈 Taux global", f"{taux_global}%")

    # Tabs résultats
    tab_recap, tab_nf, tab_jokers, tab_decale, tab_detail = st.tabs([
        "📋 Récapitulatif", "❌ Non Faites", "🔄 Jokers", "📅 Tournées Décalées", "🔍 Détail par réappro"
    ])

    with tab_recap:
        rows = []
        for reappro, data in sorted(results.items()):
            nb_p  = len(data["salles_prevues"])
            nb_f  = len(data["salles_faites"])
            nb_nf = len(data["salles_non_faites"])
            nb_j  = sum(1 for s in data["salles_faites"] if s["is_joker"])
            taux  = round((nb_f / nb_p * 100) if nb_p > 0 else 0, 1)
            decale = "📅 " + data.get("tournee_decalee", {}).get("jour_detecte", "") if data.get("tournee_decalee") else ""
            rows.append({"Réappro": reappro, "Prévues": nb_p, "Faites": nb_f,
                         "Non Faites": nb_nf, "Jokers": nb_j, "Décalée": decale, "Taux (%)": taux})
        df_recap = pd.DataFrame(rows)
        def color_row(row):
            if row["Non Faites"] == 0:
                return ["background-color:#1E7E34; color:#FFFFFF; font-weight:600"] * len(row)
            elif row["Non Faites"] == row["Prévues"]:
                return ["background-color:#C0392B; color:#FFFFFF; font-weight:600"] * len(row)
            else:
                return ["background-color:#E67E22; color:#FFFFFF; font-weight:600"] * len(row)
        st.dataframe(
            df_recap.style.apply(color_row, axis=1),
            use_container_width=True, hide_index=True,
            height=min(700, 38 + len(df_recap) * 35),
        )

    with tab_nf:
        nf_rows = []
        for reappro, data in sorted(results.items()):
            for s in data["salles_non_faites"]:
                nf_rows.append({"Réappro": reappro, "Client / Salle": s["client"], "Machine": s["machine"]})
        if nf_rows:
            df_nf = pd.DataFrame(nf_rows)
            st.dataframe(
                df_nf.style.map(lambda _: "background-color:#C0392B; color:#FFFFFF; font-weight:600"),
                use_container_width=True, hide_index=True,
                height=min(700, 38 + len(df_nf) * 35),
            )
        else:
            st.success("🎉 Toutes les salles ont été faites !")

    with tab_jokers:
        joker_rows = []
        for reappro, data in sorted(results.items()):
            for s in data["salles_faites"]:
                if s["is_joker"]:
                    joker_rows.append({
                        "Réappro Prévu": reappro, "Client / Salle": s["client"],
                        "Machine": s["machine"], "Fait Par": s["employe_reel"],
                        "Valeur Ref": s["val_ref"], "Statut": s["statut"],
                    })
        if joker_rows:
            df_joker = pd.DataFrame(joker_rows)
            st.dataframe(
                df_joker.style.map(lambda _: "background-color:#E67E22; color:#FFFFFF; font-weight:600"),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Aucun remplacement détecté.")

    with tab_decale:
        decale_rows = []
        for reappro, data in sorted(results.items()):
            td = data.get("tournee_decalee")
            if td:
                nb_matchees = len(td["salles_decalees"])
                decale_rows.append({
                    "Réappro": reappro, "Jour planifié": jour,
                    "Tournée détectée": td["jour_detecte"],
                    "Salles matchées": nb_matchees,
                    "Total fait": td["nb_machines_faites"],
                    "Salles (planning)": ", ".join(f"{c} [{m}]" for c, m in td["salles_decalees"][:5])
                                         + ("..." if nb_matchees > 5 else ""),
                })
        if decale_rows:
            st.info(
                "Ces réappros ont des salles non faites sur le jour analysé, mais ont quand même "
                "effectué des chargements correspondant à un **autre jour** de leur planning."
            )
            df_decale = pd.DataFrame(decale_rows)
            st.dataframe(
                df_decale.style.map(lambda _: "background-color:#6C3483; color:#FFFFFF; font-weight:600"),
                use_container_width=True, hide_index=True,
            )
            st.markdown("#### Détail des salles décalées")
            for reappro, data in sorted(results.items()):
                td = data.get("tournee_decalee")
                if not td:
                    continue
                with st.expander(f"🔍 {reappro} — tournée du {td['jour_detecte']} faite un {jour}"):
                    detail_dec = [{"Client / Salle": c, "Machine": m} for c, m in td["salles_decalees"]]
                    if detail_dec:
                        st.dataframe(
                            pd.DataFrame(detail_dec).style.map(
                                lambda _: "background-color:#6C3483; color:#FFFFFF; font-weight:600"
                            ),
                            use_container_width=True, hide_index=True,
                        )
                    if td["salles_hors_planning"]:
                        st.caption(f"⚠️ {len(td['salles_hors_planning'])} machine(s) faite(s) hors planning : "
                                   + ", ".join(td["salles_hors_planning"]))
        else:
            st.success("✅ Aucune tournée décalée détectée.")

    with tab_detail:
        selected = st.selectbox("Choisir un réappro", sorted(results.keys()))
        if selected:
            data = results[selected]
            nb_p  = len(data["salles_prevues"])
            nb_f  = len(data["salles_faites"])
            nb_nf = len(data["salles_non_faites"])
            nb_j  = sum(1 for s in data["salles_faites"] if s["is_joker"])
            taux  = round((nb_f / nb_p * 100) if nb_p > 0 else 0, 1)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Prévues",    nb_p)
            c2.metric("Faites",     nb_f)
            c3.metric("Non Faites", nb_nf)
            c4.metric("Taux",       f"{taux}%")
            detail_rows = []
            for s in data["salles_non_faites"]:
                detail_rows.append({"Statut": "❌ Non Faite", "Client / Salle": s["client"],
                                     "Machine": s["machine"], "Fait Par": "", "Valeur Ref": ""})
            for s in data["salles_faites"]:
                if s["is_joker"]:
                    detail_rows.append({"Statut": "🔄 Joker", "Client / Salle": s["client"],
                                         "Machine": s["machine"], "Fait Par": s["employe_reel"],
                                         "Valeur Ref": s["val_ref"]})
            for s in data["salles_faites"]:
                if not s["is_joker"]:
                    detail_rows.append({"Statut": "✅ Fait", "Client / Salle": s["client"],
                                         "Machine": s["machine"], "Fait Par": s["employe_reel"],
                                         "Valeur Ref": s["val_ref"]})
            def color_detail(row):
                if "Non Faite" in str(row["Statut"]):
                    return ["background-color:#C0392B; color:#FFFFFF; font-weight:600"] * len(row)
                elif "Joker" in str(row["Statut"]):
                    return ["background-color:#E67E22; color:#FFFFFF; font-weight:600"] * len(row)
                else:
                    return ["background-color:#1E7E34; color:#FFFFFF; font-weight:600"] * len(row)
            if detail_rows:
                df_d = pd.DataFrame(detail_rows)
                st.dataframe(
                    df_d.style.apply(color_detail, axis=1),
                    use_container_width=True, hide_index=True,
                    height=min(700, 38 + len(df_d) * 35),
                )



# ════════════════════════════════════════════════════════
# PAGE : PLANOGRAMMES
# ════════════════════════════════════════════════════════
elif st.session_state.page == "planogrammes":

    st.markdown('<div class="main-title">🗂️ Gestionnaire de Planogrammes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Créez, modifiez et exportez vos planogrammes de distributeurs automatiques.</div>',
        unsafe_allow_html=True,
    )

    page_planogrammes.render()


# ════════════════════════════════════════════════════════
# PAGE : INVENTAIRES
# ════════════════════════════════════════════════════════
elif st.session_state.page == "inventaires":

    st.markdown('<div class="main-title">📊 Suivi des Inventaires</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Analysez les inventaires machines par réappro — '
        'contrôle des seuils, produits manquants, statuts.</div>',
        unsafe_allow_html=True,
    )

    page_inventaires.render()


# ════════════════════════════════════════════════════════
# PAGE : COMMANDES
# ════════════════════════════════════════════════════════
elif st.session_state.page == "commandes":

    st.markdown('<div class="main-title">🛒 Suivi des Commandes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Importez un screenshot de mail de commande et injectez-le dans le fichier Excel de suivi.</div>',
        unsafe_allow_html=True,
    )

    page_commandes.render()


# ════════════════════════════════════════════════════════
# PAGE : INDÉFINIS
# ════════════════════════════════════════════════════════
elif st.session_state.page == "indefinis":

    st.markdown('<div class="main-title">❓ Détection des Indéfinis</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Identifiez les lignes mal paramétrées qui génèrent des ventes en INDÉFINI.</div>',
        unsafe_allow_html=True,
    )

    page_indefinis.render()


# ════════════════════════════════════════════════════════
# PAGE : CR
# ════════════════════════════════════════════════════════
elif st.session_state.page == "cr":

    st.markdown('<div class="main-title">📝 Compte Rendu Hebdomadaire</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Générez le compte rendu hebdomadaire par zone géographique.</div>',
        unsafe_allow_html=True,
    )

    page_cr.render()


# ════════════════════════════════════════════════════════
# PAGE : QUARTIX
# ════════════════════════════════════════════════════════
elif st.session_state.page == "quartix":

    st.markdown('<div class="main-title">🗺️ Trajets QUARTIX</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Visualisez le trajet complet d\'un réappro — tracé de route, arrêts et durées.</div>',
        unsafe_allow_html=True,
    )

    page_quartix.render()


# ════════════════════════════════════════════════════════
# PAGE : PICKLIST VS CHARGEMENT
# ════════════════════════════════════════════════════════
elif st.session_state.page == "picklist":

    page_picklist.render()
