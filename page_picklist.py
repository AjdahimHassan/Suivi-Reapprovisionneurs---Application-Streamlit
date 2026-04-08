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

import colorsys
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
        .astype(int)
    )
    for col in ["Code Machine", "Nom client", "Libellé produit", "Approvisionneur"]:
        if col in df.columns:
            df[col] = df[col].str.strip().str.strip('"')
    cols = ["Code Machine", "Nom client", "Libellé produit", "A Charger"]
    if "Approvisionneur" in df.columns:
        cols.append("Approvisionneur")
    return df[cols]


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
    "Conforme":          "#d4edda",
    "Insuffisant":       "#f8d7da",
    "Non chargé":        "#c0392b",
    "Surplus":           "#ffeeba",
    "Non prévu":         "#d1ecf1",
    "Rien à charger":    "#f4f4f4",
    "Quantité négative": "#00B0F0",
}

_ORDRE_STATUT = {
    "Non chargé":        0,
    "Insuffisant":       1,
    "Surplus":           2,
    "Non prévu":         3,
    "Conforme":          4,
    "Rien à charger":    5,
    "Quantité négative": 6,
}


def _statut(picklist: int, reel: int) -> str:
    if picklist < 0:
        return "Quantité négative"
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


_COMMENTAIRES = {
    "Conforme":          "Chargement conforme à la picklist",
    "Insuffisant":       "Moins chargé que prévu",
    "Non chargé":        "Produit prévu mais absent du chargement",
    "Surplus":           "Plus chargé que prévu",
    "Non prévu":         "Chargé mais non prévu dans la picklist",
    "Rien à charger":    "Rien à charger, rien de chargé",
    "Quantité négative": "Quantité négative dans la picklist",
}


