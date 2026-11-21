"""Polymarket : marché de prédiction en USDC sur la blockchain Polygon.

Bloqué en France par un filtrage DNS (ANJ). La source ne le contourne pas : elle
marche si le poste utilise un autre résolveur DNS, sinon elle est notée en panne.

Pièges vérifiés sur les vraies API :
- `outcomes`, `outcomePrices` sont des chaînes JSON à décoder ;
- un événement ouvert contient des marchés déjà fermés ;
- `/v2/trades` ignore en silence un paramètre inconnu et renvoie alors d'autres
  marchés : le filtre par marché s'appelle `condition` ;
- la Data API v1 (sans `/v2`) répond 410.
"""

import json
import time
from datetime import datetime, timedelta, timezone

from oracle.http import get_json
from oracle.marche import Marche
from oracle.selection import ALERTE_MONTANT_MIN_USD, ALERTE_PART_MIN
from oracle.source import Source

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com/v2"
TAILLE_PAGE = 500
PAGES_MAX = 120             # ~18 000 événements ouverts mesurés : 36 pages de 500
PAUSE_ENTRE_PAGES_S = 0.1

# Étiquettes Polymarket rejetées d'office (paris sportifs, crypto à 5 ou 15 minutes…).
ETIQUETTES_EXCLUES = {"Sports", "Games", "Esports", "Crypto Prices", "Up or Down",
                      "5M", "15M", "Pop Culture", "Movies", "Music"}

SEUIL_GROS_ORDRE_USD = ALERTE_MONTANT_MIN_USD
PART_DOMINANTE = ALERTE_PART_MIN
HISTORIQUE_PORTEFEUILLE = 500   # activités lues ; en deçà, l'historique est complet
PORTEFEUILLE_RECENT_J = 30
PORTEFEUILLE_CONCENTRE = 0.5    # part de ses montants engagée sur ce seul marché


def _f(valeur) -> float:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return 0.0


def _liste(valeur) -> list:
    if isinstance(valeur, list):
        return valeur
    try:
        return json.loads(valeur or "[]")
    except (TypeError, ValueError):
        return []


def probabilite_oui(m: dict) -> float | None:
    """Prix du « Yes » en %, ou None si le marché n'est pas un Oui/Non."""
    issues, prix = _liste(m.get("outcomes")), _liste(m.get("outcomePrices"))
    if len(issues) != 2 or len(prix) != 2 or "Yes" not in issues:
        return None
    return round(_f(prix[issues.index("Yes")]) * 100, 1)


def vers_marche(evenement: dict, m: dict) -> Marche | None:
    prob = probabilite_oui(m)
    if prob is None or m.get("closed") or not m.get("conditionId"):
        return None
    etiquettes = [t.get("label", "") for t in evenement.get("tags") or []]
    return Marche(
        source="polymarket",
        id=m["conditionId"],
        evenement=str(evenement.get("id", m["conditionId"])),
        titre=m.get("question") or evenement.get("title", ""),
        prob=prob,
        volume_total=_f(m.get("volumeNum") or m.get("volume")),
        volume_24h=_f(m.get("volume24hr")),
        fin=(m.get("endDateIso") or m.get("endDate") or "")[:10],
        url=f"https://polymarket.com/event/{evenement.get('slug', '')}",
        regle=m.get("description") or "",
        categorie_source=etiquettes[0] if etiquettes else "",
    )


