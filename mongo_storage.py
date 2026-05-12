"""
Module de connexion et lecture des plannings depuis MongoDB Atlas.

Structure attendue dans MongoDB :
  Database   : définie dans secrets (MONGO_DB_NAME)
  Collection : définie dans secrets (MONGO_COLLECTION)
  
  Un document par réappro :
  {
    "employe":    "RIDF1",
    "planning":   { "Lundi": [["client", "machine"], ...], "Mardi": [...], ... },
    "semaine":    "S14",
    "updated_at": "2026-03-19"
  }

Configuration (secrets Streamlit) :
  [mongo]
  uri        = "mongodb+srv://user:password@cluster.mongodb.net/"
  db_name    = "suivi_reappro"
  collection = "plannings"
"""

import datetime

import streamlit as st
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError


@st.cache_resource(show_spinner=False)
def _get_client():
    """Retourne un client MongoDB mis en cache (connexion unique)."""
    uri = st.secrets["mongo"]["uri"]
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    # Vérifier que la connexion fonctionne
    client.admin.command("ping")
    return client


def _get_collection():
    client = _get_client()
    db_name  = st.secrets["mongo"]["db_name"]
    col_name = st.secrets["mongo"]["collection"]
    return client[db_name][col_name]


def load_plannings_from_mongo() -> tuple:
    """
    Charge tous les plannings depuis MongoDB.

    Retourne :
        plannings : { employe: { jour: [(client, machine), ...] } }
        errors    : { employe: message_erreur }
    """
    plannings = {}
    errors    = {}

    try:
        col = _get_collection()
        docs = list(col.find({}, {"_id": 0, "employe": 1, "planning": 1}))

        if not docs:
            errors["MongoDB"] = "Aucun document trouvé dans la collection. Vérifie que les plannings ont bien été importés."
            return plannings, errors

        for doc in docs:
            employe = doc.get("employe", "").strip()
            planning_raw = doc.get("planning", {})

            if not employe:
                continue

            # Convertir les listes JSON en tuples (client, machine)
            planning = {}
            for jour, salles in planning_raw.items():
                planning[jour] = [(s[0], s[1]) for s in salles if len(s) >= 2]

            plannings[employe] = planning

    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        errors["MongoDB"] = f"Impossible de se connecter à MongoDB Atlas : {e}"
    except KeyError as e:
        errors["MongoDB"] = (
            f"Clé manquante dans les secrets Streamlit : {e}\n"
            f"Vérifie que secrets.toml contient [mongo] uri, db_name, collection."
        )
    except Exception as e:
        errors["MongoDB"] = f"Erreur inattendue : {e}"

    return plannings, errors


def upsert_planning(employe: str, planning: dict, semaine: str) -> None:
    """Insère ou met à jour le planning d'un réappro dans MongoDB (upsert)."""
    col = _get_collection()
    planning_json = {
        jour: [[c, m] for c, m in salles]
        for jour, salles in planning.items()
    }
    col.update_one(
        {"employe": employe},
        {"$set": {
            "employe":    employe,
            "planning":   planning_json,
            "semaine":    semaine,
            "updated_at": datetime.date.today().isoformat(),
        }},
        upsert=True,
    )


def delete_planning(employe: str) -> None:
    """Supprime le planning d'un réappro depuis MongoDB."""
    col = _get_collection()
    col.delete_one({"employe": employe})


# ─────────────────────────────────────────────────────────────────────────────
# QUARTIX VEHICLES — collection `quartix_vehicles`
#
# Un document par plaque véhicule (= nom de feuille dans l'export QUARTIX) :
# {
#   "plate":         "VEHICULE_1",
#   "employe":       "RIDF1",
#   "depot_address": "3 Rue des Abattoirs, 38120 Saint-Égrève",
#   "depot_coords":  [45.24055, 5.6652996],
#   "updated_at":    "2026-03-27"
# }
# ─────────────────────────────────────────────────────────────────────────────

def _get_qv_col():
    """Retourne la collection quartix_vehicles (même DB que plannings)."""
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["quartix_vehicles"]


