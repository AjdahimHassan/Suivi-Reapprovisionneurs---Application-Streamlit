"""
Page QUARTIX — Visualisation des trajets réappros
  • Import Excel QUARTIX (format multi-feuilles)
  • Sélecteur véhicule + journée
  • Panel employé / dépôt avec sauvegarde MongoDB
  • Carte Folium : tracé complet + cercles proportionnels aux durées d'arrêt
  • KPIs : distance minimale au dépôt avant 11h et après 18h
  • Statistiques passages dépôt pour tous les véhicules du fichier
"""

import re
import pickle
import numpy as np
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.distance import geodesic

from mongo_storage import (
    load_quartix_vehicle,
    load_all_quartix_vehicles,
    upsert_quartix_vehicle,
    load_plannings_from_mongo,
)

# ── Constantes ────────────────────────────────────────────────────────────────

CACHE_FILE     = "quartix_geocode_cache.pkl"
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


# ── Géocodage ────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(cache, f)
    except Exception:
        pass


def _geocode_all(addresses: list[str], cache: dict) -> dict:
    """Géocode uniquement les adresses absentes du cache, met à jour le cache."""
    missing = [a for a in addresses if a and str(a).strip() and a not in cache]
    if not missing:
        return cache
    geolocator = Nominatim(user_agent="distriprot_quartix_v2")
    geocode_fn = RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1,
        max_retries=3,
        error_wait_seconds=2,
        swallow_exceptions=True,
    )
    bar = st.progress(0, text="Géocodage des adresses…")
    for i, addr in enumerate(missing):
        loc = geocode_fn(str(addr), timeout=10)
        cache[addr] = (loc.latitude, loc.longitude) if loc else None
        bar.progress((i + 1) / len(missing), text=f"Géocodage… {i+1}/{len(missing)}")
    bar.empty()
    _save_cache(cache)
    return cache


# ── Helpers analytiques ───────────────────────────────────────────────────────

def _parse_min(val) -> float:
    """Convertit une durée (timedelta / 'HH:MM:SS' / '1h 23min') en minutes."""
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
    """
    Heuristique simple : le dépôt est l'adresse de départ la plus fréquente
    sur l'ensemble des données du véhicule (toutes journées confondues).
    """
    all_deps = df_all["Lieu de départ"].dropna().astype(str)
    if all_deps.empty:
        return None
    return all_deps.value_counts().idxmax()


def _stop_duration_at(grp: pd.DataFrame, i: int) -> float:
    """Durée d'arrêt (en minutes) au point de départ du trajet i = écart depuis l'arrivée i-1."""
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
    """
    Pour une journée (grp trié par départ), détecte :

    before_tour → passage dépôt AVANT la tournée :
        • parmi les FIRST_N_TRIPS premiers trajets
        • heure de départ < BEFORE_WORK_H
        • distance au dépôt ≤ DEPOT_RADIUS_M
        • arrêt ≥ MIN_STOP_MIN minutes

    after_tour → passage dépôt APRÈS la tournée :
        • parmi les LAST_N_TRIPS derniers trajets, SAUF le tout dernier
          (le dernier trajet est le retour final au dépôt, pas un « passage »)
        • distance au dépôt ≤ DEPOT_RADIUS_M
        • arrêt ≥ MIN_STOP_MIN minutes
        • pas de contrainte horaire (on se base sur la position dans la journée)
    """
    if depot_coords is None or grp.empty:
        return False, False

    grp = grp.sort_values("_dep").reset_index(drop=True)
    n   = len(grp)

    before_tour = False
    after_tour  = False

    # ── Avant tournée : N premiers trajets avec contrainte horaire ──
    for i in range(min(FIRST_N_TRIPS, n)):
        row = grp.loc[i]
        if row["_dep"].hour >= BEFORE_WORK_H:
            continue
        coords = cache.get(str(row["Lieu de départ"]))
        if not coords:
            continue
        if geodesic(coords, depot_coords).meters > DEPOT_RADIUS_M:
            continue
        if _stop_duration_at(grp, i) >= MIN_STOP_MIN:
            before_tour = True
            break

    # ── Après tournée : N derniers trajets, tout dernier exclu ──
    if n >= 2:
        # indices de n-LAST_N_TRIPS à n-2 inclus (exclut le dernier = n-1)
        start = max(0, n - LAST_N_TRIPS)
        for i in range(start, n - 1):
            row = grp.loc[i]
            coords = cache.get(str(row["Lieu de départ"]))
            if not coords:
                continue
            if geodesic(coords, depot_coords).meters > DEPOT_RADIUS_M:
                continue
            if _stop_duration_at(grp, i) >= MIN_STOP_MIN:
                after_tour = True
                break

    return before_tour, after_tour


