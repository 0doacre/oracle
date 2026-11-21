"""Un relevé complet : collecte, filtre, historique, score, alertes, briefing."""

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from oracle import briefing
from oracle.dossiers import Suivi, charger as charger_suivi
from oracle.historique import Historique
from oracle.http import ErreurReseau
from oracle.selection import NB_MARCHES, PAR_DOSSIER, choisir, est_joue, est_liquide, scorer, thematiser
from oracle.source import Source, collecter_tout
from oracle.temps import a_paris

NB_CANDIDATS_ALERTE = 60  # un appel « trades » par candidat : on n'interroge pas les 1 000


def relever(sources: list[Source], historique: Historique,
            maintenant: datetime | None = None, journal=print,
            suivi: Suivi | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    ts = int(maintenant.timestamp())
    par_nom = {s.nom: s for s in sources}

    resultats, erreurs = collecter_tout(sources)
    for nom, err in erreurs.items():
        journal(f"[{nom}] en panne : {err}")
    tous = [m for lot in resultats.values() for m in lot]
    total = sum(s.total_scanne for s in sources)

    liquides = [m for m in thematiser(tous, suivi) if est_liquide(m)]
    for m in liquides:
        historique.annoter(m, ts)
    historique.enregistrer(liquides, ts)
    vivants = [m for m in liquides if not est_joue(m)]
    journal(f"{total} marchés lus, {len(liquides)} dans les thèmes et liquides, "
            f"{len(vivants)} encore ouverts")

    aujourd_hui = a_paris(maintenant).date()
    scorer(vivants, aujourd_hui)
    _chercher_alertes(choisir(vivants, NB_CANDIDATS_ALERTE), par_nom, maintenant, erreurs)
    scorer(vivants, aujourd_hui)
    choisis = choisir(vivants, NB_MARCHES, PAR_DOSSIER, groupe=lambda m: m.dossier)

    for m in choisis:
        completer = getattr(par_nom[m.source], "completer_regle", None)
        if completer and not m.regle:
            try:
                completer(m)
            except ErreurReseau as e:
                erreurs.setdefault(f"{m.source}:regles", str(e))
    return briefing.construire(choisis, total, erreurs, maintenant)


def _chercher_alertes(candidats, par_nom, maintenant, erreurs) -> None:
    for m in candidats:
        alerte = getattr(par_nom[m.source], "alerte", None)
        if not alerte:
            continue
        try:
            m.alerte = alerte(m, maintenant)
        except ErreurReseau as e:
            erreurs.setdefault(f"{m.source}:alertes", str(e))


def main(argv: list[str] | None = None) -> int:
    from oracle.sources.kalshi import Kalshi
    from oracle.sources.manifold import Manifold
    from oracle.sources.polymarket import Polymarket

    p = argparse.ArgumentParser(description="Relevé de l'oracle : écrit le briefing JSON.")
    p.add_argument("--sortie", default="briefing_oracle.json")
    p.add_argument("--base", default="oracle_state.db")
    p.add_argument("--pages-kalshi", type=int, default=None,
                   help="limite de pages Kalshi (essais rapides)")
    p.add_argument("--journal", default=None,
                   help="fichier où ajouter le compte rendu (tâche planifiée : pas de console)")
    args = p.parse_args(argv)
    journal = Journal(args.journal)

    kalshi = Kalshi() if args.pages_kalshi is None else Kalshi(pages_max=args.pages_kalshi)
    debut = time.monotonic()
    try:
        historique = Historique(args.base)
        try:
            donnees = relever([kalshi, Polymarket(), Manifold()], historique, journal=journal,
                              suivi=charger_suivi())
        finally:
            historique.fermer()
        taille = briefing.ecrire(donnees, args.sortie)
    except Exception:
        journal("ÉCHEC du relevé :\n" + traceback.format_exc())
        return 2
    meta = donnees["meta"]
    journal(f"{args.sortie} : {meta['selected_count']} marchés, {taille} octets, "
            f"{time.monotonic() - debut:.0f} s")
    return 1 if len(meta["errors"]) and not donnees["markets"] else 0


class Journal:
    """Écrit sur la console s'il y en a une (pythonw n'en a pas), et dans un
    fichier horodaté si demandé. Le fichier est tronqué au-delà de TAILLE_MAX."""

    TAILLE_MAX = 1_000_000

    def __init__(self, chemin: str | None = None):
        self.chemin = chemin

    def __call__(self, texte: str) -> None:
        if sys.stderr is not None:
            print(texte, file=sys.stderr)
        if not self.chemin:
            return
        quand = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if os.path.exists(self.chemin) and os.path.getsize(self.chemin) > self.TAILLE_MAX:
                os.replace(self.chemin, self.chemin + ".1")
            with open(self.chemin, "a", encoding="utf-8") as f:
                f.write(f"[{quand}] {texte}\n")
        except OSError:
            pass  # le journal ne doit jamais faire tomber le relevé
