"""Lecture d'API JSON publiques : délai, reprises légères, respect des limites de débit."""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

# gzip : Polymarket l'exige au-delà de 50 événements par page (sinon 406).
ENTETES = {"User-Agent": "oracle/0.1", "Accept": "application/json", "Accept-Encoding": "gzip"}
REPRISES = 3
DELAI_S = 20


class ErreurReseau(Exception):
    """L'API n'a pas répondu correctement après toutes les reprises."""


def _corps(reponse) -> bytes:
    brut = reponse.read()
    if (reponse.headers.get("Content-Encoding") or "").lower() == "gzip":
        return gzip.decompress(brut)
    return brut


def get_json(url: str, params: dict | None = None, *, pause=time.sleep):
    """GET qui renvoie le JSON décodé. Reprend sur 429, 5xx et coupure réseau."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    derniere = None
    for essai in range(REPRISES):
        try:
            requete = urllib.request.Request(url, headers=ENTETES)
            with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
                return json.loads(_corps(reponse))
        except urllib.error.HTTPError as e:
            derniere = e
            if e.code != 429 and e.code < 500:
                detail = _corps(e).decode("utf-8", "replace")[:300]
                raise ErreurReseau(f"{e.code} sur {url} : {detail}") from e
            attente = float(e.headers.get("Retry-After") or 2 ** (essai + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            derniere = e
            attente = 2 ** (essai + 1)
        if essai < REPRISES - 1:
            pause(min(attente, 30))
    raise ErreurReseau(f"échec après {REPRISES} essais sur {url} : {derniere}")
