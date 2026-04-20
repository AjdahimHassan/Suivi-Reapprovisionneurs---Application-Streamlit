"""
Page QUARTIX — Visualisation des trajets réappros
  • Import Excel QUARTIX (format multi-feuilles)
  • Onglet 1 — Carte & Trajets : sélecteur véhicule + journée, carte Folium,
    KPIs distance/dépôt, stats multi-véhicules, cache admin
  • Onglet 2 — Analyse Passages Dépôt : par réappro, tableau matin/après-midi
    avec heure d'arrivée et durée au dépôt (tolérance 1 km)
"""

import re
import numpy as np
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import io as _io

from mongo_storage import (
    load_quartix_vehicle,
    load_all_quartix_vehicles,
    upsert_quartix_vehicle,
    load_plannings_from_mongo,
    load_geocode_cache,
    save_geocode_entry,
    load_routes_cache,
    save_route_entry,
    clear_geocode_cache,
    clear_routes_cache,
)

# ── Constantes ────────────────────────────────────────────────────────────────

import requests as _requests
DEPOT_RADIUS_M = 1000   # rayon autour du dépôt pour détecter un passage (1 km)
MIN_STOP_MIN   = 5      # durée minimale d'arrêt pour compter comme un passage (min)
BEFORE_WORK_H  = 11     # heure limite "avant tournée" — départ doit être < 11h
FIRST_N_TRIPS  = 5      # on cherche le passage dépôt parmi les N premiers trajets
LAST_N_TRIPS   = 5      # on cherche le passage dépôt parmi les N derniers trajets (hors dernier)

COLS = [
    "Trajet", "Conducteur", "Départ", "Lieu de départ", "Lieu d'arrivée",
    "Arrivée", "Durée du sous-trajet", "Durée du trajet", "Arrêt moteur en marche",
    "Kilométrage professionnel", "Kilométrage privé", "Distance totale", "Vitesse moy.",
]

# Palette Distriprot
C_BLUE_DARK  = "#1B3D6F"
C_BLUE_LIGHT = "#7BC4E8"
C_ORANGE     = "#E8922A"
C_GREEN      = "#1E7E34"
C_RED        = "#C0392B"
C_PURPLE     = "#9B59B6"


# ── Géocodage — API adresse.data.gouv.fr ─────────────────────────────────────

_GEOCODE_FR_URL       = "https://api-adresse.data.gouv.fr/search/"
_GEOCODE_FR_BATCH_URL = "https://api-adresse.data.gouv.fr/search/csv/"


def _prep_addr_for_api(addr: str) -> str:
    """Supprime le suffixe ', France' superflu pour l'API française."""
    return re.sub(r",?\s*France\s*$", "", addr, flags=re.IGNORECASE).strip()


_GEOCODE_MIN_SCORE = 0.5  # valeur par défaut — modifiable via le slider dans l'UI


def _get_score_threshold() -> float:
    """Lit le seuil depuis le session_state si le slider a été affiché, sinon valeur par défaut."""
    import streamlit as _st
    return float(_st.session_state.get("q_score_threshold", _GEOCODE_MIN_SCORE))


def _geocode_single_fr(addr: str) -> tuple | None:
    """Géocode une adresse via api-adresse.data.gouv.fr. Retourne (lat, lon) ou None."""
    clean = _prep_addr_for_api(addr)
    try:
        resp = _requests.get(
            _GEOCODE_FR_URL,
            params={"q": clean, "limit": 1, "type": "housenumber,street"},
            timeout=8,
        )
        features = resp.json().get("features", [])
        if features and features[0]["properties"].get("score", 0) >= _get_score_threshold():
            lon, lat = features[0]["geometry"]["coordinates"]
            return (float(lat), float(lon))
    except Exception:
        pass
    return None


# ── Expansion des abréviations françaises (utilisée pour la correction UI) ────

_ADDR_ABBREVS = [
    (re.compile(r'\bAv\.\s*'),   'Avenue '),
    (re.compile(r'\bBd\.?\s*'),  'Boulevard '),
    (re.compile(r'\bTrav\.\s*'), 'Traverse '),
    (re.compile(r'\bPl\.\s*'),   'Place '),
    (re.compile(r'\bImp\.\s*'),  'Impasse '),
    (re.compile(r'\bCrs\.\s*'),  'Cours '),
    (re.compile(r'\bAll\.\s*'),  'Allée '),
    (re.compile(r'\bRte\.\s*'),  'Route '),
    (re.compile(r'\bl([A-ZÉÀÂÊÎÙÛ])'), r"l'\1"),
    (re.compile(r'\bChe\.\s*'),  'Chemin '),
    (re.compile(r'\bSt\.\s*'),   'Saint '),
    (re.compile(r'\bSte\.\s*'),  'Sainte '),
    (re.compile(r'\bVla\.\s*'),  'Villa '),
    (re.compile(r'\bSq\.\s*'),   'Square '),
]


def _expand_address(addr: str) -> str:
    for pattern, replacement in _ADDR_ABBREVS:
        addr = pattern.sub(replacement, addr)
    return addr.strip()


_ARRET_MOTEUR_RE = re.compile(
    r"(?:Véhicule\s+à\s+l.arrêt[^,]*,\s*moteur\s+en\s+marche\s*)+",
    re.IGNORECASE,
)


def _clean_addr(addr: str) -> str:
    cleaned = _ARRET_MOTEUR_RE.sub("", addr).strip()
    return cleaned if cleaned else addr.strip()


# ── Géocodage ────────────────────────────────────────────────────────────────

def _get_osrm_route(coord_a: tuple, coord_b: tuple, routes_cache: dict) -> list:
    key = (tuple(coord_a), tuple(coord_b))
    if key in routes_cache:
        return routes_cache[key]
    try:
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{coord_a[1]},{coord_a[0]};{coord_b[1]},{coord_b[0]}"
            f"?overview=full&geometries=geojson"
        )
        resp = _requests.get(url, timeout=5)
        data = resp.json()
        if data.get("code") == "Ok":
            raw   = data["routes"][0]["geometry"]["coordinates"]
            route = [[c[1], c[0]] for c in raw]
            routes_cache[key] = route
            save_route_entry(coord_a, coord_b, route)
            return route
    except Exception:
        pass
    route = [list(coord_a), list(coord_b)]
    routes_cache[key] = route
    save_route_entry(coord_a, coord_b, route)
    return route


def _geocode_all(addresses: list[str], cache: dict) -> dict:
    """Géocode les adresses manquantes via api-adresse.data.gouv.fr (appel batch)."""
    missing = [a for a in addresses if a and str(a).strip() and a not in cache]
    if not missing:
        return cache

    _postcode_re = re.compile(r'\b(\d{5})\b')

    def _split_addr(raw: str):
        clean = _prep_addr_for_api(raw)
        m = _postcode_re.search(clean)
        return clean, (m.group(1) if m else "")

    bar = st.progress(0, text=f"Géocodage de {len(missing)} adresse(s)…")
    try:
        splits   = [_split_addr(a) for a in missing]
        df_req   = pd.DataFrame({"adresse": [s[0] for s in splits],
                                  "postcode": [s[1] for s in splits]})
        csv_bytes = df_req.to_csv(index=False).encode("utf-8")

        resp = _requests.post(
            _GEOCODE_FR_BATCH_URL,
            files={"data": ("addr.csv", csv_bytes, "text/csv")},
            data={"columns": "adresse", "postcode": "postcode",
                  "result_type": "housenumber,street"},
            timeout=60,
        )
        resp.raise_for_status()

        df_res = pd.read_csv(_io.StringIO(resp.text))

        for i, orig in enumerate(missing):
            row   = df_res.iloc[i] if i < len(df_res) else None
            lat   = row.get("latitude")     if row is not None else None
            lon   = row.get("longitude")    if row is not None else None
            score = row.get("result_score", 0) if row is not None else 0
            score = score or 0

            if lat is not None and lon is not None and not pd.isna(lat) and not pd.isna(lon) and float(score) >= _get_score_threshold():
                coords: tuple | None = (float(lat), float(lon))
            else:
                coords = None

            cache[orig] = coords
            save_geocode_entry(orig, coords)
            bar.progress((i + 1) / len(missing))

    except Exception:
        # Fallback : un par un si le batch échoue
        for i, addr in enumerate(missing):
            coords = _geocode_single_fr(addr)
            cache[addr] = coords
            if coords:
                save_geocode_entry(addr, coords)
            bar.progress((i + 1) / len(missing))

    bar.empty()
    return cache


# ── Helpers analytiques ───────────────────────────────────────────────────────

def _parse_min(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, float) and np.isnan(val):
        return 0.0
    if hasattr(val, "total_seconds"):
        return val.total_seconds() / 60
    s = str(val).strip()
    if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s):
        parts = s.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    h = re.search(r"(\d+)\s*[hH]", s)
    m = re.search(r"(\d+)\s*[mM]in", s)
    total = 0.0
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    return total


def _to_km(val) -> float:
    try:
        return float(str(val).replace(",", ".").replace(" ", "").replace("km", ""))
    except Exception:
        return 0.0


def _auto_detect_depot(df_all: pd.DataFrame) -> str | None:
    all_deps = df_all["Lieu de départ"].dropna().astype(str)
    if all_deps.empty:
        return None
    return all_deps.value_counts().idxmax()


def _stop_duration_at(grp: pd.DataFrame, i: int) -> float:
    if i <= 0:
        return 0.0
    prev_arr = grp.loc[i - 1, "_arr"]
    this_dep = grp.loc[i, "_dep"]
    if pd.notna(prev_arr) and pd.notna(this_dep):
        return max(0.0, (this_dep - prev_arr).total_seconds() / 60)
    return 0.0