def _count_depot_visits(
    df_vehicle: pd.DataFrame,
    cache: dict,
    depot_coords,
) -> tuple[int, int]:
    """
    Compte sur toutes les journées d'un véhicule :
      - nb de jours avec passage dépôt avant tournée
      - nb de jours avec passage dépôt après tournée
    Utilise uniquement le cache géocodage (pas de nouvel appel API).
    """
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


# ── Render ────────────────────────────────────────────────────────────────────

def render() -> None:

    # ── 1. Upload ─────────────────────────────────────────
    col_up, _ = st.columns([2, 3])
    with col_up:
        uploaded = st.file_uploader(
            "📂 Importer un export Excel QUARTIX",
            type=["xls", "xlsx"],
            key="quartix_uploader",
        )

    if not uploaded:
        st.info(
            "👆 Importez un fichier Excel QUARTIX (`.xls` ou `.xlsx`) pour visualiser les trajets.\n\n"
            "Le fichier doit contenir une feuille résumé + une feuille par véhicule (format standard QUARTIX)."
        )
        return

    # ── 2. Lecture Excel ──────────────────────────────────
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

    # ── 3. Sélecteurs véhicule + journée ──────────────────
    col_v, col_d, _ = st.columns([2, 2, 1])
    with col_v:
        selected_vehicle = st.selectbox("🚗 Véhicule (plaque)", vehicle_sheets, key="q_vehicle")

    # Parse la feuille complète (toutes dates) pour la détection dépôt
    try:
        df_raw = pd.read_excel(xls, sheet_name=selected_vehicle, header=4, usecols="B:N")
        df_raw.columns = COLS
    except Exception as e:
        st.error(f"Erreur lecture feuille «{selected_vehicle}» : {e}")
        return

    df_raw["_dep"] = pd.to_datetime(df_raw["Départ"],  errors="coerce")
    df_raw["_arr"] = pd.to_datetime(df_raw["Arrivée"], errors="coerce")
    df_raw = df_raw.dropna(subset=["_dep"]).sort_values("_dep").reset_index(drop=True)

    if df_raw.empty:
        st.warning("Aucune donnée valide dans cette feuille.")
        return

    available_days = sorted(df_raw["_dep"].dt.date.unique(), reverse=True)
    with col_d:
        sel_day_fmt = st.selectbox(
            "📅 Journée",
            [d.strftime("%d/%m/%Y") for d in available_days],
            key="q_day",
        )
    selected_day = next(d for d in available_days if d.strftime("%d/%m/%Y") == sel_day_fmt)

    # ── 4. Panel véhicule : employé + dépôt ──────────────
    st.divider()

    # Chargement données BDD
    vehicle_doc = load_quartix_vehicle(selected_vehicle)
    try:
        plannings, _ = load_plannings_from_mongo()
        employee_options = sorted(plannings.keys())
    except Exception:
        employee_options = []

    # Adresse dépôt connue ou approximée
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

    # Session state pour le mode édition
    edit_key = f"edit_depot_{selected_vehicle}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False

    with st.container():
        st.markdown("#### 🚗 Informations véhicule")

        col_emp, col_dep, col_btn = st.columns([2, 4, 1])

        # — Employé —
        with col_emp:
            emp_idx = 0
            if db_employe and db_employe in employee_options:
                emp_idx = employee_options.index(db_employe) + 1  # +1 car on ajoute "" en tête
            selected_employee = st.selectbox(
                "👤 Employé",
                [""] + employee_options,
                index=emp_idx,
                key="q_employee",
            )

        # — Adresse dépôt —
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

        # — Bouton édition —
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

        # — Bouton Sauvegarder (visible en mode édition) —
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
                            tmp_cache = _load_cache()
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
                                # Rafraîchir les variables locales
                                db_depot_address = addr_to_save
                                db_depot_coords  = list(coords)
                                db_employe       = emp_to_save
                                is_approximated  = False
                            except Exception as e:
                                st.error(f"❌ Erreur MongoDB : {e}")
                            st.rerun()

    # depot_coords utilisés pour les calculs
    depot_coords = db_depot_coords

    # ── 5. Filtrage journée + géocodage ───────────────────
    df = df_raw[df_raw["_dep"].dt.date == selected_day].copy().reset_index(drop=True)
    if df.empty:
        st.warning("Aucun trajet pour ce jour.")
        return

    addrs: set[str] = set()
    for c in ["Lieu de départ", "Lieu d'arrivée"]:
        addrs.update(df[c].dropna().astype(str).unique())

    cache = _load_cache()
    cache = _geocode_all(list(addrs), cache)

    # ── 6. Construction des arrêts ordonnés ───────────────
    stops = []
    for i, row in df.iterrows():
        dep_addr = str(row["Lieu de départ"])
        dep_coords = cache.get(dep_addr)

        stop_min = 0.0
        if i > 0:
            prev_arr = df.loc[i - 1, "_arr"]
            if pd.notna(prev_arr) and pd.notna(row["_dep"]):
                stop_min = (row["_dep"] - prev_arr).total_seconds() / 60

        stops.append({
            "addr":     dep_addr,
            "coords":   dep_coords,
            "time":     row["_dep"],
            "stop_min": max(0.0, stop_min),
            "trip_dur": row.get("Durée du sous-trajet"),
            "dist":     row.get("Distance totale"),
            "is_first": (i == 0),
            "is_last":  False,
        })

    last_row = df.iloc[-1]
    arr_addr = str(last_row["Lieu d'arrivée"])
    stops.append({
        "addr":     arr_addr,
        "coords":   cache.get(arr_addr),
        "time":     last_row["_arr"],
        "stop_min": 0.0,
        "trip_dur": None,
        "dist":     None,
        "is_first": False,
        "is_last":  True,
    })

    valid = [s for s in stops if s["coords"]]
    if len(valid) < 2:
        st.error(
            "Pas assez d'adresses géocodées pour tracer le trajet. "
            "Vérifiez que les adresses du fichier sont reconnues par OpenStreetMap."
        )
        if st.checkbox("🔍 Voir les adresses non trouvées"):
            for s in stops:
                if not s["coords"]:
                    st.caption(f"❌ {s['addr']}")
        return

    # ── 7. KPIs ───────────────────────────────────────────
    lats = [s["coords"][0] for s in valid]
    lons = [s["coords"][1] for s in valid]
    total_km   = sum(_to_km(s["dist"]) for s in stops if s["dist"])
    nb_stops   = sum(1 for s in stops if not s["is_first"] and not s["is_last"] and s["stop_min"] >= 2)
    long_stops = sum(1 for s in stops if not s["is_first"] and not s["is_last"] and s["stop_min"] >= 20)

    # Vérification passage dépôt pour la journée sélectionnée
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

    st.divider()

    # ── 8. Carte Folium ───────────────────────────────────
    center = [np.mean(lats), np.mean(lons)]
    m = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")

    # Tracé route
    folium.PolyLine(
        locations=[s["coords"] for s in valid],
        color=C_BLUE_DARK,
        weight=3,
        opacity=0.75,
    ).add_to(m)

    # Cercle dépôt (1 km) si connu
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

    # Marqueurs d'arrêt
    for s in valid:
        color, radius = _stop_style(s["stop_min"], s["is_first"], s["is_last"])
        time_str = s["time"].strftime("%H:%M") if pd.notna(s["time"]) else "?"
        dur_str  = f"{int(s['stop_min'])}min" if s["stop_min"] >= 1 else ""
        trip_min = _parse_min(s["trip_dur"])

        label_first = "🚀 Départ dépôt" if s["is_first"] else ""
        label_last  = "🏁 Retour dépôt" if s["is_last"]  else ""

        # Distance au dépôt si connu
        dist_depot_str = ""
        if depot_coords and s["coords"]:
            dm = geodesic(s["coords"], depot_coords).meters
            dist_depot_str = f"<br>🏠 Distance dépôt : <b>{dm:.0f} m</b>"

        popup_html = f"""
        <div style="font-family:sans-serif;font-size:13px;min-width:200px;max-width:300px;">
            {"<b style='color:" + C_GREEN + "'>" + label_first + "</b><br>" if label_first else ""}
            {"<b style='color:" + C_RED   + "'>" + label_last  + "</b><br>" if label_last  else ""}
            <b style="color:{C_BLUE_DARK}">{s['addr']}</b>
            <hr style="margin:4px 0">
            🕐 <b>{time_str}</b>
            {"<br>⏸️ Arrêt : <b>" + dur_str + "</b>" if dur_str else ""}
            {"<br>🚗 Trajet suivant : " + str(int(trip_min)) + " min" if trip_min > 0 else ""}
            {"<br>📏 " + str(s['dist']) + " km" if s['dist'] else ""}
            {dist_depot_str}
        </div>
        """
        tooltip = f"{time_str} — {s['addr'][:42]}{'…' if len(s['addr']) > 42 else ''}"
        if dur_str:
            tooltip += f"  ⏸ {dur_str}"

        folium.CircleMarker(
            location=s["coords"],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.88,
            weight=2,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=tooltip,
        ).add_to(m)

    # Légende
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;bottom:28px;left:28px;z-index:9999;
                background:white;padding:10px 16px;border-radius:10px;
                box-shadow:0 2px 12px rgba(0,0,0,.2);
                font-family:sans-serif;font-size:12px;line-height:2.0">
        <b style="color:{C_BLUE_DARK};font-size:13px">Légende</b><br>
        <span style="color:{C_GREEN};font-size:18px">●</span>&nbsp;Départ dépôt<br>
        <span style="color:{C_RED};font-size:18px">●</span>&nbsp;Retour dépôt<br>
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
    cache_stats  = _load_cache()   # cache en lecture seule pour les stats

    stat_rows = []
    for plate in vehicle_sheets:
        vdoc        = all_veh_docs.get(plate, {})
        dep_addr    = vdoc.get("depot_address", "—")
        dep_coords  = vdoc.get("depot_coords",  None)
        emp_code    = vdoc.get("employe",        "—")

        # Parser la feuille (peut lever une exception si format inattendu)
        try:
            df_v = pd.read_excel(xls, sheet_name=plate, header=4, usecols="B:N")
            df_v.columns = COLS
            df_v["_dep"] = pd.to_datetime(df_v["Départ"],  errors="coerce")
            df_v["_arr"] = pd.to_datetime(df_v["Arrivée"], errors="coerce")
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
2. 🕐 L'heure de départ est **avant {BEFORE_WORK_H}h00** (le réappro charge son camion en début de matinée)
3. 📍 La localisation est à moins de **{DEPOT_RADIUS_M} m** du dépôt enregistré
4. ⏱️ L'arrêt dure **au moins {MIN_STOP_MIN} minutes**

