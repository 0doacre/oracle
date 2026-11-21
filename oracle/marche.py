"""Un marché de prédiction, ramené à la même forme quelle que soit sa source."""

from dataclasses import dataclass
from datetime import date


@dataclass
class Marche:
    source: str            # "kalshi", "polymarket", "manifold"
    id: str                # identifiant dans la source
    evenement: str         # regroupe les marchés d'une même question à plusieurs issues
    titre: str
    prob: float            # probabilité du OUI, de 0 à 100
    volume_total: float    # unité propre à la source (voir briefing.UNITES)
    volume_24h: float
    fin: str               # AAAA-MM-JJ, "" si inconnue
    url: str
    regle: str = ""        # règle de résolution brute
    categorie_source: str = ""
    nb_parieurs: int = 0   # connu pour Manifold seulement
    # Rempli au fil du traitement :
    categorie: str | None = None
    delta_1h: float | None = None
    delta_6h: float | None = None
    delta_24h: float | None = None
    ratio_volume: float | None = None   # volume 24 h ÷ sa médiane des jours précédents
    alerte: dict | None = None
    score: float = 0.0

    def jours_restants(self, aujourd_hui: date) -> int | None:
        """Jours avant l'échéance (0 = aujourd'hui), None si elle est inconnue."""
        try:
            return (date.fromisoformat(self.fin) - aujourd_hui).days
        except ValueError:
            return None
