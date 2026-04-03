"""
Page Contrôle Réception — Comparaison facture vs marchandises reçues
NXT LEVEL: comparaison par prix (total HT + détail par ligne)
Autres fournisseurs: comparaison par quantités avec table de correspondance
"""

import streamlit as st
import pandas as pd
import pdfplumber
import io
import re
import datetime
import json
import os
import unicodedata

from pymongo import MongoClient
from rapidfuzz import fuzz


# ──────────────────────────────────────────────────────────────────────────────
# DÉTECTION FOURNISSEUR
# ──────────────────────────────────────────────────────────────────────────────

def detecter_fournisseur(texte):
    t = texte.lower()
    if 'heroic' in t and ('crystal' in t or '€/unit' in t):
        return 'HEROIC'
    if 'basic-fit' in t or 'basic fit' in t or 'nxt level' in t:
        return 'NXT LEVEL'
    if 'lidis' in t:
        return 'LIDIS'
    if 'hipro' in t or 'lactalis' in t:
        return 'HIPRO'
    if 'nutramino' in t or 'glanbia' in t:
        return 'NUTRAMINO'
    return 'INCONNU'


def extraire_numero_facture(texte):
    for pattern in [
        r'Facture\s+No\.?\s*[:\.]?\s*(\d+)',
        r'Facture:\s*(\d+)',
        r'Facture\s+N°\s*(\d+)',
    ]:
        m = re.search(pattern, texte, re.IGNORECASE)
        if m:
            return m.group(1)
    return ''