---

### Passage au dépôt **après** la tournée ✅

Un passage est comptabilisé si **toutes** ces conditions sont réunies :
1. 🔢 Le trajet figure parmi les **{LAST_N_TRIPS} derniers** de la journée, **sauf le tout dernier**
   *(le dernier trajet est le retour final au dépôt en fin de journée — il n'est pas compté car c'est la clôture normale, pas un passage intermédiaire)*
2. 📍 La localisation est à moins de **{DEPOT_RADIUS_M} m** du dépôt enregistré
3. ⏱️ L'arrêt dure **au moins {MIN_STOP_MIN} minutes**

---

### Pourquoi ces seuils ?

| Paramètre | Valeur | Raison |
|---|---|---|
| **Rayon dépôt** | {DEPOT_RADIUS_M} m | Le géocodage via OpenStreetMap peut être imprécis de quelques centaines de mètres. 1 km absorbe ces écarts sans confondre le dépôt avec un client voisin. |
| **Arrêt minimum** | {MIN_STOP_MIN} min | Un simple passage devant le dépôt (feu rouge, manœuvre) ne doit pas être compté. 5 min correspond au minimum pour une action réelle : chargement, signature, pause. |
| **Limite matin** | {BEFORE_WORK_H}h | Les tournées commencent généralement après 7h et rarement après 11h. Tout passage au dépôt avant 11h est considéré comme un chargement pré-tournée. |
| **Position séquence** | {FIRST_N_TRIPS} premiers / {LAST_N_TRIPS} derniers | On raisonne par position dans la journée plutôt que par heure fixe pour le retour, car les fins de tournée sont variables d'un employé à l'autre. |

Ces paramètres sont des **constantes configurables** dans le code :
`DEPOT_RADIUS_M`, `MIN_STOP_MIN`, `BEFORE_WORK_H`, `FIRST_N_TRIPS`, `LAST_N_TRIPS`
        """)
