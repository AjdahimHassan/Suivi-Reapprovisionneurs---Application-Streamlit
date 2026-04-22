"""
Page No Audit / Sans Ventes

Deux onglets :
  - No Audit   : salles qui n'apparaissent PAS DU TOUT dans la télémétrie depuis X jours
  - Sans Ventes: salles qui apparaissent dans la télémétrie (auditées) mais sans aucune
                 vente (Price = 0, ou ≤ 1.99€ si option activée) depuis X jours

Source des salles : collection MongoDB "machines" (même base que la page Machines).
Source télémétrie : fichier CSV uploadé (col 0 = Salle, col 1 = Date, col 6 = Price).
"""

import io
import datetime

import streamlit as st
import pandas as pd

from mongo_storage import _get_client


# ────────────────────────────────────────────────────────
# MONGODB — salles
# ────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=300)
def _load_plannings_from_mongo() -> dict:
    """Retourne {employe: {jour: [client, ...]}} depuis la collection plannings."""
    try:
        client = _get_client()
        db_name = st.secrets["mongo"]["db_name"]
        col = client[db_name]["plannings"]
        docs = list(col.find({}, {"_id": 0, "employe": 1, "planning": 1}))
        return {doc["employe"]: doc["planning"] for doc in docs}
    except Exception:
        return {}


def _find_planning_for_appro(approvisionneur: str, plannings: dict) -> dict | None:
    if not approvisionneur:
        return None
    if approvisionneur in plannings:
        return plannings[approvisionneur]
    appro_lower = approvisionneur.strip().lower()
    for employe, planning in plannings.items():
        if employe.strip().lower() == appro_lower:
            return planning
    return None


def _get_next_passage_date(salle: str, approvisionneur: str, plannings: dict) -> str | None:
    """Retourne 'DD/MM' du prochain passage prévu pour cette salle selon le planning."""
    planning = _find_planning_for_appro(approvisionneur, plannings)
    if not planning:
        return None

    JOUR_TO_WEEKDAY = {"Lundi": 0, "Mardi": 1, "Mercredi": 2, "Jeudi": 3, "Vendredi": 4}
    scheduled_weekdays = set()
    for jour, salles_list in planning.items():
        weekday = JOUR_TO_WEEKDAY.get(jour)
        if weekday is None:
            continue
        for s in salles_list:
            raw = s[0] if isinstance(s, list) else s
            # Le planning stocke "CODE - Nom client" ; on compare sur le nom seul
            client_name = raw.split(" - ", 1)[1].strip() if " - " in raw else raw.strip()
            if client_name == salle:
                scheduled_weekdays.add(weekday)
                break

    if not scheduled_weekdays:
        return None

    today = datetime.date.today()
    for delta in range(1, 8):
        candidate = today + datetime.timedelta(days=delta)
        if candidate.weekday() in scheduled_weekdays:
            return candidate.strftime("%d/%m")
    return None


@st.cache_data(show_spinner=False, ttl=300)
def _load_salles_from_mongo() -> pd.DataFrame:
    """
    Retourne un DataFrame {Client, Code, Approvisionneur} depuis la collection 'machines'.
    Client = nom affiché / clé de matching avec la télémétrie.
    """
    try:
        client = _get_client()
        db_name = st.secrets["mongo"]["db_name"]
        col = client[db_name]["machines"]
        docs = list(col.find({}, {"_id": 0, "Client": 1, "Code": 1, "Approvisionneur": 1}))
        df = pd.DataFrame(docs)
        if df.empty:
            return df
        for c in ["Client", "Code", "Approvisionneur"]:
            if c not in df.columns:
                df[c] = ""
        return df.fillna("").drop_duplicates(subset=["Client"])
    except Exception as e:
        st.error(f"❌ Impossible de charger les salles depuis MongoDB : {e}")
        return pd.DataFrame()


# ────────────────────────────────────────────────────────
# MONGODB — incidents
# ────────────────────────────────────────────────────────

