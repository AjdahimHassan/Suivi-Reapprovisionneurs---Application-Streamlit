# 📦 Distriprot Data — Application Streamlit

Application web de gestion opérationnelle pour les équipes de réapprovisionnement de distributeurs automatiques.
Développée avec **Streamlit**, connectée à **MongoDB Atlas** pour le stockage des données.

---

## 🗺️ Pages de l'application

L'application est composée de **10 modules** accessibles depuis la barre de navigation en haut de page.

| # | Page | Icône | Description |
|---|------|-------|-------------|
| 1 | Machines | 🖥️ | Visualisation et gestion du parc de distributeurs en exploitation |
| 2 | Tournées | 📦 | Analyse quotidienne des passages en salle (croisement planning × chargement) |
| 3 | No Audit / Ventes | 📉 | Détection des salles sans audit ou sans ventes depuis X jours |
| 4 | Planogrammes | 🗂️ | Gestion visuelle des plans de remplissage des machines |
| 5 | Inventaires | 📊 | Contrôle des inventaires machines par réappro avec seuils par type |
| 6 | Commandes | 🛒 | Extraction commandes depuis screenshot mail (Gemini) + injection Excel |
| 7 | Indéfinis & Prix | ❓ | Détection lignes INDÉFINI + contrôle des prix de vente HT par machine |
| 8 | CR | 📝 | Génération des comptes rendus hebdomadaires par zone géographique |
| 9 | Quartix | 🗺️ | Visualisation des trajets réappros sur carte (Folium + QUARTIX) |
| 10 | Picklist | 📋 | Comparaison picklist prévue vs chargement réel machine |

---

## 📋 Détail des fonctionnalités

### 🖥️ Machines

Visualisation et gestion du parc de distributeurs automatiques.

- Import du parc depuis un export CSV (écrase les données précédentes)
- Stockage dans MongoDB (collection `machines`)
- KPIs : nb machines, nb villes, nb approvisionneurs
- Filtres par approvisionneur, ville, modèle + barre de recherche
- Résumé d'import : nouvelles machines, supprimées, conservées
- Données réutilisées par No Audit, Inventaires, CR

---

### 📦 Tournées (Suivi Réapprovisionneurs)

Module principal de suivi quotidien. Croise le planning de chaque réappro avec le fichier de chargement machine du jour.

- ✅ **Salles faites** : passages validés (`Statut = "Fait"` ET `Val. Ref ≠ 0`)
- ❌ **Salles non faites** : salles prévues mais non effectuées
- 🔄 **Jokers** : détecte quand un réappro a fait la salle d'un collègue
- 📅 **Tournées décalées** : réappro ayant effectué sa tournée un autre jour que prévu
- 📊 **Export Excel** : fichier complet (récap global, non faites, jokers, décalées, détail par réappro)
- ⚙️ **Gestion des plannings depuis l'UI** :
  - 📥 Import / mise à jour de plannings CSV directement dans l'app
  - 🗑️ Suppression de plannings directement dans l'app

---

### 📉 No Audit / Ventes

Analyse de la télémétrie pour détecter les machines inactives.

- **Onglet No Audit** : salles absentes de la télémétrie depuis J-1 ou plus
- **Onglet Sans Ventes** : salles auditées mais sans ventes (Price = 0, ou ≤ 1,99 € si option activée)
- Commentaires persistants par salle (MongoDB collection `incidents`)
- Auto-résolution des incidents quand la salle disparaît de la liste
- Export Excel (deux feuilles : No Audit + Sans Ventes)
- Historique des problèmes résolus

---

### 🗂️ Planogrammes

Gestionnaire visuel des plans de remplissage des machines.