class Polymarket(Source):
    nom = "polymarket"

    def __init__(self, get=get_json, pages_max: int = PAGES_MAX, pause=time.sleep):
        self.get, self.pages_max, self.pause = get, pages_max, pause
        self.total_scanne = 0

    def collecter(self) -> list[Marche]:
        marches, curseur = [], None
        for _ in range(self.pages_max):
            params = {"closed": "false", "limit": TAILLE_PAGE}
            if curseur:
                params["after_cursor"] = curseur
            page = self.get(f"{GAMMA}/events/keyset", params)
            for e in page.get("events", []):
                etiquettes = {t.get("label") for t in e.get("tags") or []}
                for m in e.get("markets") or []:
                    self.total_scanne += 1
                    if etiquettes & ETIQUETTES_EXCLUES:
                        continue
                    marche = vers_marche(e, m)
                    if marche:
                        marches.append(marche)
            curseur = page.get("next_cursor")
            if not curseur:
                break
            self.pause(PAUSE_ENTRE_PAGES_S)
        return marches

    def alerte(self, marche: Marche, maintenant: datetime | None = None) -> dict | None:
        """Le plus gros ordre des 24 h, s'il est gros ET atypique : il pèse lourd
        dans le volume du jour, ou vient d'un portefeuille récent ou concentré."""
        maintenant = maintenant or datetime.now(timezone.utc)
        depuis = int((maintenant - timedelta(hours=24)).timestamp())
        reponse = self.get(f"{DATA}/trades", {
            "condition": marche.id, "filterType": "CASH",
            "filterAmount": SEUIL_GROS_ORDRE_USD, "limit": 100})
        ordre = plus_gros_ordre(reponse.get("data", []), marche.id, depuis)
        if ordre is None:
            return None
        part = ordre["amount_usd"] / marche.volume_24h if marche.volume_24h else 1.0
        activite = self.get(f"{DATA}/activity", {
            "user": ordre["wallet"], "limit": HISTORIQUE_PORTEFEUILLE})
        profil = profil_portefeuille(activite.get("data", []), marche.id, maintenant)
        if part < PART_DOMINANTE and not profil:
            return None
        return {
            "amount_usd": ordre["amount_usd"],
            "side": ordre["side"],
            "share_24h": round(min(part, 1.0), 3),
            "wallet_profile": profil,
            "tx_timestamp": ordre["tx_timestamp"],
        }


def plus_gros_ordre(trades: list[dict], condition: str, depuis_ts: int = 0) -> dict | None:
    """Le plus gros ordre du marché depuis `depuis_ts`, au-dessus du seuil."""
    meilleur, montant_max = None, 0.0
    for t in trades:
        if t.get("condition_id") != condition:   # garde-fou : voir le piège du paramètre
            continue
        if depuis_ts and int(_f(t.get("timestamp"))) < depuis_ts:
            continue
        montant = _f(t.get("size")) * _f(t.get("price"))
        if montant > montant_max:
            meilleur, montant_max = t, montant
    if meilleur is None or montant_max < SEUIL_GROS_ORDRE_USD:
        return None
    issue = meilleur.get("outcome", "")
    achat = meilleur.get("side") == "BUY"
    # Acheter du « Yes » ou vendre du « No » parie sur OUI.
    oui = (issue == "Yes") == achat
    return {
        "amount_usd": round(montant_max, 2),
        "side": "YES" if oui else "NO",
        "wallet": meilleur.get("proxy_wallet", ""),
        "tx_timestamp": datetime.fromtimestamp(int(_f(meilleur.get("timestamp"))),
                                               tz=timezone.utc).isoformat(),
    }


def profil_portefeuille(activites: list[dict], condition: str,
                        maintenant: datetime) -> str | None:
    """« Wallet récent », « Wallet concentré », les deux, ou None."""
    if not activites:
        return None
    traits = []
    complet = len(activites) < HISTORIQUE_PORTEFEUILLE
    premiere = min(int(_f(a.get("timestamp"))) for a in activites)
    age_j = (maintenant.timestamp() - premiere) / 86_400
    if complet and age_j < PORTEFEUILLE_RECENT_J:
        traits.append("Wallet récent")
    total = sum(_f(a.get("usdc_size")) for a in activites)
    ici = sum(_f(a.get("usdc_size")) for a in activites if a.get("condition_id") == condition)
    if total and ici / total >= PORTEFEUILLE_CONCENTRE:
        traits.append("Wallet concentré")
    return " / ".join(traits) or None