def _get_incidents_col():
    client = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["incidents"]


def _load_incidents() -> dict:
    """Retourne {"actif": [...], "resolu": [...]} depuis la collection incidents."""
    try:
        col = _get_incidents_col()
        actifs  = list(col.find({"status": "actif"},  {"_id": 0}))
        resolus = list(col.find({"status": "resolu"}, {"_id": 0}))
        return {"actif": actifs, "resolu": resolus}
    except Exception:
        return {"actif": [], "resolu": []}


def _load_known_salles(type_: str) -> set:
    """Retourne les salles qui ont déjà eu un incident (actif ou résolu) pour ce type."""
    try:
        col = _get_incidents_col()
        docs = list(col.find({"type": type_}, {"salle": 1, "_id": 0}))
        return {doc["salle"] for doc in docs}
    except Exception:
        return set()


def _save_commentaires(rows: list[dict], type_: str):
    """
    Upsert des commentaires pour chaque ligne avec commentaire non vide.
    rows = liste de dicts avec clés "Salle", "Commentaire" et optionnellement "since_date".
    since_date = date métier (dernière apparition ou dernière vente).
    """
    col = _get_incidents_col()
    now = datetime.datetime.utcnow()
    for row in rows:
        commentaire = (row.get("Commentaire") or "").strip()
        salle = row.get("Salle", "")
        if not commentaire or not salle:
            continue
        since_date = (row.get("since_date") or "").strip()
        existing = col.find_one({"salle": salle, "type": type_, "status": "actif"})
        if existing:
            col.update_one(
                {"salle": salle, "type": type_, "status": "actif"},
                {"$set": {"commentaire": commentaire, "since_date": since_date}},
            )
        else:
            col.insert_one({
                "salle":       salle,
                "type":        type_,
                "commentaire": commentaire,
                "since_date":  since_date,
                "created_at":  now,
                "resolved_at": None,
                "status":      "actif",
            })


def _auto_resolve(current_salles: list[str], type_: str) -> int:
    """
    Marque comme résolus les incidents actifs du type_ dont la salle
    n'est plus dans current_salles (problème résolu).
    Retourne le nombre de résolutions effectuées.
    """
    col = _get_incidents_col()
    now = datetime.datetime.utcnow()
    actifs = list(col.find({"type": type_, "status": "actif"}, {"salle": 1}))
    current_set = set(current_salles)
    resolved = 0
    for inc in actifs:
        if inc["salle"] not in current_set:
            col.update_one(
                {"_id": inc["_id"]},
                {"$set": {"status": "resolu", "resolved_at": now}},
            )
            resolved += 1
    return resolved


def _resolve_on_delete(salles: list[str]):
    """Quand on supprime des salles de machines, on résout leurs incidents actifs."""
    col = _get_incidents_col()
    now = datetime.datetime.utcnow()
    col.update_many(
        {"salle": {"$in": salles}, "status": "actif"},
        {"$set": {"status": "resolu", "resolved_at": now}},
    )


# ────────────────────────────────────────────────────────
# PARSING TÉLÉMÉTRIE
# ────────────────────────────────────────────────────────

def _parse_telemetry(raw_bytes: bytes) -> pd.DataFrame:
    """
    Parse le CSV de télémétrie.
    Colonnes utilisées : col 0 = Salle, col 1 = Date, col 6 = Price
    """
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                sep=";",
                decimal=",",
                encoding=enc,
                low_memory=False,
                header=0,
            )
            df = df.rename(columns={
                df.columns[0]: "Salle",
                df.columns[1]: "Date",
                df.columns[6]: "Price",
            })
            df["Salle"] = df["Salle"].astype(str).str.strip()
            # Normalise les espaces multiples dans la colonne date avant parsing
            date_str = df["Date"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
            df["Date"] = pd.to_datetime(
                date_str, format="%d/%m/%Y %H:%M:%S", errors="coerce"
            )
            # Fallback pour les lignes non parsées (format sans secondes, etc.)
            mask = df["Date"].isna()
            if mask.any():
                df.loc[mask, "Date"] = pd.to_datetime(
                    date_str[mask], dayfirst=True, errors="coerce"
                )
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0)
            return df[["Salle", "Date", "Price"]].dropna(subset=["Date"])
        except UnicodeDecodeError:
            continue
    raise ValueError("Impossible de décoder le fichier de télémétrie.")


