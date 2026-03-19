"""
Script one-shot pour importer les plannings CSV dans MongoDB Atlas.
Lance : python import_plannings_mongo.py
"""

import os
import datetime
from pymongo import MongoClient
from planning_parser import parse_planning_file

MONGO_URI  = "mongodb+srv://admin:admin@tournees.d5m0xjg.mongodb.net/"
DB_NAME    = "suivi_reappro"
COLLECTION = "plannings"
PLANNINGS_DIR = "./plannings"

def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print("Connexion MongoDB OK")

    col = client[DB_NAME][COLLECTION]
    col.create_index("employe", unique=True)

    ok, errors = 0, []
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
            total = sum(len(v) for v in planning.values())
            print(f"  OK  {employe} — {total} salles ({semaine})")
            ok += 1
        except Exception as e:
            errors.append(f"  ERR {employe} : {e}")
            print(errors[-1])

    print(f"\nImport termine : {ok} reappros importes, {len(errors)} erreur(s).")
    client.close()

if __name__ == "__main__":
    main()
