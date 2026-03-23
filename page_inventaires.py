"""
Page Inventaires — Analyse des inventaires machines par réappro.

Fonctionnalités :
  1. Upload d'un export CSV d'inventaires
  2. Détection automatique du type de machine (BF Simple / BF Double / FP / WUF)
     — Double détecté par présence de Volvic (VOLVICEXOTIC50CL / VOLVICFRAISE50CL)
  3. Comparaison du montant HT inventorié aux seuils min/max par type
  4. Croisement avec le planning (depuis MongoDB) pour détecter les inventaires non faits
  5. Détail des produits manquants (quantité = 0) avec nom du produit

Seuils :
  BF Simple     : min 380 € — max 480 €
  BF Double     : min 700 € — max 957,50 €
  FP IDF        : min 300 € — max 409 €
  FP Province   : min 300 € — max 412 €
  WUF / Autre   : min 280 € — max 400 €
"""

import io
import datetime
import pandas as pd
import streamlit as st

# ─────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────
SEUILS = {
    "BF Simple":   {"min": 380,  "max": 480.00,  "label": "Basic Fit Simple"},
    "BF Double":   {"min": 700,  "max": 957.50,  "label": "Basic Fit Double"},
    "FP IDF":      {"min": 300,  "max": 409.00,  "label": "Fitness Park IDF"},
    "FP Province": {"min": 300,  "max": 412.00,  "label": "Fitness Park Province"},
    "WUF":         {"min": 280,  "max": 400.00,  "label": "WUF"},
    "Autre":       {"min": 280,  "max": 450.00,  "label": "Autre"},
}

PRODUITS_DOUBLE = {"VOLVICEXOTIC50CL", "VOLVICFRAISE50CL"}

IDF_RESSOURCES = {"RIDF1", "RIDF2", "RIDF3", "RIDF4", "RIDF5", "RIDF6", "RIDF7", "RIDF8"}

WEEKDAY_TO_JOUR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi"}

COLOR_OK     = "#1E7E34"
COLOR_BAD    = "#C0392B"
COLOR_ORANGE = "#E67E22"
COLOR_GREY   = "#6C757D"
WHITE        = "#FFFFFF"


# ══════════════════════════════════════════
# PARSING ET ENRICHISSEMENT
# ══════════════════════════════════════════

@st.cache_data(show_spinner=False)
def _parse_inventaire(raw_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw_bytes), sep=";", encoding="utf-8-sig", dtype=str)

    required = [
        "Num Piece", "Date", "Stock Origine", "Code client", "Nom client",
        "Ressource", "Code produit", "Libellé produit", "Quantité", "Montant HT",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes : {', '.join(missing)}")

    if "Type tâche" in df.columns:
        df = df[df["Type tâche"].str.strip().str.lower() == "inventaire"].copy()

    df["Montant HT"] = pd.to_numeric(
        df["Montant HT"].str.replace(",", ".", regex=False), errors="coerce"
    ).fillna(0.0)
    df["Quantité"] = pd.to_numeric(df["Quantité"], errors="coerce").fillna(0)

    double_pieces = set(df.loc[df["Code produit"].isin(PRODUITS_DOUBLE), "Num Piece"].unique())
    df["is_double"] = df["Num Piece"].isin(double_pieces)
    df["machine_type"] = df.apply(
        lambda r: _get_machine_type(r["Code client"], r["Ressource"], r["is_double"]),
        axis=1,
    )
    return df


def _get_machine_type(code_client: str, ressource: str, is_double: bool) -> str:
    code = str(code_client).upper()
    is_idf = str(ressource).upper() in {r.upper() for r in IDF_RESSOURCES}
    if code.startswith("BF") or code.startswith("CTF"):
        return "BF Double" if is_double else "BF Simple"
    if code.startswith(("FP", "FT")):
        return "FP IDF" if is_idf else "FP Province"
    if code.startswith("WU"):
        return "WUF"
    return "Autre"


def _get_status(total: float, machine_type: str) -> dict:
    s = SEUILS.get(machine_type)
    if not s:
        return {"emoji": "❓", "label": "Non classifié", "color": COLOR_GREY}
    if total < s["min"]:
        pct = round(total / s["min"] * 100, 1)
        return {"emoji": "🔴", "label": f"Mal fait ({pct}% du min)", "color": COLOR_BAD}
    if total > s["max"]:
        return {"emoji": "🟠", "label": "Au-dessus du max", "color": COLOR_ORANGE}
    return {"emoji": "🟢", "label": "OK", "color": COLOR_OK}


def _build_summary(df: pd.DataFrame) -> pd.DataFrame:
    type_per_inv = df.groupby("Num Piece")["machine_type"].first()
    agg = df.groupby(
        ["Num Piece", "Ressource", "Code client", "Nom client", "Stock Origine", "Date"]
    ).agg(
        total             = ("Montant HT", "sum"),
        nb_produits_ref   = ("Code produit", "nunique"),
        nb_produits_vides = ("Quantité", lambda q: (q == 0).sum()),
    ).reset_index()

    agg["machine_type"] = agg["Num Piece"].map(type_per_inv)
    agg["seuil_min"]    = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("min"))
    agg["seuil_max"]    = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("max"))
    agg["type_label"]   = agg["machine_type"].map(lambda t: SEUILS.get(t, {}).get("label", t))
    agg["ecart_min"]    = (agg["total"] - agg["seuil_min"]).round(2)

    status_info = agg.apply(lambda r: _get_status(r["total"], r["machine_type"]), axis=1)
    agg["statut_emoji"] = status_info.apply(lambda d: d["emoji"])
    agg["statut_label"] = status_info.apply(lambda d: d["label"])
    agg["statut_color"] = status_info.apply(lambda d: d["color"])
    return agg.sort_values(["Ressource", "Nom client"])


