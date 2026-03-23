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


def _build_joker_index(df_inv: pd.DataFrame, plannings_mongo: dict) -> dict:
    """
    Construit un index des jokers : inventaires faits par un réappro
    pour les salles planifiées par un autre réappro le même jour.

    Retourne :
    {
      reappro_prevu: {
        date_str: [
          {"code", "label", "machine", "fait_par": reappro_fait}, ...
        ]
      }
    }
    """
    # Index planning complet : {code: [(reappro, jour, label, machine), ...]}
    code_plan_idx: dict = {}
    for reappro, planning_raw in plannings_mongo.items():
        for jour, salles in planning_raw.items():
            if jour not in WEEKDAY_TO_JOUR.values():
                continue
            for salle in salles:
                if len(salle) < 2:
                    continue
                client_full = str(salle[0]).strip()
                machine     = str(salle[1]).strip()
                code  = client_full.split(" - ")[0].strip() if " - " in client_full else client_full
                label = client_full.split(" - ", 1)[1].strip() if " - " in client_full else client_full
                if code not in code_plan_idx:
                    code_plan_idx[code] = []
                code_plan_idx[code].append((reappro, jour, label, machine))

    # Pour chaque inventaire réalisé, vérifier si le code appartient
    # au planning d'un AUTRE réappro ce même jour
    inv_unique = (
        df_inv[["Code client", "Ressource", "Date", "Nom client"]]
        .drop_duplicates(subset=["Code client", "Ressource", "Date"])
    )

    joker_index: dict = {}  # {reappro_prevu: {date: [{code, label, machine, fait_par}]}}

    for _, row in inv_unique.iterrows():
        code         = row["Code client"]
        reappro_inv  = row["Ressource"]
        date_str     = row["Date"]

        if code not in code_plan_idx:
            continue

        try:
            dt = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue
        jour_fait = WEEKDAY_TO_JOUR.get(dt.weekday())
        if not jour_fait:
            continue

        seen = set()  # deduplicate (planned_reappro, code) pairs
        for (planned_reappro, planned_jour, label, machine) in code_plan_idx[code]:
            dedup_key = (planned_reappro, code)
            if planned_reappro != reappro_inv and planned_jour == jour_fait and dedup_key not in seen:
                seen.add(dedup_key)
                if planned_reappro not in joker_index:
                    joker_index[planned_reappro] = {}
                if date_str not in joker_index[planned_reappro]:
                    joker_index[planned_reappro][date_str] = []
                joker_index[planned_reappro][date_str].append({
                    "code":     code,
                    "label":    label,
                    "machine":  machine,
                    "fait_par": reappro_inv,
                })

    return joker_index


