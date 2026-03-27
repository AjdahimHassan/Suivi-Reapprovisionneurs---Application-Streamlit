# 📦 Suivi Réapprovisionneurs — Application Streamlit

Application web de gestion opérationnelle pour les équipes de réapprovisionnement de distributeurs automatiques.
Développée avec **Streamlit**, connectée à **MongoDB Atlas** pour le stockage des données.

---

## 🗺️ Pages de l'application

L'application est composée de **8 modules** accessibles depuis la barre de navigation en haut de page.

| # | Page | Icône | Description |
|---|------|-------|-------------|
| 1 | Machines | 🖥️ | Visualisation du parc de distributeurs automatiques en exploitation |
| 2 | Suivi Réapprovisionneurs | 📦 | Analyse quotidienne des passages en salle |
| 3 | No Audit / Ventes | 📉 | Détection des salles sans audit ou sans ventes depuis X jours |
| 4 | Planogrammes | 🗂️ | Gestion des plans de remplissage des machines |
| 5 | Inventaires | 📊 | Contrôle des inventaires machines par réappro |
| 6 | Commandes | 🛒 | Suivi des commandes fournisseurs |
| 7 | Indéfinis | ❓ | Détection des lignes mal paramétrées (ventes INDÉFINI) |
| 8 | CR | 📝 | Génération des comptes rendus hebdomadaires par zone |

---

## 📋 Détail des fonctionnalités

### 🖥️ Machines

Visualisation et gestion du parc de distributeurs automatiques.

- Import du parc depuis un export CSV (écrase les données précédentes)
- Stockage dans MongoDB (collection `machines`)
- Données réutilisées par les pages No Audit / Ventes et CR

### 📦 Suivi Réapprovisionneurs

Module principal de suivi quotidien. Croise le planning de chaque réappro avec le fichier de chargement machine du jour.

- ✅ **Salles faites** : détecte les passages validés (`Statut = "Fait"` ET `Val. Ref ≠ 0`)
- ❌ **Salles non faites** : identifie les salles prévues mais non effectuées
- 🔄 **Jokers** : détecte quand un réappro a fait la salle d'un collègue
- 📅 **Tournées décalées** : détecte quand un réappro a effectué sa tournée un autre jour que prévu
- 📊 **Export Excel** : génère un fichier complet avec 38 onglets colorés (récap, non faites, jokers, décalées, détail par réappro)
- ⚙️ **Gestion des plannings depuis l'UI** :
  - 📥 Import / mise à jour de plannings CSV directement dans l'app
  - 🗑️ Suppression de plannings directement dans l'app

### 📉 No Audit / Ventes

Analyse de la télémétrie pour détecter les machines inactives.

- **No Audit** : salles absentes de la télémétrie depuis X jours (non auditées)
- **Sans Ventes** : salles auditées mais sans ventes (Price = 0, ou ≤ 1,99 € si option activée)
- Source des salles : collection MongoDB `machines`
- Source télémétrie : fichier CSV uploadé (col 0 = Salle, col 1 = Date, col 6 = Prix)

### 🗂️ Planogrammes

Gestionnaire visuel des plans de remplissage des machines.

