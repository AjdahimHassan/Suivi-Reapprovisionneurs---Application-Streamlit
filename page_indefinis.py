"""
Page : Détection des Indéfinis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Charge un fichier de ventes (export audit machine)
- Charge un fichier de planogramme (configuration machine)
- Détecte les lignes "INDEFINI"
- Identifie les lignes du planno au même prix qui n'ont PAS vendu
  → Ce sont les suspects d'un mauvais paramétrage
"""

import streamlit as st
import pandas as pd
import io


# ──────────────────────────────────────────────────────────
# PARSING
# ──────────────────────────────────────────────────────────

def parse_ventes(file_bytes: bytes) -> pd.DataFrame:
    """Parse le fichier export audit (ventes réelles)."""
    content = file_bytes.decode("utf-8-sig")
    df = pd.read_csv(
        io.StringIO(content),
        sep=";",
        dtype=str,
    )
    df.columns = [c.strip().strip('"') for c in df.columns]
    for col in df.columns:
        df[col] = df[col].str.strip().str.strip('"')

    # Normaliser les noms de colonnes attendus
    rename_map = {}
    for c in df.columns:
        cl = c.upper()
        if "CODE PRODUIT" in cl or "PRODUIT" in cl:
            rename_map[c] = "CODE_PRODUIT"
        elif "PU" == cl or "PRIX" in cl:
            rename_map[c] = "PU"
        elif "LDP" in cl or "LIGNE" in cl:
            rename_map[c] = "LDP"
        elif "CODE MACHINE" in cl or "MACHINE" in cl:
            rename_map[c] = "CODE_MACHINE"
        elif "CODE CLIENT" in cl or "CLIENT" in cl:
            rename_map[c] = "CODE_CLIENT"
    df = df.rename(columns=rename_map)

    # Convertir PU en float
    if "PU" in df.columns:
        df["PU"] = df["PU"].str.replace(",", ".").str.strip()
        df["PU"] = pd.to_numeric(df["PU"], errors="coerce")
    if "LDP" in df.columns:
        df["LDP"] = pd.to_numeric(df["LDP"], errors="coerce")

    return df


def parse_planno(file_bytes: bytes) -> pd.DataFrame:
    """Parse le fichier planogramme (configuration machine)."""
    content = file_bytes.decode("utf-8-sig")
    lines = content.splitlines()

    # Trouver la ligne d'en-tête (celle qui contient "Code")
    header_idx = 1  # fallback
    for i, line in enumerate(lines):
        stripped = line.strip().strip('"')
        if stripped.startswith("Code"):
            header_idx = i
            break

    data_lines = "\n".join(lines[header_idx:])
    df = pd.read_csv(
        io.StringIO(data_lines),
        sep=";",
        dtype=str,
    )

    # Nettoyer les noms de colonnes
    df.columns = [str(c).strip().strip('"') for c in df.columns]

    # Supprimer colonnes Unnamed ou vides
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.loc[:, df.columns.str.strip() != ""]

    # Nettoyer les valeurs (toutes les colonnes sont str ici)
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip().str.strip('"')

    # Renommer les colonnes utiles — ordre important : LIGNE avant PRIX
    rename_map = {}
    for c in df.columns:
        cl = c.upper().replace("É", "E").replace("È", "E").replace("Û", "U")
        if cl == "CODE":
            rename_map[c] = "CODE_PRODUIT"
        elif cl.startswith("LIBEL"):
            rename_map[c] = "LIBELLE"
        elif "LIGNE" in cl:          # "Ligne de prix" → LDP  (testé AVANT PRIX)
            rename_map[c] = "LDP"
        elif "PRIX" in cl:           # "Prix u.b. TTC" → PU
            rename_map[c] = "PU"
        elif cl.startswith("NIV"):
            rename_map[c] = "NIV_HAUT"
        elif "UNIT" in cl:
            rename_map[c] = "UNITE"

    df = df.rename(columns=rename_map)

    if "PU" in df.columns:
        df["PU"] = df["PU"].str.replace(",", ".").str.strip()
        df["PU"] = pd.to_numeric(df["PU"], errors="coerce")
    if "LDP" in df.columns:
        df["LDP"] = df["LDP"].str.replace(",", ".").str.strip()
        df["LDP"] = pd.to_numeric(df["LDP"], errors="coerce")

    if "CODE_PRODUIT" not in df.columns:
        raise ValueError(
            f"Colonne 'Code' introuvable dans le planno. Colonnes détectées : {list(df.columns)}"
        )

    df = df.dropna(subset=["CODE_PRODUIT"])
    df = df[df["CODE_PRODUIT"].str.strip().str.upper() != "NAN"]
    df = df[df["CODE_PRODUIT"].str.strip() != ""]

    return df


# ──────────────────────────────────────────────────────────
# ANALYSE
# ──────────────────────────────────────────────────────────