def _croiser_plannings_inventaires(df_inv: pd.DataFrame, plannings_mongo: dict) -> dict:
    """
    Retourne :
    {
      reappro: {
        date_str: {
          "jour_fr":           str,
          "nb_planifie":       int,
          "nb_fait":           int,
          "planifie":          [{code, label, machine}, ...],
          "fait":              [code, ...],
          "manquants":         [{code, label, machine}, ...],
          "deja_fait_semaine": [{code, label, machine}, ...],
          "jokers":            [{code, label, machine, fait_par}, ...],
        }
      }
    }

    Règles :
      - Double passage : planifié ce jour mais inventaire fait un autre jour de la semaine ISO.
      - Joker : planifié par ce réappro mais inventaire fait par un autre réappro le même jour.
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

    # Joker index : {reappro_prevu: {date: [{code, label, machine, fait_par}]}}
    joker_index = _build_joker_index(df_inv, plannings_mongo)

    # All codes inventoried globally on each date (any reappro)
    # used to detect jokers for reappros that have no inventories themselves
    all_done_by_date: dict = {}
    for _, row in inv_done.iterrows():
        d = row["Date"]
        if d not in all_done_by_date:
            all_done_by_date[d] = set()
        all_done_by_date[d] |= row["Code client"]

    results = {}

    # Process reappros that have inventories
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

        _populate_result(
            results, reappro, date_str, jour_fr, dt,
            planning_index[reappro][jour_fr],
            done_codes, codes_by_week,
            joker_index.get(reappro, {}).get(date_str, []),
        )

    # Also process reappros with NO inventories but who have jokers or are completely absent
    for reappro, planning in planning_index.items():
        for date_str in sorted(all_done_by_date.keys()):
            if reappro in results and date_str in results[reappro]:
                continue  # already processed
            try:
                dt = datetime.datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                continue
            jour_fr = WEEKDAY_TO_JOUR.get(dt.weekday())
            if not jour_fr or jour_fr not in planning:
                continue
            # Only add if there are jokers for this reappro on this date
            jokers_today = joker_index.get(reappro, {}).get(date_str, [])
            if jokers_today:
                _populate_result(
                    results, reappro, date_str, jour_fr, dt,
                    planning[jour_fr],
                    set(),  # no own inventories
                    codes_by_week,
                    jokers_today,
                )

    return results


def _populate_result(
    results: dict,
    reappro: str,
    date_str: str,
    jour_fr: str,
    dt: datetime.datetime,
    jour_plan: dict,
    done_codes: set,
    codes_by_week: dict,
    jokers_today: list,
) -> None:
    """Calcule et insère le résultat pour (reappro, date) dans results."""
    planned_codes   = set(jour_plan.keys())
    fait_codes      = done_codes & planned_codes
    joker_codes     = {j["code"] for j in jokers_today}
    manquants_bruts = planned_codes - done_codes - joker_codes

    iso_cal  = dt.isocalendar()
    codes_faits_semaine = codes_by_week.get((reappro, iso_cal[0], iso_cal[1]), set())

    deja_fait_semaine = sorted(manquants_bruts & codes_faits_semaine)
    manquants_reels   = manquants_bruts - codes_faits_semaine

    if reappro not in results:
        results[reappro] = {}

    results[reappro][date_str] = {
        "jour_fr":            jour_fr,
        "nb_planifie":        len(planned_codes),
        "nb_fait":            len(fait_codes) + len(deja_fait_semaine) + len(joker_codes),
        "planifie":           [{"code": c, **v} for c, v in jour_plan.items()],
        "fait":               sorted(fait_codes),
        "manquants":          [{"code": c, **jour_plan[c]} for c in sorted(manquants_reels)],
        "deja_fait_semaine":  [{"code": c, **jour_plan[c]} for c in deja_fait_semaine],
        "jokers":             jokers_today,
    }


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
    tab_suivi, tab_detail = st.tabs([
        "📋 Suivi & inventaires",
        "🔍 Détail machine",
    ])

    # ════════════════════════════════════════
    # TAB — SUIVI & INVENTAIRES
    # ════════════════════════════════════════
    with tab_suivi:

        # KPIs planning
        if croisement:
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
            st.divider()

        # Bouton export
        col_exp, _ = st.columns([1, 4])
        with col_exp:
            if st.button("📥 Exporter en Excel", key="inv_export"):
                excel_bytes = _export_excel(filtered, df_raw, croisement, plannings_mongo)
                date_str_dl = datetime.date.today().strftime("%Y%m%d")
                st.download_button(
                    "⬇️ Télécharger Excel", data=excel_bytes,
                    file_name=f"inventaires_{date_str_dl}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="inv_dl",
                )

        st.divider()

        # Accordéon par réappro
        reappros_liste = (
            [filtre_reappro] if filtre_reappro != "Tous"
            else sorted(filtered["Ressource"].unique())
        )

        for reappro in reappros_liste:
            sub = filtered[filtered["Ressource"] == reappro]
            nb_ok_r   = (sub["statut_emoji"] == "🟢").sum()
            nb_bad_r  = (sub["statut_emoji"] == "🔴").sum()
            nb_over_r = (sub["statut_emoji"] == "🟠").sum()
            total_r   = sub["total"].sum()
            inv_manq_r = sum(len(d["manquants"]) for d in croisement.get(reappro, {}).values())
            jokers_r   = sum(len(d.get("jokers", [])) for d in croisement.get(reappro, {}).values())
            nb_planif_r = sum(d["nb_planifie"] for d in croisement.get(reappro, {}).values())
            nb_fait_r   = sum(d["nb_fait"] for d in croisement.get(reappro, {}).values())

            titre = (
                f"**{reappro}** — "
                f"📋 {nb_fait_r}/{nb_planif_r} · "
                f"🟢 {nb_ok_r} · 🔴 {nb_bad_r} · 🟠 {nb_over_r}"
                + (f" · 📭 {inv_manq_r} non faits" if inv_manq_r else "")
                + (f" · 🔀 {jokers_r} joker(s)" if jokers_r else "")
                + f" · 💰 {total_r:,.2f} €"
            )

            with st.expander(titre, expanded=(nb_bad_r > 0 or inv_manq_r > 0)):

                # Section planning du réappro
                if reappro in croisement:
                    for date_str_c in sorted(croisement[reappro].keys()):
                        d       = croisement[reappro][date_str_c]
                        nb_manq = len(d["manquants"])
                        nb_deja = len(d.get("deja_fait_semaine", []))
                        nb_jok  = len(d.get("jokers", []))
                        color   = COLOR_OK if nb_manq == 0 else COLOR_BAD
                        icon    = "✅" if nb_manq == 0 else "🔴"
                        bg      = "#f8fff8" if nb_manq == 0 else "#fff8f8"
                        extra   = ""
                        if nb_deja: extra += f" · 🔄 {nb_deja} double(s)"
                        if nb_jok:  extra += f" · 🔀 {nb_jok} joker(s)"

                        st.markdown(
                            f"""<div style="border-left:4px solid {color};padding:7px 12px;
                                border-radius:4px;margin-bottom:6px;background:{bg}">
                            <b>{icon} {d['jour_fr']} {date_str_c}</b> —
                            {d['nb_fait']}/{d['nb_planifie']} inventaires réalisés{extra}
                            </div>""",
                            unsafe_allow_html=True,
                        )

                        if nb_manq > 0:
                            rows_m = [{"Code": m["code"], "Salle": m["label"], "Machine": m["machine"]}
                                      for m in d["manquants"]]
                            st.dataframe(
                                pd.DataFrame(rows_m).style.applymap(
                                    lambda _: f"background-color:{COLOR_BAD}; color:{WHITE}; font-weight:600"
                                ),
                                hide_index=True, use_container_width=True,
                                height=min(250, 38 + len(rows_m) * 35),
                            )

                        if nb_deja:
                            rows_deja = [{"Code": m["code"], "Salle": m["label"], "Machine": m["machine"]}
                                         for m in d["deja_fait_semaine"]]
                            st.markdown(f"🔄 *Double passage ({nb_deja})*")
                            st.dataframe(
                                pd.DataFrame(rows_deja).style.applymap(
                                    lambda _: f"background-color:{COLOR_ORANGE}; color:{WHITE}; font-weight:600"
                                ),
                                hide_index=True, use_container_width=True,
                                height=min(200, 38 + len(rows_deja) * 35),
                            )

                        if nb_jok:
                            rows_j = [{"Code": j["code"], "Salle": j["label"],
                                       "Machine": j["machine"], "Fait par": j["fait_par"]}
                                      for j in d["jokers"]]
                            st.markdown(f"🔀 *Jokers ({nb_jok})*")
                            st.dataframe(
                                pd.DataFrame(rows_j).style.applymap(
                                    lambda _: f"background-color:#6C3483; color:{WHITE}; font-weight:600"
                                ),
                                hide_index=True, use_container_width=True,
                                height=min(200, 38 + len(rows_j) * 35),
                            )

                    st.markdown("---")

                # Cartes inventaires réalisés
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

def _build_export_rows(
    summary: pd.DataFrame,
    df_raw: pd.DataFrame,
    croisement: dict,
    plannings_mongo: dict,
) -> list:
    """
    Construit la liste complète des lignes d'export :
    une ligne par (réappro, jour planifié, salle) — qu'elle soit faite, non faite ou double passage.
    """
    from planning_parser import parse_planning_file
    import os

    ABBR = {"l": "Lundi", "ma": "Mardi", "me": "Mercredi", "j": "Jeudi", "v": "Vendredi"}

    # Index inventaires faits : {(reappro, date): set(codes)}
    inv_by_date = (
        df_raw.groupby(["Ressource", "Date"])["Code client"]
        .apply(set)
        .to_dict()
    )

    # Index semaine : {(reappro, iso_year, iso_week): set(codes)}
    df_raw2 = df_raw.copy()
    df_raw2["_dt"] = pd.to_datetime(df_raw2["Date"], format="%d/%m/%Y", errors="coerce")
    df_raw2["_iso_year"] = df_raw2["_dt"].dt.isocalendar().year.astype("Int64")
    df_raw2["_iso_week"] = df_raw2["_dt"].dt.isocalendar().week.astype("Int64")
    codes_by_week = (
        df_raw2.groupby(["Ressource", "_iso_year", "_iso_week"])["Code client"]
        .apply(set)
        .to_dict()
    )

    # Index inventaires résumés par (reappro, code, date)
    inv_idx = {}
    for _, r in summary.iterrows():
        inv_idx[(r["Ressource"], r["Code client"], r["Date"])] = r

    # Index produits manquants par Num Piece
    missing_idx = (
        df_raw[df_raw["Quantité"] == 0]
        .groupby("Num Piece")["Libellé produit"]
        .apply(lambda x: list(x.drop_duplicates()))
        .to_dict()
    )

    # Dates présentes dans l'export
    all_dates = sorted(df_raw["Date"].unique())

    rows = []
    for date_str in all_dates:
        dt = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        jour_fr = WEEKDAY_TO_JOUR.get(dt.weekday())
        if not jour_fr:
            continue
        iso = dt.isocalendar()

        for reappro, planning_raw in sorted(plannings_mongo.items()):
            planning = _parse_planning_for_reappro(planning_raw)
            if jour_fr not in planning:
                continue

            jour_plan = planning[jour_fr]
            codes_fait_today = inv_by_date.get((reappro, date_str), set())
            codes_fait_week  = codes_by_week.get((reappro, iso[0], iso[1]), set())

            for code, info in sorted(jour_plan.items(), key=lambda x: x[1]["label"]):
                key = (reappro, code, date_str)
                inv_row = inv_idx.get(key)

                if code in codes_fait_today and inv_row is not None:
                    total        = inv_row["total"]
                    smin         = inv_row["seuil_min"]
                    smax         = inv_row["seuil_max"]
                    machine_type = inv_row["type_label"]
                    ecart        = inv_row["ecart_min"]
                    statut_plan  = "Fait"
                    if inv_row["total"] < smin:
                        statut_inv = "Mal fait"
                    elif inv_row["total"] > smax:
                        statut_inv = "Au-dessus max"
                    else:
                        statut_inv = "OK"
                    prods = missing_idx.get(inv_row["Num Piece"], [])
                    fait_par = reappro
                elif code not in codes_fait_today and code in codes_fait_week:
                    total = smin = smax = ecart = machine_type = None
                    statut_plan = "Double passage"
                    statut_inv  = "-"
                    prods       = []
                    fait_par    = reappro
                else:
                    # Check joker: was it inventoried by another reappro on the same date?
                    joker_reappro = None
                    for (other_r, other_d), other_codes in inv_by_date.items():
                        if other_r != reappro and other_d == date_str and code in other_codes:
                            joker_reappro = other_r
                            break

                    if joker_reappro:
                        joker_key = (joker_reappro, code, date_str)
                        joker_inv = inv_idx.get(joker_key)
                        if joker_inv is not None:
                            total        = joker_inv["total"]
                            smin         = joker_inv["seuil_min"]
                            smax         = joker_inv["seuil_max"]
                            machine_type = joker_inv["type_label"]
                            ecart        = joker_inv["ecart_min"]
                            if joker_inv["total"] < smin:
                                statut_inv = "Mal fait"
                            elif joker_inv["total"] > smax:
                                statut_inv = "Au-dessus max"
                            else:
                                statut_inv = "OK"
                            prods = missing_idx.get(joker_inv["Num Piece"], [])
                        else:
                            total = smin = smax = ecart = machine_type = None
                            statut_inv = "-"
                            prods = []
                        statut_plan = f"Joker ({joker_reappro})"
                        fait_par    = joker_reappro
                    else:
                        total = smin = smax = ecart = machine_type = None
                        statut_plan = "Non fait"
                        statut_inv  = "Non fait"
                        prods       = []
                        fait_par    = ""

                rows.append({
                    "reappro":      reappro,
                    "date":         date_str,
                    "jour":         jour_fr,
                    "code":         code,
                    "salle":        info["label"],
                    "machine":      info["machine"],
                    "statut_plan":  statut_plan,
                    "machine_type": machine_type or "",
                    "total":        total,
                    "seuil_min":    smin,
                    "seuil_max":    smax,
                    "ecart":        ecart,
                    "statut_inv":   statut_inv,
                    "produits":     prods,
                    "fait_par":     fait_par if statut_plan.startswith("Joker") else "",
                })

    return rows


def _export_excel(
    summary: pd.DataFrame,
    df_raw: pd.DataFrame,
    croisement: dict,
    plannings_mongo: dict = None,
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    plannings_mongo = plannings_mongo or {}
    rows = _build_export_rows(summary, df_raw, croisement, plannings_mongo)

    # ── Style helpers ──────────────────────────────────────────────────────
    def _fill(hex_col):
        return PatternFill("solid", fgColor=hex_col.lstrip("#"))

    def _font(bold=False, color="000000", size=9, italic=False):
        return Font(bold=bold, color=color.lstrip("#"), size=size,
                    name="Arial", italic=italic)

    _side_thin  = Side(style="thin",   color="CCCCCC")
    _side_med   = Side(style="medium", color="1F4E79")
    _brd        = Border(left=_side_thin, right=_side_thin,
                         top=_side_thin,  bottom=_side_thin)
    _brd_sep    = Border(left=_side_med, right=_side_thin,
                         top=_side_med,  bottom=_side_med)

    def _align(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    # Color palette
    C_DARK      = "1F4E79"; C_MID  = "2E75B6"; C_SUB = "BDD7EE"
    C_OK_BG     = "D4EDDA"; C_BAD_BG = "F8D7DA"; C_ORA_BG = "FFF3CD"
    C_DOUB_BG   = "EDE7F6"; C_GREY_BG = "F5F5F5"
    C_OK_FG     = "1E7E34"; C_BAD_FG  = "C0392B"
    C_ORA_FG    = "E67E22"; C_DOUB_FG = "6C3483"
    C_WHITE     = "FFFFFF"

    STATUS_STYLE = {
        "Fait":                  (C_OK_BG,   C_MID,    False),
        "Non fait":              (C_BAD_BG,  C_BAD_FG, True),
        "Double passage":        (C_DOUB_BG, C_DOUB_FG,True),
        "OK":                    (C_OK_BG,   C_OK_FG,  True),
        "Mal fait":              (C_BAD_BG,  C_BAD_FG, True),
        "Au-dessus max":         (C_ORA_BG,  C_ORA_FG, True),
        "-":                     (C_GREY_BG, C_DARK,   False),
        "Non fait (inv)":        (C_BAD_BG,  C_BAD_FG, True),
    }
    # Joker entries added dynamically below since the reappro name is in the key

    # Column definitions for detail sheets: (header, width)
    DETAIL_COLS = [
        ("Date",             11), ("Jour",          10), ("Salle",            36),
        ("Machine",           9), ("Type machine",  16), ("Statut planning",  22),
        ("Fait par",         12), ("Montant HT",    13), ("Statut inv.",      14),
        ("Produits épuisés", 52),
    ]
    N = len(DETAIL_COLS)

    wb = Workbook()
    wb.remove(wb.active)

    # ══════════════════════════════════════════
    # ONGLET RÉCAP GLOBAL
    # ══════════════════════════════════════════
    ws_g = wb.create_sheet("📊 Récap global")
    ws_g.freeze_panes = "A3"
    ws_g.sheet_properties.tabColor = C_DARK

    # Row 1 : big title
    ws_g.merge_cells("A1:J1")
    tc = ws_g.cell(1, 1, "Suivi des inventaires — Récapitulatif")
    tc.fill = _fill(C_DARK); tc.font = _font(True, C_WHITE, 13)
    tc.alignment = _align("center"); ws_g.row_dimensions[1].height = 26

    # Row 2 : headers
    RECAP_HDRS = [
        "Réappro", "Date", "Jour",
        "✅ Faits", "🔴 Non faits", "🔄 Double pass.",
        "⚠️ Mal faits", "📈 Au-dessus max",
        "💰 Total € fait", "% réalisation",
    ]
    ws_g.row_dimensions[2].height = 20
    for ci, h in enumerate(RECAP_HDRS, 1):
        c = ws_g.cell(2, ci, h)
        c.fill = _fill(C_MID); c.font = _font(True, C_WHITE, 9)
        c.alignment = _align("center"); c.border = _brd
        ws_g.column_dimensions[get_column_letter(ci)].width = [
            13, 11, 11, 10, 12, 13, 12, 15, 16, 14][ci - 1]

    # Aggregate
    recap: dict = {}
    for r in rows:
        k = (r["reappro"], r["date"], r["jour"])
        if k not in recap:
            recap[k] = {"fait": 0, "non_fait": 0, "double": 0,
                        "mal_fait": 0, "au_dessus": 0, "total_eur": 0.0}
        d = recap[k]
        sp = r["statut_plan"]
        si = r["statut_inv"]
        if sp == "Fait":
            d["fait"] += 1; d["total_eur"] += r["total"] or 0
            if si == "Mal fait":       d["mal_fait"] += 1
            elif si == "Au-dessus max": d["au_dessus"] += 1
        elif sp == "Non fait":     d["non_fait"] += 1
        elif sp == "Double passage": d["double"] += 1
        elif sp.startswith("Joker"):
            # Joker = fait, compté comme tel
            d["fait"] += 1; d["total_eur"] += r["total"] or 0
            if si == "Mal fait":       d["mal_fait"] += 1
            elif si == "Au-dessus max": d["au_dessus"] += 1

    ri = 3
    for (reappro, date_str, jour), d in sorted(recap.items()):
        planif = d["fait"] + d["non_fait"] + d["double"]
        pct    = round(d["fait"] / planif * 100, 1) if planif else 0
        bg = C_OK_BG if (d["non_fait"] == 0 and d["mal_fait"] == 0) else \
             C_BAD_BG if d["non_fait"] > 0 else C_ORA_BG
        vals = [reappro, date_str, jour, d["fait"], d["non_fait"], d["double"],
                d["mal_fait"], d["au_dessus"], round(d["total_eur"], 2), f"{pct}%"]
        ws_g.row_dimensions[ri].height = 17
        for ci, v in enumerate(vals, 1):
            c = ws_g.cell(ri, ci, v)
            c.fill = _fill(bg); c.border = _brd
            c.font = _font(size=9)
            c.alignment = _align("center" if ci > 3 else "left")
            if ci == 9 and isinstance(v, (int, float)):
                c.number_format = "#,##0.00 €"
        ri += 1

    # ══════════════════════════════════════════
    # UN ONGLET PAR RÉAPPRO
    # ══════════════════════════════════════════
    reappros_ordered = sorted({r["reappro"] for r in rows})
    for reappro in reappros_ordered:
        ws = wb.create_sheet(reappro[:31])
        ws.freeze_panes = "A3"

        # Title row
        ws.merge_cells(f"A1:{get_column_letter(N)}1")
        t = ws.cell(1, 1, f"Suivi inventaires — {reappro}")
        t.fill = _fill(C_DARK); t.font = _font(True, C_WHITE, 12)
        t.alignment = _align("center"); ws.row_dimensions[1].height = 24

        # Header row
        ws.row_dimensions[2].height = 18
        for ci, (h, w) in enumerate(DETAIL_COLS, 1):
            c = ws.cell(2, ci, h)
            c.fill = _fill(C_MID); c.font = _font(True, C_WHITE, 9)
            c.alignment = _align("center"); c.border = _brd
            ws.column_dimensions[get_column_letter(ci)].width = w

        sub_rows = [r for r in rows if r["reappro"] == reappro]
        current_date = None
        ri = 3

        for r in sub_rows:
            # ── Date separator ─────────────────────────────────────────────
            if r["date"] != current_date:
                current_date = r["date"]

                # Count stats for this day
                day_rows = [x for x in sub_rows if x["date"] == r["date"]]
                nb_fait    = sum(1 for x in day_rows if x["statut_plan"] == "Fait")
                nb_nf      = sum(1 for x in day_rows if x["statut_plan"] == "Non fait")
                nb_dbl     = sum(1 for x in day_rows if x["statut_plan"] == "Double passage")
                nb_mal     = sum(1 for x in day_rows if x["statut_inv"] == "Mal fait")
                total_jour = sum(x["total"] or 0 for x in day_rows if x["statut_plan"] == "Fait")
                sep_txt = (
                    f"  {r['jour']}  {r['date']}"
                    f"   |   ✅ {nb_fait} faits   🔴 {nb_nf} non faits"
                    + (f"   🔄 {nb_dbl} double(s)" if nb_dbl else "")
                    + (f"   ⚠️ {nb_mal} mal fait(s)" if nb_mal else "")
                    + f"   💰 {total_jour:,.2f} €"
                )
                ws.merge_cells(f"A{ri}:{get_column_letter(N)}{ri}")
                sep = ws.cell(ri, 1, sep_txt)
                sep.fill = _fill(C_SUB)
                sep.font = _font(True, C_DARK, 10)
                sep.alignment = _align("left")
                for ci in range(1, N + 1):
                    ws.cell(ri, ci).border = _brd_sep
                ws.row_dimensions[ri].height = 20
                ri += 1

            # ── Data row ───────────────────────────────────────────────────
            sp = r["statut_plan"]
            si = r["statut_inv"]

            # Row background
            if sp == "Non fait":
                row_bg = C_BAD_BG
            elif sp == "Double passage":
                row_bg = C_DOUB_BG
            elif sp.startswith("Joker"):
                row_bg = "F3E5F5"  # violet très clair
            elif si == "Mal fait":
                row_bg = C_BAD_BG
            elif si == "Au-dessus max":
                row_bg = C_ORA_BG
            elif si == "OK":
                row_bg = C_OK_BG
            else:
                row_bg = C_GREY_BG

            prods_str = " / ".join(r["produits"]) if r["produits"] else ""
            has_prods = bool(prods_str)
            ws.row_dimensions[ri].height = 20 if has_prods else 16

            is_joker = sp.startswith("Joker")
            values = [
                r["date"], r["jour"], r["salle"], r["machine"],
                r["machine_type"] or "-",
                sp,
                r.get("fait_par", "") or "",
                r["total"],
                si, prods_str,
            ]

            for ci, v in enumerate(values, 1):
                c = ws.cell(ri, ci, v)
                c.fill = _fill(row_bg)
                c.font = _font(size=9)
                c.border = _brd
                c.alignment = _align(
                    "center" if ci in (1, 2, 4, 8) else "left",
                    wrap=(ci == 10),
                )
                if ci == 8 and isinstance(v, (int, float)):
                    c.number_format = "#,##0.00 €"

                # Statut planning cell (col 6) — colored badge
                if ci == 6:
                    if is_joker:
                        bg, fg, bold = "E8D5F5", "6C3483", True
                    else:
                        bg, fg, bold = STATUS_STYLE.get(sp, (C_GREY_BG, C_DARK, False))
                    c.fill = _fill(bg); c.font = _font(bold, fg, 9)
                    c.alignment = _align("center")

                # Fait par cell (col 7) — violet if joker
                if ci == 7 and v:
                    c.fill = _fill("E8D5F5")
                    c.font = _font(True, "6C3483", 9)
                    c.alignment = _align("center")

                # Statut inventaire cell (col 9) — colored badge
                if ci == 9:
                    bg, fg, bold = STATUS_STYLE.get(si, (C_GREY_BG, C_DARK, False))
                    c.fill = _fill(bg); c.font = _font(bold, fg, 9)
                    c.alignment = _align("center")

                # Produits épuisés cell (col 10) — red if present
                if ci == 10 and has_prods:
                    c.fill = _fill("FFCCCC")
                    c.font = _font(True, C_BAD_FG, 9)

            ri += 1

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.read()
