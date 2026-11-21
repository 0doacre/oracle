"""Écrit le point dans le site et l'envoie par mail à 7 h, 12 h et 19 h. Voir AGENTS.md.

    python diffuser.py [--briefing ...] [--site site] [--etat etat/envois.json] [--forcer]
"""

import sys

from oracle.envoi import main

if __name__ == "__main__":
    sys.exit(main())
