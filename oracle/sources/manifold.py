"""Manifold : marchés de prédiction en monnaie fictive (mana). Signal plus faible
que Kalshi, mais beaucoup de questions sur l'IA, la France et l'Europe."""

from datetime import datetime, timedelta, timezone

from oracle.http import ErreurReseau, get_json
from oracle.marche import Marche
from oracle.source import Source

API = "https://api.manifold.markets/v0"
TRIS = ("24-hour-vol", "liquidity")  # les actifs du jour, et les gros marchés calmes


def _date(ms) -> str:
    """Sans fromtimestamp : sous Windows, il refuse les dates très lointaines
    (Errno 22), et certains marchés ferment en l'an 9999 ou au-delà."""
    if not ms:
        return ""
    try:
        quand = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
    except OverflowError:
        return ""
    return quand.strftime("%Y-%m-%d")


def vers_marche(m: dict) -> Marche:
    return Marche(
        source="manifold",
        id=m["id"],
        evenement=m["id"],
        titre=m.get("question", ""),
        prob=round(float(m.get("probability") or 0) * 100, 1),
        volume_total=float(m.get("volume") or 0),
        volume_24h=float(m.get("volume24Hours") or 0),
        fin=_date(m.get("closeTime")),
        url=m.get("url") or f"https://manifold.markets/market/{m.get('slug', '')}",
        nb_parieurs=int(m.get("uniqueBettorCount") or 0),
    )


class Manifold(Source):
    nom = "manifold"

    def __init__(self, get=get_json):
        self.get = get
        self.total_scanne = 0

    def collecter(self) -> list[Marche]:
        vus: dict[str, Marche] = {}
        derniere_erreur, reussis = None, 0
        for tri in TRIS:
            params = {"term": "", "sort": tri, "filter": "open",
                      "contractType": "BINARY", "limit": 1000}
            try:
                reponse = self.get(f"{API}/search-markets", params)
            except ErreurReseau as e:  # vu en vrai : 503 sur un tri, l'autre répond
                derniere_erreur = e
                continue
            reussis += 1
            for m in reponse:
                if m["id"] not in vus and not m.get("isResolved"):
                    vus[m["id"]] = vers_marche(m)
        if not reussis:
            raise derniere_erreur
        self.total_scanne = len(vus)
        return list(vus.values())

    def completer_regle(self, marche: Marche) -> None:
        """La recherche ne donne pas la règle : un appel par marché retenu."""
        detail = self.get(f"{API}/market/{marche.id}")
        marche.regle = detail.get("textDescription") or ""
