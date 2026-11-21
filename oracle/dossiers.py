"""Les dossiers suivis (dossiers.toml, modifiable par l'utilisateur) : chaque marché
y est rangé par mots-clés, et le bruit déclaré y est écarté."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

FICHIER = Path(__file__).resolve().parent.parent / "dossiers.toml"


@dataclass
class Dossier:
    nom: str
    motif: re.Pattern


@dataclass
class Suivi:
    dossiers: list[Dossier]
    bruit: re.Pattern | None

    def est_du_bruit(self, titre: str) -> bool:
        return bool(self.bruit and self.bruit.search(titre))

    def attribuer(self, titre: str) -> str | None:
        """Le dossier qui a le plus de mots dans le titre ; à égalité, le premier."""
        meilleur, max_touches = None, 0
        for d in self.dossiers:
            touches = len(d.motif.findall(titre))
            if touches > max_touches:
                meilleur, max_touches = d.nom, touches
        return meilleur


def _motif(mots: list[str]) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(mots) + r")(?!\w)", re.IGNORECASE)


def depuis_texte(texte: str) -> Suivi:
    donnees = tomllib.loads(texte)
    dossiers = [Dossier(d["nom"], _motif(d["mots"])) for d in donnees.get("dossier", [])
                if d.get("mots")]
    mots_bruit = donnees.get("bruit", {}).get("mots", [])
    return Suivi(dossiers, _motif(mots_bruit) if mots_bruit else None)


def charger(chemin: str | Path = FICHIER) -> Suivi:
    return depuis_texte(Path(chemin).read_text(encoding="utf-8"))
