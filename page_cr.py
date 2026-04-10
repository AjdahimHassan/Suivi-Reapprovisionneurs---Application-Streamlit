"""
Page CR — Compte Rendu Hebdomadaire

Génère un email de compte rendu par zone géographique.
Sources :
  - Collection MongoDB "reappros"  : répartition zones ↔ réappros (import Excel)
  - Collection MongoDB "machines"  : parc machines (champ Approvisionneur)
  - Collection MongoDB "incidents" : problèmes actifs non résolus
"""

import io
import datetime

import pandas as pd
import streamlit as st

from mongo_storage import _get_client
from page_inventaires import _parse_planning_for_reappro, WEEKDAY_TO_JOUR

# ────────────────────────────────────────────────────────
# CONSTANTES
# ────────────────────────────────────────────────────────

ZONES = ["IDF", "OUEST", "NORD ET CENTRE", "SUD OUEST", "SUD EST", "EST"]

SEP = "________________________________________"

SECTION_DEFAULTS: dict[str, str] = {
    "Livraisons / Fournisseurs": "Les livraisons ont été contrôlées et validées.",
    "Tournées":                   "Toutes les tournées se sont bien déroulées.",
    "Inventaire":                 "",
}


# ────────────────────────────────────────────────────────
# MONGODB — helpers
# ────────────────────────────────────────────────────────

def _get_col(name: str):
    client = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name][name]


@st.cache_data(show_spinner=False, ttl=300)
def _load_reappros_from_mongo() -> pd.DataFrame:
    """Retourne le DataFrame réappros {code, reappro, prenom, zone_geo, zone}."""
    try:
        docs = list(_get_col("reappros").find({}, {"_id": 0}))
        if not docs:
            return pd.DataFrame(columns=["code", "reappro", "prenom", "zone_geo", "zone"])
        return pd.DataFrame(docs)
    except Exception as e:
        st.error(f"❌ Impossible de charger les réappros : {e}")
        return pd.DataFrame()


def _load_incidents_for_zone(zone: str, reappros_df: pd.DataFrame) -> list[dict]:
    """
    Retourne la liste des incidents actifs pour une zone donnée.
    Chaque incident est enrichi avec le prénom du réappro responsable.
    """
    if reappros_df.empty:
        return []

    # 1. Codes réappros de la zone
    codes_zone = set(
        reappros_df[reappros_df["zone"] == zone]["code"].str.strip().tolist()
    )
    if not codes_zone:
        return []

    # 2. Salles dont l'Approvisionneur est dans les codes de la zone
    machines = list(
        _get_col("machines").find(
            {"Approvisionneur": {"$in": list(codes_zone)}},
            {"_id": 0, "Client": 1, "Approvisionneur": 1},
        )
    )
    # mapping salle → code_reappro
    salle_to_code: dict[str, str] = {
        m["Client"]: m.get("Approvisionneur", "") for m in machines
    }
    salles_zone = set(salle_to_code.keys())
    if not salles_zone:
        return []

    # 3. Incidents actifs pour ces salles (avec type et created_at)
    incidents_raw = list(
        _get_col("incidents").find(
            {"salle": {"$in": list(salles_zone)}, "status": "actif"},
            {"_id": 0, "salle": 1, "commentaire": 1, "type": 1, "created_at": 1, "since_date": 1},
        )
    )

    # 4. Enrichir avec prénom du réappro
    code_to_prenom: dict[str, str] = dict(
        zip(reappros_df["code"].str.strip(), reappros_df["prenom"].str.strip())
    )
    result = []
    for inc in incidents_raw:
        salle = inc.get("salle", "")
        code  = salle_to_code.get(salle, "")
        prenom = code_to_prenom.get(code, code)
        # Priorité : since_date (date métier) > created_at (fallback)
        created_at = inc.get("created_at")
        since_str  = inc.get("since_date") or (
            created_at.strftime("%d/%m/%Y") if created_at else None
        )
        result.append({
            "salle":       salle,
            "commentaire": inc.get("commentaire", ""),
            "type":        inc.get("type", ""),   # "no_audit" ou "sans_ventes"
            "since":       since_str,
            "prenom":      prenom,
            "code":        code,
        })

    # Tri : no_audit d'abord, puis sans_ventes ; dans chaque groupe tri par réappro puis salle
    result.sort(key=lambda x: (0 if x["type"] == "no_audit" else 1, x["code"], x["salle"]))
    return result