def analyser_indefinis(df_ventes: pd.DataFrame, df_planno: pd.DataFrame) -> list[dict]:
    """
    Pour chaque ligne INDEFINI dans les ventes :
      1. Récupère son prix
      2. Cherche dans le planno les lignes au même prix
      3. Parmi celles-ci, identifie celles qui N'ont PAS vendu
      → Ces lignes sont les suspects (mal paramétrées)
    Retourne une liste de cas analysés.
    """
    indefinis = df_ventes[df_ventes["CODE_PRODUIT"].str.upper() == "INDEFINI"].copy()

    if indefinis.empty:
        return []

    # Lignes qui ont vendu (hors INDEFINI)
    vendus_ldp = set(
        df_ventes[df_ventes["CODE_PRODUIT"].str.upper() != "INDEFINI"]["LDP"].dropna().astype(int)
    )

    cas = []
    for _, row in indefinis.iterrows():
        prix_indef = row.get("PU")
        ldp_indef = row.get("LDP")

        if pd.isna(prix_indef):
            continue

        # Lignes planno au même prix
        planno_meme_prix = df_planno[
            df_planno["PU"].round(4) == round(prix_indef, 4)
        ].copy()

        # Lignes planno au même prix qui N'ONT PAS vendu
        suspects = planno_meme_prix[
            ~planno_meme_prix["LDP"].isin(vendus_ldp)
        ].copy()

        # Lignes planno au même prix qui ONT vendu
        autres_vendus = planno_meme_prix[
            planno_meme_prix["LDP"].isin(vendus_ldp)
        ].copy()

        cas.append({
            "ldp_indefini": int(ldp_indef) if not pd.isna(ldp_indef) else "?",
            "prix": prix_indef,
            "planno_meme_prix": planno_meme_prix,
            "suspects": suspects,
            "autres_vendus": autres_vendus,
        })

    return cas


# ──────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────

