import streamlit as st
import pandas as pd
import io
from planogrammes_storage import load_produits

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
        "Code DA": "Machine",
        "Nom client": "Salle",
        "Code produit": "Code",
        "Libellé produit": "Produit",
        "Quantité": "Quantité",
        "Montant HT": "Montant_HT",
        "Date": "Date",
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

    cols = [c for c in ("Date", "Machine", "Salle", "Code", "Produit", "Quantité", "Montant_HT", "PU_HT") if c in df.columns]
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

        if not f_erp:
            st.info("Importez le fichier ERP pour lancer l'analyse.")
        elif st.button("🔍 Analyser", key="btn_analyser_prix"):
            try:
                df_ventes_prix = parse_ventes_prix(f_erp.read())
            except Exception as e:
                st.error(f"Erreur lecture fichier ERP : {e}")
                return

            if df_ventes_prix.empty:
                st.warning("Aucune ligne exploitable dans le fichier.")
                return

            with st.spinner("Chargement de la bibliothèque produits…"):
                produits = load_produits()

            if not produits:
                st.warning(
                    "La bibliothèque produits est vide. "
                    "Ajoutez des produits dans Planogrammes → Bibliothèque."
                )
                return

            anomalies_df, non_ref = analyser_prix(df_ventes_prix, produits)

            nb_lignes = len(df_ventes_prix)
            nb_anomalies = len(anomalies_df)
            nb_non_ref = len(non_ref)
            pct_ok = round((nb_lignes - nb_anomalies) / nb_lignes * 100, 1) if nb_lignes else 0.0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Lignes analysées", nb_lignes)
            k2.metric("Conformes", f"{pct_ok} %")
            k3.metric("Anomalies de prix", nb_anomalies)
            k4.metric("Codes non référencés", nb_non_ref)

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
