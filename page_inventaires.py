"""
Page Inventaires — Analyse des inventaires machines par réappro.

Logique :
  - Upload d'un export CSV d'inventaires (format chargement logiciel)
  - Détection automatique du type de machine (BF Simple / BF Double / FP IDF / FP Province / WUF)
    via le suffixe M1/M2 de Stock Origine et le préfixe du Code client
  - Comparaison du montant HT inventorié aux seuils min/max par type
  - Affichage des produits manquants (quantité = 0)
  - Vue globale + vue par réappro + vue par machine

Seuils :
  BF Simple     : min 380 € — max 480 €
  BF Double     : min 700 € — max 957,50 €
  FP IDF        : min 300 € — max 409 €
  FP Province   : min 300 € — max 412 €
  WUF / Autre   : min 280 € — max 400 €
"""

import io
import pandas as pd
import streamlit as st
import datetime

# ─────────────────────────────────────────
# Seuils par type de machine
# ─────────────────────────────────────────
SEUILS = {
    "BF Simple":     {"min": 380,  "max": 480.00,  "label": "Basic Fit Simple"},
    "BF Double":     {"min": 700,  "max": 957.50,  "label": "Basic Fit Double"},
    "FP IDF":        {"min": 300,  "max": 409.00,  "label": "Fitness Park IDF"},
    "FP Province":   {"min": 300,  "max": 412.00,  "label": "Fitness Park Province"},
    "WUF":           {"min": 280,  "max": 400.00,  "label": "WUF"},
    "Autre":         {"min": 280,  "max": 450.00,  "label": "Autre"},
}

COLOR_OK      = "#1E7E34"
COLOR_BAD     = "#C0392B"
COLOR_OVER    = "#E67E22"
COLOR_UNKNOWN = "#555555"
WHITE         = "#FFFFFF"

IDF_RESSOURCES = {"RIDF1", "RIDF2", "RIDF3", "RIDF4", "RIDF5", "RIDF6", "RIDF7", "RIDF8"}


# ─────────────────────────────────────────
# Détection type de machine
# ─────────────────────────────────────────
PRODUITS_DOUBLE = {"VOLVICEXOTIC50CL", "VOLVICFRAISE50CL"}


def _detect_doubles(df: pd.DataFrame) -> set:
    """
    Retourne l'ensemble des Num Piece correspondant à des machines doubles.
    Critère : présence de Volvic dans l'inventaire (VOLVICEXOTIC50CL ou VOLVICFRAISE50CL).
    Le suffixe M2 dans Stock Origine est un signal secondaire mais incomplet.
    """
    mask = df["Code produit"].isin(PRODUITS_DOUBLE)
    return set(df.loc[mask, "Num Piece"].unique())


def _get_machine_type(code_client: str, ressource: str, is_double: bool) -> str:
    """Retourne la clé de type machine (clé dans SEUILS)."""
    code = str(code_client).upper()
    is_idf = str(ressource).upper() in {r.upper() for r in IDF_RESSOURCES}

    if code.startswith("BF") or code.startswith("CTF"):
        return "BF Double" if is_double else "BF Simple"
    elif code.startswith("FP") or code.startswith("FT"):
        return "FP IDF" if is_idf else "FP Province"
    elif code.startswith("WU"):
        return "WUF"
    else:
        return "Autre"


def _get_status(total: float, machine_type: str) -> dict:
    """Retourne {'emoji', 'label', 'color'} selon le total et le type."""
    if machine_type not in SEUILS:
        return {"emoji": "❓", "label": "Non classifié", "color": COLOR_UNKNOWN}
    s = SEUILS[machine_type]
    if total < s["min"]:
        pct = round((total / s["min"]) * 100, 1)
        return {
            "emoji": "🔴",
            "label": f"Mal fait ({pct}% du min)",
            "color": COLOR_BAD,
            "pct_min": pct,
        }
    elif total > s["max"]:
        return {"emoji": "🟠", "label": "Au-dessus du max", "color": COLOR_OVER}
    else:
        return {"emoji": "🟢", "label": "OK", "color": COLOR_OK}


