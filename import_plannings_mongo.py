"""
Script d'import des plannings CSV dans MongoDB Atlas.
Lance : python import_plannings_mongo.py

A chaque exécution :
  1. Supprime TOUS les documents de la collection plannings
  2. Réinsère tous les plannings depuis les fichiers CSV
=> Garantit que MongoDB est toujours un miroir exact du dossier plannings/
"""

import os
import datetime
from pymongo import MongoClient
from planning_parser import parse_planning_file

MONGO_URI     = "mongodb+srv://admin:admin@tournees.d5m0xjg.mongodb.net/"
DB_NAME       = "suivi_reappro"
COLLECTION    = "plannings"
PLANNINGS_DIR = "./plannings"


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print("Connexion MongoDB OK")

    col = client[DB_NAME][COLLECTION]

    # ── Étape 1 : suppression complète de la collection ──────────────
    nb_supprimes = col.count_documents({})
    col.drop()
    print(f"Collection vidée ({nb_supprimes} document(s) supprimé(s))")

    # ── Étape 2 : réinsertion depuis les CSV ─────────────────────────
    docs  = []
    errors = []

    for fname in sorted(os.listdir(PLANNINGS_DIR)):
        if not fname.endswith(".csv"):
            continue
        employe = fname.replace(".csv", "").strip()
        path = os.path.join(PLANNINGS_DIR, fname)
        try:
            with open(path, "rb") as f:
                planning, semaine = parse_planning_file(f.read(), employe)

            planning_json = {
                jour: [[c, m] for c, m in salles]
                for jour, salles in planning.items()
            }

            docs.append({
                "employe":    employe,
                "planning":   planning_json,
                "semaine":    semaine,
                "updated_at": datetime.date.today().isoformat(),
            })
            total = sum(len(v) for v in planning.values())
            print(f"  OK  {employe} — {total} salles ({semaine})")

        except Exception as e:
            errors.append(f"  ERR {employe} : {e}")
            print(errors[-1])

    # Insertion en une seule opération bulk
    if docs:
        col.insert_many(docs)
        col.create_index("employe", unique=True)

    print(f"\nImport terminé : {len(docs)} réappro(s) importé(s), {len(errors)} erreur(s).")
    client.close()


if __name__ == "__main__":
    main()