# ══════════════════════════════════════════
# CROISEMENT PLANNING vs INVENTAIRES
# ══════════════════════════════════════════

def _parse_planning_for_reappro(planning_dict: dict) -> dict:
    """
    Transforme le planning MongoDB en {jour_fr: {client_code: {label, machine}}}.
    Format MongoDB : {"Lundi": [["BFAL50 - BF NANCY...", "1750M1"], ...], ...}
    """
    result = {}
    for jour, salles in planning_dict.items():
        if jour not in WEEKDAY_TO_JOUR.values():
            continue
        result[jour] = {}
        for salle in salles:
            if len(salle) < 2:
                continue
            client_full = str(salle[0]).strip()
            machine     = str(salle[1]).strip()
            if " - " in client_full:
                code  = client_full.split(" - ")[0].strip()
                label = client_full.split(" - ", 1)[1].strip()
            else:
                code  = client_full
                label = client_full
            result[jour][code] = {"label": label, "machine": machine}
    return result


def _croiser_plannings_inventaires(df_inv: pd.DataFrame, plannings_mongo: dict) -> dict:
    """
    Retourne :
    {
      reappro: {
        date_str: {
          "jour_fr":     str,
          "nb_planifie": int,
          "nb_fait":     int,
          "planifie":    [{code, label, machine}, ...],
          "fait":        [code, ...],
          "manquants":   [{code, label, machine}, ...],
          "deja_fait_semaine": [code, ...],  # double passage : fait un autre jour cette semaine
        }
      }
    }

    Règle double passage :
      Si une machine est planifiée le jour J mais pas inventoriée ce jour-là,
      on vérifie si elle a été inventoriée un autre jour de la même semaine ISO.
      Si c'est le cas → elle n'est PAS comptée comme manquante (juste signalée
      comme "déjà fait cette semaine").
    """
    planning_index = {
        r: _parse_planning_for_reappro(p)
        for r, p in plannings_mongo.items()
    }

    # Index semaine : {(reappro, iso_year, iso_week): set(codes faits)}
    df_inv = df_inv.copy()
    df_inv["_dt"] = pd.to_datetime(df_inv["Date"], format="%d/%m/%Y", errors="coerce")
    df_inv["_iso_year"] = df_inv["_dt"].dt.isocalendar().year.astype("Int64")
    df_inv["_iso_week"] = df_inv["_dt"].dt.isocalendar().week.astype("Int64")

    codes_by_week = (
        df_inv.groupby(["Ressource", "_iso_year", "_iso_week"])["Code client"]
        .apply(set)
        .to_dict()
    )

    inv_done = (
        df_inv.groupby(["Ressource", "Date"])["Code client"]
        .apply(set)
        .reset_index()
    )

    results = {}
    for _, row in inv_done.iterrows():
        reappro    = row["Ressource"]
        date_str   = row["Date"]
        done_codes = row["Code client"]

        if reappro not in planning_index:
            continue
        try:
            dt = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue

        jour_fr = WEEKDAY_TO_JOUR.get(dt.weekday())
        if not jour_fr or jour_fr not in planning_index[reappro]:
            continue

        jour_plan     = planning_index[reappro][jour_fr]
        planned_codes = set(jour_plan.keys())
        fait_codes    = done_codes & planned_codes
        manquants_bruts = planned_codes - done_codes

        # Filtrage double passage :
        # Pour les manquants, vérifier si l'inventaire a été fait un autre jour cette semaine
        iso_cal = dt.isocalendar()
        iso_year = iso_cal[0]
        iso_week = iso_cal[1]
        codes_faits_semaine = codes_by_week.get((reappro, iso_year, iso_week), set())

        deja_fait_semaine = sorted(manquants_bruts & codes_faits_semaine)
        manquants_reels   = manquants_bruts - codes_faits_semaine

        if reappro not in results:
            results[reappro] = {}

        results[reappro][date_str] = {
            "jour_fr":            jour_fr,
            "nb_planifie":        len(planned_codes),
            "nb_fait":            len(fait_codes) + len(deja_fait_semaine),
            "planifie":           [{"code": c, **v} for c, v in jour_plan.items()],
            "fait":               sorted(fait_codes),
            "manquants":          [{"code": c, **jour_plan[c]} for c in sorted(manquants_reels)],
            "deja_fait_semaine":  [{"code": c, **jour_plan[c]} for c in deja_fait_semaine],
        }

    return results


