from oracle.historique import Historique
from oracle.marche import Marche
from oracle.selection import choisir, est_joue, est_liquide, scorer, thematiser

H = 3600
T0 = 1_800_000_000


def marche(id="m", prob=50.0, source="kalshi", evenement=None, v_total=100_000,
           v_24h=1_000, parieurs=0, delta=None):
    m = Marche(source=source, id=id, evenement=evenement or id, titre=id, prob=prob,
               volume_total=v_total, volume_24h=v_24h, fin="2027-01-01", url="u",
               nb_parieurs=parieurs)
    m.delta_24h = delta
    return m


def test_pas_de_delta_le_premier_jour():
    h = Historique()
    h.enregistrer([marche(prob=40)], T0)
    assert h.delta_24h(marche(prob=55), T0 + 12 * H) is None


def test_delta_depuis_le_releve_d_il_y_a_24h():
    h = Historique()
    h.enregistrer([marche(prob=40)], T0)
    h.enregistrer([marche(prob=45)], T0 + 2 * H)     # trop récent pour servir
    assert h.delta_24h(marche(prob=55.5), T0 + 25 * H) == 15.5


def test_prend_le_plus_recent_des_releves_de_plus_de_24h():
    h = Historique()
    h.enregistrer([marche(prob=30)], T0)
    h.enregistrer([marche(prob=40)], T0 + 5 * H)
    assert h.delta_24h(marche(prob=50), T0 + 30 * H) == 10.0


def test_un_releve_de_plus_de_48h_ne_compte_pas():
    h = Historique()
    h.enregistrer([marche(prob=40)], T0)
    assert h.delta_24h(marche(prob=50), T0 + 49 * H) is None


def test_les_sources_ne_se_melangent_pas():
    h = Historique()
    h.enregistrer([marche(prob=10, source="manifold")], T0)
    assert h.delta_24h(marche(prob=50, source="kalshi"), T0 + 25 * H) is None


def test_purge_au_dela_de_sept_jours():
    h = Historique()
    h.enregistrer([marche(id="vieux")], T0)
    h.enregistrer([marche(id="neuf")], T0 + 8 * 24 * H)
    ids = [r[0] for r in h.base.execute("SELECT market_id FROM releves")]
    assert ids == ["neuf"]


def test_thematiser_classe_et_rejette_le_bruit_meme_thematique():
    lot = [marche("Will Trump attend the Super Bowl?"),       # USA, mais sport
           marche("Will Trump sign a tariff executive order?"),
           marche("Will it rain in Paris tomorrow?")]          # hors thèmes
    for m in lot:
        m.titre = m.id
    gardes = thematiser(lot)
    assert [m.id for m in gardes] == ["Will Trump sign a tariff executive order?"]
    assert gardes[0].categorie == "Politique USA"


def test_thematiser_rejette_une_categorie_source_exclue():
    m = marche("Will Macron attend the final?")
    m.titre, m.categorie_source = m.id, "Sports"
    assert thematiser([m]) == []


def test_liquidite_par_source():
    assert est_liquide(marche(v_total=50_000))
    assert not est_liquide(marche(v_total=49_999))
    assert not est_liquide(marche(source="manifold", v_total=30_000, parieurs=10))
    assert est_liquide(marche(source="manifold", v_total=30_000, parieurs=30))


def test_un_marche_extreme_est_joue_sauf_s_il_bouge():
    assert est_joue(marche(prob=98))
    assert est_joue(marche(prob=2))
    assert not est_joue(marche(prob=97))
    assert not est_joue(marche(prob=98, delta=4.0))
    assert not est_joue(marche(prob=2, delta=-6.0))
    assert est_joue(marche(prob=98, delta=3.9))


def test_le_score_suit_l_activite_et_la_variation():
    calme = marche("calme", v_24h=10)
    actif = marche("actif", v_24h=10_000)
    bouge = marche("bouge", v_24h=10, delta=-8.0)
    scorer([calme, actif, bouge])
    assert actif.score > calme.score
    assert bouge.score > calme.score


def test_une_alerte_monte_le_score():
    a, b = marche("a"), marche("b")
    b.alerte = {"amount_usd": 20_000}
    scorer([a, b])
    a2, b2 = marche("a"), marche("b")
    scorer([a2, b2])
    assert b.score - b2.score == 15


def test_manifold_pese_moins_que_kalshi_a_rang_egal():
    k, m = marche("k"), marche("m", source="manifold")
    scorer([k, m])
    assert k.score > m.score > 0


def test_choisir_limite_deux_marches_par_evenement():
    lot = [marche(f"c{i}", evenement="E") for i in range(5)] + [marche("autre")]
    for i, m in enumerate(lot):
        m.score = 100 - i
    choisis = choisir(lot, n=10)
    assert [m.id for m in choisis] == ["c0", "c1", "autre"]


def test_choisir_reserve_des_places_a_chaque_categorie():
    forts = [marche(f"usa{i}") for i in range(10)]
    faibles = [marche(f"rad{i}") for i in range(3)]
    for i, m in enumerate(forts):
        m.categorie, m.score = "USA", 100 - i
    for i, m in enumerate(faibles):
        m.categorie, m.score = "Radicaux", 10 - i
    choisis = choisir(forts + faibles, n=5, par_groupe=2)
    assert [m.id for m in choisis] == ["usa0", "usa1", "usa2", "rad0", "rad1"]
    # Sans réserve, le score seul écarte la catégorie faible.
    assert all(m.categorie == "USA" for m in choisir(forts + faibles, n=5))


def test_la_reserve_respecte_la_limite_par_evenement():
    lot = [marche(f"r{i}", evenement="E") for i in range(3)] + [marche("u")]
    for i, m in enumerate(lot):
        m.categorie, m.score = "R", 10 - i
    lot[-1].categorie, lot[-1].score = "U", 100
    assert [m.id for m in choisir(lot, n=10, par_groupe=3)] == ["u", "r0", "r1"]


def test_choisir_garde_les_meilleurs_scores():
    lot = [marche(str(i)) for i in range(40)]
    for i, m in enumerate(lot):
        m.score = i
    assert [m.id for m in choisir(lot, n=3)] == ["39", "38", "37"]
