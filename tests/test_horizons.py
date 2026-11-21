"""Étape 1 : ce qui se joue aujourd'hui (variations 1 h / 6 h, pics de volume,
échéances proches)."""

from datetime import date

from oracle.historique import Historique
from oracle.marche import Marche
from oracle.selection import est_joue, est_pic_de_volume, horizons_confirmes, mouvement, scorer

H = 3600
T0 = 1_800_000_000
AUJOURD_HUI = date(2026, 11, 22)


def marche(id="m", prob=50.0, v_24h=50_000.0, fin="2027-06-01"):
    return Marche(source="kalshi", id=id, evenement=id, titre=id, prob=prob,
                  volume_total=100_000, volume_24h=v_24h, fin=fin, url="u")


def test_trois_horizons_depuis_les_releves_horaires():
    h = Historique()
    for heures_avant, prob in [(30, 20), (24, 30), (6, 40), (1, 45)]:
        h.enregistrer([marche(prob=prob)], T0 - heures_avant * H)
    m = marche(prob=50)
    h.annoter(m, T0)
    assert (m.delta_1h, m.delta_6h, m.delta_24h) == (5.0, 10.0, 20.0)


def test_un_releve_horaire_en_retard_compte_encore_pour_1h():
    h = Historique()
    h.enregistrer([marche(prob=40)], T0 - int(1.8 * H))   # exécution GitHub retardée
    assert h.variation(marche(prob=50), T0, "1h") == 10.0


def test_sans_releve_dans_la_fenetre_pas_de_variation():
    h = Historique()
    h.enregistrer([marche(prob=40)], T0 - 3 * H)
    m = marche(prob=50)
    h.annoter(m, T0)
    assert (m.delta_1h, m.delta_6h, m.delta_24h) == (None, None, None)


def test_pic_de_volume_contre_la_mediane_des_jours_precedents():
    h = Historique()
    for jours, v in [(3, 1_000), (2, 1_200), (1, 800)]:
        h.enregistrer([marche(v_24h=v)], T0 - jours * 24 * H)
    m = marche(v_24h=4_000)
    h.annoter(m, T0)
    assert m.ratio_volume == 4.0 and est_pic_de_volume(m)
    m = marche(v_24h=2_000)
    h.annoter(m, T0)
    assert m.ratio_volume == 2.0 and not est_pic_de_volume(m)


def test_pas_de_ratio_de_volume_sans_assez_d_historique():
    h = Historique()
    h.enregistrer([marche()], T0 - 3 * 24 * H)
    h.enregistrer([marche()], T0 - 2 * 24 * H)
    h.enregistrer([marche()], T0 - 2 * H)        # trop récent pour servir de base
    m = marche(v_24h=9_000)
    h.annoter(m, T0)
    assert m.ratio_volume is None


def test_le_mouvement_retient_l_horizon_le_plus_marquant():
    m = marche()
    m.delta_1h, m.delta_6h, m.delta_24h = 2.0, -3.0, 4.0
    assert mouvement(m) == 6.0          # 2 pt en 1 h ≈ 6 pt en 24 h
    m.delta_1h = None
    assert mouvement(m) == 4.5          # 3 pt en 6 h ≈ 4,5 pt en 24 h
    assert mouvement(marche()) == 0.0


def test_un_marche_extreme_qui_bouge_dans_l_heure_n_est_pas_joue():
    m = marche(prob=98)
    assert est_joue(m)
    m.delta_1h = -3.0
    assert not est_joue(m)
    m.delta_1h, m.delta_6h = None, 4.0
    assert not est_joue(m)


def scores(*marches):
    scorer(list(marches), AUJOURD_HUI)
    return [m.score for m in marches]


def test_une_echeance_proche_monte_le_score():
    loin, semaine, demain = marche("a"), marche("b", fin="2026-11-28"), marche("c", fin="2026-11-23")
    s_loin, s_semaine, s_demain = scores(loin, semaine, demain)
    assert s_semaine - s_loin == 8
    assert s_demain - s_loin == 15


def test_une_echeance_passee_ne_compte_pas_comme_proche():
    passe, loin = marche("a", fin="2026-11-20"), marche("b")
    s_passe, s_loin = scores(passe, loin)
    assert s_passe == s_loin


def test_des_volumes_egaux_ont_le_meme_rang():
    a, b, c = marche("a"), marche("b"), marche("c")
    assert len(set(scores(a, b, c))) == 1


def test_un_mouvement_dans_l_heure_monte_le_score():
    calme, bouge = marche("a"), marche("b")
    bouge.delta_1h = 3.0
    s_calme, s_bouge = scores(calme, bouge)
    assert s_bouge - s_calme >= 25


def test_un_pic_de_volume_monte_le_score():
    normal, pic = marche("a"), marche("b")
    pic.ratio_volume = 5.0
    s_normal, s_pic = scores(normal, pic)
    assert s_pic - s_normal >= 10


def test_jours_restants():
    assert marche(fin="2026-11-22").jours_restants(AUJOURD_HUI) == 0
    assert marche(fin="2026-11-25").jours_restants(AUJOURD_HUI) == 3
    assert marche(fin="").jours_restants(AUJOURD_HUI) is None


def test_un_mouvement_court_sur_un_marche_peu_echange_n_est_pas_confirme():
    # Cas réel du 21/11 : Powell −4 pt en 1 h sur 1 722 $ échangés en 24 h.
    m = marche(v_24h=1_722)
    m.delta_1h, m.delta_6h, m.delta_24h = -4.0, -4.0, 1.0
    assert horizons_confirmes(m) == ["delta_24h"]
    assert mouvement(m) == 1.0
    m.volume_24h = 20_000
    assert horizons_confirmes(m) == ["delta_1h", "delta_6h", "delta_24h"]
    assert mouvement(m) == 12.0


def test_une_variation_inconnue_n_est_pas_confirmee():
    m = marche()
    m.delta_24h = 2.0
    assert horizons_confirmes(m) == ["delta_24h"]
