"""Rédige le point matinal (points/AAAA-MM-JJ.md) à partir du briefing. Voir AGENTS.md.

    python point_matinal.py [--briefing briefing_oracle.json] [--modele ...]
"""

import sys

from oracle.point_matinal import main

if __name__ == "__main__":
    sys.exit(main())
