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
import re

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


def _extract_date_from_filename(filename: str) -> datetime.date | None:
    """Extract date from filenames like export_distriprot_20260421_042131."""
    m = re.search(r'(\d{8})', filename)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return None


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


def parse_chargement_for_date(content: bytes, target_date: datetime.date) -> pd.DataFrame:
    """
    Variante de parse_chargement filtrée sur une date précise.
    La colonne Date de l'ADV est comparée à target_date (format français toléré).
    """
    df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.strip('"')

    if "Date" in df.columns:
        df["_d"] = pd.to_datetime(
            df["Date"].str.strip(), dayfirst=True, errors="coerce"
        ).dt.date
        df = df[df["_d"] == target_date].drop(columns=["_d"])

    if "Type tâche" in df.columns:
        df = df[df["Type tâche"].str.strip().str.strip('"') == "Chargement machine"]

    for col in ["Stock Destination", "Libellé produit", "Nom client", "Ressource"]:
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

    group_cols = ["Code Machine", "Nom client charg", "Libellé produit"]
    if "Ressource" in df.columns:
        return (
            df.groupby(group_cols, as_index=False)
            .agg(
                Quantité=("Quantité", "sum"),
                Ressource=("Ressource", lambda x: ", ".join(
                    sorted({v for v in x if v and v.lower() != "nan"})
                )),
            )
        )
    return df.groupby(group_cols, as_index=False)["Quantité"].sum()


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

    charg_cols = ["Code Machine", "Libellé produit", "Réel", "Nom client charg"]
    fill_vals  = {"Picklist": 0, "Réel": 0, "Nom client pick": "", "Nom client charg": ""}
    if "Ressource" in charg.columns:
        charg_cols.append("Ressource")
        fill_vals["Ressource"] = ""

    merged = pd.merge(
        pick,
        charg[charg_cols],
        on=["Code Machine", "Libellé produit"],
        how="left",
    ).fillna(fill_vals)

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