def _build_da_content(incidents: list[dict]) -> str:
    """
    Génère le texte de la section DA en distinguant :
      - Sans remontée télémétrie (no_audit)   → affiché en premier
      - Sans ventes (sans_ventes)              → affiché en second
    """
    if not incidents:
        return "Toutes les salles ont été traitées dans les groupes."

    no_audit   = [i for i in incidents if i["type"] == "no_audit"]
    sans_ventes = [i for i in incidents if i["type"] == "sans_ventes"]

    def _fmt_line(inc: dict) -> str:
        commentaire = inc["commentaire"].strip() if inc["commentaire"] else "—"
        since = f" (depuis le {inc['since']})" if inc.get("since") else ""
        return f"{inc['salle']}{since} : {commentaire} par {inc['prenom']}"

    lines = []

    if no_audit:
        lines.append("• Sans remontée télémétrie :")
        for inc in no_audit:
            lines.append(f"  {_fmt_line(inc)}")

    if no_audit and sans_ventes:
        lines.append("")  # ligne vide entre les deux groupes

    if sans_ventes:
        lines.append("• Sans ventes :")
        for inc in sans_ventes:
            lines.append(f"  {_fmt_line(inc)}")

    return "\n".join(lines)


def _generate_mail(
    zone: str,
    sections: list[tuple[str, str]],  # [(titre, contenu), ...]
) -> str:
    """Génère le texte complet du mail."""
    lines = ["Bonjour à tous,", ""]
    for i, (titre, contenu) in enumerate(sections, start=1):
        lines.append(f"{i}.{titre} :")
        lines.append("")
        lines.append(contenu)
        lines.append(SEP)
    lines.append("")
    lines.append("Bien cordialement,")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────
# IMPORT EXCEL
# ────────────────────────────────────────────────────────

def _import_reappros(raw_bytes: bytes) -> tuple[int, list[str]]:
    """
    Importe le fichier Reappro Guide.xlsx dans MongoDB.
    Retourne (nb_lignes, zones_détectées).
    """
    df = pd.read_excel(io.BytesIO(raw_bytes), header=0)
    df.columns = [str(c).strip() for c in df.columns]

    # Mapping colonnes par position :
    # col 0 = Code, col 1 = prenom, col 2 = Zone Géographique, col 3 = zone, col 4 = Responsable
    cols = df.columns.tolist()
    rename = {
        cols[0]: "code",
        cols[1]: "prenom",
        cols[2]: "zone_geo",
        cols[3]: "zone",
        cols[4]: "responsable",
    }
    df = df.rename(columns=rename)[["code", "prenom", "zone_geo", "zone", "responsable"]]
    df = df.dropna(subset=["code", "zone"]).copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["code"] != ""]

    docs = df.to_dict("records")
    col = _get_col("reappros")
    col.delete_many({})
    if docs:
        col.insert_many(docs)

    zones = sorted(df["zone"].unique().tolist())
    _load_reappros_from_mongo.clear()
    return len(docs), zones


# ────────────────────────────────────────────────────────
# INVENTAIRE AUTO-GENERATION
# ────────────────────────────────────────────────────────