def extraire_date(texte):
    for pattern in [
        r'Date de facture\s*[:\s]+(\d{1,2}/\d{1,2}/\d{4})',
        r'Date\s*[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})',
        r'Date\s*[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})',
    ]:
        m = re.search(pattern, texte, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ''


def extraire_depot(texte):
    m = re.search(r'HOME\s+BOX\s+([\w\s]+?)(?:\s*-|\s*\d{5}|\n)', texte, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'Home\s+Box\s+([\w\s]+?)(?:\n|\d{5})', texte, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    m3 = re.search(r'LE PIECE QUI VOUS MANQUE\s*[-–]?\s*([\w\s]+?)(?:\n|\d{5})', texte, re.IGNORECASE)
    if m3:
        return m3.group(1).strip()
    return ''


# ──────────────────────────────────────────────────────────────────────────────
# PARSERS PAR FOURNISSEUR
# ──────────────────────────────────────────────────────────────────────────────

def parser_lidis(texte):
    lignes = []
    pattern = re.compile(
        r'(\d{7})\s+(.+?)\s+(\d+)\s+(\d+)\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+\d'
    )
    for m in pattern.finditer(texte):
        desig = m.group(2).strip()
        if 'taxe' in desig.lower():
            continue
        cond = int(m.group(3))
        qte_packs = int(m.group(4))
        lignes.append({'designation': desig, 'quantite_unites': cond * qte_packs})
    return lignes


def parser_heroic(texte):
    lignes = []
    pattern = re.compile(
        r'(HEROIC\s+SPORT\s+\d+ML\s+[\w\s\-\/]+?)\s+([\d,]+)\s+€/unit\s+[\d\s]+?([\d]+[,]\d{2})\s+€\s*$',
        re.MULTILINE
    )
    for m in pattern.finditer(texte):
        desig = re.sub(r'\s+', ' ', m.group(1)).strip()
        try:
            pu = float(m.group(2).replace(',', '.'))
            total = float(m.group(3).replace(',', '.'))
            qte = round(total / pu)
            if qte > 0:
                lignes.append({'designation': desig, 'quantite_unites': qte})
        except Exception:
            pass
    return lignes


def parser_nxt(texte):
    """Parser NXT pour la comparaison par quantités (fallback)."""
    lignes = []
    vus = set()

    p1 = re.compile(r'^(\d+)\s+Pce\s+\S+\s+\S+\s+(.+?)(?:\n|B2B-FR)', re.MULTILINE)
    for m in p1.finditer(texte):
        qte = int(m.group(1))
        desig = m.group(2).strip()
        if desig and qte > 0 and desig not in vus:
            vus.add(desig)
            lignes.append({'designation': desig, 'quantite_unites': qte})

    p2 = re.compile(r'^(\d[\d ]+)\s+(33\d\d\w+)\s+\S+\s+(.+?)\nPce', re.MULTILINE)
    for m in p2.finditer(texte):
        qte_str = m.group(1).replace(' ', '').strip()
        desig = m.group(3).strip()
        desig = re.sub(r'\s+\d+ml$', '', desig).strip()
        try:
            qte = int(qte_str)
            if qte > 0 and desig and desig not in vus:
                vus.add(desig)
                lignes.append({'designation': desig, 'quantite_unites': qte})
        except Exception:
            pass

    return lignes


def parser_hipro(texte):
    lignes = []
    pattern = re.compile(r'(HIPRO\s+[\w\s]+?)\s+(\d+)\s+[\d,]+', re.IGNORECASE)
    for m in pattern.finditer(texte):
        desig = m.group(1).strip()
        qte = int(m.group(2))
        if qte > 0:
            lignes.append({'designation': desig, 'quantite_unites': qte})
    return lignes


def parser_nutramino(texte):
    lignes = []
    pattern = re.compile(
        r'(Protein\s+[\w\s]+?|Nutra[\w\s]+?|Pre\s+Workout[\w\s]+?)\s+(\d+)\s+[\d,]+',
        re.IGNORECASE
    )
    for m in pattern.finditer(texte):
        desig = m.group(1).strip()
        qte = int(m.group(2))
        if qte > 0:
            lignes.append({'designation': desig, 'quantite_unites': qte})
    return lignes


PARSERS = {
    'LIDIS': parser_lidis,
    'HEROIC': parser_heroic,
    'NXT LEVEL': parser_nxt,
    'HIPRO': parser_hipro,
    'NUTRAMINO': parser_nutramino,
}


# ──────────────────────────────────────────────────────────────────────────────
# NXT LEVEL — COMPARAISON PAR PRIX
# ──────────────────────────────────────────────────────────────────────────────

def extraire_total_net_nxt(texte):
    """Extrait le montant total net HT d'une facture NXT LEVEL."""
    m = re.search(r'Montant total net\s+([\d\s,]+)\s+EUR', texte)
    if m:
        return float(m.group(1).replace(' ', '').replace(',', '.'))
    return None


def extraire_lignes_prix_nxt(texte):
    """
    Extrait les lignes produit NXT avec désignation et total HT.
    Retourne liste de {designation, pu, total_ht, quantite}
    """
    # lignes_desig contient des tuples (designation, quantite) capturés
    # sur la même ligne de texte → appairage fiable, indépendant de l'ordre.
    lignes_desig = []
    vus = set()

    p1 = re.compile(r'^(\d+)\s+Pce\s+\S+\s+\S+\s+(.+?)(?:\n|B2B-FR)', re.MULTILINE)
    for m in p1.finditer(texte):
        qte = int(m.group(1))
        desig = m.group(2).strip()
        if desig and desig not in vus and qte > 0:
            vus.add(desig)
            lignes_desig.append((desig, qte))

    p2 = re.compile(r'^(\d[\d ]+)\s+(33\d\d\w+)\s+\S+\s+(.+?)\nPce', re.MULTILINE)
    for m in p2.finditer(texte):
        desig = m.group(3).strip()
        desig = re.sub(r'\s+\d+ml$', '', desig).strip()
        try:
            qte = int(m.group(1).replace(' ', '').strip())
        except ValueError:
            continue
        if desig and desig not in vus and qte > 0:
            vus.add(desig)
            lignes_desig.append((desig, qte))

    # prix_pattern : uniquement pour PU et total HT (appairage par index, ordre stable)
    prix_pattern = re.compile(
        r'Valeur nette 1\s+([\d,]+)EUR / 1 Pce\s+([\d\s,]+)\s+EUR'
    )
    prix_lignes = []
    for m in prix_pattern.finditer(texte):
        pu = float(m.group(1).replace(',', '.'))
        total = float(m.group(2).replace(' ', '').replace(',', '.'))
        prix_lignes.append({'pu': pu, 'total_ht': total})

    result = []
    for i, (desig, qte) in enumerate(lignes_desig):
        pu = prix_lignes[i]['pu'] if i < len(prix_lignes) else 0
        total_ht = prix_lignes[i]['total_ht'] if i < len(prix_lignes) else 0
        result.append({'designation': desig, 'quantite': qte, 'pu': pu, 'total_ht': total_ht})

    return result


# ──────────────────────────────────────────────────────────────────────────────
# PARSING FACTURE PDF
# ──────────────────────────────────────────────────────────────────────────────

def parser_facture_pdf(pdf_bytes):
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texte = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    except Exception as e:
        raise ValueError(f'Erreur lecture PDF : {e}')

    fournisseur = detecter_fournisseur(texte)
    numero = extraire_numero_facture(texte)
    date = extraire_date(texte)
    depot = extraire_depot(texte)

    parser = PARSERS.get(fournisseur)
    produits = parser(texte) if parser else []

    return {
        'fournisseur': fournisseur,
        'numero_facture': numero,
        'date': date,
        'depot': depot,
        'produits': produits,
        'texte_brut': texte,
    }


# ──────────────────────────────────────────────────────────────────────────────
# PARSING CSV REÇU
# ──────────────────────────────────────────────────────────────────────────────

def parser_csv_recu(csv_bytes):
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes), sep=None, engine='python')
        df.columns = [re.sub(r'^\ufeff|"', '', c).strip() for c in df.columns]

        recu = {}
        prix_recu = {}

        for _, row in df.iterrows():
            nom = ''
            for col in ['Nom commercial', 'Designation', 'Produit', 'Description', 'Nom']:
                if col in df.columns and str(row.get(col, '')).strip():
                    nom = str(row[col]).strip()
                    break
            if not nom:
                nom = str(row.get('Code', '')).strip()

            qte = 0
            for col in ['Qté', 'Quantite', 'Quantité', 'Qte', 'QTE']:
                if col in df.columns:
                    try:
                        qte = float(str(row[col]).replace(',', '.').strip())
                        break
                    except Exception:
                        pass

            total_ht = 0
            for col in ['Mt Net HT', 'Total HT', 'Montant HT']:
                if col in df.columns:
                    try:
                        total_ht = float(str(row[col]).replace(',', '.').strip())
                        break
                    except Exception:
                        pass

            if nom and qte > 0:
                recu[nom] = recu.get(nom, 0) + int(qte)
                prix_recu[nom] = prix_recu.get(nom, 0) + total_ht

        return recu, prix_recu
    except Exception as e:
        raise ValueError(f'Erreur lecture CSV : {e}')


