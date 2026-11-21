import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle import meteo, point_matinal as pm
from oracle.http import ErreurReseau

# Vraie réponse d'Open-Meteo relevée le 21/11/2026, emplacement remplacé (dépôt public) :
# 21/11 code 80, 4,8 à 8,8 °C, 0,8 mm (70 %) ; 22/11 code 61, 2,2 à 4,8 °C, 14,65 mm (90 %).
REPONSE = json.loads((Path(__file__).parent / "fixtures" / "meteo_exemple.json").read_text())
MATIN = datetime(2026, 11, 21, 6, 5, tzinfo=timezone.utc)       # 7 h 05 à Paris
SOIR = datetime(2026, 11, 21, 18, 5, tzinfo=timezone.utc)       # 19 h 05 à Paris


def test_le_matin_on_annonce_aujourd_hui():
    assert meteo.phrase(REPONSE, "Ville", MATIN) == (
        "**Météo à Ville, aujourd’hui** : averses, 4,8 à 8,8 °C, 0,8 mm "
        "(pluie probable à 70 %).")


def test_le_soir_on_annonce_demain():
    assert meteo.phrase(REPONSE, "Ville", SOIR) == (
        "**Météo à Ville, demain** : pluie faible, 2,2 à 4,8 °C, 14,7 mm "
        "(pluie probable à 90 %).")


def test_pas_de_pluie_ni_de_vent_a_signaler():
    donnees = {"daily": {"time": ["2026-11-21"], "weather_code": [0], "temperature_2m_min": [1.0],
                         "temperature_2m_max": [6.0], "precipitation_sum": [0.2],
                         "precipitation_probability_max": [10], "wind_gusts_10m_max": [30.0]}}
    assert meteo.phrase(donnees, "Ici", MATIN) == "**Météo à Ici, aujourd’hui** : ciel dégagé, 1 à 6 °C."


def test_les_fortes_rafales_sont_signalees():
    donnees = json.loads(json.dumps(REPONSE))
    donnees["daily"]["wind_gusts_10m_max"][0] = 72.4
    assert "rafales jusqu'à 72 km/h" in meteo.phrase(donnees, "Ici", MATIN)


def test_le_jour_absent_ne_donne_rien():
    lendemain_seul = {"daily": {"time": ["2026-11-25"], "weather_code": [0],
                                "temperature_2m_min": [1], "temperature_2m_max": [2]}}
    assert meteo.phrase(lendemain_seul, "Ici", MATIN) is None
    assert meteo.phrase({}, "Ici", MATIN) is None


@pytest.mark.parametrize("variable, attendu", [
    ("45.0,5.0,Ville", (45.0, 5.0, "Ville")),
    ("45.0, 5.0", (45.0, 5.0, "chez toi")),
    ("", None), ("Ville", None), ("91,7", None), ("a,b,c", None),
])
def test_le_lieu_vient_du_secret(variable, attendu):
    assert meteo.lieu(variable) == attendu


def test_sans_lieu_pas_de_meteo_et_pas_d_appel():
    def get(*a, **k):
        raise AssertionError("aucun appel sans lieu")
    assert meteo.du_jour(MATIN, get=get, variable="") == (None, None)


def test_une_panne_est_signalee_sans_rien_casser():
    def get(*a, **k):
        raise ErreurReseau("503")
    texte, erreur = meteo.du_jour(MATIN, get=get, variable="48.5,7.6,Ici")
    assert texte is None and "503" in erreur


def test_la_requete_demande_le_bon_lieu_en_heure_de_paris():
    vus = []

    def get(url, params):
        vus.append(params)
        return REPONSE
    texte, erreur = meteo.du_jour(MATIN, get=get, variable="45.0,5.0,Ville")
    assert erreur is None and texte.startswith("**Météo à Ville, aujourd’hui**")
    assert vus[0]["latitude"] == 45.0 and vus[0]["timezone"] == "Europe/Paris"


def test_la_meteo_ouvre_le_point():
    briefing = {"meta": {"generated_at": "2026-11-21T06:00:00+00:00", "total_scanned": 1, "errors": {}},
                "markets": []}
    texte, _ = pm.composer(briefing, MATIN, court=True, meteo="**Météo à Ici, aujourd’hui** : pluie.")
    assert texte.index("**Météo à Ici") < texte.index("## Les 5 choses à savoir")
    sans, _ = pm.composer(briefing, MATIN, court=True)
    assert "Météo" not in sans


def test_la_bascule_vers_demain_se_fait_a_17_h_heure_de_paris():
    # 16 h 30 UTC = 17 h 30 à Paris (hiver) : déjà « demain » ; 15 h 30 UTC = 16 h 30 : « aujourd'hui ».
    assert ", demain**" in meteo.phrase(REPONSE, "Ici", datetime(2026, 11, 21, 16, 30, tzinfo=timezone.utc))
    assert "aujourd’hui**" in meteo.phrase(REPONSE, "Ici", datetime(2026, 11, 21, 15, 30, tzinfo=timezone.utc))
