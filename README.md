# Distriprot Data — Outil Réappro

Application Streamlit de suivi des réapprovisionneurs, gestion des planogrammes et analyse des tournées de machines à vending.

---

## Table des matières

1. [Présentation générale](#présentation-générale)
2. [Prérequis & lancement](#prérequis--lancement)
3. [Structure de la base de données (MongoDB)](#structure-de-la-base-de-données-mongodb)
4. [Onglets — guide d'utilisation](#onglets--guide-dutilisation)
   - [Machines](#1--machines)
   - [Tournées (Suivi)](#2--tournées-suivi)
   - [No Audit / Sans Ventes](#3--no-audit--sans-ventes)
   - [Planogrammes](#4--planogrammes)
   - [Inventaires](#5--inventaires)
   - [Commandes](#6--commandes)
   - [Indéfinis](#7--indéfinis)
   - [CR Hebdomadaire](#8--cr-hebdomadaire)
   - [Quartix](#9--quartix)
   - [Picklist](#10--picklist)
   - [Rapport Employé](#11--rapport-employé)
5. [Ce qui impacte quoi — dépendances entre onglets](#ce-qui-impacte-quoi--dépendances-entre-onglets)

---

## Présentation générale

L'application centralise quatre grandes fonctions :

| Domaine | Ce que ça couvre |
|---------|-----------------|
| **Suivi tournées** | Comparer le planning hebdomadaire prévu avec les chargements réels réalisés chaque jour |
| **Qualité réseau** | Détecter les salles sans audits télémétriques, sans ventes, sans chargement prolongé |
| **Planogrammes** | Créer, éditer, importer (PDF) et exporter les planogrammes produits des machines |
| **Reporting** | Générer des rapports Excel/PDF par zone, par employé, par semaine |

---

## Prérequis & lancement

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application nécessite une connexion **MongoDB Atlas** configurée dans les secrets Streamlit (`secrets.toml` ou variables d'environnement) :

```toml
[mongo]
uri = "mongodb+srv://..."
db_name = "nom_de_la_base"
```

Les appels de geocodage (Nominatim) et de routage (OSRM) se font en ligne, sans clé API, mais nécessitent un accès internet.

---

## Structure de la base de données (MongoDB)

Toutes les données persistantes sont stockées dans **MongoDB Atlas**. Voici les collections utilisées et leur rôle.

### `machines`
Inventaire du parc de machines à vending.

| Champ | Description |
|-------|-------------|
| `Code` | Identifiant unique de la machine (salle) |
| `Client` | Nom du client / site |
| `Ville` | Ville d'installation |
| `Code postal` | Code postal |
| `Modèle` | Modèle de la machine |
| `Approvisionneur` | Code du réapprovisionneur assigné |
| `Date d'install` | Date d'installation |
| `Statut` | Actif / Inactif |

**Alimentée par** : onglet Machines (import CSV).
**Lue par** : No Audit, Tournées, Quartix, CR, Rapport Employé.

---

### `plannings`
Plannings hebdomadaires des réapprovisionneurs — quelle salle est prévue quel jour.

| Champ | Description |
|-------|-------------|
| `employe` | Code du réapprovisionneur |
| `semaine` | Numéro de semaine ISO |
| `planning` | Objet `{Lundi: [(client, machine)], Mardi: [...], ...}` |
| `updated_at` | Horodatage de la dernière mise à jour |

**Alimentée par** : import de fichiers CSV de planning (onglet Tournées).
**Lue par** : onglet Tournées (croisement planning vs chargement), CR, Rapport Employé.

---

### `reappros`
Référentiel des réapprovisionneurs (métadonnées).

| Champ | Description |
|-------|-------------|
| `code` | Code employé |
| `prenom` | Prénom |
| `zone` | Zone géographique / secteur |
| `responsable` | Nom du responsable |

**Lue par** : No Audit (groupement par zone), CR, Rapport Employé.

---

### `incidents`
Suivi des incidents réseau : salles sans audit, sans ventes, sans chargement.

| Champ | Description |
|-------|-------------|
| `salle` | Code machine concernée |
| `type` | `no_audit` / `sans_ventes` / `sans_chargement` |
| `commentaire` | Commentaire libre saisi par l'utilisateur |
| `since_date` | Date de début de l'incident |
| `status` | `open` / `resolved` |
| `created_at` / `resolved_at` | Horodatages d'ouverture et de résolution |

**Alimentée par** : No Audit (salles manquantes / zéro ventes), Tournées (salles sans chargement prolongé).
**Lue par** : No Audit (pré-remplissage des commentaires), Rapport Employé.

---

### `justifications_nf`
Justifications saisies pour les salles "Non Faites" lors de l'analyse de tournées.

| Champ | Description |
|-------|-------------|
| `reappro` | Code réapprovisionneur |
| `date_analyse` | Date d'analyse |
| `jour` | Jour concerné |
| `salles` | Liste `[{client, machine, justification}]` |

**Alimentée par** : onglet Tournées (section "Non Faites").
**Lue par** : Rapport Employé.

---

### `bilan_semaine`
Résultats bruts de l'analyse hebdomadaire des tournées.

| Champ | Description |
|-------|-------------|
| `iso_year` / `iso_week` | Année et semaine ISO |
| `rows` | Liste des lignes `[{reappro, jour, machine, statut}]` |

**Alimentée par** : onglet Tournées (sauvegarde des résultats).
**Lue par** : CR Hebdomadaire, Rapport Employé, Inventaires.

---

### `inventaires_semaine`
Suivi des inventaires validés semaine par semaine.

| Champ | Description |
|-------|-------------|
| `iso_year` / `iso_week` | Semaine concernée |
| `saved_at` | Horodatage |
| `done` | Liste `[{reappro, date, code}]` |

**Alimentée & lue par** : onglet Inventaires.

---

### `planogrammes`
Définitions des planogrammes produits.

| Champ | Description |
|-------|-------------|
| `nom` | Nom du planogramme |
| `type` | Type de machine cible |
| `rows` / `cols` | Dimensions de la grille |
| `slots` | Objet `{"r-c": {product, price, qty, color}}` |
| `row_labels` | Labels des lignes |

**Alimentée & lue par** : onglet Planogrammes.

---

### `produits_lib`
Bibliothèque produits (référentiel centralisé).

| Champ | Description |
|-------|-------------|
| `nom` | Nom du produit |
| `code` | Code article |
| `categorie` | Catégorie produit |
| `prix_ht` | Prix HT |
| `prix_achat` | Prix d'achat |
| `tva` | Taux TVA (%) |
| `prix_ttc` | Prix TTC calculé |
| `couleur` | Couleur d'affichage dans la grille |

**Alimentée & lue par** : onglet Planogrammes (bibliothèque produits).

---

### `plannos_theoriques`
Planogrammes théoriques extraits des exports machines.

| Champ | Description |
|-------|-------------|
| `nom` | Identifiant machine/salle |
| `produits` | Liste `[{code, libelle, unite, niv_haut, prix_ttc}]` |

**Alimentée & lue par** : onglet Planogrammes (import depuis export machine).

---

### `quartix_vehicles`
Association plaque d'immatriculation ↔ employé pour les véhicules GPS Quartix.

| Champ | Description |
|-------|-------------|
| `plate` | Plaque d'immatriculation |
| `employe` | Nom/code de l'employé |
| `depot_address` | Adresse du dépôt de départ |
| `depot_coords` | Coordonnées GPS du dépôt |
| `updated_at` | Dernière mise à jour |

**Alimentée & lue par** : onglet Quartix.

---

### `quartix_geocode_cache` et `quartix_routes_cache`
Caches de geocodage (Nominatim) et de tracés de routes (OSRM) pour éviter les appels réseau répétés.

**Alimentées & lues par** : onglet Quartix automatiquement.

---

### `rapport_employe_saves`
Sauvegardes de rapports employé générés.

| Champ | Description |
|-------|-------------|
| `_id` | Nom de la sauvegarde |
| `employe` | Employé concerné |
| `saved_at` | Date de sauvegarde |
| `payload` | Données du rapport sérialisées |

**Alimentée & lue par** : onglet Rapport Employé.

---

### `salles_traitees`
Salles ayant fait l'objet d'un contrôle prix / réception.

| Champ | Description |
|-------|-------------|
| `machine` / `salle` | Identifiants machine |
| `statut` | Résultat du contrôle |
| `raison` | Motif |
| `anomalies` | Anomalies détectées |
| `date_traitement` | Date du contrôle |

**Alimentée & lue par** : onglet Commandes.

---

## Onglets — guide d'utilisation

---

### 1 — Machines

**Objectif** : gérer le référentiel du parc de machines à vending.

**Utilisation pas à pas** :

1. Accéder à l'onglet **Machines** dans la barre de navigation.
2. **Importer le CSV machines** — cliquer sur "Parcourir" et sélectionner l'export CSV (séparateur `;`) provenant du logiciel de gestion.
   Colonnes attendues : `Code`, `Client`, `Ville`, `Code postal`, `Modèle`, `Approvisionneur`, `Date d'install`, `Statut`.
3. Valider l'import — les données sont insérées / mises à jour dans la collection `machines` de MongoDB.
4. Utiliser les **filtres** (zone, approvisionneur, statut) pour naviguer dans le parc.
5. Exporter un sous-ensemble filtré en Excel via le bouton **Télécharger**.

**Ce que cet onglet produit** : le référentiel `machines` utilisé par presque tous les autres onglets pour résoudre les codes salles en noms de clients et zones.

---

### 2 — Tournées (Suivi)

**Objectif** : comparer le planning hebdomadaire prévu avec les chargements réels effectués, et calculer les KPIs de productivité.

**Utilisation pas à pas** :

1. **Importer le planning CSV de la semaine** (si pas encore fait) — format attendu : `Client;Machine;Lundi;Mardi;Mercredi;Jeudi;Vendredi`. Le planning est sauvegardé dans MongoDB (`plannings`).
2. **Importer le CSV chargements** du jour ou de la période — export depuis le logiciel de gestion (colonnes : `Tiers`, `Date début`, `Statut`, `Employé`, `Machine`, `Val. Ref`, etc.).
3. **Sélectionner le jour d'analyse** (Lundi … Vendredi) dans le sélecteur.
4. Lancer l'analyse — l'application croise planning vs chargements et affiche :
   - **KPIs** : Prévues / Faites / Non Faites / Jokers / Décalées / Taux de réalisation
   - **Tableau détaillé** par réapprovisionneur
   - **Jokers** : salle faite par un autre employé que le prévu
   - **Tournées décalées** : employé a réalisé une tournée d'un autre jour
5. Saisir les **justifications** pour les salles Non Faites (sauvegardées dans `justifications_nf`).
6. Exporter le résultat complet en **Excel** (bouton Télécharger).
7. **Section "Sans chargement prolongé"** (en bas de page) :
   - Importer un CSV chargements sur une longue période (ex. 30 jours).
   - Visualiser les salles sans aucun chargement depuis N jours.
   - Sauvegarder les incidents dans la collection `incidents`.

**Dépendances en entrée** : `plannings` (MongoDB), `machines` (MongoDB), CSV chargements (upload).
**Produit** : `bilan_semaine`, `justifications_nf`, `incidents` (MongoDB) + fichier Excel.

---

### 3 — No Audit / Sans Ventes

**Objectif** : détecter les machines qui ne remontent pas de données télémétriques ou qui affichent zéro vente.

Cet onglet est divisé en deux sous-onglets.

#### Sous-onglet "No Audit"

1. **Importer le CSV télémétrie** — export du système d'audit distant (colonnes : `Salle`, `Date`, ..., `Prix`).
2. L'application compare la liste des salles auditées **hier** avec le parc connu (collection `machines`).
3. Les salles absentes du fichier télémétrie = **No Audit**.
4. Saisir un **commentaire** pour chaque salle concernée (ex. : machine en panne, site fermé...).
5. Cliquer **Sauvegarder** — les commentaires sont inscrits dans la collection `incidents` (type `no_audit`).
6. Quand une salle réapparaît dans la télémétrie, l'incident est **auto-résolu**.
7. Exporter un rapport Excel : global ou **par zone** (un onglet par zone + un onglet récap).

#### Sous-onglet "Sans Ventes"

1. Même import de CSV télémétrie.
2. Les salles auditées mais avec `Prix = 0` (ou ventes nulles) = **Sans Ventes**.
3. Même processus de commentaire / sauvegarde dans `incidents` (type `sans_ventes`).
4. Export Excel identique.

**Dépendances en entrée** : `machines` (MongoDB), CSV télémétrie (upload).
**Produit** : collection `incidents` mise à jour + fichiers Excel.

---

### 4 — Planogrammes

**Objectif** : créer, éditer et exporter les planogrammes (dispositions produits) des machines.

L'onglet est organisé en plusieurs vues accessibles via des boutons de navigation internes.

#### Vue "Liste des planogrammes"

- Affiche tous les planogrammes sauvegardés dans MongoDB.
- Boutons : **Créer**, **Éditer**, **Dupliquer**, **Supprimer**.

#### Vue "Éditeur"

1. Définir le **nom**, le **type de machine**, les dimensions (**lignes × colonnes**).
2. Cliquer sur une cellule de la grille pour y assigner un produit :
   - Rechercher dans la **bibliothèque produits** (`produits_lib`) par nom ou code.
   - Renseigner la **quantité** et le **prix TTC**.
3. Le coût total TTC du planogramme est calculé automatiquement (prix achat × TVA × quantité).
4. **Sauvegarder** — écrit dans la collection `planogrammes`.
5. **Exporter** en Excel ou en PDF.

#### Vue "Bibliothèque produits"

- Visualiser / ajouter / modifier les produits dans `produits_lib`.
- Import en masse depuis un fichier Excel (colonnes : `nom`, `code`, `categorie`, `prix_ht`, `prix_achat`, `tva`).

#### Vue "Import PDF"

1. Déposer un PDF de planogramme (format BasicFit ou NXT Level).
2. L'application parse les lignes (Quantité → Produit → Prix) via `pdfplumber`.
3. La grille est pré-remplie automatiquement — vérifier et ajuster si besoin.
4. Sauvegarder le résultat.

#### Vue "Planogrammes théoriques"

- Affiche les planogrammes extraits des exports machines (`plannos_theoriques`).
- Permet de comparer la théorie avec le planogramme réel saisi.

**Dépendances en entrée** : `planogrammes`, `produits_lib`, `plannos_theoriques` (MongoDB), PDF/Excel (upload optionnel).
**Produit** : `planogrammes`, `produits_lib` mis à jour + fichiers Excel/PDF.

---

### 5 — Inventaires

**Objectif** : analyser les inventaires hebdomadaires par réapprovisionneur et détecter les écarts de stock.

**Utilisation pas à pas** :

1. **Importer le CSV d'inventaire** de la semaine (une ligne par machine, avec niveaux de stock par produit).
2. Sélectionner la **semaine ISO** d'analyse.
3. L'application groupe les données par réapprovisionneur et identifie :
   - Dépassements de **seuils** (stock trop bas ou trop haut)
   - **Produits manquants** par rapport au planogramme théorique
   - **Ruptures** potentielles
4. Valider les inventaires réalisés pour une semaine donnée (sauvegarde dans `inventaires_semaine`).
5. Exporter le bilan en **Excel**.

**Dépendances en entrée** : `bilan_semaine`, `machines` (MongoDB), CSV inventaire (upload).
**Produit** : `inventaires_semaine` mis à jour + fichier Excel.

---

### 6 — Commandes

**Objectif** : contrôler la réception des commandes à partir de captures d'écran d'e-mails fournisseurs.

**Utilisation pas à pas** :

1. **Déposer la capture d'écran** de l'e-mail de commande (image PNG/JPG).
2. L'application extrait les lignes produits (référence, quantité, prix) par parsing structuré.
3. Les données sont **injectées dans un template Excel** de bon de réception.
4. Vérifier et ajuster les lignes si besoin.
5. Valider — le résultat est sauvegardé dans `salles_traitees` avec statut et anomalies détectées.
6. Télécharger le fichier Excel généré.

**Dépendances en entrée** : image e-mail (upload), template Excel interne.
**Produit** : `salles_traitees` + fichier Excel.

---

### 7 — Indéfinis

**Objectif** : détecter les produits vendus sous la catégorie "INDEFINI" (paramétrage incorrect dans la machine).

**Utilisation pas à pas** :

1. **Importer le CSV chargements** (même format que l'onglet Tournées).
2. L'application filtre les lignes où le produit n'est pas reconnu et est catégorisé INDEFINI.
3. Le tableau affiche : salle, date, produit non reconnu, valeur vendue.
4. Ces informations permettent de corriger le **paramétrage produit** dans le logiciel de gestion.
5. Export Excel disponible.

**Dépendances en entrée** : CSV chargements (upload).
**Produit** : rapport Excel des lignes INDEFINI (pas de stockage MongoDB).

---

### 8 — CR Hebdomadaire

**Objectif** : générer le compte-rendu hebdomadaire par zone, synthèse des tournées réalisées.

**Utilisation pas à pas** :

1. Sélectionner la **semaine** à reporter.
2. L'application charge les résultats depuis `bilan_semaine` et les regroupe par zone (`reappros`).
3. Le CR affiche pour chaque zone :
   - Nombre de salles prévues / faites / non faites
   - Taux de réalisation
   - Détail par réapprovisionneur
4. Exporter en **PDF** ou **Excel** par zone ou toutes zones.

**Dépendances en entrée** : `bilan_semaine`, `reappros` (MongoDB).
**Produit** : fichiers PDF/Excel de CR.

---

### 9 — Quartix

**Objectif** : visualiser les tournées GPS des conducteurs à partir des exports Quartix.

**Utilisation pas à pas** :

1. **Importer le CSV export Quartix** (données GPS : arrêts, durées, adresses, kilométrage).
2. Configurer l'**association véhicule ↔ employé** dans le panneau de configuration (sauvegardé dans `quartix_vehicles`).
3. Renseigner les **adresses de dépôt** de départ pour chaque véhicule.
4. L'application géocode les adresses via Nominatim (cache dans `quartix_geocode_cache`) et calcule les tracés via OSRM (cache dans `quartix_routes_cache`).
5. La carte **Folium interactive** s'affiche avec :
   - Tracé de la route
   - Marqueurs des arrêts avec durée et adresse
   - Métriques d'efficacité (km/salle, temps/salle)
6. Filtrer par employé ou par date.
7. Exporter le rapport de tournée.

**Dépendances en entrée** : `quartix_vehicles`, caches géocodage/routage (MongoDB), CSV Quartix (upload).
**Produit** : carte interactive + rapport + mise à jour des caches.

---

### 10 — Picklist

**Objectif** : comparer les listes de picking (préparation) avec les chargements réellement effectués et détecter les écarts.

**Utilisation pas à pas** :

1. **Importer le CSV picklist** (liste de préparation prévue : machine, produit, quantité).
2. **Importer le CSV chargements** (réalisé, même format que l'onglet Tournées).
3. L'application croise les deux fichiers ligne par ligne.
4. Le tableau d'écarts affiche :
   - Produits prévus mais non chargés
   - Produits chargés en surplus
   - Quantités différentes
5. Exporter le rapport d'écarts en Excel.

**Dépendances en entrée** : CSV picklist + CSV chargements (uploads).
**Produit** : rapport Excel des écarts (pas de stockage MongoDB).

---

### 11 — Rapport Employé

**Objectif** : générer un rapport de performance détaillé par employé sur une période donnée.

**Utilisation pas à pas** :

1. Sélectionner l'**employé** et la **période** (semaines ISO).
2. L'application agrège depuis `bilan_semaine` et `justifications_nf` :
   - Taux de réalisation semaine par semaine
   - Détail des Non Faites et justifications associées
   - Évolution du nombre de salles prévues vs faites
   - Analyse des jokers et tournées décalées
3. Les graphiques et tableaux sont affichés directement.
4. **Sauvegarder** le rapport dans MongoDB (`rapport_employe_saves`) pour y revenir plus tard.
5. Exporter en **Excel** (multi-onglets) ou **PDF**.

**Dépendances en entrée** : `bilan_semaine`, `justifications_nf`, `incidents`, `reappros` (MongoDB).
**Produit** : `rapport_employe_saves` + fichiers Excel/PDF.

---

## Ce qui impacte quoi — dépendances entre onglets

Le schéma ci-dessous résume les flux de données entre onglets. Une flèche `→` signifie "produit des données utilisées par".

```
┌─────────────┐
│   MACHINES  │ ← Import CSV
│  (référence)│ → machines (MongoDB)
└──────┬──────┘
       │ Résolution code salle → client/zone
       ▼
┌──────────────────────────────────────────┐
│  No Audit · Tournées · Quartix · CR ·    │
│  Rapport Employé · Inventaires           │
└──────────────────────────────────────────┘

┌─────────────┐
│  TOURNÉES   │ ← CSV chargements + plannings (MongoDB)
│   (suivi)   │ → bilan_semaine, justifications_nf, incidents (MongoDB)
└──────┬──────┘
       │
       ├──────────────────────────────► CR Hebdomadaire
       │                                 (lit bilan_semaine)
       └──────────────────────────────► Rapport Employé
                                         (lit bilan_semaine + justifications_nf)

┌─────────────┐
│  NO AUDIT   │ ← CSV télémétrie + machines (MongoDB)
│ SANS VENTES │ → incidents (MongoDB)
└──────┬──────┘
       │
       └──────────────────────────────► Rapport Employé
                                         (lit incidents)

┌──────────────┐
│ PLANOGRAMMES │ ↔ planogrammes, produits_lib, plannos_theoriques (MongoDB)
│              │   (autonome — pas de dépendance aval dans l'app)
└──────────────┘

┌─────────────┐
│ INVENTAIRES │ ← CSV inventaire + bilan_semaine (MongoDB)
│             │ → inventaires_semaine (MongoDB)
└─────────────┘

┌─────────────┐
│  COMMANDES  │ ← Image e-mail (upload)
│             │ → salles_traitees (MongoDB) + Excel
└─────────────┘

┌─────────────┐
│  INDÉFINIS  │ ← CSV chargements (upload)
│             │ → rapport Excel (pas de stockage MongoDB)
└─────────────┘

┌─────────────┐
│   PICKLIST  │ ← CSV picklist + CSV chargements (uploads)
│             │ → rapport Excel (pas de stockage MongoDB)
└─────────────┘

┌─────────────┐
│   QUARTIX   │ ← CSV Quartix (upload) + quartix_vehicles (MongoDB)
│             │ → quartix_vehicles, caches géocodage/routage (MongoDB)
└─────────────┘
```

### Ordre logique de remplissage

Pour un démarrage de zéro, il est recommandé de remplir les données dans cet ordre :

1. **Machines** — importer le parc (référentiel de base de tout le reste).
2. **Tournées** — importer le planning de la semaine puis le CSV chargements.
3. **No Audit / Sans Ventes** — importer la télémétrie du jour.
4. **CR Hebdomadaire / Rapport Employé** — disponibles dès que `bilan_semaine` est alimenté par Tournées.
5. **Planogrammes** — indépendant, peut être rempli à tout moment.
6. **Quartix / Picklist / Indéfinis / Commandes** — au fil des besoins.
