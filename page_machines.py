"""
Page Machines — Parc de distributeurs automatiques.

Permet de visualiser le parc de machines EN EXPLOITATION importé depuis
un export CSV. Les données sont persistées dans MongoDB (collection "machines").
Chaque import écrase intégralement les données précédentes.
"""

import io
import streamlit as st
import pandas as pd
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from mongo_storage import _get_client

# ────────────────────────────────────────────────────────
# CONSTANTES — pour ajouter une colonne : ajouter une entrée ici
# ────────────────────────────────────────────────────────

# Clé = nom exact de la colonne dans le CSV source
# Valeur = nom affiché dans le tableau Streamlit
COLUMNS_DISPLAY: dict[str, str] = {
    "Code":            "Code",
    "Code client":     "Code Client",
    "Client":          "Client",
    "Ville":           "Ville",
    "Code postal":     "Code Postal",
    "Modèle":          "Modèle",
    "Désignation":     "Désignation",
    "Approvisionneur": "Approvisionneur",
    "Date d'install":  "Date d'install",
    "Date création":   "Date création",
    "Statut":          "Statut",
}

# Colonnes exclues (non listées ci-dessus) :
# ID, Num. série, Adresse, Code modèle, Info accès, PLANOGRAMME, Commentaire

# Colonnes sur lesquelles proposer un filtre déroulant
# Pour ajouter un filtre : ajouter la clé CSV ici
FILTER_COLUMNS: list[str] = ["Approvisionneur", "Ville", "Modèle"]


# ────────────────────────────────────────────────────────
# MONGODB
# ────────────────────────────────────────────────────────

def _get_machines_col():
    """Retourne la collection MongoDB 'machines'."""
    client = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["machines"]


@st.cache_data(show_spinner=False, ttl=300)
def _load_from_mongo() -> pd.DataFrame | None:
    """Charge les machines depuis MongoDB. Retourne None si vide."""
    try:
        col = _get_machines_col()
        docs = list(col.find({}, {"_id": 0}))
        if not docs:
            return None
        return pd.DataFrame(docs)
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        st.error(f"❌ Connexion MongoDB impossible : {e}")
        return None
    except Exception as e:
        st.error(f"❌ Erreur MongoDB : {e}")
        return None


def _save_to_mongo(df: pd.DataFrame) -> int:
    """Efface la collection et insère les nouvelles données. Retourne le nb insérés."""
    col = _get_machines_col()
    col.delete_many({})
    # Remplacer NaT/NaN par None (MongoDB ne supporte pas ces types pandas)
    records = [
        {k: (None if pd.isnull(v) else v) for k, v in row.items()}
        for row in df.to_dict("records")
    ]
    if records:
        col.insert_many(records)
    return len(records)


# ────────────────────────────────────────────────────────
# PARSING & FILTRAGE
# ────────────────────────────────────────────────────────

