"""Filtrage anti-bruit, score et choix des marchés du briefing."""

import bisect
import math
from datetime import date

from oracle.dossiers import Suivi
from oracle.marche import Marche
from oracle.themes import classer, est_exclu

# Volume total minimal, dans l'unité de chaque source (contrats Kalshi ≈ USD, mana).
SEUILS_VOLUME = {"kalshi": 50_000, "polymarket": 50_000, "manifold": 20_000}
PARIEURS_MIN = {"manifold": 30}
PROB_JOUEE = 97.0           # au-delà (ou en deçà de 100 - PROB_JOUEE), le marché est joué…
DELTA_REVEIL = 4.0          # …sauf s'il a bougé d'au moins 4 points en 24 h ou en 6 h,
DELTA_REVEIL_1H = 3.0       # …ou de 3 points en une heure

# « Ce qui se joue aujourd'hui » : ce qui bouge vite, ce qui s'échange plus que
# d'habitude, ce qui se décide bientôt.
# Un point en 1 h pèse autant que 3 points en 24 h ; en 6 h, autant que 1,5.
POIDS_HORIZON = {"delta_1h": 3.0, "delta_6h": 1.5, "delta_24h": 1.0}
PIC_VOLUME = 3.0            # volume 24 h au moins 3 fois sa médiane des jours précédents
ECHEANCE_IMMINENTE_J = 2    # se décide aujourd'hui, demain ou après-demain
ECHEANCE_PROCHE_J = 7
POIDS_SOURCE = {"kalshi": 1.0, "polymarket": 1.0, "manifold": 0.7}  # Manifold : monnaie fictive
# Un mouvement sur 1 h ou 6 h ne compte que sur un marché qui s'échange vraiment.
# Mesuré le 21/11 : Powell −4 pt en 1 h sur 1 722 $ échangés en 24 h, destitution
# −4 pt sur 1 508 $, appel Trump–Zelensky −5,5 pt sur 5 667 $ ; en face, bulle IA
# −6,3 pt sur 257 062 $. Le 24 h compte toujours : il s'est installé.
VOLUME_CONFIRMATION = {"kalshi": 20_000, "polymarket": 20_000, "manifold": 10_000}
NB_MARCHES = 25
PAR_EVENEMENT = 2           # une question à 30 candidats ne doit pas remplir le briefing
PAR_DOSSIER = 2             # places réservées à chaque dossier suivi qui a des candidats

# Alerte « gros ordre », commune aux sources qui donnent les transactions.
# Mesuré sur les 60 candidats d'un vrai relevé : 29 ordres ≥ 10 k$ ; 11 pesaient
# ≥ 25 % du volume 24 h, 6 ≥ 40 %, 2 ≥ 50 %. À 25 %, 12 marchés sur 25 du
# briefing portaient une alerte : elle ne signalait plus rien d'atypique.
ALERTE_MONTANT_MIN_USD = 10_000
ALERTE_PART_MIN = 0.5


def thematiser(marches: list[Marche], suivi: Suivi | None = None) -> list[Marche]:
    """Garde les marchés d'une des six catégories ou d'un dossier suivi, hors
    bruit (exclusions générales, puis bruit déclaré dans dossiers.toml)."""
    gardes = []
    for m in marches:
        if est_exclu(m.titre, m.categorie_source):
            continue
        if suivi and suivi.est_du_bruit(m.titre):
            continue
        m.categorie = classer(m.titre)
        m.dossier = suivi.attribuer(m.titre) if suivi else None
        if m.categorie or m.dossier:
            gardes.append(m)
    return gardes


def est_liquide(m: Marche) -> bool:
    return (m.volume_total >= SEUILS_VOLUME.get(m.source, 0)
            and m.nb_parieurs >= PARIEURS_MIN.get(m.source, 0))


def est_joue(m: Marche) -> bool:
    extreme = m.prob > PROB_JOUEE or m.prob < 100 - PROB_JOUEE
    reveil = (abs(m.delta_24h or 0) >= DELTA_REVEIL or abs(m.delta_6h or 0) >= DELTA_REVEIL
              or abs(m.delta_1h or 0) >= DELTA_REVEIL_1H)
    return extreme and not reveil


