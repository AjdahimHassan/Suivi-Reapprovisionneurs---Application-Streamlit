"""
Application Streamlit - Suivi des Reapprovisionneurs
Les plannings sont charges depuis le dossier relatif plannings/.
L'utilisateur uploade uniquement le fichier de chargement machine du jour.
"""

import streamlit as st
import pandas as pd
import datetime
from pathlib import Path

from planning_parser import load_all_plannings_from_folder, get_today_day_str, JOURS
from chargement_parser import parse_chargement_csv, croiser_planning_chargement
from excel_export import generer_excel

# ────────────────────────────────────────────────────────
# CONFIG PAGE
# ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Suivi Reapprovisionneurs",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.main-title { font-size:2rem; font-weight:800; color:#1F4E79; margin-bottom:0.2rem; }
.subtitle   { font-size:1rem; color:#555; margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────────────
# DOSSIER DES PLANNINGS — dossier relatif au projet
# ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
PLANNING_DIR = APP_DIR / "plannings"

@st.cache_data(show_spinner="Chargement des plannings...")
def charger_plannings():
    plannings, errors = load_all_plannings_from_folder(str(PLANNING_DIR))
    if plannings:
        return plannings, errors, str(PLANNING_DIR)
    return {}, {"erreur": f"Aucun planning trouve dans {PLANNING_DIR}."}, str(PLANNING_DIR)

plannings, planning_errors, planning_folder = charger_plannings()

# ────────────────────────────────────────────────────────
# SESSION STATE
# ────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = {}
if "jour_analyse" not in st.session_state:
    st.session_state.jour_analyse = get_today_day_str()

# ────────────────────────────────────────────────────────
# SIDEBAR
# ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📦 Suivi Réappro")
    st.divider()

    # Statut plannings
    if plannings:
        st.success(f"✅ {len(plannings)} plannings chargés")
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

    st.divider()

    st.markdown("### Jour d'analyse")
    jour_selectionne = st.selectbox(
        "Jour",
        JOURS,
        index=JOURS.index(st.session_state.jour_analyse)
        if st.session_state.jour_analyse in JOURS else 0,
        label_visibility="collapsed",
    )
    st.session_state.jour_analyse = jour_selectionne

    st.divider()
    st.caption(f"Dossier plannings : `{planning_folder}`")

# ────────────────────────────────────────────────────────
# HEADER
# ────────────────────────────────────────────────────────
st.markdown('<div class="main-title">📦 Suivi des Réapprovisionneurs</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="subtitle">Analyse du <b>{st.session_state.jour_analyse}</b> — '
    f'{datetime.date.today().strftime("%d/%m/%Y")}</div>',
    unsafe_allow_html=True,
)

if not plannings:
    st.stop()

# ────────────────────────────────────────────────────────
# UPLOAD CHARGEMENT
# ────────────────────────────────────────────────────────
st.markdown("### 📂 Déposer le fichier de chargement machine du jour")

uploaded = st.file_uploader(
    "Fichier export chargement (CSV)",
    type=["csv"],
    key="chargement_uploader",
    label_visibility="collapsed",
)

col_btn, _ = st.columns([1, 5])
with col_btn:
    lancer = st.button(
        "🚀 Lancer l'analyse",
        type="primary",
        use_container_width=True,
        disabled=(uploaded is None),
    )

if lancer and uploaded:
    with st.spinner("Analyse en cours..."):
        try:
            chargement = parse_chargement_csv(uploaded.read())
            results = croiser_planning_chargement(
                plannings, chargement, st.session_state.jour_analyse
            )
            st.session_state.results = results
            st.success(f"✅ Analyse terminée — {len(results)} réappros traités")
        except Exception as e:
            st.error(f"Erreur : {e}")
            st.stop()

# ────────────────────────────────────────────────────────
# RÉSULTATS
# ────────────────────────────────────────────────────────
if not st.session_state.results:
    st.stop()

results = st.session_state.results
jour = st.session_state.jour_analyse

# KPIs
st.divider()
total_prev  = sum(len(d["salles_prevues"])   for d in results.values())
total_fait  = sum(len(d["salles_faites"])    for d in results.values())
total_nf    = sum(len(d["salles_non_faites"]) for d in results.values())
total_joker = sum(sum(1 for s in d["salles_faites"] if s["is_joker"]) for d in results.values())
taux_global = round((total_fait / total_prev * 100) if total_prev > 0 else 0, 1)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📋 Prévues",    total_prev)
k2.metric("✅ Faites",     total_fait)
k3.metric("❌ Non faites", total_nf,
          delta=f"-{total_nf}" if total_nf else None, delta_color="inverse")
k4.metric("🔄 Jokers",     total_joker)
k5.metric("📈 Taux global", f"{taux_global}%")

# ────────────────────────────────────────────────────────
# TABS
# ────────────────────────────────────────────────────────
tab_recap, tab_nf, tab_jokers, tab_detail = st.tabs([
    "📋 Récapitulatif", "❌ Non Faites", "🔄 Jokers", "🔍 Détail par réappro"
])

# ── RÉCAPITULATIF ──
with tab_recap:
    rows = []
    for reappro, data in sorted(results.items()):
        nb_p  = len(data["salles_prevues"])
        nb_f  = len(data["salles_faites"])
        nb_nf = len(data["salles_non_faites"])
        nb_j  = sum(1 for s in data["salles_faites"] if s["is_joker"])
        taux  = round((nb_f / nb_p * 100) if nb_p > 0 else 0, 1)
        rows.append({"Réappro": reappro, "Prévues": nb_p, "Faites": nb_f,
                     "Non Faites": nb_nf, "Jokers": nb_j, "Taux (%)": taux})

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

# ── NON FAITES ──
with tab_nf:
    nf_rows = []
    for reappro, data in sorted(results.items()):
        for s in data["salles_non_faites"]:
            nf_rows.append({"Réappro": reappro, "Client / Salle": s["client"], "Machine": s["machine"]})

    if nf_rows:
        df_nf = pd.DataFrame(nf_rows)
        st.dataframe(
            df_nf.style.applymap(lambda _: "background-color:#C0392B; color:#FFFFFF; font-weight:600"),
            use_container_width=True, hide_index=True,
            height=min(700, 38 + len(df_nf) * 35),
        )
    else:
        st.success("🎉 Toutes les salles ont été faites !")

# ── JOKERS ──
with tab_jokers:
    joker_rows = []
    for reappro, data in sorted(results.items()):
        for s in data["salles_faites"]:
            if s["is_joker"]:
                joker_rows.append({
                    "Réappro Prévu": reappro,
                    "Client / Salle": s["client"],
                    "Machine": s["machine"],
                    "Fait Par": s["employe_reel"],
                    "Valeur Ref": s["val_ref"],
                    "Statut": s["statut"],
                })
    if joker_rows:
        df_joker = pd.DataFrame(joker_rows)
        st.dataframe(
            df_joker.style.applymap(lambda _: "background-color:#E67E22; color:#FFFFFF; font-weight:600"),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("Aucun remplacement détecté.")

# ── DÉTAIL PAR RÉAPPRO ──
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

# ────────────────────────────────────────────────────────
# EXPORT EXCEL
# ────────────────────────────────────────────────────────
st.divider()
st.markdown("### 📥 Export Excel")

col_exp, _ = st.columns([1, 4])
with col_exp:
    if st.button("📊 Générer le fichier Excel", use_container_width=True):
        with st.spinner("Génération..."):
            try:
                excel_bytes = generer_excel(results, jour)
                date_str = datetime.date.today().strftime("%Y%m%d")
                st.download_button(
                    label="⬇️ Télécharger Excel",
                    data=excel_bytes,
                    file_name=f"suivi_reappro_{date_str}_{jour}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Erreur Excel : {e}")