# ─────────────────────────────────────────
# Parsing du fichier export inventaires
# ─────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _parse_inventaire(raw_bytes: bytes) -> pd.DataFrame:
    """
    Parse le CSV export inventaires et retourne un DataFrame enrichi
    avec type_machine, statut, etc.
    """
    df = pd.read_csv(
        io.BytesIO(raw_bytes),
        sep=";",
        encoding="utf-8-sig",
        dtype=str,
    )

    # Nettoyage colonnes obligatoires
    required = ["Num Piece", "Date", "Stock Origine", "Code client", "Nom client",
                "Ressource", "Code produit", "Libellé produit", "Quantité", "Montant HT"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier : {', '.join(missing)}")

    df["Montant HT"]  = df["Montant HT"].str.replace(",", ".", regex=False)
    df["Montant HT"]  = pd.to_numeric(df["Montant HT"], errors="coerce").fillna(0.0)
    df["Quantité"]    = pd.to_numeric(df["Quantité"],   errors="coerce").fillna(0)

    # Filtrer uniquement les lignes Inventaire (au cas où d'autres types seraient présents)
    if "Type tâche" in df.columns:
        df = df[df["Type tâche"].str.strip().str.lower() == "inventaire"].copy()

    # Détection doubles via présence de Volvic dans l'inventaire
    doubles_pieces = _detect_doubles(df)
    df["is_double"] = df["Num Piece"].isin(doubles_pieces)

    # Type machine (calculé une fois par inventaire, réappliqué sur toutes les lignes)
    df["machine_type"] = df.apply(
        lambda r: _get_machine_type(r["Code client"], r["Ressource"], r["is_double"]),
        axis=1,
    )

    return df


def _build_inv_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construit un résumé par inventaire (1 ligne = 1 inventaire / 1 machine).
    """
    # On prend le type machine de la première ligne (cohérent pour un même Num Piece)
    type_per_inv = df.groupby("Num Piece")["machine_type"].first()

    agg = df.groupby(
        ["Num Piece", "Ressource", "Code client", "Nom client", "Stock Origine", "Date"]
    ).agg(
        total=("Montant HT",  "sum"),
        nb_produits_ref=("Code produit", "nunique"),
        nb_produits_vides=("Quantité", lambda q: (q == 0).sum()),
        produits_vides=("Libellé produit", lambda x: list(x[df.loc[x.index, "Quantité"] == 0])),
    ).reset_index()

    agg["machine_type"] = agg["Num Piece"].map(type_per_inv)
    agg["seuil_min"] = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("min"))
    agg["seuil_max"] = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("max"))

    status_info = agg.apply(lambda r: _get_status(r["total"], r["machine_type"]), axis=1)
    agg["statut_emoji"]  = status_info.apply(lambda d: d["emoji"])
    agg["statut_label"]  = status_info.apply(lambda d: d["label"])
    agg["statut_color"]  = status_info.apply(lambda d: d["color"])
    agg["ecart_min"]     = (agg["total"] - agg["seuil_min"]).round(2)
    agg["type_label"]    = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("label", t))

    return agg.sort_values(["Ressource", "Nom client"])


def _missing_products_for_inv(df_raw: pd.DataFrame, num_piece: str) -> list[dict]:
    """Retourne la liste des produits à 0 pour un inventaire donné."""
    sub = df_raw[df_raw["Num Piece"] == num_piece]
    empty = sub[sub["Quantité"] == 0]
    return empty[["Code produit", "Libellé produit"]].drop_duplicates().to_dict("records")


# ─────────────────────────────────────────
# Render principal
# ─────────────────────────────────────────
def render():
    st.markdown("### 📂 Déposer le fichier export inventaires (CSV)")
    uploaded = st.file_uploader(
        "Export inventaires CSV",
        type=["csv"],
        key="inv_uploader",
        label_visibility="collapsed",
    )

    if uploaded is None:
        st.info(
            "**Format attendu :** export CSV du logiciel de gestion (encodage UTF-8 BOM, séparateur `;`). "
            "Colonnes nécessaires : `Num Piece`, `Date`, `Type tâche`, `Stock Origine`, "
            "`Code client`, `Nom client`, `Ressource`, `Code produit`, `Libellé produit`, "
            "`Quantité`, `Montant HT`."
        )
        _show_thresholds_legend()
        return

    # ── Parsing ──────────────────────────────────────────
    try:
        with st.spinner("Analyse du fichier…"):
            df_raw = _parse_inventaire(uploaded.read())
        st.success(f"✅ {df_raw['Num Piece'].nunique()} inventaires chargés — "
                   f"{df_raw['Ressource'].nunique()} réappros — "
                   f"{len(df_raw)} lignes produits")
    except Exception as e:
        st.error(f"❌ Erreur de parsing : {e}")
        return

    summary = _build_inv_summary(df_raw)

    # ── KPIs globaux ─────────────────────────────────────
    st.divider()
    nb_ok    = (summary["statut_emoji"] == "🟢").sum()
    nb_bad   = (summary["statut_emoji"] == "🔴").sum()
    nb_over  = (summary["statut_emoji"] == "🟠").sum()
    nb_total = len(summary)
    taux_ok  = round(nb_ok / nb_total * 100, 1) if nb_total else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("📋 Inventaires",    nb_total)
    k2.metric("✅ OK",             nb_ok,   delta=f"{taux_ok}%")
    k3.metric("🔴 Mal faits",      nb_bad,
              delta=f"-{round(nb_bad/nb_total*100,1)}%" if nb_total else None,
              delta_color="inverse")
    k4.metric("🟠 Au-dessus max",  nb_over)
    k5.metric("📅 Période",
              f"{df_raw['Date'].min()} → {df_raw['Date'].max()}")

    st.divider()

    # ── Filtres ──────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        reappros_dispo = ["Tous"] + sorted(summary["Ressource"].unique().tolist())
        filtre_reappro = st.selectbox("🔍 Filtrer par réappro", reappros_dispo, key="inv_filtre_reappro")
    with col_f2:
        statut_opts = ["Tous", "🟢 OK", "🔴 Mal fait", "🟠 Au-dessus max"]
        filtre_statut = st.selectbox("📊 Filtrer par statut", statut_opts, key="inv_filtre_statut")
    with col_f3:
        type_opts = ["Tous"] + sorted(summary["type_label"].unique().tolist())
        filtre_type = st.selectbox("🏋️ Filtrer par type", type_opts, key="inv_filtre_type")

    # Appliquer filtres
    filtered = summary.copy()
    if filtre_reappro != "Tous":
        filtered = filtered[filtered["Ressource"] == filtre_reappro]
    if filtre_statut != "Tous":
        emoji = filtre_statut.split(" ")[0]
        filtered = filtered[filtered["statut_emoji"] == emoji]
    if filtre_type != "Tous":
        filtered = filtered[filtered["type_label"] == filtre_type]

    # ── Onglets ──────────────────────────────────────────
    tab_global, tab_reappro, tab_detail, tab_vides = st.tabs([
        "🌍 Vue globale",
        "👤 Par réappro",
        "🔍 Détail machine",
        "📭 Produits manquants",
    ])

    # ══════════════════════════════
    # TAB : Vue globale
    # ══════════════════════════════
    with tab_global:
        st.markdown(f"**{len(filtered)} inventaires affichés**")

        df_display = filtered[[
            "Ressource", "Nom client", "Stock Origine", "type_label",
            "total", "seuil_min", "seuil_max", "ecart_min",
            "nb_produits_vides", "statut_emoji", "statut_label", "Date"
        ]].copy()
        df_display.columns = [
            "Réappro", "Salle", "Machine", "Type",
            "Montant HT", "Seuil min", "Seuil max", "Écart min",
            "Produits vides", "Statut", "Détail statut", "Date"
        ]
        df_display["Montant HT"] = df_display["Montant HT"].map("{:.2f} €".format)
        df_display["Seuil min"]  = df_display["Seuil min"].map(lambda x: f"{x:.0f} €" if pd.notna(x) else "—")
        df_display["Seuil max"]  = df_display["Seuil max"].map(lambda x: f"{x:.2f} €" if pd.notna(x) else "—")
        df_display["Écart min"]  = df_display["Écart min"].map(lambda x: f"{x:+.2f} €" if pd.notna(x) else "—")

        def _color_row(row):
            status = row["Statut"]
            if status == "🔴":
                bg = COLOR_BAD
            elif status == "🟠":
                bg = COLOR_OVER
            elif status == "🟢":
                bg = COLOR_OK
            else:
                bg = COLOR_UNKNOWN
            return [f"background-color:{bg}; color:{WHITE}; font-weight:600"] * len(row)

        st.dataframe(
            df_display.style.apply(_color_row, axis=1),
            use_container_width=True,
            hide_index=True,
            height=min(700, 38 + len(df_display) * 35),
        )

        # Téléchargement Excel global
        st.markdown("---")
        if st.button("📥 Exporter en Excel", key="inv_export_global"):
            excel_bytes = _export_excel(filtered, df_raw)
            date_str = datetime.date.today().strftime("%Y%m%d")
            st.download_button(
                "⬇️ Télécharger Excel",
                data=excel_bytes,
                file_name=f"inventaires_{date_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="inv_dl_global",
            )

    # ══════════════════════════════
    # TAB : Par réappro
    # ══════════════════════════════
    with tab_reappro:
        for reappro in sorted(filtered["Ressource"].unique()):
            sub = filtered[filtered["Ressource"] == reappro]
            nb_ok_r   = (sub["statut_emoji"] == "🟢").sum()
            nb_bad_r  = (sub["statut_emoji"] == "🔴").sum()
            nb_over_r = (sub["statut_emoji"] == "🟠").sum()
            total_r   = sub["total"].sum()

            # Couleur titre selon majorité
            if nb_bad_r == 0 and nb_over_r == 0:
                badge_color = COLOR_OK
                badge = "✅ Tout OK"
            elif nb_bad_r > 0:
                badge_color = COLOR_BAD
                badge = f"🔴 {nb_bad_r} mal fait(s)"
            else:
                badge_color = COLOR_OVER
                badge = f"🟠 {nb_over_r} au-dessus"

            with st.expander(
                f"**{reappro}** — {len(sub)} inventaire(s) · "
                f"🟢 {nb_ok_r} · 🔴 {nb_bad_r} · 🟠 {nb_over_r} · "
                f"Total : {total_r:,.2f} €",
                expanded=(nb_bad_r > 0),
            ):
                for _, row in sub.iterrows():
                    _machine_card(row, df_raw)

    # ══════════════════════════════
    # TAB : Détail machine
    # ══════════════════════════════
    with tab_detail:
        machines_list = sorted(
            filtered["Nom client"].unique().tolist()
        )
        if not machines_list:
            st.info("Aucune machine dans les filtres actifs.")
        else:
            sel_machine = st.selectbox(
                "Choisir une salle", machines_list, key="inv_sel_machine"
            )
            sub = filtered[filtered["Nom client"] == sel_machine]
            for _, row in sub.iterrows():
                st.markdown(f"#### 🏋️ {row['Nom client']} — {row['Stock Origine']}")
                _machine_detail_full(row, df_raw)

    # ══════════════════════════════
    # TAB : Produits manquants
    # ══════════════════════════════
    with tab_vides:
        st.markdown("Produits avec **quantité = 0** lors de l'inventaire (produits présents "
                    "dans le planogramme mais absents de la machine).")

        vides_rows = []
        for _, row in filtered.iterrows():
            missing = _missing_products_for_inv(df_raw, row["Num Piece"])
            for p in missing:
                vides_rows.append({
                    "Réappro":   row["Ressource"],
                    "Salle":     row["Nom client"],
                    "Machine":   row["Stock Origine"],
                    "Type":      row["type_label"],
                    "Code":      p["Code produit"],
                    "Produit":   p["Libellé produit"],
                    "Date":      row["Date"],
                })

        if not vides_rows:
            st.success("🎉 Aucun produit manquant détecté !")
        else:
            df_vides = pd.DataFrame(vides_rows)
            st.markdown(f"**{len(df_vides)} produit(s) manquant(s) sur {df_vides['Salle'].nunique()} salle(s)**")

            # Top produits manquants
            top_vides = df_vides["Produit"].value_counts().head(10).reset_index()
            top_vides.columns = ["Produit", "Nb machines concernées"]

            col_tv, _ = st.columns([1, 1])
            with col_tv:
                st.markdown("**Top 10 produits les plus souvent manquants**")
                st.dataframe(
                    top_vides.style.applymap(
                        lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

            st.markdown("---")
            st.markdown("**Liste complète**")

            # Filtre réappro sur cet onglet
            reappros_v = ["Tous"] + sorted(df_vides["Réappro"].unique().tolist())
            fv_reappro = st.selectbox("Réappro", reappros_v, key="inv_vides_reappro")
            if fv_reappro != "Tous":
                df_vides = df_vides[df_vides["Réappro"] == fv_reappro]

            st.dataframe(
                df_vides.style.applymap(
                    lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                ),
                use_container_width=True,
                hide_index=True,
                height=min(700, 38 + len(df_vides) * 35),
            )


# ─────────────────────────────────────────
# Composants UI
# ─────────────────────────────────────────
def _machine_card(row: pd.Series, df_raw: pd.DataFrame):
    """Affiche une carte compacte pour une machine dans la vue par réappro."""
    color  = row["statut_color"]
    emoji  = row["statut_emoji"]
    total  = row["total"]
    s_min  = row["seuil_min"]
    s_max  = row["seuil_max"]
    ecart  = row["ecart_min"]
    vides  = row["nb_produits_vides"]

    # Barre de progression
    pct = min(100, round((total / s_max) * 100, 1)) if s_max else 0

    ecart_str = f"{ecart:+.2f} €" if pd.notna(ecart) else "—"
    vides_str = f"🔴 {int(vides)} produit(s) vide(s)" if vides > 0 else "✅ Aucun produit vide"

    st.markdown(
        f"""
        <div style="
            border-left: 5px solid {color};
            background: {'#fff8f8' if color == COLOR_BAD else '#f8fff8' if color == COLOR_OK else '#fff8f0'};
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 8px;
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; font-size:1rem;">{emoji} {row['Nom client']}</span>
                <span style="font-size:0.85rem; color:#666;">{row['Stock Origine']} · {row['type_label']}</span>
            </div>
            <div style="display:flex; gap:24px; margin-top:6px; font-size:0.9rem;">
                <span><b>Montant :</b> <span style="color:{color}; font-weight:700;">{total:.2f} €</span></span>
                <span><b>Seuil :</b> {s_min:.0f} € – {s_max:.2f} €</span>
                <span><b>Écart min :</b> {ecart_str}</span>
            </div>
            <div style="margin-top:4px; font-size:0.85rem; color:#555;">{vides_str}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _machine_detail_full(row: pd.Series, df_raw: pd.DataFrame):
    """Affiche le détail complet d'une machine (produits + graphe)."""
    color = row["statut_color"]
    total = row["total"]
    s_min = row["seuil_min"]
    s_max = row["seuil_max"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Montant HT", f"{total:.2f} €")
    c2.metric("📉 Seuil min",  f"{s_min:.0f} €" if pd.notna(s_min) else "—")
    c3.metric("📈 Seuil max",  f"{s_max:.2f} €" if pd.notna(s_max) else "—")
    c4.metric("📊 Écart min",  f"{row['ecart_min']:+.2f} €" if pd.notna(row['ecart_min']) else "—",
              delta_color="normal" if row["ecart_min"] >= 0 else "inverse" if pd.notna(row["ecart_min"]) else "off")

    # Produits de cet inventaire
    sub = df_raw[df_raw["Num Piece"] == row["Num Piece"]].copy()
    sub = sub[["Code produit", "Libellé produit", "Quantité", "Montant HT"]].copy()
    sub = sub.sort_values("Montant HT", ascending=False)

    def _color_prod(r):
        if r["Quantité"] == 0:
            return [f"background-color:{COLOR_BAD}; color:{WHITE}"] * len(r)
        return [""] * len(r)

    st.markdown("**Détail des produits**")
    st.dataframe(
        sub.style.apply(_color_prod, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(500, 38 + len(sub) * 35),
    )


def _show_thresholds_legend():
    """Affiche la légende des seuils."""
    st.markdown("---")
    st.markdown("#### 📏 Seuils de validation par type de machine")
    rows = []
    for key, s in SEUILS.items():
        rows.append({
            "Type":    s["label"],
            "Seuil min (🔴 en dessous)": f"{s['min']:.0f} €",
            "Seuil max (🟠 au-dessus)":  f"{s['max']:.2f} €",
            "Fourchette OK":             f"{s['min']:.0f} € — {s['max']:.2f} €",
        })
    st.table(pd.DataFrame(rows))


def _export_excel(summary: pd.DataFrame, df_raw: pd.DataFrame) -> bytes:
    """Génère un fichier Excel avec onglet résumé + onglets par réappro."""
    import xlsxwriter
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book

        # Formats
        fmt_header = wb.add_format({
            "bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF",
            "border": 1, "align": "center", "valign": "vcenter",
        })
        fmt_ok   = wb.add_format({"bg_color": COLOR_OK,   "font_color": WHITE, "bold": True, "border": 1})
        fmt_bad  = wb.add_format({"bg_color": COLOR_BAD,  "font_color": WHITE, "bold": True, "border": 1})
        fmt_over = wb.add_format({"bg_color": COLOR_OVER, "font_color": WHITE, "bold": True, "border": 1})
        fmt_num  = wb.add_format({"num_format": "#,##0.00", "border": 1})
        fmt_cell = wb.add_format({"border": 1})

        # ── Onglet résumé global ──
        cols_disp = [
            "Ressource", "Nom client", "Stock Origine", "type_label",
            "total", "seuil_min", "seuil_max", "ecart_min",
            "nb_produits_vides", "statut_emoji", "statut_label", "Date",
        ]
        df_exp = summary[cols_disp].copy()
        df_exp.columns = [
            "Réappro", "Salle", "Machine", "Type",
            "Montant HT", "Seuil min", "Seuil max", "Écart min",
            "Produits vides", "Statut", "Détail", "Date",
        ]
        df_exp.to_excel(writer, sheet_name="Résumé global", index=False, startrow=1)
        ws_sum = writer.sheets["Résumé global"]

        for col_idx, col_name in enumerate(df_exp.columns):
            ws_sum.write(0, col_idx, col_name, fmt_header)
            ws_sum.set_column(col_idx, col_idx, max(12, len(col_name) + 2))

        for row_idx, (_, row) in enumerate(summary.iterrows(), start=2):
            fmt = fmt_ok if row["statut_emoji"] == "🟢" else \
                  fmt_bad if row["statut_emoji"] == "🔴" else fmt_over
            for col_idx in range(len(cols_disp)):
                val = row[cols_disp[col_idx]]
                ws_sum.write(row_idx, col_idx, str(val) if not isinstance(val, (int, float)) else val, fmt)

        # ── Onglets par réappro ──
        for reappro in sorted(summary["Ressource"].unique()):
            sub_r = summary[summary["Ressource"] == reappro]
            sheet_name = reappro[:31]  # Excel max 31 chars

            df_r = sub_r[cols_disp].copy()
            df_r.columns = df_exp.columns
            df_r.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1)
            ws_r = writer.sheets[sheet_name]

            for col_idx, col_name in enumerate(df_exp.columns):
                ws_r.write(0, col_idx, col_name, fmt_header)
                ws_r.set_column(col_idx, col_idx, max(12, len(col_name) + 2))

            for row_idx, (_, row) in enumerate(sub_r.iterrows(), start=2):
                fmt = fmt_ok if row["statut_emoji"] == "🟢" else \
                      fmt_bad if row["statut_emoji"] == "🔴" else fmt_over
                for col_idx in range(len(cols_disp)):
                    val = row[cols_disp[col_idx]]
                    ws_r.write(row_idx, col_idx, str(val) if not isinstance(val, (int, float)) else val, fmt)

        # ── Onglet produits vides ──
        vides_rows = []
        for _, row in summary.iterrows():
            missing = _missing_products_for_inv(df_raw, row["Num Piece"])
            for p in missing:
                vides_rows.append({
                    "Réappro":  row["Ressource"],
                    "Salle":    row["Nom client"],
                    "Machine":  row["Stock Origine"],
                    "Code":     p["Code produit"],
                    "Produit":  p["Libellé produit"],
                    "Date":     row["Date"],
                })

        if vides_rows:
            df_vides = pd.DataFrame(vides_rows)
            df_vides.to_excel(writer, sheet_name="Produits vides", index=False, startrow=1)
            ws_v = writer.sheets["Produits vides"]
            for col_idx, col_name in enumerate(df_vides.columns):
                ws_v.write(0, col_idx, col_name, fmt_header)
                ws_v.set_column(col_idx, col_idx, max(12, len(col_name) + 2))
            for row_idx in range(len(df_vides)):
                for col_idx in range(len(df_vides.columns)):
                    ws_v.write(row_idx + 2, col_idx, str(df_vides.iloc[row_idx, col_idx]), fmt_bad)

    output.seek(0)
    return output.read()