# ────────────────────────────────────────────────────────
# LOGIQUE MÉTIER
# ────────────────────────────────────────────────────────

def _compute_no_audit(
    salles_df: pd.DataFrame,
    telemetry: pd.DataFrame,
) -> pd.DataFrame:
    """
    Salles absentes de la télémétrie à J-1 (hier).
    Filtre aussi les salles où jours_depuis_audit < 0 (auditées depuis hier → OK).
    """
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
    telem_yesterday = telemetry[telemetry["Date"].dt.date == yesterday]
    salles_vues_hier = set(telem_yesterday["Salle"].unique())
    last_seen = telemetry.groupby("Salle")["Date"].max()
    ref = datetime.datetime.combine(yesterday, datetime.time())

    # Lookup rapide code / approvisionneur
    meta = salles_df.set_index("Client")[["Code", "Approvisionneur"]].to_dict("index")

    rows = []
    for _, row in salles_df.iterrows():
        salle = row["Client"]
        if salle in salles_vues_hier:
            continue  # auditée hier → OK
        last = last_seen.get(salle, pd.NaT)
        jours = (ref - last).days if not pd.isna(last) else None
        if jours is not None and jours < 0:
            continue  # auditée après hier (données du jour) → OK
        rows.append({
            "Code machine":        row.get("Code", ""),
            "Approvisionneur":     row.get("Approvisionneur", ""),
            "Salle":               salle,
            "Dernière apparition": last.strftime("%d/%m/%Y %H:%M") if not pd.isna(last) else "Jamais",
            "Jours depuis audit":  jours,
            "Commentaire":         "",
        })
    return pd.DataFrame(rows)


def _compute_sans_ventes(
    salles_df: pd.DataFrame,
    telemetry: pd.DataFrame,
    seuil: float,
) -> pd.DataFrame:
    """
    Salles auditées hier (J-1) mais sans aucune vente > seuil ce jour-là.
    Filtre les lignes où jours_sans_vente < 0 (vente récente → OK).
    """
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
    telem_yesterday = telemetry[telemetry["Date"].dt.date == yesterday]
    salles_vues_hier = set(telem_yesterday["Salle"].unique())
    avec_ventes_hier = set(
        telem_yesterday[telem_yesterday["Price"] > seuil]["Salle"].unique()
    )
    salles_set = set(salles_df["Client"].tolist())
    sans_ventes_hier = (salles_vues_hier - avec_ventes_hier) & salles_set
    ref = datetime.datetime.combine(yesterday, datetime.time())

    rows = []
    for _, row in salles_df[salles_df["Client"].isin(sans_ventes_hier)].iterrows():
        salle = row["Client"]
        # Dernière vraie vente dans toute l'historique
        last_vente = telemetry[
            (telemetry["Salle"] == salle) & (telemetry["Price"] > seuil)
        ]["Date"].max()
        jours_sans = (ref - last_vente).days if not pd.isna(last_vente) else None
        if jours_sans is not None and jours_sans < 0:
            continue  # vente récente après hier → OK
        rows.append({
            "Code machine":        row.get("Code", ""),
            "Approvisionneur":     row.get("Approvisionneur", ""),
            "Salle":               salle,
            "Dernière vente":      last_vente.strftime("%d/%m/%Y %H:%M") if not pd.isna(last_vente) else "Jamais",
            "Jours sans vente":    jours_sans,
            "Commentaire":         "",
        })
    return pd.DataFrame(rows)