def _build_inventaire_cr_text(
    done_records: list,
    plannings_mongo: dict,
    reappros_df: pd.DataFrame,
    zone: str,
    include_vendredi: bool = False,
) -> str:
    """
    Génère le texte de la section Inventaire du CR depuis les enregistrements BDD.
    done_records : [{"reappro": ..., "date": "dd/mm/yyyy", "code": ...}, ...]
    Cas gérés :
      - Tout fait                    → non mentionné
      - 0 fait toute la semaine      → "aucune salle faite de la semaine"
      - ≤ 2 salles faites la semaine → "aucune salle faite cette semaine sauf X, Y"
      - Quelques manquants par jour  → "X, Y n'ont pas été faites"
      - 0 fait ce jour               → "aucune salle n'a été faite"
      - 1 fait ce jour               → "aucune salle n'a été faite sauf X"
      - Joker                        → "fait par [prénom]"
    """
    if not done_records:
        return "Aucune donnée d'inventaire disponible."

    done_set = {(r["reappro"], r["date"], r["code"]) for r in done_records}

    if not reappros_df.empty and zone:
        zone_codes = set(reappros_df[reappros_df["zone"] == zone]["code"].str.strip())
    else:
        zone_codes = set(plannings_mongo.keys())

    code_to_prenom = (
        dict(zip(reappros_df["code"].str.strip(), reappros_df["prenom"].str.strip()))
        if not reappros_df.empty else {}
    )

    # ISO weeks depuis les dates des enregistrements
    dates = {r["date"] for r in done_records}
    iso_pairs_set = set()
    for d in dates:
        try:
            dt = datetime.datetime.strptime(d, "%d/%m/%Y")
            iso = dt.isocalendar()
            iso_pairs_set.add((int(iso[0]), int(iso[1])))
        except ValueError:
            pass
    iso_pairs = sorted(iso_pairs_set)
    if not iso_pairs:
        return "Aucune date trouvée dans les enregistrements."

    week_days = []
    for iso_year, iso_week in iso_pairs:
        monday = datetime.datetime.fromisocalendar(iso_year, iso_week, 1)
        for offset in range(5):
            day_dt  = monday + datetime.timedelta(days=offset)
            jour_fr = WEEKDAY_TO_JOUR.get(day_dt.weekday())
            if jour_fr and (include_vendredi or jour_fr != "Vendredi"):
                week_days.append((day_dt.strftime("%d/%m/%Y"), jour_fr))

    zone_plannings = {r: p for r, p in plannings_mongo.items() if r in zone_codes}
    if not zone_plannings:
        return "Aucun réappro trouvé pour cette zone dans les plannings."

    def _accord(n):
        return "n'ont pas été faites" if n > 1 else "n'a pas été faite"

    result_blocks = []

    for reappro in sorted(zone_plannings.keys()):
        planning = _parse_planning_for_reappro(zone_plannings[reappro])
        prenom   = code_to_prenom.get(reappro, reappro)

        # ── Collecter les données de toute la semaine ─────────────────────
        week_own    = []   # toutes salles faites par lui cette semaine
        week_joker  = []   # [(salle, prenom_joker)] cette semaine
        week_missing= 0
        day_data    = []   # [(jour_fr, done_own, done_joker, missing)]

        for date_str, jour_fr in week_days:
            if jour_fr not in planning or not planning[jour_fr]:
                continue
            jour_plan  = planning[jour_fr]
            done_own   = []
            done_joker = []
            missing    = []

            for code, info in sorted(jour_plan.items(), key=lambda x: x[1]["label"]):
                salle = info["label"]
                if (reappro, date_str, code) in done_set:
                    done_own.append(salle)
                else:
                    joker_r = next(
                        (r for r in plannings_mongo
                         if r != reappro and (r, date_str, code) in done_set),
                        None,
                    )
                    if joker_r:
                        done_joker.append((salle, code_to_prenom.get(joker_r, joker_r)))
                    else:
                        missing.append(salle)

            week_own.extend(done_own)
            week_joker.extend(done_joker)
            week_missing += len(missing)
            day_data.append((jour_fr, done_own, done_joker, missing))

        if not day_data:
            continue

        week_done = len(week_own) + len(week_joker)

        # ── Résumé hebdomadaire si presque rien fait ──────────────────────
        if week_done == 0 and week_missing > 0:
            result_blocks.append(f"{prenom} ({reappro}) :\n- aucune salle faite de la semaine")
            continue

        if week_done <= 2 and week_missing > 0:
            sauf_parts = week_own + [f"{s} (fait par {p})" for s, p in week_joker]
            result_blocks.append(
                f"{prenom} ({reappro}) :\n"
                f"- aucune salle faite cette semaine sauf {', '.join(sauf_parts)}"
            )
            continue

        # ── Détail jour par jour ──────────────────────────────────────────
        day_lines = []
        for jour_fr, done_own, done_joker, missing in day_data:
            done_count = len(done_own) + len(done_joker)

            if not missing and not done_joker:
                continue  # jour parfait

            if not missing:
                jk = ", ".join(f"{s} (fait par {p})" for s, p in done_joker)
                day_lines.append(f"- {jour_fr} : {jk}")
                continue

            joker_suffix = (
                " — " + ", ".join(f"{s} fait par {p}" for s, p in done_joker)
                if done_joker else ""
            )

            if done_count == 0:
                line = f"- {jour_fr} : aucune salle n'a été faite"
            elif len(done_own) == 1 and not done_joker:
                line = f"- {jour_fr} : aucune salle n'a été faite sauf {done_own[0]}"
            elif done_count == 1 and done_joker:
                s, p = done_joker[0]
                line = f"- {jour_fr} : aucune salle n'a été faite sauf {s} (fait par {p})"
            else:
                miss_str = ", ".join(missing)
                line = f"- {jour_fr} : {miss_str} {_accord(len(missing))}{joker_suffix}"

            day_lines.append(line)

        if day_lines:
            result_blocks.append(f"{prenom} ({reappro}) :\n" + "\n".join(day_lines))

    if not result_blocks:
        return "Tous les inventaires ont été réalisés conformément au planning."

    return "\n\n".join(result_blocks)


# ────────────────────────────────────────────────────────
# RENDER
# ────────────────────────────────────────────────────────