def generer_excel_hebdo(result_df: pd.DataFrame) -> bytes:
    """
    Export Excel hebdomadaire :
      - Sheet "Résumé salles"  : une ligne par salle, conformité sur la semaine
      - Sheet "Résumé jours"   : une ligne par jour, conformité globale
      - Sheet "Détail"         : toutes les lignes avec colonne Date
    """
    output = io.BytesIO()

    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
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

        has_date = "Date" in result_df.columns

        has_ressource = "Ressource" in result_df.columns

        # helper : employés uniques pour un groupe de lignes
        def _employes(grp_df):
            if not has_ressource:
                return ""
            vals = set()
            for v in grp_df["Ressource"].dropna():
                for part in str(v).split(","):
                    part = part.strip()
                    if part and part.lower() != "nan":
                        vals.add(part)
            return ", ".join(sorted(vals))

        # ── Sheet 1 : Résumé par salle ────────────────────────
        ws_salles = wb.add_worksheet("Résumé salles")
        h_salles = ["Machine", "Salle", "Employés", "Jours analysés", "Conformes",
                    "Non chargés", "Insuffisants", "Surplus", "Conformité %"]
        for c, h in enumerate(h_salles):
            ws_salles.write(0, c, h, header_fmt)

        salles_stats = []
        for machine, grp in result_df.groupby("Code Machine"):
            nom = grp["Nom client"].iloc[0] if not grp.empty else ""
            a_ch = grp[grp["Picklist"] > 0]
            total = len(a_ch)
            conf = int((a_ch["Statut"] == "Conforme").sum())
            pct = round(conf / total * 100) if total else 0
            jours = int(grp["Date"].nunique()) if has_date else 1
            salles_stats.append({
                "machine": machine, "nom": nom,
                "employes": _employes(grp),
                "jours": jours,
                "conf_str": f"{conf} / {total}",
                "nc": int((a_ch["Statut"] == "Non chargé").sum()),
                "insuf": int((a_ch["Statut"] == "Insuffisant").sum()),
                "surplus": int((a_ch["Statut"] == "Surplus").sum()),
                "pct": pct,
            })
        salles_stats.sort(key=lambda x: x["pct"], reverse=True)

        for r, s in enumerate(salles_stats, start=1):
            row_fmt = wb.add_format({
                "bg_color": _couleur_conformite(s["pct"]),
                "border": 1, "border_color": "#CCCCCC", "valign": "vcenter",
            })
            for c, val in enumerate([
                s["machine"], s["nom"], s["employes"], s["jours"], s["conf_str"],
                s["nc"], s["insuf"], s["surplus"], f"{s['pct']} %",
            ]):
                ws_salles.write(r, c, val, row_fmt)
        for c, w in enumerate([14, 38, 28, 14, 14, 13, 14, 10, 13]):
            ws_salles.set_column(c, c, w)

        # ── Sheet 2 : Résumé par jour ─────────────────────────
        if has_date:
            ws_jours = wb.add_worksheet("Résumé jours")
            h_jours = ["Date", "Nb machines", "Conformes", "Non chargés", "Insuffisants", "Conformité %"]
            for c, h in enumerate(h_jours):
                ws_jours.write(0, c, h, header_fmt)
            for r, (date, grp) in enumerate(result_df.groupby("Date"), start=1):
                a_ch = grp[grp["Picklist"] > 0]
                total = len(a_ch)
                conf = int((a_ch["Statut"] == "Conforme").sum())
                pct = round(conf / total * 100) if total else 0
                row_fmt = wb.add_format({
                    "bg_color": _couleur_conformite(pct),
                    "border": 1, "border_color": "#CCCCCC", "valign": "vcenter",
                })
                date_str = date.strftime("%d/%m/%Y") if hasattr(date, "strftime") else str(date)
                for c, val in enumerate([
                    date_str, int(grp["Code Machine"].nunique()),
                    f"{conf} / {total}",
                    int((a_ch["Statut"] == "Non chargé").sum()),
                    int((a_ch["Statut"] == "Insuffisant").sum()),
                    f"{pct} %",
                ]):
                    ws_jours.write(r, c, val, row_fmt)
            for c, w in enumerate([14, 14, 14, 13, 14, 13]):
                ws_jours.set_column(c, c, w)

        # ── Sheet 3 : Détail complet ──────────────────────────
        ws_detail = wb.add_worksheet("Détail")
        h_det = (["Date"] if has_date else []) + [
            "Machine", "Salle", "Produit", "Picklist", "Réel", "Écart", "Statut", "Commentaire",
        ] + (["Ressource"] if has_ressource else [])
        w_det = ([12] if has_date else []) + [14, 38, 38, 10, 8, 8, 18, 42] + ([28] if has_ressource else [])
        for c, h in enumerate(h_det):
            ws_detail.write(0, c, h, header_fmt)

        sort_cols = [col for col in ["Date", "Nom client", "Libellé produit"] if col in result_df.columns]
        for r, (_, row) in enumerate(result_df.sort_values(sort_cols).iterrows(), start=1):
            statut = row["Statut"]
            row_fmt = fmts.get(statut, default_fmt)
            ecart = row["Écart"]
            vals = []
            if has_date:
                d = row["Date"]
                vals.append(d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d))
            vals += [
                row["Code Machine"], row["Nom client"], row["Libellé produit"],
                int(row["Picklist"]), int(row["Réel"]),
                f"+{ecart}" if ecart > 0 else str(ecart),
                statut,
                row.get("Commentaire", ""),
            ]
            if has_ressource:
                vals.append(row.get("Ressource", ""))
            for c, val in enumerate(vals):
                ws_detail.write(r, c, val, row_fmt)
        for c, w in enumerate(w_det):
            ws_detail.set_column(c, c, w)

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

        st.divider()

        _STATUTS_PROBLEMES = {"Non chargé", "Insuffisant", "Surplus", "Quantité négative"}

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        def _hex_to_rgb(hex_c: str):
            return (int(hex_c[1:3], 16) / 255,
                    int(hex_c[3:5], 16) / 255,
                    int(hex_c[5:7], 16) / 255)

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

            # ── PNG complet pour cette salle ──────────────────
            if st.button(f"🖼️ PNG — {nom or m}", key=f"btn_png_{m}"):
                date_str = datetime.date.today().strftime("%d/%m/%Y")
                display_cols = ["Libellé produit", "Picklist", "Réel", "Écart", "Statut", "Commentaire"]
                col_labels   = ["Produit", "PL", "Réel", "Écart", "Statut", "Commentaire"]
                col_widths   = [0.32, 0.07, 0.07, 0.07, 0.16, 0.31]

                if df_m.empty:
                    fig, ax = plt.subplots(figsize=(6, 1.8))
                    ax.text(0.5, 0.5, "Aucune donnée pour cette salle",
                            ha="center", va="center", fontsize=13)
                    ax.axis("off")
                else:
                    df_disp = df_m[display_cols].copy()
                    df_disp["Écart"] = df_disp["Écart"].apply(
                        lambda v: f"+{v}" if v > 0 else str(v)
                    )
                    n = len(df_disp)
                    row_h    = 0.55          # hauteur par ligne (pouces)
                    header_h = 0.65
                    title_h  = 0.50
                    fig_h    = row_h * n + header_h + title_h + 0.3
                    fig_w    = 13

                    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
                    ax.set_position([0, 0, 1, 1])   # axes plein cadre
                    ax.axis("off")
                    fig.patch.set_facecolor("#F7F9FC")

                    row_colors = [
                        [_hex_to_rgb(_COULEURS.get(row["Statut"], "#FFFFFF"))] * len(col_labels)
                        for _, row in df_disp.iterrows()
                    ]

                    # espace réservé au titre en fraction de hauteur figure
                    title_frac  = title_h  / fig_h
                    table_y_top = 1.0 - title_frac - 0.02   # départ haut du tableau

                    tbl = ax.table(
                        cellText=df_disp.values.tolist(),
                        colLabels=col_labels,
                        cellColours=row_colors,
                        colColours=["#1B3D6F"] * len(col_labels),
                        loc="upper center",
                        cellLoc="left",
                        bbox=[0.0, 0.0, 1.0, table_y_top],
                    )
                    tbl.auto_set_font_size(False)
                    tbl.set_fontsize(10)

                    # hauteur uniforme des cellules
                    cell_h = 1.0 / (n + 1)
                    for (r, c), cell in tbl.get_celld().items():
                        cell.set_edgecolor("#CCCCCC")
                        cell.set_linewidth(0.6)
                        cell.set_width(col_widths[c])
                        cell.set_height(cell_h)
                        cell.PAD = 0.06
                        if r == 0:
                            cell.set_text_props(color="white", fontweight="bold")

                    ax.set_title(
                        f"Problèmes — {nom or m}  ({date_str})",
                        fontsize=12, fontweight="bold", pad=8,
                        color="#1B3D6F", loc="left", x=0.01,
                        y=table_y_top + 0.01,
                    )

                buf = io.BytesIO()
                fig.savefig(buf, format="png", bbox_inches="tight", dpi=150,
                            facecolor=fig.get_facecolor())
                plt.close(fig)
                st.download_button(
                    label="⬇️ Télécharger",
                    data=buf.getvalue(),
                    file_name=f"problemes_{m}_{datetime.date.today().strftime('%Y%m%d')}.png",
                    mime="image/png",
                    key=f"dl_png_{m}",
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
# HISTORIQUE PÉRIODE — MongoDB
# ─────────────────────────────────────────────────────────────────────────────

def _get_historique_col():
    from mongo_storage import _get_client
    client = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["picklist_historique"]


def _save_periode(result_df: pd.DataFrame, date_debut, date_fin, label: str) -> int:
    col = _get_historique_col()
    now = datetime.datetime.utcnow()
    col.delete_many({
        "label": label,
        "date_debut": date_debut.isoformat(),
        "date_fin": date_fin.isoformat(),
    })
    docs = [
        {
            "label":           label,
            "date_debut":      date_debut.isoformat(),
            "date_fin":        date_fin.isoformat(),
            "date_import":     now,
            "approvisionneur": str(row.get("Approvisionneur", "") or ""),
            "code_machine":    str(row.get("Code Machine", "") or ""),
            "nom_client":      str(row.get("Nom client", "") or ""),
            "libelle_produit": str(row.get("Libellé produit", "") or ""),
            "picklist":        int(row.get("Picklist", 0) or 0),
            "reel":            int(row.get("Réel", 0) or 0),
            "ecart":           int(row.get("Écart", 0) or 0),
            "statut":          str(row.get("Statut", "") or ""),
        }
        for _, row in result_df.iterrows()
    ]
    if docs:
        col.insert_many(docs)
    return len(docs)


def _load_historique() -> pd.DataFrame:
    try:
        col = _get_historique_col()
        docs = list(col.find({}, {"_id": 0}))
        if not docs:
            return pd.DataFrame()
        df = pd.DataFrame(docs)
        df["date_debut"] = pd.to_datetime(df["date_debut"], errors="coerce")
        df["date_fin"]   = pd.to_datetime(df["date_fin"],   errors="coerce")
        return df
    except Exception as e:
        st.error(f"Erreur chargement historique : {e}")
        return pd.DataFrame()


def _render_graphiques_historique(hist_df: pd.DataFrame):
    try:
        import plotly.express as px
    except ImportError:
        st.warning("Installez plotly (`pip install plotly`) pour afficher les graphiques.")
        return

    actif = hist_df[hist_df["picklist"] > 0].copy()
    if actif.empty:
        st.info("Pas de données exploitables.")
        return

    actif["conforme"] = actif["statut"] == "Conforme"

    # ── 1. Conformité par réapprovisionneur ──────────────────
    st.markdown("#### 🏆 Taux de conformité par réapprovisionneur")
    by_appro = (
        actif.groupby("approvisionneur")
        .agg(conformes=("conforme", "sum"), total=("conforme", "count"))
        .reset_index()
    )
    by_appro["pct"] = (by_appro["conformes"] / by_appro["total"] * 100).round(1)
    by_appro = by_appro.sort_values("pct", ascending=True)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            by_appro, x="pct", y="approvisionneur", orientation="h",
            text="pct", color="pct",
            color_continuous_scale=[[0, "#c0392b"], [0.5, "#f39c12"], [1, "#27ae60"]],
            range_color=[0, 100],
            labels={"pct": "Conformité %", "approvisionneur": ""},
        )
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(
            showlegend=False, coloraxis_showscale=False,
            margin=dict(l=0, r=60, t=10, b=10),
            height=max(300, 32 * len(by_appro)),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### 📊 Distribution des statuts")
        statut_counts = actif["statut"].value_counts().reset_index()
        statut_counts.columns = ["Statut", "Count"]
        COLOR_MAP_PIE = {
            "Conforme":          "#27ae60",
            "Insuffisant":       "#e74c3c",
            "Non chargé":        "#c0392b",
            "Surplus":           "#f39c12",
            "Non prévu":         "#3498db",
            "Quantité négative": "#00B0F0",
        }
        fig2 = px.pie(
            statut_counts, values="Count", names="Statut",
            color="Statut", color_discrete_map=COLOR_MAP_PIE, hole=0.4,
        )
        fig2.update_layout(margin=dict(l=0, r=0, t=10, b=10), height=350)
        st.plotly_chart(fig2, use_container_width=True)

    # ── 2. Évolution temporelle ──────────────────────────────
    st.markdown("#### 📈 Évolution de la conformité dans le temps")
    by_period = (
        actif.groupby(["date_debut", "approvisionneur"])
        .agg(conformes=("conforme", "sum"), total=("conforme", "count"))
        .reset_index()
    )
    by_period["pct"] = (by_period["conformes"] / by_period["total"] * 100).round(1)

    appros_dispo = sorted(by_period["approvisionneur"].unique())
    filtre_appros = st.multiselect(
        "Filtrer réapprovisionneurs",
        options=appros_dispo,
        default=appros_dispo,
        key="hist_appro_filter",
        label_visibility="collapsed",
    )
    df_plot = by_period[by_period["approvisionneur"].isin(filtre_appros)] if filtre_appros else by_period

    fig3 = px.line(
        df_plot, x="date_debut", y="pct", color="approvisionneur",
        markers=True,
        labels={"pct": "Conformité %", "date_debut": "Période", "approvisionneur": "Réappro"},
    )
    fig3.add_hline(y=80, line_dash="dash", line_color="orange",
                   annotation_text="Objectif 80%", annotation_position="bottom right")
    fig3.add_hline(y=95, line_dash="dash", line_color="green",
                   annotation_text="Excellence 95%", annotation_position="bottom right")
    fig3.update_layout(
        margin=dict(l=0, r=0, t=10, b=10), height=400,
        yaxis=dict(range=[0, 105]),
    )
    st.plotly_chart(fig3, use_container_width=True)

    # ── 3. Heatmap non-chargés ───────────────────────────────
    st.markdown("#### 🔥 Heatmap — Non chargés par réapprovisionneur et période")
    nc = hist_df[hist_df["statut"] == "Non chargé"].copy()
    if not nc.empty:
        nc["periode_label"] = nc["date_debut"].dt.strftime("%d/%m/%Y")
        pivot = (
            nc.groupby(["approvisionneur", "periode_label"])
            .size().reset_index(name="nb")
            .pivot(index="approvisionneur", columns="periode_label", values="nb")
            .fillna(0)
        )
        fig4 = px.imshow(
            pivot, color_continuous_scale="Reds", aspect="auto",
            labels={"color": "Non chargés"},
        )
        fig4.update_layout(
            margin=dict(l=0, r=0, t=10, b=10),
            height=max(250, 38 * len(pivot)),
        )
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.success("✅ Aucun produit non chargé dans l'historique.")

    # ── 4. Top produits non chargés ─────────────────────────
    col_nc, col_insuf = st.columns(2)
    with col_nc:
        st.markdown("#### 🚫 Top produits non chargés")
        if not nc.empty:
            top_nc = nc["libelle_produit"].value_counts().head(15).reset_index()
            top_nc.columns = ["Produit", "Occurrences"]
            fig5 = px.bar(
                top_nc, x="Occurrences", y="Produit", orientation="h",
                color="Occurrences", color_continuous_scale="Reds",
            )
            fig5.update_layout(
                showlegend=False, coloraxis_showscale=False,
                margin=dict(l=0, r=20, t=10, b=10), height=400,
            )
            st.plotly_chart(fig5, use_container_width=True)

    with col_insuf:
        st.markdown("#### ❌ Évolution non-conformités dans le temps")
        nc_time = (
            hist_df[hist_df["statut"].isin(["Non chargé", "Insuffisant", "Surplus"])]
            .groupby(["date_debut", "statut"])
            .size().reset_index(name="nb")
        )
        if not nc_time.empty:
            fig6 = px.bar(
                nc_time, x="date_debut", y="nb", color="statut",
                barmode="stack",
                color_discrete_map={
                    "Non chargé":  "#c0392b",
                    "Insuffisant": "#e74c3c",
                    "Surplus":     "#f39c12",
                },
                labels={"nb": "Nb lignes", "date_debut": "Période", "statut": "Statut"},
            )
            fig6.update_layout(margin=dict(l=0, r=0, t=10, b=10), height=400)
            st.plotly_chart(fig6, use_container_width=True)

    # ── 5. Tableau récap compétences ─────────────────────────
    st.markdown("#### 📋 Tableau de suivi des compétences")
    competences = (
        actif.groupby("approvisionneur")
        .agg(
            Périodes=("date_debut", "nunique"),
            Total_lignes=("conforme", "count"),
            Conformes=("conforme", "sum"),
            Non_charges=("statut", lambda x: (x == "Non chargé").sum()),
            Insuffisants=("statut", lambda x: (x == "Insuffisant").sum()),
            Surplus=("statut", lambda x: (x == "Surplus").sum()),
        )
        .reset_index()
    )
    competences["Taux conformité"] = (
        competences["Conformes"] / competences["Total_lignes"] * 100
    ).round(1).astype(str) + " %"
    competences = competences.rename(columns={
        "approvisionneur": "Réapprovisionneur",
        "Total_lignes": "Total lignes",
        "Non_charges": "Non chargés",
    })
    competences = competences.sort_values("Taux conformité", ascending=True)

    def _style_competences(row):
        try:
            pct_val = float(str(row["Taux conformité"]).replace("%", "").strip())
        except Exception:
            pct_val = 0
        bg = _couleur_conformite(int(pct_val))
        color = "color:white;" if pct_val < 35 else "color:#1a1a1a;"
        return [f"background-color:{bg};{color}"] * len(row)

    st.dataframe(
        competences.style.apply(_style_competences, axis=1),
        use_container_width=True,
        hide_index=True,
    )


def _render_periode_section():
    st.divider()
    st.markdown("## 📅 Analyse sur période & Suivi des compétences")
    st.caption(
        "Importez plusieurs picklists et un fichier ADV couvrant une période définie. "
        "Les données sont sauvegardées en base pour le suivi long terme des réapprovisionneurs."
    )

    # ── Paramètres période ─────────────────────────────────
    col_dates, col_label = st.columns([2, 2])
    with col_dates:
        dates = st.date_input(
            "Période analysée",
            value=(datetime.date.today() - datetime.timedelta(days=7), datetime.date.today()),
            format="DD/MM/YYYY",
            key="periode_dates",
        )
    with col_label:
        label_periode = st.text_input(
            "Nom / label",
            placeholder="ex : Semaine 16 — Avril 2026",
            key="periode_label",
        )

    if not isinstance(dates, tuple) or len(dates) != 2:
        st.warning("Sélectionnez une plage de dates (début → fin).")
        return
    date_debut, date_fin = dates
    label_final = label_periode.strip() or f"{date_debut.strftime('%d/%m/%Y')} → {date_fin.strftime('%d/%m/%Y')}"

    # ── Uploads ────────────────────────────────────────────
    col_pick, col_adv = st.columns(2)
    with col_pick:
        st.markdown("### 📋 Picklist(s)")
        st.caption("Un ou plusieurs fichiers CSV picklist (un par réappro ou par jour)")
        pick_files = st.file_uploader(
            "Picklists",
            type=["csv"],
            accept_multiple_files=True,
            key="periode_pick_upload",
            label_visibility="collapsed",
        )
    with col_adv:
        st.markdown("### 🚚 Fichier ADV")
        st.caption("Export ERP (même format que chargement) couvrant toute la période")
        adv_file = st.file_uploader(
            "ADV",
            type=["csv"],
            key="periode_adv_upload",
            label_visibility="collapsed",
        )

    if not pick_files or not adv_file:
        st.info("Déposez au moins une picklist et le fichier ADV pour lancer l'analyse.")
    else:
        col_btn, _ = st.columns([2, 6])
        with col_btn:
            analyser_btn = st.button(
                "🔍 Analyser la période",
                type="primary",
                use_container_width=True,
                key="periode_analyser_btn",
            )

        if analyser_btn:
            try:
                picks = [parse_picklist(pf.read()) for pf in pick_files]
                picklist_df = pd.concat(picks, ignore_index=True)
                chargement_df = parse_chargement(adv_file.read())
                result = analyser(picklist_df, chargement_df)
                st.session_state["periode_result"] = result
                st.session_state["periode_meta"] = {
                    "date_debut":  date_debut,
                    "date_fin":    date_fin,
                    "label":       label_final,
                }
            except Exception as e:
                st.error(f"❌ Erreur lors de l'analyse : {e}")

        result = st.session_state.get("periode_result")
        meta   = st.session_state.get("periode_meta", {})

        if result is not None:
            st.divider()
            st.markdown(f"### 📊 Résultats — {meta.get('label', '')}")

            # KPIs
            a_charger = result[result["Picklist"] > 0]
            total     = len(a_charger)
            conformes = (a_charger["Statut"] == "Conforme").sum()
            pct_g     = round(conformes / total * 100) if total else 0

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Conformité globale", f"{pct_g} %")
            k2.metric("✅ Conformes", f"{conformes} / {total}")
            k3.metric("🚫 Non chargés", (a_charger["Statut"] == "Non chargé").sum())
            k4.metric("❌ Insuffisants", (a_charger["Statut"] == "Insuffisant").sum())
            k5.metric("⚠️ Surplus", (a_charger["Statut"] == "Surplus").sum())

            st.markdown(_LEGENDE, unsafe_allow_html=True)

            # Par réapprovisionneur
            if "Approvisionneur" in result.columns:
                st.markdown("#### 👥 Par réapprovisionneur")
                rows_appro = []
                for appro, grp in result[result["Picklist"] > 0].groupby("Approvisionneur"):
                    s = _stats_machine(grp)
                    rows_appro.append({
                        "Réapprovisionneur": appro,
                        "Conformes":         f"{s['conformes']} / {s['total']}",
                        "Non chargés":       s["non_charges"],
                        "Insuffisants":      s["insuffisants"],
                        "Surplus":           s["surplus"],
                        "Conformité %":      f"{s['pct']} %",
                    })
                if rows_appro:
                    df_appro = pd.DataFrame(rows_appro)

                    def _style_appro(row):
                        try:
                            pct_v = int(str(row["Conformité %"]).replace("%", "").strip())
                        except Exception:
                            pct_v = 0
                        bg    = _couleur_conformite(pct_v)
                        color = "color:white;" if pct_v < 35 else "color:#1a1a1a;"
                        return [f"background-color:{bg};{color}"] * len(row)

                    st.dataframe(
                        df_appro.style.apply(_style_appro, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )

            # Sauvegarde
            st.divider()
            col_sv, _ = st.columns([2.5, 6])
            with col_sv:
                if st.button(
                    "💾 Sauvegarder dans l'historique",
                    key="periode_save_btn",
                    use_container_width=True,
                ):
                    try:
                        n = _save_periode(result, meta["date_debut"], meta["date_fin"], meta["label"])
                        st.success(f"✅ {n} lignes sauvegardées (période : {meta['label']}).")
                    except Exception as e:
                        st.error(f"❌ Erreur sauvegarde : {e}")

    # ── Graphiques historiques ─────────────────────────────
    st.divider()
    st.markdown("## 📈 Suivi historique des compétences")

    col_rf, _ = st.columns([1.5, 6])
    with col_rf:
        if st.button("🔄 Rafraîchir", key="hist_refresh"):
            st.rerun()

    hist_df = _load_historique()
    if hist_df.empty:
        st.info("Aucune donnée historique. Analysez et sauvegardez des périodes pour voir les graphiques.")
        return

    periodes = sorted(hist_df["label"].unique())
    st.caption(
        f"**{len(hist_df):,}** lignes · **{len(periodes)}** période(s) · "
        f"**{hist_df['approvisionneur'].nunique()}** réapprovisionneurs"
    )

    with st.expander("🔎 Filtres historique", expanded=False):
        col_fp, col_fa = st.columns(2)
        with col_fp:
            filtre_periodes = st.multiselect(
                "Périodes",
                options=periodes,
                default=periodes,
                key="hist_filtre_periodes",
            )
        with col_fa:
            appros_hist = sorted(hist_df["approvisionneur"].dropna().unique())
            filtre_appros_hist = st.multiselect(
                "Réapprovisionneurs",
                options=appros_hist,
                default=appros_hist,
                key="hist_filtre_appros",
            )
        if filtre_periodes:
            hist_df = hist_df[hist_df["label"].isin(filtre_periodes)]
        if filtre_appros_hist:
            hist_df = hist_df[hist_df["approvisionneur"].isin(filtre_appros_hist)]

    _render_graphiques_historique(hist_df)


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT HEBDOMADAIRE
# ─────────────────────────────────────────────────────────────────────────────

def _render_rapport_hebdomadaire():
    st.markdown(
        '<div style="color:#6c757d;margin-bottom:1.2rem;">'
        "Importez les picklists de chaque jour (nommées avec la date, ex : "
        "<code>export_distriprot_20260421_042131.csv</code>) et le fichier ADV "
        "de la semaine. Les chargements sont filtrés automatiquement par date."
        "</div>",
        unsafe_allow_html=True,
    )

    col_pick, col_adv = st.columns(2)
    with col_pick:
        st.markdown("### 📋 Picklists de la semaine")
        st.caption("Un CSV par jour — la date est lue dans le nom de fichier")
        pick_files = st.file_uploader(
            "Picklists",
            type=["csv"],
            accept_multiple_files=True,
            key="hebdo_pick_upload",
            label_visibility="collapsed",
        )
    with col_adv:
        st.markdown("### 🚚 Fichier ADV de la semaine")
        st.caption("Export ERP couvrant toute la semaine — filtré par date automatiquement")
        adv_file = st.file_uploader(
            "ADV",
            type=["csv"],
            key="hebdo_adv_upload",
            label_visibility="collapsed",
        )

    if not pick_files or not adv_file:
        st.info("Déposez les picklists et le fichier ADV pour lancer l'analyse.")
        return

    # ── Extraction des dates depuis les noms de fichiers ────
    fichiers_info = []
    erreurs_date  = []
    for pf in pick_files:
        d = _extract_date_from_filename(pf.name)
        if d:
            fichiers_info.append((pf, d))
        else:
            erreurs_date.append(pf.name)

    if erreurs_date:
        st.warning(f"Date non détectée dans ces fichiers (ignorés) : {', '.join(erreurs_date)}")
    if not fichiers_info:
        st.error("Aucun fichier avec une date valide dans le nom.")
        return

    fichiers_info.sort(key=lambda x: x[1])

    with st.expander(f"📆 {len(fichiers_info)} fichier(s) détecté(s)", expanded=True):
        for pf, d in fichiers_info:
            st.markdown(f"- `{pf.name}` → **{d.strftime('%d/%m/%Y')}**")

    # ── Lecture ADV une seule fois ──────────────────────────
    adv_content = adv_file.read()

    # ── Lecture et parse de chaque picklist ─────────────────
    parsed_picks = []
    all_products_set = set()
    for pf, d in fichiers_info:
        try:
            pick_df = parse_picklist(pf.read())
            all_products_set.update(pick_df["Libellé produit"].unique())
            parsed_picks.append((d, pick_df))
        except Exception as e:
            st.error(f"❌ Erreur lecture {pf.name} : {e}")

    if not parsed_picks:
        return

    # ── Produits en rupture ─────────────────────────────────
    tous_produits = sorted(all_products_set)
    ruptures = st.multiselect(
        "🚫 Produits en rupture (exclure de l'analyse et de l'export)",
        options=tous_produits,
        key="ruptures_hebdo",
        placeholder="Sélectionner les produits à exclure...",
    )

    # ── Analyse par jour ────────────────────────────────────
    all_results = []
    salles_sans_chargement = []  # [{date, machine, nom}]

    for d, pick_df in parsed_picks:
        try:
            charg_df = parse_chargement_for_date(adv_content, d)

            # Salles présentes dans la picklist mais absentes du chargement ce jour-là
            machines_pick  = set(pick_df["Code Machine"].unique())
            machines_charg = set(charg_df["Code Machine"].unique()) if not charg_df.empty else set()
            for m in machines_pick - machines_charg:
                nom = pick_df[pick_df["Code Machine"] == m]["Nom client"].iloc[0] \
                      if not pick_df[pick_df["Code Machine"] == m].empty else ""
                salles_sans_chargement.append({"Date": d.strftime("%d/%m/%Y"), "Machine": m, "Salle": nom})

            if charg_df.empty:
                st.warning(f"⚠️ Aucun chargement du tout pour le {d.strftime('%d/%m/%Y')}")

            res = analyser(pick_df, charg_df)
            res["Date"] = d
            all_results.append(res)
        except Exception as e:
            st.error(f"❌ Erreur analyse {d.strftime('%d/%m/%Y')} : {e}")

    if not all_results:
        st.error("Aucun résultat à afficher.")
        return

    result_df = pd.concat(all_results, ignore_index=True)

    if ruptures:
        result_df = result_df[~result_df["Libellé produit"].isin(ruptures)].reset_index(drop=True)

    # ── Salles sans chargement (Streamlit uniquement) ────────
    if salles_sans_chargement:
        with st.expander(
            f"🔴 {len(salles_sans_chargement)} salle(s) sans chargement au jour correspondant",
            expanded=True,
        ):
            st.caption("Ces salles sont présentes dans la picklist mais aucun chargement n'a été trouvé dans l'ADV pour la date du fichier.")
            st.dataframe(
                pd.DataFrame(salles_sans_chargement),
                use_container_width=True,
                hide_index=True,
            )

    # ── KPIs globaux ────────────────────────────────────────
    a_ch_g    = result_df[result_df["Picklist"] > 0]
    total_g   = len(a_ch_g)
    conf_g    = int((a_ch_g["Statut"] == "Conforme").sum())
    pct_g     = round(conf_g / total_g * 100) if total_g else 0
    nc_g      = int((a_ch_g["Statut"] == "Non chargé").sum())
    insuf_g   = int((a_ch_g["Statut"] == "Insuffisant").sum())
    surplus_g = int((a_ch_g["Statut"] == "Surplus").sum())
    np_g      = int((result_df["Statut"] == "Non prévu").sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Conformité globale", f"{pct_g} %")
    k2.metric("✅ Conformes", f"{conf_g} / {total_g}")
    k3.metric("🚫 Non chargés", nc_g)
    k4.metric("❌ Insuffisants", insuf_g)
    k5.metric("⚠️ Surplus / Non prévus", f"{surplus_g} + {np_g}")

    st.markdown(_LEGENDE, unsafe_allow_html=True)

    has_ressource = "Ressource" in result_df.columns

    def _employes_for_group(grp_df):
        if not has_ressource:
            return ""
        vals = set()
        for v in grp_df["Ressource"].dropna():
            for part in str(v).split(","):
                part = part.strip()
                if part and part.lower() != "nan":
                    vals.add(part)
        return ", ".join(sorted(vals))

    # ── Résumé par salle ────────────────────────────────────
    st.markdown("### 🏢 Résumé par salle")

    # Machines ayant au moins un jour sans chargement
    machines_non_faites = {entry["Machine"] for entry in salles_sans_chargement}

    salles_rows = []
    for machine, grp in result_df.groupby("Code Machine"):
        nom  = grp["Nom client"].iloc[0] if not grp.empty else ""
        a_ch = grp[grp["Picklist"] > 0]
        total = len(a_ch)
        conf  = int((a_ch["Statut"] == "Conforme").sum())
        pct   = round(conf / total * 100) if total else 0
        row = {
            "Machine":      machine,
            "Salle":        nom,
            "Jours":        int(grp["Date"].nunique()),
            "Conformes":    f"{conf} / {total}",
            "Non chargés":  int((a_ch["Statut"] == "Non chargé").sum()),
            "Insuffisants": int((a_ch["Statut"] == "Insuffisant").sum()),
            "Surplus":      int((a_ch["Statut"] == "Surplus").sum()),
            "Conformité":   f"{pct} %",
            "_pct":         pct,
            "_non_faite":   machine in machines_non_faites,
        }
        if has_ressource:
            row["Employés"] = _employes_for_group(grp)
        salles_rows.append(row)
    salles_rows.sort(key=lambda x: x["_pct"], reverse=True)

    def _row_display(r):
        return {k: v for k, v in r.items() if k not in ("_pct", "_non_faite")}

    pcts_all = [r["_pct"] for r in salles_rows]
    df_salles = pd.DataFrame([_row_display(r) for r in salles_rows])

    def _style_salle_row(row, pcts_list, df_ref):
        idx = df_ref.index.get_loc(row.name)
        pct_val = pcts_list[idx]
        bg    = _couleur_conformite(pct_val)
        color = "color:white;" if pct_val < 35 or pct_val > 80 else "color:#1a1a1a;"
        return [f"background-color:{bg};{color}"] * len(row)

    n_show   = min(3, len(salles_rows))
    col_best, col_worst = st.columns(2)

    with col_best:
        st.markdown("#### 🏆 Meilleures salles")
        best_rows = salles_rows[:n_show]
        best_pcts = [r["_pct"] for r in best_rows]
        df_best   = pd.DataFrame([_row_display(r) for r in best_rows])
        st.dataframe(
            df_best.style.apply(_style_salle_row, pcts_list=best_pcts, df_ref=df_best, axis=1),
            use_container_width=True, hide_index=True,
        )

    with col_worst:
        # Inclure : salles non faites au moins 1 jour OU pct < 80 %
        # Tri : non-faites d'abord, puis par pct croissant
        worst_rows = sorted(
            [r for r in salles_rows if r["_non_faite"] or r["_pct"] < 80],
            key=lambda x: (not x["_non_faite"], x["_pct"]),
        )
        label_worst = f"#### ⚠️ Salles à améliorer ({len(worst_rows)})"
        st.markdown(label_worst)
        if worst_rows:
            worst_pcts = [r["_pct"] for r in worst_rows]
            df_worst   = pd.DataFrame([_row_display(r) for r in worst_rows])
            st.dataframe(
                df_worst.style.apply(_style_salle_row, pcts_list=worst_pcts, df_ref=df_worst, axis=1),
                use_container_width=True, hide_index=True,
                height=min(40 + 35 * len(worst_rows), 500),
            )
        else:
            st.success("Toutes les salles sont conformes (≥ 80 %) et n'ont aucun jour manquant.")

    with st.expander(f"📊 Toutes les salles ({len(salles_rows)})", expanded=False):
        st.dataframe(
            df_salles.style.apply(_style_salle_row, pcts_list=pcts_all, df_ref=df_salles, axis=1),
            use_container_width=True, hide_index=True,
            height=min(40 + 35 * len(salles_rows), 600),
        )

    # ── Résumé par jour ─────────────────────────────────────
    st.markdown("### 📆 Résumé par jour")
    jours_rows = []
    for date, grp in result_df.groupby("Date"):
        a_ch  = grp[grp["Picklist"] > 0]
        total = len(a_ch)
        conf  = int((a_ch["Statut"] == "Conforme").sum())
        pct   = round(conf / total * 100) if total else 0
        jours_rows.append({
            "Date":         date.strftime("%d/%m/%Y"),
            "Machines":     int(grp["Code Machine"].nunique()),
            "Conformes":    f"{conf} / {total}",
            "Non chargés":  int((a_ch["Statut"] == "Non chargé").sum()),
            "Insuffisants": int((a_ch["Statut"] == "Insuffisant").sum()),
            "Conformité":   f"{pct} %",
            "_pct":         pct,
        })
    jours_pcts = [r["_pct"] for r in jours_rows]
    df_jours   = pd.DataFrame([_row_without_pct(r) for r in jours_rows])

    st.dataframe(
        df_jours.style.apply(_style_salle_row, pcts_list=jours_pcts, df_ref=df_jours, axis=1),
        use_container_width=True, hide_index=True,
    )

    # ── Export Excel ─────────────────────────────────────────
    st.divider()
    col_dl, _ = st.columns([1, 4])
    with col_dl:
        excel_bytes = generer_excel_hebdo(result_df)
        date_str = datetime.date.today().strftime("%Y%m%d")
        st.download_button(
            label="⬇️ Télécharger Excel hebdomadaire",
            data=excel_bytes,
            file_name=f"rapport_hebdo_{date_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

def _render_quotidien():
    st.markdown(
        '<div style="color:#6c757d;margin-bottom:1.2rem;">'
        "Comparez la picklist prévue avec le chargement réel — "
        "détectez les produits non chargés, insuffisants ou en surplus, machine par machine."
        "</div>",
        unsafe_allow_html=True,
    )

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

    _render_periode_section()


def render():
    st.markdown("## 📋 Picklist vs Chargement")
    tab_quot, tab_hebdo = st.tabs(["📋 Analyse quotidienne", "📅 Rapport hebdomadaire"])
    with tab_quot:
        _render_quotidien()
    with tab_hebdo:
        _render_rapport_hebdomadaire()
