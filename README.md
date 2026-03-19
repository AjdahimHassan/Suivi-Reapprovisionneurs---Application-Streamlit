# 📦 Suivi Réapprovisionneurs — Application Streamlit

Application web de suivi quotidien des passages en salle des réapprovisionneurs.  
Développée avec **Streamlit**, connectée à **MongoDB Atlas** pour le stockage des plannings.

---

## 📋 Fonctionnalités

- ✅ **Suivi quotidien** : croise le planning de chaque réappro avec le fichier de chargement machine du jour
- ❌ **Salles non faites** : identifie les salles prévues mais non effectuées
- 🔄 **Jokers** : détecte quand un réappro a fait la salle d'un collègue
- 📅 **Tournées décalées** : détecte quand un réappro a effectué sa tournée d'un autre jour (ex: tournée du Lundi faite un Mardi)
- 📊 **Export Excel** : génère un fichier Excel complet avec 38 onglets colorés (récap, non faites, jokers, tournées décalées, détail par réappro)
- 🗄️ **MongoDB Atlas** : les plannings sont stockés en base de données, indépendamment du code

---

## 🏗️ Architecture

```
PC Local                    GitHub                  Streamlit Cloud
─────────                   ──────                  ───────────────
plannings/ (CSV)            code source      →      app déployée
     │                      (sans secrets)          (lit MongoDB)
     │ import_plannings_mongo.py
     ▼
MongoDB Atlas
(plannings stockés)
```

- Les **fichiers CSV** restent sur ton PC, ils ne vont **jamais** sur GitHub
- Le **code** est sur GitHub, déployé automatiquement sur Streamlit Cloud à chaque push
- Les **plannings** sont dans MongoDB Atlas, lus par l'app au démarrage
- Le **fichier de chargement** est uploadé chaque jour directement dans l'app

---

## 📁 Structure du projet

```
├── app.py                      # Application principale Streamlit
├── planning_parser.py          # Parsing des fichiers CSV planning
├── chargement_parser.py        # Parsing du fichier de chargement machine + détection tournées décalées
├── mongo_storage.py            # Connexion et lecture des plannings depuis MongoDB
├── excel_export.py             # Génération du fichier Excel coloré
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

## 📂 Format des fichiers CSV planning

Chaque réappro a son propre fichier CSV nommé d'après son identifiant (ex: `RIDF1.csv`).

```
Client;Machine;S13 - L 23;Ma 24;Me 25;J 26;V 27;S 28;D 29;S14 - L 30;Ma 31;Me 1;J 2;V 3;S 4;D 5
FTPA61 - FP BRIE COMTE ROBERT;3218M1;1;;;;;;;1;;;;;;
BFP155 - BF SERRIS;3236M1;2;;;;;;;2;;;;;;
```

- Les colonnes représentent les jours sur **2 semaines**
- Une cellule non vide = la salle est planifiée ce jour-là
- Le script garde automatiquement la **semaine avec le plus de salles**

## 📂 Format du fichier de chargement machine

Export quotidien au format CSV séparé par `;` :

```
Tiers;Date début;Statut;Employé;Machine;Commentaire;Val. Ref;...
BF PONT SAINTE MARIE;13/03/2026 15:26;Fait;RCHAMPAGNE;2427M1;;115,52;...
```

Une salle est considérée **faite** si : `Statut = "Fait"` **ET** `Val. Ref ≠ 0`

---

## 🗄️ Structure MongoDB

```
Cluster   : Tournees
Database  : suivi_reappro
Collection: plannings
```

Un document par réappro :
```json
{
  "employe": "RIDF1",
  "semaine": "S13",
  "updated_at": "2026-03-19",
  "planning": {
    "Lundi":    [["FTPA61 - FP BRIE COMTE ROBERT", "3218M1"], ...],
    "Mardi":    [["BFP40 - BF CLICHY LA GARENNE", "1138M1"], ...],
    "Mercredi": [...],
    "Jeudi":    [...],
    "Vendredi": [...]
  }
}
```

---

## 🔧 Installation locale

### Prérequis
- Python 3.11+
- Un compte MongoDB Atlas avec le cluster `Tournees` configuré
- Accès au repo GitHub

### 1. Cloner le repo
```bash
git clone git@github.com:AjdahimHassan/Suivi-Reapprovisionneurs---Application-Streamlit.git
cd Suivi-Reapprovisionneurs---Application-Streamlit
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Configurer les secrets locaux
Créer le fichier `.streamlit/secrets.toml` :
```toml
[mongo]
uri        = "mongodb+srv://admin:admin@tournees.d5m0xjg.mongodb.net/"
db_name    = "suivi_reappro"
collection = "plannings"
```
> ⚠️ Ce fichier est dans `.gitignore` — il ne sera jamais pushé sur GitHub.

