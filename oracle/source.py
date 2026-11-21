"""Interface commune à toutes les sources de l'oracle."""

from abc import ABC, abstractmethod


class Source(ABC):
    """Une source collecte des éléments (des `Marche` pour les marchés de prédiction)."""

    nom: str = ""
    total_scanne: int = 0

    @abstractmethod
    def collecter(self) -> list:
        """Renvoie les éléments lus, avant le filtrage thématique."""


def collecter_tout(sources: list[Source]) -> tuple[dict[str, list], dict[str, str]]:
    """Interroge chaque source. Une source en panne n'empêche pas les autres :
    son erreur est rendue à part, par nom de source."""
    noms = [s.nom for s in sources]
    for source in sources:
        if not source.nom:
            raise ValueError(f"{type(source).__name__} n'a pas de nom")
    doublons = {n for n in noms if noms.count(n) > 1}
    if doublons:
        raise ValueError(f"deux sources portent le nom {sorted(doublons)[0]!r}")

    resultats: dict[str, list] = {}
    erreurs: dict[str, str] = {}
    for source in sources:
        try:
            resultats[source.nom] = source.collecter()
        except Exception as e:  # noqa: BLE001 — une source ne fait pas tomber le relevé
            erreurs[source.nom] = f"{type(e).__name__}: {e}"
    return resultats, erreurs
