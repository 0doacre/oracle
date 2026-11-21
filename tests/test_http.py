import gzip
import io
import urllib.error

import pytest

from oracle import http


class Reponse(io.BytesIO):
    def __init__(self, corps: bytes, encodage: str | None = None):
        super().__init__(corps)
        self.headers = {"Content-Encoding": encodage} if encodage else {}


def brancher(monkeypatch, *reponses):
    suite = iter(reponses)
    vus = []

    def urlopen(requete, timeout):
        vus.append(requete)
        r = next(suite)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    return vus


def test_decompresse_une_reponse_gzip_et_la_demande(monkeypatch):
    vus = brancher(monkeypatch, Reponse(gzip.compress(b'{"a": 1}'), "gzip"))
    assert http.get_json("https://x", {"k": "v"}) == {"a": 1}
    assert vus[0].get_header("Accept-encoding") == "gzip"
    assert vus[0].full_url == "https://x?k=v"


def test_lit_une_reponse_non_compressee(monkeypatch):
    brancher(monkeypatch, Reponse(b"[1, 2]"))
    assert http.get_json("https://x") == [1, 2]


def test_reprend_apres_un_503(monkeypatch):
    erreur = urllib.error.HTTPError("https://x", 503, "indisponible", {}, io.BytesIO(b""))
    brancher(monkeypatch, erreur, Reponse(b"{}"))
    pauses = []
    assert http.get_json("https://x", pause=pauses.append) == {}
    assert pauses == [2]


def test_une_erreur_400_ne_reprend_pas_et_donne_le_detail(monkeypatch):
    corps = gzip.compress(b'{"error": "use condition"}')
    erreur = urllib.error.HTTPError("https://x", 400, "mauvais", {"Content-Encoding": "gzip"},
                                    io.BytesIO(corps))
    brancher(monkeypatch, erreur)
    with pytest.raises(http.ErreurReseau, match="use condition"):
        http.get_json("https://x", pause=lambda s: None)
