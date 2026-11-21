from datetime import datetime, timezone

import pytest
from conftest import charger

from oracle.marche import Marche
from oracle.sources import polymarket
from oracle.sources.polymarket import (Polymarket, plus_gros_ordre, probabilite_oui,
                                       profil_portefeuille, vers_marche)

MAINTENANT = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
TS = int(MAINTENANT.timestamp())
J = 86_400


def test_lit_les_vrais_evenements_et_ecarte_le_bruit(reseau):
    source = Polymarket(get=reseau, pause=lambda s: None)
    marches = source.collecter()
    evenements = charger("polymarket_events.json")["events"]
    assert source.total_scanne == sum(len(e["markets"]) for e in evenements)
    assert marches
    exclus = {e["id"] for e in evenements
              if {t["label"] for t in e.get("tags") or []} & polymarket.ETIQUETTES_EXCLUES}
    assert exclus, "la fixture devrait contenir des événements exclus"
    assert not {m.evenement for m in marches} & {str(i) for i in exclus}
    for m in marches:
        assert m.id.startswith("0x") and 0 <= m.prob <= 100
        assert m.url.startswith("https://polymarket.com/event/")


def test_les_chaines_json_sont_decodees():
    m = {"outcomes": '["Yes", "No"]', "outcomePrices": '["0.235", "0.765"]'}
    assert probabilite_oui(m) == 23.5
    m = {"outcomes": '["No", "Yes"]', "outcomePrices": '["0.8", "0.2"]'}
    assert probabilite_oui(m) == 20.0


def test_un_marche_a_plus_de_deux_issues_ou_sans_yes_est_ignore():
    assert probabilite_oui({"outcomes": '["A", "B", "C"]', "outcomePrices": '["1","0","0"]'}) is None
    assert probabilite_oui({"outcomes": '["Up", "Down"]', "outcomePrices": '["0.5","0.5"]'}) is None


def test_un_marche_ferme_dans_un_evenement_ouvert_est_ignore():
    m = {"conditionId": "0x1", "closed": True, "outcomes": '["Yes","No"]',
         "outcomePrices": '["0.5","0.5"]'}
    assert vers_marche({"id": 1, "slug": "s"}, m) is None


def test_suit_le_curseur_jusqu_a_la_fin():
    pages = iter([{"events": [], "next_cursor": "a"}, {"events": [], "next_cursor": None}])
    curseurs = []

    def get(url, params=None):
        curseurs.append(params.get("after_cursor"))
        return next(pages)

    Polymarket(get=get, pause=lambda s: None).collecter()
    assert curseurs == [None, "a"]


def trade(montant, issue="Yes", cote="BUY", condition="0xC", ts=TS - 3600, wallet="0xW"):
    return {"condition_id": condition, "size": montant / 0.5, "price": 0.5, "outcome": issue,
            "side": cote, "timestamp": ts, "proxy_wallet": wallet}


@pytest.mark.parametrize("issue, cote, attendu", [
    ("Yes", "BUY", "YES"), ("Yes", "SELL", "NO"), ("No", "BUY", "NO"), ("No", "SELL", "YES")])
def test_le_cote_parie(issue, cote, attendu):
    assert plus_gros_ordre([trade(20_000, issue, cote)], "0xC")["side"] == attendu


def test_le_plus_gros_ordre_ignore_les_autres_marches_et_les_vieux_ordres():
    trades = [trade(50_000, condition="0xAUTRE"), trade(40_000, ts=TS - 2 * J),
              trade(15_000), trade(12_000)]
    ordre = plus_gros_ordre(trades, "0xC", depuis_ts=TS - J)
    assert ordre["amount_usd"] == 15_000


def test_sous_le_seuil_pas_d_ordre():
    assert plus_gros_ordre([trade(9_999)], "0xC") is None


def test_plus_gros_ordre_sur_les_vraies_transactions(monkeypatch):
    trades = charger("polymarket_trades.json")["data"]
    condition = trades[0]["condition_id"]
    attendu = max(t["size"] * t["price"] for t in trades)
    monkeypatch.setattr(polymarket, "SEUIL_GROS_ORDRE_USD", 1_000)
    assert plus_gros_ordre(trades, condition)["amount_usd"] == round(attendu, 2)


def activite(jours, condition="0xC", usdc=100.0):
    return {"timestamp": TS - jours * J, "condition_id": condition, "usdc_size": usdc}


def test_profil_recent():
    acts = [activite(5, "0xA"), activite(3, "0xB")]
    assert profil_portefeuille(acts, "0xC", MAINTENANT) == "Wallet récent"


def test_profil_concentre():
    acts = [activite(400, "0xC", 900), activite(300, "0xA", 100)]
    assert profil_portefeuille(acts, "0xC", MAINTENANT) == "Wallet concentré"


def test_profil_recent_et_concentre():
    assert profil_portefeuille([activite(2)], "0xC", MAINTENANT) == "Wallet récent / Wallet concentré"


def test_profil_ordinaire():
    acts = [activite(400, "0xA", 900), activite(300, "0xC", 100)]
    assert profil_portefeuille(acts, "0xC", MAINTENANT) is None


def test_un_historique_tronque_ne_dit_pas_recent(monkeypatch):
    # 3 activités récentes lues sur 3 permises : on ne voit pas le début de l'historique.
    monkeypatch.setattr(polymarket, "HISTORIQUE_PORTEFEUILLE", 3)
    acts = [activite(2, "0xA"), activite(1, "0xB"), activite(1, "0xD")]
    assert profil_portefeuille(acts, "0xC", MAINTENANT) is None


def marche(volume_24h):
    return Marche(source="polymarket", id="0xC", evenement="E", titre="t", prob=50,
                  volume_total=1e6, volume_24h=volume_24h, fin="", url="")


def faux_reseau(trades, activites):
    def get(url, params=None):
        if url.endswith("/trades"):
            assert params["condition"] == "0xC"
            return {"data": trades}
        return {"data": activites}
    return get


def test_alerte_si_l_ordre_pese_lourd_dans_le_volume_du_jour():
    source = Polymarket(get=faux_reseau([trade(30_000)], [activite(400, "0xA")]))
    alerte = source.alerte(marche(volume_24h=60_000), MAINTENANT)
    assert alerte["share_24h"] == 0.5 and alerte["wallet_profile"] is None
    # Juste sous la moitié du volume du jour, avec un portefeuille ordinaire : rien.
    assert source.alerte(marche(volume_24h=60_200), MAINTENANT) is None


def test_alerte_si_le_portefeuille_est_atypique_meme_dans_un_gros_volume():
    source = Polymarket(get=faux_reseau([trade(30_000)], [activite(3)]))
    alerte = source.alerte(marche(volume_24h=10_000_000), MAINTENANT)
    assert alerte["wallet_profile"] == "Wallet récent / Wallet concentré"


def test_pas_d_alerte_pour_un_gros_ordre_ordinaire():
    source = Polymarket(get=faux_reseau([trade(30_000)], [activite(400, "0xA")]))
    assert source.alerte(marche(volume_24h=10_000_000), MAINTENANT) is None
