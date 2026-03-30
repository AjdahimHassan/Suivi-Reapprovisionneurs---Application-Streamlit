"""
Page Picklist vs Chargement

Compare la picklist (quantités prévues à charger par machine et par produit)
avec le chargement réel (export ERP par tâche machine).

Fichiers :
  Picklist   : CSV `;` — colonnes : Approvisionneur, Code Machine, Nom client,
               Info accès, Libellé produit, ..., A Charger
  Chargement : CSV `;` — colonnes : IDTASK, Date, Type tâche, Stock Origine,
               Stock Destination (= code machine), ..., Libellé produit,
               Quantité, ...
"""

import datetime
import io

import pandas as pd
import streamlit as st
import xlsxwriter


# ─────────────────────────────────────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────────────────────────────────────

def parse_picklist(content: bytes) -> pd.DataFrame:
    """
    Parse un fichier picklist CSV (séparateur ;).
    Retourne un DataFrame avec les colonnes :
      Code Machine, Nom client, Libellé produit, A Charger (int ≥ 0)
    """
    df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.strip('"')
    df["A Charger"] = (
        pd.to_numeric(df["A Charger"].str.strip(), errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .astype(int)
    )
    for col in ["Code Machine", "Nom client", "Libellé produit"]:
        df[col] = df[col].str.strip().str.strip('"')
    return df[["Code Machine", "Nom client", "Libellé produit", "A Charger"]]


def parse_chargement(content: bytes) -> pd.DataFrame:
    """
    Parse un fichier chargement ERP CSV (séparateur ;).
    Colonnes attendues : Stock Destination, Libellé produit, Quantité, Nom client.
    Filtre sur Type tâche = "Chargement machine".
    Retourne un DataFrame avec les colonnes :
      Code Machine, Nom client charg, Libellé produit, Quantité (int)
    """
    df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.strip('"')

    if "Type tâche" in df.columns:
        df = df[df["Type tâche"].str.strip().str.strip('"') == "Chargement machine"]

    for col in ["Stock Destination", "Libellé produit", "Nom client"]:
        if col in df.columns:
            df[col] = df[col].str.strip().str.strip('"')

    df["Quantité"] = (
        pd.to_numeric(df["Quantité"].str.strip(), errors="coerce")
        .fillna(0)
        .astype(int)
    )

    df = df.rename(columns={
        "Stock Destination": "Code Machine",
        "Nom client":        "Nom client charg",
    })

    # Agréger si plusieurs lignes pour le même (machine, produit)
    return (
        df.groupby(["Code Machine", "Nom client charg", "Libellé produit"], as_index=False)["Quantité"]
        .sum()
    )


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSE
# ─────────────────────────────────────────────────────────────────────────────

_COULEURS = {
    "Conforme":       "#d4edda",
    "Insuffisant":    "#f8d7da",
    "Non chargé":     "#c0392b",
    "Surplus":        "#ffeeba",
    "Non prévu":      "#d1ecf1",
    "Rien à charger": "#f4f4f4",
}

_ORDRE_STATUT = {
    "Non chargé":     0,
    "Insuffisant":    1,
    "Surplus":        2,
    "Non prévu":      3,
    "Conforme":       4,
    "Rien à charger": 5,
}


def _statut(picklist: int, reel: int) -> str:
    if picklist == 0 and reel == 0:
        return "Rien à charger"
    if picklist == 0 and reel > 0:
        return "Non prévu"
    if reel == 0:
        return "Non chargé"
    if reel == picklist:
        return "Conforme"
    if reel > picklist:
        return "Surplus"
    return "Insuffisant"


def analyser(picklist_df: pd.DataFrame, chargement_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge par (Code Machine, Libellé produit).
    Retourne un DataFrame avec colonnes :
      Code Machine, Nom client, Libellé produit, Picklist, Réel, Écart, Statut
    """
    pick = picklist_df.rename(columns={"A Charger": "Picklist", "Nom client": "Nom client pick"})
    charg = chargement_df.rename(columns={"Quantité": "Réel"})

    merged = pd.merge(
        pick,
        charg[["Code Machine", "Libellé produit", "Réel", "Nom client charg"]],
        on=["Code Machine", "Libellé produit"],
        how="outer",
    ).fillna({"Picklist": 0, "Réel": 0, "Nom client pick": "", "Nom client charg": ""})

    merged["Picklist"] = merged["Picklist"].astype(int)
    merged["Réel"]     = merged["Réel"].astype(int)
    merged["Écart"]    = merged["Réel"] - merged["Picklist"]
    merged["Statut"]   = merged.apply(lambda r: _statut(r["Picklist"], r["Réel"]), axis=1)
    # Coalesce nom client
    merged["Nom client"] = merged["Nom client pick"].where(
        merged["Nom client pick"] != "", merged["Nom client charg"]
    )

    merged["_ordre"] = merged["Statut"].map(_ORDRE_STATUT)
    merged = (
        merged
        .sort_values(["Code Machine", "_ordre", "Libellé produit"])
        .drop(columns=["_ordre", "Nom client pick", "Nom client charg"])
        .reset_index(drop=True)
    )
    return merged


def _stats_machine(df_machine: pd.DataFrame) -> dict:
    """Calcule les stats de conformité pour une machine."""
    a_charger = df_machine[df_machine["Picklist"] > 0]
    total      = len(a_charger)
    conformes  = (a_charger["Statut"] == "Conforme").sum()
    return {
        "total":     total,
        "conformes": conformes,
        "non_charges": (a_charger["Statut"] == "Non chargé").sum(),
        "insuffisants": (a_charger["Statut"] == "Insuffisant").sum(),
        "surplus":    (a_charger["Statut"] == "Surplus").sum(),
        "non_prevus": (df_machine["Statut"] == "Non prévu").sum(),
        "pct":        round(conformes / total * 100) if total else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AFFICHAGE
# ─────────────────────────────────────────────────────────────────────────────

def _formater_ecart(val: int) -> str:
    if val > 0:  return f"+{val}"
    if val < 0:  return str(val)
    return "0"


def _styler(df: pd.DataFrame):
    """Coloration par ligne selon le statut."""
    def ligne(row):
        statut = row["Statut"]
        bg     = _COULEURS.get(statut, "")
        color  = "color: white;" if statut == "Non chargé" else ""
        style  = f"background-color: {bg}; {color}" if bg else ""
        return [style] * len(row)

    styled = df.style.apply(ligne, axis=1)

    def ecart_color(val):
        if val > 0:  return "color: #856404;"
        if val < 0:  return "color: #721c24;"
        return "color: #155724;"

    styled = styled.applymap(ecart_color, subset=["Écart"])
    styled = styled.format({"Écart": _formater_ecart})
    return styled


_LEGENDE = """
<div style="display:flex;gap:0.8rem;flex-wrap:wrap;margin:0.4rem 0 1rem 0;font-size:0.80rem;">
  <span style="background:#d4edda;padding:2px 8px;border-radius:4px;">✅ Conforme</span>
  <span style="background:#f8d7da;padding:2px 8px;border-radius:4px;">❌ Insuffisant</span>
  <span style="background:#c0392b;color:white;padding:2px 8px;border-radius:4px;">🚫 Non chargé</span>
  <span style="background:#ffeeba;padding:2px 8px;border-radius:4px;">⚠️ Surplus</span>
  <span style="background:#d1ecf1;padding:2px 8px;border-radius:4px;">📋 Non prévu</span>
  <span style="background:#f4f4f4;padding:2px 8px;border-radius:4px;">— Rien à charger</span>
</div>
"""


def generer_excel(result_df: pd.DataFrame) -> bytes:
    """
    Génère un fichier Excel coloré avec :
      - Sheet "Résumé"   : une ligne par machine avec les stats
      - Sheet "Détail"   : toutes les lignes produits toutes machines confondues
      - Sheet par machine: détail produits pour chaque machine
    """
    output  = io.BytesIO()
    machines = sorted(result_df["Code Machine"].unique())

    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        # ── Formats ──────────────────────────────────────────
        def fmt(bg, font="#000000", bold=False):
            return wb.add_format({
                "bg_color": bg, "font_color": font,
                "bold": bold, "border": 1, "border_color": "#CCCCCC",
                "valign": "vcenter",
            })

        fmts = {
            "Conforme":       fmt("#d4edda"),
            "Insuffisant":    fmt("#f8d7da"),
            "Non chargé":     fmt("#c0392b", font="#FFFFFF"),
            "Surplus":        fmt("#ffeeba"),
            "Non prévu":      fmt("#d1ecf1"),
            "Rien à charger": fmt("#f4f4f4"),
        }
        header_fmt = fmt("#1B3D6F", font="#FFFFFF", bold=True)
        default_fmt = fmt("#FFFFFF")

        def _ecrire_feuille(ws, headers, rows_data, col_widths, statut_col_idx=None):
            ws.set_row(0, 18)
            for c, h in enumerate(headers):
                ws.write(0, c, h, header_fmt)
            for r, row in enumerate(rows_data, start=1):
                statut = row[statut_col_idx] if statut_col_idx is not None else None
                row_fmt = fmts.get(statut, default_fmt)
                for c, val in enumerate(row):
                    ws.write(r, c, val, row_fmt)
            for c, w in enumerate(col_widths):
                ws.set_column(c, c, w)

        # ── Sheet Résumé ──────────────────────────────────────
        ws_recap = wb.add_worksheet("Résumé")
        headers_recap = ["Machine", "Client", "Conformes", "Non chargés",
                         "Insuffisants", "Surplus", "Non prévus", "Conformité %"]
        rows_recap = []
        recap_statuts = []
        for m in machines:
            df_m = result_df[result_df["Code Machine"] == m]
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            s    = _stats_machine(df_m)
            rows_recap.append([
                m, nom,
                f"{s['conformes']} / {s['total']}",
                s["non_charges"], s["insuffisants"],
                s["surplus"],     s["non_prevus"],
                f"{s['pct']} %",
            ])
            if s["pct"] >= 75:
                recap_statuts.append("Conforme")
            elif s["pct"] >= 50:
                recap_statuts.append("Insuffisant")
            else:
                recap_statuts.append("Non chargé")

        ws_recap.set_row(0, 18)
        for c, h in enumerate(headers_recap):
            ws_recap.write(0, c, h, header_fmt)
        for r, (row, statut) in enumerate(zip(rows_recap, recap_statuts), start=1):
            row_fmt = fmts.get(statut, default_fmt)
            for c, val in enumerate(row):
                ws_recap.write(r, c, val, row_fmt)
        for c, w in enumerate([14, 38, 14, 13, 14, 10, 11, 13]):
            ws_recap.set_column(c, c, w)

        # ── Sheet Détail (toutes machines) ────────────────────
        headers_det = ["Machine", "Client", "Produit", "Picklist", "Réel", "Écart", "Statut"]
        widths_det  = [14, 38, 38, 10, 8, 8, 15]
        rows_det = []
        for _, row in result_df.sort_values(["Code Machine", "Libellé produit"]).iterrows():
            ecart = row["Écart"]
            rows_det.append([
                row["Code Machine"], row["Nom client"], row["Libellé produit"],
                row["Picklist"], row["Réel"],
                f"+{ecart}" if ecart > 0 else str(ecart),
                row["Statut"],
            ])
        _ecrire_feuille(wb.add_worksheet("Détail"), headers_det, rows_det, widths_det, statut_col_idx=6)

        # ── Une sheet par machine ─────────────────────────────
        headers_m = ["Produit", "Picklist", "Réel", "Écart", "Statut"]
        widths_m  = [40, 10, 8, 8, 15]
        for m in machines:
            df_m = result_df[result_df["Code Machine"] == m].sort_values("Libellé produit")
            ws_m = wb.add_worksheet(m[:31])
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            ws_m.merge_range(0, 0, 0, len(headers_m) - 1, f"{m} — {nom}", header_fmt)
            ws_m.set_row(0, 18)
            for c, h in enumerate(headers_m):
                ws_m.write(1, c, h, header_fmt)
            for r, (_, row) in enumerate(df_m.iterrows(), start=2):
                ecart   = row["Écart"]
                statut  = row["Statut"]
                row_fmt = fmts.get(statut, default_fmt)
                vals    = [
                    row["Libellé produit"], row["Picklist"], row["Réel"],
                    f"+{ecart}" if ecart > 0 else str(ecart),
                    statut,
                ]
                for c, val in enumerate(vals):
                    ws_m.write(r, c, val, row_fmt)
            for c, w in enumerate(widths_m):
                ws_m.set_column(c, c, w)

    return output.getvalue()


def _afficher_resultats(picklist_df: pd.DataFrame, chargement_df: pd.DataFrame):
    result = analyser(picklist_df, chargement_df)
    machines = sorted(result["Code Machine"].unique())

    # ── KPIs globaux ───────────────────────────────────────
    a_charger_global = result[result["Picklist"] > 0]
    total_global     = len(a_charger_global)
    conformes_global = (a_charger_global["Statut"] == "Conforme").sum()
    pct_global       = round(conformes_global / total_global * 100) if total_global else 0
    nc_global        = (a_charger_global["Statut"] == "Non chargé").sum()
    insuf_global     = (a_charger_global["Statut"] == "Insuffisant").sum()
    surplus_global   = (a_charger_global["Statut"] == "Surplus").sum()
    np_global        = (result["Statut"] == "Non prévu").sum()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Conformité globale", f"{pct_global} %")
    k2.metric("✅ Conformes", f"{conformes_global} / {total_global}")
    k3.metric("🚫 Non chargés", nc_global)
    k4.metric("❌ Insuffisants", insuf_global)
    k5.metric("⚠️ Surplus / Non prévus", f"{surplus_global} + {np_global}")

    st.markdown(_LEGENDE, unsafe_allow_html=True)

    # ── Résumé par machine ─────────────────────────────────
    with st.expander(f"📊 Résumé par machine ({len(machines)} machines)", expanded=True):
        rows = []
        for m in machines:
            df_m = result[result["Code Machine"] == m]
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            s    = _stats_machine(df_m)
            # Statut couleur basé sur le % de conformité
            if s["pct"] >= 75:
                icone = "✅"
            elif s["pct"] >= 50:
                icone = "❌"
            else:
                icone = "🚫"
            rows.append({
                "":            icone,
                "Machine":     m,
                "Client":      nom,
                "Conformes":   f"{s['conformes']} / {s['total']}",
                "Non chargés": s["non_charges"],
                "Insuffisants":s["insuffisants"],
                "Surplus":     s["surplus"],
                "Non prévus":  s["non_prevus"],
                "Conformité":  f"{s['pct']} %",
            })
        df_recap = pd.DataFrame(rows)

        def _style_recap(row):
            icone = row[""]
            if icone == "🚫":  bg = "#c0392b"; color = "color:white;"
            elif icone == "❌": bg = "#f8d7da"; color = ""
            else:               bg = "#d4edda"; color = ""
            return [f"background-color:{bg};{color}"] * len(row)

        st.dataframe(
            df_recap.style.apply(_style_recap, axis=1),
            use_container_width=True,
            height=min(40 + 35 * len(rows), 500),
            hide_index=True,
        )

    # ── Détail par machine ─────────────────────────────────
    with st.expander(f"🔍 Détail par machine", expanded=False):
        for m in machines:
            df_m = result[result["Code Machine"] == m].copy()
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            s    = _stats_machine(df_m)

            # En-tête machine avec badge conformité
            badge_color = "#d4edda" if s["pct"] >= 75 else ("#f8d7da" if s["pct"] >= 50 else "#c0392b")
            st.markdown(
                f'<div style="margin:1rem 0 0.3rem 0;">'
                f'<b style="font-size:1rem;">{m}</b> — {nom} &nbsp;'
                f'<span style="background:{badge_color};padding:2px 10px;border-radius:10px;font-size:0.85rem;">'
                f'{s["pct"]} % conforme</span></div>',
                unsafe_allow_html=True,
            )

            cols = ["Libellé produit", "Picklist", "Réel", "Écart", "Statut"]
            st.dataframe(
                _styler(df_m[cols].rename(columns={"Libellé produit": "Produit"})),
                use_container_width=True,
                height=min(40 + 35 * len(df_m), 400),
                hide_index=True,
            )

    # ── Export Excel ───────────────────────────────────────
    st.divider()
    col_dl, _ = st.columns([1, 4])
    with col_dl:
        excel_bytes = generer_excel(result)
        date_str    = datetime.date.today().strftime("%Y%m%d")
        st.download_button(
            label="⬇️ Télécharger Excel",
            data=excel_bytes,
            file_name=f"picklist_{date_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render():
    st.markdown("## 📋 Picklist vs Chargement")
    st.markdown(
        '<div style="color:#6c757d;margin-bottom:1.2rem;">'
        "Comparez la picklist prévue avec le chargement réel — "
        "détectez les produits non chargés, insuffisants ou en surplus, machine par machine."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Upload ─────────────────────────────────────────────
    col_pick, col_charg = st.columns(2)
    with col_pick:
        st.markdown("### 📋 Picklist(s)")
        st.caption("CSV picklist du matin — colonnes : Code Machine, Libellé produit, A Charger")
        pick_files = st.file_uploader(
            "Picklist CSV",
            type=["csv"],
            accept_multiple_files=True,
            key="picklist_upload",
            label_visibility="collapsed",
        )
    with col_charg:
        st.markdown("### 🚚 Chargement(s) réel(s)")
        st.caption("Export ERP — colonnes : Stock Destination, Libellé produit, Quantité")
        charg_files = st.file_uploader(
            "Chargement CSV",
            type=["csv"],
            accept_multiple_files=True,
            key="chargement_upload",
            label_visibility="collapsed",
        )

    if not pick_files or not charg_files:
        st.info("Déposez au moins une picklist et un chargement pour lancer la comparaison.")
        return

    # ── Pairing ────────────────────────────────────────────
    if len(pick_files) == 1 and len(charg_files) == 1:
        paires = [(pick_files[0], charg_files[0])]
        lancer = True
    else:
        st.divider()
        st.markdown("### 🔗 Associer les fichiers")
        charg_options = {f.name: f for f in charg_files}
        paires = []
        for pf in pick_files:
            choix = st.selectbox(
                f"Chargement pour **{pf.name}**",
                options=list(charg_options.keys()),
                key=f"pair_{pf.name}",
            )
            paires.append((pf, charg_options[choix]))
        col_btn, _ = st.columns([1, 5])
        with col_btn:
            lancer = st.button("🔍 Analyser", type="primary", use_container_width=True)

    if not lancer:
        return

    # ── Analyse de chaque paire ────────────────────────────
    st.divider()
    use_tabs = len(paires) > 1
    if use_tabs:
        tabs      = st.tabs([pf.name for pf, _ in paires])
        contextes = [(tab, pf, cf) for tab, (pf, cf) in zip(tabs, paires)]
    else:
        contextes = [(None, paires[0][0], paires[0][1])]

    for ctx, pf, cf in contextes:
        try:
            picklist_df   = parse_picklist(pf.read())
            chargement_df = parse_chargement(cf.read())
        except Exception as e:
            msg = f"Erreur lecture fichiers ({pf.name} / {cf.name}) : {e}"
            if ctx:
                with ctx:
                    st.error(msg)
            else:
                st.error(msg)
            continue

        titre = pf.name.replace(".csv", "")
        if ctx:
            with ctx:
                st.markdown(f"### {titre}")
                _afficher_resultats(picklist_df, chargement_df)
        else:
            st.markdown(f"### {titre}")
            _afficher_resultats(picklist_df, chargement_df)