def render():
    reappros_df = _load_reappros_from_mongo()
    no_reappros = reappros_df.empty

    # Plannings (pour la génération auto inventaire)
    plannings_mongo: dict = {}
    try:
        from mongo_storage import load_plannings_from_mongo

        @st.cache_data(show_spinner=False, ttl=300)
        def _get_plannings_cr():
            return load_plannings_from_mongo()

        plannings_mongo, _ = _get_plannings_cr()
    except Exception:
        pass

    if no_reappros:
        st.warning("⚠️ Aucune répartition des zones en base. Importez le fichier ci-dessous.")

    # ── Sélecteurs ───────────────────────────────────────
    col_zone, col_date, _ = st.columns([2, 2, 4])
    with col_zone:
        zone = st.selectbox("Zone", ZONES, key="cr_zone", disabled=no_reappros)

    # Vider le contenu DA en cache si la zone a changé depuis le dernier rendu
    if st.session_state.get("_cr_last_zone") != zone:
        for k in list(st.session_state.keys()):
            if k.startswith("cr_da_content_"):
                del st.session_state[k]
        st.session_state["_cr_last_zone"] = zone
    with col_date:
        date_rapport = st.date_input(
            "Date du rapport",
            value=datetime.date.today(),
            key="cr_date",
        )

    # ── Objet ────────────────────────────────────────────
    objet_default = f"COMPTE RENDU {zone}"
    objet = st.text_input("📧 Objet du mail", value=objet_default, key=f"cr_objet_{zone}")

    st.divider()

    # ── Sections modulables ───────────────────────────────
    st.markdown("#### Sections à inclure")

    # --- Section DA (auto) ---
    col_chk_da, _ = st.columns([3, 7])
    with col_chk_da:
        include_da = st.checkbox("Distributeur Automatique (DA)", value=True, key="cr_chk_da")

    da_content = ""
    if include_da:
        if not no_reappros:
            with st.spinner("Chargement des incidents DA..."):
                incidents = _load_incidents_for_zone(zone, reappros_df)
            da_content = _build_da_content(incidents)
        else:
            da_content = "Toutes les salles ont été traitées dans les groupes."
        da_content = st.text_area(
            "Contenu DA",
            value=da_content,
            height=150,
            key=f"cr_da_content_{zone}",
            label_visibility="collapsed",
        )

    st.markdown("---")

    # --- Sections libres standard ---
    sections_standard = [
        ("Livraisons / Fournisseurs", True),
        ("Tournées", True),
        ("Inventaire", False),
    ]

    section_contents: dict[str, str] = {}
    for titre, default_checked in sections_standard:
        col_chk, _ = st.columns([3, 7])
        with col_chk:
            checked = st.checkbox(titre, value=default_checked, key=f"cr_chk_{titre}")

        if checked:
            if titre == "Inventaire":
                # ── Section Inventaire — données depuis la BDD ──────────────
                try:
                    from mongo_storage import list_inventaires_semaines, load_inventaires_semaine
                    semaines_dispo = list_inventaires_semaines()
                except Exception:
                    semaines_dispo = []

                if not semaines_dispo:
                    st.caption(
                        "⚠️ Aucune semaine sauvegardée. "
                        "Uploadez un CSV dans la page Inventaires et cliquez sur "
                        "**💾 Sauvegarder en BDD**."
                    )
                else:
                    sem_labels = [
                        f"S{d['iso_week']} {d['iso_year']}"
                        + (f"  (sauvé le {d['saved_at'][:10]})" if d.get("saved_at") else "")
                        for d in semaines_dispo
                    ]
                    col_sel, col_vend, col_gen_inv = st.columns([3, 2, 2])
                    with col_sel:
                        sel_idx = st.selectbox(
                            "Semaine", range(len(sem_labels)),
                            format_func=lambda i: sem_labels[i],
                            key=f"cr_inv_sem_{zone}",
                            label_visibility="collapsed",
                        )
                    with col_vend:
                        include_vend = st.checkbox(
                            "Inclure vendredi",
                            value=False,
                            key=f"cr_inv_vend_{zone}",
                        )
                    with col_gen_inv:
                        if st.button("🔄 Générer le texte", key=f"cr_inv_gen_{zone}",
                                     use_container_width=True):
                            with st.spinner("Chargement…"):
                                sel_doc = semaines_dispo[sel_idx]
                                inv_doc = load_inventaires_semaine(
                                    sel_doc["iso_year"], sel_doc["iso_week"]
                                )
                                done_records = inv_doc.get("done", [])
                                generated = _build_inventaire_cr_text(
                                    done_records,
                                    plannings_mongo, reappros_df, zone,
                                    include_vendredi=include_vend,
                                )
                            st.session_state[f"cr_inv_text_{zone}"] = generated
                            st.session_state[f"cr_txt_{titre}_{zone}"] = generated
                            st.rerun()

                inv_default = st.session_state.get(f"cr_inv_text_{zone}",
                                                    SECTION_DEFAULTS.get("Inventaire", ""))
                section_contents[titre] = st.text_area(
                    titre,
                    value=inv_default,
                    height=220,
                    key=f"cr_txt_{titre}_{zone}",
                    label_visibility="collapsed",
                )
            else:
                default_txt = SECTION_DEFAULTS.get(titre, "")
                section_contents[titre] = st.text_area(
                    titre,
                    value=default_txt,
                    height=120,
                    key=f"cr_txt_{titre}",
                    label_visibility="collapsed",
                )
        st.markdown("---")

    # --- Section "Autre" optionnelle ---
    col_chk_autre, _ = st.columns([3, 7])
    with col_chk_autre:
        include_autre = st.checkbox("Autre section", value=False, key="cr_chk_autre")
    autre_titre = ""
    autre_content = ""
    if include_autre:
        autre_titre = st.text_input(
            "Titre de la section",
            placeholder="Ex : Formations, RH, Matériel...",
            key="cr_autre_titre",
        )
        autre_content = st.text_area(
            "Contenu",
            height=120,
            key="cr_autre_txt",
            label_visibility="collapsed",
        )

    st.divider()

    # ── Génération ────────────────────────────────────────
    col_gen, _ = st.columns([2, 6])
    with col_gen:
        generer = st.button(
            "📋 Générer le mail",
            type="primary",
            use_container_width=True,
            key="cr_generer",
        )

    if generer:
        # Construire la liste ordonnée des sections cochées
        sections: list[tuple[str, str]] = []
        if include_da:
            sections.append(("Distributeur Automatique (DA)", da_content))
        for titre in ["Livraisons / Fournisseurs", "Tournées", "Inventaire"]:
            if titre in section_contents:
                sections.append((titre, section_contents[titre]))
        if include_autre and autre_titre.strip():
            sections.append((autre_titre.strip(), autre_content))

        mail_text = _generate_mail(zone, sections)
        st.session_state["cr_mail_result"] = mail_text
        st.session_state["cr_mail_objet"]  = objet

    # ── Affichage du résultat ─────────────────────────────
    if "cr_mail_result" in st.session_state:
        st.markdown("### 📬 Mail généré")
        st.markdown(
            f"**Objet :** `{st.session_state.get('cr_mail_objet', objet)}`"
        )
        st.text_area(
            "Contenu du mail",
            value=st.session_state["cr_mail_result"],
            height=400,
            key="cr_mail_display",
            label_visibility="collapsed",
        )
        # Bouton copier via st.code (sélectionnable facilement)
        with st.expander("📋 Version copiable (sélectionner tout avec Ctrl+A)"):
            st.code(st.session_state["cr_mail_result"], language=None)

    # ════════════════════════════════════════════════════
    # IMPORT RÉAPPROS (bas de page)
    # ════════════════════════════════════════════════════
    st.divider()
    st.markdown("### ⚙️ Mise à jour de la répartition des zones")
    st.caption("Importer le fichier `Reappro Guide.xlsx` pour mettre à jour les zones et réappros.")

    uploaded = st.file_uploader(
        "Reappro Guide.xlsx",
        type=["xlsx"],
        key="cr_reappro_uploader",
        label_visibility="collapsed",
    )

    if uploaded:
        col_imp, _ = st.columns([2, 6])
        with col_imp:
            if st.button(
                "📥 Mettre à jour la répartition",
                type="primary",
                use_container_width=True,
                key="cr_import_btn",
            ):
                with st.spinner("Import en cours..."):
                    try:
                        nb, zones_det = _import_reappros(uploaded.read())
                        st.success(
                            f"✅ **{nb}** réappros importés — "
                            f"zones détectées : {', '.join(zones_det)}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erreur lors de l'import : {e}")

    # ── Tableau récap réappros en base ───────────────────
    if not reappros_df.empty:
        with st.expander(f"👁️ Voir les {len(reappros_df)} réappros en base"):
            st.dataframe(
                reappros_df[["code", "prenom", "zone_geo", "zone", "responsable"]].rename(columns={
                    "code": "Code", "prenom": "Prénom",
                    "zone_geo": "Zone Géo", "zone": "Zone", "responsable": "Responsable",
                }),
                use_container_width=True,
                hide_index=True,
            )