- Création, modification, duplication et suppression de planogrammes
- Éditeur de grille visuel (slots, produits, couleurs, capacités)
- Bibliothèque de produits partagée : CRUD complet, champs prix achat HT + TVA
- Calcul automatique de la valeur totale du planogramme
- Export PDF (orientation paysage, taille police adaptative jusqu'à 4pt)
- Import/Export Excel (conservation du format)
- Stockage MongoDB (collections `planogrammes` et `produits_lib`)

---

### 📊 Inventaires

Analyse des inventaires machines uploadés au format CSV.

- Détection automatique du type de machine :
  - BF Simple / **BF Double** (détecté par présence de Volvic : VOLVICEXOTIC50CL / VOLVICFRAISE50CL)
  - FP IDF / FP Province / WUF / Autre

- Comparaison du montant HT inventorié aux seuils par type :

  | Type machine | Min | Max |
  |---|---|---|
  | BF Simple | 380 € | 480 € |
  | BF Double | 700 € | 957,50 € |
  | FP IDF | 300 € | 409 € |
  | FP Province | 300 € | 412 € |
  | WUF / Autre | 280 € | 400 € |

- Statuts : 🟢 OK / 🔴 Mal fait (< min) / 🟠 Au-dessus du max
- Croisement avec planning MongoDB pour détecter les jokers d'inventaire
- Détail des produits manquants (quantité = 0) par machine

---

### 🛒 Commandes

Suivi des commandes fournisseurs par extraction automatique depuis un screenshot de mail.

- Upload d'une image ou saisie de texte de mail de commande
- Extraction des quantités via l'**API Gemini** (vision)
- 5 fournisseurs supportés : **LIDIS**, **HIPRO**, **HEROIC**, **NXT LEVEL**, **NUTRAMINO**
- Correction manuelle avant injection (ajout/suppression de lignes)
- Injection dans le fichier Excel de suivi stocké dans MongoDB (`suivi_excel`)
- Gestion des formules et colonnes spécifiques par fournisseur
- **Mode Contrôle** : comparaison facture PDF vs marchandises reçues CSV

---

### ❓ Indéfinis & Contrôle des prix

Module double pour diagnostiquer les problèmes de paramétrage machine et de tarification.

#### Onglet 1 — Indéfinis

Identification des spirales mal associées qui génèrent des ventes INDÉFINI.

- Upload du fichier de ventes machine (export audit CSV) et du planogramme (CSV configuration)
- Détection automatique de toutes les lignes `CODE_PRODUIT = INDÉFINI`
- Pour chaque prix INDÉFINI : recherche dans le planogramme des produits au même prix sans vente (suspects) et avec vente (références)
- 🔴 Suspects = spirales mal paramétées à corriger / 🟢 Références = paramétrage correct

#### Onglet 2 — Contrôle des prix HT

Vérification systématique des prix de vente réels contre les prix de référence bibliothèque.

**Analyse ERP :**
- Import du fichier Audit Télémétrie (CSV séparé par `;`)
- Calcul du prix unitaire réel : `PU_HT = Montant HT ÷ Quantité`
- Comparaison aux prix HT de la bibliothèque produits (tolérance ±0,05 €)
- Gestion multi-prix : un produit peut avoir plusieurs prix valides (ex : Red Bull 2,84 € ou 3,03 € HT selon type de machine)
- Détection des lignes `INDÉFINI` dans l'ERP comme anomalies à part entière
- Exclusion automatique des salles déjà validées comme traitées

**KPIs :** lignes analysées, % conformes, nb anomalies, salles concernées, codes non référencés

**Coloration des écarts :**

| Couleur | Écart |
|---------|-------|
| 🔴 Rouge | ≥ 0,50 € |
| 🟠 Orange | ≥ 0,20 € |
| 🟡 Jaune | < 0,20 € |

**Export par réappro :** génère un Excel (feuille résumé + une feuille par réappro) depuis le planning MongoDB

**Détail par machine :**
- 🔍 Barre de recherche par code machine ou nom de réappro
- 📂 Import du fichier de ventes machine (CSV audit IUC180) par machine
- Tableau avec surlignage :
  - 🔴 Rouge : prix incorrect ou produit INDÉFINI
  - 🟡 Jaune : LDP (Ligne De Prix) en doublon sur la machine
- 4ème colonne **"Prix attendu (TTC)"** tenant compte du type de machine :
  - Machine `BF...` → prix TTC le plus bas de la bibliothèque
  - Machine `FP...` → prix TTC le plus haut de la bibliothèque
- Résumé textuel des anomalies : erreurs de prix, INDÉFINI, doublons LDP
- Export **Excel** et **PNG** par machine (mise en forme identique au tableau)
- Bouton **✅ Marquer comme traité** : valide la salle en base de données (MongoDB)

**Onglet Salles traitées :**
- Liste toutes les salles validées avec date, résumé des erreurs et détail des anomalies
- Bouton **↩️ Dévalider** pour remettre une salle dans l'analyse
- Les salles traitées n'apparaissent plus dans les nouvelles analyses ERP

---

### 📝 CR — Compte Rendu Hebdomadaire

Génération automatique des emails de compte rendu par zone géographique.

- Sources : collections MongoDB `reappros` (zones ↔ réappros), `machines` (parc), `incidents` (problèmes actifs)
- Zones : IDF, OUEST, NORD ET CENTRE, SUD OUEST, SUD EST, EST
- Sections customisables : Livraisons/Fournisseurs, Tournées, Inventaire
- KPI par zone : nb incidents actifs, nb salles concernées

---

### 🗺️ Quartix

Visualisation des trajets journaliers des réappros depuis les données QUARTIX.

- Import du fichier Excel QUARTIX (multi-feuilles, multi-véhicules)
- Sélecteur véhicule + journée
- **Carte Folium interactive** : tracé complet du trajet + cercles proportionnels aux durées d'arrêt
- Géocodage Nominatim avec cache MongoDB (`quartix_geocode_cache`)
- Enrichissement OSRM pour tracé précis des routes (`quartix_routes_cache`)
- KPIs : distance minimale dépôt avant 11h et après 18h, passages dépôt
- Persistance employé ↔ véhicule (collection `quartix_vehicles`)

---

### 📋 Picklist

Comparaison de la picklist prévisionnelle avec le chargement réel machine.

- Import picklist CSV et fichier chargement ERP (CSV `;`)
- Croisement ligne par ligne par (machine × produit)
- Statuts : ✅ Conforme / ❌ Non chargé / ⚠️ Insuffisant / 🔄 Surplus / ℹ️ Non prévu
- Résumé global : taux de conformité, nb écarts
- Détail par machine et par réappro (expandeurs)
- Export Excel avec mise en forme couleur

---

## 🏗️ Architecture

```
PC Local                    GitHub                  Streamlit Cloud
─────────                   ──────                  ───────────────
plannings/ (CSV)            code source      →      app déployée
     │                      (sans secrets)          (lit MongoDB)
     │ import_plannings_mongo.py
     │                                              ┌─ Importer planning CSV
     │                                              │  (expander "📥 Mettre à jour")
     ▼                                              └─ Supprimer un planning
MongoDB Atlas                          ◄────────────   (expander "🗑️ Supprimer")
(toutes les collections)
```

- Les **plannings** peuvent être importés depuis le PC (script) **ou depuis l'app** (expander dédié)
- Le **code** est sur GitHub, déployé automatiquement sur Streamlit Cloud à chaque push
- Les **données** sont dans MongoDB Atlas (collections listées ci-dessous)
- Les **fichiers de chargement, audit et inventaires** sont uploadés directement dans l'app

---

## 📁 Structure du projet

```
├── app.py                      # Application principale — navigation et routing
├── page_machines.py            # Module Machines (parc de distributeurs)
├── page_no_audit.py            # Module No Audit / Sans Ventes
├── page_planogrammes.py        # Module Planogrammes (UI complète)
├── page_inventaires.py         # Module Inventaires
├── page_commandes.py           # Module Commandes (extraction Gemini + Excel)
├── page_indefinis.py           # Module Indéfinis + Contrôle des prix
├── page_cr.py                  # Module Compte Rendu hebdomadaire
├── page_quartix.py             # Module Trajets QUARTIX (carte Folium)
├── page_picklist.py            # Module Picklist vs Chargement
├── page_controle_reception.py  # Module Contrôle réception (factures fournisseurs)
├── planogrammes_storage.py     # Accès MongoDB pour planogrammes et produits_lib
├── planning_parser.py          # Parsing des fichiers CSV planning
├── chargement_parser.py        # Parsing du fichier de chargement + tournées décalées
├── mongo_storage.py            # MongoDB : plannings, salles traitées, caches Quartix
├── excel_export.py             # Génération du fichier Excel coloré (Tournées)
├── import_plannings_mongo.py   # Script one-shot d'import CSV → MongoDB (local)
├── requirements.txt            # Dépendances Python
├── .gitignore                  # Exclut secrets.toml et __pycache__
├── .streamlit/
│   └── secrets.toml            # Secrets locaux (NON pushé sur GitHub)
└── plannings/                  # Fichiers CSV des plannings (NON pushés sur GitHub)
```

---

## 🗄️ Structure MongoDB

```
Cluster   : Tournees
Database  : suivi_reappro
```

| Collection | Contenu | Utilisée par |
|---|---|---|
| `plannings` | Un document par réappro avec planning semaine | Tournées, Inventaires |
| `planogrammes` | Grilles de remplissage des machines | Planogrammes |
| `produits_lib` | Bibliothèque de produits (codes, prix HT, TVA, prix TTC) | Planogrammes, Contrôle des prix |
| `machines` | Parc de distributeurs EN EXPLOITATION | Machines, No Audit, CR |
| `incidents` | Incidents No Audit / Sans Ventes (actif/résolu) | No Audit |
| `reappros` | Répartition zones ↔ réappros | CR |
| `suivi_excel` | Fichier Excel de suivi commandes | Commandes |
| `salles_traitees` | Salles avec anomalies de prix corrigées et validées | Contrôle des prix |
| `quartix_vehicles` | Liaison véhicule QUARTIX ↔ employé | Quartix |
| `quartix_geocode_cache` | Cache des géocodages Nominatim | Quartix |
| `quartix_routes_cache` | Cache des calculs d'itinéraire OSRM | Quartix |
| `product_mappings` | Correspondances produits facture ↔ reçu | Contrôle réception |

### Format d'un document planning
```json
{
  "employe": "RIDF1",
  "semaine": "S13",
  "updated_at": "2026-03-27",
  "planning": {
    "Lundi":    [["FTPA61 - FP BRIE COMTE ROBERT", "3218M1"], "..."],
    "Mardi":    [["BFP40 - BF CLICHY LA GARENNE", "1138M1"], "..."],
    "Mercredi": ["..."],
    "Jeudi":    ["..."],
    "Vendredi": ["..."]
  }
}
```

### Format d'un document salle traitée
```json
{
  "machine":         "1036M1",
  "salle":           "BF LANGON",
  "code_client":     "BFLGN01",
  "statut":          "traité",
  "raison":          "2 anomalie(s) de prix | 1 produit(s) INDÉFINI",
  "anomalies":       [{"Code": "EVIAN50CL", "Prix attendu (HT)": 0.95, "Prix réel (HT)": 1.65, "Écart (€)": 0.7}],
  "date_traitement": "2026-04-01"
}
```

---

## 📂 Format des fichiers

### Fichier CSV planning (un par réappro)
```
Client;Machine;S13 - L 23;Ma 24;Me 25;J 26;V 27;S 28;D 29;S14 - L 30;...
FTPA61 - FP BRIE COMTE ROBERT;3218M1;1;;;;;;;1;;;;;;
BFP155 - BF SERRIS;3236M1;2;;;;;;;2;;;;;;
```

### Fichier de chargement machine (Tournées)
```
Tiers;Date début;Statut;Employé;Machine;Commentaire;Val. Ref;...
BF PONT SAINTE MARIE;13/03/2026 15:26;Fait;RCHAMPAGNE;2427M1;;115,52;...
```
Salle considérée **faite** si : `Statut = "Fait"` **ET** `Val. Ref ≠ 0`

### Fichier ERP Audit Télémétrie (Contrôle des prix)
```
Type tâche;Code DA;Stock Destination;Nom client;Code produit;Libellé produit;Quantité;Montant HT;Date
Audit Telemetrie;1036M1;BFLGN01;BF LANGON;EVIAN50CL;Evian 50cl;24;22,80;31/03/2026
```
PU_HT calculé = Montant HT ÷ Quantité

### Fichier de ventes machine — Audit IUC180 (Contrôle des prix, par machine)
```
SOURCE AUDIT;CODE MACHINE;CODE CLIENT;MODELE MACHINE;CODE PRODUIT;PU;LDP;PAYMENT
"Audit IUC180";"1036M1";"BF LANGON";"JOFEMAR VISION COMBO+";"EVIAN50CL";"1,99";"22";"CB"
```

### Fichier d'inventaire machine
```
Num Piece;Date;Stock Origine;Code client;Nom client;Ressource;Code produit;Libellé produit;Quantité;Montant HT
INV-001;01/04/2026;STOCK;BF0001;BF LANGON;RCHAMPAGNE;EVIAN50CL;Evian 50cl;24;22,80
```

---

## 🔧 Installation locale

### Prérequis
- Python 3.11+
- Un compte MongoDB Atlas avec le cluster `Tournees` configuré

### 1. Cloner le repo
```bash
git clone git@github.com:AjdahimHassan/Suivi-Reapprovisionneurs---Application-Streamlit.git
cd Suivi-Reapprovisionneurs---Application-Streamlit
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Lancer l'application
```bash
streamlit run app.py
```
L'application s'ouvre sur http://localhost:8501

---

## 🗄️ Gestion des plannings

### ✅ Depuis l'application (recommandé)

Dans la page **Tournées**, section **⚙️ Plannings chargés** :

**Importer / mettre à jour un planning**
1. Déplier **📥 Mettre à jour les plannings**
2. Déposer un ou plusieurs fichiers `{réappro}.csv`
3. Cliquer **📥 Importer** → upsert dans MongoDB
4. La liste se rafraîchit automatiquement

**Supprimer un planning**
1. Déplier **🗑️ Supprimer un planning**
2. Sélectionner un ou plusieurs réappros
3. Cliquer **🗑️ Supprimer (N)** → suppression de MongoDB

### 🖥️ Depuis le terminal (méthode alternative)
```bash
python import_plannings_mongo.py
```

---

## ☁️ Déploiement sur Streamlit Cloud

### 1. Pusher le code sur GitHub
```bash
git add .
git commit -m "mise a jour"
git push origin main
```

### 2. Autoriser Streamlit Cloud dans MongoDB Atlas
1. Atlas → **Security** → **Network Access**
2. **Add IP Address** → **Allow Access from Anywhere** (`0.0.0.0/0`)

> ✅ Chaque `git push` redéploie automatiquement l'app. Les données MongoDB ne sont pas affectées.

---

## 🎨 Code couleur

| Couleur | Page | Signification |
|---------|------|---------------|
| 🟢 Vert | Tournées | Salle faite normalement |
| 🔴 Rouge | Tournées / Prix | Salle non faite / Erreur de prix / INDÉFINI |
| 🟠 Orange | Tournées / Prix | Joker — fait par un autre réappro / Écart ≥ 0,20 € |
| 🟣 Violet | Tournées | Tournée décalée — faite un autre jour |
| 🟡 Jaune | Prix | Doublon LDP / Écart < 0,20 € |
| 🟢 Vert | Prix | Salle validée comme traitée |

---

## 🔁 Workflows

### Suivi réappros (chaque matin)
```
1. Ouvrir l'app → page "Tournées"
2. Sélectionner le jour dans le sélecteur "Jour d'analyse"
3. Uploader le fichier de chargement machine du jour (export CSV)
4. Cliquer "Lancer l'analyse"
5. Consulter les résultats (récap, non faites, jokers, décalées)
6. Télécharger l'export Excel si besoin
```

### Contrôle des prix (périodique)
```
1. Ouvrir l'app → page "Indéfinis & Prix" → onglet "Contrôle des prix"
2. Uploader le fichier ERP Audit Télémétrie (.csv)
3. Cliquer "Analyser"
4. Consulter les KPIs et les anomalies détectées
5. Pour chaque machine à corriger :
   a. Ouvrir l'expander de la machine
   b. Importer le fichier de ventes machine (CSV audit IUC180)
   c. Consulter le tableau surlignée + le résumé des erreurs
   d. Exporter en Excel ou PNG pour partager
   e. Une fois corrigée sur la machine : cliquer "✅ Marquer comme traité"
6. Exporter par réappro via le menu "Sélectionner les réappros à exporter"
7. Consulter l'onglet "✅ Salles traitées" pour le suivi global
```

### Diagnostic indéfinis (au besoin)
```
1. Ouvrir l'app → page "Indéfinis & Prix" → onglet "Indéfinis"
2. Uploader le fichier de ventes (export audit machine)
3. Uploader le fichier planogramme de la machine concernée
4. Lire le diagnostic : lignes suspectes en rouge = spirales à vérifier
```

### No Audit / Sans Ventes
```
1. Ouvrir l'app → page "No Audit / Ventes"
2. Uploader le fichier de télémétrie CSV
3. Configurer la période (nombre de jours)
4. Consulter les onglets "No Audit" et "Sans Ventes"
5. Ajouter des commentaires sur les salles problématiques
```

### Mise à jour planogramme
```
1. Ouvrir l'app → page "Planogrammes"
2. Créer ou modifier un planogramme
3. Exporter en PDF si besoin pour affichage sur site
```

---

## 📦 Dépendances

```
streamlit>=1.32.0
matplotlib>=3.7.0
pandas>=2.0.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
pymongo>=4.6.0
reportlab>=4.0.0
pdfplumber>=0.10.0
requests>=2.31.0
rapidfuzz>=3.0.0
geopy>=2.4.0
folium>=0.16.0
streamlit-folium>=0.20.0
xlrd>=2.0.0
```
