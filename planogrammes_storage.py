"""
Stockage MongoDB pour les planogrammes et la bibliothèque de produits.

Collections :
  planogrammes  : un document par planogramme
  produits_lib  : un document par produit de la bibliothèque

Structure planogramme :
{
  "_id": ObjectId,
  "nom": "Double BF Oct 2025",
  "type": "double",         # "simple" ou "double"
  "rows": 4,
  "cols": 16,
  "row_labels": ["R1", "R2", ...],
  "slots": {
    "0-0": {"product": "Red Bull", "price": "3.00", "qty": "9", "color": "#1a2f47"},
    "0-1": {"product": "Evian",    "price": "1.99", "qty": "8", "color": ""},
    ...
  },
  "created_at": "2026-03-19",
  "updated_at": "2026-03-19"
}

Structure produit bibliothèque :
{
  "_id": ObjectId,
  "nom": "Red Bull 250ml",
  "code": "REDBULL25CL",
  "categorie": "Boissons",
  "couleur": "#1a2f47",
  "prix_ht": "2.840",
  "prix_achat": "1.130",
  "tva": "5.5",
  "prix_ttc": "2.9962",
  "created_at": "2026-03-19"
}
"""

import streamlit as st
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId
import datetime


# ── Client partagé ──────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_client():
    uri = st.secrets["mongo"]["uri"]
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client


def _get_db():
    client = _get_client()
    return client[st.secrets["mongo"]["db_name"]]


def _col_planogrammes():
    return _get_db()["planogrammes"]


def _col_produits():
    return _get_db()["produits_lib"]


def _today():
    return datetime.date.today().isoformat()


def _to_str_id(doc):
    """Convertit ObjectId en string pour usage dans Streamlit."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ════════════════════════════════════════════════════════
# PLANOGRAMMES
# ════════════════════════════════════════════════════════

def load_planogrammes() -> list:
    """Retourne tous les planogrammes triés par nom."""
    try:
        col = _col_planogrammes()
        docs = list(col.find({}).sort("nom", 1))
        return [_to_str_id(d) for d in docs]
    except Exception as e:
        st.error(f"Erreur chargement planogrammes : {e}")
        return []


def save_planogramme(plano: dict) -> str:
    """
    Crée ou met à jour un planogramme.
    Si plano contient '_id', fait un update. Sinon, insère.
    Retourne l'_id (string).
    """
    col = _col_planogrammes()
    plano["updated_at"] = _today()

    if "_id" in plano and plano["_id"]:
        oid = ObjectId(plano["_id"])
        data = {k: v for k, v in plano.items() if k != "_id"}
        col.update_one({"_id": oid}, {"$set": data}, upsert=True)
        return str(oid)
    else:
        plano.pop("_id", None)
        plano["created_at"] = _today()
        result = col.insert_one(plano)
        return str(result.inserted_id)


def delete_planogramme(plano_id: str) -> bool:
    """Supprime un planogramme par son _id."""
    try:
        col = _col_planogrammes()
        result = col.delete_one({"_id": ObjectId(plano_id)})
        return result.deleted_count > 0
    except Exception as e:
        st.error(f"Erreur suppression : {e}")
        return False


def duplicate_planogramme(plano_id: str) -> str:
    """Duplique un planogramme et retourne le nouvel _id."""
    col = _col_planogrammes()
    doc = col.find_one({"_id": ObjectId(plano_id)})
    if not doc:
        return None
    doc.pop("_id")
    doc["nom"] = doc.get("nom", "Planogramme") + " (copie)"
    doc["created_at"] = _today()
    doc["updated_at"] = _today()
    result = col.insert_one(doc)
    return str(result.inserted_id)


# ════════════════════════════════════════════════════════
# BIBLIOTHÈQUE PRODUITS
# ════════════════════════════════════════════════════════

def load_produits() -> list:
    """Retourne tous les produits triés par nom."""
    try:
        col = _col_produits()
        docs = list(col.find({}).sort("nom", 1))
        return [_to_str_id(d) for d in docs]
    except Exception as e:
        st.error(f"Erreur chargement produits : {e}")
        return []


def save_produit(produit: dict) -> str:
    """Crée ou met à jour un produit. Retourne l'_id."""
    col = _col_produits()
    if "_id" in produit and produit["_id"]:
        oid = ObjectId(produit["_id"])
        data = {k: v for k, v in produit.items() if k != "_id"}
        col.update_one({"_id": oid}, {"$set": data}, upsert=True)
        return str(oid)
    else:
        produit.pop("_id", None)
        produit["created_at"] = _today()
        result = col.insert_one(produit)
        return str(result.inserted_id)


def delete_produit(produit_id: str) -> bool:
    """Supprime un produit par son _id."""
    try:
        col = _col_produits()
        result = col.delete_one({"_id": ObjectId(produit_id)})
        return result.deleted_count > 0
    except Exception as e:
        st.error(f"Erreur suppression produit : {e}")
        return False
