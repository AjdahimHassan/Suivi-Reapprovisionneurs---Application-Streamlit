"""
Page Commandes — Suivi des commandes fournisseurs
Lecture d'un screenshot de mail → extraction Claude API → ajout dans le fichier Excel de suivi
"""

import streamlit as st
import anthropic
import base64
import io
import json
import datetime
import re
import os
from openpyxl import load_workbook

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION PRODUITS
# ──────────────────────────────────────────────────────────────────────────────

# Pour LIDIS : multiplier extrait du nom du produit (xNN)
LIDIS_PRODUCTS = [
    "50CL Evian x24",
    "50CL Volvic Juicy Fraise x12",
    "50CL Volvic Juicy Exotique x24",
    "25CL Redbull x24",
    "25CL Redbull Zéro x24",
]

HIPRO_PRODUCTS = [
    "HIPRO A BOIRE 330 ML VANILLE",
    "HIPRO A BOIRE 330 ML SAVEUR CHOCOLAT",
]

HEROIC_PRODUCTS = [
    "Heroic sport Fruits rouges 500ML x6",
    "Heroic sport Citron vert Menthe 500ML x6",
    "HEROIC SPORT SAVEUR TROPICAL 500ML x6",
]

NXT_PRODUCTS = [
    "RTD Protein Shake Strawberry 330ml",
    "RTD Protein Shake Vanilla 330ml",
    "RTD Protein Shake Chocolate 330ml",
    "RTD Protein Shake Milky Chocolate 500ml",
    "RTD Protein Shake Vanilla 500ml",
    "Crispy Protein Raspberry Toffee",
    "Pocket Protein Salty Caramel",
    "Pocket Protein Caramel Cookie",
    "Peanut Boost",
    "Pre-workout Shots Lemon-Lime 60ml",
    "Basic-Fit - Bidon - Orange",
    "Basic-Fit - Lock (Key)",
    "Basic-Fit - Vending Towel black",
]

FOURNISSEURS = ["LIDIS", "HIPRO", "HEROIC", "NXT LEVEL"]