# ══════════════════════════════════════════
# PRODUITS MANQUANTS (qty = 0)
# ══════════════════════════════════════════

def _get_missing_products(df_raw: pd.DataFrame, num_piece: str) -> list:
    sub = df_raw[(df_raw["Num Piece"] == num_piece) & (df_raw["Quantité"] == 0)]
    return (
        sub[["Code produit", "Libellé produit"]]
        .drop_duplicates()
        .rename(columns={"Code produit": "code", "Libellé produit": "nom"})
        .to_dict("records")
    )


def _get_all_missing_products(df_raw: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, inv in summary.iterrows():
        for p in _get_missing_products(df_raw, inv["Num Piece"]):
            rows.append({
                "Réappro":            inv["Ressource"],
                "Salle":              inv["Nom client"],
                "Machine":            inv["Stock Origine"],
                "Type":               inv["type_label"],
                "Date":               inv["Date"],
                "Code produit":       p["code"],
                "Produit manquant":   p["nom"],
                "Statut inventaire":  inv["statut_emoji"],
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ══════════════════════════════════════════
# PAGE PRINCIPALE
# ══════════════════════════════════════════

def render():
    # Récupération des plannings depuis MongoDB
    plannings_mongo: dict = {}
    try:
        from mongo_storage import load_plannings_from_mongo

        @st.cache_data(show_spinner=False, ttl=300)
        def _get_plannings():
            return load_plannings_from_mongo()

        plannings_mongo, _ = _get_plannings()
    except Exception:
        pass

    # ── Upload fichier ──────────────────────
    st.markdown("### 📂 Déposer le fichier export inventaires (CSV)")
    uploaded = st.file_uploader(
        "Export inventaires CSV", type=["csv"],
        key="inv_uploader", label_visibility="collapsed",
    )

    if uploaded is None:
        st.info(
            "**Format attendu :** export CSV du logiciel de gestion "
            "(UTF-8 BOM, séparateur `;`). Colonnes nécessaires : "
            "`Num Piece`, `Date`, `Type tâche`, `Stock Origine`, `Code client`, "
            "`Nom client`, `Ressource`, `Code produit`, `Libellé produit`, "
            "`Quantité`, `Montant HT`."
        )
        _show_thresholds()
        return

    # ── Parsing ─────────────────────────────
    try:
        with st.spinner("Analyse du fichier…"):
            df_raw  = _parse_inventaire(uploaded.read())
            summary = _build_summary(df_raw)
        nb_doubles = (summary["machine_type"] == "BF Double").sum()
        st.success(
            f"✅ **{df_raw['Num Piece'].nunique()}** inventaires chargés — "
            f"**{df_raw['Ressource'].nunique()}** réappros — "
            f"**{nb_doubles}** machines doubles détectées (Volvic)"
        )
    except Exception as e:
        st.error(f"❌ Erreur : {e}")
        return

    # ── Croisement planning ──────────────────
    croisement: dict = {}
    if plannings_mongo:
        croisement = _croiser_plannings_inventaires(df_raw, plannings_mongo)
    else:
        st.warning(
            "⚠️ Plannings non disponibles — le suivi planning est désactivé. "
            "Vérifie la connexion MongoDB."
        )

    # ── KPIs globaux ────────────────────────
    st.divider()
    nb_total = len(summary)
    nb_ok    = (summary["statut_emoji"] == "🟢").sum()
    nb_bad   = (summary["statut_emoji"] == "🔴").sum()
    nb_over  = (summary["statut_emoji"] == "🟠").sum()
    taux_ok  = round(nb_ok / nb_total * 100, 1) if nb_total else 0

    total_inv_manquants = sum(
        len(d["manquants"])
        for r_data in croisement.values()
        for d in r_data.values()
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("📋 Inventaires réalisés",  nb_total)
    k2.metric("✅ OK",                    nb_ok,   delta=f"{taux_ok}%")
    k3.metric("🔴 Mal faits",             nb_bad,
              delta=f"-{round(nb_bad/nb_total*100,1)}%" if nb_total else None,
              delta_color="inverse")
    k4.metric("🟠 Au-dessus max",         nb_over)
    k5.metric("📭 Non faits (planning)",  total_inv_manquants,
              delta=f"-{total_inv_manquants}" if total_inv_manquants else None,
              delta_color="inverse")

    st.divider()

    # ── Filtres ─────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filtre_reappro = st.selectbox(
            "🔍 Réappro",
            ["Tous"] + sorted(summary["Ressource"].unique()),
            key="inv_f_reappro",
        )
    with col_f2:
        filtre_statut = st.selectbox(
            "📊 Statut inventaire",
            ["Tous", "🟢 OK", "🔴 Mal fait", "🟠 Au-dessus max"],
            key="inv_f_statut",
        )
    with col_f3:
        filtre_type = st.selectbox(
            "🏋️ Type machine",
            ["Tous"] + sorted(summary["type_label"].unique()),
            key="inv_f_type",
        )

    filtered = summary.copy()
    if filtre_reappro != "Tous":
        filtered = filtered[filtered["Ressource"] == filtre_reappro]
    if filtre_statut != "Tous":
        filtered = filtered[filtered["statut_emoji"] == filtre_statut.split()[0]]
    if filtre_type != "Tous":
        filtered = filtered[filtered["type_label"] == filtre_type]

    # ── Onglets ─────────────────────────────
    tab_planning, tab_global, tab_reappro, tab_detail, tab_vides = st.tabs([
        "📅 Suivi planning",
        "🌍 Vue globale",
        "👤 Par réappro",
        "🔍 Détail machine",
        "📭 Produits épuisés",
    ])

    # ════════════════════════════════════════
    # TAB — SUIVI PLANNING
    # ════════════════════════════════════════
    with tab_planning:
        if not croisement:
            st.warning("Plannings non disponibles — connexion MongoDB requise.")
        else:
            st.markdown(
                "Croisement entre les **inventaires réalisés** et le **planning prévu** "
                "pour chaque réappro et chaque jour."
            )

            nb_r_ok = sum(
                1 for r_data in croisement.values()
                if all(len(d["manquants"]) == 0 for d in r_data.values())
            )
            nb_r_ko = len(croisement) - nb_r_ok

            p1, p2, p3 = st.columns(3)
            p1.metric("✅ Réappros tout OK",        nb_r_ok)
            p2.metric("🔴 Réappros avec manquants", nb_r_ko,
                      delta=f"-{nb_r_ko}" if nb_r_ko else None, delta_color="inverse")
            p3.metric("📭 Inventaires non faits",   total_inv_manquants,
                      delta=f"-{total_inv_manquants}" if total_inv_manquants else None,
                      delta_color="inverse")

            st.markdown("---")

            # Filtre réappro pour cet onglet (suit le filtre global si actif)
            if filtre_reappro != "Tous" and filtre_reappro in croisement:
                reappros_show = [filtre_reappro]
            else:
                sel_plan = st.selectbox(
                    "Filtrer par réappro",
                    ["Tous"] + sorted(croisement.keys()),
                    key="inv_plan_sel",
                )
                reappros_show = [sel_plan] if sel_plan != "Tous" else sorted(croisement.keys())

            for reappro in reappros_show:
                r_data = croisement[reappro]
                total_manq_r = sum(len(d["manquants"]) for d in r_data.values())
                all_ok = total_manq_r == 0

                with st.expander(
                    f"**{reappro}** — "
                    + ("✅ Tous les inventaires faits" if all_ok
                       else f"🔴 {total_manq_r} inventaire(s) non fait(s)"),
                    expanded=not all_ok,
                ):
                    for date_str in sorted(r_data.keys()):
                        d       = r_data[date_str]
                        nb_manq = len(d["manquants"])  # vrais manquants seulement
                        nb_deja = len(d.get("deja_fait_semaine", []))
                        color   = COLOR_OK if nb_manq == 0 else COLOR_BAD
                        icon    = "✅" if nb_manq == 0 else "🔴"
                        bg      = "#f8fff8" if nb_manq == 0 else "#fff8f8"

                        extra = f" · 🔄 {nb_deja} double(s) passage" if nb_deja else ""
                        st.markdown(
                            f"""<div style="border-left:4px solid {color};padding:8px 12px;
                                border-radius:4px;margin-bottom:8px;background:{bg}">
                            <b>{icon} {d['jour_fr']} {date_str}</b> —
                            {d['nb_fait']}/{d['nb_planifie']} inventaires réalisés{extra}
                            </div>""",
                            unsafe_allow_html=True,
                        )

                        if nb_manq > 0:
                            st.markdown(f"**Inventaires non faits ({nb_manq}) :**")
                            rows_m = [
                                {"Code client": m["code"], "Salle": m["label"], "Machine": m["machine"]}
                                for m in d["manquants"]
                            ]
                            st.dataframe(
                                pd.DataFrame(rows_m).style.applymap(
                                    lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                                ),
                                hide_index=True, use_container_width=True,
                                height=min(300, 38 + len(rows_m) * 35),
                            )

                        # Double passage : fait un autre jour de la semaine
                        deja = d.get("deja_fait_semaine", [])
                        if deja:
                            st.markdown(f"**🔄 Double passage — déjà inventorié cette semaine ({len(deja)}) :**")
                            rows_deja = [
                                {"Code client": m["code"], "Salle": m["label"], "Machine": m["machine"]}
                                for m in deja
                            ]
                            st.dataframe(
                                pd.DataFrame(rows_deja).style.applymap(
                                    lambda _: f"background-color:{COLOR_ORANGE}; color:{WHITE}; font-weight:600"
                                ),
                                hide_index=True, use_container_width=True,
                                height=min(200, 38 + len(rows_deja) * 35),
                            )

    # ════════════════════════════════════════
    # TAB — VUE GLOBALE
    # ════════════════════════════════════════
    with tab_global:
        st.markdown(f"**{len(filtered)} inventaires affichés**")

        cols_disp = [
            "Ressource", "Nom client", "Stock Origine", "type_label",
            "total", "seuil_min", "seuil_max", "ecart_min",
            "nb_produits_vides", "statut_emoji", "statut_label", "Date",
        ]
        hdrs = [
            "Réappro", "Salle", "Machine", "Type",
            "Montant HT", "Seuil min", "Seuil max", "Écart min",
            "Produits épuisés", "Statut", "Détail", "Date",
        ]
        df_disp = filtered[cols_disp].copy()
        df_disp.columns = hdrs
        df_disp["Montant HT"] = df_disp["Montant HT"].map("{:.2f} €".format)
        df_disp["Seuil min"]  = df_disp["Seuil min"].map(lambda x: f"{x:.0f} €" if pd.notna(x) else "—")
        df_disp["Seuil max"]  = df_disp["Seuil max"].map(lambda x: f"{x:.2f} €" if pd.notna(x) else "—")
        df_disp["Écart min"]  = df_disp["Écart min"].map(lambda x: f"{x:+.2f} €" if pd.notna(x) else "—")

        def _color_row(row):
            e = row["Statut"]
            bg = COLOR_OK if e == "🟢" else COLOR_BAD if e == "🔴" else COLOR_ORANGE
            return [f"background-color:{bg}; color:{WHITE}; font-weight:600"] * len(row)

        st.dataframe(
            df_disp.style.apply(_color_row, axis=1),
            use_container_width=True, hide_index=True,
            height=min(700, 38 + len(df_disp) * 35),
        )

        st.markdown("---")
        if st.button("📥 Exporter en Excel", key="inv_export"):
            excel_bytes = _export_excel(filtered, df_raw, croisement)
            date_str = datetime.date.today().strftime("%Y%m%d")
            st.download_button(
                "⬇️ Télécharger Excel", data=excel_bytes,
                file_name=f"inventaires_{date_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="inv_dl",
            )

    # ════════════════════════════════════════
    # TAB — PAR RÉAPPRO
    # ════════════════════════════════════════
    with tab_reappro:
        for reappro in sorted(filtered["Ressource"].unique()):
            sub = filtered[filtered["Ressource"] == reappro]
            nb_ok_r   = (sub["statut_emoji"] == "🟢").sum()
            nb_bad_r  = (sub["statut_emoji"] == "🔴").sum()
            nb_over_r = (sub["statut_emoji"] == "🟠").sum()
            total_r   = sub["total"].sum()
            inv_manq_r = sum(
                len(d["manquants"])
                for d in croisement.get(reappro, {}).values()
            )

            with st.expander(
                f"**{reappro}** — {len(sub)} inv. · "
                f"🟢 {nb_ok_r} · 🔴 {nb_bad_r} · 🟠 {nb_over_r}"
                + (f" · 📭 {inv_manq_r} non faits" if inv_manq_r else "")
                + f" · Total : {total_r:,.2f} €",
                expanded=(nb_bad_r > 0 or inv_manq_r > 0),
            ):
                # Inventaires manquants au planning
                if reappro in croisement:
                    manq_lines = [
                        m for d in croisement[reappro].values() for m in d["manquants"]
                    ]
                    if manq_lines:
                        st.markdown(f"**📭 {len(manq_lines)} inventaire(s) non fait(s) au planning :**")
                        st.dataframe(
                            pd.DataFrame([
                                {"Code": m["code"], "Salle": m["label"], "Machine": m["machine"]}
                                for m in manq_lines
                            ]).style.applymap(
                                lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                            ),
                            hide_index=True, use_container_width=True,
                            height=min(200, 38 + len(manq_lines) * 35),
                        )
                        st.markdown("---")

                for _, row in sub.iterrows():
                    _machine_card(row, df_raw)

    # ════════════════════════════════════════
    # TAB — DÉTAIL MACHINE
    # ════════════════════════════════════════
    with tab_detail:
        machines_list = sorted(filtered["Nom client"].unique())
        if not machines_list:
            st.info("Aucune machine dans les filtres actifs.")
        else:
            sel = st.selectbox("Choisir une salle", machines_list, key="inv_sel_machine")
            for _, row in filtered[filtered["Nom client"] == sel].iterrows():
                st.markdown(
                    f"#### 🏋️ {row['Nom client']} — {row['Stock Origine']} ({row['type_label']})"
                )
                _machine_detail_full(row, df_raw)

    # ════════════════════════════════════════
    # TAB — PRODUITS ÉPUISÉS (qty = 0)
    # ════════════════════════════════════════
    with tab_vides:
        st.markdown(
            "Produits avec **quantité = 0** lors de l'inventaire — "
            "ils étaient épuisés au moment du passage du réappro."
        )

        df_vides = _get_all_missing_products(df_raw, filtered)

        if df_vides.empty:
            st.success("🎉 Aucun produit épuisé dans la sélection !")
        else:
            v1, v2, v3 = st.columns(3)
            v1.metric("📦 Produits épuisés (lignes)", len(df_vides))
            v2.metric("🏋️ Salles concernées",         df_vides["Salle"].nunique())
            v3.metric("🏷️ Produits distincts",        df_vides["Produit manquant"].nunique())

            # Top 10
            st.markdown("---")
            st.markdown("#### 🏆 Produits les plus souvent épuisés")
            top = (
                df_vides.groupby(["Code produit", "Produit manquant"])
                .agg(
                    nb_salles      = ("Salle", "nunique"),
                    nb_occurrences = ("Salle", "count"),
                )
                .reset_index()
                .sort_values("nb_salles", ascending=False)
                .head(10)
                .rename(columns={
                    "Code produit":   "Code",
                    "Produit manquant": "Produit",
                    "nb_salles":      "Nb salles concernées",
                    "nb_occurrences": "Nb occurrences",
                })
            )
            st.dataframe(
                top.style.applymap(
                    lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                ),
                hide_index=True, use_container_width=True,
            )

            # Liste complète avec filtres
            st.markdown("---")
            st.markdown("#### 📋 Liste complète")
            col_fv1, col_fv2 = st.columns(2)
            with col_fv1:
                fv_reappro = st.selectbox(
                    "Réappro", ["Tous"] + sorted(df_vides["Réappro"].unique()),
                    key="inv_vides_reappro",
                )
            with col_fv2:
                fv_produit = st.selectbox(
                    "Produit", ["Tous"] + sorted(df_vides["Produit manquant"].unique()),
                    key="inv_vides_produit",
                )

            df_show = df_vides.copy()
            if fv_reappro != "Tous":
                df_show = df_show[df_show["Réappro"] == fv_reappro]
            if fv_produit != "Tous":
                df_show = df_show[df_show["Produit manquant"] == fv_produit]

            st.markdown(f"**{len(df_show)} ligne(s)**")
            st.dataframe(
                df_show.style.applymap(
                    lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                ),
                use_container_width=True, hide_index=True,
                height=min(700, 38 + len(df_show) * 35),
            )


# ══════════════════════════════════════════
# COMPOSANTS UI
# ══════════════════════════════════════════

def _machine_card(row: pd.Series, df_raw: pd.DataFrame):
    color  = row["statut_color"]
    total  = row["total"]
    s_min  = row["seuil_min"]
    s_max  = row["seuil_max"]
    ecart  = row["ecart_min"]
    vides  = int(row["nb_produits_vides"])

    ecart_str = f"{ecart:+.2f} €" if pd.notna(ecart) else "—"

    # Noms des produits épuisés
    missing_prods = _get_missing_products(df_raw, row["Num Piece"])
    if missing_prods:
        noms_html = " &nbsp;·&nbsp; ".join(
            f"<b>{p['nom']}</b>" for p in missing_prods
        )
        vides_html = (
            f'<div style="margin-top:4px; font-size:0.8rem; color:{COLOR_BAD};">'
            f"🔴 Épuisés ({vides}) : {noms_html}</div>"
        )
    else:
        vides_html = (
            f'<div style="margin-top:4px; font-size:0.82rem; color:#2e7d32;">✅ Aucun produit épuisé</div>'
        )

    bg = "#fff8f8" if color == COLOR_BAD else "#fff8f0" if color == COLOR_ORANGE else "#f8fff8"
    st.markdown(
        f"""<div style="border-left:5px solid {color}; background:{bg};
            border-radius:6px; padding:10px 14px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; font-size:0.95rem;">{row['statut_emoji']} {row['Nom client']}</span>
                <span style="font-size:0.8rem; color:#666;">{row['Stock Origine']} · {row['type_label']} · {row['Date']}</span>
            </div>
            <div style="display:flex; gap:20px; margin-top:5px; font-size:0.88rem;">
                <span><b>Montant :</b> <span style="color:{color}; font-weight:700;">{total:.2f} €</span></span>
                <span><b>Seuil :</b> {s_min:.0f} – {s_max:.2f} €</span>
                <span><b>Écart min :</b> {ecart_str}</span>
            </div>
            {vides_html}
        </div>""",
        unsafe_allow_html=True,
    )


def _machine_detail_full(row: pd.Series, df_raw: pd.DataFrame):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Montant HT", f"{row['total']:.2f} €")
    c2.metric("📉 Seuil min",  f"{row['seuil_min']:.0f} €" if pd.notna(row["seuil_min"]) else "—")
    c3.metric("📈 Seuil max",  f"{row['seuil_max']:.2f} €" if pd.notna(row["seuil_max"]) else "—")
    c4.metric(
        "📊 Écart min",
        f"{row['ecart_min']:+.2f} €" if pd.notna(row["ecart_min"]) else "—",
        delta_color="normal" if pd.notna(row["ecart_min"]) and row["ecart_min"] >= 0 else "inverse",
    )

    sub = df_raw[df_raw["Num Piece"] == row["Num Piece"]].copy()
    sub = sub[["Code produit", "Libellé produit", "Quantité", "Montant HT"]].sort_values(
        "Montant HT", ascending=False
    )

    def _color_prod(r):
        if r["Quantité"] == 0:
            return [f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:700"] * len(r)
        return [""] * len(r)

    st.markdown("**Détail des produits** — les lignes rouges = produits épuisés (qté = 0)")
    st.dataframe(
        sub.style.apply(_color_prod, axis=1),
        use_container_width=True, hide_index=True,
        height=min(500, 38 + len(sub) * 35),
    )


def _show_thresholds():
    st.markdown("---")
    st.markdown("#### 📏 Seuils de validation par type de machine")
    rows = [
        {
            "Type":                        s["label"],
            "Seuil min (🔴 en dessous)":   f"{s['min']:.0f} €",
            "Seuil max (🟠 au-dessus)":    f"{s['max']:.2f} €",
            "Fourchette OK":               f"{s['min']:.0f} € — {s['max']:.2f} €",
        }
        for s in SEUILS.values()
    ]
    st.table(pd.DataFrame(rows))


# ══════════════════════════════════════════
# EXPORT EXCEL
# ══════════════════════════════════════════

def _export_excel(summary: pd.DataFrame, df_raw: pd.DataFrame, croisement: dict) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book
        fmt_hdr  = wb.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": WHITE, "border": 1, "align": "center"})
        fmt_ok   = wb.add_format({"bg_color": COLOR_OK,     "font_color": WHITE, "bold": True, "border": 1})
        fmt_bad  = wb.add_format({"bg_color": COLOR_BAD,    "font_color": WHITE, "bold": True, "border": 1})
        fmt_over = wb.add_format({"bg_color": COLOR_ORANGE, "font_color": WHITE, "bold": True, "border": 1})

        cols = ["Ressource", "Nom client", "Stock Origine", "type_label",
                "total", "seuil_min", "seuil_max", "ecart_min",
                "nb_produits_vides", "statut_emoji", "statut_label", "Date"]
        hdrs = ["Réappro", "Salle", "Machine", "Type",
                "Montant HT", "Seuil min", "Seuil max", "Écart min",
                "Produits épuisés", "Statut", "Détail", "Date"]

        def _write_sheet(ws, rows_df, cols_list, hdrs_list):
            for i, h in enumerate(hdrs_list):
                ws.write(0, i, h, fmt_hdr)
                ws.set_column(i, i, max(14, len(h) + 2))
            for ri, (_, row) in enumerate(rows_df.iterrows(), 1):
                fmt = fmt_ok if row.get("statut_emoji") == "🟢" else \
                      fmt_bad if row.get("statut_emoji") == "🔴" else fmt_over
                for ci, col in enumerate(cols_list):
                    v = row[col]
                    ws.write(ri, ci, str(v) if not isinstance(v, (int, float)) else v, fmt)

        # Résumé global
        summary[cols].to_excel(writer, sheet_name="Résumé global", index=False, startrow=0)
        _write_sheet(writer.sheets["Résumé global"], summary, cols, hdrs)

        # Suivi planning
        if croisement:
            plan_rows = []
            for reappro, r_data in sorted(croisement.items()):
                for date_str, d in sorted(r_data.items()):
                    for m in d["manquants"]:
                        plan_rows.append({
                            "Réappro": reappro, "Date": date_str, "Jour": d["jour_fr"],
                            "Code client": m["code"], "Salle": m["label"],
                            "Machine": m["machine"], "Statut": "Non fait",
                        })
            if plan_rows:
                df_plan = pd.DataFrame(plan_rows)
                df_plan.to_excel(writer, sheet_name="Non faits planning", index=False, startrow=0)
                ws_p = writer.sheets["Non faits planning"]
                for i, h in enumerate(df_plan.columns):
                    ws_p.write(0, i, h, fmt_hdr)
                    ws_p.set_column(i, i, 20)
                for ri, (_, row) in enumerate(df_plan.iterrows(), 1):
                    for ci, col in enumerate(df_plan.columns):
                        ws_p.write(ri, ci, str(row[col]), fmt_bad)

        # Produits épuisés
        df_vides = _get_all_missing_products(df_raw, summary)
        if not df_vides.empty:
            df_vides.to_excel(writer, sheet_name="Produits épuisés", index=False, startrow=0)
            ws_v = writer.sheets["Produits épuisés"]
            for i, h in enumerate(df_vides.columns):
                ws_v.write(0, i, h, fmt_hdr)
                ws_v.set_column(i, i, max(14, len(h) + 2))
            for ri in range(len(df_vides)):
                for ci in range(len(df_vides.columns)):
                    ws_v.write(ri + 1, ci, str(df_vides.iloc[ri, ci]), fmt_bad)

        # Un onglet par réappro
        for reappro in sorted(summary["Ressource"].unique()):
            sub_r = summary[summary["Ressource"] == reappro]
            sn = reappro[:31]
            sub_r[cols].to_excel(writer, sheet_name=sn, index=False, startrow=0)
            _write_sheet(writer.sheets[sn], sub_r, cols, hdrs)

    output.seek(0)
    return output.read()