def horizons_confirmes(m: Marche) -> list[str]:
    """Les variations connues qui méritent d'être crues (voir VOLUME_CONFIRMATION)."""
    assez = m.volume_24h >= VOLUME_CONFIRMATION.get(m.source, 0)
    return [c for c in POIDS_HORIZON
            if getattr(m, c) is not None and (c == "delta_24h" or assez)]


def mouvement(m: Marche) -> float:
    """Amplitude du mouvement confirmé le plus marquant, à l'échelle « 24 h »."""
    return max((abs(getattr(m, c)) * POIDS_HORIZON[c] for c in horizons_confirmes(m)),
               default=0.0)


def est_pic_de_volume(m: Marche) -> bool:
    return m.ratio_volume is not None and m.ratio_volume >= PIC_VOLUME


def scorer(marches: list[Marche], aujourd_hui: date | None = None) -> None:
    """Score sur 100 environ : activité du jour (rang dans sa source), taille,
    mouvement récent, pic de volume, échéance proche, gros ordre. Les rangs
    rendent comparables des volumes en dollars et en mana."""
    aujourd_hui = aujourd_hui or date.today()
    par_source: dict[str, list[Marche]] = {}
    for m in marches:
        par_source.setdefault(m.source, []).append(m)
    for lot in par_source.values():
        rang_24h = _rangs(lot, lambda m: m.volume_24h)
        rang_total = _rangs(lot, lambda m: math.log10(m.volume_total + 1))
        for m in lot:
            score = 35 * rang_24h[id(m)] + 20 * rang_total[id(m)]
            score += 3 * min(mouvement(m), 10)
            if est_pic_de_volume(m):
                score += 10
            jours = m.jours_restants(aujourd_hui)
            if jours is not None and 0 <= jours <= ECHEANCE_IMMINENTE_J:
                score += 15
            elif jours is not None and 0 <= jours <= ECHEANCE_PROCHE_J:
                score += 8
            if m.alerte:
                score += 15
            m.score = round(score * POIDS_SOURCE.get(m.source, 1.0), 2)


def _rangs(lot: list[Marche], cle) -> dict[int, float]:
    """Rang centile de 0 (le plus faible) à 1 (le plus fort). Des valeurs égales
    ont le même rang : la part des autres marchés strictement en dessous."""
    if len(lot) == 1:
        return {id(lot[0]): 1.0}
    valeurs = sorted(cle(m) for m in lot)
    return {id(m): bisect.bisect_left(valeurs, cle(m)) / (len(lot) - 1) for m in lot}


def choisir(marches: list[Marche], n: int = NB_MARCHES, par_groupe: int = 0,
            groupe=lambda m: m.categorie) -> list[Marche]:
    """Les n meilleurs scores, deux par événement au plus. Avec `par_groupe`,
    chaque groupe (catégorie, ou dossier suivi) qui a des candidats reçoit d'abord
    ce nombre de places ; un groupe None n'a pas de réserve. Mesuré sur un vrai
    relevé : le score seul donnait 23 places sur 25 aux États-Unis et à la macro."""
    tries = sorted(marches, key=lambda m: m.score, reverse=True)
    choisis, par_evenement, pris = [], {}, set()

    def prendre(m: Marche) -> bool:
        cle = (m.source, m.evenement)
        if id(m) in pris or par_evenement.get(cle, 0) >= PAR_EVENEMENT:
            return False
        par_evenement[cle] = par_evenement.get(cle, 0) + 1
        pris.add(id(m))
        choisis.append(m)
        return True

    if par_groupe:
        comptes: dict[str, int] = {}
        for m in tries:
            if len(choisis) == n:
                break
            g = groupe(m)
            if g is not None and comptes.get(g, 0) < par_groupe and prendre(m):
                comptes[g] = comptes.get(g, 0) + 1
    for m in tries:
        if len(choisis) == n:
            break
        prendre(m)
    return sorted(choisis, key=lambda m: m.score, reverse=True)
