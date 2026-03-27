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
# RENDER
# ────────────────────────────────────────────────────────

def render():
    reappros_df = _load_reappros_from_mongo()
    no_reappros = reappros_df.empty

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
