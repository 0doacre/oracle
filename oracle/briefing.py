"""Le fichier de sortie : un JSON compact, lu par le lecteur et par le point matinal.

Les clés sont en anglais et forment un contrat : ne pas les traduire.
"""

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from oracle.marche import Marche
from oracle.temps import a_paris

TAILLE_MAX_OCTETS = 25_000
MOTS_RESUME = 15
UNITES = {"kalshi": "contracts (~USD)", "polymarket": "USDC", "manifold": "mana (play money)"}
_ENTETES_REGLE = re.compile(r"^\s*(resolution criteria|resolution|description|rules?)\s*[:\-]?\s*", re.I)


# Une phrase qui dit comment le marché se résout. Mesuré sur 90 règles réelles :
# 3 commençaient par du contexte (« The 2028 US Presidential Election is scheduled
# to take place… »), la condition venant à la phrase suivante.
# Par ordre de préférence : « If no candidate achieves this, the top two contenders
# advance to a runoff » commence par « If » sans être la règle (vu sur Le Pen 2027).
_PHRASES_DE_RESOLUTION = [re.compile(r"\bresolv\w*", re.I), re.compile(r"\b(yes|no)\b", re.I),
                          re.compile(r"^if\b", re.I)]


def resumer_regle(texte: str, mots: int = MOTS_RESUME) -> str:
    """La première phrase qui parle de résolution (à défaut, la première phrase),
    coupée à `mots` mots."""
    texte = _ENTETES_REGLE.sub("", " ".join(texte.split()))
    # Fin de phrase = ponctuation après deux minuscules ou chiffres : « J.D. Vance »
    # et « U.S. House » ne coupent pas (vu sur un vrai relevé : « If J.D. »).
    phrases = re.split(r"(?<=[a-z0-9)]{2}[.!?])\s", texte)
    phrase = next((p for motif in _PHRASES_DE_RESOLUTION for p in phrases if motif.search(p)),
                  phrases[0])
    liste = phrase.split()
    if len(liste) > mots:
        return " ".join(liste[:mots]) + "…"
    return phrase


def nettoyer_titre(titre: str, longueur: int = 140) -> str:
    titre = " ".join(titre.split())
    return titre if len(titre) <= longueur else titre[: longueur - 1] + "…"


def vers_json(m: Marche, aujourd_hui: date) -> dict:
    return {
        "id": m.id,
        "source": m.source,
        "category": m.categorie,
        "title": nettoyer_titre(m.titre),
        "yes_prob": round(m.prob, 1),
        "delta_1h": m.delta_1h,
        "delta_6h": m.delta_6h,
        "delta_24h": m.delta_24h,
        "volume_total": round(m.volume_total, 2),
        "volume_24h": round(m.volume_24h, 2),
        "volume_ratio": m.ratio_volume,
        "end_date": m.fin,
        "days_left": m.jours_restants(aujourd_hui),
        "resolution_summary": resumer_regle(m.regle),
        "url": m.url,
        "score": m.score,
        "trade_alert": m.alerte,
    }


def construire(marches: list[Marche], total_scanne: int, erreurs: dict[str, str],
               maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    return {
        "meta": {
            "generated_at": maintenant.isoformat(timespec="seconds"),
            "total_scanned": total_scanne,
            "selected_count": len(marches),
            "volume_units": UNITES,
            "errors": erreurs,
        },
        "markets": [vers_json(m, a_paris(maintenant).date()) for m in marches],
    }


def serialiser(briefing: dict) -> str:
    """JSON compact sous TAILLE_MAX_OCTETS : retire les derniers marchés si besoin."""
    while True:
        texte = json.dumps(briefing, ensure_ascii=False, separators=(",", ":"))
        if len(texte.encode("utf-8")) <= TAILLE_MAX_OCTETS or not briefing["markets"]:
            return texte
        briefing["markets"].pop()
        briefing["meta"]["selected_count"] = len(briefing["markets"])


def ecrire(briefing: dict, chemin: str | Path) -> int:
    """Écriture atomique : le lecteur ou le LLM du matin ne lisent jamais un
    fichier à moitié écrit pendant le relevé de l'heure."""
    texte = serialiser(briefing)
    chemin = Path(chemin)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(texte, encoding="utf-8")
    os.replace(provisoire, chemin)
    return len(texte.encode("utf-8"))
