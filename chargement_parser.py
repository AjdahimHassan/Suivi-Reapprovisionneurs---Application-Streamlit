"""
Module de parsing du fichier de chargement machine quotidien.
Format réel : CSV séparé par ';', encodage UTF-8 BOM, virgule comme décimale.
Colonnes : Tiers, Date début, Statut, Employé, Machine, Commentaire, Val. Ref, ...

Une salle est considérée FAITE si : statut in ('Fait', 'Annulé') ET Val. Ref != 0
"""

import pandas as pd
import io
from collections import defaultdict


# Mapping souple des colonnes vers les noms internes
_COL_ALIASES = {
    "employe":  ["employé", "employe", "technicien", "agent"],
    "statut":   ["statut", "status", "état", "etat"],
    "machine":  ["machine", "équipement", "equipement"],
    "valeur":   ["val. ref", "val.ref", "valeur", "montant", "prix", "amount", "value"],
    "client":   ["tiers", "client", "salle", "site"],
}


def _detect_columns(columns: list) -> dict:
    """Retourne un dict {nom_interne: nom_colonne_réel}."""
    col_map = {}
    for col in columns:
        cl = col.lower().strip()
        for internal, aliases in _COL_ALIASES.items():
            if internal not in col_map and any(a in cl for a in aliases):
                col_map[internal] = col
    return col_map


def parse_chargement_csv(file_bytes: bytes) -> dict:
    """
    Parse le fichier de chargement machine du jour.
    Retourne un dict : { machine_id: [{'employe', 'client', 'is_fait', 'val_ref', 'statut'}] }
    """
    # Essai 1 : format réel (sep=';', utf-8-sig)
    errors = []
    for sep in [";", ",", "\t"]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(file_bytes), sep=sep, dtype=str,
                    encoding=enc, on_bad_lines="skip"
                )
                if len(df.columns) >= 4:
                    col_map = _detect_columns(list(df.columns))
                    if all(k in col_map for k in ["employe", "statut", "machine", "valeur"]):
                        break  # trouvé
            except Exception as e:
                errors.append(str(e))
        else:
            continue
        break
    else:
        raise ValueError(
            f"Impossible de détecter le format du fichier de chargement.\n"
            f"Colonnes trouvées : {list(df.columns)}\n"
            f"Erreurs : {errors}"
        )

    df.columns = [c.strip() for c in df.columns]
    col_map = _detect_columns(list(df.columns))

    required = ["employe", "statut", "machine", "valeur"]
    missing = [r for r in required if r not in col_map]
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans le fichier de chargement : {missing}.\n"
            f"Colonnes trouvées : {list(df.columns)}"
        )

    # Renommer vers noms internes
    df = df.rename(columns={v: k for k, v in col_map.items()})

    # Garder aussi 'client' si disponible
    keep = ["employe", "statut", "machine", "valeur"]
    if "client" in col_map:
        keep.append("client")

    df = df[keep].copy()
    df = df.dropna(subset=["machine"])
    df["employe"] = df["employe"].astype(str).str.strip()
    df["statut"]  = df["statut"].astype(str).str.strip().str.capitalize()
    df["machine"] = df["machine"].astype(str).str.strip()
    if "client" in df.columns:
        df["client"] = df["client"].astype(str).str.strip()

    def parse_val(v):
        try:
            return float(str(v).replace(",", ".").replace(" ", "").replace("\xa0", ""))
        except Exception:
            return 0.0

    df["valeur"] = df["valeur"].apply(parse_val)

    result = defaultdict(list)
    for _, row in df.iterrows():
        statut = row["statut"]
        valeur = row["valeur"]
        is_fait = statut in ("Fait", "Annulé") and valeur != 0.0
        entry = {
            "employe": row["employe"],
            "client":  row.get("client", "") if "client" in df.columns else "",
            "statut":  statut,
            "is_fait": is_fait,
            "val_ref": valeur,
        }
        result[row["machine"]].append(entry)

    return dict(result)


def croiser_planning_chargement(plannings: dict, chargement: dict, jour: str) -> dict:
    """
    Croise le planning du jour avec le chargement machine.
    
    plannings : { employe: { jour: [(client, machine), ...] } }
    chargement : { machine: [{'employe', 'is_fait', 'val_ref', 'statut'}] }
    jour : str ('Lundi', 'Mardi', ...)
    
    Retourne : { employe: { 'salles_prevues', 'salles_faites', 'salles_non_faites' } }
    """
    results = {}

    for reappro, days in plannings.items():
        salles_prevues = days.get(jour, [])
        if not salles_prevues:
            results[reappro] = {
                "salles_prevues": [],
                "salles_faites": [],
                "salles_non_faites": [],
            }
            continue

        salles_faites = []
        salles_non_faites = []

        for client, machine in salles_prevues:
            fait = False
            employe_reel = ""
            val_reel = 0.0
            statut_reel = ""
            is_joker = False

            if machine in chargement:
                for entry in chargement[machine]:
                    if entry["is_fait"]:
                        fait = True
                        employe_reel = entry["employe"]
                        val_reel = entry["val_ref"]
                        statut_reel = entry["statut"]
                        if employe_reel != reappro:
                            is_joker = True
                        break

            if fait:
                salles_faites.append(
                    {
                        "client": client,
                        "machine": machine,
                        "employe_reel": employe_reel,
                        "val_ref": val_reel,
                        "statut": statut_reel,
                        "is_joker": is_joker,
                    }
                )
            else:
                salles_non_faites.append({"client": client, "machine": machine})

        results[reappro] = {
            "salles_prevues": salles_prevues,
            "salles_faites": salles_faites,
            "salles_non_faites": salles_non_faites,
        }

    return results