# ──────────────────────────────────────────────────────────────────────────────
# TABLE DE CORRESPONDANCE FIXE
# ──────────────────────────────────────────────────────────────────────────────

TABLE_CORRESPONDANCE = [
    # HEROIC
    ('HEROIC SPORT 500ML CITRON VERT',   'HEROIC CITRON'),
    ('HEROIC SPORT 500ML FRUITS ROUGES', 'HEROIC FRUIT ROUGE'),
    ('HEROIC SPORT 500ML TROPICAL',      'HEROIC TROPICAL'),
    # LIDIS
    ('RPET 50CL EVIAN',                  'EVIAN'),
    ('PET 50CL VOLVIC JUICY FRAISE',     'VOLVIC JUICY FRAISE'),
    ('PET 50CL VOLVIC JUICY EXOTIQUE',   'VOLVIC JUICY EXOTIQUE'),
    ('BOITE 25CL RED BULL ZERO',         'RED BULL ZERO'),
    ('BOITE 25CL RED BULL',              'RED BULL'),
    # NXT LEVEL
    ('RTD Boisson protéinée goût Fraise',   'Strawberry'),
    ('RTD Boisson protéinée goût Chocolat', 'CHOCOLAT'),
    ('RTD Boisson protéinée goût Vanille',  'VANILLE'),
    ('RTD Protein Shake Vanilla',           'VANILLE'),
    ('RTD Protein Shake Chocolate',         'CHOCOLAT'),
    ('Pocket Protein Salty Peanut',         'Salty'),
    ('Pocket Protein Caramel Cookie',       'Caramel Cookie'),
    ('Barre protéinée goût Brownie',        'Brownie'),
    ('Bidon Orange',                        'SPORTBOTTLE'),
    ('Padlock Combination',                 'PADLOCK COMBI'),
    ('Padlock Key',                         'PADLOCK KEY'),
    ('BF Towel Vending',                    'Towel'),
    ('Peanut Boost',                        'PEANUT BOOST'),
    ('Crispy Protein Raspberry Toffee',     'RASPBERRY TOFFEE'),
]