def _inject_commentaires(df: pd.DataFrame, type_: str) -> pd.DataFrame:
    """Pré-remplit la colonne Commentaire depuis les incidents actifs en base."""
    incidents = _load_incidents()["actif"]
    mapping = {
        inc["salle"]: inc["commentaire"]
        for inc in incidents
        if inc.get("type") == type_
    }
    if mapping:
        df["Commentaire"] = df["Salle"].map(mapping).fillna("").combine_first(df["Commentaire"])
    return df


# ────────────────────────────────────────────────────────
# EXPORT EXCEL
# ────────────────────────────────────────────────────────

def _build_rapport_excel(df_audit: pd.DataFrame, df_ventes: pd.DataFrame) -> bytes:
    """Génère un fichier Excel avec deux feuilles : No Audit et Sans Ventes (commentaires inclus)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_audit.to_excel(writer, sheet_name="No Audit", index=False)
        df_ventes.to_excel(writer, sheet_name="Sans Ventes", index=False)
    return buf.getvalue()


# ────────────────────────────────────────────────────────
# HELPERS UI
# ────────────────────────────────────────────────────────

def _render_table_with_comments(
    df: pd.DataFrame, type_: str, key_prefix: str, plannings: dict | None = None
):
    """
    data_editor propre + barre d'actions rapides (multiselect → Passage / WA) en dessous.
    """
    if plannings is None:
        plannings = {}

    date_col  = "Dernière apparition" if type_ == "no_audit" else "Dernière vente"
    jours_col = "Jours depuis audit"  if type_ == "no_audit" else "Jours sans vente"
    working_key = f"{key_prefix}_working_df"
    version_key = f"{key_prefix}_version"

    if working_key not in st.session_state:
        st.session_state[working_key] = df.copy()
        st.session_state[version_key] = 0

    working_df = st.session_state[working_key]
    known_salles = _load_known_salles(type_)

    # Ajoute colonne Tag pour affichage (non stockée dans working_df)
    display_df = working_df.copy()
    display_df.insert(
        0, "Tag",
        display_df["Salle"].apply(lambda s: "🔵 Connu" if s in known_salles else "🟢 Nouveau")
    )

    # ── Table ─────────────────────────────────────────────
    locked = [c for c in display_df.columns if c != "Commentaire"]
    col_cfg = {c: st.column_config.Column(disabled=True) for c in locked}
    col_cfg["Commentaire"] = st.column_config.TextColumn(
        "Commentaire", help="Saisissez la raison du problème", max_chars=300
    )
    col_cfg["Tag"] = st.column_config.TextColumn("Tag", disabled=True, width="small")
    if jours_col in display_df.columns:
        col_cfg[jours_col] = st.column_config.NumberColumn(jours_col, disabled=True, format="%d j")

    edited_display = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=min(700, 38 + len(display_df) * 35),
        column_config=col_cfg,
        key=f"{key_prefix}_editor_{st.session_state[version_key]}",
    )
    # On retire la colonne Tag pour garder working_df propre
    edited = edited_display.drop(columns=["Tag"], errors="ignore")

    # ── Actions rapides ───────────────────────────────────
    st.markdown("**Actions rapides sur les commentaires :**")

    new_salles = [s for s in working_df["Salle"].tolist() if s not in known_salles]
    sel_key = f"{key_prefix}_action_sel"
    col_newbtn, _ = st.columns([2, 5])
    with col_newbtn:
        if st.button(
            "🟢 Sélectionner toutes les nouvelles",
            key=f"{key_prefix}_btn_select_new",
            use_container_width=True,
            disabled=not new_salles,
        ):
            st.session_state[sel_key] = new_salles
            st.rerun()

    col_sel, col_p, col_wa, col_save = st.columns([3.5, 1.2, 0.9, 1.3])

    with col_sel:
        tag_map = {s: ("🔵" if s in known_salles else "🟢") for s in working_df["Salle"].tolist()}
        selected_salles = st.multiselect(
            "Salles",
            options=working_df["Salle"].tolist(),
            format_func=lambda s: f"{tag_map.get(s, '')} {s}",
            placeholder="Sélectionner des salles…",
            label_visibility="collapsed",
            key=sel_key,
        )

    with col_p:
        if st.button(
            "📅 Passage",
            key=f"{key_prefix}_btn_passage",
            use_container_width=True,
            disabled=not selected_salles,
        ):
            new_df = edited.copy()
            for i, row in new_df.iterrows():
                if row["Salle"] in selected_salles:
                    next_date = _get_next_passage_date(
                        row["Salle"], row.get("Approvisionneur", ""), plannings
                    )
                    if next_date:
                        new_df.at[i, "Commentaire"] = f"Passage le {next_date}"
            st.session_state[working_key] = new_df
            st.session_state[version_key] += 1
            st.rerun()

    with col_wa:
        if st.button(
            "💬 WA",
            key=f"{key_prefix}_btn_wa",
            use_container_width=True,
            disabled=not selected_salles,
        ):
            new_df = edited.copy()
            for i, row in new_df.iterrows():
                if row["Salle"] in selected_salles:
                    new_df.at[i, "Commentaire"] = "À voir sur WhatsApp"
            st.session_state[working_key] = new_df
            st.session_state[version_key] += 1
            st.rerun()

    with col_save:
        if st.button("💾 Sauvegarder", key=f"{key_prefix}_save", use_container_width=True):
            rows_to_save = [
                {
                    "Salle":       row["Salle"],
                    "Commentaire": row.get("Commentaire", ""),
                    "since_date":  row.get(date_col, ""),
                }
                for _, row in edited.iterrows()
            ]
            _save_commentaires(rows_to_save, type_)
            st.session_state[working_key] = edited.copy()
            st.toast("✅ Commentaires sauvegardés.")

    # ── Message WhatsApp ──────────────────────────────────
    msg_state_key = f"{key_prefix}_wa_messages"
    col_msg, _ = st.columns([2, 5])
    with col_msg:
        if st.button(
            "📲 Générer message WhatsApp",
            key=f"{key_prefix}_btn_msg_wa",
            use_container_width=True,
            disabled=not selected_salles,
        ):
            probleme = "pas de remontée de télémétrie" if type_ == "no_audit" else "pas de ventes"
            messages = []
            for _, row in edited.iterrows():
                if row["Salle"] in selected_salles:
                    since_raw = row.get(date_col, "—") or "—"
                    since = since_raw.split(" ")[0] if since_raw != "—" else "—"
                    messages.append(
                        f"Bonjour @ stp j'ai un souci avec la salle {row['Salle']}, "
                        f"{probleme} depuis le {since}"
                    )
            st.session_state[msg_state_key] = "\n\n".join(messages)

    if st.session_state.get(msg_state_key):
        st.text_area(
            "💬 Message(s) à copier-coller sur WhatsApp",
            value=st.session_state[msg_state_key],
            height=min(300, 80 + st.session_state[msg_state_key].count("\n\n") * 80),
            key=f"{key_prefix}_wa_textarea",
        )


def _render_delete_section(df: pd.DataFrame, key_prefix: str):
    """Section suppression de salles de la base machines."""
    st.divider()
    st.markdown("**🗑️ Supprimer des salles de la base**")
    salles_a_suppr = st.multiselect(
        "Sélectionner les salles à supprimer",
        options=df["Salle"].tolist(),
        key=f"salles_a_supprimer_{key_prefix}",
        label_visibility="collapsed",
    )
    if salles_a_suppr:
        if st.button(
            f"🗑️ Supprimer {len(salles_a_suppr)} salle(s)",
            type="primary",
            key=f"btn_suppr_{key_prefix}",
        ):
            try:
                client = _get_client()
                db_name = st.secrets["mongo"]["db_name"]
                col = client[db_name]["machines"]
                col.delete_many({"Client": {"$in": salles_a_suppr}})
                _resolve_on_delete(salles_a_suppr)
                _load_salles_from_mongo.clear()
                st.success(f"✅ {len(salles_a_suppr)} salle(s) supprimée(s) de la base.")
                st.session_state.pop("no_audit_result", None)
                st.session_state.pop("sans_ventes_result", None)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Erreur lors de la suppression : {e}")


# ────────────────────────────────────────────────────────
# RENDER
# ────────────────────────────────────────────────────────

def render():
    # ── Upload télémétrie ─────────────────────────────────
    st.markdown("### 📂 Fichier de télémétrie")
    uploaded = st.file_uploader(
        "CSV télémétrie (séparateur `;`)",
        type=["csv"],
        key="telemetry_uploader",
        label_visibility="collapsed",
    )

    if uploaded is None:
        st.info("ℹ️ Déposez le fichier de télémétrie CSV pour lancer l'analyse.")
        _render_bottom_sections()
        return

    with st.spinner("Chargement de la télémétrie..."):
        try:
            telemetry = _parse_telemetry(uploaded.read())
        except Exception as e:
            st.error(f"❌ Erreur lors du chargement : {e}")
            return

    salles_df = _load_salles_from_mongo()
    if salles_df.empty:
        st.error("❌ Aucune salle trouvée en base. Importez d'abord le parc machines.")
        return

    plannings = _load_plannings_from_mongo()

    st.success(
        f"✅ Télémétrie chargée — **{len(telemetry):,}** lignes | "
        f"**{telemetry['Salle'].nunique()}** salles distinctes"
    )
    st.divider()

    tab_no_audit, tab_sans_ventes = st.tabs(["🔕 No Audit", "📉 Sans Ventes"])

    # ════════════════════════════════════════════════════
    # ONGLET NO AUDIT
    # ════════════════════════════════════════════════════
    yesterday_str = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%d/%m/%Y")

    with tab_no_audit:
        st.markdown("Salles **absentes de la télémétrie hier (J-1)** — machine non auditée.")
        st.info(f"📅 Référence : J-1 = **{yesterday_str}**")

        col_btn, _ = st.columns([1, 5])
        with col_btn:
            calc_audit = st.button("🔍 Calculer", key="btn_no_audit", use_container_width=True)

        if calc_audit:
            st.session_state.pop("no_audit_working_df", None)
            st.session_state.pop("no_audit_version", None)
            df_audit = _compute_no_audit(salles_df, telemetry)
            df_audit = _inject_commentaires(df_audit, "no_audit")
            st.session_state["no_audit_result"] = df_audit
            resolved = _auto_resolve(df_audit["Salle"].tolist(), "no_audit")
            if resolved:
                st.toast(f"✅ {resolved} salle(s) marquée(s) comme réparée(s) !")

        df_audit = st.session_state.get("no_audit_result")
        if df_audit is not None:
            st.caption(f"**{len(df_audit)}** salle(s) absente(s) hier ({yesterday_str})")
            if not df_audit.empty:
                _render_table_with_comments(df_audit, "no_audit", "no_audit", plannings)
                _render_delete_section(df_audit, "audit")
            else:
                st.success("✅ Toutes les salles sont apparues dans la télémétrie hier.")

    # ════════════════════════════════════════════════════
    # ONGLET SANS VENTES
    # ════════════════════════════════════════════════════
    with tab_sans_ventes:
        st.markdown("Salles **auditées hier (J-1)** mais **sans aucune vente** ce jour-là.")
        st.info(f"📅 Référence : J-1 = **{yesterday_str}**")

        col_check, col_btn2, _ = st.columns([1.5, 1, 3.5])
        with col_check:
            seuil_actif = st.checkbox("Exclure ≤ 1.99€", value=False, key="seuil_check")
        with col_btn2:
            st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
            calc_ventes = st.button("🔍 Calculer", key="btn_sans_ventes", use_container_width=True)

        seuil = 1.99 if seuil_actif else 0.0

        if calc_ventes:
            st.session_state.pop("sans_ventes_working_df", None)
            st.session_state.pop("sans_ventes_version", None)
            df_ventes = _compute_sans_ventes(salles_df, telemetry, seuil)
            df_ventes = _inject_commentaires(df_ventes, "sans_ventes")
            st.session_state["sans_ventes_result"] = df_ventes
            resolved = _auto_resolve(df_ventes["Salle"].tolist(), "sans_ventes")
            if resolved:
                st.toast(f"✅ {resolved} salle(s) marquée(s) comme réparée(s) !")

        df_ventes = st.session_state.get("sans_ventes_result")
        if df_ventes is not None:
            label_seuil = f" (seuil > {seuil}€)" if seuil_actif else " (ventes à 0)"
            st.caption(
                f"**{len(df_ventes)}** salle(s) auditée(s) hier sans vente{label_seuil}"
            )
            if not df_ventes.empty:
                _render_table_with_comments(df_ventes, "sans_ventes", "sans_ventes", plannings)
                _render_delete_section(df_ventes, "ventes")
            else:
                st.success("✅ Toutes les salles auditées hier ont enregistré des ventes.")

    # ════════════════════════════════════════════════════
    # EXPORT RAPPORT
    # ════════════════════════════════════════════════════
    df_audit_exp  = st.session_state.get("no_audit_result",    pd.DataFrame())
    df_ventes_exp = st.session_state.get("sans_ventes_result", pd.DataFrame())
    if not df_audit_exp.empty or not df_ventes_exp.empty:
        st.divider()
        col_dl, _ = st.columns([1.5, 5])
        with col_dl:
            excel_bytes = _build_rapport_excel(df_audit_exp, df_ventes_exp)
            st.download_button(
                "📊 Exporter Rapport Excel",
                data=excel_bytes,
                file_name=f"rapport_audit_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # ════════════════════════════════════════════════════
    # SECTIONS BASSES
    # ════════════════════════════════════════════════════
    st.divider()
    _render_bottom_sections()


def _render_bottom_sections():
    """Sections en bas de page : commentaires actifs + historique résolu."""
    incidents = _load_incidents()

    # ── Commentaires actifs ───────────────────────────────
    actifs = incidents["actif"]
    if actifs:
        with st.expander(f"📋 Commentaires actifs ({len(actifs)})", expanded=True):
            rows = []
            for inc in actifs:
                # "Depuis" = date métier (dernière apparition / dernière vente)
                # fallback sur created_at pour les anciens incidents sans since_date
                since = inc.get("since_date") or (
                    inc.get("created_at").strftime("%d/%m/%Y")
                    if inc.get("created_at") else "—"
                )
                rows.append({
                    "Salle":       inc.get("salle", ""),
                    "Type":        "No Audit" if inc.get("type") == "no_audit" else "Sans Ventes",
                    "Commentaire": inc.get("commentaire", ""),
                    "Depuis":      since or "—",
                })
            df_actifs = pd.DataFrame(rows)
            st.dataframe(df_actifs, use_container_width=True, hide_index=True)

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_actifs.to_excel(writer, sheet_name="Commentaires actifs", index=False)
            buf.seek(0)
            st.download_button(
                label="⬇️ Exporter Excel",
                data=buf.getvalue(),
                file_name=f"commentaires_actifs_{datetime.date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # ── Historique résolus ────────────────────────────────
    resolus = incidents["resolu"]
    if resolus:
        with st.expander(f"📜 Historique des problèmes résolus ({len(resolus)})", expanded=False):
            rows = []
            for inc in resolus:
                created  = inc.get("created_at")
                resolved = inc.get("resolved_at")
                rows.append({
                    "Salle":       inc.get("salle", ""),
                    "Type":        "No Audit" if inc.get("type") == "no_audit" else "Sans Ventes",
                    "Commentaire": inc.get("commentaire", ""),
                    "Créé le":     created.strftime("%d/%m/%Y")  if created  else "—",
                    "Résolu le":   resolved.strftime("%d/%m/%Y") if resolved else "—",
                })
            df_resolus = pd.DataFrame(rows)
            st.dataframe(df_resolus, use_container_width=True, hide_index=True)