def _parse_csv(raw_bytes: bytes) -> pd.DataFrame:
    """Parse le CSV export machines (séparateur ';', encodage latin-1 ou utf-8)."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                sep=";",
                encoding=enc,
                dtype=str,
            )
            # Nettoyer les noms de colonnes (espaces parasites)
            df.columns = [c.strip().strip('"') for c in df.columns]
            # Nettoyer les valeurs
            df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError("Impossible de décoder le fichier CSV (latin-1, utf-8-sig, utf-8 échoués).")


def _filter_machines(df: pd.DataFrame) -> pd.DataFrame:
    """
    Applique les règles métier :
    - Garde uniquement Statut == "EN EXPLOITATION"
    - Exclut les clients vides ou commençant par "dépot" / "depot"
    - Retourne uniquement les colonnes définies dans COLUMNS_DISPLAY
    """
    # Filtre statut
    if "Statut" in df.columns:
        df = df[df["Statut"].str.strip().str.upper() == "EN EXPLOITATION"]

    # Filtre code : exclure les machines dont le code se termine par "M2"
    if "Code" in df.columns:
        df = df[~df["Code"].fillna("").str.strip().str.upper().str.endswith("M2")]

    # Filtre client
    if "Client" in df.columns:
        client_col = df["Client"].fillna("").str.strip()
        mask_vide = client_col == ""
        mask_depot  = client_col.str.lower().str.startswith(("dépot", "depot"))
        mask_madrid = client_col.str.lower().str.contains("madrid", na=False)
        df = df[~(mask_vide | mask_depot | mask_madrid)]

    # Garder uniquement les colonnes voulues (dans l'ordre)
    cols_present = [c for c in COLUMNS_DISPLAY.keys() if c in df.columns]
    df = df[cols_present].copy()

    # Convertir les colonnes de dates en datetime pour un tri correct
    _DATE_FORMATS = ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y  %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"]
    for date_col in ["Date d'install", "Date création"]:
        if date_col in df.columns:
            parsed = None
            for fmt in _DATE_FORMATS:
                parsed = pd.to_datetime(df[date_col], format=fmt, errors="coerce")
                if parsed.notna().sum() > 0:
                    break
            df[date_col] = parsed

    return df.reset_index(drop=True)


# ────────────────────────────────────────────────────────
# RENDER
# ────────────────────────────────────────────────────────

def render():
    # Chargement des données depuis MongoDB
    df = _load_from_mongo()

    if df is not None and not df.empty:
        # ── KPIs ──────────────────────────────────────────
        nb_machines  = len(df)
        nb_villes    = df["Ville"].nunique() if "Ville" in df.columns else "-"
        nb_approvs   = df["Approvisionneur"].nunique() if "Approvisionneur" in df.columns else "-"

        k1, k2, k3, *_ = st.columns([1, 1, 1, 3])
        k1.metric("🖥️ Machines", nb_machines)
        k2.metric("📍 Villes",   nb_villes)
        k3.metric("👤 Approvs",  nb_approvs)

        st.divider()

        # ── Barre de recherche globale ────────────────────
        search = st.text_input(
            "🔍 Recherche",
            placeholder="Tapez un nom de ville, un code machine, un client…",
            key="machines_search",
            label_visibility="collapsed",
        )

        # ── Filtres déroulants ────────────────────────────
        filter_cols = [c for c in FILTER_COLUMNS if c in df.columns]
        if filter_cols:
            filter_widgets = st.columns(len(filter_cols))
            selected_filters: dict[str, str] = {}
            for col_widget, col_name in zip(filter_widgets, filter_cols):
                label = COLUMNS_DISPLAY.get(col_name, col_name)
                options = ["Tous"] + sorted(df[col_name].dropna().unique().tolist())
                selected_filters[col_name] = col_widget.selectbox(
                    label, options, key=f"filter_{col_name}"
                )

            # Appliquer les filtres déroulants (ET logique)
            df_filtered = df.copy()
            for col_name, val in selected_filters.items():
                if val != "Tous":
                    df_filtered = df_filtered[df_filtered[col_name] == val]
        else:
            df_filtered = df.copy()

        # Appliquer la recherche textuelle (cherche dans toutes les colonnes)
        if search.strip():
            term = search.strip().lower()
            mask = df_filtered.apply(
                lambda col: col.astype(str).str.lower().str.contains(term, na=False)
            ).any(axis=1)
            df_filtered = df_filtered[mask]

        st.caption(f"**{len(df_filtered)}** machine(s) affichée(s)")

        # ── Tableau ───────────────────────────────────────
        # Renommer les colonnes pour l'affichage
        cols_present = [c for c in COLUMNS_DISPLAY.keys() if c in df_filtered.columns]
        df_display = df_filtered[cols_present].rename(columns=COLUMNS_DISPLAY)

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            height=min(700, 38 + len(df_display) * 35),
        )

        # ── Export Excel ──────────────────────────────────────
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_display.to_excel(writer, sheet_name="Machines", index=False)
        buf.seek(0)
        st.download_button(
            label="⬇️ Exporter Excel",
            data=buf.getvalue(),
            file_name=f"machines_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    else:
        st.info("ℹ️ Aucune donnée disponible. Importez un fichier CSV via la section ci-dessous.")

    # ── Section import (en bas) ───────────────────────────
    st.divider()
    st.subheader("📥 Importer un export machines")
    st.warning("⚠️ L'import **écrase toutes les données existantes** et recharge le parc complet.")

    uploaded = st.file_uploader(
        "Fichier export CSV (séparateur `;`)",
        type=["csv"],
        key="machines_uploader",
        label_visibility="collapsed",
    )

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        import_btn = st.button(
            "📤 Importer",
            type="primary",
            use_container_width=True,
            disabled=(uploaded is None),
        )

    if import_btn and uploaded:
        with st.spinner("Import en cours..."):
            try:
                df_raw = _parse_csv(uploaded.read())
                df_new = _filter_machines(df_raw)

                # Comparaison avec les données existantes (clé = "Code")
                df_old = _load_from_mongo()
                if df_old is not None and not df_old.empty and "Code" in df_old.columns and "Code" in df_new.columns:
                    old_codes = set(df_old["Code"].dropna().astype(str))
                    new_codes = set(df_new["Code"].dropna().astype(str))
                    st.session_state["machines_import_summary"] = {
                        "total":      len(df_new),
                        "nouvelles":  len(new_codes - old_codes),
                        "supprimees": len(old_codes - new_codes),
                        "conservees": len(old_codes & new_codes),
                    }
                else:
                    st.session_state["machines_import_summary"] = {"total": len(df_new)}

                _save_to_mongo(df_new)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Erreur lors de l'import : {e}")

    # Affichage du résumé après rerun (persisté dans session_state)
    summary = st.session_state.get("machines_import_summary")
    if summary:
        st.success(f"✅ Import terminé — **{summary['total']}** machine(s) dans la base.")
        if "nouvelles" in summary:
            c1, c2, c3 = st.columns(3)
            c1.metric("🆕 Nouvelles",  summary["nouvelles"],  delta=f"+{summary['nouvelles']}"   if summary["nouvelles"]  else None)
            c2.metric("🗑️ Supprimées", summary["supprimees"], delta=f"-{summary['supprimees']}"  if summary["supprimees"] else None, delta_color="inverse")
            c3.metric("✅ Conservées",  summary["conservees"])
