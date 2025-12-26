import locale
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import pairwise

import requests
from ics import Calendar

from mapbox import driving_time_between, geocode, suggestions
from utils import intervals_overlap, to_seconds

_EXEC = ThreadPoolExecutor(max_workers=12)


def set_french_time_locale():
    for loc in ("fr_FR", "fr_FR.UTF-8", "fr_FR.utf8", "French_France.1252"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            return loc
        except locale.Error:
            pass
    # If none available, keep default "C" locale (no crash)
    return None


set_french_time_locale()


class Lieu:
    def __init__(
        self,
        nom: str | None = None,
        lon: float | None = None,
        lat: float | None = None,
        mapbox_id: str | None = None,
    ):
        if nom is not None:
            if "teams" in nom.lower():
                nom = None

        if nom is None:
            # par défaut
            self.lon = -1.0842812946932405
            self.lat = 49.11306395733223
            self.nom = "Siège Mutame St Lô"
        elif mapbox_id is not None and (lon is None or lat is None):
            # Que l'id du lieu est fourni (après une recherche)
            self.lon, self.lat = geocode(mapbox_id)
            if nom is not None:
                self.nom = nom
            else:
                raise ValueError("Le nom du lieu doit être fourni avec le mapbox_id")
            return
        elif nom is not None and (lon is None or lat is None):
            # Que le nom de la ville est fourni
            mapbox_id = suggestions(nom, limit=1)[0]["mapbox_id"]
            self.lon, self.lat = geocode(mapbox_id)
            self.nom = nom
        else:
            # Tous les paramètres sont fournis
            self.lon = lon
            self.lat = lat
            self.nom = nom

    def __str__(self):
        return f"{self.nom} (lon: {self.lon}, lat: {self.lat})"


class Rdv:
    def __init__(
        self,
        titre: str,
        lieu: Lieu,
        debut: datetime,
        duree: str | int = "1h30",  # ou en secondes
    ):
        self.titre = titre
        self.lieu = lieu
        self.debut = debut
        self.duree = (
            to_seconds(duree) if isinstance(duree, str) else duree
        )  # en secondes
        self.fin = debut + timedelta(seconds=self.duree)

    def __str__(self):
        date = self.debut.strftime("%A %d %b %Y")
        heure_debut = self.debut.strftime("%H:%M")
        heure_fin = self.fin.strftime("%H:%M")
        return f"{self.titre}, {date} : {heure_debut} - {heure_fin}, à {self.lieu.nom}"


class Dispo:
    def __init__(
        self,
        debut: datetime,
        fin: datetime,
        temps_trajet_aller: int,
        temps_trajet_retour: int,
        temps_repas: int,
    ):
        self.debut = debut
        self.fin = fin
        self.temps_trajet_aller = temps_trajet_aller
        self.temps_trajet_retour = temps_trajet_retour
        self.temps_repas = temps_repas
        self.temps_trajet = temps_trajet_aller + temps_trajet_retour

    def __str__(self):
        return f"Dispo de {self.debut.strftime('%A %d %b %Y %H:%M')} à {self.fin.strftime('%H:%M')}"

    def __lt__(self, other):
        return self.temps_trajet < other.temps_trajet

    def __eq__(self, other):
        if not isinstance(other, Dispo):
            return NotImplemented
        # comparer datetimes et valeurs numériques (tolérance pour floats)
        tol = 1e-6
        return (
            self.debut == other.debut
            and self.fin == other.fin
            and abs(float(self.temps_trajet_aller) - float(other.temps_trajet_aller))
            < tol
            and abs(float(self.temps_trajet_retour) - float(other.temps_trajet_retour))
            < tol
            and abs(float(self.temps_repas) - float(other.temps_repas)) < tol
        )


class Calendrier:
    def __init__(
        self,
        debut_journee: int = 8 * 3600,  # 8h
        fin_journee: int = 18 * 3600,  # 18h
        marge: int = 600,  # 10 minutes en secondes
        temps_repas: int = 3600,  # 1 heure en secondes
        heures_repas: list[int] = [12 * 3600, 14 * 3600],  # entre 12h et 14h
    ):
        self.rendez_vous = []
        self.debut_journee = debut_journee
        self.fin_journee = fin_journee
        self.marge = marge
        self.temps_repas = temps_repas
        self.heures_repas = heures_repas

    def __str__(self):
        return "\n".join(str(rdv) for rdv in self.rendez_vous)

    def charger_ics(
        self,
        url: str,
    ):
        response = requests.get(url)
        response.raise_for_status()
        c = Calendar(response.text)
        for event in c.events:
            titre = event.name or "Rendez-vous sans titre"
            lieu = Lieu(event.location) if event.location else Lieu()
            debut = event.begin.datetime.replace(tzinfo=None)
            duree = int(event.duration.total_seconds())

            rdv = Rdv(titre, lieu, debut, duree)
            self.rendez_vous.append(rdv)

    def trouver_dispo(
        self,
        lieu: Lieu,
        semaine: int,
        annee: int = 2025,
        duree_rdv: int | str = "1h30",  # ou en secondes
    ):
        duree_rdv = (
            to_seconds(duree_rdv) if isinstance(duree_rdv, str) else duree_rdv
        )  # en secondes

        dispos = []
        debut_semaine = datetime.strptime(f"{annee}-W{semaine - 1}-1", "%Y-W%W-%w")

        tasks = {}  # key -> future
        meta = []  # list of (jour, rdv_prec, rdv_suiv) so we can compute later
        i = 0

        for jour in range(5):
            date_jour = debut_semaine + timedelta(days=jour)
            rdvs_jour = self.rdvs_de_la_journee(date_jour)

            for rdv_prec, rdv_suiv in pairwise(rdvs_jour):
                meta.append((jour, date_jour, rdv_prec, rdv_suiv))

                k1 = ("aller", i)
                k2 = ("retour", i)
                i += 1

                tasks[k1] = _EXEC.submit(
                    driving_time_between,
                    rdv_prec.lieu,
                    lieu,
                    rdv_prec.fin + timedelta(minutes=5),
                    None,
                )
                tasks[k2] = _EXEC.submit(
                    driving_time_between,
                    lieu,
                    rdv_suiv.lieu,
                    None,
                    rdv_suiv.debut - timedelta(minutes=5),
                )
        results = {k: fut.result() for k, fut in tasks.items()}

        for i, (jour, date_jour, rdv_prec, rdv_suiv) in enumerate(meta):
            creu_s = int((rdv_suiv.debut - rdv_prec.fin).total_seconds())

            temps_trajet_aller_s, _ = results[("aller", i)]
            temps_trajet_retour_s, _ = results[("retour", i)]
            # 10% en plus sur les temps de trajet
            temps_trajet_aller_s = temps_trajet_aller_s * 1.10
            temps_trajet_retour_s = temps_trajet_retour_s * 1.10

            if intervals_overlap(
                rdv_prec.debut,
                rdv_prec.debut + timedelta(seconds=temps_trajet_aller_s + duree_rdv),
                date_jour + timedelta(seconds=self.heures_repas[0]),
                date_jour + timedelta(seconds=self.heures_repas[1]),
            ) or intervals_overlap(
                rdv_suiv.debut - timedelta(seconds=temps_trajet_retour_s + duree_rdv),
                rdv_suiv.debut,
                date_jour + timedelta(seconds=self.heures_repas[0]),
                date_jour + timedelta(seconds=self.heures_repas[1]),
            ):
                temps_repas_s = self.temps_repas
            else:
                temps_repas_s = 0

            temps_total_s = (
                duree_rdv + temps_trajet_aller_s + temps_trajet_retour_s + temps_repas_s
            )
            if creu_s < temps_total_s + self.marge:
                continue

            debut = (
                rdv_prec.fin
                + timedelta(seconds=temps_trajet_aller_s)
                + timedelta(seconds=temps_repas_s)
            )
            fin = rdv_suiv.debut - timedelta(seconds=temps_trajet_retour_s)
            dispo = Dispo(
                debut,
                fin,
                temps_trajet_aller_s,
                temps_trajet_retour_s,
                temps_repas_s,
            )
            dispos.append(dispo)

        dispos.sort()  # Tri par temps de trajet rajouté
        return dispos

    def rdvs_de_la_journee(self, date: datetime):
        debut_journee = Rdv(
            "Début de journée",
            Lieu(),
            date + timedelta(seconds=self.debut_journee),
            duree=0,
        )
        rdvs_jour = [rdv for rdv in self.rendez_vous if rdv.debut.date() == date.date()]
        fin_journee = Rdv(
            "Fin de journée",
            Lieu(),
            date + timedelta(seconds=self.fin_journee),
            duree=0,
        )
        rdvs_jour.insert(0, debut_journee)
        rdvs_jour.append(fin_journee)
        rdvs_jour.sort(key=lambda r: r.debut)
        return rdvs_jour


if __name__ == "__main__":
    cal = Calendrier()
    cal.charger_ics()

    print("Rendez-vous chargés :")
    print(cal)
    print("\nDispos pour Bayeux, semaine 50 :")
    dispos = cal.trouver_dispo("mairie Bayeux", semaine=50)
    for dispo in dispos:
        print(dispo)
