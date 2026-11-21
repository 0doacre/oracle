from datetime import datetime, timezone

import pytest
from conftest import charger

from oracle.http import ErreurReseau

from oracle.sources import kalshi, manifold
from oracle.sources.kalshi import Kalshi, plus_gros_ordre, probabilite
from oracle.sources.manifold import Manifold


def test_kalshi_lit_les_vrais_evenements_et_rejette_le_sport(reseau):
    source = Kalshi(get=reseau, pause=lambda s: None)
    marches = source.collecter()
    evenements = charger("kalshi_events.json")["events"]
    total = sum(len(e["markets"]) for e in evenements)
    assert source.total_scanne == total
    assert marches, "aucun marché lu dans la fixture"
    assert all(m.categorie_source not in ("Sports", "Entertainment") for m in marches)
    assert all(0 <= m.prob <= 100 for m in marches)
    assert all(m.url.startswith("https://kalshi.com/markets/") for m in marches)


def test_kalshi_suit_le_curseur_jusqu_a_la_fin():
    pages = iter([{"events": [], "cursor": "a"}, {"events": [], "cursor": "b"},
                  {"events": [], "cursor": ""}])
    appels = []

    def get(url, params=None):
        appels.append(params.get("cursor"))
        return next(pages)

    Kalshi(get=get, pause=lambda s: None).collecter()
    assert appels == [None, "a", "b"]


def test_kalshi_s_arrete_a_la_limite_de_pages():
    appels = []
    Kalshi(get=lambda u, p=None: appels.append(1) or {"events": [], "cursor": "x"},
           pages_max=3, pause=lambda s: None).collecter()
    assert len(appels) == 3


def test_probabilite_prend_le_milieu_d_une_fourchette_serree():
    assert probabilite({"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44",
                        "last_price_dollars": "0.10"}) == 42.0


def test_probabilite_prend_le_dernier_prix_si_la_fourchette_est_large():
    assert probabilite({"yes_bid_dollars": "0.10", "yes_ask_dollars": "0.60",
                        "last_price_dollars": "0.33"}) == 33.0


def test_titre_d_un_marche_a_plusieurs_issues_porte_le_candidat():
    e = {"event_ticker": "E", "series_ticker": "S", "title": "Next PM?",
         "markets": [{}, {}]}
    m = kalshi.vers_marche(e, {"ticker": "E-A", "title": "Who will be next PM?",
                               "yes_sub_title": "Alice"})
    assert m.titre == "Who will be next PM? — Alice"
    assert m.url == "https://kalshi.com/markets/s"


def test_gros_ordre_sur_les_vraies_transactions(monkeypatch):
    trades = charger("kalshi_trades.json")["trades"]
    montants = []
    for t in trades:
        cote = "yes" if t["taker_side"] == "yes" else "no"
        montants.append(float(t["count_fp"]) * float(t[f"{cote}_price_dollars"]))
    plus_gros = max(montants)
    # Avec un seuil juste sous le plus gros ordre, l'alerte sort et porte ce montant.
    monkeypatch.setattr(kalshi, "SEUIL_GROS_ORDRE_USD", plus_gros - 0.01)
    alerte = plus_gros_ordre(trades, volume_24h=1)
    assert alerte["amount_usd"] == round(plus_gros, 2)
    assert alerte["side"] in ("YES", "NO")
    monkeypatch.setattr(kalshi, "SEUIL_GROS_ORDRE_USD", plus_gros + 0.01)
    assert plus_gros_ordre(trades, volume_24h=1) is None


def test_gros_ordre_calcule_le_montant_avec_le_prix_du_cote_pris():
    t = {"count_fp": "20000", "taker_side": "no", "yes_price_dollars": "0.90",
         "no_price_dollars": "0.10", "created_time": "2026-11-21T10:00:00Z"}
    # 20 000 contrats NON à 0,10 $ = 2 000 $ : sous le seuil de 10 000 $.
    assert plus_gros_ordre([t], volume_24h=25_000) is None
    t["taker_side"] = "yes"
    alerte = plus_gros_ordre([t], volume_24h=25_000)
    assert alerte["amount_usd"] == 18_000
    assert alerte["share_24h"] == 0.8


def test_un_gros_ordre_noye_dans_le_volume_du_jour_n_alerte_pas():
    t = {"count_fp": "20000", "taker_side": "yes", "yes_price_dollars": "0.90",
         "created_time": "2026-11-21T10:00:00Z"}
    # 18 000 $, mais 20 000 contrats sur 1 000 000 échangés : 2 %.
    assert plus_gros_ordre([t], volume_24h=1_000_000) is None
    assert plus_gros_ordre([t], volume_24h=40_000) is not None   # 50 % : limite incluse
    assert plus_gros_ordre([t], volume_24h=40_100) is None       # 49,9 %


def test_gros_ordre_ignore_les_transactions_de_plus_de_24h():
    t = {"count_fp": "50000", "taker_side": "yes", "yes_price_dollars": "0.50",
         "created_time": "2026-11-19T10:00:00Z"}
    depuis = int(datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp())
    assert plus_gros_ordre([t], 100_000, depuis) is None


def test_manifold_dedoublonne_les_deux_tris(reseau):
    source = Manifold(get=reseau)
    marches = source.collecter()
    uniques = {m["id"] for m in charger("manifold_search.json")}
    assert len(marches) == len(uniques) == source.total_scanne
    assert len([a for a in reseau.appels if "search-markets" in a[0]]) == 2
    m = marches[0]
    assert m.url.startswith("https://manifold.markets/")
    assert len(m.fin) == 10 and 0 <= m.prob <= 100


def test_manifold_survit_a_un_tri_en_panne(reseau):
    def get(url, params=None):
        if params and params.get("sort") == "liquidity":
            raise ErreurReseau("503")
        return reseau(url, params)

    assert Manifold(get=get).collecter()


def test_manifold_echoue_si_tous_les_tris_tombent():
    def get(url, params=None):
        raise ErreurReseau("503")

    with pytest.raises(ErreurReseau):
        Manifold(get=get).collecter()


def test_manifold_supporte_une_date_de_fin_tres_lointaine():
    # Cas réel : un marché qui ferme après l'an 3000 faisait tomber toute la source.
    assert manifold._date(32_503_680_000_000) == "3000-01-01"
    assert manifold._date(10 ** 20) == ""
    assert manifold._date(None) == ""
    assert manifold._date(1_798_847_940_000) == "2027-01-01"


def test_manifold_complete_la_regle_depuis_le_detail(reseau):
    source = Manifold(get=reseau)
    m = source.collecter()[0]
    source.completer_regle(m)
    assert m.regle == charger("manifold_market.json")["textDescription"]
