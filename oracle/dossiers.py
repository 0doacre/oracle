"""Les dossiers suivis (dossiers.toml, modifiable par l'utilisateur) : chaque marché
et chaque titre de presse y est rangé par mots-clés ; le bruit déclaré est écarté."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FICHIER = Path(__file__).resolve().parent.parent / "dossiers.toml"


@dataclass
class Dossier:
    nom: str
    motif: re.Pattern | None          # intitulés de marchés (anglais) ; None : actualité seule
    motif_actu: re.Pattern | None     # titres de presse : mots_fr + mots
    gdelt: str | None = None          # recherche GDELT, facultative

    @property
    def actualite_seule(self) -> bool:
        return self.motif is None


@dataclass
class Flux:
    nom: str
    url: str


@dataclass
class Suivi:
    dossiers: list[Dossier]
    bruit: re.Pattern | None
    flux: list[Flux] = field(default_factory=list)

    def est_du_bruit(self, titre: str) -> bool:
        return bool(self.bruit and self.bruit.search(titre))

    def attribuer(self, titre: str) -> str | None:
        """Le dossier de marchés qui a le plus de mots dans l'intitulé ; à égalité, le premier."""
        return _meilleur(titre, [(d.nom, d.motif) for d in self.dossiers if d.motif])

    def attribuer_actualite(self, titre: str) -> str | None:
        """Le dossier dont un titre de presse parle le plus ; à égalité, le premier."""
        return _meilleur(titre, [(d.nom, d.motif_actu) for d in self.dossiers if d.motif_actu])


def _meilleur(titre: str, candidats: list[tuple[str, re.Pattern]]) -> str | None:
    meilleur, max_touches = None, 0
    for nom, motif in candidats:
        touches = len(motif.findall(titre))
        if touches > max_touches:
            meilleur, max_touches = nom, touches
    return meilleur


def _motif(mots: list[str]) -> re.Pattern | None:
    if not mots:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(mots) + r")(?!\w)", re.IGNORECASE)


def depuis_texte(texte: str) -> Suivi:
    donnees = tomllib.loads(texte)
    dossiers = []
    for d in donnees.get("dossier", []):
        mots, mots_fr = d.get("mots", []), d.get("mots_fr", [])
        if mots or mots_fr:
            dossiers.append(Dossier(d["nom"], _motif(mots), _motif(mots_fr + mots), d.get("gdelt")))
    flux = [Flux(f["nom"], f["url"]) for f in donnees.get("actualite", {}).get("flux", [])]
    return Suivi(dossiers, _motif(donnees.get("bruit", {}).get("mots", [])), flux)


def charger(chemin: str | Path = FICHIER) -> Suivi:
    return depuis_texte(Path(chemin).read_text(encoding="utf-8"))
