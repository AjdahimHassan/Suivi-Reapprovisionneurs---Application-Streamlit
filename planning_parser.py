"""
Parser des fichiers planning réapprovisionneurs.

Format réel des fichiers CSV :
  Client;Machine;S13 - L 23;Ma 24;Me 25;J 26;V 27;S 28;D 29;S14 - L 30;Ma 31;Me 1;J 2;V 3;S 4;D 5

- Les colonnes après "Machine" sont les jours sur 2 semaines.
- Une cellule non vide = la salle est planifiée ce jour-là (valeur = ordre de passage).
- On retient la semaine avec le plus de salles planifiées.
"""

import pandas as pd
import io
from pathlib import Path
from collections import defaultdict

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]

JOUR_MAP_WEEKDAY = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi",
    3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche",
}

ABBR_TO_JOUR = {
    "l": "Lundi", "ma": "Mardi", "me": "Mercredi",
    "j": "Jeudi", "v": "Vendredi", "s": None, "d": None,
}


def _parse_col_info(day_cols: list) -> list:
    current_semaine = None
    result = []
    for col in day_cols:
        c = col.strip()
        if " - " in c:
            parts = c.split(" - ", 1)
            current_semaine = parts[0].strip()
            jour_part = parts[1].strip()
        else:
            jour_part = c
        abbr = jour_part.split()[0].lower()
        jour_fr = ABBR_TO_JOUR.get(abbr)
        result.append((col, current_semaine, jour_fr))
    return result


def parse_planning_file(file_bytes: bytes, employe: str) -> tuple:
    try:
        df = pd.read_csv(
            io.BytesIO(file_bytes), sep=";", dtype=str,
            encoding="utf-8-sig", on_bad_lines="skip"
        )
    except Exception as e:
        raise ValueError(f"Impossible de lire le fichier de {employe} : {e}")

    df.columns = [c.strip() for c in df.columns]

    if "Client" not in df.columns or "Machine" not in df.columns:
        raise ValueError(
            f"Format invalide pour {employe} : colonnes Client et Machine attendues.\n"
            f"Colonnes trouvees : {list(df.columns)}"
        )

    day_cols = [c for c in df.columns if c not in ("Client", "Machine")]
    col_info = _parse_col_info(day_cols)

    semaine_count = defaultdict(int)
    for col, sem, jour_fr in col_info:
        if jour_fr is None or sem is None:
            continue
        count = df[col].apply(lambda v: str(v).strip() not in ("", "nan")).sum()
        semaine_count[sem] += int(count)

    if not semaine_count:
        raise ValueError(f"Aucune salle planifiee pour {employe}.")

    best_semaine = max(semaine_count, key=semaine_count.get)

    planning = defaultdict(list)
    for col, sem, jour_fr in col_info:
        if sem != best_semaine or jour_fr is None:
            continue
        for _, row in df.iterrows():
            val = str(row[col]).strip()
            if val and val != "nan":
                client = str(row["Client"]).strip()
                machine = str(row["Machine"]).strip()
                planning[jour_fr].append((client, machine))

    return dict(planning), best_semaine


def load_all_plannings_from_folder(folder: str) -> tuple:
    folder_path = Path(folder)
    if not folder_path.is_absolute():
        folder_path = Path(__file__).resolve().parent / folder_path

    plannings = {}
    errors = {}
    if not folder_path.is_dir():
        return {}, {"erreur": f"Dossier introuvable : {folder_path}"}

    for csv_path in sorted(folder_path.glob("*.csv")):
        fname = csv_path.name
        if not fname.endswith(".csv"):
            continue
        employe = fname.replace(".csv", "").strip()
        try:
            with csv_path.open("rb") as f:
                planning, _ = parse_planning_file(f.read(), employe)
            plannings[employe] = planning
        except Exception as e:
            errors[employe] = str(e)
    return plannings, errors


def get_today_day_str(date=None) -> str:
    import datetime
    if date is None:
        date = datetime.date.today()
    return JOUR_MAP_WEEKDAY.get(date.weekday(), "Lundi")