- Création, modification et suppression de planogrammes
- Bibliothèque de produits partagée (référentiel `produits_lib`)
- Gestion des slots (ligne, capacité, couleur)
- Export PDF (orientation paysage, taille de police adaptative jusqu'à 4pt pour les planogrammes larges)
- Duplication de planogrammes existants
- Stockage MongoDB (collections `planogrammes` et `produits_lib`)

### 📊 Inventaires

Analyse des inventaires machines uploadés au format CSV.

- Détection automatique du type de machine (BF Simple / BF Double / FP IDF / FP Province / WUF)
  — Les machines "Double" sont détectées par la présence de produits Volvic (VOLVICEXOTIC50CL / VOLVICFRAISE50CL)
- Comparaison du montant HT inventorié aux seuils min/max par type :

  | Type machine | Min | Max |
  |---|---|---|
  | BF Simple | 380 € | 480 € |
  | BF Double | 700 € | 957,50 € |
  | FP IDF | 300 € | 409 € |
  | FP Province | 300 € | 412 € |
  | WUF / Autre | 280 € | 400 € |

- Croisement avec le planning MongoDB pour détecter les inventaires non réalisés
- Détail des produits manquants (quantité = 0)

### 🛒 Commandes

Suivi des commandes fournisseurs par extraction automatique depuis un screenshot de mail.

- Upload d'une image de mail de commande
- Extraction des quantités via l'API Gemini (vision)
- Injection dans le fichier Excel de suivi stocké dans MongoDB (collection `suivi_excel`)
- Gestion de deux fournisseurs : **LIDIS** et **HIPRO**

### ❓ Indéfinis

Outil de diagnostic pour identifier les lignes machine mal paramétrées qui génèrent des ventes en `INDEFINI`.

- Upload du fichier de ventes (export audit machine) et du fichier planogramme (configuration machine)
- Détection automatique de toutes les lignes `INDEFINI` dans les ventes
- Pour chaque indéfini : identification du prix et recherche dans le planno des lignes au même prix qui n'ont **pas vendu**
- Ces lignes sont les **suspects** d'un mauvais paramétrage (spirale mal associée à un produit)
- Affichage différencié : 🔴 suspects (non vendus) vs 🟢 lignes correctement vendues
- Message de diagnostic synthétique par cas

### 📝 CR — Compte Rendu Hebdomadaire

Génération automatique des emails de compte rendu par zone géographique.

- Sources : collections MongoDB `reappros` (zones ↔ réappros), `machines` (parc), `incidents` (problèmes actifs)
- Génération d'un email formaté par zone

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
(plannings + planogrammes + produits + commandes + machines)
```

- Les **fichiers CSV planning** peuvent être importés **depuis le PC** (script) **ou depuis l'app** (expander dédié)
- Le **code** est sur GitHub, déployé automatiquement sur Streamlit Cloud à chaque push
- Les **données** (plannings, planogrammes, produits, fichier Excel commandes, machines) sont dans MongoDB Atlas
- Le **fichier de chargement** et les **fichiers d'audit** sont uploadés directement dans l'app au besoin

---

## 📁 Structure du projet

```
├── app.py                      # Application principale — navigation et routing entre pages
├── page_machines.py            # Module Machines (parc de distributeurs)
├── page_no_audit.py            # Module No Audit / Sans Ventes
├── page_planogrammes.py        # Module Planogrammes (UI complète)
├── page_inventaires.py         # Module Inventaires
├── page_commandes.py           # Module Commandes (extraction Gemini + Excel)
├── page_indefinis.py           # Module Détection des Indéfinis
├── page_cr.py                  # Module Compte Rendu hebdomadaire
├── page_controle_reception.py  # Module Contrôle réception (factures fournisseurs)
├── planogrammes_storage.py     # Accès MongoDB pour planogrammes et produits_lib
├── planning_parser.py          # Parsing des fichiers CSV planning
├── chargement_parser.py        # Parsing du fichier de chargement + détection tournées décalées
├── mongo_storage.py            # Connexion MongoDB : lecture, upsert et suppression de plannings
├── excel_export.py             # Génération du fichier Excel coloré (38 onglets)
├── import_plannings_mongo.py   # Script one-shot d'import CSV → MongoDB (local uniquement)
├── requirements.txt            # Dépendances Python
├── .gitignore                  # Exclut secrets.toml et __pycache__
├── .streamlit/
│   └── secrets.toml            # Secrets locaux (NON pushé sur GitHub)
└── plannings/                  # Fichiers CSV des plannings (NON pushés sur GitHub)
    ├── RIDF1.csv
    ├── RIDF2.csv
    ├── AC.csv
    └── ...
```

---

## 🗄️ Structure MongoDB

```
Cluster   : Tournees
Database  : suivi_reappro
```

| Collection | Contenu | Utilisée par |
|---|---|---|
| `plannings` | Un document par réappro avec planning semaine | Suivi, Inventaires |
| `planogrammes` | Un document par planogramme de machine | Planogrammes |
| `produits_lib` | Bibliothèque de produits (référentiel) | Planogrammes |
| `suivi_excel` | Fichier Excel de suivi commandes | Commandes |
| `machines` | Parc de distributeurs automatiques | Machines, No Audit, CR |
| `reappros` | Répartition zones ↔ réappros | CR |
| `incidents` | Incidents actifs non résolus | CR |
| `product_mappings` | Cache des correspondances produits facture ↔ reçu | Contrôle réception |

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

---

## 📂 Format des fichiers

### Fichier CSV planning (un par réappro)

```
Client;Machine;S13 - L 23;Ma 24;Me 25;J 26;V 27;S 28;D 29;S14 - L 30;Ma 31;Me 1;J 2;V 3;S 4;D 5
FTPA61 - FP BRIE COMTE ROBERT;3218M1;1;;;;;;;1;;;;;;
BFP155 - BF SERRIS;3236M1;2;;;;;;;2;;;;;;
```

- Les colonnes représentent les jours sur **2 semaines**
- Une cellule non vide = la salle est planifiée ce jour-là
- Le script garde automatiquement la **semaine avec le plus de salles**

### Fichier de chargement machine (upload quotidien — page Suivi)

```
Tiers;Date début;Statut;Employé;Machine;Commentaire;Val. Ref;...
BF PONT SAINTE MARIE;13/03/2026 15:26;Fait;RCHAMPAGNE;2427M1;;115,52;...
```

Une salle est considérée **faite** si : `Statut = "Fait"` **ET** `Val. Ref ≠ 0`

### Fichier de ventes audit machine (page Indéfinis)

```
SOURCE AUDIT;CODE MACHINE;CODE CLIENT;MODELE MACHINE;CODE PRODUIT;PU;LDP;PAYMENT
"Audit IUC180";"1112M1";"BF SAINT OUEN";"JOFEMAR VISION COMBO+";"NXTPREWKORANGE";"3,5";"11";"CB"
```

### Fichier planogramme machine (page Indéfinis)

```
"Configuration";;;;;"Tarif CB";;
"Code";"Libellé";"Unité";"Niv.haut";"Prix u.b. TTC";"Ligne de prix";
"NXTPEANUTBOOST";"NXT PEANUT BOOST";"BARRE";15;3,7;20;
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

Les plannings peuvent être gérés de **deux façons** : depuis l'app ou depuis le terminal.

### ✅ Depuis l'application (recommandé)

Dans la page **Suivi Réapprovisionneurs**, section **⚙️ Plannings chargés** :

**Importer / mettre à jour un planning**
1. Déplier **📥 Mettre à jour les plannings**
2. Déposer un ou plusieurs fichiers `{réappro}.csv`
3. Cliquer **📥 Importer** → chaque planning est inséré ou mis à jour (upsert)
4. La liste se rafraîchit automatiquement

**Supprimer un planning**
1. Déplier **🗑️ Supprimer un planning**
2. Sélectionner un ou plusieurs réappros dans le menu déroulant
3. Cliquer **🗑️ Supprimer (N)** → les plannings sont supprimés de MongoDB
4. La liste se rafraîchit automatiquement

### 🖥️ Depuis le terminal (méthode alternative)

Placer les fichiers CSV dans `plannings/` puis :

```bash
python import_plannings_mongo.py
```
Le script fait un `upsert` : il **crée ou écrase** chaque document existant.

---

## ☁️ Déploiement sur Streamlit Cloud

### 1. Pusher le code sur GitHub
```bash
git add .
git commit -m "mise a jour"
git push origin main
```
> Le dossier `plannings/` et `.streamlit/secrets.toml` sont exclus automatiquement par `.gitignore`

### 2. Autoriser Streamlit Cloud dans MongoDB Atlas
1. Atlas → **Security** → **Network Access**
2. **Add IP Address** → **Allow Access from Anywhere** (`0.0.0.0/0`)
3. Confirm

> ✅ Chaque `git push` redéploie automatiquement l'app. Les données dans MongoDB ne sont pas affectées.

---

## 🎨 Code couleur

| Couleur | Signification |
|---------|---------------|
| 🟢 Vert `#1E7E34` | Salle faite normalement |
| 🔴 Rouge `#C0392B` | Salle non faite / ligne suspecte (indéfinis) |
| 🟠 Orange `#E67E22` | Joker — faite par un autre réappro |
| 🟣 Violet `#6C3483` | Tournée décalée — faite un autre jour |

---

## 📊 Export Excel (Suivi Réapprovisionneurs)

Le fichier Excel généré contient **38 onglets** :

| Onglet | Contenu |
|--------|---------|
| `Récapitulatif` | Vue globale de tous les réappros avec taux et tournées décalées |
| `Salles Non Faites` | Liste complète des salles non effectuées |
| `Jokers - Remplacements` | Remplacements entre réappros |
| `Tournees Decalees` | Réappros ayant fait une tournée d'un autre jour |
| `RIDF1` ... `YZ` | Détail par réappro (34 onglets) |

---

## 🔁 Workflows quotidiens

### Suivi réappros (chaque matin)
```
1. Ouvrir l'app → page "Suivi Réapprovisionneurs"
2. Sélectionner le jour dans le sélecteur "Jour d'analyse"
3. Uploader le fichier de chargement machine du jour (export CSV)
4. Cliquer "Lancer l'analyse"
5. Consulter les résultats (onglets : récap, non faites, jokers, décalées)
6. Télécharger l'export Excel si besoin
```

### Diagnostic indéfinis (au besoin)
```
1. Ouvrir l'app → page "Indéfinis"
2. Uploader le fichier de ventes (export audit machine)
3. Uploader le fichier planogramme de la machine concernée
4. Lire le diagnostic : lignes suspectes en rouge = à vérifier sur la machine
```

### Mise à jour planogramme
```
1. Ouvrir l'app → page "Planogrammes"
2. Créer ou modifier un planogramme
3. Exporter en PDF si besoin pour affichage sur site
```

### No Audit / Sans Ventes
```
1. Ouvrir l'app → page "No Audit / Ventes"
2. Uploader le fichier de télémétrie CSV
3. Configurer la période (nombre de jours)
4. Consulter les onglets "No Audit" et "Sans Ventes"
```

---

## 📦 Dépendances

```
streamlit>=1.32.0
pandas>=2.0.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
pymongo>=4.6.0
reportlab>=4.0.0
pdfplumber>=0.10.0
requests>=2.31.0
```
