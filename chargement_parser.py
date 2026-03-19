"""
Module de parsing du fichier de chargement machine quotidien.
Format réel : CSV séparé par ';', encodage UTF-8 BOM, virgule comme décimale.
Colonnes : Tiers, Date début, Statut, Employé, Machine, Commentaire, Val. Ref, ...

Une salle est considérée FAITE si : statut in ('Fait', 'Annulé') ET Val. Ref != 0

Fonctionnalité "tournée décalée" :
  Si un réappro a des salles non faites sur le jour J MAIS a quand même des chargements
  dans le fichier, on cherche dans son planning quel autre jour correspond à ces machines.
  Ex : RIDF1 fait sa tournée du Lundi un Mardi → détecté et signalé.
"""

import pandas as pd
import io
from collections import defaultdict

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]

# Mapping souple des colonnes vers les noms internes
_COL_ALIASES = {
    "employe": ["employé", "employe", "technicien", "agent"],
    "statut":  ["statut", "status", "état", "etat"],
    "machine": ["machine", "équipement", "equipement"],
    "valeur":  ["val. ref", "val.ref", "valeur", "montant", "prix", "amount", "value"],
    "client":  ["tiers", "client", "salle", "site"],
}


def _detect_columns(columns: list) -> dict:
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
    errors = []
    df = None
    for sep in [";", ",", "\t"]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                _df = pd.read_csv(
                    io.BytesIO(file_bytes), sep=sep, dtype=str,
                    encoding=enc, on_bad_lines="skip"
                )
                if len(_df.columns) >= 4:
                    col_map = _detect_columns(list(_df.columns))
                    if all(k in col_map for k in ["employe", "statut", "machine", "valeur"]):
                        df = _df
                        break
            except Exception as e:
                errors.append(str(e))
        if df is not None:
            break

    if df is None:
        raise ValueError(
            f"Impossible de détecter le format du fichier de chargement.\n"
            f"Erreurs : {errors}"
        )

    df.columns = [c.strip() for c in df.columns]
    col_map = _detect_columns(list(df.columns))

    missing = [r for r in ["employe", "statut", "machine", "valeur"] if r not in col_map]
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans le fichier de chargement : {missing}.\n"
            f"Colonnes trouvées : {list(df.columns)}"
        )

    df = df.rename(columns={v: k for k, v in col_map.items()})
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
            "client":  row["client"] if "client" in df.columns else "",
            "statut":  statut,
            "is_fait": is_fait,
            "val_ref": valeur,
        }
        result[row["machine"]].append(entry)

    return dict(result)


def _machines_faites_par_reappro(chargement: dict, reappro: str) -> set:
    """
    Retourne l'ensemble des machines effectivement faites par ce reappro
    dans le fichier de chargement (peu importe le jour planifié).
    """
    machines = set()
    for machine, entries in chargement.items():
        for entry in entries:
            if entry["employe"] == reappro and entry["is_fait"]:
                machines.add(machine)
    return machines


def _detecter_tournee_decalee(
    reappro: str,
    planning_reappro: dict,
    jour_analyse: str,
    machines_faites_reappro: set,
) -> dict:
    """
    Pour un réappro qui a des salles non faites sur jour_analyse MAIS qui a
    quand même des chargements dans le fichier, on cherche dans son planning
    quel autre jour correspond le mieux aux machines qu'il a réellement faites.

    Retourne un dict ou {} si pas de tournée décalée détectée :
    {
        'jour_detecte': 'Lundi',
        'salles_decalees': [(client, machine), ...]   # salles du planning ce jour-là qui matchent
        'salles_non_matchees': [(client, machine), ...] # machines faites hors planning connu
    }
    """
    if not machines_faites_reappro:
        return {}

    best_jour = None
    best_matches = []
    best_score = 0

    for jour, salles in planning_reappro.items():
        if jour == jour_analyse:
            continue
        machines_ce_jour = {machine for (_, machine) in salles}
        matches = machines_faites_reappro & machines_ce_jour
        if len(matches) > best_score:
            best_score = len(matches)
            best_jour = jour
            best_matches = [(client, machine) for (client, machine) in salles if machine in matches]

    if best_score == 0:
        return {}

    # Machines faites qui ne correspondent à aucun jour du planning
    toutes_machines_planning = {
        machine
        for salles in planning_reappro.values()
        for (_, machine) in salles
    }
    salles_hors_planning = [
        m for m in machines_faites_reappro if m not in toutes_machines_planning
    ]

    return {
        "jour_detecte": best_jour,
        "salles_decalees": best_matches,
        "nb_machines_faites": len(machines_faites_reappro),
        "salles_hors_planning": salles_hors_planning,
    }


def croiser_planning_chargement(plannings: dict, chargement: dict, jour: str) -> dict:
    """
    Croise le planning du jour avec le chargement machine.

    Pour chaque réappro :
    1. Croise normalement son planning du jour J avec le chargement
    2. Si des salles sont non faites ET qu'il a quand même des chargements →
       détecte si c'est une tournée décalée (il a fait un autre jour de son planning)

    Retourne : { employe: {
        'salles_prevues', 'salles_faites', 'salles_non_faites',
        'tournee_decalee'  # dict ou None
    }}
    """
    results = {}

    for reappro, days in plannings.items():
        salles_prevues = days.get(jour, [])

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
                salles_faites.append({
                    "client": client,
                    "machine": machine,
                    "employe_reel": employe_reel,
                    "val_ref": val_reel,
                    "statut": statut_reel,
                    "is_joker": is_joker,
                })
            else:
                salles_non_faites.append({"client": client, "machine": machine})

        # ── Détection tournée décalée ──────────────────────────────────
        tournee_decalee = None
        if salles_non_faites:
            # Ce réappro a-t-il quand même fait des chargements aujourd'hui ?
            machines_faites_reappro = _machines_faites_par_reappro(chargement, reappro)
            if machines_faites_reappro:
                tournee_decalee = _detecter_tournee_decalee(
                    reappro, days, jour, machines_faites_reappro
                )

        results[reappro] = {
            "salles_prevues":   salles_prevues,
            "salles_faites":    salles_faites,
            "salles_non_faites": salles_non_faites,
            "tournee_decalee":  tournee_decalee if tournee_decalee else None,
        }

    return results
