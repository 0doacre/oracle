from datetime import datetime, timezone

from oracle import point_matinal as pm
from oracle.collecteur import series_7_jours
from oracle.courbes import mini_courbe, par_heure
from oracle.historique import Historique
from oracle.marche import Marche

H = 3600
T0 = 1_800_000_000


def test_par_heure_prend_le_dernier_prix_de_chaque_heure_et_comble_les_trous():
    points = [(T0 + 60, 40.0), (T0 + 1800, 42.0), (T0 + 2 * H + 10, 50.0)]
    assert par_heure(points, T0, T0 + 3 * H) == [(T0, 42.0), (T0 + H, 42.0), (T0 + 2 * H, 50.0)]


def test_par_heure_ne_dessine_rien_avant_le_premier_releve():
    assert par_heure([(T0 + 2 * H, 50.0)], T0, T0 + 3 * H) == [(T0 + 2 * H, 50.0)]


def test_une_hausse_monte_et_une_baisse_descend():
    assert mini_courbe([10, 20, 30, 40]) == "▁▃▆█"
    assert mini_courbe([40, 30, 20, 10]) == "█▆▃▁"


def test_un_petit_frisson_reste_presque_plat():
    # 0,4 point de bruit ne doit pas ressembler à un effondrement.
    courbe = mini_courbe([50.0, 50.4, 50.0, 50.2])
    assert set(courbe) <= {"▄", "▅"}


def test_trop_peu_de_points_pas_de_courbe():
    assert mini_courbe([50, 51]) == ""


def test_la_mini_courbe_suit_le_prix_dans_le_point():
    m = {"title": "AI bubble burst in 2026?", "yes_prob": 63.0, "source": "polymarket",
         "sparkline_24h": "▇▇▆▃▁"}
    assert pm._phrase(m).startswith("« AI bubble burst in 2026? » : 63 % au OUI ▇▇▆▃▁ (polymarket)")
    m["sparkline_24h"] = ""
    assert "OUI (polymarket)" in pm._phrase(m)


def test_les_series_de_la_page_sur_sept_jours():
    h = Historique()
    marche = Marche(source="kalshi", id="K", evenement="K", titre="t", prob=0, volume_total=0,
                    volume_24h=0, fin="", url="")
    for heures_avant, prob in [(8 * 24, 10.0), (48, 20.0), (1, 30.0), (0, 35.0)]:
        marche.prob = prob
        h.enregistrer([marche], T0 - heures_avant * H)
    donnees = {"markets": [{"source": "kalshi", "id": "K", "title": "Titre", "dossier": "Iran"},
                           {"source": "kalshi", "id": "inconnu", "title": "x", "dossier": None}]}
    courbes = series_7_jours(donnees, h, datetime.fromtimestamp(T0, tz=timezone.utc))
    assert list(courbes["series"]) == ["kalshi:K"]           # pas de série vide
    serie = courbes["series"]["kalshi:K"]
    assert serie["title"] == "Titre" and serie["dossier"] == "Iran"
    valeurs = [v for _, v in serie["points"]]
    assert 10.0 not in valeurs                                # plus de 7 jours : hors série
    assert valeurs[0] == 20.0 and valeurs[-1] == 35.0
    assert len(valeurs) == 49                                 # de -48 h à maintenant, heure par heure
