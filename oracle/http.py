"""Lecture d'API et de flux publics : délai, reprises légères, respect des limites de débit."""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

# gzip : Polymarket l'exige au-delà de 50 événements par page (sinon 406).
ENTETES = {"User-Agent": "oracle/0.1 (lecteur personnel)", "Accept-Encoding": "gzip"}
REPRISES = 3
DELAI_S = 20


class ErreurReseau(Exception):
    """L'API n'a pas répondu correctement après toutes les reprises."""


def _corps(reponse) -> bytes:
    brut = reponse.read()
    if (reponse.headers.get("Content-Encoding") or "").lower() == "gzip":
        return gzip.decompress(brut)
    return brut


def get_octets(url: str, params: dict | None = None, *, accepte: str = "*/*",
               pause=time.sleep, decoder=lambda b: b):
    """GET qui renvoie le corps (décodé par `decoder`). Reprend sur 429, 5xx,
    coupure réseau, et sur un corps que `decoder` refuse."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    derniere = None
    for essai in range(REPRISES):
        try:
            requete = urllib.request.Request(url, headers={**ENTETES, "Accept": accepte})
            with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
                return decoder(_corps(reponse))
        except urllib.error.HTTPError as e:
            derniere = e
            if e.code != 429 and e.code < 500:
                detail = _corps(e).decode("utf-8", "replace")[:300]
                raise ErreurReseau(f"{e.code} sur {url} : {detail}") from e
            attente = float(e.headers.get("Retry-After") or 2 ** (essai + 1))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            derniere = e                      # ValueError : JSON ou XML illisible
            attente = 2 ** (essai + 1)
        if essai < REPRISES - 1:
            pause(min(attente, 30))
    raise ErreurReseau(f"échec après {REPRISES} essais sur {url} : {derniere}")


def get_json(url: str, params: dict | None = None, *, pause=time.sleep):
    """GET qui renvoie le JSON décodé."""
    return get_octets(url, params, accepte="application/json", pause=pause, decoder=json.loads)
