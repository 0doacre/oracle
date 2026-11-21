"""Lance un relevé de l'oracle. Voir AGENTS.md.

    python collecteur.py [--sortie briefing_oracle.json] [--base oracle_state.db]
"""

import sys

from oracle.collecteur import main

if __name__ == "__main__":
    sys.exit(main())
