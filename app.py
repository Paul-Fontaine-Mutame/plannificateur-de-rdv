import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

from calendrier import Calendrier, Lieu
from mapbox import geocode
from mapbox import suggestions as mapbox_suggestions
from utils import intervals_overlap, to_hours_and_minutes, to_seconds


# ---------- INIT SESSION STATE ----------
def init_state():
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()

    st.session_state.setdefault("year", iso_year)
    st.session_state.setdefault("week", iso_week)
    st.session_state.setdefault("year_input", iso_year)
    st.session_state.setdefault("week_input", iso_week)
    st.session_state.setdefault("address_query", "")
    st.session_state.setdefault("address_options", [])
    st.session_state.setdefault("selected_mapbox_id", None)
    st.session_state.setdefault("duration", "1h30")

    st.session_state.setdefault("conseiller", "Théo")
    if st.session_state.get("calendrier", None) is None:
        update_calendar(False)
    st.session_state.setdefault("debut_journee", "8h")
    st.session_state.setdefault("fin_journee", "18h")
    st.session_state.setdefault("temps_repas", "1h")
    st.session_state.setdefault("debut_repas", "12h")
    st.session_state.setdefault("fin_repas", "14h")
    st.session_state.setdefault("marge", "10min")


def set_debut_journee():
    cal = get_calendrier()
    seconds = to_seconds(st.session_state["debut_journee"])
    cal.debut_journee = seconds


def set_fin_journee():
    cal = get_calendrier()
    seconds = to_seconds(st.session_state["fin_journee"])
    cal.fin_journee = seconds


def set_temps_repas():
    cal = get_calendrier()
    seconds = to_seconds(st.session_state["temps_repas"])
    cal.fin_journee = seconds


def set_heures_repas():
    cal = get_calendrier()
    seconds = to_seconds(st.session_state["debut_repas"])
    cal.heures_repas[0] = seconds
    seconds = to_seconds(st.session_state["fin_repas"])
    cal.heures_repas[1] = seconds


def set_marge():
    cal = get_calendrier()
    seconds = to_seconds(st.session_state["marge"])
    cal.marge = seconds


def shift_week(delta_weeks: int):
    """Change year/week pair by +/- delta_weeks."""
    y = st.session_state["year"]
    w = st.session_state["week"]
    # Monday of the current ISO week
    d = date.fromisocalendar(y, w, 1) + timedelta(weeks=delta_weeks)
    ny, nw, _ = d.isocalendar()
    st.session_state["year"] = ny
    st.session_state["week"] = nw
    st.session_state["year_input"] = ny
    st.session_state["week_input"] = nw


def sync_year_week():
    st.session_state["year"] = st.session_state["year_input"]
    st.session_state["week"] = st.session_state["week_input"]


def search_address():
    query = st.session_state["address_query"].strip()
    if query:
        try:
            results = mapbox_suggestions(query)
            st.session_state["address_options"] = results
        except Exception as e:
            st.error(f"Erreur lors de la recherche d'adresse : {e}")


def show_on_google_maps():
    lon, lat = geocode(st.session_state["selected_mapbox_id"])
    url = f"https://www.google.com/maps/place/{lat},{lon}/@{lat},{lon},12z"
    st.html(
        f'''
        <script>
            window.open("{url}", "_blank");
        </script>
        '''
    )
    st.success("La localisation a été ouverte dans un nouvel onglet Google Maps.")