def load_quartix_vehicle(plate: str) -> dict | None:
    """Charge les infos (employé + dépôt) d'une plaque véhicule depuis MongoDB."""
    try:
        return _get_qv_col().find_one({"plate": plate}, {"_id": 0})
    except Exception:
        return None


def load_all_quartix_vehicles() -> dict:
    """Retourne {plate: doc} pour toutes les plaques connues en base."""
    try:
        docs = list(_get_qv_col().find({}, {"_id": 0}))
        return {d["plate"]: d for d in docs if "plate" in d}
    except Exception:
        return {}


def upsert_quartix_vehicle(plate: str, employe: str,
                            depot_address: str, depot_coords: list) -> None:
    """Insère ou met à jour les infos d'une plaque véhicule (upsert)."""
    _get_qv_col().update_one(
        {"plate": plate},
        {"$set": {
            "plate":         plate,
            "employe":       employe,
            "depot_address": depot_address,
            "depot_coords":  list(depot_coords),
            "updated_at":    datetime.date.today().isoformat(),
        }},
        upsert=True,
    )


def upsert_quartix_vehicle_info(plate: str, prenom: str = "",
                                 zone: str = "", responsable: str = "") -> None:
    """Met à jour conducteur/zone/responsable d'une plaque sans toucher au dépôt."""
    _get_qv_col().update_one(
        {"plate": plate},
        {"$set": {
            "plate":        plate,
            "prenom":       prenom,
            "zone":         zone,
            "responsable":  responsable,
            "updated_at":   datetime.date.today().isoformat(),
        }},
        upsert=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# QUARTIX GEOCODE CACHE — collection `quartix_geocode_cache`
#
# Stocke les résultats de géocodage Nominatim pour éviter les appels API répétés.
# Un document par adresse :
# { "address": "3 Rue des Abattoirs, 38120 Saint-Égrève", "coords": [45.24, 5.66] }
# coords = null si le géocodage a échoué.
# ─────────────────────────────────────────────────────────────────────────────

def _get_geocode_cache_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["quartix_geocode_cache"]


def load_geocode_cache() -> dict:
    """
    Charge le cache géocodage depuis MongoDB.
    Retourne uniquement les entrées avec coords valides {address: (lat, lon)}.
    Les adresses absentes du cache (ou anciennement en échec) seront réessayées
    avec expansion des abréviations françaises.
    """
    try:
        docs = list(_get_geocode_cache_col().find(
            {"coords": {"$ne": None}},          # ignore les éventuels None résiduels
            {"_id": 0, "address": 1, "coords": 1},
        ))
        return {
            d["address"]: tuple(d["coords"])
            for d in docs if "address" in d and d.get("coords")
        }
    except Exception:
        return {}


def save_geocode_entry(address: str, coords) -> None:
    """
    Sauvegarde une entrée de géocodage réussie dans MongoDB (upsert silencieux).
    Les coords None ne sont PAS sauvegardées : l'adresse sera réessayée
    à la prochaine session (après expansion des abréviations).
    """
    if not coords:
        return
    try:
        _get_geocode_cache_col().update_one(
            {"address": address},
            {"$set": {"address": address, "coords": list(coords)}},
            upsert=True,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# QUARTIX ROUTES CACHE — collection `quartix_routes_cache`
#
# Stocke les routes OSRM entre deux points GPS.
# { "key": "lat1_lon1|lat2_lon2", "route": [[lat, lon], ...] }
# ─────────────────────────────────────────────────────────────────────────────

def _get_routes_cache_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["quartix_routes_cache"]


def _route_key(coord_a, coord_b) -> str:
    return f"{coord_a[0]:.8f}_{coord_a[1]:.8f}|{coord_b[0]:.8f}_{coord_b[1]:.8f}"


def load_routes_cache() -> dict:
    """Charge tout le cache routes en mémoire. Retourne {(coord_a, coord_b): [[lat,lon],...]}."""
    try:
        docs = list(_get_routes_cache_col().find({}, {"_id": 0, "key": 1, "route": 1}))
        cache = {}
        for d in docs:
            if "key" not in d or "route" not in d:
                continue
            try:
                a_str, b_str = d["key"].split("|")
                a = tuple(float(x) for x in a_str.split("_"))
                b = tuple(float(x) for x in b_str.split("_"))
                cache[(a, b)] = d["route"]
            except Exception:
                pass
        return cache
    except Exception:
        return {}


def save_route_entry(coord_a, coord_b, route: list) -> None:
    """Sauvegarde une route OSRM dans MongoDB (upsert silencieux)."""
    try:
        key = _route_key(coord_a, coord_b)
        _get_routes_cache_col().update_one(
            {"key": key},
            {"$set": {"key": key, "route": route}},
            upsert=True,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CACHE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def clear_geocode_cache() -> int:
    """Supprime tous les documents du cache géocodage. Retourne le nombre supprimé."""
    try:
        result = _get_geocode_cache_col().delete_many({})
        return result.deleted_count
    except Exception:
        return 0


def clear_routes_cache() -> int:
    """Supprime tous les documents du cache routes OSRM. Retourne le nombre supprimé."""
    try:
        result = _get_routes_cache_col().delete_many({})
        return result.deleted_count
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# INVENTAIRES SEMAINE — suivi hebdomadaire des inventaires
#
# Un document par semaine ISO :
# {
#   "iso_year":  2026,
#   "iso_week":  15,
#   "saved_at":  "2026-04-10T14:32:00",
#   "done": [{"reappro": "AP", "date": "06/04/2026", "code": "BFBRES12"}, ...]
# }
# ─────────────────────────────────────────────────────────────────────────────

def _get_inv_semaine_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["inventaires_semaine"]


def save_inventaires_semaine(done_records: list, iso_year: int, iso_week: int) -> None:
    """Sauvegarde (upsert) les inventaires faits pour une semaine ISO."""
    col = _get_inv_semaine_col()
    col.update_one(
        {"iso_year": iso_year, "iso_week": iso_week},
        {"$set": {
            "iso_year": iso_year,
            "iso_week": iso_week,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "done":     done_records,
        }},
        upsert=True,
    )


def load_inventaires_semaine(iso_year: int = None, iso_week: int = None) -> dict:
    """
    Charge les inventaires d'une semaine ISO.
    Si iso_year/iso_week non fournis, charge la semaine la plus récente.
    Retourne le document ou {} si absent.
    """
    try:
        col = _get_inv_semaine_col()
        if iso_year is not None and iso_week is not None:
            doc = col.find_one({"iso_year": iso_year, "iso_week": iso_week}, {"_id": 0})
        else:
            doc = col.find_one({}, {"_id": 0}, sort=[("iso_year", -1), ("iso_week", -1)])
        return doc or {}
    except Exception:
        return {}


def list_inventaires_semaines() -> list:
    """Liste toutes les semaines disponibles (triées décroissantes). Retourne [] si erreur."""
    try:
        col  = _get_inv_semaine_col()
        docs = list(col.find(
            {},
            {"_id": 0, "iso_year": 1, "iso_week": 1, "saved_at": 1},
        ).sort([("iso_year", -1), ("iso_week", -1)]))
        return docs
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# BILAN SEMAINE CR — résultats calculés du bilan semaine (salles faites/non faites)
#
# Un document par semaine ISO :
# {
#   "iso_year":  2026,
#   "iso_week":  15,
#   "saved_at":  "2026-04-17T10:00:00",
#   "rows": [{"reappro": "RIDF1", "jour": "Lundi", "ref_date": "13/04/2026",
#             "machine": "2219M1", "salle": "...", "statut": "Non fait", "val": null}, ...]
# }
# ─────────────────────────────────────────────────────────────────────────────

def _get_bilan_semaine_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["bilan_semaine"]


def save_bilan_semaine(rows: list, iso_year: int, iso_week: int, label: str = "") -> None:
    """Sauvegarde (upsert) le bilan calculé pour une semaine ISO."""
    col = _get_bilan_semaine_col()
    col.update_one(
        {"iso_year": iso_year, "iso_week": iso_week},
        {"$set": {
            "iso_year": iso_year,
            "iso_week": iso_week,
            "label":    label,
            "rows":     rows,
        }},
        upsert=True,
    )


def load_bilan_semaine(iso_year: int = None, iso_week: int = None) -> dict:
    """
    Charge le bilan d'une semaine ISO.
    Si iso_year/iso_week non fournis, charge la semaine la plus récente.
    Retourne le document ou {} si absent.
    """
    try:
        col = _get_bilan_semaine_col()
        if iso_year is not None and iso_week is not None:
            doc = col.find_one({"iso_year": iso_year, "iso_week": iso_week}, {"_id": 0})
        else:
            doc = col.find_one({}, {"_id": 0}, sort=[("iso_year", -1), ("iso_week", -1)])
        return doc or {}
    except Exception:
        return {}


def list_bilan_semaines() -> list:
    """Liste toutes les semaines de bilan disponibles (triées décroissantes). Retourne [] si erreur."""
    try:
        col  = _get_bilan_semaine_col()
        docs = list(col.find(
            {},
            {"_id": 0, "iso_year": 1, "iso_week": 1, "saved_at": 1},
        ).sort([("iso_year", -1), ("iso_week", -1)]))
        return docs
    except Exception:
        return []


def delete_bilan_semaine(iso_year: int, iso_week: int) -> None:
    """Supprime le bilan d'une semaine ISO."""
    _get_bilan_semaine_col().delete_one({"iso_year": iso_year, "iso_week": iso_week})


# ─────────────────────────────────────────────────────────────────────────────
# SALLES TRAITÉES — contrôle des prix
# ─────────────────────────────────────────────────────────────────────────────

def _get_salles_traitees_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["salles_traitees"]


def load_salles_traitees() -> list:
    """Retourne tous les documents de salles traitées, triés par date décroissante."""
    try:
        col  = _get_salles_traitees_col()
        docs = list(col.find({}).sort("date_traitement", -1))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []


def valider_salle(machine: str, salle: str, code_client: str, raison: str, anomalies: list) -> bool:
    """Insère ou met à jour une salle traitée. Retourne True si succès."""
    try:
        col = _get_salles_traitees_col()
        col.update_one(
            {"machine": machine},
            {"$set": {
                "machine":          machine,
                "salle":            salle,
                "code_client":      code_client,
                "statut":           "traité",
                "raison":           raison,
                "anomalies":        anomalies,
                "date_traitement":  datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


def devalider_salle(machine: str) -> bool:
    """Supprime une salle des traitées. Retourne True si succès."""
    try:
        _get_salles_traitees_col().delete_one({"machine": machine})
        return True
    except Exception:
        return False


# ── Rapport Employé — sauvegardes ────────────────────────────────────────────

def _get_rapport_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["rapport_employe_saves"]


def save_rapport_employe(name: str, employe: str, payload: dict) -> bool:
    """
    Sauvegarde un rapport employé sous un nom donné.
    `payload` doit être JSON-sérialisable (DataFrames convertis en records avant l'appel).
    """
    try:
        _get_rapport_col().replace_one(
            {"_id": name},
            {
                "_id":        name,
                "employe":    employe,
                "saved_at":   datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "payload":    payload,
            },
            upsert=True,
        )
        return True
    except Exception:
        return False


def list_rapport_employe_saves() -> list[dict]:
    """Retourne la liste des sauvegardes triées par date desc. Chaque entrée : {name, employe, saved_at}."""
    try:
        docs = _get_rapport_col().find({}, {"_id": 1, "employe": 1, "saved_at": 1})
        return sorted(
            [{"name": d["_id"], "employe": d.get("employe", ""), "saved_at": d.get("saved_at", "")}
             for d in docs],
            key=lambda x: x["saved_at"],
            reverse=True,
        )
    except Exception:
        return []


def load_rapport_employe_save(name: str) -> dict | None:
    """Charge une sauvegarde par son nom. Retourne le payload ou None."""
    try:
        doc = _get_rapport_col().find_one({"_id": name})
        return doc.get("payload") if doc else None
    except Exception:
        return None


def delete_rapport_employe_save(name: str) -> bool:
    """Supprime une sauvegarde."""
    try:
        _get_rapport_col().delete_one({"_id": name})
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# JUSTIFICATIONS NON FAITES — raisons pour les salles non réalisées
#
# Un document par (réappro, date_analyse) :
# {
#   "reappro":      "RIDF1",
#   "date_analyse": "2026-04-30",
#   "jour":         "Lundi",
#   "salles":       [{"client": "...", "machine": "..."}, ...],
#   "justification":"Absent pour maladie",
#   "saved_at":     "2026-04-30T10:00:00"
# }
# ─────────────────────────────────────────────────────────────────────────────

def _get_justif_nf_col():
    client  = _get_client()
    db_name = st.secrets["mongo"]["db_name"]
    return client[db_name]["justifications_nf"]


def save_justification_nf(reappro: str, date_analyse: str, jour: str,
                           salles: list) -> bool:
    """
    Upsert les justifications par salle pour un réappro et une date donnés.
    salles : [{"client": "...", "machine": "...", "justification": "..."}, ...]
    """
    try:
        _get_justif_nf_col().update_one(
            {"reappro": reappro, "date_analyse": date_analyse},
            {"$set": {
                "reappro":      reappro,
                "date_analyse": date_analyse,
                "jour":         jour,
                "salles":       salles,
                "saved_at":     datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


def load_justifications_nf(date_analyse: str) -> list:
    """Retourne toutes les justifications enregistrées pour une date d'analyse donnée."""
    try:
        docs = list(_get_justif_nf_col().find(
            {"date_analyse": date_analyse},
            {"_id": 0},
        ).sort("reappro", 1))
        return docs
    except Exception:
        return []


def update_justification_nf_date(reappro: str, old_date: str, new_date: str) -> bool:
    """Corrige la date_analyse d'une entrée justifications_nf (reappro + ancienne date → nouvelle date)."""
    try:
        col = _get_justif_nf_col()
        # Récupérer le doc existant
        doc = col.find_one({"reappro": reappro, "date_analyse": old_date})
        if not doc:
            return False
        # Calculer le nouveau jour_fr à partir de new_date
        new_dt  = datetime.date.fromisoformat(new_date)
        jours   = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi",
                   5: "Samedi", 6: "Dimanche"}
        new_jour = jours[new_dt.weekday()]
        col.update_one(
            {"reappro": reappro, "date_analyse": old_date},
            {"$set": {"date_analyse": new_date, "jour": new_jour}},
        )
        return True
    except Exception:
        return False


def list_weeks_justifications_nf() -> list:
    """
    Retourne la liste des semaines ISO disponibles dans justifications_nf.
    Résultat : [(iso_year, iso_week), ...] triées décroissantes.
    """
    try:
        docs = list(_get_justif_nf_col().find({}, {"_id": 0, "date_analyse": 1}))
        weeks = set()
        for doc in docs:
            try:
                d = datetime.date.fromisoformat(doc["date_analyse"])
                iso = d.isocalendar()
                weeks.add((iso.year, iso.week))
            except Exception:
                pass
        return sorted(weeks, reverse=True)
    except Exception:
        return []


def load_justifications_nf_week(iso_year: int, iso_week: int) -> list:
    """
    Retourne tous les docs de justifications_nf pour la semaine ISO donnée,
    triés par date puis réappro.
    """
    try:
        monday = datetime.date.fromisocalendar(iso_year, iso_week, 1)
        sunday = datetime.date.fromisocalendar(iso_year, iso_week, 7)
        docs = list(_get_justif_nf_col().find(
            {"date_analyse": {"$gte": monday.isoformat(), "$lte": sunday.isoformat()}},
            {"_id": 0},
        ).sort([("date_analyse", 1), ("reappro", 1)]))
        return docs
    except Exception:
        return []