def _check_depot_visit_day(
    grp: pd.DataFrame,
    cache: dict,
    depot_coords,
) -> tuple[bool, bool]:
    if depot_coords is None or grp.empty:
        return False, False

    grp = grp.sort_values("_dep").reset_index(drop=True)
    n   = len(grp)

    before_tour = False
    after_tour  = False

    def _near_depot(addr: str) -> bool:
        coords = cache.get(addr)
        return bool(coords and geodesic(coords, depot_coords).meters <= DEPOT_RADIUS_M)

    def _stop_after_arrival(i: int) -> float:
        if i + 1 >= n:
            return 0.0
        arr = grp.loc[i, "_arr"]
        nxt = grp.loc[i + 1, "_dep"]
        if pd.notna(arr) and pd.notna(nxt):
            return max(0.0, (nxt - arr).total_seconds() / 60)
        return 0.0

    for i in range(min(FIRST_N_TRIPS, n)):
        row = grp.loc[i]
        if row["_dep"].hour < BEFORE_WORK_H:
            if _near_depot(str(row["Lieu de départ"])) and _stop_duration_at(grp, i) >= MIN_STOP_MIN:
                before_tour = True
                break
        if pd.notna(row["_arr"]) and row["_arr"].hour < BEFORE_WORK_H:
            if _near_depot(str(row["Lieu d'arrivée"])) and _stop_after_arrival(i) >= MIN_STOP_MIN:
                before_tour = True
                break

    if n >= 2:
        start = max(0, n - LAST_N_TRIPS)
        for i in range(start, n - 1):
            row = grp.loc[i]
            if _near_depot(str(row["Lieu de départ"])) and _stop_duration_at(grp, i) >= MIN_STOP_MIN:
                after_tour = True
                break
            if _near_depot(str(row["Lieu d'arrivée"])) and _stop_after_arrival(i) >= MIN_STOP_MIN:
                after_tour = True
                break

    return before_tour, after_tour


def _count_depot_visits(
    df_vehicle: pd.DataFrame,
    cache: dict,
    depot_coords,
) -> tuple[int, int]:
    if depot_coords is None or df_vehicle.empty:
        return 0, 0
    before_count = 0
    after_count  = 0
    for _, grp in df_vehicle.groupby(df_vehicle["_dep"].dt.date):
        b, a = _check_depot_visit_day(grp, cache, depot_coords)
        if b:
            before_count += 1
        if a:
            after_count  += 1
    return before_count, after_count


# ── Style carte ───────────────────────────────────────────────────────────────

def _stop_style(minutes: float, is_first: bool, is_last: bool) -> tuple[str, int]:
    if is_first:
        return C_GREEN, 11
    if is_last:
        return C_RED, 11
    if minutes < 2:
        return C_BLUE_LIGHT, 5
    if minutes < 15:
        return C_BLUE_DARK, 8
    if minutes < 45:
        return C_ORANGE, 12
    return C_PURPLE, 17


# ── Nouveau : parse feuille résumé ────────────────────────────────────────────

def _parse_vehicle_names(xls: pd.ExcelFile) -> dict[str, str]:
    """Tente de lire la feuille résumé pour construire {plate: full_name}."""
    try:
        df_recap = xls.parse(xls.sheet_names[0], header=None)
        vehicle_sheets = xls.sheet_names[1:]
        name_map: dict[str, str] = {}
        for _, row in df_recap.iterrows():
            cells = [str(c).strip() for c in row if pd.notna(c) and str(c).strip()]
            for plate in vehicle_sheets:
                if plate in cells:
                    candidates = [c for c in cells if c != plate and len(c) > len(plate)]
                    if candidates:
                        name_map[plate] = max(candidates, key=len)
                    break
        return name_map
    except Exception:
        return {}


# ── Nouveau : détection passages dépôt ───────────────────────────────────────

def _near_depot(addr: str, cache: dict, depot_coords: tuple) -> bool:
    coords = cache.get(addr)
    return bool(coords and geodesic(coords, depot_coords).meters <= DEPOT_RADIUS_M)


def _find_depot_passages(
    df_vehicle: pd.DataFrame,
    cache: dict,
    depot_coords: tuple,
) -> list[dict]:
    """
    Retourne la liste de tous les passages détectés au dépôt sur l'ensemble
    du fichier, triés par date/heure.
    Chaque passage : {date, period, arrive_time, depart_time, duration_min, address}
    """
    passages: list[dict] = []

    for date, grp in df_vehicle.groupby(df_vehicle["_dep"].dt.date):
        grp = grp.sort_values("_dep").reset_index(drop=True)
        n = len(grp)

        for i in range(n):
            row      = grp.iloc[i]
            dep_addr = str(row["Lieu de départ"])
            arr_addr = str(row["Lieu d'arrivée"])

            # Cas A — arrivée au dépôt
            if _near_depot(arr_addr, cache, depot_coords):
                arrive_time = row["_arr"]
                if pd.isna(arrive_time):
                    continue
                next_row    = grp.iloc[i + 1] if i < n - 1 else None
                depart_time = next_row["_dep"] if next_row is not None and pd.notna(next_row["_dep"]) else None
                duration_min = (
                    max(0.0, (depart_time - arrive_time).total_seconds() / 60)
                    if depart_time is not None
                    else 0.0
                )
                period = "matin" if arrive_time.hour < 12 else "après-midi"
                # i+1 = nombre de trajets effectués pour arriver au dépôt (inclut le trajet courant)
                # n-1-i = nombre de trajets effectués après avoir quitté le dépôt
                passages.append({
                    "date":          date,
                    "period":        period,
                    "arrive_time":   arrive_time,
                    "depart_time":   depart_time,
                    "duration_min":  duration_min,
                    "address":       arr_addr,
                    "trips_before":  i + 1,
                    "trips_after":   max(0, n - 1 - i),
                })

            # Cas B — départ depuis le dépôt (sans Cas A déjà couvert)
            elif _near_depot(dep_addr, cache, depot_coords):
                depart_time = row["_dep"]
                if pd.isna(depart_time):
                    continue
                if i == 0:
                    # Premier trajet du jour : le véhicule était garé au dépôt depuis la veille
                    # On ne connaît pas l'heure d'arrivée → on utilise l'heure de départ comme référence
                    arrive_time  = depart_time
                    duration_min = 0.0  # durée inconnue (nuit précédente)
                else:
                    prev_arr = grp.iloc[i - 1]["_arr"]
                    if pd.isna(prev_arr):
                        continue
                    arrive_time  = prev_arr
                    duration_min = max(0.0, (depart_time - prev_arr).total_seconds() / 60)
                    if duration_min < MIN_STOP_MIN:
                        continue
                period = "matin" if arrive_time.hour < 12 else "après-midi"
                # i = trajets effectués avant de repasser au dépôt (0..i-1)
                # n-i = trajets effectués après le départ du dépôt (i..n-1, inclut ce trajet)
                passages.append({
                    "date":          date,
                    "period":        period,
                    "arrive_time":   arrive_time,
                    "depart_time":   depart_time,
                    "duration_min":  duration_min,
                    "address":       dep_addr,
                    "trips_before":  i,
                    "trips_after":   n - i,
                })

    # Déduplication sur (date, arrive_time) — garder la durée la plus longue
    seen: dict[tuple, int] = {}
    for idx, p in enumerate(passages):
        key = (p["date"], p["arrive_time"])
        if key not in seen or p["duration_min"] > passages[seen[key]]["duration_min"]:
            seen[key] = idx
    passages = [passages[i] for i in sorted(seen.values())]

    return sorted(passages, key=lambda p: (p["date"], p["arrive_time"]))


# ── Onglet 1 : Carte & Trajets (code existant) ────────────────────────────────