def _commentaire(statut: str) -> str:
    return _COMMENTAIRES.get(statut, "")


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
        how="left",
    ).fillna({"Picklist": 0, "Réel": 0, "Nom client pick": "", "Nom client charg": ""})

    merged["Picklist"] = merged["Picklist"].astype(int)
    merged["Réel"]     = merged["Réel"].astype(int)
    merged["Écart"]    = merged["Réel"] - merged["Picklist"]
    merged["Statut"]      = merged.apply(lambda r: _statut(r["Picklist"], r["Réel"]), axis=1)
    merged["Commentaire"] = merged["Statut"].map(_commentaire)
    # Coalesce nom client
    merged["Nom client"] = merged["Nom client pick"].where(
        merged["Nom client pick"] != "", merged["Nom client charg"]
    )

    merged = (
        merged
        .sort_values(["Nom client", "Libellé produit"])
        .drop(columns=["Nom client pick", "Nom client charg"])
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
        color  = "color: white;" if statut in ("Non chargé", "Quantité négative") else ""
        style  = f"background-color: {bg}; {color}" if bg else ""
        return [style] * len(row)

    styled = df.style.apply(ligne, axis=1)

    def ecart_color(val):
        if val > 0:  return "color: #856404;"
        if val < 0:  return "color: #721c24;"
        return "color: #155724;"

    styled = styled.map(ecart_color, subset=["Écart"])
    styled = styled.format({"Écart": _formater_ecart})
    return styled


def _couleur_conformite(pct: int) -> str:
    """Dégradé continu rouge→orange→vert selon le % de conformité (0-100)."""
    pct = max(0, min(100, pct))
    if pct <= 50:
        t = pct / 50
        r = int(220 + (255 - 220) * t)
        g = int(53  + (176 - 53)  * t)
        b = int(69  + (0   - 69)  * t)
    else:
        t = (pct - 50) / 50
        r = int(255 + (40  - 255) * t)
        g = int(176 + (167 - 176) * t)
        b = int(0   + (69  - 0)   * t)
    return f"#{r:02X}{g:02X}{b:02X}"


_LEGENDE = """
<div style="display:flex;gap:0.8rem;flex-wrap:wrap;margin:0.4rem 0 1rem 0;font-size:0.80rem;">
  <span style="background:#d4edda;padding:2px 8px;border-radius:4px;">✅ Conforme</span>
  <span style="background:#f8d7da;padding:2px 8px;border-radius:4px;">❌ Insuffisant</span>
  <span style="background:#c0392b;color:white;padding:2px 8px;border-radius:4px;">🚫 Non chargé</span>
  <span style="background:#ffeeba;padding:2px 8px;border-radius:4px;">⚠️ Surplus</span>
  <span style="background:#d1ecf1;padding:2px 8px;border-radius:4px;">📋 Non prévu</span>
  <span style="background:#f4f4f4;padding:2px 8px;border-radius:4px;">— Rien à charger</span>
  <span style="background:#00B0F0;color:white;padding:2px 8px;border-radius:4px;">🔵 Quantité négative</span>
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
    machines = (
        result_df.drop_duplicates("Code Machine")
        .sort_values("Nom client")["Code Machine"]
        .tolist()
    )

    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        # ── Formats ──────────────────────────────────────────
        def fmt(bg, font="#000000", bold=False):
            return wb.add_format({
                "bg_color": bg, "font_color": font,
                "bold": bold, "border": 1, "border_color": "#CCCCCC",
                "valign": "vcenter",
            })

        fmts = {
            "Conforme":          fmt("#d4edda"),
            "Insuffisant":       fmt("#f8d7da"),
            "Non chargé":        fmt("#c0392b", font="#FFFFFF"),
            "Surplus":           fmt("#ffeeba"),
            "Non prévu":         fmt("#d1ecf1"),
            "Rien à charger":    fmt("#f4f4f4"),
            "Quantité négative": fmt("#00B0F0", font="#FFFFFF"),
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
            try:
                pct = int(str(row[-1]).replace("%", "").strip())
            except Exception:
                pct = 0
            row_fmt = wb.add_format({
                "bg_color": _couleur_conformite(pct),
                "border": 1, "border_color": "#CCCCCC", "valign": "vcenter",
            })
            for c, val in enumerate(row):
                ws_recap.write(r, c, val, row_fmt)
        for c, w in enumerate([14, 38, 14, 13, 14, 10, 11, 13]):
            ws_recap.set_column(c, c, w)

        # ── Sheet Détail (toutes machines) ────────────────────
        headers_det = ["Machine", "Client", "Produit", "Picklist", "Réel", "Écart", "Statut", "Commentaire"]
        widths_det  = [14, 38, 38, 10, 8, 8, 18, 42]
        rows_det = []
        for _, row in result_df.sort_values(["Nom client", "Libellé produit"]).iterrows():
            ecart = row["Écart"]
            rows_det.append([
                row["Code Machine"], row["Nom client"], row["Libellé produit"],
                row["Picklist"], row["Réel"],
                f"+{ecart}" if ecart > 0 else str(ecart),
                row["Statut"],
                row.get("Commentaire", ""),
            ])
        _ecrire_feuille(wb.add_worksheet("Détail"), headers_det, rows_det, widths_det, statut_col_idx=6)

        # ── Une sheet par machine ─────────────────────────────
        headers_m = ["Produit", "Picklist", "Réel", "Écart", "Statut", "Commentaire"]
        widths_m  = [40, 10, 8, 8, 18, 42]
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
                    row.get("Commentaire", ""),
                ]
                for c, val in enumerate(vals):
                    ws_m.write(r, c, val, row_fmt)
            for c, w in enumerate(widths_m):
                ws_m.set_column(c, c, w)

    return output.getvalue()


def _afficher_resultats(picklist_df: pd.DataFrame, chargement_df: pd.DataFrame):
    result = analyser(picklist_df, chargement_df)

    # ── Filtre ruptures ────────────────────────────────────
    tous_produits = sorted(result["Libellé produit"].unique())
    ruptures = st.multiselect(
        "🚫 Produits en rupture (exclure de l'analyse et de l'export)",
        options=tous_produits,
        key="ruptures_picklist",
        placeholder="Sélectionner les produits à exclure...",
    )
    if ruptures:
        result = result[~result["Libellé produit"].isin(ruptures)].reset_index(drop=True)

    machines = (
        result.drop_duplicates("Code Machine")
        .sort_values("Nom client")["Code Machine"]
        .tolist()
    )

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
            try:
                pct = int(str(row["Conformité"]).replace("%", "").strip())
            except Exception:
                pct = 0
            bg = _couleur_conformite(pct)
            color = "color:white;" if pct < 35 or pct > 80 else "color:#1a1a1a;"
            return [f"background-color:{bg};{color}"] * len(row)

        st.dataframe(
            df_recap.style.apply(_style_recap, axis=1),
            use_container_width=True,
            height=min(40 + 35 * len(rows), 500),
            hide_index=True,
        )

    # ── Détail par machine ─────────────────────────────────
    with st.expander(f"🔍 Détail par machine", expanded=False):

        # Filtres
        f1, f2 = st.columns(2)
        with f1:
            reapros_dispo = sorted(result["Approvisionneur"].dropna().unique()) if "Approvisionneur" in result.columns else []
            filtre_reapro = st.multiselect(
                "Filtrer par réappro",
                options=reapros_dispo,
                key="filtre_reapro_detail",
                placeholder="Tous les réapprovisionneurs",
            )
        with f2:
            salles_dispo = sorted(result["Nom client"].dropna().unique())
            filtre_salle = st.multiselect(
                "Filtrer par salle",
                options=salles_dispo,
                key="filtre_salle_detail",
                placeholder="Toutes les salles",
            )

        # Appliquer les filtres sur la liste des machines
        machines_detail = machines[:]
        if filtre_reapro or filtre_salle:
            mask = pd.Series(True, index=result.index)
            if filtre_reapro and "Approvisionneur" in result.columns:
                mask &= result["Approvisionneur"].isin(filtre_reapro)
            if filtre_salle:
                mask &= result["Nom client"].isin(filtre_salle)
            codes_filtres = set(result[mask]["Code Machine"].unique())
            machines_detail = [m for m in machines_detail if m in codes_filtres]

        # Bouton PNG des problèmes
        _STATUTS_PROBLEMES = {"Non chargé", "Insuffisant", "Surplus", "Quantité négative"}
        df_prob = result[
            result["Code Machine"].isin(machines_detail) &
            result["Statut"].isin(_STATUTS_PROBLEMES)
        ]
        if st.button("🖼️ Générer PNG des problèmes", key="btn_png_problemes"):
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            date_str = datetime.date.today().strftime("%d/%m/%Y")

            if df_prob.empty:
                fig, ax = plt.subplots(figsize=(7, 2))
                ax.text(0.5, 0.5, "✅ Aucun problème détecté", ha="center", va="center",
                        fontsize=14, color="#28a745")
                ax.axis("off")
            else:
                display_cols  = ["Nom client", "Libellé produit", "Picklist", "Réel", "Écart", "Statut"]
                col_labels    = ["Salle", "Produit", "PL", "Réel", "Écart", "Statut"]
                col_widths    = [0.20, 0.35, 0.07, 0.07, 0.07, 0.14]

                df_disp = df_prob[display_cols].copy()
                df_disp["Écart"] = df_disp["Écart"].apply(lambda v: f"+{v}" if v > 0 else str(v))

                n = len(df_disp)
                fig_h = max(2.5, 0.38 * n + 1.8)
                fig, ax = plt.subplots(figsize=(14, fig_h))
                ax.axis("off")
                fig.patch.set_facecolor("#F7F9FC")

                row_colors = []
                for _, row in df_disp.iterrows():
                    hex_c = _COULEURS.get(row["Statut"], "#FFFFFF")
                    r2 = int(hex_c[1:3], 16) / 255
                    g2 = int(hex_c[3:5], 16) / 255
                    b2 = int(hex_c[5:7], 16) / 255
                    row_colors.append([(r2, g2, b2)] * len(col_labels))

                tbl = ax.table(
                    cellText=df_disp.values.tolist(),
                    colLabels=col_labels,
                    cellColours=row_colors,
                    colColours=[("#1B3D6F",)] * len(col_labels),
                    loc="center",
                    cellLoc="left",
                )
                tbl.auto_set_font_size(False)
                tbl.set_fontsize(8.5)
                for (r, c), cell in tbl.get_celld().items():
                    cell.set_edgecolor("#CCCCCC")
                    if r == 0:
                        cell.set_text_props(color="white", fontweight="bold")
                    cell.set_linewidth(0.5)
                    # manual col width
                    cell.set_width(col_widths[c])

                ax.set_title(
                    f"Problèmes détectés — Picklist vs Chargement ({date_str})",
                    fontsize=12, fontweight="bold", pad=10, color="#1B3D6F",
                )

            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            st.download_button(
                label="⬇️ Télécharger le PNG",
                data=buf.getvalue(),
                file_name=f"problemes_picklist_{datetime.date.today().strftime('%Y%m%d')}.png",
                mime="image/png",
                key="dl_png_problemes",
            )

        st.divider()

        for m in machines_detail:
            df_m = result[result["Code Machine"] == m].copy()
            nom  = df_m["Nom client"].iloc[0] if not df_m.empty else ""
            s    = _stats_machine(df_m)

            badge_color = _couleur_conformite(s["pct"])
            text_color  = "white" if s["pct"] < 35 or s["pct"] > 80 else "#1a1a1a"
            st.markdown(
                f'<div style="margin:1rem 0 0.3rem 0;">'
                f'<b style="font-size:1rem;">{m}</b> — {nom} &nbsp;'
                f'<span style="background:{badge_color};color:{text_color};padding:2px 10px;'
                f'border-radius:10px;font-size:0.85rem;">'
                f'{s["pct"]} % conforme</span></div>',
                unsafe_allow_html=True,
            )

            cols = ["Libellé produit", "Picklist", "Réel", "Écart", "Statut", "Commentaire"]
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
