import pytest

from oracle.source import Source, collecter_tout


class SourceFactice(Source):
    def __init__(self, nom: str, elements: list, erreur: Exception | None = None):
        self.nom = nom
        self._elements = elements
        self._erreur = erreur

    def collecter(self) -> list:
        if self._erreur:
            raise self._erreur
        return self._elements


def test_regroupe_par_nom_de_source():
    a = SourceFactice("a", [{"id": 1}])
    b = SourceFactice("b", [])
    assert collecter_tout([a, b]) == ({"a": [{"id": 1}], "b": []}, {})


def test_une_source_en_panne_n_empeche_pas_les_autres():
    a = SourceFactice("a", [], erreur=TimeoutError("trop long"))
    b = SourceFactice("b", [1])
    resultats, erreurs = collecter_tout([a, b])
    assert resultats == {"b": [1]}
    assert erreurs == {"a": "TimeoutError: trop long"}


def test_refuse_deux_sources_du_meme_nom():
    with pytest.raises(ValueError, match="deux sources"):
        collecter_tout([SourceFactice("a", []), SourceFactice("a", [])])


def test_refuse_une_source_sans_nom():
    with pytest.raises(ValueError, match="pas de nom"):
        collecter_tout([SourceFactice("", [])])


def test_une_source_doit_implementer_collecter():
    class Incomplete(Source):
        nom = "x"

    with pytest.raises(TypeError):
        Incomplete()
