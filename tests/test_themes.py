import pytest

from oracle.themes import classer, est_exclu


@pytest.mark.parametrize("titre, attendu", [
    ("Will Macron dissolve the National Assembly?", "Politique France & G7"),
    ("Will the AfD win the most seats in the Bundestag?", "Droites radicales & mouvements identitaires"),
    ("Will Trump sign an executive order on tariffs?", "Politique USA"),
    ("Will China invade Taiwan before 2030?", "Géopolitique & Risques"),
    ("Will the Fed cut interest rates in December?", "Macro-finance, Énergie & IA"),
    ("Will OpenAI release GPT-6 this year?", "Macro-finance, Énergie & IA"),
    ("Will SpaceX land Starship on Mars before 2030?", "Gouvernance publique, Espace & Cyber"),
    ("Who will win the cooking contest?", None),
    ("Will Labour win the next New Zealand general election?", None),
])
def test_classe_dans_la_bonne_categorie(titre, attendu):
    assert classer(titre) == attendu


@pytest.mark.parametrize("titre", [
    "Europe heatwave",            # contient « eu »
    "Federation of chess",        # contient « fed »
    "Marseille mayor",            # contient « mars »
    "Said the owner",             # contient « ai »
])
def test_les_mots_courts_ne_touchent_pas_l_interieur_d_un_mot(titre):
    assert classer(titre) is None


def test_taiwan_reste_geopolitique_et_pas_ia():
    assert classer("Will the US issue a travel advisory for Taiwan?") == "Géopolitique & Risques"


@pytest.mark.parametrize("titre, categorie_source", [
    ("Who will win the NBA Finals?", ""),
    ("Bitcoin above $150k on Friday?", ""),
    ("Best Picture at the Oscars?", ""),
    ("Will Trump attend the game?", "Sports"),
    ("Will Powell say 'inflation'?", "Mentions"),
])
def test_le_bruit_est_exclu(titre, categorie_source):
    assert est_exclu(titre, categorie_source)


def test_la_politique_n_est_pas_exclue():
    assert not est_exclu("Will Trump win the 2028 election?", "Elections")