def update_calendar(triggered_by_url_change: bool):
    if triggered_by_url_change:
        st.session_state["conseiller"] = ""
    else:
        with st.sidebar:
            try:
                ics_path = Path(".agenda_ics_conseillers.json")
                if ics_path.exists():
                    with ics_path.open("r", encoding="utf-8") as f:
                        conseillers_to_ics = json.load(f)
                    conseiller = st.session_state.get("conseiller", "").strip()
                    url = conseillers_to_ics.get(conseiller)
                    if url:
                        st.session_state["url_calendrier"] = url
                    else:
                        liste_conseillers = list(conseillers_to_ics.keys())
                        st.warning(
                            f"Aucun calendrier trouvé pour '{conseiller}'. Choisissez parmi : {liste_conseillers}."
                        )
                        # remet le nom du conseiller correspondant à l'url
                        for key, value in conseillers_to_ics.items():
                            if value == st.session_state["url_calendrier"]:
                                nom = key
                        st.session_state["conseiller"] = nom
                else:
                    st.warning(f"Fichier {ics_path} introuvable.")
            except Exception as e:
                st.error(f"Erreur lors du chargement du fichier de mapping : {e}")

    with st.spinner("Chargement du calendrier…"):
        cal = Calendrier()
        cal.rendez_vous = []
        try:
            cal.charger_ics(st.session_state["url_calendrier"])
            st.session_state["dispos"] = []
            st.session_state["calendrier"] = cal
        except Exception as e:
            st.error(f"Impossible de charger le calendrier ICS : {e}")
            st.session_state["calendrier"] = None


def get_calendrier() -> Calendrier | None:
    if "calendrier" in st.session_state:
        return st.session_state["calendrier"]

    with st.spinner("Chargement du calendrier…"):
        cal = Calendrier()
        try:
            cal.charger_ics(st.session_state["url_calendrier"])
        except Exception as e:
            st.error(f"Impossible de charger le calendrier ICS : {e}")
            st.session_state["calendrier"] = None
        else:
            st.session_state["calendrier"] = cal

    return st.session_state["calendrier"]