### 4. Lancer l'application
```bash
streamlit run app.py
```
L'application s'ouvre sur http://localhost:8501

---

## 🗄️ Gestion des plannings (workflow local)

Les plannings CSV sont stockés **uniquement sur ton PC** dans le dossier `plannings/`.  
Pour mettre à jour la base de données MongoDB :

### Modifier un planning
1. Ouvre le fichier CSV correspondant dans `plannings/` (ex: `plannings/RIDF1.csv`)
2. Modifie les données directement dans le CSV
3. Sauvegarde

### Importer dans MongoDB
```bash
python import_plannings_mongo.py
```
Le script fait un `upsert` : il **crée ou écrase** chaque document existant.  
L'app Streamlit relit automatiquement depuis MongoDB (cache rafraîchi toutes les 5 minutes).

### Exemple de sortie du script
```
Connexion MongoDB OK
  OK  AC — 37 salles (S14)
  OK  AP — 40 salles (S14)
  OK  RIDF1 — 42 salles (S13)
  ...
Import termine : 34 reappros importes, 0 erreur(s).
```

---

## ☁️ Déploiement sur Streamlit Cloud

### 1. Pusher le code sur GitHub
```bash
git add .
git commit -m "mise a jour"
git push origin main
```
> Le dossier `plannings/` et `.streamlit/secrets.toml` sont exclus automatiquement par `.gitignore`

### 2. Configurer les secrets sur Streamlit Cloud
1. Aller sur [share.streamlit.io](https://share.streamlit.io)
2. Cliquer sur l'app → **Settings** → **Secrets**
3. Coller :
```toml
[mongo]
uri        = "mongodb+srv://admin:admin@tournees.d5m0xjg.mongodb.net/"
db_name    = "suivi_reappro"
collection = "plannings"
```
4. Cliquer **Save** → l'app redémarre automatiquement

### 3. Autoriser Streamlit Cloud dans MongoDB Atlas
1. Atlas → **Security** → **Network Access**
2. **Add IP Address** → **Allow Access from Anywhere** (`0.0.0.0/0`)
3. Confirm

> ✅ Chaque `git push` redéploie automatiquement l'app. Les plannings dans MongoDB ne sont pas affectés.

---

## 🎨 Code couleur

| Couleur | Signification |
|---------|---------------|
| 🟢 Vert foncé | Salle faite normalement |
| 🔴 Rouge | Salle non faite |
| 🟠 Orange | Joker — faite par un autre réappro |
| 🟣 Violet | Tournée décalée — faite un autre jour |

---

## 📊 Export Excel

Le fichier Excel généré contient **38 onglets** :

| Onglet | Contenu |
|--------|---------|
| `Récapitulatif` | Vue globale de tous les réappros avec taux et tournées décalées |
| `Salles Non Faites` | Liste complète des salles non effectuées |
| `Jokers - Remplacements` | Remplacements entre réappros |
| `Tournees Decalees` | Réappros ayant fait une tournée d'un autre jour |
| `RIDF1` ... `YZ` | Détail par réappro (34 onglets) |

---

## 🔁 Workflow quotidien

```
Chaque matin
─────────────
1. Ouvrir l'app Streamlit
2. Sélectionner le jour dans la sidebar
3. Uploader le fichier de chargement machine du jour (export CSV)
4. Cliquer "Lancer l'analyse"
5. Consulter les résultats (onglets : récap, non faites, jokers, décalées)
6. Télécharger l'export Excel si besoin
```
