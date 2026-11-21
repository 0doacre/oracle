import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def charger(nom: str):
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


class FauxReseau:
    """Remplace oracle.http.get_json : répond depuis les fixtures, note les appels."""

    def __init__(self, reponses: dict[str, object] | None = None):
        # Fragment d'URL → réponse ; le premier fragment contenu dans l'URL gagne.
        self.reponses = reponses or {
            "gamma-api.polymarket.com/events/keyset": charger("polymarket_events.json"),
            "data-api.polymarket.com/v2/trades": charger("polymarket_trades.json"),
            "data-api.polymarket.com/v2/activity": charger("polymarket_activity.json"),
            "kalshi.com/trade-api/v2/events": charger("kalshi_events.json"),
            "kalshi.com/trade-api/v2/markets/trades": charger("kalshi_trades.json"),
            "manifold.markets/v0/search-markets": charger("manifold_search.json"),
            "manifold.markets/v0/market/": charger("manifold_market.json"),
        }
        self.appels: list[tuple[str, dict | None]] = []

    def __call__(self, url: str, params: dict | None = None):
        self.appels.append((url, params))
        for fin, reponse in self.reponses.items():
            if fin in url:
                return json.loads(json.dumps(reponse))  # copie : chaque appel est neuf
        raise AssertionError(f"appel réseau imprévu : {url}")


@pytest.fixture(autouse=True)
def pas_de_reseau(monkeypatch):
    """Garde-fou : tout appel réseau réel pendant les tests échoue bruyamment."""
    def interdit(*a, **k):
        raise AssertionError("appel réseau réel pendant un test")
    monkeypatch.setattr("urllib.request.urlopen", interdit)


@pytest.fixture
def reseau():
    return FauxReseau()
