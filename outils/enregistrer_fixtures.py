"""Enregistre de vraies réponses Kalshi et Manifold dans tests/fixtures/.

Seul script du dépôt qui appelle le réseau en dehors du collecteur. Les tests,
eux, ne lisent que ces fichiers. Relancer quand une API change de forme :

    python outils/enregistrer_fixtures.py [kalshi] [manifold] [polymarket]
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from oracle.http import get_json  # noqa: E402
from oracle.sources.kalshi import API as KALSHI  # noqa: E402
from oracle.sources.manifold import API as MANIFOLD  # noqa: E402
from oracle.sources.polymarket import DATA as POLY_DATA, GAMMA  # noqa: E402

FIXTURES = RACINE / "tests" / "fixtures"
PAR_CATEGORIE = 4  # événements gardés par catégorie Kalshi


# Le dépôt est public : aucune trace des personnes derrière les ordres ou les
# questions (pseudonymes, biographies, avatars, identifiants).
CHAMPS_PERSONNELS = {"name", "pseudonym", "bio", "profile_image", "profile_image_optimized",
                     "creatorId", "creatorUsername", "creatorName", "creatorAvatarUrl"}


def anonymiser(donnees, portefeuilles: dict | None = None):
    """Retire les champs personnels ; remplace chaque portefeuille par un alias
    stable (« 0xanonyme1 »…), et le nom d'auteur dans les URL Manifold."""
    portefeuilles = {} if portefeuilles is None else portefeuilles
    if isinstance(donnees, list):
        return [anonymiser(x, portefeuilles) for x in donnees]
    if not isinstance(donnees, dict):
        return donnees
    propre = {}
    for cle, valeur in donnees.items():
        if cle in CHAMPS_PERSONNELS:
            continue
        if cle == "proxy_wallet" and isinstance(valeur, str):
            valeur = portefeuilles.setdefault(valeur.lower(), f"0xanonyme{len(portefeuilles) + 1}")
        elif cle == "url" and isinstance(valeur, str) and "manifold.markets/" in valeur:
            parties = valeur.split("/")
            if len(parties) >= 5:
                parties[3] = "anonyme"
            valeur = "/".join(parties)
        propre[cle] = anonymiser(valeur, portefeuilles)
    return propre


def ecrire(nom: str, donnees) -> None:
    chemin = FIXTURES / nom
    donnees = anonymiser(donnees)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{nom} : {chemin.stat().st_size // 1024} Ko")


def kalshi() -> None:
    # Trois pages réelles, puis un échantillon varié : quelques événements par
    # catégorie, en préférant ceux qui ont du volume.
    evenements, curseur = [], None
    for _ in range(3):
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if curseur:
            params["cursor"] = curseur
        page = get_json(f"{KALSHI}/events", params)
        evenements += page["events"]
        curseur = page.get("cursor")

    def volume(e):
        return max((float(m.get("volume_fp") or 0) for m in e.get("markets", [])), default=0)

    par_cat: dict[str, list] = {}
    for e in sorted(evenements, key=volume, reverse=True):
        lot = par_cat.setdefault(e.get("category", "?"), [])
        if len(lot) < PAR_CATEGORIE:
            e["markets"] = e.get("markets", [])[:3]
            lot.append(e)
    echantillon = [e for lot in par_cat.values() for e in lot]
    ecrire("kalshi_events.json", {"events": echantillon, "cursor": ""})

    # Les transactions du marché le plus actif de l'échantillon.
    marche = max((m for e in echantillon for m in e["markets"]),
                 key=lambda m: float(m.get("volume_24h_fp") or 0))
    trades = get_json(f"{KALSHI}/markets/trades", {"ticker": marche["ticker"], "limit": 100})
    ecrire("kalshi_trades.json", trades)


def manifold() -> None:
    params = {"term": "", "sort": "24-hour-vol", "filter": "open",
              "contractType": "BINARY", "limit": 60}
    marches = get_json(f"{MANIFOLD}/search-markets", params)
    ecrire("manifold_search.json", marches)
    detail = get_json(f"{MANIFOLD}/market/{marches[0]['id']}")
    ecrire("manifold_market.json", detail)


def polymarket() -> None:
    evenements, curseur = [], None
    for _ in range(4):
        params = {"closed": "false", "limit": 500}
        if curseur:
            params["after_cursor"] = curseur
        page = get_json(f"{GAMMA}/events/keyset", params)
        evenements += page["events"]
        curseur = page.get("next_cursor")

    def volume(e):
        return float(e.get("volume24hr") or 0)

    par_etiquette: dict[str, list] = {}
    for e in sorted(evenements, key=volume, reverse=True):
        etiquette = ((e.get("tags") or [{}])[0]).get("label", "?")
        lot = par_etiquette.setdefault(etiquette, [])
        if len(lot) < 3 and len(par_etiquette) <= 20:
            e["markets"] = (e.get("markets") or [])[:3]
            lot.append(e)
    echantillon = [e for lot in par_etiquette.values() for e in lot]
    ecrire("polymarket_events.json", {"events": echantillon, "next_cursor": ""})

    # Les gros ordres du marché ouvert le plus actif de l'échantillon.
    marche = max((m for e in echantillon for m in e["markets"] if not m.get("closed")),
                 key=lambda m: float(m.get("volume24hr") or 0))
    seuil = 1_000
    trades = get_json(f"{POLY_DATA}/trades", {"condition": marche["conditionId"],
                                              "filterType": "CASH", "filterAmount": seuil,
                                              "limit": 100})
    montants = [t["size"] * t["price"] for t in trades["data"]]
    autres = sum(t["condition_id"] != marche["conditionId"] for t in trades["data"])
    print(f"  trades : {len(montants)}, plus petit {min(montants, default=0):.0f} $ "
          f"(filtre {seuil} $), autres marchés : {autres}")
    ecrire("polymarket_trades.json", trades)
    if trades["data"]:
        gros = max(trades["data"], key=lambda t: t["size"] * t["price"])
        activite = get_json(f"{POLY_DATA}/activity", {"user": gros["proxy_wallet"], "limit": 500})
        ecrire("polymarket_activity.json", activite)


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    quoi = sys.argv[1:] or ["kalshi", "manifold", "polymarket"]
    for nom in quoi:
        globals()[nom]()