PRODUITS_PAR_FOURNISSEUR = {
    "LIDIS": LIDIS_PRODUCTS,
    "HIPRO": HIPRO_PRODUCTS,
    "HEROIC": HEROIC_PRODUCTS,
    "NXT LEVEL": NXT_PRODUCTS,
}

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def get_uvc_multiplier(product_name: str) -> int | None:
    """Extrait le multiplicateur UVC depuis le nom du produit (ex: x24 → 24)."""
    m = re.search(r"x(\d+)$", product_name.strip(), re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def get_uvc_formula_or_value(product_name: str, qty_col: str, row_num: int) -> str:
    """Retourne la formule UVC pour LIDIS/HEROIC/HIPRO, ou None pour NXT LEVEL."""
    mult = get_uvc_multiplier(product_name)
    if mult:
        return f"={qty_col}{row_num}*{mult}"
    return None


def find_last_data_row(ws, header_row: int) -> int:
    """Trouve la dernière ligne de données non-vide dans la feuille."""
    last = header_row
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
        if any(c.value is not None for c in row):
            last = row[0].row
    return last


def extract_image_base64(uploaded_file) -> tuple[str, str]:
    """Convertit l'image uploadée en base64."""
    content = uploaded_file.read()
    b64 = base64.standard_b64encode(content).decode("utf-8")
    mime = uploaded_file.type or "image/png"
    return b64, mime


def analyze_screenshot_with_claude(image_b64: str, mime: str, fournisseur: str) -> dict:
    """
    Envoie le screenshot à Claude pour extraire les informations de commande.
    Retourne un dict avec date, depot, produits [{nom, quantite}].
    """
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    produits_list = "\n".join(f"- {p}" for p in PRODUITS_PAR_FOURNISSEUR[fournisseur])

    system_prompt = f"""Tu es un assistant qui extrait des informations de commande depuis des screenshots de mails.
Tu dois retourner UNIQUEMENT un JSON valide, sans backticks, sans texte avant ou après.

Le fournisseur est : {fournisseur}

Liste des produits connus pour ce fournisseur :
{produits_list}

Tu dois retourner ce format JSON :
{{
  "date_commande": "DD/MM/YYYY",
  "depot": "Nom du dépôt ou box mentionné dans le mail",
  "produits": [
    {{"nom": "Nom exact du produit dans la liste", "quantite": nombre_entier}},
    ...
  ],
  "notes": "Toute information utile non capturée ci-dessus"
}}

Règles :
- Pour chaque produit mentionné, trouve le meilleur match dans la liste des produits connus.
- Si la quantité est en packs/palettes, convertis en nombre de packs (ex: "1 palette" = 1 unité sauf indication contraire).
- Si la date n'est pas mentionnée, utilise la date d'aujourd'hui : {datetime.date.today().strftime('%d/%m/%Y')}.
- Si le dépôt n'est pas clairement mentionné, mets "Non précisé".
- Retourne UNIQUEMENT le JSON, rien d'autre."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Voici un screenshot d'un mail de commande pour le fournisseur {fournisseur}. Extrais les informations de commande.",
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    # Nettoyage au cas où
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def add_commande_to_excel(
    wb,
    fournisseur: str,
    date_commande: str,
    depot: str,
    produits: list[dict],
) -> None:
    """
    Ajoute une commande dans la feuille Excel du fournisseur.
    """
    sheet_name = fournisseur
    if sheet_name not in wb.sheetnames:
        st.error(f"❌ Feuille '{sheet_name}' introuvable dans le fichier Excel.")
        return

    ws = wb[sheet_name]
    header_row = 2  # identique pour toutes les feuilles

    # Trouver la dernière ligne de données
    last_row = find_last_data_row(ws, header_row)
    next_row = last_row + 1

    # Parser la date
    try:
        dt = datetime.datetime.strptime(date_commande, "%d/%m/%Y")
    except Exception:
        dt = datetime.datetime.today()

    # NXT LEVEL a une structure légèrement différente (col F = Facturé au lieu de QUANTITE)
    is_nxt = fournisseur == "NXT LEVEL"

    for i, produit in enumerate(produits):
        row_num = next_row + i
        nom = produit.get("nom", "")
        quantite = produit.get("quantite", 0)

        # Col A : DATE COMMANDE (seulement sur la 1ère ligne du groupe)
        if i == 0:
            ws.cell(row=row_num, column=1).value = dt

        # Col D : DEPOT/BOX (seulement sur la 1ère ligne)
        if i == 0:
            ws.cell(row=row_num, column=4).value = depot

        if is_nxt:
            # Col E : UVC (valeur directe, pas de formule)
            ws.cell(row=row_num, column=5).value = quantite
            # Col G : PRODUITS NXT
            ws.cell(row=row_num, column=7).value = nom
        else:
            # Col F : QUANTITE (nombre de packs)
            ws.cell(row=row_num, column=6).value = quantite
            # Col E : UVC = formule =F{row}*{mult}
            uvc_formula = get_uvc_formula_or_value(nom, "F", row_num)
            if uvc_formula:
                ws.cell(row=row_num, column=5).value = uvc_formula
            # Col G : PRODUITS
            ws.cell(row=row_num, column=7).value = nom


# ──────────────────────────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────────────────────────

def render():
    st.markdown("### 📸 Ajouter une commande depuis un screenshot")

    # Étape 1 : choisir le fournisseur
    col_four, col_void = st.columns([2, 4])
    with col_four:
        fournisseur = st.selectbox(
            "Fournisseur",
            FOURNISSEURS,
            key="commande_fournisseur",
            help="Sélectionne le fournisseur de cette commande",
        )

    st.divider()

    # Étape 2 : uploader le screenshot
    st.markdown("**📎 Screenshot du mail de commande**")
    screenshot = st.file_uploader(
        "Image du mail",
        type=["png", "jpg", "jpeg", "webp"],
        key="commande_screenshot",
        label_visibility="collapsed",
    )

    if screenshot:
        col_img, col_void2 = st.columns([2, 3])
        with col_img:
            st.image(screenshot, caption="Aperçu du screenshot", use_container_width=True)

    st.divider()

    # Étape 3 : analyser le screenshot
    if screenshot and st.button("🔍 Analyser le screenshot", type="primary", key="btn_analyze"):
        with st.spinner(f"Analyse du mail {fournisseur} en cours..."):
            try:
                screenshot.seek(0)
                b64, mime = extract_image_base64(screenshot)
                result = analyze_screenshot_with_claude(b64, mime, fournisseur)
                st.session_state["commande_result"] = result
                st.session_state["commande_fournisseur_used"] = fournisseur
                st.success("✅ Analyse terminée — vérifiez et corrigez si besoin")
            except Exception as e:
                st.error(f"Erreur lors de l'analyse : {e}")
                return

    # Étape 4 : afficher et éditer les résultats
    if "commande_result" not in st.session_state:
        return

    result = st.session_state["commande_result"]
    fournisseur_used = st.session_state.get("commande_fournisseur_used", fournisseur)

    st.markdown("### ✏️ Vérification et correction de la commande")

    col_date, col_depot = st.columns(2)
    with col_date:
        date_val = st.text_input(
            "📅 Date de commande",
            value=result.get("date_commande", datetime.date.today().strftime("%d/%m/%Y")),
            key="commande_date",
        )
    with col_depot:
        depot_val = st.text_input(
            "📍 Dépôt / Box",
            value=result.get("depot", ""),
            key="commande_depot",
        )

    st.markdown("**Produits détectés :**")

    produits_raw = result.get("produits", [])
    produits_list_ref = PRODUITS_PAR_FOURNISSEUR[fournisseur_used]

    edited_produits = []
    for i, p in enumerate(produits_raw):
        col_nom, col_qty, col_del = st.columns([4, 2, 1])
        with col_nom:
            # Sélecteur de produit
            idx = 0
            if p.get("nom") in produits_list_ref:
                idx = produits_list_ref.index(p["nom"])
            nom_sel = st.selectbox(
                f"Produit {i+1}",
                produits_list_ref,
                index=idx,
                key=f"commande_produit_{i}",
                label_visibility="collapsed",
            )
        with col_qty:
            qty_sel = st.number_input(
                f"Qté {i+1}",
                min_value=0,
                value=int(p.get("quantite", 0)),
                step=1,
                key=f"commande_qty_{i}",
                label_visibility="collapsed",
            )
        edited_produits.append({"nom": nom_sel, "quantite": qty_sel})

    # Bouton pour ajouter une ligne
    if st.button("➕ Ajouter un produit", key="btn_add_produit"):
        produits_raw.append({"nom": produits_list_ref[0], "quantite": 0})
        result["produits"] = produits_raw
        st.session_state["commande_result"] = result
        st.rerun()

    if result.get("notes"):
        st.caption(f"ℹ️ Note : {result['notes']}")

    st.divider()

    # Étape 5 : fichier Excel + injection
    st.markdown("### 📥 Fichier Excel de suivi")
    excel_file = st.file_uploader(
        "Dépose ici le fichier Excel de suivi des commandes",
        type=["xlsx"],
        key="commande_excel",
        label_visibility="collapsed",
    )

    if excel_file and st.button("💾 Injecter dans le fichier Excel", type="primary", key="btn_inject"):
        with st.spinner("Injection en cours..."):
            try:
                excel_bytes = excel_file.read()
                wb = load_workbook(io.BytesIO(excel_bytes))

                add_commande_to_excel(
                    wb=wb,
                    fournisseur=fournisseur_used,
                    date_commande=date_val,
                    depot=depot_val,
                    produits=edited_produits,
                )

                # Sauvegarder dans un buffer
                output = io.BytesIO()
                wb.save(output)
                output.seek(0)

                date_str = datetime.date.today().strftime("%Y%m%d")
                filename = f"Suivi_commandes_{date_str}.xlsx"

                st.success(f"✅ Commande ajoutée dans la feuille **{fournisseur_used}** — {len(edited_produits)} produit(s)")
                st.download_button(
                    label="⬇️ Télécharger le fichier mis à jour",
                    data=output.getvalue(),
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

                # Reset
                del st.session_state["commande_result"]
                if "commande_fournisseur_used" in st.session_state:
                    del st.session_state["commande_fournisseur_used"]

            except Exception as e:
                st.error(f"Erreur : {e}")
