"""Kalshi : marché de prédiction régulé (États-Unis), API publique en lecture.

Un « contrat » vaut 1 $ à l'échéance : les volumes sont des nombres de contrats,
proches d'un montant en dollars. Les prix sont donnés en dollars (0,00 à 1,00).
"""

import time
from datetime import datetime, timedelta, timezone

from oracle.http import get_json
from oracle.marche import Marche
from oracle.selection import ALERTE_MONTANT_MIN_USD, ALERTE_PART_MIN
from oracle.source import Source
from oracle.themes import CATEGORIES_SOURCE_EXCLUES

API = "https://api.elections.kalshi.com/trade-api/v2"
PAGES_MAX = 250            # ~22 800 événements ouverts mesurés : 114 pages de 200
PAUSE_ENTRE_PAGES_S = 0.1  # bien sous la limite publique de débit
ECART_MAX_FOURCHETTE = 0.10  # au-delà, le milieu achat/vente n'est pas fiable

SEUIL_GROS_ORDRE_USD = ALERTE_MONTANT_MIN_USD
PART_DOMINANTE = ALERTE_PART_MIN


def _f(valeur) -> float:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return 0.0


def probabilite(m: dict) -> float:
    """Milieu de la fourchette si elle est serrée, sinon dernier prix. En %."""
    achat, vente = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
    if achat > 0 and vente > 0 and vente - achat <= ECART_MAX_FOURCHETTE:
        return round((achat + vente) / 2 * 100, 1)
    return round(_f(m.get("last_price_dollars")) * 100, 1)


def vers_marche(evenement: dict, m: dict) -> Marche:
    titre = m.get("title") or evenement.get("title", "")
    sous_titre = (m.get("yes_sub_title") or "").strip()
    if len(evenement.get("markets", [])) > 1 and sous_titre and sous_titre.lower() not in titre.lower():
        titre = f"{titre} — {sous_titre}"
    serie = evenement.get("series_ticker") or m.get("event_ticker", "")
    return Marche(
        source="kalshi",
        id=m["ticker"],
        evenement=evenement.get("event_ticker", m["ticker"]),
        titre=titre,
        prob=probabilite(m),
        volume_total=_f(m.get("volume_fp")),
        volume_24h=_f(m.get("volume_24h_fp")),
        fin=(m.get("close_time") or "")[:10],
        url=f"https://kalshi.com/markets/{serie.lower()}",
        regle=m.get("rules_primary") or "",
        categorie_source=evenement.get("category", ""),
    )


class Kalshi(Source):
    nom = "kalshi"

    def __init__(self, get=get_json, pages_max: int = PAGES_MAX, pause=time.sleep):
        self.get, self.pages_max, self.pause = get, pages_max, pause
        self.total_scanne = 0

    def collecter(self) -> list[Marche]:
        marches, curseur = [], None
        for _ in range(self.pages_max):
            params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
            if curseur:
                params["cursor"] = curseur
            page = self.get(f"{API}/events", params)
            for e in page.get("events", []):
                for m in e.get("markets", []):
                    self.total_scanne += 1
                    if e.get("category") in CATEGORIES_SOURCE_EXCLUES:
                        continue
                    if m.get("market_type") == "binary" and m.get("status") == "active":
                        marches.append(vers_marche(e, m))
            curseur = page.get("cursor")
            if not curseur:
                break
            self.pause(PAUSE_ENTRE_PAGES_S)
        return marches

    def alerte(self, marche: Marche, maintenant: datetime | None = None) -> dict | None:
        """Le plus gros ordre des dernières 24 h, s'il dépasse le seuil."""
        maintenant = maintenant or datetime.now(timezone.utc)
        depuis = int((maintenant - timedelta(hours=24)).timestamp())
        reponse = self.get(f"{API}/markets/trades",
                           {"ticker": marche.id, "limit": 1000, "min_ts": depuis})
        return plus_gros_ordre(reponse.get("trades", []), marche.volume_24h, depuis)


def plus_gros_ordre(trades: list[dict], volume_24h: float, depuis_ts: int = 0) -> dict | None:
    meilleur, montant_max = None, 0.0
    for t in trades:
        quand = t.get("created_time", "")
        if depuis_ts and _horodatage(quand) < depuis_ts:
            continue
        cote = "YES" if t.get("taker_side") == "yes" else "NO"
        prix = _f(t.get("yes_price_dollars" if cote == "YES" else "no_price_dollars"))
        montant = _f(t.get("count_fp")) * prix
        if montant > montant_max:
            meilleur, montant_max = t, montant
    if meilleur is None or montant_max < SEUIL_GROS_ORDRE_USD:
        return None
    # Un gros ordre noyé dans un marché très actif n'a rien d'atypique
    # (mesures dans oracle/selection.py).
    part = _f(meilleur.get("count_fp")) / volume_24h if volume_24h else 1.0
    if part < PART_DOMINANTE:
        return None
    return {
        "amount_usd": round(montant_max, 2),
        "side": "YES" if meilleur.get("taker_side") == "yes" else "NO",
        "share_24h": round(min(part, 1.0), 3),
        "block_trade": bool(meilleur.get("is_block_trade")),
        "tx_timestamp": meilleur.get("created_time", ""),
    }


def _horodatage(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0
