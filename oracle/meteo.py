"""La météo du jour (ou du lendemain, pour le point de 19 h), par Open-Meteo :
gratuit, sans clé. Le lieu n'est jamais dans le dépôt (public) : il vient du secret
GitHub ORACLE_METEO, au format « latitude,longitude,nom ».
"""

import os
from datetime import datetime

from oracle.http import ErreurReseau, get_json
from oracle.temps import a_paris

API = "https://api.open-meteo.com/v1/forecast"
VARIABLES = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
             "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max")
HEURE_LENDEMAIN = 17        # à partir de 17 h, on annonce le lendemain
RAFALES_A_SIGNALER_KMH = 50

# Codes météo de l'OMM (WMO), regroupés comme Open-Meteo les documente.
CODES = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine", 55: "bruine dense",
    56: "bruine verglaçante", 57: "bruine verglaçante dense",
    61: "pluie faible", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "forte pluie verglaçante",
    71: "neige faible", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses", 81: "averses fortes", 82: "averses violentes",
    85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grêle", 99: "orage avec forte grêle",
}


def lieu(variable: str | None = None) -> tuple[float, float, str] | None:
    """(latitude, longitude, nom) depuis ORACLE_METEO, ou None s'il est absent ou mal formé."""
    texte = variable if variable is not None else os.environ.get("ORACLE_METEO", "")
    morceaux = [m.strip() for m in texte.split(",", 2)]
    if len(morceaux) < 2:
        return None
    try:
        lat, lon = float(morceaux[0]), float(morceaux[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon, (morceaux[2] if len(morceaux) == 3 and morceaux[2] else "chez toi")


def prevision(lat: float, lon: float, get=get_json) -> dict:
    return get(API, {"latitude": lat, "longitude": lon, "daily": VARIABLES,
                     "timezone": "Europe/Paris", "forecast_days": 2})


def _nombre(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def phrase(donnees: dict, nom: str, maintenant: datetime) -> str | None:
    """« **Météo à Ville, demain** : pluie, 2 à 5 °C, 15 mm (pluie
    probable à 90 %). » None si la réponse ne contient pas le jour voulu."""
    local = a_paris(maintenant)
    demain = local.hour >= HEURE_LENDEMAIN
    jour = local.date().toordinal() + (1 if demain else 0)
    quotidien = donnees.get("daily") or {}
    dates = quotidien.get("time") or []
    try:
        i = [datetime.fromisoformat(d).date().toordinal() for d in dates].index(jour)
        code = quotidien["weather_code"][i]
        mini, maxi = quotidien["temperature_2m_min"][i], quotidien["temperature_2m_max"][i]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if mini is None or maxi is None:
        return None
    texte = (f"**Météo à {nom}, {'demain' if demain else 'aujourd’hui'}** : "
             f"{CODES.get(code, 'temps variable')}, {_nombre(mini)} à {_nombre(maxi)} °C")

    def valeur(cle):
        serie = quotidien.get(cle) or []
        return serie[i] if i < len(serie) else None

    pluie, probabilite = valeur("precipitation_sum"), valeur("precipitation_probability_max")
    if pluie and pluie >= 0.5:
        texte += f", {_nombre(pluie)} mm"
        if probabilite is not None:
            texte += f" (pluie probable à {probabilite} %)"
    rafales = valeur("wind_gusts_10m_max")
    if rafales is not None and rafales >= RAFALES_A_SIGNALER_KMH:
        texte += f", rafales jusqu'à {round(rafales)} km/h"
    return texte + "."


def du_jour(maintenant: datetime, get=get_json, variable: str | None = None) -> tuple[str | None, str | None]:
    """(phrase, erreur). Sans lieu configuré : (None, None), en silence."""
    ou = lieu(variable)
    if ou is None:
        return None, None
    lat, lon, nom = ou
    try:
        texte = phrase(prevision(lat, lon, get), nom, maintenant)
    except ErreurReseau as e:
        return None, str(e)[:200]
    return texte, None if texte else "réponse sans le jour demandé"