def chercher_table_fixe(nom_facture, noms_recu):
    nom_f_lower = nom_facture.lower()
    for fragment_f, fragment_r in TABLE_CORRESPONDANCE:
        if fragment_f.lower() in nom_f_lower:
            frag_r_lower = fragment_r.lower()
            candidats = [r for r in noms_recu if frag_r_lower in r.lower()]
            if candidats:
                return min(candidats, key=len)
    return None


def normaliser(texte):
    t = texte.lower()
    for k, v in {'é':'e','è':'e','ê':'e','à':'a','â':'a','ô':'o','û':'u','ù':'u','î':'i','ï':'i','ç':'c'}.items():
        t = t.replace(k, v)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _normalize(texte: str) -> str:
    """Normalisation robuste via unicodedata — couvre tous les accents."""
    t = texte.lower().strip()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS MONGODB — CACHE DES CORRESPONDANCES
# ──────────────────────────────────────────────────────────────────────────────

def _get_mongo_db():
    uri = st.secrets['mongo']['uri']
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[st.secrets['mongo']['db_name']]


def load_product_mappings_cache(fournisseur: str) -> dict:
    """Retourne {nom_facture.lower(): nom_interne} depuis MongoDB."""
    try:
        db = _get_mongo_db()
        docs = db['product_mappings'].find({'fournisseur': fournisseur})
        return {d['nom_facture'].lower(): d['nom_interne'] for d in docs}
    except Exception:
        return {}


def save_product_mappings_cache(fournisseur: str, mappings: dict, source: str = 'gemini'):
    """Sauvegarde {nom_facture: nom_interne} dans MongoDB (upsert)."""
    try:
        db = _get_mongo_db()
        col = db['product_mappings']
        for nom_f, nom_r in mappings.items():
            if nom_r:
                col.update_one(
                    {'fournisseur': fournisseur, 'nom_facture': nom_f},
                    {'$set': {'nom_interne': nom_r, 'source': source,
                              'created_at': datetime.datetime.utcnow().isoformat()}},
                    upsert=True,
                )
    except Exception:
        pass



def score_similarite(a, b):
    na, nb = normaliser(a), normaliser(b)
    mots_a = {m for m in na.split() if len(m) > 2}
    mots_b = {m for m in nb.split() if len(m) > 2}
    if not mots_a or not mots_b:
        return 0
    communs = mots_a & mots_b
    return len(communs) / max(len(mots_a), len(mots_b))


