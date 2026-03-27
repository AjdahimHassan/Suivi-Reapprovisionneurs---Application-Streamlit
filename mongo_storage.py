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
