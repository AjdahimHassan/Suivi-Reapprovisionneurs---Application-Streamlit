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