def save_url():
    def save_url_in_json():
        with st.sidebar:
            name = st.session_state.get("nouveau_conseiller", "").strip()
            url = st.session_state.get("url_calendrier", "").strip()

            if not name or not url:
                st.warning(
                    "Veuillez renseigner le nom du conseiller ET l'URL du calendrier."
                )
                return

            ics_path = Path(".agenda_ics_conseillers.json")

            if ics_path.exists():
                with ics_path.open("r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        st.error(
                            "Le fichier JSON est corrompu. Supprimez-le ou corrigez-le avant d'enregistrer."
                        )
                        return
            else:
                data = {}

            # check si l'url n'est pas déja enregistré
            for key, value in data.items():
                if value == url:
                    nom = key
                    st.warning(f"ce calendrier est déjà sauvegardé pour {nom}")
                    return
                if key == name:
                    ics = value
                    st.warning(
                        f"{name} a déjà un calendrier sauvegardé : {ics}. Souhaitez vous le modifier quand même ?"
                    )
                    c1, c2 = st.columns(2)
                    with c1:

                        def sauvegarder_quand_meme():
                            data[name] = url
                            with ics_path.open("w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            with st.sidebar:
                                st.success(f"Calendrier enregistré pour '{name}'.")
                            st.session_state["conseiller"] = name

                        st.button("✅", on_click=sauvegarder_quand_meme)

                    with c2:
                        if st.button("✖️"):
                            return
                    return

            data[name] = url

            with ics_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            st.success(f"Calendrier enregistré pour '{name}'.")
            st.session_state["conseiller"] = name

    with st.sidebar:
        st.text_input(
            "nom du conseiller",
            label_visibility="collapsed",
            key="nouveau_conseiller",
            placeholder="nom du conseiller",
            on_change=save_url_in_json,
        )


def find_dispos():
    lieu = Lieu(
        nom=st.session_state["selected_address_name"],
        mapbox_id=st.session_state["selected_mapbox_id"],
    )
    st.session_state["dispos"] = get_calendrier().trouver_dispo(
        lieu=lieu,
        semaine=st.session_state["week"],
        annee=st.session_state["year"],
        duree_rdv=st.session_state["duration"],
    )


def run_git_pull():
    """Return (exit_code, combined_output)."""
    cmd = ["git", "pull"]
    p = subprocess.run(
        cmd,
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
    )
    output = (
        (p.stdout or "") + ("\n" if p.stdout and p.stderr else "") + (p.stderr or "")
    )
    return p.returncode, output.strip()


def git_pull():
    with st.sidebar:
        with st.spinner("Running git pull..."):
            exit_code, output = run_git_pull()
            if exit_code == 0:
                st.success("Mise à jour réussie.")
            else:
                st.error("Erreur lors de la mise à jour :")
                st.code(output or "(no output)", language="bash")


# --- GLOBAL CSS FOR HEADER FIXES ---
st.markdown(
    """
<style>
/* Align buttons vertically */
.compact-button {
    padding: 0.25rem 0.5rem;
    margin-top: 1.25rem;  /* aligns with number_input labels */
}

/* Week range styling */
.week-range {
    text-align: right;
    font-size: 1.3rem;
    font-weight: 500;
    margin-top: 1.7rem;
    padding-right: 0.5rem;
    display: inline-block;
}

/* Prevent huge width stretching */
.limit-width {
    max-width: 550px;
}



/*realign the map button*/
.bouton-carte {
    margin-top: -16px;
}
</style>
""",
    unsafe_allow_html=True,
)


def inject_calendar_css():
    st.markdown(
        """
<style>
.calendar-wrapper{
  margin-top: 1rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background-color: #ffffff;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

/* Header with days */
.calendar-header-row{
  display: grid;
  grid-template-columns: 60px repeat(5, 1fr);
  background-color: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
}
.calendar-header-cell{
  padding: 6px 8px;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

/* Body: time column + 5 day columns */
.calendar-body-grid{
  display: grid;
  grid-template-columns: 60px repeat(5, 1fr);
  height: 720px; /* 12 hours * 60 min = 720px => 1px = 1 minute */
  position: relative;
  font-size: 11px;
}

/* Time labels column */
.time-column{
  position: relative;
  background: linear-gradient(to right, #f9fafb, #ffffff);
}
.time-label{
  position: absolute;
  right: 6px;
  transform: translateY(-50%);
  font-size: 11px;
  color: #6b7280;
}

/* Day columns */
.day-column{
  position: relative;
  border-left: 1px solid #f3f4f6;
  background-color: #f9fafb; /* off-hours color */
}

/* Working hours background (overrides off-hours) */
.working-hours{
  position: absolute;
  left: 0;
  right: 0;
  background-color: #ecfeff;
  z-index: 0;
}

/* Horizontal grid lines every ~30px (~30min) */
.grid-lines{
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
    to bottom,
    rgba(209,213,219,0.6) 0px,
    rgba(209,213,219,0.6) 1px,
    transparent 1px,
    transparent 29px
  );
  z-index: 1;
  pointer-events: none;
}

.calendar-time-range {
  position: absolute;
  left: 6%;
  right: 6%;
  padding: 4px 6px;
  border-radius: 4px;
  border-left: 4px solid;
  box-shadow: 0 1px 2px rgba(15,23,42,0.25);
  box-sizing: border-box;
}

/* RDVs */
.event{
  background-color: #99f6e4;
  border-left-color: #0d9488;
  z-index: 3;
}

/* Disponibilités */
.dispo{
  background-color: #bbf7d0;
  border-left-color: #16a34a;
  z-index: 2;  /* under events if they overlap */
  opacity: 0.85;
}

.best-dispo{
  border: 2px solid #16a34a;
  border-left: 4px solid #16a34a;
  box-shadow: 10px 1px 5px 1px rgba(22,163,74,0.60)
}

/* Temps de trajet */
.trajet{
    background-color: #F2DEAE;
    border-left-color: #d97706;
    z-index: 2;  /* under events if they overlap */
    opacity: 0.80;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-right: 7%;
}
.trajet-info {
    font-size: 10px;
    color: #6E2C09;
}

/* temps repas */
.repas{
    background-color: #FEFFB5;
    border-left-color: #CA8A04;
    z-index: 1;  /* under events if they overlap */
    opacity: 0.85;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-right: 7%;
}

.event-title{
  font-weight: 600;
  font-size: 11px;
  color: #111827;
}
.event-location{
  font-size: 11px;
  color: #064e3b;
}

.calendar-line {
  position: absolute;
  left: 6%;
  right: 6%;
  padding: 1px 1px;
  box-sizing: border-box;
  height: 3px;
  background-color:#0B852E;
  z-index: 4;
}
.calendar-line p {
  visibility: hidden;
  padding: 3px 6px;
  font-size: .65rem;
}
.calendar-line:hover p {
  visibility: visible;
}


</style>
        """,
        unsafe_allow_html=True,
    )


# ---------- HEADER UI ----------
def header():
    header_container = st.container()

    with header_container:
        left_col, right_col = st.columns([1, 1], gap="medium")

        # ====================
        # LEFT: WEEK SELECTOR
        # ====================
        with left_col:
            btn_col_prev, dates_col, col_year, col_week, btn_col_next = st.columns(
                [1, 3, 2, 2, 6]
            )

            # Previous week button
            with btn_col_prev:
                st.markdown('<div class="compact-button">', unsafe_allow_html=True)
                st.button("◀", key="prev_week", on_click=shift_week, args=(-1,))
                st.markdown("</div>", unsafe_allow_html=True)

            # Week date range
            with dates_col:
                year = st.session_state["year"]
                week = st.session_state["week"]

                week_start = date.fromisocalendar(year, week, 1)
                week_end = week_start + timedelta(days=5)

                txt = (
                    f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}"
                    if week_start.month != week_end.month
                    else f"{week_start.strftime('%d')}-{week_end.strftime('%d')} {week_start.strftime('%B')}"
                )

                st.markdown(
                    f'<span class="week-range">{txt}</span>', unsafe_allow_html=True
                )

            # Year
            with col_year:
                st.number_input(
                    "Année",
                    min_value=2000,
                    max_value=2100,
                    key="year_input",
                    on_change=sync_year_week,
                )

            # Week number
            with col_week:
                st.number_input(
                    "n° semaine",
                    min_value=1,
                    max_value=53,
                    key="week_input",
                    on_change=sync_year_week,
                )
            # Next week button
            with btn_col_next:
                st.markdown('<div class="compact-button">', unsafe_allow_html=True)
                st.button("▶", key="next_week", on_click=shift_week, args=(+1,))
                st.markdown("</div>", unsafe_allow_html=True)

        # ===========================
        # RIGHT: ADDRESS + DURATION
        # ===========================
        with right_col:
            addr_col, button_col, duration_col = st.columns([8, 1, 2])

            with addr_col:
                st.text_input(
                    "Recherche d'adresse",
                    key="address_query",
                    placeholder="Saisir une adresse…",
                    label_visibility="visible",
                    on_change=search_address,
                )

                # Suggestions
                options = st.session_state.get("address_options", [])
                if options:
                    labels = [
                        f"{opt['name']} - {opt['full_address']}" for opt in options
                    ]

                    selected_label = st.selectbox(
                        "Résultats",
                        labels,
                        key="select_address_label",
                    )

                    selected = next(
                        o
                        for o in options
                        if f"{o['name']} - {o['full_address']}" == selected_label
                    )

                    st.session_state["selected_mapbox_id"] = selected["mapbox_id"]
                    st.session_state["selected_address_name"] = selected["name"]

            # Search button (aligned)
            with button_col:
                st.markdown('<div class="compact-button">', unsafe_allow_html=True)
                st.button("🔍", key="search_address", on_click=search_address)
                st.markdown("</div>", unsafe_allow_html=True)

                # show on map button
                if st.session_state.get("selected_mapbox_id"):
                    lon, lat = geocode(st.session_state["selected_mapbox_id"])
                    url = f"https://www.google.com/maps/place/{lat},{lon}/@{lat},{lon},10z"
                    st.link_button("🗺️", url)

            # Duration
            with duration_col:
                st.text_input("Durée du rdv", key="duration")

                # Trouver dispos button
                st.button("Trouver dispos", key="find_dispos", on_click=find_dispos)


