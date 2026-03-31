import streamlit as st
import pandas as pd
import io
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from planogrammes_storage import load_produits
from mongo_storage import load_plannings_from_mongo

# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 1 — INDÉFINIS
# ─────────────────────────────────────────────────────────────────────────────

def _detect_sep(raw: str) -> str:
    first_line = raw.split("\n")[0]
    return ";" if first_line.count(";") >= first_line.count(",") else ","


def parse_ventes(file_bytes: bytes) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            raw = file_bytes.decode(enc)
            break
        except Exception:
            continue
    sep = _detect_sep(raw)
    df = pd.read_csv(io.StringIO(raw), sep=sep, quotechar='"', dtype=str)
    df.columns = [c.strip().replace('"', "") for c in df.columns]

    rename = {}
    for col in df.columns:
        cu = col.upper()
        if "CODE" in cu and "PRODUIT" in cu:
            rename[col] = "CODE_PRODUIT"
        elif cu in ("PU", "PRIX UNITAIRE", "PRIX_UNITAIRE", "PRIXUNITAIRE"):
            rename[col] = "PU"
        elif "LDP" in cu or "LIGNE" in cu:
            rename[col] = "LDP"
        elif "MACHINE" in cu:
            rename[col] = "CODE_MACHINE"
        elif "CLIENT" in cu and "CODE" in cu:
            rename[col] = "CODE_CLIENT"
    df = df.rename(columns=rename)

    if "CODE_PRODUIT" not in df.columns:
        raise ValueError("Colonne CODE_PRODUIT introuvable dans le fichier de ventes.")

    if "PU" in df.columns:
        df["PU"] = pd.to_numeric(
            df["PU"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
        )

    if "LDP" in df.columns:
        df["LDP"] = pd.to_numeric(
            df["LDP"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
        )

    df["CODE_PRODUIT"] = df["CODE_PRODUIT"].astype(str).str.strip().str.upper()
    return df


def parse_planno(file_bytes: bytes) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            raw = file_bytes.decode(enc)
            break
        except Exception:
            continue
    sep = _detect_sep(raw)
    lines = raw.splitlines()

    header_idx = 0
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("code") or line.strip().lower().startswith('"code'):
            header_idx = i
            break

    body = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(body), sep=sep, quotechar='"', dtype=str)
    df.columns = [c.strip().replace('"', "") for c in df.columns]

    rename = {}
    for col in df.columns:
        cu = col.upper()
        if "CODE" in cu and "PRODUIT" in cu:
            rename[col] = "CODE_PRODUIT"
        elif cu == "CODE":
            rename[col] = "CODE_PRODUIT"
        elif "LIBELLE" in cu or "LIBELLÉ" in cu or "NOM" in cu:
            rename[col] = "LIBELLE"
        elif "LDP" in cu or ("LIGNE" in cu and "PRIX" in cu):
            rename[col] = "LDP"
        elif cu in ("PU", "PRIX UNITAIRE", "PRIX_UNITAIRE"):
            rename[col] = "PU"
        elif "NIV" in cu and "HAUT" in cu:
            rename[col] = "NIV_HAUT"
        elif "UNITE" in cu or "UNITÉ" in cu:
            rename[col] = "UNITE"
    df = df.rename(columns=rename)

    if "CODE_PRODUIT" not in df.columns:
        raise ValueError("Colonne CODE_PRODUIT introuvable dans le planogramme.")

    if "PU" in df.columns:
        df["PU"] = pd.to_numeric(
            df["PU"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
        )
    if "LDP" in df.columns:
        df["LDP"] = pd.to_numeric(
            df["LDP"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
        )

    df["CODE_PRODUIT"] = df["CODE_PRODUIT"].astype(str).str.strip().str.upper()
    df = df[df["CODE_PRODUIT"].notna() & (df["CODE_PRODUIT"] != "") & (df["CODE_PRODUIT"] != "NAN")]
    return df


def analyser_indefinis(df_ventes: pd.DataFrame, df_planno: pd.DataFrame) -> list:
    indefinis = df_ventes[df_ventes["CODE_PRODUIT"] == "INDEFINI"].copy()
    if indefinis.empty or "PU" not in indefinis.columns:
        return []

    codes_vendus = set(
        df_ventes[df_ventes["CODE_PRODUIT"] != "INDEFINI"]["CODE_PRODUIT"].unique()
    )

    resultats = []
    prix_traites = set()

    for _, row in indefinis.iterrows():
        prix = row.get("PU")
        if pd.isna(prix) or prix in prix_traites:
            continue
        prix_traites.add(prix)

        if "PU" in df_planno.columns:
            meme_prix = df_planno[abs(df_planno["PU"] - prix) < 0.01].copy()
        else:
            meme_prix = pd.DataFrame()

        suspects = meme_prix[~meme_prix["CODE_PRODUIT"].isin(codes_vendus)]
        autres_vendus = meme_prix[meme_prix["CODE_PRODUIT"].isin(codes_vendus)]

        resultats.append({
            "prix": prix,
            "indefini_rows": indefinis[abs(indefinis["PU"] - prix) < 0.01],
            "planno_meme_prix": meme_prix,
            "suspects": suspects,
            "autres_vendus": autres_vendus,
        })

    return resultats


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 2 — CONTRÔLE DES PRIX
# ─────────────────────────────────────────────────────────────────────────────

_TOLERANCE_HT = 0.05


def parse_ventes_prix(file_bytes: bytes) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            raw = file_bytes.decode(enc)
            break
        except Exception:
            continue

    df = pd.read_csv(io.StringIO(raw), sep=";", quotechar='"', dtype=str)
    df.columns = [c.strip().replace('"', "") for c in df.columns]

    # Filtre "Audit Telemetrie" si la colonne existe
    col_type = next(
        (c for c in df.columns if "type" in c.lower() and "che" in c.lower()), None
    )
    if col_type:
        df = df[df[col_type].astype(str).str.strip().str.lower() == "audit telemetrie"]

    col_map = {
        "Code DA":          "Machine",
        "Stock Destination": "Code_client",
        "Nom client":       "Salle",
        "Code produit":     "Code",
        "Libellé produit":  "Produit",
        "Quantité":         "Quantité",
        "Montant HT":       "Montant_HT",
        "Date":             "Date",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    for num_col in ("Quantité", "Montant_HT"):
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(
                df[num_col].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
            )

    df = df[df["Quantité"].notna() & (df["Quantité"] > 0)]
    df = df[df["Montant_HT"].notna()]

    df["PU_HT"] = (df["Montant_HT"] / df["Quantité"]).round(3)

    cols = [c for c in ("Date", "Machine", "Code_client", "Salle", "Code", "Produit", "Quantité", "Montant_HT", "PU_HT") if c in df.columns]
    return df[cols].reset_index(drop=True)


def analyser_prix(df: pd.DataFrame, produits: list, tolerance: float = _TOLERANCE_HT):
    # Construit {code: [prix1, prix2, ...]} pour gérer les produits
    # qui ont plusieurs prix valides selon la machine (ex: Red Bull 2,84 € ou 3,03 €)
    lib = {}
    for p in produits:
        code = str(p.get("code", "")).strip().upper()
        prix = p.get("prix_ht", None)
        if code and prix:
            try:
                prix_float = round(float(str(prix).replace(",", ".")), 3)
                lib.setdefault(code, [])
                if prix_float not in lib[code]:
                    lib[code].append(prix_float)
            except (ValueError, TypeError):
                pass

    anomalies = []
    non_ref = set()

    for _, row in df.iterrows():
        code = str(row.get("Code", "")).strip().upper()
        pu = row.get("PU_HT")
        if pd.isna(pu):
            continue
        if code not in lib:
            non_ref.add(code)
            continue
        prix_valides = lib[code]
        # OK si le prix réel est proche d'AU MOINS UN prix valide
        ecarts = [round(pu - p, 3) for p in prix_valides]
        ecart_min = min(ecarts, key=abs)
        if abs(ecart_min) > tolerance:
            # Affiche le prix valide le plus proche comme référence
            attendu = prix_valides[ecarts.index(ecart_min)]
            anomalies.append({
                "Date": row.get("Date", ""),
                "Machine": row.get("Machine", ""),
                "Code_client": str(row.get("Code_client", "")).strip().upper(),
                "Salle": row.get("Salle", ""),
                "Code": code,
                "Produit": row.get("Produit", ""),
                "Prix attendu (HT)": attendu,
                "Prix réel (HT)": pu,
                "Écart (€)": ecart_min,
            })

    anomalies_df = pd.DataFrame(anomalies)
    if not anomalies_df.empty:
        anomalies_df = anomalies_df.sort_values(
            "Écart (€)", key=abs, ascending=False
        ).reset_index(drop=True)

    return anomalies_df, non_ref


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT PAR RÉAPPRO
# ─────────────────────────────────────────────────────────────────────────────

def build_reappro_mapping(plannings: dict) -> dict:
    """
    Construit un dictionnaire {code_client_upper: reappro} depuis les plannings MongoDB.
    Le code client est la partie avant " - " dans le champ client du planning.
    Ex: "FPPY01F - FP TARBES" → code = "FPPY01F"
    """
    mapping = {}
    for reappro, jours in plannings.items():
        for salles in jours.values():
            for client, _ in salles:
                code = client.split(" - ")[0].strip().upper()
                if code:
                    mapping[code] = reappro
    return mapping


def generer_export_reappros(anomalies_df: pd.DataFrame, reappro_map: dict, filtrer: list = None) -> bytes:
    """
    Génère un fichier Excel avec une feuille Résumé + une feuille par réappro.
    Si `filtrer` est fourni (liste de codes réappro), seuls ceux-ci sont inclus.
    """
    """
    Génère un fichier Excel avec une feuille Résumé + une feuille par réappro.
    Chaque feuille liste les salles problématiques avec le détail des produits.
    """
    # Styles communs
    HDR_FILL   = PatternFill("solid", fgColor="1F4E79")
    HDR_FONT   = Font(bold=True, color="FFFFFF")
    SALLE_FILL = PatternFill("solid", fgColor="D9E1F2")
    SALLE_FONT = Font(bold=True, color="1F4E79")
    FILL_RED   = PatternFill("solid", fgColor="F5C6CB")
    FILL_ORA   = PatternFill("solid", fgColor="FFD8A8")
    FILL_YEL   = PatternFill("solid", fgColor="FFF3CD")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _ecart_fill(ecart):
        a = abs(ecart)
        if a >= 0.50: return FILL_RED
        if a >= 0.20: return FILL_ORA
        return FILL_YEL

    def _apply_hdr(ws, headers, row=1):
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=col, value=h)
            c.fill = HDR_FILL
            c.font = HDR_FONT
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border

    # Assigner chaque anomalie à un réappro
    df = anomalies_df.copy()
    df["Réappro"] = df["Code_client"].apply(
        lambda x: reappro_map.get(str(x).strip().upper(), "Non assigné")
    )
    # Filtrer sur la sélection si fournie
    if filtrer:
        df = df[df["Réappro"].isin(filtrer)]

    wb = openpyxl.Workbook()

    # ── Feuille Résumé ──────────────────────────────────────────────────────
    ws_res = wb.active
    ws_res.title = "Résumé"
    hdrs = ["Réappro", "Salles KO", "Nb anomalies"]
    _apply_hdr(ws_res, hdrs)

    resume = (
        df.groupby("Réappro")
        .agg(Salles_KO=("Salle", "nunique"), Nb_anomalies=("Code", "count"))
        .reset_index()
        .sort_values("Nb_anomalies", ascending=False)
    )
    for r_idx, row in enumerate(resume.itertuples(index=False), start=2):
        ws_res.cell(r_idx, 1, row.Réappro)
        ws_res.cell(r_idx, 2, row.Salles_KO)
        ws_res.cell(r_idx, 3, row.Nb_anomalies)
        for col in range(1, 4):
            ws_res.cell(r_idx, col).border = border

    ws_res.column_dimensions["A"].width = 18
    ws_res.column_dimensions["B"].width = 14
    ws_res.column_dimensions["C"].width = 16

    # ── Une feuille par réappro ──────────────────────────────────────────────
    COLS_XLS = ["Salle", "Machine", "Code", "Produit", "Prix attendu (HT)", "Prix réel (HT)", "Écart (€)"]
    COL_W    = [35, 18, 22, 40, 20, 18, 14]

    for reappro in sorted(df["Réappro"].unique()):
        sub = df[df["Réappro"] == reappro].sort_values(["Salle", "Produit"])
        ws = wb.create_sheet(title=reappro[:31])  # Excel limite à 31 caractères
        _apply_hdr(ws, COLS_XLS)

        current_row = 2
        current_salle = None

        for _, r in sub.iterrows():
            salle = r.get("Salle", "")
            # Ligne de séparation entre salles
            if salle != current_salle:
                current_salle = salle
                for col in range(1, 8):
                    c = ws.cell(current_row, col)
                    c.fill = SALLE_FILL
                    c.font = SALLE_FONT
                    c.border = border
                ws.cell(current_row, 1, salle)
                ws.merge_cells(
                    start_row=current_row, start_column=1,
                    end_row=current_row, end_column=7
                )
                current_row += 1

            vals = [
                salle,
                r.get("Machine", ""),
                r.get("Code", ""),
                r.get("Produit", ""),
                r.get("Prix attendu (HT)", ""),
                r.get("Prix réel (HT)", ""),
                r.get("Écart (€)", ""),
            ]
            fill = _ecart_fill(r.get("Écart (€)", 0))
            for col, val in enumerate(vals, 1):
                c = ws.cell(current_row, col, val)
                c.fill = fill
                c.border = border
                if col in (5, 6):
                    c.number_format = "0.000 €"
                    c.alignment = Alignment(horizontal="center")
                elif col == 7:
                    c.number_format = '+0.000 €;-0.000 €;0.000 €'
                    c.alignment = Alignment(horizontal="center")
            current_row += 1

        for i, (col_letter, w) in enumerate(zip("ABCDEFG", COL_W), 1):
            ws.column_dimensions[col_letter].width = w

    # Retourner les bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# RENDU PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def render():
    st.title("Indéfinis & Contrôle des prix")

    tab1, tab2 = st.tabs(["🔍 Indéfinis", "💰 Contrôle des prix"])

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 1 — INDÉFINIS
    # ──────────────────────────────────────────────────────────────────────────
    with tab1:
        st.markdown("### Détection des produits indéfinis")
        st.caption(
            "Importez le fichier de ventes (export machine) et le planogramme (CSV). "
            "L'outil détecte les lignes INDÉFINI et identifie les produits suspects "
            "au même prix dans le planogramme."
        )

        col_a, col_b = st.columns(2)
        with col_a:
            f_ventes = st.file_uploader(
                "Fichier de ventes (CSV machine)", type=["csv"], key="indef_ventes"
            )
        with col_b:
            f_planno = st.file_uploader(
                "Planogramme (CSV)", type=["csv"], key="indef_planno"
            )

        if not f_ventes and not f_planno:
            st.info("Importez les deux fichiers pour lancer l'analyse.")
        else:
            df_ventes = None
            if f_ventes:
                try:
                    df_ventes = parse_ventes(f_ventes.read())
                except Exception as e:
                    st.error(f"Erreur lecture ventes : {e}")

            df_planno = None
            if f_planno:
                try:
                    df_planno = parse_planno(f_planno.read())
                except Exception as e:
                    st.error(f"Erreur lecture planogramme : {e}")

            if df_ventes is not None and df_planno is not None:
                missing_v = [c for c in ("CODE_PRODUIT", "PU") if c not in df_ventes.columns]
                missing_p = [c for c in ("CODE_PRODUIT", "PU") if c not in df_planno.columns]
                if missing_v:
                    st.error(f"Colonnes manquantes dans ventes : {missing_v}")
                elif missing_p:
                    st.error(f"Colonnes manquantes dans planogramme : {missing_p}")
                else:
                    resultats = analyser_indefinis(df_ventes, df_planno)

                    nb_indefinis = len(df_ventes[df_ventes["CODE_PRODUIT"] == "INDEFINI"])
                    nb_suspects = sum(len(r["suspects"]) for r in resultats)
                    nb_planno = len(df_planno)

                    k1, k2, k3 = st.columns(3)
                    k1.metric("Lignes INDÉFINI", nb_indefinis)
                    k2.metric("Lignes suspectes", nb_suspects)
                    k3.metric("Lignes planno analysées", nb_planno)

                    st.divider()

                    if not resultats:
                        st.success("Aucune ligne INDÉFINI trouvée dans le fichier de ventes.")
                    else:
                        for r in resultats:
                            prix = r["prix"]
                            suspects = r["suspects"]
                            autres = r["autres_vendus"]

                            st.markdown(
                                f"<div style='background:#1a1010;border-left:4px solid #e74c3c;"
                                f"padding:12px 16px;border-radius:6px;margin-bottom:8px;'>"
                                f"<b style='color:#e74c3c'>INDÉFINI</b> &nbsp;|&nbsp; "
                                f"Prix : <b>{prix:.2f} €</b> &nbsp;|&nbsp; "
                                f"{len(suspects)} suspect(s) &nbsp;|&nbsp; {len(autres)} référence(s)"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown("**🔴 Suspects** — produits au même prix sans vente")
                                if suspects.empty:
                                    st.caption("Aucun suspect.")
                                else:
                                    cols_s = [c for c in ("CODE_PRODUIT", "LIBELLE", "LDP", "PU", "NIV_HAUT") if c in suspects.columns]
                                    st.dataframe(suspects[cols_s], use_container_width=True, hide_index=True)

                            with c2:
                                st.markdown("**🟢 Références** — produits au même prix ayant vendu")
                                if autres.empty:
                                    st.caption("Aucune référence trouvée.")
                                else:
                                    cols_r = [c for c in ("CODE_PRODUIT", "LIBELLE", "LDP", "PU") if c in autres.columns]
                                    st.dataframe(autres[cols_r], use_container_width=True, hide_index=True)

                            st.markdown("---")

                    with st.expander("Toutes les ventes"):
                        st.dataframe(df_ventes, use_container_width=True, hide_index=True)

                    with st.expander("Tout le planogramme"):
                        st.dataframe(df_planno, use_container_width=True, hide_index=True)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 2 — CONTRÔLE DES PRIX
    # ──────────────────────────────────────────────────────────────────────────
    with tab2:
        st.markdown("### Vérification des prix de vente HT")
        st.caption(
            "Importez l'export ERP (Audit Télémétrie, CSV séparé par ';'). "
            "Les prix réels (Montant HT ÷ Quantité) sont comparés aux prix HT "
            f"de la bibliothèque produits. Tolérance : ±{_TOLERANCE_HT} €."
        )

        f_erp = st.file_uploader(
            "Export ERP Audit Télémétrie (.csv)", type=["csv"], key="prix_erp"
        )

        # Réinitialiser les résultats si le fichier change
        if not f_erp:
            st.session_state.pop("prix_resultats", None)
            st.info("Importez le fichier ERP pour lancer l'analyse.")
        else:
            if st.button("🔍 Analyser", key="btn_analyser_prix"):
                try:
                    df_ventes_prix = parse_ventes_prix(f_erp.read())
                except Exception as e:
                    st.error(f"Erreur lecture fichier ERP : {e}")
                    df_ventes_prix = None

                if df_ventes_prix is not None and df_ventes_prix.empty:
                    st.warning("Aucune ligne exploitable dans le fichier.")
                    df_ventes_prix = None

                if df_ventes_prix is not None:
                    with st.spinner("Chargement de la bibliothèque produits…"):
                        produits = load_produits()

                    if not produits:
                        st.warning(
                            "La bibliothèque produits est vide. "
                            "Ajoutez des produits dans Planogrammes → Bibliothèque."
                        )
                    else:
                        anomalies_df, non_ref = analyser_prix(df_ventes_prix, produits)
                        with st.spinner("Chargement du planning…"):
                            plannings, errs = load_plannings_from_mongo()
                        reappro_map = build_reappro_mapping(plannings) if not errs else {}
                        # Stocker dans session_state pour survivre aux reruns
                        st.session_state["prix_resultats"] = {
                            "anomalies_df": anomalies_df,
                            "non_ref": non_ref,
                            "nb_lignes": len(df_ventes_prix),
                            "reappro_map": reappro_map,
                            "planning_errs": errs,
                        }

            # Afficher les résultats depuis session_state (persiste entre reruns)
            if "prix_resultats" in st.session_state:
                res          = st.session_state["prix_resultats"]
                anomalies_df = res["anomalies_df"]
                non_ref      = res["non_ref"]
                nb_lignes    = res["nb_lignes"]
                reappro_map  = res["reappro_map"]
                errs         = res["planning_errs"]

                nb_anomalies  = len(anomalies_df)
                nb_non_ref    = len(non_ref)
                nb_salles_ko  = anomalies_df["Salle"].nunique() if not anomalies_df.empty else 0
                pct_ok        = round((nb_lignes - nb_anomalies) / nb_lignes * 100, 1) if nb_lignes else 0.0

                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Lignes analysées", nb_lignes)
                k2.metric("Conformes", f"{pct_ok} %")
                k3.metric("Anomalies de prix", nb_anomalies)
                k4.metric("Salles concernées", nb_salles_ko)
                k5.metric("Codes non référencés", nb_non_ref)

                st.divider()

                if anomalies_df.empty:
                    st.success("Tous les produits référencés sont vendus au bon prix HT.")
                else:
                    st.markdown(
                        f"**{nb_anomalies} ligne(s) avec un écart supérieur à ±{_TOLERANCE_HT} €**"
                    )

                    def _color_row(row):
                        ecart = abs(row["Écart (€)"])
                        if ecart >= 0.50:
                            bg = "background-color: #f5c6cb; color: #7b1a1a;"
                        elif ecart >= 0.20:
                            bg = "background-color: #ffd8a8; color: #6b3a00;"
                        else:
                            bg = "background-color: #fff3cd; color: #664d00;"
                        return [bg] * len(row)

                    # ── Export par réappro ──────────────────────────────────
                    if errs:
                        st.warning(
                            "Planning indisponible, l'export par réappro est désactivé. "
                            f"Erreur : {list(errs.values())[0]}"
                        )
                    else:
                        df_tmp = anomalies_df.copy()
                        df_tmp["Réappro"] = df_tmp["Code_client"].apply(
                            lambda x: reappro_map.get(str(x).strip().upper(), "Non assigné")
                        )
                        tous_reappros = sorted(df_tmp["Réappro"].unique().tolist())

                        st.markdown("**Sélectionner les réappros à exporter :**")
                        col_sel, col_btn = st.columns([4, 1])
                        with col_sel:
                            selection = st.multiselect(
                                label="Réappros",
                                options=tous_reappros,
                                default=[],
                                placeholder="Ajouter un réappro…",
                                label_visibility="collapsed",
                                key="export_reappro_select",
                            )
                        with col_btn:
                            if st.button("Tout sélectionner", key="btn_tout_select"):
                                selection = tous_reappros

                        col_dl1, col_dl2 = st.columns(2)
                        with col_dl1:
                            if selection:
                                excel_sel = generer_export_reappros(anomalies_df, reappro_map, filtrer=selection)
                                fname = (
                                    f"controle_prix_{'_'.join(selection)}.xlsx"
                                    if len(selection) <= 3
                                    else "controle_prix_selection.xlsx"
                                )
                                st.download_button(
                                    label=f"📥 Exporter la sélection ({len(selection)} réappro(s))",
                                    data=excel_sel,
                                    file_name=fname,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="dl_selection",
                                )
                            else:
                                st.button("📥 Exporter la sélection", disabled=True, key="dl_selection_off")
                        with col_dl2:
                            excel_all = generer_export_reappros(anomalies_df, reappro_map)
                            st.download_button(
                                label="📥 Exporter tous les réappros",
                                data=excel_all,
                                file_name="controle_prix_reappros.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="dl_all",
                            )

                    st.divider()

                    vue_machine, vue_complet = st.tabs(["🏭 Détail par machine", "📋 Détail complet"])

                    with vue_machine:
                        machines = anomalies_df["Machine"].unique() if "Machine" in anomalies_df.columns else []
                        for machine in sorted(machines):
                            sous_df = anomalies_df[anomalies_df["Machine"] == machine]
                            salle = sous_df["Salle"].iloc[0] if "Salle" in sous_df.columns and not sous_df.empty else ""
                            label = f"{machine} — {salle}" if salle else machine
                            with st.expander(f"**{label}** — {len(sous_df)} anomalie(s)", expanded=False):
                                styled_m = sous_df.style.apply(_color_row, axis=1).format(
                                    {
                                        "Prix attendu (HT)": "{:.3f} €",
                                        "Prix réel (HT)": "{:.3f} €",
                                        "Écart (€)": "{:+.3f} €",
                                    }
                                )
                                st.dataframe(styled_m, use_container_width=True, hide_index=True)

                    with vue_complet:
                        styled_c = anomalies_df.style.apply(_color_row, axis=1).format(
                            {
                                "Prix attendu (HT)": "{:.3f} €",
                                "Prix réel (HT)": "{:.3f} €",
                                "Écart (€)": "{:+.3f} €",
                            }
                        )
                        st.dataframe(styled_c, use_container_width=True, hide_index=True)

                if non_ref:
                    with st.expander(
                        f"Codes produits non référencés dans la bibliothèque ({nb_non_ref})"
                    ):
                        for code in sorted(non_ref):
                            st.markdown(f"- `{code}`")