def render():

    st.markdown("""
    <style>
    .indef-card {
        background: #1a1a2e;
        border-left: 5px solid #E74C3C;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin-bottom: 1.5rem;
    }
    .suspect-badge {
        display: inline-block;
        background: #C0392B;
        color: white;
        font-weight: 700;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.85rem;
        margin-right: 6px;
    }
    .ok-badge {
        display: inline-block;
        background: #1E7E34;
        color: white;
        font-weight: 700;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Upload ──
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📤 Fichier de ventes (audit machine)")
        st.caption("Export contenant les lignes vendues avec CODE PRODUIT, PU, LDP")
        f_ventes = st.file_uploader(
            "Ventes", type=["csv"], key="indef_ventes",
            label_visibility="collapsed"
        )
    with col2:
        st.markdown("#### 📋 Fichier planogramme (configuration machine)")
        st.caption("Export de configuration contenant Code, Libellé, Prix, Ligne de prix")
        f_planno = st.file_uploader(
            "Planno", type=["csv"], key="indef_planno",
            label_visibility="collapsed"
        )

    if not f_ventes or not f_planno:
        st.info("👆 Déposez les deux fichiers pour lancer l'analyse.")
        return

    # ── Parse ──
    try:
        df_ventes = parse_ventes(f_ventes.read())
        df_planno = parse_planno(f_planno.read())
    except Exception as e:
        st.error(f"Erreur lors du parsing : {e}")
        return

    # ── Vérifications colonnes ──
    missing_v = [c for c in ["CODE_PRODUIT", "PU", "LDP"] if c not in df_ventes.columns]
    missing_p = [c for c in ["CODE_PRODUIT", "PU", "LDP"] if c not in df_planno.columns]
    if missing_v:
        st.error(f"Colonnes manquantes dans le fichier ventes : {missing_v}")
        st.write("Colonnes détectées :", list(df_ventes.columns))
        return
    if missing_p:
        st.error(f"Colonnes manquantes dans le fichier planno : {missing_p}")
        st.write("Colonnes détectées :", list(df_planno.columns))
        return

    # ── Analyse ──
    cas = analyser_indefinis(df_ventes, df_planno)

    st.divider()

    if not cas:
        st.success("✅ Aucun produit INDÉFINI détecté dans ce fichier de ventes.")
        return

    # KPIs
    nb_indefinis = len(cas)
    nb_suspects_total = sum(len(c["suspects"]) for c in cas)

    k1, k2, k3 = st.columns(3)
    k1.metric("⚠️ Lignes INDÉFINI", nb_indefinis)
    k2.metric("🔍 Lignes suspectes (planno)", nb_suspects_total,
              help="Lignes au même prix dans le planno qui n'ont pas vendu")
    k3.metric("📋 Lignes planno analysées",
              sum(len(c["planno_meme_prix"]) for c in cas))

    st.divider()

    # ── Détail par indéfini ──
    for i, cas_item in enumerate(cas, 1):
        ldp = cas_item["ldp_indefini"]
        prix = cas_item["prix"]
        suspects = cas_item["suspects"]
        autres_vendus = cas_item["autres_vendus"]
        planno_meme_prix = cas_item["planno_meme_prix"]

        # En-tête cas
        st.markdown(f"""
        <div class="indef-card">
            <b style="color:#E74C3C; font-size:1.1rem;">
                ⚠️ INDÉFINI #{i} — Ligne {ldp} — Prix : {prix:.2f} €
            </b>
        </div>
        """, unsafe_allow_html=True)

        col_s, col_v = st.columns(2)

        with col_s:
            st.markdown(f"##### 🔴 Lignes suspectes ({len(suspects)} trouvée(s))")
            st.caption("Ces lignes sont dans le planno au même prix mais **n'ont pas vendu** — probable mauvais paramétrage")
            if suspects.empty:
                st.success("Aucune ligne suspecte — toutes les lignes planno à ce prix ont vendu.")
            else:
                cols_show = ["LDP", "CODE_PRODUIT"]
                if "LIBELLE" in suspects.columns:
                    cols_show.append("LIBELLE")
                if "NIV_HAUT" in suspects.columns:
                    cols_show.append("NIV_HAUT")
                cols_show.append("PU")
                df_show = suspects[[c for c in cols_show if c in suspects.columns]].copy()
                df_show = df_show.sort_values("LDP")
                df_show.columns = [
                    c.replace("LDP", "Ligne").replace("CODE_PRODUIT", "Code Produit")
                     .replace("LIBELLE", "Libellé").replace("NIV_HAUT", "Capacité")
                     .replace("PU", "Prix (€)")
                    for c in df_show.columns
                ]
                st.dataframe(
                    df_show.style.applymap(
                        lambda _: "background-color:#C0392B; color:#FFFFFF; font-weight:600"
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with col_v:
            st.markdown(f"##### 🟢 Lignes planno qui ont vendu ({len(autres_vendus)})")
            st.caption("Ces lignes au même prix ont correctement vendu — servent de référence")
            if autres_vendus.empty:
                st.warning("Aucune ligne à ce prix n'a vendu (hormis l'indéfini).")
            else:
                cols_show2 = ["LDP", "CODE_PRODUIT"]
                if "LIBELLE" in autres_vendus.columns:
                    cols_show2.append("LIBELLE")
                cols_show2.append("PU")
                df_show2 = autres_vendus[[c for c in cols_show2 if c in autres_vendus.columns]].copy()
                df_show2 = df_show2.sort_values("LDP")
                df_show2.columns = [
                    c.replace("LDP", "Ligne").replace("CODE_PRODUIT", "Code Produit")
                     .replace("LIBELLE", "Libellé").replace("PU", "Prix (€)")
                    for c in df_show2.columns
                ]
                st.dataframe(
                    df_show2.style.applymap(
                        lambda _: "background-color:#1E7E34; color:#FFFFFF; font-weight:600"
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        # Résumé diagnostic
        if not suspects.empty:
            lignes_str = ", ".join(str(int(l)) for l in suspects["LDP"].dropna())
            produits_str = ", ".join(suspects["CODE_PRODUIT"].dropna().unique())
            st.info(
                f"💡 **Diagnostic** : La ligne **{ldp}** vend en INDÉFINI à **{prix:.2f} €**. "
                f"Les lignes **{lignes_str}** ({produits_str}) sont configurées au même prix "
                f"dans le planno mais n'ont pas vendu. "
                f"Vérifiez le paramétrage de ces lignes sur la machine."
            )
        else:
            st.success(
                f"✅ Toutes les lignes planno à **{prix:.2f} €** ont vendu. "
                f"La ligne {ldp} est peut-être un produit absent du planno."
            )

        st.divider()

    # ── Vue d'ensemble ventes ──
    with st.expander("🔍 Voir toutes les lignes du fichier ventes"):
        cols_v = ["LDP", "CODE_PRODUIT", "PU"]
        if "CODE_MACHINE" in df_ventes.columns:
            cols_v = ["CODE_MACHINE"] + cols_v
        if "CODE_CLIENT" in df_ventes.columns:
            cols_v = ["CODE_CLIENT"] + cols_v
        df_v_show = df_ventes[[c for c in cols_v if c in df_ventes.columns]].copy()
        df_v_show = df_v_show.sort_values("LDP")

        def color_ventes(row):
            if str(row.get("CODE_PRODUIT", "")).upper() == "INDEFINI":
                return ["background-color:#C0392B; color:#FFFFFF; font-weight:600"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_v_show.style.apply(color_ventes, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("📋 Voir toutes les lignes du planogramme"):
        cols_p = ["LDP", "CODE_PRODUIT"]
        if "LIBELLE" in df_planno.columns:
            cols_p.append("LIBELLE")
        if "NIV_HAUT" in df_planno.columns:
            cols_p.append("NIV_HAUT")
        cols_p.append("PU")
        df_p_show = df_planno[[c for c in cols_p if c in df_planno.columns]].copy()
        df_p_show = df_p_show.sort_values("LDP")
        st.dataframe(df_p_show, use_container_width=True, hide_index=True)