def calendar_body():
    inject_calendar_css()

    cal = get_calendrier()
    if cal is None:
        st.info("Calendrier non disponible.")
        return

    # --- Time range displayed (y-axis) ---
    DISPLAY_START_HOUR = 6  # 06:00
    DISPLAY_END_HOUR = 21  # 21:00
    total_minutes = (DISPLAY_END_HOUR - DISPLAY_START_HOUR) * 60

    def minutes_from_start(dt: datetime) -> int:
        return (dt.hour - DISPLAY_START_HOUR) * 60 + dt.minute

    def percent_from_dt(dt: datetime) -> float:
        mins = minutes_from_start(dt)
        mins = max(0, min(total_minutes, mins))
        return mins / total_minutes * 100

    # --- Week dates based on year/week in header ---
    year = st.session_state["year"]
    week = st.session_state["week"]
    monday = datetime.fromisocalendar(year, week, 1)

    # Dispos stored in session (list[Dispo])
    all_dispos = st.session_state.get("dispos", []) or []
    best_dispo = all_dispos[0] if all_dispos else None

    days = []
    for offset in range(5):  # lundi -> vendredi
        d = monday + timedelta(days=offset)
        label = f"{d.day} {d.strftime('%A')}"
        # Only real meetings (no "Début/Fin de journée" as those are created only in rdvs_de_la_journee)
        events = [rdv for rdv in cal.rendez_vous if rdv.debut.date() == d.date()]
        dispos = [dispo for dispo in all_dispos if dispo.debut.date() == d.date()]
        days.append({"date": d, "label": label, "events": events, "dispos": dispos})

    # --- Build HTML ---
    html = []
    html.append('<div class="calendar-wrapper">')

    # Header row
    html.append('<div class="calendar-header-row">')
    html.append('<div class="calendar-header-cell time-col-header"></div>')
    for day in days:
        html.append(f'<div class="calendar-header-cell">{day["label"]}</div>')
    html.append("</div>")  # end header row

    # Body grid
    html.append('<div class="calendar-body-grid">')

    # Time column
    html.append('<div class="time-column">')
    for hour in range(DISPLAY_START_HOUR, DISPLAY_END_HOUR + 1):
        mins = (hour - DISPLAY_START_HOUR) * 60
        pct_top = mins / total_minutes * 100
        label = f"{hour:02d}h"
        html.append(
            f'<div class="time-label" style="top:{pct_top}%;"><span>{label}</span></div>'
        )
    html.append("</div>")  # time column

    # Day columns
    for day in days:
        html.append('<div class="day-column">')

        # Working hours background (based on Calendrier config)
        ws = day["date"] + timedelta(seconds=cal.debut_journee)
        we = day["date"] + timedelta(seconds=cal.fin_journee)
        ws_pct = percent_from_dt(ws)
        we_pct = percent_from_dt(we)
        height_pct = max(0, we_pct - ws_pct)

        html.append(
            f'<div class="working-hours" style="top:{ws_pct}%;height:{height_pct}%;"></div>'
        )
        html.append('<div class="grid-lines"></div>')

        # Disponibilités
        for dispo in day["dispos"]:
            dispo_start_pct = percent_from_dt(dispo.debut)
            dispo_end_pct = percent_from_dt(dispo.fin)
            dispo_height_pct = max(0.8, dispo_end_pct - dispo_start_pct)
            temps_trajet_min = min([d.temps_trajet for d in all_dispos])
            temps_trajet_max = min(max([d.temps_trajet for d in all_dispos]), 4 * 3600)
            opacity = max(
                0.2, 1 - ((dispo.temps_trajet - temps_trajet_min) / temps_trajet_max)
            )
            if dispo == best_dispo:
                html.append(f"""
<div class="calendar-time-range dispo best-dispo" style="top:{dispo_start_pct}%;height:{dispo_height_pct}%;opacity:{opacity};">
  <div class="event-title">Disponible {dispo.debut.strftime("%H:%M")} - {dispo.fin.strftime("%H:%M")} ({to_hours_and_minutes((dispo.fin - dispo.debut).seconds)})</div>
  <div class="dispo-temps-rajoute">Temps de trajet rajouté : {to_hours_and_minutes(dispo.temps_trajet)}</div>
</div>
""")
            else:
                html.append(f"""
<div class="calendar-time-range dispo" style="top:{dispo_start_pct}%;height:{dispo_height_pct}%;opacity:{opacity};">
  <div class="event-title">Disponible {dispo.debut.strftime("%H:%M")} - {dispo.fin.strftime("%H:%M")} ({to_hours_and_minutes((dispo.fin - dispo.debut).seconds)})</div>
  <div class="dispo-temps-rajoute">Temps de trajet rajouté : {to_hours_and_minutes(dispo.temps_trajet)}</div>
</div>
""")

            last_start = dispo.fin - timedelta(
                seconds=to_seconds(st.session_state["duration"])
            )
            if last_start > dispo.debut + timedelta(hours=1):
                last_start_pct = percent_from_dt(last_start)
                # render a thin marker line indicating the last possible meeting start
                html.append(f"""
<div class="calendar-line" style="top:{last_start_pct}%;opacity:{opacity};">
  <p>Dernier début possible : {last_start.strftime("%H:%M")}</p>
</div>
""")

            meal_before_trajet = False
            if dispo.temps_repas > 0:
                # will the meal time overlap more the 12h to 14h range before or after the trajet ?
                debut_heures_repas = dispo.debut.date() + timedelta(
                    seconds=cal.heures_repas[0]
                )
                fin_heures_repas = dispo.debut.date() + timedelta(
                    seconds=cal.heures_repas[1]
                )
                overlap_before = intervals_overlap(
                    dispo.debut
                    - timedelta(seconds=dispo.temps_trajet_aller + dispo.temps_repas),
                    dispo.debut - timedelta(seconds=dispo.temps_trajet_aller),
                    debut_heures_repas,
                    fin_heures_repas,
                )
                overlap_after = intervals_overlap(
                    dispo.debut - timedelta(seconds=dispo.temps_repas),
                    dispo.debut,
                    debut_heures_repas,
                    fin_heures_repas,
                )
                meal_before_trajet = overlap_before > overlap_after
            if meal_before_trajet:
                # Repas first, then trajet aller
                repas_start_pct = percent_from_dt(
                    dispo.debut
                    - timedelta(seconds=dispo.temps_repas + dispo.temps_trajet_aller)
                )
                repas_end_pct = percent_from_dt(
                    dispo.debut - timedelta(seconds=dispo.temps_trajet_aller)
                )
                trajet_aller_start_pct = percent_from_dt(
                    dispo.debut - timedelta(seconds=dispo.temps_trajet_aller)
                )
                trajet_aller_end_pct = percent_from_dt(dispo.debut)
            else:
                # Trajet aller first, then repas
                trajet_aller_start_pct = percent_from_dt(
                    dispo.debut
                    - timedelta(seconds=dispo.temps_repas + dispo.temps_trajet_aller)
                )
                trajet_aller_end_pct = percent_from_dt(
                    dispo.debut - timedelta(seconds=dispo.temps_repas)
                )
                repas_start_pct = percent_from_dt(
                    dispo.debut - timedelta(seconds=dispo.temps_repas)
                )
                repas_end_pct = percent_from_dt(dispo.debut)

            trajet_aller_height_pct = max(
                0.8, trajet_aller_end_pct - trajet_aller_start_pct
            )
            html.append(f"""
<div class="calendar-time-range trajet" style="top:{trajet_aller_start_pct}%;height:{trajet_aller_height_pct}%;">
  <div class="event-title">Trajet aller</div>
  <div class="trajet-info">{to_hours_and_minutes(dispo.temps_trajet_aller)}</div>
</div>
""")
            # temps trajet retour
            trajet_retour_start_pct = percent_from_dt(dispo.fin)
            trajet_retour_end_pct = percent_from_dt(
                dispo.fin + timedelta(seconds=dispo.temps_trajet_retour)
            )
            trajet_retour_height_pct = max(
                0.8, trajet_retour_end_pct - trajet_retour_start_pct
            )

            html.append(f"""
<div class="calendar-time-range trajet" style="top:{trajet_retour_start_pct}%;height:{trajet_retour_height_pct}%;">
  <div class="event-title">Trajet retour</div>
  <div class="trajet-info">{to_hours_and_minutes(dispo.temps_trajet_retour)}</div>
</div>
""")

            # temps repas
            if dispo.temps_repas > 0:
                repas_height_pct = max(0.8, repas_end_pct - repas_start_pct)
                html.append(
                    f"""
<div class="calendar-time-range repas" style="top:{repas_start_pct}%;height:{repas_height_pct}%;">
  <div class="event-title">Repas</div>
  <div class="event-duration">{to_hours_and_minutes(dispo.temps_repas)}</div>
</div>
"""
                )

        # Events
        for ev in day["events"]:
            start_pct = percent_from_dt(ev.debut)
            end_pct = percent_from_dt(ev.fin)
            height_pct = max(0.8, end_pct - start_pct)  # min height for visibility

            title = (ev.titre or "").replace('"', "&quot;")
            debut = ev.debut.strftime("%H:%M")
            fin = (ev.debut + timedelta(seconds=ev.duree)).strftime("%H:%M")
            loc = (ev.lieu.nom or "").replace('"', "&quot;")

            html.append(f"""
<div class="calendar-time-range event" style="top:{start_pct}%;height:{height_pct}%;">
  <div class="event-title">{title} {debut} - {fin}</div>
  <div class="event-location">{loc}</div>
</div>
""")

        html.append("</div>")  # end day-column

    html.append("</div>")  # end body grid
    html.append("</div>")  # end wrapper

    st.markdown("\n".join(html), unsafe_allow_html=True)