def faire_correspondance(noms_facture, noms_recu, fournisseur='INCONNU'):
    """
    Cascade de matching à 3 niveaux :
    0. Cache MongoDB (associations déjà validées)
    1. TABLE_CORRESPONDANCE fixe (substring match)
    2. rapidfuzz token_set_ratio (seuil 72) — robuste aux mots supplémentaires
    """
    cache = load_product_mappings_cache(fournisseur)

    correspondances = {}

    for nom_f in noms_facture:
        # Niveau 0 : cache MongoDB
        if nom_f.lower() in cache:
            correspondances[nom_f] = cache[nom_f.lower()]
            continue

        # Niveau 1 : table fixe
        match = chercher_table_fixe(nom_f, noms_recu)
        if match:
            correspondances[nom_f] = match
            continue

        # Niveau 2 : rapidfuzz token_set_ratio
        best_score, best_match = 0, None
        n_f = _normalize(nom_f)
        for nom_r in noms_recu:
            s = fuzz.token_set_ratio(n_f, _normalize(nom_r))
            if s > best_score:
                best_score, best_match = s, nom_r
        if best_score >= 72:
            correspondances[nom_f] = best_match
            continue

        correspondances[nom_f] = None

    return correspondances


# ──────────────────────────────────────────────────────────────────────────────
# COMPARAISON STANDARD (quantités)
# ──────────────────────────────────────────────────────────────────────────────

def comparer(produits_facture, recu_dict, correspondances):
    rows = []
    noms_recu_couverts = set()

    for p in produits_facture:
        nom_f = p['designation']
        qte_f = p['quantite_unites']
        nom_r = correspondances.get(nom_f)
        qte_r = recu_dict.get(nom_r, 0) if nom_r else 0
        ecart = qte_r - qte_f
        if nom_r:
            noms_recu_couverts.add(nom_r)

        if ecart == 0 and qte_f > 0:
            statut = '✅ OK'
        elif nom_r is None:
            statut = '❓ Non trouvé dans export'
        elif ecart > 0:
            statut = f'⚠️ Surplus (+{ecart})'
        else:
            statut = f'❌ Manquant ({ecart})'

        rows.append({
            'Produit (facture)': nom_f,
            'Produit (export)': nom_r or '—',
            'Facturé': qte_f,
            'Reçu': qte_r,
            'Écart': ecart,
            'Statut': statut,
        })

    for nom, qte in recu_dict.items():
        if nom not in noms_recu_couverts:
            rows.append({
                'Produit (facture)': '—',
                'Produit (export)': nom,
                'Facturé': 0,
                'Reçu': qte,
                'Écart': qte,
                'Statut': '⚠️ Reçu non facturé',
            })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# COMPARAISON NXT PAR PRIX
# ──────────────────────────────────────────────────────────────────────────────

def comparer_nxt_prix(lignes_prix, recu_dict, prix_recu, correspondances=None):
    """
    Compare chaque ligne NXT (facture) avec l'export CSV.
    Utilise le dict correspondances pré-calculé (cascade 4 niveaux).
    """
    rows = []
    noms_recu = list(recu_dict.keys())
    noms_recu_couverts = set()

    for ligne in lignes_prix:
        nom_f = ligne['designation']
        qte_f = ligne['quantite']
        pu_f = ligne['pu']
        total_f = ligne['total_ht']

        match = correspondances.get(nom_f) if correspondances else None

        qte_r = recu_dict.get(match, 0) if match else 0
        ecart = qte_r - qte_f
        if match:
            noms_recu_couverts.add(match)

        if ecart == 0 and qte_f > 0:
            statut = '✅ OK'
        elif match is None:
            statut = '❓ Non trouvé dans export'
        elif ecart > 0:
            statut = f'⚠️ Surplus (+{ecart})'
        else:
            statut = f'❌ Manquant ({ecart})'

        rows.append({
            'Produit (facture)': nom_f,
            'Produit (export)': match or '—',
            'QTE Facturée': qte_f,
            'QTE Reçue': qte_r,
            'Écart QTE': ecart,
            'PU HT (€)': pu_f,
            'Total HT facturé (€)': total_f,
            'Statut': statut,
        })

    for nom, qte in recu_dict.items():
        if nom not in noms_recu_couverts:
            rows.append({
                'Produit (facture)': '—',
                'Produit (export)': nom,
                'QTE Facturée': 0,
                'QTE Reçue': qte,
                'Écart QTE': qte,
                'PU HT (€)': 0,
                'Total HT facturé (€)': 0,
                'Statut': '⚠️ Reçu non facturé',
            })

    return pd.DataFrame(rows)


