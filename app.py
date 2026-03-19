"""
Application Streamlit - Outil Réappro
  ├── 📦 Suivi Réapprovisionneurs
  └── 🗂️  Planogrammes
"""

import streamlit as st
import pandas as pd
import datetime
import streamlit.components.v1 as components
from pathlib import Path

from planning_parser import get_today_day_str, JOURS
from mongo_storage import load_plannings_from_mongo
from chargement_parser import parse_chargement_csv, croiser_planning_chargement
from excel_export import generer_excel

# ────────────────────────────────────────────────────────
# CONFIG PAGE
# ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Outil Réappro",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
/* Cache le bouton toggle de la sidebar */
[data-testid="collapsedControl"] { display: none !important; }

/* Titres */
.main-title { font-size:2rem; font-weight:800; color:#1F4E79; margin-bottom:0.2rem; }
.subtitle   { font-size:1rem; color:#555; margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────────────
# SESSION STATE
# ────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "suivi"
if "results" not in st.session_state:
    st.session_state.results = {}
if "jour_analyse" not in st.session_state:
    st.session_state.jour_analyse = get_today_day_str()

# ────────────────────────────────────────────────────────
# NAVIGATION — barre en haut de la page principale
# ────────────────────────────────────────────────────────
nav_c1, nav_c2, nav_rest = st.columns([2, 2, 6])
with nav_c1:
    if st.button(
        "📦  Suivi Réapprovisionneurs",
        key="nav_suivi",
        use_container_width=True,
        type="primary" if st.session_state.page == "suivi" else "secondary",
    ):
        st.session_state.page = "suivi"
        st.rerun()
with nav_c2:
    if st.button(
        "🗂️  Planogrammes",
        key="nav_plano",
        use_container_width=True,
        type="primary" if st.session_state.page == "planogrammes" else "secondary",
    ):
        st.session_state.page = "planogrammes"
        st.rerun()

st.divider()

# ────────────────────────────────────────────────────────
# SIDEBAR — uniquement pour la page Suivi (options jour)
# ────────────────────────────────────────────────────────
if st.session_state.page == "suivi":
    with st.sidebar:
        st.markdown("## ⚙️ Options")
        st.divider()

        @st.cache_data(show_spinner="Chargement des plannings...", ttl=300)
        def _charger():
            return load_plannings_from_mongo()

        plannings, planning_errors = _charger()

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
            "Jour", JOURS,
            index=JOURS.index(st.session_state.jour_analyse)
            if st.session_state.jour_analyse in JOURS else 0,
            label_visibility="collapsed",
        )
        st.session_state.jour_analyse = jour_selectionne
        st.divider()
        st.caption("Plannings : `MongoDB Atlas`")


# ════════════════════════════════════════════════════════
# PAGE : SUIVI RÉAPPROVISIONNEURS
# ════════════════════════════════════════════════════════
if st.session_state.page == "suivi":

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

    st.markdown("### 📂 Déposer le fichier de chargement machine du jour")
    uploaded = st.file_uploader(
        "Fichier export chargement (CSV)", type=["csv"],
        key="chargement_uploader", label_visibility="collapsed",
    )

    col_btn, _ = st.columns([1, 5])
    with col_btn:
        lancer = st.button(
            "🚀 Lancer l'analyse", type="primary",
            use_container_width=True, disabled=(uploaded is None),
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

    if not st.session_state.results:
        st.stop()

    results = st.session_state.results
    jour    = st.session_state.jour_analyse

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
                df_nf.style.applymap(lambda _: "background-color:#C0392B; color:#FFFFFF; font-weight:600"),
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
                df_joker.style.applymap(lambda _: "background-color:#E67E22; color:#FFFFFF; font-weight:600"),
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
                df_decale.style.applymap(lambda _: "background-color:#6C3483; color:#FFFFFF; font-weight:600"),
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
                            pd.DataFrame(detail_dec).style.applymap(
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

    # Export Excel
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


# ════════════════════════════════════════════════════════
# PAGE : PLANOGRAMMES
# ════════════════════════════════════════════════════════
elif st.session_state.page == "planogrammes":

    st.markdown('<div class="main-title">🗂️ Gestionnaire de Planogrammes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Créez, modifiez et exportez vos planogrammes de distributeurs automatiques.</div>',
        unsafe_allow_html=True,
    )

    html_path = Path(__file__).parent / "assets" / "planogram_manager.html"

    if not html_path.exists():
        st.error(
            "❌ Fichier introuvable : `assets/planogram_manager.html`\n\n"
            "Assurez-vous que le fichier est bien présent dans le dossier `assets/` du projet."
        )
        st.stop()

    html_content = html_path.read_text(encoding="utf-8")
    components.html(html_content, height=920, scrolling=True)

    st.caption(
        "💾 Les planogrammes sont sauvegardés dans le **localStorage de votre navigateur** — "
        "ils persistent entre les sessions sur ce poste. "
        "Pour partager, utilisez l'export **Excel** ou **PDF**."
    )