def _render_tab_carte() -> None:

    # ── Upload ────────────────────────────────────────────
    col_up, _ = st.columns([2, 3])
    with col_up:
        uploaded = st.file_uploader(
            "📂 Importer un export Excel QUARTIX",
            type=["xls", "xlsx"],
            key="quartix_uploader",
        )

    if not uploaded:
        st.markdown(
            f"<div style='background:#f0f4fa;border-left:5px solid {C_BLUE_DARK};"
            f"padding:16px 20px;border-radius:8px;margin-top:20px'>"
            f"<b style='color:{C_BLUE_DARK}'>👆 Importez un fichier Excel QUARTIX</b>"
            f"<p style='margin:6px 0 0;color:#555;font-size:14px'>"
            f"Le fichier doit contenir une feuille résumé + une feuille par véhicule "
            f"(format standard QUARTIX, extension <code>.xls</code> ou <code>.xlsx</code>)."
            f"</p></div>",
            unsafe_allow_html=True,
        )
        return

    try:
        xls = pd.ExcelFile(uploaded)
    except Exception as e:
        st.error(f"Impossible de lire le fichier : {e}")
        return

    sheets = xls.sheet_names
    if len(sheets) <= 1:
        st.error("Fichier invalide : au moins 2 feuilles attendues (résumé + 1 feuille par véhicule).")
        return

    vehicle_sheets = sheets[1:]
    name_map       = _parse_vehicle_names(xls)

    # ── 3. Sélecteurs véhicule + journée ──────────────────
    col_v, col_d, _ = st.columns([2, 2, 1])
    with col_v:
        selected_vehicle = st.selectbox("🚗 Véhicule (plaque)", vehicle_sheets, key="q_vehicle")

    try:
        df_raw = pd.read_excel(xls, sheet_name=selected_vehicle, header=4, usecols="B:N")
        df_raw.columns = COLS
    except Exception as e:
        st.error(f"Erreur lecture feuille «{selected_vehicle}» : {e}")
        return

    df_raw["_dep"] = pd.to_datetime(df_raw["Départ"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True),  errors="coerce")
    df_raw["_arr"] = pd.to_datetime(df_raw["Arrivée"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True), errors="coerce")
    df_raw = df_raw.dropna(subset=["_dep"]).sort_values("_dep").reset_index(drop=True)

    for _col in ["Lieu de départ", "Lieu d'arrivée"]:
        df_raw[_col] = df_raw[_col].astype(str).map(_clean_addr)

    if df_raw.empty:
        st.warning("Aucune donnée valide dans cette feuille.")
        return

    available_days = sorted(df_raw["_dep"].dt.date.unique(), reverse=True)
    day_fmts = [d.strftime("%d/%m/%Y") for d in available_days]

    day_idx_key = f"q_day_idx_{selected_vehicle}"
    if day_idx_key not in st.session_state:
        st.session_state[day_idx_key] = 0

    with col_d:
        sel_day_fmt = st.selectbox(
            "📅 Journée",
            day_fmts,
            index=st.session_state[day_idx_key],
            key="q_day",
        )
        st.session_state[day_idx_key] = day_fmts.index(sel_day_fmt)

    selected_day = next(d for d in available_days if d.strftime("%d/%m/%Y") == sel_day_fmt)

    # ── 4. Panel véhicule : employé + dépôt ──────────────
    st.divider()

    vehicle_doc = load_quartix_vehicle(selected_vehicle)
    try:
        plannings, _ = load_plannings_from_mongo()
        employee_options = sorted(plannings.keys())
    except Exception:
        employee_options = []

    db_depot_address = vehicle_doc.get("depot_address", "") if vehicle_doc else ""
    db_depot_coords  = vehicle_doc.get("depot_coords",  None) if vehicle_doc else None
    db_employe       = vehicle_doc.get("employe",        "") if vehicle_doc else ""
    is_approximated  = False

    if not db_depot_address:
        approx = _auto_detect_depot(df_raw)
        display_depot = approx or "— Non défini —"
        is_approximated = bool(approx)
    else:
        display_depot = db_depot_address

    edit_key = f"edit_depot_{selected_vehicle}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False

    with st.container():
        st.markdown("#### 🚗 Informations véhicule")

        col_emp, col_dep, col_btn = st.columns([2, 4, 1])

        with col_emp:
            emp_idx = 0
            if db_employe and db_employe in employee_options:
                emp_idx = employee_options.index(db_employe) + 1
            selected_employee = st.selectbox(
                "👤 Employé",
                [""] + employee_options,
                index=emp_idx,
                key="q_employee",
            )

        with col_dep:
            if st.session_state[edit_key]:
                new_depot_input = st.text_input(
                    "📍 Adresse dépôt (modifiable)",
                    value=db_depot_address if db_depot_address else display_depot,
                    placeholder="Ex : 3 Rue des Abattoirs, 38120 Saint-Égrève",
                    key="q_depot_input",
                )
            else:
                badge = " 🔸 *approximé*" if is_approximated else ""
                st.markdown(f"**📍 Dépôt :**&nbsp; {display_depot}{badge}")

        with col_btn:
            st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
            if not st.session_state[edit_key]:
                if st.button("✏️", key="q_btn_edit", help="Modifier les infos"):
                    st.session_state[edit_key] = True
                    st.rerun()
            else:
                if st.button("✏️ Annuler", key="q_btn_cancel"):
                    st.session_state[edit_key] = False
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state[edit_key]:
            col_save, _ = st.columns([2, 5])
            with col_save:
                if st.button("💾 Sauvegarder", type="primary", key="q_btn_save", use_container_width=True):
                    addr_to_save = st.session_state.get("q_depot_input", "").strip()
                    emp_to_save  = st.session_state.get("q_employee", "").strip()

                    if not addr_to_save:
                        st.warning("Veuillez saisir une adresse de dépôt.")
                    else:
                        with st.spinner("Géocodage de l'adresse…"):
                            tmp_cache = load_geocode_cache()
                            tmp_cache = _geocode_all([addr_to_save], tmp_cache)
                            coords = tmp_cache.get(addr_to_save)

                        if not coords:
                            st.error("❌ Adresse introuvable. Vérifiez l'orthographe et réessayez.")
                        else:
                            try:
                                upsert_quartix_vehicle(
                                    plate=selected_vehicle,
                                    employe=emp_to_save,
                                    depot_address=addr_to_save,
                                    depot_coords=list(coords),
                                )
                                st.success(f"✅ Sauvegardé : {addr_to_save}")
                                st.session_state[edit_key] = False
                                db_depot_address = addr_to_save
                                db_depot_coords  = list(coords)
                                db_employe       = emp_to_save
                                is_approximated  = False
                            except Exception as e:
                                st.error(f"❌ Erreur MongoDB : {e}")
                            st.rerun()

    depot_coords = db_depot_coords

    # ── 5. Filtrage journée + géocodage ───────────────────
    df = df_raw[df_raw["_dep"].dt.date == selected_day].copy().reset_index(drop=True)
    if df.empty:
        st.warning("Aucun trajet pour ce jour.")
        return

    addrs: set[str] = set()
    for c in ["Lieu de départ", "Lieu d'arrivée"]:
        addrs.update(df[c].dropna().astype(str).unique())

    cache = load_geocode_cache()
    cache = _geocode_all(list(addrs), cache)

    # ── 6. Construction des arrêts ordonnés ───────────────
    n = len(df)
    stops = []
    prev_arr_addr = None

    for i in range(n):
        row      = df.iloc[i]
        dep_addr = str(row["Lieu de départ"])
        arr_addr = str(row["Lieu d'arrivée"])
        next_row = df.iloc[i + 1] if i < n - 1 else None

        if dep_addr != prev_arr_addr:
            stops.append({
                "addr":     dep_addr,
                "coords":   cache.get(dep_addr),
                "time":     row["_dep"],
                "stop_min": 0.0,
                "trip_dur": row.get("Durée du sous-trajet"),
                "dist":     row.get("Distance totale"),
                "is_first": (len(stops) == 0),
                "is_last":  False,
            })

        stop_min = 0.0
        if next_row is not None and pd.notna(row["_arr"]) and pd.notna(next_row["_dep"]):
            stop_min = max(0.0, (next_row["_dep"] - row["_arr"]).total_seconds() / 60)

        stops.append({
            "addr":     arr_addr,
            "coords":   cache.get(arr_addr),
            "time":     row["_arr"],
            "stop_min": stop_min,
            "trip_dur": next_row.get("Durée du sous-trajet") if next_row is not None else None,
            "dist":     next_row.get("Distance totale")       if next_row is not None else None,
            "is_first": False,
            "is_last":  (i == n - 1),
        })

        prev_arr_addr = arr_addr

    valid = [s for s in stops if s["coords"]]
    if len(valid) < 2:
        st.error(
            "Pas assez d'adresses géocodées pour tracer le trajet. "
            "Corrigez les adresses ci-dessous pour débloquer la carte."
        )
        all_stop_addrs = list(dict.fromkeys(s["addr"] for s in stops))
        missing_addrs  = [a for a in all_stop_addrs if not cache.get(a)]
        if missing_addrs:
            st.markdown(
                f"<div style='background:#fff3cd;border-left:4px solid {C_ORANGE};"
                f"padding:10px 14px;border-radius:6px;margin-bottom:8px'>"
                f"<b>⚠️ {len(missing_addrs)} adresse(s) non reconnue(s)</b></div>",
                unsafe_allow_html=True,
            )
            for orig_addr in missing_addrs:
                fix_key = f"q_addr_fix_{hash(orig_addr)}"
                if fix_key not in st.session_state:
                    st.session_state[fix_key] = _expand_address(orig_addr)
                col_addr, col_btn = st.columns([5, 1])
                with col_addr:
                    st.text_input(f"❌ {orig_addr}", key=fix_key, label_visibility="visible")
                with col_btn:
                    st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
                    if st.button("Valider", key=f"q_btn_fix_{hash(orig_addr)}", use_container_width=True):
                        corrected = st.session_state[fix_key].strip()
                        if corrected:
                            with st.spinner(f"Géocodage de « {corrected} »…"):
                                coords = _geocode_single_fr(corrected)
                            if coords:
                                save_geocode_entry(orig_addr, coords)
                                if corrected != orig_addr:
                                    save_geocode_entry(corrected, coords)
                                st.success(f"✅ {corrected}")
                                st.rerun()
                            else:
                                st.error("Introuvable. Essayez une autre formulation.")
                    st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── 7. KPIs ───────────────────────────────────────────
    lats = [s["coords"][0] for s in valid]
    lons = [s["coords"][1] for s in valid]
    total_km   = sum(_to_km(s["dist"]) for s in stops if s["dist"])
    nb_stops   = sum(1 for s in stops if not s["is_first"] and not s["is_last"] and s["stop_min"] >= 2)
    long_stops = sum(1 for s in stops if not s["is_first"] and not s["is_last"] and s["stop_min"] >= 20)

    before_ok, after_ok = _check_depot_visit_day(df, cache, depot_coords)

    st.divider()
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🚗 Trajets",          len(df))
    c2.metric("📍 Arrêts ≥ 2 min",   nb_stops)
    c3.metric("⏸️ Pauses ≥ 20 min", long_stops)
    c4.metric("📏 Distance totale",  f"{total_km:.0f} km" if total_km > 0 else "—")
    c5.metric(
        "🏠 Passage avant tournée",
        "✅ OK" if before_ok else ("❌ Pas OK" if depot_coords else "—"),
        help=f"Passage au dépôt parmi les {FIRST_N_TRIPS} premiers trajets, avant {BEFORE_WORK_H}h, arrêt ≥ {MIN_STOP_MIN}min"
             if depot_coords else "Dépôt non configuré — renseignez l'adresse ci-dessus",
    )
    c6.metric(
        "🏠 Passage après tournée",
        "✅ OK" if after_ok else ("❌ Pas OK" if depot_coords else "—"),
        help=f"Passage au dépôt parmi les {LAST_N_TRIPS} derniers trajets (hors dernier), arrêt ≥ {MIN_STOP_MIN}min"
             if depot_coords else "Dépôt non configuré — renseignez l'adresse ci-dessus",
    )

    # ── Navigation journée ◀ / ▶ ──────────────────────────
    nav_left, nav_mid, nav_right = st.columns([1, 6, 1])
    with nav_left:
        if st.button("◀ Jour préc.", key="q_day_prev", use_container_width=True,
                     disabled=st.session_state[day_idx_key] >= len(available_days) - 1):
            st.session_state[day_idx_key] += 1
            st.rerun()
    with nav_mid:
        st.markdown(
            f"<p style='text-align:center;color:#888;margin:0;padding-top:6px'>"
            f"{sel_day_fmt} — {st.session_state[day_idx_key] + 1} / {len(available_days)}</p>",
            unsafe_allow_html=True,
        )
    with nav_right:
        if st.button("Jour suiv. ▶", key="q_day_next", use_container_width=True,
                     disabled=st.session_state[day_idx_key] <= 0):
            st.session_state[day_idx_key] -= 1
            st.rerun()

    st.divider()

    # ── 8. Carte Folium ───────────────────────────────────
    center = [np.mean(lats), np.mean(lons)]
    m = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")

    if depot_coords:
        folium.Circle(
            location=list(depot_coords),
            radius=DEPOT_RADIUS_M,
            color=C_ORANGE,
            fill=True,
            fill_color=C_ORANGE,
            fill_opacity=0.06,
            weight=2,
            dash_array="6",
            tooltip=f"Zone dépôt — rayon {DEPOT_RADIUS_M}m",
        ).add_to(m)

    routes_cache = load_routes_cache()
    osrm_bar = st.empty()
    new_routes = sum(
        1 for i in range(len(valid) - 1)
        if (tuple(valid[i]["coords"]), tuple(valid[i+1]["coords"])) not in routes_cache
    )
    if new_routes:
        osrm_bar.info(f"🗺️ Calcul des routes ({new_routes} segment(s))…")
    for i in range(len(valid) - 1):
        seg = _get_osrm_route(valid[i]["coords"], valid[i + 1]["coords"], routes_cache)
        folium.PolyLine(seg, color=C_BLUE_DARK, weight=3, opacity=0.75).add_to(m)
    osrm_bar.empty()

    for num_label, s in enumerate(valid, start=1):
        color, radius = _stop_style(s["stop_min"], s["is_first"], s["is_last"])
        time_str = s["time"].strftime("%H:%M") if pd.notna(s["time"]) else "?"
        dur_str  = f"{int(s['stop_min'])}min" if s["stop_min"] >= 1 else ""
        trip_min = _parse_min(s["trip_dur"])

        label_first = "🚀 Départ" if s["is_first"] else ""
        label_last  = "🏁 Arrivée finale" if s["is_last"] else ""

        dist_depot_str = ""
        if depot_coords and s["coords"]:
            dm = geodesic(s["coords"], depot_coords).meters
            dist_depot_str = f"<br>🏠 Distance dépôt : <b>{dm:.0f} m</b>"

        popup_html = f"""
        <div style="font-family:sans-serif;font-size:13px;min-width:200px;max-width:300px;">
            {"<b style='color:" + C_GREEN + "'>" + label_first + "</b><br>" if label_first else ""}
            {"<b style='color:" + C_RED   + "'>" + label_last  + "</b><br>" if label_last  else ""}
            <b style="color:{C_BLUE_DARK}">#{num_label} — {s['addr']}</b>
            <hr style="margin:4px 0">
            🕐 <b>{time_str}</b>
            {"<br>⏸️ Arrêt : <b>" + dur_str + "</b>" if dur_str else ""}
            {"<br>🚗 Trajet suivant : " + str(int(trip_min)) + " min" if trip_min > 0 else ""}
            {"<br>📏 " + str(s['dist']) + " km" if s['dist'] else ""}
            {dist_depot_str}
        </div>
        """
        tooltip = f"#{num_label} · {time_str} — {s['addr'][:38]}{'…' if len(s['addr']) > 38 else ''}"
        if dur_str:
            tooltip += f"  ⏸ {dur_str}"

        diam      = max(24, radius * 2)
        font_size = max(9, diam // 3)
        folium.Marker(
            location=s["coords"],
            icon=folium.DivIcon(
                html=(
                    f'<div style="'
                    f'width:{diam}px;height:{diam}px;border-radius:50%;'
                    f'background:{color};border:2px solid white;'
                    f'text-align:center;line-height:{diam}px;'
                    f'font-size:{font_size}px;font-weight:bold;color:white;'
                    f'box-shadow:0 2px 5px rgba(0,0,0,.45);'
                    f'">{num_label}</div>'
                ),
                icon_size=(diam, diam),
                icon_anchor=(diam // 2, diam // 2),
            ),
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=tooltip,
        ).add_to(m)

    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;bottom:28px;left:28px;z-index:9999;
                background:white;padding:10px 16px;border-radius:10px;
                box-shadow:0 2px 12px rgba(0,0,0,.2);
                font-family:sans-serif;font-size:12px;line-height:2.0">
        <b style="color:{C_BLUE_DARK};font-size:13px">Légende</b><br>
        <span style="color:{C_GREEN};font-size:18px">●</span>&nbsp;Départ (1er arrêt)<br>
        <span style="color:{C_RED};font-size:18px">●</span>&nbsp;Arrivée finale<br>
        <span style="color:{C_BLUE_LIGHT};font-size:18px">●</span>&nbsp;Arrêt &lt; 2 min<br>
        <span style="color:{C_BLUE_DARK};font-size:18px">●</span>&nbsp;Arrêt 2 – 15 min<br>
        <span style="color:{C_ORANGE};font-size:18px">●</span>&nbsp;Pause 15 – 45 min<br>
        <span style="color:{C_PURPLE};font-size:18px">●</span>&nbsp;Longue pause &gt; 45 min<br>
        {"<span style='color:" + C_ORANGE + ";font-size:12px'>◯</span>&nbsp;Zone dépôt (1 km)<br>" if depot_coords else ""}
        <span style="color:#999;font-size:10px">Taille des cercles ∝ durée d'arrêt</span>
    </div>
    """))

    m.fit_bounds([
        [min(lats) - 0.005, min(lons) - 0.005],
        [max(lats) + 0.005, max(lons) + 0.005],
    ])

    st_folium(m, use_container_width=True, height=600, returned_objects=[])

    # ── 8b. Adresses de la journée ────────────────────────
    all_stop_addrs = list(dict.fromkeys(s["addr"] for s in stops))
    missing_addrs  = [a for a in all_stop_addrs if not cache.get(a)]
    found_addrs    = [a for a in all_stop_addrs if cache.get(a)]

    if missing_addrs:
        st.markdown(
            f"<div style='background:#fff3cd;border-left:4px solid {C_ORANGE};"
            f"padding:10px 14px;border-radius:6px;margin-bottom:8px'>"
            f"<b>⚠️ {len(missing_addrs)} adresse(s) non reconnue(s)</b> — "
            f"corrigez et validez pour les voir sur la carte.</div>",
            unsafe_allow_html=True,
        )
        for orig_addr in missing_addrs:
            fix_key = f"q_addr_fix_{hash(orig_addr)}"
            if fix_key not in st.session_state:
                st.session_state[fix_key] = _expand_address(orig_addr)
            col_addr, col_btn = st.columns([5, 1])
            with col_addr:
                st.text_input(
                    f"❌ {orig_addr}",
                    key=fix_key,
                    label_visibility="visible",
                )
            with col_btn:
                st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
                if st.button("Valider", key=f"q_btn_fix_{hash(orig_addr)}", use_container_width=True):
                    corrected = st.session_state[fix_key].strip()
                    if corrected:
                        with st.spinner(f"Géocodage de « {corrected} »…"):
                            coords = _geocode_single_fr(corrected)
                        if coords:
                            save_geocode_entry(orig_addr, coords)
                            if corrected != orig_addr:
                                save_geocode_entry(corrected, coords)
                            st.success(f"✅ Trouvé : {corrected}")
                            st.rerun()
                        else:
                            st.error("Introuvable. Essayez une autre formulation.")
                st.markdown("</div>", unsafe_allow_html=True)

    if found_addrs:
        with st.expander(f"✅ {len(found_addrs)} adresse(s) reconnue(s)", expanded=False):
            for a in found_addrs:
                coords = cache[a]
                st.caption(f"✅ {a}  —  `{coords[0]:.5f}, {coords[1]:.5f}`")

    # ── 9. Tableau détail ─────────────────────────────────
    st.divider()
    st.markdown(f"### 📋 Détail des trajets — **{selected_vehicle}** — {sel_day_fmt}")

    disp = df[["Lieu de départ", "Lieu d'arrivée", "Durée du sous-trajet", "Distance totale"]].copy()
    disp.insert(0, "Départ",  df["_dep"].dt.strftime("%H:%M"))
    disp.insert(1, "Arrivée", df["_arr"].dt.strftime("%H:%M").fillna("?"))
    st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── 10. Statistiques multi-véhicules ──────────────────
    st.divider()
    st.markdown("### 📊 Statistiques passages dépôt — tous les véhicules du fichier")
    st.caption(
        "Calculé sur l'ensemble des jours disponibles dans le fichier. "
        "Seuls les véhicules avec un dépôt enregistré en base sont analysés."
    )

    all_veh_docs = load_all_quartix_vehicles()
    cache_stats  = load_geocode_cache()

    stat_rows = []
    for plate in vehicle_sheets:
        vdoc        = all_veh_docs.get(plate, {})
        dep_addr    = vdoc.get("depot_address", "—")
        dep_coords  = vdoc.get("depot_coords",  None)
        emp_code    = vdoc.get("employe",        "—")

        try:
            df_v = pd.read_excel(xls, sheet_name=plate, header=4, usecols="B:N")
            df_v.columns = COLS
            df_v["_dep"] = pd.to_datetime(df_v["Départ"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True),  errors="coerce")
            df_v["_arr"] = pd.to_datetime(df_v["Arrivée"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True), errors="coerce")
            df_v = df_v.dropna(subset=["_dep"]).reset_index(drop=True)
            nb_days = df_v["_dep"].dt.date.nunique()
        except Exception:
            nb_days = 0
            df_v    = pd.DataFrame()

        if dep_coords and not df_v.empty:
            bef, aft = _count_depot_visits(df_v, cache_stats, dep_coords)
            before_str = str(bef)
            after_str  = str(aft)
        else:
            before_str = "—"
            after_str  = "—"

        stat_rows.append({
            "Véhicule":                  plate,
            "Employé":                   emp_code,
            "Dépôt enregistré":          dep_addr,
            "Jours dans le fichier":     nb_days if nb_days else "—",
            "Passages avant tournée":    before_str,
            "Passages après tournée":    after_str,
        })

    df_stats = pd.DataFrame(stat_rows)

    def _style_stats(row):
        base      = "font-weight:500"
        bef       = row["Passages avant tournée"]
        aft       = row["Passages après tournée"]
        has_depot = row["Dépôt enregistré"] != "—"
        if not has_depot:
            return [f"{base}; color:#888"] * len(row)
        if bef == "0" or aft == "0":
            return [f"background-color:#fdf3e7; {base}"] * len(row)
        return [f"background-color:#eaf4ec; {base}"] * len(row)

    st.dataframe(
        df_stats.style.apply(_style_stats, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # ── 11. Méthodologie ──────────────────────────────────
    st.divider()
    with st.expander("ℹ️ Méthodologie — comment sont calculés ces chiffres ?"):
        st.markdown(f"""
### Passage au dépôt **avant** la tournée ✅

Un passage est comptabilisé si **toutes** ces conditions sont réunies :
1. 🔢 Le trajet figure parmi les **{FIRST_N_TRIPS} premiers** de la journée
2. 🕐 L'heure de départ est **avant {BEFORE_WORK_H}h00**
3. 📍 La localisation est à moins de **{DEPOT_RADIUS_M} m** du dépôt enregistré
4. ⏱️ L'arrêt dure **au moins {MIN_STOP_MIN} minutes**

---

### Passage au dépôt **après** la tournée ✅

Un passage est comptabilisé si **toutes** ces conditions sont réunies :
1. 🔢 Le trajet figure parmi les **{LAST_N_TRIPS} derniers** de la journée, **sauf le tout dernier**
2. 📍 La localisation est à moins de **{DEPOT_RADIUS_M} m** du dépôt enregistré
3. ⏱️ L'arrêt dure **au moins {MIN_STOP_MIN} minutes**

---

### Pourquoi ces seuils ?

| Paramètre | Valeur | Raison |
|---|---|---|
| **Rayon dépôt** | {DEPOT_RADIUS_M} m | Le géocodage via OpenStreetMap peut être imprécis de quelques centaines de mètres. 1 km absorbe ces écarts sans confondre le dépôt avec un client voisin. |
| **Arrêt minimum** | {MIN_STOP_MIN} min | Un simple passage devant le dépôt ne doit pas être compté. 5 min correspond au minimum pour une action réelle : chargement, signature, pause. |
| **Limite matin** | {BEFORE_WORK_H}h | Les tournées commencent généralement après 7h et rarement après 11h. |
| **Position séquence** | {FIRST_N_TRIPS} premiers / {LAST_N_TRIPS} derniers | On raisonne par position dans la journée plutôt que par heure fixe pour le retour. |
        """)

    # ── 12. Administration du cache ───────────────────────
    st.divider()
    with st.expander("🗑️ Administration du cache"):
        st.caption(
            "Le cache stocke les coordonnées GPS (géocodage) et les routes OSRM calculées. "
            "Supprimez-le si des adresses corrigées ne s'affichent pas correctement."
        )
        col_gc, col_rc, col_both, _ = st.columns([2, 2, 2, 3])
        with col_gc:
            if st.button("🗑️ Vider cache géocodage", use_container_width=True):
                n = clear_geocode_cache()
                st.success(f"✅ {n} adresse(s) supprimée(s).")
                st.rerun()
        with col_rc:
            if st.button("🗑️ Vider cache routes", use_container_width=True):
                n = clear_routes_cache()
                st.success(f"✅ {n} route(s) supprimée(s).")
                st.rerun()
        with col_both:
            if st.button("🗑️ Tout vider", type="primary", use_container_width=True):
                ng = clear_geocode_cache()
                nr = clear_routes_cache()
                st.success(f"✅ Cache vidé — {ng} adresse(s) et {nr} route(s) supprimées.")
                st.rerun()


# ── Onglet 2 : helpers ───────────────────────────────────────────────────────

def _build_export_excel(
    result: dict,
    available_days: list,
    day_summary: dict,
    df_raw: "pd.DataFrame | None" = None,
    late_hour: int = 17,
) -> bytes:
    """Génère un classeur Excel (.xlsx) professionnel avec le récapitulatif des passages dépôt."""
    import io as _io_mod
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side, GradientFill
    from openpyxl.utils import get_column_letter

    # ── Pré-calcul des alertes par jour ──────────────────────────────────────
    alert_map: dict = {}
    if df_raw is not None:
        for d in available_days:
            day_df = df_raw[df_raw["_dep"].dt.date == d]
            notes  = []
            if d.weekday() >= 5:
                notes.append("Weekend")
            if not day_df.empty and day_df["_dep"].dt.hour.max() >= late_hour:
                notes.append(f"Trajet après {late_hour}h")
            alert_map[d] = " / ".join(notes) if notes else ""
    else:
        alert_map = {d: "" for d in available_days}

    # ── Palette ──────────────────────────────────────────────────────────────
    # Identité
    C_NAVY       = "0D1B2A"   # titre principal
    C_STEEL      = "1B3A57"   # sous-titres / en-têtes colonne
    C_MATIN_H    = "1A4971"   # en-tête groupe matin
    C_APMIDI_H   = "14534A"   # en-tête groupe après-midi
    C_ALERT_H    = "7B1C1C"   # en-tête colonne observations
    C_INFO_BG    = "EDF2F7"   # fond bandeau infos
    C_INFO_TXT   = "2D3748"   # texte bandeau infos
    # Données — matin
    C_MATIN_OK   = "BEE3F8"   # passage matin trouvé
    C_MATIN_NO   = "EBF8FF"   # pas de passage matin (très pâle)
    # Données — après-midi
    C_APMIDI_OK  = "B2F5EA"   # passage AM trouvé
    C_APMIDI_NO  = "E6FFFA"   # pas de passage AM
    # Données — date/jour
    C_DATE_ODD   = "FFFFFF"
    C_DATE_EVEN  = "F0F4F8"
    # Alertes
    C_ALERT_BG   = "C53030"   # fond ligne alerte
    C_ALERT_TXT  = "FFFFFF"
    # Légende (bas de page)
    C_LEG_MATIN  = "2B6CB0"
    C_LEG_APMIDI = "276749"
    C_LEG_ALERT  = "C53030"
    # Texte
    C_TXT        = "1A202C"
    C_TXT_MUTED  = "718096"
    C_WHITE      = "FFFFFF"

    def fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)

    def border(color="CBD5E0", thick_left=False):
        s = Side(style="thin", color=color)
        l = Side(style="medium", color="718096") if thick_left else s
        return Border(left=l, right=s, top=s, bottom=s)

    def font(bold=False, size=10, color=C_TXT, italic=False):
        return Font(name="Calibri", bold=bold, size=size, color=color, italic=italic)

    center  = Alignment(horizontal="center", vertical="center", wrap_text=False)
    left    = Alignment(horizontal="left",   vertical="center", wrap_text=False)
    left_w  = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    # ── Workbook ─────────────────────────────────────────────────────────────
    wb = Workbook()
    ws = wb.active
    ws.title = "Récapitulatif"

    plate      = result.get("plate", "")
    depot_addr = result.get("depot_addr", "")
    passages   = result.get("passages", [])
    nb_days    = result.get("nb_days", len(available_days))
    depot_coords = result.get("depot_coords")
    coords_str   = f"{depot_coords[0]:.5f}, {depot_coords[1]:.5f}" if depot_coords else "—"

    N_COLS = 11  # A..K
    last_col = get_column_letter(N_COLS)

    # ── Largeurs colonnes ─────────────────────────────────────────────────────
    col_widths = {
        "A": 13, "B": 13,                          # date, jour
        "C": 11, "D": 13, "E": 14, "F": 14,        # matin
        "G": 11, "H": 13, "I": 14, "J": 14,        # après-midi
        "K": 30,                                    # observations
    }
    for col_letter, w in col_widths.items():
        ws.column_dimensions[col_letter].width = w

    # ── Ligne 1 : titre ───────────────────────────────────────────────────────
    ws.merge_cells(f"A1:{last_col}1")
    c = ws["A1"]
    c.value     = f"  ANALYSE DES PASSAGES DÉPÔT   ·   {plate}"
    c.font      = font(bold=True, size=15, color=C_WHITE)
    c.fill      = fill(C_NAVY)
    c.alignment = left
    ws.row_dimensions[1].height = 36

    # ── Ligne 2 : sous-titre dépôt ────────────────────────────────────────────
    ws.merge_cells(f"A2:{last_col}2")
    c = ws["A2"]
    c.value     = f"  Dépôt : {depot_addr}   ·   GPS : {coords_str}   ·   Tolérance {DEPOT_RADIUS_M} m"
    c.font      = font(size=9, color=C_WHITE, italic=True)
    c.fill      = fill(C_STEEL)
    c.alignment = left
    ws.row_dimensions[2].height = 18

    # ── Ligne 3 : bandeau stats ───────────────────────────────────────────────
    ws.merge_cells(f"A3:{last_col}3")
    c = ws["A3"]
    date_range = (f"{available_days[0].strftime('%d/%m/%Y')} → {available_days[-1].strftime('%d/%m/%Y')}"
                  if available_days else "—")
    nb_alert = sum(1 for v in alert_map.values() if v)
    c.value = (
        f"  Période : {date_range}   ·   Jours analysés : {nb_days}"
        f"   ·   Passages détectés : {len(passages)}"
        f"   ·   Alertes : {nb_alert} jour(s)"
    )
    c.font      = font(size=9, color=C_INFO_TXT, italic=True)
    c.fill      = fill(C_INFO_BG)
    c.alignment = left
    ws.row_dimensions[3].height = 17

    # ── Ligne 4 : en-têtes de groupes ─────────────────────────────────────────
    ws.row_dimensions[4].height = 20

    for col in ["A", "B"]:
        c = ws[f"{col}4"]
        c.fill = fill(C_STEEL)

    ws.merge_cells("C4:F4")
    c = ws["C4"]
    c.value     = "🌅  MATIN"
    c.font      = font(bold=True, size=9, color=C_WHITE)
    c.fill      = fill(C_MATIN_H)
    c.alignment = center
    for col in ["D", "E", "F"]:
        ws[f"{col}4"].fill = fill(C_MATIN_H)

    ws.merge_cells("G4:J4")
    c = ws["G4"]
    c.value     = "🌆  APRÈS-MIDI"
    c.font      = font(bold=True, size=9, color=C_WHITE)
    c.fill      = fill(C_APMIDI_H)
    c.alignment = center
    for col in ["H", "I", "J"]:
        ws[f"{col}4"].fill = fill(C_APMIDI_H)

    c = ws["K4"]
    c.value     = "⚠️  ALERTES"
    c.font      = font(bold=True, size=9, color=C_WHITE)
    c.fill      = fill(C_ALERT_H)
    c.alignment = center

    # ── Ligne 5 : en-têtes colonnes ───────────────────────────────────────────
    col_headers = [
        ("A", "Date",           C_STEEL,   left),
        ("B", "Jour",           C_STEEL,   left),
        ("C", "Arrivée",        C_MATIN_H, center),
        ("D", "Durée (min)",    C_MATIN_H, center),
        ("E", "Trajets avant",  C_MATIN_H, center),
        ("F", "Trajets après",  C_MATIN_H, center),
        ("G", "Arrivée",        C_APMIDI_H,center),
        ("H", "Durée (min)",    C_APMIDI_H,center),
        ("I", "Trajets avant",  C_APMIDI_H,center),
        ("J", "Trajets après",  C_APMIDI_H,center),
        ("K", "Observations",   C_ALERT_H, left),
    ]
    for col_letter, label, bg, aln in col_headers:
        c = ws[f"{col_letter}5"]
        c.value     = label
        c.font      = font(bold=True, size=9, color=C_WHITE)
        c.fill      = fill(bg)
        c.alignment = aln
        c.border    = border()
    ws.row_dimensions[5].height = 28

    ws.freeze_panes = "A6"

    # ── Données ───────────────────────────────────────────────────────────────
    def _val_time(p):
        return p["arrive_time"].strftime("%H:%M") if p else "—"
    def _val_dur(p):
        return int(p["duration_min"]) if p and p["duration_min"] >= 1 else ("—" if not p else 0)
    def _val_tb(p):
        return int(p["trips_before"]) if p and p.get("trips_before") is not None else "—"
    def _val_ta(p):
        return int(p["trips_after"]) if p and p.get("trips_after") is not None else "—"

    for row_idx, d in enumerate(available_days, start=6):
        m   = day_summary[d]["matin"]
        apm = day_summary[d]["après-midi"]
        obs = alert_map.get(d, "")
        is_alert  = bool(obs)
        is_even   = (row_idx % 2 == 0)

        row_data = [
            d.strftime("%d/%m/%Y"),
            d.strftime("%A").capitalize(),
            _val_time(m),   _val_dur(m),   _val_tb(m),   _val_ta(m),
            _val_time(apm), _val_dur(apm), _val_tb(apm), _val_ta(apm),
            obs,
        ]

        # Couleurs par segment selon statut passage
        date_bg   = C_DATE_EVEN if is_even else C_DATE_ODD
        matin_bg  = C_MATIN_OK  if m   else C_MATIN_NO
        apmidi_bg = C_APMIDI_OK if apm else C_APMIDI_NO

        col_fills = [
            date_bg, date_bg,
            matin_bg, matin_bg, matin_bg, matin_bg,
            apmidi_bg, apmidi_bg, apmidi_bg, apmidi_bg,
            C_DATE_ODD,
        ]
        col_aligns = [
            left, left,
            center, center, center, center,
            center, center, center, center,
            left_w,
        ]
        # Bordure épaisse à gauche des groupes matin (C) et après-midi (G) et observations (K)
        thick_left_cols = {3, 7, 11}

        for col_idx, (value, bg, aln) in enumerate(zip(row_data, col_fills, col_aligns), start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = aln
            cell.border    = border(thick_left=(col_idx in thick_left_cols))
            if is_alert:
                cell.fill = fill(C_ALERT_BG)
                cell.font = font(bold=True, size=10, color=C_ALERT_TXT)
            else:
                cell.fill = fill(bg)
                cell.font = font(
                    bold=(col_idx <= 2),
                    size=10,
                    color=C_TXT if col_idx != 11 else C_ALERT_H if obs else C_TXT_MUTED,
                )

        ws.row_dimensions[row_idx].height = 19

    # ── Ligne légende ─────────────────────────────────────────────────────────
    legend_row = 6 + len(available_days) + 1
    ws.row_dimensions[legend_row].height = 8  # spacer

    legend_row += 1
    items = [
        (C_MATIN_OK,  "Passage matin détecté"),
        (C_MATIN_NO,  "Pas de passage matin"),
        (C_APMIDI_OK, "Passage après-midi détecté"),
        (C_APMIDI_NO, "Pas de passage après-midi"),
        (C_ALERT_BG,  f"Weekend ou trajet après {late_hour}h"),
    ]
    for i, (color, label) in enumerate(items):
        col_a = 1 + i * 2
        col_b = col_a + 1
        c_swatch = ws.cell(row=legend_row, column=col_a, value=" ")
        c_swatch.fill = fill(color)
        c_swatch.border = border()
        c_label = ws.cell(row=legend_row, column=col_b, value=label)
        c_label.font = font(size=8, color=C_TXT_MUTED, italic=True)
        c_label.alignment = left
    ws.row_dimensions[legend_row].height = 16

    # ── Onglet 2 : Détail passages ────────────────────────────────────────────
    ws2 = wb.create_sheet("Détail passages")

    W2 = [13, 13, 14, 12, 12, 12, 14, 14, 46]
    HDR2 = [
        ("Date",          C_STEEL,    left),
        ("Jour",          C_STEEL,    left),
        ("Période",       C_STEEL,    center),
        ("Arrivée dépôt", C_MATIN_H,  center),
        ("Départ dépôt",  C_MATIN_H,  center),
        ("Durée (min)",   C_MATIN_H,  center),
        ("Trajets avant", C_APMIDI_H, center),
        ("Trajets après", C_APMIDI_H, center),
        ("Adresse",       C_STEEL,    left),
    ]

    # Titre onglet 2
    ws2.merge_cells(f"A1:I1")
    c = ws2["A1"]
    c.value     = f"  DÉTAIL DES PASSAGES   ·   {plate}   ·   {depot_addr}"
    c.font      = font(bold=True, size=13, color=C_WHITE)
    c.fill      = fill(C_NAVY)
    c.alignment = left
    ws2.row_dimensions[1].height = 32

    for col_idx, ((label, bg, aln), w) in enumerate(zip(HDR2, W2), start=1):
        c = ws2.cell(row=2, column=col_idx, value=label)
        c.font      = font(bold=True, size=9, color=C_WHITE)
        c.fill      = fill(bg)
        c.alignment = aln
        c.border    = border(thick_left=(col_idx in {4, 7, 9}))
        ws2.column_dimensions[get_column_letter(col_idx)].width = w
    ws2.row_dimensions[2].height = 28
    ws2.freeze_panes = "A3"

    PERIOD_STYLE = {
        "matin":      (C_MATIN_OK,  C_MATIN_H,  "🌅 Matin"),
        "après-midi": (C_APMIDI_OK, C_APMIDI_H, "🌆 Après-midi"),
    }

    for row_idx, p in enumerate(passages, start=3):
        dep_t  = p["depart_time"]
        period = p["period"]
        row_bg, period_color, period_label = PERIOD_STYLE.get(
            period, (C_DATE_ODD, C_STEEL, period)
        )
        is_even2 = (row_idx % 2 == 0)
        row_bg2  = row_bg if not is_even2 else _darken_hex(row_bg)

        row_data2 = [
            p["date"].strftime("%d/%m/%Y"),
            p["date"].strftime("%A").capitalize(),
            period_label,
            p["arrive_time"].strftime("%H:%M"),
            dep_t.strftime("%H:%M") if dep_t and pd.notna(dep_t) else "—",
            int(p["duration_min"]) if p["duration_min"] >= 1 else 0,
            int(p.get("trips_before", 0)) if p.get("trips_before") is not None else "—",
            int(p.get("trips_after",  0)) if p.get("trips_after")  is not None else "—",
            p["address"],
        ]
        col_aligns2 = [left, left, center, center, center, center, center, center, left_w]

        for col_idx, (value, aln) in enumerate(zip(row_data2, col_aligns2), start=1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=value)
            cell.fill      = fill(row_bg2)
            cell.border    = border(thick_left=(col_idx in {4, 7, 9}))
            cell.alignment = aln
            cell.font      = font(
                bold=(col_idx in {1, 3}),
                size=10,
                color=period_color if col_idx == 3 else C_TXT,
            )
        ws2.row_dimensions[row_idx].height = 18

    buf = _io_mod.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _darken_hex(hex_color: str, factor: float = 0.93) -> str:
    """Assombrit légèrement une couleur hex pour les lignes paires."""
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"{int(r*factor):02X}{int(g*factor):02X}{int(b*factor):02X}"


def _render_export_button(
    result: dict,
    available_days: list,
    day_summary: dict,
    df_raw: "pd.DataFrame | None" = None,
) -> None:
    """Affiche les options d'export + bouton de téléchargement."""
    col_btn, col_hour, col_info = st.columns([2, 2, 3])

    with col_hour:
        late_hour = st.number_input(
            "⏰ Alerte trajets après (h)",
            min_value=0, max_value=23, value=17, step=1,
            key="q_export_late_hour",
            help="Les jours où le véhicule a effectué un trajet après cette heure seront signalés en rouge dans l'export.",
        )

    plate = result.get("plate", "export")
    try:
        xlsx_bytes = _build_export_excel(
            result, available_days, day_summary,
            df_raw=df_raw, late_hour=int(late_hour),
        )
        filename = (
            f"passages_depot_{plate}_"
            f"{available_days[0].strftime('%Y%m%d')}_"
            f"{available_days[-1].strftime('%Y%m%d')}.xlsx"
        )
        with col_btn:
            st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
            st.download_button(
                label="⬇️ Exporter en Excel",
                data=xlsx_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="q_export_xlsx",
                use_container_width=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
        with col_info:
            st.markdown(
                "<div style='margin-top:32px;font-size:12px;color:#888'>"
                "🔴 Rouge = weekend ou trajet tardif</div>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.warning(f"Export indisponible : {e}")

def _render_passages_result(
    result: dict,
    available_days: list,
    df_raw: "pd.DataFrame | None" = None,
) -> None:
    """Affiche les métriques + tableau + détail pour un résultat d'analyse."""
    import datetime as _dt

    passages = result["passages"]
    nb_days  = result["nb_days"]
    df_pass  = pd.DataFrame(passages) if passages else pd.DataFrame(
        columns=["date", "period", "arrive_time", "depart_time", "duration_min", "address"]
    )

    days_matin  = set(df_pass[df_pass["period"] == "matin"]["date"].unique()) if not df_pass.empty else set()
    days_apmidi = set(df_pass[df_pass["period"] == "après-midi"]["date"].unique()) if not df_pass.empty else set()
    nb_matin    = len(days_matin)
    nb_apmidi   = len(days_apmidi)

    # Bandeau dépôt
    depot_coords = result.get("depot_coords")
    if depot_coords:
        lat, lon = depot_coords[0], depot_coords[1]
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        coords_str = f"{lat:.5f}, {lon:.5f}"
    else:
        maps_url   = None
        coords_str = "coordonnées inconnues"

    st.markdown(
        f"<div style='background:{C_BLUE_DARK};padding:10px 16px;border-radius:8px;"
        f"margin:16px 0 4px'>"
        f"<span style='color:{C_BLUE_LIGHT};font-size:18px'>🏠</span>"
        f"&nbsp;<span style='color:white;font-size:14px'>"
        f"<b>Dépôt analysé :</b> {result['depot_addr']}"
        f" &nbsp;·&nbsp; tolérance {DEPOT_RADIUS_M} m</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if maps_url:
        st.caption(
            f"📍 Coordonnées géocodées : `{coords_str}` — "
            f"[Vérifier sur Google Maps]({maps_url})"
        )

    # Seuil de confiance géocodage
    col_score, _ = st.columns([2, 3])
    with col_score:
        score_threshold = st.slider(
            "🎯 Seuil de confiance géocodage",
            min_value=0.1, max_value=1.0, value=_GEOCODE_MIN_SCORE, step=0.05,
            key="q_score_threshold",
            help="Score minimum retourné par l'API adresse.gouv.fr. "
                 "Plus il est élevé, moins d'adresses sont acceptées mais plus elles sont précises. "
                 "En dessous du seuil → adresse rejetée (apparaît dans les non-géocodées).",
        )

    # Métriques
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📅 Jours analysés", nb_days)
    c2.metric("☀️ Passages matin",    nb_matin,
              delta=f"{nb_matin/nb_days*100:.0f} % des jours" if nb_days else None)
    c3.metric("🌇 Passages après-midi", nb_apmidi,
              delta=f"{nb_apmidi/nb_days*100:.0f} % des jours" if nb_days else None)
    c4.metric("📍 Total passages détectés", len(passages))

    st.divider()

    # Tableau par jour
    st.markdown("#### 📆 Récapitulatif par jour")
    st.caption("🟢 Matin ET après-midi  ·  🟡 Un seul passage  ·  🔴 Aucun passage détecté")

    day_summary: dict = {d: {"matin": None, "après-midi": None} for d in available_days}
    for p in passages:
        d   = p["date"]
        per = p["period"]
        if d in day_summary:
            existing = day_summary[d][per]
            if existing is None or p["arrive_time"] < existing["arrive_time"]:
                day_summary[d][per] = p

    def _fmt(p: dict | None) -> str:
        if p is None:
            return "—"
        t = p["arrive_time"].strftime("%H:%M")
        dur = p["duration_min"]
        return f"{t}  ({int(dur)} min)" if dur >= 1 else t

    def _fmt_trips(p: dict | None, key: str) -> str:
        if p is None:
            return "—"
        v = p.get(key)
        return str(int(v)) if v is not None else "—"

    rows = []
    for d in available_days:
        m   = day_summary[d]["matin"]
        apm = day_summary[d]["après-midi"]
        rows.append({
            "Date":              d.strftime("%d/%m/%Y"),
            "Jour":              d.strftime("%A").capitalize(),
            "🌅 Matin":          _fmt(m),
            "Av. matin":         _fmt_trips(m, "trips_before"),
            "Ap. matin":         _fmt_trips(m, "trips_after"),
            "🌆 Après-midi":     _fmt(apm),
            "Av. A-M":           _fmt_trips(apm, "trips_before"),
            "Ap. A-M":           _fmt_trips(apm, "trips_after"),
            "_m": m is not None,
            "_a": apm is not None,
        })

    df_t = pd.DataFrame(rows)

    def _col_row(row):
        if row["_m"] and row["_a"]:
            bg = "background-color:#d4edda"
        elif row["_m"] or row["_a"]:
            bg = "background-color:#fff3cd"
        else:
            bg = "background-color:#f8d7da"
        return [bg] * len(row)

    st.dataframe(
        df_t.style.apply(_col_row, axis=1).hide(axis="columns", subset=["_m", "_a"]),
        use_container_width=True,
        hide_index=True,
    )

    # Bouton export Excel
    _render_export_button(result, available_days, day_summary, df_raw=df_raw)

    # Détail dépliable
    st.divider()
    with st.expander(f"🔎 Détail de tous les passages ({len(passages)} détecté(s))", expanded=False):
        if df_pass.empty:
            st.info("Aucun passage détecté sur la période analysée.")
        else:
            det = df_pass.copy()
            det["Date"]            = det["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            det["Période"]         = det["period"].apply(lambda p: "Matin" if p == "matin" else "Après-midi")
            det["Arrivée"]         = det["arrive_time"].dt.strftime("%H:%M")
            det["Départ dépôt"]    = det["depart_time"].apply(lambda t: t.strftime("%H:%M") if pd.notna(t) else "—")
            det["Durée (min)"]     = det["duration_min"].apply(lambda m: f"{m:.0f}")
            det["Trajets avant"]   = det.apply(lambda r: str(int(r["trips_before"])) if "trips_before" in r and pd.notna(r["trips_before"]) else "—", axis=1)
            det["Trajets après"]   = det.apply(lambda r: str(int(r["trips_after"])) if "trips_after" in r and pd.notna(r["trips_after"]) else "—", axis=1)
            det["Adresse"]         = det["address"]
            st.dataframe(
                det[["Date", "Période", "Arrivée", "Départ dépôt", "Durée (min)",
                      "Trajets avant", "Trajets après", "Adresse"]],
                use_container_width=True, hide_index=True,
            )

    # Adresses non géocodées
    failed = result.get("failed_addrs")
    if failed is None:
        st.info("ℹ️ Relancez **Analyser** pour voir les adresses non géocodées.")
    else:
        label = (f"⚠️ {len(failed)} adresse(s) non géocodée(s) — invisibles pour la détection"
                 if failed else "✅ Toutes les adresses ont été géocodées")
        with st.expander(label, expanded=bool(failed)):
            if not failed:
                st.caption("Toutes les adresses du fichier ont été géocodées avec succès.")
            else:
                st.caption(
                    "Ces adresses n'ont pas pu être localisées automatiquement. "
                    "Renseignez les coordonnées GPS manuellement pour les inclure dans l'analyse."
                )
                any_saved = False
                for addr in list(failed):
                    col_addr, col_input, col_btn = st.columns([3, 2, 1])
                    with col_addr:
                        st.markdown(f"`{addr}`")
                    with col_input:
                        coords_raw = st.text_input(
                            "Coordonnées GPS",
                            placeholder="lat, lon  ex: 50.638, 2.979",
                            key=f"q_manual_coords_{addr}",
                            label_visibility="collapsed",
                        )
                    with col_btn:
                        if st.button("✅ Valider", key=f"q_manual_save_{addr}",
                                     use_container_width=True):
                            coords_input = coords_raw.strip()
                            coords_parsed = None
                            # Essai parsing direct lat, lon
                            m = re.match(r"^\s*(-?\d+\.?\d*)\s*[,\s]\s*(-?\d+\.?\d*)\s*$",
                                         coords_input)
                            if m:
                                coords_parsed = (float(m.group(1)), float(m.group(2)))
                            else:
                                # Tentative géocodage via API
                                tmp = _geocode_single_fr(coords_input)
                                if tmp:
                                    coords_parsed = tmp
                            if coords_parsed:
                                save_geocode_entry(addr, coords_parsed)
                                # Retirer de la liste des échecs
                                new_failed = [a for a in
                                              st.session_state["q_passages_result"]["failed_addrs"]
                                              if a != addr]
                                st.session_state["q_passages_result"]["failed_addrs"] = new_failed
                                any_saved = True
                                st.success(f"Sauvegardé : {coords_parsed[0]:.5f}, {coords_parsed[1]:.5f}")
                            else:
                                st.error("Coordonnées invalides ou adresse introuvable.")

                # Bouton relancer l'analyse si au moins une adresse a été corrigée
                if any_saved or st.session_state.get("q_manual_rerun_ready"):
                    st.session_state["q_manual_rerun_ready"] = True
                    if st.button("🔄 Relancer l'analyse avec les corrections",
                                 key="q_manual_rerun", type="primary"):
                        cache = load_geocode_cache()
                        depot_coords = result.get("depot_coords")
                        if depot_coords and df_raw is not None:
                            passages = _find_depot_passages(df_raw, cache, tuple(depot_coords))
                            all_addrs = (
                                set(df_raw["Lieu de départ"].dropna().astype(str))
                                | set(df_raw["Lieu d'arrivée"].dropna().astype(str))
                            )
                            new_failed = sorted(a for a in all_addrs if not cache.get(a))
                            st.session_state["q_passages_result"]["passages"]    = passages
                            st.session_state["q_passages_result"]["failed_addrs"] = new_failed
                            st.session_state.pop("q_manual_rerun_ready", None)
                            st.rerun()

    # Méthodologie
    with st.expander("ℹ️ Méthodologie de détection des passages", expanded=False):
        st.markdown(f"""
Un **passage au dépôt** est comptabilisé quand l'adresse d'**arrivée** ou de **départ**
est à moins de **{DEPOT_RADIUS_M} m** du dépôt renseigné.

- ☀️ **Matin** : heure d'arrivée avant 12h00
- 🌆 **Après-midi** : heure d'arrivée à partir de 12h00

Géocodage : **API adresse.data.gouv.fr** (gouvernement français) — gratuite, sans clé, optimisée France.
        """)


def _render_passages_cache_admin() -> None:
    """Boutons de gestion du cache et de la mémoire de l'onglet Passages."""
    st.divider()
    with st.expander("🗑️ Cache & Mémoire", expanded=False):
        col1, col2, col3, _ = st.columns([2, 2, 2, 1])
        with col1:
            if st.button("🗑️ Effacer l'analyse en mémoire", use_container_width=True,
                         key="q_clear_result"):
                st.session_state.pop("q_passages_result", None)
                st.success("✅ Résultat effacé.")
                st.rerun()
        with col2:
            if st.button("🗑️ Vider cache géocodage", use_container_width=True,
                         key="q_clear_geocache"):
                n = clear_geocode_cache()
                st.success(f"✅ {n} adresse(s) supprimée(s).")
                st.rerun()
        with col3:
            if st.button("🗑️ Tout vider", type="primary", use_container_width=True,
                         key="q_clear_all"):
                st.session_state.pop("q_passages_result", None)
                ng = clear_geocode_cache()
                st.success(f"✅ Résultat + {ng} adresse(s) géocodée(s) supprimés.")
                st.rerun()


# ── Onglet 2 : Analyse Passages Dépôt ────────────────────────────────────────

def _render_tab_passages() -> None:

    # En-tête
    st.markdown(
        f"<div style='background:linear-gradient(135deg,{C_BLUE_DARK},{C_BLUE_LIGHT});"
        f"padding:16px 20px;border-radius:10px;margin-bottom:20px'>"
        f"<span style='color:white;font-size:17px;font-weight:700'>📍 Analyse des Passages Dépôt</span>"
        f"<p style='color:rgba(255,255,255,0.85);margin:4px 0 0;font-size:13px'>"
        f"Sélectionnez un réappro, confirmez l'adresse dépôt, puis lancez l'analyse "
        f"pour voir les passages matin et après-midi sur toute la période du fichier.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Récupération du fichier depuis l'onglet Carte ─────
    uploaded       = st.session_state.get("quartix_uploader")
    xls            = None
    vehicle_sheets: list[str] = []
    name_map:       dict[str, str] = {}

    if uploaded:
        try:
            xls    = pd.ExcelFile(uploaded)
            sheets = xls.sheet_names
            if len(sheets) > 1:
                vehicle_sheets = sheets[1:]
                name_map       = _parse_vehicle_names(xls)
        except Exception:
            xls = None

    # Si aucun fichier chargé : afficher résultat en cache si dispo + gestion cache
    if xls is None:
        st.info(
            "📂 Importez d'abord un fichier QUARTIX dans l'onglet **Carte & Trajets** "
            "pour lancer une nouvelle analyse."
        )
        result = st.session_state.get("q_passages_result")
        if result:
            st.markdown("---")
            st.caption("📋 Dernier résultat enregistré en mémoire :")
            available_days = [
                pd.Timestamp(d).date() for d in result.get("available_days", [])
            ] or sorted({p["date"] for p in result["passages"]})
            _render_passages_result(result, available_days)
        _render_passages_cache_admin()
        return

    # ── Sélecteur réappro ─────────────────────────────────
    options_labels = [
        f"{p}  —  {name_map[p]}" if p in name_map else p
        for p in vehicle_sheets
    ]
    options_map    = dict(zip(options_labels, vehicle_sheets))

    col_sel, col_info = st.columns([3, 2])
    with col_sel:
        def _on_vehicle_change():
            st.session_state.pop("q_passages_depot_input", None)

        sel_label = st.selectbox("🚗 Réappro à analyser", options_labels,
                                 key="q_passages_vehicle_label",
                                 on_change=_on_vehicle_change)
    selected_plate = options_map[sel_label]

    # ── Chargement données ────────────────────────────────
    try:
        df_raw = pd.read_excel(xls, sheet_name=selected_plate, header=4, usecols="B:N")
        df_raw.columns = COLS
    except Exception as e:
        st.error(f"Erreur lecture feuille «{selected_plate}» : {e}")
        return

    df_raw["_dep"] = pd.to_datetime(df_raw["Départ"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True),  errors="coerce")
    df_raw["_arr"] = pd.to_datetime(df_raw["Arrivée"].astype(str).str.replace(r'\s+[A-Z]{2,5}$', '', regex=True), errors="coerce")
    df_raw = df_raw.dropna(subset=["_dep"]).sort_values("_dep").reset_index(drop=True)
    for col in ["Lieu de départ", "Lieu d'arrivée"]:
        df_raw[col] = df_raw[col].astype(str).map(_clean_addr)

    if df_raw.empty:
        st.warning("Aucune donnée valide dans cette feuille.")
        return

    nb_days_file   = df_raw["_dep"].dt.date.nunique()
    available_days = sorted(df_raw["_dep"].dt.date.unique())
    date_min       = available_days[0]
    date_max       = available_days[-1]

    with col_info:
        st.markdown(
            f"<div style='background:#f0f4fa;border-radius:8px;padding:10px 14px;"
            f"margin-top:24px;font-size:13px;color:{C_BLUE_DARK}'>"
            f"<b>Période :</b> {date_min.strftime('%d/%m/%Y')} → {date_max.strftime('%d/%m/%Y')}<br>"
            f"<b>Jours :</b> {nb_days_file} &nbsp;|&nbsp; <b>Trajets :</b> {len(df_raw)}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Adresse dépôt + bouton Analyser ──────────────────
    vehicle_doc      = load_quartix_vehicle(selected_plate)
    db_depot_address = vehicle_doc.get("depot_address", "") if vehicle_doc else ""
    auto_detect      = _auto_detect_depot(df_raw)
    default_depot    = db_depot_address or auto_detect or ""
    is_approximated  = bool(not db_depot_address and auto_detect)

    col_depot, col_btn = st.columns([5, 1])
    with col_depot:
        depot_input = st.text_input(
            "📍 Adresse du dépôt",
            value=default_depot,
            placeholder="Ex : 39 Av. de la Pépinière, 59320 Haubourdin  ou  50.638, 2.979",
            key="q_passages_depot_input",
            help="Adresse texte OU coordonnées GPS : latitude, longitude (ex : 50.6384, 2.9794)",
        )
        if is_approximated:
            st.caption("🔸 Adresse auto-détectée — vérifiez et corrigez si nécessaire avant d'analyser")
    with col_btn:
        st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
        run_btn = st.button("🔍 Analyser", type="primary", key="q_passages_run",
                            use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Lancement de l'analyse ────────────────────────────
    if run_btn:
        depot_addr_clean = depot_input.strip()
        if not depot_addr_clean:
            st.warning("Veuillez saisir une adresse ou des coordonnées GPS.")
            return

        # Détection coordonnées directes : "50.638, 2.979" ou "50.638 2.979"
        _coord_match = re.match(
            r"^\s*(-?\d+\.?\d*)\s*[,\s]\s*(-?\d+\.?\d*)\s*$",
            depot_addr_clean,
        )
        if _coord_match:
            try:
                depot_coords = (float(_coord_match.group(1)), float(_coord_match.group(2)))
                cache = load_geocode_cache()
            except ValueError:
                depot_coords = None
        else:
            with st.spinner("Géocodage du dépôt…"):
                cache = load_geocode_cache()
                cache = _geocode_all([depot_addr_clean], cache)
                depot_coords = cache.get(depot_addr_clean)

        if not depot_coords:
            st.error("❌ Adresse dépôt introuvable. Vérifiez l'orthographe ou entrez les coordonnées GPS.")
            return

        all_addrs: set[str] = set()
        for c in ["Lieu de départ", "Lieu d'arrivée"]:
            all_addrs.update(df_raw[c].dropna().astype(str).unique())

        with st.spinner("Géocodage des adresses du fichier…"):
            cache = _geocode_all(list(all_addrs), cache)

        failed_addrs = sorted(a for a in all_addrs if not cache.get(a))

        with st.spinner("Analyse des passages…"):
            passages = _find_depot_passages(df_raw, cache, tuple(depot_coords))

        st.session_state["q_passages_result"] = {
            "plate":          selected_plate,
            "depot_addr":     depot_addr_clean,
            "depot_coords":   depot_coords,
            "passages":       passages,
            "nb_days":        nb_days_file,
            "available_days": [d.isoformat() for d in available_days],
            "failed_addrs":   failed_addrs,
        }

    # ── Affichage des résultats ───────────────────────────
    result = st.session_state.get("q_passages_result")
    if result is None:
        st.info("👆 Sélectionnez un réappro, vérifiez l'adresse dépôt, puis cliquez **Analyser**.")
        _render_passages_cache_admin()
        return

    if result["plate"] != selected_plate:
        st.info("Le réappro sélectionné a changé. Cliquez **Analyser** pour recalculer.")
        _render_passages_cache_admin()
        return

    _render_passages_result(result, available_days, df_raw=df_raw)
    _render_passages_cache_admin()


# ── Point d'entrée de la page ─────────────────────────────────────────────────

def render() -> None:
    tab_carte, tab_passages = st.tabs([
        "🗺️  Carte & Trajets",
        "📍  Analyse Passages Dépôt",
    ])

    with tab_carte:
        _render_tab_carte()

    with tab_passages:
        _render_tab_passages()