def sidebar():
    with st.sidebar:
        st.button("Mettre à jour", key="maj", on_click=git_pull)

        st.markdown("### Paramètres")

        c1, c2, c3 = st.columns([1, 3, 1])
        with c1:
            st.text_input(
                "Conseiller",
                key="conseiller",
                on_change=update_calendar,
                args=(False,),
            )
        with c2:
            st.text_input(
                "URL",
                placeholder="https://mail.cimut.../calendar.ics",
                key="url_calendrier",
                on_change=update_calendar,
                args=(True,),
            )
        with c3:
            st.markdown('<div class="compact-button">', unsafe_allow_html=True)
            st.button("💾", key="save_url", on_click=save_url)
            st.markdown("</div>", unsafe_allow_html=True)

        st.text_input(
            "Début de journée",
            placeholder="8h",
            key="debut_journee",
            on_change=set_debut_journee,
        )

        st.text_input(
            "Fin de journée",
            placeholder="18h",
            key="fin_journee",
            on_change=set_fin_journee,
        )

        st.text_input(
            "Temps repas",
            placeholder="1h",
            key="temps_repas",
            on_change=set_temps_repas,
        )

        st.caption("Heures repas")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input(
                "debut",
                label_visibility="collapsed",
                placeholder="12h",
                key="debut_repas",
                on_change=set_heures_repas,
            )
        with c2:
            st.text_input(
                "fin",
                label_visibility="collapsed",
                placeholder="14h",
                key="fin_repas",
                on_change=set_heures_repas,
            )

        st.text_input(
            "Marge",
            placeholder="10min",
            key="marge",
            on_change=set_marge,
        )


# ---------- MAIN APP SKELETON ----------
def main():
    st.set_page_config(layout="wide")
    init_state()

    header()

    calendar_body()

    sidebar()


if __name__ == "__main__":
    main()