def colorier_ligne(row):
    s = str(row.iloc[-1])
    if '✅' in s:
        return ['background-color:#1E7E34; color:#FFFFFF; font-weight:600'] * len(row)
    elif '❌' in s:
        return ['background-color:#C0392B; color:#FFFFFF; font-weight:600'] * len(row)
    elif '⚠️' in s:
        return ['background-color:#E67E22; color:#FFFFFF; font-weight:600'] * len(row)
    else:
        return ['background-color:#6C3483; color:#FFFFFF; font-weight:600'] * len(row)


# ──────────────────────────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────────────────────────

def render():
    st.markdown('### 🔍 Contrôle de réception — Facture vs Reçu')
    st.caption('Fonctionne pour : LIDIS, NXT LEVEL, HEROIC, HIPRO, NUTRAMINO')

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('**📄 Facture fournisseur (PDF)**')
        facture_file = st.file_uploader(
            'Facture', type=['pdf'],
            key='controle_facture', label_visibility='collapsed',
        )
    with col2:
        st.markdown('**📦 Export marchandises reçues (CSV)**')
        recu_file = st.file_uploader(
            'Export reçu', type=['csv'],
            key='controle_recu', label_visibility='collapsed',
        )

    if not facture_file or not recu_file:
        st.info("⬆️ Uploade la facture PDF et l'export CSV pour lancer la comparaison.")
        return

    if st.button('🔍 Lancer le contrôle', type='primary', key='btn_controle'):
        with st.spinner('Lecture de la facture...'):
            try:
                data_facture = parser_facture_pdf(facture_file.read())
            except Exception as e:
                st.error(f'Erreur facture : {e}')
                return

        with st.spinner("Lecture de l'export reçu..."):
            try:
                recu_file.seek(0)
                recu_dict, prix_recu = parser_csv_recu(recu_file.read())
            except Exception as e:
                st.error(f'Erreur CSV : {e}')
                return

        fournisseur_detecte = data_facture.get('fournisseur', 'INCONNU')
        noms_f = [p['designation'] for p in data_facture['produits']]
        with st.spinner('Matching des produits (table → fuzzy → Gemini)...'):
            correspondances = faire_correspondance(noms_f, list(recu_dict.keys()), fournisseur=fournisseur_detecte)

        lignes_prix_nxt = None
        total_net_nxt = None
        if data_facture.get('fournisseur') == 'NXT LEVEL':
            lignes_prix_nxt = extraire_lignes_prix_nxt(data_facture['texte_brut'])
            total_net_nxt = extraire_total_net_nxt(data_facture['texte_brut'])

        st.session_state['controle_result'] = {
            'data_facture': data_facture,
            'recu_dict': recu_dict,
            'prix_recu': prix_recu,
            'correspondances': correspondances,
            'lignes_prix_nxt': lignes_prix_nxt,
            'total_net_nxt': total_net_nxt,
        }
        st.rerun()

    if 'controle_result' not in st.session_state:
        return

    data = st.session_state['controle_result']
    data_facture = data['data_facture']
    recu_dict = data['recu_dict']
    prix_recu = data['prix_recu']
    correspondances = data['correspondances']
    produits = data_facture.get('produits', [])

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Fournisseur', data_facture.get('fournisseur', '—'))
    c2.metric('N° Facture', data_facture.get('numero_facture', '—'))
    c3.metric('Date', data_facture.get('date', '—'))
    c4.metric('Dépôt', data_facture.get('depot', '—'))

    if data_facture.get('fournisseur') == 'INCONNU':
        st.warning("⚠️ Fournisseur non reconnu. Envoie un exemple de cette facture pour ajouter le parser.")

    # ── NXT LEVEL : comparaison par prix ──
    if data_facture.get('fournisseur') == 'NXT LEVEL' and data.get('lignes_prix_nxt'):
        lignes_prix = data['lignes_prix_nxt']
        total_facture = data.get('total_net_nxt', 0) or 0

        st.markdown('### 📊 Contrôle NXT LEVEL')

        # Niveau 1 : total HT facture vs total HT export CSV
        total_csv = sum(prix_recu.values())
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.metric('Total HT Facture (€)', f'{total_facture:.2f}')
        col_t2.metric('Total HT Export CSV (€)', f'{total_csv:.2f}')
        ecart_total = round(total_facture - total_csv, 2)
        col_t3.metric('Écart (€)', f'{ecart_total:.2f}')

        if abs(ecart_total) < 0.01:
            st.success('✅ Les totaux correspondent — tout est conforme !')
        else:
            st.error(f'❌ Écart de {ecart_total:.2f}€ — vérification ligne par ligne ci-dessous')

        st.markdown('#### Détail par produit')
        df = comparer_nxt_prix(lignes_prix, recu_dict, prix_recu, correspondances=correspondances)

    else:
        # ── Autres fournisseurs : comparaison par quantités ──
        if not produits:
            st.error("❌ Aucun produit détecté. Le format de cette facture n'est pas encore supporté.")
            with st.expander('📋 Texte brut extrait (pour debug)'):
                st.text(data_facture.get('texte_brut', '')[:3000])
            return
        df = comparer(produits, recu_dict, correspondances)

    nb_ok = len(df[df.iloc[:, -1].str.contains('✅')])
    nb_ko = len(df[df.iloc[:, -1].str.contains('❌')])
    nb_surplus = len(df[df.iloc[:, -1].str.contains('⚠️')])
    nb_nf = len(df[df.iloc[:, -1].str.contains('❓')])

    k1, k2, k3, k4 = st.columns(4)
    k1.metric('✅ Conformes', nb_ok)
    k2.metric('❌ Manquants', nb_ko)
    k3.metric('⚠️ Écarts', nb_surplus)
    k4.metric('❓ Non trouvés', nb_nf)

    st.dataframe(
        df.style.apply(colorier_ligne, axis=1),
        use_container_width=True, hide_index=True,
    )

    # Correction manuelle des correspondances (hors NXT par prix)
    if data_facture.get('fournisseur') != 'NXT LEVEL':
        with st.expander('✏️ Corriger les correspondances'):
            noms_recu_liste = ['—'] + list(recu_dict.keys())
            nouvelles_corr = {}
            for nom_f in [p['designation'] for p in produits]:
                actuel = correspondances.get(nom_f)
                idx = noms_recu_liste.index(actuel) if actuel in noms_recu_liste else 0
                choix = st.selectbox(
                    f'Facture: {nom_f}', noms_recu_liste, index=idx, key=f'corr_{nom_f}',
                )
                nouvelles_corr[nom_f] = choix if choix != '—' else None
            if st.button('🔄 Recalculer', key='btn_recalc'):
                st.session_state['controle_result']['correspondances'] = nouvelles_corr
                save_product_mappings_cache(
                    data_facture.get('fournisseur', 'INCONNU'),
                    {k: v for k, v in nouvelles_corr.items() if v},
                    source='manual',
                )
                st.rerun()

    # Export Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Comparaison', index=False)
        pd.DataFrame(list(recu_dict.items()), columns=['Produit', 'Qté reçue']).to_excel(
            writer, sheet_name='Reçu', index=False
        )
    output.seek(0)

    date_str = datetime.date.today().strftime('%Y%m%d')
    st.download_button(
        label='⬇️ Télécharger le rapport',
        data=output.getvalue(),
        file_name=f'controle_reception_{date_str}.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        use_container_width=True,
    )

    if st.button('🔄 Nouvelle comparaison', key='btn_reset'):
        del st.session_state['controle_result']
        st.rerun()
